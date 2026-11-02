"""
croiser_deces.py — Les députés de 1958 à 2002 retrouvés dans le fichier des personnes décédées de l'Insee (morts depuis 1970).

    py croiser_deces.py

Sources :
    les sièges des législatures I à XI (la base de l'appli, table sieges_legislature) : nom, département, législatures ;
    le fichier des décès de l'Insee, déjà chargé dans le MariaDB de XAMPP (bases insee_naissance et insee_deces) ;
    Wikidata (deputes_wikidata.parquet) : la date de naissance de beaucoup de députés — elle ne sert PAS au croisement,
    seulement à le CONTRÔLER après coup (combien de dates de naissance trouvées sont justes).

Méthode, pour chaque député :
    1. les homonymes : même nom (toutes les coupures prénom / nom possibles : « Jean-Marie Le Pen » → LE PEN), et un premier
       prénom d'état civil qui commence comme le sien ;
    2. on garde ceux qui avaient entre 23 et 85 ans à sa première élection, et qui sont morts après ;
    3. lien local : né ou mort dans un département où il a été élu.
Verdicts : « sûr » = un seul homonyme plausible, et il a le lien local ; « probable » = un seul homonyme, sans lien local,
ou plusieurs dont un seul a le lien local ; « ambigu » = plusieurs, impossible de choisir ; « absent » = personne
(mort avant 1970, vivant, ou nom d'usage différent de l'état civil : Chaban-Delmas est né Delmas).
Sortie : deces_deputes.parquet — une ligne par député, avec l'homonyme retenu (naissance, lieux, décès) et le verdict.
"""
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd
import pymysql

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("legislatures")
BASE = C.BASE
CACHE = Path(tempfile.gettempdir()) / "homonymes_deputes_insee.parquet"     # (la requête MariaDB prend ~10 minutes)


def sans_accent(t):
    t = unicodedata.normalize("NFD", str(t))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").upper()


def mots(t):
    """« Jean-Marie » et « Jean Marie » se comparent pareil ; l'apostrophe aussi (« D'Ornano » = « D ORNANO »)."""
    return re.sub(r"[\s'’\-]+", " ", sans_accent(t)).strip()


def noms_possibles(depute):
    """Toutes les coupures prénom | nom, et les écritures du nom que l'état civil peut avoir."""
    m = str(depute).split()
    for k in range(1, len(m)):
        prenom, nom = " ".join(m[:k]), " ".join(m[k:])
        n = sans_accent(nom)
        for v in {n, n.replace("'", " "), n.replace("'", ""), n.replace("-", " "), n.replace(" ", "-")}:
            yield prenom, v


def departement(code_commune):
    if not code_commune:
        return None
    return code_commune[:3] if code_commune.startswith("97") else code_commune[:2]


# 1. Les députés, leurs départements et leur première législature
con = duckdb.connect(str(BASE), read_only=True)
s = con.execute("""SELECT s.legislature, s.depute, s.lieu, s.acteur, year(l.debut) an
                   FROM sieges_legislature s JOIN legislatures l USING (legislature)
                   WHERE s.legislature <= 11 AND s.connu""").fetchdf()
s["dep"] = s["lieu"].str.extract(r"·\s*(\w+)\s*$")[0].str.upper().str.replace(r"^0?(\d)$", r"0\1", regex=True)
s["cle"] = s["acteur"].fillna(s["depute"])
dep = s.groupby("cle").agg(depute=("depute", "first"), acteur=("acteur", "first"), premier=("an", "min"),
                           legislatures=("legislature", lambda x: ",".join(map(str, sorted(set(x))))),
                           departements=("dep", lambda x: ",".join(sorted(set(x.dropna()))))).reset_index()
w = pd.read_parquet(ICI / "deputes_wikidata.parquet", columns=["qid", "naissance"]).dropna().drop_duplicates("qid")
dep = dep.merge(w.rename(columns={"qid": "acteur", "naissance": "naissance_wikidata"}), on="acteur", how="left")
print(f"{len(dep)} députés (1958-2002), dont {dep['naissance_wikidata'].notna().sum()} avec une date de naissance Wikidata")

# 2. Les homonymes dans le fichier des décès (une requête par paquet de 400 noms)
noms = sorted({v for d in dep["depute"] for _, v in noms_possibles(d)})
lignes = []
if CACHE.exists():
    insee = pd.read_parquet(CACHE)
