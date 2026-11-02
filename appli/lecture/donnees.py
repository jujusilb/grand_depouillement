"""
donnees.py — Toutes les questions posées à la base data/depouillement.duckdb.

Aucune fonction ici ne connaît tkinter : chacune reçoit des réglages (scrutin, zone…) et renvoie un DataFrame ou une valeur.
"""

import sys
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# Le dossier data/ : à côté de l'exécutable (version .exe) ou à côté du dossier gd/ (version py)
if getattr(sys, "frozen", False):
    DOSSIER = Path(sys.executable).resolve().parent
else:
    DOSSIER = Path(__file__).resolve().parents[2]
# les données de l'appli : donnees/appli (version py) ou data/ à côté de l'exécutable (version .exe)
DATA = DOSSIER / "data" if getattr(sys, "frozen", False) else DOSSIER / "donnees" / "appli"
BASE = DATA / "depouillement.duckdb"

_con = None


def con():
    global _con
    if _con is None:
        if not BASE.exists():
            raise FileNotFoundError(f"Base introuvable : {BASE}\nLance d'abord 3_base/base_appli.py (ou l'installation).")
        _con = duckdb.connect(str(BASE), read_only=True)
        # le modèle « personnes et mandats » (MariaDB fait foi ; on lit son instantané, rafraîchi s'il a changé)
        from lecture import modele
        modele.brancher(_con, BASE.parent)
        # chaque zone et toutes celles qui la contiennent (bureau → commune → arrondissement → département → région → pays),
        # calculé une fois au lancement depuis zone.parent_id : « les communes du Loiret » sans connaître la profondeur
        _con.execute("""CREATE TEMP TABLE zone_dans AS
            WITH RECURSIVE a(zone_id, ancetre_id) AS (
                SELECT id, id FROM modele.zone
                UNION ALL SELECT a.zone_id, z.parent_id FROM a JOIN modele.zone z ON z.id = a.ancetre_id WHERE z.parent_id IS NOT NULL)
            SELECT * FROM a""")
        # les scrutins (un par tour, table scrutin du modèle), avec le code des résultats : « 2022_legi_t1 »
        _con.execute(r"""CREATE TEMP TABLE scrutin_tour AS
            SELECT e.code || '_t' || s.tour AS scrutin, s.id AS scrutin_id, ce.libelle AS type_libelle, CAST(e.annee AS BIGINT) AS annee, s.tour,
                   s.date, s.libelle
            FROM modele.scrutin s JOIN modele.election e ON e.id = s.election_id
            JOIN modele.categorie_election ce ON ce.id = e.categorie_election_id
            WHERE s.date IS NOT NULL""")
        # chaque bureau de vote avec ses codes et libellés (commune, arrondissement, département, région), lus dans ses
        # zones parentes : participation et resultat ne gardent que bureau_id
        _con.execute("""CREATE TEMP TABLE bureau_lieu AS
            SELECT z.id bureau_id, any_value(z.code) id_brut_miom, split_part(any_value(z.code), '_', 2) code_bv,
                   max(a.code) FILTER (WHERE a.niveau_id = 8) code_commune, max(a.libelle) FILTER (WHERE a.niveau_id = 8) libelle_commune,
                   max(a.code) FILTER (WHERE a.niveau_id = 4) code_arr, max(a.libelle) FILTER (WHERE a.niveau_id = 4) libelle_arr,
                   max(a.code) FILTER (WHERE a.niveau_id = 3) code_departement,
                   max(a.libelle) FILTER (WHERE a.niveau_id = 3) libelle_departement,
                   max(a.code) FILTER (WHERE a.niveau_id = 2) code_region, max(a.libelle) FILTER (WHERE a.niveau_id = 2) libelle_region,
                   any_value(ca.code) code_canton, any_value(ca.libelle) libelle_canton
            FROM modele.zone z JOIN zone_dans d ON d.zone_id = z.id JOIN modele.zone a ON a.id = d.ancetre_id
            LEFT JOIN modele.bureau b ON b.id = z.id LEFT JOIN modele.zone ca ON ca.id = b.canton_id
            WHERE z.niveau_id = 12 GROUP BY z.id""")
    return _con


def sql(requete, params=None):
    return con().execute(requete, params or []).df()


# =============================================================================================
# Les scrutins
# =============================================================================================

@lru_cache(None)
def scrutins():
    d = sql("SELECT scrutin, type_libelle AS type, annee, tour, CAST(date AS DATE) AS date, libelle FROM scrutin_tour ORDER BY date")
    d["date"] = pd.to_datetime(d["date"])
    return d


NOMS_TOURS = {1: "1er tour", 2: "2nd tour", 3: "Les 2 tours"}     # 3 = le 2nd tour là où il a eu lieu, sinon le 1er
TOURS_PAR_NOM = {**{v: k for k, v in NOMS_TOURS.items()}, "Tour unique": 1}
TYPES_NATIONAUX = ("Présidentielle", "Européennes", "Référendum")   # les mêmes candidats (ou réponses) partout en France
UN_SEUL_TOUR = ("Européennes", "Référendum")


@lru_cache(maxsize=1)
def _deux_tours():
    """« Les 2 tours » : pour chaque bureau, le 2nd tour s'il a eu lieu, sinon le 1er (le résultat qui a compté). Un
    calcul (P et R ci-dessous), proposé pour les élections à deux tours — sauf la présidentielle (une seule
    circonscription) et les législatives d'avant 1999 (1er tour par commune, 2nd par circonscription)."""
    s = scrutins()
    t1 = s[(s["tour"] == 1) & (s["type"] != "Présidentielle") & ~((s["type"] == "Législatives") & (s["annee"] < 1999))]
    avec_t2 = set(s.loc[s["tour"] == 2, "scrutin"].str.replace("_t2", "_t1"))
    d = t1[t1["scrutin"].isin(avec_t2)].copy()
    d["scrutin"] = d["scrutin"].str.replace("_t1", "_2t")
    d["tour"] = 3
    d["libelle"] = d["libelle"].str.replace("1er tour", "les 2 tours")
    return d


