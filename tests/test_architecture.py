"""Architecture invariants: durable commands, relay isolation, migrations and worker trust."""
import hmac
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import create_app
from app.database import initialize_database, session
from app.services.command_service import reserve_command, finalize_command, clear_command
from app.slicer_worker import create_worker_app
from scripts.backup import create_backup
from tests.support import authenticate
import pytest


def test_durable_start_command_prevents_replay(tmp_path):
    path = tmp_path / "command.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post("/api/products", json={
            "brand": "Example", "name": "PLA", "material": "PLA", "color_name": "Green"
        }).json()["id"]
        spool = client.post("/api/spools", json={"product_id":product,"initial_g":1000}).json()["id"]
        os.environ["FILAMENT_PRINTER_ALLOWED_IPS"] = "192.168.50.20"
        printer = client.post("/api/printers", json={
            "name":"Printer","kind":"moonraker","base_url":"http://192.168.50.20:7125"
        }).json()["id"]
        job = client.post("/api/jobs", json={"printer_id":printer,"spool_id":spool,
              "file_name":"part.gcode","estimated_g":10}).json()["id"]
        actor = client.get("/api/auth/me").json()["id"]
        first = reserve_command(path, printer, job, "start", actor)
        finalize_command(path, first, "unknown", detail="Timeout")
        with pytest.raises(Exception) as exc:
            reserve_command(path, printer, job, "start", actor)
        assert getattr(exc.value, "status_code", None) == 409
        clear_command(path, first, actor, "Confirmed physically not started.")
        second = reserve_command(path, printer, job, "start", actor)
        assert first != second


def test_snapshot_backup_and_future_version_guard(tmp_path):
    source = tmp_path/"source.sqlite3"
    initialize_database(source)
    with session(source, write=True) as db:
        db.execute("INSERT INTO products(uid,brand,name,material,color_name,color_hex,diameter_mm,notes,created_at,updated_at) VALUES('uuid','Brand','Name','PLA','Black','#000000',1.75,'','','')")
    target = tmp_path/"backup.sqlite3"
    create_backup(source, target)
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM products").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer"):
        initialize_database(source)


def test_isolated_worker_requires_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FILAMENT_SLICER_WORKER_TOKEN", "unique-test-worker-key-over-thirty-two-characters")
    monkeypatch.setenv("FILAMENT_SLICER_ENABLED", "1")
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles/"approved.ini").write_text("nozzle_diameter = 0.4")
    monkeypatch.setenv("FILAMENT_SLICER_PROFILES_DIR", str(profiles))
    with TestClient(create_worker_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/profiles").status_code == 401
        assert client.get("/profiles", headers={"X-Worker-Token": "wrong"}).status_code == 401
        assert client.get("/profiles", headers={"X-Worker-Token": os.environ["FILAMENT_SLICER_WORKER_TOKEN"]}).json() == {"profiles": ["approved"]}

def test_restart_recovers_unacknowledged_start_without_retry(tmp_path):
    """A crash between physical execution and response must not trigger replay."""
    path = tmp_path / "restart.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post("/api/products", json={
            "brand": "Example", "name": "PLA", "material": "PLA", "color_name": "Green"
        }).json()["id"]
        spool = client.post("/api/spools", json={"product_id": product, "initial_g": 1000}).json()["id"]
        printer = client.post("/api/printers", json={
            "name": "Printer", "kind": "moonraker", "base_url": "http://192.168.50.20:7125"
        }).json()["id"]
        job = client.post("/api/jobs", json={
            "printer_id":printer,"spool_id":spool,"file_name":"restart.gcode","estimated_g":10
        }).json()["id"]
        actor = client.get("/api/auth/me").json()["id"]
        intent = reserve_command(path, printer, job, "start", actor)
        with session(path) as db:
            assert db.execute("SELECT state FROM printer_commands WHERE id=?", (intent,)).fetchone()[0] == "sending"
    initialize_database(path)
    with session(path) as db:
        assert db.execute("SELECT state FROM printer_commands WHERE id=?", (intent,)).fetchone()[0] == "unknown"
    with pytest.raises(Exception) as exc:
        reserve_command(path, printer, job, "start", actor)
    assert getattr(exc.value, "status_code", None) == 409


def test_schema_upgrade_never_overwrites_existing_accounting_status(tmp_path):
    """Schema v5 must not rederive an independently set accounting state on restart."""
    path = tmp_path / "accounting.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post("/api/products", json={
            "brand": "Example", "name": "PLA", "material": "PLA", "color_name": "Green"
        }).json()["id"]
        spool = client.post("/api/spools", json={"product_id": product, "initial_g": 1000}).json()["id"]
        printer = client.post("/api/printers", json={
            "name": "Printer", "kind": "moonraker", "base_url": "http://192.168.50.20:7125"
        }).json()["id"]
        job = client.post("/api/jobs", json={
            "printer_id":printer,"spool_id":spool,"file_name":"accounting.gcode","estimated_g":10
        }).json()["id"]
        with session(path, write=True) as db:
            db.execute("UPDATE print_jobs SET accounting_status='needs_review' WHERE id=?", (job,))
    initialize_database(path)
    with session(path) as db:
        assert db.execute("SELECT accounting_status FROM print_jobs WHERE id=?", (job,)).fetchone()[0] == "needs_review"
