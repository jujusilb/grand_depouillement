"""
brancher_modele.py — Branche la base de l'appli (data/depouillement.duckdb) sur le modèle « personnes et mandats ».

    py brancher_modele.py        (l'appli fermée ; lancé aussi à la fin de base_appli.py)

MariaDB fait foi (construire_modele.py l'a rempli ; on y corrige avec phpMyAdmin). Ici :
    1. l'instantané local du modèle est rafraîchi depuis MariaDB (data/modele.duckdb, voir gd/modele.py) ; l'appli lit
       personne, mandat, candidature, liste, photo… directement dans cet instantané (modele.*) ;
    2. les votes des députés et les sièges des législatures (données fixes, gardées dans DuckDB) ne gardent plus le nom :
       un numéro de personne du modèle (le nom tel qu'écrit reste seulement quand on n'a pas su qui c'est) ;
    3. les 14 anciennes tables qui écrivaient les personnes « en dur » (deputes, senateurs, rne_*, candidats_*…) sont
       retirées : tout ce qu'elles disaient est dans le modèle.
La première fois, la base est d'abord copiée dans PROJET/DECHET (et relue de là quand les tables d'origine n'y sont plus).
"""
import shutil
import sys
import time
from pathlib import Path

import duckdb

from lecture import modele

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
DATA = C.DONNEES_APPLI
BASE = C.BASE
DECHET = C.DECHET

ANCIENNES = ["deputes", "senateurs", "mandats_deputes", "groupes_deputes", "sieges_legislature", "votes_individuels",
             "candidats_details", "candidats_listes", "elus_municipaux_2014", "rne_municipaux", "rne_communautaires",
             "rne_departementaux", "rne_regionaux", "rne_arrondissements"]

# le nom affiché d'une personne, et la clé qui sert à reconnaître un nom écrit « Prénom Nom »
def nom_cle(expr_prenom, expr_nom):
    """« Jean-Marie » + « Le Pen » → « JEAN|LE PEN » : le premier prénom et le nom, sans accents ni tirets."""
    n = lambda s: f"trim(regexp_replace(upper(strip_accents(coalesce({s}, ''))), '[^A-Z0-9]+', ' ', 'g'))"
    return f"split_part({n(expr_prenom)}, ' ', 1) || '|' || {n(expr_nom)}"


