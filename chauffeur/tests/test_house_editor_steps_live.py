"""The front door, the step strip and checks one at a time, in real Chromium
(plan docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md, Tasks 7
and 8; briefs task-7-brief.md and task-8-brief.md in
.superpowers/sdd/2026-11-10-house-guided-build-piece-4/; ruling Q9: Tasks 7-8
keep their live scenarios here, Tasks 5-6 in test_house_editor_guided_live.py).

Task 7: with no buildings and no lot the canvas shows `Let's make your house`
with `Add plans and photos` (opens Your files) and `Draw it myself` (closes the
front door and arms Draw wall). A step strip, always visible, shows Your files,
Your lot, Build, Check it, Link to Home Assistant; Menu > Your place opens Your
files. The Your place dialog becomes the Your files and Your lot step panels:
nothing a person could do there is dropped (the never-drop rule), which
scenario_every_your_place_ability_is_still_reachable proves control by control.

Task 8: one queue of checks (a build pause, the model's flags, its proposals),
one at a time, with Looks right, Fix it and Skip for now; and the piece-4 exit
flow on the stub reader: start a build, Stop it mid-walls, move a wall by hand,
Continue, and the rest builds on the moved wall, which stays where the person
put it and stays theirs.

The DOM contract these scenarios assume (the node tests use the same):
  - each step of the strip carries data-step="<its words>" and
    data-state="done" | "now" | "not-yet"; it is a button or holds one, and
    pressing it opens that step whatever its state;
  - an open step's panel is an element carrying data-step-panel="<its words>";
  - the check shown is inside #check-card;
  - the Your place controls keep the ids and data attributes
    tests/test_house_place_live.py selects them by (the Task 7 brief keeps that
    file green, retargeting only the dialog itself), so the enumeration below
    names each control by them;
  - a hand move goes through window.__twinEditor.op (the editor's applyOp, the
    path a drag commits through), selection through window.__twinEditor.selection;
  - Stop is a visible button named Stop (or Stop build), Continue a visible
    button named Continue (or Resume, today's word).
Front door words, step words and check actions are found by their visible
words, verbatim.

No model is ever called: llm_budget.urlopen refuses (imported from
test_twin_build_stream), twin_reads.read refuses outside the stop scenario,
and the stop scenario replays the recorded pool house draft through that
file's StreamReader, patched in as twin_reads.read, twin_reads.read_stream and
twin_build._REAL_READER.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_steps_live.py
"""
import math
import os
import re
import socket
import sys
import tempfile
import time
import urllib.request

# Never the dev data: every service import below reads this temp dir.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_house_steps_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402
from live_app import live_app, goto_retry  # noqa: E402

# The streaming stub reader and reply positions. That module also shuts every
# socket; the served app needs loopback, so only the model's door stays shut.
_OPEN = (socket.create_connection, urllib.request.urlopen)
import test_twin_build_stream as S  # noqa: E402
socket.create_connection, urllib.request.urlopen = _OPEN
import test_twin_build as engine_tests  # noqa: E402

check = H.check
GPU_ARGS = H.GPU_ARGS
STEPS = ['Your files', 'Your lot', 'Build', 'Check it', 'Link to Home Assistant']
FRONT_DOOR = "Let's make your house"
SHOTS = tempfile.gettempdir()


def _no_reads(*args, **kwargs):
    return {'error': 'This test makes no model reads.'}


def _seed():
    from services import storage, twin_library, twin_reads
    check(os.path.abspath(storage.DB_PATH).startswith(os.path.abspath(tempfile.gettempdir())),
          ('the live app must use a temp data dir', storage.DB_PATH))
    twin_library._urlopen = H.p0view._stub_urlopen
    twin_reads.read = _no_reads
    storage.patch_settings({'auth_enforce': True})
    storage.add_member(dict(H.PARENT))
    storage.set_member_password(H.PARENT['id'], 'correct horse battery staple')
    H.STATE['token'] = storage.create_member_token(H.PARENT['id'])
    engine_tests._fresh()


