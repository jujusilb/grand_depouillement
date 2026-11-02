"""
catalogue.py — TOUT ce que l'appli propose, en un seul endroit : les onglets, leurs vues (pastilles), les questions des nuages.

C'est le fichier à modifier pour faire évoluer l'appli, sans toucher à la fenêtre :

    AJOUTER une vue      1. écrire sa fonction dans graphiques.py :   def ma_vue(fig, ctx): ... return {"legende": [], "kpi": [], "lecture": "…"}
                         2. ajouter UNE ligne dans VUES ci-dessous, dans l'onglet voulu :
                            ("Ma vue", g.ma_vue, ["barres_h", "anneau"], ["indicateur"], "Une précaution de lecture."),
    MODIFIER une vue     changer son nom, ses formes (« Autres façons de voir »), ses réglages ou sa précaution ici.
    SUPPRIMER une vue    effacer (ou mettre en commentaire avec #) sa ligne.
    AJOUTER un onglet    ajouter une clé à VUES : "Mon onglet": [ ... ],   (il apparaît tout seul dans la fenêtre)
    AJOUTER une question de nuage   ajouter une ligne à NUAGES (onglet Nuages) ou NUAGES_ECO (onglet Économie).

Une ligne de VUES = (nom de la pastille, fonction qui dessine, formes possibles, réglages de la vue, précaution)
    formes possibles : barres_h, barres_v, anneau, tableau, histogramme, boites, nuage, chaleur, courbe  (la 1re = celle par défaut)
    réglages de la vue : indicateur, tranches, candidat, candidat2, texte, echelle, chambre, vote, depute, affiches, legislature,
                         personne, gouvernement, ecole, prefets_depuis   (fabriqués par fenetre.py, panneau de droite)
La barre latérale (fenetre.py) range les mêmes vues par QUESTIONS (MENU, plus bas) : une ligne = une question et le chemin
qui y répond (onglet, vue, élection, réglages).
"""

from gd import graphiques as g
from gd import graphiques_personnes as gp
from gd.graphiques import AXE

# =============================================================================================
# Les questions des nuages
# =============================================================================================

