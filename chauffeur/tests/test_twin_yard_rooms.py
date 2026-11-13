"""Outdoor rooms: real operations/history and the HTTP HA live hand path.

Run from chauffeur/: python tests/test_twin_yard_rooms.py
"""
import copy
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ.pop('HA_BASE_URL', None)
os.environ['PYTHONIOENCODING'] = 'utf-8'
# Create with ordinary directory permissions: Python 3.13's Windows mkdtemp
# ACL prevents this sandbox's worker threads from opening SQLite in that dir.
DATA = Path(tempfile.gettempdir()) / ('chauffeur_yard_rooms_' + uuid.uuid4().hex)
DATA.mkdir()
os.environ['CHAUFFEUR_DATA_DIR'] = str(DATA)

from services import storage, twin_ha, twin_model, twin_model_bridge as bridge
from services import twin_model_ops as ops, twin_plan, twin_site_shapes as shapes, twin_store as store
import test_twin_ha_routes as routes

RECT = [[5, 5], [25, 5], [25, 15], [5, 15]]
OFFLINE = {'available': False, 'areas': [], 'floors': [], 'devices': []}


def model():
    return twin_model.normalize({'units': 'ft', 'buildings': [], 'site': {
        'lot': [[0, 0], [100, 0], [100, 100], [0, 100]],
        'pool': {'id': 'pool', 'polygon': RECT, 'depth': 5, 'coping': 1},
        'hardscape': [{'id': 'patio', 'polygon': RECT}],
        'fire_pit': {'id': 'pit', 'shape': 'round', 'at': [50, 50], 'radius': 2},
    }})[0]


def add(base=None, name='Pool deck', polygon=None, **extra):
    return ops.apply(base or model(), {'op': 'add_site_shape', 'list': 'yard_rooms',
                                      'name': name, 'polygon': polygon or RECT, **extra})[0]


def refused(base, operation):
    before = copy.deepcopy(base)
    try:
        ops.apply(base, operation, ha_catalogue=OFFLINE)
    except ops.Refused:
        assert base == before, 'refused edits must leave the input untouched'
    else:
        raise AssertionError(f'Accepted invalid operation: {operation}')


def place(base, device='dev-k-lamp', u=.5, v=.5, offset=3):
    return ops.apply(base, {'op': 'place_device', 'device': device,
                           'host': {'yard_room': base['site']['yard_rooms'][0]['id'], 'u': u, 'v': v},
                           'offset': offset}, ha_catalogue=OFFLINE)[0]


def seed(base):
    storage.patch_settings({'house_twin': None})
    shutil.rmtree(store.DATA_DIR, ignore_errors=True)
    store.push_round(bridge.flatten(base), 'build')


def test_agent_tool_edits_status_and_describe_share_the_real_save_path():
    from services import agent_tools_v2, twin_edit
    actor_id = 'yard-agent-parent'
    if not storage.get_member(actor_id):
        storage.add_member({'id': actor_id, 'name': 'Yard parent', 'role': 'parent', 'status': 'active'})
    actor = storage.get_member(actor_id)
    catalogue = {'available': True, 'areas': [{'area_id': 'patio', 'name': 'Patio'}], 'floors': [],
                 'devices': [{'device_id': did, 'name': name, 'kind': 'light', 'area_id': area,
                              'entity_id': eid, 'entities': [eid]}
                             for did, name, area, eid in [('area-light', 'Patio lamp', 'patio', 'light.patio'),
                                                         ('placed-light', 'Grill lamp', None, 'light.grill')]]}

    def read_catalogue():
        assert not store.LIFECYCLE._is_owned(), 'HA must be fetched before acquiring lifecycle lock'
        assert not store._LOCK._is_owned(), 'HA must be fetched before acquiring store lock'
        return copy.deepcopy(catalogue)

    def tool(action, **args):
        result = agent_tools_v2.execute_tool('house_design', {'action': action, **args}, actor=actor)
        assert result.get('status') == 'ok', result
        return result

    seed(model())
    with patch.object(twin_ha, 'safe_catalogue', side_effect=read_catalogue) as reads, \
            patch.object(twin_edit, 'save', wraps=twin_edit.save) as save:
        count = len(store.rounds())
        tool('edit', edit={'op': 'add_site_shape', 'list': 'yard_rooms', 'name': 'Grill station',
                           'polygon': RECT, 'ha_area': 'Patio'})
        assert save.call_count == 1 and reads.call_count == 1
        assert len(store.rounds()) == count + 1
        room = store.current_model()['site']['yard_rooms'][0]
        rid = room['id']
        assert room['ha_area'] == 'patio'
        reads.reset_mock()
        shifted = [[x + 1, y + 1] for x, y in RECT]
        tool('edit', edit={'op': 'update_site_shape', 'list': 'yard_rooms', 'id': rid,
                           'name': 'Outdoor kitchen', 'polygon': shifted, 'ha_area': 'PATIO'})
        assert save.call_count == 2 and reads.call_count == 1, 'area update must prefetch once'
        room = store.current_model()['site']['yard_rooms'][0]
        assert (room['name'], room['polygon'], room['ha_area']) == ('Outdoor kitchen', shifted, 'patio')
        tool('edit', edit={'op': 'place_device', 'device': 'placed-light',
                           'host': {'yard_room': rid, 'u': .5, 'v': .5}, 'offset': 3})
        status = tool('status')
        assert 'Yard rooms:' in status['summary'] and 'Outdoor kitchen' in status['summary'] and rid in status['summary']
        described = tool('describe', piece=rid)
        members = {d['device_id']: d for d in described['devices']}
        assert set(members) == {'area-light', 'placed-light'}, described
        assert members['placed-light']['placed'] and not members['area-light']['placed']
        assert 'Outdoor kitchen' in described['summary'] and 'placed-light' in described['summary']
        deleted = tool('edit', edit={'op': 'delete_site_item', 'list': 'yard_rooms', 'id': rid})
        assert 'Unplaced 1 device' in deleted['summary']
        assert store.current_model()['site']['yard_rooms'] == []
        assert store.current_model()['site']['devices'] == []
        assert save.call_count == 4, 'add, update, place and delete all use twin_edit.save'


