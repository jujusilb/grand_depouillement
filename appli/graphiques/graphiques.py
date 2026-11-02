"""
graphiques.py — Une fonction = une vue. Chacune reçoit la figure matplotlib et le contexte (scrutin, zone, réglages),
dessine, et renvoie ce que le panneau de droite affiche : légende, chiffres clés, phrase de lecture.

    info = dessiner(fig, ctx)      ->  {"legende": [(texte, couleur)], "kpi": [(valeur, libellé)] * 3, "lecture": "…"}

Les graphiques sont faits avec seaborn (histplot, boxplot, heatmap, scatterplot, regplot, barplot) sur matplotlib.
Ces fonctions ne savent rien de tkinter : on peut les tester seules.
"""

import dataclasses
import json
import math
from functools import lru_cache

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.transforms as mtransforms
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.collections import PolyCollection
from matplotlib.lines import Line2D

from lecture import donnees as d
from lecture import affiches
from politique import candidats, legislatures, parlement, rne, sieges
from graphiques import fond_carte
from interface import theme
from politique import votes as votes_deputes
from interface.theme import C, SERIES, TYPES_ELECTION


# =============================================================================================
# Le moteur de dessin : seaborn ou matplotlib (bouton dans l'appli). Le MÊME graphique, deux façons de le coder.
# =============================================================================================

MOTEUR = "seaborn"


def sb():
    return MOTEUR == "seaborn"


def histo(ax, v, bins, couleur):
    if sb():
        sns.histplot(v, bins=bins, kde=True, color=couleur, alpha=0.85, ax=ax)     # seaborn ajoute la courbe de densité
    else:
        ax.hist(v, bins=bins, color=couleur, alpha=0.85)


def boite(ax, v, fond, trait):
    if sb():
        sns.boxplot(x=v, color=fond, linecolor=trait, showfliers=False, width=0.4, ax=ax)
    else:
        ax.boxplot(v, vert=False, widths=0.4, patch_artist=True, showfliers=False,
                   boxprops=dict(facecolor=fond, edgecolor=trait), medianprops=dict(color=trait, lw=2))
        ax.set_yticks([])


def chaleur(fig, ax, table, cmap, fmt_, vmin=None, vmax=None, label=None, carre=False):
    donnees(table.round(2).reset_index())
    if sb():
        sns.heatmap(table, cmap=cmap, vmin=vmin, vmax=vmax, annot=True, fmt=fmt_, annot_kws={"size": T(6 if carre else 7)}, square=carre,
                    linewidths=0.5, linecolor="white", cbar_kws={"shrink": 0.8, **({"label": label} if label else {})}, ax=ax)
    else:
        im = ax.imshow(table.values, cmap=cmap, vmin=vmin, vmax=vmax, aspect="equal" if carre else "auto")
        ax.set_xticks(range(table.shape[1]), table.columns)
        ax.set_yticks(range(table.shape[0]), table.index)
        ax.grid(False)
        fig.colorbar(im, ax=ax, shrink=0.8, label=label)


def points(ax, x, y, couleur=None, teintes=None, palette=None, taille=12, alpha=0.5):
    if sb():
        if teintes is not None:
            sns.scatterplot(x=x, y=y, hue=teintes, palette=palette, s=taille, edgecolor="white", legend=False, ax=ax, zorder=3)
        else:
            sns.scatterplot(x=x, y=y, s=taille, alpha=alpha, color=couleur, edgecolor="none", ax=ax)
    else:
        c = [palette.get(t, C["gris"]) for t in teintes] if teintes is not None else couleur
        ax.scatter(x, y, s=taille, alpha=1 if teintes is not None else alpha, c=c if teintes is not None else None,
                   color=None if teintes is not None else couleur, edgecolors="white" if teintes is not None else "none", zorder=3)


def tendance(ax, x, y, bande=True):
    if sb():
        sns.regplot(x=np.asarray(x), y=np.asarray(y), scatter=False, color=C["action"], line_kws=dict(lw=1.2), ci=95 if bande else None, ax=ax)
    else:
        a, b = np.polyfit(x, y, 1)
        xs = np.linspace(np.min(x), np.max(x), 50)
        ax.plot(xs, a * xs + b, color=C["action"], lw=1.2)


def barres_groupees(ax, long_, cat, val, groupe, palette, horizontal=False):
    donnees(long_.pivot_table(index=cat, columns=groupe, values=val, sort=False).round(3).reset_index())
    if sb():
        if horizontal:
            sns.barplot(data=long_, y=cat, x=val, hue=groupe, palette=palette, orient="h", ax=ax)
        else:
            sns.barplot(data=long_, x=cat, y=val, hue=groupe, palette=palette, ax=ax)
        if ax.legend_:
            ax.legend_.remove()
    else:
        cats = list(dict.fromkeys(long_[cat]))
        grps = list(dict.fromkeys(long_[groupe]))
        larg = 0.8 / len(grps)
        pos = np.arange(len(cats))
        for i, g_ in enumerate(grps):
            v = long_[long_[groupe] == g_].set_index(cat)[val].reindex(cats)
            (ax.barh if horizontal else ax.bar)(pos + i * larg - 0.4 + larg / 2, v, larg, color=palette[i])
        (ax.set_yticks if horizontal else ax.set_xticks)(pos, cats)
        if horizontal:
            ax.invert_yaxis()


def ligne_et_points(ax, s, couleur_ligne=None):
    if sb():
        sns.lineplot(data=s, x="date", y="valeur", color=couleur_ligne or C["bordure"], ax=ax, zorder=1)
        sns.scatterplot(data=s, x="date", y="valeur", hue="type", palette=TYPES_ELECTION, s=55, edgecolor="white", legend=False, ax=ax, zorder=3)
    else:
        ax.plot(s["date"], s["valeur"], color=couleur_ligne or C["bordure"], zorder=1)
        ax.scatter(s["date"], s["valeur"], c=[TYPES_ELECTION.get(t, C["gris"]) for t in s["type"]], s=45, edgecolors="white", zorder=3)
    ax.set_xlabel("")


# =============================================================================================
# Outils communs
# =============================================================================================

# Les données de la vue en cours, pour l'export texte / CSV (gd/export.py) : une vue les donne avec donnees(tableau) ;
# sinon l'export les relit dans le graphique. La fenêtre remet à None avant chaque dessin.
DONNEES = []          # liste de (titre, tableau)


def donnees(tableau, titre=""):
    """Ajoute un tableau aux données de la vue ; donnees(None) les vide (avant chaque dessin)."""
    global DONNEES
    if tableau is None:
        DONNEES = []
    else:
        DONNEES.append((titre, tableau.reset_index(drop=True)))


def T(taille):
    """Une taille de texte de graphique : jamais moins de 9 points (lisibilité, malvoyants), et agrandie par le zoom de l'appli."""
    return max(taille, 9) * theme.ZOOM


def fmt(v, dec=1, suffixe=" %"):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:,.{dec}f}".replace(",", " ").replace(".", ",") + suffixe


def court(texte, n=26):
    texte = str(texte)
    return texte if len(texte) <= n else texte[:n - 1] + "…"


def vide(fig, message):
    ax = fig.add_subplot()
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=C["gris"], fontsize=T(11), wrap=True, transform=ax.transAxes)
    return {"legende": [], "kpi": [], "lecture": message}


@lru_cache(None)
def _rangs(scrutin, regroupement):
    return {q: i for i, q in enumerate(d.cles(scrutin, d.FRANCE, regroupement, 60))}


def couleur_politique(scrutin, regroupement, qui):
    """La couleur de son camp (theme.NUANCES) : par sa nuance, ou celle de sa liste, ou un mot de son nom ; sinon None."""
    nationale = d.type_de(scrutin) in d.TYPES_NATIONAUX   # les mots du nom : seulement là (pas les listes locales)
    c = theme.couleur_politique(qui, mots=nationale)
    if c is None and regroupement == "Candidat / liste":
        c = theme.couleur_politique(d.nuances_des_candidats(scrutin).get(qui), mots=False)
    return c


def couleur_qui(scrutin, regroupement, qui):
    """La couleur politique s'il y en a une, sinon celle de son rang national dans ce scrutin (stable d'une vue à l'autre)."""
    return couleurs_pour(scrutin, regroupement, [qui])[0]


def couleurs_pour(scrutin, regroupement, liste):
    """Les couleurs d'une liste de candidats : le rang national s'il existe (couleur stable d'une vue à l'autre),
    sinon une couleur encore libre (listes municipales, candidats locaux)."""
    rangs = _rangs(scrutin, regroupement)
    politiques = {q: couleur_politique(scrutin, regroupement, q) for q in liste}
    prises = {c for c in politiques.values() if c} | {SERIES[rangs[q] % len(SERIES)] for q in liste if rangs.get(q, 99) < 12}
    libres = [c for c in SERIES if c not in prises]
    resultat = []
    for q in liste:
        if politiques[q]:
            resultat.append(politiques[q])
        elif rangs.get(q, 99) < 12:
            resultat.append(SERIES[rangs[q] % len(SERIES)])
        else:
            resultat.append(libres.pop(0) if libres else C["doux"])
    return resultat


def titre(ax, texte, sous=None):
    ax.set_title(texte, loc="left", pad=(8 + T(9) * 1.5) if sous else 10 * theme.ZOOM)      # (la place du sous-titre, zoom compris)
    if sous:
        # décalage en points (pas en fraction de l'axe) : reste collé au titre même sur une figure très haute
        ax.text(0, 1, sous, transform=ax.transAxes + mtransforms.ScaledTranslation(0, 4 / 72, ax.figure.dpi_scale_trans),
                fontsize=T(8), color=C["gris"], va="bottom")


