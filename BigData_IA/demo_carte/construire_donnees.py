"""
construire_donnees.py — Prépare toutes les données de la carte (à lancer une fois).

    py construire_donnees.py        (depuis le dossier IA/demo_carte, compter quelques minutes)

Ce que fait le script, dans l'ordre :
  1. Les CONTOURS : on part des 48 580 IRIS de l'IGN et on les « fusionne »
     (dissolve) pour obtenir les communes, puis les départements, puis les régions.
  2. Les RÉSULTATS : voix par bureau (ton Parquet 2022), regroupées par
     commune, département et région (GROUP BY).
  3. Les ZONES DE BUREAUX : aucun fichier ne donne le contour d'un bureau de vote.
     On le fabrique : on prend le centre des adresses de ses électeurs, puis
     on découpe chaque commune en « cellules de Voronoï » (chaque morceau de
     commune est attribué au bureau dont le centre est le plus proche).
  4. Les LIEUX DE VOTE : l'adresse de chaque bureau (école, mairie...) est
     géolocalisée par le service de l'IGN (data.geopf.fr), une seule fois :
     le résultat est gardé dans cache/lieux_geocodes.csv.
  5. L'INDEX DES ADRESSES : pour la recherche « où vote mon ami ? », les 16 millions
     d'adresses d'électeurs, compactées, un fichier par département.
  6. L'EXPORT : un fichier .js par niveau (et par département pour les niveaux
     fins), lus par la page carte.html.

Métropole uniquement (les contours IRIS d'outre-mer sont dans d'autres projections).
"""

import io
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely

ICI = Path(__file__).parent
ELECTION = ICI.parent.parent / "ELECTION"
RESULTATS = ICI.parent / "data" / "2022_pres_t1_results.parquet"
IRIS = next((ICI.parent / "data" / "raw" / "contours-iris").rglob("*LAMB93_FXX-2022/CONTOURS-IRIS.shp"))
SORTIE = ICI / "donnees"
CACHE_LIEUX = ICI / "cache" / "lieux_geocodes.csv"
GEOCODEUR = "https://data.geopf.fr/geocodage/search/csv"

# Les candidats, classés de gauche à droite (l'ordre sert aussi pour les couleurs dans carte.js)
CANDIDATS = [
    "Nathalie ARTHAUD", "Philippe POUTOU", "Fabien ROUSSEL", "Jean-Luc MÉLENCHON",
    "Anne HIDALGO", "Yannick JADOT", "Jean LASSALLE", "Emmanuel MACRON",
    "Valérie PÉCRESSE", "Nicolas DUPONT-AIGNAN", "Marine LE PEN", "Éric ZEMMOUR",
]

# Simplification des contours, en mètres : plus on est loin, plus on peut simplifier
TOLERANCE = {"regions": 1500, "departements": 600, "communes": 60, "bureaux": 15}

DEBUT = time.time()


def etape(message):
    print(f"[{time.time() - DEBUT:6.1f} s] {message}", flush=True)


# =============================================================================
# 1. Les contours
# =============================================================================

def construire_contours():
    etape("Lecture des contours IRIS...")
    iris = gpd.read_file(IRIS, columns=["INSEE_COM", "NOM_COM"])  # Lambert 93, en mètres

    etape(f"Fusion de {len(iris)} IRIS en communes...")
    communes = iris.dissolve(by="INSEE_COM", aggfunc={"NOM_COM": "first"}).reset_index()
    communes = communes.rename(columns={"INSEE_COM": "code", "NOM_COM": "nom"})
    communes["dep"] = communes["code"].str[:2]

    etape(f"Fusion de {len(communes)} communes en départements...")
    deps_ref = pd.read_csv(ELECTION / "v_departement_2026.csv", dtype=str)
    departements = communes.dissolve(by="dep").reset_index()[["dep", "geometry"]]
    departements = departements.merge(deps_ref[["DEP", "REG", "LIBELLE"]], left_on="dep", right_on="DEP")
    departements = departements.rename(columns={"dep": "code", "LIBELLE": "nom", "REG": "reg"})

    etape("Fusion des départements en régions...")
    regs_ref = pd.read_csv(ELECTION / "v_region_2026.csv", dtype=str)
    regions = departements.dissolve(by="reg").reset_index()[["reg", "geometry"]]
    regions = regions.merge(regs_ref[["REG", "LIBELLE"]], left_on="reg", right_on="REG")
    regions = regions.rename(columns={"reg": "code", "LIBELLE": "nom"})

    return (communes[["code", "nom", "dep", "geometry"]],
            departements[["code", "nom", "reg", "geometry"]],
            regions[["code", "nom", "geometry"]])


