"""
integrer_investitures.py — Le parti de rattachement de chaque candidat aux législatives (2017, 2022, 2024) : la table
investiture (candidature_id, parti_id, source_id). À lancer après integrer_partis.py (relançable).

Source : « Rattachement des candidats aux élections législatives » (données du ministère de l'Intérieur, obtenues après
avis CADA, publiées sur data.gouv.fr) — BRUT/rattachement candidat. Le parti de rattachement est celui que le candidat
déclare pour le financement public : c'est son étiquette (≠ la nuance, qui est le classement du ministère).
Rapprochement : candidature du 1er tour de la même circonscription, même nom et même premier prénom. Le parti : par son
nom (parti.libelle, puis les noms de la CNCCFP) ; un nom inconnu devient un parti « groupement politique (rattachement) ».
« NON RATTACHÉ » : pas d'investiture.
"""
import re
import time
from pathlib import Path

import pandas as pd

from normaliser_zones import dep
from outils_mariadb import charger, cle_etrangere, mysql, norm, requete, sources

ICI = Path(__file__).resolve().parent
BRUT = ICI.parent.parent / "BRUT" / "rattachement candidat"
CNCCFP = ICI.parent / "donnees_contexte" / "partis" / "partis_cnccfp.tsv"
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
FICHIERS = {"2017_legi": ("rattachement-candidats-leg2017.xls", 2), "2022_legi": ("rattachement-candidats-leg-2022.xlsx", 1),
            "2024_legi": ("rattachement-candidats-leg-2024.xlsx", 1)}
CIRCO = 5                                    # (niveau de zone)


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def lire(election):
    f, debut = FICHIERS[election]
    x = pd.read_excel(BRUT / f, dtype=str, header=None).iloc[debut:]
    if election == "2017_legi":
        x = x[[0, 1, 3, 4, 7]]
    else:
        x = x[[0, 1, 2, 3, 7]]
        x[1] = x[1].str.extract(r"(\d+)")[0]
    x.columns = ["dep", "circo", "nom", "prenom", "parti"]
    x = x.dropna(subset=["nom", "circo"])
    x["zone"] = [f"{dep(d)}-{int(c):02d}" for d, c in zip(x.dep, x.circo)]
    x["cle"] = [norm(n) + "|" + norm(str(p).split(" ")[0].split("-")[0]) for n, p in zip(x.nom, x.prenom)]
    x["election"] = election
    return x


def main():
    t0 = time.time()
    r = pd.concat([lire(e) for e in FICHIERS])
    r = r[~r.parti.map(norm).isin({"NONRATTACHE", "NONRATTACHEE", ""})]
    # les candidatures du 1er tour de ces législatives
    c = requete(f"""SELECT c.id, e.code election, z.code zone, p.nom_usage, p.prenoms FROM candidature c
                    JOIN scrutin s ON s.id = c.scrutin_id AND s.tour = 1 JOIN election e ON e.id = s.election_id
                    JOIN zone z ON z.id = c.zone_id AND z.niveau_id = {CIRCO} JOIN personne p ON p.id = c.personne_id
                    WHERE e.code IN ('2017_legi', '2022_legi', '2024_legi')""")
    c["cle"] = [norm(n) + "|" + norm(str(p).split(" ")[0].split("-")[0]) for n, p in zip(c.nom_usage, c.prenoms)]
    m = r.merge(c[["id", "election", "zone", "cle"]], on=["election", "zone", "cle"], how="left")
    etape(f"rattachements : {len(r)} candidats rattachés à un parti, {m.id.notna().sum()} retrouvés dans les candidatures")
    # les partis, par leur nom
    p = requete("SELECT id, libelle, code_cnccfp FROM parti")
    par_nom = {norm(l): int(i) for i, l in zip(p.id, p.libelle)}
    cn = pd.read_csv(CNCCFP, sep="\t", dtype=str)
    par_code = {c_: int(i) for i, c_ in zip(p.id, p.code_cnccfp) if c_}
    for code, nom, autres in zip(cn.code, cn.nom, cn.autres_noms):
        if code in par_code:
            for n in [nom, *str(autres).split(" | ")]:
                par_nom.setdefault(norm(n), par_code[code])
    inconnus = sorted(set(m.parti) - {n for n in m.parti if norm(n) in par_nom})
    if inconnus:
        suivant = int(p.id.astype(int).max()) + 1
        nouveaux = pd.DataFrame({"id": range(suivant, suivant + len(inconnus)), "libelle": inconnus, "nature_parti_id": 4})
        mysql("INSERT IGNORE INTO nature_parti VALUES (4, 'groupement politique (rattachement)');")
        charger("parti", nouveaux)
        par_nom.update({norm(n): int(i) for i, n in zip(nouveaux.id, nouveaux.libelle)})
    m["parti_id"] = m.parti.map(lambda n: par_nom.get(norm(n)))
    src = sources(["rattachements législatives"])["rattachements législatives"]
    inv = m.dropna(subset=["id"])[["id", "parti_id"]].rename(columns={"id": "candidature_id"}).astype(int).drop_duplicates()
    inv["source_id"] = src
    mysql(f"""DROP TABLE IF EXISTS investiture;
              CREATE TABLE investiture (candidature_id BIGINT NOT NULL, parti_id INT NOT NULL, source_id INT NOT NULL,
                PRIMARY KEY (candidature_id, parti_id), KEY ix_investiture_parti (parti_id)) {T}""")
    charger("investiture", inv)
    for col, ref in (("candidature_id", "candidature"), ("parti_id", "parti"), ("source_id", "source")):
        cle_etrangere("investiture", col, ref)
    etape(f"investiture : {len(inv)} candidatures reliées à leur parti ({len(inconnus)} partis ajoutés, inconnus de la "
          f"CNCCFP et de Wikidata sous ce nom) — fini en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
