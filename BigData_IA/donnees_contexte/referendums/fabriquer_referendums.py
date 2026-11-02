"""
fabriquer_referendums.py — Les 3 référendums (1992, 2000, 2005) au format de la méga base, en Parquet.

    py fabriquer_referendums.py

Sources (ministère de l'Intérieur, data.gouv.fr), dans brut/ :
    RF92_communes.xls   Maastricht, 20 septembre 1992 — par COMMUNE (pas de détail par bureau publié)
    RF00_Bvot.txt       Quinquennat, 24 septembre 2000 — par bureau de vote
    RF05_BVot.txt       Constitution européenne, 29 mai 2005 — par bureau de vote

Sorties (lues par le_grand_depouillement/preparer_donnees.py) :
    referendums_scrutins.parquet       une ligne par référendum
    referendums_participation.parquet  une ligne par bureau (1992 : une par commune, bureau « 0000 »)
    referendums_resultats.parquet      une ligne par bureau et par réponse (OUI / NON), comme des « candidats »

Les fichiers ne distinguent pas blancs et nuls : tout est rangé dans « nuls » (blancs = vide).
Les collectivités d'outre-mer et les Français de l'étranger (« Ensemble du département ZM… ») sont laissés de côté.
"""
from pathlib import Path

import pandas as pd
import xlrd

ICI = Path(__file__).resolve().parent
BRUT = ICI / "brut"
DOM = {"ZA": "971", "ZB": "972", "ZC": "973", "ZD": "974"}       # codes du ministère → départements INSEE

SCRUTINS = pd.DataFrame([
    ("1992_refe_t1", "refe", "Référendum", 1992, 1, "1992-09-20", "Référendum 1992 – Maastricht"),
    ("2000_refe_t1", "refe", "Référendum", 2000, 1, "2000-09-24", "Référendum 2000 – Quinquennat"),
    ("2005_refe_t1", "refe", "Référendum", 2005, 1, "2005-05-29", "Référendum 2005 – Constitution européenne"),
], columns=["scrutin", "type", "type_libelle", "annee", "tour", "date", "libelle"])
SCRUTINS["date"] = pd.to_datetime(SCRUTINS["date"])


def departement(code):
    code = str(code).strip()
    if code.endswith(".0"):
        code = code[:-2]
    return DOM.get(code, code.zfill(2) if code.isdigit() else code)


def commune(dep, com):
    """Le code INSEE de la commune : département + numéro (les DOM : 971 + 01 → 97101)."""
    com = str(com).strip()
    if com.endswith(".0"):
        com = com[:-2]
    if len(dep) == 3:                       # DOM : le numéro du ministère contient déjà le chiffre du département
        return "97" + com.zfill(3)
    return dep + com.zfill(3)


def lire_txt(fichier, colonnes):
    lignes = [l.rstrip("\n").split(";") for l in open(fichier, encoding="latin-1") if not l.startswith("--") and l.strip()]
    i = colonnes.index("bv")
    # Caen écrit ses bureaux « 01.1 » ; en 2005 le point est devenu « ; » → une colonne de trop : on recolle
    lignes = [l[:i] + [l[i] + "." + l[i + 1]] + l[i + 2:] if len(l) == len(colonnes) + 1 else l for l in lignes]
    df =pd.DataFrame([[x.strip() for x in l] for l in lignes]).iloc[:, :len(colonnes)]
    df.columns = colonnes
    return df


def par_bureau(scrutin, df):
    df = df[~df["dep"].str.match(r"^Z[^A-D]")].copy()            # sans COM ni étranger
    df["code_departement"] = df["dep"].map(departement)
    df["code_commune"] = [commune(d, c) for d, c in zip(df["code_departement"], df["com"])]
    df["code_bv"] = [b.zfill(4) if b.isdigit() else b for b in df["bv"]]     # « 0001 », mais « 01.1 » à Caen (comme la méga base)
    df["id_brut_miom"] = df["code_commune"] + "_" + df["code_bv"]
    for c in ["inscrits", "votants", "abstentions", "exprimes", "voix"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int64")
    df["scrutin"] = scrutin
    p = df.drop_duplicates("id_brut_miom")[["scrutin", "id_brut_miom", "code_bv", "code_commune", "nom", "code_departement",
                                            "inscrits", "abstentions", "votants", "exprimes"]].rename(columns={"nom": "libelle_commune"})
    r = df[["scrutin", "id_brut_miom", "reponse", "voix"]].rename(columns={"reponse": "qui"})
    return p, r


def lire_1992():
    feuille = xlrd.open_workbook(BRUT / "RF92_communes.xls").sheet_by_index(0)
    p, r = [], []
    for i in range(1, feuille.nrows):
        v = feuille.row_values(i)
        dep = departement(v[0])
        com = commune(dep, v[2])
        ident = com + "_0000"
        ins, abst, vot, bn, expr = (int(x or 0) for x in (v[4], v[5], v[7], v[9], v[12]))
        p.append(("1992_refe_t1", ident, "0000", com, str(v[3]).title(), dep, ins, abst, vot, expr, bn))
        r.append(("1992_refe_t1", ident, str(v[15]).strip(), int(v[16] or 0)))
        r.append(("1992_refe_t1", ident, str(v[19]).strip(), int(v[20] or 0)))
    p = pd.DataFrame(p, columns=["scrutin", "id_brut_miom", "code_bv", "code_commune", "libelle_commune", "code_departement",
                                 "inscrits", "abstentions", "votants", "exprimes", "nuls"])
    return p, pd.DataFrame(r, columns=["scrutin", "id_brut_miom", "qui", "voix"])


p92, r92 = lire_1992()
p00, r00 = par_bureau("2000_refe_t1", lire_txt(BRUT / "RF00_Bvot.txt",
                      ["tour", "dep", "com", "nom", "bv", "inscrits", "votants", "abstentions", "exprimes", "reponse", "voix"]))
p05, r05 = par_bureau("2005_refe_t1", lire_txt(BRUT / "RF05_BVot.txt",
                      ["tour", "reg", "dep", "arr", "circo", "canton", "com", "ins_ref", "nom", "bv", "inscrits", "votants",
                       "abstentions", "exprimes", "reponse", "voix"]))
participation = pd.concat([p92, p00, p05], ignore_index=True)
participation["nuls"] = participation["nuls"].fillna(participation["votants"] - participation["exprimes"]).astype("int64")
participation["blancs"] = float("nan")          # pas distingués des nuls dans ces fichiers
resultats = pd.concat([r92, r00, r05], ignore_index=True)
resultats["nuance"] = resultats["qui"]          # OUI / NON : leur propre « nuance »

SCRUTINS.to_parquet(ICI / "referendums_scrutins.parquet", index=False)
participation.to_parquet(ICI / "referendums_participation.parquet", index=False)
resultats.to_parquet(ICI / "referendums_resultats.parquet", index=False)

for s in SCRUTINS["scrutin"]:
    p = participation[participation["scrutin"] == s]
    r = resultats[resultats["scrutin"] == s].groupby("qui")["voix"].sum()
    print(f"{s} : {len(p):>6} bureaux · inscrits {p['inscrits'].sum():>11,} · abstention {100 * p['abstentions'].sum() / p['inscrits'].sum():.2f} % · "
          + " · ".join(f"{q} {100 * v / r.sum():.2f} %" for q, v in r.items()))
