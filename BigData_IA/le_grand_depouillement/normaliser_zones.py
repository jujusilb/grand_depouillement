"""
normaliser_zones.py — Les territoires du schéma v2 : une seule table zone (« on est tous du règne animal »).

    py normaliser_zones.py --essai     (calcule tout, dit ce qui ne se raccroche pas, n'écrit rien)
    py normaliser_zones.py             (l'appli fermée ; MariaDB de XAMPP démarré)

Lancé par normaliser_references.py (dernière étape de la fabrication), relançable : ce qui est déjà converti est laissé.

    niveau (id, code, libelle, niveau_parent_id)        pays, région, département… bureau de vote
    zone (id, niveau_id = la discrimination, code, libelle, parent_id, superficie, date_debut, date_fin)
    commune (id → zone, epci_id → zone)                  héritage par jointure : ce qui n'appartient qu'aux communes
    bureau (id → zone, canton_id → zone, circonscription_id → zone)
Les codes gardent la forme qu'utilise l'appli (codes du ministère pour l'outre-mer : ZA = Guadeloupe, ZZ = Français
établis hors de France) ; le code d'un bureau est l'id_brut_miom (« 43157_0001 »). Un même code peut désigner deux
territoires à deux époques (la 1re circonscription de l'Ain de 1958 n'est pas celle de 2012) : zone unique par
(niveau, code, date_debut).

Remplacé par zone_id : mandat, candidature, liste, nomination (zone_niveau_id + zone_code, et pour candidature
zone_libelle, code_departement, code_region) ; fonction.zone_niveau_id → niveau_id. Dans la base de l'appli :
contours → contour (zone_id, precision_m, forme_id), populations → population (zone_id, annee, population) ; les
tables geo_* disparaissent. Tout est sauvegardé dans PROJET/DECHET avant.
"""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import pandas as pd

from outils_mariadb import charger, cle_etrangere, mysql, norm, requete, sauvegarder

ICI = Path(__file__).resolve().parent
BASE = ICI / "data" / "depouillement.duckdb"
AVANT = ICI.parent.parent / "DECHET" / "depouillement_avant_modele.duckdb"     # (les fichiers RNE d'origine)
DECHET = ICI.parent.parent / "DECHET"
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
MARIADB = f"host=127.0.0.1 user=root port={os.environ.get('GD_MARIADB_PORT', '3306')} database=grand_depouillement"

NIVEAUX = [  # id, code (pour l'appli), libellé, niveau parent
    (1, "pays", "pays", None), (2, "region", "région", 1), (3, "departement", "département", 2),
    (4, "arrondissement", "arrondissement", 3), (5, "circo", "circonscription législative", 3), (6, "canton", "canton", 3),
    (7, "epci", "intercommunalité", 3), (8, "commune", "commune", 4), (9, "arrmun", "arrondissement municipal", 8),
    (10, "secteur", "secteur électoral (Paris, Lyon, Marseille)", 8), (11, "section", "section électorale de commune", 8),
    (12, "bureau", "bureau de vote", 8), (13, "section_regionale", "section régionale (Martinique, Guyane)", 2),
    (14, "circo_metropole", "circonscription métropolitaine (Lyon)", 7),
]
N = {code: i for i, code, _, _ in NIVEAUX}
# les anciens niveaux (zone_niveau) : 1 commune, 2 secteur, 3 intercommunalité, 4 canton, 5 circonscription,
# 6 département, 7 région, 8 pays, 9 Europe
ANCIEN = {1: N["commune"], 2: N["secteur"], 3: N["epci"], 4: N["canton"], 5: N["circo"], 6: N["departement"],
          7: N["region"], 8: N["pays"], 9: N["pays"]}
# l'outre-mer : code de l'Insee → code du ministère (celui des tables de l'appli)
OUTRE_MER = {"971": "ZA", "972": "ZB", "973": "ZC", "974": "ZD", "975": "ZS", "976": "ZM", "977": "ZX", "978": "ZX",
             "985": "ZM", "986": "ZW", "987": "ZP", "988": "ZN", "099": "ZZ", "99": "ZZ",
             "ZT": "ZX", "ZY": "ZX"}      # (sénatoriales : ZT Saint-Martin, ZY Saint-Barthélemy, réunis dans ZX)
# les découpages des circonscriptions législatives (1986 : proportionnelle par département)
# les noms de département écrits autrement que dans la table (sénateurs, nominations)
AUTRES_NOMS = {"RHONEHORSMETROPOLEDELYON": "69", "COLLECTIVITEEUROPEENNEDALSACE": "6AE", "SAINTBARTHELEMY": "ZX", "SAINTMARTIN": "ZX", "ILESWALLISETFUTUNA": "ZW", "MARTINIQUE": "ZB", "GUYANE": "ZC"}
DECOUPAGES = [("1958-11-23", "1986-03-15"), ("1988-06-05", "2012-06-09"), ("2012-06-10", None)]


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def dep(code):
    """« 971 » → « ZA », « 1 » → « 01 », « 2A » → « 2A »."""
    code = str(code).strip()
    return OUTRE_MER.get(code, code.zfill(2) if code.isdigit() else code)


