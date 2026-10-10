"""Exercise recovery orchestration against Docker's changing published-port contract.

These checks validate the harness, not SQLite recovery or real container ownership;
the Docker job must still execute the full recovery smoke against the built image.
"""
import subprocess

import pytest

from scripts import container_restore_smoke as smoke


class DisposableDocker:
    def __init__(self, monkeypatch, *, fail_after_restart=False):
        self.port = 43000
        self.balance = 1000
        self.backup_balance = None
        self.signed_in = False
        self.commands = []
        self.targets = []
        self.clients = []
        self.bootstrap = ""
        self.fail_after_restart = fail_after_restart
        rig = self

        class Client(smoke.DisposableClient):
            def __init__(self, base):
                super().__init__(base)
                rig.clients.append(self)
                self.original_opener = self.client

            def wait_ready(self):
                assert self.base == f"http://127.0.0.1:{rig.port}", "Readiness used a stale published port"
                assert self.client is self.original_opener, "Rebinding discarded the browser session"
                rig.targets.append(self.base)
                if rig.fail_after_restart and len(rig.targets) == 2:
                    raise RuntimeError("Synthetic readiness failure after restore")

            def setup(self, token):
                assert token == rig.bootstrap
                rig.signed_in = True
                self.csrf = "synthetic-private-csrf"

            def login(self):
                rig.signed_in = True

            def call(self, path, method="GET", payload=None, *, expected=200, **kwargs):
                assert self.base == f"http://127.0.0.1:{rig.port}", "HTTP request used a stale published port"
                if path == "/api/auth/me":
                    assert expected == 401 and not rig.signed_in
                    return {}
                assert rig.signed_in
                if path == "/api/products":
                    assert method == "POST" and expected == 201
                    return {"id": 1}
                if path == "/api/spools":
                    if method == "POST":
                        rig.balance = payload["initial_g"]
                        return {"id": 1}
                    return [{"remaining_g": rig.balance}]
                if path == "/api/spools/1/movements":
                    assert method == "POST" and expected == 201
                    rig.balance -= payload["grams"]
                    return {}
                if path == "/api/admin/backup.sqlite3":
                    return b"SQLite format 3\x00synthetic test snapshot"
                raise AssertionError("Unexpected recovery request: " + path)

        monkeypatch.setattr(smoke, "DisposableClient", Client)
        monkeypatch.setattr(smoke.subprocess, "run", self.command)

    def command(self, argv, *, env, **kwargs):
        assert argv[0] == "docker"
        args = argv[1:]
        self.commands.append(args)
        self.bootstrap = env["FILAMENT_BOOTSTRAP_TOKEN"]
        output, returncode = "", 0
        if args[0] == "start" or (args[0] == "run" and "--detach" in args):
            self.port += 1
        elif args[0] == "port":
            output = f"127.0.0.1:{self.port}\n"
        elif args[0] == "inspect":
            assert args[2] == "{{json .State}}", "Diagnostics must not print Config.Env"
            output = '{"Status":"running","Running":true,"ExitCode":0}'
        elif args[0] == "logs":
            output = "Application startup complete.\n" + self.bootstrap
            if self.clients:
                output += "\n" + self.clients[0].password + "\n" + self.clients[0].csrf
        elif "scripts/backup.py" in args:
            self.backup_balance = self.balance
        elif "scripts/restore.py" in args:
            if "/data/unrelated.sqlite3" in args:
                returncode = 1
            else:
                self.balance = self.backup_balance
                self.signed_in = False
        elif args[0] == "run" and "-c" in args and "st_uid" in args[-1]:
            output = "[[10001,10001],[10001,10001]]"
        return subprocess.CompletedProcess(argv, returncode, output, "")


def test_recovery_smoke_refreshes_dynamic_port_on_every_restart(monkeypatch):
    docker = DisposableDocker(monkeypatch)
    smoke.run("spoolmera:synthetic-ci")
    assert docker.targets == [f"http://127.0.0.1:{port}" for port in range(43001, 43005)]
    assert len(docker.clients) == 1
    assert any("st_uid" in command[-1] for command in docker.commands)
    assert docker.commands[-2][0] == "rm" and docker.commands[-1][:2] == ["volume", "rm"]


def test_recovery_failure_reports_current_state_and_redacted_logs_before_cleanup(monkeypatch, capsys):
    docker = DisposableDocker(monkeypatch, fail_after_restart=True)
    with pytest.raises(RuntimeError, match="Synthetic readiness failure"):
        smoke.run("spoolmera:synthetic-ci")
    output = capsys.readouterr().err
    assert "http://127.0.0.1:43002" in output
    assert "Current port binding" in output and '"Status":"running"' in output
    assert "Application startup complete." in output and "[redacted]" in output
    assert docker.bootstrap not in output
    assert docker.clients[0].password not in output and docker.clients[0].csrf not in output
    assert docker.commands[-2][0] == "rm" and docker.commands[-1][:2] == ["volume", "rm"]
