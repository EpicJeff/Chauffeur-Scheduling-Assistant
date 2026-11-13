"""Device placements are schema-3 model data (house piece 3, Task 2).

Plan docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md Task 2; brief
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-2-brief.md; spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md sections 4.3
(hosts, anchors, devices) and 7 (the Home Assistant link).

Under test:
- A building's `devices` list: [{id: 'device:<ha device id>', device, host,
  offset, src}] for devices hosted directly on a surface or an opening. A
  device on an anchor lives only in that anchor's `device` field. A Home
  Assistant device id appears at most once across the whole model.
- The opening host {opening: <opening id>, side: 'in'|'out'}: world_point puts
  it on the opening's centre line, 3.5 ft above the level for a door and the
  sill + 1 ft for a window; it follows its opening; when the opening is
  deleted the device is kept and flagged.
- twin_model_ops.apply operations place_device / unplace_device, and `set` on
  a room's ha_area (an area id or ''; a legacy name stored as its id; an
  unknown value refused only while Home Assistant lists areas; linking runs
  twin_ha.obvious and places those devices with src {'auto': True}).
- twin_model_bridge flatten/assemble keep the placements.
- The Argyle tool house_design places and unplaces a device.

Home Assistant is faked by patching services.twin_ha.catalogue (and
ha_api.get_area_registry, for an implementation that reads areas directly).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model_devices.py
"""
import contextlib
import copy
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_devices_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402
from services import twin_store as ts  # noqa: E402
from services import ha_api  # noqa: E402
from services import twin_model as _model  # noqa: E402
from services import twin_model_ops as _ops  # noqa: E402
from services import twin_model_hosts as _hosts  # noqa: E402
from services import twin_model_bridge as _bridge  # noqa: E402

_MISSING = {}
try:
    from services import twin_ha as _twin_ha  # noqa: E402
except ImportError as exc:  # Task 1 lands the module
    _twin_ha, _MISSING['twin_ha'] = None, exc

TOL = 1e-6
OCCUPIED = 'That spot already holds a device; move it first.'
UNKNOWN_AREA = 'Pick an area from Home Assistant.'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def close_pt(a, b, tol=TOL):
    return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))


def twin_ha():
    if 'twin_ha' in _MISSING:
        raise _MISSING['twin_ha']
    return _twin_ha


# ---------------------------------------------------------------- fake Home Assistant

AREAS = [
    {'area_id': 'a_kitchen', 'name': 'Kitchen', 'floor_id': 'ground', 'floor_name': 'Ground floor'},
    {'area_id': 'a_garage', 'name': 'Garage', 'floor_id': 'ground', 'floor_name': 'Ground floor'},
    {'area_id': 'a_bed', 'name': 'Bedroom', 'floor_id': 'upper', 'floor_name': 'Upper floor'},
]
FLOORS = [{'floor_id': 'ground', 'name': 'Ground floor', 'level': 0},
          {'floor_id': 'upper', 'name': 'Upper floor', 'level': 1}]


def _dev(device_id, name, area_id, kind, entity_id):
    return {'device_id': device_id, 'name': name, 'area_id': area_id, 'kind': kind,
            'entity_id': entity_id, 'entities': [entity_id]}


DEVICES = [
    _dev('dev_garage_left', 'Left garage door', 'a_garage', 'garage', 'cover.left_garage_door'),
    _dev('dev_garage_right', 'Right garage door', 'a_garage', 'garage', 'cover.right_garage_door'),
    _dev('dev_garage_light', 'Garage light', 'a_garage', 'light', 'light.garage'),
    _dev('dev_lock', 'Front door lock', 'a_kitchen', 'lock', 'lock.front_door'),
    _dev('dev_lamp', 'Kitchen pendant', 'a_kitchen', 'light', 'light.kitchen_pendant'),
]
LIVE = {'available': True, 'areas': AREAS, 'floors': FLOORS, 'devices': DEVICES}
OFFLINE = {'available': False, 'areas': [], 'floors': [], 'devices': []}


@contextlib.contextmanager
def _ha(catalogue):
    """Home Assistant answers with this catalogue (or, OFFLINE, not at all)."""
    module = twin_ha()
    registry = [{'area_id': a['area_id'], 'name': a['name'], 'picture': None, 'icon': None}
                for a in catalogue['areas']]
    with patch.object(module, 'catalogue', side_effect=lambda *a, **k: copy.deepcopy(catalogue)), \
            patch.object(ha_api, 'get_area_registry', side_effect=lambda *a, **k: copy.deepcopy(registry)):
        yield


# ---------------------------------------------------------------- fixture

def _wall(wid, a, b, exterior=True, level='L1'):
    return {'id': wid, 'level': level, 'joints': [a, b], 'kind': 'solid',
            'thickness': 0.5 if exterior else 0.33, 'exterior': exterior, 'height': 9}


