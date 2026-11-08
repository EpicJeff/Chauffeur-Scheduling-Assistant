"""Your place in real Chromium (plan docs/superpowers/plans/
2026-11-07-house-editor-slice-1b-i.md Task 8, amendments A1, A11, A12): a
full-screen view in the house editor that holds the lot and every building as
cards, the documents and photos on each, the plot plan read with its
suggestions and placement, shell cards for buildings without drawings, and the
Build buttons. It replaces slice 1's Build dropdown and per-page building
selector.

The DOM contract in the Task 8 brief is binding; these scenarios select only by
its ids and data attributes, plus these test-side resolutions of what the
brief leaves open:
  - a page with two role rows (regions, A1) keeps one select[data-place-role]
    and one select[data-place-move] per region inside its
    [data-place-page="<source>:<page>"], in stored order;
  - shell controls carry name="storeys|wall_height|roof|pitch|door_side" and
    the size inputs name="width|depth";
  - a Move to is a saved action: the moved page stays where it was put after a
    reload, also for a page whose roles are not confirmed yet.

Paid routes never reach a model: page suggestions and the plot read are
mocked with page.route. The plot read's mock runs the REAL
twin_place_reads.read_plot in-process with a stub reader, so the suggestion,
placement and building routes behind it are the real ones. Builds are mocked.

Scenarios share one served app and run in the listed order.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_place_live.py
"""
import copy
import json
import os
import sys
import tempfile

# Never the dev data: every service import below reads this temp dir.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_house_place_live_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_app import live_app  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
import test_twin_view_live as p0view  # noqa: E402

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
KIND_LABELS = ['Main house', 'Garage', 'ADU or guest house', 'Pool house', 'Shed', 'Greenhouse', 'Barn',
               'Studio or office', 'Workshop', 'Other']
BUILDING_ROLE_LABELS = ['Floor', 'Roof', 'Outside view', 'Other', 'Skip']
LOT_ROLE_LABELS = ['Plot plan', 'Survey', 'Landscape plan', 'Other', 'Skip']
JSON_HEADERS = {'Content-Type': 'application/json'}
STATE = {}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def _plot_answer():
    """The recorded plot fixture (house, pool house, street edge [1, 2]) plus a third building."""
    answer = engine_tests.fixture('plot')
    answer['buildings'].append({'name': 'shed', 'outline': [[0.45, 0.2], [0.5, 0.2], [0.5, 0.26], [0.45, 0.26]]})
    return answer


def _plot_reader(kind, images, context, *, run, step):
    STATE.setdefault('plot_reads', []).append({'kind': kind, 'run': run, 'step': step, 'images': len(images)})
    return copy.deepcopy(_plot_answer())


def _no_reads(*args, **kwargs):
    return {'error': 'This test makes no model reads.'}


def _seed():
    from services import storage, twin_library, twin_reads
    tmp = os.path.abspath(tempfile.gettempdir())
    check(os.path.abspath(storage.DB_PATH).startswith(tmp), ('the live app must use a temp data dir', storage.DB_PATH))
    twin_library._urlopen = p0view._stub_urlopen
    twin_reads.read = _no_reads
    storage.patch_settings({'auth_enforce': True})
    storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent', 'email': 'pat@example.com'})
    storage.set_member_password('p1', 'correct horse battery staple')
    STATE['token'] = storage.create_member_token('p1')
    engine_tests._fresh()          # an empty house: no plan, no documents, no buildings


SERVED = None


def _serve():
    global SERVED
    if SERVED is None:
        SERVED = live_app(_seed)
    return SERVED


def _signed_in(page):
    page.add_init_script(
        "localStorage.setItem('chauffeur_admin_token', %s);"
        "localStorage.setItem('chauffeur_admin_token_for', 'p1');" % json.dumps(STATE['token']))


def _open(page, s, query='tier=high&test=1'):
    page.set_viewport_size({'width': 1600, 'height': 900})
    _signed_in(page)
    page.goto(s.url(f'house/editor?{query}'))
    page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=60000)


def _api(page, method, path, body=None):
    return page.evaluate("""async ([method, path, body]) => {
        const r = await fetch(window.chfBase + 'api/house/editor/' + path, {
            method, headers: {'Content-Type': 'application/json'},
            body: body === null ? undefined : JSON.stringify(body)});
        return {status: r.status, body: await r.json().catch(() => null)};
    }""", [method, path, body])


