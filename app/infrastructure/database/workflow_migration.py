"""Additive schema for stock planning and durable printer coordination."""
import sqlite3
from uuid import uuid4


def migrate_workflows(db: sqlite3.Connection) -> None:
    columns = {row['name'] for row in db.execute('PRAGMA table_info(products)')}
    if 'target_stock_g' not in columns:
        db.execute('ALTER TABLE products ADD COLUMN target_stock_g INTEGER NOT NULL DEFAULT 0 CHECK(target_stock_g BETWEEN 0 AND 10000000)')
    db.execute('CREATE TABLE IF NOT EXISTS application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute("INSERT OR IGNORE INTO application_metadata(key,value) VALUES('instance_epoch',?)", (str(uuid4()),))
    db.execute('''CREATE TABLE IF NOT EXISTS inventory_batch_receipts (
        actor_id INTEGER NOT NULL REFERENCES users(id),request_key TEXT NOT NULL,
        payload_digest TEXT NOT NULL,response_json TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(actor_id,request_key)
    )''')
    command_columns = {row['name'] for row in db.execute('PRAGMA table_info(printer_commands)')}
    if 'released_at' not in command_columns:
        db.execute('ALTER TABLE printer_commands ADD COLUMN released_at TEXT')
        db.execute('''UPDATE printer_commands SET released_at=updated_at
            WHERE state='confirmed' AND job_id IN (SELECT id FROM print_jobs WHERE status='completed')''')
    db.execute('''CREATE TABLE IF NOT EXISTS printer_operations (
        printer_id INTEGER PRIMARY KEY REFERENCES printers(id) ON DELETE RESTRICT,
        operation_id TEXT NOT NULL UNIQUE,
        job_id INTEGER NOT NULL REFERENCES print_jobs(id) ON DELETE RESTRICT,
        kind TEXT NOT NULL CHECK(kind IN ('start','upload')),
        state TEXT NOT NULL CHECK(state IN ('active','unknown')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )''')
    # Existing ambiguous starts must still block the entire device after upgrade.
    # Retain every command record; additional unresolved commands are checked at
    # reservation time and must each be reviewed if older code created a conflict.
    db.execute('''INSERT OR IGNORE INTO printer_operations
        (printer_id,operation_id,job_id,kind,state,created_at,updated_at)
        SELECT printer_id,id,job_id,'start','unknown',created_at,updated_at
        FROM printer_commands WHERE action='start' AND job_id IS NOT NULL
        AND (state IN ('sending','acknowledged','unknown') OR (state='confirmed' AND released_at IS NULL))
        ORDER BY created_at,id''')
    db.execute('''CREATE TABLE IF NOT EXISTS printer_operation_history (
        id INTEGER PRIMARY KEY,operation_id TEXT NOT NULL,
        printer_id INTEGER NOT NULL REFERENCES printers(id),
        job_id INTEGER NOT NULL REFERENCES print_jobs(id),
        state TEXT NOT NULL,actor_id INTEGER REFERENCES users(id),
        detail TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL
    )''')


def material_mapping_warnings(db: sqlite3.Connection) -> list[dict]:
    """Read-only clues for human review; no guessed repairs of historic ledgers."""
    return [dict(row) for row in db.execute('''
        SELECT j.id AS job_id,j.file_name,j.status,j.estimated_g AS job_estimate_g,
               SUM(m.estimated_g) AS material_estimate_g,COUNT(*) AS material_count
        FROM print_jobs j JOIN job_materials m ON m.job_id=j.id
        GROUP BY j.id HAVING SUM(m.estimated_g)<>j.estimated_g
        ORDER BY j.id
    ''')]
