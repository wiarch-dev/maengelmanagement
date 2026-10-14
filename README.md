# MängelManagement

Prototyp – temporäres Test-Hosting via GitHub Pages: https://wiarch-dev.github.io/maengelmanagement/

- `index.html` – die App (eine Datei, läuft ohne Server; Daten bleiben pro Gerät im Browser)
- `dist/MaengelManagement.html` – dieselbe Datei zum Herunterladen / Ablegen auf einem eigenen (internen) Webserver
- `desktop/MaengelArchiv.py` – Windows-Tool: Export der App (.json) in eine Access-Datenbank abgleichen + Fotoordner pro Unternehmer

## MängelArchiv (Desktop)
Voraussetzungen: Windows, Microsoft Access oder "Access Database Engine", Python 3, `pip install pyodbc pywin32`.
Start: Doppelklick auf `MaengelArchiv.py` (GUI) oder `python MaengelArchiv.py <export.json> <Archivordner>`.
