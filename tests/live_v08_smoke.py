#!/usr/bin/env python3
"""Opt-in read-only v0.8 smoke test. Prints status and counts, never tenancy payloads."""
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

SERVER = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "oci_mcp_server.py"


def main():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(hours=1)
    window = {"start_time": start.isoformat().replace("+00:00", "Z"),
              "end_time": now.isoformat().replace("+00:00", "Z")}
    planned = [
        ("oci_verify_outcome", {"arguments": ["iam", "region", "list"],
                                "expectations": [{"pointer": "/data/0/name", "operator": "exists"}]}),
        ("oci_documented_checks", {}),
        ("oci_change_timeline", window | {"limit": 10, "timeout_seconds": 60}),
    ]
    process = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    try:
        for index, (name, arguments) in enumerate(planned):
            request = {"jsonrpc": "2.0", "id": index, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            answer = json.loads(process.stdout.readline())
            payload = json.loads(answer["result"]["content"][0]["text"])
            summary = {"tool": name, "ok": payload.get("ok"),
                       "verification_status": payload.get("verification_status"),
                       "complete": payload.get("complete"), "partial": payload.get("partial"),
                       "event_count": payload.get("event_count"), "summary": payload.get("summary"),
                       "error": payload.get("error")}
            print(json.dumps(summary, sort_keys=True), flush=True)
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
