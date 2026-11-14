"""Real household HTTP golden responses and counted derivations, no HA/network."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import traceback
from unittest.mock import patch

from test_twin_ha_routes import Ctx, ts
from services import storage, twin_model, twin_model_bridge as bridge, twin_plan

FIXTURES = Path(__file__).parent / 'fixtures' / 'twin_model'
GOLDEN = FIXTURES / 'server-speed-v2.499.850.json.gz'
METRICS = FIXTURES / 'server-speed-baseline.json'
OP = '/api/house/editor/op'
STATE = '/api/house/editor/state'


class Clock:
    @staticmethod
    def now(tz=None):
        return datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


@contextmanager
def house():
    # Same input and push_round path as house_editor_model_harness.seed().
    with tempfile.TemporaryDirectory(prefix='twin_server_speed_') as directory:
        with patch.object(ts, 'DATA_DIR', directory), patch.object(ts, 'datetime', Clock):
            storage.patch_settings({'house_twin': {}})
            ts.push_round(json.loads((FIXTURES / 'household-2026-11-09.json').read_text(encoding='utf-8')), 'build')
            with Ctx(available=False) as client:
                yield client


@contextmanager
def counted():
    counts = {}
    with ExitStack() as stack:
        for obj, name, label in ((twin_model, 'normalize', 'normalize'), (twin_plan, 'normalize', 'plan_normalize'),
                                 (bridge, 'flatten', 'flatten'), (ts, '_read_round', 'read_round'),
                                 (ts, 'current', 'current'), (ts, 'current_model', 'current_model')):
            original = getattr(obj, name)
            counts[label] = 0
            def wrapped(*args, _fn=original, _label=label, **kwargs):
                counts[_label] += 1
                return _fn(*args, **kwargs)
            stack.enter_context(patch.object(obj, name, wrapped))
        yield counts


def corpus():
    model = ts.current_model()
    b = model['buildings'][0]
    wall = next(w for w in b['walls'] if w.get('state') != 'ghost')
    return [
        ('set_material', {'op': 'set_material', 'building': b['id'], 'target': {'building': b['id'], 'role': 'siding'}, 'material': {'id': 'siding'}}),
        ('move_site_item', {'op': 'move_site_item', 'list': 'planting', 'index': 0, 'by': [1, 0]}),
        ('move_wall', {'op': 'move_wall', 'building': b['id'], 'wall': wall['id'], 'by': [0.1, 0]}),
        ('place_device', {'op': 'place_device', 'building': b['id'], 'device': 'dev-test', 'host': {'wall': wall['id'], 'at': 0.5, 'z': 4, 'side': 'left'}}),
        ('move_building', {'op': 'move_building', 'building': b['id'], 'to': [12, 23]}),
        ('set_material_again', {'op': 'set_material', 'building': b['id'], 'target': {'building': b['id'], 'role': 'siding'}, 'material': {'id': 'roof'}}),
        ('unplace_device', {'op': 'unplace_device', 'device': 'dev-test'}),
        ('revert', None),
    ]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def capture():
    snapshots, metrics = [], {}
    with house() as c:
        for kind, operation in corpus():
            with counted() as counts:
                start = perf_counter()
                response = c.client.post(OP if operation else '/api/house/twin/revert', headers=c.mum,
                                         json={'op': operation} if operation else {'round': 1})
                elapsed = (perf_counter() - start) * 1000
            assert response.status_code == 200, (kind, response.text)
            body = response.json()
            metrics[kind] = {'ms': elapsed, 'timing': body.pop('timing', {}), 'calls': dict(counts)}
            body.pop('bytes', None)
            with counted() as counts:
                start = perf_counter()
                state = c.client.get(STATE, headers=c.mum)
                state_ms = (perf_counter() - start) * 1000
            assert state.status_code == 200, state.text
            metrics[kind].update(state_ms=state_ms, state_calls=dict(counts), state_bytes=len(state.content))
            with counted() as counts:
                start = perf_counter()
                lean = c.client.get(STATE, params={'have_round': ts.current_id()}, headers=c.mum)
                lean_ms = (perf_counter() - start) * 1000
            assert lean.status_code == 200, lean.text
            metrics[kind].update(lean_ms=lean_ms, lean_calls=dict(counts), lean_bytes=len(lean.content))
            snapshots.append({'kind': kind, 'op': body, 'state': state.json()})
    return snapshots, metrics


def test_op_and_state_responses_identical_with_cache():
    old = json.loads(gzip.decompress(GOLDEN.read_bytes()))
    new, _ = capture()
    assert len(old) == len(new) >= 8
    for expected, actual in zip(old, new):
        # The sole intentional full-state API extension; all old fields and
        # their serialized order/float/Unicode representation remain identical.
        current_round = actual['state'].pop('current_round')
        assert current_round == actual['state']['rounds'][-1]['id']
        assert encoded(actual) == encoded(expected), actual['kind']


def test_normalize_calls_per_op_reduced():
    baseline = json.loads(METRICS.read_text())
    _, after = capture()
    for kind in ('set_material', 'move_site_item', 'move_wall', 'place_device'):
        # v2.499.857: write-through plus skipping the second normalize of a just-published
        # model leaves one normalize (publication), except a first edit after a cold start.
        assert after[kind]['calls']['normalize'] <= 2 < baseline[kind]['calls']['normalize']
        assert after[kind]['calls']['read_round'] < baseline[kind]['calls']['read_round']
        if kind != 'set_material':
            assert after[kind]['calls']['normalize'] == 1, (kind, after[kind]['calls'])
            assert after[kind]['calls']['read_round'] == 0, (kind, after[kind]['calls'])
        assert after[kind]['state_calls']['flatten'] == 0
        assert after[kind]['state_calls']['read_round'] == 0
        assert after[kind]['lean_calls']['current'] == after[kind]['lean_calls']['current_model'] == 0


def test_cached_reads_are_private_and_keyed_by_round_generation_and_root():
    with house():
        model, plan = ts.current_model(), ts.current()
        wanted_model, wanted_plan = deepcopy(model), deepcopy(plan)
        model['buildings'][0]['joints'][0]['at'][0] = -9999
        plan['buildings'][0]['walls'].clear()
        with counted() as counts:
            assert ts.current_model() == wanted_model
            assert ts.current() == wanted_plan
        assert counts['read_round'] == counts['flatten'] == 0
        # Metadata writes invalidate even with the same round and generation.
        ts.set_front_bearing(27)
        with counted() as counts:
            assert ts.current() == wanted_plan
            assert ts.current_model() == wanted_model
        assert counts['read_round'] == counts['flatten'] == 1
        old_id, old_generation = ts.current_id(), ts.generation()
    with house():
        # Another store uses the same id and generation, with a different root.
        assert ts.current_id() == old_id and ts.generation() == old_generation
        # Write-through (v2.499.857) fills the cache from this store's own publish, under
        # this root's key: what matters is that the read is this store's model, not the old one.
        with counted() as counts:
            mine = ts.current()
        assert counts['flatten'] == 1 and counts['read_round'] <= 1
        on_disk = json.loads((Path(ts.DATA_DIR) / 'rounds' / f'{ts.current_id()}.json').read_text(encoding='utf-8'))
        assert ts.current_model() == on_disk and mine['buildings']


def changed_position(x):
    def change(model):
        model['buildings'][0]['position'][0] = x
        return model
    return change


def assert_position(x):
    # Both reads are primed before each mutation below and must reflect it.
    assert ts.current_model()['buildings'][0]['position'][0] == x
    assert ts.current()['buildings'][0]['position'][0] == x


def test_cache_invalidated_by_revert_start_over_load_and_build_round():
    from services import twin_house_saves as saves
    with house() as c:
        original = ts.current_model()['buildings'][0]['position'][0]
        ts.current()
        saved = saves.save_current('Original', 'mum')
        ts.update_model(changed_position(101))
        assert_position(101)
        response = c.client.post('/api/house/twin/revert', headers=c.mum, json={'round': 1})
        assert response.status_code == 200, response.text
        assert_position(original)
        ts.update_model(changed_position(102))
        assert_position(102)
        response = c.client.post(f'/api/house/editor/houses/{saved["id"]}/load', headers=c.mum)
        assert response.status_code == 200, response.text
        assert_position(original)
        # Both real build publication entry points, including partial builds.
        ts.update_current(changed_position(103), 'build', partial=True)
        assert_position(103)
        plan = ts.current()
        plan['buildings'][0]['position'][0] = 104
        ts.push_round(plan, 'build')
        assert_position(104)
        generation = ts.generation()
        response = c.client.post('/api/house/editor/start-over', headers=c.mum)
        assert response.status_code == 200, response.text
        assert ts.current() is None and ts.current_model() is None
        assert ts.generation() == generation + 1
        plan['buildings'][0]['position'][0] = 105
        assert ts.push_round(plan, 'build') == 1  # reused id, new generation
        assert_position(105)


def test_lean_state_omits_plan_model_only_when_round_matches():
    with house() as c:
        full = c.client.get(STATE, headers=c.mum).json()
        rid = full['current_round']
        assert rid == ts.current_id()
        with counted() as counts:
            lean = c.client.get(STATE, params={'have_round': rid}, headers=c.mum).json()
        assert lean == {k: v for k, v in full.items() if k not in ('plan', 'model')}
        assert counts['current'] == counts['current_model'] == counts['flatten'] == counts['read_round'] == 0
        assert c.client.get(STATE, params={'have_round': rid - 1}, headers=c.mum).json() == full
        ts.update_model(changed_position(106))
        mismatch = c.client.get(STATE, params={'have_round': rid}, headers=c.mum).json()
        assert mismatch['plan']['buildings'][0]['position'][0] == 106
        assert mismatch['model']['buildings'][0]['position'][0] == 106
        assert mismatch['current_round'] != rid
        ts.start_over()
        empty = c.client.get(STATE, params={'have_round': rid}, headers=c.mum).json()
        assert empty['current_round'] is None and empty['plan'] is None and empty['model'] is None


if __name__ == '__main__':
    if '--record-baseline' in sys.argv:
        snapshots, metrics = capture()
        GOLDEN.write_bytes(gzip.compress(encoded(snapshots), mtime=0))
        METRICS.write_text(json.dumps(metrics, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(metrics, indent=2))
        sys.exit(0)
    if '--measure' in sys.argv:
        print(json.dumps(capture()[1], indent=2))
        sys.exit(0)
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=8)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
