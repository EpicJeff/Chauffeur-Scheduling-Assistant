"""Saved lighting identity, conservative exclusions and real HTTP propagation."""
from copy import deepcopy
import json
from pathlib import Path
import statistics
import sys
import timeit

from test_twin_server_speed import house, ts, storage, OP, STATE
from services.twin_lighting_rev import lighting_fingerprint as fingerprint

FIXTURE = Path(__file__).parent / 'fixtures/twin_model/household-2026-11-09.json'


def test_content():
    model = json.loads(FIXTURE.read_text(encoding='utf8'))
    original = deepcopy(model)
    baked = fingerprint(model)
    for field in ('hidden', 'locked'):
        changed = deepcopy(model)
        changed['buildings'][0]['walls'][0][field] = True
        assert fingerprint(changed) != baked, ('a model flag of this name could remove geometry', field)
    for field, value in [('name', 'Renamed'), ('label', 'Display label'), ('notes', ['A note']),
                         ('src', {'person': True})]:
        changed = deepcopy(model)
        changed['buildings'][0][field] = value
        assert fingerprint(changed) == baked, field
        for pieces in ('levels', 'walls', 'rooms', 'openings'):
            changed = deepcopy(model)
            changed['buildings'][0][pieces][0][field] = value
            assert fingerprint(changed) == baked, (pieces, field)
    changed = deepcopy(model)
    changed['camera_views'] = {'camera.front': {'at': [10, 20, 5], 'facing': 90}}
    assert fingerprint(changed) == baked
    mutations = {
        'wall': lambda m: m['buildings'][0]['walls'][0]['to'].__setitem__(0, 99),
        'opening': lambda m: m['buildings'][0]['openings'][0].__setitem__('width', 9),
        'light': lambda m: m['buildings'][0]['lights'].append({'id': 'new', 'at': [1, 2, 3]}),
        'material': lambda m: m['buildings'][0]['walls'][0].__setitem__('material', {'id': 'new'}),
        'terrace': lambda m: m['site']['terraces'].append({'polygon': [[0, 0], [5, 0], [5, 5]], 'elevation': 2}),
        'roof': lambda m: m['buildings'][0]['roof']['sections'][0].__setitem__('pitch', 12),
        'unknown': lambda m: m.__setitem__('future_lighting', {'name': 'counts', 'value': 1}),
        'unknown nested': lambda m: m['buildings'][0].__setitem__('future', {'name': 'counts'}),
        'material role name': lambda m: m['materials'].__setitem__('name', {'id': 'counts'}),
        'ha hidden': lambda m: m.__setitem__('ha_display', {'hidden': {'devices': ['lamp']}}),
    }
    for label, mutate in mutations.items():
        changed = deepcopy(model)
        mutate(changed)
        assert fingerprint(changed) != baked, label
    assert fingerprint(json.loads(json.dumps(model, sort_keys=True))) == baked
    assert fingerprint(deepcopy(model)) == baked
    with_light = deepcopy(model)
    with_light['light_fixtures'] = {'light.test': [{'id': 'lamp', 'shape': 'point', 'at': [1, 2, 3]}]}
    light_bake = fingerprint(with_light)
    with_light['light_fixtures']['light.test'][0]['at'][0] += .1
    assert fingerprint(with_light) != light_bake, 'moving an existing light'
    future = deepcopy(model)
    future['future'] = {'name': 'one', 'hidden': False}
    future_bake = fingerprint(future)
    future['future']['name'] = 'two'
    assert fingerprint(future) != future_bake, 'unknown nested names stay relevant'
    assert fingerprint({'future': True}) != fingerprint({'future': 1})
    assert fingerprint({'future': 37.0}) == fingerprint({'future': 37})
    assert fingerprint({'future': 2**60}) != fingerprint({'future': 2**60 + 1})
    assert model == original, 'fingerprint mutates the saved model'


