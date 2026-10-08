"""Validated API input models. Mass is always represented in whole grams."""
from typing import Literal

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


class SpoolUpdate(InputModel):
    opened: bool | None = None
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


class MovementInput(InputModel):
    kind: Literal["consume", "adjust"]
    grams: int = Field(ge=-100000, le=100000)
    note: str = Field(default="", max_length=1000)
