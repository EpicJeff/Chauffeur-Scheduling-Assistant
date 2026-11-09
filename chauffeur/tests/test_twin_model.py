"""Schema 3 and rooms derived from walls (brief
.superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/task-2-brief.md;
spec docs/superpowers/specs/2026-11-09-house-connected-model-design.md
sections 4.1-4.3; plan docs/superpowers/plans/2026-11-09-house-connected-
model-pieces-1-2.md Task 2).

Module under test: services/twin_model.py.

- SCHEMA = 'chauffeur.twin.plan/3'.
- normalize(model) -> (model, notes): validates and re-derives.
- derive(building) -> building: re-derives rooms and flags in place.

Rules pinned here:
- Rooms are re-derived on every normalize. A region keeps the identity of the
  stored room whose cached polygon overlaps it most (at least 25% of the
  region). Of two regions claiming one room, the larger keeps it; the smaller
  gets a new id named 'Room'. A region nobody claims gets a new room named
  'Room'. A stored room with no region is dropped, and its name moves into a
  flag "This room isn't closed: a wall is missing here." at the stored
  polygon's centroid.
- Every open end gets that same flag, deduplicated within 1 ft.
- Caps: walls 400, joints 800, openings 400, rooms 120, roofs 40, anchors 400,
  items 600, each refused with a note.
- An opening on an unknown wall is kept as state 'ghost' with a note naming it.
- Ledger R7: a dropped room lives on inside its unclosed flag as
  piece {room: <the full room record>}; the flag persists across normalizes;
  when a region reappears that overlaps the cached polygon by the claim rule,
  derive restores the room (id, name, ha_area, materials) and removes the flag.
- Ledger R8: any stored room that loses its region is flagged, including one
  swallowed by a neighbour.
- Ledger R9: normalize forces separator thickness to 0.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_model.py
"""
import copy
import os
import re
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_model_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_model  # noqa: E402

NOT_CLOSED = "This room isn't closed: a wall is missing here."
LOT = [[-40, -40], [80, -40], [80, 80], [-40, 80]]
OAK = {'id': 'oak', 'color': '#a07040'}
PLASTER = {'id': 'plaster', 'color': '#f4f1ea'}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


def near(p, q, tol=1e-6):
    return close(p[0], q[0], tol) and close(p[1], q[1], tol)


def signed_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def point_set(poly):
    return {(round(p[0], 6), round(p[1], 6)) for p in poly}


# ---------------------------------------------------------------- fixtures

def level(lid='L1', elevation=0, name='Ground'):
    return {'id': lid, 'name': name, 'elevation': elevation, 'ceiling': 9}


def joint(jid, x, y, lvl='L1'):
    return {'id': jid, 'level': lvl, 'at': [x, y]}


def wall(wid, a, b, kind='solid', exterior=False, lvl='L1'):
    return {'id': wid, 'level': lvl, 'joints': [a, b], 'kind': kind,
            'thickness': 0.5 if exterior else 0.33, 'exterior': exterior}


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def room(rid, name, polygon, lvl='L1', kind='room', **extra):
    out = {'id': rid, 'level': lvl, 'name': name, 'kind': kind,
           'polygon': copy.deepcopy(polygon), 'joints': []}
    out.update(extra)
    return out


def box_joints(x1=10, y1=8):
    # c0 (0,0), c1 (x1,0), c2 (x1,y1), c3 (0,y1)
    return [joint('c0', 0, 0), joint('c1', x1, 0), joint('c2', x1, y1), joint('c3', 0, y1)]


def box_walls():
    # bottom b, right r, top t, left l; counter-clockwise, exterior
    return [wall('b', 'c0', 'c1', exterior=True), wall('r', 'c1', 'c2', exterior=True),
            wall('t', 'c2', 'c3', exterior=True), wall('l', 'c3', 'c0', exterior=True)]


def building(joints, walls, rooms, levels=None, **extra):
    out = {'id': 'main', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0,
           'materials': {}, 'levels': levels or [level()],
           'joints': joints, 'walls': walls, 'rooms': rooms,
           'openings': [], 'anchors': [], 'items': [], 'roofs': [], 'dormers': [],
           'extensions': [], 'stairs': [], 'proposals': [], 'flags': []}
    out.update(extra)
    return out


def model(b):
    return {'schema': 'chauffeur.twin.plan/3', 'units': 'ft', 'materials': {},
            'buildings': [b], 'site': {'lot': copy.deepcopy(LOT)}}


