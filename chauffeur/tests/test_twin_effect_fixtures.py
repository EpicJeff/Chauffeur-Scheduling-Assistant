"""Effect model, real store/editor HTTP operations, live markers and stream ids."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp-effects'
SCRATCH.mkdir(exist_ok=True)
tempfile.tempdir = str(SCRATCH)
DATA = SCRATCH / ('effects-tests-' + str(uuid4()))
DATA.mkdir()
os.environ['CHAUFFEUR_DATA_DIR'] = str(DATA)
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(ROOT))
from services import twin_effect_fixtures as effects, twin_fixtures as lights
from services import twin_model_bridge as bridge
from test_twin_ha_routes import Ctx, LIVE, seed as house_seed, ts, twin_model

OP = '/api/house/editor/op'


def fixture(kind='fountain', **changes):
    shape = changes.get('shape', 'line' if kind == 'waterfall' else 'point')
    geometry = {'path': [[10, 10, 2], [20, 10, 2]]} if shape == 'line' else {'at': [10, 10, 1]}
    return {'id': 'effect:' + str(uuid4()), 'type': kind, 'shape': shape,
            'ref': 'absolute', **geometry, **changes}


def seed():
    house_seed()
    def setup(m):
        m['site']['lot'] = [[-100, -100], [200, -100], [200, 200], [-100, 200]]
        m['site']['terraces'] = [{'id': 'pad1', 'polygon': [[10, 10], [20, 10], [20, 20], [10, 20]],
                                 'height': 2, 'edges': [{'edge': 'sharp', 'wall': {'material': 'stone'}} for _ in range(4)]}]
        return m
    ts.update_model(setup)


def post(c, op, status=200, headers=None):
    before, count = ts.current_id(), len(ts.rounds())
    response = c.client.post(OP, headers=headers or c.mum, json={'op': op})
    assert response.status_code == status, response.text
    assert len(ts.rounds()) == count + (status == 200), 'one accepted operation is one round'
    if status != 200:
        assert ts.current_id() == before
        return response.json()
    return response.json()['model']


def add(c, f=None):
    return post(c, {'op': 'add_effect_fixture', 'fixture': f or fixture()})['effect_fixtures'][-1]


def refused(raw):
    try:
        effects.validate(raw)
    except ValueError as exc:
        assert str(exc)
    else:
        raise AssertionError('Accepted invalid effect: ' + repr(raw))


def test_type_shape_defaults_and_identity():
    for kind, sizes in (('waterfall', (.3, 1.5)), ('fountain', (1, 6)), ('bubbler', (.3, 1.5)), ('fire', (.5, 2))):
        raw = fixture(kind)
        before = copy.deepcopy(raw)
        f = effects.validate(raw)
        assert (f['size_min'], f['size_max'], f['strength']) == (*sizes, 1)
        assert f['id'] == raw['id'] and raw == before
        assert 'building' not in f and 'level' not in f
    assert effects.validate(fixture('fire', shape='line'))['shape'] == 'line'
    for kind, shape in (('waterfall', 'point'), ('fountain', 'line'), ('bubbler', 'line'), ('fire', 'spot')):
        refused(fixture(kind, shape=shape))
    for raw in (None, [], {}, fixture('smoke'), fixture(id='effect:not-a-uuid'), fixture(id='fixture:' + str(uuid4())),
                fixture(unknown=1), fixture(floor_level='L1'), fixture(width_in=1), fixture(at=[True, 1, 1]), fixture(at=[1, 2]),
                fixture('waterfall', path=[[1, 1, 1], [1, 1, 1]])):
        refused(raw)
    refused(fixture(id='effect:12345678-1234-4ABC-8123-123456789ABC'))


def test_entity_domains_and_sensor_range():
    for domain in ('switch', 'light', 'input_boolean', 'fan'):
        assert effects.validate(fixture(entity=domain + '.pump'))['entity'] == domain + '.pump'
    for domain in ('sensor', 'number', 'input_number'):
        for lo, hi in ((1000, 3450), (3450, 1000), (-1e200, 1e200)):
            f = effects.validate(fixture(sensor=domain + '.rpm', sensor_min=lo, sensor_max=hi))
            assert f['sensor_min'] == lo and f['sensor_max'] == hi
    for raw in (fixture(entity='cover.pump'), fixture(entity='switch.Mixed'), fixture(entity='switch.'),
                fixture(sensor='light.rpm', sensor_min=0, sensor_max=100), fixture(sensor='sensor.rpm'),
                fixture(sensor='sensor.rpm', sensor_min=0), fixture(sensor='sensor.rpm', sensor_min=0, sensor_max=0),
                fixture(sensor_min=0, sensor_max=100), fixture(sensor='sensor.rpm', sensor_min=True, sensor_max=100),
                fixture(sensor='sensor.rpm', sensor_min=float('nan'), sensor_max=100),
                fixture(sensor='sensor.rpm', sensor_min=0, sensor_max=float('inf'))):
        refused(raw)


def test_limits_names_and_waterfall_drop():
    for key, bad in (('size_min', -1), ('size_max', 30.01), ('size_max', True), ('strength', -0.1),
                     ('strength', 1.01), ('strength', True), ('name', ''), ('name', ' '), ('name', 'a'*81)):
        refused(fixture(**{key: bad}))
    assert effects.validate(fixture(size_min=0, size_max=30, strength=0, name=' Jet '))['name'] == 'Jet'
    assert effects.validate(fixture('waterfall', drop_ft=40))['drop_ft'] == 40
    for value in (0, 40.1, True, float('inf')):
        refused(fixture('waterfall', drop_ft=value))
    refused(fixture(drop_ft=1))


def test_floor_adapter_preserves_intensity_and_shared_placement():
    seed()
    m = ts.current_model()
    f = effects.validate(fixture(ref='floor', building='B1', level='L1', strength=.4))
    p = effects.placement(f)
    assert p['level'] == 'L1' and f['strength'] == .4
    assert lights._reference(m, p, p['at']) == lights._reference(m, {**p, 'level': 'L1'}, p['at'])
    assert effects.validate(f) == f
    refused(fixture(ref='floor', building='B1', level=.4))
    effects.apply_op(m, {'op': 'add_effect_fixture', 'fixture': f})
    assert m['effect_fixtures'][0]['strength'] == .4 and m['effect_fixtures'][0]['level'] == 'L1'


def test_normalize_untouched_structural_invalid_duplicates_and_cap():
    m, notes = {}, []
    effects.normalize(m, notes)
    assert m == {} and not notes
    good = fixture()
    m = {'effect_fixtures': [good, copy.deepcopy(good), fixture(unknown=True), *[fixture() for _ in range(65)]]}
    effects.normalize(m, notes)
    assert len(m['effect_fixtures']) == 64 and len(notes) == 4
    assert len({f['id'] for f in m['effect_fixtures']}) == 64
    for raw in ({}, 'invalid', None):
        m, notes = {'effect_fixtures': raw}, []
        effects.normalize(m, notes)
        assert m['effect_fixtures'] == [] and len(notes) == 1


def test_normalize_context_orphans_and_repair():
    seed()
    original = ts.current_model()
    m = copy.deepcopy(original)
    f = fixture(ref='floor', building='B1', level='L1')
    m['effect_fixtures'] = [f]
    m['buildings'] = []
    notes = []
    effects.normalize(m, notes)
    orphan = m['effect_fixtures'][0]
    assert orphan['orphaned'] and 'building and level' in orphan['orphan_reason'] and not notes
    m['buildings'] = original['buildings']
    effects.normalize(m, notes)
    assert 'orphaned' not in m['effect_fixtures'][0]
    m['site']['lot'] = [[0, 0], [5, 0], [5, 5], [0, 5]]
    effects.normalize(m, notes)
    assert 'lot' in m['effect_fixtures'][0]['orphan_reason']
    m['effect_fixtures'][0]['at'] = [2, 2, 1]
    effects.normalize(m, notes)
    assert not m['effect_fixtures'][0].get('orphaned') and not notes


def test_ops_real_store_rounds_undo_redo_and_delete():
    seed()
    with Ctx() as c:
        original = ts.current_id()
        f = add(c)
        added = ts.current_id()
        model = post(c, {'op': 'update_effect_fixture', 'id': f['id'], 'change': {'strength': .3, 'name': 'Jet'}})
        changed = ts.current_id()
        assert model['effect_fixtures'][0]['strength'] == .3
        for round_id, expected in ((added, [f]), (changed, model['effect_fixtures']), (original, []), (added, [f])):
            response = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': round_id})
            assert response.status_code == 200, response.text
            assert ts.current_model().get('effect_fixtures', []) == expected
        model = post(c, {'op': 'delete_effect_fixture', 'id': f['id']})
        assert model['effect_fixtures'] == []


def test_http_refusals_domains_caps_and_type_shape_changes():
    seed()
    with Ctx() as c:
        f = add(c, fixture('fire'))
        for change in ({'type': 'waterfall'}, {'id': 'effect:' + str(uuid4())}, {'entity': 'cover.pool'},
                       {'sensor': 'sensor.pool', 'sensor_min': 1, 'sensor_max': 1}, {'strength': 2}):
            post(c, {'op': 'update_effect_fixture', 'id': f['id'], 'change': change}, 400)
        post(c, {'op': 'add_effect_fixture', 'fixture': fixture()}, 403, c.kid)
        post(c, {'op': 'add_effect_fixture', 'fixture': f}, 400)
        m = post(c, {'op': 'update_effect_fixture', 'id': f['id'], 'change': {'type': 'waterfall', 'shape': 'line',
                         'path': [[10, 10, 2], [20, 10, 2]], 'drop_ft': 3}})
        assert m['effect_fixtures'][0]['type'] == 'waterfall' and 'at' not in m['effect_fixtures'][0]
        m = post(c, {'op': 'update_effect_fixture', 'id': f['id'], 'change': {'type': 'fire'}})
        assert m['effect_fixtures'][0]['type'] == 'fire' and 'drop_ft' not in m['effect_fixtures'][0]
        ts.update_model(lambda m: {**m, 'effect_fixtures': [fixture() for _ in range(64)]})
        post(c, {'op': 'add_effect_fixture', 'fixture': fixture()}, 400)


def test_link_and_clear_sensor_and_optional_properties():
    seed()
    with Ctx() as c:
        f = add(c)
        m = post(c, {'op': 'update_effect_fixture', 'id': f['id'], 'change': {
            'sensor': 'sensor.pool_rpm', 'sensor_min': 1000, 'sensor_max': 3450, 'entity': 'switch.pool', 'name': 'Jet'}})
        assert m['effect_fixtures'][0]['sensor'] == 'sensor.pool_rpm'
        m = post(c, {'op': 'update_effect_fixture', 'id': f['id'], 'change': {'sensor': None, 'entity': None, 'name': None}})
        assert not set(m['effect_fixtures'][0]) & {'sensor', 'sensor_min', 'sensor_max', 'entity', 'name'}


def test_bridge_round_trip_flat_edit_and_absent_key():
    seed()
    m = ts.current_model()
    assert 'effect_fixtures' not in bridge.flatten(m)
    m['effect_fixtures'] = [effects.validate(fixture('waterfall', sensor='sensor.rpm', sensor_min=1000, sensor_max=3450))]
    flat = bridge.flatten(m)
    assert flat['effect_fixtures'] == m['effect_fixtures']
    restored, _ = bridge.assemble(flat, m)
    assert restored['effect_fixtures'] == m['effect_fixtures']
    flat.pop('effect_fixtures')
    restored, _ = bridge.assemble(flat, m)
    assert restored['effect_fixtures'] == m['effect_fixtures']
    ts.update_model(lambda _: m)
    ts.update_current(lambda plan: plan, 'edit')
    assert ts.current_model()['effect_fixtures'] == m['effect_fixtures']


def test_snapped_effect_follows_host_and_detaches_on_removal():
    seed()
    with Ctx() as c:
        f = add(c, fixture('waterfall', snap={'host': {'kind': 'retaining_wall', 'id': 'pad1'},
                          'edge': {'from': [10, 10], 'to': [20, 10]}, 't0': .2, 't1': .8}))
        assert f['path'] == [[12, 10, 2], [18, 10, 2]] and not f['detached']
        m = post(c, {'op': 'update_pad', 'id': 'pad1', 'polygon': [[15, 12], [25, 12], [25, 22], [15, 22]]})
        moved = m['effect_fixtures'][0]
        assert moved['path'] == [[17, 12, 2], [23, 12, 2]] and not moved['detached']
        ts.update_model(lambda m: {**m, 'site': {**m['site'], 'terraces': []}})
        detached = ts.current_model()['effect_fixtures'][0]
        assert detached['path'] == moved['path'] and detached['detached']


def test_live_payload_and_marker_fallback_deduplicates_entity():
    seed()
    with Ctx() as c:
        linked = add(c, fixture(entity='light.kitchen_ceiling', name='Jet'))
        fallback = add(c, fixture('waterfall', entity='switch.effect_only'))
        add(c, fixture('fire', entity='switch.effect_only'))
        unlinked = add(c, fixture('bubbler'))
        response = c.client.get(LIVE, headers=c.mum)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['effect_fixtures'] == ts.current_model()['effect_fixtures']
        for rows in (body['markers'], body['devices']):
            carrying = [r for r in rows if 'light.kitchen_ceiling' in [r.get('entity_id'), *r.get('entities', [])]]
            assert len(carrying) == 1 and carrying[0]['device_id'] == 'dev-k-light'
            effect_rows = [r for r in rows if r['device_id'].startswith('effect:')]
            assert len(effect_rows) == 1 and effect_rows[0]['entity_id'] == 'switch.effect_only'
            row = effect_rows[0]
            assert row['kind'] == 'switch'
            if rows is body['markers']:
                assert row['at'] == [15, 10, 2]
            assert row['name'] == 'Waterfall' and 'offered' in row
            assert not any(r['device_id'] in ('effect:' + linked['id'], 'effect:' + unlinked['id']) for r in rows)


def test_whole_house_stream_includes_switch_and_sensor_only():
    import main
    seed()
    with Ctx() as c:
        add(c, fixture(entity='switch.effect_only', sensor='number.effect_rpm', sensor_min=1000, sensor_max=3450))
        whole = main._house_stream_entities()
        assert {'switch.effect_only', 'number.effect_rpm'} <= whole
        assert not {'switch.effect_only', 'number.effect_rpm'} & main._house_stream_entities('kitchen')


def test_no_home_assistant_keeps_payload_without_markers_or_stream():
    import main
    seed()
    with Ctx(available=False) as c:
        add(c, fixture(entity='switch.pool'))
        add(c, fixture(sensor='sensor.rpm', sensor_min=1000, sensor_max=3450))
        add(c, fixture('fire'))
        response = c.client.get(LIVE, headers=c.mum)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['available'] is False and body['markers'] == []
        assert len(body['effect_fixtures']) == 3 and main._house_stream_entities() == set()


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=6)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
