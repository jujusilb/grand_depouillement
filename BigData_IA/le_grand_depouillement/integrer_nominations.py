"""
integrer_nominations.py — Ajoute à MariaDB les gouvernements et les nominations (ministres, secrétaires d'État, préfets).

    py integrer_nominations.py              (refuse si la table nomination existe déjà)
    py integrer_nominations.py --refaire    (sauvegarde d'abord personne, identifiant, gouvernement, nomination dans PROJET/DECHET)

Un mandat vient d'une élection ; une nomination vient d'un décret. D'où deux tables à part (validé le 1er novembre 2026) :
    gouvernement    (id, libelle, regime_id, premier_ministre_id, chef_etat_id, date_debut, date_fin, wikidata, source_id)
    nomination      (id, personne_id, poste_id, gouvernement_id, zone_niveau_id, zone_code, date_debut, date_fin,
                     precision_id, commentaire, source_id)
et leurs tables de référence (une valeur qui se répète a sa table, jamais une colonne de texte) :
    poste           (id, fonction_id, libelle)       le poste tel que la source l'écrit : « SE (Tourisme) », « préfet : Jura »
    regime          (id, libelle)                    Gouvernement provisoire, IVe République, Ve République…
    precision_date  (id, libelle)                    jour ; année (les préfets des Archives nationales : 1928 → 1928-01-01)
    source, licence (tables communes à toute la base, tenues par outils_mariadb.sources)
(zone_code reste un code tant que la table zone du schéma v2 n'existe pas : les départements disparus — Liamone,
Mont-Blanc — n'ont pas d'entrée dans geo_departement.)

Sources (PROJET/BRUT) :
    liste-alphabetique-ministres-de-la-liberation-a-la-veme-republique.xls   ministres et SE de 1944 au 04/06/2014
    wikidata/ministres_wikidata.csv, wikidata/gouvernements_wikidata.csv      ministres et gouvernements depuis Valls II
                                                                              (les secrétaires d'État y manquent souvent)
    od-prefets-et-prefetes-francais-depuis-1800.csv                           préfets (Archives nationales), postes par année
    wikidata/prefets_wikidata.csv                                             dates de naissance des préfets

Qui est qui ? Dans l'ordre : même identifiant Wikidata, Assemblée ou Sénat ; même nom + premier prénom + date de naissance
(une seule personne) ; pour un ministre sans date de naissance, même nom + premier prénom qu'un seul parlementaire ou
député européen de la base. Sinon, une nouvelle personne (identification_id : « nomination : … », table methode_identification).
"""
import re
import sys
import time
from pathlib import Path

import pandas as pd

from outils_mariadb import (METHODES, METHODES_FORMATION, METHODES_NOMINATION, charger, charger_identifiants,
                            charger_personnes, cle,
                            cle_etrangere, jour, lire_identifiants, mysql, norm, particule_devant, requete, sauvegarder,
                            sources)

ICI = Path(__file__).resolve().parent
BRUT = ICI.parent.parent / "BRUT"
DECHET = ICI.parent.parent / "DECHET"
JORF = ICI.parent / "donnees_contexte" / "jorf"          # (tableaux tirés du Journal officiel par lire_jorf.py)
VALLS_2 = "2014-08-25"          # premier gouvernement pris dans Wikidata (le fichier xls s'arrête en juin 2014)
debut_chrono = time.time()

FONCTIONS = [  # id, libellé, niveau du territoire (zone_niveau)
    (24, "Premier ministre", 8), (25, "ministre d'État", 8), (26, "ministre délégué", 8), (27, "secrétaire d'État", 8),
    (28, "sous-secrétaire d'État", 8), (29, "préfet", 6), (30, "président du Conseil", 8), (31, "vice-président du Conseil", 8),
]
MINISTRE = 18
PRECISIONS = {"jour": 1, "année": 2}


def etape(texte):
    print(f"[{time.time() - debut_chrono:6.0f} s] {texte}", flush=True)


