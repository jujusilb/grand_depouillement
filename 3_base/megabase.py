"""
megabase.py — Rassemble les 56 scrutins dans UNE base de données (DuckDB).

    py megabase.py      (depuis BigData_IA/demo_megabase, environ 1 à 2 minutes)

Entrée  : tes Parquet « propres », un par scrutin
          parquets/data/participation/<scrutin>.parquet   (inscrits, votants... par bureau)
          parquets/data/candidat/<scrutin>.parquet        (voix de chaque candidat / liste / binôme)
          + les fichiers officiels du COG (ELECTION/v_*.csv) pour les niveaux géographiques
Sortie  : megabase.duckdb, un seul fichier, 3 tables :
          scrutins       une ligne par scrutin (type, année, tour, date, libellé)
          participation  une ligne par bureau et par scrutin, avec TOUS les niveaux géographiques
          resultats      une ligne par bureau, scrutin et « qui » (candidat, liste, binôme...)

DuckDB, c'est une base SQL dans un simple fichier : pas de serveur, et elle lit les Parquet directement.
"""

from pathlib import Path

import duckdb
import sys
import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("megabase")
DATA = C.RESULTATS
ELECTION = C.ELECTIONS
BASE = ICI / "megabase.duckdb"

TYPES = {"pres": "Présidentielle", "legi": "Législatives", "euro": "Européennes", "muni": "Municipales",
         "regi": "Régionales", "dpmt": "Départementales", "cant": "Cantonales"}

# Dates des scrutins (pour placer les points dans le temps)
DATES = {
    "1999_euro_t1": "1999-06-13",
    "2001_cant_t1": "2001-03-11", "2001_cant_t2": "2001-03-18",
    "2002_pres_t1": "2002-04-21", "2002_pres_t2": "2002-05-05",
    "2002_legi_t1": "2002-06-09", "2002_legi_t2": "2002-06-16",
    "2004_cant_t1": "2004-03-21", "2004_cant_t2": "2004-03-28",
    "2004_regi_t1": "2004-03-21", "2004_regi_t2": "2004-03-28", "2004_euro_t1": "2004-06-13",
    "2007_pres_t1": "2007-04-22", "2007_pres_t2": "2007-05-06",
    "2007_legi_t1": "2007-06-10", "2007_legi_t2": "2007-06-17",
    "2008_muni_t1": "2008-03-09", "2008_muni_t2": "2008-03-16",
    "2008_cant_t1": "2008-03-09", "2008_cant_t2": "2008-03-16",
    "2009_euro_t1": "2009-06-07",
    "2010_regi_t1": "2010-03-14", "2010_regi_t2": "2010-03-21",
    "2011_cant_t1": "2011-03-20", "2011_cant_t2": "2011-03-27",
    "2012_pres_t1": "2012-04-22", "2012_pres_t2": "2012-05-06",
    "2012_legi_t1": "2012-06-10", "2012_legi_t2": "2012-06-17",
    "2014_muni_t1": "2014-03-23", "2014_muni_t2": "2014-03-30", "2014_euro_t1": "2014-05-25",
    "2015_dpmt_t1": "2015-03-22", "2015_dpmt_t2": "2015-03-29",
    "2015_regi_t1": "2015-12-06", "2015_regi_t2": "2015-12-13",
    "2017_pres_t1": "2017-04-23", "2017_pres_t2": "2017-05-07",
    "2017_legi_t1": "2017-06-11", "2017_legi_t2": "2017-06-18",
    "2019_euro_t1": "2019-05-26",
    "2020_muni_t1": "2020-03-15", "2020_muni_t2": "2020-06-28",
    "2021_dpmt_t1": "2021-06-20", "2021_dpmt_t2": "2021-06-27",
    "2021_regi_t1": "2021-06-20", "2021_regi_t2": "2021-06-27",
    "2022_pres_t1": "2022-04-10", "2022_pres_t2": "2022-04-24",
    "2022_legi_t1": "2022-06-12", "2022_legi_t2": "2022-06-19",
    "2024_euro_t1": "2024-06-09",
    "2024_legi_t1": "2024-06-30", "2024_legi_t2": "2024-07-07",
    "2026_muni_t1": "2026-03-15", "2026_muni_t2": "2026-03-22",
}