def _sheets(page):
    return _api(page, 'GET', 'sheets')['body']


def _place(page):
    return _sheets(page)['place']


def _building(page, bid):
    return next((b for b in _place(page)['buildings'] if b['id'] == bid), None)


def _source(page, filename):
    return next(s for s in _sheets(page)['sources'] if s['filename'] == filename)


def _wait_source(page, filename, timeout=30.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = next((s for s in _sheets(page)['sources'] if s['filename'] == filename), None)
        if found:
            return found
        page.wait_for_timeout(300)
    raise AssertionError(f'{filename} was never uploaded')


def _open_place(page):
    if not page.locator('#place-view').is_visible():
        page.click('#editor-menu')
        page.click('#editor-manage-sources')
    page.wait_for_selector('#place-view', state='visible', timeout=10000)


def _ensure_house():
    """Main house with the id house, as migration and legacy uploads create it."""
    from services import twin_store as ts
    with ts.LIFECYCLE, ts._LOCK:
        row = ts._state()
        ts._legacy_house(ts._place(row))
        ts._save(row)


def _labels(select):
    return [t.strip() for t in select.locator('option').all_inner_texts()]


def _alert_text(page):
    page.wait_for_selector('#cc-alert-modal', state='visible', timeout=10000)
    text = page.inner_text('#cc-alert-message')
    page.evaluate('window.closeGlobalAlert()')
    return text


def _paid_confirm(page, required=False, timeout=3000):
    """Accept the promptConfirm a paid action shows first; return its words."""
    try:
        page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=timeout)
    except Exception:
        check(not required, 'a paid action asks first through promptConfirm')
        return None
    title = page.inner_text('#cc-confirm-title')
    if title.startswith('Spent $'):
        return None                # a spending checkpoint, not the paid ask
    text = title + '\n' + page.inner_text('#cc-confirm-message')
    page.click('#cc-confirm-execute-btn')
    page.wait_for_selector('#cc-confirm-modal', state='hidden', timeout=5000)
    return text


def _upload(page, part, name, mime, data):
    page.set_input_files(f'[data-place-upload="{part}"]', files=[{'name': name, 'mimeType': mime, 'buffer': data}])


def _page_row(page, scope, key):
    return page.locator(f'{scope} [data-place-page="{key}"]')


def _unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


def _json(route, status, body):
    route.fulfill(status=status, headers=JSON_HEADERS, body=json.dumps(body))


# ---- the empty place, buildings, documents -------------------------------

def scenario_empty_place_opens_first():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.wait_for_selector('#place-view', state='visible', timeout=10000)
        check(page.get_by_role('dialog', name='Your place').is_visible(), 'Your place is a dialog named Your place')
        check(page.locator('#editor-build-target').count() == 0, 'the slice 1 building dropdown is retired')
        check(page.locator('[data-page-building]').count() == 0, 'the per-page building selector is retired')
        check(page.locator('#place-lot').is_visible(), 'the Lot card shows')
        check(page.inner_text('#place-close').strip() == 'Back to the house', page.inner_text('#place-close'))
        check((page.text_content('#editor-manage-sources') or '').strip() == 'Your place', 'the menu button reads Your place')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_place_empty.png'))
    check(not _unexpected(s.errors()), s.errors())


def scenario_add_building_and_duplicate():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _open_place(page)
        check(_labels(page.locator('#place-add-kind')) == KIND_LABELS, ('kinds in spec order', _labels(page.locator('#place-add-kind'))))
        page.fill('#place-add-name', 'Detached garage')
        page.select_option('#place-add-kind', label='Garage')
        check(page.inner_text('#place-add').strip() == 'Add building', page.inner_text('#place-add'))
        page.click('#place-add')
        card = page.locator('[data-place-building="detached-garage"]')
        card.wait_for(state='visible', timeout=10000)
        check('Garage' in card.inner_text(), ('the card names its kind', card.inner_text()))
        check(_building(page, 'detached-garage')['kind'] == 'garage', _place(page))
        page.fill('#place-add-name', 'Detached garage')
        page.select_option('#place-add-kind', label='Garage')
        page.click('#place-add')
        text = _alert_text(page)
        check(text == 'There is already a building called Detached garage.', text)
        check(sum(b['name'] == 'Detached garage' for b in _place(page)['buildings']) == 1, 'nothing was added twice')
    check(not _unexpected(s.errors()), s.errors())


