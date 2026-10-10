"""Label sizes are an explicit allowlist and contain the same stable spool UUID."""
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from app.labels import label_language, labels_html
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


@pytest.mark.parametrize(("query", "cookie", "header", "expected"), [
    ("de", "en", "en-US", "de"),
    ("en", "de", "de-DE", "en"),
    (None, "de", "en-US", "de"),
    (None, "en", "de-DE", "en"),
    (None, "invalid", "fr-FR,de-DE;q=0.8,en-US;q=0.4", "de"),
    (None, None, "de-DE;q=0.5,en-US;q=0.9", "en"),
    (None, None, "de;q=0,en;q=0.5", "en"),
    (None, None, "en;q=0,de;q=0.5", "de"),
    (None, None, "de;q=invalid,en;q=0.5", "en"),
    (None, None, "fr-FR,es-ES;q=0.9", "en"),
    (None, None, "en;q=0,*;q=0.8", "de"),
    (None, None, "de;q=0,*;q=0.8", "en"),
    (None, None, "en;q=0.9,de;q=0.2,*;q=1", "en"),
    (None, None, "", "en"),
])
def test_label_language_precedence(query, cookie, header, expected):
    assert label_language(query, cookie, header) == expected


@pytest.mark.parametrize("batch", [False, True])
def test_label_languages_preserve_escaping_identity_and_access(tmp_path, batch):
    with TestClient(create_app(tmp_path / "localized-labels.sqlite3")) as client:
        authenticate(client)
        product = client.post("/api/products", json={
            "brand": 'Brand & Sons "EU"', "name": "<script>alert(1)</script>",
            "material": "PLA", "color_name": "Red",
        })
        assert product.status_code == 201, product.text
        created = client.post("/api/spools", json={"product_id": product.json()["id"], "initial_g": 1000})
        assert created.status_code == 201, created.text
        uid = client.get("/api/spools").json()[0]["uid"]
        path = "/labels" if batch else f"/labels/{uid}"
        query = {"uids": uid} if batch else {}
        qr_path = f"/api/spools/{uid}/qr.svg"
        qr_before = client.get(qr_path).content
        original = client.get(path, params=query)
        assert original.status_code == 200, original.text
        assert '<html lang="en">' in original.text
        assert "Remaining: 1000 g" in original.text

        german = client.get(path, params={**query, "size": "50x30"}, headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"})
        assert german.status_code == 200, german.text
        assert german.headers["Content-Language"] == "de"
        assert german.headers["Cache-Control"] == "no-store"
        assert german.headers["Content-Security-Policy"] == original.headers["Content-Security-Policy"]
        assert '<html lang="de">' in german.text
        assert '<title>Spulenetiketten · 1</title>' in german.text
        assert "Restmenge: 1.000 g" in german.text
        assert "SPULE" in german.text
        assert "Zurück zum Bestand" in german.text
        assert "Spulenetikett, 50 mal 30 Millimeter" in german.text
        assert "Kopf- und Fußzeilen" in german.text
        assert "/static/label-50x30.css" in german.text
        assert "&amp;size=60x40&amp;lang=de" in german.text
        assert "&amp;size=50x30&amp;lang=de" in german.text
        assert qr_path in german.text
        assert "PLA · Red" in german.text  # User-entered material and color are not translated.
        assert "Brand &amp; Sons &quot;EU&quot;" in german.text
        assert "<script>" not in german.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in german.text

        client.cookies.set("spoolmera_language", "en")
        cookie_choice = client.get(path, params=query, headers={"Accept-Language": "de-DE"})
        assert cookie_choice.headers["Content-Language"] == "en"
        explicit = client.get(path, params={**query, "lang": "de"}, headers={"Accept-Language": "en-US"})
        assert explicit.headers["Content-Language"] == "de"
        client.cookies.set("spoolmera_language", "de")
        explicit_english = client.get(path, params={**query, "lang": "en"}, headers={"Accept-Language": "de-DE"})
        assert explicit_english.headers["Content-Language"] == "en"
        client.cookies.set("spoolmera_language", "invalid")
        browser_choice = client.get(path, params=query, headers={"Accept-Language": "de-DE"})
        assert browser_choice.headers["Content-Language"] == "de"
        assert client.get(path, params={**query, "lang": "fr"}).status_code == 422
        assert client.get(qr_path).content == qr_before
        deep_link = client.get(f"/s/{uid}", headers={"Accept-Language": "de-DE"}, follow_redirects=False)
        assert deep_link.headers["location"] == "/?spool=" + uid
        assert client.get("/api/auth/me").status_code == 200

        with closing(TestClient(client.app)) as anonymous:
            anonymous.cookies.set("spoolmera_language", "de")
            assert anonymous.get(path, params={**query, "lang": "de"}).status_code == 401
            assert anonymous.get(qr_path).status_code == 401


def test_label_renderer_rejects_untrusted_language():
    with pytest.raises(ValueError, match="Unsupported label language"):
        labels_html([{}], language='de" onload="alert(1)')
