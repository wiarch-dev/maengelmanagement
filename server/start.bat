@echo off
chcp 65001 >nul
title MängelManagement-Server
cd /d "%~dp0"
if not exist venv (
  echo Erstelle Python-Umgebung ...
  python -m venv venv || (echo Python nicht gefunden. Bitte Python 3.10+ installieren: https://www.python.org/downloads/ & pause & exit /b 1)
  venv\Scripts\pip install -q -r requirements.txt
)
venv\Scripts\python app.py
pause
