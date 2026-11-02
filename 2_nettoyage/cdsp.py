"""
cdsp.py — Les scrutins d'avant 1999 que l'appli n'avait pas, d'après le CDSP (Centre de données socio-politiques de
Sciences Po, banque de données du ministère de l'Intérieur, data.gouv.fr — fichiers rangés par data/trier_par_election.py) :

    législatives, 2nd tour, 1958 → 1997      (par circonscription ; 1988-1997 : les candidats nommés)
    cantonales 1988, 1992, 1994, 1998         (1er et 2nd tour, par canton, voix par courant)
    régionales 1986, 1992 (par département), 1998 (par circonscription, listes nommées)

    py cdsp.py

Un « bureau » = la circonscription, le canton ou le département entier (code « 0000 », pas de commune) : ces scrutins se lisent
pour la France, une région ou un département. Même format que la méga base : cdsp_scrutins / _participation / _resultats.parquet.
La « nuance » est le code OFFICIEL du ministère (UDF, PRG, COM, UNR…) quand le fichier le donne — c'est lui qui fait foi ;
sinon (quelques courants sans code) une famille approchée. La couleur vient de gd/theme.py (NUANCES).
"""
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("cdsp")
TRI = C.COLLECTE / "tri_parquet"

# (élection, fichier, niveau, date du scrutin)
FICHIERS = [(f"{an}_legi_t2", f"cdsp-legi{an}t2-circ", "circonscription", d) for an, d in
            [(1958, "1958-11-30"), (1962, "1962-11-25"), (1967, "1967-03-12"), (1968, "1968-06-30"), (1973, "1973-03-11"),
             (1978, "1978-03-19"), (1981, "1981-06-21"), (1988, "1988-06-12"), (1993, "1993-03-28"), (1997, "1997-06-01")]]
FICHIERS += [(f"{an}_cant_t{t}", f"cdsp-cant{an}t{t}-canton-ag", "canton", d) for an, t, d in
             [(1988, 1, "1988-09-25"), (1988, 2, "1988-10-02"), (1992, 1, "1992-03-22"), (1992, 2, "1992-03-29"),
              (1994, 1, "1994-03-20"), (1994, 2, "1994-03-27"), (1998, 1, "1998-03-15"), (1998, 2, "1998-03-22")]]
FICHIERS += [("1986_regi_t1", "cdsp-regio1986-dep-ag", "departement", "1986-03-16"),
             ("1992_regi_t1", "cdsp-regio1992-dep-ag", "departement", "1992-03-22"),
             ("1998_regi_t1", "cdsp-regio1998-circ", "circonscription", "1998-03-15")]
NOMS = {"legi": "Législatives", "cant": "Cantonales", "regi": "Régionales"}

# une famille d'aujourd'hui pour chaque courant (mots du libellé ou code), dans l'ordre : la 1re règle qui marche gagne
FAMILLES = [
    ("extrême droite", r"front national|\bfn\b|extreme droite|poujad|\bexd\b|\bmnr\b|tixier|\bfrn\b"),
    ("extrême gauche", r"extreme gauche|\blo\b|\blcr\b|trotsk|\bpsu\b|\bpci\b|\bexg\b|lutte ouvriere"),
    ("communiste", r"communiste|\bpcf\b|\bcom\b"),
    ("écologiste", r"ecolo|\bverts?\b|\bvec\b|\beco\b|generation"),
    ("régionaliste", r"regionalist|\breg\b"),
    ("radicaux", r"radicaux socialistes|\bradsoc\b|radicaux de gauche|radicaux gauche|\bmrg\b|\brdg\b|mouvement des radicaux"),
    ("socialiste", r"socialiste|\bsfio\b|\bps\b|\bsoc\b|\bprg\b|fgds|gauche plurielle|majorite presidentielle|\bmaj\b|union de la gauche"),
    ("divers gauche", r"divers gauche|\bdvg\b"),
    ("divers droite", r"divers droite|\bdvd\b|moderes|\bmod\b|independants|\bcni\b"),
    ("gaullistes et droite", r"\brpr\b|\bunr\b|\budr\b|gaull|rassemblement pour la republique|droite unie|union de la droite|\bur\b|\bupf\b"),
    ("centre", r"\budf\b|\bmrp\b|centr|\bcds\b|democrat|\bufd\b|\brgr\b|\budsr\b|reformateur"),
]
PAS_UN_COURANT = r"^(code|departement|numero|circonscription|canton|commune|region|inscrits|votants|exprimes|blancs|nuls|taux|elu|abstention)"


