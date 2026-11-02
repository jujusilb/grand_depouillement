"""
normaliser_votes.py — Les votes de l'Assemblée du schéma v2 (un « vote » : les députés votent une loi, une censure ;
un « scrutin » : la population vote).

    py normaliser_votes.py          (l'appli fermée ; MariaDB de XAMPP démarré)

Lancé par normaliser_references.py ; relançable. Dans la base de l'appli (data/depouillement.duckdb), puis recopié
dans MariaDB avec les clés étrangères :
    legislature (id = son numéro, date_debut, date_fin, sieges, source_id)          remplace legislatures
        (le chiffre romain et les comptes de sièges connus se calculent : plus de colonnes romain, sieges_lus, deputes_connus)
    vote (id, code « AN16-00001 », legislature_id, date, objet, pour, contre, abstention, source_id, complet, pour_lus,
          contre_lus)                                                               remplace votes_scrutins
    vote_depute (id, vote_id, personne_id, nom_non_identifie, position_id, groupe_id, circonscription_id)
                                                                                    remplace votes_individuels
        la circonscription (« 1re circonscription · Ain », 577 textes répétés) devient une zone (découpage de 2012 : les
        votes nominatifs commencent en 2012).
Dans MariaDB (le modèle) : position_vote (pour, contre, abstention, non-votant) et les sources des votes et des
législatures dans la table source.
Défaut de la source repéré : le code AN16-00001 sert à deux votes (censure du 11/07/2022 et Congrès du 04/03/2024) ;
le Congrès prend le code CONGRES2024, ses votes individuels restent mêlés à ceux de la censure (à refaire depuis
l'open data du Congrès).
"""
import re
import time
from pathlib import Path

import duckdb
import pandas as pd

from normaliser_references import lien, recopier, sauvegarder_duckdb
from outils_mariadb import mysql, norm, requete, sources

ICI = Path(__file__).resolve().parent
BASE = ICI / "data" / "depouillement.duckdb"
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
POSITIONS = [(1, "pour"), (2, "contre"), (3, "abstention"), (4, "non-votant")]
SOURCES_VOTES = {"open data de l'Assemblée": "votes : open data de l'Assemblée",
                 "site de l'Assemblée": "votes : site de l'Assemblée",
                 "Journal officiel (PDF numérisé)": "votes : Journal officiel"}
CIRCO, DEPARTEMENT = 5, 3                     # (niveaux de zone)
DECOUPAGE_2012 = "2012-06-10"
AUTRES_NOMS = {"SAINTBARTHELEMYETSAINTMARTIN": "ZX", "REUNION": "ZD"}


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def existe(con, t):
    return con.execute(f"SELECT count(*) FROM duckdb_tables() WHERE table_name = '{t}'").fetchall()[0][0] > 0


