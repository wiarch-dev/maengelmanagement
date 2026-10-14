@echo off
title MaengelManagement-Server
cd /d "%~dp0"

:: Firewall-Freigabe fuer Port 8000 einmalig anlegen - braucht Admin-Rechte, Ablehnung ist ok
netsh advfirewall firewall show rule name="MaengelManagement" >nul 2>&1
if errorlevel 1 (
  echo Firewall-Freigabe fuer Port 8000 wird eingerichtet - Admin-Abfrage ...
  powershell -Command "Start-Process netsh -ArgumentList 'advfirewall firewall add rule name=\"MaengelManagement\" dir=in action=allow protocol=TCP localport=8000' -Verb RunAs -Wait" >nul 2>&1
)

:: Blockier-Regeln fuer python.exe melden (entstehen, wenn der Windows-Sicherheitshinweis weggeklickt wurde)
netsh advfirewall firewall show rule name="Python" dir=in 2>nul | findstr /i "Blockieren Block" >nul
if not errorlevel 1 (
  echo.
  echo ACHTUNG: Windows blockiert python.exe in der Firewall. Handy/Tablet kommen so nicht auf den Server.
  echo Als Administrator ausfuehren:  netsh advfirewall firewall delete rule name="Python"
  echo Danach neu starten und beim Windows-Hinweis "Zugriff zulassen" waehlen.
  echo.
)

:: Python finden
set PY=python
python --version >nul 2>&1 || set PY=py -3
%PY% --version >nul 2>&1 || (
  echo Python nicht gefunden. Bitte Python 3.10 oder neuer installieren: https://www.python.org/downloads/
  echo Beim Installieren "Add python.exe to PATH" anhaken.
  pause
  exit /b 1
)

:: Umgebung anlegen und Pakete installieren bzw. pruefen
if not exist venv (
  echo Erstelle Python-Umgebung ...
  %PY% -m venv venv || (echo Fehler beim Anlegen der Umgebung. & pause & exit /b 1)
)
echo Pruefe Pakete ...
venv\Scripts\python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo Pakete konnten nicht installiert werden - Internetverbindung oder Proxy pruefen.
  pause
  exit /b 1
)

echo.
venv\Scripts\python app.py
pause
