"""
normaliser_mandats.py — Les mandats du schéma v2 : les groupes d'un mandat (mandat_groupe) et le mandat remplacé.

    py normaliser_mandats.py          (l'appli fermée ; MariaDB de XAMPP démarré)

Lancé par normaliser_references.py (après zones, élections et groupes) ; relançable.

    mandat_groupe (id, mandat_id, groupe_id, date_debut, date_fin, motif_fin_groupe_id)   remplace appartenance_groupe
        un député réélu 5 fois = 5 lignes (les groupes sont refaits à chaque législature) ; transfuge, exclu = plusieurs
        lignes datées dans le même mandat. Motif de fin, quand les dates le disent sans rien inventer : fin de législature
        (le groupe finit avec un mandat arrivé à son terme ou dissous), fin du mandat (il finit avec un mandat interrompu) ;
        sinon vide (changement de groupe dont la source ne dit pas la raison).
    mandat.remplace_mandat_id → mandat              le suppléant (ou le suivant de liste) remplace le titulaire
        relié quand c'est sans ambiguïté : un mandat entré en cours de mandat, et UN SEUL mandat de la même fonction, sur
        la même zone, fini dans le mois avant (et lui-même remplacé une seule fois) ; un député élu 45 à 60 jours après
        le départ de l'autre est le vainqueur d'une élection partielle : il succède, il ne remplace pas.
"""
import time

from outils_mariadb import cle_etrangere, mysql, requete, sauvegarder
from normaliser_elections import DECHET, T, colonnes, etape

MOTIFS_FIN_GROUPE = [(1, "fin de législature"), (2, "départ volontaire"), (3, "exclusion"),
                     (4, "création d'un nouveau groupe"), (5, "dissolution du groupe"), (6, "fin du mandat")]
ENTREE_EN_COURS = 4                          # (motif_debut : entrée en cours de mandat — suivant de liste, suppléant…)
TERME, DISSOLUTION = 1, 6                    # (motif_fin)


def contrainte(nom):
    return bool(len(requete(f"""SELECT constraint_name FROM information_schema.table_constraints
                                WHERE table_schema = DATABASE() AND constraint_name = '{nom}'""")))


def mandats(con=None):
    t0 = time.time()
    # 1. mandat_groupe (remplace appartenance_groupe), avec le motif de fin quand les dates le disent
    mysql(f"""CREATE TABLE IF NOT EXISTS motif_fin_groupe (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(40) NOT NULL) {T};
              INSERT IGNORE INTO motif_fin_groupe VALUES """
          + ", ".join(f"({i}, '{l.replace(chr(39), chr(39) * 2)}')" for i, l in MOTIFS_FIN_GROUPE) + ";")
    if colonnes("appartenance_groupe") and "groupe_id" in colonnes("appartenance_groupe"):
        etape("sauvegarde : " + sauvegarder(DECHET, "avant_mandat_groupe", ["appartenance_groupe"]).name)
        mysql("""ALTER TABLE appartenance_groupe DROP FOREIGN KEY fk_appartenance_groupe_groupe_id,
                                                 DROP FOREIGN KEY fk_appartenance_groupe_mandat_id;
                 RENAME TABLE appartenance_groupe TO mandat_groupe;
                 ALTER TABLE mandat_groupe ADD COLUMN motif_fin_groupe_id INT NULL AFTER date_fin""")
        cle_etrangere("mandat_groupe", "mandat_id", "mandat")
        cle_etrangere("mandat_groupe", "groupe_id", "groupe")
    if "motif_fin_groupe_id" in colonnes("mandat_groupe"):
        mysql(f"""UPDATE mandat_groupe g JOIN mandat m ON m.id = g.mandat_id
                  SET g.motif_fin_groupe_id = CASE WHEN m.motif_fin_id IN ({TERME}, {DISSOLUTION}) THEN 1 ELSE 6 END
                  WHERE g.motif_fin_groupe_id IS NULL AND g.date_fin IS NOT NULL AND g.date_fin = m.date_fin""")
        if not contrainte("fk_mandat_groupe_motif_fin_groupe_id"):
            cle_etrangere("mandat_groupe", "motif_fin_groupe_id", "motif_fin_groupe")
        n = requete("""SELECT count(*) n, sum(date_fin IS NULL) en_cours, sum(motif_fin_groupe_id IS NOT NULL) motif
                       FROM mandat_groupe""")
        etape(f"mandat_groupe : {n.n[0]} lignes ({n.en_cours[0]} en cours, {n.motif[0]} avec un motif de fin)")

    # 2. le mandat remplacé
    if "remplace_mandat_id" not in colonnes("mandat"):
        mysql("ALTER TABLE mandat ADD COLUMN remplace_mandat_id BIGINT NULL AFTER motif_fin_id, ADD INDEX ix_mandat_remplace (remplace_mandat_id)")
    mysql(f"""DROP TABLE IF EXISTS tmp_remplace;
              CREATE TABLE tmp_remplace (b BIGINT, a BIGINT, KEY (b), KEY (a)) {T};
              INSERT INTO tmp_remplace
              SELECT b.id, a.id FROM mandat b JOIN mandat a ON a.fonction_id = b.fonction_id AND a.zone_id = b.zone_id
                AND a.id <> b.id AND a.date_fin BETWEEN b.date_debut - INTERVAL 31 DAY AND b.date_debut
                AND (a.date_debut IS NULL OR a.date_debut < b.date_debut)
              WHERE b.motif_debut_id = {ENTREE_EN_COURS} AND b.remplace_mandat_id IS NULL
                AND coalesce(a.motif_fin_id, 0) NOT IN ({TERME}, {DISSOLUTION});
              UPDATE mandat m JOIN (SELECT b, min(a) a FROM tmp_remplace GROUP BY b HAVING count(*) = 1) x ON x.b = m.id
                JOIN (SELECT a FROM tmp_remplace GROUP BY a HAVING count(*) = 1) y ON y.a = x.a
              SET m.remplace_mandat_id = x.a;
              DROP TABLE tmp_remplace""")
    if not contrainte("fk_mandat_remplace_mandat_id"):
        cle_etrangere("mandat", "remplace_mandat_id", "mandat")
    n = requete(f"""SELECT count(*) n, sum(remplace_mandat_id IS NOT NULL) relies FROM mandat WHERE motif_debut_id = {ENTREE_EN_COURS}""")
    etape(f"mandat : {n.relies[0]} remplaçants reliés au mandat qu'ils remplacent, sur {n.n[0]} entrés en cours de mandat")
    etape(f"mandats : fini en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    mandats()
