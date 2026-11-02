"""
theme.py — Le thème du Grand Dépouillement : couleurs, polices, styles ttk et thème matplotlib.

Tout le reste de l'appli prend ses couleurs ICI. Pour changer l'allure de l'appli, on change ce fichier.

    from interface import theme
    theme.appliquer(fenetre)          # styles ttk + thème matplotlib
    tk.Label(..., bg=theme.C["primaire"], font=theme.POLICE_TITRE)
"""

import json
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import matplotlib as mpl
import seaborn as sns

NOM_APPLI = "Le Grand Dépouillement"

# --- Palette « Marianne » : chaque couleur a un RÔLE (comme dans l'atelier) -----------------
C = {
    "primaire": "#000091",     # bleu France : bandeau, éléments actifs
    "moyen": "#6A6AF4",
    "doux": "#C1C1FB",
    "clair": "#E3E3FD",        # fond d'un élément choisi
    "pale": "#F5F5FE",         # fond des volets et des bandes
    "action": "#E1000F",       # rouge : le bouton qui agit
    "action_clair": "#FFE9E9",
    "orange": "#FC5D00",
    "succes": "#18753C",
    "texte": "#161616",
    "texte2": "#3A3A3A",
    "gris": "#505050",         # texte secondaire : 8 : 1 sur blanc (malvoyants : jamais de gris pâle pour du texte)
    "bordure": "#DDDDDD",      # séparations décoratives seulement (pas les champs)
    "bordure_champ": "#767676",  # contour des champs et boutons : 4,5 : 1 (WCAG 1.4.11)
    "focus": "#FC5D00",        # liseré du focus clavier (bien visible sur blanc ET sur le bleu)
    "surface": "#F6F6F6",      # barre d'état, réglages
    "carte": "#FFFFFF",        # fond des cartes et des champs
    "fond": "#FFFFFF",
    "sur": "#FFFFFF",          # texte posé sur une couleur
}
# Les séries des graphiques, dans l'ordre (la 1re = la plus importante)
# (toutes ≥ 3 : 1 sur le fond blanc, WCAG 1.4.11 : les teintes restent, les plus pâles sont seulement foncées)
SERIES = [C["primaire"], C["action"], C["orange"], C["succes"], C["moyen"], "#A558A0", "#009081", "#A67C00", "#7D4E5B", "#6B8E23",
          "#5770BE", "#C0583F", "#5C4B8A", "#857650", C["gris"]]
# Une couleur fixe par type d'élection, la même partout
TYPES_ELECTION = {"Présidentielle": C["primaire"], "Législatives": C["action"], "Européennes": "#A67C00", "Municipales": C["succes"],
                  "Régionales": "#A558A0", "Départementales": C["orange"], "Cantonales": C["gris"], "Référendum": "#009081",
                  "Sénatoriales": "#6D4C41"}

