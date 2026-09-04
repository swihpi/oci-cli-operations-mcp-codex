# Oracle documentation routing

Use this routing map only after identifying the live OCI service and operation.
Start from the [OCI documentation home](https://docs.oracle.com/en-us/iaas/Content/home.htm)
when a service is not listed below. Search only `docs.oracle.com` and open the
result before relying on it.

| Situation | MCP evidence first | Documentation search terms |
|---|---|---|
| Compute launch, lifecycle, scale, or capacity | instance, shape, image, AD, work request, limits | `OCI Compute instance launch troubleshooting` |
| Network reachability or exposure | VCN, subnet, route, NSG, security list, gateway, DNS | `OCI Networking routing security lists network security groups troubleshooting` |
| Autonomous Database problem/change | lifecycle, backup, private endpoint, metrics, work request | `OCI Autonomous Database operations troubleshooting` |
| OKE or Containers | cluster/node-pool state, work requests, subnet and limits | `OCI Container Engine for Kubernetes troubleshooting` |
| IAM or security review | policies, dynamic groups, audit, Cloud Guard, scan findings | `OCI IAM policy reference Cloud Guard security guide` |
| Observability incident | alarms, metrics, logs, audit events, notifications | `OCI Monitoring Logging alarms troubleshooting` |
| Cost, quota, or capacity decision | tags, budgets, usage, limit values, availability | `OCI service limits quotas budgets cost analysis` |
| Resource Manager or DevOps | stack/job/pipeline/environment/work request | `OCI Resource Manager troubleshooting` or `OCI DevOps troubleshooting` |
| Recovery, backup, or deletion | lifecycle, backup, replica, retention, dependent resources | `<OCI service> backup restore recovery` |

Prefer a product guide, an operation-specific page, and—when relevant—the IAM
or service-limits page. Do not load broad catalogs unless the service is still
unknown after focused tenancy discovery.
