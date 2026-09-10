#!/usr/bin/env python3
"""Deterministic OCI CLI stand-in used by the MCP protocol tests."""
import json
import sys
import time

args = sys.argv[1:]
if "empty-success" in args or "--empty-success" in args:
    raise SystemExit(0)
if "failure" in args:
    print("simulated OCI error", file=sys.stderr)
    raise SystemExit(2)
if "echo-secret-error" in args:
    secret_index = args.index("--admin-password") + 1
    print("rejected password: " + args[secret_index], file=sys.stderr)
    raise SystemExit(2)
if "timeout-secret" in args:
    secret_index = args.index("--admin-password") + 1
    print("processing password: " + args[secret_index], flush=True)
    time.sleep(2)
if args[-3:] == ["iam", "region", "list"]:
    print(json.dumps({"data": [{"name": "eu-frankfurt-1"}]}))
elif "request-summarized-usages" in args:
    print(json.dumps({"data": {"items": [
        {"service": "Compute", "time-usage-started": "2026-09-01T00:00:00Z", "computed-amount": 2.0},
        {"service": "Compute", "time-usage-started": "2026-09-02T00:00:00Z", "computed-amount": 6.0},
        {"service": "Storage", "time-usage-started": "2026-09-01T00:00:00Z", "computed-amount": 1.0},
        {"service": "Storage", "time-usage-started": "2026-09-02T00:00:00Z", "computed-amount": 1.1}
    ]}}))
elif "budget" in args:
    print(json.dumps({"data": [{"display-name": "monthly-budget", "amount": 25}]}))
elif "resource-availability" in args:
    print(json.dumps({"data": {"available": 3, "used": 1}}))
elif "work-request" in args:
    print(json.dumps({"data": {"id": "wr-test", "opc-work-request-id": "wr-test", "status": "SUCCEEDED"}}))
elif "instance" in args:
    print(json.dumps([{"name": "test-instance", "state": "RUNNING"}]))
elif "vcn" in args:
    print(json.dumps([{"name": "test-vcn", "cidr": "10.0.0.0/16"}]))
elif "autonomous-database" in args:
    print(json.dumps([{"name": "test-adw", "state": "AVAILABLE"}]))
elif "os" in args and "ns" in args:
    print(json.dumps({"data": "testnamespace"}))
elif "bucket" in args:
    print(json.dumps({"data": [{"name": "test-bucket"}]}))
else:
    print(json.dumps({"data": [], "metadata": {"ssh_authorized_keys": "must-not-echo"}}))