def _house_raw():
    """B1, a house; B2, a shed at [60, 0].

    B1 L1 (elevation 0, ceiling 9), all walls exterior but `mid`:

    j4 (0,20) -n2- jm1 (12,20) ----n1---- j3 (34,20)
     |              |                       |
     w   Kitchen   mid       Garage         e
     |              |                       |
    j1 (0,0)  -s1- jm0 (12,0)  ----s2----  j2 (34,0)

    Openings: d-front (door, w at 10: centre (0, 10)), d-mid (door, mid at 10,
    interior), win1 (window, s1 at 6, sill 2: centre (6, 0)), g1 and g2
    (garage, s2 at 6 and 16, 9 ft wide). The Kitchen's one exterior door is
    d-front; the Garage's openings on its walls are g1 and g2 (and d-mid).
    Anchors: a-light (light, Kitchen ceiling centre), a-switch (switch, n2),
    a-fan (fan, Garage ceiling).

    B1 L2 (elevation 10, ceiling 8): Bedroom 12 x 12 (k1..k4), door d-up on
    u-s at 6 (centre (6, 0)).

    B2 (shed): 10 x 10 room `shed` on its L1, anchor sh-light on the ceiling.
    """
    b1 = {
        'id': 'B1', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0,
        'materials': {},
        'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9},
                   {'id': 'L2', 'name': 'Upper floor', 'elevation': 10, 'ceiling': 8}],
        'joints': [
            {'id': 'j1', 'level': 'L1', 'at': [0, 0]},
            {'id': 'jm0', 'level': 'L1', 'at': [12, 0]},
            {'id': 'j2', 'level': 'L1', 'at': [34, 0]},
            {'id': 'j3', 'level': 'L1', 'at': [34, 20]},
            {'id': 'jm1', 'level': 'L1', 'at': [12, 20]},
            {'id': 'j4', 'level': 'L1', 'at': [0, 20]},
            {'id': 'k1', 'level': 'L2', 'at': [0, 0]},
            {'id': 'k2', 'level': 'L2', 'at': [12, 0]},
            {'id': 'k3', 'level': 'L2', 'at': [12, 12]},
            {'id': 'k4', 'level': 'L2', 'at': [0, 12]},
        ],
        'walls': [
            _wall('s1', 'j1', 'jm0'), _wall('s2', 'jm0', 'j2'), _wall('e', 'j2', 'j3'),
            _wall('n1', 'j3', 'jm1'), _wall('n2', 'jm1', 'j4'), _wall('w', 'j4', 'j1'),
            _wall('mid', 'jm0', 'jm1', exterior=False),
            _wall('u-s', 'k1', 'k2', level='L2'), _wall('u-e', 'k2', 'k3', level='L2'),
            _wall('u-n', 'k3', 'k4', level='L2'), _wall('u-w', 'k4', 'k1', level='L2'),
        ],
        'rooms': [
            {'id': 'kitchen', 'level': 'L1', 'name': 'Kitchen', 'kind': 'room',
             'polygon': [[0, 0], [12, 0], [12, 20], [0, 20]], 'joints': ['j1', 'jm0', 'jm1', 'j4']},
            {'id': 'garage', 'level': 'L1', 'name': 'Garage', 'kind': 'room',
             'polygon': [[12, 0], [34, 0], [34, 20], [12, 20]], 'joints': ['jm0', 'j2', 'j3', 'jm1']},
            {'id': 'bedroom', 'level': 'L2', 'name': 'Bedroom', 'kind': 'room',
             'polygon': [[0, 0], [12, 0], [12, 12], [0, 12]], 'joints': ['k1', 'k2', 'k3', 'k4']},
        ],
        'openings': [
            {'id': 'd-front', 'wall': 'w', 'kind': 'door', 'at': 10, 'width': 3, 'sill': 0, 'head': 7},
            {'id': 'd-mid', 'wall': 'mid', 'kind': 'door', 'at': 10, 'width': 3, 'sill': 0, 'head': 7},
            {'id': 'win1', 'wall': 's1', 'kind': 'window', 'at': 6, 'width': 3, 'sill': 2, 'head': 6},
            {'id': 'g1', 'wall': 's2', 'kind': 'garage', 'at': 6, 'width': 9, 'sill': 0, 'head': 7},
            {'id': 'g2', 'wall': 's2', 'kind': 'garage', 'at': 16, 'width': 9, 'sill': 0, 'head': 7},
            {'id': 'd-up', 'wall': 'u-s', 'kind': 'door', 'at': 6, 'width': 3, 'sill': 0, 'head': 7},
        ],
        'anchors': [
            {'id': 'a-light', 'kind': 'light', 'host': {'ceiling': 'kitchen', 'u': 0.5, 'v': 0.5},
             'offset': 0, 'device': None},
            {'id': 'a-switch', 'kind': 'switch', 'host': {'wall': 'n2', 'side': 'right', 'at': 4, 'z': 4},
             'offset': 0, 'device': None},
            {'id': 'a-fan', 'kind': 'fan', 'host': {'ceiling': 'garage', 'u': 0.5, 'v': 0.5},
             'offset': 0, 'device': None},
        ],
        'items': [], 'roofs': [], 'dormers': [], 'extensions': [], 'stairs': [],
        'proposals': [], 'flags': [],
    }
    b2 = {
        'id': 'B2', 'name': 'Shed', 'position': [60, 0], 'rotation': 0, 'base': 0, 'materials': {},
        'levels': [{'id': 'L1', 'name': 'Shed floor', 'elevation': 0, 'ceiling': 8}],
        'joints': [{'id': 'q1', 'level': 'L1', 'at': [0, 0]}, {'id': 'q2', 'level': 'L1', 'at': [10, 0]},
                   {'id': 'q3', 'level': 'L1', 'at': [10, 10]}, {'id': 'q4', 'level': 'L1', 'at': [0, 10]}],
        'walls': [_wall('sh-s', 'q1', 'q2'), _wall('sh-e', 'q2', 'q3'),
                  _wall('sh-n', 'q3', 'q4'), _wall('sh-w', 'q4', 'q1')],
        'rooms': [{'id': 'shed', 'level': 'L1', 'name': 'Shed', 'kind': 'room',
                   'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]], 'joints': ['q1', 'q2', 'q3', 'q4']}],
        'openings': [],
        'anchors': [{'id': 'sh-light', 'kind': 'light', 'host': {'ceiling': 'shed', 'u': 0.5, 'v': 0.5},
                     'offset': 0, 'device': None}],
        'items': [], 'roofs': [], 'dormers': [], 'extensions': [], 'stairs': [],
        'proposals': [], 'flags': [],
    }
    return {'schema': 'chauffeur.twin.plan/3', 'units': 'ft', 'materials': {},
            'buildings': [b1, b2], 'site': {}}


def _house():
    model, _ = _model.normalize(_house_raw())
    return model


def _bld(model, bid='B1'):
    return next(b for b in model['buildings'] if b['id'] == bid)


def _by_id(items, pid):
    return next((p for p in items if p.get('id') == pid), None)


def _apply(model, op):
    result = _ops.apply(copy.deepcopy(model), op)
    check(isinstance(result, tuple) and len(result) == 2, f'apply returns (model, words): {result!r:.200}')
    out, words = result
    check(isinstance(words, str) and words.strip(), f'plain words for {op["op"]}: {words!r}')
    check(out.get('schema') == 'chauffeur.twin.plan/3', f'still schema 3 after {op["op"]}')
    return out


def _refused(model, op):
    try:
        _ops.apply(copy.deepcopy(model), op)
    except _ops.Refused as exc:
        return str(exc)
    raise AssertionError(f'expected Refused for {op}')


def _places(model, device):
    """Every place this Home Assistant device id appears in the whole model."""
    found = []
    for b in model['buildings']:
        for anchor in b.get('anchors', []):
            if anchor.get('device') == device:
                found.append((b['id'], 'anchor', anchor['id']))
        for entry in b.get('devices', []):
            if entry.get('device') == device:
                found.append((b['id'], 'devices', entry['id']))
    return found


def _entry(model, device, bid='B1'):
    entry = _by_id(_bld(model, bid).get('devices', []), f'device:{device}')
    check(entry is not None, f'{device} in {bid} devices: {_bld(model, bid).get("devices")}')
    return entry


def _point(model, entry, bid='B1'):
    return _hosts.world_point(_bld(model, bid), entry['host'], entry.get('offset', 0))


def _on_opening_line(point, a, b, along, thickness, offset=0):
    """The point projects `along` ft from a on the wall a-b, within the wall's
    half thickness plus the device's offset of its centre line."""
    length = math.dist(a, b)
    unit = [(b[i] - a[i]) / length for i in (0, 1)]
    t = sum((point[i] - a[i]) * unit[i] for i in (0, 1))
    off = abs((point[0] - a[0]) * unit[1] - (point[1] - a[1]) * unit[0])
    return close(t, along) and off <= thickness / 2 + offset + TOL


# ---------------------------------------------------------------- placing

def test_place_on_anchor_then_move_to_wall():
    m0 = _house()
    check(_bld(m0).get('devices') == [] and _bld(m0, 'B2').get('devices') == [],
          f'normalize gives every building an empty devices list: {_bld(m0).get("devices")!r}')
    # The anchor form names no building: the anchor id is enough.
    m1 = _apply(m0, {'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-light'})
    check(_by_id(_bld(m1)['anchors'], 'a-light')['device'] == 'dev_lamp', _bld(m1)['anchors'])
    check(_bld(m1)['devices'] == [], f'a device on an anchor lives only in its device field: {_bld(m1)["devices"]}')
    check(_places(m1, 'dev_lamp') == [('B1', 'anchor', 'a-light')], _places(m1, 'dev_lamp'))
    check(_by_id(_bld(m0)['anchors'], 'a-light')['device'] is None, 'apply leaves its input untouched')

    host = {'wall': 'n2', 'side': 'right', 'at': 4, 'z': 5}
    m2 = _apply(m1, {'op': 'place_device', 'device': 'dev_lamp', 'building': 'B1',
                     'host': dict(host), 'offset': 0.25})
    check(_by_id(_bld(m2)['anchors'], 'a-light')['device'] is None, 'the anchor is freed')
    entry = _entry(m2, 'dev_lamp')
    check(entry['device'] == 'dev_lamp' and entry['host'] == host and close(entry['offset'], 0.25), entry)
    check(isinstance(entry.get('src'), dict) and entry['src'].get('auto') is not True,
          f"a person's placement is not automatic: {entry}")
    check(_places(m2, 'dev_lamp') == [('B1', 'devices', 'device:dev_lamp')], _places(m2, 'dev_lamp'))
    # n2 runs from (12, 20) to (0, 20): 4 ft along is x 8, 5 ft above L1.
    point = _point(m2, entry)
    check(close(point[0], 8) and close(point[2], 5) and close(abs(point[1] - 20), 0.25 + 0.25),
          f'on n2 at 4 ft, z 5, 0.25 ft off its 0.5 ft wall face: {point}')

    # Without an offset the entry records 0.
    m3 = _apply(m2, {'op': 'place_device', 'device': 'dev_lock', 'building': 'B1',
                     'host': {'opening': 'd-front', 'side': 'out'}})
    lock = _entry(m3, 'dev_lock')
    check(lock == {**lock, 'id': 'device:dev_lock', 'device': 'dev_lock',
                   'host': {'opening': 'd-front', 'side': 'out'}, 'offset': 0}, lock)


def test_one_device_one_place():
    m = _house()
    steps = [
        ({'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-light'}, ('B1', 'anchor', 'a-light')),
        ({'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-switch'}, ('B1', 'anchor', 'a-switch')),
        ({'op': 'place_device', 'device': 'dev_lamp', 'building': 'B1',
          'host': {'wall': 'e', 'side': 'left', 'at': 5, 'z': 6}}, ('B1', 'devices', 'device:dev_lamp')),
        ({'op': 'place_device', 'device': 'dev_lamp', 'building': 'B1',
          'host': {'ceiling': 'garage', 'u': 0.25, 'v': 0.75}}, ('B1', 'devices', 'device:dev_lamp')),
        # Another building: the invariant holds across the whole model.
        ({'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'sh-light'}, ('B2', 'anchor', 'sh-light')),
        ({'op': 'place_device', 'device': 'dev_lamp', 'building': 'B2',
          'host': {'floor': 'shed', 'u': 0.5, 'v': 0.5}}, ('B2', 'devices', 'device:dev_lamp')),
        ({'op': 'place_device', 'device': 'dev_lamp', 'building': 'B1',
          'host': {'opening': 'win1', 'side': 'in'}}, ('B1', 'devices', 'device:dev_lamp')),
    ]
    for op, where in steps:
        m = _apply(m, op)
        check(_places(m, 'dev_lamp') == [where], f'after {op}: one place {where}, got {_places(m, "dev_lamp")}')
    check(_entry(m, 'dev_lamp')['host'] == {'opening': 'win1', 'side': 'in'}, _entry(m, 'dev_lamp'))
    check(all(a['device'] is None for b in m['buildings'] for a in b['anchors']),
          [a for b in m['buildings'] for a in b['anchors']])

    # Unplace: gone from anchors and lists (it returns to its automatic spot).
    m = _apply(m, {'op': 'place_device', 'device': 'dev_lock', 'anchor': 'a-switch'})
    gone = _apply(m, {'op': 'unplace_device', 'device': 'dev_lamp'})
    check(_places(gone, 'dev_lamp') == [], _places(gone, 'dev_lamp'))
    check(_places(gone, 'dev_lock') == [('B1', 'anchor', 'a-switch')], 'other devices stay')
    gone = _apply(gone, {'op': 'unplace_device', 'device': 'dev_lock'})
    check(_places(gone, 'dev_lock') == [] and _by_id(_bld(gone)['anchors'], 'a-switch')['device'] is None,
          _bld(gone)['anchors'])


def test_occupied_anchor_refused():
    m1 = _apply(_house(), {'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-light'})
    words = _refused(m1, {'op': 'place_device', 'device': 'dev_garage_light', 'anchor': 'a-light'})
    check(words == OCCUPIED, words)
    # The device placing itself again on its own spot is not a conflict.
    m2 = _apply(m1, {'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-light'})
    check(_places(m2, 'dev_lamp') == [('B1', 'anchor', 'a-light')], _places(m2, 'dev_lamp'))
    # A refused move leaves the device where it was: an earlier placement is
    # removed only when the new one succeeds.
    m3 = _apply(m2, {'op': 'place_device', 'device': 'dev_garage_light', 'anchor': 'a-fan'})
    words = _refused(m3, {'op': 'place_device', 'device': 'dev_garage_light', 'anchor': 'a-light'})
    check(words == OCCUPIED, words)
    # Missing targets and bad hosts are refused in plain words.
    for op in ({'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'nope'},
               {'op': 'place_device', 'device': 'dev_lamp', 'building': 'B1',
                'host': {'opening': 'nope', 'side': 'in'}},
               {'op': 'place_device', 'device': 'dev_lamp', 'building': 'B1',
                'host': {'opening': 'd-front', 'side': 'up'}},
               {'op': 'place_device', 'device': '', 'anchor': 'a-switch'}):
        words = _refused(m3, op)
        check(isinstance(words, str) and words.strip(), f'{op}: {words!r}')


# ---------------------------------------------------------------- the opening host

def test_a_device_on_an_opening_sits_on_its_centre_line():
    m = _house()
    m = _apply(m, {'op': 'place_device', 'device': 'dev_lock', 'building': 'B1',
                   'host': {'opening': 'd-front', 'side': 'out'}})
    m = _apply(m, {'op': 'place_device', 'device': 'dev_up', 'building': 'B1',
                   'host': {'opening': 'd-up', 'side': 'in'}})
    m = _apply(m, {'op': 'place_device', 'device': 'dev_window', 'building': 'B1',
                   'host': {'opening': 'win1', 'side': 'in'}})
    # A door: 3.5 ft above its level. d-front: w from (0, 20) to (0, 0), at 10.
    point = _point(m, _entry(m, 'dev_lock'))
    check(close(point[2], 0 + 3.5) and _on_opening_line(point, [0, 20], [0, 0], 10, 0.5),
          f'd-front lock at (0, 10, 3.5): {point}')
    # A door upstairs: L2's elevation 10 + 3.5. d-up: u-s from (0, 0) to (12, 0), at 6.
    point = _point(m, _entry(m, 'dev_up'))
    check(close(point[2], 10 + 3.5) and _on_opening_line(point, [0, 0], [12, 0], 6, 0.5),
          f'd-up device at (6, 0, 13.5): {point}')
    # A window: the sill + 1 ft. win1: s1 from (0, 0) to (12, 0), at 6, sill 2.
    point = _point(m, _entry(m, 'dev_window'))
    check(close(point[2], 0 + 2 + 1) and _on_opening_line(point, [0, 0], [12, 0], 6, 0.5),
          f'win1 device at (6, 0, 3): {point}')


def test_lock_follows_its_door_when_the_wall_moves():
    m1 = _apply(_house(), {'op': 'place_device', 'device': 'dev_lock', 'building': 'B1',
                           'host': {'opening': 'd-front', 'side': 'out'}})
    before = _point(m1, _entry(m1, 'dev_lock'))
    # The west wall moves 3 ft out; the door rides it at the same distance.
    m2 = _apply(m1, {'op': 'move_wall', 'building': 'B1', 'wall': 'w', 'by': [-3, 0]})
    entry = _entry(m2, 'dev_lock')
    check(entry['host'] == {'opening': 'd-front', 'side': 'out'}, f'the host is the door still: {entry}')
    after = _point(m2, entry)
    check(close_pt(after, [before[0] - 3, before[1], before[2]]),
          f'the lock moves exactly 3 ft west with its door: {before} -> {after}')
    check(close(after[2], 3.5), after)
    check(not any(f.get('piece') == 'device:dev_lock' for f in _bld(m2)['flags']), _bld(m2)['flags'])

    # The door slides 4 ft along its wall; the lock goes with it.
    m3 = _apply(m2, {'op': 'move_hosted', 'building': 'B1', 'id': 'd-front', 'at': 14})
    moved = _point(m3, _entry(m3, 'dev_lock'))
    check(close_pt(moved, [after[0], after[1] - 4, after[2]]),
          f'the lock follows the door along the wall: {after} -> {moved}')


def test_deleting_the_door_unhosts_and_flags_the_lock():
    m1 = _apply(_house(), {'op': 'place_device', 'device': 'dev_lock', 'building': 'B1',
                           'host': {'opening': 'd-front', 'side': 'out'}})
    m2 = _apply(m1, {'op': 'delete', 'building': 'B1', 'id': 'd-front'})
    check(_by_id(_bld(m2)['openings'], 'd-front') is None, 'the door is gone')
    entry = _entry(m2, 'dev_lock')
    check(entry['device'] == 'dev_lock', f'kept, never silently deleted: {entry}')
    check(_places(m2, 'dev_lock') == [('B1', 'devices', 'device:dev_lock')], _places(m2, 'dev_lock'))
    flags = [f for f in _bld(m2)['flags'] if f.get('piece') == 'device:dev_lock']
    check(len(flags) == 1 and isinstance(flags[0].get('text'), str) and flags[0]['text'].strip(),
          f'one flag names the device: {_bld(m2)["flags"]}')
    check(flags[0].get('level') == 'L1' and math.dist(flags[0]['at'][:2], [0, 10]) <= 0.25 + TOL,
          f'flagged where the door was (0, 10) on L1, never the origin: {flags[0]}')
    # The flag survives a normalize and a further edit.
    m3 = _apply(m2, {'op': 'set', 'building': 'B1', 'id': 'kitchen', 'field': 'name', 'value': 'Cook room'})
    check(any(f.get('piece') == 'device:dev_lock' for f in _bld(m3)['flags']), _bld(m3)['flags'])
    # Placing it again clears the flag.
    m4 = _apply(m3, {'op': 'place_device', 'device': 'dev_lock', 'building': 'B1',
                     'host': {'opening': 'd-mid', 'side': 'in'}})
    check(not any(f.get('piece') == 'device:dev_lock' for f in _bld(m4)['flags']), _bld(m4)['flags'])
    check(_entry(m4, 'dev_lock')['host'] == {'opening': 'd-mid', 'side': 'in'}, _entry(m4, 'dev_lock'))


# ---------------------------------------------------------------- rooms to areas

def _set_area(room, value):
    return {'op': 'set', 'building': 'B1', 'id': room, 'field': 'ha_area', 'value': value}


def _room(model, rid):
    return _by_id(_bld(model)['rooms'], rid)


def test_set_area_by_name_stores_id():
    m0 = _house()
    with _ha(LIVE):
        m1 = _apply(m0, _set_area('bedroom', 'a_bed'))
        check(_room(m1, 'bedroom')['ha_area'] == 'a_bed', _room(m1, 'bedroom'))
        # A legacy name (any case) is stored as its area's id.
        m2 = _apply(m0, _set_area('bedroom', 'bedroom'))
        check(_room(m2, 'bedroom')['ha_area'] == 'a_bed', _room(m2, 'bedroom'))
        m3 = _apply(m0, _set_area('bedroom', 'BEDROOM'))
        check(_room(m3, 'bedroom')['ha_area'] == 'a_bed', _room(m3, 'bedroom'))
        # '' unlinks the room.
        m4 = _apply(m1, _set_area('bedroom', ''))
        check(_room(m4, 'bedroom')['ha_area'] == '', _room(m4, 'bedroom'))
    check(_room(m0, 'bedroom').get('ha_area') in (None, ''), 'apply leaves its input untouched')


def test_set_unknown_area_refused_only_when_ha_answers():
    m0 = _house()
    with _ha(LIVE):
        words = _refused(m0, _set_area('kitchen', 'Attic'))
        check(words == UNKNOWN_AREA, words)
        words = _refused(m0, _set_area('kitchen', 'a_attic'))
        check(words == UNKNOWN_AREA, words)
        m1 = _apply(m0, _set_area('kitchen', ''))
        check(_room(m1, 'kitchen')['ha_area'] == '', _room(m1, 'kitchen'))
    with _ha(OFFLINE):
        # Home Assistant gives no list: the value is stored as given.
        m2 = _apply(m0, _set_area('kitchen', 'Attic'))
        check(_room(m2, 'kitchen')['ha_area'] == 'Attic', _room(m2, 'kitchen'))
        check(all(not b.get('devices') for b in m2['buildings']), 'no devices without Home Assistant')
        m3 = _apply(m0, _set_area('kitchen', 'a_kitchen'))
        check(_room(m3, 'kitchen')['ha_area'] == 'a_kitchen', _room(m3, 'kitchen'))


def test_linking_the_garage_places_its_doors():
    m0 = _house()
    with _ha(LIVE):
        m1 = _apply(m0, _set_area('garage', 'Garage'))
    check(_room(m1, 'garage')['ha_area'] == 'a_garage', _room(m1, 'garage'))
    covers = ('dev_garage_left', 'dev_garage_right')
    hosted = {}
    for device in covers:
        entry = _entry(m1, device)
        check(entry['src'] == {'auto': True}, f'an obvious placement says so: {entry}')
        check(entry['host'].get('side') == 'in' and set(entry['host']) == {'opening', 'side'}, entry)
        hosted[device] = entry['host']['opening']
    check(sorted(hosted.values()) == ['g1', 'g2'], f'one garage door each: {hosted}')
    check(_places(m1, 'dev_garage_light') == [], 'a light is not obvious; it waits at its automatic spot')
    check(_places(m1, 'dev_lock') == [], 'only the linked room is placed')

    # The Kitchen's one exterior door takes the lock; its light is not obvious.
    with _ha(LIVE):
        m2 = _apply(m1, _set_area('kitchen', 'a_kitchen'))
    lock = _entry(m2, 'dev_lock')
    check(lock['host'] == {'opening': 'd-front', 'side': 'in'} and lock['src'] == {'auto': True}, lock)
    check(_places(m2, 'dev_lamp') == [], _places(m2, 'dev_lamp'))

    # The person can still move them, and linking again never moves them back.
    left_door = hosted['dev_garage_left']
    m3 = _apply(m2, {'op': 'place_device', 'device': 'dev_garage_left', 'building': 'B1',
                     'host': {'wall': 'e', 'side': 'right', 'at': 10, 'z': 8}})
    check(_entry(m3, 'dev_garage_left')['host'] == {'wall': 'e', 'side': 'right', 'at': 10, 'z': 8},
          _entry(m3, 'dev_garage_left'))
    with _ha(LIVE):
        m4 = _apply(m3, _set_area('garage', 'a_garage'))
    check(_entry(m4, 'dev_garage_left')['host'] == {'wall': 'e', 'side': 'right', 'at': 10, 'z': 8},
          f"the person's placement wins: {_entry(m4, 'dev_garage_left')}")
    check(_entry(m4, 'dev_garage_right')['host']['opening'] == hosted['dev_garage_right'],
          _entry(m4, 'dev_garage_right'))
    check(all(len(_places(m4, d)) == 1 for d in (*covers, 'dev_lock')),
          {d: _places(m4, d) for d in (*covers, 'dev_lock')})
    check(left_door in ('g1', 'g2'), left_door)


# ---------------------------------------------------------------- the bridge

def test_devices_survive_flatten_and_assemble():
    raw = _house_raw()
    b1 = raw['buildings'][0]
    _by_id(b1['anchors'], 'a-light')['device'] = 'dev_lamp'
    b1['devices'] = [
        {'id': 'device:dev_lock', 'device': 'dev_lock', 'host': {'opening': 'd-front', 'side': 'out'},
         'offset': 0, 'src': {'auto': True}},
        {'id': 'device:dev_cam', 'device': 'dev_cam', 'host': {'wall': 'e', 'side': 'left', 'at': 10, 'z': 8},
         'offset': 0.5, 'src': {'person': True}},
    ]
    model, _ = _model.normalize(raw)
    keys = ('id', 'device', 'host', 'offset', 'src')

    def summary(m):
        return ({b['id']: [{k: d.get(k) for k in keys} for d in b.get('devices', [])] for b in m['buildings']},
                {b['id']: {a['id']: a.get('device') for a in b.get('anchors', [])} for b in m['buildings']})

    want = summary(model)
    check(want[0]['B1'] == [{k: d[k] for k in keys} for d in b1['devices']] and want[0]['B2'] == [],
          f'normalize keeps the devices: {want[0]}')
    check(want[1]['B1']['a-light'] == 'dev_lamp', want[1])
    flat = _bridge.flatten(copy.deepcopy(model))
    for previous in (copy.deepcopy(model), None):
        back, _ = _bridge.assemble(copy.deepcopy(flat), previous)
        check(summary(back) == want, f'assemble(previous={"model" if previous else None}) keeps the '
                                     f'placements: {summary(back)} vs {want}')
    # And an edit on the round-tripped model still knows the lock's door.
    back, _ = _bridge.assemble(copy.deepcopy(flat), copy.deepcopy(model))
    point = _point(back, _entry(back, 'dev_lock'))
    check(close(point[2], 3.5) and _on_opening_line(point, [0, 20], [0, 0], 10, 0.5), point)


# ---------------------------------------------------------------- Argyle

TOKENS = {}


def _people():
    if not TOKENS:
        storage.add_member({'id': 'p1', 'name': 'Pat', 'role': 'parent'})
        storage.add_member({'id': 'k1', 'name': 'Kit', 'role': 'child'})
        TOKENS['seeded'] = True


def _flat_box(east=20):
    def wall(wid, a, b):
        return {'id': wid, 'level': 'L1', 'from': list(a), 'to': list(b), 'exterior': True,
                'thickness': 0.5, 'height': 9}
    return {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {},
            'site': {'lot': [[-20, -20], [80, -20], [80, 60], [-20, 60]]},
            'buildings': [{'id': 'b1', 'name': 'Test house', 'position': [0, 0], 'rotation': 0, 'base': 0,
                           'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9}],
                           'walls': [wall('s', (0, 0), (east, 0)), wall('e', (east, 0), (east, 10)),
                                     wall('n', (east, 10), (0, 10)), wall('w', (0, 10), (0, 0))],
                           'openings': [],
                           'rooms': [{'id': 'room-hall', 'level': 'L1', 'name': 'Hall',
                                      'polygon': [[0, 0], [east, 0], [east, 10], [0, 10]]}],
                           'roof': {'sections': [], 'extensions': []},
                           'stairs': [], 'fixtures': [], 'lights': [], 'porches': []}]}


def test_house_design_places_a_device():
    from services import agent_tools_v2
    _people()
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    ts.push_round(_flat_box(20), 'build')
    parent = storage.get_member('p1')

    def run(edit):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': edit}, actor=parent)
        check(out.get('status') == 'ok' and out.get('changed') is True, f'{edit["op"]}: {out}')
        return out

    run({'op': 'add_anchor', 'building': 'b1', 'kind': 'light',
         'host': {'ceiling': 'room-hall', 'u': 0.5, 'v': 0.5}})
    run({'op': 'add_opening', 'building': 'b1', 'wall': 's', 'kind': 'door', 'at': 6})
    b = ts.current_model()['buildings'][0]
    anchor = b['anchors'][0]['id']
    door = next(o['id'] for o in b['openings'] if o.get('wall') == 's')

    rounds = ts.current_id()
    run({'op': 'place_device', 'device': 'dev_lamp', 'anchor': anchor})
    check(ts.current_id() == rounds + 1, 'one placement, one round')
    run({'op': 'place_device', 'device': 'dev_lock', 'building': 'b1',
         'host': {'opening': door, 'side': 'out'}})
    b = ts.current_model()['buildings'][0]
    check(_by_id(b['anchors'], anchor)['device'] == 'dev_lamp', b['anchors'])
    lock = _by_id(b.get('devices', []), 'device:dev_lock')
    check(lock is not None and lock['host'] == {'opening': door, 'side': 'out'}, b.get('devices'))

    run({'op': 'unplace_device', 'device': 'dev_lamp'})
    b = ts.current_model()['buildings'][0]
    check(_by_id(b['anchors'], anchor)['device'] is None, b['anchors'])
    check(_by_id(b['devices'], 'device:dev_lock') is not None, 'the lock stays')

    # Only a parent places devices.
    child = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': {
        'op': 'place_device', 'device': 'dev_lamp', 'anchor': anchor}}, actor=storage.get_member('k1'))
    check(child.get('status') == 'refused', child)
    check(_by_id(ts.current_model()['buildings'][0]['anchors'], anchor)['device'] is None, 'nothing changed')

    # The tool tells Argyle the argument shapes, in the description's style.
    description = agent_tools_v2.TOOL_SCHEMAS['house_design']['properties']['edit']['description']
    for op, keys in (('place_device', ('device', 'anchor', 'host', 'offset', 'opening')),
                     ('unplace_device', ('device',))):
        marker = op + ' ('
        check(marker in description, f'{op} needs its argument shape')
        clause = description.split(marker, 1)[1].split(';', 1)[0]
        check(all(key in clause for key in keys), f'{op} needs {keys}: {clause}')
    # Terrain pads/foundations (3b64cdce) and porch foundations (5aa80b75)
    # add 681 characters to the former 4,376-character schema. Keep a bounded
    # budget with comparable headroom (5,057 today; previously capped at 4,500).
    check(len(json.dumps(agent_tools_v2.TOOL_SCHEMAS['house_design'])) <= 5600, 'keep the tool schema compact')  # stairs added


def test_i1a_catalogue_failure_keeps_the_area_link():
    from services import twin_edit
    with patch.object(twin_ha(), 'catalogue', side_effect=RuntimeError('HA stopped')):
        for edit in ({'op': 'set', 'building': 'B1', 'id': 'garage', 'field': 'ha_area', 'value': 'saved-area'},
                     {'op': 'set', 'building': 'B1', 'piece': 'garage', 'field': 'ha_area', 'value': 'saved-area'}):
            model, _ = twin_edit.apply_model(_house(), edit)
            check(_by_id(_bld(model)['rooms'], 'garage')['ha_area'] == 'saved-area', model)
            check(_bld(model)['devices'] == [], 'no guesses when HA is unavailable')


def test_i1b_save_reads_catalogue_once_outside_store_locks():
    from services import twin_edit
    import threading
    for key in ('id', 'piece'):
        storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
        shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
        ts.push_round(_bridge.flatten(_house()), 'build')
        ts.update_model(lambda _: _house())
        calls = []

        def catalogue():
            # Another thread must be able to acquire both locks during HA IO.
            free = []
            def probe():
                for lock in (ts.LIFECYCLE, ts._LOCK):
                    acquired = lock.acquire(timeout=0.1)
                    free.append(acquired)
                    if acquired:
                        lock.release()
            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(1)
            calls.append(free)
            return copy.deepcopy(LIVE)

        with patch.object(twin_ha(), 'catalogue', side_effect=catalogue):
            before = ts.current_id()
            twin_edit.save({'op': 'set', 'building': 'B1', key: 'garage',
                            'field': 'ha_area', 'value': 'Garage'}, 'p1')
        check(calls == [[True, True]], f'{key}: catalogue once, outside both locks: {calls}')
        result = ts.current_model()
        check(ts.current_id() == before + 1, 'link and placements share one round')
        check(_by_id(_bld(result)['rooms'], 'garage')['ha_area'] == 'a_garage', result)
        check(len(_bld(result)['devices']) == 2, 'same catalogue supplies obvious devices')


def test_i1c_unplaceable_obvious_device_never_blocks_link():
    model = _house()
    _by_id(_bld(model)['openings'], 'g1').update(state='ghost', why='No longer fits.')
    with _ha(LIVE):
        result = _apply(model, {'op': 'set', 'building': 'B1', 'id': 'garage',
                                'field': 'ha_area', 'value': 'a_garage'})
    check(_by_id(_bld(result)['rooms'], 'garage')['ha_area'] == 'a_garage', result)
    check([d['host']['opening'] for d in _bld(result)['devices']] == ['g2'], result)
    # Even a stale suggestion that refuses must not abort the person's link.
    suggestions = [{'device': 'bad', 'building': 'B1', 'host': {'opening': 'gone', 'side': 'in'}},
                   {'device': 'dev_garage_right', 'building': 'B1', 'host': {'opening': 'g2', 'side': 'in'}}]
    with _ha(LIVE), patch.object(twin_ha(), 'obvious', return_value=suggestions):
        result = _apply(_house(), {'op': 'set', 'building': 'B1', 'id': 'garage',
                                  'field': 'ha_area', 'value': 'a_garage'})
    check(_by_id(_bld(result)['rooms'], 'garage')['ha_area'] == 'a_garage', result)
    check(len(_places(result, 'dev_garage_right')) == 1 and not _places(result, 'bad'), result)


def test_i2_anchor_delete_retains_device_on_its_surface():
    from services import twin_edit
    for key in ('id', 'piece'):
        for lost in (False, True):
            model = _apply(_house(), {'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-light'})
            anchor = _by_id(_bld(model)['anchors'], 'a-light')
            anchor['offset'] = 0.35
            position = _hosts.world_point(_bld(model), anchor['host'], anchor['offset'])
            if lost:
                model = _apply(model, {'op': 'delete', 'building': 'B1', 'id': 'kitchen'})
                anchor = _by_id(_bld(model)['anchors'], 'a-light')
            saved = copy.deepcopy(anchor)
            result, _ = twin_edit.apply_model(model, {'op': 'delete', 'building': 'B1', key: 'a-light'})
            entry = _entry(result, 'dev_lamp')
            check(_by_id(_bld(result)['anchors'], 'a-light') is None, 'anchor deleted')
            check(all(entry[k] == saved[k] for k in ('host', 'offset', 'src')), entry)
            check(len(_places(result, 'dev_lamp')) == 1, result)
            if lost:
                check(entry.get('state') == 'ghost', entry)
                check(any(f.get('piece') == entry['id'] for f in _bld(result)['flags']), result)
            else:
                check(close_pt(_point(result, entry), position), entry)
    # Legacy level deletion also removes anchors as dependants.
    model = _apply(_house(), {'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-light'})
    result, _ = twin_edit.apply_model(model, {'op': 'delete', 'building': 'B1', 'piece': 'L1'})
    entry = _entry(result, 'dev_lamp')
    check(entry.get('state') == 'ghost', entry)
    check(any(f.get('piece') == entry['id'] for f in _bld(result)['flags']), result)


def test_m1_device_refusals_use_q8_copy():
    for op in ('place_device', 'unplace_device'):
        for value in ('', ' ', None, 42):
            check(_refused(_house(), {'op': op, 'device': value, 'anchor': 'a-light'}) == 'Choose a device.', value)
    for host in (None, {}, {'opening': 'nope', 'side': 'in'}, {'opening': 'd-front', 'side': 'up'},
                 {'wall': 'nope', 'at': 2, 'z': 4, 'side': 'left'}):
        words = _refused(_house(), {'op': 'place_device', 'device': 'dev_lamp', 'building': 'B1', 'host': host})
        check(words == 'Pick a wall, floor, ceiling or door for it.', words)


def test_m2_opening_inside_follows_room_not_wall_direction():
    for reverse in (False, True):
        model = _house()
        if reverse:
            _by_id(_bld(model)['walls'], 'w')['joints'].reverse()
        inside = _hosts.world_point(_bld(model), {'opening': 'd-front', 'side': 'in'}, 0.5)
        outside = _hosts.world_point(_bld(model), {'opening': 'd-front', 'side': 'out'}, 0.5)
        check(close_pt(inside, [0.75, 10, 3.5]), inside)
        check(close_pt(outside, [-0.75, 10, 3.5]), outside)


def test_m3_unplacing_unplaced_device_refuses_without_a_round():
    from services import twin_edit
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    ts.push_round(_bridge.flatten(_house()), 'build')
    before = ts.current_id()
    try:
        twin_edit.save({'op': 'unplace_device', 'device': 'not-placed'}, 'p1')
    except _ops.Refused as exc:
        check(str(exc) == 'Nothing changed.', str(exc))
    else:
        raise AssertionError('unplaced device must refuse')
    check(ts.current_id() == before, 'refusal must not write an empty round')


def test_m2_place_device_refuses_an_id_ha_does_not_list():
    """Final review M2: while Home Assistant lists devices, place_device refuses an id it
    does not list (a guessed 'kitchen_pendant' would be stored and never drawn); with
    no Home Assistant the id cannot be checked and is kept."""
    from services import agent_tools_v2, twin_edit
    import threading
    with _ha(LIVE):
        for op in ({'op': 'place_device', 'device': 'kitchen_pendant', 'anchor': 'a-light'},
                   {'op': 'place_device', 'device': 'kitchen_pendant', 'building': 'B1',
                    'host': {'ceiling': 'kitchen', 'u': 0.5, 'v': 0.5}}):
            check(_refused(_house(), op) == 'Choose a device.', op)
        placed = _apply(_house(), {'op': 'place_device', 'device': 'dev_lamp', 'anchor': 'a-light'})
        check(_by_id(_bld(placed)['anchors'], 'a-light')['device'] == 'dev_lamp', 'a listed id places')
    with _ha(OFFLINE):
        kept = _apply(_house(), {'op': 'place_device', 'device': 'kitchen_pendant', 'anchor': 'a-light'})
        check(_by_id(_bld(kept)['anchors'], 'a-light')['device'] == 'kitchen_pendant', 'no HA: kept')

    # Argyle's path reads the catalogue once, outside the store locks, and hears the sentence.
    _people()
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    ts.push_round(_bridge.flatten(_house()), 'build')
    ts.update_model(lambda _: _house())
    calls = []

    def catalogue():
        free = []

        def probe():
            for lock in (ts.LIFECYCLE, ts._LOCK):
                acquired = lock.acquire(timeout=0.1)
                free.append(acquired)
                if acquired:
                    lock.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(1)
        calls.append(free)
        return copy.deepcopy(LIVE)
    with patch.object(twin_ha(), 'catalogue', side_effect=catalogue):
        before = ts.current_id()
        out = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'building': 'B1', 'edit': {
            'op': 'place_device', 'device': 'kitchen_pendant', 'anchor': 'a-light'}}, actor=storage.get_member('p1'))
        check(out.get('status') == 'error' and out.get('message') == 'Choose a device.', out)
        check(ts.current_id() == before, 'a refused guess stores nothing')
        check(calls == [[True, True]], f'catalogue once, outside both locks: {calls}')
        twin_edit.save({'op': 'place_device', 'building': 'B1', 'device': 'dev_lamp', 'anchor': 'a-light'}, 'p1')
        check(_by_id(_bld(ts.current_model())['anchors'], 'a-light')['device'] == 'dev_lamp', 'a listed id saves')


