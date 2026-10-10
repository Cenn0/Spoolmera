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
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import audit
from app.services.accounting_service import apply_consumption, reconcile_in_transaction
from app.services.accounting_models import ConsumptionInput
from app.services.command_service import (reserve_command, finalize_command, confirm_job_command,
    finish_job_operation, reserve_upload, finish_upload)
from app.services.polling_service import record_poll_success, record_poll_failure
from app.services.lease_service import acquire_lease, release_lease
from app.infrastructure.printers.adapters import adapter_for
from app.api.contracts import JobResponse
from uuid import uuid4
from app.core.policies import require_editor, require_admin
from app.database import session, utc_now
from app.printers import (
    moonraker_history, moonraker_job, printer_status, require_control, upload_controller_file,
    write_controller, SAFE_UPLOAD_NAME, ControllerRejected
)
from urllib.parse import quote

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


class MaterialMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: int = Field(ge=0, le=15)
    spool_id: int = Field(gt=0)
    estimated_g: int = Field(gt=0, le=100000)


class MultiJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    printer_id: int = Field(gt=0)
    file_name: str = Field(min_length=3, max_length=180)
    materials: list[MaterialMapping] = Field(min_length=1, max_length=8)
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
    """Keep the original single-material API as an explicit T0 translation."""
    return insert_multi_job(db_path, MultiJobInput(
        printer_id=payload.printer_id, file_name=payload.file_name, note=payload.note,
        materials=[MaterialMapping(tool=0, spool_id=payload.spool_id,
                                   estimated_g=payload.estimated_g)],
    ), actor_id)


