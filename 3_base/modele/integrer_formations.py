"""
integrer_formations.py — Ajoute à MariaDB les écoles (ENA, Sciences Po, X…) et les grands corps (Conseil d'État,
Cour des comptes, Inspection des finances, Conseil constitutionnel). À lancer après integrer_nominations.py.

    py integrer_formations.py              (refuse si la table formation existe déjà)
    py integrer_formations.py --refaire    (sauvegarde d'abord personne, identifiant, nomination, ecole, formation dans PROJET/DECHET)

Validé le 1er novembre 2026 :
    ecole        (id, libelle, wikidata, annee_creation, annee_fermeture)
    promotion    (id, ecole_id, libelle, wikidata)          « promotion Voltaire » (une seule fois, pas sur chaque élève)
    formation    (id, personne_id, ecole_id, promotion_id, annee_entree, annee_sortie, source_id)
    les grands corps sont des nominations (fonctions 32 à 35, postes ajoutés à la table poste), sans gouvernement,
    au niveau du pays ; source, licence et precision_date sont les tables créées par integrer_nominations.py.

Sources (PROJET/BRUT/wikidata, téléchargées le 1er novembre 2026) : ecole_ena.csv, ecole_sciencespo.csv, ecole_elsp.csv,
ecole_polytechnique.csv, grands_corps_wikidata.csv. Wikidata ne garde que les gens « notables » : une promotion n'y est
jamais complète (les arrêtés de sortie du Journal officiel le seraient).

Qui est qui ? Même identifiant Wikidata, Assemblée ou Sénat ; sinon même nom + premier prénom + date de naissance (une seule
personne) ; sinon une nouvelle personne (identification_id : « formation : Wikidata »). Le nom vient du libellé Wikidata
« Prénom Nom » : le premier mot est le prénom.
"""
import re
import sys
import time
from pathlib import Path

import pandas as pd

from outils_mariadb import (METHODES, METHODES_FORMATION, charger, charger_identifiants, charger_personnes, cle,
                            cle_etrangere, jour, sources,
                            lire_identifiants, mysql, norm, requete, sauvegarder)

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
WIKIDATA = C.BRUT / "wikidata"
DECHET = C.DECHET
debut_chrono = time.time()

ECOLES = [  # id, nom, Wikidata, création, fermeture, fichier
    (1, "École nationale d'administration", "Q273579", 1945, 2021, "ecole_ena.csv"),
    (2, "Institut d'études politiques de Paris (Sciences Po)", "Q859363", 1945, None, "ecole_sciencespo.csv"),
    (3, "École libre des sciences politiques", "Q273553", 1872, 1945, "ecole_elsp.csv"),
    (4, "École polytechnique", "Q273626", 1794, None, "ecole_polytechnique.csv"),
    # (les instituts régionaux d'administration : listes de sortie du Journal officiel, lues par lire_jorf.py)
    (5, "Institut régional d'administration de Bastia", None, None, None, None),
    (6, "Institut régional d'administration de Lille", None, None, None, None),
    (7, "Institut régional d'administration de Lyon", None, None, None, None),
    (8, "Institut régional d'administration de Metz", None, None, None, None),
    (9, "Institut régional d'administration de Nantes", None, None, None, None),
]
IRA = {"Bastia": 5, "Lille": 6, "Lyon": 7, "Lyon-Villeurbanne": 7, "Metz": 8, "Nantes": 9}
JORF = C.DONNEES / "jorf"
SOURCE_JO = sources(["jorf"])["jorf"]
CORPS_JO = {"Conseil d'État": "Q769657", "Cour des comptes": "Q1137614", "Inspection générale des finances": "Q3151643",
            "Conseil constitutionnel": "Q1127218"}