# --- Couleurs politiques (les usages des résultats officiels et de la presse) ---------------------
# Une famille = une couleur ; chaque code de nuance du ministère pointe vers sa famille.
# Pour corriger une couleur : change-la dans FAMILLES. Pour un code oublié : ajoute-le dans NUANCES.
FAMILLES = {
    "extrême gauche": "#8B0000", "communiste": "#D40000", "insoumis": "#CC2443", "union de la gauche": "#E4007C",
    "socialiste": "#F07AA8", "divers gauche": "#F7B5C9", "écologiste": "#2E9E47", "régionaliste": "#A0522D",
    "divers": "#B8B8B8", "centre / majorité": "#FFC20E", "divers centre": "#FF9A2E", "centre droit": "#3FA9F5",
    "droite": "#0055A4", "divers droite": "#7FAEE0", "souverainiste": "#5B3F8C", "extrême droite": "#0D2C54",
    "reconquête": "#3B2A20", "union extrême droite": "#23305E", "ruralité": "#8D6E63",
    "oui": "#1F9D55", "non": "#C62828",       # les référendums
}
_F = FAMILLES
NUANCES = {   # codes du ministère (le « L » des listes et le « BC- » des binômes sont enlevés avant de chercher)
    **dict.fromkeys(["EXG", "XG", "DXG", "LO", "LCR", "LAGU", "ARTH", "BESA", "POUT", "GLUC", "SCHI"], _F["extrême gauche"]),
    **dict.fromkeys(["COM", "PC", "PCF", "FG", "PG", "HUE", "BUFF", "COP"], _F["communiste"]),
    **dict.fromkeys(["FI", "MELE"], _F["insoumis"]),
    **dict.fromkeys(["UG", "NUP", "UGE", "GAU", "UCG", "GA"], _F["union de la gauche"]),
    **dict.fromkeys(["SOC", "PS", "JOSP", "ROYA", "HOLL", "TAUB", "PRG", "RDG", "RG", "MDC", "CHEV"], _F["socialiste"]),
    **dict.fromkeys(["DVG", "DG", "GC"], _F["divers gauche"]),
    **dict.fromkeys(["ECO", "VEC", "VE", "VEG", "EC", "MAME", "VOYN", "JOLY", "BOVE", "LEPA"], _F["écologiste"]),
    **dict.fromkeys(["REG"], _F["régionaliste"]),
    **dict.fromkeys(["DIV", "AUT", "DV", "GJ", "CHEM", "MNA"], _F["divers"]),
    **dict.fromkeys(["ENS", "REM", "REN", "MDM", "MODM", "BAYR", "UDF", "UDFD", "UC", "HOR", "MP", "MC"], _F["centre / majorité"]),
    **dict.fromkeys(["DVC", "CEN"], _F["divers centre"]),
    **dict.fromkeys(["UDI", "NCE", "ALLI", "UCD", "PRV", "MADE", "DL", "LCMD"], _F["centre droit"]),
    **dict.fromkeys(["LR", "UMP", "RPR", "UD", "UDR", "MAJ", "M", "M-NC", "CHIR", "SARK", "BOUT", "DR"], _F["droite"]),
    **dict.fromkeys(["DVD", "DD"], _F["divers droite"]),
    **dict.fromkeys(["DSV", "DLF", "DLR", "MPF", "RPF", "VILL", "DUPO"], _F["souverainiste"]),
    **dict.fromkeys(["FN", "RN", "FRN", "LEPE", "EXD", "XD", "DXD", "MNR", "MEGR"], _F["extrême droite"]),
    **dict.fromkeys(["REC"], _F["reconquête"]),
    **dict.fromkeys(["UXD"], _F["union extrême droite"]),
    **dict.fromkeys(["CPNT", "CP", "SAIN", "NIHO"], _F["ruralité"]),
    "OUI": _F["oui"], "NON": _F["non"],
    # les codes officiels d'avant 1999 (CDSP, ministère) : leur couleur seulement — l'étiquette reste le code officiel
    **dict.fromkeys(["PSU"], _F["extrême gauche"]), **dict.fromkeys(["SFIO", "FGDS", "MRG"], _F["socialiste"]),
    **dict.fromkeys(["RADSOC", "RADUFD", "UFD"], _F["divers gauche"]), **dict.fromkeys(["GEC"], _F["écologiste"]),
    **dict.fromkeys(["MRP", "MRPVREP", "CENTDEM", "CDP", "CDPURP", "CPDM", "RADCENT", "REFRAD", "DIVREF", "CRR", "UDSRMIN", "ALLREP"],
                    _F["centre / majorité"]),
    **dict.fromkeys(["RI", "RIURP", "RADDROIT", "MOD", "INDVREP"], _F["centre droit"]),
    **dict.fromkeys(["UNR", "UNR-UDT", "UDRURP", "UDR-RI", "UD5", "DIVGAUL", "DIVGAULL", "DIVURP", "DIVMAJ", "RALLIE"], _F["droite"]),
    **dict.fromkeys(["CNI"], _F["divers droite"]), **dict.fromkeys(["POUJ"], _F["extrême droite"]),
}
# Quand il n'y a pas de nuance (présidentielles récentes, européennes 2019…) : un mot du nom du candidat ou de la liste.
MOTS_POLITIQUES = [
    ("LE PEN", _F["extrême droite"]), ("BARDELLA", _F["extrême droite"]), ("FRANCE REVIENT", _F["extrême droite"]),
    ("PRENEZ LE POUVOIR", _F["extrême droite"]), ("ZEMMOUR", _F["reconquête"]), ("MARECHAL", _F["reconquête"]),
    ("MACRON", _F["centre / majorité"]), ("RENAISSANCE", _F["centre / majorité"]), ("BESOIN D EUROPE", _F["centre / majorité"]),
    ("HAYER", _F["centre / majorité"]), ("LOISEAU", _F["centre / majorité"]), ("BAYROU", _F["centre / majorité"]),
    ("MELENCHON", _F["insoumis"]), ("INSOUMISE", _F["insoumis"]), ("LFI", _F["insoumis"]),
    ("FILLON", _F["droite"]), ("PECRESSE", _F["droite"]), ("SARKOZY", _F["droite"]), ("CHIRAC", _F["droite"]),
    ("BELLAMY", _F["droite"]), ("UNION DROITE", _F["droite"]), ("LA DROITE", _F["droite"]),
    ("HAMON", _F["socialiste"]), ("HIDALGO", _F["socialiste"]), ("HOLLANDE", _F["socialiste"]), ("ROYAL", _F["socialiste"]),
    ("JOSPIN", _F["socialiste"]), ("GLUCKSMANN", _F["socialiste"]), ("REVEIL EUR", _F["socialiste"]), ("ENVIE D EUROPE", _F["socialiste"]),
    ("JADOT", _F["écologiste"]), ("ECOLOGIE", _F["écologiste"]), ("TOUSSAINT", _F["écologiste"]),
    ("ROUSSEL", _F["communiste"]), ("GAUCHE UNIE", _F["communiste"]), ("DEFFONTAINES", _F["communiste"]),
    ("DUPONT AIGNAN", _F["souverainiste"]), ("DEBOUT LA FRANCE", _F["souverainiste"]), ("ASSELINEAU", _F["souverainiste"]),
    ("ARTHAUD", _F["extrême gauche"]), ("POUTOU", _F["extrême gauche"]), ("LUTTE OUVRIERE", _F["extrême gauche"]),
    ("LASSALLE", _F["ruralité"]),
]


