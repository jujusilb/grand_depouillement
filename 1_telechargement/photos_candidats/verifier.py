"""Parmi les personnes trouvées avec photo : lesquelles sont vraiment des responsables politiques ? (profession ou mandat)"""
import json, time, urllib.parse, urllib.request
import pandas as pd
t = pd.read_parquet("candidats_wikidata.parquet")
fr = t[t.francais & (t.homonymes == 1) & t.image.notna()].drop_duplicates("candidat")
qids = sorted(set(fr.qid))
def sparql(q):
    d = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    r = urllib.request.Request("https://query.wikidata.org/sparql", data=d, headers={"User-Agent": "LeGrandDepouillement/1.0 (usage personnel)"})
    return json.load(urllib.request.urlopen(r, timeout=120))["results"]["bindings"]
politiques = set()
for i in range(0, len(qids), 200):
    v = " ".join("wd:" + q for q in qids[i:i + 200])
    r = sparql(f"""SELECT DISTINCT ?p WHERE {{ VALUES ?p {{ {v} }}
        {{ ?p wdt:P106 wd:Q82955 }} UNION {{ ?p wdt:P39 ?poste }} UNION {{ ?p wdt:P102 ?parti }} }}""")
    politiques |= {x["p"]["value"].rsplit("/", 1)[1] for x in r}
    time.sleep(1)
fr["politique"] = fr.qid.isin(politiques)
fr.to_parquet("candidats_avec_photo.parquet", index=False)
print(len(fr), "avec photo ;", int(fr.politique.sum()), "sont bien des responsables politiques (profession, mandat ou parti)")
