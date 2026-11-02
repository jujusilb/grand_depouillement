"""Les photos libres des candidats (Wikimedia Commons, via Wikidata), avec leur auteur et leur licence.

Photos dans data/photos/candidats/<qid>.jpg et la liste dans data/photos/candidats/credits.parquet
(fabriqués par donnees_contexte/photos_wikidata/ : chercher_wikidata.py → choisir.py → telecharger_photos.py).
Une photo libre se montre TOUJOURS avec son auteur et sa licence.
"""
import re
import unicodedata
from functools import lru_cache

import pandas as pd

from gd import donnees as d

DOSSIER = d.DOSSIER / "data" / "photos" / "candidats"


def _cle(texte):
    """« Jean-Luc MÉLENCHON » et « Jean-Luc MELENCHON » → la même clé."""
    t = unicodedata.normalize("NFD", str(texte).upper())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").replace("-", " ").split())


@lru_cache(maxsize=1)
def _credits():
    try:
        t = pd.read_parquet(DOSSIER / "credits.parquet")
    except (OSError, FileNotFoundError):
        return {}
    return {_cle(r.candidat): r._asdict() for r in t.itertuples(index=False)}


def personnes(qui):
    """Les personnes d'un « qui » de la base : « Jean-Luc MÉLENCHON » → [« Jean-Luc MÉLENCHON »] ;
    un binôme « M. DUPONT Jean et Mme DURAND Anne » → [« Jean DUPONT », « Anne DURAND »]."""
    qui = str(qui).strip()
    morceaux = qui.split(" et ") if re.match(r"^(M\.|Mme)", qui) else [qui]
    gens = []
    for m in morceaux:
        mots = re.sub(r"^(M\.|Mme)\s+", "", m.strip()).split()
        nom = [x for x in mots if x.upper() == x and any(c.isalpha() for c in x) and len(x) > 1]
        prenom = [x for x in mots if x not in nom]
        if nom and prenom:
            gens.append(" ".join(prenom) + " " + " ".join(nom))
    return gens


def photo(qui):
    """Les photos des personnes de ce « qui » : liste de dict (candidat, chemin, auteur, licence, page) — vide si aucune."""
    r = []
    for p in personnes(qui):
        c = _credits().get(_cle(p))
        if c and (DOSSIER / c["fichier"]).exists():
            r.append({**c, "chemin": DOSSIER / c["fichier"]})
    return r


def photo_nom(nom):
    """La photo d'une personne écrite « Prénom Nom » (sans NOM en capitales, comme dans les votes des députés), ou None."""
    c = _credits().get(_cle(nom))
    return {**c, "chemin": DOSSIER / c["fichier"]} if c and (DOSSIER / c["fichier"]).exists() else None


def disponible():
    return bool(_credits())
