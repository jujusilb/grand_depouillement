r"""
installateur.py — La fenêtre d'installation du Grand Dépouillement : chaque étape expliquée, une barre verte qui avance,
le temps qui reste. Ouverte par demarrer.bat (lui-même lancé par INSTALLMOI.bat), avec le Python de l'ordinateur :
elle n'utilise que la bibliothèque standard (tkinter), puisque les bibliothèques de l'appli ne sont pas encore là.

    pythonw installateur.py <dossier d'installation>

Le dossier d'installation contient à la fin : appli\ (l'appli et ses données), outils\ (env\ : le Python de l'appli,
depot\ : le code, tmp\ : les fichiers temporaires, installation.log : le journal) et LANCER_L_APPLI.bat.
Relançable : ce qui est déjà fait est sauté, un téléchargement coupé reprend où il s'était arrêté.
Les scripts lancés envoient leurs signes de vie sur leur sortie : « @@ fait total texte » (la barre),
« @@> texte » (ce qui se fait) ; le reste va dans le journal.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

DOSSIER = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[3]
OUTILS = DOSSIER / "outils"
DEPOT = OUTILS / "depot"
ENV = OUTILS / "env"
TMP = OUTILS / "tmp"
PYENV = ENV / "Scripts" / "python.exe"
JOURNAL = OUTILS / "installation.log"
PYTHON = Path(sys.executable).with_name("python.exe")            # (le Python de l'ordinateur, pour créer env\)
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)         # (les scripts tournent sans fenêtre noire)

# les couleurs de l'appli (thème Marianne), contrastes WCAG AA
FOND, TEXTE, BLEU, VERT, GRIS, ROUGE, PALE = "#FFFFFF", "#161616", "#000091", "#18753C", "#5A5A5A", "#CE0500", "#F5F5FE"
POLICE = "Segoe UI"

# (clé, titre, explication, poids dans la barre générale)
ETAPES = [
    ("env", "L'environnement Python", "Un Python rien que pour l'appli, rangé dans ce dossier (outils\\env).", 1),
    ("libs", "Les bibliothèques", "pandas, DuckDB, matplotlib, seaborn… : environ 300 Mo, une seule fois.", 4),
    ("choix", "Le choix des données", "Toutes prêtes, ou refabriquées depuis les sources officielles.", 0),
    ("donnees", "Les données", "La base de l'appli : 135 scrutins, les communes, les personnes et les mandats.", 10),
    ("images", "Les photos et les affiches", "Assemblée nationale, Sénat, Wikimedia Commons, Archives des Hauts-de-Seine : "
                                             "environ 9 500 images, depuis leur site d'origine.", 25),
    ("fin", "Le raccourci", "Le dossier appli et LANCER_L_APPLI.bat, dans ce dossier.", 1),
]


def taille(n):
    return f"{n / 1e9:.1f} Go" if n >= 1e9 else f"{n / 1e6:.0f} Mo"


def nombre(n):
    return f"{n:,}".replace(",", " ")


class Installation(threading.Thread):
    """Le travail, dans un fil à part : il parle à la fenêtre par une file de messages."""

    def __init__(self, file, choix):
        super().__init__(daemon=True)
        self.file, self.choix, self.processus = file, choix, None

    def dire(self, *message):
        self.file.put(message)

    def lancer(self, commande, cwd=None, filtre=None):
        """Lance un script ; ses signes de vie font avancer la fenêtre, tout le reste va dans le journal
        (filtre : une fonction qui lit les autres lignes et rend True quand elle s'en est occupée)."""
        env = dict(os.environ, TEMP=str(TMP), TMP=str(TMP), PIP_CACHE_DIR=str(TMP / "pip"), MPLCONFIGDIR=str(TMP / "matplotlib"),
                   PYTHONPYCACHEPREFIX=str(TMP / "pycache"), PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONUNBUFFERED="1",
                   GD_PROGRESSION="1")
        with open(JOURNAL, "a", encoding="utf-8", buffering=1) as j:      # (ligne à ligne : rien ne se perd si ça plante)
            j.write(f"\n=== {time.strftime('%d/%m %H:%M:%S')} {' '.join(map(str, commande))}\n")
            self.processus = subprocess.Popen([str(c) for c in commande], cwd=cwd, env=env, stdout=subprocess.PIPE,
                                              stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                              creationflags=SANS_FENETRE)
            for ligne in self.processus.stdout:
                j.write(ligne)
                ligne = ligne.strip()
                if ligne.startswith("@@!"):
                    self.dire("avertissement", ligne[3:].strip())
                elif ligne.startswith("@@>"):
                    self.dire("annonce", ligne[3:].strip())
                elif ligne.startswith("@@ "):
                    morceaux = ligne[3:].split(" ", 2)
                    self.dire("barre", int(morceaux[0]), int(morceaux[1]), morceaux[2] if len(morceaux) > 2 else "")
                elif ligne and not (filtre and filtre(ligne)):
                    self.dire("detail", ligne)
        return self.processus.wait()

    def run(self):
        try:
            for cle, *_ in ETAPES:
                self.dire("etape", cle, "en cours")
                if not getattr(self, "faire_" + cle)():
                    return
                self.dire("etape", cle, "fait")
            self.dire("fin")
        except Exception as e:                       # (une panne imprévue : on la montre, avec son détail dans le journal)
            with open(JOURNAL, "a", encoding="utf-8", buffering=1) as j:      # (ligne à ligne : rien ne se perd si ça plante)
                j.write(f"\n!!! {e!r}\n")
            self.dire("erreur", f"{e.__class__.__name__} : {e}")

    def echec(self, texte):
        self.dire("erreur", texte)
        return False

    def faire_env(self):
        if PYENV.exists():
            self.dire("annonce", "Déjà prêt.")
            return True
        self.dire("annonce", "Création du Python de l'appli…")
        self.dire("indetermine")
        return self.lancer([PYTHON, "-m", "venv", ENV]) == 0 or self.echec("Le Python de l'appli n'a pas pu être créé.")

    def faire_libs(self):
        exigences = DEPOT / "requirements.txt"
        self.dire("annonce", "Préparation de la liste des bibliothèques…")
        self.dire("indetermine")
        self.lancer([PYENV, "-m", "pip", "install", "--upgrade", "--quiet", "pip"])
        rapport = TMP / "bibliotheques.json"
        rapport.unlink(missing_ok=True)
        self.lancer([PYENV, "-m", "pip", "install", "--dry-run", "--quiet", "--report", rapport, "-r", exigences])
        a_faire = [p["metadata"]["name"] for p in json.loads(rapport.read_text(encoding="utf-8")).get("install", [])] \
            if rapport.exists() else []
        if not a_faire:
            self.dire("annonce", "Toutes les bibliothèques sont déjà là.")
            return True
        self.dire("annonce", f"Téléchargement de {len(a_faire)} bibliothèques…")
        compteur = [0]

        def compter(ligne):              # (pip écrit « Downloading pandas-….whl » ou « Using cached … » pour chacune)
            if ligne.startswith(("Downloading ", "Using cached ")):
                compteur[0] += 1
                nom = ligne.split()[1 if ligne.startswith("Downloading") else 2].split("/")[-1].split("-")[0]
                self.dire("barre", min(compteur[0], len(a_faire)), len(a_faire), nom)
                return True
            if ligne.startswith("Collecting "):
                self.dire("detail", f"Recherche de {ligne.split()[1].split('=')[0]}…")
                return True
            if ligne.startswith("Installing collected packages"):
                self.dire("annonce", "Installation des bibliothèques (une ou deux minutes)…")
                self.dire("indetermine")
                return True
            return False
        code = self.lancer([PYENV, "-m", "pip", "install", "--progress-bar", "off", "-r", exigences], filtre=compter)
        return code == 0 or self.echec("Les bibliothèques n'ont pas pu être installées (connexion internet ?).")

    def faire_choix(self):
        if (DEPOT / "donnees" / "appli" / "depouillement.duckdb").exists() and (DEPOT / "donnees" / "appli" / "modele.duckdb").exists():
            self.choix["valeur"] = "pretes"
            self.dire("annonce", "Les données sont déjà là.")
            return True
        if os.environ.get("GD_CHOIX") in ("pretes", "sources"):     # (les tests automatiques répondent à la place)
            self.choix["valeur"] = os.environ["GD_CHOIX"]
            return True
        self.dire("choix")
        self.choix["evenement"].wait()
        return True

    def faire_donnees(self):
        if self.choix["valeur"] == "pretes":
            script = DEPOT / "1_telechargement" / "donnees_pretes.py"
        else:
            script = DEPOT / "4_installation" / "reconstruire.py"
        self.dire("indetermine")
        return self.lancer([PYENV, script], cwd=script.parent) == 0 or self.echec(
            "Les données n'ont pas pu être téléchargées (connexion internet ?).")

    def faire_images(self):
        self.dire("indetermine")
        script = DEPOT / "1_telechargement" / "images.py"
        return self.lancer([PYENV, script], cwd=script.parent) == 0 or self.echec(
            "Les photos et les affiches n'ont pas pu être téléchargées (connexion internet ?).")

    def faire_fin(self):
        appli = DOSSIER / "appli"
        if not (appli / "lancer.py").exists():
            if appli.exists():
                os.rmdir(appli)                         # (un ancien raccourci, ou un dossier vide)
            subprocess.run(["cmd", "/c", "mklink", "/J", str(appli), str(DEPOT / "appli")], capture_output=True,
                           creationflags=SANS_FENETRE)
        (DOSSIER / "LANCER_L_APPLI.bat").write_text(
            '@echo off\r\ncd /d "%~dp0appli"\r\nset "MPLCONFIGDIR=%~dp0outils\\tmp\\matplotlib"\r\n'
            'set "PYTHONPYCACHEPREFIX=%~dp0outils\\tmp\\pycache"\r\nstart "" "%~dp0outils\\env\\Scripts\\pythonw.exe" lancer.py\r\n',
            encoding="ascii")
        return (appli / "lancer.py").exists() or self.echec("Le dossier appli n'a pas pu être créé.")


class Fenetre(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Installation du Grand Dépouillement")
        self.configure(bg=FOND)
        self.geometry("900x760")
        self.minsize(760, 640)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Vert.Horizontal.TProgressbar", background=VERT, troughcolor="#E5E5E5", bordercolor="#CECECE",
                        lightcolor=VERT, darkcolor=VERT, thickness=24)
        style.configure("Bleu.Horizontal.TProgressbar", background=BLEU, troughcolor="#E5E5E5", bordercolor="#CECECE",
                        lightcolor=BLEU, darkcolor=BLEU, thickness=14)
        self.file, self.choix = queue.Queue(), {"valeur": None, "evenement": threading.Event()}
        self.en_cours, self.fini, self.part, self.debut_barre, self.avertissements = None, set(), 0.0, None, []

        tk.Label(self, text="Installation du Grand Dépouillement", font=(POLICE, 20, "bold"), fg=BLEU, bg=FOND).pack(
            anchor="w", padx=24, pady=(18, 0))
        tk.Label(self, text=f"Dans le dossier {DOSSIER}", font=(POLICE, 11), fg=GRIS, bg=FOND).pack(anchor="w", padx=24)
        liste = tk.Frame(self, bg=FOND)
        liste.pack(fill="x", padx=24, pady=(14, 6))
        self.lignes = {}
        for cle, titre, explication, _ in ETAPES:
            l = tk.Frame(liste, bg=FOND)
            l.pack(fill="x", pady=3)
            signe = tk.Label(l, text="○", font=(POLICE, 16), fg=GRIS, bg=FOND, width=2)
            signe.pack(side="left", anchor="n")
            textes = tk.Frame(l, bg=FOND)
            textes.pack(side="left", fill="x", expand=True)
            t = tk.Label(textes, text=titre, font=(POLICE, 13, "bold"), fg=GRIS, bg=FOND, anchor="w")
            t.pack(fill="x")
            tk.Label(textes, text=explication, font=(POLICE, 10), fg=GRIS, bg=FOND, anchor="w", justify="left",
                     wraplength=760).pack(fill="x")
            self.lignes[cle] = (signe, t)

        cadre = tk.Frame(self, bg=PALE, highlightbackground="#CACAFB", highlightthickness=1)
        cadre.pack(fill="x", padx=24, pady=8)
        self.annonce = tk.Label(cadre, text="Démarrage…", font=(POLICE, 13, "bold"), fg=TEXTE, bg=PALE, anchor="w",
                                justify="left", wraplength=800)
        self.annonce.pack(fill="x", padx=14, pady=(12, 6))
        self.barre = ttk.Progressbar(cadre, style="Vert.Horizontal.TProgressbar", maximum=1000)
        self.barre.pack(fill="x", padx=14)
        self.compte = tk.Label(cadre, text="", font=(POLICE, 12), fg=TEXTE, bg=PALE, anchor="w")
        self.compte.pack(fill="x", padx=14, pady=(6, 2))
        self.detail = tk.Label(cadre, text="", font=(POLICE, 9), fg=GRIS, bg=PALE, anchor="w")
        self.detail.pack(fill="x", padx=14, pady=(0, 10))

        tk.Label(self, text="Toute l'installation", font=(POLICE, 11, "bold"), fg=TEXTE, bg=FOND).pack(anchor="w", padx=24, pady=(6, 0))
        self.generale = ttk.Progressbar(self, style="Bleu.Horizontal.TProgressbar", maximum=1000)
        self.generale.pack(fill="x", padx=24)
        self.pourcent = tk.Label(self, text="0 %", font=(POLICE, 11), fg=GRIS, bg=FOND)
        self.pourcent.pack(anchor="e", padx=24)
        self.boutons = tk.Frame(self, bg=FOND)
        self.boutons.pack(fill="x", padx=24, pady=(4, 16))

        self.protocol("WM_DELETE_WINDOW", self.fermer)
        OUTILS.mkdir(parents=True, exist_ok=True)
        TMP.mkdir(parents=True, exist_ok=True)
        self.travail = None
        self.demarrer()
        self.after(150, self.lire)

    # --- le travail ---------------------------------------------------------------------------------------------------
    def demarrer(self):
        for b in self.boutons.winfo_children():
            b.destroy()
        self.travail = Installation(self.file, self.choix)
        self.travail.start()

    def bouton(self, texte, action, principal=False):
        b = tk.Button(self.boutons, text=texte, command=action, font=(POLICE, 13, "bold" if principal else "normal"),
                      fg=FOND if principal else BLEU, bg=BLEU if principal else FOND, activebackground="#1212FF",
                      activeforeground=FOND, relief="flat", bd=0, padx=18, pady=10, highlightthickness=2,
                      highlightbackground=BLEU, cursor="hand2")
        b.pack(side="left", padx=(0, 12))
        b.bind("<Return>", lambda e: action())
        return b

    def poids_total(self):
        return sum(p for *_, p in ETAPES) + (50 if self.choix["valeur"] == "sources" else 0)

    def avancer(self):
        poids = {c: p + (50 if c == "donnees" and self.choix["valeur"] == "sources" else 0) for c, *_, p in ETAPES}
        fait = sum(poids[c] for c in self.fini) + (poids.get(self.en_cours, 0) * self.part if self.en_cours else 0)
        self.generale["value"] = 1000 * fait / self.poids_total()
        self.pourcent.config(text=f"{100 * fait / self.poids_total():.0f} %")

    def lire(self):
        try:
            while True:
                m = self.file.get_nowait()
                getattr(self, "m_" + m[0])(*m[1:])
        except queue.Empty:
            pass
        self.after(150, self.lire)

    # --- les messages du travail --------------------------------------------------------------------------------------
    def m_etape(self, cle, etat):
        signe, titre = self.lignes[cle]
        if etat == "en cours":
            self.en_cours, self.part = cle, 0.0
            signe.config(text="▶", fg=BLEU)
            titre.config(fg=BLEU)
            self.annonce.config(text=next(t for c, t, *_ in ETAPES if c == cle) + "…")
            self.compte.config(text="")
            self.detail.config(text="")
        else:
            self.fini.add(cle)
            self.en_cours = None
            signe.config(text="✔", fg=VERT)
            titre.config(fg=VERT)
            self.barre.stop()
            self.barre.config(mode="determinate", value=1000)
        self.avancer()

    def m_annonce(self, texte):
        self.annonce.config(text=texte)
        self.debut_barre = None

    def m_avertissement(self, texte):
        self.avertissements.append(texte)

    def m_detail(self, texte):
        self.detail.config(text=texte[:140])

    def m_indetermine(self):
        self.barre.config(mode="indeterminate")
        self.barre.start(12)
        self.compte.config(text="")

    def m_barre(self, fait, total, texte):
        if self.barre["mode"] != "determinate":
            self.barre.stop()
            self.barre.config(mode="determinate")
        total = max(total, 1)
        self.barre["value"] = 1000 * fait / total
        self.part = min(fait / total, 1)
        maintenant = time.time()
        if self.debut_barre is None or fait < self.debut_barre[1]:
            self.debut_barre = (maintenant, fait)
        t0, f0 = self.debut_barre
        reste = ""
        if maintenant - t0 > 8 and fait > f0:
            minutes = (total - fait) / ((fait - f0) / (maintenant - t0)) / 60
            reste = " — " + ("moins d'une minute" if minutes < 1 else f"environ {minutes:.0f} min restantes")
        quoi = f"{taille(fait)} sur {taille(total)}" if total > 2_000_000 else f"{nombre(fait)} sur {nombre(total)}"
        self.compte.config(text=f"{quoi}{reste}" + (f"   ·   {texte}" if texte and total <= 2_000_000 else ""))
        self.avancer()

    def m_choix(self):
        self.annonce.config(text="Quelles données veux-tu ?")
        self.barre.stop()
        self.barre.config(mode="determinate", value=0)

        def prendre(valeur):
            self.choix["valeur"] = valeur
            for b in self.boutons.winfo_children():
                b.destroy()
            self.choix["evenement"].set()
        b = self.bouton("Les données toutes prêtes  (900 Mo, quelques minutes)", lambda: prendre("pretes"), principal=True)
        self.bouton("Tout refabriquer depuis les sources  (8 Go, plusieurs heures)", lambda: prendre("sources"))
        b.focus_set()

    def m_fin(self):
        self.en_cours = None
        self.avancer()
        self.annonce.config(text="Terminé ! L'appli est installée.", fg=VERT)
        self.compte.config(text="Pour la lancer plus tard : double-clic sur LANCER_L_APPLI.bat, dans ce dossier.")
        self.detail.config(text="")
        if self.avertissements:
            tk.Label(self, text="À savoir : " + " ".join(self.avertissements), font=(POLICE, 12), fg="#B34000", bg=FOND,
                     anchor="w", justify="left", wraplength=850).pack(fill="x", padx=24, before=self.boutons)
        b = self.bouton("Lancer l'appli", self.lancer_appli, principal=True)
        self.bouton("Fermer", self.destroy)
        b.focus_set()

    def m_erreur(self, texte):
        self.barre.stop()
        if self.en_cours:
            signe, titre = self.lignes[self.en_cours]
            signe.config(text="✖", fg=ROUGE)
            titre.config(fg=ROUGE)
        self.annonce.config(text=texte, fg=ROUGE)
        self.compte.config(text="Clique sur Réessayer : l'installation reprendra là où elle s'est arrêtée.")
        self.detail.config(text=f"Le détail est dans {JOURNAL}")
        b = self.bouton("Réessayer", self.reessayer, principal=True)
        self.bouton("Copier le détail pour Julien", self.copier)
        b.focus_set()

    # --- les boutons --------------------------------------------------------------------------------------------------
    def reessayer(self):
        self.annonce.config(fg=TEXTE)
        self.fini.clear()
        for signe, titre in self.lignes.values():
            signe.config(text="○", fg=GRIS)
            titre.config(fg=GRIS)
        self.choix["evenement"].clear()
        self.demarrer()

    def copier(self):
        lignes = JOURNAL.read_text(encoding="utf-8", errors="replace").splitlines()[-80:] if JOURNAL.exists() else []
        self.clipboard_clear()
        self.clipboard_append("\n".join(lignes))
        self.detail.config(text="Copié ! Colle-le dans un mail ou un message à Julien (Ctrl+V).")

    def lancer_appli(self):
        os.startfile(DOSSIER / "LANCER_L_APPLI.bat")
        self.after(1500, self.destroy)

    def fermer(self):
        if self.travail and self.travail.is_alive():
            from tkinter import messagebox
            if not messagebox.askyesno("Installation en cours", "L'installation n'est pas finie. La fermer quand même ?\n\n"
                                       "Relancer INSTALLMOI.bat la reprendra là où elle s'est arrêtée."):
                return
            if self.travail.processus and self.travail.processus.poll() is None:
                self.travail.processus.kill()
        self.destroy()


if __name__ == "__main__":
    Fenetre().mainloop()
