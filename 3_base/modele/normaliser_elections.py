"""
normaliser_elections.py — Les élections du schéma v2 : une élection n'a pas de date, ses scrutins (un par tour) en ont.

    py normaliser_elections.py          (l'appli fermée ; MariaDB de XAMPP démarré)

Lancé par normaliser_references.py (dernière étape de la fabrication), après normaliser_zones.py ; relançable.

    categorie_election (id, code, libelle)           remplace type_election (plus de mot « type » : legi / Législatives…)
    election (id, code, categorie_election_id, annee, libelle, partielle, duree_exception)     sans date
    scrutin (id, election_id, tour, date, libelle)    un par tour ; la date reste vide tant qu'elle n'est pas fixée
On sait qu'une élection aura lieu avant d'en connaître les dates (présidentielle 2032) : elle existe sans scrutin daté.
election garde son code (« 2022_legi ») : c'est l'identifiant des fichiers d'origine et des résultats.

candidature, liste : scrutin_id à la place de election_id + tour. mandat : scrutin_id = le tour où l'élu a été élu —
celui de sa candidature élue ; sinon celui qu'on peut déduire sans rien inventer : le seul tour d'une élection à un
tour, le 1er tour d'une commune où il n'y a pas eu de 2nd tour (participation), le dernier tour d'une présidentielle.
Sinon (décision de Julien, 2 novembre 2026 : ne pas nier le mandat en lui ôtant son élection, ni inventer son tour) un
scrutin « tour inconnu » de son élection : tour vide, sans date (il n'apparaît pas dans les listes de scrutins).
"""
import time
import sys
from pathlib import Path

import duckdb
import pandas as pd

from outils_mariadb import charger, cle_etrangere, mysql, requete, sauvegarder

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
BASE = C.BASE
DECHET = C.DECHET
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
COMMUNE = 8                                   # (niveau de zone)


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def colonnes(table):
    return set(requete(f"SHOW COLUMNS FROM `{table}`").Field) if len(requete(f"SHOW TABLES LIKE '{table}'")) else set()


def lire(sql, noms):
    r = requete(sql)
    return r if len(r.columns) == len(noms) else pd.DataFrame(columns=noms)


