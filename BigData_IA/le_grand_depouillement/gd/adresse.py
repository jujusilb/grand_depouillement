"""Trouver le bureau de vote d'une adresse — sans internet.

data/adresses.parquet (fabriqué par preparer_donnees.py depuis PROJET/election/table-adresses-reu.csv) contient
les 16 millions d'adresses du répertoire électoral unique (REU), leur position et LEUR bureau de vote officiel.
On cherche les adresses qui contiennent tous les mots tapés (sans accents, « st » = « saint »).
"""
from gd import donnees as d

FICHIER = d.DOSSIER / "data" / "adresses.parquet"


def disponible():
    return FICHIER.exists()


def chercher_adresse(texte, n=8):
    """Les adresses qui contiennent tous les mots tapés : liste de dict(label, lon, lat, commune, bureau)."""
    mots = d.normaliser(texte).split()
    if not mots or not disponible():
        return []
    cond, params = [], []
    for i, m in enumerate(mots):
        cond.append("norme LIKE ?")
        params.append(f"{m} %" if i == 0 and m.isdigit() else f"%{m}%")      # « 12 … » : le numéro de la rue
    r = d.sql(f"""SELECT adresse, lon, lat, code_commune, id_brut_miom FROM '{FICHIER.as_posix()}'
                  WHERE {' AND '.join(cond)} ORDER BY length(adresse), adresse LIMIT {int(n)}""", params)
    return [{"label": a, "lon": lon, "lat": lat, "commune": c, "bureau": b} for a, lon, lat, c, b in r.itertuples(index=False)]
