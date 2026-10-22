"""Opt-in PrusaSlicer CLI bridge: STL only, operator-owned profiles, no shell."""
import asyncio
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import json
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response

from app.auth import audit
from app.core.policies import require_editor, require_admin
from app.database import session
from app.jobs import estimate_gcode

PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_STL = 8 * 1024 * 1024
MAX_RESULT = 16 * 1024 * 1024
# Match the optional Compose worker CPU quota instead of the host CPU count.
SLICER_THREADS = 2
SLICER_LOCK = threading.BoundedSemaphore(1)


class RejectWorkerRedirect(urllib.request.HTTPRedirectHandler):
    """An isolated worker cannot make the API contact a second origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def slicer_enabled() -> bool:
    return os.getenv("SPOOLMERA_SLICER_ENABLED") == "1"


def profile_root() -> Path:
    return Path(os.getenv("SPOOLMERA_SLICER_PROFILES_DIR", "/config/slicer-profiles"))


def list_profiles() -> list[str]:
    if not slicer_enabled() or not profile_root().is_dir():
        return []
    return sorted(
        f.stem for f in profile_root().iterdir()
        if f.is_file() and not f.is_symlink() and f.suffix == ".ini"
        and PROFILE_NAME.fullmatch(f.stem)
    )


def slice_stl(data: bytes, name: str) -> tuple[bytes, int | None]:
    if not slicer_enabled():
        raise HTTPException(status_code=403, detail="Slicing is disabled by the operator.")
    if name not in list_profiles():
        raise HTTPException(status_code=422, detail="Unknown or unapproved slicer profile.")
    # Operator profiles are privileged configuration, not user uploads.
    # Reject known slicer post-processing hooks: those execute arbitrary programs.
    profile_file = profile_root() / (name + ".ini")
    if len(profile_file.read_bytes()) > 1024 * 1024:
        raise HTTPException(status_code=422, detail="Approved profile exceeds 1 MiB.")
    profile_text = profile_file.read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?im)^\s*post_process\s*=\s*\S", profile_text):
        raise HTTPException(status_code=422, detail="Slicer post-processing commands are not allowed.")
    binary = Path(os.getenv("SPOOLMERA_SLICER_EXECUTABLE", "/usr/bin/prusa-slicer"))
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise HTTPException(status_code=503, detail="PrusaSlicer CLI is not installed.")
    if not SLICER_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Another slicing operation is in progress.")
    try:
        with tempfile.TemporaryDirectory(prefix="filament-slice-") as work:
            source = Path(work) / "model.stl"
            output = Path(work) / "result.gcode"
            source.write_bytes(data)
            # No user-provided CLI flags, shell commands, profile paths or output paths.
            # Avoid leaking printer credentials to the external executable.
            env = {"HOME": work, "TMPDIR": work, "PATH": "/usr/bin:/bin",
                   "LANG": "C", "LC_ALL": "C"}
            try:
                result = subprocess.run(
                    [str(binary), "--load", str(profile_root() / (name + ".ini")),
                     "--threads", str(SLICER_THREADS), "--export-gcode", "--output", str(output), str(source)],
                    cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=60, check=False,
                )
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=504, detail="Slicing exceeded the 60-second limit.") from None
            except OSError:
                raise HTTPException(status_code=502, detail="Could not execute PrusaSlicer.") from None
            if result.returncode != 0 or not output.is_file():
                raise HTTPException(status_code=422, detail="PrusaSlicer could not slice this model/profile.")
            size = output.stat().st_size
            if size < 1 or size > MAX_RESULT:
                raise HTTPException(status_code=413, detail="Generated G-code exceeds the permitted size.")
            content = output.read_bytes()
            return content, estimate_gcode(content)
    finally:
        SLICER_LOCK.release()


def worker_url() -> str:
    # The worker is only reachable via the Compose-internal slicer network.
    url = os.getenv("SPOOLMERA_SLICER_WORKER_URL", "")
    secret = os.getenv("SPOOLMERA_SLICER_WORKER_TOKEN", "")
    if url != "http://slicer-worker:8767" or len(secret) < 32:
        raise HTTPException(status_code=503, detail="Isolated slicer worker is not configured.")
    return url


def request_worker(path: str, data: bytes | None = None) -> tuple[bytes, dict]:
    url = worker_url()
    token = os.environ["SPOOLMERA_SLICER_WORKER_TOKEN"]
    headers = {"X-Worker-Token": token}
    if data is not None:
        headers["Content-Type"] = "application/octet-stream"
    request = urllib.request.Request(url + path, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
    # Never use process HTTP proxy settings for internal slicing.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectWorkerRedirect())
    try:
        with opener.open(request, timeout=75) as response:
            if response.status != 200:
                raise HTTPException(status_code=502, detail="Slicer worker failed.")
            result = response.read(MAX_RESULT + 1)
            if len(result) > MAX_RESULT:
                raise HTTPException(status_code=413, detail="Slicer result is too large.")
            return result, dict(response.headers)
    except urllib.error.HTTPError as exc:
        # Forward only bounded, structured error messages from our authenticated worker.
        try:
            detail = json.loads(exc.read(1024)).get("detail", "Slicer worker rejected request.")
            if not isinstance(detail, str):
                detail = "Slicer worker rejected request."
        except (ValueError, UnicodeError, AttributeError):
            detail = "Slicer worker rejected request."
        raise HTTPException(status_code=exc.code if 400 <= exc.code < 500 else 502,
                            detail=detail[:200]) from None
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Isolated slicer worker is unavailable.") from exc


def worker_profiles() -> list[str]:
    data, _ = request_worker("/profiles")
    try:
        profiles = json.loads(data)["profiles"]
        if not isinstance(profiles, list) or any(
                not isinstance(x, str) or not PROFILE_NAME.fullmatch(x) for x in profiles):
            raise ValueError("Invalid profile response")
        return profiles
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Invalid slicer worker response.") from exc


def remote_slice_stl(data: bytes, name: str) -> tuple[bytes, int | None]:
    content, headers = request_worker("/slice?profile=" + name, data)
    raw_weight = headers.get("X-Estimated-Grams")
    try:
        weight = int(raw_weight) if raw_weight is not None else None
        if weight is not None and not 0 < weight <= 100000:
            raise ValueError("Invalid weight")
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid worker weight estimate.") from exc
    return content, weight


def register_slicing_routes(app: FastAPI, db_path: Path) -> None:
    router = APIRouter()
    @router.get("/api/slicing/profiles", dependencies=[Depends(require_admin)])
    async def profiles():
        if not slicer_enabled():
            return {"enabled": False, "profiles": []}
        return {"enabled": True, "profiles": await asyncio.to_thread(worker_profiles)}

    @router.post("/api/slicing/slice", dependencies=[Depends(require_admin)])
    async def slice_model(request: Request, profile: str = Query(min_length=1, max_length=64)):
        if not slicer_enabled():
            raise HTTPException(status_code=403, detail="Slicing is disabled by the operator.")
        if not PROFILE_NAME.fullmatch(profile):
            raise HTTPException(status_code=422, detail="Invalid slicer profile name.")
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/octet-stream":
            raise HTTPException(status_code=415, detail="STL must be sent as application/octet-stream.")
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_STL:
                raise HTTPException(status_code=413, detail="STL exceeds the 8 MiB limit.")
            chunks.append(chunk)
        data = b"".join(chunks)
        if len(data) < 16:
            raise HTTPException(status_code=422, detail="Model is empty or invalid.")
        content, estimated = await asyncio.to_thread(remote_slice_stl, data, profile)
        with session(db_path, write=True) as db:
            audit(db, request.state.user["id"], "slicer_run", "profile", None)
        headers = {"Content-Disposition": 'attachment; filename="sliced.gcode"',
                   "Cache-Control": "no-store"}
        if estimated is not None:
            headers["X-Estimated-Grams"] = str(estimated)
        return Response(content=content, media_type="application/octet-stream", headers=headers)

    app.include_router(router)
