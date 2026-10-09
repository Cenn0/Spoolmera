"""Small HTTP client restricted to disposable loopback CI services."""
import http.cookiejar
import json
import secrets
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class DisposableClient:
    def __init__(self, base: str):
        self.set_base(base)
        self.csrf = ""
        self.username, self.password = "ci-recovery-admin", secrets.token_urlsafe(32)
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                         urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def set_base(self, base: str) -> None:
        """Follow a changed ephemeral host port while retaining the test session."""
        parsed = urlsplit(base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("CI smoke clients only target an explicit loopback HTTP service.")
        self.base = base.rstrip("/")

    def call(self, path: str, method: str = "GET", payload=None, *, expected: int = 200,
             headers: dict | None = None, timeout: int = 5):
        raw = isinstance(payload, bytes)
        data = payload if raw else json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                    headers={"Content-Type": "application/octet-stream" if raw else "application/json",
                             "X-CSRF-Token": self.csrf, **(headers or {})})
        try:
            response = self.client.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read(20 * 1024 * 1024)
            if response.status != expected:
                raise AssertionError(f"{path} returned HTTP {response.status}; expected {expected}.")
            return json.loads(body) if "application/json" in response.headers.get("Content-Type", "") else body

    def wait_ready(self) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if self.call("/api/ready")["status"] == "ready":
                    return
            except (OSError, urllib.error.URLError, AssertionError):
                time.sleep(0.5)
        raise RuntimeError("Disposable service did not become ready within 45 seconds.")

    def setup(self, token: str) -> None:
        if self.call("/api/auth/status") != {"needs_setup": True}:
            raise RuntimeError("Smoke test refused an already initialized instance.")
        result = self.call("/api/auth/setup", "POST", {"username": self.username, "password": self.password},
                           headers={"X-Bootstrap-Token": token})
        self.csrf = result["csrf_token"]

    def login(self) -> None:
        result = self.call("/api/auth/login", "POST", {"username": self.username, "password": self.password})
        self.csrf = result["csrf_token"]
