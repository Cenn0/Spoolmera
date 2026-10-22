"""Scan a Docker/registry image with a checksum-pinned upstream Trivy binary.

CI-only tool; never shipped in the application. Reports stay in the caller's
output directory. Scanner/download/database failures and HIGH/CRITICAL findings
(including unfixed ones) fail the gate. This is not an independent security audit.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import urllib.request

INPUTS = Path(__file__).with_name("container_scan_inputs.json")
MAX_ARCHIVE_BYTES = 150 * 1024 * 1024
MAX_BINARY_BYTES = 512 * 1024 * 1024


def verified_binary(archive: bytes, expected_sha256: str) -> bytes:
    if hashlib.sha256(archive).hexdigest() != expected_sha256:
        raise ValueError("Scanner archive checksum mismatch.")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        members = [member for member in source.getmembers() if member.name == "trivy"]
        if len(members) != 1 or not members[0].isfile():
            raise ValueError("Scanner archive must contain exactly one regular trivy binary.")
        if not 0 < members[0].size <= MAX_BINARY_BYTES:
            raise ValueError("Scanner binary exceeds its size limit.")
        binary = source.extractfile(members[0])
        if binary is None:
            raise ValueError("Scanner binary is missing.")
        return binary.read()


def scan(image: str, output: Path, image_source: str = "docker") -> None:
    output.mkdir(parents=True, exist_ok=True)
    # A failed retry cannot leave the previous successful report as evidence.
    for name in ("vulnerabilities.json", "sbom.cdx.json", "scan-summary.json"):
        (output / name).unlink(missing_ok=True)
    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    if platform.system() != "Linux" or platform.machine() not in inputs["archives"]:
        raise ValueError("Container scanning requires Linux AMD64 or ARM64.")
    entry = inputs["archives"][platform.machine()]
    url = (f"https://github.com/aquasecurity/trivy/releases/download/v{inputs['version']}/"
           + entry["name"])
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("Scanner archive exceeds its size limit.")
    executable = verified_binary(archive, entry["sha256"])
    with tempfile.TemporaryDirectory(prefix="spoolmera-image-scan-") as work:
        root = Path(work)
        binary = root / "trivy"
        binary.write_bytes(executable)
        binary.chmod(0o700)
        config = root / "empty.yaml"
        config.write_text("{}\n", encoding="utf-8")
        ignore = root / "empty.ignore"
        ignore.touch()
        # Do not let repository config, a developer's TRIVY_* settings or an
        # ignore file silently turn off a required scanner or vulnerability.
        env = {key: value for key, value in os.environ.items() if not key.startswith("TRIVY_")}
        command = [str(binary), "image", "--config", str(config),
                   "--ignorefile", str(ignore), "--cache-dir", str(root / "cache"),
                   "--image-src", image_source, "--scanners", "vuln",
                   "--timeout", "10m", "--disable-telemetry"]
        report = output.resolve() / "vulnerabilities.json"
        # Keep every severity, including unfixed vulnerabilities, in the report.
        subprocess.run(command + ["--format", "json", "--output", str(report),
                                  "--exit-code", "0", "--", image],
                       env=env, cwd=root, check=True, timeout=660)
        document = json.loads(report.read_text(encoding="utf-8"))
        results = document.get("Results")
        if (document.get("SchemaVersion") != 2 or not isinstance(results, list)
                or not any(item.get("Class") == "os-pkgs" and item.get("Packages")
                           for item in results)):
            raise ValueError("Scanner did not produce an OS package inventory.")
        # Generate the SBOM from the same image and vulnerability database.
        subprocess.run(command + ["--skip-db-update", "--format", "cyclonedx",
                                  "--output", str(output.resolve() / "sbom.cdx.json"),
                                  "--", image], env=env, cwd=root, check=True, timeout=660)
        sbom = json.loads((output / "sbom.cdx.json").read_text(encoding="utf-8"))
        if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("components"):
            raise ValueError("Scanner did not produce a CycloneDX component inventory.")
        findings = [finding for item in results for finding in (item.get("Vulnerabilities") or [])]
        blocking = [item for item in findings if item.get("Severity") in {"HIGH", "CRITICAL"}]
        summary = {"schema_version": 1, "image": image, "scanner": "trivy",
                   "scanner_version": inputs["version"], "blocking_severities": ["HIGH", "CRITICAL"],
                   "includes_unfixed": True, "findings": len(findings),
                   "blocking_findings": len(blocking), "passed": not blocking}
        (output / "scan-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary))
        for item in blocking:
            print(f"{item['Severity']}: {item.get('VulnerabilityID')} "
                  f"{item.get('PkgName')} {item.get('InstalledVersion')} "
                  f"fixed={item.get('FixedVersion') or 'unavailable'}")
        if blocking:
            raise ValueError("Container vulnerability gate rejected HIGH/CRITICAL findings.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-source", choices=("docker", "remote"), default="docker")
    args = parser.parse_args()
    scan(args.image, args.output, args.image_source)