def ordinal(n):
    return f"{n}{'ère' if n == 1 else 'ème'} circonscription"


class Zones:
    """La table zone en construction : numéros gardés d'une fois sur l'autre, clé (niveau, code, date_debut)."""

    def __init__(self, deja):
        self.lignes = {}                  # clé → [id, niveau, code, libelle, parent_id, date_debut, date_fin]
        for r in deja.itertuples():
            self.lignes[(int(r.niveau_id), r.code, r.date_debut)] = [int(r.id), int(r.niveau_id), r.code, r.libelle,
                                                                     None if r.parent_id is None else int(r.parent_id),
                                                                     r.date_debut, r.date_fin]
        self.anciens = {v[0] for v in self.lignes.values()}
        self.suivant = max(self.anciens, default=0) + 1

    def ajouter(self, niveau, code, libelle, parent=None, debut=None, fin=None):
        k = (niveau, code, debut)
        if k not in self.lignes:
            self.lignes[k] = [self.suivant, niveau, code, libelle, parent, debut, fin]
            self.suivant += 1
        elif self.lignes[k][4] is None and parent is not None:
            self.lignes[k][4] = parent
        return self.lignes[k][0]

    def id(self, niveau, code, debut=None):
        v = self.lignes.get((niveau, code, debut))
        return v[0] if v else None

    def table(self):
        return pd.DataFrame(list(self.lignes.values()),
                            columns=["id", "niveau_id", "code", "libelle", "parent_id", "date_debut", "date_fin"])


def lire(sql, colonnes):
    r = requete(sql)
    return r if len(r.columns) == len(colonnes) else pd.DataFrame(columns=colonnes)


def construire(con, essai):
    """La table zone complète (et ce qu'il faut pour commune et bureau) ; renvoie (zones, communes, bureaux)."""
    deja = lire("SELECT id, niveau_id, code, libelle, parent_id, date_debut, date_fin FROM zone",
                ["id", "niveau_id", "code", "libelle", "parent_id", "date_debut", "date_fin"]) \
        if len(requete("SHOW TABLES LIKE 'zone'")) else pd.DataFrame(columns=["id"])
    z = Zones(deja if len(deja) else pd.DataFrame(columns=["id", "niveau_id", "code", "libelle", "parent_id",
                                                           "date_debut", "date_fin"]))
    q = lambda s: con.execute(s).fetchall()
    geo = bool(q("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'geo_commune'")[0][0])
    communes, bureaux = {}, {}                  # zone_id → epci (code) ; zone_id → (canton, circo) en codes
    fr = z.ajouter(N["pays"], "FR", "France")
    if geo:
        for code, lib in q("SELECT code, libelle FROM geo_region"):
            z.ajouter(N["region"], code, lib, fr)
        for code, lib, reg in q("SELECT code, libelle, region FROM geo_departement"):
            z.ajouter(N["departement"], code, lib, z.id(N["region"], reg))
        for code, lib, d in q("SELECT code, libelle, departement FROM geo_arrondissement"):
            z.ajouter(N["arrondissement"], code, lib, z.id(N["departement"], d))
        for code, lib, d in q("SELECT code, libelle, departement FROM geo_circo"):
            z.ajouter(N["circo"], code, lib, z.id(N["departement"], d), DECOUPAGES[2][0])
        for code, lib, d in q("SELECT code, libelle, departement FROM geo_canton"):
            z.ajouter(N["canton"], code, lib, z.id(N["departement"], d), "2015-03-22")
        for code, lib in q("SELECT code, libelle FROM geo_epci"):
            z.ajouter(N["epci"], code, lib)
        # la Corse d'avant 1976, un seul département (préfets)
        z.ajouter(N["departement"], "20", "Corse", z.id(N["region"], "94"), None, "1975-12-31")
        z.ajouter(N["departement"], "6AE", "Collectivité européenne d'Alsace", z.id(N["region"], "44"))
        # (la métropole de Lyon exerce aussi les compétences du département depuis 2015 : sa zone est dans la région,
        #  comme celle d'un département — elle sert de section aux régionales)
        z.ajouter(N["epci"], "200046977", "Métropole de Lyon", z.id(N["region"], "84"))
        for code, lib, d, arr, epci in q("SELECT code, libelle, departement, arrondissement, epci FROM geo_commune"):
            i = z.ajouter(N["commune"], code, lib, z.id(N["arrondissement"], arr) or z.id(N["departement"], d))
            communes[i] = epci
        for code, lib, com in q("SELECT code, libelle, commune FROM geo_arrmun"):
            z.ajouter(N["arrmun"], code, lib, z.id(N["commune"], com))
        for com, bv, nom, circo, canton, arrmun, miom in q(
                "SELECT commune, code_bv, nom, circo, canton, arrmun, id_brut_miom FROM geo_bureau"):
            i = z.ajouter(N["bureau"], miom, nom or f"bureau {bv}", z.id(N["arrmun"], arrmun) or z.id(N["commune"], com))
            bureaux[i] = (canton, circo)
        # les communes et les bureaux des scrutins passés (fusionnés depuis) : d'après participation
        for com, lib, d in q("""SELECT code_commune, any_value(libelle_commune), any_value(code_departement)
                                FROM participation WHERE code_commune IS NOT NULL GROUP BY 1"""):
            if z.id(N["commune"], com) is None:
                i = z.ajouter(N["commune"], com, lib, z.id(N["departement"], dep(d)))
                communes[i] = None
        for miom, com, bv in q("""SELECT id_brut_miom, any_value(code_commune), any_value(code_bv) FROM participation
                                  WHERE id_brut_miom IS NOT NULL GROUP BY 1"""):
            if z.id(N["bureau"], miom) is None:
                i = z.ajouter(N["bureau"], miom, f"bureau {bv}" if bv else miom, z.id(N["commune"], com))
                bureaux[i] = (None, None)
    return z, communes, bureaux


