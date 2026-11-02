"""
assembler_2014.py — Les candidatures des municipales 2014 : le ministère les a publiées en un fichier Excel par région
(data.gouv.fr) ; on les met bout à bout, dans l'ordre des régions, en un CSV par jeu (celui que lit fabriquer_listes.py).

    py assembler_2014.py      (après le téléchargement : brut/2014/<jeu>/*.xls)

    brut/2014/t1_listes/            → brut/muni2014_t1_listes.csv            (communes de 1 000 habitants et plus, 1er tour)
    brut/2014/t1_petites_communes/  → brut/muni2014_t1_petites_communes.csv  (moins de 1 000 habitants, 1er tour)
    brut/2014/t2_petites_communes/  → brut/muni2014_t2_petites_communes.csv  (moins de 1 000 habitants, 2nd tour)
"""
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
BRUT = ICI / "brut"

def lire(f):
    """Une région : le tableau commence à la ligne « Critère d'export » (certains fichiers ont un titre au-dessus)."""
    debut = pd.read_excel(f, header=None, usecols=[0, 1], nrows=30)
    ligne = next(i for i, (a, b) in enumerate(zip(debut[0], debut[1])) if "Critère d'export" in (str(a), str(b)))
    return pd.read_excel(f, skiprows=ligne)


for jeu in ("t1_listes", "t1_petites_communes", "t2_petites_communes"):
    fichiers = sorted((BRUT / "2014" / jeu).glob("*.xls"))
    t = pd.concat([lire(f) for f in fichiers], ignore_index=True)
    t.to_csv(BRUT / f"muni2014_{jeu}.csv", sep=";", index=False, encoding="utf-8")
    print(f"muni2014_{jeu}.csv : {len(fichiers)} régions, {len(t)} lignes")
