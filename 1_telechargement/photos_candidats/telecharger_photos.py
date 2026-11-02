"""
telecharger_photos.py — Les photos libres des candidats reconnus (candidats_choisis.parquet), depuis Wikimedia Commons.

    py telecharger_photos.py          (~15-20 min ; on peut l'arrêter et le relancer : les photos déjà là sont gardées)

1. On demande à l'API de Commons, par paquets de 50 fichiers : l'adresse d'une vignette de 250 px, l'AUTEUR et la LICENCE
   (les photos sont libres, mais il faut citer l'auteur et la licence : CC BY, CC BY-SA…).
2. On télécharge chaque vignette, on la réduit à 200 px de large, on l'enregistre en JPEG.

Sorties (dans l'appli) : donnees/appli/photos/candidats/<qid>.jpg
                         donnees/appli/photos/candidats/credits.parquet (candidat, qid, fichier, auteur, licence, page)
"""
import html
import sys
import io
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
from PIL import Image

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("photos_candidats")
SORTIE = C.DONNEES_APPLI / "photos" / "candidats"
SORTIE.mkdir(parents=True, exist_ok=True)
ENTETES = {"User-Agent": "LeGrandDepouillement/1.0 (appli d'apprentissage, usage personnel)"}
LARGEUR = 200

c = pd.read_parquet(ICI / "candidats_choisis.parquet")
c = c[c["image"].notna()].copy()
# « http://commons.wikimedia.org/wiki/Special:FilePath/Anne%20Hidalgo.jpg » → « Anne Hidalgo.jpg »
c["fichier"] = c["image"].map(lambda u: urllib.parse.unquote(u.rsplit("/", 1)[1]))


def lire(url, essais=4):
    for essai in range(essais):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=ENTETES), timeout=60).read()
        except Exception as e:
            if essai == essais - 1:
                raise
            time.sleep(5 * (essai + 1) * (3 if "429" in str(e) else 1))


def sans_balises(texte):
    """L'auteur est donné en HTML (« <a href=…>Jacques Paquier</a> ») : on garde le texte."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", texte or ""))).strip()


# 1. auteurs, licences et adresses des vignettes
infos = {}
fichiers = sorted(set(c["fichier"]))
for i in range(0, len(fichiers), 50):
    paquet = fichiers[i:i + 50]
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata",
                                "iiurlwidth": 250, "iiextmetadatafilter": "Artist|LicenseShortName",
                                "titles": "|".join("File:" + f for f in paquet)})
    r = json.loads(lire("https://commons.wikimedia.org/w/api.php?" + q))
    # Commons renvoie les titres « normalisés » (« _ » → espace, 1re lettre en majuscule) : on retrouve les nôtres
    retour = {n["to"]: n["from"] for n in r["query"].get("normalized", [])}
    for page in r["query"]["pages"].values():
        if "imageinfo" not in page:
            continue
        ii = page["imageinfo"][0]
        meta = ii.get("extmetadata", {})
        nom = retour.get(page["title"], page["title"]).removeprefix("File:")
        infos[nom] = dict(vignette=ii.get("thumburl"), page=ii.get("descriptionurl"),
                          auteur=sans_balises(meta.get("Artist", {}).get("value")) or "auteur inconnu",
                          licence=sans_balises(meta.get("LicenseShortName", {}).get("value")) or "licence libre")
    print(f"  infos : {min(i + 50, len(fichiers))} / {len(fichiers)}", flush=True)
    time.sleep(0.5)

# 2. les vignettes
lignes, rates, poids = [], [], 0
for n, r in enumerate(c.itertuples(), 1):
    info = infos.get(r.fichier)
    dest = SORTIE / f"{r.qid}.jpg"
    if not info or not info["vignette"]:
        rates.append(r.fichier)
        continue
    if not dest.exists():
        try:
            im = Image.open(io.BytesIO(lire(info["vignette"]))).convert("RGB")
            if im.width > LARGEUR:
                im = im.resize((LARGEUR, round(im.height * LARGEUR / im.width)), Image.LANCZOS)
            im.save(dest, "JPEG", quality=85)
            time.sleep(1.5)
        except Exception as e:
            rates.append(f"{r.fichier} ({e})")
            continue
    poids += dest.stat().st_size
    lignes.append((r.candidat, r.qid, dest.name, info["auteur"], info["licence"], info["page"]))
    if n % 100 == 0:
        print(f"  photos : {n} / {len(c)} — {poids / 1e6:.0f} Mo", flush=True)

pd.DataFrame(lignes, columns=["candidat", "qid", "fichier", "auteur", "licence", "page"]).to_parquet(SORTIE / "credits.parquet", index=False)
(ICI / "photos_ratees.txt").write_text("\n".join(rates), encoding="utf-8")
print(f"\n{len(lignes)} photos ({poids / 1e6:.0f} Mo) dans {SORTIE} · {len(rates)} ratées (photos_ratees.txt)")
