"""Append-only PostgreSQL record of reports, planned actions, and outcomes."""
import json
import time


class Archive:
    def __init__(self, dsn):
        if not dsn:
            raise RuntimeError("PostgreSQL archive DSN is required for a live console")
        try:
            import psycopg
            self.psycopg = psycopg
            self.dsn = dsn
            self._schema()
        except Exception as exc:
            raise RuntimeError("PostgreSQL archive is unavailable") from exc

    def _schema(self):
        with self.psycopg.connect(self.dsn) as db:
            with db.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS operation_audit (
                  id BIGSERIAL PRIMARY KEY, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  actor_hash TEXT NOT NULL, event_type TEXT NOT NULL,
                  job_id TEXT, approval_id TEXT, command_json JSONB,
                  details JSONB NOT NULL);
                CREATE INDEX IF NOT EXISTS operation_audit_recorded_idx ON operation_audit(recorded_at DESC);
                CREATE INDEX IF NOT EXISTS operation_audit_job_idx ON operation_audit(job_id);
                CREATE TABLE IF NOT EXISTS health_reports (
                  id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  report_id TEXT NOT NULL UNIQUE, report_json JSONB NOT NULL,
                  checksum TEXT NOT NULL, mode TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS health_reports_created_idx ON health_reports(created_at DESC);
                """)

    def audit(self, actor_hash, event_type, details, job_id=None, approval_id=None, command=None):
        with self.psycopg.connect(self.dsn) as db:
            with db.cursor() as cur:
                cur.execute("""INSERT INTO operation_audit
                  (actor_hash,event_type,job_id,approval_id,command_json,details)
                  VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                  (actor_hash,event_type,job_id,approval_id,json.dumps(command) if command else None,json.dumps(details)))

    def report(self, report_id, report, checksum):
        with self.psycopg.connect(self.dsn) as db:
            with db.cursor() as cur:
                cur.execute("""INSERT INTO health_reports(report_id,report_json,checksum,mode)
                  VALUES (%s,%s::jsonb,%s,%s) ON CONFLICT (report_id) DO NOTHING""",
                  (report_id,json.dumps(report),checksum,report.get("mode","unknown")))

    def recent_reports(self):
        with self.psycopg.connect(self.dsn) as db:
            with db.cursor() as cur:
                cur.execute("SELECT report_id,created_at,checksum,mode FROM health_reports ORDER BY created_at DESC LIMIT 100")
                return [{"report_id":r[0],"created_at":r[1].timestamp(),"checksum":r[2],"mode":r[3]} for r in cur.fetchall()]


class NullArchive:
    """Test/demo adapter. Never used by a live deployment."""
    def __init__(self): self.audits=[];self.reports=[]
    def audit(self,*args,**kwargs): self.audits.append((args,kwargs))
    def report(self,*args,**kwargs): self.reports.append((args,kwargs))
    def recent_reports(self): return []
