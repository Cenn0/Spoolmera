"""Regression tests for optional material properties, balances and care history."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate
from app.database import session, initialize_database


def client_for(tmp_path):
    client = TestClient(create_app(tmp_path / "materials.sqlite3"))
    client.__enter__()
    authenticate(client)
    return client


def register(client, threshold=200):
    p = client.post("/api/products", json={
        "brand": "Example", "name": "PETG", "material": "petg",
        "color_name": "Blue", "density_g_cm3": 1.27,
        "low_stock_threshold_g": threshold, "nozzle_min_c": 220,
        "nozzle_max_c": 250, "gtin": "1234567890123"
    })
    assert p.status_code == 201, p.text
    s = client.post("/api/spools", json={
        "product_id": p.json()["id"], "initial_g": 1000,
        "remaining_g": 400, "tare_g": 225, "batch": "A23",
        "purchase_price_cents": 1999,
    })
    assert s.status_code == 201, s.text
    return p.json()["id"], s.json()["id"]


def test_material_fields_persist_and_alert_threshold(tmp_path):
    with client_for(tmp_path) as client:
        pid, sid = register(client, 450)
        p = client.get("/api/products").json()[0]
        s = client.get("/api/spools").json()[0]
        assert p["density_g_cm3"] == 1.27 and p["nozzle_max_c"] == 250
        assert s["tare_g"] == 225 and s["batch"] == "A23"
        assert s["purchase_price_cents"] == 1999
        assert client.get("/api/overview").json()["low_spools"] == 1
        assert client.get("/api/inventory/alerts").json()[0]["spool_id"] == sid
        replacement = {"brand": "Example", "name": "PETG Plus",
            "material": "PETG", "color_name": "Blue",
            "low_stock_threshold_g": 100}
        assert client.put(f"/api/products/{pid}", json=replacement).status_code == 200
        assert client.get("/api/inventory/alerts").json() == []


def test_weighing_is_atomic_and_ledger_backed(tmp_path):
    with client_for(tmp_path) as client:
        _, sid = register(client)
        path = f"/api/spools/{sid}/weigh"
        assert client.post(path, json={"gross_g": 100, "tare_g": 225}).status_code == 422
        assert client.post(path, json={"gross_g": 1500, "tare_g": 225}).status_code == 409
        assert client.get("/api/spools").json()[0]["remaining_g"] == 400
        r = client.post(path, json={"gross_g": 575, "note": "Measured after print"})
        assert r.status_code == 200, r.text
        assert r.json() == {"remaining_g": 350, "tare_g": 225, "difference_g": -50}
        hist = client.get(f"/api/spools/{sid}/movements").json()
        assert hist[0]["kind"] == "adjust" and hist[0]["delta_g"] == -50
        assert client.post(path, json={"gross_g": 575}).json()["difference_g"] == 0
        assert len(client.get(f"/api/spools/{sid}/movements").json()) == 2


def test_drying_does_not_change_stock(tmp_path):
    with client_for(tmp_path) as client:
        _, sid = register(client)
        path = f"/api/spools/{sid}/drying"
        bad = client.post(path, json={"temperature_c": 50, "duration_minutes": 360,
                                       "dried_at": "2026-01-01"})
        assert bad.status_code == 422
        good = client.post(path, json={"temperature_c": 50, "duration_minutes": 360,
                                        "dried_at": "2026-01-01T12:00:00+00:00",
                                        "note": "Dry box test"})
        assert good.status_code == 201, good.text
        assert len(client.get(path).json()) == 1
        assert client.get("/api/spools").json()[0]["remaining_g"] == 400


def test_upgrade_preserves_existing_inventory(tmp_path):
    path = tmp_path / "upgrade.sqlite3"
    initialize_database(path)
    with session(path, write=True) as db:
        db.execute("UPDATE products SET notes=notes WHERE 1=0")
        db.execute("PRAGMA user_version = 5")
    initialize_database(path)
    with session(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert "tare_g" in [r["name"] for r in db.execute("PRAGMA table_info(spools)")]
