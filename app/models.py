"""Validated API input models. Mass is always represented in whole grams."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductInput(InputModel):
    brand: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    material: str = Field(min_length=1, max_length=32)
    color_name: str = Field(min_length=1, max_length=80)
    color_hex: str = Field(default="#64748b", pattern=r"^#[0-9a-fA-F]{6}$")
    diameter_mm: float = Field(default=1.75, ge=1, le=3.5, allow_inf_nan=False)
    notes: str = Field(default="", max_length=1000)
    density_g_cm3: float | None = Field(default=None, gt=0, le=10, allow_inf_nan=False)
    nozzle_min_c: int | None = Field(default=None, ge=0, le=400)
    nozzle_max_c: int | None = Field(default=None, ge=0, le=400)
    bed_min_c: int | None = Field(default=None, ge=0, le=200)
    bed_max_c: int | None = Field(default=None, ge=0, le=200)
    gtin: str = Field(default="", max_length=32)
    manufacturer_sku: str = Field(default="", max_length=100)
    slicer_preset: str = Field(default="", max_length=160)
    low_stock_threshold_g: int = Field(default=200, ge=0, le=100000)
    target_stock_g: int = Field(default=0, ge=0, le=10000000)

    @field_validator("material")
    @classmethod
    def normalize_material(cls, value: str) -> str:
        return value.upper()

    @field_validator("color_hex")
    @classmethod
    def normalize_color(cls, value: str) -> str:
        return value.upper()


class SpoolInput(InputModel):
    product_id: int = Field(gt=0)
    initial_g: int = Field(gt=0, le=100000)
    remaining_g: int | None = Field(default=None, ge=0, le=100000)
    opened: bool = False
    location: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)
    tare_g: int = Field(default=0, ge=0, le=100000)
    purchase_price_cents: int | None = Field(default=None, ge=0, le=100000000)
    purchase_currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    purchased_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    batch: str = Field(default="", max_length=120)


class SpoolUpdate(InputModel):
    opened: bool | None = None
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    tare_g: int | None = Field(default=None, ge=0, le=100000)
    purchase_price_cents: int | None = Field(default=None, ge=0, le=100000000)
    purchase_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    purchased_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    batch: str | None = Field(default=None, max_length=120)


class MovementInput(InputModel):
    kind: Literal["consume", "adjust"]
    grams: int = Field(ge=-100000, le=100000)
    note: str = Field(default="", max_length=1000)


class WeighInput(InputModel):
    gross_g: int = Field(ge=0, le=200000)
    tare_g: int | None = Field(default=None, ge=0, le=100000)
    expected_stock_revision: int | None = Field(default=None, ge=0)
    note: str = Field(default="Physical scale measurement", min_length=3, max_length=1000)


class DryingInput(InputModel):
    temperature_c: int = Field(ge=1, le=150)
    duration_minutes: int = Field(ge=1, le=10080)
    dried_at: str = Field(min_length=10, max_length=40)
    note: str = Field(default="", max_length=1000)


class SpoolBatchInput(InputModel):
    count: int = Field(ge=1, le=100)
    spool: SpoolInput
    request_id: UUID | None = None
