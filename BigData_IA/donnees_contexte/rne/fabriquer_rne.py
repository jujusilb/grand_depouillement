"""
fabriquer_rne.py — Le Répertoire national des élus (ministère de l'Intérieur) à trois dates : qui siège vraiment.

    py fabriquer_rne.py

Sources (brut/, 235 Mo) :
    2020-01  la version du 14 janvier 2020 (les conseils élus en 2014, en fin de mandat)  — web.archive.org
    2020-12  la version du 2 décembre 2020 (les conseils élus en 2020)                     — web.archive.org
    2026-08  la version du 11 août 2026 (les conseils élus en 2026)                         — data.gouv.fr
data.gouv ne publie que la dernière version : les deux anciennes sont les copies de static.data.gouv.fr gardées par
l'Internet Archive. Les anciens fichiers (tabulations, latin-1) codent l'outre-mer ZA, ZB… et la commune sur 3 chiffres ;
les nouveaux (point-virgule, UTF-8) donnent le code Insee entier. On ramène tout aux mêmes colonnes.
Le RNE ne dit pas sur quelle liste un élu a été élu : on le retrouve en croisant avec les listes déposées (dans l'appli).
Sorties : rne_municipaux.parquet, rne_communautaires.parquet, rne_arrondissements.parquet, rne_departementaux.parquet,
          rne_regionaux.parquet — une colonne « version » (2020-01, 2020-12, 2026-08)
"""
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
BRUT = ICI / "brut"
OUTREMER = {"ZA": "971", "ZB": "972", "ZC": "973", "ZD": "974", "ZM": "976", "ZS": "975", "ZN": "988", "ZP": "987",
            "ZX": "977", "ZW": "986"}
ANCIENS = {"cm": "1-rne-cm.txt", "epci": "2-rne-epci.txt", "cd": "3-rne-cd.txt", "cr": "4-rne-cr.txt"}
NOUVEAUX = {"cm": "elus-conseiller-municipal-cm.csv", "epci": "elus-conseiller-communautaire-epci.csv",
            "cd": "elus-conseiller-departemental-cd.csv", "cr": "elus-conseiller-regional-cr.csv",
            "ca": "elus-conseiller-darrondissement-ca.csv"}
COMMUNS = {"Nom de l'élu": "nom", "Prénom de l'élu": "prenom", "Code sexe": "sexe", "Date de naissance": "naissance",
           "Date de début du mandat": "debut_mandat", "Libellé de fonction": "fonction", "Libellé de la fonction": "fonction"}


def code_insee(dep, com):
    """L'ancien format : département (ou ZA…) + commune sur 3 chiffres → code Insee à 5 caractères."""
    dep = dep.fillna("").str.strip()
    com = com.fillna("").str.strip()
    outre = dep.isin(list(OUTREMER))
    return (dep.str.zfill(2) + com.str.zfill(3)).where(~outre, "97" + com)


def lire(version, quoi):
    if version.startswith("2020"):
        t = pd.read_csv(BRUT / version / ANCIENS[quoi], sep="\t", skiprows=1, encoding="latin1", dtype=str)
        dates = {"dayfirst": True}
    else:
        t = pd.read_csv(BRUT / version / NOUVEAUX[quoi], sep=";", encoding="utf-8", dtype=str)
        dates = {"format": "%Y-%m-%d"}
    t.columns = [c.strip() for c in t.columns]
    r = pd.DataFrame({"version": version}, index=t.index)
    if quoi == "cm":
        if version.startswith("2020"):
            r["code_commune"] = code_insee(t["Code du département (Maire)"], t["Code Insee de la commune"])
        else:
            r["code_commune"] = t["Code de la commune"]
        r["commune"] = t["Libellé de la commune"]
    elif quoi == "epci":
        r["siren"] = t["N° SIREN"]
        r["epci"] = t["Libellé de l'EPCI"].str.strip()
        if version.startswith("2020"):
            r["code_commune"] = code_insee(t["Code département commune rattachée"], t["Code de la commune"])
            r["commune"] = t["Libellé commune rattachée"]
        else:
            r["code_commune"] = t["Code de la commune de rattachement"]
            r["commune"] = t["Libellé de la commune de rattachement"]
    elif quoi == "ca":
        r["code_commune"] = t["Code de la commune"]
        r["commune"] = t["Libellé de la commune"]
        r["secteur"] = t["Libellé du secteur"]
    elif quoi == "cd":
        r["departement"] = t["Code du département"].str.zfill(2).replace(OUTREMER)
        r["canton"] = t["Code du canton"]
        r["libelle_canton"] = t["Libellé du canton"]
    elif quoi == "cr":
        r["region"] = t["Code région" if version.startswith("2020") else "Code de la région"].str.zfill(2)
        r["libelle_region"] = t["Libellé de la région"]
    for c, nom in COMMUNS.items():
        if c in t.columns:
            r[nom] = t[c].str.strip() if nom not in ("naissance", "debut_mandat") else pd.to_datetime(t[c], errors="coerce", **dates)
    r["fonction"] = r["fonction"].fillna("") if "fonction" in r else ""
    return r[r["nom"].notna() & ~r["nom"].str.fullmatch(r"\d+", na=False)]          # (la dernière ligne des anciens : « Nombre total: 66858 »)


for quoi, sortie in [("cm", "rne_municipaux"), ("epci", "rne_communautaires"), ("ca", "rne_arrondissements"),
                     ("cd", "rne_departementaux"), ("cr", "rne_regionaux")]:
    versions = ["2026-08"] if quoi == "ca" else ["2020-01", "2020-12", "2026-08"]
    t = pd.concat([lire(v, quoi) for v in versions], ignore_index=True)
    t.to_parquet(ICI / f"{sortie}.parquet", index=False)
    print(f"{sortie}.parquet : {len(t)} élus —", t.groupby("version").size().to_dict())
