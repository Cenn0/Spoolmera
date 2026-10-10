"""Additive, idempotent SQLite schema migrations and restart recovery."""
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone

CURRENT_SCHEMA_VERSION = 11

def migrate_v2_v4(connection: sqlite3.Connection) -> None:
    """Preserve legacy IDs and write an idempotent material mapping upgrade."""
    for table in ("products", "spools"):
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if "uid" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN uid TEXT")
        for row in connection.execute(
            f"SELECT id FROM {table} WHERE uid IS NULL OR uid = ''"
        ).fetchall():
            connection.execute(
                f"UPDATE {table} SET uid = ? WHERE id = ?",
                (str(uuid4()), row["id"]),
            )
        connection.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uid ON {table}(uid)"
        )
    movement_columns = {row["name"] for row in connection.execute("PRAGMA table_info(movements)")}
    if "print_job_id" not in movement_columns:
        connection.execute(
            "ALTER TABLE movements ADD COLUMN print_job_id INTEGER REFERENCES print_jobs(id)"
        )
    # Version 4 supports one immutable movement per (job, physical spool).
    # Dropping the old one-movement-per-job index is required for MMU jobs.
    connection.execute("DROP INDEX IF EXISTS idx_movements_print_job")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_movements_print_job_spool "
        "ON movements(print_job_id, spool_id) WHERE print_job_id IS NOT NULL"
    )
    connection.execute(
        """INSERT OR IGNORE INTO job_materials(job_id,tool,spool_id,estimated_g,movement_id)
           SELECT j.id,0,j.spool_id,j.estimated_g,j.movement_id FROM print_jobs j
           WHERE NOT EXISTS (SELECT 1 FROM job_materials m WHERE m.job_id=j.id)"""
    )


