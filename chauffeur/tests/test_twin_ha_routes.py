"""The house's Home Assistant link and live layer, over HTTP (piece 3 Task 3 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; brief
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-3-brief.md).

Routes under test (real FastAPI app, auth enforcement ON, a fake Home
Assistant patched onto ha_api, the model seeded in the twin store):
- GET  /api/house/ha/link      (parents)  rooms, suggestions, unlinked areas, devices
- GET  /api/house/live         (wall)     markers in lot feet, rooms, `offered` per caller
- POST /api/house/ha/identify  (parents)  Blink: flash when the light has the flash bit,
                                          else a toggle restored after a short delay

Position convention assumed for `at` and `polygon_world`: a building-local
point (x, y) turns counter-clockwise by the building's `rotation` degrees about
the building origin, then adds `position`. That is the generator's own
placement (static/twin/twin_generator.js: group.position = (px, base, -py),
rotation.y = degrees, with lot y = -z, which is a counter-clockwise turn in
the lot's x/y plane).

The every-route-has-a-rule check lives in tests/test_auth.py (it walks the
app's routes against services/auth.RULES); this file also pins the tier of
the three new rules directly.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_ha_routes.py
"""
import copy
import logging
import math
import os
import shutil
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_ha_routes_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import auth, control_rules as cr, ha_api, storage  # noqa: E402
from services import twin_model, twin_model_bridge  # noqa: E402
from services import twin_model_hosts as hosts  # noqa: E402
from services import twin_store as ts  # noqa: E402

_real_settings = storage.get_settings

LINK, LIVE, IDENTIFY = '/api/house/ha/link', '/api/house/live', '/api/house/ha/identify'
GONE_COPY = "This room's Home Assistant area is gone; pick another."
NON_LIGHT_COPY = 'Only lights can blink.'
FLASH_BIT = 8


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- fake Home Assistant

def _state(eid, st='off', **attrs):
    return {'entity_id': eid, 'state': st, 'attributes': {'friendly_name': eid.split('.', 1)[1].replace('_', ' ').title(), **attrs}}


