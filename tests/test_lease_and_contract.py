"""Scheduling and API-layer separation regressions."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.lease_service import acquire_lease, release_lease
from tests.support import authenticate

def test_lease_fences_parallel_pollers(tmp_path):
    from app.database import initialize_database
    path = tmp_path / "lease.sqlite3"
    initialize_database(path)
    assert acquire_lease(path, "poll", "one", ttl_seconds=120)
    assert not acquire_lease(path, "poll", "two", ttl_seconds=120)
    release_lease(path, "poll", "wrong")
    assert not acquire_lease(path, "poll", "two", ttl_seconds=120)
    release_lease(path, "poll", "one")
    assert acquire_lease(path, "poll", "two", ttl_seconds=120)

def test_inventory_routes_still_use_shared_domain_services(tmp_path):
    path = tmp_path / "data.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post("/api/products", json={"brand":"A","name":"PLA",
                          "material":"PLA","color_name":"Red"})
        assert product.status_code == 201, product.text
        spool = client.post("/api/spools", json={"product_id":product.json()["id"],"initial_g":400})
        assert spool.status_code == 201, spool.text
        assert client.get("/api/overview").json()["remaining_g"] == 400
        movement = client.post(f'/api/spools/{spool.json()["id"]}/movements',
                               json={"kind":"consume","grams":100})
        assert movement.status_code == 201, movement.text
        assert client.get("/api/overview").json()["remaining_g"] == 300
