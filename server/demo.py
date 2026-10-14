# -*- coding: utf-8 -*-
"""Legt ein Beispielprojekt an: 7 Geschosse, 30 Unternehmer, 270 Pendenzen (200 offen / 30 bearbeitet / 40 erledigt).
Aufruf:  python demo.py   (Server darf laufen; danach in der App neu laden)"""
import random, datetime, json, base64, io, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MM_DEMO", "1")
import app as srv
from PIL import Image, ImageDraw, ImageFont

random.seed(42)
def font(sz):
    for f in ("DejaVuSans.ttf", "arial.ttf", "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try: return ImageFont.truetype(f, sz)
        except Exception: pass
    return ImageFont.load_default()

FLOORS = ["2. UG", "1. UG", "EG", "1. OG", "2. OG", "3. OG", "4. OG"]
ROOMS = {
 "2. UG": ["Einstellhalle", "Technik", "Lager", "Schutzraum"], "1. UG": ["Keller", "Waschküche", "Velo", "Heizung", "Lager"],
 "EG": ["Eingang", "Büro 1", "Büro 2", "Sitzung", "Küche", "WC"], "1. OG": ["Wohnung 1.1", "Wohnung 1.2", "Wohnung 1.3", "Treppenhaus"],
 "2. OG": ["Wohnung 2.1", "Wohnung 2.2", "Wohnung 2.3", "Treppenhaus"], "3. OG": ["Wohnung 3.1", "Wohnung 3.2", "Treppenhaus", "Terrasse"],
 "4. OG": ["Attika", "Dachterrasse", "Technik", "Treppenhaus"]}

def plan_png(name):
    W, H = 1800, 1270; im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
    d.rectangle([100, 100, 1700, 1170], outline="#222", width=8)
    rooms = ROOMS[name]; cols = 3 if len(rooms) > 4 else 2; rows = (len(rooms) + cols - 1) // cols
    cw, rh = 1600 / cols, 1070 / rows
    for i, r in enumerate(rooms):
        cx, cy = 100 + (i % cols) * cw, 100 + (i // cols) * rh
        d.rectangle([cx, cy, cx + cw, cy + rh], outline="#222", width=5)
        d.text((cx + 30, cy + 30), r, fill="#333", font=font(34)); d.text((cx + 30, cy + 80), f"{random.randint(12, 48)}.{random.randint(10, 99)} m²", fill="#777", font=font(26))
        d.line([cx + cw * .3, cy + rh, cx + cw * .3 + 90, cy + rh], fill="white", width=6)  # Tür
        d.arc([cx + cw * .3 - 90, cy + rh - 90, cx + cw * .3 + 90, cy + rh + 90], 270, 360, fill="#222", width=3)
    d.text((100, 40), f"{name} – Beispielgrundriss", fill="#222", font=font(36)); d.text((1500, 1200), "1:100", fill="#999", font=font(26))
    buf = io.BytesIO(); im.save(buf, "PNG", optimize=True); return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

def photo_jpg(nr, proof=False):
    im = Image.new("RGB", (640, 480), (random.randint(150, 220), random.randint(150, 220), random.randint(150, 220))); d = ImageDraw.Draw(im)
    for _ in range(12): x, y = random.randint(0, 640), random.randint(0, 480); d.line([x, y, x + random.randint(-120, 120), y + random.randint(-120, 120)], fill=(90, 90, 90), width=random.randint(2, 6))
    d.text((20, 20), ("Beweisfoto" if proof else "Foto") + f" Mangel {nr}", fill="#222", font=font(32))
    if not proof: d.ellipse([260, 180, 400, 320], outline=(229, 57, 53), width=8)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=70); return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

CTRS = [("211","Baumeisterarbeiten","Baumeister Hoch AG"),("212","Vorfabrizierte Rohbauelemente","Elementbau Frei AG"),("214","Montagebau in Holz","Holzbau Zimmermann AG"),("216","Natur- und Kunststeinarbeiten","Steinwerk Granit GmbH"),
 ("221","Fenster, Aussentüren, Tore","Fensterbau Klar AG"),("222","Spenglerarbeiten","Spenglerei Blech AG"),("224","Bedachungsarbeiten","Dach & Co AG"),("225","Spezielle Dichtungen und Dämmungen","Isoltech GmbH"),("226","Fassadenputze","Fassaden Putz AG"),("228","Äussere Abschlüsse, Sonnenschutz","Storen Schatten AG"),
 ("232","Starkstrominstallationen","Elektro Ludwig AG"),("233","Leuchten und Lampen","Lichtwerk GmbH"),("236","Schwachstrominstallationen","Netzwerk Data AG"),("237","Gebäudeautomation","Automation Smart AG"),
 ("242","Wärmeerzeugung","Heizung Warm AG"),("244","Lüftungsanlagen","Luft & Klima AG"),("248","Dämmungen HLK","Isolierwerk Nord GmbH"),
 ("251","Allgemeine Sanitärapparate","Sanitär Wasser AG"),("253","Sanitärleitungen","Rohrbau Fluss GmbH"),("258","Kücheneinrichtungen","Küchen Design AG"),
 ("261","Aufzüge","Lift Hoch AG"),
 ("271","Gipserarbeiten","Gipser Glatt AG"),("272","Metallbauarbeiten","Metallbau Stahl AG"),("273","Schreinerarbeiten","Schreinerei Holzfein AG"),("275","Schliessanlagen","Schloss & Schlüssel GmbH"),("277","Innere Trennwände, Schrankanlagen","Innenausbau Raum AG"),
 ("281","Bodenbeläge","Bodenleger Parkett AG"),("282","Wandbeläge","Plattenleger Keramik AG"),("285","Innere Oberflächenbehandlungen (Malerarbeiten)","Maler Kleistermeister"),("287","Baureinigung","Reinigung Blitz GmbH")]
FIRST = ["Hans","Peter","Anna","Maria","Lukas","Sandra","Beat","Urs","Nicole","Daniel","Reto","Claudia"]
LAST = ["Müller","Meier","Schmid","Keller","Weber","Huber","Schneider","Steiner","Fischer","Brunner","Baumann","Frei"]
DESC = ["Riss in der Wand, ca. {n} cm lang","Putz abgeplatzt oberhalb Türsturz","Fenster schliesst nicht sauber","Silikonfuge fehlt im Bereich Dusche","Bodenbelag verkratzt vor Lift","Steckdose ohne Abdeckung","Leuchte flackert","Türdrücker locker","Wasserflecken an Decke","Sockelleiste fehlt {n} cm","Farbanstrich fleckig","Fuge undicht am Balkon","Lüftungsgitter fehlt","Heizkörper tropft am Ventil","Plattenriss im Bad","Kratzer in Fensterglas","Türe streift am Boden","Rohrdurchführung nicht abgedichtet","Schranktüre hängt schief","Baureinigung unvollständig"]

def main():
    c = srv.db(); u = c.execute("SELECT * FROM users WHERE role='bauleiter' ORDER BY created LIMIT 1").fetchone(); u = dict(u)
    pid = srv.uid(); c.execute("INSERT INTO projects(id,name,number,created,next_nr) VALUES(?,?,?,?,?)", (pid, "Beispiel Wohnüberbauung Rheinblick", "12'345.0", srv.now(), 1))
    plan_ids = []
    for i, fl in enumerate(FLOORS):
        plid = srv.uid(); fn = srv.save_dataurl(plan_png(fl), srv.PLANS, plid)
        c.execute("INSERT INTO plans(id,project_id,name,sort,version,note,added,file) VALUES(?,?,?,?,?,?,?,?)", (plid, pid, fl, i, "A", "", srv.now(), fn)); plan_ids.append(plid)
    c.execute("UPDATE projects SET current_plan=? WHERE id=?", (plan_ids[2], pid))
    ctr_ids = []
    for bkp, trade, name in CTRS:
        cid = srv.uid(); fn_, ln_ = random.choice(FIRST), random.choice(LAST)
        c.execute("INSERT INTO contractors(id,project_id,name,bkp,trade,email,salutation,first_name,last_name,address,phones,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cid, pid, name, bkp, trade, f"info@{name.split()[0].lower().replace('&','und')}.example.ch", "Herr" if fn_ in ("Hans","Peter","Lukas","Beat","Urs","Daniel","Reto") else "Frau", fn_, ln_, f"Musterstrasse {random.randint(1,99)}\n{random.choice(['4052 Basel','4410 Liestal','4153 Reinach','4132 Muttenz'])}",
                   json.dumps([{"label":"Büro","number":f"+41 61 {random.randint(200,999)} {random.randint(10,99)} {random.randint(10,99)}"},{"label":"Mobil","number":f"+41 79 {random.randint(200,999)} {random.randint(10,99)} {random.randint(10,99)}"}]), ""))
        ctr_ids.append(cid)
    statuses = ["offen"] * 200 + ["bearbeitet"] * 30 + ["erledigt"] * 40; random.shuffle(statuses)
    today = datetime.datetime.now(); nr = 0; spots = []
    for st in statuses:
        nr += 1; did = srv.uid(); plid = random.choice(plan_ids); cid = random.choice(ctr_ids)
        created = today - datetime.timedelta(days=random.randint(1, 45), hours=random.randint(0, 9))
        if spots and random.random() < 0.12:  # gleicher Punkt wie eine frühere Pendenz
            sp = random.choice(spots); spot, x, y, plid = sp
        else:
            x, y = round(random.uniform(0.08, 0.92), 4), round(random.uniform(0.12, 0.9), 4); spot = did; spots.append((spot, x, y, plid))
        due = (created + datetime.timedelta(days=random.choice([7, 10, 14, 21, 30]))).strftime("%Y-%m-%d")
        fixed = closed = None; note = ""
        if st in ("bearbeitet", "erledigt"): fixed = (created + datetime.timedelta(days=random.randint(1, 12))).isoformat(timespec="seconds"); note = random.choice(["ausgebessert", "ersetzt", "nachgearbeitet und gestrichen", "neu montiert", ""])
        if st == "erledigt": closed = (datetime.datetime.fromisoformat(fixed) + datetime.timedelta(days=random.randint(1, 5))).isoformat(timespec="seconds")
        c.execute("INSERT INTO defects(id,project_id,nr,plan_id,spot_id,x,y,descr,contractor_id,due,status,created,created_by,fixed_at,fix_note,closed_at,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (did, pid, nr, plid, spot, x, y, random.choice(DESC).format(n=random.randint(10, 90)), cid, due, st, created.isoformat(timespec="seconds"), u["id"], fixed, note, closed, srv.now()))
        if random.random() < 0.7: srv.add_photos(c, did, "photo", [photo_jpg(nr)])
        if st in ("bearbeitet", "erledigt"): srv.add_photos(c, did, "proof", [photo_jpg(nr, True)])
        srv.log(c, pid, did, u, "create", f"Nr. {nr}")
        if fixed: srv.log(c, pid, did, u, "bearbeitet", note)
        if closed: srv.log(c, pid, did, u, "erledigt", "")
    c.execute("UPDATE projects SET next_nr=? WHERE id=?", (nr + 1, pid)); c.commit(); c.close()
    print(f"Beispielprojekt angelegt: 7 Pläne, {len(CTRS)} Unternehmer, {nr} Pendenzen (200 offen / 30 bearbeitet / 40 erledigt).")

if __name__ == "__main__":
    main()
