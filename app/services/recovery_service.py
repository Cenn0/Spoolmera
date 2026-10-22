"""Offline recovery candidates, shared by verification and guarded restore.

Only a standalone backup is read. Migrations and restart recovery run on a new
private candidate, never on the original file. ``snapshot_timeout_seconds``
limits the SQLite snapshot operation, not hashing or the subsequent migrations.
"""
from contextlib import closing
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from app import __version__
from app.database import connect, initialize_connection
from app.infrastructure.database.migrations import CURRENT_SCHEMA_VERSION
from app.services.backup_service import (
    BackupError, create_snapshot, read_only_uri, remove_snapshot, sync_file,
    validate_database,
)

_SIDECARS = ("-wal", "-shm", "-journal")
_MANIFEST_LIMIT = 16384
_RESERVE_BYTES = 64 * 1024 * 1024


def _resolve_path(path: Path) -> Path:
    try:
        return path.resolve()
    except RuntimeError:
        # Python 3.12 reports symlink loops as RuntimeError, whereas newer
        # versions use OSError. Keep both within the caller's I/O error path
        # without exposing the original exception's private pathname.
        raise OSError(errno.ELOOP, "Recovery path contains a symbolic link loop.") from None


def _sidecars_exist(path: Path) -> bool:
    return any((entry := Path(str(path) + suffix)).exists() or entry.is_symlink()
               for suffix in _SIDECARS)


def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _assert_unchanged(source: Path, original: tuple[int, int, int, int, int]) -> None:
    try:
        unchanged = _fingerprint(source.stat()) == original and not _sidecars_exist(source)
    except OSError:
        unchanged = False
    if not unchanged:
        raise BackupError("Backup changed while it was being verified.", reason="changed")


def _source_info(source: Path) -> tuple[tuple[int, int, int, int, int], str, str]:
    info = source.stat()
    if not stat.S_ISREG(info.st_mode):
        raise BackupError("Backup must be a regular database file.")
    if _sidecars_exist(source):
        raise BackupError("Recovery source must be a standalone backup without WAL/SHM or journal files; create a verified snapshot first.")
    original = _fingerprint(info)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        if _fingerprint(os.fstat(handle.fileno())) != original:
            raise BackupError("Backup changed while it was being verified.", reason="changed")
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    _assert_unchanged(source, original)
    sha256 = digest.hexdigest()
    manifest = Path(str(source) + ".manifest.json")
    if not manifest.exists():
        return original, sha256, "absent"
    if not stat.S_ISREG(manifest.stat().st_mode):
        raise BackupError("Backup manifest must be a regular JSON file.")
    with manifest.open("rb") as handle:
        raw = handle.read(_MANIFEST_LIMIT + 1)
    if len(raw) > _MANIFEST_LIMIT:
        raise BackupError("Backup manifest is too large.")
    try:
        values = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise BackupError("Backup manifest is invalid.") from None
    if (not isinstance(values, dict) or values.get("application") != "Spoolmera"
            or values.get("size_bytes") != info.st_size):
        raise BackupError("Backup manifest does not match this database.")
    if values.get("sha256") != sha256:
        raise BackupError("Backup checksum does not match its manifest.")
    return original, sha256, "verified"


