"""
trier_par_election.py — Range les fichiers de data/tri par élection, les convertit en parquet, les fusionne.

    py trier_par_election.py classer      → tri_manifeste.csv : chaque fichier, son élection, sa nature, doublon ou non (rien n'est écrit d'autre)
    py trier_par_election.py doublons     → les copies exactes partent dans data/tri_doublons (déplacées, pas effacées)
    py trier_par_election.py convertir    → data/tri_parquet/<élection>/… : un parquet par fichier (ou par feuille Excel), puis fusionnés
    py trier_par_election.py fusionner    → ajoute les nouvelles tables aux parquets existants (parquets/data/<nature>/<élection>.parquet) ;
                                             même forme : fusionnées (l'ancienne version sauvegardée dans PROJET/DECHET)

Dans data/tri, seuls les doublons exacts sont DÉPLACÉS (commande « doublons ») ; le reste est lu, et on écrit ailleurs.
Identifiant d'élection : comme dans parquets/data — « 2022_legi_t1 » (année, type sur 4 lettres, tour).
"""
import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

csv.field_size_limit(2**31 - 1)        # (les CSV « cartographiques » portent le tracé entier dans une cellule)
ICI = Path(__file__).resolve().parent
TRI = ICI / "tri"
SORTIE = ICI / "tri_parquet"
MANIFESTE = ICI / "tri_manifeste.csv"
EXISTANTS = ICI.parent / "parquets" / "data"
SAUVEGARDES = ICI.parent.parent / "DECHET" / "sauvegardes_parquets"      # (les versions d'avant une fusion)

TYPES = [  # (motif dans le nom du fichier, type)
    (r"presi|presidentielle|\bpr-|^pr\b|parrain|parraian", "pres"),
    (r"senat|^sen-", "sena"),
    (r"legi|legislative|^lg-|^leg[-_]|leg2022|leg24|candidatures-leg|rattachement-candidats-leg|nupes|publications-2022-lg", "legi"),
    (r"euro|eur-|eur24|eg2019|eg-2024", "euro"),
    (r"regio|regionale|^reg[-_]|^regresultats|^rg-|publication_regionales", "regi"),
    (r"cdsp_cant|cantonale", "cant"),
    (r"departementale|^dep-|^dp-|publications-2022-dp|conseillers-departementaux", "dpmt"),
    (r"municipale|^mun-|maires|conseils-d|metropolitaines|subcom|cirmp|candidats-\d\d-03-2020|"
     r"moins-1-000-h|moins-1000h|plus-1-000h|^corse\.xls|mairie-de|publications-2022-mp|CNCCFP", "muni"),
]
HORS_ELECTIONS = (r"^fr-en-|crous|referentiel-de-remuneration|glossaire|circulaire|dictionnaire|Tab_Inventaire|description-fichiers|"
                  r"^\d-tour-|tour-2-avec|syndicats|siret|^0ac69d4d|^45637703|communes_2020|codage-legis|votes\.json|Mesures fiscales|"
                  r"Prises de parole|CirconscriptionsModif|\.(shp|shx|dbf|prj|cpg|rels|bin|xml)$|^1-description")
PROFESSIONNELLES = r"^\d-tour-|tour-2-avec|syndicats|siret|^0ac69d4d|^45637703|description-fichiers"


def nature(nom):
    n = nom.lower()
    if re.search(r"parrain|parraian", n):
        return "parrainages"
    if re.search(r"^tp-|temps|analyse-(eur|leg)24", n):
        return "temps_de_parole"
    if re.search(r"publication|comptes|financement|depvoixdepense|etat_lab|departementale2021|cnccfp|municipales_partielles_2016", n):
        return "comptes_de_campagne"
    if "panneau" in n:
        return "panneaux"
    if re.search(r"elus|maires|conseillers-departementaux|pourvu", n):
        return "elus"
    if re.search(r"candidat|livre-des|listes|rattachement|nupes|plurinominal|sen-2023|senatoriales_2017|-ldb", n):
        return "candidats"
    if re.search(r"resultat|burvot|subcom|niveau|cdsp_|voix|pourcentages|votes|data|^\w+-\d{4}-t\d|leg-2022-t2-circo|t1_communes|1er_tour|ertour|2019|899afa|^826b4b4b|^4136646f|^c03225f8|^a0dea497", n):
        return "resultats"
    return "autre"


