"""
integrer_partis.py — Les partis politiques (groupe ≠ parti : la NUPES est une coalition de partis, le groupe GDR réunit
le PCF et le PG ; un candidat, élu ou non, peut être membre d'un parti).

    py integrer_partis.py          (MariaDB de XAMPP démarré ; relançable : refait les tables des partis)

Sources : d'abord la liste officielle de la CNCCFP (comptes des partis 2008-2024, BRUT/compte campagne →
donnees/partis/partis_cnccfp.tsv : le code CNCCFP reste le même quand un parti change de nom) ; Wikidata ensuite
(BRUT/wikidata/partis : sigles, dates, coalitions, idéologies, positions, adhésions des personnes).

    nature_parti (id, libelle)                     parti politique, coalition politique, groupement (CNCCFP)
    parti (id, libelle, sigle, nature_parti_id, date_creation, date_dissolution, remplace_parti_id, code_cnccfp,
           wikidata, nuance_id)                    nuance_id : la nuance du ministère de même nom (PS → SOC)
    parti_membre (coalition_id, parti_id)          les partis d'une coalition (NUPES : LFI, PS, PCF, EELV…)
    ideologie (id, libelle, wikidata)              la liste de Julien + celles de Wikidata
    parti_ideologie (parti_id, ideologie_id)
    position_politique (id, libelle, wikidata)     gauche, centre droit…   + parti_position (parti_id, position_politique_id)
    adhesion (id, personne_id, parti_id, date_debut, date_fin, source_id)   (personnes de la base, par leur Wikidata)
    groupe_parti (groupe_id, parti_id)             les groupes de l'Assemblée d'aujourd'hui formés d'un seul parti
Les dates de Wikidata sont gardées au jour (« 1969-05-04 »).
"""
import re
import sys
import time
from pathlib import Path

import pandas as pd

from outils_mariadb import charger, cle_etrangere, mysql, norm, requete, sauvegarder, sources

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
CNCCFP = C.SAISIES / "partis" / "partis_cnccfp.tsv"
WIKIDATA = C.BRUT / "wikidata" / "partis"
DECHET = C.DECHET
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
WIKIDATA_REF = 3                       # (referentiel : Wikidata)
NATURES = [(1, "parti politique"), (2, "coalition politique"), (3, "groupement politique (CNCCFP)")]
# la liste de départ de Julien (2 novembre 2026)
IDEOLOGIES_JULIEN = ["Progressisme", "Social-démocratie", "Social-écologie", "Europhilie", "Socialisme démocratique",
                     "Socialisme", "Réformisme", "Écosocialisme", "Social-libéralisme", "Anticapitalisme", "Marxisme"]
# les groupes de la XVIIe législature formés d'un seul parti (code du groupe → libellé du parti dans Wikidata)
GROUPES_PARTI = {"RN": "Rassemblement national", "LFI-NFP": "La France insoumise", "SOC": "Parti socialiste",
                 "EPR": "Renaissance", "DR": "Les Républicains", "DEM": "Mouvement démocrate", "HOR": "Horizons",
                 "UDDPLR": "Union des droites pour la République"}


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def qid(url):
    return url.rsplit("/", 1)[-1] if isinstance(url, str) else None


def jour(v):
    return v[:10] if isinstance(v, str) and re.match(r"\d{4}-\d\d-\d\d", v) else None


AXES = [(1, "gauche – droite", "gauche", "droite"), (2, "Europe", "souverainisme", "europhilie")]
# la place gauche – droite de chaque position politique de Wikidata (-2 à +2 ; « indépendance », « attrape-tout » : aucune)
POSITIONS = {"extrême gauche": -2, "gauche radicale": -1.75, "gauche": -1.25, "centre gauche": -0.5, "centrisme": 0, "Modéré": 0,
             "centre droit": 0.5, "droite": 1.25, "extrême droite": 2, "extrême droite politique": 2}
AXES_CSV = C.SAISIES / "partis" / "ideologies_axes.csv"


