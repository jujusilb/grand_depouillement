@echo off
rem Le Grand Depouillement : double-clic, c'est tout. Le reste (Python, l'appli, les donnees) vient de GitHub.
cd /d "%~dp0"
where git >nul 2>nul || winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
if exist outils\depot\.git (git -C outils\depot pull -q) else (git clone -q --depth 1 https://github.com/jujusilb/grand_depouillement.git outils\depot)
if not exist outils\depot\4_installation\demarrer.bat (echo Pas de connexion internet ? Relance ce fichier. & pause & exit /b 1)
call outils\depot\4_installation\demarrer.bat