class FakeHA:
    """Areas: kitchen (Kitchen), dining_area (Dining), patio (Patio). One floor.
    Kitchen holds a flashing light, a plain lamp and a lock; the patio a light."""

    def __init__(self, available=True):
        self.available = available
        self.calls = []
        self.areas = [
            {'area_id': 'kitchen', 'name': 'Kitchen', 'floor_id': 'ground'},
            {'area_id': 'dining_area', 'name': 'Dining', 'floor_id': 'ground'},
            {'area_id': 'patio', 'name': 'Patio', 'floor_id': None},
        ]
        self.floors = [{'floor_id': 'ground', 'name': 'Ground floor', 'level': 0}]
        self.devices = [
            {'id': 'dev-k-light', 'name': 'Kitchen ceiling', 'area_id': 'kitchen'},
            {'id': 'dev-k-lamp', 'name': 'Kitchen lamp', 'area_id': 'kitchen'},
            {'id': 'dev-back-lock', 'name': 'Back door lock', 'area_id': 'kitchen'},
            {'id': 'dev-patio-light', 'name': 'Patio light', 'area_id': 'patio'},
        ]
        self.entities = {   # entity id -> device id
            'light.kitchen_ceiling': 'dev-k-light', 'light.kitchen_lamp': 'dev-k-lamp',
            'lock.back_door': 'dev-back-lock', 'light.patio': 'dev-patio-light',
        }
        self.states = {s['entity_id']: s for s in (
            _state('light.kitchen_ceiling', 'off', supported_features=FLASH_BIT | 32),
            _state('light.kitchen_lamp', 'off', supported_features=0),
            _state('lock.back_door', 'locked'),
            _state('light.patio', 'off', supported_features=FLASH_BIT),
        )}

    def move_device(self, device_id, area_id):
        next(d for d in self.devices if d['id'] == device_id)['area_id'] = area_id

    def delete_area(self, area_id):
        self.areas = [a for a in self.areas if a['area_id'] != area_id]

    # --- the ha_api surface the house reads
    def area_map(self, ttl=60):
        if not self.available:
            return []
        by_device = {d['id']: d for d in self.devices}
        out = []
        for a in self.areas:
            out.append({'id': a['area_id'], 'name': a['name'],
                        'entities': [e for e, d in self.entities.items() if by_device[d]['area_id'] == a['area_id']]})
        return out

    def install(self):
        fake, names = self, ('mode', 'is_available', 'get_states', 'get_state', 'call_service', 'get_area_map',
                             'get_entity_registry', 'get_device_registry', 'get_area_registry', 'ws_command',
                             'get_exposed', 'get_floor_registry')
        self.orig = {n: getattr(ha_api, n, None) for n in names}
        up = self.available
        ha_api.mode = lambda: 'direct' if up else 'unconfigured'
        ha_api.is_available = lambda: up
        ha_api.get_states = lambda ttl=5: copy.deepcopy(list(fake.states.values())) if up else []
        ha_api.get_state = lambda eid: copy.deepcopy(fake.states.get(eid)) if up else None
        ha_api.get_area_map = self.area_map
        ha_api.get_entity_registry = lambda ttl=300: (
            [{'entity_id': e, 'device_id': d, 'area_id': None, 'name': None} for e, d in fake.entities.items()] if up else [])
        ha_api.get_device_registry = lambda ttl=300: (
            [{'id': d['id'], 'name': d['name'], 'name_by_user': None, 'manufacturer': 'Acme', 'model': 'X',
              'area_id': d['area_id']} for d in fake.devices] if up else [])
        ha_api.get_area_registry = lambda ttl=300: (
            [{'area_id': a['area_id'], 'name': a['name'], 'floor_id': a['floor_id'], 'picture': None, 'icon': None}
             for a in fake.areas] if up else [])
        ha_api.get_floor_registry = lambda ttl=300: copy.deepcopy(fake.floors) if up else []
        ha_api.get_exposed = lambda ttl=60: {}

        def ws(command, timeout=8, **fields):
            if not up:
                return None
            if command == 'config/area_registry/list':
                return [dict(a) for a in fake.areas]
            if command == 'config/floor_registry/list':
                return copy.deepcopy(fake.floors)
            return None
        ha_api.ws_command = ws

        def call(domain, service, data=None, **kw):
            fake.calls.append((domain, service, copy.deepcopy(data)))
            ids = (data or {}).get('entity_id')
            for eid in ([ids] if isinstance(ids, str) else ids or []):
                row = fake.states.get(eid)
                if row is None:
                    continue
                if service == 'turn_on':
                    row['state'] = 'on'
                elif service == 'turn_off':
                    row['state'] = 'off'
                elif service == 'toggle':
                    row['state'] = 'off' if row['state'] == 'on' else 'on'
            return []
        ha_api.call_service = call
        return self

    def uninstall(self):
        for n, fn in self.orig.items():
            if fn is None:
                if hasattr(ha_api, n):
                    delattr(ha_api, n)
            else:
                setattr(ha_api, n, fn)

    def calls_on(self, eid):
        out = []
        for domain, service, data in self.calls:
            ids = (data or {}).get('entity_id')
            ids = [ids] if isinstance(ids, str) else list(ids or [])
            if eid in ids:
                out.append((domain, service, data))
        return out


# ---------------------------------------------------------------- the model

def _wall(wid, a, b, exterior=True):
    return {'id': wid, 'level': 'L1', 'joints': [a, b], 'kind': 'solid',
            'thickness': 0.5 if exterior else 0.33, 'exterior': exterior, 'height': 9}


