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
    check(plan['schema'] == tp.SCHEMA == 'chauffeur.twin.plan/2', plan.get('schema'))
    check(notes == [], f'the hand-checked fixture is clean: {notes}')
    b = plan['buildings'][0]
    check([l['id'] for l in b['levels']] == ['L1', 'L2'], 'levels kept')
    check(b['roof']['sections'][0]['pitch'] == 11, 'pitch kept')
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
    check(plan['buildings'][0]['roof']['sections'][0]['pitch'] == 1 and any('pitch' in n for n in notes),
          'a zero pitch is clamped to 1 with a note')
    raw['buildings'][0]['roof']['main']['pitch'] = 30
    plan, notes = tp.normalize(raw)
    check(plan['buildings'][0]['roof']['sections'][0]['pitch'] == 24 and any('pitch' in n for n in notes),
          'a 30:12 pitch is clamped to 24 with a note')


def scenario_caps_stop_runaway_lists():
    check(tp.CAPS == {'walls': 400, 'openings': 400, 'rooms': 120, 'planting': 300,
                      'furniture': 120, 'beds': 60, 'roof_sections': 40, 'terraces': 40}, tp.CAPS)
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
    check(tp.diff_paths(a, b) == ['buildings[id=pool_house].walls[id=rear].height', 'materials.siding.color'],
          tp.diff_paths(a, b))
    c = copy.deepcopy(a)
    c['buildings'][0]['walls'][2]['height'] = float(int(10)) if False else c['buildings'][0]['walls'][2]['height']
    check(tp.diff_paths(a, json.loads(json.dumps(a).replace('.0,', ',').replace('.0}', '}').replace('.0]', ']'))) == [],
          'numbers compare by value: 6.0 equals 6 (the editor round trip)')
    d = copy.deepcopy(a)
    d['buildings'][0]['walls'] = [w for w in d['buildings'][0]['walls'] if w['id'] != 'stair_wall']
    check(tp.diff_paths(a, d) == ['buildings[id=pool_house].walls[id=stair_wall]'],
          f'a removed id-bearing item is one path, and later items do not shift: {tp.diff_paths(a, d)}')
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


def scenario_every_part_of_a_partial_answer_is_validated():
    raw = _fixture()
    b = raw['buildings'][0]
    b['porch']['polygon'] = [{'x': 31, 'y': 0}, {'x': 38, 'y': 0}, {'x': 38, 'y': 22}]
    b['porch']['columns'].append({'size': 0.667})
    b['stairs'].append({'level': 'L1', 'from': [1, 1], 'width': 3})
    b['lights'].append({'room': 'Sitting', 'kind': 'recessed', 'level': 'L1'})
    b['fixtures'].append({'kind': 'counter', 'level': 'L1', 'height': 3})
    raw['site']['lot'] = 'the back yard'
    raw['site']['hardscape'].append({'kind': 'patio', 'polygon': 'abc'})
    raw['site']['pool'] = {'polygon': [[1, 2], 'x'], 'depth': 5}
    raw['site']['fire_pit'] = {'radius': 3}
    plan, notes = tp.normalize(raw)
    nb = plan['buildings'][0]
    check(nb.get('porch') is None and any('porch' in n for n in notes), 'a porch with an unreadable polygon is dropped with a note')
    check(len(nb['stairs']) == 1 and any('stair' in n for n in notes), 'a stair without "to" is dropped')
    check(all('at' in l for l in nb['lights']) and any('light' in n for n in notes), 'a light without "at" is dropped')
    check(all('rect' in f for f in nb['fixtures']), 'a fixture without a rect is dropped')
    s = plan['site']
    check(s['lot'] is None and s['pool'] is None and s['fire_pit'] is None, (s['lot'], s['pool'], s['fire_pit']))
    check(all(isinstance(h.get('polygon'), list) for h in s['hardscape']), 'unreadable hardscape dropped')
    for word in ('lot', 'pool', 'fire', 'hardscape'):
        check(any(word in n for n in notes), f'a note mentions {word}: {notes}')


def scenario_missing_fields_default_with_notes():
    raw = _fixture()
    b = raw['buildings'][0]
    del b['levels'][1]['ceiling']
    door = next(o for o in b['openings'] if o.get('kind') == 'door')
    del door['sill']
    plan, notes = tp.normalize(raw)
    nb = plan['buildings'][0]
    check(nb['levels'][1]['ceiling'] == 9, 'a level without a ceiling defaults to 9 ft, the building survives')
    check(any(o.get('kind') == 'door' and o['sill'] == 0 for o in nb['openings']), 'a door without a sill sits at 0')
    check(any('ceiling' in n for n in notes) and any('sill' in n for n in notes), notes)

_DRAFT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures',
                      'twin_reads', 'recorded', 'claude', 'draft-main-spike.json')


def _draft():
    with open(_DRAFT, encoding='utf-8') as f:
        return json.load(f)


def _gable_opening(**kw):
    return {'id': 'gx', 'gable': 'front', 'section': 'left_wing', 'kind': 'window',
            'width': 3, 'sill': 2, 'head': 6, **kw}


def scenario_test_half_level_kept():
    raw = _draft()
    next(l for l in raw['buildings'][0]['levels'] if l['id'] == 'L2')['half'] = True
    plan, _ = tp.normalize(raw)
    levels = {l['id']: l for l in plan['buildings'][0]['levels']}
    check(levels['L2'].get('half') is True, f"half survives normalize: {levels['L2']}")
    check(not levels['L1'].get('half'), 'half defaults to false')


