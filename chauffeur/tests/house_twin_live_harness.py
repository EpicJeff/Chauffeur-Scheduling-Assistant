"""Shared harness for the 3D house's live layer in real Chromium (piece 3 Tasks 6
and 7 of docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; briefs
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-6-brief.md and task-7-brief.md).

Imported by tests/test_house_twin_live_markers.py (Task 6) and
tests/test_house_twin_live_rooms.py (Task 7); never run on its own.

The house. The household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round, auth enforcement ON). Before the push the
pool house's rooms are named: 'Pool Lounge' -> 'Kitchen', the 17.75-24.33 x
12.17-18.67 room -> 'Hall', 'CHANGING' -> 'Changing'. Every scenario puts the
seeded model back (reset()) with the three rooms linked to the Home Assistant
areas kitchen, hall and changing, and these placements (pool-house local feet;
the Kitchen's bounds are x 0-31, y 0-17.33, so a floor host's u, v map to
x = 31 u, y = 17.33 v):

    Ceiling light   anchor:live-ceiling, ceiling of the Kitchen u .3 v .3  -> (9.3, 5.2) at 10 ft
    Counter lamp    floor u .4 v .3   -> (12.4, 5.2)
    Coffee plug     floor u .6 v .3   -> (18.6, 5.2)
    Kitchen temp    floor u .8 v .3   -> (24.8, 5.2)
    Back door lock  floor u .3 v .6   -> (9.3, 10.4)
    Garage door     floor u .4 v .6   -> (12.4, 10.4)
    Thermostat      floor u .6 v .6   -> (18.6, 10.4)
    Smoke alarm     floor u .8 v .6   -> (24.8, 10.4)
    Ceiling fan     floor u .3 v .85  -> (9.3, 14.7)
    Pendant         not placed (its auto spot is the route's)
    Changing light  floor of Changing u .5 v .5
    Hall light      floor of Hall u .5 v .5

Home Assistant is faked in-process (tests/house_ha_fake.py, extended here so
lock, cover, brightness and setpoint services change the fake's state the way
Home Assistant would). Lights: Ceiling light off; Counter lamp on at 128;
Pendant on at 255; Changing light on at 153 tinted rgb (0, 0, 255); Hall light off.

The session. A wall panel: a panel device token in localStorage
('chauffeur_device_token'), the way a paired panel holds it; nav.html's fetch
wrapper sends it as X-Device-Token, so control_rules sees the place 'panel'.
The household grid is the default (panel: lights, switches, climate yes;
locks and garage no) unless a scenario sets it.

The camera. aim_kitchen() shows the pool house's ground floor
(view.setView('pool-house:L1')) from 50 ft straight above the Kitchen's
middle, local (15.5, 9): on a 1400 x 1000 viewport that is about 29 px per
foot at the floor. That counts as zoomed in: markers stand alone, not merged.

Hooks the live layer must give under ?test=1 (window.__twin.live): see the
task 6/7 tests report for the full list.
"""
import copy
import io
import json
import logging
import math
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_twin_live_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402
import house_ha_fake  # noqa: E402
from live_app import goto_retry  # noqa: E402

check = H.check
GPU_ARGS = H.GPU_ARGS
FT = H.FT
POOL = 'pool-house'
FLOOR = 'pool-house:L1'
KITCHEN = 'room:5d7de10ca48340ae85c407d22337c6f7'
HALL = 'room:f94386f3da524031b4530a0847d7bc75'
CHANGING = 'room:aa3a66806205434ca794927a6d66dd22'
CEILING_ANCHOR = 'anchor:live-ceiling'

UNREACHABLE = 'Home Assistant is not reachable.'
PANEL_NO_LIGHTS = 'The household does not allow lights control from this place.'
WHO = "Who's asking?"

AIM_AT = (15.5, 9.0)
AIM_HEIGHT = 50.0

