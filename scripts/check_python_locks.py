#!/usr/bin/env python3
"""Validate Spoolmera's uv-compiled, hash-pinned Python dependency sets.

This is a structural consistency gate, NOT a resolver or a vulnerability audit.
The CI installation with pip --require-hashes checks the actual distributions.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_PIN = re.compile(rf"^({_NAME})==([^\\s;#]+)")
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}(?=\\s|$)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path: Path, *, require_hashes: bool) -> dict[str, str]:
    """Read pinned requirements, including multiline uv/pip hash continuations."""
    pins: dict[str, str] = {}
    pending: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pending.append(line.removesuffix("\\").strip())
        if line.endswith("\\"):
            continue
        record = " ".join(pending)
        pending.clear()
        # Only the .in files may reference a common input manifest.
        if not require_hashes and re.fullmatch(r"-r\\s+requirements\\.in", record):
            continue
        match = _PIN.match(record)
        if not match:
            raise ValueError(f"{path}:{number}: unsupported or unpinned requirement: {record[:100]}")
        name, version = match.groups()
        normalized = normalize(name)
        if normalized in pins:
            raise ValueError(f"{path}:{number}: duplicate dependency: {name}")
        if require_hashes and not _HASH.search(record):
            raise ValueError(f"{path}:{number}: missing SHA256 hash for {name}")
        pins[normalized] = version
    if pending:
        raise ValueError(f"{path}: unterminated requirement continuation")
    if not pins:
        raise ValueError(f"{path}: no pinned dependencies")
    return pins


def check_locks(root: Path) -> list[str]:
    problems: list[str] = []
    locks: dict[str, dict[str, str]] = {}
    for stem in ("requirements", "requirements-dev", "requirements-e2e"):
        source = root / f"{stem}.in"
        compiled = root / f"{stem}.txt"
        try:
            direct = read_pins(source, require_hashes=False)
            pinned = read_pins(compiled, require_hashes=True)
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
            continue
        locks[stem] = pinned
        for name, version in direct.items():
            actual = pinned.get(name)
            if actual != version:
                problems.append(
                    f"{compiled}: {name} must equal {source.name} pin {version}; "
                    f"found {actual or 'missing'}"
                )

    # The test sets deliberately include and constrain the production graph.
    runtime = locks.get("requirements", {})
    for stem in ("requirements-dev", "requirements-e2e"):
        test_lock = locks.get(stem)
        if test_lock is None:
            continue
        for name, version in runtime.items():
            if test_lock.get(name) != version:
                problems.append(
                    f"{stem}.txt: runtime dependency {name} must be {version}; "
                    f"found {test_lock.get(name) or 'missing'}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    failures = check_locks(args.root)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("Python direct pins, SHA256 hashes and runtime/test lock versions are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
