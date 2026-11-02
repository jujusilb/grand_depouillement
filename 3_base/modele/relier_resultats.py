"""
relier_resultats.py — Chaque ligne de resultat d'une législative reliée à sa candidature (resultat.candidature_id) :
« toutes les voix d'une personne sans chercher son nom », et, par l'investiture, les voix de chaque parti.

    py relier_resultats.py --essai     (mesure le taux de rapprochement, n'écrit rien)
    py relier_resultats.py             (l'appli fermée ; ~6 min, surtout la recopie dans MariaDB)

Lancé par normaliser_references.py, après les partis. Rapprochement : même scrutin (ou, faute de candidature au 2nd
tour, celle du 1er tour de la même élection), même circonscription (celle du bureau, découpage de 2012 : législatives
2012 à 2024), même nom et même premier prénom (« Jean Yves BONY » = « Jean-Yves Bony »). qui reste le texte d'origine.
"""
import re
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

import exporter_mariadb as ex
from normaliser_references import lien, sauvegarder_duckdb
from outils_mariadb import mysql, norm, requete

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
BASE = C.BASE
ELECTIONS = ("2012_legi", "2017_legi", "2022_legi", "2024_legi")       # (circonscriptions du découpage de 2012)


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def cle_qui(qui):
    """« Jean Yves BONY » → « BONY|JEAN » : le nom (les mots en majuscules) et le premier prénom."""
    mots = str(qui).replace("M. ", "").replace("Mme ", "").split()
    nom = [m for m in mots if m.isupper() and len(m) > 1 or m in ("DE", "DU", "LE", "LA")]
    prenom = [m for m in mots if m not in nom]
    return norm(" ".join(nom)) + "|" + norm(re.split(r"[ -]", prenom[0])[0] if prenom else "")


def cle_personne(nom, prenoms):
    return norm(nom) + "|" + norm(re.split(r"[ ,-]", str(prenoms).strip())[0] if isinstance(prenoms, str) else "")


def relier(con, essai=False):
    t0 = time.time()
    fait = con.execute("SELECT count(*) FROM duckdb_columns() WHERE table_name = 'resultat' AND column_name = 'candidature_id'").fetchall()[0][0]
    if fait and not essai:
        etape("résultats : déjà reliés aux candidatures")
        return
    liste = ", ".join(f"'{e}'" for e in ELECTIONS)
    sc = requete(f"""SELECT s.id scrutin_id, s.tour, e.code election FROM scrutin s JOIN election e ON e.id = s.election_id
                     WHERE e.code IN ({liste}) AND s.tour IS NOT NULL""").astype({"scrutin_id": int, "tour": int})
    c = requete(f"""SELECT c.id candidature_id, c.scrutin_id, c.zone_id, p.nom_usage, p.prenoms FROM candidature c
                    JOIN personne p ON p.id = c.personne_id JOIN scrutin s ON s.id = c.scrutin_id JOIN election e ON e.id = s.election_id
                    WHERE e.code IN ({liste})""").astype({"candidature_id": int, "scrutin_id": int, "zone_id": int})
    c = c.merge(sc, on="scrutin_id")
    c["cle"] = [cle_personne(n, p) for n, p in zip(c.nom_usage, c.prenoms)]
    b = requete("SELECT id bureau_id, circonscription_id zone_id FROM bureau WHERE circonscription_id IS NOT NULL").astype(int)
    con.register("b_df", b)
    con.register("sc_df", sc)
    q = con.execute("""SELECT r.scrutin_id, b.zone_id, r.qui, count(*) n FROM resultat r JOIN sc_df s USING (scrutin_id)
                       JOIN b_df b USING (bureau_id) GROUP BY ALL""").df()
    q["cle"] = q.qui.map(cle_qui)
    q = q.merge(sc, on="scrutin_id")
    # la candidature de ce tour ; sinon celle du 1er tour de la même élection
    m = q.merge(c[["candidature_id", "scrutin_id", "zone_id", "cle"]], on=["scrutin_id", "zone_id", "cle"], how="left")
    t1 = c[c.tour == 1][["candidature_id", "election", "zone_id", "cle"]].rename(columns={"candidature_id": "cand_t1"})
    m = m.merge(t1.drop_duplicates(["election", "zone_id", "cle"]), on=["election", "zone_id", "cle"], how="left")
    m["candidature_id"] = m.candidature_id.fillna(m.cand_t1)
    m = m.drop_duplicates(["scrutin_id", "zone_id", "qui"])
    for e, g in m.groupby("election"):
        etape(f"{e} : {g.candidature_id.notna().mean():.1%} des couples (circonscription, candidat) reliés "
              f"({int(g[g.candidature_id.isna()].n.sum())} lignes de bureau sans candidature)")
    sans = m[m.candidature_id.isna()].qui.head(8).tolist()
    etape(f"exemples non reliés : {sans}")
    if essai:
        return
    sauvegarder_duckdb(con, "resultat", "resultat_avant_candidature")
    con.register("carte", m.dropna(subset=["candidature_id"])[["scrutin_id", "zone_id", "qui", "candidature_id"]])
    n0 = con.execute("SELECT count(*) FROM resultat").fetchall()[0][0]
    con.execute("""CREATE OR REPLACE TABLE resultat_n AS
                   SELECT r.scrutin_id, r.bureau_id, c.candidature_id::BIGINT candidature_id, r.qui, r.nuance_id, r.voix
                   FROM resultat r LEFT JOIN b_df b USING (bureau_id)
                   LEFT JOIN carte c ON c.scrutin_id = r.scrutin_id AND c.zone_id = b.zone_id AND c.qui = r.qui
                   ORDER BY 1, 2""")
    if con.execute("SELECT count(*) FROM resultat_n").fetchall()[0][0] != n0:
        raise RuntimeError("resultat : des lignes en trop ou perdues")
    con.execute("DROP TABLE resultat")
    con.execute("ALTER TABLE resultat_n RENAME TO resultat")
    con.execute("CHECKPOINT")
    ex.copier(con, "resultat", '"resultat"')
    mysql("ALTER TABLE resultat ADD INDEX ix_scrutin_bureau (scrutin_id, bureau_id), ADD INDEX ix_bureau (bureau_id), "
          "ADD INDEX ix_nuance (nuance_id), ADD INDEX ix_candidature (candidature_id)")
    for col, ref in (("scrutin_id", "scrutin"), ("bureau_id", "bureau"), ("nuance_id", "nuance"), ("candidature_id", "candidature")):
        lien("resultat", col, ref)
    n = con.execute("SELECT count(*) FILTER (WHERE candidature_id IS NOT NULL) FROM resultat").fetchall()[0][0]
    etape(f"resultat : {n} lignes reliées à leur candidature — fini en {(time.time() - t0) / 60:.0f} min")


if __name__ == "__main__":
    essai = "--essai" in sys.argv
    con = duckdb.connect(str(BASE), read_only=essai)
    relier(con, essai)
    con.close()
