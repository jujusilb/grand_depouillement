"""
preparer_cdsp.py — Les fichiers du CDSP (Sciences Po, data.gouv.fr) que lit donnees/cdsp/cdsp.py,
convertis comme le faisait trier_par_election.py (mêmes fonctions lire / typer) :

    data/tri/cdsp/cdsp_legi1958t2_circ.csv  →  data/tri_parquet/1958_legi_t2/resultats/cdsp-legi1958t2-circ.parquet

    py preparer_cdsp.py      (quelques secondes ; après le téléchargement)
"""
import re
import sys
from pathlib import Path

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.COLLECTE
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (trier_par_election.py)
from trier_par_election import _slug, lire, typer  # noqa: E402

SOURCE = ICI / "tri" / "cdsp"
SORTIE = ICI / "tri_parquet"

for f in sorted(SOURCE.glob("cdsp_*.csv")):
    m = re.match(r"cdsp_(legi|cant|regio)(\d{4})(t\d)?_", f.name)
    election = f"{m[2]}_{'regi' if m[1] == 'regio' else m[1]}_{m[3] or 't1'}"
    tab = typer(lire(f)[0][1])
    tab.columns = [str(c) for c in tab.columns]
    dest = SORTIE / election / "resultats" / f"{_slug(f.stem)}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tab.to_parquet(dest, index=False)
    print(f"{f.name} -> {dest.relative_to(ICI).as_posix()} ({len(tab)} lignes)")
