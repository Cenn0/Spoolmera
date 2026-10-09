"""SQLite storage, schema initialization and explicit write transactions."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from app.infrastructure.database.migrations import (
    CURRENT_SCHEMA_VERSION, migrate_v2_v4, migrate_v5, migrate_v6, migrate_v7, migrate_v8, migrate_v9, recover_interrupted_commands,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    brand TEXT NOT NULL,
    name TEXT NOT NULL,
    material TEXT NOT NULL,
    color_name TEXT NOT NULL,
    color_hex TEXT NOT NULL,
    diameter_mm REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spools (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    initial_g INTEGER NOT NULL CHECK (initial_g > 0),
    remaining_g INTEGER NOT NULL CHECK (remaining_g >= 0 AND remaining_g <= initial_g),
    opened INTEGER NOT NULL DEFAULT 0 CHECK (opened IN (0, 1)),
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_spools_product ON spools(product_id);
CREATE INDEX IF NOT EXISTS idx_spools_archived ON spools(archived_at);
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY,
    spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('initial', 'consume', 'adjust')),
    delta_g INTEGER NOT NULL CHECK (delta_g <> 0 OR kind = 'initial'),
    remaining_after_g INTEGER NOT NULL CHECK (remaining_after_g >= 0),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_movements_spool ON movements(spool_id, id DESC);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS auth_failures (
    subject TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_failures ON auth_failures(subject, created_at);
CREATE TABLE IF NOT EXISTS printers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('moonraker','octoprint')),
    base_url TEXT NOT NULL,
    token_env TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS print_jobs (
    id INTEGER PRIMARY KEY,
    printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE RESTRICT,
    spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
    file_name TEXT NOT NULL,
    estimated_g INTEGER NOT NULL CHECK(estimated_g BETWEEN 1 AND 100000),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','printing','completed','needs_review','cancelled')),
    external_job_id TEXT,
    observed_printing INTEGER NOT NULL DEFAULT 0 CHECK(observed_printing IN (0,1)),
    movement_id INTEGER REFERENCES movements(id),
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status,printer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_print_jobs_one_active
 ON print_jobs(printer_id,file_name) WHERE status IN ('pending','printing');
CREATE UNIQUE INDEX IF NOT EXISTS idx_print_jobs_external
 ON print_jobs(printer_id,external_job_id) WHERE external_job_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS job_materials (
    job_id INTEGER NOT NULL REFERENCES print_jobs(id) ON DELETE CASCADE,
    tool INTEGER NOT NULL CHECK(tool BETWEEN 0 AND 15),
    spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE RESTRICT,
    estimated_g INTEGER NOT NULL CHECK(estimated_g BETWEEN 1 AND 100000),
    movement_id INTEGER REFERENCES movements(id),
    PRIMARY KEY(job_id, tool)
);
CREATE INDEX IF NOT EXISTS idx_job_materials_spool ON job_materials(spool_id);
CREATE TABLE IF NOT EXISTS cloud_event_receipts (
    source TEXT NOT NULL,
    event_id TEXT NOT NULL,
    job_id INTEGER NOT NULL REFERENCES print_jobs(id),
    payload_digest TEXT NOT NULL,
    disposition TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY(source, event_id)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id INTEGER,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


@contextmanager
def session(path: str | Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        if write:
            connection.execute("COMMIT")
    except BaseException:
        if write and connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def initialize_database(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with session(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError("Database schema is newer than this Filament Manager version.")
        connection.executescript(SCHEMA)
        # Migration v2 preserves existing numeric IDs while assigning stable UUIDs.
        connection.execute("BEGIN IMMEDIATE")
        try:
            if version < 4:
                migrate_v2_v4(connection)
            if version < 5:
                migrate_v5(connection)
            if version < 6:
                migrate_v6(connection)
            if version < 7:
                migrate_v7(connection)
            if version < 8:
                migrate_v8(connection)
            if version < 9:
                migrate_v9(connection)
            recover_interrupted_commands(connection)
            connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
