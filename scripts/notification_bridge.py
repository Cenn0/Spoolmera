#!/usr/bin/env python3
"""Optional local notification bridge for a user-hosted ntfy-compatible endpoint.

Requires a scoped "events_read" token. At least once delivery: if the network
acknowledges but the cursor cannot be written, an event may be sent twice.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirect())


def required_environment() -> tuple[str,str,str]:
    server=os.environ.get("FILAMENT_MANAGER_URL","http://filament-manager:8765").rstrip("/")
    topic=os.environ.get("FILAMENT_NTFY_URL","")
    token=os.environ.get("FILAMENT_AUTOMATION_TOKEN","")
    for name,url in (("FILAMENT_MANAGER_URL",server),("FILAMENT_NTFY_URL",topic)):
        parsed=urlsplit(url)
        if (parsed.scheme not in {"http","https"} or not parsed.netloc
            or parsed.username or parsed.password or parsed.fragment):
            raise RuntimeError(name+" must be a valid HTTP(S) URL without embedded credentials.")
    if not token.startswith("fmm_") or len(token)<45:
        raise RuntimeError("FILAMENT_AUTOMATION_TOKEN must be a scoped events_read token.")
    return server,topic,token


def request_events(server:str,token:str,after:int)->tuple[list[dict],int|None]:
    url=server+"/api/automation/v1/movements?after="+str(after)+"&limit=200"
    request=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,
                                                "Accept":"application/json"})
    with OPENER.open(request,timeout=10) as response:
        body=response.read(512*1024+1)
    if len(body)>512*1024:
        raise RuntimeError("Automation response too large.")
    result=json.loads(body)
    if result.get("schema_version")!="1" or not isinstance(result.get("events"),list):
        raise RuntimeError("Unexpected automation response.")
    return result["events"],result.get("next_after")


def notify(topic:str,event:dict)->None:
    delta=int(event["delta_g"])
    description=("consumed " + str(-delta)+" g" if delta<0
                 else "added "+str(delta)+" g")
    text=("Spool "+str(event["spool_uid"])+" "+description+
          " · "+str(event["kind"])+" · "+str(event["source"]))
    payload=text.encode("utf-8")[:2048]
    request=urllib.request.Request(topic,data=payload,
        headers={"Content-Type":"text/plain; charset=utf-8","Title":"Filament Manager"},
        method="POST")
    with OPENER.open(request,timeout=10) as response:
        if response.status<200 or response.status>=300:
            raise RuntimeError("Notification endpoint rejected the event.")


def read_cursor(state:Path)->int|None:
    if not state.exists():
        return None
    data=json.loads(state.read_text(encoding="utf-8"))
    cursor=data["cursor"]
    if type(cursor) is not int or cursor<0:
        raise RuntimeError("Invalid notification cursor state.")
    return cursor


def save_cursor(state:Path,cursor:int)->None:
    state.parent.mkdir(parents=True,exist_ok=True)
    tmp=state.with_suffix(state.suffix+".tmp")
    tmp.write_text(json.dumps({"cursor":cursor}),encoding="utf-8")
    os.replace(tmp,state)


def run_once(state:Path,server:str,topic:str,token:str)->int:
    cursor=read_cursor(state)
    initial=(cursor is None)
    current=0 if initial else cursor
    emitted=0
    for page_number in range(100):
        events,next_cursor=request_events(server,token,current)
        for event in events:
            event_id=event["id"]
            if type(event_id) is not int or event_id<=current:
                raise RuntimeError("Non-monotonic automation cursor.")
            if not initial:
                notify(topic,event)
                emitted+=1
            current=event_id
            save_cursor(state,current)
        if not events or next_cursor is None:
            if initial and not state.exists():
                save_cursor(state,current)
            return emitted
    raise RuntimeError("More than 20,000 unread events; investigate before sending.")


def main() -> None:
    parser=argparse.ArgumentParser(description="Local event-to-notification bridge")
    parser.add_argument("--state",default="/state/notification-cursor.json")
    parser.add_argument("--loop",action="store_true")
    parser.add_argument("--interval",type=int,default=60)
    args=parser.parse_args()
    if not 30<=args.interval<=3600:
        parser.error("Interval must be between 30 and 3600 seconds.")
    server,topic,token=required_environment()
    while True:
        try:
            count=run_once(Path(args.state),server,topic,token)
            print(f"Notification cycle successful; delivered={count}",flush=True)
        except (OSError,ValueError,KeyError,TypeError,RuntimeError,urllib.error.URLError) as exc:
            print(f"Notification cycle failed: {type(exc).__name__}",flush=True)
            if not args.loop:
                raise SystemExit(1) from None
        if not args.loop:
            return
        time.sleep(args.interval)


if __name__=="__main__":
    main()