# Avant 2002 (Cagé-Piketty), la « nuance » est le nom d'une famille ; ces noms-là ont la couleur d'une famille d'aujourd'hui
FAMILLES_ANCIENNES = {"centre": "centre / majorité", "radicaux": "divers gauche", "gaullistes et droite": "droite",
                      "nationalistes": "extrême droite", "agrariens": "ruralité"}

# L'ordre de gauche à droite dans un hémicycle (les « oui / non » des référendums n'y vont pas)
ORDRE_FAMILLES = ["extrême gauche", "communiste", "insoumis", "union de la gauche", "socialiste", "divers gauche", "écologiste",
                  "régionaliste", "divers", "ruralité", "centre / majorité", "divers centre", "centre droit", "droite", "divers droite",
                  "souverainiste", "union extrême droite", "extrême droite", "reconquête"]
FAMILLE_DE_COULEUR = {v: k for k, v in FAMILLES.items()}


# Les grands blocs, pour savoir si une zone a « changé de camp » (une liste UD devenue UCD n'a pas basculé)
BLOCS = {"gauche": ["extrême gauche", "communiste", "insoumis", "union de la gauche", "socialiste", "divers gauche", "écologiste"],
         "droite et centre": ["centre / majorité", "divers centre", "centre droit", "droite", "divers droite", "souverainiste"],
         "extrême droite": ["union extrême droite", "extrême droite", "reconquête"],
         "divers": ["divers", "régionaliste", "ruralité"]}
BLOC_DE_FAMILLE = {f: b for b, fs in BLOCS.items() for f in fs}
COULEURS_BLOCS = {"gauche": FAMILLES["socialiste"], "droite et centre": FAMILLES["droite"],
                  "extrême droite": FAMILLES["extrême droite"], "divers": "#B8BEC6"}


