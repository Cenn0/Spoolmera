"""Explicit requests and UI-facing snapshots for material reconciliation."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActualMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spool_id: int = Field(gt=0)
    actual_g: int = Field(ge=0, le=100000)


class ConsumptionMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spool_id: int = Field(gt=0)
    gross_g: int = Field(ge=0, le=200000)
    tare_g: int | None = Field(default=None, ge=0, le=100000)
    expected_stock_revision: int = Field(ge=0)
    scale_event_id: int | None = Field(default=None, gt=0)


class ConsumptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["actual", "estimated", "discard"]
    materials: list[ActualMaterial] = Field(default_factory=list, max_length=8)
    measurements: list[ConsumptionMeasurement] = Field(default_factory=list, max_length=8)
    reason: str = Field(min_length=3, max_length=1000)
    expected_updated_at: str | None = Field(default=None, max_length=50)
    expected_accounting_revision: int | None = Field(default=None, ge=0)
    request_id: UUID | None = None

    @model_validator(mode="after")
    def complete_explicit_values(self):
        if self.mode == "actual" and not self.materials:
            raise ValueError("Actual consumption requires each physical spool, including explicit zero amounts.")
        if self.mode != "actual" and self.materials:
            raise ValueError("Explicit material amounts are only accepted for actual consumption.")
        if len({row.spool_id for row in self.materials}) != len(self.materials):
            raise ValueError("List each physical spool only once.")
        if len({row.spool_id for row in self.measurements}) != len(self.measurements):
            raise ValueError("List each measured spool only once.")
        return self


class ConsumptionSpool(BaseModel):
    spool_id: int
    spool_uid: str
    product_name: str
    brand: str
    estimated_g: int
    accounted_g: int
    initial_g: int
    remaining_g: int
    tare_g: int
    stock_revision: int
    archived: bool
    last_movement_id: int | None
    measurement_reconciliation_required: bool = False
    last_measured_g: int | None = None
    last_measured_at: str | None = None


class AccountingOperation(BaseModel):
    id: str
    mode: Literal["actual", "estimated", "discard"]
    reason: str
    actor_id: int | None
    actor_name: str | None
    created_at: str
    accounting_revision: int


class ConsumptionResponse(BaseModel):
    job_id: int
    status: str
    accounting_status: str
    accounting_method: Literal["actual", "estimated", "discard"] | None
    accounting_revision: int
    accounting_note: str
    updated_at: str
    materials: list[ConsumptionSpool]
    operations: list[AccountingOperation]
    operation_id: str | None = None
    duplicate: bool = False