def scenario_upload_to_building_and_move_page():
    s = _serve()
    if s is None:
        return
    _ensure_house()
    uploads, moves = [], []
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/twin/sources', lambda r: (uploads.append(r.request.post_data_buffer or b''), r.continue_()))
        page.route('**/api/house/editor/place/pages/move', lambda r: (moves.append(json.loads(r.request.post_data)), r.continue_()))
        _open_place(page)
        accept = (page.get_attribute('[data-place-upload="house"]', 'accept') or '').lower()
        check('pdf' in accept and ('jpeg' in accept or 'jpg' in accept) and 'png' in accept, ('PDF, JPEG and PNG', accept))
        _upload(page, 'house', 'two.pdf', 'application/pdf', engine_tests._pdf(2))
        page.wait_for_function(
            "() => document.querySelectorAll('[data-place-building=\"house\"] [data-place-page]').length === 2",
            timeout=30000)
        check(uploads and b'name="part"\r\n\r\nhouse' in uploads[-1], 'the upload posts part house')
        src = _source(page, 'two.pdf')['id']
        STATE['src'] = src
        house = '[data-place-building="house"]'
        for n in (1, 2):
            row = _page_row(page, house, f'{src}:{n}')
            check(_labels(row.locator('select[data-place-role]').first) == BUILDING_ROLE_LABELS,
                  ('building roles', _labels(row.locator('select[data-place-role]').first)))
            check(row.locator('input[data-place-level]').count() >= 1, 'a building page names its level')
            moves_to = _labels(row.locator('select[data-place-move]').first)
            check('Lot' in moves_to and 'Detached garage' in moves_to and 'Main house' not in moves_to,
                  ('Move to lists every other part', moves_to))
        _page_row(page, house, f'{src}:2').locator('select[data-place-move]').first.select_option(label='Lot')
        lot_row = _page_row(page, '#place-lot', f'{src}:2')
        lot_row.wait_for(state='visible', timeout=10000)
        check(moves and moves[-1]['source'] == src and moves[-1]['page'] == 2 and moves[-1]['part'] == 'lot',
              ('one change moves the page at once', moves))
        check(_page_row(page, house, f'{src}:2').count() == 0, 'page 2 left the house card')
        role = lot_row.locator('select[data-place-role]').first
        check(role.input_value() == 'other', ('a floor page moved to the lot becomes Other', role.input_value()))
        check(_labels(role) == LOT_ROLE_LABELS, ('lot roles', _labels(role)))
        check(lot_row.locator('input[data-place-level]').count() == 0, 'the lot has no level names')
        page.reload()
        page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=60000)
        _open_place(page)
        _page_row(page, '#place-lot', f'{src}:2').wait_for(state='visible', timeout=10000)
        check(_page_row(page, house, f'{src}:1').count() == 1, 'page 1 stays with the house')
    check(not _unexpected(s.errors()), s.errors())


