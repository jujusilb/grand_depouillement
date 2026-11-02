"""
lire_jorf.py — Lit les articles du Journal officiel mis de côté par extraire_jorf.py et en tire des tableaux propres.

    py lire_jorf.py     → jorf_gouvernement.parquet, jorf_prefets.parquet, jorf_ira.parquet, jorf_grands_corps.parquet

Les phrases du JO sont très régulières depuis 1990 :
    nomination   « M. Thierry MOSIMANN, préfet de l'Aube, est nommé préfet des Côtes-d'Armor[, à compter du 6 janvier 2020]. »
    fin          « Il est mis fin aux fonctions de M. Michel FOURNIER, ministre délégué … »
    liste        « Sont nommés ministres : » puis une ligne par personne « Mme Rachida DATI, ministre de la culture ; »
    élèves       un titre par institut (« Institut régional d'administration de Lille ») puis « Mme Silberstein (Joëlle). »
Les noms : « Prénom NOM » (NOM en capitales depuis 2010 environ), « Prénom Nom » avant ; « Nom (Prénom) » dans les listes.
"""
import re
import sys
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("jorf")
ARTICLES = ICI / "jorf_articles.parquet"
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
PARTICULES = {"de", "du", "des", "d'", "de la", "le", "la", "l'", "van", "von", "di", "da"}


def date_texte(t):
    """« 6 janvier 2020 » ou « 1er janvier 2020 » → « 2020-01-06 » (None si ce n'est pas une date)."""
    m = re.search(r"(\d{1,2})(?:er)?\s+(\w+)\s+(\d{4})", t or "")
    if not m or m[2].lower() not in MOIS:
        return None
    return f"{m[3]}-{MOIS.index(m[2].lower()) + 1:02d}-{int(m[1]):02d}"


