"""Les 17 législatures de la Ve République : la composition de l'Assemblée siège par siège, et qui siégeait un jour donné.

Tables legislature et sieges_legislature (base_appli.py ← donnees/legislatures/fabriquer_legislatures.py ;
chaque siège relié à sa personne par brancher_modele.py) ; qui siégeait un jour donné : les mandats de député du modèle
« personnes et mandats » (2002 → aujourd'hui) et leurs groupes datés (mandat_groupe).
"""
from functools import lru_cache

import duckdb
import pandas as pd

from lecture import donnees as d
from interface import theme
from politique import votes as votes_deputes


def romain(n):
    """17 → « XVII »."""
    chiffres = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    r = ""
    for v, c in chiffres:
        while n >= v:
            r, n = r + c, n - v
    return r


@lru_cache(maxsize=1)
def liste():
    try:
        # (le nombre de sièges lus et de députés connus : compté dans sieges_legislature)
        t = d.sql("""SELECT l.id legislature, l.date_debut debut, l.date_fin fin, l.sieges, s.libelle source,
                            count(x.legislature) sieges_lus, count(x.legislature) FILTER (WHERE x.connu) deputes_connus
                     FROM legislature l LEFT JOIN modele.source s ON s.id = l.source_id
                     LEFT JOIN sieges_legislature x ON x.legislature = l.id
                     GROUP BY ALL ORDER BY l.id DESC""")
        t["debut"], t["fin"] = pd.to_datetime(t["debut"]), pd.to_datetime(t["fin"])
        t["romain"] = t["legislature"].map(romain)
    except duckdb.Error:
        return pd.DataFrame()
    # « Législature XI · 1997–2002 : 577/577 connus » (députés dont on connaît le nom / sièges)
    t["libelle"] = [f"Législature {r} · {deb:%Y}–{'' if f != f or f is None else f'{f:%Y}'} : {k}/{n} connus"
                    for r, deb, f, k, n in zip(t["romain"], t["debut"], t["fin"], t["deputes_connus"], t["sieges"])]
    return t


def disponible():
    return not liste().empty


def libelles():
    return list(liste()["libelle"])


def numero(libelle):
    t = liste()
    x = t[t["libelle"] == libelle]
    return int(x["legislature"].iloc[0]) if len(x) else int(t["legislature"].max())


def _rang(groupe):
    """La place d'un groupe de gauche à droite : les sigles connus de l'Assemblée, sinon la famille de son code officiel."""
    if groupe in votes_deputes.ORDRE_SIGLES:
        return votes_deputes.ORDRE_SIGLES.index(groupe)
    if groupe in votes_deputes.FAMILLE_SIGLE:
        return theme.ORDRE_FAMILLES.index(votes_deputes.FAMILLE_SIGLE[groupe]) * 1.8
    if groupe == "?":
        return 99
    return theme.rang_politique(groupe, mots=False) * 1.8


def couleur(groupe, officielle=None):
    if isinstance(officielle, str) and officielle:
        return officielle
    if groupe == "?":
        return "#B8BEC6"
    return theme.couleur_politique(groupe, mots=False) or (theme.FAMILLES[votes_deputes.FAMILLE_SIGLE[groupe]]
                                                          if groupe in votes_deputes.FAMILLE_SIGLE else theme.FAMILLES["divers"])


@lru_cache(maxsize=20)
def sieges(num):
    """Les sièges d'une législature, rangés de gauche à droite (les députés connus d'abord dans chaque groupe)."""
    t = d.sql("""SELECT s.legislature, s.personne_id, coalesce(p.prenoms || ' ' || p.nom_usage, s.nom_non_identifie) depute,
                        gr.code groupe, gr.couleur, s.lieu, s.connu
                 FROM sieges_legislature s LEFT JOIN modele.personne p ON p.id = s.personne_id
                 LEFT JOIN modele.groupe gr ON gr.id = s.groupe_id WHERE s.legislature = ?""", [num])
    t["rang"] = t["groupe"].map(_rang)
    t["couleur"] = [couleur(g, c) for g, c in zip(t["groupe"], t["couleur"])]
    return t.sort_values(["rang", "groupe", "connu", "depute"], ascending=[True, True, False, True]).reset_index(drop=True)


def legislature_du(jour):
    t = liste()
    jour = pd.Timestamp(jour)
    x = t[(t["debut"] <= jour) & (t["fin"].isna() | (t["fin"] >= jour))]
    return x.iloc[0] if len(x) else None


