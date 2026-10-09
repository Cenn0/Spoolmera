"""Opt-in, snapshot-only Spoolman import via explicit user-supplied JSON.

Does not call a Spoolman server and never imports historical movements.
External source IDs are namespaced and never treated as local UUIDs.
"""
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.auth import audit
from app.core.policies import require_editor
from app.database import session, utc_now
from app.api.import_contracts import SpoolmanPreviewResponse

MAX_SIZE = 2 * 1024 * 1024
SOURCE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
HEX = re.compile(r"^#?(?:[A-Fa-f0-9]{6}|[A-Fa-f0-9]{8})$")


class SourceVendor(BaseModel):
    name: str = Field(default="Unknown", max_length=80)


class SourceFilament(BaseModel):
    id: int = Field(gt=0)
    name: str = Field(default="Unnamed filament", max_length=120)
    material: str = Field(default="OTHER", max_length=32)
    vendor: SourceVendor | None = None
    color_hex: str | None = None
    diameter: Decimal | None = None
    density: Decimal | None = None
    weight: Decimal | None = None
    spool_weight: Decimal | None = None
    article_number: str | None = Field(default=None, max_length=100)
    price: Decimal | None = None


class SourceSpool(BaseModel):
    id: int = Field(gt=0)
    filament: SourceFilament
    initial_weight: Decimal | None = None
    remaining_weight: Decimal | None = None
    used_weight: Decimal | None = None
    spool_weight: Decimal | None = None
    price: Decimal | None = None
    location: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=1000)
    lot_nr: str | None = Field(default=None, max_length=120)
    archived: bool = False


def grams(value: Decimal) -> int:
    if not value.is_finite() or value < 0 or value > 100000:
        raise ValueError("Import weight is out of range.")
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def as_cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    if not value.is_finite() or not 0 <= value <= 1000000:
        raise ValueError("Import price is out of range.")
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalise(source: SourceSpool) -> dict:
    filament = source.filament
    net_initial = source.initial_weight
    if net_initial is None:
        net_initial = filament.weight
    if net_initial is None:
        raise ValueError("A Spoolman spool requires initial_weight or filament.weight.")
    initial = grams(net_initial)
    if initial < 1:
        raise ValueError("Starting filament weight must be at least 1 gram.")
    if source.remaining_weight is not None:
        remaining = grams(source.remaining_weight)
    elif source.used_weight is not None:
        remaining = grams(net_initial - source.used_weight)
    else:
        raise ValueError("A Spoolman spool requires remaining_weight or used_weight.")
    if remaining > initial:
        raise ValueError("Remaining filament cannot exceed the starting weight.")
    tare = grams(source.spool_weight if source.spool_weight is not None
                 else filament.spool_weight if filament.spool_weight is not None else Decimal(0))
    if filament.diameter is None:
        diameter = 1.75
    else:
        if not filament.diameter.is_finite() or not 1 <= filament.diameter <= Decimal("3.5"):
            raise ValueError("Invalid filament diameter.")
        diameter = float(filament.diameter)
    density = None
    if filament.density is not None:
        if not filament.density.is_finite() or not 0 < filament.density <= 10:
            raise ValueError("Invalid filament density.")
        density = float(filament.density)
    color = (filament.color_hex or "").strip()
    if HEX.fullmatch(color):
        color = "#" + color.lstrip("#")[:6].upper()
    else:
        color = "#64748B"
    return {
        "external_spool": source.id,
        "external_filament": filament.id,
        "brand": filament.vendor.name if filament.vendor and filament.vendor.name else "Unknown",
        "name": filament.name or "Unnamed filament",
        "material": (filament.material or "OTHER").upper(),
        "color_hex": color,
        "color_name": filament.name or "Unknown",
        "diameter_mm": diameter, "density_g_cm3": density,
        "initial_g": initial, "remaining_g": remaining, "tare_g": tare,
        "location": source.location or "", "notes": source.comment or "",
        "batch": source.lot_nr or "",
        "article_number": filament.article_number or "",
        "price_cents": as_cents(source.price if source.price is not None else filament.price),
    }


