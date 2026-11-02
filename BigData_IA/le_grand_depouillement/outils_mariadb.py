"""
outils_mariadb.py — Les outils communs aux scripts qui ajoutent des données à MariaDB (integrer_nominations.py,
integrer_formations.py) : envoyer du SQL, lire une requête, charger un tableau, comparer des noms.
"""
import re
import os
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import pandas as pd

MYSQL = Path(os.environ.get("GD_MYSQL", r"C:\xampp\mysql\bin\mysql.exe"))     # (GD_MYSQL : le MariaDB portable de l'installation)
BASE = "grand_depouillement"

# les tables de référence de personne et identifiant (mêmes numéros dans construire_modele.py et les scripts integrer_*)
REFERENTIELS = {  # libellé → (id, adresse d'une fiche, {} = l'identifiant)
    "Assemblée nationale": (1, "https://www.assemblee-nationale.fr/dyn/deputes/{}"),
    "Sénat": (2, "https://www.senat.fr/senateur/{}.html"),
    "Wikidata": (3, "https://www.wikidata.org/wiki/{}"),
    "Insee décès": (4, None),
}
METHODES = {  # comment une personne a été reconnue → id
    "identifiant": 1, "nom + prénom + naissance": 2, "nom + prénom + commune": 3, "nom + prénom + departement": 4,
    "nom + prénom seulement (personne à part)": 5,
    "nomination : Wikidata": 6, "nomination : nom seul": 7, "nomination : Archives nationales": 8,
    "formation : Wikidata": 9, "nomination : Journal officiel": 10, "formation : Journal officiel": 11,
}
METHODES_NOMINATION = (6, 7, 8, 10)     # (personnes créées par integrer_nominations.py)
METHODES_FORMATION = (9, 11)            # (personnes créées par integrer_formations.py)