# =============================================================================
# 2. Les résultats
# =============================================================================

def charger_resultats():
    """Un tableau par bureau, avec le code commune « géographique ».

    Piège : dans les résultats, Paris, Lyon et Marseille sont UNE seule commune
    (75056, 69123, 13055), alors que les contours IGN les découpent par
    arrondissement (75101...75120). Le fichier des bureaux du REU donne
    l'arrondissement de chaque bureau : on s'en sert de pont.
    """
    etape("Lecture des résultats et du fichier des bureaux (REU)...")
    bv = pd.read_parquet(RESULTATS, columns=["id_brut_miom", "code_departement", "code_commune",
                                             "libelle_commune", "code_bv", "inscrits", "votants",
                                             "exprimes"] + CANDIDATS)
    bv = bv[bv["exprimes"] > 0]

    reu = pd.read_csv(ELECTION / "table-bv-reu.csv", dtype=str,
                      usecols=["id_brut_reu", "code_commune", "id_brut_miom"])
    reu = reu.dropna().drop_duplicates("id_brut_miom")
    reu = reu.rename(columns={"code_commune": "commune_geo"})

    bv = bv.merge(reu, on="id_brut_miom", how="left")
    bv["commune_geo"] = bv["commune_geo"].fillna(bv["code_commune"])
    return bv


def agreger(bv, colonne):
    """GROUP BY sur une colonne : on additionne les voix, les inscrits, les votants."""
    return bv.groupby(colonne)[["inscrits", "votants", "exprimes"] + CANDIDATS].sum()


# =============================================================================
# 3. Les zones de bureaux (Voronoï)
# =============================================================================

def lire_adresses():
    """Les adresses des électeurs : 1,8 Go lu avec 3 colonnes seulement."""
    etape("Lecture des adresses (1,8 Go, 3 colonnes)...")
    adresses = pd.read_csv(ELECTION / "table-adresses-reu.csv", engine="pyarrow",
                           usecols=["id_brut_bv_reu", "longitude", "latitude"])
    return adresses.dropna()


def centres_des_bureaux(adresses):
    """Le « centre » de chaque bureau = la médiane des positions de ses adresses.

    La médiane plutôt que la moyenne : quelques adresses mal géolocalisées
    (à 50 km) ne déplacent pas le centre.
    """
    etape(f"{len(adresses):,} adresses -> centre de chaque bureau...".replace(",", " "))
    return adresses.groupby("id_brut_bv_reu")[["longitude", "latitude"]].median()


def construire_bureaux(bv, communes, centres):
    """Découpe chaque commune en zones, une par bureau de vote."""
    bv = bv.merge(centres, left_on="id_brut_reu", right_index=True, how="inner").reset_index(drop=True)
    points = gpd.GeoDataFrame(bv, geometry=gpd.points_from_xy(bv["longitude"], bv["latitude"]),
                              crs="EPSG:4326").to_crs(communes.crs)

    contour = communes.set_index("code")["geometry"]
    zones = []
    etape(f"Voronoï dans {points['commune_geo'].nunique()} communes...")
    for code, groupe in points.groupby("commune_geo"):
        if code not in contour.index:
            continue
        poly = contour[code]
        # On ne garde que les bureaux dont le centre tombe bien dans la commune
        groupe = groupe[groupe.within(poly)]
        if len(groupe) == 0:
            continue
        if len(groupe) == 1:
            zones.append((groupe.index[0], poly))
            continue
        # Deux bureaux au même endroit : on les écarte d'un mètre pour que Voronoï les distingue
        xy = shapely.get_coordinates(groupe.geometry.values)
        xy = xy + np.random.default_rng(0).uniform(-1, 1, xy.shape)
        cellules = shapely.voronoi_polygons(shapely.multipoints(xy), extend_to=poly)
        cellules = shapely.get_parts(cellules)
        # Chaque cellule contient exactement un point : on retrouve à quel bureau elle appartient
        arbre = shapely.STRtree(shapely.points(xy))
        for cellule in cellules:
            proches = arbre.query(cellule, predicate="contains")
            if len(proches):
                zone = shapely.intersection(cellule, poly)
                if not zone.is_empty:
                    zones.append((groupe.index[proches[0]], zone))

    index, geometries = zip(*zones)
    bureaux = gpd.GeoDataFrame(bv.loc[list(index)], geometry=list(geometries), crs=communes.crs)
    bureaux["dep"] = bureaux["commune_geo"].str[:2]
    return bureaux


