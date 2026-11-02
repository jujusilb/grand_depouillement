"""
affiches.py — Les 2 234 affiches électorales des Hauts-de-Seine (1968-1990), Archives départementales des Hauts-de-Seine
(open data du Département, jeu « fr-229200506-affiches-electorales », licence CC BY-NC-ND 4.0 : usage non commercial,
citer la source, NE PAS MODIFIER — on montre donc chaque affiche entière, seulement réduite pour l'écran).

    py affiches.py          (~10-20 min : 5 Go d'images à réduire ; on peut l'arrêter et le relancer)

Entrées : ../../data/fr-229200506-affiches-electorales.csv (la fiche de chaque affiche)
          ../../images_telechargees/<identifiant>.jpg      (les images, téléchargées depuis l'open data)
Sorties : affiches.parquet                                   (une ligne par affiche : élection, année, lieu, communes, texte, cote…)
          donnees/appli/affiches/<identifiant>.jpg   (700 pixels au plus long : ~200 Mo pour l'appli)
"""
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from PIL import Image

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
ICI = C.dossier("affiches")
SOURCE = C.COLLECTE / "images_telechargees"
SORTIE = C.DONNEES_APPLI / "affiches"
SORTIE.mkdir(parents=True, exist_ok=True)
TAILLE = 700

TYPES = {"1": "Européennes", "2": "Présidentielle", "3": "Sénatoriales", "4": "Législatives", "5": "Législatives",
         "6": "Cantonales", "7": "Cantonales", "8": "Municipales", "9": "Municipales"}
# des mots en capitales qui ne sont PAS des noms de candidats
PAS_DES_NOMS = set("""REPUBLIQUE FRANCAISE ELECTIONS ELECTION MUNICIPALES CANTONALES LEGISLATIVES PRESIDENTIELLE EUROPEENNES TOUR
LISTE UNION POUR AVEC VOTEZ VOTER CANDIDAT CANDIDATS SUPPLEANT SUPPLEANTE PARTI SOCIALISTE COMMUNISTE FRANCAIS RPR UDF PCF PSU
LCR LUTTE OUVRIERE FRONT NATIONAL GAUCHE DROITE MAJORITE OPPOSITION MAIRE DEPUTE CONSEILLER GENERAL MARS JUIN MAI AVRIL SEPTEMBRE
OCTOBRE NOVEMBRE DECEMBRE JANVIER FEVRIER JUILLET AOUT DIMANCHE ECOLOGIE ECOLOGISTE ECOLOGISTES VERTS FRANCE PARIS CHANGEONS
NON OUI LES DES AUX ENSEMBLE AVENIR NOUVEAU NOUVELLE""".split())


MOTS_COURANTS = set("OPPOSITION LISTE POUR AVEC VOTEZ SOUTENU SOUTENUE CANDIDAT CANDIDATE MAIRE MONSIEUR MADAME ET LE LA LES".split())


def normaliser(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").replace("-", " ").replace("'", " ").split())


def sans_accent(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def candidats(texte):
    """Les noms en CAPITALES du texte de l'affiche (« Dominique FORETTE », « M. DUCOLONE ») : prénom éventuel + NOM."""
    noms = []
    for m in re.finditer(r"(?:\b([A-ZÉÈ][a-zéèëïôç]+(?:-[A-ZÉÈ][a-zéèëïôç]+)?) )?\b((?:[A-ZÉÈÀÇ][A-ZÉÈÀÇ'\-]{2,}(?: (?:DE |DU |LE |LA )?)?)+)", texte):
        nom = m.group(2).strip(" -'")
        mots = [w for w in nom.split() if sans_accent(w) not in PAS_DES_NOMS]
        if not mots or len(nom) < 4:
            continue
        nom = " ".join(mots)
        if "-" in nom and all(len(x) <= 4 for x in re.split(r"[- ]", nom)):      # « UDF-RPR-CNI » : des sigles, pas un nom
            continue
        prenom = m.group(1) if m.group(1) and sans_accent(m.group(1)).upper() not in PAS_DES_NOMS | MOTS_COURANTS else None
        noms.append(f"{prenom} {nom}" if prenom else nom)
    return list(dict.fromkeys(noms))


# les communes des Hauts-de-Seine (pour rattacher une affiche de commune ou de canton à sa / ses communes)
from lecture import donnees as d  # noqa: E402
communes = d.sql("SELECT code, libelle FROM geo_commune WHERE departement = '92'")
communes["cle"] = communes["libelle"].map(normaliser)

t = pd.read_csv(C.COLLECTE / "fr-229200506-affiches-electorales.csv", sep=";").dropna(subset=["FICHIER_IMAGE"])
t["identifiant"] = t["FICHIER_IMAGE"].str.rsplit("/", n=1).str[-1]
t["type"] = t["TYPE ELECTION"].str[0].map(TYPES)
t["partielle"] = t["TYPE ELECTION"].str.contains("partielle")
t["lieu"] = t["CIRCONSCRIPTION ELECTORALE"].fillna("Tous cantons")
lieux = t["lieu"].map(normaliser)
t["communes"] = [",".join(communes.loc[communes["cle"].map(lambda c: re.search(rf"\b{re.escape(c)}\b", l) is not None), "code"]) for l in lieux]
num = t["lieu"].str.extract(r"^(\d+)e circonscription")[0]
t["circo"] = num.map(lambda n: f"92-{int(n):02d}" if n == n else None)
t["candidats"] = t["DESCRIPTION"].fillna("").map(lambda x: " · ".join(candidats(x)))
t = t.rename(columns={"ANNEE": "annee", "DESCRIPTION": "description", "COTE": "cote", "FONDS": "fonds", "FICHIER_IMAGE": "adresse"})
t = t[["identifiant", "type", "partielle", "annee", "lieu", "communes", "circo", "candidats", "description", "cote", "fonds", "adresse"]]
t["source"] = "Archives départementales des Hauts-de-Seine"
t["licence"] = "CC BY-NC-ND 4.0"

faites, absentes = 0, []
for n, ident in enumerate(t["identifiant"], 1):
    dest = SORTIE / f"{ident}.jpg"
    if dest.exists():
        continue
    src = SOURCE / f"{ident}.jpg"
    if not src.exists():
        absentes.append(ident)
        continue
    with Image.open(src) as im:
        im.draft("RGB", (TAILLE * 2, TAILLE * 2))       # (lecture rapide : le JPEG est décodé directement à petite taille)
        im = im.convert("RGB")
        im.thumbnail((TAILLE, TAILLE), Image.LANCZOS)    # réduite, pas recadrée : l'affiche reste entière (licence ND)
        im.save(dest, "JPEG", quality=82, optimize=True)
    faites += 1
    if n % 200 == 0:
        print(f"  {n} / {len(t)}", flush=True)
t["image"] = t["identifiant"].map(lambda i: (SORTIE / f"{i}.jpg").exists())
t.to_parquet(ICI / "affiches.parquet", index=False)
poids = sum(f.stat().st_size for f in SORTIE.glob("*.jpg")) / 1e6
print(f"{len(t)} affiches · {t['image'].sum()} images ({poids:.0f} Mo) · {faites} réduites maintenant · {len(absentes)} sans image")
print(f"rattachées à une commune : {(t['communes'] != '').sum()} · à une circonscription : {t['circo'].notna().sum()} · "
      f"avec des noms de candidats : {(t['candidats'] != '').sum()}")
