"""Les partis politiques et leurs gens, lus dans le modèle (modele.*) : la fiche d'un parti (logos, ascendance,
coalitions, idéologies, adhérents, candidats), les plus anciens, les écoles de leurs adhérents, leurs personnalités,
et le parti du gouvernement qui a porté chaque grande loi.

Une adhésion compte à une date seulement si elle la couvre ET si le parti existait alors : Wikidata donne souvent des
adhésions sans dates (Michel Debré « RPR » en 1959, alors que le RPR naît en 1976).
"""
from functools import lru_cache

import pandas as pd

from lecture import donnees as d
from politique import votes as votes_deputes

# les grands votes qui sont des LOIS (pas une censure, ni l'approbation d'une intervention armée)
PAS_DES_LOIS = ("Censure", "censure", "Golfe", "Afghanistan", "Irak")
ADHESION_A = """(coalesce(a.date_debut, DATE '0001-01-01') <= {j} AND coalesce(a.date_fin, DATE '9999-12-31') >= {j}
                 AND coalesce(pa.date_creation, DATE '0001-01-01') <= {j} AND coalesce(pa.date_dissolution, DATE '9999-12-31') >= {j})"""


@lru_cache(maxsize=1)
def disponible():
    try:
        return d.sql("SELECT count(*) FROM modele.parti").iloc[0, 0] > 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def poids():
    """Chaque parti, ce qui le fait connaître dans la base : adhérents connus, candidats rattachés, logos."""
    a_des_logos = d.sql("SELECT count(*) FROM duckdb_tables() WHERE database_name = 'modele' AND table_name = 'parti_logo'").iloc[0, 0]
    lo = ("SELECT parti_id, count(*) logos FROM modele.parti_logo GROUP BY 1" if a_des_logos      # (une base d'avant les logos)
          else "SELECT NULL::INT parti_id, 0 logos WHERE FALSE")
    return d.sql(f"""
        WITH ad AS (SELECT parti_id, count(DISTINCT personne_id) adherents FROM modele.adhesion GROUP BY 1),
             inv AS (SELECT parti_id, count(*) candidats FROM modele.investiture GROUP BY 1),
             lo AS ({lo})
        SELECT p.id, p.libelle, p.sigle, p.date_creation, p.date_dissolution, np.libelle nature, p.code_cnccfp,
               coalesce(ad.adherents, 0) adherents, coalesce(inv.candidats, 0) candidats, coalesce(lo.logos, 0) logos,
               f.couleur
        FROM modele.parti p LEFT JOIN modele.nature_parti np ON np.id = p.nature_parti_id
        LEFT JOIN ad ON ad.parti_id = p.id LEFT JOIN inv ON inv.parti_id = p.id LEFT JOIN lo ON lo.parti_id = p.id
        LEFT JOIN modele.nuance nu ON nu.id = p.nuance_id LEFT JOIN modele.famille f ON f.id = nu.famille_id""")


def nom(ligne):
    """« PS — Parti socialiste », ou le libellé seul s'il n'a pas de sigle."""
    s, l = ligne["sigle"], ligne["libelle"]
    return f"{s} — {l}" if isinstance(s, str) and s and s != l else str(l)


@lru_cache(maxsize=1)
def choix():
    """{« PS — Parti socialiste » : id} : les partis qu'on connaît par des gens (adhérents, candidats) ou un logo,
    les plus présents d'abord — pour la liste du réglage « Parti »."""
    t = poids()
    t = t[(t.adherents + t.candidats + t.logos) > 0].assign(rang=lambda x: x.adherents + x.candidats)
    t = t.sort_values("rang", ascending=False)
    return {nom(l): int(l["id"]) for _, l in t.iterrows()}


def logos(parti_id):
    try:
        return d.sql("""SELECT l.fichier, l.date_debut, l.date_fin, l.auteur, li.libelle licence, l.adresse
                        FROM modele.parti_logo l LEFT JOIN modele.licence li ON li.id = l.licence_id
                        WHERE l.parti_id = ? ORDER BY l.date_debut NULLS FIRST, l.id""", [parti_id])
    except Exception:                    # (une base d'avant les logos : integrer_logos.py pas encore passé)
        return pd.DataFrame(columns=["fichier", "date_debut", "date_fin", "auteur", "licence", "adresse"])


def logo(parti_id, jour=None):
    """Le fichier du logo d'un parti (le plus récent, ou celui en cours à ce jour), ou None."""
    t = logos(parti_id)
    if jour is not None and len(t):
        en_cours = t[(t.date_debut.isna() | (t.date_debut <= jour)) & (t.date_fin.isna() | (t.date_fin >= jour))]
        t = en_cours if len(en_cours) else t
    return (d.DATA / t.iloc[-1]["fichier"]) if len(t) and (d.DATA / t.iloc[-1]["fichier"]).exists() else None


