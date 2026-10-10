"""Exercise the notifier image on a disposable internal network, with synthetic secrets."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from uuid import uuid4


STUB = r'''
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    reads = 0
    notices = 0
    def log_message(self, *args): pass
    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == '/health': return self.reply(200, {'status': 'ok'})
        if self.path == '/stats': return self.reply(200, {'reads': Handler.reads, 'notices': Handler.notices})
        if self.path != '/api/automation/v1/alerts': return self.reply(404, {})
        if self.headers.get('Authorization') != 'Bearer '+os.environ['SPOOLMERA_AUTOMATION_TOKEN']:
            return self.reply(401, {})
        Handler.reads += 1
        alerts = [] if Handler.reads == 1 else [{'id':'low_stock:ci','category':'low_stock',
            'severity':'warning','title':'Low stock','message':'Disposable integration fixture',
            'entity_type':'spool','entity_id':'1'}]
        self.reply(200, {'schema_version':'1','instance_epoch':'ci-epoch','generated_at':'2026-01-01T00:00:00Z',
                         'truncated':False,'alerts':alerts})
    def do_POST(self):
        if self.path != '/topic': return self.reply(404, {})
        if self.headers.get('Authorization') != 'Bearer '+os.environ['SPOOLMERA_NTFY_TOKEN']:
            return self.reply(401, {})
        body = self.rfile.read(int(self.headers['Content-Length']))
        if os.environ['SPOOLMERA_AUTOMATION_TOKEN'].encode() in body: return self.reply(400,{})
        Handler.notices += 1
        self.reply(200, {'id':'test-notification'})
HTTPServer(('0.0.0.0',8768),Handler).serve_forever()
'''


def run(image: str, api_image: str) -> None:
    suffix = uuid4().hex[:12]
    network, stub, state = ("spoolmera-notify-net-" + suffix, "spoolmera-notify-stub-" + suffix,
                            "spoolmera-notify-state-" + suffix)
    notifier = "spoolmera-notify-test-" + suffix
    test_env = dict(os.environ, SPOOLMERA_AUTOMATION_TOKEN="spm_" + secrets.token_urlsafe(40),
                    SPOOLMERA_NTFY_TOKEN="ntfy-" + secrets.token_urlsafe(20),
                    SPOOLMERA_NTFY_URL="http://" + stub + ":8768/topic",
                    SPOOLMERA_URL="http://" + stub + ":8768",
                    SPOOLMERA_NOTIFICATION_CATEGORIES="low_stock,job_review,printer_offline")

    def docker(*args, check=True):
        result = subprocess.run(["docker", *args], env=test_env, text=True, capture_output=True, timeout=180)
        if check and result.returncode:
            raise RuntimeError("Notifier container check failed: " + result.stderr[-2000:])
        return result

    # Resolve the actual Compose files using a disposable .env, never the user's.
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="spoolmera-notify-compose-") as folder:
        folder = Path(folder)
        for filename in ("compose.yaml", "compose.notifications.yaml"):
            (folder / filename).write_text((root / filename).read_text(encoding="utf-8"), encoding="utf-8")
        (folder / ".env").write_text(
            "SPOOLMERA_BOOTSTRAP_TOKEN=sentinel-bootstrap-not-for-notifier\n"
            "SPOOLMERA_PRINTER_TOKEN_CI=sentinel-printer-not-for-notifier\n"
            "SPOOLMERA_CLOUD_HMAC_CI=sentinel-cloud-not-for-notifier\n"
            "SPOOLMERA_SCALE_HMAC_CI=sentinel-scale-not-for-notifier\n"
            "SPOOLMERA_SLICER_WORKER_TOKEN=sentinel-slicer-not-for-notifier\n", encoding="utf-8")
        config = docker("compose", "--project-directory", str(folder), "-f", str(folder / "compose.yaml"),
                        "-f", str(folder / "compose.notifications.yaml"), "config", "--format", "json")
        values = json.loads(config.stdout)["services"]["spoolmera-notifications"]["environment"]
        assert set(values) == {"SPOOLMERA_URL", "SPOOLMERA_AUTOMATION_TOKEN", "SPOOLMERA_NTFY_URL",
                               "SPOOLMERA_NTFY_TOKEN", "SPOOLMERA_NOTIFICATION_CATEGORIES"}
        assert not any("sentinel-" in str(value) for value in values.values())

    try:
        docker("network", "create", "--internal", network)
        docker("volume", "create", state)
        docker("run", "--detach", "--name", stub, "--network", network, "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--env", "SPOOLMERA_AUTOMATION_TOKEN", "--env", "SPOOLMERA_NTFY_TOKEN",
               api_image, "python", "-u", "-c", STUB)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = docker("exec", stub, "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8768/health',timeout=2)", check=False)
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable notification stub did not become ready.")
        for _ in range(3):
            docker("run", "--rm", "--name", notifier, "--network", network, "--read-only", "--cap-drop", "ALL",
                   "--security-opt", "no-new-privileges", "--memory", "128m", "--pids-limit", "32", "--cpus", "0.5",
                   "--tmpfs", "/tmp:rw,nosuid,size=8m", "--mount", f"type=volume,source={state},target=/state",
                   "--env", "SPOOLMERA_URL", "--env", "SPOOLMERA_AUTOMATION_TOKEN", "--env", "SPOOLMERA_NTFY_URL",
                   "--env", "SPOOLMERA_NTFY_TOKEN", "--env", "SPOOLMERA_NOTIFICATION_CATEGORIES",
                   image, "python", "-u", "notification_bridge.py")
        result = docker("exec", stub, "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8768/stats').read().decode())")
        assert json.loads(result.stdout) == {"reads": 3, "notices": 1}
        print("Notifier Docker smoke passed: explicit secret allowlist, scoped API authentication, ntfy authentication, durable deduplication.")
    finally:
        docker("rm", "-f", notifier, check=False)
        docker("rm", "-f", stub, check=False)
        docker("volume", "rm", state, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="spoolmera:notifier-ci")
    parser.add_argument("--api-image", default="spoolmera:ci")
    options = parser.parse_args()
    run(options.image, options.api_image)