def insert_multi_job(db_path: Path, payload: MultiJobInput, actor_id: int) -> int:
    """Explicit tool-to-spool assignments; never infer mappings from color."""
    if not valid_filename(payload.file_name):
        raise HTTPException(status_code=422, detail="Expected a safe relative G-code filename.")
    if len({item.tool for item in payload.materials}) != len(payload.materials):
        raise HTTPException(status_code=422, detail="Tool numbers must be unique.")
    total = sum(item.estimated_g for item in payload.materials)
    if total > 100000:
        raise HTTPException(status_code=422, detail="Job total exceeds the supported weight.")
    by_spool: dict[int, int] = {}
    for item in payload.materials:
        by_spool[item.spool_id] = by_spool.get(item.spool_id, 0) + item.estimated_g
    with session(db_path, write=True) as db:
        printer = db.execute("SELECT enabled FROM printers WHERE id=?", (payload.printer_id,)).fetchone()
        if not printer or not printer["enabled"]:
            raise HTTPException(status_code=404, detail="Enabled printer not found.")
        for spool_id, grams in by_spool.items():
            spool = db.execute(
                "SELECT remaining_g,archived_at FROM spools WHERE id=?", (spool_id,)
            ).fetchone()
            if not spool or spool["archived_at"] is not None:
                raise HTTPException(status_code=404, detail="Active spool not found.")
            if spool["remaining_g"] < grams:
                raise HTTPException(status_code=409, detail="Estimated consumption exceeds available spool stock.")
        stamp = utc_now()
        try:
            job_id = db.execute(
                """INSERT INTO print_jobs(printer_id,spool_id,file_name,estimated_g,note,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (payload.printer_id, payload.materials[0].spool_id, payload.file_name,
                 total, payload.note, actor_id, stamp, stamp),
            ).lastrowid
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="An active mapping already exists for this printer and file.") from exc
        db.executemany(
            "INSERT INTO job_materials(job_id,tool,spool_id,estimated_g) VALUES(?,?,?,?)",
            [(job_id, item.tool, item.spool_id, item.estimated_g) for item in payload.materials],
        )
        audit(db, actor_id, "job_register_multi", "print_job", job_id)
    return job_id



def poll_printer(db_path: Path, printer_id: int) -> dict:
    with session(db_path) as db:
        printer = db.execute("SELECT * FROM printers WHERE id=? AND enabled=1", (printer_id,)).fetchone()
        jobs = [dict(row) for row in db.execute(
            "SELECT * FROM print_jobs WHERE printer_id=? AND status IN ('pending','printing')",
            (printer_id,),
        ).fetchall()]
        claimed_ids = {row[0] for row in db.execute(
            "SELECT external_job_id FROM print_jobs WHERE printer_id=? AND external_job_id IS NOT NULL",
            (printer_id,),
        ).fetchall()}
    if not printer:
        raise ValueError("Printer is disabled or missing.")
    adapter = adapter_for(
        printer["kind"], status=printer_status,
        history=moonraker_history, lookup=moonraker_job,
    )
    history = adapter.get_history(printer)
    current_status = adapter.get_status(printer)
    changed = 0
    for job in jobs:
        observation = adapter.observe(printer, job, history, current_status, claimed_ids)
        outcome = observation.outcome
        external_id = observation.external_id
        remote_state = observation.remote_state
        if not outcome:
            continue
        try:
            with session(db_path, write=True) as db:
                fresh = db.execute("SELECT * FROM print_jobs WHERE id=?", (job["id"],)).fetchone()
                if fresh is None or fresh["status"] not in ("pending", "printing"):
                    continue
                if fresh["external_job_id"] and external_id and fresh["external_job_id"] != external_id:
                    continue
                if external_id and remote_state and printer["kind"] == "moonraker":
                    existing_run = db.execute(
                        "SELECT job_id FROM print_runs WHERE printer_id=? AND external_run_id=?",
                        (printer_id, external_id),
                    ).fetchone()
                    if existing_run and existing_run["job_id"] not in (None, job["id"]):
                        LOG.warning("Run identity already belongs to another job; printer=%s", printer_id)
                        continue
                    db.execute(
                        """INSERT INTO print_runs(printer_id,job_id,external_run_id,state,first_seen_at,last_seen_at)
                           VALUES(?,?,?,?,?,?)
                           ON CONFLICT(printer_id,external_run_id)
                           DO UPDATE SET state=excluded.state,last_seen_at=excluded.last_seen_at""",
                        (printer_id, job["id"], external_id, remote_state, utc_now(), utc_now()),
                    )
                if outcome == "printing":
                    confirm_job_command(db, job["id"])
                    db.execute(
                        "UPDATE print_jobs SET status='printing',observed_printing=1,external_job_id=?,updated_at=? WHERE id=?",
                        (external_id, utc_now(), job["id"]),
                    )
                elif outcome == "completed":
                    # Recheck durable identity before debiting; the external run must have been seen active.
                    if not fresh["observed_printing"] or fresh["external_job_id"] != external_id:
                        continue
                    apply_consumption(db, fresh, None)
                    finish_job_operation(db, job['id'])
                else:
                    db.execute(
                        "UPDATE print_jobs SET status='needs_review',accounting_status=CASE WHEN accounting_status IN ('debited','discarded') THEN accounting_status ELSE 'needs_review' END,external_job_id=?,note=?,updated_at=? WHERE id=?",
                        (external_id, "Printer completion not proven, ambiguous history or print failed. Confirm actual material usage.",
                         utc_now(), job["id"]),
                    )
                    if (fresh['observed_printing'] and fresh['external_job_id'] == external_id
                            and remote_state in ('completed', 'cancelled', 'error', 'failed')
                            and current_status['state'].lower() in ('standby', 'complete', 'cancelled', 'operational')):
                        finish_job_operation(db, job['id'])
                changed += 1
        except sqlite3.IntegrityError:
            # Duplicate external identifiers must never trigger a second debit.
            LOG.warning("Rejected duplicate printer job identity for printer %s", printer_id)
    return {"printer_id": printer_id, "state": current_status["state"],
            "filename": current_status["filename"], "updated_jobs": changed}


def poll_all(db_path: Path) -> None:
    with session(db_path) as db:
        ids = [row[0] for row in db.execute(
            "SELECT id FROM printers WHERE enabled=1 ORDER BY id"
        ).fetchall()]
    for printer_id in ids:
        try:
            poll_printer(db_path, printer_id)
            record_poll_success(db_path, printer_id)
        except (ValueError, OSError, sqlite3.Error) as exc:
            record_poll_failure(db_path, printer_id, type(exc).__name__)
            LOG.warning("Read-only polling failed for printer %s", printer_id)


async def poll_worker(db_path: Path, settings=None):
    from app.services.polling_runtime import run_poller
    await run_poller(db_path, poll_all, settings)


def register_job_routes(app: FastAPI, db_path: Path) -> None:
    router = APIRouter()
    @router.get("/api/jobs", response_model=list[JobResponse])
    def list_jobs():
        with session(db_path) as db:
            rows = db.execute(
                """SELECT j.*,p.name AS printer_name,s.uid AS spool_uid,
                          f.brand,f.name AS product_name,
                          (SELECT pc.state FROM printer_commands pc
                           WHERE pc.job_id=j.id AND pc.action='start'
                           ORDER BY pc.rowid DESC LIMIT 1) AS start_command_state
                   FROM print_jobs j JOIN printers p ON p.id=j.printer_id
                   JOIN spools s ON s.id=j.spool_id JOIN products f ON f.id=s.product_id
                   ORDER BY j.id DESC LIMIT 200"""
            ).fetchall()
            jobs = [dict(row) for row in rows]
            for job in jobs:
                job["materials"] = [dict(row) for row in db.execute(
                    """SELECT m.tool,m.spool_id,m.estimated_g,m.movement_id,
                              s.uid AS spool_uid,p.brand,p.name AS product_name
                       FROM job_materials m JOIN spools s ON s.id=m.spool_id
                       JOIN products p ON p.id=s.product_id WHERE m.job_id=? ORDER BY m.tool""",
                    (job["id"],),
                ).fetchall()]
        return jobs

    @router.post("/api/jobs/multi", status_code=201, dependencies=[Depends(require_editor)])
    def add_multi_job(payload: MultiJobInput, request: Request):
        return {"id": insert_multi_job(db_path, payload, request.state.user["id"])}

    @router.post("/api/jobs", status_code=201, dependencies=[Depends(require_editor)])
    def add_job(payload: JobInput, request: Request):
        return {"id": insert_job(db_path, payload, request.state.user["id"])}

    @router.post("/api/jobs/import", status_code=201, dependencies=[Depends(require_editor)])
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

    @router.post("/api/printers/{printer_id}/poll", dependencies=[Depends(require_editor)])
    def manual_poll(printer_id: int):
        try:
            return poll_printer(db_path, printer_id)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/api/jobs/{job_id}/resolve", dependencies=[Depends(require_editor)])
    def resolve(job_id: int, payload: Resolution, request: Request):
        with session(db_path, write=True) as db:
            job = db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Print job not found.")
            if job["status"] != "needs_review":
                raise HTTPException(status_code=409, detail="Only jobs requiring review may be resolved.")
            if payload.action == "discard":
                reconcile_in_transaction(db, job_id, ConsumptionInput(mode='discard',
                    reason='Discard confirmed through the legacy job-review action.'), request.state.user['id'])
                db.execute("UPDATE print_jobs SET status='cancelled',accounting_status='discarded',updated_at=? WHERE id=?",
                           (utc_now(), job_id))
                db.execute("DELETE FROM job_reservations WHERE job_id=?", (job_id,))
                audit(db, request.state.user["id"], "job_discard", "print_job", job_id)
                return {"id": job_id, "status": "cancelled"}
            if not apply_consumption(db, job, request.state.user["id"]):
                raise HTTPException(status_code=409, detail="Spool archived or insufficient stock.")
            return {"id": job_id, "status": "completed"}


    @router.post("/api/jobs/{job_id}/upload", dependencies=[Depends(require_admin)])
    async def upload_to_printer(job_id: int, request: Request, file_name: str = Query(min_length=3, max_length=180)):
        require_control()
        if request.headers.get("content-type", "").split(";")[0].strip().lower() not in {
            "application/octet-stream", "text/plain", "text/x.gcode"
        }:
            raise HTTPException(status_code=415, detail="Expected raw G-code bytes.")
        with session(db_path) as db:
            job = db.execute(
                """SELECT j.*,p.kind,p.base_url,p.token_env,p.enabled
                   FROM print_jobs j JOIN printers p ON p.id=j.printer_id WHERE j.id=?""",
                (job_id,),
            ).fetchone()
        if not job or not job["enabled"]:
            raise HTTPException(status_code=404, detail="Enabled printer job not found.")
        if job["status"] != "pending":
            raise HTTPException(status_code=409, detail="Only pending jobs can receive a file.")
        if file_name != job["file_name"]:
            raise HTTPException(status_code=422, detail="Uploaded filename does not match the mapped job.")
        if job["kind"] == "bambu":
            raise HTTPException(status_code=422, detail="Bambu LAN upload is not supported; transfer via Bambu Studio.")
        if not SAFE_UPLOAD_NAME.fullmatch(job["file_name"]):
            raise HTTPException(status_code=422, detail="Upload requires a flat ASCII G-code filename.")
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_GCODE:
                raise HTTPException(status_code=413, detail="G-code exceeds the 16 MiB limit.")
            chunks.append(chunk)
        if size == 0 or b"\x00" in b"".join(chunks)[:4096]:
            raise HTTPException(status_code=422, detail="G-code must be non-empty plain text.")
        operation_id = reserve_upload(db_path, job['printer_id'], job_id, request.state.user['id'])
        dispatched = False
        try:
            state = await asyncio.to_thread(printer_status, job)
            if state["state"].lower() in ("printing", "paused", "pausing"):
                raise HTTPException(status_code=409, detail="Do not upload while the printer is active.")
            dispatched = True
            status = await asyncio.to_thread(upload_controller_file, job, job["file_name"], b"".join(chunks))
        except BaseException as exc:
            finish_upload(db_path, operation_id, uncertain=dispatched and not isinstance(exc, ControllerRejected))
            if isinstance(exc, ValueError):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            raise
        finish_upload(db_path, operation_id)
        with session(db_path, write=True) as db:
            audit(db, request.state.user["id"], "job_file_upload", "print_job", job_id)
        return {"job_id": job_id, "uploaded": True, "http_status": status,
                "note": "File transferred only; print has not been started."}

    @router.get("/api/jobs/{job_id}/commands")
    def get_job_commands(job_id: int):
        with session(db_path) as db:
            if not db.execute("SELECT id FROM print_jobs WHERE id=?", (job_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Print job not found.")
            return [dict(row) for row in db.execute(
                """SELECT id,action,state,http_status,detail,created_at,updated_at
                   FROM printer_commands WHERE job_id=? ORDER BY created_at DESC""",
                (job_id,),
            ).fetchall()]

    @router.post("/api/jobs/{job_id}/start", dependencies=[Depends(require_admin)])
    def start_printer_job(job_id: int, request: Request):
        require_control()
        with session(db_path) as db:
            job = db.execute(
                """SELECT j.*,p.kind,p.base_url,p.token_env,p.enabled
                   FROM print_jobs j JOIN printers p ON p.id=j.printer_id WHERE j.id=?""",
                (job_id,),
            ).fetchone()
        if not job or not job["enabled"]:
            raise HTTPException(status_code=404, detail="Enabled printer job not found.")
        if job["status"] != "pending":
            raise HTTPException(status_code=409, detail="Only pending jobs can be started.")
        if job["kind"] == "bambu":
            raise HTTPException(status_code=422, detail="Bambu LAN print start is not supported; start via Bambu Studio.")
        try:
            state = printer_status(job)["state"].lower()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        ready = {"standby", "complete", "cancelled"} if job["kind"] == "moonraker" else {"operational"}
        if state not in ready:
            raise HTTPException(status_code=409, detail="Printer is not in a known idle state.")
        # Persist before the physical side effect; a failed response is NOT proof
        # that the printer rejected the command. Never retry an unknown start.
        command_id = reserve_command(db_path, job["printer_id"], job_id, "start",
                                     request.state.user["id"])
        try:
            if job["kind"] == "moonraker":
                route = "/printer/print/start?filename=" + quote(job["file_name"], safe="/")
                status = write_controller(job, route)
            else:
                route = "/api/files/local/" + quote(job["file_name"], safe="/")
                status = write_controller(job, route, body=b'{"command":"select","print":true}',
                                          content_type="application/json")
        except BaseException as exc:
            if isinstance(exc, ControllerRejected):
                finalize_command(db_path, command_id, 'rejected', http_status=exc.http_status,
                                 detail='Controller explicitly rejected the request.')
            else:
                finalize_command(db_path, command_id, "unknown", detail="Confirm the physical state before retrying.")
            if isinstance(exc, ValueError):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            raise
        finalize_command(db_path, command_id, "acknowledged", http_status=status)
        return {"job_id": job_id, "command_id": command_id, "started": True,
                "http_status": status, "note": "Controller acknowledged the request; tracking still awaits independently observed state."}

    @router.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_editor)])
    def cancel(job_id: int, request: Request):
        with session(db_path, write=True) as db:
            job = db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Print job not found.")
            if job["status"] not in ("pending", "printing"):
                raise HTTPException(status_code=409, detail="Only pending or tracked jobs can be cancelled.")
            uncertain_start = db.execute("""SELECT 1 FROM printer_commands WHERE job_id=? AND action='start'
                AND state IN ('sending','acknowledged','unknown','confirmed') LIMIT 1""", (job_id,)).fetchone()
            accounting = job['accounting_status']
            if accounting in ('pending', 'needs_review'):
                accounting = 'needs_review' if job['observed_printing'] or uncertain_start else 'discarded'
            db.execute("UPDATE print_jobs SET status='cancelled',accounting_status=?,updated_at=? WHERE id=?",
                       (accounting, utc_now(), job_id))
            db.execute("DELETE FROM job_reservations WHERE job_id=?", (job_id,))
            audit(db, request.state.user["id"], "job_cancel_tracking", "print_job", job_id)
        return {"id": job_id, "status": "cancelled"}

    app.include_router(router)