def t_box(mid_x=5, rooms=None):
    # a 10x8 box with an interior wall 'mid' from (mid_x,0) to (mid_x,8);
    # its joints m0 and m1 lie on the bottom and top walls (T-junctions)
    joints = box_joints() + [joint('m0', mid_x, 0), joint('m1', mid_x, 8)]
    walls = box_walls() + [wall('mid', 'm0', 'm1')]
    return building(joints, walls, rooms or [])


def kitchen_dining(split_x=5):
    # Kitchen on the left of x=split_x, Dining on the right (cached polygons)
    return [room('kitchen', 'Kitchen', rect(0, 0, split_x, 8), ha_area='kitchen',
                 floor_material=OAK, ceiling_material=PLASTER),
            room('dining', 'Dining', rect(split_x, 0, 10, 8))]


def gap_box(stored_rooms=None, extra_joints=(), extra_walls=()):
    # the 10x8 box with the right wall shortened by 2 ft: it runs (10,0)->(10,6),
    # leaving a gap between g (10,6) and c2 (10,8)
    joints = box_joints() + [joint('g', 10, 6)] + list(extra_joints)
    walls = [wall('b', 'c0', 'c1', exterior=True), wall('r', 'c1', 'g', exterior=True),
             wall('t', 'c2', 'c3', exterior=True), wall('l', 'c3', 'c0', exterior=True)]
    return building(joints, walls + list(extra_walls), stored_rooms or [])


def run(b):
    out, notes = twin_model.normalize(model(b))
    check(isinstance(notes, list) and all(isinstance(n, str) for n in notes), notes)
    check(len(out['buildings']) == 1, out['buildings'])
    return out['buildings'][0], notes, out


def rooms_by_name(b):
    found = {}
    for r in b['rooms']:
        found.setdefault(r['name'], []).append(r)
    return found


def joint_at(b):
    return {j['id']: j['at'] for j in b['joints']}


def check_room_geometry(b, r, want_poly):
    """The room's polygon is the region: its points, positive (CCW) area, and
    a joints cache whose positions are the polygon's points."""
    check(point_set(r['polygon']) == point_set(want_poly), (r['name'], r['polygon'], want_poly))
    check(close(signed_area(r['polygon']), abs(signed_area(want_poly)), 1e-6),
          (r['name'], signed_area(r['polygon'])))
    at = joint_at(b)
    check(isinstance(r.get('joints'), list) and all(j in at for j in r['joints']),
          (r['name'], r.get('joints')))
    check(point_set([at[j] for j in r['joints']]) == point_set(want_poly),
          (r['name'], r['joints'], [at[j] for j in r['joints']]))


def closed_flags(b):
    return [f for f in b['flags'] if f.get('text') == NOT_CLOSED]


def flag_room(f):
    """The room record a flag carries (ledger R7: piece {room: <record>})."""
    piece = f.get('piece')
    return piece.get('room') if isinstance(piece, dict) and isinstance(piece.get('room'), dict) else None


def room_flags(b, name):
    return [f for f in closed_flags(b) if (flag_room(f) or {}).get('name') == name]


VALID_ID = re.compile(r'[A-Za-z0-9_.:~-]{1,64}')


# ------------------------------------------------------------------- tests

def test_schema_is_3_and_site_passes_through():
    check(twin_model.SCHEMA == 'chauffeur.twin.plan/3', twin_model.SCHEMA)
    b, _notes, out = run(t_box(rooms=kitchen_dining()))
    check(out['schema'] == 'chauffeur.twin.plan/3', out['schema'])
    check(out['units'] == 'ft', out['units'])
    check(isinstance(out['materials'], dict), out['materials'])
    check(out['site'].get('lot') == LOT, out['site'])
    check(b['id'] == 'main' and b['name'] == 'House', b)