SOURCE_WIKIDATA = sources(["wikidata"])["wikidata"]   # (table source commune : outils_mariadb)
PRECISION = {"jour": 1, "année": 2}
CORPS = {  # Wikidata du corps → (fonction, libellé)
    "Q769657": (32, "membre du Conseil d'État"), "Q1137614": (33, "magistrat de la Cour des comptes"),
    "Q3151643": (34, "inspecteur des finances"), "Q1127218": (35, "membre du Conseil constitutionnel"),
}


# (101 personnes sans libellé français ni anglais au téléchargement : leur libellé lu ensuite dans Wikidata)
LIBELLES = pd.read_csv(WIKIDATA / "libelles_complementaires.csv", dtype=str).set_index("q").libelle.to_dict()


def etape(texte):
    print(f"[{time.time() - debut_chrono:6.0f} s] {texte}", flush=True)


def date_sure(v):
    """Une date Wikidata, sauf les dates inconnues qu'il écrit « 0000-… » ou les fautes de frappe (« 0202-09-16 »)."""
    d = jour(v)
    return d if d and "1700" <= d[:4] <= "2100" else None


def annee_sure(v):
    d = date_sure(v)
    return d[:4] if d else None


# ------------------------------------------------------------------------------------------------------------------
# 0. Refaire ?
# ------------------------------------------------------------------------------------------------------------------
tables = requete("SHOW TABLES").iloc[:, 0].tolist()
if "nomination" not in tables:
    sys.exit("Lancer d'abord integrer_nominations.py (la table nomination n'existe pas).")
existe = "formation" in tables
if existe and "--refaire" not in sys.argv:
    sys.exit("La table formation existe déjà : relancer avec --refaire pour tout reprendre.")
sauvegarde = sauvegarder(DECHET, "formations_avant_refaire" if existe else "personnes_avant_formations",
                         ["personne", "identifiant", "nomination", "poste", "fonction"]
                         + (["ecole", "promotion", "formation"] if existe else []))
etape(f"sauvegarde : {sauvegarde.name}")
if existe:
    CREES = "(" + ", ".join(map(str, METHODES_FORMATION)) + ")"   # (personnes créées par ce script)
    mysql(f"""SET foreign_key_checks = 0; DROP TABLE formation; DROP TABLE promotion; DROP TABLE ecole;
             DELETE n FROM nomination n JOIN poste p ON p.id = n.poste_id WHERE p.fonction_id BETWEEN 32 AND 35;
             DELETE FROM poste WHERE fonction_id BETWEEN 32 AND 35;
             DELETE i FROM identifiant i JOIN personne p ON p.id = i.personne_id WHERE p.identification_id IN {CREES};
             DELETE FROM personne WHERE identification_id IN {CREES}; DELETE FROM fonction WHERE id BETWEEN 32 AND 35;
             SET foreign_key_checks = 1;""")

# ------------------------------------------------------------------------------------------------------------------
# 1. Les personnes déjà connues
# ------------------------------------------------------------------------------------------------------------------
etape("lecture des personnes de la base")
personnes = requete("SELECT id, nom_usage, prenoms, date_naissance, identification_id FROM personne")
personnes["cle"] = [cle(n, p) for n, p in zip(personnes.nom_usage, personnes.prenoms)]
par_naissance = personnes.dropna(subset=["date_naissance"]).groupby(["cle", "date_naissance"]).id.agg(list).to_dict()
# (les membres de gouvernement sans date de naissance — liste 1944-2014 non reconnue par Wikidata, ou député sans date :
#  on les rattache par le nom seul quand il n'y en a qu'un, sinon Simone Veil ministre et Simone Veil au Conseil
#  constitutionnel seraient deux personnes)
gouvernants = requete("""SELECT DISTINCT n.personne_id FROM nomination n JOIN poste p ON p.id = n.poste_id
                         WHERE p.fonction_id <> 29""").personne_id
ministres_sans_date = (personnes[personnes.id.isin(gouvernants) & personnes.date_naissance.isna()]
                       .groupby("cle").id.agg(list).to_dict())
