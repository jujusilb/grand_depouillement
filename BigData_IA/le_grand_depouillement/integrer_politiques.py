"""
integrer_politiques.py — Les fiches Wikidata des politiques français (BRUT/wikidata/politiques/) comblent les vides de
la base : date et lieu de naissance, date et lieu de décès, identifiant Wikidata, photo (Wikimedia Commons).

    py integrer_politiques.py            les compléments (1 min)
    py integrer_politiques.py --photos   puis les photos des personnes qui n'ont pas de photo officielle (~1 h 45 :
                                         une vignette toutes les 1,5 s ; on peut l'arrêter et le relancer)

Wikidata est une ROUE DE SECOURS : il ne remplace jamais une valeur déjà là (venue d'une source officielle : RNE,
Assemblée, Sénat, Insee…). Il ne fait que remplir les cases vides, et la base garde la trace de qui a rempli quoi
(personne.naissance_source_id, personne.deces_source_id). Les dates qui contredisent la base sont listées dans
conception/wikidata_dates_en_desaccord.csv pour vérification, jamais écrites.

Reconnaître une personne de Wikidata dans la base, dans cet ordre :
  1. son identifiant Wikidata, Assemblée ou Sénat ;
  2. nom + prénom + date de naissance (une seule personne de la base) ;
  3. nom + prénom, quand la base n'a qu'une personne sans date de ce nom ET que ses mandats tombent dans la vie
     de la personne Wikidata (après ses 18 ans, avant sa mort) — sinon deux homonymes seraient confondus.
Les personnes de Wikidata absentes de la base n'y sont pas ajoutées (elles n'y auraient ni mandat ni candidature).

Les dates au 1er janvier ne sont pas reprises : Wikidata écrit ainsi une date dont il ne connaît que l'année.
"""
import glob
import html
import io
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
from PIL import Image

from outils_mariadb import (charger, charger_identifiants, cle, cle_etrangere, lire_identifiants, mysql, requete,
                            sauvegarder, sources, texte_sql)

ICI = Path(__file__).resolve().parent
PROJET = ICI.parent.parent
FICHES = PROJET / "BRUT" / "wikidata" / "politiques"
DECHET = PROJET / "DECHET"
PHOTOS = ICI / "data" / "photos"
DOSSIER_PHOTOS = PHOTOS / "wikimedia"
DESACCORDS = ICI.parent / "conception" / "wikidata_dates_en_desaccord.csv"
ENTETES = {"User-Agent": "LeGrandDepouillement/1.0 (appli d'apprentissage, usage personnel)"}
LARGEUR = 200
WIKIDATA = 3                      # referentiel « Wikidata »


def lien(table, colonne, reference):
    """La clé étrangère, si elle n'est pas déjà posée (le script peut être relancé)."""
    deja = requete(f"""SELECT count(*) n FROM information_schema.table_constraints WHERE table_schema = DATABASE()
                       AND constraint_name = 'fk_{table}_{colonne}'""")
    if deja.n[0] == "0":
        cle_etrangere(table, colonne, reference)


def etape(texte):
    print(f"[{time.strftime('%H:%M:%S')}] {texte}", flush=True)


def date_sure(v):
    """« 1957-01-24T00:00:00Z » → « 1957-01-24 » ; None pour un 1er janvier (Wikidata ne connaît souvent que l'année)."""
    if pd.isna(v) or str(v)[4:10] == "-01-01" or str(v).startswith("-"):
        return None
    return str(v)[:10]


# ------------------------------------------------------------------------------------------------------------------
# 1. Les fiches Wikidata, reconnues dans la base
# ------------------------------------------------------------------------------------------------------------------
def lire_fiches():
    w = pd.concat([pd.read_csv(f, dtype=str) for f in glob.glob(str(FICHES / "*.csv"))
                   if open(f, encoding="utf-8").read(2) == "p,"]).drop_duplicates("p")
    w["q"] = w.p.str.extract(r"(Q\d+)")[0]
    for c in ("naissance", "deces"):   # (« valeur inconnue » de Wikidata : une adresse au lieu d'une date)
        w[c] = w[c].where(w[c].str.match(r"^\d{4}-\d\d-\d\d", na=False))
    for c in ("lieu_naissance", "lieu_deces", "insee_naissance"):
        w[c] = w[c].where(~w[c].str.startswith("http", na=False))
    w["naiss"] = w.naissance.str[:10]
    w["prenom"] = w.prenom.fillna(w.libelle.str.split(" ", n=1).str[0])
    w["nom"] = w.nom.fillna(w.libelle.str.split(" ", n=1).str[1])
    w["cle"] = [cle(n, p) for n, p in zip(w.nom, w.prenom)]
    # (le prénom de Wikidata est celui de l'état civil — « Amélie » Morançais — ; le libellé, celui d'usage — « Christelle »)
    w["cle_usage"] = [cle(n, l.split(" ", 1)[0]) if isinstance(l, str) else None for n, l in zip(w.nom, w.libelle)]
    return w.reset_index(drop=True)