def test_rooms_are_derived_and_keep_names():
    # stale caches: Kitchen's stored polygon stops at x=4.5, Dining's starts at 5.5;
    # the walls say the split is at x=5
    stored = [room('kitchen', 'Kitchen', rect(0, 0, 4.5, 8), ha_area='kitchen',
                   floor_material=OAK, ceiling_material=PLASTER),
              room('dining', 'Dining', rect(5.5, 0, 10, 8))]
    b, _notes, _out = run(t_box(rooms=stored))
    check(len(b['rooms']) == 2, b['rooms'])
    named = rooms_by_name(b)
    check(set(named) == {'Kitchen', 'Dining'}, list(named))
    kitchen, dining = named['Kitchen'][0], named['Dining'][0]
    check(kitchen['id'] == 'kitchen' and dining['id'] == 'dining', (kitchen['id'], dining['id']))
    check(kitchen['level'] == 'L1' and dining['level'] == 'L1', (kitchen, dining))
    check(kitchen['kind'] == 'room' and dining['kind'] == 'room', (kitchen, dining))
    check_room_geometry(b, kitchen, rect(0, 0, 5, 8))
    check_room_geometry(b, dining, rect(5, 0, 10, 8))
    check(set(kitchen['joints']) == {'c0', 'm0', 'm1', 'c3'}, kitchen['joints'])
    check(set(dining['joints']) == {'m0', 'c1', 'c2', 'm1'}, dining['joints'])
    # identity fields travel with the room
    check(kitchen.get('ha_area') == 'kitchen', kitchen)
    check(kitchen.get('floor_material') == OAK and kitchen.get('ceiling_material') == PLASTER, kitchen)
    # a closed house raises no unclosed flag
    check(closed_flags(b) == [], b['flags'])


def test_moving_the_split_wall_keeps_identity():
    # the joints of 'mid' move from x=5 to x=7; the cached polygons still say 5
    b, _notes, _out = run(t_box(mid_x=7, rooms=kitchen_dining(split_x=5)))
    named = rooms_by_name(b)
    check(set(named) == {'Kitchen', 'Dining'} and len(b['rooms']) == 2, b['rooms'])
    kitchen, dining = named['Kitchen'][0], named['Dining'][0]
    check(kitchen['id'] == 'kitchen' and dining['id'] == 'dining', (kitchen['id'], dining['id']))
    check(close(signed_area(kitchen['polygon']), 56.0), kitchen['polygon'])
    check(close(signed_area(dining['polygon']), 24.0), dining['polygon'])
    check(max(p[0] for p in kitchen['polygon']) == 7 and min(p[0] for p in kitchen['polygon']) == 0,
          kitchen['polygon'])   # still on the left
    check_room_geometry(b, kitchen, rect(0, 0, 7, 8))
    check_room_geometry(b, dining, rect(7, 0, 10, 8))


def test_moving_the_split_wall_after_a_normalize_keeps_identity():
    # the editor's path: a normalized house, then the joints of 'mid' are dragged to x=7
    first, _n, _o = run(t_box(rooms=kitchen_dining()))
    moved = copy.deepcopy(first)
    for j in moved['joints']:
        if j['id'] in ('m0', 'm1'):
            j['at'][0] = 7
    b, _notes, _out = run(moved)
    named = rooms_by_name(b)
    check(set(named) == {'Kitchen', 'Dining'} and len(b['rooms']) == 2, b['rooms'])
    check(named['Kitchen'][0]['id'] == 'kitchen' and named['Dining'][0]['id'] == 'dining', b['rooms'])
    check(close(signed_area(named['Kitchen'][0]['polygon']), 56.0), named['Kitchen'][0])
    check(close(signed_area(named['Dining'][0]['polygon']), 24.0), named['Dining'][0])


def test_split_room_names_the_new_part_Room():
    # one stored room 'Living' covers the whole 10x8 box; a new wall at x=6
    # splits it into 48 (left) and 32 (right); both parts claim Living fully
    stored = [room('living', 'Living', rect(0, 0, 10, 8), ha_area='living_room', floor_material=OAK)]
    b, _notes, _out = run(t_box(mid_x=6, rooms=stored))
    check(len(b['rooms']) == 2, b['rooms'])
    named = rooms_by_name(b)
    check(set(named) == {'Living', 'Room'}, list(named))
    living, new = named['Living'][0], named['Room'][0]
    check(living['id'] == 'living', living)
    check_room_geometry(b, living, rect(0, 0, 6, 8))      # the larger part keeps it
    check_room_geometry(b, new, rect(6, 0, 10, 8))
    check(isinstance(new['id'], str) and VALID_ID.fullmatch(new['id']) and new['id'] != 'living',
          new['id'])
    check(new['level'] == 'L1' and new['kind'] == 'room', new)
    check(living.get('ha_area') == 'living_room' and living.get('floor_material') == OAK, living)
    check(new.get('ha_area') in (None, ''), new)          # identity is not copied to the new part


