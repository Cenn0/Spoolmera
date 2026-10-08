"""Opt-in Open Filament Database search; fixed HTTPS origin and bounded responses."""
import json
import os
import re
import urllib.error
import urllib.request
from fastapi import FastAPI, HTTPException

ORIGIN = "https://api.openfilamentdatabase.org/api/v1/brands/"
SLUG = re.compile(r"^[a-z0-9+]+(?:_[a-z0-9+]+)*$")


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Catalog redirect rejected", headers, fp)


def fetch_catalog_json(path: str) -> dict:
    if os.getenv("FILAMENT_CATALOG_ENABLED", "0") != "1":
        raise HTTPException(503, "Online catalog is disabled; enable FILAMENT_CATALOG_ENABLED=1.")
    if path != "index.json" and not re.fullmatch(r"[a-z0-9+_]+/index\.json", path):
        raise HTTPException(422, "Invalid catalog resource.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirect())
    request = urllib.request.Request(
        ORIGIN + path, headers={"Accept": "application/json", "User-Agent": "FilamentManager/0.7"}
    )
    try:
        with opener.open(request, timeout=6) as response:
            if response.status != 200:
                raise HTTPException(502, "Catalog returned an unexpected status.")
            if "json" not in response.headers.get("Content-Type", ""):
                raise HTTPException(502, "Catalog returned unexpected content.")
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise HTTPException(502, "Catalog response is too large.")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("Unexpected catalog response")
        return decoded
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError) as exc:
        raise HTTPException(502, "Catalog unavailable or returned invalid JSON.") from exc


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

    @app.get("/api/catalog/brands/{slug}")
    def catalog_brand(slug: str):
        if not SLUG.fullmatch(slug):
            raise HTTPException(422, "Invalid brand slug.")
        # A catalog preview is never implicitly imported or merged into existing products.
        return fetch_catalog_json(slug + "/index.json")
