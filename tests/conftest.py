"""Explicit bootstrap secret for isolated authentication test instances."""
import pytest

@pytest.fixture(autouse=True)
def security_test_environment(monkeypatch):
    monkeypatch.setenv("FILAMENT_BOOTSTRAP_TOKEN", "test-only-bootstrap-token-long-enough")
    monkeypatch.setenv("FILAMENT_PRINTER_ALLOWED_IPS", "192.168.50.20,192.168.50.21")
    monkeypatch.setenv("FILAMENT_COOKIE_SECURE", "0")
    monkeypatch.setenv("FILAMENT_PRINTER_POLL_SECONDS", "300")
