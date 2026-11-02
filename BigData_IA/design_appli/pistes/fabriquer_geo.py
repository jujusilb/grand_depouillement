"""
fabriquer_geo.py — Fabrique geo_data.js : le découpage géographique pour la ligne « en cascade » de l'atelier.

    py fabriquer_geo.py      (une seule fois, ~1 minute)

Sources (lues, jamais modifiées) :
    demo_megabase/megabase.duckdb     région, département, arrondissement, commune, bureau (législatives 2022)
    ELECTION/general_results.csv      circonscription (législatives 2022) et canton (départementales 2021) de chaque bureau
    ELECTION/table-bv-reu.csv         arrondissement de Paris/Lyon/Marseille et nom de chaque bureau
    ELECTION/v_commune_2026.csv       noms des arrondissements de Paris/Lyon/Marseille
    design_appli/donnees_insee/EPCI_au_01-01-2026.xlsx   intercommunalité de chaque commune (table officielle INSEE,
                                      téléchargée sur https://www.insee.fr/fr/information/2510634)
"""

import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import duckdb
import pandas as pd

ICI = Path(__file__).resolve().parent
BASE = ICI.parent.parent / "demo_megabase" / "megabase.duckdb"
ELECTION = ICI.parent.parent.parent / "ELECTION"

INSEE = ICI.parent / "donnees_insee" / "EPCI_au_01-01-2026.xlsx"   # table INSEE des intercommunalités au 1er janvier 2026


