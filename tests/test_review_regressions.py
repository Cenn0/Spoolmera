"""Review regressions: authentication, controller contracts and stock accounting."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import time

import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE
from app.database import session
from app.jobs import apply_consumption, estimate_gcode
from app.main import create_app
from tests.support import authenticate, PASSWORD
from tests.test_security_jobs import make_inventory


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "review.sqlite3"
    application = create_app(path)
    with TestClient(application) as client:
        authenticate(client)
        spool_id = make_inventory(client)
        printer = {"name": "Review printer", "kind": "moonraker",
                   "base_url": "http://192.168.50.20:7125", "enabled": True}
        response = client.post("/api/printers", json=printer)
        assert response.status_code == 201, response.text
        yield client, application, path, spool_id, response.json()["id"], printer


def register(client, spool, printer, filename="fixture.gcode", grams=125):
    response = client.post("/api/jobs", json={"spool_id": spool, "printer_id": printer,
                           "file_name": filename, "estimated_g": grams})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def remote_run(monkeypatch, runs):
    def fetch(printer, route):
        if route.startswith("/server/history/list"):
            return {"result": {"jobs": runs}}
        return {"result": {"status": {"print_stats": {"state": "printing", "filename": "fixture.gcode"}}}}
    monkeypatch.setattr("app.printers.fetch_json", fetch)


def test_password_reset_preserves_spaces(workspace):
    client, application, _, _, _, _ = workspace
    response = client.post("/api/auth/users", json={"username": "space-user",
                           "password": "initial-password-2026", "role": "viewer"})
    user_id = response.json()["id"]
    secret = "  replacement-password-2026  "
    assert client.patch(f"/api/auth/users/{user_id}", json={"password": secret}).status_code == 200
    with closing(TestClient(application)) as other:
        assert other.post("/api/auth/login", json={"username": " space-user ", "password": secret}).status_code == 200
        assert other.post("/api/auth/login", json={"username": "space-user", "password": secret.strip()}).status_code == 401


def test_self_password_change_revokes_other_sessions(workspace):
    client, application, _, _, _, _ = workspace
    with closing(TestClient(application)) as other:
        login = other.post("/api/auth/login", json={"username": "testadmin", "password": PASSWORD})
        assert login.status_code == 200
        previous = client.cookies.get(COOKIE)
        changed = client.post("/api/auth/password", json={"old_password": PASSWORD,
                              "new_password": "  changed-password-2026  "})
        assert changed.status_code == 200
        assert client.cookies.get(COOKIE) != previous
        assert other.get("/api/auth/me").status_code == 401
        assert other.post("/api/auth/login", json={"username": "testadmin",
                          "password": "  changed-password-2026  "}).status_code == 200
        assert client.post("/api/auth/logout").status_code == 403  # previous CSRF token
        client.headers["X-CSRF-Token"] = changed.json()["csrf_token"]
        assert client.post("/api/auth/logout").status_code == 200


def test_expired_session_is_rejected(workspace):
    client, _, path, _, _, _ = workspace
    with session(path, write=True) as db:
        db.execute("UPDATE auth_sessions SET expires_at=?", (int(time.time()) - 1,))
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/export/inventory.csv").status_code == 401


@pytest.mark.parametrize("header", ["X-CSRF-Token", "X-Bootstrap-Token"])
def test_non_ascii_security_headers_fail_closed(workspace, header):
    client, _, _, _, _, _ = workspace
    route = "/api/auth/logout" if header == "X-CSRF-Token" else "/api/auth/setup"
    response = client.post(route, json={"username": "other", "password": PASSWORD},
                           headers={header.encode(): b"\xc3\xa4"})
    assert response.status_code == 403


@pytest.mark.parametrize("changes", [{"role": "viewer"}, {"enabled": False}])
def test_last_admin_cannot_be_removed(workspace, changes):
    client, _, _, _, _, _ = workspace
    assert client.patch("/api/auth/users/1", json=changes).status_code == 409
    assert client.get("/api/auth/me").json()["role"] == "admin"


def test_role_change_revokes_existing_access(workspace):
    client, application, _, _, _, _ = workspace
    user = client.post("/api/auth/users", json={"username": "editor", "password": PASSWORD, "role": "editor"})
    with closing(TestClient(application)) as other:
        assert other.post("/api/auth/login", json={"username": "editor", "password": PASSWORD}).status_code == 200
        assert client.patch(f"/api/auth/users/{user.json()['id']}", json={"role": "viewer"}).status_code == 200
        assert other.get("/api/jobs").status_code == 401


def test_duplicate_printer_update_returns_conflict(workspace):
    client, _, _, _, printer_id, printer = workspace
    assert client.post("/api/printers", json={**printer, "name": "Other"}).status_code == 201
    response = client.put(f"/api/printers/{printer_id}", json={**printer, "name": "Other"})
    assert response.status_code == 409
    assert client.get("/api/printers").json()[1]["name"] == "Review printer"


@pytest.mark.parametrize("route,data", [
    ("probe", {"result": None}),
    ("probe", {"result": {"status": []}}),
    ("probe", {"result": {"status": {"print_stats": {"state": []}}}}),
    ("poll", {"result": None}),
])
def test_malformed_moonraker_returns_gateway_error(workspace, monkeypatch, route, data):
    client, _, _, _, printer_id, _ = workspace
    monkeypatch.setattr("app.printers.fetch_json", lambda *args: data)
    assert client.post(f"/api/printers/{printer_id}/{route}").status_code == 502


@pytest.mark.parametrize("data", [{"job": []}, {"job": {"file": []}}, {"state": []}])
def test_malformed_octoprint_returns_gateway_error(workspace, monkeypatch, data):
    client, _, _, _, printer_id, printer = workspace
    monkeypatch.setenv("FILAMENT_PRINTER_TOKEN_TEST", "test-secret")
    changed = {**printer, "kind": "octoprint", "token_env": "FILAMENT_PRINTER_TOKEN_TEST"}
    assert client.put(f"/api/printers/{printer_id}", json=changed).status_code == 200
    monkeypatch.setattr("app.printers.fetch_json", lambda *args: data)
    assert client.post(f"/api/printers/{printer_id}/probe").status_code == 502


def test_unobserved_completed_run_identity_is_retained(workspace, monkeypatch):
    client, _, _, spool, printer, _ = workspace
    first = register(client, spool, printer)
    run = {"job_id": "completed-run", "filename": "fixture.gcode",
           "start_time": time.time() + 5, "status": "completed"}
    remote_run(monkeypatch, [run])
    assert client.post(f"/api/printers/{printer}/poll").status_code == 200
    assert client.get("/api/jobs").json()[0]["external_job_id"] == "completed-run"
    assert client.post(f"/api/jobs/{first}/resolve", json={"action": "debit"}).status_code == 200
    second = register(client, spool, printer)
    assert client.post(f"/api/printers/{printer}/poll").status_code == 200
    assert client.get("/api/jobs").json()[0]["id"] == second
    assert client.get("/api/jobs").json()[0]["status"] == "pending"
    assert client.get("/api/spools").json()[0]["remaining_g"] == 875


def test_ambiguous_history_does_not_choose_latest_run(workspace, monkeypatch):
    client, _, _, spool, printer, _ = workspace
    register(client, spool, printer)
    runs = [{"job_id": identifier, "filename": "fixture.gcode", "start_time": time.time() + offset,
             "status": "in_progress"} for identifier, offset in [("run-a", 5), ("run-b", 10)]]
    remote_run(monkeypatch, runs)
    assert client.post(f"/api/printers/{printer}/poll").status_code == 200
    job = client.get("/api/jobs").json()[0]
    assert job["status"] == "needs_review"
    assert job["external_job_id"] is None
    assert client.get("/api/spools").json()[0]["remaining_g"] == 1000


def test_cancelled_run_preserves_identity_and_stock(workspace, monkeypatch):
    client, _, _, spool, printer, _ = workspace
    register(client, spool, printer)
    run = {"job_id": "cancelled-run", "filename": "fixture.gcode",
           "start_time": time.time() + 5, "status": "in_progress"}
    remote_run(monkeypatch, [run])
    client.post(f"/api/printers/{printer}/poll")
    run["status"] = "cancelled"
    client.post(f"/api/printers/{printer}/poll")
    job = client.get("/api/jobs").json()[0]
    assert job["status"] == "needs_review"
    assert job["external_job_id"] == "cancelled-run"
    assert client.get("/api/spools").json()[0]["remaining_g"] == 1000


def test_concurrent_debit_records_exactly_one_movement(workspace):
    client, _, path, spool, printer, _ = workspace
    job_id = register(client, spool, printer)
    with session(path, write=True) as db:
        db.execute("UPDATE print_jobs SET status='needs_review' WHERE id=?", (job_id,))
    def debit(_):
        with session(path, write=True) as db:
            return apply_consumption(db, {"id": job_id}, 1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(debit, range(8)))
    assert results.count(True) == 1
    assert client.get("/api/spools").json()[0]["remaining_g"] == 875
    assert len(client.get(f"/api/spools/{spool}/movements").json()) == 2


def test_competing_jobs_cannot_overdraw_stock(workspace):
    client, _, path, spool, printer, _ = workspace
    ids = [register(client, spool, printer, name, 600) for name in ["one.gcode", "two.gcode"]]
    with session(path, write=True) as db:
        db.execute("UPDATE print_jobs SET status='needs_review'")
    assert client.post(f"/api/jobs/{ids[0]}/resolve", json={"action": "debit"}).status_code == 200
    assert client.post(f"/api/jobs/{ids[1]}/resolve", json={"action": "debit"}).status_code == 409
    assert client.get("/api/spools").json()[0]["remaining_g"] == 400
    assert len(client.get(f"/api/spools/{spool}/movements").json()) == 2


@pytest.mark.parametrize("content,amount", [(b"; filament used [g] = 25.1\n", 25),
    (b"; filament used [g] = 10\n; filament_weight_g: 20\n", None),
    (b"; filament used [g] = 10, 20\n", None), (b"G1 E999\n", None),
    (b"; filament_weight_g: 0\n", None)])
def test_gcode_weight_contract(content, amount):
    assert estimate_gcode(content) == amount


@pytest.mark.parametrize("filename", ["../fixture.gcode", "/fixture.gcode", "folder//fixture.gcode", "fixture.exe"])
def test_job_import_rejects_unsafe_names(workspace, filename):
    client, _, _, spool, printer, _ = workspace
    response = client.post("/api/jobs/import", params={"printer_id": printer, "spool_id": spool,
                           "file_name": filename}, content=b"; filament_weight_g: 25\n",
                           headers={"Content-Type": "text/plain"})
    assert response.status_code == 422
    assert client.get("/api/jobs").json() == []


def test_gcode_import_limits_and_manual_override(workspace, monkeypatch):
    client, _, _, spool, printer, _ = workspace
    params = {"printer_id": printer, "spool_id": spool, "file_name": "fixture.gcode"}
    headers = {"Content-Type": "text/plain"}
    assert client.post("/api/jobs/import", params=params, content=b"", headers=headers).status_code == 422
    assert client.post("/api/jobs/import", params=params, content=b"G1 E2\n", headers=headers).status_code == 422
    assert client.post("/api/jobs/import", params=params, content=b"G1 E2\n",
                       headers={"Content-Type": "application/json"}).status_code == 415
    monkeypatch.setattr("app.jobs.MAX_GCODE", 20)
    assert client.post("/api/jobs/import", params=params, content=b"x" * 21, headers=headers).status_code == 413
    response = client.post("/api/jobs/import", params={**params, "estimated_g": 25},
                           content=b"G1 E2\n", headers=headers)
    assert response.status_code == 201
    assert response.json()["weight_source"] == "manual"


def test_octoprint_matches_relative_file_path(workspace, monkeypatch):
    client, _, _, spool, printer_id, printer = workspace
    monkeypatch.setenv("FILAMENT_PRINTER_TOKEN_TEST", "secret")
    assert client.put(f"/api/printers/{printer_id}", json={**printer, "kind": "octoprint",
                      "token_env": "FILAMENT_PRINTER_TOKEN_TEST"}).status_code == 200
    register(client, spool, printer_id, "folder/fixture.gcode")
    state = {"state": "Printing", "job": {"file": {"name": "fixture.gcode", "path": "folder/fixture.gcode"}}}
    monkeypatch.setattr("app.printers.fetch_json", lambda *args: state)
    assert client.post(f"/api/printers/{printer_id}/poll").status_code == 200
    assert client.get("/api/jobs").json()[0]["status"] == "printing"
    state["state"] = "Operational"
    client.post(f"/api/printers/{printer_id}/poll")
    assert client.get("/api/jobs").json()[0]["status"] == "needs_review"
    assert client.get("/api/spools").json()[0]["remaining_g"] == 1000


@pytest.mark.parametrize("changes", [{"job_id": None}, {"start_time": float("nan")},
                                    {"start_time": float("inf")}, {"status": []}])
def test_invalid_history_cannot_change_stock(workspace, monkeypatch, changes):
    client, _, _, spool, printer_id, _ = workspace
    register(client, spool, printer_id)
    run = {"job_id": "run", "filename": "fixture.gcode", "start_time": time.time() + 5,
           "status": "in_progress", **changes}
    remote_run(monkeypatch, [run])
    assert client.post(f"/api/printers/{printer_id}/poll").status_code == 502
    assert client.get("/api/jobs").json()[0]["status"] == "pending"
    assert client.get("/api/spools").json()[0]["remaining_g"] == 1000


def test_angular_deep_links_do_not_mask_missing_api_or_assets(tmp_path, monkeypatch):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<fm-root>fixture</fm-root>", encoding="utf-8")
    monkeypatch.setattr("app.main.UI_DIR", ui)
    with TestClient(create_app(tmp_path / "spa.sqlite3")) as client:
        for path in ["/", "/jobs", "/account", "/spools"]:
            response = client.get(path)
            assert response.status_code == 200
            assert "fm-root" in response.text
            assert response.headers["Cache-Control"] == "no-store"
        assert client.get("/missing.js").status_code == 404
        assert client.get("/api/missing").status_code == 401
        authenticate(client)
        assert client.get("/api/missing").status_code == 404
        assert client.get("/labels/missing").status_code == 404


def test_test_launcher_never_replaces_existing_credentials(tmp_path):
    from scripts.start_test import ensure_test_env
    path = ensure_test_env(tmp_path)
    content = path.read_text()
    assert content.startswith("FILAMENT_BOOTSTRAP_TOKEN=")
    assert len(content.strip().split("=", 1)[1]) >= 32
    path.write_text("FILAMENT_BOOTSTRAP_TOKEN=existing-operator-secret\n")
    assert ensure_test_env(tmp_path).read_text() == "FILAMENT_BOOTSTRAP_TOKEN=existing-operator-secret\n"
