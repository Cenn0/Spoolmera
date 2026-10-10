"""Exercise a disposable running container through its real HTTP boundary.

Never point this at an existing user instance: it creates test inventory.
"""
import argparse
import http.cookiejar
import json
import os
import urllib.error
import urllib.request

PASSWORD = "container-smoke-password-2026"


def run(base: str, persistence: bool = False) -> None:
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
    csrf = ""

    def call(path, method="GET", payload=None, expected=200, headers=None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(base + path, data=body, method=method,
            headers={"Content-Type": "application/json", "X-CSRF-Token": csrf, **(headers or {})})
        try:
            response = client.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            content = response.read()
            assert response.status == expected, (path, response.status, content)
            return json.loads(content) if "application/json" in response.headers.get("Content-Type", "") else content

    assert call("/api/health") == {"status": "ok"}
    assert b"sm-root" in call("/")
    assert b"sm-root" in call("/jobs")
    call("/api/spools", expected=401)
    if persistence:
        result = call("/api/auth/login", "POST", {"username": "container-admin", "password": PASSWORD})
        csrf = result["csrf_token"]
        assert call("/api/spools")[0]["remaining_g"] == 875
        assert len(call("/api/spools/1/movements")) == 2
        print("HTTP persistence smoke passed after restart.")
        return
    result = call("/api/auth/setup", "POST", {"username": "container-admin", "password": PASSWORD},
                  headers={"X-Bootstrap-Token": os.environ["SPOOLMERA_BOOTSTRAP_TOKEN"]})
    csrf = result["csrf_token"]
    product = call("/api/products", "POST", {"brand": "Smoke", "name": "PLA", "material": "PLA",
                   "color_name": "Blue", "color_hex": "#3377AA"}, expected=201)
    spool = call("/api/spools", "POST", {"product_id": product["id"], "initial_g": 1000}, expected=201)
    call(f"/api/spools/{spool['id']}/movements", "POST", {"kind": "consume", "grams": 125}, expected=201)
    assert call("/api/spools")[0]["remaining_g"] == 875
    assert call("/api/export/inventory.csv").startswith(b"\xef\xbb\xbf")
    call("/api/auth/logout", "POST", {})
    call("/api/spools", expected=401)
    print("HTTP container smoke passed: Angular routes, setup, inventory, ledger, CSV, logout.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--persistence", action="store_true")
    args = parser.parse_args()
    run(args.base.rstrip("/"), args.persistence)
