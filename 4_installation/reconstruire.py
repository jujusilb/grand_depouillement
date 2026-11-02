"""
reconstruire.py — Refait toute la base du Grand Dépouillement à partir des sources officielles en ligne.
Lancé par INSTALLMOI.bat ; relançable : une étape déjà faite (son fichier de sortie existe) est sautée.

    py installation/reconstruire.py              (tout)
    py installation/reconstruire.py --liste      (les étapes, faites ou non)

Les scripts sont rangés par métier (1_telechargement, 2_nettoyage, 3_base) ; chacun trouve ses dossiers dans
chemins.py. Les fichiers téléchargés et fabriqués vont dans donnees/ (ignoré par git). Pour prendre le moins de place : on ne télécharge que ce dont les étapes restantes ont besoin, et
un fichier brut dont plus aucune étape n'a besoin devient un Parquet compressé (compacter.py).
"""
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))                                  # (chemins.py)
sys.path.insert(0, str(RACINE / "1_telechargement"))             # (telecharger.py)
import chemins as C  # noqa: E402
import compacter  # noqa: E402
import telecharger  # noqa: E402

D = C.DONNEES
N, B = RACINE / "2_nettoyage", RACINE / "3_base"


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
    ("epci", "Intercommunalités (INSEE)", D / "decoupage/EPCI_au_01-01-2026.xlsx",
     lambda: extraire_zip(D / "decoupage/epci_au_01-01-2026.zip", D / "decoupage", "EPCI_au_01-01-2026.xlsx")),
    ("iris", "Contours IRIS (IGN)", C.COLLECTE / "raw/contours-iris/CONTOURS-IRIS_2-1__SHP__FRA_2022-01-01",
     lambda: extraire_7z(C.COLLECTE / "raw/contours-iris/iris2022.7z", C.COLLECTE / "raw/contours-iris")),
    ("decouper", "Résultats : un fichier par scrutin", C.RESULTATS / "candidat/2026_muni_t2.parquet", N / "resultats/decouper_resultats.py"),
    ("megabase", "Méga base des 56 scrutins", D / "megabase/megabase.duckdb", B / "megabase.py"),
    ("geo", "Découpage géographique", D / "decoupage/geo_data.js", B / "decoupage.py"),
    ("pres2022", "Présidentielle 2022 pour la carte", C.RESULTATS / "2022_pres_t1_results.parquet", N / "resultats/pres2022.py"),
    ("carte", "Contours de la carte (long : géocodage des bureaux)", D / "carte/donnees/regions.js", B / "carte.py"),
    # --- phase 2 : le contexte ---
    ("referendums", "Référendums 1992, 2000, 2005", D / "referendums/referendums_participation.parquet", N / "referendums.py"),
    ("historique", "Élections 1793-1997 (Cagé et Piketty)", D / "historique/historique_participation.parquet",
     N / "historique.py"),
    ("preparer_cdsp", "Vieux scrutins du CDSP (Sciences Po) en Parquet", C.COLLECTE / "tri_parquet/1998_regi_t1/resultats/cdsp-regio1998-circ.parquet",
     N / "resultats/preparer_cdsp.py"),
    ("cdsp", "Législatives 1958-1997, cantonales et régionales anciennes (CDSP)", D / "cdsp/cdsp_participation.parquet",
     N / "cdsp.py"),
    ("elus2014", "Conseillers municipaux élus en 2014", D / "elus_2014/elus_municipaux_2014.parquet", N / "elus_2014.py"),
    ("assembler2014", "Candidatures des municipales 2014 (par région → un fichier)",
     [D / "listes/brut/muni2014_t2_petites_communes.csv", D / "listes/candidats_listes.parquet"],
     N / "listes/assembler_2014.py"),
    ("listes", "Listes et colistiers", D / "listes/candidats_listes.parquet", N / "listes/fabriquer_listes.py"),
    ("populations", "Populations communales (INSEE)", D / "populations/populations.parquet", N / "populations.py"),
    ("rne", "Répertoire national des élus (2020 et 2026)", D / "rne/rne_municipaux.parquet", N / "rne.py"),
    ("sieges2026", "Sièges à pourvoir en 2026", D / "sieges_2026/sieges_2026.parquet", N / "sieges_2026.py"),
    ("conversion_insee", "Revenus et chômage (INSEE) en Parquet", D / "insee/revenus/FILO2021_DISP_COM.parquet", N / "insee/convertir_en_parquet.py"),
    ("contexte", "Contexte des communes", D / "insee/contexte_communes.parquet", N / "insee/contexte_communes.py"),
    ("economie", "Économie (BCE, FRED, INSEE, Big Mac)", D / "economie/economie_mois.parquet", N / "economie.py"),
    ("amo10", "Députés en exercice (Assemblée nationale)", D / "parlement/brut/AMO10/json",
     lambda: extraire_zip(D / "parlement/brut/AMO10.json.zip", D / "parlement/brut/AMO10")),
    ("parlement", "Parlement et sénatoriales (+ photos officielles)", D / "parlement/senatoriales_resultats.parquet",
     N / "parlement.py"),
    # --- la base de l'appli ---
    ("base", "Base de l'appli", C.BASE, B / "base_appli.py"),
]


# fichiers fabriqués en route, compactés eux aussi après leur dernière étape
INTERMEDIAIRES = {"listes": [D / f"listes/brut/muni2014_{j}.csv" for j in ("t1_listes", "t1_petites_communes", "t2_petites_communes")]}


def fait(etape):
    """Une étape est faite si son fichier de sortie existe (ou l'un d'eux, quand il y en a plusieurs)."""
    preuves = etape[2] if isinstance(etape[2], list) else [etape[2]]
    return any(p is not None and p.exists() for p in preuves)


def lancer(script):
    r = subprocess.run([sys.executable, script.name], cwd=script.parent,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", GD_INSTALLATION="1",
                                                         GD_DECHET=os.environ.get("GD_DECHET") or str(C.DONNEES / "dechet")))
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
            telecharger.annonce(f"Étape {i} sur {len(ETAPES)} : {nom}")
            telecharger.signe(i - 1, len(ETAPES), nom, forcer=True)
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