def scenario_photo_tags():
    s = _serve()
    if s is None:
        return
    puts = []
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/editor/place/photos/**',
                   lambda r: (puts.append(json.loads(r.request.post_data)) if r.request.method == 'PUT' else None,
                              r.continue_()))
        _open_place(page)
        _upload(page, 'lot', 'yard.jpg', 'image/jpeg', engine_tests._jpeg())
        page.wait_for_function("() => document.querySelectorAll('[data-place-photo]').length >= 1", timeout=30000)
        pid = _source(page, 'yard.jpg')['id']
        photo = page.locator(f'[data-place-photo="{pid}"]')
        photo.wait_for(state='visible', timeout=10000)
        check(photo.locator('button[data-place-tag="lot"]').get_attribute('aria-pressed') == 'true', 'the Lot tag is pressed')
        check(photo.locator('button[data-place-tag="house"]').get_attribute('aria-pressed') == 'false', 'Main house is not')
        check(photo.locator('button[data-place-tag="detached-garage"]').count() == 1, 'a tag for every part')
        photo.locator('button[data-place-tag="house"]').click()
        page.wait_for_function(
            f"() => document.querySelector('[data-place-photo=\"{pid}\"] button[data-place-tag=\"house\"]')"
            ".getAttribute('aria-pressed') === 'true'", timeout=10000)
        check(puts and puts[-1]['parts'] == ['lot', 'house'], puts)
        check(_place(page)['photo_tags'][pid] == ['lot', 'house'], _place(page)['photo_tags'])
    check(not _unexpected(s.errors()), s.errors())


def scenario_hint_moves_page():
    s = _serve()
    if s is None:
        return
    suggested, moves = [], []

    def suggest(route):
        body = json.loads(route.request.post_data or '{}')
        suggested.append(body)
        _json(route, 200, {'rows': [{'source': body.get('source'), 'page': 1, 'role': 'floor', 'level': 'Main floor',
                                     'box': None, 'building': 'house', 'elsewhere': 'detached-garage',
                                     'hint': 'Page 1 looks like the Detached garage.'}]})
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/editor/sheets/suggest', suggest)
        page.route('**/api/house/editor/place/pages/move', lambda r: (moves.append(json.loads(r.request.post_data)), r.continue_()))
        _open_place(page)
        _upload(page, 'house', 'garage-sheet.pdf', 'application/pdf', engine_tests._pdf(1))
        page.wait_for_function("() => document.querySelectorAll('[data-place-suggest]').length >= 1", timeout=30000)
        src = _source(page, 'garage-sheet.pdf')['id']
        STATE['hint_src'] = src
        button = page.locator(f'[data-place-suggest="{src}"]')
        check(button.inner_text().strip().startswith('Suggest page roles'), button.inner_text())
        button.click()
        _paid_confirm(page)
        hint = page.locator('[data-place-hint]').first
        hint.wait_for(state='visible', timeout=10000)
        check('Page 1 looks like the Detached garage.' in hint.inner_text(), hint.inner_text())
        check(suggested and suggested[-1]['source'] == src, suggested)
        hint.get_by_role('button', name='Move it').click()
        _page_row(page, '[data-place-building="detached-garage"]', f'{src}:1').wait_for(state='visible', timeout=10000)
        check(_page_row(page, '[data-place-building="house"]', f'{src}:1').count() == 0, 'it left the house')
        check(moves and moves[-1]['part'] == 'detached-garage' and moves[-1]['page'] == 1, moves)
    check(not _unexpected(s.errors()), s.errors())


def scenario_region_moves_alone():
    # A1: a sheet with two cropped regions sends each region where it belongs.
    s = _serve()
    if s is None:
        return
    moves = []
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _open_place(page)
        _upload(page, 'house', 'two-regions.pdf', 'application/pdf', engine_tests._pdf(1))
        src = _wait_source(page, 'two-regions.pdf')['id']
        STATE['region_src'] = src
        rows = [{k: r[k] for k in ('source', 'page', 'role', 'level', 'box', 'building')}
                for r in _sheets(page)['page_roles'] if r['source'] != src]
        rows += [{'source': src, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': [0, 0, 0.5, 1], 'building': 'house'},
                 {'source': src, 'page': 1, 'role': 'roof', 'level': None, 'box': [0.5, 0, 1, 1], 'building': 'house'}]
        r = _api(page, 'PUT', 'sheets/roles', {'rows': rows})
        check(r['status'] == 200, r)
        page.reload()
        page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=60000)
        page.route('**/api/house/editor/place/pages/move', lambda r: (moves.append(json.loads(r.request.post_data)), r.continue_()))
        _open_place(page)
        house, garage = '[data-place-building="house"]', '[data-place-building="detached-garage"]'
        row = _page_row(page, house, f'{src}:1')
        row.first.wait_for(state='visible', timeout=10000)
        check(page.locator(f'{house} [data-place-page="{src}:1"] select[data-place-role]').count() == 2, 'one role per region')
        movers = page.locator(f'{house} [data-place-page="{src}:1"] select[data-place-move]')
        check(movers.count() == 2, 'each region has its own Move to')
        movers.nth(1).select_option(label='Detached garage')
        page.wait_for_function(
            f"() => document.querySelectorAll('{garage} [data-place-page=\"{src}:1\"] select[data-place-role]').length === 1",
            timeout=10000)
        check(moves and moves[-1] == {'source': src, 'page': 1, 'part': 'detached-garage', 'region': 1},
              ('the move names its region', moves))
        left = page.locator(f'{house} [data-place-page="{src}:1"] select[data-place-role]')
        moved = page.locator(f'{garage} [data-place-page="{src}:1"] select[data-place-role]')
        check(left.count() == 1 and left.first.input_value() == 'floor', 'the other region stays with the house')
        check(moved.first.input_value() == 'roof', 'only the moved region shows under the garage')
        stored = [r for r in _sheets(page)['page_roles'] if r['source'] == src]
        check([(r['role'], r['building']) for r in stored] == [('floor', 'house'), ('roof', 'detached-garage')], stored)
    check(not _unexpected(s.errors()), s.errors())


