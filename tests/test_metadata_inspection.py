"""G-code and 3MF metadata remains advisory and untrusted."""
import io
import zipfile
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.gcode_metadata import gcode_tool_estimates, three_mf_plate_estimates
from tests.support import authenticate


def test_gcode_multimaterial_usage_and_conflicts():
    sample = b"; filament used [g] = 34.20, 10.80\n; total filament used [g] = 46.0\n"
    assert gcode_tool_estimates(sample) == [{"tool":0,"estimated_g":34},{"tool":1,"estimated_g":11}]
    assert gcode_tool_estimates(b"; filament used [g] = 0, 25.3\n") == [
        {"tool":1,"estimated_g":25}]
    assert gcode_tool_estimates(b"; filament used [g] = 10\n; filament used [g] = 20") == []
    assert gcode_tool_estimates(b"; material = no trustworthy weights") == []


def test_3mf_plates_explicitly_separated():
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w") as archive:
        archive.writestr("Metadata/slice_info.config",
            '<root><plate><filament id="1" used_g="12.6"/></plate>'
            '<plate><filament id="2" used_g="7.9"/></plate></root>')
    assert three_mf_plate_estimates(buff.getvalue()) == [
        {"plate":1,"materials":[{"tool":0,"estimated_g":13}]},
        {"plate":2,"materials":[{"tool":1,"estimated_g":8}]},
    ]


def test_inspection_never_changes_stock(tmp_path):
    with TestClient(create_app(tmp_path / "inspect.sqlite3")) as client:
        authenticate(client)
        result = client.post("/api/jobs/inspect?name=part.gcode",
                             content=b"; filament used [g] = 20.0, 3.0",
                             headers={"Content-Type":"application/octet-stream"})
        assert result.status_code == 200, result.text
        assert result.json()["plates"][0]["materials"][1] == {"tool":1,"estimated_g":3}
        assert client.get("/api/jobs").json() == []
        assert client.get("/api/spools").json() == []
