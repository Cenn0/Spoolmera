"""Spoolmera REST API and local web frontend."""
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.core.settings import Settings
from app.database import initialize_database, session
from app.api.inventory import register_inventory_routes
from app.auth import protect
from app.services.process_lock import ProcessLock, operation_lock_path
from app.printers import register_printer_routes
from app.jobs import register_job_routes, poll_worker
from app.cloud import register_cloud_routes
from app.slicing import register_slicing_routes
from app.api.catalog import register_catalog_routes
from app.api.planning import register_planning_routes
from app.api.inspection import register_inspection_routes
from app.api.spoolman_import import register_spoolman_import
from app.api.automation import register_automation_routes
from app.api.identifiers import register_identifier_routes
from app.api.backup import register_backup_routes
from app.api.analytics import register_analytics_routes
from app.api.scale import register_scale_routes
from app.api.reconciliation import register_reconciliation_routes
from app.api.diagnostics import register_diagnostics_routes

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
    db_path = Path(database_path or os.environ.get("SPOOLMERA_DB_PATH", ".data/spoolmera.sqlite3"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings.from_environment()
        app.state.settings = settings
        application_lock = ProcessLock(operation_lock_path(db_path, "application"))
        if not application_lock.acquire():
            raise RuntimeError("This database is already used by another application process or a restore. "
                               "Run one API worker per database and stop it before restoring.")
        poll_task = None
        try:
            initialize_database(db_path)
            poll_task = asyncio.create_task(poll_worker(db_path, settings))
            app.state.poll_task = poll_task
            yield
        finally:
            try:
                if poll_task is not None:
                    poll_task.cancel()
                    try:
                        await poll_task
                    except asyncio.CancelledError:
                        pass
            finally:
                application_lock.release()

    app = FastAPI(
        title="Spoolmera API",
        version=__version__,
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
    register_spoolman_import(app, db_path)
    register_automation_routes(app, db_path)
    register_identifier_routes(app, db_path)
    register_backup_routes(app, db_path)
    register_analytics_routes(app, db_path)
    register_scale_routes(app, db_path)
    register_reconciliation_routes(app, db_path)
    register_diagnostics_routes(app, db_path)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        if not (UI_DIR / "index.html").is_file():
            return HTMLResponse(
                "<h1>Spoolmera</h1><p>Angular frontend not built. "
                "Use npm start in frontend/ during development.</p>",
                status_code=503,
            )
        return FileResponse(UI_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        with session(db_path) as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get('/api/ready')
    def ready():
        from app.services.polling_runtime import poller_snapshot
        state = poller_snapshot(db_path, getattr(app.state, 'settings', None))
        task = getattr(app.state, 'poll_task', None)
        available = (task is not None and not task.done() and state['status'] == 'running'
                     and state['lease_held'] and state['last_error'] is None)
        with session(db_path) as db:
            db.execute('SELECT 1').fetchone()
        return JSONResponse({'status': 'ready' if available else 'not_ready',
                             'poller_status': state['status']}, status_code=200 if available else 503)

    register_inventory_routes(app, db_path)

    if UI_DIR.is_dir():
        app.mount("/", SPAStaticFiles(directory=str(UI_DIR), html=True), name="angular")

    return app


app = create_app()
