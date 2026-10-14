# -*- coding: utf-8 -*-
"""
MängelArchiv – Abgleich der MängelManagement-App in eine Access-Datenbank (Windows)

Ablauf:  App → Menü → Sichern → "Alles exportieren" (.json)
         MaengelArchiv.py starten → Export-Datei + Archivordner wählen → Abgleichen

Ergebnis im Archivordner:
  MaengelArchiv.accdb                  Access-Datenbank (wird angelegt, falls fehlend)
  <Projekt>/<BKP>_<Firma>/             ein Ordner pro Unternehmer, darin die Fotos
      P-0003_1.jpg                     Foto 1 zu Pendenz Nr. 3
      P-0003_bearbeitet_1.jpg          Beweisfoto des Unternehmers
      Plan_<Planname>.jpg              Grundrisse des Projekts (im Projektordner)

Tabellen:  Projekte, Unternehmer, Pendenzen (eine Tabelle, Spalte Unternehmer),
           pro Unternehmer eine gespeicherte Abfrage "Q_<BKP>_<Firma>".
Eindeutiger Pendenz-Code:  <Projektkürzel>-<BKP>-<Nr>   z.B.  VOLIERE-285-0003

Voraussetzungen:  Windows, Microsoft Access (oder "Access Database Engine"),
                  Python 3 mit  pip install pyodbc pywin32
"""
import base64, json, os, re, sys, datetime, traceback
from pathlib import Path

try:
    import pyodbc
except ImportError:
    pyodbc = None

# ----------------------------------------------------------------- Hilfsfunktionen
def safe(s, n=60):
    s = re.sub(r"[^\w\-. äöüÄÖÜéèà]+", "_", str(s or "").replace("–", "-")).strip(" ._")
    return (s or "x")[:n]

def kuerzel(name):
    """Projektkürzel: Buchstaben/Ziffern, max. 12, Grossschreibung."""
    k = re.sub(r"[^A-Za-z0-9]+", "", name or "").upper()
    return k[:12] or "PROJ"

def iso_to_dt(s):
    if not s: return None
    try: return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except Exception: return None

def due_to_dt(s):
    if not s: return None
    try: return datetime.datetime.strptime(s, "%Y-%m-%d")
    except Exception: return None

def write_dataurl(dataurl, path):
    m = re.match(r"^data:(image/[\w+]+);base64,(.*)$", dataurl or "", re.S)
    if not m: return None
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/svg+xml": "svg"}.get(m.group(1), "jpg")
    p = Path(str(path) + "." + ext)
    data = base64.b64decode(m.group(2))
    if p.exists() and p.stat().st_size == len(data):
        return p
    p.write_bytes(data)
    return p

# ----------------------------------------------------------------- Access
def ensure_db(db_path: Path, log):
    if not db_path.exists():
        log(f"Datenbank wird angelegt: {db_path.name}")
        try:
            import win32com.client
            cat = win32com.client.Dispatch("ADOX.Catalog")
            cat.Create(f"Provider=Microsoft.ACE.OLEDB.12.0;Data Source={db_path}")
            cat = None
        except Exception as e:
            raise RuntimeError("Konnte keine leere Access-Datei anlegen (pywin32/ACE fehlt?). "
                               "Lege alternativ eine leere MaengelArchiv.accdb von Hand im Archivordner an.\n" + str(e))
    conn = pyodbc.connect(f"Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};")
    cur = conn.cursor()
    tables = {r.table_name for r in cur.tables(tableType="TABLE")}
    if "Projekte" not in tables:
        cur.execute("""CREATE TABLE Projekte (ProjektID TEXT(40) PRIMARY KEY, Kuerzel TEXT(20), Name TEXT(255),
                       Erstellt DATETIME, LetzterAbgleich DATETIME)""")
    if "Unternehmer" not in tables:
        cur.execute("""CREATE TABLE Unternehmer (UnternehmerKey TEXT(80) PRIMARY KEY, ProjektID TEXT(40), UnternehmerID DOUBLE,
                       Firma TEXT(255), BKP TEXT(10), Bezeichnung TEXT(255), Email TEXT(255), Anrede TEXT(10), Vorname TEXT(100),
                       Nachname TEXT(100), Adresse MEMO, Telefone TEXT(255), Bemerkung MEMO, Ordner TEXT(255))""")
    if "Pendenzen" not in tables:
        cur.execute("""CREATE TABLE Pendenzen (PendenzCode TEXT(60) PRIMARY KEY, ProjektID TEXT(40), Projekt TEXT(255), Nr LONG,
                       UnternehmerKey TEXT(80), Firma TEXT(255), BKP TEXT(10), Bezeichnung TEXT(255), Plan TEXT(255),
                       Beschreibung MEMO, Status TEXT(20), Frist DATETIME, Erfasst DATETIME, Bearbeitet DATETIME,
                       BearbeitetNotiz MEMO, Erledigt DATETIME, PosX DOUBLE, PosY DOUBLE, AnzFotos LONG, AnzBeweisfotos LONG,
                       FotoOrdner TEXT(255), AppID TEXT(40), LetzterAbgleich DATETIME)""")
    conn.commit()
    return conn