def niveau(nom):
    n = nom.lower()
    for motif, niv in ((r"burvot|bv-|bureau|_bv|-bv", "bureau"), (r"commp9000", "commune_9000"), (r"commp3500", "commune_3500"),
                       (r"_comm\b|_comm[ .(]|subcom|communes|t1_communes", "commune"), (r"canton|-can-|_can", "canton"),
                       (r"circ|circo|cirlg|cirmp", "circonscription"), (r"dep_|dpt|depart", "departement"), (r"-reg-|regions?\b", "region")):
        if re.search(motif, n):
            return niv
    return ""


# des fichiers reconnus à leur contenu (vérifié à la main : colonnes, nuances, noms de listes)
SPECIAUX = [
    (r"^c8d35f4e", "2021_regi_t1"),                                  # listes régionales (« HISSONS HAUT LA BRETAGNE », LR) : 2021
    (r"candidatures-leg-t2", "2022_legi_t2"),                        # nuances ENS, NUP : 2022
    (r"candidatures-legislatives-off-nupes|leg2022-nupes", "2022_legi_t1"),
    (r"^parrainagestotal", "2022_pres_t1"),                         # instantanés successifs des parrainages 2022
    (r"livre-des-listes-et-candidats-2020-t1", "2020_sena_t1"),     # « Scrutin proportionnel / majoritaire » par département
    (r"livre-des-listes-et-candidats-reg-t1", "2021_regi_t1"), (r"livre-des-listes-et-candidats-reg-t2", "2021_regi_t2"),
    (r"livre-des-candidats-et-suppleants-can-t2", "2021_dpmt_t2"), (r"livre-des-candidats-et-suppleants-t1-fe-2021", "2021_dpmt_t1"),
    (r"livre-des-candidats-et-remplacants-cirlg-t1", "2022_legi_t1"),
    (r"^reg_15_.*t2|^reg_15_resultats_t2", "2015_regi_t2"), (r"^reg_15_", "2015_regi_t1"),
    (r"resultats-par-niveau-(burvot|cirmp)-t1-dpt-69-2020", "2020_muni_t1"), (r"resultats-par-niveau-(burvot|cirmp)(-t2)?-2020-06-29", "2020_muni_t2"),
    (r"resultats-par-niveau-reg-t1-france-entiere-2021", "2021_regi_t1"),
    (r"^conseillers-departementaux", "2021_dpmt_t2"),
    (r"fichierdepvoixdepense", "2015_dpmt_t1"),                     # binômes BC-UD et leurs dépenses : 2015
    (r"publication_comptes_2015", "2015_dpmt_t1"), (r"publication_lg_2017", "2017_legi_t1"),
    (r"publications-2022-lp", "2022_legi_t1"), (r"publications-2022-dp", "2021_dpmt_t1"),
    (r"^20180920-senatoriales-2017", "2017_sena_t1"),
    (r"analyse-eur24", "2024_euro_t1"), (r"analyse-leg24", "2024_legi_t1"),
    (r"elections-pr-1er-tour-2022", "2022_pres_t1"),
    # législatives, 1re circonscription des Français de l'étranger (Canada, États-Unis) : 2012 et la partielle de 2013
    (r"^826b4b4b", "2012_legi_t1"), (r"^4136646f", "2012_legi_t2"),       # 13 candidats ; puis LEFEBVRE / NARASSIGUIN
    (r"^c03225f8", "2013_legi_t1"), (r"^a0dea497", "2013_legi_t2"),       # GISCARD D'ESTAING, SCEMAMA… ; puis SCEMAMA / LEFEBVRE
    (r"^publication-comptes-2012", "2012_legi_t1"),
    (r"^ile-de-france-2eme-partie-91-95-listes-detaillees", "2014_muni_t1"),  # (« 2eme partie », pas « 2e tour »)                       # comptes de campagne, circonscriptions « Ain - 1re »
    (r"publication-comptes-2017-2019|publications-2022-territoriales|legislatives-emplacement-panneaux", "autres"),
]


