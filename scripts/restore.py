#!/usr/bin/env python3
"""Offline restore: validate the application, preserve prior bytes and replace atomically."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.backup_service import (
    create_snapshot, now_iso, remove_snapshot,
    set_metadata, sync_directory, sync_file, validate_database, write_manifest,
)
from app.services.process_lock import ProcessLock, operation_lock_path


def _verify_manifest(source: Path) -> None:
    manifest = Path(str(source) + ".manifest.json")
    if not manifest.exists():
        return  # Legacy and in-app downloads are validated by their actual schema.
    if manifest.stat().st_size > 16384:
        raise RuntimeError("Backup manifest is too large.")
    try:
        info = json.loads(manifest.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise RuntimeError("Backup manifest is invalid.") from None
    if not isinstance(info, dict) or info.get("application") != "FilamentManager" or info.get("size_bytes") != source.stat().st_size:
        raise RuntimeError("Backup manifest does not match this database.")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if info.get("sha256") != digest.hexdigest():
        raise RuntimeError("Backup checksum does not match its manifest.")


def _preserve_bytes(source: Path, destination: Path) -> None:
    # Copy bytes even when SQLite cannot open the old database. Never overwrite.
    with source.open("rb") as original, destination.open("xb") as saved:
        os.chmod(destination, 0o600)
        shutil.copyfileobj(original, saved, length=1024 * 1024)
        saved.flush()
        os.fsync(saved.fileno())


def restore(source: Path, destination: Path, *, confirm: bool = False,
            quarantine_sidecars: bool = False) -> Path | None:
    if not confirm:
        raise RuntimeError("Explicit --confirm is required; stop the application first.")
    source, destination = Path(source), Path(destination)
    if destination.is_symlink():
        raise RuntimeError("Restore destination must not be a symbolic link.")
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise RuntimeError("Source and destination must be different files.")
    if not source.is_file():
        raise RuntimeError("Backup does not exist.")
    if not destination.parent.is_dir():
        raise RuntimeError("Restore destination directory does not exist.")
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise RuntimeError("Restore source must be a standalone backup without WAL/SHM or journal files; create a verified snapshot first.")
    _verify_manifest(source)
    locks = [ProcessLock(operation_lock_path(destination, name))
             for name in ("application", "recovery", "poll", "backup")]
    acquired = []
    scope = hashlib.sha256(str(destination).encode()).hexdigest()[:16]
    stage_prefix = ".filament-restore-" + scope + "-"
    stage = destination.parent / (stage_prefix + str(uuid4()) + ".sqlite3")
    previous = None
    try:
        for lock in locks:
            if not lock.acquire():
                raise RuntimeError("Application or another recovery operation is active; stop all services first.")
            acquired.append(lock)
            if os.name == "posix":
                intended_owner = destination.stat() if destination.exists() else destination.parent.stat()
                lock_stat = os.fstat(lock.fd)
                if (lock_stat.st_uid, lock_stat.st_gid) != (intended_owner.st_uid, intended_owner.st_gid):
                    # An administrator may recover as root. Newly created lock
                    # files must still be usable by the normal non-root runtime.
                    try:
                        os.fchown(lock.fd, intended_owner.st_uid, intended_owner.st_gid)
                    except OSError as exc:
                        raise RuntimeError("Cannot preserve recovery lock ownership; run recovery as the database owner or an authorized administrator.") from exc
        for orphan in destination.parent.glob(stage_prefix + "*.sqlite3"):
            if orphan.resolve() != source:
                remove_snapshot(orphan)
        sidecars = [Path(str(destination) + suffix) for suffix in ("-wal", "-shm", "-journal")
                    if Path(str(destination) + suffix).exists()]
        if sidecars and not quarantine_sidecars:
            raise RuntimeError("WAL/SHM sidecars exist. Stop and checkpoint, or use --quarantine-sidecars for a stopped crashed instance.")
        old_stat = destination.stat() if destination.exists() else None
        required = source.stat().st_size + (old_stat.st_size if old_stat else 0) + sum(p.stat().st_size for p in sidecars)
        if shutil.disk_usage(destination.parent).free < required + 64 * 1024 * 1024:
            raise RuntimeError("Insufficient space for recovery staging, prior state and storage reserve.")
        create_snapshot(source, stage, timeout_seconds=300)
        with closing(sqlite3.connect(stage)) as db:
            validate_database(db)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "auth_sessions" in tables:
                db.execute("DELETE FROM auth_sessions")
            if "automation_tokens" in tables:
                db.execute("UPDATE automation_tokens SET revoked_at=? WHERE revoked_at IS NULL", (now_iso(),))
            if "worker_leases" in tables:
                db.execute("DELETE FROM worker_leases")
            set_metadata(db, "instance_epoch", str(uuid4()))
            set_metadata(db, "last_restored_at", now_iso())
            set_metadata(db, "restore_token_reissue_required", "1")
            db.commit()
        intended_owner = old_stat or destination.parent.stat()
        if os.name == "posix":
            # Missing databases inherit the data directory owner; the standard
            # Docker volume belongs to UID/GID 10001 even after its DB was lost.
            stage_stat = stage.stat()
            if (stage_stat.st_uid, stage_stat.st_gid) != (intended_owner.st_uid, intended_owner.st_gid):
                try:
                    os.chown(stage, intended_owner.st_uid, intended_owner.st_gid)
                except OSError as exc:
                    raise RuntimeError("Cannot preserve database ownership; run recovery as its owner or an authorized administrator.") from exc
        if old_stat is not None:
            os.chmod(stage, stat.S_IMODE(old_stat.st_mode))
            suffix = now_iso().replace(":", "").replace("-", "") + "-" + uuid4().hex[:8]
            previous = Path(str(destination) + ".pre-restore-" + suffix)
            _preserve_bytes(destination, previous)
            sidecar_names = []
            for sidecar in sidecars:
                suffix_part = str(sidecar)[len(str(destination)):]
                _preserve_bytes(sidecar, Path(str(previous) + suffix_part))
                sidecar_names.append(suffix_part)
            write_manifest(Path(str(previous) + ".quarantine.json"),
                           {"purpose": "Prior bytes preserved before restore; integrity not assumed",
                            "created_at": now_iso(), "sidecars": sidecar_names})
        elif sidecars:
            raise RuntimeError("Orphan sidecars require manual preservation before restoring a missing database.")
        sync_file(stage)
        # All prior bytes are durable before any old sidecar is removed.
        sync_directory(destination.parent)
        for sidecar in sidecars:
            sidecar.unlink()
        os.replace(stage, destination)
        sync_directory(destination.parent)
        return previous
    finally:
        remove_snapshot(stage)
        for lock in reversed(acquired):
            lock.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--confirm", action="store_true", help="Confirm every application service is stopped")
    parser.add_argument("--quarantine-sidecars", action="store_true",
                        help="Preserve crash WAL/SHM files as raw prior-state bytes before replacement")
    args = parser.parse_args()
    try:
        saved = restore(args.backup, args.database, confirm=args.confirm,
                        quarantine_sidecars=args.quarantine_sidecars)
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        parser.exit(1, "Restore refused: " + str(exc) + "\n")
    print("Restored verified backup to", args.database)
    if saved:
        print("Previous bytes retained in", saved)
    print("All restored browser sessions and machine tokens were revoked. Sign in and issue new automation tokens.")
    print("Notification stream identity was reset; the notifier will report the recovery and establish a new baseline.")


if __name__ == "__main__":
    main()
