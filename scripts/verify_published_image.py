"""Pull a digest-pinned Spoolmera image and test it in a fresh Docker volume.

Never accepts an existing installation, volume or registry other than the project
GHCR repository. The source revision and native CPU must match before execution.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_http import DisposableClient
from http_smoke import run as http_smoke

IMAGE = re.compile(r"ghcr\.io/cenn0/spoolmera@sha256:[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
MACHINES = {"amd64": "x86_64", "arm64": "aarch64"}


def validate_metadata(metadata: dict, commit: str, architecture: str) -> str:
    config = metadata.get("Config") or {}
    labels = config.get("Labels") or {}
    if (metadata.get("Os") != "linux" or metadata.get("Architecture") != architecture
            or config.get("User") != "10001:10001"
            or labels.get("org.opencontainers.image.revision") != commit
            or labels.get("org.opencontainers.image.source") != "https://github.com/Cenn0/Spoolmera"):
        raise ValueError("Published image architecture, user or source labels do not match.")
    image_id = metadata.get("Id", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("Published image has no valid local content ID.")
    return image_id


def run(image: str, commit: str, architecture: str) -> dict:
    if not IMAGE.fullmatch(image) or not COMMIT.fullmatch(commit):
        raise ValueError("Require the project GHCR digest and a full source commit.")
    if (architecture not in MACHINES or platform.system() != "Linux"
            or platform.machine() != MACHINES[architecture]):
        raise ValueError("Published image verification requires the matching native Linux CPU.")
    environment = dict(os.environ, SPOOLMERA_BOOTSTRAP_TOKEN=secrets.token_urlsafe(32))

    def docker(*args, check=True):
        result = subprocess.run(["docker", *args], env=environment, text=True,
                                capture_output=True, timeout=300)
        if check and result.returncode:
            # Do not print Docker's command/env or container credentials.
            raise RuntimeError(f"Published image Docker operation failed ({args[0]}).")
        return result.stdout.strip()

    docker("pull", "--platform", "linux/" + architecture, image)
    metadata = json.loads(docker("image", "inspect", image))
    if not isinstance(metadata, list) or len(metadata) != 1:
        raise ValueError("Expected exactly one downloaded image.")
    image_id = validate_metadata(metadata[0], commit, architecture)
    # Execute the locally resolved content ID after validation, never a tag.
    docker("run", "--rm", "--read-only", "--network", "none", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges", "--entrypoint", "python", image_id,
           "-c", "from pathlib import Path; "
           "assert b'sm-root' in Path('/srv/spoolmera/app/ui/index.html').read_bytes(); "
           "assert all((Path('/usr/share/doc/spoolmera')/p).stat().st_size > 0 for p in "
           "['LICENSE','THIRD_PARTY_LICENSES.md','npm-licenses.txt',"
           "'python-licenses.txt','python-dependencies.json'])")
    suffix = uuid4().hex[:12]
    volume = "spoolmera-registry-check-" + suffix
    container = "spoolmera-registry-app-" + suffix
    docker("volume", "create", volume)
    try:
        docker("run", "--detach", "--name", container, "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=64m",
               "--env", "SPOOLMERA_BOOTSTRAP_TOKEN", "--mount",
               f"type=volume,source={volume},target=/data", "--publish", "127.0.0.1::8765", image_id)

        def endpoint() -> str:
            binding = docker("port", container, "8765/tcp")
            if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", binding):
                raise ValueError("Downloaded image has no unique loopback test port.")
            return "http://" + binding

        base = endpoint()
        DisposableClient(base).wait_ready()
        http_smoke(base, bootstrap_token=environment["SPOOLMERA_BOOTSTRAP_TOKEN"])
        docker("restart", container)
        base = endpoint()
        DisposableClient(base).wait_ready()
        http_smoke(base, persistence=True)
    finally:
        docker("rm", "--force", container, check=False)
        docker("volume", "rm", volume, check=False)
    return {"schema_version": 1, "image": image, "image_id": image_id,
            "commit": commit, "platform": "linux/" + architecture, "passed": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--architecture", choices=tuple(MACHINES), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.image, args.commit, args.architecture)))
