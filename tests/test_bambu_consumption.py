"""Bambu task-correlated usage: controller mocks, real HTTP and SQLite ledger.

No physical printer is connected. Firmware can change telemetry semantics;
automatic accounting remains an explicit per-job opt-in.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import initialize_database, session
from app.main import create_app
from tests.support import authenticate
from tests.test_bambu_lan import configured
from tests.test_security_jobs import make_inventory


@pytest.fixture
def workshop(tmp_path, monkeypatch):
    definition = configured(monkeypatch)
    path = tmp_path / "bambu-consumption.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        response = client.post("/api/printers", json=definition)
        assert response.status_code == 201, response.text
        printer_id = response.json()["id"]
        a, b = make_inventory(client), make_inventory(client)
        yield client, path, printer_id, a, b


def register(client, printer_id, spool_ids, *, auto=True, name="part.3mf"):
    response = client.post("/api/jobs/multi", json={
        "printer_id": printer_id, "file_name": name,
        "auto_account_bambu": auto, "note": "User-provided print note",
        "materials": [
            {"tool": 0, "spool_id": spool_ids[0], "estimated_g": 120},
            {"tool": 1, "spool_id": spool_ids[1], "estimated_g": 80},
        ],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def sensor(monkeypatch, **changes):
    state = {"state": "printing", "filename": "part.3mf", "task_id": "4812",
             "progress_percent": 38, "layer_num": 40, "total_layer_num": 100}
    state.update(changes)
    monkeypatch.setattr("app.jobs.printer_status", lambda _: dict(state))
    return state


def poll(client, printer_id):
    response = client.post(f"/api/printers/{printer_id}/poll")
    assert response.status_code == 200, response.text
    return response.json()


def job(client, job_id):
    return next(row for row in client.get("/api/jobs").json() if row["id"] == job_id)


def balances(client):
    return {item["id"]: item["remaining_g"] for item in client.get("/api/spools").json()}


def test_opt_in_multimaterial_debits_once_for_same_observed_task(workshop, monkeypatch):
    client, path, printer_id, a, b = workshop
    job_id = register(client, printer_id, (a, b))
    state = sensor(monkeypatch)
    poll(client, printer_id)
    active = job(client, job_id)
    assert active["status"] == "printing"
    assert active["external_job_id"] == "bambu:4812"
    assert active["auto_account_bambu"] is True
    assert active["last_progress_percent"] == 38
    assert active["last_layer_num"] == 40
    assert balances(client) == {a: 1000, b: 1000}

    state.update(state="paused", progress_percent=37, layer_num=39)
    poll(client, printer_id)
    assert job(client, job_id)["last_progress_percent"] == 38
    assert job(client, job_id)["last_layer_num"] == 40

    # FINISH only counts when the exact task/filename was previously seen active.
    state.update(state="complete", progress_percent=100, layer_num=100)
    assert poll(client, printer_id)["updated_jobs"] == 1
    completed = job(client, job_id)
    assert completed["status"] == "completed"
    assert completed["accounting_status"] == "debited"
    assert completed["accounting_method"] == "estimated"
    assert completed["note"] == "User-provided print note"
    assert balances(client) == {a: 880, b: 920}
    with session(path) as db:
        operations = db.execute("SELECT mode, reason FROM accounting_operations WHERE job_id=?", (job_id,)).fetchall()
        assert len(operations) == 1
        assert operations[0]["mode"] == "estimated" and "not measured" in operations[0]["reason"]
        assert db.execute("SELECT COUNT(*) FROM movements WHERE print_job_id=?", (job_id,)).fetchone()[0] == 2
        assert db.execute("SELECT state FROM print_runs WHERE printer_id=? AND external_run_id=?",
                          (printer_id, "bambu:4812")).fetchone()[0] == "completed"
    assert poll(client, printer_id)["updated_jobs"] == 0
    assert balances(client) == {a: 880, b: 920}
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM accounting_operations WHERE job_id=?", (job_id,)).fetchone()[0] == 1


@pytest.mark.parametrize(("opt_in", "task", "finish_task", "finish_file"), [
    (False, "4812", "4812", "part.3mf"),
    (True, None, None, "part.3mf"),
    (True, "4812", "other", "part.3mf"),
    (True, "4812", "4812", "other.3mf"),
])
def test_ambiguous_or_opted_out_run_stays_for_review(
    workshop, monkeypatch, opt_in, task, finish_task, finish_file
):
    client, path, printer_id, a, b = workshop
    job_id = register(client, printer_id, (a, b), auto=opt_in)
    state = sensor(monkeypatch, task_id=task)
    poll(client, printer_id)
    state.update(state="complete", task_id=finish_task, filename=finish_file)
    poll(client, printer_id)
    saved = job(client, job_id)
    assert saved["status"] == "needs_review"
    assert saved["accounting_status"] == "needs_review"
    assert saved["accounting_method"] is None
    assert saved["note"] == "User-provided print note"
    assert balances(client) == {a: 1000, b: 1000}
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM accounting_operations WHERE job_id=?", (job_id,)).fetchone()[0] == 0


def test_paused_only_and_midrun_task_identity_cannot_auto_debit(workshop, monkeypatch):
    client, _, printer_id, a, b = workshop
    # A paused snapshot cannot establish that the printer was actually running.
    first_id = register(client, printer_id, (a, b), name="part.3mf")
    state = sensor(monkeypatch, state="paused")
    poll(client, printer_id)
    assert job(client, first_id)["observed_printing"] == 0
    state.update(state="complete")
    poll(client, printer_id)
    assert job(client, first_id)["status"] == "pending"

    # A running observation with no task identity must not be retroactively
    # paired with an ID that appears only on a later poll.
    state.update(state="printing", task_id=None)
    poll(client, printer_id)
    assert job(client, first_id)["observed_printing"] == 1
    state.update(task_id="4812")
    poll(client, printer_id)
    assert job(client, first_id)["status"] == "needs_review"
    assert balances(client) == {a: 1000, b: 1000}


def test_failure_records_progress_for_manual_partial_review_without_debit(workshop, monkeypatch):
    client, path, printer_id, a, b = workshop
    job_id = register(client, printer_id, (a, b))
    state = sensor(monkeypatch, layer_num=25, total_layer_num=100)
    poll(client, printer_id)
    state.update(state="failed", layer_num=27)
    poll(client, printer_id)
    item = job(client, job_id)
    assert item["status"] == "needs_review"
    assert item["last_layer_num"] == 25
    assert item["total_layer_num"] == 100
    assert item["accounting_status"] == "needs_review"
    assert balances(client) == {a: 1000, b: 1000}
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM movements WHERE print_job_id=?", (job_id,)).fetchone()[0] == 0


def test_insufficient_spool_stock_keeps_ledger_atomic_and_reviewable(workshop, monkeypatch):
    client, path, printer_id, a, b = workshop
    job_id = register(client, printer_id, (a, b))
    state = sensor(monkeypatch)
    poll(client, printer_id)
    # The physical spool stock changed after the printer began printing.
    withdrawal = client.post(f"/api/spools/{b}/movements",
                             json={"kind": "consume", "grams": 950})
    assert withdrawal.status_code == 201, withdrawal.text
    state.update(state="complete")
    poll(client, printer_id)
    item = job(client, job_id)
    assert item["status"] == "needs_review"
    assert item["accounting_status"] == "needs_review"
    assert balances(client) == {a: 1000, b: 50}
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM movements WHERE print_job_id=?", (job_id,)).fetchone()[0] == 0


def test_unsupported_controller_and_existing_jobs_remain_opted_out(workshop, monkeypatch):
    client, path, printer_id, a, _ = workshop
    response = client.post("/api/printers", json={
        "name": "Moonraker", "kind": "moonraker",
        "base_url": "http://192.168.50.20:7125", "token_env": "", "enabled": True,
    })
    assert response.status_code == 201, response.text
    different = client.post("/api/jobs", json={
        "printer_id": response.json()["id"], "spool_id": a, "file_name": "part.gcode",
        "estimated_g": 42, "auto_account_bambu": True,
    })
    assert different.status_code == 422
    old = client.post("/api/jobs", json={
        "printer_id": printer_id, "spool_id": a, "file_name": "old.3mf",
        "estimated_g": 42,
    })
    assert old.status_code == 201, old.text
    assert job(client, old.json()["id"])["auto_account_bambu"] is False
    with session(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 12
    initialize_database(path)
    assert job(client, old.json()["id"])["auto_account_bambu"] is False
