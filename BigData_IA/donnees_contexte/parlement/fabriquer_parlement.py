"""
fabriquer_parlement.py — Les députés et sénateurs en exercice, et les sénatoriales, en Parquet (+ les photos officielles).

    py fabriquer_parlement.py            (tables + photos manquantes ; ~5 min la 1re fois pour les photos)

Sources, dans brut/ :
    AMO10.json.zip / AMO10/        Assemblée nationale (data.assemblee-nationale.fr) : députés, groupes (et leur couleur), place dans l'hémicycle
    ODSEN_GENERAL.csv              Sénat (data.senat.fr) : sénateurs, groupe, circonscription
    senatoriales_2017.xlsx, senatoriales_2023.xlsx   ministère de l'Intérieur (data.gouv.fr) : candidats, voix, grands électeurs

Sorties (ici) : deputes.parquet, senateurs.parquet, senatoriales_scrutins/participation/resultats.parquet
Photos : le_grand_depouillement/data/photos/an/<id>.jpg et data/photos/senat/<matricule>.jpg
"""
import glob
import io
import json
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
BRUT = ICI / "brut"
PHOTOS = ICI.parent.parent / "le_grand_depouillement" / "data" / "photos"
NAVIGATEUR = "LeGrandDepouillement/1.0 (appli d'apprentissage, usage personnel)"


def texte(x):
    return x.get("#text") if isinstance(x, dict) else x


# --- Assemblée nationale ------------------------------------------------------------------------
groupes = {}
for f in glob.glob(str(BRUT / "AMO10" / "json" / "organe" / "*.json")):
    o = json.load(open(f, encoding="utf-8"))["organe"]
    if o.get("codeType") == "GP" and not (o.get("viMoDe") or {}).get("dateFin"):
        groupes[o["uid"]] = (o.get("libelleAbrev"), o.get("libelle"), o.get("couleurAssociee"))
deputes = []
for f in glob.glob(str(BRUT / "AMO10" / "json" / "acteur" / "*.json")):
    a = json.load(open(f, encoding="utf-8"))["acteur"]
    uid = texte(a["uid"])
    ec = a["etatCivil"]
    mandats = a["mandats"]["mandat"]
    mandats = mandats if isinstance(mandats, list) else [mandats]
    d = {"id": uid, "civ": ec["ident"]["civ"], "prenom": ec["ident"]["prenom"], "nom": ec["ident"]["nom"],
         "naissance": (ec.get("infoNaissance") or {}).get("dateNais"), "profession": (a.get("profession") or {}).get("libelleCourant")}
    for m in mandats:
        if m.get("dateFin"):
            continue
        if m["typeOrgane"] == "ASSEMBLEE":
            lieu = (m.get("election") or {}).get("lieu") or {}
            d.update(place=(m.get("mandature") or {}).get("placeHemicycle"), departement=lieu.get("departement"),
                     num_departement=lieu.get("numDepartement"), circo=lieu.get("numCirco"), region=lieu.get("region"))
        if m["typeOrgane"] == "GP":
            g = groupes.get(m["organes"]["organeRef"], (None, None, None))
            d.update(groupe=g[0], groupe_libelle=g[1], couleur=g[2])
    deputes.append(d)
deputes = pd.DataFrame(deputes)
deputes["place"] = pd.to_numeric(deputes["place"], errors="coerce").astype("Int64")
deputes["photo"] = "an/" + deputes["id"].str.replace("PA", "", regex=False) + ".jpg"
deputes.to_parquet(ICI / "deputes.parquet", index=False)
print(f"députés : {len(deputes)} · groupes : {deputes['groupe'].value_counts().to_dict()}")

# --- Sénat ----------------------------------------------------------------------------------------
lignes = "".join(l for l in open(BRUT / "ODSEN_GENERAL.csv", encoding="latin-1") if not l.startswith("%"))
s = pd.read_csv(io.StringIO(lignes))
s = s[s["État"] == "ACTIF"].rename(columns={"Matricule": "matricule", "Qualité": "civ", "Nom usuel": "nom", "Prénom usuel": "prenom",
                                             "Date naissance": "naissance", "Groupe politique": "groupe", "Circonscription": "circonscription",
                                             "Description de la profession": "profession", "Fonction au Bureau du Sénat": "fonction"})


def slug(t):
    t = "".join(c for c in unicodedata.normalize("NFD", str(t).lower()) if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() else "_" for c in t)


s["adresse_photo"] = [f"https://www.senat.fr/senimg/{slug(n)}_{slug(p)}{m.lower()}_carre.jpg" for n, p, m in zip(s["nom"], s["prenom"], s["matricule"])]
s["photo"] = "senat/" + s["matricule"] + ".jpg"
s["naissance"] = s["naissance"].str[:10]
senateurs = s[["matricule", "civ", "prenom", "nom", "naissance", "groupe", "circonscription", "profession", "fonction", "photo", "adresse_photo"]]
senateurs.to_parquet(ICI / "senateurs.parquet", index=False)
print(f"sénateurs : {len(senateurs)} · groupes : {senateurs['groupe'].value_counts().to_dict()}")