def _serve():
    if 'served' not in H._SERVED:
        H._SERVED['served'] = live_app(_seed)
    return H._SERVED['served']


# --- what the house holds, set in this process before a page opens ----------

def _empty():
    """No buildings, no lot, no documents, no plan."""
    engine_tests._fresh()


def _household():
    """The household's real house (8 + 3 flags), as the model harness seeds it."""
    from services import twin_store as ts
    engine_tests._fresh()
    ts.push_round(H.household_plan(), 'build')


def _plot_reader(kind, images, context, *, run, step, **options):
    answer = engine_tests.fixture('plot')
    answer['buildings'].append({'name': 'shed', 'outline': [[0.45, 0.2], [0.5, 0.2], [0.5, 0.26], [0.45, 0.26]]})
    return answer


def _photo_reader(garage):
    def read(kind, images, context, *, run, step, **options):
        return {'photos': [{'index': 0, 'parts': ['lot', garage]}],
                'shells': [{'building': garage, 'storeys': 1, 'roof': 'gable', 'pitch': 6,
                            'confidence': 0.5, 'why': ''}]}
    return read


def _everything():
    """A place where every Your place control has something to show: the Main
    house with a confirmed floor page, a plot page on the lot, a second drawing
    with no roles yet, a photo of the lot, a garage without drawings (its shell),
    a plot read with open footprint suggestions, and photo suggestions."""
    from services import twin_place_reads, twin_store as ts
    engine_tests._fresh()
    two = ts.save_source('drawing', 'two.pdf', engine_tests._pdf(2), part='house')
    garage = ts.add_building('Detached garage', 'garage')['id']
    ts.set_page_roles([
        {'source': two, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': two, 'page': 2, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'}])
    loose = ts.save_source('drawing', 'loose.pdf', engine_tests._pdf(1), part='house')
    photo = ts.save_source('photo', 'yard.jpg', engine_tests._jpeg(), part='lot')
    lot = twin_place_reads.read_plot(reader=_plot_reader)
    check(any(s['state'] == 'open' for s in lot['read']['suggestions']), ('test setup: open plot suggestions', lot))
    twin_place_reads.suggest_photos(reader=_photo_reader(garage))
    return {'two': two, 'loose': loose, 'photo': photo, 'garage': garage}


# --- the page -------------------------------------------------------------------

def _open(page, s, query='tier=high&test=1'):
    page.set_viewport_size({'width': 1600, 'height': 900})
    H.signed_in(page)
    goto_retry(page, s.url(f'house/editor?{query}'))
    page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=90000)
    H.settle(page)


def _wait_house(page, timeout=60000):
    page.wait_for_function("() => window.__twin && window.__twin.plan && (window.__twin.plan.buildings || []).length > 0",
                           timeout=timeout)
    H.settle(page)


def _step(page, name):
    return page.locator(f'[data-step="{name}"]')


def _step_state(page, name):
    return _step(page, name).first.get_attribute('data-state')


def _press_step(page, name):
    step = _step(page, name)
    check(step.count() == 1, (f'one {name} step in the strip', step.count()))
    target = step if step.evaluate("n => n.matches('button')") else step.locator('button').first
    target.click()


def _open_step(page, name):
    _press_step(page, name)
    panel = page.locator(f'[data-step-panel="{name}"]')
    panel.wait_for(state='visible', timeout=10000)
    H.settle(page)
    return panel


def _expanded(page, name):
    step = _step(page, name).first
    return 'true' in (step.get_attribute('aria-expanded'),
                      step.evaluate("n => (n.matches('button') ? n : n.querySelector('button'))?.getAttribute('aria-expanded')"))


def _button(page, name, scope=None):
    """The one visible button with this name (str: exact words; pattern: regex)."""
    where = scope or page
    loc = where.get_by_role('button', name=name, exact=True) if isinstance(name, str) else where.get_by_role('button', name=name)
    shown = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible()]
    check(len(shown) == 1, (f'exactly one visible {name} button', len(shown)))
    return shown[0]


def _visible_count(page, name):
    loc = page.get_by_role('button', name=name, exact=True)
    return sum(loc.nth(i).is_visible() for i in range(loc.count()))


