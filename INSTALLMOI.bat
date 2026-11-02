@echo off
rem ===========================================================================================
rem  INSTALLMOI.bat - Le Grand Depouillement
rem  Double-clic, c'est tout. Relancable : la 2e fois, il met a jour.
rem
rem  1. Python et Git : installes avec winget s'ils manquent (les deux seules installations
rem     hors de ce dossier).
rem  2. Le code : clone (ou mis a jour) depuis le depot GitHub, dans ce dossier.
rem  3. Les bibliotheques : dans un environnement Python propre a ce dossier (env\).
rem  4. Les donnees : telechargees en ligne (data.gouv, INSEE, Wikidata) puis mises en forme
rem     par les scripts du depot, dans ce dossier.
rem  Tout le reste (fichiers temporaires, caches) reste dans ce dossier.
rem ===========================================================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "ICI=%~dp0"
set "DEPOT=https://github.com/jujusilb/grand_depouillement.git"

rem --- rien ne sort du dossier : temporaires et caches ici ---
if not exist "%ICI%tmp" mkdir "%ICI%tmp"
set "TEMP=%ICI%tmp"
set "TMP=%ICI%tmp"
set "PIP_CACHE_DIR=%ICI%tmp\pip"
set "MPLCONFIGDIR=%ICI%tmp\matplotlib"
set "PYTHONPYCACHEPREFIX=%ICI%tmp\pycache"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

echo.
echo  ==== Le Grand Depouillement : installation ====
echo.

rem --- 0. winget ---
where winget >nul 2>nul
if errorlevel 1 (
    echo  winget est introuvable. Installe "Programme d'installation d'application"
    echo  depuis le Microsoft Store, puis relance ce fichier.
    goto :echec
)

rem --- 1. Python ---
call :trouver_python
if not defined PY (
    echo  [1/4] Python absent : installation...
    winget install --exact --id Python.Python.3.14 --scope user --silent --accept-package-agreements --accept-source-agreements
    call :trouver_python
)
if not defined PY (
    echo  Python n'a pas pu etre installe.
    goto :echec
)
echo  [1/4] Python : OK

rem --- 1 bis. Git ---
call :trouver_git
if not defined GIT (
    echo  [1/4] Git absent : installation...
    winget install --exact --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    call :trouver_git
)
if not defined GIT (
    echo  Git n'a pas pu etre installe.
    goto :echec
)
echo  [1/4] Git : OK

rem --- 2. le code ---
if exist "%ICI%app\.git" (
    echo  [2/4] Mise a jour du code...
    "%GIT%" -C "%ICI%app" pull --ff-only
) else (
    echo  [2/4] Telechargement du code...
    "%GIT%" clone --depth 1 "%DEPOT%" "%ICI%app"
)
if errorlevel 1 goto :echec

rem --- 3. les bibliotheques, dans env\ ---
if not exist "%ICI%env\Scripts\python.exe" (
    echo  [3/4] Creation de l'environnement Python...
    "%PY%" -m venv "%ICI%env"
    if errorlevel 1 goto :echec
)
set "PYENV=%ICI%env\Scripts\python.exe"
echo  [3/4] Verification des bibliotheques...
"%PYENV%" -m pip install --upgrade --quiet pip
"%PYENV%" -m pip install --quiet -r "%ICI%app\requirements.txt"
if errorlevel 1 goto :echec

rem --- 4. les donnees : au choix ---
echo.
echo  [4/4] Recuperation des donnees :
echo     1 = tout retelecharger depuis les sources officielles et tout refabriquer
echo         (environ 8 Go a telecharger, plusieurs heures)
echo     2 = utiliser les donnees deja disponibles, toutes pretes
echo         (environ 900 Mo a telecharger, quelques minutes)
choice /c 12 /n /m "  Tape 1 ou 2 : "
if errorlevel 2 (
    "%PYENV%" "%ICI%app\installation\donnees_pretes.py"
) else (
    "%PYENV%" "%ICI%app\installation\reconstruire.py"
)
if errorlevel 1 goto :echec

rem --- le lanceur, dans ce dossier ---
> "%ICI%LANCER_L_APPLI.bat" (
    echo @echo off
    echo cd /d "%%~dp0app\BigData_IA\le_grand_depouillement"
    echo set "MPLCONFIGDIR=%%~dp0tmp\matplotlib"
    echo set "PYTHONPYCACHEPREFIX=%%~dp0tmp\pycache"
    echo start "" "%%~dp0env\Scripts\pythonw.exe" le_grand_depouillement.py
)

echo.
echo  ==== Termine ! Double-clique sur LANCER_L_APPLI.bat ====
echo.
pause
exit /b 0

:echec
echo.
echo  ==== L'installation s'est arretee. Envoie une photo de cet ecran a Julien. ====
echo.
pause
exit /b 1

rem --- Python : le lanceur py, sinon python.exe aux endroits habituels (PATH pas encore a jour) ---
:trouver_python
set "PY="
for %%P in (py.exe) do if not "%%~$PATH:P"=="" set "PY=%%~$PATH:P"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PY if exist "%WINDIR%\py.exe" set "PY=%WINDIR%\py.exe"
exit /b 0

:trouver_git
set "GIT="
for %%G in (git.exe) do if not "%%~$PATH:G"=="" set "GIT=%%~$PATH:G"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
exit /b 0
