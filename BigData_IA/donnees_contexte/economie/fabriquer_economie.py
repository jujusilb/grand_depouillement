"""
fabriquer_economie.py — Télécharge des séries économiques « neutres » et les range en Parquet, jusqu'à la veille du dernier scrutin.

    py fabriquer_economie.py

Sources (gratuites, officielles, sans clé) :
    Euro / dollar      Banque centrale européenne, taux de référence quotidien (depuis 1999)
    Franc / dollar     FRED (Federal Reserve Bank of St. Louis), francs pour 1 dollar, mensuel (1971 → 2001)
    Baril de Brent     FRED, d'après l'EIA américaine, en dollars, quotidien (depuis 1987)
    Prix à la pompe    INSEE, prix moyens mensuels en métropole : gazole (série 000442588), sans plomb 95 (série 000849411)
    Big Mac            The Economist, « Big Mac index » (deux relevés par an depuis 2000)
    Moral des ménages  INSEE, indicateur synthétique de confiance des ménages, CVS, mensuel (série 001587668)
    Inflation          INSEE, prix à la consommation, glissement sur un an, ensemble des ménages, France :
                       base 2015 jusqu'en décembre 2025 (série 001761313), puis base 2025 (série 011814632)
    Chômage            INSEE, taux de chômage au sens du BIT, France hors Mayotte, CVS, trimestriel (série 001688527)

Fichiers fabriqués (dans ce dossier) :
    euro_dollar_jour, franc_dollar_mois, brent_jour, carburants_mois, big_mac, menages_mois, chomage_trimestre .parquet
    economie_mois.parquet      une ligne par mois avec tout
    veille_scrutins.parquet    une ligne par scrutin : la valeur de chaque série la veille du vote
Les fichiers téléchargés tels quels sont gardés dans brut/.
"""

import io
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import duckdb
import pandas as pd

ICI = Path(__file__).resolve().parent
BRUT = ICI / "brut"
BRUT.mkdir(exist_ok=True)
BASE = ICI.parent.parent / "demo_megabase" / "megabase.duckdb"
FRANCS_POUR_1_EURO = 6.55957   # taux fixé le 1er janvier 1999
INSEE = "https://www.bdm.insee.fr/series/sdmx/data/SERIES_BDM/"

SOURCES = {
    "euro_dollar_bce.csv": "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata",
    "franc_dollar_fred.csv": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=EXFRUS",
    "brent_fred.csv": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU",
    "gazole_insee.xml": INSEE + "000442588",
    "sp95_insee.xml": INSEE + "000849411",
    "big_mac_economist.csv": "https://raw.githubusercontent.com/TheEconomist/big-mac-data/master/output-data/big-mac-full-index.csv",
    "confiance_menages_insee.xml": INSEE + "001587668",
    "inflation_base2015_insee.xml": INSEE + "001761313",
    "inflation_base2025_insee.xml": INSEE + "011814632",
    "chomage_bit_insee.xml": INSEE + "001688527",
}


def telecharger(nom):
    requete = urllib.request.Request(SOURCES[nom], headers={"User-Agent": "Mozilla/5.0 (projet etudiant)"})
    contenu = urllib.request.urlopen(requete, timeout=120).read()
    (BRUT / nom).write_bytes(contenu)
    return contenu


def serie_insee(contenu):
    """Une série de la banque de données de l'INSEE (format SDMX, du XML) -> tableau période / valeur.
    La période est le 1er jour du mois (« 2026-09 ») ou du trimestre (« 2026-Q2 »)."""
    lignes = [(o.get("TIME_PERIOD"), o.get("OBS_VALUE")) for o in ET.fromstring(contenu).iter() if o.get("TIME_PERIOD")]
    d = pd.DataFrame(lignes, columns=["mois", "valeur"])
    d["mois"] = [pd.Period(p, freq="Q").start_time if "Q" in p else pd.Timestamp(p) for p in d["mois"]]
    d["valeur"] = pd.to_numeric(d["valeur"], errors="coerce")
    return d.sort_values("mois")


def fred(nom, colonne):
    d = pd.read_csv(io.BytesIO(telecharger(nom)))
    d.columns = ["date", colonne]
    return pd.DataFrame({"date": pd.to_datetime(d["date"]), colonne: pd.to_numeric(d[colonne], errors="coerce")}).dropna()


