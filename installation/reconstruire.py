"""
reconstruire.py — Refait toute la base du Grand Dépouillement à partir des sources officielles en ligne.
Lancé par INSTALLMOI.bat ; relançable : une étape déjà faite (son fichier de sortie existe) est sautée.

    py installation/reconstruire.py              (tout)
    py installation/reconstruire.py --liste      (les étapes, faites ou non)

Le dépôt a la forme du dossier PROJET de Julien (ELECTION/, BRUT/, BigData_IA/…) : chaque script tourne sans
modification, dans son dossier, comme chez lui. Les fichiers téléchargés et fabriqués restent dans le dépôt
(ignorés par git). Pour prendre le moins de place : on ne télécharge que ce dont les étapes restantes ont besoin, et
un fichier brut dont plus aucune étape n'a besoin devient un Parquet compressé (compacter.py).
"""
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import compacter
import telecharger

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
BD = RACINE / "BigData_IA"
DC = BD / "donnees_contexte"


def extraire_zip(archive, dossier, membre=None):
    dossier.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extract(membre, dossier) if membre else z.extractall(dossier)


def extraire_7z(archive, dossier):
    import py7zr
    with py7zr.SevenZipFile(archive) as z:
        z.extractall(dossier)


# (clé, nom, ce qui prouve que c'est fait, quoi faire) ; quoi faire = un script (lancé dans son dossier) ou une fonction.
# Les sources de sources.csv sont rattachées à la clé de la DERNIÈRE étape qui les lit.
ETAPES = [
    # --- phase 1 : les résultats, la carte ---
    ("epci", "Intercommunalités (INSEE)", BD / "design_appli/donnees_insee/EPCI_au_01-01-2026.xlsx",
     lambda: extraire_zip(BD / "design_appli/donnees_insee/epci_au_01-01-2026.zip", BD / "design_appli/donnees_insee", "EPCI_au_01-01-2026.xlsx")),
    ("iris", "Contours IRIS (IGN)", BD / "data/raw/contours-iris/CONTOURS-IRIS_2-1__SHP__FRA_2022-01-01",
     lambda: extraire_7z(BD / "data/raw/contours-iris/iris2022.7z", BD / "data/raw/contours-iris")),
    ("decouper", "Résultats : un fichier par scrutin", BD / "parquets/data/candidat/2026_muni_t2.parquet", BD / "parquets/decouper_resultats.py"),
    ("megabase", "Méga base des 56 scrutins", BD / "demo_megabase/megabase.duckdb", BD / "demo_megabase/construire_megabase.py"),
    ("geo", "Découpage géographique", BD / "design_appli/pistes/geo_data.js", BD / "design_appli/pistes/fabriquer_geo.py"),
    ("pres2022", "Présidentielle 2022 pour la carte", BD / "data/2022_pres_t1_results.parquet", BD / "data/fabriquer_pres2022.py"),
    ("carte", "Contours de la carte (long : géocodage des bureaux)", BD / "demo_carte/donnees/regions.js", BD / "demo_carte/construire_donnees.py"),
    # --- phase 2 : le contexte ---
    ("referendums", "Référendums 1992, 2000, 2005", DC / "referendums/referendums_participation.parquet", DC / "referendums/fabriquer_referendums.py"),
    ("historique", "Élections 1793-1997 (Cagé et Piketty)", DC / "historique_cage_piketty/historique_participation.parquet",
     DC / "historique_cage_piketty/fabriquer_historique.py"),
    ("elus2014", "Conseillers municipaux élus en 2014", DC / "elus_2014/elus_municipaux_2014.parquet", DC / "elus_2014/fabriquer_elus_2014.py"),
    ("assembler2014", "Candidatures des municipales 2014 (par région → un fichier)",
     [DC / "listes/brut/muni2014_t2_petites_communes.csv", DC / "listes/candidats_listes.parquet"],
     DC / "listes/assembler_2014.py"),
    ("listes", "Listes et colistiers", DC / "listes/candidats_listes.parquet", DC / "listes/fabriquer_listes.py"),
    ("populations", "Populations communales (INSEE)", DC / "populations/populations.parquet", DC / "populations/fabriquer_populations.py"),
    ("rne", "Répertoire national des élus (2020 et 2026)", DC / "rne/rne_municipaux.parquet", DC / "rne/fabriquer_rne.py"),
    ("sieges2026", "Sièges à pourvoir en 2026", DC / "sieges_2026/sieges_2026.parquet", DC / "sieges_2026/fabriquer_sieges_2026.py"),
    ("conversion_insee", "Revenus et chômage (INSEE) en Parquet", DC / "revenus/FILO2021_DISP_COM.parquet", DC / "convertir_en_parquet.py"),
    ("contexte", "Contexte des communes", DC / "contexte_communes.parquet", DC / "fabriquer_contexte_communes.py"),
    ("economie", "Économie (BCE, FRED, INSEE, Big Mac)", DC / "economie/economie_mois.parquet", DC / "economie/fabriquer_economie.py"),
    ("amo10", "Députés en exercice (Assemblée nationale)", DC / "parlement/brut/AMO10/json",
     lambda: extraire_zip(DC / "parlement/brut/AMO10.json.zip", DC / "parlement/brut/AMO10")),
    ("parlement", "Parlement et sénatoriales (+ photos officielles)", DC / "parlement/senatoriales_resultats.parquet",
     DC / "parlement/fabriquer_parlement.py"),
    # --- la base de l'appli ---
    ("base", "Base de l'appli", BD / "le_grand_depouillement/data/depouillement.duckdb", BD / "le_grand_depouillement/preparer_donnees.py"),
]