def _ensure_column(db: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

def migrate_v5(db: sqlite3.Connection) -> None:
    """Run inside the existing BEGIN IMMEDIATE transaction.

    In-place upgrades never infer missing historical actor identities.
    """
    _ensure_column(db, "movements", "actor_id", "INTEGER REFERENCES users(id)")
    _ensure_column(db, "movements", "source", "TEXT NOT NULL DEFAULT 'manual'")
    _ensure_column(db, "movements", "source_ref", "TEXT")
    db.execute("UPDATE movements SET source='print_job' WHERE print_job_id IS NOT NULL AND source='manual'")
    _ensure_column(db, "print_jobs", "accounting_status",
                   "TEXT NOT NULL DEFAULT 'pending' CHECK(accounting_status IN ('pending','needs_review','debited','discarded'))")
    db.execute("""UPDATE print_jobs SET accounting_status =
        CASE WHEN status='completed' THEN 'debited'
             WHEN status='needs_review' THEN 'needs_review'
             WHEN status='cancelled' THEN 'discarded'
             ELSE accounting_status END
        WHERE status IN ('completed','needs_review','cancelled')""")
    db.execute("""CREATE TABLE IF NOT EXISTS print_runs (
        id INTEGER PRIMARY KEY,
        printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE RESTRICT,
        job_id INTEGER REFERENCES print_jobs(id) ON DELETE RESTRICT,
        external_run_id TEXT NOT NULL,
        state TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        UNIQUE(printer_id, external_run_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_print_runs_job ON print_runs(job_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS printer_commands (
        id TEXT PRIMARY KEY,
        printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE RESTRICT,
        job_id INTEGER REFERENCES print_jobs(id) ON DELETE RESTRICT,
        action TEXT NOT NULL CHECK(action IN ('start','pause','resume','cancel')),
        state TEXT NOT NULL CHECK(state IN ('sending','acknowledged','unknown','rejected','confirmed','cleared')),
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        http_status INTEGER,
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_start_command_active
        ON printer_commands(job_id,action)
        WHERE action='start' AND state IN ('sending','acknowledged','unknown','confirmed')""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_commands_printer ON printer_commands(printer_id,created_at DESC)")
    db.execute("""CREATE TABLE IF NOT EXISTS printer_poll_state (
        printer_id INTEGER PRIMARY KEY REFERENCES printers(id) ON DELETE CASCADE,
        last_attempt_at TEXT,
        last_success_at TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT ''
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS worker_leases (
        name TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        expires_at INTEGER NOT NULL
    )""")
    # Runtime recovery is separate from schema upgrades.


def recover_interrupted_commands(db: sqlite3.Connection) -> None:
    """Fail closed after API restart; never retry a possibly delivered command.

    A single API worker is the supported deployment. A second worker can only
    mark an in-flight command unknown, never execute it again automatically.
    """
    db.execute("""UPDATE printer_commands SET state='unknown',updated_at=?
                  WHERE state='sending'""",
               (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    db.execute("UPDATE printer_operations SET state='unknown' WHERE state='active'")


def migrate_v6(db: sqlite3.Connection) -> None:
    """Add optional material properties, physical weighing and drying history."""
    for name, ddl in (
        ("density_g_cm3", "REAL CHECK(density_g_cm3 > 0 AND density_g_cm3 <= 10)"),
        ("nozzle_min_c", "INTEGER CHECK(nozzle_min_c BETWEEN 0 AND 400)"),
        ("nozzle_max_c", "INTEGER CHECK(nozzle_max_c BETWEEN 0 AND 400)"),
        ("bed_min_c", "INTEGER CHECK(bed_min_c BETWEEN 0 AND 200)"),
        ("bed_max_c", "INTEGER CHECK(bed_max_c BETWEEN 0 AND 200)"),
        ("gtin", "TEXT NOT NULL DEFAULT ''"),
        ("manufacturer_sku", "TEXT NOT NULL DEFAULT ''"),
        ("slicer_preset", "TEXT NOT NULL DEFAULT ''"),
        ("low_stock_threshold_g", "INTEGER NOT NULL DEFAULT 200 CHECK(low_stock_threshold_g BETWEEN 0 AND 100000)"),
    ):
        _ensure_column(db, "products", name, ddl)
    for name, ddl in (
        ("tare_g", "INTEGER NOT NULL DEFAULT 0 CHECK(tare_g BETWEEN 0 AND 100000)"),
        ("purchase_price_cents", "INTEGER CHECK(purchase_price_cents BETWEEN 0 AND 100000000)"),
        ("purchase_currency", "TEXT NOT NULL DEFAULT 'EUR'"),
        ("purchased_on", "TEXT"),
        ("batch", "TEXT NOT NULL DEFAULT ''"),
    ):
        _ensure_column(db, "spools", name, ddl)
    db.execute("""CREATE TABLE IF NOT EXISTS drying_records (
        id INTEGER PRIMARY KEY,
        spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
        temperature_c INTEGER NOT NULL CHECK(temperature_c BETWEEN 1 AND 150),
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 10080),
        dried_at TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_drying_spool ON drying_records(spool_id, dried_at DESC)")


def migrate_v7(db: sqlite3.Connection) -> None:
    """Advisory print reservations and explicit feeder-slot mapping."""
    db.execute("""CREATE TABLE IF NOT EXISTS job_reservations (
        job_id INTEGER NOT NULL REFERENCES print_jobs(id) ON DELETE RESTRICT,
        spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
        reserved_g INTEGER NOT NULL CHECK(reserved_g > 0),
        created_at TEXT NOT NULL,
        PRIMARY KEY(job_id,spool_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_reservation_spool ON job_reservations(spool_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS printer_spool_slots (
        printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE RESTRICT,
        tool INTEGER NOT NULL CHECK(tool BETWEEN 0 AND 15),
        spool_id INTEGER NOT NULL UNIQUE REFERENCES spools(id) ON DELETE RESTRICT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(printer_id,tool)
    )""")


def migrate_v8(db: sqlite3.Connection) -> None:
    """Scoped machine tokens, portable external IDs, and NFC/QR tag references."""
    db.execute("""CREATE TABLE IF NOT EXISTS automation_tokens (
        id INTEGER PRIMARY KEY,
        label TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        scope TEXT NOT NULL CHECK(scope IN ('inventory_read','events_read')),
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS external_import_map (
        source TEXT NOT NULL,
        entity_type TEXT NOT NULL CHECK(entity_type IN ('spool','filament')),
        external_id INTEGER NOT NULL CHECK(external_id > 0),
        local_id INTEGER NOT NULL,
        PRIMARY KEY(source,entity_type,external_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS spool_identifiers (
        namespace TEXT NOT NULL CHECK(namespace IN ('nfc','openprinttag','custom')),
        external_id TEXT NOT NULL,
        spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
        created_at TEXT NOT NULL,
        PRIMARY KEY(namespace,external_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_identifiers_spool ON spool_identifiers(spool_id)")


def migrate_v9(db: sqlite3.Connection) -> None:
    """Signed scale measurements awaiting explicit inventory approval."""
    db.execute("""CREATE TABLE IF NOT EXISTS scale_event_receipts (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        event_id TEXT NOT NULL,
        payload_digest TEXT NOT NULL,
        spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
        gross_g INTEGER NOT NULL CHECK(gross_g BETWEEN 0 AND 200000),
        tare_g INTEGER CHECK(tare_g BETWEEN 0 AND 100000),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','applied','discarded')),
        received_at TEXT NOT NULL,
        reviewed_at TEXT,
        reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(source,event_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_scale_pending ON scale_event_receipts(status,id)")


def migrate_v10(db: sqlite3.Connection) -> None:
    """Reconciliation, stock planning and printer-operation coordination."""
    from app.infrastructure.database.accounting_migration import migrate_accounting
    from app.infrastructure.database.workflow_migration import migrate_workflows
    migrate_accounting(db)
    migrate_workflows(db)


def migrate_v11(db: sqlite3.Connection) -> None:
    """Persist a device serial for LAN MQTT topics without storing credentials."""
    _ensure_column(db, "printers", "serial", "TEXT NOT NULL DEFAULT ''")
