"""
decouper_resultats.py — Les « Données des élections agrégées » du ministère de l'Intérieur (data.gouv.fr), un Parquet par scrutin.

    py decouper_resultats.py      (~5 minutes)

Entrée  : ELECTION/general_results.csv     participation de chaque bureau (inscrits, votants…), toutes élections
          ELECTION/candidats_results.csv   voix de chaque candidat, liste ou binôme dans chaque bureau
Sortie  : parquets/data/participation/<scrutin>.parquet
          parquets/data/candidat/<scrutin>.parquet       (scrutin = id_election : « 2022_legi_t1 »)

Les codes (département, commune, bureau, circonscription…) restent du texte : « 01 », « 2A », « 0001 ».
DuckDB lit le CSV une seule fois (en Parquet temporaire), puis découpe : la mémoire reste petite.
"""
from pathlib import Path

import duckdb
import sys

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ELECTION = C.ELECTIONS
DATA = C.RESULTATS
NOMBRES = {"inscrits", "abstentions", "votants", "blancs", "nuls", "exprimes", "voix"}

con = duckdb.connect()
con.execute("SET preserve_insertion_order = false")
for nature, fichier in (("participation", "general_results.csv"), ("candidat", "candidats_results.csv")):
    source = (ELECTION / fichier).as_posix()
    colonnes = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{source}', delim=';', all_varchar=true)").fetchall()]
    types = ", ".join(f"'{c}': '{'BIGINT' if c in NOMBRES else 'DOUBLE' if c.startswith('ratio_') else 'VARCHAR'}'" for c in colonnes)
    temp = (DATA / f"_{nature}_tout.parquet").as_posix()
    (DATA / nature).mkdir(parents=True, exist_ok=True)
    print(f"• {fichier} → Parquet…", flush=True)
    con.execute(f"COPY (SELECT * FROM read_csv('{source}', delim=';', header=true, columns={{{types}}})) TO '{temp}' (FORMAT parquet)")
    scrutins = [r[0] for r in con.execute(f"SELECT DISTINCT id_election FROM '{temp}' ORDER BY 1").fetchall()]
    for s in scrutins:
        con.execute(f"COPY (SELECT * FROM '{temp}' WHERE id_election = '{s}') TO '{(DATA / nature / (s + '.parquet')).as_posix()}' (FORMAT parquet)")
    Path(temp).unlink()
    print(f"  {len(scrutins)} scrutins dans data/{nature}/", flush=True)
