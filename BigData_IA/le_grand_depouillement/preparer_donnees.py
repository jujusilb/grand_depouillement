"""
preparer_donnees.py — Rassemble TOUTES les données du Grand Dépouillement dans un seul fichier : data/depouillement.duckdb

    py preparer_donnees.py       (une seule fois, ~2 minutes ; à relancer si les sources changent)

Ensuite, le dossier le_grand_depouillement/ se suffit à lui-même : on peut le copier sur un autre PC.

Sources (lues, jamais modifiées), dans BigData_IA/ :
    demo_megabase/megabase.duckdb           les 56 scrutins par bureau de vote (scrutins, participation, resultats)
    design_appli/pistes/geo_data.js         le découpage : régions … circonscriptions, cantons, intercommunalités, bureaux
    donnees_contexte/contexte_communes.parquet          revenus, chômage, diplômes par commune
    donnees_contexte/economie/economie_mois.parquet     euro, franc, baril, essence, gazole, moral, inflation, chômage, Big Mac
    donnees_contexte/economie/veille_scrutins.parquet   les mêmes, la veille de chaque scrutin
    donnees_contexte/listes/candidats_listes.parquet    toutes les listes et tous les colistiers
    donnees_contexte/referendums/referendums_*.parquet  les référendums de 1992, 2000 et 2005 (fabriquer_referendums.py)
    donnees_contexte/historique_cage_piketty/historique_*.parquet  1793 → 1997 par commune (fabriquer_historique.py)
    donnees_contexte/populations/populations.parquet    population municipale par commune, 1999 et 2006 → 2023 (Insee)
    donnees_contexte/rne/rne_*.parquet                  le Répertoire national des élus en 2020-01, 2020-12, 2026-08
    donnees_contexte/elus_2014/elus_municipaux_2014.parquet   les conseillers municipaux élus en 2014 (sans leur liste)
    donnees_contexte/sieges_2026/sieges_2026.parquet    les sièges à pourvoir en 2026 : conseil municipal et conseil communautaire
    demo_carte/donnees/                     les contours des régions, départements, communes et bureaux (2022)
Et dans PROJET/election/ :
    table-adresses-reu.csv, table-bv-reu.csv   les 16 millions d'adresses du répertoire électoral et leur bureau de vote
                                                → data/adresses.parquet (refait seulement si les CSV sont plus récents)
"""

import json
import re
from pathlib import Path

import duckdb
import pandas as pd

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
DATA = ICI / "data"
DATA.mkdir(exist_ok=True)
SORTIE = DATA / "depouillement.duckdb"
TEMP = DATA / "depouillement_en_cours.duckdb"

MEGABASE = RACINE / "demo_megabase" / "megabase.duckdb"
GEO_JS = RACINE / "design_appli" / "pistes" / "geo_data.js"
CONTEXTE = RACINE / "donnees_contexte"
CONTOURS = RACINE / "demo_carte" / "donnees"
ADRESSES_REU = RACINE.parent / "election" / "table-adresses-reu.csv"
BUREAUX_REU = RACINE.parent / "election" / "table-bv-reu.csv"
ADRESSES = DATA / "adresses.parquet"


def lire_js(chemin):
    """Les fichiers .js de données : du JSON entouré d'un peu de JavaScript."""
    texte = chemin.read_text(encoding="utf-8")
    return json.loads(texte[texte.index("{"): texte.rindex("}") + 1])


def arrondir(coords, n):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], n), round(coords[1], n)]
    return [arrondir(c, n) for c in coords]


def contours(niveau, fichier, n):
    """Les contours d'un fichier : une ligne par zone (code, nom, géométrie en JSON, coordonnées arrondies)."""
    d = lire_js(fichier)
    lignes = []
    for f in d.get("features", []):
        g = f.get("geometry") or {}
        if not g.get("coordinates"):
            continue
        p = f["properties"]
        lignes.append((niveau, p.get("c"), p.get("n"), g["type"], json.dumps(arrondir(g["coordinates"], n), separators=(",", ":"))))
    return lignes


if TEMP.exists():
    TEMP.unlink()
con = duckdb.connect(str(TEMP))

