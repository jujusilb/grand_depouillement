"""
graphiques_partis.py — Les vues de l'onglet Partis : la fiche d'un parti (avec ses logos), les plus anciens, les partis des
grandes lois, les écoles et les personnalités de leurs adhérents, les coalitions. Mêmes règles que graphiques.py : une
fonction = une vue, qui reçoit la figure et le contexte, dessine, et rend {"legende", "kpi", "lecture"} ; les données
passent par donnees() pour l'export texte / CSV.
"""
import numpy as np
import pandas as pd
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from PIL import Image

from graphiques.graphiques import T, court, donnees, titre, vide
from interface.theme import C, SERIES
from politique import partis as P

AUJOURD_HUI = pd.Timestamp.today().normalize()


def _pas_de_partis(fig):
    return vide(fig, "Les partis ne sont pas dans la base : lance 3_base/modele/integrer_partis.py.")


def _parti_choisi(ctx):
    choix = P.choix()
    return choix.get(ctx.options.get("parti")) or next(iter(choix.values()))      # (comme la liste : le plus présent d'abord)


def _image(ax, fichier, xy, zoom, boite="axes fraction"):
    with Image.open(fichier) as im:
        im = np.asarray(im.convert("RGBA"))
    ax.add_artist(AnnotationBbox(OffsetImage(im, zoom=zoom), xy, xycoords=boite, frameon=False))


def _an(x):
    return str(pd.Timestamp(x).year) if pd.notna(x) else "?"


# ------------------------------------------------------------------------------------------------------------------
# Partis › Fiche d'un parti
# ------------------------------------------------------------------------------------------------------------------
def fiche_parti(fig, ctx):
    if not P.disponible():
        return _pas_de_partis(fig)
    f = P.fiche(_parti_choisi(ctx))
    logos = f["logos"]
    donnees(pd.DataFrame([{"parti": f["nom"], "nature": f["nature"], "création": f["creation"], "dissolution": f["dissolution"],
                           "adhérents connus": f["adherents"], "dont ministres": f["ministres"], "dont énarques": f["enarques"],
                           "idéologies": ", ".join(f["ideologies"]), "positions": ", ".join(f["positions"])}]), "le parti")
    if len(f["candidats"]):
        donnees(f["candidats"], "candidats rattachés à ce parti (législatives, 1er tour)")
    if len(logos):
        donnees(logos[["fichier", "date_debut", "date_fin", "auteur", "licence", "adresse"]], "ses logos (Wikimedia Commons)")
    ax = fig.add_axes([0.04, 0.30, 0.92, 0.62])
    ax.axis("off")
    titre(ax, f["nom"], f"{f['nature'] or 'parti'} · créé en {_an(f['creation'])}"
                        + (f" · dissous en {_an(f['dissolution'])}" if pd.notna(f["dissolution"]) else ""))
    # ses logos, dans l'ordre (avec leurs années quand Wikidata les connaît)
    for k, l in enumerate(logos.itertuples()):
        x = 0.08 + 0.15 * k
        if x > 0.95 or not (P.d.DATA / l.fichier).exists():
            break
        _image(ax, P.d.DATA / l.fichier, (x, 0.82), 0.45 * min(1, 140 / 200))
        ax.text(x, 0.6, (f"{_an(l.date_debut)} – {_an(l.date_fin) if pd.notna(l.date_fin) else ''}"
                         if pd.notna(l.date_debut) else "logo"), ha="center", fontsize=T(8), color=C["gris"], transform=ax.transAxes)
    if not len(logos):
        ax.text(0.08, 0.82, f["sigle"] or f["libelle"][:3], ha="center", va="center", fontsize=T(18), weight="bold",
                color="white", transform=ax.transAxes,
                bbox=dict(boxstyle="round,pad=0.6", fc=f["couleur"] or C["primaire"], ec="none"))
    lignes = []
    if len(f["lignee"]) > 1:
        lignes.append("Lignée : " + " → ".join(f"{s or court(l, 30)} ({_an(c)})" for _, l, s, c, _ in f["lignee"]))
    if len(f["coalitions"]):
        lignes.append("Membre de : " + ", ".join(f"{s or l}" for l, s in f["coalitions"].values))
    if len(f["membres"]):
        lignes.append("Rassemble : " + ", ".join(f"{s or l}" for l, s in f["membres"].values))
    if f["ideologies"]:
        lignes.append("Idéologies : " + court(", ".join(f["ideologies"]), 150))
    if f["positions"]:
        lignes.append("Position : " + ", ".join(f["positions"]))
    lignes.append(f"Adhérents connus : {f['adherents']} personnes (dont {f['ministres']} ministres, {f['enarques']} énarques)")
    for i, l in enumerate(lignes):
        ax.text(0.0, 0.42 - i * 0.09, l, fontsize=T(10), color=C["texte"], transform=ax.transAxes, wrap=True)
    # ses candidats, élection par élection
    ax2 = fig.add_axes([0.08, 0.06, 0.88, 0.2])
    if len(f["candidats"]):
        c = f["candidats"]
        ax2.bar(c["election"].str[:4], c["candidats"], color=f["couleur"] or C["primaire"])
        for x, y in zip(range(len(c)), c["candidats"]):
            ax2.text(x, y, str(y), ha="center", va="bottom", fontsize=T(9))
        ax2.set_title("Candidats rattachés à ce parti aux législatives (1er tour)", loc="left", fontsize=T(10))
        ax2.spines[["top", "right"]].set_visible(False)
    else:
        ax2.axis("off")
        ax2.text(0, 0.5, "Pas de candidats rattachés à ce parti aux législatives 2017-2024.", fontsize=T(9), color=C["gris"])
    return {"legende": [], "kpi": [(str(f["adherents"]), "adhérents connus"), (str(f["ministres"]), "ministres"),
                                   (str(len(logos)), "logos libres")],
            "lecture": "Wikidata (adhésions, idéologies, lignée, coalitions, logos de Wikimedia Commons : licences et auteurs dans "
                       "l'export) ; rattachements financiers des candidats : ministère de l'Intérieur. Un logo seulement montré "
                       "au titre de l'« usage loyal » sur Wikipédia n'est pas libre : pastille à la place."}


