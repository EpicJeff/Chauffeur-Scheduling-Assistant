"""Replay the household's recorded whole-building reads through a real build
(plan docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md,
Task 11 step 2; spec docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md
sections 4 and 8; .superpowers/sdd/2026-11-08-house-editor-whole-building-draft/task-11-fixes.md).

Each building runs through twin_build.start({'part': ...}, inline=True) with a
stub reader keyed by kind: 'draft' and 'draft_rooms' answer the fragments
recorded once from the household's own drawings (Claude, the product prompt),
'outline' answers an error (the quick first look is disposable), 'finishes'
answers a minimal empty materials answer. Sources are blank PDFs.

Spec section 8 tolerances, checked on the settled plan:
- Pool house: L1 31 x 22 within 0.25 ft; L2 placed at x 5.67..25.33 within
  0.25 ft; L2 is the half storey the read says it is, and it settles.
- Main house: L1 70 wide within 0.5 ft. Depth: the hand key's 66.3 ft is the
  outline INCLUDING the rear screened porch (spike check script: centre probe
  rear 66.31), and the spec rules a screened porch is a porch, so the outline
  (enclosed walls only) is checked against the 65'-4" overall string (65.33)
  and the footprint with its porches against 66.3, both within 0.5 ft.
- Main house: each wing's front y within 0.5 ft, probed on the L1 outline at
  the spike check script's x probes; every recorded roof section settles; the
  centre front gable is present (the check script's 6a test); at least 90% of
  the upper floor's exterior walls settle (upper walls closed).
- Rooms gate (spec section 4, controller's call): every room has a name (the
  recorded names are blank, so this checks the parse: blank becomes "Room");
  room polygons overlap by less than 1 sq ft; on every level with rooms they
  cover at least 85% of the level's outline; every room settles unless its
  polygon lies more than 0.5 ft outside its level's outline.

twin_joints.report after the build must be empty for both buildings.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_draft_replay.py
"""
import copy
import io
import json
import math
import os
import sys
import tempfile
import traceback

# Always a scratch data dir (the engine harness wipes its data dir); keep one
# an importing test module already made.
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_draft_replay_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_joints  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _accept_all, _pdf, check  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
OUTSIDE_WHY = "This room extends outside its floor's outline."
# x probe -> recorded front y of each main-house wing (the spike check script's probes).
WING_FRONTS = {'left wing': (7.0, 14.33), 'centre': (25.0, 13.33),
               'right wing': (48.0, 0.0), 'side bump': (64.5, 22.0)}
EPS = 1e-6


# --- fixtures, reader and build ----------------------------------------------

def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


class ReplayReader(Reader):
    """Answers the recorded fragments by kind; the first look fails."""

    def __init__(self, draft, rooms):
        super().__init__()
        self.draft, self.rooms = draft, rooms
        self.kinds = []

    def __call__(self, kind, images, context, *, run, step):
        self.kinds.append(kind)
        if kind in ('draft', 'draft_level'):
            return copy.deepcopy(self.draft)
        if kind == 'draft_rooms':
            return copy.deepcopy(self.rooms)
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}
        if kind == 'finishes':
            return {'materials': {}}
        if kind == 'photo_map':
            return {'from_side': 'front', 'blocks': [{'id': b['id'], 'sides': ['front']} for b in context['blocks']]}
        if kind == 'roof_observe':
            # Recorded photos have no new recorded observation yet: explicit hidden
            # sides exercise the plan-evidence fallback without a failed read.
            return {'blocks': {b['id']: {'sides': {side: {'kind': 'hidden'}
                              for side in ('front', 'rear', 'left', 'right')}} for b in context['blocks']}}

        return super().__call__(kind, images, context, run=run, step=step)


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (90, 120, 160)).save(buf, format='JPEG')
    return buf.getvalue()


_BUILT = {}


