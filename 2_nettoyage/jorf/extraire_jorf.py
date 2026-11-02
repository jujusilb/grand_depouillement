"""
extraire_jorf.py — Met de côté, dans les archives du Journal officiel (PROJET/BRUT/jorf, données ouvertes de la DILA),
les articles utiles au Grand Dépouillement, sans rien décompresser sur le disque.

    py extraire_jorf.py          → jorf_articles.parquet (ici)

Un article retenu = un article dont le TITRE du texte parle de :
    gouvernement   composition du Gouvernement, nomination du Premier ministre
    prefet         nomination d'un préfet ou d'une préfète (pas les sous-préfets)
    ecole          élèves de l'ENA, de l'INSP, des IRA, de l'École polytechnique (admission, classement, titularisation)
    grand_corps    nominations au Conseil d'État, à la Cour des comptes, à l'Inspection générale des finances,
                   au Conseil constitutionnel
Les archives quotidiennes complètent l'archive globale (juillet 2025) : un même article peut y revenir, on garde
la dernière version lue.
"""
import html
import re
import sys
import tarfile
import time
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("jorf")
JORF = C.BRUT / "jorf"
SORTIE = ICI / "jorf_articles.parquet"

FAMILLES = {  # famille → motif cherché dans le titre du texte (sans tenir compte des majuscules)
    "gouvernement": r"relatif à la composition du gouvernement|portant nomination du premier ministre",
    "prefet": r"portant nomination (?:du |de la |d'un |d'une )?(?:préfet|préfète)(?! de police adjoint)",
    "ecole": r"(?:école nationale d'administration|institut national du service public|instituts? régiona(?:l|ux) "
             r"d'administration|école polytechnique).*(?:élèves|admis|admission|classement|titularis|nomination et affectation)"
             r"|(?:élèves|admis|admission|classement|titularis).*(?:école nationale d'administration|institut national du "
             r"service public|instituts? régiona(?:l|ux) d'administration|école polytechnique)",
    "grand_corps": r"(?:nomination|nommé|titularisation|promotion|intégration).*(?:au conseil d'etat|au conseil d'état|"
                   r"à la cour des comptes|inspection générale des finances|membre du conseil constitutionnel)",
}
MOTIFS = {f: re.compile(m, re.IGNORECASE) for f, m in FAMILLES.items()}


def texte_brut(xml):
    """Le contenu d'un article, sans balises, avec un saut de ligne à chaque <br/> ou paragraphe."""
    contenu = re.search(r"<BLOC_TEXTUEL>\s*<CONTENU>(.*?)</CONTENU>", xml, re.S)
    if not contenu:
        return ""
    t = re.sub(r"<br\s*/?>|</p>", "\n", contenu[1])
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def extraire():
    debut = time.time()
    archives = sorted(JORF.glob("*.tar.gz"), key=lambda p: (not p.name.startswith("Freemium"), p.name))
    lignes = {}
    for n, archive in enumerate(archives, 1):
        with tarfile.open(archive) as t:
            for m in t:
                if not m.isfile() or "/article/" not in m.name:
                    continue
                xml = t.extractfile(m).read().decode("utf-8", "replace")
                titre = re.search(r"<TITRE_TXT[^>]*>(.*?)</TITRE_TXT>", xml, re.S)
                if not titre:
                    continue
                titre = html.unescape(titre[1]).strip()
                famille = next((f for f, motif in MOTIFS.items() if motif.search(titre)), None)
                if not famille:
                    continue
                texte = re.search(r'<TEXTE cid="([^"]+)" date_publi="([^"]*)" date_signature="([^"]*)" nature="([^"]*)"', xml)
                ident = re.search(r"<ID>(JORFARTI\d+)</ID>", xml)[1]
                num = re.search(r"<NUM>([^<]*)</NUM>", xml)
                lignes[ident] = {"article": ident, "texte": texte[1], "date_publi": texte[2], "date_signature": texte[3],
                                 "nature": texte[4], "titre": titre, "famille": famille, "num": num[1] if num else None,
                                 "contenu": texte_brut(xml), "archive": archive.name}
        print(f"[{time.time() - debut:6.0f} s] {n}/{len(archives)} {archive.name} — {len(lignes)} articles retenus", flush=True)
    t = pd.DataFrame(lignes.values())
    t.to_parquet(SORTIE, index=False)
    print(t.groupby("famille").agg(articles=("article", "size"), textes=("texte", "nunique"),
                                   de=("date_publi", "min"), a=("date_publi", "max")).to_string())


if __name__ == "__main__":
    sys.exit(extraire())