# ------------------------------------------------------------------------------------------------------------------
# Partis › Les plus anciens
# ------------------------------------------------------------------------------------------------------------------
def anciens(fig, ctx):
    if not P.disponible():
        return _pas_de_partis(fig)
    t = P.anciens(30)
    tous = P.anciens(1, encore=False)
    if t.empty:
        return vide(fig, "Aucun parti avec une date de création.")
    donnees(t[["libelle", "sigle", "date_creation", "candidats", "adherents"]], "les partis encore actifs, du plus ancien au plus récent")
    ax = fig.add_subplot()
    y = np.arange(len(t))
    debut = pd.to_datetime(t["date_creation"])
    ax.barh(y, (AUJOURD_HUI - debut).dt.days / 365.25, left=debut.dt.year, color=[c or C["primaire"] for c in t["couleur"]], height=0.6)
    for i, r in enumerate(t.itertuples()):
        ax.text(debut.iloc[i].year - 1, i, f"{court(P.nom(pd.Series({'sigle': r.sigle, 'libelle': r.libelle})), 42)} ({debut.iloc[i].year})",
                ha="right", va="center", fontsize=T(9))
        fichier = P.logo(r.id)
        if fichier:
            _image(ax, fichier, (AUJOURD_HUI.year + 4, i), 0.12, boite="data")
    ax.set_yticks([])
    ax.invert_yaxis()
    ax.set_xlim(debut.dt.year.min() - 60, AUJOURD_HUI.year + 10)
    ax.spines[["top", "right", "left"]].set_visible(False)
    titre(ax, "Les plus anciens partis encore actifs", "une barre par parti, de sa création à aujourd'hui")
    fig.tight_layout()
    premier = t.iloc[0]
    return {"legende": [], "kpi": [(str(pd.Timestamp(premier["date_creation"]).year), court(P.nom(premier), 24)),
                                   (str(pd.Timestamp(tous.iloc[0]["date_creation"]).year), f"le plus ancien de l'histoire : {court(tous.iloc[0]['libelle'], 20)}")],
            "lecture": "Encore actif = pas dissous, et des comptes déposés à la CNCCFP ou des candidats rattachés aux législatives "
                       "2017-2024 (Wikidata ne donne pas toujours la date de disparition). Dates de création : Wikidata."}


