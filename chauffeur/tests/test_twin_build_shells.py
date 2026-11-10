"""Shells for buildings without drawings (plan .superpowers/sdd/
2026-11-07-house-editor-slice-1b-i, Task 5): walls, a roof and one door built
from a building's footprint and its shell card.

- twin_place.shell_building(building, step_id) turns a place building into a
  plan building at position [0, 0], rotation 0, base 0: one level per storey
  (L<n>, Floor <n>, elevation (n-1) * wall_height, ceiling wall_height,
  outline = footprint), exterior walls along every footprint edge on every
  level (thickness 0.5, height wall_height), one roof section on the
  footprint's bounding rectangle (kind and pitch from the card, ridge along
  the longer side, plate storeys * wall_height, overhang 1, pitch_source
  'card', a shed's low side at the back y1), and one 3 ft door (head 6.67,
  sill 0) centred on the longest L1 wall whose outward normal faces the
  card's door side (front -y, back +y, left -x, right +x). Every piece is
  settled with src {'sheet': '', 'page': 1, 'step': step_id}.
- start({'part': <id>}) for a building with no floor pages runs the steps
  shell then compose, with no read; with no footprint it is refused with
  "Give <name> a footprint: type its size or draw it on the lot."
- a rebuilt shell settles through _merge_list, so a wall a person moved stays
  where the person put it.
- a shell's roof draws: twin_roof.js gives it a non-empty mesh.

Helpers come from test_twin_build and test_twin_build_parts by import, as
those files do. The roof check uses test_twin_roof_js's node harness and is
skipped (not failed) when node is missing.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_shells.py
"""
import math
import os
import shutil
import sys
import tempfile
import traceback

# Never let a run touch chauffeur/data: the temp folder is set before any
# services import, unconditionally.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_shells_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_place as tp  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _accept_all, check, close  # noqa: E402
from test_twin_build_parts import _expect_value_error, _kinds  # noqa: E402
import test_twin_roof_js as roof_js  # noqa: E402

RECT = [[0, 0], [10, 0], [10, 12], [0, 12]]
WIDE = [[0, 0], [20, 0], [20, 12], [0, 12]]
# An L, wound clockwise on purpose: the door rule speaks of outward normals,
# whatever order the footprint's points come in.
L_CW = list(reversed([[0, 0], [30, 0], [30, 10], [12, 10], [12, 24], [0, 24]]))


def _no_footprint(name):
    return f'Give {name} a footprint: type its size or draw it on the lot.'


# --- helpers -------------------------------------------------------------------

def _segment(a, b):
    return frozenset((tuple(round(v, 6) for v in a), tuple(round(v, 6) for v in b)))


def _edges(points):
    return {_segment(a, b) for a, b in zip(points, points[1:] + points[:1])}


def _shed_place(footprint=RECT, shell=None, name='Shed', kind='shed'):
    """A place with one building and no drawings at all."""
    engine_tests._fresh()
    building = ts.add_building(name, kind)
    fields = {}
    if footprint is not None:
        fields.update(footprint=footprint, footprint_from='typed')
    if shell:
        fields['shell'] = shell
    if fields:
        building = ts.update_building(building['id'], fields)
    return building


def _place_building(bid):
    return next(b for b in ts.place()['buildings'] if b['id'] == bid)


def _plan_building(plan, bid):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _pieces(building):
    return [*building['walls'], *building['openings'], *building['roof']['sections']]


def _door(building):
    doors = building['openings']
    check(len(doors) == 1, ('one door', doors))
    door = doors[0]
    wall = next((w for w in building['walls'] if w['id'] == door.get('wall')), None)
    check(wall is not None, ('the door hangs on a wall of the building', door))
    return door, wall


def _check_settled(building, step_id):
    want = {'sheet': '', 'page': 1, 'step': step_id}
    for piece in _pieces(building):
        check(piece.get('state') == 'settled', ('every shell piece is settled', piece))
        check(piece.get('src') == want, ('every shell piece names the shell step', piece.get('src'), want))


