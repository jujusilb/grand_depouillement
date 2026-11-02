"""
autotest.py — Mode test : chaque vue est affichée puis photographiée (GD_TEST = dossier des captures), puis l'appli se ferme.

    set GD_TEST=C:\\temp\\captures
    py lancer.py
"""

import ctypes
import traceback
from ctypes import wintypes
from pathlib import Path

from PIL import Image

from lecture import donnees as d


def photo(app, dossier, nom):
    """Photographie la FENÊTRE elle-même (PrintWindow), même si l'écran est agrandi par la loupe ou couvert."""
    app.update()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = int(app.wm_frame(), 16)
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    l, h = r.right - r.left, r.bottom - r.top
    dc_fen = user32.GetWindowDC(hwnd)
    dc = gdi32.CreateCompatibleDC(dc_fen)
    bmp = gdi32.CreateCompatibleBitmap(dc_fen, l, h)
    gdi32.SelectObject(dc, bmp)
    user32.PrintWindow(hwnd, dc, 2)                      # 2 = tout le contenu, même accéléré
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), l, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    tampon = ctypes.create_string_buffer(l * h * 4)
    gdi32.GetDIBits(dc, bmp, 0, h, tampon, ctypes.byref(bi), 0)
    Image.frombuffer("RGB", (l, h), tampon, "raw", "BGRX", 0, 1).save(Path(dossier) / f"{nom}.png")
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(dc); user32.ReleaseDC(hwnd, dc_fen)


