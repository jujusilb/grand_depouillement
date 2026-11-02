"""Les personnes et leurs carrières, lues dans le modèle (modele.*) : la fiche d'une personne, les gouvernements, les
présidents, les préfets, les écoles, les cumuls, les maires ; et deux lectures du temps long (le premier à chaque
élection dans une zone, les bascules des conseils départementaux).

Toutes les fonctions rendent des tableaux pandas ; les vues qui les dessinent sont dans graphiques_personnes.py.
"""
from functools import lru_cache

import duckdb
import pandas as pd

from gd import donnees as d
from gd import rne, sieges, theme


@lru_cache(maxsize=1)
def disponible():
    try:
        return d.sql("SELECT count(*) FROM modele.nomination").iloc[0, 0] > 0
    except duckdb.Error:
        return False


def nom_affiche(prenoms, nom):
    return f"{prenoms or ''} {str(nom or '').upper()}".strip()


# ------------------------------------------------------------------------------------------------------------------
# Une personne : la retrouver par son nom, puis tout son parcours
# ------------------------------------------------------------------------------------------------------------------
def chercher(texte, n=40):
    """Les personnes dont le nom (et le prénom, s'il est tapé) ressemble au texte : celles qui ont le plus de traces
    (mandats, nominations, écoles, candidatures) d'abord. « hollande », « Ségolène Royal », « silberstein »…"""
    mots = [m for m in d.normaliser(texte).split() if m]
    if not mots:
        return pd.DataFrame(columns=["id", "nom", "naissance", "traces"])
    # (chaque mot doit se trouver dans le nom ou le prénom, sans accents ni majuscules)
    conditions = " AND ".join(["(strip_accents(lower(p.nom_usage)) LIKE ? OR strip_accents(lower(p.prenoms)) LIKE ?)"] * len(mots))
    params = [x for m in mots for x in (f"%{m}%", f"%{m}%")]
    t = d.sql(f"""
        SELECT p.id, p.prenoms, p.nom_usage, p.date_naissance naissance,
               (SELECT count(*) FROM modele.mandat m WHERE m.personne_id = p.id)
             + (SELECT count(*) FROM modele.nomination n WHERE n.personne_id = p.id)
             + (SELECT count(*) FROM modele.formation f WHERE f.personne_id = p.id)
             + (SELECT count(*) FROM modele.candidature c WHERE c.personne_id = p.id) traces
        FROM modele.personne p WHERE {conditions}
        ORDER BY traces DESC, p.nom_usage LIMIT {n}""", params)
    t["nom"] = [nom_affiche(p, x) for p, x in zip(t["prenoms"], t["nom_usage"])]
    return t[["id", "nom", "naissance", "traces"]]


def etiquette(ligne):
    """« Ségolène ROYAL (née en 1953) — 42 traces » : pour la liste de choix."""
    an = f" ({pd.Timestamp(ligne['naissance']).year})" if pd.notna(ligne["naissance"]) else ""
    return f"{ligne['nom']}{an} — {int(ligne['traces'])} traces · n° {int(ligne['id'])}"


def _lieu(x):
    """Le lieu lisible d'une ligne dont la zone est x.zone_id : « France », « Haute-Loire, 1ère circonscription »,
    « Le Puy-en-Velay »… (jointures à ajouter : _ZONE.format(x=…))."""
    return (f"""CASE WHEN z.niveau_id = {d.NIVEAU['pays']} THEN z.libelle
                 WHEN z.niveau_id IN ({d.NIVEAU['circo']}, {d.NIVEAU['canton']}) THEN zp.libelle || ', ' || z.libelle
                 ELSE z.libelle END lieu""",
            f"LEFT JOIN modele.zone z ON z.id = {x}.zone_id LEFT JOIN modele.zone zp ON zp.id = z.parent_id")


