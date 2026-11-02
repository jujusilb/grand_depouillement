"""
normaliser_nuances.py — Les nuances politiques du schéma v2 : bloc → famille → nuance, et nuance_id partout.

    py normaliser_nuances.py          (l'appli fermée ; MariaDB de XAMPP démarré ; relançable)

Lancé par normaliser_references.py (après les résultats). Dans MariaDB (le modèle) :
    bloc (id, libelle, couleur)                      gauche, droite et centre, extrême droite, divers
    famille (id, libelle, couleur, rang, bloc_id)    socialiste, divers droite… ; rang = place de gauche à droite
    nuance (id, libelle, explication, famille_id)    libelle = le code tel quel (LUG, BC-DVD, « radicaux » avant 2002) ;
                                                     explication = le texte officiel (« Liste d'union de la gauche »)
Les familles, leurs couleurs et les blocs viennent de gd/theme.py (FAMILLES, ORDRE_FAMILLES, BLOCS, NUANCES).
L'explication : la grille officielle du ministère la plus récente qui donne ce code
(donnees/nuances/referentiels_ministere.tsv, municipales 2026 : fichiers des listes déposées) ; sinon vide,
à remplir avec remplir_nuances.py.
Décisions de Julien (2 novembre 2026) : un code = une nuance (DVD, LDVD, BC-DVD : trois lignes) ; aux présidentielles
2002-2012 le code de candidat (CHIR…) devient la nuance de son parti (donnees/nuances/candidats_presidentielles.tsv) ;
OUI / NON des référendums et les intitulés de liste tombés dans la colonne : pas de nuance.
Converties : resultat (base de l'appli, recopiée dans MariaDB), candidature, liste : nuance → nuance_id.
"""
import re
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
from interface import theme  # noqa: E402
from normaliser_references import lien, sauvegarder_duckdb             # noqa: E402
from outils_mariadb import charger, cle_etrangere, mysql, requete, sauvegarder   # noqa: E402

import exporter_mariadb as ex                                          # noqa: E402

BASE = C.BASE
NUANCES = C.SAISIES / "nuances"
LISTES_2026 = C.DONNEES / "listes" / "brut" / "muni2026_t1.csv"
DECHET = C.DECHET
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
PAS_NUANCE = {"OUI", "NON"}                         # (réponses des référendums)


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def colonnes(table):
    return set(requete(f"SHOW COLUMNS FROM `{table}`").Field) if len(requete(f"SHOW TABLES LIKE '{table}'")) else set()


def lire(sql, noms):
    r = requete(sql)
    return r if len(r.columns) == len(noms) else pd.DataFrame(columns=noms)


def annee(election):
    return int(re.search(r"(\d{4})", election)[1])


def explications():
    """code → explication officielle (la grille la plus récente qui le donne)."""
    g = pd.read_csv(NUANCES / "referentiels_ministere.tsv", sep="\t", comment="#", dtype=str)
    if LISTES_2026.exists():
        m = pd.read_csv(LISTES_2026, sep=";", dtype=str, usecols=["Code nuance de liste", "Nuance de liste"]).dropna().drop_duplicates()
        g = pd.concat([g, pd.DataFrame({"election": "municipales2026", "code": m["Code nuance de liste"],
                                        "explication": m["Nuance de liste"]})])
    g["annee"] = g["election"].map(annee)
    return g.sort_values("annee").drop_duplicates("code", keep="last").set_index("code")["explication"].to_dict()


def code_valide(v):
    """Un code du ministère (« LDVD », « BC-DVD ») ou un nom de famille d'avant 2002 (« radicaux ») — pas un intitulé de liste."""
    v = str(v)
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,9}", v)) or v.lower() in theme.FAMILLES_ANCIENNES or v.lower() in theme.FAMILLES


def famille_de(code):
    return theme.FAMILLE_DE_COULEUR.get(theme.couleur_politique(code, mots=False))


