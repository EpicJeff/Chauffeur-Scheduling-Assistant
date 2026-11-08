"""Extra rebuild proof: original identities, level ids and lot placement."""
import copy
import sys
import traceback

from test_twin_build_draft_rebuild import (
    DraftReader, INTERIOR, _build, _house, _l_answer, _near, _same_wall,
    _seed_old_pipeline, _walls_at, check, engine_tests, tb, tr, ts, twin_edit,
)


def test_each_person_piece_matches_only_its_read_geometry():
    engine_tests._fresh()
    house = {'id': 'house', 'walls': [
        {'id': 'carrier', 'level': 'L1', 'from': [0, 0], 'to': [40, 0]}], 'openings': [],
        'roof': {'sections': [{'id': 'gable', 'rect': [0, 0, 20, 10], 'ridge': 'x'}]}}
    shapes = [
        ('wall', {'level': 'L1', 'from': [0, 0], 'to': [20, 0]}),
        ('opening', {'wall': 'carrier', 'at': 8, 'width': 2}),
        ('opening', {'section': 'gable', 'gable': 'front', 'y': 3, 'width': 2}),
        ('room', {'level': 'L1', 'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]]}),
        ('roof', {'rect': [0, 0, 20, 10]}),
        ('porch', {'polygon': [[0, 0], [10, 0], [10, 10], [0, 10]]}),
        ('stair', {'level': 'L1', 'from': [0, 0], 'to': [0, 10]}),
    ]
    step = {'id': 'draft', 'reread': True}
    for kind, shape in shapes:
        person = dict(copy.deepcopy(shape), id='mine', src={'person': True})
        person['read_geometry'] = copy.deepcopy(tb._geometry(person, kind, house))
        if kind == 'opening':
            person['at' if 'wall' in person else 'y'] += 5
        else:
            twin_edit._transform(person, lambda p: [p[0] + 5, p[1] + 5])
        incoming = dict(copy.deepcopy(shape), id='read', src={'step': 'draft'})
        merged = tb._merge_list([person], [incoming], kind, house, {}, step)
        check(len(merged) == 1 and merged[0] == person, (kind, merged))
        # A separate read at the edited position is a different piece.
        separate = dict(copy.deepcopy(person), id='other', src={'step': 'draft'})
        separate.pop('read_geometry')
        merged = tb._merge_list([person], [separate], kind, house, {}, step)
        check(len(merged) == 2 and merged[0] == person, (kind, merged))


def test_rotated_migration_preserves_world_placement_and_runs_once():
    _seed_old_pipeline()
    plan = ts.current()
    house = _house(plan)
    house['roof']['sections'] = [{'id': 'person-roof', 'kind': 'gable', 'ridge': 'y',
        'rect': [-3, 2, 37, 22], 'plate': 9, 'pitch': 6, 'overhang': 1,
        'src': {'person': True}, 'read_geometry': {'rect': [-3, 2, 37, 22]}}]
    house['openings'] = [{'id': 'person-gable', 'kind': 'window', 'section': 'person-roof',
        'gable': 'front', 'x': 2, 'width': 2, 'sill': 1, 'head': 3, 'src': {'person': True},
        'read_geometry': {'from': [1, 2], 'to': [3, 2]}}]
    # Old level ids are arbitrary; the draft owns L1, L2... by elevation.
    house['levels'][0]['id'] = 'ground'
    old_frame = {'position': [11, -7], 'rotation': 90}
    for level in house['levels']:
        level['outline'] = [tr.to_world(old_frame, p) for p in level['outline']]
    for wall in house['walls']:
        wall['level'] = 'ground'
        twin_edit._transform(wall, lambda p: tr.to_world(old_frame, p))
        twin_edit._transform(wall['read_geometry'], lambda p: tr.to_world(old_frame, p))
    roof = house['roof']['sections'][0]
    twin_edit._transform(roof, lambda p: tr.to_world(old_frame, p))
    twin_edit._transform(roof['read_geometry'], lambda p: tr.to_world(old_frame, p))
    roof['ridge'] = 'x'
    opening = house['openings'][0]
    opening.update(gable='rear', y=tr.to_world(old_frame, [opening.pop('x'), 2])[1])
    twin_edit._transform(opening['read_geometry'], lambda p: tr.to_world(old_frame, p))
    ts.push_round(plan, 'build')
    twin_edit.save({'op': 'move', 'building': 'house', 'piece': 'wall:old-i1', 'by': [2, 0]}, 'p1')
    twin_edit.save({'op': 'delete', 'building': 'house', 'piece': 'wall:old-i3'}, 'p1')
    twin_edit.save({'op': 'set', 'building': 'house', 'piece': 'house',
                    'field': 'position', 'value': [60, 80]}, 'p1')
    twin_edit.save({'op': 'set', 'building': 'house', 'piece': 'house',
                    'field': 'rotation', 'value': 37}, 'p1')
    before = _house(ts.current())
    wall = next(w for w in before['walls'] if w['id'] == 'wall:old-i1')
    world = [tr.to_world(before, wall[k]) for k in ('from', 'to')]
    move, rms = tr.fit_outline(before['levels'][0]['outline'], _l_answer()['building']['levels'][0]['outline'])
    check(rms < .1 and abs(move['angle']) > 80, (move, rms))
    expected = [tr.to_world({'position': move['offset'], 'rotation': move['angle']}, wall[k])
                for k in ('from', 'to')]
    placement = None
    for attempt in range(2):
        _build(DraftReader(answer=_l_answer()))
        house = _house(ts.current())
        wall = next(w for w in house['walls'] if w['id'] == 'wall:old-i1')
        check(wall['level'] == 'L1' and _same_wall(wall, *expected), wall)
        check(all(_near(tr.to_world(house, wall[k]), p, .05)
                  for k, p in zip(('from', 'to'), world)), ('world placement', house, wall))
        check(not _walls_at(house, 'L1', *INTERIOR['i3']), 'migrated deletion survives the next build')
        check(ts.tombstones()[0]['level'] == 'L1', ts.tombstones())
        roof = next(s for s in house['roof']['sections'] if s['id'] == 'person-roof')
        check(roof['ridge'] == 'y' and all(abs(a - b) < .05
              for a, b in zip(roof['rect'], [0, 0, 40, 20])), roof)
        opening = next(o for o in house['openings'] if o['id'] == 'person-gable')
        check(opening['gable'] == 'front' and abs(opening['x'] - 5) < .05, opening)
        current_placement = (house['position'], house['rotation'])
        if placement:
            check(current_placement == placement, ('migration runs once', placement, current_placement))
        placement = copy.deepcopy(current_placement)


def test_added_wall_remembers_its_first_read_before_a_later_move():
    engine_tests._fresh()
    house = {'id': 'house', 'openings': []}
    mine = {'id': 'added', 'level': 'L1', 'from': [0, 0], 'to': [10, 0], 'src': {'person': True}}
    step = {'id': 'draft', 'reread': True}
    incoming = {'id': 'read', 'level': 'L1', 'from': [0, 0], 'to': [10, 0], 'src': {'step': 'draft'}}
    merged = tb._merge_list([mine], [incoming], 'wall', house, {}, step)
    check(merged[0].get('read_geometry') == {'from': [0, 0], 'to': [10, 0]}, merged)
    twin_edit._transform(merged[0], lambda p: [p[0], p[1] + 4])
    again = tb._merge_list(merged, [copy.deepcopy(incoming)], 'wall', house, {}, step)
    check(len(again) == 1 and again[0]['from'] == [0, 4], again)


if __name__ == '__main__':
    tests = [test_each_person_piece_matches_only_its_read_geometry,
             test_rotated_migration_preserves_world_placement_and_runs_once,
             test_added_wall_remembers_its_first_read_before_a_later_move]
    failed = []
    for test in tests:
        try:
            test()
            print('  ok  ', test.__name__)
        except Exception:
            failed.append(test.__name__)
            traceback.print_exc()
    print(f'{len(tests) - len(failed)}/{len(tests)} passed')
    sys.exit(bool(failed))
