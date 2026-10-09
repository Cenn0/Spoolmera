"""Operational contracts shared by the API, generated Angular models and tests."""
from typing import Literal
from pydantic import BaseModel


class JobCountResponse(BaseModel):
    status: str
    count: int


class PollerStatusResponse(BaseModel):
    status: Literal["starting", "running", "waiting", "stopped", "failed"]
    interval_seconds: int
    started_at: str | None
    last_cycle_at: str | None
    last_success_at: str | None
    last_heartbeat_at: str | None
    last_error: str | None
    lease_held: bool
    lease_owner: str | None = None
    lease_expires_at: str | None


class PrinterDiagnosticsResponse(BaseModel):
    id: int
    name: str
    enabled: bool
    active_jobs: int
    last_attempt_at: str | None
    last_success_at: str | None
    consecutive_failures: int
    last_error: str
    observation_age_seconds: int | None
    freshness: Literal["never", "current", "stale", "disabled"]


class UnresolvedCommandResponse(BaseModel):
    id: str
    printer_id: int
    printer_name: str
    job_id: int | None
    action: str
    state: str
    created_at: str
    updated_at: str


class BackupStatusResponse(BaseModel):
    status: Literal["never", "ready", "failed"]
    last_success_at: str | None
    last_size_bytes: int | None
    last_error: str | None


class StorageStatusResponse(BaseModel):
    database_bytes: int
    wal_bytes: int
    free_bytes: int
    reserve_bytes: int
    low_space: bool


class RestoreStatusResponse(BaseModel):
    last_restored_at: str | None
    requires_token_reissue: bool


class SlicerStatusResponse(BaseModel):
    enabled: bool
    configured: bool


class MaterialMappingWarningResponse(BaseModel):
    job_id: int
    file_name: str
    status: str
    job_estimate_g: int
    material_estimate_g: int
    material_count: int


class PrinterOperationDiagnosticsResponse(BaseModel):
    printer_id: int
    printer_name: str
    operation_id: str
    job_id: int
    kind: Literal["start", "upload"]
    state: Literal["active", "unknown"]
    created_at: str
    updated_at: str


class DiagnosticsResponse(BaseModel):
    version: str
    schema_version: int
    status: Literal["ok", "degraded"]
    jobs: list[JobCountResponse]
    uncertain_commands: int
    commands: list[UnresolvedCommandResponse]
    poller: PollerStatusResponse
    printers: list[PrinterDiagnosticsResponse]
    backup: BackupStatusResponse
    storage: StorageStatusResponse
    restore: RestoreStatusResponse
    slicer: SlicerStatusResponse
    material_mapping_warnings: list[MaterialMappingWarningResponse]
    printer_operations: list[PrinterOperationDiagnosticsResponse]


class AlertResponse(BaseModel):
    id: str
    category: Literal["low_stock", "job_review", "printer_offline"]
    severity: Literal["warning", "error"]
    title: str
    message: str
    entity_type: Literal["spool", "print_job", "printer"]
    entity_id: str


class AlertsResponse(BaseModel):
    schema_version: Literal["1"]
    instance_epoch: str
    generated_at: str
    truncated: bool
    alerts: list[AlertResponse]


DIAGNOSTICS_MODELS = [JobCountResponse, PollerStatusResponse, PrinterDiagnosticsResponse,
                      UnresolvedCommandResponse, BackupStatusResponse, StorageStatusResponse,
                      RestoreStatusResponse, SlicerStatusResponse, MaterialMappingWarningResponse,
                      PrinterOperationDiagnosticsResponse, DiagnosticsResponse,
                      AlertResponse, AlertsResponse]
