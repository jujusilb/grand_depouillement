"""
construire_modele.py — Construit UNE FOIS le modèle « personnes et mandats » dans MariaDB, à partir des tables de l'appli.

    py construire_modele.py              (refuse si la table personne existe déjà dans MariaDB : c'est elle qui fait foi)
    py construire_modele.py --refaire    (repart de zéro ; les tables du modèle sont d'abord sauvegardées dans PROJET/DECHET)

Le modèle (dessin : BigData_IA/conception/modele_elus.puml) :
    personne        une ligne par être humain (nom, prénoms, sexe, naissance, décès)
    identifiant     ses identifiants dans les référentiels (table referentiel : Assemblée, Sénat, Wikidata, Insee décès)
    mandat          une personne, une fonction, un territoire, une période, l'élection qui l'a donné, motifs de début et de fin
    appartenance_groupe   les groupes politiques d'un mandat de député, avec leurs dates
    liste           ceux qui sont élus ensemble : une liste municipale, régionale, européenne
    candidature     chaque candidat, élu ou non (rang sur sa liste, nuance, métier déclaré)
    photo, photo_personne   les photos (une photo peut montrer plusieurs personnes ; liée à un mandat OU à une candidature)
    fonction, fonction_duree, incompatibilite, election, type_election, mode_scrutin, zone_niveau, motif_debut, motif_fin
                    les listes de référence

Qui est qui ? Deux mentions sont la même personne si elles ont le même nom, le même premier prénom et la même date de
naissance, ou le même identifiant (Assemblée, Sénat, Wikidata). Les mentions sans date de naissance (listes municipales du
1er tour, députés 1988-2002, votes) sont rattachées par nom + prénom + commune (ou département) quand c'est sans ambiguïté ;
sinon elles forment leur propre personne. personne.identification_id (table methode_identification) dit comment
chacune a été reconnue.
Conventions : date_fin vide et motif_fin vide = mandat en cours ; motif_fin « inconnu » = fini, à une date qu'on ignore.
Les durées sont en mois.
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import pandas as pd

import exporter_mariadb as mx
from outils_mariadb import METHODES, REFERENTIELS, sources

ICI = Path(__file__).resolve().parent
BASE = ICI / "data" / "depouillement.duckdb"
WIKIDATA = ICI.parent / "donnees_contexte" / "legislatures" / "deputes_wikidata.parquet"
DECES = ICI.parent / "donnees_contexte" / "legislatures" / "deces_deputes.parquet"
DECHET = ICI.parent.parent / "DECHET"
debut_chrono = time.time()


NOMS_WIKIDATA = [  # qid, nom, prénom (lus dans Wikidata le 1er novembre 2026)
    ("Q2105", "Chirac", "Jacques"), ("Q12959", "Balladur", "Édouard"), ("Q455040", "Barrot", "Jacques"),
    ("Q2263544", "Lalumière", "Catherine"), ("Q3107823", "Moreau", "Gisèle"), ("Q3159326", "Le Roy Ladurie", "Jacques"),
    ("Q3165099", "Martinez", "Jean-Claude"), ("Q16262906", "Le Coat de Kerveguen", "Yves"), ("Q19344680", "Zimmermann", "Raymond"),
]


def etape(texte):
    print(f"[{time.time() - debut_chrono:6.0f} s] {texte}", flush=True)


# ------------------------------------------------------------------------------------------------------------------
# 0. Les listes de référence
# ------------------------------------------------------------------------------------------------------------------
FONCTIONS = [  # id, libellé, niveau du territoire
    (1, "conseiller municipal", "commune"), (2, "maire", "commune"), (3, "adjoint au maire", "commune"),
    (4, "conseiller d'arrondissement", "secteur"), (5, "conseiller communautaire", "epci"),
    (6, "président d'intercommunalité", "epci"), (7, "vice-président d'intercommunalité", "epci"),
    (8, "conseiller départemental", "canton"), (9, "président du conseil départemental", "departement"),
    (10, "vice-président du conseil départemental", "departement"), (11, "conseiller régional", "region"),
    (12, "président du conseil régional", "region"), (13, "vice-président du conseil régional", "region"),
    (14, "député", "circonscription"), (15, "sénateur", "departement"), (16, "député européen", "pays"),
    (17, "président de la République", "pays"), (18, "ministre", "pays"),
    (19, "président du Sénat", "pays"), (20, "vice-président du Sénat", "pays"), (21, "questeur du Sénat", "pays"),
    (22, "secrétaire du Sénat", "pays"), (23, "maire délégué", "commune"),
]
DUREES = [  # fonction, durée en mois, en vigueur le
    (1, 72, "1929-01-01"), (1, 48, "1884-04-05"), (2, 72, "1929-01-01"), (3, 72, "1929-01-01"), (4, 72, "1983-01-01"),
    (5, 72, "2014-03-23"), (8, 72, "2015-03-22"), (8, 72, "1833-06-22"), (11, 72, "1986-03-16"), (14, 60, "1958-10-04"),
    (14, 48, "1875-11-30"), (15, 108, "1875-02-24"), (15, 72, "2004-01-01"), (16, 60, "1979-06-10"),
    (17, 84, "1873-11-20"), (17, 60, "2002-01-01"),
]
INCOMPATIBILITES = [  # fonction A, fonction B, en vigueur le, fin, texte
    (14, 15, "1875-01-01", None, "Lois constitutionnelles de 1875 ; Constitution de 1958 (art. LO 137)"),
    (17, 14, "1958-10-04", None, "Constitution de 1958 (le président ne siège dans aucune assemblée)"),
    (17, 15, "1958-10-04", None, "Constitution de 1958"),
    (14, 16, "2002-06-16", None, "Loi organique du 5 avril 2000 (député national / député européen)"),
    (15, 16, "2004-09-26", None, "Loi organique du 5 avril 2000"),
    (14, 2, "2017-07-01", None, "Loi organique du 14 février 2014 (non-cumul avec une fonction exécutive locale)"),
    (15, 2, "2017-10-01", None, "Loi organique du 14 février 2014"),
    (14, 18, "1958-10-04", None, "Constitution de 1958, art. 23 (un ministre quitte son siège)"),
]
ZONES = [  # id, libellé, parent
    (1, "commune", 6), (2, "secteur", 1), (3, "intercommunalité", 6), (4, "canton", 6), (5, "circonscription", 6),
    (6, "département", 7), (7, "région", 8), (8, "pays", 9), (9, "Europe", None),
]
Z = {"commune": 1, "secteur": 2, "epci": 3, "canton": 4, "circonscription": 5, "departement": 6, "region": 7, "pays": 8}
MOTIFS_DEBUT = [(1, "élection générale"), (2, "élection partielle"), (3, "élection par une assemblée"),
                (4, "entrée en cours de mandat (suivant de liste, suppléant…)"), (5, "désignation"), (6, "nomination"),
                (7, "inconnu")]
MOTIFS_FIN = [(1, "terme", False), (2, "démission", True), (3, "décès", True), (4, "battu", False),
              (5, "ne s'est pas représenté", False), (6, "dissolution", False), (7, "nommé au gouvernement", True),
              (8, "invalidation", True), (9, "non-cumul", True), (10, "inconnu", False)]
MODES = [(1, "majoritaire à deux tours"), (2, "proportionnelle avec prime majoritaire (listes)"),
         (3, "plurinominal majoritaire (candidats un par un, panachage)"), (4, "binominal majoritaire à deux tours"),
         (5, "proportionnelle à un tour (listes)"), (6, "élection par l'assemblée"), (7, "désignation (fléchage)"),
         (8, "suffrage indirect (grands électeurs)"), (9, "proportionnelle départementale (listes)")]


# ------------------------------------------------------------------------------------------------------------------
# 1. Les mentions de personnes, dans les 14 tables
# ------------------------------------------------------------------------------------------------------------------
etape("lecture des mentions de personnes")
con = duckdb.connect()
# (après brancher_modele.py, les 14 tables d'origine sont devenues des vues du modèle : on lit alors la copie d'avant)
SOURCE = BASE
with duckdb.connect(str(BASE), read_only=True) as essai:
    if essai.execute("SELECT count(*) FROM duckdb_views() WHERE view_name = 'deputes'").fetchone()[0]:
        SOURCE = DECHET / "depouillement_avant_modele.duckdb"
        etape(f"tables d'origine lues dans {SOURCE}")
con.execute(f"ATTACH '{SOURCE.as_posix()}' AS b (READ_ONLY)")
con.execute("CREATE MACRO norm(s) AS trim(regexp_replace(upper(strip_accents(coalesce(s, ''))), '[^A-Z0-9]+', ' ', 'g'))")
con.execute("CREATE MACRO p1(s) AS split_part(norm(s), ' ', 1)")
con.execute(f"CREATE TABLE wd AS SELECT DISTINCT ON (qid) qid, TRY_CAST(naissance AS DATE) naissance FROM '{WIKIDATA.as_posix()}'")

# (une mention = source, référence dans la source, nom, prénom, sexe, naissance, identifiants, commune, département)
con.execute("""
CREATE TABLE mention AS
SELECT 'rne_' || t AS source, ref, nom, prenom, sexe, naissance, NULL id_an, NULL id_senat, NULL id_wd, commune, departement FROM (
    SELECT 'mun' t, version || '#' || rowid ref, nom, prenom, sexe, CAST(naissance AS DATE) naissance, code_commune commune, NULL departement FROM b.rne_municipaux
    UNION ALL SELECT 'com', version || '#' || rowid, nom, prenom, sexe, CAST(naissance AS DATE), code_commune, NULL FROM b.rne_communautaires
    UNION ALL SELECT 'dep', version || '#' || rowid, nom, prenom, sexe, CAST(naissance AS DATE), NULL, departement FROM b.rne_departementaux
    UNION ALL SELECT 'reg', version || '#' || rowid, nom, prenom, sexe, CAST(naissance AS DATE), NULL, NULL FROM b.rne_regionaux
    UNION ALL SELECT 'arr', version || '#' || rowid, nom, prenom, sexe, CAST(naissance AS DATE), code_commune, NULL FROM b.rne_arrondissements)
