"""Bounded authenticated SQLite snapshots. Restoration remains an offline action."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from app.core.policies import require_admin
from app.core.settings import Settings
from app.database import session
from app.services.backup_service import BackupError, create_snapshot, remove_snapshot, set_metadata
from app.services.process_lock import ProcessLock, operation_lock_path

MAX_BACKUP_BYTES = 256 * 1024 * 1024


class SnapshotResponse(FileResponse):
    """Release space and the download slot even when a client disconnects."""
    def __init__(self, path: Path, lock: ProcessLock, **kwargs):
        super().__init__(path, **kwargs)
        self.snapshot_path = path
        self.snapshot_lock = lock

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                remove_snapshot(self.snapshot_path)
            finally:
                self.snapshot_lock.release()


def _record_status(db_path: Path, **values: str) -> None:
    if not db_path.is_file():
        return
    try:
        with session(db_path, write=True) as db:
            for key, value in values.items():
                set_metadata(db, "backup_" + key, value)
    except sqlite3.Error:
        # A full/unavailable disk can also prevent recording the original failure.
        pass


def register_backup_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/admin/backup.sqlite3", dependencies=[Depends(require_admin)])
    def download_backup(request: Request):
        settings = getattr(request.app.state, "settings", None) or Settings.from_environment()
        lock = ProcessLock(operation_lock_path(db_path, "backup"))
        try:
            acquired = lock.acquire()
        except OSError:
            raise HTTPException(503, "The backup operation slot is unavailable.") from None
        if not acquired:
            raise HTTPException(429, "A database backup is already running or downloading.")
        scope = hashlib.sha256(str(db_path.resolve()).encode()).hexdigest()[:16]
        prefix = ".filament-snapshot-" + scope + "-"
        snapshot = db_path.parent / (prefix + str(uuid4()) + ".sqlite3")
        try:
            # Orphans can only belong to a dead process: this exclusive slot covers
            # generation and the entire response lifetime, including disconnects.
            for orphan in db_path.parent.glob(prefix + "*.sqlite3"):
                remove_snapshot(orphan)
            info = create_snapshot(db_path, snapshot, max_bytes=min(MAX_BACKUP_BYTES, settings.backup_max_bytes),
                                   timeout_seconds=settings.backup_timeout_seconds,
                                   reserve_bytes=settings.storage_reserve_bytes)
            _record_status(db_path, last_success_at=info["created_at"],
                           last_size_bytes=str(info["size_bytes"]), last_error="")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            return SnapshotResponse(snapshot, lock, filename=f"spoolmera-{stamp}.sqlite3",
                                    media_type="application/vnd.sqlite3",
                                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                             "X-Backup-SHA256": info["sha256"]})
        except BaseException as exc:
            try:
                remove_snapshot(snapshot)
            finally:
                lock.release()
            if isinstance(exc, BackupError):
                _record_status(db_path, last_error=str(exc))
                code = {"size": 413, "space": 507, "timeout": 504}.get(exc.reason, 503)
                raise HTTPException(code, str(exc)) from None
            if isinstance(exc, (OSError, sqlite3.Error)):
                _record_status(db_path, last_error="Database snapshot could not be created.")
                raise HTTPException(503, "Database snapshot could not be created.") from None
            raise