def lignee(parti_id):
    """L'ascendance (ce que le parti remplace, de proche en proche) et la descendance (ce qui le remplace) :
    [(id, libellé, sigle, création, dissolution)] du plus ancien au plus récent."""
    t = d.sql("SELECT id, libelle, sigle, date_creation, date_dissolution, remplace_parti_id FROM modele.parti").set_index("id")
    avant, x, vus = [], t.loc[parti_id, "remplace_parti_id"], {parti_id}
    while pd.notna(x) and int(x) in t.index and int(x) not in vus:
        vus.add(int(x))
        avant.insert(0, int(x))
        x = t.loc[int(x), "remplace_parti_id"]
    apres, x = [], parti_id
    while True:
        suivants = t.index[t.remplace_parti_id == x].tolist()
        suivants = [s for s in suivants if s not in vus]
        if not suivants:
            break
        x = suivants[0]
        vus.add(x)
        apres.append(x)
    return [(i, t.loc[i, "libelle"], t.loc[i, "sigle"], t.loc[i, "date_creation"], t.loc[i, "date_dissolution"])
            for i in avant + [parti_id] + apres]


def fiche(parti_id):
    """Tout ce qu'on sait d'un parti."""
    p = poids().set_index("id").loc[parti_id]
    ideologies = d.sql("""SELECT i.libelle FROM modele.parti_ideologie pi JOIN modele.ideologie i ON i.id = pi.ideologie_id
                          WHERE pi.parti_id = ? ORDER BY 1""", [parti_id])["libelle"].tolist()
    positions = d.sql("""SELECT po.libelle FROM modele.parti_position pp JOIN modele.position_politique po
                         ON po.id = pp.position_politique_id WHERE pp.parti_id = ?""", [parti_id])["libelle"].tolist()
    coalitions = d.sql("""SELECT c.libelle, c.sigle FROM modele.parti_membre m JOIN modele.parti c ON c.id = m.coalition_id
                          WHERE m.parti_id = ? ORDER BY c.date_creation NULLS LAST""", [parti_id])
    membres = d.sql("""SELECT c.libelle, c.sigle FROM modele.parti_membre m JOIN modele.parti c ON c.id = m.parti_id
                       WHERE m.coalition_id = ? ORDER BY 1""", [parti_id])
    gens = d.sql("""SELECT DISTINCT p.id, p.prenoms, p.nom_usage FROM modele.adhesion a JOIN modele.personne p
                    ON p.id = a.personne_id WHERE a.parti_id = ?""", [parti_id])
    ministres = d.sql("""SELECT count(DISTINCT a.personne_id) FROM modele.adhesion a JOIN modele.nomination n
                         ON n.personne_id = a.personne_id WHERE a.parti_id = ? AND n.gouvernement_id IS NOT NULL""",
                      [parti_id]).iloc[0, 0]
    enarques = d.sql("""SELECT count(DISTINCT a.personne_id) FROM modele.adhesion a JOIN modele.formation f
                        ON f.personne_id = a.personne_id JOIN modele.ecole e ON e.id = f.ecole_id
                        WHERE a.parti_id = ? AND e.libelle = 'École nationale d''administration'""", [parti_id]).iloc[0, 0]
    candidats = d.sql("""SELECT e.code election, count(*) candidats FROM modele.investiture i
                         JOIN modele.candidature c ON c.id = i.candidature_id JOIN modele.scrutin s ON s.id = c.scrutin_id
                         JOIN modele.election e ON e.id = s.election_id WHERE i.parti_id = ? AND s.tour = 1 GROUP BY 1 ORDER BY 1""",
                      [parti_id])
    return {"id": parti_id, "nom": nom(p), "libelle": p["libelle"], "sigle": p["sigle"], "nature": p["nature"],
            "creation": p["date_creation"], "dissolution": p["date_dissolution"], "couleur": p["couleur"],
            "adherents": int(p["adherents"]), "ministres": int(ministres), "enarques": int(enarques), "gens": gens,
            "ideologies": ideologies, "positions": positions, "coalitions": coalitions, "membres": membres,
            "candidats": candidats, "logos": logos(parti_id), "lignee": lignee(parti_id)}


def anciens(n=30, encore=True):
    """Les partis les plus anciens (date de création connue). encore=True : seulement ceux qui vivent toujours — pas
    dissous ET actifs aujourd'hui (des comptes déposés à la CNCCFP, ou des candidats rattachés aux législatives
    2017-2024) : Wikidata ne donne pas toujours la date de disparition (le Club de 1789 serait sinon « encore là »)."""
    t = poids().dropna(subset=["date_creation"])
    t = t[t.nature.isin(["parti politique", "coalition politique"])]
    if encore:
        t = t[t.date_dissolution.isna() & (t.code_cnccfp.notna() | (t.candidats > 0))]
    return t.sort_values("date_creation").head(n).reset_index(drop=True)


def ecoles():
    return d.sql("SELECT libelle FROM modele.ecole ORDER BY libelle")["libelle"].tolist()


