"""
chercher_wikidata.py — Quels candidats ont une fiche Wikidata, et une photo ? (aucune photo n'est téléchargée ici)

    py chercher_wikidata.py          (~20-30 min : ~100 000 noms, envoyés par paquets de 300 à query.wikidata.org)

On prend TOUS les noms de candidats de la base (présidentielles, législatives, sénatoriales, européennes, régionales,
départementales — les deux du binôme —, cantonales, et les têtes de liste municipales), on les met en « Prénom Nom »,
et on demande à Wikidata les RESPONSABLES POLITIQUES FRANÇAIS (humain, nationalité française, et profession politique,
un mandat ou un parti) qui portent exactement ce nom. Un nom ne compte que s'il désigne UNE seule de ces personnes.
Un paquet qui échoue est coupé en deux et relancé ; ceux qui échouent encore sont notés dans paquets_rates.txt.

Sortie : candidats_wikidata.parquet (nom, qid, image, naissance, homonymes) — puis télécharger_photos.py (avec accord).
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("photos_candidats")
BASE = C.BASE
SORTIE = ICI / "candidats_wikidata.parquet"
PAQUET = 300
PARTICULES = {"de", "du", "des", "d'", "la", "le"}


def mots_nom(nom):
    """« LE PEN » → « Le Pen », « DUPONT-AIGNAN » → « Dupont-Aignan », « D'ARTAGNAN » → « D'Artagnan »."""
    return " ".join("-".join(p[:1].upper() + p[1:].lower() for p in m.split("-")) for m in nom.split())


def variantes(prenom, nom):
    v = {f"{prenom} {mots_nom(nom)}"}
    bas = " ".join(m.lower() if m.lower() in PARTICULES else m for m in mots_nom(nom).split())
    v.add(f"{prenom} {bas}")
    return v


def depuis_qui(qui):
    """« Jean-Luc MÉLENCHON » (prénom puis NOM en capitales) → [(prénom, nom)] ; binômes « M. NOM Prénom et Mme NOM Prénom »."""
    qui = str(qui).strip()
    gens = []
    if " et " in qui and re.match(r"^(M\.|Mme)", qui):
        for morceau in qui.split(" et "):
            morceau = re.sub(r"^(M\.|Mme)\s+", "", morceau.strip())
            mots = morceau.split()
            nom = [m for m in mots if m.upper() == m and any(c.isalpha() for c in m)]
            prenom = [m for m in mots if m not in nom]
            if nom and prenom:
                gens.append((" ".join(prenom), " ".join(nom)))
        return gens
    mots = qui.split()
    nom = [m for m in mots if m.upper() == m and any(c.isalpha() for c in m) and len(m) > 1]
    prenom = [m for m in mots if m not in nom]
    if nom and prenom and "." not in " ".join(prenom):        # « J.Jack » : prénom abrégé, on laisse
        gens.append((" ".join(prenom), " ".join(nom)))
    return gens


con = duckdb.connect(str(BASE), read_only=True)
noms = con.execute("""SELECT DISTINCT r.qui FROM resultats r JOIN scrutins s USING (scrutin)
                      WHERE s.type_libelle NOT IN ('Municipales', 'Référendum')""").df()["qui"].tolist()
noms += con.execute("""SELECT DISTINCT prenom || ' ' || upper(nom) FROM candidats_listes
                       WHERE tete_de_liste AND conseil IN ('municipal', 'européen', 'régional')""").df().iloc[:, 0].tolist()
personnes = {}
for q in noms:
    for prenom, nom in depuis_qui(q):
        for v in variantes(prenom, nom):
            personnes.setdefault(v, f"{prenom} {nom}")
etiquettes = sorted(personnes)
print(f"{len(set(personnes.values())):,} personnes, {len(etiquettes):,} façons de les écrire".replace(",", " "), flush=True)


def sparql(q):
    """La réponse, ou None si le serveur n'a pas répondu après 3 essais."""
    url = "https://query.wikidata.org/sparql"
    donnees = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    req = urllib.request.Request(url, data=donnees, headers={"User-Agent": "LeGrandDepouillement/1.0 (appli d'apprentissage, usage personnel)",
                                                             "Content-Type": "application/x-www-form-urlencoded"})
    for essai in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))["results"]["bindings"]
        except Exception:
            time.sleep(10 * (essai + 1))
    return None


