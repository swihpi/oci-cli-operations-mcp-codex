# Documented check contracts

These checks join live OCI CLI evidence to a small, reviewed Oracle guidance
set. They are operational review aids, not a universal compliance certification.

| Check | Live evidence | Result contract | Oracle source |
|---|---|---|---|
| `public_ingress_review` | Security lists in one compartment | `review_required` for any IPv4 or IPv6 internet-sourced ingress rule; otherwise `passed`; unreadable evidence is `unknown`. Public access may be intentional. | [Security Lists](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securitylists.htm) |
| `cloud_guard_enabled` | Root-tenancy Cloud Guard configuration | `passed` only when status is `ENABLED`; otherwise `review_required`; unreadable evidence is `unknown`. This does not prove target or detector coverage. | [Cloud Guard](https://docs.oracle.com/en-us/iaas/Content/cloud-guard/home.htm) |
| `logging_present` | Log groups in one compartment | `passed` when at least one group is visible; otherwise `review_required`; unreadable evidence is `unknown`. A group does not prove a required service log is enabled. | [Logging Overview](https://docs.oracle.com/en-us/iaas/Content/Logging/Concepts/loggingoverview.htm) |

The source links and contracts were reviewed on 2026-09-30. Re-review the
contract when Oracle changes the governing behavior or the CLI response shape.
