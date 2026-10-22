"""Fail-closed image scanner tests; these do not replace an actual image scan."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from scripts import scan_container as scanner


def archive_with(*members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, data, kind in members:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(data) if kind == tarfile.REGTYPE else 0
            entry.linkname = "/tmp/untrusted" if kind == tarfile.SYMTYPE else ""
            archive.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
    return stream.getvalue()


def test_binary_is_verified_before_reading_archive_and_never_extracts_paths():
    archive = archive_with(("../outside", b"untrusted", tarfile.REGTYPE),
                           ("trivy", b"verified-binary", tarfile.REGTYPE))
    digest = hashlib.sha256(archive).hexdigest()
    assert scanner.verified_binary(archive, digest) == b"verified-binary"
    with pytest.raises(ValueError, match="checksum"):
        scanner.verified_binary(archive + b"changed", digest)


@pytest.mark.parametrize("members", [[], [("trivy", b"", tarfile.SYMTYPE)],
    [("trivy", b"", tarfile.REGTYPE)],
    [("trivy", b"one", tarfile.REGTYPE), ("trivy", b"two", tarfile.REGTYPE)]])
def test_missing_duplicate_symlink_and_empty_binaries_are_rejected(members):
    archive = archive_with(*members)
    with pytest.raises(ValueError):
        scanner.verified_binary(archive, hashlib.sha256(archive).hexdigest())


def mock_scan(monkeypatch, findings, *, valid_inventory=True, fail=False):
    archive = archive_with(("trivy", b"binary", tarfile.REGTYPE))
    monkeypatch.setattr(scanner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(scanner.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(scanner.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(archive))
    monkeypatch.setattr(scanner, "verified_binary", lambda *a: b"binary")
    monkeypatch.setenv("TRIVY_IGNORE_UNFIXED", "true")
    monkeypatch.setenv("TRIVY_SEVERITY", "LOW")
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        assert not any(name.startswith("TRIVY_") for name in kwargs["env"])
        assert Path(command[command.index("--ignorefile") + 1]).read_text() == ""
        assert Path(command[command.index("--config") + 1]).read_text() == "{}\n"
        assert kwargs["check"] is True and kwargs["timeout"] == 660
        if fail:
            raise subprocess.CalledProcessError(1, command)
        path = Path(command[command.index("--output") + 1])
        if command[command.index("--format") + 1] == "json":
            document = {"SchemaVersion": 2, "Results": [
                {"Class": "os-pkgs", "Packages": [{"Name": "libc6"}] if valid_inventory else [],
                 "Vulnerabilities": findings}]}
        else:
            document = {"bomFormat": "CycloneDX", "components": [{"name": "libc6"}]}
        path.write_text(json.dumps(document))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(scanner.subprocess, "run", execute)
    return calls


@pytest.mark.parametrize("severity", ["HIGH", "CRITICAL"])
@pytest.mark.parametrize("fixed", ["", "2.0"])
def test_high_and_critical_block_with_and_without_an_available_fix(monkeypatch, tmp_path, severity, fixed):
    mock_scan(monkeypatch, [{"Severity": severity, "VulnerabilityID": "CVE-test",
                            "PkgName": "test", "InstalledVersion": "1.0", "FixedVersion": fixed}])
    with pytest.raises(ValueError, match="rejected"):
        scanner.scan("spoolmera:test", tmp_path)
    summary = json.loads((tmp_path / "scan-summary.json").read_text())
    assert summary["blocking_findings"] == 1 and summary["passed"] is False
    assert (tmp_path / "vulnerabilities.json").is_file()
    assert (tmp_path / "sbom.cdx.json").is_file()


def test_all_findings_are_retained_and_actual_sbom_is_generated(monkeypatch, tmp_path):
    calls = mock_scan(monkeypatch, [{"Severity": "MEDIUM", "VulnerabilityID": "CVE-test"}])
    scanner.scan("spoolmera:test", tmp_path)
    summary = json.loads((tmp_path / "scan-summary.json").read_text())
    assert summary["passed"] is True and summary["findings"] == 1
    assert len(calls) == 2 and "--skip-db-update" in calls[1][0]
    assert all("--ignore-unfixed" not in command for command, _ in calls)


@pytest.mark.parametrize("failure", ["scanner", "inventory"])
def test_failed_scan_cannot_leave_stale_success(monkeypatch, tmp_path, failure):
    (tmp_path / "scan-summary.json").write_text('{"passed": true}')
    mock_scan(monkeypatch, [], valid_inventory=failure != "inventory", fail=failure == "scanner")
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        scanner.scan("spoolmera:test", tmp_path)
    assert not (tmp_path / "scan-summary.json").exists()
