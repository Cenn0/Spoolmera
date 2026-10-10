"""Device HMAC reports cannot directly change stock or replay multiple debits."""
import hashlib
import hmac
import json
import time
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_scale_event_requires_approval_and_is_idempotent(tmp_path,monkeypatch):
    key="scale-adapter-key-long-enough-for-HMAC-2026"
    monkeypatch.setenv("SPOOLMERA_SCALE_HMAC_SHOP",key)
    with TestClient(create_app(tmp_path/"scale.sqlite3")) as c:
        authenticate(c)
        product=c.post("/api/products",json={"brand":"Example","name":"PLA",
                  "material":"PLA","color_name":"Blue"}).json()["id"]
        c.post("/api/spools",json={"product_id":product,"initial_g":1000,
                                  "remaining_g":700,"tare_g":250})
        spool=c.get("/api/spools").json()[0]
        event={"event_id":"weigh-00001","spool_uid":spool["uid"],"gross_g":840}
        raw=json.dumps(event,separators=(",",":")).encode()
        stamp=str(int(time.time()))
        sign=hmac.new(key.encode(),stamp.encode()+b"."+raw,hashlib.sha256).hexdigest()
        headers={"X-Filament-Timestamp":stamp,"X-Filament-Signature":"sha256="+sign,
                 "Content-Type":"application/json"}
        url="/api/scales/hooks/SHOP"
        assert c.post(url,content=raw).status_code==401
        first=c.post(url,content=raw,headers=headers)
        assert first.status_code==200,first.text
        assert first.json()["status"]=="pending"
        assert c.post(url,content=raw,headers=headers).json()["duplicate"] is True
        assert c.get("/api/spools").json()[0]["remaining_g"]==700
        pending=c.get("/api/scales/measurements").json()
        assert len(pending)==1
        review=c.post(f'/api/scales/measurements/{pending[0]["id"]}/review',
                      json={"action":"approve","note":"Verified digital scale and spool ID"})
        assert review.status_code==200,review.text
        assert review.json()["weighing"]["remaining_g"]==590
        assert c.get("/api/spools").json()[0]["remaining_g"]==590
        assert c.post(f'/api/scales/measurements/{pending[0]["id"]}/review',
                      json={"action":"approve","note":"Repeat approval request"}).status_code==409
        assert len(c.get(f'/api/spools/{spool["id"]}/movements').json())==2


def test_scale_event_rejects_modified_body_with_reused_id(tmp_path,monkeypatch):
    key="scale-adapter-key-long-enough-for-HMAC-2026"
    monkeypatch.setenv("SPOOLMERA_SCALE_HMAC_SHOP",key)
    with TestClient(create_app(tmp_path/"scale.sqlite3")) as c:
        authenticate(c)
        p=c.post("/api/products",json={"brand":"Example","name":"PLA",
            "material":"PLA","color_name":"Blue"}).json()["id"]
        c.post("/api/spools",json={"product_id":p,"initial_g":1000})
        uid=c.get("/api/spools").json()[0]["uid"]
        def send(gross):
            raw=json.dumps({"event_id":"weigh-00001","spool_uid":uid,"gross_g":gross}).encode()
            stamp=str(int(time.time()))
            sig=hmac.new(key.encode(),stamp.encode()+b"."+raw,hashlib.sha256).hexdigest()
            return c.post("/api/scales/hooks/SHOP",content=raw,headers={
                "Content-Type":"application/json","X-Filament-Timestamp":stamp,
                "X-Filament-Signature":"sha256="+sig})
        assert send(900).status_code==200
        assert send(700).status_code==409
