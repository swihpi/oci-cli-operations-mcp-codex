#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "oci_mcp_server.py"
FAKE = ROOT / "tests" / "fake_oci.py"


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        config_dir = pathlib.Path(cls.home.name) / ".oci"
        config_dir.mkdir()
        (config_dir / "config").write_text(
            "[DEFAULT]\n"
            "tenancy=synthetic-test-tenancy\n"
            "region=eu-frankfurt-1\n",
            encoding="utf-8",
        )
        env = os.environ | {
            "HOME": cls.home.name,
            "OCI_CLI_BINARY": str(FAKE),
            "OCI_CLI_PROFILE": "DEFAULT",
        }
        cls.process = subprocess.Popen(["python3", str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.home.cleanup()

    def request(self, method, params=None):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": method + str(id(self)), "method": method, "params": params or {}}) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def call(self, tool, arguments=None):
        return self.request("tools/call", {"name": tool, "arguments": arguments or {}})["result"]

    def payload(self, result):
        return json.loads(result["content"][0]["text"])

    def test_initialization_and_tool_contract(self):
        tools = self.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertTrue({"oci_tenancy_summary", "oci_compute_inventory", "oci_scope_discovery", "oci_batch_read", "oci_plan_mutation", "oci_verify_cli", "oci_execute_cli"} <= names)
        self.assertTrue({"oci_cost_usage_summary", "oci_cost_usage_by_dimension", "oci_cost_anomaly_scan", "oci_budget_inventory", "oci_limits_overview", "oci_resource_availability", "oci_resource_search", "oci_security_posture", "oci_network_health", "oci_observability_inventory", "oci_governance_inventory", "oci_work_request_status"} <= names)
        self.assertTrue(all(tool["inputSchema"].get("additionalProperties") is False for tool in tools))

    def test_server_enforces_tool_contract_not_only_advertises_it(self):
        unexpected = self.payload(self.call("oci_tenancy_summary", {"ignored": "value"}))
        self.assertFalse(unexpected["ok"])
        self.assertIn("unexpected", unexpected["error"])
        wrong_type = self.payload(self.call("oci_resource_search", {"query_text": "query all resources", "limit": "ten"}))
        self.assertFalse(wrong_type["ok"])
        self.assertIn("integer", wrong_type["error"])
        missing = self.payload(self.call("oci_cost_usage_summary", {"granularity": "DAILY"}))
        self.assertFalse(missing["ok"])
        self.assertIn("missing required", missing["error"])

    def test_typed_tools_return_structured_data(self):
        for tool in ("oci_tenancy_summary", "oci_list_compartments", "oci_compute_inventory", "oci_network_inventory", "oci_autonomous_database_inventory", "oci_list_buckets"):
            payload = self.payload(self.call(tool))
            self.assertTrue(payload["ok"], tool)
            self.assertIn("data", payload, tool)
            self.assertIn("duration_ms", payload, tool)

    def test_read_only_fallback_runs_and_parses_json(self):
        payload = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "list", "--compartment-id", "x"]}))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"][0]["name"], "test-instance")

    def test_sensitive_response_fields_are_redacted(self):
        payload = self.payload(self.call("oci_execute_cli", {"arguments": ["example", "resource", "list"]}))
        self.assertEqual(payload["data"]["metadata"]["ssh_authorized_keys"], "[REDACTED]")

    def test_mutation_requires_exact_token(self):
        first = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "start", "--instance-id", "x"]}))
        self.assertTrue(first["confirmation_required"])
        wrong = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "stop", "--instance-id", "x"], "approval_token": first["approval_token"]}))
        self.assertTrue(wrong["confirmation_required"])

    def test_approval_token_is_random_single_use_and_exact(self):
        command = ["compute", "instance", "start", "--instance-id", "x"]
        first = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
        second = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
        self.assertNotEqual(first["approval_token"], second["approval_token"])
        executed = self.payload(self.call("oci_execute_cli", {"arguments": command, "approval_token": first["approval_token"]}))
        self.assertTrue(executed["ok"])
        replay = self.payload(self.call("oci_execute_cli", {"arguments": command, "approval_token": first["approval_token"]}))
        self.assertFalse(replay["ok"])
        self.assertIn("already-used", replay["error"])

    def test_profile_and_debug_overrides_are_rejected(self):
        for flag in ("--profile", "--config-file", "--auth", "--endpoint", "--debug", "--proxy", "--cli-rc-file", "--defaults-file", "--cert-bundle"):
            payload = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "list", flag, "bad"]}))
            self.assertFalse(payload["ok"])
            self.assertIn("may not override", payload["error"])

    def test_local_file_and_control_character_inputs_are_rejected(self):
        for value in ("file:///etc/passwd", "FILE:///tmp/input.json", "bad\nvalue"):
            payload = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "list", "--from-json", value]}))
            self.assertFalse(payload["ok"])

    def test_raw_request_local_admin_and_file_flags_are_rejected(self):
        cases = [
            ["raw-request", "--http-method", "GET", "--target-uri", "https://example.invalid"],
            ["setup", "config"],
            ["session", "authenticate"],
            ["os", "object", "put", "--file", "/etc/passwd"],
            ["os", "object", "get", "--output-file=/tmp/object"],
        ]
        for command in cases:
            payload = self.payload(self.call("oci_execute_cli", {"arguments": command}))
            self.assertFalse(payload["ok"], command)

    def test_read_classifier_uses_command_path_not_arbitrary_values(self):
        command = ["usage-api", "usage-summary", "request-summarized-usages", "--tenant-id", "t", "--time-usage-started", "2026-09-01", "--time-usage-ended", "2026-09-03", "--granularity", "DAILY"]
        read = self.payload(self.call("oci_batch_read", {"commands": [command]}))
        self.assertTrue(read["ok"])
        mutation_with_list_value = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "terminate", "--instance-id", "list"]}))
        self.assertTrue(mutation_with_list_value["confirmation_required"])

    def test_sensitive_command_values_are_redacted_but_execute(self):
        command = ["db", "system", "update", "--admin-password", "do-not-echo"]
        plan = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
        self.assertNotIn("do-not-echo", json.dumps(plan))
        self.assertIn("[REDACTED]", json.dumps(plan))
        result = self.payload(self.call("oci_execute_cli", {"arguments": command, "approval_token": plan["approval_token"]}))
        self.assertTrue(result["ok"])
        self.assertNotIn("do-not-echo", json.dumps(result))

    def test_sensitive_values_are_redacted_from_cli_errors(self):
        command = ["db", "system", "update", "--admin-password", "do-not-echo", "echo-secret-error"]
        plan = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
        result = self.payload(self.call("oci_execute_cli", {"arguments": command, "approval_token": plan["approval_token"]}))
        self.assertFalse(result["ok"])
        self.assertNotIn("do-not-echo", json.dumps(result))
        self.assertIn("[REDACTED]", result["stderr"])

    def test_sensitive_values_are_redacted_on_timeout(self):
        command = ["db", "system", "update", "--admin-password", "do-not-echo", "timeout-secret"]
        plan = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
        result = self.payload(self.call("oci_execute_cli", {"arguments": command, "approval_token": plan["approval_token"], "timeout_seconds": 1}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "OCI CLI timed out")
        self.assertNotIn("do-not-echo", json.dumps(result))
        self.assertIn("[REDACTED]", result["stdout"])

    def test_empty_stdout_is_an_error_not_a_false_success(self):
        payload = self.payload(self.call("oci_execute_cli", {"arguments": ["iam", "region", "get", "--empty-success"]}))
        self.assertFalse(payload["ok"])
        self.assertIn("returned no stdout", payload["error"])

    def test_empty_list_stdout_is_explicit_empty_inventory(self):
        payload = self.payload(self.call("oci_execute_cli", {"arguments": ["iam", "region", "list", "--empty-success"]}))
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["empty"])
        self.assertEqual(payload["data"], [])

    def test_empty_mutation_stdout_is_accepted_but_requires_verification(self):
        command = ["compute", "instance", "terminate", "--instance-id", "x", "--empty-success"]
        plan = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
        result = self.payload(self.call("oci_execute_cli", {"arguments": command, "approval_token": plan["approval_token"]}))
        self.assertTrue(result["ok"])
        self.assertTrue(result["accepted_without_payload"])
        self.assertIsNone(result["data"])
        self.assertIn("verify", result["message"])

    def test_scope_discovery_and_batch_read_are_structured(self):
        scope = self.payload(self.call("oci_scope_discovery"))
        self.assertTrue(scope["ok"])
        self.assertEqual(set(scope["results"]), {"regions", "availability_domains", "compartments"})
        batch = self.payload(self.call("oci_batch_read", {"commands": [["compute", "instance", "list"], ["network", "vcn", "list"]]}))
        self.assertTrue(batch["ok"])
        self.assertEqual(len(batch["results"]), 2)

    def test_mutation_plan_and_read_only_verification(self):
        plan = self.payload(self.call("oci_plan_mutation", {"arguments": ["compute", "instance", "stop", "--instance-id", "x"]}))
        self.assertTrue(plan["confirmation_required"])
        verify = self.payload(self.call("oci_verify_cli", {"arguments": ["compute", "instance", "get", "--instance-id", "x"]}))
        self.assertTrue(verify["ok"])
        rejected = self.payload(self.call("oci_verify_cli", {"arguments": ["compute", "instance", "stop", "--instance-id", "x"]}))
        self.assertFalse(rejected["ok"])

    def test_cost_usage_budget_limits_and_anomaly_tools(self):
        window = {"time_usage_started": "2026-09-01", "time_usage_ended": "2026-09-03", "granularity": "DAILY"}
        self.assertTrue(self.payload(self.call("oci_cost_usage_summary", window))["ok"])
        self.assertTrue(self.payload(self.call("oci_cost_usage_by_dimension", window | {"dimension": "service"}))["ok"])
        anomaly = self.payload(self.call("oci_cost_anomaly_scan", {"time_usage_started": "2026-09-01", "time_usage_ended": "2026-09-03", "dimension": "service", "threshold_percent": 50, "minimum_cost_delta": 1}))
        self.assertEqual(anomaly["anomalies"][0]["dimension"], "Compute")
        self.assertTrue(self.payload(self.call("oci_budget_inventory"))["ok"])
        self.assertTrue(self.payload(self.call("oci_limits_overview", {"service_name": "compute"}))["ok"])
        availability = self.payload(self.call("oci_resource_availability", {"service_name": "compute", "limit_name": "standard-e4-core-count"}))
        self.assertEqual(availability["data"]["data"]["available"], 3)

    def test_cost_usage_time_window_validation(self):
        cases = [
            {"time_usage_started": "bad", "time_usage_ended": "2026-09-03", "granularity": "DAILY"},
            {"time_usage_started": "2026-09-03", "time_usage_ended": "2026-09-01", "granularity": "DAILY"},
            {"time_usage_started": "2026-09-01", "time_usage_ended": "2026-09-03", "granularity": "HOURLY"},
            {"time_usage_started": "2026-09-02", "time_usage_ended": "2026-10-01", "granularity": "MONTHLY"},
        ]
        for arguments in cases:
            payload = self.payload(self.call("oci_cost_usage_summary", arguments))
            self.assertFalse(payload["ok"], arguments)

    def test_health_governance_search_and_work_request_tools(self):
        for name in ("oci_security_posture", "oci_network_health", "oci_observability_inventory", "oci_governance_inventory"):
            payload = self.payload(self.call(name))
            self.assertTrue(payload["ok"], name)
            self.assertIn("complete", payload, name)
        self.assertTrue(self.payload(self.call("oci_resource_search", {"query_text": "query all resources"}))["ok"])
        work = self.payload(self.call("oci_work_request_status", {"arguments": ["compute", "work-request", "get", "--work-request-id", "wr-test"]}))
        self.assertEqual(work["data"]["data"]["status"], "SUCCEEDED")
        self.assertEqual(work["work_request_ids"], ["wr-test"])


if __name__ == "__main__":
    unittest.main()
