"""Historical SQLite fixtures for recovery tests and disposable Docker smoke.

The base DDL comes from the schema-v5 revision 6456db8. Schema v1 contains
only its original three inventory tables. Later fixture versions apply the
real forward migrations up to that version, never downgrade a current DB.
This module has no pytest dependency and may be executed inside a test image.
"""
from pathlib import Path
import sqlite3

from app.infrastructure.database import migrations

FIXTURE_BALANCE_G = 900
FIXTURE_SPOOL_ID = 1
FIXTURE_PRODUCT_UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FIXTURE_SPOOL_UID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

LEGACY_SCHEMA = """
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


def create_legacy_database(path, version=5, *, with_data=True):
    """Create a standalone versioned fixture; existing paths are never replaced."""
    if version not in (1, 5, 10, 11, 12):
        raise ValueError("Unsupported historical fixture version")
    path = Path(path)
    with path.open("xb"):
        pass
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        base = LEGACY_SCHEMA.split("CREATE TABLE IF NOT EXISTS users", 1)[0] if version == 1 else LEGACY_SCHEMA
        db.executescript(base)
        if with_data:
            db.execute("""INSERT INTO products(id,brand,name,material,color_name,color_hex,
                diameter_mm,notes,created_at,updated_at)
                VALUES(1,'private-fixture-brand','private-fixture-product','PLA',
                       'Black','#000000',1.75,'private-fixture-product-note',
                       '2020-01-01','2020-01-01')""")
            db.execute("""INSERT INTO spools(id,product_id,initial_g,remaining_g,location,created_at)
                VALUES(1,1,1000,900,'private-fixture-location','2020-01-01')""")
            db.execute("""INSERT INTO movements(id,spool_id,kind,delta_g,remaining_after_g,note,created_at)
                VALUES(1,1,'initial',1000,1000,'private-fixture-ledger-note','2020-01-01')""")
            db.execute("""INSERT INTO movements(id,spool_id,kind,delta_g,remaining_after_g,note,created_at)
                VALUES(2,1,'consume',-100,900,'private-fixture-ledger-note','2020-01-02')""")
            if version >= 5:
                db.execute("""INSERT INTO users(id,username,password_hash,role,created_at)
                    VALUES(1,'private-fixture-user','private-fixture-password-hash','admin','2020-01-01')""")
                db.execute("""INSERT INTO printers(id,name,kind,base_url,token_env,enabled,created_at)
                    VALUES(1,'private-fixture-printer','moonraker','http://192.168.50.20',
                           'PRIVATE_FIXTURE_PRINTER_TOKEN',0,'2020-01-01')""")
                db.execute("""INSERT INTO print_jobs(id,printer_id,spool_id,file_name,estimated_g,
                    status,movement_id,created_by,created_at,updated_at)
                    VALUES(1,1,1,'private-fixture-job.gcode',100,'completed',2,1,'2020-01-01','2020-01-02')""")
        if version >= 5:
            migrations.migrate_v2_v4(db)
            if with_data:
                db.execute("UPDATE products SET uid=? WHERE id=1", (FIXTURE_PRODUCT_UID,))
                db.execute("UPDATE spools SET uid=? WHERE id=1", (FIXTURE_SPOOL_UID,))
                db.execute("UPDATE movements SET print_job_id=1 WHERE id=2")
            for number in range(5, version + 1):
                getattr(migrations, f"migrate_v{number}")(db)
        db.execute(f"PRAGMA user_version={version}")
        db.execute("PRAGMA journal_mode=DELETE")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise AssertionError("Historical fixture contains broken references")
    finally:
        db.close()
    return path