def test_validation_names_and_three_to_two_hundred_simple_corners():
    for name in ('X', 'X' * 40):
        assert add(name=name)['site']['yard_rooms'][0]['name'] == name
    triangle = [[1, 1], [3, 1], [1, 3]]
    assert len(add(polygon=triangle)['site']['yard_rooms'][0]['polygon']) == 3
    circle = [[50 + 20 * math.cos(i * math.tau / 200),
               50 + 20 * math.sin(i * math.tau / 200)] for i in range(200)]
    assert len(add(polygon=circle)['site']['yard_rooms'][0]['polygon']) == 200
    invalid = [{'name': ''}, {'name': '   '}, {'name': 'X' * 41}, {'name': None},
               {'polygon': RECT[:2]}, {'polygon': circle + [[60, 60]]},
               {'polygon': [[1, 1], [9, 9], [1, 9], [9, 1]]},
               {'polygon': [[1, 1], [2, 1], [3, 1]]},
               {'polygon': [[1, 1], [float('nan'), 2], [3, 1]]}]
    for change in invalid:
        operation = {'op': 'add_site_shape', 'list': 'yard_rooms', 'name': 'Room', 'polygon': RECT, **change}
        refused(model(), operation)
        existing = add()
        refused(existing, {'op': 'update_site_shape', 'list': 'yard_rooms',
                           'id': existing['site']['yard_rooms'][0]['id'], **change})
        raw = bridge.flatten(model())
        raw['site']['yard_rooms'] = [{'id': 'bad-room', 'name': 'Room', 'polygon': RECT, **change}]
        normalized, notes = twin_plan.normalize(raw)
        assert normalized['site']['yard_rooms'] == [] and any('yard_rooms' in n for n in notes)
    # Regions can cover ground geometry; adding this outline overlaps the pool
    # and patio rather than cutting either physical feature.
    made = add()
    assert made['site']['pool']['polygon'] == RECT
    assert made['site']['hardscape'][0]['polygon'] == RECT


def test_ha_link_suggestions_and_area_names_resolve_like_indoor_rooms():
    catalogue = {'available': True, 'areas': [{'area_id': 'patio', 'name': 'Patio', 'floor_level': None}],
                 'devices': [], 'floors': []}
    base = add(name='Patio')
    rid = base['site']['yard_rooms'][0]['id']
    assert twin_ha.suggest(base, catalogue['areas']) == {rid: 'patio'}
    changed, _ = ops.apply(base, {'op': 'update_site_shape', 'list': 'yard_rooms', 'id': rid,
                                  'ha_area': 'PATIO'}, ha_catalogue=catalogue)
    assert changed['site']['yard_rooms'][0]['ha_area'] == 'patio'
    assert twin_ha.gone_rooms(changed, catalogue['areas']) == []
    assert twin_ha.count_notes(changed, rid, catalogue) == []
    assert twin_ha.obvious(changed, rid, catalogue) == []
    before = copy.deepcopy(base)
    try:
        ops.apply(base, {'op': 'update_site_shape', 'list': 'yard_rooms', 'id': rid,
                         'ha_area': 'unknown'}, ha_catalogue=catalogue)
    except ValueError:
        pass
    else:
        raise AssertionError('Unknown HA areas must be refused while HA lists areas')
    assert base == before
    offline, _ = ops.apply(base, {'op': 'update_site_shape', 'list': 'yard_rooms', 'id': rid,
                                  'ha_area': 'My outside area'}, ha_catalogue=OFFLINE)
    assert offline['site']['yard_rooms'][0]['ha_area'] == 'My outside area'
    unlinked, _ = ops.apply(changed, {'op': 'update_site_shape', 'list': 'yard_rooms', 'id': rid,
                                    'ha_area': None}, ha_catalogue=catalogue)
    assert unlinked['site']['yard_rooms'][0]['ha_area'] is None


