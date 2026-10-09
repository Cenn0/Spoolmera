"""Offline ntfy bridge tests with mocked machine event responses."""
from pathlib import Path
from scripts import notification_bridge as bridge


def test_first_run_silently_initializes_and_later_sends(tmp_path,monkeypatch):
    state=tmp_path/"cursor.json"
    events=[{"id":1,"delta_g":-50,"kind":"consume","source":"manual","spool_uid":"x"}]
    sent=[]
    def fake(server,token,after):
        if after==0: return events,None
        if after==1: return [dict(events[0],id=2)],None
        return [],None
    monkeypatch.setattr(bridge,"request_events",fake)
    monkeypatch.setattr(bridge,"notify",lambda target,item:sent.append(item["id"]))
    assert bridge.run_once(state,"http://test","http://ntfy/test","secret")==0
    assert bridge.read_cursor(state)==1 and sent==[]
    assert bridge.run_once(state,"http://test","http://ntfy/test","secret")==1
    assert bridge.read_cursor(state)==2 and sent==[2]
    assert bridge.run_once(state,"http://test","http://ntfy/test","secret")==0


def test_bad_state_fails_closed(tmp_path):
    state=tmp_path/"cursor.json"
    state.write_text('{"cursor": -10}')
    try:
        bridge.read_cursor(state)
        assert False
    except RuntimeError:
        pass
