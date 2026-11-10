"""The house's Home Assistant catalogue (piece 3, Task 1; brief .superpowers/sdd/
2026-11-10-house-ha-link-piece-3/task-1-brief.md; plan docs/superpowers/plans/
2026-11-10-house-ha-link-piece-3.md Task 1 and Review Focus 1 and 3).

Modules under test: services/twin_ha.py and ha_api.get_floor_registry.

Fake HA is patched onto ha_api (pattern of test_control_endpoints.py); areas and
floors answer through a fake ws_command. The model functions are pure and run on
small schema-3 models built in the test (rooms carry cached polygons).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_ha.py
"""
import copy
import logging
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_ha_')
for _var in ('HA_BASE_URL', 'HA_TOKEN', 'SUPERVISOR_TOKEN'):
    os.environ.pop(_var, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import ha_api  # noqa: E402
from services import twin_ha  # noqa: E402  (does not exist until the implementation lands)

CACHES = ('_states_cache', '_area_cache', '_area_meta_cache', '_entity_registry_cache',
          '_device_registry_cache', '_floor_registry_cache')


def check(cond, msg=''):
    if not cond:
        raise AssertionError(msg)


def clear_caches():
    for name in CACHES:
        cache = getattr(ha_api, name, None)
        if isinstance(cache, dict):
            cache.update(ts=0.0, data=None)


# ------------------------------------------------------------------ fake HA

FLOORS = [{'floor_id': 'main', 'name': 'Main floor', 'level': 0, 'icon': None},
          {'floor_id': 'up', 'name': 'Upstairs', 'level': 1, 'icon': 'mdi:stairs'}]
AREA_ROWS = [
    {'area_id': 'kitchen', 'name': 'Kitchen', 'floor_id': 'main', 'picture': None, 'icon': None},
    {'area_id': 'living_room', 'name': 'Living Room', 'floor_id': 'main', 'picture': None, 'icon': None},
    {'area_id': 'garage', 'name': 'Garage', 'floor_id': 'main', 'picture': None, 'icon': None},
    {'area_id': 'bedroom', 'name': 'Master Bedroom', 'floor_id': 'up', 'picture': None, 'icon': None},
]
# entity_id, state, attributes, device id, area (own or from its device)
ENTITIES = [
    ('sensor.kitchen_ceiling_energy', '3', {'friendly_name': 'Kitchen ceiling energy'}, 'dK', 'kitchen'),
    ('light.kitchen_ceiling', 'on', {'friendly_name': 'Kitchen ceiling'}, 'dK', 'kitchen'),
    ('switch.coffee', 'off', {'friendly_name': 'Coffee maker'}, None, 'kitchen'),
    # a real device carries side sensors listed first; its kind is still what it IS
    ('binary_sensor.garage_door_obstruction', 'off', {'friendly_name': 'Garage obstruction', 'device_class': 'problem'}, 'dG', 'garage'),
    ('cover.garage_door', 'closed', {'friendly_name': 'Garage door', 'device_class': 'garage'}, 'dG', 'garage'),
    ('cover.living_shade', 'open', {'friendly_name': 'Living shade', 'device_class': 'shade'}, 'dS', 'living_room'),
    ('sensor.front_door_battery', '80', {'friendly_name': 'Front door battery', 'device_class': 'battery'}, 'dF', 'living_room'),
    ('lock.front_door', 'locked', {'friendly_name': 'Front door'}, 'dF', 'living_room'),
    ('sensor.hall_temperature', '20', {'friendly_name': 'Hall temperature', 'device_class': 'temperature'}, 'dC', 'living_room'),
    ('climate.hall', 'heat', {'friendly_name': 'Hall thermostat'}, 'dC', 'living_room'),
    ('media_player.tv', 'off', {'friendly_name': 'Living TV'}, 'dT', 'living_room'),
    ('camera.porch', 'idle', {'friendly_name': 'Porch camera'}, 'dP', 'living_room'),
    ('fan.bedroom_fan', 'off', {'friendly_name': 'Bedroom fan'}, 'dB', 'bedroom'),
    ('binary_sensor.motion', 'off', {'friendly_name': 'Bedroom motion'}, 'dM', 'bedroom'),
    ('vacuum.robo', 'docked', {'friendly_name': 'Robo'}, 'dR', 'bedroom'),
    ('input_boolean.guest_mode', 'off', {'friendly_name': 'Guest mode'}, None, None),
]
DEVICE_NAMES = {'dK': 'Kitchen ceiling', 'dG': 'Garage door opener', 'dS': 'Living shade motor',
                'dF': 'Front door lock', 'dC': 'Hall thermostat', 'dT': 'Living TV',
                'dP': 'Porch camera', 'dB': 'Bedroom fan', 'dM': 'Bedroom motion sensor', 'dR': 'Robo vac'}
DEVICE_KINDS = {'dK': 'light', 'dG': 'garage', 'dS': 'blinds', 'dF': 'lock', 'dC': 'climate',
                'dT': 'media', 'dP': 'camera', 'dB': 'fan', 'dM': 'sensor', 'dR': 'other',
                'entity:switch.coffee': 'switch', 'entity:input_boolean.guest_mode': 'switch'}


class FakeHA:
    """Patch ha_api to a small house; `areas`/`floors` can change mid-test."""

    NAMES = ('mode', 'is_available', 'get_states', 'get_state', 'get_area_map',
             'get_entity_registry', 'get_device_registry', 'ws_command')

    def __init__(self):
        self.areas = copy.deepcopy(AREA_ROWS)
        self.floors = copy.deepcopy(FLOORS)

    def __enter__(self):
        self.orig = {n: getattr(ha_api, n) for n in self.NAMES}
        ha_api.mode = lambda: 'external'
        ha_api.is_available = lambda: True
        ha_api.get_states = lambda ttl=5: [
            {'entity_id': e, 'state': s, 'attributes': copy.deepcopy(a)} for e, s, a, _, _ in ENTITIES]
        ha_api.get_state = lambda eid: next(
            ({'entity_id': e, 'state': s, 'attributes': copy.deepcopy(a)}
             for e, s, a, _, _ in ENTITIES if e == eid), None)
        ha_api.get_area_map = self._area_map
        ha_api.get_entity_registry = lambda ttl=300: [
            {'entity_id': e, 'name': None, 'original_name': a['friendly_name'], 'aliases': [],
             'area_id': None, 'device_id': d, 'hidden_by': None, 'disabled_by': None, 'platform': 'fake'}
            for e, s, a, d, _ in ENTITIES]
        ha_api.get_device_registry = lambda ttl=300: [
            {'id': d, 'name': n, 'name_by_user': None, 'manufacturer': 'Acme', 'model': 'M1',
             'area_id': next(ar for e, s, a, dd, ar in ENTITIES if dd == d)}
            for d, n in DEVICE_NAMES.items()]
        ha_api.ws_command = self._ws
        clear_caches()
        return self

    def __exit__(self, *exc):
        for name, fn in self.orig.items():
            setattr(ha_api, name, fn)
        clear_caches()

    def _area_map(self, ttl=60):
        live = {a['area_id'] for a in self.areas}
        return [{'id': a['area_id'], 'name': a['name'],
                 'entities': [e for e, s, at, d, ar in ENTITIES if ar == a['area_id'] and ar in live]}
                for a in self.areas]

    def _ws(self, command, timeout=8, **fields):
        if command == 'config/area_registry/list':
            return copy.deepcopy(self.areas)
        if command == 'config/floor_registry/list':
            return copy.deepcopy(self.floors)
        return None


# ------------------------------------------------------------------ model builders

def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def room(rid, name, polygon, level='L1', ha_area=None, joints=None):
    row = {'id': rid, 'level': level, 'name': name, 'kind': 'room', 'polygon': polygon,
           'joints': joints or []}
    if ha_area is not None:
        row['ha_area'] = ha_area
    return row


def building(rooms, levels=None, **extra):
    b = {'id': 'B1', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0, 'materials': {},
         'levels': levels or [{'id': 'L1', 'name': 'main floor', 'elevation': 0, 'ceiling': 9}],
         'joints': [], 'walls': [], 'rooms': rooms, 'openings': [], 'anchors': [], 'items': [],
         'devices': [], 'roofs': [], 'dormers': [], 'extensions': [], 'stairs': [],
         'proposals': [], 'flags': []}
    b.update(extra)
    return b


def model(*buildings):
    return {'schema': 'chauffeur.twin.plan/3', 'units': 'ft', 'materials': {},
            'buildings': list(buildings), 'site': {}}


def area(aid, name, floor_level=0):
    # `floor_level` carries the area floor's level into suggest(); the brief does not name where
    # suggest() reads it from, so the tests assume the catalogue's area rows carry it (see report).
    return {'area_id': aid, 'name': name, 'floor_id': f'f{floor_level}', 'floor_name': f'Floor {floor_level}',
            'floor_level': floor_level}


def dev(did, kind='light', area_id='kitchen', name=None):
    eid = {'light': 'light.', 'switch': 'switch.', 'fan': 'fan.', 'camera': 'camera.',
           'sensor': 'sensor.', 'lock': 'lock.', 'garage': 'cover.'}.get(kind, 'x.') + did
    return {'device_id': did, 'name': name or did, 'area_id': area_id, 'kind': kind,
            'entity_id': eid, 'entities': [eid]}


def cat(*devices, areas=()):
    return {'available': True, 'areas': list(areas), 'floors': [], 'devices': list(devices)}


def inside(pt, polygon):
    x, y = pt
    ok = False
    for i in range(len(polygon)):
        (x1, y1), (x2, y2) = polygon[i - 1], polygon[i]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            ok = not ok
    return ok


# ------------------------------------------------------------------ tests

def test_floor_registry_reads_floors_and_is_empty_without_ha():
    with FakeHA():
        check(ha_api.get_floor_registry() == [
            {'floor_id': 'main', 'name': 'Main floor', 'level': 0},
            {'floor_id': 'up', 'name': 'Upstairs', 'level': 1}], ha_api.get_floor_registry())
    clear_caches()
    check(ha_api.get_floor_registry() == [], ha_api.get_floor_registry())


def test_catalogue_groups_entities_by_device():
    with FakeHA():
        out = twin_ha.catalogue()
        check(out['available'] is True, out)
        check([a['area_id'] for a in out['areas']] == ['kitchen', 'living_room', 'garage', 'bedroom'], out['areas'])
        kitchen = next(a for a in out['areas'] if a['area_id'] == 'kitchen')
        for key, want in (('name', 'Kitchen'), ('floor_id', 'main'), ('floor_name', 'Main floor')):
            check(kitchen[key] == want, kitchen)
        check(out['floors'] == [{'floor_id': 'main', 'name': 'Main floor', 'level': 0},
                                {'floor_id': 'up', 'name': 'Upstairs', 'level': 1}], out['floors'])
        by_id = {d['device_id']: d for d in out['devices']}
        check(len(by_id) == len(out['devices']) == len(DEVICE_KINDS), sorted(by_id))
        # two entities of one device collapse into one row; the primary entity is the light
        check(by_id['dK'] == {'device_id': 'dK', 'name': 'Kitchen ceiling', 'area_id': 'kitchen',
                              'kind': 'light', 'entity_id': 'light.kitchen_ceiling',
                              'entities': ['sensor.kitchen_ceiling_energy', 'light.kitchen_ceiling']}, by_id['dK'])
        # an entity with no device is its own pseudo device
        check(by_id['entity:switch.coffee'] == {
            'device_id': 'entity:switch.coffee', 'name': 'Coffee maker', 'area_id': 'kitchen',
            'kind': 'switch', 'entity_id': 'switch.coffee', 'entities': ['switch.coffee']},
            by_id['entity:switch.coffee'])
        check(by_id['entity:input_boolean.guest_mode']['area_id'] is None, by_id['entity:input_boolean.guest_mode'])
        for did, kind in DEVICE_KINDS.items():
            check(by_id[did]['kind'] == kind, (did, by_id[did]))
        check(by_id['dG']['area_id'] == 'garage' and by_id['dB']['area_id'] == 'bedroom', by_id)


def test_catalogue_without_ha_is_empty_and_quiet():
    clear_caches()
    records = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record)
    handler = Grab(level=logging.WARNING)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        check(ha_api.mode() == 'unconfigured', ha_api.mode())
        out = twin_ha.catalogue()
    finally:
        root.removeHandler(handler)
    check(out == {'available': False, 'areas': [], 'floors': [], 'devices': []}, out)
    check(not records, [r.getMessage() for r in records])


