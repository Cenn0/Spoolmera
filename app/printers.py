"""Admin-configured, read-only OctoPrint and Moonraker connectors.

Defensive networking: exact RFC1918/ULA IP allowlist, no DNS resolution,
credentials or arbitrary paths in URLs, no proxy and no redirects. Tokens
come exclusively from operator environment variables and are not persisted.
"""
import ipaddress
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.database import session, utc_now
from app.auth import audit

TOKEN_PATTERN = re.compile(r"^FILAMENT_PRINTER_TOKEN_[A-Z0-9_]{1,50}$")
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"
))


class PrinterInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern=r"^(moonraker|octoprint)$")
    base_url: str = Field(min_length=10, max_length=160)
    token_env: str = ""
    enabled: bool = True


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_printer_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or
        parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment or
        parsed.port is None):
        raise ValueError("Use an http(s) URL with an explicit port and IP address only.")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("An exact private IP address is required; DNS hostnames are not supported.") from exc
    if not any(ip in network for network in PRIVATE_NETWORKS):
        raise ValueError("Only RFC1918 LAN or private IPv6 addresses are supported.")
    allowed = {item.strip() for item in os.getenv("FILAMENT_PRINTER_ALLOWED_IPS", "").split(",") if item.strip()}
    if str(ip) not in allowed:
        raise ValueError("This printer IP is not included in FILAMENT_PRINTER_ALLOWED_IPS.")
    return parsed.scheme + "://" + ("[" + str(ip) + "]" if ip.version == 6 else str(ip)) + ":" + str(parsed.port)


def validate_printer_input(payload: PrinterInput) -> str:
    base = normalize_printer_url(payload.base_url)
    if payload.token_env and not TOKEN_PATTERN.fullmatch(payload.token_env):
        raise ValueError("Token variable must match FILAMENT_PRINTER_TOKEN_<ALIAS>.")
    if payload.token_env and not os.getenv(payload.token_env):
        raise ValueError("Configured printer token environment variable is missing.")
    if payload.kind == "octoprint" and not payload.token_env:
        raise ValueError("OctoPrint requires a configured token environment variable.")
    return base


def safe_printer(row) -> dict:
    return {key: row[key] for key in ("id","name","kind","base_url","token_env","enabled","created_at")}


def fetch_json(printer, path: str) -> dict:
    # Revalidate stored config on each use: an environment allowlist change revokes access.
    base = normalize_printer_url(printer["base_url"])
    token_var = printer["token_env"]
    if token_var and not TOKEN_PATTERN.fullmatch(token_var):
        raise ValueError("Invalid configured token name.")
    token = os.getenv(token_var, "") if token_var else ""
    if token_var and not token:
        raise ValueError("Printer credentials are not configured.")
    headers = {"Accept": "application/json", "User-Agent": "FilamentManager/0.4"}
    if token:
        headers["X-Api-Key"] = token
    request = urllib.request.Request(base + path, headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=4.0) as response:
            if response.status != 200:
                raise ValueError("Printer responded with HTTP " + str(response.status))
            content = response.read(65537)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # Never leak URL credentials or token text into error responses.
        raise ValueError("Printer connection failed or returned an invalid response.") from exc
    if len(content) > 65536:
        raise ValueError("Printer response is unexpectedly large.")
    try:
        result = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Printer did not return valid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("Unexpected printer response.")
    return result


def printer_status(printer) -> dict:
    if printer["kind"] == "moonraker":
        data = fetch_json(printer, "/printer/objects/query?print_stats")
        stats = data.get("result", {}).get("status", {}).get("print_stats", {})
        if not isinstance(stats, dict) or "state" not in stats:
            raise ValueError("Moonraker print_stats is not available.")
        return {"state": str(stats["state"]), "filename": str(stats.get("filename") or "")}
    data = fetch_json(printer, "/api/job")
    info = data.get("job") or {}
    return {
        "state": str(data.get("state") or "Unknown"),
        "filename": str((info.get("file") or {}).get("name") or ""),
    }


def moonraker_history(printer) -> list[dict]:
    data = fetch_json(printer, "/server/history/list?limit=25")
    jobs = data.get("result", {}).get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Moonraker job history is unavailable or disabled.")
    return [job for job in jobs if isinstance(job, dict)]


def register_printer_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/printers")
    def printers():
        with session(db_path) as db:
            return [safe_printer(row) for row in db.execute(
                "SELECT * FROM printers ORDER BY name COLLATE NOCASE").fetchall()]

    @app.post("/api/printers", status_code=201)
    def add_printer(payload: PrinterInput, request: Request):
        try:
            base = validate_printer_input(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with session(db_path, write=True) as db:
            if db.execute("SELECT 1 FROM printers WHERE name=?", (payload.name,)).fetchone():
                raise HTTPException(status_code=409, detail="Printer name already exists.")
            printer_id = db.execute(
                "INSERT INTO printers(name,kind,base_url,token_env,enabled,created_at) VALUES(?,?,?,?,?,?)",
                (payload.name, payload.kind, base, payload.token_env, int(payload.enabled), utc_now()),
            ).lastrowid
            audit(db, request.state.user["id"], "printer_create", "printer", printer_id)
        return {"id": printer_id}

    @app.put("/api/printers/{printer_id}")
    def update_printer(printer_id: int, payload: PrinterInput, request: Request):
        try:
            base = validate_printer_input(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with session(db_path, write=True) as db:
            old = db.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone()
            if not old:
                raise HTTPException(status_code=404, detail="Printer not found.")
            if old["base_url"] != base or old["kind"] != payload.kind:
                if db.execute(
                    "SELECT 1 FROM print_jobs WHERE printer_id=? AND status IN ('pending','printing') LIMIT 1",
                    (printer_id,),
                ).fetchone():
                    raise HTTPException(status_code=409, detail="Finish or cancel active job mappings first.")
            db.execute(
                "UPDATE printers SET name=?,kind=?,base_url=?,token_env=?,enabled=? WHERE id=?",
                (payload.name,payload.kind,base,payload.token_env,int(payload.enabled),printer_id),
            )
            audit(db, request.state.user["id"], "printer_update", "printer", printer_id)
        return {"id": printer_id}

    @app.post("/api/printers/{printer_id}/probe")
    def probe(printer_id: int):
        with session(db_path) as db:
            printer = db.execute("SELECT * FROM printers WHERE id=? AND enabled=1", (printer_id,)).fetchone()
        if not printer:
            raise HTTPException(status_code=404, detail="Enabled printer not found.")
        try:
            return printer_status(printer)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
