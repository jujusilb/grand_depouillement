"""
choisir.py — Parmi les réponses de Wikidata (candidats_wikidata.parquet), qui est vraiment notre candidat ?

    py choisir.py

Règles, dans l'ordre :
  1. Nos candidats se présentent entre 1999 et 2026 : une personne née avant 1915 n'est pas eux (homonyme célèbre et mort).
  2. Un nom = UNE seule personne restante → c'est elle.
  3. Plusieurs : si l'une est très connue (≥ 10 articles Wikipédia, 5 fois plus que la suivante) → c'est elle (noté « par_notoriete »).
  4. Sinon : on ne devine pas.
Les noms écrits sans accent (« MELENCHON ») reprennent la personne trouvée avec accent.

Sortie : candidats_choisis.parquet (candidat, qid, image, naissance, par_notoriete)
"""
import unicodedata
import sys
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("photos_candidats")
t = pd.read_parquet(ICI / "candidats_wikidata.parquet").drop_duplicates(["candidat", "qid"])
annee = pd.to_numeric(t["naissance"].str[:4], errors="coerce")     # (« valeur inconnue » de Wikidata → pas d'année)
t = t[~(annee < 1915)]


def sans_accent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.upper()) if unicodedata.category(c) != "Mn")


choix = []
for cand, g in t.groupby("candidat"):
    g = g.sort_values("notoriete", ascending=False)
    if len(g) == 1:
        choix.append((cand, *g.iloc[0][["qid", "image", "naissance"]], False))
    elif g["notoriete"].iloc[0] >= 10 and g["notoriete"].iloc[0] >= 5 * max(1, g["notoriete"].iloc[1]):
        choix.append((cand, *g.iloc[0][["qid", "image", "naissance"]], True))
c = pd.DataFrame(choix, columns=["candidat", "qid", "image", "naissance", "par_notoriete"])
# les orthographes sans accent : même personne que l'orthographe avec accent
c["cle"] = c["candidat"].map(sans_accent)
c = c.sort_values("image", na_position="last").drop_duplicates("cle").drop(columns="cle")
c.to_parquet(ICI / "candidats_choisis.parquet", index=False)
print(f"{len(c):,} candidats reconnus · {c['image'].notna().sum():,} avec photo · {int(c['par_notoriete'].sum())} choisis par notoriété".replace(",", " "))

# 5. Pour ceux qui ont une photo : il faut être VRAIMENT politique (profession « personnalité politique » ou un parti) —
#    « avoir un poste » est trop large sur Wikidata (évêque, recteur, entraîneur… sont aussi des « postes »)
import json, time, urllib.parse, urllib.request


def sparql(q):
    d = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    r = urllib.request.Request("https://query.wikidata.org/sparql", data=d, headers={"User-Agent": "LeGrandDepouillement/1.0 (usage personnel)"})
    for essai in range(3):
        try:
            return json.load(urllib.request.urlopen(r, timeout=120))["results"]["bindings"]
        except Exception:
            time.sleep(10 * (essai + 1))
    raise RuntimeError("Wikidata ne répond pas")


avec = sorted(set(c.loc[c["image"].notna(), "qid"]))
vrais = set()
for i in range(0, len(avec), 200):
    v = " ".join("wd:" + q for q in avec[i:i + 200])
    vrais |= {x["p"]["value"].rsplit("/", 1)[1] for x in sparql(
        f"SELECT DISTINCT ?p WHERE {{ VALUES ?p {{ {v} }} {{ ?p wdt:P106 wd:Q82955 }} UNION {{ ?p wdt:P102 ?parti }} }}")}
    time.sleep(1)
c["politique"] = c["qid"].isin(vrais) | c["image"].isna()
c.loc[~c["politique"], "image"] = None          # pas sûr que ce soit lui : pas de photo
c.to_parquet(ICI / "candidats_choisis.parquet", index=False)
print(f"après vérification : {c['image'].notna().sum():,} avec photo ({len(avec) - len(vrais & set(avec))} photos retirées)".replace(",", " "))
