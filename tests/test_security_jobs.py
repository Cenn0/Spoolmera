"""Security and printer accounting regression tests, no real network access."""
import time
from fastapi.testclient import TestClient
from app.main import create_app
from app.printers import normalize_printer_url
from tests.support import authenticate, PASSWORD


def make_inventory(client):
    product = client.post("/api/products", json={
        "brand":"Test","name":"PLA","material":"PLA","color_name":"Blue","color_hex":"#3377AA"
    })
    assert product.status_code == 201, product.text
    spool = client.post("/api/spools",json={"product_id":product.json()["id"],"initial_g":1000})
    assert spool.status_code == 201, spool.text
    return spool.json()["id"]


def test_bootstrap_auth_roles_csrf_and_sessions(tmp_path):
    with TestClient(create_app(tmp_path/"security.db")) as client:
        assert client.get("/api/auth/status").json() == {"needs_setup":True}
        assert client.get("/api/products").status_code == 401
        assert client.get("/api/auth/users").status_code == 401
        assert client.post("/api/auth/setup",json={"username":"admin","password":PASSWORD}).status_code == 403
        authenticate(client)
        assert client.get("/api/auth/status").json()["needs_setup"] is False
        assert client.post("/api/auth/setup",json={"username":"x","password":PASSWORD},
                           headers={"X-Bootstrap-Token":"test-only-bootstrap-token-long-enough"}).status_code == 409
        assert client.post("/api/products", json={"brand":"X"} ,headers={"X-CSRF-Token":""}).status_code == 403
        assert client.post("/api/products", json={"brand":"X"},headers={
            "Origin":"https://untrusted.example"}).status_code == 403
        viewer = client.post("/api/auth/users", json={"username":"viewer","password":"viewer-password-2026","role":"viewer"})
        assert viewer.status_code == 201, viewer.text
        editor = client.post("/api/auth/users", json={"username":"editor","password":"editor-password-2026","role":"editor"})
        assert editor.status_code == 201
        assert client.patch("/api/auth/users/1", json={"enabled":False}).status_code == 409

    with TestClient(create_app(tmp_path/"security.db")) as viewer_client:
        signed = viewer_client.post("/api/auth/login",json={"username":"viewer","password":"viewer-password-2026"})
        assert signed.status_code == 200,signed.text
        assert signed.json()["role"]=="viewer"
        viewer_client.headers["X-CSRF-Token"]=signed.json()["csrf_token"]
        assert viewer_client.get("/api/products").status_code == 200
        assert viewer_client.get("/api/auth/users").status_code == 403
        assert viewer_client.post("/api/products",json={"brand":"X"}).status_code == 403
        assert viewer_client.post("/api/printers",json={}).status_code == 403
        assert viewer_client.post("/api/auth/logout").status_code == 200
        assert viewer_client.get("/api/products").status_code == 401

    with TestClient(create_app(tmp_path/"security.db")) as editor_client:
        signed = editor_client.post("/api/auth/login", json={"username":"editor","password":"editor-password-2026"})
        assert signed.status_code == 200
        editor_client.headers["X-CSRF-Token"]=signed.json()["csrf_token"]
        assert editor_client.post("/api/printers",json={}).status_code == 403
        assert editor_client.get("/api/jobs").status_code == 200


def test_password_auth_throttling_and_revoked_sessions(tmp_path):
    with TestClient(create_app(tmp_path/"rate.db")) as client:
        authenticate(client)
        for attempt in range(5):
            invalid = client.post("/api/auth/login",json={"username":"testadmin","password":"wrong"})
            assert invalid.status_code == 401, (attempt, invalid.text)
        blocked = client.post("/api/auth/login",json={"username":"testadmin","password":PASSWORD})
        assert blocked.status_code == 429
        assert client.post("/api/auth/password",json={"old_password":"wrong","new_password":"new-password-strong-2026"}).status_code==403
        updated = client.post("/api/auth/password",json={
            "old_password":PASSWORD,"new_password":"new-password-strong-2026"
        })
        assert updated.status_code==200,updated.text
        assert client.get("/api/products").status_code==401
        client.headers["X-CSRF-Token"]=updated.json()["csrf_token"]
        assert client.get("/api/products").status_code==200
        assert client.post("/api/auth/logout").status_code==200
        assert client.get("/api/auth/me").status_code==401


def test_allowlist_rejects_ssrf_targets(monkeypatch):
    for url in [
        "http://127.0.0.1:7125", "http://169.254.169.254:80", "http://8.8.8.8:80",
        "http://localhost:7125", "http://192.168.50.20:7125/path", "file:///etc/passwd",
        "http://user:pass@192.168.50.20:7125",
    ]:
        try:
            normalize_printer_url(url)
            assert False, url
        except ValueError:
            pass
    assert normalize_printer_url("http://192.168.50.20:7125")=="http://192.168.50.20:7125"
    monkeypatch.setenv("FILAMENT_PRINTER_ALLOWED_IPS","")
    try:
        normalize_printer_url("http://192.168.50.20:7125")
        assert False, "allowlist incorrectly bypassed"
    except ValueError:
        pass