def bloc_politique(texte, mots=False):
    """« gauche », « droite et centre », « extrême droite » ou « divers » (inconnu compris)."""
    return BLOC_DE_FAMILLE.get(FAMILLE_DE_COULEUR.get(couleur_politique(texte, mots)), "divers")


def rang_politique(texte, mots=True):
    """Sa place de gauche (0) à droite dans l'hémicycle ; les inconnus au milieu, avec les divers."""
    f = FAMILLE_DE_COULEUR.get(couleur_politique(texte, mots))
    return ORDRE_FAMILLES.index(f) if f in ORDRE_FAMILLES else ORDRE_FAMILLES.index("divers")


def couleur_politique(texte, mots=True):
    """La couleur politique d'un code de nuance (« LRN », « BC-SOC »…) ou, si mots=True, d'un nom (« Marine LE PEN »), sinon None."""
    if not texte:
        return None
    t = str(texte).strip().upper()
    famille = FAMILLES_ANCIENNES.get(t.lower(), t.lower())       # les scrutins d'avant 2002 : le nom de la famille
    if famille in FAMILLES:
        return FAMILLES[famille]
    if t.startswith("BC-"):
        t = t[3:]
    if t in NUANCES:
        return NUANCES[t]
    if t.startswith("L") and t[1:] in NUANCES:
        return NUANCES[t[1:]]
    if not mots:
        return None
    import unicodedata
    mots = "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")
    mots = " " + " ".join(mots.replace("-", " ").replace("'", " ").replace("’", " ").split()) + " "
    for mot, couleur in MOTS_POLITIQUES:
        if f" {mot} " in mots:
            return couleur
    return None

# --- Polices (installées sous Windows) --------------------------------------------------------
# Tailles de base (en points) ; le ZOOM (boutons A− / A+, Ctrl + / Ctrl − / Ctrl 0) les multiplie toutes, et le choix est gardé.
FAMILLE = "Segoe UI"
TAILLES = {"POLICE": (11, "normal"), "POLICE_PETITE": (10, "normal"), "POLICE_GRAS": (11, "bold"), "POLICE_INTER": (10, "bold"),
           "POLICE_FORT": (13, "bold"), "POLICE_TITRE": (16, "bold"), "POLICE_LOGO": (16, "bold"), "POLICE_CHIFFRE": (16, "bold")}
# avant la fenêtre : des tuples ; appliquer() les remplace par de vraies polices tkinter (que le zoom agrandit en direct)
for _nom, (_t, _g) in TAILLES.items():
    globals()[_nom] = (FAMILLE, _t, _g)
ZOOM = 1.0
ZOOMS = [0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0]
PREFERENCES = Path.home() / ".grand_depouillement.json"


def lire_zoom():
    try:
        return float(json.loads(PREFERENCES.read_text(encoding="utf-8")).get("zoom", 1.0))
    except (OSError, ValueError):
        return 1.0


def zoomer(facteur):
    """Change la taille de TOUS les textes (fenêtre et graphiques) ; le graphique est à redessiner ensuite."""
    global ZOOM
    ZOOM = facteur
    for nom, (taille, graisse) in TAILLES.items():
        police = globals()[nom]
        if isinstance(police, tkfont.Font):
            police.configure(size=round(taille * facteur))
    for nom in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(nom).configure(size=round(TAILLES["POLICE"][0] * facteur))
        except tk.TclError:
            pass
    appliquer_matplotlib()
    try:
        PREFERENCES.write_text(json.dumps({"zoom": facteur}), encoding="utf-8")
    except OSError:
        pass


def contraste(a, b):
    """Le rapport de contraste WCAG entre deux couleurs (1 à 21 ; 4,5 = minimum AA pour du texte)."""
    def lum(c):
        f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b_ = mpl.colors.to_rgb(c)
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b_)
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def texte_sur(fond):
    """La couleur de texte la plus lisible sur ce fond : presque noir ou blanc (WCAG 1.4.3), plutôt que blanc partout."""
    return C["sur"] if contraste(C["sur"], fond) >= contraste(C["texte"], fond) else C["texte"]

# --- Espacements --------------------------------------------------------------------------------
MARGE = 12
ESPACE = 8


