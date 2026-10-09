"""Read-only operational state and targeted alerts; never exposes endpoints or secrets."""
from datetime import datetime, timezone
from pathlib import Path
import shutil

from app import __version__
from app.core.settings import Settings
from app.database import session
from app.infrastructure.database.workflow_migration import material_mapping_warnings
from app.services.backup_service import metadata, now_iso
from app.services.polling_runtime import poller_snapshot

MAX_ALERTS = 500


def _age(value: str | None) -> int | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
    except ValueError:
        return None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def diagnostics(db_path: Path, settings: Settings) -> dict:
    with session(db_path) as db:
        schema_version = db.execute("PRAGMA user_version").fetchone()[0]
        values = metadata(db)
        jobs = [dict(row) for row in db.execute("SELECT status,COUNT(*) AS count FROM print_jobs GROUP BY status")]
        uncertain = db.execute("SELECT COUNT(*) FROM printer_commands WHERE state IN ('unknown','sending')").fetchone()[0]
        commands = [dict(row) for row in db.execute(
            """SELECT c.id,c.printer_id,p.name AS printer_name,c.job_id,c.action,c.state,c.created_at,c.updated_at
               FROM printer_commands c JOIN printers p ON p.id=c.printer_id
               WHERE c.state IN ('unknown','sending','acknowledged') ORDER BY c.created_at DESC LIMIT 100""")]
        printers = [dict(row) for row in db.execute(
            """SELECT p.id,p.name,p.enabled,ps.last_attempt_at,ps.last_success_at,
                      COALESCE(ps.consecutive_failures,0) AS consecutive_failures,
                      COALESCE(ps.last_error,'') AS last_error,
                      (SELECT COUNT(*) FROM print_jobs j WHERE j.printer_id=p.id
                       AND j.status IN ('pending','printing')) AS active_jobs
               FROM printers p LEFT JOIN printer_poll_state ps ON ps.printer_id=p.id ORDER BY p.id""")]
        active_tokens = db.execute("SELECT COUNT(*) FROM automation_tokens WHERE revoked_at IS NULL").fetchone()[0]
        mapping_warnings = material_mapping_warnings(db)
        operations = [dict(row) for row in db.execute(
            """SELECT o.*,p.name AS printer_name FROM printer_operations o JOIN printers p ON p.id=o.printer_id
               ORDER BY o.created_at DESC LIMIT 100""")]
    for printer in printers:
        printer["enabled"] = bool(printer["enabled"])
        age = _age(printer["last_success_at"])
        printer["observation_age_seconds"] = age
        printer["freshness"] = ("disabled" if not printer["enabled"] else "never" if age is None
                                else "stale" if age > 3 * settings.poll_interval_seconds else "current")
    free = shutil.disk_usage(db_path.parent).free
    storage = {"database_bytes": _size(db_path), "wal_bytes": _size(Path(str(db_path) + "-wal")),
               "free_bytes": free, "reserve_bytes": settings.storage_reserve_bytes,
               "low_space": free < settings.storage_reserve_bytes}
    poller = poller_snapshot(db_path, settings)
    last_error = values.get("backup_last_error") or None
    last_success = values.get("backup_last_success_at") or None
    degraded = (poller["status"] != "running" or bool(poller["last_error"])
                or not poller["lease_held"] or storage["low_space"])
    return {"version": __version__, "schema_version": schema_version,
            "status": "degraded" if degraded else "ok", "jobs": jobs,
            "uncertain_commands": uncertain, "commands": commands, "poller": poller, "printers": printers,
            "backup": {"status": "failed" if last_error else "ready" if last_success else "never",
                       "last_success_at": last_success,
                       "last_size_bytes": int(values["backup_last_size_bytes"]) if values.get("backup_last_size_bytes") else None,
                       "last_error": last_error},
            "storage": storage,
            "restore": {"last_restored_at": values.get("last_restored_at"),
                        "requires_token_reissue": values.get("restore_token_reissue_required") == "1" and active_tokens == 0},
            "slicer": {"enabled": settings.slicer_enabled, "configured": settings.slicer_configured},
            "material_mapping_warnings": mapping_warnings, "printer_operations": operations}


def active_alerts(db_path: Path) -> dict:
    alerts: list[dict] = []
    with session(db_path) as db:
        values = metadata(db)
        for row in db.execute(
            """SELECT s.id,s.uid,s.remaining_g,p.low_stock_threshold_g
               FROM spools s JOIN products p ON p.id=s.product_id
               WHERE s.archived_at IS NULL AND p.low_stock_threshold_g>0
                 AND s.remaining_g<=p.low_stock_threshold_g ORDER BY s.id LIMIT ?""", (MAX_ALERTS + 1,)):
            alerts.append({"id": "low_stock:" + row["uid"], "category": "low_stock", "severity": "warning",
                           "title": "Low filament stock", "message": f"Spool #{row['id']} has {row['remaining_g']} g remaining (threshold {row['low_stock_threshold_g']} g).",
                           "entity_type": "spool", "entity_id": str(row["id"])})
        for row in db.execute(
            """SELECT id FROM print_jobs WHERE status='needs_review' OR accounting_status='needs_review'
               ORDER BY id LIMIT ?""", (MAX_ALERTS + 1,)):
            alerts.append({"id": "job_review:" + str(row["id"]), "category": "job_review", "severity": "warning",
                           "title": "Print material needs review", "message": f"Review actual material usage for print job #{row['id']}.",
                           "entity_type": "print_job", "entity_id": str(row["id"])})
        for row in db.execute(
            """SELECT p.id FROM printers p JOIN printer_poll_state ps ON ps.printer_id=p.id
               WHERE p.enabled=1 AND ps.consecutive_failures>=3 ORDER BY p.id LIMIT ?""", (MAX_ALERTS + 1,)):
            alerts.append({"id": "printer_offline:" + str(row["id"]), "category": "printer_offline", "severity": "error",
                           "title": "Printer connection needs attention", "message": f"Printer #{row['id']} could not be observed in at least three consecutive polling attempts.",
                           "entity_type": "printer", "entity_id": str(row["id"])})
    alerts.sort(key=lambda item: item["id"])
    return {"schema_version": "1", "instance_epoch": values.get("instance_epoch", "legacy"),
            "generated_at": now_iso(), "truncated": len(alerts) > MAX_ALERTS, "alerts": alerts[:MAX_ALERTS]}
