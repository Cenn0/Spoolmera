"""Advisory material planning, not physical printer/feeder control."""
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi import FastAPI, Depends, HTTPException, Request
from app.core.policies import require_editor
from app.auth import audit
from app.database import session, utc_now
from app.services.reservation_service import readiness, reserve, release


class SlotAssignment(BaseModel):
    spool_id: int = Field(gt=0)


def register_planning_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/jobs/{job_id}/readiness")
    def job_readiness(job_id: int):
        return readiness(db_path, job_id)

    @app.post("/api/jobs/{job_id}/reservation", dependencies=[Depends(require_editor)])
    def reserve_job(job_id: int, request: Request):
        return reserve(db_path, job_id, request.state.user["id"])

    @app.delete("/api/jobs/{job_id}/reservation", dependencies=[Depends(require_editor)])
    def release_job(job_id: int, request: Request):
        return release(db_path, job_id, request.state.user["id"])

    @app.get("/api/printers/{printer_id}/slots")
    def printer_slots(printer_id: int):
        with session(db_path) as db:
            if not db.execute("SELECT 1 FROM printers WHERE id=?", (printer_id,)).fetchone():
                raise HTTPException(404, "Printer not found.")
            return [dict(row) for row in db.execute(
                """SELECT ps.tool,ps.spool_id,s.uid AS spool_uid,p.brand,p.name AS product_name
                   FROM printer_spool_slots ps JOIN spools s ON s.id=ps.spool_id
                   JOIN products p ON p.id=s.product_id
                   WHERE ps.printer_id=? ORDER BY ps.tool""", (printer_id,)
            )]

    @app.put("/api/printers/{printer_id}/slots/{tool}", dependencies=[Depends(require_editor)])
    def assign_slot(printer_id: int, tool: int, payload: SlotAssignment, request: Request):
        if not 0 <= tool <= 15:
            raise HTTPException(422, "Tool number must be between 0 and 15.")
        with session(db_path, write=True) as db:
            if not db.execute("SELECT 1 FROM printers WHERE id=? AND enabled=1",
                              (printer_id,)).fetchone():
                raise HTTPException(404, "Enabled printer not found.")
            if not db.execute("SELECT 1 FROM spools WHERE id=? AND archived_at IS NULL",
                              (payload.spool_id,)).fetchone():
                raise HTTPException(404, "Active spool not found.")
            conflict = db.execute("SELECT printer_id,tool FROM printer_spool_slots "
                                  "WHERE spool_id=?", (payload.spool_id,)).fetchone()
            if conflict and (conflict["printer_id"],conflict["tool"]) != (printer_id,tool):
                raise HTTPException(409, "This physical spool is assigned to another slot.")
            db.execute("INSERT INTO printer_spool_slots(printer_id,tool,spool_id,updated_at) "
                       "VALUES(?,?,?,?) ON CONFLICT(printer_id,tool) DO UPDATE SET "
                       "spool_id=excluded.spool_id,updated_at=excluded.updated_at",
                       (printer_id,tool,payload.spool_id,utc_now()))
            audit(db,request.state.user["id"],"slot_assign","printer",printer_id)
        return {"printer_id":printer_id,"tool":tool,"spool_id":payload.spool_id}

    @app.delete("/api/printers/{printer_id}/slots/{tool}", dependencies=[Depends(require_editor)])
    def unload_slot(printer_id: int, tool: int, request: Request):
        with session(db_path, write=True) as db:
            result = db.execute("DELETE FROM printer_spool_slots WHERE printer_id=? AND tool=?",
                                (printer_id,tool))
            if not result.rowcount:
                raise HTTPException(404, "Slot mapping not found.")
            audit(db,request.state.user["id"],"slot_unload","printer",printer_id)
        return {"unloaded":True}
