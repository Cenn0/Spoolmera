"""Label sizes are an explicit allowlist and contain the same stable spool UUID."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_label_variants(tmp_path):
    with TestClient(create_app(tmp_path/"label.sqlite3")) as c:
        authenticate(c)
        p=c.post("/api/products",json={"brand":"Example","name":"PLA",
                  "material":"PLA","color_name":"Red"}).json()["id"]
        c.post("/api/spools",json={"product_id":p,"initial_g":1000})
        uid=c.get("/api/spools").json()[0]["uid"]
        small=c.get(f"/labels/{uid}?size=50x30")
        assert small.status_code==200,small.text
        assert "/static/label-50x30.css" in small.text
        assert uid in small.text
        assert c.get(f"/labels/{uid}?size=60x40").status_code==200
        assert c.get(f"/labels/{uid}?size=50x40").status_code==422
