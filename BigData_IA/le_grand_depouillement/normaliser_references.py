"""
normaliser_references.py — Le schéma v2 (conception/schema_v2.puml), appliqué à la base fabriquée : les territoires
deviennent une seule table zone (normaliser_zones.py), les valeurs répétées en texte des tables de référence + clés
étrangères (groupe…) — règle de Julien : jamais de VARCHAR pour une future clé étrangère.

    py normaliser_references.py          (l'appli fermée ; MariaDB de XAMPP démarré)

C'est la DERNIÈRE étape de la fabrication, à relancer après chaque reconstruction :
    preparer_donnees.py (→ brancher_modele.py) → construire_modele.py → integrer_*.py → exporter_mariadb.py
    → normaliser_references.py
Les scripts de fabrication lisent toujours les fichiers d'origine (en texte) ; ce script convertit ce qui est encore en
texte et laisse tel quel ce qui est déjà converti. Les tables de référence sont gardées d'une fois sur l'autre (un
groupe garde son numéro) ; une valeur nouvelle y est ajoutée.

Deux bases sont touchées :
  * MariaDB (grand_depouillement) : les tables du modèle (appartenance_groupe…) sont converties sur place ;
  * la base de l'appli (data/depouillement.duckdb) : ses tables (votes_individuels, sieges_legislature…) sont converties,
    puis recopiées dans MariaDB (exporter_mariadb.copier) avec leurs clés étrangères.
Les tables de référence vivent dans MariaDB ; l'appli les lit dans l'instantané du modèle (gd/modele.py TABLES).
Chaque table est sauvegardée dans PROJET/DECHET avant d'être convertie.
"""
import time
from pathlib import Path

import duckdb
import pandas as pd

import exporter_mariadb as ex
from gd import modele
from gd.parlement import GROUPES_SENAT
from outils_mariadb import charger, cle_etrangere, mysql, requete, sauvegarder

ICI = Path(__file__).resolve().parent
DATA = ICI / "data"
BASE = DATA / "depouillement.duckdb"
DECHET = ICI.parent.parent / "DECHET"
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
DEPUTE, SENATEUR = 14, 15                     # fonction


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def lire(sql, colonnes):
    """requete(), mais un tableau vide garde ses colonnes (le client mysql n'écrit rien, pas même l'en-tête)."""
    r = requete(sql)
    return r if len(r.columns) == len(colonnes) else pd.DataFrame(columns=colonnes)


def colonnes_mariadb(table):
    return set(requete(f"SHOW COLUMNS FROM `{table}`").Field) if len(requete(f"SHOW TABLES LIKE '{table}'")) else set()


def colonnes_duckdb(con, table):
    return {c for (c,) in con.execute(f"SELECT column_name FROM duckdb_columns() WHERE table_name = '{table}'").fetchall()}


def lien(table, colonne, reference):
    """La clé étrangère, si elle n'est pas déjà posée."""
    deja = requete(f"""SELECT count(*) n FROM information_schema.table_constraints WHERE table_schema = DATABASE()
                       AND table_name = '{table}' AND constraint_name = 'fk_{table}_{colonne}'""")
    if deja.n[0] == "0":
        cle_etrangere(table, colonne, reference)


def sauvegarder_duckdb(con, table, nom):
    """Une table de l'appli, telle qu'elle est avant d'être convertie, en Parquet dans PROJET/DECHET."""
    chemin = DECHET / f"{nom}_{time.strftime('%Y%m%d_%H%M')}.parquet"
    con.execute(f"COPY {table} TO '{chemin.as_posix()}' (FORMAT parquet)")
    return chemin


def recopier(con, tables, liens):
    """Recopie dans MariaDB des tables de l'appli converties, puis leurs clés étrangères [(table, colonne, référence)]."""
    for t in tables:
        ex.copier(con, t, f'"{t}"')
        if "personne_id" in colonnes_duckdb(con, t):     # (comme exporter_mariadb : le numéro de personne relié au modèle)
            mysql(f"ALTER TABLE `{t}` ADD INDEX `ix_personne` (`personne_id`)")
            lien(t, "personne_id", "personne")
    for t, c, r in liens:
        mysql(f"ALTER TABLE `{t}` ADD INDEX `ix_{c}` (`{c}`)")
        lien(t, c, r)


