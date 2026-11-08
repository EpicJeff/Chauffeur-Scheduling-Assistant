"""The house editor in real Chromium (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md sections 6, 7, 9; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 13, plus the
Task 10 review carry: a signed-out person must see the sign-in, not a blank
page). Auth enforcement is ON; a parent session is placed in localStorage the
way admin_gate stores it. The model is a fake reader patched in-process at
services.twin_reads.read, so a Build streams ghosts with no spend.

Slice 1b-i Task 8 retired the upload card, its Build dropdown and the per-page
building selector: the scenarios that used them drive Your place (#place-view,
the DOM contract in that task's brief) and keep what the person sees.

The whole-building draft (spec docs/superpowers/specs/2026-11-08-house-editor-
whole-building-draft-design.md sections 1, 5 and 6; plan Tasks 8 and 11): a
Build from Your place reads a drawn building in one `draft` step. A quick
outline read on a side thread draws the first ghost, a log line names the read
and its elapsed time at least every 15 s, and the whole building then settles
at once. The fake reader answers `draft` with the recorded main-house spike
answer (its L2 marked as a half storey, page anchors added) and can hold that
read open or fail its first floor once. The crop chain's own pauses
(scale_outline, level_registration) are still reachable through the legacy
build body {building, photos}, which the scenarios after the draft ones drive
over the API.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_live.py
"""
import copy
import json
import re
import os
import sys
import tempfile
import threading
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
SPIKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude',
                     'draft-main-spike-answer.json')
FIRST_LOOK = 'First look at the outline while the drawings are read.'
FAILED_WHY = 'The drawings could not be read as one building.'
HEARTBEAT_JS = r"/Reading the Main house drawings as one set, \d+:\d\d so far\./"
MASTER = (5100, 3300)          # the 17 x 11 inch blank sheets of test_twin_build at 300 dpi
PAGE_LEVELS = {'Main floor': 'L1', 'Upper floor': 'L2'}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _spike_answer():
    with open(SPIKE, encoding='utf-8') as f:
        answer = json.load(f)
    # Task 11: a storey-and-a-half upper floor is still a level with its own floor button.
    next(level for level in answer['building']['levels'] if level['id'] == 'L2')['half'] = True
    return answer


def _anchor_uv(point):
    """One similarity per sheet: 70 ft across half the page width, y up the sheet."""
    ft_per_px = 70 / (0.5 * MASTER[0])
    px = 0.25 * MASTER[0] + point[0] / ft_per_px
    py = 0.8 * MASTER[1] - (point[1] + 1) / ft_per_px
    return [px / MASTER[0], py / MASTER[1]]


