"""Les votes des députés : qui a voté quoi aux scrutins publics de l'Assemblée (et du Congrès).

Tables vote et vote_depute (base_appli.py ← donnees/votes/ ; brancher_modele.py
relie chaque vote à une personne du modèle) :
    depuis 2012   tous les scrutins publics, député par député (open data de l'Assemblée)
    avant 2012    les grands votes de l'histoire : pages d'analyse du site de l'Assemblée (1998-2010) et Journal officiel
                  (1959-1991 : PDF numérisés ; tant que la liste n'est pas lue sans faute, seul le résultat officiel est gardé)
"""
from functools import lru_cache

import duckdb
import pandas as pd

from lecture import donnees as d
from interface import theme

# Les grands votes, dans l'ordre de l'histoire : (libellé dans la liste, identifiant du scrutin)
GRANDS_VOTES = [
    ("1959 · Loi Debré (école privée)", "JO1959-debre"),
    ("1962 · Censure du gouvernement Pompidou", "JO1962-censure"),
    ("1974 · Loi Veil (IVG)", "JO1974-veil"),
    ("1981 · Abolition de la peine de mort", "JO1981-peine-de-mort"),
    ("1981 · Dépénalisation de l'homosexualité", "JO1981-homosexualite"),
    ("1988 · RMI", "JO1988-rmi"),
    ("1990 · Loi Gayssot", "JO1990-gayssot"),
    ("1990 · Loi Évin", "JO1990-evin"),
    ("1991 · Guerre du Golfe", "JO1991-golfe"),
    ("1998 · 35 heures", "AN11-00093"),
    ("2004 · Signes religieux à l'école", "AN12-00436"),
    ("2004 · Loi Leonetti (fin de vie)", "AN12-00678"),
    ("2007 · Peine de mort interdite par la Constitution (Congrès)", "AN12-01094"),
    ("2008 · Révision constitutionnelle, à une voix (Congrès)", "CONGRES2008"),
    ("2008 · Afghanistan", "AN13-00195"),
    ("2010 · Voile intégral interdit", "AN13-00595"),
    ("2010 · Retraite à 62 ans", "AN13-00646"),
    ("2013 · Mariage pour tous", "AN14-00511"),
    ("2015 · Irak, après Charlie Hebdo", "AN14-00998"),
    ("2015 · État d'urgence, après le 13 Novembre", "AN14-01191"),
    ("2016 · Déchéance de nationalité (protection de la Nation)", "AN14-01237"),
    ("2021 · Bioéthique (PMA pour toutes)", "AN15-03855"),
    ("2023 · Retraites : censure rejetée à 9 voix", "AN16-01240"),
    ("2024 · L'IVG dans la Constitution", "AN16-03289"),
    ("2024 · Censure du gouvernement Barnier", "AN17-00519"),
    ("2025 · Aide à mourir", "AN17-02107"),
]
POSITIONS = {"pour": "#2E9E47", "contre": "#C62828", "abstention": "#C76E00", "non-votant": "#8C939D"}     # (≥ 3 : 1 sur blanc)
ABSENTS = ("absent", "sans vote publié")      # (petite pastille de la couleur du groupe)
COULEUR_ABSENT = "#D5D9DE"                     # (barres et cases : texte noir dessus)

# De gauche à droite : les sigles des groupes depuis 2012 ; les autres (pages web, Congrès) d'après les mots de leur nom
ORDRE_SIGLES = ["LFI-NFP", "LFI-NUPES", "LFI", "FI", "GDR-NUPES", "GDR", "ECOLO", "ECOS", "SOC", "SRC", "SER", "NG", "RRDP", "LT", "LIOT",
                "DEM", "MODEM", "EPR", "RE", "LAREM", "REM", "HOR", "AGIR", "UAI", "UDI", "UDI-I", "UDI-A", "UDI_I", "DR", "LR", "UMP",
                "UDDPLR", "RN", "NI"]
# la famille de chaque sigle (pour la couleur quand l'Assemblée n'en donne pas, comme en 2012-2017)
FAMILLE_SIGLE = {**dict.fromkeys(["LFI-NFP", "LFI-NUPES", "LFI", "FI"], "insoumis"), **dict.fromkeys(["GDR-NUPES", "GDR"], "communiste"),
                 **dict.fromkeys(["ECOLO", "ECOS"], "écologiste"), **dict.fromkeys(["SOC", "SRC", "SER", "NG"], "socialiste"),
                 "RRDP": "divers gauche", **dict.fromkeys(["LT", "LIOT"], "divers centre"),
                 **dict.fromkeys(["DEM", "MODEM", "EPR", "RE", "LAREM", "REM"], "centre / majorité"),
                 **dict.fromkeys(["HOR", "AGIR", "UAI", "UDI", "UDI-I", "UDI-A", "UDI_I"], "centre droit"),
                 **dict.fromkeys(["DR", "LR", "UMP"], "droite"), "UDR": "union extrême droite", "RN": "extrême droite", "NI": "divers"}
MOTS_GROUPES = [("communiste", "communiste"), ("gauche democrate", "communiste"), ("ecolog", "écologiste"), ("verts", "écologiste"),
                ("socialiste", "socialiste"), ("radical", "divers gauche"), ("rassemblement democratique", "divers gauche"),
                ("union pour la democratie", "centre / majorité"), ("nouveau centre", "centre droit"), ("union centriste", "centre droit"),
                ("centriste", "centre droit"), ("mouvement populaire", "droite"), ("republicains", "droite"), ("independants", "divers droite"),
                ("non inscrit", "divers"), ("reunion administrative", "divers")]


def disponible():
    try:
        return d.sql("SELECT count(*) n FROM vote")["n"].iloc[0] > 0
    except duckdb.Error:
        return False


