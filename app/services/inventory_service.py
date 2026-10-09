"""Inventory use cases and persistence-facing stock queries.

HTTP transports and auth dependencies live in app.api.inventory.
Write transactions and the ledger remain consistent with schema v5.
"""
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from app.database import session, utc_now
from app.auth import audit
from app.models import ProductInput, SpoolInput, SpoolUpdate

def spool_as_dict(row) -> dict:
    data = dict(row)
    data["opened"] = bool(data["opened"])
    data["status"] = (
        "empty" if data["remaining_g"] == 0
        else "opened" if data["opened"]
        else "sealed"
    )
    return data

def overview(db_path: Path):
    with session(db_path) as db:
        counts = db.execute(
            """SELECT COUNT(*) AS total_spools,
                      COALESCE(SUM(remaining_g), 0) AS remaining_g,
                      COALESCE(SUM(CASE WHEN remaining_g = 0 THEN 1 ELSE 0 END), 0) AS empty_spools,
                      COALESCE(SUM(CASE WHEN remaining_g > 0 AND opened = 1 THEN 1 ELSE 0 END), 0) AS opened_spools,
                      COALESCE(SUM(CASE WHEN remaining_g > 0 AND opened = 0 THEN 1 ELSE 0 END), 0) AS sealed_spools,
                      COALESCE(SUM(CASE WHEN remaining_g BETWEEN 1 AND p.low_stock_threshold_g THEN 1 ELSE 0 END), 0) AS low_spools
               FROM spools s JOIN products p ON p.id=s.product_id WHERE s.archived_at IS NULL"""
        ).fetchone()
        products = db.execute("SELECT COUNT(*) AS total FROM products").fetchone()["total"]
    return {**dict(counts), "total_products": products}



def list_products(db_path: Path):
    with session(db_path) as db:
        rows = db.execute(
            """SELECT p.*, COUNT(s.id) AS spool_count,
                      COALESCE(SUM(s.remaining_g), 0) AS total_remaining_g
               FROM products p
               LEFT JOIN spools s ON s.product_id = p.id AND s.archived_at IS NULL
               GROUP BY p.id
               ORDER BY p.brand COLLATE NOCASE, p.name COLLATE NOCASE, p.id"""
        ).fetchall()
    return [dict(row) for row in rows]



def add_product(db_path: Path, payload: ProductInput, actor_id: int):
    timestamp = utc_now()
    with session(db_path, write=True) as db:
        cursor = db.execute(
            """INSERT INTO products (uid, brand, name, material, color_name, color_hex,
                                     diameter_mm, notes, created_at, updated_at,
                                     density_g_cm3,nozzle_min_c,nozzle_max_c,bed_min_c,bed_max_c,
                                     gtin,manufacturer_sku,slicer_preset,low_stock_threshold_g,target_stock_g)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), payload.brand, payload.name, payload.material,
             payload.color_name, payload.color_hex, payload.diameter_mm,
             payload.notes, timestamp, timestamp, payload.density_g_cm3,
             payload.nozzle_min_c, payload.nozzle_max_c, payload.bed_min_c,
             payload.bed_max_c, payload.gtin, payload.manufacturer_sku,
             payload.slicer_preset, payload.low_stock_threshold_g, payload.target_stock_g),
        )
        product_id = cursor.lastrowid
        audit(db, actor_id, "product_create", "product", product_id)
    return {"id": product_id}



def update_product(db_path: Path, product_id: int, payload: ProductInput, actor_id: int):
    with session(db_path, write=True) as db:
        result = db.execute(
            """UPDATE products
               SET brand=?, name=?, material=?, color_name=?, color_hex=?,
                   diameter_mm=?, notes=?, updated_at=?, density_g_cm3=?,
                   nozzle_min_c=?, nozzle_max_c=?, bed_min_c=?, bed_max_c=?, gtin=?,
                   manufacturer_sku=?, slicer_preset=?, low_stock_threshold_g=?, target_stock_g=?
               WHERE id=?""",
            (payload.brand, payload.name, payload.material, payload.color_name,
             payload.color_hex, payload.diameter_mm, payload.notes, utc_now(),
             payload.density_g_cm3, payload.nozzle_min_c, payload.nozzle_max_c,
             payload.bed_min_c, payload.bed_max_c, payload.gtin,
             payload.manufacturer_sku, payload.slicer_preset,
             payload.low_stock_threshold_g, payload.target_stock_g, product_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Filament product not found.")
        audit(db, actor_id, "product_update", "product", product_id)
    return {"id": product_id}



def list_spools(db_path: Path):
    with session(db_path) as db:
        rows = db.execute(
            """SELECT s.*, p.brand, p.name AS product_name, p.material,
                      p.color_name, p.color_hex, p.diameter_mm, p.low_stock_threshold_g
               FROM spools s JOIN products p ON p.id=s.product_id
               WHERE s.archived_at IS NULL ORDER BY s.id DESC"""
        ).fetchall()
    return [spool_as_dict(row) for row in rows]



def add_spool(db_path: Path, payload: SpoolInput, actor_id: int):
    with session(db_path, write=True) as db:
        return {"id": insert_spool(db, payload, actor_id)}


def insert_spool(db, payload: SpoolInput, actor_id: int) -> int:
    """Create one physical spool inside a caller-owned transaction."""
    remaining = payload.initial_g if payload.remaining_g is None else payload.remaining_g
    if remaining > payload.initial_g:
        raise HTTPException(status_code=422, detail="Remaining weight cannot exceed the original spool weight.")
    opened = payload.opened or remaining < payload.initial_g
    timestamp = utc_now()
    if db.execute("SELECT 1 FROM products WHERE id=?", (payload.product_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Filament product not found.")
    cursor = db.execute(
        """INSERT INTO spools
           (uid, product_id, initial_g, remaining_g, opened, location, notes, created_at,
            tare_g,purchase_price_cents,purchase_currency,purchased_on,batch)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid4()), payload.product_id, payload.initial_g, remaining,
         int(opened), payload.location, payload.notes, timestamp,
         payload.tare_g, payload.purchase_price_cents, payload.purchase_currency,
         payload.purchased_on, payload.batch),
    )
    spool_id = cursor.lastrowid
    db.execute(
        """INSERT INTO movements
           (spool_id, kind, delta_g, remaining_after_g, note, created_at,actor_id,source)
           VALUES (?, 'initial', ?, ?, ?, ?,?,'registration')""",
        (spool_id, remaining, remaining, "Spool registered", timestamp, actor_id),
    )
    audit(db, actor_id, "spool_create", "spool", spool_id)
    return spool_id



