"""Bambu LAN integration and security regression tests (no actual hardware)."""
import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.database import initialize_database, session
from app.main import create_app
from app.printers import PrinterInput, validate_printer_input
from app.infrastructure.printers import bambu
from app.infrastructure.printers.adapters import adapter_for
from tests.support import authenticate
from tests.test_security_jobs import make_inventory


def configured(monkeypatch):
    monkeypatch.setenv('FILAMENT_PRINTER_ALLOWED_IPS', '192.168.50.20')
    monkeypatch.setenv('FILAMENT_PRINTER_TOKEN_BAMBU1', '12345678')
    monkeypatch.setenv('FILAMENT_BAMBU_CERT_SHA256_BAMBU1', hashlib.sha256(b'printer-cert').hexdigest())
    return {'name':'Bambu test', 'kind':'bambu', 'base_url':'mqtts://192.168.50.20:8883',
            'token_env':'FILAMENT_PRINTER_TOKEN_BAMBU1', 'serial':'01P00C5A1002021', 'enabled':True}


def test_config_rejects_missing_pin_url_and_serial(monkeypatch):
    p = configured(monkeypatch)
    assert validate_printer_input(PrinterInput(**p)) == p['base_url']
    monkeypatch.delenv('FILAMENT_BAMBU_CERT_SHA256_BAMBU1')
    with pytest.raises(ValueError, match='fingerprint'):
        validate_printer_input(PrinterInput(**p))
    configured(monkeypatch)
    for field, bad in [('serial','../../../etc/passwd'), ('base_url','mqtts://127.0.0.1:8883'),
                       ('base_url','mqtts://192.168.50.20:8884'),
                       ('base_url','mqtts://user:pass@192.168.50.20:8883')]:
        with pytest.raises(ValueError):
            validate_printer_input(PrinterInput(**dict(p, **{field:bad})))


def test_status_normalizes_state_and_ams_without_silent_stock_change():
    state = bambu.parse_status({'print': {'gcode_state':'RUNNING', 'subtask_name':'part.3mf',
        'mc_percent':47, 'mc_remaining_time':31,'nozzle_temper':215.0,'bed_temper':60,
        'ams':{'ams':[{'id':'0','tray':[{'id':'1','tray_type':'PETG','tray_color':'F0A020FF','remain':72}]}]}}})
    assert state == {'state':'printing','filename':'part.3mf','progress_percent':47,
                     'remaining_minutes':31,'nozzle_c':215.0,'bed_c':60,
                     'ams':[{'unit':'0','tray':'1','material':'PETG','color':'F0A020FF','remaining_percent':72}]}
    adapter = adapter_for('bambu',status=lambda _:state,history=lambda _:[],lookup=lambda *_:None)
    job={'file_name':'part.3mf','observed_printing':0,'external_job_id':None}
    assert adapter.observe(None,job,[],state,set()).outcome == 'printing'
    state['state']='complete'
    job['observed_printing']=1
    assert adapter.observe(None,job,[],state,set()).outcome == 'needs_review'
    assert adapter.capabilities.supports_verified_completion is False


class FakeMqttStream:
    def __init__(self, packets):
        self.received = bytearray(b''.join(packets))
        self.sent = []
        self.timeout = None
    def recv(self, n):
        packet = bytes(self.received[:n]); del self.received[:n]; return packet
    def sendall(self, packet):
        self.sent.append(packet)
    def settimeout(self, timeout):
        self.timeout = timeout
    def __enter__(self): return self
    def __exit__(self, *args): pass


def test_pushall_and_control_packet_framing(monkeypatch):
    topic='device/01P00C5A1002021/report'
    partial={'print':{'mc_percent':31}}
    full={'print':{'gcode_state':'RUNNING','subtask_name':'job.3mf','mc_percent':42}}
    def report(body):
        return bambu._frame(0x30,bambu._text(topic)+json.dumps(body).encode())
    stream=FakeMqttStream([bambu._frame(0x90,b'\x00\x01\x00'),report(partial),report(full)])
    monkeypatch.setattr(bambu,'_connect',lambda *_:(stream,'01P00C5A1002021'))
    assert bambu.read_bambu_status({},lambda s:s)['progress_percent']==42
    assert b'pushall' in b''.join(stream.sent)
    assert b'device/01P00C5A1002021/request' in b''.join(stream.sent)
    control=FakeMqttStream([bambu._frame(0x40,b'\x00\x03')])
    monkeypatch.setattr(bambu,'_connect',lambda *_:(control,'01P00C5A1002021'))
    assert bambu.send_bambu_control({},lambda s:s,'cancel')==202
    assert b'"command":"stop"' in b''.join(control.sent)


