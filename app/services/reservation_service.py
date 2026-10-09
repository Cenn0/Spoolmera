"""Transactional advisory reservations and readable material availability."""
from pathlib import Path
from fastapi import HTTPException
from app.database import session, utc_now
from app.auth import audit


def readiness(db_path: Path, job_id: int) -> dict:
    with session(db_path) as db:
        return _readiness(db, job_id)


def _readiness(db, job_id: int) -> dict:
    job = db.execute("SELECT id,printer_id,status FROM print_jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        raise HTTPException(404, "Print job not found.")
    materials = db.execute(
        """SELECT m.tool,m.spool_id,m.estimated_g,s.remaining_g,s.archived_at,
                  p.brand,p.name AS product_name,
                  (SELECT r.reserved_g FROM job_reservations r
                   WHERE r.job_id=? AND r.spool_id=m.spool_id) AS own_reservation_g,
                  (SELECT COALESCE(SUM(r.reserved_g),0) FROM job_reservations r
                   WHERE r.job_id<>? AND r.spool_id=m.spool_id) AS others_reserved_g,
                  (SELECT ps.tool FROM printer_spool_slots ps
                   WHERE ps.printer_id=? AND ps.spool_id=m.spool_id LIMIT 1) AS loaded_tool
           FROM job_materials m JOIN spools s ON s.id=m.spool_id
           JOIN products p ON p.id=s.product_id
           WHERE m.job_id=? ORDER BY m.tool""",
        (job_id,job_id,job["printer_id"],job_id),
    ).fetchall()
    needed = {}
    for item in materials:
        needed[item["spool_id"]] = needed.get(item["spool_id"],0) + item["estimated_g"]
    result = []
    for row in materials:
        item = dict(row)
        item["available_g"] = max(0, row["remaining_g"] - row["others_reserved_g"])
        item["ready"] = (row["archived_at"] is None and
                         needed[row["spool_id"]] <= item["available_g"])
        item["loaded_match"] = row["loaded_tool"] == row["tool"]
        result.append(item)
    return {"job_id":job_id,"status":job["status"],
            "ready":bool(result) and all(item["ready"] for item in result),
            "materials":result,
            "reserved":any(item["own_reservation_g"] is not None for item in result)}


def reserve(db_path: Path, job_id: int, actor_id: int) -> dict:
    with session(db_path, write=True) as db:
        job = db.execute("SELECT status FROM print_jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(404, "Print job not found.")
        if job["status"] != "pending":
            raise HTTPException(409, "Only pending jobs can reserve inventory.")
        state = _readiness(db, job_id)
        if not state["ready"]:
            raise HTTPException(409, "Insufficient unreserved inventory for this job.")
        amounts = {}
        for row in state["materials"]:
            amounts[row["spool_id"]] = amounts.get(row["spool_id"],0)+row["estimated_g"]
        db.execute("DELETE FROM job_reservations WHERE job_id=?", (job_id,))
        for spool_id, amount in amounts.items():
            db.execute("INSERT INTO job_reservations(job_id,spool_id,reserved_g,created_at) "
                       "VALUES(?,?,?,?)", (job_id,spool_id,amount,utc_now()))
        audit(db, actor_id, "job_reserve", "print_job", job_id)
        return _readiness(db, job_id)


def release(db_path: Path, job_id: int, actor_id: int) -> dict:
    with session(db_path, write=True) as db:
        job = db.execute("SELECT status FROM print_jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(404, "Print job not found.")
        if job["status"] == "printing":
            raise HTTPException(409, "Cannot release while print is in progress.")
        db.execute("DELETE FROM job_reservations WHERE job_id=?", (job_id,))
        audit(db, actor_id, "job_release", "print_job", job_id)
        return _readiness(db, job_id)