def test_immutable_ops_roundtrip_and_history_undo_redo():
    original = model()
    before = copy.deepcopy(original)
    made = add(original)
    assert original == before
    room_id = made['site']['yard_rooms'][0]['id']
    shifted = [[x + 2, y + 4] for x, y in RECT]
    changed, _ = ops.apply(made, {'op': 'update_site_shape', 'list': 'yard_rooms', 'id': room_id,
                                 'name': 'Evening deck', 'polygon': shifted, 'ha_area': 'patio'})
    assert made['site']['yard_rooms'][0]['name'] == 'Pool deck'
    room = changed['site']['yard_rooms'][0]
    assert (room['name'], room['polygon'], room['ha_area']) == ('Evening deck', shifted, 'patio')
    assert bridge.assemble(bridge.flatten(changed))[0]['site']['yard_rooms'] == changed['site']['yard_rooms']
    seed(original)
    initial = store.current_id()
    count = len(store.rounds())
    created = store.update_model(lambda m: ops.apply(m, {'op': 'add_site_shape', 'list': 'yard_rooms',
                                                        'name': 'Pool deck', 'polygon': RECT})[0])
    assert len(store.rounds()) == count + 1
    rid = store.current_model()['site']['yard_rooms'][0]['id']
    edited = store.update_model(lambda m: ops.apply(m, {'op': 'update_site_shape', 'list': 'yard_rooms',
                                                       'id': rid, 'name': 'Evening deck', 'polygon': shifted,
                                                       'ha_area': 'patio'})[0])
    store.revert(created)
    assert store.current_model()['site']['yard_rooms'][0]['name'] == 'Pool deck'
    store.revert(edited)
    assert store.current_model()['site']['yard_rooms'][0]['polygon'] == shifted
    store.revert(initial)
    assert store.current_model()['site']['yard_rooms'] == []
    store.revert(edited)
    removed = store.update_model(lambda m: ops.apply(m, {'op': 'delete_site_item', 'list': 'yard_rooms', 'id': rid})[0])
    assert store.current_model()['site']['yard_rooms'] == []
    store.revert(edited)
    assert store.current_model()['site']['yard_rooms'][0]['ha_area'] == 'patio'
    store.revert(removed)
    assert store.current_model()['site']['yard_rooms'] == []


def test_make_room_pool_patio_and_round_fire_pit_are_one_history_step():
    for collection, feature, expected in [('pool', 'pool', 'Pool'), ('hardscape', 'patio', 'Patio'),
                                          ('fire_pit', 'pit', 'Fire pit')]:
        original = model()
        seed(original)
        before = store.current_id()
        count = len(store.rounds())
        after = store.update_model(lambda m: ops.apply(m, {'op': 'make_yard_room', 'list': collection, 'id': feature})[0])
        current = store.current_model()
        room = current['site']['yard_rooms'][0]
        assert room['name'] == expected and len(store.rounds()) == count + 1
        assert current['site'][collection] == original['site'][collection]
        if collection == 'fire_pit':
            assert len(room['polygon']) >= 16
            assert all(abs(math.dist(p, [50, 50]) - 3.5) < 1e-8 for p in room['polygon'])
        else:
            assert room['polygon'] == RECT
        store.revert(before)
        assert store.current_model()['site']['yard_rooms'] == []
        store.revert(after)
        assert store.current_model()['site']['yard_rooms'][0] == room


