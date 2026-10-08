"""Regression tests for printer writes, slicer invocation, cloud events and MMU accounting.

All controller interactions are mocked. Hardware/cloud provider interoperability
must be validated separately with actual devices and approved provider APIs.
"""
import hashlib
import hmac
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database import initialize_database, session
from app.main import create_app
from tests.support import authenticate
from tests.test_security_jobs import make_inventory


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "operations.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        s0 = make_inventory(client)
        s1 = make_inventory(client)
        printer = client.post("/api/printers", json={
            "name": "Workshop", "kind": "moonraker", "base_url": "http://192.168.50.20:7125",
            "token_env": "", "enabled": True,
        })
        assert printer.status_code == 201, printer.text
        yield client, path, printer.json()["id"], s0, s1


def multi(client, printer, s0, s1, file="multi.gcode"):
    return client.post("/api/jobs/multi", json={
        "printer_id": printer, "file_name": file, "note": "tool test",
        "materials": [
            {"tool": 0, "spool_id": s0, "estimated_g": 120},
            {"tool": 1, "spool_id": s1, "estimated_g": 80},
        ],
    })


def test_multimaterial_ledger_is_atomic_and_idempotent(workspace):
    client, path, printer, s0, s1 = workspace
    registered = multi(client, printer, s0, s1)
    assert registered.status_code == 201, registered.text
    job_id = registered.json()["id"]
    with session(path, write=True) as db:
        db.execute("UPDATE print_jobs SET status='needs_review' WHERE id=?", (job_id,))
    result = client.post(f"/api/jobs/{job_id}/resolve", json={"action": "debit"})
    assert result.status_code == 200, result.text
    assert client.post(f"/api/jobs/{job_id}/resolve", json={"action": "debit"}).status_code == 409
    assert {row["id"]: row["remaining_g"] for row in client.get("/api/spools").json()}[s0] == 880
    assert {row["id"]: row["remaining_g"] for row in client.get("/api/spools").json()}[s1] == 920
    job = next(j for j in client.get("/api/jobs").json() if j["id"] == job_id)
    assert [(m["tool"], m["estimated_g"]) for m in job["materials"]] == [(0, 120), (1, 80)]
    with session(path) as db:
        assert db.execute("SELECT count(*) FROM movements WHERE print_job_id=?", (job_id,)).fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM job_materials WHERE job_id=? AND movement_id IS NOT NULL",
                          (job_id,)).fetchone()[0] == 2


def test_multimaterial_validates_tools_and_aggregate_stock(workspace):
    client, path, printer, s0, s1 = workspace
    duplicate = client.post("/api/jobs/multi", json={
        "printer_id": printer, "file_name": "duplicate.gcode",
        "materials": [{"tool": 0, "spool_id": s0, "estimated_g": 1},
                      {"tool": 0, "spool_id": s1, "estimated_g": 2}],
    })
    assert duplicate.status_code == 422
    insufficient = client.post("/api/jobs/multi", json={
        "printer_id": printer, "file_name": "same-spool.gcode",
        "materials": [{"tool": 0, "spool_id": s0, "estimated_g": 650},
                      {"tool": 1, "spool_id": s0, "estimated_g": 650}],
    })
    assert insufficient.status_code == 409
    with session(path) as db:
        assert db.execute("SELECT count(*) FROM print_jobs").fetchone()[0] == 0


def test_multimaterial_no_partial_debit_on_second_spool_understock(workspace):
    client, path, printer, s0, s1 = workspace
    job_id = multi(client, printer, s0, s1).json()["id"]
    with session(path, write=True) as db:
        db.execute("UPDATE print_jobs SET status='needs_review' WHERE id=?", (job_id,))
    assert client.post(f"/api/spools/{s1}/movements", json={"kind": "consume", "grams": 950}).status_code == 201
    response = client.post(f"/api/jobs/{job_id}/resolve", json={"action": "debit"})
    assert response.status_code == 409
    spools = {r["id"]: r["remaining_g"] for r in client.get("/api/spools").json()}
    assert spools[s0] == 1000
    assert spools[s1] == 50
    with session(path) as db:
        assert db.execute("SELECT count(*) FROM movements WHERE print_job_id=?", (job_id,)).fetchone()[0] == 0


