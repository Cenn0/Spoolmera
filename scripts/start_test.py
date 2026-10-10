"""Start a separate loopback-only Docker test instance with a random setup secret."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def ensure_test_env(root: Path) -> Path:
    path = root / ".env.test"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("FILAMENT_BOOTSTRAP_TOKEN=" + secrets.token_urlsafe(32) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prebuilt", action="store_true", help="Use a Docker-loaded CI image; do not rebuild.")
    parser.add_argument("--port", type=int, default=8766, help="Loopback port, default 8766.")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port between 1024 and 65535.")
    if not shutil.which("docker"):
        print("Docker with Compose is required. Start Docker Desktop or install Docker first.", file=sys.stderr)
        return 1
    path = ensure_test_env(ROOT)
    # Keep operator credentials out of command arguments and console output.
    env = {**os.environ, "FILAMENT_TEST_PORT": str(args.port)}
    command = ["docker", "compose", "--project-name", "spoolmera-test",
               "--env-file", ".env.test", "-f", "compose.test.yaml"]
    subprocess.run([*command, "config", "--quiet"],
                   cwd=ROOT, env=env, check=True)
    subprocess.run([*command, "up", "-d",
                    "--no-build" if args.prebuilt else "--build", "--wait", "--wait-timeout", "120"],
                   cwd=ROOT, env=env, check=True)
    print(f"Test instance ready: http://127.0.0.1:{args.port}")
    print(f"First setup: copy FILAMENT_BOOTSTRAP_TOKEN from {path.name}; choose your own administrator password.")
    print("Stop: docker compose -p spoolmera-test -f compose.test.yaml down (test inventory is retained).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
