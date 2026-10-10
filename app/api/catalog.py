"""Read-only, opt-in Open Filament Database browser with a bounded offline cache.

Only fixed known endpoint shapes and a single HTTPS origin are allowed.
No external response is silently applied to local product records.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from fastapi import FastAPI, HTTPException

ORIGIN = "https://api.openfilamentdatabase.org/api/v1/brands/"
SLUG = re.compile(r"^[A-Za-z0-9+]+(?:_[A-Za-z0-9+]+)*$")
LIMIT = 2 * 1024 * 1024
CACHE_SECONDS = 86400


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Catalog redirect rejected", headers, fp)


def _validate(path: str) -> None:
    if path == "index.json":
        return
    parts = path.split("/")
    valid = (len(parts) in (2,4,6,7)
             and parts[-1].endswith(".json")
             and parts[1:2] != [".."])
    if not valid:
        raise HTTPException(422, "Invalid catalog resource.")
    if len(parts) == 2:
        valid = parts[1] == "index.json" and bool(SLUG.fullmatch(parts[0]))
    elif len(parts) == 4:
        valid = (parts[1] == "materials" and parts[3] == "index.json"
                 and all(SLUG.fullmatch(s) for s in (parts[0],parts[2])))
    elif len(parts) == 6:
        valid = (parts[1] == "materials" and parts[3] == "filaments"
                 and parts[5] == "index.json"
                 and all(SLUG.fullmatch(s) for s in (parts[0],parts[2],parts[4])))
    else:
        valid = (parts[1] == "materials" and parts[3] == "filaments"
                 and parts[5] == "variants" and parts[6].endswith(".json")
                 and all(SLUG.fullmatch(s) for s in (parts[0],parts[2],parts[4],parts[6][:-5])))
    if not valid:
        raise HTTPException(422, "Invalid catalog resource.")


def _cache_path(path: str) -> Path:
    db_path = Path(os.environ.get("SPOOLMERA_DB_PATH", ".data/spoolmera.sqlite3"))
    return db_path.parent / "catalog-cache" / path


def _read_cache(cache: Path) -> dict | None:
    try:
        if not cache.is_file() or cache.stat().st_size > LIMIT:
            return None
        payload = json.loads(cache.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError):
        return None


def fetch_catalog_json(path: str) -> dict:
    if os.getenv("SPOOLMERA_CATALOG_ENABLED", "0") != "1":
        raise HTTPException(503, "Online catalog is disabled; enable SPOOLMERA_CATALOG_ENABLED=1.")
    _validate(path)
    cache = _cache_path(path)
    saved = _read_cache(cache)
    if saved is not None and time.time() - cache.stat().st_mtime < CACHE_SECONDS:
        return saved
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirect())
    request = urllib.request.Request(
        ORIGIN + path, headers={"Accept": "application/json", "User-Agent": "Spoolmera/0.7"}
    )
    try:
        with opener.open(request, timeout=6) as response:
            if response.status != 200 or "json" not in response.headers.get("Content-Type", ""):
                raise ValueError("Unexpected catalog response.")
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("Catalog response is too large.")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("Unexpected catalog JSON.")
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError, OSError) as exc:
        if saved is not None:
            return saved
        raise HTTPException(502, "Catalog unavailable or returned invalid data.") from exc
    # Cache best effort; the application remains functional on a read-only volume.
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(cache.suffix + ".tmp")
        tmp.write_text(json.dumps(decoded, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)
    except OSError:
        pass
    return decoded


def _checked(*values: str) -> None:
    if not all(SLUG.fullmatch(value) for value in values):
        raise HTTPException(422, "Invalid catalog slug.")


def register_catalog_routes(app: FastAPI) -> None:
    @app.get("/api/catalog/brands")
    def catalog_brands():
        raw = fetch_catalog_json("index.json")
        brands = raw.get("brands")
        if not isinstance(brands, list):
            raise HTTPException(502, "Malformed catalog brand index.")
        return {"version": raw.get("version"), "brands": [
            {"name": b["name"], "slug": b["slug"]}
            for b in brands if isinstance(b, dict) and isinstance(b.get("name"), str)
            and isinstance(b.get("slug"), str) and SLUG.fullmatch(b["slug"])
        ]}

    @app.get("/api/catalog/brands/{brand}")
    def catalog_brand(brand: str):
        _checked(brand)
        return fetch_catalog_json(brand + "/index.json")

    @app.get("/api/catalog/brands/{brand}/materials/{material}")
    def catalog_material(brand: str, material: str):
        _checked(brand,material)
        return fetch_catalog_json(f"{brand}/materials/{material}/index.json")

    @app.get("/api/catalog/brands/{brand}/materials/{material}/filaments/{filament}")
    def catalog_filament(brand: str, material: str, filament: str):
        _checked(brand,material,filament)
        return fetch_catalog_json(
            f"{brand}/materials/{material}/filaments/{filament}/index.json"
        )

    @app.get("/api/catalog/brands/{brand}/materials/{material}/filaments/{filament}/variants/{variant}")
    def catalog_variant(brand: str, material: str, filament: str, variant: str):
        _checked(brand,material,filament,variant)
        return fetch_catalog_json(
            f"{brand}/materials/{material}/filaments/{filament}/variants/{variant}.json"
        )