def upsert(cur, table, key_col, key, values: dict):
    cols = list(values.keys())
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {key_col}=?", key)
    if cur.fetchone()[0]:
        sets = ", ".join(f"[{c}]=?" for c in cols)
        cur.execute(f"UPDATE {table} SET {sets} WHERE {key_col}=?", *[values[c] for c in cols], key)
        return "update"
    names = ", ".join(f"[{c}]" for c in [key_col] + cols)
    qs = ", ".join("?" for _ in range(len(cols) + 1))
    cur.execute(f"INSERT INTO {table} ({names}) VALUES ({qs})", key, *[values[c] for c in cols])
    return "insert"

def ensure_queries(db_path: Path, names_sql: dict, log):
    """Gespeicherte Abfragen pro Unternehmer via DAO (Access-COM)."""
    try:
        import win32com.client
        eng = win32com.client.Dispatch("DAO.DBEngine.120")
        db = eng.OpenDatabase(str(db_path))
        existing = {db.QueryDefs(i).Name for i in range(db.QueryDefs.Count)}
        for name, sql in names_sql.items():
            if name in existing:
                db.QueryDefs(name).SQL = sql
            else:
                db.CreateQueryDef(name, sql)
        db.Close()
        log(f"{len(names_sql)} Unternehmer-Abfragen aktualisiert.")
    except Exception as e:
        log("Hinweis: Abfragen konnten nicht angelegt werden (DAO/pywin32): " + str(e))

# ----------------------------------------------------------------- Abgleich
def sync(export_path: Path, archive: Path, log):
    if pyodbc is None:
        raise RuntimeError("pyodbc fehlt:  pip install pyodbc pywin32")
    data = json.loads(Path(export_path).read_text(encoding="utf-8"))
    if data.get("type") != "mm-backup":
        raise RuntimeError("Das ist keine Export-Datei der MängelManagement-App.")
    archive.mkdir(parents=True, exist_ok=True)
    db_path = archive / "MaengelArchiv.accdb"
    conn = ensure_db(db_path, log)
    cur = conn.cursor()
    now = datetime.datetime.now()
    queries = {}
    stats = {"pendenzen": 0, "neu": 0, "fotos": 0}

    for proj in data["projects"]:
        pk = kuerzel(proj["name"])
        pdir = archive / safe(proj["name"])
        pdir.mkdir(exist_ok=True)
        log(f"Projekt: {proj['name']}  ({pk})")
        upsert(cur, "Projekte", "ProjektID", proj["id"],
               {"Kuerzel": pk, "Name": proj["name"], "Erstellt": iso_to_dt(proj.get("created")), "LetzterAbgleich": now})
        # Pläne ablegen
        plans = {p["id"]: p for p in proj.get("plans", [])}
        for p in plans.values():
            write_dataurl(p.get("src"), pdir / f"Plan_{safe(p['name'])}")
        # Unternehmer
        ctr = {}
        for c in proj.get("contractors", []):
            key = f"{proj['id']}|{c['id']}"
            folder = f"{safe(c.get('bkp') or '000')}_{safe(c['name'])}"
            (pdir / folder).mkdir(exist_ok=True)
            phones = "; ".join(f"{p.get('label','')} {p.get('number','')}".strip() for p in c.get("phones", []) if p.get("number"))
            upsert(cur, "Unternehmer", "UnternehmerKey", key, {
                "ProjektID": proj["id"], "UnternehmerID": float(c["id"]), "Firma": c["name"], "BKP": c.get("bkp") or "",
                "Bezeichnung": c.get("trade") or "", "Email": c.get("email") or "", "Anrede": c.get("salutation") or "",
                "Vorname": c.get("firstName") or "", "Nachname": c.get("lastName") or "", "Adresse": c.get("address") or "",
                "Telefone": phones, "Bemerkung": c.get("note") or "", "Ordner": str(pdir / folder)})
            ctr[c["id"]] = {"key": key, "folder": pdir / folder, "c": c}
            qname = f"Q_{safe(c.get('bkp') or '000')}_{safe(c['name'], 40)}"
            queries[qname] = (f"SELECT Nr, PendenzCode, Projekt, Plan, Beschreibung, Status, Frist, Erfasst, Bearbeitet, "
                              f"BearbeitetNotiz, Erledigt, AnzFotos, FotoOrdner FROM Pendenzen "
                              f"WHERE UnternehmerKey='{key}' ORDER BY Nr")
        # Pendenzen
        for d in proj.get("defects", []):
            c = ctr.get(d.get("contractorId"))
            bkp = (c["c"].get("bkp") if c else None) or "000"
            nr = int(d.get("nr") or 0)
            code = f"{pk}-{bkp}-{nr:04d}"
            folder = c["folder"] if c else (pdir / "000_ohne_Unternehmer")
            folder.mkdir(exist_ok=True)
            # Fotos
            n_ph = 0
            for i, ph in enumerate(d.get("photos", []), 1):
                if write_dataurl(ph, folder / f"P-{nr:04d}_{i}"): n_ph += 1
            n_pr = 0
            for i, ph in enumerate(d.get("proofPhotos", []) or [], 1):
                if write_dataurl(ph, folder / f"P-{nr:04d}_bearbeitet_{i}"): n_pr += 1
            stats["fotos"] += n_ph + n_pr
            res = upsert(cur, "Pendenzen", "PendenzCode", code, {
                "ProjektID": proj["id"], "Projekt": proj["name"], "Nr": nr,
                "UnternehmerKey": c["key"] if c else "", "Firma": c["c"]["name"] if c else "",
                "BKP": bkp if c else "", "Bezeichnung": (c["c"].get("trade") or "") if c else "",
                "Plan": plans.get(d.get("planId"), {}).get("name", ""),
                "Beschreibung": d.get("desc") or "", "Status": d.get("status") or "offen",
                "Frist": due_to_dt(d.get("due")), "Erfasst": iso_to_dt(d.get("created")),
                "Bearbeitet": iso_to_dt(d.get("fixedAt")), "BearbeitetNotiz": d.get("fixNote") or "",
                "Erledigt": iso_to_dt(d.get("closedAt")), "PosX": float(d.get("x") or 0), "PosY": float(d.get("y") or 0),
                "AnzFotos": n_ph, "AnzBeweisfotos": n_pr, "FotoOrdner": str(folder), "AppID": d.get("id") or "",
                "LetzterAbgleich": now})
            stats["pendenzen"] += 1
            if res == "insert": stats["neu"] += 1
        conn.commit()
    conn.close()
    ensure_queries(db_path, queries, log)
    log(f"Fertig: {stats['pendenzen']} Pendenzen abgeglichen ({stats['neu']} neu), {stats['fotos']} Fotos abgelegt.")
    return stats

