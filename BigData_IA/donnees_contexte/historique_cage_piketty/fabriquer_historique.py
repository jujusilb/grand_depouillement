"""
fabriquer_historique.py — Les élections d'avant 2002, PAR COMMUNE, de Julia Cagé et Thomas Piketty
(« Une histoire du conflit politique. Élections et inégalités sociales en France, 1789-2022 », Seuil, 2023 —
données libres, à citer : https://www.unehistoireduconflitpolitique.fr).

    py fabriquer_historique.py          (~2 min)

brut/*.zip (un CSV par scrutin, téléchargés du site) →
  1. parquet/<scrutin>.parquet : chaque CSV tel quel, en parquet (plus léger, plus rapide à lire)
  2. les tables de l'appli, au même format que la méga base (un « bureau » = la commune entière, code « 0000 ») :
       historique_scrutins.parquet · historique_participation.parquet · historique_resultats.parquet
     Législatives : un « candidat » = un courant politique (les colonnes du fichier : PCF, SFIO, RADSOC…).
     Présidentielles : les candidats, 1er et 2nd tour (1848 : un seul tour). Référendums : OUI et NON.
     La « nuance » range chaque courant dans une famille d'aujourd'hui (pour sa couleur) : c'est une APPROXIMATION.

Les communes sont déjà ramenées par Cagé et Piketty à leur code INSEE actuel (même pour 1793).
"""
import io
import zipfile
from pathlib import Path

import pandas as pd

ICI = Path(__file__).resolve().parent
BRUT, PARQUET = ICI / "brut", ICI / "parquet"
PARQUET.mkdir(exist_ok=True)

# fichier : (scrutin, type, type_libelle, année, date du 1er tour, date du 2nd tour ou None, précision du libellé)
SCRUTINS = {
    "ref1793": ("1793_refe_t1", "refe", "Référendum", 1793, "1793-07-15", None, "Constitution de l'an I"),
    "ref1795": ("1795_refe_t1", "refe", "Référendum", 1795, "1795-09-06", None, "Constitution de l'an III"),
    "ref1946": ("1946_refe_t1", "refe", "Référendum", 1946, "1946-05-05", None, "1er projet de constitution (rejeté)"),
    "pres1848": ("1848_pres_t1", "pres", "Présidentielle", 1848, "1848-12-10", None, "tour unique"),
    "pres1965": ("1965_pres_t1", "pres", "Présidentielle", 1965, "1965-12-05", "1965-12-19", ""),
    "pres1969": ("1969_pres_t1", "pres", "Présidentielle", 1969, "1969-06-01", "1969-06-15", ""),
    "pres1974": ("1974_pres_t1", "pres", "Présidentielle", 1974, "1974-05-05", "1974-05-19", ""),
    "pres1981": ("1981_pres_t1", "pres", "Présidentielle", 1981, "1981-04-26", "1981-05-10", ""),
    "pres1988": ("1988_pres_t1", "pres", "Présidentielle", 1988, "1988-04-24", "1988-05-08", ""),
    "pres1995": ("1995_pres_t1", "pres", "Présidentielle", 1995, "1995-04-23", "1995-05-07", ""),
}
DATES_LEGISLATIVES = {
    "1848": "1848-04-23", "1849": "1849-05-13", "1871fev": "1871-02-08", "1871juil": "1871-07-02", "1876": "1876-02-20",
    "1881": "1881-08-21", "1885": "1885-10-04", "1889": "1889-09-22", "1893": "1893-08-20", "1898": "1898-05-08",
    "1902": "1902-04-27", "1906": "1906-05-06", "1910": "1910-04-24", "1914": "1914-04-26", "1919": "1919-11-16",
    "1924": "1924-05-11", "1928": "1928-04-22", "1932": "1932-05-01", "1936": "1936-04-26", "1945": "1945-10-21",
    "1946Juin": "1946-06-02", "1946Nov": "1946-11-10", "1951": "1951-06-17", "1956": "1956-01-02", "1958": "1958-11-23",
    "1962": "1962-11-18", "1967": "1967-03-05", "1968": "1968-06-23", "1973": "1973-03-04", "1978": "1978-03-12",
    "1981": "1981-06-14", "1986": "1986-03-16", "1988": "1988-06-05", "1993": "1993-03-21", "1997": "1997-05-25",
}
PROPORTIONNELLE = {"1945", "1946Juin", "1946Nov", "1951", "1956", "1986"}     # un seul tour
for k, date in DATES_LEGISLATIVES.items():
    an = int(k[:4])
    suffixe = {"fev": "a", "juil": "b", "Juin": "a", "Nov": "b"}.get(k[4:], "")
    precision = {"fev": "février", "juil": "juillet", "Juin": "juin", "Nov": "novembre"}.get(k[4:], "")
    precision = precision or ("tour unique" if k in PROPORTIONNELLE else "1er tour")
    SCRUTINS["leg" + k] = (f"{an}{suffixe}_legi_t1", "legi", "Législatives", an, date, None, precision)

