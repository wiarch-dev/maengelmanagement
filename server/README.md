# MängelManagement – Server

## Start auf dem Laptop (Windows)
1. Python 3.10 oder neuer installieren (python.org, "Add to PATH" anhaken).
2. Diesen Ordner `server` irgendwohin kopieren (z. B. `C:\MaengelManagement\server`).
3. Doppelklick auf **start.bat**. Beim ersten Mal wird eine Python-Umgebung angelegt (1–2 Minuten).
4. Im Fenster steht die Adresse, z. B. `http://192.168.1.23:8000` – diese am Handy/Tablet im selben WLAN öffnen. Am PC: `http://localhost:8000`.
5. Erstes Login: **admin@dietziker-bm.ch / start1234** → Passwort wird sofort geändert.
6. Bisherige Testdaten: Menü → Sichern → "Import aus Browser-Version" → Export-Datei der alten App wählen.

Windows-Firewall: Beim ersten Start fragt Windows evtl. nach – "Zugriff zulassen" (privates Netz), sonst kommt das Handy nicht drauf.

## Daten
Alles liegt im Ordner `server\data\` (Datenbank `maengel.db`, Ordner `photos`, `plans`, Logo).
Sicherung = diesen Ordner kopieren (oder in der App: Menü → Sichern → Komplett-Sicherung ZIP).
Umzug auf einen anderen Server = Ordner `server` samt `data` kopieren und dort starten.

## Rollen
- **Bauleiter**: alle Rechte, legt Projekte, Pläne, Unternehmer und Benutzer an.
- **Unternehmer**: Konto mit E-Mail + Passwort (wird beim Unternehmer mit "Zugang anlegen" erzeugt); sieht nur eigene Pendenzen, darf nur offen → bearbeitet melden (mit Beweisfoto).
- **Bauherr**: nur lesen, pro Projekt zugeordnet.
Alle müssen das Start-Passwort beim ersten Login ändern. Passwörter werden nur als Hash gespeichert (PBKDF2-SHA256).

## Konfiguration (optional, Umgebungsvariablen)
- `MM_PORT` (Standard 8000), `MM_DATA` (Datenordner), `MM_ADMIN_EMAIL` / `MM_ADMIN_PW` (nur beim allerersten Start)
