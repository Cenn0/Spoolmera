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
    test_env = dict(os.environ, SPOOLMERA_BOOTSTRAP_TOKEN=secrets.token_urlsafe(32))
    client = None

    def redact(value: str) -> str:
        sensitive = [test_env["SPOOLMERA_BOOTSTRAP_TOKEN"]]
        if client is not None:
            sensitive.extend([client.password, client.csrf])
        for secret in sensitive:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value

    def docker(*args, check=True, timeout_seconds=300):
        result = subprocess.run(["docker", *args], env=test_env, text=True,
                                capture_output=True, timeout=timeout_seconds)
        if check and result.returncode:
            raise RuntimeError("Disposable Docker recovery check failed: " + redact(result.stderr)[-2000:])
        return result

    def published_base() -> str:
        # Empty HostPort is allocated by Docker when the container starts. A
        # stop/start can therefore assign a different port on the same container.
        bindings = docker("port", container, "8765/tcp").stdout.strip().splitlines()
        if len(bindings) != 1 or not bindings[0].startswith("127.0.0.1:"):
            raise RuntimeError("Disposable recovery container has no unique loopback port binding.")
        return "http://" + bindings[0]

    def restart() -> None:
        docker("start", container)
        previous_base = client.base
        client.set_base(published_base())
        print(f"Recovery restart HTTP target: {previous_base} -> {client.base}", flush=True)
        client.wait_ready()

    def diagnostics() -> None:
        print("Disposable recovery failure diagnostics:", file=sys.stderr)
        if client is not None:
            print("Last HTTP target: " + client.base, file=sys.stderr)
        for label, args in (
            ("Current port binding", ("port", container, "8765/tcp")),
            ("Container state", ("inspect", "--format", "{{json .State}}", container)),
            ("Container logs", ("logs", "--tail", "120", "--timestamps", container)),
        ):
            try:
                result = docker(*args, check=False, timeout_seconds=10)
                content = redact(result.stdout + result.stderr)[-16000:].strip()
                print(label + ":\n" + (content or "(no output)"), file=sys.stderr)
            except Exception as exc:
                # Diagnostic collection must not hide the original failed check.
                print(label + " unavailable: " + type(exc).__name__, file=sys.stderr)

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
               "--env", "SPOOLMERA_BOOTSTRAP_TOKEN", "--mount", f"type=volume,source={volume},target=/data",
               "--publish", "127.0.0.1::8765", image)
        client = DisposableClient(published_base())
        print("Recovery initial HTTP target: " + client.base, flush=True)
        client.wait_ready()
        client.setup(test_env["SPOOLMERA_BOOTSTRAP_TOKEN"])
        product = client.call("/api/products", "POST", {"brand": "Recovery", "name": "PLA", "material": "PLA", "color_name": "Blue"}, expected=201)["id"]
        spool = client.call("/api/spools", "POST", {"product_id": product, "initial_g": 1000}, expected=201)["id"]
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 100}, expected=201)
        docker("exec", container, "python", "scripts/backup.py", "/data/ci-backup.sqlite3", "--database", "/data/spoolmera.sqlite3")
        verified = json.loads(offline("scripts/verify_backup.py", "/data/ci-backup.sqlite3",
                                      "--work-dir", "/data", "--json").stdout)
        assert verified["status"] == "ok" and verified["manifest_status"] == "verified"
        assert verified["source_schema"] == verified["target_schema"] and not verified["migration_required"]
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 50}, expected=201)
        docker("stop", "--time", "10", container)
        offline("scripts/restore.py", "/data/ci-backup.sqlite3", "/data/spoolmera.sqlite3", "--confirm")
        owner = offline("-c", "import os,json; from pathlib import Path; files=[Path('/data/spoolmera.sqlite3'),*Path('/data').glob('.spoolmera.sqlite3.*.lock')]; print(json.dumps([[p.stat().st_uid,p.stat().st_gid] for p in files]))").stdout
        assert all(pair == [10001, 10001] for pair in json.loads(owner)), "Root-run restore changed database or operation-lock ownership"
        restart()
        client.call("/api/auth/me", expected=401)
        client.login()
        assert client.call("/api/spools")[0]["remaining_g"] == 900
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 25}, expected=201)
        assert client.call("/api/spools")[0]["remaining_g"] == 875
        assert client.call("/api/admin/backup.sqlite3").startswith(b"SQLite format 3"), "Restored lock ownership prevents online backup"
        docker("stop", "--time", "10", container)
        # A SQLite-valid file can still claim a current schema while missing a
        # required table. It must be rejected before the active file is touched.
        offline("-c", """
from contextlib import closing
import hashlib
from pathlib import Path
import shutil
import sqlite3
active = Path('/data/spoolmera.sqlite3')
Path('/data/ci-active.sha256').write_text(hashlib.sha256(active.read_bytes()).hexdigest())
shutil.copyfile('/data/ci-backup.sqlite3', '/data/ci-incomplete.sqlite3')
with closing(sqlite3.connect('/data/ci-incomplete.sqlite3')) as db:
    db.execute('DROP TABLE printer_operations')
    db.commit()
""")
        incomplete = offline("scripts/verify_backup.py", "/data/ci-incomplete.sqlite3",
                             "--work-dir", "/data", "--json", check=False)
        assert incomplete.returncode == 1 and json.loads(incomplete.stdout)["error"]["code"] == "schema"
        refused = offline("scripts/restore.py", "/data/ci-incomplete.sqlite3",
                          "/data/spoolmera.sqlite3", "--confirm", check=False)
        assert refused.returncode != 0, "Restore accepted an incomplete current-schema database"
        offline("-c", "from pathlib import Path; import hashlib; assert hashlib.sha256(Path('/data/spoolmera.sqlite3').read_bytes()).hexdigest() == Path('/data/ci-active.sha256').read_text()")
        offline("-c", "from pathlib import Path; Path('/data/spoolmera.sqlite3').write_bytes(b'corrupt-recovery-fixture')")
        offline("scripts/restore.py", "/data/ci-backup.sqlite3", "/data/spoolmera.sqlite3", "--confirm")
        offline("-c", "from pathlib import Path; assert any(p.read_bytes()==b'corrupt-recovery-fixture' for p in Path('/data').glob('spoolmera.sqlite3.pre-restore-*') if not p.name.endswith('.json'))")
        offline("-c", "import sqlite3; c=sqlite3.connect('/data/unrelated.sqlite3'); c.execute('CREATE TABLE unrelated(value TEXT)'); c.close()")
        result = offline("scripts/restore.py", "/data/unrelated.sqlite3", "/data/spoolmera.sqlite3", "--confirm", check=False)
        assert result.returncode != 0, "Restore accepted an unrelated SQLite file"
        restart()
        client.login()
        assert client.call("/api/spools")[0]["remaining_g"] == 900
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 1}, expected=201)
        docker("stop", "--time", "10", container)
        offline("-c", "from pathlib import Path; Path('/data/spoolmera.sqlite3').unlink()")
        offline("scripts/restore.py", "/data/ci-backup.sqlite3", "/data/spoolmera.sqlite3", "--confirm")
        restart()
        client.login()
        assert client.call("/api/spools")[0]["remaining_g"] == 900
        assert client.call("/api/admin/backup.sqlite3").startswith(b"SQLite format 3")
        client.call(f"/api/spools/{spool}/movements", "POST", {"kind": "consume", "grams": 1}, expected=201)
        docker("stop", "--time", "10", container)
        # Send a real historical fixture's source into this disposable image;
        # test fixtures remain outside the shipped application filesystem.
        fixture = Path(__file__).resolve().parent.parent / "tests" / "recovery_fixtures.py"
        offline("-c", fixture.read_text(encoding="utf-8") + """
from contextlib import closing
import hashlib
legacy = create_legacy_database('/data/ci-legacy.sqlite3', version=5)
with closing(sqlite3.connect('/data/ci-backup.sqlite3')) as saved:
    user = saved.execute('SELECT username,password_hash,role,enabled,created_at FROM users WHERE id=1').fetchone()
with closing(sqlite3.connect(legacy)) as db:
    db.execute('UPDATE users SET username=?,password_hash=?,role=?,enabled=?,created_at=? WHERE id=1', user)
    db.commit()
Path('/data/ci-legacy.sha256').write_text(hashlib.sha256(legacy.read_bytes()).hexdigest())
""")
        legacy_report = json.loads(offline("scripts/verify_backup.py", "/data/ci-legacy.sqlite3",
                                           "--work-dir", "/data", "--json").stdout)
        assert legacy_report["status"] == "ok" and legacy_report["source_schema"] == 5
        assert legacy_report["target_schema"] == verified["target_schema"]
        assert legacy_report["migration_required"] and legacy_report["manifest_status"] == "absent"
        offline("scripts/restore.py", "/data/ci-legacy.sqlite3", "/data/spoolmera.sqlite3", "--confirm")
        # Check migration and the standalone result before any API startup can
        # perform work. Then prove authentication, ledger reads and writes.
        offline("-c", """
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from app.infrastructure.database.migrations import CURRENT_SCHEMA_VERSION
with closing(sqlite3.connect('/data/spoolmera.sqlite3')) as db:
    assert db.execute('PRAGMA user_version').fetchone()[0] == CURRENT_SCHEMA_VERSION
    assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    assert db.execute('SELECT remaining_g FROM spools WHERE id=1').fetchone()[0] == 900
    assert db.execute('SELECT count(*) FROM movements').fetchone()[0] == 2
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
assert hashlib.sha256(Path('/data/ci-legacy.sqlite3').read_bytes()).hexdigest() == Path('/data/ci-legacy.sha256').read_text()
assert not list(Path('/data').glob('spoolmera-verify-*'))
""")
        restart()
        client.call("/api/auth/me", expected=401)
        client.login()
        assert client.call("/api/spools")[0]["remaining_g"] == 900
        client.call("/api/spools/1/movements", "POST", {"kind": "consume", "grams": 1}, expected=201)
        assert client.call("/api/spools")[0]["remaining_g"] == 899
        assert client.call("/api/admin/backup.sqlite3").startswith(b"SQLite format 3")
        print("Docker recovery passed: packaged backup verification, historical-schema upgrade before startup, rejected incomplete candidates, corrupt and missing targets, retained prior bytes, revoked sessions, runtime ownership, and new ledger writes.")
    except BaseException:
        diagnostics()
        raise
    finally:
        for args in (("rm", "-f", container), ("volume", "rm", volume)):
            try:
                docker(*args, check=False, timeout_seconds=20)
            except (OSError, subprocess.TimeoutExpired) as exc:
                print("Disposable recovery cleanup failed: " + type(exc).__name__, file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="spoolmera:ci")
    run(parser.parse_args().image)
