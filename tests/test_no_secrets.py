#!/usr/bin/env python3
"""Fail closed when common personal OCI material is added to the public tree."""

from pathlib import Path
import hashlib
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {Path(".gitignore"), Path("tests/fake_oci.py"), Path("tests/test_protocol.py"), Path("tests/test_no_secrets.py")}
PUBLIC_SCREENSHOT_HASHES = {
    Path("assets/screenshots/approval-gated-mutation-redacted.png"): "7e6ffc0700f0eb98b0fcf93753df04306a9c6f49a85af3e05c8e2630a3515198",
    Path("assets/screenshots/network-findings-redacted.png"): "eae50d23eb9dbccca8c0b0a596b8fae1204cfa0ca6218abc1d8a5b4b51f051f3",
    Path("assets/screenshots/network-topology-audit-redacted.png"): "8c7b9f1c2c88d2339507fdfe9906afe83cbcc957538c17342eda0c9aaceb5c99",
    Path("assets/screenshots/vm-inspection-redacted.png"): "8d8c3a109d20101cd5c35a07e5aeb088aed6e4fd0cf77f18aee796ee26a08965",
}
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
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(ROOT)
        if relative in EXCLUDED:
            continue
        yield path, relative


def main():
    findings = []
    found_screenshots = set()
    for path, relative in candidate_files():
        if relative in PUBLIC_SCREENSHOT_HASHES:
            found_screenshots.add(relative)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != PUBLIC_SCREENSHOT_HASHES[relative]:
                findings.append(f"{relative}: screenshot hash changed; review and explicitly update the allowlist")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{relative}: non-text file is not allowed in the public source tree")
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: matches forbidden {name} pattern")
    unexpected_screenshots = set((ROOT / "assets" / "screenshots").glob("*")) - {ROOT / item for item in PUBLIC_SCREENSHOT_HASHES}
    if unexpected_screenshots:
        findings.extend(f"{path.relative_to(ROOT)}: unreviewed screenshot is not allowed" for path in sorted(unexpected_screenshots))
    missing_screenshots = set(PUBLIC_SCREENSHOT_HASHES) - found_screenshots
    if missing_screenshots:
        findings.extend(f"{path}: reviewed screenshot is missing" for path in sorted(missing_screenshots))
    if findings:
        print("Public-release secret scan failed:", *findings, sep="\n- ")
        return 1
    print("Public-release secret scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
