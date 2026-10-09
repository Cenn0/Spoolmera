"""Create a disposable Docker volume and prove offline recovery and UID preservation.

Never accepts an existing container or volume. Requires an already built image.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_http import DisposableClient


def run(image: str) -> None:
    suffix = uuid4().hex[:12]
    volume, container = "filament-recovery-" + suffix, "filament-recovery-app-" + suffix
    test_env = dict(os.environ, FILAMENT_BOOTSTRAP_TOKEN=secrets.token_urlsafe(32))

    def docker(*args, check=True):
        result = subprocess.run(["docker", *args], env=test_env, text=True,
                                capture_output=True, timeout=300)
        if check and result.returncode:
            raise RuntimeError("Disposable Docker recovery check failed: " + result.stderr[-2000:])
        return result

    def offline(*python_args, check=True):
        return docker("run", "--rm", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=64m",
                      "--user", "0:0", "--cap-drop", "ALL", "--cap-add", "CHOWN",
                      "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER", "--security-opt", "no-new-privileges",
                      "--mount", f"type=volume,source={volume},target=/data", image,
                      "python", *python_args, check=check)

    try:
        docker("volume", "create", volume)
        docker("run", "--detach", "--name", container, "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=64m",
               "--env", "FILAMENT_BOOTSTRAP_TOKEN", "--mount", f"type=volume,source={volume},target=/data",
               "--publish", "127.0.0.1::8765", image)
        address = docker("port", container, "8765/tcp").stdout.strip().splitlines()[0]
        client = DisposableClient("http://" + address)
        client.wait_ready()
        client.setup(test_env["FILAMENT_BOOTSTRAP_TOKEN"])
        product = client.call("/api/products", "POST", {"brand": "Recovery", "name": "PLA", "material": "PLA", "color_name": "Blue"}, expected=201)["id"]
        spool = client.call("/api/spools", "POST", {"product_id": product, "initial_g": 1000}, expected=201)["id"]
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 100}, expected=201)
        docker("exec", container, "python", "scripts/backup.py", "/data/ci-backup.sqlite3", "--database", "/data/filaments.sqlite3")
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 50}, expected=201)
        docker("stop", "--time", "10", container)
        offline("scripts/restore.py", "/data/ci-backup.sqlite3", "/data/filaments.sqlite3", "--confirm")
        owner = offline("-c", "import os,json; from pathlib import Path; files=[Path('/data/filaments.sqlite3'),*Path('/data').glob('.filaments.sqlite3.*.lock')]; print(json.dumps([[p.stat().st_uid,p.stat().st_gid] for p in files]))").stdout
        assert all(pair == [10001, 10001] for pair in json.loads(owner)), "Root-run restore changed database or operation-lock ownership"
        docker("start", container)
        client.wait_ready()
        client.call("/api/auth/me", expected=401)
        client.login()
        assert client.call("/api/spools")[0]["remaining_g"] == 900
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 25}, expected=201)
        assert client.call("/api/spools")[0]["remaining_g"] == 875
        assert client.call("/api/admin/backup.sqlite3").startswith(b"SQLite format 3"), "Restored lock ownership prevents online backup"
        docker("stop", "--time", "10", container)
        offline("-c", "from pathlib import Path; Path('/data/filaments.sqlite3').write_bytes(b'corrupt-recovery-fixture')")
        offline("scripts/restore.py", "/data/ci-backup.sqlite3", "/data/filaments.sqlite3", "--confirm")
        offline("-c", "from pathlib import Path; assert any(p.read_bytes()==b'corrupt-recovery-fixture' for p in Path('/data').glob('filaments.sqlite3.pre-restore-*') if not p.name.endswith('.json'))")
        offline("-c", "import sqlite3; c=sqlite3.connect('/data/unrelated.sqlite3'); c.execute('CREATE TABLE unrelated(value TEXT)'); c.close()")
        result = offline("scripts/restore.py", "/data/unrelated.sqlite3", "/data/filaments.sqlite3", "--confirm", check=False)
        assert result.returncode != 0, "Restore accepted an unrelated SQLite file"
        docker("start", container)
        client.wait_ready()
        client.login()
        assert client.call("/api/spools")[0]["remaining_g"] == 900
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 1}, expected=201)
        docker("stop", "--time", "10", container)
        offline("-c", "from pathlib import Path; Path('/data/filaments.sqlite3').unlink()")
        offline("scripts/restore.py", "/data/ci-backup.sqlite3", "/data/filaments.sqlite3", "--confirm")
        docker("start", container)
        client.wait_ready()
        client.login()
        assert client.call("/api/spools")[0]["remaining_g"] == 900
        assert client.call("/api/admin/backup.sqlite3").startswith(b"SQLite format 3")
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 1}, expected=201)
        print("Docker recovery passed: corrupt and missing destinations recover, prior bytes survive, foreign schema is rejected, sessions are revoked, UID and backup locks remain usable, new ledger writes succeed.")
    finally:
        docker("rm", "-f", container, check=False)
        docker("volume", "rm", volume, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="filament-manager:ci")
    run(parser.parse_args().image)
