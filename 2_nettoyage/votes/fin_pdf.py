"""fin_pdf.py fichier.pdf [n] — les n derniers caractères du texte d'un compte rendu (les annexes : scrutins…)."""
import re
import sys

import pypdf

texte = re.sub(r"\s+", " ", " ".join((p.extract_text() or "") for p in pypdf.PdfReader(sys.argv[1]).pages))
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
print(len(texte), "caractères")
print(texte[-n:])
