# Security policy

Do not include OCI private keys, API-key fingerprints, tenancy/user/resource
OCIDs, wallet files, passwords, tokens, or unredacted CLI output in issues,
pull requests, or discussions.

Report a suspected vulnerability privately through the repository's security
advisory feature. Include a minimal reproduction using fictional identifiers.
Do not send credentials, wallets, or a copy of `~/.oci/config`.

The project deliberately requires explicit approval before cloud-changing CLI
commands execute. A report that can bypass that boundary, alter profile/auth
configuration, reveal redacted values, or execute arbitrary shell commands is
security-sensitive.