def elections(con):
    t0 = time.time()
    a_faire = "date_t1" in colonnes("election") or "type_election_id" in colonnes("election") \
        or "election_id" in colonnes("mandat") | colonnes("candidature") | colonnes("liste")
    if not a_faire:
        etape("élections : déjà converties")
        return
    etape("sauvegarde : " + sauvegarder(DECHET, "avant_scrutins", [t for t in ("type_election", "election", "mandat",
                                                                               "candidature", "liste") if colonnes(t)]).name)

    # 1. categorie_election (remplace type_election, mêmes numéros)
    mysql(f"""CREATE TABLE IF NOT EXISTS categorie_election (id INT NOT NULL PRIMARY KEY, code VARCHAR(4) NOT NULL,
                libelle VARCHAR(40) NOT NULL, UNIQUE KEY ix_categorie_code (code)) {T}""")
    if "type_election_id" in colonnes("election"):
        mysql("""INSERT IGNORE INTO categorie_election SELECT id, code, label FROM type_election;
                 ALTER TABLE election DROP FOREIGN KEY fk_election_type_election_id;
                 ALTER TABLE election CHANGE type_election_id categorie_election_id INT NULL;
                 SET foreign_key_checks = 0; DROP TABLE type_election""")
        cle_etrangere("election", "categorie_election_id", "categorie_election")
        etape("categorie_election : remplace type_election")

    # 2. scrutin : un par tour (numéros gardés d'une fois sur l'autre)
    mysql(f"""CREATE TABLE IF NOT EXISTS scrutin (id INT NOT NULL PRIMARY KEY, election_id BIGINT NOT NULL, tour TINYINT NULL,
                date DATE NULL, libelle VARCHAR(120) NOT NULL, UNIQUE KEY ix_scrutin_tour (election_id, tour)) {T}""")
    if "date_t1" in colonnes("election"):
        deja = lire("SELECT id, election_id, tour FROM scrutin", ["id", "election_id", "tour"])
        connus = {(int(e), int(t)): int(i) for i, e, t in deja.itertuples(index=False)}
        tours = requete("""SELECT id election_id, 1 tour, date_t1 date, libelle_t1 libelle FROM election
                           UNION ALL SELECT id, 2, date_t2, libelle_t2 FROM election WHERE date_t2 IS NOT NULL OR libelle_t2 IS NOT NULL
                           ORDER BY 1, 2""")
        suivant = max(connus.values(), default=0) + 1
        ids = []
        for e, t in zip(tours.election_id.astype(int), tours.tour.astype(int)):
            if (e, t) not in connus:
                connus[e, t], suivant = suivant, suivant + 1
            ids.append(connus[e, t])
        tours.insert(0, "id", ids)
        nouveaux = tours[~tours.id.isin(set(deja.id.astype(int)))]
        if len(nouveaux):
            charger("scrutin", nouveaux)
        if not len(requete("SELECT 1 FROM information_schema.table_constraints WHERE table_schema = DATABASE() "
                           "AND constraint_name = 'fk_scrutin_election_id'")):
            cle_etrangere("scrutin", "election_id", "election")
        etape(f"scrutin : {len(tours)} scrutins ({len(nouveaux)} nouveaux)")

    # 3. mandat : le tour où l'élu a été élu (avant de convertir les candidatures, qui le disent)
    if "election_id" in colonnes("mandat"):
        mysql(f"""DROP TABLE IF EXISTS tmp_tour; CREATE TABLE tmp_tour (personne_id BIGINT, election_id INT, tour TINYINT,
                    PRIMARY KEY (personne_id, election_id)) {T};
                  INSERT INTO tmp_tour SELECT personne_id, election_id, max(tour) FROM candidature
                  WHERE elu AND election_id IS NOT NULL GROUP BY 1, 2;
                  ALTER TABLE mandat ADD COLUMN scrutin_id INT NULL AFTER election_id;
                  UPDATE mandat m JOIN tmp_tour t ON t.personne_id = m.personne_id AND t.election_id = m.election_id
                    JOIN scrutin s ON s.election_id = m.election_id AND s.tour = t.tour SET m.scrutin_id = s.id;
                  UPDATE mandat m JOIN scrutin s ON s.election_id = m.election_id AND s.tour = 1
                    SET m.scrutin_id = s.id
                  WHERE m.scrutin_id IS NULL AND NOT EXISTS (SELECT 1 FROM scrutin s2 WHERE s2.election_id = m.election_id AND s2.tour = 2);
                  DROP TABLE tmp_tour""")
        # les communes sans 2nd tour à une élection municipale : tous leurs élus l'ont été au 1er
        t2 = con.execute(r"""SELECT DISTINCT regexp_replace(scrutin, '_t2$', '') election, code_commune FROM participation
                             WHERE scrutin LIKE '%\_muni\_t2' ESCAPE '\'""").df()
        mysql(f"DROP TABLE IF EXISTS tmp_t2; CREATE TABLE tmp_t2 (election VARCHAR(12), commune VARCHAR(10), PRIMARY KEY (election, commune)) {T}")
        charger("tmp_t2", t2.rename(columns={"code_commune": "commune"}))
        mysql(f"""UPDATE mandat m JOIN election e ON e.id = m.election_id AND e.code LIKE '%\\_muni'
                    JOIN zone z ON z.id = m.zone_id JOIN scrutin s ON s.election_id = m.election_id AND s.tour = 1
                    SET m.scrutin_id = s.id
                  WHERE m.scrutin_id IS NULL
                    AND EXISTS (SELECT 1 FROM tmp_t2 x WHERE x.election = e.code)
                    AND NOT EXISTS (SELECT 1 FROM tmp_t2 x WHERE x.election = e.code AND x.commune = left(z.code, 5));
                  DROP TABLE tmp_t2""")
        # la présidentielle : une seule circonscription, un 2nd tour seulement si personne n'a la majorité au 1er
        # (Constitution, art. 7) — le président est élu au dernier tour de son élection
        mysql("""UPDATE mandat m JOIN election e ON e.id = m.election_id
                   JOIN categorie_election ce ON ce.id = e.categorie_election_id AND ce.code = 'pres'
                   JOIN scrutin s ON s.election_id = e.id AND s.tour = (SELECT max(s2.tour) FROM scrutin s2 WHERE s2.election_id = e.id)
                   SET m.scrutin_id = s.id WHERE m.scrutin_id IS NULL""")
        n_deduits = requete("SELECT sum(scrutin_id IS NULL) sans FROM mandat WHERE election_id IS NOT NULL").sans[0]
        # le reste : un scrutin « tour inconnu » de son élection (tour vide, sans date ; décision de Julien)
        mysql("""SET @n := (SELECT max(id) FROM scrutin);
                 INSERT INTO scrutin (id, election_id, tour, date, libelle)
                 SELECT (@n := @n + 1), e.id, NULL, NULL, concat(e.libelle, ' – tour inconnu') FROM election e
                 WHERE e.id IN (SELECT election_id FROM mandat WHERE scrutin_id IS NULL)
                   AND NOT EXISTS (SELECT 1 FROM scrutin s WHERE s.election_id = e.id AND s.tour IS NULL);
                 UPDATE mandat m JOIN scrutin s ON s.election_id = m.election_id AND s.tour IS NULL
                 SET m.scrutin_id = s.id WHERE m.scrutin_id IS NULL""")
        etape(f"mandat : {n_deduits} élus dont le tour est inconnu (scrutin « tour inconnu » de leur élection)")
        n = requete("SELECT count(*) n, sum(scrutin_id IS NULL) sans FROM mandat WHERE election_id IS NOT NULL")
        mysql("""ALTER TABLE mandat DROP FOREIGN KEY fk_mandat_election_id;
                 ALTER TABLE mandat DROP COLUMN election_id, ADD INDEX ix_mandat_scrutin (scrutin_id)""")
        cle_etrangere("mandat", "scrutin_id", "scrutin")
        etape(f"mandat : scrutin_id ({n.sans[0]} élus d'une élection dont on ne connaît pas le tour, sur {n.n[0]})")

    # 4. candidature, liste : scrutin_id à la place de election_id + tour
    for t in ("candidature", "liste"):
        if "election_id" not in colonnes(t):
            continue
        mysql(f"""ALTER TABLE {t} ADD COLUMN scrutin_id INT NULL AFTER election_id;
                  UPDATE {t} x JOIN scrutin s ON s.election_id = x.election_id AND s.tour = x.tour SET x.scrutin_id = s.id;""")
        n = requete(f"SELECT sum(election_id IS NOT NULL AND scrutin_id IS NULL) perdus, sum(scrutin_id IS NULL) sans FROM {t}")
        if int(n.perdus[0] or 0):
            raise RuntimeError(f"{t} : {n.perdus[0]} lignes avec une élection mais sans scrutin (tour sans date ?)")
        mysql(f"""ALTER TABLE {t} DROP FOREIGN KEY fk_{t}_election_id;
                  ALTER TABLE {t} DROP COLUMN election_id, DROP COLUMN tour, ADD INDEX ix_{t}_scrutin (scrutin_id)""")
        cle_etrangere(t, "scrutin_id", "scrutin")
        etape(f"{t} : scrutin_id ({n.sans[0]} lignes sans élection, comme avant)")

    # 5. election : sans dates ; l'année et le libellé de l'élection (celui du 1er tour, sans « 1er tour »)
    if "date_t1" in colonnes("election"):
        mysql("""ALTER TABLE election ADD COLUMN annee SMALLINT NULL AFTER categorie_election_id,
                                      ADD COLUMN libelle VARCHAR(120) NULL AFTER annee;
                 UPDATE election SET annee = CAST(left(code, 4) AS UNSIGNED),
                   libelle = replace(replace(libelle_t1, ' – 1er tour', ''), ' – tour unique', '');
                 ALTER TABLE election DROP COLUMN date_t1, DROP COLUMN date_t2, DROP COLUMN libelle_t1, DROP COLUMN libelle_t2""")
        etape("election : sans dates (année et libellé)")
    etape(f"élections : fini en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    con = duckdb.connect(str(BASE), read_only=True)
    elections(con)
    con.close()
