"""Print-job metadata import and idempotent completion-based inventory accounting.

We never execute or forward untrusted G-code. A job refers to a file already on
the user's printer. Moonraker history supplies a unique print-run ID. OctoPrint
polling cannot prove a successful completion; it requires human review.
"""
import asyncio
import logging
import os
import re
import sqlite3
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import audit
from app.database import session, utc_now
from app.printers import moonraker_history, printer_status

LOG = logging.getLogger(__name__)
MAX_GCODE = 16 * 1024 * 1024
GRAMS_COMMENT = re.compile(
    r"(?im)^[ \t]*;\s*(?:filament used \[g\]|filament_weight_g|estimated_filament_weight_g)"
    r"\s*[:=]\s*(\d{1,5}(?:\.\d{1,3})?)\s*$"
)


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    printer_id: int = Field(gt=0)
    spool_id: int = Field(gt=0)
    file_name: str = Field(min_length=3, max_length=180)
    estimated_g: int = Field(gt=0, le=100000)
    note: str = Field(default="", max_length=300)


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern=r"^(debit|discard)$")


def valid_filename(name: str) -> bool:
    if len(name) > 180 or not name.lower().endswith((".gcode", ".gco", ".gc")):
        return False
    if name.startswith("/") or "\\" in name or any(ord(char) < 32 for char in name):
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def estimate_gcode(content: bytes) -> int | None:
    # Header and trailer comments are common slicer metadata locations.
    text = (content[:131072] + b"\n" + content[-131072:]).decode("utf-8", "replace")
    matches = GRAMS_COMMENT.findall(text)
    if not matches:
        return None
    numbers = {round(float(item)) for item in matches}
    if len(numbers) != 1:
        return None
    amount = numbers.pop()
    return amount if 0 < amount <= 100000 else None