def axes(ideologies, positions):
    """L'échiquier : axe (gauche – droite, Europe), la valeur de chaque idéologie sur chaque axe (-2 à +2, lue dans
    donnees/partis/ideologies_axes.csv, que Julien corrige et complète — les idéologies nouvelles y sont
    ajoutées vides), et la place gauche – droite de chaque position politique (position_politique.valeur)."""
    lu = pd.read_csv(AXES_CSV, sep=";", dtype=str, encoding="utf-8-sig") if AXES_CSV.exists() else \
        pd.DataFrame(columns=["ideologie", "gauche_droite", "europe", "remarque"])
    manquantes = sorted(set(ideologies.libelle) - set(lu.ideologie))
    lu = pd.concat([lu, pd.DataFrame({"ideologie": manquantes})], ignore_index=True)
    lu.to_csv(AXES_CSV, sep=";", index=False, encoding="utf-8-sig")
    id_ideo = dict(zip(ideologies.libelle, ideologies.id))
    valeurs = []
    for r in lu.itertuples():
        for axe, col in ((1, r.gauche_droite), (2, r.europe)):
            if r.ideologie in id_ideo and isinstance(col, str) and col.strip():
                valeurs.append((id_ideo[r.ideologie], axe, float(col.replace(",", "."))))
    mysql(f"""DROP TABLE IF EXISTS ideologie_axe; DROP TABLE IF EXISTS axe;
              CREATE TABLE axe (id INT PRIMARY KEY, libelle VARCHAR(40) NOT NULL, pole_moins VARCHAR(40), pole_plus VARCHAR(40)) {T};
              CREATE TABLE ideologie_axe (ideologie_id INT NOT NULL, axe_id INT NOT NULL, valeur DECIMAL(3,2) NOT NULL,
                PRIMARY KEY (ideologie_id, axe_id)) {T};
              INSERT INTO axe VALUES """ + ", ".join(f"({i}, '{l}', '{m}', '{p}')" for i, l, m, p in AXES) + ";"
          + "ALTER TABLE position_politique ADD COLUMN valeur DECIMAL(3,2) NULL;"
          + "".join(f"UPDATE position_politique SET valeur = {v} WHERE libelle = '{l}';" for l, v in POSITIONS.items()))
    if valeurs:
        charger("ideologie_axe", pd.DataFrame(valeurs, columns=["ideologie_id", "axe_id", "valeur"]))
    cle_etrangere("ideologie_axe", "ideologie_id", "ideologie")
    cle_etrangere("ideologie_axe", "axe_id", "axe")
    etape(f"échiquier : {len(valeurs)} valeurs d'idéologies sur 2 axes ({len(manquantes)} idéologies nouvelles ajoutées vides "
          f"au fichier {AXES_CSV.name})")


