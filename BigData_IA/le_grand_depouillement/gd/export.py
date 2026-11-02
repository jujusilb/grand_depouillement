"""Les données de la vue en TEXTE et en CSV : pour les lecteurs d'écran (NVDA lit très bien le Bloc-notes et les tableurs),
et pour réutiliser les chiffres ailleurs.

Une vue peut donner ses données elle-même (graphiques.donnees(tableau)) ; sinon on les relit dans le graphique dessiné :
barres, courbes, nuages de points, cartes de chaleur et tableaux.
Les fichiers vont dans « Documents\\Le Grand Dépouillement\\exports » et s'ouvrent tout seuls.
"""
import os
import re
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.collections import PathCollection, QuadMesh
from matplotlib.container import BarContainer

DOSSIER = Path.home() / "Documents" / "Le Grand Dépouillement" / "exports"
MAX_LIGNES_TEXTE = 2000          # au-delà, le texte renvoie au CSV (une liste de 35 000 communes ne se lit pas à l'oreille)


def _etiquettes(axe):
    return {round(t, 6): l.get_text() for t, l in zip(axe.get_ticklocs(), axe.get_ticklabels())}


def _proche(etiq, v):
    if not etiq:
        return ""
    k = min(etiq, key=lambda t: abs(t - v))
    return etiq[k] if abs(k - v) < 0.5 else ""


def _date_ou_nombre(ax, axe, v):
    """Une position sur un axe de dates → « 24/04/2022 » ; sinon le nombre."""
    if isinstance(axe.get_major_formatter(), (mdates.DateFormatter, mdates.AutoDateFormatter, mdates.ConciseDateFormatter)):
        return mdates.num2date(v).strftime("%d/%m/%Y")
    return round(v, 3)


def depuis_figure(fig):
    """Ce que montre le graphique, relu dans ses objets matplotlib : une liste de (titre, tableau)."""
    tableaux = []
    for ax in fig.axes:
        titre = ax.get_title(loc="left") or ax.get_title() or ax.get_ylabel() or ""
        # 1. les tableaux dessinés (ax.table)
        for tab in ax.tables:
            cellules = tab.get_celld()
            if not cellules:
                continue
            nl = max(r for r, _ in cellules) + 1
            nc = max(c for _, c in cellules) + 1
            lignes = [[cellules[(r, c)].get_text().get_text() if (r, c) in cellules else "" for c in range(nc)] for r in range(nl)]
            tableaux.append((titre, pd.DataFrame(lignes[1:], columns=lignes[0])))
        # 2. les barres (verticales ou horizontales)
        lignes = []
        ex, ey = _etiquettes(ax.xaxis), _etiquettes(ax.yaxis)
        for cont in ax.containers:
            if not isinstance(cont, BarContainer):
                continue
            serie = cont.get_label() if cont.get_label() and not cont.get_label().startswith("_") else ""
            for p in cont.patches:
                x, y, w, h = p.get_x(), p.get_y(), p.get_width(), p.get_height()
                if cont.orientation == "horizontal":
                    lignes.append((serie, _proche(ey, y + h / 2), round(w, 3)))
                else:
                    lignes.append((serie, _proche(ex, x + w / 2) or _date_ou_nombre(ax, ax.xaxis, x + w / 2), round(h, 3)))
        if lignes:
            t = pd.DataFrame(lignes, columns=["série", "catégorie", "valeur"])
            if t["série"].eq("").all():
                t = t.drop(columns="série")
            tableaux.append((titre, t))
        # 3. les courbes
        for ligne in ax.get_lines():
            nom = ligne.get_label()
            x, y = np.asarray(ligne.get_xdata()), np.asarray(ligne.get_ydata())
            if len(x) < 2 or nom.startswith("_child") and len(x) < 3:
                continue
            xs = [_date_ou_nombre(ax, ax.xaxis, float(v)) if isinstance(v, (int, float, np.floating, np.integer)) else str(v) for v in x]
            tableaux.append((f"{titre} — courbe {'' if nom.startswith('_') else nom}".strip(" —"),
                             pd.DataFrame({"x": xs, "y": np.round(y.astype(float), 3)})))
        # 4. les nuages de points (sans les cartes : leurs zones sont données à part)
        for coll in ax.collections:
            if isinstance(coll, PathCollection) and len(coll.get_offsets()) and not hasattr(coll, "votants") and not hasattr(coll, "parlementaires"):
                o = np.asarray(coll.get_offsets())
                if len(o) <= 50000:
                    tableaux.append((f"{titre} — points", pd.DataFrame({ax.get_xlabel() or "x": np.round(o[:, 0], 3),
                                                                         ax.get_ylabel() or "y": np.round(o[:, 1], 3)})))
            elif isinstance(coll, QuadMesh):                      # carte de chaleur (seaborn heatmap)
                a = np.asarray(coll.get_array()).reshape(len(ey), -1) if ey and np.size(coll.get_array()) % len(ey) == 0 else None
                if a is not None and a.shape[1] == len(ex):
                    tableaux.append((titre, pd.DataFrame(np.round(a, 2), index=list(ey.values()), columns=list(ex.values())).reset_index()))
    return tableaux


