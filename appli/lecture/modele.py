"""Le modèle « personnes et mandats » : MariaDB fait foi, l'appli en lit un instantané local (data/modele.duckdb).

À l'ouverture de la base, `brancher(con)` :
    1. si MariaDB (XAMPP) répond et a changé depuis l'instantané, recopie ses tables du modèle dans data/modele.duckdb
       (une vingtaine de secondes ; sinon rien) ;
    2. ouvre l'instantané sous le nom « modele » : l'appli lit directement modele.personne, modele.mandat,
       modele.candidature, modele.liste, modele.photo, modele.election…
Sans MariaDB (l'exe copié sur un autre PC), l'appli tourne sur le dernier instantané. Une correction faite dans
phpMyAdmin apparaît donc au lancement suivant de l'appli.
"""
import os
import json
import time
from pathlib import Path

import duckdb

INSTANTANE_NOM = "modele.duckdb"
TABLES = ["niveau", "zone", "commune", "bureau", "forme", "fonction", "fonction_duree", "incompatibilite", "categorie_election", "scrutin", "mode_scrutin", "motif_debut",
          "motif_fin", "election", "referentiel", "methode_identification", "personne", "identifiant", "mandat",
          "mandat_source", "groupe", "mandat_groupe", "motif_fin_groupe", "liste", "candidature", "photo", "photo_personne", "gouvernement",
          "nomination", "poste", "regime", "precision_date", "source", "licence", "position_vote", "bloc", "famille", "nuance", "nature_parti", "parti", "parti_membre", "ideologie", "parti_ideologie", "position_politique", "parti_position", "adhesion", "groupe_parti", "investiture", "axe", "ideologie_axe", "ecole", "promotion", "formation",
          "type_lien", "lien"]
MARIADB = f"host=127.0.0.1 user=root port={os.environ.get('GD_MARIADB_PORT', '3306')} database=grand_depouillement"


def empreinte_mariadb(c):
    """Ce qui change quand on modifie le modèle dans phpMyAdmin : la date de modification et le nombre de lignes de
    chaque table (après un redémarrage de MariaDB la date est vide, puis revient à la première modification)."""
    liste = ",".join(f"'{t}'" for t in TABLES)
    r = c.execute(f"""SELECT * FROM mysql_query('m', 'SELECT table_name, update_time, table_rows FROM information_schema.tables
                      WHERE table_schema = ''grand_depouillement'' AND table_name IN ({liste.replace("'", "''")})')""").fetchall()
    if len(r) < len(TABLES):
        return None
    return {t: [str(u), n] for t, u, n in r}


def rafraichir(dossier):
    """Recopie MariaDB → data/modele.duckdb si MariaDB répond et a changé. Renvoie un message (ou None si rien à faire)."""
    fichier = dossier / INSTANTANE_NOM
    marque = dossier / "modele_empreinte.json"
    try:
        c = duckdb.connect()
        c.execute("LOAD mysql")
        c.execute(f"ATTACH '{MARIADB}' AS m (TYPE mysql, READ_ONLY)")
    except Exception:          # (pas d'extension, ou MariaDB éteint : on garde l'instantané)
        return None
    try:
        e = empreinte_mariadb(c)
        if e is None:
            return None
        ancienne = json.loads(marque.read_text(encoding="utf-8")) if marque.exists() else None
        # (une table modifiée retrouve une date de modification : son empreinte change, on recopie)
        if fichier.exists() and ancienne == e:
            return None
        t0 = time.time()
        neuf = dossier / "modele_nouveau.duckdb"
        neuf.unlink(missing_ok=True)
        c.execute(f"ATTACH '{neuf.as_posix()}' AS n")
        for t in TABLES:
            c.execute(f"CREATE TABLE n.{t} AS SELECT * FROM m.{t}")
        c.execute("DETACH n")
        c.close()
        neuf.replace(fichier)
        marque.write_text(json.dumps(e), encoding="utf-8")
        return f"modèle recopié depuis MariaDB en {time.time() - t0:.0f} s"
    finally:
        try:
            c.close()
        except Exception:
            pass


def brancher(con, dossier, rafraichir_d_abord=True):
    """Ouvre l'instantané du modèle sous le nom « modele » (après l'avoir rafraîchi depuis MariaDB si possible)."""
    if rafraichir_d_abord:
        try:
            rafraichir(Path(dossier))
        except Exception:          # (un instantané un peu ancien vaut mieux qu'une appli qui ne démarre pas)
            pass
    fichier = Path(dossier) / INSTANTANE_NOM
    if fichier.exists():
        con.execute(f"ATTACH '{fichier.as_posix()}' AS modele (READ_ONLY)")
        return True
    return False
