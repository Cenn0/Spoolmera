"""Local scoped read-only API for optional self-hosted automation.

Machine tokens are hashed in SQLite and are never used to control printers or
write stock. Token values are returned *once*, during admin provisioning.
"""
import hashlib
import re
import secrets
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from app.core.policies import require_admin
from app.database import session, utc_now
from app.auth import audit


class NewToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1,max_length=80)
    scope: str = Field(pattern=r"^(inventory_read|events_read)$")


def authenticate_machine(db_path: Path, request: Request, scope: str) -> None:
    raw = request.headers.get("authorization", "")
    if not re.fullmatch(r"Bearer fmm_[A-Za-z0-9_-]{40,64}", raw):
        raise HTTPException(401, "Valid scoped machine token required.")
    secret = raw[7:]
    digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
    with session(db_path) as db:
        token = db.execute(
            "SELECT id,scope FROM automation_tokens WHERE token_hash=? AND revoked_at IS NULL",
            (digest,),
        ).fetchone()
    if not token or token["scope"] != scope:
        raise HTTPException(403, "Unknown, revoked or insufficiently scoped token.")


def register_automation_routes(app: FastAPI, db_path: Path) -> None:
    @app.post("/api/admin/automation-tokens", status_code=201, dependencies=[Depends(require_admin)])
    def create_token(payload: NewToken, request: Request):
        secret = "fmm_" + secrets.token_urlsafe(40)
        digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
        with session(db_path, write=True) as db:
            token_id = db.execute(
                """INSERT INTO automation_tokens(label,scope,token_hash,created_by,created_at)
                   VALUES(?,?,?,?,?)""",
                (payload.label,payload.scope,digest,request.state.user["id"],utc_now()),
            ).lastrowid
            audit(db,request.state.user["id"],"automation_token_create","automation_token",token_id)
        return {"id":token_id,"label":payload.label,"scope":payload.scope,"token":secret,
                "warning":"Copy now. This secret cannot be read again."}

    @app.get("/api/admin/automation-tokens", dependencies=[Depends(require_admin)])
    def list_tokens():
        with session(db_path) as db:
            return [dict(r) for r in db.execute(
                """SELECT id,label,scope,created_at,revoked_at
                   FROM automation_tokens ORDER BY id DESC LIMIT 200"""
            )]

    @app.delete("/api/admin/automation-tokens/{token_id}", dependencies=[Depends(require_admin)])
    def revoke_token(token_id: int, request: Request):
        with session(db_path, write=True) as db:
            updated = db.execute(
                "UPDATE automation_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (utc_now(),token_id),
            )
            if not updated.rowcount:
                raise HTTPException(404, "Active token not found.")
            audit(db,request.state.user["id"],"automation_token_revoke","automation_token",token_id)
        return {"revoked":True}

    @app.get("/api/automation/v1/spools")
    def machine_spools(request: Request, limit: int=Query(default=100,ge=1,le=200),
                       cursor: int|None=Query(default=None,gt=0)):
        authenticate_machine(db_path,request,"inventory_read")
        with session(db_path) as db:
            rows = db.execute(
                """SELECT s.id,s.uid,p.uid AS product_uid,p.brand,p.name AS product_name,
                          p.material,p.color_name,p.color_hex,s.remaining_g,s.initial_g,
                          s.location,s.opened
                   FROM spools s JOIN products p ON p.id=s.product_id
                   WHERE s.archived_at IS NULL AND (? IS NULL OR s.id>?)
                   ORDER BY s.id ASC LIMIT ?""",
                (cursor,cursor,limit+1),
            ).fetchall()
        records = [dict(row) for row in rows[:limit]]
        return {"schema_version":"1","spools":records,
                "next_cursor":records[-1]["id"] if len(rows)>limit else None}

    @app.get("/api/automation/v1/movements")
    def machine_events(request: Request, after: int=Query(default=0,ge=0),
                       limit: int=Query(default=100,ge=1,le=200)):
        authenticate_machine(db_path,request,"events_read")
        with session(db_path) as db:
            rows = db.execute(
                """SELECT m.id,s.uid AS spool_uid,m.kind,m.delta_g,
                          m.remaining_after_g,m.created_at,m.source,m.source_ref
                   FROM movements m JOIN spools s ON s.id=m.spool_id
                   WHERE m.id>? ORDER BY m.id ASC LIMIT ?""",
                (after,limit+1),
            ).fetchall()
        entries=[dict(r) for r in rows[:limit]]
        return {"schema_version":"1","events":entries,
                "next_after":entries[-1]["id"] if len(rows)>limit else None}
