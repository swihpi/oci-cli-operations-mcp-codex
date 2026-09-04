# Contributing

Contributions must be credential-free and runnable with the fake OCI CLI test
fixture. Never commit local OCI configuration, credentials, wallet files,
private keys, API-key fingerprints, tenancy/user/resource OCIDs, public IPs,
or live CLI output.

Run `python3 tests/test_protocol.py -v` before opening a pull request. New
MCP tools should return structured results, preserve mutation approval rules,
redact sensitive response fields, and include deterministic tests.
