"""SQLite storage, schema initialization and explicit write transactions."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

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
        connection.executescript(SCHEMA)
