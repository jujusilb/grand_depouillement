"""
compacter.py — Pour prendre le moins de place possible : un fichier brut dont plus aucune étape n'a besoin est
transformé en Parquet compressé (zstd) à côté de lui, puis supprimé ; une archive déjà extraite est supprimée.

    x.csv / x.txt   → x.csv.parquet    (toutes les colonnes en texte : rien ne se perd, « 01001 » reste « 01001 »)
    x.xls / x.xlsx  → x.xlsx.parquet   (toutes les feuilles : colonnes feuille, ligne, c0, c1… telles qu'elles sont)
    x.zip / x.7z    → supprimé (son contenu extrait est déjà là)
Un fichier illisible tel quel est gardé (on ne perd jamais une source).
"""
from pathlib import Path

import duckdb
import pandas as pd


def vers_parquet(f):
    cible = f.with_name(f.name + ".parquet")
    ext = f.suffix.lower()
    if ext in (".csv", ".txt"):
        con = duckdb.connect()
        for options in ("", ", encoding='latin-1'"):
            try:
                con.execute(f"COPY (SELECT * FROM read_csv('{f.as_posix()}', all_varchar=true, null_padding=true{options})) "
                            f"TO '{cible.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
                return cible
            except duckdb.Error:
                continue
        return None
    if ext in (".xls", ".xlsx"):
        feuilles = pd.read_excel(f, sheet_name=None, header=None, dtype=str)
        t = pd.concat([x.set_axis([f"c{i}" for i in range(x.shape[1])], axis=1).assign(feuille=nom, ligne=range(len(x)))
                       for nom, x in feuilles.items()], ignore_index=True)
        t.to_parquet(cible, index=False, compression="zstd")
        return cible
    return None


def compacter(f):
    """Rend le nombre d'octets gagnés."""
    f = Path(f)
    if not f.exists():
        return 0
    avant = f.stat().st_size
    if f.suffix.lower() in (".zip", ".7z"):
        f.unlink()
        return avant
    try:
        cible = vers_parquet(f)
    except Exception as e:                       # (un format exotique : on garde l'original)
        print(f"      {f.name} gardé tel quel ({e.__class__.__name__})")
        return 0
    if cible is None:
        return 0
    f.unlink()
    return avant - cible.stat().st_size
