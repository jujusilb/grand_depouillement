"""
exporter_mariadb.py — Copie la base de l'appli (data/depouillement.duckdb) dans MariaDB, pour la parcourir avec phpMyAdmin.

    py exporter_mariadb.py                 (toutes les tables ; MariaDB de XAMPP démarré, utilisateur root sans mot de passe)
    py exporter_mariadb.py resultats rne_municipaux   (seulement ces tables)
    py exporter_mariadb.py --adresses      (ajoute aussi data/adresses.parquet : 16 millions d'adresses, ~10 minutes de plus)

L'appli continue de lire DuckDB : MariaDB n'est qu'une copie, à refaire quand la base change. Base créée : grand_depouillement
(les autres bases du serveur ne sont pas touchées ; une table déjà copiée est remplacée).

Pour chaque table : les colonnes et leurs types traduits (texte court → VARCHAR à la bonne longueur, texte long → TEXT,
vrai/faux → TINYINT(1), dates → DATETIME), une clé « id » (phpMyAdmin en a besoin pour modifier une ligne), les lignes
envoyées par blocs de 2 millions (DuckDB écrit un fichier, MariaDB le charge avec LOAD DATA), puis les index utiles et
le nombre de lignes vérifié.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import duckdb

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
BASE = C.BASE
ADRESSES = C.DONNEES_APPLI / "adresses.parquet"
MYSQL = Path(os.environ.get("GD_MYSQL", r"C:\xampp\mysql\bin\mysql.exe"))     # (GD_MYSQL : le MariaDB portable de l'installation)
CONNEXION = ["-u", "root", "-h", "127.0.0.1", "-P", os.environ.get("GD_MARIADB_PORT", "3306")]   # (en TCP : XAMPP ou le portable)
CIBLE = "grand_depouillement"
BLOC = 2_000_000
# (après brancher_modele.py : ces tables de DuckDB gardent un numéro de personne, relié à personne dans MariaDB)
RELIEES = {"votes_individuels": "votes_individuels", "sieges_legislature": "sieges_legislature"}
# les tables qui écrivaient les personnes en dur, remplacées par le modèle personne / mandat (voir construire_modele.py)
ANCIENNES = ["deputes", "senateurs", "mandats_deputes", "groupes_deputes", "sieges_legislature", "votes_individuels",
             "candidats_details", "candidats_listes", "elus_municipaux_2014", "rne_municipaux", "rne_communautaires",
             "rne_departementaux", "rne_regionaux", "rne_arrondissements"]

# les index qui rendent la navigation rapide (une table absente est sautée)
INDEX = {
    "resultats": [("scrutin", "id_brut_miom"), ("qui",)],
    "participation": [("scrutin", "id_brut_miom"), ("code_commune",), ("code_departement",)],
    "candidats_listes": [("election", "code_zone"), ("nom",)],
    "candidats_details": [("scrutin",), ("nom",)],
    "rne_municipaux": [("version", "code_commune"), ("nom",)],
    "rne_communautaires": [("version", "siren"), ("code_commune",)],
    "elus_municipaux_2014": [("code_commune",), ("nom",)],
    "sieges_figes": [("calcul", "scrutin", "zone")],
    "votes_individuels": [("scrutin",), ("depute",)],
    "populations": [("code_commune", "annee")],
    "contours": [("niveau", "code")],
    "geo_bureau": [("id_brut_miom",), ("commune",)],
    "geo_commune": [("code",)],
    "sieges_2026": [("code_commune",), ("siren_epci",)],
    "adresses": [("id_brut_miom",), ("code_commune",)],
}


def mysql(sql, base=CIBLE):
    """Une commande SQL dans MariaDB (avec le client de XAMPP : rien à installer)."""
    # (le SQL passe par l'entrée standard, en UTF-8 : la ligne de commande de Windows abîmerait les accents — « député »)
    r = subprocess.run([str(MYSQL), *CONNEXION, "--local-infile=1", "--default-character-set=utf8mb4", *([base] if base else [])],
                       input=sql, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:500])
    return r.stdout


def type_mariadb(con, source, colonne, type_duck):
    t = type_duck.upper()
    if t in ("VARCHAR", "TEXT") or t.startswith("VARCHAR"):
        n = con.execute(f'SELECT coalesce(max(length("{colonne}")), 1) FROM {source}').fetchone()[0]
        if n <= 255:
            return f"VARCHAR({max(int(n), 1)})"
        return "TEXT" if n < 16_000 else "MEDIUMTEXT" if n < 4_000_000 else "LONGTEXT"     # (en caractères ; utf8mb4 = 4 octets)
    if t == "BOOLEAN":
        return "TINYINT(1)"
    if t.startswith("TIMESTAMP") or t == "DATE":
        return "DATETIME(6)" if t.startswith("TIMESTAMP") else "DATE"
    if t in ("HUGEINT", "BIGINT", "UBIGINT"):
        return "BIGINT"
    if t in ("INTEGER", "UINTEGER"):
        return "INT"
    if t in ("SMALLINT", "TINYINT", "USMALLINT", "UTINYINT"):
        return "SMALLINT"
    if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
        return "DOUBLE"
    return "TEXT"


def selection(colonnes):
    """Ce que DuckDB écrit pour chaque colonne : vrai/faux en 1/0, dates au format de MariaDB, le reste tel quel."""
    morceaux = []
    for nom, t in colonnes:
        q = f'"{nom}"'
        t = t.upper()
        if t == "BOOLEAN":
            morceaux.append(f"CAST({q} AS INTEGER) AS {q}")
        elif t.startswith("TIMESTAMP"):
            morceaux.append(f"strftime({q}, '%Y-%m-%d %H:%M:%S.%f') AS {q}")
        elif t == "HUGEINT":
            morceaux.append(f"CAST({q} AS BIGINT) AS {q}")
        else:
            morceaux.append(q)
    return ", ".join(morceaux)


def copier(con, nom, source):
    t0 = time.time()
    colonnes = con.execute(f"SELECT column_name, column_type FROM (DESCRIBE {source})").fetchall()
    types = [(c, type_mariadb(con, source, c, t)) for c, t in colonnes]
    defs = ",\n  ".join(f"`{c}` {t} NULL" for c, t in types)
    cle = "id_ligne" if any(c.lower() == "id" for c, _ in colonnes) else "id"      # (deputes a déjà sa colonne « id »)
    mysql(f"DROP TABLE IF EXISTS `{nom}`; CREATE TABLE `{nom}` (\n  `{cle}` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,\n  {defs}\n)"
          " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci")
    n = con.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
    textes = [c for c, t in colonnes if t.upper().startswith("VARCHAR") or t.upper() == "VARCHAR"]
    liste = ", ".join(f"`{c}`" for c, _ in colonnes)
    with tempfile.TemporaryDirectory() as dossier:
        fichier = Path(dossier) / f"{nom}.tsv"
        for debut in range(0, max(n, 1), BLOC):
            # (tabulation, textes entre guillemets — un vrai mot « NULL » reste donc du texte —, NULL sans guillemets)
            force = f", FORCE_QUOTE ({', '.join(chr(34) + c + chr(34) for c in textes)})" if textes else ""
            con.execute(f"""COPY (SELECT {selection(colonnes)} FROM {source} LIMIT {BLOC} OFFSET {debut})
                            TO '{fichier.as_posix()}' (FORMAT csv, DELIMITER '\t', QUOTE '"', ESCAPE '"', NULLSTR 'NULL',
                            HEADER false{force})""")
            mysql(f"""SET unique_checks = 0; SET foreign_key_checks = 0;
                      LOAD DATA LOCAL INFILE '{fichier.as_posix()}' INTO TABLE `{nom}` CHARACTER SET utf8mb4
                      FIELDS TERMINATED BY '\\t' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '' LINES TERMINATED BY '\\n' ({liste})""")
            if n > BLOC:
                print(f"      {min(debut + BLOC, n):>11,} / {n:,}".replace(",", " "), flush=True)
    for cols in INDEX.get(nom, []):
        if all(c in dict(colonnes) for c in cols):
            # (un index sur un TEXT doit dire combien de caractères il prend)
            parts = ", ".join(f"`{c}`(64)" if dict(types)[c] in ("TEXT", "MEDIUMTEXT", "LONGTEXT") else f"`{c}`" for c in cols)
            mysql(f"ALTER TABLE `{nom}` ADD INDEX `ix_{'_'.join(cols)}` ({parts})")
    copie = int(mysql(f"SELECT count(*) FROM `{nom}`").split()[-1])
    etat = "ok" if copie == n else f"ÉCART : {n - copie} lignes manquent"
    print(f"   {nom:24s} {n:>12,} lignes  {time.time() - t0:7.1f} s  {etat}".replace(",", " "), flush=True)
    return copie == n


if __name__ == "__main__":
    demandes = [a for a in sys.argv[1:] if not a.startswith("--")]
    mysql(f"CREATE DATABASE IF NOT EXISTS `{CIBLE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci", base="")
    con = duckdb.connect(str(BASE), read_only=True)
    tables = [t for (t,) in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY estimated_size").fetchall()]
    tables = [t for t in tables if not demandes or t in demandes]
    # les anciennes tables qui écrivaient les personnes en dur n'ont plus leur place dans MariaDB : sauvegarde, puis retrait
    # (votes_individuels et sieges_legislature : seulement leur ancienne forme, celle qui a une colonne « depute »)
    def ancienne_forme(t):
        existe = int(mysql(f"SELECT count(*) FROM information_schema.tables WHERE table_schema = '{CIBLE}' AND table_name = '{t}'").split()[-1])
        if not existe or t not in RELIEES.values():
            return bool(existe)
        return bool(int(mysql(f"SELECT count(*) FROM information_schema.columns WHERE table_schema = '{CIBLE}' "
                              f"AND table_name = '{t}' AND column_name = 'depute'").split()[-1]))
    restes = [t for t in ANCIENNES if ancienne_forme(t)]
    if restes and not demandes:
        sauvegarde = C.DECHET / f"anciennes_tables_{time.strftime('%Y%m%d_%H%M')}.sql"
        sauvegarde.parent.mkdir(parents=True, exist_ok=True)
        with open(sauvegarde, "w", encoding="utf-8") as f:
            subprocess.run([str(MYSQL.parent / "mysqldump.exe"), *CONNEXION, "--default-character-set=utf8mb4", CIBLE, *restes],
                           stdout=f, check=True)
        mysql("SET foreign_key_checks = 0; " + " ".join(f"DROP TABLE `{t}`;" for t in restes))
        print(f"Retirées de MariaDB (sauvegarde {sauvegarde.name} dans DECHET) : {', '.join(restes)}")
    debut, ok = time.time(), True
    print(f"Copie de {len(tables)} tables dans MariaDB ({CIBLE})…")
    for t in tables:
        nom = RELIEES.get(t, t)
        ok &= copier(con, nom, f'"{t}"')
        if t in RELIEES:          # (votes et sièges : un numéro de personne, relié à la table personne du modèle)
            mysql(f"SET foreign_key_checks = 0; ALTER TABLE `{nom}` ADD INDEX `ix_personne` (`personne_id`), "
                  f"ADD CONSTRAINT `fk_{nom}_personne_id` FOREIGN KEY (`personne_id`) REFERENCES `personne` (`id`)")
    if "--adresses" in sys.argv and ADRESSES.exists():
        ok &= copier(con, "adresses", f"read_parquet('{ADRESSES.as_posix()}')")
    print(f"Terminé en {(time.time() - debut) / 60:.0f} min — " + ("toutes les lignes sont là." if ok else "des lignes manquent (voir ÉCART)."))
    print("phpMyAdmin : http://localhost/phpmyadmin, base « grand_depouillement ».")