def axe_dates(ax):
    debut, fin = ax.get_xlim()
    ans = (fin - debut) / 365.25                     # depuis 1793 : une étiquette tous les 20 ans, sinon tous les 4 ans
    ax.xaxis.set_major_locator(mdates.YearLocator(20 if ans > 80 else 10 if ans > 40 else 4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def zone_txt(ctx):
    return ctx.zone.libelle


# =============================================================================================
# Formes interchangeables pour une liste « nom -> valeur » (barres, anneau, tableau)
# =============================================================================================

LIGNES_SANS_ASCENSEUR = 25   # au-delà, une liste se dessine en grand et la fenêtre propose l'ascenseur


def hauteur_liste(fig, n, pouces_par_ligne=0.3):
    """Demande à la fenêtre une figure plus haute que l'écran (elle ajoute l'ascenseur)."""
    fig.hauteur_voulue = int((n * pouces_par_ligne * 1.15 * theme.ZOOM + 1.4) * fig.dpi)


def dessiner_liste(fig, noms, valeurs, couleurs, forme, titre_, sous, unite=" %", dec=1):
    noms, valeurs = list(noms), list(valeurs)
    donnees(pd.DataFrame({"rang": range(1, len(noms) + 1), "nom": noms, ("valeur" + unite).strip(): np.round(valeurs, 3)}))
    longue = len(noms) > LIGNES_SANS_ASCENSEUR
    if forme == "anneau":
        ax = fig.add_subplot()
        if len(noms) > 8:
            noms, valeurs, couleurs = noms[:8] + ["Autres"], valeurs[:8] + [sum(valeurs[8:])], couleurs[:8] + [C["bordure"]]
        ax.pie(valeurs, colors=couleurs, startangle=90, counterclock=False, wedgeprops=dict(width=0.38, edgecolor="white"))
        ax.text(0, 0, f"{court(noms[0], 18)}\n{fmt(valeurs[0], dec, unite)}", ha="center", va="center", fontsize=T(11), weight="bold", color=C["texte"])
        ax.set_aspect("equal")
        titre(ax, titre_, sous)
    elif forme == "tableau":
        ax = fig.add_subplot()
        ax.axis("off")
        lignes = [[str(i + 1), court(n, 40), fmt(v, dec, unite)] for i, (n, v) in enumerate(zip(noms, valeurs))]
        if longue:
            hauteur_liste(fig, len(lignes), 0.28)
        t = ax.table(cellText=lignes, colLabels=["#", "Nom", "Valeur"], loc="upper center", colLoc="left", cellLoc="left",
                     colWidths=[0.06, 0.6, 0.18])
        t.auto_set_font_size(False)
        t.set_fontsize(T(10))
        t.scale(1, 1.35)
        for (r, c), cell in t.get_celld().items():
            cell.set_edgecolor(C["bordure"])
            if r == 0:
                cell.set_facecolor(C["surface"]); cell.set_text_props(weight="bold")
        titre(ax, titre_, sous)
    elif forme == "barres_v":
        ax = fig.add_subplot()
        etiq = [f"{i + 1}. {court(n, 14)}" for i, n in enumerate(noms)]
        if sb():
            sns.barplot(x=etiq, y=valeurs, hue=etiq, palette=couleurs, legend=False, ax=ax)
        else:
            ax.bar(range(len(etiq)), valeurs, color=couleurs)
        ax.set_xticks(range(len(etiq)), etiq, rotation=40, ha="right", fontsize=T(8))
        for xi, v in enumerate(valeurs):
            ax.text(xi, v, fmt(v, dec, ""), ha="center", va="bottom", fontsize=T(7), color=C["gris"])
        ax.set_xlabel(""); ax.set_ylabel("")
        ax.grid(axis="x", visible=False)
        titre(ax, titre_, sous)
    else:   # barres horizontales
        ax = fig.add_subplot()
        etiq = [f"{i + 1}. {court(n, 32)}" for i, n in enumerate(noms)]
        if longue:
            hauteur_liste(fig, len(etiq))
        if sb():
            sns.barplot(y=etiq, x=valeurs, hue=etiq, palette=couleurs, legend=False, ax=ax, orient="h")
        else:
            ax.barh(range(len(etiq)), valeurs, color=couleurs, height=0.75)
            ax.set_yticks(range(len(etiq)), etiq)
            ax.invert_yaxis()
        ax.tick_params(axis="y", labelsize=T(10))
        for yi, v in enumerate(valeurs):
            ax.text(v, yi, " " + fmt(v, dec, unite), va="center", fontsize=T(9.5), color=C["gris"])
        ax.set_xlabel(""); ax.set_ylabel("")
        ax.grid(axis="y", visible=False)
        ax.margins(x=0.12)
        titre(ax, titre_, sous)
    if longue:
        fig.set_layout_engine("tight")      # la mise en page se refera à la vraie taille (la figure va grandir)
    else:
        fig.tight_layout()


# =============================================================================================
# Onglet Participation
# =============================================================================================

def taux_par_bureau(fig, ctx):
    ind = ctx.options.get("indicateur", "Abstention")
    b = d.taux_bureaux(ctx.scrutin, ctx.zone, ind).dropna(subset=["valeur"])
    if b.empty:
        return vide(fig, f"Pas de donnée « {ind} » pour ce scrutin dans cette zone (les blancs ne sont comptés à part que depuis 2014).")
    zone_val, fr = d.totaux(ctx.scrutin, ctx.zone)[ind], d.totaux(ctx.scrutin)[ind]
    ax = fig.add_subplot()
    if ctx.forme == "boites":
        boite(ax, b["valeur"], C["clair"], C["primaire"])
    else:
        histo(ax, b["valeur"], int(ctx.options.get("tranches", 60)), C["primaire"])
        ax.set_ylabel("Nombre de bureaux")
    ax.axvline(fr, color=C["action"], ls="--", lw=1.5)
    ax.set_xlabel(f"{ind} (%)")
    titre(ax, f"{ind} par bureau – {zone_txt(ctx)}", f"{d.libelle(ctx.scrutin)} · {len(b):,} bureaux".replace(",", " "))
    fig.tight_layout()
    return {"legende": [("Bureaux de la zone", C["primaire"]), ("France entière", C["action"])],
            "kpi": [(fmt(zone_val), f"{ind.lower()} zone"), (fmt(fr), "France"), (fmt(b["valeur"].std(), 1, ""), "écart-type")],
            "lecture": f"Chaque barre = le nombre de bureaux dans une tranche. Trait rouge = la France ({fmt(fr)})."}


def zone_et_niveaux(fig, ctx):
    """La zone comparée aux niveaux au-dessus d'elle : département, région, France."""
    niveaux = [ctx.zone]
    if ctx.zone.niveau in ("commune", "bureau", "arrmun", "canton", "circo", "epci", "arrondissement"):
        dep = d.sql(f"SELECT any_value(code_departement) c, any_value(libelle_departement) l FROM {d.P(ctx.scrutin)} p "
                    f"WHERE {d.filtre(ctx.zone)[0]}", d.filtre(ctx.zone)[1]).iloc[0]
        if dep["c"]:
            niveaux.append(d.Zone("departement", dep["c"], dep["l"]))
    if ctx.zone.niveau != "france":
        reg = d.sql(f"SELECT any_value(code_region) c, any_value(libelle_region) l FROM {d.P(ctx.scrutin)} p "
                    f"WHERE {d.filtre(ctx.zone)[0]}", d.filtre(ctx.zone)[1]).iloc[0]
        if reg["c"] and ctx.zone.niveau != "region":
            niveaux.append(d.Zone("region", reg["c"], reg["l"]))
        niveaux.append(d.FRANCE)
    inds = ["Abstention", "Blancs", "Nuls"]
    t = pd.DataFrame({z.libelle: [d.totaux(ctx.scrutin, z)[i] for i in inds] for z in niveaux}, index=inds)
    ax = fig.add_subplot()
    coul = [C["primaire"], C["moyen"], C["doux"], C["bordure"]]
    long_ = t.reset_index(names="taux").melt(id_vars="taux", var_name="zone", value_name="valeur")
    barres_groupees(ax, long_, "taux", "valeur", "zone", coul[:len(t.columns)], ctx.forme == "barres_h")
    ax.set_xlabel(""); ax.set_ylabel("%")
    titre(ax, f"{zone_txt(ctx)} et les niveaux au-dessus", d.libelle(ctx.scrutin))
    fig.tight_layout()
    return {"legende": [(z, coul[i % 4]) for i, z in enumerate(t.columns)],
            "kpi": [(fmt(t.iloc[0, 0]), "abstention zone"), (fmt(t.iloc[0, -1]), "France"), (fmt(t.iloc[0, 0] - t.iloc[0, -1], 1, " pts"), "écart")],
            "lecture": "Chaque groupe = un taux ; chaque barre = un niveau, de la zone choisie à la France entière."}


def pondere(fig, ctx):
    inds = ["Abstention", "Participation", "Blancs", "Nuls"]
    pond, moy = [], []
    for i in inds:
        b = d.taux_bureaux(ctx.scrutin, ctx.zone, i).dropna(subset=["valeur"])
        pond.append(d.totaux(ctx.scrutin, ctx.zone)[i]); moy.append(b["valeur"].mean() if len(b) else np.nan)
    ax = fig.add_subplot()
    long_ = pd.DataFrame({"taux": inds * 2, "valeur": pond + moy, "calcul": ["Pondéré"] * 4 + ["Moyenne des bureaux"] * 4})
    barres_groupees(ax, long_, "taux", "valeur", "calcul", [C["primaire"], C["action"]])
    ax.set_xlabel(""); ax.set_ylabel("%")
    titre(ax, "Chaque électeur compte pour 1… ou chaque bureau ?", f"{d.libelle(ctx.scrutin)} · {zone_txt(ctx)}")
    fig.tight_layout()
    return {"legende": [("Pondéré (total voix / total inscrits)", C["primaire"]), ("Moyenne des % des bureaux", C["action"])],
            "kpi": [(fmt(pond[0]), "abstention pondérée"), (fmt(moy[0]), "moyenne des bureaux"), (fmt(moy[0] - pond[0], 1, " pts"), "écart")],
            "lecture": "Si la barre rouge dépasse la bleue : le taux est plus fort dans les PETITS bureaux (souvent ruraux)."}


# =============================================================================================
# Onglet Candidat
# =============================================================================================

def resultats(fig, ctx):
    r = d.resultats(ctx.scrutin, ctx.zone, ctx.regroupement).head(15)
    if r.empty:
        return vide(fig, "Aucun résultat pour ce scrutin dans cette zone.")
    coul = couleurs_pour(ctx.scrutin, ctx.regroupement, list(r["qui"]))
    dessiner_liste(fig, r["qui"], r["pct"], coul, ctx.forme, f"{d.libelle(ctx.scrutin)} – {zone_txt(ctx)}",
                   f"en % des exprimés · {ctx.regroupement.lower()}")
    ecart = r["pct"].iloc[0] - r["pct"].iloc[1] if len(r) > 1 else np.nan
    lecture = "Les 15 premiers, en % des exprimés de la zone."
    if r["pct"].sum() > 101:
        lecture = "⚠ La somme dépasse 100 % : dans les petites communes, chaque bulletin donne une voix à plusieurs personnes."
    return {"legende": [(court(q, 22), c) for q, c in zip(r["qui"].head(4), coul[:4])] + [("Autres", C["doux"])],
            "kpi": [(fmt(r["pct"].iloc[0]), "1er : " + court(r["qui"].iloc[0], 16)), (fmt(ecart, 1, " pts"), "avance sur le 2e"), (str(len(r)), "affichés")],
            "lecture": lecture}


def score_candidat(fig, ctx):
    qui = ctx.options.get("candidat") or (d.cles(ctx.scrutin, ctx.zone, ctx.regroupement, 1) or [None])[0]
    if not qui:
        return vide(fig, "Aucun candidat dans cette zone.")
    t = d.pct_bureaux(ctx.scrutin, ctx.zone, ctx.regroupement, [qui])
    v = t.loc[t[qui] > 0, qui]
    if v.empty:
        return vide(fig, f"« {qui} » n'a pas de voix dans cette zone.")
    nat = d.resultats(ctx.scrutin, d.FRANCE, ctx.regroupement).set_index("qui")["pct"].get(qui, np.nan)
    coul = couleur_qui(ctx.scrutin, ctx.regroupement, qui)
    ax = fig.add_subplot()
    if ctx.forme == "boites":
        boite(ax, v, C["clair"], coul)
    else:
        histo(ax, v, 60, coul)
        ax.set_ylabel("Nombre de bureaux")
    ax.axvline(nat, color=C["texte"], ls="--", lw=1.2)
    ax.set_xlabel("% des exprimés dans le bureau")
    titre(ax, f"{court(qui, 40)} : score bureau par bureau", f"{d.libelle(ctx.scrutin)} · {zone_txt(ctx)} · {len(v)} bureaux")
    fig.tight_layout()
    return {"legende": [(court(qui, 22), coul), ("Score national", C["texte"])],
            "kpi": [(fmt(v.median()), "médiane des bureaux"), (fmt(v.max()), "meilleur bureau"), (fmt(nat), "France")],
            "lecture": "Seulement les bureaux où il/elle avait des voix. Trait pointillé = score national."}


def duel(fig, ctx):
    l = d.cles(ctx.scrutin, ctx.zone, ctx.regroupement, 2)
    a = ctx.options.get("candidat") or (l[0] if l else None)
    b = ctx.options.get("candidat2") or (l[1] if len(l) > 1 else None)
    if not a or not b or a == b:
        return vide(fig, "Choisis deux candidats différents (réglages de la vue).")
    t = d.pct_bureaux(ctx.scrutin, ctx.zone, ctx.regroupement, [a, b])
    if len(t) < 3:
        return vide(fig, "Pas assez de bureaux dans cette zone.")
    ax = fig.add_subplot()
    if ctx.forme == "chaleur" or (ctx.forme != "nuage" and len(t) > 3000):
        hb = ax.hexbin(t[a], t[b], gridsize=55, cmap="Blues", mincnt=1, bins="log")
        fig.colorbar(hb, ax=ax, label="bureaux (échelle log)")
    else:
        points(ax, t[a], t[b], couleur=C["primaire"])
        tendance(ax, t[a], t[b])
    r = np.corrcoef(t[a], t[b])[0, 1]
    ax.set_xlabel(f"% {court(a, 30)}"); ax.set_ylabel(f"% {court(b, 30)}")
    titre(ax, f"{court(a, 24)} contre {court(b, 24)}", f"{d.libelle(ctx.scrutin)} · {zone_txt(ctx)} · un point = un bureau")
    fig.tight_layout()
    return {"legende": [("Un bureau de vote", C["primaire"])],
            "kpi": [(fmt(r, 2, ""), "corrélation"), (fmt(r * r * 100, 0), "part expliquée (r²)"), (f"{len(t):,}".replace(",", " "), "bureaux")],
            "lecture": "Un point = un bureau. Corrélation proche de −1 : là où l'un est fort, l'autre est faible."}


def zone_contre_france(fig, ctx):
    if ctx.zone.niveau == "france":
        return vide(fig, "Choisis une zone (volet Zone) pour la comparer à la France.")
    zo = d.resultats(ctx.scrutin, ctx.zone, ctx.regroupement).head(12)
    fr = d.resultats(ctx.scrutin, d.FRANCE, ctx.regroupement).set_index("qui")["pct"]
    ax = fig.add_subplot()
    noms = [court(q, 24) for q in zo["qui"]]
    long_ = pd.DataFrame({"qui": noms * 2, "valeur": list(fr.reindex(zo["qui"]).fillna(0)) + list(zo["pct"]),
                          "où": ["France"] * len(zo) + [zone_txt(ctx)] * len(zo)})
    barres_groupees(ax, long_, "qui", "valeur", "où", [C["bordure"], C["primaire"]], ctx.forme == "barres_h")
    if ctx.forme == "barres_h":
        ax.tick_params(axis="y", labelsize=T(8))
    else:
        ax.tick_params(axis="x", labelsize=T(8), rotation=40)
        for lab in ax.get_xticklabels():
            lab.set_ha("right")
    ax.set_xlabel(""); ax.set_ylabel("% des exprimés")
    titre(ax, f"{zone_txt(ctx)} comparé à la France", d.libelle(ctx.scrutin))
    fig.tight_layout()
    e = (zo.set_index("qui")["pct"] - fr.reindex(zo["qui"])).dropna()
    return {"legende": [(zone_txt(ctx), C["primaire"]), ("France entière", C["bordure"])],
            "kpi": [(court(e.idxmax(), 14) if len(e) else "—", "plus fort qu'en France"), (fmt(e.max(), 1, " pts"), "écart"),
                    (court(e.idxmin(), 14) if len(e) else "—", "plus faible")],
            "lecture": "Les 12 premiers de la zone, et leur score national à côté."}


# =============================================================================================
# Onglet Comparer : deux zones côte à côte (bureaux, communes, circonscriptions, cantons… même de niveaux différents)
# =============================================================================================

COULEURS_AB = [C["primaire"], "#FC5D00"]
TAUX_COMPARES = ["Participation", "Abstention", "Blancs", "Nuls"]


def _deux_zones(fig, ctx):
    z = list(ctx.comparaison or [])
    if len(z) < 2:
        deja = f"Zone A : {z[0].libelle}. " if z else ""
        vide(fig, deja + "Ajoute " + ("une 2e zone" if z else "deux zones") + " à la comparaison :\n"
             "sur la carte, clique une zone puis « Comparer » (fiche de droite),\n"
             "ou choisis-la dans le volet Zone puis « Ajouter la zone choisie » (réglages, à droite).")
        return None
    return z


def comparer_zones(fig, ctx):
    z = _deux_zones(fig, ctx)
    if z is None:
        return {"legende": [], "kpi": [], "lecture": "Deux zones à ajouter (voir le message)."}
    noms = [court(x.libelle, 28) for x in z]
    t = [d.totaux(ctx.scrutin, x) for x in z]
    r = [d.resultats(ctx.scrutin, x, ctx.regroupement).set_index("qui")["pct"] for x in z]
    qui = list(dict.fromkeys(list(r[0].head(8).index) + list(r[1].head(8).index)))[:10]
    horizontal = ctx.forme == "barres_h"
    g1, g2 = fig.add_gridspec(1, 2, width_ratios=[1, 2.2])
    ax1, ax2 = fig.add_subplot(g1), fig.add_subplot(g2)
    taux = pd.DataFrame({"taux": TAUX_COMPARES * 2, "valeur": [t[0].get(k) for k in TAUX_COMPARES] + [t[1].get(k) for k in TAUX_COMPARES],
                         "zone": [noms[0]] * 4 + [noms[1]] * 4})
    barres_groupees(ax1, taux, "taux", "valeur", "zone", COULEURS_AB, horizontal)
    ax1.set_xlabel(""); ax1.set_ylabel("" if horizontal else "%")
    ax1.set_title("Participation (% des inscrits)\nblancs et nuls (% des votants)", loc="left", fontsize=T(9))
    scores = pd.DataFrame({"qui": [court(q, 20) for q in qui] * 2, "valeur": list(r[0].reindex(qui).fillna(0)) + list(r[1].reindex(qui).fillna(0)),
                           "zone": [noms[0]] * len(qui) + [noms[1]] * len(qui)})
    barres_groupees(ax2, scores, "qui", "valeur", "zone", COULEURS_AB, horizontal)
    ax2.set_xlabel(""); ax2.set_ylabel("" if horizontal else "% des exprimés")
    ax2.set_title(f"Scores ({ctx.regroupement.lower()}, % des exprimés)", loc="left", fontsize=T(9))
    for ax in (ax1, ax2):
        if not horizontal:
            ax.tick_params(axis="x", labelsize=T(8), rotation=35)
            for lab in ax.get_xticklabels():
                lab.set_ha("right")
        else:
            ax.tick_params(axis="y", labelsize=T(8))
    fig.suptitle(f"{noms[0]}  vs  {noms[1]} — {d.libelle(ctx.scrutin)}", x=0.01, ha="left", fontsize=T(12), weight="bold")
    fig.tight_layout()
    ecart = (r[0].reindex(qui).fillna(0) - r[1].reindex(qui).fillna(0))
    return {"legende": [(noms[0], COULEURS_AB[0]), (noms[1], COULEURS_AB[1])],
            "kpi": [(fmt((t[0].get("Participation") or np.nan) - (t[1].get("Participation") or np.nan), 1, " pts"), "écart de participation"),
                    (court(ecart.abs().idxmax(), 14) if len(ecart) else "—", "le plus grand écart"),
                    (fmt(ecart.abs().max(), 1, " pts") if len(ecart) else "—", "d'écart")],
            "lecture": f"A = {z[0].libelle} · B = {z[1].libelle}. Les deux zones peuvent être de niveaux différents (un bureau et une commune…)."}


def comparer_dans_le_temps(fig, ctx):
    z = _deux_zones(fig, ctx)
    if z is None:
        return {"legende": [], "kpi": [], "lecture": "Deux zones à ajouter (voir le message)."}
    ind = ctx.options.get("indicateur", "Abstention")
    ax = fig.add_subplot()
    series = []
    for x, coul in zip(z, COULEURS_AB):
        s = d.serie_taux(x, ind, tour=1).set_index("date")["valeur"]
        s.index = pd.to_datetime(s.index)
        series.append(s)
        ax.plot(s.index, s.values, "o-", color=coul, lw=1.6, ms=4, label=court(x.libelle, 28))
    axe_dates(ax)
    ax.set_ylabel(f"{ind} (%)")
    titre(ax, f"{ind} à chaque élection (1er tour) : les deux zones", f"A = {court(z[0].libelle, 40)} · B = {court(z[1].libelle, 40)}")
    fig.tight_layout()
    ecart = (series[0] - series[1]).dropna()
    return {"legende": [(court(z[0].libelle, 22), COULEURS_AB[0]), (court(z[1].libelle, 22), COULEURS_AB[1])],
            "kpi": [(fmt(ecart.mean(), 1, " pts"), "écart moyen A − B"), (fmt(ecart.max(), 1, " pts"), "plus grand"),
                    (str(len(ecart)), "élections communes")],
            "lecture": "Un point = une élection (1er tour). Un bureau renuméroté manque à certaines dates."}


# =============================================================================================
# Onglet Sièges : qui siège ? (les sièges recalculés avec les règles du code électoral, voir sieges.py)
# =============================================================================================

def _departement_de(zone):
    if zone.niveau == "departement":
        return zone.code
    if zone.niveau in ("france", "region"):
        return None
    return d.ou_est(zone)["dp"]


def _region_de(zone):
    if zone.niveau == "region":
        return zone.code
    if zone.niveau == "france":
        return None
    return d.ou_est(zone)["r"]


def _commune_de(zone):
    if zone.niveau in ("commune", "bureau"):
        return str(zone.code).split("_")[0]
    return None


def _ville_plm(arrondissement):
    """« 75117 » → « 75056 » (Paris), « 69383 » → Lyon, « 13207 » → Marseille."""
    return {"751": "75056", "693": "69123", "132": "13055"}.get(str(arrondissement)[:3])


def _conseil_plm(s, base, com, arrondissement):
    """Paris, Lyon, Marseille : toute la ville (les sièges réunis par nuance) ou, avec un arrondissement, les listes de son
    secteur (avant 2026 ; ensuite toute la ville, seule élue au conseil municipal)."""
    m = sieges.conseil_plm(base, com, arrondissement if int(s[:4]) < 2026 else None)
    if m is None:
        return {"message": "Pas de résultats pour cette ville à ce scrutin."}
    r, n, noms, note = m
    r = r[r["sieges"] > 0]
    secteur = arrondissement and int(s[:4]) < 2026
    par_nuance = not secteur and int(s[:4]) < 2026        # (vingt secteurs : les listes réunies par nuance)
    if par_nuance:
        groupes = r.groupby("nuance", dropna=False)["sieges"].sum().reset_index().assign(groupe=lambda x: x["nuance"].fillna("?"))
    else:                                                  # (une seule élection : les listes, avec leur nuance)
        groupes = r[["qui", "sieges", "nuance"]].rename(columns={"qui": "groupe"})
    # chaque siège : l'élu (les premiers de sa liste) et, d'après le Répertoire national des élus, s'il siège encore
    en_place, quand = _en_place_rne(s, com)
    nuance = dict(zip(r["qui"], r["nuance"]))
    elus = pd.DataFrame({
        "qui": noms["elu"],
        "etiquette": [nuance.get(l) if par_nuance else l for l in noms["liste"]],
        "lieu": [f"{x} · " + (f"siège en {quand} (RNE)" if d.normaliser(q) in en_place else f"ne siège plus en {quand}")
                 if quand else x for x, q in zip(noms["secteur"], noms["elu"])],
        "tour": int(r["tour"].iloc[0][-1]) if len(r) else 1, "pct": np.nan})
    titre = (f"Conseil municipal {s[:4]} – {d.nom_zone('commune', com)}"
             + (f" – élus du secteur {r['secteur'].iloc[0]}" if secteur and len(r) else ""))
    if quand:
        note += f" Élus : les premiers de chaque liste ; « siège en {quand} » d'après le Répertoire national des élus."
    return {"titre": titre, "groupes": groupes[["groupe", "sieges", "nuance"]], "elus": elus,
            "regroupement": "Nuance" if par_nuance else "Candidat / liste", "note": note}


def _en_place_rne(s, com):
    """Les noms (normalisés) des conseillers municipaux en place d'après le RNE le plus proche de ce scrutin, et sa date."""
    from politique import rne
    c = rne.conseil(s.replace("_2t", "_t1"), d.Zone("commune", com, d.nom_zone("commune", com)))
    if "elus" not in c:
        return set(), None
    t = c["elus"]
    return {d.normaliser(f"{p} {n}") for p, n in zip(t["prenom"].fillna(""), t["nom"])}, rne.LIBELLES[c["version"]]


def assemblee(ctx):
    """L'assemblée élue par ce scrutin, dans la zone choisie : dict(titre, groupes, elus, note) ou dict(message)."""
    s, t, z = ctx.scrutin, d.type_de(ctx.scrutin), ctx.zone
    base = s.replace("_2t", "_t1")
    if t == "Législatives" and int(s[:4]) < 2002:
        return {"message": "Avant 2002, les résultats sont par commune ou par circonscription sans les bureaux : l'Assemblée "
                           "élue se voit dans la pastille « Législature » (1958 → aujourd'hui), siège par siège."}
    if t == "Législatives":
        a = sieges.assemblee_nationale(base)
        groupes = a.groupby("nuance").size().rename("sieges").reset_index().rename(columns={"nuance": "groupe"})
        dep = _departement_de(z)
        elus = a[a["dep"] == dep] if dep else a
        elus = elus.assign(lieu=elus["nom"], etiquette=elus["nuance"])[["lieu", "qui", "etiquette", "tour", "pct"]]
        return {"titre": f"Assemblée nationale élue en {s[:4]}", "groupes": groupes, "elus": elus, "regroupement": "Nuance",
                "note": f"{len(a)} circonscriptions reconstituées (bureaux reliés par leurs candidats). "
                        "Couleurs = nuances du ministère, pas les groupes formés ensuite à l'Assemblée."
                        + (f" Liste des élus : {z.libelle}." if dep else " Choisis un département pour la liste de ses élus.")}
    if t in ("Départementales", "Cantonales"):
        dep = _departement_de(z)
        if not dep:
            return {"message": "Choisis un département (volet Zone) : c'est son conseil départemental qui s'affiche."}
        c = sieges.conseils_departementaux(base)
        c = c[c["dep"] == dep]
        groupes = c.groupby("nuance")["sieges"].sum().reset_index().rename(columns={"nuance": "groupe"})
        elus = c.assign(lieu=c["nom"], etiquette=c["nuance"])[["lieu", "qui", "etiquette", "tour", "pct"]]
        quoi = "Conseil départemental" if t == "Départementales" else "Conseillers généraux élus en"
        return {"titre": f"{quoi} {s[:4]} – {d.nom_zone('departement', dep)}",
                "groupes": groupes, "elus": elus, "regroupement": "Nuance",
                "note": "Un binôme (une femme, un homme) par canton : 2 sièges." if t == "Départementales"
                        else "Cantonales : un conseiller par canton, renouvellement par moitié — seuls les élus de CE scrutin."}
    if t == "Régionales":
        reg = _region_de(z)
        if not reg:
            return {"message": "Choisis une région (volet Zone) : c'est son conseil régional qui s'affiche."}
        r = sieges.conseil_regional(base, reg)
        if r is None:
            return {"message": "Conseils régionaux recalculés pour 2015 et 2021 (régions actuelles) seulement."}
        tour, listes, n = r
        groupes = listes[listes["sieges"] > 0][["qui", "sieges", "nuance"]].rename(columns={"qui": "groupe"})
        elus = listes.assign(lieu="", etiquette=listes["nuance"], tour=int(tour[-1]))[["lieu", "qui", "etiquette", "tour", "pct", "sieges"]]
        nom = d.nom_zone("region", reg)
        return {"titre": f"Conseil régional {s[:4]} – {nom}", "groupes": groupes, "elus": elus, "regroupement": "Candidat / liste",
                "note": f"{n} sièges : prime de 25 % à la liste en tête, le reste à la plus forte moyenne (listes ≥ 5 %), "
                        f"décidé au {'1er' if tour.endswith('t1') else '2nd'} tour. (La répartition entre départements n'est pas faite.)"}
    if t == "Municipales":
        com = _commune_de(z)
        plm = {"75": "75056"}.get(z.code) if z.niveau == "departement" else _ville_plm(z.code) if z.niveau == "arrmun" else None
        if com in d.VILLES_PLM or plm:
            return _conseil_plm(s, base, com or plm, z.code if z.niveau == "arrmun" else None)
        if not com:
            return {"message": "Choisis une commune (volet Zone, ou 🔎 Commune) : c'est son conseil municipal qui s'affiche."}
        m = sieges.conseil_municipal(base, com)
        if m is None:
            return {"message": "Conseil municipal calculable de 2008 à 2026, hors Paris, Lyon et Marseille (élus par secteur : "
                               "voir « Conseil en place »)." if com in d.VILLES_PLM else "Pas de résultats pour cette commune à ce scrutin."}
        tour, listes, n, elus_noms = m
        groupes = listes[listes["sieges"] > 0][["qui", "sieges", "nuance"]].rename(columns={"qui": "groupe"})
        elus = elus_noms.assign(lieu=elus_noms["liste"], qui=elus_noms["elu"], etiquette=elus_noms["ordre"].astype(str), tour=int(tour[-1]), pct=np.nan)
        nom = d.nom_zone("commune", com)
        taille = ("nombre publié par le ministère" if com in sieges.sieges_officiels(int(s[:4])) else
                  "taille légale selon la population Insee, CGCT art. L2121-2")
        return {"titre": f"Conseil municipal {s[:4]} – {nom}", "groupes": groupes, "elus": elus[["lieu", "qui", "etiquette", "tour", "pct"]],
                "regroupement": "Candidat / liste",
                "note": (f"{n} sièges ({taille}) : petite commune, chaque candidat "
                         "est élu pour lui-même — majorité absolue et 25 % des inscrits au 1er tour, les mieux placés au 2nd."
                         if listes["sieges"].max() <= 1 and len(elus_noms) and (elus_noms["liste"] == elus_noms["elu"]).all() else
                         f"{n} sièges ({taille}) : "
                         f"prime de 50 % à la liste en tête, le reste à la plus forte moyenne (listes ≥ 5 %), décidé au "
                         f"{'1er' if tour.endswith('t1') else '2nd'} tour. "
                         + ("Élus = les premiers de chaque liste." if len(elus_noms) else
                            "Les listes déposées de cette année ne sont pas dans la base : pas de noms d'élus."))}
    if t == "Européennes":
        e = sieges.delegation_europeenne(base)
        if e is None:
            return {"message": "Délégation française au Parlement européen : 2019 et 2024 (circonscription nationale unique)."}
        listes, n = e
        groupes = listes[listes["sieges"] > 0][["qui", "sieges", "nuance"]].rename(columns={"qui": "groupe"})
        elus = listes.assign(lieu="", etiquette=listes["nuance"].fillna(""), tour=1)[["lieu", "qui", "etiquette", "tour", "pct", "sieges"]]
        return {"titre": f"Eurodéputés français élus en {s[:4]}", "groupes": groupes, "elus": elus, "regroupement": "Candidat / liste",
                "note": f"{n} sièges à la plus forte moyenne entre les listes ≥ 5 % des exprimés."}
    if t == "Sénatoriales":
        return {"message": "Le Sénat est renouvelé par moitié, au suffrage indirect : la pastille « Sénat actuel » montre sa composition."}
    return {"message": "Pas d'assemblée élue à ce scrutin : choisis des législatives, départementales, régionales, municipales ou européennes."}


def ronds_qui_se_touchent(fig, ax, n, points, anneaux=None, contour=0.14, facteurs=None):
    """Après la mise en page : le diamètre des sièges = l'écart entre deux sièges voisins (en points d'écran).
    Les ronds se touchent, quel que soit le nombre de sièges ou la taille de la fenêtre."""
    # l'écart = la distance entre les deux sièges les plus proches (plafonnée : un petit conseil n'a pas des ronds géants)
    xy = np.asarray(points.get_offsets(), dtype=float)
    if len(xy) > 1:
        dist = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
        np.fill_diagonal(dist, np.inf)
        ecart = min(float(dist.min()), 0.24)
    else:
        ecart = 0.24
    # et de la place autour pour que les ronds du bord ne soient pas coupés
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    if len(xy):
        x0, x1 = min(x0, xy[:, 0].min() - ecart / 2), max(x1, xy[:, 0].max() + ecart / 2)
        y0, y1 = min(y0, xy[:, 1].min() - ecart / 2), max(y1, xy[:, 1].max() + ecart / 2)
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    boite = ax.get_position()
    largeur = (getattr(fig, "largeur_visible", 0) or fig.get_figwidth() * fig.dpi) / fig.dpi
    hauteur = (getattr(fig, "hauteur_visible", 0) or fig.get_figheight() * fig.dpi) / fig.dpi
    par_unite = min(boite.width * largeur * 72 / (x1 - x0), boite.height * hauteur * 72 / (y1 - y0))
    diametre = 0.96 * ecart * par_unite
    if facteurs is None:
        points.set_sizes([diametre ** 2])
    else:                       # (chaque rond sa taille : 1 = gros rond, 0,4 = petite pastille)
        points.set_sizes((diametre * np.asarray(facteurs, dtype=float)) ** 2)
    points.set_linewidths(max(0.6, diametre * contour))
    if anneaux is not None:
        anneaux.set_sizes([(diametre * 1.5) ** 2]); anneaux.set_linewidths(max(1.5, diametre * 0.18))
    return diametre


def positions_hemicycle(n):
    """Les places d'un hémicycle de n sièges, rangées de gauche à droite (angle de 180° à 0°)."""
    rangs = max(1, int(round(math.sqrt(n / 3.5))))
    rayons = np.linspace(0.42, 1.0, rangs) if rangs > 1 else np.array([1.0])
    parts = rayons / rayons.sum() * n
    nb = np.floor(parts).astype(int)
    for i in np.argsort(-(parts - nb))[: n - nb.sum()]:
        nb[i] += 1
    places = []
    for r, k in zip(rayons, nb):
        angles = np.linspace(math.pi, 0, k) if k > 1 else np.array([math.pi / 2])
        places += [(a, r) for a in angles]
    places.sort(key=lambda p: (-p[0], p[1]))
    return places


def hemicycle(fig, ctx):
    a = assemblee(ctx)
    if "message" in a:
        return vide(fig, a["message"]) or {"legende": [], "kpi": [], "lecture": a["message"]}
    g = a["groupes"]
    g = g[g["sieges"] > 0].copy()
    reg = a["regroupement"]
    nuance = g["nuance"] if "nuance" in g else g["groupe"]
    g["rang"] = [theme.rang_politique(n, mots=False) if n == n and n else theme.rang_politique(q) for n, q in zip(nuance, g["groupe"])]
    g = g.sort_values(["rang", "sieges"], ascending=[True, False])
    g["couleur"] = couleurs_pour(ctx.scrutin.replace("_2t", "_t1") if reg == "Nuance" else ctx.scrutin, reg, list(g["groupe"]))
    if reg != "Nuance":       # les listes : la couleur de leur nuance quand le nom seul ne dit rien
        nuance = g["nuance"] if "nuance" in g else g["groupe"]      # (relue APRÈS le tri, pour rester alignée)
        g["couleur"] = [theme.couleur_politique(n, mots=False) or c for n, c in zip(nuance, g["couleur"])]
    n = int(g["sieges"].sum())
    donnees(g[["groupe", "sieges"]].assign(nuance=nuance.values if hasattr(nuance, "values") else None))
    places = positions_hemicycle(n)
    couleurs = [c for c, k in zip(g["couleur"], g["sieges"]) for _ in range(int(k))]
    # qui est assis sur chaque siège : les élus du groupe (scrutin uninominal), sinon la liste et le rang de l'élu dans la liste
    e = a.get("elus")
    if d.type_de(ctx.scrutin) == "Législatives" and ctx.zone.niveau != "france":
        # l'hémicycle montre TOUTE l'Assemblée : les noms de tous les députés, pas seulement ceux de la zone choisie
        e = assemblee(dataclasses.replace(ctx, zone=d.FRANCE)).get("elus", e)
    occupants = []
    for groupe, k, coul in zip(g["groupe"], g["sieges"], g["couleur"]):
        noms = []
        if e is not None and "sieges" not in e:
            x_ = e[e["etiquette"].astype(str) == str(groupe)] if "etiquette" in e else e.iloc[0:0]
            noms = [(str(q), str(l)) for q, l in zip(x_["qui"], x_["lieu"])]
        for i in range(int(k)):
            nom, lieu = noms[i] if i < len(noms) else (str(groupe), f"{i + 1}{'er' if i == 0 else 'e'} siège de la liste" if e is not None and "sieges" in e else "")
            occupants.append({"nom": nom, "groupe": str(groupe), "lieu": lieu, "couleur": coul})
    ax = fig.add_subplot()
    x = [r * math.cos(t) for t, r in places]
    y = [r * math.sin(t) for t, r in places]
    points = ax.scatter(x, y, c=couleurs, s=10, edgecolors="white", zorder=3, picker=True)
    points.sieges_occupants = occupants
    majorite = n // 2 + 1
    ax.text(0, 0.08, f"{n} sièges", ha="center", fontsize=T(16), weight="bold", color=C["texte"])
    ax.text(0, -0.04, f"majorité absolue : {majorite}", ha="center", fontsize=T(10), color=C["gris"])
    ax.set_xlim(-1.08, 1.08); ax.set_ylim(-0.12, 1.08)
    ax.set_aspect("equal"); ax.axis("off")
    titre(ax, a["titre"], f"{d.type_de(ctx.scrutin)} {ctx.scrutin[:4]} · sièges attribués après le tour décisif · de gauche à droite"
                          " · clique sur un siège")
    fig.tight_layout()
    ronds_qui_se_touchent(fig, ax, n, points, contour=0.08)
    premier = g.sort_values("sieges", ascending=False).iloc[0]
    # une liste ou un candidat : sa nuance devant (« LUG · Julien BAYOU — 53 ») ; l'info-bulle de la légende l'explique
    devant = [f"{n} · " if reg != "Nuance" and isinstance(n, str) and n and n != q else "" for n, q in zip(nuance, g["groupe"])]
    return {"legende": [(f"{v}{court(q, 22)} — {int(k)}", c) for v, q, k, c in zip(devant, g["groupe"], g["sieges"], g["couleur"])],
            "kpi": [(str(int(premier["sieges"])), court(premier["groupe"], 16)), (str(majorite), "majorité absolue"), (str(len(g)), "groupes")],
            "lecture": a["note"]}


def elus(fig, ctx):
    a = assemblee(ctx)
    if "message" in a:
        return vide(fig, a["message"]) or {"legende": [], "kpi": [], "lecture": a["message"]}
    e = a["elus"]
    donnees(e)
    avec_sieges = "sieges" in e
    ax = fig.add_subplot()
    ax.axis("off")
    if avec_sieges:       # scrutin de listes : une ligne par liste
        lignes = [[court(q, 46), str(x), fmt(p), str(int(k))] for q, x, p, k in zip(e["qui"], e["etiquette"], e["pct"], e["sieges"])]
        entetes, largeurs = ["Liste", "Nuance", "% exprimés", "Sièges"], [0.52, 0.14, 0.16, 0.12]
    else:
        lignes = [[court(l, 38), court(q, 42), str(x), f"{int(t)}er" if t == 1 else f"{int(t)}nd", fmt(p) if p == p else ""]
                  for l, q, x, t, p in zip(e["lieu"], e["qui"], e["etiquette"], e["tour"], e["pct"])]
        entetes, largeurs = ["Circonscription / canton / liste", "Élu(e)", "Nuance / rang", "Tour", "%"], [0.34, 0.36, 0.12, 0.07, 0.08]
    if not lignes:
        return vide(fig, "Aucun élu pour cette zone.") or {"legende": [], "kpi": [], "lecture": ""}
    if len(lignes) > LIGNES_SANS_ASCENSEUR:
        hauteur_liste(fig, len(lignes), 0.26)
    t = ax.table(cellText=lignes, colLabels=entetes, loc="upper center", cellLoc="left", colLoc="left", colWidths=largeurs)
    t.auto_set_font_size(False); t.set_fontsize(T(10)); t.scale(1, 1.3 * theme.ZOOM)
    couleurs = {x: theme.couleur_politique(x, mots=False) for x in set(e["etiquette"])}
    for (r, c), cell in t.get_celld().items():
        cell.set_edgecolor(C["bordure"])
        if r == 0:
            cell.set_facecolor(C["surface"]); cell.set_text_props(weight="bold")
        elif c == (1 if avec_sieges else 2) and couleurs.get(str(lignes[r - 1][c])):
            cell.set_facecolor(couleurs[str(lignes[r - 1][c])]); cell.set_text_props(color=theme.texte_sur(couleurs[str(lignes[r - 1][c])]), weight="bold")
    titre(ax, a["titre"] + (" — les listes" if avec_sieges else " — les élus"), f"{d.type_de(ctx.scrutin)} {ctx.scrutin[:4]}")
    if len(lignes) > LIGNES_SANS_ASCENSEUR:
        fig.set_layout_engine("tight")
    else:
        fig.tight_layout()
    return {"legende": [], "kpi": [(str(len(lignes)), "lignes")], "lecture": a["note"]}


# --- Le Parlement d'aujourd'hui : la vraie composition (groupes), les places, les photos ------------------------

def _legende_groupes(t):
    c = t.groupby(["rang", "groupe", "couleur"]).size().reset_index(name="n").sort_values("rang")
    return [(f"{g} — {n}", col) for g, col, n in zip(c["groupe"], c["couleur"], c["n"])]


def _hemicycle_elus(fig, ctx, t, places, titre_, sous, chambre):
    """Un point par élu, à sa place ; ceux de la zone choisie ressortent (les autres pâlissent). Clic = sa fiche."""
    zone, avec_zone = parlement.de_la_zone(t, ctx.zone, chambre)
    ax = fig.add_subplot()
    x = np.array([r * math.cos(a) for a, r in places]); y = np.array([r * math.sin(a) for a, r in places])
    n = len(places)
    taille = max(10, min(300, 24000 / n))
    vides = sorted(set(range(n)) - set(t["indice"]))
    ax.scatter(x[vides], y[vides], s=taille, c=C["surface"], edgecolors=C["bordure"], linewidths=0.4, zorder=2)
    alpha = [1.0 if (not avec_zone or i in zone.index) else 0.3 for i in t.index]
    couleurs = [mcolors.to_rgba(c, a) for c, a in zip(t["couleur"], alpha)]
    points = ax.scatter(x[t["indice"]], y[t["indice"]], s=taille, c=couleurs, edgecolors="white", linewidths=0.5, zorder=3, picker=True)
    points.parlementaires = (chambre, list(t.index))
    anneaux = None
    if avec_zone:
        anneaux = ax.scatter(x[zone["indice"]], y[zone["indice"]], s=taille * 1.6, facecolors="none", edgecolors=C["texte"], linewidths=1.4, zorder=4)
    ax.text(0, 0.08, f"{len(t)} {('députés' if chambre == 'Assemblée nationale' else 'sénateurs')}", ha="center", fontsize=T(15), weight="bold")
    ax.text(0, -0.04, f"majorité absolue : {len(t) // 2 + 1}", ha="center", fontsize=T(10), color=C["gris"])
    ax.set_xlim(-1.08, 1.08); ax.set_ylim(-0.12, 1.08); ax.set_aspect("equal"); ax.axis("off")
    titre(ax, titre_, sous + (f" · entourés : {ctx.zone.libelle}" if avec_zone else " · clique sur un siège pour la fiche (et la photo)"))
    fig.tight_layout()
    diametre = ronds_qui_se_touchent(fig, ax, n, points, anneaux, contour=0.08)
    if vides:          # les sièges vacants : même taille, en creux
        ax.collections[0].set_sizes([diametre ** 2]); ax.collections[0].set_linewidths(max(0.6, diametre * 0.08))
    return zone, avec_zone


def assemblee_actuelle(fig, ctx):
    if not parlement.disponible():
        return vide(fig, "Les députés ne sont pas dans la base : lance donnees/parlement/parlement.py puis base_appli.py.")
    t = parlement.deputes().copy()
    # l'ordre des groupes vient des vraies places (650 = tout à gauche … 1 = tout à droite) ; chaque groupe forme un secteur
    milieu = t.groupby("groupe")["place"].median()
    t["cote"] = -t["groupe"].map(milieu).astype(float)
    t = t.sort_values(["cote", "place"], ascending=[True, False])
    t["indice"] = range(len(t))
    donnees(t[["prenom", "nom", "groupe", "lieu", "place"]].rename(columns={"prenom": "prénom", "lieu": "circonscription"}))
    places = sorted(positions_hemicycle(577), key=lambda p: -p[0])           # 577 sièges ; les sièges vacants restent vides
    zone, avec = _hemicycle_elus(fig, ctx, t, places, "Assemblée nationale aujourd'hui (17e législature)",
                                 "par groupe, de gauche à droite comme dans la salle", "Assemblée nationale")
    groupe1 = t["groupe"].value_counts()
    return {"legende": _legende_groupes(t), "kpi": [(str(groupe1.iloc[0]), groupe1.index[0]), (str(len(t)), "députés en exercice"),
                                                   (str(len(zone)) if avec else str(577 - len(t)), "dans la zone" if avec else "sièges vacants")],
            "lecture": "Groupes : Assemblée nationale (open data). L'ordre des groupes vient des vraies places (le numéro officiel est dans "
                       "la fiche de chaque député). Choisis un département pour voir ses députés."}


def senat_actuel(fig, ctx):
    if not parlement.disponible():
        return vide(fig, "Les sénateurs ne sont pas dans la base : lance donnees/parlement/parlement.py puis base_appli.py.")
    t = parlement.senateurs().sort_values(["rang", "nom"]).copy()
    t["indice"] = range(len(t))
    donnees(t[["prenom", "nom", "groupe", "lieu"]].rename(columns={"prenom": "prénom", "lieu": "département"}))
    places = sorted(positions_hemicycle(len(t)), key=lambda p: -p[0])
    zone, avec = _hemicycle_elus(fig, ctx, t, places, "Sénat aujourd'hui", "par groupe, de gauche à droite (places non publiées)", "Sénat")
    g1 = t["groupe"].value_counts()
    return {"legende": _legende_groupes(t), "kpi": [(str(g1.iloc[0]), court(g1.index[0], 16)), (str(len(t)), "sénateurs"),
                                                   (str(len(zone)) if avec else str(len(g1)), "dans la zone" if avec else "groupes")],
            "lecture": "Groupes : Sénat (open data). Le Sénat ne publie pas les places : les sénateurs sont rangés par groupe, de gauche à droite. "
                       "Élus au suffrage indirect (grands électeurs) : voir les sénatoriales dans Scrutin."}


def trombinoscope(fig, ctx):
    if not parlement.disponible():
        return vide(fig, "Les photos ne sont pas là : lance donnees/parlement/parlement.py puis base_appli.py.")
    chambre = ctx.options.get("chambre", "Assemblée nationale")
    t = parlement.deputes() if chambre == "Assemblée nationale" else parlement.senateurs()
    t, avec = parlement.de_la_zone(t, ctx.zone, chambre)
    if not len(t):
        return vide(fig, f"Aucun élu de la zone « {ctx.zone.libelle} ».")
    colonnes = 10 if len(t) > 20 else max(4, len(t))
    donnees(t[["prenom", "nom", "groupe", "lieu"]].rename(columns={"prenom": "prénom", "lieu": "élu(e) de"}))       # (l'image, en mots)
    image, ids, (lc, hc, nc) = parlement.mosaique(t, colonnes)
    titre_ = f"Trombinoscope — {chambre}" + (f" — {ctx.zone.libelle}" if avec else "")
    if len(t) > 20:       # beaucoup d'élus : une figure aussi haute que la mosaïque (au pixel près), avec l'ascenseur
        largeur = fig.get_figwidth() * fig.dpi * 0.96
        haut, bas = 50, 10
        h = int(image.shape[0] * largeur / image.shape[1]) + haut + bas
        fig.hauteur_voulue = h
        ax = fig.add_axes([0.02, bas / h, 0.96, (h - haut - bas) / h])
        vue = ax.imshow(image, interpolation="lanczos", picker=True, aspect="auto")
        fig.text(0.02, 1 - 32 / h, titre_, fontsize=T(13), weight="bold")
    else:
        ax = fig.add_axes([0.02, 0.01, 0.96, 0.88])
        vue = ax.imshow(image, interpolation="lanczos", picker=True)
        fig.suptitle(titre_, x=0.02, ha="left", fontsize=T(13), weight="bold")
    vue.trombi = (chambre, ids, lc, hc, nc)
    ax.axis("off")
    return {"legende": _legende_groupes(t), "kpi": [(str(len(t)), "élus"), (str(t["groupe"].nunique()), "groupes")],
            "lecture": "Photos officielles (Assemblée nationale, Sénat). Clique sur une photo pour la fiche. Choisis un département pour ses seuls élus."}


# --- Les votes des députés : qui a voté quoi (onglet Votes) --------------------------------------------------------

def _vote_choisi(fig, ctx):
    """Le scrutin choisi et ses votes ; (None, None) avec un message dessiné s'il n'y a rien à montrer."""
    if not votes_deputes.disponible():
        vide(fig, "Les votes ne sont pas dans la base : lance les scripts de donnees/votes/ puis base_appli.py.")
        return None, None
    sid = ctx.options.get("vote") or votes_deputes.GRANDS_VOTES[17][1]
    s = votes_deputes.scrutin(sid)
    if s is None:
        vide(fig, "Scrutin introuvable.")
        return None, None
    t = legislatures.votes_complets(sid) if legislatures.disponible() else votes_deputes.votes(sid)
    if t.empty:
        ax = fig.add_subplot(); ax.axis("off")
        ax.text(0.5, 0.62, f"{int(s['pour'])} pour   ·   {int(s['contre'])} contre", ha="center", fontsize=T(22), weight="bold", color=C["texte"])
        ax.text(0.5, 0.45, "La liste nominative existe dans le Journal officiel (PDF numérisé), mais la machine la lit encore avec des\n"
                           "colonnes mélangées : plutôt que d'afficher un vote faux, seul le résultat officiel est montré.",
                ha="center", fontsize=T(10), color=C["gris"])
        titre(ax, votes_deputes.libelle(sid), f"{s['date']:%d/%m/%Y} · {s['objet']}")
        return s, None
    donnees(t[["depute", "groupe", "position", "lieu"]].rename(columns={"depute": "député", "position": "vote", "lieu": "circonscription"}))
    return s, t


def _kpi_vote(s, t):
    return [(str(int(s["pour"])), "pour"), (str(int(s["contre"])), "contre"),
            (str(int((t["position"] == "abstention").sum())), "abstentions")]


def vote_hemicycle(fig, ctx):
    s, t = _vote_choisi(fig, ctx)
    if t is None:
        return {"legende": [], "kpi": [], "lecture": ""}
    n = len(t)
    places = sorted(positions_hemicycle(n), key=lambda p: -p[0])        # de gauche à droite, groupe après groupe
    x = np.array([r * math.cos(a) for a, r in places]); y = np.array([r * math.sin(a) for a, r in places])
    ax = fig.add_subplot()
    cherche = d.normaliser(ctx.options.get("depute", ""))
    ressort = t["depute"].map(d.normaliser).str.contains(cherche, regex=False) if cherche else pd.Series(False, index=t.index)
    absent = t["position"].isin(votes_deputes.ABSENTS).values
    # présent (pour, contre, abstention, non-votant) : gros rond de la couleur du vote ; absent : petite pastille de la couleur du groupe
    points = ax.scatter(x, y, s=10, c=[c if a_ else votes_deputes.POSITIONS.get(p, C["gris"]) for p, c, a_ in zip(t["position"], t["couleur"], absent)],
                        edgecolors=[C["carte"] if a_ else c for c, a_ in zip(t["couleur"], absent)], zorder=3, picker=True)
    points.votants = (s["scrutin"], list(t.index))
    anneau = ax.scatter(x[ressort.values], y[ressort.values], s=10, facecolors="none", edgecolors=C["texte"], zorder=4) if ressort.any() else None
    centre = min(theme.ZOOM, 1.15)          # (le texte du centre doit tenir dans le trou de l'hémicycle)
    ax.text(0, 0.16, f"{int(s['pour'])} pour · {int(s['contre'])} contre", ha="center", fontsize=15 * centre, weight="bold", color=C["texte"])
    censure = "censure" in s["objet"] and int(s["contre"]) == 0
    lue = ""
    if str(s["source"]).startswith("Journal") and s.get("pour_lus") == s.get("pour_lus"):        # (NaN ≠ NaN : pas de compte)
        lue = f"\nliste lue : {int(s['pour_lus'])} pour / {int(s['pour'])}, {int(s['contre_lus'])} contre / {int(s['contre'])}"
    ax.text(0, 0.06, s["source"] + lue + ("\nmotion de censure : seuls les « pour » sont publiés" if censure else ""),
            ha="center", va="top", fontsize=9.5 * centre, color=C["gris"])
    ax.set_xlim(-1.06, 1.06); ax.set_ylim(-0.04, 1.06); ax.set_aspect("equal"); ax.axis("off")
    titre(ax, votes_deputes.libelle(s["scrutin"]), f"{s['date']:%d/%m/%Y} · gros rond = présent (couleur = son vote), petite pastille = absent · clique sur un rond")
    fig.tight_layout()
    ronds_qui_se_touchent(fig, ax, n, points, anneau, facteurs=np.where(absent, 0.42, 1.0))
    legende = [(f"{p} — {(t['position'] == p).sum()}", c) for p, c in votes_deputes.POSITIONS.items() if (t["position"] == p).any()]
    for p in votes_deputes.ABSENTS:
        if (t["position"] == p).any():
            legende.append((f"{p} (petite pastille) — {(t['position'] == p).sum()}", votes_deputes.COULEUR_ABSENT))
    g = t.drop_duplicates("groupe")
    legende += [(f"groupe {court(gr, 30)}", c) for gr, c in zip(g["groupe"], g["couleur"]) if gr != "?"]      # (« ? » : JO, groupe non lu)
    return {"legende": legende, "kpi": _kpi_vote(s, t),
            "lecture": "Les députés sont rangés par groupe, de gauche à droite (ce ne sont pas leurs vraies places). " + s["objet"]}


def vote_groupes(fig, ctx):
    s, t = _vote_choisi(fig, ctx)
    if t is None:
        return {"legende": [], "kpi": [], "lecture": ""}
    c = t.groupby(["rang", "groupe", "position"]).size().unstack(fill_value=0)
    couleurs_pos = {**votes_deputes.POSITIONS, **dict.fromkeys(votes_deputes.ABSENTS, votes_deputes.COULEUR_ABSENT)}
    c = c.reindex(columns=[p for p in couleurs_pos if p in c.columns]).sort_index(level=0, ascending=False)
    ax = fig.add_subplot()
    gauche = np.zeros(len(c))
    noms = [court(g, 34) for _, g in c.index]
    for p in c.columns:
        ax.barh(noms, c[p], left=gauche, color=couleurs_pos[p], label=p, edgecolor="white", linewidth=0.5)
        for i, (v, l) in enumerate(zip(c[p], gauche)):
            if v >= 8:
                ax.text(l + v / 2, i, str(int(v)), ha="center", va="center", fontsize=T(8), color=theme.texte_sur(couleurs_pos[p]))
        gauche += c[p].values
    couleurs_g = t.drop_duplicates("groupe").set_index("groupe")["couleur"]
    # le nom du groupe en noir (lisible), et une barrette de SA couleur juste devant les barres (repère visuel)
    for etiquette in ax.get_yticklabels():
        etiquette.set_color(C["texte"]); etiquette.set_fontweight("bold")
    marge = gauche.max() * 0.025
    ax.barh(noms, [marge] * len(c), left=-marge * 1.3, color=[couleurs_g.get(g, C["gris"]) for _, g in c.index],
            edgecolor=C["gris"], linewidth=0.6)
    ax.set_xlim(left=-marge * 1.5)
    ax.set_xlabel("députés"); ax.legend(loc="lower right", fontsize=T(8), frameon=False)
    titre(ax, votes_deputes.libelle(s["scrutin"]), f"{s['date']:%d/%m/%Y} · le vote de chaque groupe, de gauche (en haut) à droite")
    fig.tight_layout()
    return {"legende": [(p, col) for p, col in couleurs_pos.items() if p in c.columns], "kpi": _kpi_vote(s, t), "lecture": s["objet"]}


def vote_liste(fig, ctx):
    s, t = _vote_choisi(fig, ctx)
    if t is None:
        return {"legende": [], "kpi": [], "lecture": ""}
    t = t[t["depute"].notna()]
    cherche = d.normaliser(ctx.options.get("depute", ""))
    if cherche:
        t = t[t["depute"].map(d.normaliser).str.contains(cherche, regex=False)]
        if t.empty:
            return vide(fig, f"Aucun député « {ctx.options['depute']} » à ce scrutin.") or {"legende": [], "kpi": [], "lecture": ""}
    t = t.sort_values(["ordre_pos", "rang", "depute"])
    lignes = [[court(dep, 34), court(gr, 40), pos] for dep, gr, pos in zip(t["depute"], t["groupe"], t["position"])]
    ax = fig.add_subplot(); ax.axis("off")
    if len(lignes) > LIGNES_SANS_ASCENSEUR:
        hauteur_liste(fig, len(lignes), 0.26)
    tab = ax.table(cellText=lignes, colLabels=["Député(e)", "Groupe", "Vote"], loc="upper center", cellLoc="left", colLoc="left",
                   colWidths=[0.33, 0.42, 0.21])
    tab.auto_set_font_size(False); tab.set_fontsize(T(10)); tab.scale(1, 1.3 * theme.ZOOM)
    for (r, col), cell in tab.get_celld().items():
        cell.set_edgecolor(C["bordure"])
        if r == 0:
            cell.set_facecolor(C["surface"]); cell.set_text_props(weight="bold")
        elif col == 2:
            cell.set_facecolor(votes_deputes.POSITIONS.get(lignes[r - 1][2], votes_deputes.COULEUR_ABSENT))
            cell.set_text_props(color=theme.texte_sur(votes_deputes.POSITIONS.get(lignes[r - 1][2], votes_deputes.COULEUR_ABSENT)), weight="bold")
    titre(ax, votes_deputes.libelle(s["scrutin"]) + (f" — « {ctx.options['depute']} »" if cherche else ""), f"{s['date']:%d/%m/%Y} · {len(lignes)} députés")
    if len(lignes) > LIGNES_SANS_ASCENSEUR:
        fig.set_layout_engine("tight")
    else:
        fig.tight_layout()
    return {"legende": [(p, col) for p, col in votes_deputes.POSITIONS.items()], "kpi": _kpi_vote(s, t if not cherche else votes_deputes.votes(s["scrutin"])),
            "lecture": s["objet"]}


# --- Les affiches électorales des Hauts-de-Seine (onglet Affiches) ------------------------------------------------

def affiches_campagne(fig, ctx):
    if not affiches.disponible():
        return vide(fig, "Les affiches ne sont pas dans la base : lance donnees/affiches/affiches.py puis base_appli.py.")
    o = ctx.options
    t = affiches.de_la_zone(ctx.zone, o.get("affiche_type"), o.get("affiche_annee"), o.get("affiche_cherche", ""))
    donnees(t[["annee", "type", "lieu", "candidats", "description", "cote"]].rename(columns={"annee": "année", "type": "élection"}))
    if t.empty:
        msg = ("Aucune affiche pour ces réglages." if ctx.zone.niveau in ("france", "region", "departement", "commune", "bureau", "circo")
               else "Les affiches sont rangées par commune et par circonscription.")
        return vide(fig, msg + "\nLes affiches viennent des Hauts-de-Seine (92) : choisis le département, une de ses communes, "
                               "ou « France entière ».") or {"legende": [], "kpi": [], "lecture": ""}
    tronque = len(t) > affiches.MAX_MOSAIQUE
    montre = t.head(affiches.MAX_MOSAIQUE)
    colonnes = 8
    image, ids, (lc, hc, nc) = affiches.mosaique(montre, colonnes)
    # toujours la même taille de vignette (8 par rangée sur toute la largeur), qu'il y ait 3 affiches ou 240
    largeur_fig = getattr(fig, "largeur_visible", 0) or fig.get_figwidth() * fig.dpi      # (la taille finale, donnée par la fenêtre)
    visible = getattr(fig, "hauteur_visible", 0) or fig.get_figheight() * fig.dpi
    echelle = largeur_fig * 0.96 / (colonnes * lc)
    l_img, h_img = image.shape[1] * echelle, image.shape[0] * echelle
    haut, bas = 64, 16
    h = max(visible, h_img + haut + bas)
    if h > visible:
        fig.hauteur_voulue = int(h)          # une longue planche : la fenêtre ajoute l'ascenseur
    ax = fig.add_axes([0.02, 1 - (haut + h_img) / h, l_img / largeur_fig, h_img / h])
    vue = ax.imshow(image, interpolation="lanczos", picker=True, aspect="auto")
    ax.set_xlim(0, image.shape[1]); ax.set_ylim(image.shape[0], 0)
    vue.affiches = (ids, lc, hc, nc)
    ax.axis("off")
    filtre = " · ".join(x for x in (o.get("affiche_type") if o.get("affiche_type") not in (None, "Tous") else "",
                                    str(o.get("affiche_annee")) if o.get("affiche_annee") not in (None, "Toutes") else "",
                                    f"« {o['affiche_cherche']} »" if o.get("affiche_cherche") else "") if x)
    fig.text(0.02, 1 - 26 / h, f"Affiches de campagne — {ctx.zone.libelle}" + (f" — {filtre}" if filtre else ""), fontsize=T(13), weight="bold",
             color=C["texte"])
    fig.text(0.02, 1 - 46 / h, f"{len(t)} affiches{' (les ' + str(affiches.MAX_MOSAIQUE) + ' premières : filtre à droite)' if tronque else ''} · "
             f"clique sur une affiche pour la voir en grand · {affiches.CREDIT}", fontsize=T(9), color=C["gris"])
    par_type = t["type"].value_counts()
    return {"legende": [],
            "kpi": [(str(len(t)), "affiches"), (f"{t['annee'].min()}–{t['annee'].max()}", "années"), (court(par_type.index[0], 14), "le plus souvent")],
            "lecture": "Affiches officielles des campagnes dans les Hauts-de-Seine (Archives départementales, licence CC BY-NC-ND 4.0 : "
                       "montrées entières). Filtre par élection, année ou nom de candidat à droite."}


def affiches_par_annee(fig, ctx):
    if not affiches.disponible():
        return vide(fig, "Les affiches ne sont pas dans la base.")
    o = ctx.options
    t = affiches.de_la_zone(ctx.zone, None, None, o.get("affiche_cherche", ""))
    if t.empty:
        return vide(fig, "Aucune affiche pour cette zone (les affiches viennent des Hauts-de-Seine).") or {"legende": [], "kpi": [], "lecture": ""}
    c = t.groupby(["annee", "type"]).size().unstack(fill_value=0)
    donnees(c.reset_index())
    ax = fig.add_subplot()
    bas_ = np.zeros(len(c))
    for typ in c.columns:
        ax.bar(c.index.astype(str), c[typ], bottom=bas_, color=TYPES_ELECTION.get(typ, C["gris"]), label=typ, edgecolor="white", linewidth=0.5)
        bas_ += c[typ].values
    ax.legend(fontsize=T(9), frameon=False)
    ax.tick_params(axis="x", rotation=45)
    ax.set_ylabel("affiches")
    titre(ax, f"Les affiches conservées, année par année — {ctx.zone.libelle}", "Archives départementales des Hauts-de-Seine · par élection")
    fig.tight_layout()
    return {"legende": [(typ, TYPES_ELECTION.get(typ, C["gris"])) for typ in c.columns],
            "kpi": [(str(len(t)), "affiches"), (str(int(c.sum(axis=1).idxmax())), "l'année la plus fournie"), (str(c.shape[1]), "élections")],
            "lecture": "Une barre = une année ; ses couleurs = les types d'élection. Les années pleines sont les années d'élections."}


def legislature_hemicycle(fig, ctx):
    """L'Assemblée d'une législature, siège par siège : gros rond = député connu (clic = qui), petite pastille = inconnu."""
    if not legislatures.disponible():
        return vide(fig, "Les législatures ne sont pas dans la base : lance donnees/legislatures/fabriquer_legislatures.py.")
    num = legislatures.numero(ctx.options.get("legislature") or legislatures.libelles()[0])
    leg = legislatures.liste().set_index("legislature").loc[num]
    t = legislatures.sieges(num)
    donnees(t[["depute", "groupe", "lieu", "connu"]].rename(columns={"depute": "député", "connu": "nom connu"}))
    n = len(t)
    places = sorted(positions_hemicycle(n), key=lambda p: -p[0])
    x = np.array([r * math.cos(a) for a, r in places]); y = np.array([r * math.sin(a) for a, r in places])
    ax = fig.add_subplot()
    points = ax.scatter(x, y, s=10, c=list(t["couleur"]), edgecolors="white", zorder=3, picker=True)
    points.sieges_occupants = [{"nom": dep if c_ else "Député(e) non connu(e) dans nos données", "groupe": g_, "lieu": l_ or "", "couleur": col_}
                               for dep, c_, g_, l_, col_ in zip(t["depute"], t["connu"], t["groupe"], t["lieu"], t["couleur"])]
    centre = min(theme.ZOOM, 1.15)
    ax.text(0, 0.16, f"{n} sièges", ha="center", fontsize=15 * centre, weight="bold", color=C["texte"])
    ax.text(0, 0.06, f"{int(t['connu'].sum())} députés connus · {leg['source']}", ha="center", va="top", fontsize=9.5 * centre, color=C["gris"])
    ax.set_xlim(-1.06, 1.06); ax.set_ylim(-0.04, 1.06); ax.set_aspect("equal"); ax.axis("off")
    fin = "" if leg["fin"] != leg["fin"] else f"{leg['fin']:%Y}"
    titre(ax, f"Assemblée nationale — {leg['romain']}e législature ({leg['debut']:%Y}–{fin})",
          "gros rond = député connu (clique pour savoir qui), petite pastille = siège dont on ne connaît pas l'occupant · de gauche à droite")
    fig.tight_layout()
    ronds_qui_se_touchent(fig, ax, n, points, contour=0.08, facteurs=np.where(t["connu"], 1.0, 0.42))
    c = t.groupby(["rang", "groupe", "couleur"]).size().reset_index(name="k").sort_values("rang")
    return {"legende": [(f"{g_} — {k}", col_) for g_, col_, k in zip(c["groupe"], c["couleur"], c["k"]) if g_ != "?"]
                       + ([(f"inconnu — {int((t['groupe'] == '?').sum())}", "#B8BEC6")] if (t["groupe"] == "?").any() else []),
            "kpi": [(str(n), "sièges"), (str(int(t["connu"].sum())), "députés connus"), (court(c.sort_values("k").iloc[-1]["groupe"], 12), "1er groupe")],
            "lecture": "Composition au début de la législature. 2002 → aujourd'hui : groupes officiels de l'Assemblée ; 1988-2002 : élus "
                       "nommés (CDSP), avec leur nuance officielle ; 1986-1988 (proportionnelle) : élus et groupes d'après Wikidata ; "
                       "1958-1986 : le courant arrivé en tête dans chaque circonscription (CDSP) et, quand Wikidata indique sa "
                       "circonscription, le nom de l'élu (environ deux sur trois)."}


def conseil_en_place(fig, ctx, version=None):
    """Le conseil qui siège vraiment (RNE) : commune, intercommunalité, département ou région. Un rond par élu, à la couleur
    de sa liste ; dans un conseil communautaire, les élus de plusieurs communes et de plusieurs listes se mélangent.
    version : une date du RNE imposée (« Qui siège aujourd'hui ? ») ; sinon celle qui va avec l'élection choisie."""
    a = rne.conseil(ctx.scrutin, ctx.zone, version)
    if "message" in a:
        return vide(fig, a["message"]) or {"legende": [], "kpi": [], "lecture": a["message"]}
    t = a["elus"]
    donnees(t[["qui", "groupe", "lieu"] + (["liste", "nuance"] if "liste" in t else [])].rename(columns={"qui": "élu(e)", "lieu": "commune / fonction"}))
    n = len(t)
    places = sorted(positions_hemicycle(n), key=lambda p: -p[0])
    x = np.array([r * math.cos(a_) for a_, r in places]); y = np.array([r * math.sin(a_) for a_, r in places])
    ax = fig.add_subplot()
    points = ax.scatter(x, y, s=10, c=list(t["couleur"]), edgecolors="white", zorder=3, picker=True)
    points.sieges_occupants = [{"nom": q, "groupe": g_, "lieu": str(l_ or ""), "couleur": c_}
                               for q, g_, l_, c_ in zip(t["qui"], t["groupe"], t["lieu"], t["couleur"])]
    centre = min(theme.ZOOM, 1.15)
    ax.text(0, 0.16, f"{n} élus", ha="center", fontsize=15 * centre, weight="bold", color=C["texte"])
    ax.text(0, 0.06, f"majorité absolue : {n // 2 + 1}", ha="center", va="top", fontsize=9.5 * centre, color=C["gris"])
    ax.set_xlim(-1.06, 1.06); ax.set_ylim(-0.04, 1.06); ax.set_aspect("equal"); ax.axis("off")
    titre(ax, a["titre"], "un rond par élu, à la couleur de sa liste · de gauche à droite · clique sur un siège pour savoir qui")
    fig.tight_layout()
    ronds_qui_se_touchent(fig, ax, n, points, contour=0.08)
    c = t.groupby(["rang", "groupe", "couleur"], sort=False).size().reset_index(name="k").sort_values(["rang", "k"], ascending=[True, False])
    retrouves = int(t["liste"].notna().sum()) if "liste" in t else n
    return {"legende": [(f"{court(g_, 30)} — {k}", col_) for g_, col_, k in zip(c["groupe"], c["couleur"], c["k"])],
            "kpi": [(str(n), "élus"), (str(len(c)), "groupes"),
                    (f"{retrouves}/{n}", "listes retrouvées") if "liste" in t else (rne.LIBELLES[a["version"]], "RNE")],
            "lecture": a["note"]}


def profils_candidats(fig, ctx):
    """Qui sont les candidats de ce scrutin dans la zone : la pyramide des âges (femmes / hommes) et les professions."""
    t = candidats.du_scrutin(ctx.scrutin, ctx.zone)
    if t.empty:
        dispo = sorted(candidats.disponible())
        return vide(fig, "Pas de fiches de candidats pour ce scrutin.\nElles existent pour : "
                         + ", ".join(sorted({x[:4] + " " + x[5:9] for x in dispo})[:30])) or {"legende": [], "kpi": [], "lecture": ""}
    donnees(t[["nom", "prenom", "sexe", "age", "profession", "nuance", "lieu", "departement", "sortant"]])
    g1, g2 = fig.add_gridspec(1, 2, width_ratios=[1, 1.35])
    ax1, ax2 = fig.add_subplot(g1), fig.add_subplot(g2)
    tranches = list(range(18, 96, 5))
    for sexe, couleur, signe in (("F", C["action"], -1), ("M", C["primaire"], 1)):
        a = t.loc[t["sexe"] == sexe, "age"].dropna().astype(int)
        h = np.histogram(a, bins=tranches)[0]
        ax1.barh([f"{x}-{x + 4}" for x in tranches[:-1]], signe * h, color=couleur, label="femmes" if sexe == "F" else "hommes")
    ax1.axvline(0, color=C["texte"], lw=0.8)
    ax1.set_xticks(ax1.get_xticks()); ax1.set_xticklabels([str(abs(int(x))) for x in ax1.get_xticks()])
    ax1.legend(fontsize=T(9), frameon=False, loc="lower right")
    titre(ax1, "Âge des candidats", "femmes à gauche, hommes à droite")
    prof = t["profession"].dropna()
    prof = prof[~prof.str.match(r"^\(?\d+\)?$")]                    # (quelques fichiers ne donnent qu'un code)
    top = prof.value_counts().head(15)[::-1]
    ax2.barh([court(x, 40) for x in top.index], top.values, color=C["moyen"])
    for i, v in enumerate(top.values):
        ax2.text(v, i, f" {v}", va="center", fontsize=T(9), color=C["gris"])
    ax2.margins(x=0.15)
    titre(ax2, "Professions les plus fréquentes", f"{d.libelle(ctx.scrutin)} · {zone_txt(ctx)}")
    fig.tight_layout()
    femmes = (t["sexe"] == "F").mean() if t["sexe"].notna().any() else float("nan")
    return {"legende": [("femmes", C["action"]), ("hommes", C["primaire"])],
            "kpi": [(str(len(t)), "candidats"), (f"{t['age'].mean():.0f} ans" if t["age"].notna().any() else "—", "âge moyen"),
                    (fmt(100 * femmes, 0), "de femmes")],
            "lecture": "Âge le jour du vote, calculé avec la date de naissance des fichiers de candidatures (ministère de l'Intérieur). "
                       "Profession telle que déclarée par le candidat."}


def correlations(fig, ctx):
    top = d.cles(ctx.scrutin, ctx.zone, ctx.regroupement, 10)
    t = d.pct_bureaux(ctx.scrutin, ctx.zone, ctx.regroupement, top)
    if len(t) < 5 or len(top) < 2:
        return vide(fig, "Pas assez de bureaux ou de candidats.")
    m = t[top].corr()
    m.index = [court(q, 18) for q in top]
    m.columns = [court(q, 12) for q in top]
    ax = fig.add_subplot()
    chaleur(fig, ax, m, "RdBu_r", ".2f", -1, 1, carre=True)
    ax.tick_params(labelsize=T(7))
    titre(ax, "Qui monte et baisse avec qui ?", f"{d.libelle(ctx.scrutin)} · {zone_txt(ctx)} · corrélation des % par bureau")
    fig.tight_layout()
    vals = pd.DataFrame(m.values).where(~np.eye(len(top), dtype=bool)).stack()
    return {"legende": [("monte ensemble", "#B2182B"), ("l'un monte, l'autre baisse", "#2166AC")],
            "kpi": [(fmt(vals.max(), 2, ""), "plus forte"), (fmt(vals.min(), 2, ""), "plus opposée"), (str(len(t)), "bureaux")],
            "lecture": "Rouge : montent ensemble d'un bureau à l'autre. Bleu : quand l'un monte, l'autre baisse."}


# =============================================================================================
# Onglet Dans le temps
# =============================================================================================

def evolution(fig, ctx):
    ind = ctx.options.get("indicateur", "Abstention")
    s = d.serie_taux(ctx.zone, ind).dropna(subset=["valeur"])
    if s.empty:
        return vide(fig, "Aucune donnée.")
    s["date"] = pd.to_datetime(s["date"])
    ax = fig.add_subplot()
    if ctx.forme == "barres_v":
        ax.bar(s["date"], s["valeur"], width=120, color=[TYPES_ELECTION.get(t, C["gris"]) for t in s["type"]])
    else:
        ligne_et_points(ax, s)
        if ctx.zone.niveau != "france":
            fr = d.serie_taux(d.FRANCE, ind)
            ax.plot(pd.to_datetime(fr["date"]), fr["valeur"], color=C["texte"], ls=":", lw=1)
        ax.set_xlabel("")
    axe_dates(ax)
    ax.set_ylabel(f"{ind} (%)")
    titre(ax, f"{ind} élection après élection – {zone_txt(ctx)}", "chaque point = un scrutin ; pointillés = France")
    fig.tight_layout()
    types_ = [t for t in TYPES_ELECTION if t in set(s["type"])]
    der = s.iloc[-1]
    return {"legende": [(t, TYPES_ELECTION[t]) for t in types_],
            "kpi": [(fmt(der["valeur"]), "dernier scrutin"), (fmt(s["valeur"].max()), "record"), (str(len(s)), "scrutins")],
            "lecture": "Chaque point = un scrutin, sa couleur = le type d'élection. Les pointillés = la France entière."}


def type_ou_annee(fig, ctx):
    ind = ctx.options.get("indicateur", "Abstention")
    s = d.serie_taux(ctx.zone, ind, tour=1).dropna(subset=["valeur"])
    t = s.pivot_table(index="type", columns="annee", values="valeur")
    t = t.reindex([x for x in TYPES_ELECTION if x in t.index])
    if t.empty:
        return vide(fig, "Aucune donnée.")
    ax = fig.add_subplot()
    chaleur(fig, ax, t, "Reds" if ind == "Abstention" else "Blues", ".0f", label=f"{ind} (%)")
    ax.set_xlabel(""); ax.set_ylabel("")
    ax.tick_params(axis="x", labelsize=T(7), rotation=60)
    titre(ax, "Type d'élection ou année ?", f"{ind}, 1er tour · {zone_txt(ctx)}")
    fig.tight_layout()
    moy = t.mean(axis=1)
    return {"legende": [("plus foncé = plus élevé", "#CB181D")],
            "kpi": [(court(moy.idxmax(), 14), "type le plus haut"), (court(moy.idxmin(), 14), "le plus bas"), (fmt(moy.max() - moy.min(), 0, " pts"), "écart")],
            "lecture": "Lis les LIGNES pour l'effet du type d'élection, les COLONNES pour l'effet de l'époque."}


def ecarts(fig, ctx):
    ind = ctx.options.get("indicateur", "Abstention")
    s = d.taux_par_scrutin_et_bureau(ctx.zone, ind).dropna(subset=["valeur"])
    if s.empty:
        return vide(fig, "Aucune donnée.")
    ordre = s.drop_duplicates("scrutin").sort_values("date")
    groupes = [s.loc[s["scrutin"] == x, "valeur"].values for x in ordre["scrutin"]]
    ax = fig.add_subplot()
    palette = {x: TYPES_ELECTION.get(t, C["gris"]) for x, t in zip(ordre["scrutin"], ordre["type"])}
    if sb():
        sns.boxplot(data=s, x="scrutin", y="valeur", order=ordre["scrutin"], hue="scrutin", palette=palette, legend=False,
                    showfliers=False, linewidth=0.8, ax=ax)
    else:
        bp = ax.boxplot(groupes, positions=range(len(groupes)), patch_artist=True, showfliers=False, widths=0.6)
        for patch, x_ in zip(bp["boxes"], ordre["scrutin"]):
            patch.set_facecolor(palette[x_]); patch.set_edgecolor(C["texte2"])
    ax.set_xticks(range(len(ordre)), [x[:4] + " " + x[5:9] for x in ordre["scrutin"]], rotation=70, fontsize=T(6))
    ax.set_xlabel(""); ax.set_ylabel(f"{ind} (%)")
    titre(ax, f"{ind} : écarts entre bureaux, 1er tour", zone_txt(ctx))
    fig.tight_layout()
    largeur = [np.subtract(*np.percentile(g, [75, 25])) for g in groupes]
    return {"legende": [(t, TYPES_ELECTION[t]) for t in TYPES_ELECTION if t in set(ordre["type"])],
            "kpi": [(fmt(max(largeur), 1, " pts"), "boîte la plus large"), (fmt(min(largeur), 1, " pts"), "la plus étroite"), (str(len(ordre)), "scrutins")],
            "lecture": "Chaque boîte = la moitié des bureaux d'un scrutin ; le trait = la médiane. Grande boîte = bureaux très différents."}


def suivre(fig, ctx):
    texte = (ctx.options.get("texte") or "LE PEN").strip()
    s = d.suivre_nom(texte, ctx.zone).dropna(subset=["valeur"])
    if s.empty:
        return vide(fig, f"Aucun « {texte} » trouvé.")
    s["date"] = pd.to_datetime(s["date"])
    ax = fig.add_subplot()
    ligne_et_points(ax, s)
    for _, l in s[s["tour"] == 1].iterrows():
        ax.annotate(court(str(l["qui"]).split(" / ")[0], 20), (l["date"], l["valeur"]), fontsize=T(6), rotation=30,
                    xytext=(3, 4), textcoords="offset points", color=C["gris"])
    axe_dates(ax)
    ax.set_ylabel("% des exprimés")
    titre(ax, f"« {texte} » à travers les scrutins – {zone_txt(ctx)}")
    fig.tight_layout()
    return {"legende": [(t, TYPES_ELECTION[t]) for t in TYPES_ELECTION if t in set(s["type"])],
            "kpi": [(fmt(s["valeur"].max()), "meilleur score"), (str(s.loc[s["valeur"].idxmax(), "scrutin"])[:9], "quand"), (str(len(s)), "scrutins")],
            "lecture": "Mot entier : « LE PEN » ne compte pas « LE PENNEC ». Aux législatives, un candidat n'est que dans UNE circonscription."}


# =============================================================================================
# Le Top (classement)
# =============================================================================================

def top(fig, ctx):
    o = ctx.top
    niveau, mesure = o["niveau"], o["mesure"]
    v = d.par_niveau(ctx.scrutin, ctx.zone, niveau, mesure, ctx.regroupement, o.get("qui")).dropna(subset=["valeur"])
    if v.empty:
        return vide(fig, "Rien à classer pour ces réglages.")
    v = v.sort_values("valeur", ascending=o["ordre"] == "Les plus bas").head(int(o["n"]))
    nom = mesure if mesure != "Score" else court(o.get("qui"), 30)
    coul = [C["action"] if o["ordre"] == "Les plus hauts" else C["succes"]] * len(v)
    dessiner_liste(fig, v["libelle"], v["valeur"], coul, ctx.forme, f"Top {len(v)} {d.NOMS_NIVEAUX[niveau].lower()} – {nom}",
                   f"{d.libelle(ctx.scrutin)} · {zone_txt(ctx)} · {o['ordre'].lower()}")
    return {"legende": [(o["ordre"], coul[0])],
            "kpi": [(fmt(v["valeur"].iloc[0]), court(v["libelle"].iloc[0], 18)), (fmt(v["valeur"].iloc[-1]), f"{len(v)}e"), (str(len(v)), "classés")],
            "lecture": "Zones de moins de 200 inscrits ignorées (50 pour les bureaux)."}


# =============================================================================================
# Onglet Carte : dessinée DANS l'appli (contours 2022), clic = fiche de la zone
# =============================================================================================

_POLYS = {}


def polygones(niveau, deps):
    cle = (niveau, tuple(deps) if deps else None)
    if cle not in _POLYS:
        c = d.contours(niveau, deps)
        polys, codes, noms = [], [], []
        for code, nom, typ, coords in c.itertuples(index=False):
            g = json.loads(coords)
            for poly in (g if typ == "MultiPolygon" else [g]):
                if poly and len(poly[0]) > 2:
                    polys.append(np.asarray(poly[0])); codes.append(code); noms.append(nom)
        _POLYS[cle] = (polys, codes, noms)
    return _POLYS[cle]


FONDS = ["Automatique", "Plan des rues (OpenStreetMap)", "Aucun"]    # automatique : le plan dès qu'on est sous la région
ECHELLES = {"Automatique (selon la zone)": None, "Régions": "region", "Départements": "departement", "Communes": "commune", "Bureaux de vote": "bureau"}


# échelle « automatique » : un cran plus fin que la zone choisie (la France → la mosaïque des communes, une commune → ses bureaux)
ECHELLE_AUTO = {"france": "Communes", "region": "Bureaux de vote", "departement": "Communes", "arrondissement": "Communes",
                "epci": "Communes", "circo": "Communes", "canton": "Communes", "commune": "Bureaux de vote",
                "arrmun": "Bureaux de vote", "bureau": "Bureaux de vote"}
PETITES_ZONES = ("arrondissement", "epci", "circo", "canton", "commune", "arrmun", "bureau")


def carte(fig, ctx):
    echelle = ctx.options.get("echelle", "Automatique (selon la zone)")
    if ECHELLES.get(echelle) is None:
        echelle = ECHELLE_AUTO.get(ctx.zone.niveau, "Départements")
    niveau = ECHELLES[echelle]
    deps = d.departements_de(ctx.zone)
    if niveau == "bureau" and (deps is None or len(deps) > 13):
        return vide(fig, "Les bureaux de vote s'affichent dès qu'une région (ou une zone plus petite) est choisie dans le volet Zone.\n"
                         "France entière : prends l'échelle « Communes » pour la mosaïque.")
    if niveau in ("region", "departement") and deps is None:
        polys, codes, noms = polygones(niveau, None)
    elif niveau in ("region", "departement"):
        polys, codes, noms = polygones(niveau, None)
        garder = set(deps) if niveau == "departement" else None
        if garder:
            sel = [i for i, c in enumerate(codes) if c in garder]
            polys, codes, noms = [polys[i] for i in sel], [codes[i] for i in sel], [noms[i] for i in sel]
    else:
        polys, codes, noms = polygones(niveau, deps)
    if not polys:
        return vide(fig, "Pas de contours pour cette zone et cette échelle.")
    participation = ctx.options.get("mode_carte") == "Participation"
    # on colore tout le territoire affiché (le département d'une commune choisie, par ex.) ; la zone choisie sera entourée
    if deps is None or niveau == "region":
        etendue = d.FRANCE
    elif ctx.zone.niveau in ("region", "departement"):
        etendue = ctx.zone
    elif niveau == "bureau" and ctx.zone.niveau in PETITES_ZONES:
        # les bureaux d'une petite zone : on zoome sur elle (un bureau choisi → tous ceux de sa commune)
        etendue = d.Zone("commune", ctx.zone.code.split("_")[0], "") if ctx.zone.niveau == "bureau" else ctx.zone
    elif len(deps) == 1:
        etendue = d.Zone("departement", deps[0], "")
    else:
        etendue = ctx.zone
    ax = fig.add_subplot()
    ax.set_aspect(1.45)
    ax.axis("off")
    if participation:
        ind = ctx.options.get("indicateur", "Abstention")
        v = d.par_niveau(ctx.scrutin, etendue, niveau, ind, min_inscrits=0)
        val = dict(zip(v["code"], v["valeur"]))
        x = np.array([val.get(c, np.nan) for c in codes], dtype=float)
        cmap_part = "Reds" if ind == "Abstention" else "Blues"
        coll = PolyCollection(polys, array=np.ma.masked_invalid(x), cmap=cmap_part,
                              edgecolors="white", linewidths=0 if len(polys) > 5000 else 0.15 if niveau in ("commune", "bureau") else 0.5, picker=True)
        coll.cmap.set_bad(C["surface"])
        ax.add_collection(coll)
        fig.colorbar(coll, ax=ax, shrink=0.7, label=f"{ind} (%)")
        legende = [(f"{ind} : plus foncé = plus élevé", "#CB181D")]
        kpi = [(fmt(np.nanmax(x)), "le plus haut"), (fmt(np.nanmin(x)), "le plus bas"), (f"{len(set(codes)):,}".replace(",", " "), "zones")]
    else:
        # élection locale sur plusieurs communes : chaque commune a ses propres listes, seules les nuances se comparent
        regroupement = ctx.regroupement
        locale_large = (d.type_de(ctx.scrutin) not in d.TYPES_NATIONAUX and regroupement == "Candidat / liste"
                        and ctx.zone.niveau not in ("commune", "arrmun", "bureau"))
        if locale_large:
            regroupement = "Nuance"
        g = d.gagnants(ctx.scrutin, etendue, niveau, regroupement)
        gag = dict(zip(g["code"], g["gagnant"]))
        ordre = g["gagnant"].value_counts().index.tolist()
        palette = dict(zip(ordre, couleurs_pour(ctx.scrutin, regroupement, ordre)))
        couleurs = [palette.get(gag[c], C["doux"]) if c in gag else C["surface"] for c in codes]
        coll = PolyCollection(polys, facecolors=couleurs, edgecolors="white", linewidths=0 if len(polys) > 5000 else 0.15 if niveau in ("commune", "bureau") else 0.5, picker=True)
        ax.add_collection(coll)
        compte = g["gagnant"].value_counts()
        legende = [(court(q, 22), palette.get(q, C["doux"])) for q in compte.index[:5]]
        kpi = [(court(compte.index[0], 14) if len(compte) else "—", "1er le plus souvent"),
               (fmt(100 * compte.iloc[0] / compte.sum(), 0) if len(compte) else "—", "des zones"), (f"{len(set(codes)):,}".replace(",", " "), "zones")]
    if niveau == "bureau" and ctx.zone.niveau in PETITES_ZONES:
        dedans = set(v["code"] if participation else g["code"])
        sel = [i for i, c in enumerate(codes) if c in dedans]
        if not sel:
            return vide(fig, "Pas de contours de bureaux pour cette zone (bureaux renumérotés depuis 2022 ?).")
        coll.remove()
        polys, codes, noms = [polys[i] for i in sel], [codes[i] for i in sel], [noms[i] for i in sel]
        coll = PolyCollection(polys, facecolors=[coll.get_facecolors()[i] for i in sel] if not participation else None,
                              edgecolors="white", linewidths=0.6, picker=True)
        if participation:
            coll.set_array(np.ma.masked_invalid(x[sel])); coll.set_cmap(cmap_part); coll.set_clim(np.nanmin(x), np.nanmax(x))
        ax.add_collection(coll)
        kpi[2] = (str(len(set(codes))), "bureaux")
    if ctx.zone.niveau == niveau:   # (bureaux d'une commune : la vue entière est déjà la zone, rien à entourer)
        choisis = [p_ for p_, c in zip(polys, codes) if c == ctx.zone.code or (niveau == "bureau" and c.startswith(str(ctx.zone.code) + "_"))]
        if choisis:
            ax.add_collection(PolyCollection(choisis, facecolors="none", edgecolors=C["texte"], linewidths=1.6, linestyles="--", zorder=5))
    toutes = np.vstack(polys)
    ax.set_xlim(toutes[:, 0].min(), toutes[:, 0].max())
    ax.set_ylim(toutes[:, 1].min(), toutes[:, 1].max())
    # le plan des rues en dessous (OpenStreetMap), pour se repérer
    fond = ctx.options.get("fond", "Automatique")
    sans_plan = None
    if fond == FONDS[1] or (fond == FONDS[0] and ctx.zone.niveau not in ("france", "region")):
        p = fond_carte.plan(toutes[:, 0].min(), toutes[:, 0].max(), toutes[:, 1].min(), toutes[:, 1].max())
        if p is None:
            sans_plan = "Plan des rues indisponible (pas d'internet ?)."
        else:
            ax.imshow(p[0], extent=p[1], zorder=0, aspect="auto", interpolation="bilinear")
            coll.set_alpha(0.72)
            ax.set_xlim(toutes[:, 0].min(), toutes[:, 0].max())
            ax.set_ylim(toutes[:, 1].min(), toutes[:, 1].max())
            ax.set_aspect(1.45)
            ax.text(1, 0, fond_carte.MENTION, transform=ax.transAxes, ha="right", va="bottom", fontsize=T(7), color=C["gris"],
                    bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", pad=1))
    point = ctx.options.get("adresse")       # l'adresse cherchée dans le volet Zone : un point rouge
    if point and toutes[:, 0].min() <= point[0] <= toutes[:, 0].max() and toutes[:, 1].min() <= point[1] <= toutes[:, 1].max():
        ax.plot(point[0], point[1], "o", ms=11, color=C["action"], mec="white", mew=2.2, zorder=8)
        ax.annotate(court(point[2], 40), (point[0], point[1]), xytext=(8, 8), textcoords="offset points", fontsize=T(8), zorder=8,
                    color=C["texte"], bbox=dict(facecolor="white", edgecolor=C["action"], boxstyle="round,pad=0.3"))
    coll.codes_zones, coll.noms_zones, coll.niveau_zones = codes, noms, niveau
    zones = dict(zip(codes, noms))
    if participation:
        donnees(pd.DataFrame({"zone": list(zones.values()), "code": list(zones), f"{ind} (%)": [val.get(c, np.nan) for c in zones]}))
    else:
        donnees(pd.DataFrame({"zone": list(zones.values()), "code": list(zones), "en tête": [gag.get(c, "") for c in zones]}))
    titre(ax, f"{d.libelle(ctx.scrutin)} – {echelle.lower()}", f"{zone_txt(ctx)} · clique sur une zone pour voir son détail · contours 2022")
    fig.tight_layout()
    lecture = "Clique sur une zone : son détail s'affiche à droite. Le survol ne fait rien. Zoom : la loupe de la barre d'outils."
    if sans_plan:
        lecture = sans_plan + " " + lecture
    if not participation and locale_large:
        lecture = ("Élection locale : couleurs par NUANCE (chaque commune a ses propres listes). Gris = pas de nuance "
                   "(petites communes)" + (" ou pas de 2nd tour — prends « Les 2 tours »" if ctx.scrutin.endswith("t2") else "") + ". Clique sur une zone pour ses listes.")
    if d.type_de(ctx.scrutin) == "Municipales" and niveau in ("region", "departement"):
        lecture = ("Municipales : chaque commune a ses propres listes, le « 1er » d'un département ne veut pas dire grand-chose. "
                   "Prends l'échelle « Communes » ou « Bureaux de vote ».")
    if len(set(codes)) == 1:
        lecture = "Une seule zone à cette échelle : prends l'échelle « Communes » ou « Bureaux de vote » (réglages de la vue, à droite)."
    return {"legende": legende, "kpi": kpi, "lecture": lecture}


# =============================================================================================
# Nuages de points et économie
# =============================================================================================

def _ax_label(axe, point):
    m = axe["mesure"]
    if m == "Score":
        return f"% {court(axe.get('qui'), 26)}" + ("" if point in ("Élection", "Mois") else f" ({axe.get('scrutin', '')[:9]})")
    if m in d.MESURES_ECO or m in d.MESURES_LOCALES or point in ("Élection", "Mois"):
        lab = m
    else:
        lab = f"{m} ({axe.get('scrutin', '')[:9]})"
    if axe.get("plus") and axe["plus"] != "(rien)":
        lab += f" + {axe['plus']}"
    return lab


def _valeurs(axe, point, zone, type_):
    v = d.valeurs_axe(axe, point, zone, type_)
    if axe.get("plus") and axe["plus"] != "(rien)":
        w = d.valeurs_axe({**axe, "mesure": axe["plus"]}, point, zone, type_)
        com = v.index.intersection(w.index)
        v = d.standardise(v.loc[com]) + d.standardise(w.loc[com])
    return v


def nuage(fig, ctx):
    n = ctx.nuage
    point, zone = n["point"], ctx.zone
    zx = d.FRANCE if n.get("zone_france") else zone
    x = _valeurs(n["x"], point, zx, n.get("type"))
    y = _valeurs(n["y"], point, zone, n.get("type"))
    com = x.index.intersection(y.index)
    if len(com) < 3:
        return vide(fig, "Pas assez de points communs aux deux axes.\nVérifie les réglages (bouton « Réglages du nuage ») : élection, mesure, candidat.")
    x, y = x.loc[com].astype(float), y.loc[com].astype(float)
    # pour l'export (texte / CSV) : chaque point avec son nom, pas seulement ses deux valeurs
    tab = pd.DataFrame({point: list(com), _ax_label(n["x"], point): x.round(3).values, _ax_label(n["y"], point): y.round(3).values})
    if point == "Commune":
        noms_c = d.noms_zones("commune")
        tab.insert(1, "nom", [noms_c.get(str(c).split("_")[0], "") for c in com])
    elif point == "Bureau de vote":
        noms_c = d.noms_zones("commune")
        tab.insert(1, "commune", [noms_c.get(str(c).split("_")[0], "") for c in com])
    elif point == "Élection":
        tab.insert(1, "scrutin", [d.libelle(k) for k in com])
    donnees(tab)
    ax = fig.add_subplot()
    legende = []
    if point == "Élection":
        types_ = d.scrutins().set_index("scrutin").loc[com, "type"]
        points(ax, x.values, y.values, teintes=types_.values, palette=TYPES_ELECTION, taille=70)
        for k in com:
            ax.annotate(k[:9].replace("_", " "), (x[k], y[k]), fontsize=T(6), color=C["gris"], xytext=(3, 3), textcoords="offset points")
        legende = [(t, TYPES_ELECTION[t]) for t in TYPES_ELECTION if t in set(types_)]
    elif point == "Mois":
        dates = pd.to_datetime(com)
        sc = ax.scatter(x, y, c=dates.year, cmap="viridis", s=14, alpha=0.8)
        fig.colorbar(sc, ax=ax, label="année", shrink=0.8)
        legende = [("ancien", "#440154"), ("récent", "#FDE725")]
    else:
        if len(com) > 4000 and ctx.forme != "nuage":
            hb = ax.hexbin(x, y, gridsize=60, cmap="Blues", mincnt=1, bins="log")
            fig.colorbar(hb, ax=ax, label="points (échelle log)", shrink=0.8)
        else:
            points(ax, x.values, y.values, couleur=C["primaire"], taille=10 if len(com) > 500 else 24)
        legende = [(f"un point = {point.lower()}", C["primaire"])]
    if n.get("diagonale"):
        lo, hi = min(x.min(), y.min()), max(x.max(), y.max())
        ax.plot([lo, hi], [lo, hi], color=C["gris"], ls="--", lw=1)
    tendance(ax, x.values, y.values, bande=len(com) <= 2000)
    r = np.corrcoef(x, y)[0, 1]
    ax.set_xlabel(_ax_label(n["x"], point) + (" — en France" if n.get("zone_france") else ""))
    ax.set_ylabel(_ax_label(n["y"], point) + (f" — {zone.libelle}" if n.get("zone_france") else ""))
    titre(ax, n["question"], f"un point = {point.lower()} · {zone.libelle} · trait rouge = tendance")
    fig.tight_layout()
    legende.append(("tendance", C["action"]))
    lecture = n.get("lecture", "")
    if point not in ("Élection", "Mois") and any(ax_["mesure"] in d.MESURES_ECO for ax_ in (n["x"], n["y"])):
        lecture = "⚠ Indicateur national : la même valeur partout le même jour. Prends « Un point = élection » ou « mois »."
    return {"legende": legende, "kpi": [(fmt(r, 2, ""), "corrélation"), (fmt(r * r * 100, 0), "part expliquée (r²)"),
                                        (f"{len(com):,}".replace(",", " "), "points")], "lecture": lecture}


def suivi(fig, ctx):
    n = ctx.nuage
    m, plus = n["y"]["mesure"], n["y"].get("plus", "(rien)")
    col = d.MESURES_ECO.get(m)
    if not col:
        return vide(fig, "Choisis un indicateur économique en Y (bouton « Réglages du nuage »).")
    e = d.economie_mois()
    s = e.set_index("mois")[col].dropna()
    ax = fig.add_subplot()
    ax.plot(s.index, s.values, color=C["texte"], lw=1.6, label=m, zorder=2)    # pas le bleu : c'est celui des présidentielles
    v = d.veille()
    v = v[v["date"] >= s.index.min()]
    couleurs = [TYPES_ELECTION.get(t, C["gris"]) for t in v["type"]]
    # un trait vertical par scrutin, et sa pastille en haut du graphique : un clic = le résultat national (fiche de droite)
    for date, c in zip(v["date"], couleurs):
        ax.axvline(date, color=c, lw=0.9, alpha=0.4, zorder=1)
    en_haut = mtransforms.blended_transform_factory(ax.transData, ax.transAxes)
    rang = {t: i for i, t in enumerate(TYPES_ELECTION)}     # une ligne de pastilles par type : rien ne se cache
    pastilles = ax.scatter(v["date"], [0.97 - 0.03 * rang.get(t, 0) for t in v["type"]], transform=en_haut, c=couleurs, s=70, zorder=4,
                           edgecolors="white", linewidths=1, picker=True)
    pastilles.scrutins_points = v["scrutin"].tolist()
    w = v[v[col].notna()]      # la valeur de l'indicateur la veille du vote, sur la courbe
    ax.scatter(w["date"], w[col], c=[TYPES_ELECTION.get(t, C["gris"]) for t in w["type"]], s=30, zorder=3, edgecolors="white")
    if plus != "(rien)" and d.MESURES_ECO.get(plus):
        ax2 = ax.twinx()
        s2 = e.set_index("mois")[d.MESURES_ECO[plus]].dropna()
        ax2.plot(s2.index, s2.values, color=C["gris"], ls="--", lw=1, label=plus)
        ax2.set_ylabel(plus, color=C["gris"])
        ax2.spines["right"].set_visible(True)
        ax2.grid(False)
    axe_dates(ax)
    ax.set_ylabel(m)
    titre(ax, f"{m} depuis {s.index.min().year}" + (f" — comparé à : {plus.lower()}" if plus != "(rien)" else ""),
          "ligne = chaque mois · un trait = un scrutin (clique sur sa pastille)" + (" · pointillés = " + plus.lower() if plus != "(rien)" else ""))
    fig.tight_layout()
    types = [t for t in TYPES_ELECTION if t in set(v["type"])]
    return {"legende": [(m, C["texte"])] + ([(plus, C["gris"])] if plus != "(rien)" else []) + [(t, TYPES_ELECTION[t]) for t in types],
            "kpi": [(fmt(s.iloc[-1], 2, ""), "dernière valeur"), (fmt(s.max(), 2, ""), "maximum"), (fmt(s.min(), 2, ""), "minimum")],
            "lecture": "Ligne = l'indicateur mois par mois. Un trait = un scrutin : clique sur sa pastille (en haut) pour son résultat national. "
                       "Comparer à un autre indicateur : « Réglages du nuage », Y → plus."}


# Les questions des onglets Nuages et Économie (des préréglages, modifiables ensuite dans « Réglages du nuage »).
# Une ligne = (nom court de la pastille, question, axe X, axe Y, un point =, diagonale ?, phrase de lecture)
# AXE(mesure, scrutin, qui, regroupement, plus) : voir les mesures possibles dans donnees.py
def AXE(mesure, scrutin=None, qui=None, regroupement="Candidat / liste", plus="(rien)"):
    return {"mesure": mesure, "scrutin": scrutin, "qui": qui, "regroupement": regroupement, "plus": plus}
