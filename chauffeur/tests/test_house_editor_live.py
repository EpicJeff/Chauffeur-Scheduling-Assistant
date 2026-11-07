"""The house editor in real Chromium (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md sections 6, 7, 9; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 13, plus the
Task 10 review carry: a signed-out person must see the sign-in, not a blank
page). Auth enforcement is ON; a parent session is placed in localStorage the
way admin_gate stores it. The model is a fake reader patched in-process at
services.twin_reads.read, so a Build streams ghosts with no spend.

Run from chauffeur/:  python tests/test_house_editor_live.py
"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_live_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_app import live_app  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
import test_twin_view_live as p0view  # noqa: E402

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
BANNED = ('mesh', 'extrude', 'gizmo', 'vertex')
STATE = {}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _seed():
    from services import storage, twin_library, twin_reads
    twin_library._urlopen = p0view._stub_urlopen
    storage.patch_settings({'auth_enforce': True})
    storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent'})
    STATE['token'] = storage.create_member_token('p1')
    engine_tests._fresh()
    _, _, photo = engine_tests._sources()
    STATE['photo'] = photo
    STATE['reader'] = engine_tests.Reader()
    twin_reads.read = STATE['reader']


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
    page.goto(s.url(f'house/editor?{query}'))
    page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=60000)


def _api(page, method, path, body=None):
    return page.evaluate("""async ([method, path, body]) => {
        const r = await fetch(window.chfBase + 'api/house/editor/' + path, {
            method, headers: {'Content-Type': 'application/json'},
            body: body === null ? undefined : JSON.stringify(body)});
        return {status: r.status, body: await r.json().catch(() => null)};
    }""", [method, path, body])


def _unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


def scenario_signed_out_sees_the_sign_in():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.goto(s.url('house/editor'))
        page.wait_for_timeout(2500)
        check(page.get_by_role('heading', name='Sign in').is_visible(), 'the sign-in shows, not a blank page')


def scenario_shell_matches_the_mockup_regions():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        for sel in ('#editor-scene canvas', '#editor-top', '#editor-rail', '#editor-floors', '#editor-agent',
                    '#editor-time'):
            check(page.locator(sel).first.is_visible(), sel)
        check('$' in page.inner_text('#editor-top'), 'running cost in the top bar')
        bar = page.get_by_placeholder("Ask Argyle... (e.g. 'What is my driving schedule today?')")
        check(bar.count() == 0 or not bar.first.is_visible(), 'the app-wide command bar is hidden: the editor has its own Argyle panel')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_shell.png'))
    check(not _unexpected(s.errors()), s.errors())


def scenario_build_streams_ghosts_and_log_lines():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        start = time.time()
        page.click('#editor-build')
        page.wait_for_function('window.__editor.ghostCount() > 0', timeout=30000)
        check(time.time() - start < 30, 'first ghost within 30 s')
        st = page.evaluate('window.__editor.build()')
        check(st and st['state'] == 'paused' and st['pause']['kind'] == 'scale_outline', st)
        r = _api(page, 'POST', f"build/{st['id']}/answer", {'step': 'outline:L1', 'decision': {'accept': True}})
        check(r['status'] == 200, r)
        page.wait_for_function(
            """() => document.querySelector('#editor-agent').innerText.includes("Main floor outline: 70'-0\\" by 65'-4\\"")""",
            timeout=20000)
        page.wait_for_function(
            "() => document.querySelector('#editor-agent').innerText.toLowerCase().includes('stamp')", timeout=20000)
        check(page.locator('#editor-build').is_disabled(), 'Build is off while a build is paused')
        page.wait_for_timeout(1500)
        plan = _api(page, 'GET', 'state')['body']['plan']
        walls = [w for w in plan['buildings'][0]['walls'] if w['level'] == 'L1']
        drawn = page.evaluate("() => window.__twin.pieceIds('house')")
        check(walls and all(w['id'] in drawn for w in walls), ('every main-floor wall is drawn', len(walls), drawn[:10]))
        lines = page.inner_text('#editor-agent').splitlines()
        check(sum('more than 2 ft' in line for line in lines) <= 2, 'repeated reasons are summarised, not one line per piece')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_building.png'))
    check(not _unexpected(s.errors()), s.errors())


def scenario_signed_out_message():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        page.route('**/api/house/editor/state', lambda route: route.fulfill(
            status=401, body='401: Unauthorized', headers={'Content-Type': 'text/plain'}))
        page.evaluate('window.__editor.pollNow()')
        page.wait_for_function(
            "() => document.body.innerText.includes('Home Assistant signed this tab out')", timeout=10000)
        check('401: Unauthorized' not in page.inner_text('body'), 'no raw error')