def _uncovered(page, locator):
    """The control is on top where it is drawn (nothing covers it)."""
    return locator.evaluate("""el => {
        const r = el.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !!hit && (hit === el || el.contains(hit));
    }""")


def _paid_confirm(page, timeout=5000):
    page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=timeout)
    text = page.inner_text('#cc-confirm-title') + '\n' + page.inner_text('#cc-confirm-message')
    page.click('#cc-confirm-execute-btn')
    page.wait_for_selector('#cc-confirm-modal', state='hidden', timeout=5000)
    return text


def _front_door_shown(page):
    loc = page.get_by_text(FRONT_DOOR, exact=True)
    return any(loc.nth(i).is_visible() for i in range(loc.count()))


def _strip_ok(page):
    names = page.locator('[data-step]').evaluate_all('ns => ns.map(n => n.dataset.step)')
    check(names == STEPS, ('the strip shows the five steps, in order, with these words', names))
    for name in STEPS:
        step = _step(page, name).first
        check(step.is_visible(), f'the {name} step is visible')
        check(name in step.inner_text(), (f'the {name} step shows its words', step.inner_text()))
        check(step.get_attribute('data-state') in ('done', 'now', 'not-yet'), (name, step.get_attribute('data-state')))


def _unexpected(errors):
    return H.unexpected(errors)


# --- Task 7: the front door and the step strip ----------------------------------

def scenario_empty_house_shows_the_front_door():
    s = _serve()
    if s is None:
        return
    _empty()
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.get_by_text(FRONT_DOOR, exact=True).first.wait_for(state='visible', timeout=10000)
        for words in ('Add plans and photos', 'Draw it myself'):
            button = _button(page, words)
            check(_uncovered(page, button), f'{words} is on top: the front door leads, nothing opens over it')
        _strip_ok(page)
        check(_step_state(page, 'Your files') == 'now', ('an empty house starts at Your files', _step_state(page, 'Your files')))
        for name in STEPS[1:]:
            check(_step_state(page, name) == 'not-yet', (f'{name} is not yet', _step_state(page, name)))
        page.screenshot(path=os.path.join(SHOTS, 'house_steps_front_door.png'))
    check(not _unexpected(s.errors()), s.errors())


def scenario_add_plans_opens_your_files():
    s = _serve()
    if s is None:
        return
    _empty()
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.get_by_text(FRONT_DOOR, exact=True).first.wait_for(state='visible', timeout=10000)
        _button(page, 'Add plans and photos').click()
        panel = page.locator('[data-step-panel="Your files"]')
        panel.wait_for(state='visible', timeout=10000)
        check(_expanded(page, 'Your files'), 'the strip marks Your files open')
        check(panel.locator('[data-place-upload="lot"]').count() == 1, 'Your files offers an upload for the lot')
        check(panel.locator('#place-add-name').is_visible(), 'Your files offers Add building')
        page.screenshot(path=os.path.join(SHOTS, 'house_steps_your_files.png'))
        # Menu > Your place and Menu > Upload more open Your files, from anywhere.
        for item in ('Your place', 'Upload more'):
            _open_step(page, 'Your lot')
            page.click('#editor-menu > summary')
            page.get_by_role('button', name=item, exact=True).click()
            panel.wait_for(state='visible', timeout=10000)
            check(_expanded(page, 'Your files') and not _expanded(page, 'Your lot'),
                  f'Menu > {item} opens Your files')
    check(not _unexpected(s.errors()), s.errors())


