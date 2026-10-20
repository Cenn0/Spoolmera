"""Complete, authenticated and spreadsheet-safe movement-history CSV exports."""
import csv
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import session
from app.main import create_app
from app.services.movement_csv_service import MOVEMENT_CSV_COLUMNS, stream_movements
from tests.support import authenticate


@pytest.fixture
def history(tmp_path):
    path = tmp_path / 'history.sqlite3'
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post('/api/products', json={
            'brand': 'Müller', 'name': 'Grün PLA', 'material': 'PLA', 'color_name': 'Crème',
        })
        assert product.status_code == 201, product.text
        spool = client.post('/api/spools', json={
            'product_id': product.json()['id'], 'initial_g': 1000,
        })
        assert spool.status_code == 201, spool.text
        yield client, path, spool.json()


def read_csv(response):
    assert response.status_code == 200, response.text
    assert response.content.startswith(b'\xef\xbb\xbf')
    return list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'), newline='')))


def test_history_csv_has_stable_versioned_headers_and_does_not_modify_inventory(history):
    client, path, spool = history
    before = client.get('/api/spools').json()
    empty = client.get('/api/movements/export.csv', params={'kind': 'consume'})
    assert read_csv(empty) == []
    header = empty.content.decode('utf-8-sig').splitlines()[0]
    assert tuple(header.split(',')) == MOVEMENT_CSV_COLUMNS
    assert empty.headers['cache-control'] == 'no-store'
    assert empty.headers['x-content-type-options'] == 'nosniff'
    assert 'attachment; filename="spoolmera-movements-v1.csv"' == empty.headers['content-disposition']
    assert client.get('/api/spools').json() == before


def test_export_fetches_every_filtered_row_not_only_first_page(history):
    client, path, spool = history
    with session(path, write=True) as db:
        db.executemany('''INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,actor_id,source)
            VALUES(?,'consume',-1,?,'Batch export','2023-02-20T15:00:00+00:00',1,'manual')''',
            [(spool['id'], 999 - i) for i in range(231)])
        db.execute('UPDATE spools SET remaining_g=769,opened=1 WHERE id=?', (spool['id'],))
    filters = {'spool_id': spool['id'], 'kind': 'consume', 'actor_id': 1,
               'source': 'manual', 'from_date': '2023-02-20', 'to_date': '2023-02-20'}
    response = client.get('/api/movements/export.csv', params=filters)
    exported = read_csv(response)
    assert len(exported) == 231
    assert all(item['schema_version'] == '1' and item['note'] == 'Batch export' for item in exported)
    ids = [int(item['movement_id']) for item in exported]
    assert ids == sorted(set(ids), reverse=True)
    assert all(item['created_at'].startswith('2023-02-20') for item in exported)
    paginated = []
    before = None
    while True:
        page = client.get('/api/movements/page', params={
            **filters, 'limit': 50, **({'before_id': before} if before else {}),
        }).json()
        paginated.extend(item['id'] for item in page['items'])
        before = page['next_cursor']
        if before is None:
            break
    assert ids == paginated


def test_export_matches_unicode_search_filters_and_includes_archived_spools(history):
    client, _, spool = history
    movement = client.post(f"/api/spools/{spool['id']}/movements",
        json={'kind': 'consume', 'grams': 15, 'note': 'Straße Café_100%'}).json()
    assert client.post(f"/api/spools/{spool['id']}/archive").status_code == 200
    filters = {'q': 'MULLER cafe_100%', 'kind': 'consume', 'spool_id': spool['id'],
               'actor_id': 1, 'source': 'manual'}
    paged = client.get('/api/movements/page', params=filters)
    assert paged.status_code == 200 and len(paged.json()['items']) == 1
    rows = read_csv(client.get('/api/movements/export.csv', params=filters))
    assert [int(row['movement_id']) for row in rows] == [
        item['id'] for item in paged.json()['items']
    ]
    assert rows[0]['spool_uid'] == spool['uid']
    assert rows[0]['delta_g'] == '-15'
    assert rows[0]['remaining_after_g'] == '985'
    assert rows[0]['actor_name'] == 'testadmin'
    assert rows[0]['note'] == 'Straße Café_100%'
    assert read_csv(client.get('/api/movements/export.csv', params={'q': 'cafe%100%'})) == []
    assert read_csv(client.get('/api/movements/export.csv', params={
        **filters, 'spool_id': spool['id'] + 2000,
    })) == []


def test_csv_quotes_multiline_notes_and_neutralizes_spreadsheet_formulas(history):
    client, path, spool = history
    note = ' \t=2+2\r\n"quoted",field'
    response = client.post(f"/api/spools/{spool['id']}/movements",
        json={'kind': 'consume', 'grams': 7, 'note': 'temporary'})
    assert response.status_code == 201, response.text
    with session(path, write=True) as db:
        db.execute("UPDATE movements SET note=?, source_ref=? WHERE spool_id=? AND kind='consume'",
                   (note, '@CMD()', spool['id']))
    rows = read_csv(client.get('/api/movements/export.csv', params={'kind': 'consume'}))
    assert len(rows) == 1
    assert rows[0]['note'] == "'" + note
    assert rows[0]['source_ref'] == "'@CMD()"
    # Negative gram deltas are numeric values, not spreadsheet formulas.
    assert rows[0]['delta_g'] == '-7'


@pytest.mark.parametrize('params', [
    {'from_date': '2026-01-02', 'to_date': '2026-01-01'},
    {'kind': 'invalid'},
    {'spool_id': -1},
    {'q': 'a' * 121},
    {'source': 'b' * 81},
    {'to_date': 'not-a-date'},
])
def test_invalid_export_filters_are_rejected_before_streaming(history, params):
    client, _, _ = history
    response = client.get('/api/movements/export.csv', params=params)
    assert response.status_code == 422, response.text


def test_history_export_requires_login_and_allows_viewers(history):
    client, _, _ = history
    viewer = client.post('/api/auth/users', json={
        'username': 'historyviewer', 'password': 'viewer-password-2026', 'role': 'viewer',
    })
    assert viewer.status_code == 201, viewer.text
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/movements/export.csv').status_code == 401
    signed = client.post('/api/auth/login', json={
        'username': 'historyviewer', 'password': 'viewer-password-2026',
    })
    assert signed.status_code == 200, signed.text
    assert signed.json()['role'] == 'viewer'
    assert read_csv(client.get('/api/movements/export.csv'))
    assert client.post('/api/products', json={'brand': 'forbidden'}).status_code == 403


def test_stream_uses_one_read_snapshot_while_new_movements_are_recorded(history):
    client, path, spool = history
    original = client.get('/api/movements/page').json()['items']
    stream = stream_movements(path)
    header = next(stream)
    first = next(stream)
    assert header.startswith('\ufeff')
    assert first
    # A concurrent writer should not affect the snapshot captured by the CSV.
    added = client.post(f"/api/spools/{spool['id']}/movements",
        json={'kind': 'consume', 'grams': 1, 'note': 'Later movement'})
    assert added.status_code == 201, added.text
    remaining = list(stream)
    assert len(remaining) + 1 == len(original)
    assert all('Later movement' not in record for record in [first, *remaining])
