# OCI value and coverage review

The console is not intended to rebuild the Oracle Cloud Console. OCI already has
strong native services for broad recommendations, anomaly detection, network
configuration analysis and fleet patching. This application adds value only
where it joins those systems to current tenancy evidence, operational intent,
documentation, accountable action approval and durable evidence.

## What OCI already does well — integrate, do not duplicate

| OCI capability | Native strength | Console role |
|---|---|---|
| Cloud Advisor | Tenancy-wide daily cost, performance and availability recommendations; some recommendations can be implemented natively. | Ingest recommendations, link each to resource dependencies, owner/tags, prior changes, approval and post-change evidence. Do not invent a second right-sizing engine. |
| Cost Anomaly Detection | Daily cost anomalies, resource-change insights and alerts; monitors need 60 days of history before activation. | Put anomaly, budget, tags, deployment/audit changes and an approved remediation path in one investigation. Display ingestion age and monitor readiness. |
| Cloud Guard / Security Zones / Vulnerability Scanning | Managed detection, posture rules and service-specific findings. | Correlate a finding to exposure paths, resource inventory, audit changes, logging coverage, stated workload intent and accountable remediation. |
| Network Path Analyzer | Configuration-path analysis; it does not send application traffic. | Orchestrate topology review with DNS, NSG/security-list/route changes, metrics/logs and separately labelled active probes. Never claim a successful connection from path analysis alone. |
| Monitoring, Logging, APM, Stack Monitoring and Operations Insights | Managed telemetry, alarms, logs, traces and analysis where configured. | Show missing telemetry as unknown, correlate signals with configuration and changes, and preserve investigation reports. Do not replace collectors or APM. |
| OS Management Hub | Centralised OS updates, schedules and jobs for managed instances. | Surface patch/job posture and remediation evidence; use OS Management Hub rather than invent a second fleet patcher. |

Sources: [Cloud Advisor](https://docs.oracle.com/en-us/iaas/Content/CloudAdvisor/Concepts/cloudadvisoroverview.htm), [Cost Anomaly Detection](https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/costanomalydetectionoverview.htm), [Network Path Analyzer](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/path_analyzer.htm), and [OS Management Hub](https://docs.oracle.com/en-us/iaas/osmh/doc/overview.htm).

## What is implemented now

- Read-only tenancy/compartment discovery with visible coverage failure states.
- Inventory across Compute, core networking, block storage/backup, Autonomous
  Database, IAM policy/users, Cloud Guard, log groups, alarms and budgets.
- Deterministic baseline checks: public ingress review, broad policy review,
  lifecycle/backup faults and explicit unknown checks for unimplemented
  domains. Missing data never becomes a green result.
- Targeted `docs.oracle.com` retrieval with a host allowlist and cached source
  metadata. AI diagnosis is intentionally disabled.
- Resource-specific Compute lifecycle controls with live ETag/state
  preconditions and verification.
- Generic normal OCI CLI commands (no shell) with a server-held, session-bound,
  single-use five-minute approval. Generic success remains *submitted,
  unverified* until a service-specific verification contract exists.
- PostgreSQL retention for every completed report, planned/approved action and
  result. Action and report JSON include a report checksum.

## High-value remaining integrations

These are intentionally visible as coverage gaps instead of being claimed as
complete:

1. **Native recommendation ingestion:** Cloud Advisor, Cost Anomaly Detection,
   Cloud Guard, Vulnerability Scanning, Security Zones, budgets, limits and
   work requests. This is the highest-value next slice because it reuses OCI
   intelligence and explains it in resource context.
2. **Network incident truth:** DNS, load balancer/backend health, VCN flow logs,
   Network Path Analyzer and optional authenticated endpoint probes. Label
   configuration permission separately from observed connectivity.
3. **Identity effective access:** groups, dynamic groups, policy simulation or
   normalized policy analysis, Identity Domain MFA, API-key/auth-token age and
   audit changes. Do not call “MFA healthy” from OCI IAM user inventory alone.
4. **Performance evidence:** Monitoring query support for CPU, memory, network,
   storage latency/IOPS and alarm history. Add guest and application metrics
   only through an explicitly configured collector; OCI CLI cannot see inside a
   VM by itself.
5. **Recovery evidence:** backup policy assignment, age/retention, replication,
   work-request history and separately recorded restore-test outcomes. A
   successful backup is not proof of a recoverable workload.
6. **Operational governance:** tag coverage, Cloud Advisor savings, cost monitor
   readiness, scheduled report notification, report retention policy, owner
   acknowledgement and drift baselines.
7. **Service-specific safe actions:** add dependency checks, change previews,
   work-request tracking and verification contracts before presenting polished
   forms for network, IAM, database, storage or delete operations.

## Security and operational boundary

The console is a private admin tool, not an unattended remediation engine.
Read-only schedules never mutate OCI. Every interactive command is recorded in
PostgreSQL and requires an authenticated, fresh, single-use approval. The
console host is protected from lifecycle operations. The generic route covers
OCI service command syntax without permitting shell execution, credential or
endpoint override, or web-controlled `file://` reads.
