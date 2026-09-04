#!/usr/bin/env python3
"""A safe, structured stdio MCP server for one local OCI CLI profile."""

import hashlib
import json
import os
import subprocess
import sys
import time

PROFILE = os.environ.get("OCI_CLI_PROFILE", "DEFAULT")
OCI_BINARY = os.environ.get("OCI_CLI_BINARY", "oci")
MAX_OUTPUT_BYTES = 1_000_000
DEFAULT_TIMEOUT_SECONDS = 45
BLOCKED_FLAGS = {"--profile", "--config-file", "--auth", "--endpoint", "--debug"}
READ_ONLY_VERBS = {"get", "list", "search", "summarize", "list-all"}
SENSITIVE_KEY_PARTS = ("password", "secret", "private_key", "token", "authorized_keys")


def schema(properties=None, required=None):
    return {"type": "object", "additionalProperties": False,
            "properties": properties or {}, "required": required or []}


TOOLS = [
    {"name": "oci_tenancy_summary", "description": "Return the configured profile, tenancy OCID, configured region, and subscribed regions.", "inputSchema": schema()},
    {"name": "oci_list_compartments", "description": "List active compartments below the configured tenancy.", "inputSchema": schema()},
    {"name": "oci_compute_inventory", "description": "Return a compact Compute inventory for a compartment; defaults to the tenancy.", "inputSchema": schema({"compartment_id": {"type": "string", "description": "Compartment OCID."}})},
    {"name": "oci_network_inventory", "description": "List VCNs in a compartment; defaults to the tenancy.", "inputSchema": schema({"compartment_id": {"type": "string", "description": "Compartment OCID."}})},
    {"name": "oci_autonomous_database_inventory", "description": "List Autonomous Databases in a compartment; defaults to the tenancy.", "inputSchema": schema({"compartment_id": {"type": "string", "description": "Compartment OCID."}})},
    {"name": "oci_list_buckets", "description": "List Object Storage buckets in a compartment; defaults to the tenancy.", "inputSchema": schema({"compartment_id": {"type": "string"}, "namespace": {"type": "string"}})},
    {"name": "oci_scope_discovery", "description": "Discover tenancy scope, subscribed regions, availability domains, and compartments in one read-only response.", "inputSchema": schema()},
    {"name": "oci_batch_read", "description": "Run up to eight independent read-only OCI CLI commands and return one structured result per command. Use it for any OCI service not covered by a typed inventory tool.", "inputSchema": schema({"commands": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "array", "items": {"type": "string"}}}}, ["commands"])},
    {"name": "oci_plan_mutation", "description": "Validate any OCI mutation command and return its exact approval token without executing it. Use before presenting a planned cloud change to the user.", "inputSchema": schema({"arguments": {"type": "array", "items": {"type": "string"}}}, ["arguments"])},
    {"name": "oci_verify_cli", "description": "Run a focused read-only OCI CLI verification command after a cloud mutation.", "inputSchema": schema({"arguments": {"type": "array", "items": {"type": "string"}}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120}}, ["arguments"])},
    {"name": "oci_execute_cli", "description": "Advanced fallback for any OCI CLI command. Read-only commands run immediately. Mutations return an approval token and run only when that exact token is supplied after the user approves.", "inputSchema": schema({"arguments": {"type": "array", "items": {"type": "string"}, "description": "OCI arguments only; omit the leading oci."}, "approval_token": {"type": "string", "description": "Token returned for this exact mutating command after explicit user approval."}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120}}, ["arguments"])},
]


def config_values():
    values, current = {}, None
    with open(os.path.expanduser("~/.oci/config"), encoding="utf-8") as config:
        for raw in config:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
            elif current == PROFILE and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    if "tenancy" not in values:
        raise ValueError(f"Missing tenancy in OCI profile {PROFILE!r}")
    return values


def compact(text):
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return text, False
    return encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore"), True


def run_oci(arguments, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
    started = time.monotonic()
    command = [OCI_BINARY, "--profile", PROFILE, "--output", "json", *arguments]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "command": command, "exit_code": None, "stdout": compact(exc.stdout or "")[0], "stderr": compact(exc.stderr or "")[0], "error": "OCI CLI timed out", "duration_ms": round((time.monotonic() - started) * 1000)}
    stdout, stdout_truncated = compact(result.stdout or "")
    stderr, stderr_truncated = compact(result.stderr or "")
    response = {"ok": result.returncode == 0 and bool(stdout.strip()), "command": command, "exit_code": result.returncode, "stdout": stdout, "stderr": stderr, "duration_ms": round((time.monotonic() - started) * 1000), "truncated": stdout_truncated or stderr_truncated}
    if result.returncode == 0 and not stdout.strip():
        response["error"] = "OCI CLI exited successfully but returned no stdout; result is not treated as a successful inventory."
    elif result.returncode != 0:
        response["error"] = "OCI CLI command failed"
    return response


def parsed_result(result):
    if not result["ok"]:
        return result
    try:
        result["data"] = redact(json.loads(result.pop("stdout")))
    except json.JSONDecodeError:
        result["ok"] = False
        result["error"] = "OCI CLI returned non-JSON output"
    return result