# =============================================================================
# 4. Les lieux de vote (géocodage IGN, mis en cache)
# =============================================================================

def geocoder_lieux(reu):
    """Envoie les adresses des lieux de vote au géocodeur de l'IGN, par paquets.

    Ce sont des adresses publiques (écoles, mairies...), aucune donnée personnelle.
    Le service renvoie le même CSV avec des colonnes en plus : longitude, latitude,
    result_score (confiance de 0 à 1), result_type (numéro, rue, commune...).
    """
    entree = reu[["id_brut_miom", "adresse_lieu", "code_commune"]].copy()
    morceaux = []
    for debut in range(0, len(entree), 5000):
        paquet = entree.iloc[debut:debut + 5000]
        etape(f"  géocodage {debut + len(paquet)} / {len(entree)}...")
        reponse = requests.post(
            GEOCODEUR,
            files={"data": ("lieux.csv", paquet.to_csv(index=False).encode("utf-8"))},
            data={"columns": "adresse_lieu", "citycode": "code_commune"},
            timeout=600,
        )
        reponse.raise_for_status()
        morceaux.append(pd.read_csv(io.StringIO(reponse.text), dtype=str))
    resultat = pd.concat(morceaux)
    CACHE_LIEUX.parent.mkdir(exist_ok=True)
    resultat.to_csv(CACHE_LIEUX, index=False)
    return resultat


def lieux_des_bureaux(centres):
    """Pour chaque bureau : le nom du lieu, son adresse, et la position du « X »."""
    etape("Lieux de vote...")
    reu = pd.read_csv(ELECTION / "table-bv-reu.csv", dtype=str,
                      usecols=["id_brut_reu", "code_commune", "libelle_reu", "num_voie_reu",
                               "voie_reu", "cp_reu", "commune_reu", "id_brut_miom"])
    reu = reu.dropna(subset=["id_brut_miom"]).drop_duplicates("id_brut_miom").fillna("")
    for col in ["num_voie_reu", "voie_reu", "libelle_reu", "commune_reu"]:
        reu[col] = reu[col].str.strip().replace(".", "")
    reu["adresse_lieu"] = (reu["num_voie_reu"] + " " + reu["voie_reu"]).str.strip()
    # Pas de rue ? On tente le nom du lieu (« mairie », « salle des fêtes »...)
    reu["adresse_lieu"] = reu["adresse_lieu"].where(reu["adresse_lieu"] != "", reu["libelle_reu"])

    geo = pd.read_csv(CACHE_LIEUX, dtype=str) if CACHE_LIEUX.exists() else geocoder_lieux(reu)
    geo = geo[["id_brut_miom", "longitude", "latitude", "result_score", "result_type",
               "result_label", "result_citycode"]]
    reu = reu.merge(geo, on="id_brut_miom", how="left")

    # On fait confiance au géocodeur seulement s'il a trouvé un numéro ou une rue,
    # avec un score correct, et dans la bonne commune.
    fiable = (
        reu["result_type"].isin(["housenumber", "street", "locality"])
        & (pd.to_numeric(reu["result_score"], errors="coerce") >= 0.45)
        & (reu["result_citycode"] == reu["code_commune"])
    )
    reu["x"] = pd.to_numeric(reu["longitude"], errors="coerce").where(fiable)
    reu["y"] = pd.to_numeric(reu["latitude"], errors="coerce").where(fiable)
    reu["precis"] = fiable

    # Sinon, le X va au centre des adresses des électeurs (position approximative)
    centres = centres.rename(columns={"longitude": "cx", "latitude": "cy"})
    reu = reu.merge(centres, left_on="id_brut_reu", right_index=True, how="left")
    reu["x"] = reu["x"].fillna(reu["cx"])
    reu["y"] = reu["y"].fillna(reu["cy"])

    # Textes affichés : « Ecole elementaire » et « 28 Rue Cambon 75001 Paris »
    reu["lieu"] = reu["libelle_reu"].str.capitalize()
    adresse_brute = (reu["adresse_lieu"] + " " + reu["cp_reu"] + " " + reu["commune_reu"].str.title()).str.strip()
    reu["adresse"] = reu["result_label"].where(fiable, adresse_brute).fillna(adresse_brute)

    etape(f"  {fiable.mean():.0%} des lieux de vote localisés précisément")
    return reu.set_index("id_brut_miom")[["lieu", "adresse", "x", "y", "precis"]]


