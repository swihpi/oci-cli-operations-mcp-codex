#!/usr/bin/env python3
"""A safe, structured stdio MCP server for one local OCI CLI profile."""

import json
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

PROFILE = os.environ.get("OCI_CLI_PROFILE", "DEFAULT")
OCI_BINARY = os.environ.get("OCI_CLI_BINARY", "oci")
MAX_OUTPUT_BYTES = 1_000_000
DEFAULT_TIMEOUT_SECONDS = 45
MAX_ARGUMENTS = 256
MAX_ARGUMENT_BYTES = 131_072
MAX_PENDING_APPROVALS = 256
APPROVAL_TTL_SECONDS = 300
BLOCKED_FLAGS = {
    "--auth", "--auth-purpose", "--cert-bundle", "--cli-rc-file", "--config-file",
    "--debug", "--defaults-file", "--endpoint", "--federation-endpoint", "--profile",
    "--proxy", "--realm-specific-endpoint",
}
BLOCKED_COMMAND_ROOTS = {"raw-request", "session", "setup", "update"}
BLOCKED_LOCAL_FILE_FLAGS = {
    "--file", "--file-path", "--filename", "--output-file", "--private-key-file",
    "--script-file", "--source-file", "--src-file", "--ssh-authorized-keys-file",
}
READ_ONLY_OPERATIONS = {
    "free-text-search", "get", "list", "list-all", "search", "structured-search",
    "summarize", "summarize-metrics-data",
}
READ_ONLY_OPERATION_PREFIXES = ("get-", "list-", "search-", "summarize-")
# Some OCI GET/POST queries use request-* command names even though they do not
# mutate cloud state. Keep these exceptional paths explicit and fail closed for
# unknown request commands.
READ_ONLY_PATHS = {
    ("usage-api", "average-carbon-emission", "request"),
    ("usage-api", "clean-energy-usage", "request"),
    ("usage-api", "configuration", "request-summarized"),
    ("usage-api", "configuration", "request-usage-carbon-emission-config"),
    ("usage-api", "usage-carbon-emission-summary", "request-usage-carbon-emissions"),
    ("usage-api", "usage-summary", "request-summarized-usages"),
}
SENSITIVE_KEY_PARTS = ("password", "secret", "privatekey", "token", "authorizedkeys")
SENSITIVE_OPTION_PARTS = ("password", "secret", "private-key", "private_key", "token")
USAGE_GRANULARITIES = {"HOURLY", "DAILY", "MONTHLY"}
USAGE_QUERY_TYPES = {"USAGE", "COST", "CREDIT", "EXPIREDCREDIT", "ALLCREDIT", "USAGE_ONLY"}
USAGE_DIMENSIONS = {
    "service", "skuName", "skuPartNumber", "unit", "compartmentName", "compartmentPath",
    "compartmentId", "platform", "region", "logicalAd", "resourceId", "tenantId", "tenantName",
}
PENDING_APPROVALS = {}


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
    {"name": "oci_cost_usage_summary", "description": "Query OCI Usage API cost, usage, or credits for an explicit time window. Read-only and tenancy-scoped.", "inputSchema": schema({"time_usage_started": {"type": "string"}, "time_usage_ended": {"type": "string"}, "granularity": {"type": "string", "enum": sorted(USAGE_GRANULARITIES)}, "query_type": {"type": "string", "enum": sorted(USAGE_QUERY_TYPES)}, "group_by": {"type": "array", "maxItems": 4, "items": {"type": "string", "enum": sorted(USAGE_DIMENSIONS)}}}, ["time_usage_started", "time_usage_ended", "granularity"])},
    {"name": "oci_cost_usage_by_dimension", "description": "Query OCI cost or usage grouped by one supported service, SKU, compartment, resource, region, platform, or tenant dimension.", "inputSchema": schema({"time_usage_started": {"type": "string"}, "time_usage_ended": {"type": "string"}, "granularity": {"type": "string", "enum": sorted(USAGE_GRANULARITIES)}, "query_type": {"type": "string", "enum": sorted(USAGE_QUERY_TYPES)}, "dimension": {"type": "string", "enum": sorted(USAGE_DIMENSIONS)}}, ["time_usage_started", "time_usage_ended", "granularity", "dimension"])},
    {"name": "oci_cost_anomaly_scan", "description": "Run a deterministic read-only daily OCI cost query and compare the latest returned period with its prior-period baseline. This is evidence-based arithmetic, not an AI forecast.", "inputSchema": schema({"time_usage_started": {"type": "string"}, "time_usage_ended": {"type": "string"}, "dimension": {"type": "string", "enum": sorted(USAGE_DIMENSIONS)}, "threshold_percent": {"type": "number", "minimum": 1, "maximum": 10000}, "minimum_cost_delta": {"type": "number", "minimum": 0}}, ["time_usage_started", "time_usage_ended"])},
    {"name": "oci_budget_inventory", "description": "List OCI budgets visible in a compartment, including tag-target budgets. Read-only.", "inputSchema": schema({"compartment_id": {"type": "string"}})},
    {"name": "oci_limits_overview", "description": "List service limit values and active compartment quotas for a named OCI service.", "inputSchema": schema({"service_name": {"type": "string"}, "compartment_id": {"type": "string"}}, ["service_name"])},
    {"name": "oci_resource_availability", "description": "Read current usage and available capacity for a supported OCI service limit.", "inputSchema": schema({"service_name": {"type": "string"}, "limit_name": {"type": "string"}, "compartment_id": {"type": "string"}, "availability_domain": {"type": "string"}}, ["service_name", "limit_name"])},
    {"name": "oci_resource_search", "description": "Run an OCI Search structured query across resources visible in the configured tenancy.", "inputSchema": schema({"query_text": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, ["query_text"])},
    {"name": "oci_security_posture", "description": "Collect a read-only, explicitly partial security evidence bundle: IAM policies, Cloud Guard, security zones, Vulnerability Scanning recipes, vaults, and Audit configuration.", "inputSchema": schema({"compartment_id": {"type": "string"}})},
    {"name": "oci_network_health", "description": "Collect a read-only network topology and exposure evidence bundle for a compartment: VCNs, subnets, routes, security lists, NSGs, gateways, and load balancers.", "inputSchema": schema({"compartment_id": {"type": "string"}})},
    {"name": "oci_observability_inventory", "description": "Collect a read-only observability evidence bundle: alarms, log groups, event rules, and notification topics.", "inputSchema": schema({"compartment_id": {"type": "string"}})},
    {"name": "oci_governance_inventory", "description": "Collect a read-only governance evidence bundle: budgets, quotas, tag namespaces, and tenancy-wide resource-search coverage.", "inputSchema": schema({"compartment_id": {"type": "string"}})},
    {"name": "oci_work_request_status", "description": "Run a service-specific read-only OCI work-request get or list command and return any discovered work-request identifiers and status fields.", "inputSchema": schema({"arguments": {"type": "array", "items": {"type": "string"}}}, ["arguments"])},
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
        return {"ok": False, "command": [OCI_BINARY, "--profile", PROFILE, "--output", "json", *display_arguments(arguments)], "exit_code": None,
                "stdout": compact(redact_sensitive_text(exc.stdout or "", arguments))[0],
                "stderr": compact(redact_sensitive_text(exc.stderr or "", arguments))[0],
                "error": "OCI CLI timed out", "duration_ms": round((time.monotonic() - started) * 1000)}
    stdout, stdout_truncated = compact(redact_sensitive_text(result.stdout or "", arguments))
    stderr, stderr_truncated = compact(redact_sensitive_text(result.stderr or "", arguments))
    path = command_path(arguments)
    empty_list = result.returncode == 0 and not stdout.strip() and bool(path) and (path[-1] == "list" or path[-1].startswith("list-"))
    accepted_without_payload = result.returncode == 0 and not stdout.strip() and not is_read_only(arguments)
    if empty_list:
        stdout = "[]"
    elif accepted_without_payload:
        stdout = "null"
    response = {"ok": result.returncode == 0 and bool(stdout.strip()), "command": [OCI_BINARY, "--profile", PROFILE, "--output", "json", *display_arguments(arguments)], "exit_code": result.returncode, "stdout": stdout, "stderr": stderr, "duration_ms": round((time.monotonic() - started) * 1000), "truncated": stdout_truncated or stderr_truncated}
    if empty_list:
        response["empty"] = True
        response["message"] = "OCI CLI returned exit code 0 and no rows for this list operation."
    elif accepted_without_payload:
        response["accepted_without_payload"] = True
        response["message"] = "OCI CLI returned exit code 0 with no response body; verify the resulting cloud state with a focused read."
    elif result.returncode == 0 and not stdout.strip():
        response["error"] = "OCI CLI exited successfully but returned no stdout; result is not treated as a successful inventory."
    elif result.returncode != 0:
        response["error"] = "OCI CLI command failed"
    return response


def parsed_result(result):
    if not result["ok"]:
        return result
    try:
        result["data"] = redact(json.loads(result.pop("stdout")))
        work_request_ids = extract_named_values(result["data"], {"opcworkrequestid", "workrequestid"})
        if work_request_ids:
            result["work_request_ids"] = sorted(work_request_ids)
    except json.JSONDecodeError:
        result["ok"] = False
        result["error"] = "OCI CLI returned non-JSON output"
    return result


def redact(value):
    """Keep command results useful without echoing credential-like response fields."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if any(part in "".join(ch for ch in key.lower() if ch.isalnum()) for part in SENSITIVE_KEY_PARTS)
                else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def extract_named_values(value, normalized_names):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(ch for ch in key.lower() if ch.isalnum())
            if normalized in normalized_names and isinstance(item, str) and item:
                found.add(item)
            found.update(extract_named_values(item, normalized_names))
    elif isinstance(value, list):
        for item in value:
            found.update(extract_named_values(item, normalized_names))
    return found


def display_arguments(arguments):
    """Return an audit-safe representation while preserving command structure."""
    shown, redact_next = [], False
    for argument in arguments:
        lower = argument.lower()
        if redact_next:
            shown.append("[REDACTED]")
            redact_next = False
        elif argument.startswith("--") and "=" in argument and any(part in argument.split("=", 1)[0].lower() for part in SENSITIVE_OPTION_PARTS):
            shown.append(argument.split("=", 1)[0] + "=[REDACTED]")
        else:
            shown.append(argument)
            redact_next = argument.startswith("--") and any(part in lower for part in SENSITIVE_OPTION_PARTS)
    return shown


def sensitive_argument_values(arguments):
    values, redact_next = [], False
    for argument in arguments:
        lower = argument.lower()
        if redact_next:
            values.append(argument)
            redact_next = False
        elif argument.startswith("--") and "=" in argument and any(part in argument.split("=", 1)[0].lower() for part in SENSITIVE_OPTION_PARTS):
            values.append(argument.split("=", 1)[1])
        else:
            redact_next = argument.startswith("--") and any(part in lower for part in SENSITIVE_OPTION_PARTS)
    return [value for value in values if value]


def redact_sensitive_text(text, arguments):
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    for value in sensitive_argument_values(arguments):
        text = text.replace(value, "[REDACTED]")
    return text


def validate_schema_value(value, definition, field):
    expected = definition.get("type")
    matches = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
    }
    if expected in matches and not matches[expected](value):
        return f"{field} must be {expected}"
    if "enum" in definition and value not in definition["enum"]:
        return f"{field} is not an allowed value"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in definition and value < definition["minimum"]:
            return f"{field} is below its minimum"
        if "maximum" in definition and value > definition["maximum"]:
            return f"{field} exceeds its maximum"
    if isinstance(value, list):
        if "minItems" in definition and len(value) < definition["minItems"]:
            return f"{field} has too few items"
        if "maxItems" in definition and len(value) > definition["maxItems"]:
            return f"{field} has too many items"
        for index, item in enumerate(value):
            error = validate_schema_value(item, definition.get("items", {}), f"{field}[{index}]")
            if error:
                return error
    return None


def validate_tool_call(name, arguments):
    tool = next((item for item in TOOLS if item["name"] == name), None)
    if tool is None:
        return f"Unknown tool: {name}"
    if not isinstance(arguments, dict):
        return "tool arguments must be an object"
    contract = tool["inputSchema"]
    unknown = set(arguments) - set(contract["properties"])
    if unknown:
        return "unexpected tool argument(s): " + ", ".join(sorted(unknown))
    missing = set(contract.get("required", [])) - set(arguments)
    if missing:
        return "missing required tool argument(s): " + ", ".join(sorted(missing))
    for field, value in arguments.items():
        error = validate_schema_value(value, contract["properties"][field], field)
        if error:
            return error
    return None


def validate_arguments(arguments):
    if not isinstance(arguments, list) or not arguments or any(not isinstance(a, str) or not a for a in arguments):
        raise ValueError("arguments must be a non-empty array of non-empty strings")
    if len(arguments) > MAX_ARGUMENTS or sum(len(a.encode("utf-8")) for a in arguments) > MAX_ARGUMENT_BYTES:
        raise ValueError("arguments exceed the configured size limit")
    if arguments[0] == "oci":
        raise ValueError("omit the leading oci executable")
    if arguments[0] in BLOCKED_COMMAND_ROOTS:
        raise ValueError("local CLI administration, sessions, self-update, and raw HTTP requests are outside this MCP boundary")
    if any(any(ord(ch) < 32 or ord(ch) == 127 for ch in a) for a in arguments):
        raise ValueError("arguments may not contain control characters")
    if any("file://" in a.lower() for a in arguments):
        raise ValueError("file:// inputs are blocked; provide validated inline JSON instead")
    if any(a in BLOCKED_LOCAL_FILE_FLAGS or any(a.startswith(flag + "=") for flag in BLOCKED_LOCAL_FILE_FLAGS) for a in arguments):
        raise ValueError("local file input and output flags are blocked; use a separately reviewed file-transfer workflow")
    if any(a in BLOCKED_FLAGS or any(a.startswith(flag + "=") for flag in BLOCKED_FLAGS) for a in arguments):
        raise ValueError("arguments may not override profile, config, authentication, transport, defaults, or enable debug output")


def command_path(arguments):
    """OCI service/group/action tokens must precede command options."""
    path = []
    for argument in arguments:
        if argument.startswith("-"):
            break
        path.append(argument)
    return tuple(path)


def is_read_only(arguments):
    path = command_path(arguments)
    return bool(path) and (path[-1] in READ_ONLY_OPERATIONS or path[-1].startswith(READ_ONLY_OPERATION_PREFIXES) or path in READ_ONLY_PATHS)


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
        return {"ok": True, "read_only": True, "command": ["oci", *display_arguments(arguments)], "message": "This command is read-only and needs no approval token."}
    purge_approvals()
    if len(PENDING_APPROVALS) >= MAX_PENDING_APPROVALS:
        PENDING_APPROVALS.pop(next(iter(PENDING_APPROVALS)))
    approval_token = secrets.token_urlsafe(32)
    PENDING_APPROVALS[approval_token] = {"arguments": tuple(arguments), "expires": time.monotonic() + APPROVAL_TTL_SECONDS}
    return {"ok": True, "read_only": False, "confirmation_required": True,
            "command": ["oci", *display_arguments(arguments)], "approval_token": approval_token,
            "expires_at": time.time() + APPROVAL_TTL_SECONDS,
            "message": "Present this exact command, scope, availability impact, and cost/security impact. This single-use approval expires in five minutes."}


def purge_approvals():
    now = time.monotonic()
    for token in [token for token, record in PENDING_APPROVALS.items() if record["expires"] <= now]:
        PENDING_APPROVALS.pop(token, None)


def consume_approval(token, arguments):
    purge_approvals()
    record = PENDING_APPROVALS.pop(token, None) if isinstance(token, str) else None
    return bool(record and record["expires"] > time.monotonic() and record["arguments"] == tuple(arguments))


def usage_arguments(config, arguments, group_by=None, query_type=None, granularity=None):
    started, ended = arguments.get("time_usage_started"), arguments.get("time_usage_ended")
    if not isinstance(started, str) or not isinstance(ended, str) or not started or not ended:
        raise ValueError("time_usage_started and time_usage_ended are required")
    try:
        start_time = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("usage times must be ISO 8601 dates or timestamps") from exc
    if start_time >= end_time:
        raise ValueError("time_usage_started must precede time_usage_ended")
    granularity = granularity or arguments.get("granularity")
    query_type = query_type or arguments.get("query_type", "COST")
    if granularity not in USAGE_GRANULARITIES or query_type not in USAGE_QUERY_TYPES:
        raise ValueError("unsupported Usage API granularity or query type")
    if granularity == "HOURLY" and (end_time - start_time).total_seconds() > 36 * 3600:
        raise ValueError("HOURLY Usage API windows may not exceed 36 hours")
    if granularity == "MONTHLY" and (start_time.day != 1 or end_time.day != 1):
        raise ValueError("MONTHLY Usage API windows must begin and end on the first day of a month")
    groups = group_by if group_by is not None else arguments.get("group_by", [])
    if not isinstance(groups, list) or len(groups) > 4 or any(group not in USAGE_DIMENSIONS for group in groups):
        raise ValueError("group_by must contain up to four supported Usage API dimensions")
    result = ["usage-api", "usage-summary", "request-summarized-usages", "--tenant-id", config["tenancy"],
              "--time-usage-started", started, "--time-usage-ended", ended, "--granularity", granularity,
              "--query-type", query_type]
    if groups:
        result += ["--group-by", json.dumps(groups, separators=(",", ":"))]
    return result


def bundle(commands):
    with ThreadPoolExecutor(max_workers=min(4, len(commands))) as pool:
        futures = {label: pool.submit(run_typed, cli_args) for label, cli_args in commands.items()}
        results = {label: future.result() for label, future in futures.items()}
    return {"ok": any(item["ok"] for item in results.values()), "complete": all(item["ok"] for item in results.values()),
            "partial": not all(item["ok"] for item in results.values()), "results": results,
            "message": "Partial evidence is not a healthy result; inspect each failed or unauthorized check."}


def extract_items(result):
    value = result.get("data", {})
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    if isinstance(value, dict):
        value = value.get("items", [])
    return value if isinstance(value, list) else []


def anomaly_report(result, dimension, threshold_percent, minimum_delta):
    grouped = {}
    for item in extract_items(result):
        if not isinstance(item, dict):
            continue
        period = item.get("time-usage-started") or item.get("timeUsageStarted")
        amount = item.get("computed-amount", item.get("computedAmount"))
        label = item.get(dimension, "(unassigned)")
        try:
            grouped.setdefault(str(label), {}).setdefault(str(period), 0.0)
            grouped[str(label)][str(period)] += float(amount)
        except (TypeError, ValueError):
            continue
    anomalies = []
    for label, periods in grouped.items():
        ordered = sorted(periods.items())
        if len(ordered) < 2:
            continue
        latest_period, latest = ordered[-1]
        baseline_values = [amount for _, amount in ordered[:-1]]
        baseline = sum(baseline_values) / len(baseline_values)
        delta = latest - baseline
        percent = (delta / baseline * 100) if baseline else None
        exceeds_percent = percent >= threshold_percent if percent is not None else latest > 0
        if delta >= minimum_delta and exceeds_percent:
            anomalies.append({"dimension": label, "latest_period": latest_period, "latest_cost": latest,
                              "baseline_average": baseline, "absolute_delta": delta, "percent_delta": percent,
                              "baseline_was_zero": baseline == 0})
    return sorted(anomalies, key=lambda item: item["absolute_delta"], reverse=True)


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
    elif name == "oci_cost_usage_summary":
        result = run_typed(usage_arguments(config, arguments))
    elif name == "oci_cost_usage_by_dimension":
        dimension = arguments.get("dimension")
        if dimension not in USAGE_DIMENSIONS:
            return text_result({"ok": False, "error": "unsupported Usage API dimension"}, True)
        result = run_typed(usage_arguments(config, arguments, group_by=[dimension]))
    elif name == "oci_cost_anomaly_scan":
        dimension = arguments.get("dimension", "service")
        if dimension not in USAGE_DIMENSIONS:
            return text_result({"ok": False, "error": "unsupported Usage API dimension"}, True)
        threshold = arguments.get("threshold_percent", 50)
        minimum_delta = arguments.get("minimum_cost_delta", 1)
        if not isinstance(threshold, (int, float)) or not 1 <= threshold <= 10000 or not isinstance(minimum_delta, (int, float)) or minimum_delta < 0:
            return text_result({"ok": False, "error": "invalid anomaly thresholds"}, True)
        usage = run_typed(usage_arguments(config, arguments, group_by=[dimension], query_type="COST", granularity="DAILY"))
        result = {"ok": usage["ok"], "dimension": dimension, "threshold_percent": threshold,
                  "minimum_cost_delta": minimum_delta, "usage": usage,
                  "anomalies": anomaly_report(usage, dimension, threshold, minimum_delta) if usage["ok"] else [],
                  "method": "Latest returned daily period versus the arithmetic mean of earlier returned periods; zero-baseline increases are infinite-percent changes."}
    elif name == "oci_budget_inventory":
        result = run_typed(["budgets", "budget", "budget", "list", "--compartment-id", compartment, "--target-type", "ALL", "--all"])
    elif name == "oci_limits_overview":
        service_name = arguments.get("service_name")
        if not isinstance(service_name, str) or not service_name or len(service_name) > 128:
            return text_result({"ok": False, "error": "service_name is required"}, True)
        result = bundle({
            "limit_values": ["limits", "value", "list", "--compartment-id", compartment, "--service-name", service_name, "--all"],
            "quotas": ["limits", "quota", "list", "--compartment-id", compartment, "--lifecycle-state", "ACTIVE", "--all"],
        })
    elif name == "oci_resource_availability":
        service_name, limit_name = arguments.get("service_name"), arguments.get("limit_name")
        if not all(isinstance(value, str) and value and len(value) <= 256 for value in (service_name, limit_name)):
            return text_result({"ok": False, "error": "service_name and limit_name are required"}, True)
        cli_args = ["limits", "resource-availability", "get", "--service-name", service_name,
                    "--limit-name", limit_name, "--compartment-id", compartment]
        if arguments.get("availability_domain"):
            cli_args += ["--availability-domain", arguments["availability_domain"]]
        result = run_typed(cli_args)
    elif name == "oci_resource_search":
        query_text = arguments.get("query_text")
        limit = arguments.get("limit", 1000)
        if not isinstance(query_text, str) or not 3 <= len(query_text) <= 4000 or not isinstance(limit, int) or not 1 <= limit <= 1000:
            return text_result({"ok": False, "error": "query_text must be 3-4000 characters and limit 1-1000"}, True)
        result = run_typed(["search", "resource", "structured-search", "--query-text", query_text, "--limit", str(limit)])
    elif name == "oci_security_posture":
        result = bundle({
            "iam_policies": ["iam", "policy", "list", "--compartment-id", compartment, "--all"],
            "cloud_guard": ["cloud-guard", "configuration", "get", "--compartment-id", tenancy],
            "security_zones": ["cloud-guard", "security-zone-collection", "list-security-zones", "--compartment-id", compartment, "--all"],
            "host_scan_recipes": ["vulnerability-scanning", "host", "scan", "recipe", "list", "--compartment-id", compartment, "--all"],
            "vaults": ["kms", "management", "vault", "list", "--compartment-id", compartment, "--all"],
            "audit_configuration": ["audit", "config", "get", "--compartment-id", tenancy],
        })
    elif name == "oci_network_health":
        result = bundle({
            "vcns": ["network", "vcn", "list", "--compartment-id", compartment, "--all"],
            "subnets": ["network", "subnet", "list", "--compartment-id", compartment, "--all"],
            "route_tables": ["network", "route-table", "list", "--compartment-id", compartment, "--all"],
            "security_lists": ["network", "security-list", "list", "--compartment-id", compartment, "--all"],
            "network_security_groups": ["network", "nsg", "list", "--compartment-id", compartment, "--all"],
            "internet_gateways": ["network", "internet-gateway", "list", "--compartment-id", compartment, "--all"],
            "nat_gateways": ["network", "nat-gateway", "list", "--compartment-id", compartment, "--all"],
            "service_gateways": ["network", "service-gateway", "list", "--compartment-id", compartment, "--all"],
            "load_balancers": ["lb", "load-balancer", "list", "--compartment-id", compartment, "--all"],
        })
    elif name == "oci_observability_inventory":
        result = bundle({
            "alarms": ["monitoring", "alarm", "list", "--compartment-id", compartment, "--compartment-id-in-subtree", "true", "--all"],
            "log_groups": ["logging", "log-group", "list", "--compartment-id", compartment, "--compartmentidinsubtree", "true", "--all"],
            "event_rules": ["events", "rule", "list", "--compartment-id", compartment, "--all"],
            "notification_topics": ["ons", "topic", "list", "--compartment-id", compartment, "--all"],
        })
    elif name == "oci_governance_inventory":
        result = bundle({
            "budgets": ["budgets", "budget", "budget", "list", "--compartment-id", compartment, "--target-type", "ALL", "--all"],
            "quotas": ["limits", "quota", "list", "--compartment-id", compartment, "--lifecycle-state", "ACTIVE", "--all"],
            "tag_namespaces": ["iam", "tag-namespace", "list", "--compartment-id", compartment, "--include-subcompartments", "true", "--all"],
            "resources": ["search", "resource", "structured-search", "--query-text", "query all resources", "--limit", "1000"],
        })
    elif name == "oci_work_request_status":
        cli_args = arguments.get("arguments")
        error = validation_error(cli_args, read_only=True)
        path = command_path(cli_args) if not error else ()
        if error or not any(token in {"work-request", "work-requests"} for token in path):
            return text_result({"ok": False, "error": error or "command path must target an OCI work-request get or list operation"}, True)
        result = run_typed(cli_args)
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
            if not consume_approval(arguments.get("approval_token"), cli_args):
                plan = mutation_plan(cli_args)
                plan["ok"] = False
                plan["error"] = "Missing, expired, already-used, or command-mismatched approval token"
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
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "oci-tenancy", "version": "0.5.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params", {})
        name, arguments = params.get("name"), params.get("arguments", {})
        error = validate_tool_call(name, arguments)
        if error:
            result = text_result({"ok": False, "error": error}, True)
        else:
            try:
                result = call_tool(name, arguments)
            except ValueError as exc:
                result = text_result({"ok": False, "error": str(exc)}, True)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
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
