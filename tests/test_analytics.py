"""Cost estimates separate currencies and unknown purchase prices."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.support import authenticate


def test_purchase_cost_reporting(tmp_path):
    with TestClient(create_app(tmp_path/"cost.sqlite3")) as c:
        authenticate(c)
        prod=c.post("/api/products",json={"brand":"Example","name":"PLA",
              "material":"PLA","color_name":"Black"}).json()["id"]
        s=c.post("/api/spools",json={"product_id":prod,"initial_g":1000,
             "purchase_price_cents":2000,"purchase_currency":"EUR"}).json()["id"]
        assert c.post(f"/api/spools/{s}/movements",
                      json={"kind":"consume","grams":250}).status_code==201
        r=c.get("/api/analytics/material-usage")
        assert r.status_code==200,r.text
        assert r.json()["consumed_g"]==250
        assert r.json()["currency_groups"]==[{"currency":"EUR","consumed_g":250,
                                               "known_cost_cents":500,"unpriced_g":0}]
        assert r.json()["estimated"] is True