if __name__ == "__main__":
    t0 = time.time()
    msg = modele.rafraichir(DATA)
    print("Instantané du modèle :", msg or "déjà à jour")
    con = duckdb.connect(str(BASE))
    modele.brancher(con, DATA, rafraichir_d_abord=False)
    sauvegarde = DECHET / "depouillement_avant_modele.duckdb"
    tables = {t for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = 'depouillement'").fetchall()}
    ancienne_forme = lambda t: t in tables and bool(con.execute(
        f"SELECT count(*) FROM duckdb_columns() WHERE table_name = '{t}' AND column_name = 'depute'").fetchone()[0])
    if any(t in tables for t in ANCIENNES) and not sauvegarde.exists():
        con.close()
        DECHET.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE, sauvegarde)
        print("Copie de sauvegarde : PROJET/DECHET/depouillement_avant_modele.duckdb")
        con = duckdb.connect(str(BASE))
        modele.brancher(con, DATA, rafraichir_d_abord=False)

    # où lire les votes et les sièges d'origine (avec les noms) : dans la base si base_appli.py vient de les y mettre,
    # sinon dans la copie d'avant (pour suivre un modèle refait)
    if ancienne_forme("votes_individuels"):
        SRC = ""
    else:
        con.execute(f"ATTACH '{sauvegarde.as_posix()}' AS src (READ_ONLY)")
        SRC = "src."
    LG = "(SELECT legislature, CAST(debut AS DATE) debut, CAST(fin AS DATE) fin FROM legislatures)"
    # les votes : le numéro de la personne (le député de cette législature qui porte ce nom), sinon le nom tel qu'écrit
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE deputes_par_legislature AS
    SELECT lg.legislature, any_value(m.personne_id) personne_id, {nom_cle('p.prenoms', 'p.nom_usage')} cle
    FROM modele.mandat m JOIN modele.personne p ON p.id = m.personne_id
    JOIN modele.fonction f ON f.id = m.fonction_id AND f.label = 'député'
    JOIN {LG} lg ON coalesce(m.date_debut, DATE '2024-07-07') < coalesce(lg.fin, DATE '2999-01-01')
                AND coalesce(m.date_fin, DATE '2999-01-01') > lg.debut
    GROUP BY lg.legislature, cle HAVING count(DISTINCT m.personne_id) = 1""")
    con.execute(f"""
    CREATE OR REPLACE TABLE votes_nouveaux AS
    WITH v AS (SELECT v.*, coalesce(TRY_CAST(regexp_extract(v.scrutin, '^AN(\\d+)', 1) AS INTEGER),
                                    (SELECT lg.legislature FROM {LG} lg WHERE CAST(s.date AS DATE) >= lg.debut
                                     AND CAST(s.date AS DATE) < coalesce(lg.fin, DATE '2999-01-01'))) legislature,
                      {nom_cle("regexp_extract(v.depute, '^(\\S+)', 1)", "regexp_replace(v.depute, '^\\S+\\s+', '')")} cle
               FROM {SRC}votes_individuels v LEFT JOIN (SELECT DISTINCT ON (scrutin) scrutin, date FROM votes_scrutins) s USING (scrutin))
    SELECT v.scrutin, d.personne_id, CASE WHEN d.personne_id IS NULL THEN v.depute END nom_non_identifie,
           v.groupe, v.couleur, v.position, v.lieu
    FROM v LEFT JOIN deputes_par_legislature d ON d.legislature = v.legislature AND d.cle = v.cle""")
    # les sièges des législatures : par l'identifiant de l'Assemblée (2002 →), sinon par le mandat du même siège
    con.execute(f"""
    CREATE OR REPLACE TABLE sieges_nouveaux AS
    SELECT s.legislature, coalesce(an.personne_id, mt.personne_id) personne_id,
           CASE WHEN coalesce(an.personne_id, mt.personne_id) IS NULL THEN s.depute END nom_non_identifie,
           s.groupe, s.couleur, s.lieu, s.connu
    FROM {SRC}sieges_legislature s JOIN {LG} lg USING (legislature)
    LEFT JOIN (modele.identifiant an JOIN modele.referentiel ran ON ran.id = an.referentiel_id
               AND ran.libelle = 'Assemblée nationale') ON an.valeur = s.acteur
    LEFT JOIN (SELECT DISTINCT ON (m.date_debut, m.zone_code) m.date_debut, m.zone_code, m.personne_id FROM modele.mandat m
               JOIN modele.fonction f ON f.id = m.fonction_id AND f.label = 'député' WHERE m.personne_id IS NOT NULL) mt
           ON s.legislature < 12 AND s.connu AND mt.date_debut = lg.debut
          AND mt.zone_code = upper(regexp_extract(s.lieu, '·\\s*(\\S+)\\s*$', 1)) || '-' || regexp_extract(s.lieu, '^(\\d+)', 1)""")
    if SRC:
        con.execute("DETACH src")

    # les 14 anciennes tables (ou vues de transition) retirées ; votes et sièges prennent leur nom définitif
    for t in ANCIENNES:
        con.execute(f"DROP VIEW IF EXISTS {t}")
        con.execute(f"DROP TABLE IF EXISTS {t}")
    for t in ["votes_individuels_base", "sieges_legislature_base"]:
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.execute("ALTER TABLE votes_nouveaux RENAME TO votes_individuels")
    con.execute("ALTER TABLE sieges_nouveaux RENAME TO sieges_legislature")
    print()
    for t in ["votes_individuels", "sieges_legislature"]:
        n, k = con.execute(f"SELECT count(*), count(personne_id) FROM {t}").fetchone()
        print(f"   {t:20s} {k:,} / {n:,} lignes reliées à une personne ({100 * k / max(n, 1):.1f} %)".replace(",", " "))
    reste = con.execute(f"""SELECT count(*) FROM duckdb_columns() WHERE database_name = 'depouillement'
                            AND column_name IN ('nom', 'prenom', 'naissance', 'depute', 'photo', 'acteur')
                            AND table_name NOT IN ('contours', 'geo_bureau')""").fetchone()[0]
    print(f"   colonnes d'identité encore dans la base de l'appli : {reste}")
    con.execute("CHECKPOINT")
    con.close()
    print(f"Branché en {time.time() - t0:.0f} s.")