NUAGES = [
    ("Électeurs gardés ?", "Qui a gardé ses électeurs ?", AXE("Score", "2017_pres_t1", "Marine LE PEN"), AXE("Score", "2022_pres_t1", "Marine LE PEN"),
     "Commune", True, "Au-dessus de la diagonale, le candidat a progressé entre les deux élections ; en dessous, il a reculé."),
    ("1er → 2nd tour", "Le 1er tour annonce-t-il le 2nd ?", AXE("Score", "2022_pres_t1", "Marine LE PEN"), AXE("Score", "2022_pres_t2", "Marine LE PEN"),
     "Commune", True, "Un nuage serré : le 2nd tour suit le 1er. Au-dessus de la diagonale : le candidat a gagné des voix entre les tours."),
    ("Abstention hier / auj.", "Les abstentionnistes d'hier le sont-ils encore ?", AXE("Abstention", "2017_pres_t1"), AXE("Abstention", "2022_pres_t1"),
     "Commune", True, "Au-dessus de la diagonale, l'abstention a augmenté. Nuage serré : ce sont toujours les mêmes communes."),
    ("Prés. / légis.", "Présidentielle et législatives : même vote ?", AXE("Score", "2022_pres_t1", "Marine LE PEN"),
     AXE("Score", "2022_legi_t1", "RN", "Nuance"), "Commune", True, "Sous la diagonale : le parti fait moins aux législatives qu'à la présidentielle."),
    ("Local / national", "Vote local et vote national ?", AXE("Participation", "2020_muni_t1"), AXE("Participation", "2022_pres_t1"),
     "Commune", True, "Au-dessus de la diagonale : on vote plus pour le président que pour le maire."),
    ("Abstention → qui ?", "L'abstention profite-t-elle à quelqu'un ?", AXE("Abstention", "2022_pres_t1"), AXE("Score", "2022_pres_t1", "Marine LE PEN"),
     "Bureau de vote", False, "Si le nuage monte, ce candidat est plus fort là où l'on s'abstient beaucoup."),
    ("Blanc ou abstention", "Le vote blanc remplace-t-il l'abstention ?", AXE("Abstention", "2022_pres_t1"), AXE("Blancs", "2022_pres_t1"),
     "Bureau de vote", False, "Si le nuage monte : là où l'on s'abstient, on vote aussi plus blanc."),
    ("Gros bureaux", "Les gros bureaux votent-ils autrement ?", AXE("Inscrits", "2022_pres_t1"), AXE("Score", "2022_pres_t1", "Emmanuel MACRON"),
     "Bureau de vote", False, "À droite les gros bureaux (villes), à gauche les petits. Si le nuage monte, le candidat est plus fort en ville."),
    ("Revenu → vote", "Le revenu explique-t-il le vote ?", AXE("Niveau de vie médian (commune)"), AXE("Score", "2022_pres_t1", "Marine LE PEN"),
     "Commune", False, "Si le nuage descend, le candidat est plus fort dans les communes modestes."),
    ("Revenu → abstention", "Les communes modestes votent-elles moins ?", AXE("Niveau de vie médian (commune)"), AXE("Abstention", "2022_pres_t1"),
     "Commune", False, "Si le nuage descend vers la droite, on s'abstient moins dans les communes aisées."),
    ("Ma zone / France", "Ma zone vote-t-elle comme la France ?", AXE("Abstention"), AXE("Abstention"),
     "Élection", True, "Un point = une élection. Au-dessus de la diagonale, la zone s'abstient plus que la France. Choisis une zone !"),
    ("Duel", "Là où l'un est fort, l'autre est-il faible ?", AXE("Score", "2022_pres_t1", "Emmanuel MACRON"), AXE("Score", "2022_pres_t1", "Marine LE PEN"),
     "Bureau de vote", False, "Un point = un bureau. Si le nuage descend : là où l'un est fort, l'autre est faible."),
]
NUAGES_ECO = [
    ("📈 Suivi d'un indicateur", "Comment évolue cet indicateur ? Un trait = un scrutin : clique sur sa pastille pour le résultat national.",
     AXE("Moral des ménages"), AXE("Moral des ménages"),
     "Mois", False, "suivi"),
    ("Chômage + essence → moral", "Le chômage et l'essence pèsent-ils sur le moral des ménages ?",
     AXE("Chômage (France)", plus="Prix de l'essence (SP95)"), AXE("Moral des ménages"), "Mois", False,
     "Un point = un mois. Si le nuage descend : quand chômage et essence montent, le moral baisse (les deux sont ramenés à la même échelle)."),
    ("Moral → abstention", "Quand le moral baisse, s'abstient-on plus ?", AXE("Moral des ménages"), AXE("Abstention"), "Élection", False,
     "Un point = une élection. Compare les points d'une même couleur : une municipale mobilise toujours moins qu'une présidentielle."),
    ("Vie chère → blancs et nuls", "La vie chère pousse-t-elle au vote blanc ?", AXE("Big Mac (€)"), AXE("Blancs + nuls"), "Élection", False,
     "Un point = une élection depuis 2000. Les blancs ne sont comptés à part que depuis 2014 environ."),
    ("Inflation → abstention", "L'inflation éloigne-t-elle des urnes ?", AXE("Inflation"), AXE("Abstention"), "Élection", False,
     "Un point = une élection ; l'inflation sur un an, le mois avant le vote."),
    ("Chômage local → abstention", "Les communes touchées par le chômage votent-elles moins ?", AXE("Chômage (commune)"),
     AXE("Abstention", "2022_pres_t1"), "Commune", False, "Un point = une commune ; chômage du recensement 2022."),
]

# =============================================================================================
# Le catalogue des vues : onglet -> pastilles (nom, fonction, formes possibles, réglages de la vue, précaution)
# =============================================================================================

