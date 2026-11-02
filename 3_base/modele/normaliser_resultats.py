"""
normaliser_resultats.py — Les résultats du schéma v2 : participation et resultat rangés par scrutin_id et bureau_id.

    py normaliser_resultats.py          (l'appli fermée ; MariaDB de XAMPP démarré ; ~30 min, surtout la recopie)

Lancé par normaliser_references.py (après zones et élections) ; relançable.

    participation (scrutin_id, bureau_id, inscrits, abstentions, votants, blancs, nuls, exprimes)
        plus de texte recopié à chaque ligne : le scrutin (« 2022_legi_t1 »), le bureau (id_brut_miom, code_bv), la
        commune, l'arrondissement, le canton, le département, la région et leurs libellés se lisent dans zone (le bureau
        et ses parents ; commune.epci_id, bureau.canton_id / circonscription_id).
    resultat (scrutin_id, bureau_id, qui, nuance, voix)                       remplace resultats
        qui et nuance restent du texte en attendant la nuance (point ouvert 7) et le rattachement à la candidature
        ou à la liste.
« Les 2 tours » (2nd tour là où il a eu lieu, sinon le 1er) ne sont plus recopiés : l'appli les calcule
(gd/donnees.py). Les tables scrutins et scrutins_2tours disparaissent (le modèle a scrutin).

Avant : les codes de canton et d'arrondissement de participation (ceux du découpage d'aujourd'hui, même pour 1936)
complètent les bureaux et communes disparus (bureau.canton_id, parent arrondissement de la commune).
"""
import time
import sys
from pathlib import Path

import duckdb
import pandas as pd

import exporter_mariadb as ex
from normaliser_references import lien, sauvegarder_duckdb
from normaliser_zones import dep
from outils_mariadb import charger, mysql, requete

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
BASE = C.BASE
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
ARRONDISSEMENT, CANTON, COMMUNE, BUREAU = 4, 6, 8, 12      # (niveaux de zone)
CANTONS_2015 = "2015-03-22"


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def existe(con, t):
    return con.execute(f"SELECT count(*) FROM duckdb_tables() WHERE table_name = '{t}'").fetchall()[0][0] > 0


def completer_zones(con):
    """Bureaux et communes disparus : leur canton et leur arrondissement d'après participation (découpage d'aujourd'hui)."""
    lieux = con.execute(r"""SELECT id_brut_miom, any_value(code_commune) commune, any_value(code_departement) departement,
                                   any_value(code_departement || '-' || right(code_canton, 2)) canton, any_value(code_arr) arr
                            FROM participation WHERE NOT regexp_matches(scrutin, '_2t$') GROUP BY 1""").df()
    mysql(f"""DROP TABLE IF EXISTS tmp_lieu; CREATE TABLE tmp_lieu (bureau VARCHAR(20) PRIMARY KEY, commune VARCHAR(10),
                departement VARCHAR(3), canton VARCHAR(12), arr VARCHAR(5), KEY (commune)) {T}""")
    lieux["departement"] = lieux["departement"].map(lambda x: dep(x) if x else None)   # (« 972 » → « ZB », comme zone)
    charger("tmp_lieu", lieux.rename(columns={"id_brut_miom": "bureau"}))
    mysql(f"""UPDATE bureau b JOIN zone z ON z.id = b.id JOIN tmp_lieu t ON t.bureau = z.code
                JOIN zone c ON c.niveau_id = {CANTON} AND c.code = t.canton AND c.date_debut = '{CANTONS_2015}'
              SET b.canton_id = c.id WHERE b.canton_id IS NULL;
              UPDATE zone z JOIN zone d ON d.id = z.parent_id AND d.niveau_id = 3
                JOIN (SELECT commune, max(arr) arr FROM tmp_lieu WHERE arr IS NOT NULL GROUP BY commune) t ON t.commune = z.code
                JOIN zone a ON a.niveau_id = {ARRONDISSEMENT} AND a.code = t.arr AND a.parent_id = d.id
              SET z.parent_id = a.id WHERE z.niveau_id = {COMMUNE};
              UPDATE zone z JOIN tmp_lieu t ON t.bureau = z.code
                JOIN zone d ON d.niveau_id = 3 AND d.code = t.departement
              SET z.parent_id = d.id WHERE z.niveau_id = {BUREAU} AND z.parent_id IS NULL;
              DROP TABLE tmp_lieu""")
    # (les « bureaux » des anciens scrutins publiés par département, circonscription ou canton — « 39_SEN » des
    #  sénatoriales — n'ont pas de commune : leur zone est rattachée à leur département)
    n = requete(f"""SELECT (SELECT count(*) FROM bureau WHERE canton_id IS NULL) sans_canton,
                           (SELECT count(*) FROM zone z JOIN zone d ON d.id = z.parent_id AND d.niveau_id = 3
                            WHERE z.niveau_id = {COMMUNE}) communes_sans_arr""")
    etape(f"zones complétées : {n.sans_canton[0]} bureaux sans canton, {n.communes_sans_arr[0]} communes sans arrondissement")