def _house(position=(100, 50), rotation=90):
    """B1: Kitchen x 0-12, Dining x 12-20, both y 0-10; ceiling 9 ft."""
    joints = [('j1', 0, 0), ('jm0', 12, 0), ('j2', 20, 0), ('j3', 20, 10), ('jm1', 12, 10), ('j4', 0, 10)]
    building = {
        'id': 'B1', 'name': 'House', 'position': list(position), 'rotation': rotation, 'base': 0,
        'materials': {'siding': {'id': 'board_and_batten', 'color': '#c9c4b8'}, 'trim': {'id': 'painted_trim', 'color': '#f2efe6'}},
        'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9}],
        'joints': [{'id': i, 'level': 'L1', 'at': [x, y]} for i, x, y in joints],
        'walls': [_wall('s1', 'j1', 'jm0'), _wall('s2', 'jm0', 'j2'), _wall('e', 'j2', 'j3'),
                  _wall('n1', 'j3', 'jm1'), _wall('n2', 'jm1', 'j4'), _wall('w', 'j4', 'j1'),
                  _wall('mid', 'jm0', 'jm1', exterior=False)],
        'rooms': [
            {'id': 'kitchen', 'level': 'L1', 'name': 'Kitchen', 'kind': 'room',
             'polygon': [[0, 0], [12, 0], [12, 10], [0, 10]], 'joints': ['j1', 'jm0', 'jm1', 'j4']},
            {'id': 'dining', 'level': 'L1', 'name': 'Dining', 'kind': 'room',
             'polygon': [[12, 0], [20, 0], [20, 10], [12, 10]], 'joints': ['jm0', 'j2', 'j3', 'jm1']},
        ],
        'openings': [], 'anchors': [], 'items': [], 'roofs': [], 'dormers': [], 'extensions': [],
        'stairs': [], 'proposals': [], 'flags': [],
    }
    raw = {'schema': 'chauffeur.twin.plan/3', 'units': 'ft', 'materials': {}, 'buildings': [building], 'site': {}}
    model, _ = twin_model.normalize(raw)
    return model