def main():
    t0 = time.time()
    w = pd.read_csv(WIKIDATA / "partis_wikidata.csv", dtype=str)
    w["q"] = w.parti.map(qid)
    w = w[~w.partiLabel.str.match(r"^Q\d+$", na=True)]
    c = pd.read_csv(CNCCFP, sep="\t", dtype=str)

    # 1. les partis : ceux de Wikidata, reliés à la CNCCFP par le nom (nom actuel, anciens noms, alias, sigle)
    wp = w.groupby("q").agg(libelle=("partiLabel", "first"), sigle=("sigle", lambda s: s.dropna().iloc[0] if s.notna().any() else None),
                            creation=("creation", "min"), dissolution=("dissolution", "max"),
                            nature=("natureLabel", lambda s: "coalition politique" if (s == "coalition politique").any() else "parti politique"),
                            succede=("succede", lambda s: qid(s.dropna().iloc[0]) if s.notna().any() else None),
                            noms=("alias", lambda s: set(s.dropna()))).reset_index()
    par_nom = {}
    for r in wp.itertuples():
        for n in {r.libelle, *(r.noms or set())}:
            par_nom.setdefault(norm(n), r.q)
    c["q"] = [next((par_nom[norm(n)] for n in [nom, *str(autres).split(" | ")] if isinstance(n, str) and norm(n) in par_nom), None)
              for nom, autres in zip(c.nom, c.autres_noms)]
    c = pd.concat([c[c.q.notna()].drop_duplicates("q", keep="last"), c[c.q.isna()]])   # (un parti Wikidata = un code CNCCFP)
    lignes = []
    for r in wp.itertuples():
        cc = c[c.q == r.q]
        lignes.append({"libelle": r.libelle, "sigle": r.sigle, "nature": r.nature, "date_creation": jour(r.creation),
                       "date_dissolution": jour(r.dissolution), "succede": r.succede,
                       "code_cnccfp": cc.code.iloc[0] if len(cc) else None, "wikidata": r.q})
    for r in c[c.q.isna()].itertuples():           # (partis de la CNCCFP que Wikidata ne connaît pas sous ce nom)
        lignes.append({"libelle": r.nom.title() if r.nom.isupper() else r.nom, "sigle": None, "nature": "groupement politique (CNCCFP)",
                       "date_creation": None, "date_dissolution": None, "succede": None, "code_cnccfp": r.code, "wikidata": None})
    p = pd.DataFrame(lignes)
    p.insert(0, "id", range(1, len(p) + 1))
    p["nature_parti_id"] = p.nature.map({l: i for i, l in NATURES})
    par_q = dict(zip(p.wikidata, p.id))
    p["remplace_parti_id"] = p.succede.map(par_q)
    # la nuance du ministère dont l'explication est le nom du parti (« Parti socialiste » → SOC)
    nu = requete("SELECT id, libelle, explication FROM nuance WHERE explication IS NOT NULL")
    par_expl = {}
    for i, code, e in nu.itertuples(index=False):
        if not code.startswith(("L", "BC-")):
            par_expl.setdefault(norm(e), int(i))
    p["nuance_id"] = p.libelle.map(lambda l: par_expl.get(norm(l)))
    etape(f"parti : {len(p)} ({p.wikidata.notna().sum()} Wikidata, {p.code_cnccfp.notna().sum()} CNCCFP, "
          f"{(p.wikidata.notna() & p.code_cnccfp.notna()).sum()} les deux ; {p.nuance_id.notna().sum()} avec leur nuance)")

    # 2. coalitions, idéologies, positions, adhésions
    membres = w.dropna(subset=["membre"]).assign(m=lambda x: x.membre.map(qid))[["q", "m"]].drop_duplicates()
    membres = pd.DataFrame({"coalition_id": membres.q.map(par_q), "parti_id": membres.m.map(par_q)}).dropna().astype(int).drop_duplicates()
    ideo = w.dropna(subset=["ideologie"]).assign(i=lambda x: x.ideologie.map(qid))[["q", "i", "ideologieLabel"]].drop_duplicates()
    noms_ideo = dict(zip(ideo.i, ideo.ideologieLabel.str[:1].str.upper() + ideo.ideologieLabel.str[1:]))
    ideologies = pd.DataFrame({"libelle": IDEOLOGIES_JULIEN})
    par_nom_ideo = {norm(v): k for k, v in noms_ideo.items()}
    ideologies["wikidata"] = ideologies.libelle.map(lambda l: par_nom_ideo.get(norm(l)))
    autres = [(v, k) for k, v in noms_ideo.items() if k not in set(ideologies.wikidata.dropna()) and not re.match(r"^Q\d+$", v)]
    ideologies = pd.concat([ideologies, pd.DataFrame(autres, columns=["libelle", "wikidata"])], ignore_index=True)
    ideologies = ideologies.drop_duplicates("libelle")
    ideologies.insert(0, "id", range(1, len(ideologies) + 1))
    id_ideo = dict(zip(ideologies.wikidata, ideologies.id))
    p_ideo = pd.DataFrame({"parti_id": ideo.q.map(par_q), "ideologie_id": ideo.i.map(id_ideo)}).dropna().astype(int).drop_duplicates()
    pos = w.dropna(subset=["position"]).assign(i=lambda x: x.position.map(qid))[["q", "i", "positionLabel"]].drop_duplicates()
    positions = pos.drop_duplicates("i")[["positionLabel", "i"]].rename(columns={"positionLabel": "libelle", "i": "wikidata"})
    positions = positions[~positions.libelle.str.match(r"^Q\d+$")].reset_index(drop=True)
    positions.insert(0, "id", range(1, len(positions) + 1))
    p_pos = pd.DataFrame({"parti_id": pos.q.map(par_q), "position_politique_id": pos.i.map(dict(zip(positions.wikidata, positions.id)))})
    p_pos = p_pos.dropna().astype(int).drop_duplicates()
    a = pd.read_csv(WIKIDATA / "adhesions_wikidata.csv", dtype=str)
    ids = requete(f"SELECT personne_id, valeur FROM identifiant WHERE referentiel_id = {WIKIDATA_REF}")
    a = a.assign(valeur=a.personne.map(qid), parti_id=a.parti.map(qid).map(par_q)).merge(ids, on="valeur")
    a = a.dropna(subset=["parti_id"])
    src = sources(["wikidata"])["wikidata"]
    adhesions = pd.DataFrame({"personne_id": a.personne_id.astype("int64"), "parti_id": a.parti_id.astype(int),
                              "date_debut": a.debut.map(jour), "date_fin": a.fin.map(jour), "source_id": src}).drop_duplicates()
    adhesions.insert(0, "id", range(1, len(adhesions) + 1))
    g = requete("SELECT id, code FROM groupe WHERE fonction_id = 14")
    par_libelle = dict(zip(p.libelle, p.id))
    groupe_parti = pd.DataFrame([(int(i), par_libelle[GROUPES_PARTI[code]]) for i, code in g.itertuples(index=False)
                                 if code in GROUPES_PARTI and GROUPES_PARTI[code] in par_libelle], columns=["groupe_id", "parti_id"])

    # 3. dans MariaDB (les tables des partis sont refaites ; sauvegarde avant)
    # (investiture pointe vers parti : elle est refaite ensuite par integrer_investitures.py)
    vieilles = [t for t in ("investiture", "groupe_parti", "adhesion", "parti_position", "position_politique", "parti_ideologie", "ideologie",
                            "parti_membre", "parti", "nature_parti") if len(requete(f"SHOW TABLES LIKE '{t}'"))]
    if vieilles:
        etape("sauvegarde : " + sauvegarder(DECHET, "partis_avant_refaire", vieilles).name)
        mysql("SET foreign_key_checks = 0; " + " ".join(f"DROP TABLE `{t}`;" for t in vieilles))
    mysql(f"""CREATE TABLE nature_parti (id INT PRIMARY KEY, libelle VARCHAR(40) NOT NULL) {T};
              CREATE TABLE parti (id INT PRIMARY KEY, libelle VARCHAR(200) NOT NULL, sigle VARCHAR(40), nature_parti_id INT NOT NULL,
                date_creation DATE, date_dissolution DATE, remplace_parti_id INT, code_cnccfp INT, wikidata VARCHAR(20), nuance_id INT,
                KEY ix_parti_libelle (libelle), KEY ix_parti_cnccfp (code_cnccfp)) {T};
              CREATE TABLE parti_membre (coalition_id INT NOT NULL, parti_id INT NOT NULL, PRIMARY KEY (coalition_id, parti_id)) {T};
              CREATE TABLE ideologie (id INT PRIMARY KEY, libelle VARCHAR(120) NOT NULL, wikidata VARCHAR(20)) {T};
              CREATE TABLE parti_ideologie (parti_id INT NOT NULL, ideologie_id INT NOT NULL, PRIMARY KEY (parti_id, ideologie_id)) {T};
              CREATE TABLE position_politique (id INT PRIMARY KEY, libelle VARCHAR(80) NOT NULL, wikidata VARCHAR(20)) {T};
              CREATE TABLE parti_position (parti_id INT NOT NULL, position_politique_id INT NOT NULL,
                PRIMARY KEY (parti_id, position_politique_id)) {T};
              CREATE TABLE adhesion (id INT PRIMARY KEY, personne_id BIGINT NOT NULL, parti_id INT NOT NULL, date_debut DATE,
                date_fin DATE, source_id INT, KEY ix_adhesion_personne (personne_id)) {T};
              CREATE TABLE groupe_parti (groupe_id INT NOT NULL, parti_id INT NOT NULL, PRIMARY KEY (groupe_id, parti_id)) {T};
              INSERT INTO nature_parti VALUES """ + ", ".join(f"({i}, '{l}')" for i, l in NATURES) + ";")
    charger("parti", p[["id", "libelle", "sigle", "nature_parti_id", "date_creation", "date_dissolution", "remplace_parti_id",
                        "code_cnccfp", "wikidata", "nuance_id"]])
    for t, df in [("parti_membre", membres), ("ideologie", ideologies), ("parti_ideologie", p_ideo),
                  ("position_politique", positions), ("parti_position", p_pos), ("adhesion", adhesions), ("groupe_parti", groupe_parti)]:
        if len(df):
            charger(t, df)
    for t, col, ref in [("parti", "nature_parti_id", "nature_parti"), ("parti", "remplace_parti_id", "parti"), ("parti", "nuance_id", "nuance"),
                        ("parti_membre", "coalition_id", "parti"), ("parti_membre", "parti_id", "parti"),
                        ("parti_ideologie", "parti_id", "parti"), ("parti_ideologie", "ideologie_id", "ideologie"),
                        ("parti_position", "parti_id", "parti"), ("parti_position", "position_politique_id", "position_politique"),
                        ("adhesion", "personne_id", "personne"), ("adhesion", "parti_id", "parti"), ("adhesion", "source_id", "source"),
                        ("groupe_parti", "groupe_id", "groupe"), ("groupe_parti", "parti_id", "parti")]:
        cle_etrangere(t, col, ref)
    etape(f"coalitions : {len(membres)} liens ; idéologies : {len(ideologies)} ({len(p_ideo)} liens) ; positions : "
          f"{len(positions)} ({len(p_pos)}) ; adhésions : {len(adhesions)} ({adhesions.personne_id.nunique()} personnes) ; "
          f"groupes : {len(groupe_parti)}")
    axes(ideologies, positions)
    etape(f"partis : fini en {time.time() - t0:.0f} s")
    import integrer_investitures
    integrer_investitures.main()


if __name__ == "__main__":
    main()
