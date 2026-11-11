"""Round-one fixture regressions. Stub readers only; isolated household data."""
import copy
import os
import sys
import tempfile
import time
import traceback

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_fixture_merge_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import twin_model, twin_model_bridge as bridge, twin_edit
from test_twin_reads_rules import _flat, _wall
from test_twin_reads_fixtures import FIXTURES
from test_twin_build_draft import DraftReader, _drawn_house, tb, ts


def build(fixtures=None, rooms=None, *, single_floor=False):
    _drawn_house(photos=0)
    if single_floor:
        ts.set_page_roles([r for r in ts.page_roles() if r.get('level') != 'Upper floor'])
    building = _flat(copy.deepcopy(FIXTURES if fixtures is None else fixtures))['buildings'][0]
    building['levels'][0]['outline'] = [[0, 0], [20, 0], [20, 10], [0, 10]]
    building['rooms'] = []
    reader = DraftReader(answer={'building': building, 'pages': [], 'checks': {}, 'notes': []}, rooms=rooms)
    bid = tb.start({'part': 'house'}, reader=reader, inline=True)
    assert tb.status(bid)['state'] == 'done', tb.status(bid)
    return bid, reader


def test_I1_rooms_step_rehosts_draft_fixtures():
    rooms = {'walls': [dict(_wall('middle', (10, 0), (10, 10)), exterior=False)], 'rooms': [
        {'id': 'left', 'name': 'Left', 'level': 'L1', 'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]]},
        {'id': 'right', 'name': 'Right', 'level': 'L1', 'polygon': [[10, 0], [20, 0], [20, 10], [10, 10]]}]}
    fixtures = copy.deepcopy(FIXTURES) + [dict(FIXTURES[0], id='floor', surface='floor', at=[6, 6])]
    build(fixtures, rooms)
    house = ts.current_model()['buildings'][0]
    assert len(house['anchors']) == 4
    for anchor in house['anchors']:
        assert twin_model._host_error(anchor['host'], house) is None, anchor
        assert not anchor.get('src', {}).get('person')


def test_I2_deleted_read_fixtures_stay_deleted_on_reread():
    fixtures = copy.deepcopy(FIXTURES) + [dict(FIXTURES[1], id='outlet', kind='outlet', at=[8, 0])]
    bid, reader = build(fixtures)
    house = ts.current_model()['buildings'][0]
    assert {p['kind'] for p in house['anchors']} == {'light', 'switch', 'sensor', 'outlet'}
    for anchor in house['anchors']:
        twin_edit.save({'op': 'delete', 'id': anchor['id'], 'building': house['id']}, 'test')
    assert not ts.current_model()['buildings'][0]['anchors']
    tombstones = ts.tombstones()
    assert len([t for t in tombstones if t['kind'] == 'fixture']) == 4, tombstones
    tb.reread(bid, 'draft', reader=reader, inline=True)
    assert not ts.current_model()['buildings'][0]['anchors']


def test_I3_household_fixtures_and_person_anchors_under_300ms():
    from test_twin_model_bridge import _household
    flat = _household()
    house = flat['buildings'][0]
    model, _ = bridge.assemble(flat)
    room = next(r for r in model['buildings'][0]['rooms'] if r.get('state') != 'ghost')
    house['anchors'] = [dict(id=f'person-{i}', kind='light', host={'ceiling': room['id'], 'u': .2, 'v': .2},
                             offset=0, device=None, src={'person': True}) for i in range(30)]
    x0, y0, x1, y1 = twin_model._bounds(room['polygon'])
    house['fixtures'] = [dict(id=f'fixture-{i}', kind='light', level=room['level'],
                             at=[(x0 + x1) / 2, (y0 + y1) / 2], surface='ceiling') for i in range(60)]
    times = []
    for _ in range(3):
        start = time.perf_counter()
        model, _ = bridge.assemble(flat)
        times.append(time.perf_counter() - start)
    elapsed = min(times)
    print(f'  60 fixtures + 30 person anchors: {elapsed * 1000:.1f} ms')
    assert len(model['buildings'][0]['anchors']) == 90
    assert elapsed < .3, elapsed


def test_I4_wall_snap_and_kind_words():
    fixtures = []
    for i, kind in enumerate(['Light', 'pendant lamp', 'smoke detector', 'CO alarm',
                             'thermostat', 'receptacle', 'dimmer', 'ceiling fan']):
        fixtures.append(dict(id=str(i), kind=kind, level='L1', surface='wall', at=[2 + i * 2, 1.5],
                             **({'wall': 's'} if i % 2 else {})))
    fixtures += [dict(id='fallback', kind='switch', level='L1', surface='wall', wall='n', at=[4, 1.8]),
                 dict(id='far', kind='switch', level='L1', surface='wall', at=[10, 5]),
                 dict(id='unknown', kind='mystery', level='L1', surface='ceiling', at=[5, 5])]
    model, _ = bridge.assemble(_flat(fixtures))
    house = model['buildings'][0]
    assert len(house['anchors']) == 9, house['flags']
    assert [p['kind'] for p in house['anchors'][:8]] == ['light', 'light', 'sensor', 'sensor', 'sensor', 'outlet', 'switch', 'fan']
    assert all(p['host']['wall'].split('~')[0] == 's' for p in house['anchors'])
    assert all(twin_model._host_error(p['host'], house) is None for p in house['anchors'])
    unknown = next(f for f in house['flags'] if f['piece']['fixture']['id'] == 'unknown')
    assert 'kind' in unknown['text'] and 'surface' not in unknown['text'], unknown
    assert any('no valid surface' in f['text'] for f in house['flags'])


def test_M1_smoke_alarm_identity_survives_reread():
    bid, reader = build()
    before = {p['kind']: p['id'] for p in ts.current_model()['buildings'][0]['anchors']}
    tb.reread(bid, 'draft', reader=reader, inline=True)
    after = {p['kind']: p['id'] for p in ts.current_model()['buildings'][0]['anchors']}
    assert before == after, (before, after)


def test_M8_fallback_without_fixture_key_keeps_read_fixtures():
    bid, reader = build(single_floor=True)
    before = copy.deepcopy(ts.current_model()['buildings'][0]['anchors'])
    original = reader.__call__
    class Fallback:
        def __call__(self, kind, images, context, **kwargs):
            if kind == 'draft':
                return {'error': 'max tokens', 'truncated': True}
            if kind == 'draft_level':
                if context['level'] == 'roof':
                    return {'building': {'roof': {'sections': [dict(id='r', rect=[0, 0, 20, 10],
                            kind='gable', ridge='x', pitch=6, plate=9, overhang=.5, level='L1')]}}, 'notes': []}
                answer = copy.deepcopy(reader.answer)
                answer['building'].pop('fixtures', None)
                return answer
            return original(kind, images, context, **kwargs)
    tb.reread(bid, 'draft', reader=Fallback(), inline=True)
    assert tb.status(bid)['state'] == 'done', tb.status(bid)
    assert ts.current_model()['buildings'][0]['anchors'] == before


TESTS = [test_I1_rooms_step_rehosts_draft_fixtures, test_I2_deleted_read_fixtures_stay_deleted_on_reread,
         test_I3_household_fixtures_and_person_anchors_under_300ms, test_I4_wall_snap_and_kind_words,
         test_M1_smoke_alarm_identity_survives_reread, test_M8_fallback_without_fixture_key_keeps_read_fixtures]
if __name__ == '__main__':
    failed = 0
    for test in TESTS:
        try:
            test()
            print('ok', test.__name__)
        except Exception:
            failed += 1
            traceback.print_exc()
    print(f'{len(TESTS) - failed}/{len(TESTS)} passed')
    sys.exit(bool(failed))
