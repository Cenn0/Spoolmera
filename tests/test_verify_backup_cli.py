"""Exercise the operator CLI as a real process with private fixture data."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app import __version__
from app.infrastructure.database.migrations import CURRENT_SCHEMA_VERSION
from tests.recovery_fixtures import create_legacy_database


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_backup.py"
PRIVATE_VALUES = (
    "private-fixture-brand", "private-fixture-product", "private-fixture-product-note",
    "private-fixture-location", "private-fixture-ledger-note", "private-fixture-user",
    "private-fixture-password-hash", "private-fixture-printer", "http://192.168.50.20",
    "PRIVATE_FIXTURE_PRINTER_TOKEN", "private-fixture-job.gcode",
)


def run_cli(source, *options, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), *map(str, options)],
        capture_output=True, text=True, cwd=cwd, env=env, timeout=30,
    )


def assert_private_output(result, source, work_dir):
    text = result.stdout + result.stderr
    for value in (*PRIVATE_VALUES, str(source), str(work_dir)):
        assert value not in text


@pytest.mark.parametrize("version", [1, 5, 10, 11, 12])
def test_json_cli_migrates_historical_backup_and_leaves_source_and_workspace_untouched(tmp_path, version):
    source = create_legacy_database(tmp_path / "private-source-name.sqlite3", version)
    before = source.read_bytes()
    work_dir = tmp_path / "private-workspace-name"
    work_dir.mkdir()
    result = run_cli(source, "--json", "--work-dir", work_dir,
                     "--snapshot-timeout-seconds", "300", cwd=tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert set(report) == {
        "report_version", "status", "application", "application_version",
        "source_schema", "target_schema", "migration_required", "manifest_status",
        "source_size_bytes", "source_sha256",
    }
    assert report["report_version"] == 1
    assert report["status"] == "ok"
    assert report["application"] == "Spoolmera"
    assert report["application_version"] == __version__
    assert report["source_schema"] == version
    assert report["target_schema"] == CURRENT_SCHEMA_VERSION
    assert report["migration_required"] == (version < CURRENT_SCHEMA_VERSION)
    assert report["manifest_status"] == "absent"
    assert report["source_size_bytes"] == len(before)
    assert report["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before
    assert list(work_dir.iterdir()) == []
    assert_private_output(result, source, work_dir)


def test_json_cli_verifies_optional_manifest(tmp_path):
    source = create_legacy_database(tmp_path / "source.sqlite3", 5)
    before = source.read_bytes()
    manifest = {"application": "Spoolmera", "schema_version": 5,
                "size_bytes": len(before), "sha256": hashlib.sha256(before).hexdigest()}
    Path(str(source) + ".manifest.json").write_text(json.dumps(manifest))
    result = run_cli(source, "--json", "--work-dir", tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["manifest_status"] == "verified"
    assert source.read_bytes() == before


@pytest.mark.parametrize("kind,code", [
    ("missing", "io"),
    ("corrupt", "invalid"),
    ("future", "invalid"),
    ("table", "schema"),
    ("column", "schema"),
    ("migration", "migration"),
    ("manifest", "invalid"),
    ("sidecar", "invalid"),
    ("workspace", "io"),
])
def test_json_cli_failures_are_structured_redacted_and_leave_no_artifacts(tmp_path, kind, code):
    source = tmp_path / "private-source-name.sqlite3"
    work_dir = tmp_path / "private-workspace-name"
    if kind != "workspace":
        work_dir.mkdir()
    if kind not in {"missing", "corrupt"}:
        create_legacy_database(source, 1 if kind == "migration" else 12)
    if kind == "corrupt":
        source.write_bytes(b"private-fixture-password-hash: not a SQLite database")
    elif kind in {"future", "table", "column", "migration"}:
        statements = {
            "future": f"PRAGMA user_version={CURRENT_SCHEMA_VERSION + 1}",
            "table": "DROP TABLE printer_operations",
            "column": "ALTER TABLE print_jobs DROP COLUMN auto_account_bambu",
            "migration": "ALTER TABLE spools DROP COLUMN created_at",
        }
        with closing(sqlite3.connect(source)) as db:
            db.execute(statements[kind])
            db.commit()
    elif kind == "manifest":
        Path(str(source) + ".manifest.json").write_text("{private-fixture-password-hash")
    elif kind == "sidecar":
        Path(str(source) + "-wal").write_bytes(b"private-fixture-password-hash")
    before = source.read_bytes() if source.exists() else None

    result = run_cli(source, "--json", "--work-dir", work_dir, cwd=tmp_path)

    assert result.returncode == 1
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert set(report) == {"report_version", "status", "application", "application_version", "error"}
    assert report["report_version"] == 1
    assert report["status"] == "error"
    assert report["application"] == "Spoolmera"
    assert report["application_version"] == __version__
    assert set(report["error"]) == {"code", "message"}
    assert report["error"]["code"] == code
    assert report["error"]["message"]
    assert_private_output(result, source, work_dir)
    if before is not None:
        assert source.read_bytes() == before
    else:
        assert not source.exists()
    if work_dir.exists():
        assert list(work_dir.iterdir()) == []


@pytest.mark.parametrize("value", ["0", "-1", "3601", "nan", "inf", "1.5"])
def test_snapshot_timeout_argument_rejects_invalid_values(tmp_path, value):
    result = run_cli(tmp_path / "not-needed.sqlite3", "--json",
                     "--snapshot-timeout-seconds", value)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Snapshot timeout" in result.stderr


def test_default_temporary_workspace_is_cleaned_and_text_mode_reports_outcome(tmp_path):
    source = create_legacy_database(tmp_path / "source.sqlite3", 5)
    work_dir = tmp_path / "temporary-root"
    work_dir.mkdir()
    env = dict(os.environ, TMPDIR=str(work_dir))
    result = run_cli(source, env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert "Backup verified" in result.stdout
    assert f"Schema: 5 -> {CURRENT_SCHEMA_VERSION}" in result.stdout
    assert "no active database was replaced" in result.stdout
    assert list(work_dir.iterdir()) == []


def test_text_mode_errors_are_redacted_on_stderr(tmp_path):
    source = tmp_path / "private-source-name.sqlite3"
    result = run_cli(source, "--work-dir", tmp_path, cwd=tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Backup verification failed" in result.stderr
    assert_private_output(result, source, tmp_path)


def test_json_cli_symlink_loop_is_a_redacted_io_failure(tmp_path):
    source = tmp_path / "private-source-name.sqlite3"
    source.symlink_to(source.name)
    work_dir = tmp_path / "private-workspace-name"
    work_dir.mkdir()

    result = run_cli(source, "--json", "--work-dir", work_dir, cwd=tmp_path)

    assert result.returncode == 1
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["report_version"] == 1
    assert report["status"] == "error"
    assert report["error"]["code"] == "io"
    assert_private_output(result, source, work_dir)
    assert source.is_symlink()
    assert source.readlink() == Path(source.name)
    assert list(work_dir.iterdir()) == []
