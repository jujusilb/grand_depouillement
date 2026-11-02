"""
graphiques_personnes.py — Les vues des personnes et du temps long (onglet Personnes, et quelques vues de Sièges et de
Dans le temps). Mêmes règles que graphiques.py : une fonction = une vue, qui reçoit la figure et le contexte, dessine, et
rend {"legende", "kpi", "lecture"} ; les données passent par donnees() pour l'export texte / CSV.
"""
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from gd import donnees as d
from gd import personnes as P
from gd import rne, theme
from gd.graphiques import (LIGNES_SANS_ASCENSEUR, T, _departement_de, conseil_en_place, court, donnees, fmt, hauteur_liste,
                           titre, vide)
from gd.theme import C, SERIES, TYPES_ELECTION

AUJOURD_HUI = pd.Timestamp.today().normalize()
COULEURS_SORTES = {"Mandat": C["primaire"], "Gouvernement": C["action"], "Préfet": C["succes"], "Grand corps": "#A558A0",
                   "École": C["orange"]}


def _pas_de_modele(fig):
    return vide(fig, "Les nominations ne sont pas dans la base : lance integrer_nominations.py puis integrer_formations.py.")


def _frise(fig, lignes, titre_, sous, couleur_de, etiquette_de, rangee_de=None):
    """Une frise : une barre par ligne, de son début à sa fin (aujourd'hui si elle est en cours).
    rangee_de : la rangée de chaque ligne (plusieurs lignes peuvent partager une rangée) ; par défaut une rangée chacune."""
    lignes = lignes.reset_index(drop=True)
    rangees = list(dict.fromkeys(rangee_de(r) for _, r in lignes.iterrows())) if rangee_de else list(range(len(lignes)))
    n = len(rangees)
    if n > LIGNES_SANS_ASCENSEUR:
        hauteur_liste(fig, n, 0.32)
    ax = fig.add_subplot()
    for i, r in lignes.iterrows():
        y = rangees.index(rangee_de(r)) if rangee_de else i
        debut = r["debut"]
        fin = r["fin"] if pd.notna(r["fin"]) else AUJOURD_HUI
        if pd.isna(debut):
            continue
        largeur = max((fin - debut).days, 120)            # (au moins quatre mois : un poste court reste visible)
        ax.barh(y, largeur, left=mdates.date2num(debut), height=0.62, color=couleur_de(r), edgecolor="white")
    etiquettes = [str(x) for x in rangees] if rangee_de else [etiquette_de(lignes.iloc[i]) for i in range(n)]
    ax.set_yticks(range(n), [court(e, 46) for e in etiquettes], fontsize=T(9))
    ax.invert_yaxis()
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(axis="y", visible=False)
    titre(ax, titre_, sous)
    for texte in ax.texts:          # (un long sous-titre ne doit pas faire rétrécir l'axe des dates à la mise en page)
        texte.set_in_layout(False)
    if n > LIGNES_SANS_ASCENSEUR:
        fig.set_layout_engine("tight")
    else:
        fig.tight_layout()
    return ax


# ------------------------------------------------------------------------------------------------------------------
# Sièges › Qui siège aujourd'hui
# ------------------------------------------------------------------------------------------------------------------
def qui_siege(fig, ctx):
    """Le conseil en place aujourd'hui (dernière version du Répertoire national des élus), quelle que soit l'élection
    choisie dans le menu : municipal, communautaire, départemental ou régional selon la zone."""
    return conseil_en_place(fig, ctx, version=rne.version_actuelle())


# ------------------------------------------------------------------------------------------------------------------
# Personnes › Fiche d'une personne
# ------------------------------------------------------------------------------------------------------------------
def fiche_personne(fig, ctx):
    if not P.disponible():
        return _pas_de_modele(fig)
    pid = ctx.options.get("personne")
    if not pid:
        return vide(fig, "Tape un nom dans le volet de droite (« Réglages de la vue »), puis choisis la personne :\n"
                         "ses mandats, ses postes au gouvernement, ses écoles et ses candidatures s'affichent ici.")
    f = P.fiche(int(pid))
    if f is None:
        return vide(fig, "Cette personne n'est plus dans la base.")
    r = _fiche_personne(fig, f)
    r["lecture"] += _photo_et_liens(fig, f)
    return r