def reconnaitre(w):
    """Ajoute à w : pid (la personne de la base) et comment (comment on l'a reconnue)."""
    p = requete("SELECT id, nom_usage, prenoms, date_naissance FROM personne")
    p["id"] = p.id.astype("int64")
    p["cle"] = [cle(n, x) for n, x in zip(p.nom_usage, p.prenoms)]
    par_id = {(s, v): int(pid) for pid, s, v in lire_identifiants().itertuples(index=False)}
    par_naiss = p.dropna(subset=["date_naissance"]).groupby(["cle", "date_naissance"]).id.agg(list).to_dict()
    sans_date = p[p.date_naissance.isna()].groupby("cle").id.agg(list).to_dict()
    # les années d'activité connues de chaque personne sans date (mandats, nominations, candidatures)
    activite = requete("""SELECT personne_id, min(an) premier, max(an) dernier FROM (
                            SELECT m.personne_id, year(m.date_debut) an FROM mandat m JOIN personne p ON p.id = m.personne_id
                             WHERE p.date_naissance IS NULL AND m.date_debut IS NOT NULL
                            UNION ALL SELECT n.personne_id, year(n.date_debut) FROM nomination n JOIN personne p ON p.id = n.personne_id
                             WHERE p.date_naissance IS NULL AND n.date_debut IS NOT NULL
                            UNION ALL SELECT c.personne_id, year(e.date_t1) FROM candidature c JOIN election e ON e.id = c.election_id
                             JOIN personne p ON p.id = c.personne_id WHERE p.date_naissance IS NULL AND e.date_t1 IS NOT NULL) x
                          GROUP BY personne_id""")
    activite = {int(r.personne_id): (int(r.premier), int(r.dernier)) for r in activite.itertuples(index=False)}

    def dans_sa_vie(pid, r):
        if pid not in activite or pd.isna(r.naiss):
            return False
        premier, dernier = activite[pid]
        mort = int(r.deces[:4]) if pd.notna(r.deces) and not r.deces.startswith("-") else 9999
        return premier >= int(r.naiss[:4]) + 18 and dernier <= mort

    def lier(r):
        if ("Wikidata", r.q) in par_id:
            return par_id[("Wikidata", r.q)], "identifiant Wikidata"
        if pd.notna(r.an) and ("Assemblée nationale", f"PA{r.an}") in par_id:
            return par_id[("Assemblée nationale", f"PA{r.an}")], "identifiant Assemblée"
        if pd.notna(r.senat) and ("Sénat", str(r.senat)[-6:].upper()) in par_id:
            return par_id[("Sénat", str(r.senat)[-6:].upper())], "identifiant Sénat"
        if pd.notna(r.naiss) and len(par_naiss.get((r.cle, r.naiss), [])) == 1:
            return par_naiss[(r.cle, r.naiss)][0], "nom + prénom + naissance"
        if pd.notna(r.naiss) and len(par_naiss.get((r.cle_usage, r.naiss), [])) == 1:
            return par_naiss[(r.cle_usage, r.naiss)][0], "nom + prénom d'usage + naissance"
        if len(sans_date.get(r.cle, [])) == 1:
            pid = sans_date[r.cle][0]
            return (pid, "nom + prénom (mandats dans sa vie)") if dans_sa_vie(pid, r) else (None, "nom seul, non vérifiable")
        return None, "homonymes sans date dans la base" if sans_date.get(r.cle) else "absente de la base"

    res = [lier(r) for r in w.itertuples(index=False)]
    w["pid"] = [x[0] for x in res]
    w["comment"] = [x[1] for x in res]
    # une personne de la base reconnue dans deux fiches Wikidata (doublon de Wikidata) : on ne choisit pas
    doubles = w.dropna(subset=["pid"]).pid.value_counts()
    doubles = set(doubles[doubles > 1].index)
    w.loc[w.pid.isin(doubles), ["pid", "comment"]] = [None, "deux fiches Wikidata pour une personne"]
    return w