# 1. La méga base : les trois tables, telles quelles
print("1/6 Méga base…")
con.execute(f"ATTACH '{MEGABASE.as_posix()}' AS mb (READ_ONLY)")
for t in ["scrutins", "participation", "resultats"]:
    con.execute(f"CREATE TABLE {t} AS SELECT * FROM mb.{t}")
con.execute("DETACH mb")

# 1 a. Les référendums (1992 par commune, 2000 et 2005 par bureau) : OUI et NON rangés comme des « candidats ».
#      Et les élections d'avant 2002 de Cagé et Piketty (1793 → 1997, par commune : un « bureau » = la commune, code 0000).
#      Le découpage (région, arrondissement, canton…) est repris des autres scrutins : par bureau, sinon par commune.
GEO = "libelle_departement, code_region, libelle_region, code_arr, libelle_arr, code_canton, libelle_canton"


def ajouter_scrutins(dossier, prefixe):
    """Ajoute <prefixe>_scrutins / _participation / _resultats.parquet aux trois tables de la méga base."""
    f = lambda t: (dossier / f"{prefixe}_{t}.parquet").as_posix()
    con.execute(f"INSERT INTO scrutins BY NAME SELECT * FROM '{f('scrutins')}'")
    con.execute(f"""INSERT INTO participation BY NAME
        WITH r AS (SELECT * FROM '{f('participation')}'),
        par_bv AS (SELECT id_brut_miom, {', '.join(f'any_value({c}) {c}' for c in GEO.split(', '))}
                   FROM participation WHERE scrutin IN ('2002_pres_t1', '2007_pres_t1') GROUP BY 1),
        par_com AS (SELECT code_commune, any_value(libelle_commune) nom, {', '.join(f'any_value({c}) {c}' for c in GEO.split(', '))}
                    FROM participation WHERE scrutin LIKE '20%' GROUP BY 1)
        SELECT r.scrutin, r.id_brut_miom, r.code_bv, r.code_commune, coalesce(c.nom, r.libelle_commune) libelle_commune, r.code_departement,
               {', '.join(f'coalesce(b.{x}, c.{x}) {x}' for x in GEO.split(', '))},
               r.inscrits, r.abstentions, r.votants, r.blancs, r.nuls, r.exprimes
        FROM r LEFT JOIN par_bv b USING (id_brut_miom) LEFT JOIN par_com c USING (code_commune)""")
    con.execute(f"INSERT INTO resultats BY NAME SELECT * FROM '{f('resultats')}'")


if (CONTEXTE / "referendums" / "referendums_participation.parquet").exists():
    print("   … les référendums")
    ajouter_scrutins(CONTEXTE / "referendums", "referendums")
if (CONTEXTE / "historique_cage_piketty" / "historique_participation.parquet").exists():
    print("   … les élections d'avant 2002 (Cagé et Piketty)")
    ajouter_scrutins(CONTEXTE / "historique_cage_piketty", "historique")
if (CONTEXTE / "cdsp_anciens" / "cdsp_participation.parquet").exists():
    # le CDSP : législatives au 2nd tour 1958-1997, cantonales 1988-1998, régionales 1986-1998 (circonscription, canton, département)
    print("   … les scrutins anciens du CDSP")
    ajouter_scrutins(CONTEXTE / "cdsp_anciens", "cdsp")

# 1 b. Le Parlement d'aujourd'hui (députés et sénateurs en exercice) et les sénatoriales (un « bureau » = le collège d'un département)
PARLEMENT = CONTEXTE / "parlement"
if (PARLEMENT / "deputes.parquet").exists():
    print("   … le Parlement et les sénatoriales")
    for t in ["deputes", "senateurs"]:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM '{(PARLEMENT / (t + '.parquet')).as_posix()}'")
    con.execute(f"INSERT INTO scrutins BY NAME SELECT * FROM '{(PARLEMENT / 'senatoriales_scrutins.parquet').as_posix()}'")
    # (les libellés de département et de région sont ajoutés à l'étape 5, une fois le découpage chargé)
    con.execute(f"INSERT INTO participation BY NAME SELECT * FROM '{(PARLEMENT / 'senatoriales_participation.parquet').as_posix()}'")
    con.execute(f"INSERT INTO resultats BY NAME SELECT * FROM '{(PARLEMENT / 'senatoriales_resultats.parquet').as_posix()}'")

