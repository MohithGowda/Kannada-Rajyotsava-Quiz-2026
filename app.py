"""Kannada Rajyotsava 2026 - Fastest Finger First quiz (Flask + SQLite)."""
import csv
import hashlib
import io
import json
import os
import random
import secrets
import socket
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit

import qrcode
from flask import (Flask, Response, abort, g, jsonify, redirect,
                   render_template, request, send_file, session, url_for)

from questions_data import DIFFICULTIES, QUESTIONS, THEMES, quiz_order

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)
DB_PATH = os.path.join(INSTANCE_DIR, "quiz.db")

# ---- Round / scoring configuration -------------------------------------
ROUND_SECONDS = 5 * 60          # default round length
CORRECT_POINTS = 100            # base points for a correct answer
SPEED_BONUS_MAX = 50            # extra points for an instant answer
SPEED_WINDOW_S = 15             # bonus shrinks linearly to 0 over this many seconds
WRONG_PENALTY = 10              # points lost for a wrong answer
GRACE_MS = 1500                 # network grace after the round ends
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "karnataka2026")
PORT = int(os.environ.get("PORT", "5000"))


def _secret_key():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = os.path.join(INSTANCE_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


app = Flask(__name__)
app.secret_key = _secret_key()
app.permanent_session_lifetime = timedelta(days=1)
app.config["JSON_AS_ASCII"] = False


# ---- Database -----------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    theme TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'medium',
    position INTEGER NOT NULL DEFAULT 0,
    text_kn TEXT NOT NULL,
    text_en TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_idx INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    members TEXT NOT NULL DEFAULT '',
    token TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    seq INTEGER NOT NULL,
    served_at REAL NOT NULL,
    answered_at REAL,
    chosen_idx INTEGER,
    is_correct INTEGER,
    time_ms INTEGER,
    points INTEGER NOT NULL DEFAULT 0,
    UNIQUE (team_id, question_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def connect():
    db = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def tx(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def bank_hash():
    return hashlib.sha256(json.dumps(QUESTIONS, ensure_ascii=False).encode("utf-8")).hexdigest()


def seed_questions(db, replace=False):
    position_of = {idx: pos for pos, idx in enumerate(quiz_order(), start=1)}
    with tx(db):
        if replace:
            db.execute("DELETE FROM answers")
            db.execute("DELETE FROM questions")
        for i, (theme, level, q_kn, q_en, correct, wrong) in enumerate(QUESTIONS, start=1):
            options = [correct] + list(wrong)
            random.Random(i * 31 + 7).shuffle(options)
            correct_idx = options.index(correct)
            payload = [{"kn": kn, "en": en} for kn, en in options]
            db.execute(
                "INSERT INTO questions (id, theme, difficulty, position, text_kn, text_en, "
                "options_json, correct_idx) VALUES (?,?,?,?,?,?,?,?)",
                (i, theme, level, position_of[i - 1], q_kn, q_en,
                 json.dumps(payload, ensure_ascii=False), correct_idx))
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('bank_hash', ?)",
                   (bank_hash(),))


def init_db():
    db = connect()
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(questions)")}
    for name, ddl in (("difficulty", "TEXT NOT NULL DEFAULT 'medium'"),
                      ("position", "INTEGER NOT NULL DEFAULT 0")):
        if name not in cols:
            db.execute(f"ALTER TABLE questions ADD COLUMN {name} {ddl}")
    for key, value in (("status", "waiting"), ("duration", str(ROUND_SECONDS)),
                       ("started_at", ""), ("ended_at", "")):
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (key, value))
    stored = db.execute("SELECT value FROM settings WHERE key='bank_hash'").fetchone()
    have_questions = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0] > 0
    if not have_questions or stored is None or stored["value"] != bank_hash():
        if db.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0:
            seed_questions(db, replace=True)   # nothing to lose: load the current question bank
        else:
            print("WARNING: questions_data.py changed but answers already exist. "
                  "Run `python app.py --reseed` to load it (this clears answers).")
    db.close()