def build(slug):
    """Build one recorded building in a fresh place; cached per slug.
    Returns {'house', 'status', 'kinds', 'report'}."""
    if slug in _BUILT:
        return copy.deepcopy(_BUILT[slug])
    draft = recorded(f'draft-{slug}.json')
    rooms = recorded(f'draft_rooms-{slug}.json')
    engine_tests._fresh()
    if slug == 'main-house':
        source = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
        bid = 'house'
    else:
        bid = ts.add_building('Pool house', 'pool_house')['id']
        source = ts.save_source('drawing', 'pool.pdf', _pdf(3), part=bid)
    names = [l['name'] for l in sorted(draft['building']['levels'], key=lambda l: l['elevation'])]
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': names[0], 'box': None, 'building': bid},
        {'source': source, 'page': 2, 'role': 'floor', 'level': names[1], 'box': None, 'building': bid},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': bid}])
    ts.save_source('photo', f'{bid}.jpg', _jpeg(), part=bid)
    reader = ReplayReader(draft, rooms)
    b = tb.start({'part': bid}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (slug, 'the replay build finishes', st['state'], st.get('pause'),
                                  [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    check(reader.kinds.count('draft') == 1 and reader.kinds.count('draft_rooms') == 1,
          (slug, 'one draft read and one rooms read', reader.kinds))
    house = next(h for h in ts.current()['buildings'] if h['id'] == bid)
    _BUILT[slug] = {'house': house, 'status': st, 'kinds': reader.kinds,
                    'report': twin_joints.report(copy.deepcopy(house))}
    return copy.deepcopy(_BUILT[slug])


# --- geometry -----------------------------------------------------------------

def _level(house, lid):
    return next(l for l in house['levels'] if l['id'] == lid)


def _bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _span_at_x(poly, x):
    """The outline's min and max y where the vertical line at x crosses it."""
    ys = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[0] - x) * (b[0] - x) < 0:
            ys.append(a[1] + (x - a[0]) / (b[0] - a[0]) * (b[1] - a[1]))
    return (min(ys), max(ys)) if ys else None


def _span_at_y(poly, y):
    xs = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] - y) * (b[1] - y) < 0:
            xs.append(a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0]))
    return (min(xs), max(xs)) if xs else None


def _row(poly, y):
    """Exact x intervals of a polygon on the horizontal line y (even-odd)."""
    xs = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                for a, b in zip(poly, poly[1:] + poly[:1]) if (a[1] > y) != (b[1] > y))
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def _covered(rows, need):
    """Length of x covered by at least `need` of the interval lists."""
    events = sorted((x, d) for intervals in rows for lo, hi in intervals for x, d in ((lo, 1), (hi, -1)))
    total, depth, last = 0.0, 0, None
    for x, d in events:
        if depth >= need and last is not None:
            total += x - last
        depth += d
        last = x
    return total


def _clip(intervals, within):
    return [(max(a, c), min(b, d)) for a, b in intervals for c, d in within if min(b, d) > max(a, c)]


def room_areas(polygons, outline, step=0.02):
    """(outline area, area of the outline the rooms cover, area covered by two
    or more rooms), in sq ft, by exact scanlines every `step` ft."""
    y0, y1 = min(p[1] for p in outline), max(p[1] for p in outline)
    for poly in polygons:
        y0, y1 = min(y0, *(p[1] for p in poly)), max(y1, *(p[1] for p in poly))
    n = max(1, math.ceil((y1 - y0) / step))
    h = (y1 - y0) / n
    area = cover = overlap = 0.0
    for i in range(n):
        y = y0 + (i + .5) * h + 1.234e-7     # off every vertex
        out = _row(outline, y)
        rows = [_row(poly, y) for poly in polygons]
        area += sum(b - a for a, b in out) * h
        cover += _covered([_clip(r, out) for r in rows], 1) * h
        overlap += _covered(rows, 2) * h
    return area, cover, overlap


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0 if length == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _inside(p, poly):
    c = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            c = not c
    return c


def outside_by(points, outline, closed=True):
    """How far (ft) the boundary of `points` reaches outside `outline`, sampled
    every 0.25 ft along its edges."""
    pairs = list(zip(points, points[1:] + points[:1])) if closed else list(zip(points, points[1:]))
    samples = [points[-1]] if not closed else []
    for a, b in pairs:
        n = max(1, math.ceil(math.dist(a, b) / .25))
        samples.extend([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n] for k in range(n))
    edges = list(zip(outline, outline[1:] + outline[:1]))
    return max([min(_seg_dist(p, a, b) for a, b in edges) for p in samples if not _inside(p, outline)] or [0.0])


