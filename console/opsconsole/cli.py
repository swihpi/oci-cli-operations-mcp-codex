"""Typed OCI worker. Browser input never becomes a shell command.

This companion deliberately does not trust the desktop MCP's verb classifier or
deterministic approval token as a web authorization boundary.
"""
import json
import os
import re
import signal
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass


class InvalidOperation(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"ocid[0-9]+\.[a-z0-9._-]{5,240}", value):
        raise InvalidOperation("A valid OCI resource identifier is required")
    return value


def region_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z]{2}-[a-z0-9-]+-[0-9]+", value):
        raise InvalidOperation("Invalid OCI region")
    return value


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if any(p in k.lower().replace("-", "_") for p in
                ("password", "secret", "private_key", "token", "authorized_keys", "metadata"))
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass(frozen=True)
class Command:
    path: tuple
    required: tuple = ()
    fixed: tuple = ()


READS = {
    "regions": Command(("iam", "region-subscription", "list")),
    "compartments": Command(("iam", "compartment", "list"), ("compartment-id",),
                            ("--compartment-id-in-subtree", "true", "--access-level", "ACCESSIBLE", "--all")),
    "instances": Command(("compute", "instance", "list"), ("compartment-id",), ("--all",)),
    "instance": Command(("compute", "instance", "get"), ("instance-id",)),
    "vnics": Command(("compute", "instance", "list-vnics"), ("instance-id",)),
    "vcns": Command(("network", "vcn", "list"), ("compartment-id",), ("--all",)),
    "subnets": Command(("network", "subnet", "list"), ("compartment-id",), ("--all",)),
    "security_lists": Command(("network", "security-list", "list"), ("compartment-id",), ("--all",)),
    "nsgs": Command(("network", "nsg", "list"), ("compartment-id",), ("--all",)),
    "routes": Command(("network", "route-table", "list"), ("compartment-id",), ("--all",)),
    "volumes": Command(("bv", "volume", "list"), ("compartment-id",), ("--all",)),
    "backups": Command(("bv", "backup", "list"), ("compartment-id",), ("--all",)),
    "boot_backups": Command(("bv", "boot-volume-backup", "list"), ("compartment-id",), ("--all",)),
    "databases": Command(("db", "autonomous-database", "list"), ("compartment-id",), ("--all",)),
    "policies": Command(("iam", "policy", "list"), ("compartment-id",), ("--all",)),
    "users": Command(("iam", "user", "list"), ("compartment-id",), ("--all",)),
    "cloud_guard": Command(("cloud-guard", "configuration", "get"), ("compartment-id",)),
    "log_groups": Command(("logging", "log-group", "list"), ("compartment-id",), ("--all",)),
    "alarms": Command(("monitoring", "alarm", "list"), ("compartment-id",), ("--all",)),
    "budgets": Command(("budgets", "budget", "budget", "list"), ("compartment-id",), ("--target-type", "ALL", "--all")),
}

BLOCKED_GENERIC_ARGUMENTS = {"--auth", "--config-file", "--profile", "--endpoint", "--debug", "--cli-rc-file", "--defaults-file", "--proxy", "-d"}
FILE_ARGUMENT_PREFIXES = ("file://",)


def generic_arguments(command):
    """Parse a normal OCI CLI command without invoking a shell.

    The console supports every installed service command whose inputs can be
    represented as ordinary arguments. Credential, endpoint, debug and file
    indirections are intentionally server-owned or rejected.
    """
    if not isinstance(command, str) or not 1 <= len(command) <= 8000:
        raise InvalidOperation("Enter an OCI command of 1–8000 characters")
    if "\x00" in command or "\n" in command or "\r" in command:
        raise InvalidOperation("Command may not contain control characters")
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError as exc:
        raise InvalidOperation("Command quoting is invalid") from exc
    if arguments and arguments[0] == "oci": arguments = arguments[1:]
    if not arguments or len(arguments) > 120 or any(not 1 <= len(item) <= 2048 for item in arguments):
        raise InvalidOperation("Command must contain 1–120 ordinary arguments")
    if any(item in BLOCKED_GENERIC_ARGUMENTS or item.startswith(tuple(flag+"=" for flag in BLOCKED_GENERIC_ARGUMENTS)) for item in arguments):
        raise InvalidOperation("Authentication, profile, endpoint, proxy, config and debug flags are server-owned")
    if any(item.startswith(FILE_ARGUMENT_PREFIXES) for item in arguments):
        raise InvalidOperation("file:// input is not accepted by the web console; use supported forms or the desktop MCP")
    if any("\x00" in item or "\n" in item or "\r" in item for item in arguments):
        raise InvalidOperation("Command arguments may not contain control characters")
    return arguments


