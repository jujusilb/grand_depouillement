"""
fabriquer_legislatures.py — Les 17 législatures de la Ve République, siège par siège : qui y siégeait (quand on le sait).

    py fabriquer_legislatures.py

Sources :
    XII → XVII (2002 → aujourd'hui)  ../parlement/brut/amo30/amo30.zip (Assemblée nationale, open data) : chaque député, ses mandats
                                      (dates, circonscription) et ses groupes (dates, sigle, couleur officielle) → tout le monde est connu
    IX → XI (1988 → 2002)            CDSP (data/tri_parquet) : l'élu de chaque circonscription, nommé, avec sa nuance officielle
    I → VII (1958 → 1986)            CDSP : le courant arrivé en tête dans chaque circonscription (code officiel : UNR, SFIO, COM…) ;
                                      le nom de l'élu vient de Wikidata (deputes_wikidata.parquet ← wikidata_deputes.py), retrouvé
                                      par sa circonscription (« deuxième circonscription de l'Ain ») — sinon petite pastille
    VIII (1986 → 1988)               scrutin proportionnel par département : les élus de Wikidata, avec leur groupe (ou leur parti)
Règle de l'élu (1958-1997) : le 1er du 2nd tour s'il y en a eu un dans la circonscription, sinon le 1er du 1er tour.

Sorties : legislatures.parquet · sieges_legislature.parquet (la composition au début de la législature)
          mandats_deputes.parquet · groupes_deputes.parquet (XII → XVII, avec les dates : qui siégeait le jour d'un vote)
"""
import json
import sys
import re
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("legislatures")
AMO = C.DONNEES / "parlement" / "brut" / "amo30" / "amo30.zip"
TRI = C.COLLECTE / "tri_parquet"

LEGISLATURES = [  # numéro, début, fin, sièges, année des législatives
    (1, "1958-12-09", "1962-10-09", 579, 1958), (2, "1962-12-06", "1967-04-02", 482, 1962), (3, "1967-04-03", "1968-05-30", 487, 1967),
    (4, "1968-07-11", "1973-04-01", 487, 1968), (5, "1973-04-02", "1978-04-02", 490, 1973), (6, "1978-04-03", "1981-05-22", 491, 1978),
    (7, "1981-07-02", "1986-04-01", 491, 1981), (8, "1986-04-02", "1988-05-14", 577, 1986), (9, "1988-06-23", "1993-04-01", 577, 1988),
    (10, "1993-04-02", "1997-04-21", 577, 1993), (11, "1997-06-12", "2002-06-18", 577, 1997), (12, "2002-06-19", "2007-06-19", 577, 2002),
    (13, "2007-06-20", "2012-06-19", 577, 2007), (14, "2012-06-20", "2017-06-20", 577, 2012), (15, "2017-06-21", "2022-06-21", 577, 2017),
    (16, "2022-06-22", "2024-06-09", 577, 2022), (17, "2024-07-01", None, 577, 2024),
]


def romain(n):
    r = ""
    for v, s in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            r += s
            n -= v
    return r