def _rooms(house):
    return [r for r in house['rooms'] if (r.get('src') or {}).get('step') == 'draft_rooms']


# --- shared checks -------------------------------------------------------------

def _gate_rooms(slug):
    house = build(slug)['house']
    rooms = _rooms(house)
    check(rooms, (slug, 'the rooms read settles rooms into the plan', len(house['rooms'])))
    return house, rooms


def rooms_named(slug):
    house, rooms = _gate_rooms(slug)
    unnamed = [r['polygon'] for r in rooms if not (isinstance(r.get('name'), str) and r['name'].strip())]
    check(not unnamed, (slug, 'every room has a name (a blank printed name becomes "Room")',
                        len(unnamed), 'of', len(rooms), [r.get('name') for r in rooms]))


def rooms_cover_without_overlap(slug):
    house, rooms = _gate_rooms(slug)
    for level in house['levels']:
        polygons = [r['polygon'] for r in rooms if r['level'] == level['id']]
        if not polygons:
            continue
        area, cover, overlap = room_areas(polygons, level['outline'])
        check(overlap < 1, (slug, level['id'], 'room polygons overlap by less than 1 sq ft', round(overlap, 2)))
        check(cover >= .85 * area, (slug, level['id'], 'rooms cover at least 85% of the outline',
                                    round(cover, 1), round(area, 1)))


def rooms_settle(slug):
    house, rooms = _gate_rooms(slug)
    wrong = []
    for room in rooms:
        reach = outside_by(room['polygon'], _level(house, room['level'])['outline'])
        expect_ghost = reach > .5 + EPS
        if expect_ghost != (room.get('state') == 'ghost'):
            wrong.append((room['level'], room.get('name'), room.get('state'), room.get('why'),
                          round(reach, 3), room['polygon']))
    check(not wrong, (slug, 'every room settles unless it lies more than 0.5 ft outside its outline',
                      f'{len(wrong)} of {len(rooms)} wrong', wrong[:4]))


# --- pool house ------------------------------------------------------------------

def test_pool_house_first_floor_31_by_22():
    house = build('pool-house')['house']
    box = _bounds(_level(house, 'L1')['outline'])
    size = [box[2] - box[0], box[3] - box[1]]
    check(abs(size[0] - 31) <= .25 + EPS and abs(size[1] - 22) <= .25 + EPS,
          ('pool house L1 is 31 x 22 within 0.25 ft', size))


def test_pool_house_upper_floor_offset():
    draft = recorded('draft-pool-house.json')
    house = build('pool-house')['house']
    l2 = _level(house, 'L2')
    # The loft runs x 5.67..25.33 at the front; its stair alcove reaches x 0
    # only at the rear left, so probe across the middle of its depth.
    span = _span_at_y(l2['outline'], 11.0)
    check(span and abs(span[0] - 5.67) <= .25 + EPS and abs(span[1] - 25.33) <= .25 + EPS,
          ('pool house L2 sits at x 5.67..25.33 within 0.25 ft', span))
    recorded_half = bool(next(l for l in draft['building']['levels'] if l['id'] == 'L2').get('half'))
    check(recorded_half, 'test setup: the recorded pool-house L2 is a half storey')
    check(l2.get('half') is True, ('the half storey stays a half storey', {k: l2.get(k) for k in ('id', 'half')}))


def test_pool_house_half_storey_settles():
    # Spec section 3: a half storey's walls are knee walls (exterior: false);
    # it still gets a floor and a floor button like any other level.
    house = build('pool-house')['house']
    l2 = _level(house, 'L2')
    check(l2.get('state') != 'ghost', ('the pool-house half storey settles', l2.get('state'), l2.get('why')))


def test_pool_house_room_names():
    rooms_named('pool-house')


def test_pool_house_rooms_cover_without_overlap():
    rooms_cover_without_overlap('pool-house')


def test_pool_house_rooms_settle():
    rooms_settle('pool-house')


# --- main house ------------------------------------------------------------------

