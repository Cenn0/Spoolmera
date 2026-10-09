"""SQLite-backed bounded lease for the in-process polling scheduler."""
import time
from pathlib import Path
from app.database import session
from app.services.process_lock import ProcessLock, operation_lock_path

def acquire_lease(db_path: Path, name: str, owner: str, *, ttl_seconds: int) -> bool:
    now = int(time.time())
    with session(db_path, write=True) as db:
        result = db.execute("""INSERT INTO worker_leases(name,owner,expires_at) VALUES(?,?,?)
            ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at
            WHERE worker_leases.expires_at <= ? OR worker_leases.owner = excluded.owner""",
            (name, owner, now+ttl_seconds, now))
        return result.rowcount == 1

def release_lease(db_path: Path, name: str, owner: str) -> None:
    with session(db_path, write=True) as db:
        db.execute("DELETE FROM worker_leases WHERE name=? AND owner=?", (name, owner))


def renew_lease(db_path: Path, name: str, owner: str, *, ttl_seconds: int) -> bool:
    """A former owner cannot extend a lease that expired or was reassigned."""
    now = int(time.time())
    with session(db_path, write=True) as db:
        result = db.execute("UPDATE worker_leases SET expires_at=? "
                            "WHERE name=? AND owner=? AND expires_at>?",
                            (now + ttl_seconds, name, owner, now))
        return result.rowcount == 1


def claim_poll_lease(db_path: Path, owner: str, lock: ProcessLock, *, ttl_seconds: int) -> None:
    """Replace an orphan only while holding the single-host kernel polling lock.

    A killed process loses this lock immediately. SQLite expiry is for diagnostics
    and renewal, not proof that a still-running controller request has stopped.
    Physical printer operation leases are deliberately untouched.
    """
    if lock.fd is None or lock.path.resolve() != operation_lock_path(db_path, "poll").resolve():
        raise RuntimeError("Exclusive process polling lock is required.")
    with session(db_path, write=True) as db:
        db.execute("INSERT INTO worker_leases(name,owner,expires_at) VALUES('printer-poll',?,?) "
                   "ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at",
                   (owner, int(time.time()) + ttl_seconds))
