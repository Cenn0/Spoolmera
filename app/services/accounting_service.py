"""Central transactional accounting for manual and printer-driven inventory changes."""
from pathlib import Path
from fastapi import HTTPException
from app.database import session, utc_now
from app.auth import audit
from app.models import MovementInput

def record_manual_movement(db_path: Path, spool_id: int, payload: MovementInput, actor_id: int) -> dict:
    if payload.kind == "consume" and payload.grams <= 0:
        raise HTTPException(status_code=422, detail="Consumption must be greater than zero.")
    if payload.kind == "adjust" and (payload.grams == 0 or not payload.note):
        raise HTTPException(status_code=422, detail="Adjustments require a nonzero amount and an explanation.")
    delta = -payload.grams if payload.kind == "consume" else payload.grams
    with session(db_path, write=True) as db:
        spool = db.execute(
            "SELECT initial_g, remaining_g FROM spools WHERE id=? AND archived_at IS NULL",
            (spool_id,),
        ).fetchone()
        if spool is None:
            raise HTTPException(status_code=404, detail="Spool not found.")
        remaining = spool["remaining_g"] + delta
        if remaining < 0 or remaining > spool["initial_g"]:
            raise HTTPException(status_code=409,
                                detail="Movement would exceed the allowed stock range (0 to original weight).")
        db.execute(
            """UPDATE spools SET remaining_g=?, opened=CASE WHEN ? < 0 THEN 1 ELSE opened END WHERE id=?""",
            (remaining, delta, spool_id),
        )
        movement_id = db.execute(
            """INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,actor_id,source)
               VALUES(?,?,?,?,?,?,?,'manual')""",
            (spool_id, payload.kind, delta, remaining, payload.note, utc_now(), actor_id),
        ).lastrowid
        audit(db, actor_id, "movement_"+payload.kind, "movement", movement_id)
    return {"id": movement_id, "remaining_g": remaining}

def apply_consumption(db, job, actor_id: int | None) -> bool:
    """Atomic and retry-safe accounting across every physical spool in a job."""
    current = db.execute("SELECT * FROM print_jobs WHERE id=?", (job["id"],)).fetchone()
    if not current or current["status"] in ("completed", "cancelled"):
        return False
    mappings = db.execute(
        "SELECT tool,spool_id,estimated_g FROM job_materials WHERE job_id=? ORDER BY tool",
        (current["id"],),
    ).fetchall()
    if not mappings:
        # Compatibility with a pre-v4 database opened by older automation.
        mappings = [{"tool": 0, "spool_id": current["spool_id"],
                     "estimated_g": current["estimated_g"]}]
    amounts: dict[int, int] = {}
    for mapping in mappings:
        spool_id = mapping["spool_id"]
        amounts[spool_id] = amounts.get(spool_id, 0) + mapping["estimated_g"]
    for spool_id, required in amounts.items():
        spool = db.execute("SELECT remaining_g,archived_at FROM spools WHERE id=?", (spool_id,)).fetchone()
        if not spool or spool["archived_at"] or spool["remaining_g"] < required:
            db.execute(
                "UPDATE print_jobs SET status='needs_review',accounting_status='needs_review',note=?,updated_at=? WHERE id=?",
                ("Cannot safely debit: one or more mapped spools are archived or have insufficient stock.",
                 utc_now(), current["id"]),
            )
            return False
    first_movement = None
    for spool_id, required in amounts.items():
        spool = db.execute("SELECT remaining_g FROM spools WHERE id=?", (spool_id,)).fetchone()
        remaining = spool["remaining_g"] - required
        db.execute("UPDATE spools SET remaining_g=?,opened=1 WHERE id=?", (remaining, spool_id))
        movement_id = db.execute(
            """INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,print_job_id,actor_id,source,source_ref)
               VALUES(?,'consume',?,?,?,?,?,?, 'print_job', ?)""",
            (spool_id, -required, remaining, "Print job #" + str(current["id"]) + " — " +
             current["file_name"], utc_now(), current["id"], actor_id, str(current["id"])),
        ).lastrowid
        db.execute(
            "UPDATE job_materials SET movement_id=? WHERE job_id=? AND spool_id=?",
            (movement_id, current["id"], spool_id),
        )
        if first_movement is None:
            first_movement = movement_id
    db.execute(
        "UPDATE print_jobs SET status='completed',accounting_status='debited',movement_id=?,updated_at=? WHERE id=?",
        (first_movement, utc_now(), current["id"]),
    )
    audit(db, actor_id, "job_consumption", "print_job", current["id"])
    return True


