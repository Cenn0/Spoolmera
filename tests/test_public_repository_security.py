"""Regression gates for public GitHub repo configuration (not admin state)."""

from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RULESET = ROOT / ".github/rulesets/main.json"
CI = ROOT / ".github/workflows/ci.yml"
CODEQL = ROOT / ".github/workflows/codeql.yml"
REQUIRED_JOBS = {"test", "docker-smoke", "browser-smoke", "slicer-build", "security-audit"}


def test_proposed_branch_ruleset_has_no_bypass_and_requires_pull_requests():
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    assert ruleset["enforcement"] == "active"
    assert ruleset["target"] == "branch"
    assert ruleset["bypass_actors"] == []
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    rules = {rule["type"]: rule for rule in ruleset["rules"]}
    assert {"deletion", "non_fast_forward", "required_linear_history", "pull_request", "required_status_checks"} <= rules.keys()
    pr = rules["pull_request"]["parameters"]
    assert pr["required_approving_review_count"] == 0  # solo maintainer
    assert not pr["require_code_owner_review"]
    assert pr["required_review_thread_resolution"]
    assert pr["allowed_merge_methods"] == ["squash", "rebase"]


def test_required_checks_exist_in_current_ci_and_are_strict():
    rules = json.loads(RULESET.read_text(encoding="utf-8"))["rules"]
    policy = next(r for r in rules if r["type"] == "required_status_checks")["parameters"]
    assert policy["strict_required_status_checks_policy"] is True
    configured = {c["context"] for c in policy["required_status_checks"]}
    assert configured == REQUIRED_JOBS
    ci = CI.read_text(encoding="utf-8")
    for name in configured:
        assert re.search(r"^  " + re.escape(name) + r":\s*$", ci, flags=re.MULTILINE)


def test_public_pull_request_ci_is_read_only_and_only_main_publishes_images():
    ci = CI.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in ci
    assert "  pull_request:\n" in ci
    assert "pull_request_target:" not in ci
    assert re.search(r"- name: Package tested image\n\s+if: github.event_name == 'push'", ci)
    assert re.search(r"- name: Publish downloadable test instance\n\s+if: github.event_name == 'push'", ci)


def test_all_workflow_action_references_are_commit_pinned():
    for path in (CI, CODEQL):
        workflow = path.read_text(encoding="utf-8")
        action_refs = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
        assert action_refs
        for ref in action_refs:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+(?:/[\w.-]+)?@[0-9a-f]{40}", ref), ref
        assert "persist-credentials: false" in workflow