class LiveReader(engine_tests.Reader):
    """test_twin_build's fake reader plus the whole-building draft kinds.

    - 'draft' answers the recorded main-house spike answer with L2 a half
      storey and a pages[] entry per floor page carrying four outline-corner
      anchors. While `draft_gate` is set to an Event the read stays open until
      the scenario releases it (the quick outline ghost and the heartbeat
      happen meanwhile). `fail_first_floor` answers the spike without its
      first-floor walls that many times, so the build pauses.
    - 'draft_rooms' answers nothing new; 'outline' and the crop kinds are the
      engine fake's (a 70' x 65'-4" first floor).
    - Keyword options the real twin_reads.read takes (checkpoint_checked) are
      accepted and ignored.
    """

    def __init__(self):
        super().__init__()
        self.draft_gate = None
        self.fail_first_floor = 0
        self.failing_build = False

    def _draft(self, context):
        answer = _spike_answer()
        self.failing_build = bool(self.fail_first_floor)
        if self.fail_first_floor:
            self.fail_first_floor -= 1
            building = answer['building']
            building['walls'] = [w for w in building['walls'] if w['level'] != 'L1']
            kept = {w['id'] for w in building['walls']}
            building['openings'] = [o for o in building['openings'] if 'wall' not in o or o['wall'] in kept]
            return answer
        outlines = {level['id']: level['outline'] for level in answer['building']['levels']}
        floors = [p for p in context.get('pages') or [] if p.get('role') == 'floor']
        pages = []
        for index, entry in enumerate(floors):
            level = PAGE_LEVELS.get(entry.get('level_name')) or f'L{index + 1}'
            outline = outlines.get(level)
            if not outline:
                continue
            corners = [outline[k * len(outline) // 4] for k in range(4)]
            pages.append({'image': entry['image'], 'level': level,
                          'anchors': [{'px': _anchor_uv(p), 'at': list(p)} for p in corners]})
        answer['pages'] = pages
        return answer

    def __call__(self, kind, images, context, *, run, step, **_options):
        if kind == 'draft':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            gate = self.draft_gate
            if gate is not None:
                gate.wait(90)
            return self._draft(context)
        if kind == 'draft_level' and self.failing_build and (context or {}).get('level') == 'L1':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return {}
        if kind == 'draft_rooms':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return {'rooms': [], 'walls': []}
        return super().__call__(kind, images, context, run=run, step=step)


def _seed():
    from services import storage, twin_library, twin_reads
    twin_library._urlopen = p0view._stub_urlopen
    storage.patch_settings({'auth_enforce': True})
    storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent', 'email': 'pat@example.com'})
    storage.set_member_password('p1', 'correct horse battery staple')
    STATE['token'] = storage.create_member_token('p1')
    engine_tests._fresh()
    _, _, photo = engine_tests._sources()
    STATE['photo'] = photo
    STATE['reader'] = LiveReader()
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


def _open_place(page):
    if not page.locator('#place-view').is_visible():
        page.click('#editor-menu')
        page.click('#editor-manage-sources')
    page.wait_for_selector('#place-view', state='visible', timeout=10000)


def _paid_confirm(page, timeout=3000):
    """Accept the promptConfirm a paid action may show first; a spending checkpoint is left alone."""
    try:
        page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=timeout)
    except Exception:
        return None
    title = page.inner_text('#cc-confirm-title')
    if title.startswith('Spent $'):
        return None
    page.click('#cc-confirm-execute-btn')
    page.wait_for_selector('#cc-confirm-modal', state='hidden', timeout=5000)
    return title


def _wait_source(page, filename, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        sources = _api(page, 'GET', 'sheets')['body']['sources']
        found = next((s for s in sources if s['filename'] == filename), None)
        if found:
            return found
        page.wait_for_timeout(300)
    raise AssertionError(f'{filename} was never uploaded')


def _unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


def _wait_build(page, predicate_js, timeout=30000):
    """Wait until the editor's followed build satisfies predicate_js(b); return it."""
    page.wait_for_function(f"() => {{ const b = window.__editor.build(); return !!(b && ({predicate_js})); }}",
                           timeout=timeout)
    return page.evaluate('window.__editor.build()')


def _first_look_events(page, build_id):
    events = _api(page, 'GET', f'build/{build_id}')['body'].get('events') or []
    return [e for e in events if e.get('type') == 'ghost' and e.get('why') == FIRST_LOOK]


def _house_of(plan, bid='house'):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _drawn_walls_check(page, level='L1', step='draft'):
    house = _house_of(_plan(page))
    walls = [w for w in house['walls'] if w['level'] == level and w.get('state') != 'ghost'
             and (step is None or (w.get('src') or {}).get('step') == step)]
    drawn = page.evaluate("() => window.__twin.pieceIds('house')")
    check(walls and all(w['id'] in drawn for w in walls),
          (f'every settled {level} wall is drawn', len(walls), [w['id'] for w in walls if w['id'] not in drawn][:10]))
    return house


def _plain_log_check(page):
    """Ghost reasons are summarised once per reason, in words, never piece ids."""
    text = page.inner_text('#editor-agent')
    rows = [line for line in text.splitlines() if 'checking:' in line]
    check(len(rows) == len(set(rows)), ('repeated reasons are summarised, not one line per piece', rows))
    check('draft-outline' not in text and 'draft_rooms' not in text, ('plain words, no ids', text[-600:]))
    return text


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
    # The whole-building draft (spec sections 1 and 6; plan Tasks 8 and 11).
    # The draft read is held open so the quick outline ghost and the
    # heartbeat can be seen before the whole building settles at once.
    s = _serve()
    if s is None:
        return
    reader = STATE['reader']
    gate = threading.Event()
    reader.draft_gate = gate
    try:
        with s.browser(launch_args=GPU_ARGS) as page:
            page.set_viewport_size({'width': 1600, 'height': 900})
            _signed_in(page)
            _open(page, s)
            _open_place(page)
            start = time.time()
            page.click('[data-place-build="house"]')
            _paid_confirm(page)
            st = _wait_build(page, "b.state === 'running'", timeout=20000)
            step = next((x for x in st['steps'] if x['status'] == 'running'), None)
            check(step and step['id'] == 'draft' and step['label'] == 'Reading the drawings',
                  ('a drawn building is read as one set', st['steps']))
            check([x['id'] for x in st['steps']][:2] == ['draft', 'draft_rooms'],
                  ('the crop chain is gone for a drawn building', [x['id'] for x in st['steps']]))
            # The engine half of the first ghost: the side outline read lands
            # while the draft is still open.
            deadline = start + 30
            while time.time() < deadline and not _first_look_events(page, st['id']):
                page.wait_for_timeout(300)
            check(_first_look_events(page, st['id']),
                  'the quick outline read sends its first-look ghost while the drawings are read')
            # The person's half: the editor draws it, within 30 s of Build.
            try:
                page.wait_for_function('window.__editor.ghostCount() > 0',
                                       timeout=max(1000, int((deadline - time.time()) * 1000)))
            except Exception:
                raise AssertionError('the first-look ghost reached the build events but the editor drew nothing '
                                     '(previewPlan draws only ghost events that carry an outline)')
            check(not page.locator('#place-view').is_visible(), 'Your place closes and the editor follows the build')
            check(time.time() - start < 30, 'first ghost within 30 s')
            check(page.locator('[data-place-build="house"]').is_disabled() and page.locator('#place-build').is_disabled(),
                  'Build is off while a build is running')
            page.wait_for_function(
                "(why) => document.querySelector('#editor-agent').innerText.includes(why.replace(/\\.$/, ''))",
                arg=FIRST_LOOK, timeout=10000)
            log = page.inner_text('#editor-log')
            check('need checking' not in log, ('the first look is not an unresolved piece', log))
            check(log.count(FIRST_LOOK) == 1, ('one plain first-look line', log))
            # Log lines stream while the one long read runs: one at least every 15 s.
            page.wait_for_function(f"() => {HEARTBEAT_JS}.test(document.querySelector('#editor-agent').innerText)",
                                   timeout=25000)
            check(time.time() - start < 32, ('the first heartbeat comes about 15 s into the read', time.time() - start))
            check(page.evaluate('window.__editor.build().state') == 'running', 'still reading')
            gate.set()
            st = _wait_build(page, "b.state === 'done'", timeout=30000)
            page.wait_for_timeout(1500)
            house = _drawn_walls_check(page, 'L1')
            check(FIRST_LOOK not in json.dumps(_plan(page)), 'a first look never settles into the plan')
            check(FIRST_LOOK not in page.inner_text('#editor-log'), 'the first-look line clears when the draft settles')
            check({'L1', 'L2'} <= {level['id'] for level in house['levels']}, ('the whole building at once', house['levels']))
            check(any(w['level'] == 'L2' for w in house['walls']), 'the upper floor settles with the first')
            _plain_log_check(page)
            page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_building.png'))
    finally:
        gate.set()
        reader.draft_gate = None
    check(not _unexpected(s.errors()), s.errors())


def scenario_a_half_storey_has_its_floor_button_and_every_floor_lines_up():
    # Plan Task 11: the floor buttons show the half level the draft read.
    # Plan Task 8: page anchors register each drawn floor's sheet, so the
    # Sheet tool shows a drawing under the upper floor too.
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        upper = next(level for level in _house_of(_plan(page))['levels'] if level['id'] == 'L2')
        check(upper.get('half') is True, ('the upper floor stays a half storey', upper))
        page.wait_for_selector('#editor-floors [data-floor="house:L2"]', state='visible', timeout=20000)
        label = page.inner_text('#editor-floors [data-floor="house:L2"]').strip()
        check(label == upper['name'] and label, ('the half storey has a floor button with its name', label, upper['name']))
        page.click('#editor-floors [data-floor="house:L2"]')
        vis = page.evaluate('window.__twin.levelVisibility()')
        check(vis.get('house:L2') and not vis.get('house:L1', False), ('the half storey shows on its own', vis))
        regs = _api(page, 'GET', 'sheets')['body'].get('registrations') or []
        check(any(r['level'] == 'L2' for r in regs), ('the upper floor sheet is lined up from its anchors', regs))
        page.click('#rail-sheet')
        page.wait_for_function('() => window.__twin.sheetInfo() && window.__twin.sheetInfo().ready', timeout=20000)
        check('not have a lined-up drawing' not in page.inner_text('#editor-agent'), 'no "not lined up" note for L2')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_half_storey.png'))
    check(not _unexpected(s.errors()), s.errors())


def scenario_a_draft_that_cannot_be_read_pauses_in_plain_words():
    # The draft flow's only pause (spec section 5): the whole first floor
    # fails, the card says so in one sentence, offers Try again instead of
    # Looks right, and a paused build can be stopped.
    s = _serve()
    if s is None:
        return
    reader = STATE['reader']
    reader.fail_first_floor = 1
    try:
        with s.browser(launch_args=GPU_ARGS) as page:
            page.set_viewport_size({'width': 1600, 'height': 900})
            _signed_in(page)
            _open(page, s)
            _open_place(page)
            page.click('[data-place-build="house"]')
            _paid_confirm(page)
            st = _wait_build(page, "b.state === 'paused' && b.pause && b.pause.kind === 'draft'", timeout=30000)
            check(st['pause']['step'] == 'draft' and st['pause']['why'] == FAILED_WHY, st['pause'])
            page.wait_for_selector('#pause-card', state='visible', timeout=10000)
            check(not page.locator('#place-view').is_visible(), 'Your place yields to the question')
            reason = page.inner_text('#pause-card .pause-why').strip()
            check(reason.startswith(FAILED_WHY) and reason.endswith('.'),
                  ('the card says what went wrong in a sentence', reason))
            check('unsure' not in reason.lower() and reason == FAILED_WHY, ('no confidence sentence on a failed read', reason))
            card = page.inner_text('#pause-card')
            check(not any(w in card.lower() for w in BANNED) and not re.search(r"draft_rooms|outline:L\d|\bL\d\b", card),
                  ('plain words, no step ids', card))
            for sel in ('#pause-accept', '#pause-pin', '#pause-drag'):
                check(not page.locator(sel).is_visible(), (sel, 'nothing to line up when the drawings were not read'))
            check(page.inner_text('#pause-reread').strip() == 'Try again', page.inner_text('#pause-reread'))
            check(page.locator('#editor-stop').is_visible(), 'a paused build can be stopped')
            check(page.locator('[data-place-build="house"]').is_disabled() and page.locator('#place-build').is_disabled(),
                  'Build is off while a build is paused')
            page.click('#pause-reread')
            _paid_confirm(page)
            _wait_build(page, "b.state === 'done'", timeout=30000)
            page.wait_for_timeout(1500)
            _drawn_walls_check(page, 'L1')
            page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_draft_pause.png'))
    finally:
        reader.fail_first_floor = 0
    check(not _unexpected(s.errors()), s.errors())


def scenario_the_legacy_body_still_pauses_at_the_scale_outline():
    # The crop chain's first pause moved here from the Build scenario: a
    # drawn building no longer reads an outline first, but the legacy build
    # body {building, photos} still runs the crop steps (spec section 1, "My
    # call"). This leaves that build paused at registration:L2 with the main
    # floor settled, which the pause scenarios below rely on. The crop chain
    # starts from a house with nothing drawn, as it did when it was the Build
    # path: the draft's walls left in place would sit under the crop walls,
    # and the drag scenarios below would grab whichever one is on top. (A
    # plan needs one building, so the house keeps only its first floor.)
    s = _serve()
    if s is None:
        return
    _stop_builds()
    from services import twin_plan, twin_store
    plan = copy.deepcopy(twin_store.current())
    house = _house_of(plan)
    house.update(levels=[level for level in house['levels'] if level['id'] == 'L1'],
                 walls=[], openings=[], rooms=[], stairs=[], porch=None, roof={'sections': []})
    twin_store.push_round(twin_plan.normalize(plan)[0], 'edit')
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        r = _api(page, 'POST', 'build', engine_tests._inputs(STATE['photo']))
        check(r['status'] == 200, r)
        page.evaluate('(id) => window.__editor.followBuild(id)', r['body']['id'])
        st = _wait_build(page, "b.state === 'paused'", timeout=30000)
        check(st['pause']['kind'] == 'scale_outline' and st['pause']['step'] == 'outline:L1', st['pause'])
        page.wait_for_selector('#pause-card', state='visible', timeout=10000)
        check(not page.locator('#pause-pin').is_visible(), 'no Pin 2 points at the first outline')
        card = page.inner_text('#pause-card')
        check("70'-0\"" in card and "65'-4\"" in card, ('the card shows what was read', card))
        check(page.locator('#editor-stop').is_visible(), 'a paused build can be stopped')
        r = _api(page, 'POST', f"build/{st['id']}/answer", {'step': 'outline:L1', 'decision': {'accept': True}})
        check(r['status'] == 200, r)
        page.wait_for_function(
            """() => document.querySelector('#editor-agent').innerText.includes("Main floor outline: 70'-0\\" by 65'-4\\"")""",
            timeout=20000)
        page.wait_for_function(
            "() => document.querySelector('#editor-agent').innerText.toLowerCase().includes('stamp')", timeout=20000)
        check(page.locator('[data-place-build="house"]').is_disabled() and page.locator('#place-build').is_disabled(),
              'Build is off while a build is paused')
        page.wait_for_timeout(1500)
        plan = _api(page, 'GET', 'state')['body']['plan']
        walls = [w for w in _house_of(plan)['walls'] if w['level'] == 'L1' and w.get('state') != 'ghost']
        drawn = page.evaluate("() => window.__twin.pieceIds('house')")
        check(walls and all(w['id'] in drawn for w in walls), ('every main-floor wall is drawn', len(walls), drawn[:10]))
        lines = page.inner_text('#editor-agent').splitlines()
        check(sum('more than 2 ft' in line for line in lines) <= 2, 'repeated reasons are summarised, not one line per piece')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_legacy_pause.png'))
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
        _open_place(page)
        page.click('[data-place-build="house"]')
        _paid_confirm(page)
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
        page.wait_for_selector('#place-view', state='visible', timeout=10000)
        check(page.locator('#place-view').is_visible(), 'Your place shows on an empty house')
        check(page.locator('#place-build').is_disabled(), 'Build waits for confirmed pages')
        page.fill('#place-add-name', 'Main house')
        page.select_option('#place-add-kind', label='Main house')
        page.click('#place-add')
        page.wait_for_selector('[data-place-upload="main-house"]', state='attached', timeout=10000)
        pdf = engine_tests._pdf(3)
        page.set_input_files('[data-place-upload="main-house"]', files=[
            {'name': 'lot58.pdf', 'mimeType': 'application/pdf', 'buffer': pdf}])
        page.wait_for_function(
            "() => document.querySelectorAll('[data-place-page] select[data-place-role]').length >= 3", timeout=30000)
        src = _wait_source(page, 'lot58.pdf')['id']
        page.click(f'[data-place-suggest="{src}"]')
        _paid_confirm(page)
        page.wait_for_function(
            "() => [...document.querySelectorAll('select[data-place-role]')].some(s => s.value === 'roof')", timeout=20000)
        page.click('#place-confirm-pages')
        page.wait_for_function("() => !document.querySelector('[data-place-build=\"main-house\"]').disabled"
                               " && !document.querySelector('#place-build').disabled", timeout=10000)
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_empty.png'))
    check(not _unexpected(s.errors()), s.errors())


# ---- Tasks 14-17: scene tools, plan view, pauses, timeline -----------------
# These run after scenario_the_legacy_body_still_pauses_at_the_scale_outline,
# which leaves a legacy-body build paused at registration:L2 with the main
# floor settled (a drawn building's draft build never pauses there).

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
        page.locator('#editor-floors').get_by_role('button', name='Main floor', exact=True).click()
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
        reason = page.inner_text('#pause-card .pause-why')
        check(reason[:1].isupper() and reason.rstrip().endswith('.'), ('a sentence', reason))
        check(not page.locator('#editor-check-step').is_visible(), 'one way to check the step, not two')
        sheet = page.evaluate('window.__twin.sheetInfo()')
        reg = page.evaluate('window.__editor.pause().registration')
        master = page.evaluate('window.__editor.sheetMaster()')
        check(abs(sheet['widthFt'] - master[0] * reg['scale']) < 0.5, ('underlay at the registered scale', sheet, master, reg))
        check('$' in page.inner_text('#pause-reread'), 'the re-read shows its cost')
        page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_editor_pause.png'))
        page.click('#pause-pin')
        check('floor below' in page.inner_text('#pause-card').lower(), 'level pins point at the floor below, not the moving sheet')
        for gx, gy, sx, sy in ((0.3, 0.2, 0.31, 0.2), (0.6, 0.7, 0.61, 0.7)):
            a = page.evaluate("([u, v]) => window.__editor.screenOfGhostUV(u, v)", [gx, gy])
            page.mouse.click(*a)
            b = page.evaluate("([u, v]) => window.__editor.screenOfSheetUV(u, v)", [sx, sy])
            page.mouse.click(*b)
        check(page.evaluate('window.__editor.lastAnswer()') in (None, {}) or
              not page.evaluate('window.__editor.lastAnswer() && window.__editor.lastAnswer().step === "registration:L2"'),
              'pins only preview until Looks right')
        landed = page.evaluate('window.__editor.pinCheck()')
        page.click('#pause-accept')
        page.wait_for_function("() => window.__editor.lastAnswer() && window.__editor.lastAnswer().decision.registration",
                               timeout=10000)
        check(page.evaluate('window.__editor.lastAnswer().decision.registration.scale') > 0, 'a registration was sent')
        check(landed and landed['error_ft'] < 0.05, ('the second pin lands where it was put', landed))


def _stop_builds():
    # Return here is disabled while any build is active (final review I9);
    # earlier scenarios can leave one paused in this shared server.
    from services import twin_build
    for bid in list(getattr(twin_build, '_BUILDS', {}) or {}):
        try:
            twin_build.stop(bid)
        except Exception:
            pass


def scenario_timeline_previews_and_returns_without_rewriting_history():
    s = _serve()
    if s is None:
        return
    _stop_builds()
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        n = len(_api(page, 'GET', 'state')['body']['rounds'])
        # Return to the step just before now. The scenarios after this one edit
        # a settled main-floor wall of the house it leaves current; an early
        # round (the whole-floor walls read, which the fake reader answers with
        # the crop's own edges) has only ghosts.
        page.evaluate("(i) => window.__editor.scrubTo(i)", n - 2)
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


def scenario_a_stopped_build_can_be_resumed():
    # Review finding: a build stopped at a checkpoint or by an add-on restart
    # must offer Resume (cached answers, no new reads), never a dead end.
    s = _serve()
    if s is None:
        return
    resumes = []
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)

        def build(route):
            req = route.request
            if req.method == 'POST' and req.url.endswith('/resume'):
                resumes.append(1)
                return route.fulfill(status=200, body='{}', headers={'Content-Type': 'application/json'})
            if req.method == 'GET':
                return route.fulfill(status=200, headers={'Content-Type': 'application/json'}, body=json.dumps({
                    'id': 'b-stopped', 'state': 'stopped', 'steps': [], 'events': [], 'seq': 0, 'pause': None,
                    'cost': 1.2}))
            return route.continue_()
        page.route('**/api/house/editor/build/**', build)
        page.evaluate("() => window.__editor.followBuild('b-stopped')")
        page.wait_for_selector('#editor-resume', state='visible', timeout=10000)
        page.click('#editor-resume')
        page.wait_for_timeout(1000)
        check(resumes == [1], 'Resume asks the server to continue the stopped build')


# ---- Tasks 14-17 review ----

def scenario_a_real_mouse_drag_moves_a_wall_without_turning_the_view():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.get_by_role('button', name='Top', exact=True).click()
        page.click('#rail-move')
        wall = _first(_plan(page), 'walls')
        x, y = page.evaluate("([p, b]) => window.__twin.screenOf(p, b)", [wall['id'], 'house'])
        camera = page.evaluate('window.__twin.cameraState()')
        page.mouse.move(x, y)
        page.mouse.down()
        for step in range(1, 9):
            page.mouse.move(x + step * 6, y)
        page.mouse.up()
        page.wait_for_function("() => (window.__editor.lastSummary() || '').startsWith('Moved')", timeout=10000)
        moved = _piece(_plan(page), wall['id'])
        check(moved['from'] != wall['from'], 'the wall moved')
        after = page.evaluate('window.__twin.cameraState()')
        check(all(abs(a - b) < 1e-3 for a, b in zip(camera['position'], after['position'])), 'the view did not orbit')
        summary = page.evaluate('window.__editor.lastSummary()')
        check(not re.search(r'wall[:-][0-9a-f]{4,}|wall-\d', summary), ('plain words, no ids', summary))


def scenario_turning_keeps_the_house_in_place():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        before = page.evaluate("() => window.__editor.buildingCentre('house')")
        page.evaluate("([b, deg]) => window.__editor.rotateBuilding(b, deg)", ['house', 90])
        page.wait_for_function("() => (window.__editor.lastSummary() || '').startsWith('Turned')", timeout=10000)
        after = page.evaluate("() => window.__editor.buildingCentre('house')")
        check(abs(before[0] - after[0]) < 1.0 and abs(before[1] - after[1]) < 1.0, ('turns about its middle', before, after))
        page.evaluate("([b, deg]) => window.__editor.rotateBuilding(b, deg)", ['house', 0])
        page.wait_for_function("() => (window.__editor.lastSummary() || '').startsWith('Turned')", timeout=10000)


def scenario_a_card_save_keeps_what_is_typed_elsewhere():
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
        page.locator('#piece-card').get_by_label('Thickness', exact=True).fill("0'-8\"")
        _card_set(page, 'Height', "10'-6\"")
        page.wait_for_function("() => (window.__editor.lastSummary() || '').startsWith('Set ')", timeout=10000)
        check(page.locator('#piece-card').get_by_label('Thickness', exact=True).input_value() == "0'-8\"",
              'half-typed text survives another field saving')


def scenario_pause_adjustments_wait_for_looks_right():
    # Drag at a pause only previews; nothing is answered (a paid step) until Looks right.
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        if not page.locator('#pause-card').is_visible():
            return       # the build moved past its pauses in an earlier scenario
        page.evaluate("() => window.__editor.clearLastAnswer()")
        page.click('#pause-drag')
        page.evaluate("() => window.__editor.dragPauseGhost(30, 0)")
        page.wait_for_timeout(800)
        check(page.evaluate('window.__editor.lastAnswer()') is None, 'a drag only previews')
        page.click('#pause-accept')
        page.wait_for_function('() => window.__editor.lastAnswer() !== null', timeout=10000)
        check(page.evaluate('window.__editor.lastAnswer().decision.registration || window.__editor.lastAnswer().decision.transform'),
              'Looks right sends the adjusted placement')


def scenario_return_here_leaves_preview():
    s = _serve()
    if s is None:
        return
    _stop_builds()
    with s.browser(launch_args=GPU_ARGS) as page:
        _signed_in(page)
        _open(page, s)
        n = page.evaluate('window.__editor.roundCount()')
        page.evaluate("(i) => window.__editor.scrubTo(i)", n - 1)
        check(page.locator('#time-return').is_disabled(), 'nothing to return to at the newest step')
        page.evaluate("(i) => window.__editor.scrubTo(i)", 1)
        page.click('#time-return')
        page.wait_for_function("(n) => window.__editor.roundCount() === n + 1", arg=n, timeout=10000)
        check(not page.locator('#time-chip').is_visible(), 'back to the present after returning')


# ---- Task 18 review: the art director's paid path and the refusals ----

def _director_route(calls, first_checkpoint):
    def critique(route):
        calls.append(json.loads(route.request.post_data or '{}'))
        if first_checkpoint and len(calls) == 1:
            return route.fulfill(status=409, headers={'Content-Type': 'application/json'},
                                 body=json.dumps({'detail': {'checkpoint': 10.0, 'total': 10.05}}))
        plan = _api_plan_cache['plan']
        route.fulfill(status=200, headers={'Content-Type': 'application/json'}, body=json.dumps({
            'round': 950 + len(calls), 'critique': f'Round {len(calls)}: fine now.', 'done': True,
            'plan': plan, 'cost': 0.01, 'total': 10.06}))
    return critique


def scenario_director_checkpoint_continue_retries_and_stop_spends_nothing_more():
    s = _serve()
    if s is None:
        return
    for choice in ('Continue', 'Stop'):
        calls, acks = [], []
        with s.browser(launch_args=GPU_ARGS) as page:
            page.set_viewport_size({'width': 1600, 'height': 900})
            _signed_in(page)
            _open(page, s)
            _api_plan_cache['plan'] = _plan(page)
            page.route('**/api/house/twin/critique', _director_route(calls, True))
            page.route('**/api/house/twin/cost/ack', lambda r: (acks.append(1), r.fulfill(
                status=200, body='{}', headers={'Content-Type': 'application/json'})))
            page.click('#editor-menu')
            page.click('#menu-director')
            page.wait_for_function("() => document.body.innerText.includes('Spent $10.05 so far')", timeout=20000)
            page.get_by_role('button', name=choice, exact=True).click()
            page.wait_for_timeout(2500)
        if choice == 'Continue':
            check(acks == [1] and len(calls) == 2 and calls[0].get('run') == calls[1].get('run'),
                  ('Continue acknowledges and retries the same run', acks, len(calls)))
        else:
            check(acks == [] and len(calls) == 1, ('Stop spends nothing more', acks, len(calls)))


def scenario_editor_refusals_are_plain_and_change_nothing():
    s = _serve()
    if s is None:
        return
    from services import twin_cost, twin_store
    twin_cost.record('step:outline', [{'model': next(iter(twin_cost.PRICES)), 'input_tokens': 1000,
                                       'output_tokens': 100, 'images': 0, 'prompt_chars': 1,
                                       'max_output_tokens': 1024}])
    spent = twin_cost.total()
    rounds = len(twin_store.rounds())
    current = twin_store.current_id()
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.click('#editor-menu')
        page.click('#menu-advanced')
        page.wait_for_selector('#advanced-plan', state='visible', timeout=10000)
        page.fill('#advanced-reason', '')
        page.click('#advanced-save')
        check(page.evaluate("() => document.querySelector('#advanced-reason').validity.valueMissing"),
              'a blank reason is refused by the form itself')
        page.fill('#advanced-reason', 'testing')
        page.fill('#advanced-plan', '{not json')
        page.click('#advanced-save')
        page.wait_for_function("() => document.body.innerText.includes('valid JSON')", timeout=10000)
        page.reload()
        page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=60000)
        page.click('#editor-menu')
        page.click('#menu-reset-spend')
        page.locator('input').last.fill('nope')
        page.get_by_role('button', name='Reset', exact=True).click()
        page.wait_for_timeout(1200)
        page.reload()
        page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=60000)
        page.click('#editor-menu')
        page.click('#menu-start-over')
        page.get_by_role('button', name='Keep it', exact=True).click()
        page.wait_for_timeout(1200)
    check(abs(twin_cost.total() - spent) < 1e-9, 'a wrong word resets nothing')
    check(len(twin_store.rounds()) == rounds and twin_store.current_id() == current, 'Keep it and refusals change nothing')