# Les candidats des présidentielles : (Prénom NOM, nuance d'aujourd'hui pour la couleur)
CANDIDATS = {
    "RASPAIL": ("François-Vincent RASPAIL", "EXG"), "LEDRUROLLIN": ("Alexandre LEDRU-ROLLIN", "SOC"),
    "LAMARTINE": ("Alphonse de LAMARTINE", "DVG"), "CAVAIGNAC": ("Louis-Eugène CAVAIGNAC", "UDF"),
    "BONAPARTE": ("Louis-Napoléon BONAPARTE", "RPR"), "CHANGARNIER": ("Nicolas CHANGARNIER", "DVD"),
    "BARBU": ("Marcel BARBU", "DIV"), "MITTERRAND": ("François MITTERRAND", "SOC"), "LECANUET": ("Jean LECANUET", "UDF"),
    "DEGAULLE": ("Charles DE GAULLE", "RPR"), "MARCILHACY": ("Pierre MARCILHACY", "DVD"),
    "TIXIERVIGNANCOUR": ("Jean-Louis TIXIER-VIGNANCOUR", "EXD"), "KRIVINE": ("Alain KRIVINE", "EXG"),
    "ROCARD": ("Michel ROCARD", "EXG"), "DUCLOS": ("Jacques DUCLOS", "PCF"), "DEFFERRE": ("Gaston DEFFERRE", "SOC"),
    "DUCATEL": ("Louis DUCATEL", "DIV"), "POMPIDOU": ("Georges POMPIDOU", "RPR"), "POHER": ("Alain POHER", "UDF"),
    "LAGUILLER": ("Arlette LAGUILLER", "EXG"), "DUMONT": ("René DUMONT", "ECO"), "HERAUD": ("Guy HÉRAUD", "REG"),
    "MULLER": ("Émile MULLER", "DVG"), "SEBAG": ("Jean-Claude SEBAG", "DIV"), "CHABANDELMAS": ("Jacques CHABAN-DELMAS", "RPR"),
    "GISCARDDESTAING": ("Valéry GISCARD D'ESTAING", "UDF"), "ROYER": ("Jean ROYER", "DVD"),
    "RENOUVIN": ("Bertrand RENOUVIN", "DVD"), "LEPEN": ("Jean-Marie LE PEN", "FN"), "MARCHAIS": ("Georges MARCHAIS", "PCF"),
    "BOUCHARDEAU": ("Huguette BOUCHARDEAU", "EXG"), "CREPEAU": ("Michel CRÉPEAU", "RDG"), "LALONDE": ("Brice LALONDE", "ECO"),
    "CHIRAC": ("Jacques CHIRAC", "RPR"), "DEBRE": ("Michel DEBRÉ", "DVD"), "GARAUD": ("Marie-France GARAUD", "MPF"),
    "BOUSSEL": ("Pierre BOUSSEL", "EXG"), "JUQUIN": ("Pierre JUQUIN", "DVG"), "LAJOINIE": ("André LAJOINIE", "PCF"),
    "WAECHTER": ("Antoine WAECHTER", "ECO"), "BARRE": ("Raymond BARRE", "UDF"), "HUE": ("Robert HUE", "PCF"),
    "VOYNET": ("Dominique VOYNET", "ECO"), "JOSPIN": ("Lionel JOSPIN", "SOC"), "CHEMINADE": ("Jacques CHEMINADE", "DIV"),
    "BALLADUR": ("Édouard BALLADUR", "UDF"), "VILLIERS": ("Philippe de VILLIERS", "MPF"),
}

