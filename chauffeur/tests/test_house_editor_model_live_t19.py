"""The editor places each room's devices, in real Chromium (piece 3 Task 5 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; brief
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-5-brief.md; spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md section 7,
"the placement flow, room by room").

The house is the household's migrated house (tests/house_editor_model_harness.py).
The pool house's 'Pool Lounge' is renamed 'Kitchen' before the push (Task 10's
naming), and every scenario puts back the seeded model with:
- the Kitchen linked to the Home Assistant area `kitchen`;
- LIGHT_1, LIGHT_2: light anchors on the Kitchen ceiling; LIGHT_1 holds the Ceiling light;
- SWITCH_1: a switch anchor on WEST_X0, the Kitchen side ('left'), at 2.5, z 4, holding the Coffee plug;
- SWITCH_2: a switch anchor on NORTH_IN, the Kitchen side ('right'), at 6, z 4, free.

Home Assistant is faked in-process (tests/house_ha_fake.py): area Kitchen holds
Ceiling light (flash), Counter lamp (no flash), Pendant (flash), Coffee plug and
Kettle plug (switches); area Patio holds the Patio light. So the plan shows 2
lights and Home Assistant has 3; switches agree (2 and 2).

What the editor must give (the brief):
- The room card has a `Devices` section listing the area's devices, each row with
  the device's name, its kind and `Placed` or `Not placed yet`, and the count notes
  under it (`The plan shows 2 lights; Home Assistant has 3 in this area.`).
- `Pick a spot` opens promptChoice (#cc-choice-modal) over the room's free anchors
  of a fitting kind plus `On a wall` and `On the ceiling`. An anchor posts
  {op: 'place_device', device, anchor}. `On a wall` arms a one-click placement:
  the next click on a wall posts {op: 'place_device', device, building, host:
  {wall, side, at, z}} (the library's surface pick decides the host); Escape cancels.
- Dragging a device row onto the scene: onto an anchor posts place_device with
  `anchor`; onto a wall posts it with that wall host at the drop point. An anchor
  holding another device refuses with `That spot already holds a device; move it
  first.` through showGlobalAlert (#cc-alert-message), and nothing is stored.
- `Blink` (lights only) calls POST api/house/ha/identify; Home Assistant sees
  light.turn_on with flash 'short'; a failure shows `Could not blink that light.`
- An anchor card shows its device with `Remove`, which posts {op: 'unplace_device', device}.

A device row, as this file finds it: the innermost element inside #piece-card
whose text holds the device's name and `Placed` or `Not placed yet` and that
holds a button. The drag grabs the row 12 px in from its left edge, mid-height
(the row is the drag source; its buttons sit to the right of the name).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t19.py
"""
import copy
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t19_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402
import house_ha_fake  # noqa: E402

check = H.check
POOL = 'pool-house'
FLOOR_KEY = 'pool-house:L1'
KITCHEN = 'room:5d7de10ca48340ae85c407d22337c6f7'
WEST_X0 = 'wall:17ec2a8dad9e47d0aefbfe143524c1c2~2'     # x = 0, from (0, 17.33) to (0, 0)
NORTH_IN = 'wall:d60289b4c26b487db5145bdeb22d530e'      # y = 17.33, from (0, 17.33) to (17.75, 17.33)
LIGHT_1, LIGHT_2 = 'anchor:t19-light-1', 'anchor:t19-light-2'
SWITCH_1, SWITCH_2 = 'anchor:t19-switch-1', 'anchor:t19-switch-2'

NY = 17.0 + 1.0 / 3.0            # the line of NORTH_IN
FACE = NY - 0.25                 # NORTH_IN's Kitchen face
KITCHEN_FLOOR = (8.0, 8.0, 0.0)
ABOVE = (15.5, 9.0)
EYE, TARGET = (7.0, 11.0, 5.0), (0.5, 16.6, 4.0)   # t12's view of the Kitchen's north-west corner
WALL_EYE, WALL_TARGET = (6.0, 8.0, 5.5), (6.0, NY, 5.5)   # straight at NORTH_IN from inside the Kitchen
DROP = (5.0, FACE, 6.0)          # on NORTH_IN, clear of SWITCH_2 (6, z 4); seen by the wall view
ARMED = (7.5, FACE, 6.0)         # on NORTH_IN, for the armed click

