"""Registry harness regressions with a fake Docker transport, not real containers."""
import copy
import json
import subprocess

import pytest

from scripts import verify_published_image as verifier

COMMIT = "a" * 40
IMAGE = "ghcr.io/cenn0/spoolmera@sha256:" + "b" * 64
LOCAL_ID = "sha256:" + "c" * 64
METADATA = {"Id": LOCAL_ID, "Architecture": "amd64", "Os": "linux",
    "Config": {"User": "10001:10001", "Labels": {
        "org.opencontainers.image.revision": COMMIT,
        "org.opencontainers.image.source": "https://github.com/Cenn0/Spoolmera"}}}


@pytest.mark.parametrize("field,value", [("Architecture", "arm64"), ("Os", "windows"),
    ("Id", "invalid"), ("User", "0:0"), ("revision", "d" * 40),
    ("source", "https://example.org/untrusted")])
def test_rejects_incorrect_downloaded_image_before_execution(field, value):
    metadata = copy.deepcopy(METADATA)
    if field == "User":
        metadata["Config"][field] = value
    elif field in {"revision", "source"}:
        metadata["Config"]["Labels"]["org.opencontainers.image." + field] = value
    else:
        metadata[field] = value
    with pytest.raises(ValueError):
        verifier.validate_metadata(metadata, COMMIT, "amd64")


@pytest.mark.parametrize("image", ["ghcr.io/cenn0/spoolmera:main", "--help",
    "ghcr.io/other/spoolmera@sha256:" + "b" * 64])
def test_only_project_digest_is_accepted(monkeypatch, image):
    monkeypatch.setattr(verifier.subprocess, "run", lambda *a, **kw: pytest.fail("Docker must not run"))
    with pytest.raises(ValueError):
        verifier.run(image, COMMIT, "amd64")


def fake_runtime(monkeypatch, *, fail_smoke=False):
    monkeypatch.setattr(verifier.platform, "system", lambda: "Linux")
    monkeypatch.setattr(verifier.platform, "machine", lambda: "x86_64")
    calls, smokes, ready = [], [], []

    def docker(command, **kwargs):
        calls.append(command)
        assert kwargs["capture_output"] and kwargs["timeout"] == 300
        content = ""
        if command[1:3] == ["image", "inspect"]:
            content = json.dumps([METADATA])
        if command[1] == "port":
            content = "127.0.0.1:" + ("49002" if any(c[1] == "restart" for c in calls) else "49001")
        return subprocess.CompletedProcess(command, 0, content, "")

    def smoke(base, persistence=False, **kwargs):
        smokes.append((base, persistence, kwargs))
        if fail_smoke:
            raise RuntimeError("simulated HTTP failure")

    monkeypatch.setattr(verifier.subprocess, "run", docker)
    monkeypatch.setattr(verifier, "http_smoke", smoke)
    monkeypatch.setattr(verifier.DisposableClient, "wait_ready", lambda self: ready.append(self.base))
    return calls, smokes, ready


def test_registry_digest_is_inspected_and_only_validated_local_content_is_executed(monkeypatch):
    calls, smokes, ready = fake_runtime(monkeypatch)
    summary = verifier.run(IMAGE, COMMIT, "amd64")
    assert summary["passed"] and summary["image_id"] == LOCAL_ID
    assert calls[0] == ["docker", "pull", "--platform", "linux/amd64", IMAGE]
    runs = [call for call in calls if call[1] == "run"]
    assert len(runs) == 2
    assert all(LOCAL_ID in call and IMAGE not in call for call in runs)
    assert [(base, persistence) for base, persistence, _ in smokes] == [
        ("http://127.0.0.1:49001", False), ("http://127.0.0.1:49002", True)]
    assert ready == ["http://127.0.0.1:49001", "http://127.0.0.1:49002"]
    assert len(smokes[0][2]["bootstrap_token"]) >= 32
    assert calls[-2][1:3] == ["rm", "--force"] and calls[-1][1:3] == ["volume", "rm"]


def test_failure_cleans_only_its_disposable_container_and_volume(monkeypatch):
    calls, _, _ = fake_runtime(monkeypatch, fail_smoke=True)
    with pytest.raises(RuntimeError, match="HTTP failure"):
        verifier.run(IMAGE, COMMIT, "amd64")
    assert calls[-2][1:3] == ["rm", "--force"] and calls[-1][1:3] == ["volume", "rm"]
    created = next(call[-1] for call in calls if call[1:3] == ["volume", "create"])
    assert created.startswith("spoolmera-registry-check-") and calls[-1][-1] == created


def test_native_architecture_required_before_pull(monkeypatch):
    monkeypatch.setattr(verifier.platform, "system", lambda: "Linux")
    monkeypatch.setattr(verifier.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(verifier.subprocess, "run", lambda *a, **kw: pytest.fail("Docker must not run"))
    with pytest.raises(ValueError, match="native"):
        verifier.run(IMAGE, COMMIT, "amd64")
