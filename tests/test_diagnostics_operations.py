"""Operational visibility separates scheduler health, device failures and human review."""
from fastapi.testclient import TestClient
from uuid import UUID

from app.database import session, utc_now
from app.main import create_app
from tests.support import authenticate


def test_diagnostics_reports_device_failure_without_leaking_endpoints(tmp_path):
    path = tmp_path / "database.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        printer = client.post("/api/printers", json={"name": "Workshop", "kind": "moonraker",
                                                     "base_url": "http://192.168.50.20:7125"}).json()["id"]
        with session(path, write=True) as db:
            db.execute("INSERT INTO printer_poll_state(printer_id,last_attempt_at,consecutive_failures,last_error) VALUES(?,?,3,'TimeoutError')",
                       (printer, utc_now()))
        response = client.get("/api/diagnostics")
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["version"] and value["schema_version"] >= 10
        assert value["poller"]["status"] == "running"
        assert UUID(value["poller"]["lease_owner"])
        assert value["status"] == "ok"
        assert value["printers"][0]["consecutive_failures"] == 3
        assert value["printers"][0]["freshness"] == "never"
        assert "192.168.50.20" not in response.text and "token_env" not in response.text
        assert value["backup"]["status"] == "never"
        assert client.get("/api/admin/backup.sqlite3").status_code == 200
        assert client.get("/api/diagnostics").json()["backup"]["status"] == "ready"
        assert client.get("/api/ready").status_code == 200


def test_machine_alerts_require_events_scope_and_deduplicate_conditions(tmp_path):
    with TestClient(create_app(tmp_path / "database.sqlite3")) as client:
        authenticate(client)
        product = client.post("/api/products", json={"brand": "Test", "name": "PLA", "material": "PLA", "color_name": "Black"}).json()["id"]
        client.post("/api/spools", json={"product_id": product, "initial_g": 1000, "remaining_g": 190})
        assert client.get("/api/automation/v1/alerts").status_code == 401
        read = client.post("/api/admin/automation-tokens", json={"label": "Inventory", "scope": "inventory_read"}).json()["token"]
        events = client.post("/api/admin/automation-tokens", json={"label": "Alerts", "scope": "events_read"}).json()["token"]
        assert client.get("/api/automation/v1/alerts", headers={"Authorization": "Bearer " + read}).status_code == 403
        response = client.get("/api/automation/v1/alerts", headers={"Authorization": "Bearer " + events})
        assert response.status_code == 200, response.text
        alerts = response.json()
        assert alerts["instance_epoch"] and not alerts["truncated"]
        assert len(alerts["alerts"]) == 1 and alerts["alerts"][0]["category"] == "low_stock"
