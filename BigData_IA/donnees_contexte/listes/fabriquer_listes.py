"""
fabriquer_listes.py — Les listes candidates avec TOUS les colistiers (ministère de l'Intérieur, data.gouv.fr),
ramenées à un seul tableau aux mêmes colonnes, en Parquet.

    py fabriquer_listes.py      (les fichiers d'origine sont dans brut/ ; ~1 minute)

Élections : municipales 2014 (1er tour, et le 2nd tour des petites communes — les listes du 2nd tour 2014 ne sont
pas dans data/tri ; pas de nuance dans les fichiers 2014 : elle est dans les résultats), 2020 et 2026 (1er et 2nd tour ; 2026 avec les conseils d'arrondissement de Paris, Lyon, Marseille
et la métropole de Lyon), régionales 2021 (1er et 2nd tour), européennes 2019 et 2024.

Sortie : candidats_listes.parquet — une ligne par candidat :
    election (comme dans la méga base : 2026_muni_t1…), conseil (municipal, arrondissement, métropole, régional, européen),
    code_departement, code_zone, libelle_zone, numero_panneau, libelle_liste, libelle_abrege, nuance_liste,
    tete_de_liste, ordre, sexe, nom, prenom, date_naissance, profession, nationalite, conseil_communautaire, sortant,
    vote_de_liste (False = petites communes 2020 : on vote pour des personnes, pas pour une liste)
"""

import csv
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
BRUT = ICI / "brut"

# Les colonnes de chaque famille de fichiers -> nos colonnes communes
C2026 = {"Code département": "code_departement", "Code circonscription": "code_zone", "Circonscription": "libelle_zone",
         "Numéro de panneau": "numero_panneau", "Libellé abrégé de liste": "libelle_abrege", "Libellé de la liste": "libelle_liste",
         "Code nuance de liste": "nuance_liste", "Tête de liste": "tete_de_liste", "Ordre": "ordre", "Sexe": "sexe",
         "Nom sur le bulletin de vote": "nom", "Prénom sur le bulletin de vote": "prenom", "Nationalité": "nationalite", "CC": "conseil_communautaire"}
C2020 = {"Code du département": "code_departement", "Code commune": "code_commune_court", "Libellé commune": "libelle_zone",
         "N° Panneau Liste": "numero_panneau", "Libellé abrégé liste": "libelle_abrege", "Libellé Etendu Liste": "libelle_liste",
         "Nuance Liste": "nuance_liste", "N° candidat": "ordre", "N° dépot candidat": "ordre", "Sexe candidat": "sexe",
         "Nom candidat": "nom", "Prénom candidat": "prenom", "Date naissance candidat": "date_naissance",
         "Profession du candidat": "profession", "Nationalité": "nationalite", "Candidat au conseil communautaire": "conseil_communautaire"}
C2014 = {"Code du département": "code_departement", "Code commune": "code_commune_court", "Libellé commune": "libelle_zone",
         "N° Panneau Liste": "numero_panneau", "Libellé abrégé liste": "libelle_abrege", "Libellé Etendu Liste": "libelle_liste",
         "N° du candidat dans la liste": "ordre", "N° de dépôt du candidat": "ordre", "Sexe": "sexe", "Nom": "nom", "Prénom": "prenom",
         "Date naissance": "date_naissance", "Nationalité": "nationalite", "Candidat au conseil communautaire": "conseil_communautaire"}
CREG = {"Code de la région": "code_region", "Code section électorale": "code_departement", "Libellé section électorale": "libelle_zone",
        "N° Panneau Liste": "numero_panneau", "Libellé Etendu Liste": "libelle_liste", "Nuance Liste": "nuance_liste",
        "Tête de Liste": "tete_de_liste", "N° candidat": "ordre", "Sexe candidat": "sexe", "Nom candidat": "nom", "Prénom candidat": "prenom",
        "Date naissance candidat": "date_naissance", "Profession candidat": "profession"}
CEU19 = {"Code de la circ.europ.": "code_zone", "Libellé de la circ.europ.": "libelle_zone", "N° Panneau Liste": "numero_panneau",
         "Libellé Etendu Liste": "libelle_liste", "Tête de Liste": "tete_de_liste", "N° candidat": "ordre", "Sexe candidat": "sexe",
         "Nom candidat": "nom", "Prénom candidat": "prenom", "Date naissance candidat": "date_naissance",
         "Profession candidat": "profession", "Le candidat est sortant": "sortant"}
CEU24 = {"Code circonscription": "code_zone", "Circonscription": "libelle_zone", "Numéro de panneau": "numero_panneau",
         "Libellé de la liste": "libelle_liste", "Tête de liste": "tete_de_liste", "Ordre": "ordre", "Sexe": "sexe",
         "Nom sur le bulletin de vote": "nom", "Prénom sur le bulletin de vote": "prenom", "Date de naissance": "date_naissance",
         "Profession": "profession", "Sortant": "sortant"}