@lru_cache(maxsize=1)
def _tous():
    """Les scrutins ET les « 2 tours » (pour les listes de choix et les libellés ; pas pour les courbes dans le temps)."""
    return pd.concat([scrutins(), _deux_tours()])


@lru_cache(maxsize=1)
def _ids():
    return dict(sql("SELECT scrutin, scrutin_id FROM scrutin_tour").values)


def _tours_de(scrutin):
    """(id du scrutin, id du tour de repli) : « 2022_legi_t1 » → (id, None) ; « 2022_legi_2t » → (id du 2nd, id du 1er)."""
    ids = _ids()
    if str(scrutin).endswith("_2t"):
        base = str(scrutin)[:-3]
        return int(ids.get(base + "_t2", -1)), int(ids.get(base + "_t1", -1))
    return int(ids.get(scrutin, -1)), None


def P(scrutin):
    """La participation d'un scrutin, un bureau par ligne, avec les codes et libellés du bureau (« FROM {P(s)} p »)."""
    a, b = _tours_de(scrutin)
    base = "SELECT p.*, l.* EXCLUDE (bureau_id) FROM participation p JOIN bureau_lieu l USING (bureau_id)"
    if b is None:
        return f"({base} WHERE p.scrutin_id = {a})"
    return (f"({base} WHERE p.scrutin_id = {a} UNION ALL {base} WHERE p.scrutin_id = {b} "
            f"AND p.bureau_id NOT IN (SELECT bureau_id FROM participation WHERE scrutin_id = {a}))")


# les voix avec le code de leur nuance (« LDVD » : nuance.libelle) et son explication (« Liste divers droite »)
VOIX = ("SELECT r.* EXCLUDE (nuance_id), n.libelle nuance, n.explication FROM resultat r "
        "LEFT JOIN modele.nuance n ON n.id = r.nuance_id")


def R(scrutin):
    """Les voix d'un scrutin, bureau par bureau (« FROM {R(s)} r », à joindre à P par bureau_id)."""
    a, b = _tours_de(scrutin)
    if b is None:
        return f"({VOIX} WHERE r.scrutin_id = {a})"
    return (f"({VOIX} WHERE r.scrutin_id = {a} UNION ALL {VOIX} WHERE r.scrutin_id = {b} "
            f"AND r.bureau_id NOT IN (SELECT bureau_id FROM participation WHERE scrutin_id = {a}))")


# tous les scrutins à la fois, avec leur code (« 2022_legi_t1 ») : pour les courbes dans le temps
P_TOUS = ("(SELECT p.*, l.* EXCLUDE (bureau_id), s.scrutin FROM participation p JOIN bureau_lieu l USING (bureau_id) "
          "JOIN scrutin_tour s USING (scrutin_id))")
R_TOUS = f"(SELECT x.*, s.scrutin FROM ({VOIX}) x JOIN scrutin_tour s USING (scrutin_id))"


def types():
    ordre = ["Présidentielle", "Législatives", "Sénatoriales", "Européennes", "Référendum", "Municipales", "Régionales", "Départementales", "Cantonales"]
    presents = set(scrutins()["type"])
    return [t for t in ordre if t in presents]


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def annees(type_):
    """Les années d'un type, la plus récente d'abord ; deux élections la même année (législatives de 1871, de 1946)
    se distinguent par leur mois : « 1946 · juin », « 1946 · novembre »."""
    s = scrutins()
    s = s[(s["type"] == type_) & (s["tour"] == 1)].sort_values("date", ascending=False)
    doubles = set(s.loc[s["annee"].duplicated(keep=False), "annee"])
    return list(dict.fromkeys(f"{r.annee} · {MOIS[r.date.month - 1]}" if r.annee in doubles else r.annee for r in s.itertuples()))


def annee_de(scrutin):
    """L'année d'un scrutin telle que la liste des années l'écrit (« 1871 · février » s'il y en a deux cette année-là)."""
    s = _tous().set_index("scrutin").loc[scrutin]
    t1 = scrutins().set_index("scrutin")
    base = scrutin.replace("_t2", "_t1").replace("_2t", "_t1")
    for a in annees(s["type"]):
        if str(a).startswith(str(s["annee"])) and ("·" not in str(a) or base in t1.index and
                                                   MOIS[t1.loc[base, "date"].month - 1] == str(a).split("·")[1].strip()):
            return str(a)
    return str(s["annee"])


def _an(annee):
    """« 2005 · Constitution européenne » → 2005 (le volet Scrutin affiche le thème des référendums à côté de l'année)."""
    return int(str(annee)[:4])


def _choix(type_, annee):
    """Les scrutins (tous les tours) d'un type et d'une année ; « 1946 · juin » : seulement celui de juin."""
    s = _tous()
    s = s[(s["type"] == type_) & (s["annee"] == _an(annee))]
    mois = str(annee).split("·")[1].strip() if "·" in str(annee) else ""
    if mois in MOIS:
        t1 = s[(s["tour"] == 1) & (s["date"].dt.month == MOIS.index(mois) + 1)]["scrutin"]
        s = s[s["scrutin"].str.replace("_t2", "_t1").str.replace("_2t", "_t1").isin(set(t1))]
    return s


def tours(type_, annee):
    return sorted(_choix(type_, annee)["tour"].unique().tolist())


def scrutin_id(type_, annee, tour):
    t = _choix(type_, annee)
    t = t[t["tour"] == int(tour)]
    return t["scrutin"].iloc[0] if len(t) else None


def libelle(scrutin):
    s = _tous().set_index("scrutin")
    return s.loc[scrutin, "libelle"] if scrutin in s.index else scrutin


def type_de(scrutin):
    s = _tous().set_index("scrutin")
    return s.loc[scrutin, "type"] if scrutin in s.index else ""