# La date limite : la veille du dernier scrutin de la méga base
con = duckdb.connect(str(BASE), read_only=True)
scrutins = con.sql("SELECT scrutin, libelle, CAST(date AS DATE) AS date FROM scrutins ORDER BY date").df()
scrutins["date"] = pd.to_datetime(scrutins["date"])
LIMITE = scrutins["date"].max() - pd.to_timedelta(1, unit="D")
print("Séries coupées au", LIMITE.date(), "(veille du dernier scrutin)")

# Euro / dollar (BCE) : combien de dollars pour 1 euro
bce = pd.read_csv(io.BytesIO(telecharger("euro_dollar_bce.csv")))
euro = pd.DataFrame({"date": pd.to_datetime(bce["TIME_PERIOD"]), "eur_usd": pd.to_numeric(bce["OBS_VALUE"], errors="coerce")}).dropna()

# Franc / dollar (FRED) : francs pour 1 dollar jusqu'en 2001 ; on ajoute « dollars pour 1 franc », et après 1999
# l'équivalent tiré de l'euro (1 euro = 6,55957 francs), pour avoir une seule courbe de 1971 à aujourd'hui
franc = fred("franc_dollar_fred.csv", "francs_pour_1_dollar").rename(columns={"date": "mois"})
franc["dollars_pour_1_franc"] = (1 / franc["francs_pour_1_dollar"]).round(5)

# Baril de Brent (FRED) : dollars par baril ; converti en euros avec le taux du jour
brent = fred("brent_fred.csv", "brent_usd")
brent = pd.merge_asof(brent.sort_values("date"), euro.sort_values("date"), on="date")
brent["brent_eur"] = (brent["brent_usd"] / brent["eur_usd"]).round(2)
brent = brent.drop(columns="eur_usd")

# Prix à la pompe (INSEE) : euros par litre, moyenne du mois en métropole
gazole = serie_insee(telecharger("gazole_insee.xml")).rename(columns={"valeur": "gazole_litre"})
sp95 = serie_insee(telecharger("sp95_insee.xml")).rename(columns={"valeur": "sp95_litre"})
carburants = gazole.merge(sp95, on="mois", how="outer").sort_values("mois")

# Big Mac (The Economist) : prix local, prix en dollars, et sur/sous-évaluation de la monnaie face au dollar (USD_raw)
bm = pd.read_csv(io.BytesIO(telecharger("big_mac_economist.csv")))
bm["date"] = pd.to_datetime(bm["date"])
big_mac = bm[["date", "iso_a3", "name", "currency_code", "local_price", "dollar_ex", "dollar_price", "USD_raw"]].copy()

# Moral des ménages et inflation (INSEE), mensuels. L'inflation change de base en janvier 2026 : on met les deux bout à bout.
confiance = serie_insee(telecharger("confiance_menages_insee.xml")).rename(columns={"valeur": "moral_menages"})
infl15 = serie_insee(telecharger("inflation_base2015_insee.xml"))
infl25 = serie_insee(telecharger("inflation_base2025_insee.xml"))
inflation = pd.concat([infl15[infl15.mois < "2026-01-01"], infl25[infl25.mois >= "2026-01-01"]]).rename(columns={"valeur": "inflation_1an"})
menages = confiance.merge(inflation, on="mois", how="outer").sort_values("mois")

# Chômage au sens du BIT (INSEE), trimestriel ; « trimestre » = son 1er jour
chomage = serie_insee(telecharger("chomage_bit_insee.xml")).rename(columns={"mois": "trimestre", "valeur": "chomage_bit"})

# On coupe tout à la veille du dernier scrutin. Une valeur mensuelle (ou trimestrielle) est une moyenne sur toute la période :
# on ne garde que les périodes TERMINÉES avant la limite.
fin_mois = lambda d: d + pd.offsets.MonthEnd(0)
fin_trim = lambda d: d + pd.offsets.QuarterEnd(0)
euro, brent, big_mac = euro[euro.date <= LIMITE], brent[brent.date <= LIMITE], big_mac[big_mac.date <= LIMITE]
carburants, menages = carburants[fin_mois(carburants.mois) <= LIMITE], menages[fin_mois(menages.mois) <= LIMITE]
franc, chomage = franc[fin_mois(franc.mois) <= LIMITE], chomage[fin_trim(chomage.trimestre) <= LIMITE]
for nom, d in [("euro_dollar_jour", euro), ("franc_dollar_mois", franc), ("brent_jour", brent), ("carburants_mois", carburants),
               ("big_mac", big_mac), ("menages_mois", menages), ("chomage_trimestre", chomage)]:
    d.to_parquet(ICI / f"{nom}.parquet", index=False)
    print(f"{nom}.parquet : {len(d)} lignes, de {d.iloc[:, 0].min().date()} à {d.iloc[:, 0].max().date()}")

