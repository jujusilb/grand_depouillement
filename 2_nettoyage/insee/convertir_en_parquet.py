"""
convertir_en_parquet.py — Transforme les CSV de l'INSEE (chomage/, revenus/) en fichiers Parquet.

    py convertir_en_parquet.py

Les CSV sont dans les zip téléchargés sur insee.fr. On les extrait, on écrit un .parquet par CSV, puis on supprime le CSV
extrait (le zip d'origine reste là).
    - le code commune (CODGEO) reste du TEXTE : sinon « 01001 » deviendrait 1001 ;
    - les nombres écrits à la française (« 5,0 ») deviennent de vrais nombres (5.0) ;
    - « s » (secret statistique : trop peu de ménages) et « nd » (non disponible) deviennent des cases vides (NULL).
"""

import zipfile
import sys
from pathlib import Path

import duckdb

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("insee")
VIDES = "('', 's', 'nd', 'NA')"


def convertir(csv, parquet):
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t AS SELECT * FROM read_csv('{csv.as_posix()}', delim=';', header=true, all_varchar=true)")
    colonnes = [c[0] for c in con.execute("DESCRIBE t").fetchall()]
    choix = []
    for c in colonnes:
        q = f'"{c}"'
        # une colonne est numérique si toutes ses valeurs (hors vides et secrets) se lisent comme des nombres
        texte = con.execute(f"SELECT count(*) FROM t WHERE {q} NOT IN {VIDES} AND TRY_CAST(REPLACE({q}, ',', '.') AS DOUBLE) IS NULL").fetchall()[0][0]
        if c == "CODGEO" or texte:
            choix.append(q)
        else:
            choix.append(f"TRY_CAST(REPLACE({q}, ',', '.') AS DOUBLE) AS {q}")
    con.execute(f"COPY (SELECT {', '.join(choix)} FROM t) TO '{parquet.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    return len(colonnes), len(colonnes) - sum(1 for x in choix if " AS " not in x)


for zip_ in sorted(ICI.glob("*/*.zip")):
    dossier = zip_.parent
    with zipfile.ZipFile(zip_) as z:
        for nom in z.namelist():
            if not nom.lower().endswith(".csv"):
                continue
            csv = dossier / nom
            z.extract(nom, dossier)
            parquet = csv.with_suffix(".parquet")
            if nom.lower().startswith("meta_"):   # les fichiers « meta_ » décrivent les colonnes : tout en texte
                duckdb.sql(f"""COPY (SELECT * FROM read_csv('{csv.as_posix()}', delim=';', header=true, all_varchar=true))
                               TO '{parquet.as_posix()}' (FORMAT parquet, COMPRESSION zstd)""")
                info = "dictionnaire des colonnes"
            else:
                n, num = convertir(csv, parquet)
                info = f"{n} colonnes dont {num} numériques"
            print(f"{parquet.relative_to(ICI)} : {info}, {parquet.stat().st_size / 1e6:.1f} Mo (CSV : {csv.stat().st_size / 1e6:.1f} Mo)")
            csv.unlink()