UNION ALL SELECT 'elus2014', CAST(rowid AS VARCHAR), nom, prenom, sexe, CAST(naissance AS DATE), NULL, NULL, NULL, code_commune, left(code_commune, 2)
    FROM b.elus_municipaux_2014
UNION ALL SELECT 'cdet', CAST(rowid AS VARCHAR), nom, prenom, sexe, CAST(naissance AS DATE), NULL, NULL, NULL, NULL, departement FROM b.candidats_details
UNION ALL SELECT 'clist', CAST(rowid AS VARCHAR), nom, prenom, sexe, TRY_CAST(date_naissance AS DATE), NULL, NULL, NULL,
    CASE WHEN conseil IN ('municipal', 'arrondissement') THEN left(code_zone, 5) END, code_departement FROM b.candidats_listes
UNION ALL SELECT 'dep_an', id, nom, prenom, CASE WHEN civ = 'Mme' THEN 'F' ELSE 'M' END, TRY_CAST(naissance AS DATE), id, NULL, NULL, NULL,
    lpad(CAST(num_departement AS VARCHAR), 2, '0') FROM b.deputes
UNION ALL SELECT 'sen', matricule, nom, prenom, CASE WHEN civ = 'Mme' THEN 'F' ELSE 'M' END, TRY_CAST(naissance AS DATE), NULL, matricule, NULL,
    NULL, NULL FROM b.senateurs
UNION ALL SELECT 'mand', acteur, regexp_replace(any_value(depute), '^\\S+\\s+', ''), regexp_extract(any_value(depute), '^(\\S+)', 1), NULL,
    NULL, acteur, NULL, NULL, NULL, any_value(departement) FROM b.mandats_deputes GROUP BY acteur
UNION ALL SELECT 'sieg', CAST(s.rowid AS VARCHAR), regexp_replace(depute, '^\\S+\\s+', ''), regexp_extract(depute, '^(\\S+)', 1), NULL,
    wd.naissance, NULL, NULL, CASE WHEN acteur LIKE 'Q%' THEN acteur END, NULL, upper(regexp_extract(lieu, '·\\s*(\\S+)\\s*$', 1))
    FROM b.sieges_legislature s LEFT JOIN wd ON wd.qid = s.acteur WHERE s.legislature <= 11 AND s.connu
