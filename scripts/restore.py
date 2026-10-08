#!/usr/bin/env python3
"""Offline, fail-closed SQLite restore for a stopped FilamentManager instance.

Refuses active WAL sidecars, verifies a consistent snapshot and preserves a
pre-restore backup before atomically replacing the database. Never runs inside
the live API process.
"""
import argparse
import os
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from app.infrastructure.database.migrations import CURRENT_SCHEMA_VERSION


def _integrity(db:sqlite3.Connection)->None:
    if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
        raise RuntimeError("SQLite integrity check failed.")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError("SQLite foreign-key integrity check failed.")
    version=db.execute("PRAGMA user_version").fetchone()[0]
    if version>CURRENT_SCHEMA_VERSION:
        raise RuntimeError("Backup schema is newer than supported application version.")


def restore(source:Path,destination:Path,*,confirm:bool=False)->Path|None:
    if not confirm:
        raise RuntimeError("Explicit --confirm is required; stop the application first.")
    source=source.resolve()
    destination=destination.resolve()
    if source==destination:
        raise RuntimeError("Source and destination must be different files.")
    if not source.is_file():
        raise RuntimeError("Backup does not exist.")
    if destination.parent.exists() is False:
        raise RuntimeError("Restore destination directory does not exist.")
    if any(Path(str(destination)+suffix).exists() for suffix in ("-wal","-shm")):
        raise RuntimeError("WAL/SHM sidecars exist. Stop and checkpoint the application before restore.")
    fd,staging=tempfile.mkstemp(prefix=".filament-restore-",suffix=".sqlite3",
                                dir=str(destination.parent))
    os.close(fd)
    stage=Path(staging)
    previous=None
    try:
        uri="file:"+quote(str(source),safe="/")+ "?mode=ro"
        with sqlite3.connect(uri,uri=True) as src,sqlite3.connect(stage) as dst:
            _integrity(src)
            src.backup(dst,pages=1000,sleep=0.01)
            dst.execute("PRAGMA journal_mode=DELETE")
            _integrity(dst)
        if destination.exists():
            backup_suffix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            previous=Path(str(destination)+".pre-restore-"+backup_suffix)
            if previous.exists():
                raise RuntimeError("Pre-restore backup path already exists.")
            with sqlite3.connect(destination) as src,sqlite3.connect(previous) as dst:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                _integrity(dst)
            os.chmod(stage,stat.S_IMODE(destination.stat().st_mode))
        os.replace(stage,destination)
        return previous
    finally:
        if stage.exists():
            stage.unlink()


def main()->None:
    cli=argparse.ArgumentParser(description="Offline Filament Manager database recovery")
    cli.add_argument("backup",type=Path)
    cli.add_argument("database",type=Path)
    cli.add_argument("--confirm",action="store_true",
                     help="Confirm the service is completely stopped")
    args=cli.parse_args()
    try:
        saved=restore(args.backup,args.database,confirm=args.confirm)
    except (RuntimeError,OSError,sqlite3.Error) as exc:
        cli.exit(1,"Restore refused: "+str(exc)+"\n")
    print("Restored verified backup to",args.database)
    if saved:
        print("Previous state retained in",saved)


if __name__=="__main__":
    main()