# 1 c. Les votes des députés (scrutins publics) : tous depuis 2012 (open data), et les grands votes d'avant
#      (pages du site de l'Assemblée, Journal officiel) — fabriqués dans donnees_contexte/votes_deputes/
VOTES = CONTEXTE / "votes_deputes"
if (VOTES / "votes_scrutins_opendata.parquet").exists():
    print("   … les votes des députés")
    f = lambda nom: (VOTES / nom).as_posix()
    con.execute(f"""CREATE TABLE votes_scrutins AS
        SELECT scrutin, legislature, date, objet, pour, contre, abstention, source, TRUE AS complet FROM '{f('votes_scrutins_opendata.parquet')}'
        UNION ALL BY NAME
        SELECT scrutin, date, objet, pour, contre, abstention, source, complet, pour_lus, contre_lus
        FROM '{f('votes_scrutins_historiques.parquet')}'""")
    con.execute(f"""CREATE TABLE votes_individuels AS
        SELECT scrutin, depute, groupe, couleur, position, lieu FROM '{f('votes_individuels_opendata.parquet')}'
        UNION ALL BY NAME
        SELECT scrutin, depute, groupe, position FROM '{f('votes_individuels_historiques.parquet')}'""")

# 1 d. Les affiches électorales des Hauts-de-Seine (1968-1990), Archives départementales — donnees_contexte/affiches_92/
AFFICHES = CONTEXTE / "affiches_92" / "affiches.parquet"
if AFFICHES.exists():
    print("   … les affiches électorales des Hauts-de-Seine")
    con.execute(f"CREATE TABLE affiches AS SELECT * FROM '{AFFICHES.as_posix()}'")

# 1 e. Qui sont les candidats : âge, profession, sexe, sortant (fichiers du ministère, 2002-2024) — donnees_contexte/candidats_details/
DETAILS = CONTEXTE / "candidats_details" / "candidats_details.parquet"
if DETAILS.exists():
    print("   … l'âge et la profession des candidats")
    con.execute(f"CREATE TABLE candidats_details AS SELECT * FROM '{DETAILS.as_posix()}'")

# 1 f. Les 17 législatures de la Ve République, siège par siège (qui y siégeait quand on le sait), et les mandats datés
#      (2002 → aujourd'hui) pour savoir qui siégeait le jour d'un vote — donnees_contexte/legislatures/
LEG = CONTEXTE / "legislatures"
if (LEG / "legislatures.parquet").exists():
    print("   … les législatures et leurs sièges")
    for t in ["legislatures", "sieges_legislature", "mandats_deputes", "groupes_deputes"]:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM '{(LEG / (t + '.parquet')).as_posix()}'")

# 1 bis. « Les 2 tours » : pour chaque bureau, le 2nd tour s'il a eu lieu, sinon le 1er (le résultat qui a compté).
# Rangés dans scrutins_2tours (et pas dans scrutins) : les courbes « dans le temps » ne les comptent pas en double.
print("   … les 2 tours")
con.execute("""CREATE TABLE scrutins_2tours AS
    SELECT * REPLACE (replace(scrutin, '_t1', '_2t') AS scrutin, 3 AS tour, replace(libelle, '1er tour', 'les 2 tours') AS libelle)
    FROM scrutins s WHERE tour = 1 AND type_libelle <> 'Présidentielle'
      AND NOT (type_libelle = 'Législatives' AND annee < 1999)   -- (avant 1999 : 1er tour par commune, 2nd par circonscription)
      AND EXISTS (SELECT 1 FROM scrutins t WHERE t.tour = 2 AND t.type_libelle = s.type_libelle AND t.annee = s.annee)""")
