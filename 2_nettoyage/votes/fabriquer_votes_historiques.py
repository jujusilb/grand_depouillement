"""
fabriquer_votes_historiques.py — Les grands votes d'avant 2012, député par député, lus dans le Journal officiel (PDF numérisés,
1959-1991) ou sur le site de l'Assemblée (pages web d'analyse des scrutins, 1998-2010).

    py fabriquer_votes_historiques.py

Les PDF sont des pages numérisées : le texte lu par la machine a des fautes (« Iionrepaux » pour Bonrepaux) et les colonnes
se mélangent parfois. On garde le nom TEL QU'IMPRIMÉ et on compare le nombre de noms lus au résultat officiel :
la colonne « complet » dit si la liste est gardée (au plus 4 % de noms manquants, rien de trop).
Sorties : votes_scrutins_historiques.parquet, votes_individuels_historiques.parquet (même forme que l'open data, sans identifiant de député).
Une liste PDF incomplète (colonnes mélangées par la numérisation) n'est PAS gardée : seul le résultat officiel l'est.
"""
import html
import sys
import re
from pathlib import Path

import pandas as pd
import pypdf

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("votes")
JO, WEB = ICI / "brut" / "jo", ICI / "brut" / "web"

# id, date, objet, source (fichier), début du bloc dans le texte, résultat officiel (pour, contre)
VOTES = [
    ("JO1959-debre", "1959-12-23", "Loi Debré : l'ensemble du projet de loi sur les rapports entre l'État et l'enseignement privé",
     "1_1959-1960-extraordinaire1_005.pdf", r"Pour l.adoption\s*427", (427, 71)),
    ("JO1962-censure", "1962-10-04", "Motion de censure contre le gouvernement Pompidou (seuls les « pour » sont comptés)",
     "1_1962-1963-ordinaire1_003.pdf", r"Ont vot. pour \(", (280, 0)),
    ("JO1974-veil", "1974-11-28", "Loi Veil : l'ensemble du projet de loi relatif à l'interruption volontaire de la grossesse",
     "5_1974-1975-ordinaire1_077.pdf", r"SCRUTIN\s*\(\s*N\S{0,3}\s*120\s*\)", (284, 189)),
    ("JO1981-peine-de-mort", "1981-09-18", "L'ensemble du projet de loi portant abolition de la peine de mort",
     "7_1980-1981-extraordinaire2_017.pdf", r"SCRUTIN\s*\(\s*N\S{0,3}\s*60\s*\)", (363, 117)),
    ("JO1981-homosexualite", "1981-12-20", "Dépénalisation de l'homosexualité : l'article unique de la proposition de loi",
     "7_1981-1982-ordinaire1_153.pdf", r"SCRUTIN\s*\(\s*N\S{0,3}\s*213\s*\)", (327, 155)),
    ("JO1988-rmi", "1988-10-12", "L'ensemble du projet de loi relatif au revenu minimum d'insertion",
     "9_1988-1989-ordinaire1_010.pdf", r"SCRUTIN\s*\(\s*N\S{0,3}\s*11\s*\)", (547, 3)),
    ("JO1990-gayssot", "1990-05-02", "Loi Gayssot : l'ensemble de la proposition de loi tendant à réprimer tout acte raciste, antisémite ou xénophobe",
     "9_1989-1990-ordinaire2_031.pdf", r"SCRUTIN\s*\(\s*N\S{0,3}\s*292\s*\)", (307, 265)),
    ("JO1990-evin", "1990-12-11", "Loi Évin : l'ensemble du projet de loi relatif à la lutte contre le tabagisme et l'alcoolisme",
     "9_1990-1991-ordinaire1_114.pdf", r"SCRUTIN\s*\(\s*N\S{0,3}\s*406\s*\)", (321, 9)),
    ("JO1991-golfe", "1991-01-16", "Guerre du Golfe : approbation de la déclaration du Gouvernement (article 49, alinéa 1er)",
     "9_1990-1991-extraordinaire1_001.pdf", r"Ont vot. pour\s+Pour l.adoption", (523, 43)),
]
PAGES_WEB = [   # id, date, objet, fichier (le résultat officiel est lu dans la page)
    ("AN11-00093", "1998-02-10", "35 heures : l'ensemble du projet de loi relatif à la réduction du temps de travail", "11_jo0093.html"),
    ("AN12-00436", "2004-02-10", "L'ensemble du projet de loi sur la laïcité à l'école (signes religieux)", "12_jo0436.html"),
    ("AN12-00678", "2004-11-30", "Loi Leonetti : l'ensemble de la proposition de loi relative aux droits des malades et à la fin de vie", "12_jo0678.html"),
    ("AN12-01094", "2007-02-19", "L'ensemble du projet de loi constitutionnelle relatif à l'interdiction de la peine de mort", "12_jo1094.html"),
    ("CONGRES2008", "2008-07-21", "Congrès : révision constitutionnelle de modernisation des institutions (députés ET sénateurs)", "13_jo9001.html"),
    ("AN13-00195", "2008-09-22", "Autorisation de la prolongation de l'intervention des forces armées en Afghanistan", "13_jo0195.html"),
    ("AN13-00595", "2010-07-13", "L'ensemble du projet de loi interdisant la dissimulation du visage dans l'espace public", "13_jo0595.html"),
    ("AN13-00646", "2010-10-27", "Retraites : l'ensemble du projet de loi portant réforme des retraites (texte de la CMP)", "13_jo0646.html"),
]