# --- Les photos (seulement celles qui manquent ; 2 téléchargements à la fois) ----------------------
def telecharger(adresse_fichier):
    adresse, fichier = adresse_fichier
    if fichier.exists():
        return True
    fichier.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(urllib.request.Request(adresse, headers={"User-Agent": NAVIGATEUR}), timeout=15) as r:
            fichier.write_bytes(r.read())
        time.sleep(0.2)
        return True
    except Exception:
        return False


travail = [(f"https://www2.assemblee-nationale.fr/static/tribun/17/photos/carre/{p[3:-4]}.jpg", PHOTOS / p) for p in deputes["photo"]]
travail += [(a, PHOTOS / p) for a, p in zip(senateurs["adresse_photo"], senateurs["photo"])]
with ThreadPoolExecutor(2) as pool:
    ok = list(pool.map(telecharger, travail))
print(f"photos : {sum(ok)} / {len(ok)} (manquantes : {[str(t[1].name) for t, o in zip(travail, ok) if not o][:10]})")


# --- Sénatoriales : au format de la méga base (un « bureau » = le collège d'un département) ---------
def colonnes_candidats(df):
    """Les colonnes répétées (candidat 1, 2, …) → une ligne par candidat."""
    lignes = []
    for _, r in df.iterrows():
        i = 1
        while f"Voix {i}" in r.index:
            if pd.notna(r.get(f"Voix {i}")):
                nom = r.get(f"Nom candidat {i}")
                tete = f"{r.get(f'Prénom candidat {i}')} {nom}" if pd.notna(nom) else r.get(f"Libellé abrégé de liste {i}")
                nuance = r.get(f"Nuance liste {i}") if pd.notna(r.get(f"Nuance liste {i}")) else r.get(f"Nuance candidat {i}")
                lignes.append((r["dep"], tete, nuance, int(r[f"Voix {i}"])))
            i += 1
    return lignes


def colonnes_2017(df, prop):
    lignes = []
    suffixes = [""] + [f".{k}" for k in range(1, 60)]
    for _, r in df.iterrows():
        for sx in suffixes:
            v = r.get("Voix" + sx)
            if v is None or pd.isna(v):
                continue
            if prop:
                tete, nuance = r.get("Nom Tête de Liste" + sx), r.get("Nuance Liste" + sx)
            else:
                tete, nuance = f"{r.get('Prénom' + sx)} {r.get('Nom' + sx)}", r.get("Nuance" + sx)
            lignes.append((r["dep"], tete, nuance, int(v)))
    return lignes


def code_dep(x):
    x = str(x).strip()
    return x.zfill(2) if x.isdigit() and len(x) < 3 else x


scrutins, participation, resultats = [], [], []
for an, fichier in [(2017, "senatoriales_2017.xlsx"), (2023, "senatoriales_2023.xlsx")]:
    x = pd.ExcelFile(BRUT / fichier)
    feuilles = {"t1": [], "t2": []}
    for nom in x.sheet_names:
        if "lu" in nom.lower():
            continue
        entete = 0 if an == 2023 else (3 if "PROP" in nom else 2)
        df = x.parse(nom, header=entete).dropna(subset=["Inscrits"])
        df["dep"] = df["Code département" if an == 2023 else "Code du département"].map(code_dep)
        tour = "t2" if "T2" in nom.upper() else "t1"
        prop = "PROP" in nom.upper()
        lignes = colonnes_candidats(df) if an == 2023 else colonnes_2017(df, prop)
        feuilles[tour].append((df, lignes))
    for tour, morceaux in feuilles.items():
        if not morceaux:
            continue
        sc = f"{an}_sena_{tour}"
        scrutins.append((sc, "sena", "Sénatoriales", an, int(tour[1]), f"{an}-09-{24 if an == 2017 else 24}",
                         f"Sénatoriales {an} – {'1er' if tour == 't1' else '2nd'} tour"))
        for df, lignes in morceaux:
            for _, r in df.iterrows():
                participation.append((sc, r["dep"] + "_SEN", "SEN", r["dep"], int(r["Inscrits"]), int(r["Abstentions"]), int(r["Votants"]),
                                      float(r["Blancs"]) if pd.notna(r.get("Blancs")) else None, int(r["Nuls"]) if pd.notna(r.get("Nuls")) else 0,
                                      int(r["Exprimés"])))
            resultats += [(sc, dep + "_SEN", qui, nuance, voix) for dep, qui, nuance, voix in lignes]
sc = pd.DataFrame(scrutins, columns=["scrutin", "type", "type_libelle", "annee", "tour", "date", "libelle"])
sc["date"] = pd.to_datetime(sc["date"])
sc.to_parquet(ICI / "senatoriales_scrutins.parquet", index=False)
p = pd.DataFrame(participation, columns=["scrutin", "id_brut_miom", "code_bv", "code_departement", "inscrits", "abstentions", "votants",
                                         "blancs", "nuls", "exprimes"]).drop_duplicates(["scrutin", "id_brut_miom"])
p.to_parquet(ICI / "senatoriales_participation.parquet", index=False)
r = pd.DataFrame(resultats, columns=["scrutin", "id_brut_miom", "qui", "nuance", "voix"])
r.to_parquet(ICI / "senatoriales_resultats.parquet", index=False)
print(f"sénatoriales : {p.groupby('scrutin').size().to_dict()} collèges · {len(r)} lignes de résultats")