def test_unclaimed_region_is_a_new_room_named_Room():
    # Kitchen is stored; nothing is stored on the right of the T wall
    b, _notes, _out = run(t_box(rooms=kitchen_dining()[:1]))
    named = rooms_by_name(b)
    check(set(named) == {'Kitchen', 'Room'} and len(b['rooms']) == 2, b['rooms'])
    check(named['Kitchen'][0]['id'] == 'kitchen', named['Kitchen'])
    check_room_geometry(b, named['Room'][0], rect(5, 0, 10, 8))
    check(named['Room'][0]['id'] != 'kitchen', named['Room'])


def test_a_quarter_of_the_region_is_needed_to_claim_it():
    # 'Den' is cached as a 1 ft strip (5..6) inside the right region (5..10):
    # 8 of 40 sq ft is 20%, under the 25% bar, so the right region is a new
    # 'Room' and Den, left with no region, is dropped into a flag
    stored = kitchen_dining()[:1] + [room('den', 'Den', rect(5, 0, 6, 8))]
    b, _notes, _out = run(t_box(rooms=stored))
    named = rooms_by_name(b)
    check(set(named) == {'Kitchen', 'Room'} and len(b['rooms']) == 2, b['rooms'])
    check(all(r['id'] != 'den' for r in b['rooms']), b['rooms'])
    den_flags = room_flags(b, 'Den')
    check(len(den_flags) == 1 and near(den_flags[0]['at'], [5.5, 4]), b['flags'])
    check(flag_room(den_flags[0])['id'] == 'den', den_flags)


def test_merging_keeps_the_room_that_overlaps_most():
    # Kitchen cached 0..6 (48), Dining cached 6..10 (32); no wall between them:
    # the one 80 sq ft region keeps Kitchen
    stored = [room('kitchen', 'Kitchen', rect(0, 0, 6, 8)), room('dining', 'Dining', rect(6, 0, 10, 8))]
    b, _notes, _out = run(building(box_joints(), box_walls(), stored))
    check(len(b['rooms']) == 1, b['rooms'])
    kitchen = b['rooms'][0]
    check(kitchen['id'] == 'kitchen' and kitchen['name'] == 'Kitchen', kitchen)
    check_room_geometry(b, kitchen, rect(0, 0, 10, 8))
    # ledger R8: the swallowed Dining is flagged at its cached centroid, carrying its record
    dining = room_flags(b, 'Dining')
    check(len(dining) == 1 and near(dining[0]['at'], [8, 4]) and dining[0]['level'] == 'L1', b['flags'])
    check(flag_room(dining[0])['id'] == 'dining', dining)
    check(len(closed_flags(b)) == 1, b['flags'])


def test_porch_room_bounded_by_separators_keeps_its_kind():
    # the 10x8 house plus a porch in front, x 2..8, y -4..0, closed by three
    # separators whose ends p0 (2,0) and p3 (8,0) lie on the house's bottom wall
    joints = box_joints() + [joint('p0', 2, 0), joint('p1', 2, -4), joint('p2', 8, -4), joint('p3', 8, 0)]
    walls = box_walls() + [wall('s1', 'p0', 'p1', kind='separator'),
                           wall('s2', 'p1', 'p2', kind='separator'),
                           wall('s3', 'p2', 'p3', kind='separator')]
    stored = [room('living', 'Living', rect(0, 0, 10, 8)),
              room('porch', 'Front Porch', rect(2, -4, 8, 0), kind='porch')]
    b, _notes, _out = run(building(joints, walls, stored))
    named = rooms_by_name(b)
    check(set(named) == {'Living', 'Front Porch'} and len(b['rooms']) == 2, b['rooms'])
    porch, living = named['Front Porch'][0], named['Living'][0]
    check(porch['id'] == 'porch' and porch['kind'] == 'porch', porch)
    check(living['id'] == 'living' and living['kind'] == 'room', living)
    check_room_geometry(b, porch, rect(2, -4, 8, 0))
    check(close(signed_area(living['polygon']), 80.0), living['polygon'])
    check(point_set(living['polygon']) >= point_set(rect(0, 0, 10, 8)), living['polygon'])
    check(closed_flags(b) == [], b['flags'])