def date_fr(texte):
    """« 21/05/1981 » → « 1981-05-21 » (None si ce n'est pas une date)."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(texte))
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


# ------------------------------------------------------------------------------------------------------------------
# 0. Refaire ?
# ------------------------------------------------------------------------------------------------------------------
# (integrer_formations.py s'appuie sur ces tables : un --refaire ici efface aussi ce qu'il a ajouté — le relancer ensuite)
NOS_TABLES = ["formation", "promotion", "ecole", "nomination", "gouvernement", "poste", "regime", "precision_date"]
tables = requete("SHOW TABLES").iloc[:, 0].tolist()
existe = "nomination" in tables
if existe and "--refaire" not in sys.argv:
    sys.exit("La table nomination existe déjà : relancer avec --refaire pour tout reprendre.")
if existe:
    a_sauver = ["personne", "identifiant", "fonction"] + [t for t in NOS_TABLES if t in tables]
    etape(f"sauvegarde : {sauvegarder(DECHET, 'nominations_avant_refaire', a_sauver).name}")
    CREES = "(" + ", ".join(map(str, METHODES_NOMINATION + METHODES_FORMATION)) + ")"   # (personnes créées par nos scripts)
    mysql("SET foreign_key_checks = 0; " + "".join(f"DROP TABLE IF EXISTS {t}; " for t in NOS_TABLES) + f"""
             DELETE i FROM identifiant i JOIN personne p ON p.id = i.personne_id WHERE p.identification_id IN {CREES};
             DELETE FROM personne WHERE identification_id IN {CREES};
             DELETE FROM fonction WHERE id BETWEEN 24 AND 35;
             DELETE ms FROM mandat_source ms JOIN mandat m ON m.id = ms.mandat_id WHERE m.fonction_id = 17;
             DELETE FROM mandat WHERE fonction_id = 17;
             SET foreign_key_checks = 1;""")
    etape("tables des nominations et des formations effacées : relancer integrer_formations.py après ce script")

# ------------------------------------------------------------------------------------------------------------------
# 1. Les personnes déjà connues
# ------------------------------------------------------------------------------------------------------------------
etape("lecture des personnes de la base")
personnes = requete("SELECT id, nom_usage, prenoms, date_naissance FROM personne")
personnes["cle"] = [cle(n, p) for n, p in zip(personnes.nom_usage, personnes.prenoms)]
par_naissance = personnes.dropna(subset=["date_naissance"]).groupby(["cle", "date_naissance"]).id.agg(list).to_dict()
ident = lire_identifiants()
par_ident = {(s, v): p for p, s, v in ident.itertuples(index=False)}
parlementaires = requete("SELECT DISTINCT personne_id FROM mandat WHERE fonction_id IN (14, 15, 16)").personne_id
nationaux = personnes[personnes.id.isin(parlementaires)].groupby("cle").id.agg(list).to_dict()
notables = personnes[personnes.id.isin(ident[ident.source == "Wikidata"].personne_id)].groupby("cle").id.agg(list).to_dict()
prochain_id = int(personnes.id.astype("int64").max()) + 1
etape(f"   {len(personnes):,} personnes".replace(",", " "))

nouvelles, nouveaux_ident, sans_naissance = [], [], {}
SANS_DATE = ("nom seul", "Journal officiel")    # (sources sans date de naissance : on n'y crée chaque nom qu'une fois)


def qui(nom, prenoms, q=None, naissance=None, an=None, senat=None, sexe=None, defaut="nom seul"):
    """Rend l'id de la personne (en la créant au besoin) et la façon dont on l'a reconnue."""
    global prochain_id
    if q and ("Wikidata", q) in par_ident:
        return par_ident[("Wikidata", q)], "Wikidata"
    if an and ("Assemblée nationale", f"PA{an}") in par_ident:
        pid, how = par_ident[("Assemblée nationale", f"PA{an}")], "Assemblée nationale"
    elif senat and ("Sénat", str(senat)[-6:].upper()) in par_ident:
        pid, how = par_ident[("Sénat", str(senat)[-6:].upper())], "Sénat"
    elif naissance and len(par_naissance.get((cle(nom, prenoms), naissance), [])) == 1:
        pid, how = par_naissance[(cle(nom, prenoms), naissance)][0], "nom + prénom + naissance"
    elif not naissance and len(nationaux.get(cle(nom, prenoms), [])) == 1:
        pid, how = nationaux[cle(nom, prenoms)][0], "nom + prénom + mandat national"
    elif not naissance and defaut in SANS_DATE and len(notables.get(cle(nom, prenoms), [])) == 1:
        # (un ministre sans date : la seule personnalité Wikidata de la base qui porte ce nom — Jacques Barrot)
        pid, how = notables[cle(nom, prenoms)][0], "nom + prénom + personnalité Wikidata"
    elif (defaut in SANS_DATE and cle(nom, prenoms) in sans_naissance
          and (not naissance or not sans_naissance[cle(nom, prenoms)][1])):
        # (ministre déjà créé plus haut, sans date de naissance : un ministre a une ligne par gouvernement ;
        #  les préfets, une ligne chacun, ne passent pas par là — deux préfets homonymes à un siècle d'écart restent deux)
        pid, how = sans_naissance[cle(nom, prenoms)][0], "nouvelle"
    else:
        pid, how = str(prochain_id), "nouvelle"
        prochain_id += 1
        if defaut in SANS_DATE and (not naissance or cle(nom, prenoms) not in sans_naissance):
            sans_naissance[cle(nom, prenoms)] = (pid, naissance)
        nouvelles.append({"id": pid, "nom_usage": particule_devant(nom).upper(), "prenoms": str(prenoms).strip(),
                          "sexe": sexe, "date_naissance": naissance,
                          "identification_id": METHODES[f"nomination : {'Wikidata' if q else defaut}"]})
        if naissance:
            par_naissance[(cle(nom, prenoms), naissance)] = [pid]
    if q:
        par_ident[("Wikidata", q)] = pid
        nouveaux_ident.append((pid, "Wikidata", q))
    return pid, how


# les ministres de Wikidata, pour retrouver la date de naissance de ceux du fichier xls
wm = pd.read_csv(BRUT / "wikidata" / "ministres_wikidata.csv", dtype=str)
wm["q"] = wm.p.str.extract(r"(Q\d+)")[0]
wm["naiss"] = wm.naissance.map(jour)
# (nom ou prénom parfois absents dans Wikidata : on les prend dans le libellé « Michel Sapin »)
wm["prenom"] = wm.prenom.fillna(wm.pLabel.str.split(" ", n=1).str[0])
wm["nom"] = wm.nom.fillna(wm.pLabel.str.split(" ", n=1).str[1])
wm["cle"] = [cle(n, p) for n, p in zip(wm.nom, wm.prenom)]
# (on cherche aussi par le libellé usuel : le nom de famille officiel diffère parfois — « Galouzeau de Villepin » —
#  alors que la liste des ministres écrit « VILLEPIN (DE) », comme « Dominique de Villepin »)
par_libelle = wm.assign(cle=[cle(l.partition(" ")[2], l.partition(" ")[0]) for l in wm.pLabel.astype(str)])
wiki_par_cle = pd.concat([wm, par_libelle]).drop_duplicates(["q", "cle"]).groupby("cle").agg(list)


def qui_ministre(nom, prenom):
    """Un ministre du fichier xls (sans date de naissance) : d'abord Wikidata par le nom, s'il n'y en a qu'un."""
    w = wiki_par_cle.loc[cle(nom, prenom)] if cle(nom, prenom) in wiki_par_cle.index else None
    if w is not None and len(w.q) == 1:
        return qui(nom, prenom, w.q[0], w.naiss[0], w.an[0] if pd.notna(w.an[0]) else None,
                   w.senat[0] if pd.notna(w.senat[0]) else None)
    return qui(nom, prenom)


# ------------------------------------------------------------------------------------------------------------------
# 2. Les ministres de 1944 à 2014 (fichier xls) et leurs gouvernements
# ------------------------------------------------------------------------------------------------------------------
etape("ministres 1944-2014")
xl = pd.read_excel(BRUT / "liste-alphabetique-ministres-de-la-liberation-a-la-veme-republique.xls", header=1)
xl.columns = ["initiale", "nom", "prenom", "regime", "chef_etat", "chef_gouv", "periode", "fonction", "debut", "fin", "commentaire"]
xl = xl.dropna(subset=["nom"]).copy()
for c in ["nom", "prenom", "regime", "chef_etat", "chef_gouv", "periode", "fonction"]:
    xl[c] = xl[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
xl["prenom"] = xl.prenom.str[:43]


def type_fonction(texte):
    t = texte.lower()
    if t.startswith("premier ministre"):
        return 24
    if t.startswith(("président du conseil", "président du gouvernement provisoire")) and "du plan" not in t:
        return 30
    if t.startswith("vice-président du conseil"):
        return 31
    if t.startswith("ministre d'etat") or t.startswith("ministre d'état"):
        return 25
    if t.startswith(("ministre délégué", "md ")) or t == "md":
        return 26
    if t.startswith("sous-se") or t.startswith("sous-secrétaire"):
        return 28
    if t.startswith(("se ", "se(")) or t == "se" or t.startswith("secrétaire d'"):
        return 27
    return MINISTRE


def nom_chef(texte):
    """« Pierre MAUROY (1er Gouvernement) » ou « François MITTERRAND 21/05/1981 - … » → (prénom, NOM)."""
    texte = re.split(r"\s*\(|\s+\d{2}/", str(texte).split("\n")[0])[0].strip()
    mots = texte.split()
    i = next((k for k, m in enumerate(mots) if m.isupper() and len(m) > 1 or m.lower() in ("de", "d'")), len(mots) - 1)
    return " ".join(mots[:i]), " ".join(mots[i:])


gouv_xl = xl.drop_duplicates(["chef_gouv", "periode"])[["regime", "chef_etat", "chef_gouv", "periode"]].copy()
gouv_xl["date_debut"] = gouv_xl.periode.map(date_fr)
gouv_xl["date_fin"] = gouv_xl.periode.map(lambda p: date_fr(p.split("-", 1)[1]) if "-" in p else None)
gouv_xl = gouv_xl.sort_values("date_debut").reset_index(drop=True)
gouv_xl["id"] = gouv_xl.index + 1
id_gouv = {(g.chef_gouv, g.periode): g.id for g in gouv_xl.itertuples()}

nominations = []
for r in xl.itertuples():
    pid, how = qui_ministre(r.nom, r.prenom)
    commentaire = None if pd.isna(r.commentaire) else str(r.commentaire).strip()
    fin = jour(r.fin)
    if fin and fin < jour(r.debut):  # (erreur de la source : fin avant le début → la fin du gouvernement)
        commentaire = f"fin {fin} dans la source, remplacée par celle du gouvernement"
        fin = date_fr(r.periode.split("-", 1)[1])
    nominations.append({"personne_id": pid, "fonction_id": type_fonction(r.fonction), "gouvernement_id": id_gouv[(r.chef_gouv, r.periode)],
                        "zone_niveau_id": 8, "zone_code": None, "intitule": r.fonction[:255], "date_debut": jour(r.debut),
                        "date_fin": fin, "precision_date": "jour", "commentaire": commentaire,
                        "source": "ministres", "_how": how})

gouvernements = []
for g in gouv_xl.itertuples():
    chef = next((n for n in nominations if n["gouvernement_id"] == g.id and n["fonction_id"] in (24, 30)), None)
    if chef:
        pm = chef["personne_id"]
    else:
        prenom, nom = nom_chef(g.chef_gouv)
        pm = qui_ministre(nom, prenom)[0]
    prenom, nom = nom_chef(g.chef_etat)
    gouvernements.append({"id": g.id, "libelle": re.sub(r"\(([^)]*)\)", lambda m: "(" + m[1].lower() + ")", g.chef_gouv),
                          "regime": g.regime, "premier_ministre_id": pm, "chef_etat_id": qui_ministre(nom, prenom)[0],
                          "date_debut": g.date_debut, "date_fin": g.date_fin, "wikidata": None,
                          "source": "ministres"})
etape(f"   {len(gouvernements)} gouvernements, {len(nominations)} nominations")

# ------------------------------------------------------------------------------------------------------------------
# 3. Les gouvernements et ministres depuis Valls II : le Journal officiel, Wikidata en roue de secours
# ------------------------------------------------------------------------------------------------------------------
# Le JO (donnees_contexte/jorf, lu par lire_jorf.py) : un gouvernement commence à chaque décret « portant nomination du
# Premier ministre » ; les décrets « relatif à la composition du Gouvernement » nomment les ministres et mettent fin à
# leurs fonctions. Ce qui manque au JO (la nomination d'Élisabeth Borne en 2022) vient de Wikidata.
etape("gouvernements et ministres depuis 2014 (Journal officiel, Wikidata en secours)")
jo = pd.read_parquet(JORF / "jorf_gouvernement.parquet")
jo = jo[jo.date >= VALLS_2].copy()
jo["cle"] = [cle(n, p) for n, p in zip(jo.nom, jo.prenom)]
gw = pd.read_csv(BRUT / "wikidata" / "gouvernements_wikidata.csv", dtype=str)
gw = gw[(gw.debut.fillna("") >= VALLS_2) & ~gw.gLabel.str.startswith("remaniement")].copy()
gw["q"] = gw.g.str.extract(r"(Q\d+)")[0]
gw = gw.drop_duplicates("q").sort_values("debut")
# (Valls I, du 31 mars au 25 août 2014, vient du fichier xls, qui n'a pas sa date de fin)
for g in gouvernements:
    if g["libelle"].upper().startswith("MANUEL VALLS") and not g["date_fin"]:
        g["date_fin"] = VALLS_2
for n in nominations:
    if n["date_fin"] is None and gouvernements[n["gouvernement_id"] - 1]["libelle"].upper().startswith("MANUEL VALLS"):
        n["date_fin"] = VALLS_2
hollande = qui_ministre("HOLLANDE", "François")[0]
macron = qui("MACRON", "Emmanuel", "Q3052772", "1977-12-21")[0]
FONCTION_JO = {"Premier ministre": 24, "ministre d'État": 25, "ministre délégué": 26, "secrétaire d'État": 27,
               "ministre": MINISTRE}


def proche(d1, d2, jours=3):
    return abs((pd.Timestamp(d1) - pd.Timestamp(d2)).days) <= jours


# les gouvernements : chaque nomination du Premier ministre au JO, plus ceux de Wikidata que le JO n'a pas
pm_jo = jo[jo.action == "premier ministre"].drop_duplicates("date")
debuts = [{"date": r.date, "nom": r.nom, "prenom": r.prenom, "q": None, "source": "jorf"} for r in pm_jo.itertuples()]
for g in gw.itertuples():
    q_g = re.search(r"Q\d+", g.g)[0]
    deja = next((d for d in debuts if proche(d["date"], g.debut[:10])), None)
    if deja:
        deja["q"] = q_g                                                   # (le même : on garde son identifiant Wikidata)
    else:
        prenom, _, nom = str(g.chefLabel).partition(" ")
        debuts.append({"date": g.debut[:10], "nom": nom, "prenom": prenom, "q": q_g, "source": "wikidata",
                       "chef_q": (re.search(r"Q\d+", str(g.chef)) or [None])[0]})
debuts.sort(key=lambda d: d["date"])
premier_gouv = len(gouvernements) + 1
for i, d in enumerate(debuts):
    meme_pm = [x for x in debuts if cle(x["nom"], x["prenom"]) == cle(d["nom"], d["prenom"])]
    rang = f" {['I', 'II', 'III', 'IV'][meme_pm.index(d)]}" if len(meme_pm) > 1 else ""
    pm, _ = qui(d["nom"], d["prenom"], d.get("chef_q")) if d["source"] == "wikidata" else qui_ministre(d["nom"], d["prenom"])
    gouvernements.append({"id": len(gouvernements) + 1, "libelle": f"Gouvernement {d['prenom']} {particule_devant(d['nom']).title()}{rang}",
                          "regime": "Vème République", "premier_ministre_id": pm,
                          "chef_etat_id": hollande if d["date"] < "2017-05-14" else macron, "date_debut": d["date"],
                          "date_fin": debuts[i + 1]["date"] if i + 1 < len(debuts) else None, "wikidata": d["q"],
                          "source": d["source"]})
    nominations.append({"personne_id": pm, "fonction_id": 24, "gouvernement_id": len(gouvernements), "zone_niveau_id": 8,
                        "zone_code": None, "intitule": "Premier ministre", "date_debut": d["date"],
                        "date_fin": gouvernements[-1]["date_fin"], "precision_date": "jour", "commentaire": None,
                        "source": d["source"], "_how": "Premier ministre"})


def gouvernement_au(jour_):
    return next((g for g in gouvernements[premier_gouv - 1:] if g["date_debut"] <= jour_
                 and (not g["date_fin"] or jour_ < g["date_fin"])), None)


# les ministres du JO : une nomination dure jusqu'à la fin de ses fonctions au JO, sinon jusqu'à la fin du gouvernement
n_avant = len(nominations)
fins = jo[jo.action == "fin"]
for r in jo[jo.action == "nomination"].itertuples():
    g = gouvernement_au(r.date)
    if g is None:
        continue
    pid, how = qui_ministre(r.nom, r.prenom)
    fin = fins[(fins.cle == r.cle) & (fins.date >= r.date) & ((fins.date < g["date_fin"]) if g["date_fin"] else True)].date.min()
    poste = r.poste[0].upper() + r.poste[1:]
    fonction = FONCTION_JO.get(r.fonction) or FONCTION_JO.get(next((f for f in FONCTION_JO if f.lower() in r.poste.lower()), ""),
                                                                 MINISTRE)
    nominations.append({"personne_id": pid, "fonction_id": fonction, "gouvernement_id": g["id"], "zone_niveau_id": 8,
                        "zone_code": None, "intitule": poste[:255], "date_debut": r.date,
                        "date_fin": fin if isinstance(fin, str) else g["date_fin"], "precision_date": "jour",
                        "commentaire": None, "source": "jorf", "_how": how})
n_jo = len(nominations) - n_avant
# Wikidata en secours : un ministre que le JO ne nomme pas à ±10 jours (compositions absentes des archives)
deja = {(n["personne_id"], n["date_debut"]) for n in nominations[n_avant:]}
for r in wm[wm.debut.fillna("") >= VALLS_2].drop_duplicates(["q", "poste", "debut"]).itertuples():
    g = gouvernement_au(r.debut[:10])
    t = str(r.posteLabel).lower()
    if t.startswith("premier ministre") or g is None:
        continue                      # (déjà fait avec les gouvernements ; on ne crée pas de personne pour rien)
    pid, how = qui(r.nom, r.prenom, r.q, r.naiss, r.an if pd.notna(r.an) else None, r.senat if pd.notna(r.senat) else None)
    if any(p == pid and proche(d, r.debut[:10], 10) for p, d in deja):
        continue
    fonction = 26 if "délégué" in t else 27 if "secrétaire d" in t else MINISTRE
    nominations.append({"personne_id": pid, "fonction_id": fonction, "gouvernement_id": g["id"] if g else None,
                        "zone_niveau_id": 8, "zone_code": None, "intitule": str(r.posteLabel)[:255],
                        "date_debut": jour(r.debut), "date_fin": jour(r.fin), "precision_date": "jour",
                        "commentaire": "absent des décrets du Journal officiel téléchargés", "source": "wikidata",
                        "_how": how})
etape(f"   {len(debuts)} gouvernements ({sum(d['source'] == 'jorf' for d in debuts)} au JO), {n_jo} nominations au JO, "
      f"{len(nominations) - n_avant - n_jo} prises dans Wikidata en secours")

# ------------------------------------------------------------------------------------------------------------------
# 3 bis. Les présidents de la République depuis 1947 : des mandats (ils sont élus), pas des nominations
# ------------------------------------------------------------------------------------------------------------------
# La source officielle : les proclamations du Conseil constitutionnel (BRUT/dila/constit), une par présidentielle depuis
# 1965 — qui est élu, et parfois la date de prise de fonctions (« à compter du 14 mai 2022 à 0 heure »). Elles ne disent
# rien de la IVe République, des intérims ni des fins de mandat : Wikidata comble (une ligne par période — Mitterrand
# 1981-1995 —, coupée à la durée légale de fonction_duree : 84 mois, puis 60 depuis 2002), et on vérifie qu'ils concordent.
etape("présidents de la République")


def proclamations():
    """{année de l'élection: (nom proclamé, date de la décision, date de prise de fonctions si le texte la donne)}."""
    import glob
    import html
    import tarfile
    resultat = {}
    for archive in sorted(glob.glob(str(BRUT / "dila" / "constit" / "*.tar.gz"))):
        with tarfile.open(archive) as t:
            for m in t:
                if not m.name.endswith(".xml"):
                    continue
                x = t.extractfile(m).read().decode("utf-8")
                titre = re.search(r"<TITRE>(.*?)</TITRE>", x, re.S)
                if "<NATURE>PDR</NATURE>" not in x or not titre or \
                        not re.search(r"(?i)proclamation des résultats de l'élection du président", titre[1]):
                    continue        # (les autres décisions PDR citent parfois une proclamation : on ne garde que les vraies)
                texte = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x)))
                date = re.search(r"<DATE_DEC>(\d{4}-\d{2}-\d{2})</DATE_DEC>", x)[1]
                # (« Qu'ainsi Monsieur Valéry Giscard d'Estaing a atteint… », « M. Nicolas SARKOZY a recueilli… »)
                elu = re.search(r"([A-ZÉ][\w'-]+(?: (?:de |d')?[A-ZÉ][\w'-]+){1,3}) a (?:atteint|recueilli) la majorité absolue",
                                texte)[1]
                debut = re.search(re.escape(elu.split()[-1]) + r" Président de la République(?: française)? à compter du (\d+) (\w+) (\d{4})",
                                  texte, re.IGNORECASE)
                resultat[int(date[:4])] = (elu, date, date_texte(debut.groups()) if debut else None)
    return resultat