ident = lire_identifiants()
par_ident = {(s, v): p for p, s, v in ident.itertuples(index=False)}
prochain_id = int(personnes.id.astype("int64").max()) + 1
nouvelles, nouveaux_ident, dates_trouvees, crees_wikidata = [], [], [], {}


def qui(r):
    """Une ligne Wikidata (p, pLabel, naissance, an, senat) → id de la personne (créée au besoin), façon de la reconnaître."""
    global prochain_id
    q = re.search(r"Q\d+", r.p)[0]
    naissance = date_sure(r.naissance)
    prenom, _, nom = LIBELLES.get(q, str(r.pLabel)).partition(" ")
    if ("Wikidata", q) in par_ident:
        return par_ident[("Wikidata", q)], "Wikidata"
    if pd.notna(r.an) and ("Assemblée nationale", f"PA{r.an}") in par_ident:
        pid, how = par_ident[("Assemblée nationale", f"PA{r.an}")], "Assemblée nationale"
    elif pd.notna(r.senat) and ("Sénat", str(r.senat)[-6:].upper()) in par_ident:
        pid, how = par_ident[("Sénat", str(r.senat)[-6:].upper())], "Sénat"
    elif naissance and len(par_naissance.get((cle(nom, prenom), naissance), [])) == 1:
        pid, how = par_naissance[(cle(nom, prenom), naissance)][0], "nom + prénom + naissance"
    elif len(ministres_sans_date.get(cle(nom, prenom), [])) == 1:
        pid, how = ministres_sans_date.pop(cle(nom, prenom))[0], "nom + prénom (ministre sans date)"
        if naissance:   # (Wikidata apporte la date de naissance qui manquait)
            dates_trouvees.append((pid, naissance))
    else:
        pid, how = str(prochain_id), "nouvelle"
        prochain_id += 1
        nouvelles.append({"id": pid, "nom_usage": (nom or prenom)[:60].upper(), "prenoms": prenom[:70] if nom else None,
                          "date_naissance": naissance,
                          "identification_id": METHODES["formation : Wikidata"]})
        crees_wikidata.setdefault(cle(nom, prenom), []).append(pid)    # (pour les listes du JO, plus bas)
    par_ident[("Wikidata", q)] = pid
    nouveaux_ident.append((pid, "Wikidata", q))
    return pid, how


# ------------------------------------------------------------------------------------------------------------------
# 2. Les écoles
# ------------------------------------------------------------------------------------------------------------------
formations = []
for ecole_id, nom, _, _, _, fichier in ECOLES:
    if fichier is None:
        continue                                                          # (les IRA viennent du JO, plus bas)
    e = pd.read_csv(WIKIDATA / fichier, dtype=str)
    if "promoLabel" not in e:
        e["promo"], e["promoLabel"] = None, None
    for r in e.itertuples():
        pid, how = qui(r)
        promo = r.promoLabel if pd.notna(r.promoLabel) and not re.fullmatch(r"Q\d+", str(r.promoLabel)) else None
        entree, sortie = annee_sure(r.entree), annee_sure(r.sortie)
        if entree and sortie and sortie < entree:  # (erreur de Wikidata : Motchane entre en 1956, sort en 1954)
            sortie = None
        formations.append({"personne_id": pid, "ecole_id": ecole_id, "annee_entree": entree, "annee_sortie": sortie,
                           "promotion": promo, "promo_q": re.search(r"Q\d+", str(r.promo))[0] if promo else None,
                           "_how": how})
    etape(f"{nom} : {e.p.nunique()} personnes")
# les élèves des IRA (Journal officiel, sans date de naissance) : rattachés à une personne déjà connue — élue au Parlement,
# présidente, nommée, ou dans Wikidata — quand une seule porte ce nom (Ugo Bernalicis, IRA de Lille 2013 → député),
# sinon une personne à part
connues = requete("""SELECT i.personne_id id FROM identifiant i JOIN referentiel r ON r.id = i.referentiel_id
                       WHERE r.libelle = 'Wikidata'
                     UNION SELECT personne_id FROM mandat WHERE fonction_id IN (14, 15, 16, 17)
                     UNION SELECT personne_id FROM nomination""").id