def test_unclosed_room_is_flagged_never_silent():
    # Kitchen is stored over the whole box, but the right wall stops 2 ft short
    b, _notes, _out = run(gap_box([room('kitchen', 'Kitchen', rect(0, 0, 10, 8), ha_area='kitchen')]))
    check(b['rooms'] == [], b['rooms'])
    check(b['flags'] and b['flags'][0]['text'] == NOT_CLOSED, b['flags'])
    flags = closed_flags(b)
    check(len(flags) == 3, flags)            # the room's centroid, and the two ends of the gap
    check(all(f['level'] == 'L1' for f in flags), flags)
    named = room_flags(b, 'Kitchen')
    check(len(named) == 1 and near(named[0]['at'], [5, 4]), flags)
    kept = flag_room(named[0])                 # ledger R7: the whole record rides in the flag
    check(kept['id'] == 'kitchen' and kept.get('ha_area') == 'kitchen' and kept.get('level') == 'L1', kept)
    ends = [f['at'] for f in flags if f is not named[0]]
    check(sorted((round(p[0], 6), round(p[1], 6)) for p in ends) == [(10, 6), (10, 8)], ends)
    # the walls are kept as drawn; nothing is closed for the person
    check({w['id'] for w in b['walls']} == {'b', 'r', 't', 'l'}, b['walls'])


def test_open_end_flags_are_deduplicated_within_a_foot():
    # the gap box plus a dangling stub from (5,0) up to s (5,4.5); the stub's
    # free end is 0.5 ft from the dropped Kitchen's centroid (5,4), so the two
    # make one flag, and that flag still carries Kitchen's name
    b, _notes, _out = run(gap_box([room('kitchen', 'Kitchen', rect(0, 0, 10, 8))],
                                  extra_joints=[joint('s0', 5, 0), joint('s', 5, 4.5)],
                                  extra_walls=[wall('stub', 's0', 's')]))
    flags = closed_flags(b)
    check(len(flags) == 3, flags)
    middle = [f for f in flags if abs(f['at'][0] - 5) <= 1 and abs(f['at'][1] - 4.25) <= 1]
    check(len(middle) == 1, flags)
    check(len(room_flags(b, 'Kitchen')) == 1, flags)
    for i, f in enumerate(flags):
        for g in flags[i + 1:]:
            check(not near(f['at'], g['at'], 1.0), (f, g))


def test_flags_do_not_pile_up_and_other_flags_survive():
    # a second normalize re-derives the unclosed flags rather than adding to them;
    # the dropped Kitchen's flag persists (ledger R7); a flag with other words
    # (a migration note) is left alone
    migration = {'level': 'L1', 'at': [1, 1],
                 'text': 'I added an invisible wall here to keep the kitchen and the dining room apart; check it.'}
    first, _n, _o = run(gap_box([room('kitchen', 'Kitchen', rect(0, 0, 10, 8))]))
    first['flags'].append(copy.deepcopy(migration))
    b, _notes, _out = run(first)
    ends = [f['at'] for f in closed_flags(b) if flag_room(f) is None]
    check(sorted((round(p[0], 6), round(p[1], 6)) for p in ends) == [(10, 6), (10, 8)], b['flags'])
    check(len(room_flags(b, 'Kitchen')) == 1, b['flags'])
    check(len(closed_flags(b)) == 3, b['flags'])
    check(sum(1 for f in b['flags'] if f.get('text') == migration['text']) == 1, b['flags'])


def test_rooms_are_derived_per_level():
    # walls on L1 only; a stored L2 room 'Bedroom' with the same outline must not
    # claim the L1 region, and with no L2 walls it is dropped into an L2 flag
    levels = [level('L1', 0, 'Ground'), level('L2', 10, 'Upper')]
    stored = [room('bed', 'Bedroom', rect(0, 0, 10, 8), lvl='L2')]
    b, _notes, _out = run(building(box_joints(), box_walls(), stored, levels=levels))
    check(len(b['rooms']) == 1, b['rooms'])
    only = b['rooms'][0]
    check(only['level'] == 'L1' and only['name'] == 'Room' and only['id'] != 'bed', only)
    check_room_geometry(b, only, rect(0, 0, 10, 8))
    bed = room_flags(b, 'Bedroom')
    check(len(bed) == 1 and bed[0]['level'] == 'L2' and near(bed[0]['at'], [5, 4]), b['flags'])


