"""
fabriquer_contexte_communes.py — Une ligne par commune avec les indicateurs essentiels
(revenus 2021, chômage 2011/2016/2022, diplômes 2012/2017/2023).

    py convertir_en_parquet.py          (d'abord, une fois)
    py fabriquer_contexte_communes.py   -> contexte_communes.parquet

Les fichiers complets restent dans chomage/ et revenus/ (des centaines de colonnes, décrites dans les fichiers meta_).
"""

from pathlib import Path

import duckdb

ICI = Path(__file__).resolve().parent
chomage = (ICI / "chomage" / "base-cc-emploi-pop-active-2022.parquet").as_posix()
revenus = (ICI / "revenus" / "FILO2021_DISP_COM.parquet").as_posix()
pauvres = (ICI / "revenus" / "FILO2021_DISP_PAUVRES_COM.parquet").as_posix()
diplomes = (ICI / "diplomes" / "DS_RP_DIPLOMES_PRINC_2023.parquet").as_posix()
sortie = ICI / "contexte_communes.parquet"

# Diplômes : le fichier INSEE est « long » (une ligne par commune × année × diplôme × sexe).
# On garde les deux sexes ensemble et on calcule la part de chaque diplôme parmi les 15 ans ou plus non scolarisés.
# Codes EDUC : 001T100 aucun diplôme ou certificat d'études · 200 brevet · 300 CAP-BEP · 350T351 bac ·
#              500T702 enseignement supérieur = 500 bac+2 + 600 bac+3/4 + 700 bac+5 ou plus (2012 : 600T702 = bac+3 ou plus)
duckdb.sql(f"""
    CREATE TEMP TABLE dipl AS
    WITH d AS (SELECT GEO AS CODGEO, year(TIME_PERIOD) AS an, EDUC, OBS_VALUE AS v
               FROM '{diplomes}' WHERE GEO_OBJECT IN ('COM', 'ARM') AND SEX = '_T'),
    t AS (SELECT CODGEO, an, v AS total FROM d WHERE EDUC = '_T')
    SELECT CODGEO,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '001T100_RP') / any_value(total) FILTER (an = 2023), 1) AS part_sans_diplome_2023,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '200_RP') / any_value(total) FILTER (an = 2023), 1) AS part_brevet_2023,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '300_RP') / any_value(total) FILTER (an = 2023), 1) AS part_cap_bep_2023,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '350T351_RP') / any_value(total) FILTER (an = 2023), 1) AS part_bac_2023,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '500_RP') / any_value(total) FILTER (an = 2023), 1) AS part_bac2_2023,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '600_RP') / any_value(total) FILTER (an = 2023), 1) AS part_bac3_4_2023,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '700_RP') / any_value(total) FILTER (an = 2023), 1) AS part_bac5_plus_2023,
        round(100 * sum(v) FILTER (an = 2023 AND EDUC = '500T702_RP') / any_value(total) FILTER (an = 2023), 1) AS part_superieur_2023,
        round(100 * sum(v) FILTER (an = 2017 AND EDUC = '500T702_RP') / any_value(total) FILTER (an = 2017), 1) AS part_superieur_2017,
        round(100 * sum(v) FILTER (an = 2012 AND EDUC = '500T702_RP') / any_value(total) FILTER (an = 2012), 1) AS part_superieur_2012,
        round(100 * sum(v) FILTER (an = 2017 AND EDUC = '001T100_RP') / any_value(total) FILTER (an = 2017), 1) AS part_sans_diplome_2017,
        round(100 * sum(v) FILTER (an = 2012 AND EDUC = '001T100_RP') / any_value(total) FILTER (an = 2012), 1) AS part_sans_diplome_2012
    FROM d JOIN t USING (CODGEO, an) GROUP BY CODGEO""")

duckdb.sql(f"""
    COPY (
        SELECT c.CODGEO AS code_commune,
               r.NBMEN21 AS menages_2021,
               r.Q221 AS niveau_vie_median_2021,          -- € par an et par unité de consommation
               r.D121 AS niveau_vie_d1_2021,              -- les 10 % les plus modestes gagnent moins que ça
               r.D921 AS niveau_vie_d9_2021,              -- les 10 % les plus aisés gagnent plus que ça
               r.RD AS rapport_d9_d1_2021,                -- écart entre aisés et modestes
               p.TP6021 AS taux_pauvrete_2021,            -- % sous le seuil de pauvreté (60 % du niveau de vie médian national)
               c.P22_ACT1564 AS actifs_2022,
               round(100 * c.P22_CHOM1564 / nullif(c.P22_ACT1564, 0), 1) AS taux_chomage_2022,
               round(100 * c.P16_CHOM1564 / nullif(c.P16_ACT1564, 0), 1) AS taux_chomage_2016,
               round(100 * c.P11_CHOM1564 / nullif(c.P11_ACT1564, 0), 1) AS taux_chomage_2011,
               d.* EXCLUDE (CODGEO)
        FROM '{chomage}' c
        LEFT JOIN '{revenus}' r USING (CODGEO)
        LEFT JOIN '{pauvres}' p USING (CODGEO)
        LEFT JOIN dipl d USING (CODGEO)
        ORDER BY 1
    ) TO '{sortie.as_posix()}' (FORMAT parquet, COMPRESSION zstd)""")
print(duckdb.sql(f"SELECT count(*) AS communes, count(niveau_vie_median_2021) AS avec_revenu, count(taux_chomage_2022) AS avec_chomage, count(part_superieur_2023) AS avec_diplomes FROM '{sortie.as_posix()}'").fetchall())
print(duckdb.sql(f"SELECT * FROM '{sortie.as_posix()}' WHERE code_commune IN ('43157', '43224')").df().T)