def fiche(pid):
    """dict : identité, et le parcours (une ligne par mandat, nomination, école ; les candidatures comptées à part)."""
    p = d.sql("SELECT * FROM modele.personne WHERE id = ?", [pid])
    if p.empty:
        return None
    p = p.iloc[0]
    ids = d.sql("""SELECT r.libelle, r.url_modele, i.valeur FROM modele.identifiant i JOIN modele.referentiel r
                   ON r.id = i.referentiel_id WHERE i.personne_id = ?""", [pid])
    mandats = d.sql(f"""SELECT 'Mandat' sorte, f.libelle quoi, {_lieu('m')[0]}, m.date_debut debut, m.date_fin fin,
                              e.code election
                       FROM modele.mandat m JOIN modele.fonction f ON f.id = m.fonction_id {_lieu('m')[1]}
                       LEFT JOIN modele.scrutin sc ON sc.id = m.scrutin_id LEFT JOIN modele.election e ON e.id = sc.election_id
                       WHERE m.personne_id = ?""", [pid])
    nominations = d.sql(f"""SELECT CASE WHEN f.id = 29 THEN 'Préfet' WHEN f.id >= 32 THEN 'Grand corps' ELSE 'Gouvernement' END sorte,
                                  po.libelle quoi, {_lieu('n')[0]}, n.date_debut debut, n.date_fin fin,
                                  g.libelle election
                           FROM modele.nomination n JOIN modele.poste po ON po.id = n.poste_id
                           JOIN modele.fonction f ON f.id = po.fonction_id {_lieu('n')[1]}
                           LEFT JOIN modele.gouvernement g ON g.id = n.gouvernement_id WHERE n.personne_id = ?""", [pid])
    ecoles = d.sql("""SELECT 'École' sorte, e.libelle || coalesce(' — ' || pr.libelle, '') quoi, NULL lieu,
                             make_date(coalesce(f.annee_entree, f.annee_sortie), 1, 1) debut,
                             make_date(f.annee_sortie, 1, 1) fin, NULL election
                      FROM modele.formation f JOIN modele.ecole e ON e.id = f.ecole_id
                      LEFT JOIN modele.promotion pr ON pr.id = f.promotion_id WHERE f.personne_id = ?""", [pid])
    t = pd.concat([x for x in (mandats, nominations, ecoles) if len(x)], ignore_index=True) if len(mandats) + len(nominations) + len(ecoles) else mandats
    if len(t):
        t["lieu"] = t["lieu"].fillna("")
        t["debut"] = pd.to_datetime(t["debut"])
        t["fin"] = pd.to_datetime(t["fin"])
        t = t.sort_values(["debut", "sorte"]).reset_index(drop=True)
    candidatures = d.sql("""SELECT e.code election, sc.tour, z.libelle lieu, nc.libelle nuance,
                                   (SELECT string_agg(pa.libelle, ', ') FROM modele.investiture i JOIN modele.parti pa ON pa.id = i.parti_id
                                    WHERE i.candidature_id = c.id) parti, c.elu
                            FROM modele.candidature c JOIN modele.scrutin sc ON sc.id = c.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                            LEFT JOIN modele.zone z ON z.id = c.zone_id LEFT JOIN modele.nuance nc ON nc.id = c.nuance_id
                            WHERE c.personne_id = ? ORDER BY e.code, sc.tour""", [pid])
    # ses partis : adhésions (Wikidata), et partis de rattachement de ses candidatures (ministère)
    partis = d.sql("""SELECT pa.libelle parti, pa.sigle, a.date_debut debut, a.date_fin fin, 'adhésion (Wikidata)' source
                       FROM modele.adhesion a JOIN modele.parti pa ON pa.id = a.parti_id WHERE a.personne_id = ?
                       UNION
                       SELECT pa.libelle, pa.sigle, min(sc.date), max(sc.date), 'candidat rattaché (ministère)'
                       FROM modele.candidature c JOIN modele.investiture i ON i.candidature_id = c.id
                       JOIN modele.parti pa ON pa.id = i.parti_id JOIN modele.scrutin sc ON sc.id = c.scrutin_id
                       WHERE c.personne_id = ? GROUP BY 1, 2
                       ORDER BY debut NULLS FIRST""", [pid, pid])
    return {"nom": nom_affiche(p["prenoms"], p["nom_usage"]), "sexe": p["sexe"], "naissance": p["date_naissance"],
            "deces": p["date_deces"], "lieu_naissance": p["lieu_naissance"], "identifiants": ids, "parcours": t,
            "candidatures": candidatures, "partis": partis, "photo": photo(pid), "liens": liens(pid, p["sexe"])}