DEVICES = [
    # id, name, area, entity, state, attributes, placement
    ('dev-k-ceiling', 'Ceiling light', 'kitchen', 'light.ceiling_light', 'off',
     {'supported_features': 40, 'supported_color_modes': ['brightness'], 'brightness': None}, ('anchor', None)),
    ('dev-k-lamp', 'Counter lamp', 'kitchen', 'light.counter_lamp', 'on',
     {'brightness': 128, 'supported_color_modes': ['brightness'], 'color_mode': 'brightness'}, ('floor', KITCHEN, .4, .3)),
    ('dev-k-coffee', 'Coffee plug', 'kitchen', 'switch.coffee_plug', 'off', {}, ('floor', KITCHEN, .6, .3)),
    ('dev-k-temp', 'Kitchen temperature', 'kitchen', 'sensor.kitchen_temperature', '71.2',
     {'unit_of_measurement': '°F', 'device_class': 'temperature'}, ('floor', KITCHEN, .8, .3)),
    ('dev-back-lock', 'Back door lock', 'kitchen', 'lock.back_door', 'locked', {}, ('floor', KITCHEN, .3, .6)),
    ('dev-garage', 'Garage door', 'kitchen', 'cover.garage_door', 'closed',
     {'device_class': 'garage'}, ('floor', KITCHEN, .4, .6)),
    ('dev-k-thermo', 'Thermostat', 'kitchen', 'climate.kitchen', 'heat',
     {'current_temperature': 70, 'temperature': 68, 'min_temp': 45, 'max_temp': 95, 'target_temp_step': 1,
      'hvac_modes': ['off', 'heat', 'cool'], 'hvac_action': 'idle'}, ('floor', KITCHEN, .6, .6)),
    ('dev-k-smoke', 'Smoke alarm', 'kitchen', 'binary_sensor.kitchen_smoke', 'off',
     {'device_class': 'smoke'}, ('floor', KITCHEN, .8, .6)),
    ('dev-k-fan', 'Ceiling fan', 'kitchen', 'fan.kitchen_fan', 'off', {}, ('floor', KITCHEN, .3, .85)),
    ('dev-k-pendant', 'Pendant', 'kitchen', 'light.pendant', 'on',
     {'brightness': 255, 'supported_color_modes': ['brightness'], 'color_mode': 'brightness'}, None),
    ('dev-changing-light', 'Changing light', 'changing', 'light.changing_light', 'on',
     {'brightness': 153, 'rgb_color': [0, 0, 255], 'color_mode': 'rgb', 'supported_color_modes': ['rgb']},
     ('floor', CHANGING, .5, .5)),
    ('dev-hall-light', 'Hall light', 'hall', 'light.hall_light', 'off',
     {'supported_color_modes': ['brightness']}, ('floor', HALL, .5, .5)),
]
NAMES = {d[0]: d[1] for d in DEVICES}
ENTITY = {d[0]: d[3] for d in DEVICES}
KITCHEN_DEVICES = [d[0] for d in DEVICES if d[2] == 'kitchen']