# ---- the plot plan read in setup -----------------------------------------

def _confirm_plot_page(page):
    """The hand path: page 2 of two.pdf (on the lot) becomes the plot plan, then Confirm pages."""
    src = STATE['src']
    role = _page_row(page, '#place-lot', f'{src}:2').locator('select[data-place-role]').first
    if role.input_value() != 'plot':
        role.select_option('plot')
    page.click('#place-confirm-pages')
    page.wait_for_function("() => !document.querySelector('#place-read-plot').disabled", timeout=10000)


def scenario_plot_read_checkpoint_opens_continue():
    # A12: the plot read checks spend before any work, so Continue retries it.
    s = _serve()
    if s is None:
        return
    calls, acks = [], []

    def read(route):
        calls.append(1)
        if len(calls) == 1:
            return _json(route, 409, {'detail': {'checkpoint': 10.0, 'total': 10.12}})
        return _json(route, 400, {'detail': 'The plot plan could not be read. Try again, or place the buildings by hand.'})
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _open_place(page)
        check(page.locator('#place-read-plot').is_disabled(), 'the read waits for a confirmed plot page')
        _confirm_plot_page(page)
        page.route('**/api/house/editor/place/plot/read', read)
        page.route('**/api/house/twin/cost/ack', lambda r: (acks.append(1), _json(r, 200, {})))
        page.click('#place-read-plot')
        _paid_confirm(page, required=True)
        page.wait_for_function("() => document.body.innerText.includes('Spent $10.12 so far')", timeout=10000)
        page.get_by_role('button', name='Continue', exact=True).click()
        text = _alert_text(page)
        check(acks == [1] and len(calls) == 2, ('Continue acknowledges and retries the read', acks, calls))
        check(text == 'The plot plan could not be read. Try again, or place the buildings by hand.',
              ('errors show the server sentence', text))
    check(not _unexpected(s.errors()), s.errors())