def decouper_nom(complet):
    """« Thierry MOSIMANN » → (MOSIMANN, Thierry) ; « Jean-Pierre de Lavernée » → (de Lavernée, Jean-Pierre) ;
    « Jean Dominé » → (Dominé, Jean). Le NOM en capitales est reconnu ; sinon la particule, sinon le dernier mot."""
    entre_parentheses = re.fullmatch(r"\s*(.+?)\s*\(([^)]+)\)?\s*", complet)     # (parenthèse parfois non fermée)
    if entre_parentheses:                                       # (« Marigeaud (Martine) » : le prénom est entre parenthèses)
        return entre_parentheses[1], entre_parentheses[2]
    mots = complet.replace("\xa0", " ").split()
    majuscules = [i for i, m in enumerate(mots) if len(re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", m)) > 1 and m == m.upper()]
    if majuscules:
        i = majuscules[0]
        while i > 1 and mots[i - 1].lower() in PARTICULES:      # (« Jean-Noël de LA COSTE » : la particule va au nom)
            i -= 1
    else:
        i = next((k for k, m in enumerate(mots) if k > 0 and (m.lower() in PARTICULES or m.lower().startswith("d'"))),
                 len(mots) - 1)
    return " ".join(mots[i:]), " ".join(mots[:i])


def sexe(civilite):
    return "F" if civilite.startswith("Mme") else "M"


def textes(famille):
    """Un texte par ligne : ses articles recollés dans l'ordre."""
    a = pd.read_parquet(ARTICLES)
    a = a[a.famille == famille].copy()
    a["n"] = pd.to_numeric(a.num.str.extract(r"(\d+)")[0], errors="coerce").fillna(0)
    a = a.sort_values(["texte", "n", "article"])
    return (a.groupby("texte").agg(titre=("titre", "first"), date_publi=("date_publi", "first"),
                                   date_signature=("date_signature", "first"), contenu=("contenu", "\n".join))
            .reset_index())


def date_du_texte(r):
    """La date de signature (2999-01-01 = inconnue dans les vieux textes : on prend celle du titre, sinon la publication)."""
    return r.date_signature if r.date_signature and not r.date_signature.startswith("2999") \
        else date_texte(r.titre) or r.date_publi


# (« M. X, ancien poste, est nommé poste », « M. X est nommé, à compter du 11 janvier 2016, poste »,
#  « … est nommé, sur sa demande, poste », « … est nommé poste, à compter du … »)
NOMME = re.compile(r"(?P<civ>M\.|Mme)\s+(?P<nom>[^,]+?)(?:,\s+(?P<avant>.+?))?,?\s+est\s+nommée?"
                   r"(?:,\s*(?:à\s+compter\s+du\s+(?P<effet1>\d{1,2}(?:er)?\s+\w+\s+\d{4})|[^,]{0,40}),)?"
                   r"\s+(?P<poste>.+?)(?:,?\s+à\s+compter\s+du\s+(?P<effet>\d{1,2}(?:er)?\s+\w+\s+\d{4}))?\s*(?:\.|;|$)",
                   re.S)


def nominations_simples(famille):
    """Toutes les phrases « M. X, ancien poste, est nommé nouveau poste » d'une famille de textes."""
    lignes = []
    for r in textes(famille).itertuples():
        for m in NOMME.finditer(re.sub(r"\s+", " ", r.contenu)):
            nom, prenom = decouper_nom(m["nom"])
            lignes.append({"texte": r.texte, "titre": r.titre,
                           "date": date_texte(m["effet"] or m["effet1"]) or date_du_texte(r),
                           "date_texte": date_du_texte(r), "sexe": sexe(m["civ"]), "nom": nom, "prenom": prenom,
                           "avant": (m["avant"] or "").strip(), "poste": m["poste"].strip()})
    return pd.DataFrame(lignes)


# ------------------------------------------------------------------------------------------------------------------
# Le gouvernement : nominations du Premier ministre, compositions, fins de fonctions
# ------------------------------------------------------------------------------------------------------------------
RUBRIQUES = [  # en-tête de liste → fonction
    (r"secrétaires? d'(?:é|e)tat", "secrétaire d'État"), (r"ministres? délégués?", "ministre délégué"),
    (r"ministres? d'(?:é|e)tat", "ministre d'État"), (r"ministres?", "ministre"),
]


def rubrique(texte):
    t = texte.lower()
    return next((f for motif, f in RUBRIQUES if re.search(motif, t)), None)


def gouvernement():
    lignes = []
    for r in textes("gouvernement").itertuples():
        date = date_du_texte(r)
        if re.search(r"(?i)nomination du premier ministre", r.titre):
            m = re.search(r"(M\.|Mme)\s+(.+?)\s+est\s+nommée?\s+Premier\s+ministre", re.sub(r"\s+", " ", r.contenu))
            if m:
                nom, prenom = decouper_nom(m[2])
                lignes.append({"texte": r.texte, "date": date, "action": "premier ministre", "sexe": sexe(m[1]), "nom": nom,
                               "prenom": prenom, "poste": "Premier ministre", "fonction": "Premier ministre"})
            continue
        courante = None
        for ligne in r.contenu.splitlines():
            ligne = re.sub(r"^Art(?:icle|\.)\s*\w+\.?\s*-?\s*", "", ligne.strip())
            fin = re.match(r"Il est mis fin(?:,\s+[^,]+,)? aux fonctions de (M\.|Mme)\s+([^,]+),\s+(.+?)\.?$", ligne)
            if fin:
                nom, prenom = decouper_nom(fin[2])
                lignes.append({"texte": r.texte, "date": date, "action": "fin", "sexe": sexe(fin[1]), "nom": nom,
                               "prenom": prenom, "poste": fin[3].strip(" ;."), "fonction": rubrique(fin[3])})
                continue
            entete = re.match(r"(?:Sont|Est) nommée?s?\s+(.+?)\s*:\s*$", ligne)
            if entete:
                courante = rubrique(entete[1])
                continue
            seul = re.match(r"(M\.|Mme)\s+(.+?)\s+est\s+nommée?\s+(.+?)\.?$", ligne)
            liste = re.match(r"(M\.|Mme)\s+([^,]+),\s+(.+?)\s*[;.]?$", ligne)
            if seul or (liste and courante):
                m = seul or liste
                nom, prenom = decouper_nom(m[2])
                poste = m[3].strip(" ;.")
                lignes.append({"texte": r.texte, "date": date, "action": "nomination", "sexe": sexe(m[1]), "nom": nom,
                               "prenom": prenom, "poste": poste,
                               "fonction": rubrique(poste) if seul else courante if courante != "ministre" else rubrique(poste)})
    return pd.DataFrame(lignes).sort_values(["date", "texte"])


# ------------------------------------------------------------------------------------------------------------------
# Les préfets de département
# ------------------------------------------------------------------------------------------------------------------
def departement_du_poste(poste):
    """« préfet de la région Bretagne, préfet d'Ille-et-Vilaine » → « Ille-et-Vilaine » ; None pour un préfet hors cadre,
    délégué, de zone ou de police."""
    if re.search(r"(?i)hors cadre|délégué|adjoint|de police|en mission|chargé d", poste.split(",")[0]):
        return None
    lieux = [l.strip() for l in re.findall(r"(?i)\bpréf(?:et|ète)\s+(?:de la |du |des |de l'|d'|de )([^,(]+)", poste)]
    lieux = [l for l in lieux if not re.match(r"(?i)(?:la )?(?:région|zone)\b", l)]
    return lieux[-1] if lieux else None


def prefets():
    t = nominations_simples("prefet")
    t["departement"] = t.poste.map(departement_du_poste)
    return t.dropna(subset=["departement"])


# ------------------------------------------------------------------------------------------------------------------
# Les élèves des instituts régionaux d'administration (listes de sortie : aptes à être titularisés)
# ------------------------------------------------------------------------------------------------------------------
# les formes des listes, selon les années :
#   « Mme Silberstein (Joëlle), nom d'usage X. »   « M. Boualem ABDALLAH. » (2015)
#   la civilité seule sur sa ligne, parfois « M l l e », puis « Allard (Marie-Christine). » (2003)
#   un tableau « Nom - Prénom » : « AGRARIO Caroline », puis le ministère et le lieu sur les lignes suivantes (2021-)
CIVILITE = r"(M\.?|Mme|Mlle|M l l e|M m e)"
ELEVE_PARENTHESES = re.compile(rf"^(?:{CIVILITE}\s+)?([^(]+?)\s*\(([^)]+)\)(?:,\s*nom d'usage\s+([^.]+?))?\s*\.?$")
ELEVE_SIMPLE = re.compile(rf"^{CIVILITE}\s+([^(]+?)\s*\.$")
ELEVE_TABLEAU = re.compile(r"^((?:(?:de|du|d'|le|la)\s+)?[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’ -]+)\s+([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ].*)$")


def ira():
    lignes = []
    t = textes("ecole")
    t = t[t.titre.str.contains(r"(?i)instituts? régiona\w+ d'administration") &
          t.titre.str.contains(r"(?i)aptes à être titularisés|titularisation") &
          ~t.titre.str.contains(r"(?i)modifiant|corps interministériel")]
    for r in t.itertuples():
        promo = re.search(r"promotions?\s+(\d{4})\s*-\s*(\d{4})", r.titre)
        seul = re.search(r"(?i)de l'institut régional d'administration (?:de |d')([A-ZÀ-Þ][\w-]+)", r.titre)
        institut, civ, tableau = (seul[1] if seul else None), None, False
        for ligne in r.contenu.splitlines():
            ligne = ligne.strip()
            entete = re.match(r"(?i)^Institut régional d'administration (?:de |d')(.+?)(?:\s*\(\d+ élèves?\))?\s*:?$", ligne)
            if entete:
                institut, civ = entete[1].strip(), None
                continue
            if re.search(r"(?i)nouvelle scolarité|redoubl|autorisés? à effectuer", ligne):
                institut = None          # (la suite : élèves qui recommencent, pas des diplômés)
                continue
            if re.match(r"(?i)^Nom\s*-\s*Prénom", ligne):
                tableau = True
                continue
            if re.fullmatch(CIVILITE, ligne):
                civ = ligne.replace(" ", "")
                continue
            m = ELEVE_PARENTHESES.match(ligne)
            if m and institut:
                nom, prenom, usage, c = m[2].strip(), m[3].strip(), m[4], m[1] or civ
            elif (m := ELEVE_SIMPLE.match(ligne)) and institut:
                (nom, prenom), usage, c = decouper_nom(m[2]), None, m[1]
            elif tableau and institut and (m := ELEVE_TABLEAU.match(ligne)):
                nom, prenom, usage, c = m[1].strip(), m[2].strip(), None, None
            else:
                continue
            civ = None
            lignes.append({"texte": r.texte, "date": date_du_texte(r), "institut": institut,
                           "entree": promo[1] if promo else None, "sortie": promo[2] if promo else date_du_texte(r)[:4],
                           "sexe": None if not c else "M" if c.replace(" ", "") in ("M", "M.") else "F",
                           "nom": nom, "prenom": prenom, "nom_usage": usage.strip() if usage else None})
    t = pd.DataFrame(lignes)
    # (un élève figure parfois deux fois — liste puis rectificatif : une ligne par élève, institut et année de sortie)
    return t.drop_duplicates(["institut", "sortie", "nom", "prenom"])


# ------------------------------------------------------------------------------------------------------------------
# Les grands corps
# ------------------------------------------------------------------------------------------------------------------
CORPS = [  # (motif dans le poste ou le titre, corps)
    (r"conseil constitutionnel", "Conseil constitutionnel"),
    (r"inspect\w+ (?:générale? )?des finances|inspection générale des finances", "Inspection générale des finances"),
    (r"cour des comptes|conseiller maître|conseiller référendaire|premier président de la cour", "Cour des comptes"),
    (r"conseil d'(?:é|e)tat|conseiller d'(?:é|e)tat|maître des requêtes", "Conseil d'État"),
]


def grands_corps():
    t = nominations_simples("grand_corps")
    t["corps"] = [next((c for motif, c in CORPS if re.search(motif, p, re.I)), None) or
                  next((c for motif, c in CORPS if re.search(motif, ti, re.I)), None) for p, ti in zip(t.poste, t.titre)]
    return t.dropna(subset=["corps"])


if __name__ == "__main__":
    for nom, f in [("gouvernement", gouvernement), ("prefets", prefets), ("ira", ira), ("grands_corps", grands_corps)]:
        t = f()
        t.to_parquet(ICI / f"jorf_{nom}.parquet", index=False)
        print(f"jorf_{nom}.parquet : {len(t)} lignes, {t.date.min() if 'date' in t else ''} → {t.date.max() if 'date' in t else ''}")
