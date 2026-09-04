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
        self.assertTrue(all(tool["inputSchema"].get("additionalProperties") is False for tool in tools))

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

    def test_profile_and_debug_overrides_are_rejected(self):
        for flag in ("--profile", "--config-file", "--auth", "--endpoint", "--debug"):
            payload = self.payload(self.call("oci_execute_cli", {"arguments": ["compute", "instance", "list", flag, "bad"]}))
            self.assertFalse(payload["ok"])
            self.assertIn("may not override", payload["error"])

    def test_empty_stdout_is_an_error_not_a_false_success(self):
        payload = self.payload(self.call("oci_execute_cli", {"arguments": ["iam", "region", "list", "empty-success"]}))
        self.assertFalse(payload["ok"])
        self.assertIn("returned no stdout", payload["error"])

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


if __name__ == "__main__":
    unittest.main()
