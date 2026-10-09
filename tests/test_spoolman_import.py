"""Idempotent, source-namespaced and transactional Spoolman snapshots."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def fixture(remaining=350):
    return {"spools":[{"id":15,"filament":{"id":4,"name":"Matte Blue",
        "material":"PLA","vendor":{"name":"Example Lab"},"weight":1000,
        "color_hex":"3244AC","density":1.24,"spool_weight":250},
        "remaining_weight":remaining,"location":"Shelf A","lot_nr":"ABC",
        "price":19.95}]}


def test_import_dry_run_and_commit_and_repeat(tmp_path):
    with TestClient(create_app(tmp_path/"spoolman.sqlite3")) as c:
        authenticate(c)
        url="/api/import/spoolman?source=workshop"
        preview=c.post(url,json=fixture())
        assert preview.status_code==200,preview.text
        assert preview.json()["spools_created"]==1
        assert c.get("/api/spools").json()==[]
        commit=c.post(url+"&dry_run=false",json=fixture())
        assert commit.status_code==200,commit.text
        assert commit.json()["products_created"]==1
        spool=c.get("/api/spools").json()[0]
        assert spool["remaining_g"]==350 and spool["tare_g"]==250
        assert spool["batch"]=="ABC"
        repeat=c.post(url+"&dry_run=false",json=fixture(800))
        assert repeat.json()["spools_skipped"]==1
        assert c.get("/api/spools").json()[0]["remaining_g"]==350
        movements=c.get(f'/api/spools/{spool["id"]}/movements').json()
        assert len(movements)==1 and movements[0]["kind"]=="initial"


def test_invalid_import_is_atomic_and_namespaced(tmp_path):
    with TestClient(create_app(tmp_path/"spoolman.sqlite3")) as c:
        authenticate(c)
        src=fixture()
        src["spools"].append({**src["spools"][0],"id":16,"remaining_weight":9999})
        assert c.post("/api/import/spoolman?dry_run=false",json=src).status_code==422
        assert c.get("/api/products").json()==[]
        assert c.get("/api/spools").json()==[]
        assert c.post("/api/import/spoolman?dry_run=false",json=fixture()).status_code==200
        assert c.post("/api/import/spoolman?source=second&dry_run=false",json=fixture()).status_code==200
        assert len(c.get("/api/spools").json())==2


def test_archived_snapshot_rows_not_imported(tmp_path):
    with TestClient(create_app(tmp_path/"spoolman.sqlite3")) as c:
        authenticate(c)
        source=fixture()
        source["spools"][0]["archived"]=True
        r=c.post("/api/import/spoolman?dry_run=false",json=source)
        assert r.status_code==200 and r.json()["archived_skipped"]==1
        assert c.get("/api/spools").json()==[]
