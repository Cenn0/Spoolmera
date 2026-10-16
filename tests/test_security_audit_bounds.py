"""Regression tests for security resource boundaries (mocked, no printer hardware)."""
import asyncio
import hashlib
import hmac
import io
import json
import os
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, jobs, slicing
from app.core.auth_body_limit import AUTH_BODY_LIMIT, AuthenticationBodyLimit
from app.database import session
from app.main import create_app
from app.services.gcode_metadata import gcode_tool_estimates, three_mf_plate_estimates
from app.services.process_lock import ProcessLock
from tests.support import authenticate


def _metadata_zip(xml: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Metadata/slice_info.config", xml)
    return buffer.getvalue()


@pytest.mark.parametrize("endpoint", ["/api/auth/login", "/api/auth/setup"])
def test_public_auth_body_size_checked_before_json(endpoint, tmp_path):
    with TestClient(create_app(tmp_path / "limit.sqlite3")) as client:
        response = client.post(endpoint, content=b"x" * (AUTH_BODY_LIMIT + 1),
                               headers={"Content-Type": "application/json"})
        assert response.status_code == 413
        # A valid-size body is passed through to normal model validation.
        response = client.post(endpoint, content=b"{}",
                               headers={"Content-Type": "application/json"})
        assert response.status_code == 422


def test_chunked_public_auth_body_is_bounded_without_content_length():
    invoked = False
    async def next_app(scope, receive, send):
        nonlocal invoked
        invoked = True

    chunks = iter([
        {"type": "http.request", "body": b"a" * 2048, "more_body": True},
        {"type": "http.request", "body": b"b" * 2049, "more_body": False},
    ])
    async def receive():
        return next(chunks)

    sent = []
    async def send(message):
        sent.append(message)

    asyncio.run(AuthenticationBodyLimit(next_app)(
        {"type": "http", "path": "/api/auth/login", "method": "POST", "headers": []},
        receive, send,
    ))
    assert not invoked
    assert any(msg["type"] == "http.response.start" and msg["status"] == 413 for msg in sent)


def test_rotating_login_usernames_exhausts_shared_budget_before_argon2(tmp_path, monkeypatch):
    calls = 0
    actual_verify = auth.verify_password

    def measured_verify(password, hashed):
        nonlocal calls
        calls += 1
        return actual_verify(password, hashed)

    with TestClient(create_app(tmp_path / "rate.sqlite3")) as client:
        authenticate(client)
        monkeypatch.setattr(auth, "verify_password", measured_verify)
        for number in range(auth.LOGIN_CLIENT_BUDGET):
            response = client.post("/api/auth/login",
                                   json={"username": f"unknown{number}", "password": "incorrect"})
            assert response.status_code == 401, response.text
        blocked = client.post("/api/auth/login",
                              json={"username": "another-unknown-user", "password": "incorrect"})
        assert blocked.status_code == 429
        assert calls == auth.LOGIN_CLIENT_BUDGET
        with session(tmp_path / "rate.sqlite3") as db:
            count = db.execute("SELECT COUNT(*) FROM auth_failures WHERE subject='login-global'").fetchone()[0]
        assert count == auth.LOGIN_CLIENT_BUDGET


def test_gcode_whitespace_near_match_has_bounded_parse_time():
    adversarial = b"; filament used [g] = " + b" " * 130000 + b"X\n"
    started = time.monotonic()
    assert gcode_tool_estimates(adversarial) == []
    assert time.monotonic() - started < 2.0


def test_3mf_rejects_nested_plates_and_excessive_xml_structure():
    valid = b'<config><plate><filament id="1" used_g="12.5"/></plate></config>'
    assert three_mf_plate_estimates(_metadata_zip(valid)) == [
        {"plate": 1, "materials": [{"tool": 0, "estimated_g": 13}]}
    ]
    nested = b"<config><plate><plate><filament id='1' used_g='12'/></plate></plate></config>"
    with pytest.raises(ValueError, match="Nested"):
        three_mf_plate_estimates(_metadata_zip(nested))
    deep = b"<config>" + b"<other>" * 35 + b"<plate/>" + b"</other>" * 35 + b"</config>"
    with pytest.raises(ValueError, match="structural limits"):
        three_mf_plate_estimates(_metadata_zip(deep))
    oversized = b"<config>" + b"<other/>" * 4096 + b"</config>"
    with pytest.raises(ValueError, match="structural limits"):
        three_mf_plate_estimates(_metadata_zip(oversized))


def _product_and_job(client):
    product = client.post("/api/products", json={
        "brand": "Fixture", "name": "PLA", "material": "PLA", "color_name": "Black",
        "color_hex": "#000000", "diameter_mm": 1.75,
    })
    assert product.status_code == 201, product.text
    spool = client.post("/api/spools", json={
        "product_id": product.json()["id"], "initial_g": 1000,
    })
    assert spool.status_code == 201, spool.text
    printer = client.post("/api/printers", json={
        "name": "Mock device", "kind": "moonraker",
        "base_url": "http://192.168.50.20:7125", "enabled": True,
    })
    assert printer.status_code == 201, printer.text
    printer_id = printer.json()["id"]
    job = client.post("/api/jobs", json={
        "printer_id": printer_id, "spool_id": spool.json()["id"],
        "file_name": "fixture.gcode", "estimated_g": 40,
    })
    assert job.status_code == 201, job.text
    return printer_id, job.json()["id"]


def test_cloud_telemetry_does_not_create_unbounded_receipts(tmp_path, monkeypatch):
    secret = "test-only-relay-key-longer-than-thirty-two-bytes"
    monkeypatch.setenv("SPOOLMERA_CLOUD_HMAC_TEST", secret)
    path = tmp_path / "cloud.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        printer_id, job_id = _product_and_job(client)
        monkeypatch.setenv("SPOOLMERA_CLOUD_PRINTER_TEST", str(printer_id))

        def event(identifier, status):
            body = json.dumps({"event_id": identifier, "job_id": job_id,
                               "status": status}, separators=(",", ":")).encode()
            stamp = str(int(time.time()))
            sig = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            return client.post("/api/cloud/hooks/TEST", content=body, headers={
                "X-Spoolmera-Timestamp": stamp,
                "X-Spoolmera-Signature": "sha256=" + sig,
                "Content-Type": "application/json",
            })

        for n in range(15):
            response = event(f"printing{n:04d}", "printing")
            assert response.status_code == 200, response.text
            assert response.json()["disposition"] == "ignored_no_change"
        accepted = event("completed0001", "completed")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["disposition"] == "needs_review"
        replay = event("completed0001", "completed")
        assert replay.json()["duplicate"] is True
        for n in range(15):
            response = event(f"latecompleted{n:04d}", "completed")
            assert response.status_code == 200, response.text
            assert response.json()["disposition"] == "ignored_no_change"
        with session(path) as db:
            assert db.execute("SELECT COUNT(*) FROM cloud_event_receipts").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action LIKE 'cloud_%'").fetchone()[0] == 1


def test_scheduled_and_manual_printer_polls_share_same_gate(tmp_path, monkeypatch):
    path = tmp_path / "poll.sqlite3"
    entered = threading.Event()
    release = threading.Event()
    failures = []

    class FakeAdapter:
        def get_history(self, printer):
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("Mock poll did not release.")
            return []

        def get_status(self, printer):
            return {"state": "standby", "filename": ""}

        def observe(self, *args):
            from types import SimpleNamespace
            return SimpleNamespace(outcome=None, external_id=None, remote_state=None)

    monkeypatch.setattr(jobs, "adapter_for", lambda *a, **k: FakeAdapter())
    with TestClient(create_app(path)) as client:
        authenticate(client)
        printer_id, _ = _product_and_job(client)

        def first_poll():
            try:
                jobs.poll_printer(path, printer_id)
            except Exception as exc:
                failures.append(exc)

        worker = threading.Thread(target=first_poll, daemon=True)
        try:
            worker.start()
            assert entered.wait(timeout=3)
            with pytest.raises(jobs.PollBusyError):
                jobs.poll_printer(path, printer_id)
            response = client.post(f"/api/printers/{printer_id}/poll")
            assert response.status_code == 429
        finally:
            release.set()
            worker.join(timeout=5)
        assert not worker.is_alive()
        assert not failures


def test_isolated_slicer_worker_cannot_redirect_api_request(monkeypatch):
    visited = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            visited.append(self.path)
            if self.path == "/first":
                self.send_response(302)
                self.send_header("Location", "/second")
                self.send_header("Content-Length", "0")
            else:
                self.send_response(200)
                self.send_header("Content-Length", "2")
            self.end_headers()
            if self.path == "/second":
                self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setattr(slicing, "worker_url",
                            lambda: f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("SPOOLMERA_SLICER_WORKER_TOKEN", "x" * 40)
        with pytest.raises(HTTPException) as error:
            slicing.request_worker("/first")
        assert error.value.status_code == 502
        assert visited == ["/first"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
                    reason="POSIX no-follow operation-lock protection")
def test_operation_lock_refuses_symlink_without_modifying_target(tmp_path):
    target = tmp_path / "outside"
    target.write_text("do not touch", encoding="utf-8")
    link = tmp_path / ".spoolmera.sqlite3.recovery.lock"
    link.symlink_to(target)
    with pytest.raises(OSError):
        ProcessLock(link).acquire()
    assert target.read_text(encoding="utf-8") == "do not touch"
    normal = ProcessLock(tmp_path / ".spoolmera.sqlite3.application.lock")
    assert normal.acquire()
    normal.release()


def test_legacy_gcode_estimate_rejects_multiline_metadata_and_accepts_crlf():
    # The separator cannot absorb a newline and borrow an unsigned following line.
    assert jobs.estimate_gcode(b";\nfilament_weight_g = 23\n") is None
    assert jobs.estimate_gcode(b"; filament_weight_g = 23\r\n") == 23
    assert jobs.estimate_gcode(b"; filament used [g] = 23.4\r\n") == 23


def test_metadata_inspection_accepts_crlf_gcode_comments():
    assert gcode_tool_estimates(b"; filament used [g] = 12.5, 8\r\n") == [
        {"tool": 0, "estimated_g": 13},
        {"tool": 1, "estimated_g": 8},
    ]
    assert gcode_tool_estimates(b"; filament_weight_g = 10.2\r\n") == [
        {"tool": 0, "estimated_g": 10},
    ]