def test_ground_hosts_concave_outline_and_height_and_unplace_message():
    ell = [[0, 0], [12, 0], [12, 4], [4, 4], [4, 12], [0, 12]]
    base = add(polygon=ell)
    rid = base['site']['yard_rooms'][0]['id']
    made = place(base, u=.2, v=.7, offset=6.25)
    assert math.dist(shapes.yard_device_point(made['site'], made['site']['devices'][0]), [2.4, 8.4]) < 1e-8
    assert twin_ha.yard_spot(made, twin_ha.placements(made)['dev-k-lamp'])['z'] == 6.25
    operation = {'op': 'place_device', 'device': 'dev-k-lamp', 'host': {'yard_room': rid, 'u': .8, 'v': .8}}
    refused(base, operation)  # The bounding-box notch is outside the actual room.
    for height in (-.01, 100.01, True, float('nan')):
        refused(base, {**operation, 'host': {'yard_room': rid, 'u': .2, 'v': .7}, 'offset': height})
    for host in ({'yard_room': rid, 'u': -1, 'v': .2}, {'yard_room': 'gone', 'u': .2, 'v': .2}):
        refused(base, {**operation, 'host': host})
    assert bridge.assemble(bridge.flatten(made))[0]['site']['devices'] == made['site']['devices']
    unplaced, words = ops.apply(made, {'op': 'unplace_device', 'device': 'dev-k-lamp'})
    assert unplaced['site']['devices'] == [] and 'placement' in words
    deleted, words = ops.apply(made, {'op': 'delete_site_item', 'list': 'yard_rooms', 'id': rid})
    assert deleted['site']['yard_rooms'] == [] and deleted['site']['devices'] == []
    assert 'Unplaced 1 device' in words and 'remain in Home Assistant' in words
    assert len(made['site']['devices']) == 1, 'deleting must not mutate its input'
    seed(made)
    before = store.current_id()
    after = store.update_model(lambda m: ops.apply(m, {'op': 'delete_site_item', 'list': 'yard_rooms', 'id': rid})[0])
    store.revert(before)
    assert store.current_model()['site']['devices'][0]['device'] == 'dev-k-lamp'
    store.revert(after)
    assert store.current_model()['site']['devices'] == []


def live_model(link='patio'):
    base = add(routes._house(), ha_area=link)
    return place(base, u=.25, v=.75, offset=6.25)


def test_live_linked_yard_auto_and_explicit_no_area_devices_permission_and_stream():
    seed(live_model())
    rid = store.current_model()['site']['yard_rooms'][0]['id']
    with routes.Ctx() as c:
        c.ha.move_device('dev-k-lamp', None)
        next(d for d in c.ha.devices if d['id'] == 'dev-k-lamp')['name'] = 'Unassigned lamp'
        c.ha.states['light.kitchen_lamp']['attributes']['friendly_name'] = 'Unassigned lamp'
        grid = routes.cr.default_rules({})
        grid['places']['panel']['lights'] = 'no'
        c.extra['ha_control'] = grid
        body = c.client.get(routes.LIVE, headers=c.panel).json()
        room = next(r for r in body['rooms'] if r['room'] == rid)
        assert room['yard'] and room['building'] is None and room['level'] is None and room['area_id'] == 'patio'
        assert room['polygon_world'] == RECT
        explicit = routes.marker_for(body, 'dev-k-lamp')
        auto = routes.marker_for(body, 'dev-patio-light')
        assert explicit['at'] == [10, 12.5, 6.25] and explicit['placed']
        assert explicit['yard'] and explicit['building'] is None and explicit['level'] is None and explicit['room'] == rid
        assert auto['room'] == rid and not auto['placed'] and auto['at'][2] == 0
        assert twin_ha._inside(auto['at'][:2], RECT)
        assert not explicit['offered'] and not auto['offered']
        assert 'light.kitchen_lamp' in room['lights']
        device = next(d for d in body['devices'] if d['device_id'] == 'dev-k-lamp')
        assert device['area_id'] is None and device['room'] == rid and device['yard']
        import main
        assert {'light.kitchen_lamp', 'light.patio'} <= main._house_stream_entities()
        assert {'light.kitchen_lamp', 'light.patio'} <= main._house_stream_entities('patio')
        grid['places']['panel']['lights'] = 'yes'
        allowed = c.client.get(routes.LIVE, headers=c.panel).json()
        assert routes.marker_for(allowed, 'dev-k-lamp')['offered']
        linked = c.client.get(routes.LINK, headers=c.mum).json()
        assert next(r for r in linked['rooms'] if r['room'] == rid)['yard']


def test_ha_absent_or_unlinked_yard_has_no_markers_and_remains_a_room():
    for available, linked in ((False, 'patio'), (True, None)):
        seed(live_model(linked))
        rid = store.current_model()['site']['yard_rooms'][0]['id']
        with routes.Ctx(available=available) as c:
            response = c.client.get(routes.LIVE, headers=c.mum)
            assert response.status_code == 200, response.text
            body = response.json()
            assert next(r for r in body['rooms'] if r['room'] == rid)['yard']
            assert not any(m.get('yard') for m in body['markers'])


if __name__ == '__main__':
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith('test_') and callable(fn)]
    passed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f'ok   {fn.__name__}', flush=True)
        except Exception:
            print(f'FAIL {fn.__name__}', flush=True)
            traceback.print_exc(limit=6)
    print(f'{passed}/{len(tests)} passed')
    storage.db.close()
    sys.exit(0 if passed == len(tests) else 1)
