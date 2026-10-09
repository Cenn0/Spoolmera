"""Public import and scale review results shared with the Angular client."""
from typing import Literal

from pydantic import BaseModel


class CsvPreviewResponse(BaseModel):
    dry_run: bool
    products_created: int
    products_skipped: int
    spools_created: int
    spools_skipped: int


class SpoolmanPreviewResponse(CsvPreviewResponse):
    source: str
    archived_skipped: int


class ScaleMeasurementResponse(BaseModel):
    id: int
    source: str
    event_id: str
    spool_id: int
    spool_uid: str
    gross_g: int
    tare_g: int | None
    status: Literal['pending', 'applied', 'discarded']
    received_at: str
    reviewed_at: str | None
    measured_at: str | None
    net_g: int | None
    captured_stock_revision: int | None
    captured_tare_g: int | None
    review_note: str | None
    accounting_operation_id: str | None
    stock_revision: int
    remaining_g: int
    current_tare_g: int
    brand: str
    product_name: str
    stale: bool
    stale_reason: str | None
    blocking_job_ids: list[int]


IMPORT_MODELS = [CsvPreviewResponse, SpoolmanPreviewResponse, ScaleMeasurementResponse]