par_nom_connu = personnes[personnes.id.isin(connues)].groupby("cle").id.agg(list).to_dict()
# (les membres des grands corps de Wikidata sont reconnus avant de lire le JO, pour que le JO les retrouve par leur nom)
g = pd.read_csv(WIKIDATA / "grands_corps_wikidata.csv", dtype=str)
for r in g.itertuples():
    qui(r)
for c, pids in crees_wikidata.items():      # (énarques, polytechniciens, membres des grands corps créés pendant ce passage)
    par_nom_connu[c] = list(dict.fromkeys(par_nom_connu.get(c, []) + pids))


avec_wikidata = set(ident[ident.source == "Wikidata"].personne_id) | {p for pids in crees_wikidata.values() for p in pids}
jo_crees = {}       # (grands corps : une carrière = plusieurs décrets, une seule personne par nom)


def qui_jo(nom, prenom, sexe=None, nom_usage=None, un_par_nom=False):
    """Une personne du Journal officiel (pas de date de naissance, pas d'identifiant)."""
    global prochain_id
    for n in filter(None, [nom_usage, nom]):
        candidats = par_nom_connu.get(cle(n, prenom), [])
        if len(candidats) > 1:      # (homonymes : la seule qui a une fiche Wikidata, s'il n'y en a qu'une — Jacques Barrot)
            candidats = [p for p in candidats if p in avec_wikidata]
        if len(candidats) == 1:
            return candidats[0], "nom + prénom (personnalité connue)"
    if un_par_nom and cle(nom, prenom) in jo_crees:
        return jo_crees[cle(nom, prenom)], "nouvelle"
    pid = str(prochain_id)
    prochain_id += 1
    if un_par_nom:
        jo_crees[cle(nom, prenom)] = pid
    nouvelles.append({"id": pid, "nom_usage": (nom_usage or nom).upper()[:60],
                      "nom_naissance": nom.upper()[:24] if nom_usage else None, "prenoms": prenom[:70], "sexe": sexe,
                      "date_naissance": None,
                      "identification_id": METHODES["formation : Journal officiel"]})
    return pid, "nouvelle"


ira = pd.read_parquet(JORF / "jorf_ira.parquet")
for r in ira.itertuples():
    pid, how = qui_jo(r.nom, r.prenom, r.sexe, r.nom_usage)
    formations.append({"personne_id": pid, "ecole_id": IRA[r.institut], "annee_entree": r.entree, "annee_sortie": r.sortie,
                       "promotion": f"promotion {r.entree}-{r.sortie}" if r.entree else None, "promo_q": None,
                       "source_id": SOURCE_JO, "_how": how})
etape(f"instituts régionaux d'administration (Journal officiel) : {len(ira)} élèves sortis de {ira.sortie.min()} à {ira.sortie.max()}")
# (Wikidata répète une ligne par date de naissance ou identifiant : une formation par personne, école, entrée et sortie)
formations = pd.DataFrame(formations)
formations["source_id"] = formations.source_id.fillna(SOURCE_WIKIDATA)
formations = formations.sort_values("promotion").drop_duplicates(["personne_id", "ecole_id", "annee_entree", "annee_sortie"])
# les promotions : une ligne chacune dans la table promotion, et l'élève n'en garde que le numéro
promotions = (formations.dropna(subset=["promotion"]).drop_duplicates(["ecole_id", "promotion"])
              [["ecole_id", "promotion", "promo_q"]].sort_values(["ecole_id", "promotion"]).reset_index(drop=True))
promotions.insert(0, "id", promotions.index + 1)
formations = formations.merge(promotions[["id", "ecole_id", "promotion"]].rename(columns={"id": "promotion_id"}),
                              on=["ecole_id", "promotion"], how="left").drop(columns=["promotion", "promo_q"])

