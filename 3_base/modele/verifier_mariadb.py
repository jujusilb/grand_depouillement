"""
verifier_mariadb.py — Vérifie de fond en comble la base MariaDB grand_depouillement (le modèle « personnes et mandats »).

    py verifier_mariadb.py

Chaque contrôle affiche « ok » ou le nombre de lignes en défaut, avec un exemple. Rien n'est modifié.
    1. les liens : aucune ligne ne pointe vers une ligne qui n'existe pas (toutes les clés étrangères)
    2. les identités : aucune colonne nom / prénom / naissance / photo en dehors de la table personne
    3. les mandats : pas de fin avant le début, pas de doublon, les effectifs en cours sont plausibles
    4. les règles de cumul (table incompatibilite) : combien de personnes les enfreignent aujourd'hui
    5. l'encodage : pas d'accent abîmé (« Ã© » au lieu de « é », « ? » au lieu d'une lettre)
"""
import exporter_mariadb as mx

BASE = "grand_depouillement"
defauts = 0


def valeur(sql):
    return mx.mysql(sql, base=BASE).strip().split("\n")[1:]


def controle(titre, sql_compte, sql_exemple=None, attendu=0):
    """Affiche le contrôle ; un écart à « attendu » compte comme un défaut."""
    global defauts
    n = int(valeur(sql_compte)[0])
    ok = n == attendu if isinstance(attendu, int) else attendu(n)
    print(f"  {'ok ' if ok else '⚠  '} {titre:70s} {n:>10,}".replace(",", " "))
    if not ok:
        defauts += 1
        if sql_exemple:
            for ligne in valeur(sql_exemple)[:3]:
                print(f"        ex. {ligne[:150]}")


print("1. Les liens (clés étrangères)")
fks = [l.split("\t") for l in valeur(f"""SELECT table_name, column_name, referenced_table_name, referenced_column_name
                                         FROM information_schema.key_column_usage
                                         WHERE table_schema = '{BASE}' AND referenced_table_name IS NOT NULL ORDER BY 1, 2""")]
for t, c, rt, rc in fks:
    controle(f"{t}.{c} → {rt}", f"SELECT count(*) FROM `{t}` x LEFT JOIN `{rt}` r ON r.`{rc}` = x.`{c}` WHERE x.`{c}` IS NOT NULL AND r.`{rc}` IS NULL",
             f"SELECT x.`{c}` FROM `{t}` x LEFT JOIN `{rt}` r ON r.`{rc}` = x.`{c}` WHERE x.`{c}` IS NOT NULL AND r.`{rc}` IS NULL LIMIT 3")
print(f"   ({len(fks)} clés étrangères)")

print("2. Les identités : seulement dans personne")
LIEUX = "AND table_name NOT IN ('contour')"
controle("colonnes nom / prénom / naissance… hors de personne (noms de lieux exceptés)",
         f"""SELECT count(*) FROM information_schema.columns WHERE table_schema = '{BASE}' AND table_name <> 'personne' {LIEUX}
             AND column_name IN ('nom', 'prenom', 'prenoms', 'naissance', 'date_naissance', 'sexe', 'civ', 'depute', 'photo', 'acteur')""",
         f"""SELECT concat(table_name, '.', column_name) FROM information_schema.columns WHERE table_schema = '{BASE}' AND table_name <> 'personne' {LIEUX}
             AND column_name IN ('nom', 'prenom', 'prenoms', 'naissance', 'date_naissance', 'sexe', 'civ', 'depute', 'photo', 'acteur')""")
controle("personnes sans nom", "SELECT count(*) FROM personne WHERE nom_usage IS NULL OR nom_usage = ''")

print("2 bis. Les territoires (une seule table zone : la clé étrangère dit que la zone existe, pas qu'elle est du bon niveau)")
for t, c, niveau in [("commune", "id", 8), ("commune", "epci_id", 7), ("bureau", "id", 12), ("bureau", "canton_id", 6),
                     ("bureau", "circonscription_id", 5)]:
    controle(f"{t}.{c} : une zone du bon niveau", f"""SELECT count(*) FROM {t} x JOIN zone z ON z.id = x.{c} WHERE z.niveau_id <> {niveau}""",
             f"""SELECT x.{c}, z.niveau_id, z.code FROM {t} x JOIN zone z ON z.id = x.{c} WHERE z.niveau_id <> {niveau} LIMIT 3""")