def test_main_house_first_floor_size():
    house = build('main-house')['house']
    box = _bounds(_level(house, 'L1')['outline'])
    size = [box[2] - box[0], box[3] - box[1]]
    check(abs(size[0] - 70) <= .5 + EPS, ('main house L1 is 70 ft wide within 0.5 ft', size))
    check(abs(size[1] - 65.33) <= .5 + EPS,
          ('main house L1 enclosed outline is 65.33 deep (the 65\'-4" overall string) within 0.5 ft', size))
    footprint = list(_level(house, 'L1')['outline'])
    for porch in twin_plan.porches(house):
        footprint.extend(porch.get('polygon') or [])
    box = _bounds(footprint)
    size = [box[2] - box[0], box[3] - box[1]]
    check(abs(size[0] - 70) <= .5 + EPS and abs(size[1] - 66.3) <= .5 + EPS,
          ('main house footprint with its porches is 70 x 66.3 (the hand key) within 0.5 ft', size))


def test_main_house_wing_fronts():
    house = build('main-house')['house']
    outline = _level(house, 'L1')['outline']
    got = {}
    for name, (x, front) in WING_FRONTS.items():
        span = _span_at_x(outline, x)
        got[name] = None if span is None else round(span[0], 3)
        check(span is not None and abs(span[0] - front) <= .5 + EPS,
              (f'the {name} front (x {x}) is at y {front} within 0.5 ft', got))


def test_main_house_roof_sections_settle():
    draft = recorded('draft-main-house.json')
    house = build('main-house')['house']
    sections = house['roof']['sections']
    check(len(draft['building']['roof']['sections']) == 10, ('test setup: ten recorded roof sections',
                                                              len(draft['building']['roof']['sections'])))
    # Ruling R14: the roof now comes from the blocks of the settled walls. Every block
    # gets exactly one settled roof, and nothing on the roof is a ghost.
    from services import twin_blocks
    blocks = twin_blocks.blocks(house)
    derived = [s for s in sections if (s.get('src') or {}).get('step') == 'roof_blocks']
    bad = [(b['rect'], [(s['rect'], s.get('state')) for s in derived
                        if all(abs(a - c) <= 1 for a, c in zip(s['rect'], b['rect']))]) for b in blocks]
    bad = [row for row in bad if len(row[1]) != 1 or row[1][0][1] == 'ghost']
    check(blocks and not bad, ('one settled block roof over every block', bad))
    ghosts = [(s['rect'], s.get('why')) for s in sections if s.get('state') == 'ghost']
    check(not ghosts, ('every roof section settles', ghosts))
    # The centre two-storey block has its roof at the upper plate.
    centre = [s for s in derived if s.get('state') != 'ghost' and s['plate'] >= 15
              and s['rect'][0] >= 13 and s['rect'][2] <= 38.5]
    check(centre, ('the centre two-storey block is roofed at the upper plate',
                   [(s['kind'], s.get('ridge'), s['rect'], s['plate']) for s in derived]))
    check(any(s.get('state') != 'ghost' and s['kind'] == 'gable' and s.get('ridge') == 'y'
              and s['plate'] >= 15 and s['rect'][0] >= 13 and s['rect'][2] <= 38.5
              and s['rect'][1] <= 16 for s in sections),
          ('the centre front gable from the drawings settles', sections))


def test_main_house_upper_walls_close():
    house = build('main-house')['house']
    walls = [w for w in house['walls'] if w['level'] == 'L2' and w.get('exterior')
             and (w.get('src') or {}).get('step') == 'draft']
    settled = [w for w in walls if w.get('state') != 'ghost']
    check(len(walls) >= 10, ('test setup: the upper floor has its exterior walls', len(walls)))
    need = math.ceil(.9 * len(walls))
    check(len(settled) >= need,
          ('at least 90% of the upper floor\'s exterior walls settle', f'{len(settled)} of {len(walls)}, need {need}',
           [(w['from'], w['to'], w.get('why')) for w in walls if w.get('state') == 'ghost']))