OCCUPIED = 'That spot already holds a device; move it first.'
BLINK_FAILED = 'Could not blink that light.'
LIGHTS_NOTE = 'The plan shows 2 lights; Home Assistant has 3 in this area.'

DEVICES = {   # device id -> (name, entity id)
    'dev-k-ceiling': ('Ceiling light', 'light.ceiling_light'),
    'dev-k-lamp': ('Counter lamp', 'light.counter_lamp'),
    'dev-k-pendant': ('Pendant', 'light.pendant'),
    'dev-k-coffee': ('Coffee plug', 'switch.coffee_plug'),
    'dev-k-kettle': ('Kettle plug', 'switch.kettle_plug'),
}
FAKE = house_ha_fake.FakeHA(
    areas=[{'area_id': 'kitchen', 'name': 'Kitchen', 'floor_id': 'ground'},
           {'area_id': 'patio', 'name': 'Patio', 'floor_id': 'ground'}],
    floors=[{'floor_id': 'ground', 'name': 'Ground floor', 'level': 0}],
    devices=[{'id': 'dev-k-ceiling', 'name': 'Ceiling light', 'area_id': 'kitchen',
              'entities': [('light.ceiling_light', 'off', {'supported_features': 8 | 32})]},
             {'id': 'dev-k-lamp', 'name': 'Counter lamp', 'area_id': 'kitchen',
              'entities': [('light.counter_lamp', 'off', {'supported_features': 0})]},
             {'id': 'dev-k-pendant', 'name': 'Pendant', 'area_id': 'kitchen',
              'entities': [('light.pendant', 'off', {'supported_features': 8})]},
             {'id': 'dev-k-coffee', 'name': 'Coffee plug', 'area_id': 'kitchen',
              'entities': [('switch.coffee_plug', 'off', {})]},
             {'id': 'dev-k-kettle', 'name': 'Kettle plug', 'area_id': 'kitchen',
              'entities': [('switch.kettle_plug', 'off', {})]},
             {'id': 'dev-patio', 'name': 'Patio light', 'area_id': 'patio',
              'entities': [('light.patio_light', 'off', {'supported_features': 8})]}],
).install()
SEED = {}


def _rename(plan):
    room = next(r for r in H.building(plan, POOL)['rooms'] if r['id'] == KITCHEN)
    room['name'] = 'Kitchen'
    room['ha_area'] = ''
    return plan


def _serve():
    served = H.serve(_rename)
    if served is not None and 'model' not in SEED:
        SEED['model'] = copy.deepcopy(H.model())
    return served


def _linked(model):
    b = H.building(model, POOL)
    next(r for r in b['rooms'] if r['id'] == KITCHEN)['ha_area'] = 'kitchen'
    b['anchors'] = [a for a in b.get('anchors') or [] if not a['id'].startswith('anchor:t19-')] + [
        {'id': LIGHT_1, 'kind': 'light', 'host': {'ceiling': KITCHEN, 'u': 0.3, 'v': 0.3}, 'offset': 0, 'device': 'dev-k-ceiling'},
        {'id': LIGHT_2, 'kind': 'light', 'host': {'ceiling': KITCHEN, 'u': 0.6, 'v': 0.3}, 'offset': 0, 'device': None},
        {'id': SWITCH_1, 'kind': 'switch', 'host': {'wall': WEST_X0, 'side': 'left', 'at': 2.5, 'z': 4.0},
         'offset': 0, 'device': 'dev-k-coffee'},
        {'id': SWITCH_2, 'kind': 'switch', 'host': {'wall': NORTH_IN, 'side': 'right', 'at': 6.0, 'z': 4.0},
         'offset': 0, 'device': None},
    ]
    b['devices'] = []