# Codes « Z » du ministère -> codes INSEE des départements / collectivités d'outre-mer
OUTRE_MER = {"ZA": "971", "ZB": "972", "ZC": "973", "ZD": "974", "ZM": "976", "ZS": "975",
             "ZT": "978", "ZY": "977", "ZX": "977", "ZN": "988", "ZP": "987", "ZW": "986"}


def etape(texte):
    print("•", texte, flush=True)


def table_scrutins():
    lignes = []
    for f in sorted((DATA / "participation").glob("*.parquet")):
        annee, typ, tour = f.stem.split("_")
        lignes.append({"scrutin": f.stem, "type": typ, "type_libelle": TYPES[typ], "annee": int(annee),
                       "tour": int(tour[1]), "date": pd.Timestamp(DATES[f.stem]),
                       "libelle": f"{TYPES[typ]} {annee} – {'1er' if tour == 't1' else '2nd'} tour"})
    return pd.DataFrame(lignes).sort_values("date")


def tables_geo():
    """Commune -> canton, arrondissement (découpage 2026), et département -> région."""
    com = pd.read_csv(ELECTION / "v_commune_2026.csv", dtype=str)
    can = pd.read_csv(ELECTION / "v_canton_2026.csv", dtype=str)[["CAN", "LIBELLE"]]
    arr = pd.read_csv(ELECTION / "v_arrondissement_2026.csv", dtype=str)[["ARR", "LIBELLE"]]
    dep = pd.read_csv(ELECTION / "v_departement_2026.csv", dtype=str)[["DEP", "REG", "LIBELLE"]]
    reg = pd.read_csv(ELECTION / "v_region_2026.csv", dtype=str)[["REG", "LIBELLE"]]

    # Les communes actuelles, puis les anciennes communes (déléguées / associées) rattachées à leur parent
    actuelles = com[com["TYPECOM"] == "COM"].set_index("COM")[["CAN", "ARR"]]
    anciennes = com[com["TYPECOM"].isin(["COMD", "COMA"]) & ~com["COM"].isin(actuelles.index)]
    anciennes = anciennes.drop_duplicates("COM").set_index("COM")["COMPARENT"].map(lambda p: p)
    anciennes = anciennes.to_frame("parent").join(actuelles, on="parent")[["CAN", "ARR"]]
    geo = pd.concat([actuelles, anciennes]).reset_index().rename(columns={"index": "COM"})
    geo = geo.merge(can.rename(columns={"LIBELLE": "libelle_canton"}), on="CAN", how="left")
    geo = geo.merge(arr.rename(columns={"LIBELLE": "libelle_arr"}), on="ARR", how="left")
    # Code canton se terminant par 99 = grande ville répartie sur plusieurs cantons
    plusieurs = geo["CAN"].fillna("").str.endswith("99")
    geo.loc[plusieurs, "libelle_canton"] = geo.loc[plusieurs, "libelle_canton"].fillna("") + " (ville sur plusieurs cantons)"
    geo = geo.rename(columns={"COM": "code_commune", "CAN": "code_canton", "ARR": "code_arr"})

    dep = dep.merge(reg.rename(columns={"LIBELLE": "libelle_region"}), on="REG", how="left")
    dep = dep.rename(columns={"DEP": "dep_insee", "REG": "code_region", "LIBELLE": "libelle_dep_cog"})
    return geo, dep


