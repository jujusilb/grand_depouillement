"""
integrer_liens.py — Les liens familiaux entre personnes de la base : conjoint, compagnon ou compagne, parent → enfant,
frère ou sœur.

    py integrer_liens.py              télécharge les liens Wikidata (si pas déjà là), puis refait les tables
    py integrer_liens.py --sans-wikidata   relit seulement les fichiers (après avoir complété liens_saisis.csv)

Deux sources :
  * Wikidata (conjoint P26, partenaire P451, père P22, mère P25, enfant P40, fratrie P3373), pour les personnes de la
    base qui ont un identifiant Wikidata ; un lien n'est gardé que si les deux personnes sont dans la base ;
  * liens_saisis.csv : ce que l'auteur de la base sait et qu'aucune source ne dit (une mère suppléante de la binôme de
    son fils…). Une ligne par lien : personne_id, lien (libellé de type_lien), autre_id, qui (pour se relire), note.

Tables :
  type_lien (id, libelle, libelle_inverse, symetrique)  — « parent de » / « enfant de »
  lien (id, personne_id, autre_id, type_lien_id, date_debut, date_fin, source_id, note)
       un lien symétrique (conjoint, fratrie) est rangé une seule fois, la plus petite personne_id d'abord ;
       « parent de » va toujours du parent vers l'enfant.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from outils_mariadb import charger, cle_etrangere, lire_identifiants, mysql, requete, sauvegarder, sources

ICI = Path(__file__).resolve().parent
PROJET = ICI.parent.parent
BRUT = PROJET / "BRUT" / "wikidata" / "liens"
DECHET = PROJET / "DECHET"
SAISIS = ICI / "liens_saisis.csv"
ENTETES = {"User-Agent": "LeGrandDepouillement/1.0 (appli d'apprentissage, usage personnel)"}

TYPES = [  # id, libellé, libellé inverse, symétrique
    (1, "conjoint", "conjoint", 1),
    (2, "compagnon ou compagne", "compagnon ou compagne", 1),
    (3, "parent de", "enfant de", 0),
    (4, "frère ou sœur", "frère ou sœur", 1),
]
PROPRIETES = {"P26": (1, False), "P451": (2, False), "P22": (3, True), "P25": (3, True), "P40": (3, False),
              "P3373": (4, False)}   # propriété → (type, à l'envers : « a pour père b » = b parent de a)
PAQUET = 1500


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def telecharger(qids):
    """Les liens Wikidata des personnes qids, par paquets, dans BRUT/wikidata/liens/paquet_NNN.json."""
    BRUT.mkdir(parents=True, exist_ok=True)
    proprietes = " ".join(f"(p:{p} ps:{p})" for p in PROPRIETES)
    for n, i in enumerate(range(0, len(qids), PAQUET)):
        fichier = BRUT / f"paquet_{n:03d}.json"
        if fichier.exists():
            continue
        valeurs = " ".join(f"wd:{q}" for q in qids[i:i + PAQUET])
        sparql = f"""SELECT ?a ?prop ?b ?debut ?fin WHERE {{
                       VALUES ?a {{ {valeurs} }} VALUES (?prop ?ps) {{ {proprietes} }}
                       ?a ?prop ?st . ?st ?ps ?b .
                       OPTIONAL {{ ?st pq:P580 ?debut }} OPTIONAL {{ ?st pq:P582 ?fin }} }}"""
        for essai in range(4):
            try:
                demande = urllib.request.Request("https://query.wikidata.org/sparql",
                                                 data=urllib.parse.urlencode({"query": sparql, "format": "json"}).encode(),
                                                 headers={**ENTETES, "Accept": "application/sparql-results+json"})
                fichier.write_bytes(urllib.request.urlopen(demande, timeout=120).read())
                break
            except Exception as e:
                if essai == 3:
                    raise
                etape(f"  paquet {n} : {e} — nouvel essai")
                time.sleep(20 * (essai + 1))
        etape(f"  paquet {n + 1} / {-(-len(qids) // PAQUET)}")
        time.sleep(2)


def liens_wikidata(par_q):
    lignes = []
    for f in sorted(BRUT.glob("paquet_*.json")):
        for r in json.loads(f.read_text(encoding="utf-8"))["results"]["bindings"]:
            a, b = r["a"]["value"].rsplit("/", 1)[1], r["b"]["value"].rsplit("/", 1)[1]
            prop = r["prop"]["value"].rsplit("/", 1)[1]
            if a not in par_q or b not in par_q or par_q[a] == par_q[b]:
                continue
            type_lien, envers = PROPRIETES[prop]
            x, y = (par_q[b], par_q[a]) if envers else (par_q[a], par_q[b])
            date = lambda k: r[k]["value"][:10] if k in r and r[k]["value"][:1].isdigit() else None
            lignes.append((x, y, type_lien, date("debut"), date("fin")))
    return pd.DataFrame(lignes, columns=["personne_id", "autre_id", "type_lien_id", "date_debut", "date_fin"])


def ranger(t):
    """Un lien symétrique une seule fois (plus petite personne d'abord) ; un même lien vu deux fois → une ligne."""
    sym = t.type_lien_id.isin([i for i, _, _, s in TYPES if s])
    a, b = t.personne_id.copy(), t.autre_id.copy()
    t.loc[sym, "personne_id"] = a[sym].where(a[sym] < b[sym], b[sym])
    t.loc[sym, "autre_id"] = b[sym].where(a[sym] < b[sym], a[sym])
    return (t.sort_values(["date_debut", "date_fin"], na_position="last")
            .drop_duplicates(["personne_id", "autre_id", "type_lien_id"]))


if __name__ == "__main__":
    ident = lire_identifiants()
    ident = ident[ident.source == "Wikidata"]
    par_q = dict(zip(ident.valeur, ident.personne_id.astype("int64")))
    if "--sans-wikidata" not in sys.argv:
        etape(f"liens Wikidata de {len(par_q)} personnes")
        telecharger(sorted(par_q))
    SOURCE = sources(["wikidata", "saisie manuelle"])

    w = ranger(liens_wikidata(par_q)).assign(source_id=SOURCE["wikidata"], note=None)
    s = pd.read_csv(SAISIS, dtype={"personne_id": "int64", "autre_id": "int64"})
    s["type_lien_id"] = s.lien.map({l: i for i, l, _, _ in TYPES})
    if s.type_lien_id.isna().any():
        raise SystemExit(f"type de lien inconnu dans {SAISIS.name} : {sorted(set(s.lien[s.type_lien_id.isna()]))}")
    s = ranger(s.assign(date_debut=None, date_fin=None, source_id=SOURCE["saisie manuelle"]))
    t = pd.concat([s, w])      # (ce que l'auteur sait passe avant Wikidata)
    t = t.drop_duplicates(["personne_id", "autre_id", "type_lien_id"]).reset_index(drop=True)
    t["id"] = range(1, len(t) + 1)

    existe = requete("SHOW TABLES LIKE 'lien'")
    if len(existe):
        sauvegarder(DECHET, "liens_avant_refaire", ["lien", "type_lien"])
    T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    mysql(f"""DROP TABLE IF EXISTS lien; DROP TABLE IF EXISTS type_lien;
              CREATE TABLE type_lien (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(40) NOT NULL,
                                      libelle_inverse VARCHAR(40) NOT NULL, symetrique TINYINT(1) NOT NULL) {T};
              INSERT INTO type_lien VALUES """ + ", ".join(f"({i}, '{l}', '{li}', {s_})" for i, l, li, s_ in TYPES) + f""";
              CREATE TABLE lien (id BIGINT NOT NULL PRIMARY KEY, personne_id BIGINT NOT NULL, autre_id BIGINT NOT NULL,
                                 type_lien_id INT NOT NULL, date_debut DATE, date_fin DATE, source_id INT NOT NULL,
                                 note VARCHAR(255),
                                 UNIQUE KEY un_lien (personne_id, autre_id, type_lien_id), KEY ix_lien_autre (autre_id),
                                 CONSTRAINT pas_soi_meme CHECK (personne_id <> autre_id)) {T}""")
    charger("lien", t[["id", "personne_id", "autre_id", "type_lien_id", "date_debut", "date_fin", "source_id", "note"]])
    cle_etrangere("lien", "personne_id", "personne")
    cle_etrangere("lien", "autre_id", "personne")
    cle_etrangere("lien", "type_lien_id", "type_lien")
    cle_etrangere("lien", "source_id", "source")
    etape(f"{len(t)} liens ({len(s)} saisis à la main) :\n"
          + t.type_lien_id.map({i: l for i, l, _, _ in TYPES}).value_counts().to_string())