# Les sources et leurs licences : des tables de référence communes à toute la base, jamais effacées par un script.
# Chaque source a une clé technique (cle) ; son numéro est attribué une fois pour toutes à sa première apparition.
LICENCES = [  # id, libellé, url
    (1, "Licence ouverte v1.0", "https://www.etalab.gouv.fr/wp-content/uploads/2014/05/Licence_Ouverte.pdf"),
    (2, "Licence ouverte v2.0", "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"),
    (3, "CC0 1.0 (domaine public)", "https://creativecommons.org/publicdomain/zero/1.0/"),
    (4, "CC BY-NC-ND 4.0", "https://creativecommons.org/licenses/by-nc-nd/4.0/deed.fr"),
]
RNE = "https://www.data.gouv.fr/datasets/repertoire-national-des-elus-1"
SOURCES_CONNUES = {  # cle → (libellé, producteur, url, fichier dans PROJET/BRUT, licence)
    "ministres": ("Liste alphabétique des ministres de la Libération à la Vème République", "Premier ministre",
                  "https://www.data.gouv.fr/datasets/liste-alphabetique-des-ministres-de-la-liberation-a-la-veme-republique",
                  "liste-alphabetique-ministres-de-la-liberation-a-la-veme-republique.xls", 1),
    "wikidata": ("Wikidata", "Wikimedia", "https://www.wikidata.org", "wikidata/", 3),
    "prefets": ("Préfets et préfètes français depuis 1800", "Ministère de la Culture (Archives nationales)",
                "https://www.data.gouv.fr/datasets/prefets-et-prefetes-francais-depuis-1800",
                "od-prefets-et-prefetes-francais-depuis-1800.csv", 2),
    "Assemblée nationale (mandats)": ("Députés et mandats (open data de l'Assemblée nationale)", "Assemblée nationale",
                                      "https://data.assemblee-nationale.fr", None, 2),
    "Sénat (en exercice)": ("Sénateurs en exercice (open data du Sénat)", "Sénat", "https://data.senat.fr", None, 2),
    "Sénat (bureau)": ("Bureau du Sénat (open data du Sénat)", "Sénat", "https://data.senat.fr", None, 2),
    "élus municipaux 2014": ("Élus municipaux 2014", "Ministère de l'Intérieur", RNE, None, 2),
    "fiches des candidats": ("Fiches détaillées des candidats", "Ministère de l'Intérieur",
                             "https://www.data.gouv.fr/organizations/ministere-de-l-interieur-et-des-outre-mer", None, 2),
    "listes déposées": ("Listes et candidatures déposées", "Ministère de l'Intérieur",
                        "https://www.data.gouv.fr/organizations/ministere-de-l-interieur-et-des-outre-mer", None, 2),
    "photos Assemblée nationale": ("Photos officielles des députés", "Assemblée nationale",
                                   "https://data.assemblee-nationale.fr", None, 2),
    "photos Sénat": ("Photos officielles des sénateurs", "Sénat", "https://data.senat.fr", None, 2),
    "photos Wikimedia Commons": ("Photos libres des personnalités politiques (via Wikidata)", "Wikimedia Commons",
                                 "https://commons.wikimedia.org", None, None),   # (une licence par photo : photo.licence_id)
    "saisie manuelle": ("Renseigné à la main par l'auteur de la base (liens_saisis.csv…)", "auteur de la base",
                        None, None, None),
    "promotions ENA": ("Noms et années des promotions de l'ENA depuis 1945", "Institut national du service public (ex-ENA)",
                       "https://insp.gouv.fr", "../BigData_IA/donnees_contexte/ena/promotions_ena.csv", None),
    "votes : open data de l'Assemblée": ("Scrutins publics de l'Assemblée nationale (open data)", "Assemblée nationale",
                                         "https://data.assemblee-nationale.fr", None, 2),
    "votes : site de l'Assemblée": ("Analyses des scrutins publics sur le site de l'Assemblée nationale", "Assemblée nationale",
                                    "https://www.assemblee-nationale.fr", None, None),
    "votes : Journal officiel": ("Journal officiel, débats de l'Assemblée nationale (PDF numérisés)", "Assemblée nationale",
                                 "https://archives.assemblee-nationale.fr", None, None),
    "législatures : CDSP (courant) + Wikidata (noms)": ("Composition des législatures : CDSP (députés en cours) et Wikidata (noms)",
                                                        "CDSP (Sciences Po) et Wikidata", "https://cdsp.sciences-po.fr", None, None),
    "législatures : CDSP (élus nommés)": ("Composition des législatures : CDSP (élus nommés)", "CDSP (Sciences Po)",
                                          "https://cdsp.sciences-po.fr", None, None),
    "législatures : Wikidata (proportionnelle)": ("Composition de la législature élue à la proportionnelle (1986) : Wikidata",
                                                  "Wikimedia", "https://www.wikidata.org", None, 3),
    "législatures : Assemblée nationale (open data)": ("Composition des législatures : open data de l'Assemblée nationale",
                                                       "Assemblée nationale", "https://data.assemblee-nationale.fr", None, 2),
    "rattachements législatives": ("Rattachement des candidats aux élections législatives (ministère de l'Intérieur, avis CADA)",
                                   "Ministère de l'Intérieur",
                                   "https://www.data.gouv.fr/datasets/rattachement-des-candidats-aux-elections-legislatives",
                                   "rattachement candidat/", None),
    "jorf": ("Journal officiel de la République française (lois et décrets)", "DILA",
             "https://echanges.dila.gouv.fr/OPENDATA/JORF/", "jorf/", 2),
    "conseil constitutionnel": ("Décisions du Conseil constitutionnel (proclamation des résultats de l'élection du Président)",
                                "Conseil constitutionnel (DILA, données CONSTIT)", "https://echanges.dila.gouv.fr/OPENDATA/CONSTIT/",
                                "dila/constit/", 2),
}


