"""Transactional inventory CSV import/export with a versioned schema.

CSV is an inventory snapshot, not a full backup of the movement history.
Existing UUIDs are never overwritten; archived spools are never resurrected.
"""
import csv
import io
import sqlite3
from collections import OrderedDict
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError

from app.database import utc_now
from app.models import ProductInput, SpoolInput

CSV_COLUMNS = (
    "schema_version", "product_uid", "brand", "name", "material", "color_name",
    "color_hex", "diameter_mm", "product_notes", "spool_uid", "initial_g",
    "remaining_g", "opened", "location", "spool_notes",
)
TEXT_FIELDS = {"brand", "name", "material", "color_name", "product_notes", "location", "spool_notes"}


def _protect_csv_cell(value: object) -> object:
    """Avoid spreadsheet-formula execution while preserving exact round-trip text."""
    if not isinstance(value, str):
        return value
    if value.startswith("'") or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _unprotect_csv_cell(value: str) -> str:
    if value.startswith("''") or (
        value.startswith("'") and value[1:].lstrip().startswith(("=", "+", "-", "@"))
    ):
        return value[1:]
    return value


def export_inventory(db: sqlite3.Connection) -> str:
    rows = db.execute(
        """SELECT p.uid AS product_uid, p.brand, p.name, p.material,
                  p.color_name, p.color_hex, p.diameter_mm, p.notes AS product_notes,
                  s.uid AS spool_uid, s.initial_g, s.remaining_g,
                  s.opened, s.location, s.notes AS spool_notes
           FROM products p
           LEFT JOIN spools s ON s.product_id = p.id AND s.archived_at IS NULL
           ORDER BY p.id, s.id"""
    ).fetchall()
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        values = dict(row)
        values["schema_version"] = "1"
        if values["spool_uid"] is None:
            for column in ("spool_uid", "initial_g", "remaining_g", "opened", "location", "spool_notes"):
                values[column] = ""
        else:
            values["opened"] = "true" if values["opened"] else "false"
        writer.writerow({
            key: _protect_csv_cell(values[key]) if key in TEXT_FIELDS else values[key]
            for key in CSV_COLUMNS
        })
    # The UTF-8 BOM helps spreadsheet software recognize Unicode; plain UTF-8 is accepted on import.
    return "\ufeff" + stream.getvalue()


def _uid(value: str, row_number: int, field: str) -> str:
    try:
        parsed = str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(422, f"Row {row_number}: invalid {field}.") from None
    if parsed != value.lower():
        raise HTTPException(422, f"Row {row_number}: {field} must be a canonical UUID.")
    return parsed


def _spool_input(row: dict[str, str], row_number: int) -> SpoolInput:
    try:
        opened = {"true": True, "false": False}[row["opened"].lower()]
        for key in ("initial_g", "remaining_g"):
            if not row[key].isascii() or not row[key].isdigit():
                raise ValueError(key)
        payload = SpoolInput(
            product_id=1,
            initial_g=int(row["initial_g"]),
            remaining_g=int(row["remaining_g"]),
            opened=opened,
            location=row["location"],
            notes=row["spool_notes"],
        )
    except (KeyError, ValueError, ValidationError):
        raise HTTPException(422, f"Row {row_number}: invalid spool values.") from None
    if payload.remaining_g is None or payload.remaining_g > payload.initial_g:
        raise HTTPException(422, f"Row {row_number}: remaining_g exceeds initial_g.")
    return payload


