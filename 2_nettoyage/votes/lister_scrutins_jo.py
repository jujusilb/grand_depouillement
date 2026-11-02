"""
lister_scrutins_jo.py brut/jo/*.pdf — Les scrutins publics trouvés dans des comptes rendus du Journal officiel :
numéro, objet (« Sur l'ensemble du projet de loi… ») et résultat (pour / contre), pour repérer le bon.
"""
import re
import sys
from pathlib import Path

import pypdf

for f in sys.argv[1:]:
    texte = " ".join((p.extract_text() or "") for p in pypdf.PdfReader(f).pages)
    texte = re.sub(r"\s+", " ", texte)
    trouves = list(re.finditer(r"SCRUTIN\s*\(\s*N\S{0,3}\s*(\d+)\s*\)", texte, flags=re.I))
    print(f"== {Path(f).name} : {len(trouves)} scrutin(s)")
    for m in trouves:
        suite = texte[m.end():m.end() + 900]
        objet = re.search(r"Sur (.{20,220}?)(?:\.|Nombre)", suite)
        pour = re.search(r"Pour l.adoption\D{0,15}(\d+)", suite)
        contre = re.search(r"Contre\D{0,15}(\d+)", suite)
        print(f"   n° {m.group(1)} : {objet.group(1) if objet else '?'} — pour {pour.group(1) if pour else '?'}, contre {contre.group(1) if contre else '?'}")
