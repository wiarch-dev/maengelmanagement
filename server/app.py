# -*- coding: utf-8 -*-
"""
MängelManagement – Server (Python / FastAPI / SQLite)

Start:   python app.py            (oder start.bat)
Dann:    http://localhost:8000    bzw. im WLAN  http://<IP-des-Laptops>:8000

Daten liegen im Ordner  data/   (Datenbank, Fotos, Pläne, Logo) – das ist auch das Backup-Paket.
Beim ersten Start wird ein Bauleiter-Konto angelegt (siehe Konsole).
"""
import base64, hashlib, hmac, json, os, re, secrets, sqlite3, datetime, mimetypes, shutil, io, zipfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("MM_DATA", ROOT / "data"))
DB_PATH = DATA / "maengel.db"
PHOTOS = DATA / "photos"
PLANS = DATA / "plans"
JPHOTOS = DATA / "journal"
for d in (DATA, PHOTOS, PLANS, JPHOTOS): d.mkdir(parents=True, exist_ok=True)

from contextlib import asynccontextmanager
@asynccontextmanager
async def _lifespan(app):
    import asyncio
    task = asyncio.get_event_loop().create_task(_bg_loop())
    yield
    task.cancel()

app = FastAPI(title="MängelManagement", docs_url=None, redoc_url=None, lifespan=_lifespan)

# ----------------------------------------------------------------- Hilfen
def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def uid(): return secrets.token_hex(8)

def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON"); c.execute("PRAGMA journal_mode=WAL")
    return c

