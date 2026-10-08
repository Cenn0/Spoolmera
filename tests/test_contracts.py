"""Public response contracts, pagination and least-privilege inventory views."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate
from scripts.generate_api_types import generate, OUTPUT

def test_types_generated_from_pydantic_models():
    assert OUTPUT.read_text(encoding="utf-8") == generate()

def test_inventory_cursor_and_diagnostics(tmp_path):
    with TestClient(create_app(tmp_path/"contract.sqlite3")) as client:
        authenticate(client)
        product = client.post("/api/products", json={
            "brand":"Example","name":"PLA","material":"PLA","color_name":"Black"
        }).json()["id"]
        for _ in range(5):
            assert client.post("/api/spools", json={"product_id":product,"initial_g":1000}).status_code==201
        first = client.get("/api/inventory/v2/spools?limit=2").json()
        second = client.get(f'/api/inventory/v2/spools?limit=2&cursor={first["next_cursor"]}').json()
        third = client.get(f'/api/inventory/v2/spools?limit=2&cursor={second["next_cursor"]}').json()
        ids = [spool["id"] for page in (first,second,third) for spool in page["items"]]
        assert len(set(ids))==5
        assert len(ids)==5
        assert third["next_cursor"] is None
        assert client.get("/api/diagnostics").status_code==200
        assert client.get("/api/audit").status_code==200
