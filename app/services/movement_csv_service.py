"""Stream a complete, consistently filtered movement ledger as versioned CSV.

Exports are read-only; individual movements remain immutable. The response is
streamed from one SQLite read snapshot without materializing history in memory.
"""
import csv
import io
import sqlite3
from pathlib import Path
from typing import Iterator

from app.inventory_csv import _protect_csv_cell
from app.services.inventory_query_service import movement_query, _search_fold

MOVEMENT_CSV_COLUMNS = (
    'schema_version', 'movement_id', 'created_at', 'spool_id', 'spool_uid',
    'brand', 'product_name', 'material', 'color_name', 'kind', 'delta_g',
    'remaining_after_g', 'source', 'source_ref', 'actor_id', 'actor_name',
    'job_id', 'job_file_name', 'corrects_movement_id', 'accounting_operation_id',
    'note',
)
MOVEMENT_CSV_TEXT = {
    'created_at', 'spool_uid', 'brand', 'product_name', 'material', 'color_name',
    'kind', 'source', 'source_ref', 'actor_name', 'job_file_name',
    'accounting_operation_id', 'note',
}


def stream_movements(db_path: Path, *, spool_id=None, job_id=None, actor_id=None,
                     source=None, from_date=None, to_date=None, kind=None, q=None) -> Iterator[str]:
    """Return the full filtered export, independent of UI pagination.

    SQLite's thread affinity is disabled *only for this dedicated read-only
    connection*: Starlette may call successive next() operations on different
    worker threads. It consumes this iterator sequentially, never concurrently.
    The cursor stays on one SQLite read snapshot until the response is closed.
    """
    query, parameters = movement_query(
        spool_id=spool_id, job_id=job_id, actor_id=actor_id, source=source,
        from_date=from_date, to_date=to_date, kind=kind, q=q,
    )

    def generate() -> Iterator[str]:
        connection = sqlite3.connect(
            str(db_path), timeout=10, isolation_level=None, check_same_thread=False,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            if q and q.strip():
                connection.create_function('inventory_search_fold', 1, _search_fold, deterministic=True)
            cursor = connection.execute(query + ' ORDER BY m.id DESC', parameters)
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer, lineterminator='\r\n')
            writer.writerow(MOVEMENT_CSV_COLUMNS)
            yield '\ufeff' + buffer.getvalue()
            while batch := cursor.fetchmany(200):
                for row in batch:
                    buffer.seek(0)
                    buffer.truncate(0)
                    values = {
                        'schema_version': '1',
                        'movement_id': row['id'],
                        **dict(row),
                    }
                    writer.writerow([
                        _protect_csv_cell(value) if column in MOVEMENT_CSV_TEXT else value
                        for column in MOVEMENT_CSV_COLUMNS
                        for value in [values.get(column) if values.get(column) is not None else '']
                    ])
                    yield buffer.getvalue()
        finally:
            connection.close()

    return generate()
