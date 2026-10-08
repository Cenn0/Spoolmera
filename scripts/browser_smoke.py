"""Browser smoke test covering Angular inventory workflows on desktop and mobile."""
from pathlib import Path
import os
import re
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8765"

def run() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
            executable_path=os.getenv("FILAMENT_TEST_BROWSER_EXECUTABLE") or None)
        page = browser.new_page(accept_downloads=True)
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

        uid = page.request.get(BASE + "/api/spools").json()[0]["uid"]
        page.goto(BASE + "/s/" + uid, wait_until="networkidle")
        expect(dialog).to_be_visible()
        expect(page.locator("#modal-title")).to_contain_text("Spool details")
        expect(dialog).to_contain_text("Matte Basic")
        dialog.get_by_role("button", name="Close dialog").click()
        page.locator('.side-nav a[href="/integrations"]').click()
        expect(page.locator("fm-root")).to_contain_text("Read-only available")
        expect(page.locator("fm-root")).to_contain_text("Signed cloud bridge")
        expect(page.locator("fm-root")).to_contain_text("External relay required")

        # Admin can provision users and register a restricted controller without
        # opening a real connection; a print job maps to an existing spool.
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

        page.locator('.side-nav a[href="/jobs"]').click()
        page.locator('input[name="fileName"]').fill("fixture.gcode")
        page.locator('input[name="estimatedG"]').fill("25")
        page.get_by_role("button", name="Register print job").click()
        expect(page.locator(".workflow-list")).to_contain_text("fixture.gcode")

        # Multi-tool mapping is edited through Angular, not only through REST.
        page.locator('input[name="fileName"]').fill("two-tools.gcode")
        page.locator('input[name="estimatedG"]').fill("20")
        page.get_by_role("button", name="Add another material/tool").click()
        expect(page.get_by_role('spinbutton', name='Estimated g')).to_be_visible()
        page.get_by_role('spinbutton', name='Estimated g').fill('5')
        # Additional tool assignments deliberately start unselected; an operator
        # must choose the physical spool before submitting a print job.
        page.locator('select[name="materialSpool0"]').select_option(label=re.compile("Example Filament"))
        page.get_by_role("button", name="Register print job").click()
        expect(page.locator(".workflow-list")).to_contain_text("two-tools.gcode")
        mapped = next(job for job in page.request.get(BASE + "/api/jobs").json()
                      if job["file_name"] == "two-tools.gcode")
        assert sorted((item["tool"], item["estimated_g"]) for item in mapped["materials"]) == [
            (0, 20), (1, 5),
        ]

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
        expect(page.locator('.side-nav a[href="/users"]')).to_have_count(0)
        expect(page.locator(".add-spool")).to_have_count(0)
        page.get_by_role("button", name="Sign out").click()
        page.locator('fm-login input[name="username"]').fill("browser-admin")
        page.locator('fm-login input[name="password"]').fill("  browser-new-password-2026  ")
        page.get_by_role("button", name="Sign in").click()
        expect(page.locator(".add-spool")).to_be_visible()

        mobile_context = browser.new_context(viewport={"width": 390, "height": 844},
                                             storage_state=page.context.storage_state())
        mobile = mobile_context.new_page()
        mobile.goto(BASE + "/spools", wait_until="networkidle")
        expect(mobile.locator(".mobile-spool")).to_have_count(1)
        expect(mobile.locator(".side-nav")).to_be_visible()
        mobile_context.close()

        # Revocation in another session must return the UI to login on the next API call.
        csrf = page.request.get(BASE + "/api/auth/me").json()["csrf_token"]
        assert page.request.post(BASE + "/api/auth/logout", headers={"X-CSRF-Token": csrf}).status == 200
        page.locator('.side-nav a[href="/jobs"]').click()
        expect(page.locator("h1")).to_contain_text("Welcome back")
        assert not errors, errors
        browser.close()

if __name__ == "__main__":
    run()
    print("Angular browser smoke passed: inventory, QR, CSV, roles, password, session revocation, mobile.")

