# Operations console delivery ledger

This is an independent, OCI-hosted companion to OCI CLI Operations MCP (Codex).
It does not replace the existing stdio plugin or publish tenancy data to GitHub.

## Accepted scope

- Bright Redwood-inspired operational UI, light/dark modes, accessible controls.
- Authenticated tenancy discovery, resource explorer, explicit coverage gaps.
- Deterministic network/security/identity/Compute/recovery/cost checks.
- Focused official Oracle documentation retrieval with timestamps and citations.
- Optional model-backed explanation; no model is required for routine checks.
- Server-owned command schemas plus a tokenized generic OCI CLI route, session-bound expiring single-use approvals,
  precondition checks, audit records, asynchronous job history.
- Private VM deployment, preserved existing services, no signing keys in browser.
- Scheduled read-only checks, baseline comparisons, no automatic remediation.

## Delivery gates

1. Read-only readiness and upstream test baseline.
2. Local complete operational slice with sample and live read-only modes.
3. Security and failure-path tests; no unrestricted browser-to-shell endpoint.
4. Supported mutations tested using fakes, then explicitly designated OCI resources.
5. Separately approved execution identity and private deployment specification.
6. Live browser tests, restart/recovery checks, source-only commit.

## Current boundaries

Compute START, SOFTSTOP and SOFTRESET receive resource-specific preconditions
and read-after-write checks. The advanced command workspace can execute normal
OCI CLI service commands, including create/update/delete, only after a five
minute single-use server approval. It rejects shell syntax, credential/profile/
endpoint/debug overrides, file:// indirections, and protected-host targeting.
Generic results are deliberately "submitted, unverified" until a service-specific
verification contract exists; they are never called successful remediation.
Instance-principal IAM policies require approval of their exact scope. Personal
administrator signing keys must not be copied to the web host as an implicit step.
No claim of whole-tenancy coverage is made when discovery fails or a service is
not implemented. No telemetry is represented as a healthy result.

Every completed health report and consequential action lifecycle is retained in
the VM's local PostgreSQL database, in addition to short-lived operational state.

## Design references

- https://blogs.oracle.com/cloud-infrastructure/introducing-redwood-theming-for-oracle-cloud
- https://docs.oracle.com/en/middleware/developer-tools/jet/16/develop/use-css-and-themes-oracle-jet-apps.html

Oracle Sans is preferred when installed locally; system sans-serif is the fallback.
No proprietary fonts or Oracle logos are redistributed without a verified license.