# fichier, élection, conseil, colonnes, séparateur, encodage, lignes d'en-tête à sauter, vote de liste ?
FICHIERS = [
    ("muni2026_t1.csv", "2026_muni_t1", "municipal", C2026, ";", "utf-8", 0, True),
    ("muni2026_t2.csv", "2026_muni_t2", "municipal", C2026, ";", "utf-8", 0, True),
    ("muni2026_t1_arrondissements_plm.csv", "2026_muni_t1", "arrondissement", C2026, ";", "utf-8", 0, True),
    ("muni2026_t2_arrondissements_plm.csv", "2026_muni_t2", "arrondissement", C2026, ";", "utf-8", 0, True),
    ("metropole_lyon2026_t2.csv", "2026_muni_t2", "métropole", C2026, ";", "utf-8", 0, True),
    ("muni2014_t1_listes.csv", "2014_muni_t1", "municipal", C2014, ";", "utf-8", 0, True),
    ("muni2014_t1_petites_communes.csv", "2014_muni_t1", "municipal", C2014, ";", "utf-8", 0, False),
    ("muni2014_t2_petites_communes.csv", "2014_muni_t2", "municipal", C2014, ";", "utf-8", 0, False),
    ("muni2020_t1_listes.txt", "2020_muni_t1", "municipal", C2020, "\t", "latin-1", 2, True),
    ("muni2020_t2_listes.txt", "2020_muni_t2", "municipal", C2020, "\t", "latin-1", 0, True),
    ("muni2020_t1_petites_communes.txt", "2020_muni_t1", "municipal", C2020, "\t", "latin-1", 0, False),
    ("muni2020_t2_petites_communes.txt", "2020_muni_t2", "municipal", C2020, "\t", "latin-1", 0, False),
    ("regi2021_t1.txt", "2021_regi_t1", "régional", CREG, "\t", "latin-1", 0, True),
    ("regi2021_t2.txt", "2021_regi_t2", "régional", CREG, "\t", "latin-1", 0, True),
    ("euro2019.csv", "2019_euro_t1", "européen", CEU19, ";", "latin-1", 0, True),
    ("euro2024.csv", "2024_euro_t1", "européen", CEU24, ";", "utf-8", 0, True),
]
# Dans les fichiers 2020, l'outre-mer a des codes de département en lettres
DOM = {"ZA": "971", "ZB": "972", "ZC": "973", "ZD": "974", "ZM": "976", "ZN": "988", "ZP": "987", "ZS": "975", "ZW": "986", "ZX": "977"}
COLONNES = ["election", "conseil", "code_region", "code_departement", "code_zone", "libelle_zone", "numero_panneau", "libelle_liste",
            "libelle_abrege", "nuance_liste", "tete_de_liste", "ordre", "sexe", "nom", "prenom", "date_naissance", "profession",
            "nationalite", "conseil_communautaire", "sortant", "vote_de_liste"]


def oui(v):
    return v.fillna("").astype(str).str.strip().str.upper().isin(["OUI", "O", "1", "TRUE"])


tables = []
for nom, election, conseil, colonnes, sep, enc, saut, liste in FICHIERS:
    d = pd.read_csv(BRUT / nom, sep=sep, encoding=enc, skiprows=saut, dtype=str, keep_default_na=False, na_values=[""],
                    quoting=csv.QUOTE_NONE if sep == "\t" else csv.QUOTE_MINIMAL, on_bad_lines="warn")
    d.columns = [c.strip().strip('"') for c in d.columns]
    d = d.rename(columns=colonnes)
    d = d[[c for c in d.columns if c in set(colonnes.values())]]
    d = d.loc[:, ~d.columns.duplicated()]
    d = d[d["nom"].notna()]                                   # 2026 T2 : lignes vides pour les communes sans 2nd tour
    if "code_commune_court" in d:                            # 2020 : département + numéro de commune -> code INSEE
        dep = d["code_departement"].str.strip()
        dom = dep.map(DOM)
        dep_insee = dom.fillna(dep.str.zfill(2))
        num = d["code_commune_court"].str.strip()
        d["code_zone"] = (dep_insee + num.where(dom.isna(), num.str[-2:].str.zfill(2)).str.zfill(3).where(dom.isna(), num.str[-2:].str.zfill(2)))
        d["code_departement"] = dep_insee
    if conseil == "régional":   # une liste régionale couvre la région ; « code_departement » = sa section départementale
        d["code_zone"] = d["code_region"]
    for c in COLONNES:
        if c not in d:
            d[c] = None
    d["election"], d["conseil"], d["vote_de_liste"] = election, conseil, liste
    d["ordre"] = pd.to_numeric(d["ordre"], errors="coerce").astype("Int64")
    d["numero_panneau"] = pd.to_numeric(d["numero_panneau"], errors="coerce").astype("Int64")
    # tête de liste : la colonne du fichier ; sinon (2020) le candidat n°1 de chaque liste
    d["tete_de_liste"] = oui(d["tete_de_liste"]) if d["tete_de_liste"].notna().any() else (d["ordre"] == 1) & liste
    d["conseil_communautaire"] = oui(d["conseil_communautaire"])
    d["sortant"] = oui(d["sortant"])
    tables.append(d[COLONNES])
    print(f"{nom:42s} {len(d):>9,} candidats".replace(",", " "))

tout = pd.concat(tables, ignore_index=True)
for c in ["sexe", "nom", "prenom", "libelle_liste", "libelle_zone"]:
    tout[c] = tout[c].str.strip()
tout.to_parquet(ICI / "candidats_listes.parquet", index=False, compression="zstd")
print(f"candidats_listes.parquet : {len(tout):,} candidats, {(ICI / 'candidats_listes.parquet').stat().st_size / 1e6:.1f} Mo".replace(",", " "))