def decrire_source(cle):
    """(libellé, producteur, url, fichier, licence) d'une source, d'après sa clé : « rne_municipaux 2020-01 »,
    « législature IV (CDSP (courant) + Wikidata (noms)) »…"""
    if cle in SOURCES_CONNUES:
        return SOURCES_CONNUES[cle]
    m = re.fullmatch(r"rne_(\w+) (\d{4}-\d{2})", cle)
    if m:
        return (f"Répertoire national des élus : {m[1]} (version {m[2]})", "Ministère de l'Intérieur", RNE, None, 2)
    m = re.fullmatch(r"législature (\w+) \((.*)\)", cle)
    if m:
        return (f"Composition de la législature {m[1]} : {m[2]}", "CDSP (Sciences Po) et Wikidata",
                "https://cdsp.sciences-po.fr", None, None)
    raise KeyError(f"source inconnue : {cle!r} (à décrire dans outils_mariadb.SOURCES_CONNUES)")


def sources(cles):
    """{cle: id} pour ces sources, en ajoutant à la table source celles qui n'y sont pas encore."""
    T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    mysql(f"""CREATE TABLE IF NOT EXISTS licence (id INT NOT NULL PRIMARY KEY, libelle VARCHAR(60) NOT NULL, url VARCHAR(255)) {T};
              CREATE TABLE IF NOT EXISTS source (id INT NOT NULL PRIMARY KEY, cle VARCHAR(120) NOT NULL, libelle VARCHAR(160) NOT NULL,
                producteur VARCHAR(80), url VARCHAR(255), fichier VARCHAR(120), licence_id INT,
                UNIQUE KEY ix_source_cle (cle), CONSTRAINT fk_source_licence_id FOREIGN KEY (licence_id) REFERENCES licence (id)) {T};
              INSERT IGNORE INTO licence VALUES """ + ", ".join(f"({i}, {texte_sql(l)}, {texte_sql(u)})" for i, l, u in LICENCES) + ";")
    deja = requete("SELECT id, cle FROM source")
    connus = dict(zip(deja.cle, deja.id.astype(int)))
    prochain = max(connus.values(), default=0) + 1
    for c in dict.fromkeys(cles):
        if c not in connus:
            libelle, producteur, url, fichier, licence = decrire_source(c)
            mysql(f"INSERT INTO source VALUES ({prochain}, {texte_sql(c)}, {texte_sql(libelle)}, {texte_sql(producteur)}, "
                  f"{texte_sql(url)}, {texte_sql(fichier)}, {licence or 'NULL'});")
            connus[c], prochain = prochain, prochain + 1
    return {c: connus[c] for c in cles}


def texte_sql(v):
    return "NULL" if v is None else "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def charger_personnes(df):
    """Les nouvelles personnes, après avoir ajouté à methode_identification les méthodes apparues depuis (même liste
    que METHODES : la clé étrangère refuserait sinon une personne « nomination : Journal officiel »)."""
    mysql("INSERT IGNORE INTO methode_identification (id, libelle) VALUES "
          + ", ".join(f"({i}, {texte_sql(l)})" for l, i in METHODES.items()) + ";")
    charger("personne", df)


def lire_identifiants():
    """Les identifiants de la base, avec le nom de leur référentiel en clair : (personne_id, source, valeur)."""
    return requete("""SELECT i.personne_id, r.libelle source, i.valeur FROM identifiant i
                      JOIN referentiel r ON r.id = i.referentiel_id""")


def charger_identifiants(df):
    """(personne_id, source, valeur) avec le nom du référentiel → la table identifiant (referentiel_id)."""
    df = df.assign(referentiel_id=df.source.map(lambda s: REFERENTIELS[s][0]))
    charger("identifiant", df[["personne_id", "referentiel_id", "valeur"]])


def mysql(sql):
    # (le SQL passe par l'entrée standard, en UTF-8 : la ligne de commande de Windows abîmerait les accents)
    r = subprocess.run([str(MYSQL), "-u", "root", "--local-infile=1", "--default-character-set=utf8mb4", "-B", BASE],
                       input=sql, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:500])
    return r.stdout


