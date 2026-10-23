from datetime import datetime, date
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
import sqlite3
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "school.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-development-secret")

SCHOOL_START = "07:00"
GRACE_MINUTES = 15

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            academic_year TEXT NOT NULL,
            term_number INTEGER NOT NULL CHECK(term_number BETWEEN 1 AND 3),
            start_date TEXT,
            end_date TEXT,
            active INTEGER NOT NULL DEFAULT 0,
            UNIQUE(academic_year, term_number)
        );
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_code TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student','teacher')),
            class_name TEXT,
            department TEXT,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS scan_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL REFERENCES people(id),
            term_id INTEGER NOT NULL REFERENCES terms(id),
            scan_type TEXT NOT NULL CHECK(scan_type IN ('entrance_in','entrance_out','classroom')),
            scanned_at TEXT NOT NULL,
            class_name TEXT,
            subject TEXT,
            scanned_by TEXT,
            status TEXT NOT NULL,
            note TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_scans_person_date ON scan_events(person_id, scanned_at);
        CREATE INDEX IF NOT EXISTS idx_scans_term ON scan_events(term_id);
        """)
        active = db.execute("SELECT id FROM terms WHERE active=1").fetchone()
        if not active:
            year = str(date.today().year)
            db.execute("INSERT OR IGNORE INTO terms(academic_year, term_number, start_date, end_date, active) VALUES(?,1,?, ?,1)",
                       (year, f"{year}-01-01", f"{year}-04-30"))
            term1 = db.execute("SELECT id FROM terms WHERE academic_year=? AND term_number=1", (year,)).fetchone()
            db.execute("UPDATE terms SET active=0")
            db.execute("UPDATE terms SET active=1 WHERE id=?", (term1["id"],))
        # Demonstration records are added only when the people table is empty.
        if db.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO people(person_code, full_name, role, class_name, department) VALUES(?,?,?,?,?)",
                [
                    ("STU001", "Example Student One", "student", "Form 1A", None),
                    ("STU002", "Example Student Two", "student", "Form 1A", None),
                    ("TCH001", "Example Teacher", "teacher", None, "Mathematics"),
                ],
            )

def active_term(db):
    row = db.execute("""
        SELECT * FROM terms WHERE active=1
        ORDER BY academic_year DESC, term_number DESC LIMIT 1
    """).fetchone()
    if not row:
        raise ValueError("No active term. Create or activate a term first.")
    return row

def classify_arrival(timestamp):
    # Arrival is on time through 07:15 inclusive.
    t = timestamp.strftime("%H:%M")
    cutoff = "07:15"
    return "on_time" if t <= cutoff else "late"

def person_by_code(db, code):
    return db.execute("SELECT * FROM people WHERE person_code=? AND active=1", (code.strip().upper(),)).fetchone()

@app.route("/")
def index():
    with connect_db() as db:
        term = active_term(db)
        people_count = db.execute("SELECT COUNT(*) FROM people WHERE active=1").fetchone()[0]
        today = date.today().isoformat()
        entrance_count = db.execute("""
            SELECT COUNT(DISTINCT person_id) FROM scan_events
            WHERE term_id=? AND scan_type='entrance_in' AND substr(scanned_at,1,10)=?
        """, (term["id"], today)).fetchone()[0]
        late_count = db.execute("""
            SELECT COUNT(*) FROM scan_events
            WHERE term_id=? AND scan_type='entrance_in' AND status='late'
            AND substr(scanned_at,1,10)=?
        """, (term["id"], today)).fetchone()[0]
        recent = db.execute("""
            SELECT s.*, p.person_code, p.full_name, p.role
            FROM scan_events s JOIN people p ON p.id=s.person_id
            WHERE s.term_id=? ORDER BY s.id DESC LIMIT 12
        """, (term["id"],)).fetchall()
        people = db.execute("SELECT * FROM people WHERE active=1 ORDER BY role, full_name").fetchall()
        terms = db.execute("SELECT * FROM terms ORDER BY academic_year DESC, term_number DESC").fetchall()
    return render_template("index.html", term=term, people_count=people_count,
                           entrance_count=entrance_count, late_count=late_count,
                           recent=recent, people=people, terms=terms,
                           start=SCHOOL_START, grace=GRACE_MINUTES)

@app.post("/people")
def add_person():
    code = request.form.get("person_code", "").strip().upper()
    name = request.form.get("full_name", "").strip()
    role = request.form.get("role", "").strip()
    class_name = request.form.get("class_name", "").strip() or None
    department = request.form.get("department", "").strip() or None
    if not code or not name or role not in ("student", "teacher"):
        flash("Enter an ID, full name, and valid role.", "error")
        return redirect(url_for("index"))
    try:
        with connect_db() as db:
            db.execute("""INSERT INTO people(person_code,full_name,role,class_name,department)
                          VALUES(?,?,?,?,?)""", (code, name, role, class_name, department))
        flash(f"Added {name} ({code}).", "success")
    except sqlite3.IntegrityError:
        flash("That ID already exists. Use a unique student/staff ID.", "error")
    return redirect(url_for("index"))

@app.post("/terms")
def add_term():
    year = request.form.get("academic_year", "").strip()
    term_number = request.form.get("term_number", type=int)
    start_date = request.form.get("start_date", "").strip() or None
    end_date = request.form.get("end_date", "").strip() or None
    activate = request.form.get("activate") == "yes"
    if not year or term_number not in (1, 2, 3):
        flash("Enter an academic year and Term 1, 2, or 3.", "error")
        return redirect(url_for("index"))
    try:
        with connect_db() as db:
            db.execute("""INSERT INTO terms(academic_year,term_number,start_date,end_date,active)
                          VALUES(?,?,?,?,0)""", (year, term_number, start_date, end_date))
            if activate:
                db.execute("UPDATE terms SET active=0")
                db.execute("UPDATE terms SET active=1 WHERE academic_year=? AND term_number=?", (year, term_number))
        flash("Term created." + (" It is now active." if activate else ""), "success")
    except sqlite3.IntegrityError:
        flash("That academic year and term already exist.", "error")
    return redirect(url_for("index"))

@app.post("/terms/<int:term_id>/activate")
def activate_term(term_id):
    with connect_db() as db:
        exists = db.execute("SELECT id FROM terms WHERE id=?", (term_id,)).fetchone()
        if exists:
            db.execute("UPDATE terms SET active=0")
            db.execute("UPDATE terms SET active=1 WHERE id=?", (term_id,))
            flash("Active term changed. New scans will be stored under this term.", "success")
        else:
            flash("Term not found.", "error")
    return redirect(url_for("index"))

@app.post("/api/scan")
def scan():
    payload = request.get_json(silent=True) or request.form
    code = str(payload.get("person_code", "")).strip().upper()
    scan_type = str(payload.get("scan_type", "entrance_in")).strip()
    class_name = str(payload.get("class_name", "")).strip() or None
    subject = str(payload.get("subject", "")).strip() or None
    scanned_by = str(payload.get("scanned_by", "")).strip() or None

    if not code:
        return jsonify(ok=False, message="Enter or scan an ID code."), 400
    if scan_type not in ("entrance_in", "entrance_out", "classroom"):
        return jsonify(ok=False, message="Choose entrance sign-in, entrance sign-out, or classroom attendance."), 400

    now = datetime.now()
    timestamp = now.isoformat(timespec="seconds")
    with connect_db() as db:
        person = person_by_code(db, code)
        if not person:
            return jsonify(ok=False, message=f"No active student or teacher found for ID {code}."), 404
        term = active_term(db)

        if scan_type == "classroom":
            if person["role"] != "student":
                return jsonify(ok=False, message="Classroom attendance scans must use a student ID."), 400
            if not class_name:
                class_name = person["class_name"]
            duplicate = db.execute("""
                SELECT id FROM scan_events WHERE person_id=? AND term_id=? AND scan_type='classroom'
                AND substr(scanned_at,1,10)=? AND COALESCE(class_name,'')=COALESCE(?,'')
                AND COALESCE(subject,'')=COALESCE(?,'')
            """, (person["id"], term["id"], now.date().isoformat(), class_name, subject)).fetchone()
            if duplicate:
                return jsonify(ok=False, message="This student is already registered for this class/subject today.",
                               person=person["full_name"]), 409
            status = "present"
        elif scan_type == "entrance_in":
            # Only one sign-in per person per date; corrections should be made by authorized staff.
            existing = db.execute("""
                SELECT id FROM scan_events WHERE person_id=? AND term_id=? AND scan_type='entrance_in'
                AND substr(scanned_at,1,10)=?
            """, (person["id"], term["id"], now.date().isoformat())).fetchone()
            if existing:
                return jsonify(ok=False, message="An entrance sign-in is already recorded for this person today.",
                               person=person["full_name"]), 409
            status = classify_arrival(now) if person["role"] in ("student", "teacher") else "present"
        else:
            prior_in = db.execute("""
                SELECT id FROM scan_events WHERE person_id=? AND term_id=? AND scan_type='entrance_in'
                AND substr(scanned_at,1,10)=?
            """, (person["id"], term["id"], now.date().isoformat())).fetchone()
            if not prior_in:
                return jsonify(ok=False, message="Sign-in must be recorded before sign-out."), 409
            existing_out = db.execute("""
                SELECT id FROM scan_events WHERE person_id=? AND term_id=? AND scan_type='entrance_out'
                AND substr(scanned_at,1,10)=?
            """, (person["id"], term["id"], now.date().isoformat())).fetchone()
            if existing_out:
                return jsonify(ok=False, message="Sign-out is already recorded for today.",
                               person=person["full_name"]), 409
            status = "signed_out"

        db.execute("""
            INSERT INTO scan_events(person_id,term_id,scan_type,scanned_at,class_name,subject,scanned_by,status)
            VALUES(?,?,?,?,?,?,?,?)
        """, (person["id"], term["id"], scan_type, timestamp, class_name, subject, scanned_by, status))

    label = {"entrance_in": "Entrance sign-in", "entrance_out": "Entrance sign-out", "classroom": "Classroom attendance"}[scan_type]
    return jsonify(ok=True, message=f"{label} saved for {person['full_name']}.",
                   person=person["full_name"], role=person["role"], code=person["person_code"],
                   time=now.strftime("%H:%M:%S"), status=status, term=f"{term['academic_year']} Term {term['term_number']}")

@app.get("/reports")
def reports():
    term_id = request.args.get("term_id", type=int)
    with connect_db() as db:
        terms = db.execute("SELECT * FROM terms ORDER BY academic_year DESC, term_number DESC").fetchall()
        if term_id is None:
            term = active_term(db)
        else:
            term = db.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()
            if term is None:
                term = active_term(db)
        rows = db.execute("""
            SELECT p.person_code, p.full_name, p.role, p.class_name,
                   substr(s.scanned_at,1,10) AS attendance_date,
                   MIN(CASE WHEN s.scan_type='entrance_in' THEN s.scanned_at END) AS sign_in,
                   MAX(CASE WHEN s.scan_type='entrance_out' THEN s.scanned_at END) AS sign_out,
                   SUM(CASE WHEN s.scan_type='entrance_in' AND s.status='late' THEN 1 ELSE 0 END) AS late_count,
                   SUM(CASE WHEN s.scan_type='classroom' THEN 1 ELSE 0 END) AS classroom_count
            FROM scan_events s JOIN people p ON p.id=s.person_id
            WHERE s.term_id=?
            GROUP BY p.id, substr(s.scanned_at,1,10)
            ORDER BY attendance_date DESC, p.full_name
        """, (term["id"],)).fetchall()
    return render_template("reports.html", terms=terms, term=term, rows=rows)

@app.get("/health")
def health():
    return jsonify(ok=True, service="QR School Management System")

init_db()

if __name__ == "__main__":
    # Accessible on the local network when host=0.0.0.0, subject to firewall/network settings.
    app.run(host="0.0.0.0", port=5000, debug=True)