# ------------------------------------------------------------------------------------------------------------------
# Les codes du modèle → une zone
# ------------------------------------------------------------------------------------------------------------------
class Raccord:
    """Retrouve (ou crée, quand le territoire a disparu) la zone d'un ancien (zone_niveau_id, zone_code)."""

    def __init__(self, z, noms_communes, noms_epci):
        self.z, self.noms_communes, self.noms_epci = z, noms_communes, noms_epci
        self.manques = {}
        self.par_nom = {}                             # (niveau, département, NOM) → id
        for (niv, code, debut), v in z.lignes.items():
            if niv in (N["canton"], N["commune"], N["circo"]) and v[4] is not None and (niv != N["circo"] or debut == DECOUPAGES[2][0]):
                self.par_nom.setdefault((niv, self.departement(v[0]), norm(v[3])), v[0])
        for v in z.lignes.values():
            if v[1] == N["departement"]:
                self.par_nom[(N["departement"], None, norm(v[3]))] = v[0]
        for nom, d in AUTRES_NOMS.items():
            self.par_nom.setdefault((N["departement"], None, nom), z.id(N["departement"], d))

    def departement(self, i):
        """Le code du département d'une zone (en remontant les parents)."""
        par_id = getattr(self, "_par_id", None)
        if par_id is None:
            par_id = self._par_id = {v[0]: v for v in self.z.lignes.values()}
        v = par_id.get(i)
        while v is not None and v[1] != N["departement"]:
            v = par_id.get(v[4])
        return v[2] if v else None

    def manque(self, quoi, exemple):
        self.manques.setdefault(quoi, [0, exemple])[0] += 1
        return None

    def commune(self, code, libelle=None):
        i = self.z.id(N["commune"], code)
        if i is None:
            d = dep(code[:3] if code[:2] in ("97", "98") else code[:2])
            lib = libelle or self.noms_communes.get(code) or code
            i = self.z.ajouter(N["commune"], code, lib, self.z.id(N["departement"], d))
        return i

    def section_departementale(self, code):
        """La section départementale d'une liste régionale : « 1 », « 69D » (Rhône hors métropole), « 69M » (métropole de
        Lyon), « 67-68 » (Collectivité européenne d'Alsace)."""
        if code == "69M":
            return self.z.id(N["epci"], "200046977")
        d = {"69D": "69", "67-68": "6AE"}.get(code, dep(code))
        return self.z.id(N["departement"], d) or self.manque("section départementale", code)

    def ancienne_commune(self, d, libelle):
        """Une commune fusionnée depuis, retrouvée par son nom dans les fichiers RNE d'origine."""
        if not hasattr(self, "_rne"):
            self._rne = {(dep(c[:3] if c[:2] in ("97", "98") else c[:2]), norm(n)): c for c, n in self.noms_communes.items()}
        code = self._rne.get((d, norm(libelle)))
        return self.commune(code, libelle) if code else None

    def secteur(self, commune, numero, libelle=None):
        code = f"{commune}SR{int(numero):02d}"
        return self.z.ajouter(N["secteur"], code, libelle or code, self.commune(commune))

    def circo(self, code, debut):
        d, n = code.split("-")
        d, n = dep(d), int(n)
        epoque = next((a for a, b in DECOUPAGES if debut is None or (debut >= a and (b is None or debut <= b))), None)
        if epoque is None:                          # (1986-1988 : la proportionnelle, pas de circonscription)
            return self.z.id(N["departement"], d)
        c = f"{d}-{n:02d}"
        i = self.z.id(N["circo"], c, epoque)
        if i is None:
            fin = dict(DECOUPAGES)[epoque]
            i = self.z.ajouter(N["circo"], c, ordinal(n), self.z.id(N["departement"], d), epoque, fin)
        return i

    def canton(self, code):
        d, c = code.split("-")
        d = "67" if d == "6AE" and c.startswith("67") else "68" if d == "6AE" else dep(d)
        num = c[-2:]
        return self.z.id(N["canton"], f"{d}-{num}", "2015-03-22") or self.manque("canton", code)

    def par_libelle(self, niveau, d, libelle):
        return self.par_nom.get((niveau, d, norm(libelle)))

    def zone(self, niveau, code, libelle=None, election=None, debut=None):
        """L'ancien couple (zone_niveau_id, zone_code) + ce qu'on sait d'autre → zone_id (None : on ne sait pas)."""
        z = self.z
        if niveau == 8 or code == "FE" or (code is None and election and election.endswith("_euro")):   # (circonscription unique)
            return z.id(N["pays"], "FR")
        if code is None or code == "-":
            if niveau == 6 and libelle and " - Section" in libelle:     # (Martinique, Guyane : sections régionales)
                reg = {"Martinique": "02", "Guyane": "03"}[libelle.split(" - ")[0]]
                return z.ajouter(N["section_regionale"], f"{reg}|{libelle.split(' - ', 1)[1]}", libelle, z.id(N["region"], reg))
            if niveau == 6 and libelle == "Métropole de Lyon":   # (section des régionales : la métropole)
                return z.id(N["epci"], "200046977")
            if niveau == 6 and libelle:                         # (sections départementales des régionales)
                return self.par_libelle(N["departement"], None, libelle) or self.manque("département (nom)", libelle)
            return None
        m = re.fullmatch(r"(\d{5})(SR|SN)(\d{2})", code)
        if m:
            if m[2] == "SR":
                return self.secteur(m[1], m[3], libelle)
            return z.ajouter(N["section"], code, libelle or code, self.commune(m[1]))
        if niveau == 1:
            return self.commune(code, libelle)
        if niveau == 2:                                         # « 75056|Paris 9Eme Secteur »
            com, lib = code.split("|")
            return self.secteur(com, re.search(r"(\d+)", lib)[1])
        if niveau == 3:
            if election == "2026_muni" and len(code) == 5:     # (circonscriptions de la métropole de Lyon)
                return z.ajouter(N["circo_metropole"], code, libelle or code, z.id(N["epci"], "200046977"))
            return z.id(N["epci"], code) or z.ajouter(N["epci"], code, self.noms_epci.get(code, code))
        if niveau == 4:
            return self.canton(code)
        if niveau == 5:
            return self.circo(code, debut)
        if niveau == 6:
            if "|" not in code:
                return z.id(N["departement"], dep(code)) or self.par_libelle(N["departement"], None, code) \
                    or self.manque("département", code)
            d, lib = code.split("|")
            d = dep(d)
            if not lib:                                         # (sénatoriales : le département)
                return z.id(N["departement"], d)
            m = re.fullmatch(r"(\d+)(?:ère|ème|ere|eme) circonscription", lib)
            if m:
                return self.circo(f"{d}-{m[1]}", debut)
            m = re.fullmatch(r"(Paris|Lyon|Marseille) (?:Secteur )?(\d+)(?:er|ème|eme|e)?(?: [sS]ecteur)?", lib)
            if m:
                return self.secteur({"Paris": "75056", "Lyon": "69123", "Marseille": "13055"}[m[1]], m[2])
            if election and election.endswith("dpmt"):
                return self.par_libelle(N["canton"], d, lib) or self.manque("canton (nom)", code)
            if norm(lib) == norm(self.z.lignes.get((N["departement"], d, None), [0] * 4)[3]):
                return z.id(N["departement"], d)          # (« ZS|Saint-Pierre-et-Miquelon » : le territoire entier)
            return self.par_libelle(N["commune"], d, lib) or self.par_libelle(N["canton"], d, lib) \
                or self.ancienne_commune(d, lib) or self.manque("commune (nom)", code)
        if niveau == 7 and libelle and libelle.startswith("DEP:"):  # (section départementale des régionales)
            return self.section_departementale(libelle[4:])
        if niveau == 7:
            reg = code.zfill(2)
            if libelle and " - Section" in libelle:
                return z.ajouter(N["section_regionale"], f"{reg}|{libelle.split(' - ', 1)[1]}", libelle, z.id(N["region"], reg))
            return z.id(N["region"], reg) or self.manque("région", code)
        return self.manque(f"niveau {niveau}", code)