def scenario_idle_poll_is_one_minute_and_building_poll_one_second():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        check(page.evaluate('window.__editor.idleInterval') == 60000, 'keep-alive cadence')
        check(page.evaluate('window.__editor.buildInterval') == 1000, 'build cadence')


def scenario_checkpoint_asks_to_continue():
    # Runs before any build exists (Build is off while one is active): a due
    # checkpoint at Build asks with the app's own confirm sheet.
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        page.route('**/api/house/editor/build', lambda route: route.fulfill(
            status=409, body=json.dumps({'detail': {'checkpoint': 10.0, 'total': 10.12}}),
            headers={'Content-Type': 'application/json'}))
        page.click('#editor-build')
        page.wait_for_function("() => document.body.innerText.includes('Spent $10.12 so far')", timeout=10000)
        page.get_by_role('button', name='Stop', exact=True).click()


def scenario_no_banned_words():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        text = page.inner_text('body').lower()
        check(not any(w in text for w in BANNED), [w for w in BANNED if w in text])


def scenario_empty_state_uploads_and_suggests_roles():
    # Runs last: it starts over to reach the empty house.
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        from services import twin_build
        for bid in list(getattr(twin_build, '_BUILDS', {}) or {}):
            try:
                twin_build.stop(bid)
            except Exception:
                pass
        r = _api(page, 'POST', 'start-over', {})
        check(r['status'] == 200, r)
        page.reload()
        page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=60000)
        check(page.locator('#editor-upload').is_visible(), 'the upload card shows on an empty house')
        check(page.locator('#editor-build').is_disabled(), 'Build waits for confirmed pages')
        pdf = engine_tests._pdf(3)
        page.set_input_files('#editor-upload input[type=file]', files=[
            {'name': 'lot58.pdf', 'mimeType': 'application/pdf', 'buffer': pdf}])
        page.wait_for_function("() => document.querySelectorAll('[data-page-role]').length >= 3", timeout=30000)
        page.click('#editor-suggest-roles')
        page.wait_for_function(
            "() => [...document.querySelectorAll('[data-page-role]')].some(s => s.value === 'roof')", timeout=20000)
        page.click('#editor-confirm-roles')
        page.wait_for_function("() => !document.querySelector('#editor-build').disabled", timeout=10000)
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_empty.png'))
    check(not _unexpected(s.errors()), s.errors())


# ---- Tasks 14-17: scene tools, plan view, pauses, timeline -----------------
# These run after scenario_build_streams_ghosts_and_log_lines, which leaves the
# build paused at registration:L2 with the main floor settled.

def _plan(page):
    return _api(page, 'GET', 'state')['body']['plan']


def _piece(plan, pid):
    for b in plan['buildings']:
        for kind in ('walls', 'openings', 'rooms'):
            for item in b.get(kind) or []:
                if item['id'] == pid:
                    return item
        for sec in b['roof']['sections']:
            if sec['id'] == pid:
                return sec
    return None


def _first(plan, kind, level='L1'):
    return next(i for i in plan['buildings'][0][kind] if i.get('level', level) == level and i.get('state') != 'ghost')


def _card_set(page, label, value):
    field = page.locator('#piece-card').get_by_label(label, exact=True)
    field.fill(value)
    field.press('Enter')


def scenario_card_edit_round_trip():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        wall = _first(_plan(page), 'walls')
        page.evaluate("([p, b]) => window.__editor.clickPiece(p, b)", [wall['id'], 'house'])
        page.wait_for_selector('#piece-card', state='visible', timeout=10000)
        check(page.evaluate('window.__editor.selected().pieceId') == wall['id'], 'selected')
        _card_set(page, 'Height', "11'-0\"")
        page.wait_for_function(f"() => window.__editor.lastSummary().startsWith('Set ')", timeout=10000)
        check(_piece(_plan(page), wall['id'])['height'] == 11, 'saved through the edit route')
        check(page.locator('#piece-card').get_by_role('button', name='Ask Argyle about this').is_visible(), 'ask')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_card.png'))


def scenario_drag_moves_on_the_floor_only():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.click('#rail-move')
        wall = _first(_plan(page), 'walls')
        page.evaluate("([p, b, dx, dy]) => window.__editor.dragPiece(p, b, dx, dy)", [wall['id'], 'house', 80, 0])
        page.wait_for_function("() => window.__editor.lastSummary().startsWith('Moved')", timeout=10000)
        moved = _piece(_plan(page), wall['id'])
        check(moved['from'] != wall['from'] and moved['height'] == wall['height'], (wall, moved))


