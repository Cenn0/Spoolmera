"""Authenticated scale relay receipts. All measurements require an editor's approval.

An ESP32/ESPHome bridge can sign exact JSON body bytes; no signed message alone
is trusted to change a physical spool's recorded inventory.
"""
import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, Depends, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from app.auth import audit
from app.core.policies import require_editor
from app.database import session, utc_now
from app.api.import_contracts import ScaleMeasurementResponse
from app.models import WeighInput
from app.services.material_service import record_weighing_in_transaction
from app.services.accounting_service import blocking_accounting_jobs

SOURCE = re.compile(r"^[A-Z][A-Z0-9_]{0,30}$")
EVENT = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


class Measurement(BaseModel):
    model_config=ConfigDict(extra="forbid")
    event_id: str = Field(min_length=8,max_length=100)
    spool_uid: UUID
    gross_g: int = Field(ge=0,le=200000)
    tare_g: int | None = Field(default=None,ge=0,le=100000)
    measured_at: AwareDatetime | None = None


class Review(BaseModel):
    model_config=ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["approve","discard"]
    note: str = Field(min_length=10,max_length=500)


def verify(source: str, request: Request, raw: bytes) -> int:
    if not SOURCE.fullmatch(source):
        raise HTTPException(404,"Unknown scale bridge.")
    secret=os.environ.get("FILAMENT_SCALE_HMAC_"+source,"")
    if len(secret)<32:
        raise HTTPException(503,"Scale bridge not configured.")
    stamp=request.headers.get("X-Filament-Timestamp","")
    sig=request.headers.get("X-Filament-Signature","").removeprefix("sha256=")
    if not stamp.isascii() or not stamp.isdecimal() or len(stamp)>12 or not DIGEST.fullmatch(sig):
        raise HTTPException(401,"Invalid signature.")
    if abs(int(time.time())-int(stamp))>300:
        raise HTTPException(401,"Expired measurement.")
    expected=hmac.new(secret.encode(),stamp.encode()+b"."+raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,sig):
        raise HTTPException(401,"Invalid signature.")
    return int(stamp)


def measurement_staleness(receipt, spool) -> str | None:
    if receipt["captured_stock_revision"] is None or receipt["captured_tare_g"] is None:
        return "This older receipt has no stock revision or tare context; take a new measurement."
    if spool["archived_at"] is not None:
        return "This spool was archived after the receipt."
    if (receipt["captured_stock_revision"] != spool["stock_revision"] or
            receipt["captured_tare_g"] != spool["tare_g"]):
        return "Stock or tare changed after this receipt; take a new measurement."
    return None


