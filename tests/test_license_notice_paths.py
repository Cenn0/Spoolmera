"""Regression tests for the build-only frontend license notice collector."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def notice_fixture(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed")
    frontend = tmp_path / "frontend"
    scripts = frontend / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "collect-license-notices.mjs"
    script.write_text(
        (ROOT / "frontend" / "scripts" / "collect-license-notices.mjs").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    package = frontend / "node_modules" / "test-fixture"
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": "test-fixture", "version": "1.0.0", "license": "MIT"}),
        encoding="utf-8",
    )
    (package / "LICENSE").write_text("Example MIT fixture license.\n", encoding="utf-8")
    (frontend / "package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/test-fixture": {"license": "MIT"}}}),
        encoding="utf-8",
    )
    return frontend, script


def test_npm_notices_write_only_expected_build_path(notice_fixture):
    frontend, script = notice_fixture
    result = subprocess.run(["node", str(script)], cwd=frontend, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    content = (frontend / "third-party-licenses.txt").read_text(encoding="utf-8")
    assert "test-fixture@1.0.0" in content
    assert "Example MIT fixture license." in content


def test_npm_notices_reject_attacker_chosen_output_location(notice_fixture, tmp_path):
    frontend, script = notice_fixture
    outside = tmp_path / "unexpected-file"
    result = subprocess.run(
        ["node", str(script), str(outside)],
        cwd=frontend, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert not outside.exists()
    assert not (frontend / "third-party-licenses.txt").exists()


def test_npm_notices_reject_symlinked_license_files(notice_fixture, tmp_path):
    frontend, script = notice_fixture
    source = frontend / "node_modules" / "test-fixture" / "LICENSE"
    source.unlink()
    outside = tmp_path / "outside"
    outside.write_text("External content should not be packaged.", encoding="utf-8")
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available on this platform")
    result = subprocess.run(["node", str(script)], cwd=frontend, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert not (frontend / "third-party-licenses.txt").exists()


def test_npm_notices_do_not_follow_destination_symlink(notice_fixture, tmp_path):
    frontend, script = notice_fixture
    outside = tmp_path / "outside"
    outside.write_text("unchanged", encoding="utf-8")
    destination = frontend / "third-party-licenses.txt"
    try:
        destination.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available")
    result = subprocess.run(
        ["node", str(script)], cwd=frontend, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert outside.read_text(encoding="utf-8") == "unchanged"
    assert destination.is_file() and not destination.is_symlink()
    assert "test-fixture" in destination.read_text(encoding="utf-8")


def test_npm_notices_reject_escape_from_lockfile(notice_fixture, tmp_path):
    frontend, script = notice_fixture
    lock = frontend / "package-lock.json"
    lock.write_text(json.dumps({"packages": {
        "node_modules/../../outside": {"license": "MIT"}
    }}), encoding="utf-8")
    result = subprocess.run(
        ["node", str(script)], cwd=frontend, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert not (frontend / "third-party-licenses.txt").exists()


def test_npm_notices_reject_symlinked_package_directory(notice_fixture, tmp_path):
    frontend, script = notice_fixture
    import os
    package = frontend / "node_modules" / "test-fixture"
    outside = tmp_path / "package"
    package.rename(outside)
    try:
        os.symlink(outside, package, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available")
    result = subprocess.run(
        ["node", str(script)], cwd=frontend, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert not (frontend / "third-party-licenses.txt").exists()
