"""Les affiches électorales des Hauts-de-Seine (1968-1990) : Archives départementales des Hauts-de-Seine, open data du Département,
licence CC BY-NC-ND 4.0 (citer la source, pas d'usage commercial, ne pas modifier : les affiches sont montrées entières).

Table affiches (base_appli.py ← donnees/affiches/affiches.py), images dans data/affiches/.
"""
from functools import lru_cache

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from lecture import donnees as d

DOSSIER = d.DATA / "affiches"
CREDIT = "Archives départementales des Hauts-de-Seine · CC BY-NC-ND 4.0"
MAX_MOSAIQUE = 240          # au-delà, on demande de filtrer (une mosaïque de 2 000 affiches serait illisible et lente)
VIGNETTE = (150, 205)
LEGENDE = 40


@lru_cache(maxsize=1)
def tout():
    try:
        t = d.sql("SELECT * FROM affiches WHERE image ORDER BY annee, type, lieu")
    except duckdb.Error:
        return pd.DataFrame()
    t["annee"] = t["annee"].astype(int)
    t["texte"] = (t["candidats"].fillna("") + " " + t["description"].fillna("") + " " + t["lieu"].fillna("")).map(d.normaliser)
    return t


def disponible():
    return not tout().empty


def de_la_zone(zone, type_=None, annee=None, cherche=""):
    """Les affiches de la zone (commune, bureau → sa commune, circonscription, Hauts-de-Seine, Île-de-France, France), filtrées."""
    t = tout()
    if t.empty:
        return t
    code = str(zone.code)
    if zone.niveau == "bureau":
        code, niveau = code.split("_")[0], "commune"
    else:
        niveau = zone.niveau
    if niveau == "commune":
        t = t[t["communes"].str.split(",").map(lambda l: code in l)]
    elif niveau == "circo":
        t = t[t["circo"] == code]
    elif niveau == "departement" and code != "92" or niveau == "region" and code != "11":
        t = t.iloc[0:0]
    elif niveau not in ("france", "departement", "region"):
        t = t.iloc[0:0]
    if type_ and type_ != "Tous":
        t = t[t["type"] == type_]
    if annee and annee != "Toutes":
        t = t[t["annee"] == int(annee)]
    if cherche.strip():
        for mot in d.normaliser(cherche).split():
            t = t[t["texte"].str.contains(mot, regex=False)]
    return t


def _police(taille):
    for nom in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            pass
    return ImageFont.load_default()


def mosaique(t, colonnes):
    """Une planche d'affiches (vignettes entières, sur fond blanc) avec l'année, l'élection et le lieu sous chacune.
    Rend (image, identifiants dans l'ordre, (largeur, hauteur d'une case, nombre de colonnes))."""
    lc, hc = VIGNETTE[0] + 12, VIGNETTE[1] + LEGENDE + 12
    lignes = -(-len(t) // colonnes)
    planche = Image.new("RGB", (colonnes * lc, lignes * hc), "white")
    dessin = ImageDraw.Draw(planche)
    p1, p2 = _police(13), _police(12)
    for k, (_, a) in enumerate(t.iterrows()):
        x, y = (k % colonnes) * lc + 6, (k // colonnes) * hc + 6
        try:
            with Image.open(DOSSIER / f"{a['identifiant']}.jpg") as im:
                im = im.convert("RGB")
                im.thumbnail(VIGNETTE)
                planche.paste(im, (x + (VIGNETTE[0] - im.width) // 2, y + (VIGNETTE[1] - im.height) // 2))
        except OSError:
            dessin.rectangle([x, y, x + VIGNETTE[0], y + VIGNETTE[1]], outline="#767676")
        dessin.text((x, y + VIGNETTE[1] + 3), f"{a['annee']} · {a['type']}", fill="#161616", font=p1)
        lieu = str(a["lieu"])
        dessin.text((x, y + VIGNETTE[1] + 20), lieu if len(lieu) <= 24 else lieu[:23] + "…", fill="#3A3A3A", font=p2)
    return np.asarray(planche), list(t.index), (lc, hc, colonnes)
