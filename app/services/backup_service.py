"""Bounded, single-file SQLite snapshots and application identity validation."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Callable

from app.infrastructure.database.migrations import CURRENT_SCHEMA_VERSION

APPLICATION_ID = 0x53504D52


class BackupError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "invalid"):
        super().__init__(message)
        self.reason = reason


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_only_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def logical_size(db: sqlite3.Connection) -> int:
    return db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]


def validate_database(db: sqlite3.Connection) -> int:
    """Accept recognized legacy layouts, never just an arbitrary valid SQLite file."""
    if any(row[0] != "ok" for row in db.execute("PRAGMA integrity_check")):
        raise BackupError("SQLite integrity verification failed.")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise BackupError("SQLite foreign-key verification failed.")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if not 0 <= version <= CURRENT_SCHEMA_VERSION:
        raise BackupError("Backup schema is newer than the supported application version.")
    identity = db.execute("PRAGMA application_id").fetchone()[0]
    if identity not in (0, APPLICATION_ID):
        raise BackupError("Database belongs to a different application.")
    expected = {
        "products": {"id", "brand", "name", "material", "color_name", "color_hex", "diameter_mm"},
        "spools": {"id", "product_id", "initial_g", "remaining_g"},
        "movements": {"id", "spool_id", "kind", "delta_g", "remaining_after_g"},
    }
    if version >= 2:
        expected["products"].add("uid")
        expected["spools"].add("uid")
    if version >= 5:
        expected.update({
            "users": {"id", "username", "password_hash", "role"},
            "print_jobs": {"id", "printer_id", "accounting_status"},
            "job_materials": {"job_id", "tool", "spool_id", "estimated_g"},
            "printer_commands": {"id", "printer_id", "state", "action"},
        })
    if version >= 9:
        expected["scale_event_receipts"] = {"id", "source", "event_id", "spool_id", "status"}
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, columns in expected.items():
        if table not in tables or not columns <= {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            raise BackupError("File is not a recognized Spoolmera database.")
    return version


def ensure_metadata(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS application_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")


def set_metadata(db: sqlite3.Connection, key: str, value: str) -> None:
    ensure_metadata(db)
    db.execute("INSERT INTO application_metadata(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def metadata(db: sqlite3.Connection) -> dict[str, str]:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='application_metadata'").fetchone():
        return {}
    return dict(db.execute("SELECT key,value FROM application_metadata"))


def sync_file(path: Path) -> None:
    with path.open("rb") as source:
        os.fsync(source.fileno())


def sync_directory(path: Path) -> None:
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def remove_snapshot(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def create_snapshot(source: Path, destination: Path, *, max_bytes: int | None = None,
                    timeout_seconds: float = 30, reserve_bytes: int = 64 * 1024 * 1024,
                    progress_hook: Callable[[int, int, int], None] | None = None) -> dict:
    """Create exclusively; include WAL pages and check time, growth and free space."""
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise FileNotFoundError("Source database does not exist.")
    if source.resolve() == destination.resolve():
        raise ValueError("Backup destination must differ from the source database.")
    if timeout_seconds <= 0 or reserve_bytes < 0:
        raise ValueError("Invalid backup resource limits.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    deadline = time.monotonic() + timeout_seconds
    try:
        with closing(sqlite3.connect(read_only_uri(source), uri=True, timeout=1)) as original:
            page_size = original.execute("PRAGMA page_size").fetchone()[0]
            size = logical_size(original)
            if max_bytes is not None and size > max_bytes:
                raise BackupError("Database exceeds the online backup size limit; use the offline CLI.", reason="size")
            if shutil.disk_usage(destination.parent).free < size + reserve_bytes:
                raise BackupError("Insufficient free space for a backup and the application reserve.", reason="space")

            def progress(status: int, remaining: int, total: int) -> None:
                if time.monotonic() >= deadline:
                    raise BackupError("Backup exceeded its time limit.", reason="timeout")
                if max_bytes is not None and total * page_size > max_bytes:
                    raise BackupError("Database grew beyond the online backup size limit.", reason="size")
                if shutil.disk_usage(destination.parent).free < reserve_bytes:
                    raise BackupError("Backup would exhaust the application storage reserve.", reason="space")
                if progress_hook is not None:
                    progress_hook(status, remaining, total)

            with closing(sqlite3.connect(destination, timeout=1)) as target:
                target.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                original.backup(target, pages=128, progress=progress, sleep=0.01)
                target.execute("PRAGMA journal_mode=DELETE")
                version = validate_database(target)
                target.execute(f"PRAGMA application_id={APPLICATION_ID}")
                set_metadata(target, "backup_created_at", now_iso())
                target.commit()
                progress(0, 0, target.execute("PRAGMA page_count").fetchone()[0])
        actual_size = destination.stat().st_size
        if max_bytes is not None and actual_size > max_bytes:
            raise BackupError("Snapshot exceeds the online backup size limit.", reason="size")
        sync_file(destination)
        digest = hashlib.sha256()
        with destination.open("rb") as snapshot:
            for chunk in iter(lambda: snapshot.read(1024 * 1024), b""):
                if time.monotonic() >= deadline:
                    raise BackupError("Backup exceeded its time limit.", reason="timeout")
                digest.update(chunk)
        if time.monotonic() >= deadline:
            raise BackupError("Backup exceeded its time limit.", reason="timeout")
        return {"application": "Spoolmera", "schema_version": version,
                "created_at": now_iso(), "size_bytes": actual_size, "sha256": digest.hexdigest()}
    except sqlite3.OperationalError as exc:
        remove_snapshot(destination)
        if time.monotonic() >= deadline:
            raise BackupError("Backup exceeded its time limit.", reason="timeout") from exc
        raise
    except BaseException:
        remove_snapshot(destination)
        raise


def write_manifest(path: Path, values: dict) -> None:
    with path.open("x", encoding="utf-8") as output:
        os.chmod(path, 0o600)
        json.dump(values, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
