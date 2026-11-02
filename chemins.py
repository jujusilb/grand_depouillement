"""
chemins.py — Où est chaque chose. Tous les scripts de fabrication (1_telechargement à 4_installation) lisent leurs
dossiers ici : pour déplacer les données, on ne change que ce fichier.

    donnees/                    (pas sur GitHub : retéléchargé ou refabriqué par 4_installation/reconstruire.py)
        elections/              les fichiers du ministère et de l'INSEE (résultats agrégés, COG, répertoire électoral)
        brut/                   les autres sources telles que téléchargées (Wikidata, DILA, JORF, rattachements…)
        collecte/               les fichiers rassemblés à la main au fil du projet (tri/, raw/ : contours IRIS…)
        resultats/              un Parquet par scrutin (participation/, candidat/, candidats_details/)
        megabase/, decoupage/, carte/   les étapes de la base
        <thème>/                une source mise en forme (referendums/, listes/, rne/…) : son brut/ et ses Parquet
        appli/                  ce que lit l'appli : depouillement.duckdb, modele.duckdb, adresses, photos, affiches
    saisies/                    ce que Julien remplit à la main (nuances, idéologies, promotions de l'ENA, liens) : sur GitHub
"""
import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent
APPLI = RACINE / "appli"
SAISIES = RACINE / "saisies"
DONNEES = RACINE / "donnees"
ELECTIONS = DONNEES / "elections"
BRUT = DONNEES / "brut"
COLLECTE = DONNEES / "collecte"
RESULTATS = DONNEES / "resultats"
DONNEES_APPLI = DONNEES / "appli"
BASE = DONNEES_APPLI / "depouillement.duckdb"
# la corbeille avant toute suppression : PROJET/DECHET chez Julien, donnees/dechet ailleurs (GD_DECHET l'impose)
DECHET = Path(os.environ.get("GD_DECHET") or (RACINE.parents[1] / "DECHET" if (RACINE.parents[1] / "DECHET").exists()
                                              else DONNEES / "dechet"))


def dossier(nom):
    """Le dossier de données d'un thème (donnees/<nom>), créé s'il manque."""
    d = DONNEES / nom
    d.mkdir(parents=True, exist_ok=True)
    return d
