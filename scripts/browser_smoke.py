"""Browser smoke test covering Angular inventory workflows on desktop and mobile."""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8765"


@contextmanager
def browser_session(playwright):
    browser = playwright.chromium.launch(headless=True,
        executable_path=os.getenv("FILAMENT_TEST_BROWSER_EXECUTABLE") or None)
    context = browser.new_context(accept_downloads=True, locale="en-US")
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    try:
        yield browser, page
    except Exception:
        folder = Path(os.getenv("FILAMENT_BROWSER_ARTIFACT_DIR") or tempfile.mkdtemp(prefix="filament-browser-"))
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / "failure.png"), full_page=True)
        context.tracing.stop(path=str(folder / "trace.zip"))
        raise
    finally:
        browser.close()


def select_id(select, identifier: int) -> None:
    """Select a rendered numeric ID, including Angular's serialized ngValue."""
    for option in select.locator("option").all():
        value = option.get_attribute("value") or ""
        if value == str(identifier) or value.endswith(": " + str(identifier)):
            select.select_option(value=value)
            return
    raise AssertionError(f"Rendered select has no option for ID {identifier}.")


def report_failed_fixture(page, job_id: int) -> None:
    """A signed synthetic relay exercises the normal review boundary, not hardware."""
    secret = os.environ["FILAMENT_CLOUD_HMAC_BROWSER"]
    raw = json.dumps({"event_id": "browser-partial-job-" + str(job_id),
                      "job_id": job_id, "status": "failed"}, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    result = page.request.post(BASE + "/api/cloud/hooks/BROWSER", data=raw, headers={
        "Content-Type": "application/json", "X-Filament-Timestamp": stamp,
        "X-Filament-Signature": signature})
    assert result.status == 200 and result.json()["disposition"] == "needs_review"


def german_workflows(browser, errors: list[str]) -> None:
    """Exercise preference detection, live forms, German copy and label pages."""
    context = browser.new_context(locale="de-DE", viewport={"width": 1280, "height": 800})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    folder = Path(os.getenv("FILAMENT_BROWSER_ARTIFACT_DIR") or tempfile.mkdtemp(prefix="filament-language-"))
    folder.mkdir(parents=True, exist_ok=True)
    try:
        page.goto(BASE + "/", wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "de")
        expect(page.locator("h1")).to_have_text("Willkommen zurück.")
        language = page.locator("fm-language-picker select")
        expect(language).to_have_value("de")
        page.locator('fm-login input[name="username"]').fill("browser-admin")
        page.locator('fm-login input[name="password"]').fill("deliberately-wrong-password")
        language.select_option("en")
        expect(page.locator("h1")).to_have_text("Welcome back.")
        expect(page.locator('fm-login input[name="username"]')).to_have_value("browser-admin")
        language.select_option("de")
        page.get_by_role("button", name="Anmelden", exact=True).click()
        expect(page.locator(".form-error")).to_have_text("Ungültige Zugangsdaten.")
        page.locator('fm-login input[name="password"]').fill("  browser-new-password-2026  ")
        page.get_by_role("button", name="Anmelden", exact=True).click()
        expect(page.get_by_role("button", name="Abmelden", exact=True)).to_be_visible()
        expect(page.locator("h1")).to_contain_text("Jede Spule")
        expect(page.locator(".metrics")).to_contain_text("2,84 kg")
        expect(page.locator('.side-nav a[href="/jobs"]')).to_contain_text("Druckaufträge")
        expect(page.locator('.side-nav a[href="/users"]')).to_contain_text("Benutzer")

        # Changing language must neither submit nor reset an unfinished job form.
        page.locator('.side-nav a[href="/jobs"]').click()
        page.locator('input[name="fileName"]').fill("draft-language-check.gcode")
        page.locator('input[name="note"]').fill("Unveränderte Notiz: Ä, ö und ß")
        before = page.request.get(BASE + "/api/jobs").json()
        language.select_option("en")
        expect(page.locator("h1")).to_contain_text("Tracked")
        expect(page.locator('input[name="fileName"]')).to_have_value("draft-language-check.gcode")
        expect(page.locator('input[name="note"]')).to_have_value("Unveränderte Notiz: Ä, ö und ß")
        language.select_option("de")
        expect(page.locator('input[name="fileName"]')).to_have_value("draft-language-check.gcode")
        assert page.request.get(BASE + "/api/jobs").json() == before
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "de")
        expect(language).to_have_value("de")

        # Follow each actual menu link, including the lower desktop destinations.
        for path in ("/filaments", "/catalog", "/restock", "/history", "/printers",
                     "/integrations", "/account", "/diagnostics", "/users", "/spools"):
            page.locator(f'.side-nav a[href="{path}"]').click()
            expect(page).to_have_url(BASE + path)
            expect(page.locator("html")).to_have_attribute("lang", "de")
            expect(page.locator("main h1")).to_be_visible()
        expect(page.locator("#spool-table-body tr")).to_have_count(3)
        expect(page.locator("#spool-table-body")).to_contain_text("Example Filament")
        expect(page.locator("#spool-table-body")).to_contain_text("Matte Basic")
        expect(page.locator("#spool-table-body")).to_contain_text("Graphite")
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), "German desktop layout overflows horizontally"

        with page.expect_popup() as popup_info:
            page.locator('#spool-table-body tr').first.locator('a[href^="/labels/"]').first.click()
        label = popup_info.value
        label.wait_for_load_state("networkidle")
        expect(label.locator("html")).to_have_attribute("lang", "de")
        expect(label.locator(".print-toolbar")).to_contain_text("Spulenetikett")
        expect(label.locator(".label-weight")).to_contain_text("Restmenge:")
        expect(label.locator(".label-product")).to_contain_text("Example Filament")
        expect(label.locator('a[href*="size=50x30"]')).to_have_attribute("href", re.compile(r"lang=de"))
        assert label.locator('img').get_attribute('src').endswith('/qr.svg')
        label.close()
        page.screenshot(path=str(folder / "de-desktop.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator(".mobile-spool")).to_have_count(3)
        expect(language).to_be_visible()
        expect(page.locator(".side-nav")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), "German mobile layout overflows horizontally"
        page.screenshot(path=str(folder / "de-mobile.png"), full_page=True)
        language.select_option("en")
        expect(page.locator("html")).to_have_attribute("lang", "en")
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible()
        print("German browser smoke passed: browser preference, saved EN/DE choice, login errors, draft preservation, every navigation destination, localized numbers, original user data, labels and mobile layout.")
    except Exception:
        page.screenshot(path=str(folder / "failure-de.png"), full_page=True)
        context.tracing.stop(path=str(folder / "trace-de.zip"))
        raise
    else:
        context.tracing.stop()
    finally:
        context.close()


def run() -> None:
    with sync_playwright() as playwright, browser_session(playwright) as (browser, page):
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/", wait_until="networkidle")
        expect(page.locator("h1")).to_contain_text("Create the first administrator")
        page.locator('fm-login input[name="username"]').fill("browser-admin")
        page.locator('fm-login input[name="password"]').fill("browser-test-password-strong-2026")
        page.locator('fm-login input[name="token"]').fill("test-only-bootstrap-token-long-enough")
        page.get_by_role("button", name="Create administrator").click()
        expect(page.locator("h1")).to_contain_text("Every spool")

        page.get_by_role("button", name="New filament").click()
        dialog = page.locator("dialog.modal")
        expect(dialog).to_be_visible()
        dialog.locator('[name="brand"]').fill("Example Filament")
        dialog.locator('[name="name"]').fill("Matte Basic")
        dialog.locator('[name="material"]').fill("PLA")
        dialog.locator('[name="color_name"]').fill("Graphite")
        dialog.locator('[name="targetStock"]').fill("3500")
        dialog.get_by_role("button", name="Add filament").click()
        expect(dialog).not_to_be_visible()

        page.locator(".add-spool").click()
        expect(dialog).to_be_visible()
        dialog.locator('[name="location"]').fill("Shelf A")
        dialog.get_by_role("button", name="Register spool").click()
        expect(dialog).not_to_be_visible()

        page.locator('.side-nav a[href="/spools"]').click()
        expect(page.locator("#spool-table-body tr")).to_have_count(1)
        expect(page.locator("#spool-table-body")).to_contain_text("1 kg")

        page.locator("#spool-table-body").get_by_role("button", name="Record use").click()
        expect(dialog).to_be_visible()
        dialog.locator('[name="grams"]').fill("125")
        dialog.locator('[name="note"]').fill("Printed a mounting bracket")
        dialog.get_by_role("button", name="Save movement").click()
        expect(dialog).not_to_be_visible()
        expect(page.locator("#spool-table-body")).to_contain_text("875 g")

        with page.expect_popup() as popup_info:
            page.locator("#spool-table-body").get_by_role("link", name="QR label").click()
        label = popup_info.value
        label.wait_for_load_state("networkidle")
        expect(label.locator(".label-product")).to_contain_text("Matte Basic")
        expect(label.locator(".label-weight")).to_contain_text("875 g")
        assert label.locator("img").evaluate("(image) => image.complete && image.naturalWidth > 0")
        label.close()

        with page.expect_download() as download_info:
            page.get_by_role("link", name="Export CSV").click()
        csv_bytes = Path(download_info.value.path()).read_bytes()
        assert csv_bytes.startswith(b"\xef\xbb\xbf")
        page.get_by_role("button", name="Import CSV").click()
        expect(dialog).to_be_visible()
        dialog.locator('input[type="file"]').set_input_files({
            "name": "inventory.csv", "mimeType": "text/csv", "buffer": csv_bytes
        })
        expect(dialog.locator("#csv-preview")).to_contain_text("1 known spools")
        dialog.get_by_role("button", name="Continue to confirmation").click()
        dialog.get_by_role("button", name="Confirm import").click()
        expect(dialog).not_to_be_visible()
        expect(page.locator("#spool-table-body tr")).to_have_count(1)

        original = page.request.get(BASE + "/api/spools").json()[0]
        sid, uid, product_id = original['id'], original['uid'], original['product_id']
        page.goto(BASE + "/s/" + uid, wait_until="networkidle")
        expect(dialog).to_be_visible()
        expect(page.locator("#modal-title")).to_contain_text("Spool details")
        expect(dialog).to_contain_text("Matte Basic")
        dialog.get_by_role("button", name="Archive spool…").click()
        dialog.get_by_role("button", name="Confirm archive").click()
        expect(dialog).not_to_be_visible()
        page.goto(BASE + "/spools", wait_until="networkidle")
        page.get_by_label("Inventory archive filter").select_option("archived")
        expect(page.locator("#spool-table-body")).to_contain_text("archived")
        page.locator("#spool-table-body").get_by_role("button", name="Details").click()
        expect(dialog).to_contain_text("Archived on")
        expect(dialog).to_contain_text("Printed a mounting bracket")
        dialog.get_by_role("button", name="Restore to active inventory").click()
        expect(dialog).not_to_be_visible()
        assert page.request.get(BASE + "/api/spools/by-uid/" + uid).json()["archived_at"] is None
        # Archived QR links keep resolving to the physical spool; restore keeps its UID.
        page.goto(BASE + "/s/" + uid, wait_until="networkidle")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Close dialog").click()

        page.goto(BASE + "/spools/batch", wait_until="networkidle")
        select_id(page.locator('select[name="product"]'), product_id)
        page.locator('input[name="count"]').fill("2")
        page.locator('input[name="location"]').fill("Shelf B")
        page.get_by_role("button", name="Preview batch").click()
        expect(page.get_by_role("heading", name="Confirm 2 separate spools")).to_be_visible()
        page.get_by_label("These values apply to every roll in this batch.").check()
        page.get_by_role("button", name="Register 2 spools", exact=True).click()
        expect(page.get_by_role("heading", name="2 physical spools")).to_be_visible()
        with page.expect_popup() as popup_info:
            page.get_by_role("link", name="Open batch label sheet").click()
        label = popup_info.value
        expect(label.locator("article.label")).to_have_count(2)
        label.close()
        spools = page.request.get(BASE + "/api/spools").json()
        assert len(spools) == len({item['uid'] for item in spools}) == 3
        assert sum(item['remaining_g'] for item in spools) == 2875

        page.locator('.side-nav a[href="/restock"]').click()
        expect(page.locator(".restock-row")).to_contain_text("625 g")
        page.locator('.side-nav a[href="/history"]').click()
        page.locator('input[name="spool"]').fill(str(sid))
        page.locator('select[name="kind"]').select_option("consume")
        page.get_by_role("button", name="Apply filters").click()
        expect(page.locator(".data-table tbody tr")).to_have_count(1)
        expect(page.locator(".data-table tbody")).to_contain_text("Printed a mounting bracket")
        page.locator('.side-nav a[href="/integrations"]').click()
        expect(page.locator("fm-root")).to_contain_text("Read-only available")
        expect(page.locator("fm-root")).to_contain_text("Signed cloud bridge")
        expect(page.locator("fm-root")).to_contain_text("External relay required")

        # Admin provisions users and a restricted fixture controller. Background
        # polling may attempt read-only status GETs; this smoke sends no printer commands.
        page.locator('.side-nav a[href="/users"]').click()
        # Wait for template-driven controls to register before dispatching input.
        expect(page.locator("form.workflow-form")).to_have_class(re.compile(r".*ng-invalid.*"))
        page.locator('input[name="username"]').fill("browser-viewer")
        page.locator('input[name="password"]').fill("browser-viewer-password-2026")
        page.get_by_role("button", name="Create user").click()
        expect(page.locator(".workflow-list")).to_contain_text("browser-viewer")

        page.locator('.side-nav a[href="/printers"]').click()
        page.locator('input[name="name"]').fill("Test Klipper")
        page.locator('input[name="base_url"]').fill("http://192.168.50.20:7125")
        page.get_by_role("button", name="Add printer").click()
        expect(page.locator(".workflow-list")).to_contain_text("Test Klipper")
        printer_id = page.request.get(BASE + "/api/printers").json()[0]["id"]
        select_id(page.locator('select[name="slotPrinter"]'), printer_id)
        page.locator('input[name="slotTool"]').fill("3")
        select_id(page.locator('select[name="slotSpool"]'), sid)
        page.get_by_role("button", name="Save slot assignment").click()
        expect(page.locator(".printer-detail")).to_contain_text("Tool 3")

        page.locator('.side-nav a[href="/jobs"]').click()
        page.locator('input[name="fileName"]').fill("single-t3.gcode")
        page.locator('input[name="firstTool"]').fill("3")
        page.locator('input[name="estimatedG"]').fill("200")
        page.get_by_role("button", name="Suggest rolls from recorded printer slots").click()
        page.once("dialog", lambda prompt: prompt.accept())
        page.get_by_role("button", name="Use these suggested rolls").click()
        page.get_by_role("button", name="Register print job").click()
        expect(page.locator(".workflow-list")).to_contain_text("single-t3.gcode")
        single = next(job for job in page.request.get(BASE + "/api/jobs").json()
                      if job["file_name"] == "single-t3.gcode")
        assert [(item["tool"], item["estimated_g"]) for item in single["materials"]] == [(3, 200)]
        assert single['materials'][0]['spool_id'] == sid

        # Multi-tool mapping is edited through Angular, not only through REST.
        page.locator('input[name="fileName"]').fill("two-tools.gcode")
        page.locator('input[name="firstTool"]').fill("3")
        select_id(page.locator('select[name="spool"]'), sid)
        page.locator('input[name="estimatedG"]').fill("20")
        page.get_by_role("button", name="Add another material/tool").click()
        expect(page.get_by_role('spinbutton', name='Estimated g')).to_be_visible()
        page.get_by_role('spinbutton', name='Estimated g').fill('5')
        # Additional tool assignments deliberately start unselected; an operator
        # must choose the physical spool before submitting a print job.
        select_id(page.locator('.material-mapping-list select'), sid)
        page.get_by_role("button", name="Register print job").click()
        expect(page.locator(".workflow-list")).to_contain_text("two-tools.gcode")
        mapped = next(job for job in page.request.get(BASE + "/api/jobs").json()
                      if job["file_name"] == "two-tools.gcode")
        assert sorted((item["tool"], item["estimated_g"]) for item in mapped["materials"]) == [
            (0, 5), (3, 20),
        ]

        report_failed_fixture(page, single['id'])
        page.get_by_role("button", name="Refresh jobs").click()
        job_row = page.locator("article.workflow-row").filter(has_text="single-t3.gcode")
        expect(job_row).to_contain_text("needs review")
        for actual, balance in [(37, 838), (40, 835)]:
            job_row.get_by_role("button", name="Review consumption").click()
            consumption = page.locator("fm-consumption dialog")
            expect(consumption.get_by_label("Total actual use (g)")).to_be_visible()
            consumption.get_by_label("Total actual use (g)").fill(str(actual))
            consumption.locator('textarea[name="reason"]').fill("Confirmed partial print including purge")
            consumption.locator('input[name="confirmed"]').check()
            consumption.get_by_role("button", name="Confirm consumption").click()
            expect(consumption).not_to_be_visible()
            assert page.request.get(BASE + "/api/spools/by-uid/" + uid).json()["remaining_g"] == balance
        current = page.request.get(BASE + f"/api/jobs/{single['id']}/consumption").json()
        assert current['materials'][0]['estimated_g'] == 200
        assert current['materials'][0]['accounted_g'] == 40
        movements = page.request.get(BASE + f"/api/movements/page?job_id={single['id']}").json()['items']
        assert sum(item['delta_g'] for item in movements) == -40
        assert any(item['corrects_movement_id'] is not None for item in movements)
        job_row.get_by_role("link", name="Movement history", exact=True).click()
        expect(page.locator(".data-table tbody")).to_contain_text("Corrects movement")
        page.locator('.side-nav a[href="/printers"]').click()
        page.get_by_role("button", name="Remove assignment").click()
        expect(page.locator(".printer-detail")).not_to_contain_text("Tool 3")

        # Passwords are exact secrets, including leading/trailing spaces.
        page.locator('.side-nav a[href="/account"]').click()
        expect(page.locator('form.workflow-form')).to_have_class(re.compile('.*ng-invalid.*'))
        page.locator('input[name="old"]').fill("browser-test-password-strong-2026")
        page.locator('input[name="new"]').fill("  browser-new-password-2026  ")
        page.locator('input[name="confirm"]').fill("  browser-new-password-2026  ")
        page.get_by_role("button", name="Update password").click()
        expect(page.locator(".notice")).to_contain_text("Password changed")

        # Viewer access is read-only, and the session is genuinely revoked on logout.
        page.get_by_role("button", name="Sign out").click()
        expect(page.locator("h1")).to_contain_text("Welcome back")
        page.locator('fm-login input[name="username"]').fill("browser-viewer")
        page.locator('fm-login input[name="password"]').fill("browser-viewer-password-2026")
        page.get_by_role("button", name="Sign in").click()
        # Absence of editor controls is already true on the login screen. Wait
        # for a confirmed session before those checks or a full-page navigation.
        expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible()
        viewer_session = page.request.get(BASE + "/api/auth/me")
        assert viewer_session.status == 200
        viewer_identity = viewer_session.json()
        assert (viewer_identity["username"], viewer_identity["role"]) == ("browser-viewer", "viewer")
        expect(page.locator('.side-nav a[href="/users"]')).to_have_count(0)
        expect(page.locator(".add-spool")).to_have_count(0)
        page.goto(BASE + "/spools/batch", wait_until="networkidle")
        expect(page).to_have_url(re.compile(r"/access-denied$"))
        page.goto(BASE + "/printers", wait_until="networkidle")
        expect(page.get_by_role("button", name="Save slot assignment")).to_have_count(0)
        page.get_by_role("button", name="Sign out").click()
        page.locator('fm-login input[name="username"]').fill("browser-admin")
        page.locator('fm-login input[name="password"]').fill("  browser-new-password-2026  ")
        page.get_by_role("button", name="Sign in").click()
        expect(page.locator(".add-spool")).to_be_visible()

        mobile_context = browser.new_context(viewport={"width": 390, "height": 844},
                                             storage_state=page.context.storage_state())
        mobile = mobile_context.new_page()
        mobile.goto(BASE + "/spools", wait_until="networkidle")
        expect(mobile.locator(".mobile-spool")).to_have_count(3)
        expect(mobile.locator(".side-nav")).to_be_visible()
        mobile_context.close()

        # Revocation in another session must return the UI to login on the next API call.
        csrf = page.request.get(BASE + "/api/auth/me").json()["csrf_token"]
        assert page.request.post(BASE + "/api/auth/logout", headers={"X-CSRF-Token": csrf}).status == 200
        page.locator('.side-nav a[href="/jobs"]').click()
        expect(page.locator("h1")).to_contain_text("Welcome back")
        german_workflows(browser, errors)
        assert not errors, errors

if __name__ == "__main__":
    run()
    print("Angular browser smoke passed: inventory, archive, batch labels, restock, history, T3/T0 slots, partial/corrected consumption, CSV, roles, password, revocation and mobile.")