class LiveFakeHA(house_ha_fake.FakeHA):
    """house_ha_fake.FakeHA, plus the services the live layer sends.

    `frozen` holds entity ids the house ignores (the call is recorded, the state
    does not move): a light that never reached the state somebody asked for."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.frozen = set()
        self.initial = copy.deepcopy(self.states)

    def reset(self):
        self.available = True
        self.fail_calls = False
        self.frozen = set()
        del self.calls[:]
        self.states.clear()
        self.states.update(copy.deepcopy(self.initial))

    def install(self):
        super().install()
        from services import ha_api
        recorded = ha_api.call_service
        fake = self

        def call(domain, service, data=None, **kw):
            data = copy.deepcopy(data or {})
            ids = data.get('entity_id')
            ids = [ids] if isinstance(ids, str) else list(ids or [])
            before = {eid: copy.deepcopy(fake.states.get(eid)) for eid in ids}
            out = recorded(domain, service, data, **kw)
            for eid in ids:
                row = fake.states.get(eid)
                if row is None:
                    continue
                if eid in fake.frozen:
                    fake.states[eid] = before[eid]
                    continue
                attrs = row['attributes']
                if service == 'lock':
                    row['state'] = 'locked'
                elif service == 'unlock':
                    row['state'] = 'unlocked'
                elif service == 'open_cover':
                    row['state'] = 'open'
                elif service == 'close_cover':
                    row['state'] = 'closed'
                elif service == 'set_temperature' and data.get('temperature') is not None:
                    attrs['temperature'] = data['temperature']
                if domain == 'light' and row['state'] == 'on':
                    if data.get('brightness_pct') is not None:
                        attrs['brightness'] = round(float(data['brightness_pct']) * 255 / 100)
                    elif not attrs.get('brightness'):
                        attrs['brightness'] = 255
            return out
        ha_api.call_service = call
        return self


FAKE = LiveFakeHA(
    areas=[{'area_id': 'kitchen', 'name': 'Kitchen', 'floor_id': 'ground'},
           {'area_id': 'hall', 'name': 'Hall', 'floor_id': 'ground'},
           {'area_id': 'changing', 'name': 'Changing', 'floor_id': 'ground'}],
    floors=[{'floor_id': 'ground', 'name': 'Ground floor', 'level': 0}],
    devices=[{'id': d[0], 'name': d[1], 'area_id': d[2], 'entities': [(d[3], d[4], d[5])]} for d in DEVICES],
).install()

SEED = {}
STATE = {}


# --- seed and serve ------------------------------------------------------------------

def _names(plan):
    rooms = H.building(plan, POOL)['rooms']
    for rid, name in ((KITCHEN, 'Kitchen'), (HALL, 'Hall'), (CHANGING, 'Changing')):
        room = next(r for r in rooms if r['id'] == rid)
        room['name'] = name
        room['ha_area'] = ''
    return plan


def serve():
    served = H.serve(_names)
    if served is not None and 'model' not in SEED:
        from services import storage
        SEED['model'] = copy.deepcopy(H.model())
        STATE['panel'] = storage.enrol_device_token('panel-live', 'Kitchen panel', by_member=H.PARENT['id'])
    return served


def grid(panel=None, proof=None, people=None):
    """The household grid: the defaults with the given cells changed."""
    from services import control_rules as cr
    rules = cr.default_rules({})
    rules['places']['panel'].update(panel or {})
    rules['proof'].update(proof or {})
    for role, cells in (people or {}).items():
        rules['people'][role].update(cells)
    return rules


def set_grid(rules):
    from services import storage
    storage.patch_settings({'ha_control': rules})


def _linked(model):
    b = H.building(model, POOL)
    for room in b['rooms']:
        room['ha_area'] = {KITCHEN: 'kitchen', HALL: 'hall', CHANGING: 'changing'}.get(room['id'], '')
    b['anchors'] = [a for a in b.get('anchors') or [] if a['id'] != CEILING_ANCHOR] + [
        {'id': CEILING_ANCHOR, 'kind': 'light', 'host': {'ceiling': KITCHEN, 'u': 0.3, 'v': 0.3},
         'offset': 0, 'device': 'dev-k-ceiling'}]
    b['devices'] = []
    for did, _name, _area, _eid, _state, _attrs, place in DEVICES:
        if place and place[0] == 'floor':
            b['devices'].append({'id': f'device:{did}', 'device': did,
                                 'host': {'floor': place[1], 'u': place[2], 'v': place[3]},
                                 'offset': 0, 'src': {'person': True}})


def reset(rules=None):
    """The seeded house, three rooms linked, the placements; HA connected; the grid set."""
    from services import twin_store
    FAKE.reset()
    set_grid(rules or grid())

    def mutate(_before):
        model = copy.deepcopy(SEED['model'])
        _linked(model)
        return model
    twin_store.update_model(mutate, 'edit', note='twin live reset')


def live_route():
    """GET /api/house/live as the panel (the layout the page should draw)."""
    import urllib.request
    served = serve()
    req = urllib.request.Request(served.url('api/house/live'), headers={'X-Device-Token': STATE['panel']})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def facts():
    """The seed is what the scenarios assume; the route places every device."""
    model = H.model()
    b = H.building(model, POOL)
    rooms = {r['id']: r for r in b['rooms']}
    check(rooms[KITCHEN]['name'] == 'Kitchen' and rooms[KITCHEN]['ha_area'] == 'kitchen', rooms[KITCHEN])
    check(rooms[HALL]['ha_area'] == 'hall' and rooms[CHANGING]['ha_area'] == 'changing', (rooms[HALL], rooms[CHANGING]))
    body = live_route()
    check(body.get('available') is True, ('the live route sees Home Assistant', body))
    ids = {m['device_id'] for m in body['markers']}
    check(ids == set(NAMES), ('one marker per device in the route', sorted(ids)))
    return body


# --- the page ------------------------------------------------------------------------

PANEL_SCRIPT = (
    "if (location.protocol.startsWith('http')) { try {"
    "localStorage.setItem('chauffeur_device_token', %s);"
    "localStorage.setItem('chauffeur_device_id', 'panel-live');"
    "} catch (e) {} }")


def as_panel(page):
    page.add_init_script(PANEL_SCRIPT % json.dumps(STATE['panel']))


def record(page):
    """Every request the page makes: (method, url, body or None), in order."""
    seen = []

    def on_request(request):
        body = None
        if request.method == 'POST':
            try:
                body = request.post_data_json
            except Exception:
                body = None
        seen.append((request.method, request.url, body))
    page.on('request', on_request)
    return seen


def service_posts(seen):
    return [body for method, url, body in seen
            if method == 'POST' and url.split('?')[0].endswith('/api/ha/card/service')]


def open_twin(page, served, query='tier=low&test=1&panel=true', live=True):
    """Open /house/twin as the panel; wait for the house, then (live=True) for the live layer."""
    as_panel(page)
    goto_retry(page, served.url(f'house/twin?{query}'))
    page.wait_for_function('() => window.__twin && window.__twin.ready === true', timeout=90000)
    H.settle(page)
    if not live:
        return
    try:
        page.wait_for_function('() => !!(window.__twin && window.__twin.live)', timeout=20000)
    except Exception:
        raise AssertionError('window.__twin.live is missing: twin_view mounts mountLive(view, {api}) there under ?test=1 '
                             'when api/house/live says available')
    wait_markers(page)


def markers(page):
    return page.evaluate('() => window.__twin.live.markers()')


def marker(page, device_id):
    rows = [m for m in markers(page) if m.get('device_id') == device_id]
    check(len(rows) == 1, ('one marker per device in live.markers()', device_id, rows))
    return rows[0]


def wait_markers(page, timeout=20.0):
    """Every device has a marker and the first state answer is drawn."""
    deadline = time.time() + timeout
    rows = []
    while time.time() < deadline:
        rows = markers(page)
        looks = {m.get('device_id'): m.get('look') for m in rows}
        if set(looks) >= set(NAMES) and looks.get('dev-k-lamp') == 'on' and looks.get('dev-k-ceiling') == 'off':
            return rows
        page.wait_for_timeout(200)
    raise AssertionError(('every device has a marker drawn with its state', [(m.get('device_id'), m.get('look')) for m in rows]))


def wait_look(page, device_id, look, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker(page, device_id).get('look') == look:
            return
        page.wait_for_timeout(200)
    raise AssertionError(('the marker shows the confirmed state', device_id, look, marker(page, device_id)))


def refresh(page):
    page.evaluate('async () => { await window.__twin.live.refresh(); }')
    H.settle(page)


def aim_kitchen(page):
    """The pool house's ground floor from 50 ft above the Kitchen's middle."""
    page.evaluate("""([bid, key, x, y, h]) => {
        const v = window.__twin, b = v.plan.buildings.find(item => item.id === bid);
        const a = (b.rotation || 0) * Math.PI / 180;
        const wx = Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0);
        const wy = Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0);
        v.setView(key);
        v.aim([wx, wy - 0.5, h], [wx, wy, 0]);
    }""", [POOL, FLOOR, AIM_AT[0], AIM_AT[1], AIM_HEIGHT])
    H.settle(page, 3)


def lot_of_local(page, x, y):
    return page.evaluate("""([bid, x, y]) => {
        const b = window.__twin.plan.buildings.find(item => item.id === bid);
        const a = (b.rotation || 0) * Math.PI / 180;
        return [Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0),
                Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0)];
    }""", [POOL, x, y])


def screen_of_lot(page, at):
    """Client pixel of a lot point [x, y, z] in feet (the ground is flat at 0)."""
    return page.evaluate("""([at, FT]) => {
        const v = window.__twin, camera = v.camera;
        camera.updateMatrixWorld(true);
        const p = camera.position.clone().set(at[0] * FT, at[2] * FT, -at[1] * FT).project(camera);
        const r = v.renderer3.domElement.getBoundingClientRect();
        return [r.left + (p.x + 1) * r.width / 2, r.top + (1 - p.y) * r.height / 2];
    }""", [list(at), FT])


SPRITES_JS = """(id) => {
    const out = [];
    window.__twin.scene.traverse(o => { if (o.isSprite && o.userData && o.userData.deviceId === id) out.push(o); });
    const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
    const camera = window.__twin.camera; camera.updateMatrixWorld(true);
    const r = window.__twin.renderer3.domElement.getBoundingClientRect();
    return out.map(o => {
        o.updateMatrixWorld(true);
        const w = o.getWorldPosition(o.position.clone()), p = w.clone().project(camera);
        const m = o.material || {}, c = m.color || {r: 1, g: 1, b: 1};
        return {screen: [r.left + (p.x + 1) * r.width / 2, r.top + (1 - p.y) * r.height / 2],
                world: [w.x, w.y, w.z], visible: shown(o), opacity: m.opacity, transparent: !!m.transparent,
                color: Math.max(c.r, c.g, c.b)};
    });
}"""


def sprites(page, device_id):
    return page.evaluate(SPRITES_JS, device_id)


def sprite(page, device_id):
    rows = sprites(page, device_id)
    check(len(rows) == 1, ('one THREE.Sprite with userData.deviceId per marker', device_id, rows))
    return rows[0]


def drawn_dim(row):
    """A dimmed sprite: opacity at most 0.6, or its colour at most 0.6 of full."""
    return (row.get('opacity') is not None and row['opacity'] <= 0.6) or row.get('color', 1) <= 0.6


def drawn_full(row):
    return (row.get('opacity') is None or row['opacity'] >= 0.9) and row.get('color', 1) >= 0.9


def on_canvas(page, sx, sy):
    hit = page.evaluate("""([x, y]) => {
        const node = document.elementFromPoint(x, y), canvas = window.__twin.renderer3.domElement;
        return node === canvas ? null : (node ? node.tagName + '#' + node.id + '.' + node.className : 'nothing');
    }""", [sx, sy])
    check(hit is None, f'the point ({sx:.0f}, {sy:.0f}) is covered by {hit}, not the scene')


def tap_marker(page, device_id, others_clear=True):
    """A real mouse click on the marker's sprite; returns the client pixel."""
    row = sprite(page, device_id)
    check(row['visible'], ('the marker is drawn at this camera (not merged into a room badge)', device_id, row))
    sx, sy = row['screen']
    if others_clear:
        for other in NAMES:
            if other == device_id:
                continue
            for o in sprites(page, other):
                if o['visible']:
                    check(math.dist(o['screen'], (sx, sy)) > 30,
                          ('fixture: another marker sits on the one tapped', device_id, other, o['screen'], (sx, sy)))
    on_canvas(page, sx, sy)
    page.mouse.click(sx, sy)
    H.settle(page)
    return sx, sy


