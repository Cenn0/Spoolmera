"""Online backup snapshots remain consistent and are restricted to admins."""
import sqlite3
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_snapshot_contains_committed_inventory(tmp_path):
    path=tmp_path/"inventory.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        pid=client.post("/api/products",json={"brand":"Test","name":"PLA",
            "material":"PLA","color_name":"Black"}).json()["id"]
        client.post("/api/spools",json={"product_id":pid,"initial_g":1000})
        response=client.get("/api/admin/backup.sqlite3")
        assert response.status_code==200,response.text[:100] if response.status_code!=200 else ""
        out=tmp_path/"snapshot.sqlite3"
        out.write_bytes(response.content)
        with sqlite3.connect(out) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            assert db.execute("SELECT COUNT(*) FROM spools").fetchone()[0]==1
        assert not list(tmp_path.glob(".filament-snapshot-*"))


def test_unauthenticated_cannot_download_database(tmp_path):
    with TestClient(create_app(tmp_path/"db.sqlite3")) as client:
        assert client.get("/api/admin/backup.sqlite3").status_code==401