# ---- final whole-branch review ----

def scenario_the_known_width_can_be_typed_at_the_first_pause():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.route('**/api/house/editor/build/b-scale**', lambda route: route.fulfill(
            status=200, headers={'Content-Type': 'application/json'}, body=json.dumps({
                'id': 'b-scale', 'state': 'paused', 'steps': [{'id': 'outline:L1', 'status': 'paused', 'label': 'Main floor outline'}],
                'events': [], 'seq': 0, 'cost': 0.1,
                'pause': {'kind': 'scale_outline', 'step': 'outline:L1', 'why': 'Read 70 ft.', 'confidence': 0.8,
                          'dimension_ft': 70.0, 'size_ft': [70.0, 65.333],
                          'registration': {'scale': 0.02745, 'angle': 0, 'origin_px': [1020, 3000], 'offset': [0, 0]}}}))
            if route.request.method == 'GET' else route.fulfill(
                status=200, headers={'Content-Type': 'application/json'}, body='{"id": "b-scale", "state": "running"}'))
        page.evaluate("() => window.__editor.followBuild('b-scale')")
        page.wait_for_selector('#pause-dimension', state='visible', timeout=10000)
        page.fill('#pause-dimension', "71'-0\"")
        page.click('#pause-accept')
        page.wait_for_function('() => window.__editor.lastAnswer() !== null', timeout=10000)
        reg = page.evaluate('window.__editor.lastAnswer().decision.registration')
        check(abs(reg['scale'] - 0.02745 * 71 / 70) < 1e-6, ('the typed width rescales the drawing', reg))