# ------------------------------------------------------------------------------------------------------------------
# groupe : les groupes parlementaires (code, libellé, couleur), par assemblée
# ------------------------------------------------------------------------------------------------------------------
# Un même code n'a pas toujours le même libellé ni la même couleur (« SOC » : Socialiste, Socialistes et apparentés…) :
# une ligne de groupe par combinaison rencontrée, sans fusionner des époques différentes.
def groupe(con):
    mysql(f"""CREATE TABLE IF NOT EXISTS groupe (id INT NOT NULL PRIMARY KEY, fonction_id INT NOT NULL,
                code VARCHAR(40) NOT NULL, libelle VARCHAR(100) NOT NULL, couleur VARCHAR(7) NULL,
                KEY ix_groupe_code (fonction_id, code),
                CONSTRAINT fk_groupe_fonction_id FOREIGN KEY (fonction_id) REFERENCES fonction (id)) {T}""")
    deja = lire("SELECT id, fonction_id, code, libelle, couleur FROM groupe", ["id", "fonction_id", "code", "libelle", "couleur"])
    deja = deja.astype({"id": int, "fonction_id": int})
    cle = lambda f, c, l, k: (int(f), c, l, k if isinstance(k, str) and k else None)
    connus = {cle(r.fonction_id, r.code, r.libelle, r.couleur): r.id for r in deja.itertuples()}

    def ajouter(f, code, lib, coul):
        k = cle(f, code, lib, coul)
        if k not in connus:
            connus[k] = max(connus.values(), default=0) + 1
        return connus[k]

    # 1. les appartenances du modèle (code, libellé, couleur ; les sénateurs : libellé et couleur de GROUPES_SENAT)
    a_convertir = "groupe" in colonnes_mariadb("appartenance_groupe")
    if a_convertir:
        a = requete("""SELECT g.id, m.fonction_id, g.groupe code, g.groupe_libelle libelle, g.couleur
                       FROM appartenance_groupe g JOIN mandat m ON m.id = g.mandat_id""")
        a["libelle"] = a.libelle.fillna(a.code)
        senat = (a.fonction_id == str(SENATEUR)) & a.couleur.isna() & (a.libelle == a.code) & a.code.isin(GROUPES_SENAT)
        a.loc[senat, "libelle"] = a.code[senat].map(lambda g: GROUPES_SENAT[g][0])
        a.loc[senat, "couleur"] = a.code[senat].map(lambda g: GROUPES_SENAT[g][1])
        a["groupe_id"] = [ajouter(f, c, l, k) for f, c, l, k in zip(a.fonction_id, a.code, a.libelle, a.couleur)]
    for g, (lib, coul) in GROUPES_SENAT.items():          # (les groupes du Sénat d'aujourd'hui, même sans sénateur lu)
        ajouter(SENATEUR, g, lib, coul)

    # 2. les votes et les sièges des législatures (code et couleur seulement) : le groupe de l'Assemblée de même code et
    #    même couleur — celui dont le libellé est le code s'il y en a plusieurs —, sinon un nouveau (libellé = code)
    a_recopier = [t for t in ("votes_individuels", "sieges_legislature") if "groupe" in colonnes_duckdb(con, t)]
    paires = set()
    for t in a_recopier:
        paires |= set(con.execute(f"SELECT DISTINCT groupe, couleur FROM {t} WHERE groupe IS NOT NULL").fetchall())
    carte = {}         # (code, couleur) → groupe_id (« » et vide : la même couleur absente)
    for code, coul in sorted(paires, key=str):
        coul = coul if isinstance(coul, str) and coul else None
        if (code, coul) in carte:
            continue
        memes = [(k, i) for k, i in connus.items() if k[0] == DEPUTE and k[1] == code and k[3] == coul]
        choix = [i for k, i in memes if k[2] == code] or ([memes[0][1]] if len(memes) == 1 else [])
        carte[code, coul] = choix[0] if choix else ajouter(DEPUTE, code, code, coul)

    # 3. la table groupe complétée
    nouveaux = [(i, *k) for k, i in connus.items() if i not in set(deja.id)]
    if nouveaux:
        charger("groupe", pd.DataFrame(nouveaux, columns=["id", "fonction_id", "code", "libelle", "couleur"]))
    etape(f"groupe : {len(connus)} groupes ({len(nouveaux)} nouveaux)")

    # 4. appartenance_groupe (MariaDB) : groupe_id à la place de groupe, groupe_libelle, couleur
    if a_convertir:
        sauvegarder(DECHET, "appartenance_groupe_avant_groupe_id", ["appartenance_groupe"])
        mysql(f"""DROP TABLE IF EXISTS tmp_groupe; CREATE TABLE tmp_groupe (id BIGINT PRIMARY KEY, groupe_id INT) {T}""")
        charger("tmp_groupe", a[["id", "groupe_id"]])
        mysql("""ALTER TABLE appartenance_groupe ADD COLUMN groupe_id INT NULL AFTER mandat_id;
                 UPDATE appartenance_groupe g JOIN tmp_groupe t ON t.id = g.id SET g.groupe_id = t.groupe_id;
                 ALTER TABLE appartenance_groupe DROP COLUMN groupe, DROP COLUMN groupe_libelle, DROP COLUMN couleur;
                 DROP TABLE tmp_groupe""")
        lien("appartenance_groupe", "groupe_id", "groupe")
        etape(f"appartenance_groupe : {len(a)} lignes reliées à groupe")

    # 5. votes_individuels et sieges_legislature (base de l'appli), puis leur copie dans MariaDB
    if a_recopier:
        con.register("carte_df", pd.DataFrame([(c, k, i) for (c, k), i in carte.items()], columns=["code", "couleur", "groupe_id"]))
        con.execute("CREATE OR REPLACE TEMP TABLE carte_groupe AS SELECT code::VARCHAR code, couleur::VARCHAR couleur, "
                    "groupe_id::INTEGER groupe_id FROM carte_df")
        con.unregister("carte_df")
        for t in a_recopier:
            sauvegarder_duckdb(con, t, f"{t}_avant_groupe_id")
            n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            con.execute(f"""CREATE OR REPLACE TABLE {t} AS
                            SELECT x.* EXCLUDE (groupe, couleur), c.groupe_id FROM {t} x
                            LEFT JOIN carte_groupe c ON c.code = x.groupe AND c.couleur IS NOT DISTINCT FROM nullif(x.couleur, '')""")
            assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == n, f"{t} : nombre de lignes changé"
        con.execute("DROP TABLE carte_groupe")
        recopier(con, a_recopier, [(t, "groupe_id", "groupe") for t in a_recopier])
        etape(f"{', '.join(a_recopier)} : groupe_id")


