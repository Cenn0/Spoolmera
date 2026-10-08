"""Admin-configured, read-only OctoPrint and Moonraker connectors.

Defensive networking: exact RFC1918/ULA IP allowlist, no DNS resolution,
credentials or arbitrary paths in URLs, no proxy and no redirects. Tokens
come exclusively from operator environment variables and are not persisted.
"""
import ipaddress
import json
import math
import os
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, quote

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.core.policies import require_editor, require_admin
from app.database import session, utc_now
from app.auth import audit
from app.services.command_service import reserve_command, finalize_command, clear_command
from app.api.contracts import PrinterResponse

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


def response_object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Invalid printer response: " + label + " must be an object.")
    return value


def response_status(state, filename) -> dict:
    if not isinstance(state, str) or not state.strip() or not isinstance(filename, str):
        raise ValueError("Invalid printer state or filename.")
    return {"state": state, "filename": filename}


def printer_status(printer) -> dict:
    if printer["kind"] == "moonraker":
        data = fetch_json(printer, "/printer/objects/query?print_stats")
        result = response_object(data.get("result"), "result")
        status = response_object(result.get("status"), "status")
        stats = response_object(status.get("print_stats"), "print_stats")
        return response_status(stats.get("state"), stats.get("filename", ""))
    data = fetch_json(printer, "/api/job")
    info = response_object(data.get("job") if data.get("job") is not None else {}, "job")
    file = response_object(info.get("file") if info.get("file") is not None else {}, "file")
    # OctoPrint names only the basename; path is the relative identity for subfolders.
    filename = file.get("path", file.get("name"))
    return response_status(data.get("state"), filename if filename is not None else "")


def moonraker_history(printer) -> list[dict]:
    data = fetch_json(printer, "/server/history/list?limit=25")
    result = response_object(data.get("result"), "result")
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Moonraker job history is unavailable or disabled.")
    for job in jobs:
        if (not isinstance(job, dict) or not isinstance(job.get("job_id"), str)
                or not job["job_id"] or not isinstance(job.get("filename"), str)
                or not isinstance(job.get("status"), str)
                or type(job.get("start_time")) not in (int, float)
                or not math.isfinite(job["start_time"])):
            raise ValueError("Invalid Moonraker history entry.")
    return jobs


def moonraker_job(printer, job_id: str) -> dict | None:
    """Fetch a known history UID even after the entry left the latest 25."""
    if not job_id or len(job_id) > 120:
        raise ValueError("Invalid remote job identity.")
    data = fetch_json(printer, "/server/history/job?uid=" + quote(job_id, safe=""))
    # HTTP Moonraker history responses use a top-level "job"; support JSON-RPC
    # envelopes as well for adapter fixtures and version differences.
    root = data.get("result", data)
    entry = response_object(response_object(root, "history").get("job"), "job")
    if (entry.get("job_id") != job_id or not isinstance(entry.get("filename"), str)
            or not isinstance(entry.get("status"), str)
            or type(entry.get("start_time")) not in (int, float)
            or not math.isfinite(entry["start_time"])):
        raise ValueError("Invalid Moonraker history identity.")
    return entry


class PrinterCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume", "cancel"]


class ClearCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=10, max_length=500)


SAFE_UPLOAD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,169}\.(?:gcode|gco|gc)$", re.I)


def control_enabled() -> bool:
    """Fail closed: sending data or physical commands requires explicit opt-in."""
    return os.getenv("FILAMENT_PRINTER_CONTROL_ENABLED") == "1"


def require_control() -> None:
    if not control_enabled():
        raise HTTPException(status_code=403, detail="Printer write access is disabled by the operator.")


def write_controller(printer, path: str, *, body: bytes = b"", content_type: str | None = None) -> int:
    """Limited POST transport with the same IP allowlist, no proxy and no redirects as polling."""
    base = normalize_printer_url(printer["base_url"])
    token_var = printer["token_env"]
    if token_var and not TOKEN_PATTERN.fullmatch(token_var):
        raise ValueError("Invalid configured printer token.")
    token = os.getenv(token_var, "") if token_var else ""
    if token_var and not token:
        raise ValueError("Printer credentials are not configured.")
    headers = {"User-Agent": "FilamentManager/0.5"}
    if token:
        headers["X-Api-Key"] = token
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=10.0) as response:
            if response.status not in (200, 201, 204):
                raise ValueError("Printer rejected the operation.")
            if len(response.read(65537)) > 65536:
                raise ValueError("Printer response is unexpectedly large.")
            return response.status
    except urllib.error.HTTPError as exc:
        # Never expose the remote error body; controllers sometimes echo configuration.
        raise ValueError("Printer rejected the operation (HTTP " + str(exc.code) + ").") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("Printer operation failed. Confirm remote state before retrying.") from exc


def issue_control(printer, action: str) -> int:
    if printer["kind"] == "moonraker":
        return write_controller(printer, "/printer/print/" + action)
    payload = {"command": "pause", "action": action} if action != "cancel" else {"command": "cancel"}
    return write_controller(printer, "/api/job", body=json.dumps(payload).encode(),
                            content_type="application/json")