def seed(kitchen_area='kitchen', dining_area='', anchors=(), devices=(), position=(100, 50), rotation=90):
    """Replace the stored house with the two-room model and the given links and placements."""
    storage.patch_settings({'house_twin': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    model = _house(position, rotation)
    ts.push_round(twin_model_bridge.flatten(model), 'build')

    def mutate(m):
        b = m['buildings'][0]
        for room in b['rooms']:
            room['ha_area'] = {'kitchen': kitchen_area, 'dining': dining_area}[room['id']]
        b['anchors'] = [copy.deepcopy(a) for a in anchors]
        b['devices'] = [copy.deepcopy(d) for d in devices]
        return m
    ts.update_model(mutate)


def ceiling_anchor(aid='a1', device='dev-k-light'):
    return {'id': aid, 'kind': 'light', 'host': {'ceiling': 'kitchen', 'u': 0.5, 'v': 0.5},
            'offset': 0, 'device': device}


def rotate_to_lot(local, position, rotation):
    """Counter-clockwise by `rotation` degrees about the building origin, then translate."""
    r = math.radians(rotation)
    x, y = local[0], local[1]
    return [position[0] + x * math.cos(r) - y * math.sin(r), position[1] + x * math.sin(r) + y * math.cos(r)]


def inside(point, polygon):
    x, y, n, hit = point[0], point[1], len(polygon), False
    for i in range(n):
        (x1, y1), (x2, y2) = polygon[i], polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


# ---------------------------------------------------------------- the app

class Ctx:
    """The fake HA, the people, the client; enter with `with Ctx() as c`."""

    def __init__(self, available=True):
        self.ha = FakeHA(available)
        self.extra = {}

    def __enter__(self):
        from fastapi.testclient import TestClient
        import main
        self.ha.install()
        for mid, role in (('mum', 'parent'), ('kid', 'child'), ('visitor', 'guest')):
            if not storage.get_member(mid):
                storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active'})
        storage.set_member_pin('mum', '4321')
        self.mum = {'X-Member-Token': storage.create_member_token('mum', proof='password', minted_on='personal')}
        self.kid = {'X-Member-Token': storage.create_member_token('kid', proof='pin', minted_on='personal')}
        self.visitor = {'X-Member-Token': storage.create_member_token('visitor', proof='password', minted_on='personal')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')}
        self.patch = patch.object(storage, 'get_settings', side_effect=lambda: {
            **_real_settings(), 'auth_enforce': True, **self.extra})
        self.patch.start()
        self.client = TestClient(main.app)
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        self.ha.uninstall()


class LogWatch(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def __enter__(self):
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *exc):
        logging.getLogger().removeHandler(self)


def marker_for(body, device_id):
    found = [m for m in body['markers'] if m['device_id'] == device_id]
    check(len(found) <= 1, f'one marker per device: {found}')
    return found[0] if found else None


def suggested_area(room):
    value = room.get('suggested')
    return value.get('area_id') if isinstance(value, dict) else value


# ---------------------------------------------------------------- tests

def test_auth_rules_for_the_three_routes():
    check(auth.resolve('GET', LINK) == auth.PARENTS, f'link is parents: {auth.resolve("GET", LINK)}')
    check(auth.resolve('POST', IDENTIFY) == auth.PARENTS, 'identify is parents')
    check(auth.resolve('GET', LIVE) == auth.WALL, f'live is the wall tier: {auth.resolve("GET", LIVE)}')


def test_link_lists_rooms_suggestions_and_unlinked():
    seed(kitchen_area='kitchen', dining_area='', anchors=[ceiling_anchor()])
    with Ctx() as c:
        for headers in (c.kid, c.visitor, c.panel):
            check(c.client.get(LINK, headers=headers).status_code == 403, 'the link is for parents only')
        r = c.client.get(LINK, headers=c.mum)
        check(r.status_code == 200, r.text)
        body = r.json()
        for key in ('available', 'areas', 'floors', 'rooms', 'unlinked', 'devices'):
            check(key in body, f'key {key}: {sorted(body)}')
        check(body['available'] is True, body)
        check({a['area_id'] for a in body['areas']} == {'kitchen', 'dining_area', 'patio'}, body['areas'])
        check([f['floor_id'] for f in body['floors']] == ['ground'], body['floors'])
        rooms = {r['room']: r for r in body['rooms']}
        check(set(rooms) == {'kitchen', 'dining'}, rooms)
        k, d = rooms['kitchen'], rooms['dining']
        for room in (k, d):
            for key in ('building', 'level', 'room', 'name', 'ha_area', 'gone', 'notes'):
                check(key in room, f'room key {key}: {room}')
        check(k['building'] == 'B1' and k['level'] == 'L1' and k['name'] == 'Kitchen', k)
        check(k['ha_area'] == 'kitchen' and isinstance(k['notes'], list), k)
        check(k['gone'] is False and d['gone'] is False, (k, d))
        check(not d['ha_area'], f'the dining room is unlinked: {d}')
        check(suggested_area(d) == 'dining_area', f'Dining is suggested for the dining room: {d}')
        check(not suggested_area(k), f'a linked room has no suggestion: {k}')
        check({u['area_id'] for u in body['unlinked']} >= {'patio'}, body['unlinked'])
        check('kitchen' not in {u['area_id'] for u in body['unlinked']}, 'a linked area is not unlinked')
        check(all(set(u) >= {'area_id', 'name'} for u in body['unlinked']), body['unlinked'])
        devices = {x['device_id']: x for x in body['devices']}
        check(set(devices) == {'dev-k-light', 'dev-k-lamp', 'dev-back-lock', 'dev-patio-light'}, sorted(devices))
        light = devices['dev-k-light']
        for key in ('device_id', 'name', 'kind', 'area_id', 'entity_id', 'placed', 'auto'):
            check(key in light, f'device key {key}: {light}')
        check(light['kind'] == 'light' and light['entity_id'] == 'light.kitchen_ceiling'
              and light['area_id'] == 'kitchen', light)
        check(light['placed'] and light['placed'].get('building') == 'B1' and light['auto'] is None, light)
        lamp = devices['dev-k-lamp']
        check(lamp['placed'] is None and lamp['auto'] and lamp['auto']['room'] == 'kitchen', lamp)
        check(devices['dev-back-lock']['kind'] == 'lock', devices['dev-back-lock'])


def test_link_without_ha():
    seed(kitchen_area='', dining_area='')
    with Ctx(available=False) as c, LogWatch() as log:
        r = c.client.get(LINK, headers=c.mum)
        check(r.status_code == 200, r.text)
        body = r.json()
        check(body['available'] is False, body)
        for key in ('areas', 'floors', 'unlinked', 'devices'):
            check(body[key] == [], f'{key} empty with no HA: {body[key]}')
        check({r['room'] for r in body['rooms']} == {'kitchen', 'dining'}
              and all(r['gone'] is False and r['notes'] == [] for r in body['rooms']), body['rooms'])
        check(log.records == [], f'no error logged: {[r.getMessage() for r in log.records]}')


def test_live_positions_follow_building_rotation():
    anchor = ceiling_anchor()
    seed(anchors=[anchor], position=(100, 50), rotation=90)
    with Ctx() as c:
        r = c.client.get(LIVE, headers=c.panel)
        check(r.status_code == 200, r.text)
        body = r.json()
        check(body['available'] is True and set(body) >= {'available', 'markers', 'rooms'}, sorted(body))
        m = marker_for(body, 'dev-k-light')
        check(m is not None, f'the placed light has a marker: {body["markers"]}')
        for key in ('device_id', 'name', 'kind', 'entity_id', 'entities', 'room', 'building', 'level', 'at',
                    'placed', 'offered'):
            check(key in m, f'marker key {key}: {m}')
        check(m['kind'] == 'light' and m['entity_id'] == 'light.kitchen_ceiling'
              and 'light.kitchen_ceiling' in m['entities'], m)
        check(m['room'] == 'kitchen' and m['building'] == 'B1' and m['level'] == 'L1' and m['placed'] is True, m)
        # The kitchen's ceiling centre is (6, 5) in the building; a quarter turn counter-clockwise puts it at
        # (-5, 6), and the building sits at (100, 50): (95, 56) in lot feet, at the ceiling.
        local = hosts.world_point(_building_now(), anchor['host'], anchor['offset'])
        check(close(local[0], 6) and close(local[1], 5), f'the anchor sits at the room centre: {local}')
        check(len(m['at']) == 3 and close(m['at'][0], 95) and close(m['at'][1], 56), f'rotated, then translated: {m["at"]}')
        check(close(m['at'][2], local[2]), f'height is the anchor height, {local[2]}: {m["at"]}')
        # Rotation 0 and a different position: no turn, just the translation.
        seed(anchors=[anchor], position=(30, 70), rotation=0)
        m = marker_for(c.client.get(LIVE, headers=c.panel).json(), 'dev-k-light')
        check(close(m['at'][0], 36) and close(m['at'][1], 75), f'unrotated: {m["at"]}')
        # 30 degrees: the generator's counter-clockwise turn, computed independently.
        seed(anchors=[anchor], position=(10, 20), rotation=30)
        m = marker_for(c.client.get(LIVE, headers=c.panel).json(), 'dev-k-light')
        want = rotate_to_lot([6, 5], (10, 20), 30)
        check(close(m['at'][0], want[0], 1e-4) and close(m['at'][1], want[1], 1e-4), f'30 degrees: {m["at"]} vs {want}')
        # The rooms carry their outline in lot feet by the same rule.
        body = c.client.get(LIVE, headers=c.panel).json()
        room = next(r for r in body['rooms'] if r['room'] == 'kitchen')
        for key in ('room', 'building', 'level', 'area_id', 'name', 'polygon_world', 'lights'):
            check(key in room, f'room key {key}: {room}')
        corners = sorted((round(p[0], 3), round(p[1], 3)) for p in room['polygon_world'])
        want = sorted((round(p[0], 3), round(p[1], 3)) for p in
                      (rotate_to_lot(q, (10, 20), 30) for q in ([0, 0], [12, 0], [12, 10], [0, 10])))
        check(corners == want, f'polygon_world {corners} vs {want}')
        check(room['area_id'] == 'kitchen' and room['name'] == 'Kitchen', room)
        check(sorted(room['lights']) == ['light.kitchen_ceiling', 'light.kitchen_lamp'], room['lights'])


def test_live_unplaced_devices_take_auto_spots_inside_their_room():
    seed(anchors=[ceiling_anchor()], position=(100, 50), rotation=90)
    with Ctx() as c:
        body = c.client.get(LIVE, headers=c.panel).json()
        lamp = marker_for(body, 'dev-k-lamp')
        check(lamp is not None and lamp['placed'] is False and lamp['room'] == 'kitchen', lamp)
        room = next(r for r in body['rooms'] if r['room'] == 'kitchen')
        check(inside(lamp['at'][:2], room['polygon_world']), f'the auto spot is inside the room: {lamp["at"]}')
        lock = marker_for(body, 'dev-back-lock')
        check(lock is not None and lock['kind'] == 'lock' and lock['placed'] is False, lock)
        check(marker_for(body, 'dev-patio-light') is None, 'a device in an area with no room has no marker')


def test_live_omits_devices_whose_area_is_gone():
    # The room is linked to an area HA no longer has; a placed device HA no longer lists is dropped too.
    seed(kitchen_area='old_area',
         anchors=[ceiling_anchor('a1', 'dev-k-light'), ceiling_anchor('a2', 'dev-vanished')])
    with Ctx() as c, LogWatch() as log:
        r = c.client.get(LIVE, headers=c.panel)
        check(r.status_code == 200, r.text)
        body = r.json()
        check(body['available'] is True, body)
        ids = {m['device_id'] for m in body['markers']}
        check('dev-vanished' not in ids, f'HA no longer lists it: {ids}')
        check(not ids & {'dev-k-lamp', 'dev-back-lock'}, f'auto spots need a live area link: {ids}')
        link = c.client.get(LINK, headers=c.mum)
        check(link.status_code == 200, link.text)
        k = next(x for x in link.json()['rooms'] if x['room'] == 'kitchen')
        check(k['gone'] is True and k['ha_area'] == 'old_area', k)
        check(log.records == [], f'no error logged: {[r.getMessage() for r in log.records]}')
        # Deleting an area the room really used: its devices vanish from the markers, nothing errors.
        seed(kitchen_area='kitchen')
        before = {m['device_id'] for m in c.client.get(LIVE, headers=c.panel).json()['markers']}
        check({'dev-k-light', 'dev-k-lamp', 'dev-back-lock'} <= before, before)
        c.ha.delete_area('kitchen')
        r = c.client.get(LIVE, headers=c.panel)
        check(r.status_code == 200, r.text)
        after = {m['device_id'] for m in r.json()['markers']}
        check(not after & {'dev-k-light', 'dev-k-lamp', 'dev-back-lock'}, f'devices of a deleted area are omitted: {after}')
        check(log.records == [], f'no error logged: {[r.getMessage() for r in log.records]}')


def test_moved_device_keeps_its_placement():
    anchor = ceiling_anchor()
    seed(anchors=[anchor], position=(100, 50), rotation=90)
    with Ctx() as c:
        before = marker_for(c.client.get(LIVE, headers=c.panel).json(), 'dev-k-light')
        check(before and before['placed'] is True, before)
        c.ha.move_device('dev-k-light', 'patio')   # moved to another HA area after it was placed
        body = c.client.get(LIVE, headers=c.panel).json()
        after = marker_for(body, 'dev-k-light')
        check(after is not None, f'the moved light keeps its marker: {[m["device_id"] for m in body["markers"]]}')
        check(after['placed'] is True and all(close(a, b) for a, b in zip(after['at'], before['at'])),
              f'the person\'s placement wins: {before["at"]} -> {after["at"]}')
        check(after['room'] == before['room'] == 'kitchen', after)
        link = c.client.get(LINK, headers=c.mum).json()
        row = next(d for d in link['devices'] if d['device_id'] == 'dev-k-light')
        check(row['area_id'] == 'patio', f'its new area is reported for the room panel: {row}')
        check(row['placed'] and row['auto'] is None, row)


def test_live_without_ha():
    seed(anchors=[ceiling_anchor()])
    with Ctx(available=False) as c, LogWatch() as log:
        r = c.client.get(LIVE, headers=c.panel)
        check(r.status_code == 200, r.text)
        body = r.json()
        check(body['available'] is False and body['markers'] == [], body)
        check({x['room'] for x in body['rooms']} == {'kitchen', 'dining'}, body['rooms'])
        check(all(x['area_id'] is None for x in body['rooms']), f'area_id is null with no HA: {body["rooms"]}')
        check(log.records == [], f'no error logged: {[r.getMessage() for r in log.records]}')


def test_live_offered_follows_the_grid():
    seed(anchors=[ceiling_anchor()])
    with Ctx() as c:
        panel = c.client.get(LIVE, headers=c.panel).json()
        lock = marker_for(panel, 'dev-back-lock')
        check(lock['offered'] is False, f'a panel with locks off is offered no lock: {lock}')
        check(marker_for(panel, 'dev-k-light')['offered'] is True, 'a panel is offered a light')
        mum = c.client.get(LIVE, headers=c.mum).json()
        check(marker_for(mum, 'dev-back-lock')['offered'] is True, 'a parent is offered the lock')
        check(marker_for(mum, 'dev-k-light')['offered'] is True, 'a parent is offered the light')
        # The household switch off: nothing is offered to anyone.
        rules = cr.default_rules({})
        rules['enabled'] = False
        c.extra = {'ha_control': rules}
        off = c.client.get(LIVE, headers=c.mum).json()
        check(all(m['offered'] is False for m in off['markers']) and off['markers'], off['markers'])


def _identify(c, device_id, headers=None):
    return c.client.post(IDENTIFY, json={'device_id': device_id}, headers=headers or c.mum)


def _wait(cond, seconds=4.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_identify_flash_and_toggle_restore():
    seed(anchors=[ceiling_anchor()])
    with Ctx() as c:
        # A light with the flash bit (supported_features has 8) flashes; nothing is left to restore.
        r = _identify(c, 'dev-k-light')
        check(r.status_code == 200 and r.json() == {'ok': True, 'how': 'flash'}, r.text)
        calls = c.ha.calls_on('light.kitchen_ceiling')
        check(len(calls) == 1 and calls[0][:2] == ('light', 'turn_on') and calls[0][2].get('flash') == 'short', calls)
        time.sleep(2.2)
        check(len(c.ha.calls_on('light.kitchen_ceiling')) == 1, 'a flash is one call; nothing is restored')
        # A light without the bit toggles, then goes back to what it was, from either starting state.
        for start in ('off', 'on'):
            c.ha.states['light.kitchen_lamp']['state'] = start
            c.ha.calls.clear()
            r = _identify(c, 'dev-k-lamp')
            check(r.status_code == 200 and r.json() == {'ok': True, 'how': 'toggle'}, r.text)
            flipped = 'on' if start == 'off' else 'off'
            check(c.ha.states['light.kitchen_lamp']['state'] == flipped
                  or _wait(lambda: len(c.ha.calls_on('light.kitchen_lamp')) >= 1),
                  f'the toggle happened: {c.ha.calls}')
            check(all(call[2].get('flash') is None for call in c.ha.calls_on('light.kitchen_lamp')), 'no flash for a plain lamp')
            check(_wait(lambda: len(c.ha.calls_on('light.kitchen_lamp')) >= 2),
                  f'the earlier state is restored after the delay: {c.ha.calls}')
            check(_wait(lambda: c.ha.states['light.kitchen_lamp']['state'] == start),
                  f'the lamp is back to {start}: {c.ha.states["light.kitchen_lamp"]["state"]}')
        # A non-light cannot blink.
        c.ha.calls.clear()
        r = _identify(c, 'dev-back-lock')
        check(r.status_code == 400 and NON_LIGHT_COPY in r.text, (r.status_code, r.text))
        check(c.ha.calls == [], c.ha.calls)


def test_identify_guarded():
    seed(anchors=[ceiling_anchor()])
    with Ctx() as c:
        r = _identify(c, 'dev-k-light', c.visitor)
        check(r.status_code == 403, f'a guest is refused: {r.status_code} {r.text}')
        check(_identify(c, 'dev-k-light', c.kid).status_code == 403, 'a child is refused')
        check(c.ha.calls == [], f'nothing reached Home Assistant: {c.ha.calls}')
        # A parent the household grid says may not turn lights on is refused by control_rules.guard.
        rules = cr.default_rules({})
        rules['people']['parent']['light'] = 'no'
        c.extra = {'ha_control': rules}
        r = _identify(c, 'dev-k-light')
        check(r.status_code == 403, f'the grid refuses before any call: {r.status_code} {r.text}')
        check(c.ha.calls == [], c.ha.calls)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]


def _building_now():
    return ts.current_model()['buildings'][0]


if __name__ == '__main__':
    passed = 0
    for fn in TESTS:
        try:
            fn()
            passed += 1
            print(f'ok   {fn.__name__}')
        except Exception:
            print(f'FAIL {fn.__name__}')
            traceback.print_exc(limit=4)
    print(f'{passed}/{len(TESTS)} passed')
    sys.exit(0 if passed == len(TESTS) else 1)