def _reset():
    """The seeded house, the Kitchen linked, the four anchors; Home Assistant connected."""
    from services import twin_store
    FAKE.available = True
    FAKE.fail_calls = False
    del FAKE.calls[:]

    def mutate(_before):
        model = copy.deepcopy(SEED['model'])
        _linked(model)
        return model
    twin_store.update_model(mutate, 'edit', note='t19 reset')


# --- the stored house -----------------------------------------------------------

def _b(model=None):
    return H.building(model or H.model(), POOL)


def _anchor(model, aid):
    return next((a for a in _b(model).get('anchors') or [] if a['id'] == aid), None)


def _placements(model, device_id):
    out = []
    for b in model['buildings']:
        for a in b.get('anchors') or []:
            if a.get('device') == device_id:
                out.append(('anchor', b['id'], a))
        for d in b.get('devices') or []:
            if d.get('device') == device_id:
                out.append(('host', b['id'], d))
    return out


def _store():
    from services import twin_store
    return {'round': twin_store.current_id(), 'rounds': len(twin_store.rounds())}


def _facts():
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3', 'the store holds a schema 3 model')
    b = _b(model)
    room = next(r for r in b['rooms'] if r['id'] == KITCHEN)
    check(room['name'] == 'Kitchen' and room['ha_area'] == 'kitchen', ('the Kitchen is linked', room))
    for aid, device in ((LIGHT_1, 'dev-k-ceiling'), (LIGHT_2, None), (SWITCH_1, 'dev-k-coffee'), (SWITCH_2, None)):
        a = _anchor(model, aid)
        check(a is not None and (a.get('device') or None) == device,
              ('the seeded anchor keeps its device (Task 2: anchors carry `device`)', aid, a))
    walls = H.room_walls(model, POOL, KITCHEN)
    check(WEST_X0 in walls and NORTH_IN in walls, walls)
    line = H.wall_line(model, POOL, NORTH_IN)
    check(all(abs(a - b) < 0.01 for a, b in zip(line[0] + line[1], [0.0, NY, 17.75, NY])), ('NORTH_IN runs +x along y = 17.33', line))
    return model


def _world(model, aid):
    from services import twin_model_hosts
    a = _anchor(model, aid)
    return twin_model_hosts.world_point(_b(model), a['host'], a.get('offset', 0))


# --- page helpers ----------------------------------------------------------------

def _record_ops(page):
    posted = []

    def on_request(request):
        if request.method == 'POST' and request.url.split('?')[0].endswith('/api/house/editor/op'):
            try:
                body = request.post_data_json
            except Exception:
                body = None
            posted.append((body or {}).get('op') if isinstance(body, dict) else body)
    page.on('request', on_request)
    return posted


def _selection(page, until=None, timeout=3.0):
    deadline = time.time() + timeout
    while True:
        sel = H.editor_state(page, 'selection')
        if until is None or until(sel) or time.time() > deadline:
            return sel
        page.wait_for_timeout(50)


def _is(kind, pid):
    return lambda sel: bool(sel) and (kind is None or sel.get('kind') == kind) and sel.get('id') == pid


def _open(page, served):
    H.open_editor(page, served)
    try:
        page.wait_for_function('() => !!(window.__twinEditor && window.__twinEditor.haLink)', timeout=5000)
    except Exception:
        raise AssertionError('window.__twinEditor.haLink is missing: the editor exposes createHaLink(...) there under ?test=1')
    page.wait_for_function("""() => {
        const link = window.__twinEditor.haLink, state = link.state && link.state();
        return !!state && state.available === true && (state.devices || []).length > 0;
    }""", timeout=20000)
    H.choose_floor(page, FLOOR_KEY)


