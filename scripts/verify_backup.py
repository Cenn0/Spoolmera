#!/usr/bin/env python3
"""Verify a standalone backup and rehearse its upgrade without replacing a database."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import __version__
from app.services.backup_service import BackupError
from app.services.recovery_service import verify_backup


ERROR_MESSAGES = {
    "invalid": "The backup or its checksum manifest is invalid or unsupported.",
    "schema": "The backup is missing structures required by its application schema.",
    "migration": "The backup could not be upgraded and validated with this application version.",
    "changed": "The backup changed during verification; use an unchanged standalone snapshot.",
    "space": "There is not enough free space for verification and the storage reserve.",
    "timeout": "The SQLite snapshot exceeded its configured time limit.",
    "io": "The backup could not be read or the private verification workspace could not be used.",
}


def snapshot_timeout(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Snapshot timeout must be an integer between 1 and 3600 seconds.") from None
    if not 1 <= seconds <= 3600:
        raise argparse.ArgumentTypeError("Snapshot timeout must be between 1 and 3600 seconds.")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Standalone SQLite backup; keep any adjacent manifest with it")
    parser.add_argument("--json", action="store_true", help="Emit one versioned JSON result, without database contents or paths")
    parser.add_argument("--work-dir", type=Path,
                        help="Existing directory for a private temporary workspace; use /data in the Docker container")
    parser.add_argument("--snapshot-timeout-seconds", type=snapshot_timeout, default=300,
                        help="SQLite snapshot time limit, 1–3600 seconds (default 300); excludes hashing and migration")
    args = parser.parse_args(argv)
    try:
        report = verify_backup(args.backup, work_dir=args.work_dir,
                               snapshot_timeout_seconds=args.snapshot_timeout_seconds)
    except (BackupError, OSError, sqlite3.Error, ValueError) as exc:
        code = exc.reason if isinstance(exc, BackupError) else "io" if isinstance(exc, OSError) else "invalid"
        if code not in ERROR_MESSAGES:
            code = "invalid"
        report = {
            "report_version": 1,
            "status": "error",
            "application": "Spoolmera",
            "application_version": __version__,
            "error": {"code": code, "message": ERROR_MESSAGES[code]},
        }
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print("Backup verification failed: " + ERROR_MESSAGES[code], file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"Backup verified with Spoolmera {report['application_version']}.")
        print(f"Schema: {report['source_schema']} -> {report['target_schema']}; "
              f"migration required: {'yes' if report['migration_required'] else 'no'}.")
        print(f"Manifest: {report['manifest_status']}; source bytes: {report['source_size_bytes']}.")
        print("Source SHA-256: " + report["source_sha256"])
        print("The original backup was preserved; no active database was replaced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
