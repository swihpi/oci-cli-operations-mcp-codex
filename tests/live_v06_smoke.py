#!/usr/bin/env python3
"""Opt-in, read-only v0.6 smoke test. Prints status without tenancy payloads."""
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

SERVER = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "oci_mcp_server.py"


def main():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(hours=1)
    planned = [
        ("oci_scope_discovery", {}),
        ("oci_native_intelligence", {}),
        ("oci_network_diagnostics", {}),
        ("oci_identity_evidence", {}),
        ("oci_recovery_evidence", {}),
        *(("oci_service_inventory", {"family": family}) for family in
          ("containers", "devops", "resource_manager", "serverless", "messaging", "data_science", "goldengate", "databases")),
        ("oci_metric_query", {"namespace": "oci_computeagent", "query_text": "CpuUtilization[1m].mean()",
                              "start_time": start.isoformat().replace("+00:00", "Z"),
                              "end_time": now.isoformat().replace("+00:00", "Z")}),
    ]
    process = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        for index, (name, arguments) in enumerate(planned):
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                                            "params": {"name": name, "arguments": arguments}}) + "\n")
            process.stdin.flush()
            answer = json.loads(process.stdout.readline())
            if "result" not in answer:
                raise RuntimeError(f"{name}: no MCP result")
            payload = json.loads(answer["result"]["content"][0]["text"])
            sources = payload.get("results", {})
            failed = {key: {"error": value.get("error"), "exit_code": value.get("exit_code"),
                            "http_status": value.get("oci_error", {}).get("http_status"),
                            "oci_code": value.get("oci_error", {}).get("oci_code")}
                      for key, value in sources.items() if not value.get("ok")} if isinstance(sources, dict) else {}
            print(json.dumps({"tool": name, "ok": payload.get("ok"), "complete": payload.get("complete"),
                              "partial": payload.get("partial"), "failed_sources": failed,
                              "error_kind": payload.get("error")}), flush=True)
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
