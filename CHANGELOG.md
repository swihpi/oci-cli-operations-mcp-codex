# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No changes yet.

## [0.8.0] - 2026-09-30

### Added

- Provenance envelopes on typed live OCI reads: source, UTC observation time,
  configured profile, redacted command, and completeness.
- `oci_change_timeline` for a bounded, optionally resource-filtered OCI Audit
  timeline. It treats preceding changes as leads rather than proof of causation
  and discloses its first-page coverage boundary.
- `oci_documented_checks` with three reviewed Oracle-guided contracts for
  public ingress, Cloud Guard enablement, and logging presence. Results are
  `passed`, `review_required`, or `unknown`, with live evidence kept separate
  from documented guidance.
- `oci_verify_outcome` for deterministic read-after-write verification using
  bounded JSON Pointer assertions. It distinguishes `verified`, `failed`, and
  `unknown` outcomes.

### Changed

- Updated the OCI tenancy and documentation skills to route incident timelines,
  maintained checks, and assertion-based verification without overstating
  causality, compliance, or application health.

### Known limitations

- Audit timeline retrieval uses one CLI page because the installed Audit CLI
  exposes pagination but no `--limit` option; the MCP applies its client limit
  after redaction and never claims complete event coverage.
- The documented check catalog is deliberately small and reviewed. It does not
  replace Cloud Guard, Security Zones, compliance assessment, or workload-level
  testing.

## [0.7.1] - 2026-09-30

### Fixed

- Preserve command-path preflight failures in `oci_execute_cli` rather than
  replacing them with a misleading approval-token error.
- Mark interrupted mutations as outcome-unknown on output overflow as well as
  timeout. A killed CLI process does not prove the cloud operation was cancelled;
  verify resource state before considering another action. Approval remains single-use.
- Added regression tests for both cases, including read-only overflow and
  rejection of approval replay after a truncated mutation.

## [0.7.0] - 2026-09-30

### Added

- `oci_cli_help` reads the installed CLI's root, service, group, or operation
  help without making a tenancy API request. Operators can confirm actual
  command paths and options before forming an unfamiliar OCI command.
- Mutation planning checks the command path against local CLI help before
  issuing an approval token. This is a syntax preflight, not an IAM, capacity,
  configuration, or outcome guarantee.

### Security

- Failed or non-JSON CLI stdout is omitted from MCP results instead of being
  echoed unparsed. Timeout and overflow retain only an explicit omission marker.
- Generic calls reject output/query/interactive overrides that could bypass
  structured redaction. Known credential-returning reads and one-time
  credential-creation operations require a separate reviewed workflow.

### Known limitations

- CLI help cannot prove an option value is valid, a service is available in the
  selected region, IAM permits access, or a planned change will succeed.
- These controls do not make arbitrary OCI output inherently safe or establish
  complete feature parity with every OCI product. Unknown secret-bearing
  response shapes still require careful review before adding typed support.

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

[Unreleased]: https://github.com/swihpi/oci-cli-operations-mcp-codex/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/swihpi/oci-cli-operations-mcp-codex/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/swihpi/oci-cli-operations-mcp-codex/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/swihpi/oci-cli-operations-mcp-codex/compare/52c93d0...v0.5.0
