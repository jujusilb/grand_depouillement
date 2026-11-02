@echo off
rem demarrer.bat - lance par INSTALLMOI.bat : installe Python s'il manque, puis ouvre la fenetre d'installation
rem (installateur.py), qui fait tout le reste en montrant chaque etape.
setlocal
for %%I in ("%~dp0..\..\..") do set "DOSSIER=%%~fI"
call :python
if not defined PYW (
    echo Installation de Python, quelques minutes...
    winget install -e --id Python.Python.3.14 --scope user --silent --accept-package-agreements --accept-source-agreements
    call :python
)
if not defined PYW (echo Python n'a pas pu etre installe. Envoie une photo de cet ecran a Julien. & pause & exit /b 1)
start "" "%PYW%" "%~dp0installateur.py" "%DOSSIER%"
exit /b 0

:python
set "PYW="
for /f "delims=" %%P in ('py -3.14 -c "import sys; print(sys.executable)" 2^>nul') do set "PYW=%%~dpPpythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
exit /b 0