def scenario_draw_it_myself_arms_draw_wall():
    s = _serve()
    if s is None:
        return
    _empty()
    from services import twin_store as ts
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.get_by_text(FRONT_DOOR, exact=True).first.wait_for(state='visible', timeout=10000)
        _button(page, 'Draw it myself').click()
        page.wait_for_function("() => document.getElementById('rail-draw-wall').getAttribute('aria-pressed') === 'true'",
                               timeout=10000)
        check(not _front_door_shown(page), 'Draw it myself closes the front door')
        check(page.locator('#draw-tools').is_visible() and 'Click wall corners' in page.inner_text('#draw-note'),
              ('the Draw wall tool is armed and says how', page.inner_text('#draw-note')))
        # Armed means a person can draw: two clicks on the canvas make a wall.
        box = page.evaluate("() => { const r = window.__twin.renderer3.domElement.getBoundingClientRect();"
                            " return [r.left + r.width / 2, r.top + r.height / 2]; }")
        for sx in (box[0] - 160, box[0] + 160):
            H._on_canvas(page, sx, box[1])
            page.mouse.click(sx, box[1])
            H.settle(page)
        deadline = time.time() + 15
        walls = 0
        while time.time() < deadline and not walls:
            model = ts.current_model() or {}
            walls = sum(len(b.get('walls') or []) for b in model.get('buildings') or [])
            page.wait_for_timeout(250)
        check(walls >= 1, ('two clicks with Draw wall armed draw a wall', ts.current_model()))
        page.keyboard.press('Escape')
        page.screenshot(path=os.path.join(SHOTS, 'house_steps_draw_myself.png'))
    check(not _unexpected(s.errors()), s.errors())


# Every control of the Your place dialog (templates/house_editor.html #place-view
# and static/twin/editor/place.js), each with where it may now live. A control is
# reachable when it shows inside that step's panel (a control inside a closed
# <details> is reached by opening it; a file input by its visible label).
def _abilities(ids):
    garage, loose, two, photo = ids['garage'], ids['loose'], ids['two'], ids['photo']
    files, lot, build = ['Your files'], ['Your lot'], ['Build']
    either = ['Your files', 'Your lot']
    card = f'[data-place-building="{garage}"]'
    shell = f'[data-place-shell="{garage}"]'
    return [
        ('Building name (add a building)', '#place-add-name', files),
        ('Kind (add a building)', '#place-add-kind', files),
        ('Add building', '#place-add', files),
        ('Place on the lot (a building)', 'button:text-is("Place on the lot")', either),
        ('Name and kind: Name', lambda p: p.locator(card).get_by_label('Name', exact=True), files),
        # The building's own kind pick (the shell's selects carry a name: roof, door_side).
        ('Name and kind: Kind', f'{card} select:not([name])', files),
        ('Name and kind: Remove building', f'{card} button:text-is("Remove building")', files),
        ('Add drawings or photos (a building)', '[data-place-upload="house"]', files),
        ('Add drawings or photos (a building without drawings)', f'[data-place-upload="{garage}"]', files),
        ('Add drawings or photos (the lot)', '[data-place-upload="lot"]', either),
        ('This page shows (a building page)', f'[data-place-page="{two}:1"] select[data-place-role]', files),
        ('This page shows (a lot page)', f'[data-place-page="{two}:2"] select[data-place-role]', either),
        ('Level name', f'[data-place-page="{two}:1"] input[data-place-level]', files),
        ('Move to (a page)', f'[data-place-page="{two}:1"] select[data-place-move]', files),
        ('Suggest page roles', f'[data-place-suggest="{loose}"]', files),
        ('Move it (a page hint)', '[data-place-hint] button', files),
        ('This photo shows (part tags)', f'[data-place-photo="{photo}"] button[data-place-tag="lot"]', files),
        ('This photo shows (another part)', f'[data-place-photo="{photo}"] button[data-place-tag="{garage}"]', files),
        ('Shape without drawings: Storeys', f'{shell} [name="storeys"]', files),
        ('Shape without drawings: Wall height in feet', f'{shell} [name="wall_height"]', files),
        ('Shape without drawings: Roof pitch', f'{shell} [name="pitch"]', files),
        ('Shape without drawings: Roof', f'{shell} [name="roof"]', files),
        ('Shape without drawings: Door side', f'{shell} [name="door_side"]', files),
        ('Size: Width in feet', f'{shell} [data-place-size] [name="width"]', files),
        ('Size: Depth in feet', f'{shell} [data-place-size] [name="depth"]', files),
        ('Size: Set size', f'{shell} [data-place-size] button:text-is("Set size")', files),
        ('Draw on the lot', f'{shell} [data-place-draw]', either),
        ('Confirm pages', '#place-confirm-pages', files),
        ('Read the plot plan', '#place-read-plot', lot),
        ('Plot suggestion: Match to', '[data-place-suggestion] select[data-suggestion-match]', lot),
        ('Plot suggestion: Name', '[data-place-suggestion] input[data-suggestion-name]', lot),
        ('Plot suggestion: Kind', '[data-place-suggestion] select[data-suggestion-kind]', lot),
        ('Plot suggestion: Accept', '[data-place-suggestion] button[data-suggestion-accept]', lot),
        ('Plot suggestion: Dismiss', '[data-place-suggestion] button[data-suggestion-dismiss]', lot),
        ('Place in the scene', '#place-in-scene', lot),
        ('These are in the right place', '#place-confirm-placement', lot),
        ('Suggest from photos', '#place-suggest-photos', either),
        ('Photo suggestion: Add', '[data-photo-suggestion] button', either),
        ('Photo shell suggestion: Use these', f'[data-shell-suggestion="{garage}"] button', either),
        ('Build the lot', '[data-place-build="lot"]', build),
        ('Build this building (with drawings)', '[data-place-build="house"]', build),
        ('Build this building (without drawings)', f'[data-place-build="{garage}"]', build),
        ('Build your place', '#place-build', build),
    ]