def scenario_each_page_belongs_to_a_building_and_build_builds_that_one():
    s = _serve()
    if s is None:
        return
    posts = []
    from services import twin_build
    for bid in list(getattr(twin_build, '_BUILDS', {}) or {}):
        try:
            twin_build.stop(bid)
        except Exception:
            pass
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.route('**/api/house/editor/build', lambda route: (posts.append(json.loads(route.request.post_data)),
                                                               route.fulfill(status=200, body=json.dumps({'id': 'b-pool'}),
                                                                             headers={'Content-Type': 'application/json'})))
        page.click('#editor-menu')
        page.click('#menu-upload')
        page.wait_for_selector('#place-view', state='visible', timeout=10000)
        rows = page.locator('[data-place-page]')
        carded = page.locator('[data-place-building] [data-place-page], #place-lot [data-place-page]')
        check(rows.count() >= 1 and carded.count() == rows.count(), 'every page sits on the card of the part it shows')
        page.fill('#place-add-name', 'Pool house')
        page.select_option('#place-add-kind', label='Pool house')
        page.click('#place-add')
        page.wait_for_selector('[data-place-building="pool-house"]', state='visible', timeout=10000)
        page.locator('[data-place-building="main-house"] select[data-place-move]').first.select_option(label='Pool house')
        page.wait_for_selector('[data-place-building="pool-house"] [data-place-page]', state='visible', timeout=10000)
        page.wait_for_function("() => !document.querySelector('[data-place-build=\"pool-house\"]').disabled", timeout=10000)
        page.click('[data-place-build="pool-house"]')
        _paid_confirm(page)
        again = page.get_by_role('button', name='Build again', exact=True)
        if again.count():
            again.click()
        page.wait_for_timeout(1500)
    check(posts and posts[-1] == {'part': 'pool-house'}, posts)


