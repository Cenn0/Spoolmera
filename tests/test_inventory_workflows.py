"""Complete inventory workflows: atomic batches, archive, history and restock."""
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import session
from app.main import create_app
from tests.support import authenticate


@pytest.fixture
def inventory(tmp_path):
    path = tmp_path / 'inventory.sqlite3'
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post('/api/products', json={'brand': 'Example', 'name': 'PLA',
            'material': 'PLA', 'color_name': 'Blue', 'target_stock_g': 1500}).json()['id']
        yield client, path, product


def test_batch_distinct_identity_stock_and_authenticated_print(inventory):
    client, path, product = inventory
    response = client.post('/api/spools/batch', json={'count': 5, 'spool': {
        'product_id': product, 'initial_g': 1000, 'location': 'Box A'}})
    assert response.status_code == 201, response.text
    batch = response.json()
    assert len(batch['items']) == 5
    assert len({UUID(item['uid']) for item in batch['items']}) == 5
    assert sum(item['remaining_g'] for item in batch['items']) == 5000
    labels = client.get(batch['label_url'])
    assert labels.status_code == 200
    assert labels.text.count('<article class="label"') == 5
    for item in batch['items']:
        assert f'/api/spools/{item["uid"]}/qr.svg' in labels.text
    assert client.get(batch['label_url'].replace('60x40', '50x30')).status_code == 200
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM movements WHERE source='registration' AND actor_id=1").fetchone()[0] == 5
    client.post('/api/auth/logout')
    assert client.get(batch['label_url']).status_code == 401


def test_batch_rolls_back_after_intermediate_failure(inventory, monkeypatch):
    client, path, product = inventory
    from app.services import inventory_query_service as queries
    original = queries.insert_spool
    calls = 0
    def fail_third(db, payload, actor):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise HTTPException(409, 'Simulated write conflict')
        return original(db, payload, actor)
    monkeypatch.setattr(queries, 'insert_spool', fail_third)
    failed = client.post('/api/spools/batch', json={'count': 5, 'spool': {'product_id': product, 'initial_g': 1000}})
    assert failed.status_code == 409
    with session(path) as db:
        assert db.execute('SELECT COUNT(*) FROM spools').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM movements').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='spool_create'").fetchone()[0] == 0


