"""Semantic upgrade/restart invariants, including legitimate jobs without T0."""
import sqlite3
from uuid import uuid4

import pytest

from app.database import SCHEMA, initialize_database, session
from app.jobs import MaterialMapping, MultiJobInput, insert_multi_job
from app.services.accounting_service import apply_consumption


def seed_database(path):
    initialize_database(path)
    with session(path, write=True) as db:
        db.execute("INSERT INTO users(id,username,password_hash,role,created_at) VALUES(1,'tester','unused','admin','2026-01-01')")
        db.execute("INSERT INTO products(id,uid,brand,name,material,color_name,color_hex,diameter_mm,created_at,updated_at) VALUES(1,?,'Test','PLA','PLA','Black','#000000',1.75,'2026-01-01','2026-01-01')", (str(uuid4()),))
        for spool_id in range(1, 9):
            db.execute("INSERT INTO spools(id,uid,product_id,initial_g,remaining_g,created_at) VALUES(?,?,1,1000,1000,'2026-01-01')", (spool_id, str(uuid4())))
        db.execute("INSERT INTO printers(id,name,kind,base_url,created_at) VALUES(1,'Test printer','moonraker','http://192.168.50.20','2026-01-01')")


@pytest.mark.parametrize('tools', [[1, 2], [3], [3, 7], list(range(8))])
@pytest.mark.parametrize('completed', [False, True])
def test_restart_preserves_explicit_materials_and_accounting(tmp_path, tools, completed):
    path = tmp_path / 'inventory.sqlite3'
    seed_database(path)
    job_id = insert_multi_job(path, MultiJobInput(printer_id=1, file_name='restart.gcode',
        materials=[MaterialMapping(tool=tool, spool_id=i + 1, estimated_g=(i + 1) * 10)
                   for i, tool in enumerate(tools)]), 1)
    if completed:
        with session(path, write=True) as db:
            apply_consumption(db, {'id': job_id}, 1)
    with session(path) as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM job_materials WHERE job_id=? ORDER BY tool', (job_id,))]
        before_movements = [tuple(row) for row in db.execute('SELECT * FROM movements ORDER BY id')]
    initialize_database(path)
    initialize_database(path)
    with session(path, write=True) as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM job_materials WHERE job_id=? ORDER BY tool', (job_id,))] == before
        assert [tuple(row) for row in db.execute('SELECT * FROM movements ORDER BY id')] == before_movements
        if not completed:
            assert apply_consumption(db, {'id': job_id}, 1)
        balances = dict(db.execute('SELECT id,remaining_g FROM spools'))
        for i in range(len(tools)):
            assert balances[i + 1] == 1000 - (i + 1) * 10


def test_legacy_job_without_materials_gets_exactly_one_mapping(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO products(id,brand,name,material,color_name,color_hex,diameter_mm,created_at,updated_at) VALUES(1,'Legacy','PLA','PLA','Black','#000000',1.75,'2020-01-01','2020-01-01')")
    db.execute("INSERT INTO spools(id,product_id,initial_g,remaining_g,created_at) VALUES(1,1,1000,1000,'2020-01-01')")
    db.execute("INSERT INTO printers(id,name,kind,base_url,created_at) VALUES(1,'Legacy','moonraker','http://192.168.50.20','2020-01-01')")
    db.execute("INSERT INTO print_jobs(id,printer_id,spool_id,file_name,estimated_g,created_at,updated_at) VALUES(1,1,1,'legacy.gcode',100,'2020-01-01','2020-01-01')")
    db.execute('PRAGMA user_version = 1')
    db.commit()
    db.close()
    initialize_database(path)
    initialize_database(path)
    with session(path) as db:
        rows = [tuple(r) for r in db.execute('SELECT job_id,tool,spool_id,estimated_g FROM job_materials')]
        assert rows == [(1, 0, 1, 100)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_main_schema_upgrade_preserves_uuid_and_stock(tmp_path):
    path = tmp_path / 'main.sqlite3'
    seed_database(path)
    with session(path) as db:
        before = [tuple(row) for row in db.execute('SELECT uid,remaining_g FROM spools ORDER BY id')]
        db.execute('PRAGMA user_version = 5')
    initialize_database(path)
    with session(path) as db:
        assert [tuple(row) for row in db.execute('SELECT uid,remaining_g FROM spools ORDER BY id')] == before
