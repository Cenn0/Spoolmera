"""Real browser UX regressions. Fixtures are synthetic; no physical printer writes."""
import os
import json
import re
from pathlib import Path
from playwright.sync_api import expect
from catalog_browser_smoke import check_product_gallery
from ui_followup_smoke import run_followup_workflows

BASE = 'http://127.0.0.1:8765'


def file_drop(page, selector, name, contents):
    transfer = page.evaluate_handle('''({name,contents}) => {
      const data = new DataTransfer(); data.items.add(new File([contents],name)); return data;
    }''', {'name': name, 'contents': contents})
    page.locator(selector).dispatch_event('drop', {'dataTransfer': transfer})
    transfer.dispose()


def capture_preview(page, path, end_selector, *, full_page=True):
    """Capture the rendered view and reject an image using stale page bounds."""
    expect(page.locator(end_selector).last).to_be_visible()
    page.evaluate('''async () => {
      await document.fonts.ready;
      window.scrollTo({top:0,left:0,behavior:'instant'});
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }''')
    geometry = '''selector => {
      const end = [...document.querySelectorAll(selector)].at(-1).getBoundingClientRect();
      return {width:Math.max(innerWidth,document.documentElement.scrollWidth,document.body.scrollWidth),
        height:Math.max(innerHeight,document.documentElement.scrollHeight,document.body.scrollHeight),
        viewportWidth:innerWidth,viewportHeight:innerHeight,endBottom:end.bottom+scrollY};
    }'''
    before = page.evaluate(geometry, end_selector)
    png = page.screenshot(path=str(path), full_page=full_page, animations='disabled', scale='css')
    after = page.evaluate(geometry, end_selector)
    width, height = int.from_bytes(png[16:20], 'big'), int.from_bytes(png[20:24], 'big')
    if full_page:
        assert all(abs(before[key]-after[key]) <= 1 for key in ('width','height','endBottom')), (path.name,before,after)
        assert abs(width-after['width']) <= 1 and abs(height-after['height']) <= 1, (path.name,width,height,after)
    else:
        assert (width,height) == (after['viewportWidth'],after['viewportHeight']), (path.name,width,height,after)
    assert after['endBottom'] <= height+1, (path.name,'Preview clips its final element',height,after)
    print('Preview bounds:',json.dumps({'file':path.name,'pixels':[width,height],'fullPage':full_page,**after}))


