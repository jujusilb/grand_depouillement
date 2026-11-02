"""
elus_2014.py — Les conseillers municipaux élus en mars 2014 (ministère de l'Intérieur, publiés le 31 mars 2014).

    py elus_2014.py

Sources (brut/, 90 Mo, 10 fichiers xls) : « Elections municipales 2014 – Liste des élus » (communes de 1 000 habitants et
plus / de moins de 1 000), data.gouv.fr. Une ligne par élu : commune, tour où il a été élu, nom, prénom, sexe, naissance,
profession. Le fichier ne dit PAS sur quelle liste l'élu a été élu.
Sortie : elus_municipaux_2014.parquet
"""
import sys
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("elus_2014")


def code_commune(dpt, com):
    """« 35 », « 1 » → « 35001 » ; outre-mer « 971 », « 101 » ou « 1 » → « 97101 »."""
    dpt, com = str(dpt).strip(), str(com).strip()
    if len(dpt) == 3:
        return dpt + com[-2:].zfill(2)
    return dpt.zfill(2) + com.zfill(3)


morceaux = []
for f in sorted((ICI / "brut").glob("muni-2014-elus-*.xls")):
    t = pd.read_excel(f, dtype=str)
    morceaux.append(pd.DataFrame({
        "code_commune": [code_commune(a, b) for a, b in zip(t["DPT"], t["CODCOM"])],
        "commune": t["COMMUNE"].replace({"False": "Faux"}), "tour": t["TOUR"].astype(int), "nom": t["NOM"].str.strip(), "prenom": t["PRENOM"].str.strip(),
        "sexe": t["SEXE"], "naissance": pd.to_datetime(t["NAISS"], errors="coerce"), "profession": t["LIBCSP"],
        "petite_commune": "moins-1000h" in f.name}))
e = pd.concat(morceaux, ignore_index=True)
e.to_parquet(ICI / "elus_municipaux_2014.parquet", index=False)
print(f"elus_municipaux_2014.parquet : {len(e)} élus, {e['code_commune'].nunique()} communes")
