"""Plan format v2 for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 8; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 1): roof
sections, building rotation and base, piece state, reserved terrain, and the
migration of P0 plans. Pure: no storage, no browser, no network.

Run from chauffeur/:  python tests/test_twin_plan_v2.py
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import twin_plan  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _wall(wall_id, start=(0, 0), end=(30, 0)):
    wall = {'level': 'L1', 'from': list(start), 'to': list(end), 'height': 10, 'thickness': 0.5, 'exterior': True}
    if wall_id is not None:
        wall['id'] = wall_id
    return wall


def _building(**over):
    building = {
        'id': 'house', 'name': 'House', 'position': [0, 0],
        'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 10}],
        'walls': [_wall('front', (0, 0), (30, 0)), _wall('right', (30, 0), (30, 20)),
                  _wall('rear', (30, 20), (0, 20)), _wall('left', (0, 20), (0, 0))],
        'openings': [], 'rooms': [], 'stairs': [],
    }
    building.update(over)
    return building


def _plan(building):
    return {'units': 'ft', 'buildings': [building], 'materials': {}, 'site': {}}


def scenario_p0_pool_house_migrates_to_one_gable_section():
    with open(FIXTURE, encoding='utf-8') as f:
        p0 = json.load(f)
    before = copy.deepcopy(p0)
    plan, notes = twin_plan.normalize(p0)
    check(p0 == before, 'input untouched')
    check(plan['schema'] == 'chauffeur.twin.plan/2', plan['schema'])
    roof = plan['buildings'][0]['roof']
    main = p0['buildings'][0]['roof']['main']
    check(roof['sections'] == [{'id': 'roof-main', 'kind': 'gable',
                                'rect': [main['x0'], main['y0'], main['x1'], main['y1']],
                                'ridge': main['ridge_axis'], 'pitch': main['pitch'], 'plate': main['plate'],
                                'overhang': main['overhang'], 'pitch_source': 'drawn'}],
          roof['sections'])
    check(len(roof['extensions']) == 2 and all(e['section'] == 'roof-main' for e in roof['extensions']),
          roof['extensions'])
    check(notes == [], f'migration of the clean fixture adds no notes: {notes}')
    again, _ = twin_plan.normalize(plan)
    check(again == plan, 'v2 normalize is idempotent')


def scenario_roof_sections_validate():
    b = _building(roof={'sections': [
        {'id': 'r1', 'kind': 'hip', 'rect': [0, 0, 40, 20], 'ridge': 'x', 'pitch': 8, 'plate': 9, 'overhang': 1},
        {'id': 'r2', 'kind': 'shed', 'rect': [40, 0, 50, 20], 'low_side': 'x1', 'pitch': 3, 'plate': 9},
        {'id': 'r3', 'kind': 'gable', 'rect': [5, 5, 5, 9], 'ridge': 'y', 'pitch': 8, 'plate': 9},
        {'id': 'r4', 'kind': 'dome', 'rect': [0, 0, 1, 1], 'pitch': 8, 'plate': 9},
        {'id': 'r5', 'kind': 'gable', 'rect': [0, 0, 10, 10], 'ridge': 'y', 'pitch': 40, 'plate': 9},
        {'id': 'r6', 'kind': 'flat', 'rect': [50, 0, 60, 10], 'pitch': 4, 'plate': 9},
        {'id': 'r7', 'kind': 'shed', 'rect': [60, 0, 70, 10], 'pitch': 3, 'plate': 9}]})
    plan, notes = twin_plan.normalize(_plan(b))
    s = plan['buildings'][0]['roof']['sections']
    check([x['id'] for x in s] == ['r1', 'r2', 'r5', 'r6'], [x['id'] for x in s])
    check(s[0]['pitch_source'] == 'default' and s[0]['overhang'] == 1 and 'state' not in s[0], s[0])
    check(s[1]['overhang'] == 1, 'overhang defaults to 1 ft')
    check(s[2]['pitch'] == 24 and any('r5' in n and 'clamped' in n for n in notes), notes)
    check(s[3]['pitch'] == 0, 'a flat section has no pitch')
    for dropped in ('r3', 'r4', 'r7'):
        check(any(dropped in n for n in notes), f'{dropped} named in notes: {notes}')


def scenario_building_rotation_and_base():
    plan, notes = twin_plan.normalize(_plan(_building(rotation=-90, base=2.5)))
    b = plan['buildings'][0]
    check(b['rotation'] == 270 and b['base'] == 2.5 and b['position'] == [0, 0], b)
    plan, notes = twin_plan.normalize(_plan(_building(rotation='north')))
    check(plan['buildings'][0]['rotation'] == 0 and any('rotation' in n for n in notes), notes)
    plan, notes = twin_plan.normalize(_plan(_building()))
    check(plan['buildings'][0]['rotation'] == 0 and plan['buildings'][0]['base'] == 0, 'defaults')


def scenario_missing_ids_are_assigned_and_unique():
    b = _building(walls=[_wall(None), _wall(None, (30, 0), (30, 20)), _wall('wall-1', (30, 20), (0, 20))])
    plan, _ = twin_plan.normalize(_plan(b))
    ids = [w['id'] for w in plan['buildings'][0]['walls']]
    check(len(set(ids)) == 3 and 'wall-1' in ids and all(i.startswith('wall-') for i in ids), ids)


def scenario_piece_meta_is_kept_and_checked():
    w = {**_wall('w9'), 'state': 'ghost', 'src': {'sheet': 'abc', 'page': 2, 'step': 'walls:L1:main'},
         'confidence': 0.4, 'why': 'stamp covers the corner'}
    bad = {**_wall('w10', (30, 0), (30, 20)), 'state': 'floating', 'confidence': 3, 'src': 'model'}
    person = {**_wall('w11', (30, 20), (0, 20)), 'src': {'person': True, 'sheet': 'abc', 'page': 2}}
    plan, notes = twin_plan.normalize(_plan(_building(walls=[w, bad, person])))
    a, b, c = plan['buildings'][0]['walls']
    check(a['state'] == 'ghost' and a['src'] == {'sheet': 'abc', 'page': 2, 'step': 'walls:L1:main'}
          and a['confidence'] == 0.4 and a['why'] == 'stamp covers the corner', a)
    check('state' not in b and 'confidence' not in b and 'src' not in b, 'a bad state is dropped: absent means settled')
    check(c['src'] == {'person': True, 'sheet': 'abc', 'page': 2}, c)


def scenario_terraces_validate_and_ground_items_keep_elevation():
    site = {'lot': [[0, 0], [100, 0], [100, 150], [0, 150]],
            'terraces': [{'id': 't1', 'polygon': [[0, 0], [100, 0], [100, 60], [0, 60]], 'height': -4},
                         {'id': 't2', 'polygon': [[0, 0], [1, 1]], 'height': 0},
                         {'id': 't3', 'polygon': [[0, 0], [1, 0], [1, 1]], 'height': 400}],
            'fire_pit': {'at': [20, 20], 'radius': 3, 'elevation': -4}}
    plan, notes = twin_plan.normalize({'units': 'ft', 'buildings': [_building()], 'site': site})
    check([t['id'] for t in plan['site']['terraces']] == ['t1'], plan['site']['terraces'])
    check(plan['site']['fire_pit']['elevation'] == -4, plan['site']['fire_pit'])
    check(any('t2' in n for n in notes) and any('t3' in n for n in notes), notes)


def scenario_state_is_never_added_by_default():
    # A normalized plan must equal its source wherever nothing was invalid:
    # 'state' absent means settled, so composed site items and P0 rounds do
    # not grow a key on every save (that showed up as hundreds of fixes).
    with open(FIXTURE, encoding='utf-8') as f:
        p0 = json.load(f)
    plan, _ = twin_plan.normalize(p0)
    def walk(node):
        if isinstance(node, dict):
            check('state' not in node, node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(plan)


def scenario_gable_openings_name_their_section():
    with open(FIXTURE, encoding='utf-8') as f:
        p0 = json.load(f)
    plan, _ = twin_plan.normalize(p0)
    gables = [o for o in plan['buildings'][0]['openings'] if 'gable' in o]
    check(gables and all(o.get('section') == 'roof-main' for o in gables), gables)


if __name__ == '__main__':
    for fn in (scenario_p0_pool_house_migrates_to_one_gable_section,
               scenario_roof_sections_validate,
               scenario_building_rotation_and_base,
               scenario_missing_ids_are_assigned_and_unique,
               scenario_piece_meta_is_kept_and_checked,
               scenario_terraces_validate_and_ground_items_keep_elevation,
               scenario_state_is_never_added_by_default,
               scenario_gable_openings_name_their_section):
        fn()
        print('  ok ', fn.__name__)