def _check_rect_shed(building, step_id):
    """The 10 x 12 ft, one storey, 8 ft, gable 6:12, front door shell."""
    check((building['id'], building['name'], building['kind']) == ('shed', 'Shed', 'shed'),
          ('id, name and kind come from the place', building['id'], building['name'], building.get('kind')))
    check(building['position'] == [0, 0] and building['rotation'] == 0 and building['base'] == 0,
          (building['position'], building['rotation'], building.get('base')))
    levels = building['levels']
    check(len(levels) == 1, ('one level', levels))
    level = levels[0]
    check((level['id'], level['name'], level['elevation'], level['ceiling']) == ('L1', 'Floor 1', 0, 8), level)
    outline = level.get('outline') or []
    check(len(outline) == 4 and all(close(a, b) for a, b in zip(outline, RECT)), ('outline = footprint', outline))
    walls = building['walls']
    check(len(walls) == 4, ('four walls', walls))
    check({_segment(w['from'], w['to']) for w in walls} == _edges(RECT), ('a wall on each footprint edge', walls))
    for wall in walls:
        check(wall['level'] == 'L1' and wall['height'] == 8 and wall['thickness'] == 0.5 and wall['exterior'] is True,
              ('exterior, 8 ft high, 0.5 ft thick', wall))
    sections = building['roof']['sections']
    check(len(sections) == 1, ('one roof section', sections))
    roof = sections[0]
    check(close(roof['rect'], [0, 0, 10, 12], 1e-9), ('the footprint bounds', roof['rect']))
    check(roof['kind'] == 'gable' and roof['ridge'] == 'y', ('a gable, ridge along the longer side', roof))
    check(roof['plate'] == 8 and roof['pitch'] == 6 and roof['overhang'] == 1 and roof['pitch_source'] == 'card',
          ('plate 8, pitch 6 from the card, overhang 1', roof))
    door, wall = _door(building)
    check(_segment(wall['from'], wall['to']) == _segment([0, 0], [10, 0]),
          ('the front door is on the street side, y = 0', wall))
    check(wall['level'] == 'L1', ('the door is on the ground floor', wall))
    check(door['kind'] == 'door' and abs(door['at'] - 5) < 1e-6, ('centred, at 5', door))
    check(door['width'] == 3 and abs(door['head'] - 6.67) < 1e-9 and door['sill'] == 0,
          ('3 ft wide, head 6.67, sill 0', door))
    _check_settled(building, step_id)


def _expect_no_build():
    check(tb.latest() is None, ('a refused start leaves no build behind', tb.latest()))


# --- shell_building ------------------------------------------------------------