def raccorder(r, df, colonnes):
    """df avec une colonne zone_id (une recherche par combinaison distincte)."""
    cles = df[colonnes].drop_duplicates()
    cles["zone_id"] = [r.zone(*(None if pd.isna(v) else v for v in ligne)) for ligne in cles.itertuples(index=False)]
    return cles


CLES = {  # table → les colonnes de la carte (niveau, code, libelle, election, debut) en SQL
    "mandat": ("x.zone_niveau_id", "x.zone_code", "NULL", "e.code",
               "CASE WHEN x.zone_niveau_id = 5 THEN coalesce(strftime(x.date_debut, '%Y-%m-%d'), '2024-07-07') END"),
    # (régionales : la section départementale du candidat d'une liste est dans code_departement → « DEP:01 »)
    "candidature": ("x.zone_niveau_id", "x.zone_code",
                    "CASE WHEN x.zone_niveau_id = 7 AND x.code_departement IS NOT NULL AND coalesce(x.zone_libelle, '') "
                    "NOT LIKE '% - Section%' THEN 'DEP:' || x.code_departement ELSE x.zone_libelle END",
                    "e.code", "strftime(e.date_t1, '%Y-%m-%d')"),
    "liste": ("x.zone_niveau_id", "x.zone_code", "NULL", "e.code", "NULL"),
    "nomination": ("x.zone_niveau_id", "x.zone_code", "NULL", "NULL", "NULL"),
}
TEXTES = {"candidature": ["zone_libelle", "code_departement", "code_region"]}      # (se déduisent de la zone)
APRES = {"mandat": "fonction_id", "candidature": "personne_id", "liste": "election_id", "nomination": "poste_id"}