def test_catalogue_is_unavailable_when_ha_has_no_areas():
    with FakeHA() as fake:
        fake.areas = []
        out = twin_ha.catalogue()
        check(out['available'] is False and out['areas'] == [], out)


def test_resolve_area_accepts_ids_and_legacy_names():
    areas = [area('kitchen', 'Kitchen'), area('living_room', 'Living Room'), area('study', 'Den'),
             area('den', 'Library')]
    check(twin_ha.resolve_area('kitchen', areas) == 'kitchen')
    check(twin_ha.resolve_area('Kitchen', areas) == 'kitchen')
    check(twin_ha.resolve_area('living room', areas) == 'living_room')
    check(twin_ha.resolve_area('LIVING ROOM', areas) == 'living_room')
    check(twin_ha.resolve_area('living_room', areas) == 'living_room')
    # an id wins over another area's name
    check(twin_ha.resolve_area('den', areas) == 'den', twin_ha.resolve_area('den', areas))
    check(twin_ha.resolve_area('Den', areas) == 'study', twin_ha.resolve_area('Den', areas))
    check(twin_ha.resolve_area('attic', areas) is None)
    check(twin_ha.resolve_area('', areas) is None)
    check(twin_ha.resolve_area(None, areas) is None)
    check(twin_ha.resolve_area('kitchen', []) is None)


