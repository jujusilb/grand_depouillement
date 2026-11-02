"""
donnees_pretes.py — Option 2 de INSTALLMOI.bat : les données toutes prêtes, au lieu de tout refabriquer.

    py installation/donnees_pretes.py

Télécharge la dernière « Release » du dépôt GitHub (donnees_appli.zip : depouillement.duckdb + modele.duckdb ;
adresses.parquet ; images.zip : toutes les photos et les affiches) et la range dans BigData_IA/donnees/appli/. Relançable : ce qui est déjà là est gardé.
"""
import sys
import zipfile
from pathlib import Path

import requests

import telecharger

ICI = Path(__file__).resolve().parent
DATA = ICI.parent / "donnees" / "appli"
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
        # (une archive est « déjà là » quand ce qu'elle contient est là : la base, ou les affiches pour images.zip)
        fait = {"donnees_appli.zip": DATA / "depouillement.duckdb", "images.zip": DATA / "affiches" / "LISEZMOI.txt"}.get(a["name"], cible)
        if fait.exists():
            print(f"   {a['name']} : déjà là")
            continue
        print(f"   {a['name']} ({telecharger.taille_lisible(a['size'])})")
        telecharger.annonce(f"{a['name']} ({telecharger.taille_lisible(a['size'])}) depuis GitHub")
        if not telecharger.telecharger(a["browser_download_url"], cible, a["size"]):
            print(f"Impossible de télécharger {a['name']}. Relancer INSTALLMOI.bat reprendra ici.")
            return 1
        if cible.suffix == ".zip":
            telecharger.annonce(f"Décompression de {a['name']}")
            with zipfile.ZipFile(cible) as z:
                membres = z.namelist()
                for i, m in enumerate(membres, 1):
                    z.extract(m, DATA)
                    telecharger.signe(i, len(membres), "fichiers décompressés")
            if a["name"] == "images.zip":
                (DATA / "affiches" / "LISEZMOI.txt").write_text(
                    "Photos et affiches installées depuis la Release GitHub (images.zip). Chacune garde son auteur et sa "
                    "licence dans la base ; 1_telechargement/images.py complète ce qui manque depuis les sites d'origine.
",
                    encoding="utf-8")
            cible.unlink()                 # (le moins de place possible)
    print("Données prêtes installées.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