def test_m2_house_design_lists_a_linked_rooms_devices():
    """Final review M2: Argyle learns device ids. Describing a linked room lists its
    area's devices with ids, names, kinds and placed state; status names the linked rooms."""
    from services import agent_tools_v2
    _people()
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    ts.push_round(_bridge.flatten(_house()), 'build')

    def linked(_):
        model = _house()
        _by_id(_bld(model)['rooms'], 'kitchen')['ha_area'] = 'a_kitchen'
        _by_id(_bld(model)['anchors'], 'a-light')['device'] = 'dev_lamp'
        return model
    ts.update_model(linked)
    parent = storage.get_member('p1')
    with _ha(LIVE):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'describe', 'piece': 'kitchen', 'building': 'B1'},
                                          actor=parent)
        check(out.get('status') == 'ok', out)
        rows = {d['device_id']: d for d in out.get('devices') or []}
        check(set(rows) == {'dev_lamp', 'dev_lock'}, ("the area's devices, no other area's", out))
        check(rows['dev_lamp'] == {'device_id': 'dev_lamp', 'name': 'Kitchen pendant', 'kind': 'light', 'placed': True},
              rows['dev_lamp'])
        check(rows['dev_lock']['placed'] is False, rows['dev_lock'])
        for words in ('dev_lamp', 'Kitchen pendant', 'dev_lock', 'Front door lock', 'not placed'):
            check(words in out['summary'], (words, out['summary']))
        status = agent_tools_v2.execute_tool('house_design', {'action': 'status'}, actor=parent)
        check('Kitchen (kitchen)' in status['summary'] and 'describe' in status['summary'].lower(), status['summary'])
        # An unlinked room lists nothing.
        garage = agent_tools_v2.execute_tool('house_design', {'action': 'describe', 'piece': 'garage', 'building': 'B1'},
                                             actor=parent)
        check(not garage.get('devices') and 'dev_' not in garage['summary'], garage)
    with _ha(OFFLINE):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'describe', 'piece': 'kitchen', 'building': 'B1'},
                                          actor=parent)
        check(out.get('status') == 'ok' and not out.get('devices'), out)


TESTS = (
    test_place_on_anchor_then_move_to_wall,
    test_one_device_one_place,
    test_occupied_anchor_refused,
    test_a_device_on_an_opening_sits_on_its_centre_line,
    test_lock_follows_its_door_when_the_wall_moves,
    test_deleting_the_door_unhosts_and_flags_the_lock,
    test_set_area_by_name_stores_id,
    test_set_unknown_area_refused_only_when_ha_answers,
    test_linking_the_garage_places_its_doors,
    test_devices_survive_flatten_and_assemble,
    test_house_design_places_a_device,
    test_i1a_catalogue_failure_keeps_the_area_link,
    test_i1b_save_reads_catalogue_once_outside_store_locks,
    test_i1c_unplaceable_obvious_device_never_blocks_link,
    test_i2_anchor_delete_retains_device_on_its_surface,
    test_m1_device_refusals_use_q8_copy,
    test_m2_opening_inside_follows_room_not_wall_direction,
    test_m3_unplacing_unplaced_device_refuses_without_a_round,
    test_m2_place_device_refuses_an_id_ha_does_not_list,
    test_m2_house_design_lists_a_linked_rooms_devices,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