def colonnes(table):
    return set(requete(f"SHOW COLUMNS FROM `{table}`").Field) if len(requete(f"SHOW TABLES LIKE '{table}'")) else set()


def contrainte(nom):
    return bool(len(requete(f"""SELECT constraint_name FROM information_schema.table_constraints
                                WHERE table_schema = DATABASE() AND constraint_name = '{nom}'""")))


def fins_communes():
    """La date de fin des communes disparues (fusionnées…), d'après le code officiel géographique de l'Insee : une commune
    absente du COG 2026 a cessé d'être une commune la veille de son dernier mouvement (fichier des mouvements)."""
    brut = ICI.parent.parent / "BRUT"
    if not (brut / "v_mvt_commune_2026.csv").exists():
        return
    c = duckdb.connect()
    fins = c.execute(f"""SELECT COM_AV code, strftime(max(DATE_EFF::DATE) - 1, '%Y-%m-%d') fin
        FROM read_csv('{(brut / 'v_mvt_commune_2026.csv').as_posix()}', all_varchar = true)
        WHERE TYPECOM_AV = 'COM' AND (TYPECOM_AP <> 'COM' OR COM_AP <> COM_AV)
          AND COM_AV NOT IN (SELECT COM FROM read_csv('{(brut / 'v_commune_2026.csv').as_posix()}', all_varchar = true)
                             WHERE TYPECOM = 'COM')
        GROUP BY 1""").df()
    c.close()
    mysql(f"DROP TABLE IF EXISTS tmp_fin; CREATE TABLE tmp_fin (code VARCHAR(10) PRIMARY KEY, fin DATE) {T}")
    charger("tmp_fin", fins)
    mysql(f"""UPDATE zone z JOIN tmp_fin f ON f.code = z.code SET z.date_fin = f.fin
              WHERE z.niveau_id = {N['commune']} AND z.date_fin IS NULL; DROP TABLE tmp_fin""")
    n = requete(f"SELECT count(*) n, sum(date_fin IS NOT NULL) fin FROM zone WHERE niveau_id = {N['commune']}")
    etape(f"communes : {n.fin[0]} disparues sur {n.n[0]} (date de fin d'après le COG de l'Insee)")


