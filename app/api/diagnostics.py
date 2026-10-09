"""Operator diagnostics and a scoped alert snapshot for the optional notifier."""
from pathlib import Path
from fastapi import Depends, FastAPI, Request

from app.api.diagnostics_contracts import DiagnosticsResponse, AlertsResponse, DIAGNOSTICS_MODELS
from app.core.policies import require_editor
from app.core.settings import Settings
from app.services.diagnostics_service import diagnostics, active_alerts


def register_diagnostics_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/diagnostics", response_model=DiagnosticsResponse, dependencies=[Depends(require_editor)])
    def get_diagnostics(request: Request):
        settings = getattr(request.app.state, "settings", None) or Settings.from_environment()
        return diagnostics(db_path, settings)

    @app.get("/api/alerts", response_model=AlertsResponse, dependencies=[Depends(require_editor)])
    def alerts():
        return active_alerts(db_path)

    @app.get("/api/automation/v1/alerts", response_model=AlertsResponse)
    def machine_alerts(request: Request):
        from app.api.automation import authenticate_machine
        authenticate_machine(db_path, request, "events_read")
        return active_alerts(db_path)
