"""Read fixtures survive normalization, saved rounds, rereads and a real build."""
import copy
import math
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_read_fixtures_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_model_bridge as bridge, twin_model_hosts as hosts, twin_plan, twin_store
from test_twin_reads_rules import _flat


FIXTURES = [{'id': 'read-light', 'kind': 'light', 'level': 'L1', 'at': [5, 5], 'surface': 'ceiling'},
            {'id': 'read-switch', 'kind': 'switch', 'level': 'L1', 'at': [3, 0], 'surface': 'wall', 'wall': 's'},
            {'id': 'read-smoke', 'kind': 'smoke alarm', 'level': 'L1', 'at': [12, 5], 'surface': 'ceiling'}]


def test_fixture_round_survives_a_flat_save():
    twin_store.start_over()
    twin_store.update_current(lambda _: _flat(copy.deepcopy(FIXTURES)), kind='build')
    house = twin_store.current_model()['buildings'][0]
    assert len(house['anchors']) == 3
    assert {p['kind'] for p in house['anchors']} == {'light', 'switch', 'sensor'}
    flat = bridge.flatten(twin_store.current_model())['buildings'][0]
    assert flat['fixtures'] == []  # Legacy fixture rendering requires rectangles.
    assert len(flat['anchors']) == 3 and len(flat['lights']) == 1
    twin_store.update_current(lambda flat: flat, kind='build')
    def placements(building):
        return [{k: p[k] for k in ('id', 'kind', 'host', 'src')} for p in building['anchors']]
    assert placements(twin_store.current_model()['buildings'][0]) == placements(house)


def test_reread_moves_and_removes_generated_fixtures():
    plan, _ = bridge.assemble(_flat(copy.deepcopy(FIXTURES)))
    fixtures = copy.deepcopy(FIXTURES)
    light = next(p for p in fixtures if p['id'] == 'read-light')
    light['at'] = [8, 5]
    fixtures[:] = [p for p in fixtures if p['id'] != 'read-smoke']
    again, _ = bridge.assemble(twin_plan.normalize(_flat(fixtures))[0], plan)
    house = again['buildings'][0]
    assert len(house['anchors']) == 2
    light = next(p for p in house['anchors'] if p['id'] == 'read-light')
    assert hosts.world_point(house, light['host'])[:2] == [8, 5]


def test_draft_build_keeps_fixture_wall_references():
    from test_twin_build_draft import DraftReader, _drawn_house, tb, ts
    _drawn_house(photos=0)
    building = _flat(copy.deepcopy(FIXTURES))['buildings'][0]
    building['levels'][0]['outline'] = [[0, 0], [20, 0], [20, 10], [0, 10]]
    building['rooms'] = []
    reader = DraftReader(answer={'building': building, 'pages': [], 'checks': {}, 'notes': []})
    bid = tb.start({'part': 'house'}, reader=reader, inline=True)
    assert tb.status(bid)['state'] == 'done'
    house = ts.current_model()['buildings'][0]
    assert len(house['anchors']) == 3
    switch = next(p for p in house['anchors'] if p['kind'] == 'switch')
    assert any(w['id'] == switch['host']['wall'] for w in house['walls'])
    assert switch['src']['step'] == 'draft'
    assert math.dist(hosts.world_point(house, switch['host'])[:2], [3, 0]) <= .5

    light = next(p for p in house['anchors'] if p['kind'] == 'light')
    light_id = light['id']
    def move_light(model):
        anchor = next(p for p in model['buildings'][0]['anchors'] if p['id'] == light_id)
        anchor['src'] = {'person': True}
        anchor['host']['u'] = .4
        return model
    ts.update_model(move_light)
    before = next(p for p in ts.current_model()['buildings'][0]['anchors'] if p['id'] == light_id)
    tb.reread(bid, 'draft', reader=reader, inline=True)
    house = ts.current_model()['buildings'][0]
    lights = [p for p in house['anchors'] if p['kind'] == 'light']
    assert len(lights) == 1 and lights[0]['id'] == light_id
    assert lights[0]['host'] == before['host'] and lights[0]['src']['person']


if __name__ == '__main__':
    tests = [test_fixture_round_survives_a_flat_save, test_reread_moves_and_removes_generated_fixtures,
             test_draft_build_keeps_fixture_wall_references]
    for test in tests:
        test()
        print('ok', test.__name__)
    print(f'{len(tests)}/{len(tests)} passed')