# Les courants des législatives (codes de Cagé et Piketty) → une nuance d'aujourd'hui, pour la couleur (approximatif)
FAMILLES = {
    "EXG": "SOCREV AUG LO LCR PSU PCI",
    "PCF": "COM PCF BOP",
    "UG": "PCFSFIO",
    "SOC": "DEMSOC SOC SOCOUV SOCUNI SOCIND SOCGUES SFIO FGDS PS PSRDG MRG RDG",
    "DVG": "DVG USR REPSOC MAJ RAD RADSOC RADIND RADDIV RADDIS RADREP REPRAD PRRS UR REP OPP RADSOCIND UFDRAD TED",
    "ECO": "ECO VEC GEC",
    "REG": "REG",
    "UDF": "UDF MRP CDEM CPDM CDPURP CENT CONST REPMOD RG RGR UDSR UDSRMIN CRR MR RADCENT FRREP REPDIV REPMIN REPIND REPCONS RGRIF",
    "UDI": "REPLIB PROG REPPROG LIB ARD MOD RALLIE ADRG ADIND ADPDP AD ADPRD RADARD FRARD FRLIB RIURP RADDROIT CED",
    "RPR": "RPR UDFRPR UNR UNRUDT UD5UNR UDR UDRURP RPF GAUL GAULG RFGAUL DIVGAUL CNI PRL INDPAYS ADPAYS URDDVD UIPRN "
           "CONS CONSAF FR FRPR FRURD URERD ERD BN MON LEG CLE REAC BON PLEB PLEBI ALP",
    "DVD": "DVD INDV",
    "EXD": "FN POUJ UFFUDCA AUD AUDAR AF ANT NATI BOUL REVIS UNIR",
    "CPNT": "AGR",
}
# … et le nom de la famille, écrit dans la colonne « nuance » (la légende de la carte l'affiche ; gd/theme.py lui donne sa couleur)
NOM_FAMILLE = {"EXG": "extrême gauche", "PCF": "communiste", "UG": "union de la gauche", "SOC": "socialiste", "DVG": "radicaux",
               "ECO": "écologiste", "REG": "régionaliste", "UDF": "centre", "UDI": "centre droit", "RPR": "gaullistes et droite",
               "DVD": "divers droite", "EXD": "extrême droite", "CPNT": "agrariens", "MPF": "souverainiste", "FN": "extrême droite",
               "RDG": "socialiste", "DIV": "divers"}
NUANCE_DE = {code: NOM_FAMILLE[n] for n, codes in FAMILLES.items() for code in codes.split()}


def lire(zip_):
    z = zipfile.ZipFile(zip_)
    nom = next(n for n in z.namelist() if n.endswith(".csv") and "MACOSX" not in n)
    t = pd.read_csv(io.BytesIO(z.read(nom)), low_memory=False)
    for c in t.columns[t.dtypes == object]:          # colonnes mélangées (« 2A004 » et 1001…) : en texte
        t[c] = t[c].astype("string")
    return t


def code_insee(x):
    x = str(x).strip().removesuffix(".0")
    return x.zfill(5)


