"""Filament Manager REST API and local web frontend."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import initialize_database, session, utc_now
from app.models import MovementInput, ProductInput, SpoolInput, SpoolUpdate

STATIC_DIR = Path(__file__).resolve().parent / "static"


def spool_as_dict(row) -> dict:
    data = dict(row)
    data["opened"] = bool(data["opened"])
    data["status"] = (
        "empty" if data["remaining_g"] == 0
        else "opened" if data["opened"]
        else "sealed"
    )
    return data


def create_app(database_path: str | Path | None = None) -> FastAPI:
    db_path = Path(database_path or os.environ.get("FILAMENT_DB_PATH", ".data/filaments.sqlite3"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize_database(db_path)
        yield

    app = FastAPI(
        title="Filament Manager API",
        version="0.1.0",
        description="Lokale Verwaltung von Filamentprodukten, Rollen und Bestandsbewegungen.",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        with session(db_path) as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/overview")
    def overview():
        with session(db_path) as db:
            counts = db.execute(
                """SELECT COUNT(*) AS total_spools,
                          COALESCE(SUM(remaining_g), 0) AS remaining_g,
                          COALESCE(SUM(CASE WHEN remaining_g = 0 THEN 1 ELSE 0 END), 0) AS empty_spools,
                          COALESCE(SUM(CASE WHEN remaining_g > 0 AND opened = 1 THEN 1 ELSE 0 END), 0) AS opened_spools,
                          COALESCE(SUM(CASE WHEN remaining_g > 0 AND opened = 0 THEN 1 ELSE 0 END), 0) AS sealed_spools,
                          COALESCE(SUM(CASE WHEN remaining_g BETWEEN 1 AND 200 THEN 1 ELSE 0 END), 0) AS low_spools
                   FROM spools WHERE archived_at IS NULL"""
            ).fetchone()
            products = db.execute("SELECT COUNT(*) AS total FROM products").fetchone()["total"]
        return {**dict(counts), "total_products": products}

    @app.get("/api/products")
    def list_products():
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

    @app.post("/api/products", status_code=201)
    def add_product(payload: ProductInput):
        timestamp = utc_now()
        with session(db_path, write=True) as db:
            cursor = db.execute(
                """INSERT INTO products (brand, name, material, color_name, color_hex,
                                         diameter_mm, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (payload.brand, payload.name, payload.material, payload.color_name,
                 payload.color_hex, payload.diameter_mm, payload.notes, timestamp, timestamp),
            )
            product_id = cursor.lastrowid
        return {"id": product_id}

    @app.put("/api/products/{product_id}")
    def update_product(product_id: int, payload: ProductInput):
        with session(db_path, write=True) as db:
            result = db.execute(
                """UPDATE products
                   SET brand=?, name=?, material=?, color_name=?, color_hex=?,
                       diameter_mm=?, notes=?, updated_at=?
                   WHERE id=?""",
                (payload.brand, payload.name, payload.material, payload.color_name,
                 payload.color_hex, payload.diameter_mm, payload.notes, utc_now(), product_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Filamentprodukt nicht gefunden.")
        return {"id": product_id}

    @app.get("/api/spools")
    def list_spools():
        with session(db_path) as db:
            rows = db.execute(
                """SELECT s.*, p.brand, p.name AS product_name, p.material,
                          p.color_name, p.color_hex, p.diameter_mm
                   FROM spools s JOIN products p ON p.id=s.product_id
                   WHERE s.archived_at IS NULL ORDER BY s.id DESC"""
            ).fetchall()
        return [spool_as_dict(row) for row in rows]

    @app.post("/api/spools", status_code=201)
    def add_spool(payload: SpoolInput):
        remaining = payload.initial_g if payload.remaining_g is None else payload.remaining_g
        if remaining > payload.initial_g:
            raise HTTPException(status_code=422, detail="Restbestand darf den Startbestand nicht übersteigen.")
        opened = payload.opened or remaining < payload.initial_g
        timestamp = utc_now()
        with session(db_path, write=True) as db:
            if db.execute("SELECT 1 FROM products WHERE id=?", (payload.product_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="Filamentprodukt nicht gefunden.")
            cursor = db.execute(
                """INSERT INTO spools
                   (product_id, initial_g, remaining_g, opened, location, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (payload.product_id, payload.initial_g, remaining, int(opened),
                 payload.location, payload.notes, timestamp),
            )
            spool_id = cursor.lastrowid
            db.execute(
                """INSERT INTO movements
                   (spool_id, kind, delta_g, remaining_after_g, note, created_at)
                   VALUES (?, 'initial', ?, ?, ?, ?)""",
                (spool_id, remaining, remaining, "Rolle erfasst", timestamp),
            )
        return {"id": spool_id}

    @app.patch("/api/spools/{spool_id}")
    def update_spool(spool_id: int, payload: SpoolUpdate):
        changes = payload.model_dump(exclude_unset=True)
        if not changes or any(value is None for value in changes.values()):
            raise HTTPException(status_code=422, detail="Mindestens ein gültiges Feld ist erforderlich.")
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
                    raise HTTPException(status_code=404, detail="Rolle nicht gefunden.")
                if spool["remaining_g"] != spool["initial_g"]:
                    raise HTTPException(
                        status_code=409,
                        detail="Eine benutzte Rolle kann nicht als ungeöffnet markiert werden.",
                    )
            result = db.execute(
                f"UPDATE spools SET {assignments} WHERE id=? AND archived_at IS NULL",
                (*changes.values(), spool_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Rolle nicht gefunden.")
        return {"id": spool_id}

    @app.post("/api/spools/{spool_id}/movements", status_code=201)
    def add_movement(spool_id: int, payload: MovementInput):
        if payload.kind == "consume" and payload.grams <= 0:
            raise HTTPException(status_code=422, detail="Verbrauch muss positiv sein.")
        if payload.kind == "adjust" and (payload.grams == 0 or not payload.note):
            raise HTTPException(status_code=422, detail="Korrekturen benötigen eine Menge und einen Grund.")
        delta = -payload.grams if payload.kind == "consume" else payload.grams
        with session(db_path, write=True) as db:
            spool = db.execute(
                "SELECT initial_g, remaining_g FROM spools WHERE id=? AND archived_at IS NULL",
                (spool_id,),
            ).fetchone()
            if spool is None:
                raise HTTPException(status_code=404, detail="Rolle nicht gefunden.")
            remaining = spool["remaining_g"] + delta
            if remaining < 0 or remaining > spool["initial_g"]:
                raise HTTPException(
                    status_code=409,
                    detail="Buchung außerhalb des möglichen Bestands (0 bis Startmenge).",
                )
            db.execute(
                """UPDATE spools
                   SET remaining_g=?, opened=CASE WHEN ? < 0 THEN 1 ELSE opened END
                   WHERE id=?""",
                (remaining, delta, spool_id),
            )
            cursor = db.execute(
                """INSERT INTO movements (spool_id, kind, delta_g, remaining_after_g, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (spool_id, payload.kind, delta, remaining, payload.note, utc_now()),
            )
            movement_id = cursor.lastrowid
        return {"id": movement_id, "remaining_g": remaining}

    @app.get("/api/spools/{spool_id}/movements")
    def spool_movements(spool_id: int):
        with session(db_path) as db:
            if db.execute("SELECT 1 FROM spools WHERE id=?", (spool_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="Rolle nicht gefunden.")
            rows = db.execute(
                """SELECT id, spool_id, kind, delta_g, remaining_after_g, note, created_at
                   FROM movements WHERE spool_id=? ORDER BY id DESC""",
                (spool_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/movements")
    def recent_movements(limit: int = Query(default=30, ge=1, le=200)):
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

    @app.post("/api/spools/{spool_id}/archive")
    def archive_spool(spool_id: int):
        with session(db_path, write=True) as db:
            result = db.execute(
                "UPDATE spools SET archived_at=? WHERE id=? AND archived_at IS NULL",
                (utc_now(), spool_id),
            )
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Aktive Rolle nicht gefunden.")
        return {"id": spool_id, "archived": True}

    return app


app = create_app()
