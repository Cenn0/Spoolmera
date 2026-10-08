"""Opt-in PrusaSlicer CLI bridge: STL only, operator-owned profiles, no shell."""
import asyncio
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response

from app.auth import audit
from app.core.policies import require_editor, require_admin
from app.database import session
from app.jobs import estimate_gcode

PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_STL = 8 * 1024 * 1024
MAX_RESULT = 16 * 1024 * 1024
SLICER_LOCK = threading.BoundedSemaphore(1)


def slicer_enabled() -> bool:
    return os.getenv("FILAMENT_SLICER_ENABLED") == "1"


def profile_root() -> Path:
    return Path(os.getenv("FILAMENT_SLICER_PROFILES_DIR", "/config/slicer-profiles"))


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
    binary = Path(os.getenv("FILAMENT_SLICER_EXECUTABLE", "/usr/bin/prusa-slicer"))
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
                     "--export-gcode", "--output", str(output), str(source)],
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


def register_slicing_routes(app: FastAPI, db_path: Path) -> None:
    @app.get("/api/slicing/profiles", dependencies=[Depends(require_admin)])
    def profiles():
        return {"enabled": slicer_enabled(), "profiles": list_profiles()}

    @app.post("/api/slicing/slice", dependencies=[Depends(require_admin)])
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
        content, estimated = await asyncio.to_thread(slice_stl, data, profile)
        with session(db_path, write=True) as db:
            audit(db, request.state.user["id"], "slicer_run", "profile", None)
        headers = {"Content-Disposition": 'attachment; filename="sliced.gcode"',
                   "Cache-Control": "no-store"}
        if estimated is not None:
            headers["X-Estimated-Grams"] = str(estimated)
        return Response(content=content, media_type="application/octet-stream", headers=headers)