def zones(con):
    import normaliser_zones                    # (normaliser_zones se sert des outils d'ici)
    normaliser_zones.zones(con)


def elections(con):
    import normaliser_elections
    normaliser_elections.elections(con)


def mandats(con):
    import normaliser_mandats
    normaliser_mandats.mandats(con)


def tours(con):
    import deduire_tours
    deduire_tours.deduire(con)


def votes(con):
    import normaliser_votes
    normaliser_votes.votes(con)


def resultats(con):
    import normaliser_resultats
    normaliser_resultats.resultats(con)


def libelles(con):
    import normaliser_libelles
    normaliser_libelles.libelles(con)


def nuances(con):
    import normaliser_nuances
    normaliser_nuances.nuances(con)


def partis(con):
    import integrer_partis              # (partis, coalitions, idéologies, adhésions, puis investitures : refaits à chaque fois)
    integrer_partis.main()


def relier(con):
    import relier_resultats
    relier_resultats.relier(con)


ETAPES = [zones, elections, tours, groupe, mandats, votes, resultats, nuances, libelles, partis, relier]

if __name__ == "__main__":
    t0 = time.time()
    con = duckdb.connect(str(BASE))
    for f in ETAPES:
        f(con)
    con.execute("CHECKPOINT")
    con.close()
    etape(modele.rafraichir(DATA) or "instantané du modèle déjà à jour")
    etape(f"fini en {time.time() - t0:.0f} s")