def requete(sql):
    sortie = mysql(sql)
    lignes = [l.split("\t") for l in sortie.rstrip("\n").split("\n")]
    return pd.DataFrame(lignes[1:], columns=lignes[0]).replace("NULL", None)


def charger(table, df):
    """Envoie un tableau dans une table existante (LOAD DATA : rapide, et les accents passent)."""
    def texte(v):
        if pd.isna(v):
            return "\\N"                                   # (le vide, pour LOAD DATA)
        if isinstance(v, float) and v.is_integer():
            return str(int(v))                             # (une colonne d'entiers avec des vides devient float : 12.0 → 12)
        return str(v).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8", newline="\n") as f:
        for ligne in df.itertuples(index=False):
            f.write("\t".join(texte(v) for v in ligne) + "\n")
    mysql(f"""LOAD DATA LOCAL INFILE '{Path(f.name).as_posix()}' INTO TABLE `{table}` CHARACTER SET utf8mb4
              FIELDS TERMINATED BY '\\t' ESCAPED BY '\\\\' LINES TERMINATED BY '\\n' ({', '.join(df.columns)})""")
    Path(f.name).unlink()


def cle_etrangere(table, colonne, reference):
    """Pose une clé étrangère après avoir vérifié qu'aucun lien ne pointe dans le vide."""
    orphelins = int(requete(f"SELECT count(*) n FROM {table} x LEFT JOIN {reference} r ON r.id = x.{colonne} "
                            f"WHERE x.{colonne} IS NOT NULL AND r.id IS NULL").n[0])
    if orphelins:
        raise RuntimeError(f"{table}.{colonne} : {orphelins} liens vers rien")
    # (foreign_key_checks = 0 : MariaDB pose la clé sans recopier la table ; on vient de vérifier les liens)
    mysql(f"SET foreign_key_checks = 0; ALTER TABLE {table} ADD CONSTRAINT fk_{table}_{colonne} "
          f"FOREIGN KEY ({colonne}) REFERENCES {reference} (id);")


def sauvegarder(dossier, nom, tables):
    """mysqldump de quelques tables dans PROJET/DECHET avant de les toucher."""
    import time
    chemin = dossier / f"{nom}_{time.strftime('%Y%m%d_%H%M')}.sql"
    with open(chemin, "w", encoding="utf-8") as f:
        subprocess.run([str(MYSQL.parent / "mysqldump.exe"), "-u", "root", BASE, *tables], stdout=f, check=True)
    return chemin


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z]", "", s)


def particule_devant(nom):
    """« VILLEPIN (DE) » → « DE VILLEPIN », « AUBERT (D') » → « D'AUBERT » : la liste des ministres range la particule
    à la fin, Wikidata et les listes électorales la mettent devant. (Les autres parenthèses — nom de jeune fille — restent.)"""
    m = re.match(r"^(.*?)\s*\((de la|de|du|des|le|la|d'|l')\)\s*$", str(nom).strip(), re.IGNORECASE)
    if not m:
        return str(nom).strip()
    particule = m[2].upper()
    return particule + m[1] if particule.endswith("'") else f"{particule} {m[1]}"


def cle(nom, prenoms):
    """NOM|PREMIERPRÉNOM sans accents ni espaces : « Le Roy Ladurie, Jacques Emmanuel » → LEROYLADURIE|JACQUES ;
    « VILLEPIN (DE) » et « de Villepin » donnent tous deux DEVILLEPIN."""
    premier = re.split(r"[ ,\-]", str(prenoms).strip())[0] if pd.notna(prenoms) else ""
    return norm(particule_devant(nom)) + "|" + norm(premier)


def jour(v):
    """« 1981-05-21T00:00:00Z » ou un Timestamp → « 1981-05-21 » (None si vide)."""
    return None if pd.isna(v) or v == "" else str(v)[:10]
