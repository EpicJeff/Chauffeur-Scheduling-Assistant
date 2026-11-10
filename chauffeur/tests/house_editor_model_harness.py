"""Shared harness for the connected-model editor's live scenarios (Part B of
docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md; Ruling
R29 in .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/progress.md).

Each Part B task keeps its scenarios in tests/test_house_editor_model_live_t<N>.py
and imports this module. It seeds the household's real house, serves the app,
opens /house/editor as a parent with the test flag, and gives a few helpers.

    import house_editor_model_harness as H
    s = H.serve()                         # None -> playwright missing, skip
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        H.choose_floor(page, 'pool-house:L1')
        H.look_down(page, 'pool-house', 15.5, 9.0)
        H.click_world(page, 8, 8, 0, 'pool-house')
        H.editor_state(page, 'selection')

Coordinates. Every helper that takes a point takes it in the building's own
plan coordinates in feet (x, y as the plan stores them), plus z in feet above
the building's base (a level's elevation plus a height within that level). The
helpers apply the building's position and rotation the way twin_view does
(wx = cos(a) x - sin(a) y + px; wy = sin(a) x + cos(a) y + py; the scene's
three.js point is (wx, base + z, -wy) * FT). The ground is flat
(twin_ground.groundAt returns 0).

The seed. tests/fixtures/twin_model/household-2026-11-09.json (schema 2, the
plan from the user's build record) goes in through twin_store.push_round, which
assembles it into schema 3 (migration, Task 6). A task file may pass `mutate`
to serve() to change the flat plan before the push (for example to name a
room); serve() seeds once per process, so one mutate per test file.

The hooks. The editor sets window.__editor (ready flag and the slice-1 hooks)
and, from Part B, window.__twinEditor, both only under ?test=1. open_editor
waits for window.__editor.ready and then insists window.__twinEditor exists.
The scene is window.__twin (twin_view), which offers pick, screenOf,
pieceInfo, pieceIds and, under ?test=1, setCameraState.

The model. The app runs in this process, so model() and flat() read the
store directly (twin_store.current_model() and current()).
"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_model_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_app import live_app, goto_retry  # noqa: E402
import test_twin_view_live as p0view  # noqa: E402  (library download stubs)

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
FT = 0.3048
HOUSEHOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_model',
                         'household-2026-11-09.json')
PARENT = {'id': 'p1', 'name': 'Pat', 'role': 'parent', 'email': 'pat@example.com'}
STATE = {}
_SERVED = {}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# --- seed and serve ---------------------------------------------------------

def household_plan():
    """A fresh copy of the household's flat (schema 2) plan."""
    with open(HOUSEHOLD, encoding='utf-8') as f:
        return json.load(f)


def seed(mutate=None):
    """Auth on, one parent with a session token, the household pushed as a round."""
    from services import storage, twin_library, twin_store
    twin_library._urlopen = p0view._stub_urlopen
    storage.patch_settings({'auth_enforce': True})
    storage.add_member(dict(PARENT))
    storage.set_member_password(PARENT['id'], 'correct horse battery staple')
    STATE['token'] = storage.create_member_token(PARENT['id'])
    plan = household_plan()
    if mutate:
        plan = mutate(plan) or plan
    twin_store.push_round(plan, 'build')


def serve(mutate=None):
    """The served app (seeded once per process), or None when playwright is missing."""
    if 'served' not in _SERVED:
        _SERVED['served'] = live_app(lambda: seed(mutate))
    return _SERVED['served']


def model():
    """The stored schema 3 model."""
    from services import twin_store
    return twin_store.current_model()


def flat():
    """The stored flat view the editor's scene draws."""
    from services import twin_store
    return twin_store.current()


def building(plan, bid):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def room_walls(model_, bid, room_id):
    """Ids of the walls along a room's joint cycle (schema 3), in cycle order."""
    b = building(model_, bid)
    room = next(r for r in b['rooms'] if r['id'] == room_id)
    by_pair = {frozenset(w['joints']): w['id'] for w in b['walls']}
    cycle = room.get('joints') or []
    pairs = [frozenset((cycle[i], cycle[(i + 1) % len(cycle)])) for i in range(len(cycle))]
    return [by_pair[p] for p in pairs if p in by_pair]


def wall_line(model_, bid, wall_id):
    """[from, to] of a schema 3 wall, read through its joints."""
    b = building(model_, bid)
    joints = {j['id']: j['at'] for j in b['joints']}
    wall = next(w for w in b['walls'] if w['id'] == wall_id)
    return [list(joints[wall['joints'][0]]), list(joints[wall['joints'][1]])]


def unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


# --- the page ---------------------------------------------------------------

def signed_in(page):
    """Place the parent session in localStorage the way admin_gate stores it."""
    # Init scripts run in every document, Chromium's chrome-error:// page after a
    # loopback reset included, where localStorage throws (R56): guard both.
    page.add_init_script(SIGN_IN_SCRIPT % (json.dumps(STATE['token']), json.dumps(PARENT['id'])))


SIGN_IN_SCRIPT = (
    "if (location.protocol.startsWith('http')) { try {"
    "localStorage.setItem('chauffeur_admin_token', %s);"
    "localStorage.setItem('chauffeur_admin_token_for', %s);"
    "} catch (e) {} }")


def settle(page, frames=2):
    page.evaluate('(n) => new Promise(r => { const step = k => k ? requestAnimationFrame(() => step(k - 1)) : r(); step(n); })',
                  frames)