def en_fonction(jour):
    """Les députés qui siégeaient ce jour-là (2002 → aujourd'hui) : nom, groupe à cette date, couleur, circonscription."""
    jour = pd.Timestamp(jour).date()
    try:
        # (un mandat sans date de début connue — député en exercice — compte depuis l'ouverture de la XVIIe législature)
        m = d.sql("""SELECT m.personne_id, p.prenoms || ' ' || p.nom_usage depute, coalesce(m.date_debut, DATE '2024-07-07') debut,
                            zd.code departement, z.code circo,
                            n.n || CASE n.n WHEN 1 THEN 're' ELSE 'e' END || ' circonscription · ' || zd.libelle lieu,
                            g.groupe, g.couleur
                     FROM modele.mandat m JOIN modele.fonction f ON f.id = m.fonction_id AND f.libelle = 'député'
                     JOIN modele.personne p ON p.id = m.personne_id
                     JOIN modele.zone z ON z.id = m.zone_id JOIN modele.zone zd ON zd.id = z.parent_id,
                     LATERAL (SELECT CAST(split_part(z.code, '-', 2) AS INTEGER) n) n
                     LEFT JOIN (SELECT DISTINCT ON (a.mandat_id) a.mandat_id, gr.code groupe, gr.couleur
                                FROM modele.mandat_groupe a JOIN modele.groupe gr ON gr.id = a.groupe_id
                                WHERE a.date_debut <= ? AND (a.date_fin IS NULL OR a.date_fin >= ?)
                                ORDER BY a.mandat_id, a.date_debut DESC) g ON g.mandat_id = m.id
                     WHERE coalesce(m.date_debut, DATE '2024-07-07') <= ? AND (m.date_fin IS NULL OR m.date_fin >= ?)
                       AND coalesce(m.date_debut, DATE '2024-07-07') >= DATE '2002-06-19'""", [jour, jour, jour, jour])
    except duckdb.Error:
        return pd.DataFrame()
    # (deux mandats de la même personne peuvent se chevaucher : on n'en garde qu'un)
    m = m.sort_values("debut").drop_duplicates("personne_id", keep="last")
    m["groupe"] = m["groupe"].fillna("?")
    return m


@lru_cache(maxsize=8)
def votes_complets(sid):
    """Les votes d'un scrutin + les députés ABSENTS (en fonction ce jour-là, mais sans vote enregistré).
    2002 → aujourd'hui : les absents sont nommés (mandats datés) ; avant : des absents anonymes jusqu'au nombre de sièges.
    Motion de censure : seuls les « pour » sont publiés — les autres ne sont pas « absents », ils n'ont pas voté la censure."""
    t = votes_deputes.votes(sid)
    s = votes_deputes.scrutin(sid)
    if t.empty or s is None:
        return t
    censure = "censure" in str(s["objet"]) and int(s["contre"]) == 0
    manquant = "sans vote publié" if censure else "absent"
    presents = set(t["personne_id"].dropna().astype(int))
    ros = en_fonction(s["date"]) if pd.Timestamp(s["date"]) >= pd.Timestamp("2002-06-19") and "CONGRES" not in str(sid) else pd.DataFrame()
    leg = legislature_du(s["date"])
    places = int(leg["sieges"]) if leg is not None and "CONGRES" not in str(sid) else len(t)
    absents = pd.DataFrame(columns=["depute", "groupe", "couleur", "position", "lieu"])
    if len(ros):
        # absent = en fonction ce jour-là, sans vote, et personne de sa circonscription n'a voté (l'open data garde parfois
        # deux mandats qui se chevauchent : le ministre et son suppléant)
        lieux = set(t["lieu"].dropna())
        a = ros[~ros["personne_id"].isin(presents) & ~ros["lieu"].isin(lieux)]
        a = a.sort_values("debut").drop_duplicates(["departement", "circo"], keep="last").head(max(0, places - len(t)))
        absents = pd.DataFrame({"personne_id": a["personne_id"], "depute": a["depute"], "groupe": a["groupe"], "couleur": [couleur(g, c) for g, c in zip(a["groupe"], a["couleur"])],
                                "position": manquant, "lieu": a["lieu"]})
    # les sièges qui restent (députés que nos listes n'ont pas, ou avant 2002) : des absents anonymes
    n = places - len(t) - len(absents)
    if n > 0:
        absents = pd.concat([absents, pd.DataFrame({"depute": [None] * n, "groupe": "?", "couleur": "#B8BEC6", "position": manquant, "lieu": ""})],
                            ignore_index=True)
    if absents.empty:
        return t
    absents["rang"] = absents["groupe"].map(_rang)
    absents["ordre_pos"] = 9
    tout = pd.concat([t, absents], ignore_index=True)
    return tout.sort_values(["rang", "groupe", "ordre_pos", "depute"], na_position="last").reset_index(drop=True)