def test_closing_the_gap_restores_the_room():
    # ledger R7: gap -> the flag carries Kitchen; a second normalize keeps it;
    # closing the right wall brings Kitchen back with its id, name and ha_area
    stored = [room('kitchen', 'Kitchen', rect(0, 0, 10, 8), ha_area='kitchen', floor_material=OAK)]
    first, _n, _o = run(gap_box(stored))
    check(first['rooms'] == [], first['rooms'])
    check(len(room_flags(first, 'Kitchen')) == 1, first['flags'])
    again, _n, _o = run(first)
    check(again['rooms'] == [], again['rooms'])
    kept = room_flags(again, 'Kitchen')
    check(len(kept) == 1 and near(kept[0]['at'], [5, 4]), again['flags'])
    check(flag_room(kept[0])['id'] == 'kitchen' and flag_room(kept[0]).get('ha_area') == 'kitchen', kept)
    closed = copy.deepcopy(again)
    for w in closed['walls']:
        if w['id'] == 'r':
            w['joints'] = ['c1', 'c2']            # the right wall now runs the full 8 ft
    closed['joints'] = [j for j in closed['joints'] if j['id'] != 'g']
    b, _notes, _out = run(closed)
    check(len(b['rooms']) == 1, b['rooms'])
    kitchen = b['rooms'][0]
    check(kitchen['id'] == 'kitchen' and kitchen['name'] == 'Kitchen', kitchen)
    check(kitchen.get('ha_area') == 'kitchen' and kitchen.get('floor_material') == OAK, kitchen)
    check_room_geometry(b, kitchen, rect(0, 0, 10, 8))
    check(closed_flags(b) == [], b['flags'])


def test_separator_thickness_is_zero():
    # ledger R9: the porch fixture's separators arrive with 0.33 and leave with 0;
    # solid walls keep theirs
    joints = box_joints() + [joint('p0', 2, 0), joint('p1', 2, -4), joint('p2', 8, -4), joint('p3', 8, 0)]
    walls = box_walls() + [wall('s1', 'p0', 'p1', kind='separator'),
                           wall('s2', 'p1', 'p2', kind='separator'),
                           wall('s3', 'p2', 'p3', kind='separator')]
    b, _notes, _out = run(building(joints, walls, []))
    seps = [w for w in b['walls'] if w.get('kind') == 'separator']
    check({w['id'] for w in seps} == {'s1', 's2', 's3'}, seps)
    check(all(w['thickness'] == 0 for w in seps), seps)
    solids = [w for w in b['walls'] if w.get('kind') != 'separator']
    check(solids and all(w['thickness'] == 0.5 for w in solids), solids)


def test_derive_works_in_place_and_returns_the_building():
    b = t_box(mid_x=7, rooms=kitchen_dining(split_x=5))
    got = twin_model.derive(b)
    check(got is b, 'derive must return the same building object')
    named = rooms_by_name(b)
    check(set(named) == {'Kitchen', 'Dining'} and len(b['rooms']) == 2, b['rooms'])
    check(named['Kitchen'][0]['id'] == 'kitchen', named)
    check(close(signed_area(named['Kitchen'][0]['polygon']), 56.0), named['Kitchen'])
    check(close(signed_area(named['Dining'][0]['polygon']), 24.0), named['Dining'])
    g = gap_box([room('kitchen', 'Kitchen', rect(0, 0, 10, 8))])
    twin_model.derive(g)
    check(g['rooms'] == [] and len(closed_flags(g)) == 3, g)


def test_caps_and_bad_hosts_are_refused_with_notes():
    # a plain box; door-ok sits on the bottom wall, door-lost names a wall that does not exist
    b = building(box_joints(), box_walls(), [room('living', 'Living', rect(0, 0, 10, 8))])
    b['openings'] = [
        {'id': 'door-ok', 'wall': 'b', 'at': 5, 'width': 3, 'sill': 0, 'head': 7, 'kind': 'door'},
        {'id': 'door-lost', 'wall': 'nope', 'at': 5, 'width': 3, 'sill': 0, 'head': 7, 'kind': 'door'},
    ]
    out, notes, _o = run(b)
    openings = {o['id']: o for o in out['openings']}
    check(set(openings) == {'door-ok', 'door-lost'}, out['openings'])
    check(openings['door-lost'].get('state') == 'ghost', openings['door-lost'])
    check(openings['door-lost']['wall'] == 'nope' and openings['door-lost']['at'] == 5,
          openings['door-lost'])
    check(openings['door-ok'].get('state', 'settled') == 'settled', openings['door-ok'])
    check(any('door-lost' in n for n in notes), notes)
    check(not any('door-ok' in n for n in notes), notes)

    # 401 walls in a straight chain of 402 joints: the first 400 are kept
    joints = [joint(f'k{i}', i * 2, 0) for i in range(402)]
    walls = [wall(f'w{i}', f'k{i}', f'k{i + 1}') for i in range(401)]
    out, notes, _o = run(building(joints, walls, []))
    check(len(out['walls']) == 400, len(out['walls']))
    check(any('walls' in n and '400' in n for n in notes), notes)