@lru_cache(maxsize=None)
def scrutin(sid):
    t = d.sql("""SELECT v.code scrutin, v.legislature_id legislature, v.date, v.objet, v.pour, v.contre, v.abstention,
                     s.libelle source, v.complet, v.pour_lus, v.contre_lus
              FROM vote v LEFT JOIN modele.source s ON s.id = v.source_id WHERE v.code = ?""", [sid])
    return t.iloc[0] if len(t) else None


def _famille(groupe):
    if groupe in FAMILLE_SIGLE:
        return FAMILLE_SIGLE[groupe]
    g = d.normaliser(groupe or "")
    return next((f for mot, f in MOTS_GROUPES if mot in g), "divers")


@lru_cache(maxsize=8)
def votes(sid):
    """Les votes d'un scrutin, un député par ligne, avec le rang de son groupe (gauche → droite) et la couleur du groupe."""
    # (le député : sa personne dans le modèle ; le nom écrit dans le scrutin seulement quand on n'a pas su qui c'est)
    # (la circonscription écrite comme dans legislatures.en_fonction : « 1re circonscription · Ain »)
    t = d.sql("""SELECT vd.personne_id, coalesce(p.prenoms || ' ' || p.nom_usage, vd.nom_non_identifie) depute, gr.code groupe,
                        gr.couleur, pv.libelle position,
                        CASE WHEN zc.id IS NOT NULL THEN CAST(split_part(zc.code, '-', 2) AS INTEGER)
                          || CASE split_part(zc.code, '-', 2) WHEN '01' THEN 're' ELSE 'e' END || ' circonscription · ' || zd.libelle END lieu
                 FROM vote_depute vd JOIN vote v ON v.id = vd.vote_id
                 JOIN modele.position_vote pv ON pv.id = vd.position_id
                 LEFT JOIN modele.personne p ON p.id = vd.personne_id LEFT JOIN modele.groupe gr ON gr.id = vd.groupe_id
                 LEFT JOIN modele.zone zc ON zc.id = vd.circonscription_id LEFT JOIN modele.zone zd ON zd.id = zc.parent_id
                 WHERE v.code = ?""", [sid])
    if "lieu" not in t:
        t["lieu"] = None
    if t.empty:
        return t
    t["groupe"] = t["groupe"].fillna("?")
    fam = {g: _famille(g) for g in t["groupe"].unique()}
    rang = {g: ORDRE_SIGLES.index(g) if g in ORDRE_SIGLES else theme.ORDRE_FAMILLES.index(fam[g]) * 1.8 for g in fam}
    t["rang"] = t["groupe"].map(rang)
    t["couleur"] = [c if isinstance(c, str) and c else theme.FAMILLES[fam[g]] for c, g in zip(t["couleur"], t["groupe"])]
    ordre_pos = {p: i for i, p in enumerate(POSITIONS)}
    t["ordre_pos"] = t["position"].map(ordre_pos).fillna(9)
    return t.sort_values(["rang", "groupe", "ordre_pos", "depute"]).reset_index(drop=True)


def libelle(sid):
    for lib, s in GRANDS_VOTES:
        if s == sid:
            return lib
    s = scrutin(sid)
    return f"{s['date']:%d/%m/%Y} · {s['objet'][:90]}" if s is not None else sid


def chercher(texte, n=60):
    """Les scrutins depuis 2012 dont l'objet contient ces mots (« mariage », « retraites »…), les plus récents d'abord."""
    mots = [m for m in d.normaliser(texte).split() if len(m) > 2]
    if not mots:
        return []
    t = d.sql("SELECT code scrutin, date, objet FROM vote WHERE legislature_id IS NOT NULL ORDER BY date DESC")
    objet = t["objet"].map(d.normaliser)
    garde = pd.Series(True, index=t.index)
    for m in mots:
        garde &= objet.str.contains(m, regex=False)
    t = t[garde].head(n)
    return [(f"{dt:%d/%m/%Y} · {o[:110]}", s) for s, dt, o in zip(t["scrutin"], t["date"], t["objet"])]


def parcours(personne_id, depute=None):
    """Ce que ce député (sa personne ; à défaut, le nom écrit dans le scrutin) a voté aux grands votes : [(libellé, position)]."""
    ids = [s for _, s in GRANDS_VOTES]
    marque = ",".join("?" * len(ids))
    if personne_id == personne_id and personne_id is not None:
        t = d.sql(f"""SELECT v.code scrutin, pv.libelle position FROM vote_depute vd JOIN vote v ON v.id = vd.vote_id
                      JOIN modele.position_vote pv ON pv.id = vd.position_id WHERE vd.personne_id = ? AND v.code IN ({marque})""",
                  [int(personne_id)] + ids)
    else:
        t = d.sql(f"""SELECT v.code scrutin, pv.libelle position FROM vote_depute vd JOIN vote v ON v.id = vd.vote_id
                      JOIN modele.position_vote pv ON pv.id = vd.position_id WHERE vd.nom_non_identifie = ? AND v.code IN ({marque})""",
                  [depute] + ids)
    pos = dict(zip(t["scrutin"], t["position"]))
    return [(lib, pos[s]) for lib, s in GRANDS_VOTES if s in pos]


def vote_de(nom, sid):
    """La position d'un député (nom tapé, même partiel, sans accents) à ce scrutin : liste de (député, groupe, position)."""
    t = votes(sid)
    if t.empty or not nom.strip():
        return []
    cle = d.normaliser(nom)
    x = t[t["depute"].map(d.normaliser).str.contains(cle, regex=False)]
    return list(zip(x["depute"], x["groupe"], x["position"]))
