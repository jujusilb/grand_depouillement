"""
normaliser_libelles.py — Un seul mot pour les noms dans tout le schéma : libelle (plus de « label »).

    py normaliser_libelles.py          (MariaDB de XAMPP démarré ; relançable)

Lancé par normaliser_references.py. fonction, mode_scrutin, motif_debut, motif_fin : label → libelle ;
liste : label → libelle, label_abrege → libelle_abrege.
"""
from outils_mariadb import mysql, requete

RENOMMER = [("fonction", "label", "libelle"), ("mode_scrutin", "label", "libelle"), ("motif_debut", "label", "libelle"),
            ("motif_fin", "label", "libelle"), ("liste", "label", "libelle"), ("liste", "label_abrege", "libelle_abrege")]


def libelles(con=None):
    faits = []
    for table, ancien, nouveau in RENOMMER:
        c = requete(f"""SELECT column_type, is_nullable FROM information_schema.columns WHERE table_schema = DATABASE()
                        AND table_name = '{table}' AND column_name = '{ancien}'""")
        if not len(c):
            continue
        # (MariaDB 10.4 de XAMPP : pas de RENAME COLUMN, on redonne le type)
        mysql(f"ALTER TABLE `{table}` CHANGE `{ancien}` `{nouveau}` {c.column_type[0]} {'NULL' if c.is_nullable[0] == 'YES' else 'NOT NULL'}")
        faits.append(f"{table}.{ancien}")
    print("libellés : " + (", ".join(faits) + " → libelle" if faits else "déjà renommés"), flush=True)


if __name__ == "__main__":
    libelles()