def _photo_et_liens(fig, f):
    """La photo en haut à droite (avec son auteur et sa licence, obligatoires pour une photo libre) et les liens
    familiaux ; rend la phrase à ajouter à la lecture."""
    texte = ""
    if len(f["liens"]):
        donnees(f["liens"], "liens familiaux")
        texte += " Liens : " + " ; ".join(f"{r.relation} {r.nom}" + (f" ({r.note})" if isinstance(r.note, str) and r.note else "")
                                          for r in f["liens"].itertuples()) + "."
    ph = f["photo"]
    if ph is None:
        return texte
    from PIL import Image
    moteur = fig.get_layout_engine()
    if moteur is not None:               # (on fige la mise en page, puis on laisse une colonne à droite pour la photo)
        moteur.execute(fig)
        fig.set_layout_engine("none")
    for ax in fig.axes:
        x0, y0, l, h = ax.get_position().bounds
        if x0 + l > 0.80:
            ax.set_position([x0, y0, max(0.80 - x0, 0.2), h])
    hauteur = fig.get_figheight()
    cote = min(1.9 / hauteur, 0.30)      # (environ 1,9 pouce de haut, quelle que soit la hauteur de la figure)
    axe = fig.add_axes([0.82, 1 - cote - 0.02, 0.16, cote])
    axe.imshow(Image.open(ph["chemin"]))
    axe.axis("off")
    credit = f"Photo : {ph['auteur'] or ph['source']}" + (f"\n{ph['licence']}" if ph["licence"] else "") \
        + (f" · {ph['source']}" if ph["auteur"] else "")
    axe.text(0.5, -0.03, credit, transform=axe.transAxes, ha="center", va="top", fontsize=T(9), color=C["gris"], wrap=True)
    return texte + f" {credit.replace(chr(10), ', ')}."


def _fiche_personne(fig, f):
    t = f["parcours"]
    n_cand = len(f["candidatures"])
    if len(f["candidatures"]):
        donnees(f["candidatures"], "candidatures")
    if len(f.get("partis", [])):
        donnees(f["partis"], "partis")
    if t.empty:
        return vide(fig, f"{f['nom']} : aucun mandat, poste ni école connus ({n_cand} candidature(s) — voir l'export).")
    donnees(t[["sorte", "quoi", "lieu", "debut", "fin", "election"]].rename(columns={"election": "élection / gouvernement"}),
            "parcours")
    datees = t.dropna(subset=["debut"])
    naissance = f"née le {pd.Timestamp(f['naissance']):%d/%m/%Y}" if pd.notna(f["naissance"]) and f["sexe"] == "F" else \
        f"né le {pd.Timestamp(f['naissance']):%d/%m/%Y}" if pd.notna(f["naissance"]) else "date de naissance inconnue"
    if datees.empty:
        return vide(fig, f"{f['nom']} ({naissance}) : " + " ; ".join(t["quoi"]))
    _frise(fig, datees, f"Le parcours de {f['nom']}", f"{naissance} · une barre par mandat, poste ou école · jusqu'à aujourd'hui si en cours",
           lambda r: COULEURS_SORTES.get(r["sorte"], C["gris"]),
           lambda r: f"{r['quoi']}" + (f" — {r['lieu']}" if r["lieu"] else ""))
    sortes = [s for s in COULEURS_SORTES if s in set(t["sorte"])]
    sans_date = t[t["debut"].isna()]
    partis = f.get("partis")
    partis = (" Partis : " + ", ".join(dict.fromkeys(str(s) if s == s and s else str(n) for n, s in zip(partis["parti"], partis["sigle"])))
              + "." if partis is not None and len(partis) else "")
    lecture = (f"{f['nom']} : {len(t)} mandats, postes ou écoles, {n_cand} candidature(s).{partis} "
               + (f"Sans date : {', '.join(sans_date['quoi'])}. " if len(sans_date) else "")
               + "Sources : Répertoire national des élus, Assemblée, Sénat, Journal officiel, Archives nationales, Wikidata.")
    return {"legende": [(s, COULEURS_SORTES[s]) for s in sortes],
            "kpi": [(str(int((t["sorte"] == "Mandat").sum())), "mandats"),
                    (str(int(t["sorte"].isin(["Gouvernement", "Préfet", "Grand corps"]).sum())), "nominations"),
                    (str(n_cand), "candidatures")],
            "lecture": lecture}


