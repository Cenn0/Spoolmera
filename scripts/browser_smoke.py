"""Browser smoke test covering Angular inventory workflows on desktop and mobile."""
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8765"

def run() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
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
        expect(page.locator("fm-root")).to_contain_text("Not connected")

        mobile = page.context.new_page()
        mobile.set_viewport_size({"width": 390, "height": 844})
        mobile.goto(BASE + "/spools", wait_until="networkidle")
        expect(mobile.locator(".mobile-spool")).to_have_count(1)
        expect(mobile.locator(".side-nav")).to_be_visible()
        mobile.close()
        browser.close()

if __name__ == "__main__":
    run()
    print("Angular browser smoke passed: product, spool, use, QR, CSV, deep link, integrations, mobile.")