def lire_feuille_xlsx(chemin, feuille):
    """Lit une feuille Excel sans openpyxl (qui refuse les styles du fichier INSEE) : un .xlsx est un zip de XML."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    z = zipfile.ZipFile(chemin)
    partages = []
    if "xl/sharedStrings.xml" in z.namelist():
        partages = ["".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t"))
                    for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns)]
    rid = next(s.get(f"{{{ns['r']}}}id") for s in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{{{ns['m']}}}sheet")
               if s.get("name") == feuille)
    cible = next(r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")) if r.get("Id") == rid)
    lignes = []
    for ligne in ET.fromstring(z.read("xl/" + cible.lstrip("/").removeprefix("xl/"))).iter(f"{{{ns['m']}}}row"):
        valeurs = []
        for c in ligne.findall("m:c", ns):
            if c.get("t") == "inlineStr":
                v = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
            else:
                v = c.findtext("m:v", "", ns)
                if c.get("t") == "s":
                    v = partages[int(v)]
            valeurs.append(v)
        lignes.append(valeurs)
    entete = next(i for i, l in enumerate(lignes) if "CODGEO" in l)   # les premières lignes sont un titre
    return pd.DataFrame(lignes[entete + 1:], columns=lignes[entete])


con = duckdb.connect()
con.execute(f"ATTACH '{BASE.as_posix()}' AS mb (READ_ONLY)")
con.execute(f"""CREATE TABLE general AS SELECT id_election, id_brut_miom, code_departement, code_commune,
    code_circonscription, libelle_circonscription, code_canton, libelle_canton
    FROM read_csv('{(ELECTION / "general_results.csv").as_posix()}', delim=';', all_varchar=true)
    WHERE id_election IN ('2022_legi_t1', '2021_dpmt_t1')""")

# Les bureaux des législatives 2022, avec tous leurs niveaux
bureaux = con.sql(f"""
    WITH b AS (SELECT DISTINCT id_brut_miom, code_bv, code_commune, libelle_commune, code_departement, libelle_departement,
                      code_region, libelle_region, code_arr, libelle_arr
               FROM mb.participation WHERE scrutin = '2022_legi_t1'),
    circ AS (SELECT id_brut_miom, code_departement || '-' || code_circonscription AS circ, libelle_circonscription AS lib_circ
             FROM general WHERE id_election = '2022_legi_t1'),
    can AS (SELECT id_brut_miom, code_departement || '-' || code_canton AS can, libelle_canton AS lib_can
            FROM general WHERE id_election = '2021_dpmt_t1' AND code_canton IS NOT NULL),
    -- un bureau renuméroté depuis 2021 : on prend le canton de sa commune si elle n'en a qu'un
    can_com AS (SELECT code_commune, any_value(code_departement || '-' || code_canton) AS can, any_value(libelle_canton) AS lib_can
                FROM general WHERE id_election = '2021_dpmt_t1' AND code_canton IS NOT NULL
                GROUP BY code_commune HAVING count(DISTINCT code_canton) = 1),
    reu AS (SELECT id_brut_miom, any_value(code_commune) AS arm, any_value(libelle_reu) AS nom
            FROM read_csv('{(ELECTION / "table-bv-reu.csv").as_posix()}', all_varchar=true) GROUP BY 1)
    SELECT b.*, circ.circ, circ.lib_circ, coalesce(can.can, can_com.can) AS can, coalesce(can.lib_can, can_com.lib_can) AS lib_can,
           CASE WHEN b.code_commune IN ('75056', '69123', '13055') THEN reu.arm END AS arm, reu.nom
    FROM b LEFT JOIN circ USING (id_brut_miom) LEFT JOIN can USING (id_brut_miom)
           LEFT JOIN can_com ON can_com.code_commune = b.code_commune LEFT JOIN reu USING (id_brut_miom)
    ORDER BY b.code_commune, b.code_bv""").df()

# L'intercommunalité (communauté de communes, d'agglomération, urbaine, métropole) de chaque commune,
# d'après la table officielle de l'INSEE au 1er janvier 2026 (feuille « Composition_communale »)
epci = lire_feuille_xlsx(INSEE, "Composition_communale").rename(columns={"CODGEO":"code_commune", "EPCI":"siren", "LIBEPCI":"lib_epci"})
epci = epci[epci["siren"] != "ZZZZZZZZZ"][["code_commune", "siren", "lib_epci"]]   # ZZZZZZZZZ = commune sans intercommunalité (îles)
bureaux = bureaux.merge(epci, on="code_commune", how="left")

arm_noms = con.sql(f"""SELECT COM, LIBELLE FROM read_csv('{(ELECTION / "v_commune_2026.csv").as_posix()}', all_varchar=true)
                       WHERE TYPECOM = 'ARM'""").df().set_index("COM")["LIBELLE"].to_dict()

def uniques(colonnes):
    return bureaux[colonnes].dropna(subset=[colonnes[0]]).drop_duplicates(colonnes[0]).values.tolist()

geo = {
    "reg": uniques(["code_region", "libelle_region"]),
    "dep": uniques(["code_departement", "libelle_departement", "code_region"]),
    "arr": uniques(["code_arr", "libelle_arr", "code_departement"]),
    "circ": uniques(["circ", "lib_circ", "code_departement"]),
    "can": uniques(["can", "lib_can", "code_departement"]),
    "epci": uniques(["siren", "lib_epci"]),
    # une commune : code, nom, département, arrondissement, intercommunalité
    "com": [[c, l, d, a, s if isinstance(s, str) else ""] for c, l, d, a, s in
            bureaux[["code_commune", "libelle_commune", "code_departement", "code_arr", "siren"]]
            .drop_duplicates("code_commune").values.tolist()],
    "arm": [[a, arm_noms.get(a, a), c] for a, c in bureaux[["arm", "code_commune"]].dropna().drop_duplicates().values.tolist()],
    # un bureau : commune, numéro, nom, circonscription, canton, arrondissement municipal
    "bv": [[r.code_commune, r.code_bv, (r.nom or "")[:32], r.circ or "", r.can or "", r.arm or ""]
           for r in bureaux.itertuples()],
}
for cle in ("reg", "dep", "arr", "circ", "can", "epci", "com"):
    geo[cle].sort(key=lambda x: x[1])
texte = "// Fabriqué par fabriquer_geo.py — découpage géographique (législatives 2022, cantons 2021)\nconst GEO = " + \
        json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + ";\n"
(ICI / "geo_data.js").write_text(texte, encoding="utf-8")
print({k: len(v) for k, v in geo.items()}, f"{len(texte) / 1e6:.1f} Mo")
