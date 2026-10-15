"""Regression guards for public source and redistributable license documentation."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.check_public_content import is_unapproved_email, unapproved_email_lines
from scripts.collect_python_licenses import parse_pins

ROOT = Path(__file__).resolve().parent.parent


def test_example_and_noreply_addresses_are_accepted():
    for address in ("tester@example.com", "someone@example.org",
                    "198997962+Cenn0@users.noreply.github.com", "noreply@github.com"):
        assert not is_unapproved_email(address)


def test_private_email_detector_does_not_emit_original_address():
    assert unapproved_email_lines("safe@example.org\nName <person@private-domain.tld>\n") == [2]
    assert is_unapproved_email("person@private-domain.tld")


def test_runtime_requirements_are_pinned():
    pins = parse_pins((ROOT / "requirements.txt").read_text(encoding="utf-8"))
    assert pins["fastapi"][1]
    assert pins["uvicorn"][1]
    assert pins["qrcode"][1]


def test_lockfile_runtime_components_have_license_metadata():
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    runtime = [(name, pkg) for name, pkg in lock["packages"].items()
               if name.startswith("node_modules/") and not pkg.get("dev")
               and not pkg.get("devOptional")]
    assert runtime
    for name, pkg in runtime:
        assert pkg.get("license"), name


def test_container_and_ci_ship_notices():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "COPY LICENSE THIRD_PARTY_LICENSES.md /usr/share/doc/spoolmera/" in docker
    assert "python-licenses.txt" in docker
    assert "npm-licenses.txt" in docker
    assert "cp LICENSE THIRD_PARTY_LICENSES.md test-release/" in ci
    assert "frontend-sbom.cdx.json" in ci