def _kitchen(page, view=None):
    """Focus the Kitchen with a real click on its floor; then look at its north-west
    corner ('corner') or straight at NORTH_IN ('wall'); None keeps the view from above."""
    H.look_down(page, POOL, *ABOVE)
    H.click_world(page, *KITCHEN_FLOOR, POOL)
    sel = _selection(page, _is('room', KITCHEN))
    check(_is('room', KITCHEN)(sel), ('a click on the Kitchen floor focuses the Kitchen', sel))
    check(H.card_title(page) == 'Kitchen', ('the Kitchen card', H.card_title(page)))
    if view == 'corner':
        H.look_at(page, POOL, EYE, TARGET)
    elif view == 'wall':
        H.look_at(page, POOL, WALL_EYE, WALL_TARGET)


def _card_text(page):
    return ' '.join(page.inner_text('#piece-card').split())


ROW_JS = """([name, mark]) => {
    const card = document.getElementById('piece-card');
    document.querySelectorAll('[data-t19-row]').forEach(n => n.removeAttribute('data-t19-row'));
    const fits = n => { const t = n.innerText || '';
        return t.includes(name) && (t.includes('Placed') || t.includes('Not placed yet')) && !!n.querySelector('button'); };
    const all = [...card.querySelectorAll('*')].filter(fits);
    const rows = all.filter(n => !all.some(m => m !== n && n.contains(m)));
    rows.forEach(n => n.setAttribute('data-t19-row', mark));
    return rows.length;
}"""


def _row(page, name):
    """The device's row in the Devices section (see the module docstring)."""
    found = page.evaluate(ROW_JS, [name, 'row'])
    check(found == 1, ('one Devices row for', name, found, _card_text(page)))
    row = page.locator('[data-t19-row="row"]')
    row.scroll_into_view_if_needed()
    return row


def _status(page, name):
    text = ' '.join(_row(page, name).inner_text().split())
    if 'Not placed yet' in text:
        return 'Not placed yet'
    return 'Placed' if 'Placed' in text else text


def _button(row, label):
    found = row.get_by_role('button', name=label, exact=True)
    check(found.count() == 1, ('the row has one button', label, found.count(), row.inner_text()))
    return found


def _choices(page):
    page.wait_for_selector('#cc-choice-modal', state='visible', timeout=5000)
    return [' '.join(t.split()) for t in page.locator('#cc-choice-options button').all_inner_texts()]


def _choose(page, text):
    page.locator('#cc-choice-options button').filter(has_text=text).first.click()
    H.settle(page)


def _committed(page, posted, before, count=1, timeout=20.0):
    from services import twin_store
    deadline = time.time() + timeout
    while time.time() < deadline and twin_store.current_id() == before['round']:
        page.wait_for_timeout(100)
    check(twin_store.current_id() != before['round'], ('nothing was stored (no new round)', posted, _alert(page)))
    page.wait_for_timeout(500)
    check(len(posted) == count, ('the editor posted', count, 'op(s)', posted))
    check(len(twin_store.rounds()) == before['rounds'] + 1, 'one action adds exactly one round')
    return list(posted)


def _alert(page):
    if not page.locator('#cc-alert-modal').is_visible():
        return None
    return page.inner_text('#cc-alert-message').strip()