# ------------------------------------------------------------------------------------------------------------------
# 2. Les compléments
# ------------------------------------------------------------------------------------------------------------------
def colonnes():
    """Les colonnes qui gardent la trace de Wikidata (sources, commune de naissance) ; lieux élargis aux noms longs."""
    mysql("""ALTER TABLE personne ADD COLUMN IF NOT EXISTS naissance_source_id INT NULL,
                                  ADD COLUMN IF NOT EXISTS deces_source_id INT NULL,
                                  ADD COLUMN IF NOT EXISTS lieu_naissance_id INT NULL,
                                  MODIFY lieu_naissance VARCHAR(80) NULL, MODIFY lieu_deces VARCHAR(80) NULL""")


def complements(w):
    SOURCE = sources(["wikidata"])["wikidata"]
    p = requete("SELECT id, date_naissance, lieu_naissance, date_deces, lieu_deces FROM personne")
    p["id"] = p.id.astype("int64")
    communes = requete("SELECT id commune_id, code insee_naissance FROM zone WHERE niveau_id = 8 AND date_fin IS NULL")   # (8 : commune)
    lies = (w.dropna(subset=["pid"]).astype({"pid": "int64"})
            .merge(p, left_on="pid", right_on="id", suffixes=("", "_base"))
            .merge(communes, on="insee_naissance", how="left"))
    lies["naiss_sure"] = lies.naissance.map(date_sure)
    lies["deces_sur"] = lies.deces.map(date_sure)

    # les désaccords : jamais écrits, listés
    desaccord = lies[lies.date_naissance.notna() & lies.naiss.notna() & (lies.date_naissance != lies.naiss)]
    desaccord[["pid", "q", "libelle", "date_naissance", "naiss", "comment"]].rename(columns={
        "pid": "personne_id", "q": "wikidata", "libelle": "nom", "date_naissance": "naissance_base",
        "naiss": "naissance_wikidata", "comment": "reconnue_par"}).to_csv(DESACCORDS, index=False, encoding="utf-8")
    etape(f"{len(desaccord)} dates de naissance en désaccord → {DESACCORDS.name} (la base garde la sienne)")

    # une ligne par personne : ce que Wikidata apporte là où la base est vide
    t = pd.DataFrame({
        "personne_id": lies.pid,
        "date_naissance": lies.naiss_sure.where(lies.date_naissance.isna()),
        "lieu_naissance": lies.lieu_naissance.where(lies.lieu_naissance_base.isna()).str[:80],
        "lieu_naissance_id": lies.commune_id.where(lies.lieu_naissance_base.isna()),
        "date_deces": lies.deces_sur.where(lies.date_deces.isna()),
        "lieu_deces": lies.lieu_deces.where(lies.lieu_deces_base.isna()).str[:80]})
    t = t.dropna(how="all", subset=t.columns[1:])
    mysql("""DROP TABLE IF EXISTS tmp_wikidata;
             CREATE TABLE tmp_wikidata (personne_id BIGINT PRIMARY KEY, date_naissance DATE, lieu_naissance VARCHAR(80),
                                        lieu_naissance_id INT, date_deces DATE, lieu_deces VARCHAR(80))
             ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
    charger("tmp_wikidata", t)
    # (la source est notée avant de remplir : « la case était vide et Wikidata la remplit »)
    mysql(f"""UPDATE personne p JOIN tmp_wikidata t ON t.personne_id = p.id
              SET p.naissance_source_id = {SOURCE}
              WHERE p.naissance_source_id IS NULL AND ((p.date_naissance IS NULL AND t.date_naissance IS NOT NULL)
                                                    OR (p.lieu_naissance IS NULL AND t.lieu_naissance IS NOT NULL));
              UPDATE personne p JOIN tmp_wikidata t ON t.personne_id = p.id
              SET p.deces_source_id = {SOURCE}
              WHERE p.deces_source_id IS NULL AND ((p.date_deces IS NULL AND t.date_deces IS NOT NULL)
                                                OR (p.lieu_deces IS NULL AND t.lieu_deces IS NOT NULL));
              UPDATE personne p JOIN tmp_wikidata t ON t.personne_id = p.id SET
                p.date_naissance = coalesce(p.date_naissance, t.date_naissance),
                p.lieu_naissance_id = CASE WHEN p.lieu_naissance IS NULL THEN t.lieu_naissance_id ELSE p.lieu_naissance_id END,
                p.lieu_naissance = coalesce(p.lieu_naissance, t.lieu_naissance),
                p.date_deces = coalesce(p.date_deces, t.date_deces),
                p.lieu_deces = coalesce(p.lieu_deces, t.lieu_deces);
              DROP TABLE tmp_wikidata""")
    etape(f"naissances datées : {t.date_naissance.notna().sum()} · lieux de naissance : {t.lieu_naissance.notna().sum()} "
          f"(dont {t.lieu_naissance_id.notna().sum()} communes reliées) · décès : {t.date_deces.notna().sum()} · "
          f"lieux de décès : {t.lieu_deces.notna().sum()}")

    # les identifiants Wikidata (une personne qui en a déjà un autre le garde : à vérifier à la main)
    deja = lire_identifiants()
    deja = deja[deja.source == "Wikidata"]
    a_un_q = set(deja.personne_id.astype("int64"))
    q_pris = set(deja.valeur)
    nouveaux = lies[~lies.pid.isin(a_un_q) & ~lies.q.isin(q_pris)][["pid", "q"]].drop_duplicates()
    if len(nouveaux):
        charger_identifiants(pd.DataFrame({"personne_id": nouveaux.pid, "source": "Wikidata", "valeur": nouveaux.q}))
    etape(f"identifiants Wikidata ajoutés : {len(nouveaux)}")


# ------------------------------------------------------------------------------------------------------------------
# 3. Les photos (Wikimedia Commons) des personnes sans photo officielle
# ------------------------------------------------------------------------------------------------------------------
def lire(url, essais=4):
    for essai in range(essais):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=ENTETES), timeout=60).read()
        except Exception as e:
            if essai == essais - 1:
                raise
            time.sleep(5 * (essai + 1) * (3 if "429" in str(e) else 1))


def sans_balises(texte):
    """L'auteur est donné en HTML (« <a href=…>Jacques Paquier</a> ») : on garde le texte."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", texte or ""))).strip()


def colonnes_photo():
    """photo.licence (texte) → photo.licence_id (table licence) ; photo.auteur pour créditer les photos libres."""
    mysql("""ALTER TABLE photo ADD COLUMN IF NOT EXISTS licence_id INT NULL, ADD COLUMN IF NOT EXISTS auteur VARCHAR(255) NULL,
                               MODIFY fichier VARCHAR(40) NULL, MODIFY adresse VARCHAR(255) NULL""")
    if "licence" in set(requete("SHOW COLUMNS FROM photo").Field):
        senat = licence("Photo officielle du Sénat (usage non commercial, source citée)", "https://www.senat.fr")
        mysql(f"""UPDATE photo SET licence_id = 2 WHERE licence LIKE 'Licence ouverte%';
                  UPDATE photo SET licence_id = {senat} WHERE licence LIKE 'Photo officielle du Sénat%';
                  ALTER TABLE photo DROP COLUMN licence""")
    lien("photo", "licence_id", "licence")


_licences = {}


def licence(libelle, url=None):
    """L'id d'une licence (ajoutée à la table licence si elle n'y est pas). « CC0 » = la CC0 1.0 déjà connue."""
    libelle = {"CC0": "CC0 1.0 (domaine public)", "Public domain": "Domaine public"}.get(libelle, libelle)[:60]
    if not _licences:
        _licences.update({r.libelle.lower(): int(r.id) for r in requete("SELECT id, libelle FROM licence").itertuples()})
    if libelle.lower() not in _licences:
        n = max(_licences.values()) + 1
        mysql(f"INSERT INTO licence (id, libelle, url) VALUES ({n}, {texte_sql(libelle)}, {texte_sql(url)})")
        _licences[libelle.lower()] = n
    return _licences[libelle.lower()]


def photos(w):
    colonnes_photo()
    SOURCE = sources(["photos Wikimedia Commons"])["photos Wikimedia Commons"]
    DOSSIER_PHOTOS.mkdir(parents=True, exist_ok=True)
    # les personnes de la base reconnues, avec une photo sur Wikidata, mais aucune photo dans la base
    ont = set(requete("SELECT DISTINCT personne_id FROM photo_personne").personne_id.astype("int64"))
    a = w.dropna(subset=["pid", "photo"]).astype({"pid": "int64"})
    a = a[~a.pid.isin(ont)].drop_duplicates("pid").copy()
    a["fichier"] = a.photo.map(lambda u: urllib.parse.unquote(u.rsplit("/", 1)[1]))
    etape(f"{len(a)} personnes sans photo dans la base ont une photo sur Wikimedia Commons")

    # les crédits déjà connus (photos des candidats, même dossier d'origine) évitent de redemander
    candidats = PHOTOS / "candidats" / "credits.parquet"
    deja = pd.read_parquet(candidats).drop_duplicates("qid").set_index("qid") if candidats.exists() else pd.DataFrame()

    # 1. auteurs, licences et adresses des vignettes (par paquets de 50 fichiers)
    infos = {}
    fichiers = sorted(set(a.fichier))
    for i in range(0, len(fichiers), 50):
        paquet = fichiers[i:i + 50]
        q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata",
                                    "iiurlwidth": 250, "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl",
                                    "titles": "|".join("File:" + f for f in paquet)})
        r = json.loads(lire("https://commons.wikimedia.org/w/api.php?" + q))
        retour = {n["to"]: n["from"] for n in r["query"].get("normalized", [])}
        for page in r["query"]["pages"].values():
            if "imageinfo" not in page:
                continue
            ii = page["imageinfo"][0]
            meta = ii.get("extmetadata", {})
            nom = retour.get(page["title"], page["title"]).removeprefix("File:")
            infos[nom] = dict(vignette=ii.get("thumburl"), page=ii.get("descriptionurl"),
                              auteur=sans_balises(meta.get("Artist", {}).get("value")) or "auteur inconnu",
                              licence=sans_balises(meta.get("LicenseShortName", {}).get("value")) or "licence libre",
                              url_licence=sans_balises(meta.get("LicenseUrl", {}).get("value")) or None)
        if (i // 50) % 10 == 0:
            etape(f"  crédits : {min(i + 50, len(fichiers))} / {len(fichiers)}")
        time.sleep(0.5)

    # 2. les vignettes (200 px de large, en JPEG) ; celles déjà téléchargées pour les candidats sont recopiées
    lignes, rates, poids = [], [], 0
    for n, r in enumerate(a.itertuples(index=False), 1):
        info = infos.get(r.fichier)
        dest = DOSSIER_PHOTOS / f"{r.q}.jpg"
        if not info or not info["vignette"]:
            rates.append(f"{r.q}\t{r.fichier}\tpas sur Commons")
            continue
        if not dest.exists() and r.q in deja.index and (PHOTOS / "candidats" / f"{r.q}.jpg").exists():
            shutil.copy(PHOTOS / "candidats" / f"{r.q}.jpg", dest)
        if not dest.exists():
            try:
                im = Image.open(io.BytesIO(lire(info["vignette"]))).convert("RGB")
                if im.width > LARGEUR:
                    im = im.resize((LARGEUR, round(im.height * LARGEUR / im.width)), Image.LANCZOS)
                im.save(dest, "JPEG", quality=85)
                time.sleep(1.5)
            except Exception as e:
                rates.append(f"{r.q}\t{r.fichier}\t{e}")
                continue
        poids += dest.stat().st_size
        lignes.append((r.pid, f"wikimedia/{dest.name}", info["page"], info["auteur"][:255],
                       licence(info["licence"], info["url_licence"])))
        if n % 200 == 0:
            etape(f"  photos : {n} / {len(a)} — {poids / 1e6:.0f} Mo")
    (DOSSIER_PHOTOS / "ratees.txt").write_text("\n".join(rates), encoding="utf-8")

    # 3. dans la base : photo (fichier, page Commons, auteur, licence) et photo_personne
    mysql(f"""DELETE pp FROM photo_personne pp JOIN photo ph ON ph.id = pp.photo_id WHERE ph.source_id = {SOURCE};
              DELETE FROM photo WHERE source_id = {SOURCE}""")
    debut = int(requete("SELECT coalesce(max(id), 0) n FROM photo").n[0]) + 1
    t = pd.DataFrame(lignes, columns=["personne_id", "fichier", "adresse", "auteur", "licence_id"])
    t["id"] = range(debut, debut + len(t))
    t["source_id"] = SOURCE
    charger("photo", t[["id", "fichier", "adresse", "auteur", "licence_id", "source_id"]])
    charger("photo_personne", t[["id", "personne_id"]].rename(columns={"id": "photo_id"}))
    etape(f"{len(t)} photos ({poids / 1e6:.0f} Mo) dans {DOSSIER_PHOTOS} · {len(rates)} ratées (ratees.txt)")


if __name__ == "__main__":
    w = reconnaitre(lire_fiches())
    etape(f"{len(w)} fiches Wikidata · reconnues : {w.pid.notna().sum()}\n" + w.comment.value_counts().to_string())
    if "--photos" in sys.argv:
        sauvegarder(DECHET, "photo_avant_wikimedia", ["photo", "photo_personne", "licence"])
        photos(w)
    else:
        sauvegarder(DECHET, "personne_avant_wikidata", ["personne", "identifiant"])
        colonnes()
        complements(w)
        for col in ("naissance_source_id", "deces_source_id"):
            lien("personne", col, "source")
        lien("personne", "lieu_naissance_id", "zone")
    etape("fini")
