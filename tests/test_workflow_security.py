"""Regression checks for the repository's public CI workflows."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
CODEQL = ROOT / ".github/workflows/codeql.yml"
RELEASE = ROOT / ".github/workflows/release-test.yml"
EXPECTED_JOBS = {"test", "docker-smoke", "browser-smoke", "slicer-build", "security-audit"}


def test_ci_workflow_has_all_test_and_audit_jobs():
    ci = CI.read_text(encoding="utf-8")
    for name in EXPECTED_JOBS:
        assert re.search(r"^  " + re.escape(name) + r":\s*$", ci, flags=re.MULTILINE)


def test_pull_request_ci_is_read_only_and_avoids_persistent_storage():
    ci = CI.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in ci
    assert "  pull_request:\n" in ci
    assert "  workflow_call:\n" in ci
    assert "pull_request_target:" not in ci
    assert "actions/upload-artifact" not in ci
    assert "actions/cache" not in ci
    assert "cache: pip" not in ci
    assert "cache: npm" not in ci
    assert "docker save spoolmera:" not in ci
    assert ci.count("package-manager-cache: false") == 3


def test_tagged_release_requires_ci_verification_and_checksums():
    release = RELEASE.read_text(encoding="utf-8")
    assert "  push:\n    tags:" in release
    assert "uses: ./.github/workflows/ci.yml" in release
    assert "    needs: verify" in release
    assert "if: github.repository == 'Cenn0/Spoolmera'" in release
    assert "      contents: write" in release
    assert "Verify release tag matches exact project version" in release
    assert "git merge-base --is-ancestor" in release
    assert "gh release create" in release
    assert "--verify-tag" in release
    assert "sha256sum" in release
    assert "docker save spoolmera:test" in release
    assert "actions/upload-artifact" not in release


def test_codeql_scans_python_and_typescript():
    codeql = CODEQL.read_text(encoding="utf-8")
    assert "language: [python, javascript-typescript]" in codeql
    assert "security-extended" in codeql


def test_all_workflow_actions_are_pinned_to_commit_shas():
    for path in (CI, CODEQL, RELEASE):
        workflow = path.read_text(encoding="utf-8")
        refs = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
        assert refs
        for ref in refs:
            if ref.startswith("./"):
                assert path == RELEASE and ref == "./.github/workflows/ci.yml"
            else:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+(?:/[\w.-]+)?@[0-9a-f]{40}", ref), ref
        assert "persist-credentials: false" in workflow