def _wait_alert(page, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline and _alert(page) is None:
        page.wait_for_timeout(100)
    return _alert(page)


def _wait(page, cond, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        page.wait_for_timeout(100)
    return cond()


def _drag_row_to(page, name, point):
    """Press on the device's row, carry it over the scene, release at a building-local point."""
    row = _row(page, name)
    box = row.bounding_box()
    check(box and box['width'] > 20 and box['height'] > 8, ('the row is on screen', box))
    sx, sy = H.screen_of_world(page, *point, POOL)
    H._on_canvas(page, sx, sy)
    x0, y0 = box['x'] + 12, box['y'] + box['height'] / 2
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x0 - 6, y0 + 2, steps=3)
    page.mouse.move(x0 - 20, y0 + 6, steps=3)
    page.mouse.move(sx, sy, steps=20)
    page.mouse.move(sx + 1, sy, steps=2)
    page.mouse.move(sx, sy, steps=2)
    H.settle(page)
    page.mouse.up()
    H.settle(page)


def _wall_host(op, wall, side, at, z, tol=0.5):
    host = (op or {}).get('host') or {}
    return (host.get('wall') == wall and host.get('side') == side
            and abs(float(host.get('at', -99)) - at) <= tol and abs(float(host.get('z', -99)) - z) <= tol)


def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


# --- scenarios -------------------------------------------------------------------

def scenario_count_note_shows():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        _open(page, s)
        _kitchen(page)
        text = _card_text(page)
        check('Devices' in text, ('the room card has a Devices section', text))
        check(LIGHTS_NOTE in text, ('the count note, word for word', text))
        check('switches;' not in text, ('switches agree, so no note for them', text))
        for _device, (name, _eid) in DEVICES.items():
            _row(page, name)
        check('Patio light' not in text, ('only the area\'s own devices are listed', text))
        check(_status(page, 'Ceiling light') == 'Placed', _status(page, 'Ceiling light'))
        check(_status(page, 'Coffee plug') == 'Placed', _status(page, 'Coffee plug'))
        for name in ('Counter lamp', 'Pendant', 'Kettle plug'):
            check(_status(page, name) == 'Not placed yet', (name, _status(page, name)))
        check('switch' in _row(page, 'Kettle plug').inner_text().lower(), ('the row names its kind', _row(page, 'Kettle plug').inner_text()))
        check('light' in _row(page, 'Pendant').inner_text().lower(), ('the row names its kind', _row(page, 'Pendant').inner_text()))
        _no_errors(s)


def scenario_pick_a_spot_on_an_anchor():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _kitchen(page)
        check(_status(page, 'Kettle plug') == 'Not placed yet', _status(page, 'Kettle plug'))
        _button(_row(page, 'Kettle plug'), 'Pick a spot').click()
        labels = _choices(page)
        check('On a wall' in labels and 'On the ceiling' in labels, ('the surfaces are offered', labels))
        anchors = [t for t in labels if t not in ('On a wall', 'On the ceiling')]
        check(len(anchors) == 1, ('only the free switch spot is offered: not the occupied one, not the light spots', labels))
        before = _store()
        _choose(page, anchors[0])
        ops = _committed(page, posted, before)
        op = ops[0]
        check(isinstance(op, dict) and op.get('op') == 'place_device' and op.get('device') == 'dev-k-kettle'
              and op.get('anchor') == SWITCH_2, ('the free spot takes the device', op))
        model = H.model()
        check((_anchor(model, SWITCH_2) or {}).get('device') == 'dev-k-kettle', _anchor(model, SWITCH_2))
        check(len(_placements(model, 'dev-k-kettle')) == 1, _placements(model, 'dev-k-kettle'))
        check(_wait(page, lambda: _status(page, 'Kettle plug') == 'Placed'), ('the row says Placed', _status(page, 'Kettle plug')))
        _no_errors(s)


def scenario_drag_a_device_onto_a_wall():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _kitchen(page, 'wall')
        before = _store()
        _drag_row_to(page, 'Counter lamp', DROP)
        ops = _committed(page, posted, before)
        op = ops[0]
        check(isinstance(op, dict) and op.get('op') == 'place_device' and op.get('device') == 'dev-k-lamp'
              and op.get('building') == POOL and 'anchor' not in op, ('a drop on a wall posts place_device with a host', op))
        check(_wall_host(op, NORTH_IN, 'right', DROP[0], DROP[2]), ('the wall under the drop, the Kitchen side, at the drop point', op))
        placed = _placements(H.model(), 'dev-k-lamp')
        check(len(placed) == 1 and placed[0][0] == 'host' and placed[0][1] == POOL, ('stored once, on the wall', placed))
        check(placed[0][2].get('host') == op.get('host'), ('stored where it was posted', placed[0][2], op))
        check(not (placed[0][2].get('src') or {}).get('auto'), ('a person placed it', placed[0][2]))
        check(_wait(page, lambda: _status(page, 'Counter lamp') == 'Placed'), _status(page, 'Counter lamp'))
        _no_errors(s)


def scenario_occupied_anchor_says_so():
    s = _serve()
    if s is None:
        return
    _reset()
    model0 = _facts()
    point = _world(model0, SWITCH_1)
    check(math.dist(point, [0.25, NY - 2.5, 4.0]) < 0.05, ('the switch spot sits on the inside face', point))
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _kitchen(page, 'corner')
        before = _store()
        _drag_row_to(page, 'Kettle plug', tuple(point))
        check(_wait_alert(page) == OCCUPIED, ('the refusal, word for word', _alert(page), posted))
        page.wait_for_timeout(500)
        check(_store() == before, 'a refused placement stores nothing')
        check(all(isinstance(op, dict) and op.get('op') == 'place_device' and op.get('device') == 'dev-k-kettle'
                  and op.get('anchor') == SWITCH_1 for op in posted) and len(posted) <= 1,
              ('at most the one refused place_device on the occupied spot', posted))
        model = H.model()
        check((_anchor(model, SWITCH_1) or {}).get('device') == 'dev-k-coffee', ('the spot keeps its device', _anchor(model, SWITCH_1)))
        check(_placements(model, 'dev-k-kettle') == [], _placements(model, 'dev-k-kettle'))
        _no_errors(s)


def scenario_blink_calls_identify():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        identify = []
        page.on('request', lambda r: r.method == 'POST' and r.url.split('?')[0].endswith('/api/house/ha/identify')
                and identify.append(r.post_data_json))
        _open(page, s)
        _kitchen(page)
        check(_row(page, 'Coffee plug').get_by_role('button', name='Blink', exact=True).count() == 0,
              'only lights can blink: a switch row has no Blink')
        _button(_row(page, 'Ceiling light'), 'Blink').click()
        check(_wait(page, lambda: len(FAKE.calls_on('light.ceiling_light')) >= 1),
              ('Blink reaches Home Assistant', FAKE.calls, identify))
        calls = FAKE.calls_on('light.ceiling_light')
        check(len(calls) == 1 and calls[0][:2] == ('light', 'turn_on') and calls[0][2].get('flash') == 'short',
              ('light.turn_on with flash short', calls))
        check(identify and (identify[0] or {}).get('device_id') == 'dev-k-ceiling', ('the identify route names the device', identify))
        check(_alert(page) is None, ('a good blink says nothing', _alert(page)))

        # A failed blink says so, word for word.
        page.route('**/api/house/ha/identify', lambda route: route.fulfill(
            status=502, content_type='application/json', body='{"detail": "upstream"}'))
        _button(_row(page, 'Pendant'), 'Blink').click()
        check(_wait_alert(page) == BLINK_FAILED, ('the blink failure copy', _alert(page)))
        check(FAKE.calls_on('light.pendant') == [], FAKE.calls)
        _no_errors(s)


def scenario_escape_cancels_an_armed_placement():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _kitchen(page, 'wall')
        _button(_row(page, 'Pendant'), 'Pick a spot').click()
        _choices(page)
        _choose(page, 'On a wall')
        page.wait_for_selector('#cc-choice-modal', state='hidden', timeout=5000)
        before = _store()
        H.press(page, 'Escape')
        H.click_world(page, *ARMED, POOL)
        page.wait_for_timeout(1500)
        check([op for op in posted if (op or {}).get('op') == 'place_device'] == [],
              ('Escape disarms: the next wall click places nothing', posted))
        check(_store() == before and _placements(H.model(), 'dev-k-pendant') == [], 'nothing is stored')

        # Armed again, the next click on the wall places the device there.
        del posted[:]
        page.evaluate('([p, b]) => window.__editor.clickPiece(p, b)', [KITCHEN, POOL])
        H.settle(page)
        if H.card_title(page) != 'Kitchen':
            _kitchen(page)
        H.look_at(page, POOL, WALL_EYE, WALL_TARGET)
        _button(_row(page, 'Pendant'), 'Pick a spot').click()
        _choices(page)
        _choose(page, 'On a wall')
        page.wait_for_selector('#cc-choice-modal', state='hidden', timeout=5000)
        before = _store()
        H.click_world(page, *ARMED, POOL)
        ops = _committed(page, posted, before)
        op = ops[0]
        check(isinstance(op, dict) and op.get('op') == 'place_device' and op.get('device') == 'dev-k-pendant'
              and op.get('building') == POOL, ('the armed click posts place_device', op))
        check(_wall_host(op, NORTH_IN, 'right', ARMED[0], ARMED[2]), ('on the clicked wall, at the click', op))
        check(len(_placements(H.model(), 'dev-k-pendant')) == 1, _placements(H.model(), 'dev-k-pendant'))
        _no_errors(s)


def scenario_anchor_card_removes_its_device():
    # Beyond the brief's list: the hand path for unplace_device (Task 5's cards.js
    # line: an anchor card shows its device with Remove).
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _kitchen(page)
        page.evaluate('([p, b]) => window.__editor.clickPiece(p, b)', [SWITCH_1, POOL])
        sel = _selection(page, _is(None, SWITCH_1))
        check(_is(None, SWITCH_1)(sel), ('the switch spot is selected', sel))
        check('Coffee plug' in _card_text(page), ('the anchor card names its device', _card_text(page)))
        remove = page.locator('#piece-card').get_by_role('button', name='Remove', exact=True)
        check(remove.count() == 1, ('one Remove button', _card_text(page)))
        before = _store()
        remove.click()
        ops = _committed(page, posted, before)
        check(isinstance(ops[0], dict) and ops[0].get('op') == 'unplace_device' and ops[0].get('device') == 'dev-k-coffee',
              ('Remove posts unplace_device', ops))
        check(not (_anchor(H.model(), SWITCH_1) or {}).get('device'), _anchor(H.model(), SWITCH_1))
        check(_placements(H.model(), 'dev-k-coffee') == [], _placements(H.model(), 'dev-k-coffee'))
        _no_errors(s)


def scenario_a_carried_row_says_where_to_drop():
    # Browser fix round: a row carried over the scene says what a drop does, the
    # note never blocks a drop beneath it, and Escape puts the row down unplaced.
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _kitchen(page, 'wall')
        row = _row(page, 'Counter lamp')
        box = row.bounding_box()
        sx, sy = H.screen_of_world(page, *DROP, POOL)
        x0, y0 = box['x'] + 12, box['y'] + box['height'] / 2
        page.mouse.move(x0, y0)
        page.mouse.down()
        page.mouse.move(x0 - 20, y0 + 6, steps=3)
        page.mouse.move(sx, sy, steps=10)
        H.settle(page)
        note = page.locator('#device-tools')
        check(note.is_visible(), 'a carried row shows the placement note')
        text = ' '.join(page.inner_text('#device-note').split())
        check(text == 'Drop Counter lamp on a wall, the floor, the ceiling or a spot. Escape cancels.', text)
        nb = note.bounding_box()
        under = page.evaluate("""([x, y]) => document.elementFromPoint(x, y) === window.__twin.renderer3.domElement""",
                              [nb['x'] + nb['width'] / 2, nb['y'] + nb['height'] / 2])
        check(under, 'the note lets a drop under it reach the scene')
        before = _store()
        H.press(page, 'Escape')
        check(not note.is_visible(), 'Escape puts the row down and hides the note')
        page.mouse.up()
        page.wait_for_timeout(1000)
        check(posted == [] and _store() == before, ('a cancelled carry places nothing', posted))
        check(_status(page, 'Counter lamp') == 'Not placed yet', _status(page, 'Counter lamp'))
        _no_errors(s)


SCENARIOS = [
    scenario_count_note_shows,
    scenario_pick_a_spot_on_an_anchor,
    scenario_drag_a_device_onto_a_wall,
    scenario_occupied_anchor_says_so,
    scenario_blink_calls_identify,
    scenario_escape_cancels_an_armed_placement,
    scenario_anchor_card_removes_its_device,
    scenario_a_carried_row_says_where_to_drop,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
