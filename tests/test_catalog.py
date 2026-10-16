"""Catalog is explicitly opt-in and never writes local inventory automatically."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_catalog_requires_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("SPOOLMERA_CATALOG_ENABLED", raising=False)
    with TestClient(create_app(tmp_path / "catalog.sqlite3")) as client:
        authenticate(client)
        assert client.get("/api/catalog/brands").status_code == 503


def test_catalog_brand_validation_and_read_only_preview(tmp_path, monkeypatch):
    from app.api import catalog
    monkeypatch.setenv("SPOOLMERA_CATALOG_ENABLED", "1")
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


def test_catalog_navigation_validates_every_path_segment(tmp_path, monkeypatch):
    from app.api import catalog
    monkeypatch.setenv("SPOOLMERA_CATALOG_ENABLED", "1")
    paths=[]
    monkeypatch.setattr(catalog, "fetch_catalog_json", lambda path: paths.append(path) or {"ok":True})
    with TestClient(create_app(tmp_path / "catalog.sqlite3")) as client:
        authenticate(client)
        assert client.get("/api/catalog/brands/test/materials/PLA").status_code==200
        assert client.get("/api/catalog/brands/test/materials/PLA/filaments/basic").status_code==200
        assert client.get("/api/catalog/brands/test/materials/PLA/filaments/basic/variants/red").status_code==200
        assert paths==["test/materials/PLA/index.json",
                       "test/materials/PLA/filaments/basic/index.json",
                       "test/materials/PLA/filaments/basic/variants/red.json"]


def test_catalog_transport_uses_fixed_tls_origin_without_redirects(tmp_path, monkeypatch):
    from app.api import catalog
    from app import __version__
    monkeypatch.setenv("SPOOLMERA_CATALOG_ENABLED", "1")
    monkeypatch.setenv("SPOOLMERA_DB_PATH", str(tmp_path / "catalog.sqlite3"))
    calls = []

    class Response:
        status = 200
        headers = {"Content-Type": "application/json; charset=utf-8"}
        def read(self, size):
            assert size == catalog.LIMIT + 1
            return b'{"name":"Fixture"}'

    class Connection:
        def __init__(self, host, *, timeout):
            assert host == "api.openfilamentdatabase.org"
            assert timeout == 6
            calls.append(("open", host))
        def request(self, method, resource, *, headers):
            assert method == "GET"
            assert resource == "/api/v1/brands/fixture/index.json"
            assert headers["User-Agent"] == f"Spoolmera/{__version__}"
            calls.append(("request", resource))
        def getresponse(self):
            return Response()
        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(catalog.http.client, "HTTPSConnection", Connection)
    assert catalog.fetch_catalog_json("fixture/index.json") == {"name": "Fixture"}
    assert calls[-1] == ("close",)
    # A fresh valid local cache must not trigger another outbound request.
    assert catalog.fetch_catalog_json("fixture/index.json") == {"name": "Fixture"}
    assert calls.count(("open", "api.openfilamentdatabase.org")) == 1


def test_catalog_rejects_redirect_response_without_following(tmp_path, monkeypatch):
    from app.api import catalog
    from fastapi import HTTPException
    import pytest
    monkeypatch.setenv("SPOOLMERA_CATALOG_ENABLED", "1")
    monkeypatch.setenv("SPOOLMERA_DB_PATH", str(tmp_path / "catalog.sqlite3"))
    calls = []

    class Response:
        status = 302
        headers = {"Content-Type": "application/json", "Location": "http://other.invalid/"}
        def read(self, size):
            raise AssertionError("Redirect bodies must not be read.")

    class Connection:
        def __init__(self, host, *, timeout): pass
        def request(self, method, resource, *, headers): calls.append(resource)
        def getresponse(self): return Response()
        def close(self): calls.append("closed")

    monkeypatch.setattr(catalog.http.client, "HTTPSConnection", Connection)
    with pytest.raises(HTTPException) as error:
        catalog.fetch_catalog_json("fixture/index.json")
    assert error.value.status_code == 502
    assert calls == ["/api/v1/brands/fixture/index.json", "closed"]
