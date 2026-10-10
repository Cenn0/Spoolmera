"""Targeted notification deduplication, recovery and authenticated ntfy delivery."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error

import pytest
from scripts import notification_bridge as bridge


def alert(identifier="low_stock:a", category="low_stock"):
    return {"id": identifier, "category": category, "title": "Needs attention", "message": "Check the application."}


def snapshot(items, epoch="one"):
    return {"schema_version": "1", "instance_epoch": epoch, "truncated": False, "alerts": items}


def test_quiet_baseline_then_only_new_conditions_and_recurrences(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    current = snapshot([alert()])
    sent = []
    monkeypatch.setattr(bridge, "request_alerts", lambda *_: deepcopy(current))
    monkeypatch.setattr(bridge, "notify", lambda topic, item: sent.append(item["id"]))
    assert bridge.run_once(state, "server", "topic", "token") == 0
    current["alerts"].append(alert("job_review:2", "job_review"))
    assert bridge.run_once(state, "server", "topic", "token") == 1
    assert sent == ["job_review:2"]
    current["alerts"][1]["message"] = "A different description of the same unresolved condition."
    assert bridge.run_once(state, "server", "topic", "token") == 0
    current["alerts"] = []
    bridge.run_once(state, "server", "topic", "token")
    current["alerts"] = [alert("job_review:2", "job_review")]
    assert bridge.run_once(state, "server", "topic", "token") == 1


def test_partial_delivery_retries_only_unacknowledged_alerts(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    current = snapshot([])
    monkeypatch.setattr(bridge, "request_alerts", lambda *_: deepcopy(current))
    bridge.run_once(state, "server", "topic", "token")
    current["alerts"] = [alert("low_stock:a"), alert("low_stock:b")]
    sent = []

    def notify(topic, item):
        if item["id"] == "low_stock:b":
            raise urllib.error.URLError("test delivery failure")
        sent.append(item["id"])

    monkeypatch.setattr(bridge, "notify", notify)
    with pytest.raises(urllib.error.URLError):
        bridge.run_once(state, "server", "topic", "token")
    assert bridge.read_state(state)["delivered_ids"] == ["low_stock:a"]
    monkeypatch.setattr(bridge, "notify", lambda topic, item: sent.append(item["id"]))
    assert bridge.run_once(state, "server", "topic", "token") == 1
    assert sent == ["low_stock:a", "low_stock:b"]


def test_database_restore_reports_reset_and_new_ids_are_not_skipped(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    current = snapshot([alert("job_review:99", "job_review")])
    sent = []
    monkeypatch.setattr(bridge, "request_alerts", lambda *_: deepcopy(current))
    monkeypatch.setattr(bridge, "notify", lambda topic, item: sent.append(item["title"]))
    bridge.run_once(state, "server", "topic", "token")
    current.update(snapshot([], epoch="restored"))
    assert bridge.run_once(state, "server", "topic", "token") == 1
    assert sent == ["Database recovery detected"]
    current["alerts"] = [alert("job_review:2", "job_review")]
    assert bridge.run_once(state, "server", "topic", "token") == 1
    assert len(sent) == 2


def test_category_filter_legacy_state_and_corruption(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text('{"cursor": 10000}')
    monkeypatch.setenv("SPOOLMERA_NOTIFICATION_CATEGORIES", "low_stock")
    current = snapshot([])
    monkeypatch.setattr(bridge, "request_alerts", lambda *_: deepcopy(current))
    sent = []
    monkeypatch.setattr(bridge, "notify", lambda topic, item: sent.append(item["id"]))
    bridge.run_once(state, "server", "topic", "token")
    current["alerts"] = [alert("job_review:2", "job_review"), alert("low_stock:x")]
    assert bridge.run_once(state, "server", "topic", "token") == 1
    assert sent == ["low_stock:x"]
    state.write_text('{"cursor": -1}')
    with pytest.raises(RuntimeError, match="state"):
        bridge.read_state(state)


def test_ntfy_uses_its_own_bearer_token_and_no_redirects(monkeypatch):
    monkeypatch.setenv("SPOOLMERA_NTFY_TOKEN", "ntfy-test-only-secret")
    monkeypatch.setenv("SPOOLMERA_AUTOMATION_TOKEN", "spm_application-secret-must-not-reach-ntfy")
    requests = []

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return None

    monkeypatch.setattr(bridge, "OPENER", SimpleNamespace(open=lambda req, timeout: requests.append(req) or Response()))
    bridge.notify("http://local-ntfy/topic", alert())
    assert requests[0].get_header("Authorization") == "Bearer ntfy-test-only-secret"
    assert b"application-secret" not in requests[0].data
    with pytest.raises(urllib.error.HTTPError):
        bridge.RejectRedirect().redirect_request(requests[0], None, 302, "Moved", {}, "https://elsewhere.invalid")


def test_alert_response_must_be_complete(monkeypatch):
    content = json.dumps(snapshot([]) | {"truncated": True}).encode()

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self, _): return content

    monkeypatch.setattr(bridge, "OPENER", SimpleNamespace(open=lambda *_args, **_kwargs: Response()))
    with pytest.raises(RuntimeError, match="incomplete"):
        bridge.request_alerts("http://server", "token")