def demander(paquet):
    """Les responsables politiques français qui portent ces noms ; un paquet qui échoue est coupé en deux."""
    # les noms « fr », et les noms communs à toutes les langues (« mul » : Wikidata y range désormais Emmanuel Macron…)
    valeurs = " ".join(json.dumps(e, ensure_ascii=False) + langue for e in paquet for langue in ("@fr", "@mul"))
    r = sparql(f"""SELECT ?nom ?p ?img ?naissance ?notoriete WHERE {{
        VALUES ?nom {{ {valeurs} }}
        ?p rdfs:label ?nom ; wdt:P31 wd:Q5 ; wdt:P27 wd:Q142 .
        FILTER EXISTS {{ {{ ?p wdt:P106 wd:Q82955 }} UNION {{ ?p wdt:P39 ?mandat }} UNION {{ ?p wdt:P102 ?parti }} }}
        OPTIONAL {{ ?p wdt:P18 ?img }}
        OPTIONAL {{ ?p wdt:P569 ?naissance }}
        ?p wikibase:sitelinks ?notoriete .
    }}""")
    if r is not None:
        return r
    if len(paquet) == 1:
        rates.append(paquet[0])
        return []
    moitie = len(paquet) // 2
    return demander(paquet[:moitie]) + demander(paquet[moitie:])


lignes, rates = [], []
for i in range(0, len(etiquettes), PAQUET):
    paquet = etiquettes[i:i + PAQUET]
    r = demander(paquet)
    for x in r:
        lignes.append((personnes[x["nom"]["value"]], x["nom"]["value"], x["p"]["value"].rsplit("/", 1)[1], x.get("img", {}).get("value"),
                       x.get("naissance", {}).get("value", "")[:10], True, int(x["notoriete"]["value"])))
    if (i // PAQUET) % 20 == 0:
        print(f"  {i + len(paquet):,} / {len(etiquettes):,} — {len(lignes):,} réponses".replace(",", " "), flush=True)
    time.sleep(1)

t = pd.DataFrame(lignes, columns=["candidat", "libelle", "qid", "image", "naissance", "francais", "notoriete"])
t = t.drop_duplicates(["candidat", "qid", "image"])
fr = t[t["francais"]]
homonymes = fr.groupby("candidat")["qid"].nunique()
t["homonymes"] = t["candidat"].map(homonymes).fillna(0).astype(int)
# homonymes : si l'un est très connu (≥ 10 articles Wikipédia, et 5 fois plus que le suivant), c'est lui (choix noté)
t["choisi"] = t["homonymes"] == 1
t["par_notoriete"] = False
for cand, g in t[t["homonymes"] > 1].drop_duplicates(["candidat", "qid"]).groupby("candidat"):
    g = g.sort_values("notoriete", ascending=False)
    n = g["notoriete"].tolist()
    if n[0] >= 10 and n[0] >= 5 * max(1, n[1]):
        t.loc[(t["candidat"] == cand) & (t["qid"] == g["qid"].iloc[0]), ["choisi", "par_notoriete"]] = True
t.to_parquet(SORTIE, index=False)
(ICI / "paquets_rates.txt").write_text("\n".join(rates), encoding="utf-8")
print(f"Noms sans réponse du serveur : {len(rates)}")
seuls = t[t["choisi"]].drop_duplicates("candidat")
print(f"\nPersonnes trouvées (sans homonyme, ou le plus connu) : {len(seuls):,}".replace(",", " "))
print(f"… dont choisies par notoriété : {int(seuls['par_notoriete'].sum()):,}".replace(",", " "))
print(f"… dont avec photo : {seuls['image'].notna().sum():,}".replace(",", " "))
print(f"Noms à plusieurs personnes (laissés de côté) : {(homonymes > 1).sum():,}".replace(",", " "))
