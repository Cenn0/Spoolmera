"""Regression checks for the repository's public CI workflows."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
CODEQL = ROOT / ".github/workflows/codeql.yml"
EXPECTED_JOBS = {"test", "docker-smoke", "browser-smoke", "slicer-build", "security-audit"}


def test_ci_workflow_has_all_test_and_audit_jobs():
    ci = CI.read_text(encoding="utf-8")
    for name in EXPECTED_JOBS:
        assert re.search(r"^  " + re.escape(name) + r":\s*$", ci, flags=re.MULTILINE)


def test_pull_request_ci_uses_read_only_permissions_and_limits_artifacts():
    ci = CI.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in ci
    assert "  pull_request:\n" in ci
    assert "pull_request_target:" not in ci
    assert re.search(r"- name: Package tested image\n\s+if: github.event_name == 'push'", ci)
    assert re.search(r"- name: Publish downloadable test instance\n\s+if: github.event_name == 'push'", ci)


def test_codeql_scans_python_and_typescript():
    codeql = CODEQL.read_text(encoding="utf-8")
    assert "language: [python, javascript-typescript]" in codeql
    assert "security-extended" in codeql


def test_all_workflow_actions_are_pinned_to_commit_shas():
    for path in (CI, CODEQL):
        workflow = path.read_text(encoding="utf-8")
        refs = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
        assert refs
        for ref in refs:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+(?:/[\w.-]+)?@[0-9a-f]{40}", ref), ref
        assert "persist-credentials: false" in workflow
