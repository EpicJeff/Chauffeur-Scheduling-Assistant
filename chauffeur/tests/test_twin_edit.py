"""Hand edits for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md sections 6, 7.3; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 9 and its
review amendment): one set of edit operations shared by the editor's cards,
plan view, pauses and Argyle's house_design tool. Every changed piece is
marked as the person's, deletions leave tombstones, and a registration change
moves every piece read from that sheet.

Run from chauffeur/:  python tests/test_twin_edit.py
"""
import copy
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_edit_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_plan as tp  # noqa: E402
from services import twin_register as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_edit_house.plan.json')


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def expect_value_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('expected ValueError')


def house():
    with open(FIXTURE, encoding='utf-8') as f:
        return tp.normalize(json.load(f))[0]


def piece(plan, pid):
    b = plan['buildings'][0]
    for kind in ('walls', 'openings', 'rooms', 'stairs'):
        for item in b.get(kind) or []:
            if item.get('id') == pid:
                return item
    for s in b['roof']['sections']:
        if s['id'] == pid:
            return s
    return None


def walls(plan, level):
    return [w for w in plan['buildings'][0]['walls'] if w['level'] == level]


def _seed():
    storage.patch_settings({'house_twin': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    ts.push_round(house(), 'build')


def scenario_editable_fields_are_pinned():
    check(twin_edit.EDITABLE == {
        'wall': ('height', 'thickness', 'exterior'),
        'opening': ('width', 'sill', 'head', 'kind', 'panels', 'at'),
        'room': ('name', 'ha_area'),
        'roof': ('kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side', 'ends'),
        'building': ('name', 'position', 'rotation', 'base'),
        'level': ('name', 'elevation', 'ceiling')}, twin_edit.EDITABLE)


def scenario_set_pitch_marks_the_person():
    before = house()
    plan, summary = twin_edit.apply(before, {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8})
    s = piece(plan, 'roof-1')
    check(s['pitch'] == 8 and s['pitch_source'] == 'person' and s['src']['person'] is True, s)
    check(s['src'].get('sheet') == 'sheetC', 'provenance kept alongside the person mark')
    check(piece(before, 'roof-1')['pitch'] == 6, 'apply never mutates its input')
    check(summary.startswith('Set ') and 'pitch' in summary.lower(), summary)


def scenario_unknown_field_or_piece_is_refused():
    expect_value_error(lambda: twin_edit.apply(house(), {'op': 'set', 'piece': 'wall-1', 'field': 'from', 'value': [0, 0]}))
    expect_value_error(lambda: twin_edit.apply(house(), {'op': 'set', 'piece': 'wall-99', 'field': 'height', 'value': 9}))
    expect_value_error(lambda: twin_edit.apply(house(), {'op': 'teleport', 'piece': 'wall-1'}))
    expect_value_error(lambda: twin_edit.apply(house(), {'op': 'set', 'piece': 'wall-1', 'field': 'height', 'value': -3}))


def scenario_move_wall_and_room_and_section():
    plan, _ = twin_edit.apply(house(), {'op': 'move', 'piece': 'wall-2', 'by': [1, 0]})
    w = piece(plan, 'wall-2')
    check(w['from'] == [41, 0] and w['to'] == [41, 30] and w['src']['person'] is True, w)
    plan, _ = twin_edit.apply(house(), {'op': 'move', 'piece': 'room-1', 'by': [0, 2]})
    check(piece(plan, 'room-1')['polygon'][0] == [0, 2], piece(plan, 'room-1'))
    plan, _ = twin_edit.apply(house(), {'op': 'move', 'piece': 'roof-1', 'by': [-1, 0]})
    check(piece(plan, 'roof-1')['rect'] == [-1, 0, 39, 30], piece(plan, 'roof-1'))


def scenario_move_slides_an_opening_along_its_wall():
    plan, summary = twin_edit.apply(house(), {'op': 'move', 'piece': 'opening-1', 'by': [2, 5]})
    check(piece(plan, 'opening-1')['at'] == 12, 'projected onto the wall: only the along-wall part counts')
    plan, _ = twin_edit.apply(house(), {'op': 'move', 'piece': 'opening-1', 'by': [100, 0]})
    o = piece(plan, 'opening-1')
    check(o['at'] + o['width'] / 2 <= 40, 'an opening never slides off its wall')


def scenario_rotate_building_and_accept_ghosts():
    plan, summary = twin_edit.apply(house(), {'op': 'rotate', 'building': 'house', 'to': 90})
    check(plan['buildings'][0]['rotation'] == 90 and 'turned' in summary.lower(), summary)
    plan, _ = twin_edit.apply(house(), {'op': 'accept', 'pieces': ['opening-2']})
    check(piece(plan, 'opening-2')['state'] == 'settled', piece(plan, 'opening-2'))


def scenario_add_wall_and_opening():
    plan, _ = twin_edit.apply(house(), {'op': 'add_wall', 'building': 'house', 'level': 'L1',
                                        'from': [20, 0], 'to': [20, 30]})
    added = [w for w in walls(plan, 'L1') if w['from'] == [20, 0]]
    check(len(added) == 1 and added[0]['src'] == {'person': True} and added[0]['state'] == 'settled', added)
    wid = added[0]['id']
    plan, _ = twin_edit.apply(plan, {'op': 'add_opening', 'wall': wid, 'at': 15, 'kind': 'door', 'width': 3})
    check(any(o['wall'] == wid and o['kind'] == 'door' for o in plan['buildings'][0]['openings']), 'door added')


def scenario_registration_moves_every_piece_from_that_sheet():
    before = house()
    old = tr.make(0.05, origin_px=(100, 100))
    new = dict(old, offset=[old['offset'][0] + 1.0, old['offset'][1]])
    plan, _ = twin_edit.apply(before, {'op': 'registration', 'source': 'sheetB', 'page': 2, 'level': 'L2',
                                       'reg': new, 'from_reg': old})
    for w in walls(plan, 'L2'):
        b = piece(before, w['id'])
        check(close(w['from'], [b['from'][0] + 1, b['from'][1]], 1e-6) and close(w['to'], [b['to'][0] + 1, b['to'][1]], 1e-6),
              w['id'])
    check(walls(plan, 'L1') == walls(before, 'L1'), 'other sheets untouched')


def scenario_save_logs_fixes_and_a_plain_summary():
    _seed()
    out = twin_edit.save({'op': 'set', 'piece': 'opening-1', 'field': 'width', 'value': 4}, 'p1')
    check(out['summary'].startswith('Set ') and "4'-0\"" in out['summary'], out)
    check(ts.current_id() == out['round'] and ts.rounds()[-1]['kind'] == 'edit', ts.rounds()[-1])
    check(ts.fixes()[-1]['round'] == out['round'], ts.fixes())
    check(piece(ts.current(), 'opening-1')['width'] == 4, 'saved')


def scenario_delete_leaves_a_tombstone():
    _seed()
    out = twin_edit.save({'op': 'delete', 'piece': 'wall-5'}, 'p1')
    check(piece(ts.current(), 'wall-5') is None, 'deleted')
    t = ts.tombstones()[-1]
    check(t['kind'] == 'wall' and t['level'] == 'L2' and t['src']['step'] == 'walls:L2:upper', t)
    check(t['geometry']['from'] == [5, 5] and t['geometry']['to'] == [35, 5], t)
    check('Removed' in out['summary'] or 'Deleted' in out['summary'], out)


def scenario_registration_save_updates_the_store():
    import io as _io
    import pypdfium2 as pdfium
    storage.patch_settings({'house_twin': None})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    doc = pdfium.PdfDocument.new()
    for _ in range(2):
        doc.new_page(1224, 792)
    buf = _io.BytesIO()
    doc.save(buf)
    sid = ts.save_source('drawing', 'upper.pdf', buf.getvalue())
    plan = json.loads(json.dumps(house()).replace('"sheetB"', json.dumps(sid)))
    ts.push_round(plan, 'build')
    ts.set_registration(sid, 2, 'L2', tr.make(0.05, origin_px=(100, 100)))
    new = tr.make(0.05, origin_px=(100, 100), offset=(1.0, 0))
    twin_edit.save({'op': 'registration', 'source': sid, 'page': 2, 'level': 'L2', 'reg': new}, 'p1')
    check(ts.registration(sid, 2, 'L2')['offset'] == [1.0, 0], ts.registration(sid, 2, 'L2'))
    check(piece(ts.current(), 'wall-5')['from'] == [6, 5], 'pieces moved with it')


def scenario_an_id_shared_by_two_buildings_needs_the_building():
    # Review finding (Task 1): ids are unique per building only; an edit that
    # names a piece two buildings share must say which building.
    two = house()
    other = copy.deepcopy(two['buildings'][0])
    other['id'] = 'garage'
    two['buildings'].append(other)
    two, _ = tp.normalize(two)
    expect_value_error(lambda: twin_edit.apply(two, {'op': 'set', 'piece': 'wall-1', 'field': 'height', 'value': 10}))
    plan, _ = twin_edit.apply(two, {'op': 'set', 'building': 'garage', 'piece': 'wall-1', 'field': 'height', 'value': 10})
    garage = next(b for b in plan['buildings'] if b['id'] == 'garage')
    house_b = next(b for b in plan['buildings'] if b['id'] == 'house')
    check(garage['walls'][0]['height'] == 10 and house_b['walls'][0]['height'] == 9, 'only the named building')


def scenario_llm_sized_numbers_are_refused_not_crashes():
    for edit in ({'op': 'set', 'piece': 'wall-1', 'field': 'height', 'value': 10 ** 400},
                 {'op': 'set', 'piece': 'wall-1', 'field': 'height', 'value': float('nan')},
                 {'op': 'set', 'piece': 'wall-1', 'field': 'height', 'value': True},
                 {'op': 'set', 'piece': 'wall-1', 'field': 'height', 'value': '9'},
                 {'op': 'move', 'piece': 'wall-1', 'by': [1e308, 1e308]},
                 {'op': 'move', 'piece': 'wall-1', 'by': [1, 2, 3]},
                 {'op': 'set', 'building': 'house', 'piece': 'house', 'field': 'position', 'value': [1e308, 1]},
                 {'op': 'add_wall', 'building': 'house', 'level': 'L1', 'from': [0, 0], 'to': [1e-9, 0]},
                 {'op': 'add_wall', 'building': 'house', 'level': 'L1', 'from': [0, 0], 'to': [1e300, 0]},
                 {'op': 'set', 'piece': 'opening-1', 'field': 'width', 'value': 3}):     # no change
        expect_value_error(lambda: twin_edit.apply(house(), edit))


def scenario_deleting_a_wall_tombstones_what_goes_with_it():
    _seed()
    out = twin_edit.save({'op': 'delete', 'piece': 'wall-1'}, 'p1')
    plan = ts.current()
    check(piece(plan, 'wall-1') is None and piece(plan, 'opening-1') is None, 'its opening goes with it')
    kinds = sorted(t['kind'] for t in ts.tombstones())
    check(kinds == ['opening', 'wall'], kinds)
    check('opening' in out['summary'], out['summary'])


def scenario_gable_openings_follow_their_section():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json'),
              encoding='utf-8') as f:
        pool = tp.normalize(json.load(f))[0]
    before = [o['x'] for o in pool['buildings'][0]['openings'] if 'gable' in o]
    plan, _ = twin_edit.apply(pool, {'op': 'move', 'piece': 'roof-main', 'by': [1, 0]})
    after = [o['x'] for o in plan['buildings'][0]['openings'] if 'gable' in o]
    check(len(after) == len(before) == 3 and all(abs(a - b - 1) < 1e-9 for a, b in zip(after, before)), (before, after))


def scenario_registration_needs_one_on_file():
    _seed()
    try:
        twin_edit.save({'op': 'registration', 'source': 'nope', 'page': 2, 'level': 'L2',
                        'reg': tr.make(0.05)}, 'p1')
    except ValueError as exc:
        check('registration' in str(exc).lower(), exc)
    else:
        raise AssertionError('no registration on file must refuse')


def scenario_summaries_use_plain_labels_not_ids():
    plan = house()
    b = plan['buildings'][0]
    b['walls'][0]['id'] = 'wall:0650fff600eb48258bbc641401b772e9'
    for o in b['openings']:
        if o['wall'] == 'wall-1':
            o['wall'] = b['walls'][0]['id']
    plan, _ = tp.normalize(plan)
    _, summary = twin_edit.apply(plan, {'op': 'set', 'piece': b['walls'][0]['id'], 'field': 'height', 'value': 10})
    check('0650fff6' not in summary and 'wall:' not in summary, summary)
    check('Main floor' in summary and 'wall' in summary, summary)
    _, summary = twin_edit.apply(plan, {'op': 'add_opening', 'wall': b['walls'][0]['id'], 'at': 20, 'kind': 'window',
                                        'width': 3})
    check('0650fff6' not in summary and 'wall:' not in summary, summary)
    _, summary = twin_edit.apply(house(), {'op': 'set', 'piece': 'room-1', 'field': 'ha_area', 'value': 'kitchen'})
    check('ha_area' not in summary, summary)


def scenario_turning_about_the_middle_is_one_edit():
    # Review finding: a turn sent as a move plus a rotate could leave the house
    # displaced if the second half was refused; one atomic op keeps the middle put.
    before = house()
    b = before['buildings'][0]
    xs = [p[0] for w in b['walls'] for p in (w['from'], w['to'])]
    ys = [p[1] for w in b['walls'] for p in (w['from'], w['to'])]
    centre = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    plan, summary = twin_edit.apply(before, {'op': 'rotate', 'building': 'house', 'to': 90, 'about': centre})
    after = plan['buildings'][0]
    check(after['rotation'] == 90 and 'Turned' in summary, (after['rotation'], summary))
    world_before = tr.to_world(b, centre)
    world_after = tr.to_world(after, centre)
    check(close(world_before, world_after, 1e-6), (world_before, world_after))


def scenario_tombstone_matches_current_and_read_geometry():
    from services import twin_build
    _seed()

    def remember_read(plan):
        wall = piece(plan, 'wall-1')
        wall['read_geometry'] = {k: copy.deepcopy(wall[k]) for k in ('from', 'to')}
        return plan

    ts.update_current(remember_read, kind='build')
    original = copy.deepcopy(piece(ts.current(), 'wall-1'))
    twin_edit.save({'op': 'move', 'piece': 'wall-1', 'by': [0, -4]}, 'p1')
    current = copy.deepcopy(piece(ts.current(), 'wall-1'))
    twin_edit.save({'op': 'delete', 'piece': 'wall-1'}, 'p1')
    tombstone = next(t for t in ts.tombstones() if t['kind'] == 'wall')
    building = ts.current()['buildings'][0]
    check(tombstone['geometry'] == {k: current[k] for k in ('from', 'to')}, tombstone)
    check(tombstone['read_geometry'] == original['read_geometry'], tombstone)
    check(twin_build._deleted(original, 'wall', building, {}), 'original line stays deleted')
    check(twin_build._deleted(current, 'wall', building, {}), 'moved line stays deleted')
    check(not twin_build._deleted(original, 'wall', {**building, 'id': 'another-building'}, {}),
          'a different building keeps its own wall')


def scenario_ridge_x_gable_moves_and_deletes():
    _seed()
    plan = ts.current()
    b = plan['buildings'][0]
    section = b['roof']['sections'][0]
    section.update(kind='gable', ridge='x', rect=[0, 0, 30, 20])
    b['openings'].append({'id': 'ridge-x-window', 'kind': 'window', 'section': section['id'],
                          'gable': 'front', 'y': 8, 'width': 2, 'sill': 1, 'head': 3})
    ts.push_round(plan, 'build')
    twin_edit.save({'op': 'move', 'piece': section['id'], 'by': [4, 3]}, 'p1')
    opening = piece(ts.current(), 'ridge-x-window')
    check(opening['y'] == 11 and 'x' not in opening, opening)
    twin_edit.save({'op': 'delete', 'piece': opening['id']}, 'p1')
    check(piece(ts.current(), opening['id']) is None, 'delete publishes')
    stone = next(t for t in ts.tombstones() if t['kind'] == 'opening')
    check(stone['geometry'] == {'from': [4, 10], 'to': [4, 12]}, stone)


def scenario_accept_out_of_span_window_refused():
    _seed()
    plan = ts.current()
    b = plan['buildings'][0]
    opening = next(o for o in b['openings'] if 'wall' in o)
    opening.update(at=1000, state='ghost', why='This opening extends beyond its wall span or height.')
    opening['src']['step'] = 'draft'
    ts.push_round(plan, 'build')
    before = ts.current_id()
    try:
        twin_edit.save({'op': 'accept', 'pieces': [opening['id']]}, 'p1')
    except ValueError as exc:
        check(str(exc) == 'This window does not fit on its wall. Move it onto the wall or delete it.', str(exc))
    else:
        raise AssertionError('bad opening accepted')
    check(ts.current_id() == before, 'refusal publishes nothing')


def scenario_accept_invalid_door_names_kind_and_plain_reason():
    for reason in ('span', 'height'):
        _seed()
        plan = ts.current()
        b = plan['buildings'][0]
        opening = next(o for o in b['openings'] if 'wall' in o)
        opening.update(kind='door', state='ghost',
                       why='This opening extends beyond its wall span or height.')
        opening['src']['step'] = 'draft'
        if reason == 'span':
            opening['at'] = 1000
            expected = 'This door does not fit on its wall. Move it onto the wall or delete it.'
        else:
            wall = next(w for w in b['walls'] if w['id'] == opening['wall'])
            opening.update(at=5, width=2, head=wall['height'] + 10)
            expected = 'This door is taller than its wall. Lower its top or delete it.'
        ts.push_round(plan, 'build')
        before = ts.current_id()
        try:
            twin_edit.save({'op': 'accept', 'pieces': [opening['id']]}, 'p1')
        except ValueError as exc:
            check(str(exc) == expected, str(exc))
        else:
            raise AssertionError('invalid door accepted')
        check(ts.current_id() == before, 'refusal publishes nothing')


# ---- per-end roof ends (.superpowers/sdd/2026-11-08-house-editor-roofs-from-photos task 2):
# the roof card sets ends {<end>: 'gable'|'hip'|'clip'} on a section with one set
# edit (the whole mapping as the value); roof-1 is a ridge-x hip, ends x0 and x1.

def scenario_test_card_sets_roof_ends():
    before = house()
    plan, summary = twin_edit.apply(before, {'op': 'set', 'piece': 'roof-1', 'field': 'ends',
                                             'value': {'x0': 'gable', 'x1': 'hip'}})
    s = piece(plan, 'roof-1')
    check(s.get('ends') == {'x0': 'gable', 'x1': 'hip'} and s['src']['person'] is True, s)
    check('ends' not in piece(before, 'roof-1'), 'apply never mutates its input')
    check(summary.startswith('Set ') and '{' not in summary and 'x0' not in summary,
          f'a plain summary, no raw mapping or end ids: {summary}')
    renormalized, notes = tp.normalize(plan)
    check(piece(renormalized, 'roof-1').get('ends') == {'x0': 'gable', 'x1': 'hip'}, ('ends survive normalize', notes))

    _seed()
    out = twin_edit.save({'op': 'set', 'piece': 'roof-1', 'field': 'ends', 'value': {'x0': 'clip', 'x1': 'gable'}}, 'p1')
    check(ts.current_id() == out['round'] and ts.rounds()[-1]['kind'] == 'edit', ts.rounds()[-1])
    s = piece(ts.current(), 'roof-1')
    check(s.get('ends') == {'x0': 'clip', 'x1': 'gable'} and s['src']['person'] is True, f'persisted: {s}')
    check(s['kind'] == 'hip' and s['ridge'] == 'x' and s['pitch'] == 6, 'nothing else changed')


def scenario_test_invalid_roof_ends_refused():
    for bad in ({'x0': 'dome'},          # not gable, hip or clip
                {'y0': 'hip'},           # roof-1 runs left to right: its ends are x0 and x1
                'hip',                   # not a mapping
                ['x0', 'gable']):
        expect_value_error(lambda bad=bad: twin_edit.apply(
            house(), {'op': 'set', 'piece': 'roof-1', 'field': 'ends', 'value': bad}))
    _seed()
    before = ts.current_id()
    try:
        twin_edit.save({'op': 'set', 'piece': 'roof-1', 'field': 'ends', 'value': {'x1': 'dome'}}, 'p1')
    except ValueError:
        pass
    else:
        raise AssertionError('invalid end accepted')
    check(ts.current_id() == before, 'refusal publishes nothing')


def scenario_roof_kind_switch_clears_ends():
    for kind in ('shed', 'flat'):
        plan, _ = twin_edit.apply(house(), {'op': 'set', 'piece': 'roof-1', 'field': 'ends',
                                           'value': {'x0': 'clip', 'x1': 'gable'}})
        plan, _ = twin_edit.apply(plan, {'op': 'set', 'piece': 'roof-1', 'field': 'kind', 'value': kind})
        roof = piece(plan, 'roof-1')
        check(roof['kind'] == kind and 'ends' not in roof, roof)
        check(roof['pitch'] == 0 if kind == 'flat' else roof['low_side'] == 'x0', roof)


def scenario_hip_end_with_window_names_the_remedy():
    for ridge, end, coordinate in (('x', 'x0', 'y'), ('y', 'y1', 'x')):
        _seed()
        plan = ts.current()
        roof = piece(plan, 'roof-1')
        roof.update(kind='gable', ridge=ridge, rect=[0, 0, 30, 20])
        plan['buildings'][0]['openings'].append(
            {'id': 'gable-window', 'kind': 'window', 'section': 'roof-1',
             'gable': 'front' if end.endswith('0') else 'rear', coordinate: 10,
             'width': 2, 'sill': 1, 'head': 3})
        ts.push_round(plan, 'build')
        before = ts.current_id()
        try:
            twin_edit.save({'op': 'set', 'piece': 'roof-1', 'field': 'ends',
                            'value': {end: 'hip'}}, 'p1')
        except ValueError as exc:
            check(str(exc) == 'A window sits in that gable; move or delete it first.', str(exc))
        else:
            raise AssertionError('a window-bearing gable became a hip')
        check(ts.current_id() == before, 'refusal publishes nothing')
        check(piece(ts.current(), 'gable-window') is not None, 'window retained')


if __name__ == '__main__':
    scenario_accept_invalid_door_names_kind_and_plain_reason()
    scenario_ridge_x_gable_moves_and_deletes()
    scenario_accept_out_of_span_window_refused()
    scenario_tombstone_matches_current_and_read_geometry()
    print('  ok ', scenario_tombstone_matches_current_and_read_geometry.__name__)
    for fn in (scenario_editable_fields_are_pinned,
               scenario_set_pitch_marks_the_person,
               scenario_unknown_field_or_piece_is_refused,
               scenario_move_wall_and_room_and_section,
               scenario_move_slides_an_opening_along_its_wall,
               scenario_rotate_building_and_accept_ghosts,
               scenario_add_wall_and_opening,
               scenario_registration_moves_every_piece_from_that_sheet,
               scenario_save_logs_fixes_and_a_plain_summary,
               scenario_delete_leaves_a_tombstone,
               scenario_registration_save_updates_the_store,
               scenario_an_id_shared_by_two_buildings_needs_the_building,
               scenario_llm_sized_numbers_are_refused_not_crashes,
               scenario_deleting_a_wall_tombstones_what_goes_with_it,
               scenario_gable_openings_follow_their_section,
               scenario_registration_needs_one_on_file,
               scenario_summaries_use_plain_labels_not_ids,
               scenario_turning_about_the_middle_is_one_edit):
        fn()
        print('  ok ', fn.__name__)
    # Per-end roof ends: each reported on its own so one failure does not hide the other.
    failed = []
    for fn in (scenario_test_card_sets_roof_ends,
               scenario_test_invalid_roof_ends_refused,
               scenario_roof_kind_switch_clears_ends,
               scenario_hip_end_with_window_names_the_remedy):
        try:
            fn()
        except Exception as e:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, repr(e)[:300])
        else:
            print('  ok ', fn.__name__)
    if failed:
        raise SystemExit(1)
