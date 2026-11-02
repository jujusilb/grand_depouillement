"""Les conseils EN PLACE, lus dans le modèle « personnes et mandats » (MariaDB, instantané modele.*), à trois dates.

    janvier 2020   les conseils élus en 2014 (et les régions et départements de 2015), en fin de mandat
    décembre 2020  les conseils élus en 2020
    août 2026      les conseils élus en 2026 (et les régions et départements de 2021)
Ces trois dates sont celles des versions du Répertoire national des élus d'où viennent les mandats.

Qui siège : les mandats (conseiller municipal, communautaire, départemental, régional) en cours à cette date.
Sa fonction : son mandat exécutif de la même élection (maire, adjoint, président, vice-président).
Sa liste et sa nuance : SA candidature à la même élection (modèle : candidature → liste) — plus de rapprochement par le nom.
Un conseil communautaire mélange les élus de plusieurs communes et de plusieurs listes : chacun prend la couleur de la
nuance de SA liste municipale. Les listes de 2014 n'ont pas de nuance : on la prend dans les résultats, par la tête de liste ;
les binômes départementaux de 2015 n'ont pas de fiche : on les retrouve par leur nom parmi les candidats.
"""
from datetime import date
from functools import lru_cache

import duckdb
import pandas as pd

from gd import donnees as d
from gd import theme

GRIS = "#B8BEC6"
BEIGE = "#D8C9AE"
SANS_NUANCE = "Petite commune, sans nuance"
SANS_LISTE = "Candidats sans liste (petite commune)"
LIBELLES = {"2020-01": "janvier 2020", "2020-12": "décembre 2020", "2026-08": "août 2026"}
JOURS = {"2020-01": date(2020, 1, 14), "2020-12": date(2020, 12, 2), "2026-08": date(2026, 8, 11)}
# niveau de zone : (fonction de base, fonctions exécutives, conseil des candidatures)
CONSEILS = {"commune": ("conseiller municipal", ("maire", "adjoint au maire", "maire délégué"), "municipal"),
            "epci": ("conseiller communautaire", ("président d'intercommunalité", "vice-président d'intercommunalité"), "municipal"),
            "departement": ("conseiller départemental", ("président du conseil départemental",
                                                          "vice-président du conseil départemental"), None),
            "region": ("conseiller régional", ("président du conseil régional", "vice-président du conseil régional"), "régional")}


@lru_cache(maxsize=1)
def disponible():
    try:
        return d.sql("SELECT count(*) FROM modele.mandat").iloc[0, 0] > 0
    except duckdb.Error:
        return False


ELECTIONS_DE_CONSEIL = ("muni", "regi", "dpmt", "cant")


def version_pour(scrutin):
    """La date (version du RNE) qui montre le conseil élu à ce scrutin, ou en place à cette date.
    Élection d'un conseil (Régionales 2021) : la première version prise APRÈS le scrutin (août 2026, pas décembre 2020 qui
    montre encore le conseil de 2015). Autre élection (Présidentielle 2022) : la dernière version prise AVANT sa date."""
    if int(scrutin[:4]) < 2014:
        return None
    code = "_".join(scrutin.split("_")[:2])
    e = d.sql("""SELECT max(s.date) jour FROM modele.scrutin s JOIN modele.election e ON e.id = s.election_id
                 WHERE e.code = ?""", [code])
    jour = pd.Timestamp(e.iloc[0, 0]).date() if len(e) and pd.notna(e.iloc[0, 0]) else date(int(scrutin[:4]), 12, 31)
    if code.split("_")[1] in ELECTIONS_DE_CONSEIL:
        return next((v for v, j in JOURS.items() if j > jour), "2026-08")
    avant = [v for v, j in JOURS.items() if j <= jour]
    return avant[-1] if avant else "2020-01"


def version_actuelle():
    """La version la plus récente du RNE : qui siège aujourd'hui."""
    return list(JOURS)[-1]


ZONE = "m.zone_id = (SELECT id FROM modele.zone WHERE niveau_id = ? AND code = ? ORDER BY date_fin NULLS FIRST LIMIT 1)"


