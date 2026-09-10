#!/usr/bin/env python3
"""Opt-in live smoke test that prints status only, never tenancy payloads."""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "oci_mcp_server.py"


def main(started, ended):
    process = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=os.environ | {"OCI_CLI_PROFILE": os.environ.get("OCI_CLI_PROFILE", "DEFAULT")},
    )

    def call(name, arguments=None):
        request = {"jsonrpc": "2.0", "id": name, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        result = response["result"]
        payload = json.loads(result["content"][0]["text"])
        status = {"ok": payload.get("ok", False), "complete": payload.get("complete"), "partial": payload.get("partial"), "is_error": result.get("isError", False)}
        if not status["ok"] or status["partial"]:
            if isinstance(payload.get("results"), dict):
                status["checks"] = {label: {"ok": item.get("ok"), "exit_code": item.get("exit_code"), "error": item.get("error")} for label, item in payload["results"].items()}
            else:
                status["exit_code"] = payload.get("exit_code")
                status["error"] = payload.get("error")
        return status

    planned = [
        ("cost", "oci_cost_usage_summary", {"time_usage_started": started, "time_usage_ended": ended, "granularity": "DAILY", "query_type": "COST", "group_by": ["service"]}),
        ("cost_anomaly", "oci_cost_anomaly_scan", {"time_usage_started": started, "time_usage_ended": ended, "dimension": "service", "threshold_percent": 50, "minimum_cost_delta": 1}),
        ("budgets", "oci_budget_inventory", {}),
        ("limits", "oci_limits_overview", {"service_name": "compute"}),
        ("resource_search", "oci_resource_search", {"query_text": "query all resources", "limit": 10}),
        ("security", "oci_security_posture", {}),
        ("network", "oci_network_health", {}),
        ("observability", "oci_observability_inventory", {}),
        ("governance", "oci_governance_inventory", {}),
    ]
    checks = {}
    for label, tool, arguments in planned:
        checks[label] = call(tool, arguments)
        print(json.dumps({label: checks[label]}, sort_keys=True), flush=True)
    process.terminate()
    process.wait(timeout=5)
    print(json.dumps({"summary": checks}, sort_keys=True))
    if not all(check["ok"] for check in checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: live_read_smoke.py START END")
    main(sys.argv[1], sys.argv[2])