def nuances(con):
    t0 = time.time()
    # 1. bloc, famille, nuance (numéros gardés d'une fois sur l'autre : on retrouve par libellé)
    mysql(f"""CREATE TABLE IF NOT EXISTS bloc (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(40) NOT NULL, couleur VARCHAR(7) NULL,
                UNIQUE KEY ix_bloc (libelle)) {T};
              CREATE TABLE IF NOT EXISTS famille (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(40) NOT NULL, couleur VARCHAR(7) NULL,
                rang INT NULL, bloc_id INT NULL, UNIQUE KEY ix_famille (libelle),
                CONSTRAINT fk_famille_bloc_id FOREIGN KEY (bloc_id) REFERENCES bloc (id)) {T};
              CREATE TABLE IF NOT EXISTS nuance (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(40) NOT NULL, explication VARCHAR(120) NULL,
                famille_id INT NULL, UNIQUE KEY ix_nuance (libelle),
                CONSTRAINT fk_nuance_famille_id FOREIGN KEY (famille_id) REFERENCES famille (id)) {T};""")
    blocs = list(theme.BLOCS)
    mysql("INSERT IGNORE INTO bloc VALUES " + ", ".join(
        f"({i}, '{b}', '{theme.COULEURS_BLOCS[b]}')" for i, b in enumerate(blocs, 1)) + ";")
    familles = [f for f in theme.FAMILLES if f not in ("oui", "non")]
    mysql("INSERT IGNORE INTO famille VALUES " + ", ".join(
        f"({i}, '{f}', '{theme.FAMILLES[f]}', {theme.ORDRE_FAMILLES.index(f) if f in theme.ORDRE_FAMILLES else 'NULL'}, "
        f"{blocs.index(theme.BLOC_DE_FAMILLE[f]) + 1 if f in theme.BLOC_DE_FAMILLE else 'NULL'})" for i, f in enumerate(familles, 1)) + ";")
    id_famille = {f: i for i, f in enumerate(familles, 1)}

    # 2. les valeurs à convertir, et ce qu'elles deviennent
    a_faire_res = con.execute("SELECT count(*) FROM duckdb_columns() WHERE table_name = 'resultat' AND column_name = 'nuance'").fetchall()[0][0]
    a_faire = [t for t in ("candidature", "liste") if "nuance" in colonnes(t)]
    if not a_faire_res and not a_faire:
        etape("nuances : déjà converties")
        return
    pres = pd.read_csv(NUANCES / "candidats_presidentielles.tsv", sep="\t", comment="#", dtype=str)
    carte_pres = {(e, c): n for e, c, n in zip(pres.election, pres.code, pres.nuance)}
    # (le code de l'élection de chaque scrutin, depuis MariaDB)
    sc = requete("SELECT s.id, e.code FROM scrutin s JOIN election e ON e.id = s.election_id").astype({"id": int})
    con.register("sc_df", sc)
    con.execute("CREATE OR REPLACE TEMP TABLE scrutin_cle AS SELECT id::INTEGER id, code FROM sc_df")
    con.unregister("sc_df")
    paires = con.execute("""SELECT DISTINCT e.code election, r.nuance valeur FROM resultat r JOIN scrutin_cle e ON e.id = r.scrutin_id
                            WHERE r.nuance IS NOT NULL""").df() if a_faire_res else pd.DataFrame(columns=["election", "valeur"])
    for t in a_faire:
        paires = pd.concat([paires, requete(f"SELECT DISTINCT '' election, nuance valeur FROM {t} WHERE nuance IS NOT NULL")])

    def devient(election, valeur):
        if (election, valeur) in carte_pres:
            return carte_pres[election, valeur]
        if valeur in PAS_NUANCE or not code_valide(valeur):
            return None
        return valeur
    paires["code"] = [devient(e, v) for e, v in zip(paires.election, paires.valeur)]
    codes = sorted(set(paires.code.dropna()))

    # 3. la table nuance : les codes rencontrés, leur explication officielle, leur famille
    deja = lire("SELECT id, libelle FROM nuance", ["id", "libelle"])
    connus = dict(zip(deja.libelle, deja.id.astype(int)))
    expl = explications()
    nouveaux = []
    for c in codes:
        if c not in connus:
            connus[c] = max(connus.values(), default=0) + 1
            nouveaux.append((connus[c], c, expl.get(c), id_famille.get(famille_de(c))))
    if nouveaux:
        charger("nuance", pd.DataFrame(nouveaux, columns=["id", "libelle", "explication", "famille_id"]))
    # (une explication officielle trouvée depuis : on la met, sans écraser ce que Julien a rempli)
    for c, e in expl.items():
        if c in connus:
            mysql(f"UPDATE nuance SET explication = '{e.replace(chr(39), chr(39) * 2)}' WHERE libelle = '{c}' AND explication IS NULL;")
    n = requete("SELECT count(*) n, sum(explication IS NULL) sans, sum(famille_id IS NULL) sans_famille FROM nuance")
    etape(f"nuance : {n.n[0]} nuances ({len(nouveaux)} nouvelles), {n.sans[0]} sans explication, {n.sans_famille[0]} sans famille")
    paires["nuance_id"] = paires.code.map(connus)
    jetees = paires[paires.code.isna()].valeur.unique()
    etape(f"pas une nuance (vide) : {', '.join(sorted(map(str, jetees))[:12])}{'…' if len(jetees) > 12 else ''}")

    # 4. resultat (base de l'appli) : nuance_id à la place du texte, puis sa copie dans MariaDB
    if a_faire_res:
        sauvegarder_duckdb(con, "resultat", "resultat_avant_nuance")
        con.register("carte", paires[paires.election != ""][["election", "valeur", "nuance_id"]])
        n0 = con.execute("SELECT count(*) FROM resultat").fetchall()[0][0]
        con.execute("""CREATE OR REPLACE TABLE resultat_n AS
                       SELECT r.scrutin_id, r.bureau_id, r.qui, c.nuance_id::INTEGER nuance_id, r.voix
                       FROM resultat r JOIN scrutin_cle e ON e.id = r.scrutin_id
                       LEFT JOIN carte c ON c.election = e.code AND c.valeur = r.nuance ORDER BY 1, 2""")
        if con.execute("SELECT count(*) FROM resultat_n").fetchall()[0][0] != n0:
            raise RuntimeError("resultat : des lignes perdues")
        con.unregister("carte")
        con.execute("DROP TABLE resultat")
        con.execute("ALTER TABLE resultat_n RENAME TO resultat")
        con.execute("CHECKPOINT")
        ex.copier(con, "resultat", '"resultat"')
        mysql("ALTER TABLE resultat ADD INDEX ix_scrutin_bureau (scrutin_id, bureau_id), ADD INDEX ix_bureau (bureau_id), "
              "ADD INDEX ix_nuance (nuance_id)")
        for c, r in (("scrutin_id", "scrutin"), ("bureau_id", "bureau"), ("nuance_id", "nuance")):
            lien("resultat", c, r)
        etape("resultat : nuance_id (recopiée dans MariaDB)")

    # 5. candidature, liste (MariaDB) : nuance_id
    carte = paires[paires.election == ""][["valeur", "nuance_id"]].drop_duplicates("valeur")
    for t in a_faire:
        etape("sauvegarde : " + sauvegarder(DECHET, f"{t}_avant_nuance", [t]).name)
        mysql(f"DROP TABLE IF EXISTS tmp_nu; CREATE TABLE tmp_nu (valeur VARCHAR(255) PRIMARY KEY, nuance_id INT) {T}")
        charger("tmp_nu", carte)
        mysql(f"""ALTER TABLE {t} ADD COLUMN nuance_id INT NULL AFTER nuance;
                  UPDATE {t} x JOIN tmp_nu n ON n.valeur = x.nuance SET x.nuance_id = n.nuance_id;
                  ALTER TABLE {t} DROP COLUMN nuance, ADD INDEX ix_{t}_nuance (nuance_id); DROP TABLE tmp_nu""")
        cle_etrangere(t, "nuance_id", "nuance")
        etape(f"{t} : nuance_id")
    etape(f"nuances : fini en {(time.time() - t0) / 60:.0f} min")


if __name__ == "__main__":
    con = duckdb.connect(str(BASE))
    nuances(con)
    con.close()