# =============================================================================
# 5. L'index des adresses (pour la recherche)
# =============================================================================

def exporter_index_adresses(adresses, bv, lieux):
    """Un fichier par département : toutes les adresses d'électeurs, et leur bureau.

    Format compact : les coordonnées en entiers (degrés x 100 000, soit ~1 m),
    triées par bureau, et stockées en DIFFÉRENCE avec le point précédent
    (des petits nombres prennent moins de place qu'un grand nombre répété).
    """
    etape("Index des adresses pour la recherche...")
    pont = bv[["id_brut_reu", "id_brut_miom", "commune_geo"]].dropna()
    adr = adresses.merge(pont, left_on="id_brut_bv_reu", right_on="id_brut_reu", how="inner")
    adr["x"] = (adr["longitude"] * 1e5).round().astype("int64")
    adr["y"] = (adr["latitude"] * 1e5).round().astype("int64")
    adr = adr.drop_duplicates(["id_brut_miom", "x", "y"])
    adr["dep"] = adr["commune_geo"].str[:2]
    etape(f"  {len(adr):,} adresses distinctes".replace(",", " "))

    taille = 0
    for dep, groupe in adr.groupby("dep"):
        groupe = groupe.sort_values(["id_brut_miom", "x"])
        comptes = groupe.groupby("id_brut_miom", sort=False).size()
        fiches = []
        for code in comptes.index:
            if code in lieux.index:
                l = lieux.loc[code]
                fiches.append([code, l["lieu"], l["adresse"],
                               round(float(l["x"]), 5) if pd.notna(l["x"]) else None,
                               round(float(l["y"]), 5) if pd.notna(l["y"]) else None,
                               bool(l["precis"])])
            else:
                fiches.append([code, "", "", None, None, False])
        donnees = {
            "bureaux": fiches,
            "n": comptes.tolist(),
            "dx": np.diff(groupe["x"].to_numpy(), prepend=0).tolist(),
            "dy": np.diff(groupe["y"].to_numpy(), prepend=0).tolist(),
        }
        texte = json.dumps(donnees, ensure_ascii=False, separators=(",", ":"))
        fichier = SORTIE / "adresses" / f"{dep}.js"
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(f'CARTE.recevoir("adresses","{dep}",{texte});\n', encoding="utf-8")
        taille += fichier.stat().st_size
    print(f"  adresses : {taille / 1e6:.1f} Mo")


# =============================================================================
# 6. L'export vers la carte
# =============================================================================

def proprietes(ligne):
    """Ce que la carte doit savoir d'une zone : gagnant, % de chacun, participation."""
    voix = np.array([ligne[c] for c in CANDIDATS], dtype=float)
    exprimes = ligne["exprimes"]
    pct = np.round(voix / exprimes * 100, 1) if exprimes else np.zeros(len(CANDIDATS))
    props = {
        "g": int(voix.argmax()),                       # index du candidat arrivé en tête
        "p": pct.tolist(),                             # % de chaque candidat
        "e": int(exprimes),
        "t": round(ligne["votants"] / ligne["inscrits"] * 100, 1) if ligne["inscrits"] else 0,
    }
    if "lieu" in ligne and pd.notna(ligne["x"]):       # bureaux seulement : le lieu de vote et son X
        props.update({"l": ligne["lieu"], "a": ligne["adresse"], "px": round(float(ligne["x"]), 5),
                      "py": round(float(ligne["y"]), 5), "pr": bool(ligne["precis"])})
    return props