def appliquer(racine):
    """Styles ttk + thème matplotlib. À appeler une fois, juste après la création de la fenêtre."""
    global ZOOM
    racine.configure(bg=C["fond"])
    # les polices deviennent de vraies polices tkinter : le zoom les agrandit partout d'un coup
    ZOOM = lire_zoom()
    for nom, (taille, graisse) in TAILLES.items():
        globals()[nom] = tkfont.Font(racine, family=FAMILLE, size=round(taille * ZOOM), weight=graisse)
    # la police par défaut de TOUS les widgets (sans écraser les polices des styles ttk ci-dessous)
    for nom in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(nom).configure(family=FAMILLE, size=round(TAILLES["POLICE"][0] * ZOOM))
    s = ttk.Style(racine)
    s.theme_use("clam")
    s.configure(".", font=POLICE, background=C["fond"], foreground=C["texte"])
    s.configure("TFrame", background=C["fond"])
    s.configure("Pale.TFrame", background=C["pale"])
    s.configure("Surface.TFrame", background=C["surface"])
    s.configure("TLabel", background=C["fond"], foreground=C["texte"])
    s.configure("Pale.TLabel", background=C["pale"])
    s.configure("Libelle.TLabel", background=C["pale"], foreground=C["gris"], font=POLICE_INTER)
    s.configure("Titre.TLabel", font=POLICE_TITRE)
    s.configure("Gris.TLabel", foreground=C["gris"])
    s.configure("Inter.TLabel", foreground=C["primaire"], font=POLICE_INTER)
    s.configure("Etat.TLabel", background=C["surface"], foreground=C["texte2"], font=POLICE_PETITE, padding=(MARGE, 5))
    s.configure("TCombobox", fieldbackground=C["carte"], background=C["carte"], bordercolor=C["bordure_champ"],
                lightcolor=C["carte"], darkcolor=C["carte"], arrowcolor=C["primaire"], arrowsize=16, padding=5)
    s.map("TCombobox", fieldbackground=[("readonly", C["carte"]), ("disabled", C["surface"])],
          foreground=[("disabled", C["gris"])], bordercolor=[("focus", C["focus"])], lightcolor=[("focus", C["focus"])],
          darkcolor=[("focus", C["focus"])])
    s.configure("TEntry", fieldbackground=C["carte"], bordercolor=C["bordure_champ"], lightcolor=C["carte"], darkcolor=C["carte"], padding=5)
    s.map("TEntry", bordercolor=[("focus", C["focus"])], lightcolor=[("focus", C["focus"])], darkcolor=[("focus", C["focus"])])
    s.configure("Action.TButton", background=C["action"], foreground=C["sur"], font=POLICE_GRAS, borderwidth=0, padding=(12, 6))
    s.map("Action.TButton", background=[("active", "#B60000")])
    s.configure("Action.TButton", focuscolor=C["sur"])
    s.configure("Clair.TButton", background=C["clair"], foreground=C["primaire"], borderwidth=1, bordercolor=C["moyen"],
                lightcolor=C["clair"], darkcolor=C["clair"], padding=(10, 5), focuscolor=C["focus"])
    s.map("Clair.TButton", background=[("active", C["doux"])])
    s.configure("Treeview", background=C["carte"], fieldbackground=C["carte"], bordercolor=C["bordure_champ"],
                rowheight=int(TAILLES["POLICE"][0] * 2.4 * ZOOM))
    s.configure("Treeview.Heading", background=C["surface"], foreground=C["texte2"], font=POLICE_INTER, relief="flat")
    s.map("Treeview", background=[("selected", C["clair"])], foreground=[("selected", C["primaire"])])
    # l'ascenseur : un curseur gris moyen bien visible (3 : 1) sur un rail clair
    s.configure("Vertical.TScrollbar", background="#8A8A8A", troughcolor=C["surface"], bordercolor=C["surface"], arrowcolor=C["texte"],
                arrowsize=16)
    s.map("Vertical.TScrollbar", background=[("active", C["gris"])])
    s.configure("TScale", background=C["fond"], troughcolor=C["clair"])
    racine.option_add("*TCombobox*Listbox.font", POLICE)
    racine.option_add("*TCombobox*Listbox.selectBackground", C["clair"])
    racine.option_add("*TCombobox*Listbox.selectForeground", C["primaire"])
    appliquer_matplotlib()