def date_texte(jma):
    """(« 14 », « mai », « 2022 ») → « 2022-05-14 »."""
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return f"{jma[2]}-{mois.index(jma[1].lower()) + 1:02d}-{int(jma[0]):02d}"


CC = proclamations()
etape(f"   {len(CC)} proclamations du Conseil constitutionnel ({min(CC)}-{max(CC)})")
PRESIDENT = 17
MOTIF = {"élu": 1, "élu par une assemblée": 3, "intérim": 4, "terme": 1, "inconnu": 10}   # (motif_debut / motif_fin)
MODE = {"deux tours": 1, "assemblée": 6, "grands électeurs": 8}                            # (mode_scrutin)
wpr = pd.read_csv(BRUT / "wikidata" / "presidents_wikidata.csv", dtype=str)
wpr = wpr[wpr.debut.fillna("").str.match(r"\d{4}-") & (wpr.debut.fillna("") >= "1947")].drop_duplicates(["p", "debut"])
wpr["q"] = wpr.p.str.extract(r"(Q\d+)")[0]
wpr["naiss"] = wpr.naissance.map(jour)
# (nom ou prénom parfois absents dans Wikidata — René Coty : on les prend dans le libellé)
wpr["prenom"] = wpr.prenom.fillna(wpr.pLabel.str.split(" ", n=1).str[0])
wpr["nom"] = wpr.nom.fillna(wpr.pLabel.str.split(" ", n=1).str[1])
presidentielles = requete("SELECT id, date_t2 FROM election WHERE code LIKE '%\\_pres' AND date_t2 IS NOT NULL")
durees = requete(f"SELECT duree, en_vigueur_le FROM fonction_duree WHERE fonction_id = {PRESIDENT} ORDER BY en_vigueur_le")


