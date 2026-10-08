"""Reservation concurrency semantics, lifecycle release and physical feeder mapping."""
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.database import session
from tests.support import authenticate
from tests.test_security_jobs import make_inventory


@pytest.fixture
def workspace(tmp_path):
    path=tmp_path/"planning.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        s0=make_inventory(client)
        s1=make_inventory(client)
        p=client.post("/api/printers",json={
            "name":"Workshop","kind":"moonraker",
            "base_url":"http://192.168.50.20:7125","enabled":True,"token_env":""
        })
        assert p.status_code==201,p.text
        yield client,path,p.json()["id"],s0,s1


def add_job(client,printer,spool,file,grams):
    response=client.post("/api/jobs",json={"printer_id":printer,"spool_id":spool,
        "file_name":file,"estimated_g":grams})
    assert response.status_code==201,response.text
    return response.json()["id"]


def test_reservations_do_not_consume_and_cannot_oversubscribe(workspace):
    client,path,printer,s0,s1=workspace
    first=add_job(client,printer,s0,"a.gcode",700)
    second=add_job(client,printer,s0,"b.gcode",500)
    base=f"/api/jobs/{first}/reservation"
    r=client.post(base)
    assert r.status_code==200,r.text
    assert r.json()["reserved"] is True
    assert client.post(base).status_code==200
    assert client.post(f"/api/jobs/{second}/reservation").status_code==409
    assert client.get(f"/api/jobs/{second}/readiness").json()["ready"] is False
    assert client.get("/api/spools").json()[0]["remaining_g"]==1000 or any(
        s["id"]==s0 and s["remaining_g"]==1000 for s in client.get("/api/spools").json())
    assert client.delete(base).status_code==200
    assert client.post(f"/api/jobs/{second}/reservation").status_code==200
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM job_reservations").fetchone()[0]==1


def test_multi_tool_reservation_released_on_debit_and_cancel(workspace):
    client,path,printer,s0,s1=workspace
    multi=client.post("/api/jobs/multi",json={"printer_id":printer,"file_name":"multi.gcode",
        "materials":[{"tool":0,"spool_id":s0,"estimated_g":100},
                     {"tool":1,"spool_id":s1,"estimated_g":80}]})
    assert multi.status_code==201,multi.text
    jid=multi.json()["id"]
    assert client.post(f"/api/jobs/{jid}/reservation").status_code==200
    with session(path,write=True) as db:
        db.execute("UPDATE print_jobs SET status='needs_review' WHERE id=?",(jid,))
    result=client.post(f"/api/jobs/{jid}/resolve",json={"action":"debit"})
    assert result.status_code==200,result.text
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM job_reservations WHERE job_id=?",(jid,)).fetchone()[0]==0
    other=add_job(client,printer,s0,"later.gcode",40)
    assert client.post(f"/api/jobs/{other}/reservation").status_code==200
    assert client.post(f"/api/jobs/{other}/cancel").status_code==200
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM job_reservations WHERE job_id=?",(other,)).fetchone()[0]==0


def test_slot_mapping_is_explicit_and_uniqueness_guarded(workspace):
    client,path,printer,s0,s1=workspace
    route=f"/api/printers/{printer}/slots/0"
    assert client.put(route,json={"spool_id":s0}).status_code==200
    assert client.put(f"/api/printers/{printer}/slots/1",json={"spool_id":s0}).status_code==409
    jid=add_job(client,printer,s0,"slot.gcode",10)
    r=client.get(f"/api/jobs/{jid}/readiness")
    assert r.status_code==200,r.text
    assert r.json()["materials"][0]["loaded_match"] is True
    assert client.delete(route).status_code==200
    assert client.get(f"/api/printers/{printer}/slots").json()==[]