def _en_place(niveau, filtre, params, jour):
    """Les mandats de base en cours ce jour-là, avec la personne, sa fonction exécutive, sa liste et sa nuance."""
    base, executives, conseil = CONSEILS[niveau]
    execs = ",".join(f"'{f.replace(chr(39), chr(39) * 2)}'" for f in executives)
    cand = "AND (c.conseil = ? OR c.conseil IS NULL)" if conseil else ""
    # (la candidature doit être sur le même territoire : la commune du conseiller — ou l'un de ses secteurs —, ou une fiche
    #  sans liste)
    meme_zone = {"commune": "b.zone_id IN (c.zone_id, c.zone_parent)", "epci": "cm.zone_id IN (c.zone_id, c.zone_parent)",
                 "region": "c.zone_id IN (SELECT a.zone_id FROM zone_dans a WHERE a.ancetre_id = b.zone_id)",   # (sa section)
                 "departement": "TRUE"}[niveau]
    return d.sql(f"""
        WITH b AS (SELECT m.id, m.personne_id, sm.election_id, m.zone_id, m.date_debut
                   FROM modele.mandat m JOIN modele.fonction f ON f.id = m.fonction_id
                   LEFT JOIN modele.scrutin sm ON sm.id = m.scrutin_id
                   WHERE f.libelle = ? AND {filtre}
                     AND coalesce(m.date_debut, DATE '1900-01-01') <= ? AND (m.date_fin IS NULL OR m.date_fin > ?)
                     AND m.motif_fin_id IS DISTINCT FROM (SELECT id FROM modele.motif_fin WHERE libelle = 'inconnu'))
        SELECT b.*, p.prenoms prenom, p.nom_usage nom, e.code election, coalesce(x.fonction, '') fonction,
               c.liste, c.nuance, zc.code commune_code, zb.libelle zone_libelle
        FROM b JOIN modele.personne p ON p.id = b.personne_id LEFT JOIN modele.election e ON e.id = b.election_id
        JOIN modele.zone zb ON zb.id = b.zone_id
        LEFT JOIN (SELECT DISTINCT ON (mx.personne_id, sx.election_id) mx.personne_id, sx.election_id,
                          upper(left(f.libelle, 1)) || substr(f.libelle, 2) fonction
                   FROM modele.mandat mx JOIN modele.fonction f ON f.id = mx.fonction_id
                   JOIN modele.scrutin sx ON sx.id = mx.scrutin_id WHERE f.libelle IN ({execs})
                   ORDER BY mx.personne_id, sx.election_id, f.id) x ON x.personne_id = b.personne_id AND x.election_id = b.election_id
        LEFT JOIN (SELECT DISTINCT ON (mc.personne_id, sy.election_id) mc.personne_id, sy.election_id, mc.zone_id
                   FROM modele.mandat mc JOIN modele.fonction f ON f.id = mc.fonction_id
                   JOIN modele.scrutin sy ON sy.id = mc.scrutin_id WHERE f.libelle = 'conseiller municipal') cm
               ON cm.personne_id = b.personne_id AND cm.election_id = b.election_id
        LEFT JOIN modele.zone zc ON zc.id = cm.zone_id
        LEFT JOIN (SELECT c.personne_id, sz.election_id, c.zone_id, zx.parent_id zone_parent, sz.tour, c.liste_id IS NULL fiche,
                          coalesce(l.libelle, CASE WHEN s.cle = 'listes déposées' THEN '{SANS_LISTE}' END) liste,
                          coalesce(nl.libelle, nc.libelle) nuance
                   FROM modele.candidature c JOIN modele.source s ON s.id = c.source_id
                   LEFT JOIN modele.liste l ON l.id = c.liste_id LEFT JOIN modele.zone zx ON zx.id = c.zone_id
                   LEFT JOIN modele.nuance nl ON nl.id = l.nuance_id LEFT JOIN modele.nuance nc ON nc.id = c.nuance_id
                   JOIN modele.scrutin sz ON sz.id = c.scrutin_id
                   WHERE TRUE {cand}) c
               ON c.personne_id = b.personne_id AND c.election_id = b.election_id AND (c.fiche OR {meme_zone})
        QUALIFY row_number() OVER (PARTITION BY b.id ORDER BY c.fiche, c.tour DESC) = 1""",
                 [base, *params, jour, jour] + ([conseil] if conseil else []))


