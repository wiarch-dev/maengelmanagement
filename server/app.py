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
for d in (DATA, PHOTOS, PLANS): d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MängelManagement", docs_url=None, redoc_url=None)

# ----------------------------------------------------------------- Hilfen
def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def uid(): return secrets.token_hex(8)

def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
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
CREATE TABLE IF NOT EXISTS defects (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, nr INTEGER, plan_id TEXT, spot_id TEXT, x REAL, y REAL,
  descr TEXT, contractor_id TEXT, due TEXT, status TEXT DEFAULT 'offen', created TEXT, created_by TEXT,
  fixed_at TEXT, fix_note TEXT, closed_at TEXT, reopen_reason TEXT, updated TEXT, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS photos (
  id TEXT PRIMARY KEY, defect_id TEXT NOT NULL, kind TEXT DEFAULT 'photo', sort INTEGER DEFAULT 0, file TEXT, created TEXT, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, defect_id TEXT, ts TEXT, user_id TEXT, user_name TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
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

def init_db():
    c = db()
    c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM settings WHERE key='bkp'").fetchone():
        c.execute("INSERT INTO settings VALUES('bkp',?)", (json.dumps([{"code":a,"name":b} for a,b in BKP_DEFAULT], ensure_ascii=False),))
    if not c.execute("SELECT 1 FROM settings WHERE key='company'").fetchone():
        c.execute("INSERT INTO settings VALUES('company',?)", (json.dumps({"name":"Dietziker Partner Baumanagement AG","addr":"Grosspeteranlage 29 ▪ 4052 Basel","contact":"T +41 61 266 50 00 ▪ info@dietziker-bm.ch ▪ www.dietziker-bm.ch","slogan":"Gemeinsam erfolgreich bauen"}, ensure_ascii=False),))
    if not c.execute("SELECT 1 FROM users").fetchone():
        pw = os.environ.get("MM_ADMIN_PW") or "start1234"
        email = os.environ.get("MM_ADMIN_EMAIL") or "admin@dietziker-bm.ch"
        c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)", (uid(), email, hash_pw(pw), "bauleiter", "Administrator", 1, 1, now()))
        print(f"\n  Erstes Bauleiter-Konto angelegt:  {email}  /  Passwort: {pw}   (beim ersten Login ändern)\n")
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

def require(request: Request, roles=None):
    u = current_user(request)
    if not u: raise HTTPException(401, "Nicht angemeldet")
    if roles and u["role"] not in roles: raise HTTPException(403, "Keine Berechtigung")
    return u

def user_projects(c, u):
    """Projekt-IDs, die der Benutzer sehen darf."""
    if u["role"] == "bauleiter":
        return [r["id"] for r in c.execute("SELECT id FROM projects WHERE archived=0")]
    if u["role"] == "unternehmer":
        return [r["project_id"] for r in c.execute("SELECT DISTINCT project_id FROM contractors WHERE user_id=? AND deleted=0", (u["id"],))]
    return [r["project_id"] for r in c.execute("SELECT project_id FROM project_users WHERE user_id=?", (u["id"],))]

def own_contractor_ids(c, u, project_id):
    return [r["id"] for r in c.execute("SELECT id FROM contractors WHERE project_id=? AND user_id=? AND deleted=0", (project_id, u["id"]))]

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
    return {"ok": True, "user": {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"], "mustChange": bool(row["must_change"])}}

@app.post("/api/logout")
async def logout(request: Request, response: Response):
    tok = request.cookies.get("mm_session")
    if tok:
        c = db(); c.execute("DELETE FROM sessions WHERE token=?", (tok,)); c.commit(); c.close()
    response.delete_cookie("mm_session"); return {"ok": True}

@app.get("/api/me")
async def me(request: Request):
    u = current_user(request)
    if not u: return {"user": None}
    return {"user": {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"], "mustChange": bool(u["must_change"])}}

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
@app.get("/api/users")
async def users_list(request: Request):
    require(request, ["bauleiter"]); c = db()
    rows = [dict(r) for r in c.execute("SELECT id,email,name,role,must_change,active,created FROM users ORDER BY role,name")]
    for r in rows:
        r["projects"] = [x["project_id"] for x in c.execute("SELECT project_id FROM project_users WHERE user_id=?", (r["id"],))]
        r["contractors"] = [dict(x) for x in c.execute("SELECT id,project_id,name FROM contractors WHERE user_id=? AND deleted=0", (r["id"],))]
    c.close(); return rows

@app.post("/api/users")
async def users_save(request: Request):
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
    email = (d.get("email") or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email): c.close(); raise HTTPException(400, "Ungültige E-Mail")
    role = d.get("role") if d.get("role") in ("bauleiter","unternehmer","bauherr") else "bauherr"
    if d.get("id"):
        c.execute("UPDATE users SET email=?, name=?, role=?, active=? WHERE id=?", (email, d.get("name") or "", role, 1 if d.get("active", True) else 0, d["id"]))
        if d.get("password"): c.execute("UPDATE users SET pw=?, must_change=1 WHERE id=?", (hash_pw(d["password"]), d["id"]))
        user_id = d["id"]; pw = d.get("password")
    else:
        if c.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone(): c.close(); raise HTTPException(400, "E-Mail bereits vergeben")
        pw = d.get("password") or secrets.token_urlsafe(6)
        user_id = uid()
        c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)", (user_id, email, hash_pw(pw), role, d.get("name") or "", 1, 1, now()))
    if "projects" in d:
        c.execute("DELETE FROM project_users WHERE user_id=?", (user_id,))
        for pid in d["projects"]: c.execute("INSERT OR IGNORE INTO project_users VALUES(?,?)", (pid, user_id))
    c.commit(); c.close()
    return {"ok": True, "id": user_id, "initialPassword": pw}

@app.delete("/api/users/{user_id}")
async def users_delete(request: Request, user_id: str):
    u = require(request, ["bauleiter"])
    if user_id == u["id"]: raise HTTPException(400, "Eigenes Konto kann nicht gelöscht werden")
    c = db(); c.execute("UPDATE users SET active=0 WHERE id=?", (user_id,)); c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    c.execute("UPDATE contractors SET user_id=NULL WHERE user_id=?", (user_id,)); c.commit(); c.close(); return {"ok": True}

# ----------------------------------------------------------------- Projekte
def project_access(c, u, pid):
    if pid not in user_projects(c, u): raise HTTPException(403, "Kein Zugriff auf dieses Projekt")

@app.get("/api/projects")
async def projects_list(request: Request):
    u = require(request); c = db(); ids = user_projects(c, u)
    rows = [dict(r) for r in c.execute("SELECT id,name,number,created,archived FROM projects WHERE archived=0 ORDER BY name")]
    rows = [r for r in rows if r["id"] in ids]
    for r in rows: r["defects"] = c.execute("SELECT COUNT(*) FROM defects WHERE project_id=? AND deleted=0", (r["id"],)).fetchone()[0]
    c.close(); return rows

@app.post("/api/projects")
async def project_save(request: Request):
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
    if d.get("id"):
        c.execute("UPDATE projects SET name=?, number=? WHERE id=?", (d.get("name") or "", d.get("number") or "", d["id"])); pid = d["id"]
    else:
        pid = uid(); c.execute("INSERT INTO projects(id,name,number,created) VALUES(?,?,?,?)", (pid, d.get("name") or "Neues Projekt", d.get("number") or "", now()))
    c.commit(); c.close(); return {"ok": True, "id": pid}

@app.delete("/api/projects/{pid}")
async def project_delete(request: Request, pid: str):
    require(request, ["bauleiter"]); c = db(); c.execute("UPDATE projects SET archived=1 WHERE id=?", (pid,)); c.commit(); c.close(); return {"ok": True}

@app.get("/api/projects/{pid}/full")
async def project_full(request: Request, pid: str):
    """Alles zu einem Projekt – gefiltert nach Rolle."""
    u = require(request); c = db(); project_access(c, u, pid)
    p = dict(c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    plans = [dict(r) for r in c.execute("SELECT * FROM plans WHERE project_id=? AND deleted=0 ORDER BY sort,added", (pid,))]
    for pl in plans: pl["src"] = f"/api/plans/{pl['id']}/image?v={pl.get('replaced') or pl.get('added') or ''}"; pl["history"] = json.loads(pl.get("history") or "[]")
    ctrs = [dict(r) for r in c.execute("SELECT * FROM contractors WHERE project_id=? AND deleted=0 ORDER BY bkp,name", (pid,))]
    for ct in ctrs: ct["phones"] = json.loads(ct.get("phones") or "[]")
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
    c.close()
    return {"project": {"id": p["id"], "name": p["name"], "number": p["number"], "currentPlanId": p["current_plan"], "settings": json.loads(p["settings"] or "{}")},
            "plans": plans, "contractors": ctrs, "defects": defs, "history": hist, "role": u["role"]}

@app.post("/api/projects/{pid}/settings")
async def project_settings(request: Request, pid: str):
    u = require(request); d = await body(request); c = db(); project_access(c, u, pid)
    if "currentPlanId" in d: c.execute("UPDATE projects SET current_plan=? WHERE id=?", (d["currentPlanId"], pid))
    if "settings" in d and u["role"] == "bauleiter": c.execute("UPDATE projects SET settings=? WHERE id=?", (json.dumps(d["settings"], ensure_ascii=False), pid))
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
        c.execute("UPDATE contractors SET name=?,bkp=?,trade=?,email=?,salutation=?,first_name=?,last_name=?,address=?,phones=?,note=? WHERE id=? AND project_id=?", vals + (cid, pid))
    else:
        c.execute("INSERT INTO contractors(id,project_id,name,bkp,trade,email,salutation,first_name,last_name,address,phones,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (cid, pid) + vals)
    initial_pw = None
    if d.get("createLogin") and d.get("email"):
        email = d["email"].strip().lower()
        row = c.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
        if row: user_id = row["id"]
        else:
            user_id = uid(); initial_pw = secrets.token_urlsafe(6)
            c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)", (user_id, email, hash_pw(initial_pw), "unternehmer", d.get("name") or "", 1, 1, now()))
        c.execute("UPDATE contractors SET user_id=? WHERE id=?", (user_id, cid))
    c.commit(); c.close(); return {"ok": True, "id": cid, "initialPassword": initial_pw}

@app.delete("/api/contractors/{cid}")
async def contractor_delete(request: Request, cid: str):
    require(request, ["bauleiter"]); c = db(); c.execute("UPDATE contractors SET deleted=1 WHERE id=?", (cid,)); c.commit(); c.close(); return {"ok": True}

# ----------------------------------------------------------------- Mängel
def defect_row(c, did):
    r = c.execute("SELECT * FROM defects WHERE id=? AND deleted=0", (did,)).fetchone()
    if not r: raise HTTPException(404, "Mangel nicht gefunden")
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
    if d.get("id"):
        old = defect_row(c, d["id"]); did = d["id"]
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
    c.commit(); row = defect_row(c, did); c.close(); return {"ok": True, "id": did, "nr": row["nr"]}

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
    new = d.get("status")
    if u["role"] == "unternehmer":
        if df["contractor_id"] not in own_contractor_ids(c, u, df["project_id"]): c.close(); raise HTTPException(403, "Nicht Ihr Mangel")
        if new != "bearbeitet" or df["status"] != "offen": c.close(); raise HTTPException(403, "Unternehmer dürfen nur offene Mängel als bearbeitet melden")
    if new == "bearbeitet":
        c.execute("UPDATE defects SET status='bearbeitet', fixed_at=?, fix_note=?, updated=? WHERE id=?", (now(), d.get("note") or "", now(), did))
        add_photos(c, did, "proof", d.get("proofPhotos"))
        log(c, df["project_id"], did, u, "bearbeitet", d.get("note") or "")
    elif new == "erledigt":
        c.execute("UPDATE defects SET status='erledigt', closed_at=?, updated=? WHERE id=?", (now(), now(), did)); log(c, df["project_id"], did, u, "erledigt", "")
    elif new == "offen":
        reason = (d.get("reason") or "").strip()
        if not reason: c.close(); raise HTTPException(400, "Begründung erforderlich")
        c.execute("UPDATE defects SET status='offen', closed_at=NULL, reopen_reason=?, updated=? WHERE id=?", (reason, now(), did)); log(c, df["project_id"], did, u, "offen", reason)
    else: c.close(); raise HTTPException(400, "Unbekannter Status")
    c.commit(); c.close(); return {"ok": True}

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
    c.commit(); c.close(); return {"ok": True}

@app.delete("/api/defects/{did}")
async def defect_delete(request: Request, did: str):
    u = require(request, ["bauleiter"]); c = db(); df = defect_row(c, did); project_access(c, u, df["project_id"])
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
        if r["key"] in ("smtp",) and u["role"] != "bauleiter": continue
        try: out[r["key"]] = json.loads(r["value"])
        except Exception: out[r["key"]] = r["value"]
    c.close(); return out

@app.post("/api/settings")
async def settings_set(request: Request):
    require(request, ["bauleiter"]); d = await body(request); c = db()
    for k, v in d.items():
        if k in ("bkp", "company", "mail", "pdf", "backup", "smtp"): c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False)))
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
    require(request, ["bauleiter"]); d = await body(request)
    for ext in ("png", "jpg", "jpeg"): (DATA / f"logo.{ext}").unlink(missing_ok=True)
    save_dataurl(d.get("src"), DATA, "logo"); return {"ok": True}

# ----------------------------------------------------------------- Import (App-Export JSON) / Export / Backup
@app.post("/api/import")
async def import_json(request: Request):
    """Import eines Exports der Browser-Version (type mm-backup). Legt Projekte neu an."""
    u = require(request, ["bauleiter"]); d = await body(request); c = db()
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
    u = require(request, ["bauleiter"]); c = db(); out = {"type": "mm-backup", "v": 2, "exported": now(), "projects": []}
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

@app.get("/api/backup.zip")
async def backup_zip(request: Request):
    """Kompletter Datenordner als ZIP (Datenbank + Fotos + Pläne + Logo)."""
    require(request, ["bauleiter"])
    c = db(); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in DATA.rglob("*"):
            if p.is_file() and not p.name.endswith(("-wal", "-shm")): z.write(p, p.relative_to(DATA))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=MaengelManagement-Backup-{datetime.date.today()}.zip"})

# ----------------------------------------------------------------- App ausliefern
@app.get("/", response_class=HTMLResponse)
async def index():
    p = ROOT / "static" / "index.html"
    return HTMLResponse(p.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})

if (ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

if __name__ == "__main__":
    import uvicorn, socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
    except Exception: ip = "127.0.0.1"
    print(f"\n  MängelManagement-Server läuft.\n  Am PC:    http://localhost:8000\n  Im WLAN:  http://{ip}:8000   (Handy/Tablet im selben Netz)\n  Daten:    {DATA}\n")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MM_PORT", "8000")), log_level="warning")