def votes(con):
    t0 = time.time()
    mysql(f"""CREATE TABLE IF NOT EXISTS position_vote (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(20) NOT NULL) {T};
              INSERT IGNORE INTO position_vote VALUES """ + ", ".join(f"({i}, '{l}')" for i, l in POSITIONS) + ";")

    # 1. legislature (remplace legislatures)
    if existe(con, "legislatures"):
        sauvegarder_duckdb(con, "legislatures", "legislatures_avant_v2")
        cles = {s: f"législatures : {s}" for (s,) in con.execute("SELECT DISTINCT source FROM legislatures").fetchall()}
        ids = sources(list(cles.values()))
        con.register("src", pd.DataFrame([(s, ids[c]) for s, c in cles.items()], columns=["source", "source_id"]))
        con.execute("""CREATE OR REPLACE TABLE legislature AS
                       SELECT l.legislature::INTEGER id, l.debut::DATE date_debut, l.fin::DATE date_fin, l.sieges,
                              s.source_id::INTEGER source_id
                       FROM legislatures l LEFT JOIN src s USING (source) ORDER BY 1""")
        con.unregister("src")
        con.execute("DROP TABLE legislatures")
        recopier(con, ["legislature"], [("legislature", "source_id", "source")])
        mysql("SET foreign_key_checks = 0; ALTER TABLE legislature DROP COLUMN id_ligne, ADD PRIMARY KEY (id)")
        etape(f"legislature : {con.execute('SELECT count(*) FROM legislature').fetchall()[0][0]} législatures")

    # 2. vote (remplace votes_scrutins)
    if existe(con, "votes_scrutins"):
        sauvegarder_duckdb(con, "votes_scrutins", "votes_scrutins_avant_v2")
        ids = sources(list(SOURCES_VOTES.values()))
        con.register("src", pd.DataFrame([(s, ids[c]) for s, c in SOURCES_VOTES.items()], columns=["source", "source_id"]))
        con.execute("""CREATE OR REPLACE TABLE vote AS
                       SELECT row_number() OVER (ORDER BY v.date, v.scrutin)::INTEGER id,
                              CASE WHEN v.scrutin = 'AN16-00001' AND v.pour + v.contre + v.abstention > 577 THEN 'CONGRES2024'
                                   ELSE v.scrutin END code,
                              v.legislature::INTEGER legislature_id, v.date::DATE date, v.objet, v.pour, v.contre, v.abstention,
                              s.source_id::INTEGER source_id, v.complet, v.pour_lus, v.contre_lus
                       FROM votes_scrutins v LEFT JOIN src s USING (source)""")
        con.unregister("src")
        sans = con.execute("SELECT count(*) FROM vote WHERE source_id IS NULL").fetchall()[0][0]
        doubles = con.execute("SELECT count(*) - count(DISTINCT code) FROM vote").fetchall()[0][0]
        if sans or doubles:
            raise RuntimeError(f"vote : {sans} sans source, {doubles} codes en double")
        con.execute("DROP TABLE votes_scrutins")
        recopier(con, ["vote"], [("vote", "source_id", "source")])
        mysql("""SET foreign_key_checks = 0; ALTER TABLE vote DROP COLUMN id_ligne, ADD PRIMARY KEY (id),
                 ADD UNIQUE KEY ix_vote_code (code), ADD INDEX ix_legislature (legislature_id);
                 ALTER TABLE vote ADD CONSTRAINT fk_vote_legislature_id FOREIGN KEY (legislature_id) REFERENCES legislature (id)""")
        etape(f"vote : {con.execute('SELECT count(*) FROM vote').fetchall()[0][0]} votes")

    # 3. vote_depute (remplace votes_individuels) : vote_id, position_id, circonscription_id
    if existe(con, "votes_individuels"):
        sauvegarder_duckdb(con, "votes_individuels", "votes_individuels_avant_v2")
        z = requete(f"""SELECT c.id, c.code, d.libelle dep, d.code dep_code FROM zone c JOIN zone d ON d.id = c.parent_id
                        WHERE c.niveau_id = {CIRCO} AND c.date_debut = '{DECOUPAGE_2012}'""")
        par_dep = {}
        for i, code, dep, dep_code in z.itertuples(index=False):
            par_dep[(norm(dep), int(code.split("-")[1]))] = int(i)
            par_dep[(dep_code, int(code.split("-")[1]))] = int(i)
        lieux = [l for (l,) in con.execute("SELECT DISTINCT lieu FROM votes_individuels WHERE lieu IS NOT NULL").fetchall()]
        carte = []
        for l in lieux:
            m = re.fullmatch(r"(\d+)(?:re|e) circonscription · (.+)", l)
            cle = (AUTRES_NOMS.get(norm(m[2]), norm(m[2])), int(m[1])) if m else None
            carte.append((l, par_dep.get(cle) or par_dep.get((AUTRES_NOMS.get(norm(m[2])), int(m[1]))) if m else None))
        perdus = [l for l, i in carte if i is None]
        if perdus:
            raise RuntimeError(f"vote_depute : circonscriptions non retrouvées : {perdus[:5]}")
        con.register("lieux", pd.DataFrame(carte, columns=["lieu", "circonscription_id"]))
        con.register("positions", pd.DataFrame(POSITIONS, columns=["position_id", "position"]))
        con.execute("""CREATE OR REPLACE TABLE vote_depute AS
                       SELECT row_number() OVER ()::BIGINT id, v.id::INTEGER vote_id, x.personne_id, x.nom_non_identifie,
                              p.position_id::INTEGER position_id, x.groupe_id::INTEGER groupe_id,
                              l.circonscription_id::INTEGER circonscription_id
                       FROM votes_individuels x
                       JOIN (SELECT id, CASE code WHEN 'CONGRES2024' THEN 'AN16-00001-congres' ELSE code END code FROM vote) v
                         ON v.code = x.scrutin
                       LEFT JOIN positions p ON p.position = x.position LEFT JOIN lieux l ON l.lieu = x.lieu""")
        n0 = con.execute("SELECT count(*) FROM votes_individuels").fetchall()[0][0]
        n1 = con.execute("SELECT count(*) FROM vote_depute").fetchall()[0][0]
        if n0 != n1:
            raise RuntimeError(f"vote_depute : {n0 - n1} votes perdus")
        con.unregister("lieux")
        con.unregister("positions")
        con.execute("DROP TABLE votes_individuels")
        import exporter_mariadb as ex
        ex.copier(con, "vote_depute", '"vote_depute"')
        mysql("SET foreign_key_checks = 0; ALTER TABLE vote_depute DROP COLUMN id_ligne, ADD PRIMARY KEY (id), ADD INDEX ix_personne (personne_id)")
        lien("vote_depute", "personne_id", "personne")
        recopier(con, [], [("vote_depute", "vote_id", "vote"), ("vote_depute", "position_id", "position_vote"),
                                        ("vote_depute", "groupe_id", "groupe"), ("vote_depute", "circonscription_id", "zone")])
        if len(requete("SHOW TABLES LIKE 'votes_individuels'")):
            mysql("SET foreign_key_checks = 0; DROP TABLE votes_individuels; DROP TABLE IF EXISTS votes_scrutins; "
                  "DROP TABLE IF EXISTS legislatures")
        etape(f"vote_depute : {n1} votes de députés")
    etape(f"votes : fini en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    con = duckdb.connect(str(BASE))
    votes(con)
    con.execute("CHECKPOINT")
    con.close()