def sans_accent(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def famille(texte):
    t = " " + re.sub(r"[^a-z0-9]+", " ", sans_accent(texte)) + " "
    return next((f for f, motif in FAMILLES if re.search(motif, t)), "divers")


def col(t, *motifs):
    """La première colonne dont le nom (sans accents) commence par l'un des motifs."""
    for c in t.columns:
        if any(re.match(m, sans_accent(c)) for m in motifs):
            return c
    return None


def code_dep(v):
    v = str(v).strip().removesuffix(".0")
    return v.zfill(2) if v.isdigit() else v.upper()


scrutins, participation, resultats = [], [], []
for ident, fichier, niveau, date in FICHIERS:
    f = TRI / ident / "resultats" / f"{fichier}.parquet"
    if not f.exists():
        print(f"  {ident} : {fichier} absent")
        continue
    t = pd.read_parquet(f)
    c_dep, c_ins, c_vot, c_exp = col(t, r"code dep", r"numero de dep"), col(t, r"inscrits"), col(t, r"votants"), col(t, r"exprimes")
    c_lieu = col(t, r"circonscription") if niveau == "circonscription" else col(t, r"code canton") if niveau == "canton" else None
    c_nom_dep = col(t, r"departement")
    t = t[t[c_dep].notna() & t[c_ins].notna()].copy()
    t["dep"] = t[c_dep].map(code_dep)
    lieu = t[c_lieu].astype(str).str.removesuffix(".0").str.zfill(3) if c_lieu else pd.Series("", index=t.index)
    lettre = {"circonscription": "C", "canton": "K", "departement": "D"}[niveau]
    t["id"] = f"{ident[:4]}{lettre}_" + t["dep"] + ("_" + lieu if c_lieu else "")
    an, typ, tour = ident.split("_")
    tour_n = int(tour[1])
    libelle = f"{NOMS[typ]} {an} – " + ("2nd tour" if tour_n == 2 else "1er tour" if typ != "regi" else "tour unique")
    scrutins.append((ident, typ, NOMS[typ], int(an), tour_n, pd.Timestamp(date), libelle))
    num = lambda c: pd.to_numeric(t[c], errors="coerce") if c else None
    p = pd.DataFrame({"scrutin": ident, "id_brut_miom": t["id"], "code_bv": "0000", "code_commune": None, "code_departement": t["dep"],
                      "libelle_commune": (t[c_nom_dep].astype(str) + (" – " + niveau + " " + lieu.str.lstrip("0") if c_lieu else "")),
                      "inscrits": num(c_ins), "votants": num(c_vot), "exprimes": num(c_exp)})
    p["abstentions"] = p["inscrits"] - p["votants"]
    p["nuls"] = (p["votants"] - p["exprimes"]).clip(lower=0)
    p["blancs"] = float("nan")
    participation.append(p)
    # les résultats : soit des blocs par candidat (« 1 Nom candidat », « 1 voix »… ou « Nom candidat 1 »…), soit une colonne par courant
    blocs = sorted({int(m.group(1) or m.group(2)) for c in t.columns for m in [re.match(r"^(\d+) voix$|^voix (\d+)$", sans_accent(c))] if m})
    lignes = []
    if blocs:
        for k in blocs:
            voix = col(t, rf"{k} voix$", rf"voix {k}$")
            nom, prenom = col(t, rf"{k} nom", rf"nom candidat {k}$"), col(t, rf"{k} prenom", rf"prenom candidat {k}$")
            nuance, liste = col(t, rf"{k} nuance", rf"nuance {k}$"), col(t, rf"{k} etiquette", rf"liste {k}$")
            for i, r in t.iterrows():
                v = pd.to_numeric(r[voix], errors="coerce")
                if not v or v != v:
                    continue
                qui = " ".join(str(r[c]).strip() for c in (prenom, nom) if c and str(r[c]).strip() not in ("", "None", "nan"))
                if not qui and liste:
                    qui = str(r[liste]).strip()
                nu = str(r[nuance]).strip() if nuance else ""
                # la nuance OFFICIELLE du ministère (UDF, PRG, FRN…) telle quelle ; une famille seulement si elle manque
                officielle = nu if nu not in ("", "None", "nan") else famille(r[liste] if liste else "")
                lignes.append((ident, r["id"], qui or nu or f"candidat {k}", officielle, v))
    else:
        for c in t.columns:
            if c in ("dep", "id") or re.match(PAS_UN_COURANT, sans_accent(c)):
                continue
            v = pd.to_numeric(t[c], errors="coerce")
            if v.notna().sum() == 0:
                continue
            code = re.search(r"\(([^)]+)\)\s*$", str(c))
            if code and code.group(1).strip() == "%":            # (une colonne de pourcentage, pas un courant)
                continue
            qui = re.sub(r"\s*\([^)]*\)\s*$", "", re.sub(r"^Listes? (du |des |de la |d')?", "", str(c))).strip()
            officielle = code.group(1).strip() if code else famille(c)     # le code officiel (« COM », « UNR ») s'il est donné
            for i, x in v.items():
                if x and x == x:
                    lignes.append((ident, t.at[i, "id"], qui, officielle, x))
    r = pd.DataFrame(lignes, columns=["scrutin", "id_brut_miom", "qui", "nuance", "voix"])
    resultats.append(r)
    print(f"  {ident:<14} {len(p):>5} {niveau}s · {r['qui'].nunique():>4} {'candidats' if blocs else 'courants'}", flush=True)

s = pd.DataFrame(scrutins, columns=["scrutin", "type", "type_libelle", "annee", "tour", "date", "libelle"])
p = pd.concat(participation, ignore_index=True)
for c in ["inscrits", "votants", "exprimes", "abstentions", "nuls"]:
    p[c] = p[c].round().astype("Int64")
r = pd.concat(resultats, ignore_index=True)
r["voix"] = r["voix"].round().astype("int64")
s.to_parquet(ICI / "cdsp_scrutins.parquet", index=False)
p.to_parquet(ICI / "cdsp_participation.parquet", index=False)
r.to_parquet(ICI / "cdsp_resultats.parquet", index=False)
print(f"\n{len(s)} scrutins · {len(p):,} lignes de participation · {len(r):,} résultats".replace(",", " "))
print("familles :", r.groupby("nuance")["voix"].sum().sort_values(ascending=False).head(12).to_dict())
