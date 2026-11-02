# Le Grand Dépouillement

Les élections françaises de 1793 à 2026, bureau par bureau quand on les a : résultats, participation, carte, sièges,
personnes et mandats, partis, Parlement. Une appli tkinter sur une base DuckDB, faite uniquement de données ouvertes.

## Installer (sur un PC Windows)

1. Télécharger [`INSTALLMOI.bat`](https://github.com/jujusilb/grand_depouillement/raw/main/INSTALLMOI.bat) et le mettre dans le dossier de son choix.
2. Double-cliquer dessus (Windows : « Informations complémentaires » → « Exécuter quand même »).
3. Taper **2** (les données toutes prêtes) ou **1** (tout refabriquer depuis les sources officielles).
4. Ensuite : double-clic sur `LANCER_L_APPLI.bat`.

Le dossier contient alors `appli\` (l'appli et ses données) et `outils\` (Python, le code, les fichiers temporaires).

## Où est quoi

| Dossier | Ce qu'il contient |
| --- | --- |
| `appli/` | **l'appli** : `lancer.py` pour la démarrer |
| `appli/interface/` | les fenêtres tkinter : la fenêtre, le thème (couleurs, tailles), le catalogue des vues, l'export, l'autotest |
| `appli/graphiques/` | les graphiques : résultats, personnes, fond de carte |
| `appli/politique/` | les calculs politiques : sièges et conseils (code électoral), législatures, Parlement, votes, élus en place, personnes, candidats |
| `appli/lecture/` | la lecture de la base : requêtes, modèle des personnes, adresses, photos, affiches |
| `1_telechargement/` | aller chercher les sources : `sources.csv` (adresse officielle de chaque fichier), Wikidata, photos et affiches |
| `2_nettoyage/` | mettre chaque source en forme (un script par source : référendums, listes, RNE, INSEE, Parlement…) |
| `3_base/` | assembler la base : méga base, découpage, contours de la carte, base de l'appli ; `modele/` : les personnes et mandats |
| `4_installation/` | le fil rouge qui lance tout dans l'ordre (`reconstruire.py`) |
| `saisies/` | ce qui est rempli à la main : explications des nuances, idéologies des partis, promotions de l'ENA, liens familiaux |
| `chemins.py` | où est chaque dossier de données (un seul endroit à changer) |
| `donnees/` | les données (pas sur GitHub : retéléchargées ou refabriquées) |

## Sources

Ministère de l'Intérieur et INSEE (data.gouv.fr), IGN, Assemblée nationale, Sénat, CDSP (Sciences Po), Julia Cagé et
Thomas Piketty (unehistoireduconflitpolitique.fr), Archives départementales des Hauts-de-Seine, Wikidata et Wikimedia
Commons. Chaque fichier : son adresse dans `1_telechargement/sources.csv`, sa licence dans la base.