def test_main_house_front_jog_survives_snap():
    # Beyond the brief (found writing this test): spec section 2, "Exterior
    # walls follow the outline exactly, with shared endpoints". The recorded
    # 1 ft front jog at x 22.67 (y 14.33 to 13.33, on L1 and L2) must not be
    # welded away by the 1 ft corner weld, leaving the front walls 0.5 ft off
    # the outline on both sides of it.
    house = build('main-house')['house']
    for lid in ('L1', 'L2'):
        outline = _level(house, lid)['outline']
        walls = [w for w in house['walls'] if w['level'] == lid and w.get('exterior')
                 and w.get('state') != 'ghost' and (w.get('src') or {}).get('step') == 'draft']
        jog = [w for w in walls if {(round(w['from'][0], 1), round(w['from'][1], 1)),
                                    (round(w['to'][0], 1), round(w['to'][1], 1))} == {(22.7, 14.3), (22.7, 13.3)}]
        check(jog, (lid, 'the 1 ft front jog wall at x 22.67 survives the snap',
                    sorted((tuple(w['from']), tuple(w['to'])) for w in walls if min(w['from'][1], w['to'][1]) < 16)))
        off = [(w['from'], w['to'], round(max(outside_by([w['from'], w['to']], outline, closed=False),
                                               min(_seg_dist(p, a, b) for p in (w['from'], w['to'])
                                                   for a, b in zip(outline, outline[1:] + outline[:1]))), 3))
               for w in walls]
        off = [o for o in off if o[2] > .1 + EPS]
        check(not off, (lid, 'every settled exterior wall end lies on the outline within 0.1 ft', off[:4]))


def test_main_house_photo_reads_replace_roof_check():
    built = build('main-house')
    reads = [k for k in built['kinds'] if k in ('draft', 'draft_level', 'photo_map', 'roof_observe', 'roof_check', 'draft_rooms')]
    check(reads == ['draft', 'photo_map', 'roof_observe', 'draft_rooms'], ('photo reads precede rooms', built['kinds']))
    house = built['house']
    from services import twin_blocks
    blocks = twin_blocks.blocks(house)
    sections = house['roof']['sections']
    for block in blocks:
        found = [s for s in sections if all(abs(a - b) < 1 for a, b in zip(
            s.get('read_geometry', {}).get('rect', s['rect']), block['rect']))]
        check(len(found) == 1 and found[0]['kind'] == 'gable', ('block form from hidden photos', block, found))
    for section in recorded('draft-main-house.json')['building']['roof']['sections']:
        if section['id'] not in {'r_porch_shed', 'r_porch_gable', 'r_screen'}:
            continue
        found = [s for s in sections if tuple(s.get('read_geometry', {}).get('rect', s['rect'])) == tuple(section['rect'])]
        check(len(found) == 1 and (found[0]['kind'], found[0].get('ridge'), found[0].get('low_side'))
              == (section['kind'], section.get('ridge'), section.get('low_side')), (section, found))
    check(not any(e.get('text') == 'The roofs could not be checked against the photos; they follow the drawings.'
                  for e in built['status']['events']), 'a usable observation is not reported as failed')


def test_main_house_room_names():
    rooms_named('main-house')


def test_main_house_rooms_cover_without_overlap():
    rooms_cover_without_overlap('main-house')


def test_main_house_rooms_settle():
    rooms_settle('main-house')


def test_both_buildings_have_no_joint_report():
    for slug in ('pool-house', 'main-house'):
        check(not build(slug)['report'], (slug, build(slug)['report']))


TESTS = (
    test_both_buildings_have_no_joint_report,
    test_pool_house_first_floor_31_by_22,
    test_pool_house_upper_floor_offset,
    test_pool_house_half_storey_settles,
    test_pool_house_room_names,
    test_pool_house_rooms_cover_without_overlap,
    test_pool_house_rooms_settle,
    test_main_house_first_floor_size,
    test_main_house_wing_fronts,
    test_main_house_roof_sections_settle,
    test_main_house_upper_walls_close,
    test_main_house_front_jog_survives_snap,
    test_main_house_photo_reads_replace_roof_check,
    test_main_house_room_names,
    test_main_house_rooms_cover_without_overlap,
    test_main_house_rooms_settle,
)


def print_joint_reports():
    for slug in ('pool-house', 'main-house'):
        try:
            lines = build(slug)['report']
        except Exception as exc:
            print(f'  joints {slug}: no build ({type(exc).__name__})')
            continue
        print(f'  joints {slug}: {len(lines)} line(s)')
        for line in lines:
            print(f'    - {line}')


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
        else:
            print('  ok  ', fn.__name__)
    print_joint_reports()
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
