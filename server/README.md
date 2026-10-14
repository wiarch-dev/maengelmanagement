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

## Mailversand (SMTP)
Menü → Einstellungen → Mailversand: Server, Port, Verschlüsselung, Benutzer, Passwort, Absender. „Testmail an mich senden“ prüft die Einstellungen.
Microsoft 365: Server `smtp.office365.com`, Port 587, STARTTLS, Benutzer = Postfach-Adresse (SMTP-AUTH muss für das Postfach erlaubt sein).
Pendenzen → „✉ Direkt senden“ verschickt pro Unternehmer eine Mail mit PDF; der Versand wird im Verlauf jeder Pendenz protokolliert.
Hinweis: Per SMTP gesendete Mails erscheinen nicht automatisch unter „Gesendet“ in Outlook – dafür „Kopie an mich selbst“ aktivieren.

## Offline
Die App merkt sich Änderungen ohne Verbindung (neuer Mangel, Foto, Status, Position) und gleicht sie automatisch ab, sobald der Server erreichbar ist (rote Leiste zeigt wartende Änderungen; ⏳ in der Liste).
Voraussetzung ohne HTTPS: die App bleibt im Browser geöffnet. Vollständiger Offline-Start (auch nach Schliessen) kommt mit HTTPS.

## Fotos
Fotos werden beim Erfassen auf max. 1024 px verkleinert (JPEG). Fotos erledigter Mängel werden nach 30 Tagen automatisch gelöscht (Einstellungen → Tage; 0 = nie). Der Mangel selbst bleibt mit allen Daten erhalten.

## Beispielprojekt
`demo.bat` legt „Beispiel Wohnüberbauung Rheinblick“ an: 7 Geschosse, 30 Unternehmer, 270 Pendenzen.

## Konfiguration (optional, Umgebungsvariablen)
- `MM_PORT` (Standard 8000), `MM_DATA` (Datenordner), `MM_ADMIN_EMAIL` / `MM_ADMIN_PW` (nur beim allerersten Start)
