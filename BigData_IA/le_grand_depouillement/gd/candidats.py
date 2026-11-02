"""Qui sont les candidats ? Âge, profession, sexe, sortant — d'après les fichiers de candidatures du ministère (2002-2024).

Données : le modèle « personnes et mandats » — les candidatures qui ont une fiche détaillée (candidature.fiche_detaillee),
la personne (nom, sexe, naissance), l'élection ; d'après donnees_contexte/candidats_details/ (construire_modele.py).
"""
from functools import lru_cache

import duckdb
import pandas as pd

from gd import donnees as d


@lru_cache(maxsize=1)
def disponible():
    try:
        return set(d.sql("""SELECT DISTINCT e.code || '_t' || sc.tour scrutin FROM modele.candidature c
                            JOIN modele.scrutin sc ON sc.id = c.scrutin_id JOIN modele.election e ON e.id = sc.election_id WHERE c.fiche_detaillee""")["scrutin"])
    except duckdb.Error:
        return set()


def _scrutin(s):
    """« Les 2 tours » (_2t) : les candidats du 1er tour."""
    return s.replace("_2t", "_t1")


def departements(zone):
    """Les départements de la zone (None = la France entière)."""
    code = str(zone.code)
    if zone.niveau == "france":
        return None
    if zone.niveau == "departement":
        return [code]
    if zone.niveau == "region":
        return d.departements(code)["code"].tolist()
    if zone.niveau == "circo":
        return [code.split("-")[0]]
    info = d.ou_est(zone)
    return [info["dp"]] if info.get("dp") else None


@lru_cache(maxsize=16)
def _tous(scrutin):
    code, tour = d.election_tour(scrutin)
    # (l'âge le jour du vote, en années révolues)
    t = d.sql(f"""SELECT c.personne_id, e.code || '_t' || sc.tour scrutin, zd.code departement, z.libelle lieu,
                        p.nom_usage nom, p.prenoms prenom, p.sexe, p.date_naissance naissance,
                        year(j.jour) - year(p.date_naissance)
                          - CASE WHEN strftime(j.jour, '%m%d') < strftime(p.date_naissance, '%m%d') THEN 1 ELSE 0 END age,
                        c.metier profession, nc.libelle nuance, CASE WHEN c.sortant THEN 'OUI' END sortant
                 FROM modele.candidature c JOIN modele.scrutin sc ON sc.id = c.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                 JOIN modele.personne p ON p.id = c.personne_id JOIN modele.zone z ON z.id = c.zone_id
                 LEFT JOIN modele.nuance nc ON nc.id = c.nuance_id
                 LEFT JOIN (zone_dans a JOIN modele.zone zd ON zd.id = a.ancetre_id AND zd.niveau_id = {d.NIVEAU['departement']})
                   ON a.zone_id = c.zone_id,
                      LATERAL (SELECT sc.date jour) j
                 WHERE c.fiche_detaillee AND e.code = ? AND sc.tour = ?""", [code, tour])
    t["cle"] = (t["prenom"].fillna("") + " " + t["nom"].fillna("")).map(d.normaliser)
    return t


def du_scrutin(scrutin, zone):
    s = _scrutin(scrutin)
    if s not in disponible():
        return pd.DataFrame()
    t = _tous(s)
    deps = departements(zone)
    return t[t["departement"].isin(deps)] if deps else t


def de(qui, scrutin, zone=None):
    """La fiche d'un candidat (« Michel VOISIN », « Marine LE PEN ») à ce scrutin, ou None."""
    s = _scrutin(scrutin)
    if s not in disponible():
        return None
    t = du_scrutin(s, zone) if zone is not None else _tous(s)
    cle = d.normaliser(qui)
    x = t[t["cle"] == cle]
    if x.empty:         # « NOM Prénom » ou des mots dans un autre ordre
        mots = set(cle.split())
        x = t[t["cle"].map(lambda c: set(c.split()) == mots)]
    return x.iloc[0] if len(x) else None
