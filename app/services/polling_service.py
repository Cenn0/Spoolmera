"""Persist polling outcomes so restarts and admin views retain reconciliation diagnostics."""
from pathlib import Path
from app.database import session, utc_now

def record_poll_success(db_path: Path, printer_id: int) -> None:
    with session(db_path, write=True) as db:
        stamp = utc_now()
        db.execute("""INSERT INTO printer_poll_state(printer_id,last_attempt_at,last_success_at,consecutive_failures,last_error)
                      VALUES(?,?,?,0,'')
                      ON CONFLICT(printer_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                      last_success_at=excluded.last_success_at,consecutive_failures=0,last_error=''""",
                   (printer_id, stamp, stamp))

def record_poll_failure(db_path: Path, printer_id: int, error_type: str) -> None:
    with session(db_path, write=True) as db:
        db.execute("""INSERT INTO printer_poll_state(printer_id,last_attempt_at,consecutive_failures,last_error)
                      VALUES(?,?,1,?)
                      ON CONFLICT(printer_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                      consecutive_failures=printer_poll_state.consecutive_failures+1,
                      last_error=excluded.last_error""",
                   (printer_id, utc_now(), error_type[:100]))
