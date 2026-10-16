#!/usr/bin/env python3
"""Collect verbatim Python runtime license notices from pinned installed wheels.

Uses only the standard library; fails closed for absent wheels or license files.
This is package-notice collection, not legal certification or an OS-package SBOM.
"""
from __future__ import annotations

import argparse
import json
from importlib import metadata
from pathlib import Path, PurePosixPath
import re


PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s\\]+)", re.MULTILINE)
NOTICE = re.compile(r"^(?:license|licence|copying|notice)(?:$|[._-])", re.IGNORECASE)


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(contents: str) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for name, version in PIN.findall(contents):
        key = norm(name)
        if key in result:
            raise ValueError(f"Duplicate requirement: {key}")
        result[key] = (name, version)
    if not result:
        raise ValueError("No pinned requirements found.")
    return result


def notices(dist: metadata.Distribution) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for candidate in dist.files or ():
        name = PurePosixPath(str(candidate))
        value = str(name).lower()
        if ".dist-info/" not in value:
            continue
        if not (NOTICE.match(name.name) or "/licenses/" in value):
            continue
        filename = Path(dist.locate_file(candidate))
        if not filename.is_file() or filename.stat().st_size > 1024 * 1024:
            continue
        try:
            content = filename.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if content.strip():
            found.append((str(name), content))
    return sorted(found)


def collect(requirements: Path) -> tuple[str, list[dict]]:
    chunks = ["Python runtime third-party license/notice texts",
              "Package versions are taken from the pinned requirements file.",
              "Actual wheel license records follow. No package is relicensed to Apache-2.0."]
    records: list[dict] = []
    for key, (name, version) in sorted(parse_pins(requirements.read_text(encoding="utf-8")).items()):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError as exc:
            raise ValueError(f"Pinned runtime package not installed: {name}") from exc
        actual = dist.version
        if actual != version:
            raise ValueError(f"Runtime dependency version mismatch for {name}: expected {version}, found {actual}")
        texts = notices(dist)
        if not texts:
            raise ValueError(f"No bundled license/notice text in installed wheel: {name}=={version}")
        license_id = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "UNSPECIFIED"
        # Legacy metadata may contain multiline full license text. Do not duplicate it in JSON.
        if len(license_id) > 200:
            license_id = "SEE_BUNDLED_LICENSE_FILES"
        records.append({"name": name, "version": version, "license_metadata": license_id,
                        "files": [path for path, _ in texts]})
        chunks.extend(("", "=" * 72, f"{name}=={version}", f"License metadata: {license_id}"))
        for path, content in texts:
            chunks.extend(("", f"--- {path} ---", content.rstrip("\n")))
    return "\n".join(chunks) + "\n", records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    document, records = collect(args.requirements)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    args.manifest.write_text(json.dumps({"generator": "spoolmera-python-license-notices-v1",
                                          "components": records}, indent=2) + "\n", encoding="utf-8")
    print(f"Collected notices for {len(records)} pinned Python runtime packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