def insert_job(db_path: Path, payload: JobInput, actor_id: int) -> int:
    if not valid_filename(payload.file_name):
        raise HTTPException(status_code=422, detail="Expected a safe relative .gcode/.gco/.gc filename.")
    with session(db_path, write=True) as db:
        printer = db.execute("SELECT enabled FROM printers WHERE id=?", (payload.printer_id,)).fetchone()
        spool = db.execute(
            "SELECT remaining_g,archived_at FROM spools WHERE id=?", (payload.spool_id,)
        ).fetchone()
        if not printer or not printer["enabled"]:
            raise HTTPException(status_code=404, detail="Enabled printer not found.")
        if not spool or spool["archived_at"] is not None:
            raise HTTPException(status_code=404, detail="Active spool not found.")
        if spool["remaining_g"] < payload.estimated_g:
            raise HTTPException(status_code=409, detail="Estimated consumption exceeds current stock.")
        try:
            stamp = utc_now()
            job_id = db.execute(
                """INSERT INTO print_jobs(printer_id,spool_id,file_name,estimated_g,note,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (payload.printer_id, payload.spool_id, payload.file_name,
                 payload.estimated_g, payload.note, actor_id, stamp, stamp),
            ).lastrowid
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="An active mapping already exists for this printer and file.") from exc
        audit(db, actor_id, "job_register", "print_job", job_id)
    return job_id


def apply_consumption(db, job, actor_id: int | None) -> bool:
    """Called under BEGIN IMMEDIATE: one movement and one state transition."""
    current = db.execute("SELECT * FROM print_jobs WHERE id=?", (job["id"],)).fetchone()
    if not current or current["status"] in ("completed", "cancelled"):
        return False
    spool = db.execute("SELECT * FROM spools WHERE id=?", (current["spool_id"],)).fetchone()
    if not spool or spool["archived_at"] or spool["remaining_g"] < current["estimated_g"]:
        db.execute("UPDATE print_jobs SET status='needs_review',note=?,updated_at=? WHERE id=?",
                   ("Cannot safely debit: spool archived or stock insufficient.", utc_now(), current["id"]))
        return False
    remaining = spool["remaining_g"] - current["estimated_g"]
    db.execute("UPDATE spools SET remaining_g=?,opened=1 WHERE id=?", (remaining, current["spool_id"]))
    movement_id = db.execute(
        """INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,print_job_id)
           VALUES(?,'consume',?,?,?,?,?)""",
        (current["spool_id"], -current["estimated_g"], remaining,
         "Print job #" + str(current["id"]) + " — " + current["file_name"], utc_now(), current["id"]),
    ).lastrowid
    db.execute(
        "UPDATE print_jobs SET status='completed',movement_id=?,updated_at=? WHERE id=?",
        (movement_id, utc_now(), current["id"]),
    )
    audit(db, actor_id, "job_consumption", "print_job", current["id"])
    return True


def poll_printer(db_path: Path, printer_id: int) -> dict:
    with session(db_path) as db:
        printer = db.execute("SELECT * FROM printers WHERE id=? AND enabled=1", (printer_id,)).fetchone()
        jobs = [dict(row) for row in db.execute(
            "SELECT * FROM print_jobs WHERE printer_id=? AND status IN ('pending','printing')",
            (printer_id,),
        ).fetchall()]
    if not printer:
        raise ValueError("Printer is disabled or missing.")
    if printer["kind"] == "moonraker":
        history = moonraker_history(printer)
        current_status = printer_status(printer)
    else:
        history = []
        current_status = printer_status(printer)
    changed = 0
    for job in jobs:
        outcome = None
        external_id = job["external_job_id"]
        if printer["kind"] == "moonraker":
            # An immutable history ID is the reliable identity of a physical run.
            matched = None
            if external_id:
                matched = next((item for item in history if str(item.get("job_id")) == external_id), None)
            else:
                created = datetime.fromisoformat(job["created_at"]).timestamp()
                candidates = [item for item in history if
                    item.get("filename") == job["file_name"]
                    and isinstance(item.get("start_time"), (int, float))
                    and item["start_time"] >= created - 2
                    and str(item.get("job_id", ""))]
                if candidates:
                    matched = max(candidates, key=lambda item: item["start_time"])
            if not matched:
                continue
            remote_state = matched.get("status")
            external_id = str(matched["job_id"])
            if remote_state == "in_progress":
                outcome = "printing"
            elif remote_state == "completed":
                outcome = "completed" if job["observed_printing"] and job["external_job_id"] == external_id else "needs_review"
            elif remote_state in ("cancelled", "error", "klippy_shutdown", "klippy_disconnect", "interrupted"):
                outcome = "needs_review"
        else:
            state = current_status["state"].lower()
            same_file = current_status["filename"] == job["file_name"]
            if state in ("printing", "paused") and same_file:
                outcome = "printing"
            elif job["observed_printing"] and state not in ("printing", "paused"):
                outcome = "needs_review"
        if not outcome:
            continue
        try:
            with session(db_path, write=True) as db:
                fresh = db.execute("SELECT * FROM print_jobs WHERE id=?", (job["id"],)).fetchone()
                if fresh is None or fresh["status"] not in ("pending", "printing"):
                    continue
                if fresh["external_job_id"] and external_id and fresh["external_job_id"] != external_id:
                    continue
                if outcome == "printing":
                    db.execute(
                        "UPDATE print_jobs SET status='printing',observed_printing=1,external_job_id=?,updated_at=? WHERE id=?",
                        (external_id, utc_now(), job["id"]),
                    )
                elif outcome == "completed":
                    # Recheck durable identity before debiting; the external run must have been seen active.
                    if not fresh["observed_printing"] or fresh["external_job_id"] != external_id:
                        continue
                    apply_consumption(db, fresh, None)
                else:
                    db.execute(
                        "UPDATE print_jobs SET status='needs_review',note=?,updated_at=? WHERE id=?",
                        ("Printer completion not proven or print failed. Confirm actual material usage.",
                         utc_now(), job["id"]),
                    )
                changed += 1
        except sqlite3.IntegrityError:
            # Duplicate external identifiers must never trigger a second debit.
            LOG.warning("Rejected duplicate printer job identity for printer %s", printer_id)
    return {"printer_id": printer_id, "state": current_status["state"],
            "filename": current_status["filename"], "updated_jobs": changed}


def poll_all(db_path: Path) -> None:
    with session(db_path) as db:
        ids = [row[0] for row in db.execute(
            """SELECT DISTINCT p.id FROM printers p JOIN print_jobs j ON j.printer_id=p.id
               WHERE p.enabled=1 AND j.status IN ('pending','printing')"""
        ).fetchall()]
    for printer_id in ids:
        try:
            poll_printer(db_path, printer_id)
        except (ValueError, OSError, sqlite3.Error):
            LOG.warning("Read-only polling failed for printer %s", printer_id)


async def poll_worker(db_path: Path):
    interval = max(10, min(300, int(os.getenv("FILAMENT_PRINTER_POLL_SECONDS", "30"))))
    while True:
        try:
            await asyncio.to_thread(poll_all, db_path)
        except Exception:
            LOG.exception("Unexpected printer polling failure")
        await asyncio.sleep(interval)


def register_job_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/jobs")
    def list_jobs():
        with session(db_path) as db:
            return [dict(row) for row in db.execute(
                """SELECT j.*,p.name AS printer_name,s.uid AS spool_uid,
                          f.brand,f.name AS product_name
                   FROM print_jobs j JOIN printers p ON p.id=j.printer_id
                   JOIN spools s ON s.id=j.spool_id JOIN products f ON f.id=s.product_id
                   ORDER BY j.id DESC LIMIT 200"""
            ).fetchall()]

    @app.post("/api/jobs", status_code=201)
    def add_job(payload: JobInput, request: Request):
        return {"id": insert_job(db_path, payload, request.state.user["id"])}

    @app.post("/api/jobs/import", status_code=201)
    async def import_gcode(
        request: Request,
        printer_id: int = Query(gt=0),
        spool_id: int = Query(gt=0),
        file_name: str = Query(min_length=3, max_length=180),
        estimated_g: int | None = Query(default=None, gt=0, le=100000),
    ):
        if request.headers.get("content-type", "").split(";")[0].strip().lower() not in {
            "application/octet-stream", "text/plain", "text/x.gcode"
        }:
            raise HTTPException(status_code=415, detail="Expected a raw G-code file.")
        if not valid_filename(file_name):
            raise HTTPException(status_code=422, detail="Invalid G-code filename.")
        size = 0
        parts = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_GCODE:
                raise HTTPException(status_code=413, detail="G-code exceeds the 16 MiB import limit.")
            parts.append(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="File is empty.")
        discovered = estimate_gcode(b"".join(parts))
        quantity = estimated_g if estimated_g is not None else discovered
        if quantity is None:
            raise HTTPException(
                status_code=422, detail="Missing unambiguous filament weight (g). Provide estimated_g."
            )
        job_id = insert_job(db_path, JobInput(
            printer_id=printer_id, spool_id=spool_id, file_name=file_name, estimated_g=quantity,
        ), request.state.user["id"])
        return {"id": job_id, "estimated_g": quantity, "weight_source": "manual" if estimated_g else "gcode_comment",
                "file_stored": False}

    @app.post("/api/printers/{printer_id}/poll")
    def manual_poll(printer_id: int):
        try:
            return poll_printer(db_path, printer_id)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/resolve")
    def resolve(job_id: int, payload: Resolution, request: Request):
        with session(db_path, write=True) as db:
            job = db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Print job not found.")
            if job["status"] != "needs_review":
                raise HTTPException(status_code=409, detail="Only jobs requiring review may be resolved.")
            if payload.action == "discard":
                db.execute("UPDATE print_jobs SET status='cancelled',updated_at=? WHERE id=?",
                           (utc_now(), job_id))
                audit(db, request.state.user["id"], "job_discard", "print_job", job_id)
                return {"id": job_id, "status": "cancelled"}
            if not apply_consumption(db, job, request.state.user["id"]):
                raise HTTPException(status_code=409, detail="Spool archived or insufficient stock.")
            return {"id": job_id, "status": "completed"}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: int, request: Request):
        with session(db_path, write=True) as db:
            job = db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Print job not found.")
            if job["status"] not in ("pending", "printing"):
                raise HTTPException(status_code=409, detail="Only pending or tracked jobs can be cancelled.")
            db.execute("UPDATE print_jobs SET status='cancelled',updated_at=? WHERE id=?",
                       (utc_now(), job_id))
            audit(db, request.state.user["id"], "job_cancel_tracking", "print_job", job_id)
        return {"id": job_id, "status": "cancelled"}
