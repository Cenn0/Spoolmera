"""Recovery regressions for WAL growth, resource bounds and actual application identity."""
from contextlib import closing
import asyncio
import errno
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.api import backup as backup_api
from app.database import initialize_database, session
from app.main import create_app
from app.services import backup_service
from app.services.backup_service import BackupError, create_snapshot, metadata
from app.services.process_lock import ProcessLock, operation_lock_path
from scripts.backup import create_backup
from scripts.restore import restore
from tests.support import authenticate


def test_online_download_counts_committed_wal_pages(tmp_path, monkeypatch):
    path = tmp_path / "inventory.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        with closing(sqlite3.connect(path)) as keeper:
            keeper.execute("PRAGMA wal_autocheckpoint=0")
            limit = path.stat().st_size + 64 * 1024
            monkeypatch.setattr(backup_api, "MAX_BACKUP_BYTES", limit)
            keeper.execute("CREATE TABLE large_payload(data BLOB)")
            keeper.execute("INSERT INTO large_payload VALUES(zeroblob(524288))")
            keeper.commit()
            assert path.stat().st_size < limit
            assert Path(str(path) + "-wal").stat().st_size > limit
            response = client.get("/api/admin/backup.sqlite3")
            assert response.status_code == 413, response.text
        assert not list(tmp_path.glob(".filament-snapshot-*.sqlite3"))


def test_growth_during_backup_aborts_and_cleans_partial_snapshot(tmp_path):
    source, target = tmp_path / "source.sqlite3", tmp_path / "target.sqlite3"
    initialize_database(source)
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("CREATE TABLE large_payload(data BLOB)")
        writer.execute("INSERT INTO large_payload VALUES(zeroblob(2097152))")
        writer.commit()
        grew = False

        def grow(status, remaining, total):
            nonlocal grew
            if remaining and not grew:
                grew = True
                writer.execute("INSERT INTO large_payload VALUES(zeroblob(2097152))")
                writer.commit()

        with pytest.raises(BackupError, match="grew"):
            create_snapshot(source, target, max_bytes=3 * 1024 * 1024, progress_hook=grow)
    assert grew and not target.exists()


def test_backup_deadline_and_disk_reserve_are_enforced(tmp_path, monkeypatch):
    source, target = tmp_path / "source.sqlite3", tmp_path / "target.sqlite3"
    initialize_database(source)
    monkeypatch.setattr(backup_service.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(BackupError, match="free space"):
        create_snapshot(source, target)
    assert not target.exists()
    monkeypatch.undo()
    with pytest.raises(BackupError, match="time limit"):
        create_snapshot(source, target, timeout_seconds=0.000001)
    assert not target.exists()


def test_backup_slot_covers_other_downloads(tmp_path):
    path = tmp_path / "database.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        lock = ProcessLock(operation_lock_path(path, "backup"))
        assert lock.acquire()
        try:
            assert client.get("/api/admin/backup.sqlite3").status_code == 429
        finally:
            lock.release()
        assert client.get("/api/admin/backup.sqlite3").status_code == 200


def test_backup_disconnect_removes_file_and_releases_download_slot(tmp_path):
    path = tmp_path / "database.sqlite3"
    snapshot = tmp_path / "snapshot.sqlite3"
    snapshot.write_bytes(b"snapshot body")
    lock = ProcessLock(operation_lock_path(path, "backup"))
    assert lock.acquire()
    response = backup_api.SnapshotResponse(snapshot, lock)

    async def send(message):
        if message["type"] == "http.response.body":
            raise ConnectionError("Client disconnected during file delivery")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(ConnectionError, match="disconnected"):
        asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, send))
    assert not snapshot.exists()
    contender = ProcessLock(operation_lock_path(path, "backup"))
    try:
        assert contender.acquire()
    finally:
        contender.release()


def test_wrong_application_and_modified_manifest_leave_destination_untouched(tmp_path):
    active, wrong, backup = (tmp_path / name for name in ("active.sqlite3", "wrong.sqlite3", "backup.sqlite3"))
    initialize_database(active)
    before = active.read_bytes()
    with closing(sqlite3.connect(wrong)) as db:
        db.execute("CREATE TABLE unrelated(value TEXT)")
        db.commit()
    with pytest.raises(BackupError, match="recognized"):
        restore(wrong, active, confirm=True)
    assert active.read_bytes() == before
    create_backup(active, backup)
    # Reading a WAL-mode database for backup can leave WAL/SHM files behind.
    # Restore requires a stopped, checkpointed destination before source checks.
    with closing(sqlite3.connect(active)) as db:
        assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    before = active.read_bytes()
    with closing(sqlite3.connect(backup)) as db:
        db.execute("CREATE TABLE changed(value TEXT)")
        db.commit()
    with pytest.raises(RuntimeError, match="manifest|checksum"):
        restore(backup, active, confirm=True)
    assert active.read_bytes() == before