VUES = {
    "Participation": [
        ("Taux par bureau", g.taux_par_bureau, ["histogramme", "boites"], ["indicateur", "tranches"], "Blancs comptés à part seulement depuis 2014 environ."),
        ("Zone et ses niveaux", g.zone_et_niveaux, ["barres_v", "barres_h"], [], "Choisis une commune ou un bureau pour voir tous les niveaux."),
        ("Pondéré / non pondéré", g.pondere, ["barres_v"], [], "Le vrai taux est le pondéré : total des voix / total des inscrits."),
    ],
    "Candidat": [
        ("Résultats", g.resultats, ["barres_h", "barres_v", "anneau", "tableau"], [], "Score = total des voix / total des exprimés de la zone."),
        ("Score d'un candidat", g.score_candidat, ["histogramme", "boites"], ["candidat"], "Seulement les bureaux où le candidat a des voix."),
        ("Duel", g.duel, ["nuage", "chaleur"], ["candidat", "candidat2"], "Une corrélation ne dit pas pourquoi."),
        ("Zone / France", g.zone_contre_france, ["barres_v", "barres_h"], [], "Choisis une zone dans le volet Zone."),
        ("Profils des candidats", g.profils_candidats, [], [], "Fiches de candidatures du ministère : 2002-2024 (législatives, régionales, départementales, européennes…)."),
        ("Corrélations", g.correlations, ["chaleur"], [], "Une corrélation ne dit pas pourquoi : une variable cachée peut tout expliquer."),
    ],
    "Dans le temps": [
        ("Évolution", g.evolution, ["courbe", "barres_v"], ["indicateur"], "Un bureau peut changer de numéro d'une élection à l'autre."),
        ("Type ou année ?", g.type_ou_annee, ["chaleur"], ["indicateur"], "1er tour seulement."),
        ("Écarts entre bureaux", g.ecarts, ["boites"], ["indicateur"], "1er tour seulement ; un point = un bureau."),
        ("Suivre un nom", g.suivre, ["courbe"], ["texte"], "Aux législatives, un candidat n'est que dans une circonscription."),
        ("Qui arrive en tête", gp.premiers, [], [], "1er tour seulement, depuis 1999 ; arrivé en tête n'est pas élu."),
        ("Bascules départementales", gp.bascules, [], [], "Sièges recalculés (sièges figés), regroupés en quatre camps."),
    ],
    "Carte": [
        ("Résultats sur la carte", g.carte, [], ["echelle", "fond"], "Contours des bureaux de 2022 : un bureau renuméroté reste gris."),
        ("Participation sur la carte", g.carte, [], ["echelle", "fond", "indicateur"], "Contours des bureaux de 2022 : un bureau renuméroté reste gris."),
    ],
    "Sièges": [
        ("Hémicycle", g.hemicycle, [], [], "Sièges recalculés avec les règles du code électoral (voir sieges.py)."),
        ("Élus et listes", g.elus, [], [], "Les noms viennent des résultats (législatives, départementales) ou des listes déposées (municipales)."),
        ("Qui siège aujourd'hui", gp.qui_siege, [], [], "La dernière photo du Répertoire national des élus (août 2026), quelle que "
                                                          "soit l'élection choisie. Choisis une commune, une agglo, un département ou une région."),
        ("Conseil en place", g.conseil_en_place, [], [], "Qui siège vraiment (Répertoire national des élus : 2014, 2020, 2026). "
                                                          "Choisis une commune, une agglo, un département ou une région."),
        ("Législature", g.legislature_hemicycle, [], ["legislature"], "1958-1986 : le nom de l'élu est connu pour environ deux sièges sur trois (Wikidata)."),
        ("Assemblée actuelle", g.assemblee_actuelle, [], [], "Députés en exercice : groupes et places officiels (open data de l'Assemblée)."),
        ("Sénat actuel", g.senat_actuel, [], [], "Sénateurs en exercice : groupes officiels (open data du Sénat)."),
        ("Trombinoscope", g.trombinoscope, [], ["chambre"], "Photos officielles de l'Assemblée nationale et du Sénat."),
        ("Portrait des maires", gp.maires, [], [], "Trois photos du Répertoire national des élus : 2020 (élus 2014), 2020 (élus 2020), 2026."),
    ],
    "Votes": [
        ("Hémicycle du vote", g.vote_hemicycle, [], ["vote", "depute"], "Députés rangés par groupe, de gauche à droite (pas leurs vraies places)."),
        ("Vote des groupes", g.vote_groupes, [], ["vote"], "Un député peut voter autrement que son groupe : c'est fréquent sur les lois de société."),
        ("Qui a voté quoi", g.vote_liste, [], ["vote", "depute"], "Avant 2012 : noms tels qu'ils sont publiés (sans identifiant) ; Congrès = députés ET sénateurs."),
    ],
    "Affiches": [
        ("Affiches de campagne", g.affiches_campagne, [], ["affiches"], "Hauts-de-Seine seulement, 1968-1990 : ce que les Archives départementales ont conservé."),
        ("Affiches par année", g.affiches_par_annee, [], ["affiches"], "Le nombre d'affiches conservées, pas le nombre de candidats."),
    ],
    "Personnes": [
        ("Fiche d'une personne", gp.fiche_personne, [], ["personne"], "Une même personne peut apparaître deux fois si ses sources "
                                                                    "l'écrivent autrement et n'ont pas de date de naissance."),
        ("Un gouvernement", gp.gouvernement, [], ["gouvernement"], "Liste du Premier ministre (1944-2014), Journal officiel depuis."),
        ("Présidents", gp.presidents, [], [], "Conseil constitutionnel (élus depuis 1965) ; Wikidata pour le reste."),
        ("Préfets du département", gp.prefets, [], ["prefets_depuis"], "Années seules avant 1990 (Archives nationales)."),
        ("Écoles et pouvoir", gp.ecoles, [], ["ecole"], "Wikidata ne connaît que les diplômés « notables »."),
        ("Cumuls aujourd'hui", gp.cumuls, [], [], "Le Répertoire national des élus n'est pas toujours à jour."),
        ("Idéologies d'une zone", gp.ideologies_zone, [], [], "Législatives 2017-2024 : voix → parti de rattachement du "
                                                              "candidat → idéologies du parti (Wikidata)."),
        ("Échiquier politique", gp.echiquier, [], ["personne"], "Partis placés d'après Wikidata (positions, idéologies) ; "
                                                               "tape un nom pour voir son trajet d'un parti à l'autre."),
    ],
    "Comparer": [
        ("Deux zones", g.comparer_zones, ["barres_v", "barres_h"], ["comparaison"], "Score = voix / exprimés de chaque zone ; blancs et nuls = / votants."),
        ("Deux zones dans le temps", g.comparer_dans_le_temps, [], ["comparaison", "indicateur"], "Un bureau peut changer de numéro d'une élection à l'autre."),
    ],
    "Nuages": [(q[0], g.nuage, ["nuage", "chaleur"], [], "Une corrélation ne dit pas pourquoi.") for q in NUAGES],
    "Économie": [(q[0], g.suivi if i == 0 else g.nuage, [] if i == 0 else ["nuage"], [],
                  "Indicateurs nationaux, pris la veille du vote (dernière période terminée).") for i, q in enumerate(NUAGES_ECO)],
}
QUESTIONS = {"Nuages": NUAGES, "Économie": NUAGES_ECO}
NOMS_FORMES = {"barres_h": "▤ Barres", "barres_v": "▥ Colonnes", "anneau": "◔ Anneau", "tableau": "☰ Tableau", "histogramme": "▃▅ Histo",
               "boites": "⊟ Boîtes", "nuage": "⁘ Nuage", "chaleur": "▦ Densité", "courbe": "∿ Courbe"}
