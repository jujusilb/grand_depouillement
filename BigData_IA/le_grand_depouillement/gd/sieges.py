"""Qui siège ? Les sièges recalculés à partir des voix, avec les règles du code électoral.

    Législatives      scrutin uninominal à 2 tours par circonscription (élu au 1er tour : > 50 % des exprimés ET ≥ 25 % des inscrits)
    Départementales   binôme par canton, mêmes règles → 2 sièges par canton
    Cantonales        un conseiller par canton (renouvellement par moitié : seulement les élus de CE scrutin)
    Régionales        listes : prime de 25 % des sièges à la liste arrivée en tête, le reste à la plus forte moyenne (listes ≥ 5 %)
    Municipales       communes à listes : prime de 50 %, le reste à la plus forte moyenne (listes ≥ 5 %) ;
                      petites communes (moins de 1 000 habitants, 3 500 avant 2014) : chaque candidat élu pour lui-même.
                      La taille du conseil : celle publiée par le ministère (2026), sinon celle de la loi (CGCT,
                      article L2121-2) selon la population municipale (Insee).
    Européennes       2019 et 2024 : circonscription nationale, plus forte moyenne entre les listes ≥ 5 %

Les circonscriptions législatives ne sont pas dans la base : on les reconstitue. Un candidat ne se présente que dans UNE
circonscription, donc deux bureaux qui ont un candidat en commun sont dans la même circonscription (composantes connexes).
Ce module ne dessine rien : il renvoie des tableaux (graphiques.py fait les hémicycles).

Les sièges sont calculés UNE fois pour toutes (figer_sieges.py, à la fin de preparer_donnees.py) et rangés dans la table
sieges_figes de la base : une ligne par (calcul, scrutin, zone), le résultat en JSON. L'appli relit la ligne demandée
(la commune cliquée…) sans rien recalculer ni charger le reste en mémoire ; si la table manque, on recalcule comme avant.
"""
import functools
import io
import json
import math
from functools import lru_cache

import duckdb
import pandas as pd

from gd import donnees as d


# --- les sièges figés -------------------------------------------------------------------------
def en_json(valeur):
    """Un résultat (None, nombre, texte, tableau, ou un tuple de tout ça) → texte JSON."""
    def coder(v):
        if isinstance(v, pd.DataFrame):
            return {"tableau": v.to_json(orient="split", index=False, date_format="iso", force_ascii=False)}
        if isinstance(v, tuple):
            return {"tuple": [coder(x) for x in v]}
        return v.item() if hasattr(v, "item") else v
    return json.dumps(coder(valeur), ensure_ascii=False)


def depuis_json(texte):
    def decoder(v):
        if isinstance(v, dict) and "tableau" in v:
            return pd.read_json(io.StringIO(v["tableau"]), orient="split", dtype=False)
        if isinstance(v, dict) and "tuple" in v:
            return tuple(decoder(x) for x in v["tuple"])
        return v
    return decoder(json.loads(texte))


CALCULER = False        # (figer_sieges.py le met à True : on calcule, on ne relit pas)


def fige(f):
    """Relit le résultat figé de f(scrutin[, zone]) s'il existe ; sinon le calcule."""
    @functools.wraps(f)
    def relire(scrutin, zone=""):
        if not CALCULER:
            try:
                # (rangé sous le 1er tour : le calcul trouve lui-même le tour décisif)
                t = d.sql("SELECT valeur FROM sieges_figes WHERE calcul = ? AND scrutin = ? AND zone = ?",
                          [f.__name__, _id_tour(scrutin, 1), str(zone)])
                if len(t):
                    return depuis_json(t.iloc[0, 0])
            except duckdb.Error:          # (pas de table sieges_figes : base d'avant)
                pass
        return f(scrutin, zone) if zone != "" else f(scrutin)
    relire.calculer = f
    return relire

# --- les tailles des assemblées (sièges, prime majoritaire) ------------------------------------
CONSEILS_REGIONAUX = {   # 2015 et 2021 (régions actuelles) : (sièges, prime). Corse, Martinique, Guyane : collectivités uniques
    "84": (204, 51), "27": (100, 25), "53": (83, 21), "24": (77, 20), "44": (169, 43), "32": (170, 43), "11": (209, 53),
    "28": (102, 26), "75": (183, 46), "76": (158, 40), "52": (93, 24), "93": (123, 31), "94": (63, 11),
    "01": (41, 11), "02": (51, 11), "03": (55, 11), "04": (45, 12),
}
SIEGES_EUROPEENS = {2019: 79, 2024: 81}


