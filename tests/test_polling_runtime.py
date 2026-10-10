"""The real scheduler owns polling until its thread finishes, and survives process crashes."""
import asyncio
import os
from pathlib import Path
import select
import subprocess
import sys
import threading

from fastapi.testclient import TestClient
import pytest

from app.core.settings import ConfigurationError, Settings
from app.database import initialize_database, session
from app.main import create_app
from app.services.lease_service import claim_poll_lease
from app.services.polling_runtime import PollerRuntime
from app.services.process_lock import ProcessLock, operation_lock_path


@pytest.mark.parametrize("setting,value", [
    ("SPOOLMERA_PRINTER_POLL_SECONDS", "abc"), ("SPOOLMERA_PRINTER_POLL_SECONDS", "301"),
    ("SPOOLMERA_COOKIE_SECURE", "yes"), ("SPOOLMERA_PUBLIC_BASE_URL", "https://host/path"),
])
def test_invalid_configuration_fails_before_serving(tmp_path, monkeypatch, setting, value):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ConfigurationError):
        with TestClient(create_app(tmp_path / "database.sqlite3")):
            pytest.fail("The application accepted malformed operator configuration.")


def test_second_application_lifespan_cannot_initialize_an_active_database(tmp_path):
    path = tmp_path / "database.sqlite3"
    with TestClient(create_app(path)) as first:
        with pytest.raises(RuntimeError, match="already used"):
            with TestClient(create_app(path)):
                pytest.fail("Two application lifespans acquired the same database")
        assert first.get("/api/health").status_code == 200
    with TestClient(create_app(path)) as replacement:
        assert replacement.get("/api/health").status_code == 200


@pytest.mark.skipif(os.name != "posix", reason="Docker's Linux kernel ownership is tested here")
def test_hard_crash_releases_kernel_lock_without_waiting_for_old_sqlite_lease(tmp_path):
    path = tmp_path / "database.sqlite3"
    initialize_database(path)
    program = """
import sys
from pathlib import Path
from app.services.process_lock import ProcessLock, operation_lock_path
from app.services.lease_service import claim_poll_lease
database = Path(sys.argv[1])
lock = ProcessLock(operation_lock_path(database, 'poll'))
assert lock.acquire()
claim_poll_lease(database, 'killed-process', lock, ttl_seconds=1800)
print('owned', flush=True)
sys.stdin.readline()
"""
    child = subprocess.Popen([sys.executable, "-c", program, str(path)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             cwd=Path(__file__).resolve().parents[1])
    contender = ProcessLock(operation_lock_path(path, "poll"))
    try:
        assert select.select([child.stdout], [], [], 5)[0], "Child did not acquire polling ownership"
        assert child.stdout.readline().strip() == "owned"
        assert not contender.acquire()
        child.kill()
        child.wait(timeout=5)
        assert contender.acquire()
        claim_poll_lease(path, "replacement-process", contender, ttl_seconds=30)
        with session(path) as db:
            assert db.execute("SELECT owner FROM worker_leases WHERE name='printer-poll'").fetchone()[0] == "replacement-process"
    finally:
        contender.release()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_cancellation_keeps_ownership_until_poll_thread_exits(tmp_path):
    path = tmp_path / "database.sqlite3"
    initialize_database(path)
    started, finish = threading.Event(), threading.Event()

    def work(database):
        started.set()
        assert finish.wait(5)

    async def exercise():
        runtime = PollerRuntime(path, work, Settings(poll_interval_seconds=10))
        task = asyncio.create_task(runtime.run())
        other = ProcessLock(operation_lock_path(path, "poll"))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not other.acquire(), "Cancelled asyncio task released a still-running thread's ownership"
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert other.acquire()
        finally:
            finish.set()
            other.release()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())
