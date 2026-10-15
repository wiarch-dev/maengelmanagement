# MEMA (MängelManagement) – Server

*MEMA – Pendenzen abgrasen.* Der Bauleiter ist der Hirte, der Unternehmer das Schaf: jeder Unternehmer sieht nur seine eigene «Koppel» (seine Pendenzen) und grast sie ab.

## Start auf dem Laptop (Windows)
1. Python 3.10 oder neuer installieren (python.org, "Add to PATH" anhaken).
2. Diesen Ordner `server` irgendwohin kopieren (z. B. `C:\MaengelManagement\server`).
3. Doppelklick auf **start.bat**. Beim ersten Mal wird eine Python-Umgebung angelegt (1–2 Minuten).
4. Im Fenster steht die Adresse, z. B. `http://192.168.1.23:8000` – diese am Handy/Tablet im selben WLAN öffnen. Am PC: `http://localhost:8000`.
5. Erstes Login: **wi_arch@hotmail.com / start1234** → Passwort wird sofort geändert.
6. Bisherige Testdaten: Menü → Sichern → "Import aus Browser-Version" → Export-Datei der alten App wählen.

Windows-Firewall: Beim ersten Start fragt Windows nach – **"Zugriff zulassen"** (privat und öffentlich). Wird der Hinweis weggeklickt, legt Windows eine Blockier-Regel "Python" an; dann kommt das Handy nicht drauf (am Laptop geht localhost, die eigene IP aber nicht). Beheben als Administrator: `netsh advfirewall firewall delete rule name="Python"`, Server neu starten, Zugriff zulassen.