# ------------------------------------------------------------------------------------------------------------------
# Personnes › Un gouvernement ; les présidents
# ------------------------------------------------------------------------------------------------------------------
def gouvernement(fig, ctx):
    if not P.disponible():
        return _pas_de_modele(fig)
    g_ = P.gouvernements()
    choix = ctx.options.get("gouvernement") or g_["choix"].iloc[0]
    ligne = g_[g_["choix"] == choix]
    ligne = ligne.iloc[0] if len(ligne) else g_.iloc[0]
    t = P.membres(int(ligne["id"]))
    if t.empty:
        return vide(fig, f"{ligne['libelle']} : aucun membre connu.")
    donnees(t[["fonction", "qui", "poste", "debut", "fin"]])
    couleurs = {f_: SERIES[i % len(SERIES)] for i, f_ in enumerate(dict.fromkeys(t["fonction"]))}
    ax = _frise(fig, t, ligne["libelle"], f"{ligne['regime']} · {len(t)} nominations · une barre par poste, du décret à la fin des fonctions",
                lambda r: couleurs[r["fonction"]], lambda r: f"{r['qui']} — {r['poste']}")
    debut, fin = pd.Timestamp(ligne["debut"]), pd.Timestamp(ligne["fin"]) if pd.notna(ligne["fin"]) else AUJOURD_HUI
    ax.set_xlim(mdates.date2num(debut - pd.Timedelta(days=15)), mdates.date2num(fin + pd.Timedelta(days=15)))
    jours = (fin - debut).days
    return {"legende": [(f"{f_} — {int((t['fonction'] == f_).sum())}", c) for f_, c in couleurs.items()],
            "kpi": [(str(t["personne_id"].nunique()), "personnes"), (f"{jours} j", "durée"),
                    (str(int((t["fonction_id"].isin([18, 25])).sum())), "ministres de plein exercice")],
            "lecture": "Sources : liste des ministres du Premier ministre (1944-2014), décrets du Journal officiel depuis 2014 ; "
                       "Wikidata seulement quand le JO manque (gouvernement Borne)."}


def presidents(fig, ctx):
    if not P.disponible():
        return _pas_de_modele(fig)
    t = P.presidents()
    donnees(t[["qui", "debut", "fin", "election", "motif_debut", "motif_fin"]])
    couleurs = {q: SERIES[i % len(SERIES)] for i, q in enumerate(dict.fromkeys(t["qui"]))}
    _frise(fig, t, "Les présidents de la République depuis 1947", "une barre par mandat (De Gaulle, Mitterrand, Chirac et Macron : deux)",
           lambda r: couleurs[r["qui"]], lambda r: r["qui"], rangee_de=lambda r: r["qui"])
    return {"legende": [], "kpi": [(str(len(couleurs)), "présidents"), (str(len(t)), "mandats"),
                                   (str(int(t["motif_debut"].str.contains("entrée", na=False).sum())), "intérims")],
            "lecture": "Élus au suffrage universel depuis 1965 : proclamations du Conseil constitutionnel. IVe République, "
                       "intérims (Alain Poher) et dates de fin : Wikidata."}


# ------------------------------------------------------------------------------------------------------------------
# Personnes › Les préfets d'un département
# ------------------------------------------------------------------------------------------------------------------
def prefets(fig, ctx):
    if not P.disponible():
        return _pas_de_modele(fig)
    dep = _departement_de(ctx.zone)
    if not dep:
        return vide(fig, "Choisis un département (ou une commune) dans le volet Zone : ses préfets s'affichent ici.")
    t = P.prefets(dep)
    if t.empty:
        return vide(fig, f"Aucun préfet connu pour ce département ({dep}).")
    donnees(t[["qui", "debut", "fin", "precis", "source"]].rename(columns={"precis": "précision des dates"}))
    depuis = int(ctx.options.get("prefets_depuis") or 1945)
    recents = t[pd.to_datetime(t["debut"]).dt.year >= depuis].copy()
    recents["debut"], recents["fin"] = pd.to_datetime(recents["debut"]), pd.to_datetime(recents["fin"])
    nom = d.nom_zone("departement", dep)
    _frise(fig, recents, f"Les préfets — {nom} (depuis {depuis})",
           "une barre par préfet ; vert foncé : date au jour près (Journal officiel, depuis 1990), vert clair : année seule (Archives nationales)",
           lambda r: C["succes"] if r["precis"] == "jour" else "#8CC4A0", lambda r: r["qui"])
    duree = (recents["fin"] - recents["debut"]).dt.days.dropna() / 365.25
    return {"legende": [("au jour près (Journal officiel)", C["succes"]), ("à l'année (Archives nationales)", "#8CC4A0")],
            "kpi": [(str(len(t)), "préfets depuis 1800"), (fmt(duree.mean(), 1, " ans") if len(duree) else "—", f"en poste en moyenne (depuis {depuis})"),
                    (court(t.iloc[-1]["qui"], 16), "dernier nommé")],
            "lecture": "Avant 1990 : les postes des Archives nationales (années seules) ; depuis 1990 : les décrets de nomination "
                       "du Journal officiel, un poste finissant à la nomination suivante."}