def scenario_rotate_snaps_to_quarter_turns():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.click('#rail-rotate')
        page.evaluate("([b, deg]) => window.__editor.rotateBuilding(b, deg)", ['house', 86])
        page.wait_for_function("() => window.__editor.lastSummary().startsWith('Turned')", timeout=10000)
        check(_plan(page)['buildings'][0]['rotation'] == 90, 'snapped to a quarter turn')
        page.evaluate("([b, deg]) => window.__editor.rotateBuilding(b, deg)", ['house', -90])
        page.wait_for_function("() => window.__editor.lastSummary().startsWith('Turned')", timeout=10000)


def scenario_cameras_floors_and_sheet():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        for name in ('Top', 'Front', 'Back', 'Orbit'):
            page.get_by_role('button', name=name, exact=True).click()
        page.locator('#editor-floors').get_by_role('button', name='Main floor').click()
        vis = page.evaluate('window.__twin.levelVisibility()')
        check(vis.get('house:L1') and not vis.get('house:L2', False), vis)
        page.click('#rail-sheet')
        page.wait_for_function('() => window.__twin.sheetInfo() && window.__twin.sheetInfo().ready', timeout=20000)


def scenario_plan_view_is_flat_and_adds_walls_and_windows():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.click('#rail-plan')
        check(page.evaluate('window.__editor.cameraKind()') == 'orthographic-top', 'flat top-down')
        page.click('#plan-add-wall')
        for x, y in ((10, 10), (20, 10.4)):
            px, py = page.evaluate("([x, y]) => window.__editor.screenOfFloor(x, y, 'house:L1')", [x, y])
            page.mouse.click(px, py)
        page.wait_for_function("() => window.__editor.lastSummary().startsWith('Added a wall')", timeout=10000)
        walls = _plan(page)['buildings'][0]['walls']
        added = [w for w in walls if abs(w['from'][0] - 10) < 0.3 and abs(w['from'][1] - 10) < 0.3]
        check(added and abs(added[0]['to'][1] - added[0]['from'][1]) < 0.01, ('snapped straight', added))
        page.click('#plan-add-window')
        mid = [(added[0]['from'][0] + added[0]['to'][0]) / 2, added[0]['from'][1]]
        px, py = page.evaluate("([x, y]) => window.__editor.screenOfFloor(x, y, 'house:L1')", mid)
        page.mouse.click(px, py)
        page.wait_for_function("() => window.__editor.lastSummary().startsWith('Added a window')", timeout=10000)
        check(any(o.get('wall') == added[0]['id'] and o['kind'] == 'window' and o['width'] == 3
                  for o in _plan(page)['buildings'][0]['openings']), 'window added')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_plan_view.png'))


def scenario_pause_card_shows_its_reason_cost_and_pins():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.wait_for_selector('#pause-card', state='visible', timeout=20000)
        text = page.inner_text('#pause-card')
        check('stamp' in text.lower() or 'sure' in text.lower(), text)
        check('$' in page.inner_text('#pause-reread'), 'the re-read shows its cost')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_pause.png'))
        page.click('#pause-pin')
        for gx, gy, sx, sy in ((0.3, 0.2, 0.31, 0.2), (0.6, 0.7, 0.61, 0.7)):
            a = page.evaluate("([u, v]) => window.__editor.screenOfGhostUV(u, v)", [gx, gy])
            page.mouse.click(*a)
            b = page.evaluate("([u, v]) => window.__editor.screenOfSheetUV(u, v)", [sx, sy])
            page.mouse.click(*b)
        page.wait_for_function("() => window.__editor.lastAnswer() && window.__editor.lastAnswer().decision.registration",
                               timeout=10000)
        check(page.evaluate('window.__editor.lastAnswer().decision.registration.scale') > 0, 'a registration was sent')


def scenario_timeline_previews_and_returns_without_rewriting_history():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        n = len(_api(page, 'GET', 'state')['body']['rounds'])
        page.evaluate("(i) => window.__editor.scrubTo(i)", 1)
        page.wait_for_selector('#time-chip', state='visible', timeout=10000)
        check(len(_api(page, 'GET', 'state')['body']['rounds']) == n, 'preview only')
        page.click('#time-return')
        page.wait_for_function("(n) => window.__editor.roundCount() === n + 1", arg=n, timeout=10000)
        rounds = _api(page, 'GET', 'state')['body']['rounds']
        check(rounds[-1]['kind'] == 'revert', rounds[-1])
        page.click('#time-now')
        check(not page.locator('#time-chip').is_visible(), 'back to now')


