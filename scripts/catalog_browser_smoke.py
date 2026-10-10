"""Read-only gallery refinements exercised against the actual Angular application."""
from playwright.sync_api import expect


def check_product_gallery(page):
    """Use the existing synthetic inventory; do not create or change any records."""
    before = page.request.get('http://127.0.0.1:8765/api/products').json()
    by_id = {product['id']: product for product in before}
    cards = page.locator('.filament-card')
    search = page.get_by_label('Search products', exact=True)
    order = page.get_by_label('Sort products', exact=True)
    summary = page.locator('#product-results')
    writes = []

    def record_write(request):
        if '/api/' in request.url and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            writes.append((request.method, request.url))

    page.on('request', record_write)
    try:
        # These terms are not adjacent or in display order in the card.
        search.fill('Ocean PETG')
        expect(cards).to_have_count(1)
        expect(summary).to_contain_text('1 filament product')
        expect(summary).to_contain_text('1 active roll')
        expect(summary).to_contain_text('310 g')
        page.get_by_label('Filter by material', exact=True).select_option('PETG')
        page.get_by_label('In stock only', exact=True).check()
        order.select_option('stock-high')
        page.locator('sm-language-picker select').select_option('de')
        expect(summary).to_contain_text('1 Filamentprodukt')
        expect(summary).to_contain_text('1 aktive Spule')
        expect(page.get_by_label('Filamente sortieren', exact=True)).to_have_value('stock-high')
        expect(page.locator('#product-search')).to_have_value('Ocean PETG')
        page.locator('sm-language-picker select').select_option('en')
        search.fill('No product matches this input')
        expect(cards).to_have_count(0)
        expect(summary).to_contain_text('0 filament products')
        expect(summary).to_contain_text('0 active rolls')
        page.locator('.product-empty').get_by_role('button', name='Clear filters', exact=True).click()
        expect(search).to_be_focused()
        expect(search).to_have_value('')
        expect(page.get_by_label('In stock only', exact=True)).not_to_be_checked()
        expect(page.get_by_label('Filter by material', exact=True)).to_have_value('')
        expect(order).to_have_value('stock-high')
        expect(cards).to_have_count(len(before))

        maximum = max(before, key=lambda item: item['total_remaining_g'])
        expect(cards.first).to_have_attribute('data-product-id', str(maximum['id']))
        ids = cards.evaluate_all('(items) => items.map(item => Number(item.dataset.productId))')
        amounts = [by_id[item]['total_remaining_g'] for item in ids]
        assert amounts == sorted(amounts, reverse=True), amounts
        minimum = min(before, key=lambda item: item['total_remaining_g'])
        order.select_option('stock-low')
        expect(cards.first).to_have_attribute('data-product-id', str(minimum['id']))
        ids = cards.evaluate_all('(items) => items.map(item => Number(item.dataset.productId))')
        amounts = [by_id[item]['total_remaining_g'] for item in ids]
        assert amounts == sorted(amounts), amounts
        page.reload(wait_until='networkidle')
        expect(order).to_have_value('stock-low')
        expect(cards).to_have_count(len(before))
        order.select_option('name')
        # Long translated controls must not make the page wider on a phone.
        page.locator('sm-language-picker select').select_option('de')
        original = page.viewport_size
        for width in (320, 390, 768, 1024, 1440):
            page.set_viewport_size({'width': width, 'height': 1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), f'Gallery overflow at {width}px'
        page.set_viewport_size(original)
        page.locator('sm-language-picker select').select_option('en')
        assert not writes, writes
        assert page.request.get('http://127.0.0.1:8765/api/products').json() == before
        print('Gallery checks passed: filtered totals, combined search, sort persistence, keyboard reset, EN/DE and five widths without data writes.')
    finally:
        page.remove_listener('request', record_write)