def test_suggest_matches_names_once_and_prefers_floor():
    areas = [area('kitchen', 'Kitchen'), area('master', 'Master Bedroom', 1), area('bath', 'Bathroom', 1),
             area('laundry', 'Laundry'), area('fam_den', 'Family den'), area('garage', 'Garage')]
    b = building([
        room('r_nook', 'Kitchen nook', rect(0, 0, 4, 4)),            # contains 'kitchen', but Kitchen is taken exactly
        room('r_kit', 'Kitchen', rect(5, 0, 12, 6)),                  # exact
        room('r_mast', 'Master Bedroom!', rect(0, 8, 8, 14), level='L2'),  # punctuation and case dropped
        room('r_bath0', 'Bathroom', rect(20, 0, 24, 4)),              # level index 0
        room('r_bath1', 'Bathroom', rect(20, 0, 24, 4), level='L2'),  # level index 1 = Upstairs floor level 1
        room('r_laun', 'Laundry room', rect(30, 0, 34, 4)),           # area name inside the room name
        room('r_den', 'Den', rect(40, 0, 44, 4)),                     # room name inside the area name
        room('r_gar', 'Garage', rect(50, 0, 60, 10), ha_area='garage'),  # already linked
        room('r_gar2', 'Garage storage', rect(60, 0, 64, 4)),         # Garage is linked: not suggested twice
        room('r_hall', 'Hall', rect(70, 0, 74, 4)),                   # no match
    ], levels=[{'id': 'L1', 'name': 'main', 'elevation': 0, 'ceiling': 9},
               {'id': 'L2', 'name': 'up', 'elevation': 10, 'ceiling': 9}])
    out = twin_ha.suggest(model(b), areas)
    check(out == {'r_kit': 'kitchen', 'r_mast': 'master', 'r_bath1': 'bath',
                  'r_laun': 'laundry', 'r_den': 'fam_den'}, out)