# ---- Round state ----------------------------------------------------------
def get_round(db):
    s = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}
    status = s["status"]
    duration = int(s["duration"])
    started = float(s["started_at"]) if s["started_at"] else None
    ended = float(s["ended_at"]) if s["ended_at"] else None
    now = time.time()
    end_ts = None
    remaining = duration
    if status == "running":
        end_ts = started + duration
        remaining = end_ts - now
        if remaining <= 0:
            status, remaining = "finished", 0
    elif status == "finished":
        end_ts = ended if ended else (started + duration if started else now)
        remaining = 0
    return {"status": status, "duration": duration, "started_at": started,
            "end_ts": end_ts, "remaining_ms": int(max(0, remaining) * 1000)}


def public_round(rnd):
    return {"status": rnd["status"], "duration_s": rnd["duration"],
            "remaining_ms": rnd["remaining_ms"], "server_now_ms": int(time.time() * 1000)}


# ---- Auth helpers -----------------------------------------------------------
def current_team(db):
    tid, token = session.get("team_id"), session.get("team_token")
    if not tid or not token:
        return None
    team = db.execute("SELECT * FROM teams WHERE id=?", (tid,)).fetchone()
    if team and secrets.compare_digest(team["token"], token):
        return team
    session.pop("team_id", None)
    session.pop("team_token", None)
    return None