def appliquer_matplotlib():
    """Le thème des graphiques (seaborn + matplotlib), assorti à l'appli : fond blanc, grille légère, Segoe UI, couleurs Marianne."""
    sns.set_theme(style="whitegrid", palette=SERIES, font=FAMILLE)
    z = ZOOM
    mpl.rcParams.update({
        "font.family": FAMILLE, "font.size": 10 * z,
        "axes.facecolor": C["carte"], "figure.facecolor": C["carte"], "savefig.facecolor": C["carte"],
        "axes.edgecolor": "#8A8A8A", "axes.labelcolor": C["texte2"], "axes.titlesize": 13 * z, "axes.labelsize": 10 * z, "axes.titleweight": "bold",
        "axes.titlecolor": C["texte"], "axes.titlelocation": "left", "axes.titlepad": 10,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.axisbelow": True,
        "grid.color": "#E2E2E2", "grid.linewidth": 0.8,      # (la grille est décorative : les valeurs sont écrites)
        "xtick.color": C["texte2"], "ytick.color": C["texte2"], "xtick.labelsize": 9.5 * z, "ytick.labelsize": 9.5 * z,
        "legend.frameon": False, "legend.fontsize": 9.5 * z,
        "axes.prop_cycle": mpl.cycler(color=SERIES),
    })


def bouton_plat(parent, texte, commande, fond=None, couleur=None, gras=False, **kw):
    """Un bouton plat (tk.Label cliquable) : sert pour les pilules de la barre bleue, les pastilles, les onglets."""
    fond = fond or C["carte"]
    b = tk.Label(parent, text=texte, bg=fond, fg=couleur or C["primaire"], font=POLICE_GRAS if gras else POLICE,
                 cursor="hand2", padx=12, pady=5, **kw)
    return cliquable(b, commande)


def cliquable(widget, commande):
    """Un Label qui sert de bouton devient utilisable AU CLAVIER : Tab pour l'atteindre, Entrée ou Espace pour l'activer,
    et un liseré orange quand il a le focus (WCAG 2.1.1 et 2.4.7). La souris marche comme avant."""
    epaisseur = int(widget.cget("highlightthickness") or 0)
    if epaisseur == 0:                       # pas de liseré à lui : on en met un, invisible (couleur du fond) sans le focus
        widget.configure(highlightbackground=widget.cget("bg"))
    widget.configure(takefocus=1, highlightcolor=C["focus"], highlightthickness=max(2, epaisseur))
    for touche in ("<Button-1>", "<Return>", "<space>", "<KP_Enter>"):
        widget.bind(touche, lambda e=None: commande())      # (e=None : tkinter appelle parfois sans événement)
    return widget


def infobulle(widget, texte):
    """Une info-bulle sur un widget : au survol de la souris, ou quand il a le focus du clavier (Tab) — WCAG 1.4.13 :
    elle reste tant que la souris est dessus, Échap la ferme."""
    bulle = {}

    def montrer(_e=None):
        if bulle or not texte:
            return
        x, y = widget.winfo_rootx() + 12, widget.winfo_rooty() + widget.winfo_height() + 4
        t = tk.Toplevel(widget)
        t.wm_overrideredirect(True)
        t.wm_geometry(f"+{x}+{y}")
        tk.Label(t, text=texte, bg=C["carte"], fg=C["texte"], font=POLICE_PETITE, padx=8, pady=4, justify="left",
                 wraplength=360, highlightthickness=1, highlightbackground=C["primaire"]).pack()
        bulle["t"] = t

    def cacher(_e=None):
        if bulle:
            bulle.pop("t").destroy()
    widget.configure(takefocus=1)
    widget.bind("<Enter>", montrer, add="+")
    widget.bind("<FocusIn>", montrer, add="+")
    widget.bind("<Leave>", cacher, add="+")
    widget.bind("<FocusOut>", cacher, add="+")
    widget.bind("<Escape>", cacher, add="+")
    return widget
