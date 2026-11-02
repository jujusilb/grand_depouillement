"""
images.py — Toutes les photos et toutes les affiches de l'appli, téléchargées depuis leur source d'origine
(elles ne sont pas republiées sur GitHub : chacune garde sa licence, son auteur et son adresse d'origine dans la base).

    py installation/images.py      (relançable : ce qui est déjà là n'est pas retéléchargé ; ~1 heure la 1re fois)

    data/photos/an/        photos officielles des députés (Assemblée nationale)
    data/photos/senat/     photos officielles des sénateurs (Sénat)
    data/photos/wikimedia/ photos libres des personnalités (Wikimedia Commons, vignettes de 200 px)
    data/photos/candidats/ photos libres des candidats (Wikimedia Commons, vignettes de 200 px ; crédits : credits.parquet)
    data/affiches/         affiches des Hauts-de-Seine 1968-1990 (Archives départementales, 700 px au plus long,
                           réduites mais jamais recadrées : licence CC BY-NC-ND)
"""
import io
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
from pathlib import Path

import duckdb
import pandas as pd
import requests
from PIL import Image

from telecharger import annonce, avertir, signe   # (les signes de vie pour la fenêtre d'installation)

ICI = Path(__file__).resolve().parent
DATA = ICI.parent / "donnees" / "appli"
ENTETE = {"User-Agent": "LeGrandDepouillement/1.0 (installation ; https://github.com/jujusilb/grand_depouillement)"}
_local = threading.local()                     # (une session par fil de téléchargement)
_pause = [0.0]                                 # (« ralentis » : quand un serveur répond 429, tous les fils attendent jusque-là)


def session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(ENTETE)
    return _local.s


class Quota(Exception):
    """Le site refuse : la limite de téléchargements du jour est atteinte (Hauts-de-Seine : 5 000 par jour et par adresse)."""


def lire(url, essais=5):
    for essai in range(essais):
        attente = _pause[0] - time.time()
        if attente > 0:
            time.sleep(attente)
        try:
            r = session().get(url, timeout=60)
            if r.status_code == 429 and "limit" in r.text:            # (un quota du jour : inutile d'insister)
                raise Quota(r.json().get("reset_time", "") if r.headers.get("content-type", "").startswith("application/json") else "")
            if r.status_code == 429 or r.status_code >= 500:          # (trop vite, ou serveur occupé : on ralentit tous)
                attendre = r.headers.get("Retry-After", "")
                delai = float(attendre) if attendre.isdigit() else 2 * (essai + 1)
                _pause[0] = max(_pause[0], time.time() + delai)
                continue
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            time.sleep(2 * (essai + 1))
    return None


def enregistrer(contenu, dest, taille=None, largeur=None):
    """L'image telle quelle, ou réduite : à taille pixels au plus long (affiches), ou à largeur pixels de large (vignettes)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not taille and not largeur:
        dest.write_bytes(contenu)
        return
    im = Image.open(io.BytesIO(contenu)).convert("RGB")
    if taille:
        im.thumbnail((taille, taille), Image.LANCZOS)
    elif im.width > largeur:
        im = im.resize((largeur, round(im.height * largeur / im.width)), Image.LANCZOS)
    im.save(dest, "JPEG", quality=85)


def serie(nom, travail, fils, depuis=0, total=None, **reduire):
    """travail : [(adresse, fichier)], téléchargés par fils à la fois ; rend le nombre d'échecs. depuis, total : où en est
    toute la série d'images (la barre de la fenêtre d'installation avance d'un seul tenant, des députés aux affiches)."""
    reste = [(a, f) for a, f in travail if a and not f.exists()]
    total = total or len(reste)
    print(f"   {nom} : {len(travail) - len(reste)} déjà là, {len(reste)} à télécharger", flush=True)
    annonce(f"{nom[0].upper()}{nom[1:]} : {len(travail) - len(reste)} déjà là, {len(reste)} à télécharger")
    compte = {"faits": 0, "rates": 0, "quota": False}
    verrou = threading.Lock()

    def un(adresse_fichier):
        adresse, fichier = adresse_fichier
        if compte["quota"]:
            return
        try:
            contenu = lire(adresse)
        except Quota:
            compte["quota"] = True
            return
        try:
            enregistrer(contenu, fichier, **reduire) if contenu else None
        except Exception:
            contenu = None
        with verrou:
            compte["faits"] += 1
            compte["rates"] += contenu is None
            i = compte["faits"]
        signe(depuis + i, total, nom, forcer=i == len(reste))
        if i % 500 == 0:
            print(f"      {i} / {len(reste)}", flush=True)

    with ThreadPoolExecutor(max_workers=fils) as groupe:
        list(groupe.map(un, reste))
    if compte["quota"]:
        manque = len(reste) - compte["faits"]
        print(f"   {nom} : limite du jour atteinte sur le site, {manque} reportées", flush=True)
        avertir(f"{manque} {nom} n'ont pas pu être téléchargées aujourd'hui (le site limite le nombre de téléchargements "
                "par jour) : relance l'installation demain, elles se compléteront.")
        return compte["rates"] + manque
    return compte["rates"]


