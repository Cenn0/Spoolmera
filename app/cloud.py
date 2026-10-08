"""HMAC-authenticated, vendor-neutral inbound cloud bridge.

Not an undocumented Bambu/Prusa API client: a separate cloud bridge must POST
normalized events. No cloud report independently proves physical consumption.
"""
import hashlib
import hmac
import os
import re
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.auth import audit
from app.database import session, utc_now

SOURCE = re.compile(r"^[A-Z][A-Z0-9_]{0,30}$")
EVENT = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
SIGNATURE = re.compile(r"^[0-9a-f]{64}$")
MAX_EVENT_BYTES = 8192
MAX_AGE_SECONDS = 300


class CloudEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=8, max_length=100)
    job_id: int = Field(gt=0)
    status: Literal["printing", "completed", "failed", "cancelled"]


def verify_cloud_request(source: str, request: Request, body: bytes) -> None:
    if not SOURCE.fullmatch(source):
        raise HTTPException(status_code=404, detail="Unknown cloud adapter.")
    secret = os.getenv("FILAMENT_CLOUD_HMAC_" + source, "")
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Cloud adapter is not configured.")
    stamp = request.headers.get("x-filament-timestamp", "")
    signature = request.headers.get("x-filament-signature", "").removeprefix("sha256=")
    if not stamp.isascii() or not stamp.isdecimal() or len(stamp) > 12 or not SIGNATURE.fullmatch(signature):
        raise HTTPException(status_code=401, detail="Invalid cloud signature.")
    if abs(int(time.time()) - int(stamp)) > MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Expired cloud event.")
    expected = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid cloud signature.")


def register_cloud_routes(app: FastAPI, db_path: Path) -> None:
    @app.post("/api/cloud/hooks/{source}")
    async def receive_cloud_event(source: str, request: Request):
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_EVENT_BYTES:
                raise HTTPException(status_code=413, detail="Cloud event exceeds 8 KiB.")
            chunks.append(chunk)
        body = b"".join(chunks)
        verify_cloud_request(source, request, body)
        try:
            event = CloudEvent.model_validate_json(body)
        except ValidationError:
            raise HTTPException(status_code=422, detail="Invalid cloud event schema.") from None
        if not EVENT.fullmatch(event.event_id):
            raise HTTPException(status_code=422, detail="Invalid cloud event ID.")
        digest = hashlib.sha256(body).hexdigest()
        with session(db_path, write=True) as db:
            old = db.execute(
                "SELECT payload_digest,disposition FROM cloud_event_receipts WHERE source=? AND event_id=?",
                (source, event.event_id),
            ).fetchone()
            if old:
                if old["payload_digest"] != digest:
                    raise HTTPException(status_code=409, detail="Event ID reused with different payload.")
                return {"duplicate": True, "disposition": old["disposition"]}
            job = db.execute("SELECT * FROM print_jobs WHERE id=?", (event.job_id,)).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Tracked job not found.")
            disposition = "recorded"
            if event.status in {"completed", "failed", "cancelled"} and job["status"] in {"pending", "printing"}:
                db.execute(
                    """UPDATE print_jobs SET status='needs_review',note=?,updated_at=?
                       WHERE id=?""",
                    ("Cloud source " + source + " reported " + event.status +
                     "; verify actual material usage before deduction.", utc_now(), event.job_id),
                )
                disposition = "needs_review"
            db.execute(
                """INSERT INTO cloud_event_receipts(source,event_id,job_id,payload_digest,disposition,received_at)
                   VALUES(?,?,?,?,?,?)""",
                (source, event.event_id, event.job_id, digest, disposition, utc_now()),
            )
            audit(db, None, "cloud_" + event.status, "print_job", event.job_id)
        return {"duplicate": False, "disposition": disposition}

    @app.get("/api/cloud/events")
    def list_cloud_events():
        with session(db_path) as db:
            return [dict(row) for row in db.execute(
                """SELECT source,event_id,job_id,disposition,received_at
                   FROM cloud_event_receipts ORDER BY received_at DESC,event_id DESC LIMIT 100"""
            ).fetchall()]
