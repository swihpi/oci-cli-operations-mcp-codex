#!/usr/bin/env python3
"""Deterministic OCI CLI stand-in used by the MCP protocol tests."""
import json
import sys

args = sys.argv[1:]
if "empty-success" in args:
    raise SystemExit(0)
if "failure" in args:
    print("simulated OCI error", file=sys.stderr)
    raise SystemExit(2)
if args[-3:] == ["iam", "region", "list"]:
    print(json.dumps({"data": [{"name": "eu-frankfurt-1"}]}))
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