def test_rooms_for_area_largest_region_first():
    big, small, other = rect(0, 0, 8, 6), rect(10, 0, 14, 4), rect(20, 0, 22, 2)
    b = building([room('r_small', 'Kitchen', small, ha_area='kitchen'),
                  room('r_big', 'Dining', big, ha_area='kitchen'),
                  room('r_other', 'Hall', other, ha_area='hall')])
    out = twin_ha.rooms_for_area(model(b), 'kitchen')
    check([r['id'] for r in out] == ['r_big', 'r_small'], out)
    check(twin_ha.rooms_for_area(model(b), 'nowhere') == [])


def test_two_rooms_one_area_auto_spots_in_largest():
    small, big = rect(10, 0, 14, 4), rect(0, 0, 8, 6)
    b = building([room('r_small', 'Kitchen', small, ha_area='kitchen'),
                  room('r_big', 'Dining', big, ha_area='kitchen'),
                  room('r_liv', 'Living', rect(30, 0, 40, 10))],
                 anchors=[{'id': 'a1', 'kind': 'light', 'host': {'ceiling': 'r_big', 'u': 0.5, 'v': 0.5},
                           'device': 'placed_on_anchor'}],
                 devices=[{'id': 'device:placed_on_wall', 'device': 'placed_on_wall',
                           'host': {'wall': 'w1', 'at': 1.0, 'side': 'in'}, 'offset': 4.0}])
    c = cat(dev('lamp1', 'light'), dev('plug', 'switch'), dev('placed_on_anchor', 'light'),
            dev('placed_on_wall', 'switch'), dev('liv_lamp', 'light', area_id='living_room'),
            dev('ghost_lamp', 'light', area_id=None))
    spots = twin_ha.auto_spots(model(b), c)
    # placed devices (anchor or surface), devices of unlinked areas and area-less devices get no spot
    check(sorted(spots) == ['lamp1', 'plug'], sorted(spots))
    for did, spot in spots.items():
        check(spot['building'] == 'B1' and spot['level'] == 'L1' and spot['room'] == 'r_big', spot)
        check(inside(spot['at'], big), spot)
    # the first device sits at the centroid of the largest linked room; the next steps away
    ats = [(round(s['at'][0], 6), round(s['at'][1], 6)) for s in spots.values()]
    check((4, 3) in ats, ats)
    check(len(set(ats)) == 2, ats)
    check(abs(spots['lamp1']['z'] - 9) <= 0.5, spots['lamp1'])      # a light rides the ceiling (9 ft)
    check(spots['plug']['z'] == 4, spots['plug'])                   # anything else sits at 4 ft