# =============================================================================================
# Les zones (volet Zone)
# =============================================================================================

@dataclass(frozen=True)
class Zone:
    niveau: str = "france"      # france, region, departement, arrondissement, epci, circo, canton, commune, arrmun, bureau
    code: str = None
    libelle: str = "France entière"


FRANCE = Zone()
VILLES_PLM = ("75056", "69123", "13055")
# les niveaux de la table modele.niveau (une seule table zone pour tous les territoires, niveau_id = la discrimination)
NIVEAU = {"pays": 1, "region": 2, "departement": 3, "arrondissement": 4, "circo": 5, "canton": 6, "epci": 7, "commune": 8,
          "arrmun": 9, "secteur": 10, "section": 11, "bureau": 12, "section_regionale": 13, "circo_metropole": 14}
# une zone d'aujourd'hui : pas finie (les communes fusionnées, les anciens découpages ont une date de fin)
ACTUELLE = "{z}.date_fin IS NULL"


def _dans(niveau, code):
    """Les zones contenues dans la zone (niveau, code), elle comprise : « z.id IN (…) »."""
    return (f"""(SELECT a.zone_id FROM zone_dans a JOIN modele.zone d ON d.id = a.ancetre_id
                WHERE d.niveau_id = {NIVEAU[niveau]} AND d.code = ?)""", [code])


def filtre(zone, a="p"):
    """La condition SQL qui garde les bureaux de la zone (alias a = la table participation)."""
    n, c = zone.niveau, zone.code
    simples = {"region": "code_region", "departement": "code_departement", "arrondissement": "code_arr",
               "commune": "code_commune", "bureau": "id_brut_miom"}
    if n == "france" or c is None:
        return "TRUE", []
    if n in simples:
        return f"{a}.{simples[n]} = ?", [c]
    if n == "epci":
        return (f"""{a}.code_commune IN (SELECT z.code FROM modele.commune cm JOIN modele.zone z ON z.id = cm.id
                    JOIN modele.zone e ON e.id = cm.epci_id WHERE e.code = ?)""", [c])
    if n in ("circo", "canton"):
        col = "circonscription_id" if n == "circo" else "canton_id"
        return (f"""{a}.id_brut_miom IN (SELECT z.code FROM modele.bureau b JOIN modele.zone z ON z.id = b.id
                    JOIN modele.zone t ON t.id = b.{col} WHERE t.code = ?)""", [c])
    if n == "arrmun":
        return (f"""{a}.id_brut_miom IN (SELECT z.code FROM modele.zone z JOIN modele.zone m ON m.id = z.parent_id
                    WHERE z.niveau_id = {NIVEAU['bureau']} AND m.niveau_id = {NIVEAU['arrmun']} AND m.code = ?)""", [c])
    return "TRUE", []


def _liste(niveau, dans=None, ordre="z.libelle"):
    """Les zones d'aujourd'hui d'un niveau (code, libelle), dans une autre zone (niveau, code) si on la donne."""
    cond, p = f"z.niveau_id = {NIVEAU[niveau]} AND {ACTUELLE.format(z='z')}", []
    if dans and dans[1]:
        sous, p = _dans(*dans)
        cond += f" AND z.id IN {sous}"
    return sql(f"SELECT z.code, z.libelle FROM modele.zone z WHERE {cond} ORDER BY {ordre}", p)


def regions():
    return _liste("region")


def departements(region=None):
    # (sans les zones qui n'ont aucune commune : la Collectivité européenne d'Alsace, section des régionales)
    d = _liste("departement", ("region", region))
    avec = set(sql(f"""SELECT DISTINCT d.code FROM modele.zone d JOIN modele.zone c ON c.parent_id = d.id
                       WHERE d.niveau_id = {NIVEAU['departement']}""")["code"])
    return d[d["code"].isin(avec)].reset_index(drop=True)


def arrondissements(dep):
    return _liste("arrondissement", ("departement", dep))


def _communes_de(dep, arr):
    """La condition « la commune cm.id est dans le département (ou l'arrondissement) »."""
    sous, p = _dans("arrondissement", arr) if arr else _dans("departement", dep)
    return f"cm.id IN {sous}", p


def epcis(dep, arr=None):
    cond, p = _communes_de(dep, arr)
    return sql(f"""SELECT DISTINCT e.code, e.libelle FROM modele.commune cm JOIN modele.zone e ON e.id = cm.epci_id
                   JOIN modele.zone z ON z.id = cm.id WHERE {cond} AND {ACTUELLE.format(z='z')} ORDER BY e.libelle""", p)


def _par_bureau(colonne, dep, arr):
    """Les circonscriptions (ou cantons) des bureaux d'un département (ou d'un arrondissement)."""
    sous, p = _dans("arrondissement", arr) if arr else _dans("departement", dep)
    return sql(f"""SELECT DISTINCT t.code, t.libelle FROM modele.bureau b JOIN modele.zone t ON t.id = b.{colonne}
                   WHERE b.id IN {sous} ORDER BY t.libelle""", p)


def circos(dep, arr=None):
    return _par_bureau("circonscription_id", dep, arr)


def cantons(dep, arr=None):
    return _par_bureau("canton_id", dep, arr)


def communes(dep, arr=None, epci=None, circo=None, canton=None):
    cond, p = _communes_de(dep, arr)
    if epci:
        cond += " AND cm.epci_id = (SELECT id FROM modele.zone WHERE niveau_id = ? AND code = ?)"
        p += [NIVEAU["epci"], epci]
    if circo or canton:
        col, val = ("circonscription_id", circo) if circo else ("canton_id", canton)
        cond += f""" AND cm.id IN (SELECT a.ancetre_id FROM modele.bureau b JOIN modele.zone t ON t.id = b.{col}
                                   JOIN zone_dans a ON a.zone_id = b.id WHERE t.code = ?)"""
        p.append(val)
    return sql(f"""SELECT z.code, z.libelle FROM modele.commune cm JOIN modele.zone z ON z.id = cm.id
                   WHERE {cond} AND {ACTUELLE.format(z='z')} ORDER BY z.libelle""", p)


