"""Independent regressions for physical operation ownership and accounting lifecycle.

Controller calls are substituted at the transport boundary. These tests prove
which requests the application dispatches, not how real firmware executes them.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import io
import json
from threading import Barrier, Event
import time
import urllib.error

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import initialize_database, session
from app.main import create_app
from app.printers import ControllerRejected
from app.services.command_service import reserve_command, reserve_upload
from tests.support import authenticate


@pytest.fixture
def workshop(tmp_path, monkeypatch):
    async def idle_poller(*_):
        await asyncio.Event().wait()
    monkeypatch.setattr("app.main.poll_worker", idle_poller)
    monkeypatch.setenv("SPOOLMERA_PRINTER_CONTROL_ENABLED", "1")
    path = tmp_path / "coordination.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post("/api/products", json={"brand": "Workshop", "name": "PLA",
                                                     "material": "PLA", "color_name": "Blue"})
        assert product.status_code == 201, product.text
        spools = []
        for _ in range(2):
            result = client.post("/api/spools", json={"product_id": product.json()["id"], "initial_g": 1000})
            assert result.status_code == 201, result.text
            spools.append(result.json()["id"])
        printers = []
        for index in range(2):
            config = {"name": f"Coordinated printer {index}", "kind": "moonraker",
                      "base_url": f"http://192.168.50.{20 + index}:7125"}
            result = client.post("/api/printers", json=config)
            assert result.status_code == 201, result.text
            printers.append({"id": result.json()["id"], **config})
        yield {"client": client, "path": path, "spools": spools, "printers": printers}


def register(workshop, *, printer=0, filename="part.gcode", grams=100):
    result = workshop["client"].post("/api/jobs", json={
        "printer_id": workshop["printers"][printer]["id"], "spool_id": workshop["spools"][printer],
        "file_name": filename, "estimated_g": grams,
    })
    assert result.status_code == 201, result.text
    return result.json()["id"]


def start(workshop, job_id):
    return workshop["client"].post(f"/api/jobs/{job_id}/start")


def upload(workshop, job_id, filename="part.gcode"):
    return workshop["client"].post(f"/api/jobs/{job_id}/upload", params={"file_name": filename},
                                       content=b"G28\nG1 X1 Y2\n", headers={"Content-Type": "text/x.gcode"})


def rows(workshop, sql, params=()):
    with session(workshop["path"]) as db:
        return [dict(row) for row in db.execute(sql, params)]


def operations(workshop, printer=0):
    result = workshop["client"].get(f"/api/printers/{workshop['printers'][printer]['id']}/operations")
    assert result.status_code == 200, result.text
    return result.json()


def mock_idle(monkeypatch):
    monkeypatch.setattr("app.jobs.printer_status", lambda _: {"state": "standby", "filename": ""})


def running_job(workshop, monkeypatch):
    """Start, then independently observe the same identified Moonraker run."""
    job_id = register(workshop)
    mock_idle(monkeypatch)
    monkeypatch.setattr("app.jobs.write_controller", lambda *_args, **_kwargs: 200)
    result = start(workshop, job_id)
    assert result.status_code == 200, result.text
    command_id = result.json()["command_id"]
    remote = {"job_id": "coordinated-run", "filename": "part.gcode",
              "start_time": time.time() + 2, "status": "in_progress"}
    monkeypatch.setattr("app.jobs.moonraker_history", lambda _: [dict(remote)])
    monkeypatch.setattr("app.jobs.moonraker_job", lambda *_: dict(remote))
    monkeypatch.setattr("app.jobs.printer_status", lambda _: {
        "state": "printing" if remote["status"] == "in_progress" else "complete", "filename": "part.gcode"})
    result = workshop["client"].post(f"/api/printers/{workshop['printers'][0]['id']}/poll")
    assert result.status_code == 200, result.text
    assert rows(workshop, "SELECT state FROM printer_commands WHERE id=?", (command_id,))[0]["state"] == "confirmed"
    return job_id, command_id, remote


def test_two_jobs_on_same_printer_dispatch_only_one_start(workshop, monkeypatch):
    first = register(workshop, filename="first.gcode")
    second = register(workshop, filename="second.gcode")
    simultaneous_preflight = Barrier(2, timeout=5)
    dispatched = []
    def state(_):
        simultaneous_preflight.wait()
        return {"state": "standby", "filename": ""}
    def write(printer, route, **_):
        dispatched.append((printer["printer_id"], route))
        return 200
    monkeypatch.setattr("app.jobs.printer_status", state)
    monkeypatch.setattr("app.jobs.write_controller", write)
    with ThreadPoolExecutor(max_workers=2) as workers:
        replies = list(workers.map(lambda jid: start(workshop, jid), [first, second]))
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    assert len(dispatched) == 1
    assert len(operations(workshop)) == 1
    assert len(rows(workshop, "SELECT id FROM printer_commands WHERE action='start'")) == 1


def test_different_printers_can_dispatch_in_parallel(workshop, monkeypatch):
    first = register(workshop, printer=0)
    second = register(workshop, printer=1)
    both_transports = Barrier(2, timeout=5)
    dispatched = []
    mock_idle(monkeypatch)
    def write(printer, _route, **_):
        dispatched.append(printer["printer_id"])
        both_transports.wait()
        return 200
    monkeypatch.setattr("app.jobs.write_controller", write)
    with ThreadPoolExecutor(max_workers=2) as workers:
        replies = list(workers.map(lambda jid: start(workshop, jid), [first, second]))
    assert [reply.status_code for reply in replies] == [200, 200]
    assert set(dispatched) == {item["id"] for item in workshop["printers"]}
    assert len(operations(workshop, 0)) == len(operations(workshop, 1)) == 1


@pytest.mark.parametrize("interruption", ["before_dispatch", "lost_response"])
def test_unknown_start_survives_restart_and_needs_explicit_physical_clear(workshop, monkeypatch, interruption):
    first = register(workshop, filename="first.gcode")
    second = register(workshop, filename="second.gcode")
    printer_id = workshop["printers"][0]["id"]
    mock_idle(monkeypatch)
    dispatched = []
    def lost_reply(*_args, **_kwargs):
        dispatched.append("start")
        raise ValueError("Connection ended before the response arrived.")
    monkeypatch.setattr("app.jobs.write_controller", lost_reply)
    if interruption == "before_dispatch":
        command_id = reserve_command(workshop["path"], printer_id, first, "start", 1)
    else:
        assert start(workshop, first).status_code == 502
        command_id = rows(workshop, "SELECT id FROM printer_commands WHERE job_id=?", (first,))[0]["id"]
    before_restart = len(dispatched)
    initialize_database(workshop["path"])
    command = rows(workshop, "SELECT * FROM printer_commands WHERE id=?", (command_id,))[0]
    assert command["state"] == "unknown"
    assert operations(workshop)[0]["state"] == "unknown"
    assert start(workshop, second).status_code == 409
    assert len(dispatched) == before_restart  # Recovery never sends a hardware request.
    cleared = workshop["client"].post(f"/api/printers/commands/{command_id}/clear",
        json={"reason": "Verified the physical printer is idle and the previous start is resolved."})
    assert cleared.status_code == 200, cleared.text
    assert operations(workshop) == []
    monkeypatch.setattr("app.jobs.write_controller", lambda *_args, **_kwargs: 200)
    assert start(workshop, second).status_code == 200


def test_verified_completion_releases_printer_but_retains_command_and_consumption_history(workshop, monkeypatch):
    first, command_id, remote = running_job(workshop, monkeypatch)
    second = register(workshop, filename="second.gcode")
    assert len(operations(workshop)) == 1
    remote["status"] = "completed"
    result = workshop["client"].post(f"/api/printers/{workshop['printers'][0]['id']}/poll")
    assert result.status_code == 200, result.text
    command = rows(workshop, "SELECT * FROM printer_commands WHERE id=?", (command_id,))[0]
    assert command["state"] == "confirmed" and command["released_at"]
    assert operations(workshop) == []
    assert rows(workshop, "SELECT status,accounting_status FROM print_jobs WHERE id=?", (first,)) == [
        {"status": "completed", "accounting_status": "debited"}]
    assert rows(workshop, "SELECT delta_g FROM movements WHERE print_job_id=?", (first,)) == [{"delta_g": -100}]
    assert start(workshop, second).status_code == 200


@pytest.mark.parametrize("change", ["consumed", "archived", "mapping_mismatch"])
def test_start_checks_current_material_and_mapping_before_dispatch(workshop, monkeypatch, change):
    job_id = register(workshop, grams=900)
    client, sid = workshop["client"], workshop["spools"][0]
    if change == "consumed":
        assert client.post(f"/api/spools/{sid}/movements", json={"kind": "consume", "grams": 900}).status_code == 201
    elif change == "archived":
        assert client.post(f"/api/spools/{sid}/archive").status_code == 200
    else:
        # A historical mapping discrepancy must be reviewed, not silently started.
        with session(workshop["path"], write=True) as db:
            db.execute("UPDATE job_materials SET estimated_g=50 WHERE job_id=?", (job_id,))
    mock_idle(monkeypatch)
    dispatched = []
    monkeypatch.setattr("app.jobs.write_controller", lambda *_args, **_kwargs: dispatched.append(True) or 200)
    result = start(workshop, job_id)
    assert result.status_code == 409, result.text
    assert dispatched == [] and operations(workshop) == []


def test_disable_during_preflight_is_rechecked_before_start(workshop, monkeypatch):
    job_id = register(workshop)
    pid = workshop["printers"][0]["id"]
    dispatched = []
    def state(_):
        with session(workshop["path"], write=True) as db:
            db.execute("UPDATE printers SET enabled=0 WHERE id=?", (pid,))
        return {"state": "standby", "filename": ""}
    monkeypatch.setattr("app.jobs.printer_status", state)
    monkeypatch.setattr("app.jobs.write_controller", lambda *_args, **_kwargs: dispatched.append(True) or 200)
    assert start(workshop, job_id).status_code == 409
    assert dispatched == [] and operations(workshop) == []


def test_upload_reservation_rechecks_enabled_printer(workshop):
    job_id = register(workshop)
    pid = workshop["printers"][0]["id"]
    with session(workshop["path"], write=True) as db:
        db.execute("UPDATE printers SET enabled=0 WHERE id=?", (pid,))
    with pytest.raises(HTTPException) as failure:
        reserve_upload(workshop["path"], pid, job_id, 1)
    assert failure.value.status_code == 409
    assert operations(workshop) == []


@pytest.mark.parametrize("first_operation", ["upload", "start"])
def test_upload_and_start_cannot_dispatch_over_each_other(workshop, monkeypatch, first_operation):
    job_id = register(workshop)
    mock_idle(monkeypatch)
    entered, release = Event(), Event()
    dispatched = []
    def write(kind):
        def send(*_args, **_kwargs):
            dispatched.append(kind)
            if kind == first_operation:
                entered.set()
                assert release.wait(5), "Test did not release the substituted controller call."
            return 200
        return send
    monkeypatch.setattr("app.jobs.write_controller", write("start"))
    monkeypatch.setattr("app.jobs.upload_controller_file", write("upload"))
    first = upload if first_operation == "upload" else start
    second = start if first_operation == "upload" else upload
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(first, workshop, job_id)
        try:
            assert entered.wait(5), "First operation did not reach its transport."
            blocked = second(workshop, job_id)
            assert blocked.status_code == 409, blocked.text
            assert dispatched == [first_operation]
        finally:
            release.set()
        response = pending.result(timeout=5)
    assert response.status_code == 200, response.text
    if first_operation == "upload":
        assert operations(workshop) == []
        assert start(workshop, job_id).status_code == 200
    else:
        assert operations(workshop)[0]["kind"] == "start"
        assert upload(workshop, job_id).status_code == 409


def test_unknown_upload_survives_restart_and_explicit_clear_keeps_reason(workshop, monkeypatch):
    job_id = register(workshop)
    mock_idle(monkeypatch)
    def missing_upload_response(*_args, **_kwargs):
        raise ValueError("Upload response lost; remote outcome unknown.")
    monkeypatch.setattr("app.jobs.upload_controller_file", missing_upload_response)
    assert upload(workshop, job_id).status_code == 502
    operation = operations(workshop)[0]
    assert (operation["kind"], operation["state"]) == ("upload", "unknown")
    initialize_database(workshop["path"])
    dispatched = []
    monkeypatch.setattr("app.jobs.write_controller", lambda *_args, **_kwargs: dispatched.append(True) or 200)
    assert start(workshop, job_id).status_code == 409
    assert dispatched == []
    reason = "Verified file list and physical printer; no transfer remains active."
    result = workshop["client"].post(
        f"/api/printers/{operation['printer_id']}/operations/{operation['operation_id']}/clear", json={"reason": reason})
    assert result.status_code == 200, result.text
    assert operations(workshop) == []
    history = rows(workshop, "SELECT state,actor_id,detail FROM printer_operation_history WHERE operation_id=? ORDER BY id",
                   (operation["operation_id"],))
    assert [event["state"] for event in history] == ["sending", "unknown", "cleared"]
    assert history[-1]["actor_id"] == 1 and history[-1]["detail"] == reason
    assert start(workshop, job_id).status_code == 200


@pytest.mark.parametrize("status,expected_state", [(400, "rejected"), (401, "rejected"), (409, "rejected"), (500, "unknown")])
def test_http_rejection_and_uncertain_server_failure_have_different_retry_rules(workshop, monkeypatch, status, expected_state):
    job_id = register(workshop)
    next_job = register(workshop, filename="next.gcode")
    mock_idle(monkeypatch)
    class RejectingOpener:
        def open(self, request, timeout):
            assert request.method == "POST"
            raise urllib.error.HTTPError(request.full_url, status, "controller error", {},
                                         io.BytesIO(b"controller-secret-must-not-appear"))
    monkeypatch.setattr("app.printers.urllib.request.build_opener", lambda *_: RejectingOpener())
    result = start(workshop, job_id)
    assert result.status_code == 502
    assert "controller-secret" not in result.text
    command = rows(workshop, "SELECT * FROM printer_commands WHERE job_id=?", (job_id,))[0]
    assert command["state"] == expected_state
    monkeypatch.setattr("app.jobs.write_controller", lambda *_args, **_kwargs: 200)
    if expected_state == "rejected":
        assert command["http_status"] == status
        assert operations(workshop) == []
        assert start(workshop, next_job).status_code == 200
    else:
        assert operations(workshop)[0]["state"] == "unknown"
        assert start(workshop, next_job).status_code == 409


def test_explicit_upload_rejection_releases_operation_without_starting(workshop, monkeypatch):
    job_id = register(workshop)
    mock_idle(monkeypatch)
    def rejected(*_args, **_kwargs):
        raise ControllerRejected(409)
    monkeypatch.setattr("app.jobs.upload_controller_file", rejected)
    assert upload(workshop, job_id).status_code == 502
    assert operations(workshop) == []
    assert rows(workshop, "SELECT id FROM printer_commands") == []
    monkeypatch.setattr("app.jobs.upload_controller_file", lambda *_args, **_kwargs: 201)
    assert upload(workshop, job_id).status_code == 200


@pytest.mark.parametrize("origin", ["tracking", "controller"])
def test_cancel_keeps_confirmed_start_blocked_until_physical_check(workshop, monkeypatch, origin):
    job_id, command_id, _ = running_job(workshop, monkeypatch)
    next_job = register(workshop, filename="next.gcode")
    pid = workshop["printers"][0]["id"]
    if origin == "tracking":
        cancelled = workshop["client"].post(f"/api/jobs/{job_id}/cancel")
        expected_status = "cancelled"
    else:
        monkeypatch.setattr("app.printers.issue_control", lambda *_: 200)
        cancelled = workshop["client"].post(f"/api/printers/{pid}/control", json={"action": "cancel"})
        expected_status = "needs_review"
    assert cancelled.status_code == 200, cancelled.text
    assert rows(workshop, "SELECT status,accounting_status FROM print_jobs WHERE id=?", (job_id,)) == [
        {"status": expected_status, "accounting_status": "needs_review"}]
    mock_idle(monkeypatch)
    assert start(workshop, next_job).status_code == 409
    assert len(operations(workshop)) == 1
    cleared = workshop["client"].post(f"/api/printers/commands/{command_id}/clear", json={
        "reason": "Confirmed the physical printer is idle; partial consumption will be reviewed separately."})
    assert cleared.status_code == 200, cleared.text
    assert operations(workshop) == []
    assert rows(workshop, "SELECT status,accounting_status FROM print_jobs WHERE id=?", (job_id,)) == [
        {"status": expected_status, "accounting_status": "needs_review"}]
    assert start(workshop, next_job).status_code == 200


@pytest.mark.parametrize("operation_kind", ["start", "upload"])
def test_unresolved_operation_keeps_device_identity_bound_after_tracking_cancel(workshop, monkeypatch, operation_kind):
    job_id = register(workshop)
    mock_idle(monkeypatch)
    def lost_reply(*_args, **_kwargs):
        raise ValueError("No response after dispatch.")
    monkeypatch.setattr("app.jobs.write_controller", lost_reply)
    monkeypatch.setattr("app.jobs.upload_controller_file", lost_reply)
    result = start(workshop, job_id) if operation_kind == "start" else upload(workshop, job_id)
    assert result.status_code == 502
    assert workshop["client"].post(f"/api/jobs/{job_id}/cancel").status_code == 200
    current = workshop["printers"][0]
    config = {key: value for key, value in current.items() if key != "id"}
    monkeypatch.setenv("SPOOLMERA_PRINTER_TOKEN_CHANGED", "test-token-value")
    for change in ({"base_url": "http://192.168.50.21:7125"},
                   {"token_env": "SPOOLMERA_PRINTER_TOKEN_CHANGED"},
                   {"kind": "octoprint", "token_env": "SPOOLMERA_PRINTER_TOKEN_CHANGED"}):
        result = workshop["client"].put(f"/api/printers/{current['id']}", json={**config, **change})
        assert result.status_code == 409, result.text
    assert rows(workshop, "SELECT base_url,kind,token_env FROM printers WHERE id=?", (current["id"],)) == [
        {"base_url": current["base_url"], "kind": "moonraker", "token_env": ""}]


@pytest.mark.parametrize("terminal_source", ["poll", "controller", "cloud"])
def test_later_failure_signal_preserves_already_reviewed_actual_consumption(workshop, monkeypatch, terminal_source):
    job_id, _, remote = running_job(workshop, monkeypatch)
    pid, sid = workshop["printers"][0]["id"], workshop["spools"][0]
    client = workshop["client"]
    result = client.post(f"/api/jobs/{job_id}/consumption", json={
        "mode": "actual", "materials": [{"spool_id": sid, "actual_g": 37}],
        "reason": "Measured material used by the interrupted print", "expected_accounting_revision": 0})
    assert result.status_code == 200, result.text
    if terminal_source == "poll":
        remote["status"] = "error"
        result = client.post(f"/api/printers/{pid}/poll")
    elif terminal_source == "controller":
        monkeypatch.setattr("app.printers.issue_control", lambda *_: 200)
        result = client.post(f"/api/printers/{pid}/control", json={"action": "cancel"})
    else:
        secret = "cloud-test-secret-with-more-than-thirty-two-bytes"
        monkeypatch.setenv("SPOOLMERA_CLOUD_HMAC_TEST", secret)
        monkeypatch.setenv("SPOOLMERA_CLOUD_PRINTER_TEST", str(pid))
        raw = json.dumps({"event_id": "accounted-print-failed", "job_id": job_id, "status": "failed"}).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        result = client.post("/api/cloud/hooks/TEST", content=raw,
            headers={"X-Spoolmera-Timestamp": stamp, "X-Spoolmera-Signature": signature})
    assert result.status_code == 200, result.text
    snapshot = client.get(f"/api/jobs/{job_id}/consumption").json()
    assert snapshot["status"] == "needs_review"
    assert (snapshot["accounting_status"], snapshot["accounting_method"], snapshot["accounting_revision"]) == ("debited", "actual", 1)
    assert snapshot["materials"][0]["accounted_g"] == 37
    assert rows(workshop, "SELECT remaining_g FROM spools WHERE id=?", (sid,)) == [{"remaining_g": 963}]
    assert rows(workshop, "SELECT delta_g FROM movements WHERE print_job_id=?", (job_id,)) == [{"delta_g": -37}]


def test_legacy_discard_after_partial_accounting_uses_a_linked_compensation(workshop, monkeypatch):
    job_id, _, _ = running_job(workshop, monkeypatch)
    client, sid, pid = workshop["client"], workshop["spools"][0], workshop["printers"][0]["id"]
    actual = client.post(f"/api/jobs/{job_id}/consumption", json={"mode": "actual",
        "materials": [{"spool_id": sid, "actual_g": 37}], "reason": "Initial actual amount for later review"})
    assert actual.status_code == 200, actual.text
    monkeypatch.setattr("app.printers.issue_control", lambda *_: 200)
    assert client.post(f"/api/printers/{pid}/control", json={"action": "cancel"}).status_code == 200
    result = client.post(f"/api/jobs/{job_id}/resolve", json={"action": "discard"})
    assert result.status_code == 200, result.text
    movements = rows(workshop, "SELECT id,delta_g,source,corrects_movement_id FROM movements WHERE print_job_id=? ORDER BY id", (job_id,))
    assert [movement["delta_g"] for movement in movements] == [-37, 37]
    assert movements[1]["corrects_movement_id"] == movements[0]["id"]
    assert movements[1]["source"] == "job_correction"
    assert rows(workshop, "SELECT remaining_g FROM spools WHERE id=?", (sid,)) == [{"remaining_g": 1000}]
    assert rows(workshop, "SELECT status,accounting_status,accounting_method FROM print_jobs WHERE id=?", (job_id,)) == [
        {"status": "cancelled", "accounting_status": "discarded", "accounting_method": "discard"}]
    assert len(operations(workshop)) == 1  # Accounting does not attest the physical printer state.
