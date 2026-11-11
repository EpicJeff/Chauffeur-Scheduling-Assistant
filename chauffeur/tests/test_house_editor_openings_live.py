"""Adding doors and windows in the house editor, in real Chromium, the way a
person does it (bug report 2026-11-11: "I have not gotten adding doors or
windows to work ... it fails to add every time I try either one").

A person presses Add door or Add window on the rail, then clicks the wall
where they see it: its face, a few feet up, in the 3D view. Before the fix
draw.js projected that click onto the focused floor's plane and only took a
wall within 1 ft of that floor point, so a click on a wall's face (the
projection lands feet behind the wall) and any click on a building or floor
other than the focused one (the first building's ground floor when none is
focused) said "Click a solid wall." and sent nothing.

Each scenario starts from the seeded household (tests/house_editor_model_harness.py),
opens its own page and checks that:
- the opening is stored on the wall that was clicked, near where it was clicked;
- the scene draws it (its piece is in the scene and a pick on it finds it);
- a spot that cannot hold one (already a door there) is refused in plain words,
  shown to the person, and nothing is stored.

The pool house (rotation 270 on the lot), level L1, in its own plan feet:
front wall y = 0 x 0-31 (slider 3.08-15.08, bifold 18.67-28.67), north wall
y = 22, interior wall y = 12.1667 x 17.75-31 (a wall meets it at x = 24.33,
so its first stretch is 17.75-24.33). The main house: L1 interior wall
y = 35.67 x 0-14.33; L2 (elevation 11) exterior wall y = 52 x 14.33-37, windows at x 22.5-25.5
and 32.5-35.5, a porch below it whose pick box reaches up past its roof.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_openings_live.py
"""
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_openings_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
POOL = 'pool-house'
MAIN = 'main-house'
VIEWPORT = {'width': 1600, 'height': 900}
_SEED = {}


def _serve():
    s = H.serve()
    if s is not None:
        _reset()
    return s


def _reset():
    from services import twin_store
    if 'round' not in _SEED:
        _SEED['round'] = min(r['id'] for r in twin_store.rounds())
        _SEED['model'] = twin_store.current_model()
    if twin_store.current_model() != _SEED['model']:
        twin_store.revert(_SEED['round'])


def _open(page, served, floor=None):
    dialogs = []
    page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
    page.set_viewport_size(VIEWPORT)
    H.open_editor(page, served)
    if floor:
        H.choose_floor(page, floor)
    return dialogs


def _no_errors(served, dialogs):
    check(not dialogs, ('no browser dialogs; use promptInput and showGlobalAlert', dialogs))
    errors = H.unexpected(served.errors())
    check(not errors, errors)


def _openings(model, bid):
    return {o['id']: o for o in H.building(model, bid)['openings']}


def _wait_new(before, bid, what, timeout=20.0):
    known = set(_openings(before, bid))
    deadline = time.time() + timeout
    while time.time() < deadline:
        model = H.model()
        added = [o for i, o in _openings(model, bid).items() if i not in known]
        if added:
            return model, added
        time.sleep(0.1)
    raise AssertionError(f'the stored house never showed {what}')


def _alert(page):
    modal = page.locator('#cc-alert-modal')
    return page.inner_text('#cc-alert-message').strip() if modal.count() and modal.is_visible() else None


def _note(page):
    return page.inner_text('#draw-note').strip() if page.locator('#draw-note').is_visible() else ''


def _add(page, served, tool, bid, point, what, kind):
    """Press the rail tool, click the wall at `point` (building feet, z above the
    building's base), and return the stored opening it made and its wall line."""
    before = H.model()
    page.click(f'#rail-{tool}')
    H.settle(page)
    H.click_world(page, *point, bid)
    try:
        after, added = _wait_new(before, bid, what)
    except AssertionError:
        raise AssertionError((f'{what}: nothing was stored', 'note:', _note(page), 'alert:', _alert(page)))
    check(len(added) == 1, (what, 'exactly one opening', added))
    opening = added[0]
    check(opening['kind'] == kind and abs(opening['width'] - 3.0) < 1e-6, (what, opening))
    return after, opening, H.wall_line(after, bid, opening['wall'])


def _on_line(line, x, y, tol=0.05):
    (ax, ay), (bx, by) = line
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    cross = abs(dx * (y - ay) - dy * (x - ax)) / length
    along = ((x - ax) * dx + (y - ay) * dy) / length
    return cross <= tol and -tol <= along <= length + tol, along


def _placed(opening, line, x, y, what):
    on, along = _on_line(line, x, y)
    check(on, (what, 'on the clicked wall', line, (x, y)))
    check(abs(opening['at'] - along) < 0.5, (what, 'where it was clicked', opening['at'], along))


