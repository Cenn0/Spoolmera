#!/usr/bin/env python3
"""Prevent accidental publication of private contact emails in tracked source files.

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


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
    issues: list[str] = []
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
        for line in unapproved_email_lines(text):
            issues.append(f"{relative.as_posix()}:{line}")
    if issues:
        for location in issues:
            print("ERROR: review private/contact email in tracked file at " + location)
        print("The address itself is intentionally withheld from CI logs.")
        return 1
    print(f"Public source email check OK: {checked} text files; Git commit metadata not scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