def vignettes_commons(fichiers):
    """{nom de fichier Commons : adresse de sa vignette de 250 px} (l'API, par paquets de 50)."""
    adresses = {}
    fichiers = sorted(set(f for f in fichiers if f))
    annonce(f"Recherche des {len(fichiers)} photos sur Wikimedia Commons")
    for i in range(0, len(fichiers), 50):
        q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url",
                                    "iiurlwidth": 250, "titles": "|".join("File:" + f for f in fichiers[i:i + 50])})
        contenu = lire("https://commons.wikimedia.org/w/api.php?" + q)
        if not contenu:
            continue
        r = json.loads(contenu)
        retour = {n["to"]: n["from"] for n in r["query"].get("normalized", [])}
        for page in r["query"]["pages"].values():
            if "imageinfo" in page:
                adresses[retour.get(page["title"], page["title"]).removeprefix("File:")] = page["imageinfo"][0].get("thumburl")
        signe(min(i + 50, len(fichiers)), len(fichiers), "photos trouvées sur Wikimedia Commons")
        time.sleep(0.2)
    return adresses


def fichier_commons(page):
    """« https://commons.wikimedia.org/wiki/File:Louis_Loucheur.jpg » → « Louis Loucheur.jpg »."""
    return urllib.parse.unquote(str(page).split("File:", 1)[-1]).replace("_", " ") if page and "File:" in str(page) else None


def main():
    if not (DATA / "modele.duckdb").exists() or not (DATA / "depouillement.duckdb").exists():
        print("Images : la base n'est pas encore là (data/modele.duckdb) : rien à télécharger pour l'instant.")
        return 0
    con = duckdb.connect()
    con.execute(f"ATTACH '{(DATA / 'modele.duckdb').as_posix()}' AS m (READ_ONLY)")
    con.execute(f"ATTACH '{(DATA / 'depouillement.duckdb').as_posix()}' AS b (READ_ONLY)")
    photos = con.execute("SELECT fichier, adresse FROM m.photo WHERE fichier IS NOT NULL").df()
    series = []                                   # (nom, travail, téléchargements à la fois, réduction)
    # 1. Assemblée nationale et Sénat : les photos officielles, telles quelles
    for dossier, nom in (("an", "députés (Assemblée nationale)"), ("senat", "sénateurs (Sénat)")):
        p = photos[photos.fichier.str.startswith(dossier + "/")]
        series.append((nom, [(a, DATA / "photos" / f) for a, f in zip(p.adresse, p.fichier)], 4, {}))
    # 2. Wikimedia Commons : les personnalités (photo du modèle) et les candidats (credits.parquet)
    p = photos[photos.fichier.str.startswith("wikimedia/")]
    credits = DATA / "photos" / "candidats" / "credits.parquet"
    c = pd.read_parquet(credits) if credits.exists() else pd.DataFrame(columns=["fichier", "page"])
    a_faire = [(fichier_commons(a), DATA / "photos" / f) for a, f in zip(p.adresse, p.fichier)] + \
              [(fichier_commons(pg), DATA / "photos" / "candidats" / f) for pg, f in zip(c.page, c.fichier)]
    a_faire = [(n, f) for n, f in a_faire if not f.exists()]
    print(f"   Wikimedia Commons : {len(a_faire)} vignettes à chercher", flush=True)
    adresses = vignettes_commons([n for n, _ in a_faire])
    series.append(("photos libres (Wikimedia Commons)", [(adresses.get(n), f) for n, f in a_faire], 4, {"largeur": 200}))
    # 3. les affiches des Hauts-de-Seine
    a = con.execute("SELECT identifiant, adresse FROM b.affiches").df() if \
        con.execute("SELECT count(*) FROM duckdb_tables() WHERE database_name = 'b' AND table_name = 'affiches'").fetchall()[0][0] else \
        pd.DataFrame(columns=["identifiant", "adresse"])
    series.append(("affiches (Hauts-de-Seine)", [(u, DATA / "affiches" / f"{i}.jpg") for i, u in zip(a.identifiant, a.adresse)],
                   2, {"taille": 700}))
    # les téléchargements, comptés ensemble
    total = sum(1 for _, travail, _, _ in series for u, f in travail if u and not f.exists())
    rates = fait = 0
    for nom, travail, fils, reduire in series:
        n = sum(1 for u, f in travail if u and not f.exists())
        rates += serie(nom, travail, fils, depuis=fait, total=total, **reduire)
        fait += n
    print(f"Images : terminé ({rates} introuvables à leur source)." if rates else "Images : terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