def plus_forte_moyenne(voix, sieges):
    """Répartition à la plus forte moyenne (méthode de d'Hondt) : {liste: voix} → {liste: sièges}."""
    voix = {k: v for k, v in voix.items() if v > 0}
    res = {k: 0 for k in voix}
    for _ in range(int(sieges)):
        if not voix:
            break
        k = max(voix, key=lambda x: (voix[x] / (res[x] + 1), voix[x]))
        res[k] += 1
    return res


def _id_tour(scrutin, tour):
    return scrutin.rsplit("_", 1)[0] + f"_t{tour}"


def _existe(scrutin):
    return scrutin in set(d.scrutins()["scrutin"])


# --- scrutins uninominaux / binominaux : une zone = une circonscription ou un canton -----------------
def _gagnants(scrutin_t1, zones):
    """zones : DataFrame (id_brut_miom, zone). Le gagnant de chaque zone : 1er tour s'il est élu d'emblée, sinon 2nd tour."""
    def agreger(s):
        p = d.sql(f"SELECT id_brut_miom, inscrits, exprimes FROM {d.P(s)}").merge(zones, on="id_brut_miom")
        r = d.sql(f"""SELECT l.id_brut_miom, r.qui, any_value(r.nuance) nuance, sum(r.voix) voix FROM {d.R(s)} r
                      JOIN bureau_lieu l USING (bureau_id) GROUP BY 1, 2""")
        r = r.merge(zones, on="id_brut_miom")
        tot = p.groupby("zone")[["inscrits", "exprimes"]].sum()
        v = r.groupby(["zone", "qui"]).agg(voix=("voix", "sum"), nuance=("nuance", "first")).reset_index()
        v = v.join(tot, on="zone")
        return v.sort_values(["zone", "voix"], ascending=[True, False])
    t1 = agreger(scrutin_t1)
    premiers = t1.groupby("zone").head(1).copy()
    premiers["tour"] = 1
    elus = premiers[(premiers["voix"] > premiers["exprimes"] / 2) & (premiers["voix"] >= premiers["inscrits"] / 4)]
    reste = set(t1["zone"]) - set(elus["zone"])
    resultat = [elus]
    t2_id = _id_tour(scrutin_t1, 2)
    if reste and _existe(t2_id):
        t2 = agreger(t2_id)
        t2 = t2[t2["zone"].isin(reste)]
        g2 = t2.groupby("zone").head(1).copy()
        g2["tour"] = 2
        resultat.append(g2)
    g = pd.concat(resultat, ignore_index=True)
    g["pct"] = 100 * g["voix"] / g["exprimes"]
    return g[["zone", "qui", "nuance", "tour", "voix", "pct"]]


