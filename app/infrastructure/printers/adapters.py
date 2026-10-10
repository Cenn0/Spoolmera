"""Controller-specific observations normalized to one print-job state machine."""
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol, Any

@dataclass(frozen=True)
class PrinterCapabilities:
    supports_history: bool
    supports_verified_completion: bool
    supports_file_transfer: bool = True
    supports_control: bool = True

@dataclass(frozen=True)
class Observation:
    outcome: str | None
    external_id: str | None = None
    remote_state: str | None = None

class PrinterAdapter(Protocol):
    capabilities: PrinterCapabilities
    def get_status(self, printer) -> dict: ...
    def get_history(self, printer) -> list[dict]: ...
    def observe(self, printer, job, history: list[dict], status: dict, claimed_ids: set[str]) -> Observation: ...

class MoonrakerAdapter:
    capabilities = PrinterCapabilities(supports_history=True, supports_verified_completion=True)
    def __init__(self, status, history, lookup):
        self.status_fn = status
        self.history_fn = history
        self.lookup_fn = lookup

    def get_status(self, printer):
        return self.status_fn(printer)

    def get_history(self, printer):
        return self.history_fn(printer)

    def observe(self, printer, job, history, status, claimed_ids):
        external_id = job["external_job_id"]
        matched = None
        if external_id:
            matched = next((run for run in history if run["job_id"] == external_id), None)
            if matched is None:
                try:
                    matched = self.lookup_fn(printer, external_id)
                except ValueError:
                    return Observation(None, external_id)
        else:
            created = datetime.fromisoformat(job["created_at"]).timestamp()
            candidates = [run for run in history
                          if run.get("filename") == job["file_name"]
                          and isinstance(run.get("start_time"), (int, float))
                          and run["start_time"] >= created-2
                          and run["job_id"] not in claimed_ids]
            if len(candidates) > 1:
                return Observation("needs_review")
            if candidates:
                matched = candidates[0]
        if matched is None:
            return Observation(None, external_id)
        run_id, remote_state = matched["job_id"], matched["status"]
        if remote_state == "in_progress":
            return Observation("printing", run_id, remote_state)
        if remote_state == "completed":
            success = job["observed_printing"] and job["external_job_id"] == run_id
            return Observation("completed" if success else "needs_review", run_id, remote_state)
        if remote_state in ("cancelled", "error", "klippy_shutdown", "klippy_disconnect", "interrupted"):
            return Observation("needs_review", run_id, remote_state)
        return Observation(None, run_id, remote_state)

class OctoPrintAdapter:
    capabilities = PrinterCapabilities(supports_history=False, supports_verified_completion=False)
    def __init__(self, status):
        self.status_fn = status

    def get_status(self, printer):
        return self.status_fn(printer)

    def get_history(self, printer):
        return []

    def observe(self, printer, job, history, status, claimed_ids):
        state = status["state"].lower()
        if state in ("printing", "paused") and status["filename"] == job["file_name"]:
            return Observation("printing")
        if job["observed_printing"] and state not in ("printing", "paused"):
            return Observation("needs_review")
        return Observation(None)

class BambuAdapter(OctoPrintAdapter):
    """Opt-in completion inference only for a durable, observed MQTT task ID.

    This is not firmware-signed proof or immutable print history. Missing IDs,
    mid-job reconnects and conflicting filenames always require manual review.
    """
    capabilities = PrinterCapabilities(supports_history=False, supports_verified_completion=False,
                                        supports_file_transfer=False, supports_control=True)

    def observe(self, printer, job, history, status, claimed_ids):
        state = status["state"].lower()
        same_file = bool(status["filename"]) and status["filename"] == job["file_name"]
        task_id = status.get("task_id")
        run_id = "bambu:" + task_id if isinstance(task_id, str) and task_id else None
        previously_seen = job["external_job_id"]
        if state in ("printing", "paused") and same_file:
            if run_id and run_id in claimed_ids and run_id != previously_seen:
                return Observation(None)  # an earlier registered print owns this task
            if previously_seen and previously_seen != run_id:
                return Observation("needs_review", previously_seen, state)
            return Observation("printing", run_id, state)
        if job["observed_printing"]:
            if (state == "complete" and same_file and run_id
                    and run_id == previously_seen and job.get("auto_account_bambu")):
                return Observation("completed", run_id, "completed")
            return Observation("needs_review", previously_seen, state)
        return Observation(None)


def adapter_for(kind: str, *, status: Callable, history: Callable, lookup: Callable) -> PrinterAdapter:
    if kind == "moonraker":
        return MoonrakerAdapter(status, history, lookup)
    if kind == "octoprint":
        return OctoPrintAdapter(status)
    if kind == "bambu":
        return BambuAdapter(status)
    raise ValueError("Unsupported printer controller.")