def election_juste_avant(jour_debut):
    """L'élection présidentielle dont le 2e tour tombe dans les 45 jours avant ce début (None s'il n'y en a pas)."""
    d = pd.Timestamp(jour_debut)
    ok = presidentielles[pd.to_datetime(presidentielles.date_t2).between(d - pd.Timedelta(days=45), d)]
    return ok.id.iloc[0] if len(ok) else None


def duree_legale(jour_debut):
    return int(durees[durees.en_vigueur_le <= jour_debut].duree.iloc[-1])


mandats_pr = []
for r in wpr.itertuples():
    pid, _ = qui(r.nom, r.prenom, r.q, r.naiss, r.an if pd.notna(r.an) else None, r.senat if pd.notna(r.senat) else None)
    debut, fin = jour(r.debut), jour(r.fin)
    while True:
        election = election_juste_avant(debut)
        if debut < "1959":                     # (IVe République : élu par le Parlement réuni en Congrès)
            mode, motif_debut = MODE["assemblée"], MOTIF["élu par une assemblée"]
        elif debut < "1965":                   # (de Gaulle, élu en décembre 1958 par un collège de grands électeurs)
            mode, motif_debut = MODE["grands électeurs"], MOTIF["élu"]
        elif election is not None:
            mode, motif_debut = MODE["deux tours"], MOTIF["élu"]
        else:                                  # (le président du Sénat assure l'intérim : Alain Poher en 1969 et 1974)
            mode, motif_debut = None, MOTIF["intérim"]
        terme = (pd.Timestamp(debut) + pd.DateOffset(months=duree_legale(debut))).strftime("%Y-%m-%d")
        limite = fin or time.strftime("%Y-%m-%d")                          # (en cours : Macron, réélu en 2022)
        coupe = motif_debut != MOTIF["intérim"] and terme < limite and \
            (pd.Timestamp(limite) - pd.Timestamp(terme)).days > 30         # (réélu : un second mandat commence)
        morceau_fin = terme if coupe else fin
        # (fin de mandat : « terme » quand il s'achève à sa durée légale ou juste après une présidentielle ;
        #  sinon on ne sait pas — démission de De Gaulle, décès de Pompidou, fin de la IVe République)
        a_terme = morceau_fin and (coupe or election_juste_avant(morceau_fin) is not None
                                   or abs((pd.Timestamp(morceau_fin) - pd.Timestamp(terme)).days) <= 30)
        motif_fin = None if not morceau_fin else MOTIF["terme"] if a_terme else MOTIF["inconnu"]
        sources_mandat = ["wikidata"]
        annee = int(presidentielles.set_index("id").date_t2[election][:4]) if election is not None else None
        if annee in CC:                        # (élu au suffrage universel : la proclamation fait foi)
            elu, _, debut_officiel = CC.pop(annee)
            if norm(elu.split()[-1]) not in norm(r.nom):
                raise RuntimeError(f"présidentielle {annee} : le Conseil constitutionnel proclame {elu}, Wikidata dit {r.pLabel}")
            if debut_officiel and debut_officiel != debut:
                etape(f"   {annee} : début {debut} (Wikidata) remplacé par {debut_officiel} (Conseil constitutionnel)")
                debut = debut_officiel
            sources_mandat = ["conseil constitutionnel", "wikidata"]
        mandats_pr.append({"personne_id": pid, "fonction_id": PRESIDENT, "election_id": election, "mode_scrutin_id": mode,
                           "zone_niveau_id": 8, "zone_code": "FR", "date_debut": debut, "motif_debut_id": motif_debut,
                           "date_fin": morceau_fin, "motif_fin_id": motif_fin, "sources": sources_mandat})
        if not coupe:
            break
        debut = terme
