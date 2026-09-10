"""Single-process private application. Use one gthread worker (see deploy notes)."""
import hmac
import hashlib
import json
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash

from .cli import CLI, InvalidOperation, identifier, power_arguments, region_name
from .demo import snapshot as demo_snapshot
from .docs import Docs, SOURCES, topic_for
from .health import Scanner, data_of, difference
from .store import Store
from .worker import WorkerClient
from .archive import Archive, NullArchive


def create_app(config=None, cli=None, archive=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(
        MODE=os.environ.get("CONSOLE_MODE","demo"),
        DATABASE=os.environ.get("CONSOLE_DATABASE",str(Path.home()/".local/state/oci-console/console.db")),
        PASSWORD_HASH=os.environ.get("CONSOLE_PASSWORD_HASH",""),
        TENANCY = os.environ.get("CONSOLE_TENANCY",""),
        REGION=os.environ.get("CONSOLE_REGION","eu-frankfurt-1"),
        ENABLE_WRITES=os.environ.get("CONSOLE_ENABLE_WRITES","false")=="true",
        PROTECTED_INSTANCES=os.environ.get("CONSOLE_PROTECTED_INSTANCES","").split(","),
        ALLOWED_ORIGIN=os.environ.get("CONSOLE_ORIGIN","http://127.0.0.1:8765"),
        SECURE_COOKIE=os.environ.get("CONSOLE_SECURE_COOKIE","true")=="true",
        MAX_CONTENT_LENGTH=16384, TESTING=False,
        START_SCHEDULER=os.environ.get("CONSOLE_START_SCHEDULER","false")=="true",
        ARCHIVE_DSN=os.environ.get("CONSOLE_ARCHIVE_DSN",""),
    )
    if config: app.config.update(config)
    if not app.config["PASSWORD_HASH"]:
        raise RuntimeError("Set CONSOLE_PASSWORD_HASH using the password setup command")
    if app.config["MODE"] not in {"demo","live"}: raise ValueError("Invalid mode")
    if app.config["MODE"] == "live":
        identifier(app.config["TENANCY"])
        region_name(app.config["REGION"])
    store = Store(app.config["DATABASE"])
    store.recover_jobs()
    if archive is None:
        archive = Archive(app.config["ARCHIVE_DSN"]) if app.config["MODE"] == "live" else NullArchive()
    if cli is None and os.environ.get("CONSOLE_ISOLATED_WORKER")=="true":
        cli=WorkerClient(["sudo","-n","-H","-u","ociworker","/opt/oci-operations-console/venv/bin/python","-m","opsconsole.worker"])
    cli = cli or CLI(os.environ.get("OCI_CLI_BINARY","oci"),os.environ.get("OCI_CLI_PROFILE","DEFAULT"),os.environ.get("CONSOLE_OCI_AUTH","api_key"))
    docs = Docs(store)
    pool = ThreadPoolExecutor(max_workers=2,thread_name_prefix="oci-console")
    scan_lock, mutation_lock, login_lock = threading.Lock(),threading.Lock(),threading.Lock()
    login_attempts = []
    app.extensions.update(ops_store=store,ops_cli=cli,ops_pool=pool,ops_docs=docs,ops_archive=archive)
    if app.config["MODE"] == "demo" and store.get("snapshot") is None:
        store.set("snapshot",demo_snapshot())

    @app.before_request
    def protect():
        # Host/Origin checks also protect localhost deployments from DNS rebinding.
        if request.host_url.rstrip("/") != app.config["ALLOWED_ORIGIN"]:
            abort(400,description="Unexpected origin; configure the exact private URL")
        if request.path in {"/","/healthz"} or request.path.startswith("/static/"):
            return
        if request.method not in {"GET","HEAD","OPTIONS"}:
            if request.headers.get("Origin") != app.config["ALLOWED_ORIGIN"]:
                abort(403,description="Origin check failed")
            if not request.is_json: abort(415,description="JSON body required")
        if request.path == "/api/login": return
        g.identity = store.authenticate(request.cookies.get("ops_session",""))
        if not g.identity: abort(401,description="Sign in required")
        if request.method not in {"GET","HEAD","OPTIONS"}:
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token",""),g.identity["csrf"]):
                abort(403,description="CSRF check failed")

    @app.after_request
    def headers(response):
        response.headers.update({
            "Cache-Control":"no-store", "X-Content-Type-Options":"nosniff",
            "Referrer-Policy":"no-referrer", "X-Frame-Options":"DENY",
            "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "Permissions-Policy":"camera=(), microphone=(), geolocation=()",
        })
        if app.config["SECURE_COOKIE"]:
            response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    @app.errorhandler(InvalidOperation)
    def invalid(error): return jsonify(error=str(error)),400

    @app.errorhandler(ValueError)
    def value_error(error): return jsonify(error=str(error)),400

    from werkzeug.exceptions import HTTPException
    @app.errorhandler(HTTPException)
    def http_error(error): return jsonify(error=error.description),error.code

    @app.get("/")
    def index(): return send_from_directory(app.static_folder,"index.html")

    @app.get("/healthz")
    def healthz(): return {"ok":True,"service":"oci-operations-console"}

    def body(fields):
        data = request.get_json()
        if not isinstance(data,dict) or set(data)-set(fields): raise ValueError("Unexpected request fields")
        return data

    def archive_audit(actor, event_type, details, **identifiers):
        """Persist consequential evidence before an OCI mutation can be submitted."""
        archive.audit(actor, event_type, details, **identifiers)

    @app.post("/api/login")
    def login():
        data = body({"password"})
        password = data.get("password","")
        if not isinstance(password,str) or len(password)>256: abort(400)
        with login_lock:
            now = time.time()
            login_attempts[:] = [t for t in login_attempts if t>now-300]
            if len(login_attempts)>=8: abort(429,description="Too many login attempts; wait five minutes")
            login_attempts.append(now)
        if not check_password_hash(app.config["PASSWORD_HASH"],password):
            store.event("anonymous","login_failed",{})
            abort(401,description="Invalid password")
        store.logout(request.cookies.get("ops_session",""))
        sid,csrf = store.session()
        store.event("admin","login",{})
        response = jsonify(csrf=csrf)
        response.set_cookie("ops_session",sid,httponly=True,secure=app.config["SECURE_COOKIE"],samesite="Strict",max_age=3600,path="/")
        return response

    @app.post("/api/logout")
    def logout():
        store.logout(request.cookies.get("ops_session",""))
        response = jsonify(ok=True)
        response.delete_cookie("ops_session",path="/")
        return response

    @app.get("/api/session")
    def session():
        return {"csrf":g.identity["csrf"],"mode":app.config["MODE"],"writes_enabled":app.config["ENABLE_WRITES"],
                "ai_enabled":False,"region":app.config["REGION"],"sources":{k:{"title":v[0],"url":v[1]} for k,v in SOURCES.items()}}

    @app.get("/api/snapshot")
    def snapshot():
        result = store.get("snapshot")
        if result and result.get("mode") != app.config["MODE"]: result=None
        return {"snapshot":result}

    def enqueue_scan(actor):
        if not scan_lock.acquire(blocking=False): raise ValueError("A scan is already running")
        job_id = store.create_job("scan")
        store.event(actor,"scan_requested",{"job_id":job_id})
        def run():
            try:
                store.finish_job(job_id,"running")
                previous = store.get("snapshot")
                result = demo_snapshot() if app.config["MODE"] == "demo" else Scanner(cli,app.config["TENANCY"],app.config["REGION"]).scan()
                result["difference"] = difference(previous,result)
                store.set("snapshot",result)
                report_id = secrets.token_urlsafe(18)
                checksum = hashlib.sha256(json.dumps(result,sort_keys=True,separators=(",",":")).encode()).hexdigest()
                archive.report(report_id,result,checksum)
                store.finish_job(job_id,"completed",{"findings":len(result["findings"]),"coverage_gaps":result["coverage_gaps"]})
                event = {"job_id":job_id,"report_id":report_id,"checksum":checksum,"difference":result["difference"]}
                store.event(actor,"scan_completed",event)
                archive_audit(actor,"scan_completed",event,job_id=job_id)
            except Exception:
                store.finish_job(job_id,"failed",{"error":"Scan failed; previous snapshot retained"})
            finally: scan_lock.release()
        pool.submit(run)
        return job_id

    @app.post("/api/scans")
    def scans():
        body(set())
        return {"job_id":enqueue_scan(g.identity["id"])},202

    @app.get("/api/jobs")
    def jobs(): return {"jobs":store.jobs()}

    @app.get("/api/events")
    def events(): return {"events":store.events()}

    @app.get("/api/reports")
    def reports(): return {"reports":archive.recent_reports()}

    @app.get("/api/schedule")
    def schedule():
        return dict(store.get("schedule",{"enabled":False,"hours":24,"next_run":None}),worker_enabled=app.config["START_SCHEDULER"])

    @app.post("/api/schedule")
    def set_schedule():
        data=body({"enabled","hours"})
        if type(data.get("enabled")) is not bool or type(data.get("hours")) is not int or not 1<=data["hours"]<=168:
            raise ValueError("Schedule requires a boolean enabled and interval of 1–168 hours")
        if data["enabled"] and not app.config["START_SCHEDULER"]:
            raise ValueError("Scheduler worker is disabled in this deployment")
        value=dict(data,next_run=time.time()+data["hours"]*3600 if data["enabled"] else None)
        store.set("schedule",value)
        store.event(g.identity["id"],"schedule_changed",value)
        return value

    @app.post("/api/investigate")
    def investigate():
        data=body({"question"})
        question=data.get("question","")
        if not isinstance(question,str) or not 3<=len(question)<=1500: raise ValueError("Enter a question of 3–1500 characters")
        topic=topic_for(question)
        snapshot=store.get("snapshot") or {}
        relevant=[f for f in snapshot.get("findings",[]) if f.get("docs_topic")==topic]
        source=docs.fetch(topic)
        # No LLM credentials are assumed. This is explicit evidence routing, not
        # an invented AI diagnosis or assertion that retrieved text was interpreted.
        source.pop("text",None)
        return {"mode":"evidence_routing","question":question,"topic":topic,"findings":relevant,
                "source":source,"snapshot_at":snapshot.get("completed_at"),
                "explanation":"Related observations and official documentation. Model-backed diagnosis is not configured; no cause or remediation is asserted.",
                "actions_executed":False}

    def permitted_resource(resource_id,region):
        identifier(resource_id);region_name(region)
        snapshot=store.get("snapshot") or {}
        if snapshot.get("mode")!="live" or time.time()-snapshot.get("completed_at",0)>1800:
            raise ValueError("Run a fresh live scan before planning resource changes")
        matches=[r for r in snapshot.get("resources",[]) if r["id"]==resource_id and r["kind"]=="instances" and r["region"]==region]
        if not matches: raise ValueError("Resource is outside the discovered scope")
        if resource_id in app.config["PROTECTED_INSTANCES"]:
            raise ValueError("This instance is protected from console lifecycle actions")
        return matches[0]

    @app.post("/api/actions/plan")
    def plan():
        data=body({"action","instance_id","region"})
        action=data.get("action")
        if action not in {"START","SOFTSTOP","SOFTRESET"}: raise ValueError("Unsupported action")
        if app.config["MODE"]!="live": raise ValueError("Demo mode cannot plan real OCI changes")
        resource=permitted_resource(data.get("instance_id"),data.get("region"))
        result=cli.read("instance",{"instance-id":resource["id"]},resource["region"])
        live=data_of(result)
        if not isinstance(live,dict): raise ValueError("Live precondition lookup failed")
        etag=result["data"].get("etag")
        command=power_arguments(action,resource["id"],resource["region"],etag)
        expected="STOPPED" if action=="START" else "RUNNING"
        if live.get("lifecycle-state")!=expected: raise ValueError("Resource state does not permit this action")
        if live.get("compartment-id")!=resource["compartment"]: raise ValueError("Resource scope changed; scan again")
        impact="Starts compute and can increase compute charges." if action=="START" else "Interrupts applications and connections; graceful shutdown can still cause data loss. Storage charges continue."
        payload={"action":action,"instance_id":resource["id"],"region":resource["region"],"name":resource["name"],
                 "compartment":resource["compartment"],"etag":etag,"before":expected,"command":["oci",*command],"impact":impact}
        planned=store.plan(g.identity["id"],payload)
        store.event(g.identity["id"],"action_planned",payload)
        archive_audit(g.identity["id"],"action_planned",payload,approval_id=planned["approval_id"],command=payload["command"])
        return dict(planned,execution_enabled=app.config["ENABLE_WRITES"])

    @app.post("/api/actions/generic-plan")
    def generic_plan():
        from .cli import generic_arguments
        data = body({"command"})
        if app.config["MODE"] != "live":
            raise ValueError("Demo mode cannot plan real OCI commands")
        arguments = generic_arguments(data.get("command"))
        if any(item in app.config["PROTECTED_INSTANCES"] for item in arguments):
            raise ValueError("This command targets the protected console host")
        payload = {"kind":"generic","command":data["command"],"arguments":arguments,
                   "impact":"Generic OCI CLI execution can create, change, expose, stop, delete or incur cost. Review every argument and OCI effect before approval.",
                   "scope":"No automatic scope inference; this is an administrator-level command."}
        planned = store.plan(g.identity["id"],payload)
        store.event(g.identity["id"],"generic_action_planned",payload)
        archive_audit(g.identity["id"],"generic_action_planned",payload,approval_id=planned["approval_id"],command=["oci",*arguments])
        return dict(planned,execution_enabled=app.config["ENABLE_WRITES"])

    @app.post("/api/actions/execute")
    def execute():
        data=body({"approval_id","confirmation"})
        if not app.config["ENABLE_WRITES"] or app.config["MODE"]!="live": abort(403,description="Live writes are disabled")
        if data.get("confirmation")!="EXECUTE": raise ValueError("Type EXECUTE to confirm the exact planned operation")
        if not isinstance(data.get("approval_id"),str): raise ValueError("Approval ID required")
        if not mutation_lock.acquire(blocking=False): raise ValueError("Another mutation is in progress")
        try:
            payload=store.consume(data["approval_id"],g.identity["id"])
            if payload.get("kind") != "generic":
                permitted_resource(payload["instance_id"],payload["region"])
            actor=g.identity["id"]
            job_id=store.create_job("generic_mutation" if payload.get("kind")=="generic" else "mutation")
            store.event(actor,"action_approved",{"job_id":job_id,**payload})
            archive_audit(actor,"action_approved",payload,job_id=job_id,approval_id=data["approval_id"],command=payload.get("command"))
            def run():
                try:
                    store.finish_job(job_id,"running")
                    if payload.get("kind") == "generic":
                        result=cli.generic(payload["command"])
                        # Generic OCI operations may be asynchronous or change unknown resource types.
                        # Never label a successful CLI return as verified without a service-specific read.
                        status="submitted_unverified" if result.get("ok") else "uncertain" if result.get("uncertain") else "failed"
                        outcome={"execution":result,"verification":{"ok":False,"error":"No generic verification contract"}}
                        store.finish_job(job_id,status,outcome)
                        archive_audit(actor,"generic_action_result",{"status":status,**outcome},job_id=job_id,command=["oci",*payload["arguments"]])
                        return
                    current=cli.read("instance",{"instance-id":payload["instance_id"]},payload["region"])
                    live=data_of(current)
                    if not isinstance(live,dict) or current["data"].get("etag")!=payload["etag"] or live.get("lifecycle-state")!=payload["before"] or live.get("compartment-id")!=payload["compartment"]:
                        store.finish_job(job_id,"rejected",{"error":"Resource changed after approval; create a new plan"})
                        return
                    result=cli.power(payload["action"],payload["instance_id"],payload["region"],payload["etag"])
                    verification=cli.read("instance",{"instance-id":payload["instance_id"]},payload["region"])
                    after=data_of(verification)
                    target="STOPPED" if payload["action"]=="SOFTSTOP" else "RUNNING"
                    # A single RUNNING read cannot prove that a reboot completed.
                    verified=result.get("ok") and isinstance(after,dict) and after.get("lifecycle-state")==target and payload["action"]!="SOFTRESET"
                    status="verified" if verified else "submitted_unverified" if result.get("ok") else "uncertain" if result.get("uncertain") else "failed"
                    store.finish_job(job_id,status,{"execution":result,"verification":verification,"target_state":target})
                    store.event(actor,"action_result",{"job_id":job_id,"status":status})
                    archive_audit(actor,"action_result",{"status":status,"execution":result,"verification":verification},job_id=job_id,command=payload["command"])
                except Exception:
                    store.finish_job(job_id,"uncertain",{"error":"Worker failed; inspect resource state before retrying"})
                    try: archive_audit(actor,"action_result",{"status":"uncertain","error":"Worker failed; inspect resource state before retrying"},job_id=job_id,command=payload.get("command"))
                    except Exception: pass
                finally: mutation_lock.release()
            pool.submit(run)
        except Exception:
            mutation_lock.release()
            raise
        return {"job_id":job_id},202

    if app.config["START_SCHEDULER"]:
        def tick():
            while True:
                time.sleep(30)
                schedule=store.get("schedule",{})
                if schedule.get("enabled") and (schedule.get("next_run") or float("inf"))<=time.time():
                    try:
                        enqueue_scan("scheduler")
                        schedule["next_run"]=time.time()+schedule["hours"]*3600
                        store.set("schedule",schedule)
                    except ValueError: pass
        threading.Thread(target=tick,daemon=True,name="read-only-scheduler").start()
    return app
