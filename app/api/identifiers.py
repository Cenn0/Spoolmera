"""Optional tag identity lookup; NFC/OpenPrintTag identifiers are NOT credentials.

The server never trusts a scanned tag as proof of physical spool possession.
"""
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel, ConfigDict, Field
from app.auth import audit
from app.core.policies import require_editor
from app.database import session, utc_now

ID = re.compile(r"^[A-Za-z0-9:_-]{8,128}$")
NAMESPACES = frozenset({"nfc","openprinttag","custom"})


class IdentifierInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str = Field(pattern=r"^(nfc|openprinttag|custom)$")
    external_id: str = Field(min_length=8,max_length=128,pattern=r"^[A-Za-z0-9:_-]{8,128}$")


def register_identifier_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/spools/{spool_id}/identifiers")
    def list_spool_identifiers(spool_id: int):
        with session(db_path) as db:
            if not db.execute("SELECT 1 FROM spools WHERE id=?",(spool_id,)).fetchone():
                raise HTTPException(404,"Spool not found.")
            return [dict(row) for row in db.execute(
                "SELECT namespace,external_id,created_at FROM spool_identifiers "
                "WHERE spool_id=? ORDER BY namespace,external_id",(spool_id,))]

    @app.get("/api/identifiers/{namespace}/{external_id}")
    def resolve_identifier(namespace: str, external_id: str):
        if namespace not in NAMESPACES or not ID.fullmatch(external_id):
            raise HTTPException(422,"Unsupported tag namespace or identifier.")
        with session(db_path) as db:
            row=db.execute(
                """SELECT s.id,s.uid,s.archived_at,p.brand,p.name AS product_name
                   FROM spool_identifiers i JOIN spools s ON s.id=i.spool_id
                   JOIN products p ON p.id=s.product_id
                   WHERE i.namespace=? AND i.external_id=?""",
                (namespace,external_id),
            ).fetchone()
        if not row:
            raise HTTPException(404,"Unknown spool tag.")
        return dict(row)

    @app.post("/api/spools/{spool_id}/identifiers",status_code=201,
              dependencies=[Depends(require_editor)])
    def add_identifier(spool_id: int, payload: IdentifierInput, request: Request):
        with session(db_path,write=True) as db:
            if not db.execute("SELECT 1 FROM spools WHERE id=? AND archived_at IS NULL",
                              (spool_id,)).fetchone():
                raise HTTPException(404,"Active spool not found.")
            found=db.execute(
                "SELECT spool_id FROM spool_identifiers WHERE namespace=? AND external_id=?",
                (payload.namespace,payload.external_id),
            ).fetchone()
            if found:
                if found["spool_id"] == spool_id:
                    return {"spool_id":spool_id,"already_registered":True}
                raise HTTPException(409,"Tag identifier belongs to another physical spool.")
            db.execute(
                "INSERT INTO spool_identifiers(namespace,external_id,spool_id,created_at) "
                "VALUES(?,?,?,?)",
                (payload.namespace,payload.external_id,spool_id,utc_now()),
            )
            audit(db,request.state.user["id"],"tag_register","spool",spool_id)
        return {"spool_id":spool_id,"already_registered":False}

    @app.delete("/api/spools/{spool_id}/identifiers/{namespace}/{external_id}",
                dependencies=[Depends(require_editor)])
    def remove_identifier(spool_id: int, namespace: str, external_id: str,
                          request: Request):
        if namespace not in NAMESPACES or not ID.fullmatch(external_id):
            raise HTTPException(422,"Invalid tag reference.")
        with session(db_path,write=True) as db:
            result=db.execute(
                "DELETE FROM spool_identifiers WHERE spool_id=? AND namespace=? AND external_id=?",
                (spool_id,namespace,external_id),
            )
            if not result.rowcount:
                raise HTTPException(404,"Tag mapping not found.")
            audit(db,request.state.user["id"],"tag_remove","spool",spool_id)
        return {"deleted":True}