def test_rounds_and_http():
    with house() as c:
        first = ts.current_id()
        baked = ts.round_lighting(first)
        assert baked == fingerprint(ts.current_model())
        assert c.client.get('/api/house/twin', headers=c.mum).json()['lighting'] == baked
        building = ts.current_model()['buildings'][0]
        before = ts.current_model()
        response = c.client.post(OP, headers=c.mum, json={'op': {
            'op': 'set', 'kind': 'building', 'building': building['id'], 'id': building['id'],
            'field': 'name', 'value': 'Renamed house'}})
        assert response.status_code == 200, response.text
        from services import twin_plan
        assert response.json()['lighting'] == baked, twin_plan.diff_paths(before, ts.current_model())
        rid = response.json()['round']
        for params in ({}, {'have_round': rid}):
            state = c.client.get(STATE, params=params, headers=c.mum).json()
            assert state['lighting'] == baked
            assert next(r for r in state['rounds'] if r['id'] == rid)['lighting'] == baked
        for collection in ('levels', 'rooms'):
            piece = ts.current_model()['buildings'][0][collection][0]
            response = c.client.post(OP, headers=c.mum, json={'op': {
                'op': 'set', 'building': building['id'], 'id': piece['id'],
                'field': 'name', 'value': 'Renamed ' + collection}})
            assert response.status_code == 200, response.text
            assert response.json()['lighting'] == baked, collection
        # Sheet/underlay registrations are editor reference metadata. Moving
        # one changes no model (unlike applying a registration to house pieces).
        with ts._LOCK:
            row = ts._state()
            row['registrations'] = [{'source': 'sheet', 'page': 1, 'level': 'L1',
                                     'reg': {'offset': [100, 200], 'rotation': 90}}]
            ts._save(row)
        assert fingerprint(ts.current_model()) == baked
        # Relevance on the stored (schema-3) model shape, not only the flat fixture.
        stored = ts.current_model()
        b0 = stored['buildings'][0]
        real = {
            'joint': lambda m: m['buildings'][0]['joints'][0]['at'].__setitem__(0, m['buildings'][0]['joints'][0]['at'][0] + 1),
            'opening width': lambda m: next(o for b in m['buildings'] for o in b.get('openings') or []).__setitem__(
                'width', next(o for b in m['buildings'] for o in b.get('openings') or []).get('width', 3) + 1),
            'roof pitch': lambda m: (lambda r: r.__setitem__('pitch', (r.get('pitch') or 6) + 1))(next(r for b in m['buildings'] for r in b.get('roofs') or [])),
            'terrace': lambda m: m['site'].setdefault('terraces', []).append(
                {'id': 't-new', 'polygon': [[0, 0], [5, 0], [5, 5]], 'height': 2}),
            'wall material': lambda m: m['buildings'][0]['walls'][0].__setitem__('material', {'id': 'other-siding'}),
            'building material': lambda m: m['buildings'][0].__setitem__('materials', {'siding': {'id': 'other'}}),
        }
        assert b0.get('joints') and b0.get('walls'), sorted(b0)
        for label, mutate in real.items():
            changed = deepcopy(stored)
            mutate(changed)
            assert fingerprint(changed) != baked, ('stored model', label)
        changed = ts.current_model()
        changed['buildings'][0]['joints'][0]['at'][0] += 1
        moved = ts.update_model(lambda _: changed)
        assert ts.round_lighting(moved) != baked
        restored = ts.revert(first)
        assert restored > moved and ts.round_lighting(restored) == baked
        # No lazy geometry/hash work for pre-upgrade rounds.
        with ts._LOCK:
            row = ts._state()
            next(r for r in row['rounds'] if r['id'] == restored).pop('lighting')
            ts._save(row)
        assert ts.round_lighting(restored) is None
        assert c.client.get(STATE, headers=c.mum).json()['lighting'] is None
        storage.patch_settings({'house_twin': {}})
        assert c.client.get('/api/house/twin', headers=c.mum).json()['lighting'] is None
        assert c.client.get(STATE, headers=c.mum).json()['lighting'] is None


def test_cost():
    model = json.loads(FIXTURE.read_text(encoding='utf8'))
    with house():
        stored = ts.current_model()
    for label, value in [('household fixture', model), ('stored connected model', stored)]:
        def measure(fn):
            return statistics.median(timeit.repeat(fn, number=100, repeat=5)) * 10
        cost = measure(lambda: fingerprint(value))
        serialization = measure(lambda: json.dumps(value, ensure_ascii=False, allow_nan=False))
        print(f'COST {label}: fingerprint={cost:.3f} ms; serialization={serialization:.3f} ms; ratio={cost / serialization:.3f}')


if __name__ == '__main__':
    for test in (test_content, test_rounds_and_http, test_cost):
        test()
        print('PASS', test.__name__)
