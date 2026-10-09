"""Revisioned stock and explicit, append-only print-consumption decisions.

A controller observation, a physical measurement and a manual confirmation may
arrive in any order. The job's accounting decision is separate from its physical
status; changing that decision posts only the difference, linked to its previous
movement. No recorded movement or original estimate is overwritten.
"""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from app.database import session, utc_now
from app.auth import audit
from app.models import MovementInput
from app.services.accounting_models import ConsumptionInput

def record_manual_movement(db_path: Path, spool_id: int, payload: MovementInput, actor_id: int) -> dict:
    if payload.kind == "consume" and payload.grams <= 0:
        raise HTTPException(status_code=422, detail="Consumption must be greater than zero.")
    if payload.kind == "adjust" and (payload.grams == 0 or not payload.note):
        raise HTTPException(status_code=422, detail="Adjustments require a nonzero amount and an explanation.")
    delta = -payload.grams if payload.kind == "consume" else payload.grams
    with session(db_path, write=True) as db:
        spool = db.execute(
            "SELECT initial_g, remaining_g FROM spools WHERE id=? AND archived_at IS NULL",
            (spool_id,),
        ).fetchone()
        if spool is None:
            raise HTTPException(status_code=404, detail="Spool not found.")
        remaining = spool["remaining_g"] + delta
        if remaining < 0 or remaining > spool["initial_g"]:
            raise HTTPException(status_code=409,
                                detail="Movement would exceed the allowed stock range (0 to original weight).")
        db.execute(
            """UPDATE spools SET remaining_g=?, opened=CASE WHEN ? < 0 THEN 1 ELSE opened END WHERE id=?""",
            (remaining, delta, spool_id),
        )
        movement_id = db.execute(
            """INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,actor_id,source)
               VALUES(?,?,?,?,?,?,?,'manual')""",
            (spool_id, payload.kind, delta, remaining, payload.note, utc_now(), actor_id),
        ).lastrowid
        audit(db, actor_id, "movement_"+payload.kind, "movement", movement_id)
    return {"id": movement_id, "remaining_g": remaining}

def blocking_accounting_jobs(db, spool_id: int, *, excluding_job_id: int | None = None) -> list[int]:
    """Unsettled observations that an absolute measurement must not bypass."""
    return [row[0] for row in db.execute(
        """SELECT j.id FROM print_jobs j
           WHERE j.id IS NOT ? AND j.accounting_status NOT IN ('debited','discarded')
             AND (EXISTS (SELECT 1 FROM job_materials m WHERE m.job_id=j.id AND m.spool_id=?)
                  OR (j.spool_id=? AND NOT EXISTS (SELECT 1 FROM job_materials m WHERE m.job_id=j.id)))
             AND (j.observed_printing=1 OR j.status IN ('printing','needs_review')
                  OR EXISTS (SELECT 1 FROM printer_commands c WHERE c.job_id=j.id
                     AND c.action='start' AND c.state IN ('sending','acknowledged','unknown','confirmed')))
           ORDER BY j.id""",
        (excluding_job_id, spool_id, spool_id),
    )]


def assert_measurement_context(db, spool_id: int, *, excluding_job_id: int | None = None) -> None:
    blocked = blocking_accounting_jobs(db, spool_id, excluding_job_id=excluding_job_id)
    if blocked:
        raise HTTPException(409, "Reconcile the unaccounted print consumption first (jobs " +
                            ", ".join(str(job_id) for job_id in blocked) +
                            "). Use the job consumption review to confirm actual use and this measurement together.")


