"""
integrer_promotions_ena.py — Les promotions de l'ENA d'après la liste officielle de l'école (INSP, ex-ENA) :
donnees/ena/promotions_ena.csv (nom, année d'entrée, année de sortie ; 78 promotions de 1946 à 2021).

    py integrer_promotions_ena.py     (quelques secondes ; à relancer après integrer_formations.py --refaire)

La liste officielle passe AVANT Wikidata :
  * chaque promotion de l'ENA prend le nom officiel (« promotion Jean Jaurès », pas « promotion Jean-Jaurès ») et ses
    années ; les promotions que Wikidata a mal données (la personne qui donne son nom à la promotion — Tocqueville,
    Louise Michel… — ou une année, « 1991 ») sont fondues dans la bonne, ou retirées si on ne sait pas laquelle ;
  * les promotions officielles que Wikidata ne connaissait pas sont ajoutées (sans élèves connus pour l'instant) ;
  * les années de scolarité des élèves (formation) sont celles de leur promotion.
"""
import sys
from pathlib import Path

import pandas as pd

from outils_mariadb import charger, cle_etrangere, mysql, norm, requete, sauvegarder, sources

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
LISTE = C.SAISIES / "ena" / "promotions_ena.csv"
DECHET = C.DECHET
ENA = 1                                  # ecole « École nationale d'administration »


def cle_promo(libelle):
    """« promotion Victor-Schœlcher » et « Victor Schoelcher » → VICTORSCHOELCHER."""
    return norm(str(libelle).removeprefix("promotion ").replace("œ", "oe").replace("Œ", "OE"))


officielle = pd.read_csv(LISTE)
officielle["cle"] = officielle.promotion.map(cle_promo)
SOURCE = sources(["promotions ENA"])["promotions ENA"]
sauvegarder(DECHET, "promotions_avant_liste_ena", ["promotion", "formation"])
mysql("""ALTER TABLE promotion ADD COLUMN IF NOT EXISTS annee_entree SMALLINT NULL,
                               ADD COLUMN IF NOT EXISTS annee_sortie SMALLINT NULL,
                               ADD COLUMN IF NOT EXISTS source_id INT NULL""")

base = requete(f"""SELECT pr.id, pr.libelle, pr.wikidata, (SELECT count(*) FROM formation f WHERE f.promotion_id = pr.id) eleves
                   FROM promotion pr WHERE pr.ecole_id = {ENA}""")
base["id"] = base.id.astype(int)
base["eleves"] = base.eleves.astype(int)
base["cle"] = base.libelle.map(cle_promo)
base = base.merge(officielle[["cle", "promotion", "annee_entree", "annee_sortie"]], on="cle", how="left")

# 1. les promotions de Wikidata qui ne sont pas dans la liste officielle : on ne sait pas laquelle c'est → retirées
inconnues = base[base.promotion.isna()]
for r in inconnues.itertuples():
    print(f"  retirée : « {r.libelle} » ({r.eleves} élève(s) gardé(s) à l'ENA, sans promotion)")
# 2. plusieurs promotions de la base pour une seule officielle : on garde celle qui a le plus d'élèves (la vraie fiche
#    « promotion » de Wikidata), les autres y sont fondues
base = base.dropna(subset=["promotion"]).sort_values(["cle", "libelle"], key=lambda s: s.str.startswith("promotion")
                                                     if s.name == "libelle" else s, ascending=[True, False])
garde = base.sort_values("eleves", ascending=False).drop_duplicates("cle").set_index("cle").id
fondues = base[base.id != base.cle.map(garde)]
for r in fondues.itertuples():
    print(f"  fondue : « {r.libelle} » → « promotion {r.promotion} » ({r.eleves} élève(s))")
sql = ["SET foreign_key_checks = 0"]
for r in fondues.itertuples():
    sql.append(f"UPDATE formation SET promotion_id = {garde[r.cle]} WHERE promotion_id = {r.id}")
if len(inconnues):
    ids = ",".join(map(str, inconnues.id))
    sql.append(f"UPDATE formation SET promotion_id = NULL WHERE promotion_id IN ({ids})")
retirees = list(inconnues.id) + list(fondues.id)
if retirees:
    sql.append(f"DELETE FROM promotion WHERE id IN ({','.join(map(str, retirees))})")
mysql(";\n".join(sql))

# 3. le nom officiel et les années (une table temporaire, puis une seule mise à jour)
gardees = base[base.id.isin(garde.values)][["id", "promotion", "annee_entree", "annee_sortie"]]
mysql("""DROP TABLE IF EXISTS tmp_promo; CREATE TABLE tmp_promo (id INT PRIMARY KEY, libelle VARCHAR(80),
         annee_entree SMALLINT, annee_sortie SMALLINT) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
charger("tmp_promo", gardees.assign(libelle="promotion " + gardees.promotion)[["id", "libelle", "annee_entree", "annee_sortie"]])
mysql(f"""UPDATE promotion p JOIN tmp_promo t ON t.id = p.id
          SET p.libelle = t.libelle, p.annee_entree = t.annee_entree, p.annee_sortie = t.annee_sortie, p.source_id = {SOURCE};
          DROP TABLE tmp_promo""")

# 4. les promotions officielles que la base n'avait pas
nouvelles = officielle[~officielle.cle.isin(garde.index)].copy()
debut = int(requete("SELECT coalesce(max(id), 0) n FROM promotion").n[0]) + 1
nouvelles["id"] = range(debut, debut + len(nouvelles))
charger("promotion", nouvelles.assign(ecole_id=ENA, libelle="promotion " + nouvelles.promotion, source_id=SOURCE)
        [["id", "ecole_id", "libelle", "annee_entree", "annee_sortie", "source_id"]])

# 5. les années de scolarité des élèves = celles de leur promotion (la liste officielle passe avant Wikidata)
avant = int(requete(f"""SELECT count(*) n FROM formation f JOIN promotion p ON p.id = f.promotion_id
                        WHERE p.ecole_id = {ENA} AND (f.annee_entree <=> p.annee_entree) + (f.annee_sortie <=> p.annee_sortie) < 2""").n[0])
mysql(f"""UPDATE formation f JOIN promotion p ON p.id = f.promotion_id
          SET f.annee_entree = p.annee_entree, f.annee_sortie = p.annee_sortie WHERE p.ecole_id = {ENA}""")
deja = requete("SELECT count(*) n FROM information_schema.table_constraints WHERE table_schema = DATABASE() "
               "AND constraint_name = 'fk_promotion_source_id'").n[0]
if deja == "0":
    cle_etrangere("promotion", "source_id", "source")
print(f"{len(garde)} promotions reconnues (nom officiel et années), {len(fondues)} fondues, {len(inconnues)} retirées, "
      f"{len(nouvelles)} ajoutées ; années corrigées pour {avant} élèves")
