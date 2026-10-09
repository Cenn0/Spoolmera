"""Durable intent and reconciliation for commands that can change real hardware."""
import sqlite3
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from app.database import session, utc_now
from app.auth import audit


def _assert_printer_available(db, printer_id: int) -> None:
    printer = db.execute('SELECT enabled FROM printers WHERE id=?', (printer_id,)).fetchone()
    if not printer or not printer['enabled']:
        raise HTTPException(409, 'The printer was disabled or removed before this operation.')
    if db.execute('SELECT 1 FROM printer_operations WHERE printer_id=?', (printer_id,)).fetchone():
        raise HTTPException(409, 'A printer operation is active or requires physical-state review.')
    if db.execute("""SELECT 1 FROM printer_commands WHERE printer_id=? AND action='start'
        AND (state IN ('sending','acknowledged','unknown') OR (state='confirmed' AND released_at IS NULL))
        LIMIT 1""", (printer_id,)).fetchone():
        raise HTTPException(409, 'A previous start on this printer still requires review.')


def _assert_material_ready(db, job_id: int) -> None:
    rows = db.execute('''SELECT m.spool_id,SUM(m.estimated_g) AS required_g,
        s.remaining_g,s.archived_at FROM job_materials m JOIN spools s ON s.id=m.spool_id
        WHERE m.job_id=? GROUP BY m.spool_id''', (job_id,)).fetchall()
    if not rows or any(row['archived_at'] is not None or row['remaining_g'] < row['required_g'] for row in rows):
        raise HTTPException(409, 'Mapped material is archived or no longer has sufficient stock. Review current inventory before starting.')
    estimate = db.execute('SELECT estimated_g FROM print_jobs WHERE id=?', (job_id,)).fetchone()[0]
    if sum(row['required_g'] for row in rows) != estimate:
        raise HTTPException(409, 'Material assignments disagree with the stored job estimate. Review this historical mapping before starting.')