def _current_schema() -> dict[str, frozenset[str]]:
    """Derive required names from the real initializer, not a second schema."""
    with closing(connect(":memory:")) as reference:
        initialize_connection(reference)
        tables = [row[0] for row in reference.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_")]
        return {table: frozenset(row[0] for row in reference.execute(
                    "SELECT name FROM pragma_table_info(?)", (table,)))
                for table in tables}


def _validate_current_schema(db: sqlite3.Connection,
                             expected: dict[str, frozenset[str]]) -> None:
    """Check required tables and columns, not SQL-text/constraint equivalence."""
    for table, columns in expected.items():
        found = db.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
        if found is None or found[0] != "table":
            raise BackupError("Backup is missing tables required by the current Spoolmera schema.", reason="schema")
        actual = {row[0] for row in db.execute("SELECT name FROM pragma_table_info(?)", (table,))}
        if not columns <= actual:
            raise BackupError("Backup is missing columns required by the current Spoolmera schema.", reason="schema")


def prepare_candidate(source: Path, stage: Path, *, snapshot_timeout_seconds: float = 300,
                      reserve_bytes: int = _RESERVE_BYTES) -> dict:
    """Create a new, migrated, standalone candidate; remove it on any failure.

    A successful call transfers ownership of ``stage`` to the caller. Existing
    paths are never overwritten or removed. Credential revocation remains the
    restore caller's responsibility after this shared preflight succeeds.
    """
    if (isinstance(snapshot_timeout_seconds, bool)
            or not isinstance(snapshot_timeout_seconds, (float, int))
            or not math.isfinite(snapshot_timeout_seconds) or snapshot_timeout_seconds <= 0):
        raise BackupError("Snapshot timeout must be finite and positive.")
    if isinstance(reserve_bytes, bool) or not isinstance(reserve_bytes, int) or reserve_bytes < 0:
        raise BackupError("Storage reserve must be a non-negative integer.")
    source, stage = _resolve_path(Path(source)), Path(stage)
    if source == _resolve_path(stage):
        raise BackupError("Recovery candidate must differ from the source backup.")
    if stage.exists() or stage.is_symlink() or _sidecars_exist(stage):
        raise FileExistsError("Recovery candidate or its database sidecars already exist.")
    original, sha256, manifest_status = _source_info(source)
    owned = False
    success = False
    phase = "invalid"
    try:
        expected = _current_schema()
        # Opening an offline backup as immutable avoids source-side WAL/SHM
        # creation even if its persisted header says WAL. This must never be
        # used for a live database: check standalone state and changes around
        # every stage, in addition to SQLite's normal snapshot validation.
        with closing(sqlite3.connect(read_only_uri(source, immutable=True), uri=True)) as original_db:
            source_schema = original_db.execute("PRAGMA user_version").fetchone()[0]
            if source_schema == CURRENT_SCHEMA_VERSION:
                # Check the source too: snapshot metadata must not disguise a
                # missing application_metadata table in a purported current DB.
                _validate_current_schema(original_db, expected)
        _assert_unchanged(source, original)
        info = create_snapshot(source, stage, timeout_seconds=snapshot_timeout_seconds,
                               reserve_bytes=reserve_bytes, immutable_source=True)
        owned = True
        _assert_unchanged(source, original)
        if info["schema_version"] != source_schema:
            raise BackupError("Backup changed while it was being verified.", reason="changed")
        with closing(connect(stage)) as candidate:
            if source_schema == CURRENT_SCHEMA_VERSION:
                _validate_current_schema(candidate, expected)
            phase = "migration"
            try:
                initialize_connection(candidate)
            except (sqlite3.Error, RuntimeError):
                raise BackupError("Backup candidate could not be migrated to the current Spoolmera schema.", reason="migration") from None
            phase = "schema"
            _validate_current_schema(candidate, expected)
            if validate_database(candidate) != CURRENT_SCHEMA_VERSION:
                raise BackupError("Backup candidate did not reach the current Spoolmera schema.", reason="schema")
            checkpoint = candidate.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint[0] != 0:
                raise BackupError("Recovery candidate checkpoint did not complete.", reason="migration")
            mode = candidate.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode.lower() != "delete":
                raise BackupError("Recovery candidate could not be finalized as a standalone database.", reason="migration")
        if _sidecars_exist(stage):
            raise BackupError("Recovery candidate still has database sidecar files.", reason="migration")
        _assert_unchanged(source, original)
        sync_file(stage)
        success = True
        return {"report_version": 1, "status": "ok", "application": "Spoolmera",
                "application_version": __version__, "source_schema": source_schema,
                "target_schema": CURRENT_SCHEMA_VERSION,
                "migration_required": source_schema != CURRENT_SCHEMA_VERSION,
                "manifest_status": manifest_status, "source_size_bytes": original[2],
                "source_sha256": sha256}
    except BackupError:
        _assert_unchanged(source, original)
        raise
    except sqlite3.Error:
        _assert_unchanged(source, original)
        raise BackupError("Backup database verification failed.", reason=phase) from None
    except RuntimeError:
        _assert_unchanged(source, original)
        raise BackupError("Backup candidate could not be migrated to the current Spoolmera schema.", reason="migration") from None
    finally:
        if owned and not success:
            remove_snapshot(stage)


def verify_backup(source: Path, *, work_dir: Path | None = None,
                  snapshot_timeout_seconds: float = 300) -> dict:
    """Exercise recovery in a temporary directory without replacing any data."""
    with tempfile.TemporaryDirectory(prefix="spoolmera-verify-", dir=work_dir) as directory:
        return prepare_candidate(source, Path(directory) / "candidate.sqlite3",
                                 snapshot_timeout_seconds=snapshot_timeout_seconds)