def open_editor(page, served, query='tier=high&test=1'):
    """Sign in, open the editor, wait for the house to draw, and require window.__twinEditor."""
    signed_in(page)
    goto_retry(page, served.url(f'house/editor?{query}'))
    page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=90000)
    page.wait_for_function("() => window.__twin && window.__twin.plan && (window.__twin.plan.buildings || []).length > 0"
                           " && window.__twin.pieceIds(window.__twin.plan.buildings[0].id).length > 0", timeout=60000)
    if page.locator('#place-view').is_visible():
        page.click('#place-close')
        page.wait_for_selector('#place-view', state='hidden', timeout=10000)
    check(page.evaluate('() => !!window.__twinEditor'),
          'window.__twinEditor is missing: the editor sets it under ?test=1 (Part B test hooks)')
    settle(page)


def editor_state(page, name, *args):
    """Read window.__twinEditor[name]: called with args when it is a function, else its value."""
    return page.evaluate("""([name, args]) => {
        const hooks = window.__twinEditor;
        if (!hooks) throw new Error('window.__twinEditor is missing');
        const value = hooks[name];
        return typeof value === 'function' ? value(...args) : value;
    }""", [name, list(args)])


def scene_signature(page):
    """A short signature of the plan the scene last drew."""
    return page.evaluate("""() => {
        const text = JSON.stringify(window.__twin && window.__twin.plan || null);
        let h = 0; for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
        return text.length + ':' + h;
    }""")


def wait_rebuilt(page, before=None, timeout=30.0):
    """Wait until the scene draws a plan other than `before` (a scene_signature), then two frames."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        now = scene_signature(page)
        if before is None or now != before:
            settle(page)
            return now
        page.wait_for_timeout(100)
    raise AssertionError('the scene never rebuilt')


def choose_floor(page, key):
    """Press a floor's button in the Floors aside (key is '{building}:{level}')."""
    page.click(f'#editor-floors [data-floor="{key}"]')
    settle(page)


def all_floors(page):
    page.click('#editor-floors button:text-is("All floors")')
    settle(page)


def card_title(page):
    """The selected thing's card heading, or None when the card is hidden."""
    if not page.locator('#piece-card').is_visible():
        return None
    return page.inner_text('#piece-card h3').strip()


_TO_SCENE = """
    const toScene = ([x, y, z], bid) => {
        const b = (window.__twin.plan.buildings || []).find(item => item.id === bid);
        if (!b) throw new Error('no building ' + bid);
        const a = (b.rotation || 0) * Math.PI / 180;
        const wx = Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0);
        const wy = Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0);
        return [wx * %r, ((b.base || 0) + z) * %r, -wy * %r];
    };
""" % (FT, FT, FT)


def screen_of_world(page, x, y, z, bid):
    """Client pixel [x, y] of a building-local point (feet), through the current camera."""
    return page.evaluate("([p, bid]) => {" + _TO_SCENE + """
        const view = window.__twin, camera = view.camera;
        camera.updateMatrixWorld(true);
        const v = camera.position.clone().set(...toScene(p, bid)).project(camera);
        const r = view.renderer3.domElement.getBoundingClientRect();
        return [r.left + (v.x + 1) * r.width / 2, r.top + (1 - v.y) * r.height / 2];
    }""", [[x, y, z], bid])


def _on_canvas(page, sx, sy):
    hit = page.evaluate("""([x, y]) => {
        const node = document.elementFromPoint(x, y), canvas = window.__twin.renderer3.domElement;
        return node === canvas ? null : (node ? node.tagName + '#' + node.id + '.' + node.className : 'nothing');
    }""", [sx, sy])
    check(hit is None, f'the point ({sx:.0f}, {sy:.0f}) is covered by {hit}, not the scene')


def click_world(page, x, y, z, bid):
    """A real mouse click at a building-local point; returns the client pixel."""
    sx, sy = screen_of_world(page, x, y, z, bid)
    _on_canvas(page, sx, sy)
    page.mouse.click(sx, sy)
    settle(page)
    return sx, sy


def hover_world(page, x, y, z, bid):
    """A real mouse move to a building-local point (no buttons); returns the client pixel."""
    sx, sy = screen_of_world(page, x, y, z, bid)
    _on_canvas(page, sx, sy)
    page.mouse.move(sx - 3, sy - 3)
    page.mouse.move(sx, sy)
    settle(page)
    return sx, sy


def look_at(page, bid, eye, target):
    """Point the perspective camera from `eye` at `target` (building-local [x, y, z] feet)."""
    page.evaluate("([eye, target, bid]) => {" + _TO_SCENE + """
        const view = window.__twin;
        if (view.cameraKind() !== 'perspective') view.setCamera('front');
        view.setCameraState({ position: toScene(eye, bid), target: toScene(target, bid) });
    }""", [list(eye), list(target), bid])
    settle(page)


def look_down(page, bid, x, y, height=90.0):
    """A camera straight above a building-local point, looking down (the floor plan in 3D)."""
    look_at(page, bid, [x, y - 0.01, height], [x, y, 0.0])


def press(page, key):
    page.keyboard.press(key)
    settle(page)


def run(scenarios):
    """The house runner: every scenario runs, failures are listed, exit non-zero on any."""
    import traceback
    failed = []
    for fn in scenarios:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(scenarios) - len(failed)}/{len(scenarios)} passed')
    served = _SERVED.get('served')
    if served is not None:
        served.stop()
    sys.exit(1 if failed else 0)