def test_every_list_is_capped_with_a_note():
    def capped(name, cap, out, notes):
        check(len(out[name]) <= cap, (name, len(out[name])))
        check(any(name in n and str(cap) in n for n in notes), (name, notes))

    # joints: 801, no walls
    out, notes, _o = run(building([joint(f'k{i}', i, 0) for i in range(801)], [], []))
    capped('joints', 800, out, notes)

    # openings: 401 doors along one 4020 ft wall
    b = building([joint('a', 0, 0), joint('z', 4020, 0)], [wall('long', 'a', 'z')], [])
    b['openings'] = [{'id': f'o{i}', 'wall': 'long', 'at': 5 + 10 * i, 'width': 3,
                      'sill': 0, 'head': 7, 'kind': 'door'} for i in range(401)]
    out, notes, _o = run(b)
    check(len(out['openings']) == 400, len(out['openings']))
    capped('openings', 400, out, notes)

    # rooms: a strip of 121 one-foot cells, so 121 regions
    joints = ([joint(f'b{i}', i, 0) for i in range(122)]
              + [joint(f't{i}', i, 1) for i in range(122)])
    walls = ([wall(f'bw{i}', f'b{i}', f'b{i + 1}') for i in range(121)]
             + [wall(f'tw{i}', f't{i + 1}', f't{i}') for i in range(121)]
             + [wall(f'v{i}', f'b{i}', f't{i}') for i in range(122)])
    out, notes, _o = run(building(joints, walls, []))
    check(len(out['rooms']) == 120, len(out['rooms']))
    capped('rooms', 120, out, notes)

    # roofs: 41 square hips
    b = building(box_joints(), box_walls(), [])
    b['roofs'] = [{'id': f'roof{i}', 'area': rect(i * 20, 0, i * 20 + 10, 10),
                   'edges': [{'setting': 'sloped', 'pitch': 6} for _ in range(4)],
                   'plate': 9, 'overhang': 1} for i in range(41)]
    out, notes, _o = run(b)
    check(len(out['roofs']) == 40, len(out['roofs']))
    capped('roofs', 40, out, notes)

    # anchors: 401 on the ground
    b = building(box_joints(), box_walls(), [])
    b['anchors'] = [{'id': f'a{i}', 'kind': 'camera', 'host': {'ground': True, 'at': [i, 20]},
                     'offset': 0, 'device': None} for i in range(401)]
    out, notes, _o = run(b)
    check(len(out['anchors']) == 400, len(out['anchors']))
    capped('anchors', 400, out, notes)

    # items: 601 on the ground
    b = building(box_joints(), box_walls(), [])
    b['items'] = [{'id': f'i{i}', 'asset': 'planter', 'host': {'ground': True, 'at': [i, 30]},
                   'rotation': 0, 'scale': 1} for i in range(601)]
    out, notes, _o = run(b)
    check(len(out['items']) == 600, len(out['items']))
    capped('items', 600, out, notes)


TESTS = (
    test_schema_is_3_and_site_passes_through,
    test_rooms_are_derived_and_keep_names,
    test_moving_the_split_wall_keeps_identity,
    test_moving_the_split_wall_after_a_normalize_keeps_identity,
    test_split_room_names_the_new_part_Room,
    test_unclaimed_region_is_a_new_room_named_Room,
    test_a_quarter_of_the_region_is_needed_to_claim_it,
    test_merging_keeps_the_room_that_overlaps_most,
    test_porch_room_bounded_by_separators_keeps_its_kind,
    test_unclosed_room_is_flagged_never_silent,
    test_open_end_flags_are_deduplicated_within_a_foot,
    test_flags_do_not_pile_up_and_other_flags_survive,
    test_rooms_are_derived_per_level,
    test_closing_the_gap_restores_the_room,
    test_separator_thickness_is_zero,
    test_derive_works_in_place_and_returns_the_building,
    test_caps_and_bad_hosts_are_refused_with_notes,
    test_every_list_is_capped_with_a_note,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
