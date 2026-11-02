"""
chercher_historiques.py — Les candidats aux présidentielles d'avant 2002 (1848, 1965 → 1995) sur Wikidata, et leur photo libre.

    py chercher_historiques.py          (quelques secondes ; puis py telecharger_photos.py pour les photos)

Les noms viennent de ../historique_cage_piketty/historique.py (CANDIDATS). On cherche chaque nom en libellé
OU en autre nom (« Louis-Napoléon Bonaparte » est un autre nom de Napoléon III), parmi les humains de nationalité française,
et on garde le plus connu (le plus d'articles Wikipédia). On les ajoute à candidats_choisis.parquet (sans doublon).
"""
import json
import sys
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("photos_candidats")
source = (RACINE_DEPOT / "2_nettoyage" / "historique.py").read_text(encoding="utf-8-sig")
noms = re.findall(r'\(\s*"([^"]+)",\s*"[A-Z]+"\)', source[source.index("CANDIDATS = {"):source.index("# Les courants des législatives")])


def libelles(nom):
    """« Charles DE GAULLE » → « Charles de Gaulle », « Charles De Gaulle » ; « Jean-Marie LE PEN » → « Jean-Marie Le Pen »…"""
    mots = nom.split()
    i = next(k for k, m in enumerate(mots) if m.isupper() and len(m) > 1)
    prenom, famille = " ".join(mots[:i]), mots[i:]
    titre = " ".join("-".join(p.capitalize() for p in m.split("-")) for m in famille)
    titre = re.sub(r"D'(\w)", lambda x: "d'" + x.group(1).upper(), titre)
    bas = " ".join(m.lower() if m.lower() in ("de", "du", "des") else m for m in titre.split())
    return {f"{prenom} {titre}", f"{prenom} {bas}", f"{prenom} {bas.replace('Le ', 'Le ')}"}


etiquettes = {lib: nom for nom in noms for lib in libelles(nom)}
valeurs = " ".join(json.dumps(e, ensure_ascii=False) + l for e in etiquettes for l in ("@fr", "@mul"))
requete = f"""SELECT ?nom ?p ?img ?naissance ?notoriete WHERE {{
    VALUES ?nom {{ {valeurs} }}
    {{ ?p rdfs:label ?nom }} UNION {{ ?p skos:altLabel ?nom }}
    ?p wdt:P31 wd:Q5 ; wdt:P27 ?pays ; wikibase:sitelinks ?notoriete .
    VALUES ?pays {{ wd:Q142 wd:Q71084 wd:Q58296 wd:Q70802 }}
    OPTIONAL {{ ?p wdt:P18 ?img }}
    OPTIONAL {{ ?p wdt:P569 ?naissance }}
}}"""
d = urllib.parse.urlencode({"query": requete, "format": "json"}).encode()
r = urllib.request.Request("https://query.wikidata.org/sparql", data=d, headers={"User-Agent": "LeGrandDepouillement/1.0 (usage personnel)"})
res = json.load(urllib.request.urlopen(r, timeout=120))["results"]["bindings"]
t = pd.DataFrame([(etiquettes[x["nom"]["value"]], x["p"]["value"].rsplit("/", 1)[1], x.get("img", {}).get("value"),
                   x.get("naissance", {}).get("value", "")[:10], int(x["notoriete"]["value"])) for x in res],
                 columns=["candidat", "qid", "image", "naissance", "notoriete"]).drop_duplicates(["candidat", "qid"])
choix = t.sort_values("notoriete", ascending=False).drop_duplicates("candidat")
print(f"{len(noms)} candidats · {len(choix)} trouvés · {choix['image'].notna().sum()} avec photo")
print(choix[["candidat", "qid", "notoriete", "naissance"]].assign(photo=choix["image"].notna()).to_string(index=False))
print("non trouvés :", ", ".join(sorted(set(noms) - set(choix["candidat"]))))

c = pd.read_parquet(ICI / "candidats_choisis.parquet")
nouveaux = choix[choix["image"].notna()].assign(par_notoriete=True, politique=True)[["candidat", "qid", "image", "naissance", "par_notoriete", "politique"]]
c = pd.concat([c[~c["candidat"].isin(nouveaux["candidat"])], nouveaux], ignore_index=True)
c.to_parquet(ICI / "candidats_choisis.parquet", index=False)
print(f"candidats_choisis.parquet : {c['image'].notna().sum()} avec photo")