def _nom_fichier(nom):
    return re.sub(r"[^\w\-]+", "_", nom).strip("_")[:60] + datetime.now().strftime("_%Y-%m-%d_%Hh%M")


def texte_de_la_vue(entete, info, tableaux):
    """Le texte complet de la vue : ce que montre le graphique, dit avec des mots et des chiffres."""
    l = [entete["titre"], "=" * len(entete["titre"]), ""]
    for cle in ("scrutin", "zone", "explication"):
        if entete.get(cle):
            l.append(f"{cle.capitalize()} : {entete[cle]}")
    if info.get("lecture"):
        l += ["", "Lecture : " + info["lecture"]]
    if info.get("kpi"):
        l += ["", "Chiffres clés :"] + [f"  - {lib} : {val}" for val, lib in info["kpi"]]
    if info.get("legende"):
        l += ["", "Légende :"] + [f"  - {t}" for t, _ in info["legende"]]
    for titre, t in tableaux:
        l += ["", f"Données — {titre}" if titre else "Données", f"({len(t)} lignes ; colonnes : {', '.join(map(str, t.columns))})"]
        if len(t) > MAX_LIGNES_TEXTE:
            l.append(f"Trop de lignes pour un texte : les {MAX_LIGNES_TEXTE} premières ; tout est dans le fichier CSV.")
        for _, r in t.head(MAX_LIGNES_TEXTE).iterrows():
            l.append("  " + " ; ".join(f"{c} : {_fmt(v)}" for c, v in r.items()))
    if entete.get("precaution"):
        l += ["", "Précaution : " + entete["precaution"]]
    return "\n".join(l) + "\n"


def _fmt(v):
    if isinstance(v, float):
        return "" if v != v else f"{v:,.2f}".replace(",", " ").replace(".", ",").replace(",00", "")
    return str(v)


def enregistrer(entete, info, tableaux, sorte="texte"):
    """Écrit le fichier (texte .txt, ou .csv pour le tableur) et l'ouvre ; rend son chemin."""
    DOSSIER.mkdir(parents=True, exist_ok=True)
    base = DOSSIER / _nom_fichier(entete["titre"])
    if sorte == "texte":
        chemin = base.with_suffix(".txt")
        chemin.write_text(texte_de_la_vue(entete, info, tableaux), encoding="utf-8-sig")
    else:
        chemin = base.with_suffix(".csv")
        morceaux = []
        for titre, t in tableaux or [("", pd.DataFrame({"information": ["Pas de données chiffrées pour cette vue."]}))]:
            morceaux.append(t.assign(**{"tableau": titre}) if len(tableaux) > 1 else t)
        tout = pd.concat(morceaux, ignore_index=True) if morceaux else pd.DataFrame()
        tout.to_csv(chemin, sep=";", decimal=",", index=False, encoding="utf-8-sig")       # (le format du tableur français)
    if not os.environ.get("GD_TEST"):
        try:
            os.startfile(chemin)            # Bloc-notes pour le texte, le tableur pour le CSV
        except OSError:
            pass
    return chemin
