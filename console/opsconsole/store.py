"""SQLite state: opaque sessions and atomic approval consumption."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals (
                  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL,
                  expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                  created REAL NOT NULL, result TEXT);
                CREATE TABLE IF NOT EXISTS events (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                  actor TEXT NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        Path(path).chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self):
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (digest(sid), csrf, time.time()+3600))
        return sid, csrf

    def authenticate(self, sid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND expires>?", (digest(sid), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, sid):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (digest(sid),))
            db.execute("DELETE FROM approvals WHERE session_id=?", (digest(sid),))

    def plan(self, session_id, payload):
        plan_id = secrets.token_urlsafe(24)
        expires = time.time()+300
        with self.connect() as db:
            db.execute("DELETE FROM approvals WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO approvals VALUES (?,?,?,?,0)", (plan_id, session_id, json.dumps(payload), expires))
        return dict(payload, approval_id=plan_id, expires_at=expires)

    def consume(self, plan_id, session_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM approvals WHERE id=? AND session_id=? AND consumed=0 AND expires>?",
                             (plan_id, session_id, time.time())).fetchone()
            if not row:
                raise ValueError("Approval expired, already used, or belongs to another session")
            db.execute("UPDATE approvals SET consumed=1 WHERE id=?", (plan_id,))
            return json.loads(row["payload"])

    def event(self, actor, kind, details):
        with self.connect() as db:
            db.execute("INSERT INTO events(at,actor,kind,details) VALUES (?,?,?,?)",
                       (time.time(), actor[:16], kind, json.dumps(details)))

    def events(self):
        with self.connect() as db:
            return [dict(row, details=json.loads(row["details"])) for row in db.execute(
                "SELECT * FROM events ORDER BY sequence DESC LIMIT 200")]

    def create_job(self, kind):
        job_id = secrets.token_urlsafe(18)
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,NULL)", (job_id, kind, "queued", time.time()))
        return job_id

    def finish_job(self, job_id, status, result=None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?, result=? WHERE id=?", (status, json.dumps(result), job_id))

    def jobs(self):
        with self.connect() as db:
            return [dict(row, result=json.loads(row["result"]) if row["result"] else None)
                    for row in db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 30")]

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))

    def recover_jobs(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='interrupted', result=? WHERE status IN ('queued','running')",
                       (json.dumps({"error": "Service restarted; do not retry mutations without checking state"}),))