def test_auto_spots_stay_inside_an_l_shaped_room():
    ell = [[0, 0], [12, 0], [12, 4], [4, 4], [4, 12], [0, 12]]   # its centroid (4.4, 4.4) is outside the L
    b = building([room('r_l', 'Hall', ell, ha_area='hall')])
    c = cat(*[dev(f'l{i}', 'light', area_id='hall') for i in range(8)])
    spots = twin_ha.auto_spots(model(b), c)
    check(len(spots) == 8, sorted(spots))
    ats = [tuple(s['at']) for s in spots.values()]
    check(len(set(ats)) == 8, ats)
    for did, spot in spots.items():
        check(spot['room'] == 'r_l' and inside(spot['at'], ell), (did, spot))
    # a spot never lands in the notch of the L
    check(not any(x > 4 and y > 4 for x, y in ats), ats)


def test_auto_spots_ignore_unlinked_areas():
    b = building([room('r1', 'Kitchen', rect(0, 0, 8, 6), ha_area='kitchen'), room('r2', 'Den', rect(10, 0, 18, 6))])
    spots = twin_ha.auto_spots(model(b), cat(dev('d1', 'light', area_id='den'), dev('d2', 'light', area_id=None)))
    check(spots == {}, spots)


def test_placements_read_anchors_and_building_devices():
    b = building([room('r1', 'Kitchen', rect(0, 0, 8, 6), ha_area='kitchen')],
                 anchors=[{'id': 'a1', 'kind': 'light', 'host': {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}, 'device': 'dev1'},
                          {'id': 'a2', 'kind': 'light', 'host': {'ceiling': 'r1', 'u': 0.2, 'v': 0.2}}],
                 devices=[{'id': 'device:dev2', 'device': 'dev2', 'host': {'wall': 's', 'at': 0.5, 'side': 'in'},
                           'offset': 1.5}])
    out = twin_ha.placements(model(b))
    check(out == {'dev1': {'kind': 'anchor', 'building': 'B1', 'anchor': 'a1', 'offset': 0},
                  'dev2': {'kind': 'host', 'building': 'B1',
                           'host': {'wall': 's', 'at': 0.5, 'side': 'in'}, 'offset': 1.5}}, out)