def autotest(app, dossier):
    Path(dossier).mkdir(parents=True, exist_ok=True)
    rapport = []
    try:
        from interface.catalogue import VUES
        from graphiques import graphiques as g_
        # une zone : Haute-Loire, pour que les vues locales aient du sens
        app.cascade["region"].set("Auvergne-Rhône-Alpes"); app.maj_cascade("region", utilisateur=False)
        nom = next(n for n in app.codes_zone["departement"] if n.startswith("Haute-Loire"))
        app.cascade["departement"].set(nom); app.maj_cascade("departement", utilisateur=True)
        for onglet, vues in VUES.items():
            for i, v in enumerate(vues):
                app.choisir_vue(onglet, i)
                photo(app, dossier, f"{list(VUES).index(onglet)}{i:02d}_{onglet}_{v[0]}".replace(" ", "_").replace("/", "-").replace("?", "").replace("📈", ""))
                lecture = app.etat.get()[:90]
                # l'export texte / CSV de la vue (accessibilité) : combien de lignes de données ?
                from interface import export
                export.DOSSIER = Path(dossier) / "exports"
                tableaux = list(g_.DONNEES) or export.depuis_figure(app.fig)
                app.exporter("texte"); app.exporter("csv")
                lignes = sum(len(t) for _, t in tableaux)
                rapport.append(f"{onglet} | {v[0]} | {lecture} | export : {lignes} lignes{' (relues dans le graphique)' if not g_.DONNEES else ''}")
        # les volets ouverts
        app.choisir_vue("Candidat", 0)
        for cle in ("scrutin", "zone"):
            app.basculer(cle)
        photo(app, dossier, "volets_ouverts")
        for cle in ("scrutin", "zone"):
            app.basculer(cle)
        app.basculer("top")
        photo(app, dossier, "volet_top")
        app.afficher_top()
        photo(app, dossier, "top_affiche")
        # un Top 100 : dessiné en grand, avec l'ascenseur
        app.top_n.set("Top 100"); app.top_niveau.set("Communes"); app.afficher_top()
        photo(app, dossier, "top_100")
        app.defile.yview_moveto(0.5); app.update()
        photo(app, dossier, "top_100_milieu")
        app.top_n.set("Top 25")
        app.choisir_vue("Nuages", 0)
        app.basculer("nuage")
        photo(app, dossier, "volet_nuage")
        app.basculer("nuage")
        # économie : la courbe seule, puis un clic (simulé) sur la pastille de la présidentielle 2022
        app.choisir_vue("Économie", 0)
        photo(app, dossier, "economie_suivi")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "scrutins_points"))
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [coll.scrutins_points.index("2022_pres_t1")]})())
        photo(app, dossier, "economie_clic_scrutin")
        # sièges : l'Assemblée nationale de 2024, puis le conseil départemental de Haute-Loire 2021
        app.cb_type.set("Législatives"); app.cb_annee.set("2024"); app.maj_regles_scrutin()
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_assemblee_2024")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "sieges_occupants"))
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [10]})())
        rapport.append(f"siège cliqué | {app.etat.get()[:90]}")
        app.choisir_vue("Sièges", next(i for i, v in enumerate(VUES["Sièges"]) if v[0] == "Assemblée actuelle"))
        photo(app, dossier, "sieges_assemblee_actuelle")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "parlementaires"))
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [100]})())
        photo(app, dossier, "sieges_assemblee_actuelle_clic")
        app.cb_type.set("Départementales"); app.cb_annee.set("2021"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("departement", "43", "Haute-Loire"))
        app.choisir_vue("Sièges", 1)
        photo(app, dossier, "sieges_elus_cd43")
        app.cb_type.set("Présidentielle"); app.cb_annee.set("2022"); app.maj_regles_scrutin()
        # comparer deux zones : un bureau et une commune
        app.ajouter_comparaison(d.Zone("bureau", "43157_0102", "Le Puy – bureau 0102"))
        app.ajouter_comparaison(d.Zone("commune", "43040", "Brioude"))
        photo(app, dossier, "comparer_deux_zones")
        app.choisir_vue("Comparer", 1)
        photo(app, dossier, "comparer_dans_le_temps")
        # municipales 2026 au Puy : les listes
        app.cb_type.set("Municipales"); app.cb_annee.set("2026"); app.maj_regles_scrutin()
        com = next(n for n in app.codes_zone["commune"] if n.startswith("Le Puy-En-Velay"))
        app.cascade["commune"].set(com); app.maj_cascade("commune", utilisateur=True)
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "municipales_puy_listes")
        # les sièges figés : le conseil municipal du Puy (2026), une petite commune de 2020 (candidats un par un), l'Île-de-France 2021
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_conseil_municipal_puy_2026")
        # Paris : le Conseil de Paris 2026 (toute la ville, prime de 25 %), puis le secteur du 17e en 2020
        app.choisir_zone(d.Zone("departement", "75", "Paris"))
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_conseil_de_paris_2026")
        app.cb_annee.set("2020"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("arrmun", "75117", "Paris 17e Arrondissement"))
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_paris_17e_2020")
        app.cb_annee.set("2020"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("commune", "43001", "Agnat"))
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_petite_commune_2020")
        app.cb_type.set("Régionales"); app.cb_annee.set("2021"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("region", "11", "Île-de-France"))
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_conseil_regional_idf_2021")
        # 2014 et 2008 : la taille légale du conseil (population Insee) ; Clermont-Ferrand 2014, Le Puy 2008
        app.cb_type.set("Municipales"); app.cb_annee.set("2014"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("commune", "63113", "Clermont-Ferrand"))
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_conseil_municipal_clermont_2014")
        app.cb_annee.set("2008"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("commune", "43157", "Le Puy-en-Velay"))
        app.choisir_vue("Sièges", 0)
        photo(app, dossier, "sieges_conseil_municipal_puy_2008")
        # les conseils en place (RNE) : l'agglo du Puy et Paris en 2026, Le Puy en 2014 (par fonction), un clic sur un siège
        en_place = next(i for i, v in enumerate(VUES["Sièges"]) if v[0] == "Conseil en place")
        app.cb_annee.set("2014"); app.maj_regles_scrutin()
        app.choisir_vue("Sièges", en_place)
        photo(app, dossier, "en_place_puy_2014")
        app.cb_annee.set("2026"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("epci", "200073419", "CA du Puy-en-Velay"))
        app.choisir_vue("Sièges", en_place)
        photo(app, dossier, "en_place_agglo_puy_2026")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "sieges_occupants"))
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [3]})())
        rapport.append(f"élu en place cliqué | {app.etat.get()[:90]}")
        photo(app, dossier, "en_place_agglo_puy_2026_clic")
        app.choisir_zone(d.Zone("commune", "75056", "Paris"))
        app.choisir_vue("Sièges", en_place)
        photo(app, dossier, "en_place_paris_2026")
        app.cb_annee.set("2020"); app.maj_regles_scrutin()
        app.choisir_zone(d.Zone("commune", "13055", "Marseille"))
        app.choisir_vue("Sièges", en_place)
        photo(app, dossier, "en_place_marseille_2020")
        app.cb_annee.set("2026"); app.maj_regles_scrutin()
        app.cascade["commune"].set(com); app.maj_cascade("commune", utilisateur=True)
        # municipales 2020 au Puy, carte en échelle automatique : les bureaux de la commune, puis un clic sur un bureau
        app.cb_annee.set("2020"); app.maj_regles_scrutin()
        app.choisir_vue("Carte", 0)
        photo(app, dossier, "carte_puy_bureaux")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "codes_zones"))
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [0]})())
        photo(app, dossier, "carte_puy_clic_bureau")
        # la carte en communes, puis un clic (simulé) sur une commune : la fiche « Zone cliquée »
        app.cb_type.set("Présidentielle"); app.cb_annee.set("2022"); app.maj_regles_scrutin()
        app.options["echelle"] = "Communes"
        app.choisir_vue("Carte", 0)
        photo(app, dossier, "carte_communes")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "codes_zones"))
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [coll.codes_zones.index("43157") if "43157" in coll.codes_zones else 0]})())
        photo(app, dossier, "carte_clic")
        # les photos des candidats (panneau de droite), France entière
        app.choisir_zone(d.FRANCE)
        app.options["echelle"] = "Automatique (selon la zone)"
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "photos_candidats_2022")
        app.choisir_vue("Candidat", 2)
        photo(app, dossier, "photos_duel_2022")
        # avant 2002 (Cagé-Piketty, par commune) : 1995, le Front populaire, novembre 1946, 1793 sur la carte
        app.cb_type.set("Présidentielle"); app.cb_annee.set("1995"); app.cb_tour.set("2nd tour"); app.maj_regles_scrutin()
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "historique_pres_1995_t2")
        app.cb_type.set("Législatives"); app.cb_annee.set("1936"); app.maj_regles_scrutin()
        app.choisir_vue("Carte", 0)
        photo(app, dossier, "historique_carte_1936")
        app.cb_annee.set("1946 · novembre"); app.maj_regles_scrutin()
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "historique_legi_1946_novembre")
        app.cb_type.set("Référendum"); app.cb_annee.set("1793 · Constitution de l'an I"); app.maj_regles_scrutin()
        app.choisir_vue("Carte", 0)
        photo(app, dossier, "historique_carte_1793")
        app.choisir_vue("Dans le temps", 0)
        photo(app, dossier, "historique_evolution")
        rapport.append(f"historique | {app.ctx.scrutin} | {app.etat.get()[:90]}")
        app.cb_type.set("Présidentielle"); app.cb_annee.set("2022"); app.cb_tour.set("1er tour"); app.maj_regles_scrutin()
        # les votes des députés : la censure Barnier, un député cherché, un clic sur un siège ; 1981 (résultat seul) ; une recherche
        app.options["vote"] = "AN17-00519"; app.options["depute"] = "Le Pen"
        app.choisir_vue("Votes", 0)
        photo(app, dossier, "votes_hemicycle_barnier")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "votants"))
        from politique import legislatures
        t = legislatures.votes_complets("AN17-00519")
        panot = coll.votants[1].index(t.index[t["depute"] == "Mathilde Panot"][0]) if (t["depute"] == "Mathilde Panot").any() else 0
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [panot]})())
        photo(app, dossier, "votes_clic_depute")
        app.options["vote"] = "AN14-00998"; app.options["depute"] = ""
        app.choisir_vue("Votes", 0)
        photo(app, dossier, "votes_hemicycle_irak")
        # un absent (petite pastille) cliqué au vote du mariage pour tous
        app.options["vote"] = "AN14-00511"
        app.choisir_vue("Votes", 0)
        photo(app, dossier, "votes_hemicycle_mariage_absents")
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "votants"))
        t = legislatures.votes_complets("AN14-00511")
        absent = coll.votants[1].index(t.index[t["position"] == "absent"][0])
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [absent]})())
        photo(app, dossier, "votes_clic_absent")
        rapport.append(f"absent cliqué | {t.loc[t.index[t['position'] == 'absent'][0], 'depute']}")
        # les législatures : la XVIIe (tous connus), la XIe (CDSP, nommés), la Ire (courant seulement), et un clic
        vue_leg = next(i for i, v in enumerate(VUES["Sièges"]) if v[0] == "Législature")
        for lib in [l_ for l_ in legislatures.libelles() if l_.startswith(("Législature XVII ", "Législature XI ", "Législature VIII ", "Législature I "))]:
            app.options["legislature"] = lib
            app.choisir_vue("Sièges", vue_leg)
            photo(app, dossier, "legislature_" + lib.split()[1])
        app.options["legislature"] = legislatures.libelles()[0]
        app.choisir_vue("Sièges", vue_leg)
        coll = next(c for ax in app.fig.axes for c in ax.collections if hasattr(c, "sieges_occupants"))
        app.clic_carte(type("Clic", (), {"artist": coll, "ind": [200]})())
        photo(app, dossier, "legislature_clic")
        rapport.append(f"législature, siège cliqué | {app.etat.get()[:90]}")
        app.options["vote"] = "AN14-00511"
        app.choisir_vue("Votes", 1)
        photo(app, dossier, "votes_groupes_mariage")
        app.options["depute"] = "Chirac"; app.options["vote"] = "AN11-00093"
        app.choisir_vue("Votes", 2)
        photo(app, dossier, "votes_liste_35h_chirac")
        app.options["vote"] = "JO1981-peine-de-mort"; app.options["depute"] = "Chirac"; app.options["recherche_vote"] = "état d'urgence"
        app.choisir_vue("Votes", 0)
        photo(app, dossier, "votes_1981_et_recherche")
        rapport.append(f"votes | {app.etat.get()[:90]}")
        app.options["recherche_vote"] = ""
        # les affiches des Hauts-de-Seine : tout le département, puis Issy-les-Moulineaux, un clic sur une affiche, une recherche
        app.choisir_zone(d.Zone("departement", "92", "Hauts-de-Seine"))
        app.choisir_vue("Affiches", 0)
        photo(app, dossier, "affiches_92")
        app.choisir_zone(d.Zone("commune", "92040", "Issy-les-Moulineaux"))
        app.choisir_vue("Affiches", 0)
        photo(app, dossier, "affiches_issy")
        coll = next((im for ax in app.fig.axes for im in ax.images if hasattr(im, "affiches")), None)
        if coll is not None:
            app.clic_carte(type("Clic", (), {"artist": coll, "mouseevent": type("M", (), {"xdata": 30, "ydata": 30})()})())
            photo(app, dossier, "affiches_clic")
        app.choisir_zone(d.Zone("departement", "92", "Hauts-de-Seine"))
        app.options["affiche_cherche"] = "SARKOZY"
        app.choisir_vue("Affiches", 0)
        photo(app, dossier, "affiches_sarkozy")
        rapport.append(f"affiches | {app.etat.get()[:90]}")
        app.options["affiche_cherche"] = ""
        app.cb_type.set("Présidentielle"); app.cb_annee.set("1969"); app.cb_tour.set("1er tour"); app.maj_regles_scrutin()
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "affiches_candidats_1969")
        # les fiches des candidats (âge, profession) : législatives 2024 dans l'Ain ; puis les scrutins anciens du CDSP
        app.choisir_zone(d.Zone("departement", "01", "Ain"))
        app.cb_type.set("Législatives"); app.cb_annee.set("2024"); app.cb_tour.set("1er tour"); app.maj_regles_scrutin()
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "candidats_qui_sont_ils")
        app.choisir_vue("Candidat", next(i for i, v in enumerate(VUES["Candidat"]) if v[0] == "Profils des candidats"))
        photo(app, dossier, "candidats_profils_ain_2024")
        app.choisir_zone(d.FRANCE)
        app.cb_type.set("Cantonales"); app.cb_annee.set("1988"); app.cb_tour.set("1er tour"); app.maj_regles_scrutin()
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "cdsp_cantonales_1988")
        app.cb_type.set("Législatives"); app.cb_annee.set("1981"); app.cb_tour.set("2nd tour"); app.maj_regles_scrutin()
        app.choisir_vue("Candidat", 0)
        photo(app, dossier, "cdsp_legislatives_1981_t2")
        app.cb_type.set("Régionales"); app.cb_annee.set("1986"); app.maj_regles_scrutin()
        app.choisir_vue("Dans le temps", 0)
        photo(app, dossier, "cdsp_evolution")
        rapport.append(f"cdsp | {app.ctx.scrutin} | {app.etat.get()[:80]}")
        app.cb_type.set("Présidentielle"); app.cb_annee.set("2022"); app.cb_tour.set("1er tour"); app.maj_regles_scrutin()
        app.choisir_vue("Affiches", 1)
        photo(app, dossier, "affiches_par_annee")
        app.choisir_zone(d.FRANCE)
        # accessibilité : les textes agrandis (A+ A+ A+ = 150 %), puis retour à 100 %
        app.choisir_vue("Candidat", 0)
        for _ in range(3):
            app.zoom(+1)
        photo(app, dossier, "zoom_150_candidat")
        app.choisir_vue("Votes", 0)
        photo(app, dossier, "zoom_150_votes")
        app.zoom(0)
        app.changer_moteur("matplotlib")
        app.choisir_vue("Participation", 0)
        photo(app, dossier, "moteur_matplotlib")
        app.changer_moteur("seaborn")
        # la barre latérale : des questions cliquées, une personne cherchée, la barre repliée puis filtrée
        from interface.catalogue import MENU
        question = lambda texte: next(q for _, (_, qs) in MENU.items() for q in qs if q["question"].startswith(texte))
        app.choisir_zone(d.Zone("region", "84", "Auvergne-Rhône-Alpes"))
        app.aller_question(question("Qui siège aujourd'hui"))
        photo(app, dossier, "barre_qui_siege_aura")
        rapport.append(f"barre | qui siège | {app.etat.get()[:100]}")
        app.aller_question(question("Le parcours d'une personne"))
        app.options["recherche_personne"] = "Ségolène Royal"; app.options.pop("personne", None)
        app.tracer(); app.update(); app.after(50); app.update()
        photo(app, dossier, "barre_fiche_royal")
        rapport.append(f"barre | fiche | {app.etat.get()[:100]}")
        app.aller_question(question("Qui était dans tel gouvernement"))
        photo(app, dossier, "barre_gouvernement")
        app.choisir_zone(d.Zone("departement", "45", "Loiret"))
        app.aller_question(question("Qui était préfet"))
        photo(app, dossier, "barre_prefets_loiret")
        app.aller_question(question("Combien d'énarques"))
        photo(app, dossier, "barre_ecoles")
        app.choisir_zone(d.Zone("departement", "43", "Haute-Loire"))
        app.aller_question(question("Y a-t-il des fiefs"))
        photo(app, dossier, "barre_fiefs_haute_loire")
        app.aller_question(question("Quels départements ont changé"))
        photo(app, dossier, "barre_bascules")
        app.aller_question(question("Où s'abstient-on"))
        photo(app, dossier, "barre_top_abstention")
        app.filtre_questions.insert(0, "maire"); app.filtrer_questions()
        photo(app, dossier, "barre_filtre_maire")
        app.replier_barre(); app.update()
        photo(app, dossier, "barre_repliee")
        app.replier_barre()
    except Exception:
        rapport.append("ERREUR\n" + traceback.format_exc())
    (Path(dossier) / "rapport.txt").write_text("\n".join(rapport), encoding="utf-8")
    app.destroy()
