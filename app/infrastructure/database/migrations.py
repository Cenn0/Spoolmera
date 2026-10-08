"""Idempotent migration to schema v5; v2-v4 compatibility remains in database.py."""
import sqlite3

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
    # A crash can occur after the command reached hardware but before acknowledgement.
    # Reconciliation must never silently retry such a command on restart.
    db.execute("UPDATE printer_commands SET state='unknown',updated_at=CURRENT_TIMESTAMP WHERE state='sending'")
