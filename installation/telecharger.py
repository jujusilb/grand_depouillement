"""
telecharger.py — Télécharge les sources listées dans sources.csv (adresse officielle → emplacement dans l'installation).

    py telecharger.py            (toutes les phases)
    py telecharger.py 1          (la phase 1 seulement)

Un fichier déjà là, à la bonne taille, n'est pas retéléchargé. Un téléchargement coupé reprend où il s'était arrêté.
"""
import csv
import sys
import time
from pathlib import Path

import requests

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent                         # (le dépôt = le dossier PROJET : ELECTION/, BRUT/, BigData_IA/…)
SOURCES = ICI / "sources.csv"
ENTETE = {"User-Agent": "LeGrandDepouillement/1.0 (installation, donnees electorales ouvertes)"}


def sources(phase=None):
    with open(SOURCES, encoding="utf-8") as f:
        lignes = list(csv.DictReader(f, delimiter=";"))
    return [l for l in lignes if phase is None or l["phase"] == str(phase)]


def taille_lisible(n):
    return f"{n / 1e9:.1f} Go" if n >= 1e9 else f"{n / 1e6:.0f} Mo" if n >= 1e6 else f"{n / 1e3:.0f} Ko"


def telecharger(url, cible, attendue=None, essais=5):
    """Télécharge url dans cible (reprise si le fichier .partiel existe). Rend True si le fichier est complet."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    if cible.exists() and (not attendue or cible.stat().st_size == attendue):
        return True
    partiel = cible.with_name(cible.name + ".partiel")
    for essai in range(1, essais + 1):
        deja = partiel.stat().st_size if partiel.exists() else 0
        entete = dict(ENTETE, **({"Range": f"bytes={deja}-"} if deja else {}))
        try:
            with requests.get(url, headers=entete, stream=True, timeout=60) as r:
                if r.status_code == 416:                      # (déjà tout reçu)
                    break
                r.raise_for_status()
                if deja and r.status_code != 206:             # (le serveur ne sait pas reprendre : on recommence)
                    deja = 0
                total = deja + int(r.headers.get("Content-Length", 0) or 0)
                t0, recu = time.time(), deja
                with open(partiel, "ab" if deja else "wb") as f:
                    for bloc in r.iter_content(1 << 20):
                        f.write(bloc)
                        recu += len(bloc)
                        if total and time.time() - t0 > 2:
                            print(f"\r      {recu * 100 // total:3d} % de {taille_lisible(total)}", end="", flush=True)
                print("\r" + " " * 40 + "\r", end="")
            break
        except requests.RequestException as e:
            print(f"      coupure ({e.__class__.__name__}), essai {essai}/{essais}…")
            time.sleep(5 * essai)
    else:
        return False
    if attendue and partiel.stat().st_size != attendue:
        print(f"      taille inattendue : {partiel.stat().st_size} au lieu de {attendue} (la source a peut-être été mise à jour)")
    partiel.replace(cible)
    return True


def main(phase=None):
    liste = sources(phase)
    manque = [l for l in liste if not (RACINE / l["destination"]).exists()]
    total = sum(int(l["taille"] or 0) for l in manque)
    print(f"   {len(manque)} fichiers à télécharger sur {len(liste)} ({taille_lisible(total)})")
    rates = []
    for i, l in enumerate(liste, 1):
        cible = RACINE / l["destination"]
        if cible.exists():
            continue
        print(f"   [{i}/{len(liste)}] {l['destination']} ({taille_lisible(int(l['taille'] or 0))})")
        if not telecharger(l["url"], cible, int(l["taille"]) if l["taille"] else None):
            rates.append(l["destination"])
    if rates:
        print("   Impossible de télécharger :", *rates, sep="\n      ")
    return not rates


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else None) else 1)
