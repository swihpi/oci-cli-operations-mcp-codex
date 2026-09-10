"""Evidence-driven, deterministic checks. Missing evidence never means healthy."""
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

DOMAIN_OPERATIONS = {
    "Compute": ("instances",),
    "Networking": ("vcns", "subnets", "security_lists", "nsgs", "routes"),
    "Security": ("cloud_guard", "log_groups"),
    "Identity": ("policies", "users"),
    "Storage & recovery": ("volumes", "backups", "boot_backups", "databases"),
    "Cost": ("budgets",),
    "Observability": ("alarms",),
}


def data_of(result):
    if not result.get("ok"):
        return None
    payload = result.get("data")
    return payload.get("data") if isinstance(payload, dict) else None


def finding(domain, title, status, evidence, scope, resource=None, docs=None, severity="information"):
    key = "|".join([domain, title, scope, resource or ""])
    return {"id": hashlib.sha256(key.encode()).hexdigest()[:20], "domain": domain,
            "title": title, "status": status, "severity": severity, "evidence": evidence,
            "scope": scope, "resource_id": resource, "docs_topic": docs,
            "observed_at": time.time()}


def evaluate(operation, result, scope):
    domain = next((d for d, ops in DOMAIN_OPERATIONS.items() if operation in ops), "Coverage")
    rows = data_of(result)
    if rows is None or not isinstance(rows, (list, dict)):
        return [finding(domain, operation.replace("_", " ")+" observation failed", "check_failed",
                        result.get("error", "Missing structured data"), scope)]
    findings = []
    if operation == "cloud_guard":
        enabled = rows.get("status") == "ENABLED" if isinstance(rows, dict) else False
        findings.append(finding(domain, "Cloud Guard configuration", "healthy" if enabled else "unknown",
                                "Enabled; target/recipe coverage still requires review" if enabled else
                                "Not confirmed enabled; verify status and monitoring region", scope, docs="security"))
    if not isinstance(rows, list):
        return findings
    for item in rows:
        rid = item.get("id")
        if operation == "security_lists":
            for rule in item.get("ingress-security-rules", []):
                if rule.get("source") in {"0.0.0.0/0", "::/0"}:
                    tcp = (rule.get("tcp-options") or {}).get("destination-port-range")
                    protocol = rule.get("protocol")
                    detail = f"Source {rule['source']}; protocol {protocol}; TCP destination {tcp or 'any/not specified'}"
                    findings.append(finding(domain, "Internet-sourced ingress requires intent review", "unhealthy",
                        detail+". Configuration permission alone does not prove endpoint reachability.", scope,
                        rid, "network", "high" if protocol == "all" or protocol == "6" and not tcp else "medium"))
        elif operation == "policies":
            for statement in item.get("statements", []):
                if re.search(r"\bmanage\s+all-resources\s+in\s+tenancy\b", statement, re.I):
                    findings.append(finding(domain, "Tenancy-wide administrator policy", "unhealthy",
                        "Broad administrator grant found. Confirm ownership and intended membership; this is not proof of misuse.",
                        scope, rid, "identity", "medium"))
        elif operation == "instances":
            state = item.get("lifecycle-state", "UNKNOWN")
            findings.append(finding(domain, item.get("display-name", "Instance")+" lifecycle", "healthy" if state == "RUNNING" else "unknown",
                                    f"Lifecycle is {state}. Guest/application health and utilization are separate checks.", scope, rid, "compute"))
        elif operation in {"backups", "boot_backups"}:
            state = item.get("lifecycle-state")
            if state == "FAULTY":
                findings.append(finding(domain, "Backup is faulty", "unhealthy", "OCI reports FAULTY; restore readiness is not established", scope, rid, "recovery", "high"))
    if operation in {"backups", "boot_backups", "alarms", "log_groups", "budgets"} and not rows:
        findings.append(finding(domain, "No "+operation.replace("_", " ")+" returned", "unknown",
                                "No records in this scope. Other regions, services, policies, or collectors may provide coverage.", scope,
                                docs={"budgets":"cost", "backups":"recovery", "boot_backups":"recovery"}.get(operation,"monitoring")))
    return findings


