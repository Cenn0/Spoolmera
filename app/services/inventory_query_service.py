"""Paged inventory/history queries and product-level restock planning."""
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

from fastapi import HTTPException

from app.auth import audit
from app.database import session, utc_now
from app.models import SpoolBatchInput
from app.services.inventory_service import insert_spool, spool_as_dict


SPOOL_SELECT = '''SELECT s.*,p.brand,p.name AS product_name,p.material,
    p.color_name,p.color_hex,p.diameter_mm,p.low_stock_threshold_g
    FROM spools s JOIN products p ON p.id=s.product_id'''


def spool_page(db_path: Path, *, archived='active', before_id=None, limit=50,
               q=None, material=None, status=None, product_id=None, low_stock=False) -> dict:
    clauses, values = [], []
    if archived != 'all':
        clauses.append('s.archived_at IS ' + ('NULL' if archived == 'active' else 'NOT NULL'))
    if before_id is not None:
        clauses.append('s.id<?')
        values.append(before_id)
    if product_id is not None:
        clauses.append('s.product_id=?')
        values.append(product_id)
    if material:
        clauses.append('p.material=?')
        values.append(material.upper())
    status_clauses = {'empty': 's.remaining_g=0', 'opened': 's.opened=1 AND s.remaining_g>0',
                      'sealed': 's.opened=0 AND s.remaining_g>0'}
    if status:
        clauses.append('(' + status_clauses[status] + ')')
    if low_stock:
        # Match the inventory warning definition; empty rolls have their own state.
        clauses.append('s.remaining_g>0 AND s.remaining_g<=p.low_stock_threshold_g')
    if q:
        # LIKE is parameterized; escaped wildcards make search literal.
        term = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        searchable = ('p.brand', 'p.name', 'p.material', 'p.color_name', 's.uid',
                      's.location', 's.notes', 's.batch', 'CAST(s.id AS TEXT)')
        clauses.append('(' + ' OR '.join(column + " LIKE ? ESCAPE '\\'" for column in searchable) + ')')
        values.extend([term] * len(searchable))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with session(db_path) as db:
        rows = db.execute(SPOOL_SELECT + where + ' ORDER BY s.id DESC LIMIT ?', (*values, limit + 1)).fetchall()
    items = [spool_as_dict(row) for row in rows[:limit]]
    return {'items': items, 'next_cursor': items[-1]['id'] if len(rows) > limit else None}


