"""Exercise primary inventory workflows in a real Chromium browser.

Start the app at http://127.0.0.1:8765 before running this script.
This is deliberately a separate CI job to keep normal unit tests lightweight.
"""
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8765"


def run() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        page.goto(BASE + "/", wait_until="networkidle")
        expect(page.locator("h1")).to_contain_text("Every spool")
        page.locator('[data-action="new-product"]').first.click()
        product = page.locator("#product-dialog")
        expect(product).to_be_visible()
        product.locator('[name="brand"]').fill("Example Filament")
        product.locator('[name="name"]').fill("Matte Basic")
        product.locator('[name="material"]').fill("PLA")
        product.locator('[name="color_name"]').fill("Graphite")
        product.locator('button[type="submit"]').click()

        spool = page.locator("#spool-dialog")
        expect(spool).to_be_visible()
        spool.locator('[name="location"]').fill("Shelf A")
        spool.locator('button[type="submit"]').click()
        expect(spool).not_to_be_visible()

        page.locator('.side-nav [data-view="spools"]').click()
        expect(page.locator("#spool-table-body tr")).to_have_count(1)
        expect(page.locator("#spool-table-body")).to_contain_text("1 kg")

        # Manual usage stays consistent with the transaction ledger.
        page.locator('#spool-table-body [data-action="consume"]').click()
        movement = page.locator("#movement-dialog")
        expect(movement).to_be_visible()
        movement.locator('[name="grams"]').fill("125")
        movement.locator('[name="note"]').fill("Printed a mounting bracket")
        movement.locator('button[type="submit"]').click()
        expect(movement).not_to_be_visible()
        expect(page.locator("#spool-table-body")).to_contain_text("875 g")

        # Printed QR label is served by the application and includes a real QR image.
        with page.expect_popup() as popup_info:
            page.locator('#spool-table-body [data-action="label"]').click()
        label = popup_info.value
        label.wait_for_load_state("networkidle")
        expect(label.locator(".label-product")).to_contain_text("Matte Basic")
        expect(label.locator(".label-weight")).to_contain_text("875 g")
        expect(label.locator("img")).to_have_js_property("complete", True)
        assert label.locator("img").evaluate("(image) => image.naturalWidth > 0")
        label.close()

        # Exported CSV can be previewed and re-imported without a duplicate.
        with page.expect_download() as download_info:
            page.locator('a[href="/api/export/inventory.csv"]').click()
        download = download_info.value
        downloaded_csv = Path(download.path()).read_bytes()
        assert downloaded_csv.startswith(b"\xef\xbb\xbf")
        page.locator('[data-action="import-csv"]').click()
        import_dialog = page.locator("#csv-dialog")
        expect(import_dialog).to_be_visible()
        import_dialog.locator('input[type="file"]').set_input_files({
            "name": "inventory.csv", "mimeType": "text/csv", "buffer": downloaded_csv
        })
        expect(page.locator("#csv-preview")).to_contain_text("1 known spools")
        expect(page.locator("#csv-import-submit")).to_be_enabled()
        page.once("dialog", lambda alert: alert.accept())
        page.locator("#csv-import-submit").click()
        expect(import_dialog).not_to_be_visible()
        expect(page.locator("#spool-table-body tr")).to_have_count(1)
        expect(page.locator("#spool-table-body")).to_contain_text("875 g")

        # Scanning the stable spool deep link opens the correct details dialog.
        response = page.request.get(BASE + "/api/spools")
        assert response.ok
        uid = response.json()[0]["uid"]
        page.goto(BASE + "/?spool=" + uid, wait_until="networkidle")
        expect(page.locator("#edit-spool-dialog")).to_be_visible()
        expect(page.locator("#edit-spool-subtitle")).to_contain_text("Matte Basic")
        page.locator("#edit-spool-dialog [data-close-dialog]").first.click()
        page.locator('.side-nav [data-view="integrations"]').click()
        expect(page.locator("#view-integrations")).to_contain_text("Read-only")
        expect(page.locator("#view-integrations")).to_contain_text("Not connected")
        browser.close()


if __name__ == "__main__":
    run()
    print("Browser smoke test passed: create, consume, QR label, export/import, scan, integrations.")