def _anchors(prefix, kind, n, room_id, surface):
    return [{'id': f'{prefix}{i}', 'kind': kind, 'host': {surface: room_id, 'u': 0.5, 'v': 0.5}}
            for i in range(n)]


def test_count_note_copy():
    b = building(
        [room('r1', 'Kitchen', rect(0, 0, 8, 6), ha_area='kitchen'),
         room('r2', 'Den', rect(10, 0, 18, 6), ha_area='den')],
        anchors=(_anchors('l', 'light', 5, 'r1', 'ceiling')
                 + _anchors('s', 'switch', 3, 'r1', 'floor')
                 + _anchors('e', 'sensor', 2, 'r1', 'floor')
                 + _anchors('c', 'camera', 1, 'r1', 'ceiling')
                 + _anchors('x', 'light', 7, 'r2', 'ceiling')))
    c = cat(*[dev(f'kl{i}', 'light') for i in range(4)],                  # 5 vs 4: noted
            *[dev(f'ks{i}', 'switch') for i in range(2)],                  # 3 vs 2: noted
            *[dev(f'ke{i}', 'sensor') for i in range(2)],                  # 2 vs 2: equal, quiet
            dev('kf', 'fan'),                                               # 0 anchors: quiet
            *[dev(f'dl{i}', 'light', area_id='den') for i in range(3)])    # the Den's own: 7 vs 3
    notes = twin_ha.count_notes(model(b), 'r1', c)
    check('The plan shows 5 lights; Home Assistant has 4 in this area.' in notes, notes)
    check(sorted(notes) == ['The plan shows 3 switches; Home Assistant has 2 in this area.',
                            'The plan shows 5 lights; Home Assistant has 4 in this area.'], notes)
    check(twin_ha.count_notes(model(b), 'r2', c) == ['The plan shows 7 lights; Home Assistant has 3 in this area.'])
    # a room linked to no area has nothing to compare with
    b2 = building([room('r3', 'Hall', rect(0, 0, 4, 4))])
    check(twin_ha.count_notes(model(b2), 'r3', c) == [])


def _garage_building(extra_door=False, ha_area='garage'):
    walls = [
        {'id': 's', 'level': 'L1', 'joints': ['j1', 'j2'], 'kind': 'solid', 'exterior': True, 'thickness': 0.5, 'height': 9},
        {'id': 'e', 'level': 'L1', 'joints': ['j2', 'j3'], 'kind': 'solid', 'exterior': True, 'thickness': 0.5, 'height': 9},
        {'id': 'n', 'level': 'L1', 'joints': ['j3', 'j4'], 'kind': 'solid', 'exterior': False, 'thickness': 0.5, 'height': 9},
        {'id': 'w', 'level': 'L1', 'joints': ['j4', 'j1'], 'kind': 'solid', 'exterior': True, 'thickness': 0.5, 'height': 9},
    ]

    def op(oid, wall, at, kind, width=3.0):
        return {'id': oid, 'wall': wall, 'at': at, 'width': width, 'sill': 0, 'head': 7, 'kind': kind}
    openings = [op('g1', 's', 2.5, 'garage', 8), op('g2', 's', 7.0, 'garage', 8), op('win', 'e', 5, 'window'),
                op('d_front', 'e', 2, 'door'), op('d_int', 'n', 5, 'door')]
    if extra_door:
        openings.append(op('d_back', 'w', 5, 'door'))
    return building(
        [room('rg', 'Garage', rect(0, 0, 20, 10), ha_area=ha_area, joints=['j1', 'j2', 'j3', 'j4'])],
        joints=[{'id': 'j1', 'level': 'L1', 'at': [0, 0]}, {'id': 'j2', 'level': 'L1', 'at': [20, 0]},
                {'id': 'j3', 'level': 'L1', 'at': [20, 10]}, {'id': 'j4', 'level': 'L1', 'at': [0, 10]}],
        walls=walls, openings=openings)


