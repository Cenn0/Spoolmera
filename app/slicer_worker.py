"""Internal-only, credential-free slicer worker. Never publish its TCP port."""
import asyncio
import hmac
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from app.slicing import MAX_STL, PROFILE_NAME, list_profiles, slice_stl

def create_worker_app() -> FastAPI:
    app = FastAPI(title="Internal Filament Slicer", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def require_worker_token(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        secret = os.getenv("FILAMENT_SLICER_WORKER_TOKEN", "")
        provided = request.headers.get("x-worker-token", "")
        if len(secret) < 32 or not hmac.compare_digest(
                secret.encode("utf-8"), provided.encode("utf-8")):
            return Response(status_code=401)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/profiles")
    def profiles():
        return {"profiles": list_profiles()}

    @app.post("/slice")
    async def slice_model(request: Request, profile: str = Query(min_length=1, max_length=64)):
        if not PROFILE_NAME.fullmatch(profile):
            raise HTTPException(status_code=422, detail="Invalid slicer profile name.")
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/octet-stream":
            raise HTTPException(status_code=415, detail="STL must be application/octet-stream.")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_STL:
                raise HTTPException(status_code=413, detail="STL exceeds the 8 MiB limit.")
            chunks.append(chunk)
        payload = b"".join(chunks)
        if len(payload) < 16:
            raise HTTPException(status_code=422, detail="Model is empty or invalid.")
        result, weight = await asyncio.to_thread(slice_stl, payload, profile)
        headers = {"Cache-Control": "no-store"}
        if weight is not None:
            headers["X-Estimated-Grams"] = str(weight)
        return Response(result, media_type="application/octet-stream", headers=headers)

    return app

app = create_worker_app()
