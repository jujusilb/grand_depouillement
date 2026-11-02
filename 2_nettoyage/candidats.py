"""
candidats.py — Qui sont les candidats ? Âge, profession, sexe, sortant… une seule table pour toutes les élections.

    py candidats.py

Source : parquets/data/candidats_details/*.parquet (fichiers du ministère de l'Intérieur, rangés par data/trier_par_election.py).
Leurs colonnes changent d'une élection à l'autre (« Nom du candidat », « Nom candidat », « NomPsn »…) : on les ramène à
scrutin, departement, lieu, nom, prenom, sexe, naissance, age (le jour du vote), profession, nuance, sortant.
Les lignes sans date de naissance NI profession ne sont pas gardées (elles n'apprennent rien de plus que les résultats).
Sortie : candidats_details.parquet
"""
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("candidats")
SOURCE = C.RESULTATS / "candidats_details"
DATES = {"pres": "-04-20", "legi": "-06-10", "euro": "-05-26", "muni": "-03-15", "regi": "-03-20", "dpmt": "-03-20", "cant": "-03-20", "sena": "-09-25"}

CHAMPS = {  # champ : motifs du nom de colonne (sans accents, en minuscules), le premier trouvé gagne
    "nom": [r"^nom (du )?candidat$", r"^nom candidat", r"^nom sur le bulletin", r"^nompsn$", r"^nom$"],
    "prenom": [r"^prenom (du )?candidat$", r"^prenom candidat", r"^prenom sur le bulletin", r"^prepsn$", r"^prenom$"],
    "sexe": [r"^sexe (du )?candidat", r"^sexe$", r"^civilitepsn$", r"^civilite$"],
    "naissance": [r"^date (de )?naissance (du )?candidat", r"^date de naissance$", r"^date naissance$", r"naissance candidat"],
    "profession": [r"^profession( du)?( candidat)?$", r"libelle profession", r"^profession"],
    "nuance": [r"^code nuance$", r"^nuance (du )?candidat$", r"^nuance$", r"^code nuance (du )?candidat", r"^nuance liste$", r"^codnualiste$",
               r"^nuance de liste$"],
    "departement": [r"^code (du )?departement$", r"^code departement$"],
    "lieu": [r"^libelle (de la )?circonscription", r"^libelle (du )?canton", r"^libelle (de la )?commune$", r"^libsubcom$",
             r"^libelle section", r"^libelle commune$"],
    "sortant": [r"^sortant$"],
}


def sans_accent(t):
    t = unicodedata.normalize("NFD", str(t).lower().strip())
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn"))


def trouver(colonnes, motifs):
    propres = {sans_accent(c): c for c in colonnes}
    for m in motifs:
        for p, c in propres.items():
            if re.search(m, p):
                return c
    return None


def date(v):
    v = str(v).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return pd.to_datetime(v, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


morceaux = []
for f in sorted(SOURCE.glob("*.parquet")):
    t = pd.read_parquet(f)
    scrutin = str(t["id_election"].iloc[0]) if "id_election" in t else f.stem[:12]
    # un titre lu comme en-tête (colonnes « colonne_2 »…) : la vraie ligne d'en-tête est la première ligne du tableau
    if sum(str(c).startswith("colonne") for c in t.columns) > len(t.columns) / 2:
        entete = [str(v) for v in t.iloc[0]]
        t = t.iloc[1:].copy()
        t.columns = ["id_election"] + entete[1:] if "id_election" in t.columns[:1] else entete
    cols = {k: trouver(t.columns, m) for k, m in CHAMPS.items()}
    if not cols["nom"] or not (cols["naissance"] or cols["profession"]):
        print(f"  {f.name[:70]:<70} : ni date de naissance ni profession, laissé de côté")
        continue
    x = pd.DataFrame({k: (t[c].astype(str).str.strip().replace({"None": None, "nan": None, "": None}) if c else None) for k, c in cols.items()})
    x = x[x["nom"].notna() & (x["naissance"].notna() | x["profession"].notna())]
    x["sexe"] = x["sexe"].replace({"M.": "M", "Mme": "F", "MME": "F", "Mlle": "F"})
    x["departement"] = x["departement"].map(lambda v: v.zfill(2) if v and v.isdigit() and len(v) < 3 else v)
    x["naissance"] = x["naissance"].map(date)
    x["profession"] = x["profession"].str.replace(r"^\(\d+\)\s*-\s*", "", regex=True)       # « (34) - Professeur » → « Professeur »
    an, typ = int(scrutin[:4]), scrutin[5:9]
    jour = pd.Timestamp(f"{an}{DATES.get(typ, '-06-01')}")
    x["age"] = ((jour - x["naissance"]).dt.days / 365.25).round().astype("Int64")
    x.loc[(x["age"] < 18) | (x["age"] > 105), "age"] = pd.NA
    x["scrutin"], x["source"] = scrutin, f.stem
    morceaux.append(x)
    print(f"  {f.name[:70]:<70} : {len(x):>7} candidats", flush=True)

t = pd.concat(morceaux, ignore_index=True)
# le même candidat lu dans deux fichiers d'une même élection (fusion + fichier d'origine) : une seule ligne
t["cle"] = t["scrutin"] + "|" + t["nom"].map(sans_accent) + "|" + t["prenom"].fillna("").map(sans_accent) + "|" + t["departement"].fillna("")
t = t.sort_values(["naissance", "profession"], na_position="last").drop_duplicates("cle").drop(columns="cle")
t = t[["scrutin", "departement", "lieu", "nom", "prenom", "sexe", "naissance", "age", "profession", "nuance", "sortant", "source"]]
t.to_parquet(ICI / "candidats_details.parquet", index=False)
print(f"\n{len(t):,} candidats · {t['scrutin'].nunique()} élections · âge connu : {t['age'].notna().mean():.0%} · "
      f"profession connue : {t['profession'].notna().mean():.0%}".replace(",", " "))
print(t.groupby("scrutin").size().to_string())