def _parse_rows(content: str) -> tuple[OrderedDict, list]:
    if "\x00" in content:
        raise HTTPException(422, "CSV contains forbidden null bytes.")
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
        if (
            reader.fieldnames is None
            or len(reader.fieldnames) != len(CSV_COLUMNS)
            or set(reader.fieldnames) != set(CSV_COLUMNS)
        ):
            raise HTTPException(422, "CSV header must match the inventory v1 schema.")
        products = OrderedDict()
        spools = []
        seen_spools = set()
        for row_number, original in enumerate(reader, start=2):
            if row_number > 2501:
                raise HTTPException(413, "CSV exceeds the limit of 2,500 data rows.")
            if None in original or any(value is None for value in original.values()):
                raise HTTPException(422, f"Row {row_number}: missing or extra CSV columns.")
            row = {
                key: _unprotect_csv_cell(original[key]) if key in TEXT_FIELDS else original[key]
                for key in CSV_COLUMNS
            }
            if row["schema_version"] != "1":
                raise HTTPException(422, f"Row {row_number}: unsupported schema_version.")
            product_uid = _uid(row["product_uid"], row_number, "product_uid")
            try:
                product = ProductInput(
                    brand=row["brand"], name=row["name"], material=row["material"],
                    color_name=row["color_name"], color_hex=row["color_hex"],
                    diameter_mm=row["diameter_mm"], notes=row["product_notes"],
                )
            except ValidationError:
                raise HTTPException(422, f"Row {row_number}: invalid product values.") from None
            if product_uid in products and products[product_uid] != product:
                raise HTTPException(422, f"Row {row_number}: conflicting product data for one UUID.")
            products[product_uid] = product
            if row["spool_uid"]:
                spool_uid = _uid(row["spool_uid"], row_number, "spool_uid")
                if spool_uid in seen_spools:
                    raise HTTPException(422, f"Row {row_number}: duplicate spool_uid.")
                seen_spools.add(spool_uid)
                spools.append((spool_uid, product_uid, _spool_input(row, row_number)))
            elif any(row[column] for column in (
                "initial_g", "remaining_g", "opened", "location", "spool_notes"
            )):
                raise HTTPException(422, f"Row {row_number}: spool data requires a spool_uid.")
        return products, spools
    except csv.Error:
        raise HTTPException(422, "Malformed CSV document.") from None


def import_inventory(db: sqlite3.Connection, content: str, *, dry_run: bool,
                     actor_id: int | None = None) -> dict:
    products, spools = _parse_rows(content)
    existing_products = {row["uid"]: row["id"] for row in db.execute("SELECT id, uid FROM products")}
    existing_spools = {
        row["uid"]: row["product_uid"]
        for row in db.execute(
            """SELECT s.uid, p.uid AS product_uid
               FROM spools s JOIN products p ON p.id = s.product_id"""
        )
    }
    for uid, product_uid, _ in spools:
        if uid in existing_spools and existing_spools[uid] != product_uid:
            raise HTTPException(409, "Spool UUID already belongs to another product UUID.")

    missing_products = [uid for uid in products if uid not in existing_products]
    new_spools = [item for item in spools if item[0] not in existing_spools]
    result = {
        "dry_run": dry_run,
        "products_created": len(missing_products),
        "products_skipped": len(products) - len(missing_products),
        "spools_created": len(new_spools),
        "spools_skipped": len(spools) - len(new_spools),
    }
    if dry_run:
        return result

    timestamp = utc_now()
    for uid in missing_products:
        product = products[uid]
        cursor = db.execute(
            """INSERT INTO products
               (uid, brand, name, material, color_name, color_hex,
                diameter_mm, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uid, product.brand, product.name, product.material,
             product.color_name, product.color_hex, product.diameter_mm,
             product.notes, timestamp, timestamp),
        )
        existing_products[uid] = cursor.lastrowid
    for spool_uid, product_uid, spool in new_spools:
        initial = spool.initial_g
        remaining = spool.remaining_g
        opened = spool.opened or remaining < initial
        cursor = db.execute(
            """INSERT INTO spools
               (uid, product_id, initial_g, remaining_g, opened, location, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (spool_uid, existing_products[product_uid], initial, remaining,
             int(opened), spool.location, spool.notes, timestamp),
        )
        db.execute(
            """INSERT INTO movements
               (spool_id, kind, delta_g, remaining_after_g, note, created_at, actor_id, source)
               VALUES (?, 'initial', ?, ?, ?, ?, ?, 'csv_import')""",
            (cursor.lastrowid, remaining, remaining, "Imported from inventory CSV snapshot", timestamp, actor_id),
        )
    return result
