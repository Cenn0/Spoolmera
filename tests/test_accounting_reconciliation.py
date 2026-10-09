"""Cross-workflow stock invariants: measurements, print completion and corrections."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import initialize_database, session
from app.infrastructure.database.accounting_migration import migrate_accounting
from app.main import create_app
from app.services.accounting_models import ConsumptionInput
from app.services.accounting_service import apply_consumption, reconcile_consumption
from tests.support import authenticate


@pytest.fixture
def workshop(tmp_path, monkeypatch):
    async def idle_poller(*_):
        await asyncio.Event().wait()
    monkeypatch.setattr("app.main.poll_worker", idle_poller)
    path = tmp_path / "accounting.sqlite3"
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post("/api/products", json={"brand": "Workshop", "name": "PLA",
                                                     "material": "PLA", "color_name": "Blue"})
        assert product.status_code == 201, product.text
        spool_ids = []
        for _ in range(2):
            spool = client.post("/api/spools", json={"product_id": product.json()["id"], "initial_g": 1000})
            assert spool.status_code == 201, spool.text
            spool_ids.append(spool.json()["id"])
        printer = client.post("/api/printers", json={"name": "Accounting printer", "kind": "moonraker",
                                                   "base_url": "http://192.168.50.20:7125"})
        assert printer.status_code == 201, printer.text
        yield client, path, spool_ids, printer.json()["id"]


def job_for(workshop, grams=100, name="part.gcode", materials=None):
    client, _, spools, printer = workshop
    payload = {"printer_id": printer, "file_name": name}
    if materials is None:
        payload.update(spool_id=spools[0], estimated_g=grams)
        result = client.post("/api/jobs", json=payload)
    else:
        payload["materials"] = materials
        result = client.post("/api/jobs/multi", json=payload)
    assert result.status_code == 201, result.text
    return result.json()["id"]


def observed(workshop, job_id, status="needs_review"):
    with session(workshop[1], write=True) as db:
        db.execute("UPDATE print_jobs SET status=?,observed_printing=1,accounting_status='needs_review' WHERE id=?",
                   (status, job_id))


def spool_state(workshop, spool_id=None):
    with session(workshop[1]) as db:
        return dict(db.execute("SELECT * FROM spools WHERE id=?", (spool_id or workshop[2][0],)).fetchone())


def confirm(workshop, job_id, grams, **extra):
    payload = {"mode": "actual", "materials": [{"spool_id": workshop[2][0], "actual_g": grams}],
               "reason": "Verified actual filament use", **extra}
    return workshop[0].post(f"/api/jobs/{job_id}/consumption", json=payload)


def ledger(workshop, job_id):
    with session(workshop[1]) as db:
        return [dict(row) for row in db.execute("SELECT * FROM movements WHERE print_job_id=? ORDER BY id", (job_id,))]


def remote_run(workshop, monkeypatch, filename="part.gcode"):
    current = {"job_id": "accounting-run", "filename": filename,
               "start_time": time.time() + 2, "status": "in_progress"}
    def fetch(_, route):
        if route.startswith("/server/history/list"):
            return {"result": {"jobs": [dict(current)]}}
        return {"result": {"status": {"print_stats": {
            "state": "printing" if current["status"] == "in_progress" else "complete", "filename": filename}}}}
    monkeypatch.setattr("app.printers.fetch_json", fetch)
    first = workshop[0].post(f"/api/printers/{workshop[3]}/poll")
    assert first.status_code == 200, first.text
    return current


def scale_receipt(workshop, monkeypatch, gross, *, name=None, tare=None, measured_at=None,
                  expected_status=200):
    secret = "scale-review-secret-with-more-than-thirty-two-bytes"
    monkeypatch.setenv("FILAMENT_SCALE_HMAC_WORKSHOP", secret)
    payload = {"event_id": name or "measurement-" + str(uuid4()),
               "spool_uid": spool_state(workshop)["uid"], "gross_g": gross, "tare_g": tare}
    if measured_at is not None:
        payload["measured_at"] = measured_at
    raw = json.dumps(payload).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    result = workshop[0].post("/api/scales/hooks/WORKSHOP", content=raw,
                             headers={"X-Filament-Timestamp": stamp, "X-Filament-Signature": signature})
    assert result.status_code == expected_status, result.text
    return result.json()["id"] if expected_status == 200 else result


def test_every_stock_and_tare_change_advances_revision_in_its_transaction(workshop):
    client, _, spools, _ = workshop
    sid = spools[0]
    assert spool_state(workshop)["stock_revision"] == 0
    assert client.post(f"/api/spools/{sid}/movements", json={"kind": "consume", "grams": 20}).status_code == 201
    assert spool_state(workshop)["stock_revision"] == 1
    assert client.patch(f"/api/spools/{sid}", json={"tare_g": 200}).status_code == 200
    assert spool_state(workshop)["stock_revision"] == 2
    assert client.patch(f"/api/spools/{sid}", json={"tare_g": 200, "notes": "Metadata only"}).status_code == 200
    assert spool_state(workshop)["stock_revision"] == 2
    stale = client.post(f"/api/spools/{sid}/weigh", json={"gross_g": 1100, "expected_stock_revision": 1})
    assert stale.status_code == 409
    assert spool_state(workshop)["remaining_g"] == 980
    weighed = client.post(f"/api/spools/{sid}/weigh", json={"gross_g": 1100, "expected_stock_revision": 2})
    assert weighed.status_code == 200, weighed.text
    assert (spool_state(workshop)["remaining_g"], spool_state(workshop)["stock_revision"]) == (900, 3)


def test_cancelled_job_can_record_partial_or_explicit_zero_without_changing_physical_status(workshop):
    jid = job_for(workshop, 200)
    observed(workshop, jid, "cancelled")
    result = confirm(workshop, jid, 37, expected_accounting_revision=0)
    assert result.status_code == 200, result.text
    result = result.json()
    assert result["status"] == "cancelled"
    assert (result["accounting_status"], result["accounting_method"]) == ("debited", "actual")
    assert result["materials"][0]["estimated_g"] == 200
    assert result["materials"][0]["accounted_g"] == 37
    assert spool_state(workshop)["remaining_g"] == 963
    zero = confirm(workshop, jid, 0, expected_accounting_revision=1, reason="Confirmed no filament use; correcting the prior estimate")
    assert zero.status_code == 200, zero.text
    assert spool_state(workshop)["remaining_g"] == 1000
    rows = ledger(workshop, jid)
    assert [row["delta_g"] for row in rows] == [-37, 37]
    assert rows[1]["corrects_movement_id"] == rows[0]["id"]
    assert rows[1]["actor_id"] == 1 and rows[1]["source"] == "job_correction"
    assert zero.json()["status"] == "cancelled"
    assert zero.json()["accounting_method"] == "actual"


def test_multitool_actuals_aggregate_by_physical_spool_and_correct_atomically(workshop):
    client, _, spools, _ = workshop
    jid = job_for(workshop, materials=[{"tool": 0, "spool_id": spools[0], "estimated_g": 100},
                                     {"tool": 2, "spool_id": spools[0], "estimated_g": 20},
                                     {"tool": 3, "spool_id": spools[1], "estimated_g": 80}])
    observed(workshop, jid)
    route = f"/api/jobs/{jid}/consumption"
    first = client.post(route, json={"mode": "actual", "reason": "Partial print, verified both rolls",
        "materials": [{"spool_id": spools[0], "actual_g": 37}, {"spool_id": spools[1], "actual_g": 15}]})
    assert first.status_code == 200, first.text
    assert [row["estimated_g"] for row in first.json()["materials"]] == [120, 80]
    before = ledger(workshop, jid)
    correction = client.post(route, json={"mode": "actual", "reason": "Corrected measured amounts after checking both rolls",
        "expected_accounting_revision": 1,
        "materials": [{"spool_id": spools[0], "actual_g": 10}, {"spool_id": spools[1], "actual_g": 30}]})
    assert correction.status_code == 200, correction.text
    assert [spool_state(workshop, sid)["remaining_g"] for sid in spools] == [990, 970]
    rows = ledger(workshop, jid)
    assert rows[:2] == before  # Original postings remain immutable.
    assert [row["delta_g"] for row in rows[2:]] == [27, -15]
    assert {row["corrects_movement_id"] for row in rows[2:]} == {row["id"] for row in before}
    failed = client.post(route, json={"mode": "actual", "reason": "Invalid overdraw must roll back every spool",
        "materials": [{"spool_id": spools[0], "actual_g": 200}, {"spool_id": spools[1], "actual_g": 2000}]})
    assert failed.status_code == 409
    assert ledger(workshop, jid) == rows
    assert [spool_state(workshop, sid)["remaining_g"] for sid in spools] == [990, 970]


def test_actual_requires_each_spool_once_and_explicit_zero(workshop):
    client, _, spools, _ = workshop
    jid = job_for(workshop, materials=[{"tool": 0, "spool_id": spools[0], "estimated_g": 100},
                                     {"tool": 1, "spool_id": spools[1], "estimated_g": 100}])
    observed(workshop, jid)
    assert confirm(workshop, jid, 37).status_code == 422
    duplicate = client.post(f"/api/jobs/{jid}/consumption", json={"mode": "actual", "reason": "Duplicate spool test",
        "materials": [{"spool_id": spools[0], "actual_g": 37}, {"spool_id": spools[0], "actual_g": 0}]})
    assert duplicate.status_code == 422
    assert ledger(workshop, jid) == []


def test_unobserved_registration_cannot_be_accounted_and_then_started(workshop):
    jid = job_for(workshop)
    for mode in ("actual", "estimated", "discard"):
        payload = {"mode": mode, "reason": "No physical observation yet",
                   "materials": [{"spool_id": workshop[2][0], "actual_g": 0}] if mode == "actual" else []}
        result = workshop[0].post(f"/api/jobs/{jid}/consumption", json=payload)
        assert result.status_code == 409
    assert spool_state(workshop)["remaining_g"] == 1000


def test_explicit_zero_has_a_decision_without_a_fake_movement_and_can_be_corrected(workshop):
    jid = job_for(workshop)
    observed(workshop, jid, "cancelled")
    first = confirm(workshop, jid, 0)
    assert first.status_code == 200 and first.json()["accounting_method"] == "actual"
    assert ledger(workshop, jid) == []
    changed = confirm(workshop, jid, 37, expected_accounting_revision=1,
                      reason="Found and measured the failed print's used material")
    assert changed.status_code == 200, changed.text
    assert [row["delta_g"] for row in ledger(workshop, jid)] == [-37]
    assert spool_state(workshop)["remaining_g"] == 963


def test_parallel_repeated_correction_has_one_effect_and_survives_restart(workshop):
    client, path, _, _ = workshop
    jid = job_for(workshop)
    observed(workshop, jid)
    with session(path, write=True) as db:
        assert apply_consumption(db, {"id": jid}, None)
    request_id = str(uuid4())
    def change(_):
        return confirm(workshop, jid, 37, request_id=request_id, expected_accounting_revision=1)
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(change, range(2)))
    assert [result.status_code for result in responses] == [200, 200]
    assert sum(result.json()["duplicate"] for result in responses) == 1
    rows = ledger(workshop, jid)
    assert [row["delta_g"] for row in rows] == [-100, 63]
    assert rows[0]["actor_id"] is None and rows[1]["actor_id"] == 1
    initialize_database(path)
    retry = change(None)
    assert retry.status_code == 200 and retry.json()["duplicate"]
    assert ledger(workshop, jid) == rows
    assert spool_state(workshop)["remaining_g"] == 963
    reused = confirm(workshop, jid, 42, request_id=request_id, expected_accounting_revision=1)
    assert reused.status_code == 409


def test_stale_accounting_revision_does_not_override_another_review(workshop):
    jid = job_for(workshop)
    observed(workshop, jid)
    assert confirm(workshop, jid, 37, expected_accounting_revision=0).status_code == 200
    stale = confirm(workshop, jid, 42, expected_accounting_revision=0)
    assert stale.status_code == 409
    assert spool_state(workshop)["remaining_g"] == 963


def test_weighing_before_completion_requires_atomic_job_reconciliation(workshop, monkeypatch):
    client, _, spools, printer = workshop
    jid = job_for(workshop)
    run = remote_run(workshop, monkeypatch)
    run["status"] = "completed"
    ordinary = client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 900, "tare_g": 0})
    assert ordinary.status_code == 409 and "Reconcile" in ordinary.json()["detail"]
    assert spool_state(workshop)["remaining_g"] == 1000
    reconciled = confirm(workshop, jid, 100, expected_accounting_revision=0, measurements=[{
        "spool_id": spools[0], "gross_g": 900, "tare_g": 0, "expected_stock_revision": 0}])
    assert reconciled.status_code == 200, reconciled.text
    assert spool_state(workshop)["remaining_g"] == 900
    assert client.post(f"/api/printers/{printer}/poll").status_code == 200
    snapshot = client.get(f"/api/jobs/{jid}/consumption").json()
    assert (snapshot["status"], snapshot["accounting_method"]) == ("completed", "actual")
    assert spool_state(workshop)["remaining_g"] == 900
    assert len(ledger(workshop, jid)) == 1


def test_completion_before_weighing_reaches_same_balance(workshop, monkeypatch):
    client, _, spools, printer = workshop
    jid = job_for(workshop)
    run = remote_run(workshop, monkeypatch)
    run["status"] = "completed"
    assert client.post(f"/api/printers/{printer}/poll").status_code == 200
    weighed = client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 900, "expected_stock_revision": 1})
    assert weighed.status_code == 200 and weighed.json()["difference_g"] == 0
    assert spool_state(workshop)["remaining_g"] == 900
    assert len(ledger(workshop, jid)) == 1


@pytest.mark.parametrize("completion_first", [False, True])
def test_actual_different_from_estimate_remains_correct_on_both_sides_of_absolute_stocktake(workshop, monkeypatch, completion_first):
    client, path, spools, printer = workshop
    jid = job_for(workshop, 100)
    remote = remote_run(workshop, monkeypatch)
    remote["status"] = "completed"
    if completion_first:
        assert client.post(f"/api/printers/{printer}/poll").status_code == 200
        assert spool_state(workshop)["remaining_g"] == 900
        weighed = client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 963, "expected_stock_revision": 1})
        assert weighed.status_code == 200, weighed.text
        assert confirm(workshop, jid, 37).status_code == 409  # Do not refund the same 63 g twice.
        snapshot = client.get(f"/api/jobs/{jid}/consumption").json()
        assert snapshot["materials"][0]["measurement_reconciliation_required"]
    else:
        assert client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 963}).status_code == 409
    revision = spool_state(workshop)["stock_revision"]
    request_id = str(uuid4())
    def reconcile():
        return confirm(workshop, jid, 37, request_id=request_id, measurements=[{
            "spool_id": spools[0], "gross_g": 963, "expected_stock_revision": revision}])
    result = reconcile()
    assert result.status_code == 200, result.text
    assert reconcile().json()["duplicate"]
    assert client.post(f"/api/printers/{printer}/poll").status_code == 200
    assert spool_state(workshop)["remaining_g"] == 963
    assert -sum(row["delta_g"] for row in ledger(workshop, jid)) == 37
    with session(path) as db:
        assert db.execute("SELECT SUM(delta_g) FROM movements WHERE spool_id=?", (spools[0],)).fetchone()[0] == 963
        assert db.execute("SELECT estimated_g FROM print_jobs WHERE id=?", (jid,)).fetchone()[0] == 100
        if completion_first:
            offset = db.execute("SELECT * FROM movements WHERE source='measurement_reconciliation'").fetchone()
            measured = db.execute("SELECT id FROM movements WHERE source='weighing'").fetchone()
            assert offset["delta_g"] == -63 and offset["corrects_movement_id"] == measured["id"]
            assert offset["print_job_id"] is None and offset["accounting_operation_id"] == result.json()["operation_id"]


def test_job_history_includes_measurement_reconciliation_without_counting_it_as_print_consumption(workshop):
    client, _, spools, _ = workshop
    jid = job_for(workshop, 100)
    observed(workshop, jid)
    estimated = client.post(f"/api/jobs/{jid}/consumption", json={
        "mode": "estimated", "reason": "Initially confirmed the original 100 g estimate"})
    assert estimated.status_code == 200, estimated.text
    weighed = client.post(f"/api/spools/{spools[0]}/weigh", json={
        "gross_g": 963, "expected_stock_revision": 1})
    assert weighed.status_code == 200, weighed.text
    measurement_history = client.get("/api/movements/page", params={"spool_id": spools[0], "source": "weighing"})
    assert measurement_history.status_code == 200, measurement_history.text
    measurement_id = measurement_history.json()["items"][0]["id"]
    corrected = confirm(workshop, jid, 37, measurements=[{
        "spool_id": spools[0], "gross_g": 963, "expected_stock_revision": 2}])
    assert corrected.status_code == 200, corrected.text

    # A filtered, paginated API result must contain both sides of the review,
    # including the measurement offset linked through its accounting operation.
    first = client.get("/api/movements/page", params={"job_id": jid, "limit": 2})
    assert first.status_code == 200, first.text
    assert first.json()["next_cursor"] is not None
    second = client.get("/api/movements/page", params={
        "job_id": jid, "limit": 2, "before_id": first.json()["next_cursor"]})
    assert second.status_code == 200, second.text
    assert second.json()["next_cursor"] is None
    items = first.json()["items"] + second.json()["items"]
    assert len(items) == len({item["id"] for item in items}) == 3
    assert {item["source"] for item in items} == {"print_job", "job_correction", "measurement_reconciliation"}
    assert all(item["job_id"] == jid and item["job_file_name"] == "part.gcode" for item in items)

    original = next(item for item in items if item["source"] == "print_job")
    correction = next(item for item in items if item["source"] == "job_correction")
    offset = next(item for item in items if item["source"] == "measurement_reconciliation")
    assert original["accounting_operation_id"] == estimated.json()["operation_id"]
    assert correction["accounting_operation_id"] == offset["accounting_operation_id"] == corrected.json()["operation_id"]
    assert correction["corrects_movement_id"] == original["id"]
    assert offset["corrects_movement_id"] == measurement_id
    assert offset["print_job_id"] is None and offset["job_id"] == jid
    assert (original["delta_g"], correction["delta_g"], offset["delta_g"]) == (-100, 63, -63)
    assert -sum(item["delta_g"] for item in items if item["print_job_id"] == jid) == 37
    assert spool_state(workshop)["remaining_g"] == 963


def test_zero_difference_stocktake_and_metadata_reconfirmation_keep_measurement_requirement(workshop):
    client, path, spools, _ = workshop
    jid = job_for(workshop)
    observed(workshop, jid, "cancelled")
    assert confirm(workshop, jid, 100).status_code == 200
    weighed = client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 900, "expected_stock_revision": 1})
    assert weighed.status_code == 200 and weighed.json()["difference_g"] == 0
    assert spool_state(workshop)["stock_revision"] == 1
    # Neither a zero-difference measurement nor a same-total mode/note change
    # should erase the ordering fact needed by a later material correction.
    assert confirm(workshop, jid, 100, reason="Reconfirmed the same original total").status_code == 200
    assert confirm(workshop, jid, 37).status_code == 409
    result = confirm(workshop, jid, 37, measurements=[{
        "spool_id": spools[0], "gross_g": 900, "expected_stock_revision": 1}])
    assert result.status_code == 200, result.text
    assert spool_state(workshop)["remaining_g"] == 900
    assert confirm(workshop, jid, 20).status_code == 409
    unchanged_total_wrong_measurement = confirm(workshop, jid, 37, measurements=[{
        "spool_id": spools[0], "gross_g": 800, "expected_stock_revision": 1}],
        reason="A different stocktake is not a job correction")
    assert unchanged_total_wrong_measurement.status_code == 409
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM stock_measurements WHERE spool_id=?", (spools[0],)).fetchone()[0] == 2
        assert db.execute("SELECT SUM(delta_g) FROM movements WHERE spool_id=?", (spools[0],)).fetchone()[0] == 900


def test_estimated_and_discard_corrections_after_stocktake_can_reconcile_current_measurement(workshop):
    client, _, spools, _ = workshop
    jid = job_for(workshop)
    observed(workshop, jid, "cancelled")
    assert confirm(workshop, jid, 37).status_code == 200
    assert client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 800}).status_code == 200
    for mode in ("estimated", "discard"):
        payload = {"mode": mode, "reason": "Explicit review after an intervening physical stocktake",
                   "measurements": [{"spool_id": spools[0], "gross_g": 800,
                                     "expected_stock_revision": spool_state(workshop)["stock_revision"]}]}
        result = client.post(f"/api/jobs/{jid}/consumption", json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["accounting_method"] == mode
        assert spool_state(workshop)["remaining_g"] == 800
    assert sum(row["delta_g"] for row in ledger(workshop, jid)) == 0


def test_larger_historical_usage_after_stocktake_posts_nonnegative_atomic_journal(workshop):
    client, path, spools, _ = workshop
    jid = job_for(workshop)
    observed(workshop, jid, "cancelled")
    assert confirm(workshop, jid, 100).status_code == 200
    assert client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 0}).status_code == 200
    result = confirm(workshop, jid, 900, measurements=[{
        "spool_id": spools[0], "gross_g": 0, "expected_stock_revision": 2}])
    assert result.status_code == 200, result.text
    assert spool_state(workshop)["remaining_g"] == 0
    assert -sum(row["delta_g"] for row in ledger(workshop, jid)) == 900
    with session(path) as db:
        movements = db.execute("SELECT * FROM movements WHERE spool_id=? ORDER BY id", (spools[0],)).fetchall()
        balance = 0
        for movement in movements:
            balance += movement["delta_g"]
            assert balance == movement["remaining_after_g"] and 0 <= balance <= 1000
        assert balance == 0
    rejected = confirm(workshop, jid, 1001, measurements=[{
        "spool_id": spools[0], "gross_g": 0, "expected_stock_revision": 2}])
    assert rejected.status_code == 409


def test_stocktake_correction_keeps_even_split_compensations_within_roll_bounds(workshop):
    client, path, spools, _ = workshop
    jid = job_for(workshop)
    observed(workshop, jid, "cancelled")
    assert confirm(workshop, jid, 100).status_code == 200
    assert client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 950}).status_code == 200
    result = confirm(workshop, jid, 0, measurements=[{
        "spool_id": spools[0], "gross_g": 10, "expected_stock_revision": 2}])
    assert result.status_code == 200, result.text
    assert spool_state(workshop)["remaining_g"] == 10
    assert sum(row["delta_g"] for row in ledger(workshop, jid)) == 0
    with session(path) as db:
        balance = 0
        for movement in db.execute("SELECT * FROM movements WHERE spool_id=? ORDER BY id", (spools[0],)):
            balance += movement["delta_g"]
            assert balance == movement["remaining_after_g"] and 0 <= balance <= 1000
        assert balance == 10


def test_measurement_anchor_order_and_correction_survive_restart(workshop):
    client, path, spools, _ = workshop
    # A measurement before a new print is a valid starting balance, not a
    # reason to block that print's first decision or a subsequent correction.
    assert client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 900}).status_code == 200
    jid = job_for(workshop)
    observed(workshop, jid, "cancelled")
    assert confirm(workshop, jid, 37).status_code == 200
    assert confirm(workshop, jid, 20).status_code == 200
    assert spool_state(workshop)["remaining_g"] == 880
    assert client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 850}).status_code == 200
    initialize_database(path)
    with session(path, write=True) as db:
        migrate_accounting(db)
        before = [tuple(row) for row in db.execute("SELECT * FROM stock_measurements ORDER BY id")]
        migrate_accounting(db)
        assert [tuple(row) for row in db.execute("SELECT * FROM stock_measurements ORDER BY id")] == before
    assert confirm(workshop, jid, 25).status_code == 409
    revision = spool_state(workshop)["stock_revision"]
    result = confirm(workshop, jid, 25, measurements=[{
        "spool_id": spools[0], "gross_g": 850, "expected_stock_revision": revision}])
    assert result.status_code == 200, result.text
    assert spool_state(workshop)["remaining_g"] == 850
    assert -sum(row["delta_g"] for row in ledger(workshop, jid)) == 25


def test_upgrade_preserves_legacy_zero_difference_stocktake_without_inventing_weight(workshop):
    client, path, spools, _ = workshop
    jid = job_for(workshop)
    observed(workshop, jid, "cancelled")
    assert confirm(workshop, jid, 100).status_code == 200
    assert client.post(f"/api/spools/{spools[0]}/weigh", json={"gross_g": 900}).status_code == 200
    with session(path, write=True) as db:
        # Old versions retained only the audit event for an unchanged weight.
        # Recreate that exact absence of measurement context for the upgrade.
        db.execute("DROP TABLE stock_measurements")
        migrate_accounting(db)
        anchor = db.execute("SELECT * FROM stock_measurements WHERE spool_id=?", (spools[0],)).fetchone()
        assert anchor["net_g"] is None and anchor["tare_g"] is None and anchor["stock_revision"] is None
        migrate_accounting(db)
        assert db.execute("SELECT COUNT(*) FROM stock_measurements").fetchone()[0] == 1
    snapshot = client.get(f"/api/jobs/{jid}/consumption").json()
    assert snapshot["materials"][0]["measurement_reconciliation_required"]
    assert snapshot["materials"][0]["last_measured_g"] is None
    assert confirm(workshop, jid, 37).status_code == 409
    result = confirm(workshop, jid, 37, measurements=[{
        "spool_id": spools[0], "gross_g": 900, "expected_stock_revision": 1}])
    assert result.status_code == 200, result.text
    assert spool_state(workshop)["remaining_g"] == 900


def test_measurement_must_match_explicit_actuals_and_have_current_revision(workshop):
    client, _, spools, _ = workshop
    jid = job_for(workshop)
    observed(workshop, jid)
    mismatch = confirm(workshop, jid, 37, measurements=[{"spool_id": spools[0], "gross_g": 900,
                                                        "expected_stock_revision": 0}])
    assert mismatch.status_code == 409
    assert ledger(workshop, jid) == []
    assert client.patch(f"/api/spools/{spools[0]}", json={"tare_g": 20}).status_code == 200
    stale = confirm(workshop, jid, 100, measurements=[{"spool_id": spools[0], "gross_g": 920,
                                                      "expected_stock_revision": 0}])
    assert stale.status_code == 409
    assert spool_state(workshop)["remaining_g"] == 1000


def test_measurement_cannot_infer_attribution_across_other_unaccounted_jobs(workshop):
    jid = job_for(workshop)
    another = job_for(workshop, name="another.gcode")
    observed(workshop, jid)
    observed(workshop, another)
    result = confirm(workshop, jid, 100, measurements=[{"spool_id": workshop[2][0], "gross_g": 900,
                                                       "expected_stock_revision": 0}])
    assert result.status_code == 409
    assert str(another) in result.json()["detail"]
    assert ledger(workshop, jid) == []


@pytest.mark.parametrize("change", ["consumption", "tare"])
def test_scale_approval_detects_intervening_stock_or_tare_changes(workshop, monkeypatch, change):
    client, _, spools, _ = workshop
    receipt = scale_receipt(workshop, monkeypatch, 1000)
    if change == "consumption":
        assert client.post(f"/api/spools/{spools[0]}/movements", json={"kind": "consume", "grams": 100}).status_code == 201
    else:
        assert client.patch(f"/api/spools/{spools[0]}", json={"tare_g": 100}).status_code == 200
    before = spool_state(workshop)
    result = client.post(f"/api/scales/measurements/{receipt}/review",
                         json={"action": "approve", "note": "Reviewed the pending scale receipt"})
    assert result.status_code == 409
    assert spool_state(workshop) == before
    pending = client.get("/api/scales/measurements").json()
    assert pending[0]["stale"] and pending[0]["captured_stock_revision"] == 0


def test_two_scale_receipts_cannot_reinterpret_each_others_applied_stock(workshop, monkeypatch):
    client = workshop[0]
    older = scale_receipt(workshop, monkeypatch, 950)
    newer = scale_receipt(workshop, monkeypatch, 900)
    payload = {"action": "approve", "note": "Verified physical spool and scale"}
    assert client.post(f"/api/scales/measurements/{newer}/review", json=payload).status_code == 200
    assert client.post(f"/api/scales/measurements/{older}/review", json=payload).status_code == 409
    assert spool_state(workshop)["remaining_g"] == 900


def test_declared_scale_capture_before_a_stock_change_is_rejected_at_receipt(workshop, monkeypatch):
    captured = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    sid = workshop[2][0]
    assert workshop[0].post(f"/api/spools/{sid}/movements", json={"kind": "consume", "grams": 100}).status_code == 201
    result = scale_receipt(workshop, monkeypatch, 1000, measured_at=captured, expected_status=409)
    assert "declared measurement time" in result.json()["detail"]
    assert workshop[0].get("/api/scales/measurements").json() == []
    assert spool_state(workshop)["remaining_g"] == 900


def test_scale_receipt_and_explicit_job_accounting_are_applied_together(workshop, monkeypatch):
    client, path, spools, printer = workshop
    jid = job_for(workshop)
    run = remote_run(workshop, monkeypatch)
    run["status"] = "completed"
    receipt = scale_receipt(workshop, monkeypatch, 900)
    listed = client.get("/api/scales/measurements").json()[0]
    assert listed["blocking_job_ids"] == [jid] and not listed["stale"]
    ordinary = client.post(f"/api/scales/measurements/{receipt}/review",
                           json={"action": "approve", "note": "Confirm measurement after printing"})
    assert ordinary.status_code == 409
    result = confirm(workshop, jid, 100, request_id=str(uuid4()), measurements=[{
        "spool_id": spools[0], "gross_g": 900, "expected_stock_revision": 0, "scale_event_id": receipt}])
    assert result.status_code == 200, result.text
    with session(path) as db:
        stored = db.execute("SELECT * FROM scale_event_receipts WHERE id=?", (receipt,)).fetchone()
        assert stored["status"] == "applied"
        assert stored["accounting_operation_id"] == result.json()["operation_id"]
    assert client.post(f"/api/printers/{printer}/poll").status_code == 200
    assert spool_state(workshop)["remaining_g"] == 900
    assert len(ledger(workshop, jid)) == 1


def test_parallel_poll_and_explicit_actual_decision_have_one_net_accounting_effect(workshop):
    jid = job_for(workshop)
    observed(workshop, jid, "printing")
    payload = ConsumptionInput(mode="actual", materials=[{"spool_id": workshop[2][0], "actual_g": 37}],
                               reason="Verified partial physical consumption")
    def poll():
        with session(workshop[1], write=True) as db:
            return apply_consumption(db, {"id": jid}, None)
    def actual():
        return reconcile_consumption(workshop[1], jid, payload, 1)
    with ThreadPoolExecutor(max_workers=2) as workers:
        pending = [workers.submit(poll), workers.submit(actual)]
        for future in pending:
            future.result()
    assert spool_state(workshop)["remaining_g"] == 963
    assert sum(row["delta_g"] for row in ledger(workshop, jid)) == -37
    assert workshop[0].get(f"/api/jobs/{jid}/consumption").json()["accounting_method"] == "actual"


def test_parallel_absolute_measurements_require_one_current_revision(workshop):
    route = f"/api/spools/{workshop[2][0]}/weigh"
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda weight: workshop[0].post(route, json={
            "gross_g": weight, "expected_stock_revision": 0}), [970, 980]))
    assert sorted(result.status_code for result in results) == [200, 409]
    assert spool_state(workshop)["remaining_g"] in (970, 980)
    assert spool_state(workshop)["stock_revision"] == 1


def test_repeated_accounting_migration_preserves_correction_history_and_legacy_receipts_conflict(workshop, monkeypatch):
    jid = job_for(workshop)
    observed(workshop, jid)
    assert confirm(workshop, jid, 100).status_code == 200
    assert confirm(workshop, jid, 37, reason="Measured partial print correction").status_code == 200
    before = ledger(workshop, jid)
    with session(workshop[1], write=True) as db:
        migrate_accounting(db)
        migrate_accounting(db)
    assert ledger(workshop, jid) == before
    assert spool_state(workshop)["remaining_g"] == 963
    receipt = scale_receipt(workshop, monkeypatch, 963)
    with session(workshop[1], write=True) as db:
        db.execute("UPDATE scale_event_receipts SET captured_stock_revision=NULL,captured_tare_g=NULL WHERE id=?", (receipt,))
    result = workshop[0].post(f"/api/scales/measurements/{receipt}/review",
                              json={"action": "approve", "note": "Older receipt without stored context"})
    assert result.status_code == 409 and "older" in result.json()["detail"]