def update_spool(db_path: Path, spool_id: int, payload: SpoolUpdate, actor_id: int):
    changes = payload.model_dump(exclude_unset=True)
    nullable = {'purchase_price_cents', 'purchased_on'}
    if not changes or any(value is None and field not in nullable for field, value in changes.items()):
        raise HTTPException(status_code=422, detail="At least one valid field is required.")
    if "opened" in changes:
        changes["opened"] = int(changes["opened"])
    assignments = ", ".join(f"{name}=?" for name in changes)
    with session(db_path, write=True) as db:
        if changes.get("opened") == 0:
            spool = db.execute(
                "SELECT initial_g, remaining_g FROM spools WHERE id=? AND archived_at IS NULL",
                (spool_id,),
            ).fetchone()
            if spool is None:
                raise HTTPException(status_code=404, detail="Spool not found.")
            if spool["remaining_g"] != spool["initial_g"]:
                raise HTTPException(
                    status_code=409,
                    detail="A used spool cannot be marked as sealed.",
                )
        result = db.execute(
            f"UPDATE spools SET {assignments} WHERE id=? AND archived_at IS NULL",
            (*changes.values(), spool_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Spool not found.")
        audit(db, actor_id, "spool_update", "spool", spool_id)
    return {"id": spool_id}



def spool_movements(db_path: Path, spool_id: int):
    with session(db_path) as db:
        if db.execute("SELECT 1 FROM spools WHERE id=?", (spool_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Spool not found.")
        rows = db.execute(
            """SELECT id, spool_id, kind, delta_g, remaining_after_g, note, created_at
               FROM movements WHERE spool_id=? ORDER BY id DESC""",
            (spool_id,),
        ).fetchall()
    return [dict(row) for row in rows]



def recent_movements(db_path: Path, limit: int = 30):
    with session(db_path) as db:
        rows = db.execute(
            """SELECT m.*, p.brand, p.name AS product_name,
                      p.material, p.color_name, p.color_hex
               FROM movements m JOIN spools s ON s.id=m.spool_id
               JOIN products p ON p.id=s.product_id
               ORDER BY m.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]



def archive_spool(db_path: Path, spool_id: int, actor_id: int):
    with session(db_path, write=True) as db:
        if db.execute("SELECT 1 FROM job_reservations WHERE spool_id=? LIMIT 1", (spool_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Release print reservations before archiving this spool.")
        if db.execute("SELECT 1 FROM printer_spool_slots WHERE spool_id=? LIMIT 1", (spool_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Unmap the loaded printer slot before archiving this spool.")
        result = db.execute(
            "UPDATE spools SET archived_at=? WHERE id=? AND archived_at IS NULL",
            (utc_now(), spool_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Active spool not found.")
        audit(db, actor_id, "spool_archive", "spool", spool_id)
    return {"id": spool_id, "archived": True}


