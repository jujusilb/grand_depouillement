"""
populations.py — La population municipale de chaque commune, année par année (pour la taille légale des conseils).

    py populations.py

Source : Insee, « Historique des populations communales 1876-2023 » (brut/base-pop-historiques-1876-2023.xlsx, 7 Mo)
    https://www.insee.fr/fr/statistiques/3698339
Géographie au 1er janvier 2025 : une commune fusionnée depuis (commune nouvelle) n'a plus sa propre ligne.
Concepts : population municipale depuis 2006 (PMUN), population sans doubles comptes en 1999 (PSDC, celle des municipales 2008).
Paris est donné par arrondissement : on ajoute la ligne 75056 (la somme).
Sortie : populations.parquet (code_commune, annee, population)
"""
import sys
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("populations")

t = pd.read_excel(ICI / "brut" / "base-pop-historiques-1876-2023.xlsx", sheet_name=0, header=5, dtype={"CODGEO": str})
colonnes = {c: int(c[4:]) for c in t.columns if c.startswith("PMUN") or c == "PSDC1999"}
p = t.melt(id_vars="CODGEO", value_vars=list(colonnes), var_name="v", value_name="population").dropna()
p = pd.DataFrame({"code_commune": p["CODGEO"], "annee": p["v"].map(colonnes).astype("int16"), "population": p["population"].astype("int32")})
paris = p[p["code_commune"].str.startswith("751")].groupby("annee", as_index=False)["population"].sum()
paris["code_commune"] = "75056"
p = pd.concat([p, paris[p.columns]], ignore_index=True).sort_values(["code_commune", "annee"])
p.to_parquet(ICI / "populations.parquet", index=False)
print(f"populations.parquet : {p['code_commune'].nunique()} communes, années {sorted(p['annee'].unique())}")
