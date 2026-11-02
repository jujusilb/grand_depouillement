"""
figer_sieges.py — Calcule UNE fois les sièges de toutes les assemblées, et les fige dans la base (table sieges_figes).

    py figer_sieges.py              (appelé aussi à la fin de preparer_donnees.py ; l'appli doit être fermée)

Pour chaque scrutin de la base :
    Législatives       l'Assemblée nationale (une circonscription = un élu)
    Départementales    les conseils départementaux (binômes) ; Cantonales : les conseillers généraux élus
    Régionales         chaque conseil régional (2015 et 2021, régions actuelles)
    Municipales        chaque conseil municipal (2008 → 2026), avec les élus quand les listes déposées sont connues (2020, 2026)
    Européennes        la délégation française (2019 et 2024)
Le résultat de chaque calcul est rangé en JSON, une ligne par (calcul, scrutin, zone) : l'appli relit seulement la ligne
qu'on lui demande. Les calculs sont ceux de gd/sieges.py — les conseils municipaux sont faits en lot (toutes les communes
d'un scrutin en quelques requêtes) avec le même calcul que dans l'appli.
"""
import time

import duckdb
import pandas as pd

from gd import donnees as d
from gd import sieges

sieges.CALCULER = True          # on calcule (on ne relit pas d'anciens sièges figés)
lignes = []                     # (calcul, scrutin, zone, valeur JSON)
debut = time.time()


def garder(calcul, scrutin, zone, valeur):
    # (les vieilles législatives, par commune, ne permettent pas de reconstituer les circonscriptions : on ne fige pas un faux résultat)
    if calcul == "assemblee_nationale" and len(valeur) < 300 or isinstance(valeur, pd.DataFrame) and valeur.empty:
        return
    if valeur is not None:
        lignes.append((calcul, scrutin, str(zone), sieges.en_json(valeur)))


s = d.scrutins()
premiers = s[s["tour"] == 1]
ids = set(s["scrutin"])

# 1. Assemblée, conseils départementaux, conseils régionaux, délégation européenne
for sid, type_ in zip(premiers["scrutin"], premiers["type"]):
    t0 = time.time()
    try:
        if type_ == "Législatives":
            garder("assemblee_nationale", sid, "", sieges.assemblee_nationale.calculer(sid))
        elif type_ in ("Départementales", "Cantonales"):
            garder("conseils_departementaux", sid, "", sieges.conseils_departementaux.calculer(sid))
        elif type_ == "Régionales":
            for reg in sieges.CONSEILS_REGIONAUX:
                garder("conseil_regional", sid, reg, sieges.conseil_regional.calculer(sid, reg))
        elif type_ == "Européennes":
            garder("delegation_europeenne", sid, "", sieges.delegation_europeenne.calculer(sid))
        else:
            continue
        print(f"   {sid:18s} {time.time() - t0:6.1f} s")
    except Exception as e:          # (un vieux scrutin dont les bureaux ne permettent pas le calcul : on passe)
        print(f"   {sid:18s} pas calculable : {e}")