def test_moonraker_exact_once_completion_and_gcode_import(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path/"moon.db")) as client:
        authenticate(client)
        spool_id = make_inventory(client)
        p = client.post("/api/printers",json={
            "name":"Klipper test","kind":"moonraker","base_url":"http://192.168.50.20:7125",
            "token_env":"","enabled":True
        })
        assert p.status_code==201,p.text
        p_id = p.json()["id"]
        content = b"; generated by slicer\n; filament used [g] = 125.1\nG1 E1\n"
        imported = client.post(
            f"/api/jobs/import?printer_id={p_id}&spool_id={spool_id}&file_name=fixture.gcode",
            content=content,headers={"Content-Type":"application/octet-stream"}
        )
        assert imported.status_code==201,imported.text
        assert imported.json()["estimated_g"]==125
        job_id=imported.json()["id"]
        start=time.time()+10
        remote={"job_id":"run-unique-01","filename":"fixture.gcode","start_time":start,"status":"in_progress"}
        state={"state":"printing","filename":"fixture.gcode"}
        def fake_fetch(printer,path):
            if path.startswith("/server/history/list"):return {"result":{"jobs":[dict(remote)]}}
            if path.startswith("/printer/objects/query"):return {"result":{"status":{"print_stats":dict(state)}}}
            raise AssertionError(path)
        monkeypatch.setattr("app.printers.fetch_json",fake_fetch)
        first = client.post(f"/api/printers/{p_id}/poll")
        assert first.status_code==200,first.text
        assert client.get("/api/jobs").json()[0]["status"]=="printing"
        assert client.get("/api/spools").json()[0]["remaining_g"]==1000
        remote["status"]="completed"
        state["state"]="complete"
        second=client.post(f"/api/printers/{p_id}/poll")
        assert second.status_code==200,second.text
        assert client.get("/api/spools").json()[0]["remaining_g"]==875
        job = client.get("/api/jobs").json()[0]
        assert job["status"]=="completed" and job["movement_id"]
        assert client.post(f"/api/printers/{p_id}/poll").status_code==200
        assert client.get("/api/spools").json()[0]["remaining_g"]==875
        assert len(client.get(f"/api/spools/{spool_id}/movements").json())==2
        assert client.post(f"/api/jobs/{job_id}/resolve",json={"action":"debit"}).status_code==409
        # A completed history entry without previously observing printing must not debit.
        imported = client.post(
            f"/api/jobs/import?printer_id={p_id}&spool_id={spool_id}&file_name=second.gcode",
            content=b"; filament_weight_g: 50\n",headers={"Content-Type":"text/plain"}
        )
        assert imported.status_code==201
        remote.update(job_id="run-unique-02",filename="second.gcode",start_time=time.time()+5)
        assert client.post(f"/api/printers/{p_id}/poll").status_code==200
        assert client.get("/api/jobs").json()[0]["status"]=="needs_review"
        assert client.get("/api/spools").json()[0]["remaining_g"]==875


def test_octoprint_requires_human_completion_review(tmp_path, monkeypatch):
    monkeypatch.setenv("FILAMENT_PRINTER_TOKEN_OCTO","test-secret")
    with TestClient(create_app(tmp_path/"octo.db")) as client:
        authenticate(client)
        spool_id = make_inventory(client)
        printer = client.post("/api/printers",json={
            "name":"OctoPrint","kind":"octoprint","base_url":"http://192.168.50.21:5000",
            "token_env":"FILAMENT_PRINTER_TOKEN_OCTO","enabled":True
        })
        assert printer.status_code==201,printer.text
        printer_id=printer.json()["id"]
        job=client.post("/api/jobs",json={
            "printer_id":printer_id,"spool_id":spool_id,"file_name":"bracket.gcode",
            "estimated_g":150
        })
        assert job.status_code==201,job.text
        current={"state":"Printing","job":{"file":{"name":"bracket.gcode"}}}
        monkeypatch.setattr("app.printers.fetch_json",lambda printer,path:dict(current))
        assert client.post(f"/api/printers/{printer_id}/poll").status_code==200
        current["state"]="Operational"
        assert client.post(f"/api/printers/{printer_id}/poll").status_code==200
        assert client.get("/api/jobs").json()[0]["status"]=="needs_review"
        assert client.get("/api/spools").json()[0]["remaining_g"]==1000
        approved=client.post(f"/api/jobs/{job.json()['id']}/resolve",json={"action":"debit"})
        assert approved.status_code==200
        assert client.get("/api/spools").json()[0]["remaining_g"]==850
