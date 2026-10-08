"""Material care, weighing and stock alerts; persistent stock changes are ledger-backed."""
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from app.auth import audit
from app.database import session, utc_now
from app.models import WeighInput, DryingInput


def record_weighing(db_path: Path, spool_id: int, payload: WeighInput, actor_id: int) -> dict:
    with session(db_path, write=True) as db:
        spool = db.execute(
            "SELECT initial_g,remaining_g,tare_g FROM spools WHERE id=? AND archived_at IS NULL",
            (spool_id,),
        ).fetchone()
        if spool is None:
            raise HTTPException(404, "Active spool not found.")
        tare = spool["tare_g"] if payload.tare_g is None else payload.tare_g
        if tare > payload.gross_g:
            raise HTTPException(422, "Gross weight must not be smaller than empty spool weight.")
        net = payload.gross_g - tare
        if net > spool["initial_g"]:
            raise HTTPException(409, "Measured filament exceeds registered starting weight.")
        difference = net - spool["remaining_g"]
        if difference:
            db.execute(
                "INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,actor_id,source) "
                "VALUES(?,'adjust',?,?,?,?,?,'weighing')",
                (spool_id, difference, net, payload.note, utc_now(), actor_id),
            )
        db.execute("UPDATE spools SET remaining_g=?,tare_g=?, "
                   "opened=CASE WHEN ? < initial_g THEN 1 ELSE opened END WHERE id=?",
                   (net, tare, net, spool_id))
        audit(db, actor_id, "spool_weigh", "spool", spool_id)
        return {"remaining_g": net, "tare_g": tare, "difference_g": difference}


def record_drying(db_path: Path, spool_id: int, payload: DryingInput, actor_id: int) -> dict:
    try:
        date = datetime.fromisoformat(payload.dried_at.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("timezone missing")
    except (ValueError, OverflowError):
        raise HTTPException(422, "dried_at requires ISO 8601 and a timezone.") from None
    if date.timestamp() > datetime.now(timezone.utc).timestamp() + 60:
        raise HTTPException(422, "Drying cannot be recorded in the future.")
    with session(db_path, write=True) as db:
        if not db.execute("SELECT 1 FROM spools WHERE id=? AND archived_at IS NULL",
                          (spool_id,)).fetchone():
            raise HTTPException(404, "Active spool not found.")
        identifier = db.execute(
            "INSERT INTO drying_records(spool_id,temperature_c,duration_minutes,dried_at,note,actor_id,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (spool_id, payload.temperature_c, payload.duration_minutes,
             date.isoformat(), payload.note, actor_id, utc_now()),
        ).lastrowid
        audit(db, actor_id, "drying_record", "spool", spool_id)
        return {"id": identifier}


def drying_history(db_path: Path, spool_id: int) -> list[dict]:
    with session(db_path) as db:
        if not db.execute("SELECT 1 FROM spools WHERE id=?", (spool_id,)).fetchone():
            raise HTTPException(404, "Spool not found.")
        return [dict(row) for row in db.execute(
            "SELECT id,spool_id,temperature_c,duration_minutes,dried_at,note,created_at "
            "FROM drying_records WHERE spool_id=? ORDER BY dried_at DESC,id DESC LIMIT 200",
            (spool_id,),
        )]


def stock_alerts(db_path: Path) -> list[dict]:
    with session(db_path) as db:
        return [dict(row) for row in db.execute(
            """SELECT s.id AS spool_id,s.uid,p.brand,p.name AS product_name,p.material,
                      s.remaining_g,p.low_stock_threshold_g
               FROM spools s JOIN products p ON p.id=s.product_id
               WHERE s.archived_at IS NULL AND s.remaining_g>0
                 AND s.remaining_g<=p.low_stock_threshold_g
               ORDER BY s.remaining_g ASC,s.id ASC"""
        )]