def redact(value):
    """Keep command results useful without echoing credential-like response fields."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if any(part in key.lower() for part in SENSITIVE_KEY_PARTS)
                else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def command_token(arguments):
    canonical = json.dumps(arguments, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256((PROFILE + "\0" + canonical).encode()).hexdigest()[:24]


def validate_arguments(arguments):
    if not isinstance(arguments, list) or not arguments or any(not isinstance(a, str) or not a for a in arguments):
        raise ValueError("arguments must be a non-empty array of non-empty strings")
    if any(a in BLOCKED_FLAGS or any(a.startswith(flag + "=") for flag in BLOCKED_FLAGS) for a in arguments):
        raise ValueError("arguments may not override profile, config, authentication, endpoint, or enable debug output")


def is_read_only(arguments):
    return any(arg in READ_ONLY_VERBS for arg in arguments[:4])


def text_result(payload, error=False):
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}], "isError": error}


def run_typed(arguments):
    return parsed_result(run_oci(arguments))


def validation_error(arguments, read_only=False):
    try:
        validate_arguments(arguments)
    except ValueError as exc:
        return str(exc)
    if read_only and not is_read_only(arguments):
        return "only read-only OCI commands are accepted by this tool"
    return None


def mutation_plan(arguments):
    error = validation_error(arguments)
    if error:
        return {"ok": False, "error": error}
    if is_read_only(arguments):
        return {"ok": True, "read_only": True, "command": ["oci", *arguments], "message": "This command is read-only and needs no approval token."}
    return {"ok": True, "read_only": False, "confirmation_required": True,
            "command": ["oci", *arguments], "approval_token": command_token(arguments),
            "message": "Present this exact command, scope, availability impact, and cost/security impact. Execute only after explicit approval."}


def call_tool(name, arguments):
    arguments = arguments or {}
    config = config_values()
    tenancy = config["tenancy"]
    compartment = arguments.get("compartment_id", tenancy)
    if name == "oci_tenancy_summary":
        result = run_typed(["iam", "region", "list"])
        result.update({"profile": PROFILE, "tenancy": tenancy, "configured_region": config.get("region")})
        return text_result(result, not result["ok"])
    if name == "oci_list_compartments":
        result = run_typed(["iam", "compartment", "list", "--compartment-id", tenancy, "--all"])
    elif name == "oci_compute_inventory":
        result = run_typed(["compute", "instance", "list", "--compartment-id", compartment, "--all", "--query", 'data[].{id:id,name:"display-name",state:"lifecycle-state",shape:shape,region:region,availability_domain:"availability-domain",compartment_id:"compartment-id"}'])
    elif name == "oci_network_inventory":
        result = run_typed(["network", "vcn", "list", "--compartment-id", compartment, "--all", "--query", 'data[].{id:id,name:"display-name",state:"lifecycle-state",cidr:"cidr-block",compartment_id:"compartment-id"}'])
    elif name == "oci_autonomous_database_inventory":
        result = run_typed(["db", "autonomous-database", "list", "--compartment-id", compartment, "--all", "--query", 'data[].{id:id,name:"display-name",state:"lifecycle-state",workload:"db-workload",cpu:"cpu-core-count",storage_tbs:"data-storage-size-in-tbs",private_endpoint:"private-endpoint"}'])
    elif name == "oci_list_buckets":
        namespace = arguments.get("namespace")
        if not namespace:
            namespace_result = run_typed(["os", "ns", "get"])
            if not namespace_result["ok"]:
                return text_result(namespace_result, True)
            namespace = namespace_result["data"].get("data")
        result = run_typed(["os", "bucket", "list", "--compartment-id", compartment, "--namespace", namespace, "--all"])
    elif name == "oci_scope_discovery":
        commands = {
            "regions": ["iam", "region", "list"],
            "availability_domains": ["iam", "availability-domain", "list", "--compartment-id", tenancy],
            "compartments": ["iam", "compartment", "list", "--compartment-id", tenancy, "--all"],
        }
        entries = {label: run_typed(command) for label, command in commands.items()}
        result = {"ok": all(entry["ok"] for entry in entries.values()), "profile": PROFILE,
                  "tenancy": tenancy, "configured_region": config.get("region"), "results": entries}
    elif name == "oci_batch_read":
        commands = arguments.get("commands")
        if not isinstance(commands, list) or not 1 <= len(commands) <= 8:
            return text_result({"ok": False, "error": "commands must contain between 1 and 8 OCI argument arrays"}, True)
        entries = []
        for cli_args in commands:
            error = validation_error(cli_args, read_only=True)
            entries.append({"arguments": cli_args, "ok": False, "error": error} if error else run_typed(cli_args))
        result = {"ok": all(entry["ok"] for entry in entries), "results": entries}
    elif name == "oci_plan_mutation":
        result = mutation_plan(arguments.get("arguments"))
    elif name == "oci_verify_cli":
        cli_args = arguments.get("arguments")
        error = validation_error(cli_args, read_only=True)
        if error:
            return text_result({"ok": False, "error": error}, True)
        result = parsed_result(run_oci(cli_args, arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)))
    elif name == "oci_execute_cli":
        cli_args = arguments.get("arguments")
        error = validation_error(cli_args)
        if error:
            return text_result({"ok": False, "error": error}, True)
        if not is_read_only(cli_args):
            plan = mutation_plan(cli_args)
            if arguments.get("approval_token") != plan["approval_token"]:
                plan["ok"] = False
                return text_result(plan, True)
        timeout = arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        result = parsed_result(run_oci(cli_args, timeout))
        return text_result(result, not result["ok"])
    else:
        return text_result({"ok": False, "error": f"Unknown tool: {name}"}, True)
    return text_result(result, not result["ok"])


def respond(message):
    method, request_id = message.get("method"), message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "oci-tenancy", "version": "0.2.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params", {})
        return {"jsonrpc": "2.0", "id": request_id, "result": call_tool(params.get("name"), params.get("arguments", {}))}
    if request_id is not None:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unsupported method: {method}"}}
    return None


for line in sys.stdin:
    request_id = None
    try:
        message = json.loads(line)
        request_id = message.get("id")
        response = respond(message)
        if response is not None:
            print(json.dumps(response), flush=True)
    except Exception as exc:
        print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}), flush=True)