def register_scale_routes(app: FastAPI, db_path: Path) -> None:
    @app.post("/api/scales/hooks/{source}")
    async def receive_measurement(source: str, request: Request):
        chunks=[];n=0
        async for chunk in request.stream():
            n+=len(chunk)
            if n>8192:
                raise HTTPException(413,"Measurement event exceeds 8 KiB.")
            chunks.append(chunk)
        raw=b"".join(chunks)
        signed_at = verify(source,request,raw)
        try:
            payload=Measurement.model_validate_json(raw)
        except ValidationError:
            raise HTTPException(422,"Invalid measurement event.") from None
        if not EVENT.fullmatch(payload.event_id):
            raise HTTPException(422,"Invalid scale event ID.")
        measured_at = payload.measured_at or datetime.fromtimestamp(signed_at, timezone.utc)
        digest=hashlib.sha256(raw).hexdigest()
        with session(db_path,write=True) as db:
            existing=db.execute(
                "SELECT id,payload_digest,status FROM scale_event_receipts "
                "WHERE source=? AND event_id=?",(source,payload.event_id),
            ).fetchone()
            if existing:
                if existing["payload_digest"]!=digest:
                    raise HTTPException(409,"Event ID reused with different payload.")
                return {"id":existing["id"],"duplicate":True,"status":existing["status"]}
            if abs(measured_at.timestamp() - signed_at) > 300 or measured_at.timestamp() > time.time() + 60:
                raise HTTPException(422, "Measurement time must be recent and cannot be in the future.")
            spool=db.execute("SELECT id,initial_g,tare_g,stock_revision,stock_changed_at FROM spools WHERE uid=? AND archived_at IS NULL",
                             (str(payload.spool_uid),)).fetchone()
            if not spool:
                raise HTTPException(404,"Active spool not found.")
            if payload.measured_at is not None and spool["stock_changed_at"] is not None:
                try:
                    changed = datetime.fromisoformat(spool["stock_changed_at"])
                except ValueError:
                    raise HTTPException(409, "The stored stock-change time is unknown. Verify this spool before submitting a timed measurement.") from None
                if changed.tzinfo is None or payload.measured_at < changed:
                    raise HTTPException(409, "Stock or tare changed after the declared measurement time. Take a new measurement.")
            effective_tare = spool["tare_g"] if payload.tare_g is None else payload.tare_g
            net = payload.gross_g - effective_tare
            if not 0 <= net <= spool["initial_g"]:
                raise HTTPException(422, "Measured net filament is outside the registered spool weight.")
            count=db.execute("SELECT COUNT(*) FROM scale_event_receipts "
                             "WHERE source=? AND status='pending'",(source,)).fetchone()[0]
            if count>=100:
                raise HTTPException(429,"Scale event review backlog is full.")
            identifier=db.execute(
                """INSERT INTO scale_event_receipts
                   (source,event_id,payload_digest,spool_id,gross_g,tare_g,received_at,
                    captured_stock_revision,captured_tare_g,net_g,measured_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (source,payload.event_id,digest,spool["id"],
                 payload.gross_g,payload.tare_g,utc_now(),spool["stock_revision"],
                 spool["tare_g"],net,measured_at.isoformat()),
            ).lastrowid
        return {"id":identifier,"duplicate":False,"status":"pending"}

    @app.get("/api/scales/measurements", response_model=list[ScaleMeasurementResponse],
             dependencies=[Depends(require_editor)])
    def list_measurements(status: Literal["pending","applied","discarded"]="pending",
                          limit: int=Query(default=100,ge=1,le=200)):
        with session(db_path) as db:
            rows = db.execute(
                """SELECT e.id,e.source,e.event_id,e.spool_id,e.gross_g,e.tare_g,e.status,
                          e.received_at,e.reviewed_at,e.measured_at,e.net_g,
                          e.captured_stock_revision,e.captured_tare_g,e.review_note,
                          e.accounting_operation_id,s.uid AS spool_uid,s.stock_revision,
                          s.remaining_g,s.tare_g AS current_tare_g,s.archived_at,
                          p.brand,p.name AS product_name
                   FROM scale_event_receipts e JOIN spools s ON s.id=e.spool_id
                   JOIN products p ON p.id=s.product_id
                   WHERE e.status=? ORDER BY e.id DESC LIMIT ?""",(status,limit)).fetchall()
            output = []
            for row in rows:
                item = dict(row)
                spool = {"stock_revision":row["stock_revision"],
                         "tare_g":row["current_tare_g"],"archived_at":row["archived_at"]}
                item["stale_reason"] = measurement_staleness(row, spool) if row["status"] == "pending" else None
                item["stale"] = item["stale_reason"] is not None
                item["blocking_job_ids"] = blocking_accounting_jobs(db, row["spool_id"]) if row["status"] == "pending" else []
                item.pop("archived_at")
                output.append(item)
            return output

    @app.post("/api/scales/measurements/{event_id}/review",
              dependencies=[Depends(require_editor)])
    def review_measurement(event_id: int, payload: Review, request: Request):
        with session(db_path,write=True) as db:
            row=db.execute("SELECT * FROM scale_event_receipts WHERE id=?",
                           (event_id,)).fetchone()
            if not row:
                raise HTTPException(404,"Scale event not found.")
            if row["status"]!="pending":
                raise HTTPException(409,"Scale event already decided.")
            if payload.action=="approve":
                spool = db.execute("SELECT tare_g,stock_revision,archived_at FROM spools WHERE id=?",
                                   (row["spool_id"],)).fetchone()
                stale = measurement_staleness(row, spool)
                if stale is not None:
                    raise HTTPException(409, stale)
                tare = row["captured_tare_g"] if row["tare_g"] is None else row["tare_g"]
                weighing=WeighInput(gross_g=row["gross_g"],tare_g=tare,
                                   expected_stock_revision=row["captured_stock_revision"],
                                   note="Scale "+row["source"]+": "+payload.note)
                result=record_weighing_in_transaction(db,row["spool_id"],
                                                     weighing,request.state.user["id"])
            else:
                result=None
            state="applied" if payload.action=="approve" else "discarded"
            db.execute("UPDATE scale_event_receipts SET status=?,reviewed_at=?,reviewed_by=?,review_note=? WHERE id=?",
                       (state,utc_now(),request.state.user["id"],payload.note,event_id))
            audit(db,request.state.user["id"],"scale_"+state,"scale_event",event_id)
        return {"id":event_id,"status":state,"weighing":result}