def scenario_plot_read_suggestions_and_placement():
    s = _serve()
    if s is None:
        return
    from services import twin_place_reads
    reads, placements = [], []

    def read(route):
        reads.append(1)
        lot = twin_place_reads.read_plot(reader=_plot_reader)
        _json(route, 200, {'lot': lot, 'cost': lot['read']['cost']})
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/editor/place/plot/read', read)
        page.route('**/api/house/editor/place/lot/placement',
                   lambda r: (placements.append(json.loads(r.request.post_data)), r.continue_()))
        _open_place(page)
        if page.locator('#place-read-plot').is_disabled():
            _confirm_plot_page(page)
        estimate = f"${_sheets(page)['estimates']['plot']:.2f}"
        label = page.inner_text('#place-read-plot')
        check(label.startswith('Read the plot plan') and f'about {estimate}' in label, (label, estimate))
        page.click('#place-read-plot')
        asked = _paid_confirm(page, required=True)
        check(estimate in asked, ('the confirm names the estimate', asked, estimate))
        page.wait_for_function("() => document.querySelectorAll('[data-place-suggestion]').length === 3", timeout=15000)
        check(reads == [1] and STATE['plot_reads'][-1]['step'] == 'plot', 'one plot read')
        for sid in ('plot-1', 'plot-2', 'plot-3'):
            text = page.inner_text(f'[data-place-suggestion="{sid}"]')
            check('at the' in text and any(c.isdigit() for c in text), ('size and where words', sid, text))
        check(_building(page, 'shed') is None, 'nothing becomes part of the place without the person accepting it')
        outlines = {s_['id']: s_['outline'] for s_ in _place(page)['lot']['read']['suggestions']}

        shed = page.locator('[data-place-suggestion="plot-2"]')
        shed.locator('input[data-suggestion-name]').fill('Shed')
        shed.locator('select[data-suggestion-kind]').select_option(label='Shed')
        match = shed.locator('select[data-suggestion-match]')
        check(_labels(match)[0] == 'New building' and 'Main house' in _labels(match), _labels(match))
        match.select_option(label='New building')
        shed.locator('button[data-suggestion-accept]').click()
        page.locator('[data-place-building="shed"]').wait_for(state='visible', timeout=10000)
        check('Shed' in page.inner_text('[data-place-building="shed"]'), 'a shed card')
        check(_building(page, 'shed')['kind'] == 'shed' and _building(page, 'shed')['footprint'] == outlines['plot-2'],
              _building(page, 'shed'))

        house = page.locator('[data-place-suggestion="plot-1"]')
        house.locator('select[data-suggestion-match]').select_option(label='Main house')
        house.locator('button[data-suggestion-accept]').click()
        page.wait_for_function(
            "() => !document.querySelector('[data-place-suggestion=\"plot-1\"] button[data-suggestion-accept]')", timeout=10000)
        check(_building(page, 'house')['footprint'] == outlines['plot-1'], ('matched to Main house', _building(page, 'house')))
        check(len(_place(page)['buildings']) == 3, 'matching adds no building')

        page.locator('[data-place-suggestion="plot-3"] button[data-suggestion-dismiss]').click()
        page.wait_for_function("() => !document.querySelector('[data-place-suggestion=\"plot-3\"]')", timeout=10000)

        # The map: drag the shed's footprint 50 px, then confirm the placement.
        page.wait_for_selector('#place-map [data-place-footprint="shed"]', state='visible', timeout=10000)
        check(page.locator('#place-map [data-place-footprint="house"]').count() == 1, 'every accepted footprint is drawn')
        box = page.locator('#place-map [data-place-footprint="shed"]').bounding_box()
        x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        for step in range(1, 11):
            page.mouse.move(x + step * 5, y)
        page.mouse.up()
        check(page.inner_text('#place-confirm-placement').strip() == 'These are in the right place',
              page.inner_text('#place-confirm-placement'))
        page.click('#place-confirm-placement')
        page.wait_for_timeout(800)
        check(placements, 'Confirm sends the placement')
        sent = next(f['outline'] for f in placements[-1]['footprints'] if f['building'] == 'shed')
        before = outlines['plot-2']
        shift = [sent[0][0] - before[0][0], sent[0][1] - before[0][1]]
        check(abs(shift[0]) + abs(shift[1]) > 0.5, ('the drag moved the shed', before, sent))
        check(all(close([p[0] - q[0], p[1] - q[1]], shift, 1e-3) for p, q in zip(sent, before)),
              ('a drag moves, it does not reshape', before, sent))
        check(_place(page)['lot']['placement']['confirmed'] is True, 'the placement is confirmed')

        page.locator('#place-map [data-place-edge="0"]').click()
        page.wait_for_timeout(800)
        if not any(p.get('street_edge') == [0, 1] for p in placements):
            page.click('#place-confirm-placement')
            page.wait_for_timeout(800)
        check(any(p.get('street_edge') == [0, 1] for p in placements), ('tapping a lot edge makes it the street', placements))
        check(_place(page)['lot']['placement']['street_edge'] == [0, 1], _place(page)['lot']['placement'])
    check(not _unexpected(s.errors()), s.errors())