# ------------------------------------------------------------------------------------------------------------------
# Personnes › Écoles et pouvoir ; cumuls ; maires
# ------------------------------------------------------------------------------------------------------------------
def ecoles(fig, ctx):
    if not P.disponible():
        return _pas_de_modele(fig)
    t = P.ecoles_et_pouvoir()
    donnees(t)
    ecole = ctx.options.get("ecole") or "École nationale d'administration"
    m = P.ministres_d_une_ecole(ecole)
    if len(m):
        donnees(m[["qui", "annee_sortie", "promotion", "premier"]].rename(columns={"premier": "premier poste au gouvernement"}),
                f"membres d'un gouvernement passés par : {ecole}")
    mesures = [("elus", "élus (tous mandats)"), ("parlementaires_ou_president", "parlementaires ou président"),
               ("gouvernement", "membres d'un gouvernement"), ("prefets", "préfets"), ("grands_corps", "grands corps")]
    ax = fig.add_subplot()
    y = np.arange(len(t))
    h = 0.16
    for k, (col, lib) in enumerate(mesures):
        ax.barh(y + (k - 2) * h, t[col], height=h, color=SERIES[k], label=lib)
    ax.set_yticks(y, [f"{court(e, 40)} ({int(n)} connus)" for e, n in zip(t["ecole"], t["diplomes"])], fontsize=T(9))
    ax.invert_yaxis()
    ax.legend(fontsize=T(8), loc="lower right")
    titre(ax, "Les écoles et le pouvoir", "parmi les diplômés connus de chaque école : combien d'élus, de membres d'un gouvernement, de préfets…")
    fig.tight_layout()
    ena = t[t["ecole"] == ecole]
    return {"legende": [], "kpi": [(str(len(m)), f"membres d'un gouvernement : {court(ecole, 22)}"),
                                   (str(int(ena["diplomes"].iloc[0])) if len(ena) else "—", "diplômés connus"),
                                   (str(int(t["gouvernement"].sum())), "ministres passés par une de ces écoles")],
            "lecture": "Diplômés connus : Wikidata pour l'ENA, Sciences Po et l'X (seulement les gens « notables » : la part des "
                       "énarques devenus ministres y est surestimée, celle des ministres énarques est fiable) ; Journal officiel "
                       "pour les IRA (listes de sortie 1993-2018). Choisis une école à droite : la liste de ses ministres est dans l'export."}


def cumuls(fig, ctx):
    t = P.cumuls()
    if t.empty:
        return vide(fig, "Aucun cumul de mandats en cours dans la base.")
    donnees(t[["qui", "mandats"]])
    c = t.groupby("mandats").size().sort_values()
    ax = fig.add_subplot()
    ax.barh(range(len(c)), c.values, color=C["primaire"])
    ax.set_yticks(range(len(c)), [court(x, 60) for x in c.index], fontsize=T(9))
    for i, v in enumerate(c.values):
        ax.text(v, i, f" {v}", va="center", fontsize=T(9), color=C["gris"])
    titre(ax, "Qui cumule aujourd'hui ?", "personnes qui ont en même temps deux mandats ou fonctions de ces natures (mandats en cours)")
    fig.tight_layout()
    return {"legende": [], "kpi": [(str(len(t)), "personnes"), (str(int(c.get("député + maire", 0))), "député + maire"),
                                   (str(int(c.get("maire + sénateur", 0))), "maire + sénateur")],
            "lecture": "Député ou sénateur + maire est interdit depuis 2017 : un élu a un mois pour choisir, et le Répertoire "
                       "national des élus n'est pas toujours à jour. Maire + président d'intercommunalité est autorisé. "
                       "La liste nominative est dans l'export (Ctrl+E)."}


