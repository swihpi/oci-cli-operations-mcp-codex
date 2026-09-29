# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No changes yet.

## [0.6.0] - 2026-09-29

### Added

- Read-only native intelligence bundle for Cloud Advisor recommendations and
  resource actions, Cloud Guard problems, Vulnerability Scanning host results,
  and OS Management Hub managed-instance status.
- Focused network diagnostics, identity evidence, block/boot-volume recovery
  evidence, Monitoring MQL time-series queries, and load-balancer backend health.
- Compartment-scoped inventories for Containers, DevOps, Resource Manager,
  Functions/API Gateway, Streaming/Queue, Data Science, GoldenGate, and
  database services, with all command paths checked against the installed CLI.
- Explicit scope and limitation notes on the new evidence tools, resource-search
  coverage bounds, and normalized OCI service error fields when available.

### Changed

- Compartment discovery now requests the accessible tenancy subtree explicitly.
- Batch reads now run up to four CLI commands concurrently while retaining
  request order and partial-failure reporting.
- CLI output is bounded while the process runs; timeout and output overflow
  terminate its process group. A timed-out mutation reports an unknown outcome
  that requires read-only verification before retrying.

### Known limitations

- Native OCI Cost Anomaly Detection is not exposed by the validated installed
  CLI version. The existing Usage API anomaly tool remains a deterministic
  comparison, not a substitute for Oracle's native detector.
- Identity inventory does not establish effective access or MFA; backup
  inventory does not establish restore readiness; network configuration reads
  do not prove packet reachability. Partial and unauthorized reads remain
  visible in tool results.

## [0.5.0] - 2026-09-10

### Added

- Typed OCI Cost/Usage queries, dimension attribution, deterministic daily
  anomaly candidates, budgets, service limits, quota statements, resource
  availability, Resource Search, and constrained work-request status.
- Security, network, observability, and governance evidence bundles with
  explicit complete/partial coverage states.
- A private OCI Operations Console companion with tenancy discovery, resource
  exploration, deterministic health reports, scheduled read-only checks,
  approval-gated actions, and durable PostgreSQL report/action records.
- Deployment assets and operational design documentation for the console.
- Deterministic protocol, console, credential-scanning, and live read-smoke
  tests.
- GitHub Actions coverage for both MCP and Operations Console tests, plus
  monthly dependency-update proposals.

### Changed

- Expanded generic read and mutation support across OCI CLI product families.
- Improved result contracts with command duration, parsed data, truncation,
  work-request identifiers, and honest handling of successful empty output.
- Documented the division of responsibility between live tenancy evidence,
  official Oracle documentation, model interpretation, and human approval.

### Security

- Bound mutation approvals to the exact argument vector using random,
  single-use, five-minute tokens.
- Blocked profile, config, authentication, endpoint, proxy, certificate,
  defaults-file, debug, local setup/session, raw HTTP, `file://`, and local
  file-input/output overrides.
- Added response redaction for credential-like fields and a public-source scan
  for private keys, API fingerprints, tenancy/resource identifiers, local
  identity, and unreviewed binary assets.

[Unreleased]: https://github.com/swihpi/oci-cli-operations-mcp-codex/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/swihpi/oci-cli-operations-mcp-codex/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/swihpi/oci-cli-operations-mcp-codex/compare/52c93d0...v0.5.0