@lru_cache(maxsize=8)
def circonscriptions(scrutin_t1):
    """Chaque bureau → sa circonscription, reconstituée (bureaux reliés par un candidat commun, dans un même département)."""
    r = d.sql(f"""SELECT DISTINCT p.id_brut_miom, p.code_departement || '|' || r.qui AS cand
                 FROM {d.R(scrutin_t1)} r JOIN {d.P(scrutin_t1)} p USING (bureau_id)""")
    parent = {}

    def racine(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for cand, bureaux in r.groupby("cand")["id_brut_miom"]:
        b = list(bureaux)
        a = racine(b[0])
        for x in b[1:]:
            parent[racine(x)] = a
    z = pd.DataFrame({"id_brut_miom": list(parent)})
    z["zone"] = [racine(x) for x in z["id_brut_miom"]]
    # un nom lisible : la circonscription (découpage 2022) la plus fréquente parmi ses bureaux, sinon « département – n° »
    noms = d.sql("""SELECT zb.code id_brut_miom, c.libelle || ' (' || zd.code || ')' AS nom, zd.code dep
                    FROM modele.bureau b JOIN modele.zone zb ON zb.id = b.id
                    JOIN modele.zone c ON c.id = b.circonscription_id JOIN modele.zone zd ON zd.id = c.parent_id""")
    z = z.merge(noms, on="id_brut_miom", how="left")
    z["dep"] = z["dep"].fillna(z["id_brut_miom"].str[:2])
    libelle = z.groupby("zone").agg(nom=("nom", lambda s: s.mode().iloc[0] if s.notna().any() else None), dep=("dep", "first"))
    z = z[["id_brut_miom", "zone"]].join(libelle, on="zone")
    z["nom"] = z["nom"].fillna("Circonscription de " + z["dep"])
    return z


@lru_cache(maxsize=8)
@fige
def assemblee_nationale(scrutin):
    """Les députés élus à une législative : une ligne par circonscription (élu, nuance, tour, score)."""
    t1 = _id_tour(scrutin, 1)
    z = circonscriptions(t1)
    g = _gagnants(t1, z[["id_brut_miom", "zone"]])
    libelles = z.drop_duplicates("zone").set_index("zone")[["nom", "dep"]]
    return g.join(libelles, on="zone").sort_values(["dep", "nom"]).reset_index(drop=True)


@lru_cache(maxsize=8)
@fige
def conseils_departementaux(scrutin):
    """Départementales (binômes : 2 sièges par canton) ou cantonales (1 siège) : une ligne par canton, tous départements."""
    t1 = _id_tour(scrutin, 1)
    # (le canton de chaque bureau : celui d'aujourd'hui, bureau.canton_id — comme le faisaient déjà les codes de participation)
    z = d.sql(f"SELECT id_brut_miom, code_canton AS zone, code_departement dep, any_value(libelle_canton) nom "
              f"FROM {d.P(t1)} WHERE code_canton IS NOT NULL GROUP BY ALL")
    g = _gagnants(t1, z[["id_brut_miom", "zone"]])
    libelles = z.drop_duplicates("zone").set_index("zone")[["nom", "dep"]]
    g = g.join(libelles, on="zone")
    g["sieges"] = 2 if d.type_de(scrutin) == "Départementales" else 1
    return g.sort_values(["dep", "nom"]).reset_index(drop=True)


# --- scrutins de listes : prime majoritaire + plus forte moyenne ------------------------------------
def _voix_listes(scrutin, filtre_sql, params):
    r = d.sql(f"""SELECT r.qui, any_value(r.nuance) nuance, sum(r.voix) voix FROM {d.R(scrutin)} r JOIN {d.P(scrutin)} p USING (bureau_id)
                  WHERE {filtre_sql} GROUP BY 1 ORDER BY voix DESC""", params)
    e = d.sql(f"SELECT sum(exprimes) e, sum(inscrits) i FROM {d.P(scrutin)} p WHERE {filtre_sql}", params).iloc[0]
    return r, float(e["e"] or 0), float(e["i"] or 0)


def _avec_prime(r, exprimes, sieges, prime):
    """Prime à la liste en tête, puis plus forte moyenne entre les listes ≥ 5 % des exprimés (la liste en tête comprise)."""
    r = r.copy()
    r["sieges"] = 0
    if not len(r) or not sieges:
        return r
    r.loc[r.index[0], "sieges"] = prime
    eligibles = r[r["voix"] >= 0.05 * exprimes]
    for qui, n in plus_forte_moyenne(dict(zip(eligibles["qui"], eligibles["voix"])), sieges - prime).items():
        r.loc[r["qui"] == qui, "sieges"] += n
    r["pct"] = 100 * r["voix"] / exprimes if exprimes else 0
    return r


def tour_decisif(scrutin, filtre_sql, params, majorite_inscrits=False):
    """Le tour qui attribue les sièges : le 1er si une liste a la majorité absolue, sinon le 2nd (s'il a eu lieu)."""
    t1, t2 = _id_tour(scrutin, 1), _id_tour(scrutin, 2)
    r, e, i = _voix_listes(t1, filtre_sql, params)
    gagne = len(r) and r["voix"].iloc[0] > e / 2 and (not majorite_inscrits or r["voix"].iloc[0] >= i / 4)
    if not gagne and _existe(t2):
        r2, e2, i2 = _voix_listes(t2, filtre_sql, params)
        if len(r2):
            return t2, r2, e2
    return t1, r, e


@lru_cache(maxsize=32)
@fige
def conseil_regional(scrutin, region):
    if region not in CONSEILS_REGIONAUX or int(scrutin[:4]) < 2015:
        return None
    sieges, prime = CONSEILS_REGIONAUX[region]
    tour, r, e = tour_decisif(scrutin, "p.code_region = ?", [region])
    return tour, _avec_prime(r, e, sieges, prime), sieges


# --- la taille légale d'un conseil municipal (CGCT, article L2121-2, depuis 2014 ; 9 sièges sous 100 habitants avant) ----
TRANCHES = [(100, 7), (500, 11), (1500, 15), (2500, 19), (3500, 23), (5000, 27), (10000, 29), (20000, 33), (30000, 35),
            (40000, 39), (50000, 43), (60000, 45), (80000, 49), (100000, 53), (150000, 55), (200000, 59), (250000, 61),
            (300000, 65)]
POPULATION_LEGALE = {2008: 1999, 2014: 2011, 2020: 2017, 2026: 2023}     # (la population en vigueur le jour du vote)


def taille_legale(population, annee):
    for seuil, n in TRANCHES:
        if population < seuil:
            return 9 if n == 7 and annee < 2014 else n
    return 69


def seuil_listes(annee):
    """En dessous : candidats un par un (panachage). 3 500 habitants avant 2014, 1 000 ensuite, des listes partout en 2026."""
    return 3500 if annee < 2014 else 1000 if annee < 2026 else 0


@lru_cache(maxsize=8)
def populations(annee):
    """{commune: population municipale} de l'année qui fait foi pour l'élection (Insee, géographie 2025)."""
    an = POPULATION_LEGALE.get(annee, annee - 3)
    try:
        p = d.sql("SELECT z.code code_commune, p.population FROM population p JOIN modele.zone z ON z.id = p.zone_id "
                  "WHERE p.annee = ?", [an])
    except duckdb.Error:          # (base d'avant les populations)
        return {}
    return dict(zip(p["code_commune"], p["population"]))


def population(scrutin, commune, inscrits=0):
    """La population légale ; à défaut (commune fusionnée depuis), estimée par les inscrits (environ 3 inscrits pour 4 habitants)."""
    p = populations(int(scrutin[:4])).get(commune)
    return int(p) if p is not None else inscrits / 0.75


@lru_cache(maxsize=4)
def sieges_officiels(annee):
    """{commune: sièges du conseil municipal} publiés par le ministère (2026 seulement : « nombre de sièges à pourvoir »)."""
    if annee != 2026:
        return {}
    try:
        t = d.sql("SELECT code_commune, sieges_municipaux FROM sieges_2026")
    except duckdb.Error:
        return {}
    return dict(zip(t["code_commune"], t["sieges_municipaux"]))


def sieges_municipaux(scrutin, commune, inscrits=0):
    """Le nombre de sièges : celui publié par le ministère (2026), sinon la taille légale selon la population Insee, sinon
    (commune fusionnée depuis) la plus petite liste déposée, sinon une estimation par les inscrits.
    (La plus petite liste ne suffit pas : une liste peut avoir 2 candidats de plus que de sièges, et en 2026 2 de moins
    dans les petites communes — elle se trompait pour 4 communes sur 10.)"""
    an = int(scrutin[:4])
    n = sieges_officiels(an).get(commune)
    if n:
        return int(n)
    p = populations(an).get(commune)
    if p is not None:
        return taille_legale(int(p), an)
    base = scrutin.rsplit("_", 1)[0]
    n = d.sql("""SELECT min(n) FROM (SELECT l.id, count(*) n FROM modele.liste l JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                 JOIN modele.candidature c ON c.liste_id = l.id JOIN modele.zone z ON z.id = l.zone_id
                 WHERE e.code = ? AND z.niveau_id = ? AND z.code = ? AND l.conseil = 'municipal' GROUP BY l.id)""",
              [base, d.NIVEAU["commune"], commune]).iloc[0, 0]
    if not pd.isna(n) and n:
        return int(n)
    return taille_legale(inscrits / 0.75, an)


@lru_cache(maxsize=32)
@fige
def conseil_municipal(scrutin, commune):
    """(tour, listes avec leurs sièges, sièges, élus) ou None (petite commune sans listes, PLM, ou pas de listes déposées connues)."""
    if commune in d.VILLES_PLM:
        return None
    t1, t2 = _id_tour(scrutin, 1), _id_tour(scrutin, 2)
    r1, e1, i1 = _voix_listes(t1, "p.code_commune = ?", [commune])
    if not len(r1):
        return None
    if _sans_listes(scrutin, commune, i1):
        r2 = _voix_listes(t2, "p.code_commune = ?", [commune])[0] if _existe(t2) else None
        taille = sieges_municipaux(scrutin, commune, i1)
        return repartir_plurinominal(t1, r1, e1, i1, t2, r2, taille)
    sieges = sieges_municipaux(scrutin, commune, i1)
    tour, r, e = tour_decisif(scrutin, "p.code_commune = ?", [commune])
    # (les listes du 2nd tour 2014 manquent : on prend celles du 1er, retrouvées par leur tête de liste)
    for qui_tour in dict.fromkeys([tour, t1]):
        c = d.sql("""SELECT l.numero_panneau, c.rang ordre, p.prenoms || ' ' || p.nom_usage AS elu, p.nom_usage nom, p.sexe,
                            l.libelle libelle_liste, l.libelle_abrege libelle_abrege, c.tete_de_liste
                     FROM modele.candidature c JOIN modele.liste l ON l.id = c.liste_id
                     JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id JOIN modele.personne p ON p.id = c.personne_id
                     JOIN modele.zone z ON z.id = l.zone_id
                     WHERE e.code = ? AND sc.tour = ? AND z.niveau_id = ? AND z.code = ? AND l.conseil = 'municipal'
                     ORDER BY l.numero_panneau, c.rang""", [*d.election_tour(qui_tour), d.NIVEAU["commune"], commune])
        if len(c):
            break
    return repartir_municipal(tour, r, e, sieges, c)


def _sans_listes(scrutin, commune, inscrits=0):
    """2020 et avant : dans les petites communes, des candidats un par un. On le lit dans les candidatures déposées (pas de
    numéro de liste) ; sans elles (2008, 2014), on le déduit de la population."""
    t = d.sql("""SELECT count(*) FILTER (WHERE c.liste_id IS NULL) sans, count(*) n FROM modele.candidature c
                 JOIN modele.scrutin sc ON sc.id = c.scrutin_id JOIN modele.election e ON e.id = sc.election_id JOIN modele.zone z ON z.id = c.zone_id
                 WHERE e.code = ? AND sc.tour = 1 AND z.niveau_id = ? AND z.code = ? AND c.conseil = 'municipal'""",
              [scrutin.rsplit("_", 1)[0], d.NIVEAU["commune"], commune]).iloc[0]
    if t["n"] > 0:
        return t["sans"] == t["n"]
    return population(scrutin, commune, inscrits) < seuil_listes(int(scrutin[:4]))


def repartir_plurinominal(t1, r1, e1, i1, t2=None, r2=None, taille=11):
    """Petites communes (scrutin plurinominal, panachage) : chaque candidat est élu pour lui-même. Au 1er tour, ceux qui ont
    la majorité absolue des exprimés et au moins 25 % des inscrits ; au 2nd tour, les sièges qui restent aux mieux placés."""
    r1 = r1.sort_values("voix", ascending=False).reset_index(drop=True)
    elus1 = list(r1[(r1["voix"] > e1 / 2) & (r1["voix"] >= i1 / 4)]["qui"].head(taille))
    elus2 = []
    if len(elus1) < taille and r2 is not None and len(r2):
        r2 = r2[~r2["qui"].isin(elus1)].sort_values("voix", ascending=False)
        elus2 = list(r2["qui"].head(taille - len(elus1)))
    tour = t2 if elus2 else t1
    r = r1.copy()
    if elus2:                 # (les voix du tour où chacun a été élu)
        v2 = r2.set_index("qui")["voix"]
        r["voix"] = [v2.get(q, v) if q in elus2 else v for q, v in zip(r["qui"], r["voix"])]
    r["sieges"] = r["qui"].isin(elus1 + elus2).astype(int)
    r["pct"] = 100 * r["voix"] / e1 if e1 else 0
    r = r.sort_values(["sieges", "voix"], ascending=False).reset_index(drop=True)
    elus = pd.DataFrame({"liste": elus1 + elus2, "ordre": range(1, len(elus1) + len(elus2) + 1), "elu": elus1 + elus2, "sexe": None})
    return tour, r, taille, elus


def repartir_municipal(tour, r, e, sieges, c, prime=None):
    """Le calcul seul : r = voix des listes au tour décisif (rangées par voix), e = exprimés, c = les candidats de ce tour ;
    prime : 50 % des sièges sauf mention contraire (25 % pour Paris, Lyon, Marseille depuis 2026)."""
    if prime is None:
        prime = math.ceil(sieges / 2) if sieges > 4 else sieges // 2
    r = _avec_prime(r.sort_values("voix", ascending=False).reset_index(drop=True), e, sieges, prime)
    # les élus : les premiers de chaque liste, dans l'ordre (la tête de liste du résultat = son nom)
    c = c.copy()
    tetes = c[c["tete_de_liste"].fillna(False).astype(bool)].groupby("numero_panneau")["nom"].first().str.upper()
    c["tete"] = c["numero_panneau"].map(tetes)
    elus = []
    c["libelle_norme"] = c["libelle_liste"].map(d.normaliser)
    c["abrege_norme"] = c["libelle_abrege"].map(d.normaliser) if "libelle_abrege" in c else ""
    for qui, n in zip(r["qui"], r["sieges"]):
        # le résultat donne la tête de liste (« Michel CHAPUIS »), le nom (parfois tronqué) de la liste ou son sigle (« BDAVEPV »)
        q = d.normaliser(qui)
        liste = c[[(isinstance(t, str) and t in str(qui).upper()) or (bool(q) and (str(l).startswith(q) or a == q))
                   for t, l, a in zip(c["tete"], c["libelle_norme"], c["abrege_norme"])]]
        for _, x in liste.head(int(n)).iterrows():
            elus.append((qui, x["ordre"], x["elu"], x["sexe"]))
    return tour, r, sieges, pd.DataFrame(elus, columns=["liste", "ordre", "elu", "sexe"])


# --- Paris, Lyon, Marseille (code électoral, tableaux n° 2, 3 et 4) ---------------------------------------------------------
# Jusqu'en 2020 : chaque secteur élit ses conseillers municipaux (prime de 50 % dans le secteur, puis plus forte moyenne) ;
# le conseil municipal est la somme des secteurs. Depuis 2026 (loi du 11 août 2025) : toute la ville élit le conseil
# municipal sur une seule liste, prime de 25 % à la liste en tête (et à part, chaque secteur son conseil d'arrondissement).
def _secteurs_paris(sieges, centre=None):
    s = [(f"{i}e" if i > 1 else "1er", [f"751{i:02d}"], n) for i, n in enumerate(sieges, 1)]
    return ([("Paris Centre", ["75101", "75102", "75103", "75104"], centre)] + s[4:]) if centre else s


SECTEURS = {  # ville → [(depuis l'année, [(secteur, ses arrondissements, conseillers municipaux)])], le plus récent d'abord
    "75056": [(2020, _secteurs_paris([0, 0, 0, 0, 4, 3, 4, 3, 4, 7, 11, 10, 13, 10, 18, 13, 12, 15, 14, 14], centre=8)),
              (2014, _secteurs_paris([1, 2, 3, 2, 4, 3, 4, 3, 4, 7, 11, 10, 13, 10, 18, 13, 12, 15, 14, 14])),
              (0, _secteurs_paris([3, 3, 3, 3, 4, 3, 5, 3, 4, 6, 11, 10, 13, 10, 17, 13, 13, 14, 12, 13]))],
    "69123": [(0, [(f"{i}e" if i > 1 else "1er", [f"6938{i}"], n) for i, n in enumerate([4, 5, 12, 5, 8, 9, 9, 12, 9], 1)])],
    "13055": [(0, [(f"{s} ({'1er' if a == 1 else f'{a}e'} et {b}e)", [f"132{a:02d}", f"132{b:02d}"], n)
                   for s, a, b, n in [("I", 1, 7, 11), ("II", 2, 3, 8), ("III", 4, 5, 11), ("IV", 6, 8, 15), ("V", 9, 10, 15),
                                      ("VI", 11, 12, 13), ("VII", 13, 14, 16), ("VIII", 15, 16, 12)]])],
}
FILTRE_ARRONDISSEMENTS = ("p.id_brut_miom IN (SELECT z.code FROM modele.zone z JOIN modele.zone m ON m.id = z.parent_id "
                          "WHERE z.niveau_id = 12 AND m.niveau_id = 9 AND m.code IN ({}))")


def secteurs(commune, annee):
    return next(s for depuis, s in SECTEURS[commune] if annee >= depuis)


def numero_secteur(commune, annee, arrondissement):
    """Le numéro du secteur d'un arrondissement (celui des zones « 75056SR17 ») : Paris et Lyon, le numéro de
    l'arrondissement (Paris Centre = 1 depuis 2020) ; Marseille, I à VIII."""
    if commune == "13055":
        return next(i for i, (_, arr, _) in enumerate(secteurs(commune, annee), 1) if arrondissement in arr)
    n = int(str(arrondissement)[-2:])
    return 1 if commune == "75056" and annee >= 2020 and n <= 4 else n


def _candidats_liste(scrutin, tour, niveau, code):
    """Les candidats des listes municipales d'une zone (commune ou secteur), au tour décisif (sinon au 1er : les listes
    du 2nd tour 2014 manquent), dans l'ordre de leur liste."""
    for qui_tour in dict.fromkeys([tour, _id_tour(scrutin, 1)]):
        c = d.sql("""SELECT l.numero_panneau, c.rang ordre, p.prenoms || ' ' || p.nom_usage AS elu, p.nom_usage nom, p.sexe,
                            l.libelle libelle_liste, l.libelle_abrege libelle_abrege, c.tete_de_liste
                     FROM modele.candidature c JOIN modele.liste l ON l.id = c.liste_id
                     JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                     JOIN modele.personne p ON p.id = c.personne_id JOIN modele.zone z ON z.id = l.zone_id
                     WHERE e.code = ? AND sc.tour = ? AND z.niveau_id = ? AND z.code = ? AND l.conseil = 'municipal'
                     ORDER BY l.numero_panneau, c.rang""", [*d.election_tour(qui_tour), d.NIVEAU[niveau], code])
        if len(c):
            return c
    return c


@lru_cache(maxsize=32)
def conseil_plm(scrutin, commune, arrondissement=None):
    """Le conseil municipal de Paris, Lyon ou Marseille : (listes avec leurs sièges et leur secteur, sièges, élus, note) ;
    avec un arrondissement (avant 2026) : seulement les conseillers municipaux élus dans son secteur.
    Les élus : les premiers de chaque liste, dans l'ordre (les listes déposées du secteur, ou de la ville en 2026)."""
    an = int(scrutin[:4])
    if an >= 2026:
        n = int(sieges_officiels(an)[commune])
        tour, r, e = tour_decisif(scrutin, "p.code_commune = ?", [commune])
        _, r, _, elus = repartir_municipal(tour, r, e, n, _candidats_liste(scrutin, tour, "commune", commune), math.ceil(n / 4))
        r = r.assign(secteur="toute la ville", tour=tour)
        return r, n, elus.assign(secteur="toute la ville"), (f"{n} sièges élus par toute la ville (réforme de 2025) : prime de 25 % à la liste en tête, le reste à "
                      f"la plus forte moyenne (listes ≥ 5 %), décidé au {'1er' if tour.endswith('t1') else '2nd'} tour.")
    morceaux, elus = [], []
    for i, (nom, arrondissements, n) in enumerate(secteurs(commune, an), 1):
        if arrondissement and arrondissement not in arrondissements:
            continue
        filtre = FILTRE_ARRONDISSEMENTS.format(", ".join("?" * len(arrondissements)))
        tour, r, e = tour_decisif(scrutin, filtre, arrondissements)
        if not len(r):
            continue
        code = f"{commune}SR{numero_secteur(commune, an, arrondissements[0]):02d}"
        _, r, _, e_ = repartir_municipal(tour, r, e, n, _candidats_liste(scrutin, tour, "secteur", code))
        morceaux.append(r.assign(secteur=nom, tour=tour))
        elus.append(e_.assign(secteur=nom))
    if not morceaux:
        return None
    r = pd.concat(morceaux, ignore_index=True)
    n = int(r["sieges"].sum())
    return r, n, pd.concat(elus, ignore_index=True), (f"{n} conseillers municipaux élus {'dans ce secteur' if arrondissement else 'secteur par secteur'} : "
                  "dans chaque secteur, prime de 50 % à la liste en tête, le reste à la plus forte moyenne (listes ≥ 5 %), "
                  "au tour décisif du secteur. (Les conseillers d'arrondissement, élus en plus, ne sont pas comptés.)")


@lru_cache(maxsize=32)
@fige
def delegation_europeenne(scrutin):
    an = int(scrutin[:4])
    if an not in SIEGES_EUROPEENS:
        return None
    r, e, _ = _voix_listes(scrutin, "TRUE", [])
    eligibles = r[r["voix"] >= 0.05 * e]
    s = plus_forte_moyenne(dict(zip(eligibles["qui"], eligibles["voix"])), SIEGES_EUROPEENS[an])
    r["sieges"] = r["qui"].map(s).fillna(0).astype(int)
    r["pct"] = 100 * r["voix"] / e
    return r, SIEGES_EUROPEENS[an]