DESCRIPTIONS = {
    "Taux par bureau": "Comment un taux (abstention, blancs, nuls…) se répartit entre les bureaux de la zone.",
    "Zone et ses niveaux": "La zone choisie comparée à son département, sa région et la France.",
    "Pondéré / non pondéré": "Chaque électeur compte pour 1, ou chaque bureau ? L'écart révèle le poids des petits bureaux.",
    "Résultats": "Le score de chaque candidat, liste ou nuance dans la zone choisie.",
    "Score d'un candidat": "Comment le score d'un candidat varie d'un bureau à l'autre.",
    "Duel": "Un point par bureau : là où l'un est fort, l'autre est-il faible ?",
    "Zone / France": "La zone choisie comparée au résultat national, candidat par candidat.",
    "Corrélations": "Quels candidats montent ou baissent ENSEMBLE d'un bureau à l'autre.",
    "Profils des candidats": "Qui se présente ? L'âge des candidates et des candidats et leurs professions, dans la zone choisie.",
    "Évolution": "Un taux élection après élection dans la zone, comparé à la France.",
    "Type ou année ?": "L'abstention dépend-elle du type d'élection ou de l'époque ?",
    "Écarts entre bureaux": "Pour chaque scrutin, la dispersion d'un taux entre les bureaux de la zone.",
    "Suivre un nom": "Le score d'un nom à chaque élection depuis 1999.",
    "Hémicycle": "L'assemblée élue par ce scrutin : Assemblée nationale (législatives), conseil départemental, régional ou municipal "
                 "(de la zone choisie), eurodéputés français. De gauche à droite selon la famille politique.",
    "Législature": "Choisis une législature de la Ve République (I à XVII) : l'Assemblée siège par siège. Gros rond = on sait qui "
                   "y siégeait (clique dessus), petite pastille = on ne le sait pas encore.",
    "Assemblée actuelle": "Les 577 sièges de l'Assemblée d'aujourd'hui, par groupe parlementaire, chaque député à sa place. "
                          "Choisis un département : ses députés sont entourés.",
    "Sénat actuel": "Les 348 sénateurs d'aujourd'hui, par groupe. Choisis un département : ses sénateurs sont entourés.",
    "Trombinoscope": "Les photos des députés ou des sénateurs (réglage à droite), de toute la chambre ou du département choisi.",
    "Élus et listes": "Qui a été élu, où, avec quelle nuance et à quel tour — ou, pour les scrutins de listes, les sièges de chaque liste.",
    "Hémicycle du vote": "Un scrutin de l'Assemblée, chaque député à sa place dans son groupe, coloré selon son vote. "
                         "Choisis un grand vote de l'histoire, ou cherche n'importe quel scrutin depuis 2012.",
    "Vote des groupes": "Pour, contre, abstention : le vote de chaque groupe parlementaire.",
    "Qui a voté quoi": "La liste des députés et de leur vote ; tape un nom pour trouver le vote de ton député.",
    "Affiches de campagne": "Les affiches officielles des campagnes électorales dans les Hauts-de-Seine, de 1968 à 1990 "
                            "(Archives départementales). Choisis une commune du 92, une élection, une année, ou cherche un nom.",
    "Affiches par année": "Combien d'affiches les archives ont gardées, année par année et élection par élection.",
    "Deux zones": "Deux zones côte à côte : participation, blancs, nuls et scores. Bureau, commune, circonscription, canton…",
    "Deux zones dans le temps": "Un taux à chaque élection, pour les deux zones de la comparaison.",
    "Résultats sur la carte": "Le 1er de chaque zone. L'échelle se choisit (et ne change pas avec le zoom).",
    "Participation sur la carte": "Un taux zone par zone. L'échelle se choisit (et ne change pas avec le zoom).",
    "Qui siège aujourd'hui": "Le conseil en place aujourd'hui : municipal, communautaire, départemental ou régional selon la zone "
                             "choisie — sans avoir à choisir d'élection.",
    "Portrait des maires": "Les maires de France à trois dates : combien de femmes, quel âge, combien l'étaient déjà.",
    "Qui arrive en tête": "La zone élection après élection : la couleur de celui qui arrive en tête. Une couleur qui revient "
                          "toujours = un fief.",
    "Bascules départementales": "Les conseils départementaux qui ont changé de camp entre 2015 et 2021.",
    "Fiche d'une personne": "Tape un nom à droite : tout son parcours — mandats, postes au gouvernement, préfectures, grands "
                            "corps, écoles — sur une frise, et ses candidatures dans l'export.",
    "Un gouvernement": "Choisis un gouvernement à droite : tous ses membres, du décret de nomination à la fin des fonctions.",
    "Présidents": "Les présidents de la République depuis 1947, mandat par mandat.",
    "Préfets du département": "Les préfets du département choisi (volet Zone), de 1800 à aujourd'hui.",
    "Écoles et pouvoir": "ENA, Sciences Po, X, IRA : combien de leurs diplômés sont devenus élus, ministres, préfets.",
    "Cumuls aujourd'hui": "Qui a aujourd'hui deux mandats ou fonctions en même temps (député + maire…).",
    "Idéologies d'une zone": "Quelles idéologies pèsent dans la zone choisie, d'une législative à l'autre.",
    "Échiquier politique": "Les partis placés de gauche à droite et du souverainisme à l'europhilie, d'après leurs idéologies.",
}

