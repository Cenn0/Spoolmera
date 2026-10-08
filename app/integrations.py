"""Versioned read-only inventory contract for future printer and slicer adapters.

No printer connection, remote command execution, or automatic stock mutation is
implemented. A future adapter must introduce authenticated, idempotent writes.
"""
import sqlite3


def get_integration_capabilities() -> dict:
    return {
        "schema_version": "1",
        "inventory_read": True,
        "usage_write": False,
        "printer_connections": False,
        "slicer_connections": False,
    }


def get_inventory_snapshot(db: sqlite3.Connection) -> dict:
    rows = db.execute(
        """SELECT s.uid AS spool_uid, p.uid AS product_uid, p.brand,
                  p.name AS product_name, p.material, p.color_name,
                  p.color_hex, p.diameter_mm, s.initial_g, s.remaining_g,
                  s.opened, s.location
           FROM spools s JOIN products p ON p.id=s.product_id
           WHERE s.archived_at IS NULL ORDER BY s.id"""
    ).fetchall()
    return {
        "schema_version": "1",
        "spools": [{**dict(row), "opened": bool(row["opened"])} for row in rows],
    }
