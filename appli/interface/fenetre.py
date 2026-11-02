"""
fenetre.py — La fenêtre du Grand Dépouillement (tkinter), d'après la maquette de l'atelier.

    +---------------------------------------------------------------------------------------------+
    | ◆ Le Grand Dépouillement  (🗳 Scrutin ▾) (📍 Zone ▾)                  graphiques : seaborn |  barre bleue
    |   [volets Scrutin / Zone : ils se déroulent PAR-DESSUS la page, un 2e clic les replie]          |
    | Participation  Candidat  Dans le temps  Carte  Nuages  Économie            (🏆 Top ▾)       |  onglets
    | (pastille) (pastille) (pastille) …                                                          |  vues
    | +-------------------------------------------------------------+  +------------------------+ |
    | |                    GRAPHIQUE (matplotlib / seaborn)          |  |  fiche « couteau      | |
    | |  [barre d'outils : zoom, enregistrer…]                       |  |  suisse » de la vue   | |
    | +-------------------------------------------------------------+  +------------------------+ |
    | barre d'état : comment lire le graphique                                                    |
    +---------------------------------------------------------------------------------------------+
"""

import os
import webbrowser
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure
from PIL import Image, ImageTk

from lecture import donnees as d
from graphiques import graphiques as g
from lecture import adresse, affiches, photos
from politique import candidats, legislatures, parlement, sieges
from interface import export, theme
from politique import votes as votes_deputes
from politique import personnes
from interface.catalogue import DESCRIPTIONS, MENU, NOMS_FORMES, QUESTIONS, THEMES_REFERENDUMS, VUES
from interface.theme import C

@dataclass
class Contexte:
    scrutin: str = "2022_pres_t1"
    zone: d.Zone = d.FRANCE
    regroupement: str = "Candidat / liste"
    forme: str = None
    options: dict = field(default_factory=dict)
    top: dict = None
    nuage: dict = None
    comparaison: list = field(default_factory=list)     # les deux zones de l'onglet Comparer


# =============================================================================================
# Petits composants
# =============================================================================================

class Pilule(tk.Label):
    """Un bouton arrondi… version tkinter : un Label avec un liseré, qui change d'aspect quand son volet est ouvert."""

    def __init__(self, parent, commande, fond, texte_couleur):
        super().__init__(parent, bg=fond, fg=texte_couleur, font=theme.POLICE, padx=14, pady=5, cursor="hand2",
                         highlightthickness=1, highlightbackground=texte_couleur, anchor="w")
        self.fond, self.couleur = fond, texte_couleur
        theme.cliquable(self, commande)

    def etat(self, texte, ouvert):
        self.configure(text=f"{texte}   {'▴' if ouvert else '▾'}", font=theme.POLICE_GRAS if ouvert else theme.POLICE,
                       bg=C["sur"] if ouvert and self.fond == C["primaire"] else self.fond,
                       fg=C["primaire"] if ouvert and self.fond == C["primaire"] else self.couleur)


class Volet(tk.Frame):
    """Un volet qui se déroule PAR-DESSUS la page (place) et se replie (place_forget)."""

    def __init__(self, racine):
        super().__init__(racine, bg=C["pale"], highlightthickness=1, highlightbackground=C["bordure"])
        self.ouvert = False

    def champ(self, parent, libelle, largeur, valeurs=(), commande=None, etat="readonly"):
        f = tk.Frame(parent, bg=C["pale"])
        ttk.Label(f, text=libelle.upper(), style="Libelle.TLabel").pack(anchor="w")
        cb = ttk.Combobox(f, values=list(valeurs), width=largeur, state=etat, height=25)
        cb.configure(postcommand=lambda: elargir_liste(cb))
        cb.pack(anchor="w")
        if commande:
            cb.bind("<<ComboboxSelected>>", lambda e: commande())
        return f, cb


def elargir_liste(cb):
    """La liste déroulante s'élargit jusqu'au nom le plus long (sinon ttk la coupe à la largeur du champ)."""
    valeurs = cb.cget("values")
    if not valeurs:
        return
    police = tkfont.nametofont("TkDefaultFont")
    besoin = max(police.measure(str(v)) for v in valeurs) + 40     # + la marge et l'ascenseur
    style = f"Large{cb.winfo_id()}.TCombobox"
    ttk.Style().configure(style, postoffset=(0, 0, max(0, besoin - cb.winfo_width()), 0))
    cb.configure(style=style)