# =============================================================================================
# La barre latérale : les questions, rangées par thème. Une question = (la question, le chemin qui y répond).
#   onglet, vue      la pastille à ouvrir
#   scrutin          l'élection à choisir (sinon on garde celle du menu) ; zone : "france" pour revenir à la France
#   options          les réglages de la vue ; top : le classement à afficher (n, niveau, ordre, mesure, qui)
#   aide             ce qu'il reste à choisir soi-même (les « trous » de la question), affiché dans la barre d'état
# =============================================================================================
def Q(question, onglet, vue, aide="", scrutin=None, zone=None, options=None, top=None):
    return {"question": question, "onglet": onglet, "vue": vue, "aide": aide, "scrutin": scrutin, "zone": zone,
            "options": options or {}, "top": top}


MENU = {
    "Résultats": ("🗳", [
        Q("Qui est arrivé en tête dans ma commune ?", "Candidat", "Résultats", "Choisis l'élection et ta commune en haut."),
        Q("Ma commune vote-t-elle comme la France ?", "Candidat", "Zone / France", "Choisis ta commune en haut."),
        Q("La carte d'une élection", "Carte", "Résultats sur la carte", "Choisis l'élection en haut (ex. Présidentielle 2002)."),
        Q("Où un candidat fait-il ses meilleurs scores ?", "Candidat", "Résultats", "Puis « Top » : mesure Score, choisis le candidat.",
          top={"n": 25, "niveau": "departement", "ordre": "Les plus hauts", "mesure": "Score"}),
        Q("Là où l'un est fort, l'autre est-il faible ?", "Candidat", "Duel", "Choisis les deux candidats à droite."),
        Q("Le 1er tour annonce-t-il le 2nd ?", "Nuages", "1er → 2nd tour", "Change les axes avec « Réglages du nuage »."),
    ]),
    "Participation": ("📊", [
        Q("Où s'abstient-on le plus ?", "Participation", "Taux par bureau", "Le classement s'affiche avec « Top ».",
          top={"n": 25, "niveau": "departement", "ordre": "Les plus hauts", "mesure": "Abstention"}),
        Q("Ma commune s'abstient-elle plus que le département ?", "Participation", "Zone et ses niveaux", "Choisis ta commune en haut."),
        Q("L'abstention dépend-elle du type d'élection ?", "Dans le temps", "Type ou année ?"),
        Q("Les abstentionnistes d'hier le sont-ils encore ?", "Nuages", "Abstention hier / auj."),
        Q("Le vote blanc remplace-t-il l'abstention ?", "Nuages", "Blanc ou abstention"),
        Q("Les communes modestes votent-elles moins ?", "Nuages", "Revenu → abstention"),
    ]),
    "Dans le temps": ("🕰", [
        Q("Y a-t-il des fiefs ? Qui arrive en tête, élection après élection", "Dans le temps", "Qui arrive en tête",
          "Choisis une commune, un département… en haut.", zone=None),
        Q("Quels départements ont changé de camp en 2021 ?", "Dans le temps", "Bascules départementales"),
        Q("Comment a évolué l'abstention dans ma commune ?", "Dans le temps", "Évolution", "Choisis ta commune en haut."),
        Q("Le score d'un nom à chaque élection", "Dans le temps", "Suivre un nom", "Tape le nom à droite (ex. LE PEN)."),
        Q("Deux communes ont-elles évolué pareil ?", "Comparer", "Deux zones dans le temps", "Ajoute deux zones à droite."),
        Q("Qui a gardé ses électeurs entre 2017 et 2022 ?", "Nuages", "Électeurs gardés ?"),
    ]),
    "Territoires": ("🗺", [
        Q("Le revenu explique-t-il le vote ?", "Nuages", "Revenu → vote"),
        Q("Le chômage local fait-il baisser la participation ?", "Économie", "Chômage local → abstention"),
        Q("L'inflation éloigne-t-elle des urnes ?", "Économie", "Inflation → abstention"),
        Q("Les gros bureaux votent-ils autrement ?", "Nuages", "Gros bureaux"),
        Q("Comparer deux zones", "Comparer", "Deux zones", "Ajoute deux zones à droite."),
    ]),
    "Élus et conseils": ("🏛", [
        Q("Qui siège aujourd'hui dans ma commune, mon département, ma région ?", "Sièges", "Qui siège aujourd'hui",
          "Choisis la commune, le département ou la région en haut."),
        Q("Qui a été élu à cette élection ? (conseil municipal, régional…)", "Sièges", "Élus et listes",
          "Choisis l'élection (ex. Municipales 2020) et la zone en haut."),
        Q("Combien de sièges pour chaque liste ?", "Sièges", "Hémicycle", "Choisis l'élection et la zone en haut."),
        Q("Les maires : femmes, âge, réélection", "Sièges", "Portrait des maires"),
        Q("Qui cumule des mandats aujourd'hui ?", "Personnes", "Cumuls aujourd'hui"),
        Q("Les présidents de la République", "Personnes", "Présidents"),
    ]),
    "Parlement et votes": ("⚖", [
        Q("L'Assemblée aujourd'hui", "Sièges", "Assemblée actuelle", "Choisis un département en haut : ses députés sont entourés."),
        Q("Le Sénat aujourd'hui", "Sièges", "Sénat actuel"),
        Q("L'Assemblée d'une législature (depuis 1958)", "Sièges", "Législature", "Choisis la législature à droite."),
        Q("Comment mon député a-t-il voté ?", "Votes", "Qui a voté quoi", "Choisis le vote, puis tape le nom à droite."),
        Q("Comment chaque groupe a-t-il voté ?", "Votes", "Vote des groupes", "Choisis le vote à droite."),
        Q("Les photos des députés et sénateurs", "Sièges", "Trombinoscope"),
    ]),
    "Personnes": ("👤", [
        Q("Le parcours d'une personne (mandats, ministères, écoles)", "Personnes", "Fiche d'une personne", "Tape un nom à droite."),
        Q("Qui était dans tel gouvernement ?", "Personnes", "Un gouvernement", "Choisis le gouvernement à droite."),
        Q("Combien d'énarques sont devenus ministres ?", "Personnes", "Écoles et pouvoir", "Choisis une autre école à droite.",
          options={"ecole": "École nationale d'administration"}),
        Q("Qui était préfet de mon département ?", "Personnes", "Préfets du département", "Choisis le département en haut."),
        Q("Où sont les partis sur l'échiquier politique ?", "Personnes", "Échiquier politique", "Tape un nom à droite pour son trajet."),
        Q("Quelles idéologies pèsent dans ma zone ?", "Personnes", "Idéologies d'une zone", "Choisis la zone en haut."),
        Q("Candidats : âge, métiers", "Candidat", "Profils des candidats", "Choisis l'élection et la zone en haut."),
        Q("Les affiches de campagne", "Affiches", "Affiches de campagne"),
    ]),
}
# Le thème de chaque référendum, affiché à côté de l'année dans le volet Scrutin (un seul tour, réponses OUI / NON)
THEMES_REFERENDUMS = {1793: "Constitution de l'an I", 1795: "Constitution de l'an III",
                      1946: "1er projet de constitution (rejeté)", 1992: "Maastricht", 2000: "Quinquennat", 2005: "Constitution européenne"}