def test_restore_rejects_backup_sidecars_even_with_a_matching_main_file_manifest(tmp_path):
    active, backup = tmp_path / "active.sqlite3", tmp_path / "backup.sqlite3"
    initialize_database(active)
    create_backup(active, backup)
    with closing(sqlite3.connect(active)) as db:
        assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    before = active.read_bytes()
    Path(str(backup) + "-wal").write_bytes(b"This WAL is not covered by the standalone snapshot manifest")
    with pytest.raises(RuntimeError, match="standalone backup"):
        restore(backup, active, confirm=True)
    assert active.read_bytes() == before


def test_corrupt_destination_is_preserved_as_raw_bytes_then_restored(tmp_path):
    source, active = tmp_path / "snapshot.sqlite3", tmp_path / "active.sqlite3"
    initialize_database(source)
    damaged = b"corrupt database that SQLite cannot open"
    active.write_bytes(damaged)
    active.chmod(0o640)
    previous = restore(source, active, confirm=True)
    assert previous is not None and previous.read_bytes() == damaged
    assert Path(str(previous) + ".quarantine.json").is_file()
    assert active.stat().st_mode & 0o777 == 0o640
    initialize_database(active)
    with session(active, write=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert metadata(db)["last_restored_at"]


@pytest.mark.skipif(os.name != "posix" or getattr(os, "geteuid", lambda: -1)() != 0,
                    reason="Real owner changes require an administrator; Docker CI covers non-root recovery too")
@pytest.mark.parametrize("existing", [False, True])
def test_administrator_restore_preserves_database_and_lock_owners(tmp_path, existing):
    source = tmp_path / "snapshot.sqlite3"
    initialize_database(source)
    directory = tmp_path / "runtime-data"
    directory.mkdir()
    try:
        os.chown(directory, 10001, 10001)
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EINVAL, errno.ENOTSUP):
            pytest.skip("This host cannot map runtime UID 10001; the real Docker recovery gate checks ownership")
        raise
    active = directory / "spoolmera.sqlite3"
    if existing:
        active.write_bytes(b"damaged original")
        os.chown(active, 10001, 10001)
    restore(source, active, confirm=True)
    for path in [active, *(operation_lock_path(active, name)
                          for name in ("application", "recovery", "poll", "backup"))]:
        assert (path.stat().st_uid, path.stat().st_gid) == (10001, 10001)


def test_restore_rotates_notification_identity_and_revokes_restored_credentials(tmp_path):
    active, backup = tmp_path / "active.sqlite3", tmp_path / "backup.sqlite3"
    with TestClient(create_app(active)) as client:
        authenticate(client)
        token = client.post("/api/admin/automation-tokens", json={"label": "Notifier", "scope": "events_read"})
        assert token.status_code == 201
        with session(active) as db:
            original_epoch = metadata(db)["instance_epoch"]
        create_snapshot(active, backup)
        with pytest.raises(RuntimeError, match="active"):
            restore(backup, active, confirm=True)
    restore(backup, active, confirm=True)
    with session(active) as db:
        assert metadata(db)["instance_epoch"] != original_epoch
        assert db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM automation_tokens WHERE revoked_at IS NULL").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM worker_leases").fetchone()[0] == 0


def test_live_api_still_blocks_restore_after_its_poller_stops(tmp_path):
    active, backup = tmp_path / "active.sqlite3", tmp_path / "backup.sqlite3"
    app = create_app(active)
    with TestClient(app) as client:
        authenticate(client)
        create_snapshot(active, backup)

        async def stop_poller():
            app.state.poll_task.cancel()
            await asyncio.gather(app.state.poll_task, return_exceptions=True)

        client.portal.call(stop_poller)
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == 503
        poll_lock = ProcessLock(operation_lock_path(active, "poll"))
        try:
            assert poll_lock.acquire(), "The poller has already relinquished its own lock"
        finally:
            poll_lock.release()
        with pytest.raises(RuntimeError, match="active"):
            restore(backup, active, confirm=True)
    restore(backup, active, confirm=True)


def test_crash_sidecars_require_explicit_quarantine_and_are_preserved(tmp_path):
    source, active = tmp_path / "backup.sqlite3", tmp_path / "active.sqlite3"
    initialize_database(source)
    active.write_bytes(b"broken")
    wal = Path(str(active) + "-wal")
    wal.write_bytes(b"unrecoverable WAL bytes")
    with pytest.raises(RuntimeError, match="WAL/SHM"):
        restore(source, active, confirm=True)
    previous = restore(source, active, confirm=True, quarantine_sidecars=True)
    assert Path(str(previous) + "-wal").read_bytes() == b"unrecoverable WAL bytes"
    assert not wal.exists()