con.execute("""CREATE TEMP TABLE source_2tours AS
    WITH m AS (SELECT scrutin AS f, replace(scrutin, '_2t', '_t1') AS t1, replace(scrutin, '_2t', '_t2') AS t2 FROM scrutins_2tours)
    SELECT m.f, p.id_brut_miom, m.t2 AS source FROM m JOIN participation p ON p.scrutin = m.t2
    UNION ALL
    SELECT m.f, p.id_brut_miom, m.t1 FROM m JOIN participation p ON p.scrutin = m.t1
    WHERE NOT EXISTS (SELECT 1 FROM participation q WHERE q.scrutin = m.t2 AND q.id_brut_miom = p.id_brut_miom)""")
for t in ["participation", "resultats"]:
    con.execute(f"""INSERT INTO {t} SELECT x.* REPLACE (s.f AS scrutin)
                    FROM {t} x JOIN source_2tours s ON x.scrutin = s.source AND x.id_brut_miom = s.id_brut_miom""")

# 2. Le découpage géographique (déjà calculé pour l'atelier)
print("2/6 Découpage géographique…")
geo = lire_js(GEO_JS)
tables_geo = {
    "geo_region": (geo["reg"], ["code", "libelle"]),
    "geo_departement": (geo["dep"], ["code", "libelle", "region"]),
    "geo_arrondissement": (geo["arr"], ["code", "libelle", "departement"]),
    "geo_circo": (geo["circ"], ["code", "libelle", "departement"]),
    "geo_canton": (geo["can"], ["code", "libelle", "departement"]),
    "geo_epci": (geo["epci"], ["code", "libelle"]),
    "geo_commune": (geo["com"], ["code", "libelle", "departement", "arrondissement", "epci"]),
    "geo_arrmun": (geo["arm"], ["code", "libelle", "commune"]),
    "geo_bureau": (geo["bv"], ["commune", "code_bv", "nom", "circo", "canton", "arrmun"]),
}
for nom, (lignes, colonnes) in tables_geo.items():
    df = pd.DataFrame(lignes, columns=colonnes).astype(str).replace({"": None, "None": None})
    if nom == "geo_bureau":
        df["id_brut_miom"] = df["commune"] + "_" + df["code_bv"]
    con.register("df", df)
    con.execute(f"CREATE TABLE {nom} AS SELECT * FROM df")
    con.unregister("df")

# 3. Contexte, économie, listes
print("3/6 Contexte, économie, listes…")
for nom, fichier in ([("contexte_communes", CONTEXTE / "contexte_communes.parquet"),
                     ("economie_mois", CONTEXTE / "economie" / "economie_mois.parquet"),
                     ("veille_scrutins", CONTEXTE / "economie" / "veille_scrutins.parquet"),
                     ("candidats_listes", CONTEXTE / "listes" / "candidats_listes.parquet"),
                     ("populations", CONTEXTE / "populations" / "populations.parquet"),
                     ("elus_municipaux_2014", CONTEXTE / "elus_2014" / "elus_municipaux_2014.parquet"),
                     ("sieges_2026", CONTEXTE / "sieges_2026" / "sieges_2026.parquet")]
                     + [(f.stem, f) for f in sorted((CONTEXTE / "rne").glob("rne_*.parquet"))]):
    if fichier.exists():
        con.execute(f"CREATE TABLE {nom} AS SELECT * FROM '{fichier.as_posix()}'")
    else:
        print("   (absent :", fichier, ")")

# 4. Les contours de la carte (coordonnées arrondies : ~100 m pour régions et départements, ~10 m sinon)
print("4/6 Contours de la carte…")
lignes = contours("region", CONTOURS / "regions.js", 3) + contours("departement", CONTOURS / "departements.js", 3)
for niveau in ["communes", "bureaux"]:
    for f in sorted((CONTOURS / niveau).glob("*.js")):
        lignes += contours(niveau[:-1], f, 4)
df = pd.DataFrame(lignes, columns=["niveau", "code", "nom", "type", "coords"])
df["departement"] = [re.sub(r"^(97\d|2[AB]|\d\d).*", r"\1", c) if n in ("commune", "bureau") else None for n, c in zip(df.niveau, df.code)]
con.register("df", df)
con.execute("CREATE TABLE contours AS SELECT * FROM df")
con.unregister("df")

