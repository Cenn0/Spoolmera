"""Authenticated inventory, label, CSV and read-only integration routes."""
from pathlib import Path
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from app.auth import audit
from app.core.policies import require_editor, require_admin
from app.database import session, utc_now
from app.models import ProductInput, SpoolInput, SpoolUpdate, MovementInput
from app.labels import label_html, qr_svg, spool_public_url
from app.inventory_csv import export_inventory, import_inventory
from app.integrations import get_inventory_snapshot, get_integration_capabilities
from app.services.accounting_service import record_manual_movement
from app.services import inventory_service
from app.services.inventory_service import spool_as_dict

def register_inventory_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/overview")
    def overview():
        return inventory_service.overview(db_path)

    @app.get("/api/products")
    def list_products():
        return inventory_service.list_products(db_path)

    @app.post("/api/products", status_code=201, dependencies=[Depends(require_editor)])
    def add_product(payload: ProductInput, request: Request):
        return inventory_service.add_product(db_path, payload, request.state.user["id"])

    @app.put("/api/products/{product_id}", dependencies=[Depends(require_editor)])
    def update_product(product_id: int, payload: ProductInput, request: Request):
        return inventory_service.update_product(db_path, product_id, payload, request.state.user["id"])

    @app.get("/api/spools")
    def list_spools():
        return inventory_service.list_spools(db_path)

    @app.post("/api/spools", status_code=201, dependencies=[Depends(require_editor)])
    def add_spool(payload: SpoolInput, request: Request):
        return inventory_service.add_spool(db_path, payload, request.state.user["id"])

    @app.patch("/api/spools/{spool_id}", dependencies=[Depends(require_editor)])
    def update_spool(spool_id: int, payload: SpoolUpdate, request: Request):
        return inventory_service.update_spool(db_path, spool_id, payload, request.state.user["id"])

    @app.post("/api/spools/{spool_id}/movements", status_code=201, dependencies=[Depends(require_editor)])
    def add_movement(spool_id: int, payload: MovementInput, request: Request):
        return record_manual_movement(db_path, spool_id, payload, request.state.user["id"])

    @app.get("/api/spools/{spool_id}/movements")
    def spool_movements(spool_id: int):
        return inventory_service.spool_movements(db_path, spool_id)

    @app.get("/api/movements")
    def recent_movements(limit: int = Query(default=30, ge=1, le=200)):
        return inventory_service.recent_movements(db_path, limit)

    @app.post("/api/spools/{spool_id}/archive", dependencies=[Depends(require_editor)])
    def archive_spool(spool_id: int, request: Request):
        return inventory_service.archive_spool(db_path, spool_id, request.state.user["id"])

    # Stable UUIDs identify spools, but are NOT authentication tokens.
    @app.get("/s/{spool_uid}", include_in_schema=False)
    def open_spool(spool_uid: str):
        with session(db_path) as db:
            row = db.execute("SELECT uid FROM spools WHERE uid=?", (spool_uid,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Spool not found.")
        return RedirectResponse(url="/?spool=" + spool_uid, status_code=302)

    @app.get("/api/spools/{spool_uid}/qr.svg", include_in_schema=False)
    def spool_qr(spool_uid: str):
        with session(db_path) as db:
            row = db.execute("SELECT uid FROM spools WHERE uid=?", (spool_uid,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Spool not found.")
        return Response(
            content=qr_svg(spool_public_url(spool_uid)),
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-store",
                     "Content-Security-Policy": "default-src 'none'; sandbox"},
        )

    @app.get("/labels/{spool_uid}", response_class=HTMLResponse, include_in_schema=False)
    def print_label(spool_uid: str):
        with session(db_path) as db:
            row = db.execute(
                """SELECT s.uid, s.id, s.remaining_g, s.initial_g,
                          p.brand, p.name, p.material, p.color_name
                   FROM spools s JOIN products p ON p.id=s.product_id
                   WHERE s.uid=?""", (spool_uid,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Spool not found.")
        return HTMLResponse(
            content=label_html(dict(row)),
            headers={"Cache-Control": "no-store",
                     "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'"},
        )

    @app.get("/api/export/inventory.csv")
    def download_inventory():
        with session(db_path) as db:
            content = export_inventory(db)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="filament-inventory-v1.csv"',
                     "Cache-Control": "no-store"},
        )

    @app.post("/api/import/inventory.csv", dependencies=[Depends(require_editor)])
    async def upload_inventory(request: Request, dry_run: bool = Query(default=True)):
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "text/csv":
            raise HTTPException(status_code=415, detail="The request must use Content-Type: text/csv.")
        size = 0
        parts = []
        async for part in request.stream():
            size += len(part)
            if size > 2 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="CSV exceeds the 2 MiB limit.")
            parts.append(part)
        try:
            csv_data = b"".join(parts).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded.") from None
        with session(db_path, write=True) as db:
            result = import_inventory(db, csv_data, dry_run=dry_run)
            if not dry_run:
                audit(db, request.state.user["id"], "csv_import", "inventory", None)
            return result

    @app.get("/api/integrations/v1/capabilities")
    def integration_capabilities():
        return get_integration_capabilities()

    @app.get("/api/integrations/v1/spools")
    def integration_spools():
        with session(db_path) as db:
            return get_inventory_snapshot(db)


