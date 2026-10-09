"""Supervised in-process polling with crash-released single-host ownership."""
import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Callable
from uuid import uuid4

from app.core.settings import Settings
from app.services.backup_service import now_iso
from app.services.lease_service import claim_poll_lease, release_lease, renew_lease
from app.services.process_lock import ProcessLock, operation_lock_path

LOG = logging.getLogger(__name__)
_RUNTIMES: dict[str, "PollerRuntime"] = {}


class PollerRuntime:
    def __init__(self, db_path: Path, poll: Callable[[Path], None], settings: Settings):
        self.db_path, self.poll, self.settings = db_path, poll, settings
        self.owner = str(uuid4())
        self.lock = ProcessLock(operation_lock_path(db_path, "poll"))
        self._state_lock = threading.Lock()
        self._state = {"status": "starting", "interval_seconds": settings.poll_interval_seconds,
                       "started_at": None, "last_cycle_at": None, "last_success_at": None,
                       "last_heartbeat_at": None, "last_error": None,
                       "lease_held": False, "lease_owner": None, "lease_expires_at": None}

    def update(self, **values) -> None:
        with self._state_lock:
            self._state.update(values)

    def snapshot(self) -> dict:
        with self._state_lock:
            return dict(self._state)

    def _renewed(self) -> None:
        expires = datetime.fromtimestamp(time.time() + self.settings.poll_lease_seconds, timezone.utc)
        self.update(last_heartbeat_at=now_iso(), lease_expires_at=expires.isoformat(timespec="seconds"))

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(self.settings.poll_lease_seconds / 3)
            renewed = await asyncio.to_thread(renew_lease, self.db_path, "printer-poll", self.owner,
                                             ttl_seconds=self.settings.poll_lease_seconds)
            if not renewed:
                raise RuntimeError("Polling ownership could not be renewed.")
            self._renewed()

    async def run(self) -> None:
        _RUNTIMES[str(self.db_path.resolve())] = self
        heartbeat = None
        worker = None
        self.update(started_at=now_iso())
        try:
            while not self.lock.acquire():
                self.update(status="waiting", last_error="Another application process owns polling.")
                await asyncio.sleep(1)
            claim_poll_lease(self.db_path, self.owner, self.lock,
                             ttl_seconds=self.settings.poll_lease_seconds)
            self._renewed()
            self.update(status="running", lease_held=True, lease_owner=self.owner, last_error=None)
            heartbeat = asyncio.create_task(self._heartbeat())
            while True:
                self.update(last_cycle_at=now_iso())
                worker = asyncio.create_task(asyncio.to_thread(self.poll, self.db_path))
                done, _ = await asyncio.wait({worker, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
                if heartbeat in done:
                    await asyncio.shield(worker)
                    heartbeat.result()
                try:
                    worker.result()
                    self.update(last_success_at=now_iso(), last_error=None)
                except Exception as exc:
                    # Exception classes are sufficient here; URLs/secret values are not exposed.
                    self.update(last_error="Polling cycle failed: " + type(exc).__name__)
                    LOG.warning("Polling cycle failed: %s", type(exc).__name__)
                worker = None
                sleeper = asyncio.create_task(asyncio.sleep(self.settings.poll_interval_seconds))
                try:
                    done, _ = await asyncio.wait({sleeper, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
                    if heartbeat in done:
                        heartbeat.result()
                finally:
                    sleeper.cancel()
        except asyncio.CancelledError:
            # to_thread cancellation does not stop the thread. Keep kernel ownership
            # and renewal until that thread has actually completed its bounded I/O.
            if worker is not None and not worker.done():
                try:
                    await asyncio.shield(worker)
                except Exception:
                    pass
            self.update(status="stopped")
            raise
        except Exception as exc:
            self.update(status="failed", last_error="Polling stopped: " + type(exc).__name__)
            LOG.error("Polling stopped: %s", type(exc).__name__)
            raise
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                try:
                    await heartbeat
                except (asyncio.CancelledError, Exception):
                    pass
            try:
                if self.lock.fd is not None:
                    try:
                        release_lease(self.db_path, "printer-poll", self.owner)
                    finally:
                        self.lock.release()
            finally:
                self.update(lease_held=False, lease_owner=None, lease_expires_at=None)


def poller_snapshot(db_path: Path, settings: Settings | None = None) -> dict:
    runtime = _RUNTIMES.get(str(db_path.resolve()))
    if runtime is not None:
        return runtime.snapshot()
    return {"status": "stopped", "interval_seconds": (settings or Settings()).poll_interval_seconds,
            "started_at": None, "last_cycle_at": None, "last_success_at": None,
            "last_heartbeat_at": None, "last_error": "Polling has not started.",
            "lease_held": False, "lease_owner": None, "lease_expires_at": None}


async def run_poller(db_path: Path, poll: Callable[[Path], None], settings: Settings | None = None) -> None:
    await PollerRuntime(db_path, poll, settings or Settings.from_environment()).run()