def simplifier(geometries, tolerance):
    """Alléger les contours sans créer de trous entre zones voisines."""
    try:
        return shapely.coverage_simplify(geometries, tolerance)
    except Exception:
        return shapely.simplify(geometries, tolerance, preserve_topology=True)


def exporter(gdf, niveau, nom_fichier, cle):
    """Écrit un fichier .js : CARTE.recevoir("niveau", "cle", {geojson});"""
    gdf = gdf[~gdf.geometry.is_empty].copy()
    gdf["geometry"] = simplifier(gdf.geometry.values, TOLERANCE[niveau])
    gdf = gdf.to_crs("EPSG:4326")
    gdf["geometry"] = shapely.set_precision(gdf.geometry.values, 0.00001)  # ~1 m

    features = []
    for _, ligne in gdf.iterrows():
        if ligne.geometry is None or ligne.geometry.is_empty:
            continue
        props = proprietes(ligne)
        props["c"] = ligne["code"]
        props["n"] = ligne["nom"]
        features.append({"type": "Feature", "properties": props,
                         "geometry": json.loads(shapely.to_geojson(ligne.geometry))})

    collection = {"type": "FeatureCollection", "features": features}
    fichier = SORTIE / nom_fichier
    fichier.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
    fichier.write_text(f'CARTE.recevoir("{niveau}","{cle}",{texte});\n', encoding="utf-8")
    return len(features), fichier.stat().st_size


def main():
    communes, departements, regions = construire_contours()
    bv = charger_resultats()

    # Résultats agrégés, collés à chaque contour par leur code (merge)
    res_com = agreger(bv, "commune_geo")
    res_dep = agreger(bv, "code_departement")
    deps_ref = pd.read_csv(ELECTION / "v_departement_2026.csv", dtype=str)
    bv = bv.merge(deps_ref[["DEP", "REG"]], left_on="code_departement", right_on="DEP", how="left")
    res_reg = agreger(bv, "REG")

    communes = communes.merge(res_com, left_on="code", right_index=True, how="inner")
    departements = departements.merge(res_dep, left_on="code", right_index=True, how="inner")
    regions = regions.merge(res_reg, left_on="code", right_index=True, how="inner")
    etape(f"Contours avec résultats : {len(regions)} régions, {len(departements)} départements, "
          f"{len(communes)} communes")

    adresses = lire_adresses()
    centres = centres_des_bureaux(adresses)
    bureaux = construire_bureaux(bv, communes, centres)
    lieux = lieux_des_bureaux(centres)
    bureaux = bureaux.merge(lieux, left_on="id_brut_miom", right_index=True, how="left")
    bureaux["code"] = bureaux["id_brut_miom"]
    bureaux["nom"] = bureaux["libelle_commune"] + " - bureau " + bureaux["code_bv"]
    etape(f"{len(bureaux)} zones de bureaux construites")

    etape("Export...")
    print("  régions      :", exporter(regions, "regions", "regions.js", "FR"))
    n, taille = exporter(departements, "departements", "departements.js", "FR")
    print("  départements :", n, taille)

    # Pour chaque département : sa « boîte » (bbox), afin que la carte sache
    # quels fichiers charger selon la zone affichée à l'écran.
    boites = departements.to_crs("EPSG:4326").set_index("code").bounds.round(4)
    (SORTIE / "boites.js").write_text(
        "CARTE.boites=" + json.dumps({c: list(b) for c, b in boites.iterrows()}) + ";\n",
        encoding="utf-8")

    total_c = total_b = 0
    for dep in departements["code"]:
        nc, tc = exporter(communes[communes["dep"] == dep], "communes", f"communes/{dep}.js", dep)
        nb, tb = exporter(bureaux[bureaux["dep"] == dep], "bureaux", f"bureaux/{dep}.js", dep)
        total_c += tc
        total_b += tb
    print(f"  communes : {total_c / 1e6:.1f} Mo, bureaux : {total_b / 1e6:.1f} Mo")
    exporter_index_adresses(adresses, bv, lieux)
    etape("Terminé.")


if __name__ == "__main__":
    main()