if CC:
    raise RuntimeError(f"proclamations sans mandat dans Wikidata : {CC}")
etape(f"   {wpr.q.nunique()} présidents, {len(mandats_pr)} mandats "
      f"({sum('conseil constitutionnel' in m['sources'] for m in mandats_pr)} confirmés par le Conseil constitutionnel)")

# ------------------------------------------------------------------------------------------------------------------
# 4. Les préfets (Archives nationales ; dates de naissance par Wikidata)
# ------------------------------------------------------------------------------------------------------------------
etape("préfets")
pf = pd.read_csv(BRUT / "od-prefets-et-prefetes-francais-depuis-1800.csv", dtype=str)
pf["q"] = pf.Wikidata.str.extract(r"(Q\d+)")[0]
wp = pd.read_csv(BRUT / "wikidata" / "prefets_wikidata.csv", dtype=str)
wp["q"] = wp.p.str.extract(r"(Q\d+)")[0]
naiss_wiki = wp.dropna(subset=["naissance"]).drop_duplicates("q").set_index("q").naissance.map(jour).to_dict()
ids_wiki = wp.drop_duplicates("q").set_index("q")[["an", "senat"]].to_dict("index")
n_avant = len(nominations)
sans_poste = 0
DEBUT_JO = "1990"           # (depuis 1990, les décrets de nomination du Journal officiel, au jour près, font foi)
codes_departements = {}     # (nom du département → code, d'après les Archives nationales : « 90 - Territoire de Belfort »)
prefets_an = {}             # (NOM|PRÉNOM → personnes, pour retrouver dans le JO les préfets des Archives nationales)
postes_an_recents = []      # (personne, code, année) des postes commencés depuis 1990 : comparés au JO plus bas
for r in pf.itertuples():
    codes = {}
    for poste in str(r._6).split("|"):
        m = re.match(r"\s*(\w+) - (.+)", poste)
        if m:
            codes[norm(m[2])] = m[1]
    codes_departements.update(codes)
    postes = [m for poste in (str(r._7).split("|") if pd.notna(r._7) else [])
              if (m := re.match(r"\s*(\d{4})\s*-\s*(\d{4}|[.…]+)\s*:\s*(.+)", poste.replace("\xa0", " ")))]
    if not postes:  # (313 préfets sans poste en département dans le fichier : rien à nommer, on ne les crée pas)
        sans_poste += 1
        continue
    autres = ids_wiki.get(r.q, {})
    pid, how = qui(r._1, r._2, r.q, naiss_wiki.get(r.q), autres.get("an") if pd.notna(autres.get("an")) else None,
                   autres.get("senat") if pd.notna(autres.get("senat")) else None,
                   {"masculin": "M", "féminin": "F"}.get(r.Sexe), defaut="Archives nationales")
    prefets_an.setdefault(cle(r._1, r._2), set()).add(pid)
    for m in postes:
        code = codes.get(norm(m[3]))
        if m[1] >= DEBUT_JO:
            postes_an_recents.append((pid, code, int(m[1])))
            continue
        fin_lisible = m[2].isdigit() and m[2] >= m[1]
        nominations.append({"personne_id": pid, "fonction_id": 29, "gouvernement_id": None, "zone_niveau_id": 6,
                            "zone_code": code.zfill(2) if code and code.isdigit() else code, "intitule": f"préfet : {m[3].strip()}"[:255],
                            "date_debut": f"{m[1]}-01-01", "date_fin": f"{m[2]}-01-01" if fin_lisible else None,
                            "precision_date": "année",
                            "commentaire": f"fin illisible dans la source : {m[2]}" if m[2].isdigit() and not fin_lisible else None,
                            "source": "prefets", "_how": how})