class Defilant(tk.Frame):
    """Un cadre qu'on peut faire défiler (pour la fiche de droite)."""

    def __init__(self, parent, largeur):
        super().__init__(parent, bg=C["carte"])
        self.canvas = tk.Canvas(self, bg=C["carte"], highlightthickness=0, width=largeur)
        barre = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interieur = tk.Frame(self.canvas, bg=C["carte"])
        self.interieur.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.interieur, anchor="nw", width=largeur)
        self.canvas.configure(yscrollcommand=barre.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        barre.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._roue))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _roue(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")


# =============================================================================================
# La fenêtre
# =============================================================================================

class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(theme.NOM_APPLI)
        self.geometry("1440x900")
        self.minsize(1200, 760)
        theme.appliquer(self)
        self.ctx = Contexte()
        self.onglet, self.vue_i = "Candidat", 0
        self.top_actif = False
        self.formes = {}              # forme choisie pour chaque vue
        self.comparaison = []
        self.options = {"indicateur": "Abstention", "tranches": 60, "echelle": "Automatique (selon la zone)", "fond": "Automatique", "texte": "LE PEN"}

        self.creer_bandeau()
        self.creer_etat()
        self.creer_barre_laterale()
        self.creer_onglets()
        self.creer_corps()
        self.creer_volets()
        self.bind("<Configure>", lambda e: self.placer_volets() if e.widget is self else None)
        self.after(50, self.choisir_vue, "Candidat", 0)

    # ------------------------------------------------------------------ barre bleue
    def creer_bandeau(self):
        b = tk.Frame(self, bg=C["primaire"], height=int(56 * max(1.0, theme.ZOOM)))
        b.pack(side="top", fill="x")
        b.pack_propagate(False)
        self.bandeau = b
        tk.Label(b, text="◆  " + theme.NOM_APPLI, bg=C["primaire"], fg=C["sur"], font=theme.POLICE_LOGO).pack(side="left", padx=(16, 24))
        for touches, pas in (("<Control-plus>", 1), ("<Control-equal>", 1), ("<Control-KP_Add>", 1),
                             ("<Control-minus>", -1), ("<Control-KP_Subtract>", -1), ("<Control-0>", 0)):
            self.bind_all(touches, lambda e, p_=pas: self.zoom(p_))
        self.bind_all("<Control-e>", lambda e: self.exporter("texte"))
        self.bind_all("<Control-E>", lambda e: self.exporter("csv"))          # (Ctrl + Maj + E)
        # les deux pilules prennent la place qui reste (créées APRÈS les boutons de droite : ceux-ci ne sont jamais poussés dehors)
        self.pilules = {}
        for cle, poids in [("scrutin", 40), ("zone", 34)]:
            p = Pilule(b, lambda c=cle: self.basculer(c), C["primaire"], C["sur"])
            p.configure(width=max(12, int(poids / theme.ZOOM)))
            p.pack(side="left", padx=5, pady=8, fill="x", expand=True)
            self.pilules[cle] = p
        # le Top (ou les réglages du nuage) : le 3e réglage toujours visible, à côté de l'élection et de la zone
        # (il était au bout des onglets : avec la barre latérale, il cachait les derniers)
        self.pilule_top = Pilule(b, lambda: self.basculer("top"), C["primaire"], C["sur"])
        self.pilule_top.configure(width=max(18, int(30 / theme.ZOOM)))
        self.pilule_top.pack(side="left", padx=(5, 12), pady=8, fill="x", expand=True)

    def zoom(self, pas):
        """Agrandit (+1) ou réduit (−1) tous les textes, ou revient à la taille normale (0)."""
        if pas == 0:
            f = 1.0
        else:
            i = min(range(len(theme.ZOOMS)), key=lambda k: abs(theme.ZOOMS[k] - theme.ZOOM))
            f = theme.ZOOMS[max(0, min(len(theme.ZOOMS) - 1, i + pas))]
        theme.zoomer(f)
        self.bandeau.configure(height=int(56 * max(1.0, f)))
        for cle, poids in [("scrutin", 40), ("zone", 34)]:
            self.pilules[cle].configure(width=max(12, int(poids / f)))
        self.pilule_top.configure(width=max(18, int(30 / f)))
        self.placer_volets()
        self.etat.set(f"Taille du texte : {round(f * 100)} %  (Ctrl + / Ctrl − / Ctrl 0)")
        self.tracer()

    def changer_moteur(self, nom, tracer=True):
        g.MOTEUR = nom
        for n, l in self.boutons_moteur.items():
            l.configure(bg=C["primaire"] if n == nom else C["carte"], fg=C["sur"] if n == nom else C["primaire"])
        if tracer:
            self.tracer()

    # ------------------------------------------------------------------ la barre latérale : les questions
    LARGEUR_BARRE = 270

    def creer_barre_laterale(self):
        """À gauche, toute la hauteur : les questions rangées par thème (catalogue.MENU). Une question ouvre la bonne vue,
        déjà réglée ; il ne reste à choisir que ses « trous » (la commune, l'élection, le nom), dits dans la barre d'état.
        Un champ filtre les questions ; « ‹ » replie la barre en une colonne d'icônes."""
        self.barre = tk.Frame(self, bg=C["pale"], highlightthickness=1, highlightbackground=C["bordure"])
        self.barre.pack(side="left", fill="y")
        self.barre_ouverte, self.question_active, self.themes_ouverts = True, None, set(MENU)
        self.dessiner_barre()

    def dessiner_barre(self):
        for w in self.barre.winfo_children():
            w.destroy()
        haut = tk.Frame(self.barre, bg=C["pale"])
        haut.pack(fill="x", padx=8, pady=(8, 4))
        bouton = tk.Label(haut, text="‹" if self.barre_ouverte else "›", bg=C["pale"], fg=C["primaire"], font=theme.POLICE_TITRE,
                          padx=6, cursor="hand2")
        bouton.pack(side="right" if self.barre_ouverte else "top")
        theme.cliquable(bouton, self.replier_barre)
        if not self.barre_ouverte:     # repliée : une icône par thème, qui rouvre la barre sur ce thème
            for nom, (icone, _) in MENU.items():
                l = tk.Label(self.barre, text=icone, bg=C["pale"], fg=C["primaire"], font=theme.POLICE_TITRE, pady=6, cursor="hand2")
                l.pack()
                theme.cliquable(l, lambda n=nom: self.ouvrir_theme(n))
            return
        ttk.Label(haut, text="QUESTIONS", style="Libelle.TLabel").pack(side="left")
        self.filtre_questions = ttk.Entry(self.barre)
        self.filtre_questions.pack(fill="x", padx=10, pady=(0, 2))
        self.filtre_questions.insert(0, getattr(self, "texte_filtre", ""))
        self.filtre_questions.bind("<KeyRelease>", lambda e: self.filtrer_questions())
        ttk.Label(self.barre, text="Tape un mot : maire, préfet, abstention…", style="Gris.TLabel", background=C["pale"],
                  wraplength=self.LARGEUR_BARRE - 30).pack(anchor="w", padx=10, pady=(0, 6))
        self.liste_questions = Defilant(self.barre, self.LARGEUR_BARRE)
        self.liste_questions.configure(bg=C["pale"])
        self.liste_questions.canvas.configure(bg=C["pale"])
        self.liste_questions.interieur.configure(bg=C["pale"])
        self.liste_questions.pack(fill="both", expand=True)
        self.remplir_questions()

    def remplir_questions(self):
        f = self.liste_questions.interieur
        for w in f.winfo_children():
            w.destroy()
        cherche = d.normaliser(getattr(self, "texte_filtre", ""))
        for nom, (icone, questions) in MENU.items():
            garde = [q for q in questions if not cherche or cherche in d.normaliser(q["question"] + " " + nom)]
            if not garde:
                continue
            ouvert = nom in self.themes_ouverts or bool(cherche)
            t = tk.Label(f, text=f"{icone}  {nom}   {'▾' if ouvert else '▸'}", bg=C["pale"], fg=C["primaire"], font=theme.POLICE_GRAS,
                         anchor="w", padx=8, pady=5, cursor="hand2")
            t.pack(fill="x", pady=(6, 0))
            theme.cliquable(t, lambda n=nom: self.basculer_theme(n))
            if not ouvert:
                continue
            for q in garde:
                actif = q is self.question_active
                l = tk.Label(f, text=q["question"], bg=C["primaire"] if actif else C["pale"], fg=C["sur"] if actif else C["texte"],
                             font=theme.POLICE_PETITE, anchor="w", justify="left", wraplength=self.LARGEUR_BARRE - 40,
                             padx=8, pady=4, cursor="hand2")
                l.pack(fill="x", padx=(16, 4), pady=1)
                theme.cliquable(l, lambda q_=q: self.aller_question(q_))

    def filtrer_questions(self):
        self.texte_filtre = self.filtre_questions.get()
        self.remplir_questions()

    def basculer_theme(self, nom):
        self.themes_ouverts ^= {nom}
        self.remplir_questions()

    def ouvrir_theme(self, nom):
        self.barre_ouverte, self.themes_ouverts = True, {nom}
        self.dessiner_barre()

    def replier_barre(self):
        self.barre_ouverte = not self.barre_ouverte
        self.dessiner_barre()
        self.after(50, self.tracer)                 # (la figure a changé de largeur)

    def aller_question(self, q):
        """Ouvre la vue qui répond à la question, avec ses réglages ; ce qu'il reste à choisir va dans la barre d'état."""
        self.question_active = q
        if q["scrutin"]:
            s = d.scrutins().set_index("scrutin").loc[q["scrutin"]]
            self.cb_type.set(s["type"]); self.cb_annee.set(str(s["annee"]))
            self.cb_tour.set(d.NOMS_TOURS.get(int(s["tour"]), "1er tour"))
            self.ctx.scrutin = q["scrutin"]
        self.options.update(q["options"])
        noms = [v[0] for v in VUES[q["onglet"]]]
        self.onglet, self.vue_i = q["onglet"], noms.index(q["vue"]) if q["vue"] in noms else 0
        self.top_actif = bool(q["top"])
        if q["top"]:
            t = q["top"]
            self.top_n.set(f"Top {t['n']}"); self.maj_niveaux_top()
            if d.NOMS_NIVEAUX.get(t["niveau"]) in self.top_niveau["values"]:
                self.top_niveau.set(d.NOMS_NIVEAUX[t["niveau"]])
            self.top_ordre.set(t["ordre"]); self.top_mesure.set(t["mesure"]); self.remplir_qui_top()
        if self.onglet in QUESTIONS:
            self.appliquer_question()
        for v in self.volets.values():
            v.ouvert = False
        self.placer_volets()
        self.dessiner_pastilles()
        self.maj_resumes()
        self.remplir_questions()
        self.tracer()
        if q["aide"]:
            self.etat.set(f"À toi : {q['aide']}   —   {self.etat.get()}")

    # ------------------------------------------------------------------ onglets et pastilles
    def creer_onglets(self):
        o = tk.Frame(self, bg=C["carte"], highlightthickness=0)
        o.pack(side="top", fill="x")
        self.rangee_onglets = o
        self.boutons_onglets = {}
        for nom in VUES:
            l = tk.Label(o, text=nom, bg=C["carte"], fg=C["texte2"], font=theme.POLICE, padx=int(11 / theme.ZOOM), pady=9, cursor="hand2")
            l.pack(side="left")
            theme.cliquable(l, lambda n=nom: self.choisir_vue(n, 0))
            self.boutons_onglets[nom] = l
        tk.Frame(self, bg=C["bordure"], height=1).pack(side="top", fill="x")
        self.rangee_pastilles = tk.Frame(self, bg=C["pale"])
        self.rangee_pastilles.pack(side="top", fill="x")

    def dessiner_pastilles(self):
        for w in self.rangee_pastilles.winfo_children():
            w.destroy()
        for i, v in enumerate(VUES[self.onglet]):
            actif = i == self.vue_i and not self.top_actif
            l = tk.Label(self.rangee_pastilles, text=v[0], bg=C["primaire"] if actif else C["carte"], fg=C["sur"] if actif else C["primaire"],
                         font=theme.POLICE_GRAS if actif else theme.POLICE_PETITE, padx=11, pady=3, cursor="hand2",
                         highlightthickness=1, highlightbackground=C["primaire"] if actif else C["moyen"])
            l.pack(side="left", padx=(8 if i == 0 else 3, 0), pady=8)
            theme.cliquable(l, lambda k=i: self.choisir_vue(self.onglet, k))
        for nom, l in self.boutons_onglets.items():
            l.configure(fg=C["primaire"] if nom == self.onglet else C["texte2"], font=theme.POLICE_GRAS if nom == self.onglet else theme.POLICE)

    # ------------------------------------------------------------------ graphique + fiche
    def creer_corps(self):
        corps = tk.Frame(self, bg=C["surface"])
        corps.pack(side="top", fill="both", expand=True)
        gauche = tk.Frame(corps, bg=C["carte"], highlightthickness=1, highlightbackground=C["bordure"])
        # (placée APRÈS le volet de droite, plus bas : le volet garde toujours sa largeur, le graphique prend le reste)
        self.fig = Figure(figsize=(9, 6), dpi=100)
        self.fig.hauteur_voulue = 0
        # la figure vit dans un canevas qui défile : une longue liste (Top 100…) se dessine en grand, avec l'ascenseur
        zone = tk.Frame(gauche, bg=C["carte"])
        self.defile = tk.Canvas(zone, bg=C["carte"], highlightthickness=0, width=300, height=300)   # (petite taille demandée : le volet de droite garde sa place)
        self.ascenseur = ttk.Scrollbar(zone, orient="vertical", command=self.defile.yview)
        self.defile.configure(yscrollcommand=self.ascenseur.set)
        self.defile.pack(side="left", fill="both", expand=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.defile)
        self.fenetre_fig = self.defile.create_window(0, 0, window=self.canvas.get_tk_widget(), anchor="nw")
        self.defile.bind("<Configure>", lambda e: self.ajuster_hauteur())
        w = self.canvas.get_tk_widget()
        w.bind("<Enter>", lambda e: w.bind_all("<MouseWheel>", self.roue_figure))
        w.bind("<Leave>", lambda e: w.unbind_all("<MouseWheel>"))
        barre = NavigationToolbar2Tk(self.canvas, gauche, pack_toolbar=False)
        barre.configure(bg=C["carte"])
        for w_ in barre.winfo_children():
            try:
                w_.configure(bg=C["carte"])
            except tk.TclError:
                pass
        barre.update()
        barre.pack(side="bottom", fill="x")
        zone.pack(fill="both", expand=True, padx=6, pady=6)
        self.canvas.mpl_connect("pick_event", self.clic_carte)
        large = int(370 * max(1.0, min(theme.ZOOM, 1.5)))          # (plus large quand les textes sont agrandis)
        droite = tk.Frame(corps, bg=C["carte"], highlightthickness=1, highlightbackground=C["bordure"], width=large)
        droite.pack(side="right", fill="y", padx=(6, 12), pady=10)
        gauche.pack(side="left", fill="both", expand=True, padx=(12, 6), pady=10)
        droite.pack_propagate(False)
        self.fiche = Defilant(droite, large - 20)
        self.lt = large - 60          # la largeur des textes de la fiche (retour à la ligne)
        self.fiche.pack(fill="both", expand=True)

    def creer_etat(self):
        """La barre du bas : le message d'état à gauche ; à droite la taille du texte (A− / A+) et le moteur des graphiques."""
        bas = tk.Frame(self, bg=C["surface"], highlightthickness=1, highlightbackground=C["bordure"])
        bas.pack(side="bottom", fill="x")
        droite = tk.Frame(bas, bg=C["surface"])
        droite.pack(side="right", padx=10, pady=3)
        tk.Label(droite, text="Taille du texte", bg=C["surface"], fg=C["texte2"], font=theme.POLICE_PETITE).pack(side="left", padx=(0, 6))
        for texte, pas in (("A−", -1), ("A+", +1)):
            l = tk.Label(droite, text=texte, bg=C["carte"], fg=C["primaire"], font=theme.POLICE_GRAS, padx=9, pady=1, cursor="hand2",
                         highlightthickness=1, highlightbackground=C["primaire"])
            l.pack(side="left", padx=2)
            theme.cliquable(l, lambda p_=pas: self.zoom(p_))
        tk.Label(droite, text="   Graphiques", bg=C["surface"], fg=C["texte2"], font=theme.POLICE_PETITE).pack(side="left", padx=(0, 6))
        self.boutons_moteur = {}
        for nom in ["seaborn", "matplotlib"]:
            l = tk.Label(droite, text=nom, font=theme.POLICE_PETITE, padx=10, pady=1, cursor="hand2", bg=C["carte"],
                         highlightthickness=1, highlightbackground=C["primaire"])
            l.pack(side="left", padx=1)
            theme.cliquable(l, lambda n=nom: self.changer_moteur(n))
            self.boutons_moteur[nom] = l
        self.changer_moteur("seaborn", tracer=False)
        self.etat = tk.StringVar(value="Bienvenue !  (Ctrl + / Ctrl − : taille du texte ; Tab : passer d'un bouton à l'autre)")
        ttk.Label(bas, textvariable=self.etat, style="Etat.TLabel", wraplength=1000).pack(side="left", fill="x", expand=True)

    # ------------------------------------------------------------------ les volets
    def creer_volets(self):
        self.volets = {"scrutin": self.volet_scrutin(), "zone": self.volet_zone(),
                       "top": self.volet_top(), "nuage": self.volet_nuage()}
        self.maj_regles_scrutin()
        self.maj_cascade("region")
        self.maj_resumes()

    def basculer(self, cle):
        v = self.volets[cle]
        if cle in ("top", "nuage"):     # un seul des deux à la fois
            autre = self.volets["nuage" if cle == "top" else "top"]
            autre.ouvert = False
        v.ouvert = not v.ouvert
        self.placer_volets()
        self.maj_resumes()

    def placer_volets(self):
        self.update_idletasks()
        y = self.bandeau.winfo_height()
        for cle in ["scrutin", "zone"]:
            v = self.volets[cle]
            if v.ouvert:
                v.place(x=0, y=y, relwidth=1)
                v.lift()
                self.update_idletasks()
                y += v.winfo_reqheight()
            else:
                v.place_forget()
        y2 = self.bandeau.winfo_height() + self.rangee_onglets.winfo_height()
        for cle in ["top", "nuage"]:
            v = self.volets[cle]
            if v.ouvert:
                v.place(x=0, y=max(y, y2), relwidth=1)
                v.lift()
            else:
                v.place_forget()

    def maj_resumes(self):
        type_, an, tour = self.cb_type.get(), self.cb_annee.get(), self.cb_tour.get()
        resume = f"🗳  {type_} · {an}" + ("" if tour == "Tour unique" else f" · {tour}")
        self.pilules["scrutin"].etat(court(resume, 48), self.volets["scrutin"].ouvert)
        self.pilules["zone"].etat(f"📍  {court(self.ctx.zone.libelle, 34)}", self.volets["zone"].ouvert)
        if self.onglet in QUESTIONS:
            q = QUESTIONS[self.onglet][self.vue_i]
            self.pilule_top.etat(f"⁘  Réglages du nuage · {court(q[0], 26)}", self.volets["nuage"].ouvert)
        else:
            t = self.lire_top()
            nom = t["mesure"] if t["mesure"] != "Score" else court(t.get("qui") or "", 18)
            self.pilule_top.etat(f"🏆  Top {t['n']} {d.NOMS_NIVEAUX.get(t['niveau'], '').lower()} · {nom}", self.volets["top"].ouvert)

    # --- volet Scrutin
    def volet_scrutin(self):
        v = Volet(self)
        ligne = tk.Frame(v, bg=C["pale"])
        ligne.pack(fill="x", padx=12, pady=8)
        f, self.cb_type = v.champ(ligne, "Scrutin", 20, d.types(), self.maj_regles_scrutin)
        f.pack(side="left", padx=(0, 12))
        f, self.cb_annee = v.champ(ligne, "Année", 26, [], lambda: self.maj_regles_scrutin("annee"))
        f.pack(side="left", padx=(0, 12))
        f, self.cb_tour = v.champ(ligne, "Tour", 12, [], lambda: self.maj_regles_scrutin("tour"))
        f.pack(side="left", padx=(0, 12))
        f, self.cb_regroup = v.champ(ligne, "Regrouper les voix par", 18, list(d.REGROUPEMENTS), self.changer_regroupement)
        f.pack(side="left", padx=(0, 12))
        self.cb_type.set("Présidentielle"); self.cb_regroup.set("Candidat / liste")
        self.info_scrutin = ttk.Label(ligne, text="", style="Pale.TLabel", foreground=C["gris"])
        self.info_scrutin.pack(side="left", padx=8)
        return v

    def maj_regles_scrutin(self, change="type"):
        t = self.cb_type.get()
        # référendum : le thème à côté de l'année (« 2005 · Constitution européenne »)
        ans = [f"{a} · {THEMES_REFERENDUMS[a]}" if t == "Référendum" and a in THEMES_REFERENDUMS else str(a) for a in d.annees(t)]
        self.cb_annee["values"] = ans
        meme_annee = [a for a in ans if a[:4] == self.cb_annee.get()[:4]]
        if self.cb_annee.get() not in ans:
            self.cb_annee.set(meme_annee[0] if meme_annee else ans[0] if t != "Présidentielle" or "2022" not in ans else "2022")
        tours = d.tours(t, self.cb_annee.get())
        noms = ["Tour unique"] if t in d.UN_SEUL_TOUR else [d.NOMS_TOURS[x] for x in tours]
        self.cb_tour["values"] = noms
        self.cb_tour.configure(state="readonly" if len(noms) > 1 else "disabled")
        if self.cb_tour.get() not in noms:
            self.cb_tour.set(noms[0])
        tour = d.TOURS_PAR_NOM.get(self.cb_tour.get(), 1)
        self.ctx.scrutin = d.scrutin_id(t, self.cb_annee.get(), tour)
        if t == "Référendum":
            info = "Référendum : un seul tour, deux réponses (OUI / NON)."
        elif t not in d.TYPES_NATIONAUX:
            info = "Élection locale : regrouper par nuance permet de comparer les familles politiques."
        else:
            info = ""
        self.info_scrutin.configure(text=info)
        if hasattr(self, "cascade"):
            self.maj_cascade("visibilite")
            self.maj_resumes()
            self.tracer()

    def changer_regroupement(self):
        self.ctx.regroupement = self.cb_regroup.get()
        g._rangs.cache_clear()
        self.remplir_qui_top()
        self.tracer()

    # --- volet Zone (la cascade)
    # (largeurs en caractères : assez pour « Auvergne-Rhône-Alpes » ou « Tous les arrondissements » sans couper le texte)
    NIVEAUX_ZONE = [("region", "Région", 21, "Toutes les régions"), ("departement", "Département", 21, "Tous les départements"),
                    ("arrondissement", "Arrondissement", 22, "Tous les arrondissements"), ("epci", "Intercommunalité", 25, "Toutes les intercommunalités"),
                    ("circo", "Circonscription", 23, "Toutes les circonscriptions"), ("canton", "Canton", 17, "Tous les cantons"),
                    ("commune", "Commune", 22, "Toutes les communes"), ("arrmun", "Arrondissement de la ville", 16, "Toute la ville"),
                    ("bureau", "Bureau de vote", 22, "Tous les bureaux")]

    FILTRABLES = ("commune", "bureau")      # listes où l'on peut taper pour filtrer (un numéro, un bout de nom…)

    def volet_zone(self):
        v = Volet(self)
        haut = tk.Frame(v, bg=C["pale"])
        haut.pack(fill="x", padx=12, pady=(8, 0))
        ttk.Label(haut, text="🔎 COMMUNE", style="Libelle.TLabel").pack(side="left")
        self.recherche = ttk.Entry(haut, width=28)
        self.recherche.pack(side="left", padx=(6, 18))
        self.recherche.bind("<KeyRelease>", self.chercher)
        self.recherche.bind("<Return>", lambda e: self.choisir_trouvee(0))
        self.recherche.bind("<Down>", lambda e: self.aller_dans_trouvees())
        self.recherche.bind("<Escape>", lambda e: self.cacher_trouvees())
        ttk.Label(haut, text="📫 ADRESSE → SON BUREAU", style="Libelle.TLabel").pack(side="left")
        self.recherche_adresse = ttk.Entry(haut, width=40)
        self.recherche_adresse.pack(side="left", padx=6)
        self.recherche_adresse.bind("<Return>", lambda e: self.chercher_adresse())
        self.recherche_adresse.bind("<Down>", lambda e: self.aller_dans_trouvees())
        self.recherche_adresse.bind("<Escape>", lambda e: self.cacher_trouvees())
        ttk.Button(haut, text="Trouver", style="Clair.TButton", command=self.chercher_adresse).pack(side="left")
        # l'aide : sur sa propre ligne, qui revient à la ligne (jamais coupée au bord de la fenêtre, même texte agrandi)
        ttk.Label(v, text="Exemple : « 12 avenue Lamartine Villiers » puis Entrée (répertoire électoral, sans internet).  "
                          "Dans « Bureau de vote », tape un numéro pour filtrer.", style="Gris.TLabel", background=C["pale"],
                  wraplength=1100).pack(anchor="w", padx=14, pady=(0, 2))
        self.trouvees, self.elements_trouves, self.choix_trouve = None, [], None
        ligne = tk.Frame(v, bg=C["pale"])
        ligne.pack(fill="x", padx=12, pady=8)
        self.cascade, self.cadres_zone, self.codes_zone, self.toutes_valeurs = {}, {}, {}, {}
        for cle, lib, larg, defaut in self.NIVEAUX_ZONE:
            f, cb = v.champ(ligne, lib, larg, [defaut], lambda c=cle: self.maj_cascade(c, utilisateur=True))
            cb.set(defaut)
            f.pack(side="left", padx=(0, 8))
            self.cascade[cle], self.cadres_zone[cle], self.codes_zone[cle] = cb, f, {}
            if cle in self.FILTRABLES:
                cb.bind("<KeyRelease>", lambda e, c=cle: self.filtrer(c, e))
                cb.bind("<Return>", lambda e, c=cle: self.valider_saisie(c))
                cb.bind("<FocusOut>", lambda e, c=cle: self.valider_saisie(c, en_partant=True))
        self.remplir("region", d.regions())
        return v

    # --- la liste flottante des résultats (communes ou adresses), sous le champ où l'on tape
    def montrer_trouvees(self, champ, lignes, elements, choisir):
        if self.trouvees is None:
            self.trouvees = tk.Listbox(self, height=12, font=theme.POLICE, activestyle="none", bg=C["carte"], fg=C["texte"],
                                       selectbackground=C["clair"], selectforeground=C["primaire"], relief="solid", bd=1, highlightthickness=0)
            self.trouvees.bind("<ButtonRelease-1>", lambda e: self.choisir_trouvee(self.trouvees.nearest(e.y)))
            self.trouvees.bind("<Return>", lambda e: self.choisir_trouvee((self.trouvees.curselection() or [0])[0]))
            self.trouvees.bind("<Escape>", lambda e: self.cacher_trouvees())
        self.trouvees.delete(0, "end")
        for l in lignes:
            self.trouvees.insert("end", l)
        self.elements_trouves, self.choix_trouve, self.champ_trouve = elements, choisir, champ
        x = champ.winfo_rootx() - self.winfo_rootx()
        y = champ.winfo_rooty() - self.winfo_rooty() + champ.winfo_height()
        self.trouvees.configure(height=min(12, max(1, len(lignes))))
        self.trouvees.place(x=x, y=y, width=520)
        self.trouvees.lift()

    def aller_dans_trouvees(self):
        if self.trouvees is not None and self.trouvees.winfo_ismapped() and self.elements_trouves:
            self.trouvees.focus_set()
            self.trouvees.selection_clear(0, "end"); self.trouvees.selection_set(0); self.trouvees.activate(0)

    def cacher_trouvees(self):
        if self.trouvees is not None:
            self.trouvees.place_forget()

    def choisir_trouvee(self, i):
        if not self.elements_trouves or i >= len(self.elements_trouves):
            return
        self.cacher_trouvees()
        self.champ_trouve.delete(0, "end")
        self.choix_trouve(self.elements_trouves[i])

    # --- recherche d'une commune en tapant
    def chercher(self, e):
        if e.keysym in ("Return", "Down", "Up", "Escape", "Tab"):
            return
        texte = self.recherche.get().strip()
        if len(texte) < 2:
            return self.cacher_trouvees()
        r = d.chercher_communes(texte)
        lignes = [f"{nom} ({code}) · {dep}" for code, nom, dep in r.itertuples(index=False)] or ["Aucune commune ne correspond."]
        self.montrer_trouvees(self.recherche, lignes, list(zip(r["code"], r["libelle"])), self.choisir_commune_trouvee)

    def choisir_commune_trouvee(self, element):
        code, nom = element
        self.choisir_zone(d.Zone("commune", code, nom))
        self.cascade["bureau"].focus_set()      # la suite logique : chercher son bureau

    # --- recherche d'une adresse : le répertoire électoral donne sa position et son bureau (data/adresses.parquet)
    def chercher_adresse(self):
        texte = self.recherche_adresse.get().strip()
        if len(texte) < 4:
            return
        if not adresse.disponible():
            self.etat.set("Pas de fichier data/adresses.parquet : lance py base_appli.py (il faut PROJET/election/table-adresses-reu.csv).")
            return
        self.etat.set("Recherche de l'adresse…"); self.update_idletasks()
        r = adresse.chercher_adresse(texte)
        lignes = [x["label"] for x in r] or ["Aucune adresse ne correspond (essaie moins de mots : « lamartine villiers »)."]
        self.montrer_trouvees(self.recherche_adresse, lignes, r, self.choisir_adresse)
        self.etat.set(f"{len(r)} adresse(s) — clique sur la bonne (ou ↓ puis Entrée)")

    def choisir_adresse(self, a):
        self.options["adresse"] = (a["lon"], a["lat"], a["label"])
        nom = f"{d.nom_zone('commune', a['commune'])} – bureau {a['bureau'].split('_')[-1]}"
        self.choisir_zone(d.Zone("bureau", a["bureau"], nom))
        if self.onglet != "Carte":
            self.choisir_vue("Carte", 0)
        self.etat.set(f"📫 {a['label']} → {nom} (bureau officiel du répertoire électoral)")

    # --- listes filtrables (commune, bureau) : on tape, la liste ne garde que ce qui contient le texte
    def filtrer(self, cle, e):
        if e.keysym in ("Return", "Down", "Up", "Escape", "Tab"):
            return
        cb, tout = self.cascade[cle], self.toutes_valeurs.get(cle, [])
        q = d.normaliser(cb.get())
        garde = [x for x in tout[1:] if q in d.normaliser(x)] if q else tout
        cb["values"] = garde or tout
        self.etat.set(f"{len(garde)} résultat(s) — ↓ pour ouvrir la liste" if q else "")

    def valider_saisie(self, cle, en_partant=False):
        cb = self.cascade[cle]
        texte, valeurs = cb.get(), list(cb["values"])
        defaut = next(x[3] for x in self.NIVEAUX_ZONE if x[0] == cle)
        if texte in self.codes_zone[cle] or texte == defaut:
            if not en_partant:
                self.maj_cascade(cle, utilisateur=True)
        elif len([x for x in valeurs if x != defaut]) == 1:       # un seul résultat : Entrée (ou quitter le champ) le choisit
            cb.set(next(x for x in valeurs if x != defaut))
            self.maj_cascade(cle, utilisateur=True)
        elif en_partant:
            cb.set(defaut)
        if en_partant:
            cb["values"] = self.toutes_valeurs.get(cle, valeurs)

    def code(self, cle):
        return self.codes_zone[cle].get(self.cascade[cle].get())

    def remplir(self, cle, df, actif=True):
        defaut = next(x[3] for x in self.NIVEAUX_ZONE if x[0] == cle)
        noms = df["libelle"].tolist() if df is not None and len(df) else []
        if cle == "commune" or cle == "departement":
            noms = [f"{l} ({c})" for c, l in zip(df["code"], df["libelle"])] if noms else []
        self.codes_zone[cle] = dict(zip(noms, df["code"])) if noms else {}
        self.cascade[cle]["values"] = self.toutes_valeurs[cle] = [defaut] + noms
        actif_ = "normal" if cle in self.FILTRABLES else "readonly"
        self.cascade[cle].configure(state=actif_ if actif and noms else "disabled")
        if self.cascade[cle].get() not in self.codes_zone[cle]:
            self.cascade[cle].set(defaut)

    def maj_cascade(self, depuis, utilisateur=False):
        """Chaque liste ne propose que ce qui est DANS le choix précédent."""
        ordre = [x[0] for x in self.NIVEAUX_ZONE]
        if utilisateur and depuis == "commune" and self.code("commune"):
            for c in ("canton", "circo"):
                self.cascade[c].set(next(x[3] for x in self.NIVEAUX_ZONE if x[0] == c))
        if utilisateur and depuis in ("canton", "circo") and self.code(depuis):
            self.cascade["commune"].set("Toutes les communes")
        t = self.cb_type.get()
        visible = {"circo": t == "Législatives", "canton": t in ("Cantonales", "Départementales")}
        for c in ("circo", "canton"):
            if visible[c]:
                self.cadres_zone[c].pack(side="left", padx=(0, 8), before=self.cadres_zone["commune"])
            else:
                self.cadres_zone[c].pack_forget()
                self.cascade[c].set(next(x[3] for x in self.NIVEAUX_ZONE if x[0] == c))
        debut = 0 if depuis in ("region", "visibilite") else ordre.index(depuis) + 1
        reg, dep = self.code("region"), self.code("departement")
        if debut <= 1:
            self.remplir("departement", d.departements(reg))
            dep = self.code("departement")
        if debut <= 2:
            self.remplir("arrondissement", d.arrondissements(dep) if dep else None, bool(dep))
        arr = self.code("arrondissement")
        if debut <= 4:
            self.remplir("epci", d.epcis(dep, arr) if dep else None, bool(dep))
            self.remplir("circo", d.circos(dep, arr) if dep else None, bool(dep))
            self.remplir("canton", d.cantons(dep, arr) if dep else None, bool(dep))
        epci, circo, canton = self.code("epci"), self.code("circo"), self.code("canton")
        if debut <= 7 or depuis in ("circo", "canton", "epci"):
            self.remplir("commune", d.communes(dep, arr, epci, circo if visible["circo"] else None, canton if visible["canton"] else None) if dep else None, bool(dep))
        com = self.code("commune")
        self.remplir("arrmun", d.arrmuns(com) if com in d.VILLES_PLM else None, com in d.VILLES_PLM)
        if com in d.VILLES_PLM:
            self.cadres_zone["arrmun"].pack(side="left", padx=(0, 8), before=self.cadres_zone["bureau"])
        else:
            self.cadres_zone["arrmun"].pack_forget()
        if depuis != "bureau":
            bv = d.bureaux(commune=com, arrmun=self.code("arrmun"), canton=canton if visible["canton"] else None,
                           circo=circo if visible["circo"] else None, epci=epci, arr=arr)
            self.remplir("bureau", bv, len(bv) > 0)
        # la zone la plus fine choisie
        zone = d.FRANCE
        for cle in ordre:
            c = self.code(cle)
            if c and (cle not in visible or visible[cle]):
                zone = d.Zone(cle, c, self.cascade[cle].get())
        self.ctx.zone = zone
        self.maj_niveaux_top()
        if utilisateur or depuis == "visibilite":
            self.maj_resumes()
            if utilisateur:
                self.remplir_qui_top()
                self.tracer()

    def choisir_zone(self, zone):
        """Depuis la carte : « Choisir comme zone »."""
        def poser(cle, code):
            for nom, c in self.codes_zone[cle].items():
                if c == code:
                    self.cascade[cle].set(nom)
                    return True
            return False
        for cle in [x[0] for x in self.NIVEAUX_ZONE]:
            self.cascade[cle].set(next(x[3] for x in self.NIVEAUX_ZONE if x[0] == cle))
        if zone.niveau == "france":
            self.maj_cascade("region")
        elif zone.niveau == "region":
            poser("region", zone.code)
        else:
            info = d.ou_est(zone)
            poser("region", info["r"]); self.maj_cascade("region")
            poser("departement", info["dp"]); self.maj_cascade("departement")
            if zone.niveau in ("arrondissement", "epci", "circo", "canton"):
                poser(zone.niveau, zone.code); self.maj_cascade(zone.niveau)
            if zone.niveau in ("commune", "bureau", "arrmun"):
                poser("commune", info["cm"]); self.maj_cascade("commune")
            if zone.niveau == "arrmun":                 # (un arrondissement de Paris, Lyon ou Marseille)
                poser("arrmun", zone.code); self.maj_cascade("arrmun")
            if zone.niveau == "bureau":
                poser("bureau", zone.code)
        self.maj_cascade("bureau", utilisateur=True)

    # --- volet Top
    def volet_top(self):
        v = Volet(self)
        ligne = tk.Frame(v, bg=C["pale"])
        ligne.pack(fill="x", padx=12, pady=8)
        f, self.top_n = v.champ(ligne, "Combien", 8, ["Top 5", "Top 10", "Top 25", "Top 50", "Top 100"], self.maj_resumes)
        f.pack(side="left", padx=(0, 10)); self.top_n.set("Top 25")
        f, self.top_niveau = v.champ(ligne, "Classer les", 18, [], self.maj_resumes)
        f.pack(side="left", padx=(0, 10))
        f, self.top_ordre = v.champ(ligne, "Ordre", 14, ["Les plus hauts", "Les plus bas"], self.maj_resumes)
        f.pack(side="left", padx=(0, 10)); self.top_ordre.set("Les plus hauts")
        f, self.top_mesure = v.champ(ligne, "Mesure", 14, ["Abstention", "Participation", "Blancs", "Nuls", "Blancs + nuls", "Exprimés", "Score"],
                                     lambda: (self.remplir_qui_top(), self.maj_resumes()))
        f.pack(side="left", padx=(0, 10)); self.top_mesure.set("Abstention")
        f, self.top_qui = v.champ(ligne, "Qui (si Score)", 30, [], self.maj_resumes)
        f.pack(side="left", padx=(0, 10))
        ttk.Button(ligne, text="Afficher le Top ▶", style="Action.TButton", command=self.afficher_top).pack(side="left", padx=10, pady=(12, 0))
        return v

    def maj_niveaux_top(self):
        rang = {"france": -1, "region": 0, "departement": 1, "arrondissement": 2, "epci": 3, "circo": 4, "canton": 4, "commune": 5, "arrmun": 6, "bureau": 7}
        niveaux = [("region", 0), ("departement", 1), ("arrondissement", 2), ("epci", 3), ("circo", 4), ("canton", 4), ("commune", 5), ("bureau", 7)]
        possibles = [d.NOMS_NIVEAUX[n] for n, r in niveaux if r > rang[self.ctx.zone.niveau]] or ["Bureaux de vote"]
        self.top_niveau["values"] = possibles
        if self.top_niveau.get() not in possibles:
            self.top_niveau.set("Départements" if "Départements" in possibles else possibles[0])

    def remplir_qui_top(self):
        if not hasattr(self, "top_qui") or not self.ctx.scrutin:
            return
        l = d.cles(self.ctx.scrutin, self.ctx.zone, self.ctx.regroupement, 30)
        self.top_qui["values"] = l
        self.top_qui.configure(state="readonly" if self.top_mesure.get() == "Score" else "disabled")
        if self.top_qui.get() not in l:
            self.top_qui.set(l[0] if l else "")

    def lire_top(self):
        inverse = {v: k for k, v in d.NOMS_NIVEAUX.items()}
        return {"n": int(self.top_n.get().split()[1]), "niveau": inverse.get(self.top_niveau.get(), "departement"),
                "ordre": self.top_ordre.get(), "mesure": self.top_mesure.get(), "qui": self.top_qui.get()}

    def afficher_top(self):
        self.top_actif = True
        self.volets["top"].ouvert = False
        self.placer_volets()
        self.maj_resumes()
        self.dessiner_pastilles()
        self.tracer()

    # --- volet du nuage
    def volet_nuage(self):
        v = Volet(self)
        self.axes_nuage = {}
        mesures = d.MESURES_ELECTION + list(d.MESURES_LOCALES) + list(d.MESURES_ECO)
        for a in ("x", "y"):
            ligne = tk.Frame(v, bg=C["pale"])
            ligne.pack(fill="x", padx=12, pady=(6, 0))
            tk.Label(ligne, text=a.upper(), bg=C["pale"], fg=C["primaire"], font=theme.POLICE_TITRE, width=2).pack(side="left", padx=(0, 8))
            w = {}
            f, w["mesure"] = v.champ(ligne, "Mesure", 26, mesures, lambda a=a: self.maj_axe(a))
            f.pack(side="left", padx=(0, 8))
            f, w["type"] = v.champ(ligne, "Élection", 15, d.types(), lambda a=a: self.maj_axe(a, "type"))
            f.pack(side="left", padx=(0, 8))
            f, w["annee"] = v.champ(ligne, "Année", 7, [], lambda a=a: self.maj_axe(a, "annee"))
            f.pack(side="left", padx=(0, 8))
            f, w["tour"] = v.champ(ligne, "Tour", 9, [], lambda a=a: self.maj_axe(a, "tour"))
            f.pack(side="left", padx=(0, 8))
            f, w["regroupement"] = v.champ(ligne, "Regrouper par", 15, list(d.REGROUPEMENTS), lambda a=a: self.maj_axe(a, "regroupement"))
            f.pack(side="left", padx=(0, 8))
            f, w["qui"] = v.champ(ligne, "Qui", 28, [])
            f.pack(side="left", padx=(0, 8))
            f, w["plus"] = v.champ(ligne, "+ ajouter (même échelle)", 22, ["(rien)"] + list(d.MESURES_ECO) + ["Abstention"])
            f.pack(side="left", padx=(0, 8))
            self.axes_nuage[a] = w
        ligne = tk.Frame(v, bg=C["pale"])
        ligne.pack(fill="x", padx=12, pady=8)
        tk.Label(ligne, text="⚙", bg=C["pale"], fg=C["primaire"], font=theme.POLICE_TITRE, width=2).pack(side="left", padx=(0, 8))
        f, self.n_point = v.champ(ligne, "Un point =", 16, ["Bureau de vote", "Commune", "Département", "Élection", "Mois"])
        f.pack(side="left", padx=(0, 8))
        f, self.n_type = v.champ(ligne, "Élections (si un point = élection)", 22, ["Toutes les élections"] + d.types())
        f.pack(side="left", padx=(0, 8)); self.n_type.set("Toutes les élections")
        self.n_diag = tk.BooleanVar()
        tk.Checkbutton(ligne, text="Diagonale", variable=self.n_diag, bg=C["pale"], activebackground=C["pale"]).pack(side="left", padx=8, pady=(12, 0))
        ttk.Button(ligne, text="Tracer ▶", style="Action.TButton", command=self.tracer).pack(side="left", padx=10, pady=(12, 0))
        return v

    def maj_axe(self, a, depuis="mesure"):
        w = self.axes_nuage[a]
        t = w["type"].get() or "Présidentielle"
        ans = [str(x) for x in d.annees(t)]
        w["annee"]["values"] = ans
        if w["annee"].get() not in ans:
            w["annee"].set(ans[0] if ans else "")
        tours = d.tours(t, w["annee"].get()) if ans else []
        w["tour"]["values"] = [d.NOMS_TOURS[x] for x in tours]
        if w["tour"].get() not in w["tour"]["values"]:
            w["tour"].set("1er tour")
        m = w["mesure"].get()
        electoral = m in d.MESURES_ELECTION
        for k in ("type", "annee", "tour"):
            w[k].configure(state="readonly" if electoral else "disabled")
        for k in ("regroupement", "qui"):
            w[k].configure(state="readonly" if m == "Score" else "disabled")
        if m == "Score":
            s = self.scrutin_axe(a)
            l = d.cles(s, self.ctx.zone, w["regroupement"].get() or "Candidat / liste", 30) if s else []
            w["qui"]["values"] = l
            if w["qui"].get() not in l and depuis != "preset":
                w["qui"].set(l[0] if l else "")

    def scrutin_axe(self, a):
        w = self.axes_nuage[a]
        try:
            return d.scrutin_id(w["type"].get(), w["annee"].get(), d.TOURS_PAR_NOM.get(w["tour"].get(), 1))
        except (ValueError, TypeError):
            return None

    def appliquer_question(self):
        """Une question des onglets Nuages / Économie : on remplit le volet de réglages avec son préréglage."""
        court_, q, x, y, point, diag, lecture = QUESTIONS[self.onglet][self.vue_i]
        for a, ax in (("x", x), ("y", y)):
            w = self.axes_nuage[a]
            w["mesure"].set(ax["mesure"])
            if ax.get("scrutin"):
                s = d.scrutins().set_index("scrutin").loc[ax["scrutin"]]
                w["type"].set(s["type"]); w["annee"].set(str(s["annee"])); w["tour"].set("1er tour" if s["tour"] == 1 else "2nd tour")
            w["regroupement"].set(ax.get("regroupement", "Candidat / liste"))
            w["qui"].set(ax.get("qui") or "")
            w["plus"].set(ax.get("plus", "(rien)"))
            self.maj_axe(a, "preset")
        self.n_point.set(point)
        self.n_diag.set(diag)
        self.question = (q, lecture, court_.startswith("Ma zone"))

    def lire_nuage(self):
        axe = lambda a: {"mesure": self.axes_nuage[a]["mesure"].get(), "scrutin": self.scrutin_axe(a),
                         "regroupement": self.axes_nuage[a]["regroupement"].get() or "Candidat / liste",
                         "qui": self.axes_nuage[a]["qui"].get(), "plus": self.axes_nuage[a]["plus"].get() or "(rien)"}
        q, lecture, zf = self.question
        return {"question": q, "lecture": lecture, "zone_france": zf, "x": axe("x"), "y": axe("y"), "point": self.n_point.get(),
                "diagonale": self.n_diag.get(), "type": self.n_type.get()}

    # ------------------------------------------------------------------ choisir et tracer une vue
    def choisir_vue(self, onglet, i):
        self.onglet, self.vue_i, self.top_actif = onglet, i, False
        if onglet in QUESTIONS:
            self.appliquer_question()
        self.volets["top"].ouvert = self.volets["nuage"].ouvert = False
        self.placer_volets()
        self.dessiner_pastilles()
        self.maj_resumes()
        self.tracer()

    def vue(self):
        if self.top_actif:
            return ("Top", g.top, ["barres_h", "barres_v", "tableau"], [], "Zones de moins de 200 inscrits ignorées (50 pour les bureaux).")
        return VUES[self.onglet][self.vue_i]

    def ajuster_hauteur(self):
        """La figure prend la largeur visible, et la hauteur demandée par la vue si elle dépasse (alors : ascenseur)."""
        largeur, visible = self.defile.winfo_width(), self.defile.winfo_height()
        hauteur = max(visible, self.fig.hauteur_voulue)
        self.defile.itemconfigure(self.fenetre_fig, width=largeur, height=hauteur)
        self.defile.configure(scrollregion=(0, 0, largeur, hauteur))
        if hauteur > visible:
            self.ascenseur.pack(side="right", fill="y")
        else:
            self.ascenseur.pack_forget()

    def roue_figure(self, e):
        if self.fig.hauteur_voulue > self.defile.winfo_height():
            self.defile.yview_scroll(int(-e.delta / 120) * 3, "units")

    def tracer(self):
        if not self.ctx.scrutin:
            return
        nom, fonction, formes, reglages, precaution = self.vue()
        cle = (self.onglet, nom)
        forme = self.formes.get(cle, formes[0] if formes else None)
        self.ctx.forme = forme
        self.ctx.options = dict(self.options, mode_carte="Participation" if nom == "Participation sur la carte" else "Résultats")
        self.ctx.top = self.lire_top() if self.top_actif else None
        self.ctx.comparaison = list(self.comparaison)
        self.ctx.nuage = self.lire_nuage() if self.onglet in QUESTIONS and not self.top_actif else None
        self.etat.set("Calcul en cours…")
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.fig.clear()
            self.fig.set_layout_engine("none")
            self.fig.hauteur_voulue = 0
            g.donnees(None)
            # la taille FINALE de la zone de dessin (la figure n'est mise à cette taille qu'après le dessin)
            self.fig.largeur_visible, self.fig.hauteur_visible = self.defile.winfo_width(), self.defile.winfo_height()
            if self.fig.largeur_visible > 50 and self.fig.hauteur_visible > 50:      # (repart de la taille visible : une longue vue
                self.fig.set_size_inches(self.fig.largeur_visible / self.fig.dpi,    #  précédente avait agrandi la figure)
                                         self.fig.hauteur_visible / self.fig.dpi, forward=False)
            info = fonction(self.fig, self.ctx)
            self.ajuster_hauteur()
            self.defile.yview_moveto(0)
            self.canvas.draw()
        except Exception as erreur:      # on affiche l'erreur au lieu de faire planter l'appli
            self.fig.clear()
            self.fig.hauteur_voulue = 0
            self.ajuster_hauteur()
            self.canvas.draw()
            info = {"legende": [], "kpi": [], "lecture": f"Impossible de tracer cette vue : {erreur!r}"}
        finally:
            self.config(cursor="")
        self.info = info
        self.etat.set(info.get("lecture", ""))
        self.remplir_fiche(nom, formes, forme, reglages, precaution, info)

    # ------------------------------------------------------------------ la fiche de droite
    def intertitre(self, parent, texte):
        ttk.Label(parent, text=texte.upper(), style="Inter.TLabel").pack(anchor="w", padx=14, pady=(12, 4))

    def remplir_fiche(self, nom, formes, forme, reglages, precaution, info, detail=None, scrutins_cliques=None, elu=None, votant=None, affiche=None):
        f = self.fiche.interieur
        for w in f.winfo_children():
            w.destroy()
        titre = QUESTIONS[self.onglet][self.vue_i][0].replace("📈 ", "") if self.onglet in QUESTIONS and not self.top_actif else nom
        ttk.Label(f, text=titre, style="Titre.TLabel", wraplength=self.lt).pack(anchor="w", padx=14, pady=(14, 2))
        texte = (QUESTIONS[self.onglet][self.vue_i][1] if self.onglet in QUESTIONS and not self.top_actif
                 else DESCRIPTIONS.get(nom, "Le classement des zones selon les réglages du Top."))
        ttk.Label(f, text=texte, style="Gris.TLabel", wraplength=self.lt).pack(anchor="w", padx=14)
        self.fiche_export(f)
        if detail:
            self.fiche_detail(f, detail)
        if scrutins_cliques:
            self.fiche_scrutins(f, scrutins_cliques)
        if elu:
            self.fiche_elu(f, *elu)
        if votant:
            self.fiche_votant(f, *votant)
        if affiche is not None:
            self.fiche_affiche(f, affiche)
        if self.onglet == "Candidat" and self.ctx.regroupement == "Candidat / liste" and not self.top_actif:
            self.fiche_candidats(f, reglages)
        if self.onglet == "Candidat" and not self.top_actif and self.ctx.regroupement == "Candidat / liste":
            self.fiche_qui_sont_ils(f)
        if self.onglet == "Candidat" and not self.top_actif:
            self.fiche_affiches_candidats(f)
        # autres façons de voir
        if len(formes) > 1:
            self.intertitre(f, "Autres façons de voir")
            r = tk.Frame(f, bg=C["carte"])
            r.pack(anchor="w", padx=12)
            for k in formes:
                actif = k == forme
                l = tk.Label(r, text=NOMS_FORMES.get(k, k), bg=C["clair"] if actif else C["carte"], fg=C["primaire"],
                             font=theme.POLICE_GRAS if actif else theme.POLICE_PETITE, padx=8, pady=4, cursor="hand2",
                             highlightthickness=1, highlightbackground=C["primaire"] if actif else C["moyen"])
                l.pack(side="left", padx=2, pady=2)
                theme.cliquable(l, lambda k=k: self.changer_forme(k))
        # légende
        if info.get("legende"):
            self.intertitre(f, "Légende")
            for texte, couleur in info["legende"][:20]:
                r = tk.Frame(f, bg=C["carte"])
                r.pack(anchor="w", padx=14, pady=1)
                tk.Label(r, bg=couleur, width=2, height=1, highlightthickness=1, highlightbackground=C["gris"]).pack(side="left", padx=(0, 6))
                l = ttk.Label(r, text=texte, font=theme.POLICE_PETITE)
                l.pack(side="left")
                if d.explication(texte):          # (un code de nuance : son explication au survol ou au clavier)
                    theme.infobulle(l, d.explication(texte))
        # chiffres clés
        if info.get("kpi"):
            self.intertitre(f, "Chiffres clés")
            r = tk.Frame(f, bg=C["carte"])
            r.pack(anchor="w", padx=12, fill="x")
            for v, l in info["kpi"][:3]:
                b = tk.Frame(r, bg=C["pale"], padx=8, pady=6)
                b.pack(side="left", padx=2, fill="both", expand=True)
                tk.Label(b, text=v, bg=C["pale"], fg=C["primaire"], font=theme.POLICE_CHIFFRE).pack(anchor="w")
                tk.Label(b, text=l, bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE, wraplength=self.lt // 3 - 10, justify="left").pack(anchor="w")
        # réglages propres à la vue
        if reglages:
            self.intertitre(f, "Réglages de la vue")
            self.fiche_reglages(f, reglages)
        # listes et colistiers
        self.fiche_listes(f)
        # précaution
        if precaution:
            tk.Label(f, text="ℹ  " + precaution, bg=C["clair"], fg=C["primaire"], font=theme.POLICE_PETITE, wraplength=self.lt,
                     justify="left", padx=10, pady=8).pack(anchor="w", padx=12, pady=(14, 14), fill="x")
        self.fiche.canvas.yview_moveto(0)

    def fiche_export(self, f):
        """Deux boutons (atteignables au clavier) : la vue en texte (Bloc-notes, lu par NVDA) ou en CSV (tableur)."""
        r = tk.Frame(f, bg=C["carte"])
        r.pack(anchor="w", padx=12, pady=(8, 0))
        ttk.Button(r, text="📄 Texte (Ctrl+E)", style="Clair.TButton", command=lambda: self.exporter("texte")).pack(side="left")
        ttk.Button(r, text="📊 CSV (Ctrl+Maj+E)", style="Clair.TButton", command=lambda: self.exporter("csv")).pack(side="left", padx=6)
        if theme.ZOOM > 1.05:
            for w in r.winfo_children():
                w.pack_configure(side="top", anchor="w", padx=0, pady=(0, 4))

    def exporter(self, sorte="texte"):
        """Les données de la vue affichée → un fichier texte ou CSV, ouvert tout de suite."""
        nom, _, _, _, precaution = self.vue()
        titre = QUESTIONS[self.onglet][self.vue_i][0] if self.onglet in QUESTIONS and not self.top_actif else nom
        entete = {"titre": f"{self.onglet} — {titre}", "scrutin": d.libelle(self.ctx.scrutin), "zone": self.ctx.zone.libelle,
                  "explication": DESCRIPTIONS.get(nom, ""), "precaution": precaution}
        tableaux = list(g.DONNEES) or export.depuis_figure(self.fig)
        chemin = export.enregistrer(entete, getattr(self, "info", {}) or {}, tableaux, sorte)
        self.etat.set(f"Données enregistrées et ouvertes : {chemin}")
        return chemin

    def changer_forme(self, forme):
        nom = self.vue()[0]
        self.formes[(self.onglet, nom)] = forme
        self.tracer()

    def fiche_reglages(self, f, reglages):
        def combo(lib, valeurs, cle, largeur=36):
            ttk.Label(f, text=lib, style="Gris.TLabel").pack(anchor="w", padx=14)
            cb = ttk.Combobox(f, values=valeurs, state="readonly", width=largeur)
            cb.set(self.options.get(cle) or (valeurs[0] if valeurs else ""))
            cb.pack(anchor="w", padx=14, pady=(0, 6))
            cb.bind("<<ComboboxSelected>>", lambda e: (self.options.__setitem__(cle, cb.get()), self.tracer()))
        if "indicateur" in reglages:
            combo("Indicateur", list(d.INDICATEURS), "indicateur")
        if "tranches" in reglages:
            ttk.Label(f, text="Nombre de tranches", style="Gris.TLabel").pack(anchor="w", padx=14)
            v = tk.IntVar(value=self.options.get("tranches", 60))
            s = tk.Scale(f, from_=10, to=200, resolution=10, orient="horizontal", variable=v, length=290, bg=C["carte"],
                         highlightthickness=0, troughcolor=C["clair"], activebackground=C["primaire"])
            s.pack(anchor="w", padx=14)
            s.bind("<ButtonRelease-1>", lambda e: (self.options.__setitem__("tranches", v.get()), self.tracer()))
        if "candidat" in reglages or "candidat2" in reglages:
            l = d.cles(self.ctx.scrutin, self.ctx.zone, self.ctx.regroupement, 30)
            if self.options.get("candidat") not in l:
                self.options["candidat"] = l[0] if l else None
            if "candidat2" in reglages and self.options.get("candidat2") not in l:
                self.options["candidat2"] = l[1] if len(l) > 1 else None
            combo("Candidat (ou nuance)", l, "candidat")
            if "candidat2" in reglages:
                combo("contre", l, "candidat2")
        if "texte" in reglages:
            ttk.Label(f, text="Nom à suivre (ex. LE PEN, BAYROU, MÉLENCHON)", style="Gris.TLabel").pack(anchor="w", padx=14)
            r = tk.Frame(f, bg=C["carte"]); r.pack(anchor="w", padx=14)
            e = ttk.Entry(r, width=24); e.insert(0, self.options.get("texte", "")); e.pack(side="left")
            valider = lambda *_: (self.options.__setitem__("texte", e.get()), self.tracer())
            e.bind("<Return>", valider)
            ttk.Button(r, text="OK", style="Clair.TButton", command=valider).pack(side="left", padx=6)
        if "echelle" in reglages:
            combo("Échelle (fixée : elle ne change pas avec le zoom)", list(g.ECHELLES), "echelle")
        if "chambre" in reglages:
            combo("Chambre", ["Assemblée nationale", "Sénat"], "chambre")
        if "comparaison" in reglages:
            for lettre, z_, coul in zip("AB", self.comparaison + [None, None], g.COULEURS_AB):
                ligne = tk.Frame(f, bg=C["carte"]); ligne.pack(anchor="w", padx=14, pady=1)
                tk.Label(ligne, text="  ", bg=coul).pack(side="left")
                tk.Label(ligne, text=f" {lettre} : {z_.libelle if z_ else '(à choisir)'}", bg=C["carte"], fg=C["texte"],
                         font=theme.POLICE, wraplength=self.lt - 30, justify="left").pack(side="left")
            ligne = tk.Frame(f, bg=C["carte"]); ligne.pack(anchor="w", padx=14, pady=(4, 6))
            ttk.Button(ligne, text="➕ Ajouter la zone choisie", style="Clair.TButton",
                       command=lambda: self.ajouter_comparaison(self.ctx.zone)).pack(side="left")
            ttk.Button(ligne, text="Vider", style="Clair.TButton", command=self.vider_comparaison).pack(side="left", padx=6)
        if "fond" in reglages:
            combo("Fond de plan (pour se repérer)", g.FONDS, "fond")
        if "vote" in reglages:
            def choisir_vote(sid):
                self.options["vote"] = sid
                self.tracer()
            grands = dict(votes_deputes.GRANDS_VOTES)
            ttk.Label(f, text="Un grand vote de l'histoire", style="Gris.TLabel").pack(anchor="w", padx=14)
            cb = ttk.Combobox(f, values=list(grands), state="readonly", width=44)
            actuel = self.options.get("vote") or votes_deputes.GRANDS_VOTES[17][1]
            cb.set(next((lib for lib, s in grands.items() if s == actuel), ""))
            cb.pack(anchor="w", padx=14, pady=(0, 6))
            cb.bind("<<ComboboxSelected>>", lambda e: choisir_vote(grands[cb.get()]))
            ttk.Label(f, text="… ou un scrutin depuis 2012 (mots-clés)", style="Gris.TLabel").pack(anchor="w", padx=14)
            r = tk.Frame(f, bg=C["carte"]); r.pack(anchor="w", padx=14)
            e = ttk.Entry(r, width=20); e.insert(0, self.options.get("recherche_vote", "")); e.pack(side="left")
            chercher = lambda *_: (self.options.__setitem__("recherche_vote", e.get()), self.tracer())
            e.bind("<Return>", chercher)
            ttk.Button(r, text="Chercher", style="Clair.TButton", command=chercher).pack(side="left", padx=6)
            trouves = dict(votes_deputes.chercher(self.options.get("recherche_vote", "")))
            if trouves:
                cb2 = ttk.Combobox(f, values=list(trouves), state="readonly", width=44)
                cb2.set(next((lib for lib, s in trouves.items() if s == actuel), f"{len(trouves)} scrutins trouvés : choisis-en un"))
                cb2.pack(anchor="w", padx=14, pady=(4, 6))
                cb2.bind("<<ComboboxSelected>>", lambda e: choisir_vote(trouves[cb2.get()]))
            elif self.options.get("recherche_vote"):
                ttk.Label(f, text="Aucun scrutin avec ces mots.", style="Gris.TLabel").pack(anchor="w", padx=14)
        if "legislature" in reglages and legislatures.disponible():
            combo("Législature", legislatures.libelles(), "legislature", largeur=38)
        if "affiches" in reglages and affiches.disponible():
            t = affiches.tout()
            combo("Élection", ["Tous"] + sorted(t["type"].unique()), "affiche_type")
            combo("Année", ["Toutes"] + [str(x) for x in sorted(t["annee"].unique())], "affiche_annee")
            ttk.Label(f, text="Un nom ou un mot de l'affiche (ex. SARKOZY, écologie)", style="Gris.TLabel").pack(anchor="w", padx=14)
            r = tk.Frame(f, bg=C["carte"]); r.pack(anchor="w", padx=14)
            e3 = ttk.Entry(r, width=20); e3.insert(0, self.options.get("affiche_cherche", "")); e3.pack(side="left")
            valider3 = lambda *_: (self.options.__setitem__("affiche_cherche", e3.get().strip()), self.tracer())
            e3.bind("<Return>", valider3)
            ttk.Button(r, text="OK", style="Clair.TButton", command=valider3).pack(side="left", padx=6)
            ttk.Button(f, text="Tout afficher (sans filtre)", style="Clair.TButton",
                       command=lambda: ([self.options.pop(k, None) for k in ("affiche_type", "affiche_annee", "affiche_cherche")], self.tracer())
                       ).pack(anchor="w", padx=14, pady=(6, 0))
        if "personne" in reglages:
            ttk.Label(f, text="Un nom (ex. Royal, Ségolène Royal, Silberstein)", style="Gris.TLabel").pack(anchor="w", padx=14)
            r = tk.Frame(f, bg=C["carte"]); r.pack(anchor="w", padx=14)
            e4 = ttk.Entry(r, width=24); e4.insert(0, self.options.get("recherche_personne", "")); e4.pack(side="left")
            chercher_p = lambda *_: (self.options.__setitem__("recherche_personne", e4.get().strip()), self.options.pop("personne", None),
                                     self.tracer())
            e4.bind("<Return>", chercher_p)
            ttk.Button(r, text="Chercher", style="Clair.TButton", command=chercher_p).pack(side="left", padx=6)
            trouvees = personnes.chercher(self.options.get("recherche_personne", "")) if self.options.get("recherche_personne") else None
            if trouvees is not None and len(trouvees):
                choix = {personnes.etiquette(l): int(l["id"]) for _, l in trouvees.iterrows()}
                ttk.Label(f, text=f"{len(trouvees)} personne(s) : choisis-en une (les plus connues d'abord)", style="Gris.TLabel").pack(anchor="w", padx=14, pady=(4, 0))
                cb4 = ttk.Combobox(f, values=list(choix), state="readonly", width=44)
                cb4.set(next((k for k, v in choix.items() if v == self.options.get("personne")), ""))
                cb4.pack(anchor="w", padx=14, pady=(0, 6))
                cb4.configure(postcommand=lambda: elargir_liste(cb4))
                cb4.bind("<<ComboboxSelected>>", lambda e: (self.options.__setitem__("personne", choix[cb4.get()]), self.tracer()))
                if not self.options.get("personne"):          # (la plus connue, tout de suite)
                    self.options["personne"] = next(iter(choix.values()))
                    self.after(10, self.tracer)
            elif trouvees is not None:
                ttk.Label(f, text="Personne de ce nom dans la base.", style="Gris.TLabel").pack(anchor="w", padx=14)
        if "gouvernement" in reglages and personnes.disponible():
            combo("Gouvernement", personnes.gouvernements()["choix"].tolist(), "gouvernement", largeur=44)
        if "ecole" in reglages and personnes.disponible():
            combo("École (la liste de ses ministres est dans l'export)", personnes.ecoles(), "ecole", largeur=44)
        if "prefets_depuis" in reglages:
            combo("Depuis", ["1945", "1800", "1990"], "prefets_depuis", largeur=10)
        if "depute" in reglages:
            ttk.Label(f, text="Un député (nom, même partiel)", style="Gris.TLabel").pack(anchor="w", padx=14, pady=(6, 0))
            r = tk.Frame(f, bg=C["carte"]); r.pack(anchor="w", padx=14)
            e2 = ttk.Entry(r, width=24); e2.insert(0, self.options.get("depute", "")); e2.pack(side="left")
            valider = lambda *_: (self.options.__setitem__("depute", e2.get().strip()), self.tracer())
            e2.bind("<Return>", valider)
            ttk.Button(r, text="OK", style="Clair.TButton", command=valider).pack(side="left", padx=6)
            for dep, gr, pos in votes_deputes.vote_de(self.options.get("depute", ""), self.options.get("vote") or votes_deputes.GRANDS_VOTES[17][1])[:8]:
                tk.Label(f, text=f"{dep} ({court(gr, 24)}) : {pos.upper()}", bg=C["carte"], fg=votes_deputes.POSITIONS.get(pos, C["texte"]),
                         font=theme.POLICE_GRAS, wraplength=self.lt, justify="left").pack(anchor="w", padx=14)

    def fiche_listes(self, f):
        """Les listes et tous leurs colistiers (municipales, régionales, européennes), quand on les a."""
        s, z = self.ctx.scrutin.replace("_2t", "_t1"), self.ctx.zone      # « les 2 tours » : les listes du 1er tour
        if s not in d.elections_avec_listes():
            return
        t = d.type_de(s)
        groupes = []
        if t == "Municipales":
            com = z.code if z.niveau == "commune" else z.code.split("_")[0] if z.niveau == "bureau" else None
            if z.niveau == "departement" and z.code == "75":                     # (Paris : le département est la commune)
                com = "75056"
            if z.niveau == "arrmun":                                              # (un arrondissement de Paris, Lyon, Marseille)
                com = {"751": "75056", "693": "69123", "132": "13055"}.get(z.code[:3])
            if not com:
                self.intertitre(f, "Listes et colistiers")
                ttk.Label(f, text="Choisis une commune dans le volet Zone pour voir ses listes.", style="Gris.TLabel", wraplength=self.lt).pack(anchor="w", padx=14)
                return
            groupes.append(("Conseil municipal", com, "municipal"))
            if com in d.VILLES_PLM:
                # les listes de chaque secteur (jusqu'en 2020 : le conseil municipal ; depuis 2026 : le conseil d'arrondissement) ;
                # un arrondissement choisi : seulement son secteur
                seul = sieges.numero_secteur(com, int(s[:4]), z.code) if z.niveau == "arrmun" else None
                for code, conseil in d.sql(f"""SELECT DISTINCT z.code, l.conseil FROM modele.liste l JOIN modele.scrutin sc ON sc.id = l.scrutin_id
                                     JOIN modele.election e ON e.id = sc.election_id
                                     JOIN modele.zone z ON z.id = l.zone_id AND z.niveau_id = {d.NIVEAU['secteur']}
                                     WHERE e.code = ? AND sc.tour = ? AND z.code LIKE ? ORDER BY 1, 2""",
                                           [*d.election_tour(s), com + "SR%"]).itertuples(index=False):
                    if seul is None or int(code[-2:]) == seul:
                        quoi = "Conseil municipal" if conseil == "municipal" else "Conseil d'arrondissement"
                        groupes.append((f"{quoi} – secteur {int(code[-2:])}", code, conseil))
        elif t == "Régionales":
            reg = z.code if z.niveau == "region" else None
            if z.niveau not in ("france", "region"):
                reg = d.sql(f"SELECT any_value(code_region) r FROM {d.P(s)} p WHERE {d.filtre(z)[0]}", d.filtre(z)[1])["r"].iloc[0]
            if not reg:
                self.intertitre(f, "Listes et colistiers")
                ttk.Label(f, text="Choisis une région (ou plus petit) pour voir ses listes.", style="Gris.TLabel", wraplength=self.lt).pack(anchor="w", padx=14)
                return
            groupes.append(("Conseil régional", reg, "régional"))
        elif t == "Européennes":
            groupes.append(("Listes nationales", "FR", "européen"))
        self.intertitre(f, "Listes et colistiers")
        arbre = ttk.Treeview(f, columns=("info",), show="tree headings", height=12)
        arbre.heading("#0", text="Liste / candidat"); arbre.heading("info", text="")
        arbre.column("#0", width=245); arbre.column("info", width=62, anchor="e")
        arbre.pack(anchor="w", padx=12, fill="x")
        self.listes_chargees = {}
        nuance_de = {}                 # (une liste de l'arbre → son code de nuance, pour l'expliquer quand on la choisit)
        n = 0
        for titre, code, conseil in groupes[:25]:
            l = d.listes(s, code, conseil)
            if l.empty:
                continue
            g_ = arbre.insert("", "end", text=titre, open=len(groupes) == 1)
            for row in l.itertuples():
                nuance = f"[{row.nuance}] " if isinstance(row.nuance, str) else ""
                it = arbre.insert(g_, "end", text=f"{row.numero_panneau}. {nuance}{court(row.libelle_liste, 30)} — {row.tete or ''}",
                                  values=(f"{row.noms} noms",))
                arbre.insert(it, "end", text="…")
                self.listes_chargees[it] = (s, code, row.numero_panneau, conseil)
                nuance_de[it] = row.nuance if isinstance(row.nuance, str) else None
                n += 1
        if n == 0:
            arbre.destroy()
            ttk.Label(f, text="Pas de liste pour ce scrutin dans cette zone.", style="Gris.TLabel").pack(anchor="w", padx=14)
            return

        def ouvrir(_):
            it = arbre.focus()
            if it in self.listes_chargees:
                s_, code_, pan, conseil_ = self.listes_chargees.pop(it)
                arbre.delete(*arbre.get_children(it))
                for c in d.colistiers(s_, code_, pan, conseil_).itertuples():
                    sec = f"[{c.section}] " if conseil_ == "régional" else ""
                    arbre.insert(it, "end", text=f"{sec}{int(c.ordre) if c.ordre == c.ordre else ''}. {c.prenom} {c.nom}",
                                 values=("tête" if c.tete_de_liste else c.sexe,))
        arbre.bind("<<TreeviewOpen>>", ouvrir)
        # la nuance de la liste choisie, en clair (« [LUG] » → « LUG : Liste d'union de la gauche »)
        sens = ttk.Label(f, text="", wraplength=self.lt)
        sens.pack(anchor="w", padx=14, pady=(2, 0))

        def expliquer(_):
            code = nuance_de.get(arbre.focus())
            sens.config(text=f"{code} : {d.explication(code) or 'nuance sans explication officielle'}" if code else "")
        arbre.bind("<<TreeviewSelect>>", expliquer)
        ttk.Label(f, text="Déplie une liste pour voir tous ses colistiers (fichiers officiels du ministère de l'Intérieur). "
                          "Entre crochets : la nuance de la liste ; choisis une liste pour la voir en clair.",
                  style="Gris.TLabel", font=theme.POLICE_PETITE, wraplength=self.lt).pack(anchor="w", padx=14, pady=(2, 0))

    # ------------------------------------------------------------------ la carte : clic = fiche de la zone
    def clic_carte(self, evenement):
        coll = evenement.artist
        elu = None
        if hasattr(coll, "parlementaires") and len(getattr(evenement, "ind", [])):        # un siège d'un hémicycle
            chambre, ids = coll.parlementaires
            elu = (chambre, ids[evenement.ind[0]])
        elif hasattr(coll, "trombi") and evenement.mouseevent.xdata is not None:           # une photo du trombinoscope
            chambre, ids, lc, hc, nc = coll.trombi
            i = int(evenement.mouseevent.ydata // hc) * nc + int(evenement.mouseevent.xdata // lc)
            if 0 <= i < len(ids):
                elu = (chambre, ids[i])
        if elu:
            nom_vue, _, formes, reglages, precaution = self.vue()
            self.remplir_fiche(nom_vue, formes, self.ctx.forme, reglages, precaution, self.info, elu=elu)
            t_ = parlement.deputes() if elu[0] == "Assemblée nationale" else parlement.senateurs()
            e_ = t_.loc[elu[1]]
            self.popin(f"{e_['prenom']} {str(e_['nom']).upper()}", e_["groupe_libelle"] or e_["groupe"] if "groupe_libelle" in e_ else e_["groupe"],
                       e_["couleur"], str(e_["lieu"] or ""))
            return
        if hasattr(coll, "sieges_occupants") and len(getattr(evenement, "ind", [])):        # un siège de l'hémicycle calculé
            o = coll.sieges_occupants[evenement.ind[0]]
            self.popin(o["nom"], o["groupe"], o["couleur"], o["lieu"])
            self.etat.set(f"{o['nom']} — {o['groupe']}" + (f" — {o['lieu']}" if o["lieu"] else ""))
            return
        if hasattr(coll, "affiches") and evenement.mouseevent.xdata is not None:            # une affiche de la planche
            ids, lc, hc, nc = coll.affiches
            i = int(evenement.mouseevent.ydata // hc) * nc + int(evenement.mouseevent.xdata // lc)
            if 0 <= i < len(ids):
                nom_vue, _, formes, reglages, precaution = self.vue()
                self.remplir_fiche(nom_vue, formes, self.ctx.forme, reglages, precaution, self.info, affiche=ids[i])
            return
        if hasattr(coll, "votants") and len(getattr(evenement, "ind", [])):       # un siège de l'hémicycle d'un vote
            sid, ids = coll.votants
            nom_vue, _, formes, reglages, precaution = self.vue()
            self.remplir_fiche(nom_vue, formes, self.ctx.forme, reglages, precaution, self.info, votant=(sid, ids[evenement.ind[0]]))
            self.popin_votant(sid, ids[evenement.ind[0]])
            return
        if hasattr(coll, "scrutins_points") and len(evenement.ind):     # une pastille de scrutin (onglet Économie)
            scrutins = list(dict.fromkeys(coll.scrutins_points[i] for i in evenement.ind))
            nom_vue, _, formes, reglages, precaution = self.vue()
            self.remplir_fiche(nom_vue, formes, self.ctx.forme, reglages, precaution, self.info, scrutins_cliques=scrutins)
            self.etat.set("Scrutin cliqué : " + " · ".join(d.libelle(s) for s in scrutins))
            return
        if not hasattr(coll, "codes_zones") or not len(evenement.ind):
            return
        i = evenement.ind[0]
        code, nom, niveau = coll.codes_zones[i], coll.noms_zones[i], coll.niveau_zones
        zone = d.Zone(niveau, code, nom)
        if getattr(self, "surlignage", None) is not None and self.surlignage.axes is not None:
            self.surlignage.remove()
        formes = [p.vertices for p, c in zip(coll.get_paths(), coll.codes_zones) if c == code]
        self.surlignage = PolyCollection(formes, facecolors="none", edgecolors=C["texte"], linewidths=2.4, zorder=6)
        coll.axes.add_collection(self.surlignage)
        self.canvas.draw_idle()
        nom_vue, _, formes, reglages, precaution = self.vue()
        self.remplir_fiche(nom_vue, formes, self.ctx.forme, reglages, precaution, {"legende": [], "kpi": [], "lecture": ""}, detail=zone)
        self.etat.set(f"Zone cliquée : {nom}")

    # --- la comparaison de deux zones (onglet Comparer)
    def ajouter_comparaison(self, zone):
        if any(z.niveau == zone.niveau and z.code == zone.code for z in self.comparaison):
            self.etat.set(f"{zone.libelle} est déjà dans la comparaison.")
            return
        self.comparaison = (self.comparaison + [zone])[-2:]       # deux zones au plus : la plus ancienne s'en va
        if len(self.comparaison) == 2:
            self.choisir_vue("Comparer", 0)
            self.etat.set(f"⚖ {self.comparaison[0].libelle}  ⇄  {self.comparaison[1].libelle}")
        else:
            self.etat.set(f"⚖ Zone A : {zone.libelle} — clique (ou choisis) une 2e zone, puis « ⚖ Comparer ».")

    def vider_comparaison(self):
        self.comparaison = []
        self.tracer()

    def fiche_elu(self, f, chambre, indice):
        """La fiche d'un député ou d'un sénateur : photo, groupe, circonscription, âge, profession."""
        t = parlement.deputes() if chambre == "Assemblée nationale" else parlement.senateurs()
        e = t.loc[indice]
        self.intertitre(f, "Député(e)" if chambre == "Assemblée nationale" else "Sénateur / sénatrice")
        cadre = tk.Frame(f, bg=C["pale"], padx=10, pady=8)
        cadre.pack(anchor="w", padx=12, fill="x")
        try:
            im = Image.open(parlement.DOSSIER_PHOTOS / e["photo"])
            im.thumbnail((130, 160))
            self.photo_elu = ImageTk.PhotoImage(im)          # (gardée : sinon tkinter l'efface)
            tk.Label(cadre, image=self.photo_elu, bg=C["pale"]).pack(anchor="w", pady=(0, 6))
        except (OSError, FileNotFoundError):
            pass
        tk.Label(cadre, text=f"{e['civ']} {e['prenom']} {e['nom']}", bg=C["pale"], fg=C["texte"], font=theme.POLICE_GRAS).pack(anchor="w")
        groupe = tk.Frame(cadre, bg=C["pale"]); groupe.pack(anchor="w", pady=2)
        tk.Label(groupe, text="  ", bg=e["couleur"]).pack(side="left")
        tk.Label(groupe, text=f" {e['groupe_libelle'] or e['groupe']}", bg=C["pale"], fg=C["texte2"], font=theme.POLICE_PETITE,
                 wraplength=self.lt - 30, justify="left").pack(side="left")
        a = parlement.age(e["naissance"])
        lignes = [e["lieu"], f"{a} ans" if a else "", e.get("profession") or ""]
        if chambre == "Assemblée nationale" and e["place"] == e["place"]:
            lignes.append(f"place n° {e['place']} dans l'hémicycle")
        for l in lignes:
            if l:
                tk.Label(cadre, text=l, bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE, wraplength=self.lt, justify="left").pack(anchor="w")
        self.etat.set(f"{e['prenom']} {e['nom']} — {e['groupe']} — {e['lieu']}")

    def fiche_candidats(self, f, reglages):
        """Les photos libres des candidats (Wikimedia Commons), chacune avec son auteur et sa licence (obligatoire)."""
        if "candidat" in reglages:
            quis = [self.options.get(k) for k in ("candidat", "candidat2") if k in reglages and self.options.get(k)]
        else:
            quis = d.cles(self.ctx.scrutin, self.ctx.zone, self.ctx.regroupement, 6)
        gens = [p for q in quis for p in photos.photo(q)][:6]
        if not gens:
            return
        self.intertitre(f, "Les candidats en photo")
        grille = tk.Frame(f, bg=C["carte"])
        grille.pack(anchor="w", padx=12)
        self.photos_candidats = []                       # (gardées : sinon tkinter les efface)
        for i, p in enumerate(gens):
            case = tk.Frame(grille, bg=C["pale"], padx=5, pady=5)
            case.grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="nsew")
            try:
                im = Image.open(p["chemin"])
                im.thumbnail((130, 150))
                self.photos_candidats.append(ImageTk.PhotoImage(im))
                tk.Label(case, image=self.photos_candidats[-1], bg=C["pale"]).pack(anchor="w")
            except OSError:
                pass
            tk.Label(case, text=p["candidat"], bg=C["pale"], fg=C["texte"], font=theme.POLICE_GRAS, wraplength=self.lt // 2 - 20,
                     justify="left").pack(anchor="w")
            auteur = p["auteur"] if len(p["auteur"]) <= 50 else p["auteur"][:48] + "…"
            tk.Label(case, text=f"Photo : {auteur} · {p['licence']} · Wikimedia Commons", bg=C["pale"], fg=C["gris"],
                     font=theme.POLICE_PETITE, wraplength=self.lt // 2 - 20, justify="left").pack(anchor="w")

    def popin(self, nom, groupe, couleur_groupe, lieu="", badge="", couleur_badge=None, bord=None):
        """Une petite fenêtre près de la souris (gros texte) : le nom, le groupe (sa couleur), le lieu, et un badge (le vote…).
        Elle se ferme d'un clic, ou toute seule après 8 secondes. Sert aux hémicycles (votes, sièges, Parlement)."""
        if getattr(self, "fenetre_popin", None) is not None and self.fenetre_popin.winfo_exists():
            self.fenetre_popin.destroy()
        p = self.fenetre_popin = tk.Toplevel(self)
        p.overrideredirect(True)
        p.attributes("-topmost", True)
        cadre_bord = tk.Frame(p, bg=bord or couleur_groupe or C["primaire"], padx=4, pady=4); cadre_bord.pack()
        cadre = tk.Frame(cadre_bord, bg="white", padx=12, pady=8); cadre.pack()
        tk.Label(cadre, text=nom, bg="white", fg=C["texte"], font=theme.POLICE_FORT).pack(anchor="w")
        ligne = tk.Frame(cadre, bg="white"); ligne.pack(anchor="w", pady=(2, 0))
        tk.Label(ligne, text="  ", bg=couleur_groupe or C["gris"]).pack(side="left")
        tk.Label(ligne, text=f" {groupe}", bg="white", fg=C["texte2"], font=theme.POLICE).pack(side="left")
        if lieu:
            tk.Label(cadre, text=lieu, bg="white", fg=C["texte2"], font=theme.POLICE, wraplength=360, justify="left").pack(anchor="w")
        if badge:
            tk.Label(cadre, text=badge, bg=couleur_badge, fg=theme.texte_sur(couleur_badge), font=theme.POLICE_GRAS, padx=6).pack(anchor="w", pady=(6, 0))
        p.update_idletasks()
        x, y = self.winfo_pointerx() + 14, self.winfo_pointery() + 14
        x = min(x, self.winfo_screenwidth() - p.winfo_width() - 8); y = min(y, self.winfo_screenheight() - p.winfo_height() - 40)
        p.geometry(f"+{x}+{y}")
        for w in [p, cadre_bord, cadre] + list(cadre.winfo_children()) + list(ligne.winfo_children()):
            w.bind("<Button-1>", lambda ev: p.destroy())
        p.after(8000, lambda: p.winfo_exists() and p.destroy())

    def votant(self, sid, indice):
        t = legislatures.votes_complets(sid) if legislatures.disponible() else votes_deputes.votes(sid)
        return t.loc[indice]

    def popin_votant(self, sid, indice):
        e = self.votant(sid, indice)
        couleur = votes_deputes.POSITIONS.get(e["position"], votes_deputes.COULEUR_ABSENT)
        if not isinstance(e["depute"], str):
            self.popin("Député(e) absent(e)", "nom inconnu dans nos données", e["couleur"], "", e["position"].upper(), couleur, bord=C["gris"])
            return
        mots = e["depute"].split(" ", 1)
        nom = f"{mots[0]} {mots[1].upper()}" if len(mots) == 2 else e["depute"]       # « Mathilde PANOT »
        lieu = e["lieu"].replace(" circonscription ·", "") if isinstance(e.get("lieu"), str) else ""
        self.popin(nom, e["groupe"], e["couleur"], lieu, e["position"].upper(), couleur, bord=couleur)

    def fiche_votant(self, f, sid, indice):
        """Le député cliqué dans l'hémicycle d'un vote : sa photo (officielle s'il siège aujourd'hui, sinon libre), son groupe,
        son vote, et ce qu'il a voté aux autres grands votes."""
        e = self.votant(sid, indice)
        self.intertitre(f, "Député(e) cliqué(e)")
        if not isinstance(e["depute"], str):
            tk.Label(f, text=f"Siège d'un(e) député(e) {e['position']} : son nom n'est pas dans nos listes.", bg=C["carte"], fg=C["texte"],
                     font=theme.POLICE, wraplength=self.lt - 30, justify="left").pack(anchor="w", padx=12)
            return
        cadre = tk.Frame(f, bg=C["pale"], padx=10, pady=8)
        cadre.pack(anchor="w", padx=12, fill="x")
        # (sa photo officielle s'il siège aujourd'hui : même personne dans le modèle, plus de rapprochement par le nom)
        actuels = parlement.deputes() if parlement.disponible() else None
        pid = e.get("personne_id")
        officielle = actuels[actuels["personne_id"] == pid] if actuels is not None and pid == pid and pid is not None else []
        libre = photos.photo_nom(e["depute"])
        try:
            if len(officielle):
                im, credit = Image.open(parlement.DOSSIER_PHOTOS / officielle.iloc[0]["photo"]), "Photo : Assemblée nationale"
            elif libre:
                im, credit = Image.open(libre["chemin"]), f"Photo : {libre['auteur'][:48]} · {libre['licence']} · Wikimedia Commons"
            else:
                im = None
            if im is not None:
                im.thumbnail((130, 160))
                self.photo_votant = ImageTk.PhotoImage(im)          # (gardée : sinon tkinter l'efface)
                tk.Label(cadre, image=self.photo_votant, bg=C["pale"]).pack(anchor="w")
                tk.Label(cadre, text=credit, bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE, wraplength=self.lt - 30, justify="left").pack(anchor="w", pady=(0, 6))
        except OSError:
            pass
        tk.Label(cadre, text=e["depute"], bg=C["pale"], fg=C["texte"], font=theme.POLICE_GRAS).pack(anchor="w")
        ligne = tk.Frame(cadre, bg=C["pale"]); ligne.pack(anchor="w", pady=2)
        tk.Label(ligne, text="  ", bg=e["couleur"]).pack(side="left")
        tk.Label(ligne, text=f" {e['groupe']}", bg=C["pale"], fg=C["texte2"], font=theme.POLICE_PETITE, wraplength=self.lt - 30, justify="left").pack(side="left")
        if isinstance(e.get("lieu"), str) and e["lieu"]:
            tk.Label(cadre, text=e["lieu"], bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE, wraplength=self.lt - 30, justify="left").pack(anchor="w")
        tk.Label(cadre, text=(f"a voté : {e['position'].upper()}" if e["position"] not in votes_deputes.ABSENTS else e["position"].upper()),
                 bg=votes_deputes.POSITIONS.get(e["position"], votes_deputes.COULEUR_ABSENT),
                 fg=theme.texte_sur(votes_deputes.POSITIONS.get(e["position"], votes_deputes.COULEUR_ABSENT)), font=theme.POLICE_GRAS, padx=6, pady=2).pack(anchor="w", pady=4)
        autres = [(lib, pos) for lib, pos in votes_deputes.parcours(e.get("personne_id"), e["depute"]) if lib != votes_deputes.libelle(sid)]
        if autres:
            tk.Label(cadre, text="Ses autres grands votes :", bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE).pack(anchor="w", pady=(6, 0))
            for lib, pos in autres:
                tk.Label(cadre, text=f"{lib} : {pos}", bg=C["pale"], fg=votes_deputes.POSITIONS.get(pos, C["texte"]) if pos != "non-votant" else C["gris"],
                         font=theme.POLICE_PETITE, wraplength=self.lt, justify="left").pack(anchor="w")
        self.etat.set(f"{e['depute']} — {e['groupe']} — {e['position']}")

    def fiche_qui_sont_ils(self, f):
        """L'âge, la profession et « sortant » des premiers candidats du scrutin, quand les fichiers de candidatures les donnent."""
        if candidats._scrutin(self.ctx.scrutin) not in candidats.disponible():
            return
        lignes = []
        for qui in d.cles(self.ctx.scrutin, self.ctx.zone, "Candidat / liste", 10):
            c = candidats.de(qui, self.ctx.scrutin, self.ctx.zone)
            if c is None:
                continue
            bouts = [f"{int(c['age'])} ans" if c["age"] == c["age"] and c["age"] is not None else "",
                     str(c["profession"]) if c["profession"] else "", "sortant(e)" if str(c["sortant"]).upper() in ("OUI", "O", "VRAI") else ""]
            lignes.append((str(qui), " · ".join(b for b in bouts if b)))
        if not lignes:
            return
        self.intertitre(f, "Qui sont-ils ?")
        for qui, info in lignes:
            r = tk.Frame(f, bg=C["carte"]); r.pack(anchor="w", padx=14, pady=1, fill="x")
            tk.Label(r, text=court(qui, 30), bg=C["carte"], fg=C["texte"], font=theme.POLICE_GRAS, wraplength=self.lt, justify="left").pack(anchor="w")
            tk.Label(r, text=info, bg=C["carte"], fg=C["texte2"], font=theme.POLICE_PETITE, wraplength=self.lt, justify="left").pack(anchor="w")
        tk.Label(f, text="Source : fichiers de candidatures du ministère de l'Intérieur.", bg=C["carte"], fg=C["gris"],
                 font=theme.POLICE_PETITE, wraplength=self.lt).pack(anchor="w", padx=14, pady=(2, 0))

    def fiche_affiches_candidats(self, f):
        """Les affiches (Hauts-de-Seine) des candidats de ce scrutin, quand il y en a : même élection, même année, leur nom dessus."""
        if not affiches.disponible():
            return
        type_, an = d.type_de(self.ctx.scrutin), int(self.ctx.scrutin[:4])
        t = affiches.tout()
        t = t[(t["type"] == type_) & (t["annee"] == an)]
        if t.empty:
            return
        trouvees = []
        for qui in d.cles(self.ctx.scrutin, d.FRANCE, "Candidat / liste", 12):
            nom = d.normaliser(str(qui).split()[-1]) if str(qui).split() else ""
            if len(nom) >= 3:
                trouvees += [(qui, i) for i in t.index[t["texte"].str.contains(rf"{nom}", regex=True)][:1]]
        if not trouvees:
            return
        self.intertitre(f, "Leurs affiches (Hauts-de-Seine)")
        grille = tk.Frame(f, bg=C["carte"]); grille.pack(anchor="w", padx=12)
        self.photos_affiches_c = []
        for k, (qui, i) in enumerate(trouvees[:6]):
            case = tk.Frame(grille, bg=C["pale"], padx=4, pady=4)
            case.grid(row=k // 3, column=k % 3, padx=2, pady=2, sticky="nw")
            try:
                im = Image.open(affiches.DOSSIER / f"{affiches.tout().loc[i, 'identifiant']}.jpg")
                im.thumbnail((self.lt // 3 - 14, int(self.lt // 3 * 1.4)))
                self.photos_affiches_c.append(ImageTk.PhotoImage(im))
                l = tk.Label(case, image=self.photos_affiches_c[-1], bg=C["pale"], cursor="hand2")
                l.pack()
                theme.cliquable(l, lambda i=i: self.remplir_fiche(*self.vue()[:1], self.vue()[2], self.ctx.forme, self.vue()[3],
                                                                   self.vue()[4], self.info, affiche=i))
            except OSError:
                pass
            tk.Label(case, text=court(str(qui), 18), bg=C["pale"], fg=C["texte"], font=theme.POLICE_PETITE).pack(anchor="w")
        tk.Label(f, text=affiches.CREDIT + " · clic = en grand", bg=C["carte"], fg=C["gris"], font=theme.POLICE_PETITE,
                 wraplength=self.lt, justify="left").pack(anchor="w", padx=14, pady=(2, 0))

    def fiche_affiche(self, f, indice):
        """L'affiche cliquée, en grand dans le panneau (entière : licence « pas de modification »), sa fiche d'archives et sa source."""
        a = affiches.tout().loc[indice]
        self.intertitre(f, "Affiche cliquée")
        cadre = tk.Frame(f, bg=C["pale"], padx=10, pady=8)
        cadre.pack(anchor="w", padx=12, fill="x")
        chemin = affiches.DOSSIER / f"{a['identifiant']}.jpg"
        try:
            im = Image.open(chemin)
            im.thumbnail((self.lt, int(self.lt * 1.5)))
            self.photo_affiche = ImageTk.PhotoImage(im)          # (gardée : sinon tkinter l'efface)
            tk.Label(cadre, image=self.photo_affiche, bg=C["pale"]).pack(anchor="w", pady=(0, 6))
        except OSError:
            pass
        tk.Label(cadre, text=f"{a['type']}{' partielles' if a['partielle'] else ''} · {a['annee']} · {a['lieu']}", bg=C["pale"],
                 fg=C["texte"], font=theme.POLICE_GRAS, wraplength=self.lt - 20, justify="left").pack(anchor="w")
        if a["candidats"]:
            tk.Label(cadre, text="Noms sur l'affiche : " + a["candidats"], bg=C["pale"], fg=C["texte2"], font=theme.POLICE_PETITE,
                     wraplength=self.lt - 20, justify="left").pack(anchor="w", pady=(4, 0))
        tk.Label(cadre, text=a["description"], bg=C["pale"], fg=C["texte2"], font=theme.POLICE_PETITE, wraplength=self.lt - 20,
                 justify="left").pack(anchor="w", pady=(4, 0))
        tk.Label(cadre, text=f"Cote {a['cote']} · fonds {a['fonds']}\n{affiches.CREDIT}", bg=C["pale"], fg=C["gris"],
                 font=theme.POLICE_PETITE, wraplength=self.lt - 20, justify="left").pack(anchor="w", pady=(6, 0))
        boutons = tk.Frame(cadre, bg=C["pale"]); boutons.pack(anchor="w", pady=(8, 0))
        ttk.Button(boutons, text="🔍 Ouvrir en grand", style="Clair.TButton", command=lambda: os.startfile(chemin)).pack(anchor="w")
        ttk.Button(boutons, text="🌐 L'original (site des Archives)", style="Clair.TButton",
                   command=lambda: webbrowser.open(a["adresse"])).pack(anchor="w", pady=(4, 0))
        self.etat.set(f"{a['type']} {a['annee']} · {a['lieu']} · {a['candidats'] or ''}")

    def fiche_scrutins(self, f, scrutins):
        """Le résultat national des scrutins cliqués, et la valeur de l'indicateur la veille du vote."""
        self.intertitre(f, "Scrutin cliqué")
        veille = d.veille().set_index("scrutin")
        mesure = self.ctx.nuage["y"]["mesure"] if self.ctx.nuage else None
        col = d.MESURES_ECO.get(mesure)
        for s in scrutins:
            cadre = tk.Frame(f, bg=C["pale"], padx=10, pady=8)
            cadre.pack(anchor="w", padx=12, pady=(0, 6), fill="x")
            tk.Label(cadre, text="🗳 " + d.libelle(s), bg=C["pale"], fg=C["texte"], font=theme.POLICE_GRAS, wraplength=self.lt, justify="left").pack(anchor="w")
            ligne = f"{veille.loc[s, 'date']:%d/%m/%Y}" if s in veille.index else ""
            if col and s in veille.index and veille.loc[s, col] == veille.loc[s, col]:
                ligne += f" · {mesure} la veille : {g.fmt(veille.loc[s, col], 2, '')}"
            t = d.totaux(s, d.FRANCE)
            ligne += f"\nFrance · participation {g.fmt(t['Participation'])}"
            tk.Label(cadre, text=ligne, bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE, justify="left", wraplength=self.lt).pack(anchor="w")
            # élection locale : au niveau national, seules les nuances ont un sens (chaque commune a ses candidats)
            regroupement = "Candidat / liste" if d.type_de(s) in d.TYPES_NATIONAUX else "Nuance"
            for row in d.resultats(s, d.FRANCE, regroupement).head(6).itertuples():
                tk.Label(cadre, text=f"{court(row.qui, 30)}   {g.fmt(row.pct)}", bg=C["pale"], fg=C["texte2"], font=theme.POLICE_PETITE).pack(anchor="w")
            ttk.Button(cadre, text="🗳 Choisir ce scrutin", style="Action.TButton", command=lambda s=s: self.choisir_scrutin(s)).pack(anchor="w", pady=(6, 0))

    def choisir_scrutin(self, scrutin):
        r = d.scrutins().set_index("scrutin").loc[scrutin]
        self.cb_type.set(r["type"]); self.cb_annee.set(d.annee_de(scrutin))
        self.cb_tour.set("Tour unique" if r["type"] in d.UN_SEUL_TOUR else d.NOMS_TOURS[int(r["tour"])])
        self.maj_regles_scrutin("type")

    def fiche_detail(self, f, zone):
        self.intertitre(f, "Zone cliquée")
        cadre = tk.Frame(f, bg=C["pale"], padx=10, pady=8)
        cadre.pack(anchor="w", padx=12, fill="x")
        tk.Label(cadre, text="📍 " + zone.libelle, bg=C["pale"], fg=C["texte"], font=theme.POLICE_GRAS, wraplength=self.lt, justify="left").pack(anchor="w")
        t = d.totaux(self.ctx.scrutin, zone)
        if not (t["inscrits"] == t["inscrits"] and t["inscrits"]):       # NaN ou 0 : rien pour ce scrutin ici
            tk.Label(cadre, text=f"Pas de résultat ici pour {d.libelle(self.ctx.scrutin)} (pas de 2nd tour, ou bureau renuméroté).",
                     bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE, wraplength=self.lt, justify="left").pack(anchor="w")
        else:
            tk.Label(cadre, text=f"Inscrits {int(t['inscrits']):,} · participation {g.fmt(t['Participation'])}".replace(",", " "),
                     bg=C["pale"], fg=C["gris"], font=theme.POLICE_PETITE).pack(anchor="w")
        for row in d.resultats(self.ctx.scrutin, zone, self.ctx.regroupement).head(6).itertuples():
            tk.Label(cadre, text=f"{court(row.qui, 30)}   {g.fmt(row.pct)}", bg=C["pale"], fg=C["texte2"], font=theme.POLICE_PETITE).pack(anchor="w")
        boutons = tk.Frame(cadre, bg=C["pale"])
        boutons.pack(anchor="w", pady=(6, 0))
        ttk.Button(boutons, text="📍 Choisir comme zone", style="Action.TButton", command=lambda: self.choisir_zone(zone)).pack(side="left")
        ttk.Button(boutons, text="⚖ Comparer", style="Clair.TButton", command=lambda: self.ajouter_comparaison(zone)).pack(side="left", padx=6)
        if theme.ZOOM > 1.05:          # textes agrandis : les deux boutons l'un sous l'autre (sinon le 2e sort du panneau)
            for i, w in enumerate(boutons.winfo_children()):
                w.pack_configure(side="top", anchor="w", padx=0, pady=(0, 4))


def court(texte, n):
    return g.court(texte, n)


def lancer():
    try:   # Windows : une fenêtre nette sur les écrans agrandis (125 %, 150 %…)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        app = Application()
    except FileNotFoundError as erreur:
        racine = tk.Tk(); racine.withdraw()
        messagebox.showerror(theme.NOM_APPLI, str(erreur))
        return
    if os.environ.get("GD_TEST"):
        from interface.autotest import autotest
        app.after(800, autotest, app, os.environ["GD_TEST"])
    app.mainloop()