def tables_filles(z, communes, bureaux):
    """commune et bureau : une ligne pour CHAQUE zone de ce niveau (les disparues comprises), avec ce que le découpage
    d'aujourd'hui (tables geo_* de preparer_donnees.py) dit d'elle : l'intercommunalité, le canton, la circonscription.
    Sans ce découpage (déjà converti), on n'y touche pas."""
    if not communes:
        return
    tz = z.table()
    c = tz.loc[tz.niveau_id == N["commune"], ["id"]]
    c["epci_id"] = [z.id(N["epci"], communes[i]) if communes.get(i) else None for i in c.id]
    mysql("DELETE FROM commune")
    charger("commune", c)
    etape(f"commune : {len(c)} ({c.epci_id.notna().sum()} dans une intercommunalité)")
    b = tz.loc[tz.niveau_id == N["bureau"], ["id"]]
    ca_ci = [bureaux.get(i, (None, None)) for i in b.id]
    b["canton_id"] = [z.id(N["canton"], ca, "2015-03-22") if ca else None for ca, _ in ca_ci]
    b["circonscription_id"] = [z.id(N["circo"], ci, DECOUPAGES[2][0]) if ci else None for _, ci in ca_ci]
    mysql("DELETE FROM bureau")
    charger("bureau", b)
    etape(f"bureau : {len(b)} ({b.circonscription_id.notna().sum()} du découpage d'aujourd'hui)")


