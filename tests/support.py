"""Test-only first-admin bootstrap; production does not have a test bypass."""
from fastapi.testclient import TestClient

PASSWORD = "test-admin-password-strong-2026"
BOOTSTRAP = "test-only-bootstrap-token-long-enough"

def authenticate(client: TestClient) -> TestClient:
    response = client.post("/api/auth/setup", json={"username":"testadmin","password":PASSWORD},
                           headers={"X-Bootstrap-Token":BOOTSTRAP})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client