# ---- repair after the first live build (repair-brief.md R6, R7) ----
# These run last: R6 puts a two-building plan in place.

def _two_buildings():
    from services import twin_plan, twin_store

    def level(lid, name, elevation, w, d):
        return {'id': lid, 'name': name, 'elevation': elevation, 'ceiling': 9,
                'outline': [[0, 0], [w, 0], [w, d], [0, d]]}

    def building(bid, name, kind, position, levels):
        return {'id': bid, 'name': name, 'kind': kind, 'position': position, 'rotation': 0, 'levels': levels,
                'walls': [], 'openings': [], 'rooms': [], 'roof': {'sections': []}}

    plan = {'units': 'ft', 'site': {}, 'materials': {}, 'buildings': [
        building('main-house', 'Main house', 'main_house', [0, 0],
                 [level('L1', 'Main floor', 0, 70, 65), level('L2', 'Second floor', 9, 58, 51)]),
        building('pool-house', 'Pool house', 'pool_house', [80, 0], [level('L1', 'Main floor', 0, 31, 22)])]}
    twin_store.push_round(twin_plan.normalize(plan)[0], 'edit')


def scenario_floor_buttons_name_their_building():
    s = _serve()
    if s is None:
        return
    _stop_builds()
    _two_buildings()
    with s.browser(launch_args=GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        _signed_in(page)
        _open(page, s)
        page.wait_for_function("() => document.querySelectorAll('#editor-floors [data-floor]').length === 3",
                               timeout=20000)
        labels = page.eval_on_selector_all('#editor-floors [data-floor]', 'nodes => nodes.map(n => n.textContent.trim())')
        check(sorted(labels) == ['Main house \u00b7 Main floor', 'Main house \u00b7 Second floor',
                                 'Pool house \u00b7 Main floor'],
              ('with two buildings each floor names its building', labels))
        page.locator('#editor-floors').get_by_role('button', name='Pool house \u00b7 Main floor', exact=True).click()
        vis = page.evaluate('window.__twin.levelVisibility()')
        check(vis.get('pool-house:L1') and not vis.get('main-house:L1', False), vis)
    check(not _unexpected(s.errors()), s.errors())


def scenario_download_build_record():
    s = _serve()
    if s is None:
        return
    dialogs = []
    with s.browser(launch_args=GPU_ARGS, accept_downloads=True) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
        _signed_in(page)
        _open(page, s)
        page.click('#editor-menu')
        item = page.locator('#editor-menu').get_by_role('button', name='Download build record', exact=True)
        check(item.is_visible() and item.is_enabled(), 'the menu offers the build record')
        with page.expect_download(timeout=20000) as info:
            item.click()
        download = info.value
        name = download.suggested_filename
        with open(download.path(), encoding='utf-8') as f:
            record = json.load(f)
    check(name.endswith('.json'), ('one JSON file', name))
    check({'plan', 'builds', 'place', 'registrations', 'ledger'} <= set(record), sorted(record))
    check([b['id'] for b in record['plan']['buildings']] == ['main-house', 'pool-house'], 'the current plan')
    check(not dialogs, ('no browser dialog', dialogs))
    check(not _unexpected(s.errors()), s.errors())


if __name__ == '__main__':
    for fn in (scenario_signed_out_sees_the_sign_in,
               scenario_shell_matches_the_mockup_regions,
               scenario_checkpoint_asks_to_continue,
               scenario_build_streams_ghosts_and_log_lines,
               scenario_a_half_storey_has_its_floor_button_and_every_floor_lines_up,
               scenario_a_draft_that_cannot_be_read_pauses_in_plain_words,
               scenario_the_legacy_body_still_pauses_at_the_scale_outline,
               scenario_signed_out_message,
               scenario_idle_poll_is_one_minute_and_building_poll_one_second,
               scenario_no_banned_words,
               scenario_say_is_never_resent_after_a_checkpoint,
               scenario_stop_at_a_checkpoint_stops_the_build,
               scenario_the_sign_out_notice_shows_once,
               scenario_rebuilds_keep_the_parents_view,
               scenario_a_stopped_build_can_be_resumed,
               scenario_card_edit_round_trip,
               scenario_drag_moves_on_the_floor_only,
               scenario_rotate_snaps_to_quarter_turns,
               scenario_cameras_floors_and_sheet,
               scenario_plan_view_is_flat_and_adds_walls_and_windows,
               scenario_pause_card_shows_its_reason_cost_and_pins,
               scenario_timeline_previews_and_returns_without_rewriting_history,
               scenario_a_real_mouse_drag_moves_a_wall_without_turning_the_view,
               scenario_turning_keeps_the_house_in_place,
               scenario_a_card_save_keeps_what_is_typed_elsewhere,
               scenario_pause_adjustments_wait_for_looks_right,
               scenario_return_here_leaves_preview,
               scenario_director_runs_from_the_editor,
               scenario_director_checkpoint_continue_retries_and_stop_spends_nothing_more,
               scenario_editor_refusals_are_plain_and_change_nothing,
               scenario_advanced_plan_editor_round_trips,
               scenario_reset_spend_needs_the_word_reset,
               scenario_start_over_clears_the_house_and_keeps_the_spend,
               scenario_the_known_width_can_be_typed_at_the_first_pause,
               scenario_empty_state_uploads_and_suggests_roles,
               scenario_each_page_belongs_to_a_building_and_build_builds_that_one,
               scenario_floor_buttons_name_their_building,
               scenario_download_build_record):
        fn()
        print('  ok ', fn.__name__)
