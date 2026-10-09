"""Location-board updates use an optional atomic precondition, with no stock debit."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.database import session
from tests.support import authenticate


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / 'inventory.sqlite3'
    with TestClient(create_app(path)) as client:
        authenticate(client)
        product = client.post('/api/products', json={
            'brand': 'Example', 'name': 'PLA', 'material': 'PLA', 'color_name': 'Blue',
        })
        assert product.status_code == 201
        spool = client.post('/api/spools', json={
            'product_id': product.json()['id'], 'initial_g': 1000,
            'remaining_g': 730, 'location': 'Shelf A', 'notes': 'Do not dry',
        })
        assert spool.status_code == 201
        yield client, path, spool.json()['id']


def test_board_location_is_atomic_conditional_and_audited(setup):
    client, path, spool_id = setup
    url = f'/api/spools/{spool_id}'
    original = client.get('/api/spools').json()[0]
    first = client.patch(url, json={'location': 'Drawer C', 'expected_location': 'Shelf A'})
    assert first.status_code == 200, first.text
    stale = client.patch(url, json={'location': 'Shelf B', 'expected_location': 'Shelf A'})
    assert stale.status_code == 409 and 'location changed' in stale.json()['detail']
    updated = client.get('/api/spools').json()[0]
    assert updated['location'] == 'Drawer C'
    assert updated['remaining_g'] == original['remaining_g'] == 730
    assert updated['notes'] == 'Do not dry'
    assert updated['stock_revision'] == original['stock_revision']
    assert len(client.get(f'/api/spools/{spool_id}/movements').json()) == 1
    with session(path) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='spool_update' AND entity_id=?",(spool_id,)).fetchone()[0] == 1


def test_legacy_patch_and_unassigned_are_backward_compatible(setup):
    client, _, spool_id = setup
    url = f'/api/spools/{spool_id}'
    assert client.patch(url, json={'notes': 'Review later'}).status_code == 200
    assert client.patch(url, json={'location': '', 'expected_location': 'Shelf A'}).status_code == 200
    assert client.patch(url, json={'location': 'Shelf B', 'expected_location': ''}).status_code == 200
    assert client.get('/api/spools').json()[0]['location'] == 'Shelf B'
    assert client.patch(url, json={'expected_location': 'Shelf B'}).status_code == 422


def test_archived_and_invalid_location_rejected_without_change(setup):
    client, path, spool_id = setup
    url = f'/api/spools/{spool_id}'
    assert client.patch(url, json={'location': 'X' * 121, 'expected_location': 'Shelf A'}).status_code == 422
    assert client.patch(url, json={'location': 'Shelf B', 'expected_location': 'Wrong'}).status_code == 409
    assert client.post(url + '/archive').status_code == 200
    assert client.patch(url, json={'location': 'Drawer C', 'expected_location': 'Shelf A'}).status_code == 404
    with session(path) as db:
        assert db.execute('SELECT location FROM spools WHERE id=?',(spool_id,)).fetchone()[0] == 'Shelf A'
