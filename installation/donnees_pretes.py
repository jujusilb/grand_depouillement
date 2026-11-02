"""
donnees_pretes.py — Option 2 de INSTALLMOI.bat : les données toutes prêtes, au lieu de tout refabriquer.

    py installation/donnees_pretes.py

Télécharge la dernière « Release » du dépôt GitHub (donnees_appli.zip : depouillement.duckdb + modele.duckdb ;
adresses.parquet) et la range dans BigData_IA/le_grand_depouillement/data/. Relançable : ce qui est déjà là est gardé.
"""
import sys
import zipfile
from pathlib import Path

import requests

import telecharger

ICI = Path(__file__).resolve().parent
DATA = ICI.parent / "BigData_IA" / "le_grand_depouillement" / "data"
RELEASE = "https://api.github.com/repos/jujusilb/grand_depouillement/releases/latest"
# (les fichiers qui ne vont pas dans data/ même : les crédits des photos des candidats — les photos, elles, viennent de
#  Wikimedia Commons, par images.py)
AILLEURS = {"credits_photos_candidats.parquet": DATA / "photos" / "candidats" / "credits.parquet"}


def main():
    r = requests.get(RELEASE, headers=telecharger.ENTETE, timeout=60)
    r.raise_for_status()
    publication = r.json()
    print(f"Données prêtes : « {publication['name']} »")
    DATA.mkdir(parents=True, exist_ok=True)
    for a in publication["assets"]:
        cible = AILLEURS.get(a["name"], DATA / a["name"])
        fait = DATA / "depouillement.duckdb" if a["name"] == "donnees_appli.zip" else cible
        if fait.exists():
            print(f"   {a['name']} : déjà là")
            continue
        print(f"   {a['name']} ({telecharger.taille_lisible(a['size'])})")
        if not telecharger.telecharger(a["browser_download_url"], cible, a["size"]):
            print(f"Impossible de télécharger {a['name']}. Relancer INSTALLMOI.bat reprendra ici.")
            return 1
        if cible.suffix == ".zip":
            with zipfile.ZipFile(cible) as z:
                z.extractall(DATA)
            cible.unlink()                 # (le moins de place possible)
    print("Données prêtes installées.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