def scenario_shell_geometry():
    _shed_place()
    building = tp.shell_building(_place_building('shed'), 'shell')
    _check_rect_shed(building, 'shell')
    normalized, notes = twin_plan.normalize({'units': 'ft', 'buildings': [building], 'site': {}})
    check(notes == [], ('a shell needs no repairs', notes))
    kept = _plan_building(normalized, 'shed')
    check(len(kept['walls']) == 4 and len(kept['openings']) == 1 and len(kept['roof']['sections']) == 1,
          ('normalize keeps every piece', kept))
    check(kept['roof']['sections'][0]['pitch_source'] == 'card', ('pitch_source card survives', kept['roof']))
    _check_settled(kept, 'shell')

    # The same shell through a build of the part: no read, shell then compose.
    reader = Reader()
    b = tb.start({'part': 'shed'}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(st.get('part') == 'shed', st.get('part'))
    check(_kinds(b) == ['shell', 'compose'], ('a building without drawings builds as a shell', _kinds(b)))
    check(reader.calls == [], ('a shell is never read', [c['kind'] for c in reader.calls]))
    step_id = next(s['id'] for s in st['steps'] if s['kind'] == 'shell')
    plan = ts.current()
    check([b_['id'] for b_ in plan['buildings']] == ['shed'], plan['buildings'])
    _check_rect_shed(_plan_building(plan, 'shed'), step_id)


def scenario_shell_two_storeys_hip_left_door():
    _shed_place(footprint=WIDE, shell={'storeys': 2, 'wall_height': 9, 'roof': 'hip', 'door_side': 'left'})
    building = tp.shell_building(_place_building('shed'), 'shell')
    levels = building['levels']
    check([(l['id'], l['name'], l['elevation'], l['ceiling']) for l in levels]
          == [('L1', 'Floor 1', 0, 9), ('L2', 'Floor 2', 9, 9)], levels)
    for level in levels:
        check(len(level['outline']) == 4 and all(close(a, b) for a, b in zip(level['outline'], WIDE)),
              ('each floor outline = footprint', level))
        walls = [w for w in building['walls'] if w['level'] == level['id']]
        check({_segment(w['from'], w['to']) for w in walls} == _edges(WIDE) and len(walls) == 4,
              ('exterior walls on every level', level['id'], walls))
        check(all(w['height'] == 9 and w['thickness'] == 0.5 and w['exterior'] is True for w in walls), walls)
    check(len(building['walls']) == 8, building['walls'])
    roof = building['roof']['sections']
    check(len(roof) == 1, roof)
    roof = roof[0]
    check(roof['kind'] == 'hip' and roof['ridge'] == 'x' and close(roof['rect'], [0, 0, 20, 12], 1e-9),
          ('a hip along the longer x side', roof))
    check(roof['plate'] == 18 and roof['pitch'] == 6 and roof['pitch_source'] == 'card', ('plate 2 x 9', roof))
    door, wall = _door(building)
    check(_segment(wall['from'], wall['to']) == _segment([0, 0], [0, 12]) and wall['level'] == 'L1',
          ('the left door is on the x = 0 wall of the ground floor', wall))
    check(abs(door['at'] - 6) < 1e-6, ('centred on the 12 ft wall', door))
    _, notes = twin_plan.normalize({'units': 'ft', 'buildings': [building], 'site': {}})
    check(notes == [], notes)


def scenario_shell_door_on_longest_facing_wall():
    # The brief's rule on a footprint with two walls facing each way.
    _shed_place(footprint=L_CW, shell={'door_side': 'back'})
    building = tp.shell_building(_place_building('shed'), 'shell')
    check(close(building['roof']['sections'][0]['rect'], [0, 0, 30, 24], 1e-9),
          ('the roof covers the bounding rectangle', building['roof']['sections'][0]['rect']))
    check(building['roof']['sections'][0]['ridge'] == 'x', building['roof']['sections'][0])
    check(len(building['walls']) == 6 and {_segment(w['from'], w['to']) for w in building['walls']} == _edges(L_CW),
          building['walls'])
    door, wall = _door(building)
    # Back (+y) faces: y = 10 from x 12 to 30 (18 ft) and y = 24 from x 0 to 12 (12 ft).
    check(_segment(wall['from'], wall['to']) == _segment([30, 10], [12, 10]), ('the longer back wall', wall))
    check(abs(door['at'] - 9) < 1e-6, door)
    ts.update_building('shed', {'shell': {'door_side': 'right'}})
    building = tp.shell_building(_place_building('shed'), 'shell')
    door, wall = _door(building)
    # Right (+x) faces: x = 30 from y 0 to 10 (10 ft) and x = 12 from y 10 to 24 (14 ft).
    check(_segment(wall['from'], wall['to']) == _segment([12, 10], [12, 24]), ('the longer right wall', wall))
    check(abs(door['at'] - 7) < 1e-6, door)
    _, notes = twin_plan.normalize({'units': 'ft', 'buildings': [building], 'site': {}})
    check(notes == [], notes)


# --- the build -----------------------------------------------------------------

def scenario_shell_needs_footprint():
    _shed_place(footprint=None, name='Garden shed')
    check(_place_building('garden-shed')['footprint'] is None, _place_building('garden-shed'))
    _expect_value_error(lambda: tb.start({'part': 'garden-shed'}, reader=Reader(), inline=True),
                        _no_footprint('Garden shed'))
    _expect_no_build()
    check(ts.current() is None, ('nothing was built', ts.current()))


def scenario_shell_rebuild_keeps_person_edit():
    _shed_place()
    b = tb.start({'part': 'shed'}, reader=Reader(), inline=True)
    check(_accept_all(b)['state'] == 'done', tb.status(b)['state'])
    shed = _plan_building(ts.current(), 'shed')
    back = next(w for w in shed['walls'] if _segment(w['from'], w['to']) == _segment([0, 12], [10, 12]))
    twin_edit.save({'op': 'move', 'building': 'shed', 'piece': back['id'], 'by': [0, 2]}, 'p1')
    moved = next(w for w in _plan_building(ts.current(), 'shed')['walls'] if w['id'] == back['id'])
    check(_segment(moved['from'], moved['to']) == _segment([0, 14], [10, 14]), ('the person moved it', moved))

    reader = Reader()
    b = tb.start({'part': 'shed'}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(_kinds(b) == ['shell', 'compose'] and reader.calls == [], (_kinds(b), reader.calls))
    shed = _plan_building(ts.current(), 'shed')
    wall = next((w for w in shed['walls'] if w['id'] == back['id']), None)
    check(wall is not None, ('the moved wall keeps its id', [w['id'] for w in shed['walls']], back['id']))
    check(_segment(wall['from'], wall['to']) == _segment([0, 14], [10, 14]),
          ('a rebuild leaves the wall where the person put it', wall))
    check((wall.get('src') or {}).get('person') is True, ('still the person\'s wall', wall.get('src')))
    check(len(shed['walls']) == 4, ('no second back wall at the old place', [(w['from'], w['to']) for w in shed['walls']]))
    check(not any(_segment(w['from'], w['to']) == _segment([0, 12], [10, 12]) for w in shed['walls']),
          ('the read line is not put back', shed['walls']))
    check(len(shed['openings']) == 1, ('still one door', shed['openings']))


def scenario_shell_roof_draws():
    _shed_place()
    b = tb.start({'part': 'shed'}, reader=Reader(), inline=True)
    check(_accept_all(b)['state'] == 'done', tb.status(b)['state'])
    sections = _plan_building(ts.current(), 'shed')['roof']['sections']
    check(len(sections) == 1, sections)
    # Every card roof, straight from shell_building.
    cards = {}
    for roof in ('hip', 'shed', 'flat'):
        ts.update_building('shed', {'shell': {'roof': roof}})
        cards[roof] = tp.shell_building(_place_building('shed'), 'shell')['roof']['sections']
    check(cards['shed'][0]['kind'] == 'shed' and cards['shed'][0].get('low_side') == 'y1',
          ('a shed roof falls to the back', cards['shed'][0]))
    check(cards['flat'][0]['kind'] == 'flat' and cards['flat'][0]['pitch'] == 0, ('a flat roof has no pitch', cards['flat'][0]))
    for roof, found in cards.items():
        _, notes = twin_plan.normalize({'units': 'ft', 'buildings': [{
            **tp.shell_building(_place_building('shed'), 'shell'), 'roof': {'sections': found}}], 'site': {}})
        check(notes == [], (roof, notes))
    if not shutil.which('node'):
        print('  ..  roof mesh skipped (node not available)')
        return
    js = roof_js.Node()
    for name, found in (('built gable', sections), *cards.items()):
        r = js.mesh(found)
        check(r['triangles'] > 0 and r['sectionOf'] == r['triangles'], (name, 'a non-empty roof mesh', r))
        check(r['uncovered'] == 0 and r['maxError'] < 0.01 and r['downward'] == 0, (name, r))
    r = js.mesh(sections)
    check(r['gableTriangles'] == 2, ('the gable shell has both gable ends', r))
    r = js.run({'cover': sections})
    check(r['points'] > 0 and r['holes'] == 0 and r['wrong'] == 0, ('the roof has no holes', r))


def scenario_shell_moved_then_deleted_wall_stays_deleted():
    _shed_place()

    def rebuild():
        b = tb.start({'part': 'shed'}, reader=Reader(), inline=True)
        check(_accept_all(b)['state'] == 'done', tb.status(b))
        return _plan_building(ts.current(), 'shed')

    shed = rebuild()
    _, front = _door(shed)
    original = {'from': front['from'][:], 'to': front['to'][:]}
    twin_edit.save({'op': 'move', 'building': 'shed', 'piece': front['id'], 'by': [0, -2]}, 'p1')
    shed = rebuild()
    check(len(shed['walls']) == 4, shed['walls'])
    moved = next(w for w in shed['walls'] if w['id'] == front['id'])
    current = {'from': moved['from'][:], 'to': moved['to'][:]}
    twin_edit.save({'op': 'delete', 'building': 'shed', 'piece': front['id']}, 'p1')
    tombstone = next(t for t in ts.tombstones() if t['kind'] == 'wall')
    check(tombstone['geometry'] == current and tombstone.get('read_geometry') == original, tombstone)
    shed = rebuild()
    check(len(shed['walls']) == 3, shed['walls'])
    check(not shed['openings'], shed['openings'])
    check(all(_segment(w['from'], w['to']) not in (
        _segment(*original.values()), _segment(*current.values())) for w in shed['walls']), shed['walls'])


def scenario_shell_refit_then_rebuild_lands_on_footprint_once():
    from services import twin_place_reads as tpr, twin_register as tr
    from test_twin_build_parts import _lot_only
    for edge, drag in ((None, [20, 10]), ([0, 1], [0, 0])):
        _lot_only()
        tpr.read_plot(reader=Reader())
        suggestion = ts.place()['lot']['read']['suggestions'][0]
        tpr.answer_suggestion(suggestion['id'], 'accept', name='Shed', kind='shed')
        tpr.confirm_placement(None, [])
        tb.start({'part': 'shed'}, reader=Reader(), inline=True)
        footprint = _place_building('shed')['footprint']
        dragged = [[x + drag[0], y + drag[1]] for x, y in footprint]
        tpr.confirm_placement(edge, [] if edge else [{'building': 'shed', 'outline': dragged}])
        footprint = _place_building('shed')['footprint']
        b = tb.start({'part': 'shed'}, reader=Reader(), inline=True)
        check(tb.status(b)['state'] == 'done', tb.status(b))
        shed = _plan_building(ts.current(), 'shed')
        world = [tr.to_world(shed, p) for p in shed['levels'][0]['outline']]
        check(_edges(world) == _edges(footprint), (edge, world, footprint))


def scenario_shell_fewer_storeys_drops_only_empty_generated_levels():
    for edit in ('none', 'level', 'wall', 'room'):
        _shed_place(shell={'storeys': 2})
        tb.start({'part': 'shed'}, reader=Reader(), inline=True)

        def person_edit(plan):
            shed = _plan_building(plan, 'shed')
            if edit == 'level':
                shed['levels'][1]['src'] = {'person': True}
            elif edit == 'wall':
                next(w for w in shed['walls'] if w['level'] == 'L2')['src']['person'] = True
            elif edit == 'room':
                shed['rooms'].append({'id': 'my-room', 'name': 'Loft', 'level': 'L2',
                                      'polygon': RECT, 'src': {'person': True}})
            return plan

        ts.update_current(person_edit, kind='edit')
        ts.update_building('shed', {'shell': {'storeys': 1}})
        b = tb.start({'part': 'shed'}, reader=Reader(), inline=True)
        check(tb.status(b)['state'] == 'done', tb.status(b))
        shed = _plan_building(ts.current(), 'shed')
        check([l['id'] for l in shed['levels']] == (['L1'] if edit == 'none' else ['L1', 'L2']), (edit, shed))
        # Invisible separators that keep the person's room closed are the
        # model's (R1), not generated walls.
        check(not any(w['level'] == 'L2' and not w.get('src', {}).get('person')
                      and w.get('kind') != 'separator' for w in shed['walls']), shed)


def scenario_renamed_shell_still_lands_on_footprint():
    from services import twin_place_reads as tpr, twin_register as tr
    from test_twin_build_parts import _lot_only
    for edit in (None, {'op': 'move', 'piece': 'shed', 'by': [5, 7]},
                 {'op': 'rotate', 'to': 90},
                 {'op': 'set', 'piece': 'shed', 'field': 'position', 'value': [12, 34]},
                 {'op': 'set', 'piece': 'shed', 'field': 'rotation', 'value': 180}):
        _lot_only()
        tpr.read_plot(reader=Reader())
        tpr.answer_suggestion(ts.place()['lot']['read']['suggestions'][0]['id'],
                              'accept', name='Shed', kind='shed')
        tpr.confirm_placement(None, [])
        check(tb.status(tb.start({'part': 'shed'}, reader=Reader(), inline=True))['state'] == 'done', 'built')
        footprint = _place_building('shed')['footprint']
        tpr.confirm_placement(None, [{'building': 'shed', 'outline': [[x + 20, y + 10] for x, y in footprint]}])
        if edit:
            twin_edit.save({**edit, 'building': 'shed'}, 'p1')
        before = _plan_building(ts.current(), 'shed')
        twin_edit.save({'op': 'set', 'building': 'shed', 'piece': 'shed',
                        'field': 'name', 'value': 'Garden shed'}, 'p1')
        check(tb.status(tb.start({'part': 'shed'}, reader=Reader(), inline=True))['state'] == 'done', 'rebuilt')
        shed = _plan_building(ts.current(), 'shed')
        check(shed['name'] == 'Garden shed', shed['name'])
        if edit:
            check(shed['position'] == before['position'] and shed['rotation'] == before['rotation'],
                  'rename retains a person-placed transform across rebuild')
        else:
            world = [tr.to_world(shed, p) for p in shed['levels'][0]['outline']]
            check(_edges(world) == _edges(_place_building('shed')['footprint']),
                  ('a rename does not apply the refit offset twice', world))
    # A dragged answer to the build's placement pause also pins the transform.
    engine_tests.scenario_lot_placement_answer_moves_and_turns_the_building()
    check(_plan_building(ts.current(), 'house').get('position_from') == 'person',
          'the placement answer records who placed the building')
    ts.update_building('house', {'footprint': RECT, 'footprint_from': 'typed'})
    ts.set_page_roles([{**row, 'role': 'other', 'level': None}
                       if row['building'] == 'house' else row for row in ts.page_roles()])
    check(tb.status(tb.start({'part': 'house'}, reader=Reader(), inline=True))['state'] == 'done',
          'a building whose drawings are now Other rebuilds as a shell')
    house = _plan_building(ts.current(), 'house')
    check(house['position'] == [10, 20] and house['rotation'] == 90,
          'a shell rebuild keeps the dragged placement')


SCENARIOS = (
    scenario_renamed_shell_still_lands_on_footprint,
    scenario_shell_refit_then_rebuild_lands_on_footprint_once,
    scenario_shell_fewer_storeys_drops_only_empty_generated_levels,
    scenario_shell_moved_then_deleted_wall_stays_deleted,
    scenario_shell_geometry,
    scenario_shell_two_storeys_hip_left_door,
    scenario_shell_door_on_longest_facing_wall,
    scenario_shell_needs_footprint,
    scenario_shell_rebuild_keeps_person_edit,
    scenario_shell_roof_draws,
)


if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)