def _seen(page, opening, bid, what):
    """The scene draws the new opening: its piece is there, and a pick at it finds it."""
    deadline = time.time() + 20
    while time.time() < deadline:
        if opening['id'] in (page.evaluate('(b) => window.__twin.pieceIds(b)', bid) or []):
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError((what, 'the scene never drew the opening', opening['id']))
    H.settle(page)
    picked = page.evaluate("""([id, b]) => {
        const at = window.__twin.screenOf(id, b); if (!at) return null;
        // Rooms skipped as the opening tools skip them: a porch's pick box can
        // stand in front of the wall above it (a Select-mode matter, not this one).
        const hit = window.__twin.pick(at[0], at[1], { skip: ['room'] });
        return hit && { kind: hit.kind, id: hit.id };
    }""", [opening['id'], bid])
    check(picked and picked['kind'] == 'opening' and picked['id'] == opening['id'],
          (what, 'a pick on the drawn opening finds it', picked))


def _front(page, bid, x, y, z, normal, distance=22.0, rise=3.0):
    """Stand `distance` feet out along `normal` from a wall point and look at it."""
    page.evaluate("() => { document.querySelector('#editor-cameras [data-editor-camera=\"front\"]')?.click(); }")
    H.settle(page)
    H.look_at(page, bid, [x + normal[0] * distance, y + normal[1] * distance, z + rise], [x, y, z])


# --- scenarios ---------------------------------------------------------------

def scenario_door_on_an_outside_wall_face_with_no_floor_chosen():
    """The editor opens on the whole house; the person never picks a floor."""
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        # The pool house's north wall (y = 22, outside is +y), 4 ft up its face.
        _front(page, POOL, 9.0, 22.0, 4.0, (0, 1))
        _, door, line = _add(page, s, 'add-door', POOL, (9.0, 22.0, 4.0), 'a door on the north wall', 'door')
        _placed(door, line, 9.0, 22.0, 'the door')
        check(abs(line[0][1] - 22.0) < 1e-6 and abs(line[1][1] - 22.0) < 1e-6, ('the north wall', line))
        _seen(page, door, POOL, 'the door')
        check(_alert(page) is None, ('no alert', _alert(page)))
        _no_errors(s, dialogs)


def scenario_window_on_an_upper_floor_outside_wall():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s)
        # The main house's second floor (elevation 11), back wall y = 52, 4 ft up,
        # between its windows (x 32.5-35.5 and 22.5-25.5), over the porch roof.
        _front(page, MAIN, 29.0, 52.0, 15.0, (0, 1), distance=30.0)
        _, window, line = _add(page, s, 'add-window', MAIN, (29.0, 52.0, 15.0), 'a window upstairs', 'window')
        _placed(window, line, 29.0, 52.0, 'the window')
        level = next(w for w in H.building(H.model(), MAIN)['walls'] if w['id'] == window['wall'])['level']
        check(level == 'L2', ('on the second floor wall, not the one below it', level))
        _seen(page, window, MAIN, 'the window')
        _no_errors(s, dialogs)


def scenario_door_on_an_inside_wall_of_the_chosen_floor():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s, 'pool-house:L1')
        # The interior wall y = 12.1667 (x 17.75-31), seen from the front room at an angle.
        y = 12.166666666666666
        H.look_at(page, POOL, [21.0, -6.0, 22.0], [21.0, y, 3.0])
        _, door, line = _add(page, s, 'add-door', POOL, (21.0, y, 4.0), 'a door on the inside wall', 'door')
        _placed(door, line, 21.0, y, 'the door')
        _seen(page, door, POOL, 'the door')
        _no_errors(s, dialogs)


def scenario_window_on_an_inside_wall_of_the_chosen_floor():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s, 'main-house:L1')
        # The main house's L1 interior wall y = 35.67 (x 0-14.33).
        y = 35.666666666666664
        H.look_at(page, MAIN, [7.0, 20.0, 24.0], [7.0, y, 3.0])
        _, window, line = _add(page, s, 'add-window', MAIN, (7.0, y, 5.0), 'a window on the inside wall', 'window')
        _placed(window, line, 7.0, y, 'the window')
        _seen(page, window, MAIN, 'the window')
        _no_errors(s, dialogs)


def scenario_a_spot_that_already_has_a_door_is_refused_in_words():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=H.GPU_ARGS) as page:
        dialogs = _open(page, s, 'pool-house:L1')
        # The pool house's front wall y = 0: its 12 ft slider runs x 3.08-15.08.
        H.look_at(page, POOL, [9.0, -22.0, 7.0], [9.0, 0.0, 4.0])
        before = H.model()
        page.click('#rail-add-door')
        H.settle(page)
        H.click_world(page, 9.0, 0.0, 4.0, POOL)
        deadline = time.time() + 20
        while time.time() < deadline and _alert(page) is None:
            page.wait_for_timeout(100)
        words = _alert(page)
        check(words, ('the refusal is shown', 'note:', _note(page)))
        check('already' in words.lower() and 'invalid' not in words.lower(), ('plain words', words))
        page.wait_for_timeout(500)
        check(_openings(H.model(), POOL) == _openings(before, POOL), 'nothing was stored')
        _no_errors(s, dialogs)


SCENARIOS = [
    scenario_door_on_an_outside_wall_face_with_no_floor_chosen,
    scenario_window_on_an_upper_floor_outside_wall,
    scenario_door_on_an_inside_wall_of_the_chosen_floor,
    scenario_window_on_an_inside_wall_of_the_chosen_floor,
    scenario_a_spot_that_already_has_a_door_is_refused_in_words,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
