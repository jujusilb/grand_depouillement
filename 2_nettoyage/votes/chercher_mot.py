"""chercher_mot.py « mot » fichier.pdf… — les passages d'un compte rendu qui contiennent ce mot (pour trouver un vote)."""
import re
import sys
from pathlib import Path

import pypdf

mot = sys.argv[1]
for f in sys.argv[2:]:
    texte = re.sub(r"\s+", " ", " ".join((p.extract_text() or "") for p in pypdf.PdfReader(f).pages))
    trouves = [m.start() for m in re.finditer(mot, texte, flags=re.I)]
    print(f"== {Path(f).name} : {len(trouves)} fois")
    for i in trouves[:6]:
        print("   …" + texte[max(0, i - 150):i + 250] + "…")