def import_spoolman(db_path: Path, source: str, records: list[SourceSpool],
                    dry_run: bool, actor_id: int) -> dict:
    if not SOURCE.fullmatch(source):
        raise HTTPException(422, "Import source must contain only letters, numbers, underscore and hyphen.")
    ids = [record.id for record in records]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Spoolman snapshot contains duplicate spool IDs.")
    try:
        normal = [normalise(record) for record in records if not record.archived]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    summary = {"dry_run": dry_run, "source": source, "spools_created": 0,
               "spools_skipped": 0, "products_created": 0, "products_skipped": 0,
               "archived_skipped": len(records) - len(normal)}
    with session(db_path, write=True) as db:
        material_ids: set[int] = set()
        for row in normal:
            current = db.execute(
                "SELECT local_id FROM external_import_map WHERE source=? AND entity_type='spool' AND external_id=?",
                (source, row["external_spool"]),
            ).fetchone()
            if current:
                summary["spools_skipped"] += 1
                continue
            current_product = db.execute(
                "SELECT local_id FROM external_import_map WHERE source=? AND entity_type='filament' AND external_id=?",
                (source, row["external_filament"]),
            ).fetchone()
            product_id = current_product["local_id"] if current_product else None
            if product_id is None and row["external_filament"] not in material_ids:
                summary["products_created"] += 1
                material_ids.add(row["external_filament"])
            elif row["external_filament"] not in material_ids:
                summary["products_skipped"] += 1
                material_ids.add(row["external_filament"])
            summary["spools_created"] += 1
            if dry_run:
                continue
            stamp = utc_now()
            if product_id is None:
                product_id = db.execute(
                    """INSERT INTO products(uid,brand,name,material,color_name,color_hex,diameter_mm,notes,
                       created_at,updated_at,density_g_cm3,manufacturer_sku)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid4()),row["brand"],row["name"],row["material"],row["color_name"],
                     row["color_hex"],row["diameter_mm"],"Imported from Spoolman: " + source,
                     stamp,stamp,row["density_g_cm3"],row["article_number"]),
                ).lastrowid
                db.execute(
                    "INSERT INTO external_import_map(source,entity_type,external_id,local_id) "
                    "VALUES(?,'filament',?,?)", (source,row["external_filament"],product_id))
            spool_id = db.execute(
                """INSERT INTO spools(uid,product_id,initial_g,remaining_g,opened,location,notes,
                   created_at,tare_g,purchase_price_cents,batch)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid4()),product_id,row["initial_g"],row["remaining_g"],
                 int(row["remaining_g"] < row["initial_g"]),row["location"],row["notes"],
                 stamp,row["tare_g"],row["price_cents"],row["batch"]),
            ).lastrowid
            db.execute("INSERT INTO external_import_map(source,entity_type,external_id,local_id) "
                       "VALUES(?,'spool',?,?)", (source,row["external_spool"],spool_id))
            db.execute(
                """INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,actor_id,source)
                   VALUES(?,'initial',?,?,?,?,?,'spoolman_import')""",
                (spool_id,row["remaining_g"],row["remaining_g"],
                 "Spoolman snapshot: " + source,stamp,actor_id))
        if not dry_run:
            audit(db, actor_id, "spoolman_import", "inventory", None)
    return summary


def register_spoolman_import(app: FastAPI, db_path: Path) -> None:
    @app.post("/api/import/spoolman", response_model=SpoolmanPreviewResponse,
              dependencies=[Depends(require_editor)])
    async def import_snapshot(request: Request,
                              source: str = Query(default="spoolman", min_length=1, max_length=40),
                              dry_run: bool = Query(default=True)):
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise HTTPException(415, "Expected application/json Spoolman spool list.")
        chunks = []
        size = 0
        async for part in request.stream():
            size += len(part)
            if size > MAX_SIZE:
                raise HTTPException(413, "Spoolman snapshot exceeds 2 MiB.")
            chunks.append(part)
        try:
            parsed = json.loads(b"".join(chunks))
            if isinstance(parsed, dict):
                parsed = parsed["spools"]
            if not isinstance(parsed,list) or len(parsed)>2500:
                raise ValueError("Expected a list with up to 2500 spools.")
            records = [SourceSpool.model_validate(row) for row in parsed]
        except (ValueError, TypeError, KeyError, ValidationError) as exc:
            raise HTTPException(422, "Invalid Spoolman snapshot structure or fields.") from exc
        return import_spoolman(db_path,source,records,dry_run,request.state.user["id"])