def test_v3_material_migration_preserves_existing_records(workspace):
    client, path, printer, s0, s1 = workspace
    job_id = client.post("/api/jobs", json={
        "printer_id": printer, "spool_id": s0, "file_name": "old.gcode", "estimated_g": 44
    }).json()["id"]
    with session(path, write=True) as db:
        db.execute("DELETE FROM job_materials")
        db.execute("DROP INDEX idx_movements_print_job_spool")
        db.execute("CREATE UNIQUE INDEX idx_movements_print_job ON movements(print_job_id) WHERE print_job_id IS NOT NULL")
        db.execute("PRAGMA user_version = 3")
    initialize_database(path)
    initialize_database(path)
    with session(path) as db:
        mat = db.execute("SELECT tool,spool_id,estimated_g FROM job_materials WHERE job_id=?", (job_id,)).fetchone()
        assert tuple(mat) == (0, s0, 44)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4


def test_printer_control_default_off_and_admin_only(workspace, monkeypatch):
    client, path, printer, s0, s1 = workspace
    assert client.get("/api/printers/capabilities").json()["write_enabled"] is False
    assert client.post(f"/api/printers/{printer}/control", json={"action": "pause"}).status_code == 403
    monkeypatch.setenv("FILAMENT_PRINTER_CONTROL_ENABLED", "1")
    seen = []
    monkeypatch.setattr("app.printers.write_controller", lambda row, route, **kwargs: seen.append((route,kwargs)) or 204)
    assert client.post(f"/api/printers/{printer}/control", json={"action": "pause"}).status_code == 200
    assert seen == [("/printer/print/pause", {})]
    assert client.post(f"/api/printers/{printer}/control", json={"action": "send_gcode"}).status_code == 422
    created = client.post("/api/auth/users", json={
        "username": "edit-user", "password": "editor-password-strong-2026", "role": "editor"
    })
    assert created.status_code == 201
    with TestClient(create_app(path)) as editor:
        response = editor.post("/api/auth/login", json={
            "username": "edit-user", "password": "editor-password-strong-2026"
        })
        editor.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        assert editor.post(f"/api/printers/{printer}/control", json={"action": "pause"}).status_code == 403


def test_upload_requires_matching_filename_never_auto_prints(workspace, monkeypatch):
    client, path, printer, s0, s1 = workspace
    job_id = client.post("/api/jobs", json={
        "printer_id": printer, "spool_id": s0, "file_name": "part.gcode", "estimated_g": 20,
    }).json()["id"]
    query = {"file_name": "part.gcode"}
    headers = {"Content-Type": "application/octet-stream"}
    assert client.post(f"/api/jobs/{job_id}/upload", params=query, content=b"G1 X0\n", headers=headers).status_code == 403
    monkeypatch.setenv("FILAMENT_PRINTER_CONTROL_ENABLED", "1")
    assert client.post(f"/api/jobs/{job_id}/upload", params={"file_name": "other.gcode"},
                       content=b"G1 X0\n", headers=headers).status_code == 422
    monkeypatch.setattr("app.jobs.printer_status", lambda row: {"state": "standby", "filename": ""})
    uploaded = []
    monkeypatch.setattr("app.jobs.upload_controller_file",
                        lambda row, name, body: uploaded.append((name,body)) or 201)
    result = client.post(f"/api/jobs/{job_id}/upload", params=query, content=b"; GCODE\nG1 X0\n", headers=headers)
    assert result.status_code == 200, result.text
    assert uploaded == [("part.gcode", b"; GCODE\nG1 X0\n")]
    assert client.get("/api/jobs").json()[0]["status"] == "pending"
    monkeypatch.setattr("app.jobs.printer_status", lambda row: {"state": "printing", "filename": "part.gcode"})
    assert client.post(f"/api/jobs/{job_id}/upload", params=query,
                       content=b"G1 X0\n", headers=headers).status_code == 409


def test_start_requires_idle_and_never_marks_observed_printing(workspace, monkeypatch):
    client, path, printer, s0, s1 = workspace
    job_id = client.post("/api/jobs", json={
        "printer_id": printer, "spool_id": s0, "file_name": "part.gcode", "estimated_g": 20,
    }).json()["id"]
    monkeypatch.setenv("FILAMENT_PRINTER_CONTROL_ENABLED", "1")
    monkeypatch.setattr("app.jobs.printer_status", lambda row: {"state": "printing", "filename": "part.gcode"})
    assert client.post(f"/api/jobs/{job_id}/start").status_code == 409
    issued = []
    monkeypatch.setattr("app.jobs.printer_status", lambda row: {"state": "standby", "filename": ""})
    monkeypatch.setattr("app.jobs.write_controller", lambda row, route, **kwargs: issued.append(route) or 200)
    response = client.post(f"/api/jobs/{job_id}/start")
    assert response.status_code == 200, response.text
    assert issued == ["/printer/print/start?filename=part.gcode"]
    job = client.get("/api/jobs").json()[0]
    assert job["status"] == "pending" and job["observed_printing"] == 0


def signature(secret, stamp, body):
    return hmac.new(secret.encode(), str(stamp).encode()+b"."+body, hashlib.sha256).hexdigest()