etape(f"   Archives nationales : {pf.q.nunique() - sans_poste} préfets, {len(nominations) - n_avant} postes avant {DEBUT_JO} "
      f"({sans_poste} sans poste, laissés de côté)")

# depuis 1990 : les décrets du JO ; un poste s'achève à la nomination suivante dans le même département
pj = pd.read_parquet(JORF / "jorf_prefets.parquet").sort_values("date")
pj["code"] = pj.departement.map(lambda d: codes_departements.get(norm(d)))
pj["fin"] = pj.groupby("departement").date.shift(-1)
n_avant = len(nominations)
for r in pj.itertuples():
    connus = prefets_an.get(cle(r.nom, r.prenom), set())
    if len(connus) == 1:                       # (le préfet des Archives nationales qui porte ce nom)
        pid, how = next(iter(connus)), "Archives nationales"
    else:
        pid, how = qui(r.nom, r.prenom, sexe=r.sexe, defaut="Journal officiel")
    nominations.append({"personne_id": pid, "fonction_id": 29, "gouvernement_id": None, "zone_niveau_id": 6,
                        "zone_code": r.code.zfill(2) if r.code and r.code.isdigit() else r.code,
                        "intitule": f"préfet : {r.departement}"[:255], "date_debut": r.date,
                        "date_fin": r.fin if isinstance(r.fin, str) else None, "precision_date": "jour",
                        "commentaire": None, "source": "jorf", "_how": how})
