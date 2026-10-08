"""Filament Manager REST API and local web frontend."""
import os
import asyncio
from uuid import uuid4
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.policies import require_editor, require_admin
from app.database import initialize_database, session
from app.api.inventory import register_inventory_routes, spool_as_dict
from app.auth import protect, audit
from app.services.accounting_service import record_manual_movement
from app.printers import register_printer_routes
from app.jobs import register_job_routes, poll_worker
from app.cloud import register_cloud_routes
from app.slicing import register_slicing_routes
from app.api.catalog import register_catalog_routes
from app.api.planning import register_planning_routes
from app.api.inspection import register_inspection_routes
from app.models import MovementInput, ProductInput, SpoolInput, SpoolUpdate
from app.labels import label_html, qr_svg, spool_public_url
from app.inventory_csv import export_inventory, import_inventory
from app.integrations import get_inventory_snapshot, get_integration_capabilities

STATIC_DIR = Path(__file__).resolve().parent / "static"
UI_DIR = Path(__file__).resolve().parent / "ui"


class SPAStaticFiles(StaticFiles):
    """Serve compiled Angular assets and fall back to index.html for UI routes."""

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if (exc.status_code != 404 or "." in Path(path).name
                    or path.startswith(("api/", "labels/", "static/", "s/"))):
                raise
            response = await super().get_response("index.html", scope)
        if response.media_type == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response



def create_app(database_path: str | Path | None = None) -> FastAPI:
    db_path = Path(database_path or os.environ.get("FILAMENT_DB_PATH", ".data/filaments.sqlite3"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize_database(db_path)
        poll_task = asyncio.create_task(poll_worker(db_path))
        try:
            yield
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="Filament Manager API",
        version="0.6.0",
        description="Local management of filament products, physical spools and inventory movements.",
        lifespan=lifespan,
    )
    protect(app, db_path)
    register_printer_routes(app, db_path)
    register_job_routes(app, db_path)
    register_cloud_routes(app, db_path)
    register_slicing_routes(app, db_path)
    register_catalog_routes(app)
    register_planning_routes(app, db_path)
    register_inspection_routes(app)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        if not (UI_DIR / "index.html").is_file():
            return HTMLResponse(
                "<h1>Filament Manager</h1><p>Angular frontend not built. "
                "Use npm start in frontend/ during development.</p>",
                status_code=503,
            )
        return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        with session(db_path) as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    register_inventory_routes(app, db_path)

    if UI_DIR.is_dir():
        app.mount("/", SPAStaticFiles(directory=str(UI_DIR), html=True), name="angular")

    return app


app = create_app()
