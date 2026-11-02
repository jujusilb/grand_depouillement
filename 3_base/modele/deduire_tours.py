"""
deduire_tours.py — Le tour où un élu a été élu, déduit des résultats officiels (participation) quand sa candidature ne
le dit pas : les mandats rattachés à un scrutin « tour inconnu » (normaliser_elections.py) passent au bon tour.

    py deduire_tours.py          (lancé aussi par normaliser_references.py ; relançable)

Règles sûres (rien n'est inventé) :
  * un siège par zone (canton des départementales) : un 2nd tour a eu lieu dans le canton → élu au 2nd ; sinon au 1er ;
  * municipales, commune à listes (des listes déposées dans le modèle) : un 2nd tour a eu lieu dans la commune → toute la
    liste est élue au 2nd (la prime et la répartition se font au tour décisif) ; sinon au 1er.
Les petites communes (candidats un par un) gardent « tour inconnu » quand il y a eu un 2nd tour : une partie des
sièges a pu être pourvue au 1er.
"""
import time
import sys
from pathlib import Path

import duckdb

from outils_mariadb import charger, mysql, requete

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
CANTON, COMMUNE, SECTEUR = 6, 8, 10                  # (niveaux de zone)


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def deduire(con):
    avant = int(requete("SELECT count(*) n FROM mandat m JOIN scrutin s ON s.id = m.scrutin_id WHERE s.tour IS NULL").n[0])
    textes = {c for (c,) in con.execute("SELECT column_name FROM duckdb_columns() WHERE table_name = 'participation'").fetchall()}
    if not avant or "scrutin" not in textes:      # (participation déjà rangée par scrutin_id : déduction déjà faite)
        return
    # les zones où chaque scrutin a eu lieu : cantons (« 01-01 ») et communes, d'après les bureaux de participation
    lieux = con.execute(r"""
        SELECT DISTINCT regexp_replace(scrutin, '_t[12]$', '') election, CAST(right(scrutin, 1) AS INTEGER) tour,
               code_departement || '-' || right(code_canton, 2) canton, code_commune commune
        FROM participation WHERE regexp_matches(scrutin, '_(dpmt|cant|muni)_t[12]$')""").df()
    mysql(f"""DROP TABLE IF EXISTS tmp_lieu; CREATE TABLE tmp_lieu (election VARCHAR(12), tour TINYINT, canton VARCHAR(12),
                commune VARCHAR(10), KEY (election, canton), KEY (election, commune)) {T}""")
    charger("tmp_lieu", lieux)
    # mandats « tour inconnu » → le scrutin du bon tour, selon le cas
    regles = {
        "canton": f"""z.niveau_id = {CANTON} AND e.code LIKE '%\\_dpmt'
                      AND EXISTS (SELECT 1 FROM tmp_lieu l WHERE l.election = e.code AND l.canton = z.code AND l.tour = 1)""",
        "commune à listes": f"""z.niveau_id IN ({COMMUNE}, {SECTEUR}) AND e.code LIKE '%\\_muni'
                      AND EXISTS (SELECT 1 FROM liste li JOIN scrutin sl ON sl.id = li.scrutin_id
                                  JOIN zone zl ON zl.id = li.zone_id
                                  WHERE sl.election_id = e.id AND left(zl.code, 5) = left(z.code, 5))""",
    }
    for nom, cond in regles.items():
        mysql(f"""UPDATE mandat m JOIN scrutin si ON si.id = m.scrutin_id AND si.tour IS NULL
                    JOIN election e ON e.id = si.election_id JOIN zone z ON z.id = m.zone_id
                    JOIN scrutin s ON s.election_id = e.id
                     AND s.tour = CASE WHEN EXISTS (SELECT 1 FROM tmp_lieu l WHERE l.election = e.code AND l.tour = 2
                                    AND ((z.niveau_id = {CANTON} AND l.canton = z.code)
                                      OR (z.niveau_id <> {CANTON} AND l.commune = left(z.code, 5)))) THEN 2 ELSE 1 END
                  SET m.scrutin_id = s.id WHERE {cond}""")
    mysql("DROP TABLE tmp_lieu")
    apres = int(requete("SELECT count(*) n FROM mandat m JOIN scrutin s ON s.id = m.scrutin_id WHERE s.tour IS NULL").n[0])
    etape(f"tours déduits des résultats : {avant - apres} mandats ; {apres} restent « tour inconnu »")


if __name__ == "__main__":
    con = duckdb.connect(str(C.BASE), read_only=True)
    deduire(con)
    con.close()