def tap_local_floor(page, x, y):
    """A real mouse click on the pool house's ground floor at local (x, y)."""
    lot = lot_of_local(page, x, y)
    sx, sy = screen_of_lot(page, [lot[0], lot[1], 0.0])
    on_canvas(page, sx, sy)
    page.mouse.click(sx, sy)
    H.settle(page)
    return sx, sy


def alert(page):
    if not page.locator('#cc-alert-modal').is_visible():
        return None
    return page.inner_text('#cc-alert-message').strip()


def close_alert(page):
    if page.locator('#cc-alert-modal').is_visible():
        page.evaluate('() => window.closeGlobalAlert && window.closeGlobalAlert()')


def wait_for(page, cond, seconds=8.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cond():
            return True
        page.wait_for_timeout(100)
    return cond()


def pixel(page, sx, sy, r=3):
    """Mean RGB of a small square of the page around a client pixel (the composited screen)."""
    from PIL import Image
    png = page.screenshot(clip={'x': sx - r, 'y': sy - r, 'width': 2 * r + 1, 'height': 2 * r + 1})
    img = Image.open(io.BytesIO(png)).convert('RGB')
    px = list(img.getdata())
    return [sum(p[i] for p in px) / len(px) for i in range(3)]


def no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


class LogWatch(logging.Handler):
    """Every ERROR the app's own code logs while the block runs (uvicorn's own records left out)."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        if not record.name.startswith('uvicorn'):
            self.records.append(record)

    def __enter__(self):
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *exc):
        logging.getLogger().removeHandler(self)


run = H.run