def hash_pw(pw: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()

def check_pw(pw: str, stored: str) -> bool:
    try:
        salt_b64, h_b64 = stored.split("$")
        return hmac.compare_digest(hash_pw(pw, base64.b64decode(salt_b64)), stored)
    except Exception:
        return False

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, role TEXT NOT NULL,
  name TEXT, must_change INTEGER DEFAULT 1, active INTEGER DEFAULT 1, created TEXT);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT, created TEXT, last TEXT);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, number TEXT, created TEXT, next_nr INTEGER DEFAULT 1,
  current_plan TEXT, settings TEXT DEFAULT '{}', archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS project_users (project_id TEXT, user_id TEXT, PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT, sort INTEGER DEFAULT 0, version TEXT, note TEXT,
  added TEXT, replaced TEXT, file TEXT, history TEXT DEFAULT '[]', deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS contractors (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT, bkp TEXT, trade TEXT, email TEXT, salutation TEXT,
  first_name TEXT, last_name TEXT, address TEXT, phones TEXT DEFAULT '[]', note TEXT, user_id TEXT, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS contractor_users (contractor_id TEXT, user_id TEXT, PRIMARY KEY(contractor_id,user_id));
CREATE TABLE IF NOT EXISTS defects (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, nr INTEGER, plan_id TEXT, spot_id TEXT, x REAL, y REAL,
  descr TEXT, contractor_id TEXT, due TEXT, status TEXT DEFAULT 'offen', created TEXT, created_by TEXT,
  fixed_at TEXT, fix_note TEXT, closed_at TEXT, reopen_reason TEXT, updated TEXT, deleted INTEGER DEFAULT 0, photos_purged TEXT);
CREATE TABLE IF NOT EXISTS photos (
  id TEXT PRIMARY KEY, defect_id TEXT NOT NULL, kind TEXT DEFAULT 'photo', sort INTEGER DEFAULT 0, file TEXT, created TEXT, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, defect_id TEXT, ts TEXT, user_id TEXT, user_name TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS journal (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, day TEXT NOT NULL, weather TEXT, weather_final INTEGER DEFAULT 0,
  presence TEXT DEFAULT '[]', works TEXT DEFAULT '[]', incidents TEXT, orders_ TEXT, visitors TEXT, note TEXT,
  created TEXT, created_by TEXT, updated TEXT, updated_by TEXT, UNIQUE(project_id, day));
CREATE TABLE IF NOT EXISTS journal_photos (
  id TEXT PRIMARY KEY, journal_id TEXT NOT NULL, sort INTEGER DEFAULT 0, file TEXT, comment TEXT, created TEXT, deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_journal_proj ON journal(project_id, day);
CREATE INDEX IF NOT EXISTS ix_def_proj ON defects(project_id);
CREATE INDEX IF NOT EXISTS ix_photo_def ON photos(defect_id);
"""

BKP_DEFAULT = [
 ('211','Baumeisterarbeiten'),('212','Vorfabrizierte Rohbauelemente'),('213','Montagebau in Stahl'),('214','Montagebau in Holz'),('215','Montagebau in Leichtmetall'),('216','Natur- und Kunststeinarbeiten'),('217','Spezielle Rohbauarbeiten'),('219','Übriges Rohbau 1'),
 ('221','Fenster, Aussentüren, Tore'),('222','Spenglerarbeiten'),('223','Blitzschutzanlagen'),('224','Bedachungsarbeiten'),('225','Spezielle Dichtungen und Dämmungen'),('226','Fassadenputze'),('227','Äussere Oberflächenbehandlungen'),('228','Äussere Abschlüsse, Sonnenschutz'),('229','Übriges Rohbau 2'),
 ('231','Apparate Starkstrom'),('232','Starkstrominstallationen'),('233','Leuchten und Lampen'),('234','Elektrogeräte'),('235','Apparate Schwachstrom'),('236','Schwachstrominstallationen'),('237','Gebäudeautomation'),('238','Provisorische Elektroinstallationen'),('239','Übriges Elektro'),
 ('241','Zentrale Anlagen HLK'),('242','Wärmeerzeugung'),('243','Wärmeverteilung'),('244','Lüftungsanlagen'),('245','Klimaanlagen'),('246','Kälteanlagen'),('247','Spezialanlagen HLK'),('248','Dämmungen HLK'),('249','Übriges HLK'),
 ('251','Allgemeine Sanitärapparate'),('252','Spezielle Sanitärapparate'),('253','Sanitärleitungen'),('254','Sanitärleitungen speziell'),('255','Dämmungen Sanitär'),('256','Installationselemente Sanitär'),('257','Spezialanlagen Sanitär'),('258','Kücheneinrichtungen'),('259','Übriges Sanitär'),
 ('261','Aufzüge'),('262','Fahrtreppen, Fahrsteige'),('263','Spezielle Transportanlagen'),('269','Übriges Transportanlagen'),
 ('271','Gipserarbeiten'),('272','Metallbauarbeiten'),('273','Schreinerarbeiten'),('274','Innere Verglasungen'),('275','Schliessanlagen'),('276','Innere Abschlüsse'),('277','Innere Trennwände, Schrankanlagen'),('278','Spezielle Ausbauarbeiten'),('279','Übriges Ausbau 1'),
 ('281','Bodenbeläge'),('282','Wandbeläge'),('283','Deckenbekleidungen'),('284','Öfen, Cheminées'),('285','Innere Oberflächenbehandlungen (Malerarbeiten)'),('286','Austrocknung'),('287','Baureinigung'),('288','Spezielle Ausbauarbeiten 2'),('289','Übriges Ausbau 2'),
 ('291','Architekt'),('292','Bauingenieur'),('293','Elektroingenieur'),('294','HLK-Ingenieur'),('295','Sanitäringenieur'),('296','Spezialisten'),('297','Bauleitung / Bautreuhand'),('298','Übrige Honorare'),('299','Übriges Honorare')]

ACCESS_MAIL_DEFAULT = {
    "subject": "Ihr Zugang zum MängelManagement – {projekt}",
    "body": "{anrede},\n\nSie sind im MängelManagement für das Projekt {projekt} als Unternehmer erfasst. Darin sehen Sie Ihre Pendenzen mit Plan und Fotos und können erledigte Arbeiten mit Beweisfoto als «bearbeitet» melden.\n\nLink: {link}\nZugangsname: {zugangsname}\nPasswort: {passwort}\n\nBeim ersten Anmelden werden Sie aufgefordert, ein eigenes Passwort zu setzen.\n\nFreundliche Grüsse\n{absender}\n{firma}"}

def init_db():
    c = db()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(defects)")}
    if "photos_purged" not in cols: c.execute("ALTER TABLE defects ADD COLUMN photos_purged TEXT")
    ccols = {r[1] for r in c.execute("PRAGMA table_info(contractors)")}
    if "inactive" not in ccols: c.execute("ALTER TABLE contractors ADD COLUMN inactive INTEGER DEFAULT 0")
    ucols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    if "prefs" not in ucols: c.execute("ALTER TABLE users ADD COLUMN prefs TEXT DEFAULT '{}'")
    if "updated" not in ccols: c.execute("ALTER TABLE contractors ADD COLUMN updated TEXT")
    pcols = {r[1] for r in c.execute("PRAGMA table_info(projects)")}
    if "del_by" not in pcols: c.execute("ALTER TABLE projects ADD COLUMN del_by TEXT"); c.execute("ALTER TABLE projects ADD COLUMN del_at TEXT")
    if "address" not in pcols: c.execute("ALTER TABLE projects ADD COLUMN address TEXT"); c.execute("ALTER TABLE projects ADD COLUMN lat REAL"); c.execute("ALTER TABLE projects ADD COLUMN lon REAL")
    c.execute("INSERT OR IGNORE INTO contractor_users SELECT id, user_id FROM contractors WHERE user_id IS NOT NULL")
    if not c.execute("SELECT 1 FROM settings WHERE key='accessMail'").fetchone():
        c.execute("INSERT INTO settings VALUES('accessMail',?)", (json.dumps(ACCESS_MAIL_DEFAULT, ensure_ascii=False),))
    if not c.execute("SELECT 1 FROM settings WHERE key='retention'").fetchone():
        c.execute("INSERT INTO settings VALUES('retention',?)", (json.dumps({"enabled": True, "days": 30}),))
    if not c.execute("SELECT 1 FROM settings WHERE key='bkp'").fetchone():
        c.execute("INSERT INTO settings VALUES('bkp',?)", (json.dumps([{"code":a,"name":b} for a,b in BKP_DEFAULT], ensure_ascii=False),))
    if not c.execute("SELECT 1 FROM settings WHERE key='company'").fetchone():
        c.execute("INSERT INTO settings VALUES('company',?)", (json.dumps({"name":"Dietziker Partner Baumanagement AG","addr":"Grosspeteranlage 29 ▪ 4052 Basel","contact":"T +41 61 266 50 00 ▪ info@dietziker-bm.ch ▪ www.dietziker-bm.ch","slogan":"Gemeinsam erfolgreich bauen"}, ensure_ascii=False),))
    if not c.execute("SELECT 1 FROM users").fetchone():
        pw = os.environ.get("MM_ADMIN_PW") or "start1234"
        email = os.environ.get("MM_ADMIN_EMAIL") or "wi_arch@hotmail.com"
        c.execute("INSERT INTO users(id,email,pw,role,name,must_change,active,created) VALUES(?,?,?,?,?,?,?,?)", (uid(), email, hash_pw(pw), "superadmin", "Superadmin", 1, 1, now()))
        print(f"\n  Superadmin-Konto angelegt:  {email}  /  Passwort: {pw}   (beim ersten Login ändern)\n")
    if not c.execute("SELECT 1 FROM users WHERE role='superadmin'").fetchone():
        row = c.execute("SELECT id FROM users WHERE role='bauleiter' AND active=1 ORDER BY created LIMIT 1").fetchone()
        if row: c.execute("UPDATE users SET role='superadmin' WHERE id=?", (row["id"],))
    c.commit(); c.close()

init_db()

# ----------------------------------------------------------------- Auth
def current_user(request: Request):
    tok = request.cookies.get("mm_session")
    if not tok: return None
    c = db()
    row = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND u.active=1", (tok,)).fetchone()
    if row: c.execute("UPDATE sessions SET last=? WHERE token=?", (now(), tok)); c.commit()
    c.close()
    return dict(row) if row else None

BL = ("superadmin", "bauleiter")          # Bauleitungs-Rechte
def is_sa(u): return u["role"] == "superadmin"
def is_bl(u): return u["role"] in BL

def require(request: Request, roles=None):
    u = current_user(request)
    if not u: raise HTTPException(401, "Nicht angemeldet")
    if roles:
        allowed = set(roles) | ({"superadmin"} if "bauleiter" in roles else set())
        if u["role"] not in allowed: raise HTTPException(403, "Keine Berechtigung")
    return u

def user_projects(c, u):
    """Projekt-IDs, die der Benutzer sehen darf."""
    if u["role"] == "superadmin":
        return [r["id"] for r in c.execute("SELECT id FROM projects WHERE archived=0")]
    if u["role"] == "unternehmer":
        return [r["project_id"] for r in c.execute("SELECT DISTINCT ct.project_id FROM contractor_users cu JOIN contractors ct ON ct.id=cu.contractor_id WHERE cu.user_id=? AND ct.deleted=0", (u["id"],))]
    return [r["project_id"] for r in c.execute("SELECT project_id FROM project_users WHERE user_id=?", (u["id"],))]

def own_contractor_ids(c, u, project_id):
    return [r["id"] for r in c.execute("SELECT ct.id FROM contractor_users cu JOIN contractors ct ON ct.id=cu.contractor_id WHERE ct.project_id=? AND cu.user_id=? AND ct.deleted=0", (project_id, u["id"]))]

def access_mail_text(c):
    row = c.execute("SELECT value FROM settings WHERE key='accessMail'").fetchone()
    try: m = json.loads(row["value"]) if row else {}
    except Exception: m = {}
    return {"subject": m.get("subject") or ACCESS_MAIL_DEFAULT["subject"], "body": m.get("body") or ACCESS_MAIL_DEFAULT["body"]}

def send_access_mail(c, request, u, ct, usr, pw, text=None):
    """Zugangsdaten-Mail an einen Unternehmer-Login. text = {subject, body} mit Platzhaltern."""
    import html as _h
    proj = c.execute("SELECT name, number FROM projects WHERE id=?", (ct["project_id"],)).fetchone()
    co = {}
    row = c.execute("SELECT value FROM settings WHERE key='company'").fetchone()
    if row:
        try: co = json.loads(row["value"])
        except Exception: pass
    url = (co.get("appUrl") or str(request.base_url)).rstrip("/") + "/"
    anrede = {"Herr": f"Sehr geehrter Herr {ct['last_name'] or ''}".strip(), "Frau": f"Sehr geehrte Frau {ct['last_name'] or ''}".strip()}.get(ct["salutation"] or "", "Sehr geehrte Damen und Herren")
    pname = ((proj["number"] + " ") if proj and proj["number"] else "") + (proj["name"] if proj else "")
    vals = {"anrede": anrede, "projekt": pname, "link": url, "zugangsname": usr["email"], "passwort": pw, "absender": u.get("name") or u["email"], "firma": co.get("name") or "", "unternehmer": ct["name"] or ""}
    txt = text if (text and text.get("body")) else access_mail_text(c)
    def fill(s):
        for k, v in vals.items(): s = s.replace("{" + k + "}", str(v))
        return s
    subject = fill(txt.get("subject") or ACCESS_MAIL_DEFAULT["subject"]); body_ = fill(txt["body"])
    html = '<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:11pt;color:#222">' + _h.escape(body_).replace(_h.escape(url), f'<a href="{url}">{url}</a>').replace("\n", "<br>") + "</body></html>"
    cfg = smtp_cfg()
    smtp_send(cfg, [usr["email"]], subject, html, [], [u["email"]] if cfg.get("ccSelf") else None)
    log(c, ct["project_id"], None, u, "zugang_mail", f"{ct['name']} <{usr['email']}>")

def create_contractor_login(c, cid, email, name):
    """Legt (falls nötig) einen Unternehmer-Benutzer an und verknüpft ihn. Gibt (user_id, passwort|None, fehler|None)."""
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email): return None, None, "keine gültige E-Mail"
    row = c.execute("SELECT id, role FROM users WHERE lower(email)=?", (email,)).fetchone()
    if row:
        if row["role"] != "unternehmer": return None, None, "E-Mail gehört zu einem Bauleiter/Bauherr-Konto"
        user_id = row["id"]; pw = None
        c.execute("UPDATE users SET active=1 WHERE id=?", (user_id,))
    else:
        user_id = uid(); pw = secrets.token_urlsafe(7)
        c.execute("INSERT INTO users(id,email,pw,role,name,must_change,active,created) VALUES(?,?,?,?,?,?,?,?)", (user_id, email, hash_pw(pw), "unternehmer", name or "", 1, 1, now()))
    c.execute("INSERT OR IGNORE INTO contractor_users VALUES(?,?)", (cid, user_id))
    if not c.execute("SELECT user_id FROM contractors WHERE id=?", (cid,)).fetchone()["user_id"]: c.execute("UPDATE contractors SET user_id=? WHERE id=?", (user_id, cid))
    return user_id, pw, None

def contractor_logins(c, cid):
    return [dict(r) for r in c.execute("SELECT u.id AS userId, u.email, u.name, u.must_change AS mustChange, u.active FROM contractor_users cu JOIN users u ON u.id=cu.user_id WHERE cu.contractor_id=? ORDER BY u.email", (cid,))]

def contractor_emails(c, cid):
    ct = c.execute("SELECT email FROM contractors WHERE id=?", (cid,)).fetchone()
    out = []
    if ct and ct["email"]: out.append(ct["email"].strip().lower())
    for l in contractor_logins(c, cid):
        if l["active"] and l["email"] and l["email"].lower() not in out: out.append(l["email"].lower())
    return out

def log(c, project_id, defect_id, u, action, detail=""):
    c.execute("INSERT INTO history(project_id,defect_id,ts,user_id,user_name,action,detail) VALUES(?,?,?,?,?,?,?)",
              (project_id, defect_id, now(), u["id"], u.get("name") or u["email"], action, detail))

async def body(request: Request):
    try: return await request.json()
    except Exception: return {}

@app.post("/api/login")
async def login(request: Request, response: Response):
    d = await body(request)
    email = (d.get("email") or "").strip().lower(); pw = d.get("password") or ""
    c = db(); row = c.execute("SELECT * FROM users WHERE lower(email)=? AND active=1", (email,)).fetchone()
    if not row or not check_pw(pw, row["pw"]):
        c.close(); raise HTTPException(401, "E-Mail oder Passwort falsch")
    tok = secrets.token_urlsafe(32)
    c.execute("INSERT INTO sessions VALUES(?,?,?,?)", (tok, row["id"], now(), now())); c.commit(); c.close()
    response.set_cookie("mm_session", tok, httponly=True, samesite="lax", max_age=60*60*24*90)
    return {"ok": True, "user": pub_user(dict(row))}

@app.post("/api/logout")
async def logout(request: Request, response: Response):
    tok = request.cookies.get("mm_session")
    if tok:
        c = db(); c.execute("DELETE FROM sessions WHERE token=?", (tok,)); c.commit(); c.close()
    response.delete_cookie("mm_session"); return {"ok": True}

def user_prefs(u):
    try: p = json.loads(u.get("prefs") or "{}")
    except Exception: p = {}
    return p if isinstance(p, dict) else {}

def pub_user(u): return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"], "mustChange": bool(u["must_change"]), "prefs": user_prefs(u)}

@app.get("/api/me")
async def me(request: Request):
    u = current_user(request)
    if not u: return {"user": None}
    return {"user": pub_user(u)}

@app.post("/api/me/prefs")
async def me_prefs(request: Request):
    """Persönliche Einstellungen (Sync-Verhalten, Anleitung gesehen …) – für alle Rollen."""
    u = require(request); d = await body(request)
    if not isinstance(d, dict): raise HTTPException(400)
    p = user_prefs(u); p.update(d)
    c = db(); c.execute("UPDATE users SET prefs=? WHERE id=?", (json.dumps(p, ensure_ascii=False), u["id"])); c.commit(); c.close()
    return {"ok": True, "prefs": p}

@app.post("/api/change-password")
async def change_password(request: Request):
    u = require(request); d = await body(request)
    old, new = d.get("old") or "", d.get("new") or ""
    if len(new) < 8: raise HTTPException(400, "Neues Passwort: mindestens 8 Zeichen")
    c = db(); row = c.execute("SELECT pw FROM users WHERE id=?", (u["id"],)).fetchone()
    if not u["must_change"] and not check_pw(old, row["pw"]): c.close(); raise HTTPException(400, "Altes Passwort falsch")
    c.execute("UPDATE users SET pw=?, must_change=0 WHERE id=?", (hash_pw(new), u["id"])); c.commit(); c.close()
    return {"ok": True}

# ----------------------------------------------------------------- Benutzer (Bauleiter)
def visible_users(c, u):
    """Superadmin: alle. Bauleiter: Bauherren/Unternehmer seiner Projekte (und sich selbst)."""
    rows = [dict(r) for r in c.execute("SELECT id,email,name,role,must_change,active,created FROM users ORDER BY role,name")]
    for r in rows:
        r["projects"] = [x["project_id"] for x in c.execute("SELECT project_id FROM project_users WHERE user_id=?", (r["id"],))]
        r["contractors"] = [dict(x) for x in c.execute("SELECT ct.id,ct.project_id,ct.name FROM contractor_users cu JOIN contractors ct ON ct.id=cu.contractor_id WHERE cu.user_id=? AND ct.deleted=0", (r["id"],))]
    if is_sa(u): return rows
    mine = set(user_projects(c, u))
    def ok(r):
        if r["id"] == u["id"]: return True
        if r["role"] in ("superadmin", "bauleiter"): return False
        if r["role"] == "bauherr": return bool(mine & set(r["projects"]))
        return any(x["project_id"] in mine for x in r["contractors"])
    return [r for r in rows if ok(r)]

@app.get("/api/users")
async def users_list(request: Request):
    u = require(request, ["bauleiter"]); c = db(); rows = visible_users(c, u); c.close(); return rows

@app.post("/api/users")
async def users_save(request: Request):
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
    email = (d.get("email") or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email): c.close(); raise HTTPException(400, "Ungültige E-Mail")
    role = d.get("role") if d.get("role") in ("superadmin","bauleiter","unternehmer","bauherr") else "bauherr"
    if not is_sa(u):
        if role in ("superadmin", "bauleiter"): c.close(); raise HTTPException(403, "Nur der Superadmin kann Bauleiter anlegen")
        if d.get("id") and d["id"] not in {r["id"] for r in visible_users(c, u)}: c.close(); raise HTTPException(403, "Kein Zugriff auf diesen Benutzer")
        mine = set(user_projects(c, u))
        if "projects" in d and not set(d["projects"]) <= mine: c.close(); raise HTTPException(403, "Nur eigene Projekte zuweisbar")
    if d.get("id") == u["id"] and role != u["role"]: c.close(); raise HTTPException(400, "Eigene Rolle kann nicht geändert werden")
    if d.get("id"):
        c.execute("UPDATE users SET email=?, name=?, role=?, active=? WHERE id=?", (email, d.get("name") or "", role, 1 if d.get("active", True) else 0, d["id"]))
        if d.get("password"): c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (hash_pw(d["password"]), d["id"]))
        user_id = d["id"]; pw = d.get("password")
    else:
        if c.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone(): c.close(); raise HTTPException(400, "E-Mail bereits vergeben")
        pw = d.get("password") or secrets.token_urlsafe(6)
        user_id = uid()
        c.execute("INSERT INTO users(id,email,pw,role,name,must_change,active,created) VALUES(?,?,?,?,?,?,?,?)", (user_id, email, hash_pw(pw), role, d.get("name") or "", 1, 1, now()))
    if "projects" in d:
        c.execute("DELETE FROM project_users WHERE user_id=?", (user_id,))
        for pid in d["projects"]: c.execute("INSERT OR IGNORE INTO project_users VALUES(?,?)", (pid, user_id))
    c.commit(); c.close()
    return {"ok": True, "id": user_id, "initialPassword": pw}

@app.delete("/api/users/{user_id}")
async def users_delete(request: Request, user_id: str):
    u = require(request, ["bauleiter"])
    if user_id == u["id"]: raise HTTPException(400, "Eigenes Konto kann nicht gelöscht werden")
    c = db()
    if not is_sa(u) and user_id not in {r["id"] for r in visible_users(c, u)}: c.close(); raise HTTPException(403, "Kein Zugriff auf diesen Benutzer")
    c.execute("UPDATE users SET active=0 WHERE id=?", (user_id,)); c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    c.execute("UPDATE contractors SET user_id=NULL WHERE user_id=?", (user_id,)); c.execute("DELETE FROM contractor_users WHERE user_id=?", (user_id,)); c.commit(); c.close(); return {"ok": True}

# ----------------------------------------------------------------- Projekte
def project_access(c, u, pid):
    if pid not in user_projects(c, u): raise HTTPException(403, "Kein Zugriff auf dieses Projekt")

@app.get("/api/projects")
async def projects_list(request: Request):
    u = require(request); c = db(); ids = user_projects(c, u)
    rows = [dict(r) for r in c.execute("SELECT id,name,number,created,archived,del_by,del_at,address,lat,lon FROM projects WHERE archived=0 ORDER BY name")]
    rows = [r for r in rows if r["id"] in ids]
    for r in rows:
        r["defects"] = c.execute("SELECT COUNT(*) FROM defects WHERE project_id=? AND deleted=0", (r["id"],)).fetchone()[0]
        if r["del_by"]:
            ub = c.execute("SELECT name,email FROM users WHERE id=?", (r["del_by"],)).fetchone()
            r["deleteRequest"] = {"byId": r["del_by"], "by": (ub["name"] or ub["email"]) if ub else "?", "at": r["del_at"], "mine": r["del_by"] == u["id"]}
        else: r["deleteRequest"] = None
        del r["del_by"]; del r["del_at"]
    c.close(); return rows

@app.post("/api/projects")
async def project_save(request: Request):
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
    geo = None
    if d.get("id"):
        project_access(c, u, d["id"]); pid = d["id"]
        c.execute("UPDATE projects SET name=?, number=? WHERE id=?", (d.get("name") or "", d.get("number") or "", pid))
    else:
        if not is_sa(u): c.close(); raise HTTPException(403, "Nur der Superadmin legt Projekte an")
        pid = uid(); c.execute("INSERT INTO projects(id,name,number,created) VALUES(?,?,?,?)", (pid, d.get("name") or "Neues Projekt", d.get("number") or "", now()))
    if "address" in d or "lat" in d:
        addr = (d.get("address") or "").strip(); lat = d.get("lat"); lon = d.get("lon")
        if addr and (lat is None or lon is None):
            geo = geocode(addr)
            if geo: lat, lon = geo["lat"], geo["lon"]; addr = addr or geo["label"]
        c.execute("UPDATE projects SET address=?, lat=?, lon=? WHERE id=?", (addr, lat, lon, pid))
    c.commit(); c.close(); return {"ok": True, "id": pid, "geo": geo, "lat": d.get("lat") if geo is None else geo["lat"], "lon": d.get("lon") if geo is None else geo["lon"]}

def can_approve_delete(c, u, pid):
    """Superadmin oder dem Projekt zugewiesener Bauleiter."""
    if is_sa(u): return True
    return u["role"] == "bauleiter" and bool(c.execute("SELECT 1 FROM project_users WHERE project_id=? AND user_id=?", (pid, u["id"])).fetchone())

@app.post("/api/projects/{pid}/delete-request")
async def project_delete_request(request: Request, pid: str):
    """1. Freigabe: Löschung beantragen. 2. Freigabe durch eine andere berechtigte Person -> archiviert."""
    u = require(request, ["bauleiter"]); c = db(); project_access(c, u, pid)
    if not can_approve_delete(c, u, pid): c.close(); raise HTTPException(403, "Nur zugewiesene Bauleiter oder der Superadmin")
    p = c.execute("SELECT del_by, name FROM projects WHERE id=?", (pid,)).fetchone()
    if p["del_by"] and p["del_by"] != u["id"]:
        c.execute("UPDATE projects SET archived=1, del_by=NULL, del_at=NULL WHERE id=?", (pid,))
        log(c, pid, None, u, "projekt_geloescht", f"{p['name']} – 2. Freigabe"); c.commit(); c.close(); return {"ok": True, "deleted": True}
    if p["del_by"] == u["id"]: c.close(); raise HTTPException(400, "Sie haben die Löschung bereits beantragt – eine zweite Person muss bestätigen")
    c.execute("UPDATE projects SET del_by=?, del_at=? WHERE id=?", (u["id"], now(), pid))
    log(c, pid, None, u, "projekt_loeschantrag", p["name"]); c.commit(); c.close(); return {"ok": True, "deleted": False}

@app.delete("/api/projects/{pid}/delete-request")
async def project_delete_withdraw(request: Request, pid: str):
    u = require(request, ["bauleiter"]); c = db(); project_access(c, u, pid)
    p = c.execute("SELECT del_by FROM projects WHERE id=?", (pid,)).fetchone()
    if p["del_by"] and (p["del_by"] == u["id"] or is_sa(u)):
        c.execute("UPDATE projects SET del_by=NULL, del_at=NULL WHERE id=?", (pid,)); log(c, pid, None, u, "projekt_loeschantrag_zurueck", ""); c.commit()
    c.close(); return {"ok": True}

@app.get("/api/projects/{pid}/members")
async def project_members(request: Request, pid: str):
    u = require(request, ["bauleiter"]); c = db(); project_access(c, u, pid)
    rows = [dict(r) for r in c.execute("SELECT u.id,u.name,u.email,u.role,u.active FROM project_users pu JOIN users u ON u.id=pu.user_id WHERE pu.project_id=? ORDER BY u.role,u.name", (pid,))]
    ctrs = [dict(r) for r in c.execute("SELECT id,name,bkp,email,inactive FROM contractors WHERE project_id=? AND deleted=0 ORDER BY bkp,name", (pid,))]
    for ct in ctrs: ct["logins"] = contractor_logins(c, ct["id"])
    c.close(); return {"users": rows, "contractors": ctrs}

@app.delete("/api/projects/{pid}/members/{user_id}")
async def project_member_remove(request: Request, pid: str, user_id: str):
    u = require(request, ["bauleiter"]); c = db(); project_access(c, u, pid)
    tgt = c.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if not tgt: c.close(); raise HTTPException(404)
    if tgt["role"] in ("bauleiter", "superadmin") and not is_sa(u): c.close(); raise HTTPException(403, "Bauleiter kann nur der Superadmin aus dem Projekt nehmen")
    c.execute("DELETE FROM project_users WHERE project_id=? AND user_id=?", (pid, user_id)); log(c, pid, None, u, "mitglied_entfernt", user_id); c.commit(); c.close(); return {"ok": True}

@app.post("/api/projects/{pid}/members")
async def project_member_add(request: Request, pid: str):
    """{userId} – Bauherr (Bauleiter+SA) oder Bauleiter (nur SA) dem Projekt zuweisen."""
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); project_access(c, u, pid)
    tgt = c.execute("SELECT role FROM users WHERE id=? AND active=1", (d.get("userId"),)).fetchone()
    if not tgt or tgt["role"] not in ("bauleiter", "bauherr"): c.close(); raise HTTPException(400, "Nur Bauleiter oder Bauherren")
    if tgt["role"] == "bauleiter" and not is_sa(u): c.close(); raise HTTPException(403, "Bauleiter weist nur der Superadmin zu")
    c.execute("INSERT OR IGNORE INTO project_users VALUES(?,?)", (pid, d["userId"])); log(c, pid, None, u, "mitglied_hinzu", d["userId"]); c.commit(); c.close(); return {"ok": True}

@app.get("/api/users/assignable")
async def users_assignable(request: Request):
    u = require(request, ["bauleiter"]); c = db()
    roles = ("bauleiter", "bauherr") if is_sa(u) else ("bauherr",)
    rows = [dict(r) for r in c.execute(f"SELECT id,name,email,role FROM users WHERE active=1 AND role IN ({','.join('?'*len(roles))}) ORDER BY role,name", roles)]
    c.close(); return rows

@app.get("/api/projects/{pid}/full")
async def project_full(request: Request, pid: str):
    """Alles zu einem Projekt – gefiltert nach Rolle."""
    u = require(request); c = db(); project_access(c, u, pid)
    p = dict(c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    plans = [dict(r) for r in c.execute("SELECT * FROM plans WHERE project_id=? AND deleted=0 ORDER BY sort,added", (pid,))]
    for pl in plans: pl["src"] = f"/api/plans/{pl['id']}/image?v={pl.get('replaced') or pl.get('added') or ''}"; pl["history"] = json.loads(pl.get("history") or "[]")
    ctrs = [dict(r) for r in c.execute("SELECT * FROM contractors WHERE project_id=? AND deleted=0 ORDER BY bkp,name", (pid,))]
    for ct in ctrs:
        ct["phones"] = json.loads(ct.get("phones") or "[]"); ct["logins"] = contractor_logins(c, ct["id"]); ct["emails"] = contractor_emails(c, ct["id"])
    defs = [dict(r) for r in c.execute("SELECT * FROM defects WHERE project_id=? AND deleted=0 ORDER BY nr", (pid,))]
    mine = None
    if u["role"] == "unternehmer":
        mine = set(own_contractor_ids(c, u, pid)); defs = [d for d in defs if d["contractor_id"] in mine]
        ctrs = [ct for ct in ctrs if ct["id"] in mine]
    for d in defs:
        ph = [dict(r) for r in c.execute("SELECT id,kind,sort FROM photos WHERE defect_id=? AND deleted=0 ORDER BY kind,sort", (d["id"],))]
        d["photos"] = [f"/api/photos/{x['id']}" for x in ph if x["kind"] == "photo"]
        d["proofPhotos"] = [f"/api/photos/{x['id']}" for x in ph if x["kind"] == "proof"]
        d["photoIds"] = [x["id"] for x in ph if x["kind"] == "photo"]; d["proofIds"] = [x["id"] for x in ph if x["kind"] == "proof"]
    hist = [dict(r) for r in c.execute("SELECT defect_id,ts,user_name,action,detail FROM history WHERE project_id=? ORDER BY id DESC LIMIT 500", (pid,))]
    if u["role"] == "unternehmer":
        own = {d["id"] for d in defs}; hist = [h for h in hist if h["defect_id"] in own]
    c.close()
    return {"project": {"id": p["id"], "name": p["name"], "number": p["number"], "currentPlanId": p["current_plan"], "settings": json.loads(p["settings"] or "{}"), "address": p.get("address") or "", "lat": p.get("lat"), "lon": p.get("lon")},
            "plans": plans, "contractors": ctrs, "defects": defs, "history": hist, "role": u["role"], "now": now()}

@app.get("/api/projects/{pid}/changes")
async def project_changes(request: Request, pid: str, since: str = ""):
    """Was hat sich seit `since` (ISO) geändert? Für die Nachfrage „N neue/geänderte Mängel – aktualisieren?“ ohne alles zu laden."""
    u = require(request); c = db(); project_access(c, u, pid)
    since = since or "0000"
    q = "SELECT COUNT(*) FROM defects WHERE project_id=? AND (updated>? OR created>?)"; args = [pid, since, since]
    if u["role"] == "unternehmer":
        mine = own_contractor_ids(c, u, pid)
        if not mine: c.close(); return {"defects": 0, "new": 0, "plans": 0, "contractors": 0, "now": now()}
        q += f" AND contractor_id IN ({','.join('?'*len(mine))})"; args += mine
    n = c.execute(q, args).fetchone()[0]
    nn = c.execute(q.replace("(updated>? OR created>?)", "created>? AND ?<>''"), args).fetchone()[0]
    npl = c.execute("SELECT COUNT(*) FROM plans WHERE project_id=? AND (added>? OR replaced>?)", (pid, since, since)).fetchone()[0]
    nct = c.execute("SELECT COUNT(*) FROM contractors WHERE project_id=? AND updated>?", (pid, since)).fetchone()[0]
    c.close(); return {"defects": n, "new": nn, "plans": npl, "contractors": nct, "now": now()}

@app.post("/api/projects/{pid}/settings")
async def project_settings(request: Request, pid: str):
    u = require(request); d = await body(request); c = db(); project_access(c, u, pid)
    if "currentPlanId" in d: c.execute("UPDATE projects SET current_plan=? WHERE id=?", (d["currentPlanId"], pid))
    if "settings" in d and is_bl(u): c.execute("UPDATE projects SET settings=? WHERE id=?", (json.dumps(d["settings"], ensure_ascii=False), pid))
    c.commit(); c.close(); return {"ok": True}

# ----------------------------------------------------------------- Pläne
def save_dataurl(dataurl: str, folder: Path, name: str) -> str:
    m = re.match(r"^data:(image/[\w+]+);base64,(.*)$", dataurl or "", re.S)
    if not m: raise HTTPException(400, "Kein Bild")
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/svg+xml": "svg"}.get(m.group(1), "jpg")
    fn = f"{name}.{ext}"; (folder / fn).write_bytes(base64.b64decode(m.group(2))); return fn

@app.post("/api/projects/{pid}/plans")
async def plan_save(request: Request, pid: str):
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); project_access(c, u, pid)
    if d.get("id"):
        pl = c.execute("SELECT * FROM plans WHERE id=?", (d["id"],)).fetchone()
        if not pl: raise HTTPException(404)
        if d.get("src"):  # neue Version
            hist = json.loads(pl["history"] or "[]")
            hist.append({"version": pl["version"] or "", "note": pl["note"] or "", "file": pl["file"], "from": pl["replaced"] or pl["added"], "to": now(), "pins": d.get("pins", 0), "calibrated": bool(d.get("calibrated"))})
            hist = hist[-5:]
            fn = save_dataurl(d["src"], PLANS, uid())
            c.execute("UPDATE plans SET file=?, replaced=?, version=?, note=?, history=? WHERE id=?", (fn, now(), d.get("version") or "", d.get("note") or "", json.dumps(hist, ensure_ascii=False), d["id"]))
            # Pins umrechnen
            if d.get("affine"):
                A = d["affine"]
                for df in c.execute("SELECT id,x,y FROM defects WHERE plan_id=? AND deleted=0", (d["id"],)).fetchall():
                    nx = A["x"][0]*df["x"] + A["x"][1]*df["y"] + A["x"][2]; ny = A["y"][0]*df["x"] + A["y"][1]*df["y"] + A["y"][2]
                    c.execute("UPDATE defects SET x=?, y=?, updated=? WHERE id=?", (min(1, max(0, nx)), min(1, max(0, ny)), now(), df["id"]))
            log(c, pid, None, u, "plan_version", f"{pl['name']}: Version {d.get('version') or '–'}")
        if "name" in d: c.execute("UPDATE plans SET name=? WHERE id=?", (d["name"], d["id"]))
        if "sort" in d: c.execute("UPDATE plans SET sort=? WHERE id=?", (int(d["sort"]), d["id"]))
        plid = d["id"]
    else:
        plid = uid(); fn = save_dataurl(d.get("src"), PLANS, plid)
        sort = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM plans WHERE project_id=?", (pid,)).fetchone()[0]
        c.execute("INSERT INTO plans(id,project_id,name,sort,version,note,added,file) VALUES(?,?,?,?,?,?,?,?)", (plid, pid, d.get("name") or "Plan", sort, d.get("version") or "", "", now(), fn))
        log(c, pid, None, u, "plan_add", d.get("name") or "")
    c.commit(); c.close(); return {"ok": True, "id": plid}

@app.post("/api/projects/{pid}/plans/order")
async def plan_order(request: Request, pid: str):
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); project_access(c, u, pid)
    for i, plid in enumerate(d.get("ids", [])): c.execute("UPDATE plans SET sort=? WHERE id=? AND project_id=?", (i, plid, pid))
    c.commit(); c.close(); return {"ok": True}

@app.delete("/api/plans/{plid}")
async def plan_delete(request: Request, plid: str):
    u = require(request, ["bauleiter"]); c = db()
    pl = c.execute("SELECT project_id,name FROM plans WHERE id=?", (plid,)).fetchone()
    if not pl: raise HTTPException(404)
    c.execute("UPDATE plans SET deleted=1 WHERE id=?", (plid,)); c.execute("UPDATE defects SET deleted=1 WHERE plan_id=?", (plid,))
    log(c, pl["project_id"], None, u, "plan_delete", pl["name"]); c.commit(); c.close(); return {"ok": True}

@app.get("/api/plans/{plid}/image")
async def plan_image(request: Request, plid: str):
    u = require(request); c = db(); pl = c.execute("SELECT project_id,file FROM plans WHERE id=?", (plid,)).fetchone(); c.close()
    if not pl: raise HTTPException(404)
    c = db(); project_access(c, u, pl["project_id"]); c.close()
    return FileResponse(PLANS / pl["file"], headers={"Cache-Control": "private, max-age=86400"})

# ----------------------------------------------------------------- Unternehmer
@app.post("/api/projects/{pid}/contractors")
async def contractor_save(request: Request, pid: str):
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); project_access(c, u, pid)
    vals = (d.get("name") or "", d.get("bkp") or "", d.get("trade") or "", d.get("email") or "", d.get("salutation") or "", d.get("firstName") or "", d.get("lastName") or "", d.get("address") or "", json.dumps(d.get("phones") or [], ensure_ascii=False), d.get("note") or "")
    cid = d.get("id") or uid()
    if d.get("id"):
        c.execute("UPDATE contractors SET name=?,bkp=?,trade=?,email=?,salutation=?,first_name=?,last_name=?,address=?,phones=?,note=?,updated=? WHERE id=? AND project_id=?", vals + (now(), cid, pid))
    else:
        c.execute("INSERT INTO contractors(id,project_id,name,bkp,trade,email,salutation,first_name,last_name,address,phones,note,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (cid, pid) + vals + (now(),))
    # Logins: Liste von E-Mails (neue werden als Unternehmer-Benutzer angelegt und verknüpft)
    wanted = [e.strip().lower() for e in (d.get("logins") or []) if e and e.strip()]
    if d.get("createLogin") and d.get("email"): wanted.append(d["email"].strip().lower())
    created = []
    for email in dict.fromkeys(wanted):
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email): continue
        row = c.execute("SELECT id, role FROM users WHERE lower(email)=?", (email,)).fetchone()
        if row:
            if row["role"] != "unternehmer": continue   # Bauleiter/Bauherr-Konten nicht umhängen
            user_id = row["id"]; pw = None
        else:
            user_id = uid(); pw = secrets.token_urlsafe(7)
            c.execute("INSERT INTO users(id,email,pw,role,name,must_change,active,created) VALUES(?,?,?,?,?,?,?,?)", (user_id, email, hash_pw(pw), "unternehmer", d.get("name") or "", 1, 1, now()))
        c.execute("INSERT OR IGNORE INTO contractor_users VALUES(?,?)", (cid, user_id))
        if not c.execute("SELECT user_id FROM contractors WHERE id=?", (cid,)).fetchone()["user_id"]: c.execute("UPDATE contractors SET user_id=? WHERE id=?", (user_id, cid))
        created.append({"userId": user_id, "email": email, "password": pw})
    c.commit(); c.close()
    first = next((x for x in created if x["password"]), None)
    return {"ok": True, "id": cid, "created": created, "initialPassword": first["password"] if first else None, "initialUserId": first["userId"] if first else None}

@app.delete("/api/contractors/{cid}/logins/{user_id}")
async def contractor_login_remove(request: Request, cid: str, user_id: str):
    u = require(request, ["bauleiter"]); c = db()
    ct = c.execute("SELECT project_id FROM contractors WHERE id=?", (cid,)).fetchone()
    if not ct: c.close(); raise HTTPException(404)
    project_access(c, u, ct["project_id"])
    c.execute("DELETE FROM contractor_users WHERE contractor_id=? AND user_id=?", (cid, user_id))
    c.execute("UPDATE contractors SET user_id=NULL WHERE id=? AND user_id=?", (cid, user_id))
    if not c.execute("SELECT 1 FROM contractor_users WHERE user_id=?", (user_id,)).fetchone():
        c.execute("UPDATE users SET active=0 WHERE id=? AND role='unternehmer'", (user_id,)); c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    c.commit(); c.close(); return {"ok": True}

@app.post("/api/contractors/{cid}/send-access")
async def contractor_send_access(request: Request, cid: str):
    """Zugangsdaten per Mail: {password?} – ohne password wird ein neues erzeugt (Reset)."""
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
    ct = c.execute("SELECT * FROM contractors WHERE id=? AND deleted=0", (cid,)).fetchone()
    if not ct: c.close(); raise HTTPException(404, "Unternehmer nicht gefunden")
    project_access(c, u, ct["project_id"])
    uid_ = d.get("userId") or ct["user_id"]
    if not uid_ or not c.execute("SELECT 1 FROM contractor_users WHERE contractor_id=? AND user_id=?", (cid, uid_)).fetchone(): c.close(); raise HTTPException(400, "Kein Zugang für diesen Unternehmer")
    usr = c.execute("SELECT * FROM users WHERE id=?", (uid_,)).fetchone()
    if not usr or not usr["email"]: c.close(); raise HTTPException(400, "Kein Benutzer/E-Mail")
    pw = d.get("password")
    if not pw:
        pw = secrets.token_urlsafe(7); c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (hash_pw(pw), usr["id"]))
    try: send_access_mail(c, request, u, ct, usr, pw, d.get("text"))
    except HTTPException: raise
    except Exception as e: c.close(); raise HTTPException(400, f"Versand fehlgeschlagen: {e}")
    c.commit(); c.close()
    return {"ok": True, "to": usr["email"]}

@app.post("/api/projects/{pid}/contractors/access-bulk")
async def contractors_access_bulk(request: Request, pid: str):
    """{action:'create'|'send', contractorIds?:[], text?:{subject,body}, includeActive?:bool}
    create: Zugang für alle Unternehmer mit E-Mail aber ohne Login anlegen.
    send:   Zugangsmail (neues Passwort) an alle Logins, die ihr Passwort noch nie gesetzt haben; includeActive = auch aktive (Passwort wird zurückgesetzt)."""
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); project_access(c, u, pid)
    ids = d.get("contractorIds")
    cts = [r for r in c.execute("SELECT * FROM contractors WHERE project_id=? AND deleted=0 ORDER BY bkp,name", (pid,)).fetchall() if not ids or r["id"] in ids]
    res = []
    if d.get("action") == "create":
        for ct in cts:
            if ct["inactive"]: res.append({"id": ct["id"], "name": ct["name"], "status": "inaktiv – übersprungen"}); continue
            if contractor_logins(c, ct["id"]): res.append({"id": ct["id"], "name": ct["name"], "status": "hat bereits Zugang"}); continue
            user_id, pw, err = create_contractor_login(c, ct["id"], ct["email"], ct["name"])
            res.append({"id": ct["id"], "name": ct["name"], "status": err or ("Zugang angelegt" if pw else "bestehendes Konto verknüpft"), "email": ct["email"], "password": pw})
        c.commit(); c.close(); return {"ok": True, "results": res}
    if d.get("action") == "send":
        text = d.get("text") if d.get("text") and d["text"].get("body") else None
        if text: c.execute("INSERT OR REPLACE INTO settings VALUES('accessMail',?)", (json.dumps({"subject": text.get("subject") or ACCESS_MAIL_DEFAULT["subject"], "body": text["body"]}, ensure_ascii=False),))
        sent = 0
        for ct in cts:
            if ct["inactive"]: res.append({"id": ct["id"], "name": ct["name"], "status": "inaktiv – übersprungen"}); continue
            logins = contractor_logins(c, ct["id"])
            if not logins: res.append({"id": ct["id"], "name": ct["name"], "status": "kein Zugang – übersprungen"}); continue
            for lg in logins:
                usr = c.execute("SELECT * FROM users WHERE id=?", (lg["userId"],)).fetchone()
                if not usr["must_change"] and not d.get("includeActive"): res.append({"id": ct["id"], "name": ct["name"], "email": usr["email"], "status": "bereits aktiv – übersprungen"}); continue
                pw = secrets.token_urlsafe(7); c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (hash_pw(pw), usr["id"])); c.commit()
                try: send_access_mail(c, request, u, ct, usr, pw, text); c.commit(); sent += 1; res.append({"id": ct["id"], "name": ct["name"], "email": usr["email"], "status": "gesendet"})
                except Exception as e: res.append({"id": ct["id"], "name": ct["name"], "email": usr["email"], "status": f"Fehler: {e}"})
        c.commit(); c.close(); return {"ok": True, "sent": sent, "results": res}
    c.close(); raise HTTPException(400, "action fehlt")

@app.post("/api/contractors/{cid}/inactive")
async def contractor_inactive(request: Request, cid: str):
    """{inactive:true|false} – Unternehmer inaktiv schalten: Logins gesperrt, erscheint nicht mehr in Auswahl/Versand; Pendenzen bleiben."""
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
    ct = c.execute("SELECT project_id,name FROM contractors WHERE id=?", (cid,)).fetchone()
    if not ct: c.close(); raise HTTPException(404)
    project_access(c, u, ct["project_id"]); flag = 1 if d.get("inactive") else 0
    c.execute("UPDATE contractors SET inactive=? WHERE id=?", (flag, cid))
    for lg in contractor_logins(c, cid):
        others = c.execute("SELECT 1 FROM contractor_users cu JOIN contractors x ON x.id=cu.contractor_id WHERE cu.user_id=? AND x.id<>? AND x.deleted=0 AND x.inactive=0", (lg["userId"], cid)).fetchone()
        if flag and not others: c.execute("UPDATE users SET active=0 WHERE id=? AND role='unternehmer'", (lg["userId"],)); c.execute("DELETE FROM sessions WHERE user_id=?", (lg["userId"],))
        if not flag: c.execute("UPDATE users SET active=1 WHERE id=? AND role='unternehmer'", (lg["userId"],))
    log(c, ct["project_id"], None, u, "unternehmer_inaktiv" if flag else "unternehmer_aktiv", ct["name"]); c.commit(); c.close(); return {"ok": True}

@app.delete("/api/contractors/{cid}")
async def contractor_delete(request: Request, cid: str):
    require(request, ["bauleiter"]); c = db(); c.execute("UPDATE contractors SET deleted=1 WHERE id=?", (cid,)); c.commit(); c.close(); return {"ok": True}

# ----------------------------------------------------------------- Mängel
def defect_row(c, did):
    r = c.execute("SELECT * FROM defects WHERE id=? AND deleted=0", (did,)).fetchone()
    if not r:
        g = c.execute("SELECT nr FROM defects WHERE id=? AND deleted=1", (did,)).fetchone()
        raise HTTPException(410 if g else 404, f"Mangel {g['nr']} wurde inzwischen gelöscht" if g else "Mangel nicht gefunden")
    return dict(r)

def add_photos(c, did, kind, dataurls):
    n = c.execute("SELECT COALESCE(MAX(sort),0) FROM photos WHERE defect_id=? AND kind=?", (did, kind)).fetchone()[0]
    for du in dataurls or []:
        if not isinstance(du, str) or not du.startswith("data:"): continue
        phid = uid(); fn = save_dataurl(du, PHOTOS, phid); n += 1
        c.execute("INSERT INTO photos(id,defect_id,kind,sort,file,created) VALUES(?,?,?,?,?,?)", (phid, did, kind, n, fn, now()))

@app.post("/api/projects/{pid}/defects")
async def defect_save(request: Request, pid: str):
    """Anlegen/Bearbeiten (Bauleiter). photos: Liste aus URLs (bestehend) und data:-URLs (neu)."""
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); project_access(c, u, pid)
    info = None
    if d.get("id"):
        old = defect_row(c, d["id"]); did = d["id"]
        # Konfliktregel: Offline-Änderung trifft auf neueren Serverstand -> letzte Änderung gewinnt, wird aber im Verlauf vermerkt
        if d.get("baseUpdated") and (old.get("updated") or "") > d["baseUpdated"]:
            who = c.execute("SELECT user_name, ts FROM history WHERE defect_id=? AND action IN ('edit','move','bearbeitet','erledigt','offen') ORDER BY id DESC LIMIT 1", (did,)).fetchone()
            info = f"Konflikt: zwischenzeitliche Änderung{(' von ' + who['user_name'] + ' (' + who['ts'] + ')') if who else ''} wurde überschrieben"
            log(c, pid, did, u, "konflikt", info)
        c.execute("UPDATE defects SET descr=?, contractor_id=?, due=?, updated=? WHERE id=?", (d.get("desc") or "", d.get("contractorId") or None, d.get("due") or "", now(), did))
        if "x" in d and "y" in d: c.execute("UPDATE defects SET x=?, y=? WHERE id=?", (float(d["x"]), float(d["y"]), did))
        log(c, pid, did, u, "edit", "")
    else:
        did = uid(); nr = c.execute("SELECT next_nr FROM projects WHERE id=?", (pid,)).fetchone()[0]
        c.execute("UPDATE projects SET next_nr=? WHERE id=?", (nr + 1, pid))
        c.execute("INSERT INTO defects(id,project_id,nr,plan_id,spot_id,x,y,descr,contractor_id,due,status,created,created_by,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (did, pid, nr, d.get("planId"), d.get("spotId") or did, float(d.get("x") or 0), float(d.get("y") or 0), d.get("desc") or "", d.get("contractorId") or None, d.get("due") or "", "offen", now(), u["id"], now()))
        log(c, pid, did, u, "create", f"Nr. {nr}")
    # Fotos: bestehende behalten (URLs), fehlende löschen, neue (data:) anlegen
    if "photos" in d:
        keep = {p.rsplit("/", 1)[-1] for p in d["photos"] if isinstance(p, str) and p.startswith("/api/photos/")}
        for r in c.execute("SELECT id FROM photos WHERE defect_id=? AND kind='photo' AND deleted=0", (did,)).fetchall():
            if r["id"] not in keep: c.execute("UPDATE photos SET deleted=1 WHERE id=?", (r["id"],))
        add_photos(c, did, "photo", [p for p in d["photos"] if isinstance(p, str) and p.startswith("data:")])
    c.commit(); row = defect_row(c, did); c.close(); return {"ok": True, "id": did, "nr": row["nr"], "info": info}

@app.post("/api/defects/{did}/move")
async def defect_move(request: Request, did: str):
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); df = defect_row(c, did); project_access(c, u, df["project_id"])
    ids = [r["id"] for r in c.execute("SELECT id FROM defects WHERE spot_id=? AND deleted=0", (df["spot_id"],))] or [did]
    for i in ids: c.execute("UPDATE defects SET x=?, y=?, updated=? WHERE id=?", (float(d["x"]), float(d["y"]), now(), i))
    if d.get("planId"): c.execute("UPDATE defects SET plan_id=? WHERE spot_id=?", (d["planId"], df["spot_id"]))
    log(c, df["project_id"], did, u, "move", ""); c.commit(); c.close(); return {"ok": True}

@app.post("/api/defects/{did}/status")
async def defect_status(request: Request, did: str):
    u = require(request, ["bauleiter", "unternehmer"]); d = await body(request); c = db(); df = defect_row(c, did); project_access(c, u, df["project_id"])
    new = d.get("status"); info = None
    if u["role"] == "unternehmer":
        if df["contractor_id"] not in own_contractor_ids(c, u, df["project_id"]): c.close(); raise HTTPException(403, "Nicht Ihr Mangel")
        if new != "bearbeitet": c.close(); raise HTTPException(403, "Unternehmer dürfen nur „bearbeitet“ melden")
    # Konfliktregeln (treten v.a. beim Offline-Abgleich auf): Beweisfotos/Notiz werden nie verworfen
    if new == "bearbeitet":
        add_photos(c, did, "proof", d.get("proofPhotos"))
        if df["status"] == "offen":
            c.execute("UPDATE defects SET status='bearbeitet', fixed_at=?, fix_note=?, updated=? WHERE id=?", (now(), d.get("note") or "", now(), did))
            log(c, df["project_id"], did, u, "bearbeitet", d.get("note") or "")
        elif df["status"] == "bearbeitet":
            note = (df.get("fix_note") or ""); add = (d.get("note") or "").strip()
            if add and add not in note: note = (note + "\n" if note else "") + add
            c.execute("UPDATE defects SET fix_note=?, updated=? WHERE id=?", (note, now(), did))
            info = f"Mangel {df['nr']} war bereits als bearbeitet gemeldet – Fotos/Notiz ergänzt"; log(c, df["project_id"], did, u, "bearbeitet", "erneut gemeldet – " + (add or "ohne Notiz"))
        else:
            c.execute("UPDATE defects SET updated=? WHERE id=?", (now(), did))
            info = f"Mangel {df['nr']} ist inzwischen erledigt – Meldung „bearbeitet“ nur im Verlauf vermerkt"; log(c, df["project_id"], did, u, "bearbeitet", "nachträglich gemeldet, war bereits erledigt – " + (d.get("note") or ""))
    elif new == "erledigt":
        if df["status"] == "erledigt": info = f"Mangel {df['nr']} war bereits erledigt"
        else: c.execute("UPDATE defects SET status='erledigt', closed_at=?, updated=? WHERE id=?", (now(), now(), did)); log(c, df["project_id"], did, u, "erledigt", "")
    elif new == "offen":
        reason = (d.get("reason") or "").strip()
        if not reason: c.close(); raise HTTPException(400, "Begründung erforderlich")
        if df["status"] == "offen": info = f"Mangel {df['nr']} war bereits offen"; log(c, df["project_id"], did, u, "offen", "(war bereits offen) " + reason)
        else: c.execute("UPDATE defects SET status='offen', closed_at=NULL, reopen_reason=?, updated=? WHERE id=?", (reason, now(), did)); log(c, df["project_id"], did, u, "offen", reason)
    else: c.close(); raise HTTPException(400, "Unbekannter Status")
    c.commit(); c.close(); return {"ok": True, "info": info}

@app.post("/api/defects/{did}/photo")
async def defect_photo_replace(request: Request, did: str):
    """Ein bestehendes Foto ersetzen (Beschriftung) oder Beweisfoto hinzufügen."""
    u = require(request, ["bauleiter", "unternehmer"]); d = await body(request); c = db(); df = defect_row(c, did); project_access(c, u, df["project_id"])
    kind = d.get("kind") or "photo"
    if u["role"] == "unternehmer":
        if kind != "proof" or df["contractor_id"] not in own_contractor_ids(c, u, df["project_id"]): c.close(); raise HTTPException(403, "Keine Berechtigung")
    if d.get("replaceId"):
        row = c.execute("SELECT file FROM photos WHERE id=? AND defect_id=?", (d["replaceId"], did)).fetchone()
        if not row: c.close(); raise HTTPException(404)
        fn = save_dataurl(d["src"], PHOTOS, d["replaceId"]); c.execute("UPDATE photos SET file=? WHERE id=?", (fn, d["replaceId"]))
        log(c, df["project_id"], did, u, "foto_beschriftet", "")
    else:
        add_photos(c, did, kind, [d.get("src")])
    c.execute("UPDATE defects SET updated=? WHERE id=?", (now(), did))
    c.commit(); c.close(); return {"ok": True}

@app.delete("/api/defects/{did}")
async def defect_delete(request: Request, did: str):
    u = require(request, ["bauleiter"]); c = db()
    if c.execute("SELECT 1 FROM defects WHERE id=? AND deleted=1", (did,)).fetchone(): c.close(); return {"ok": True, "info": "war bereits gelöscht"}
    df = defect_row(c, did); project_access(c, u, df["project_id"])
    c.execute("UPDATE defects SET deleted=1, updated=? WHERE id=?", (now(), did)); log(c, df["project_id"], did, u, "delete", f"Nr. {df['nr']}"); c.commit(); c.close(); return {"ok": True}

@app.get("/api/photos/{phid}")
async def photo_get(request: Request, phid: str):
    u = require(request); c = db()
    row = c.execute("SELECT p.file, d.project_id, d.contractor_id FROM photos p JOIN defects d ON d.id=p.defect_id WHERE p.id=?", (phid,)).fetchone()
    if not row: c.close(); raise HTTPException(404)
    project_access(c, u, row["project_id"])
    if u["role"] == "unternehmer" and row["contractor_id"] not in own_contractor_ids(c, u, row["project_id"]): c.close(); raise HTTPException(403)
    c.close()
    path = PHOTOS / row["file"]
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

@app.get("/api/defects/{did}/history")
async def defect_history(request: Request, did: str):
    u = require(request); c = db(); df = defect_row(c, did); project_access(c, u, df["project_id"])
    rows = [dict(r) for r in c.execute("SELECT ts,user_name,action,detail FROM history WHERE defect_id=? ORDER BY id", (did,))]; c.close(); return rows

# ----------------------------------------------------------------- Einstellungen / BKP / Logo
@app.get("/api/settings")
async def settings_get(request: Request):
    u = require(request); c = db(); out = {}
    for r in c.execute("SELECT key,value FROM settings"):
        if r["key"] in ("smtp",) and not is_bl(u): continue
        try: out[r["key"]] = json.loads(r["value"])
        except Exception: out[r["key"]] = r["value"]
        if r["key"] == "smtp" and isinstance(out[r["key"]], dict): out[r["key"]] = {**out[r["key"]], "password": "", "hasPassword": bool(out[r["key"]].get("password"))}
    c.close(); return out

@app.post("/api/settings")
async def settings_set(request: Request):
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
    if not is_sa(u) and any(k in d for k in ("smtp", "company", "retention", "bkp", "backup")): c.close(); raise HTTPException(403, "Nur der Superadmin ändert Firmen-Einstellungen")
    for k, v in d.items():
        if k == "smtp" and isinstance(v, dict) and not v.get("password"):   # leeres Passwort = bisheriges behalten
            old = c.execute("SELECT value FROM settings WHERE key='smtp'").fetchone()
            if old:
                try: v["password"] = json.loads(old["value"]).get("password", "")
                except Exception: pass
        if k == "backup" and isinstance(v, dict):
            old = c.execute("SELECT value FROM settings WHERE key='backup'").fetchone()
            try: ov = json.loads(old["value"]) if old else {}
            except Exception: ov = {}
            if isinstance(ov, dict):
                for kk in ("lastRun", "lastResult"):
                    if kk in ov: v.setdefault(kk, ov[kk])
        if k in ("bkp", "company", "mail", "pdf", "backup", "smtp", "retention", "accessMail"): c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False)))
    c.commit(); c.close(); return {"ok": True}

@app.get("/api/logo")
async def logo_get():
    for ext in ("png", "jpg", "jpeg"):
        p = DATA / f"logo.{ext}"
        if p.exists(): return FileResponse(p, headers={"Cache-Control": "public, max-age=3600"})
    p = ROOT / "static" / "logo.jpg"
    return FileResponse(p) if p.exists() else Response(status_code=404)

@app.post("/api/logo")
async def logo_set(request: Request):
    require(request, ["superadmin"]); d = await body(request)
    for ext in ("png", "jpg", "jpeg"): (DATA / f"logo.{ext}").unlink(missing_ok=True)
    save_dataurl(d.get("src"), DATA, "logo"); return {"ok": True}

# ----------------------------------------------------------------- Import (App-Export JSON) / Export / Backup
@app.post("/api/import")
async def import_json(request: Request):
    """Import eines Exports der Browser-Version (type mm-backup). Legt Projekte neu an."""
    u = require(request, ["superadmin"]); d = await body(request); c = db()
    if d.get("type") != "mm-backup": c.close(); raise HTTPException(400, "Kein MängelManagement-Export")
    created = []
    for proj in d.get("projects", []):
        pid = uid(); c.execute("INSERT INTO projects(id,name,number,created,next_nr) VALUES(?,?,?,?,?)", (pid, proj.get("name") or "Import", "", proj.get("created") or now(), int(proj.get("nextNr") or 1)))
        plan_map = {}; i = 0
        for pl in proj.get("plans", []):
            i += 1; plid = uid()
            try: fn = save_dataurl(pl.get("src"), PLANS, plid)
            except HTTPException: continue
            c.execute("INSERT INTO plans(id,project_id,name,sort,version,note,added,file) VALUES(?,?,?,?,?,?,?,?)", (plid, pid, pl.get("name") or "Plan", i, pl.get("version") or "", pl.get("note") or "", pl.get("added") or now(), fn))
            plan_map[pl.get("id")] = plid
        ctr_map = {}
        for ct in proj.get("contractors", []):
            cid = uid(); ctr_map[ct.get("id")] = cid
            c.execute("INSERT INTO contractors(id,project_id,name,bkp,trade,email,salutation,first_name,last_name,address,phones,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (cid, pid, ct.get("name") or "", ct.get("bkp") or "", ct.get("trade") or "", ct.get("email") or "", ct.get("salutation") or "", ct.get("firstName") or "", ct.get("lastName") or "", ct.get("address") or "", json.dumps(ct.get("phones") or [], ensure_ascii=False), ct.get("note") or ""))
        spot_map = {}; mx = 0
        for df in proj.get("defects", []):
            did = uid(); spot = spot_map.setdefault(df.get("spotId") or df.get("id"), did); nr = int(df.get("nr") or 0); mx = max(mx, nr)
            c.execute("INSERT INTO defects(id,project_id,nr,plan_id,spot_id,x,y,descr,contractor_id,due,status,created,created_by,fixed_at,fix_note,closed_at,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (did, pid, nr, plan_map.get(df.get("planId")), spot, float(df.get("x") or 0), float(df.get("y") or 0), df.get("desc") or "", ctr_map.get(df.get("contractorId")), df.get("due") or "", df.get("status") or "offen", df.get("created") or now(), u["id"], df.get("fixedAt"), df.get("fixNote") or "", df.get("closedAt"), now()))
            add_photos(c, did, "photo", df.get("photos")); add_photos(c, did, "proof", df.get("proofPhotos"))
        c.execute("UPDATE projects SET next_nr=? WHERE id=?", (mx + 1, pid)); created.append(proj.get("name"))
        if plan_map: c.execute("UPDATE projects SET current_plan=? WHERE id=?", (list(plan_map.values())[0], pid))
    c.commit(); c.close(); return {"ok": True, "projects": created}

@app.get("/api/export")
async def export_json(request: Request):
    """Export im App-Format (für MaengelArchiv.py), inkl. Fotos als data-URLs."""
    u = require(request, ["superadmin"]); c = db(); out = {"type": "mm-backup", "v": 2, "exported": now(), "projects": []}
    def du(folder, fn):
        p = folder / fn
        if not p.exists(): return None
        mt = mimetypes.guess_type(fn)[0] or "image/jpeg"; return f"data:{mt};base64," + base64.b64encode(p.read_bytes()).decode()
    for p in c.execute("SELECT * FROM projects WHERE archived=0"):
        proj = {"id": p["id"], "name": p["name"], "number": p["number"], "created": p["created"], "nextNr": p["next_nr"], "currentPlanId": p["current_plan"], "plans": [], "contractors": [], "defects": []}
        for pl in c.execute("SELECT * FROM plans WHERE project_id=? AND deleted=0 ORDER BY sort", (p["id"],)):
            proj["plans"].append({"id": pl["id"], "name": pl["name"], "version": pl["version"], "note": pl["note"], "added": pl["added"], "replaced": pl["replaced"], "src": du(PLANS, pl["file"])})
        for ct in c.execute("SELECT * FROM contractors WHERE project_id=? AND deleted=0", (p["id"],)):
            proj["contractors"].append({"id": ct["id"], "name": ct["name"], "bkp": ct["bkp"], "trade": ct["trade"], "email": ct["email"], "salutation": ct["salutation"], "firstName": ct["first_name"], "lastName": ct["last_name"], "address": ct["address"], "phones": json.loads(ct["phones"] or "[]"), "note": ct["note"]})
        for df in c.execute("SELECT * FROM defects WHERE project_id=? AND deleted=0 ORDER BY nr", (p["id"],)):
            ph = [du(PHOTOS, r["file"]) for r in c.execute("SELECT file FROM photos WHERE defect_id=? AND kind='photo' AND deleted=0 ORDER BY sort", (df["id"],))]
            pr = [du(PHOTOS, r["file"]) for r in c.execute("SELECT file FROM photos WHERE defect_id=? AND kind='proof' AND deleted=0 ORDER BY sort", (df["id"],))]
            proj["defects"].append({"id": df["id"], "nr": df["nr"], "planId": df["plan_id"], "spotId": df["spot_id"], "x": df["x"], "y": df["y"], "desc": df["descr"], "contractorId": df["contractor_id"], "due": df["due"], "status": df["status"], "created": df["created"], "fixedAt": df["fixed_at"], "fixNote": df["fix_note"], "closedAt": df["closed_at"], "reopenReason": df["reopen_reason"], "photos": [x for x in ph if x], "proofPhotos": [x for x in pr if x]})
        out["projects"].append(proj)
    c.close(); return JSONResponse(out, headers={"Content-Disposition": f"attachment; filename=MaengelManagement-Export-{datetime.date.today()}.json"})

BACKUPS = DATA / "backups"

def make_backup_zip(out, with_photos=True):
    """Datenordner als ZIP in out (Pfad oder BytesIO). Ohne backups/ und WAL-Dateien."""
    c = db(); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in DATA.rglob("*"):
            if not p.is_file() or p.name.endswith(("-wal", "-shm")): continue
            rel = p.relative_to(DATA)
            if rel.parts[0] == "backups": continue
            if not with_photos and rel.parts[0] == "photos": continue
            z.write(p, rel)

@app.get("/api/backup.zip")
async def backup_zip(request: Request):
    """Kompletter Datenordner als ZIP (Datenbank + Fotos + Pläne + Logo)."""
    require(request, ["superadmin"])
    buf = io.BytesIO(); make_backup_zip(buf); buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=MaengelManagement-Backup-{datetime.date.today()}.zip"})

@app.post("/api/restore")
async def restore_zip(request: Request):
    """Sicherung (ZIP aus /api/backup.zip) wieder einspielen. Body = ZIP-Datei roh.
    Der bisherige Datenordner wird vorher nach backups/vor-wiederherstellung-<zeit>.zip gesichert."""
    u = require(request, ["superadmin"])
    raw = await request.body()
    if len(raw) < 100: raise HTTPException(400, "Keine Datei")
    try: z = zipfile.ZipFile(io.BytesIO(raw))
    except Exception: raise HTTPException(400, "Das ist keine ZIP-Datei")
    names = z.namelist()
    if "maengel.db" not in names: raise HTTPException(400, "In der ZIP-Datei fehlt maengel.db – das ist keine MängelManagement-Sicherung")
    for n in names:
        if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/"): raise HTTPException(400, "Ungültiger Pfad in der ZIP-Datei")
    # Datenbank in der Sicherung prüfen
    tmpdb = DATA / f"restore-check-{uid()}.db"
    try:
        tmpdb.write_bytes(z.read("maengel.db"))
        t = sqlite3.connect(tmpdb)
        tabs = {r[0] for r in t.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        nproj = t.execute("SELECT COUNT(*) FROM projects").fetchone()[0] if "projects" in tabs else 0
        ndef = t.execute("SELECT COUNT(*) FROM defects WHERE deleted=0").fetchone()[0] if "defects" in tabs else 0
        t.close()
        if not {"users", "projects", "defects"} <= tabs: raise HTTPException(400, "Die Datenbank in der Sicherung ist unvollständig")
    except HTTPException: raise
    except Exception as e: raise HTTPException(400, f"Datenbank in der Sicherung nicht lesbar: {e}")
    finally: tmpdb.unlink(missing_ok=True)
    # Aktuellen Stand sichern
    BACKUPS.mkdir(exist_ok=True)
    safety = BACKUPS / f"vor-wiederherstellung-{datetime.datetime.now():%Y%m%d-%H%M%S}.zip"
    make_backup_zip(safety)
    # Einspielen: Datenordner leeren (ausser backups/), ZIP entpacken
    for p in list(DATA.iterdir()):
        if p.name == "backups": continue
        if p.is_dir(): shutil.rmtree(p, ignore_errors=True)
        else:
            try: p.unlink()
            except Exception: pass
    for d in (PHOTOS, PLANS): d.mkdir(parents=True, exist_ok=True)
    z.extractall(DATA)
    init_db()
    print(f"  Wiederhergestellt aus Sicherung durch {u['email']}: {nproj} Projekte, {ndef} Mängel. Vorheriger Stand: {safety.name}")
    return {"ok": True, "projects": nproj, "defects": ndef, "safety": safety.name}

@app.get("/api/backups")
async def backups_list(request: Request):
    require(request, ["superadmin"]); BACKUPS.mkdir(exist_ok=True)
    out = []
    for p in sorted(BACKUPS.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        st = p.stat(); out.append({"name": p.name, "size": st.st_size, "time": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return out

@app.get("/api/backups/{name}")
async def backups_get(request: Request, name: str):
    require(request, ["superadmin"])
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".zip"): raise HTTPException(400)
    p = BACKUPS / name
    if not p.exists(): raise HTTPException(404)
    return FileResponse(p, media_type="application/zip", filename=name)

def backup_cfg():
    c = db(); row = c.execute("SELECT value FROM settings WHERE key='backup'").fetchone(); c.close()
    try: cfg = json.loads(row["value"]) if row else {}
    except Exception: cfg = {}
    if not isinstance(cfg, dict): cfg = {}
    return {"enabled": cfg.get("enabled", True), "hour": int(cfg.get("hour", 2) or 0), "keep": int(cfg.get("keep", 14) or 14), "mailTo": (cfg.get("mailTo") or "").strip(), "mailPhotos": bool(cfg.get("mailPhotos")), "lastRun": cfg.get("lastRun")}

def daily_backup():
    """Tägliche Sicherung nach data/backups (Rotation) und optional per Mail. Läuft einmal pro Tag ab der eingestellten Stunde."""
    cfg = backup_cfg()
    if not cfg["enabled"]: return
    nowdt = datetime.datetime.now(); today = nowdt.date().isoformat()
    if (cfg.get("lastRun") or "")[:10] == today or nowdt.hour < cfg["hour"]: return
    BACKUPS.mkdir(exist_ok=True)
    name = f"MaengelManagement-Backup-{nowdt:%Y%m%d-%H%M}.zip"; path = BACKUPS / name
    make_backup_zip(path)
    # Rotation (nur automatische Sicherungen, nicht die "vor-wiederherstellung")
    autos = sorted(BACKUPS.glob("MaengelManagement-Backup-*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
    for old in autos[max(1, cfg["keep"]):]:
        try: old.unlink()
        except Exception: pass
    msg = f"Sicherung {name} ({path.stat().st_size // 1024} KB)"
    if cfg["mailTo"]:
        try:
            scfg = smtp_cfg()
            if cfg["mailPhotos"]: data = path.read_bytes(); att = name
            else:
                buf = io.BytesIO(); make_backup_zip(buf, with_photos=False); data = buf.getvalue(); att = name.replace(".zip", "-ohne-Fotos.zip")
            mb = len(data) / 1048576
            if mb > 20:
                smtp_send(scfg, [cfg["mailTo"]], f"MängelManagement – Sicherung {today} (zu gross für Mail)", f"<p>Die tägliche Sicherung ist {mb:.0f} MB gross und wurde deshalb nicht angehängt. Sie liegt auf dem Server unter data/backups/{name} und kann im Menü → Sichern heruntergeladen werden.</p>", [])
            else:
                smtp_send(scfg, [cfg["mailTo"]], f"MängelManagement – Sicherung {today}", f"<p>Anbei die tägliche Sicherung ({'mit' if cfg['mailPhotos'] else 'ohne'} Fotos, {mb:.1f} MB). Wiederherstellen: Menü → Sichern → Sicherung wiederherstellen.</p>", [{"name": att, "b64": base64.b64encode(data).decode(), "type": "application/zip"}])
            msg += f", per Mail an {cfg['mailTo']}"
        except Exception as e: msg += f", Mailversand fehlgeschlagen: {e}"
    c = db()
    row = c.execute("SELECT value FROM settings WHERE key='backup'").fetchone()
    try: stored = json.loads(row["value"]) if row else {}
    except Exception: stored = {}
    if not isinstance(stored, dict): stored = {}
    stored["lastRun"] = now(); stored["lastResult"] = msg
    c.execute("INSERT OR REPLACE INTO settings VALUES('backup',?)", (json.dumps(stored, ensure_ascii=False),)); c.commit(); c.close()
    print("  " + msg)

# ----------------------------------------------------------------- Aufräumen: Fotos erledigter Mängel
def purge_photos():
    """Löscht Fotos (inkl. Beweisfotos) von Mängeln, die länger als N Tage erledigt sind."""
    c = db()
    row = c.execute("SELECT value FROM settings WHERE key='retention'").fetchone()
    ret = json.loads(row["value"]) if row else {}
    days = int(ret.get("days", 30) or 0)
    if not ret.get("enabled", days > 0) or days <= 0: c.close(); return 0
    limit = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    n = 0
    for d in c.execute("SELECT id FROM defects WHERE status='erledigt' AND closed_at IS NOT NULL AND closed_at<? AND photos_purged IS NULL AND deleted=0", (limit,)).fetchall():
        for ph in c.execute("SELECT id,file FROM photos WHERE defect_id=? AND deleted=0", (d["id"],)).fetchall():
            try: (PHOTOS / ph["file"]).unlink(missing_ok=True)
            except Exception: pass
            c.execute("UPDATE photos SET deleted=1 WHERE id=?", (ph["id"],)); n += 1
        c.execute("UPDATE defects SET photos_purged=? WHERE id=?", (now(), d["id"]))
    c.commit(); c.close()
    if n: print(f"  Aufräumen: {n} Fotos erledigter Mängel (älter als {days} Tage) gelöscht.")
    return n

async def _bg_loop():
    import asyncio
    while True:
        try: purge_photos()
        except Exception as e: print("Aufräumen fehlgeschlagen:", e)
        try: await asyncio.get_event_loop().run_in_executor(None, daily_backup)
        except Exception as e: print("Tägliche Sicherung fehlgeschlagen:", e)
        try: await asyncio.get_event_loop().run_in_executor(None, finalize_weather)
        except Exception as e: print("Wetter nachliefern fehlgeschlagen:", e)
        await asyncio.sleep(600)

# ----------------------------------------------------------------- Mailversand (SMTP)
def smtp_cfg():
    c = db(); row = c.execute("SELECT value FROM settings WHERE key='smtp'").fetchone(); c.close()
    cfg = json.loads(row["value"]) if row else {}
    if not cfg.get("host"): raise HTTPException(400, "SMTP ist nicht eingerichtet (Einstellungen → Mailversand)")
    return cfg

def smtp_send(cfg, to_list, subject, html, attachments, cc_list=None):
    import smtplib, ssl
    from email.message import EmailMessage
    from email.utils import formataddr
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("fromName") or "", cfg.get("from") or cfg.get("user") or ""))
    msg["To"] = ", ".join(to_list)
    if cc_list: msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg.set_content(re.sub(r"<[^>]+>", "", html).strip() or " ")
    msg.add_alternative(html, subtype="html")
    for a in attachments or []:
        data = base64.b64decode(a["b64"]); mt = (a.get("type") or "application/pdf").split("/")
        msg.add_attachment(data, maintype=mt[0], subtype=mt[1] if len(mt) > 1 else "octet-stream", filename=a["name"])
    port = int(cfg.get("port") or 587); host = cfg["host"]; timeout = 30
    if cfg.get("security") == "ssl":
        s = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        s = smtplib.SMTP(host, port, timeout=timeout); s.ehlo()
        if cfg.get("security", "starttls") == "starttls": s.starttls(context=ssl.create_default_context()); s.ehlo()
    if cfg.get("user"): s.login(cfg["user"], cfg.get("password") or "")
    s.send_message(msg); s.quit()

@app.post("/api/mail/test")
async def mail_test(request: Request):
    u = require(request, ["bauleiter"]); cfg = smtp_cfg()
    try: smtp_send(cfg, [u["email"]], "MängelManagement – Testmail", "<p>SMTP-Versand funktioniert.</p>", [])
    except Exception as e: raise HTTPException(400, f"Versand fehlgeschlagen: {e}")
    return {"ok": True, "to": u["email"]}

@app.post("/api/mail/send")
async def mail_send(request: Request):
    """Pendenzen-Mail: {to:[..], cc:[..], subject, html, attachments:[{name,b64,type}], defectIds:[..]}"""
    u = require(request, ["bauleiter"]); d = await body(request); cfg = smtp_cfg()
    to = [x for x in (d.get("to") or []) if x]; 
    if not to: raise HTTPException(400, "Kein Empfänger")
    cc = [x for x in (d.get("cc") or []) if x]
    if cfg.get("ccSelf") and u["email"] not in cc: cc.append(u["email"])
    try: smtp_send(cfg, to, d.get("subject") or "Pendenzenliste", d.get("html") or "", d.get("attachments") or [], cc)
    except Exception as e: raise HTTPException(400, f"Versand fehlgeschlagen: {e}")
    c = db()
    for did in d.get("defectIds") or []:
        row = c.execute("SELECT project_id FROM defects WHERE id=?", (did,)).fetchone()
        if row: log(c, row["project_id"], did, u, "mail", "an " + ", ".join(to))
    c.commit(); c.close()
    return {"ok": True}

# ----------------------------------------------------------------- Baujournal
def http_json(url, timeout=12):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "MAEMA-Baujournal/1.0 (DPBM)"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode("utf-8"))

def geocode(addr):
    """Adresse -> {lat, lon, label}. Zuerst Nominatim (Strasse+Hausnummer), dann Open-Meteo-Geocoding (Ort)."""
    import urllib.parse
    q = addr.strip()
    if not q: return None
    try:
        res = http_json("https://nominatim.openstreetmap.org/search?format=json&limit=1&addressdetails=0&q=" + urllib.parse.quote(q))
        if res: return {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "label": res[0].get("display_name", q), "src": "nominatim"}
    except Exception as e: print("Geocoding (Nominatim) fehlgeschlagen:", e)
    try:
        # Ort aus der Adresse: letztes Wort/Teil nach Komma oder PLZ
        m = re.search(r"(\d{4,5})?\s*([A-Za-zÄÖÜäöüß .\-]+)$", q.split(",")[-1].strip())
        ort = (m.group(2) if m else q).strip()
        res = http_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=de&name=" + urllib.parse.quote(ort))
        r = (res.get("results") or [None])[0]
        if r: return {"lat": r["latitude"], "lon": r["longitude"], "label": f"{r.get('name')}, {r.get('admin1') or ''} {r.get('country') or ''}".strip(), "src": "open-meteo", "approx": True}
    except Exception as e: print("Geocoding (Open-Meteo) fehlgeschlagen:", e)
    return None

def fetch_weather(lat, lon, day):
    """Stundenwerte 00–23 Uhr für einen Tag (Vorhersage + Archiv bis 7 Tage zurück via forecast-API past_days)."""
    today = datetime.date.today(); d = datetime.date.fromisoformat(day); delta = (today - d).days
    base = "https://api.open-meteo.com/v1/forecast" if delta <= 7 else "https://archive-api.open-meteo.com/v1/archive"
    url = f"{base}?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation,weather_code,wind_speed_10m&timezone=Europe%2FZurich&start_date={day}&end_date={day}"
    j = http_json(url, timeout=15); h = j.get("hourly") or {}
    out = {"time": h.get("time") or [], "temp": h.get("temperature_2m") or [], "rain": h.get("precipitation") or [], "code": h.get("weather_code") or [], "wind": h.get("wind_speed_10m") or [], "fetched": now(), "source": "open-meteo"}
    temps = [t for t in out["temp"] if t is not None]
    if temps: out["tmin"] = min(temps); out["tmax"] = max(temps)
    out["rainSum"] = round(sum(x for x in out["rain"] if x), 1)
    codes = [x for x in out["code"] if x is not None]
    if codes:
        # dominanter Tageszustand: schlechtester Code zwischen 7 und 19 Uhr
        day_codes = [x for i, x in enumerate(out["code"]) if x is not None and 7 <= i <= 19] or codes
        out["codeDay"] = max(day_codes)
    return out

WMO = {0: "sonnig", 1: "meist sonnig", 2: "teils bewölkt", 3: "bedeckt", 45: "Nebel", 48: "Reifnebel", 51: "leichter Nieselregen", 53: "Nieselregen", 55: "starker Nieselregen", 61: "leichter Regen", 63: "Regen", 65: "starker Regen", 66: "gefrierender Regen", 67: "gefrierender Regen", 71: "leichter Schneefall", 73: "Schneefall", 75: "starker Schneefall", 77: "Schneegriesel", 80: "Regenschauer", 81: "Regenschauer", 82: "heftige Regenschauer", 85: "Schneeschauer", 86: "Schneeschauer", 95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Gewitter mit Hagel"}

def journal_row(c, jid):
    r = c.execute("SELECT * FROM journal WHERE id=?", (jid,)).fetchone()
    if not r: raise HTTPException(404, "Journaleintrag nicht gefunden")
    return dict(r)

def journal_out(c, r):
    j = {"id": r["id"], "projectId": r["project_id"], "day": r["day"], "weather": json.loads(r["weather"]) if r.get("weather") else None, "weatherFinal": bool(r.get("weather_final")),
         "presence": json.loads(r.get("presence") or "[]"), "works": json.loads(r.get("works") or "[]"), "incidents": r.get("incidents") or "", "orders": r.get("orders_") or "", "visitors": r.get("visitors") or "", "note": r.get("note") or "",
         "created": r.get("created"), "createdBy": r.get("created_by"), "updated": r.get("updated"), "updatedBy": r.get("updated_by")}
    j["photos"] = [{"id": p["id"], "url": f"/api/journal/photo/{p['id']}", "comment": p["comment"] or "", "created": p["created"]} for p in c.execute("SELECT * FROM journal_photos WHERE journal_id=? AND deleted=0 ORDER BY sort,created", (r["id"],))]
    if j["weather"] and j["weather"].get("codeDay") is not None: j["weather"]["text"] = WMO.get(j["weather"]["codeDay"], "")
    return j

def ensure_weather(c, pid, r, force=False):
    """Wetter holen, wenn fehlt oder noch nicht final. Final = Tag vorbei (ab 00:00 des Folgetags) -> fix gespeichert."""
    if r.get("weather_final") and not force: return r
    p = c.execute("SELECT lat, lon FROM projects WHERE id=?", (pid,)).fetchone()
    if not p or p["lat"] is None: return r
    try:
        w = fetch_weather(p["lat"], p["lon"], r["day"])
        final = 1 if datetime.date.fromisoformat(r["day"]) < datetime.date.today() else 0
        c.execute("UPDATE journal SET weather=?, weather_final=? WHERE id=?", (json.dumps(w), final, r["id"])); c.commit()
        r["weather"] = json.dumps(w); r["weather_final"] = final
    except Exception as e: print("Wetter fehlgeschlagen:", e)
    return r

def finalize_weather():
    """Hintergrund: Wetter vergangener Tage nachliefern/fixieren (auch wenn niemand mehr im Journal war)."""
    c = db(); n = 0
    for r in c.execute("SELECT j.*, p.lat FROM journal j JOIN projects p ON p.id=j.project_id WHERE j.weather_final=0 AND j.day<? AND p.lat IS NOT NULL", (datetime.date.today().isoformat(),)).fetchall():
        r = dict(r); ensure_weather(c, r["project_id"], r); n += 1
    c.close(); return n

@app.get("/api/projects/{pid}/journal")
async def journal_list(request: Request, pid: str):
    """Übersicht: alle Tage (ohne Fotos) + Trefferliste bei ?q=Suchbegriff."""
    u = require(request, ["bauleiter", "bauherr"]); c = db(); project_access(c, u, pid)
    q = (request.query_params.get("q") or "").strip().lower()
    rows = [dict(r) for r in c.execute("SELECT * FROM journal WHERE project_id=? ORDER BY day DESC", (pid,))]
    out = []
    for r in rows:
        j = journal_out(c, r); j["photoCount"] = len(j.pop("photos"))
        if q:
            hay = []
            for k in ("incidents", "orders", "visitors", "note"): hay.append((k, j[k]))
            hay.append(("presence", ", ".join(f"{x.get('name','')} ({x.get('count','')})" for x in j["presence"])))
            hay.append(("works", "; ".join(f"{x.get('name','')}: {x.get('text','')}" for x in j["works"])))
            for p in c.execute("SELECT comment FROM journal_photos WHERE journal_id=? AND deleted=0", (r["id"],)): hay.append(("photo", p["comment"] or ""))
            hits = []
            for k, txt in hay:
                low = (txt or "").lower(); i = low.find(q)
                while i >= 0 and len(hits) < 3:
                    a = max(0, i - 40); b = min(len(txt), i + len(q) + 60)
                    hits.append({"field": k, "snippet": ("…" if a else "") + txt[a:b] + ("…" if b < len(txt) else "")}); i = low.find(q, i + 1)
            if not hits: continue
            j["hits"] = hits
        out.append(j)
    c.close(); return out

@app.get("/api/projects/{pid}/journal/{day}")
async def journal_get(request: Request, pid: str, day: str):
    u = require(request, ["bauleiter", "bauherr"]); c = db(); project_access(c, u, pid)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day): c.close(); raise HTTPException(400, "Datum")
    r = c.execute("SELECT * FROM journal WHERE project_id=? AND day=?", (pid, day)).fetchone()
    if not r: c.close(); return {"exists": False, "day": day}
    r = ensure_weather(c, pid, dict(r)); j = journal_out(c, r); j["exists"] = True; c.close(); return j

@app.post("/api/projects/{pid}/journal/{day}")
async def journal_save(request: Request, pid: str, day: str):
    """Anlegen/Speichern eines Tages. presence:[{contractorId,name,count}], works:[{contractorId,name,text}], incidents, orders, visitors, note."""
    u = require(request, ["bauleiter"]); d = await body(request); c = db(); project_access(c, u, pid)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day): c.close(); raise HTTPException(400, "Datum")
    r = c.execute("SELECT * FROM journal WHERE project_id=? AND day=?", (pid, day)).fetchone()
    if r: jid = r["id"]
    else:
        jid = uid(); c.execute("INSERT INTO journal(id,project_id,day,created,created_by) VALUES(?,?,?,?,?)", (jid, pid, day, now(), u.get("name") or u["email"]))
        log(c, pid, None, u, "journal_neu", day)
    c.execute("UPDATE journal SET presence=?, works=?, incidents=?, orders_=?, visitors=?, note=?, updated=?, updated_by=? WHERE id=?",
              (json.dumps(d.get("presence") or [], ensure_ascii=False), json.dumps(d.get("works") or [], ensure_ascii=False), d.get("incidents") or "", d.get("orders") or "", d.get("visitors") or "", d.get("note") or "", now(), u.get("name") or u["email"], jid))
    # Fotos: neue (data:) anlegen, Kommentare bestehender aktualisieren, fehlende löschen
    if "photos" in d:
        keep = set()
        n = c.execute("SELECT COALESCE(MAX(sort),0) FROM journal_photos WHERE journal_id=?", (jid,)).fetchone()[0]
        for ph in d["photos"]:
            if not isinstance(ph, dict): continue
            if ph.get("id"):
                keep.add(ph["id"]); c.execute("UPDATE journal_photos SET comment=? WHERE id=? AND journal_id=?", (ph.get("comment") or "", ph["id"], jid))
            elif isinstance(ph.get("src"), str) and ph["src"].startswith("data:"):
                phid = uid(); fn = save_dataurl(ph["src"], JPHOTOS, phid); n += 1; keep.add(phid)
                c.execute("INSERT INTO journal_photos(id,journal_id,sort,file,comment,created) VALUES(?,?,?,?,?,?)", (phid, jid, n, fn, ph.get("comment") or "", ph.get("created") or now()))
        for row in c.execute("SELECT id FROM journal_photos WHERE journal_id=? AND deleted=0", (jid,)).fetchall():
            if row["id"] not in keep: c.execute("UPDATE journal_photos SET deleted=1 WHERE id=?", (row["id"],))
    c.commit()
    r = ensure_weather(c, pid, journal_row(c, jid), force=bool(d.get("refreshWeather")))
    j = journal_out(c, r); j["exists"] = True; c.close(); return j

@app.delete("/api/projects/{pid}/journal/{day}")
async def journal_delete(request: Request, pid: str, day: str):
    u = require(request, ["bauleiter"]); c = db(); project_access(c, u, pid)
    r = c.execute("SELECT id FROM journal WHERE project_id=? AND day=?", (pid, day)).fetchone()
    if r:
        for p in c.execute("SELECT file FROM journal_photos WHERE journal_id=?", (r["id"],)).fetchall():
            try: (JPHOTOS / p["file"]).unlink(missing_ok=True)
            except Exception: pass
        c.execute("DELETE FROM journal_photos WHERE journal_id=?", (r["id"],)); c.execute("DELETE FROM journal WHERE id=?", (r["id"],)); log(c, pid, None, u, "journal_geloescht", day)
    c.commit(); c.close(); return {"ok": True}

@app.get("/api/journal/photo/{phid}")
async def journal_photo(request: Request, phid: str):
    u = require(request, ["bauleiter", "bauherr"]); c = db()
    row = c.execute("SELECT p.file, j.project_id FROM journal_photos p JOIN journal j ON j.id=p.journal_id WHERE p.id=?", (phid,)).fetchone()
    if not row: c.close(); raise HTTPException(404)
    project_access(c, u, row["project_id"]); c.close()
    path = JPHOTOS / row["file"]
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

@app.get("/api/geocode")
async def geocode_api(request: Request):
    require(request, ["bauleiter"]); q = request.query_params.get("q") or ""
    g = geocode(q)
    if not g: raise HTTPException(404, "Adresse nicht gefunden – Schreibweise prüfen oder nur Strasse und Ort eingeben")
    return g

@app.get("/api/weather")
async def weather_api(request: Request):
    """Vorschau fürs Diagramm ohne Journal-Eintrag: ?lat&lon&day"""
    require(request, ["bauleiter", "bauherr"]); qp = request.query_params
    try: return fetch_weather(float(qp["lat"]), float(qp["lon"]), qp["day"])
    except Exception as e: raise HTTPException(400, f"Wetter nicht verfügbar: {e}")

# ----------------------------------------------------------------- App ausliefern
@app.get("/", response_class=HTMLResponse)
async def index():
    p = ROOT / "static" / "index.html"
    return HTMLResponse(p.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})

@app.get("/sw.js")
async def sw():
    p = ROOT / "static" / "sw.js"
    return Response(p.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-cache"})

if (ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

if __name__ == "__main__":
    import uvicorn, socket
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips: ips.append(ip)
    except Exception: pass
    if not ips: ips = ["127.0.0.1"]
    port = int(os.environ.get("MM_PORT", "8000"))
    print(f"\n  MängelManagement-Server läuft.\n  Am PC:    http://localhost:{port}")
    for ip in ips: print(f"  Im WLAN:  http://{ip}:{port}")
    print(f"  Daten:    {DATA}\n  Handy kommt nicht drauf? Windows-Firewall Port {port} freigeben, FRITZ!Box: WLAN-Geraete duerfen untereinander kommunizieren.\n")
    cert, key = DATA / "cert.pem", DATA / "key.pem"
    ssl_kw = {}
    if cert.exists() and key.exists():
        ssl_kw = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        print(f"  HTTPS aktiv (data/cert.pem + key.pem). Adressen oben mit https:// aufrufen – nötig für Offline-Start/PWA.\n")
    else:
        print("  Hinweis: ohne HTTPS funktioniert die App nur bei bestehender Verbindung (kein Offline-Start). Zertifikat: siehe README (data/cert.pem + data/key.pem).\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning", **ssl_kw)
