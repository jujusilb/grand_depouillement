"""
reconstruire.py — Refait toute la base du Grand Dépouillement à partir des sources officielles en ligne.
Lancé par INSTALLMOI.bat ; relançable : une étape déjà faite (son fichier de sortie existe) est sautée.

    py installation/reconstruire.py              (tout)
    py installation/reconstruire.py --liste      (les étapes, faites ou non)

Le dépôt a la forme du dossier PROJET de Julien (ELECTION/, BRUT/, BigData_IA/…) : chaque script tourne sans
modification, dans son dossier, comme chez lui. Les fichiers téléchargés et fabriqués restent dans le dépôt
(ignorés par git).
"""
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import telecharger

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
BD = RACINE / "BigData_IA"


def extraire_zip(archive, membre, cible):
    cible.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        cible.write_bytes(z.read(membre))


def extraire_7z(archive, dossier):
    import py7zr
    with py7zr.SevenZipFile(archive) as z:
        z.extractall(dossier)


# (nom, ce qui prouve que c'est fait, quoi faire) ; quoi faire = un script (lancé dans son dossier) ou une fonction
ETAPES = [
    ("Téléchargement des sources (phase 1)", None, lambda: telecharger.main(1)),
    ("Intercommunalités (INSEE)", BD / "design_appli/donnees_insee/EPCI_au_01-01-2026.xlsx",
     lambda: extraire_zip(BD / "design_appli/donnees_insee/epci_au_01-01-2026.zip", "EPCI_au_01-01-2026.xlsx",
                          BD / "design_appli/donnees_insee/EPCI_au_01-01-2026.xlsx")),
    ("Contours IRIS (IGN)", BD / "data/raw/contours-iris/CONTOURS-IRIS_2-1__SHP__FRA_2022-01-01",
     lambda: extraire_7z(BD / "data/raw/contours-iris/iris2022.7z", BD / "data/raw/contours-iris")),
    ("Résultats : un fichier par scrutin", BD / "parquets/data/candidat/2026_muni_t2.parquet", BD / "parquets/decouper_resultats.py"),
    ("Méga base des 56 scrutins", BD / "demo_megabase/megabase.duckdb", BD / "demo_megabase/construire_megabase.py"),
    ("Découpage géographique", BD / "design_appli/pistes/geo_data.js", BD / "design_appli/pistes/fabriquer_geo.py"),
    ("Présidentielle 2022 pour la carte", BD / "data/2022_pres_t1_results.parquet", BD / "data/fabriquer_pres2022.py"),
    ("Contours de la carte (long : géocodage des bureaux)", BD / "demo_carte/donnees/regions.js", BD / "demo_carte/construire_donnees.py"),
    ("Base de l'appli", BD / "le_grand_depouillement/data/depouillement.duckdb", BD / "le_grand_depouillement/preparer_donnees.py"),
]


def lancer(script):
    r = subprocess.run([sys.executable, script.name], cwd=script.parent, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r.returncode == 0


def main():
    if "--liste" in sys.argv:
        for i, (nom, preuve, _) in enumerate(ETAPES, 1):
            print(f"{i:2d}. [{'fait' if preuve and preuve.exists() else '    '}] {nom}")
        return 0
    t0 = time.time()
    for i, (nom, preuve, quoi) in enumerate(ETAPES, 1):
        if preuve and preuve.exists():
            print(f"[{i}/{len(ETAPES)}] {nom} : déjà fait")
            continue
        print(f"\n[{i}/{len(ETAPES)}] {nom}… ({time.strftime('%H:%M')})", flush=True)
        ok = lancer(quoi) if isinstance(quoi, Path) else quoi() is not False
        if not ok or (preuve and not preuve.exists()):
            print(f"\nÉCHEC à l'étape « {nom} ». Relancer INSTALLMOI.bat reprendra ici.")
            return 1
    print(f"\nBase reconstruite en {(time.time() - t0) / 60:.0f} min.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