def election(chemin, nom):
    """L'identifiant d'élection d'un fichier, d'après son nom ET celui de son dossier (« candidats-02-03-2020.csv/candidats.csv »)."""
    for motif, ident in SPECIAUX:
        if re.search(motif, nom.lower()):
            return ident
    if re.search(HORS_ELECTIONS, nom):
        return "elections_professionnelles" if re.search(PROFESSIONNELLES, nom) else "hors_elections"
    dossier = chemin.parent.name.lower() if chemin.parent != TRI else ""
    # « pr-uniquement » / « sans-pr » (temps de parole) : ce « pr » n'est pas « présidentielle »
    n = re.sub(r"(sans-)?pr-uniquement|sans-pr", "", nom.lower())
    typ = next((t for motif, t in TYPES if re.search(motif, n) or (dossier and re.search(motif, dossier))), None)
    an = re.search(r"(19[4-9]\d|20[0-2]\d)", re.sub(r"^\d{8}-", "", nom)) or re.search(r"(19[4-9]\d|20[0-2]\d)", dossier)
    an = an.group(1) if an else None
    # les années écrites sur 2 chiffres (« eur24 », « Reg_15 »…)
    if not an:
        m = re.search(r"(?:eur|leg|reg|rg|lg|dp|euro|sen)[-_]?(\d\d)(?!\d)", n)
        an = ("20" + m.group(1)) if m else None
    # les fichiers sans année, reconnus à leur contenu (voir le README de la commande « classer »)
    if not an:
        if typ == "muni" and re.search(r"moins-1-000-h|moins-1000h|plus-1-000h|corse\.xls", n):
            an = "2014"
        elif re.search(r"^resultats-par-niveau-(burvot|subcom|can|dpt)-t1-france-entiere", n):
            typ, an = "dpmt", "2021"
        elif re.search(r"livre-des-(listes-et-candidats|candidats-scrutin-plurinominal)", n):
            typ, an = "muni", "2020"
        elif n.startswith("899afa4a"):
            typ, an = "regi", "2010"
        elif n.startswith("calcul-financement-public"):
            typ, an = "legi", "2017"
        elif n.startswith("emplacement_panneaux"):
            typ, an = "muni", "2026"
    if typ == "muni" and an == "2021":
        typ = "regi" if "reg" in n else "dpmt"
    # 2nd tour : « t2 », « 2t », « tour-2 », « second »… mais pas le « t2 » de « can-t2-001 » ni de « cant2001 »
    tour = "t2" if re.search(r"(?:^|[^a-z])t2(?:[^0-9]|$)|\d{4}t2|(?:^|[^0-9a-z])2t(?:[^a-z]|$)|tour-?2|second|2eme|2nd", n) else "t1"
    if typ == "euro" or (typ == "sena" and not re.search(r"-t2-", n)) or (typ == "regi" and an in ("1986", "1992", "1998")) or (typ == "legi" and an == "1986"):
        tour = "t1"
    if not typ or not an:
        return "a_classer"
    return f"{an}_{typ}_{tour}"