def test_obvious_places_garage_and_lock():
    c = cat(dev('gd1', 'garage', 'garage'), dev('gd2', 'garage', 'garage'), dev('gd3', 'garage', 'garage'),
            dev('lk1', 'lock', 'garage'), dev('lamp', 'light', 'garage'),
            dev('gd_elsewhere', 'garage', 'bedroom'))
    out = twin_ha.obvious(model(_garage_building()), 'rg', c)
    got = {row['device']: row for row in out}
    # gd3 has no garage opening left; the lamp and the other area's opener are not this room's business
    check(len(out) == 3 and sorted(got) == ['gd1', 'gd2', 'lk1'], out)
    check(got['gd1'] == {'device': 'gd1', 'building': 'B1', 'host': {'opening': 'g1', 'side': 'in'}}, got['gd1'])
    check(got['gd2'] == {'device': 'gd2', 'building': 'B1', 'host': {'opening': 'g2', 'side': 'in'}}, got['gd2'])
    check(got['lk1'] == {'device': 'lk1', 'building': 'B1', 'host': {'opening': 'd_front', 'side': 'in'}}, got['lk1'])

    # a second exterior door makes the lock a guess: it is not placed
    out = twin_ha.obvious(model(_garage_building(extra_door=True)), 'rg', c)
    check(sorted(row['device'] for row in out) == ['gd1', 'gd2'], out)

    # a device already placed (anchor or building list) is not offered again
    b = _garage_building()
    b['anchors'].append({'id': 'a1', 'kind': 'lock', 'host': {'wall': 'e', 'at': 1, 'side': 'in'}, 'device': 'lk1'})
    b['devices'].append({'id': 'device:gd1', 'device': 'gd1', 'host': {'opening': 'g1', 'side': 'in'}, 'offset': 0})
    out = twin_ha.obvious(model(b), 'rg', c)
    check('lk1' not in [row['device'] for row in out] and 'gd1' not in [row['device'] for row in out], out)
    check('gd2' in [row['device'] for row in out], out)

    # a room linked to no area has nothing obvious
    check(twin_ha.obvious(model(_garage_building(ha_area='')), 'rg', c) == [])


def test_deleted_area_reads_as_gone():
    b = building([room('r_k', 'Kitchen', rect(0, 0, 8, 6), ha_area='kitchen'),
                  room('r_b', 'Basement', rect(10, 0, 18, 6), ha_area='basement'),
                  room('r_h', 'Hall', rect(20, 0, 24, 4)),
                  room('r_unset', 'Den', rect(30, 0, 34, 4), ha_area='')])
    with FakeHA() as fake:
        areas = twin_ha.catalogue()['areas']
        check(twin_ha.gone_rooms(model(b), areas) == ['r_b'], twin_ha.gone_rooms(model(b), areas))
        # HA answers with no areas at all: nothing is called gone (a blip is not a deletion)
        check(twin_ha.gone_rooms(model(b), []) == [])
        # the kitchen area is deleted in HA: its room is flagged and its devices vanish quietly
        fake.areas = [a for a in fake.areas if a['area_id'] != 'kitchen']
        clear_caches()
        out = twin_ha.catalogue()
        check(out['available'] is True and 'kitchen' not in [a['area_id'] for a in out['areas']], out['areas'])
        check(sorted(twin_ha.gone_rooms(model(b), out['areas'])) == ['r_b', 'r_k'],
              twin_ha.gone_rooms(model(b), out['areas']))
        check(not any(d['area_id'] == 'kitchen' for d in out['devices']), out['devices'])
        check(twin_ha.auto_spots(model(b), out) == {}, twin_ha.auto_spots(model(b), out))
        check(twin_ha.suggest(model(b), out['areas']).get('r_k') is None)