def test_batch_retry_keeps_the_same_physical_spools(inventory):
    client, path, product = inventory
    payload = {'count': 5, 'spool': {'product_id': product, 'initial_g': 1000}, 'request_id': str(uuid4())}
    first = client.post('/api/spools/batch', json=payload)
    second = client.post('/api/spools/batch', json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert len(client.get('/api/spools').json()) == 5
    assert client.post('/api/spools/batch', json={**payload, 'count': 6}).status_code == 409
    assert len(client.get('/api/spools').json()) == 5


def test_paginated_search_preserves_color_material_notes_and_literal_text(inventory):
    client, _, product = inventory
    sid = client.post('/api/spools', json={'product_id': product, 'initial_g': 1000,
        'notes': 'Keep 100% dry', 'batch': 'lot_1', 'location': 'Drawer'}).json()['id']
    for term in ('blue', 'PLA', '100%', 'lot_1', 'Drawer', str(sid)):
        found = client.get('/api/spools/page', params={'q': term}).json()['items']
        assert [row['id'] for row in found] == [sid]
    assert client.get('/api/spools/page', params={'q': 'lot%1'}).json()['items'] == []


def test_spool_search_folds_case_and_accents_without_changing_inventory(inventory):
    client, _, existing_product = inventory
    product_response = client.post('/api/products', json={
        'brand': 'Müller', 'name': 'Grün Weiß', 'material': 'PETG', 'color_name': 'Crème',
    })
    assert product_response.status_code == 201, product_response.text
    product_id = product_response.json()['id']
    first_response = client.post('/api/spools', json={
        'product_id': product_id, 'initial_g': 1000, 'remaining_g': 250,
        'location': 'Büro Süd', 'notes': 'Straße', 'batch': 'Café_1',
    })
    second_response = client.post('/api/spools', json={
        'product_id': product_id, 'initial_g': 1000,
    })
    unrelated_response = client.post('/api/spools', json={
        'product_id': existing_product, 'initial_g': 1000, 'batch': 'CafeX1',
    })
    assert all(response.status_code == 201 for response in (
        first_response, second_response, unrelated_response
    ))
    first = first_response.json()['id']
    second = second_response.json()['id']
    baseline = client.get('/api/spools/page?archived=all').json()['items']

    for query in ('MULLER', 'Mu\u0308ller', 'grun', 'GRÜN', 'weiss', 'creme'):
        found = client.get('/api/spools/page', params={'q': query}).json()['items']
        assert [row['id'] for row in found] == [second, first], query
    for query in ('buro', 'sud', 'STRASSE', 'cafe_1'):
        found = client.get('/api/spools/page', params={'q': query}).json()['items']
        assert [row['id'] for row in found] == [first], query

    # Wildcards stay literal even when a Unicode character was normalized.
    assert client.get('/api/spools/page', params={'q': 'Cafe%1'}).json()['items'] == []
    first_page = client.get('/api/spools/page', params={
        'q': 'GRUN', 'material': 'petg', 'product_id': product_id, 'limit': 1,
    }).json()
    assert [row['id'] for row in first_page['items']] == [second]
    assert first_page['next_cursor'] == second
    next_page = client.get('/api/spools/page', params={
        'q': 'GRUN', 'material': 'petg', 'product_id': product_id,
        'limit': 1, 'before_id': second,
    }).json()
    assert [row['id'] for row in next_page['items']] == [first]
    assert next_page['next_cursor'] is None
    assert [row['id'] for row in client.get('/api/spools/page', params={
        'q': 'grun', 'status': 'opened',
    }).json()['items']] == [first]
    assert client.get('/api/spools/page?archived=all').json()['items'] == baseline

    assert client.post(f'/api/spools/{second}/archive').status_code == 200
    assert [row['id'] for row in client.get('/api/spools/page', params={
        'q': 'grun', 'archived': 'archived',
    }).json()['items']] == [second]
    assert [row['id'] for row in client.get('/api/spools/page', params={
        'q': 'grun',
    }).json()['items']] == [first]


def test_archived_uuid_history_and_audited_reactivation(inventory):
    client, path, product = inventory
    spool = client.post('/api/spools/batch', json={'count': 1, 'spool': {'product_id': product,
        'initial_g': 1000, 'remaining_g': 300, 'location': 'Archive shelf'}}).json()['items'][0]
    sid, uid = spool['id'], spool['uid']
    assert client.post(f'/api/spools/{sid}/archive').status_code == 200
    assert client.get('/api/spools/page').json()['items'] == []
    archived = client.get('/api/spools/page?archived=archived&q=Archive&status=opened').json()['items']
    assert [row['uid'] for row in archived] == [uid]
    by_uid = client.get(f'/api/spools/by-uid/{uid}').json()
    assert by_uid['archived_at'] and by_uid['remaining_g'] == 300
    assert len(client.get(f'/api/movements/page?spool_id={sid}').json()['items']) == 1
    restored = client.post(f'/api/spools/{sid}/unarchive')
    assert restored.status_code == 200 and restored.json()['uid'] == uid
    assert client.post(f'/api/spools/{sid}/unarchive').status_code == 200
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='spool_unarchive' AND entity_id=?", (sid,)).fetchone()[0] == 1


def test_history_pagination_searches_beyond_recent_window(inventory):
    client, path, product = inventory
    sid = client.post('/api/spools', json={'product_id': product, 'initial_g': 1000}).json()['id']
    with session(path, write=True) as db:
        db.executemany('''INSERT INTO movements(spool_id,kind,delta_g,remaining_after_g,note,created_at,actor_id,source)
            VALUES(?,'consume',-1,?,'Historic use','2023-02-20T15:00:00+00:00',1,'manual')''',
            [(sid, 999 - i) for i in range(231)])
        db.execute('UPDATE spools SET remaining_g=769,opened=1 WHERE id=?', (sid,))
    base = f'/api/movements/page?spool_id={sid}&kind=consume&actor_id=1&source=manual&from_date=2023-02-20&to_date=2023-02-20&limit=100'
    ids, cursor = [], None
    while True:
        response = client.get(base + (f'&before_id={cursor}' if cursor else ''))
        assert response.status_code == 200, response.text
        page = response.json()
        ids.extend(item['id'] for item in page['items'])
        assert all(item['actor_name'] == 'testadmin' for item in page['items'])
        cursor = page['next_cursor']
        if cursor is None:
            break
    assert len(ids) == len(set(ids)) == 231
    assert ids == sorted(ids, reverse=True)
    assert client.get('/api/movements/page?from_date=2024-01-02&to_date=2024-01-01').status_code == 422


def test_history_free_text_search_finds_older_rows_across_fields_without_wildcards(inventory):
    client, path, original_product = inventory
    response = client.post('/api/products', json={
        'brand': 'Müller', 'name': 'Grün Weiß', 'material': 'PETG', 'color_name': 'Crème',
    })
    assert response.status_code == 201, response.text
    special = client.post('/api/spools', json={
        'product_id': response.json()['id'], 'initial_g': 1000,
    }).json()
    other = client.post('/api/spools', json={
        'product_id': original_product, 'initial_g': 1000,
    }).json()
    for note in ('Straße Café_100%', 'Café_100% spare'):
        assert client.post(f"/api/spools/{special['id']}/movements", json={
            'kind': 'consume', 'grams': 10, 'note': note,
        }).status_code == 201
    assert client.post(f"/api/spools/{other['id']}/movements", json={
        'kind': 'consume', 'grams': 5, 'note': 'CafeX100X',
    }).status_code == 201

    with session(path, write=True) as db:
        # Assign synthetic job metadata only; no printer command or accounting is executed.
        db.execute("""INSERT INTO printers(id,name,kind,base_url,created_at)
            VALUES(1,'Test','moonraker','http://192.168.50.20','2026-01-01')""")
        db.execute("""INSERT INTO print_jobs(id,printer_id,spool_id,file_name,estimated_g,created_at,updated_at)
            VALUES(1,1,?,'prototype_case.gcode',100,'2026-01-01','2026-01-01')""", (special['id'],))
        newest = db.execute("""SELECT id FROM movements WHERE spool_id=? AND kind='consume'
            ORDER BY id DESC LIMIT 1""", (special['id'],)).fetchone()['id']
        db.execute('UPDATE movements SET print_job_id=1 WHERE id=?', (newest,))

    base = client.get('/api/movements/page', params={'limit': 100}).json()['items']
    result = client.get('/api/movements/page', params={
        'q': 'MULLER cafe_100%', 'kind': 'consume', 'limit': 1,
    })
    assert result.status_code == 200, result.text
    first = result.json()
    assert len(first['items']) == 1
    assert first['next_cursor'] == first['items'][0]['id']
    later = client.get('/api/movements/page', params={
        'q': 'müller CAFÉ_100%', 'kind': 'consume', 'limit': 1,
        'before_id': first['next_cursor'],
    }).json()
    assert len(later['items']) == 1 and later['next_cursor'] is None
    assert first['items'][0]['id'] > later['items'][0]['id']
    assert {row['note'] for row in first['items'] + later['items']} == {
        'Straße Café_100%', 'Café_100% spare',
    }
    spool_uid = client.get('/api/spools/page', params={
        'product_id': response.json()['id'],
    }).json()['items'][0]['uid']
    for term in ('grun', 'WEISS', 'crème', spool_uid):
        results = client.get('/api/movements/page', params={'q': term}).json()['items']
        assert {row['spool_id'] for row in results} == {special['id']}, term
    assert len(client.get('/api/movements/page', params={'q': 'STRASSE'}).json()['items']) == 1
    assert len(client.get('/api/movements/page', params={
        'q': 'MULLER prototype_case.gcode',
    }).json()['items']) == 1
    assert len(client.get('/api/movements/page', params={
        'q': 'testadmin', 'kind': 'consume',
    }).json()['items']) == 3
    assert client.get('/api/movements/page', params={'q': 'cafe%100%'}).json()['items'] == []
    assert client.get('/api/movements/page', params={'q': 'MULLER cafe_100%',
        'spool_id': other['id']}).json()['items'] == []
    assert client.get('/api/movements/page', params={'q': 'MULLER', 'kind': 'initial',
        'from_date': '2027-01-01'}).json()['items'] == []
    assert client.get('/api/movements/page', params={'q': 'x' * 121}).status_code == 422
    assert client.get('/api/movements/page', params={'limit': 100}).json()['items'] == base


def test_restock_counts_spares_zero_stock_and_advisory_reservations(inventory):
    client, path, product = inventory
    zero = client.get('/api/inventory/restock').json()['items'][0]
    assert zero['remaining_g'] == 0 and zero['suggested_g'] == 1500
    client.post('/api/spools', json={'product_id': product, 'initial_g': 1000, 'remaining_g': 100})
    spare = client.post('/api/spools', json={'product_id': product, 'initial_g': 1000}).json()['id']
    state = client.get('/api/inventory/restock').json()['items'][0]
    assert state['remaining_g'] == 1100 and state['sealed_spools'] == 1
    assert state['suggested_g'] == 400
    item = client.get('/api/products').json()[0]
    from app.models import ProductInput
    data = {key: item[key] for key in ProductInput.model_fields}
    data['target_stock_g'] = 1000
    assert client.put(f'/api/products/{product}', json=data).status_code == 200
    state = client.get('/api/inventory/restock').json()['items'][0]
    assert state['suggested_g'] == 0
    # A reservation is displayed separately and does not mutate physical stock.
    with session(path, write=True) as db:
        db.execute("INSERT INTO printers(id,name,kind,base_url,created_at) VALUES(1,'Test','moonraker','http://192.168.50.20','2026-01-01')")
        db.execute("INSERT INTO print_jobs(id,printer_id,spool_id,file_name,estimated_g,created_at,updated_at) VALUES(1,1,?,'planned.gcode',500,'2026-01-01','2026-01-01')", (spare,))
        db.execute("INSERT INTO job_reservations(job_id,spool_id,reserved_g,created_at) VALUES(1,?,500,'2026-01-01')", (spare,))
    state = client.get('/api/inventory/restock').json()['items'][0]
    assert state['remaining_g'] == 1100 and state['reserved_g'] == 500
    assert state['available_g'] == 600 and state['suggested_g'] == 0


def test_optional_metadata_clears_without_erasing_required_fields(inventory):
    client, path, product = inventory
    sid = client.post('/api/spools', json={'product_id': product, 'initial_g': 1000,
        'purchase_price_cents': 2400, 'purchased_on': '2026-09-01'}).json()['id']
    result = client.patch(f'/api/spools/{sid}', json={'purchase_price_cents': None, 'purchased_on': None})
    assert result.status_code == 200, result.text
    spool = client.get('/api/spools').json()[0]
    assert spool['purchase_price_cents'] is None and spool['purchased_on'] is None
    assert client.patch(f'/api/spools/{sid}', json={'location': None}).status_code == 422


def test_viewer_can_read_archive_but_cannot_change_inventory(inventory):
    client, path, product = inventory
    sid = client.post('/api/spools', json={'product_id': product, 'initial_g': 1000}).json()['id']
    client.post(f'/api/spools/{sid}/archive')
    assert client.post('/api/auth/users', json={'username': 'viewer', 'password': 'viewer-password-2026', 'role': 'viewer'}).status_code == 201
    client.post('/api/auth/logout')
    login = client.post('/api/auth/login', json={'username': 'viewer', 'password': 'viewer-password-2026'})
    client.headers['X-CSRF-Token'] = login.json()['csrf_token']
    assert client.get('/api/spools/page?archived=all').status_code == 200
    assert client.get('/api/movements/page').status_code == 200
    assert client.get('/api/inventory/restock').status_code == 200
    assert client.post(f'/api/spools/{sid}/unarchive').status_code == 403
    assert client.post('/api/spools/batch', json={'count': 1, 'spool': {'product_id': product, 'initial_g': 1000}}).status_code == 403


def test_exact_product_filter_composes_with_cursor_and_archive(inventory):
    client, _, first = inventory
    # Similar names must not turn a product-specific link into broad text search.
    second = client.post('/api/products', json={'brand': 'Example', 'name': 'PLA 2',
        'material': 'PLA', 'color_name': 'Blue'}).json()['id']
    a = client.post('/api/spools/batch', json={'count': 3, 'spool': {'product_id': first,
        'initial_g': 1000}}).json()['items']
    client.post('/api/spools/batch', json={'count': 3, 'spool': {'product_id': second,
        'initial_g': 1000}})
    params = {'product_id': first, 'limit': 2}
    page = client.get('/api/spools/page', params=params).json()
    assert len(page['items']) == 2 and all(s['product_id'] == first for s in page['items'])
    following = client.get('/api/spools/page', params={**params, 'before_id': page['next_cursor']}).json()
    assert len(following['items']) == 1 and following['items'][0]['product_id'] == first
    client.post(f'/api/spools/{a[0]["id"]}/archive')
    archived = client.get('/api/spools/page', params={'product_id': first, 'archived': 'archived'}).json()
    assert [s['id'] for s in archived['items']] == [a[0]['id']]
    assert client.get('/api/spools/page', params={'product_id': -1}).status_code == 422
    assert client.get('/api/spools/page', params={'product_id': 99999}).json()['items'] == []


def test_label_sheet_honors_user_selected_order(inventory):
    client, _, product = inventory
    items = client.post('/api/spools/batch', json={'count': 3, 'spool': {
        'product_id': product, 'initial_g': 1000}}).json()['items']
    order = [items[2]['uid'], items[0]['uid'], items[1]['uid']]
    response = client.get('/labels', params={'uids': ','.join(order), 'lang': 'de'})
    assert response.status_code == 200
    offsets = [response.text.index(f'/api/spools/{uid}/qr.svg') for uid in order]
    assert offsets == sorted(offsets)


def test_low_stock_filter_runs_before_pagination_and_combines_with_existing_filters(inventory):
    client, path, product = inventory
    # Oldest roll would not be on the first unfiltered page.
    low = client.post('/api/spools', json={'product_id': product, 'initial_g': 1000,
        'remaining_g': 200, 'location': 'Dry box 100%'}).json()
    client.post('/api/spools/batch', json={'count': 5, 'spool': {'product_id': product, 'initial_g': 1000}})
    empty = client.post('/api/spools', json={'product_id': product, 'initial_g': 1000, 'remaining_g': 0}).json()
    with session(path) as db:
        before = [tuple(row) for row in db.execute('SELECT id,remaining_g,stock_revision FROM spools ORDER BY id')]
        movements = db.execute('SELECT COUNT(*) FROM movements').fetchone()[0]
    params = {'low_stock': 'true', 'limit': 1, 'material': 'PLA', 'status': 'opened',
              'product_id': product, 'q': '100%'}
    result = client.get('/api/spools/page', params=params)
    assert result.status_code == 200
    assert [item['id'] for item in result.json()['items']] == [low['id']]
    assert result.json()['next_cursor'] is None
    assert client.get('/api/spools/page?low_stock=true&status=empty').json()['items'] == []
    assert len(client.get('/api/spools/page?low_stock=false').json()['items']) == 7
    assert client.get('/api/spools/page?low_stock=unsupported').status_code == 422
    with session(path) as db:
        assert [tuple(row) for row in db.execute('SELECT id,remaining_g,stock_revision FROM spools ORDER BY id')] == before
        assert db.execute('SELECT COUNT(*) FROM movements').fetchone()[0] == movements
    assert client.post(f"/api/spools/{low['id']}/archive").status_code == 200
    assert client.get('/api/spools/page?low_stock=true').json()['items'] == []
    assert [item['id'] for item in client.get('/api/spools/page?low_stock=true&archived=archived').json()['items']] == [low['id']]


def test_low_stock_inclusive_product_threshold_and_cursor(inventory):
    client, path, product = inventory
    ids = []
    for remaining in [1, 200, 201, 50, 0, 199]:
        ids.append(client.post('/api/spools', json={'product_id': product, 'initial_g': 1000,
                                                 'remaining_g': remaining}).json()['id'])
    found, cursor = [], None
    while True:
        params = {'low_stock': 'true', 'limit': 2}
        if cursor is not None:
            params['before_id'] = cursor
        result = client.get('/api/spools/page', params=params).json()
        found.extend(item['id'] for item in result['items'])
        cursor = result['next_cursor']
        if cursor is None:
            break
    assert found == [ids[5], ids[3], ids[1], ids[0]]
    with session(path, write=True) as db:
        db.execute('UPDATE products SET low_stock_threshold_g=0 WHERE id=?', (product,))
    assert client.get('/api/spools/page?low_stock=true').json()['items'] == []