jo_postes = {(n["personne_id"], n["zone_code"], int(n["date_debut"][:4])) for n in nominations[n_avant:]}
confirmes = sum(any((p, c, a + k) in jo_postes for k in (-1, 0, 1)) for p, c, a in postes_an_recents)
etape(f"   Journal officiel : {len(nominations) - n_avant} nominations depuis {DEBUT_JO} ; postes des Archives nationales "
      f"depuis {DEBUT_JO} confirmés par le JO : {confirmes} / {len(postes_an_recents)}")

# ------------------------------------------------------------------------------------------------------------------
# 5. Écriture dans MariaDB
# ------------------------------------------------------------------------------------------------------------------
etape("écriture dans MariaDB")
if not existe:
    etape(f"   sauvegarde : {sauvegarder(DECHET, 'personnes_avant_nominations', ['personne', 'identifiant', 'fonction']).name}")
mysql("ALTER TABLE personne MODIFY nom_usage VARCHAR(60), MODIFY prenoms VARCHAR(70);")
mysql("INSERT INTO fonction (id, label, zone_niveau_id) VALUES "
      + ", ".join(f"({i}, '{l.replace(chr(39), chr(39) * 2)}', {z})" for i, l, z in FONCTIONS) + ";")
TABLE = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
SOURCE = sources(["ministres", "wikidata", "prefets", "conseil constitutionnel", "jorf"])     # (table source commune : outils_mariadb)
mysql(f"""CREATE TABLE regime (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(60) NOT NULL) {TABLE};
          CREATE TABLE precision_date (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(10) NOT NULL) {TABLE};
          CREATE TABLE poste (id INT NOT NULL PRIMARY KEY, fonction_id INT NOT NULL, libelle VARCHAR(255) NOT NULL,
            UNIQUE KEY ix_poste_0 (fonction_id, libelle)) {TABLE};
          CREATE TABLE gouvernement (
            id INT NOT NULL PRIMARY KEY, libelle VARCHAR(80), regime_id INT NOT NULL, premier_ministre_id BIGINT,
            chef_etat_id BIGINT, date_debut DATE, date_fin DATE, wikidata VARCHAR(12), source_id INT NOT NULL,
            KEY ix_gouvernement_0 (date_debut)) {TABLE};
          CREATE TABLE nomination (
            id BIGINT NOT NULL PRIMARY KEY, personne_id BIGINT NOT NULL, poste_id INT NOT NULL, gouvernement_id INT,
            zone_niveau_id INT, zone_code VARCHAR(3), date_debut DATE, date_fin DATE, precision_id INT NOT NULL,
            commentaire VARCHAR(80), source_id INT NOT NULL,
            KEY ix_nomination_0 (zone_niveau_id, zone_code), KEY ix_nomination_1 (date_debut)) {TABLE};""")
