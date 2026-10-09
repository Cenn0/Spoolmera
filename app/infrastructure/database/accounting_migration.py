"""Add revisioned stock and an append-only record of accounting decisions.

Called by the schema migration while its write transaction is already held.
No historical movement is rewritten or inferred from a current spool balance.
"""
import sqlite3


def _column(db: sqlite3.Connection, table: str, name: str, declaration: str) -> bool:
    if name not in {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
        return True
    return False


def migrate_accounting(db: sqlite3.Connection) -> None:
    _column(db, "spools", "stock_revision", "INTEGER NOT NULL DEFAULT 0 CHECK(stock_revision>=0)")
    _column(db, "spools", "stock_changed_at", "TEXT")
    _column(db, "print_jobs", "accounting_revision", "INTEGER NOT NULL DEFAULT 0 CHECK(accounting_revision>=0)")
    _column(db, "print_jobs", "accounting_method", "TEXT CHECK(accounting_method IN ('estimated','actual','discard'))")
    _column(db, "print_jobs", "accounting_note", "TEXT NOT NULL DEFAULT ''")
    db.execute("""CREATE TABLE IF NOT EXISTS accounting_operations (
        id TEXT PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES print_jobs(id) ON DELETE RESTRICT,
        request_key TEXT,
        payload_digest TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('estimated','actual','discard')),
        reason TEXT NOT NULL,
        actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        accounting_revision INTEGER NOT NULL CHECK(accounting_revision>0),
        response_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(job_id,request_key),
        UNIQUE(job_id,accounting_revision)
    )""")
    _column(db, "movements", "corrects_movement_id", "INTEGER REFERENCES movements(id) ON DELETE RESTRICT")
    _column(db, "movements", "accounting_operation_id", "TEXT REFERENCES accounting_operations(id) ON DELETE RESTRICT")
    # Initial job/spool postings retain their existing uniqueness. Subsequent
    # corrections keep their job reference and point to the preceding posting.
    db.execute("DROP INDEX IF EXISTS idx_movements_print_job_spool")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_movements_print_job_spool
        ON movements(print_job_id,spool_id)
        WHERE print_job_id IS NOT NULL AND corrects_movement_id IS NULL""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_movements_correction ON movements(corrects_movement_id)")
    import_legacy_measurements = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_measurements'").fetchone() is None
    db.execute("""CREATE TABLE IF NOT EXISTS stock_measurements (
        id INTEGER PRIMARY KEY,
        spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
        movement_id INTEGER UNIQUE REFERENCES movements(id) ON DELETE RESTRICT,
        accounting_operation_id TEXT REFERENCES accounting_operations(id) ON DELETE RESTRICT,
        stock_revision INTEGER,
        net_g INTEGER CHECK(net_g BETWEEN 0 AND 100000),
        tare_g INTEGER CHECK(tare_g BETWEEN 0 AND 100000),
        actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_stock_measurements_spool ON stock_measurements(spool_id,id DESC)")
    # A physical stocktake remains a balance anchor even when a later job
    # correction changes how historical use is attributed. Preserve known
    # legacy measurements; their original tare/revision cannot be recovered.
    if import_legacy_measurements:
        db.execute("""INSERT INTO stock_measurements
            (spool_id,movement_id,net_g,actor_id,note,created_at)
            SELECT spool_id,movement_id,net_g,actor_id,note,created_at FROM (
                SELECT spool_id,id AS movement_id,remaining_after_g AS net_g,actor_id,note,created_at
                FROM movements WHERE source='weighing'
                UNION ALL
                SELECT a.entity_id,NULL,NULL,a.actor_id,
                    'Legacy physical stocktake; historical weight context was not stored.',a.created_at
                FROM audit_events a WHERE a.action='spool_weigh' AND a.entity='spool'
                    AND EXISTS (SELECT 1 FROM spools s WHERE s.id=a.entity_id)
                    AND NOT EXISTS (SELECT 1 FROM movements m WHERE m.spool_id=a.entity_id
                        AND m.source='weighing' AND m.created_at=a.created_at)
            ) ORDER BY created_at,movement_id""")
    db.execute("""CREATE TABLE IF NOT EXISTS job_consumption_totals (
        job_id INTEGER NOT NULL REFERENCES print_jobs(id) ON DELETE RESTRICT,
        spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
        accounted_g INTEGER NOT NULL DEFAULT 0 CHECK(accounted_g BETWEEN 0 AND 100000),
        last_movement_id INTEGER REFERENCES movements(id) ON DELETE RESTRICT,
        PRIMARY KEY(job_id,spool_id)
    )""")
    new_anchor_column = _column(db, "job_consumption_totals", "measurement_anchor_id",
                               "INTEGER REFERENCES stock_measurements(id) ON DELETE RESTRICT")
    # Preserve recorded amounts; estimates are not proof of a historical debit.
    db.execute("""INSERT OR IGNORE INTO job_consumption_totals
        (job_id,spool_id,accounted_g,last_movement_id)
        SELECT m.print_job_id,m.spool_id,MAX(0,-SUM(m.delta_g)),MAX(m.id)
        FROM movements m WHERE m.print_job_id IS NOT NULL
        GROUP BY m.print_job_id,m.spool_id""")
    if new_anchor_column:
        db.execute("""UPDATE job_consumption_totals SET measurement_anchor_id=(
            SELECT MAX(a.id) FROM stock_measurements a
            WHERE a.spool_id=job_consumption_totals.spool_id
                AND a.created_at < (SELECT created_at FROM movements m
                    WHERE m.id=job_consumption_totals.last_movement_id)
        )""")
    db.execute("""UPDATE print_jobs SET accounting_method=
        CASE WHEN accounting_status='debited' THEN 'estimated'
             WHEN accounting_status='discarded' THEN 'discard' END
        WHERE accounting_method IS NULL AND accounting_status IN ('debited','discarded')""")
    # Cover every write path, including imports and direct metadata updates.
    # No-op saves do not invalidate an otherwise current measurement.
    db.execute("DROP TRIGGER IF EXISTS spool_stock_revision")
    db.execute("""CREATE TRIGGER spool_stock_revision
        AFTER UPDATE OF remaining_g,tare_g ON spools
        WHEN NEW.remaining_g IS NOT OLD.remaining_g OR NEW.tare_g IS NOT OLD.tare_g
        BEGIN
            UPDATE spools SET stock_revision=OLD.stock_revision+1,
                stock_changed_at=strftime('%Y-%m-%dT%H:%M:%f+00:00','now') WHERE id=NEW.id;
        END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS spool_stock_created
        AFTER INSERT ON spools WHEN NEW.stock_changed_at IS NULL
        BEGIN
            UPDATE spools SET stock_changed_at=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
            WHERE id=NEW.id;
        END""")
    db.execute("""UPDATE spools SET stock_changed_at=COALESCE(
        (SELECT MAX(m.created_at) FROM movements m WHERE m.spool_id=spools.id),created_at)
        WHERE stock_changed_at IS NULL""")
    for name, declaration in (
        ("captured_stock_revision", "INTEGER CHECK(captured_stock_revision>=0)"),
        ("captured_tare_g", "INTEGER CHECK(captured_tare_g BETWEEN 0 AND 100000)"),
        ("net_g", "INTEGER CHECK(net_g BETWEEN 0 AND 100000)"),
        ("measured_at", "TEXT"),
        ("review_note", "TEXT NOT NULL DEFAULT ''"),
        ("accounting_operation_id", "TEXT REFERENCES accounting_operations(id) ON DELETE RESTRICT"),
    ):
        _column(db, "scale_event_receipts", name, declaration)
    # Legacy pending receipts deliberately keep NULL context. Approval must ask
    # for a fresh measurement instead of inventing their historical revision.
