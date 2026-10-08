"""SQLite-backed bounded lease for the in-process polling scheduler."""
import time
from pathlib import Path
from app.database import session

def acquire_lease(db_path: Path, name: str, owner: str, *, ttl_seconds: int) -> bool:
    now = int(time.time())
    with session(db_path, write=True) as db:
        result = db.execute("""INSERT INTO worker_leases(name,owner,expires_at) VALUES(?,?,?)
            ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at
            WHERE worker_leases.expires_at < ? OR worker_leases.owner = excluded.owner""",
            (name, owner, now+ttl_seconds, now))
        return result.rowcount == 1

def release_lease(db_path: Path, name: str, owner: str) -> None:
    with session(db_path, write=True) as db:
        db.execute("DELETE FROM worker_leases WHERE name=? AND owner=?", (name, owner))