# ---- Task 18: finishing, the art director, start over, spend reset, advanced plan editor ----

def scenario_director_runs_from_the_editor():
    s = _serve()
    if s is None:
        return
    calls = []

    def critique(route):
        calls.append(1)
        n = len(calls)
        plan = _api_plan_cache['plan']
        route.fulfill(status=200, headers={'Content-Type': 'application/json'}, body=json.dumps({
            'round': 900 + n, 'critique': f'Round {n}: layer the rear bed.', 'done': n >= 2,
            'plan': plan, 'cost': 0.01 * n, 'total': 7.5 + 0.01 * n}))
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        _api_plan_cache['plan'] = _plan(page)
        page.route('**/api/house/twin/critique', critique)
        page.click('#editor-menu')
        page.click('#menu-director')
        page.wait_for_function("() => document.querySelector('#editor-agent').innerText.includes('Round 2')",
                               timeout=60000)
        check(len(calls) == 2, calls)


_api_plan_cache = {}


def scenario_advanced_plan_editor_round_trips():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.click('#editor-menu')
        page.click('#menu-advanced')
        page.wait_for_selector('#advanced-plan', state='visible', timeout=10000)
        plan = json.loads(page.input_value('#advanced-plan'))
        plan.setdefault('materials', {}).setdefault('roof', {'id': 'standing_seam', 'color': '#2f2622'})
        plan['materials']['roof']['color'] = '#123456'
        page.fill('#advanced-plan', json.dumps(plan))
        page.fill('#advanced-reason', 'roof is darker')
        page.click('#advanced-save')
        page.wait_for_function(
            "() => window.__editor.lastSummary() && window.__editor.lastSummary().toLowerCase().includes('saved')",
            timeout=10000)
        rounds = _api(page, 'GET', 'state')['body']['rounds']
        check(rounds[-1]['kind'] == 'hand', rounds[-1])
        check(_plan(page)['materials']['roof']['color'] == '#123456', 'saved')


def scenario_reset_spend_needs_the_word_reset():
    s = _serve()
    if s is None:
        return
    from services import twin_cost
    twin_cost.record('step:outline', [{'model': next(iter(twin_cost.PRICES)), 'input_tokens': 1000,
                                       'output_tokens': 100, 'images': 0, 'prompt_chars': 1,
                                       'max_output_tokens': 1024}])
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.click('#editor-menu')
        page.click('#menu-reset-spend')
        box = page.locator('input').last
        box.fill('reset')
        page.get_by_role('button', name='Reset', exact=True).click()
        page.wait_for_function("() => document.querySelector('#editor-top').innerText.includes('$0.00')", timeout=10000)
    check(twin_cost.total() == 0, twin_cost.total())


def scenario_start_over_clears_the_house_and_keeps_the_spend():
    s = _serve()
    if s is None:
        return
    from services import twin_build, twin_cost, twin_store
    twin_cost.record('step:outline', [{'model': next(iter(twin_cost.PRICES)), 'input_tokens': 1000,
                                       'output_tokens': 100, 'images': 0, 'prompt_chars': 1,
                                       'max_output_tokens': 1024}])
    spent = twin_cost.total()
    for bid in list(getattr(twin_build, '_BUILDS', {}) or {}):
        try:
            twin_build.stop(bid)
        except Exception:
            pass
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.click('#editor-menu')
        page.click('#menu-start-over')
        page.get_by_role('button', name='Start over', exact=True).click()
        page.wait_for_function('() => window.__editor.ready && window.__editor.isEmpty()', timeout=20000)
    check(twin_store.current() is None and abs(twin_cost.total() - spent) < 1e-9, 'cleared, spend kept')


# ---- Task 13 review: money paths, sign-out notice, camera ----

