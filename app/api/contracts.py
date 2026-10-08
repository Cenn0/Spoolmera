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
    opened: bool
    status: Literal['sealed','opened','empty']
    location: str
    notes: str
    created_at: str
    archived_at: str | None
    brand: str
    product_name: str
    material: str
    color_name: str
    color_hex: str
    diameter_mm: float

class SpoolPageResponse(BaseModel):
    items: list[SpoolResponse]
    next_cursor: int | None

class PrinterResponse(BaseModel):
    id: int
    name: str
    kind: Literal['moonraker','octoprint']
    base_url: str
    token_env: str
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
    status: Literal['pending','printing','completed','needs_review','cancelled']
    accounting_status: Literal['pending','needs_review','debited','discarded']
    movement_id: int | None
    note: str
    external_job_id: str | None
    created_at: str
    start_command_state: str | None
    materials: list[JobMaterialResponse]

class CapabilitiesResponse(BaseModel):
    schema_version: str
    inventory_read: bool
    usage_write: bool
    printer_connections: bool
    slicer_connections: bool

API_MODELS = [OverviewResponse, ProductResponse, SpoolResponse, SpoolPageResponse, PrinterResponse, JobMaterialResponse, JobResponse, CapabilitiesResponse]
