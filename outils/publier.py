"""
publier.py — (pour Julien) Recopie dans ce dépôt le code de PROJET, aux mêmes emplacements, avant un commit.

    py outils/publier.py            (affiche ce qui a changé ; puis git add / commit / push)

Seuls les fichiers de CODE (et les petits fichiers remplis à la main) listés dans FICHIERS sont copiés :
jamais les données, qui se retéléchargent (installation/sources.csv).
"""
import filecmp
import shutil
from pathlib import Path

DEPOT = Path(__file__).resolve().parents[1]
PROJET = Path(r"C:\Users\Jujusilb\Desktop\PROJET")

FICHIERS = [  # motifs glob, relatifs à PROJET
    "BigData_IA/demo_megabase/construire_megabase.py",
    "BigData_IA/design_appli/pistes/fabriquer_geo.py",
    "BigData_IA/demo_carte/construire_donnees.py",
    "BigData_IA/data/trier_par_election.py",
    "BigData_IA/donnees_contexte/cdsp_anciens/fabriquer_cdsp.py",
    "BigData_IA/donnees_contexte/convertir_en_parquet.py",
    "BigData_IA/donnees_contexte/fabriquer_contexte_communes.py",
    "BigData_IA/donnees_contexte/referendums/fabriquer_referendums.py",
    "BigData_IA/donnees_contexte/historique_cage_piketty/fabriquer_historique.py",
    "BigData_IA/donnees_contexte/elus_2014/fabriquer_elus_2014.py",
    "BigData_IA/donnees_contexte/listes/fabriquer_listes.py",
    "BigData_IA/donnees_contexte/populations/fabriquer_populations.py",
    "BigData_IA/donnees_contexte/rne/fabriquer_rne.py",
    "BigData_IA/donnees_contexte/sieges_2026/fabriquer_sieges_2026.py",
    "BigData_IA/donnees_contexte/economie/fabriquer_economie.py",
    "BigData_IA/donnees_contexte/parlement/fabriquer_parlement.py",
    "BigData_IA/le_grand_depouillement/*.py",
    "BigData_IA/le_grand_depouillement/gd/*.py",
    "BigData_IA/le_grand_depouillement/outils/*.py",
    "BigData_IA/le_grand_depouillement/requirements.txt",
    "BigData_IA/le_grand_depouillement/LISEZMOI.md",
]


def main():
    vus = 0
    for motif in FICHIERS:
        for source in sorted(PROJET.glob(motif)):
            cible = DEPOT / source.relative_to(PROJET)
            vus += 1
            if cible.exists() and filecmp.cmp(source, cible, shallow=False):
                continue
            print(("modifié : " if cible.exists() else "nouveau : ") + cible.relative_to(DEPOT).as_posix())
            cible.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, cible)
    print(f"{vus} fichiers suivis.")


if __name__ == "__main__":
    main()
