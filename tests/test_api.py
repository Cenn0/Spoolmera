"""HTTP-level regression tests with isolated temporary SQLite databases."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "inventory.sqlite3")) as test_client:
        yield test_client


def create_product(client):
    response = client.post(
        "/api/products",
        json={
            "brand": "Bambu Lab", "name": "Basic", "material": "pla",
            "color_name": "Black", "color_hex": "#141414", "diameter_mm": 1.75,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_spool(client, **kwargs):
    product_id = kwargs.pop("product_id", None) or create_product(client)
    response = client.post(
        "/api/spools",
        json={"product_id": product_id, "initial_g": 1000, **kwargs},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_health_and_empty_overview(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    overview = client.get("/api/overview").json()
    assert overview["total_spools"] == 0
    assert overview["remaining_g"] == 0


def test_create_product_spool_and_initial_history(client):
    product_id = create_product(client)
    product = client.get("/api/products").json()[0]
    assert product["material"] == "PLA"
    assert product["id"] == product_id
    spool_id = create_spool(client, product_id=product_id, location="Shelf A")
    spool = client.get("/api/spools").json()[0]
    assert spool["id"] == spool_id
    assert spool["status"] == "sealed"
    assert spool["remaining_g"] == 1000
    assert spool["location"] == "Shelf A"
    movements = client.get(f"/api/spools/{spool_id}/movements").json()
    assert len(movements) == 1
    assert movements[0]["kind"] == "initial"
    assert movements[0]["remaining_after_g"] == 1000


def test_consumption_is_atomic_and_is_audited(client):
    spool_id = create_spool(client)
    response = client.post(f"/api/spools/{spool_id}/movements", json={
        "kind": "consume", "grams": 325, "note": "Print job",
    })
    assert response.status_code == 201
    assert response.json()["remaining_g"] == 675
    spool = client.get("/api/spools").json()[0]
    assert spool["status"] == "opened"
    assert spool["remaining_g"] == 675
    history = client.get(f"/api/spools/{spool_id}/movements").json()
    assert [item["kind"] for item in history] == ["consume", "initial"]
    assert history[0]["delta_g"] == -325


def test_insufficient_stock_cannot_modify_inventory_or_history(client):
    spool_id = create_spool(client, remaining_g=100)
    response = client.post(f"/api/spools/{spool_id}/movements", json={
        "kind": "consume", "grams": 101,
    })
    assert response.status_code == 409
    assert client.get("/api/spools").json()[0]["remaining_g"] == 100
    assert len(client.get(f"/api/spools/{spool_id}/movements").json()) == 1


def test_adjustment_requires_reason_and_respects_capacity(client):
    spool_id = create_spool(client, remaining_g=300)
    endpoint = f"/api/spools/{spool_id}/movements"
    assert client.post(endpoint, json={"kind": "adjust", "grams": 25}).status_code == 422
    assert client.post(endpoint, json={
        "kind": "adjust", "grams": 701, "note": "Incorrect weighing",
    }).status_code == 409
    result = client.post(endpoint, json={
        "kind": "adjust", "grams": -50, "note": "Reweighed",
    })
    assert result.status_code == 201
    assert result.json()["remaining_g"] == 250
    assert client.get("/api/spools").json()[0]["remaining_g"] == 250


def test_products_can_be_edited_without_losing_spools(client):
    product_id = create_product(client)
    create_spool(client, product_id=product_id)
    response = client.put(f"/api/products/{product_id}", json={
        "brand": "Bambu Lab", "name": "Matte", "material": "PLA",
        "color_name": "Gray", "color_hex": "#999999", "diameter_mm": 1.75,
    })
    assert response.status_code == 200
    spool = client.get("/api/spools").json()[0]
    assert spool["product_name"] == "Matte"
    assert spool["color_name"] == "Gray"


def test_archiving_removes_spool_from_active_stock_but_keeps_history(client):
    spool_id = create_spool(client)
    assert client.post(f"/api/spools/{spool_id}/archive").status_code == 200
    assert client.get("/api/spools").json() == []
    assert client.get("/api/overview").json()["remaining_g"] == 0
    assert len(client.get(f"/api/spools/{spool_id}/movements").json()) == 1
    assert client.post(f"/api/spools/{spool_id}/archive").status_code == 404


def test_reject_invalid_input_and_missing_references(client):
    product_id = create_product(client)
    assert client.post("/api/spools", json={
        "product_id": product_id, "initial_g": 1000, "remaining_g": 1001,
    }).status_code == 422
    assert client.post("/api/spools", json={
        "product_id": 100000, "initial_g": 1000,
    }).status_code == 404
    assert client.put("/api/products/99999", json={
        "brand": "X", "name": "Y", "material": "PLA",
        "color_name": "Z", "color_hex": "#AAZZZZ",
    }).status_code == 422
    assert client.patch("/api/spools/99999", json={"location": "Shelf"}).status_code == 404


def test_overview_counts_and_low_stock(client):
    product_id = create_product(client)
    create_spool(client, product_id=product_id, remaining_g=150)
    create_spool(client, product_id=product_id, remaining_g=0)
    create_spool(client, product_id=product_id)
    stats = client.get("/api/overview").json()
    assert stats["total_spools"] == 3
    assert stats["sealed_spools"] == 1
    assert stats["opened_spools"] == 1
    assert stats["empty_spools"] == 1
    assert stats["low_spools"] == 1
    assert stats["remaining_g"] == 1150


def test_static_frontend_is_served(client):
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "Filament Manager" in homepage.text
    assert client.get("/static/styles.css").status_code == 200
    javascript = client.get("/static/app.js")
    assert javascript.status_code == 200
    assert "openSpoolDialog" in javascript.text


def test_opened_spool_cannot_be_marked_as_sealed_after_consumption(client):
    spool_id = create_spool(client)
    assert client.post(f"/api/spools/{spool_id}/movements", json={
        "kind": "consume", "grams": 100,
    }).status_code == 201
    assert client.patch(f"/api/spools/{spool_id}", json={"opened": False}).status_code == 409
    assert client.get("/api/spools").json()[0]["status"] == "opened"


def test_spool_metadata_and_recent_movement_queries(client):
    spool_id = create_spool(client)
    assert client.patch(f"/api/spools/{spool_id}", json={
        "location": "Dry cabinet", "notes": "Keep dry", "opened": True,
    }).status_code == 200
    assert client.get("/api/spools").json()[0]["location"] == "Dry cabinet"
    assert len(client.get("/api/movements?limit=1").json()) == 1
    assert client.get("/api/movements?limit=201").status_code == 422
