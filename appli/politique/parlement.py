"""Le Parlement d'aujourd'hui : députés et sénateurs en exercice, leurs groupes, leurs photos (trombinoscope).

Données : le modèle « personnes et mandats » (MariaDB, lu dans l'instantané modele.*) — les mandats de député et de sénateur
en cours, la personne, son groupe (mandat_groupe → groupe), sa photo (photo, photo_personne) ; les fichiers des photos sont dans
data/photos/an/ et data/photos/senat/ (photos officielles de l'Assemblée nationale et du Sénat).
"""
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from lecture import donnees as d

DOSSIER_PHOTOS = d.DATA / "photos"
PLACES_ASSEMBLEE = 650          # numéros de places de l'hémicycle (1 = tout à droite … 650 = tout à gauche)

# L'ordre de gauche à droite et les couleurs des groupes (Assemblée : couleurs officielles, lues dans les données)
ORDRE_AN = ["LFI-NFP", "GDR", "ECOS", "SOC", "LIOT", "DEM", "EPR", "HOR", "DR", "UDDPLR", "RN", "NI"]
# (Sénat : l'ordre de gauche à droite ; le nom complet et la couleur sont recopiés une fois pour toutes dans la table
#  groupe par normaliser_references.py, d'où l'appli les lit)
GROUPES_SENAT = {   # abréviation : (nom complet, couleur), de gauche à droite
    "CRCE-K": ("Communiste, Républicain, Citoyen, Écologiste – Kanaky", "#C00D0D"),
    "GEST": ("Écologiste – Solidarité et Territoires", "#77AA79"),
    "SER": ("Socialiste, Écologiste et Républicain", "#F07AA8"),
    "RDPI": ("Rassemblement des démocrates, progressistes et indépendants", "#7B4591"),
    "RDSE": ("Rassemblement démocratique et social européen", "#F07E26"),
    "UCI": ("Union Centriste", "#3FA9F5"),
    "Les Indépendants": ("Les Indépendants – République et Territoires", "#B5E2F9"),
    "Les Républicains": ("Les Républicains", "#0055A4"),
    "UNT": ("Union nationale des territoires (RN)", "#313567"),
    "NI": ("Non inscrits", "#8D949A"),
}


def disponible():
    try:
        d.sql("SELECT 1 FROM modele.mandat LIMIT 1")
        return True
    except Exception:
        return False


def age(naissance):
    try:
        n = date.fromisoformat(str(naissance)[:10])
        t = date.today()
        return t.year - n.year - ((t.month, t.day) < (n.month, n.day))
    except ValueError:
        return None


def _photos(source):
    """La photo officielle de chaque personne (une par personne) pour une source : Assemblée nationale, Sénat."""
    return f"""(SELECT pp.personne_id, any_value(ph.fichier) fichier, any_value(ph.adresse) adresse FROM modele.photo ph
               JOIN modele.source s ON s.id = ph.source_id AND s.cle = 'photos {source}'
               JOIN modele.photo_personne pp ON pp.photo_id = ph.id GROUP BY 1)"""


@lru_cache(maxsize=1)
def deputes():
    """Les députés en exercice : un mandat de député en cours, la personne, son groupe aujourd'hui, sa place, sa photo."""
    t = d.sql(f"""
        SELECT p.id personne_id, an.valeur id, CASE p.sexe WHEN 'F' THEN 'Mme' ELSE 'M.' END civ, p.prenoms prenom, p.nom_usage nom,
               p.date_naissance naissance, m.metier profession, g.code groupe, g.libelle groupe_libelle, g.couleur, m.siege place,
               zd.libelle departement, zd.code num_departement, CAST(split_part(z.code, '-', 2) AS INTEGER) circo,
               zr.libelle region, ph.fichier photo
        FROM modele.mandat m JOIN modele.fonction f ON f.id = m.fonction_id AND f.libelle = 'député'
        JOIN modele.personne p ON p.id = m.personne_id
        LEFT JOIN (modele.identifiant an JOIN modele.referentiel ran ON ran.id = an.referentiel_id
                   AND ran.libelle = 'Assemblée nationale') ON an.personne_id = p.id
        LEFT JOIN (SELECT DISTINCT ON (a.mandat_id) a.mandat_id, gr.code, gr.libelle, gr.couleur
                   FROM modele.mandat_groupe a JOIN modele.groupe gr ON gr.id = a.groupe_id WHERE a.date_fin IS NULL
                   ORDER BY a.mandat_id, a.date_debut DESC) g ON g.mandat_id = m.id
        LEFT JOIN modele.zone z ON z.id = m.zone_id          -- (la circonscription → son département → sa région)
        LEFT JOIN modele.zone zd ON zd.id = z.parent_id LEFT JOIN modele.zone zr ON zr.id = zd.parent_id
        LEFT JOIN {_photos('Assemblée nationale')} ph ON ph.personne_id = p.id
        WHERE m.date_fin IS NULL AND m.motif_fin_id IS NULL""")
    t["rang"] = t["groupe"].map({g: i for i, g in enumerate(ORDRE_AN)}).fillna(len(ORDRE_AN))
    t["lieu"] = t["departement"].fillna("") + " – " + t["circo"].fillna("").astype(str) + "e circ."
    t["couleur"] = t["couleur"].fillna("#8D949A")
    return t