# ------------------------------------------------------------------------------------------------------------------
# Partis › Les partis des grandes lois
# ------------------------------------------------------------------------------------------------------------------
def lois(fig, ctx):
    if not P.disponible():
        return _pas_de_partis(fig)
    t = P.lois()
    if t.empty:
        return vide(fig, "Les grands votes ne sont pas dans la base.")
    donnees(t[["loi", "date", "gouvernement", "premier_ministre", "parti", "proposition"]]
            .rename(columns={"proposition": "proposition de loi (d'un député)"}), "les grandes lois et le parti du gouvernement")
    c = t.groupby("parti").agg(n=("loi", "size"), lois=("loi", lambda x: " · ".join(s.split(" · ", 1)[1] for s in x))).sort_values("n")
    ax = fig.add_subplot()
    y = np.arange(len(c))
    couleurs = P.poids().set_index("id")["couleur"]
    ids = t.drop_duplicates("parti").set_index("parti")["parti_id"]
    ax.barh(y, c["n"], color=[couleurs.get(ids.get(p)) or C["gris"] for p in c.index], height=0.6)
    for i, (p, r) in enumerate(c.iterrows()):
        ax.text(r["n"] + 0.1, i, f"{r['n']}  —  {court(r['lois'], 110)}", va="center", fontsize=T(8), color=C["texte"])
    ax.set_yticks(y, [court(p, 34) for p in c.index], fontsize=T(9))
    ax.set_xlim(0, c["n"].max() * 4)
    ax.spines[["top", "right"]].set_visible(False)
    titre(ax, "Quel parti est à l'origine des grandes lois ?", f"{len(t)} lois entrées dans l'histoire · le parti du Premier ministre le jour du vote")
    fig.tight_layout()
    premier = c.sort_values("n").iloc[-1]
    return {"legende": [], "kpi": [(str(int(premier["n"])), court(c["n"].idxmax(), 24)), (str(len(t)), "grandes lois"),
                                   (str(int(t["proposition"].sum())), "propositions de loi")],
            "lecture": "Un projet de loi vient du gouvernement : on compte le parti de son Premier ministre, à la date du vote. "
                       "Une proposition de loi vient d'un député (loi Gayssot : PCF ; loi Leonetti : UMP…) : son parti peut "
                       "différer — elles sont marquées dans l'export. Lois : les grands votes de la vue Votes (sans les "
                       "censures ni les interventions armées)."}