def maires(fig, ctx):
    t = P.portrait_maires()
    donnees(t)
    axes = fig.subplots(1, 3)
    for ax, (col, lib, unite) in zip(axes, [("femmes", "Part de femmes", " %"), ("age_median", "Âge médian", " ans"),
                                            ("deja_maires", "Déjà maires de la commune\nà la version précédente", " %")]):
        v = t[col].fillna(0)
        ax.bar(range(len(t)), v, color=[C["doux"], C["moyen"], C["primaire"]])
        ax.set_xticks(range(len(t)), t["version"], fontsize=T(8), rotation=15)
        for i, (x, brut) in enumerate(zip(v, t[col])):
            ax.text(i, x, fmt(brut, 1, unite) if pd.notna(brut) else "—", ha="center", va="bottom", fontsize=T(9))
        ax.set_title(lib, fontsize=T(10), loc="left")
        ax.grid(axis="x", visible=False)
    fig.suptitle("Les maires de France : 2014, 2020, 2026", x=0.02, ha="left", fontsize=T(12))
    fig.tight_layout()
    der = t.iloc[-1]
    return {"legende": [], "kpi": [(str(int(der["maires"])), "maires (août 2026)"), (fmt(der["femmes"]), "de femmes"),
                                   (fmt(der["deja_maires"]), "déjà maires en 2020")],
            "lecture": "Trois photos du Répertoire national des élus : janvier 2020 (élus en 2014), décembre 2020 (élus en 2020), "
                       "août 2026 (élus en 2026). « Déjà maires » : la même personne, maire de la même commune à la photo d'avant."}


# ------------------------------------------------------------------------------------------------------------------
# Dans le temps › Le premier à chaque élection (fiefs) ; Bascules départementales
# ------------------------------------------------------------------------------------------------------------------
def premiers(fig, ctx):
    t = P.premiers(ctx.zone)
    if t.empty:
        return vide(fig, "Aucun résultat dans cette zone.")
    donnees(t[["scrutin", "type", "annee", "nuance", "pct"]].rename(columns={"nuance": "en tête", "pct": "score %"}))
    types_ = [x for x in P.TYPES_FIEFS if x in set(t["type"])]
    ax = fig.add_subplot()
    for _, r in t.iterrows():
        y = types_.index(r["type"])
        ax.scatter(mdates.date2num(r["date"]), y, s=420 * theme.ZOOM, marker="s", color=r["couleur"], edgecolors="white", zorder=3)
        ax.text(mdates.date2num(r["date"]), y + 0.32, court(r["nuance"], 10), ha="center", va="top", fontsize=T(7), color=C["texte2"])
    ax.set_yticks(range(len(types_)), types_, fontsize=T(9))
    ax.set_ylim(len(types_) - 0.4, -0.6)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    titre(ax, f"Qui arrive en tête, élection après élection — {ctx.zone.libelle}",
          "1er tour de chaque élection depuis 1999 ; la couleur = le camp de la nuance (ou du candidat) arrivée en tête")
    fig.tight_layout()
    camps = t["couleur"].value_counts()
    domine = camps.index[0]
    part = 100 * camps.iloc[0] / len(t)
    exemple = t[t["couleur"] == domine]["nuance"].mode().iloc[0]
    return {"legende": [(court(n, 30), c) for n, c in t.drop_duplicates("couleur")[["nuance", "couleur"]].values][:12],
            "kpi": [(fmt(part, 0), f"des élections gagnées par le même camp ({court(exemple, 12)})"),
                    (str(len(t)), "élections"), (str(t["couleur"].nunique()), "camps différents en tête")],
            "lecture": "Un fief : la même couleur d'une élection à l'autre, quel que soit le type. Plus le premier camp gagne "
                       "souvent, plus le résultat de la zone se devine à l'avance. Arrivé en tête au 1er tour ≠ élu."}


