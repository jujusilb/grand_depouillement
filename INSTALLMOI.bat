@echo off
rem ===========================================================================================
rem  INSTALLMOI.bat - Le Grand Depouillement
rem  Double-clic, c'est tout. Relancable : la 2e fois, il met a jour.
rem
rem  1. Python et Git : installes avec winget s'ils manquent (les deux seules installations
rem     hors de ce dossier).
rem  2. Le code : clone (ou mis a jour) depuis le depot GitHub, dans outils\depot.
rem  3. Les bibliotheques : dans un environnement Python propre a ce dossier (outils\env).
rem  4. Les donnees : toutes pretes (GitHub) ou refabriquees depuis les sources officielles.
rem  5. Les photos et les affiches, depuis leur source d'origine.
rem  A la fin, ce dossier contient : appli\ (l'appli et ses donnees), outils\ (la partie
rem  technique) et LANCER_L_APPLI.bat. Tout reste dans ce dossier (temporaires : outils\tmp).
rem ===========================================================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "ICI=%~dp0"
set "DEPOT=https://github.com/jujusilb/grand_depouillement.git"
set "OUTILS=%ICI%outils"
set "CODE=%ICI%outils\depot"

rem --- rien ne sort du dossier : temporaires et caches dans outils\tmp ---
if not exist "%OUTILS%\tmp" mkdir "%OUTILS%\tmp"
set "TEMP=%OUTILS%\tmp"
set "TMP=%OUTILS%\tmp"
set "PIP_CACHE_DIR=%OUTILS%\tmp\pip"
set "MPLCONFIGDIR=%OUTILS%\tmp\matplotlib"
set "PYTHONPYCACHEPREFIX=%OUTILS%\tmp\pycache"
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
    echo  [1/5] Python absent : installation...
    winget install --exact --id Python.Python.3.14 --scope user --silent --accept-package-agreements --accept-source-agreements
    call :trouver_python
)
if not defined PY (
    echo  Python n'a pas pu etre installe.
    goto :echec
)
echo  [1/5] Python : OK

rem --- 1 bis. Git ---
call :trouver_git
if not defined GIT (
    echo  [1/5] Git absent : installation...
    winget install --exact --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    call :trouver_git
)
if not defined GIT (
    echo  Git n'a pas pu etre installe.
    goto :echec
)
echo  [1/5] Git : OK

rem --- 2. le code, dans outils\depot ; appli\ = un raccourci de dossier vers l'appli ---
if exist "%CODE%\.git" (
    echo  [2/5] Mise a jour du code...
    "%GIT%" -C "%CODE%" pull --ff-only
) else (
    echo  [2/5] Telechargement du code...
    "%GIT%" clone --depth 1 "%DEPOT%" "%CODE%"
)
if errorlevel 1 goto :echec
if not exist "%ICI%appli\le_grand_depouillement.py" (
    if exist "%ICI%appli" rmdir "%ICI%appli" 2>nul
    mklink /J "%ICI%appli" "%CODE%\BigData_IA\le_grand_depouillement" >nul
)
if not exist "%ICI%appli\le_grand_depouillement.py" (
    echo  Le dossier appli n'a pas pu etre cree.
    goto :echec
)

rem --- 3. les bibliotheques, dans outils\env ---
if not exist "%OUTILS%\env\Scripts\python.exe" (
    echo  [3/5] Creation de l'environnement Python...
    "%PY%" -m venv "%OUTILS%\env"
    if errorlevel 1 goto :echec
)
set "PYENV=%OUTILS%\env\Scripts\python.exe"
echo  [3/5] Verification des bibliotheques...
"%PYENV%" -m pip install --upgrade --quiet pip
"%PYENV%" -m pip install --quiet -r "%CODE%\requirements.txt"
if errorlevel 1 goto :echec

rem --- 4. les donnees : au choix ---
echo.
echo  [4/5] Recuperation des donnees :
echo     1 = tout retelecharger depuis les sources officielles et tout refabriquer
echo         (environ 8 Go a telecharger, plusieurs heures)
echo     2 = utiliser les donnees deja disponibles, toutes pretes
echo         (environ 900 Mo a telecharger, quelques minutes)
choice /c 12 /n /m "  Tape 1 ou 2 : "
if errorlevel 2 (
    "%PYENV%" "%CODE%\installation\donnees_pretes.py"
) else (
    "%PYENV%" "%CODE%\installation\reconstruire.py"
)
if errorlevel 1 goto :echec

rem --- 5. toutes les photos et toutes les affiches, depuis leur source (long la 1re fois : environ 1 heure) ---
echo  [5/5] Photos et affiches (depuis leur source d'origine, environ 1 heure la premiere fois)...
"%PYENV%" "%CODE%\installation\images.py"
if errorlevel 1 goto :echec

rem --- le lanceur, dans ce dossier ---
> "%ICI%LANCER_L_APPLI.bat" (
    echo @echo off
    echo cd /d "%%~dp0appli"
    echo set "MPLCONFIGDIR=%%~dp0outils\tmp\matplotlib"
    echo set "PYTHONPYCACHEPREFIX=%%~dp0outils\tmp\pycache"
    echo start "" "%%~dp0outils\env\Scripts\pythonw.exe" le_grand_depouillement.py
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