def _reached(page, panel, find):
    loc = (find(panel) if callable(find) else panel.locator(find))
    if loc.count() == 0:
        return False
    first = loc.first
    first.evaluate("el => { const d = el.closest('details'); if (d && !d.open) d.querySelector(':scope > summary')?.click(); }")
    H.settle(page)
    if first.is_visible():
        return True
    return first.evaluate("""el => {
        const label = el.closest('label') || (el.id && document.querySelector(`label[for="${el.id}"]`));
        return !!label && label.getClientRects().length > 0 && getComputedStyle(label).visibility !== 'hidden';
    }""")


def scenario_every_your_place_ability_is_still_reachable():
    s = _serve()
    if s is None:
        return
    ids = _everything()
    suggested = []

    def suggest(route):
        import json
        body = json.loads(route.request.post_data or '{}')
        suggested.append(body)
        route.fulfill(status=200, headers={'Content-Type': 'application/json'}, body=json.dumps({'rows': [
            {'source': body.get('source'), 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None,
             'building': 'house', 'elsewhere': ids['garage'], 'hint': 'Page 1 looks like the Detached garage.'}]}))
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        check(not _front_door_shown(page), 'a place with buildings shows no front door')
        _strip_ok(page)
        page.route('**/api/house/editor/sheets/suggest', suggest)
        # The page hint (Move it) exists only after a page-role suggestion: ask for one.
        panel = _open_step(page, 'Your files')
        panel.locator(f'[data-place-suggest="{ids["loose"]}"]').click()
        _paid_confirm(page)
        panel.locator('[data-place-hint]').first.wait_for(state='visible', timeout=10000)
        check(suggested and suggested[-1].get('source') == ids['loose'], suggested)

        missing, where = [], {}
        for words, find, steps in _abilities(ids):
            for step in steps:
                if _reached(page, _open_step(page, step), find):
                    where[words] = step
                    break
            else:
                missing.append(f'{words} (looked in {", ".join(steps)})')
        check(not missing, ('every Your place control is reachable from the step panels; missing:', missing))

        build = _open_step(page, 'Build')
        check(re.search(r'about \$\d+\.\d\d', build.inner_text()),
              ('the Build step shows what each build would cost', build.inner_text()))
        # A way back to the house from every panel that took over the dialog.
        for step in ('Your files', 'Your lot', 'Build'):
            panel = _open_step(page, step)
            close = panel.get_by_role('button', name=re.compile(r'^(Back to the house|Close)'))
            if close.count() and close.first.is_visible():
                close.first.click()
            else:
                page.keyboard.press('Escape')
            panel.wait_for(state='hidden', timeout=5000)
        page.screenshot(path=os.path.join(SHOTS, 'house_steps_every_ability.png'))
    check(not _unexpected(s.errors()), s.errors())