# fichiers fabriqués en route, compactés eux aussi après leur dernière étape
INTERMEDIAIRES = {"listes": [DC / f"listes/brut/muni2014_{j}.csv" for j in ("t1_listes", "t1_petites_communes", "t2_petites_communes")]}


def fait(etape):
    """Une étape est faite si son fichier de sortie existe (ou l'un d'eux, quand il y en a plusieurs)."""
    preuves = etape[2] if isinstance(etape[2], list) else [etape[2]]
    return any(p is not None and p.exists() for p in preuves)


def lancer(script):
    r = subprocess.run([sys.executable, script.name], cwd=script.parent,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", GD_INSTALLATION="1"))
    return r.returncode == 0


def main():
    if "--liste" in sys.argv:
        for i, e in enumerate(ETAPES, 1):
            print(f"{i:2d}. [{'fait' if fait(e) else '    '}] {e[1]}")
        return 0
    t0 = time.time()
    restantes = {e[0] for e in ETAPES if not fait(e)}
    sources = telecharger.sources()
    besoin = [s for s in sources if s["etape"] in restantes]
    print("Téléchargement des sources…")
    if not telecharger.main(liste=besoin):
        print("\nÉCHEC du téléchargement. Relancer INSTALLMOI.bat reprendra ici.")
        return 1
    for i, (cle, nom, preuve, quoi) in enumerate(ETAPES, 1):
        if fait(ETAPES[i - 1]):
            print(f"[{i}/{len(ETAPES)}] {nom} : déjà fait")
        else:
            print(f"\n[{i}/{len(ETAPES)}] {nom}… ({time.strftime('%H:%M')})", flush=True)
            ok = lancer(quoi) if isinstance(quoi, Path) else quoi() is not False
            if not ok or not fait(ETAPES[i - 1]):
                print(f"\nÉCHEC à l'étape « {nom} ». Relancer INSTALLMOI.bat reprendra ici.")
                return 1
        gain = sum(compacter.compacter(f) for f in [RACINE / s["destination"] for s in sources if s["etape"] == cle]
                   + INTERMEDIAIRES.get(cle, []))
        if gain > 1e6:
            print(f"      (sources brutes compactées : {gain / 1e6:.0f} Mo gagnés)")
    print(f"\nBase reconstruite en {(time.time() - t0) / 60:.0f} min.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