""")
# (les noms des députés écrits « Prénom Nom » : le prénom est le premier mot — « Jean-Marie Le Pen » → LE PEN)
con.execute("UPDATE mention SET nom = trim(nom), prenom = trim(prenom)")
# (9 députés sans libellé français dans Wikidata au moment du téléchargement : leur « nom » était leur identifiant)
for qid, nom, prenom in NOMS_WIKIDATA:
    con.execute("UPDATE mention SET nom = ?, prenom = ? WHERE id_wd = ? AND nom = ?", [nom, prenom, qid, qid])
etape(f"{con.execute('SELECT count(*) FROM mention').fetchone()[0]:,} mentions".replace(",", " "))

# ------------------------------------------------------------------------------------------------------------------
# 2. Les regrouper en personnes : même nom + 1er prénom + date de naissance, ou même identifiant
# ------------------------------------------------------------------------------------------------------------------
etape("regroupement des mentions en personnes")
m = con.execute("""SELECT source, ref, norm(nom) n, p1(prenom) p, naissance, id_an, id_senat, id_wd, commune, departement
                   FROM mention""").fetchdf()
m["mid"] = range(len(m))
parent = {}


def racine(x):
    while parent.get(x, x) != x:
        parent[x] = parent.get(parent[x], parent[x])
        x = parent[x]
    return x


def unir(a, b):
    ra, rb = racine(a), racine(b)
    if ra != rb:
        parent[rb] = ra


forte = m["naissance"].notna() & (m["n"] != "")
cle = ("k:" + m["n"] + "|" + m["p"] + "|" + m["naissance"].astype(str)).where(forte)
for col, pref in [(cle, ""), (m["id_an"], "an:"), (m["id_senat"], "sen:"), (m["id_wd"], "wd:")]:
    for mid, v in zip(m["mid"], col):
        if isinstance(v, str) and v:
            unir(("m", mid), (pref + v))
# (un député de 2002-2024 n'a pas de date de naissance dans l'open data : on la prend dans sa fiche de candidat aux
#  législatives, même nom + même prénom + même département, quand il n'y en a qu'une)
fiches = m[(m["source"] == "cdet") & forte].groupby(["n", "p", "departement"])["mid"].agg(list)
sans_date = m[(m["source"] == "mand") & m["naissance"].isna()]
for mid, n_, p_, dep_ in zip(sans_date["mid"], sans_date["n"], sans_date["p"], sans_date["departement"]):
    trouves = fiches.get((n_, p_, dep_))
    if trouves:
        cles_ = {cle[i] for i in trouves}
        if len(cles_) == 1:
            unir(("m", mid), cles_.pop())
identifiee = forte | m["id_an"].notna() | m["id_senat"].notna() | m["id_wd"].notna()
m["groupe"] = [racine(("m", mid)) if ok else None for mid, ok in zip(m["mid"], identifiee)]
groupes = {g: i + 1 for i, g in enumerate(pd.unique(m["groupe"].dropna()))}
m["personne_id"] = m["groupe"].map(groupes)
m["identification"] = None
m.loc[forte, "identification"] = "nom + prénom + naissance"
m.loc[~forte & identifiee, "identification"] = "identifiant"
etape(f"{len(groupes):,} personnes reconnues avec certitude".replace(",", " "))

# 3. Les mentions sans date ni identifiant : par nom + prénom + commune (ou département), quand il n'y a qu'une personne
etape("rattachement des mentions sans date de naissance")
connues = m[m["personne_id"].notna()]
nouveau = len(groupes)
for lieu in ["commune", "departement"]:
    reste = m["personne_id"].isna() & m[lieu].notna() & (m["n"] != "")
    index = connues.dropna(subset=[lieu]).groupby(["n", "p", lieu])["personne_id"].agg(["nunique", "first"])
    seules = index.loc[index["nunique"] == 1, "first"]
    k = pd.MultiIndex.from_frame(m.loc[reste, ["n", "p", lieu]])
    trouve = pd.Series(seules.reindex(k).values, index=m.index[reste])
    ok = trouve.notna()
    m.loc[trouve.index[ok], "personne_id"] = trouve[ok]
    m.loc[trouve.index[ok], "identification"] = f"nom + prénom + {lieu}"
# les autres : une personne par (nom, prénom, commune ou département)
reste = m["personne_id"].isna()
cles = m.loc[reste, "n"] + "|" + m.loc[reste, "p"] + "|" + m.loc[reste, "commune"].fillna(m.loc[reste, "departement"]).fillna("")
nouvelles = {c: nouveau + i + 1 for i, c in enumerate(pd.unique(cles))}
m.loc[reste, "personne_id"] = cles.map(nouvelles)
m.loc[reste, "identification"] = "nom + prénom seulement (personne à part)"
m["personne_id"] = m["personne_id"].astype("int64")
etape(f"{m['personne_id'].nunique():,} personnes en tout".replace(",", " "))
con.register("lien", m[["source", "ref", "personne_id", "identification"]])
con.execute("CREATE TABLE lien_m AS SELECT * FROM lien")
con.unregister("lien")

# les personnes : le nom et le prénom les plus complets, la naissance, le sexe
con.execute("""CREATE MACRO PRIO(s) AS CASE s WHEN 'dep_an' THEN 1 WHEN 'sen' THEN 2 WHEN 'mand' THEN 3 WHEN 'sieg' THEN 4
               WHEN 'elus2014' THEN 6 WHEN 'cdet' THEN 7 WHEN 'clist' THEN 8 ELSE 5 END""")
con.execute("""
CREATE TABLE personne AS
SELECT l.personne_id AS id,
       -- (l'écriture de la source la plus soignée : Assemblée, Sénat, puis RNE, élus 2014, fiches, listes)
       arg_min(mn.nom, PRIO(mn.source)) AS nom_usage, CAST(NULL AS VARCHAR) AS nom_naissance,
       arg_min(mn.prenom, PRIO(mn.source) * 1000 - length(mn.prenom)) AS prenoms,
       mode(CASE WHEN mn.sexe IN ('M', 'F') THEN mn.sexe END) AS sexe,
       mode(mn.naissance) AS date_naissance, CAST(NULL AS VARCHAR) AS lieu_naissance,
       CAST(NULL AS DATE) AS date_deces, CAST(NULL AS VARCHAR) AS lieu_deces,
       arg_min(l.identification, CASE l.identification WHEN 'nom + prénom + naissance' THEN 1 WHEN 'identifiant' THEN 2
               WHEN 'nom + prénom + commune' THEN 3 WHEN 'nom + prénom + departement' THEN 4 ELSE 5 END) AS identification
FROM lien_m l JOIN mention mn USING (source, ref) GROUP BY l.personne_id""")
con.execute("""
CREATE TABLE identifiant AS
SELECT DISTINCT l.personne_id, s.source, s.valeur FROM lien_m l JOIN (
    SELECT source AS src, ref, 'Assemblée nationale' source, id_an valeur FROM mention WHERE id_an IS NOT NULL
    UNION ALL SELECT source, ref, 'Sénat', id_senat FROM mention WHERE id_senat IS NOT NULL
    UNION ALL SELECT source, ref, 'Wikidata', id_wd FROM mention WHERE id_wd IS NOT NULL) s ON s.src = l.source AND s.ref = l.ref""")
# le décès, quand le croisement avec le fichier de l'Insee est « sûr » (deces_deputes.parquet, voir croiser_deces.py)
if DECES.exists():
    con.execute(f"""
    UPDATE personne p SET date_deces = TRY_CAST(d.deces AS DATE), lieu_deces = d.lieu_deces, lieu_naissance = d.lieu_naissance,
                          nom_naissance = d.nom, date_naissance = coalesce(p.date_naissance, TRY_CAST(d.naissance AS DATE))
    FROM identifiant i, '{DECES.as_posix()}' d
    WHERE i.personne_id = p.id AND i.source = 'Wikidata' AND i.valeur = d.acteur AND d.verdict = 'sûr'""")
    con.execute(f"""INSERT INTO identifiant SELECT DISTINCT i.personne_id, 'Insee décès', CAST(d.id_insee AS VARCHAR)
                    FROM identifiant i JOIN '{DECES.as_posix()}' d ON i.source = 'Wikidata' AND i.valeur = d.acteur AND d.verdict = 'sûr'""")

# ------------------------------------------------------------------------------------------------------------------
# 4. Les élections, puis les mandats
# ------------------------------------------------------------------------------------------------------------------
etape("élections et mandats")
con.execute("""
CREATE TABLE type_election AS SELECT row_number() OVER (ORDER BY type_libelle) id, type_libelle label, type code
    FROM (SELECT DISTINCT type, type_libelle FROM b.scrutins)""")
con.execute("""
CREATE TABLE election AS
SELECT row_number() OVER (ORDER BY min(s.date), s.base) id, s.base code, any_value(t.id) type_election_id,
       CAST(min(s.date) FILTER (WHERE s.tour = 1) AS DATE) date_t1, CAST(min(s.date) FILTER (WHERE s.tour = 2) AS DATE) date_t2,
       any_value(s.libelle) FILTER (WHERE s.tour = 1) libelle_t1, any_value(s.libelle) FILTER (WHERE s.tour = 2) libelle_t2,
       FALSE partielle, CAST(NULL AS INTEGER) duree_exception
FROM (SELECT *, regexp_replace(scrutin, '_t\\d$', '') base FROM b.scrutins) s JOIN type_election t ON t.code = s.type GROUP BY s.base""")
# (les mandats de 2014-2020 ont duré 6 ans, mais une loi a raccourci les régionales 2010 et les cantonales 2011)
con.execute("UPDATE election SET duree_exception = 48 WHERE code = '2011_cant'")
con.execute("UPDATE election SET duree_exception = 60 WHERE code = '2010_regi'")
con.execute("CREATE MACRO el(c) AS (SELECT id FROM election WHERE code = c)")
con.execute("CREATE MACRO date_el(c) AS (SELECT coalesce(date_t1, date_t2) FROM election WHERE code = c)")

MANDATS = []
# --- le RNE : conseillers municipaux (et maires, adjoints), communautaires, départementaux, régionaux, d'arrondissement
CYCLES_MUNI = "CASE version WHEN '2020-01' THEN '2014_muni' WHEN '2020-12' THEN '2020_muni' ELSE '2026_muni' END"
FIN_MUNI = "CASE version WHEN '2020-01' THEN date_el('2020_muni') WHEN '2020-12' THEN date_el('2026_muni') END"
CYCLES_DEP = "CASE WHEN version LIKE '2020%' THEN '2015_dpmt' ELSE '2021_dpmt' END"
CYCLES_REG = "CASE WHEN version LIKE '2020%' THEN '2015_regi' ELSE '2021_regi' END"
FIN_DEP = "CASE WHEN version LIKE '2020%' THEN date_el('2021_dpmt') END"
FIN_REG = "CASE WHEN version LIKE '2020%' THEN date_el('2021_regi') END"


def rne(table, source, fonctions_sql, zone, code_zone, cycle, fin, mode):
    """Chaque ligne du RNE donne un mandat de base (conseiller…), plus un mandat exécutif si sa fonction le dit."""
    return f"""
    SELECT l.personne_id, f.fonction_id, el({cycle}) election_id, {mode} mode_scrutin_id, {Z[zone]} zone_niveau_id,
           {code_zone} zone_code, CAST(r.debut_mandat AS DATE) date_debut,
           CASE WHEN f.fonction_id IN (1, 4, 5, 8, 11) THEN
                CASE WHEN CAST(r.debut_mandat AS DATE) <= date_el({cycle}) + INTERVAL 120 DAY THEN 1 ELSE 4 END ELSE 3 END motif_debut_id,
           {fin} date_fin, CASE WHEN {fin} IS NOT NULL THEN 1 END motif_fin_id, NULL metier, '{table} ' || r.version source
    FROM b.{table} r JOIN lien_m l ON l.source = '{source}' AND l.ref = r.version || '#' || r.rowid,
         LATERAL ({fonctions_sql}) f(fonction_id)"""


def exec_ou_base(base_id, executif):
    """La fonction de base (toujours) et, selon le libellé du RNE, la fonction exécutive."""
    return f"SELECT {base_id} UNION ALL SELECT {executif} WHERE {executif} IS NOT NULL"


MANDATS.append(rne("rne_municipaux", "rne_mun", exec_ou_base(1, """CASE WHEN r.fonction ILIKE 'maire délégué%' THEN 23
                   WHEN r.fonction ILIKE 'maire%' THEN 2
                   WHEN r.fonction ILIKE '%adjoint%' THEN 3 END"""), "commune", "r.code_commune", CYCLES_MUNI, FIN_MUNI, "NULL"))
MANDATS.append(rne("rne_communautaires", "rne_com", exec_ou_base(5, """CASE WHEN r.fonction ILIKE 'président%' THEN 6
                   WHEN r.fonction ILIKE '%vice-président%' THEN 7 END"""), "epci", "r.siren", CYCLES_MUNI, FIN_MUNI, "7"))
MANDATS.append(rne("rne_departementaux", "rne_dep", exec_ou_base(8, """CASE WHEN r.fonction ILIKE 'président%' THEN 9
                   WHEN r.fonction ILIKE '%vice-président%' THEN 10 END"""), "canton", "r.departement || '-' || r.canton",
                   CYCLES_DEP, FIN_DEP, "4"))
MANDATS.append(rne("rne_regionaux", "rne_reg", exec_ou_base(11, """CASE WHEN r.fonction ILIKE 'président%' THEN 12
                   WHEN r.fonction ILIKE '%vice-président%' THEN 13 END"""), "region", "r.region", CYCLES_REG, FIN_REG, "2"))
MANDATS.append(rne("rne_arrondissements", "rne_arr", "SELECT 4", "secteur", "r.code_commune || '|' || r.secteur",
                   CYCLES_MUNI, FIN_MUNI, "2"))
# --- les élus municipaux de 2014 (au soir de l'élection)
MANDATS.append("""
    SELECT l.personne_id, 1, el('2014_muni'), CASE WHEN e.petite_commune THEN 3 ELSE 2 END, 1, e.code_commune,
           CASE WHEN e.tour = 1 THEN date_el('2014_muni') ELSE (SELECT date_t2 FROM election WHERE code = '2014_muni') END, 1,
           date_el('2020_muni'), 1, e.profession, 'élus municipaux 2014'
    FROM b.elus_municipaux_2014 e JOIN lien_m l ON l.source = 'elus2014' AND l.ref = CAST(e.rowid AS VARCHAR)""")
# --- les députés depuis 2002 (open data de l'Assemblée : dates exactes)
MANDATS.append("""
    SELECT l.personne_id, 14, el(CASE md.legislature WHEN 12 THEN '2002_legi' WHEN 13 THEN '2007_legi' WHEN 14 THEN '2012_legi'
                                WHEN 15 THEN '2017_legi' WHEN 16 THEN '2022_legi' ELSE '2024_legi' END), 1, 5,
           md.departement || '-' || md.circo, CAST(md.debut AS DATE),
           CASE WHEN CAST(md.debut AS DATE) <= lg.debut + INTERVAL 30 DAY THEN 1 ELSE 4 END,
           CAST(md.fin AS DATE),
           CASE WHEN md.fin IS NULL THEN NULL WHEN md.legislature = 16 AND CAST(md.fin AS DATE) >= DATE '2024-06-09' THEN 6
                WHEN CAST(md.fin AS DATE) >= lg.fin - INTERVAL 2 DAY THEN 1 ELSE 10 END, NULL,
           'Assemblée nationale (mandats)'
    FROM b.mandats_deputes md JOIN b.legislatures lg USING (legislature)
    JOIN lien_m l ON l.source = 'mand' AND l.ref = md.acteur""")
# --- les législatures I à XI (composition au début : CDSP et Wikidata ; personne inconnue = siège sans nom)
MANDATS.append("""
    SELECT l.personne_id, 14, (SELECT id FROM election WHERE code LIKE CAST(year(lg.debut) AS VARCHAR) || '%legi' ORDER BY code LIMIT 1),
           CASE WHEN s.legislature = 8 THEN 9 ELSE 1 END, 5,
           upper(regexp_extract(s.lieu, '·\\s*(\\S+)\\s*$', 1)) || '-' || regexp_extract(s.lieu, '^(\\d+)', 1),
           lg.debut, 1, lg.fin, 1, NULL, 'législature ' || lg.romain || ' (' || lg.source || ')'
    FROM b.sieges_legislature s JOIN b.legislatures lg USING (legislature)
    LEFT JOIN lien_m l ON l.source = 'sieg' AND l.ref = CAST(s.rowid AS VARCHAR)
    WHERE s.legislature <= 11""")
# --- les sénateurs en exercice
MANDATS.append("""
    SELECT l.personne_id, 15, NULL, 8, 6, coalesce(g.code, s.circonscription), NULL, 7, NULL, NULL, s.profession, 'Sénat (en exercice)'
    FROM b.senateurs s JOIN lien_m l ON l.source = 'sen' AND l.ref = s.matricule
    LEFT JOIN b.geo_departement g ON lower(strip_accents(g.libelle)) = lower(strip_accents(s.circonscription))""")
MANDATS.append("""
    SELECT l.personne_id, CASE WHEN s.fonction ILIKE 'président du sénat' THEN 19 WHEN s.fonction ILIKE 'vice-président%' THEN 20
                               WHEN s.fonction ILIKE 'questeur%' THEN 21 ELSE 22 END,
           NULL, 6, 8, 'FR', NULL, 3, NULL, NULL, NULL, 'Sénat (bureau)'
    FROM b.senateurs s JOIN lien_m l ON l.source = 'sen' AND l.ref = s.matricule WHERE s.fonction IS NOT NULL""")

MANDATS.append("""
    SELECT l.personne_id, 14, el('2024_legi'), 1, 5, lpad(CAST(d.num_departement AS VARCHAR), 2, '0') || '-' || CAST(d.circo AS VARCHAR),
           NULL, 7, NULL, NULL, d.profession, 'Assemblée nationale (en exercice)'
    FROM b.deputes d JOIN lien_m l ON l.source = 'dep_an' AND l.ref = d.id
    WHERE d.id NOT IN (SELECT acteur FROM b.mandats_deputes WHERE fin IS NULL)""")
colonnes = ("personne_id, fonction_id, election_id, mode_scrutin_id, zone_niveau_id, zone_code, date_debut, motif_debut_id, "
            "date_fin, motif_fin_id, metier, source")
# (les types fixés une fois pour toutes : une branche qui ne donne que des NULL ne doit pas changer le type d'une colonne)
con.execute(f"""CREATE TABLE mandat_brut AS SELECT CAST(personne_id AS BIGINT) personne_id, CAST(fonction_id AS INTEGER) fonction_id,
                CAST(election_id AS BIGINT) election_id, CAST(mode_scrutin_id AS INTEGER) mode_scrutin_id,
                CAST(zone_niveau_id AS INTEGER) zone_niveau_id, CAST(zone_code AS VARCHAR) zone_code, TRY_CAST(date_debut AS DATE) date_debut,
                CAST(motif_debut_id AS INTEGER) motif_debut_id, TRY_CAST(date_fin AS DATE) date_fin, CAST(motif_fin_id AS INTEGER) motif_fin_id,
                CAST(metier AS VARCHAR) metier, CAST(source AS VARCHAR) source
                FROM ({' UNION ALL '.join(f'SELECT * FROM ({q})' for q in MANDATS)}) x({colonnes})""")
# (un même mandat est vu dans plusieurs versions du RNE, et pour 2014 aussi dans la liste des élus : on n'en garde qu'un,
#  avec la date de début la plus ancienne et le métier quand une source le donne)
con.execute(f"""
CREATE TABLE mandat AS
SELECT row_number() OVER (ORDER BY personne_id NULLS LAST, date_debut, fonction_id) id, *
FROM (SELECT personne_id, fonction_id, election_id, any_value(mode_scrutin_id) mode_scrutin_id, zone_niveau_id, zone_code,
             min(date_debut) date_debut, min(motif_debut_id) motif_debut_id, max(date_fin) date_fin, max(motif_fin_id) motif_fin_id,
             any_value(metier) metier, string_agg(DISTINCT source, ' ; ') source
      FROM mandat_brut
      GROUP BY personne_id, fonction_id, election_id, zone_niveau_id, zone_code,
               CASE WHEN personne_id IS NULL THEN random() END,
               CASE WHEN source LIKE 'Assemblée nationale%' THEN date_debut END,
               CASE WHEN source LIKE 'Assemblée nationale%' THEN coalesce(CAST(date_fin AS VARCHAR), 'en cours') END)""")
# (un élu de 2014 absent du RNE de janvier 2020 est parti en cours de mandat, à une date qu'on ignore)
con.execute("""UPDATE mandat SET date_fin = NULL, motif_fin_id = 10
               WHERE source = 'élus municipaux 2014' AND election_id = el('2014_muni')""")
# le mode de scrutin des conseillers municipaux : celui de la commune à cette élection (listes ou candidats un par un)
con.execute("""
UPDATE mandat SET mode_scrutin_id = CASE WHEN c.listes THEN 2 ELSE 3 END
FROM (SELECT left(code_zone, 5) commune, election, bool_or(vote_de_liste) listes FROM b.candidats_listes
      WHERE conseil = 'municipal' AND election LIKE '%_t1' GROUP BY ALL) c, election e
WHERE mandat.fonction_id = 1 AND mandat.mode_scrutin_id IS NULL AND e.id = mandat.election_id
  AND c.election = e.code || '_t1' AND c.commune = mandat.zone_code""")
con.execute("UPDATE mandat SET mode_scrutin_id = 6 WHERE fonction_id IN (2, 3, 6, 7, 9, 10, 12, 13)")
etape(f"{con.execute('SELECT count(*) FROM mandat').fetchone()[0]:,} mandats".replace(",", " "))

# --- les groupes politiques des députés (avec leurs dates)
con.execute("""
CREATE TABLE appartenance_groupe AS
SELECT row_number() OVER () id, * FROM (
SELECT DISTINCT ON (g.acteur, g.debut, g.groupe) mt.id mandat_id, g.groupe, g.groupe_libelle, g.couleur,
       CAST(g.debut AS DATE) date_debut, CAST(g.fin AS DATE) date_fin
FROM b.groupes_deputes g JOIN identifiant i ON i.source = 'Assemblée nationale' AND i.valeur = g.acteur
JOIN mandat mt ON mt.personne_id = i.personne_id AND mt.fonction_id = 14
     AND CAST(g.debut AS DATE) BETWEEN coalesce(mt.date_debut, DATE '2024-07-07') - INTERVAL 1 DAY AND coalesce(mt.date_fin, DATE '2999-01-01')
-- (la période finie avant la fin du mandat va au mandat fini ; la période ouverte, au mandat en cours)
ORDER BY g.acteur, g.debut, g.groupe, (coalesce(CAST(g.fin AS DATE), DATE '2999-01-01') <= coalesce(mt.date_fin, DATE '2999-01-01')) DESC,
         mt.date_fin NULLS LAST)""")
con.execute("""
INSERT INTO appartenance_groupe
SELECT (SELECT max(id) FROM appartenance_groupe) + row_number() OVER (), mt.id, s.groupe, s.groupe, s.couleur, lg.debut, lg.fin
FROM b.sieges_legislature s JOIN b.legislatures lg USING (legislature)
LEFT JOIN lien_m l ON l.source = 'sieg' AND l.ref = CAST(s.rowid AS VARCHAR)
JOIN mandat mt ON mt.fonction_id = 14 AND mt.date_debut = lg.debut
     AND mt.zone_code = upper(regexp_extract(s.lieu, '·\\s*(\\S+)\\s*$', 1)) || '-' || regexp_extract(s.lieu, '^(\\d+)', 1)
     AND mt.personne_id IS NOT DISTINCT FROM l.personne_id
WHERE s.legislature <= 11""")
# le métier déclaré des députés en exercice
con.execute("""UPDATE mandat SET metier = d.profession FROM b.deputes d, identifiant i
               WHERE i.source = 'Assemblée nationale' AND i.valeur = d.id AND mandat.personne_id = i.personne_id
                 AND mandat.fonction_id = 14 AND mandat.date_fin IS NULL""")
# la place dans l'hémicycle (députés en exercice)
con.execute("ALTER TABLE mandat ADD COLUMN siege INTEGER")
con.execute("""UPDATE mandat SET siege = d.place FROM b.deputes d, identifiant i
               WHERE i.source = 'Assemblée nationale' AND i.valeur = d.id AND mandat.personne_id = i.personne_id
                 AND mandat.fonction_id = 14 AND mandat.date_fin IS NULL""")
con.execute("UPDATE mandat SET siege = NULL WHERE siege IS NOT NULL AND date_fin IS NOT NULL")
con.execute("""INSERT INTO appartenance_groupe
SELECT (SELECT coalesce(max(id), 0) FROM appartenance_groupe) + row_number() OVER (), mt.id, s.groupe, s.groupe, NULL, NULL, NULL
FROM b.senateurs s JOIN identifiant i ON i.source = 'Sénat' AND i.valeur = s.matricule
JOIN mandat mt ON mt.personne_id = i.personne_id AND mt.fonction_id = 15""")

# ------------------------------------------------------------------------------------------------------------------
# 5. Les listes, les candidatures, les photos
# ------------------------------------------------------------------------------------------------------------------
etape("listes, candidatures, photos")
con.execute("""
CREATE TABLE liste AS
SELECT row_number() OVER (ORDER BY election, code_zone, numero_panneau) id, el(regexp_replace(election, '_t\\d$', '')) election_id,
       right(election, 1)::INTEGER tour, conseil,
       CASE conseil WHEN 'arrondissement' THEN 2 WHEN 'métropole' THEN 3 WHEN 'régional' THEN 7 WHEN 'européen' THEN 8 ELSE 1 END zone_niveau_id,
       code_zone zone_code, numero_panneau, any_value(libelle_liste) label, any_value(libelle_abrege) label_abrege,
       any_value(nuance_liste) nuance
FROM b.candidats_listes WHERE numero_panneau IS NOT NULL GROUP BY election, conseil, code_zone, numero_panneau""")
con.execute("""
CREATE TABLE cand_liste AS
SELECT l.personne_id, el(regexp_replace(c.election, '_t\\d$', '')) election_id, right(c.election, 1)::INTEGER tour,
       li.id liste_id, CASE c.conseil WHEN 'arrondissement' THEN 2 WHEN 'métropole' THEN 3 WHEN 'régional' THEN 7 WHEN 'européen' THEN 8 ELSE 1 END zone_niveau_id,
       c.code_zone zone_code, c.libelle_zone zone_libelle, c.code_departement, c.code_region, c.conseil,
       c.ordre rang, c.tete_de_liste, li.nuance, c.profession metier, c.sortant, c.nationalite, c.conseil_communautaire,
       c.vote_de_liste, 'listes déposées' source
FROM b.candidats_listes c JOIN lien_m l ON l.source = 'clist' AND l.ref = CAST(c.rowid AS VARCHAR)
LEFT JOIN liste li ON li.election_id = el(regexp_replace(c.election, '_t\\d$', '')) AND li.tour = right(c.election, 1)::INTEGER
     AND li.conseil = c.conseil AND li.zone_code = c.code_zone AND li.numero_panneau = c.numero_panneau""")
con.execute("""
CREATE TABLE cand_fiche AS
SELECT DISTINCT ON (l.personne_id, d.scrutin) l.personne_id, el(regexp_replace(d.scrutin, '_t\\d$', '')) election_id,
       right(d.scrutin, 1)::INTEGER tour, d.departement code_departement, d.lieu zone_libelle, d.nuance, d.profession metier,
       CAST(d.sortant AS VARCHAR) IN ('OUI', 'Oui', 'True', 'true', '1') sortant
FROM b.candidats_details d JOIN lien_m l ON l.source = 'cdet' AND l.ref = CAST(d.rowid AS VARCHAR)""")
# (une fiche détaillée qui correspond à une candidature d'une liste la complète ; les autres sont des candidatures à part)
con.execute("""
CREATE TABLE candidature AS
SELECT row_number() OVER () id, * FROM (
    SELECT c.personne_id, c.election_id, c.tour, c.liste_id, c.zone_niveau_id, c.zone_code, c.zone_libelle, c.code_departement,
           c.code_region, c.conseil, c.rang, c.tete_de_liste, coalesce(c.nuance, f.nuance) nuance, coalesce(c.metier, f.metier) metier,
           coalesce(c.sortant, f.sortant) sortant, c.nationalite, c.conseil_communautaire, c.vote_de_liste,
           f.personne_id IS NOT NULL fiche_detaillee, CAST(NULL AS BOOLEAN) elu, c.source
    FROM cand_liste c LEFT JOIN cand_fiche f USING (personne_id, election_id, tour)
    UNION ALL
    SELECT f.personne_id, f.election_id, f.tour, NULL, 6, f.code_departement || '|' || coalesce(f.zone_libelle, ''), f.zone_libelle,
           f.code_departement, NULL, NULL, NULL, NULL, f.nuance, f.metier, f.sortant, NULL, NULL, NULL, TRUE, NULL, 'fiches des candidats'
    FROM cand_fiche f ANTI JOIN cand_liste c USING (personne_id, election_id, tour))""")
# élu ou non : la personne a un mandat obtenu à cette élection
con.execute("""UPDATE candidature SET elu = EXISTS (SELECT 1 FROM mandat m WHERE m.personne_id = candidature.personne_id
               AND m.election_id = candidature.election_id) WHERE election_id IN (SELECT DISTINCT election_id FROM mandat)""")
con.execute("""
CREATE TABLE photo AS
SELECT row_number() OVER () id, fichier, adresse, CAST(NULL AS DATE) date, source, licence, mandat_id, CAST(NULL AS BIGINT) candidature_id, personne_id
FROM (SELECT d.photo fichier, 'https://www2.assemblee-nationale.fr/static/tribun/17/photos/carre/' || replace(d.id, 'PA', '') || '.jpg' adresse,
             'Assemblée nationale' source, 'Licence ouverte (open data de l''Assemblée)' licence, mt.id mandat_id, i.personne_id
      FROM b.deputes d JOIN identifiant i ON i.source = 'Assemblée nationale' AND i.valeur = d.id
      LEFT JOIN mandat mt ON mt.personne_id = i.personne_id AND mt.fonction_id = 14 AND mt.date_fin IS NULL WHERE d.photo IS NOT NULL
      UNION ALL
      SELECT s.photo, s.adresse_photo, 'Sénat', 'Photo officielle du Sénat (usage non commercial, source citée)', mt.id, i.personne_id
      FROM b.senateurs s JOIN identifiant i ON i.source = 'Sénat' AND i.valeur = s.matricule
      LEFT JOIN mandat mt ON mt.personne_id = i.personne_id AND mt.fonction_id = 15 WHERE s.photo IS NOT NULL)""")
con.execute("CREATE TABLE photo_personne AS SELECT id photo_id, personne_id FROM photo")
con.execute("ALTER TABLE photo DROP COLUMN personne_id")

# ------------------------------------------------------------------------------------------------------------------
# 6. Le bilan de l'identification
# ------------------------------------------------------------------------------------------------------------------
print()
print(con.execute("""SELECT identification, count(*) personnes, round(100 * count(*) / sum(count(*)) OVER (), 1) "%"
                     FROM personne GROUP BY 1 ORDER BY 2 DESC""").fetchdf().to_string(index=False))
print(con.execute("""SELECT f.label fonction, count(*) mandats, count(DISTINCT personne_id) personnes,
                            count(*) FILTER (WHERE date_fin IS NULL AND motif_fin_id IS NULL) en_cours
                     FROM mandat m JOIN (SELECT * FROM (VALUES """ + ",".join(f"({i}, '{l.replace(chr(39), chr(39) * 2)}')" for i, l, _ in FONCTIONS)
                  + """) v(id, label)) f ON f.id = m.fonction_id GROUP BY 1 ORDER BY 2 DESC""").fetchdf().to_string(index=False))

# ------------------------------------------------------------------------------------------------------------------
# 7. Dans MariaDB (la base de référence)
# ------------------------------------------------------------------------------------------------------------------
# (pendant la construction, référentiel et méthode sont du texte, plus lisible dans les requêtes ci-dessus ; dans la base,
#  chacun a sa table de référence et n'est plus qu'un numéro — les mêmes numéros que les scripts integrer_*)
q = lambda s: "NULL" if s is None else "'" + s.replace("'", "''") + "'"
con.execute("CREATE TABLE referentiel AS SELECT * FROM (VALUES " + ",".join(f"({i}, {q(l)}, {q(u)})" for l, (i, u) in REFERENTIELS.items())
            + ") v(id, libelle, url_modele)")
con.execute("CREATE TABLE methode_identification AS SELECT * FROM (VALUES " + ",".join(f"({i}, {q(l)})" for l, i in METHODES.items())
            + ") v(id, libelle)")
con.execute("""CREATE OR REPLACE TABLE identifiant AS SELECT i.personne_id, r.id referentiel_id, i.valeur
               FROM identifiant i JOIN referentiel r ON r.libelle = i.source""")
con.execute("""CREATE OR REPLACE TABLE personne AS SELECT p.* EXCLUDE (identification), m.id identification_id
               FROM personne p LEFT JOIN methode_identification m ON m.libelle = p.identification""")
# les sources : la table source de MariaDB, commune à toute la base (outils_mariadb.sources) ; un mandat peut en citer
# plusieurs (« rne_municipaux 2020-01 ; élus municipaux 2014 ») → une ligne par source dans mandat_source
PHOTOS = {"Assemblée nationale": "photos Assemblée nationale", "Sénat": "photos Sénat"}
cles = [c for (c,) in con.execute("""SELECT DISTINCT trim(unnest(string_split(source, ';'))) FROM mandat
                                     UNION SELECT DISTINCT source FROM candidature""").fetchall() if c]
src = sources(sorted(set(cles)) + list(PHOTOS.values()))
con.register("src", pd.DataFrame({"cle": list(src), "source_id": list(src.values())}))
con.register("src_photo", pd.DataFrame({"ancienne": list(PHOTOS), "cle": list(PHOTOS.values())}))
con.execute("""CREATE TABLE mandat_source AS SELECT DISTINCT m.mandat_id, s.source_id
               FROM (SELECT id mandat_id, trim(unnest(string_split(source, ';'))) cle FROM mandat) m JOIN src s USING (cle)""")
con.execute("CREATE OR REPLACE TABLE mandat AS SELECT * EXCLUDE (source) FROM mandat")
con.execute("""CREATE OR REPLACE TABLE candidature AS SELECT c.* EXCLUDE (source), s.source_id
               FROM candidature c JOIN src s ON s.cle = c.source""")
con.execute("""CREATE OR REPLACE TABLE photo AS SELECT p.* EXCLUDE (source), s.source_id
               FROM photo p JOIN src_photo a ON a.ancienne = p.source JOIN src s ON s.cle = a.cle""")
TABLES = {  # table : (clé primaire, [(colonne, clé étrangère vers)], index)
    "zone_niveau": ("id", [("parent_id", "zone_niveau")], []),
    "fonction": ("id", [], []), "type_election": ("id", [], []), "mode_scrutin": ("id", [], []),
    "motif_debut": ("id", [], []), "motif_fin": ("id", [], []),
    "fonction_duree": ("fonction_id, en_vigueur_le", [("fonction_id", "fonction")], []),
    "incompatibilite": ("fonction_a_id, fonction_b_id, en_vigueur_le", [("fonction_a_id", "fonction"), ("fonction_b_id", "fonction")], []),
    "election": ("id", [("type_election_id", "type_election")], ["code"]),
    "referentiel": ("id", [], []), "methode_identification": ("id", [], []),
    "personne": ("id", [("identification_id", "methode_identification")], ["nom_usage, prenoms", "date_naissance"]),
    "identifiant": ("personne_id, referentiel_id, valeur", [("personne_id", "personne"), ("referentiel_id", "referentiel")],
                    ["referentiel_id, valeur"]),
    "mandat": ("id", [("personne_id", "personne"), ("fonction_id", "fonction"), ("election_id", "election"),
                      ("mode_scrutin_id", "mode_scrutin"), ("zone_niveau_id", "zone_niveau"), ("motif_debut_id", "motif_debut"),
                      ("motif_fin_id", "motif_fin")], ["zone_niveau_id, zone_code", "date_debut"]),
    "mandat_source": ("mandat_id, source_id", [("mandat_id", "mandat"), ("source_id", "source")], ["source_id"]),
    "appartenance_groupe": ("id", [("mandat_id", "mandat")], ["groupe"]),
    "liste": ("id", [("election_id", "election"), ("zone_niveau_id", "zone_niveau")], ["zone_code"]),
    "candidature": ("id", [("personne_id", "personne"), ("election_id", "election"), ("liste_id", "liste"),
                           ("zone_niveau_id", "zone_niveau"), ("source_id", "source")], ["zone_code"]),
    "photo": ("id", [("mandat_id", "mandat"), ("candidature_id", "candidature"), ("source_id", "source")], []),
    "photo_personne": ("photo_id, personne_id", [("photo_id", "photo"), ("personne_id", "personne")], []),
}
con.execute("CREATE TABLE zone_niveau AS SELECT * FROM (VALUES " + ",".join(f"({i}, '{l}', {p if p else 'NULL'})" for i, l, p in ZONES)
            + ") v(id, label, parent_id)")
con.execute("CREATE TABLE fonction AS SELECT * FROM (VALUES " + ",".join(f"({i}, '{l.replace(chr(39), chr(39) * 2)}', {Z.get(n, 8)})"
            for i, l, n in FONCTIONS) + ") v(id, label, zone_niveau_id)")
con.execute("CREATE TABLE fonction_duree AS SELECT * FROM (VALUES " + ",".join(f"({f}, {d}, DATE '{e}')" for f, d, e in DUREES)
            + ") v(fonction_id, duree, en_vigueur_le)")
con.execute("CREATE TABLE incompatibilite AS SELECT * FROM (VALUES " + ",".join(
    f"({a}, {b_}, DATE '{e}', {('DATE ' + repr(f)) if f else 'CAST(NULL AS DATE)'}, '{t.replace(chr(39), chr(39) * 2)}')"
    for a, b_, e, f, t in INCOMPATIBILITES) + ") v(fonction_a_id, fonction_b_id, en_vigueur_le, fin_vigueur, texte)")
con.execute("CREATE TABLE mode_scrutin AS SELECT * FROM (VALUES " + ",".join(f"({i}, '{l.replace(chr(39), chr(39) * 2)}')" for i, l in MODES)
            + ") v(id, label)")
con.execute("CREATE TABLE motif_debut AS SELECT * FROM (VALUES " + ",".join(f"({i}, '{l.replace(chr(39), chr(39) * 2)}')" for i, l in MOTIFS_DEBUT)
            + ") v(id, label)")
con.execute("CREATE TABLE motif_fin AS SELECT * FROM (VALUES " + ",".join(f"({i}, '{l.replace(chr(39), chr(39) * 2)}', {str(r).upper()})"
            for i, l, r in MOTIFS_FIN) + ") v(id, label, appelle_remplacant)")

deja = mx.mysql("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'grand_depouillement' AND table_name = 'personne'")
if int(deja.split()[-1]) and "--refaire" not in sys.argv:
    sys.exit("La table personne existe déjà dans MariaDB : c'est elle qui fait foi. Relancer avec --refaire pour repartir de zéro.")
if int(deja.split()[-1]):
    sauvegarde = DECHET / f"modele_avant_refaire_{time.strftime('%Y%m%d_%H%M')}.sql"
    sauvegarde.parent.mkdir(parents=True, exist_ok=True)
    with open(sauvegarde, "w", encoding="utf-8") as f:
        import subprocess
        subprocess.run([str(mx.MYSQL.parent / "mysqldump.exe"), "-u", "root", "grand_depouillement", *TABLES], stdout=f, check=True)
    etape(f"ancien modèle sauvegardé dans {sauvegarde}")

etape("chargement dans MariaDB")
mx.mysql("SET foreign_key_checks = 0; " + " ".join(f"DROP TABLE IF EXISTS `{t}`;" for t in reversed(list(TABLES))))
for t, (pk, fks, index) in TABLES.items():
    colonnes = con.execute(f"SELECT column_name, column_type FROM (DESCRIBE {t})").fetchall()
    types = [(c, mx.type_mariadb(con, t, c, ty)) for c, ty in colonnes]
    defs = [f"`{c}` {ty} {'NOT NULL' if c in pk.replace(' ', '').split(',') else 'NULL'}" for c, ty in types]
    defs.append(f"PRIMARY KEY ({', '.join('`' + c.strip() + '`' for c in pk.split(','))})")
    defs += [f"KEY `ix_{t}_{i}` ({', '.join('`' + c.strip() + '`' for c in ix.split(','))})" for i, ix in enumerate(index)]
    if t == "photo":   # (une photo est liée à un mandat OU à une candidature, pas aux deux)
        defs.append("CONSTRAINT `un_seul_lien` CHECK (`mandat_id` IS NULL OR `candidature_id` IS NULL)")
    mx.mysql(f"CREATE TABLE `{t}` ({', '.join(defs)}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci")
    n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    with tempfile.TemporaryDirectory() as dossier:
        fichier = Path(dossier) / f"{t}.tsv"
        for debut in range(0, max(n, 1), mx.BLOC):
            textes = [c for c, ty in colonnes if ty.upper().startswith("VARCHAR")]
            force = f", FORCE_QUOTE ({', '.join(chr(34) + c + chr(34) for c in textes)})" if textes else ""
            con.execute(f"""COPY (SELECT {mx.selection(colonnes)} FROM {t} ORDER BY 1 LIMIT {mx.BLOC} OFFSET {debut})
                            TO '{fichier.as_posix()}' (FORMAT csv, DELIMITER '\t', QUOTE '"', ESCAPE '"', NULLSTR 'NULL', HEADER false{force})""")
            mx.mysql(f"""SET foreign_key_checks = 0; LOAD DATA LOCAL INFILE '{fichier.as_posix()}' INTO TABLE `{t}` CHARACTER SET utf8mb4
                         FIELDS TERMINATED BY '\\t' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '' LINES TERMINATED BY '\\n'
                         ({', '.join('`' + c + '`' for c, _ in colonnes)})""")
    copie = int(mx.mysql(f"SELECT count(*) FROM `{t}`").split()[-1])
    etape(f"   {t:22s} {n:>11,} lignes {'ok' if copie == n else 'ÉCART ' + str(n - copie)}".replace(",", " "))
# les clés étrangères, une fois tout chargé (MariaDB vérifie alors chaque lien)
# (foreign_key_checks = 0 : MariaDB pose la clé sans recopier la table — quelques secondes au lieu de 25 minutes —,
#  et on vérifie soi-même juste après qu'aucune ligne ne pointe dans le vide)
orphelins = 0
for t, (pk, fks, index) in TABLES.items():
    for col, cible in fks:
        mx.mysql(f"SET foreign_key_checks = 0; ALTER TABLE `{t}` ADD CONSTRAINT `fk_{t}_{col}` FOREIGN KEY (`{col}`) REFERENCES `{cible}` (`id`)")
        n = int(mx.mysql(f"SELECT count(*) FROM `{t}` x LEFT JOIN `{cible}` c ON c.id = x.`{col}` WHERE x.`{col}` IS NOT NULL AND c.id IS NULL").split()[-1])
        if n:
            print(f"   ⚠ {t}.{col} : {n} lignes pointent vers un {cible} inexistant")
            orphelins += n
etape("clés étrangères posées et vérifiées : " + ("aucun lien cassé" if not orphelins else f"{orphelins} liens cassés"))
etape("modèle construit dans MariaDB (base grand_depouillement)")