def reserve_command(db_path: Path, printer_id: int, job_id: int | None,
                    action: str, actor_id: int) -> str:
    command_id = str(uuid4())
    with session(db_path, write=True) as db:
        if job_id is not None:
            job = db.execute("SELECT status,printer_id,accounting_status FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["status"] != "pending" or job["printer_id"] != printer_id:
                raise HTTPException(status_code=409, detail="Print job is no longer pending.")
        if action == 'start':
            _assert_printer_available(db, printer_id)
            _assert_material_ready(db, job_id)
            if job['accounting_status'] != 'pending':
                raise HTTPException(409, 'This job already has an accounting decision. Register a new job for a new physical print.')
        try:
            db.execute(
                """INSERT INTO printer_commands(id,printer_id,job_id,action,state,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,'sending',?,?,?)""",
                (command_id, printer_id, job_id, action, actor_id, utc_now(), utc_now()),
            )
            if action == 'start':
                db.execute('''INSERT INTO printer_operations
                    (printer_id,operation_id,job_id,kind,state,created_at,updated_at)
                    VALUES(?,?,?,'start','active',?,?)''',
                    (printer_id, command_id, job_id, utc_now(), utc_now()))
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
        if state == 'rejected':
            db.execute('DELETE FROM printer_operations WHERE operation_id=?', (command_id,))
        elif state == 'unknown':
            db.execute("UPDATE printer_operations SET state='unknown',updated_at=? WHERE operation_id=?", (utc_now(), command_id))

def confirm_job_command(db: sqlite3.Connection, job_id: int) -> None:
    db.execute("""UPDATE printer_commands SET state='confirmed',updated_at=?
                  WHERE job_id=? AND action='start'
                  AND state IN ('sending','acknowledged','unknown')""",
               (utc_now(), job_id))

def clear_command(db_path: Path, command_id: str, actor_id: int, reason: str) -> None:
    """Explicit admin attestation that the printer is idle and the operation resolved."""
    with session(db_path, write=True) as db:
        command = db.execute("SELECT * FROM printer_commands WHERE id=?", (command_id,)).fetchone()
        if not command:
            raise HTTPException(status_code=404, detail="Command not found.")
        if command["action"] != "start" or command["state"] not in ("unknown", "acknowledged", "confirmed"):
            raise HTTPException(status_code=409, detail="Only uncertain or unconfirmed start commands can be cleared.")
        job = db.execute("SELECT status FROM print_jobs WHERE id=?", (command["job_id"],)).fetchone()
        if not job:
            raise HTTPException(status_code=409, detail="The associated print job is missing.")
        db.execute("UPDATE printer_commands SET state='cleared',detail=?,updated_at=?,released_at=? WHERE id=?",
                   (reason, utc_now(), utc_now(), command_id))
        db.execute('DELETE FROM printer_operations WHERE operation_id=?', (command_id,))
        if job['status'] == 'printing':
            db.execute("""UPDATE print_jobs SET status='needs_review',
                accounting_status=CASE WHEN accounting_status='pending' THEN 'needs_review' ELSE accounting_status END,
                updated_at=? WHERE id=?""", (utc_now(), command['job_id']))
        audit(db, actor_id, "command_cleared_after_physical_check", "printer", command["printer_id"])


def finish_job_operation(db, job_id: int) -> None:
    """A terminal controller observation releases device coordination, not history."""
    confirm_job_command(db, job_id)
    db.execute("UPDATE printer_commands SET released_at=? WHERE job_id=? AND action='start'", (utc_now(), job_id))
    db.execute("DELETE FROM printer_operations WHERE job_id=? AND kind='start'", (job_id,))


def reserve_upload(db_path: Path, printer_id: int, job_id: int, actor_id: int) -> str:
    operation_id = str(uuid4())
    with session(db_path, write=True) as db:
        _assert_printer_available(db, printer_id)
        job = db.execute('SELECT status,printer_id FROM print_jobs WHERE id=?', (job_id,)).fetchone()
        if not job or job['status'] != 'pending' or job['printer_id'] != printer_id:
            raise HTTPException(409, 'Print job is no longer pending.')
        db.execute('''INSERT INTO printer_operations
            (printer_id,operation_id,job_id,kind,state,created_at,updated_at)
            VALUES(?,?,?,'upload','active',?,?)''',
            (printer_id, operation_id, job_id, utc_now(), utc_now()))
        audit(db, actor_id, 'upload_requested', 'print_job', job_id)
        db.execute('''INSERT INTO printer_operation_history(operation_id,printer_id,job_id,state,actor_id,created_at)
            VALUES(?,?,?,'sending',?,?)''', (operation_id, printer_id, job_id, actor_id, utc_now()))
    return operation_id


def finish_upload(db_path: Path, operation_id: str, *, uncertain=False) -> None:
    with session(db_path, write=True) as db:
        db.execute('''INSERT INTO printer_operation_history(operation_id,printer_id,job_id,state,created_at)
            SELECT operation_id,printer_id,job_id,?,? FROM printer_operations WHERE operation_id=? AND kind='upload'
        ''', ('unknown' if uncertain else 'finished', utc_now(), operation_id))
        if uncertain:
            db.execute("UPDATE printer_operations SET state='unknown',updated_at=? WHERE operation_id=? AND kind='upload'", (utc_now(), operation_id))
        else:
            db.execute("DELETE FROM printer_operations WHERE operation_id=? AND kind='upload'", (operation_id,))


def clear_upload(db_path: Path, printer_id: int, operation_id: str, actor_id: int, reason: str) -> None:
    with session(db_path, write=True) as db:
        db.execute('''INSERT INTO printer_operation_history(operation_id,printer_id,job_id,state,actor_id,detail,created_at)
            SELECT operation_id,printer_id,job_id,'cleared',?,?,? FROM printer_operations
            WHERE printer_id=? AND operation_id=? AND kind='upload' AND state='unknown'
        ''', (actor_id, reason, utc_now(), printer_id, operation_id))
        changed = db.execute("""DELETE FROM printer_operations WHERE printer_id=?
            AND operation_id=? AND kind='upload' AND state='unknown'""", (printer_id, operation_id))
        if not changed.rowcount:
            raise HTTPException(409, 'This upload is no longer awaiting review.')
        audit(db, actor_id, 'upload_cleared_after_physical_check', 'printer', printer_id)
