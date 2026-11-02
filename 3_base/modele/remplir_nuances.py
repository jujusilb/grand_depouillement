"""
remplir_nuances.py — Remplir à la main les explications (et les familles) des nuances que les grilles officielles
ne donnent pas, puis les envoyer dans la base.

    py remplir_nuances.py              écrit donnees/nuances/nuances_a_remplir.csv
                                       (toutes les nuances ; celles déjà remplies gardent leur texte)
    … ouvrir le fichier (Excel, LibreOffice), remplir les colonnes explication et famille, enregistrer en CSV …
    py remplir_nuances.py envoyer      envoie dans MariaDB ce qui a été rempli (puis l'appli le voit à son lancement)

Colonnes : code (ne pas toucher), explication (le texte de l'info-bulle : « Liste d'union de la gauche »),
famille (l'une des familles listées dans familles.txt, à côté), utilisee (nombre de lignes de résultats, pour savoir
par quoi commencer), source (« officielle » si le texte vient d'une grille du ministère).
Une case vide ne change rien dans la base.
"""
import sys
from pathlib import Path

import pandas as pd

from outils_mariadb import charger, mysql, requete

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
sys.path.insert(0, str(RACINE_DEPOT / "appli"))                # (les modules de l'appli)
import chemins as C  # noqa: E402
DOSSIER = C.SAISIES / "nuances"
FICHIER = DOSSIER / "nuances_a_remplir.csv"
OFFICIELLES = DOSSIER / "referentiels_ministere.tsv"
T = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"


def ecrire():
    n = requete("""SELECT n.libelle code, n.explication, f.libelle famille,
                          (SELECT count(*) FROM resultat r WHERE r.nuance_id = n.id) utilisee
                   FROM nuance n LEFT JOIN famille f ON f.id = n.famille_id ORDER BY n.explication IS NOT NULL, utilisee + 0 DESC""")
    officielles = set(pd.read_csv(OFFICIELLES, sep="\t", comment="#", dtype=str)["code"])
    n["source"] = ["officielle" if c in officielles and e else "" for c, e in zip(n.code, n.explication)]
    if FICHIER.exists():          # (ce qui a été tapé et pas encore envoyé n'est pas perdu)
        avant = pd.read_csv(FICHIER, sep=";", dtype=str, encoding="utf-8-sig").set_index("code")
        for col in ("explication", "famille"):
            tape = n["code"].map(avant[col]) if col in avant else None
            if tape is not None:
                n[col] = n[col].where(n[col].notna(), tape)
    n.to_csv(FICHIER, sep=";", index=False, encoding="utf-8-sig")       # (« ; » et BOM : Excel l'ouvre bien)
    (DOSSIER / "familles.txt").write_text("\n".join(requete("SELECT libelle FROM famille ORDER BY rang").libelle), encoding="utf-8")
    vides = n.explication.isna().sum()
    print(f"{FICHIER} : {len(n)} nuances, {vides} sans explication (en haut du fichier).")
    print(f"Familles possibles : {DOSSIER / 'familles.txt'}")


def envoyer():
    t = pd.read_csv(FICHIER, sep=";", dtype=str, encoding="utf-8-sig")
    familles = set(requete("SELECT libelle FROM famille").libelle)
    inconnues = sorted(set(t.famille.dropna()) - familles)
    if inconnues:
        sys.exit(f"Familles inconnues (voir familles.txt) : {', '.join(inconnues)} — rien n'a été envoyé.")
    t = t[t.explication.notna() | t.famille.notna()][["code", "explication", "famille"]]
    mysql(f"""DROP TABLE IF EXISTS tmp_nuance; CREATE TABLE tmp_nuance (code VARCHAR(40) PRIMARY KEY, explication VARCHAR(120),
                famille VARCHAR(40)) {T}""")
    charger("tmp_nuance", t)
    mysql("""UPDATE nuance n JOIN tmp_nuance t ON t.code = n.libelle SET n.explication = coalesce(t.explication, n.explication);
             UPDATE nuance n JOIN tmp_nuance t ON t.code = n.libelle JOIN famille f ON f.libelle = t.famille
               SET n.famille_id = f.id;
             DROP TABLE tmp_nuance""")
    r = requete("SELECT count(*) n, sum(explication IS NULL) sans, sum(famille_id IS NULL) sans_famille FROM nuance")
    print(f"Envoyé : {len(t)} lignes. Il reste {r.sans[0]} nuances sans explication et {r.sans_famille[0]} sans famille.")


if __name__ == "__main__":
    envoyer() if "envoyer" in sys.argv else ecrire()