# 2. Les conseils municipaux, en lot (2008 → 2026 ; la taille du conseil : la plus petite liste déposée, sinon la taille
#    légale selon la population Insee (2026 : celle publiée par le ministère) ; communes à candidats un par un : celles sans numéro de liste, sinon par la population)
for t1 in premiers[premiers["type"] == "Municipales"]["scrutin"]:
    t0 = time.time()
    base = t1.rsplit("_", 1)[0]
    t2 = base + "_t2"
    an = int(t1[:4])
    # (les candidatures du modèle : une commune « à candidats un par un » n'a, au 1er tour, aucune candidature sur une liste)
    deposees = set(d.sql("""SELECT DISTINCT z.code FROM modele.candidature c JOIN modele.scrutin sc ON sc.id = c.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                            JOIN modele.zone z ON z.id = c.zone_id WHERE e.code = ? AND c.conseil = 'municipal'""", [base])["code"])
    seuls = set(d.sql("""SELECT z.code FROM modele.candidature c JOIN modele.scrutin sc ON sc.id = c.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                         JOIN modele.zone z ON z.id = c.zone_id WHERE e.code = ? AND sc.tour = 1 AND c.conseil = 'municipal'
                         GROUP BY 1 HAVING count(c.liste_id) = 0""", [base])["code"])
    officiels, pops = sieges.sieges_officiels(an), sieges.populations(an)
    petites = d.sql("""SELECT zone_code code_zone, min(n) n FROM (SELECT l.id, z.code zone_code, count(*) n FROM modele.liste l
                       JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id JOIN modele.candidature c ON c.liste_id = l.id
                       JOIN modele.zone z ON z.id = l.zone_id
                       WHERE e.code = ? AND l.conseil = 'municipal' GROUP BY 1, 2) GROUP BY 1""", [base]).set_index("code_zone")["n"]

    def taille(com, ins):          # (même ordre que sieges.sieges_municipaux : ministère, loi, plus petite liste, inscrits)
        if com in officiels:
            return int(officiels[com])
        if com in pops:
            return sieges.taille_legale(int(pops[com]), an)
        if com in petites.index:
            return int(petites[com])
        return sieges.taille_legale(ins / 0.75, an)

    def voix(sid):
        r = d.sql(f"""SELECT p.code_commune, r.qui, any_value(r.nuance) nuance, sum(r.voix) voix FROM {d.R(sid)} r
                     JOIN {d.P(sid)} p USING (bureau_id) GROUP BY 1, 2""")
        p = d.sql(f"SELECT code_commune, sum(exprimes) e, sum(inscrits) i FROM {d.P(sid)} GROUP BY 1")
        p = p.set_index("code_commune")
        return {k: g.drop(columns="code_commune").sort_values("voix", ascending=False).reset_index(drop=True)
                for k, g in r.groupby("code_commune")}, p["e"], p["i"]
    v1, e1, i1 = voix(t1)
    v2, e2, _ = voix(t2) if t2 in ids else ({}, pd.Series(dtype=float), None)
    # (les candidats des listes, des deux tours, avec la personne du modèle)
    c = d.sql("""SELECT e.code || '_t' || sc.tour election, z.code code_zone, l.numero_panneau, c.rang ordre,
                        p.prenoms || ' ' || p.nom_usage AS elu, p.nom_usage nom, p.sexe, l.libelle libelle_liste,
                        l.libelle_abrege libelle_abrege, c.tete_de_liste
                 FROM modele.candidature c JOIN modele.liste l ON l.id = c.liste_id
                 JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id JOIN modele.personne p ON p.id = c.personne_id
                 JOIN modele.zone z ON z.id = l.zone_id
                 WHERE e.code = ? AND l.conseil = 'municipal'
                 ORDER BY l.numero_panneau, c.rang""", [base])
    cands = {k: g for k, g in c.groupby(["election", "code_zone"])}
    vide = c.iloc[0:0]
    n = {"listes": 0, "un par un": 0}
    for com, r in v1.items():
        if com in d.VILLES_PLM or not len(r):
            continue
        e, ins = float(e1.get(com, 0) or 0), float(i1.get(com, 0) or 0)
        pop = sieges.population(t1, com, ins)
        if com in seuls or (com not in deposees and pop < sieges.seuil_listes(an)):
            garder("conseil_municipal", t1, com, sieges.repartir_plurinominal(t1, r, e, ins, t2, v2.get(com), taille(com, ins)))
            n["un par un"] += 1
            continue
        n_sieges = taille(com, ins)
        tour = t1
        if not (r["voix"].iloc[0] > e / 2) and com in v2:          # (même règle que sieges.tour_decisif)
            tour, r, e = t2, v2[com], float(e2.get(com, 0) or 0)
        garder("conseil_municipal", t1, com, sieges.repartir_municipal(tour, r, e, n_sieges,
                                                                          cands.get((tour, com), cands.get((t1, com), vide))))
        n["listes"] += 1
    print(f"   {t1:18s} {n['listes']} conseils à listes, {n['un par un']} à candidats un par un, {time.time() - t0:6.1f} s")

# 3. Dans la base (la connexion de lecture de l'appli d'abord fermée)
t = pd.DataFrame(lignes, columns=["calcul", "scrutin", "zone", "valeur"])
d.con().close()
d._con = None
con = duckdb.connect(str(d.BASE))
con.execute("CREATE OR REPLACE TABLE sieges_figes AS SELECT * FROM t")
con.execute("CHECKPOINT")
con.close()
print(f"sieges_figes : {len(t)} résultats ({t['valeur'].str.len().sum() / 1e6:.0f} Mo de JSON), en {time.time() - debut:.0f} s")
print(t.groupby("calcul").size().to_string())