def scenario_test_ridge_x_gable_opening_valid():
    raw = _draft()
    # left_wing: ridge x, y range 14.33..54; y = 34 spans 32.5..35.5
    raw['buildings'][0]['openings'].append(_gable_opening(y=34))
    plan, notes = tp.normalize(raw)
    kept = [o for o in plan['buildings'][0]['openings'] if o.get('id') == 'gx']
    check(len(kept) == 1 and kept[0]['y'] == 34, (kept, notes))


def scenario_test_ridge_x_gable_opening_outside_dropped():
    raw = _draft()
    n0 = len(raw['buildings'][0]['openings'])
    raw['buildings'][0]['openings'].append(_gable_opening(id='gx1', y=60))       # past y1 = 54
    raw['buildings'][0]['openings'].append(_gable_opening(id='gx2', y=15))       # 13.5 < y0 = 14.33
    raw['buildings'][0]['openings'].append(_gable_opening(id='gx3', gable='rear', y=54.5))
    plan, notes = tp.normalize(raw)
    check(len(plan['buildings'][0]['openings']) == n0, 'all three dropped')
    check(len(notes) == 3 and all('outside' in n for n in notes), notes)


def scenario_test_ridge_y_gable_opening_unchanged():
    raw = _draft()
    n0 = len(raw['buildings'][0]['openings'])
    plan, notes = tp.normalize(raw)
    check(any(o.get('id') == 'g1' for o in plan['buildings'][0]['openings']), 'ridge-y gable opening kept')
    raw['buildings'][0]['openings'].append({'id': 'gbad', 'gable': 'front', 'section': 'front_wing',
                                            'kind': 'window', 'x': 90, 'width': 2, 'sill': 2, 'head': 5})
    plan, notes = tp.normalize(raw)
    check(len(plan['buildings'][0]['openings']) == n0, 'ridge-y x outside the span still dropped')
    check(any('outside' in n for n in notes), notes)


# ---- per-end roof ends (plan .superpowers/sdd/2026-11-08-house-editor-roofs-from-photos
# task 2): a gable or hip section may carry ends {<end>: 'gable'|'hip'|'clip'};
# ridge x has ends x0 and x1, ridge y has ends y0 and y1.

def _sections(plan):
    return {s['id']: s for s in plan['buildings'][0]['roof']['sections']}


def _set_ends(raw, section_id, ends):
    next(s for s in raw['buildings'][0]['roof']['sections'] if s['id'] == section_id)['ends'] = ends
    return raw


def scenario_test_roof_ends_survive_normalize():
    _, base_notes = tp.normalize(_draft())
    raw = _set_ends(_draft(), 'left_wing', {'x0': 'gable', 'x1': 'hip'})      # ridge x
    raw = _set_ends(raw, 'front_wing', {'y0': 'clip', 'y1': 'gable'})          # ridge y
    raw = _set_ends(raw, 'main', {'x0': 'hip', 'x1': 'clip'})                  # a hip may end in a clip
    plan, notes = tp.normalize(raw)
    s = _sections(plan)
    check(s['left_wing'].get('ends') == {'x0': 'gable', 'x1': 'hip'}, s['left_wing'])
    check(s['front_wing'].get('ends') == {'y0': 'clip', 'y1': 'gable'}, s['front_wing'])
    check(s['main'].get('ends') == {'x0': 'hip', 'x1': 'clip'}, s['main'])
    check(notes == base_notes, f'valid ends add no notes: {notes}')
    plan, _ = tp.normalize(_draft())
    check('ends' not in _sections(plan)['left_wing'], 'no ends unless given')


def scenario_test_roof_invalid_end_dropped_with_note():
    _, base_notes = tp.normalize(_draft())
    raw = _set_ends(_draft(), 'left_wing', {'x0': 'gable', 'x1': 'dome'})
    plan, notes = tp.normalize(raw)
    s = _sections(plan)['left_wing']
    check(s.get('ends') == {'x0': 'gable'}, f'the bad value is dropped, the good one kept: {s}')
    extra = [n for n in notes if n not in base_notes]
    check(len(extra) == 1 and 'end' in extra[0].lower(), f'one plain note about the end: {extra}')
    check('dome' in extra[0] or 'x1' in extra[0] or 'right' in extra[0].lower(), extra)

    # an end the ridge does not have: ridge x has no y0 end
    raw = _set_ends(_draft(), 'left_wing', {'y0': 'hip', 'x1': 'hip'})
    plan, notes = tp.normalize(raw)
    s = _sections(plan)['left_wing']
    check(s.get('ends') == {'x1': 'hip'}, f'an end off the ridge axis is dropped: {s}')
    extra = [n for n in notes if n not in base_notes]
    check(len(extra) == 1 and 'end' in extra[0].lower(), extra)

    # ends that are not a mapping at all
    raw = _set_ends(_draft(), 'left_wing', 'hip')
    plan, notes = tp.normalize(raw)
    s = _sections(plan)['left_wing']
    check('ends' not in s, f'non-mapping ends dropped: {s}')
    extra = [n for n in notes if n not in base_notes]
    check(len(extra) == 1 and 'end' in extra[0].lower(), extra)
    check(s['kind'] == 'gable' and s['ridge'] == 'x', 'the section itself survives')


if __name__ == '__main__':
    failed = []
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
               scenario_openings_that_exactly_fill_a_wall_survive,
               scenario_every_part_of_a_partial_answer_is_validated,
               scenario_missing_fields_default_with_notes,
               scenario_test_half_level_kept,
               scenario_test_ridge_x_gable_opening_valid,
               scenario_test_ridge_x_gable_opening_outside_dropped,
               scenario_test_ridge_y_gable_opening_unchanged,
               scenario_test_roof_ends_survive_normalize,
               scenario_test_roof_invalid_end_dropped_with_note):
        try:
            fn()
        except Exception as e:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, repr(e)[:200])
        else:
            print('  ok ', fn.__name__)
    if failed:
        raise SystemExit(1)