def scenario_say_is_never_resent_after_a_checkpoint():
    s = _serve()
    if s is None:
        return
    calls = []

    def say(route):
        calls.append(1)
        route.fulfill(status=409, headers={'Content-Type': 'application/json'}, body=json.dumps({'detail': {
            'checkpoint': 10.0, 'total': 10.2, 'changed': True, 'summary': ['Moved the upper floor 1\'-0" toward the street'],
            'cost': 0.04}}))

    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.route('**/api/house/editor/say', say)
        page.route('**/api/house/twin/cost/ack', lambda r: r.fulfill(status=200, body='{}',
                                                                     headers={'Content-Type': 'application/json'}))
        page.fill('#editor-message', 'shift the upper floor a foot toward the street')
        page.keyboard.press('Enter')
        page.wait_for_function("() => document.body.innerText.includes('Spent $10.20 so far')", timeout=10000)
        page.get_by_role('button', name='Continue', exact=True).click()
        page.wait_for_function(
            "() => document.querySelector('#editor-agent').innerText.includes('Moved the upper floor')", timeout=10000)
        page.wait_for_timeout(1500)
        check(len(calls) == 1, f'the turn was sent {len(calls)} times; edits must never apply twice')


def scenario_stop_at_a_checkpoint_stops_the_build():
    s = _serve()
    if s is None:
        return
    stops = []
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)

        def status(route):
            if route.request.method == 'POST' and route.request.url.endswith('/stop'):
                stops.append(1)
                return route.fulfill(status=200, body='{}', headers={'Content-Type': 'application/json'})
            if route.request.method == 'GET':
                return route.fulfill(status=200, headers={'Content-Type': 'application/json'}, body=json.dumps({
                    'id': 'b-test', 'state': 'checkpoint', 'steps': [], 'events': [], 'seq': 0, 'pause': None,
                    'cost': 10.1, 'checkpoint': 10.0, 'total': 10.1}))
            return route.continue_()
        page.route('**/api/house/editor/build/**', status)
        page.evaluate("() => window.__editor.followBuild('b-test')")
        page.wait_for_function("() => document.body.innerText.includes('so far')", timeout=10000)
        page.get_by_role('button', name='Stop', exact=True).click()
        page.wait_for_timeout(1500)
        check(stops == [1], 'Stop asks the server to stop the build')
        check(page.evaluate('window.__editor.currentInterval()') == 60000, 'and polling drops to the idle cadence')


def scenario_the_sign_out_notice_shows_once():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        page.route('**/api/house/editor/**', lambda route: route.fulfill(
            status=401, body='401: Unauthorized', headers={'Content-Type': 'text/plain'}))
        page.evaluate('window.__editor.pollNow()')
        page.wait_for_function(
            "() => document.body.innerText.includes('Home Assistant signed this tab out')", timeout=10000)
        page.evaluate('window.__editor.pollNow()')
        page.wait_for_timeout(1500)
        check(page.evaluate('window.__editor.signOutNotices()') == 1, 'shown once, not every poll')
        check(page.evaluate('window.__editor.polling()') is False, 'polling stops until the tab comes back')
        check('Home Assistant' in page.inner_text('#editor-top'), 'the status says what happened')


def scenario_rebuilds_keep_the_parents_view():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        page.evaluate("() => window.__twin.setCameraState({position: [30, 25, 30], target: [5, 0, -5]})")
        before = page.evaluate('window.__twin.cameraState()')
        page.evaluate("async () => window.__twin.rebuild(structuredClone(window.__twin.plan))")
        after = page.evaluate('window.__twin.cameraState()')
        check(all(abs(a - b) < 1e-3 for a, b in zip(before['position'] + before['target'],
                                                    after['position'] + after['target'])), (before, after))


if __name__ == '__main__':
    for fn in (scenario_signed_out_sees_the_sign_in,
               scenario_shell_matches_the_mockup_regions,
               scenario_checkpoint_asks_to_continue,
               scenario_build_streams_ghosts_and_log_lines,
               scenario_signed_out_message,
               scenario_idle_poll_is_one_minute_and_building_poll_one_second,
               scenario_no_banned_words,
               scenario_say_is_never_resent_after_a_checkpoint,
               scenario_stop_at_a_checkpoint_stops_the_build,
               scenario_the_sign_out_notice_shows_once,
               scenario_rebuilds_keep_the_parents_view,
               scenario_card_edit_round_trip,
               scenario_drag_moves_on_the_floor_only,
               scenario_rotate_snaps_to_quarter_turns,
               scenario_cameras_floors_and_sheet,
               scenario_plan_view_is_flat_and_adds_walls_and_windows,
               scenario_pause_card_shows_its_reason_cost_and_pins,
               scenario_timeline_previews_and_returns_without_rewriting_history,
               scenario_director_runs_from_the_editor,
               scenario_advanced_plan_editor_round_trips,
               scenario_reset_spend_needs_the_word_reset,
               scenario_start_over_clears_the_house_and_keeps_the_spend,
               scenario_empty_state_uploads_and_suggests_roles):
        fn()
        print('  ok ', fn.__name__)
