from app.infrastructure.database.migrations import CURRENT_SCHEMA_VERSION
"""Regression tests for spool UUIDs, QR labels, CSV import/export and adapters."""
import csv
import io
import sqlite3
import xml.etree.ElementTree as ET
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SCHEMA, initialize_database
from app.labels import public_base_url
from app.main import create_app
from tests.support import authenticate


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "inventory.db")) as app:
        authenticate(app)
        yield app


def product(client, **overrides):
    data = {
        "brand": "Example Filament",
        "name": "Basic",
        "material": "PLA",
        "color_name": "Black",
        "color_hex": "#131313",
        "diameter_mm": 1.75,
    }
    data.update(overrides)
    response = client.post("/api/products", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def spool(client, product_id=None, **overrides):
    data = {"product_id": product_id or product(client), "initial_g": 1000}
    data.update(overrides)
    response = client.post("/api/spools", json=data)
    assert response.status_code == 201, response.text
    return client.get("/api/spools").json()[0]


def import_file(client, data, *, dry_run=True):
    return client.post(
        f"/api/import/inventory.csv?dry_run={str(dry_run).lower()}",
        content=data, headers={"Content-Type": "text/csv"},
    )


def decode_csv(value):
    return list(csv.DictReader(io.StringIO(value.lstrip("\ufeff"))))


def to_csv(rows):
    headers = (
        "schema_version,product_uid,brand,name,material,color_name,color_hex,"
        "diameter_mm,product_notes,spool_uid,initial_g,remaining_g,opened,location,spool_notes"
    ).split(",")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_new_products_and_spools_get_stable_uuids(client):
    product_id = product(client)
    result = spool(client, product_id=product_id)
    product_uid = client.get("/api/products").json()[0]["uid"]
    assert str(UUID(product_uid)) == product_uid
    assert str(UUID(result["uid"])) == result["uid"]
    assert product_uid != result["uid"]
    first_uid = result["uid"]
    client.post(f"/api/spools/{result['id']}/movements", json={
        "kind": "consume", "grams": 15,
    })
    assert client.get("/api/spools").json()[0]["uid"] == first_uid


def test_label_qr_and_deep_link(client, monkeypatch):
    monkeypatch.setenv("SPOOLMERA_PUBLIC_BASE_URL", "http://filament.example.test:8765")
    result = spool(client)
    uid = result["uid"]
    svg_response = client.get(f"/api/spools/{uid}/qr.svg")
    assert svg_response.status_code == 200
    assert svg_response.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(svg_response.content)
    assert root.tag.endswith("svg")
    assert any(element.tag.endswith("path") for element in root.iter())

    label_response = client.get(f"/labels/{uid}")
    assert label_response.status_code == 200
    assert f"/api/spools/{uid}/qr.svg" in label_response.text
    assert "Remaining: 1000 g" in label_response.text
    assert "60 by 40 millimeter" in label_response.text
    css = client.get("/static/label.css")
    assert "@page{size:60mm 40mm" in css.text

    link = client.get(f"/s/{uid}", follow_redirects=False)
    assert link.status_code == 302
    assert link.headers["location"] == "/?spool=" + uid


def test_unknown_label_and_invalid_public_url(client, monkeypatch):
    missing = str(uuid4())
    assert client.get(f"/labels/{missing}").status_code == 404
    assert client.get(f"/api/spools/{missing}/qr.svg").status_code == 404
    assert client.get(f"/s/{missing}", follow_redirects=False).status_code == 404
    monkeypatch.setenv("SPOOLMERA_PUBLIC_BASE_URL", "https://username:password@example.com")
    with pytest.raises(ValueError, match="SPOOLMERA_PUBLIC_BASE_URL"):
        public_base_url()
    monkeypatch.setenv("SPOOLMERA_PUBLIC_BASE_URL", "https://example.test/insecure/path")
    with pytest.raises(ValueError):
        public_base_url()


def test_label_escapes_html_from_catalog(client):
    entry = spool(client, product_id=product(client, name="<script>alert(1)</script>"))
    html = client.get(f"/labels/{entry['uid']}").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_export_preserves_product_without_spools_and_uses_bom(client):
    orphan_id = product(client, name="No spools")
    other_id = product(client, name="With spool")
    created = spool(client, product_id=other_id, remaining_g=425)
    export = client.get("/api/export/inventory.csv")
    assert export.status_code == 200
    assert export.headers["content-disposition"].startswith("attachment;")
    assert export.content.startswith(b"\xef\xbb\xbf")
    rows = decode_csv(export.text)
    assert len(rows) == 2
    empty = next(row for row in rows if row["name"] == "No spools")
    full = next(row for row in rows if row["name"] == "With spool")
    assert empty["spool_uid"] == ""
    assert empty["initial_g"] == ""
    assert full["spool_uid"] == created["uid"]
    assert full["remaining_g"] == "425"
    assert full["opened"] == "true"
    assert orphan_id != other_id


def test_csv_round_trip_preview_and_idempotent_reimport(client, tmp_path):
    p = product(client)
    original = spool(client, product_id=p, remaining_g=700, location="Shelf B")
    source = client.get("/api/export/inventory.csv").content

    with TestClient(create_app(tmp_path / "target.db")) as imported:
        authenticate(imported)
        before = import_file(imported, source)
        assert before.status_code == 200
        assert before.json() == {
            "dry_run": True,
            "products_created": 1,
            "products_skipped": 0,
            "spools_created": 1,
            "spools_skipped": 0,
        }
        assert imported.get("/api/spools").json() == []
        created = import_file(imported, source, dry_run=False)
        assert created.status_code == 200
        imported_spool = imported.get("/api/spools").json()[0]
        assert imported_spool["uid"] == original["uid"]
        assert imported_spool["remaining_g"] == 700
        assert len(imported.get(f"/api/spools/{imported_spool['id']}/movements").json()) == 1

        consume = imported.post(f"/api/spools/{imported_spool['id']}/movements", json={
            "kind": "consume", "grams": 100,
        })
        assert consume.status_code == 201
        repeated = import_file(imported, source, dry_run=False)
        assert repeated.status_code == 200
        assert repeated.json()["spools_skipped"] == 1
        assert imported.get("/api/spools").json()[0]["remaining_g"] == 600
        assert len(imported.get(f"/api/spools/{imported_spool['id']}/movements").json()) == 2


def test_invalid_import_rejected_before_any_rows_are_written(client, tmp_path):
    p = product(client, name="Material 1")
    spool(client, product_id=p)
    spool(client, product_id=p, remaining_g=500)
    rows = decode_csv(client.get("/api/export/inventory.csv").text)
    rows[-1]["remaining_g"] = "1001"
    corrupted = to_csv(rows)
    with TestClient(create_app(tmp_path / "empty.db")) as target:
        authenticate(target)
        response = import_file(target, corrupted, dry_run=False)
        assert response.status_code == 422
        assert target.get("/api/products").json() == []
        assert target.get("/api/spools").json() == []


def test_duplicate_spool_uuid_in_file_is_rejected(client, tmp_path):
    spool(client)
    rows = decode_csv(client.get("/api/export/inventory.csv").text)
    data = to_csv(rows + rows)
    with TestClient(create_app(tmp_path / "target-duplicates.db")) as target:
        authenticate(target)
        rejected = import_file(target, data, dry_run=False)
        assert rejected.status_code == 422
        assert target.get("/api/products").json() == []


def test_conflicting_existing_spool_ownership_is_rejected(client):
    p1 = product(client, name="Product one")
    product(client, name="Product two")
    result = spool(client, product_id=p1)
    rows = decode_csv(client.get("/api/export/inventory.csv").text)
    target_product = next(row for row in rows if row["name"] == "Product two")
    source_row = next(row for row in rows if row["spool_uid"] == result["uid"])
    source_row["product_uid"] = target_product["product_uid"]
    source_row["name"] = target_product["name"]
    conflicted = import_file(client, to_csv(rows), dry_run=False)
    assert conflicted.status_code == 409
    assert client.get("/api/spools").json()[0]["product_id"] == p1


def test_csv_protects_spreadsheet_formulas_and_can_import_them(client, tmp_path):
    data = {
        "brand": '=HYPERLINK("https://example.invalid", "Click")',
        "name": "'=literal",
        "color_name": "@Unsafe",
    }
    p = product(client, **data)
    original = spool(client, product_id=p, location="+SUM(A1:A2)")
    rows = decode_csv(client.get("/api/export/inventory.csv").text)
    assert rows[0]["brand"].startswith("'=")
    assert rows[0]["name"].startswith("''=")
    assert rows[0]["color_name"].startswith("'@")
    assert rows[0]["location"].startswith("'+")
    with TestClient(create_app(tmp_path / "safe-import.db")) as target:
        authenticate(target)
        imported = import_file(target, to_csv(rows), dry_run=False)
        assert imported.status_code == 200
        assert target.get("/api/products").json()[0]["brand"] == data["brand"]
        assert target.get("/api/products").json()[0]["name"] == data["name"]
        assert target.get("/api/spools").json()[0]["location"] == original["location"]


def test_import_requires_csv_and_enforces_byte_and_schema_limits(client):
    assert client.post("/api/import/inventory.csv", json={}).status_code == 415
    oversized = b"a" * (2 * 1024 * 1024 + 1)
    assert import_file(client, oversized).status_code == 413
    assert import_file(client, "irrelevant,column\n1,2\n").status_code == 422
    assert import_file(client, b"\xff\xff").status_code == 422
    assert client.get("/api/products").json() == []


def test_archived_spool_not_resurrected_on_reimport(client):
    result = spool(client)
    snapshot = client.get("/api/export/inventory.csv").content
    assert client.post(f"/api/spools/{result['id']}/archive").status_code == 200
    response = import_file(client, snapshot, dry_run=False)
    assert response.status_code == 200
    assert response.json()["spools_skipped"] == 1
    assert client.get("/api/spools").json() == []
    exported = decode_csv(client.get("/api/export/inventory.csv").text)
    assert exported[0]["spool_uid"] == ""


def test_integration_contract_is_read_only_and_filters_archived(client):
    p = product(client)
    first = spool(client, product_id=p)
    product(client, name="Other filament")
    capabilities = client.get("/api/integrations/v1/capabilities").json()
    assert capabilities["schema_version"] == "1"
    assert capabilities["inventory_read"] is True
    assert capabilities["usage_write"] is False
    assert capabilities["printer_connections"] is False
    snapshot = client.get("/api/integrations/v1/spools").json()
    assert snapshot["schema_version"] == "1"
    assert len(snapshot["spools"]) == 1
    assert snapshot["spools"][0]["spool_uid"] == first["uid"]
    assert snapshot["spools"][0]["material"] == "PLA"
    assert isinstance(snapshot["spools"][0]["opened"], bool)
    client.post(f"/api/spools/{first['id']}/archive")
    assert client.get("/api/integrations/v1/spools").json()["spools"] == []


def test_upgrade_from_v1_retains_numeric_ids_stock_and_history(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute(
            """INSERT INTO products
            (id, brand, name, material, color_name, color_hex, diameter_mm, notes, created_at, updated_at)
            VALUES (5, 'OldCo', 'Classic', 'PETG', 'Gray', '#555555', 1.75, '', '2025', '2025')"""
        )
        db.execute(
            """INSERT INTO spools
            (id, product_id, initial_g, remaining_g, opened, location, notes, created_at)
            VALUES (23, 5, 1000, 450, 1, 'Shelf', '', '2025')"""
        )
        db.execute(
            """INSERT INTO movements
            (id, spool_id, kind, delta_g, remaining_after_g, note, created_at)
            VALUES (99, 23, 'consume', -550, 450, 'Old movement', '2025')"""
        )
    initialize_database(path)
    with sqlite3.connect(path) as db:
        first_product_uid = db.execute("SELECT uid FROM products WHERE id=5").fetchone()[0]
        first_spool_uid = db.execute("SELECT uid FROM spools WHERE id=23").fetchone()[0]
        assert str(UUID(first_product_uid)) == first_product_uid
        assert str(UUID(first_spool_uid)) == first_spool_uid
        assert db.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
    initialize_database(path)
    with TestClient(create_app(path)) as migrated:
        authenticate(migrated)
        assert migrated.get("/api/products").json()[0]["uid"] == first_product_uid
        spool_data = migrated.get("/api/spools").json()[0]
        assert spool_data["id"] == 23
        assert spool_data["uid"] == first_spool_uid
        assert spool_data["remaining_g"] == 450
        movement = migrated.get("/api/spools/23/movements").json()[0]
        assert movement["id"] == 99
        assert movement["note"] == "Old movement"


def test_web_page_and_user_language_are_english(client):
    response = client.get("/")
    if response.status_code == 503:
        assert "Angular frontend not built" in response.text
    else:
        assert response.status_code == 200
        assert '<html lang="en"' in response.text
        assert "<fm-root>" in response.text
        assert "Spoolmera" in response.text
        assert client.get("/spools").status_code == 200
        assert client.get("/integrations").status_code == 200
    # Angular renders translated UI copy in browser, not as static HTML.
    # Browser-level regressions verify the English navigation and dialogs.
    assert client.get("/static/label.css").status_code == 200
