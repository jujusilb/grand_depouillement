"""Le plan des rues sous la carte : des tuiles OpenStreetMap, assemblées avec Pillow (aucune bibliothèque en plus).

Les tuiles téléchargées sont gardées dans data/tuiles/ : la 2e fois, plus besoin d'internet pour ce coin-là.
Sans internet, plan() renvoie None et la carte s'affiche simplement sans fond.
Le plan est passé en gris clair (comme un fond « discret ») pour que les couleurs des bureaux restent lisibles.
Règles d'OpenStreetMap : peu de tuiles à la fois, un nom d'appli clair, et la mention « © les contributeurs d'OpenStreetMap ».
"""
import io
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from gd import donnees as d

ADRESSE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
CLARTE = 0.55          # 0 = plan d'origine, 1 = blanc : on éclaircit le plan gris pour qu'il reste discret
NAVIGATEUR = "LeGrandDepouillement/1.0 (appli d'apprentissage, usage personnel)"
MENTION = "© les contributeurs d'OpenStreetMap"
TUILES_MAX = 24        # au plus 24 tuiles par carte : on choisit le zoom en fonction
DOSSIER_TUILES = d.DOSSIER / "data" / "tuiles"


def _x(lon, z):
    return (lon + 180) / 360 * 2 ** z


def _y(lat, z):
    r = math.radians(lat)
    return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z


def _lat(y, z):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))


def _tuile(z, x, y):
    fichier = DOSSIER_TUILES / str(z) / str(x) / f"{y}.png"
    if fichier.exists():
        return Image.open(fichier).convert("RGB")
    requete = urllib.request.Request(ADRESSE.format(z=z, x=x, y=y), headers={"User-Agent": NAVIGATEUR})
    with urllib.request.urlopen(requete, timeout=6) as r:
        contenu = r.read()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_bytes(contenu)
    return Image.open(io.BytesIO(contenu)).convert("RGB")


def plan(lon_min, lon_max, lat_min, lat_max):
    """(image, étendue) du plan des rues qui couvre ce rectangle, ou None (pas d'internet…).
    L'image est remise en latitude « droite » (la carte de l'appli n'est pas en Mercator)."""
    z = 17
    while z > 3:
        nx = int(_x(lon_max, z)) - int(_x(lon_min, z)) + 1
        ny = int(_y(lat_min, z)) - int(_y(lat_max, z)) + 1
        if nx * ny <= TUILES_MAX:
            break
        z -= 1
    x0, x1 = int(_x(lon_min, z)), int(_x(lon_max, z))
    y0, y1 = int(_y(lat_max, z)), int(_y(lat_min, z))
    cases = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    try:
        with ThreadPoolExecutor(2) as pool:      # 2 à la fois au plus (règle d'OpenStreetMap)
            images = list(pool.map(lambda c: _tuile(z, *c), cases))
    except Exception:
        return None
    grande = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    for (x, y), im in zip(cases, images):
        grande.paste(im, ((x - x0) * 256, (y - y0) * 256))
    gris = np.asarray(grande.convert("L"), dtype=float)          # en gris, puis éclairci
    px = np.repeat((gris + (255 - gris) * CLARTE)[:, :, None], 3, axis=2).astype(np.uint8)
    # Mercator → latitude régulière : chaque ligne de l'image finale va chercher la bonne ligne de la mosaïque
    haut, bas = _lat(y0, z), _lat(y1 + 1, z)
    lats = np.linspace(haut, bas, px.shape[0])
    lignes = np.array([(_y(l, z) - y0) * 256 for l in lats]).clip(0, px.shape[0] - 1).astype(int)
    gauche, droite = x0 / 2 ** z * 360 - 180, (x1 + 1) / 2 ** z * 360 - 180
    return px[lignes], (gauche, droite, bas, haut)
