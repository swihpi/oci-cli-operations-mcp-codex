#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import tempfile
import time
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
        self.assertEqual(self.request("initialize")["result"]["serverInfo"]["version"], "0.8.0")
        tools = self.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertTrue({"oci_cli_help", "oci_tenancy_summary", "oci_compute_inventory", "oci_scope_discovery", "oci_batch_read", "oci_plan_mutation", "oci_verify_cli", "oci_execute_cli"} <= names)
        self.assertTrue({"oci_cost_usage_summary", "oci_cost_usage_by_dimension", "oci_cost_anomaly_scan", "oci_budget_inventory", "oci_limits_overview", "oci_resource_availability", "oci_resource_search", "oci_security_posture", "oci_network_health", "oci_observability_inventory", "oci_governance_inventory", "oci_work_request_status"} <= names)
        self.assertTrue({"oci_native_intelligence", "oci_network_diagnostics", "oci_identity_evidence", "oci_recovery_evidence", "oci_metric_query", "oci_load_balancer_backend_health", "oci_service_inventory"} <= names)
        self.assertTrue({"oci_change_timeline", "oci_documented_checks", "oci_verify_outcome"} <= names)
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
            self.assertEqual(payload["evidence"]["source"], "live_oci_cli")
            self.assertTrue(payload["evidence"]["complete"])

    def test_read_only_fallback_runs_and_parses_json(self):
        payload = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "list", "--compartment-id", "x"]}))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"][0]["name"], "test-instance")

    def test_installed_cli_help_discovery_is_safe_and_precise(self):
        root = self.payload(self.call("oci_cli_help"))
        self.assertTrue(root["ok"])
        self.assertIn("Usage: oci", root["help"])
        path = self.payload(self.call("oci_cli_help", {"path": ["compute", "instance"]}))
        self.assertTrue(path["ok"])
        self.assertEqual(path["cli_path"], ["compute", "instance"])
        self.assertIn("compute instance", path["help"])
        invalid = self.payload(self.call("oci_cli_help", {"path": ["compute", "--profile"]}))
        self.assertFalse(invalid["ok"])
        missing = self.payload(self.call("oci_cli_help", {"path": ["definitely-not-a-service"]}))
        self.assertFalse(missing["ok"])

    def test_mutation_path_is_preflighted_before_approval(self):
        for command in (["definitely-not-a-service", "create"],
                        ["compute", "instance", "start", "--instance-id", "x"],
                        ["compute", "instance"]):
            invalid = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
            self.assertFalse(invalid["ok"])
            self.assertNotIn("approval_token", invalid)
            self.assertIn("preflight", invalid)

    def test_sensitive_response_fields_are_redacted(self):
        payload = self.payload(self.call("oci_execute_cli", {"arguments": ["example", "resource", "list"]}))
        self.assertEqual(payload["data"]["metadata"]["ssh_authorized_keys"], "[REDACTED]")

    def test_execute_preserves_failed_preflight_reason(self):
        for command in (["definitely-not-a-service", "create"],
                        ["compute", "instance"]):
            result = self.payload(self.call("oci_execute_cli", {"arguments": command}))
            self.assertFalse(result["ok"])
            self.assertNotIn("approval_token", result)
            self.assertIn("complete operation path", result["error"])
            self.assertIn("preflight", result)

    def test_mutation_requires_exact_token(self):
        first = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "action", "--instance-id", "x", "--action", "START"]}))
        self.assertTrue(first["confirmation_required"])
        wrong = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "action", "--instance-id", "x", "--action", "STOP"], "approval_token": first["approval_token"]}))
        self.assertTrue(wrong["confirmation_required"])

    def test_approval_token_is_random_single_use_and_exact(self):
        command = ["compute", "instance", "action", "--instance-id", "x", "--action", "START"]
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

    def test_credential_returning_paths_and_output_overrides_are_rejected(self):
        commands = [
            ["secrets", "secret-bundle", "get", "--secret-id", "x"],
            ["secrets", "secret-bundle", "get-secret-bundle-by-name", "--secret-name", "x"],
            ["compute", "instance", "get-windows-initial-creds", "--instance-id", "x"],
            ["iam", "customer-secret-key", "create", "--user-id", "x"],
            ["iam", "smtp-credential", "create", "--user-id", "x"],
            ["iam", "auth-token", "create", "--user-id", "x"],
            ["compute", "instance", "list", "--output", "table"],
            ["compute", "instance", "list", "--raw-output"],
            ["secrets", "secret-bundle", "--region", "eu-frankfurt-1", "get", "--secret-id", "x"],
            ["compute", "instance", "list", "--query", "data[0].secret"],
            ["compute", "instance", "list", "--help"],
            ["--latest-version"],
        ]
        for command in commands:
            result = self.payload(self.call("oci_execute_cli", {"arguments": command}))
            self.assertFalse(result["ok"], command)

    def test_unparsed_or_failed_stdout_is_not_exposed(self):
        for marker in ("--text-output", "--failed-stdout"):
            result = self.payload(self.call("oci_execute_cli", {"arguments": ["iam", "region", "list", marker]}))
            self.assertFalse(result["ok"])
            self.assertNotIn("credential-content-that-must-not-leak", json.dumps(result))

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
        self.assertIn("OMITTED", result["stdout"])
        self.assertTrue(result["outcome_unknown"])

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
        self.assertTrue(scope["compartment_scope"]["subtree"])
        self.assertIn("--compartment-id-in-subtree", scope["results"]["compartments"]["command"])
        batch = self.payload(self.call("oci_batch_read", {"commands": [["compute", "instance", "list"], ["network", "vcn", "list"]]}))
        self.assertTrue(batch["ok"])
        self.assertEqual(len(batch["results"]), 2)

    def test_batch_read_is_parallel_ordered_and_partial_on_failure(self):
        commands = [["compute", "instance", "list", "--delay", str(index)] for index in range(4)]
        started = time.monotonic()
        batch = self.payload(self.call("oci_batch_read", {"commands": commands}))
        self.assertLess(time.monotonic() - started, 1.7)
        self.assertEqual(len(batch["results"]), 4)
        self.assertTrue(batch["complete"])
        self.assertEqual([entry["command"][-1] for entry in batch["results"]], ["0", "1", "2", "3"])
        partial = self.payload(self.call("oci_batch_read", {"commands": [["iam", "region", "list"], ["iam", "region", "get", "failure"]]}))
        self.assertFalse(partial["ok"])
        self.assertTrue(partial["partial"])

    def test_large_cli_output_is_stopped_with_explicit_error(self):
        result = self.payload(self.call("oci_execute_cli", {"arguments": ["iam", "region", "list", "--large-output"]}))
        self.assertFalse(result["ok"])
        self.assertTrue(result["truncated"])
        self.assertIn("byte limit", result["error"])
        self.assertFalse(result["outcome_unknown"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 1_000_000)

    def test_truncated_mutation_has_unknown_outcome_and_consumed_approval(self):
        command = ["compute", "instance", "action", "--instance-id", "x",
                   "--action", "STOP", "--large-output"]
        plan = self.payload(self.call("oci_plan_mutation", {"arguments": command}))
        request = {"arguments": command, "approval_token": plan["approval_token"]}
        result = self.payload(self.call("oci_execute_cli", request))
        self.assertFalse(result["ok"])
        self.assertTrue(result["truncated"])
        self.assertTrue(result["outcome_unknown"])
        replay = self.payload(self.call("oci_execute_cli", request))
        self.assertFalse(replay["ok"])
        self.assertIn("already-used", replay["error"])

    def test_service_error_is_normalized_without_retrying_mutation(self):
        failure = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "get", "--service-error"]}))
        self.assertFalse(failure["ok"])
        self.assertEqual(failure["oci_error"]["http_status"], 429)
        self.assertEqual(failure["oci_error"]["oci_code"], "TooManyRequests")
        self.assertTrue(failure["oci_error"]["retryable_read"])

    def test_mutation_plan_and_read_only_verification(self):
        plan = self.payload(self.call("oci_plan_mutation", {"arguments": ["compute", "instance", "action", "--instance-id", "x", "--action", "STOP"]}))
        self.assertTrue(plan["confirmation_required"])
        verify = self.payload(self.call("oci_verify_cli", {"arguments": ["compute", "instance", "get", "--instance-id", "x"]}))
        self.assertTrue(verify["ok"])
        rejected = self.payload(self.call("oci_verify_cli", {"arguments": ["compute", "instance", "action", "--instance-id", "x", "--action", "STOP"]}))
        self.assertFalse(rejected["ok"])

    def test_explicit_outcome_verification_passes_fails_and_validates(self):
        arguments = ["compute", "instance", "get", "--instance-id", "instance-test"]
        verified = self.payload(self.call("oci_verify_outcome", {"arguments": arguments,
            "expectations": [{"pointer": "/0/state", "operator": "equals", "expected": "RUNNING"}]}))
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["verification_status"], "verified")
        failed = self.payload(self.call("oci_verify_outcome", {"arguments": arguments,
            "expectations": [{"pointer": "/0/state", "operator": "equals", "expected": "STOPPED"}]}))
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["verification_status"], "failed")
        invalid = self.payload(self.call("oci_verify_outcome", {"arguments": arguments,
            "expectations": [{"pointer": "/0/state", "operator": "regex", "expected": ".*"}]}))
        self.assertFalse(invalid["ok"])

    def test_change_timeline_is_bounded_filtered_and_non_causal(self):
        timeline = self.payload(self.call("oci_change_timeline", {
            "start_time": "2026-09-30T07:00:00Z", "end_time": "2026-09-30T10:00:00Z",
            "resource_id": "instance-test", "limit": 10}))
        self.assertTrue(timeline["ok"])
        self.assertEqual(timeline["event_count"], 1)
        self.assertEqual(timeline["events"][0]["event-name"], "UpdateInstance")
        self.assertIn("does not establish causation", timeline["interpretation"])
        too_wide = self.payload(self.call("oci_change_timeline", {
            "start_time": "2026-09-01T00:00:00Z", "end_time": "2026-09-30T00:00:00Z"}))
        self.assertFalse(too_wide["ok"])

    def test_documented_checks_keep_guidance_and_evidence_separate(self):
        result = self.payload(self.call("oci_documented_checks"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], {"passed": 2, "review_required": 1, "unknown": 0})
        public = next(check for check in result["checks"] if check["check_id"] == "public_ingress_review")
        self.assertEqual(public["status"], "review_required")
        self.assertTrue(public["documentation"].startswith("https://docs.oracle.com/"))
        self.assertEqual(public["evidence"]["source"], "live_oci_cli")

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

    def test_native_evidence_and_metric_tools(self):
        for name in ("oci_native_intelligence", "oci_network_diagnostics", "oci_identity_evidence", "oci_recovery_evidence"):
            result = self.payload(self.call(name))
            self.assertTrue(result["complete"], name)
            self.assertIn("limitations", result, name)
        metrics = self.payload(self.call("oci_metric_query", {"namespace": "oci_computeagent", "query_text": "CpuUtilization[1m].mean()",
                                                              "start_time": "2026-09-28T00:00:00Z", "end_time": "2026-09-28T01:00:00Z"}))
        self.assertTrue(metrics["ok"])
        self.assertIn("--query-text", metrics["command"])
        invalid = self.payload(self.call("oci_metric_query", {"namespace": "oci_computeagent", "query_text": "CpuUtilization[1m].mean()",
                                                              "start_time": "2026-09-28", "end_time": "2026-09-27"}))
        self.assertFalse(invalid["ok"])
        health = self.payload(self.call("oci_load_balancer_backend_health", {"load_balancer_id": "lb-test", "backend_set_name": "web"}))
        self.assertTrue(health["ok"])
        family = self.payload(self.call("oci_service_inventory", {"family": "containers"}))
        self.assertTrue(family["complete"])
        self.assertEqual(set(family["results"]), {"clusters", "node_pools"})
        search = self.payload(self.call("oci_resource_search", {"query_text": "query all resources", "limit": 1}))
        self.assertIsNone(search["coverage"]["complete"])


if __name__ == "__main__":
    unittest.main()