def photo(pid):
    """La photo d'une personne (officielle d'abord, Wikimedia Commons sinon) : dict (chemin, auteur, licence, source,
    adresse), ou None. Une photo libre se montre toujours avec son auteur et sa licence."""
    try:
        t = d.sql("""SELECT ph.fichier, ph.adresse, ph.auteur, l.libelle licence, s.producteur source
                     FROM modele.photo_personne pp JOIN modele.photo ph ON ph.id = pp.photo_id
                     JOIN modele.source s ON s.id = ph.source_id LEFT JOIN modele.licence l ON l.id = ph.licence_id
                     WHERE pp.personne_id = ? ORDER BY s.cle = 'photos Wikimedia Commons', ph.id""", [pid])
    except duckdb.Error:                     # (modèle d'avant photo.licence_id)
        return None
    for r in t.itertuples(index=False):
        chemin = d.DOSSIER / "data" / "photos" / r.fichier
        if chemin.exists():
            return {"chemin": chemin, "auteur": r.auteur, "licence": r.licence, "source": r.source, "adresse": r.adresse}
    return None


# « parent de » vu du côté de la personne, selon son sexe : mère de, père de ; et de l'autre côté : fille de, fils de…
_GENRE = {"parent de": ("mère de", "père de"), "enfant de": ("fille de", "fils de"),
          "frère ou sœur": ("sœur de", "frère de"), "conjoint": ("épouse de", "époux de"),
          "compagnon ou compagne": ("compagne de", "compagnon de")}


def liens(pid, sexe=None):
    """Les liens familiaux d'une personne : tableau (relation, id, nom, source, debut, fin, note), la relation dite
    depuis cette personne (« mère de », « fils de »…)."""
    try:
        t = d.sql("""SELECT CASE WHEN l.personne_id = ? THEN t.libelle ELSE t.libelle_inverse END relation,
                            o.id, o.prenoms, o.nom_usage, s.producteur source, l.date_debut debut, l.date_fin fin, l.note
                     FROM modele.lien l JOIN modele.type_lien t ON t.id = l.type_lien_id
                     JOIN modele.personne o ON o.id = CASE WHEN l.personne_id = ? THEN l.autre_id ELSE l.personne_id END
                     JOIN modele.source s ON s.id = l.source_id
                     WHERE l.personne_id = ? OR l.autre_id = ? ORDER BY 1, o.nom_usage""", [pid] * 4)
    except duckdb.Error:                     # (modèle d'avant les liens)
        return pd.DataFrame(columns=["relation", "id", "nom", "source", "debut", "fin", "note"])
    t["relation"] = [_GENRE.get(r, (r, r))[0 if sexe == "F" else 1] if sexe in ("F", "M") else r for r in t["relation"]]
    t["nom"] = [nom_affiche(p, n) for p, n in zip(t["prenoms"], t["nom_usage"])]
    return t[["relation", "id", "nom", "source", "debut", "fin", "note"]]


# ------------------------------------------------------------------------------------------------------------------
# Le pouvoir nommé : gouvernements, présidents, préfets, écoles
# ------------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def gouvernements():
    """Tous les gouvernements, du plus récent au plus ancien : (id, libellé affiché, début, fin)."""
    t = d.sql("""SELECT g.id, g.libelle, g.date_debut debut, g.date_fin fin, r.libelle regime
                 FROM modele.gouvernement g JOIN modele.regime r ON r.id = g.regime_id ORDER BY g.date_debut DESC""")
    t["choix"] = [f"{l} ({pd.Timestamp(a).year}" + (f"-{pd.Timestamp(b).year})" if pd.notna(b) else "-)")
                  for l, a, b in zip(t["libelle"], t["debut"], t["fin"])]
    return t


def membres(gid):
    """Les membres d'un gouvernement : poste, fonction, personne, dates."""
    t = d.sql("""SELECT f.libelle fonction, f.id fonction_id, po.libelle poste, p.id personne_id, p.prenoms, p.nom_usage,
                        n.date_debut debut, n.date_fin fin
                 FROM modele.nomination n JOIN modele.poste po ON po.id = n.poste_id JOIN modele.fonction f ON f.id = po.fonction_id
                 JOIN modele.personne p ON p.id = n.personne_id WHERE n.gouvernement_id = ?""", [gid])
    ordre = {24: 0, 30: 0, 31: 1, 25: 2, 18: 3, 26: 4, 27: 5, 28: 6}
    t["rang"] = t["fonction_id"].map(ordre).fillna(9)
    t["qui"] = [nom_affiche(p, x) for p, x in zip(t["prenoms"], t["nom_usage"])]
    return t.sort_values(["rang", "debut", "qui"]).reset_index(drop=True)