def run_ui_workflows(browser, errors):
    folder = Path(os.environ.get('SPOOLMERA_BROWSER_ARTIFACT_DIR', '/tmp/spoolmera-ui-previews'))
    folder.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(locale='en-US', color_scheme='dark', viewport={'width': 1440, 'height': 1000})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(BASE, wait_until='networkidle')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        page.locator('input[name="username"]').fill('browser-admin')
        page.locator('input[name="password"]').fill('  browser-new-password-2026  ')
        theme = page.locator('sm-theme-picker select')
        theme.select_option('light')
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        expect(page.locator('input[name="password"]')).to_have_value('  browser-new-password-2026  ')
        theme.select_option('dark')
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.get_by_role('button', name='Sign out', exact=True)).to_be_visible()
        page.locator('.side-nav a[href="/spools"]').click()
        expect(page.locator('.spool-card')).to_have_count(3)
        # Native mouse drag and click fallback both select without stock mutations.
        before = page.request.get(BASE + '/api/spools').json()
        cards = page.locator('.spool-card')
        cards.nth(0).locator('.drag-handle').drag_to(page.locator('.label-tray'))
        expect(page.locator('.label-tray-item')).to_have_count(1)
        cards.nth(1).locator('.drag-handle').click()
        expect(page.locator('.label-tray-item')).to_have_count(2)
        ordered_before = page.locator('.print-selected').get_attribute('href')
        page.locator('.label-tray-item').last.get_by_role('button', name='Move up', exact=True).click()
        # Angular commits signal changes on its render cycle; assert the DOM result, not a same-tick read.
        expect(page.locator('.print-selected')).not_to_have_attribute('href', ordered_before)
        # Complete scrolling before pressing the mouse: drag_to can scroll its
        # target after mousedown, moving the source before a native drag starts.
        tray_items = page.locator('.label-tray-item')
        tray_source = tray_items.first.locator('.drag-handle')
        tray_target = tray_items.last
        tray_target.scroll_into_view_if_needed()
        tray_source.hover()
        viewport = page.viewport_size
        assert viewport
        start, end = tray_source.bounding_box(), tray_target.bounding_box()
        assert start and end
        for box in (start, end):
            assert 0 <= box['x'] and box['x'] + box['width'] <= viewport['width']
            assert 0 <= box['y'] and box['y'] + box['height'] <= viewport['height']
        sx, sy = start['x'] + start['width']/2, start['y'] + start['height']/2
        page.mouse.down()
        page.mouse.move(sx+12, sy-8, steps=5)
        expect(page.locator('.label-tray')).to_have_class(re.compile(r'\baccepting-drag\b'))
        # Read the current target after dragstart has rendered. Aim at its text
        # area, away from the row's disabled reorder buttons, and send dragover
        # twice using real pointer moves without another scroll action.
        end = tray_target.locator('.label-identity').bounding_box()
        assert end
        tx, ty = end['x'] + end['width']/2, end['y'] + end['height']/2
        assert 0 <= tx < viewport['width']-1 and 0 <= ty < viewport['height']
        page.mouse.move(tx, ty, steps=12)
        page.mouse.move(tx+1, ty)
        expect(tray_target).to_have_class(re.compile(r'\bdrop-after\b'))
        page.mouse.up()
        expect(page.locator('.print-selected')).to_have_attribute('href', ordered_before)
        page.get_by_label('Search spools', exact=True).fill('does-not-exist')
        expect(cards).to_have_count(0)
        expect(page.locator('.label-tray-item')).to_have_count(2)
        page.get_by_label('Search spools', exact=True).fill('')
        expect(cards).to_have_count(3)
        page.get_by_role('button', name='Table', exact=True).click()
        expect(page.locator('#spool-table-body tr')).to_have_count(3)
        page.get_by_role('button', name='Cards', exact=True).click()
        assert page.request.get(BASE + '/api/spools').json() == before

        # CSV drop validates only; an invalid replacement invalidates the preview.
        csv = page.request.get(BASE + '/api/export/inventory.csv').text()
        page.get_by_role('button', name='Import CSV', exact=True).click()
        file_drop(page, 'dialog sm-file-drop .file-drop', 'inventory.csv', csv)
        expect(page.locator('#csv-preview')).to_be_visible()
        expect(page.locator('dialog sm-file-drop')).to_contain_text('Maximum file size: 2 MiB')
        file_drop(page, 'dialog sm-file-drop .file-drop', 'wrong.exe', 'invalid')
        expect(page.locator('#csv-preview')).to_have_count(0)
        expect(page.locator('dialog .form-error').first).to_contain_text('file type')
        page.get_by_role('button', name='Close dialog', exact=True).click()
        assert page.request.get(BASE + '/api/spools').json() == before

        # Metadata drops do not create jobs or transfer files to a printer.
        page.locator('.side-nav a[href="/jobs"]').click()
        jobs = page.request.get(BASE + '/api/jobs').json()
        page.locator('input[name="note"]').fill('Keep this draft while switching themes')
        file_drop(page, 'sm-file-drop .file-drop', 'sample.gcode', '; generated by PrusaSlicer\n; filament used [g] = 37\nG1 X0\n')
        expect(page.locator('.selected-file')).to_have_text('sample.gcode')
        theme.select_option('light')
        expect(page.locator('input[name="note"]')).to_have_value('Keep this draft while switching themes')
        page.get_by_role('button', name='Inspect file', exact=True).click()
        expect(page.get_by_role('button', name='Apply estimates to mapping', exact=True)).to_be_visible()
        assert page.request.get(BASE + '/api/jobs').json() == jobs

        # Spool -> printer drop only prepares an editor form; Save is separate.
        page.locator('.side-nav a[href="/printers"]').click()
        slots = page.request.get(BASE + '/api/printers/1/slots').json()
        page.locator('input[name="slotTool"]').fill('4')
        # Use the documented native mouse sequence: dragover needs two moves in
        # some engines. Do not synthesize drop events or bypass application guards.
        # https://playwright.dev/python/docs/input#dragging-manually
        page.evaluate("""() => {
          window.printerDragEvents = [];
          for (const type of ['dragstart','dragenter','dragover','drop','dragend']) {
            document.addEventListener(type, e => {
              if (window.printerDragEvents.length < 80) window.printerDragEvents.push({
                type, target: e.target.tagName + '.' + e.target.className,
                canceled: e.defaultPrevented, effect: e.dataTransfer?.dropEffect,
                allowed: e.dataTransfer?.effectAllowed, types: [...(e.dataTransfer?.types ?? [])]
              });
            });
          }
        }""")
        source = page.locator('.palette-spool').first
        target = page.locator('.printer-drop-target').first
        source.hover()
        page.mouse.down()
        target.hover()
        target.hover()
        expect(target).to_have_class(re.compile(r'\bdrop-active\b'))
        page.mouse.up()
        expect(page.locator('select[name="slotSpool"]')).not_to_have_value('0: 0')
        assert page.request.get(BASE + '/api/printers/1/slots').json() == slots
        page.get_by_role('button', name='Save slot assignment', exact=True).click()
        expect(page.locator('.printer-detail')).to_contain_text('Tool 4')
        assert page.request.get(BASE + '/api/printers/1/slots').json() != slots

        # Create explicitly synthetic color fixtures only in this ephemeral browser DB.
        csrf = page.request.get(BASE + '/api/auth/me').json()['csrf_token']
        headers = {'X-CSRF-Token': csrf}
        samples = [
            ('PLA Matte', 'Sage', '#82a392', 740, 'PLA'),
            ('PETG', 'Ocean', '#3a7e9a', 310, 'PETG'),
            ('PLA Silk', 'Amber', '#d69a4b', 1000, 'PLA'),
            ('PLA Matte', 'Terracotta', '#ba7360', 140, 'PLA'),
            ('TPU Flexible', 'Graphite', '#464f5b', 880, 'TPU'),
        ]
        for name, color, color_hex, weight, material in samples:
            response = page.request.post(BASE + '/api/products', headers=headers, data={
                'brand': 'Workshop samples', 'name': name, 'material': material,
                'color_name': color, 'color_hex': color_hex, 'diameter_mm': 1.75})
            assert response.status == 201, response.text()
            pid = response.json()['id']
            response = page.request.post(BASE + '/api/spools', headers=headers, data={
                'product_id': pid, 'initial_g': 1000, 'remaining_g': weight,
                'opened': weight < 1000, 'location': 'Studio / Box A'})
            assert response.status == 201, response.text()

        page.locator('.side-nav a[href="/filaments"]').click()
        expect(page.locator('.filament-card')).to_have_count(6)
        check_product_gallery(page)
        page.locator('.filament-card').filter(has_text='Ocean').get_by_role('link', name='View spools', exact=True).click()
        expect(page.locator('.spool-card')).to_have_count(1)
        page.get_by_role('button', name='Show all products', exact=True).click()
        expect(page.locator('.spool-card')).to_have_count(8)
        assert 'product=' not in page.url
        run_followup_workflows(page)
        page.goto(BASE + '/spools', wait_until='networkidle')
        # Stage and commit a location change via a genuine browser drag. A drop is
        # never itself a server mutation; explicit physical verification is required.
        page.get_by_role('button', name='Locations', exact=True).click()
        page.get_by_label('New location', exact=True).fill('Lab / Bin C')
        page.get_by_role('button', name='Add location', exact=True).click()
        source = page.locator('.storage-spool').first
        uid = source.get_attribute('data-spool-uid')
        assert uid
        before_move = page.request.get(BASE + '/api/spools/by-uid/' + uid).json()
        # Every location stays inside the inventory width, and short/empty
        # columns must not stretch to the height of the busiest location.
        target = page.locator('.storage-lane[data-location="Lab / Bin C"] .storage-empty')
        board = page.locator('#storage-board')
        assert board.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        lane_heights = page.locator('.storage-lane').evaluate_all('(lanes) => lanes.map(el => el.getBoundingClientRect().height)')
        assert min(lane_heights) < max(lane_heights) - 100, lane_heights
        assert page.request.get(BASE + '/api/spools/by-uid/' + uid).json()['location'] == before_move['location']
        page.evaluate("""() => {
          window.storageDragEvents=[];
          for(const type of ['dragstart','dragenter','dragover','drop','dragend']){
            document.addEventListener(type, event => {
              if(window.storageDragEvents.length<35){
                window.storageDragEvents.push({type, target:event.target.tagName+'.'+String(event.target.className).slice(0,80),
                  prevented:event.defaultPrevented, x:event.clientX,y:event.clientY,
                  types:[...(event.dataTransfer?.types||[])]});
              }
            }, true);
          }
        }""")
        # Move both objects into the viewport BEFORE pressing the mouse. Hover
        # actions scroll containers and can cancel a drag that is already held.
        target.scroll_into_view_if_needed()
        handle = source.locator('.drag-handle')
        handle.scroll_into_view_if_needed()
        start, end = handle.bounding_box(), target.bounding_box()
        assert start and end
        sx, sy = start['x'] + start['width']/2, start['y'] + start['height']/2
        tx, ty = end['x'] + end['width']/2, end['y'] + end['height']/2
        assert 0 <= sx < 1440 and 0 <= tx < 1440 and 0 <= sy < 1000 and 0 <= ty < 1000
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx-12, sy-8, steps=5)  # Cross Chromium's drag threshold.
        page.mouse.move(tx, ty, steps=16)      # Dragover must reach the drop lane.
        page.mouse.up()
        print('Storage drag events:',json.dumps(page.evaluate('window.storageDragEvents ?? []')))
        expect(page.locator('.storage-confirm')).to_be_visible()
        expect(page.get_by_role('button', name='Save location', exact=True)).to_be_disabled()
        assert page.request.get(BASE + '/api/spools/by-uid/' + uid).json()['location'] == before_move['location']
        page.locator('.storage-confirm input[type=checkbox]').check()
        page.get_by_role('button', name='Save location', exact=True).click()
        expect(page.locator('.storage-confirm')).to_have_count(0)
        assert page.request.get(BASE + '/api/spools/by-uid/' + uid).json()['location'] == 'Lab / Bin C'
        page.get_by_role('button', name='Cards', exact=True).click()

        # Saved preferences override the OS; System reacts to it without a reload.
        theme.select_option('dark'); page.reload(wait_until='networkidle')
        expect(theme).to_have_value('dark')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        page.emulate_media(color_scheme='light')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        theme.select_option('system')
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        page.emulate_media(color_scheme='dark')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        page.locator('sm-language-picker select').select_option('de')
        # Clear the product URL before reloads and viewport sweeps.
        page.goto(BASE + '/spools', wait_until='networkidle')
        theme.select_option('dark')
        for width in (320, 390, 768, 1024, 1440, 1920):
            page.set_viewport_size({'width': width, 'height': 1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), f'Overflow at {width}px'
            expect(theme).to_be_visible()
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
        assert page.locator('.sidebar').bounding_box()['y'] == 0
        page.get_by_role('button', name='Lagerorte', exact=True).click()
        for width in (320, 390, 768, 1024, 1440, 1920):
            page.set_viewport_size({'width': width, 'height': 1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), f'Locations page overflow at {width}px'
            assert page.locator('#storage-board').evaluate('(el) => el.scrollWidth <= el.clientWidth+1'), f'Clipped locations at {width}px'
            assert page.locator('.storage-lane').evaluate_all('(lanes) => lanes.every(el => {const b=el.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth+1})'), f'Location outside viewport at {width}px'
        page.set_viewport_size({'width': 1440, 'height': 1000})
        expect(page.get_by_role('button', name='Lagerorte', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.storage-spool')).to_have_count(8)
        capture_preview(page, folder / 'ui-de-dark-locations.png', '.label-tray')
        page.get_by_role('button', name='Karten', exact=True).click()
        expect(page.get_by_role('button', name='Karten', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.spool-card')).to_have_count(8)
        expect(page.locator('#storage-board')).to_have_count(0)
        capture_preview(page, folder / 'ui-de-dark-spools.png', '.spool-card-actions')
        theme.select_option('light')
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        capture_preview(page, folder / 'ui-de-light-spools.png', '.spool-card-actions')
        page.locator('.side-nav a[href="/filaments"]').click();theme.select_option('dark')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        expect(page.locator('.filament-card')).to_have_count(6)
        capture_preview(page, folder / 'ui-de-dark-filaments.png', '.filament-card .spool-card-actions')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(BASE + '/spools', wait_until='networkidle')
        expect(page.locator('.mobile-navigation')).to_be_visible()
        # Actual Chromium-computed styles, not mocked markup.
        summary_font = page.locator('.inventory-stats span').first.evaluate('(el) => parseFloat(getComputedStyle(el).fontSize)')
        search_font = page.locator('#spool-search').evaluate('(el) => parseFloat(getComputedStyle(el).fontSize)')
        handle_size = page.locator('.spool-card .drag-handle').first.bounding_box()
        assert summary_font >= 11, f'Inventory metric text too small: {summary_font}'
        assert search_font >= 16, f'Mobile input font too small: {search_font}'
        assert handle_size['width'] >= 44 and handle_size['height'] >= 44, handle_size
        # The stock identity is visible sooner; secondary actions and filters
        # remain keyboard/click accessible behind explicit mobile controls.
        filter_button=page.locator('.mobile-filter-toggle')
        filter_select=page.locator('#spool-material-filter')
        expect(filter_select).not_to_be_visible()
        filter_button.click();expect(filter_select).to_be_visible()
        mobile_sort = page.locator('#spool-mobile-sort')
        expect(mobile_sort).to_be_visible()
        mobile_sort.select_option('remaining-low')
        expect(mobile_sort).to_have_value('remaining-low')
        filter_select.select_option('PETG')
        expect(page.locator('.spool-card')).to_have_count(1)
        filter_button.click();expect(filter_select).not_to_be_visible()
        expect(page.locator('.active-filter-count')).to_have_text('1')
        filter_button.click();filter_select.select_option('')
        expect(page.locator('.spool-card')).to_have_count(8)
        filter_button.click()
        page.locator('.mobile-inventory-actions summary').click()
        expect(page.get_by_role('button', name='CSV importieren', exact=True)).to_be_visible()
        page.get_by_role('button', name='CSV importieren', exact=True).click()
        expect(page.locator('dialog[open]')).to_be_visible()
        expect(page.locator('.mobile-inventory-actions')).not_to_have_attribute('open', '')
        page.get_by_role('button', name='Dialog schließen', exact=True).click()
        page.get_by_role('button', name='Mehr', exact=True).click()
        expect(page.locator('.sidebar')).to_be_visible()
        page.locator('.side-nav a[href="/filaments"]').click()
        expect(page.locator('.sidebar')).not_to_be_visible()
        page.get_by_role('button', name='Mehr', exact=True).click()
        page.keyboard.press('Escape')
        expect(page.locator('.sidebar')).not_to_be_visible()
        page.get_by_role('button', name='Mehr', exact=True).click()
        page.set_viewport_size({'width': 1024, 'height': 844})
        expect(page.locator('.workspace')).not_to_have_attribute('inert', '')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(BASE + '/spools', wait_until='networkidle')
        last=page.locator('.spool-card').last
        last.scroll_into_view_if_needed()
        page.evaluate('window.scrollTo({top:document.body.scrollHeight,behavior:"instant"})')
        tray=page.locator('.label-tray')
        assert tray.bounding_box()['y'] + tray.bounding_box()['height'] < page.locator('.mobile-navigation').bounding_box()['y']
        page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
        first_identity=page.locator('.spool-card-identity').first
        assert first_identity.bounding_box()['y'] + first_identity.bounding_box()['height'] < page.locator('.mobile-navigation').bounding_box()['y']
        expect(page.get_by_role('button', name='Karten', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.spool-card')).to_have_count(8)
        capture_preview(page, folder / 'ui-de-mobile-dark.png', '.mobile-navigation', full_page=False)
        print('UI browser checks passed: real spool/label and printer drops, safe file previews, exact product filtering, light/dark/system, draft persistence, mobile drawer and six viewport widths.')
    except Exception:
        events = page.evaluate('window.printerDragEvents ?? []')
        (folder / 'ui-drag-events.json').write_text(json.dumps(events, indent=2))
        print('Native printer drag events:', json.dumps(events))
        context.tracing.stop(path=str(folder / 'ui-trace.zip'))
        page.screenshot(path=str(folder / 'failure-ui.png'), full_page=True, animations='disabled')
        raise
    finally:
        context.close()