ENTETES = [(r"Ont\s*vot\S*\s+pour", "pour"), (r"Ont\s*vot\S*\s+(contre|confie|centre|coutre)", "contre"),
           (r"abstenus?\s+volontairement", "abstention"), (r"N.\s*ont\s+pas\s+pris\s+part\s+au\s+vote", "non-votant"),
           (r"N.\s*a\s+pas\s+pris\s+part\s+au\s+vote", "non-votant"), (r"Excus.s?\s+ou\s+absents?\s+par\s+cong", "excusé")]
FIN = r"ANALYSE DU SCRUTIN|Mises au point|SCRUTIN\s*\(\s*N\S{0,3}\s*\d+|Groupe socialiste|Imprimerie des Journaux"


def texte_en_colonnes(chemin):
    """Le texte des pages, colonne après colonne (et pas ligne après ligne à travers les colonnes) quand la page est lue
    en petits morceaux (un nom chacun) ; sinon (morceaux = lignes entières qui traversent les colonnes) : tel quel."""
    morceaux_pages = []
    for page in pypdf.PdfReader(chemin).pages:
        m = []
        page.extract_text(visitor_text=lambda t, cm, tm, f, s: m.append((tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5], t.strip()))
                          if t.strip() else None)
        longueurs = sorted(len(t) for _, _, t in m)
        if not m or longueurs[len(longueurs) // 2] > 35:
            morceaux_pages.append(page.extract_text() or "")
            continue
        xs = sorted({round(x) for x, _, _ in m})
        bords = [b for a, b in zip(xs, xs[1:]) if b - a > 40]          # une colonne commence après un « trou » de 40 points
        m.sort(key=lambda p: (sum(p[0] >= b for b in bords), -p[1]))
        morceaux_pages.append("\n".join(t for _, _, t in m))
    return "\n".join(morceaux_pages)


def noms_du_bloc(bloc):
    """« Ansquer . Audinot . Aubert (François d ') . » → les noms, un par un."""
    bloc = re.sub(r"ASSEMBL.E NATIONALE.{0,60}?(19\d\d|SEANCE|SÉANCE)\S*", " ", bloc)
    morceaux = re.split(r"\s*\.\s+(?=[A-ZÉÈÀÂÎÔÛÇ])|\n|\s*;\s*|,\s+(?=[A-ZÉ][a-zé])", bloc)
    noms, attente = [], ""
    for m in morceaux:
        m = attente + " " + m if attente else m
        if m.count("(") > m.count(")") and not attente and len(m) < 30:     # « Harcourt (François » + « d') » ; une seule fois
            attente = m
            continue
        attente = ""
        m = re.sub(r"^[^A-Za-zÀ-ÿ(]+", "", m.strip())                          # « {{ Delatre » → « Delatre »
        m = re.sub(r"^(MM?\.|Mmes?|Mlle|M\s)\s*", "", m).strip(" .,:;'")
        mots = m.split()
        if mots and sum(len(x) <= 2 for x in mots) > len(mots) / 2:          # « H a by ( R ené) » → « Haby (René) »
            m = re.sub(r"\s+", "", m).replace("(", " (")
        for n in re.split(r"\s+et\s+", m):                                    # « Houteer et Rigaud »
            n = n.strip(" .,:;'")
            if (3 <= len(n) <= 45 and len(n.split()) <= 5 and re.search(r"[a-zéèàïô]", n) and (n[:1].isupper() or " " not in n)
                    and not re.search(r"\d{2,}|Nombre|Majorit|adopt|scrutin|Pour l|Contre|Journal|Débats|porté|«|»|\b(les|aux|une|sur|pour|par|qui)\b", n)):
                noms.append(n)
    return noms


def cellules_par_bloc(chemin):
    """pdfplumber : chaque mot avec sa position. On regroupe les mots en « cellules » (mots voisins d'une même ligne),
    puis chaque page en deux blocs (moitié gauche, moitié droite), lus l'un après l'autre.
    Rend la liste des blocs : [(lignes du bloc = [(haut, texte de la ligne)], cellules = [(x, haut, texte)])]."""
    import pdfplumber
    blocs = []
    with pdfplumber.open(chemin) as pdf:
        for page in pdf.pages:
            mots = page.extract_words(x_tolerance=1.5, y_tolerance=2)
            rangs = {}
            for m in mots:
                rangs.setdefault(round(m["top"] / 3), []).append(m)
            cellules = []
            for k in sorted(rangs):
                ligne = sorted(rangs[k], key=lambda m: m["x0"])
                cel = [ligne[0]]
                for m in ligne[1:] + [None]:
                    if m is None or m["x0"] - cel[-1]["x1"] > 6:
                        cellules.append((cel[0]["x0"], cel[0]["top"], " ".join(c["text"] for c in cel)))
                        cel = [m]
                    else:
                        cel.append(m)
            milieu = page.width / 2
            for gauche in (True, False):
                cel = [c for c in cellules if (c[0] < milieu) == gauche]
                lignes = {}
                for x, h, t in sorted(cel, key=lambda c: (round(c[1] / 3), c[0])):
                    lignes.setdefault(round(h / 3), []).append(t)
                blocs.append(([(k * 3, " ".join(v)) for k, v in sorted(lignes.items())], cel))
    return blocs


def colonnes_en_ordre(cellules):
    """Des cellules de noms → les noms, colonne après colonne (une colonne commence là où beaucoup de cellules commencent)."""
    if not cellules:
        return []
    xs = sorted(c[0] for c in cellules)
    debuts = []
    for x in xs:
        if not debuts or x - debuts[-1][0] > 20:
            debuts.append([x, 0])
        debuts[-1][1] += 1
    debuts = [x for x, n in debuts if n >= 4] or [xs[0]]
    col = lambda x: max([i for i, d in enumerate(debuts) if d <= x + 12] or [0])
    rangees = sorted(cellules, key=lambda c: (col(c[0]), c[1]))
    # les morceaux de nom coupés (« Aubert (François » + « d') . », « Mme Moreau » + « (Louise) . ») : recollés
    noms = []
    for x, h, t in rangees:
        ouvert = noms and noms[-1].count("(") > noms[-1].count(")")
        suite = t[:1].islower() or t[:1] == "(" or t.startswith("d'") or (ouvert and ")" in t and len(t) < 25 and t.find(")") < t.find(".") + 2)
        if noms and suite and len(noms[-1]) < 40:
            noms[-1] += " " + t
        else:
            noms.append(t)
    return noms


def depuis_pdf(vid, date, objet, fichier, debut, officiel):
    """La liste nominative d'un scrutin dans le Journal officiel, lue par position (pdfplumber)."""
    etat, section, votes, vues = "avant", None, [], set()
    for lignes, cellules in cellules_par_bloc(JO / fichier):
        evenements = []          # (haut, sorte, valeur) : début du scrutin, titre de section, fin
        for h, texte in lignes:
            if etat == "avant" and re.search(debut, texte, flags=re.I):
                evenements.append((h, "debut", None))
            elif re.search(r"ANALYSE DU SCRUTIN|Mises au point|SCRUTIN\s*\(\s*N\S{0,3}\s*\d+", texte, flags=re.I):
                evenements.append((h, "fin", None))
            for motif, pos in ENTETES:
                if re.search(motif, texte, flags=re.I):
                    evenements.append((h + 0.1, "section", pos))
                    break
        evenements.sort()
        bornes = [e[0] for e in evenements] + [1e9]
        cel_avant = [c for c in cellules if c[1] < bornes[0] - 1]
        morceaux = [(None, cel_avant)] + [(e, [c for c in cellules if e[0] - 1 <= c[1] < bornes[i + 1] - 1])
                                          for i, e in enumerate(evenements)]
        for e, cel in morceaux:
            if e is not None:
                if e[1] == "debut":
                    etat, section = "dedans", None
                elif e[1] == "fin" and etat == "dedans" and section is not None:
                    etat = "fini"
                elif e[1] == "section" and etat == "dedans":
                    if e[2] in vues:            # une section déjà vue : c'est le scrutin suivant qui commence
                        etat = "fini"
                    else:
                        section = e[2]
                        vues.add(e[2])
            if etat == "dedans" and section and section != "excusé":
                cel = [c for c in cel if not re.search(r"Ont vot|abstenus|pris part|Excus|Nombre|Majorit|adoption|Contre\s+\d", c[2], re.I)]
                votes += [(vid, n, section) for n in noms_du_bloc("\n".join(colonnes_en_ordre(cel)))]
        if etat == "fini":
            break
    return votes


def depuis_pdf_ancien(vid, date, objet, fichier, debut, officiel):
    texte = texte_en_colonnes(JO / fichier)
    i = re.search(debut, texte)
    if not i:
        print(f"  {vid} : début introuvable"); return []
    suite = texte[i.end():]
    # les sections jusqu'à la fin du scrutin (début de l'analyse par groupe, ou scrutin suivant)
    positions = []
    for motif, pos in ENTETES:
        for m in re.finditer(motif, suite[:60000], flags=re.I):
            positions.append((m.start(), m.end(), pos))
    positions.sort()
    votes, vus = [], set()
    for k, (a, b, pos) in enumerate(positions):
        if pos in vus:                           # la 1re section de chaque sorte (les suivantes : autre scrutin)
            continue
        vus.add(pos)
        fin = positions[k + 1][0] if k + 1 < len(positions) else len(suite)
        bloc = suite[b:fin]
        f = re.search(FIN, bloc)
        votes += [(vid, n, pos) for n in noms_du_bloc(bloc[:f.start()] if f else bloc)]
    return votes


def depuis_web(vid, fichier):
    brut = (WEB / fichier).read_bytes()
    try:
        t = brut.decode("utf-8")
    except UnicodeDecodeError:                 # les pages du Congrès sont en Windows-1252
        t = brut.decode("cp1252")
    t = re.sub(r"(?s)<(script|style).*?</\1>", " ", t)
    t = t[t.find("Nombre de votants"):]
    t = t[:t.find("Mises au point")] if "Mises au point" in t else t      # (les rectifications répètent des noms)
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", t)))
    resultat = (int(re.search(r"Pour l.(?:adoption|approbation)[\s|:]*(\d+)", t).group(1)), int(re.search(r"Contre[\s|:]*(\d+)", t).group(1)))
    votes, groupe, pos = [], None, None
    for m in re.finditer(r"(GROUPE[^|(]*|NON[ -]INSCRITS?|S.NAT[^|(]*)\s*\(\d+\)|\b(POUR|CONTRE|ABSTENTIONS?|NON[ -]VOTANTS?)\s*:[\s|]*\d*"
                         r"|([A-ZÉ][\w'’\-\. ]{0,40}?)\s*\|([^|]{2,60})\|", t, flags=re.I):
        if m.group(1):
            groupe = m.group(1).strip().removeprefix("GROUPE ").removeprefix("Groupe ").title()
        elif m.group(2):
            mot = m.group(2).upper()
            pos = {"POUR": "pour", "CONTRE": "contre"}.get(mot, "abstention" if mot.startswith("ABST") else "non-votant")
        elif pos and groupe:
            prenom = re.sub(r"^(MM?\.|Mmes?)\s+", "", m.group(3).strip())
            votes.append((vid, f"{prenom} {m.group(4).strip()}", pos, groupe))
    return resultat, votes


scrutins, individus = [], []
for vid, date, objet, fichier, debut, officiel in VOTES:
    v = depuis_pdf(vid, date, objet, fichier, debut, officiel)
    lus = {p: sum(1 for x in v if x[2] == p) for p in ("pour", "contre", "abstention")}
    # gardée si rien de trop (à la marge près) et au plus 4 % de noms manquants (les noms lus sont alors bien rangés)
    complet = all(o - 0.04 * o - 1 <= lus[p] <= o + max(4, 0.015 * o) for p, o in (("pour", officiel[0]), ("contre", officiel[1])))
    scrutins.append((vid, int(date[:4]), date, objet, officiel[0], officiel[1], lus["abstention"], "Journal officiel (PDF numérisé)", complet,
                     lus["pour"], lus["contre"]))
    individus += [(a, n, p, None) for a, n, p in v] if complet else []      # une liste mal lue ne doit pas dire « X a voté contre »
    print(f"  {vid:<22} lus : {lus['pour']:>3} pour / {lus['contre']:>3} contre   (officiel {officiel[0]} / {officiel[1]})  {'OK' if complet else 'INCOMPLET'}")
for vid, date, objet, fichier in PAGES_WEB:
    officiel, v = depuis_web(vid, fichier)
    lus = {p: sum(1 for x in v if x[2] == p) for p in ("pour", "contre", "abstention")}
    complet = abs(lus["pour"] - officiel[0]) <= 3 and abs(lus["contre"] - officiel[1]) <= 3
    scrutins.append((vid, int(date[:4]), date, objet, officiel[0], officiel[1], lus["abstention"], "site de l'Assemblée", complet,
                     lus["pour"], lus["contre"]))
    individus += v
    print(f"  {vid:<22} lus : {lus['pour']:>3} pour / {lus['contre']:>3} contre   (officiel {officiel[0]} / {officiel[1]})  {'OK' if complet else 'INCOMPLET'}")

s = pd.DataFrame(scrutins, columns=["scrutin", "annee", "date", "objet", "pour", "contre", "abstention", "source", "complet", "pour_lus", "contre_lus"])
s["date"] = pd.to_datetime(s["date"])
v = pd.DataFrame(individus, columns=["scrutin", "depute", "position", "groupe"])
s.to_parquet(ICI / "votes_scrutins_historiques.parquet", index=False)
v.to_parquet(ICI / "votes_individuels_historiques.parquet", index=False)
print(f"{len(s)} scrutins · {len(v)} votes · listes complètes : {int(s['complet'].sum())}/{len(s)}")