def test_renamed_area_keeps_the_link():
    b = building([room('r_k', 'Kitchen', rect(0, 0, 8, 6), ha_area='kitchen')])
    with FakeHA() as fake:
        before = twin_ha.catalogue()
        spots_before = twin_ha.auto_spots(model(b), before)
        check(sorted(spots_before) == ['dK', 'entity:switch.coffee'], sorted(spots_before))
        for row in fake.areas:
            if row['area_id'] == 'kitchen':
                row['name'] = 'Cookhouse'
        clear_caches()
        after = twin_ha.catalogue()
        check(next(a for a in after['areas'] if a['area_id'] == 'kitchen')['name'] == 'Cookhouse', after['areas'])
        check(twin_ha.gone_rooms(model(b), after['areas']) == [])
        check([r['id'] for r in twin_ha.rooms_for_area(model(b), 'kitchen')] == ['r_k'])
        check(sorted(twin_ha.auto_spots(model(b), after)) == ['dK', 'entity:switch.coffee'])
        check(twin_ha.suggest(model(b), after['areas']) == {})       # a linked room is never suggested again
        check(twin_ha.resolve_area('Kitchen', after['areas']) is None)   # the old name no longer resolves
        check(twin_ha.resolve_area('kitchen', after['areas']) == 'kitchen')


def test_m1_smart_plug_is_an_outlet():
    """Final review M1: a switch whose device_class is outlet (in its state, or the
    registry's device_class / original_device_class) is kind outlet, so the outlets
    count note and the outlet spots work; a plain switch stays a switch."""
    extra = [('switch.kettle_plug', 'on', {'friendly_name': 'Kettle plug', 'device_class': 'outlet'}, 'dO', 'kitchen'),
             ('switch.lamp_plug', 'off', {'friendly_name': 'Lamp plug'}, 'dQ', 'kitchen')]
    ENTITIES.extend(extra)
    DEVICE_NAMES.update(dO='Kettle plug', dQ='Lamp plug')
    try:
        with FakeHA():
            rows = ha_api.get_entity_registry

            def registry(ttl=300):
                out = rows(ttl)
                for row in out:
                    if row['entity_id'] == 'switch.lamp_plug':
                        row['original_device_class'] = 'outlet'
                return out
            ha_api.get_entity_registry = registry
            by_id = {d['device_id']: d for d in twin_ha.catalogue()['devices']}
        check(by_id['dO']['kind'] == 'outlet', by_id['dO'])
        check(by_id['dQ']['kind'] == 'outlet', ("the registry's outlet signal counts too", by_id['dQ']))
        check(by_id['entity:switch.coffee']['kind'] == 'switch', by_id['entity:switch.coffee'])
    finally:
        del ENTITIES[-len(extra):]
        DEVICE_NAMES.pop('dO')
        DEVICE_NAMES.pop('dQ')
    # The outlets note now has devices to count.
    b = building([room('r1', 'Kitchen', rect(0, 0, 8, 6), ha_area='kitchen')],
                 anchors=_anchors('o', 'outlet', 6, 'r1', 'floor'))
    c = cat(dict(dev('p1', 'switch'), kind='outlet'), dict(dev('p2', 'switch'), kind='outlet'))
    check(twin_ha.count_notes(model(b), 'r1', c) == ['The plan shows 6 outlets; Home Assistant has 2 in this area.'],
          twin_ha.count_notes(model(b), 'r1', c))


TESTS = (
    test_floor_registry_reads_floors_and_is_empty_without_ha,
    test_catalogue_groups_entities_by_device,
    test_catalogue_without_ha_is_empty_and_quiet,
    test_catalogue_is_unavailable_when_ha_has_no_areas,
    test_resolve_area_accepts_ids_and_legacy_names,
    test_suggest_matches_names_once_and_prefers_floor,
    test_rooms_for_area_largest_region_first,
    test_two_rooms_one_area_auto_spots_in_largest,
    test_auto_spots_stay_inside_an_l_shaped_room,
    test_auto_spots_ignore_unlinked_areas,
    test_placements_read_anchors_and_building_devices,
    test_count_note_copy,
    test_obvious_places_garage_and_lock,
    test_deleted_area_reads_as_gone,
    test_renamed_area_keeps_the_link,
    test_m1_smart_plug_is_an_outlet,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