def _nuances_2014(t):
    """Les listes de 2014 n'ont pas de nuance dans les fichiers du ministère : celle des résultats, par le nom de la tête."""
    manque = t["liste"].notna() & t["nuance"].isna() & t["election"].eq("2014_muni")
    if not manque.any():
        return t
    communes = sorted(set(t.loc[manque, "commune_code"].dropna()))
    if not communes:
        return t
    marque = ",".join("?" * len(communes))
    tetes = d.sql(f"""SELECT left(z.code, 5) commune, l.libelle liste, p.prenoms || ' ' || p.nom_usage tete
                      FROM modele.liste l JOIN modele.scrutin sl ON sl.id = l.scrutin_id JOIN modele.election e ON e.id = sl.election_id AND e.code = '2014_muni'
                      JOIN modele.zone z ON z.id = l.zone_id
                      JOIN modele.candidature c ON c.liste_id = l.id AND c.tete_de_liste JOIN modele.personne p ON p.id = c.personne_id
                      WHERE left(z.code, 5) IN ({marque})""", communes)
    res = d.sql(f"""SELECT p.code_commune commune, r.qui, any_value(r.nuance) nuance FROM {d.R('2014_muni_t1')} r
                    JOIN {d.P('2014_muni_t1')} p USING (bureau_id) WHERE p.code_commune IN ({marque}) GROUP BY 1, 2""",
                communes)
    nuances = {(c, d.normaliser(q)): n for c, q, n in zip(res["commune"], res["qui"], res["nuance"])}
    par_liste = {(c, l): nuances.get((c, d.normaliser(te))) for c, l, te in zip(tetes["commune"], tetes["liste"], tetes["tete"])}
    t.loc[manque, "nuance"] = [par_liste.get((c, l)) for c, l in zip(t.loc[manque, "commune_code"], t.loc[manque, "liste"])]
    return t


def _cle(nom, prenom):
    """« DUPONT », « Jean-Marie Pierre » → « dupont jean »."""
    p = d.normaliser(prenom or "").split()
    return d.normaliser(nom or "") + " " + (p[0] if p else "")


def _binomes(t, dep, election):
    """La nuance d'un binôme départemental (2015 : pas de fiche ; 2021 : fiche sans nuance) : par son nom, dans les résultats."""
    manque = t["nuance"].isna()
    if not manque.any():
        return t
    try:
        c = d.sql(f"""SELECT p.scrutin, r.qui, any_value(r.nuance) nuance FROM {d.R_TOUS} r JOIN {d.P_TOUS} p USING (scrutin, bureau_id)
                     WHERE p.scrutin IN (?, ?) AND p.code_departement = ? GROUP BY 1, 2 ORDER BY p.scrutin DESC""",
                  [election + "_t2", election + "_t1", dep])
    except duckdb.Error:
        return t
    r = {}
    for qui, nu in zip(c["qui"], c["nuance"]):
        for bout in str(qui).split(" et "):
            mots = bout.split()[1:]                       # (sans « M. » ou « Mme »)
            nom = " ".join(m for m in mots if m.isupper() and len(m) > 1)
            prenom = " ".join(m for m in mots if not (m.isupper() and len(m) > 1))
            r.setdefault(_cle(nom, prenom), (qui, nu))
    trouve = [r.get(_cle(n, p)) for n, p in zip(t.loc[manque, "nom"], t.loc[manque, "prenom"])]
    t.loc[manque, "liste"] = [x[0] if x else None for x in trouve]
    t.loc[manque, "nuance"] = [x[1] if x else None for x in trouve]
    return t


def _fonction_rang(f):
    f = str(f or "").lower()
    return 0 if f.startswith(("maire", "président")) else 1 if ("adjoint" in f or "vice" in f) else 2


def _par_fonction(t):
    """Sans liste connue : on range par fonction (le maire ou le président, ses adjoints ou vice-présidents, les autres)."""
    k = t["fonction"].map(_fonction_rang)
    t["groupe"] = k.map({0: "Maire / président(e)", 1: "Adjoints / vice-présidents", 2: "Conseillers"})
    t["couleur"] = k.map({0: "#0B5394", 1: "#6FA8DC", 2: GRIS})
    t["rang"] = k
    return t


def _colorer(t, par_nuance, perdu="Liste inconnue"):
    """Chaque élu prend sa liste (ou sa nuance) et la couleur de la nuance ; sans liste connue, il reste gris."""
    def famille(nu):
        f = theme.FAMILLE_DE_COULEUR.get(theme.couleur_politique(nu, mots=False))
        return f"{nu} ({f})" if f else str(nu)
    # (une même liste s'écrit un peu autrement d'un secteur à l'autre à Paris, Lyon, Marseille : les 18 premières lettres
    #  font la liste, on garde l'écriture la plus courante)
    norme = t["liste"].map(lambda l: d.normaliser(l).replace(" ", "")[:18] if isinstance(l, str) else "")
    ecrit = t.groupby(norme)["liste"].agg(lambda x: x.value_counts().index[0] if x.notna().any() else None)
    t["liste"] = [ecrit.get(k) if k else None for k in norme]
    if par_nuance:
        t["groupe"] = [famille(nu) if nu else SANS_NUANCE if l else perdu for nu, l in zip(t["nuance"], t["liste"])]
    else:
        # (une fiche de candidat sans liste — régionales 2015 — donne au moins la nuance)
        t["groupe"] = [l if l else famille(nu) if nu else perdu for l, nu in zip(t["liste"], t["nuance"])]
    t["couleur"] = [theme.couleur_politique(nu, mots=False) or GRIS if nu else BEIGE if l else GRIS for nu, l in zip(t["nuance"], t["liste"])]
    t["rang"] = [theme.rang_politique(nu, mots=False) if nu else 50 if l else 99 for nu, l in zip(t["nuance"], t["liste"])]
    return t


