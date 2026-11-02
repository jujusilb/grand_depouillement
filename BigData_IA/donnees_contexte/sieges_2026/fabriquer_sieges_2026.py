"""
fabriquer_sieges_2026.py — Combien de sièges à pourvoir en 2026, commune par commune (ministère de l'Intérieur, 27 février 2026).

    py fabriquer_sieges_2026.py

Source : brut/27-02-2026-mun-26-referentiels-nombre-de-cm-et-cc-a-pourvoir.xlsx (2,6 Mo, data.gouv.fr)
Pour chaque commune : son intercommunalité, sa population légale, ses inscrits, le nombre de sièges de son conseil municipal
et le nombre de ses sièges au conseil communautaire. (Les communes associées ont leur propre ligne : on garde la commune.)
Sortie : sieges_2026.parquet
"""
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent

t = pd.read_excel(next((ICI / "brut").glob("*nombre-de-cm-et-cc*.xlsx")), dtype={"CODE_COMMUNE": str, "CODE_EPCI": str, "LIB_COMMUNE": str})
t = t[t["CODE_COM_ASSOCIEE"].isna()]
s = pd.DataFrame({"code_commune": t["CODE_COMMUNE"].str.zfill(5), "commune": t["LIB_COMMUNE"].replace({"False": "Faux"}),   # (Excel a changé Faux, Ardennes, en booléen)
                   "siren_epci": t["CODE_EPCI"],
                  "epci": t["LIB_EPCI"], "population": t["POPULATION"], "inscrits": t["INSCRITS"],
                  "sieges_municipaux": t["NBRE_SAP_COM"], "sieges_communautaires": t["NBRE_SAP_EPCI"]})
s.to_parquet(ICI / "sieges_2026.parquet", index=False)
print(f"sieges_2026.parquet : {len(s)} communes, {s['sieges_municipaux'].sum()} sièges municipaux, "
      f"{s['sieges_communautaires'].sum()} sièges communautaires")
