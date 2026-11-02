"""
fabriquer_pres2022.py — La présidentielle 2022 (1er tour) en tableau large : une ligne par bureau, une colonne par candidat.
C'est l'entrée de demo_carte/construire_donnees.py (la liste des bureaux et leurs voix).

    py fabriquer_pres2022.py      (quelques secondes ; après parquets/decouper_resultats.py)

Entrée  : parquets/data/participation/2022_pres_t1.parquet, parquets/data/candidat/2022_pres_t1.parquet
Sortie  : data/2022_pres_t1_results.parquet
"""
from pathlib import Path

import duckdb

ICI = Path(__file__).resolve().parent
P = (ICI.parent / "parquets" / "data" / "participation" / "2022_pres_t1.parquet").as_posix()
C = (ICI.parent / "parquets" / "data" / "candidat" / "2022_pres_t1.parquet").as_posix()
SORTIE = ICI / "2022_pres_t1_results.parquet"

con = duckdb.connect()
con.execute(f"CREATE TABLE v AS SELECT id_brut_miom, prenom || ' ' || nom candidat, sum(voix) voix FROM '{C}' GROUP BY ALL")
large = con.execute("PIVOT v ON candidat USING sum(voix) GROUP BY id_brut_miom").df()
p = con.execute(f"SELECT * FROM '{P}'").df()
t = p.merge(large, on="id_brut_miom", how="left")
noms = [c for c in large.columns if c != "id_brut_miom"]
t["total_voix"] = t[noms].sum(axis=1).astype("int64")
t.to_parquet(SORTIE, index=False)
print(f"{SORTIE.name} : {len(t)} bureaux, {len(noms)} candidats")