def upload_controller_file(printer, filename: str, content: bytes) -> int:
    """Upload only to G-code storage, never select or auto-start a print."""
    if not SAFE_UPLOAD_NAME.fullmatch(filename):
        raise ValueError("Use a simple ASCII G-code filename without folders.")
    boundary = "FilamentBoundary" + secrets.token_hex(18)
    b = boundary.encode("ascii")
    fields = b""
    if printer["kind"] == "moonraker":
        fields = b"--" + b + b'\r\nContent-Disposition: form-data; name="root"\r\n\r\ngcodes\r\n'
    prefix = (fields + b"--" + b + b'\r\nContent-Disposition: form-data; name="file"; filename="' +
              filename.encode("ascii") + b'"\r\nContent-Type: application/octet-stream\r\n\r\n')
    payload = prefix + content + b"\r\n--" + b + b"--\r\n"
    route = "/server/files/upload" if printer["kind"] == "moonraker" else "/api/files/local"
    return write_controller(printer, route, body=payload,
                            content_type="multipart/form-data; boundary=" + boundary)


def register_printer_routes(app: FastAPI, db_path: Path) -> None:
    router = APIRouter()
    @router.get("/api/printers/capabilities")
    def printer_capabilities():
        return {"write_enabled": control_enabled(), "max_upload_bytes": 16 * 1024 * 1024}

    @router.get("/api/printers", response_model=list[PrinterResponse])
    def printers(request: Request):
        with session(db_path) as db:
            rows = [safe_printer(row) for row in db.execute(
                "SELECT * FROM printers ORDER BY name COLLATE NOCASE").fetchall()]
        if request.state.user["role"] != "admin":
            for row in rows:
                row["base_url"] = ""
                row["token_env"] = ""
        return rows

    @router.post("/api/printers", status_code=201, dependencies=[Depends(require_admin)])
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

    @router.put("/api/printers/{printer_id}", dependencies=[Depends(require_admin)])
    def update_printer(printer_id: int, payload: PrinterInput, request: Request):
        try:
            base = validate_printer_input(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with session(db_path, write=True) as db:
            old = db.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone()
            if not old:
                raise HTTPException(status_code=404, detail="Printer not found.")
            if db.execute("SELECT 1 FROM printers WHERE name=? AND id<>?",
                          (payload.name, printer_id)).fetchone():
                raise HTTPException(status_code=409, detail="Printer name already exists.")
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

    @router.post("/api/printers/{printer_id}/probe", dependencies=[Depends(require_admin)])
    def probe(printer_id: int):
        with session(db_path) as db:
            printer = db.execute("SELECT * FROM printers WHERE id=? AND enabled=1", (printer_id,)).fetchone()
        if not printer:
            raise HTTPException(status_code=404, detail="Enabled printer not found.")
        try:
            return printer_status(printer)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/api/printers/{printer_id}/commands", dependencies=[Depends(require_admin)])
    def printer_command_history(printer_id: int):
        with session(db_path) as db:
            if not db.execute("SELECT 1 FROM printers WHERE id=?", (printer_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Printer not found.")
            return [dict(row) for row in db.execute(
                """SELECT id,job_id,action,state,http_status,detail,created_at,updated_at
                   FROM printer_commands WHERE printer_id=? ORDER BY created_at DESC LIMIT 100""",
                (printer_id,),
            ).fetchall()]

    @router.post("/api/printers/commands/{command_id}/clear", dependencies=[Depends(require_admin)])
    def clear_start_command(command_id: str, payload: ClearCommand, request: Request):
        clear_command(db_path, command_id, request.state.user["id"], payload.reason)
        return {"id": command_id, "state": "cleared"}

    @router.post("/api/printers/{printer_id}/control", dependencies=[Depends(require_admin)])
    def control_printer(printer_id: int, payload: PrinterCommand, request: Request):
        require_control()
        with session(db_path) as db:
            printer = db.execute(
                "SELECT * FROM printers WHERE id=? AND enabled=1", (printer_id,)
            ).fetchone()
        if not printer:
            raise HTTPException(status_code=404, detail="Enabled printer not found.")
        command_id = reserve_command(db_path, printer_id, None, payload.action, request.state.user["id"])
        try:
            status = issue_control(printer, payload.action)
        except BaseException as exc:
            finalize_command(db_path, command_id, "unknown", detail="Controller outcome unknown; verify physically.")
            if isinstance(exc, ValueError):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            raise
        finalize_command(db_path, command_id, "acknowledged", http_status=status)
        with session(db_path, write=True) as db:
            if payload.action == "cancel":
                db.execute(
                    """UPDATE print_jobs SET status='needs_review',accounting_status='needs_review',
                              note='Print cancelled at controller; verify actual consumed material.',
                              updated_at=?
                       WHERE printer_id=? AND status='printing'""",
                    (utc_now(), printer_id),
                )
            audit(db, request.state.user["id"], "printer_" + payload.action, "printer", printer_id)
        return {"printer_id": printer_id, "command_id": command_id,
                "action": payload.action, "http_status": status}

    app.include_router(router)