charger("precision_date", pd.DataFrame([(i, l) for l, i in PRECISIONS.items()], columns=["id", "libelle"]))
# (un préfet des Archives nationales dont tous les postes sont postérieurs à 1990, et que le JO ne retrouve pas par son
#  nom, n'a plus rien : on ne crée pas sa personne)
utilisees = ({n["personne_id"] for n in nominations} | {m["personne_id"] for m in mandats_pr}
             | {g[c] for g in gouvernements for c in ("premier_ministre_id", "chef_etat_id")})
crees = {p["id"] for p in nouvelles}
nouvelles = [p for p in nouvelles if p["id"] in utilisees]
charger_personnes(pd.DataFrame(nouvelles))
nouveaux_ident = pd.DataFrame(nouveaux_ident, columns=["personne_id", "source", "valeur"]).drop_duplicates()
nouveaux_ident = nouveaux_ident[~nouveaux_ident.personne_id.isin(crees - utilisees)]
nouveaux_ident = nouveaux_ident[~nouveaux_ident.set_index(["personne_id", "source", "valeur"]).index.isin(
    ident.set_index(["personne_id", "source", "valeur"]).index)]
charger_identifiants(nouveaux_ident)
gouv = pd.DataFrame(gouvernements)
# (les régimes numérotés dans l'ordre où ils apparaissent : Gouvernement provisoire = 1)
regimes = gouv.sort_values("date_debut").regime.drop_duplicates().reset_index(drop=True)
charger("regime", pd.DataFrame({"id": regimes.index + 1, "libelle": regimes}))
gouv["regime_id"] = gouv.pop("regime").map({l: i + 1 for i, l in regimes.items()})
gouv["source_id"] = gouv.pop("source").map(SOURCE)
charger("gouvernement", gouv)
nom = pd.DataFrame(nominations).drop_duplicates(["personne_id", "fonction_id", "intitule", "date_debut"])
# (un poste = un libellé, aux majuscules, accents et ponctuation près : « SE (Tourisme) » = « SE (tourisme) »)
nom["k"] = nom.intitule.map(norm)
postes = nom.drop_duplicates(["fonction_id", "k"])[["fonction_id", "k", "intitule"]].sort_values(["fonction_id", "k"])
postes = postes.reset_index(drop=True)
postes.insert(0, "id", postes.index + 1)
charger("poste", postes.drop(columns="k").rename(columns={"intitule": "libelle"}))
nom = nom.merge(postes[["id", "fonction_id", "k"]].rename(columns={"id": "poste_id"}), on=["fonction_id", "k"]).drop(columns="k")
liens, fonctions_nom = nom.pop("_how"), nom.pop("fonction_id")
nom = nom.drop(columns="intitule")
nom["precision_id"] = nom.pop("precision_date").map(PRECISIONS)
nom["source_id"] = nom.pop("source").map(SOURCE)
nom.insert(0, "id", range(1, len(nom) + 1))
charger("nomination", nom)
# (les mandats présidentiels vont dans mandat, à la suite des autres ; ses clés étrangères sont déjà posées)
premier_mandat = int(requete("SELECT coalesce(max(id), 0) n FROM mandat").n[0]) + 1
mandats_pr = pd.DataFrame(mandats_pr)
mandats_pr.insert(0, "id", range(premier_mandat, premier_mandat + len(mandats_pr)))
charger("mandat", mandats_pr.drop(columns="sources"))
liens_sources = mandats_pr[["id", "sources"]].explode("sources")
charger("mandat_source", pd.DataFrame({"mandat_id": liens_sources.id, "source_id": liens_sources.sources.map(SOURCE)}))
for t, c, ref in [("poste", "fonction_id", "fonction"),
                  ("gouvernement", "premier_ministre_id", "personne"), ("gouvernement", "chef_etat_id", "personne"),
                  ("gouvernement", "regime_id", "regime"), ("gouvernement", "source_id", "source"),
                  ("nomination", "personne_id", "personne"), ("nomination", "poste_id", "poste"),
                  ("nomination", "gouvernement_id", "gouvernement"), ("nomination", "zone_niveau_id", "zone_niveau"),
                  ("nomination", "precision_id", "precision_date"), ("nomination", "source_id", "source")]:
    cle_etrangere(t, c, ref)

# ------------------------------------------------------------------------------------------------------------------
# 6. Bilan
# ------------------------------------------------------------------------------------------------------------------
nom["how"], nom["fonction_id"] = liens.values, fonctions_nom.values
bilan = nom.drop_duplicates(["personne_id", "fonction_id"]).assign(
    qui=lambda d: d.fonction_id.map(lambda f: "préfets" if f == 29 else "membres du gouvernement")).drop_duplicates(["personne_id", "qui"])
etape(f"{len(nouvelles)} personnes ajoutées, {len(nouveaux_ident)} identifiants Wikidata, "
      f"{len(gouvernements)} gouvernements, {len(nom)} nominations, {len(mandats_pr)} mandats présidentiels")
print(bilan.groupby(["qui", "how"]).size().to_string())
