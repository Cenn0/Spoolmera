"""Machine tokens cannot inherit browser privileges and never mutate stock."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_scoped_machine_auth_revoke_and_pagination(tmp_path):
    with TestClient(create_app(tmp_path/"token.sqlite3")) as c:
        authenticate(c)
        assert c.get("/api/automation/v1/spools").status_code==401
        created=c.post("/api/admin/automation-tokens",json={"label":"Home Assistant","scope":"inventory_read"})
        assert created.status_code==201,created.text
        secret=created.json()["token"]
        assert secret.startswith("spm_")
        assert secret not in str(c.get("/api/admin/automation-tokens").json())
        c.headers["Authorization"]="Bearer "+secret
        assert c.get("/api/automation/v1/spools").status_code==200
        assert c.get("/api/automation/v1/movements").status_code==403
        pid=c.post("/api/products",json={"brand":"Test","name":"PETG",
          "material":"PETG","color_name":"Red"}).json()["id"]
        c.post("/api/spools",json={"product_id":pid,"initial_g":1000})
        assert len(c.get("/api/automation/v1/spools").json()["spools"])==1
        assert c.delete("/api/admin/automation-tokens/"+str(created.json()["id"])).status_code==200
        assert c.get("/api/automation/v1/spools").status_code==403
        assert c.delete("/api/admin/automation-tokens/"+str(created.json()["id"])).status_code==404


def test_machine_events_requires_separate_scope(tmp_path):
    with TestClient(create_app(tmp_path/"token.sqlite3")) as c:
        authenticate(c)
        r=c.post("/api/admin/automation-tokens",json={"label":"ntfy","scope":"events_read"})
        c.headers["Authorization"]="Bearer "+r.json()["token"]
        assert c.get("/api/automation/v1/movements?after=0").status_code==200
        assert c.get("/api/automation/v1/spools").status_code==403
        assert c.get("/api/automation/v1/movements?limit=300").status_code==422


def test_machine_routes_reject_cookie_without_authorization(tmp_path):
    with TestClient(create_app(tmp_path/"token.sqlite3")) as c:
        authenticate(c)
        assert c.get("/api/automation/v1/spools").status_code==401
        assert c.get("/api/automation/v1/movements").status_code==401
