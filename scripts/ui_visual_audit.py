"""Reproducible visual inventory of Spoolmera's routes and interactive states.

After building the frontend, run a complete isolated audit::

  python scripts/ui_visual_audit.py --serve --strict \
    --output /tmp/spoolmera-visual-audit

This starts the real backend in a child process with a temporary database and
synthetic fixtures, replaces only that process's outbound printer-poll cycle,
and terminates the server after capture. Playwright Chromium must be installed;
SPOOLMERA_TEST_BROWSER_EXECUTABLE optionally selects an existing executable.
Use --base-url plus --seed only for a disposable loopback server whose printer
polling is already disabled and whose bootstrap/fixture configuration is set.

The default matrix is German, light/dark, desktop 1440x1000 and mobile
390x844 (296 captures). ``--languages en`` selects an English pass;
``--only 'spools-*'`` (alias: --states)
and ``--contexts desktop-dark`` allow focused reruns. All persisted fixture
writes use the normal API. Explicitly labelled browser response fixtures
exercise unavailable catalog/hardware and initial-setup presentation states.
The browser never sends physical printer commands. Screenshots, JSON metrics
and an HTML contact index are emitted. --strict requires complete requested
state coverage, no page errors or document overflow, and the concrete layout
invariants documented in METRICS below. General overflow/visibility metrics
remain review leads; screenshots still require human visual inspection.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, nullcontext
import fnmatch
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROUTES = {
    "overview": "/", "spools-cards": "/spools", "batch": "/spools/batch",
    "spoolman-import": "/import/spoolman", "catalog": "/catalog",
    "filaments": "/filaments", "history": "/history", "restock": "/restock",
    "integrations": "/integrations", "jobs": "/jobs", "printers": "/printers",
    "operations": "/diagnostics", "users": "/users", "account": "/account",
    "access-denied": "/access-denied",
}
VIEWPORTS = {"desktop": {"width": 1440, "height": 1000}, "mobile": {"width": 390, "height": 844}}
PASSWORD = "visual-audit-password-only-2026"


def translations() -> dict[str, str]:
    result = {}
    folder = Path(__file__).resolve().parents[1] / "frontend/src/app/core/i18n"
    pair = re.compile(r'''^\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')''', re.M)
    for path in folder.glob("*.de.ts"):
        for key, value in pair.findall(path.read_text()):
            result[ast.literal_eval(key)] = ast.literal_eval(value)
    return result


METRICS = r"""() => {
  const root = document.documentElement;
  const vw = root.clientWidth;
  const rect = el => { const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}; };
  const rendered = el => {const s=getComputedStyle(el),r=el.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;};
  const label = el => (el.id?'#'+el.id:el.tagName.toLowerCase()+'.'+String(el.className).replace(/\s+/g,'.')).slice(0,140);
  const intentionalScroll = el => {for(let p=el.parentElement;p&&p!==root;p=p.parentElement){const s=getComputedStyle(p);if(['auto','scroll','hidden','clip'].includes(s.overflowX)&&p.scrollWidth>p.clientWidth+1)return label(p);}return null;};
  const outside=[],clipped=[],tiny=[],images=[];
  for(const el of document.querySelectorAll('main *,dialog[open] *')){
    if(!rendered(el)||['OPTION','SVG','PATH'].includes(el.tagName))continue;
    const r=rect(el),s=getComputedStyle(el),text=(el.textContent||'').trim().replace(/\s+/g,' ').slice(0,120);
    if((r.x < -1 || r.right > vw+1) && !intentionalScroll(el))outside.push({element:label(el),text,rect:r});
    if(!['INPUT','SELECT','TEXTAREA'].includes(el.tagName)&&text&&el.children.length===0&&el.scrollWidth>el.clientWidth+2&&['hidden','clip'].includes(s.overflowX)&&s.textOverflow!=='ellipsis')clipped.push({element:label(el),text,client:el.clientWidth,scroll:el.scrollWidth});
    if(text&&el.children.length===0&&parseFloat(s.fontSize)<11)tiny.push({element:label(el),text,size:s.fontSize});
  }
  for(const el of document.images)if(rendered(el)&&(!el.complete||el.naturalWidth===0))images.push({src:el.getAttribute('src')});
  const controls=[...document.querySelectorAll('button,input,select,textarea,a.btn,summary')].filter(rendered).map(el=>({element:label(el),name:el.getAttribute('aria-label')||el.innerText||el.name||'',rect:rect(el),disabled:!!el.disabled}));
  const scrollRegions=[...document.querySelectorAll('*')].filter(el=>rendered(el)&&['auto','scroll'].includes(getComputedStyle(el).overflowX)&&el.scrollWidth>el.clientWidth+2).map(el=>({element:label(el),viewport:el.clientWidth,content:el.scrollWidth}));
  const checks=[];
  const check=(name,passed,actual)=>checks.push({name,passed,actual});
  for(const qr of document.querySelectorAll('.label img'))if(rendered(qr))check('Printed label QR image loads successfully',qr.complete&&qr.naturalWidth>0,{src:qr.getAttribute('src'),complete:qr.complete,naturalWidth:qr.naturalWidth});
  for(const name of document.querySelectorAll('.label-product strong'))if(rendered(name)){
    const product=rect(name.closest('.label-product')),r=rect(name),style=getComputedStyle(name);
    const lineHeight=parseFloat(style.lineHeight)||parseFloat(style.fontSize)*1.2;
    check('Printed label retains at least the first product-name line',r.y>=product.y-1&&r.y+Math.min(lineHeight,r.height)<=product.bottom+1,{product,name:r,lineHeight});
  }
  for(const title of document.querySelectorAll('.detail-summary h3'))if(rendered(title)){
    check('Spool detail title fits its text column',title.scrollWidth<=title.clientWidth+1,{client:title.clientWidth,scroll:title.scrollWidth});
    const status=title.closest('.detail-summary').querySelector('.status');
    if(status&&rendered(status)){const a=rect(title),b=rect(status);check('Spool detail title and status do not overlap',a.right<=b.x+1||b.right<=a.x+1||a.bottom<=b.y+1||b.bottom<=a.y+1,{title:a,status:b});}
  }
  const board=document.querySelector('.storage-board');
  if(board&&rendered(board)){
    const b=rect(board),lanes=[...board.querySelectorAll('.storage-lane')].filter(rendered);
    check('Every storage lane is reachable without horizontal page or board scrolling',board.scrollWidth<=board.clientWidth+1&&lanes.every(el=>{const r=rect(el);return r.x>=b.x-1&&r.right<=b.right+1}),{viewport:board.clientWidth,content:board.scrollWidth,lanes:lanes.map(el=>rect(el))});
    const counts=lanes.map(el=>el.querySelectorAll('.storage-spool').length),heights=lanes.map(el=>el.getBoundingClientRect().height);
    if(counts.length>1&&Math.max(...counts)-Math.min(...counts)>1)check('Asymmetric storage lanes retain their content height',Math.max(...heights)-Math.min(...heights)>1,{counts,heights});
  }
  for(const id of document.querySelectorAll('.label-identity small'))if(rendered(id))check('Selected label keeps its complete physical spool ID visible',id.scrollWidth<=id.clientWidth+1,{text:id.textContent,client:id.clientWidth,scroll:id.scrollWidth});
  for(const link of document.querySelectorAll('.printer-detail .detail-movement a'))if(rendered(link)){
    const r=rect(link),parent=rect(link.closest('.detail-movement'));
    check('Loaded-spool identity has room beside assignment controls',r.width+1>=Math.min(160,parent.width/2),{link:r.width,row:parent.width});
  }
  for(const dialog of document.querySelectorAll('dialog[open]')){
    const d=rect(dialog),header=dialog.querySelector('.modal-header'),close=dialog.querySelector('.close-button');
    if(header&&close){const h=rect(header),c=rect(close);check('Dialog header and close control remain visible after scrolling',h.y>=Math.max(0,d.y)-1&&h.bottom<=Math.min(innerHeight,d.bottom)+1&&c.x>=d.x-1&&c.right<=d.right+1&&c.y>=Math.max(0,d.y)-1&&c.bottom<=Math.min(innerHeight,d.bottom)+1,{dialog:d,header:h,close:c});}
  }
  return {viewport:{width:vw,height:innerHeight},document:{width:root.scrollWidth,height:root.scrollHeight},horizontalOverflow:Math.max(0,root.scrollWidth-vw),outside:outside.slice(0,40),clippedText:clipped.slice(0,25),smallText:tiny.slice(0,25),brokenImages:images,scrollRegions,controls,checks,theme:root.dataset.theme,language:root.lang,heading:document.querySelector('h1')?.innerText||'',dialogs:[...document.querySelectorAll('dialog[open],[role="dialog"][aria-modal="true"]')].map(el=>({rect:rect(el),scrollHeight:el.scrollHeight,clientHeight:el.clientHeight}))};
}"""


class Audit:
    def __init__(self, args, browser):
        self.args, self.browser = args, browser
        self.base = args.base_url.rstrip("/")
        self.out = Path(args.output).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.de = translations()
        self.records, self.previous_expected = [], set()
        if args.append and (self.out/"manifest.json").exists():
            previous=json.loads((self.out/"manifest.json").read_text())
            self.records=list({(r["language"],r["context"],r["state"]):r for r in previous["captures"]}.values())
            self.previous_expected={tuple(item) for item in previous.get("requestedMatrix",[])}
        self.auth_state, self.spools, self.products, self.printers, self.jobs = {}, [], [], [], []
        self.page = self.context = None
        self.current = ""
        self.errors = []
        self.mocks = []

    def api(self, request, method, path, data=None, headers=None, required=True):
        response = request.fetch(self.base + path, method=method, data=data, headers=headers or {})
        if required and not response.ok:
            raise RuntimeError(f"Fixture API {method} {path}: HTTP {response.status}: {response.text()[:300]}")
        return response

    def authenticate_and_seed(self):
        context = self.browser.new_context()
        request = context.request
        setup = self.api(request, "GET", "/api/auth/status").json()["needs_setup"]
        credentials = {"username": self.args.username, "password": os.environ.get(self.args.password_env, PASSWORD)}
        if setup:
            token = os.environ.get(self.args.bootstrap_env, "")
            if not token:
                raise RuntimeError(f"Fresh server requires {self.args.bootstrap_env} in the environment.")
            result = self.api(request, "POST", "/api/auth/setup", credentials, {"X-Bootstrap-Token": token})
        else:
            result = self.api(request, "POST", "/api/auth/login", credentials)
        headers = {"X-CSRF-Token": result.json()["csrf_token"]}
        write = lambda path, data: self.api(request, "POST", path, data, headers).json()
        products = self.api(request, "GET", "/api/products").json()
        if self.args.seed and not any(p["brand"] == "Visual workshop" for p in products):
            samples = [
                ("Visual workshop", "Matte PLA", "PLA", "Sage", "#82a392", [740,1000,520,310], "Studio / Box A"),
                ("Visual workshop", "PETG", "PETG", "Ocean blue", "#3a7e9a", [140], "Werkstatt / Regal B"),
                ("Visual workshop", "Silk PLA", "PLA", "Warm amber", "#d69a4b", [1000], ""),
                ("Visual workshop", "Flexible TPU", "TPU", "Graphite", "#464f5b", [0], "Drucker / Materialschrank"),
                ("Werkstatt für außergewöhnlich anspruchsvolle Filamentmaterialien", "Temperaturbeständiges kohlenstofffaserverstärktes Prototypenmaterial für lange Produktbezeichnungen", "PA6-CF", "Dunkles Anthrazit mit feinen silberfarbenen Einsprengseln", "#716882", [850], "Ersatzmaterial / geschlossener Trockenschrank / oberes Fach links"),
            ]
            for brand,name,material,color,color_hex,weights,location in samples:
                product=write("/api/products", {"brand":brand,"name":name,"material":material,"color_name":color,"color_hex":color_hex,"diameter_mm":1.75,"density_g_cm3":1.24,"nozzle_min_c":210,"nozzle_max_c":240,"bed_min_c":45,"bed_max_c":60,"target_stock_g":2000,"notes":"Synthetic visual-audit sample. No physical inventory."})
                for weight in weights:
                    write("/api/spools", {"product_id":product["id"],"initial_g":1000,"remaining_g":weight,"opened":weight<1000,"location":location,"tare_g":180,"purchase_price_cents":2499,"purchase_currency":"EUR","purchased_on":"2026-10-01","batch":"VISUAL-2026-10","notes":"Synthetic sample for layout review only."})
            first=self.api(request,"GET","/api/spools").json()[0]
            write(f'/api/spools/{first["id"]}/drying', {"temperature_c":50,"duration_minutes":240,"dried_at":"2026-10-09T09:00:00+00:00","note":"Synthetic material care history for visual audit."})
            write(f'/api/spools/{first["id"]}/movements', {"kind":"adjust","grams":-1,"note":"Synthetic visual audit adjustment entry."})
        self.products=self.api(request,"GET","/api/products").json()
        self.spools=self.api(request,"GET","/api/spools").json()
        self.printers=self.api(request,"GET","/api/printers").json()
        if self.args.seed and not self.printers:
            configurations=[
                {"name":"Visual workshop · Klipper","kind":"moonraker","base_url":"http://192.168.250.2:7125","enabled":True},
                {"name":"Visual workshop · Bambu Lab P1S with AMS","kind":"bambu","base_url":"mqtts://192.168.250.3:8883","token_env":"SPOOLMERA_PRINTER_TOKEN_VISUAL","serial":"VISUAL202600001","enabled":True},
            ]
            for config in configurations:
                write("/api/printers",config)
            self.printers=self.api(request,"GET","/api/printers").json()
            full=[s for s in self.spools if s["remaining_g"]>=100]
            for index,printer in enumerate(self.printers):
                self.api(request,"PUT",f'/api/printers/{printer["id"]}/slots/0',{"spool_id":full[index%len(full)]["id"]},headers)
        self.jobs=self.api(request,"GET","/api/jobs").json()
        if self.args.seed and not self.jobs and self.printers:
            full=[s for s in self.spools if s["remaining_g"]>=100]
            write("/api/jobs/multi",{"printer_id":self.printers[0]["id"],"file_name":"visual-audit/long-prototype-enclosure-with-support-and-multimaterial-mapping.gcode","materials":[{"tool":0,"spool_id":full[0]["id"],"estimated_g":85},{"tool":1,"spool_id":full[1]["id"],"estimated_g":45}],"note":"Synthetic print metadata only. No printer was contacted."})
            self.jobs=self.api(request,"GET","/api/jobs").json()
        if self.args.seed:
            users=self.api(request,"GET","/api/auth/users").json()
            if not any(u["username"]=="visual-viewer" for u in users):
                write("/api/auth/users",{"username":"visual-viewer","password":PASSWORD,"role":"viewer"})
        self.auth_state=context.storage_state()
        context.close()

    def wanted(self, name):
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.args.states.split(","))

    def word(self, english):
        return self.de.get(english,english) if self.language=="de" else english

    def button(self, english, scope=None):
        return (scope or self.page).get_by_role("button",name=self.word(english),exact=True)

    def goto(self, path):
        self.page.goto(self.base+path,wait_until="networkidle")
        expect(self.page.locator("h1").first).to_be_visible()
        self.page.evaluate("window.scrollTo({top:0,behavior:'instant'})")

    def settle(self):
        self.page.wait_for_load_state("networkidle")
        self.page.evaluate("() => document.fonts.ready")
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")

    def capture(self,name,focus=None,note=""):
        if not self.wanted(name):
            # Selection suppresses artifacts, not Angular's asynchronous render
            # cycle; a subsequent Escape must close the already-open dialog.
            self.settle()
            return
        self.current=name
        if focus:
            self.page.locator(focus).first.scroll_into_view_if_needed()
        self.settle()
        stem=f"{self.language}-{self.config}-{name}"
        metrics=self.page.evaluate(METRICS)
        screenshot=stem+".png"
        # Full-page captures must start at the top. Otherwise Chromium places
        # sticky sidebars at the previous scroll offset in the stitched image.
        offset=self.page.evaluate("({x:scrollX,y:scrollY})")
        if not metrics["dialogs"]:
            self.page.evaluate("window.scrollTo({top:0,left:0,behavior:'instant'})")
            self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        self.page.screenshot(path=str(self.out/screenshot),full_page=not bool(metrics["dialogs"]),animations="disabled")
        if not metrics["dialogs"]:
            self.page.evaluate("p=>window.scrollTo({top:p.y,left:p.x,behavior:'instant'})",offset)
            self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        viewport=None
        if metrics["document"]["height"]>metrics["viewport"]["height"]*1.15 and not metrics["dialogs"]:
            viewport=stem+"-viewport.png"
            self.page.screenshot(path=str(self.out/viewport),animations="disabled")
        self.records=[r for r in self.records if (r["state"],r["context"],r["language"])!=(name,self.config,self.language)]
        self.records.append({"state":name,"context":self.config,"language":self.language,"url":self.page.url,"screenshot":screenshot,"viewportScreenshot":viewport,"notes":note,"mocks":list(self.mocks),"metrics":metrics,"pageErrors":list(self.errors),"result":"captured"})
        self.errors.clear()
        regressions=[check["name"] for check in metrics["checks"] if not check["passed"]]
        print(f'CAPTURE {stem}: overflow={metrics["horizontalOverflow"]}px, regressions={len(regressions)}'+(" · "+"; ".join(dict.fromkeys(regressions)) if regressions else ""),flush=True)
        self.report()

    @contextmanager
    def mock(self,path,value,description,status=200,method=None):
        pattern=self.base+path
        def handler(route):
            if method and route.request.method!=method:
                route.fallback();return
            route.fulfill(status=status,content_type="application/json",body=json.dumps(value))
        self.context.route(pattern,handler)
        self.mocks.append(description)
        try:
            yield
        finally:
            self.context.unroute(pattern,handler)
            self.mocks.pop()

    def attempt(self,name,callback):
        try:
            callback()
            self.records=[r for r in self.records if not (r["result"]=="failed" and (r["state"],r["context"],r["language"])==(name,self.config,self.language))]
        except Exception as error:
            screenshot=f"{self.language}-{self.config}-{name}-FAILED.png"
            try:self.page.screenshot(path=str(self.out/screenshot),full_page=True)
            except Exception:screenshot=None
            self.records.append({"state":name,"context":self.config,"language":self.language,"url":self.page.url,"screenshot":screenshot,"result":"failed","error":str(error)[:1600]})
            print(f"FAILED {self.language}-{self.config}-{name}: {str(error)[:220]}",flush=True)
            self.report()
            try:self.page.keyboard.press("Escape")
            except Exception:pass

    def select_id(self,locator,identifier):
        for option in locator.locator("option").all():
            value=option.get_attribute("value") or ""
            if value==str(identifier) or value.endswith(": "+str(identifier)):
                locator.select_option(value=value)
                return
        raise RuntimeError(f"Select has no option for fixture ID {identifier}")

    def open_details(self):
        self.goto("/spools")
        self.page.locator(".view-switch button").nth(0).click()
        self.page.locator(".spool-card").first.get_by_role("button",name=self.word("Details"),exact=True).click()
        expect(self.page.locator("dialog[open]")).to_be_visible()

    def inventory_states(self):
        self.goto("/spools")
        self.page.locator(".view-switch button").nth(0).click()
        self.capture("spools-cards")
        self.page.locator(".spool-scanner summary").click()
        self.capture("spools-scanner")
        self.page.locator(".spool-scanner summary").click()
        if self.page.locator(".mobile-filter-toggle").is_visible():
            self.page.locator(".mobile-filter-toggle").click()
        self.capture("spools-filters")
        if self.page.locator(".mobile-filter-toggle").is_visible():
            self.page.locator(".mobile-filter-toggle").click()
        self.page.locator(".spool-card .drag-handle").nth(0).click()
        self.page.locator(".spool-card .drag-handle").nth(1).click()
        self.capture("spools-label-tray", ".label-tray")
        self.page.locator(".view-switch button").nth(1).click()
        self.capture("spools-table")
        self.page.locator(".view-switch button").nth(2).click()
        self.page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
        self.capture("locations")
        if self.page.locator(".storage-label-selector").count():
            selection=self.page.locator(".storage-label-selector").first
            if selection.get_attribute("aria-pressed")!="true":selection.click()
            self.capture("locations-label-selected", ".storage-label-selector")
        destination=self.page.locator(".storage-destination select").first
        current=destination.input_value()
        values=destination.locator("option").evaluate_all("els => els.map(el=>el.value)")
        destination.select_option(next(value for value in values if value!=current))
        self.capture("locations-confirm", ".storage-confirm")
        self.goto("/spools?q=visual-no-matches-available")
        self.capture("spools-empty-filter")
        if self.config.startswith("mobile"):
            self.goto("/spools")
            self.page.locator(".mobile-inventory-actions summary").click()
            self.capture("mobile-inventory-actions")
            self.page.locator(".mobile-inventory-actions summary").click()
            self.page.locator(".mobile-navigation button").click()
            self.capture("mobile-navigation-drawer")
            self.page.keyboard.press("Escape")

    def dialog_states(self):
        self.goto("/filaments")
        self.button("+ Add filament").click()
        self.capture("product-add")
        self.page.keyboard.press("Escape")
        self.page.locator(".filament-card .icon-btn").last.click()
        self.capture("product-edit")
        self.page.keyboard.press("Escape")
        self.page.locator(".filament-card .btn.primary").first.click()
        self.capture("spool-add")
        self.page.keyboard.press("Escape")
        self.open_details()
        self.capture("spool-details")
        self.page.locator("dialog[open]").evaluate("el=>el.scrollTop=el.scrollHeight")
        self.page.locator("dialog[open] .modal-body").evaluate("el=>el.scrollTop=el.scrollHeight")
        self.capture("spool-details-history")
        for action,state in (("Record use","spool-consume"),("Adjust stock","spool-adjust"),("Weigh","spool-weigh"),("Record drying","spool-drying")):
            self.open_details()
            self.button(action,self.page.locator("dialog[open]")).click()
            self.capture(state)
        self.page.keyboard.press("Escape")
        self.goto("/spools")
        if self.page.locator(".mobile-inventory-actions summary").is_visible():
            self.page.locator(".mobile-inventory-actions summary").click()
        self.button("Import CSV").filter(visible=True).click()
        self.capture("csv-import")
        csv=self.page.request.get(self.base+"/api/export/inventory.csv").body()
        self.page.locator("dialog input[type=file]").set_input_files({"name":"synthetic-inventory.csv","mimeType":"text/csv","buffer":csv})
        expect(self.page.locator("#csv-preview")).to_be_visible()
        self.capture("csv-preview")
        self.button("Continue to confirmation").click()
        self.capture("csv-confirmation")
        self.page.keyboard.press("Escape")

    def batch_and_import_states(self):
        self.goto("/spools/batch")
        self.select_id(self.page.locator('select[name="product"]'),self.products[0]["id"])
        self.page.locator('input[name="count"]').fill("3")
        self.page.locator('input[name="location"]').fill("Werkstatt / Regal für neue Filamentlieferungen")
        self.button("Preview batch").click()
        self.capture("batch-preview", ".confirm-box")
        self.goto("/import/spoolman")
        payload=[{"id":7001,"remaining_weight":550,"initial_weight":1000,"location":"Visual imported shelf","filament":{"id":7001,"name":"Synthetic import sample","material":"PLA","color_hex":"82a392","diameter":1.75,"weight":1000,"vendor":{"id":7001,"name":"Visual import vendor"}}}]
        self.page.locator("input[type=file]").set_input_files({"name":"synthetic-spoolman.json","mimeType":"application/json","buffer":json.dumps(payload).encode()})
        self.button("Validate and preview").click()
        expect(self.page.locator(".detail-summary")).to_be_visible()
        self.capture("spoolman-preview")

    def catalog_states(self):
        data={
            "brands":{"version":"synthetic-visual-fixture","brands":[{"slug":"visual","name":"Visual catalog manufacturer"}]},
            "brands/visual":{"name":"Visual catalog manufacturer","materials":[{"slug":"pla","material":"PLA","filament_count":1}]},
            "brands/visual/materials/pla":{"material":"PLA","filaments":[{"slug":"matte","name":"Matte prototype filament for detailed catalog review","variant_count":1}]},
            "brands/visual/materials/pla/filaments/matte":{"name":"Matte prototype filament for detailed catalog review","density":1.24,"min_print_temperature":210,"max_print_temperature":230,"min_bed_temperature":45,"max_bed_temperature":60,"variants":[{"slug":"sage","name":"Sage green with a matte finish","color_hex":"#82a392"}]},
            "brands/visual/materials/pla/filaments/matte/variants/sage":{"name":"Sage green with a matte finish","color_hex":"#82a392","sizes":[{"diameter":1.75,"filament_weight":1000,"empty_spool_weight":180,"article_number":"VISUAL-PLA-SAGE-1000"}]},
        }
        def handler(route):
            key=urlsplit(route.request.url).path.removeprefix("/api/catalog/")
            route.fulfill(status=200,content_type="application/json",body=json.dumps(data[key]))
        pattern=self.base+"/api/catalog/**"
        self.context.route(pattern,handler);self.mocks.append("Synthetic offline catalog API responses")
        try:
            self.goto("/catalog")
            for name,value in (("brand","visual"),("material","pla"),("filament","matte"),("variant","sage")):
                self.page.locator(f'select[name="{name}"]').select_option(value)
            expect(self.page.locator(".detail-summary")).to_be_visible()
            self.capture("catalog-selected")
            self.button("Review and add as local product").click()
            self.capture("catalog-product-review")
            self.page.keyboard.press("Escape")
        finally:self.context.unroute(pattern,handler);self.mocks.pop()

    def job_states(self):
        self.goto("/jobs")
        self.button("Add another material/tool").click()
        self.capture("jobs-multiple-materials")
        self.page.locator('input[type="file"]').first.set_input_files({"name":"synthetic-prototype.gcode","mimeType":"text/plain","buffer":b"; generated by PrusaSlicer\n; filament used [g] = 37\nG1 X0\n"})
        self.button("Inspect file").click()
        expect(self.button("Apply estimates to mapping")).to_be_visible()
        self.capture("jobs-file-inspection")
        if not self.jobs:return
        jobs=[dict(job) for job in self.jobs]
        jobs[0].update(status="needs_review",accounting_status="needs_review",note="Synthetic failed-print review state; no physical printer contacted.")
        with self.mock("/api/jobs",jobs,"Synthetic needs-review job presentation over real local job metadata"):
            self.goto("/jobs?job="+str(jobs[0]["id"]))
            self.capture("jobs-focused")
            self.button("Check material").first.click()
            self.capture("jobs-material-readiness", ".workflow-row")
            self.button("Review consumption").first.click()
            expect(self.page.locator("sm-consumption dialog[open]")).to_be_visible()
            expect(self.page.locator('sm-consumption select[name="mode"]')).to_be_visible()
            self.capture("consumption-actual")
            self.page.locator('.reconciliation-material input[type="checkbox"]').first.check()
            self.capture("consumption-measured")
            self.page.locator('sm-consumption select[name="mode"]').select_option("estimated")
            self.capture("consumption-estimated")
            self.page.locator('sm-consumption select[name="mode"]').select_option("discard")
            self.capture("consumption-discard")
            self.page.keyboard.press("Escape")

    def printer_states(self):
        self.goto("/printers")
        self.page.locator('select[name="kind"]').select_option("octoprint")
        self.capture("printer-add-octoprint")
        self.page.locator('select[name="kind"]').select_option("bambu")
        self.capture("printer-add-bambu")
        self.button("Edit connection").last.click()
        self.page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
        self.capture("printer-edit")
        self.page.locator(".palette-spool").first.click()
        self.page.locator(".printer-drop-target").last.click()
        self.capture("printer-assignment", ".spool-palette")
        bambu=next((p for p in self.printers if p["kind"]=="bambu"),None)
        if bambu:
            observation={"state":"RUNNING","filename":"visual-prototype-enclosure-with-four-materials.3mf","progress_percent":46,"remaining_minutes":75,"nozzle_c":218.5,"bed_c":54.2,"ams":[{"unit":0,"tray":i,"material":material,"remaining_percent":remaining} for i,material,remaining in ((0,"PLA",74),(1,"PETG",31),(2,"PA6-CF",85),(3,"TPU",0))]}
            with self.mock(f'/api/printers/{bambu["id"]}/probe',observation,"Synthetic Bambu LAN/AMS response; intercepted before any backend or printer I/O"):
                row=self.page.locator("article.workflow-row").filter(has_text=bambu["name"])
                self.button("Test connection",row).click()
                self.capture("printer-bambu-status", ".printer-detail")

    def other_states(self):
        self.goto("/filaments")
        self.page.locator("#product-search").fill("visual-no-matches-available")
        self.capture("filaments-empty-filter")
        self.goto("/history?spool=9999999")
        self.capture("history-empty-filter")
        self.goto("/restock")
        self.page.locator('input[type="checkbox"]').first.check()
        self.capture("restock-below-target")
        self.goto("/diagnostics")
        self.page.locator(".service-details summary").click()
        self.capture("operations-service-details", ".service-details")
        self.goto("/users")
        self.button("Reset password").last.click()
        self.capture("user-password-reset", ".inline-reset")
        self.goto("/integrations")
        self.capture("integrations-scales", ".workflow-panel")
        self.capture("integrations-tokens", 'input[name="tokenLabel"]')
        self.capture("integrations-capabilities", ".capabilities")
        with self.mock("/api/admin/automation-tokens",{"id":999,"token":"spm_synthetic_visual_preview_not_a_valid_credential_0123456789","label":"Synthetic preview","scope":"inventory_read"},"Synthetic one-time token response, not a valid credential",method="POST"):
            self.page.locator('input[name="tokenLabel"]').fill("Synthetic visual preview")
            self.button("Create scoped token").click()
            self.capture("integrations-issued-token",'input[readonly]')
        self.goto("/account")
        self.page.locator('input[name="old"]').fill("synthetic-password")
        self.page.locator('input[name="new"]').fill("synthetic-new-password-2026")
        self.page.locator('input[name="confirm"]').fill("different-new-password-2026")
        self.button("Update password").click()
        self.capture("account-validation")

    def auth_states(self):
        self.context.clear_cookies()
        with self.mock("/api/auth/status",{"needs_setup":False},"Login presentation, signed out browser"):
            self.goto("/login")
            self.capture("login")
            with self.mock("/api/auth/login",{"detail":"Invalid credentials."},"Synthetic invalid-credentials response without account login attempts",401):
                self.page.locator('input[name="username"]').fill("visual-invalid-user")
                self.page.locator('input[name="password"]').fill("synthetic-invalid-password")
                self.page.locator('sm-login button[type="submit"]').click()
                expect(self.page.locator(".form-error")).to_be_visible()
                self.capture("login-error")
        with self.mock("/api/auth/status",{"needs_setup":True},"Synthetic first-administrator setup state; no account creation submitted"):
            self.goto("/login")
            expect(self.page.locator('input[name="token"]')).to_be_visible()
            self.capture("setup")

    def label_states(self):
        for size in ("60x40","50x30"):
            self.page.goto(self.base+f'/labels/{self.spools[0]["uid"]}?size={size}&lang={self.language}',wait_until="networkidle")
            self.capture("label-"+size,note="Print labels intentionally retain their paper colors in both application themes.")
        self.page.goto(self.base+"/labels?uids="+",".join(s["uid"] for s in self.spools[:2])+"&lang="+self.language,wait_until="networkidle")
        self.capture("labels-batch",note="Print sheet with two distinct physical spool identities.")

    def operation_states(self):
        if self.jobs and self.printers:
            jobs=[dict(job) for job in self.jobs]
            jobs[0]["start_command_state"]="unknown"
            with self.mock("/api/jobs",jobs,"Synthetic uncertain start-operation state"):
                self.goto("/jobs")
                self.button("Review start operation").first.click()
                self.capture("jobs-start-review", ".workflow-row")
            printer=self.printers[0]
            operations=[{"operation_id":"synthetic-visual-upload","printer_id":printer["id"],"job_id":jobs[0]["id"],"kind":"upload","state":"unknown","created_at":"2026-10-10T10:00:00Z","updated_at":"2026-10-10T10:05:00Z"}]
            with self.mock(f'/api/printers/{printer["id"]}/operations',operations,"Synthetic uncertain-upload operation, no file transfer"):
                self.goto("/printers")
                self.button("Review uncertain upload").click()
                self.capture("printer-upload-review", "section.confirm-box")
        with self.mock("/api/slicing/profiles",{"enabled":True,"profiles":["synthetic-local-printer-0.20mm-profile"]},"Synthetic enabled slicer-profile presentation, no slicer executed"):
            self.goto("/jobs")
            self.capture("jobs-slicing-enabled", ".workflow-panel:last-of-type")
        if self.spools:
            spool=self.spools[0]
            measurement={"id":999,"source":"VISUAL","event_id":"synthetic-scale-receipt","spool_id":spool["id"],"spool_uid":spool["uid"],"gross_g":900,"tare_g":180,"status":"pending","received_at":"2026-10-10T10:00:00Z","measured_at":"2026-10-10T09:59:59Z","net_g":720,"captured_stock_revision":spool.get("stock_revision",0),"captured_tare_g":180,"remaining_g":spool["remaining_g"],"brand":spool["brand"],"product_name":spool["product_name"],"stale":False,"blocking_job_ids":[]}
            outdated={**measurement,"id":1000,"event_id":"synthetic-stale-scale-receipt","stale":True,"stale_reason":"Stock or tare changed after this receipt; take a new measurement.","blocking_job_ids":[self.jobs[0]["id"]] if self.jobs else []}
            tokens=[{"id":901+index,"label":label,"scope":"inventory_read" if index==0 else "events_read","created_at":"2026-10-09T10:00:00Z","revoked_at":None if index==0 else "2026-10-10T10:00:00Z"} for index,label in enumerate(("Visual audit inventory reader with a descriptive automation label","Visual audit stock movement history reader"))]
            receipts=[{"source":"VISUAL","event_id":"synthetic-visual-completion-receipt","job_id":self.jobs[0]["id"] if self.jobs else 1,"disposition":"needs_review","received_at":"2026-10-10T10:05:00Z"}]
            with self.mock("/api/scales/measurements",[measurement,outdated],"Synthetic current and stale/blocked physical scale receipts; not approved"),self.mock("/api/admin/automation-tokens",tokens,"Synthetic active/revoked token metadata; no valid secrets",method="GET"),self.mock("/api/cloud/events",receipts,"Synthetic cloud receipt metadata"):
                self.goto("/integrations")
                self.capture("integrations-pending-scale", ".workflow-row")
        matching=[s for s in self.spools if s["product_id"]==next((p["id"] for p in self.products if p["name"]=="Matte PLA"),-1)][:3]
        if len(matching)==3:
            self.goto("/spools/batch")
            self.select_id(self.page.locator('select[name="product"]'),matching[0]["product_id"])
            self.page.locator('input[name="count"]').fill("3")
            self.button("Preview batch").click()
            self.page.locator('.confirm-box input[type="checkbox"]').check()
            with self.mock("/api/spools/batch",{"items":matching,"label_url":"/labels"},"Synthetic batch result using three existing fixture rolls; no duplicate stock created",method="POST"):
                self.page.locator(".confirm-box button.btn.primary").click()
                expect(self.page.locator(".detail-movement").first).to_be_visible()
                self.capture("batch-result")

    def groups(self):
        return (
            ("inventory-states",self.inventory_states,"spools-cards,spools-scanner,spools-filters,spools-label-tray,spools-table,locations,locations-label-selected,locations-confirm,spools-empty-filter,mobile-inventory-actions,mobile-navigation-drawer"),
            ("dialog-states",self.dialog_states,"product-add,product-edit,spool-add,spool-details,spool-details-history,spool-consume,spool-adjust,spool-weigh,spool-drying,csv-import,csv-preview,csv-confirmation"),
            ("batch-import-states",self.batch_and_import_states,"batch-preview,spoolman-preview"),
            ("catalog-states",self.catalog_states,"catalog-selected,catalog-product-review"),
            ("job-states",self.job_states,"jobs-multiple-materials,jobs-file-inspection,jobs-focused,jobs-material-readiness,consumption-actual,consumption-measured,consumption-estimated,consumption-discard"),
            ("printer-states",self.printer_states,"printer-add-octoprint,printer-add-bambu,printer-edit,printer-assignment,printer-bambu-status"),
            ("other-states",self.other_states,"filaments-empty-filter,history-empty-filter,restock-below-target,operations-service-details,user-password-reset,integrations-scales,integrations-tokens,integrations-capabilities,integrations-issued-token,account-validation"),
            ("operation-states",self.operation_states,"jobs-start-review,printer-upload-review,jobs-slicing-enabled,integrations-pending-scale,batch-result"),
            ("label-states",self.label_states,"label-60x40,label-50x30,labels-batch"),
            ("auth-states",self.auth_states,"login,login-error,setup"),
        )

    def network_guard(self,route):
        parsed=urlsplit(route.request.url)
        if parsed.scheme in ("http","https") and parsed.netloc!=urlsplit(self.base).netloc:
            route.abort("blockedbyclient");return
        if route.request.method not in ("GET","HEAD","OPTIONS") and re.search(r"/api/(?:printers/.+/(?:probe|poll|control)|jobs/.+/(?:start|upload|cancel))$",parsed.path):
            route.abort("blockedbyclient");return
        route.fallback()

    def run_context(self,language,config):
        self.language,self.config=language,config
        device,theme=config.split("-")
        self.context=self.browser.new_context(storage_state=self.auth_state,locale="de-DE" if language=="de" else "en-US",viewport=VIEWPORTS[device],color_scheme=theme,device_scale_factor=1)
        self.context.add_init_script(f"localStorage.setItem('spoolmera.language',{json.dumps(language)});localStorage.setItem('spoolmera-theme',{json.dumps(theme)});")
        self.context.route("**/*",self.network_guard)
        self.page=self.context.new_page()
        self.page.set_default_timeout(8000)
        self.page.on("pageerror",lambda error:self.errors.append(str(error)))
        try:
            for name,path in ROUTES.items():
                if self.wanted(name):
                    self.attempt(name,lambda name=name,path=path:(self.goto(path),self.capture(name)))
            for name,callback,states in self.groups():
                if any(self.wanted(state) and (not state.startswith("mobile-") or config.startswith("mobile")) for state in states.split(",")):
                    self.attempt(name,callback)
        finally:self.context.close()

    def report(self):
        routes=sorted({urlsplit(item["url"]).path for item in self.records if item["result"]=="captured"})
        states=set(ROUTES)
        for _,_,names in self.groups():states.update(names.split(","))
        expected={(language,config,state) for language in self.args.languages.split(",") for config in self.args.contexts.split(",") for state in states if self.wanted(state) and (not state.startswith("mobile-") or config.startswith("mobile"))}
        expected.update(self.previous_expected)
        captured={(r["language"],r["context"],r["state"]) for r in self.records if r["result"]=="captured"}
        missing=sorted(expected-captured)
        summary={"captures":sum(r["result"]=="captured" for r in self.records),"expectedSelectedCaptures":len(expected),"missingStates":len(missing),"missingStateNames":["/".join(item) for item in missing],"failures":sum(r["result"]=="failed" for r in self.records),"regressionFailures":sum(any(not check["passed"] for check in r.get("metrics",{}).get("checks",[])) for r in self.records),"pageErrorCaptures":sum(bool(r.get("pageErrors")) for r in self.records),"horizontalOverflow":sum(r.get("metrics",{}).get("horizontalOverflow",0)>1 for r in self.records),"routes":routes,"expectedRoutes":sorted(set(ROUTES.values())|{"/login"})}
        report={"baseUrl":self.base,"fixturePolicy":"Disposable localhost API fixtures. Catalog/bootstrap/hardware presentation mocks labelled per capture. No physical printer I/O.","requestedMatrix":sorted(expected),"summary":summary,"captures":self.records}
        (self.out/"manifest.json").write_text(json.dumps(report,indent=2,ensure_ascii=False))
        items=[]
        for record in self.records:
            title=html.escape(f'{record["language"]} · {record["context"]} · {record["state"]}')
            findings=record.get("metrics",{})
            failures=[check["name"] for check in findings.get("checks",[]) if not check["passed"]]
            text=html.escape(record.get("error",f'Horizontal overflow {findings.get("horizontalOverflow",0)} px · regressions {len(failures)}'+(" · "+"; ".join(dict.fromkeys(failures)) if failures else "")))
            picture=f'<a href="{record["screenshot"]}"><img loading="lazy" src="{record.get("viewportScreenshot") or record["screenshot"]}" alt="{title}"></a>' if record.get("screenshot") else ""
            items.append(f'<article><h2>{title}</h2><p>{text}</p>{picture}<p>{html.escape("; ".join(record.get("mocks",[])))}</p></article>')
        (self.out/"index.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Spoolmera visual audit</title><style>body{font:15px system-ui;background:#171c24;color:#e8eef8;margin:24px}header{margin-bottom:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}article{border:1px solid #4b566a;padding:14px;border-radius:12px;min-width:0}h2{font-size:16px}img{width:100%;max-height:650px;object-fit:contain;object-position:top;background:#111}a{color:#a4dcd0}p{overflow-wrap:anywhere}</style><header><h1>Spoolmera visual audit</h1><p>'+html.escape(json.dumps(summary))+'</p><p>Click a preview for the complete screenshot. Geometry findings require visual review. Every browser mock is labelled.</p><a href="manifest.json">Machine-readable manifest</a></header><main>'+"".join(items)+"</main></html>")
        return summary


@contextmanager
def isolated_server(args):
    """Serve the real app with disposable fixtures and no outbound poll cycle."""
    project=Path(__file__).resolve().parents[1]
    if not (project/"app/ui/index.html").exists():
        raise RuntimeError("Build frontend into app/ui before running --serve.")
    with tempfile.TemporaryDirectory(prefix="spoolmera-visual-db-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        token=secrets.token_urlsafe(32)
        os.environ[args.bootstrap_env]=token
        env=dict(os.environ,SPOOLMERA_DB_PATH=str(Path(directory)/"fixture.sqlite3"),SPOOLMERA_BOOTSTRAP_TOKEN=token,SPOOLMERA_PUBLIC_BASE_URL=f"http://127.0.0.1:{port}",SPOOLMERA_CATALOG_ENABLED="0",SPOOLMERA_PRINTER_ALLOWED_IPS="192.168.250.2,192.168.250.3",SPOOLMERA_PRINTER_TOKEN_VISUAL="visual-fixture-access-code",SPOOLMERA_BAMBU_CERT_SHA256_VISUAL="1"*64)
        # The replacement lives only in this child interpreter. Production
        # modules, HTTP routes and the poller lifecycle remain unchanged.
        code=f"import app.jobs; app.jobs.poll_all=lambda db_path: None; from app.main import app; import uvicorn; uvicorn.run(app,host='127.0.0.1',port={port},log_level='warning')"
        args.base_url=f"http://127.0.0.1:{port}"
        args.seed=True
        output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
        with (output/"server.log").open("w") as log:
            server=subprocess.Popen([sys.executable,"-c",code],cwd=project,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if server.poll() is not None:raise RuntimeError("Visual server exited; see server.log.")
                    try:
                        with urllib.request.urlopen(args.base_url+"/api/health",timeout=1):break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError("Visual server startup timed out; see server.log.")
                yield
            finally:
                server.terminate()
                try:server.wait(timeout=8)
                except subprocess.TimeoutExpired:server.kill();server.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url",default="http://127.0.0.1:8767")
    parser.add_argument("--output",default="/tmp/spoolmera-visual-audit")
    parser.add_argument("--username",default="visual-admin")
    parser.add_argument("--password-env",default="SPOOLMERA_VISUAL_PASSWORD")
    parser.add_argument("--bootstrap-env",default="SPOOLMERA_BOOTSTRAP_TOKEN")
    parser.add_argument("--seed",action="store_true",help="Create synthetic fixtures in the disposable localhost database")
    parser.add_argument("--serve",action="store_true",help="Start and clean up an isolated real backend with synthetic fixtures and no printer polling I/O")
    parser.add_argument("--languages",default="de")
    parser.add_argument("--contexts",default="desktop-dark,desktop-light,mobile-dark,mobile-light")
    parser.add_argument("--states","--only",default="*",help="Comma-separated state-name glob patterns to capture")
    parser.add_argument("--append",action="store_true",help="Preserve captures from an earlier pass of the same build and replace rerun states")
    parser.add_argument("--strict",action="store_true",help="Fail on missing requested states, capture/page errors, document overflow or concrete layout regressions")
    args=parser.parse_args()
    host=urlsplit(args.base_url).hostname
    if host!="localhost":
        try:local=ipaddress.ip_address(host or "").is_loopback
        except ValueError:local=False
        if not local:parser.error("Visual fixture audit requires a disposable loopback server.")
    for config in args.contexts.split(","):
        if config not in {device+"-"+theme for device in VIEWPORTS for theme in ("dark","light")}:
            parser.error("Unknown context: "+config)
    if any(language not in {"de","en"} for language in args.languages.split(",")):parser.error("Supported languages: de,en")
    with isolated_server(args) if args.serve else nullcontext(), sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,executable_path=os.getenv("SPOOLMERA_TEST_BROWSER_EXECUTABLE") or None,args=["--no-sandbox","--disable-dev-shm-usage"])
        audit=Audit(args,browser)
        try:
            audit.authenticate_and_seed()
            for language in args.languages.split(","):
                for config in args.contexts.split(","):
                    audit.run_context(language,config)
            summary=audit.report()
        finally:browser.close()
    bad=summary["failures"]+summary["horizontalOverflow"]+summary["regressionFailures"]+summary["pageErrorCaptures"]+summary["missingStates"]
    print(f"Visual audit complete: {summary['captures']} captures; missingStates={summary['missingStates']}; {bad} capture/geometry/page errors. {audit.out/'index.html'}",flush=True)
    if args.strict and bad:raise SystemExit(1)


if __name__=="__main__":
    main()