# --- Task 8: checks one at a time -----------------------------------------------

def _flags():
    model = H.model()
    return [(b['id'], i, f) for b in model['buildings'] for i, f in enumerate(b.get('flags') or [])]


def _card_flag(page, flags):
    """The flag the check card shows, by its words (None when it shows none of them)."""
    text = page.inner_text('#check-card')
    shown = [row for row in flags if row[2]['text'] in text]
    return shown[0] if shown else None


def _one_check(page):
    check(page.locator('#check-card').is_visible(), 'the check card shows')
    for words in ('Looks right', 'Fix it', 'Skip for now'):
        check(_visible_count(page, words) == 1, (f'one check at a time: one {words}', _visible_count(page, words)))


def scenario_checks_come_one_at_a_time():
    s = _serve()
    if s is None:
        return
    _household()
    flags = _flags()
    total = len(flags)
    check(total == 11, ('test setup: the household has 11 flags', total))
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _wait_house(page)
        check(_step(page, 'Check it').count() == 1, ('one Check it step in the strip', _step(page, 'Check it').count()))
        check(re.search(rf'\b{total}\b', _step(page, 'Check it').first.inner_text()),
              ('the Check it step counts what waits', _step(page, 'Check it').first.inner_text()))
        _open_step(page, 'Check it')
        page.locator('#check-card').wait_for(state='visible', timeout=10000)
        _one_check(page)
        first = _card_flag(page, flags)
        check(first is not None, ('the card says what to check', page.inner_text('#check-card')))
        _button(page, 'Skip for now').click()
        page.wait_for_function("t => !document.getElementById('check-card').innerText.includes(t)", arg=first[2]['text'],
                               timeout=5000)
        second = _card_flag(page, flags)
        check(second is not None and second[:2] != first[:2], ('Skip for now shows the next check', first[:2], second))
        check(len(_flags()) == total, 'skipping changes nothing')
        _one_check(page)
        _button(page, 'Looks right').click()
        deadline = time.time() + 10
        while time.time() < deadline and len(_flags()) != total - 1:
            page.wait_for_timeout(200)
        check(len(_flags()) == total - 1, ('Looks right clears that one flag', len(_flags())))
        page.wait_for_function("t => !document.getElementById('check-card').innerText.includes(t)", arg=second[2]['text'],
                               timeout=10000)
        _one_check(page)
        page.wait_for_function("n => new RegExp('\\\\b' + n + '\\\\b').test(document.querySelector('[data-step=\"Check it\"]').innerText)",
                               arg=total - 1, timeout=10000)
        page.screenshot(path=os.path.join(SHOTS, 'house_steps_checks.png'))
    check(not _unexpected(s.errors()), s.errors())


def scenario_fix_it_opens_the_piece():
    s = _serve()
    if s is None:
        return
    _household()
    flags = _flags()
    flat = H.flat()
    walls = {(b['id'], w['id']) for b in flat['buildings'] for w in b['walls']}
    target = next(r for r in flags if isinstance(r[2].get('piece'), str) and (r[0], r[2]['piece']) in walls)
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        _wait_house(page)
        _open_step(page, 'Check it')
        page.locator('#check-card').wait_for(state='visible', timeout=10000)
        for _ in range(len(flags) + 2):
            shown = _card_flag(page, flags)
            if shown and shown[:2] == target[:2]:
                break
            before = page.inner_text('#check-card')
            _button(page, 'Skip for now').click()
            page.wait_for_function("t => document.getElementById('check-card').innerText !== t", arg=before, timeout=5000)
        check(_card_flag(page, flags)[:2] == target[:2], ('test setup: the walk reaches the wall flag', target[:2]))
        _button(page, 'Fix it').click()
        page.wait_for_function("id => (window.__twinEditor.selection() || {}).id === id", arg=target[2]['piece'], timeout=10000)
        check(page.locator('#piece-card').is_visible(), 'Fix it opens the piece for editing')
        check(len(_flags()) == len(flags), 'Fix it changes nothing by itself; the check waits')
        page.screenshot(path=os.path.join(SHOTS, 'house_steps_fix_it.png'))
    check(not _unexpected(s.errors()), s.errors())