def record_measurement_anchor(db, spool_id: int, net: int, tare: int, actor_id: int | None,
                              note: str, *, movement_id: int | None = None,
                              operation_id: str | None = None) -> int:
    """Record every accepted absolute weight, including a zero-difference one."""
    revision = db.execute("SELECT stock_revision FROM spools WHERE id=?", (spool_id,)).fetchone()[0]
    return db.execute("""INSERT INTO stock_measurements
        (spool_id,movement_id,accounting_operation_id,stock_revision,net_g,tare_g,actor_id,note,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (spool_id, movement_id, operation_id, revision, net, tare, actor_id, note, utc_now())).lastrowid


def _job(db, job_id: int):
    row = db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Print job not found.")
    return row


def _estimates(db, job) -> dict[int, int]:
    rows = db.execute("SELECT spool_id,estimated_g FROM job_materials WHERE job_id=?",
                      (job["id"],)).fetchall()
    if not rows or sum(row["estimated_g"] for row in rows) != job["estimated_g"]:
        raise HTTPException(409, "Job material assignments do not match its original estimate. Repair the mapping before accounting.")
    estimates: dict[int, int] = {}
    for row in rows:
        estimates[row["spool_id"]] = estimates.get(row["spool_id"], 0) + row["estimated_g"]
    return estimates


def consumption_snapshot(db, job_id: int) -> dict:
    job = _job(db, job_id)
    rows = db.execute(
        """SELECT m.spool_id,s.uid AS spool_uid,p.brand,p.name AS product_name,
                  SUM(m.estimated_g) AS estimated_g,
                  COALESCE(t.accounted_g,0) AS accounted_g,t.last_movement_id,
                  t.job_id AS accounted_job_id,t.measurement_anchor_id,
                  s.initial_g,s.remaining_g,s.tare_g,s.stock_revision,s.archived_at
           FROM job_materials m JOIN spools s ON s.id=m.spool_id
           JOIN products p ON p.id=s.product_id
           LEFT JOIN job_consumption_totals t ON t.job_id=m.job_id AND t.spool_id=m.spool_id
           WHERE m.job_id=? GROUP BY m.spool_id ORDER BY m.spool_id""", (job_id,),
    ).fetchall()
    materials = []
    for row in rows:
        item = dict(row)
        item["archived"] = item.pop("archived_at") is not None
        anchor = db.execute("SELECT id,net_g,created_at FROM stock_measurements WHERE spool_id=? ORDER BY id DESC LIMIT 1",
                            (item["spool_id"],)).fetchone()
        accounted = item.pop("accounted_job_id") is not None
        baseline = item.pop("measurement_anchor_id") or 0
        item["measurement_reconciliation_required"] = bool(accounted and anchor and anchor["id"] > baseline)
        item["last_measured_g"] = anchor["net_g"] if anchor else None
        item["last_measured_at"] = anchor["created_at"] if anchor else None
        materials.append(item)
    operations = [dict(row) for row in db.execute(
        """SELECT a.id,a.mode,a.reason,a.actor_id,u.username AS actor_name,a.created_at,
                  a.accounting_revision
           FROM accounting_operations a LEFT JOIN users u ON u.id=a.actor_id
           WHERE a.job_id=? ORDER BY a.accounting_revision DESC LIMIT 30""", (job_id,),
    )]
    return {"job_id": job_id, "status": job["status"],
            "accounting_status": job["accounting_status"],
            "accounting_method": job["accounting_method"],
            "accounting_revision": job["accounting_revision"],
            "accounting_note": job["accounting_note"], "updated_at": job["updated_at"],
            "materials": materials, "operations": operations,
            "operation_id": operations[0]["id"] if operations else None, "duplicate": False}


def get_consumption(db_path: Path, job_id: int) -> dict:
    with session(db_path) as db:
        return consumption_snapshot(db, job_id)


def _payload(payload: ConsumptionInput) -> tuple[str, str]:
    values = payload.model_dump(mode="json", exclude={"request_id"})
    values["materials"] = sorted(values["materials"], key=lambda row: row["spool_id"])
    values["measurements"] = sorted(values["measurements"], key=lambda row: row["spool_id"])
    serialised = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return serialised, hashlib.sha256(serialised.encode()).hexdigest()


def _repeat_response(operation) -> dict:
    response = json.loads(operation["response_json"])
    response["duplicate"] = True
    return response


def _check_scale_measurement(db, measurement, spool, tare: int, net: int):
    if measurement.scale_event_id is None:
        return None
    receipt = db.execute("SELECT * FROM scale_event_receipts WHERE id=?",
                         (measurement.scale_event_id,)).fetchone()
    if receipt is None or receipt["spool_id"] != measurement.spool_id:
        raise HTTPException(404, "Scale measurement does not belong to this spool.")
    if receipt["status"] != "pending":
        raise HTTPException(409, "Scale measurement is already decided.")
    if (receipt["captured_stock_revision"] is None or
            receipt["captured_stock_revision"] != spool["stock_revision"] or
            receipt["captured_tare_g"] != spool["tare_g"]):
        raise HTTPException(409, "Scale measurement is stale. Capture a new measurement before reconciling.")
    effective_tare = receipt["tare_g"] if receipt["tare_g"] is not None else receipt["captured_tare_g"]
    if (receipt["gross_g"] != measurement.gross_g or effective_tare != tare or
            receipt["net_g"] != net):
        raise HTTPException(409, "Reconciliation must use the exact reviewed scale measurement.")
    return receipt


def reconcile_in_transaction(db, job_id: int, payload: ConsumptionInput,
                             actor_id: int | None, *, automatic: bool = False) -> dict:
    """Caller owns BEGIN IMMEDIATE. Validate every spool before any stock write."""
    job = _job(db, job_id)
    serialised, digest = _payload(payload)
    key = str(payload.request_id) if payload.request_id is not None else None
    if key is not None:
        previous = db.execute("SELECT * FROM accounting_operations WHERE job_id=? AND request_key=?",
                              (job_id, key)).fetchone()
        if previous is not None:
            if previous["payload_digest"] != digest:
                raise HTTPException(409, "Request ID was already used for a different accounting decision.")
            return _repeat_response(previous)
    latest = db.execute("SELECT * FROM accounting_operations WHERE job_id=? ORDER BY accounting_revision DESC LIMIT 1",
                        (job_id,)).fetchone()
    # A retry without an explicit key is safe while it repeats the latest
    # decision. Do this before freshness checks so a successful retry is usable.
    if key is None and latest is not None and latest["payload_digest"] == digest:
        return _repeat_response(latest)
    if (payload.expected_accounting_revision is not None and
            payload.expected_accounting_revision != job["accounting_revision"]):
        raise HTTPException(409, "Job accounting changed. Reload its consumption review before confirming.")
    if payload.expected_updated_at is not None and payload.expected_updated_at != job["updated_at"]:
        raise HTTPException(409, "Job state changed. Reload its consumption review before confirming.")
    if not automatic and job["status"] == "pending" and not job["observed_printing"]:
        command = db.execute("SELECT 1 FROM printer_commands WHERE job_id=? AND action='start' "
                             "AND state IN ('sending','acknowledged','unknown','confirmed')", (job_id,)).fetchone()
        if command is None:
            raise HTTPException(409, "This print has not been observed. Use Stop tracking to cancel its registration, or await a print observation before confirming use.")
    estimates = _estimates(db, job)
    desired = ({row.spool_id: row.actual_g for row in payload.materials}
               if payload.mode == "actual" else
               {spool_id: (amount if payload.mode == "estimated" else 0)
                for spool_id, amount in estimates.items()})
    if set(desired) != set(estimates):
        raise HTTPException(422, "Confirm an actual amount, including zero, for every mapped physical spool and no others.")
    if sum(desired.values()) > 100000:
        raise HTTPException(422, "Total confirmed consumption exceeds 100000 grams.")
    measurements = {row.spool_id: row for row in payload.measurements}
    if not set(measurements).issubset(desired):
        raise HTTPException(422, "A measurement must refer to a mapped physical spool.")
    changes = []
    for spool_id, quantity in desired.items():
        spool = db.execute("SELECT * FROM spools WHERE id=?", (spool_id,)).fetchone()
        total = db.execute("SELECT accounted_g,last_movement_id,measurement_anchor_id FROM job_consumption_totals WHERE job_id=? AND spool_id=?",
                           (job_id, spool_id)).fetchone()
        old_quantity = total["accounted_g"] if total else 0
        last_movement = total["last_movement_id"] if total else None
        delta = old_quantity - quantity
        if spool is None or (spool["archived_at"] is not None and (delta < 0 or spool_id in measurements)):
            raise HTTPException(409, "A mapped spool is archived. Reactivate it before recording new consumption or a measurement.")
        if quantity > spool["initial_g"]:
            raise HTTPException(409, "Confirmed consumption exceeds the registered weight of this physical spool.")
        if old_quantity > spool["initial_g"]:
            raise HTTPException(409, "Historical consumption exceeds this spool's registered weight. Review the historical mapping before correcting it.")
        anchor = db.execute("SELECT * FROM stock_measurements WHERE spool_id=? ORDER BY id DESC LIMIT 1", (spool_id,)).fetchone()
        anchor_id = anchor["id"] if anchor else None
        measured_since = bool(total and anchor and anchor_id > (total["measurement_anchor_id"] or 0))
        requires_measurement = measured_since and delta != 0
        # Reconfirming the same amount is metadata, not evidence that a later
        # stocktake occurred before this job. Keep its original ordering basis.
        basis_anchor_id = total["measurement_anchor_id"] if total is not None and delta == 0 else anchor_id
        predicted = spool["remaining_g"] + delta
        remaining = predicted
        tare = spool["tare_g"]
        measurement = measurements.get(spool_id)
        receipt = None
        measurement_delta = 0
        if requires_measurement and measurement is None:
            raise HTTPException(409, "This spool was physically weighed after the previous job decision. Include a current measurement when correcting its consumption; the earlier stocktake must not be counted twice.")
        if measurement is not None:
            if measurement.expected_stock_revision != spool["stock_revision"]:
                raise HTTPException(409, "Spool stock or tare changed since this measurement. Reload and measure again.")
            assert_measurement_context(db, spool_id, excluding_job_id=job_id)
            tare = spool["tare_g"] if measurement.tare_g is None else measurement.tare_g
            net = measurement.gross_g - tare
            if not 0 <= net <= spool["initial_g"]:
                raise HTTPException(422, "Measured net filament is outside the registered spool weight.")
            if not requires_measurement and net != predicted:
                raise HTTPException(409, "Measured net weight does not match the explicitly confirmed consumption. Review actual grams; no stock was changed.")
            receipt = _check_scale_measurement(db, measurement, spool, tare, net)
            remaining = net
            measurement_delta = net - predicted
        if not 0 <= remaining <= spool["initial_g"]:
            raise HTTPException(409, "Consumption or its correction exceeds the allowed spool stock range.")
        changes.append({"spool_id": spool_id, "quantity": quantity, "delta": delta,
                        "remaining": remaining, "tare": tare, "previous_movement": last_movement,
                        "receipt": receipt, "measurement": measurement, "measurement_delta": measurement_delta,
                        "anchor": anchor, "anchor_id": basis_anchor_id, "old_remaining": spool["remaining_g"],
                        "initial": spool["initial_g"]})
    operation_id = str(uuid4())
    revision = job["accounting_revision"] + 1
    stamp = utc_now()
    db.execute("""INSERT INTO accounting_operations
        (id,job_id,request_key,payload_digest,payload_json,mode,reason,actor_id,created_at,accounting_revision)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
               (operation_id, job_id, key, digest, serialised, payload.mode, payload.reason,
                actor_id, stamp, revision))
    first_movement = job["movement_id"]
    for change in changes:
        spool_id, quantity, delta = change["spool_id"], change["quantity"], change["delta"]
        remaining, tare = change["remaining"], change["tare"]
        previous_movement, receipt = change["previous_movement"], change["receipt"]
        movement_id = previous_movement
        measured_movement_id = None
        entries = []
        def measurement_entry(amount):
            anchor = change["anchor"]
            return {"job": False, "delta": amount, "kind": "adjust",
                    "source": "measurement_reconciliation", "parent": anchor["movement_id"],
                    "reference": "measurement:" + str(anchor["id"]),
                    "note": "Measured stock reconciled while correcting print job #" + str(job_id) + ": " + payload.reason}
        # Keep intermediate journal balances within the roll's bounds too. If
        # necessary, part of the measurement offset precedes the linked job
        # correction and the rest follows it; the entire operation is atomic.
        predicted = change["old_remaining"] + delta
        first_offset = max(0, min(change["initial"], predicted)) - predicted
        if first_offset and 0 <= change["old_remaining"] + change["measurement_delta"] <= change["initial"]:
            first_offset = change["measurement_delta"]
        if first_offset:
            entries.append(measurement_entry(first_offset))
        if delta:
            correction = previous_movement is not None
            entries.append({"job": True, "delta": delta, "kind": "adjust" if correction else "consume",
                            "source": "job_correction" if correction else "print_job",
                            "parent": previous_movement, "reference": operation_id,
                            "note": "Print job #" + str(job_id) + ": " + payload.reason})
        final_offset = change["measurement_delta"] - first_offset
        if final_offset:
            entries.append(measurement_entry(final_offset))
        ledger_remaining = change["old_remaining"]
        for entry in entries:
            ledger_remaining += entry["delta"]
            identifier = db.execute(
                """INSERT INTO movements
                   (spool_id,kind,delta_g,remaining_after_g,note,created_at,print_job_id,
                    actor_id,source,source_ref,corrects_movement_id,accounting_operation_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (spool_id, entry["kind"], entry["delta"], ledger_remaining, entry["note"], stamp,
                 job_id if entry["job"] else None, actor_id, entry["source"], entry["reference"],
                 entry["parent"], operation_id),
            ).lastrowid
            if entry["job"]:
                movement_id = identifier
                if first_movement is None:
                    first_movement = movement_id
            else:
                measured_movement_id = identifier
        db.execute("UPDATE spools SET remaining_g=?,tare_g=?, "
                   "opened=CASE WHEN ?<>0 THEN 1 ELSE opened END WHERE id=?",
                   (remaining, tare, delta, spool_id))
        db.execute("""INSERT INTO job_consumption_totals(job_id,spool_id,accounted_g,last_movement_id,measurement_anchor_id)
            VALUES(?,?,?,?,?) ON CONFLICT(job_id,spool_id) DO UPDATE
            SET accounted_g=excluded.accounted_g,last_movement_id=excluded.last_movement_id,
                measurement_anchor_id=excluded.measurement_anchor_id""",
                   (job_id, spool_id, quantity, movement_id, change["anchor_id"]))
        db.execute("UPDATE job_materials SET movement_id=? WHERE job_id=? AND spool_id=?",
                   (movement_id, job_id, spool_id))
        if change["measurement"] is not None:
            record_measurement_anchor(db, spool_id, remaining, tare, actor_id, payload.reason,
                                      movement_id=measured_movement_id, operation_id=operation_id)
        if receipt is not None:
            db.execute("UPDATE scale_event_receipts SET status='applied',reviewed_at=?,reviewed_by=?,"
                       "accounting_operation_id=?,review_note=? WHERE id=?",
                       (stamp, actor_id, operation_id, payload.reason, receipt["id"]))
            audit(db, actor_id, "scale_applied", "scale_event", receipt["id"])
    db.execute("""UPDATE print_jobs SET accounting_status=?,accounting_method=?,accounting_revision=?,
        accounting_note=?,movement_id=?,updated_at=? WHERE id=?""",
               ("discarded" if payload.mode == "discard" else "debited", payload.mode, revision,
                payload.reason, first_movement, stamp, job_id))
    db.execute("DELETE FROM job_reservations WHERE job_id=?", (job_id,))
    audit(db, actor_id, "job_consumption_" + payload.mode, "print_job", job_id)
    result = consumption_snapshot(db, job_id)
    result["operation_id"] = operation_id
    db.execute("UPDATE accounting_operations SET response_json=? WHERE id=?",
               (json.dumps(result, separators=(",", ":")), operation_id))
    return result


def reconcile_consumption(db_path: Path, job_id: int, payload: ConsumptionInput, actor_id: int) -> dict:
    with session(db_path, write=True) as db:
        return reconcile_in_transaction(db, job_id, payload, actor_id)


def apply_consumption(db, job, actor_id: int | None) -> bool:
    """Compatibility entry point for verified completion and legacy confirmation.

    A previously reconciled run can still become physically completed. Its
    accounting outcome must never be posted for a second time by the poller.
    """
    current = db.execute("SELECT * FROM print_jobs WHERE id=?", (job["id"],)).fetchone()
    if not current or current["status"] in ("completed", "cancelled"):
        return False
    if (current["accounting_status"] in ("debited", "discarded") or
            current["accounting_method"] is not None):
        if current["status"] in ("pending", "printing"):
            db.execute("UPDATE print_jobs SET status='completed',updated_at=? WHERE id=?",
                       (utc_now(), current["id"]))
        return False
    payload = ConsumptionInput(mode="estimated", reason="Confirmed print completion; original material estimate")
    try:
        reconcile_in_transaction(db, current["id"], payload, actor_id, automatic=True)
    except HTTPException as exc:
        if exc.status_code not in (409, 422):
            raise
        db.execute("UPDATE print_jobs SET status='needs_review',accounting_status='needs_review',"
                   "accounting_note=?,updated_at=? WHERE id=?",
                   (str(exc.detail), utc_now(), current["id"]))
        return False
    db.execute("UPDATE print_jobs SET status='completed',updated_at=? WHERE id=?",
               (utc_now(), current["id"]))
    return True
