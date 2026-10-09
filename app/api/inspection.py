"""Read-only user-file inspection. Files are not persisted, sliced or uploaded."""
from fastapi import FastAPI, HTTPException, Request, Query
from app.services.gcode_metadata import MAX_FILE, gcode_tool_estimates, three_mf_plate_estimates
from app.api.contracts import InspectionResponse


def register_inspection_routes(app: FastAPI) -> None:
    @app.post("/api/jobs/inspect", response_model=InspectionResponse)
    async def inspect(request: Request, name: str = Query(min_length=1,max_length=180)):
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/octet-stream":
            raise HTTPException(415, "Expected raw file bytes.")
        lower = name.lower()
        if not lower.endswith((".gcode",".gco",".gc",".3mf")):
            raise HTTPException(422, "Supported files: .gcode, .gco, .gc, .3mf.")
        chunks = []
        total = 0
        async for part in request.stream():
            total += len(part)
            if total > MAX_FILE:
                raise HTTPException(413, "File exceeds the 16 MiB metadata inspection limit.")
            chunks.append(part)
        try:
            payload = b"".join(chunks)
            if lower.endswith(".3mf"):
                plates = three_mf_plate_estimates(payload)
            else:
                tools = gcode_tool_estimates(payload)
                plates = [{"plate": 1, "materials": tools}] if tools else []
        except (ValueError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"file_stored": False, "verified": False, "source": "slicer_metadata",
                "plates": plates, "needs_manual_estimate": not bool(plates)}