def zones(con, essai=False):
    t0 = time.time()
    from normaliser_references import recopier, sauvegarder_duckdb      # (ici : normaliser_references nous appelle)
    z, communes, bureaux = construire(con, essai)
    etape(f"zones des tables de l'appli : {len(z.lignes)}")
    a_convertir = [t for t in CLES if "zone_code" in colonnes(t)]
    m = duckdb.connect()
    m.execute("LOAD mysql")
    m.execute(f"ATTACH '{MARIADB}' AS m (TYPE mysql, READ_ONLY)")
    cartes = {}
    if a_convertir:
        # les noms des territoires disparus : les fichiers RNE d'origine
        a = duckdb.connect(str(AVANT), read_only=True)
        noms_communes = dict(a.execute("SELECT code_commune, any_value(commune) FROM rne_municipaux GROUP BY 1").fetchall())
        noms_epci = dict(a.execute("SELECT siren, any_value(epci) FROM rne_communautaires GROUP BY 1").fetchall())
        a.close()
        r = Raccord(z, noms_communes, noms_epci)
        for t in a_convertir:
            n, k, l, e, d = CLES[t]
            jointure = "LEFT JOIN m.election e ON e.id = x.election_id" if t != "nomination" else ""
            cartes[t] = raccorder(r, m.execute(f"""SELECT DISTINCT {n} niveau, {k} code, {l} libelle, {e} election, {d} debut
                                                  FROM m.{t} x {jointure}""").df(), ["niveau", "code", "libelle", "election", "debut"])
            sans = cartes[t][cartes[t].zone_id.isna() & cartes[t].code.notna() & (cartes[t].code != "-")]
            etape(f"{t:12s} {len(cartes[t]):7d} combinaisons, {len(sans)} sans zone")
            if len(sans):
                print(sans.head(8).to_string())
        for quoi, (n, ex) in r.manques.items():
            print(f"   pas trouvé : {quoi:20s} {n:5d}  ex. {ex}")
    etape(f"zones en tout : {len(z.lignes)} ({len(z.lignes) - len(z.anciens)} nouvelles)")
    if essai:
        return

    # 1. niveau, zone, commune, bureau dans MariaDB ------------------------------------------------------------------
    if a_convertir:
        etape("sauvegarde : " + sauvegarder(DECHET, "avant_zones", a_convertir + ["fonction", "zone_niveau", "personne"]).name)
    mysql(f"""CREATE TABLE IF NOT EXISTS niveau (id INT NOT NULL PRIMARY KEY, code VARCHAR(20) NOT NULL, libelle VARCHAR(60) NOT NULL,
                niveau_parent_id INT NULL, UNIQUE KEY ix_niveau_code (code),
                CONSTRAINT fk_niveau_niveau_parent_id FOREIGN KEY (niveau_parent_id) REFERENCES niveau (id)) {T};
              CREATE TABLE IF NOT EXISTS zone (id INT NOT NULL PRIMARY KEY, niveau_id INT NOT NULL, code VARCHAR(80) NOT NULL,
                libelle VARCHAR(120) NOT NULL, parent_id INT NULL, superficie DOUBLE NULL, date_debut DATE NULL, date_fin DATE NULL,
                UNIQUE KEY ix_zone_code (niveau_id, code, date_debut), KEY ix_zone_parent (parent_id), KEY ix_zone_libelle (libelle),
                CONSTRAINT fk_zone_niveau_id FOREIGN KEY (niveau_id) REFERENCES niveau (id)) {T};
              CREATE TABLE IF NOT EXISTS commune (id INT NOT NULL PRIMARY KEY, epci_id INT NULL, KEY ix_commune_epci (epci_id),
                CONSTRAINT fk_commune_id FOREIGN KEY (id) REFERENCES zone (id),
                CONSTRAINT fk_commune_epci_id FOREIGN KEY (epci_id) REFERENCES zone (id)) {T};
              CREATE TABLE IF NOT EXISTS bureau (id INT NOT NULL PRIMARY KEY, canton_id INT NULL, circonscription_id INT NULL,
                KEY ix_bureau_canton (canton_id), KEY ix_bureau_circo (circonscription_id),
                CONSTRAINT fk_bureau_id FOREIGN KEY (id) REFERENCES zone (id),
                CONSTRAINT fk_bureau_canton_id FOREIGN KEY (canton_id) REFERENCES zone (id),
                CONSTRAINT fk_bureau_circonscription_id FOREIGN KEY (circonscription_id) REFERENCES zone (id)) {T};
              CREATE TABLE IF NOT EXISTS forme (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(20) NOT NULL) {T};
              INSERT IGNORE INTO forme VALUES (1, 'Polygon'), (2, 'MultiPolygon');
              INSERT IGNORE INTO niveau (id, code, libelle) VALUES """
          + ", ".join(f"({i}, '{c}', '{l.replace(chr(39), chr(39) * 2)}')" for i, c, l, _ in NIVEAUX) + ";"
          + "".join(f"UPDATE niveau SET niveau_parent_id = {p} WHERE id = {i};" for i, _, _, p in NIVEAUX if p))
    tz = z.table()
    nouvelles = tz[~tz.id.isin(z.anciens)]
    if len(nouvelles):
        mysql("SET foreign_key_checks = 0;")
        charger("zone", nouvelles)
    if not contrainte("fk_zone_parent_id"):
        cle_etrangere("zone", "parent_id", "zone")
    etape(f"zone : {len(nouvelles)} zones ajoutées ({len(tz)} en tout)")
    fins_communes()
    tables_filles(z, communes, bureaux)

    # 2. mandat, candidature, liste, nomination : zone_id à la place de zone_niveau_id + zone_code ------------------
    for t in a_convertir:
        m.register("carte", cartes[t])
        n, k, l, e, d = CLES[t]
        jointure = "LEFT JOIN m.election e ON e.id = x.election_id" if t != "nomination" else ""
        with tempfile.TemporaryDirectory() as dossier:
            f = Path(dossier) / "ids.tsv"
            m.execute(f"""COPY (SELECT x.id, c.zone_id::BIGINT FROM m.{t} x {jointure}
                              JOIN carte c ON c.niveau IS NOT DISTINCT FROM {n} AND c.code IS NOT DISTINCT FROM {k}
                               AND c.libelle IS NOT DISTINCT FROM {l} AND c.election IS NOT DISTINCT FROM {e}
                               AND c.debut IS NOT DISTINCT FROM {d} WHERE c.zone_id IS NOT NULL)
                          TO '{f.as_posix()}' (FORMAT csv, DELIMITER '\t', HEADER false)""")
            m.unregister("carte")
            mysql(f"""DROP TABLE IF EXISTS tmp_zone; CREATE TABLE tmp_zone (id BIGINT PRIMARY KEY, zone_id INT) {T};
                      LOAD DATA LOCAL INFILE '{f.as_posix()}' INTO TABLE tmp_zone FIELDS TERMINATED BY '\\t' (id, zone_id)""")
        enlever = ["zone_niveau_id", "zone_code"] + TEXTES.get(t, [])
        mysql(f"""ALTER TABLE {t} DROP FOREIGN KEY fk_{t}_zone_niveau_id;
                  ALTER TABLE {t} ADD COLUMN zone_id INT NULL AFTER {APRES[t]};
                  UPDATE {t} x JOIN tmp_zone z ON z.id = x.id SET x.zone_id = z.zone_id;
                  ALTER TABLE {t} {', '.join(f'DROP COLUMN {c}' for c in enlever)}, ADD INDEX ix_{t}_zone (zone_id);
                  DROP TABLE tmp_zone""")
        cle_etrangere(t, "zone_id", "zone")
        etape(f"{t} : zone_id ({requete(f'SELECT count(*) n FROM {t} WHERE zone_id IS NULL').n[0]} lignes sans zone)")

    # fonction : le niveau de ses mandats ; personne : la commune de naissance devient une zone
    if "zone_niveau_id" in colonnes("fonction"):
        mysql("ALTER TABLE fonction ADD COLUMN niveau_id INT NULL AFTER label; "
              + " ".join(f"UPDATE fonction SET niveau_id = {nouveau} WHERE zone_niveau_id = {ancien};" for ancien, nouveau in ANCIEN.items())
              + " ALTER TABLE fonction DROP COLUMN zone_niveau_id;")
        cle_etrangere("fonction", "niveau_id", "niveau")
    if "commune_naissance_id" in colonnes("personne"):
        g = requete("SELECT id, code FROM geo_commune")
        g["zone_id"] = [z.id(N["commune"], c) for c in g.code]
        mysql(f"DROP TABLE IF EXISTS tmp_zone; CREATE TABLE tmp_zone (id BIGINT PRIMARY KEY, zone_id INT) {T}")
        charger("tmp_zone", g[["id", "zone_id"]])
        mysql("""ALTER TABLE personne DROP FOREIGN KEY fk_personne_commune_naissance_id;
                 ALTER TABLE personne ADD COLUMN lieu_naissance_id INT NULL AFTER lieu_naissance;
                 UPDATE personne p JOIN tmp_zone z ON z.id = p.commune_naissance_id SET p.lieu_naissance_id = z.zone_id;
                 ALTER TABLE personne DROP COLUMN commune_naissance_id, ADD INDEX ix_personne_lieu_naissance (lieu_naissance_id);
                 DROP TABLE tmp_zone""")
        cle_etrangere("personne", "lieu_naissance_id", "zone")
        etape("personne : commune_naissance_id → lieu_naissance_id (zone)")
    if len(requete("SHOW TABLES LIKE 'zone_niveau'")):
        mysql("SET foreign_key_checks = 0; DROP TABLE zone_niveau")
        etape("zone_niveau retirée (remplacée par niveau)")

    # 3. la base de l'appli : contours → contour, populations → population, plus de geo_* ---------------------------
    q = lambda s: con.execute(s).fetchall()
    existe = lambda t: q(f"SELECT count(*) FROM duckdb_tables() WHERE table_name = '{t}'")[0][0]
    con.register("zones_df", tz[["id", "niveau_id", "code"]])
    if existe("contours"):
        sauvegarder_duckdb(con, "contours", "contours_avant_zone")
        niveaux = ", ".join(f"('{c}', {N[c]})" for c in ("region", "departement", "commune", "bureau"))
        con.execute(f"""CREATE OR REPLACE TABLE contour AS
            SELECT row_number() OVER (ORDER BY z.id) id, z.id::INTEGER zone_id,
                   CASE WHEN c.niveau IN ('region', 'departement') THEN 100 ELSE 10 END precision_m,
                   CASE c.type WHEN 'Polygon' THEN 1 ELSE 2 END forme_id, c.coords
            FROM contours c JOIN (VALUES {niveaux}) n(niveau, niveau_id) ON n.niveau = c.niveau
            JOIN zones_df z ON z.code = c.code AND (c.niveau = 'commune' AND z.niveau_id = {N['arrmun']}
                 OR z.niveau_id = n.niveau_id AND NOT (c.niveau = 'commune'
                    AND EXISTS (SELECT 1 FROM zones_df x WHERE x.niveau_id = {N['arrmun']} AND x.code = c.code)))""")
        # (les arrondissements de Paris, Lyon et Marseille sont dans le fichier des communes : ils vont à leur zone
        #  d'arrondissement municipal, même quand d'anciens scrutins les ont aussi comptés comme communes)
        perdus = q("SELECT (SELECT count(*) FROM contours) - (SELECT count(*) FROM contour)")[0][0]
        con.execute("DROP TABLE contours")
        etape(f"contour : {q('SELECT count(*) FROM contour')[0][0]} ({perdus} sans zone)")
        recopier(con, ["contour"], [("contour", "zone_id", "zone"), ("contour", "forme_id", "forme")])
    if existe("populations"):
        sauvegarder_duckdb(con, "populations", "populations_avant_zone")
        con.execute(f"""CREATE OR REPLACE TABLE population AS SELECT z.id::INTEGER zone_id, p.annee, p.population
                        FROM populations p JOIN zones_df z ON z.niveau_id = {N['commune']} AND z.code = p.code_commune""")
        perdus = q("SELECT (SELECT count(*) FROM populations) - (SELECT count(*) FROM population)")[0][0]
        con.execute("DROP TABLE populations")
        etape(f"population : {q('SELECT count(*) FROM population')[0][0]} lignes ({perdus} sans zone)")
        recopier(con, ["population"], [("population", "zone_id", "zone")])
    con.unregister("zones_df")
    geo = [t for (t,) in q("SELECT table_name FROM duckdb_tables() WHERE starts_with(table_name, 'geo_')")]
    for t in geo:
        sauvegarder_duckdb(con, t, f"{t}_avant_zone")
        con.execute(f"DROP TABLE {t}")
    restes = [t for t in requete("SHOW TABLES").iloc[:, 0] if t.startswith("geo_") or t in ("contours", "populations")]
    if restes:
        mysql("SET foreign_key_checks = 0; " + " ".join(f"DROP TABLE `{t}`;" for t in restes))
    if geo or restes:
        etape(f"retirées : {', '.join(sorted(set(geo) | set(restes)))}")
    etape(f"zones : fini en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    essai = "--essai" in sys.argv
    con = duckdb.connect(str(BASE), read_only=essai)
    zones(con, essai)
    if not essai:
        con.execute("CHECKPOINT")
    con.close()
