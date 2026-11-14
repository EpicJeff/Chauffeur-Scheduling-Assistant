"""Drawn pool features through the parent HTTP gate, real store and normalizer."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_pool_features_')
from services import twin_model_bridge as bridge, twin_plan, twin_store
from test_twin_model_ops_more import _client, _people, _enforced


def rect(x, y, w=4, h=4):
    return [[x, y], [x+w, y], [x+w, y+h], [x, y+h]]


def seed():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    fixture['site']['pool'] = {'id': 'pool', 'polygon': rect(0, 0, 30, 20), 'depth': 5, 'coping': 1}
    twin_store.push_round(fixture, 'build')


def post(op, status=200, who='parent'):
    before, count = twin_store.current_id(), len(twin_store.rounds())
    with _enforced():
        response = _client().post('/api/house/editor/op', headers=_people()[who], json={'op': op})
    assert response.status_code == status, response.text
    if status != 200:
        assert twin_store.current_id() == before and len(twin_store.rounds()) == count
        return response.json()
    assert len(twin_store.rounds()) == count + 1, 'one edit is one round'
    return response.json()['plan']


def add(kind, **extra):
    plan = post({'op': 'add_pool_feature', 'kind': kind, 'polygon': rect(0, 0, 6, 4), **extra})
    return plan['site']['pool']['features'][-1]


def test_add_update_delete_each_kind_and_undo_redo():
    for kind, field, value in [('ledge', 'depth_in', 14), ('steps', 'treads', 5), ('spa', 'mode', 'flush')]:
        seed()
        start = twin_store.current_id()
        f = add(kind)
        added = twin_store.current_id()
        assert f['kind'] == kind and len(f['polygon']) == 4
        if kind == 'ledge':
            assert f['depth_in'] == 10
        elif kind == 'steps':
            assert f['treads'] == 3 and f['entry_edge'] == 0
        else:
            assert all(f[k] == v for k, v in {'mode': 'raised', 'raise_in': 12, 'depth_in': 36, 'spillover': True}.items())
        changed = post({'op': 'update_pool_feature', 'id': f['id'], field: value})
        updated = twin_store.current_id()
        assert changed['site']['pool']['features'][0][field] == value
        assert not post({'op': 'delete_pool_feature', 'id': f['id']})['site']['pool']['features']
        deleted = twin_store.current_id()
        for round_id, expected in [(start, []), (added, [f]), (updated, changed['site']['pool']['features']), (deleted, [])]:
            with _enforced():
                response = _client().post('/api/house/twin/revert', headers=_people()['parent'], json={'round': round_id})
            assert response.status_code == 200, response.text
            assert twin_store.current_model()['site']['pool'].get('features', []) == expected


def test_parents_only_for_all_feature_ops_and_spa_room():
    seed()
    f = add('spa')
    for op in [{'op': 'add_pool_feature', 'kind': 'ledge', 'polygon': rect(0, 0)},
               {'op': 'update_pool_feature', 'id': f['id'], 'depth_in': 40},
               {'op': 'delete_pool_feature', 'id': f['id']},
               {'op': 'make_yard_room', 'list': 'pool', 'feature': f['id']}]:
        post(op, 403, who='child')


def test_ranges_topology_and_containment_are_refused():
    seed()
    for kind, changes in [('ledge', [{'depth_in': 5}, {'depth_in': 19}, {'depth_in': True}, {'depth_in': float('inf')},
                                   {'polygon': rect(29, 0)}, {'polygon': [[0, 0], [4, 4], [0, 4], [4, 0]]}]),
                          ('steps', [{'treads': 0}, {'treads': 7}, {'treads': 2.5}, {'treads': True},
                                     {'entry_edge': -1}, {'entry_edge': 4}, {'entry_edge': False}, {'polygon': rect(-1, 0)}]),
                          ('spa', [{'mode': 'sunken'}, {'raise_in': 5}, {'raise_in': 25}, {'depth_in': 23}, {'depth_in': 49},
                                   {'spillover': 'yes'}, {'polygon': rect(32.1, 0)}, {'materials': {'water': {'id': 'red_brick_03'}}}])]:
        for change in changes:
            # JSON disallows infinity: exercise the validator directly for nonfinite values.
            if change.get('depth_in') == float('inf'):
                from services.twin_site_shapes import pool_feature
                try:
                    pool_feature(twin_store.current_model()['site']['pool'], {'id': 'bad', 'kind': kind, 'polygon': rect(0, 0), **change})
                except ValueError:
                    continue
                raise AssertionError('accepted infinity')
            post({'op': 'add_pool_feature', 'kind': kind, 'polygon': rect(0, 0), **change}, 400)
    f = add('steps')
    post({'op': 'update_pool_feature', 'id': f['id'], 'entry_edge': 12}, 400)
    post({'op': 'update_pool_feature', 'id': f['id'], 'kind': 'spa'}, 400)
    post({'op': 'delete_pool_feature', 'id': 'missing'}, 400)


def test_concave_pool_and_default_entry_edge():
    seed()
    pool = [[0, 0], [10, 0], [10, 10], [6, 10], [6, 4], [4, 4], [4, 10], [0, 10]]
    post({'op': 'update_site_shape', 'list': 'pool', 'polygon': pool})
    # All corners inside, but the polygon bridges the notch.
    post({'op': 'add_pool_feature', 'kind': 'ledge', 'polygon': [[3, 5], [7, 5], [7, 8], [3, 8]]}, 400)
    f = add('steps', polygon=rect(1, 0, 3, 2))
    assert f['entry_edge'] == 0
    post({'op': 'update_pool_feature', 'id': f['id'], 'entry_edge': 2})


def test_spa_locations_slots_and_room():
    seed()
    for polygon in [rect(2, 2), rect(28, 2), rect(30, 2), rect(32, 2)]:
        f = add('spa', polygon=polygon)
        post({'op': 'delete_pool_feature', 'id': f['id']})
    f = add('spa', polygon=rect(28, 2))
    slots = {'coping': {'id': 'red_brick_03'}, 'interior': {'id': 'mocha_oak_veneer'}, 'wall': {'id': 'red_brick_03', 'color': '#123456'}}
    plan = post({'op': 'update_pool_feature', 'id': f['id'], 'materials': slots})
    assert plan['site']['pool']['features'][0]['materials'] == slots
    plan = post({'op': 'update_pool_feature', 'id': f['id'], 'materials': {'coping': None}})
    assert plan['site']['pool']['features'][0]['materials'] == {k: v for k, v in slots.items() if k != 'coping'}
    post({'op': 'update_pool_feature', 'id': f['id'], 'materials': {'wall': {'id': 'fake'}}}, 400)
    plan = post({'op': 'make_yard_room', 'list': 'pool', 'feature': f['id']})
    room = plan['site']['yard_rooms'][-1]
    assert room['name'] == 'Spa' and room['polygon'] == f['polygon']
    assert room['feature'] == {'list': 'pool', 'id': 'pool', 'feature': f['id']}
    assert plan['site']['pool']['features'][0]['polygon'] == f['polygon']
    post({'op': 'delete_pool_feature', 'id': f['id']})
    replacement = add('spa')
    assert replacement['id'] != f['id'], 'a new spa never steals a saved room source id'
    ledge = add('ledge')
    post({'op': 'make_yard_room', 'list': 'pool', 'feature': ledge['id']}, 400)


def test_normalize_drops_bad_feature_keeps_pool_and_bridge():
    seed()
    f = add('spa')
    plan = bridge.flatten(twin_store.current_model())
    pool = plan['site']['pool']
    pool['features'] += [dict(f, id='bad', depth_in=500), None, dict(f, id='crossed', polygon=[[0, 0], [4, 4], [0, 4], [4, 0]])]
    normalized, notes = twin_plan.normalize(plan)
    assert normalized['site']['pool']['polygon'] == pool['polygon']
    assert normalized['site']['pool']['features'] == [f]
    assert sum('Dropped pool feature:' in n for n in notes) == 3
    roundtrip = bridge.flatten(bridge.assemble(normalized)[0])
    assert roundtrip['site']['pool']['features'] == [f]
    for bad in (None, {}, 'spa'):
        altered = copy.deepcopy(normalized)
        altered['site']['pool']['features'] = bad
        result, notes = twin_plan.normalize(altered)
        assert result['site']['pool']['features'] == [] and notes
    altered = copy.deepcopy(normalized)
    altered['site']['pool']['features'][0]['materials'] = {'wall': {'id': 'missing'}}
    result, notes = twin_plan.normalize(altered)
    assert len(result['site']['pool']['features']) == 1 and 'materials' not in result['site']['pool']['features'][0]
    assert any('Reset spa materials' in n for n in notes)


def test_limit_and_pool_transforms_keep_features():
    seed()
    for _ in range(12):
        add('ledge')
    post({'op': 'add_pool_feature', 'kind': 'spa', 'polygon': rect(0, 0)}, 400)
    before = twin_store.current_model()['site']['pool']['features'][0]['polygon']
    moved = post({'op': 'move_site_item', 'list': 'pool', 'by': [4, 2]})
    assert moved['site']['pool']['features'][0]['polygon'] == [[x+4, y+2] for x, y in before]
    post({'op': 'update_site_shape', 'list': 'pool', 'rotation': 90})


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    try:
        for test in tests:
            try:
                test()
                passed += 1
                print('ok', test.__name__)
            except Exception:
                traceback.print_exc(limit=8)
                print('FAIL', test.__name__)
    finally:
        from services import storage
        storage.db.close()
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
