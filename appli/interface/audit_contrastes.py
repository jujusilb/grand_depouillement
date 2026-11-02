"""
audit_contrastes.py — Mesure les contrastes de l'appli (WCAG 2.1, critères 1.4.3 et 1.4.11).

    py outils/audit_contrastes.py          (depuis le dossier le_grand_depouillement)

Il lit le code de la fenêtre (gd/fenetre.py, gd/theme.py) et des graphiques (gd/graphiques.py) et, pour chaque texte posé sur
un fond (fg= / bg=, styles ttk, textes des graphiques), calcule le rapport de contraste :
    texte normal  ≥ 4,5 : 1   (AA)      grand texte (≥ 18 pt, ou ≥ 14 pt gras) ≥ 3 : 1
    éléments graphiques (bordures de champs, pastilles de légende, points) ≥ 3 : 1 sur leur fond
"""
import re
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ICI))                       # (le dossier appli/)
from interface import theme  # noqa: E402
from interface.theme import C  # noqa: E402


def lum(couleur):
    h = couleur.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contraste(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


NOMMEES = {"white": "#FFFFFF", "black": "#000000"}


def resoudre(expr):
    """« C["gris"] » → #666666 ; « "#ABCDEF" » → #ABCDEF ; sinon None (couleur calculée : vérifiée à part)."""
    expr = expr.strip()
    m = re.fullmatch(r'C\["(\w+)"\]', expr)
    if m:
        return C.get(m.group(1))
    m = re.fullmatch(r'"(#[0-9A-Fa-f]{3,6}|white|black)"', expr)
    if m:
        return NOMMEES.get(m.group(1), m.group(1))
    return None


resultats = []
# 1. les widgets tkinter : une ligne avec bg= et fg=
for fichier in ("gd/fenetre.py", "gd/theme.py"):
    for n, ligne in enumerate((ICI / fichier).read_text(encoding="utf-8").splitlines(), 1):
        bg = re.search(r"\bbg=(C\[\"\w+\"\]|\"[^\"]+\")", ligne)
        fg = re.search(r"\bfg=(C\[\"\w+\"\]|\"[^\"]+\")", ligne)
        if bg and fg:
            a, b = resoudre(fg.group(1)), resoudre(bg.group(1))
            if a and b:
                petit = "POLICE_PETITE" in ligne or "POLICE_INTER" in ligne
                resultats.append((contraste(a, b), 4.5, f"{fichier}:{n}", f"texte {fg.group(1)} sur {bg.group(1)}" + (" (petit)" if petit else "")))
# 2. les styles ttk (foreground sur background, ou sur le fond par défaut)
styles = {"Gris.TLabel": (C["gris"], C["fond"]), "Libelle.TLabel": (C["gris"], C["pale"]), "Inter.TLabel": (C["primaire"], C["fond"]),
          "Etat.TLabel": (C["texte2"], C["surface"]), "Clair.TButton": (C["primaire"], C["clair"]), "Action.TButton": (C["sur"], C["action"]),
          "Treeview.Heading": (C["texte2"], C["surface"]), "Combobox désactivée": (C["gris"], C["surface"]),
          "Liste déroulante (sélection)": (C["primaire"], C["clair"])}
for nom, (a, b) in styles.items():
    resultats.append((contraste(a, b), 4.5, "gd/theme.py (styles ttk)", nom))
# 3. les éléments non textuels (1.4.11 : 3:1)
for nom, (a, b) in {"bordure des champs (combobox, saisie)": (C["bordure_champ"], C["carte"]), "contour des pastilles et onglets": (C["moyen"], C["carte"]),
                    "liseré du focus clavier (sur blanc)": (C["focus"], C["carte"]), "liseré du focus clavier (sur le bleu)": (C["focus"], C["primaire"]),
                    "curseur de l'ascenseur": ("#8A8A8A", C["surface"]), "axes des graphiques": ("#8A8A8A", C["carte"]),
                    "contour des pastilles de légende": (C["gris"], C["carte"])}.items():
    resultats.append((contraste(a, b), 3.0, "gd/theme.py", nom))
# 4. les graphiques : textes gris, couleurs des votes, des familles et des séries sur fond blanc (1.4.11)
resultats.append((contraste(C["texte2"], C["carte"]), 4.5, "theme.appliquer_matplotlib", "graduations des axes"))
from politique import votes  # noqa: E402
for p, coul in votes.POSITIONS.items():
    resultats.append((contraste(coul, C["carte"]), 3.0, "gd/votes.py POSITIONS", f"rond « {p} » sur blanc"))
for f, coul in theme.FAMILLES.items():
    # les couleurs officielles des partis restent (identité) : la pastille de légende a un contour, la valeur est écrite à côté
    resultats.append((max(contraste(coul, C["carte"]), contraste(C["gris"], C["carte"])), 3.0, "gd/theme.py FAMILLES",
                      f"famille « {f} » sur blanc ({contraste(coul, C['carte']):.1f} seule ; contour gris)"))
    resultats.append((contraste(theme.texte_sur(coul), coul), 4.5, "gd/graphiques.py (tableau des élus)", f"texte (noir ou blanc) sur « {f} »"))
for i, coul in enumerate(theme.SERIES):
    resultats.append((contraste(coul, C["carte"]), 3.0, "gd/theme.py SERIES", f"série n° {i + 1} {coul} sur blanc"))

echecs = [r for r in resultats if r[0] < r[1]]
for ratio, seuil, ou, quoi in sorted(resultats):
    print(f"{'ÉCHEC' if ratio < seuil else 'ok   '}  {ratio:5.2f} (≥ {seuil})  {quoi:<55} {ou}")
print(f"\n{len(echecs)} échecs sur {len(resultats)} combinaisons mesurées")