else:
  m = pymysql.connect(host="localhost", user="root", charset="utf8mb4")
  with m.cursor() as c:
    for i in range(0, len(noms), 400):
        paquet = noms[i:i + 400]
        c.execute(f"""SELECT p.id, p.nom, p.prenom, n.date, cn.code, cn.libelle, d.date, cd.code, cd.libelle
                      FROM insee_naissance.personne p
                      JOIN insee_naissance.evenement n ON n.personne_id = p.id AND n.type_evenement_id = 1
                      LEFT JOIN insee_naissance.lieu ln ON ln.id = n.lieu_id LEFT JOIN insee_naissance.commune cn ON cn.id = ln.commune_id
                      JOIN insee_deces.evenement d ON d.personne_id = p.id
                      LEFT JOIN insee_naissance.lieu ld ON ld.id = d.lieu_id LEFT JOIN insee_naissance.commune cd ON cd.id = ld.commune_id
                      WHERE p.nom IN ({",".join(["%s"] * len(paquet))})""", paquet)
        lignes += c.fetchall()
  m.close()
  insee = pd.DataFrame(lignes, columns=["id_insee", "nom", "prenoms", "naissance", "commune_naissance", "lieu_naissance",
                                        "deces", "commune_deces", "lieu_deces"]).drop_duplicates("id_insee")
  insee.to_parquet(CACHE, index=False)
insee["nom_mots"] = insee["nom"].map(mots)
insee["prenoms_mots"] = insee["prenoms"].map(mots)
par_nom = {k: g for k, g in insee.groupby("nom_mots")}
print(f"{len(insee)} homonymes possibles dans le fichier des décès")

# 3. Les verdicts
resultats = []
for _, d in dep.iterrows():
    deps = set(d["departements"].split(",")) if d["departements"] else set()
    cands = []
    for prenom, nom in noms_possibles(d["depute"]):
        g = par_nom.get(mots(nom))
        if g is None:
            continue
        p = mots(prenom)
        g = g[g["prenoms_mots"].str.startswith(p + " ") | (g["prenoms_mots"] == p)]
        cands.append(g)
    c = pd.concat(cands).drop_duplicates("id_insee") if cands else insee.iloc[0:0]
    # vivant à sa première élection : né entre 85 et 23 ans avant, mort après
    age = d["premier"] - pd.to_datetime(c["naissance"], errors="coerce").dt.year
    c = c[(age >= 23) & (age <= 85) & (pd.to_datetime(c["deces"], errors="coerce").dt.year >= d["premier"])]
    local = c[c["commune_naissance"].map(departement).isin(deps) | c["commune_deces"].map(departement).isin(deps)]
    if len(c) == 0:
        verdict, choix = "absent", None
    elif len(c) == 1:
        verdict, choix = ("sûr" if len(local) == 1 else "probable"), c.iloc[0]
    elif len(local) == 1:
        verdict, choix = "probable", local.iloc[0]
    else:
        verdict, choix = "ambigu", None
    r = {"depute": d["depute"], "acteur": d["acteur"], "legislatures": d["legislatures"], "departements": d["departements"],
         "verdict": verdict, "homonymes": len(c), "naissance_wikidata": d["naissance_wikidata"]}
    if choix is not None:
        r.update({k: choix[k] for k in ["id_insee", "nom", "prenoms", "naissance", "lieu_naissance", "deces", "lieu_deces"]})
    resultats.append(r)
t = pd.DataFrame(resultats)
t.to_parquet(ICI / "deces_deputes.parquet", index=False)

# 4. Le contrôle : la date de naissance trouvée est-elle celle que donne Wikidata ?
print("\nVerdicts :")
print(t["verdict"].value_counts().to_string())
ctrl = t[t["naissance_wikidata"].notna() & t["naissance"].notna()].copy()
ctrl["juste"] = pd.to_datetime(ctrl["naissance"]).dt.date == pd.to_datetime(ctrl["naissance_wikidata"], errors="coerce").dt.date
print("\nContrôle avec Wikidata (même date de naissance) :")
print(ctrl.groupby("verdict")["juste"].agg(["count", "sum", "mean"]).rename(columns={"count": "contrôlés", "sum": "justes", "mean": "taux"}).to_string())
print("\nLes « sûrs » dont la date ne correspond pas (à regarder à la main) :")
faux = ctrl[(ctrl["verdict"] == "sûr") & ~ctrl["juste"]]
print(faux[["depute", "departements", "naissance_wikidata", "naissance", "lieu_naissance", "deces", "lieu_deces"]].to_string())
