"""Brand identity regression tests for public surfaces and deployment continuity."""
from pathlib import Path

from app.labels import label_html
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_spoolmera_branding_on_public_surfaces(tmp_path):
    app = create_app(tmp_path / "brand.sqlite3")
    assert app.title == "Spoolmera API"
    index = (ROOT / "frontend/src/index.html").read_text()
    assert "Spoolmera" in index and "spoolmera-mark.svg" in index
    login = (ROOT / "frontend/src/app/login.component.ts").read_text()
    sidebar = (ROOT / "frontend/src/app/app.component.html").read_text()
    assert "SPOOLMERA" in login and "spoolmera-mark.svg" in login
    assert "SPOOLMERA" in sidebar and "spoolmera-mark.svg" in sidebar
    assert "Spoolmera" not in index + login + sidebar


def test_labels_are_branded_in_both_languages():
    spool = {"uid": "4d24bf09-8d33-428a-8538-701234567890", "name": "Test",
             "brand": "Sample", "material": "PLA", "color_name": "Black",
             "remaining_g": 200, "id": 1}
    for language in ("en", "de"):
        markup = label_html(spool, language=language)
        assert "SPOOLMERA" in markup
        assert "Spoolmera" not in markup


def test_existing_deployment_settings_are_preserved():
    compose = (ROOT / "compose.yaml").read_text()
    assert "name: filamentmanager" in compose
    assert "filament_data:/data" in compose
    assert "FILAMENT_DB_PATH" in compose


def test_dynamic_document_title_is_branded():
    service = (ROOT / 'frontend/src/app/core/i18n/i18n.service.ts').read_text()
    assert "this.t('Spoolmera · Material inventory')" in service
    operations = (ROOT / 'frontend/src/app/features/operations/operations.component.html').read_text()
    assert 'Spoolmera' in operations


def test_route_titles_use_spoolmera():
    routes = (ROOT / 'frontend/src/app/app.routes.ts').read_text()
    assert 'Filament Manager' not in routes
    assert 'Spoolmera' in routes