def resultats(con):
    t0 = time.time()
    if not existe(con, "resultats") and not existe(con, "scrutins"):
        etape("résultats : déjà convertis")
        return
    if existe(con, "resultats"):
        completer_zones(con)
        scrutins = requete("""SELECT s.id, concat(e.code, '_t', s.tour) cle FROM scrutin s JOIN election e ON e.id = s.election_id
                              WHERE s.tour IS NOT NULL""").astype({"id": int})
        bureaux = requete(f"SELECT id, code FROM zone WHERE niveau_id = {BUREAU}").astype({"id": int})
        con.register("smap", scrutins)
        con.register("bmap", bureaux)
        con.execute("CREATE OR REPLACE TEMP TABLE sm AS SELECT id::INTEGER id, cle FROM smap")
        con.execute("CREATE OR REPLACE TEMP TABLE bm AS SELECT id::INTEGER id, code FROM bmap")
        con.unregister("smap")
        con.unregister("bmap")
        reels = r"NOT regexp_matches(x.scrutin, '_2t$')"
        for ancien, nouveau, colonnes in [
                ("participation", "participation_v2", "x.inscrits, x.abstentions, x.votants, x.blancs, x.nuls, x.exprimes"),
                ("resultats", "resultat", "x.qui, x.nuance, x.voix::BIGINT voix")]:
            sauvegarder_duckdb(con, ancien, f"{ancien}_avant_v2")
            con.execute(f"""CREATE OR REPLACE TABLE {nouveau} AS
                            SELECT s.id scrutin_id, b.id bureau_id, {colonnes}
                            FROM {ancien} x JOIN sm s ON s.cle = x.scrutin JOIN bm b ON b.code = x.id_brut_miom
                            WHERE {reels} ORDER BY 1, 2""")
            attendu = con.execute(f"SELECT count(*) FROM {ancien} x WHERE {reels}").fetchall()[0][0]
            obtenu = con.execute(f"SELECT count(*) FROM {nouveau}").fetchall()[0][0]
            if attendu != obtenu:
                raise RuntimeError(f"{nouveau} : {attendu - obtenu} lignes sans scrutin ou sans bureau")
            etape(f"{nouveau} : {obtenu} lignes (« les 2 tours » retirés : calculés par l'appli)")
        con.execute("DROP TABLE resultats")
        con.execute("DROP TABLE participation")
        con.execute("ALTER TABLE participation_v2 RENAME TO participation")
    for t in ("scrutins", "scrutins_2tours"):
        if existe(con, t):
            sauvegarder_duckdb(con, t, f"{t}_avant_v2")
            con.execute(f"DROP TABLE {t}")
    con.execute("CHECKPOINT")

    # la copie dans MariaDB, avec ses clés étrangères (la plus longue partie)
    for t in ("participation", "resultat"):
        if t == "participation" and "scrutin_id" in set(requete("SHOW COLUMNS FROM participation").Field):
            continue
        if t == "resultat" and len(requete("SHOW TABLES LIKE 'resultat'")):
            continue
        ex.copier(con, t, f'"{t}"')
        mysql(f"ALTER TABLE `{t}` ADD INDEX ix_scrutin_bureau (scrutin_id, bureau_id), ADD INDEX ix_bureau (bureau_id)")
        lien(t, "scrutin_id", "scrutin")
        lien(t, "bureau_id", "bureau")
        etape(f"{t} recopiée dans MariaDB")
    vieux = [t for t in ("resultats", "scrutins", "scrutins_2tours") if len(requete(f"SHOW TABLES LIKE '{t}'"))]
    if vieux:
        mysql("SET foreign_key_checks = 0; " + " ".join(f"DROP TABLE `{t}`;" for t in vieux))
    etape(f"résultats : fini en {(time.time() - t0) / 60:.0f} min")


if __name__ == "__main__":
    con = duckdb.connect(str(BASE))
    resultats(con)
    con.close()
