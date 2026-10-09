"""Read-only browser regressions for the continued UI review."""
import re
from playwright.sync_api import expect

BASE = 'http://127.0.0.1:8765'


def run_followup_workflows(page):
    """Use the existing synthetic inventory; never send stock or printer writes."""
    before = page.request.get(BASE + '/api/spools').json()
    page.goto(BASE + '/spools', wait_until='networkidle')
    cards = page.locator('.spool-card')
    expect(cards).to_have_count(8)
    page.get_by_label('Filter by material', exact=True).select_option('PETG')
    page.get_by_label('Filter by status', exact=True).select_option('opened')
    expect(cards).to_have_count(1)
    expect(page).to_have_url(re.compile(r'material=PETG'))
    expect(page).to_have_url(re.compile(r'status=opened'))
    page.reload(wait_until='networkidle')
    expect(page.get_by_label('Filter by material', exact=True)).to_have_value('PETG')
    expect(page.get_by_label('Filter by status', exact=True)).to_have_value('opened')
    expect(cards).to_have_count(1)
    page.get_by_role('button', name='Select loaded labels', exact=True).click()
    expect(page.locator('.label-tray-item')).to_have_count(1)
    page.get_by_role('button', name='Show all low-stock spools', exact=True).click()
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text('140 g')
    expect(page.get_by_label('Filter by material', exact=True)).to_have_value('')
    # The selected PETG roll is outside the low-stock filter and must be retained.
    expect(page.locator('.label-tray-item')).to_have_count(1)
    page.get_by_role('button', name='Select loaded labels', exact=True).click()
    expect(page.locator('.label-tray-item')).to_have_count(2)
    page.get_by_role('button', name='Deselect loaded labels', exact=True).click()
    expect(page.locator('.label-tray-item')).to_have_count(1)
    page.go_back(wait_until='networkidle')
    expect(page.get_by_label('Filter by material', exact=True)).to_have_value('PETG')
    expect(page.get_by_label('Filter by status', exact=True)).to_have_value('opened')
    page.go_forward(wait_until='networkidle')
    expect(cards.first).to_contain_text('140 g')
    page.get_by_role('button', name='Clear filters', exact=True).click()
    expect(cards).to_have_count(8)
    page.get_by_role('button', name='Select loaded labels', exact=True).click()
    expect(page.locator('.label-tray-item')).to_have_count(8)
    page.locator('.label-tray-item').nth(1).get_by_role('button', name='Move up', exact=True).click()
    expect(page.locator('.tray-feedback')).to_contain_text('position 1 of 8')
    # A delayed refresh keeps the real DOM node and its focusable controls mounted.
    held = []
    page.route('**/api/spools/page*', lambda route: held.append(route))
    try:
        page.evaluate("window.firstCardBeforeRefresh = document.querySelector('.spool-card')")
        page.get_by_role('button', name='Refresh spools', exact=True).click()
        expect(page.locator('.inventory-results')).to_have_attribute('aria-busy', 'true')
        expect(cards).to_have_count(8)
        assert page.evaluate("window.firstCardBeforeRefresh === document.querySelector('.spool-card')")
        for route in held:
            route.fulfill(response=route.fetch())
        expect(page.locator('.inventory-results')).to_have_attribute('aria-busy', 'false')
        assert page.evaluate("window.firstCardBeforeRefresh === document.querySelector('.spool-card')")
    finally:
        page.unroute('**/api/spools/page*')
    page.get_by_role('button', name='Clear selection', exact=True).click()
    expect(page.locator('.label-tray-item')).to_have_count(0)
    assert page.request.get(BASE + '/api/spools').json() == before

    page.goto(BASE + '/spools', wait_until='networkidle')
    print('Spool follow-up passed: URL history, low-stock filtering, bulk labels, reorder feedback and stable refresh without stock writes.')
