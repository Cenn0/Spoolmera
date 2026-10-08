"""Consistent online SQLite backup for a self-hosted Filament Manager instance."""
import argparse
import os
import sqlite3
from pathlib import Path

def create_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Database not found: {source}")
    if source.resolve() == destination.resolve():
        raise ValueError("Backup destination must differ from the source database.")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite an existing backup: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as original:
            with sqlite3.connect(str(destination)) as backup:
                original.backup(backup)
                check = backup.execute("PRAGMA integrity_check").fetchone()
                if check is None or check[0] != "ok":
                    raise RuntimeError("Backup failed SQLite integrity verification.")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New .sqlite3 backup path")
    parser.add_argument("--database", type=Path,
                        default=Path(os.getenv("FILAMENT_DB_PATH", ".data/filaments.sqlite3")))
    args = parser.parse_args()
    create_backup(args.database, args.destination)
    print(f"Verified SQLite backup created: {args.destination}")