controle("communes de zone sans ligne dans commune (ou l'inverse)",
         """SELECT (SELECT count(*) FROM zone z WHERE z.niveau_id = 8 AND NOT EXISTS (SELECT 1 FROM commune c WHERE c.id = z.id))
                 + (SELECT count(*) FROM zone z WHERE z.niveau_id = 12 AND NOT EXISTS (SELECT 1 FROM bureau b WHERE b.id = z.id)) n""")
controle("zones dont le parent n'est pas d'un niveau au-dessus",
         """SELECT count(*) FROM zone z JOIN zone p ON p.id = z.parent_id JOIN niveau nz ON nz.id = z.niveau_id
            WHERE p.niveau_id = z.niveau_id""",
         """SELECT z.id, z.code, p.code FROM zone z JOIN zone p ON p.id = z.parent_id WHERE p.niveau_id = z.niveau_id LIMIT 3""")

print("3. Les mandats")
controle("mandats qui finissent avant de commencer", "SELECT count(*) FROM mandat WHERE date_fin < date_debut",
         "SELECT id, personne_id, fonction_id, date_debut, date_fin FROM mandat WHERE date_fin < date_debut LIMIT 3")
controle("mandats en double (même personne, fonction, territoire, élection, début)",
         """SELECT count(*) FROM (SELECT 1 FROM mandat WHERE personne_id IS NOT NULL
            GROUP BY personne_id, fonction_id, zone_id, scrutin_id, date_debut, date_fin HAVING count(*) > 1) d""",
         """SELECT personne_id, fonction_id, zone_id, scrutin_id, date_debut, count(*) FROM mandat WHERE personne_id IS NOT NULL
            GROUP BY personne_id, fonction_id, zone_id, scrutin_id, date_debut, date_fin HAVING count(*) > 1 LIMIT 3""")
controle("mandats finis sans motif de fin", "SELECT count(*) FROM mandat WHERE date_fin IS NOT NULL AND motif_fin_id IS NULL")
for f, mini, maxi in [("député", 560, 577), ("sénateur", 330, 348), ("président du Sénat", 1, 1),
                      ("président de la République", 1, 1), ("maire", 34000, 35500),
                      ("conseiller municipal", 480000, 520000), ("conseiller régional", 1700, 1950),
                      ("conseiller départemental", 3900, 4110)]:
    controle(f"{f}s en exercice (attendu {mini} à {maxi})",
             f"""SELECT count(*) FROM mandat m JOIN fonction f ON f.id = m.fonction_id
                 WHERE f.libelle = '{f}' AND m.date_fin IS NULL AND m.motif_fin_id IS NULL""", attendu=lambda n, a=mini, b=maxi: a <= n <= b)
controle("personnes sans mandat, candidature, nomination, formation ni gouvernement",
         """SELECT count(*) FROM personne p WHERE NOT EXISTS (SELECT 1 FROM mandat m WHERE m.personne_id = p.id)
            AND NOT EXISTS (SELECT 1 FROM candidature c WHERE c.personne_id = p.id)
            AND NOT EXISTS (SELECT 1 FROM nomination n WHERE n.personne_id = p.id)
            AND NOT EXISTS (SELECT 1 FROM formation f WHERE f.personne_id = p.id)
            AND NOT EXISTS (SELECT 1 FROM gouvernement g WHERE p.id IN (g.premier_ministre_id, g.chef_etat_id))""")
controle("mandats sans source", "SELECT count(*) FROM mandat m WHERE NOT EXISTS (SELECT 1 FROM mandat_source s WHERE s.mandat_id = m.id)")
controle("nominations qui finissent avant de commencer", "SELECT count(*) FROM nomination WHERE date_fin < date_debut")
controle("formations qui finissent avant de commencer", "SELECT count(*) FROM formation WHERE annee_sortie < annee_entree")
controle("gouvernements sans Premier ministre ou sans chef de l'État",
         "SELECT count(*) FROM gouvernement WHERE premier_ministre_id IS NULL OR chef_etat_id IS NULL")
