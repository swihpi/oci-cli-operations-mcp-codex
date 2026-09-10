# Security policy

Do not include OCI private keys, API-key fingerprints, tenancy/user/resource
OCIDs, wallet files, passwords, tokens, or unredacted CLI output in issues,
pull requests, or discussions.

Report a suspected vulnerability privately through the repository's security
advisory feature. Include a minimal reproduction using fictional identifiers.
Do not send credentials, wallets, or a copy of `~/.oci/config`.

The project deliberately requires explicit approval before cloud-changing CLI
commands execute. Approval tokens are process-local, random, exact-command
bound, single-use, and expire after five minutes. The generic boundary rejects
profile/auth/transport overrides, raw requests, local CLI administration, and
arbitrary local file input/output. A report that can bypass these controls,
replay an approval, reveal redacted values, or execute arbitrary shell commands
is security-sensitive.
