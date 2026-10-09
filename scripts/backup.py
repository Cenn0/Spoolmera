"""Consistent online SQLite backup with a checksum manifest and resource bounds."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.backup_service import create_snapshot, write_manifest


def create_backup(source: Path, destination: Path, *, timeout_seconds: float = 300,
                  reserve_bytes: int = 64 * 1024 * 1024) -> None:
    manifest = Path(str(destination) + ".manifest.json")
    if manifest.exists():
        raise FileExistsError("Refusing to overwrite an existing backup manifest.")
    info = create_snapshot(source, destination, timeout_seconds=timeout_seconds, reserve_bytes=reserve_bytes)
    write_manifest(manifest, info)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New .sqlite3 backup path")
    parser.add_argument("--database", type=Path,
                        default=Path(os.getenv("FILAMENT_DB_PATH", ".data/filaments.sqlite3")))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 3600:
        parser.error("Timeout must be between 1 and 3600 seconds.")
    create_backup(args.database, args.destination, timeout_seconds=args.timeout_seconds)
    print("Verified SQLite backup and SHA-256 manifest created:", args.destination)