def presidents():
    t = d.sql("""SELECT p.id personne_id, p.prenoms, p.nom_usage, m.date_debut debut, m.date_fin fin, e.code election,
                        md.libelle motif_debut, mf.libelle motif_fin
                 FROM modele.mandat m JOIN modele.personne p ON p.id = m.personne_id
                 LEFT JOIN modele.scrutin sc ON sc.id = m.scrutin_id LEFT JOIN modele.election e ON e.id = sc.election_id
                 LEFT JOIN modele.motif_debut md ON md.id = m.motif_debut_id LEFT JOIN modele.motif_fin mf ON mf.id = m.motif_fin_id
                 WHERE m.fonction_id = 17 ORDER BY m.date_debut""")
    t["qui"] = [nom_affiche(p, x) for p, x in zip(t["prenoms"], t["nom_usage"])]
    return t


def prefets(code_departement):
    """Les préfets d'un département, du plus ancien au plus récent (années seules avant 1990 : Archives nationales)."""
    t = d.sql("""SELECT p.id personne_id, p.prenoms, p.nom_usage, n.date_debut debut, n.date_fin fin, pr.libelle precis,
                        s.cle source
                 FROM modele.nomination n JOIN modele.poste po ON po.id = n.poste_id
                 JOIN modele.personne p ON p.id = n.personne_id JOIN modele.precision_date pr ON pr.id = n.precision_id
                 JOIN modele.source s ON s.id = n.source_id JOIN modele.zone z ON z.id = n.zone_id
                 WHERE po.fonction_id = 29 AND z.niveau_id = ? AND z.code = ? ORDER BY n.date_debut""",
              [d.NIVEAU["departement"], code_departement])
    t["qui"] = [nom_affiche(p, x) for p, x in zip(t["prenoms"], t["nom_usage"])]
    return t


@lru_cache(maxsize=1)
def ecoles_et_pouvoir():
    """Pour chaque école : combien de diplômés connus, et combien sont devenus élus, membres d'un gouvernement, préfets,
    membres d'un grand corps."""
    return d.sql("""
        WITH f AS (SELECT DISTINCT ecole_id, personne_id FROM modele.formation),
        elus AS (SELECT DISTINCT personne_id FROM modele.mandat),
        nat AS (SELECT DISTINCT personne_id FROM modele.mandat WHERE fonction_id IN (14, 15, 16, 17)),
        gouv AS (SELECT DISTINCT n.personne_id FROM modele.nomination n WHERE n.gouvernement_id IS NOT NULL),
        pref AS (SELECT DISTINCT n.personne_id FROM modele.nomination n JOIN modele.poste po ON po.id = n.poste_id
                 WHERE po.fonction_id = 29),
        corps AS (SELECT DISTINCT n.personne_id FROM modele.nomination n JOIN modele.poste po ON po.id = n.poste_id
                  WHERE po.fonction_id BETWEEN 32 AND 35)
        SELECT e.libelle ecole, count(*) diplomes,
               count(elus.personne_id) elus, count(nat.personne_id) parlementaires_ou_president,
               count(gouv.personne_id) gouvernement, count(pref.personne_id) prefets, count(corps.personne_id) grands_corps
        FROM f JOIN modele.ecole e ON e.id = f.ecole_id
        LEFT JOIN elus USING (personne_id) LEFT JOIN nat USING (personne_id) LEFT JOIN gouv USING (personne_id)
        LEFT JOIN pref USING (personne_id) LEFT JOIN corps USING (personne_id)
        GROUP BY 1 ORDER BY diplomes DESC""")


def ministres_d_une_ecole(ecole):
    """Les membres d'un gouvernement passés par cette école, avec leur promotion et leur premier poste."""
    t = d.sql("""SELECT DISTINCT p.id personne_id, p.prenoms, p.nom_usage, fo.annee_sortie, pr.libelle promotion,
                        min(n.date_debut) OVER (PARTITION BY p.id) premier
                 FROM modele.formation fo JOIN modele.ecole e ON e.id = fo.ecole_id
                 JOIN modele.nomination n ON n.personne_id = fo.personne_id AND n.gouvernement_id IS NOT NULL
                 JOIN modele.personne p ON p.id = fo.personne_id LEFT JOIN modele.promotion pr ON pr.id = fo.promotion_id
                 WHERE e.libelle = ? ORDER BY premier""", [ecole])
    t["qui"] = [nom_affiche(p, x) for p, x in zip(t["prenoms"], t["nom_usage"])]
    return t.drop_duplicates("personne_id")


def ecoles():
    return d.sql("SELECT libelle FROM modele.ecole ORDER BY id")["libelle"].tolist()