def anciens_eleves(ecole="École nationale d'administration", n=20):
    """Les partis qui comptent le plus d'adhérents passés par cette école (personnes distinctes)."""
    return d.sql("""SELECT pa.id, pa.libelle, pa.sigle, count(DISTINCT a.personne_id) n,
                           string_agg(DISTINCT p.prenoms || ' ' || p.nom_usage, ', ') qui
                    FROM modele.formation f JOIN modele.ecole e ON e.id = f.ecole_id
                    JOIN modele.adhesion a ON a.personne_id = f.personne_id JOIN modele.parti pa ON pa.id = a.parti_id
                    JOIN modele.personne p ON p.id = a.personne_id
                    WHERE e.libelle = ? GROUP BY 1, 2, 3 ORDER BY n DESC LIMIT ?""", [ecole, n])


def personnalites(n=20):
    """Les partis qui comptent le plus de personnalités : les personnes connues de Wikidata qui y ont adhéré, et parmi
    elles les ministres et les parlementaires."""
    return d.sql("""
        WITH ad AS (SELECT DISTINCT a.parti_id, a.personne_id FROM modele.adhesion a),
             mi AS (SELECT DISTINCT personne_id FROM modele.nomination WHERE gouvernement_id IS NOT NULL),
             pa_ AS (SELECT DISTINCT m.personne_id FROM modele.mandat m JOIN modele.fonction f ON f.id = m.fonction_id
                     WHERE f.libelle IN ('député', 'sénateur', 'député européen'))
        SELECT p.id, p.libelle, p.sigle, count(*) n, count(mi.personne_id) ministres, count(pa_.personne_id) parlementaires
        FROM ad JOIN modele.parti p ON p.id = ad.parti_id
        LEFT JOIN mi ON mi.personne_id = ad.personne_id LEFT JOIN pa_ ON pa_.personne_id = ad.personne_id
        GROUP BY 1, 2, 3 ORDER BY n DESC LIMIT ?""", [n])


@lru_cache(maxsize=1)
def lois():
    """Pour chaque grande loi (les grands votes de l'appli, sauf censures et interventions) : la date du vote, le
    gouvernement en place, son Premier ministre et SON parti à cette date — le parti « à l'origine » d'un projet de loi.
    (Une proposition de loi vient d'un député : son parti peut être un autre ; c'est dit dans la vue.)"""
    codes = [(lib, c) for lib, c in votes_deputes.GRANDS_VOTES if not any(m in lib for m in PAS_DES_LOIS)]
    lignes = []
    for lib, code in codes:
        v = d.sql("SELECT date, objet FROM vote WHERE code = ?", [code])
        if v.empty:
            continue
        jour = v.iloc[0]["date"]
        g = d.sql("""SELECT g.libelle gouvernement, g.premier_ministre_id pm, p.prenoms || ' ' || p.nom_usage premier_ministre
                     FROM modele.gouvernement g LEFT JOIN modele.personne p ON p.id = g.premier_ministre_id
                     WHERE g.date_debut <= ? AND coalesce(g.date_fin, DATE '9999-12-31') > ?
                     ORDER BY g.date_debut DESC LIMIT 1""", [jour, jour])
        parti = pd.DataFrame()
        if len(g) and pd.notna(g.iloc[0]["pm"]):
            parti = d.sql(f"""SELECT pa.id, pa.libelle, pa.sigle FROM modele.adhesion a JOIN modele.parti pa ON pa.id = a.parti_id
                              WHERE a.personne_id = ? AND pa.nature_parti_id = 1 AND {ADHESION_A.format(j='?')}
                              ORDER BY (a.date_debut IS NOT NULL) DESC, pa.date_creation DESC NULLS LAST LIMIT 1""",
                          [int(g.iloc[0]["pm"]), jour, jour, jour, jour])
        lignes.append({"loi": lib, "code": code, "date": jour, "objet": v.iloc[0]["objet"],
                       "proposition": "proposition de loi" in str(v.iloc[0]["objet"]).lower(),
                       "gouvernement": g.iloc[0]["gouvernement"] if len(g) else None,
                       "premier_ministre": g.iloc[0]["premier_ministre"] if len(g) else None,
                       "parti_id": int(parti.iloc[0]["id"]) if len(parti) else None,
                       "parti": nom(parti.iloc[0]) if len(parti) else "parti inconnu"})
    return pd.DataFrame(lignes)


def coalitions():
    """Les coalitions et les partis qui les composent (Wikidata : P527 « comprend »)."""
    return d.sql("""SELECT c.id, c.libelle coalition, c.sigle, c.date_creation, string_agg(p.coalesce_sigle, ', ' ORDER BY p.coalesce_sigle) membres,
                           count(*) n
                    FROM modele.parti_membre m JOIN modele.parti c ON c.id = m.coalition_id
                    JOIN (SELECT id, coalesce(sigle, libelle) coalesce_sigle FROM modele.parti) p ON p.id = m.parti_id
                    GROUP BY 1, 2, 3, 4 ORDER BY c.date_creation DESC NULLS LAST""")
