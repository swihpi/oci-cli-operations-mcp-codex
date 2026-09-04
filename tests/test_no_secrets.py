#!/usr/bin/env python3
"""Fail closed when common personal OCI material is added to the public tree."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {Path(".gitignore"), Path("tests/fake_oci.py"), Path("tests/test_protocol.py"), Path("tests/test_no_secrets.py")}
PATTERNS = {
    "OCI OCID": re.compile(r"ocid1\.", re.I),
    "OCI config tenancy": re.compile(r"^\s*tenancy=", re.I | re.M),
    "OCI config user": re.compile(r"^\s*user=", re.I | re.M),
    "OCI config fingerprint": re.compile(r"^\s*fingerprint=", re.I | re.M),
    "OCI key file": re.compile(r"^\s*key_file=", re.I | re.M),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "wallet material": re.compile(r"cwallet\.sso|ewallet\.p12", re.I),
    "local absolute user path": re.compile(r"/Users/[^/]+/"),
}


def candidate_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        if relative in EXCLUDED:
            continue
        yield path, relative


def main():
    findings = []
    for path, relative in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{relative}: non-text file is not allowed in the public source tree")
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: matches forbidden {name} pattern")
    if findings:
        print("Public-release secret scan failed:", *findings, sep="\n- ")
        return 1
    print("Public-release secret scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
