"""
wikidata_deputes.py — Les mandats de député (1789 → aujourd'hui) des personnes qui ont une fiche Sycomore, d'après Wikidata.

    py wikidata_deputes.py

Wikidata (CC0) reprend la base Sycomore de l'Assemblée nationale : pour chaque député, ses mandats (P39 « fonction occupée »)
avec la législature (P2937), la circonscription (P768), le groupe (P4100), les dates (P580/P582) ; et son parti (P102).
On télécharge fonction par fonction (« député de la Troisième République », « membre du Conseil des Cinq-Cents »…) :
une petite requête par fonction, gardée telle quelle dans brut/wikidata/ (une relance ne retélécharge pas ce qui est là).

Sortie : deputes_wikidata.parquet (un mandat par ligne).
"""
import json
import sys
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("legislatures")
BRUT = ICI / "brut" / "wikidata"
BRUT.mkdir(parents=True, exist_ok=True)
URL = "https://query.wikidata.org/sparql"
ENTETE = {"User-Agent": "LeGrandDepouillement/1.0 (projet d'apprentissage, donnees electorales)"}
# les fonctions de député (et des chambres basses d'avant : Cinq-Cents, Anciens, Corps législatif…)
MOTS = re.compile(r"d[ée]put[ée]|chambre des|cinq-cents|conseil des anciens|corps l[ée]gislatif|assembl[ée]e|convention|repr[ée]sentants",
                  re.I)
SAUF = re.compile(r"europ|conseil de l'europe|otan|ueo|suppl[ée]ant|s[ée]nat|pair|vice-pr[ée]sident|pr[ée]sident|questeur|secr[ée]taire",
                  re.I)


def sparql(requete):
    for essai in range(5):
        try:
            r = urllib.request.Request(URL + "?" + urllib.parse.urlencode({"query": requete, "format": "json"}), headers=ENTETE)
            return json.load(urllib.request.urlopen(r, timeout=300))["results"]["bindings"]
        except Exception as e:          # (429 ou délai dépassé : on patiente et on recommence)
            print("   nouvel essai :", e)
            time.sleep(20 * (essai + 1))
    raise RuntimeError("Wikidata ne répond pas")


def val(b, cle):
    v = b.get(cle, {}).get("value")
    return v.replace("http://www.wikidata.org/entity/", "") if v else None


# 1. les fonctions occupées par les députés de Sycomore
fonctions = sparql("""
SELECT ?pos ?posLabel (COUNT(DISTINCT ?st) AS ?n) WHERE {
  ?p wdt:P1045 []; p:P39 ?st. ?st ps:P39 ?pos.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
} GROUP BY ?pos ?posLabel""")
fonctions = [(val(b, "pos"), val(b, "posLabel"), int(val(b, "n"))) for b in fonctions]
gardees = [f for f in fonctions if MOTS.search(f[1] or "") and not SAUF.search(f[1] or "")]
print(f"{len(gardees)} fonctions de député sur {len(fonctions)} ; {sum(f[2] for f in gardees)} mandats")
pd.DataFrame(gardees, columns=["fonction", "libelle", "mandats"]).to_csv(BRUT / "fonctions.csv", index=False, encoding="utf-8")

# 2. les mandats, fonction par fonction
REQUETE = """
SELECT ?p ?pLabel ?st ?leg ?legLabel ?debut ?fin ?circ ?circLabel ?groupe ?groupeLabel ?naissance ?sycomore WHERE {
  ?p wdt:P1045 ?sycomore; p:P39 ?st. ?st ps:P39 wd:%s.
  OPTIONAL { ?st pq:P2937 ?leg } OPTIONAL { ?st pq:P580 ?debut } OPTIONAL { ?st pq:P582 ?fin }
  OPTIONAL { ?st pq:P768 ?circ } OPTIONAL { ?st pq:P4100 ?groupe } OPTIONAL { ?p wdt:P569 ?naissance }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
}"""
for i, (q, lib, n) in enumerate(gardees, 1):
    f = BRUT / f"{q}.json"
    if f.exists():
        continue
    print(f"[{i}/{len(gardees)}] {lib} ({n})")
    f.write_text(json.dumps(sparql(REQUETE % q), ensure_ascii=False), encoding="utf-8")
    time.sleep(1.5)

# 3. le parti de chaque député (sur sa fiche, pas sur le mandat)
f = BRUT / "partis.json"
if not f.exists():
    f.write_text(json.dumps(sparql("""
SELECT ?p ?parti ?partiLabel ?debut ?fin WHERE {
  ?p wdt:P1045 []; p:P102 ?s. ?s ps:P102 ?parti. OPTIONAL { ?s pq:P580 ?debut } OPTIONAL { ?s pq:P582 ?fin }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
}"""), ensure_ascii=False), encoding="utf-8")

# 4. tout en un tableau
lignes = []
for q, lib, n in gardees:
    for b in json.loads((BRUT / f"{q}.json").read_text(encoding="utf-8")):
        lignes.append({"qid": val(b, "p"), "depute": val(b, "pLabel"), "sycomore": val(b, "sycomore"), "naissance": val(b, "naissance"),
                       "fonction": q, "fonction_libelle": lib, "mandat": val(b, "st"),
                       "legislature_qid": val(b, "leg"), "legislature_libelle": val(b, "legLabel"),
                       "debut": val(b, "debut"), "fin": val(b, "fin"),
                       "circonscription_qid": val(b, "circ"), "circonscription": val(b, "circLabel"),
                       "groupe_qid": val(b, "groupe"), "groupe": val(b, "groupeLabel")})
t = pd.DataFrame(lignes)
for c in ("debut", "fin", "naissance"):
    t[c] = pd.to_datetime(t[c].str[:10], errors="coerce")
# (un mandat avec deux circonscriptions ou deux groupes donne deux lignes : on garde la première)
t = t.drop_duplicates("mandat")
t.to_parquet(ICI / "deputes_wikidata.parquet", index=False, compression="zstd")
p = pd.DataFrame([{"qid": val(b, "p"), "parti_qid": val(b, "parti"), "parti": val(b, "partiLabel"), "debut": val(b, "debut"), "fin": val(b, "fin")}
                  for b in json.loads(f.read_text(encoding="utf-8"))])
for c in ("debut", "fin"):
    p[c] = pd.to_datetime(p[c].str[:10], errors="coerce")
p.to_parquet(ICI / "partis_wikidata.parquet", index=False, compression="zstd")
print(f"{len(t)} mandats, {t['qid'].nunique()} députés ; {len(p)} affiliations à un parti")