@lru_cache(maxsize=1)
def explications_nuances():
    """{code de nuance : son explication} (« LDVD » : « Liste divers droite ») — pour l'info-bulle des légendes."""
    t = sql("SELECT libelle, explication FROM modele.nuance WHERE explication IS NOT NULL")
    return dict(zip(t["libelle"], t["explication"]))


def explication(texte):
    """L'explication de la nuance qui commence un texte de légende (« LUG — 24 », « LDVD (divers droite) »), ou None."""
    e = explications_nuances()
    mot = str(texte).split(" ")[0].strip(" (),:—-") if texte else ""
    return e.get(mot) or e.get(str(texte).split(" (")[0].split(" —")[0].strip())


@lru_cache(maxsize=16)
def nuances_des_candidats(scrutin):
    """La nuance la plus fréquente de chaque candidat / liste d'un scrutin (pour lui donner sa couleur politique)."""
    r = sql(f"SELECT qui, mode(nuance) nuance FROM {R(scrutin)} WHERE nuance IS NOT NULL GROUP BY qui")
    return dict(zip(r["qui"], r["nuance"]))


def normaliser(texte):
    """« Le Puy-en-Velay » → « le puy en velay » : sans accents, sans tirets ni apostrophes (pour chercher en tapant)."""
    t = unicodedata.normalize("NFD", str(texte).lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    abreges = {"st": "saint", "ste": "sainte"}      # « st etienne » trouve Saint-Étienne
    return " ".join(abreges.get(m, m) for m in t.replace("-", " ").replace("'", " ").replace("’", " ").split())


def chercher_communes(texte, n=30):
    """Les communes dont le nom contient le texte tapé (ou dont le code INSEE est ce texte) ; celles qui COMMENCENT par lui d'abord."""
    q = normaliser(texte)
    nom = "replace(replace(strip_accents(lower(z.libelle)), '-', ' '), chr(39), ' ')"
    return sql(f"""SELECT z.code, z.libelle, d.libelle AS departement FROM modele.zone z
                   JOIN zone_dans a ON a.zone_id = z.id JOIN modele.zone d ON d.id = a.ancetre_id AND d.niveau_id = {NIVEAU['departement']}
                   WHERE z.niveau_id = {NIVEAU['commune']} AND {ACTUELLE.format(z='z')} AND ({nom} LIKE ? OR z.code = ?)
                   ORDER BY z.code = ? DESC, {nom} LIKE ? DESC, length(z.libelle), z.libelle LIMIT ?""",
               [f"%{q}%", texte.strip(), texte.strip(), f"{q}%", n])


def ancetre(niveau_zone, code, niveau):
    """Le code de la zone d'un niveau qui contient une zone (« la région du département 43 » → 84), ou None."""
    r = sql("""SELECT d.code FROM modele.zone z JOIN zone_dans a ON a.zone_id = z.id JOIN modele.zone d ON d.id = a.ancetre_id
               WHERE z.niveau_id = ? AND z.code = ? AND d.niveau_id = ? ORDER BY z.date_fin NULLS FIRST LIMIT 1""",
            [NIVEAU[niveau_zone], code, NIVEAU[niveau]])
    return r.iloc[0, 0] if len(r) else None


def nom_zone(niveau, code):
    """Le libellé d'une zone (le code s'il n'y en a pas)."""
    return noms_zones(niveau).get(code, code)


@lru_cache(maxsize=16)
def noms_zones(niveau):
    """{code: libellé} des zones d'un niveau (une zone d'aujourd'hui l'emporte sur une ancienne de même code)."""
    t = sql("SELECT code, libelle FROM modele.zone WHERE niveau_id = ? ORDER BY date_fin DESC NULLS LAST", [NIVEAU[niveau]])
    return dict(zip(t["code"], t["libelle"]))


def ou_est(zone):
    """La région, le département et la commune d'une zone (pour remplir la cascade quand on la choisit d'un coup)."""
    if zone.niveau in ("commune", "bureau"):
        com = str(zone.code).split("_")[0]
        dp = ancetre("commune", com, "departement")
        if dp:
            return pd.Series({"r": ancetre("departement", dp, "region"), "dp": dp, "cm": com})
    if zone.niveau == "departement":
        r = ancetre("departement", zone.code, "region")
        if r:
            return pd.Series({"r": r, "dp": zone.code, "cm": None})
    f, p = filtre(zone)
    return sql(f"""SELECT any_value(code_region) r, any_value(code_departement) dp, any_value(code_commune) cm
                   FROM {P('2022_legi_t1')} p WHERE {f}""", p).iloc[0]


def arrmuns(commune):
    return _liste("arrmun", ("commune", commune), ordre="z.code")


def bureaux(commune=None, arrmun=None, canton=None, circo=None, epci=None, arr=None):
    # (les bureaux d'aujourd'hui : ceux du découpage actuel, rattachés à une circonscription ; les bureaux des
    #  scrutins passés sont aussi des zones, mais ne sont plus proposés)
    cond, p = ["b.circonscription_id IS NOT NULL"], []
    if commune:
        sous, q = _dans("arrmun", arrmun) if arrmun else _dans("commune", commune)
        cond.append(f"b.id IN {sous}"); p += q
    elif canton or circo:
        col = "canton_id" if canton else "circonscription_id"
        cond.append(f"b.{col} = (SELECT id FROM modele.zone WHERE niveau_id = ? AND code = ? AND date_fin IS NULL)")
        p += [NIVEAU["canton" if canton else "circo"], canton or circo]
        if arr:
            sous, q = _dans("arrondissement", arr)
            cond.append(f"b.id IN {sous}"); p += q
    elif epci:
        cond.append("""b.id IN (SELECT a.zone_id FROM zone_dans a JOIN modele.commune cm ON cm.id = a.ancetre_id
                        JOIN modele.zone e ON e.id = cm.epci_id WHERE e.code = ?)"""); p.append(epci)
    else:
        return pd.DataFrame(columns=["code", "libelle"])
    numero = "split_part(z.code, '_', 2) || coalesce(' · ' || nullif(z.libelle, ''), '')"
    avec_commune = "c.libelle || ' – ' ||" if not commune else ""
    return sql(f"""SELECT z.code, {avec_commune} {numero} AS libelle
                   FROM modele.bureau b JOIN modele.zone z ON z.id = b.id
                   JOIN modele.zone c ON c.niveau_id = {NIVEAU['commune']} AND c.code = split_part(z.code, '_', 1)
                     AND c.date_fin IS NULL
                   WHERE {' AND '.join(cond)} ORDER BY 2""", p)


# =============================================================================================
# Participation
# =============================================================================================

INDICATEURS = {   # nom : (numérateur, dénominateur)
    "Abstention": ("abstentions", "inscrits"), "Participation": ("votants", "inscrits"), "Blancs": ("blancs", "votants"),
    "Nuls": ("nuls", "votants"), "Blancs + nuls": ("blancs + nuls", "votants"), "Exprimés": ("exprimes", "inscrits"),
}


def _taux(indicateur):
    num, den = INDICATEURS[indicateur]
    return f"100.0 * sum({num}) / nullif(sum({den}), 0)"


def totaux(scrutin, zone=FRANCE):
    f, p = filtre(zone)
    d = sql(f"""SELECT sum(inscrits) inscrits, sum(abstentions) abstentions, sum(votants) votants, sum(blancs) blancs,
                       sum(nuls) nuls, sum(exprimes) exprimes, count(*) bureaux
                FROM {P(scrutin)} p WHERE {f}""", p).iloc[0]
    r = d.to_dict()
    ins, vot = r["inscrits"] or 0, r["votants"] or 0
    r.update({k: (100 * r[n.split(" ")[0]] / (ins if d_ == "inscrits" else vot) if (ins if d_ == "inscrits" else vot) else np.nan)
              for k, (n, d_) in INDICATEURS.items() if " + " not in n})
    r["Blancs + nuls"] = 100 * ((r["blancs"] or 0) + (r["nuls"] or 0)) / vot if vot else np.nan
    return r


def taux_bureaux(scrutin, zone, indicateur):
    f, p = filtre(zone)
    num, den = INDICATEURS[indicateur]
    return sql(f"""SELECT id_brut_miom, code_commune, libelle_commune, inscrits, 100.0 * ({num}) / nullif({den}, 0) AS valeur
                   FROM {P(scrutin)} p WHERE {f} AND inscrits > 0""", p)


def serie_taux(zone, indicateur, tour=None):
    """Un taux à chaque scrutin dans la zone (pour les courbes « dans le temps »)."""
    f, p = filtre(zone)
    cond = "AND s.tour = ?" if tour else ""
    return sql(f"""SELECT s.scrutin, s.type_libelle AS type, s.annee, s.tour, CAST(s.date AS DATE) AS date, {_taux(indicateur)} AS valeur
                   FROM {P_TOUS} p JOIN scrutin_tour s USING (scrutin) WHERE {f} {cond}
                   GROUP BY ALL ORDER BY date""", p + ([tour] if tour else []))


def taux_par_scrutin_et_bureau(zone, indicateur, tour=1):
    f, p = filtre(zone)
    num, den = INDICATEURS[indicateur]
    return sql(f"""SELECT s.scrutin, s.type_libelle AS type, CAST(s.date AS DATE) AS date, 100.0 * ({num}) / nullif({den}, 0) AS valeur
                   FROM {P_TOUS} p JOIN scrutin_tour s USING (scrutin) WHERE {f} AND s.tour = ? AND p.inscrits > 0""", p + [tour])


# =============================================================================================
# Résultats
# =============================================================================================

REGROUPEMENTS = {"Candidat / liste": "qui", "Nuance": "nuance"}


def resultats(scrutin, zone=FRANCE, regroupement="Candidat / liste"):
    f, p = filtre(zone)
    cle = REGROUPEMENTS[regroupement]
    d = sql(f"""WITH z AS (SELECT bureau_id, exprimes FROM {P(scrutin)} p WHERE {f})
                SELECT r.{cle} AS qui, any_value(r.nuance) AS nuance, sum(r.voix) AS voix, (SELECT sum(exprimes) FROM z) AS exprimes
                FROM {R(scrutin)} r JOIN z USING (bureau_id) WHERE r.{cle} IS NOT NULL
                GROUP BY 1 ORDER BY voix DESC""", p)
    d["voix"] = d["voix"].astype(float)
    d["pct"] = 100 * d["voix"] / d["exprimes"].astype(float)
    return d


def cles(scrutin, zone=FRANCE, regroupement="Candidat / liste", n=40):
    return resultats(scrutin, zone, regroupement)["qui"].head(n).tolist()


def pct_bureaux(scrutin, zone, regroupement, qui_liste):
    """Le % de chaque « qui » dans chaque bureau de la zone (une colonne par qui)."""
    f, p = filtre(zone)
    cle = REGROUPEMENTS[regroupement]
    marque = ",".join("?" * len(qui_liste))
    d = sql(f"""WITH z AS (SELECT bureau_id, id_brut_miom, code_commune, exprimes, inscrits FROM {P(scrutin)} p
                          WHERE {f} AND exprimes > 0)
                SELECT z.id_brut_miom, z.code_commune, z.exprimes, z.inscrits, r.{cle} AS qui, sum(r.voix) AS voix
                FROM z LEFT JOIN {R(scrutin)} r ON r.bureau_id = z.bureau_id AND r.{cle} IN ({marque})
                GROUP BY z.id_brut_miom, z.code_commune, z.exprimes, z.inscrits, r.{cle}""", p + list(qui_liste))
    t = d.pivot_table(index=["id_brut_miom", "code_commune", "exprimes", "inscrits"], columns="qui", values="voix", aggfunc="sum").fillna(0)
    t = t.reset_index()
    for q in qui_liste:
        t[q] = 100 * t[q].astype(float) / t["exprimes"].astype(float) if q in t else 0.0
    return t


def suivre_nom(texte, zone=FRANCE):
    f, p = filtre(zone)
    motif = f"\\b{texte.upper().strip()}\\b"
    return sql(f"""WITH z AS (SELECT scrutin, bureau_id, exprimes FROM {P_TOUS} p WHERE {f}),
                   e AS (SELECT scrutin, sum(exprimes) exprimes FROM z GROUP BY 1),
                   v AS (SELECT r.scrutin, sum(r.voix) voix, any_value(r.qui) qui FROM {R_TOUS} r JOIN z USING (scrutin, bureau_id)
                         WHERE regexp_matches(upper(r.qui), ?) GROUP BY 1)
                   SELECT s.scrutin, s.type_libelle AS type, CAST(s.date AS DATE) AS date, s.tour, v.qui, 100.0 * v.voix / e.exprimes AS valeur
                   FROM v JOIN e USING (scrutin) JOIN scrutin_tour s USING (scrutin) ORDER BY date""", p + [motif])


# =============================================================================================
# Classements (le Top) et niveaux
# =============================================================================================

NIVEAUX = {   # niveau : (expression de la clé, expression du libellé, jointure supplémentaire)
    "region": ("p.code_region", "any_value(p.libelle_region)", ""),
    "departement": ("p.code_departement", "any_value(p.libelle_departement)", ""),
    "arrondissement": ("p.code_arr", "any_value(p.libelle_arr)", ""),
    "epci": ("ze.code", "any_value(ze.libelle)",
             f"""JOIN modele.zone zc ON zc.niveau_id = {NIVEAU['commune']} AND zc.code = p.code_commune
                 JOIN modele.commune cm ON cm.id = zc.id JOIN modele.zone ze ON ze.id = cm.epci_id"""),
    "circo": ("zt.code", "any_value(zt.libelle) || ' (' || any_value(p.code_departement) || ')'",
              "JOIN modele.bureau b ON b.id = p.bureau_id JOIN modele.zone zt ON zt.id = b.circonscription_id"),
    "canton": ("zt.code", "any_value(zt.libelle) || ' (' || any_value(p.code_departement) || ')'",
               "JOIN modele.bureau b ON b.id = p.bureau_id JOIN modele.zone zt ON zt.id = b.canton_id"),
    "commune": ("p.code_commune", "any_value(p.libelle_commune) || ' (' || p.code_commune || ')'", ""),
    "bureau": ("p.id_brut_miom", "any_value(p.libelle_commune) || ' – ' || any_value(p.code_bv)", ""),
}
NOMS_NIVEAUX = {"region": "Régions", "departement": "Départements", "arrondissement": "Arrondissements", "epci": "Intercommunalités",
                "circo": "Circonscriptions", "canton": "Cantons", "commune": "Communes", "bureau": "Bureaux de vote"}


def par_niveau(scrutin, zone, niveau, mesure, regroupement="Candidat / liste", qui=None, min_inscrits=200):
    """Une valeur par zone d'un niveau (pour le Top et la carte) : un taux, ou le score d'un « qui »."""
    f, p = filtre(zone)
    k, lib, jointure = NIVEAUX[niveau]
    seuil = min_inscrits if niveau != "bureau" else 50
    if mesure in INDICATEURS:
        num, den = INDICATEURS[mesure]
        num = " + ".join(f"p.{x.strip()}" for x in num.split("+"))
        return sql(f"""SELECT {k} AS code, {lib} AS libelle, sum(p.inscrits) inscrits, 100.0 * sum({num}) / nullif(sum(p.{den}), 0) AS valeur
                       FROM {P(scrutin)} p {jointure} WHERE {f} GROUP BY {k} HAVING sum(p.inscrits) >= ?""",
                   p + [seuil])
    cle = REGROUPEMENTS[regroupement]
    return sql(f"""WITH v AS (SELECT bureau_id, sum(voix) voix FROM {R(scrutin)} WHERE {cle} = ? GROUP BY 1)
                   SELECT {k} AS code, {lib} AS libelle, sum(p.inscrits) inscrits, 100.0 * sum(coalesce(v.voix, 0)) / nullif(sum(p.exprimes), 0) AS valeur
                   FROM {P(scrutin)} p {jointure} LEFT JOIN v ON v.bureau_id = p.bureau_id
                   WHERE {f} GROUP BY {k} HAVING sum(p.inscrits) >= ?""", [qui] + p + [seuil])


def gagnants(scrutin, zone, niveau, regroupement="Candidat / liste"):
    """Pour la carte : le 1er de chaque zone d'un niveau, avec son %."""
    f, p = filtre(zone)
    k, lib, jointure = NIVEAUX[niveau]
    cle = REGROUPEMENTS[regroupement]
    return sql(f"""WITH b AS (SELECT p.bureau_id, {k} AS code, p.exprimes FROM {P(scrutin)} p {jointure} WHERE {f}),
                   e AS (SELECT code, sum(exprimes) exprimes FROM b GROUP BY 1),
                   v AS (SELECT b.code, r.{cle} AS qui, sum(r.voix) voix FROM {R(scrutin)} r JOIN b USING (bureau_id)
                         WHERE r.{cle} IS NOT NULL GROUP BY 1, 2)
                   SELECT v.code, arg_max(v.qui, v.voix) AS gagnant, 100.0 * max(v.voix) / any_value(e.exprimes) AS pct
                   FROM v JOIN e USING (code) GROUP BY v.code""", p)


# =============================================================================================
# Contexte local, économie, listes, contours
# =============================================================================================

MESURES_LOCALES = {"Chômage (commune)": "taux_chomage_2022", "Niveau de vie médian (commune)": "niveau_vie_median_2021",
                   "Taux de pauvreté (commune)": "taux_pauvrete_2021", "Diplômés du supérieur (commune)": "part_superieur_2023"}
MESURES_ECO = {"Moral des ménages": "moral_menages", "Chômage (France)": "chomage_bit", "Prix de l'essence (SP95)": "sp95_litre",
               "Prix du gazole": "gazole_litre", "Baril de Brent (€)": "brent_eur", "Euro / dollar": "eur_usd",
               "Franc / dollar": "dollars_pour_1_franc", "Inflation": "inflation_1an", "Big Mac (€)": "big_mac_euros"}
MESURES_ELECTION = ["Score", "Abstention", "Participation", "Blancs", "Nuls", "Blancs + nuls", "Exprimés", "Inscrits"]


@lru_cache(None)
def contexte():
    return sql("SELECT * FROM contexte_communes")


@lru_cache(None)
def economie_mois():
    d = sql("SELECT * FROM economie_mois ORDER BY mois")
    d["mois"] = pd.to_datetime(d["mois"])
    return d


@lru_cache(None)
def veille():
    d = sql("SELECT * FROM veille_scrutins")
    d["date"] = pd.to_datetime(d["date"])
    return d.merge(scrutins()[["scrutin", "type"]], on="scrutin")


def election_tour(scrutin):
    """« 2026_muni_t1 » → (« 2026_muni », 1) : l'élection du modèle et le tour."""
    code, tour = scrutin.rsplit("_t", 1)
    return code, int(tour)


# la zone d'une liste selon son conseil (un même code peut désigner une commune et une circonscription de la métropole de Lyon)
NIVEAUX_CONSEIL = {"municipal": ("commune", "secteur", "section"), "arrondissement": ("secteur", "commune"),
                   "régional": ("region", "section_regionale"), "européen": ("pays",), "métropole": ("circo_metropole",)}


def _niveaux_conseil(conseil):
    return ", ".join(str(NIVEAU[n]) for n in NIVEAUX_CONSEIL.get(conseil, NIVEAU)) or "0"


def listes(scrutin, code_zone, conseil="municipal"):
    """Les listes déposées (modèle : liste, candidature, personne) : panneau, nom, nuance, nombre de noms, tête, femmes."""
    return sql("""SELECT l.numero_panneau, l.libelle libelle_liste, nl.libelle nuance, count(*) noms,
                         max(CASE WHEN c.tete_de_liste THEN p.prenoms || ' ' || p.nom_usage END) tete, sum((p.sexe = 'F')::INT) femmes
                  FROM modele.liste l JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                  JOIN modele.candidature c ON c.liste_id = l.id JOIN modele.personne p ON p.id = c.personne_id
                  JOIN modele.zone z ON z.id = l.zone_id LEFT JOIN modele.nuance nl ON nl.id = l.nuance_id
                  WHERE e.code = ? AND sc.tour = ? AND z.code = ? AND z.niveau_id IN ({n}) AND l.conseil = ?
                  GROUP BY 1, 2, 3 ORDER BY 1""".replace("{n}", _niveaux_conseil(conseil)), [*election_tour(scrutin), code_zone, conseil])


def colistiers(scrutin, code_zone, panneau, conseil="municipal"):
    return sql("""SELECT c.rang ordre, p.sexe, p.nom_usage nom, p.prenoms prenom, CASE WHEN zc.niveau_id = {d} THEN zc.code ELSE '' END section,
                         c.tete_de_liste, c.conseil_communautaire
                  FROM modele.liste l JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id
                  JOIN modele.candidature c ON c.liste_id = l.id JOIN modele.personne p ON p.id = c.personne_id
                  JOIN modele.zone z ON z.id = l.zone_id LEFT JOIN modele.zone zc ON zc.id = c.zone_id
                  WHERE e.code = ? AND sc.tour = ? AND z.code = ? AND z.niveau_id IN ({n}) AND l.conseil = ? AND l.numero_panneau = ?
                  ORDER BY section, ordre""".replace("{n}", _niveaux_conseil(conseil)).replace("{d}", str(NIVEAU["departement"])),
               [*election_tour(scrutin), code_zone, conseil, panneau])


def elections_avec_listes():
    return set(sql("""SELECT DISTINCT e.code || '_t' || sc.tour election FROM modele.liste l
                      JOIN modele.scrutin sc ON sc.id = l.scrutin_id JOIN modele.election e ON e.id = sc.election_id""")["election"])


def contours(niveau, departements=None, codes=None):
    """Les contours d'un niveau (code, nom, forme, coordonnées), dans des départements ou pour des codes donnés.
    (« commune » comprend les arrondissements de Paris, Lyon et Marseille, dessinés comme des communes.)"""
    autres = f", {NIVEAU['arrmun']}" if niveau == "commune" else ""
    choix = f"""SELECT z.code, z.libelle nom, f.libelle type, c.coords FROM contour c JOIN modele.zone z ON z.id = c.zone_id
                 JOIN modele.forme f ON f.id = c.forme_id WHERE z.niveau_id IN ({NIVEAU[niveau]}{autres})"""
    if departements:
        marque = ",".join("?" * len(departements))
        return sql(f"""{choix} AND c.zone_id IN (SELECT a.zone_id FROM zone_dans a JOIN modele.zone d ON d.id = a.ancetre_id
                         WHERE d.niveau_id = {NIVEAU['departement']} AND d.code IN ({marque}))""", list(departements))
    if codes:
        marque = ",".join("?" * len(codes))
        return sql(f"{choix} AND z.code IN ({marque})", list(codes))
    return sql(choix)


def departements_de(zone):
    """Les départements couverts par une zone (pour charger les bons contours)."""
    if zone.niveau == "france":
        return None
    if zone.niveau == "region":
        return departements(zone.code)["code"].tolist()
    if zone.niveau == "departement":
        return [zone.code]
    f, p = filtre(zone)
    return sql(f"SELECT DISTINCT code_departement FROM {P('2022_legi_t1')} p WHERE {f}", p)["code_departement"].tolist()


# =============================================================================================
# Les axes des nuages de points
# =============================================================================================

CLES_POINT = {"Bureau de vote": "p.id_brut_miom", "Commune": "p.code_commune", "Département": "p.code_departement"}


def valeurs_axe(axe, point, zone, type_election=None):
    """La valeur d'un axe pour chaque point. axe = dict(mesure, scrutin, regroupement, qui)."""
    m = axe["mesure"]
    if point == "Mois":
        col = MESURES_ECO.get(m)
        if not col:
            return pd.Series(dtype=float)
        e = economie_mois()
        return e.set_index("mois")[col].dropna()
    if point == "Élection":
        s = scrutins()
        if type_election and type_election != "Toutes les élections":
            s = s[s["type"] == type_election]
        if m in MESURES_ECO:
            v = veille().set_index("scrutin")[MESURES_ECO[m]]
            return v[v.index.isin(s["scrutin"])].dropna()
        if m in INDICATEURS:
            v = serie_taux(zone, m).set_index("scrutin")["valeur"]
            return v[v.index.isin(s["scrutin"])].dropna()
        if m == "Score" and axe.get("qui"):
            f, p = filtre(zone)
            cle = REGROUPEMENTS[axe.get("regroupement", "Candidat / liste")]
            v = sql(f"""WITH z AS (SELECT scrutin, bureau_id, exprimes FROM {P_TOUS} p WHERE {f}),
                           e AS (SELECT scrutin, sum(exprimes) ex FROM z GROUP BY 1)
                        SELECT r.scrutin, 100.0 * sum(r.voix) / any_value(e.ex) valeur FROM {R_TOUS} r JOIN z USING (scrutin, bureau_id)
                        JOIN e USING (scrutin) WHERE r.{cle} = ? GROUP BY 1""", p + [axe["qui"]]).set_index("scrutin")["valeur"]
            return v[v.index.isin(s["scrutin"])]
        return pd.Series(dtype=float)
    # un point = un bureau, une commune ou un département
    k = CLES_POINT[point]
    if m in MESURES_LOCALES:
        ctx = contexte().set_index("code_commune")[MESURES_LOCALES[m]]
        if point == "Commune":
            return ctx.dropna()
        f, p = filtre(zone)
        lien = sql(f"SELECT DISTINCT {k} AS cle, p.code_commune FROM {P('2022_legi_t1')} p WHERE {f}", p)
        lien["v"] = lien["code_commune"].map(ctx)
        return lien.groupby("cle")["v"].mean().dropna()
    scrutin = axe.get("scrutin")
    if not scrutin:
        return pd.Series(dtype=float)
    f, p = filtre(zone)
    if m in INDICATEURS:
        num, den = INDICATEURS[m]
        num = " + ".join(f"p.{x.strip()}" for x in num.split("+"))
        d = sql(f"SELECT {k} cle, 100.0 * sum({num}) / nullif(sum(p.{den}), 0) v FROM {P(scrutin)} p WHERE {f} GROUP BY 1", p)
    elif m == "Inscrits":
        d = sql(f"SELECT {k} cle, sum(p.inscrits) v FROM {P(scrutin)} p WHERE {f} GROUP BY 1", p)
    elif m == "Score" and axe.get("qui"):
        cle = REGROUPEMENTS[axe.get("regroupement", "Candidat / liste")]
        d = sql(f"""WITH v AS (SELECT bureau_id, sum(voix) voix FROM {R(scrutin)} WHERE {cle} = ? GROUP BY 1)
                    SELECT {k} cle, 100.0 * sum(coalesce(v.voix, 0)) / nullif(sum(p.exprimes), 0) v
                    FROM {P(scrutin)} p LEFT JOIN v USING (bureau_id) WHERE {f} GROUP BY 1""",
                [axe["qui"]] + p)
    else:
        return pd.Series(dtype=float)
    return d.set_index("cle")["v"].dropna()


def standardise(s):
    return (s - s.mean()) / s.std() if s.std() else s * 0


# =============================================================================================
# Les idéologies d'une zone (voix → candidature → parti de rattachement → idéologies du parti)
# =============================================================================================

ELECTIONS_IDEOLOGIES = ("2017_legi_t1", "2022_legi_t1", "2024_legi_t1")    # (rattachements des candidats connus)


def ideologies_zone(scrutin, zone=FRANCE):
    """La part des exprimés qui a voté pour un candidat dont le parti porte chaque idéologie (une voix compte pour toutes
    les idéologies de son parti ; un parti sans idéologie connue — une coalition — prend celles de ses membres)."""
    f, p = filtre(zone)
    return sql(f"""
        WITH z AS (SELECT bureau_id, exprimes FROM {P(scrutin)} p WHERE {f}),
        ideo AS (SELECT parti_id, ideologie_id FROM modele.parti_ideologie
                 UNION SELECT m.coalition_id, pi.ideologie_id FROM modele.parti_membre m
                       JOIN modele.parti_ideologie pi ON pi.parti_id = m.parti_id
                 WHERE m.coalition_id NOT IN (SELECT parti_id FROM modele.parti_ideologie)),
        v AS (SELECT r.candidature_id, sum(r.voix) voix FROM {R(scrutin)} r JOIN z USING (bureau_id)
              WHERE r.candidature_id IS NOT NULL GROUP BY 1)
        SELECT i.libelle ideologie, sum(v.voix) voix, 100.0 * sum(v.voix) / (SELECT sum(exprimes) FROM z) pct,
               count(DISTINCT inv.parti_id) partis
        FROM v JOIN modele.investiture inv USING (candidature_id) JOIN ideo USING (parti_id)
        JOIN modele.ideologie i ON i.id = ideo.ideologie_id
        GROUP BY 1 ORDER BY voix DESC""", p)