def bascules(fig, ctx):
    avant, apres = "2015_dpmt_t1", "2021_dpmt_t1"
    a, b = P.majorites_departementales(avant), P.majorites_departementales(apres)
    if a.empty or b.empty:
        return vide(fig, "Les sièges des départementales 2015 et 2021 ne sont pas figés : lance figer_sieges.py.")
    t = a.merge(b, on="dep", suffixes=("_2015", "_2021"))
    noms = d.noms_zones("departement")
    t["departement"] = t["dep"].map(lambda c: noms.get(c, c))
    t["bascule"] = t["bloc_2015"] != t["bloc_2021"]
    t = t.sort_values(["bascule", "departement"], ascending=[False, True]).reset_index(drop=True)
    donnees(t[["departement", "bloc_2015", "sieges_2015", "total_2015", "bloc_2021", "sieges_2021", "total_2021", "bascule"]]
            .rename(columns={"bloc_2015": "camp 2015", "bloc_2021": "camp 2021"}))
    hauteur_liste(fig, len(t), 0.3)
    ax = fig.add_subplot()
    for i, r in t.iterrows():
        ax.scatter([0, 1], [i, i], s=170 * theme.ZOOM, marker="s", zorder=3,
                   color=[theme.COULEURS_BLOCS[r["bloc_2015"]], theme.COULEURS_BLOCS[r["bloc_2021"]]])
        ax.text(1.25, i, f"{r['bloc_2015']} → {r['bloc_2021']}  ◀ bascule" if r["bascule"] else r["bloc_2021"], va="center",
                fontsize=T(9), color=C["action"] if r["bascule"] else C["gris"], weight="bold" if r["bascule"] else "normal")
    ax.set_yticks(range(len(t)), [court(x, 26) for x in t["departement"]], fontsize=T(9))
    ax.set_xticks([0, 1], ["2015", "2021"], fontsize=T(10))
    ax.set_xlim(-0.6, 3.2)
    ax.set_ylim(len(t) - 0.5, -0.5)
    ax.grid(False)
    titre(ax, "Les conseils départementaux qui ont changé de camp (2015 → 2021)",
          "le camp qui a le plus de sièges dans chaque conseil ; les bascules en haut")
    fig.set_layout_engine("tight")
    return {"legende": [(b_, c_) for b_, c_ in theme.COULEURS_BLOCS.items()],
            "kpi": [(str(int(t["bascule"].sum())), "conseils qui ont changé de camp"), (str(len(t)), "départements"),
                    (fmt(100 * (~t["bascule"]).mean(), 0), "gardés par le même camp")],
            "lecture": "Sièges recalculés à partir des résultats (sièges figés), regroupés en quatre camps : gauche, droite et "
                       "centre, extrême droite, divers. Le camp le plus nombreux n'a pas toujours la majorité absolue."}


# ------------------------------------------------------------------------------------------------------------------
# Personnes › Échiquier politique
# ------------------------------------------------------------------------------------------------------------------
def echiquier(fig, ctx):
    """Les partis sur deux axes (gauche – droite ; souverainisme – europhilie), d'après leurs positions et leurs idéologies
    (Wikidata ; valeur de chaque idéologie : donnees_contexte/partis/ideologies_axes.csv). Avec une personne choisie : son
    trajet d'un parti à l'autre."""
    if not P.disponible():
        return _pas_de_modele(fig)
    t = P.echiquier()
    if t.empty:
        return vide(fig, "Aucun parti placé : lance integrer_partis.py.")
    t["sans_europe"] = t["y"].isna()
    t["y"] = t["y"].fillna(0.0)
    t["couleur"] = t["couleur"].fillna(C["gris"])
    donnees(t[["libelle", "etiquette", "x", "y", "n", "sans_europe", "dissolution"]]
            .rename(columns={"x": "gauche – droite", "y": "Europe", "n": "personnes dans la base"}))
    ax = fig.add_subplot()
    ax.axhline(0, color=C["bordure"], lw=1, zorder=0)
    ax.axvline(0, color=C["bordure"], lw=1, zorder=0)
    taille = 40 + 400 * np.sqrt(t["n"] / t["n"].max())
    pleins = ~t["sans_europe"]
    ax.scatter(t.loc[pleins, "x"], t.loc[pleins, "y"], s=taille[pleins], c=t.loc[pleins, "couleur"], alpha=0.85,
               edgecolors="white", linewidths=1, zorder=2)
    ax.scatter(t.loc[~pleins, "x"], t.loc[~pleins, "y"], s=taille[~pleins], facecolors="none", edgecolors=t.loc[~pleins, "couleur"],
               linewidths=1.5, zorder=2)
    for r in t.itertuples():
        ax.annotate(court(r.etiquette, 18), (r.x, r.y), xytext=(0, 9), textcoords="offset points", ha="center",
                    fontsize=T(8), color=C["texte"])
    trajet_txt = ""
    pid = ctx.options.get("personne")
    if pid:
        f = P.fiche(int(pid))
        tr = P.trajet(int(pid)).merge(t[["id", "x", "y"]], left_on="parti_id", right_on="id")
        if len(tr) and f is not None:
            ax.plot(tr["x"], tr["y"], color=C["primaire"], lw=2, zorder=3)
            ax.scatter(tr["x"].iloc[-1:], tr["y"].iloc[-1:], s=120, marker="*", color=C["primaire"], zorder=4)
            trajet_txt = f" Trajet de {f['nom']} : " + " → ".join(tr["etiquette"]) + "."
    ax.set_xlim(-2.4, 2.4)
    ax.set_ylim(-2.4, 2.4)
    ax.set_xlabel("← gauche · droite →", fontsize=T(9))
    ax.set_ylabel("← souverainisme · europhilie →", fontsize=T(9))
    titre(ax, "L'échiquier politique", "un rond par parti (taille : personnes connues dans la base) · rond vide : pas d'idée "
                                        "sur l'Europe dans Wikidata")
    fig.tight_layout()
    return {"legende": [], "kpi": [(str(len(t)), "partis placés"), (str(int(pleins.sum())), "placés sur l'Europe"),
                                   (str(int(t["n"].sum())), "personnes reliées")],
            "lecture": "Place de chaque parti : la moyenne de ses positions (Wikidata : gauche, centre droit…) et des valeurs de ses "
                       "idéologies, de -2 à +2 sur chaque axe (fichier donnees_contexte/partis/ideologies_axes.csv, à corriger "
                       "puis relancer integrer_partis.py)." + trajet_txt}