# ------------------------------------------------------------------------------------------------------------------
# 3. Les grands corps (des nominations)
# ------------------------------------------------------------------------------------------------------------------
# le Journal officiel d'abord (depuis 1990, au jour près) ; Wikidata en secours, pour ce que le JO n'a pas
corps = []
gj = pd.read_parquet(JORF / "jorf_grands_corps.parquet")
for r in gj.itertuples():
    pid, how = qui_jo(r.nom, r.prenom, r.sexe, un_par_nom=True)
    fonction, _ = CORPS[CORPS_JO[r.corps]]
    corps.append({"personne_id": pid, "fonction_id": fonction, "gouvernement_id": None, "zone_niveau_id": 8,
                  "zone_code": None, "intitule": (r.poste[0].upper() + r.poste[1:])[:255], "date_debut": r.date,
                  "date_fin": None, "precision_id": PRECISION["jour"], "commentaire": None, "source_id": SOURCE_JO,
                  "_how": how})
dans_jo = {(c["personne_id"], c["fonction_id"]): c["date_debut"] for c in corps}
g = pd.read_csv(WIKIDATA / "grands_corps_wikidata.csv", dtype=str)
g["corps_q"] = g.corps.str.extract(r"(Q\d+)")[0]
g["poste_q"] = g.poste.str.extract(r"(Q\d+)")[0]
for r in g.itertuples():
    pid, how = qui(r)
    fonction, libelle = CORPS[r.corps_q]
    debut, fin = date_sure(r.debut), date_sure(r.fin)
    commentaire = None
    if pd.notna(r.fin) and (not fin or (debut and fin < debut)):
        commentaire, fin = f"fin illisible dans Wikidata : {jour(r.fin)}", None
    jo_debut = dans_jo.get((pid, fonction))
    if jo_debut and debut and abs(int(jo_debut[:4]) - int(debut[:4])) <= 1:
        continue                                                          # (déjà au Journal officiel)
    # (une date au 1er janvier, dans Wikidata, est presque toujours une année seule)
    precision = "année" if (debut or "")[5:] in ("", "01-01") and (fin or "")[5:] in ("", "01-01") else "jour"
    corps.append({"personne_id": pid, "fonction_id": fonction, "gouvernement_id": None, "zone_niveau_id": 8,
                  "zone_code": None, "intitule": libelle if r.poste_q == r.corps_q else str(r.posteLabel)[:255],
                  "date_debut": debut, "date_fin": fin, "precision_id": PRECISION[precision], "commentaire": commentaire,
                  "source_id": SOURCE_WIKIDATA, "_how": how})
corps = pd.DataFrame(corps).drop_duplicates(["personne_id", "fonction_id", "intitule", "date_debut"])
# les postes des grands corps vont dans la table poste, à la suite de ceux des gouvernements et des préfets
# (comme dans integrer_nominations.py : un poste par libellé, aux majuscules et accents près)
corps["k"] = corps.intitule.map(norm)
postes = corps.drop_duplicates(["fonction_id", "k"])[["fonction_id", "k", "intitule"]].sort_values(["fonction_id", "k"])
premier_poste = int(requete("SELECT coalesce(max(id), 0) n FROM poste").n[0]) + 1
postes.insert(0, "id", range(premier_poste, premier_poste + len(postes)))
corps = corps.merge(postes[["id", "fonction_id", "k"]].rename(columns={"id": "poste_id"}), on=["fonction_id", "k"]).drop(columns="k")
postes = postes.drop(columns="k")
etape(f"grands corps : {corps.personne_id.nunique()} personnes, {len(corps)} postes")

# ------------------------------------------------------------------------------------------------------------------
# 4. Écriture dans MariaDB
# ------------------------------------------------------------------------------------------------------------------
etape("écriture dans MariaDB")
mysql("INSERT INTO fonction (id, label, zone_niveau_id) VALUES "
      + ", ".join(f"({f}, '{l.replace(chr(39), chr(39) * 2)}', 8)" for f, l in CORPS.values()) + ";")
