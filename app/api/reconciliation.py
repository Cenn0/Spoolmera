"""Explicit review of estimated, measured and actual print material usage."""
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request

from app.core.policies import require_editor
from app.services.accounting_models import ConsumptionInput, ConsumptionResponse
from app.services.accounting_service import get_consumption, reconcile_consumption


def register_reconciliation_routes(app: FastAPI, db_path: Path) -> None:
    router = APIRouter()

    @router.get("/api/jobs/{job_id}/consumption", response_model=ConsumptionResponse)
    def read_consumption(job_id: int):
        return get_consumption(db_path, job_id)

    @router.post("/api/jobs/{job_id}/consumption", response_model=ConsumptionResponse,
                 dependencies=[Depends(require_editor)])
    def confirm_consumption(job_id: int, payload: ConsumptionInput, request: Request):
        return reconcile_consumption(db_path, job_id, payload, request.state.user["id"])

    app.include_router(router)