# ------------------------------------------------------------------------------------------------------------------
# Personnes › Idéologies d'une zone
# ------------------------------------------------------------------------------------------------------------------
def ideologies_zone(fig, ctx):
    """Les idéologies qui pèsent dans la zone aux législatives 2017, 2022, 2024 (1er tour) : voix des candidats →
    leur parti de rattachement → les idéologies du parti (Wikidata)."""
    if not P.disponible():
        return _pas_de_modele(fig)
    series = {s[:4]: d.ideologies_zone(s, ctx.zone).set_index("ideologie")["pct"] for s in d.ELECTIONS_IDEOLOGIES}
    t = pd.DataFrame(series).fillna(0)
    if t.empty:
        return vide(fig, "Aucune voix reliée à un parti dans cette zone.")
    t = t.sort_values(list(series)[-1], ascending=False).head(14)
    donnees(t.round(1).reset_index().rename(columns={"index": "idéologie"}))
    ax = fig.add_subplot()
    y = np.arange(len(t))
    h = 0.8 / len(series)
    for k, (an, col) in enumerate(zip(series, [C["moyen"], C["gris"], C["primaire"]])):
        ax.barh(y + (k - 1) * h, t[an], height=h, color=col, label=f"législatives {an}")
    ax.set_yticks(y, [court(i, 32) for i in t.index], fontsize=T(9))
    ax.invert_yaxis()
    ax.set_xlabel("% des exprimés (1er tour) — une voix compte pour chaque idéologie du parti", fontsize=T(8))
    ax.legend(fontsize=T(8), loc="lower right")
    titre(ax, f"Les idéologies qui pèsent — {ctx.zone.libelle}", "législatives, 1er tour : voix → parti de rattachement du candidat → "
                                                                "idéologies du parti (Wikidata)")
    fig.tight_layout()
    an = list(series)[-1]
    tete = t[an].idxmax()
    return {"legende": [(f"législatives {a}", c) for a, c in zip(series, [C["moyen"], C["gris"], C["primaire"]])],
            "kpi": [(court(tete, 18), f"en tête en {an}"), (fmt(t.loc[tete, an], 0, " %"), "des exprimés")],
            "lecture": "Une voix compte pour chacune des idéologies du parti de son candidat : les pourcentages ne s'additionnent pas. "
                       "Partis de rattachement : ministère de l'Intérieur (législatives 2017-2024) ; idéologies : Wikidata "
                       "(une coalition, comme la NUPES, prend celles de ses partis)."}