def spool_by_uid(db_path: Path, uid: str) -> dict:
    with session(db_path) as db:
        row = db.execute(SPOOL_SELECT + ' WHERE s.uid=?', (uid,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Spool not found.')
    return spool_as_dict(row)


def create_batch(db_path: Path, payload: SpoolBatchInput, actor_id: int) -> dict:
    digest = hashlib.sha256(json.dumps(payload.model_dump(mode='json', exclude={'request_id'}),
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    key = str(payload.request_id) if payload.request_id else None
    with session(db_path, write=True) as db:
        if key:
            prior = db.execute('SELECT * FROM inventory_batch_receipts WHERE actor_id=? AND request_key=?', (actor_id, key)).fetchone()
            if prior:
                if prior['payload_digest'] != digest:
                    raise HTTPException(409, 'This batch request ID was already used for different input.')
                return json.loads(prior['response_json'])
        ids = [insert_spool(db, payload.spool, actor_id) for _ in range(payload.count)]
        marks = ','.join('?' for _ in ids)
        rows = db.execute(SPOOL_SELECT + f' WHERE s.id IN ({marks}) ORDER BY s.id', ids).fetchall()
        items = [spool_as_dict(row) for row in rows]
        audit(db, actor_id, 'spool_batch_create', 'product', payload.spool.product_id)
        result = {'items': items, 'label_url': '/labels?uids=' + ','.join(item['uid'] for item in items) + '&size=60x40'}
        if key:
            db.execute('INSERT INTO inventory_batch_receipts VALUES(?,?,?,?,?)',
                       (actor_id, key, digest, json.dumps(result, separators=(',', ':')), utc_now()))
    return result


def unarchive(db_path: Path, spool_id: int, actor_id: int) -> dict:
    with session(db_path, write=True) as db:
        found = db.execute('SELECT archived_at FROM spools WHERE id=?', (spool_id,)).fetchone()
        if not found:
            raise HTTPException(404, 'Spool not found.')
        if found['archived_at'] is not None:
            db.execute('UPDATE spools SET archived_at=NULL WHERE id=?', (spool_id,))
            audit(db, actor_id, 'spool_unarchive', 'spool', spool_id)
        row = db.execute(SPOOL_SELECT + ' WHERE s.id=?', (spool_id,)).fetchone()
    return spool_as_dict(row)


def movements_page(db_path: Path, *, before_id=None, limit=50, spool_id=None,
                   job_id=None, actor_id=None, source=None, from_date=None, to_date=None, kind=None) -> dict:
    clauses, values = [], []
    for field, value in [('m.spool_id', spool_id), ('COALESCE(m.print_job_id,ao.job_id)', job_id),
                         ('m.actor_id', actor_id), ('m.source', source), ('m.kind', kind)]:
        if value is not None:
            clauses.append(field + '=?')
            values.append(value)
    if before_id is not None:
        clauses.append('m.id<?')
        values.append(before_id)
    if from_date and to_date and from_date > to_date:
        raise HTTPException(422, 'The start date must not follow the end date.')
    if from_date:
        clauses.append('m.created_at>=?')
        values.append(from_date.isoformat())
    if to_date:
        # Inclusive calendar day; ISO timestamps sort correctly for stored UTC dates.
        if to_date < date.max:
            clauses.append('m.created_at<?')
            values.append((to_date + timedelta(days=1)).isoformat())
    query = '''SELECT m.*,COALESCE(m.print_job_id,ao.job_id) AS job_id,s.uid AS spool_uid,
        p.brand,p.name AS product_name,p.material,p.color_name,p.color_hex,
        u.username AS actor_name,j.file_name AS job_file_name
        FROM movements m JOIN spools s ON s.id=m.spool_id
        JOIN products p ON p.id=s.product_id LEFT JOIN users u ON u.id=m.actor_id
        LEFT JOIN accounting_operations ao ON ao.id=m.accounting_operation_id
        LEFT JOIN print_jobs j ON j.id=COALESCE(m.print_job_id,ao.job_id)'''
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    with session(db_path) as db:
        rows = db.execute(query + ' ORDER BY m.id DESC LIMIT ?', (*values, limit + 1)).fetchall()
    items = [dict(row) for row in rows[:limit]]
    return {'items': items, 'next_cursor': items[-1]['id'] if len(rows) > limit else None}


def restock(db_path: Path) -> dict:
    with session(db_path) as db:
        rows = db.execute('''SELECT p.id AS product_id,p.brand,p.name,p.material,
            p.color_name,p.color_hex,p.target_stock_g,
            COALESCE(stock.remaining_g,0) AS remaining_g,
            COALESCE(stock.active_spools,0) AS active_spools,
            COALESCE(stock.sealed_spools,0) AS sealed_spools,
            COALESCE(reserved.reserved_g,0) AS reserved_g
            FROM products p
            LEFT JOIN (SELECT product_id,SUM(remaining_g) AS remaining_g,
                COUNT(*) AS active_spools,SUM(CASE WHEN opened=0 AND remaining_g>0 THEN 1 ELSE 0 END) AS sealed_spools
                FROM spools WHERE archived_at IS NULL GROUP BY product_id) stock ON stock.product_id=p.id
            LEFT JOIN (SELECT s.product_id,SUM(r.reserved_g) AS reserved_g
                FROM job_reservations r JOIN spools s ON s.id=r.spool_id
                WHERE s.archived_at IS NULL GROUP BY s.product_id) reserved ON reserved.product_id=p.id
            ORDER BY p.brand COLLATE NOCASE,p.name COLLATE NOCASE,p.id''').fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item['available_g'] = max(0, item['remaining_g'] - item['reserved_g'])
        # A reservation is advisory and is shown separately from physical stock.
        item['suggested_g'] = max(0, item['target_stock_g'] - item['remaining_g'])
        items.append(item)
    return {'items': items}
