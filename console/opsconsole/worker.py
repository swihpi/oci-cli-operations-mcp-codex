"""Privilege-separated JSON worker; no shell and no arbitrary CLI arguments.

On the VM, sudo runs this root-owned module as the credential-owning ociworker
account. The web account cannot read its key. One request per invocation.
"""
import json
import os
import subprocess
import sys
from .cli import CLI


class WorkerClient:
    def __init__(self, command):self.command=command
    def invoke(self, payload):
        try:
            result=subprocess.run(self.command,input=json.dumps(payload),text=True,capture_output=True,
                                  timeout=65,check=False)
            if result.returncode or len(result.stdout)>2_100_000:raise ValueError("Worker failure")
            return json.loads(result.stdout)
        except Exception:
            return {"ok":False,"error":"Isolated worker unavailable; inspect state before retrying", "uncertain":payload.get("kind")=="power"}
    def read(self, operation, parameters, region):
        return self.invoke({"kind":"read","operation":operation,"parameters":parameters,"region":region})
    def power(self,action,instance_id,region,etag):
        return self.invoke({"kind":"power","action":action,"instance_id":instance_id,"region":region,"etag":etag})
    def generic(self, command):
        return self.invoke({"kind":"generic","command":command})


def dispatch(payload, cli):
    if not isinstance(payload,dict):raise ValueError("Object required")
    if payload.get("kind")=="read" and set(payload)=={"kind","operation","parameters","region"}:
        return cli.read(payload["operation"],payload["parameters"],payload["region"])
    if payload.get("kind")=="power" and set(payload)=={"kind","action","instance_id","region","etag"}:
        if os.environ.get("CONSOLE_WORKER_WRITES")!="true":
            return {"ok":False,"error":"Worker writes disabled"}
        protected=os.environ.get("CONSOLE_PROTECTED_INSTANCES","").split(",")
        if payload["instance_id"] in protected:
            return {"ok":False,"error":"Protected instance"}
        return cli.power(payload["action"],payload["instance_id"],payload["region"],payload["etag"])
    if payload.get("kind")=="generic" and set(payload)=={"kind","command"}:
        if os.environ.get("CONSOLE_WORKER_WRITES")!="true":
            return {"ok":False,"error":"Worker writes disabled"}
        if any(protected and protected in payload["command"] for protected in os.environ.get("CONSOLE_PROTECTED_INSTANCES","").split(",")):
            return {"ok":False,"error":"Protected instance"}
        return cli.generic(payload["command"])
    raise ValueError("Unsupported worker request")


if __name__=='__main__':
    try:
        # Root/worker-readable environment is separate from the web configuration.
        from pathlib import Path
        path=Path('/etc/oci-operations-console/worker.json')
        settings=json.loads(path.read_text())
        os.environ['CONSOLE_WORKER_WRITES']='true' if settings.get('enable_writes') else 'false'
        os.environ['CONSOLE_PROTECTED_INSTANCES']=','.join(settings.get('protected_instances',[]))
        raw=sys.stdin.read(16385)
        if len(raw)>16384:raise ValueError("Request too large")
        result=dispatch(json.loads(raw),CLI('/opt/oci-operations-console/oci-venv/bin/oci'))
        print(json.dumps(result))
    except Exception:
        print(json.dumps({"ok":False,"error":"Worker rejected request"}))
        sys.exit(1)