# ------------------------------------------------------------------------------------------------------------------
# Les élus d'aujourd'hui : cumuls, portrait des maires
# ------------------------------------------------------------------------------------------------------------------
def cumuls():
    """Les personnes qui ont aujourd'hui (mandats en cours) au moins deux mandats de nature différente."""
    t = d.sql("""
        WITH en_cours AS (SELECT m.personne_id, f.libelle FROM modele.mandat m JOIN modele.fonction f ON f.id = m.fonction_id
                          WHERE m.date_fin IS NULL AND m.motif_fin_id IS NULL
                            AND f.libelle IN ('député', 'sénateur', 'député européen', 'maire', 'président du conseil départemental',
                                            'président du conseil régional', 'président d''intercommunalité'))
        SELECT personne_id, string_agg(DISTINCT libelle, ' + ' ORDER BY libelle) mandats, count(DISTINCT libelle) n
        FROM en_cours GROUP BY 1 HAVING count(DISTINCT libelle) >= 2""")
    if t.empty:
        return t
    noms = d.sql(f"SELECT id personne_id, prenoms, nom_usage FROM modele.personne WHERE id IN ({','.join(map(str, t['personne_id']))})")
    t = t.merge(noms, on="personne_id")
    t["qui"] = [nom_affiche(p, x) for p, x in zip(t["prenoms"], t["nom_usage"])]
    return t.sort_values(["mandats", "qui"])


def portrait_maires():
    """Pour chaque version du RNE (2020-01 : élus 2014 ; 2020-12 : élus 2020 ; 2026-08 : élus 2026) : le nombre de maires,
    la part de femmes, l'âge médian, et la part de maires qui l'étaient déjà dans la même commune à la version précédente."""
    lignes, avant = [], None
    for v, jour in rne.JOURS.items():
        t = d.sql("""SELECT m.personne_id, m.zone_id, p.sexe, p.date_naissance FROM modele.mandat m
                     JOIN modele.fonction f ON f.id = m.fonction_id JOIN modele.personne p ON p.id = m.personne_id
                     WHERE f.libelle = 'maire' AND m.date_debut <= ? AND (m.date_fin IS NULL OR m.date_fin >= ?)""", [jour, jour])
        age = (pd.Timestamp(jour) - pd.to_datetime(t["date_naissance"])).dt.days / 365.25
        reelus = None if avant is None else 100 * t.set_index(["personne_id", "zone_id"]).index.isin(avant).mean()
        lignes.append({"version": rne.LIBELLES[v], "maires": len(t), "femmes": 100 * (t["sexe"] == "F").mean(),
                       "age_median": age.median(), "deja_maires": reelus})
        avant = t.set_index(["personne_id", "zone_id"]).index
    return pd.DataFrame(lignes)


# ------------------------------------------------------------------------------------------------------------------
# Le temps long : le premier à chaque élection dans une zone ; les bascules des conseils départementaux
# ------------------------------------------------------------------------------------------------------------------
TYPES_FIEFS = ("Présidentielle", "Législatives", "Européennes", "Régionales", "Départementales", "Cantonales", "Municipales")


def premiers(zone):
    """Pour chaque 1er tour depuis 1999 (résultats par bureau) : la nuance (ou, à la présidentielle, le candidat) arrivée en
    tête dans la zone, et son score."""
    s = d.scrutins()
    s = s[(s["tour"] == 1) & (s["annee"] >= 1999) & s["type"].isin(TYPES_FIEFS)]
    f, p = d.filtre(zone)
    liste = ",".join(f"'{x}'" for x in s["scrutin"])
    t = d.sql(f"""
        WITH z AS (SELECT scrutin, bureau_id, exprimes FROM {d.P_TOUS} p WHERE scrutin IN ({liste}) AND {f}),
        e AS (SELECT scrutin, sum(exprimes) exprimes FROM z GROUP BY 1),
        v AS (SELECT r.scrutin, coalesce(r.nuance, r.qui) nuance, sum(r.voix) voix FROM {d.R_TOUS} r JOIN z USING (scrutin, bureau_id)
              WHERE coalesce(r.nuance, r.qui) IS NOT NULL GROUP BY 1, 2)
        SELECT v.scrutin, arg_max(v.nuance, v.voix) nuance, 100.0 * max(v.voix) / any_value(e.exprimes) pct
        FROM v JOIN e USING (scrutin) GROUP BY v.scrutin""", p)
    t = t.merge(s[["scrutin", "type", "annee", "date"]], on="scrutin").sort_values("date")
    # (la présidentielle n'a pas de nuance : son « nuance » est le nom du candidat, reconnu par ses mots — LE PEN…)
    t["couleur"] = [theme.couleur_politique(n, mots=ty in d.TYPES_NATIONAUX) or "#B8BEC6" for n, ty in zip(t["nuance"], t["type"])]
    return t


