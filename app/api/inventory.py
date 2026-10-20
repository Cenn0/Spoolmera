"""Authenticated inventory, label, CSV and read-only integration routes."""
from pathlib import Path
from datetime import date
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from app.auth import audit
from app.core.policies import require_editor, require_admin
from app.database import session, utc_now
from app.models import ProductInput, SpoolInput, SpoolUpdate, SpoolBatchInput, MovementInput, WeighInput, DryingInput
from app.labels import label_html, labels_html, label_language, qr_svg, spool_public_url
from app.inventory_csv import export_inventory, import_inventory
from app.integrations import get_inventory_snapshot, get_integration_capabilities
from app.services.accounting_service import record_manual_movement
from app.services import inventory_service
from app.services import inventory_query_service
from app.services.movement_csv_service import stream_movements
from app.services.material_service import record_weighing, record_drying, drying_history, stock_alerts
from app.services.inventory_service import spool_as_dict
from app.api.import_contracts import CsvPreviewResponse
from app.api.contracts import (
    OverviewResponse, ProductResponse, SpoolResponse, SpoolPageResponse, CapabilitiesResponse,
    MovementPageResponse, SpoolBatchResponse, RestockResponse,
)

def register_inventory_routes(app: FastAPI, db_path: Path) -> None:
    router = APIRouter()
    @router.get("/api/overview", response_model=OverviewResponse)
    def overview():
        return inventory_service.overview(db_path)

    @router.get("/api/products", response_model=list[ProductResponse])
    def list_products():
        return inventory_service.list_products(db_path)

    @router.post("/api/products", status_code=201, dependencies=[Depends(require_editor)])
    def add_product(payload: ProductInput, request: Request):
        return inventory_service.add_product(db_path, payload, request.state.user["id"])

    @router.put("/api/products/{product_id}", dependencies=[Depends(require_editor)])
    def update_product(product_id: int, payload: ProductInput, request: Request):
        return inventory_service.update_product(db_path, product_id, payload, request.state.user["id"])

    @router.get("/api/inventory/v2/spools", response_model=SpoolPageResponse)
    def paginated_spools(limit: int = Query(default=50, ge=1, le=200),
                         cursor: int | None = Query(default=None, gt=0),
                         material: str | None = Query(default=None, min_length=1, max_length=32)):
        """Cursor pagination for large inventories without changing the v1 API."""
        clauses = ["s.archived_at IS NULL"]
        params: list[object] = []
        if cursor is not None:
            clauses.append("s.id < ?")
            params.append(cursor)
        if material is not None:
            clauses.append("p.material = ?")
            params.append(material.upper())
        query = """SELECT s.*, p.brand, p.name AS product_name, p.material,
                          p.color_name, p.color_hex, p.diameter_mm, p.low_stock_threshold_g
                   FROM spools s JOIN products p ON p.id=s.product_id
                   WHERE """ + " AND ".join(clauses) + " ORDER BY s.id DESC LIMIT ?"
        with session(db_path) as db:
            rows = db.execute(query, (*params, limit + 1)).fetchall()
        has_more = len(rows) > limit
        items = [spool_as_dict(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["id"] if has_more else None}

    @router.get("/api/spools", response_model=list[SpoolResponse])
    def list_spools():
        return inventory_service.list_spools(db_path)

    @router.get('/api/spools/page', response_model=SpoolPageResponse)
    def spool_page(archived: Literal['active', 'archived', 'all'] = 'active',
                   before_id: int | None = Query(default=None, gt=0),
                   limit: int = Query(default=50, ge=1, le=200),
                   q: str | None = Query(default=None, min_length=1, max_length=120),
                   material: str | None = Query(default=None, min_length=1, max_length=32),
                   status: Literal['sealed', 'opened', 'empty'] | None = None,
                   product_id: int | None = Query(default=None, gt=0),
                   low_stock: bool = False):
        return inventory_query_service.spool_page(db_path, archived=archived,
            before_id=before_id, limit=limit, q=q, material=material, status=status, product_id=product_id, low_stock=low_stock)

    @router.get('/api/spools/by-uid/{spool_uid}', response_model=SpoolResponse)
    def spool_by_uid(spool_uid: UUID):
        return inventory_query_service.spool_by_uid(db_path, str(spool_uid))

    @router.post('/api/spools/batch', status_code=201, response_model=SpoolBatchResponse,
                 dependencies=[Depends(require_editor)])
    def spool_batch(payload: SpoolBatchInput, request: Request):
        return inventory_query_service.create_batch(db_path, payload, request.state.user['id'])

    @router.get('/api/inventory/restock', response_model=RestockResponse)
    def restock():
        return inventory_query_service.restock(db_path)

    @router.post("/api/spools", status_code=201, dependencies=[Depends(require_editor)])
    def add_spool(payload: SpoolInput, request: Request):
        return inventory_service.add_spool(db_path, payload, request.state.user["id"])

    @router.patch("/api/spools/{spool_id}", dependencies=[Depends(require_editor)])
    def update_spool(spool_id: int, payload: SpoolUpdate, request: Request):
        return inventory_service.update_spool(db_path, spool_id, payload, request.state.user["id"])

    @router.post("/api/spools/{spool_id}/movements", status_code=201, dependencies=[Depends(require_editor)])
    def add_movement(spool_id: int, payload: MovementInput, request: Request):
        return record_manual_movement(db_path, spool_id, payload, request.state.user["id"])

    @router.get("/api/spools/{spool_id}/movements")
    def spool_movements(spool_id: int):
        return inventory_service.spool_movements(db_path, spool_id)

    @router.get("/api/inventory/alerts")
    def inventory_alerts():
        return stock_alerts(db_path)

    @router.post("/api/spools/{spool_id}/weigh", dependencies=[Depends(require_editor)])
    def weigh_spool(spool_id: int, payload: WeighInput, request: Request):
        return record_weighing(db_path, spool_id, payload, request.state.user["id"])

    @router.get("/api/spools/{spool_id}/drying")
    def get_drying(spool_id: int):
        return drying_history(db_path, spool_id)

    @router.post("/api/spools/{spool_id}/drying", status_code=201,
                 dependencies=[Depends(require_editor)])
    def add_drying(spool_id: int, payload: DryingInput, request: Request):
        return record_drying(db_path, spool_id, payload, request.state.user["id"])

    @router.get("/api/movements")
    def recent_movements(limit: int = Query(default=30, ge=1, le=200)):
        return inventory_service.recent_movements(db_path, limit)

    @router.get('/api/movements/page', response_model=MovementPageResponse)
    def movement_page(before_id: int | None = Query(default=None, gt=0),
                      limit: int = Query(default=50, ge=1, le=200),
                      spool_id: int | None = Query(default=None, gt=0),
                      job_id: int | None = Query(default=None, gt=0),
                      actor_id: int | None = Query(default=None, gt=0),
                      source: str | None = Query(default=None, min_length=1, max_length=80),
                      q: str | None = Query(default=None, min_length=1, max_length=120),
                      kind: Literal['initial', 'consume', 'adjust'] | None = None,
                      from_date: date | None = None, to_date: date | None = None):
        return inventory_query_service.movements_page(db_path, before_id=before_id,
            limit=limit, spool_id=spool_id, job_id=job_id, actor_id=actor_id, source=source,
            from_date=from_date, to_date=to_date, kind=kind, q=q)

    @router.get('/api/movements/export.csv')
    def export_movement_history(
        spool_id: int | None = Query(default=None, gt=0),
        job_id: int | None = Query(default=None, gt=0),
        actor_id: int | None = Query(default=None, gt=0),
        source: str | None = Query(default=None, min_length=1, max_length=80),
        q: str | None = Query(default=None, min_length=1, max_length=120),
        kind: Literal['initial', 'consume', 'adjust'] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ):
        # This endpoint uses exactly the same filters as /api/movements/page.
        # Validate dates before starting the stream so malformed input returns 422.
        records = stream_movements(
            db_path, spool_id=spool_id, job_id=job_id, actor_id=actor_id,
            source=source, q=q, kind=kind, from_date=from_date, to_date=to_date,
        )
        return StreamingResponse(records, media_type='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': 'attachment; filename="spoolmera-movements-v1.csv"',
                'Cache-Control': 'no-store',
                'X-Content-Type-Options': 'nosniff',
            })

    @router.post("/api/spools/{spool_id}/archive", dependencies=[Depends(require_editor)])
    def archive_spool(spool_id: int, request: Request):
        return inventory_service.archive_spool(db_path, spool_id, request.state.user["id"])

    @router.post('/api/spools/{spool_id}/unarchive', response_model=SpoolResponse,
                 dependencies=[Depends(require_editor)])
    def unarchive_spool(spool_id: int, request: Request):
        return inventory_query_service.unarchive(db_path, spool_id, request.state.user['id'])

    @router.get('/labels', response_class=HTMLResponse, include_in_schema=False)
    def print_labels(request: Request, uids: str = Query(min_length=36, max_length=3700),
                     size: Literal['60x40', '50x30'] = '60x40',
                     lang: Literal['en', 'de'] | None = None):
        try:
            requested = [str(UUID(uid)) for uid in uids.split(',')]
        except ValueError as exc:
            raise HTTPException(422, 'Expected a comma-separated list of spool UUIDs.') from exc
        if len(requested) > 100 or len(requested) != len(set(requested)):
            raise HTTPException(422, 'Select between 1 and 100 distinct spools.')
        marks = ','.join('?' for _ in requested)
        with session(db_path) as db:
            rows = db.execute(f'''SELECT s.uid,s.id,s.remaining_g,s.initial_g,
                p.brand,p.name,p.material,p.color_name FROM spools s
                JOIN products p ON p.id=s.product_id WHERE s.uid IN ({marks})''', requested).fetchall()
        found = {row['uid']: dict(row) for row in rows}
        if len(found) != len(requested):
            raise HTTPException(404, 'One or more spools were not found.')
        language = label_language(lang, request.cookies.get('spoolmera_language'), request.headers.get('accept-language', ''))
        return HTMLResponse(labels_html([found[uid] for uid in requested], size, language), headers={
            'Cache-Control': 'no-store',
            'Content-Language': language,
            'Vary': 'Cookie, Accept-Language',
            'Content-Security-Policy': "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'",
        })

    # Stable UUIDs identify spools, but are NOT authentication tokens.
    @router.get("/s/{spool_uid}", include_in_schema=False)
    def open_spool(spool_uid: str):
        with session(db_path) as db:
            row = db.execute("SELECT uid FROM spools WHERE uid=?", (spool_uid,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Spool not found.")
        return RedirectResponse(url="/?spool=" + spool_uid, status_code=302)

    @router.get("/api/spools/{spool_uid}/qr.svg", include_in_schema=False)
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

    @router.get("/labels/{spool_uid}", response_class=HTMLResponse, include_in_schema=False)
    def print_label(spool_uid: str, request: Request,
                    size: Literal["60x40","50x30"] = Query(default="60x40"),
                    lang: Literal["en", "de"] | None = None):
        with session(db_path) as db:
            row = db.execute(
                """SELECT s.uid, s.id, s.remaining_g, s.initial_g,
                          p.brand, p.name, p.material, p.color_name
                   FROM spools s JOIN products p ON p.id=s.product_id
                   WHERE s.uid=?""", (spool_uid,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Spool not found.")
        language = label_language(lang, request.cookies.get("spoolmera_language"), request.headers.get("accept-language", ""))
        return HTMLResponse(
            content=label_html(dict(row), size=size, language=language),
            headers={"Cache-Control": "no-store", "Content-Language": language,
                     "Vary": "Cookie, Accept-Language",
                     "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'"},
        )

    @router.get("/api/export/inventory.csv")
    def download_inventory():
        with session(db_path) as db:
            content = export_inventory(db)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="filament-inventory-v1.csv"',
                     "Cache-Control": "no-store"},
        )

    @router.post("/api/import/inventory.csv", response_model=CsvPreviewResponse,
                 dependencies=[Depends(require_editor)])
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
            result = import_inventory(db, csv_data, dry_run=dry_run, actor_id=request.state.user['id'])
            if not dry_run:
                audit(db, request.state.user["id"], "csv_import", "inventory", None)
            return result

    @router.get("/api/audit", dependencies=[Depends(require_admin)])
    def audit_events(limit: int = Query(default=100, ge=1, le=200)):
        with session(db_path) as db:
            return [dict(row) for row in db.execute(
                """SELECT a.id,a.action,a.entity,a.entity_id,a.created_at,u.username AS actor
                   FROM audit_events a LEFT JOIN users u ON u.id=a.actor_id
                   ORDER BY a.id DESC LIMIT ?""", (limit,)).fetchall()]

    @router.get("/api/integrations/v1/capabilities", response_model=CapabilitiesResponse)
    def integration_capabilities():
        return get_integration_capabilities()

    @router.get("/api/integrations/v1/spools")
    def integration_spools():
        with session(db_path) as db:
            return get_inventory_snapshot(db)

    app.include_router(router)
