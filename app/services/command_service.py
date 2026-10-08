"""Durable intent and reconciliation for commands that can change real hardware."""
import sqlite3
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from app.database import session, utc_now
from app.auth import audit

def reserve_command(db_path: Path, printer_id: int, job_id: int | None,
                    action: str, actor_id: int) -> str:
    command_id = str(uuid4())
    with session(db_path, write=True) as db:
        if job_id is not None:
            job = db.execute("SELECT status,printer_id FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["status"] != "pending" or job["printer_id"] != printer_id:
                raise HTTPException(status_code=409, detail="Print job is no longer pending.")
        try:
            db.execute(
                """INSERT INTO printer_commands(id,printer_id,job_id,action,state,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,'sending',?,?,?)""",
                (command_id, printer_id, job_id, action, actor_id, utc_now(), utc_now()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409,
                                detail="A previous start may already have reached this printer. Reconcile its command first.") from exc
        audit(db, actor_id, "command_requested_"+action, "printer", printer_id)
    return command_id

def finalize_command(db_path: Path, command_id: str, state: str,
                     *, http_status: int | None = None, detail: str = "") -> None:
    if state not in {"acknowledged", "unknown", "rejected"}:
        raise ValueError("Invalid command finalization state.")
    with session(db_path, write=True) as db:
        db.execute("""UPDATE printer_commands SET state=?,http_status=?,detail=?,updated_at=?
                      WHERE id=? AND state='sending'""",
                   (state, http_status, detail, utc_now(), command_id))

def confirm_job_command(db: sqlite3.Connection, job_id: int) -> None:
    db.execute("""UPDATE printer_commands SET state='confirmed',updated_at=?
                  WHERE job_id=? AND action='start'
                  AND state IN ('sending','acknowledged','unknown')""",
               (utc_now(), job_id))

def clear_command(db_path: Path, command_id: str, actor_id: int, reason: str) -> None:
    """Explicit admin attestation that no physical start occurred."""
    with session(db_path, write=True) as db:
        command = db.execute("SELECT * FROM printer_commands WHERE id=?", (command_id,)).fetchone()
        if not command:
            raise HTTPException(status_code=404, detail="Command not found.")
        if command["action"] != "start" or command["state"] not in ("unknown", "acknowledged"):
            raise HTTPException(status_code=409, detail="Only uncertain or unconfirmed start commands can be cleared.")
        job = db.execute("SELECT status FROM print_jobs WHERE id=?", (command["job_id"],)).fetchone()
        if not job or job["status"] != "pending":
            raise HTTPException(status_code=409, detail="Print job is no longer pending.")
        db.execute("UPDATE printer_commands SET state='cleared',detail=?,updated_at=? WHERE id=?",
                   (reason, utc_now(), command_id))
        audit(db, actor_id, "command_cleared_after_physical_check", "printer", command["printer_id"])