@lru_cache(maxsize=1)
def senateurs():
    """Les sénateurs en exercice : mandat de sénateur en cours, la personne, son groupe, sa fonction au bureau, sa photo."""
    t = d.sql(f"""
        SELECT p.id personne_id, se.valeur matricule, CASE p.sexe WHEN 'F' THEN 'Mme' ELSE 'M.' END civ, p.prenoms prenom,
               p.nom_usage nom, p.date_naissance naissance, gr.code groupe, gr.libelle groupe_libelle, gr.couleur,
               z.libelle circonscription,
               m.metier profession, b.fonction, ph.fichier photo, ph.adresse adresse_photo
        FROM modele.mandat m JOIN modele.fonction f ON f.id = m.fonction_id AND f.libelle = 'sénateur'
        JOIN modele.personne p ON p.id = m.personne_id
        LEFT JOIN (modele.identifiant se JOIN modele.referentiel rse ON rse.id = se.referentiel_id
                   AND rse.libelle = 'Sénat') ON se.personne_id = p.id
        LEFT JOIN modele.mandat_groupe g ON g.mandat_id = m.id
        LEFT JOIN modele.groupe gr ON gr.id = g.groupe_id
        LEFT JOIN modele.zone z ON z.id = m.zone_id
        LEFT JOIN (SELECT mb.personne_id, upper(left(fb.libelle, 1)) || substr(fb.libelle, 2) fonction FROM modele.mandat mb
                   JOIN modele.fonction fb ON fb.id = mb.fonction_id WHERE fb.libelle LIKE '% du Sénat'
                   AND mb.date_fin IS NULL AND mb.motif_fin_id IS NULL) b ON b.personne_id = p.id
        LEFT JOIN {_photos('Sénat')} ph ON ph.personne_id = p.id
        WHERE m.date_fin IS NULL AND m.motif_fin_id IS NULL""")
    ordre = list(GROUPES_SENAT)
    t["rang"] = t["groupe"].map({g: i for i, g in enumerate(ordre)}).fillna(len(ordre))
    t["groupe_libelle"] = t["groupe_libelle"].fillna(t["groupe"])
    t["couleur"] = t["couleur"].fillna("#8D949A")
    t["lieu"] = t["circonscription"]
    return t


def de_la_zone(t, zone, chambre):
    """Les élus de la zone choisie (département ou plus petit) ; toute la chambre sinon."""
    if zone.niveau in ("france", "region"):
        return t, False
    dep = zone.code if zone.niveau == "departement" else d.ou_est(zone)["dp"]
    if chambre == "Assemblée nationale":
        garde = t["num_departement"].astype(str).str.zfill(2) == str(dep)
    else:
        garde = t["circonscription"] == d.nom_zone("departement", dep)
    return t[garde], True


# --- Le trombinoscope : une seule image (une vignette par élu), puis on la montre et on la clique ----
VIGNETTE, LEGENDE = 96, 46


def _police(taille, gras=False):
    for nom in (["segoeuib.ttf"] if gras else []) + ["segoeui.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def _photo(chemin):
    try:
        im = Image.open(DOSSIER_PHOTOS / chemin).convert("RGB")
    except (OSError, FileNotFoundError):
        return Image.new("RGB", (VIGNETTE, VIGNETTE), (230, 230, 236))
    c = min(im.size)
    im = im.crop(((im.width - c) // 2, 0, (im.width - c) // 2 + c, c))
    return im.resize((VIGNETTE, VIGNETTE), Image.LANCZOS)


def mosaique(t, colonnes):
    """L'image du trombinoscope : photo, bandeau de la couleur du groupe, nom. Renvoie (image, ids dans l'ordre)."""
    t = t.sort_values(["rang", "nom", "prenom"])
    largeur, hauteur = VIGNETTE + 22, VIGNETTE + LEGENDE + 10
    lignes = max(1, -(-len(t) // colonnes))
    im = Image.new("RGB", (colonnes * largeur, lignes * hauteur), "white")
    dessin = ImageDraw.Draw(im)
    p_nom, p_groupe = _police(12, gras=True), _police(11)
    for i, (_, e) in enumerate(t.iterrows()):
        x, y = (i % colonnes) * largeur + 11, (i // colonnes) * hauteur + 4
        im.paste(_photo(e["photo"]), (x, y))
        dessin.rectangle([x, y + VIGNETTE, x + VIGNETTE - 1, y + VIGNETTE + 5], fill=e["couleur"])
        nom = f"{e['prenom']} {e['nom']}"
        lignes_nom = [nom] if dessin.textlength(nom, font=p_nom) <= VIGNETTE + 18 else [e["prenom"], e["nom"]]
        for k, l in enumerate(lignes_nom[:2]):
            while dessin.textlength(l, font=p_nom) > VIGNETTE + 18 and len(l) > 4:
                l = l[:-2] + "…"
            dessin.text((x + VIGNETTE / 2, y + VIGNETTE + 8 + 14 * k), l, font=p_nom, fill=(22, 22, 22), anchor="ma")
        dessin.text((x + VIGNETTE / 2, y + VIGNETTE + 8 + 14 * len(lignes_nom[:2])), str(e["groupe"]), font=p_groupe,
                    fill=(110, 110, 110), anchor="ma")
    return np.asarray(im), list(t.index), (largeur, hauteur, colonnes)
