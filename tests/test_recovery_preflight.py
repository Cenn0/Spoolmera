"""A backup must survive real migration before a restore can replace any data."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app import __version__
from app.database import initialize_database
from app.infrastructure.database.migrations import CURRENT_SCHEMA_VERSION
from app.services import backup_service, recovery_service as recovery
from app.services.backup_service import APPLICATION_ID, BackupError, metadata
from app.services.process_lock import ProcessLock, operation_lock_path
from scripts import restore as restore_module
from scripts.restore import restore
from tests.recovery_fixtures import (
    FIXTURE_PRODUCT_UID, FIXTURE_SPOOL_UID, create_legacy_database,
)


def inventory(path):
    with closing(sqlite3.connect(path)) as db:
        return (
            db.execute("SELECT id,product_id,initial_g,remaining_g FROM spools ORDER BY id").fetchall(),
            db.execute("SELECT id,spool_id,kind,delta_g,remaining_after_g,note,created_at "
                       "FROM movements ORDER BY id").fetchall(),
        )


def manifest_for(path):
    return {
        "application": "Spoolmera",
        "schema_version": CURRENT_SCHEMA_VERSION,
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def assert_no_candidate(path):
    assert not any(Path(str(path) + suffix).exists()
                   for suffix in ("", "-wal", "-shm", "-journal"))


@pytest.mark.parametrize("version", [1, 5, 10, 11])
def test_real_legacy_layout_is_migrated_without_modifying_backup(tmp_path, version):
    source = create_legacy_database(tmp_path / "legacy.sqlite3", version)
    stage = tmp_path / "candidate.sqlite3"
    before = source.read_bytes()
    inventory_before = inventory(source)
    with closing(sqlite3.connect(source)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version == 1:
            assert tables == {"products", "spools", "movements"}
            assert "uid" not in {row[1] for row in db.execute("PRAGMA table_info(spools)")}
        else:
            printer_columns = {row[1] for row in db.execute("PRAGMA table_info(printers)")}
            assert ("serial" in printer_columns) == (version >= 11)
            printer_ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='printers'").fetchone()[0]
            assert ("'bambu'" in printer_ddl) == (version >= 11)
        assert "auto_account_bambu" not in {row[1] for row in db.execute("PRAGMA table_info(print_jobs)")}

    result = recovery.prepare_candidate(source, stage)

    assert result == {
        "report_version": 1,
        "status": "ok",
        "application": "Spoolmera",
        "application_version": __version__,
        "source_schema": version,
        "target_schema": CURRENT_SCHEMA_VERSION,
        "migration_required": True,
        "manifest_status": "absent",
        "source_size_bytes": len(before),
        "source_sha256": hashlib.sha256(before).hexdigest(),
    }
    assert source.read_bytes() == before
    assert inventory(stage) == inventory_before
    with closing(sqlite3.connect(stage)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        assert db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM printer_operations").fetchone()[0] == 0
        if version >= 5:
            assert db.execute("SELECT uid FROM products WHERE id=1").fetchone()[0] == FIXTURE_PRODUCT_UID
            assert db.execute("SELECT uid FROM spools WHERE id=1").fetchone()[0] == FIXTURE_SPOOL_UID
            assert db.execute("SELECT job_id,tool,spool_id,estimated_g,movement_id FROM job_materials").fetchall() == [(1, 0, 1, 100, 2)]
            assert db.execute("SELECT accounted_g FROM job_consumption_totals WHERE job_id=1 AND spool_id=1").fetchone()[0] == 100
            assert db.execute("SELECT auto_account_bambu FROM print_jobs WHERE id=1").fetchone()[0] == 0
    if os.name == "posix":
        assert stage.stat().st_mode & 0o777 == 0o600
    assert not any(Path(str(stage) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    # The next real application initialization must succeed, preserving the ledger.
    initialize_database(stage)
    assert inventory(stage) == inventory_before
    assert source.read_bytes() == before


def test_verification_report_uses_original_hash_and_removes_private_workspace(tmp_path):
    source = create_legacy_database(tmp_path / "source.sqlite3", 5)
    before = source.read_bytes()
    work_dir = tmp_path / "verification"
    work_dir.mkdir()
    result = recovery.verify_backup(source, work_dir=work_dir)
    assert result["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["source_schema"] == 5
    assert result["target_schema"] == CURRENT_SCHEMA_VERSION
    assert result["migration_required"] is True
    assert source.read_bytes() == before
    assert list(work_dir.iterdir()) == []


@pytest.mark.parametrize("statement", [
    "DROP TABLE printer_operations",
    "DROP TABLE auth_failures",
    "DROP TABLE inventory_batch_receipts",
    "DROP TABLE application_metadata",
    "ALTER TABLE printers DROP COLUMN serial",
    "ALTER TABLE print_jobs DROP COLUMN auto_account_bambu",
    "ALTER TABLE automation_tokens DROP COLUMN revoked_at",
    "ALTER TABLE scale_event_receipts DROP COLUMN captured_stock_revision",
])
def test_damaged_current_schema_is_refused_before_restore_replaces_destination(tmp_path, statement):
    source = create_legacy_database(tmp_path / "damaged.sqlite3", 12)
    with closing(sqlite3.connect(source)) as db:
        db.execute(statement)
        db.commit()
    before = source.read_bytes()
    destination = tmp_path / "active.sqlite3"
    destination.write_bytes(b"Previous bytes must survive even when the destination is corrupt")
    old = destination.read_bytes()
    with pytest.raises(BackupError):
        restore(source, destination, confirm=True)
    assert destination.read_bytes() == old
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".spoolmera-restore-*.sqlite3*"))
    assert not list(tmp_path.glob("active.sqlite3.pre-restore-*"))


@pytest.mark.parametrize("mutation", ["application", "future", "foreign_key"])
def test_wrong_identity_future_schema_and_invalid_references_are_refused(tmp_path, mutation):
    source = create_legacy_database(tmp_path / "invalid.sqlite3", 12)
    with closing(sqlite3.connect(source)) as db:
        if mutation == "application":
            db.execute("PRAGMA application_id=12345")
        elif mutation == "future":
            db.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION + 1}")
        else:
            db.execute("UPDATE spools SET product_id=999 WHERE id=1")
        db.commit()
    before = source.read_bytes()
    stage = tmp_path / "candidate.sqlite3"
    with pytest.raises((BackupError, sqlite3.Error)):
        recovery.prepare_candidate(source, stage)
    assert source.read_bytes() == before
    assert_no_candidate(stage)


@pytest.mark.parametrize("kind", ["malformed", "list", "oversized", "size", "checksum", "deep", "non_utf8", "directory"])
def test_invalid_manifest_never_yields_candidate(tmp_path, kind):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    before = source.read_bytes()
    manifest = manifest_for(source)
    if kind == "size":
        manifest["size_bytes"] += 1
    elif kind == "checksum":
        manifest["sha256"] = "0" * 64
    body = json.dumps(manifest)
    if kind == "malformed":
        body = "{private-fixture-manifest"
    elif kind == "list":
        body = "[]"
    elif kind == "oversized":
        body += " " * 20000
    elif kind == "deep":
        body = "[" * 5000 + "]" * 5000
    manifest_path = Path(str(source) + ".manifest.json")
    if kind == "directory":
        manifest_path.mkdir()
    elif kind == "non_utf8":
        manifest_path.write_bytes(b"\xff")
    else:
        manifest_path.write_text(body)
    stage = tmp_path / "candidate.sqlite3"
    with pytest.raises(BackupError):
        recovery.prepare_candidate(source, stage)
    assert source.read_bytes() == before
    assert_no_candidate(stage)


def test_valid_manifest_is_verified_against_original_file(tmp_path):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    manifest = manifest_for(source)
    Path(str(source) + ".manifest.json").write_text(json.dumps(manifest))
    result = recovery.verify_backup(source, work_dir=tmp_path)
    assert result["manifest_status"] == "verified"
    assert result["source_sha256"] == manifest["sha256"]
    assert result["migration_required"] is False


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_source_sidecars_are_refused_and_preserved(tmp_path, suffix):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    before = source.read_bytes()
    sidecar = Path(str(source) + suffix)
    sidecar.write_bytes(b"unverified external sidecar bytes")
    stage = tmp_path / "candidate.sqlite3"
    with pytest.raises(BackupError):
        recovery.prepare_candidate(source, stage)
    assert source.read_bytes() == before
    assert sidecar.read_bytes() == b"unverified external sidecar bytes"
    assert_no_candidate(stage)


@pytest.mark.parametrize("existing", ["file", "symlink", "source"])
def test_existing_stage_is_never_removed_or_overwritten(tmp_path, existing):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    before = source.read_bytes()
    stage = tmp_path / "existing.sqlite3"
    if existing == "file":
        stage.write_bytes(b"do not remove existing bytes")
    elif existing == "symlink":
        stage.symlink_to(source)
    else:
        stage = source
    stage_before = stage.read_bytes()
    with pytest.raises((FileExistsError, ValueError, BackupError)):
        recovery.prepare_candidate(source, stage)
    assert stage.read_bytes() == stage_before
    assert source.read_bytes() == before
    if existing == "symlink":
        assert stage.is_symlink()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_foreign_sidecars_beside_absent_stage_are_preserved(tmp_path, suffix):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    before = source.read_bytes()
    stage = tmp_path / "candidate.sqlite3"
    sidecar = Path(str(stage) + suffix)
    sidecar.write_bytes(b"unrelated staging sidecar must survive")
    with pytest.raises((FileExistsError, BackupError)):
        recovery.prepare_candidate(source, stage)
    assert not stage.exists()
    assert sidecar.read_bytes() == b"unrelated staging sidecar must survive"
    assert source.read_bytes() == before


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_snapshot_limits_are_rejected_without_creating_stage(tmp_path, timeout):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    stage = tmp_path / "candidate.sqlite3"
    with pytest.raises(BackupError):
        recovery.prepare_candidate(source, stage, snapshot_timeout_seconds=timeout)
    assert_no_candidate(stage)


def test_expired_snapshot_deadline_cleans_private_workspace(tmp_path):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    before = source.read_bytes()
    work_dir = tmp_path / "verification"
    work_dir.mkdir()
    with pytest.raises(BackupError) as failure:
        recovery.verify_backup(source, work_dir=work_dir, snapshot_timeout_seconds=1e-12)
    assert failure.value.reason == "timeout"
    assert list(work_dir.iterdir()) == []
    assert source.read_bytes() == before


def test_real_legacy_migration_failure_cleans_candidate_and_preserves_source(tmp_path):
    source = create_legacy_database(tmp_path / "legacy.sqlite3", 1)
    with closing(sqlite3.connect(source)) as db:
        db.execute("ALTER TABLE spools DROP COLUMN created_at")
        db.commit()
    before = source.read_bytes()
    stage = tmp_path / "candidate.sqlite3"
    with pytest.raises(BackupError) as failure:
        recovery.prepare_candidate(source, stage)
    assert failure.value.reason in {"schema", "migration"}
    assert source.read_bytes() == before
    assert_no_candidate(stage)


def test_insufficient_storage_cleans_candidate(tmp_path, monkeypatch):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    before = source.read_bytes()
    stage = tmp_path / "candidate.sqlite3"
    monkeypatch.setattr(backup_service.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(BackupError) as failure:
        recovery.prepare_candidate(source, stage)
    assert failure.value.reason == "space"
    assert source.read_bytes() == before
    assert_no_candidate(stage)


def test_source_change_during_snapshot_is_detected_without_rollback_of_external_write(tmp_path, monkeypatch):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    stage = tmp_path / "candidate.sqlite3"
    snapshot = recovery.create_snapshot
    changed_bytes = None

    def snapshot_then_change(*args, **kwargs):
        nonlocal changed_bytes
        result = snapshot(*args, **kwargs)
        with source.open("ab") as output:
            output.write(b"external change after the snapshot")
        changed_bytes = source.read_bytes()
        return result

    monkeypatch.setattr(recovery, "create_snapshot", snapshot_then_change)
    with pytest.raises(BackupError) as failure:
        recovery.prepare_candidate(source, stage)
    assert failure.value.reason == "changed"
    assert source.read_bytes() == changed_bytes
    assert_no_candidate(stage)


def test_probe_and_restore_preserve_ledger_and_uncertainty_but_reset_only_restored_credentials(tmp_path):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    with closing(sqlite3.connect(source)) as db:
        db.execute("INSERT INTO auth_sessions VALUES('private-session-hash',1,'private-csrf',9999999999)")
        db.execute("""INSERT INTO automation_tokens(id,label,token_hash,scope,created_by,created_at)
            VALUES(1,'private-token-label','private-token-hash','events_read',1,'2020-01-01')""")
        db.execute("INSERT INTO worker_leases VALUES('printer-poll','private-lease-owner',9999999999)")
        db.execute("""INSERT INTO print_jobs(id,printer_id,spool_id,file_name,estimated_g,created_at,updated_at)
            VALUES(2,1,1,'uncertain-private-job.gcode',80,'2020-01-03','2020-01-03')""")
        db.execute("INSERT INTO job_materials(job_id,tool,spool_id,estimated_g) VALUES(2,0,1,80)")
        for command, action, state in [("start", "start", "sending"), ("pause", "pause", "acknowledged"), ("resume", "resume", "unknown")]:
            db.execute("""INSERT INTO printer_commands(id,printer_id,job_id,action,state,created_at,updated_at)
                VALUES(?,1,2,?,?, '2020-01-03','2020-01-03')""", (command, action, state))
        db.execute("""INSERT INTO printer_operations VALUES(1,'start',2,'start','active','2020-01-03','2020-01-03')""")
        db.commit()
        epoch = metadata(db)["instance_epoch"]
    before = source.read_bytes()
    inventory_before = inventory(source)
    stage = tmp_path / "probe.sqlite3"
    recovery.prepare_candidate(source, stage)
    with closing(sqlite3.connect(stage)) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 1
        assert db.execute("SELECT revoked_at FROM automation_tokens").fetchone()[0] is None
        assert db.execute("SELECT COUNT(*) FROM worker_leases").fetchone()[0] == 1
        assert metadata(db)["instance_epoch"] == epoch

    restored = tmp_path / "restored.sqlite3"
    restore(source, restored, confirm=True)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0
        assert db.execute("SELECT revoked_at FROM automation_tokens").fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM worker_leases").fetchone()[0] == 0
        assert metadata(db)["instance_epoch"] != epoch
        assert metadata(db)["restore_token_reissue_required"] == "1"
        assert db.execute("SELECT password_hash FROM users WHERE id=1").fetchone()[0] == "private-fixture-password-hash"
        assert dict(db.execute("SELECT id,state FROM printer_commands")) == {"start": "unknown", "pause": "acknowledged", "resume": "unknown"}
        assert db.execute("SELECT state FROM printer_operations WHERE printer_id=1").fetchone()[0] == "unknown"
    assert inventory(restored) == inventory_before
    assert source.read_bytes() == before


@pytest.mark.parametrize("fail_before_replace", [False, True])
def test_restore_cleanup_failure_still_releases_every_operation_lock(tmp_path, monkeypatch, fail_before_replace):
    source = create_legacy_database(tmp_path / "source.sqlite3", 12)
    source_before = source.read_bytes()
    destination = tmp_path / "active.sqlite3"
    destination.write_bytes(b"Existing destination must survive a pre-replacement failure")
    destination.chmod(0o640)
    destination_before = destination.read_bytes()

    def fail_cleanup(_):
        raise OSError("Synthetic candidate cleanup failure")

    def fail_before_replacement(_):
        raise RuntimeError("Synthetic failure before replacement")

    monkeypatch.setattr(restore_module, "remove_snapshot", fail_cleanup)
    if fail_before_replace:
        monkeypatch.setattr(restore_module, "sync_file", fail_before_replacement)

    with pytest.raises(OSError, match="candidate cleanup failure"):
        restore(source, destination, confirm=True)

    contenders = [ProcessLock(operation_lock_path(destination, name))
                  for name in ("application", "recovery", "poll", "backup")]
    try:
        for contender in contenders:
            assert contender.acquire(), "Failed candidate cleanup leaked an operation lock"
    finally:
        for contender in reversed(contenders):
            contender.release()
    assert source.read_bytes() == source_before
    if fail_before_replace:
        assert destination.read_bytes() == destination_before
        candidates = list(tmp_path.glob(".spoolmera-restore-*.sqlite3"))
        assert len(candidates) == 1
        if os.name == "posix":
            assert candidates[0].stat().st_mode & 0o777 == 0o640
    else:
        assert inventory(destination) == inventory(source)
        assert not list(tmp_path.glob(".spoolmera-restore-*.sqlite3"))
