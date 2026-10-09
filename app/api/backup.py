"""Consistent authenticated SQLite snapshot download.

Restoration must happen offline through a separate operator-owned command.
"""
import os
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from app.core.policies import require_admin

MAX_BACKUP_BYTES = 256 * 1024 * 1024


def register_backup_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/admin/backup.sqlite3", dependencies=[Depends(require_admin)])
    def download_backup():
        # An API download copies the database once; the existing SQLite backup CLI
        # remains recommended for larger instances.
        try:
            if db_path.stat().st_size > MAX_BACKUP_BYTES:
                raise HTTPException(413, "Database too large for in-app download; use scripts/backup.py.")
        except OSError as exc:
            raise HTTPException(503, "Database is unavailable.") from exc
        fd, snapshot = tempfile.mkstemp(prefix=".filament-snapshot-", suffix=".sqlite3",
                                        dir=str(db_path.parent))
        os.close(fd)
        def cleanup() -> None:
            # A WAL-mode source can produce snapshot -wal/-shm companions.
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(snapshot + suffix)
                except FileNotFoundError:
                    pass
        try:
            with closing(sqlite3.connect(str(db_path))) as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target, pages=1000, sleep=0.01)
                target.execute("PRAGMA journal_mode=DELETE")
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise HTTPException(503, "Snapshot integrity verification failed.")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            return FileResponse(
                snapshot, filename=f"filament-manager-{stamp}.sqlite3",
                media_type="application/vnd.sqlite3",
                headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"},
                background=BackgroundTask(cleanup),
            )
        except BaseException:
            cleanup()
            raise
