#!/usr/bin/env python3
"""Deterministic OCI CLI stand-in used by the MCP protocol tests."""
import json
import sys
import time

args = sys.argv[1:]
if "--help" in args:
    path = args[2:-1]
    if (path and path[0] == "definitely-not-a-service") or path in (["compute", "instance", "start"], ["compute", "instance", "stop"]):
        print("Error: No such command.", file=sys.stderr)
        raise SystemExit(2)
    suffix = "[OPTIONS]" if path and path[-1] in {"action", "create", "delete", "get", "list", "terminate", "update"} else "[OPTIONS] COMMAND [ARGS]..."
    print(f"Usage: oci {' '.join(path)} {suffix}\n\nCommands:\n  action\n  get\n  list\n")
    raise SystemExit(0)
if "--text-output" in args:
    print("credential-content-that-must-not-leak")
    raise SystemExit(0)
if "--failed-stdout" in args:
    print("credential-content-that-must-not-leak")
    print("simulated CLI failure", file=sys.stderr)
    raise SystemExit(2)
if "--large-output" in args:
    print("x" * 2_000_000)
    raise SystemExit(0)
if "--delay" in args:
    time.sleep(0.5)
if "empty-success" in args or "--empty-success" in args:
    raise SystemExit(0)
if "failure" in args:
    print("simulated OCI error", file=sys.stderr)
    raise SystemExit(2)
if "--service-error" in args:
    print('ServiceError: {"status": 429, "code": "TooManyRequests", "target_service": "compute", "opc-request-id": "test-request-id"}', file=sys.stderr)
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
elif "audit" in args and "event" in args and "list" in args:
    print(json.dumps({"data": [
        {"event-time": "2026-09-30T08:00:00Z", "event-name": "UpdateInstance", "resource-id": "instance-test"},
        {"event-time": "2026-09-30T09:00:00Z", "event-name": "UpdateRouteTable", "resource-id": "route-test"}
    ]}))
elif "security-list" in args:
    print(json.dumps({"data": [{"id": "sl-test", "ingress-security-rules": [
        {"source": "0.0.0.0/0", "protocol": "6", "tcp-options": {"destination-port-range": {"min": 443, "max": 443}}}
    ]}]}))
elif "cloud-guard" in args and "configuration" in args:
    print(json.dumps({"data": {"status": "ENABLED"}}))
elif "logging" in args and "log-group" in args:
    print(json.dumps({"data": [{"id": "log-group-test", "display-name": "operations"}]}))
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
