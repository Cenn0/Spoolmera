"""Typed public API response contracts, used to generate Angular types."""
from typing import Literal
from pydantic import BaseModel

class OverviewResponse(BaseModel):
    total_spools: int
    remaining_g: int
    opened_spools: int
    sealed_spools: int
    empty_spools: int
    low_spools: int
    total_products: int

class ProductResponse(BaseModel):
    id: int
    uid: str
    brand: str
    name: str
    material: str
    color_name: str
    color_hex: str
    diameter_mm: float
    notes: str
    density_g_cm3: float | None
    nozzle_min_c: int | None
    nozzle_max_c: int | None
    bed_min_c: int | None
    bed_max_c: int | None
    gtin: str
    manufacturer_sku: str
    slicer_preset: str
    low_stock_threshold_g: int
    target_stock_g: int
    created_at: str
    updated_at: str
    spool_count: int
    total_remaining_g: int

class SpoolResponse(BaseModel):
    id: int
    uid: str
    product_id: int
    initial_g: int
    remaining_g: int
    stock_revision: int
    opened: bool
    status: Literal['sealed','opened','empty']
    location: str
    notes: str
    created_at: str
    archived_at: str | None
    tare_g: int
    purchase_price_cents: int | None
    purchase_currency: str
    purchased_on: str | None
    batch: str
    brand: str
    product_name: str
    material: str
    color_name: str
    color_hex: str
    diameter_mm: float
    low_stock_threshold_g: int

class SpoolPageResponse(BaseModel):
    items: list[SpoolResponse]
    next_cursor: int | None

class PrinterResponse(BaseModel):
    id: int
    name: str
    kind: Literal['moonraker','octoprint','bambu']
    base_url: str
    token_env: str
    serial: str
    enabled: int
    created_at: str

class JobMaterialResponse(BaseModel):
    tool: int
    spool_id: int
    estimated_g: int
    movement_id: int | None
    spool_uid: str
    brand: str
    product_name: str

class JobResponse(BaseModel):
    id: int
    printer_id: int
    printer_name: str
    spool_id: int
    spool_uid: str
    brand: str
    product_name: str
    file_name: str
    estimated_g: int
    auto_account_bambu: bool
    last_progress_percent: int | None
    last_layer_num: int | None
    total_layer_num: int | None
    status: Literal['pending','printing','completed','needs_review','cancelled']
    accounting_status: Literal['pending','needs_review','debited','discarded']
    accounting_revision: int
    accounting_method: Literal['actual','estimated','discard'] | None
    movement_id: int | None
    note: str
    external_job_id: str | None
    observed_printing: int
    created_at: str
    created_by: int | None
    updated_at: str
    start_command_state: str | None
    materials: list[JobMaterialResponse]

class CapabilitiesResponse(BaseModel):
    schema_version: str
    inventory_read: bool
    usage_write: bool
    printer_connections: bool
    slicer_connections: bool

class MovementResponse(BaseModel):
    id: int
    spool_id: int
    spool_uid: str
    kind: Literal['initial', 'consume', 'adjust']
    delta_g: int
    remaining_after_g: int
    note: str
    created_at: str
    source: str
    source_ref: str | None
    actor_id: int | None
    actor_name: str | None
    print_job_id: int | None
    job_id: int | None
    job_file_name: str | None
    corrects_movement_id: int | None
    accounting_operation_id: str | None
    brand: str
    product_name: str
    material: str
    color_name: str
    color_hex: str


class MovementPageResponse(BaseModel):
    items: list[MovementResponse]
    next_cursor: int | None


class RestockItemResponse(BaseModel):
    product_id: int
    brand: str
    name: str
    material: str
    color_name: str
    color_hex: str
    target_stock_g: int
    remaining_g: int
    reserved_g: int
    available_g: int
    active_spools: int
    sealed_spools: int
    suggested_g: int


class RestockResponse(BaseModel):
    items: list[RestockItemResponse]


class SpoolBatchResponse(BaseModel):
    items: list[SpoolResponse]
    label_url: str


class SlotResponse(BaseModel):
    tool: int
    spool_id: int
    spool_uid: str
    brand: str
    product_name: str


class ReadinessMaterialResponse(BaseModel):
    tool: int
    spool_id: int
    estimated_g: int
    remaining_g: int
    archived_at: str | None
    brand: str
    product_name: str
    own_reservation_g: int | None
    others_reserved_g: int
    loaded_tool: int | None
    available_g: int
    ready: bool
    loaded_match: bool


class ReadinessResponse(BaseModel):
    job_id: int
    status: str
    ready: bool
    materials: list[ReadinessMaterialResponse]
    reserved: bool


class InspectionMaterialResponse(BaseModel):
    tool: int
    estimated_g: int


class InspectionPlateResponse(BaseModel):
    plate: int
    materials: list[InspectionMaterialResponse]


class InspectionResponse(BaseModel):
    file_stored: bool
    verified: bool
    source: str
    plates: list[InspectionPlateResponse]
    needs_manual_estimate: bool


class PrinterOperationResponse(BaseModel):
    operation_id: str
    printer_id: int
    job_id: int
    kind: Literal['start', 'upload']
    state: Literal['active', 'unknown']
    created_at: str
    updated_at: str


API_MODELS = [OverviewResponse, ProductResponse, SpoolResponse, SpoolPageResponse,
              PrinterResponse, JobMaterialResponse, JobResponse, CapabilitiesResponse,
              MovementResponse, MovementPageResponse, RestockItemResponse, RestockResponse,
              SpoolBatchResponse, SlotResponse, ReadinessMaterialResponse, ReadinessResponse,
              InspectionMaterialResponse, InspectionPlateResponse, InspectionResponse,
              PrinterOperationResponse]