def majorites_departementales(scrutin):
    """Département → le bloc (gauche, droite et centre, extrême droite, divers) qui a le plus de sièges au conseil
    départemental élu à ce scrutin (sièges figés), et sa nuance la plus nombreuse."""
    t = sieges.conseils_departementaux(scrutin)
    if t is None or len(t) == 0:
        return pd.DataFrame(columns=["dep", "bloc", "sieges", "total", "nuance"])
    t = t.assign(bloc=[theme.bloc_politique(n) for n in t["nuance"]])
    s = t.groupby(["dep", "bloc"])["sieges"].sum().reset_index()
    total = s.groupby("dep")["sieges"].sum().rename("total")
    s = s.sort_values("sieges", ascending=False).drop_duplicates("dep").join(total, on="dep")
    principale = (t.groupby(["dep", "bloc", "nuance"])["sieges"].sum().reset_index().sort_values("sieges", ascending=False)
                  .drop_duplicates(["dep", "bloc"]).set_index(["dep", "bloc"])["nuance"])
    s["nuance"] = [principale.get((dp, b)) for dp, b in zip(s["dep"], s["bloc"])]
    return s.sort_values("dep").reset_index(drop=True)


# ------------------------------------------------------------------------------------------------------------------
# L'échiquier politique : chaque parti placé d'après ses positions et ses idéologies (axes gauche – droite, Europe)
# ------------------------------------------------------------------------------------------------------------------
def echiquier(n=45):
    """Les partis placés sur l'échiquier : x = gauche – droite (moyenne de ses positions politiques, sinon de ses
    idéologies), y = Europe (moyenne de ses idéologies sur cet axe, vide si aucune). Les n plus présents dans la base
    (adhérents connus + candidats rattachés), dissous compris."""
    return d.sql(f"""
        WITH pos AS (SELECT pp.parti_id, avg(po.valeur) v FROM modele.parti_position pp
                     JOIN modele.position_politique po ON po.id = pp.position_politique_id WHERE po.valeur IS NOT NULL GROUP BY 1),
        ideo AS (SELECT pi.parti_id, ia.axe_id, avg(ia.valeur) v FROM modele.parti_ideologie pi
                 JOIN modele.ideologie_axe ia ON ia.ideologie_id = pi.ideologie_id GROUP BY 1, 2),
        poids AS (SELECT parti_id, count(*) n FROM (SELECT parti_id FROM modele.adhesion UNION ALL
                                                    SELECT parti_id FROM modele.investiture) GROUP BY 1)
        SELECT p.id, coalesce(p.sigle, p.libelle) etiquette, p.libelle, coalesce(pos.v, ix.v) x, iy.v y, poids.n,
               f.couleur, p.date_dissolution dissolution
        FROM modele.parti p JOIN poids ON poids.parti_id = p.id
        LEFT JOIN pos ON pos.parti_id = p.id
        LEFT JOIN ideo ix ON ix.parti_id = p.id AND ix.axe_id = 1 LEFT JOIN ideo iy ON iy.parti_id = p.id AND iy.axe_id = 2
        LEFT JOIN modele.nuance nu ON nu.id = p.nuance_id LEFT JOIN modele.famille f ON f.id = nu.famille_id
        WHERE coalesce(pos.v, ix.v) IS NOT NULL
        ORDER BY poids.n DESC LIMIT {int(n)}""")


def trajet(pid):
    """Les partis d'une personne dans l'ordre de ses adhésions (et de ses rattachements de candidat), pour l'échiquier."""
    return d.sql("""SELECT pa.id parti_id, coalesce(pa.sigle, pa.libelle) etiquette, min(x.debut) debut FROM (
                        SELECT parti_id, date_debut debut FROM modele.adhesion WHERE personne_id = ?
                        UNION ALL SELECT i.parti_id, sc.date FROM modele.candidature c JOIN modele.investiture i ON i.candidature_id = c.id
                        JOIN modele.scrutin sc ON sc.id = c.scrutin_id WHERE c.personne_id = ?) x
                    JOIN modele.parti pa ON pa.id = x.parti_id GROUP BY 1, 2 ORDER BY debut NULLS LAST""", [pid, pid])