# ----------------------------------------------------------------- GUI
def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    root = tk.Tk(); root.title("MängelArchiv – Abgleich App → Access"); root.geometry("640x420")
    cfg_path = Path.home() / ".maengelarchiv.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    v_exp = tk.StringVar(value=cfg.get("export", "")); v_arc = tk.StringVar(value=cfg.get("archive", ""))
    f = tk.Frame(root, padx=10, pady=10); f.pack(fill="both", expand=True)
    tk.Label(f, text="Export-Datei der App (.json):").grid(row=0, column=0, sticky="w")
    tk.Entry(f, textvariable=v_exp, width=60).grid(row=1, column=0, sticky="we")
    tk.Button(f, text="…", command=lambda: v_exp.set(filedialog.askopenfilename(filetypes=[("Export", "*.json")]) or v_exp.get())).grid(row=1, column=1)
    tk.Label(f, text="Archivordner (enthält MaengelArchiv.accdb):").grid(row=2, column=0, sticky="w", pady=(8, 0))
    tk.Entry(f, textvariable=v_arc, width=60).grid(row=3, column=0, sticky="we")
    tk.Button(f, text="…", command=lambda: v_arc.set(filedialog.askdirectory() or v_arc.get())).grid(row=3, column=1)
    log_box = scrolledtext.ScrolledText(f, height=12); log_box.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=8)
    f.rowconfigure(5, weight=1); f.columnconfigure(0, weight=1)
    def log(s): log_box.insert("end", s + "\n"); log_box.see("end"); root.update()
    def run():
        if not v_exp.get() or not v_arc.get(): messagebox.showwarning("Fehlt", "Export-Datei und Archivordner wählen."); return
        cfg_path.write_text(json.dumps({"export": v_exp.get(), "archive": v_arc.get()}))
        log_box.delete("1.0", "end")
        try:
            sync(Path(v_exp.get()), Path(v_arc.get()), log)
            messagebox.showinfo("Fertig", "Abgleich abgeschlossen.")
        except Exception as e:
            log("FEHLER: " + str(e)); log(traceback.format_exc()); messagebox.showerror("Fehler", str(e))
    tk.Button(f, text="Abgleichen", command=run, bg="#c0392b", fg="white", padx=16, pady=6).grid(row=4, column=0, sticky="w", pady=4)
    root.mainloop()

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        sync(Path(sys.argv[1]), Path(sys.argv[2]), print)
    else:
        gui()