def _model_line(model, bid, wid):
    return H.wall_line(model, bid, wid)


def _on_line(line, seg, tol):
    return all(S._seg_dist(p, seg[0], seg[1]) <= tol for p in line)


def _model_walls_along(model, bid, level, seg, tol=0.05):
    b = H.building(model, bid)
    return [w['id'] for w in b['walls'] if w['level'] == level and w.get('state') != 'ghost'
            and math.dist(*_model_line(model, bid, w['id'])) > 0.1
            and _on_line(_model_line(model, bid, w['id']), seg, tol)]


def scenario_stop_fix_continue():
    # The piece-4 exit flow (Review Focus 3): start, Stop mid-walls, move a wall
    # by hand, Continue; the rest builds on the moved wall, which stays put and
    # stays the person's.
    s = _serve()
    if s is None:
        return
    from services import twin_build as tb, twin_reads, twin_store as ts
    bid = S._pool_house()
    reader = S.StreamReader(gate_at=('draft', S.after_wall(5, half=True)))   # W1-W4 and K1 whole, K2 half way

    def fake_read(kind, images, context, *, run, step, **options):
        keep = {k: v for k, v in options.items() if k in ('cancel', 'on_text')}
        return reader(kind, images, context, run=run, step=step, **keep)

    def fake_read_stream(kind, context, images, *, cancel, on_text, run, step, **options):
        return reader(kind, images, context, run=run, step=step, cancel=cancel, on_text=on_text)

    saved = (twin_reads.read, getattr(twin_reads, 'read_stream', None), tb._REAL_READER)
    twin_reads.read, twin_reads.read_stream, tb._REAL_READER = fake_read, fake_read_stream, fake_read
    w2 = S.WALLS[1]
    try:
        with s.browser(launch_args=GPU_ARGS) as page:
            _open(page, s)
            check(not _front_door_shown(page), 'a place with a building shows no front door')
            build = _open_step(page, 'Build')
            build.locator(f'[data-place-build="{bid}"]').click()
            _paid_confirm(page)
            check(reader.at_gate.wait(30), ('the draft read reached the middle of the walls', reader.calls))
            b = list(tb._BUILDS)[-1]
            arrived = S._wait_for(lambda: len(S._pieces(tb.status(b), 'draft')) >= 7, 10)
            check(arrived, ('the levels and five whole walls arrived before Stop', len(S._pieces(tb.status(b), 'draft'))))

            stop = _button(page, re.compile(r'^Stop( build)?$'))
            pressed = time.monotonic()
            stop.click()
            check(reader.exited.wait(5) and reader.exited_at - pressed <= 3.0,
                  ('Stop in the page ends the paid read at once', reader.exited_at and reader.exited_at - pressed))
            stopped = S._wait_for(lambda: tb.status(b)['state'] == 'stopped', 5)
            check(stopped, ('the build reads stopped', tb.status(b)['state']))
            page.wait_for_function("bid => (window.__twin.plan.buildings || []).some(x => x.id === bid && x.walls.length >= 5)"
                                   " && (window.__editor.build() || {}).state === 'stopped'", arg=bid, timeout=20000)

            # The person moves W2 one foot by hand, in the editor.
            model = ts.current_model()
            along = _model_walls_along(model, bid, w2['level'], [w2['from'], w2['to']])
            check(len(along) == 1, ('test setup: W2 arrived as one wall', along))
            wid = along[0]
            old = _model_line(model, bid, wid)
            page.evaluate("async op => { await window.__twinEditor.op(op); return true; }",
                          {'op': 'move_wall', 'building': bid, 'wall': wid, 'by': [1, 0]})
            moved = [[p[0] + 1, p[1]] for p in old]
            model = ts.current_model()
            piece = next(w for w in H.building(model, bid)['walls'] if w['id'] == wid)
            check(_on_line(_model_line(model, bid, wid), moved, 0.01) and (piece.get('src') or {}).get('person'),
                  ('test setup: the moved wall is the person\'s, one foot over', piece, _model_line(model, bid, wid)))

            _button(page, re.compile(r'^(Continue|Resume)$')).click()
            check(S._wait_for(lambda: reader.kinds().count('draft') == 2 or tb.status(b)['state'] != 'stopped', 10),
                  ('Continue starts the build again', tb.status(b)['state'], reader.kinds()))
            deadline, looked = time.time() + 90, 0
            while time.time() < deadline:
                state = tb.status(b)['state']
                if state == 'done':
                    break
                if state in ('stopped', 'failed'):
                    raise AssertionError(('Continue ended the build early', state, tb.status(b)['events'][-6:]))
                if state == 'paused' and page.locator('#check-card').is_visible() and _visible_count(page, 'Looks right'):
                    _button(page, 'Looks right').click()   # a pause on the way is answered as a person would
                    looked += 1
                    page.wait_for_timeout(500)
                page.wait_for_timeout(250)
            check(tb.status(b)['state'] == 'done', ('Continue builds the rest', tb.status(b)['state'], looked))
            check(reader.kinds().count('draft') == 2 and reader.kinds().count('draft_rooms') == 1,
                  ('Continue reads the stopped step again, then the later ones', reader.kinds()))

            model = ts.current_model()
            piece = next((w for w in H.building(model, bid)['walls'] if w['id'] == wid), None)
            check(piece is not None and _on_line(_model_line(model, bid, wid), moved, 0.01),
                  ('the moved wall stays where the person put it', piece and _model_line(model, bid, wid)))
            check((piece.get('src') or {}).get('person'), ('the moved wall stays the person\'s', piece))
            back = [w for w in _model_walls_along(model, bid, w2['level'], old, tol=0.25) if w != wid]
            check(not back, ('the read does not put W2 back at its old place', back))
            house = S._house(bid)
            for wall in S.WALLS[4:]:
                check(S._covered_once(house, wall), ('the walls still to come were built once', wall['id']))
            built = H.building(model, bid)
            check(built.get('openings') and built.get('rooms'), ('doors, windows and rooms were built on top',
                                                                 len(built.get('openings') or []), len(built.get('rooms') or [])))
            complete = [r for r in ts.rounds() if r['kind'] == 'build' and (r.get('step') or {}).get('id') == 'draft'
                        and not r.get('partial')]
            check(len(complete) == 1, ('the re-read settles as one complete round', len(complete)))

            # The editor draws the house on the moved wall.
            page.wait_for_function("bid => (window.__editor.build() || {}).state === 'done'", arg=bid, timeout=20000)
            H.settle(page)
            drawn = page.evaluate("bid => (window.__twin.plan.buildings.find(x => x.id === bid) || {walls: []}).walls"
                                  ".map(w => ({level: w.level, from: w.from, to: w.to, person: !!(w.src && w.src.person)}))", bid)
            on = [w for w in drawn if w['level'] == w2['level'] and _on_line([w['from'], w['to']], moved, 0.05)
                  and math.dist(w['from'], w['to']) > 0.1]
            check(on and all(w['person'] for w in on), ('the scene shows the moved wall, the person\'s', on))
            page.screenshot(path=os.path.join(SHOTS, 'house_steps_stop_fix_continue.png'))
        check(not _unexpected(s.errors()), s.errors())
    finally:
        twin_reads.read, tb._REAL_READER = saved[0], saved[2]
        if saved[1] is None:
            if hasattr(twin_reads, 'read_stream'):
                del twin_reads.read_stream
        else:
            twin_reads.read_stream = saved[1]
        twin_reads.read = _no_reads
        S._release(reader)


if __name__ == '__main__':
    H.run([
        scenario_empty_house_shows_the_front_door,
        scenario_add_plans_opens_your_files,
        scenario_draw_it_myself_arms_draw_wall,
        scenario_every_your_place_ability_is_still_reachable,
        scenario_checks_come_one_at_a_time,
        scenario_fix_it_opens_the_piece,
        scenario_stop_fix_continue,
    ])