class Scanner:
    def __init__(self, cli, tenancy, home_region, max_scopes=24):
        self.cli, self.tenancy, self.home_region, self.max_scopes = cli, tenancy, home_region, max_scopes

    def scan(self):
        started = time.time()
        regions_result = self.cli.read("regions", {}, self.home_region)
        compartments_result = self.cli.read("compartments", {"compartment-id": self.tenancy}, self.home_region)
        regions = data_of(regions_result)
        compartments = data_of(compartments_result)
        coverage = []
        if not isinstance(regions, list):
            coverage.append("Region discovery failed; only configured region checked")
            regions = []
        if not isinstance(compartments, list):
            coverage.append("Compartment discovery failed; only tenancy root checked")
            compartments = []
        region_names = sorted(set([r["region-name"] for r in regions if r.get("status") == "READY"]+[self.home_region]))
        compartment_ids = list(dict.fromkeys([self.tenancy]+[c["id"] for c in compartments if c.get("lifecycle-state") == "ACTIVE"]))
        scopes = [(r,c) for r in region_names for c in compartment_ids]
        if len(scopes)>self.max_scopes:
            coverage.append(f"Scan cap: {self.max_scopes} of {len(scopes)} region/compartment pairs checked")
        tasks = []
        for region, compartment in scopes[:self.max_scopes]:
            for operation in (o for ops in DOMAIN_OPERATIONS.values() for o in ops):
                if operation in {"users", "policies", "budgets", "cloud_guard"} and region != self.home_region:
                    continue
                if operation in {"users", "budgets", "cloud_guard"} and compartment != self.tenancy:
                    continue
                tasks.append((operation, region, compartment))
        def execute(task):
            operation, region, compartment = task
            result = self.cli.read(operation, {"compartment-id": compartment}, region)
            return {"operation":operation,"region":region,"compartment":compartment,"result":result}
        with ThreadPoolExecutor(max_workers=4) as pool:
            observations = list(pool.map(execute,tasks))
        findings, resources = [], []
        for entry in observations:
            scope = entry["region"]+" / "+entry["compartment"]
            findings.extend(evaluate(entry["operation"],entry["result"],scope))
            rows = data_of(entry["result"])
            if isinstance(rows,list):
                for item in rows:
                    if item.get("id"):
                        resources.append({"id":item["id"],"name":item.get("display-name") or item.get("name") or item["id"],
                            "kind":entry["operation"],"region":entry["region"],"compartment":entry["compartment"],
                            "state":item.get("lifecycle-state",item.get("status","Observed")),"details":item})
        for domain, title, why in [
            ("Compute","Performance telemetry","CPU, memory and volume time-series collection is not implemented in this release"),
            ("Networking","End-to-end connectivity","No Network Path Analyzer run or active endpoint probe performed"),
            ("Identity","Effective access and MFA","Identity Domain MFA, group membership and credential-age checks are not implemented"),
            ("Storage & recovery","Restore readiness","Backup inventory does not establish retention compliance or tested restore"),
            ("Cost","Spend anomaly analysis","Native anomaly and usage ingestion is not implemented; budget inventory is not anomaly detection"),
            ("Observability","Guest and application health","Guest collector and service probes are not configured"),
        ]:
            findings.append(finding(domain,title,"unknown",why,"Selected tenancy"))
        return {"started_at":started,"completed_at":time.time(),"regions":region_names,
                "compartment_count":len(compartment_ids),"coverage_gaps":coverage,
                "observations":observations,"resources":resources,"findings":findings,
                "discovery":{"regions":regions_result,"compartments":compartments_result},
                "mode":"live", "scope_pairs_checked":min(len(scopes),self.max_scopes)}


def difference(previous, current):
    before = {f["id"]:f for f in (previous or {}).get("findings",[])}
    after = {f["id"]:f for f in current.get("findings",[])}
    # Disappearing findings are not called resolved: coverage may have failed.
    return {"new":sorted(set(after)-set(before)),"not_observed":sorted(set(before)-set(after)),
            "changed":[key for key in before.keys() & after.keys()
                       if (before[key]["status"],before[key]["evidence"]) != (after[key]["status"],after[key]["evidence"])]}
