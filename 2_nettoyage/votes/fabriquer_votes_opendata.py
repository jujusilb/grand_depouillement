"""
fabriquer_votes_opendata.py — Les scrutins publics de l'Assemblée depuis 2012 (législatures 14 à 17), député par député.

    py fabriquer_votes_opendata.py          (~1 min)

Sources (open data de l'Assemblée, data.assemblee-nationale.fr) :
    brut/scrutins_14.json.zip … scrutins_17.json.zip      les scrutins, avec le vote nominatif de chaque député
    ../parlement/brut/amo30/amo30.zip                      les députés (nom) et les groupes (sigle, nom, couleur officielle)
Sorties :
    votes_scrutins_opendata.parquet     un scrutin par ligne (législature, numéro, date, objet, résultat)
    votes_individuels_opendata.parquet  un vote par ligne (scrutin, député, groupe, position : pour / contre / abstention / non-votant,
                                        lieu : sa circonscription)
"""
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

RACINE_DEPOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE_DEPOT))                          # (chemins.py : où est chaque chose)
import chemins as C  # noqa: E402
ICI = C.dossier("votes")
AMO = C.DONNEES / "parlement" / "brut" / "amo30" / "amo30.zip"

# 1. les députés et les groupes
z = zipfile.ZipFile(AMO)
deputes, groupes, circos = {}, {}, {}
for n in z.namelist():
    if "/acteur/" in n:
        a = json.loads(z.read(n))["acteur"]
        i = a["etatCivil"]["ident"]
        uid = a["uid"]["#text"] if isinstance(a["uid"], dict) else a["uid"]
        deputes[uid] = f"{i['prenom']} {i['nom']}"
        mandats = a["mandats"]["mandat"]
        for m in mandats if isinstance(mandats, list) else [mandats]:          # où il a été élu, à chaque législature
            lieu = ((m.get("election") or {}).get("lieu") or {}) if m.get("typeOrgane") == "ASSEMBLEE" else {}
            if lieu.get("numCirco"):
                n = int(lieu["numCirco"])
                circos[(uid, int(m["legislature"]))] = f"{n}{'re' if n == 1 else 'e'} circonscription · {lieu.get('departement', '')}"
    elif "/organe/" in n:
        o = json.loads(z.read(n))["organe"]
        if o.get("codeType") == "GP":
            groupes[o["uid"]] = (o.get("libelleAbrev") or o.get("libelleAbrege"), o.get("libelle"), o.get("couleurAssociee"))
print(f"{len(deputes)} députés, {len(groupes)} groupes")


def liste(x):
    """Le JSON met un seul votant en objet, plusieurs en liste, aucun en null (ou « 0 » dans la 14e législature)."""
    if not x or isinstance(x, str):
        return []
    v = x.get("votant") if isinstance(x, dict) else x
    return v if isinstance(v, list) else [v] if v else []


def scrutins_du_zip(chemin):
    z = zipfile.ZipFile(chemin)
    for n in z.namelist():
        if not n.endswith(".json"):
            continue
        d = json.loads(z.read(n))
        if "scrutins" in d:                                  # 14e législature : un seul gros fichier
            yield from d["scrutins"]["scrutin"]
        else:
            yield d["scrutin"]


lignes_s, lignes_v = [], []
for leg in (14, 15, 16, 17):
    for s in scrutins_du_zip(ICI / "brut" / f"scrutins_{leg}.json.zip"):
        sid = f"AN{leg}-{int(s['numero']):05d}"
        synthese = s.get("syntheseVote") or {}
        dec = synthese.get("decompte") or {}
        titre = (s.get("objet") or {}).get("libelle") or s.get("titre") or ""
        lignes_s.append((sid, leg, int(s["numero"]), s["dateScrutin"][:10], titre.strip(), (s.get("typeVote") or {}).get("libelleTypeVote"),
                         (s.get("sort") or {}).get("code"), int(dec.get("pour") or 0), int(dec.get("contre") or 0),
                         int(dec.get("abstentions") or dec.get("abstention") or 0), "open data de l'Assemblée"))
        organe = ((s.get("ventilationVotes") or {}).get("organe") or {})
        gps = (organe.get("groupes") or {}).get("groupe") or []
        for g in gps if isinstance(gps, list) else [gps]:
            sigle, nom_g, couleur = groupes.get(g["organeRef"], (g["organeRef"], None, None))
            nominatif = (g.get("vote") or {}).get("decompteNominatif") or {}
            # (les noms des clés changent : « pours » depuis 2017, « pour » dans la 14e législature)
            for cles, position in ((("pours", "pour"), "pour"), (("contres", "contre"), "contre"), (("abstentions", "abstention"), "abstention"), (("nonVotants", "nonVotant"), "non-votant")):
                for v in [x for cle in cles for x in liste(nominatif.get(cle))]:
                    lignes_v.append((sid, v["acteurRef"], deputes.get(v["acteurRef"], v["acteurRef"]), sigle, nom_g, couleur, position,
                                     circos.get((v["acteurRef"], leg))))
    print(f"  législature {leg} : {sum(1 for x in lignes_s if x[1] == leg)} scrutins", flush=True)

s = pd.DataFrame(lignes_s, columns=["scrutin", "legislature", "numero", "date", "objet", "type_vote", "sort", "pour", "contre", "abstention", "source"])
s["date"] = pd.to_datetime(s["date"])
v = pd.DataFrame(lignes_v, columns=["scrutin", "acteur", "depute", "groupe", "groupe_libelle", "couleur", "position", "lieu"])
s.to_parquet(ICI / "votes_scrutins_opendata.parquet", index=False)
v.to_parquet(ICI / "votes_individuels_opendata.parquet", index=False)
print(f"{len(s):,} scrutins · {len(v):,} votes individuels · députés sans nom : {(v['depute'] == v['acteur']).sum()}".replace(",", " "))
