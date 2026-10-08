"""Offline restore preserves previous state and refuses unsafe preconditions."""
import sqlite3
from contextlib import closing
import pytest
from app.database import initialize_database
from scripts.restore import restore


def test_restore_database_and_preserve_old_snapshot(tmp_path):
    active=tmp_path/"active.sqlite3"
    initialize_database(active)
    with closing(sqlite3.connect(active)) as db:
        db.execute("""INSERT INTO products(uid,brand,name,material,color_name,color_hex,
                   diameter_mm,notes,created_at,updated_at)
                   VALUES('a','Old','Black','PLA','Black','#000000',1.75,'','','')""")
        db.commit()
    saved=tmp_path/"saved.sqlite3"
    with closing(sqlite3.connect(active)) as src,closing(sqlite3.connect(saved)) as target:
        src.backup(target)
        target.commit()
    with closing(sqlite3.connect(active)) as db:
        db.execute("UPDATE products SET brand='Later'")
        db.commit()
    old=restore(saved,active,confirm=True)
    assert old is not None and old.is_file()
    with closing(sqlite3.connect(active)) as db:
        assert db.execute("SELECT brand FROM products").fetchone()[0]=="Old"
    with closing(sqlite3.connect(old)) as db:
        assert db.execute("SELECT brand FROM products").fetchone()[0]=="Later"


def test_restore_requires_explicit_confirmation_and_stopped_wal(tmp_path):
    active=tmp_path/"db.sqlite3";saved=tmp_path/"backup.sqlite3"
    initialize_database(active)
    with closing(sqlite3.connect(active)) as src,closing(sqlite3.connect(saved)) as target:
        src.backup(target)
    with pytest.raises(RuntimeError,match="confirm"):
        restore(saved,active)
    sidecar=tmp_path/"db.sqlite3-wal"
    sidecar.write_bytes(b"busy")
    with pytest.raises(RuntimeError,match="WAL/SHM"):
        restore(saved,active,confirm=True)