# Une ligne par mois
mois = lambda d, col: d.assign(mois=d[col].dt.to_period("M").dt.to_timestamp())
zone_euro = big_mac[big_mac.iso_a3 == "EUZ"].sort_values("date")
eco = (mois(euro, "date").groupby("mois")["eur_usd"].mean().round(4).to_frame()
       .join(franc.set_index("mois")[["francs_pour_1_dollar", "dollars_pour_1_franc"]], how="outer")
       .join(mois(brent, "date").groupby("mois")[["brent_usd", "brent_eur"]].mean().round(2), how="outer")
       .join(carburants.set_index("mois"), how="outer")
       .join(menages.set_index("mois"), how="outer").reset_index())
# le franc après 1999 : l'équivalent tiré de l'euro, pour une courbe continue
apres = eco["dollars_pour_1_franc"].isna() & eco["eur_usd"].notna()
eco.loc[apres, "dollars_pour_1_franc"] = (eco.loc[apres, "eur_usd"] / FRANCS_POUR_1_EURO).round(5)
# le chômage trimestriel vaut pour les 3 mois de son trimestre
eco["trimestre"] = eco["mois"].dt.to_period("Q").dt.start_time
eco = eco.merge(chomage, on="trimestre", how="left").drop(columns="trimestre")
eco = pd.merge_asof(eco.sort_values("mois"), zone_euro[["date", "local_price", "dollar_price"]]
                    .rename(columns={"date": "releve_big_mac", "local_price": "big_mac_euros", "dollar_price": "big_mac_dollars"}),
                    left_on="mois", right_on="releve_big_mac")
eco = eco[eco.mois <= LIMITE]
eco.to_parquet(ICI / "economie_mois.parquet", index=False)
print(f"economie_mois.parquet : {len(eco)} mois")

# La valeur de chaque série la veille de chaque scrutin (la dernière connue avant le vote)
v = scrutins.assign(veille=scrutins["date"] - pd.to_timedelta(1, unit="D")).sort_values("veille")
v = pd.merge_asof(v, euro.sort_values("date").rename(columns={"date": "d1"}), left_on="veille", right_on="d1")
v = pd.merge_asof(v, brent.sort_values("date").rename(columns={"date": "d2"}), left_on="veille", right_on="d2")
# mensuel / trimestriel : la dernière période terminée avant le vote (celle du vote contiendrait des jours d'après)
v = pd.merge_asof(v, carburants.assign(d3=fin_mois(carburants.mois)).rename(columns={"mois": "mois_carburants"}), left_on="veille", right_on="d3")
v = pd.merge_asof(v, menages.assign(d5=fin_mois(menages.mois)).rename(columns={"mois": "mois_menages"}), left_on="veille", right_on="d5")
v = pd.merge_asof(v, chomage.assign(d6=fin_trim(chomage.trimestre)).rename(columns={"trimestre": "trimestre_chomage"}), left_on="veille", right_on="d6")
v = pd.merge_asof(v, zone_euro[["date", "local_price"]].rename(columns={"date": "d4", "local_price": "big_mac_euros"}), left_on="veille", right_on="d4")
v = pd.merge_asof(v, eco[["mois", "dollars_pour_1_franc"]].assign(d7=lambda d: fin_mois(d.mois)).drop(columns="mois").dropna(),
                  left_on="veille", right_on="d7")
v = v.drop(columns=["d1", "d2", "d3", "d4", "d5", "d6", "d7"])
v.to_parquet(ICI / "veille_scrutins.parquet", index=False)
print(f"veille_scrutins.parquet : {len(v)} scrutins")
print(v[["scrutin", "veille", "eur_usd", "sp95_litre", "moral_menages", "inflation_1an", "chomage_bit", "dollars_pour_1_franc"]].to_string(index=False))