# 5. Quelques tables pré-calculées pour que l'appli réponde vite
print("5/6 Pré-calculs…")
con.execute("""UPDATE participation p SET libelle_departement = d.libelle, code_region = d.region, libelle_region = r.libelle,
                      libelle_commune = 'Collège sénatorial – ' || d.libelle
               FROM geo_departement d LEFT JOIN geo_region r ON r.code = d.region
               WHERE p.scrutin LIKE '%_sena_%' AND d.code = p.code_departement""")
# les « bureaux » sans commune (circonscriptions, cantons, départements du CDSP) : leur département et leur région
con.execute("""UPDATE participation p SET libelle_departement = coalesce(p.libelle_departement, d.libelle), code_region = d.region,
                      libelle_region = r.libelle
               FROM geo_departement d LEFT JOIN geo_region r ON r.code = d.region
               WHERE p.code_commune IS NULL AND p.libelle_region IS NULL AND d.code = p.code_departement""")
con.execute("""CREATE TABLE totaux_scrutin AS
    SELECT scrutin, sum(inscrits) inscrits, sum(abstentions) abstentions, sum(votants) votants,
           sum(blancs) blancs, sum(nuls) nuls, sum(exprimes) exprimes
    FROM participation GROUP BY scrutin""")

con.execute("CHECKPOINT")
con.close()
if SORTIE.exists():
    SORTIE.unlink()
TEMP.rename(SORTIE)

# 6. Contrôle
print("6/6 Contrôle…")
con = duckdb.connect(str(SORTIE), read_only=True)
for (t,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
    print(f"   {t:22s} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>12,}".replace(",", " "))
print(f"data/depouillement.duckdb : {SORTIE.stat().st_size / 1e6:.0f} Mo")


# 7. Les adresses du répertoire électoral (REU) : chaque adresse, sa position et SON bureau de vote (officiel)
#    Un fichier à part (data/adresses.parquet) : la base principale reste légère, et on ne le refait que si besoin.
if ADRESSES_REU.exists() and BUREAUX_REU.exists():
    if not ADRESSES.exists() or ADRESSES.stat().st_mtime < ADRESSES_REU.stat().st_mtime:
        print("7/8 Adresses du répertoire électoral (16 millions, ~1 min)…")
        lire = "read_csv('{}', all_varchar=true, quote='\"', delim=',', header=true)"
        duckdb.connect().execute(f"""COPY (
            SELECT a.geo_adresse AS adresse,
                   replace(replace(replace(strip_accents(lower(a.geo_adresse)), '-', ' '), chr(39), ' '), '’', ' ') AS norme,
                   CAST(a.longitude AS DOUBLE) AS lon, CAST(a.latitude AS DOUBLE) AS lat,
                   b.id_brut_miom, a.code_commune_ref AS code_commune
            FROM {lire.format(ADRESSES_REU.as_posix())} a
            JOIN {lire.format(BUREAUX_REU.as_posix())} b ON b.id_brut_reu = a.id_brut_bv_reu
            ORDER BY code_commune, norme
        ) TO '{ADRESSES.as_posix()}' (FORMAT parquet, COMPRESSION zstd)""")
    n = duckdb.connect().execute(f"SELECT count(*) FROM '{ADRESSES.as_posix()}'").fetchall()[0][0]
    print(f"   adresses.parquet : {n:,} adresses, {ADRESSES.stat().st_size / 1e6:.0f} Mo".replace(",", " "))
else:
    print("7/8 Adresses : PROJET/election/table-adresses-reu.csv absent → pas de recherche par adresse.")

# 8. Le modèle « personnes et mandats » (MariaDB fait foi) : les tables qui écrivaient les personnes en dur deviennent
#    des vues du modèle (brancher_modele.py), puis les sièges de toutes les assemblées sont figés (table sieges_figes)
con.close()
import os
import subprocess
import sys
if os.environ.get("GD_INSTALLATION"):      # (l'installation lance ces deux scripts plus tard, une fois MariaDB rempli)
    sys.exit(0)
print("8/8 Branchement sur le modèle, puis sièges figés (Assemblée, départements, régions, communes, ~ quelques minutes)…")
subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve().parent / "brancher_modele.py")], check=True)
subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve().parent / "figer_sieges.py")], check=True)