controle("membres du gouvernement sans gouvernement",
         """SELECT count(*) FROM nomination n JOIN poste p ON p.id = n.poste_id
            WHERE (p.fonction_id = 18 OR p.fonction_id BETWEEN 24 AND 31) AND p.fonction_id <> 29 AND n.gouvernement_id IS NULL""")
controle("gouvernements en place aujourd'hui (attendu 1)", "SELECT count(*) FROM gouvernement WHERE date_fin IS NULL",
         attendu=lambda n: n == 1)
controle("photos liées à un mandat ET à une candidature", "SELECT count(*) FROM photo WHERE mandat_id IS NOT NULL AND candidature_id IS NOT NULL")
controle("photos libres sans auteur ou sans licence",
         """SELECT count(*) FROM photo ph JOIN source s ON s.id = ph.source_id
            WHERE s.cle = 'photos Wikimedia Commons' AND (ph.auteur IS NULL OR ph.licence_id IS NULL)""")
controle("parents nés moins de 12 ans avant leur enfant (ou après)",
         """SELECT count(*) FROM lien l JOIN personne a ON a.id = l.personne_id JOIN personne b ON b.id = l.autre_id
            WHERE l.type_lien_id = 3 AND b.date_naissance < a.date_naissance + INTERVAL 12 YEAR""")

print("4. Les règles de cumul en vigueur (information : un élu a un mois pour choisir, le RNE ne suit pas toujours)")
for a, b, texte in [l.split("\t") for l in valeur("""SELECT i.fonction_a_id, i.fonction_b_id, concat(fa.libelle, ' + ', fb.libelle)
                                                   FROM incompatibilite i JOIN fonction fa ON fa.id = i.fonction_a_id
                                                   JOIN fonction fb ON fb.id = i.fonction_b_id WHERE i.fin_vigueur IS NULL""")]:
    controle(texte, attendu=lambda n: True, sql_compte=f"""SELECT count(DISTINCT a.personne_id) FROM mandat a JOIN mandat b ON b.personne_id = a.personne_id
                        WHERE a.fonction_id = {a} AND b.fonction_id = {b} AND a.date_fin IS NULL AND a.motif_fin_id IS NULL
                          AND b.date_fin IS NULL AND b.motif_fin_id IS NULL""",
             sql_exemple=f"""SELECT p.prenoms, p.nom_usage, a.zone_id, b.zone_id FROM mandat a JOIN mandat b ON b.personne_id = a.personne_id
                 JOIN personne p ON p.id = a.personne_id WHERE a.fonction_id = {a} AND b.fonction_id = {b}
                 AND a.date_fin IS NULL AND a.motif_fin_id IS NULL AND b.date_fin IS NULL AND b.motif_fin_id IS NULL LIMIT 3""")

print("5. L'encodage")
# (les séquences d'un accent lu dans le mauvais encodage, comparées octet par octet : « â » ou « Â » sont de vraies lettres)
ABIME = "REGEXP BINARY 'Ã©|Ã¨|Ãª|Ã«|Ã§|Ã´|Ã®|Ã¯|Ã¢|Ã¹|Ã»|Ã‰|Ã€|[?]'"
controle("noms ou prénoms avec un accent abîmé (« Ã© » pour « é », « ? »)",
         f"SELECT count(*) FROM personne WHERE concat(nom_usage, prenoms) {ABIME}",
         f"SELECT id, nom_usage, prenoms FROM personne WHERE concat(nom_usage, prenoms) {ABIME} LIMIT 3")
ABIME_LISTE = ABIME.replace("|[?]", "")          # (« Ensemble : pourquoi pas ? » : un vrai point d'interrogation)
controle("libellés de liste avec un accent abîmé", f"SELECT count(*) FROM liste WHERE libelle {ABIME_LISTE}",
         f"SELECT id, libelle FROM liste WHERE libelle {ABIME_LISTE} LIMIT 3")

print()
print("Aucun défaut." if not defauts else f"{defauts} contrôle(s) en défaut : voir les ⚠ ci-dessus.")