def scenario_shell_card_and_size():
    s = _serve()
    if s is None:
        return
    patches = []
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/editor/place/buildings/**',
                   lambda r: (patches.append(json.loads(r.request.post_data)) if r.request.method == 'PATCH' else None,
                              r.continue_()))
        _open_place(page)
        card = page.locator('[data-place-building="shed"]')
        card.wait_for(state='visible', timeout=10000)
        shell = page.locator('[data-place-shell="shed"]')
        check(shell.is_visible(), 'a building without drawings has a shell card')
        for field in ('storeys', 'wall_height', 'roof', 'pitch', 'door_side'):
            check(shell.locator(f'[name="{field}"]').count() == 1, ('shell control', field))
        check(page.locator('[data-place-shell="house"]').count() == 0, 'a building with drawings has no shell card')
        check(card.locator('[data-place-draw]').is_visible(), 'Draw on the lot shows once the lot is placed')
        size = card.locator('[data-place-size]')
        size.locator('[name="width"]').fill('10')
        size.locator('[name="depth"]').fill('12')
        size.get_by_role('button', name='Set size').click()
        page.wait_for_timeout(800)
        sized = [p for p in patches if 'footprint' in p]
        check(sized, ('Set size sends a footprint', patches))
        fp = sized[-1]['footprint']
        x, y = fp[0]
        check(len(fp) == 4 and close(fp[1], [x + 10, y]) and close(fp[2], [x + 10, y + 12]) and close(fp[3], [x, y + 12]),
              ('a 10 by 12 rectangle', fp))
        check(_building(page, 'shed')['footprint'] == fp, 'saved')
        shell.locator('[name="roof"]').select_option('hip')
        page.wait_for_timeout(800)
        shelled = [p for p in patches if 'shell' in p]
        check(shelled and shelled[-1]['shell']['roof'] == 'hip', patches)
        check(_building(page, 'shed')['shell']['roof'] == 'hip', _building(page, 'shed'))
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_place_cards.png'))
    check(not _unexpected(s.errors()), s.errors())


# ---- builds ---------------------------------------------------------------

def _build(bid, state, **extra):
    return {'id': bid, 'state': state, 'steps': [], 'events': [], 'seq': 1, 'pause': None, 'cost': 0.1, 'next': None,
            **extra}


def scenario_build_place_follows_chain():
    # A11: following next happens inside the poller.
    s = _serve()
    if s is None:
        return
    posts, gets = [], []

    def builds(route):
        req = route.request
        if req.method == 'POST' and req.url.endswith('/api/house/editor/build'):
            posts.append(json.loads(req.post_data))
            return _json(route, 200, {'id': 'b-chain-1'})
        if req.method == 'GET' and '/build/b-chain-1' in req.url:
            gets.append('b-chain-1')
            return _json(route, 200, _build('b-chain-1', 'done', part='lot', next='b-chain-2'))
        if req.method == 'GET' and '/build/b-chain-2' in req.url:
            gets.append('b-chain-2')
            return _json(route, 200, _build('b-chain-2', 'done', part='house'))
        return route.continue_()
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/editor/build**', builds)
        _open_place(page)
        check(page.inner_text('[data-place-build="lot"]').strip() == 'Build the lot', page.inner_text('[data-place-build="lot"]'))
        check(page.inner_text('[data-place-build="house"]').strip() == 'Build this building',
              page.inner_text('[data-place-build="house"]'))
        check(page.inner_text('#place-build').strip() == 'Build your place', page.inner_text('#place-build'))
        page.click('#place-build')
        _paid_confirm(page)
        page.wait_for_function("() => document.querySelector('#place-view').hidden || "
                               "getComputedStyle(document.querySelector('#place-view')).display === 'none'", timeout=10000)
        deadline = 10
        while deadline > 0 and 'b-chain-2' not in gets:
            page.wait_for_timeout(500)
            deadline -= 0.5
        check(posts and posts[-1] == {'part': 'place'}, ('Build your place posts part place', posts))
        check('b-chain-1' in gets and 'b-chain-2' in gets and gets.index('b-chain-2') > gets.index('b-chain-1'),
              ('the editor follows next', gets))
    check(not _unexpected(s.errors()), s.errors())


def _push_two_building_plan():
    from services import twin_plan, twin_store
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_lot58_main.plan.json'),
              encoding='utf-8') as f:
        plan = twin_plan.normalize(json.load(f))[0]
    twin_store.push_round(plan, 'build')
    return plan


def _fit_build(part, step):
    return _build('b-fit', 'paused', part=part, steps=[step], pause={
        'kind': 'lot_placement', 'step': 'fit', 'why': 'This building has no footprint on the lot yet. Drag it into place.',
        'transform': STATE['transforms'][part],
        'registration': {'scale': 1, 'angle': 0, 'origin_px': [0, 0], 'offset': [0, 0]}})


def _drag_fit(s, part, step):
    answers = []

    def route(r):
        if r.request.method == 'POST':
            answers.append(json.loads(r.request.post_data or '{}'))
            return _json(r, 200, {})
        return _json(r, 200, _fit_build(part, step))
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/editor/build/b-fit**', route)
        if page.locator('#place-view').is_visible():
            page.click('#place-close')
        page.evaluate("() => window.__editor.followBuild('b-fit')")
        page.wait_for_selector('#pause-card', state='visible', timeout=10000)
        where = "(id) => { const b = window.__twin.plan.buildings.find(b => b.id === id); return b && b.position; }"
        lot = page.evaluate('() => JSON.stringify(window.__twin.plan.site && window.__twin.plan.site.lot)')
        others = {bid: page.evaluate(where, bid) for bid in ('house', 'pool_house')}
        page.evaluate("() => window.__editor.dragPauseGhost(60, 0)")
        page.wait_for_function(f"([id, p]) => {{ const q = ({where})(id); return q && Math.hypot(q[0] - p[0], q[1] - p[1]) > 0.5; }}",
                               arg=[part, others[part]], timeout=10000)
        for bid, position in others.items():
            if bid != part:
                check(close(page.evaluate(where, bid), position, 1e-6), (f'{bid} did not move', part))
        check(page.evaluate('() => JSON.stringify(window.__twin.plan.site && window.__twin.plan.site.lot)') == lot,
              'the lot did not move')
        moved = page.evaluate(where, part)
        page.click('#pause-accept')
        page.wait_for_function('() => window.__editor.lastAnswer() !== null', timeout=10000)
        sent = page.evaluate('window.__editor.lastAnswer().decision.transform')
        check(sent and close(sent['position'], moved, 1e-6), ('Looks right sends where the owner was dragged', sent, moved))
    return answers


def scenario_fit_pause_drags_owner():
    # The owner of a fit pause is the build's part, never a page lookup.
    s = _serve()
    if s is None:
        return
    plan = _push_two_building_plan()
    STATE['transforms'] = {b['id']: {'position': list(b['position']), 'rotation': b['rotation']} for b in plan['buildings']}
    plot_src = STATE['src']
    # The house's fit, on a step that also names the lot's plot page: a page
    # lookup would choose the lot.
    _drag_fit(s, 'house', {'id': 'fit', 'status': 'paused', 'label': 'Fit Main house onto the lot',
                           'source': plot_src, 'page': 2})
    # Pool house's fit: a page lookup would fall back to the house.
    _drag_fit(s, 'pool_house', {'id': 'fit', 'status': 'paused', 'label': 'Fit Pool house onto the lot'})
    check(not _unexpected(s.errors()), s.errors())


def scenario_lot_plot_pause_offers_looks_right_and_reread():
    s = _serve()
    if s is None:
        return
    build = _build('b-lot', 'paused', part='lot',
                   steps=[{'id': 'plot', 'status': 'paused', 'label': 'Plot plan', 'source': STATE['src'], 'page': 2}],
                   pause={'kind': 'lot_placement', 'step': 'plot', 'why': 'Check where the lot sits.',
                          'transform': {'position': [0, 0], 'rotation': 0},
                          'registration': {'scale': 0.03, 'angle': 0, 'origin_px': [0, 0], 'offset': [0, 0]}})
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.route('**/api/house/editor/build/b-lot**', lambda r: _json(r, 200, build if r.request.method == 'GET' else {}))
        if page.locator('#place-view').is_visible():
            page.click('#place-close')
        page.evaluate("() => window.__editor.followBuild('b-lot')")
        page.wait_for_selector('#pause-card', state='visible', timeout=10000)
        check(page.locator('#pause-accept').is_visible() and page.locator('#pause-reread').is_visible(),
              'Looks right and Re-read')
        for sel in ('#pause-drag', '#pause-pin', '#pause-turn-label'):
            check(not page.locator(sel).is_visible(), (sel, 'a lot plot pause offers only Looks right and Re-read'))
    check(not _unexpected(s.errors()), s.errors())


if __name__ == '__main__':
    for fn in (scenario_empty_place_opens_first,
               scenario_add_building_and_duplicate,
               scenario_upload_to_building_and_move_page,
               scenario_photo_tags,
               scenario_hint_moves_page,
               scenario_region_moves_alone,
               scenario_plot_read_checkpoint_opens_continue,
               scenario_plot_read_suggestions_and_placement,
               scenario_shell_card_and_size,
               scenario_build_place_follows_chain,
               scenario_fit_pause_drags_owner,
               scenario_lot_plot_pause_offers_looks_right_and_reread):
        fn()
        print('  ok ', fn.__name__)