def test_cloud_signature_replay_and_conservative_review(workspace, monkeypatch):
    client, path, printer, s0, s1 = workspace
    job_id = client.post("/api/jobs", json={
        "printer_id": printer, "spool_id": s0, "file_name": "cloud.gcode", "estimated_g": 35
    }).json()["id"]
    monkeypatch.setenv("FILAMENT_CLOUD_HMAC_FARM", "cloud-test-key-with-at-least-thirty-two-characters")
    data = {"event_id": "remote-run-0001", "job_id": job_id, "status": "completed"}
    body = json.dumps(data).encode()
    stamp = str(int(time.time()))
    route = "/api/cloud/hooks/FARM"
    assert client.post(route, content=body).status_code == 401
    headers = {"X-Filament-Timestamp": stamp, "X-Filament-Signature": signature(
        "cloud-test-key-with-at-least-thirty-two-characters", stamp, body)}
    assert client.post(route, content=body, headers=headers).json()["disposition"] == "needs_review"
    assert client.post(route, content=body, headers=headers).json()["duplicate"] is True
    altered = json.dumps({**data, "status": "cancelled"}).encode()
    assert client.post(route, content=altered, headers=headers).status_code == 401
    stale = str(int(time.time())-3600)
    assert client.post(route, content=body, headers={
        "X-Filament-Timestamp": stale,
        "X-Filament-Signature": signature("cloud-test-key-with-at-least-thirty-two-characters", stale, body)
    }).status_code == 401
    assert client.get("/api/jobs").json()[0]["status"] == "needs_review"
    assert {r["id"]: r["remaining_g"] for r in client.get("/api/spools").json()}[s0] == 1000
    assert len(client.get("/api/cloud/events").json()) == 1


def test_slicing_opt_in_profile_and_cli_argument_guards(workspace, monkeypatch, tmp_path):
    client, path, printer, s0, s1 = workspace
    source = b"solid cube\nfacet normal 0 0 1\nendsolid cube\n"
    query = {"profile": "approved"}
    headers = {"Content-Type": "application/octet-stream"}
    assert client.post("/api/slicing/slice", params=query, content=source, headers=headers).status_code == 403
    directory = tmp_path/"profiles"
    directory.mkdir()
    (directory/"approved.ini").write_text("nozzle_diameter = 0.4\n")
    binary = tmp_path/"prusa-slicer"
    binary.write_text("fake executable")
    binary.chmod(0o755)
    monkeypatch.setenv("FILAMENT_SLICER_ENABLED", "1")
    monkeypatch.setenv("FILAMENT_SLICER_PROFILES_DIR", str(directory))
    monkeypatch.setenv("FILAMENT_SLICER_EXECUTABLE", str(binary))
    assert client.get("/api/slicing/profiles").json() == {"enabled": True, "profiles": ["approved"]}
    assert client.post("/api/slicing/slice", params={"profile": "../evil"},
                       content=source, headers=headers).status_code == 422
    def fake_run(argv, **kwargs):
        assert "--load" in argv and "--output" in argv
        assert argv[argv.index("--load")+1] == str(directory/"approved.ini")
        assert kwargs["timeout"] == 60 and kwargs["env"].get("FILAMENT_BOOTSTRAP_TOKEN") is None
        assert kwargs["check"] is False and "shell" not in kwargs
        Path(argv[argv.index("--output")+1]).write_bytes(b"; filament used [g] = 22.4\nG1 E2\n")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("app.slicing.subprocess.run", fake_run)
    response = client.post("/api/slicing/slice", params=query, content=source, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["X-Estimated-Grams"] == "22"
    assert response.content.endswith(b"G1 E2\n")


def test_slicer_rejects_profile_postprocessing(workspace, monkeypatch, tmp_path):
    client, _, _, _, _ = workspace
    root = tmp_path / "profiles"
    root.mkdir()
    (root / "unsafe.ini").write_text("post_process = /bin/sh /tmp/command.sh\n")
    binary = tmp_path / "prusa-slicer"
    binary.write_text("fake")
    binary.chmod(0o755)
    monkeypatch.setenv("FILAMENT_SLICER_ENABLED", "1")
    monkeypatch.setenv("FILAMENT_SLICER_PROFILES_DIR", str(root))
    monkeypatch.setenv("FILAMENT_SLICER_EXECUTABLE", str(binary))
    response = client.post("/api/slicing/slice?profile=unsafe",
                           content=b"solid cube\nfacet normal 0 0 1\nendsolid cube\n",
                           headers={"Content-Type":"application/octet-stream"})
    assert response.status_code == 422
    assert "post-processing" in response.text