def read_arguments(operation, parameters, region):
    if operation not in READS:
        raise InvalidOperation("Unsupported read operation; arbitrary CLI input is not accepted")
    spec = READS[operation]
    if set(parameters) != set(spec.required):
        raise InvalidOperation("Unexpected or missing operation parameters")
    result = list(spec.path)
    for name in spec.required:
        result += ["--" + name, identifier(parameters[name])]
    return result + list(spec.fixed) + ["--region", region_name(region)]


def power_arguments(action, instance_id, region, etag):
    if action not in {"START", "SOFTSTOP", "SOFTRESET"}:
        raise InvalidOperation("Unsupported power action")
    if not isinstance(etag, str) or not re.fullmatch(r"[a-zA-Z0-9._:/+=-]{1,200}", etag):
        raise InvalidOperation("A valid live ETag is required")
    return ["compute", "instance", "action", "--instance-id", identifier(instance_id),
            "--action", action, "--if-match", etag, "--region", region_name(region)]


class CLI:
    def __init__(self, binary="oci", profile="DEFAULT", auth="api_key", timeout=45):
        if auth not in {"api_key", "instance_principal"}:
            raise ValueError("Unsupported authentication method")
        self.binary, self.profile, self.auth, self.timeout = binary, profile, auth, timeout

    def read(self, operation, parameters, region):
        arguments = read_arguments(operation, parameters, region)
        result = self._run(arguments)
        if result.get("error") == "Empty CLI output; coverage unknown" and "--all" in arguments:
            # Some OCI CLI releases print nothing for --all with zero rows.
            # Prove emptiness with a bounded independent read; never infer it.
            probe = self._run([a for a in arguments if a != "--all"] + ["--limit", "1"])
            payload = probe.get("data")
            if probe.get("ok") and isinstance(payload, dict) and payload.get("data") == [] and not payload.get("opc-next-page"):
                return dict(probe, empty_confirmed=True, note="Explicit empty JSON confirmed by bounded read after blank --all output")
        return result

    def power(self, action, instance_id, region, etag):
        return self._run(power_arguments(action, instance_id, region, etag), mutation=True)

    def generic(self, command):
        return self._run(generic_arguments(command), mutation=True)

    def _run(self, arguments, mutation=False):
        command = [self.binary, "--output", "json", "--no-retry", "--connection-timeout", "10",
                   "--read-timeout", "30", "--auth", self.auth]
        if self.auth == "api_key":
            command += ["--profile", self.profile]
        command += arguments
        # Do not inherit proxy, endpoint, debug, auto-prompt, or API-key env overrides.
        environment = {k: os.environ[k] for k in ("HOME", "PATH", "LANG", "LC_ALL") if k in os.environ}
        # OCI CLI treats even the string "False" as enabling auto-prompt.
        # Omit this variable entirely so unattended commands cannot enter a REPL.
        start = time.monotonic()
        base = {"observed_at": time.time(), "command": ["oci", *arguments]}
        try:
            # Temporary output files bound memory; kill the process group on timeout
            # or excess output rather than collecting an unbounded communicate().
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                           env=environment, start_new_session=True)
                failure = None
                while process.poll() is None:
                    if time.monotonic() - start > self.timeout:
                        failure = "CLI timeout; inspect resource state before any retry" if mutation else "CLI timeout"
                    if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 2_000_000:
                        failure = "CLI output limit exceeded; observation incomplete"
                    if failure:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        break
                    time.sleep(0.025)
                process.wait()
                if failure:
                    return dict(base, ok=False, error=failure, uncertain=mutation)
                if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 2_000_000:
                    return dict(base, ok=False, error="CLI output limit exceeded", uncertain=mutation)
                out.seek(0)
                content = out.read().decode("utf-8", "replace")
                if process.returncode:
                    # Never expose raw stderr which may contain a credential response.
                    err.seek(0)
                    error_text = err.read().decode("utf-8", "replace")
                    try:
                        service_error = json.loads(error_text[error_text.index("{"):])
                        code = str(service_error.get("code", "CLI_ERROR"))[:80]
                    except (ValueError, TypeError):
                        code = "CLI_ERROR"
                    return dict(base, ok=False, exit_code=process.returncode, error=code, uncertain=mutation)
                if not content.strip():
                    return dict(base, ok=False, error="Empty CLI output; coverage unknown", uncertain=mutation)
                data = json.loads(content)
                return dict(base, ok=True, data=redact(data), duration_ms=int((time.monotonic()-start)*1000))
        except (OSError, ValueError):
            return dict(base, ok=False, error="CLI unavailable or returned invalid JSON", uncertain=mutation)