scrutins, participation, resultats = [], [], []
for zip_ in sorted(BRUT.glob("*_csv.zip")):
    cle = zip_.name.removesuffix("_csv.zip")
    if cle not in SCRUTINS:
        continue
    t = lire(zip_)
    t.to_parquet(PARQUET / f"{cle}.parquet", index=False, compression="zstd")
    scrutin, typ, type_lib, an, date1, date2, precision = SCRUTINS[cle]
    if "plmdoublon" in t:                              # Paris, Lyon, Marseille comptés deux fois (ville + arrondissements)
        t = t[t["plmdoublon"].fillna(0) != 1]
    t["code_commune"] = t["codecommune"].map(code_insee)
    if "inscrits" not in t or t["inscrits"].isna().all():
        t["inscrits"] = t.get("electeurs")
    voix1 = [c for c in t.columns if c.startswith("voix") and not c.startswith(("voixT2", "voixtot"))]
    voix2 = [c for c in t.columns if c.startswith("voixT2")]
    nombres = ["inscrits", "votants", "exprimes", "inscritsT2", "votantsT2", "exprimesT2"] + voix1 + voix2
    nombres = [c for c in nombres if c in t]
    t[nombres] = t[nombres].apply(pd.to_numeric, errors="coerce")
    noms = t.dropna(subset=["nomcommune"]).groupby("code_commune")["nomcommune"].first() if "nomcommune" in t else None
    t = t.groupby("code_commune", as_index=False)[nombres].sum(min_count=1)      # une ligne par commune
    t["libelle_commune"] = t["code_commune"].map(noms) if noms is not None else None
    t["code_departement"] = [c[:3] if c.startswith("97") else c[:2] for c in t["code_commune"]]
    t["id_brut_miom"] = t["code_commune"] + "_0000"

    tours = [(1, scrutin, date1, "", voix1)]
    if voix2:
        tours.append((2, scrutin.replace("_t1", "_t2"), date2, "T2", voix2))
    for tour, s, date, suf, colonnes in tours:
        libelle = f"{type_lib} {an} – " + (precision if tour == 1 and precision else "2nd tour" if tour == 2 else "1er tour")
        scrutins.append((s, typ, type_lib, an, tour, pd.Timestamp(date), libelle))
        p = pd.DataFrame({"scrutin": s, "id_brut_miom": t["id_brut_miom"], "code_bv": "0000", "code_commune": t["code_commune"],
                          "libelle_commune": t["libelle_commune"], "code_departement": t["code_departement"]})
        ins = t.get("inscrits" + suf, t["inscrits"])
        exprimes = t["exprimes" + suf] if "exprimes" + suf in t else t[colonnes].sum(axis=1)
        votants = t["votants" + suf] if "votants" + suf in t else exprimes
        p["inscrits"], p["votants"], p["exprimes"] = ins, votants, exprimes
        p["abstentions"] = ins - votants
        p["nuls"] = (votants - exprimes).clip(lower=0)
        p["blancs"] = float("nan")                     # jamais distingués des nuls à l'époque
        participation.append(p[p["inscrits"].notna() | p["exprimes"].notna()])
        r = t[["id_brut_miom"] + colonnes].melt(id_vars="id_brut_miom", var_name="colonne", value_name="voix").query("voix > 0")
        code = r["colonne"].str.removeprefix("voix").str.removeprefix("T2")
        if typ == "pres":
            r["qui"] = code.map(lambda c: CANDIDATS.get(c, (c.title(), None))[0])
            r["nuance"] = code.map(lambda c: NOM_FAMILLE[CANDIDATS.get(c, (None, "DIV"))[1]])
        elif typ == "refe":
            r["qui"] = r["nuance"] = code
        else:
            r["qui"] = code
            r["nuance"] = code.map(lambda c: NUANCE_DE.get(c, "divers"))
        r["scrutin"] = s
        resultats.append(r[["scrutin", "id_brut_miom", "qui", "nuance", "voix"]])
    print(f"  {cle:<14} {len(t):>6} communes · {len(voix1)} colonnes de voix" + (" (+ 2nd tour)" if voix2 else ""), flush=True)

s = pd.DataFrame(scrutins, columns=["scrutin", "type", "type_libelle", "annee", "tour", "date", "libelle"])
p = pd.concat(participation, ignore_index=True)
for c in ["inscrits", "votants", "exprimes", "abstentions", "nuls"]:
    p[c] = p[c].round().astype("Int64")
r = pd.concat(resultats, ignore_index=True)
r["voix"] = r["voix"].round().astype("int64")
s.to_parquet(ICI / "historique_scrutins.parquet", index=False)
p.to_parquet(ICI / "historique_participation.parquet", index=False)
r.to_parquet(ICI / "historique_resultats.parquet", index=False)
inconnus = sorted(set(r.loc[r["nuance"] == "divers", "qui"]) - {"DIV"})
print(f"\n{len(s)} scrutins · {len(p):,} lignes de participation · {len(r):,} résultats".replace(",", " "))
print("Courants sans famille (rangés en « divers ») :", " ".join(inconnus) or "aucun")
