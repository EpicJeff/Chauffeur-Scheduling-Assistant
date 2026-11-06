"""The twin plan file's laws (spec docs/superpowers/specs/
2026-11-06-house-digital-twin-design.md section 7; plan Task 1). Pure:
no storage, no browser, no network.

Run from chauffeur/:  python tests/test_twin_plan.py
"""
import copy
import json
import os

from harness import check
from services import twin_plan as tp

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'fixtures', 'twin_poolhouse.plan.json')


def _fixture():
    with open(_FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def _raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    return False


def scenario_the_fixture_normalizes_clean():
    plan, notes = tp.normalize(_fixture())
    check(plan['schema'] == tp.SCHEMA == 'chauffeur.twin.plan/1', plan.get('schema'))
    check(notes == [], f'the hand-checked fixture is clean: {notes}')
    b = plan['buildings'][0]
    check([l['id'] for l in b['levels']] == ['L1', 'L2'], 'levels kept')
    check(b['roof']['main']['pitch'] == 11, 'pitch kept')
    check(len(b['walls']) == 13 and len(b['openings']) == 12, 'nothing dropped')


def scenario_levels_are_sorted_by_elevation():
    raw = _fixture()
    raw['buildings'][0]['levels'].reverse()
    plan, _ = tp.normalize(raw)
    check([l['id'] for l in plan['buildings'][0]['levels']] == ['L1', 'L2'],
          'levels come back lowest first')


def scenario_normalize_does_not_mutate_its_input():
    raw = _fixture()
    before = copy.deepcopy(raw)
    tp.normalize(raw)
    check(raw == before, 'input untouched')


def scenario_bad_openings_are_dropped_with_notes():
    raw = _fixture()
    n0 = len(raw['buildings'][0]['openings'])
    # front wall is 31 ft long: 30.5 +/- 2 runs past its end
    raw['buildings'][0]['openings'].append(
        {'wall': 'front', 'kind': 'window', 'at': 30.5, 'width': 4, 'sill': 3, 'head': 7})
    # sill above head
    raw['buildings'][0]['openings'].append(
        {'wall': 'left', 'kind': 'window', 'at': 5, 'width': 2, 'sill': 7, 'head': 3})
    # a wall that does not exist
    raw['buildings'][0]['openings'].append(
        {'wall': 'nope', 'kind': 'door', 'at': 2, 'width': 3, 'sill': 0, 'head': 7})
    # head above the wall (front wall is 10.917 tall)
    raw['buildings'][0]['openings'].append(
        {'wall': 'front', 'kind': 'window', 'at': 4, 'width': 2, 'sill': 9, 'head': 12})
    # a gable window outside the 0..31 span
    raw['buildings'][0]['openings'].append(
        {'gable': 'front', 'kind': 'window', 'x': 33, 'width': 2, 'sill': 2, 'head': 5})
    plan, notes = tp.normalize(raw)
    check(len(plan['buildings'][0]['openings']) == n0, 'all five bad openings dropped')
    check(len(notes) == 5, f'one note per dropped opening: {notes}')
    check(any('front' in n and 'outside' in n for n in notes), notes)
    check(any('nope' in n for n in notes), notes)


def scenario_defaults_and_degenerate_walls():
    raw = _fixture()
    walls = raw['buildings'][0]['walls']
    del walls[0]['thickness']           # exterior 'front'
    del walls[4]['thickness']           # interior 'stair_wall'
    walls.append({'id': 'dot', 'level': 'L1', 'from': [3, 3], 'to': [3, 3], 'height': 8})
    walls.append({'id': 'ghost', 'level': 'L9', 'from': [1, 1], 'to': [2, 1], 'height': 8})
    plan, notes = tp.normalize(raw)
    by_id = {w['id']: w for w in plan['buildings'][0]['walls']}
    check(by_id['front']['thickness'] == 0.5, 'exterior default 0.5')
    check(by_id['stair_wall']['thickness'] == 0.33, 'interior default 0.33')
    check('dot' not in by_id and 'ghost' not in by_id, 'zero-length and unknown-level walls dropped')
    check(any('dot' in n for n in notes) and any('ghost' in n for n in notes), notes)


def scenario_rooms_need_three_points():
    raw = _fixture()
    raw['buildings'][0]['rooms'].append({'name': 'Line', 'level': 'L1', 'polygon': [[0, 0], [1, 1]]})
    plan, notes = tp.normalize(raw)
    check(all(r['name'] != 'Line' for r in plan['buildings'][0]['rooms']), 'two-point room dropped')
    check(any('Line' in n for n in notes), notes)


def scenario_roof_pitch_is_bounded():
    raw = _fixture()
    raw['buildings'][0]['roof']['main']['pitch'] = 0
    plan, notes = tp.normalize(raw)
    check(plan['buildings'][0]['roof']['main']['pitch'] == 1 and any('pitch' in n for n in notes),
          'a zero pitch is clamped to 1 with a note')
    raw['buildings'][0]['roof']['main']['pitch'] = 30
    plan, notes = tp.normalize(raw)
    check(plan['buildings'][0]['roof']['main']['pitch'] == 24 and any('pitch' in n for n in notes),
          'a 30:12 pitch is clamped to 24 with a note')


def scenario_caps_stop_runaway_lists():
    check(tp.CAPS == {'walls': 400, 'openings': 400, 'rooms': 120, 'planting': 300,
                      'furniture': 120, 'beds': 60}, tp.CAPS)
    raw = _fixture()
    raw['site']['planting'] = [{'kind': 'shrub', 'preset': 'Bush 1', 'at': [50 + i % 20, -50 - i // 20],
                                'height': 3, 'seed': i} for i in range(500)]
    plan, notes = tp.normalize(raw)
    check(len(plan['site']['planting']) == 300, len(plan['site']['planting']))
    capped = [n for n in notes if 'planting' in n and '300' in n]
    check(len(capped) == 1, f'one note naming the cap: {notes}')


def scenario_units_must_be_feet():
    raw = _fixture()
    raw['units'] = 'm'
    check(_raises(lambda: tp.normalize(raw), ValueError), 'metres refused')
    raw = _fixture()
    raw['buildings'] = []
    check(_raises(lambda: tp.normalize(raw), ValueError), 'no buildings refused')


def scenario_merge_director_never_touches_buildings():
    plan, _ = tp.normalize(_fixture())
    revised = copy.deepcopy(plan)
    revised['buildings'][0]['walls'][0]['height'] = 30
    revised['site']['beds'].append({'polygon': [[-6, 0], [-1, 0], [-1, 20], [-6, 20]], 'material': 'mulch'})
    revised['materials']['siding']['color'] = '#ffffff'
    merged, _ = tp.merge_director(plan, revised)
    check(merged['buildings'] == plan['buildings'], 'buildings unchanged')
    check(len(merged['site']['beds']) == 1, 'the new bed is kept')
    check(merged['materials']['siding']['color'] == '#ffffff', 'materials taken from the director')


def scenario_diff_paths_names_leaves():
    a, _ = tp.normalize(_fixture())
    b = copy.deepcopy(a)
    b['materials']['siding']['color'] = '#000000'
    b['buildings'][0]['walls'][2]['height'] = 9.5
    check(tp.diff_paths(a, b) == ['buildings[0].walls[2].height', 'materials.siding.color'],
          tp.diff_paths(a, b))
    check(tp.diff_paths(a, copy.deepcopy(a)) == [], 'no change, no paths')


def scenario_model_shaped_junk_is_coerced_not_crashed():
    raw = _fixture()
    raw['materials'] = None
    raw['site']['planting'] = ['not a dict', {'kind': 'shrub', 'preset': 'Bush 1', 'at': [60, -60], 'height': 3, 'seed': 1}]
    raw['site']['beds'] = 'nope'
    plan, notes = tp.normalize(raw)
    check(plan['materials'] == {} and any('materials' in n for n in notes), 'materials=None becomes {} with a note')
    check(len(plan['site']['planting']) == 1 and any('planting' in n for n in notes), 'non-dict planting dropped')
    check(plan['site']['beds'] == [] and any('beds' in n for n in notes), 'a non-list bed field becomes []')


def scenario_openings_that_exactly_fill_a_wall_survive():
    raw = _fixture()
    walls = raw['buildings'][0]['walls']
    walls.append({'id': 'diag', 'level': 'L1', 'from': [0.1, 0.3], 'to': [3.1, 4.3], 'height': 9})
    # length is 5.0 up to float error; a 5 ft opening centred at 2.5 fills it exactly
    raw['buildings'][0]['openings'].append({'wall': 'diag', 'kind': 'passage', 'at': 2.5, 'width': 5.0,
                                            'sill': 0, 'head': 7})
    raw['buildings'][0]['openings'].append({'wall': 'left', 'kind': 'window', 'at': 5, 'width': 2,
                                            'sill': -1, 'head': 4})
    plan, notes = tp.normalize(raw)
    ops = plan['buildings'][0]['openings']
    check(any(o.get('wall') == 'diag' for o in ops), f'an exact fit is kept (float tolerance): {notes}')
    check(not any(o.get('wall') == 'left' and o['sill'] == -1 for o in ops) and any('sill' in n for n in notes),
          'a negative sill is dropped with a note')


if __name__ == '__main__':
    for fn in (scenario_the_fixture_normalizes_clean,
               scenario_levels_are_sorted_by_elevation,
               scenario_normalize_does_not_mutate_its_input,
               scenario_bad_openings_are_dropped_with_notes,
               scenario_defaults_and_degenerate_walls,
               scenario_rooms_need_three_points,
               scenario_roof_pitch_is_bounded,
               scenario_caps_stop_runaway_lists,
               scenario_units_must_be_feet,
               scenario_merge_director_never_touches_buildings,
               scenario_diff_paths_names_leaves,
               scenario_model_shaped_junk_is_coerced_not_crashed,
               scenario_openings_that_exactly_fill_a_wall_survive):
        fn()
        print('  ok ', fn.__name__)
