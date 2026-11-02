"""
integrer_logos.py — Les logos des partis politiques, d'après Wikidata (propriété P154 « logo », avec ses dates quand un
parti a changé de logo) : seulement les logos libres de Wikimedia Commons, chacun avec son auteur et sa licence.

    py integrer_logos.py          (MariaDB de XAMPP démarré ; relançable : refait la table, ne retélécharge pas les images)

Table parti_logo (id, parti_id, fichier, adresse, date_debut, date_fin, auteur, licence_id, source_id) ;
images : donnees/appli/logos/<parti_id>_<n>.png (vignettes de 200 px de large, en PNG : les logos sont souvent en SVG).
Les logos que Wikipédia montre au titre de l'« usage loyal » (PS, LR, RN…) ne sont pas sur Commons : ils ne sont pas pris.
"""
import io
import json
import sys
import time
import urllib.parse
from pathlib import Path

import pandas as pd
import requests
from PIL import Image

from integrer_politiques import ENTETES, licence, sans_balises
from outils_mariadb import charger, cle_etrangere, mysql, requete, sauvegarder, sources

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
DOSSIER = C.DONNEES_APPLI / "logos"
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
LARGEUR = 200


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def logos_wikidata(qids):
    """[(qid, nom du fichier Commons, début, fin)] : la propriété P154 de chaque parti, avec ses dates."""
    lignes = []
    for i in range(0, len(qids), 200):
        q = ("SELECT ?p ?logo ?debut ?fin WHERE { VALUES ?p { " + " ".join("wd:" + x for x in qids[i:i + 200]) + " } "
             "?p p:P154 ?st . ?st ps:P154 ?logo . OPTIONAL { ?st pq:P580 ?debut } OPTIONAL { ?st pq:P582 ?fin } }")
        r = requests.get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"}, headers=ENTETES, timeout=180)
        r.raise_for_status()
        for b in r.json()["results"]["bindings"]:
            lignes.append((b["p"]["value"].rsplit("/", 1)[1], urllib.parse.unquote(b["logo"]["value"].rsplit("/", 1)[1]),
                           b.get("debut", {}).get("value", "")[:10] or None, b.get("fin", {}).get("value", "")[:10] or None))
        time.sleep(1)
    return lignes


def infos_commons(fichiers):
    """{fichier : (vignette PNG de 250 px, page, auteur, licence, adresse de la licence)} (l'API, par paquets de 50)."""
    infos = {}
    for i in range(0, len(fichiers), 50):
        q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata",
                                    "iiurlwidth": 250, "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl",
                                    "titles": "|".join("File:" + f for f in fichiers[i:i + 50])})
        r = requests.get("https://commons.wikimedia.org/w/api.php?" + q, headers=ENTETES, timeout=120).json()
        retour = {n["to"]: n["from"] for n in r["query"].get("normalized", [])}
        for page in r["query"]["pages"].values():
            if "imageinfo" not in page:            # (pas sur Commons : un logo en « usage loyal » de Wikipédia)
                continue
            ii, meta = page["imageinfo"][0], page["imageinfo"][0].get("extmetadata", {})
            infos[retour.get(page["title"], page["title"]).removeprefix("File:")] = (
                ii.get("thumburl"), ii.get("descriptionurl"), sans_balises(meta.get("Artist", {}).get("value")) or "auteur inconnu",
                sans_balises(meta.get("LicenseShortName", {}).get("value")) or "licence libre",
                sans_balises(meta.get("LicenseUrl", {}).get("value")) or None)
        time.sleep(0.5)
    return infos


def main():
    t0 = time.time()
    p = requete("SELECT id, wikidata FROM parti WHERE wikidata IS NOT NULL")
    qid_parti = dict(zip(p.wikidata, p.id.astype(int)))
    etape(f"{len(qid_parti)} partis ont une fiche Wikidata")
    w = logos_wikidata(sorted(qid_parti))
    etape(f"{len(w)} logos sur Wikidata, pour {len({q for q, *_ in w})} partis")
    infos = infos_commons(sorted({f.replace("_", " ") for _, f, _, _ in w}))
    DOSSIER.mkdir(parents=True, exist_ok=True)
    src = sources(["logos Wikimedia Commons"])["logos Wikimedia Commons"]
    lignes, rang = [], {}
    for qid, fichier, debut, fin in sorted(w, key=lambda x: (x[0], x[2] or "")):
        info = infos.get(fichier.replace("_", " "))
        if not info or not info[0]:
            continue
        pid = qid_parti[qid]
        rang[pid] = rang.get(pid, 0) + 1
        dest = DOSSIER / f"{pid}_{rang[pid]}.png"
        if not dest.exists():
            try:
                im = Image.open(io.BytesIO(requests.get(info[0], headers=ENTETES, timeout=60).content)).convert("RGBA")
                if im.width > LARGEUR:
                    im = im.resize((LARGEUR, round(im.height * LARGEUR / im.width)), Image.LANCZOS)
                im.save(dest, "PNG")
                time.sleep(0.2)
            except Exception as e:
                etape(f"  {fichier} : {e.__class__.__name__}")
                rang[pid] -= 1
                continue
        lignes.append({"parti_id": pid, "fichier": f"logos/{dest.name}", "adresse": info[1], "date_debut": debut,
                       "date_fin": fin, "auteur": info[2][:255], "licence_id": licence(info[3], info[4]), "source_id": src})
    t = pd.DataFrame(lignes)
    t.insert(0, "id", range(1, len(t) + 1))
    if requete("SHOW TABLES LIKE 'parti_logo'").shape[0]:
        sauvegarder(C.DECHET, "parti_logo_avant", ["parti_logo"])
    mysql(f"""DROP TABLE IF EXISTS parti_logo;
              CREATE TABLE parti_logo (id INT NOT NULL PRIMARY KEY, parti_id INT NOT NULL, fichier VARCHAR(80) NOT NULL,
                adresse VARCHAR(400), date_debut DATE, date_fin DATE, auteur VARCHAR(255), licence_id INT NOT NULL,
                source_id INT NOT NULL, KEY ix_parti_logo_parti (parti_id)) {T}""")
    charger("parti_logo", t)
    for col, ref in (("parti_id", "parti"), ("licence_id", "licence"), ("source_id", "source")):
        cle_etrangere("parti_logo", col, ref)
    etape(f"parti_logo : {len(t)} logos libres pour {t.parti_id.nunique()} partis "
          f"({int((t.date_debut.notna()).sum())} datés) — fini en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