def conseil(scrutin, zone, version=None):
    """dict(titre, elus, note, version) ou dict(message). elus : nom affiché, groupe, couleur, rang, lieu (commune · fonction).
    version : une version du RNE imposée (« Qui siège aujourd'hui ? » : la plus récente, quelle que soit l'élection choisie)."""
    if not disponible():
        return {"message": "Le modèle « personnes et mandats » n'est pas branché : lance brancher_modele.py."}
    v = version or version_pour(scrutin)
    if v is None:
        return {"message": "Les mandats locaux commencent avec les conseils élus en 2014 : choisis un scrutin de 2014 ou après."}
    quand, jour = LIBELLES[v], JOURS[v]
    n, code = zone.niveau, str(zone.code).split("_")[0]
    if n in ("commune", "bureau", "arrmun"):
        com = d.ancetre("arrmun", code, "commune") if n == "arrmun" else code
        t = _nuances_2014(_en_place("commune", ZONE, [d.NIVEAU["commune"], com], jour))
        quoi = f"Conseil municipal en place ({quand})"
        t = _colorer(t, False)
        t["lieu"] = t["fonction"]
    elif n == "epci":
        t = _nuances_2014(_en_place("epci", ZONE, [d.NIVEAU["epci"], code], jour))
        quoi = f"Conseil communautaire en place ({quand})"
        t = _colorer(t, True, "Liste inconnue (nom écrit autrement, remplaçant…)")
        communes = d.noms_zones("commune")
        t["lieu"] = [f"{communes.get(c, c or '')} · {f}" if f else str(communes.get(c, c or "")) for c, f in zip(t["commune_code"], t["fonction"])]
    elif n == "departement":
        t = _en_place("departement", f"""m.zone_id IN (SELECT a.zone_id FROM zone_dans a JOIN modele.zone dz ON dz.id = a.ancetre_id
                                           WHERE dz.niveau_id = {d.NIVEAU['departement']} AND dz.code = ?)""", [code], jour)
        t = _binomes(t, code, "2021_dpmt" if v == "2026-08" else "2015_dpmt")
        quoi = f"Conseil départemental en place ({quand})"
        t = _colorer(t, True, "Binôme non retrouvé (élu partiel…)")
        t["lieu"] = [f"{c} · {f}" if f else str(c) for c, f in zip(t["zone_libelle"], t["fonction"])]
    elif n == "region":
        t = _en_place("region", ZONE, [d.NIVEAU["region"], code], jour)
        quoi = f"Conseil régional en place ({quand})"
        t = _colorer(t, False)
        t["lieu"] = t["fonction"]
    else:
        return {"message": "Choisis une commune, une intercommunalité, un département ou une région (volet Zone) : "
                           "c'est son conseil en place qui s'affiche."}
    if t.empty:
        return {"message": f"Personne en place ({quand}) pour {zone.libelle}."}
    t["qui"] = [f"{p} {str(x).upper()}" for p, x in zip(t["prenom"].fillna(""), t["nom"])]
    t["chef"] = t["fonction"].map(_fonction_rang) == 0
    t = t.sort_values(["rang", "groupe", "chef"], ascending=[True, True, False]).reset_index(drop=True)
    note = (f"Qui siège en {quand} : les mandats en cours à cette date (modèle « personnes et mandats », d'après le Répertoire "
            "national des élus). La liste de chacun est celle de sa propre candidature à la même élection ; en gris, ceux dont "
            "on ne connaît pas la candidature (remplaçant, liste de 2008…)."
            + (" Départementales : la nuance du binôme est retrouvée par son nom dans les résultats." if n == "departement" else "")
            + (" Les démissionnaires ont déjà été remplacés." if v == "2020-01" else ""))
    return {"titre": f"{quoi} – {zone.libelle}", "elus": t, "note": note, "version": v}