def team_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        team = current_team(get_db())
        if team is None:
            return jsonify(error="not_registered"), 401
        return view(team, *args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            if request.path.startswith("/api/"):
                return jsonify(error="unauthorized"), 401
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


# ---- Stats ------------------------------------------------------------------
STATS_SQL = """
SELECT t.id, t.name, t.members, t.created_at,
       COALESCE(SUM(a.points), 0) AS score,
       COALESCE(SUM(CASE WHEN a.answered_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS answered,
       COALESCE(SUM(CASE WHEN a.is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct,
       COALESCE(SUM(CASE WHEN a.is_correct = 1 THEN a.time_ms END), 0) AS correct_time_ms,
       COALESCE(SUM(CASE WHEN a.answered_at IS NOT NULL THEN a.time_ms END), 0) AS total_time_ms
FROM teams t LEFT JOIN answers a ON a.team_id = t.id
GROUP BY t.id
"""


def team_stats(db):
    teams = [dict(r) for r in db.execute(STATS_SQL)]
    for t in teams:
        t["avg_ms"] = round(t["correct_time_ms"] / t["correct"]) if t["correct"] else None
    teams.sort(key=lambda t: (-t["score"], -t["correct"], t["correct_time_ms"], t["created_at"]))
    for rank, t in enumerate(teams, start=1):
        t["rank"] = rank
    return teams


def public_team(t):
    return {"id": t["id"], "rank": t["rank"], "name": t["name"], "score": t["score"],
            "answered": t["answered"], "correct": t["correct"], "avg_ms": t["avg_ms"],
            "total_ms": t["total_time_ms"]}


def theme_info(key):
    kn, en, icon = THEMES.get(key, (key, key, "❓"))
    return {"kn": kn, "en": en, "icon": icon}


# ---- QR code ------------------------------------------------------------------
def lan_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def join_url():
    override = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if override:
        return override.rstrip("/") + "/join"
    origin = urlsplit(request.host_url)
    if origin.hostname in ("localhost", "127.0.0.1", "::1"):
        return f"{request.scheme}://{lan_ip()}:{origin.port or PORT}{url_for('register')}"
    return url_for("register", _external=True)


@app.get("/qr.png")
def qr_png():
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=2)
    qr.add_data(join_url())
    qr.make(fit=True)
    img = qr.make_image(fill_color="#3b0a0f", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    resp = send_file(buf, mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---- Participant pages -----------------------------------------------------------
@app.get("/")
def home():
    # QR-only screen meant to be projected for participants
    return render_template("home.html")


@app.get("/display")
def display():
    return redirect(url_for("home"))


@app.route("/join", methods=["GET", "POST"])
def register():
    db = get_db()
    if current_team(db):
        return redirect(url_for("play"))
    rnd = get_round(db)
    error = None
    values = {"name": "", "members": ""}
    if request.method == "POST":
        name = " ".join(request.form.get("name", "").split())
        members = " ".join(request.form.get("members", "").split())[:200]
        values = {"name": name, "members": members}
        if not 2 <= len(name) <= 40:
            error = ("ತಂಡದ ಹೆಸರು 2 ರಿಂದ 40 ಅಕ್ಷರಗಳಿರಬೇಕು.",
                     "Team name must be 2 to 40 characters.")
        elif rnd["status"] != "waiting":
            error = ("ನೋಂದಣಿ ಮುಚ್ಚಲಾಗಿದೆ.", "Registration is closed.")
        else:
            token = secrets.token_hex(16)
            try:
                cur = db.execute(
                    "INSERT INTO teams (name, members, token, created_at) VALUES (?,?,?,?)",
                    (name, members, token, time.time()))
            except sqlite3.IntegrityError:
                error = ("ಈ ತಂಡದ ಹೆಸರು ಈಗಾಗಲೇ ಬಳಕೆಯಲ್ಲಿದೆ. ಬೇರೆ ಹೆಸರು ಆರಿಸಿ.",
                         "That team name is already taken. Please choose another.")
            else:
                session.permanent = True
                session["team_id"] = cur.lastrowid
                session["team_token"] = token
                return redirect(url_for("play"))
    return render_template("register.html", error=error, values=values, rnd=rnd)


@app.get("/play")
def play():
    team = current_team(get_db())
    if team is None:
        return redirect(url_for("register"))
    return render_template("play.html", team=team)


@app.post("/leave")
def leave():
    session.pop("team_id", None)
    session.pop("team_token", None)
    return redirect(url_for("register"))


# ---- Public APIs ------------------------------------------------------------------
@app.get("/api/status")
def api_status():
    db = get_db()
    data = public_round(get_round(db))
    data["teams"] = db.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    return jsonify(data)


# ---- Quiz APIs --------------------------------------------------------------------
def question_payload(db, qid, seq, served_at, rnd):
    q = db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    return {"state": "question", "round": public_round(rnd),
            "question": {"id": q["id"], "number": seq, "theme": theme_info(q["theme"]),
                         "text_kn": q["text_kn"], "text_en": q["text_en"],
                         "options": json.loads(q["options_json"]),
                         "elapsed_ms": int(max(0, time.time() - served_at) * 1000)}}


@app.post("/api/next")
@team_required
def api_next(team):
    db = get_db()
    rnd = get_round(db)
    if rnd["status"] != "running":
        return jsonify(state=rnd["status"], round=public_round(rnd))
    with tx(db):
        row = db.execute("SELECT * FROM answers WHERE team_id=? AND answered_at IS NULL "
                         "ORDER BY seq DESC LIMIT 1", (team["id"],)).fetchone()
        if row is None:
            # every team gets the same fixed sequence (easy, medium, tough, ...)
            nxt = db.execute(
                "SELECT id FROM questions WHERE id NOT IN "
                "(SELECT question_id FROM answers WHERE team_id=?) ORDER BY position LIMIT 1",
                (team["id"],)).fetchone()
            if nxt is None:
                return jsonify(state="completed", round=public_round(rnd))
            seq = db.execute("SELECT COUNT(*) FROM answers WHERE team_id=?",
                             (team["id"],)).fetchone()[0] + 1
            qid, served = nxt["id"], time.time()
            db.execute("INSERT INTO answers (team_id, question_id, seq, served_at) VALUES (?,?,?,?)",
                       (team["id"], qid, seq, served))
        else:
            qid, seq, served = row["question_id"], row["seq"], row["served_at"]
    return jsonify(question_payload(db, qid, seq, served, rnd))


@app.post("/api/answer")
@team_required
def api_answer(team):
    data = request.get_json(silent=True) or {}
    try:
        qid, choice = int(data.get("question_id")), int(data.get("choice"))
    except (TypeError, ValueError):
        return jsonify(error="bad_request"), 400
    db = get_db()
    rnd = get_round(db)
    now = time.time()
    if rnd["end_ts"] is None or now > rnd["end_ts"] + GRACE_MS / 1000 or rnd["status"] == "waiting":
        return jsonify(error="round_over", state="finished"), 409
    with tx(db):
        row = db.execute("SELECT * FROM answers WHERE team_id=? AND question_id=?",
                         (team["id"], qid)).fetchone()
        if row is None or row["answered_at"] is not None:
            return jsonify(error="not_open"), 409
        q = db.execute("SELECT options_json, correct_idx FROM questions WHERE id=?", (qid,)).fetchone()
        if not 0 <= choice < len(json.loads(q["options_json"])):
            return jsonify(error="bad_request"), 400
        time_ms = int(max(0, now - row["served_at"]) * 1000)
        correct = choice == q["correct_idx"]
        if correct:
            bonus = round(SPEED_BONUS_MAX * max(0.0, 1 - time_ms / (SPEED_WINDOW_S * 1000)))
            points = CORRECT_POINTS + bonus
        else:
            points = -WRONG_PENALTY
        db.execute("UPDATE answers SET answered_at=?, chosen_idx=?, is_correct=?, time_ms=?, points=? "
                   "WHERE id=?", (now, choice, int(correct), time_ms, points, row["id"]))
    # Participants get no feedback: correctness, timing and scores are admin-only
    return jsonify(ok=True)


@app.get("/api/me")
@team_required
def api_me(team):
    return jsonify(name=team["name"])


# ---- Admin ----------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = False
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session.permanent = True
            session["is_admin"] = True
            return redirect(url_for("admin"))
        error = True
    return render_template("admin_login.html", error=error)


@app.get("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.get("/admin")
@admin_required
def admin():
    return render_template("admin.html")


@app.get("/admin/registrations")
@admin_required
def admin_registrations():
    return render_template("registrations.html")


@app.get("/admin/questions")
@admin_required
def admin_questions():
    return render_template("questions.html")


@app.get("/api/admin/questions")
@admin_required
def api_admin_questions():
    rows = get_db().execute("SELECT * FROM questions ORDER BY position").fetchall()
    return jsonify(
        themes=[{"key": k, "kn": v[0], "en": v[1], "icon": v[2]} for k, v in THEMES.items()],
        difficulties=[{"key": k, "kn": v[0], "en": v[1]} for k, v in DIFFICULTIES.items()],
        questions=[{"id": r["id"], "position": r["position"], "difficulty": r["difficulty"],
                    "theme": r["theme"], "text_kn": r["text_kn"], "text_en": r["text_en"],
                    "options": json.loads(r["options_json"]), "correct_idx": r["correct_idx"]}
                   for r in rows])


@app.get("/api/admin/registrations")
@admin_required
def api_admin_registrations():
    db = get_db()
    rows = db.execute("SELECT id, name, members, created_at FROM teams ORDER BY created_at").fetchall()
    return jsonify(round=public_round(get_round(db)), join_url=join_url(),
                   teams=[{"id": r["id"], "no": i, "name": r["name"], "members": r["members"],
                           "registered_at_ms": int(r["created_at"] * 1000)}
                          for i, r in enumerate(rows, start=1)])


@app.get("/api/admin/overview")
@admin_required
def api_admin_overview():
    db = get_db()
    teams = team_stats(db)
    return jsonify(round=public_round(get_round(db)), join_url=join_url(),
                   question_count=db.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
                   teams=[{**public_team(t), "members": t["members"]} for t in teams])


@app.post("/api/admin/start")
@admin_required
def api_admin_start():
    db = get_db()
    minutes = (request.get_json(silent=True) or {}).get("minutes", ROUND_SECONDS / 60)
    try:
        duration = int(float(minutes) * 60)
    except (TypeError, ValueError):
        return jsonify(error="bad_duration"), 400
    duration = max(30, min(duration, 3600))
    with tx(db):
        if get_round(db)["status"] != "waiting":
            return jsonify(error="not_waiting"), 409
        if db.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 0:
            return jsonify(error="no_teams"), 409
        for key, value in (("status", "running"), ("duration", str(duration)),
                           ("started_at", repr(time.time())), ("ended_at", "")):
            db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
    return jsonify(ok=True)


@app.post("/api/admin/stop")
@admin_required
def api_admin_stop():
    db = get_db()
    with tx(db):
        if get_round(db)["status"] == "running":
            db.execute("UPDATE settings SET value='finished' WHERE key='status'")
            db.execute("UPDATE settings SET value=? WHERE key='ended_at'", (repr(time.time()),))
    return jsonify(ok=True)


@app.post("/api/admin/reset")
@admin_required
def api_admin_reset():
    db = get_db()
    clear_teams = bool((request.get_json(silent=True) or {}).get("clear_teams"))
    with tx(db):
        db.execute("DELETE FROM answers")
        if clear_teams:
            db.execute("DELETE FROM teams")
        db.execute("UPDATE settings SET value='waiting' WHERE key='status'")
        db.execute("UPDATE settings SET value=? WHERE key='duration'", (str(ROUND_SECONDS),))
        db.execute("UPDATE settings SET value='' WHERE key IN ('started_at','ended_at')")
    return jsonify(ok=True)


@app.get("/api/admin/team/<int:team_id>")
@admin_required
def api_admin_team(team_id):
    db = get_db()
    if db.execute("SELECT 1 FROM teams WHERE id=?", (team_id,)).fetchone() is None:
        abort(404)
    rows = []
    for r in db.execute(
            "SELECT a.seq, a.chosen_idx, a.is_correct, a.time_ms, a.points, a.answered_at, "
            "q.theme, q.difficulty, q.text_kn, q.text_en, q.options_json, q.correct_idx "
            "FROM answers a JOIN questions q ON q.id=a.question_id "
            "WHERE a.team_id=? ORDER BY a.seq", (team_id,)):
        options = json.loads(r["options_json"])
        rows.append({"seq": r["seq"], "theme": theme_info(r["theme"]), "difficulty": r["difficulty"],
                     "text_kn": r["text_kn"],
                     "text_en": r["text_en"], "answered": r["answered_at"] is not None,
                     "correct": bool(r["is_correct"]), "time_ms": r["time_ms"],
                     "points": r["points"],
                     "chosen": options[r["chosen_idx"]]["kn"] if r["chosen_idx"] is not None else None,
                     "answer": options[r["correct_idx"]]["kn"]})
    return jsonify(answers=rows)


def csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    # BOM so Excel renders Kannada text correctly
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.get("/admin/export/summary.csv")
@admin_required
def export_summary():
    teams = team_stats(get_db())
    rows = [[t["rank"], t["name"], t["members"], t["score"], t["answered"], t["correct"],
             t["answered"] - t["correct"], t["avg_ms"] if t["avg_ms"] is not None else "",
             t["total_time_ms"]] for t in teams]
    return csv_response("kr2026_leaderboard.csv",
                        ["Rank", "Team", "Members", "Score", "Answered", "Correct", "Wrong",
                         "Avg correct time (ms)", "Total time (ms)"], rows)


@app.get("/admin/export/answers.csv")
@admin_required
def export_answers():
    rows = []
    for r in get_db().execute(
            "SELECT t.name, a.seq, q.id AS qid, q.theme, q.difficulty, q.text_en, q.options_json, "
            "q.correct_idx, a.chosen_idx, a.is_correct, a.time_ms, a.points "
            "FROM answers a JOIN teams t ON t.id=a.team_id JOIN questions q ON q.id=a.question_id "
            "WHERE a.answered_at IS NOT NULL ORDER BY t.name COLLATE NOCASE, a.seq"):
        options = json.loads(r["options_json"])
        rows.append([r["name"], r["seq"], r["qid"], THEMES[r["theme"]][1],
                     DIFFICULTIES[r["difficulty"]][1], r["text_en"],
                     options[r["chosen_idx"]]["en"] or options[r["chosen_idx"]]["kn"],
                     options[r["correct_idx"]]["en"] or options[r["correct_idx"]]["kn"],
                     "Yes" if r["is_correct"] else "No", r["time_ms"], round(r["time_ms"] / 1000, 2),
                     r["points"]])
    return csv_response("kr2026_answers.csv",
                        ["Team", "Order", "Question ID", "Theme", "Difficulty", "Question", "Chosen",
                         "Correct answer", "Correct?", "Time (ms)", "Time (s)", "Points"], rows)


init_db()

if __name__ == "__main__":
    if "--reseed" in sys.argv:
        conn = connect()
        seed_questions(conn, replace=True)
        conn.close()
        print(f"Question bank reloaded ({len(QUESTIONS)} questions); previous answers cleared.")
        sys.exit(0)
    ip = lan_ip()
    print("=" * 60)
    print(" Kannada Rajyotsava 2026 - Fastest Finger First Quiz")
    print(f" QR screen    : http://{ip}:{PORT}/   (project this for participants)")
    print(f" Admin        : http://{ip}:{PORT}/admin   (password: {ADMIN_PASSWORD})")
    print(f" Registrations: http://{ip}:{PORT}/admin/registrations")
    print("=" * 60)
    app.run(host="0.0.0.0", port=PORT, threaded=True)