def empreinte(f):
    h = hashlib.md5()
    with open(f, "rb") as x:
        for bloc in iter(lambda: x.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def classer():
    """Le manifeste : chaque fichier, son élection, sa nature, son niveau, s'il est un doublon exact, s'il sera converti."""
    lignes = []
    # (les noms « propres » d'abord : en cas de doublon, on garde « fichier.csv » plutôt que « fichier (3).csv »)
    fichiers = sorted((f for f in TRI.rglob("*") if f.is_file()), key=lambda f: (bool(re.search(r" \(\d+\)", f.name)), str(f)))
    vus = {}
    for f in fichiers:
        rel = f.relative_to(TRI)
        h = empreinte(f)
        doublon = vus.get(h)
        vus.setdefault(h, str(rel))
        lignes.append({"fichier": str(rel), "ext": f.suffix.lower(), "octets": f.stat().st_size, "election": election(f, f.name),
                       "nature": nature(f.name), "niveau": niveau(f.name), "doublon_de": doublon or ""})
    t = pd.DataFrame(lignes).sort_values("fichier")
    # les paires .txt / .xlsx (ou .csv / .xls…) du même nom : on garde le texte (même contenu, plus rapide à lire)
    t["base"] = t["fichier"].str.replace(r"( \(\d+\))?\.[^.]+$", "", regex=True)
    a_convertir = t["ext"].isin([".csv", ".txt", ".xls", ".xlsx", ".ods", ".json", ".parquet"]) & (t["doublon_de"] == "")
    a_convertir &= ~t["fichier"].str.contains(r"^(?:CANTONALES|LEGISLATIVES|PRESIDENTIELLES|REGIONALES)_\d{4}-\d{4}-xls", regex=True)  # (= les csv)
    a_convertir &= ~t["fichier"].str.contains(r"cdsp_\w+\.txt$", regex=True)       # (les notices du CDSP : texte, gardées telles quelles)
    a_convertir &= ~t["election"].isin(["hors_elections", "a_classer"])
    textes = set(t.loc[a_convertir & t["ext"].isin([".txt", ".csv"]), "base"])
    a_convertir &= ~(t["ext"].isin([".xls", ".xlsx", ".json", ".geojson"]) & t["base"].isin(textes))
    t["convertir"] = a_convertir
    t.drop(columns="base").to_csv(MANIFESTE, index=False, encoding="utf-8-sig")
    print(f"{len(t)} fichiers · {(t['doublon_de'] != '').sum()} doublons exacts · {t['convertir'].sum()} à convertir")
    print(t[t["convertir"]].groupby("election").size().sort_index().to_string())


def ranger_doublons():
    """Les copies EXACTES (même contenu, octet pour octet) partent dans data/tri_doublons (même arborescence) : rien n'est effacé."""
    t = pd.read_csv(MANIFESTE)
    d = t[t["doublon_de"].notna() & (t["doublon_de"] != "")]
    poids = 0
    for rel in d["fichier"]:
        src, dst = TRI / rel, ICI / "tri_doublons" / rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            poids += src.stat().st_size
            src.replace(dst)
    print(f"{len(d)} doublons déplacés dans data/tri_doublons ({poids / 1e6:.0f} Mo)")


# --- la lecture des fichiers ----------------------------------------------------------------------------------------------

def _texte(f):
    brut = f.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return brut.decode(enc)
        except UnicodeDecodeError:
            continue
    return brut.decode("latin-1")


def _noms_uniques(noms):
    vus, sortie = {}, []
    for n in noms:
        n = re.sub(r"\s+", " ", str(n)).strip() or "colonne"
        if n in vus:
            vus[n] += 1
            n = f"{n}_{vus[n]}"
        else:
            vus[n] = 1
        sortie.append(n)
    return sortie


def _etendre_entete(entete, largeur):
    """Les fichiers « par niveau » du ministère : chaque candidat ajoute un bloc de colonnes sans titre au bout de la ligne.
    On nomme ces blocs comme le premier (N°Panneau_2, Nuance_2, Voix_2…) au lieu de les perdre."""
    entete = list(entete)
    if largeur <= len(entete):
        return entete
    debut = next((i for i, c in enumerate(entete) if re.search(r"panneau|n° ?d[ée]p[oô]t|^sexe", str(c), re.I)), None)
    bloc = entete[debut:] if debut is not None else ["colonne"]
    k = 2
    while len(entete) < largeur:
        entete += [f"{c}_{k}" for c in bloc]
        k += 1
    return entete[:largeur]


def lire_texte(f):
    """CSV ou TXT : encodage, séparateur et ligne d'en-tête devinés ; lignes de longueurs inégales acceptées."""
    lignes = [l for l in _texte(f).splitlines() if l.strip(" ;,\t\"")]
    if not lignes:
        return pd.DataFrame()
    tete = lignes[0]
    sep = max([";", "\t", ","], key=lambda c: tete.count(c))
    rangees = list(csv.reader(lignes, delimiter=sep))
    largeur = max(len(r) for r in rangees)
    entete = _etendre_entete(rangees[0], largeur)
    corps = [r + [""] * (largeur - len(r)) for r in rangees[1:]]
    # les fichiers du CDSP ont DEUX lignes d'en-tête : les libellés, puis les codes (« Parti communiste » / « COM ») ;
    # la 2e ligne est reconnue à ce qu'elle porte du texte court là où les lignes suivantes portent des nombres
    if len(corps) > 3:
        nombre = lambda v: bool(re.fullmatch(r"-?\d+([.,]\d+)?", v.strip()))
        r1, r2 = corps[0], corps[1]
        cols = [i for i in range(largeur) if r2[i].strip()]
        codes = [i for i in cols if r1[i].strip() and not nombre(r1[i]) and nombre(r2[i]) and len(r1[i].strip()) <= 12]
        if cols and len(codes) >= 0.4 * len(cols):
            entete = [f"{e} ({r1[i].strip()})" if i in codes and r1[i].strip() and r1[i].strip() != e else e for i, e in enumerate(entete)]
            corps = corps[1:]
    entete = _noms_uniques(entete)
    return pd.DataFrame(corps, columns=entete)


def lire_feuille(t):
    """Une feuille Excel lue sans en-tête : la ligne d'en-tête = la première ligne bien remplie (les titres au-dessus sont sautés)."""
    t = t.dropna(how="all").dropna(axis=1, how="all")
    if t.empty:
        return t
    remplis = t.notna().sum(axis=1)
    seuil = 0.6 * remplis.head(40).max()
    i = remplis[remplis >= seuil].index[0]
    entete = [str(v) if v == v else "" for v in t.loc[i]]
    corps = t.loc[t.index > i]
    entete = _noms_uniques(_etendre_entete([e for e in entete], corps.shape[1]) if all(e == "" for e in entete[len(entete):]) else entete)
    corps.columns = entete[:corps.shape[1]]
    return corps.astype(str).replace({"nan": "", "NaT": "", "None": ""})


def lire(f):
    """Un fichier → [(suffixe, tableau)] (une entrée par feuille Excel)."""
    ext = f.suffix.lower()
    if ext in (".csv", ".txt"):
        return [("", lire_texte(f))]
    if ext in (".xls", ".xlsx", ".ods"):
        x = pd.ExcelFile(f)
        return [(("" if len(x.sheet_names) == 1 else _slug(feuille)), lire_feuille(x.parse(feuille, header=None, dtype=object)))
                for feuille in x.sheet_names]
    if ext == ".json":
        d = json.loads(_texte(f))
        if isinstance(d, dict):
            d = next((v for v in d.values() if isinstance(v, list)), [d])
        return [("", pd.json_normalize(d))] if isinstance(d, list) else []
    if ext == ".parquet":
        return [("", pd.read_parquet(f))]
    return []


def typer(t):
    """Les colonnes toutes numériques deviennent des nombres (« 66,74 » compris) ; les codes (« 01 », « 2A », « 0012 ») restent du texte."""
    t = t.copy()
    for c in t.columns:
        s = t[c]
        if s.dtype != object:
            continue
        v = s.astype(str).str.strip()
        plein = v[v != ""]
        if plein.empty:
            continue
        if plein.str.fullmatch(r"-?\d+([.,]\d+)?").all() and not plein.str.match(r"0\d").any():
            t[c] = pd.to_numeric(v.str.replace(",", ".", regex=False).replace("", None), errors="coerce")
        else:
            t[c] = v.replace("", None)
    return t


def _slug(x):
    x = unicodedata.normalize("NFD", str(x))
    x = "".join(ch for ch in x if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "-", x).strip("-").lower()[:70]


def convertir():
    """Chaque fichier retenu → data/tri_parquet/<élection>/<nature>/<nom>.parquet ; puis la fusion par élection et par nature."""
    t = pd.read_csv(MANIFESTE)
    t = t[t["convertir"]]
    journal = []
    for _, r in t.iterrows():
        f = TRI / r["fichier"]
        if not f.exists():
            continue
        try:
            morceaux = lire(f)
        except Exception as e:
            journal.append((r["fichier"], r["election"], r["nature"], "", 0, 0, f"ERREUR {type(e).__name__}: {e}"[:200]))
            continue
        for suffixe, tab in morceaux:
            if tab is None or tab.empty or tab.shape[1] < 2:
                continue
            nom = _slug(Path(r["fichier"]).stem.replace(" (", "-")) + (f"__{suffixe}" if suffixe else "")
            if f.suffix.lower() in (".xls", ".xlsx", ".ods"):         # Excel → d'abord un CSV (lisible partout), puis le parquet
                csv_ = ICI / "tri_csv" / r["election"] / r["nature"] / f"{nom}.csv"
                csv_.parent.mkdir(parents=True, exist_ok=True)
                tab.to_csv(csv_, sep=";", index=False, encoding="utf-8-sig")
                tab = lire_texte(csv_)
            tab = typer(tab)
            tab.columns = [str(c) for c in tab.columns]
            nom = _slug(Path(r["fichier"]).stem.replace(" (", "-")) + (f"__{suffixe}" if suffixe else "")
            dest = SORTIE / r["election"] / r["nature"] / f"{nom}.parquet"
            dest.parent.mkdir(parents=True, exist_ok=True)
            tab.to_parquet(dest, index=False)
            journal.append((r["fichier"], r["election"], r["nature"], str(dest.relative_to(SORTIE)), len(tab), tab.shape[1], ""))
        print(f"  {r['fichier'][:90]}", flush=True)
    j = pd.DataFrame(journal, columns=["source", "election", "nature", "parquet", "lignes", "colonnes", "erreur"])
    j.to_csv(SORTIE / "journal_conversion.csv", index=False, encoding="utf-8-sig")
    print(f"{(j['erreur'] == '').sum()} parquets écrits · {(j['erreur'] != '').sum()} erreurs (journal_conversion.csv)")
    fusionner_par_election()


def fusionner_par_election():
    """Dans chaque élection et chaque nature : les tableaux qui ont LES MÊMES colonnes sont mis bout à bout (colonne « source »)
    et dédoublonnés → <élection>/<nature>__fusion.parquet (un fichier par forme de tableau)."""
    resume = []
    for dossier in sorted(p for p in SORTIE.glob("*/*") if p.is_dir()):
        groupes = {}
        for f in sorted(dossier.glob("*.parquet")):
            t = pd.read_parquet(f)
            groupes.setdefault(tuple(t.columns), []).append((f.stem, t))
        for k, (colonnes, tabs) in enumerate(sorted(groupes.items(), key=lambda g: -sum(len(x) for _, x in g[1]))):
            if len(tabs) < 2:
                continue
            # (une même colonne peut être un nombre ici et du texte là — « 2A » : tout en texte, puis on retype l'ensemble)
            en_texte = [x.astype(str).replace({"nan": "", "None": "", "<NA>": ""}).assign(source=nom) for nom, x in tabs]
            tout = pd.concat(en_texte, ignore_index=True)
            avant = len(tout)
            tout = typer(tout.drop_duplicates(subset=list(colonnes)))
            nom = f"{dossier.name}__fusion" + (f"_{k + 1}" if k else "")
            tout.to_parquet(dossier.parent / f"{nom}.parquet", index=False)
            resume.append((dossier.parent.name, dossier.name, len(tabs), avant, len(tout), f"{nom}.parquet"))
    r = pd.DataFrame(resume, columns=["election", "nature", "fichiers", "lignes_avant", "lignes_apres_doublons", "fusion"])
    r.to_csv(SORTIE / "journal_fusion.csv", index=False, encoding="utf-8-sig")
    print(f"{len(r)} fusions par élection (journal_fusion.csv)")


# --- l'ajout aux parquets existants (parquets/data) -------------------------------------------------------------------------

CATEGORIES = {"candidats": "candidats_details", "elus": "elus", "parrainages": "parrainages", "temps_de_parole": "temps_de_parole",
              "comptes_de_campagne": "comptes_de_campagne", "panneaux": "panneaux"}


def fusionner_existants():
    """Chaque nouvelle table rejoint la collection parquets/data, au format « <nature>/<élection>.parquet » :
    - les résultats anciens ou à d'autres niveaux → resultats_<niveau>/<élection>.parquet (circonscription, commune, canton…) ;
    - les fiches de candidats (profession, date de naissance…) → candidats_details/<élection>.parquet ; etc.
    Un fichier qui existe déjà est FUSIONNÉ quand il a les mêmes colonnes (ses lignes + les nouvelles, sans doublons ; l'ancienne
    version est d'abord copiée dans PROJET/DECHET/sauvegardes_parquets/) ; sinon la nouvelle table est rangée à côté, sous son nom."""
    m = pd.read_csv(MANIFESTE)
    niveaux = dict(zip(m["fichier"].map(lambda x: _slug(Path(x).stem.replace(" (", "-"))), m["niveau"].fillna("")))
    journal = []
    for el in sorted(p for p in SORTIE.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}_\w{4}_t\d", p.name)):
        for nat in sorted(p for p in el.iterdir() if p.is_dir()):
            # les fusions (chacune réunit les fichiers d'une même forme), plus les fichiers qu'aucune fusion ne contient
            fusions = sorted(el.glob(f"{nat.name}__fusion*.parquet"))
            formes = {tuple(c for c in pd.read_parquet(f).columns if c != "source") for f in fusions}
            seuls = [f for f in sorted(nat.glob("*.parquet")) if tuple(pd.read_parquet(f).columns) not in formes]
            fichiers = [(f.stem, f) for f in fusions + seuls]
            for k, (nom, f) in enumerate(fichiers):
                if nat.name == "resultats":
                    niv = niveaux.get(nom.split("__")[0], "") or "autre"
                    categorie = f"resultats_{niv}"
                else:
                    categorie = CATEGORIES.get(nat.name, nat.name)
                dest = EXISTANTS / categorie / (f"{el.name}.parquet" if k == 0 else f"{el.name}__{nom}.parquet")
                t = pd.read_parquet(f)
                t.insert(0, "id_election", el.name)
                if dest.exists():
                    ancien = pd.read_parquet(dest)
                    if list(ancien.columns) != list(t.columns):
                        dest = EXISTANTS / categorie / f"{el.name}__{nom}.parquet"       # (autre forme : rangée à côté)
                if dest.exists():
                    ancien = pd.read_parquet(dest)
                    if list(ancien.columns) != list(t.columns):
                        journal.append((el.name, categorie, str(f.relative_to(SORTIE)), "déjà là, autres colonnes : gardé tel quel"))
                        continue
                    # seulement les lignes qu'il n'a pas encore (l'ancien fichier garde TOUTES ses lignes, même répétées)
                    en_texte = lambda x: x.astype(str).replace({"nan": "", "None": "", "<NA>": ""})
                    a_, n_ = en_texte(ancien), en_texte(t)
                    cles = [c for c in a_.columns if c != "source"]
                    connues = set(map(tuple, a_[cles].itertuples(index=False)))
                    nouvelles = n_[[tuple(x) not in connues for x in n_[cles].itertuples(index=False)]].drop_duplicates(subset=cles)
                    if nouvelles.empty:
                        journal.append((el.name, categorie, str(f.relative_to(SORTIE)), "déjà là : rien de nouveau"))
                        continue
                    tout = pd.concat([a_, nouvelles], ignore_index=True)
                    sauvegarde = SAUVEGARDES / dest.relative_to(EXISTANTS)
                    sauvegarde.parent.mkdir(parents=True, exist_ok=True)
                    if not sauvegarde.exists():
                        dest.replace(sauvegarde)
                    typer(tout).to_parquet(dest, index=False)
                    journal.append((el.name, categorie, str(f.relative_to(SORTIE)), f"fusionné (+{len(tout) - len(ancien)} lignes)"))
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                t.to_parquet(dest, index=False)
                journal.append((el.name, categorie, str(f.relative_to(SORTIE)), "ajouté"))
    j = pd.DataFrame(journal, columns=["election", "categorie", "depuis", "etat"])
    j.to_csv(SORTIE / "journal_ajout_existants.csv", index=False, encoding="utf-8-sig")
    print(j.groupby(["categorie", "etat"]).size().to_string())


if __name__ == "__main__":
    {"classer": classer, "doublons": ranger_doublons, "convertir": convertir, "fusionner": fusionner_existants}[sys.argv[1]]()