def main():
    if BASE.exists():
        BASE.unlink()
    con = duckdb.connect(str(BASE))

    etape("Table des scrutins")
    scrutins = table_scrutins()
    con.register("scrutins_df", scrutins)
    con.execute("CREATE TABLE scrutins AS SELECT * FROM scrutins_df")

    etape("Tables géographiques (COG 2026)")
    geo, dep = tables_geo()
    om = pd.DataFrame({"code_departement": list(OUTRE_MER), "dep_insee": list(OUTRE_MER.values())})
    con.register("geo_df", geo)
    con.register("dep_df", dep)
    con.register("om_df", om)

    etape("Participation : 56 scrutins, 3 millions de bureaux-scrutins")
    participation = str(DATA / "participation" / "*.parquet").replace("\\", "/")
    con.execute(f"""
        CREATE TABLE participation AS
        SELECT
            p.id_election                               AS scrutin,
            p.id_brut_miom,
            p.code_bv,
            p.code_commune,
            p.libelle_commune,
            p.code_departement,
            COALESCE(d.libelle_dep_cog, p.libelle_departement) AS libelle_departement,
            COALESCE(d.code_region,
                     CASE WHEN p.code_departement = 'ZZ' THEN 'FE'
                          WHEN p.code_departement LIKE 'Z%' OR p.code_departement IN ('975', '977', '978', '986', '987', '988')
                          THEN 'COM' END)
                                                        AS code_region,
            COALESCE(d.libelle_region,
                     CASE WHEN p.code_departement = 'ZZ' THEN 'Français de l''étranger'
                          WHEN p.code_departement LIKE 'Z%' OR p.code_departement IN ('975', '977', '978', '986', '987', '988')
                          THEN 'Collectivités d''outre-mer' END)
                                                        AS libelle_region,
            g.code_arr,  g.libelle_arr,
            g.code_canton, g.libelle_canton,
            p.inscrits, p.abstentions, p.votants, p.blancs, p.nuls, p.exprimes
        FROM read_parquet('{participation}', union_by_name = true) p
        LEFT JOIN om_df o   ON o.code_departement = p.code_departement
        LEFT JOIN dep_df d  ON d.dep_insee = COALESCE(o.dep_insee, p.code_departement)
        LEFT JOIN geo_df g  ON g.code_commune = p.code_commune
        ORDER BY scrutin, id_brut_miom
    """)

    etape("Résultats : 27 millions de lignes -> un « qui » par bureau et par scrutin")
    candidats = str(DATA / "candidat" / "*.parquet").replace("\\", "/")
    # « qui » = le nom le plus parlant disponible, selon le scrutin (liste, binôme, candidat, tête de liste...)
    con.execute(f"""
        CREATE TABLE resultats AS
        SELECT id_election AS scrutin, id_brut_miom, qui, ANY_VALUE(nuance) AS nuance, SUM(voix) AS voix
        FROM (
            SELECT id_election, id_brut_miom, voix, nuance,
                   COALESCE(CASE WHEN LENGTH(TRIM(libelle_abrege_liste)) >= 6 THEN TRIM(libelle_abrege_liste) END,
                            NULLIF(TRIM(libelle_etendu_liste), ''),       -- abrégé trop court (sigle) : nom complet
                            NULLIF(TRIM(libelle_abrege_liste), ''),
                            NULLIF(TRIM(binome), ''),
                            NULLIF(TRIM(COALESCE(prenom, '') || ' ' || COALESCE(nom, '')), ''),
                            NULLIF(TRIM(nom_tete_liste), ''),
                            nuance, 'inconnu') AS qui
            FROM read_parquet('{candidats}', union_by_name = true)
        )
        GROUP BY ALL
        ORDER BY scrutin, id_brut_miom
    """)

    etape("Index et contrôles")
    # Pas d'index : les tables sont triées par scrutin (ORDER BY), et DuckDB saute tout seul
    # les blocs qui ne concernent pas le scrutin demandé.
    n_s, = con.execute("SELECT COUNT(*) FROM scrutins").fetchone()
    n_p, = con.execute("SELECT COUNT(*) FROM participation").fetchone()
    n_r, = con.execute("SELECT COUNT(*) FROM resultats").fetchone()
    sans_region, = con.execute("SELECT COUNT(*) FROM participation WHERE code_region IS NULL").fetchone()
    sans_canton, = con.execute("SELECT COUNT(*) FROM participation WHERE code_canton IS NULL").fetchone()
    print(f"  {n_s} scrutins | {n_p:,} lignes de participation | {n_r:,} lignes de résultats".replace(",", " "))
    print(f"  sans région : {sans_region} | sans canton/arrondissement 2026 : {sans_canton} "
          f"(communes disparues ou hors COG)")
    con.execute("CHECKPOINT")
    con.close()
    print(f"Base écrite : {BASE} ({BASE.stat().st_size / 1e6:.0f} Mo)")


if __name__ == "__main__":
    main()
