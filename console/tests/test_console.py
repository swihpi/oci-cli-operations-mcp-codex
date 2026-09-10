import concurrent.futures
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from opsconsole.app import create_app
from opsconsole.cli import CLI, InvalidOperation, power_arguments, read_arguments, redact
from opsconsole.docs import Docs, Redirect, allowed
from opsconsole.health import Scanner, evaluate, difference
from opsconsole.store import Store
from opsconsole.worker import dispatch
from opsconsole.archive import NullArchive

TENANCY = "ocid"+"1.tenancy.oc1..exampletesttenancy"
INSTANCE="ocid"+"1.instance.oc1.eu-frankfurt-1.exampleinstance"
REGION="eu-frankfurt-1"
ORIGIN="http://localhost"
PASSWORD="test-password-never-used-live"


class FakeCLI:
    def __init__(self):
        self.power_calls=[]
        self.state="RUNNING"
        self.etag="etag-1"
        self.empty_compartments=False
        self.fail_power=False
    def read(self,operation,parameters,region):
        if operation=="regions": rows=[{"region-name":REGION,"status":"READY"}]
        elif operation=="compartments":
            if self.empty_compartments:return {"ok":False,"error":"Empty CLI output"}
            rows=[]
        elif operation in {"instance","instances"}:
            rows={"id":INSTANCE,"display-name":"test-instance","lifecycle-state":self.state,"compartment-id":TENANCY}
            if operation=="instances":rows=[rows]
        elif operation=="cloud_guard":rows={"status":"ENABLED"}
        else:rows=[]
        return {"ok":True,"data":{"data":rows,"etag":self.etag},"observed_at":time.time()}
    def power(self,action,instance_id,region,etag):
        self.power_calls.append((action,instance_id,region,etag))
        if self.fail_power:return {"ok":False,"uncertain":True,"error":"timeout"}
        self.state="STOPPED" if action=="SOFTSTOP" else "RUNNING"
        return {"ok":True,"data":{"data":{"lifecycle-state":self.state}}}
    def generic(self,command):
        return {"ok":True,"data":{"data":{"command":command}}}


class ConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.password_hash=generate_password_hash(PASSWORD)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cli=FakeCLI()
        self.app=create_app({"TESTING":True,"MODE":"live","TENANCY":TENANCY,"REGION":REGION,
                            "DATABASE":str(Path(self.temp.name)/"state.db"),"PASSWORD_HASH":self.password_hash,
                            "ALLOWED_ORIGIN":ORIGIN,"SECURE_COOKIE":False,"ENABLE_WRITES":True},self.cli,NullArchive())
        self.client=self.app.test_client()
        self.store=self.app.extensions["ops_store"]
        self.store.set("snapshot",Scanner(self.cli,TENANCY,REGION).scan())
        self.csrf=self.login(self.client)
    def tearDown(self):
        self.app.extensions["ops_pool"].shutdown(wait=True)
        self.temp.cleanup()
    def login(self,client):
        response=client.post('/api/login',json={"password":PASSWORD},headers={"Origin":ORIGIN})
        self.assertEqual(response.status_code,200)
        return response.json["csrf"]
    def post(self,path,data=None,client=None,csrf=None):
        return (client or self.client).post(path,json=data or {},headers={"Origin":ORIGIN,"X-CSRF-Token":csrf or self.csrf})
    def plan(self):
        response=self.post('/api/actions/plan',{"action":"SOFTSTOP","instance_id":INSTANCE,"region":REGION})
        self.assertEqual(response.status_code,200,response.json)
        return response.json
    def finish(self,job_id):
        for _ in range(100):
            job=next(j for j in self.store.jobs() if j["id"]==job_id)
            if job["status"] not in {"queued","running"}:return job
            time.sleep(.01)
        self.fail("Job did not finish")
    def test_authentication_required(self):
        client=self.app.test_client()
        self.assertEqual(client.get('/api/snapshot').status_code,401)
        with client.get('/') as response:self.assertEqual(response.status_code,200)
    def test_cookie_and_security_headers(self):
        response=self.client.get('/api/session')
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        response=self.client.post('/api/login',json={"password":PASSWORD},headers={"Origin":ORIGIN})
        self.assertIn('HttpOnly',response.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict',response.headers['Set-Cookie'])
    def test_cross_origin_and_csrf_rejected(self):
        self.assertEqual(self.client.post('/api/scans',json={},headers={"Origin":"https://evil.example"}).status_code,403)
        self.assertEqual(self.client.post('/api/scans',json={},headers={"Origin":ORIGIN}).status_code,403)
    def test_dns_rebinding_host_rejected(self):
        self.assertEqual(self.client.get('/healthz',headers={"Host":"evil.example"}).status_code,400)
    def test_request_size_limit(self):
        self.assertEqual(self.post('/api/investigate',{"question":"x"*20000}).status_code,413)
    def test_unknown_request_fields_rejected(self):
        self.assertEqual(self.post('/api/scans',{"command":"rm"}).status_code,400)
    def test_plan_never_executes(self):
        plan=self.plan()
        self.assertIn('--if-match',plan['command'])
        self.assertEqual(self.cli.power_calls,[])
    def test_mutation_is_verified_and_approval_not_replayed(self):
        plan=self.plan()
        response=self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"})
        self.assertEqual(response.status_code,202,response.json)
        self.assertEqual(self.finish(response.json['job_id'])['status'],'verified')
        self.assertEqual(len(self.cli.power_calls),1)
        self.assertEqual(self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"}).status_code,400)
    def test_approval_bound_to_session(self):
        plan=self.plan()
        other=self.app.test_client();csrf=self.login(other)
        self.assertEqual(self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"},other,csrf).status_code,400)
        self.assertFalse(self.cli.power_calls)
    def test_expired_approval_rejected(self):
        plan=self.plan()
        with self.store.connect() as db:db.execute('UPDATE approvals SET expires=0')
        self.assertEqual(self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"}).status_code,400)
    def test_changed_resource_rejected(self):
        plan=self.plan();self.cli.etag='changed'
        response=self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"})
        self.assertEqual(self.finish(response.json['job_id'])['status'],'rejected')
        self.assertFalse(self.cli.power_calls)
    def test_write_disable_is_server_enforced(self):
        plan=self.plan();self.app.config['ENABLE_WRITES']=False
        self.assertEqual(self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"}).status_code,403)
        self.assertFalse(self.cli.power_calls)
    def test_protected_host_rejected(self):
        self.app.config['PROTECTED_INSTANCES']=[INSTANCE]
        self.assertEqual(self.post('/api/actions/plan',{"action":"SOFTSTOP","instance_id":INSTANCE,"region":REGION}).status_code,400)
    def test_arbitrary_and_destructive_actions_rejected(self):
        self.assertEqual(self.post('/api/actions/plan',{"action":"DELETE","instance_id":INSTANCE,"region":REGION}).status_code,400)
    def test_generic_command_is_planned_then_approval_gated(self):
        response=self.post('/api/actions/generic-plan',{"command":"oci iam region-subscription list --region eu-frankfurt-1"})
        self.assertEqual(response.status_code,200,response.json)
        self.assertIn('iam',response.json['arguments'])
        self.assertFalse(self.cli.power_calls)
    def test_generic_command_executes_only_after_approval_and_stays_unverified(self):
        plan=self.post('/api/actions/generic-plan',{"command":"oci iam region-subscription list --region eu-frankfurt-1"}).json
        response=self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"})
        self.assertEqual(response.status_code,202,response.json)
        self.assertEqual(self.finish(response.json['job_id'])['status'],'submitted_unverified')
    def test_generic_command_blocks_credential_and_shell_indirection(self):
        for command in ["oci iam region list --profile evil", "oci iam region list --from-json file:///etc/passwd", "oci iam region list bad\ninput"]:
            self.assertEqual(self.post('/api/actions/generic-plan',{"command":command}).status_code,400)
    def test_timeout_is_uncertain_not_success(self):
        plan=self.plan();self.cli.fail_power=True
        response=self.post('/api/actions/execute',{"approval_id":plan['approval_id'],"confirmation":"EXECUTE"})
        self.assertEqual(self.finish(response.json['job_id'])['status'],'uncertain')
    def test_stale_snapshot_rejected(self):
        snapshot=self.store.get('snapshot');snapshot['completed_at']=0;self.store.set('snapshot',snapshot)
        self.assertEqual(self.post('/api/actions/plan',{"action":"START","instance_id":INSTANCE,"region":REGION}).status_code,400)
    def test_logout_revokes_session(self):
        self.assertEqual(self.post('/api/logout').status_code,200)
        self.assertEqual(self.client.get('/api/snapshot').status_code,401)
    def test_schedule_never_silently_enables_without_worker(self):
        self.assertEqual(self.post('/api/schedule',{"enabled":True,"hours":24}).status_code,400)
        self.assertEqual(self.post('/api/schedule',{"enabled":False,"hours":24}).status_code,200)
    def test_scan_jobs_complete(self):
        response=self.post('/api/scans')
        self.assertEqual(response.status_code,202)
        self.assertEqual(self.finish(response.json['job_id'])['status'],'completed')
        self.assertEqual(len(self.app.extensions['ops_archive'].reports),1)
    def test_docs_failure_is_explicit_and_does_not_invent_diagnosis(self):
        with patch.object(self.app.extensions['ops_docs'],'fetch',return_value={"ok":False,"error":"unavailable"}):
            response=self.post('/api/investigate',{"question":"Review network health"})
        self.assertEqual(response.json['mode'],'evidence_routing')
        self.assertFalse(response.json['source']['ok'])
        self.assertFalse(response.json['actions_executed'])
    def test_restart_marks_inflight_jobs_interrupted(self):
        job=self.store.create_job('mutation');self.store.recover_jobs()
        self.assertEqual(next(j for j in self.store.jobs() if j['id']==job)['status'],'interrupted')


class UnitTests(unittest.TestCase):
    def test_worker_rejects_arbitrary_command(self):
        with self.assertRaises(ValueError):dispatch({'kind':'shell','command':'whoami'},FakeCLI())
    def test_worker_independently_disables_writes(self):
        cli=FakeCLI()
        with patch.dict(os.environ,{'CONSOLE_WORKER_WRITES':'false'}):
            result=dispatch({'kind':'power','action':'START','instance_id':INSTANCE,'region':REGION,'etag':'v1'},cli)
        self.assertFalse(result['ok']);self.assertFalse(cli.power_calls)
    def test_worker_protects_console_instance(self):
        cli=FakeCLI()
        with patch.dict(os.environ,{'CONSOLE_WORKER_WRITES':'true','CONSOLE_PROTECTED_INSTANCES':INSTANCE}):
            result=dispatch({'kind':'power','action':'SOFTSTOP','instance_id':INSTANCE,'region':REGION,'etag':'v1'},cli)
        self.assertFalse(result['ok']);self.assertFalse(cli.power_calls)
    def test_empty_fallback_requires_explicit_empty_json(self):
        cli=CLI()
        with patch.object(cli,'_run',side_effect=[{'ok':False,'error':'Empty CLI output; coverage unknown'},{'ok':True,'data':{'data':[]}}]):
            self.assertTrue(cli.read('instances',{'compartment-id':TENANCY},REGION)['empty_confirmed'])
        with patch.object(cli,'_run',side_effect=[{'ok':False,'error':'Empty CLI output; coverage unknown'},{'ok':True,'data':{'data':[{'id':'not-empty'}]}}]):
            self.assertFalse(cli.read('instances',{'compartment-id':TENANCY},REGION)['ok'])
    def test_no_arbitrary_flags_or_shell(self):
        for params in [{"compartment-id":TENANCY,"--endpoint":"evil"},{"compartment-id":"$(whoami)"}]:
            with self.assertRaises(InvalidOperation):read_arguments('instances',params,REGION)
        with self.assertRaises(InvalidOperation):read_arguments('delete',{},REGION)
    def test_list_vnics_is_validated_read(self):
        self.assertEqual(read_arguments('vnics',{'instance-id':INSTANCE},REGION)[:3],['compute','instance','list-vnics'])
    def test_power_rejects_injection(self):
        with self.assertRaises(InvalidOperation):power_arguments('START',INSTANCE,REGION,'x\n--debug')
    def test_sensitive_output_redacted(self):
        self.assertEqual(redact({'metadata':{'ssh_authorized_keys':'example'},'security-token':'example'})['metadata'],'[REDACTED]')
    def test_empty_compartment_output_stays_unknown(self):
        cli=FakeCLI();cli.empty_compartments=True
        snapshot=Scanner(cli,TENANCY,REGION).scan()
        self.assertTrue(snapshot['coverage_gaps'])
        self.assertEqual(snapshot['compartment_count'],1)
    def test_failed_check_is_not_healthy(self):
        self.assertEqual(evaluate('security_lists',{'ok':False,'error':'denied'},'scope')[0]['status'],'check_failed')
    def test_missing_nsg_is_not_automatically_unsafe(self):
        self.assertEqual(evaluate('nsgs',{'ok':True,'data':{'data':[]}},'scope'),[])
    def test_disappearance_not_called_resolved(self):
        result=difference({'findings':[{'id':'a'}]},{'findings':[]})
        self.assertEqual(result['not_observed'],['a'])
        self.assertNotIn('resolved',result)
    def test_docs_host_allowlist(self):
        for url in ['http://docs.oracle.com/','https://docs.oracle.com.evil.example/','https://user@docs.oracle.com/','https://127.0.0.1/']:
            self.assertFalse(allowed(url))
        self.assertTrue(allowed('https://docs.oracle.com/en-us/iaas/Content/home.htm'))
    def test_atomic_approval_consumption(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'state.db');plan=store.plan('session',{'action':'START'})
            def consume(_):
                try:store.consume(plan['approval_id'],'session');return True
                except ValueError:return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(consume,range(4)))
            self.assertEqual(sum(results),1)


if __name__=='__main__':unittest.main()
