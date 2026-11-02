# Le Grand Dépouillement

Les **56 scrutins de 1999 à 2026**, bureau par bureau, et **51 scrutins de 1793 à 1997** commune par commune, dans une appli tkinter : résultats, participation, évolutions,
carte (dans l'appli), nuages de points, économie, listes et colistiers. Design « Marianne » de l'atelier
(`design_appli/pistes/atelier.html`), graphiques **seaborn** ou **matplotlib** (un bouton en haut à droite).

## Lancer

| Situation | Quoi faire |
|---|---|
| Sur ce PC | double-clic sur **`lancer.bat`** (ou `py le_grand_depouillement.py`) |
| Première fois, ou après avoir changé les sources | `py preparer_donnees.py` : fabrique `data\depouillement.duckdb` (~1 min, 530 Mo) |
| Sur un autre PC **avec** Python | copier tout le dossier `le_grand_depouillement\` (avec `data\`), puis **`installer.bat`** une fois, puis `lancer.bat` |
| Sur un autre PC **sans** Python | **`construire_exe.bat`** ici, puis copier (ou zipper) le dossier `dist\LeGrandDepouillement\` ; on lance `LeGrandDepouillement.exe` |

Le dossier `dist\LeGrandDepouillement\` pèse ~1,8 Go (dont 530 Mo de base et 365 Mo d'adresses). Sur un autre PC, Windows peut afficher
« Windows a protégé votre ordinateur » (exe non signé) : « Informations complémentaires » → « Exécuter quand même ».
Le `.exe` ne se modifie pas : après une modification du code, relancer `construire_exe.bat`.

## Utiliser

- **Barre bleue** : trois boutons qui déroulent leur volet **par-dessus** la page (un 2e clic le replie) ; fermés, ils résument le choix.
  - 🗳 **Scrutin** : type, année, tour (1er, 2nd, ou **les 2 tours** = le 2nd tour là où il a eu lieu, sinon le 1er), regroupement (candidat ou nuance).
  - 📍 **Zone** : région → département → arrondissement → intercommunalité → circonscription (législatives) ou canton
    (cantonales, départementales) → commune → arrondissement de Paris/Lyon/Marseille → bureau. Chaque liste ne propose que ce qui est dans le choix précédent.
  - Les **référendums** sont dans Scrutin (« 1992 · Maastricht », « 2000 · Quinquennat », « 2005 · Constitution européenne ») :
    un seul tour, OUI et NON sont rangés comme deux « candidats » (toutes les vues marchent). 1992 n'existe que par commune.
  - **Avant 2002** (données de Julia Cagé et Thomas Piketty, *Une histoire du conflit politique*, Seuil 2023, unehistoireduconflitpolitique.fr) :
    législatives 1848 → 1997, présidentielles 1848 et 1965 → 1995 (2 tours), référendums 1793, 1795 et mai 1946, **par commune**
    (« bureau » 0000 = la commune entière ; communes ramenées à leur code INSEE actuel). Aux législatives, un « candidat » = un courant
    (PCF, SFIO, RADSOC…) ; sa nuance le range dans une famille d'aujourd'hui pour la couleur (approximatif). Deux législatives la même
    année (1871, 1946) : « 1946 · juin », « 1946 · novembre ». Fabriqué par `donnees_contexte/historique_cage_piketty/fabriquer_historique.py`.
  - **Le CDSP** (Sciences Po, données du ministère) ajoute : les **législatives au 2nd tour 1958-1997** (par circonscription ;
    candidats nommés dès 1988), les **cantonales 1988-1998** (par canton) et les **régionales 1986-1998** (département ou
    circonscription). Pas de commune : ils se lisent pour la France, une région ou un département. `donnees_contexte/cdsp_anciens/`.
- **Qui sont les candidats** (onglet Candidat) : âge le jour du vote, profession, sortant, pour 352 000 candidats de 24 élections
  (2002-2024 : législatives, régionales, départementales, européennes, sénatoriales, municipales 2014 et 2020 au 2nd tour).
  Section « Qui sont-ils ? » dans la fiche, et vue **Profils des candidats** (pyramide des âges, professions). `gd/candidats.py`.
- **Photos des candidats** (onglet Candidat, panneau de droite) : 2 500 photos libres de Wikimedia Commons trouvées via Wikidata,
  chacune affichée avec son **auteur et sa licence** (obligatoire). `gd/photos.py`, photos dans `data/photos/candidats/`.
  - En haut du volet Zone : **🔎 Commune** (tape un bout de nom) et **📫 Adresse → son bureau** (sans internet : les 16 millions
    d'adresses du répertoire électoral, `data/adresses.parquet`, fabriqué depuis `PROJET/election/table-adresses-reu.csv` ;
    chaque adresse a SON bureau officiel ; elle s'affiche en point rouge sur la carte).
- **Onglets** Participation · Candidat · Dans le temps · Carte · Comparer · Nuages · Économie, et leurs **pastilles** (les vues).
- **Sièges** : l'assemblée élue par le scrutin choisi, recalculée avec les règles du code électoral (`gd/sieges.py`) —
  Assemblée nationale (législatives, circonscriptions reconstituées), conseil départemental, régional (2015, 2021), municipal
  (2020, 2026), eurodéputés (2019, 2024) — en hémicycle ou en liste des élus. Et le Parlement d'aujourd'hui (`gd/parlement.py`) :
  **Assemblée actuelle** et **Sénat actuel** par groupe (clic = fiche avec photo), **Trombinoscope** (photos officielles,
  toute la chambre ou le département choisi). Source : open data de l'Assemblée et du Sénat (`donnees_contexte/parlement/`).
- **Votes** : qui a voté quoi à l'Assemblée (`gd/votes.py`). **Tous les scrutins publics depuis 2012** (19 000, député par député,
  open data de l'Assemblée) et **les grands votes de l'histoire** (1959 → 2010 : pages du site de l'Assemblée et Journal officiel).
  Hémicycle du vote (couleur = le vote, contour = le groupe ; clic = la fiche du député, sa photo et ses autres grands votes),
  vote des groupes, liste « qui a voté quoi » (tape un nom). Avant 1998, les listes viennent des PDF numérisés du Journal officiel,
  lus mot à mot avec leur position (pdfplumber) : une liste n'est gardée que si les comptes collent au résultat officiel
  (loi Veil, peine de mort, dépénalisation de l'homosexualité) ; sinon (lecture trop abîmée) seul le résultat officiel est montré.
  Fabriqué dans `donnees_contexte/votes_deputes/`.
- **Affiches** : les 2 234 affiches électorales des **Hauts-de-Seine, 1968-1990** (Archives départementales des Hauts-de-Seine,
  open data du Département, licence **CC BY-NC-ND 4.0** : citées, sans usage commercial, montrées entières et non modifiées).
  Planche filtrable (commune ou circonscription du 92, élection, année, nom : « SARKOZY », « écologie »…), clic = l'affiche en grand,
  sa cote et l'original en ligne ; dans l'onglet Candidat, les affiches des candidats de l'élection choisie (ex. présidentielle 1969).
  Fabriqué par `donnees_contexte/affiches_92/fabriquer_affiches.py` (vignettes de 700 px dans `data/affiches/`, ~160 Mo).
- **Sénatoriales** 2017 et 2023 dans Scrutin : un « bureau » = le collège des grands électeurs d'un département.
- **Comparer** : deux zones de n'importe quel niveau (un bureau et une commune…). Sur la carte, clique une zone puis « ⚖ Comparer » ;
  ou choisis-la dans le volet Zone puis « ➕ Ajouter la zone choisie ».
- **🏆 Top** (à droite des onglets) : un classement réglable (Top 5 → 100, quelles zones, plus hauts / plus bas, quel taux ou quel candidat).
  Dans les onglets Nuages et Économie, ce bouton devient **Réglages du nuage** (X, Y, un point =, diagonale).
- **Carte** : l'échelle se **choisit** (régions, départements, communes, bureaux) ; un **clic** sur une zone affiche son détail à droite,
  avec « 📍 Choisir comme zone ». France entière = mosaïque des communes ; les bureaux dès qu'une région est choisie.
- **Panneau de droite** (le « couteau suisse » de la vue) : explication, **autres façons de voir** (la même information en barres,
  anneau, tableau, boîtes…), légende, chiffres clés, réglages de la vue, **listes et colistiers** (municipales 2020/2026,
  régionales 2021, européennes 2019/2024), précaution de lecture.
- **seaborn / matplotlib** (barre du bas, à droite) : le même graphique, dessiné avec l'une ou l'autre bibliothèque.
- **Accessibilité** : **A− / A+** (barre du bas) ou **Ctrl + / Ctrl − / Ctrl 0** agrandit tous les textes, fenêtre et graphiques
  (90 → 200 %, gardé d'une fois sur l'autre) ; **Tab** passe d'un bouton à l'autre (liseré orange), **Entrée** ou **Espace** l'active.
  Contrastes WCAG AA vérifiés par `py outils/audit_contrastes.py` ; le détail est dans `AUDIT_ACCESSIBILITE.md`.
- **📄 Lire en texte (Ctrl+E)** et **📊 CSV (Ctrl+Maj+E)**, en haut du panneau de droite : la vue affichée, avec toutes ses
  valeurs, en fichier texte (Bloc-notes, lu par NVDA) ou en CSV (tableur), dans `Documents\Le Grand Dépouillement\exports` (`gd/export.py`).

## Modifier l'appli (elle est faite pour ça)

| Je veux… | Fichier | Comment |
|---|---|---|
| ajouter / modifier / supprimer une **vue** ou un **onglet** | `gd/catalogue.py` | une ligne par vue (le mode d'emploi est en tête du fichier) |
| ajouter une **question de nuage** | `gd/catalogue.py` | une ligne dans `NUAGES` ou `NUAGES_ECO` |
| écrire le **graphique** d'une nouvelle vue | `gd/graphiques.py` | `def ma_vue(fig, ctx):` … `return {"legende": [...], "kpi": [...], "lecture": "..."}` |
| poser une nouvelle **question à la base** | `gd/donnees.py` | une fonction qui renvoie un DataFrame (requête SQL DuckDB) |
| changer les **couleurs, polices, styles** | `gd/theme.py` | voir ci-dessous |
| corriger la **couleur d'un parti** | `gd/theme.py` | `FAMILLES` (une couleur par famille), `NUANCES` (code du ministère → famille), `MOTS_POLITIQUES` (nom de candidat ou de liste) |
| le **plan des rues** sous la carte | `gd/fond_carte.py` | tuiles OpenStreetMap gardées dans `data/tuiles/` (internet seulement la 1re fois) |
| changer la **fenêtre** (volets, fiche, barre bleue) | `gd/fenetre.py` | |
| ajouter une **source de données** | `preparer_donnees.py` | une table de plus dans `data/depouillement.duckdb` |

`py le_grand_depouillement.py` relance l'appli après une modification. Pour vérifier toutes les vues d'un coup :
`set GD_TEST=C:\temp\captures` puis `py le_grand_depouillement.py` → une image par vue + `rapport.txt`, puis l'appli se ferme.

## Le thème (`gd/theme.py`) : l'appliquer à une autre appli

```python
from gd import theme
from gd.theme import C

fenetre = tk.Tk()
theme.appliquer(fenetre)                    # styles ttk (clam) + thème des graphiques (seaborn + matplotlib)
tk.Frame(fenetre, bg=C["primaire"])         # les couleurs ont un RÔLE : primaire, clair, pale, action, texte, gris, bordure…
ttk.Label(fenetre, text="Titre", style="Titre.TLabel")
ttk.Button(fenetre, text="Tracer ▶", style="Action.TButton")
```
- `C` : la palette Marianne par rôles ; `SERIES` : les couleurs des séries ; `TYPES_ELECTION` : une couleur fixe par type d'élection.
- `POLICE`, `POLICE_TITRE`, `POLICE_INTER`… : les polices (Segoe UI) ; `NOM_APPLI` : le nom, une seule fois.
- Styles ttk prêts : `Titre.TLabel`, `Gris.TLabel`, `Inter.TLabel`, `Libelle.TLabel`, `Etat.TLabel`, `Action.TButton`, `Clair.TButton`, `Pale.TFrame`…

## Les fichiers

| Fichier | Rôle |
|---|---|
| `le_grand_depouillement.py` | lance l'appli |
| `gd/theme.py` | couleurs, polices, styles ttk, thème seaborn/matplotlib |
| `gd/catalogue.py` | la liste des onglets, des vues et des questions |
| `gd/donnees.py` | toutes les requêtes à la base (aucun tkinter) |
| `gd/graphiques.py` | une fonction = une vue (aucun tkinter), seaborn ou matplotlib |
| `gd/fenetre.py` | la fenêtre : barre bleue, volets, onglets, graphique, fiche |
| `gd/autotest.py` | le mode test (photos de chaque vue) |
| `preparer_donnees.py` | rassemble toutes les sources dans `data/depouillement.duckdb` |
| `exporter_mariadb.py` | copie la base dans MariaDB (XAMPP), base `grand_depouillement`, pour la parcourir avec phpMyAdmin ; l'appli, elle, lit toujours DuckDB |

## Les données (`data/depouillement.duckdb`, un seul fichier)

Méga base (56 scrutins, 3,2 M lignes de participation, 27,5 M de résultats) · découpage (régions → bureaux, circonscriptions 2022,
cantons 2021, intercommunalités INSEE 2026) · contexte par commune (revenus, chômage, diplômes) · économie (euro, franc, baril,
essence, gazole, moral des ménages, inflation, chômage, Big Mac) · les 3 référendums (1992, 2000, 2005) · 51 scrutins de 1793 à 1997 par commune (Cagé-Piketty) · 2,1 M candidats et colistiers · contours de 2022 pour la carte.

## Limites connues
- Un bureau peut changer de numéro d'une élection à l'autre (il manque alors dans les comparaisons bureau à bureau).
- Contours de la carte : bureaux de 2022 ; circonscriptions 2022, cantons 2021 (rattachés par bureau).
- Blancs comptés à part seulement depuis 2014 environ ; municipales des petites communes : la somme des % peut dépasser 100.
- Référendums : blancs et nuls ne sont pas séparés (tout est dans « nuls ») ; 1992 par commune seulement (gris en échelle « bureaux »).
- Avant 2002 : par commune seulement ; législatives = 1er tour (ou tour unique), par courant et pas par candidat ; blancs et nuls ensemble.

## Sièges figés et législatures

- `figer_sieges.py` (lancé à la fin de `preparer_donnees.py`, appli fermée) calcule une fois pour toutes les sièges de chaque
  assemblée et les range dans la table `sieges_figes` (un résultat JSON par calcul, scrutin et zone) : Assemblée nationale
  (2002 → 2024), conseils départementaux (2001 → 2021), conseils régionaux (2015, 2021), conseils municipaux (2008, 2014,
  2020, 2026), délégation européenne. L'appli relit la seule ligne demandée ; sans la table, elle recalcule.
- Taille d'un conseil municipal : le nombre publié par le ministère (2026, `donnees_contexte/sieges_2026/`), sinon la taille
  légale (CGCT, article L2121-2 ; 9 sièges sous 100 habitants avant 2014) selon la population municipale Insee en vigueur
  (1999 pour 2008, 2011 pour 2014, 2017 pour 2020 — `donnees_contexte/populations/`). La plus petite liste déposée ne sert
  qu'en dernier recours : une liste peut compter 2 candidats de plus que de sièges (et, en 2026, 2 de moins dans les petites
  communes). Sous 3 500 habitants (avant 2014) puis 1 000 : candidats un par un, chacun élu pour lui-même.
- Noms des élus : les premiers de chaque liste déposée (2014, 2020, 2026). Les listes du 2nd tour 2014 ne sont pas dans
  `data/tri` : on prend celles du 1er tour (les colistiers venus d'une fusion manquent). 2008 : sièges sans noms.
- Onglet Sièges → Conseil en place : qui siège vraiment, d'après le Répertoire national des élus (`donnees_contexte/rne/`,
  versions de janvier 2020, décembre 2020 — copies de l'Internet Archive — et août 2026). Commune (Paris, Lyon, Marseille
  compris), intercommunalité, département, région. Le RNE ne dit pas la liste d'un élu : on la retrouve par son nom dans les
  listes déposées (2014, 2020, 2026, régions 2021 ; en 2014 la nuance vient des résultats), ou parmi les binômes des
  départementales (2015, 2021) ; sinon (régions de 2015), les élus sont rangés par fonction.
- Onglet Sièges → Législature : les 17 législatures de la Ve République. Noms : open data de l'Assemblée (2002 →), CDSP
  (1988-2002), Wikidata (1958-1988, `donnees_contexte/legislatures/telecharger_wikidata.py`).
