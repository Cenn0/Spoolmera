#!/usr/bin/env python3
"""Optional targeted alerts for a user-hosted ntfy endpoint, with durable deduplication.

Only new low-stock, material-review and repeated printer-connection alerts are
sent. Initial conditions form a quiet baseline. Delivery is at least once;
a crash after delivery but before state persistence can repeat one message.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

CATEGORIES = {"low_stock", "job_review", "printer_offline"}
MAX_MESSAGES_PER_CYCLE = 25


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirect())


def _secret(name: str) -> str:
    value, filename = os.environ.get(name, ""), os.environ.get(name + "_FILE", "")
    if value and filename:
        raise RuntimeError("Set only one of " + name + " and " + name + "_FILE.")
    if filename:
        with Path(filename).open("r", encoding="utf-8") as source:
            value = source.read(8193).rstrip("\r\n")
    if len(value) > 8192 or any(ord(character) < 32 for character in value):
        raise RuntimeError("Invalid secret configuration for " + name + ".")
    return value


def selected_categories() -> set[str]:
    result = {value.strip() for value in os.getenv("SPOOLMERA_NOTIFICATION_CATEGORIES", ",".join(sorted(CATEGORIES))).split(",")}
    if not result or not result <= CATEGORIES:
        raise RuntimeError("Notification categories must be low_stock, job_review or printer_offline.")
    return result


def required_environment() -> tuple[str, str, str]:
    server = os.getenv("SPOOLMERA_URL", "http://spoolmera:8765").rstrip("/")
    topic = os.getenv("SPOOLMERA_NTFY_URL", "")
    token = _secret("SPOOLMERA_AUTOMATION_TOKEN")
    for name, url in (("SPOOLMERA_URL", server), ("SPOOLMERA_NTFY_URL", topic)):
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise RuntimeError(name + " must be an HTTP(S) URL without credentials, query or fragment.")
    if not token.startswith("fmm_") or not 45 <= len(token) <= 68:
        raise RuntimeError("SPOOLMERA_AUTOMATION_TOKEN must be a scoped events_read token.")
    _secret("SPOOLMERA_NTFY_TOKEN")
    selected_categories()
    return server, topic, token


def request_alerts(server: str, token: str) -> dict:
    request = urllib.request.Request(server + "/api/automation/v1/alerts",
                                     headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    with OPENER.open(request, timeout=10) as response:
        body = response.read(512 * 1024 + 1)
    if len(body) > 512 * 1024:
        raise RuntimeError("Automation response is too large.")
    result = json.loads(body)
    if (not isinstance(result, dict) or result.get("schema_version") != "1"
            or not isinstance(result.get("instance_epoch"), str) or not result["instance_epoch"]
            or not isinstance(result.get("alerts"), list) or len(result["alerts"]) > 500):
        raise RuntimeError("Unexpected automation response.")
    if result.get("truncated") is not False:
        raise RuntimeError("Alert snapshot is incomplete; review current alerts in the application.")
    ids = set()
    for alert in result["alerts"]:
        if (not isinstance(alert, dict) or alert.get("category") not in CATEGORIES
                or not isinstance(alert.get("id"), str) or not 1 <= len(alert["id"]) <= 128
                or alert["id"] in ids or not isinstance(alert.get("title"), str)
                or not isinstance(alert.get("message"), str)):
            raise RuntimeError("Invalid alert response.")
        ids.add(alert["id"])
    return result


def notify(topic: str, alert: dict) -> None:
    payload = (alert["title"] + "\n" + alert["message"]).encode("utf-8")
    if len(payload) > 4096:
        raise RuntimeError("Notification payload is too large.")
    headers = {"Content-Type": "text/plain; charset=utf-8", "Title": "Spoolmera"}
    token = _secret("SPOOLMERA_NTFY_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(topic, data=payload, headers=headers, method="POST")
    with OPENER.open(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError("Notification endpoint rejected the alert.")


def read_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.stat().st_size > 128 * 1024:
        raise RuntimeError("Notification state is too large.")
    data = json.loads(path.read_text(encoding="utf-8"))
    # Upgrade the old movement cursor by creating a new targeted-alert baseline.
    if isinstance(data, dict) and type(data.get("cursor")) is int and data["cursor"] >= 0:
        return None
    if (not isinstance(data, dict) or data.get("version") != 2
            or not isinstance(data.get("instance_epoch"), str)
            or not isinstance(data.get("delivered_ids"), list)
            or len(data["delivered_ids"]) > 500
            or any(not isinstance(value, str) or len(value) > 128 for value in data["delivered_ids"])):
        raise RuntimeError("Invalid notification state.")
    return data


def save_state(path: Path, epoch: str, ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".notification-state-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"version": 2, "instance_epoch": epoch, "delivered_ids": sorted(ids)}, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(filename, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(filename).unlink(missing_ok=True)


def run_once(state: Path, server: str, topic: str, token: str) -> int:
    old = read_state(state)
    snapshot = request_alerts(server, token)
    categories = selected_categories()
    alerts = [alert for alert in snapshot["alerts"] if alert["category"] in categories]
    current_ids = {alert["id"] for alert in alerts}
    epoch = snapshot["instance_epoch"]
    if old is None:
        save_state(state, epoch, current_ids)
        return 0
    if epoch != old["instance_epoch"]:
        # A restore can reuse numeric row IDs. Do not silently keep an old cursor.
        notify(topic, {"title": "Database recovery detected",
                       "message": "The notification baseline was reset. Review current stock and pending print jobs in Spoolmera."})
        save_state(state, epoch, current_ids)
        return 1
    delivered = set(old["delivered_ids"]) & current_ids
    save_state(state, epoch, delivered)
    emitted = 0
    for alert in alerts:
        if alert["id"] in delivered:
            continue
        notify(topic, alert)
        delivered.add(alert["id"])
        save_state(state, epoch, delivered)
        emitted += 1
        if emitted >= MAX_MESSAGES_PER_CYCLE:
            break
    return emitted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="/state/notification-cursor.json")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if not 30 <= args.interval <= 3600:
        parser.error("Interval must be between 30 and 3600 seconds.")
    try:
        server, topic, token = required_environment()
    except (OSError, ValueError, RuntimeError):
        parser.exit(1, "Invalid notification configuration. Check endpoint URLs, categories and scoped secrets.\n")
    while True:
        try:
            count = run_once(Path(args.state), server, topic, token)
            print(f"Notification cycle successful; delivered={count}", flush=True)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, urllib.error.URLError) as exc:
            print("Notification cycle failed: " + type(exc).__name__, flush=True)
            if not args.loop:
                raise SystemExit(1) from None
        if not args.loop:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
