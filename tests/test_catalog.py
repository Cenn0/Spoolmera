"""Catalog is explicitly opt-in and never writes local inventory automatically."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_catalog_requires_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("FILAMENT_CATALOG_ENABLED", raising=False)
    with TestClient(create_app(tmp_path / "catalog.sqlite3")) as client:
        authenticate(client)
        assert client.get("/api/catalog/brands").status_code == 503


def test_catalog_brand_validation_and_read_only_preview(tmp_path, monkeypatch):
    from app.api import catalog
    monkeypatch.setenv("FILAMENT_CATALOG_ENABLED", "1")
    paths = []
    def fake(path):
        paths.append(path)
        return ({"brands": [{"name": "Test", "slug": "test"}, {"name": "bad", "slug": "../evil"}]}
                if path == "index.json" else {"name": "Test", "materials": []})
    monkeypatch.setattr(catalog, "fetch_catalog_json", fake)
    with TestClient(create_app(tmp_path / "catalog.sqlite3")) as client:
        authenticate(client)
        assert client.get("/api/catalog/brands").json()["brands"] == [{"name": "Test", "slug": "test"}]
        assert client.get("/api/catalog/brands/test").json()["name"] == "Test"
        assert client.get("/api/catalog/brands/%2e%2e").status_code in (404, 422)
        assert paths == ["index.json", "test/index.json"]
        assert client.get("/api/products").json() == []