TABLE = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
mysql(f"""CREATE TABLE ecole (
            id INT NOT NULL PRIMARY KEY, libelle VARCHAR(80) NOT NULL, wikidata VARCHAR(12), annee_creation SMALLINT,
            annee_fermeture SMALLINT) {TABLE};
          CREATE TABLE promotion (
            id INT NOT NULL PRIMARY KEY, ecole_id INT NOT NULL, libelle VARCHAR(80) NOT NULL, wikidata VARCHAR(12),
            UNIQUE KEY ix_promotion_0 (ecole_id, libelle)) {TABLE};
          CREATE TABLE formation (
            id BIGINT NOT NULL PRIMARY KEY, personne_id BIGINT NOT NULL, ecole_id INT NOT NULL, promotion_id INT,
            annee_entree SMALLINT, annee_sortie SMALLINT, source_id INT NOT NULL,
            KEY ix_formation_0 (ecole_id, annee_sortie)) {TABLE};""")
charger("ecole", pd.DataFrame([e[:5] for e in ECOLES], columns=["id", "libelle", "wikidata", "annee_creation", "annee_fermeture"]))
charger("promotion", promotions.rename(columns={"promotion": "libelle", "promo_q": "wikidata"}))
charger("poste", postes.rename(columns={"intitule": "libelle"}))
# (une personne créée pour un membre des grands corps de Wikidata dont la ligne a été écartée — déjà au JO — n'a rien :
#  on ne la garde pas)
utilisees = set(formations.personne_id) | set(corps.personne_id)
crees = {p["id"] for p in nouvelles}
nouvelles = [p for p in nouvelles if p["id"] in utilisees]
charger_personnes(pd.DataFrame(nouvelles))
nouveaux_ident = pd.DataFrame(nouveaux_ident, columns=["personne_id", "source", "valeur"]).drop_duplicates()
nouveaux_ident = nouveaux_ident[~nouveaux_ident.personne_id.isin(crees - utilisees)]
nouveaux_ident = nouveaux_ident[~nouveaux_ident.set_index(["personne_id", "source", "valeur"]).index.isin(
    ident.set_index(["personne_id", "source", "valeur"]).index)]
charger_identifiants(nouveaux_ident)
if dates_trouvees:
    mysql("".join(f"UPDATE personne SET date_naissance = '{d}' WHERE id = {p} AND date_naissance IS NULL;\n"
                  for p, d in dates_trouvees))
liens_f = formations.pop("_how")
formations.insert(0, "id", range(1, len(formations) + 1))
charger("formation", formations)
liens_c, fonctions_c = corps.pop("_how"), corps.pop("fonction_id")
corps = corps.drop(columns="intitule")
premier = int(requete("SELECT coalesce(max(id), 0) n FROM nomination").n[0]) + 1
corps.insert(0, "id", range(premier, premier + len(corps)))
charger("nomination", corps)
for t, c, ref in [("promotion", "ecole_id", "ecole"), ("formation", "personne_id", "personne"),
                  ("formation", "ecole_id", "ecole"), ("formation", "promotion_id", "promotion"),
                  ("formation", "source_id", "source")]:
    cle_etrangere(t, c, ref)

# ------------------------------------------------------------------------------------------------------------------
# 5. Bilan
# ------------------------------------------------------------------------------------------------------------------
etape(f"{len(nouvelles)} personnes ajoutées, {len(nouveaux_ident)} identifiants Wikidata, "
      f"{len(formations)} formations, {len(corps)} postes dans les grands corps")
formations["how"] = liens_f.values
corps["how"], corps["fonction_id"] = liens_c.values, fonctions_c.values
print(formations.drop_duplicates(["personne_id", "ecole_id"]).groupby(["ecole_id", "how"]).size().unstack(fill_value=0).to_string())
print(corps.drop_duplicates(["personne_id", "fonction_id"]).groupby(["fonction_id", "how"]).size().unstack(fill_value=0).to_string())