def sans_accent(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def liste(x):
    return x if isinstance(x, list) else [x] if x else []


# ---------------------------------------------------------------- XII → XVII : l'open data de l'Assemblée
z = zipfile.ZipFile(AMO)
groupes_info, mandats, groupes = {}, [], []
for n in z.namelist():
    if "/organe/" in n:
        o = json.loads(z.read(n))["organe"]
        if o.get("codeType") == "GP":
            groupes_info[o["uid"]] = (o.get("libelleAbrev") or o.get("libelleAbrege"), o.get("libelle"), o.get("couleurAssociee"))
for n in z.namelist():
    if "/acteur/" not in n:
        continue
    a = json.loads(z.read(n))["acteur"]
    uid = a["uid"]["#text"] if isinstance(a["uid"], dict) else a["uid"]
    i = a["etatCivil"]["ident"]
    nom = f"{i['prenom']} {i['nom']}"
    for m in liste(a["mandats"]["mandat"]):
        if m.get("typeOrgane") == "ASSEMBLEE" and m.get("legislature"):
            lieu = ((m.get("election") or {}).get("lieu") or {})
            num = lieu.get("numCirco")
            mandats.append((uid, nom, int(m["legislature"]), m.get("dateDebut"), m.get("dateFin"),
                            f"{int(num)}{'re' if num and int(num) == 1 else 'e'} circonscription · {lieu.get('departement', '')}" if num else "",
                            lieu.get("numDepartement"), num))
        elif m.get("typeOrgane") == "GP":
            ref = (m.get("organes") or {}).get("organeRef")
            sigle, libelle, couleur = groupes_info.get(ref, (None, None, None))
            if sigle:
                groupes.append((uid, m.get("dateDebut"), m.get("dateFin"), sigle, libelle, couleur))
mandats = pd.DataFrame(mandats, columns=["acteur", "depute", "legislature", "debut", "fin", "lieu", "departement", "circo"])
groupes = pd.DataFrame(groupes, columns=["acteur", "debut", "fin", "groupe", "groupe_libelle", "couleur"])
for t in (mandats, groupes):
    t["debut"] = pd.to_datetime(t["debut"]); t["fin"] = pd.to_datetime(t["fin"])

sieges = []
for num, debut, fin, nb, an in LEGISLATURES:
    d0 = pd.Timestamp(debut)
    if num >= 12:
        # la composition au début : les mandats qui commencent dans le premier mois ; le groupe du député à ce moment-là
        # la rentrée = le premier mandat de la législature (une semaine après la date officielle en 2024) ;
        # un député par circonscription : celui dont le mandat dure le plus (pas le ministre qui laisse aussitôt sa place)
        m = mandats[mandats["legislature"] == num].copy()
        rentree = d0                                    # (le mandat commence le jour de l'élection, parfois avant la rentrée)
        m = m[m["debut"] <= d0 + pd.Timedelta(days=10)]
        m["duree"] = (m["fin"].fillna(pd.Timestamp("2100-01-01")) - m["debut"]).dt.days
        m = m.sort_values("duree", ascending=False).drop_duplicates(["departement", "circo"]).drop_duplicates("acteur")
        for r in m.itertuples():
            # son groupe : le dernier choisi dans le premier mois (à la rentrée, tout le monde est d'abord « non inscrit »)
            g = groupes[(groupes["acteur"] == r.acteur) & (groupes["debut"] >= rentree - pd.Timedelta(days=20))
                        & (groupes["debut"] <= rentree + pd.Timedelta(days=30))].sort_values("debut").tail(1)
            sigle, couleur = (g["groupe"].iloc[0], g["couleur"].iloc[0]) if len(g) else ("?", None)
            sieges.append((num, r.depute, sigle, couleur, r.lieu, True, r.acteur))

# ---------------------------------------------------------------- I → XI : les élus d'après le CDSP


def lire(an, tour):
    f = sorted((TRI / f"{an}_legi_t{tour}" / "resultats").glob(f"cdsp-legi{an}t{tour}-circ*.parquet")) if tour else \
        sorted((TRI / f"{an}_legi_t1" / "resultats").glob(f"cdsp-legi{an}-circ*.parquet"))
    return pd.read_parquet(f[0]) if f else None


def col(t, motif):
    return next((c for c in t.columns if re.match(motif, sans_accent(c))), None)


def gagnants(t):
    """Pour chaque circonscription : (clé, nom ou None, nuance officielle) du 1er en voix."""
    sortie = {}
    c_dep, c_circ, c_nom = col(t, r"code dep"), col(t, r"circonscription"), col(t, r"departement")
    blocs = sorted({int(m.group(1)) for c in t.columns for m in [re.match(r"^(\d+) voix$", sans_accent(c))] if m})
    for _, r in t.iterrows():
        dep = str(r[c_dep]).strip().removesuffix(".0")
        dep = dep.zfill(2) if dep.isdigit() else dep
        cle = (dep, str(r[c_circ]).removesuffix(".0"))
        if c_nom:
            NOMS_DEP[cle[0]] = sans_accent(r[c_nom]).replace(" ", "-")
        best = None
        if blocs:
            for k in blocs:
                v = pd.to_numeric(r.get(f"{k} voix"), errors="coerce")
                if v == v and v and (best is None or v > best[0]):
                    nom = " ".join(str(r.get(f"{k} {x}") or "").strip().title() for x in ("Prénom candidat", "Nom candidat")).strip()
                    best = (v, nom or None, str(r.get(f"{k} nuance") or "").strip() or "?")
        else:
            for c in t.columns:
                m = re.search(r"\(([^)]+)\)\s*$", str(c))
                if not m or m.group(1) == "%":
                    continue
                v = pd.to_numeric(r[c], errors="coerce")
                if v == v and v and (best is None or v > best[0]):
                    best = (v, None, m.group(1))
            if best is None:          # (1986 : les colonnes sont les codes eux-mêmes)
                for c in t.columns:
                    if re.fullmatch(r"[A-Z][A-Z\- ]{1,20}", str(c)):
                        v = pd.to_numeric(r[c], errors="coerce")
                        if v == v and v and (best is None or v > best[0]):
                            best = (v, None, str(c))
        if best:
            sortie[cle] = best
    return sortie


# ---------------------------------------------------------------- Wikidata : les noms des élus de 1958 à 1988
WD = pd.read_parquet(ICI / "deputes_wikidata.parquet") if (ICI / "deputes_wikidata.parquet").exists() else None
PARTIS = pd.read_parquet(ICI / "partis_wikidata.parquet") if (ICI / "partis_wikidata.parquet").exists() else None
QID_LEG = {1: "Q3154303", 2: "Q3146705", 3: "Q3146694", 4: "Q2380278", 5: "Q3555150", 6: "Q3552959", 7: "Q3552950", 8: "Q3552944"}
NOMS_DEP = {}


def _ieme(mot):
    return {"un": "un", "cinq": "cinqu", "neuf": "neuv"}.get(mot, mot[:-1] if mot.endswith("e") else mot) + "ieme"


UNITES = ["un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze", "treize", "quatorze",
          "quinze", "seize"]
ORDINAUX = {"premiere": 1, "premier": 1, **{_ieme(m): i for i, m in enumerate(UNITES, 1)}}
ORDINAUX.update({"dix-septieme": 17, "dix-huitieme": 18, "dix-neuvieme": 19})
for dz, base in ((20, "vingt"), (30, "trente")):
    ORDINAUX[base + "ieme"] = dz
    ORDINAUX[base + "-et-unieme"] = dz + 1
    ORDINAUX.update({f"{base}-{_ieme(m)}": dz + i for i, m in enumerate(UNITES[1:9], 2)})


# les départements d'avant 1968 : le CDSP les range sous le code d'aujourd'hui (Seine → 75, Seine-et-Oise → 78)
ANCIENS_DEP = {"seine": "paris", "seine-et-oise": "yvelines", "reunion": "la-reunion"}


def circo_wikidata(libelle):
    """« deuxième circonscription de l'Ain » → (« ain », 2) ; None si ce n'est pas une circonscription numérotée."""
    m = re.match(r"([a-z\-]+) circonscription (?:de la |de l'|du |des |de |d')(.+)$", sans_accent(libelle or ""))
    if not m or m.group(1) not in ORDINAUX:
        return None
    dep = re.sub(r"-de-\d{4}-a-\d{4}$", "", m.group(2).strip().replace(" ", "-"))      # (« seine de 1958 à 1967 »)
    return ANCIENS_DEP.get(dep, dep), ORDINAUX[m.group(1)]


def code_groupe(texte):
    """Le groupe ou le parti (Wikidata) → un code court, comme les nuances officielles (pour la couleur et le rang)."""
    t = sans_accent(texte or "")
    if "socialiste unifie" in t or "internationale ouvriere" in t:
        return "NI"
    for mot, code in (("communiste", "COM"), ("socialiste", "SOC"), ("radicaux de gauche", "MRG"), ("radical de gauche", "MRG"),
                      ("front national", "FN"), ("rassemblement national", "FN"), ("parti radical", "UDF"),
                      ("rassemblement pour la republique", "RPR"), ("union pour la democratie", "UDF"), ("republicain", "UDF"),
                      ("centre des democrates sociaux", "UDF"), ("non inscrit", "NI")):
        if mot in t:
            return code
    return "NI" if t else "?"


def elus_wikidata(num, debut):
    """Les députés Wikidata du début de la législature, avec le département (normalisé) et le n° de leur circonscription."""
    if WD is None:
        return pd.DataFrame()
    x = WD[WD["legislature_qid"] == QID_LEG[num]].copy()
    d0 = pd.Timestamp(debut)
    # au début : le mandat commence avant la rentrée + 30 jours (ou n'a pas de date)
    x = x[x["debut"].isna() | (x["debut"] <= d0 + pd.Timedelta(days=30))]
    # la circonscription : sur ce mandat, sinon sur un autre mandat de la même personne qui commence le même jour
    autres = WD[WD["circonscription"].notna()][["qid", "debut", "circonscription"]].drop_duplicates(["qid", "debut"])
    manque = x["circonscription"].isna()
    if manque.any():
        y = x[manque].drop(columns="circonscription").merge(autres, on=["qid", "debut"], how="left")
        x = pd.concat([x[~manque], y], ignore_index=True)
    c = x["circonscription"].map(circo_wikidata)
    x["dep_nom"] = [v[0] if v else None for v in c]
    x["num_circo"] = [v[1] if v else None for v in c]
    return x.sort_values("debut").drop_duplicates("qid")


for num, debut, fin, nb, an in LEGISLATURES:
    if num >= 12:
        continue
    if num == 8:
        # proportionnelle 1986 : les élus de Wikidata, leur département, leur groupe (sinon leur parti à cette date)
        x = elus_wikidata(8, debut)
        if len(x):
            d0 = pd.Timestamp(debut)
            # le parti en 1986 : celui dont les dates couvrent avril 1986, sinon un parti de 1986 parmi les siens (souvent sans dates)
            pa = PARTIS.copy() if PARTIS is not None else pd.DataFrame(columns=["qid", "parti", "debut", "fin"])
            pa["code"] = pa["parti"].map(code_groupe)
            pa = pa[pa["code"].isin(["COM", "SOC", "MRG", "UDF", "RPR", "FN"])]
            pa["couvre"] = (pa["debut"].isna() | (pa["debut"] <= d0)) & (pa["fin"].isna() | (pa["fin"] >= d0))
            pa["date_connue"] = pa["debut"].notna()
            parti = pa.sort_values(["couvre", "date_connue"], ascending=False).drop_duplicates("qid").set_index("qid")["code"]
            x = x[x["debut"].isna() | (x["debut"] <= d0 + pd.Timedelta(days=5))]       # (les remplaçants arrivés plus tard : non)
            for r in x.head(nb).itertuples():
                g = code_groupe(r.groupe) if isinstance(r.groupe, str) else parti.get(r.qid, "?")
                lieu = re.sub(r"^(circonscription|departement) (de la |de l'|du |des |de |d')| de 1986 a 1988$", "",
                              sans_accent(r.circonscription)).title() if isinstance(r.circonscription, str) else ""
                sieges.append((8, r.depute, g, None, lieu, True, r.qid))
        continue
    t1, t2 = lire(an, 1), lire(an, 2)
    g1 = gagnants(t1) if t1 is not None else {}
    g2 = gagnants(t2) if t2 is not None else {}
    # 1958-1986 : le nom de l'élu d'après Wikidata, retrouvé par (département, n° de circonscription)
    wd = {}
    if num <= 7:
        x = elus_wikidata(num, debut)
        for r in x[x["num_circo"].notna()].itertuples():
            wd.setdefault((r.dep_nom, int(r.num_circo)), (r.depute, r.qid))
    for cle in sorted(set(g1) | set(g2)):
        v, nom, nuance = g2.get(cle) or g1[cle]
        qid = None
        if nom is None and cle[1].isdigit():
            nom, qid = wd.get((NOMS_DEP.get(cle[0]), int(cle[1])), (None, None))
        sieges.append((num, nom, nuance, None, f"{int(cle[1]) if cle[1].isdigit() else cle[1]}e circonscription · {cle[0]}",
                       nom is not None, qid))

s = pd.DataFrame(sieges, columns=["legislature", "depute", "groupe", "couleur", "lieu", "connu", "acteur"])
# les sièges que nos fichiers n'ont pas (Algérie et outre-mer en 1958, quelques députés de 2002…) : des pastilles inconnues
manque = []
for num, debut, fin, nb, an in LEGISLATURES:
    k = int((s["legislature"] == num).sum())
    manque += [(num, None, "?", None, "", False, None)] * max(0, nb - k)
s = pd.concat([s, pd.DataFrame(manque, columns=s.columns)], ignore_index=True)
leg = pd.DataFrame([(n, romain(n), pd.Timestamp(d), pd.Timestamp(f) if f else pd.NaT, nb, int((s["legislature"] == n).sum()),
                     int(((s["legislature"] == n) & s["connu"]).sum())) for n, d, f, nb, _ in LEGISLATURES],
                   columns=["legislature", "romain", "debut", "fin", "sieges", "sieges_lus", "deputes_connus"])
leg["source"] = ["CDSP (courant) + Wikidata (noms)" if n <= 7 else "Wikidata (proportionnelle)" if n == 8 else
                 "CDSP (élus nommés)" if n <= 11 else "Assemblée nationale (open data)" for n in leg["legislature"]]
leg.to_parquet(ICI / "legislatures.parquet", index=False)
s.to_parquet(ICI / "sieges_legislature.parquet", index=False)
mandats.to_parquet(ICI / "mandats_deputes.parquet", index=False)
groupes.to_parquet(ICI / "groupes_deputes.parquet", index=False)
print(leg.to_string(index=False))