# ------------------------------------------------------------------------------------------------------------------
# Partis › Les écoles des partis (énarques…) et leurs personnalités
# ------------------------------------------------------------------------------------------------------------------
def ecoles(fig, ctx):
    if not P.disponible():
        return _pas_de_partis(fig)
    ecole = ctx.options.get("ecole") or "École nationale d'administration"
    t = P.anciens_eleves(ecole, 20)
    if t.empty:
        return vide(fig, f"Aucun adhérent connu passé par : {ecole}.")
    donnees(t[["libelle", "sigle", "n", "qui"]].rename(columns={"n": "anciens élèves", "qui": "qui"}), f"anciens élèves de : {ecole}")
    t = t.iloc[::-1]
    ax = fig.add_subplot()
    couleurs = P.poids().set_index("id")["couleur"]
    ax.barh(range(len(t)), t["n"], color=[couleurs.get(i) or C["primaire"] for i in t["id"]], height=0.6)
    for i, n in enumerate(t["n"]):
        ax.text(n, i, f" {n}", va="center", fontsize=T(9))
    ax.set_yticks(range(len(t)), [court(P.nom(r), 40) for _, r in t.iterrows()], fontsize=T(9))
    ax.spines[["top", "right"]].set_visible(False)
    titre(ax, f"Quel parti a le plus d'anciens élèves de : {court(ecole, 40)} ?", "adhérents connus passés par cette école")
    fig.tight_layout()
    return {"legende": [], "kpi": [(str(int(t["n"].iloc[-1])), court(P.nom(t.iloc[-1]), 24))],
            "lecture": "Wikidata ne connaît que les diplômés « notables » et leurs adhésions déclarées : ce sont des ordres de "
                       "grandeur. Une personne passée par plusieurs partis compte dans chacun. Choisis une autre école à droite."}


def personnalites(fig, ctx):
    if not P.disponible():
        return _pas_de_partis(fig)
    t = P.personnalites(20)
    donnees(t[["libelle", "sigle", "n", "ministres", "parlementaires"]].rename(columns={"n": "personnalités"}),
            "les partis qui comptent le plus de personnalités")
    t = t.iloc[::-1]
    ax = fig.add_subplot()
    y = np.arange(len(t))
    for k, (col, lib) in enumerate([("n", "personnalités connues"), ("parlementaires", "dont parlementaires"), ("ministres", "dont ministres")]):
        ax.barh(y + (k - 1) * 0.26, t[col], height=0.26, color=SERIES[k], label=lib)
    ax.set_yticks(y, [court(P.nom(r), 40) for _, r in t.iterrows()], fontsize=T(9))
    ax.legend(fontsize=T(8), loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    titre(ax, "Quel parti a le plus de personnalités ?", "les personnes connues de Wikidata qui y ont adhéré, dont les ministres et les parlementaires")
    fig.tight_layout()
    return {"legende": [], "kpi": [(str(int(t["n"].iloc[-1])), court(P.nom(t.iloc[-1]), 24)),
                                   (str(int(t["ministres"].max())), "ministres (le plus)")],
            "lecture": "Personnalité = une personne qui a une fiche Wikidata et une adhésion déclarée à ce parti. Une personne "
                       "passée par plusieurs partis compte dans chacun (Chirac : UDR, RPR, UMP)."}


# ------------------------------------------------------------------------------------------------------------------
# Partis › Les coalitions
# ------------------------------------------------------------------------------------------------------------------
def coalitions(fig, ctx):
    if not P.disponible():
        return _pas_de_partis(fig)
    t = P.coalitions().head(18)
    if t.empty:
        return vide(fig, "Aucune coalition dans la base.")
    donnees(t[["coalition", "sigle", "date_creation", "n", "membres"]], "les coalitions et leurs partis")
    ax = fig.add_subplot()
    ax.axis("off")
    titre(ax, "Les coalitions et les partis qui les composent", "des plus récentes aux plus anciennes (Wikidata)")
    for i, r in enumerate(t.itertuples()):
        y = 1 - (i + 0.5) / len(t)
        ax.text(0, y, f"{court(r.coalition, 44)} ({_an(r.date_creation)})", fontsize=T(10), weight="bold", color=C["primaire"],
                transform=ax.transAxes, va="center")
        ax.text(0.42, y, f"{r.n} : {court(r.membres, 120)}", fontsize=T(9), color=C["texte"], transform=ax.transAxes, va="center")
    return {"legende": [], "kpi": [(str(len(P.coalitions())), "coalitions"), (str(int(t["n"].max())), "partis au plus")],
            "lecture": "Composition d'après Wikidata (propriété « comprend ») : elle peut dater ou être incomplète."}