def test_fingerprint_refuses_credential_before_any_mqtt_message(monkeypatch):
    p=configured(monkeypatch)
    class FakeTls:
        def getpeercert(self,binary_form=False): return b'not-the-pinned-cert'
        def settimeout(self,t): pass
        def sendall(self,data): raise AssertionError('credentials transmitted before pin validation')
        def close(self): pass
    class FakeContext:
        check_hostname=False
        verify_mode=None
        def wrap_socket(self,raw,server_hostname=None):return FakeTls()
    class FakeRaw:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(bambu.ssl,'SSLContext',lambda *_:FakeContext())
    monkeypatch.setattr(bambu.socket,'create_connection',lambda *_args,**_kw:FakeRaw())
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        bambu._connect(p,lambda url:url)


def test_routes_keep_pin_and_secret_out_of_database_and_require_operator_opt_in(tmp_path,monkeypatch):
    p=configured(monkeypatch)
    with TestClient(create_app(tmp_path/'bambu.sqlite3')) as client:
        authenticate(client)
        result=client.post('/api/printers',json=p)
        assert result.status_code==201,result.text
        identity=result.json()['id']
        exposed=client.get('/api/printers').json()[0]
        assert exposed['serial']==p['serial']
        assert exposed['token_env']==p['token_env']
        assert '12345678' not in json.dumps(exposed)
        with session(tmp_path/'bambu.sqlite3') as db:
            row=dict(db.execute('SELECT * FROM printers WHERE id=?',(identity,)).fetchone())
            assert row['serial']==p['serial']
            assert '12345678' not in json.dumps(row)
        assert client.post(f'/api/printers/{identity}/control',json={'action':'pause'}).status_code==403
        monkeypatch.setattr('app.printers.printer_status',lambda _: {'state':'printing','filename':'part.3mf','ams':[]})
        assert client.post(f'/api/printers/{identity}/probe').json()['state']=='printing'
        spool=make_inventory(client)
        job=client.post('/api/jobs',json={'printer_id':identity,'spool_id':spool,
            'file_name':'part.3mf','estimated_g':42})
        assert job.status_code==201,job.text
        monkeypatch.setenv('FILAMENT_PRINTER_CONTROL_ENABLED','1')
        assert client.post(f"/api/jobs/{job.json()['id']}/start").status_code==422
        assert client.post(f"/api/jobs/{job.json()['id']}/upload?file_name=part.3mf",
            content=b'G1 E1',headers={'content-type':'application/octet-stream'}).status_code==422


def test_migration_v10_upgrade_preserves_referenced_jobs(tmp_path,monkeypatch):
    configured(monkeypatch)
    path=tmp_path/'migrate.sqlite3'
    with TestClient(create_app(path)) as client:
        authenticate(client)
        pid=client.post('/api/printers',json={'name':'Old','kind':'octoprint',
            'base_url':'http://192.168.50.20:5000','token_env':'FILAMENT_PRINTER_TOKEN_BAMBU1',
            'enabled':True}).json()['id']
        sid=make_inventory(client)
        jid=client.post('/api/jobs',json={'printer_id':pid,'spool_id':sid,
            'file_name':'old.gcode','estimated_g':31}).json()['id']
    db=sqlite3.connect(path)
    try:
        db.execute('PRAGMA foreign_keys=OFF')
        db.executescript("""CREATE TABLE printers_legacy (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL CHECK(kind IN ('moonraker','octoprint')),
          base_url TEXT NOT NULL, token_env TEXT NOT NULL DEFAULT '',
          enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), created_at TEXT NOT NULL);
          INSERT INTO printers_legacy SELECT id,name,kind,base_url,token_env,enabled,created_at FROM printers;
          DROP TABLE printers; ALTER TABLE printers_legacy RENAME TO printers;
          PRAGMA user_version=10;""")
        db.commit()
    finally:db.close()
    initialize_database(path)
    with session(path) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT printer_id FROM print_jobs WHERE id=?',(jid,)).fetchone()[0]==pid
        assert 'bambu' in db.execute("SELECT sql FROM sqlite_master WHERE name='printers'").fetchone()[0]