## Daten
Alles liegt im Ordner `server\data\` (Datenbank `maengel.db`, Ordner `photos`, `plans`, Logo).
Sicherung = diesen Ordner kopieren (oder in der App: Menü → Sichern → Komplett-Sicherung ZIP).
Umzug auf einen anderen Server = Ordner `server` samt `data` kopieren und dort starten.

## Rollen
- **Superadmin** (erstes Konto, wi_arch@hotmail.com): alles – legt Projekte an und weist sie Bauleitern zu, verwaltet alle Benutzer, Firmen-Einstellungen (Logo, Firmenangaben, SMTP, Löschfrist), Sicherungen.
- **Bauleiter**: nur zugewiesene Projekte; dort Pläne, Unternehmer (inkl. Login), Mängel, Versand; legt Bauherren und Unternehmer-Zugänge für seine Projekte an. Keine Bauleiter, keine Projekte.
- **Unternehmer**: Zugänge werden im Unternehmer-Dialog angelegt – Häkchen „Zugang gewähren“ (Firmen-Mail) und/oder weitere Logins (eigene E-Mail je Mitarbeiter). Jeder Login bekommt ein zufälliges Start-Passwort; mit ✉ werden Link, Zugangsname und Passwort per Mail verschickt (↻ = neues Passwort erzeugen & senden). Pendenzen-Mails gehen an die Firmen-Mail und alle Logins. Sieht nur eigene Pendenzen, darf nur offen → bearbeitet melden (mit Beweisfoto).
- **Bauherr**: nur lesen, pro Projekt zugeordnet.
Alle müssen das Start-Passwort beim ersten Login ändern. Passwörter werden nur als Hash gespeichert (PBKDF2-SHA256).

## Mailversand (SMTP)
Menü → Einstellungen → Mailversand: Server, Port, Verschlüsselung, Benutzer, Passwort, Absender. „Testmail an mich senden“ prüft die Einstellungen.
Microsoft 365: Server `smtp.office365.com`, Port 587, STARTTLS, Benutzer = Postfach-Adresse (SMTP-AUTH muss für das Postfach erlaubt sein).
Pendenzen → „✉ Direkt senden“ verschickt pro Unternehmer eine Mail mit PDF; der Versand wird im Verlauf jeder Pendenz protokolliert.
Hinweis: Per SMTP gesendete Mails erscheinen nicht automatisch unter „Gesendet“ in Outlook – dafür „Kopie an mich selbst“ aktivieren.

## Offline & Abgleich
- Nach dem ersten Login mit Verbindung bleibt der Benutzer angemeldet (90 Tage) und der letzte Projektstand liegt im Gerät (IndexedDB). Ohne Netz: Mängel erfassen, Fotos machen, Status melden – die Änderungen warten in einer Warteschlange (Zähler am Knopf oben, rote Leiste) und werden **automatisch hochgeladen**, sobald Verbindung besteht. Hochladen fragt nie nach.
- **Beim App-Start** prüft MEMA, ob es auf dem Server Neues gibt, und fragt mit Anzahl nach («3 neue Mängel – jetzt herunterladen?»). Erst nach Ja wird geladen.
- Menü → **Abgleich & Offline** (jede Rolle, wird pro Benutzer auf dem Server gespeichert): neue Mängel *automatisch alle X Minuten* oder *nur manuell* (Knopf oben: Hirtenstab für Bauleitung, Glocke für Unternehmer) holen; Herunterladen *nur im WLAN* oder auch über mobile Daten (iPhone/iPad melden dem Browser nicht, ob WLAN aktiv ist – dort wirkt die Einstellung nicht).
- **Konfliktregeln beim Abgleich** (letzte Änderung gewinnt, nichts geht verloren): Beweisfotos und Notizen werden immer übernommen. Meldet ein Unternehmer «bearbeitet» für einen Mangel, der inzwischen erledigt ist, bleibt er erledigt und die Meldung steht im Verlauf. Überschreibt eine Offline-Bearbeitung eine zwischenzeitliche Änderung, wird das im Verlauf als «Konflikt» vermerkt. Gelöschte Mängel werden gemeldet und die Änderung verworfen. Nach dem Abgleich zeigt die App alle Hinweise in einem Fenster.
- **Offline-Start** (App öffnen ohne Netz) braucht einen Service Worker und damit **HTTPS** (oder localhost). Ohne HTTPS muss die App beim Öffnen eine Verbindung haben; geöffnet bleibt sie aber offline-fähig.
- iPhone/iPad: zwingend in Safari über «Zum Home-Bildschirm» installieren und von dort starten – sonst löscht Safari die lokalen Daten nach 7 Tagen Nichtnutzung. Die Anleitung steht in der App (Erste Schritte, erscheint nach dem ersten Login, Menü → Erste Schritte).

## HTTPS
Liegen `data\cert.pem` und `data\key.pem` im Datenordner, startet der Server mit HTTPS (Adresse `https://…:8000`). Möglichkeiten:
- **Intern (Firmennetz) mit [mkcert](https://github.com/FiloSottile/mkcert):** `mkcert -install` auf dem Server-PC, dann `mkcert -cert-file cert.pem -key-file key.pem 192.168.1.23 servername` (eigene IP/Name einsetzen) und die beiden Dateien nach `data\` kopieren. Auf jedem Handy/Tablet muss das mkcert-Root-Zertifikat (`mkcert -CAROOT` zeigt den Ordner, Datei `rootCA.pem`) einmalig installiert und vertraut werden (iOS: Datei per Mail/AirDrop öffnen → Einstellungen → Profil installieren → Allgemein → Info → Zertifikatsvertrauen einschalten).
- **Extern erreichbar (VPS):** Reverse-Proxy mit automatischem Let's-Encrypt-Zertifikat, z. B. Caddy (`Caddyfile`: `maengel.firma.ch { reverse_proxy localhost:8000 }`); der Server selbst läuft dann ohne cert.pem auf Port 8000 nur lokal.
- Selbstsignierte Zertifikate ohne installiertes Root-Zertifikat funktionieren im Browser mit Warnung, aber **nicht** für Service Worker/Offline-Start.

## Sicherung
- Menü → Sichern (Superadmin): **Komplett-Sicherung (ZIP)** herunterladen (Datenbank + Fotos + Pläne + Logo), **Sicherung wiederherstellen (ZIP)** vom eigenen Computer einspielen (ersetzt alle Daten; der bisherige Stand wird vorher automatisch unter `data\backups\vor-wiederherstellung-….zip` abgelegt; danach müssen sich alle neu anmelden).
- **Tägliche Sicherung** auf dem Server nach `data\backups\` (Uhrzeit und Anzahl behaltener Sicherungen einstellbar) – zusätzlich optional per Mail an eine Adresse (ohne Fotos nur Datenbank + Pläne; mit Fotos bis 20 MB, darüber kommt ein Hinweis). Die Sicherungen auf dem Server sind im Dialog aufgelistet und herunterladbar.
- Umzug auf einen anderen Server = Ordner `server` samt `data` kopieren (oder dort «Sicherung wiederherstellen»).

## Fotos
Fotos werden beim Erfassen auf max. 1024 px verkleinert (JPEG). Fotos erledigter Mängel werden nach 30 Tagen automatisch gelöscht (Einstellungen → Tage; 0 = nie). Der Mangel selbst bleibt mit allen Daten erhalten.

## Beispielprojekt
`demo.bat` legt „Beispiel Wohnüberbauung Rheinblick“ an: 7 Geschosse, 30 Unternehmer, 270 Pendenzen.

## Konfiguration (optional, Umgebungsvariablen)
- `MM_PORT` (Standard 8000), `MM_DATA` (Datenordner), `MM_ADMIN_EMAIL` / `MM_ADMIN_PW` (nur beim allerersten Start)

## Projekte löschen (Vier-Augen-Prinzip)
Ein Bauleiter allein kann kein Projekt löschen. Im Menü «Projekte» beantragt eine Person die Löschung (🗑);
eine **zweite** Person – ein anderer zugewiesener Bauleiter oder der Superadmin – bestätigt sie (🗑 bestätigen).
Erst dann wird das Projekt archiviert (Daten bleiben auf dem Server). Ein Antrag kann zurückgezogen werden (↩).

## Projektmitglieder (👥 im Menü «Projekte»)
- Bauleiter: Bauherren und Unternehmer aus dem Projekt nehmen, Bauherren und Unternehmer (+ Unternehmer) hinzufügen.
- Unternehmer: 🔑 Zugang anlegen (Zufallspasswort), ✉ Zugangsdaten mailen, ⏸ inaktiv schalten (Zugang gesperrt, nicht mehr in Auswahl/Versand, Pendenzen bleiben), ✕ entfernen.
- «🔑 Alle freischalten» legt Zugänge für alle Unternehmer mit E-Mail an; «✉ Zugangsmail an alle …» sendet die Zugangsdaten als Sammelmail (Text mit Platzhaltern einstellbar, wird als Vorlage gespeichert; bereits aktive Zugänge werden übersprungen, optional mit Passwort-Reset).
- Superadmin: zusätzlich Bauleiter aus dem Projekt nehmen oder hinzufügen; sieht alle Projekte.
- Bauleiter sehen nur die ihnen zugewiesenen Projekte.

## Fotos erledigter Mängel
Einstellungen (Superadmin): Häkchen «Fotos erledigter Mängel automatisch löschen» + Anzahl Tage (Standard 30).
