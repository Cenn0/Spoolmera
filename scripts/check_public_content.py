#!/usr/bin/env python3
"""Reject high-confidence credentials and private contact emails in tracked text.

This does NOT inspect Git commit authors or rewrite history. Values are deliberately
never printed, including in CI failure messages.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SAFE_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "example.invalid",
    "users.noreply.github.com",
})


# Deliberately narrow: never print matching values. This is a pre-publication
# guard, not a substitute for GitHub secret scanning or historical analysis.
SECRET_PATTERNS = (
    re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9_]{36,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
)



def is_unapproved_email(address: str) -> bool:
    """Return True for potentially private contacts without disclosing them."""
    local, separator, domain = address.lower().rpartition("@")
    if not separator:
        return False
    return domain not in SAFE_DOMAINS and not (local == "noreply" and domain == "github.com")


def unapproved_email_lines(text: str) -> list[int]:
    return sorted({text.count("\n", 0, match.start()) + 1
                   for match in EMAIL_PATTERN.finditer(text)
                   if is_unapproved_email(match.group(0))})


def suspected_secret_lines(text: str) -> list[int]:
    """Return locations of high-confidence markers without returning values."""
    return sorted({text.count("\n", 0, match.start()) + 1
                   for pattern in SECRET_PATTERNS
                   for match in pattern.finditer(text)})


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    email_found = False
    secret_found = False
    checked = 0
    for entry in tracked:
        if not entry:
            continue
        relative = Path(entry.decode("utf-8", "surrogateescape"))
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # Checked-in binary assets are not text.
        checked += 1
        if unapproved_email_lines(text):
            email_found = True
        if suspected_secret_lines(text):
            secret_found = True
    if email_found:
        print("ERROR: tracked source contains an unapproved contact email.")
    if secret_found:
        print("ERROR: tracked source contains a possible credential or private-key marker.")
    if email_found or secret_found:
        print("Values, paths and line numbers are withheld from CI logs; inspect locally.")
        return 1
    print(f"Public source content check OK: {checked} text files; Git commit metadata not scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
