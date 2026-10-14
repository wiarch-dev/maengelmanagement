@echo off
chcp 65001 >nul
title MängelManagement-Server
cd /d "%~dp0"
rem --- Firewall-Regel einmalig anlegen (braucht Admin-Rechte; wird bei Ablehnung übersprungen)
netsh advfirewall firewall show rule name="MaengelManagement" >nul 2>&1
if errorlevel 1 (
  echo Firewall-Freigabe fuer Port 8000 wird eingerichtet ^(Admin-Abfrage^) ...
  powershell -Command "Start-Process netsh -ArgumentList 'advfirewall firewall add rule name=\"MaengelManagement\" dir=in action=allow protocol=TCP localport=8000' -Verb RunAs -Wait" >nul 2>&1
)
if not exist venv (
  echo Erstelle Python-Umgebung ...
  python -m venv venv || (echo Python nicht gefunden. Bitte Python 3.10+ installieren: https://www.python.org/downloads/ & pause & exit /b 1)
  venv\Scripts\pip install -q -r requirements.txt
)
venv\Scripts\python app.py
pause
