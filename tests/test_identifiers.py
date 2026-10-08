"""Tag association is optional, unique, revocable, and never grants authorization."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_scanned_tag_is_not_authorization_and_cannot_be_reassigned(tmp_path):
    with TestClient(create_app(tmp_path/"tags.sqlite3")) as c:
        authenticate(c)
        prod=c.post("/api/products",json={"brand":"Example","name":"PLA",
            "material":"PLA","color_name":"Black"}).json()["id"]
        s1=c.post("/api/spools",json={"product_id":prod,"initial_g":1000}).json()["id"]
        s2=c.post("/api/spools",json={"product_id":prod,"initial_g":1000}).json()["id"]
        tag={"namespace":"nfc","external_id":"04A45F3398"}
        p=f"/api/spools/{s1}/identifiers"
        assert c.post(p,json=tag).status_code==201
        assert c.post(p,json=tag).json()["already_registered"] is True
        assert c.post(f"/api/spools/{s2}/identifiers",json=tag).status_code==409
        assert c.get("/api/identifiers/nfc/04A45F3398").json()["id"]==s1
        # Even with a guessed tag, anonymous clients cannot read the inventory.
        anonymous=TestClient(create_app(tmp_path/"tags.sqlite3"))
        assert anonymous.get("/api/identifiers/nfc/04A45F3398").status_code==401
        anonymous.close()
        assert c.delete(p+"/nfc/04A45F3398").status_code==200
        assert c.get("/api/identifiers/nfc/04A45F3398").status_code==404
        assert c.post(f"/api/spools/{s2}/identifiers",json=tag).status_code==201
