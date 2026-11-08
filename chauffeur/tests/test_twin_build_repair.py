"""Repair round after the first live build of Your place (brief
.superpowers/sdd/2026-11-07-house-editor-slice-1b-i/repair-brief.md, R1-R5,
engine half). Written before the repair, as its contract.

- R1 every floor gets one walls read of the whole floor crop, and each named
  wing its own zoomed read as well; the whole-floor read comes first so the
  wings can lean on it. A wall two reads return settles once, and no two
  walls of a floor ever lie on top of each other. Wing step ids stay
  walls:<level>:<wing>.
- R2 an upper floor's registration, or the roof, whose fitted shape differs
  from the floor it is fitted to by more than 10% in area or 2 ft across says
  so in plain words at a pause ("... do not match ..."), even when the fit's
  rms is low. Equal shapes settle as they do now.
- R3 a building built where there is no lot placement lands beside the
  buildings already there (10 ft right of the rightmost one, y 0, unturned).
- R4 a part build's finishes read is told the kit's roles and allowed asset
  ids; a role answered with an id outside the kit takes the kit default.
- R5b pieces normalize leaves out are named once per step in plain words.

The reader is a stub keyed by step id (then by kind and level, then kind); it
answers in the real contracts' shapes, several taken from the recorded reads
of the reproduction (the pool house outline with its porch wing, the upper
floor with its stair wing, the porch walls drawn in three pieces, the
finishes answer). Sources are blank 17 x 11 inch PDFs (5100 x 3300 px
masters); 70 ft = 0.5 of the page width unless a recorded dimension says
otherwise.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_repair.py
"""
import copy
import json
import math
import os
import re
import sys
import tempfile
import traceback

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_repair_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_library  # noqa: E402
from services import twin_register as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import DEPTH_V, DIM, L1, _accept_all, _jpeg, _pdf, check  # noqa: E402

W, H = 5100, 3300
PX_PER_FT = 2550 / 70          # DIM: 70 ft over half the page width
U, V = PX_PER_FT / W, PX_PER_FT / H     # crop u and v per foot on a full page
FULL = [0, 0, 1, 1]
MISMATCH = 'do not match'
RAW_ID = re.compile(r'(wall|opening|room|roof|site|level)[:-][0-9a-f]{6,}')
KIT = twin_library.kit('modern_farmhouse')

# The pool house as the reproduction read it (reads 01 and 06): the enclosed
# rooms with the open porch named as a wing; the upper floor with its stair.
POOL_OUTLINE = {'dimension': {'a': [0.298, 0.516], 'b': [0.694, 0.516], 'feet': 38.0},
                'outline': [[0.298, 0.122], [0.62, 0.122], [0.62, 0.43], [0.298, 0.43]],
                'wings': [{'name': 'porch', 'box': [0.62, 0.122, 0.694, 0.43]}], 'confidence': 0.7,
                'why': 'Enclosed 31x22 rectangle plus 7 ft covered porch on right; outline traced as '
                       'enclosed walls, porch given as wing.'}
POOL_UPPER = [[0.2671, 0.1225], [0.5313, 0.1225], [0.5313, 0.4297], [0.3262, 0.4297], [0.3262, 0.1875],
              [0.2671, 0.1875]]
POOL_REGISTRATION = {'dimension': {'a': [0.2671, 0.0518], 'b': [0.6631, 0.0518], 'feet': 38.0},
                     'lower_outline': [[0.2671, 0.1225], [0.6631, 0.1225], [0.6631, 0.4297], [0.2671, 0.4297]],
                     'outline': POOL_UPPER,
                     'wings': [{'name': 'stair', 'box': [0.2671, 0.1225, 0.3262, 0.1875]}], 'confidence': 0.7,
                     'why': 'Upper floor is a 19\'-8" wide exercise room plus a stair strip along the north wall.'}
# Read 02: the porch crop sees only the house's right wall, in three pieces.
POOL_PORCH_WALLS = {'walls': [{'from': [0.01, 0.0], 'to': [0.01, 0.29], 'exterior': True, 'thickness_in': 6},
                              {'from': [0.01, 0.29], 'to': [0.01, 0.6], 'exterior': True, 'thickness_in': 6},
                              {'from': [0.01, 0.6], 'to': [0.01, 1.0], 'exterior': True, 'thickness_in': 6}],
                    'confidence': 0.55, 'why': 'The only wall drawn in the crop is the thick vertical line.'}
# Read 07: the stair crop's perimeter and two thin partitions.
POOL_STAIR_WALLS = {'walls': [{'from': [0.055, 0.105], 'to': [1.0, 0.105], 'exterior': True, 'thickness_in': 6},
                              {'from': [0.055, 0.105], 'to': [0.055, 0.915], 'exterior': True, 'thickness_in': 6},
                              {'from': [0.055, 0.915], 'to': [1.0, 0.915], 'exterior': True, 'thickness_in': 6},
                              {'from': [0.763, 0.105], 'to': [0.763, 0.915], 'exterior': False, 'thickness_in': 4},
                              {'from': [0.902, 0.105], 'to': [0.902, 0.915], 'exterior': False, 'thickness_in': 4}],
                    'confidence': 0.55, 'why': 'Heavy perimeter lines read as exterior walls.'}
# Read 12: the pool house finishes, roles and ids the model guessed.
POOL_FINISHES = {'materials': {'wall': {'id': 'board_and_batten', 'color': '#c9ccc4'},
                               'trim': {'id': 'painted_wood', 'color': '#f2f2ee'},
                               'roof': {'id': 'asphalt_shingle', 'color': '#4a3a33'},
                               'window_frame': {'id': 'vinyl', 'color': '#f4f4f2'},
                               'awning': {'id': 'standing_seam_metal', 'color': '#3e2f2a'},
                               'soffit': {'id': 'painted_wood', 'color': '#f2f2ee'}}}

DEFAULTS = {'openings': {'openings': []}, 'rooms': {'rooms': []}, 'walls': {'walls': []},
            'draft_rooms': {'rooms': [], 'walls': []},
            'pitch': {'pitches': []}, 'finishes': {'materials': {}}}


# --- the stub reader and page geometry -----------------------------------------

def rect(u0, v0, w_ft, h_ft):
    """A rectangle on a full page at the 70 ft scale, traced like the reads."""
    return [[u0, v0], [u0 + w_ft * U, v0], [u0 + w_ft * U, v0 + h_ft * V], [u0, v0 + h_ft * V]]


def edges(poly):
    return list(zip(poly, poly[1:] + poly[:1]))


def to_crop(box, p):
    return [(p[0] - box[0]) / (box[2] - box[0]), (p[1] - box[1]) / (box[3] - box[1])]


def page_walls(segments):
    """A walls answer drawn in page uv, sent in whatever crop the step reads."""
    def answer(context):
        box = context['box']
        return {'walls': [{'from': to_crop(box, a), 'to': to_crop(box, b), 'exterior': ext}
                          for a, b, ext in segments], 'confidence': 0.8, 'why': ''}
    return answer


class StepReader:
    """Stands in for twin_reads.read: an answer per step id, else per
    (kind, level), else per kind, else an empty answer of the right shape.
    Callables receive the step's context and answer in its crop."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, kind, images, context, *, run, step):
        self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
        if kind == 'draft':
            # Part-only finishes and placement tests use the same footprint in
            # feet; crop regressions below explicitly exercise the legacy body.
            return engine_tests.draft_answer(self.answers.get('outline', {}).get('outline', L1))
        answer = self.answers.get(step)
        if answer is None:
            answer = self.answers.get((kind, context.get('level')))
        if answer is None:
            answer = self.answers.get(kind)
        if answer is None:
            answer = DEFAULTS.get(kind) or engine_tests.fixture(kind)
        if callable(answer):
            answer = answer(context)
        return copy.deepcopy(answer)


def _outline(poly, wings=(), dim=DIM):
    return {'dimension': dim, 'outline': poly, 'wings': list(wings), 'confidence': 0.8, 'why': ''}


def _registration(lower, upper, wings=(), why='the stamp covers a corner'):
    return {'dimension': DIM, 'lower_outline': lower, 'outline': upper, 'wings': list(wings),
            'confidence': 0.7, 'why': why}


def _place(floors=('Main floor',), roof=False, photo=False, building='house', name=None, kind=None):
    """One building's drawings (one page per floor, then the roof) and an
    optional photo tagged to it. Rows already saved for other buildings stay."""
    if building == 'house':
        engine_tests._fresh()
        sheet = ts.save_source('drawing', 'house.pdf', _pdf(len(floors) + (1 if roof else 0)))
    else:
        building = ts.add_building(name, kind)['id']
        sheet = ts.save_source('drawing', f'{building}.pdf', _pdf(len(floors) + (1 if roof else 0)), part=building)
    rows = [r for r in ts.page_roles() if r['source'] != sheet]
    rows += [{'source': sheet, 'page': i + 1, 'role': 'floor', 'level': level, 'box': None, 'building': building}
             for i, level in enumerate(floors)]
    if roof:
        rows.append({'source': sheet, 'page': len(floors) + 1, 'role': 'roof', 'level': None, 'box': None,
                     'building': building})
    ts.set_page_roles(rows)
    if photo:
        ts.save_source('photo', f'{building}.jpg', _jpeg(), part=building)
    return building, sheet


def _legacy_inputs(part='house'):
    building = next(b for b in ts.place()['buildings'] if b['id'] == part)
    return {'building': {k: building[k] for k in ('id', 'name', 'kind')}, 'photos': ts.photos_for(part)}


def _build(part, reader, *, legacy=False):
    b = tb.start(_legacy_inputs(part) if legacy else {'part': part}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'),
                                  [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    return b, st


def _building(bid):
    return next(b for b in ts.current()['buildings'] if b['id'] == bid)


def _world(sheet, page, level, p):
    return tr.apply(ts.registration(sheet, page, level), [p[0] * W, p[1] * H])


def _near(a, b, tol=1.0):
    return math.dist(a, b) <= tol


def _same_wall(wall, a, b, tol=1.0):
    return ((_near(wall['from'], a, tol) and _near(wall['to'], b, tol))
            or (_near(wall['from'], b, tol) and _near(wall['to'], a, tol)))


def _point_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2)) if length2 else 0
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _overlaps(walls, tol=1.0):
    """Pairs of walls on one floor where the shorter lies along the longer:
    the same real wall drawn twice."""
    found = []
    for i, a in enumerate(walls):
        for b in walls[i + 1:]:
            if a['level'] != b['level']:
                continue
            short, long_ = sorted((a, b), key=lambda w: math.dist(w['from'], w['to']))
            if math.dist(short['from'], short['to']) <= tol:
                continue
            if all(_point_segment(short[k], long_['from'], long_['to']) <= tol for k in ('from', 'to')):
                found.append((a['id'], b['id']))
    return found


def _walls_steps(st, level):
    return [s for s in st['steps'] if s['kind'] == 'walls' and s['level'] == level]


def _whole_floor(st, level, floor_box=FULL):
    whole = [s for s in _walls_steps(st, level) if s['box'] == floor_box]
    check(len(whole) == 1, (f'one walls read of the whole {level} crop', [(s['id'], s['box']) for s in _walls_steps(st, level)]))
    return whole[0]


def _logs(st, step_id):
    return [e['text'] for e in st['events'] if e['type'] == 'log' and e.get('step') == step_id]


def _bounds(points):
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def _world_bounds(building):
    return _bounds([tr.to_world(building, p) for level in building['levels'] for p in level.get('outline', [])])


# --- R1 walls of the whole floor and each wing --------------------------------

PORCH = [0.62, 0.1, 0.7, 0.4]
GARAGE = [0.55, 0.5, 0.7, 0.1 + DEPTH_V]
PARTITION = ([0.55, 0.5], [0.7, 0.5])           # inside the garage crop: both reads see it
GARAGE_LEFT = ([0.55, 0.5], [0.55, 0.1 + DEPTH_V])
PORCH_WALLS = [([0.62, 0.1], [0.62, 0.4]), ([0.62, 0.4], [0.7, 0.4])]


def _r1_reader():
    jitter = 0.3 * V                             # the zoomed read lands 0.3 ft off, drawn the other way
    return StepReader({
        'outline': _outline(L1, [{'name': 'porch', 'box': PORCH}, {'name': 'garage', 'box': GARAGE}]),
        ('walls', 'L1'): page_walls([(a, b, True) for a, b in edges(L1)] + [(*PARTITION, False)]),
        'walls:L1:garage': page_walls([([0.7, 0.5 + jitter], [0.55, 0.5 + jitter], False), (*GARAGE_LEFT, False)]),
        'walls:L1:porch': page_walls([(a, b, False) for a, b in PORCH_WALLS]),
    })


def scenario_walls_read_the_whole_floor_and_each_wing():
    _, sheet = _place()
    reader = _r1_reader()
    b, st = _build('house', reader, legacy=True)
    ids = [s['id'] for s in st['steps']]
    walls = _walls_steps(st, 'L1')
    check({'walls:L1:porch', 'walls:L1:garage'} <= {s['id'] for s in walls},
          ('each wing keeps its step id', [s['id'] for s in walls]))
    whole = _whole_floor(st, 'L1')
    check(len(walls) == 3, ('the whole floor plus both wings, nothing else', [s['id'] for s in walls]))
    check(whole['id'] not in ('walls:L1:porch', 'walls:L1:garage'), whole)
    check(ids.index('outline:L1') < ids.index(whole['id']) < min(ids.index('walls:L1:porch'), ids.index('walls:L1:garage'))
          and max(ids.index(s['id']) for s in walls) < ids.index('openings:L1'),
          ('the whole floor is read first, after its outline and before its openings', ids))
    call = next(c for c in reader.calls if c['step'] == whole['id'])
    check(call['kind'] == 'walls' and call['context']['box'] == FULL, ('the whole floor crop is read', call))
    for wing, box in (('walls:L1:porch', PORCH), ('walls:L1:garage', GARAGE)):
        call = next(c for c in reader.calls if c['step'] == wing)
        check(all(abs(x - y) < 1e-9 for x, y in zip(call['context']['box'], box)), ('a wing is read zoomed', wing, call['context']['box']))


def scenario_whole_floor_walls_settle_on_the_outline():
    _, sheet = _place()
    _build('house', _r1_reader(), legacy=True)
    house = _building('house')
    l1 = [w for w in house['walls'] if w['level'] == 'L1']
    for a, b in edges(L1):
        a, b = _world(sheet, 1, 'L1', a), _world(sheet, 1, 'L1', b)
        on_edge = [w for w in l1 if _same_wall(w, a, b)]
        check(len(on_edge) == 1 and on_edge[0].get('state') == 'settled',
              ('the outside wall along each outline edge settles once', a, b, [(w['from'], w['to'], w.get('state')) for w in l1]))


def scenario_a_wall_two_reads_return_settles_once():
    _, sheet = _place()
    _build('house', _r1_reader(), legacy=True)
    l1 = [w for w in _building('house')['walls'] if w['level'] == 'L1']
    a, b = (_world(sheet, 1, 'L1', p) for p in PARTITION)
    partition = [w for w in l1 if _same_wall(w, a, b)]
    check(len(partition) == 1, ('the partition both reads returned is one wall', [(w['id'], w['from'], w['to']) for w in partition]))
    check(partition[0].get('state') == 'settled', partition)
    check(not _overlaps(l1), ('no wall lies on top of another', _overlaps(l1)))
    check(len(l1) == 8 and all(w.get('state') == 'settled' for w in l1),
          ('four outside walls, the partition, the garage wall and two porch walls, all settled',
           len(l1), [(w['from'], w['to'], w.get('state')) for w in l1]))


def scenario_recorded_pool_house_reads_every_floor_whole_and_never_twice():
    # The reproduction's pool house: the porch read sees only the house's right
    # wall, in three pieces; the stair read redraws three of the upper floor's
    # outside walls. Every floor still gets a whole-floor read, and no wall is
    # left lying on another.
    _, sheet = _place(floors=('Main floor', 'Second floor'))
    lower = POOL_OUTLINE['outline']
    reader = StepReader({
        'outline': POOL_OUTLINE,
        'registration': POOL_REGISTRATION,
        ('walls', 'L1'): page_walls([(a, b, True) for a, b in edges(lower)]),
        ('walls', 'L2'): page_walls([(a, b, True) for a, b in edges(POOL_UPPER)]),
        'walls:L1:porch': POOL_PORCH_WALLS,
        'walls:L2:stair': POOL_STAIR_WALLS,
    })
    b, st = _build('house', reader, legacy=True)
    for level, wing, box in (('L1', 'walls:L1:porch', FULL), ('L2', 'walls:L2:stair', FULL)):
        steps = _walls_steps(st, level)
        whole = _whole_floor(st, level, box)
        check({s['id'] for s in steps} == {whole['id'], wing},
              ('the whole floor and its one wing', level, [s['id'] for s in steps]))
    house = _building('house')
    for level, poly, page in (('L1', lower, 1), ('L2', POOL_UPPER, 2)):
        walls = [w for w in house['walls'] if w['level'] == level]
        check(not _overlaps(walls), ('a wall two reads drew is kept once', level, _overlaps(walls),
                                     [(w['from'], w['to']) for w in walls]))
        settled = [w for w in walls if w.get('state') == 'settled']
        for a, b in edges(poly):
            a, b = _world(sheet, page, level, a), _world(sheet, page, level, b)
            check(any(all(_point_segment(p, a, b) <= 1 for p in (w['from'], w['to'])) for w in settled),
                  ('each outline edge carries a settled wall', level, a, b))


# --- R2 a fit that changes the shape says so ---------------------------------

L1_31 = rect(0.2, 0.1, 31, 22)          # the pool house's enclosed walls
L1_38 = rect(0.2, 0.1, 38, 22)          # the same with the open porch
UPPER = rect(0.2, 0.1, 25.4167, 22)


def scenario_a_registration_fitted_to_a_bigger_floor_below_says_the_shapes_do_not_match():
    _place(floors=('Main floor', 'Second floor'))
    reader = StepReader({'outline': _outline(L1_31), 'registration': _registration(L1_38, UPPER)})
    b = tb.start(_legacy_inputs(), reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['step'] == 'outline:L1', (st['state'], st.get('pause')))
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['step'] == 'registration:L2', (st['state'], st.get('pause')))
    why = st['pause']['why']
    check(MISMATCH in why, ("a 38 x 22 floor below fitted to a 31 x 22 main floor says the shapes do not match", why))
    check(not RAW_ID.search(why), why)


def scenario_a_registration_onto_an_equal_floor_below_settles():
    _, sheet = _place(floors=('Main floor', 'Second floor'))
    reader = StepReader({'outline': _outline(L1_31), 'registration': _registration(L1_31, UPPER)})
    b = tb.start(_legacy_inputs(), reader=reader, inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['step'] == 'registration:L2', (st['state'], st.get('pause')))
    check(MISMATCH not in st['pause']['why'], ('equal shapes raise no size question', st['pause']['why']))
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause')))
    level = next(l for l in _building('house')['levels'] if l['id'] == 'L2')
    check(level.get('state') == 'settled' and len(level.get('outline') or []) == 4, level)
    size = _bounds(level['outline'])
    check(abs(size[2] - size[0] - 25.4167) < 0.2 and abs(size[3] - size[1] - 22) < 0.2, ('the upper floor keeps its size', size))


def _roof_reader(roof_outline):
    box = _bounds(roof_outline)
    return StepReader({'outline': _outline(L1_31),
                       'roof': {'outline': roof_outline, 'confidence': 0.7,
                                'sections': [{'kind': 'gable', 'box': box, 'ridge': 'x', 'low_side': None}]}})


def scenario_a_roof_that_includes_the_porch_pauses_and_says_the_shapes_do_not_match():
    _place(roof=True)
    b = tb.start(_legacy_inputs(), reader=_roof_reader(L1_38), inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(st['state'] == 'paused' and st['pause']['step'] == 'roof',
          ('a 38 x 22 roof over a 31 x 22 floor waits for the person', st['state'], st.get('pause'),
           [e for e in st['events'] if e['type'] in ('question', 'error')][-2:]))
    check(MISMATCH in st['pause']['why'], st['pause'])
    check(not RAW_ID.search(st['pause']['why']), st['pause']['why'])
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause')))
    check(_building('house')['roof']['sections'], 'accepting it settles the roof')


def scenario_a_roof_over_its_floor_with_eaves_settles_without_a_pause():
    _place(roof=True)
    b = tb.start(_legacy_inputs(), reader=_roof_reader(rect(0.2 - U, 0.1 - V, 33, 24)), inline=True)
    tb.answer(b, 'outline:L1', {'accept': True})
    st = tb.status(b)
    check(st['state'] == 'done', ('equal shapes settle alone', st['state'], st.get('pause')))
    sections = _building('house')['roof']['sections']
    check(len(sections) == 1 and sections[0].get('state') == 'settled', sections)


# --- R3 a second building lands beside the first ------------------------------

def scenario_buildings_without_a_lot_land_side_by_side():
    _place()
    _build('house', StepReader({'outline': _outline(L1)}))
    pool, _ = _place(building='pool', name='Pool house', kind='pool_house')
    _build(pool, StepReader({'outline': _outline(L1_31)}))
    house, pool_house = _building('house'), _building(pool)
    check(house['position'] == [0, 0] and house['rotation'] == 0, ('the first building stays put', house['position']))
    first, second = _world_bounds(house), _world_bounds(pool_house)
    check(second[0] >= first[2] or first[0] >= second[2] or second[1] >= first[3] or first[1] >= second[3],
          ('the buildings do not overlap', first, second))
    check(abs(pool_house['position'][0] - (first[2] + 10)) < 0.01 and abs(pool_house['position'][1]) < 1e-9
          and pool_house['rotation'] == 0,
          ('10 ft right of the rightmost building, y 0, unturned', pool_house['position'], pool_house['rotation'], first))


# --- R4 finishes in a part build ----------------------------------------------

def _kit_default(role):
    return {'id': KIT['materials'][role]['asset'], 'color': KIT['materials'][role]['color']}


def scenario_finishes_read_is_told_the_kit_roles_and_ids():
    _place(photo=True)
    reader = StepReader({'outline': _outline(L1)})
    _build('house', reader)
    call = next(c for c in reader.calls if c['kind'] == 'finishes')
    text = json.dumps(call['context'])
    missing_roles = [role for role in KIT['materials'] if json.dumps(role) not in text]
    missing_ids = sorted({v['asset'] for v in KIT['materials'].values() if json.dumps(v['asset']) not in text})
    check(not missing_roles and not missing_ids, ('the finishes read sees every kit role and allowed id',
                                                 missing_roles, missing_ids, sorted(call['context'])))


def scenario_finishes_role_with_an_id_outside_the_kit_takes_the_kit_default():
    _place(photo=True)
    answer = {'materials': {'siding': {'id': 'board_and_batten', 'color': '#112233'},
                            'trim': {'id': 'painted_wood', 'color': '#f2f2ee'}}}
    _build('house', StepReader({'outline': _outline(L1), 'finishes': answer}))
    own = _building('house').get('materials') or {}
    check(own == {'siding': {'id': 'board_and_batten', 'color': '#112233'}, 'trim': _kit_default('trim')},
          ('both answered roles are written, the bad id as the kit default, nothing else', own))


def scenario_recorded_pool_finishes_write_kit_defaults_for_the_roles_it_named():
    _place(photo=True)
    _build('house', StepReader({'outline': _outline(L1), 'finishes': POOL_FINISHES}))
    own = _building('house').get('materials') or {}
    want = {role: _kit_default(role) for role in ('trim', 'roof', 'window_frame')}
    check(own == want, ('kit roles answered with ids outside the kit take its defaults; '
                        'roles outside the kit are left out', own))
    check('siding' not in ts.current()['materials'], 'a part build leaves plan.materials alone')


# --- R5b dropped pieces are named once, in plain words ------------------------

def scenario_openings_left_out_are_named_once_per_step():
    _place()
    top, bottom = [0.45, 0.1], [0.45, 0.1 + DEPTH_V]
    reader = StepReader({
        'outline': _outline(L1),
        ('walls', 'L1'): page_walls([(a, b, True) for a, b in edges(L1)]),
        'openings': {'openings': [
            {'at': [0.3, 0.1], 'kind': 'window', 'width_ft': 3.0, 'sill_ft': 3.0, 'head_ft': 7.0},
            # wider than any wall on the floor: no wall can carry them
            {'at': top, 'kind': 'slider', 'width_ft': 80.0, 'sill_ft': 0.0, 'head_ft': 8.0},
            {'at': bottom, 'kind': 'bifold', 'width_ft': 80.0, 'sill_ft': 0.0, 'head_ft': 8.0}]},
    })
    b, st = _build('house', reader, legacy=True)
    logs = _logs(st, 'openings:L1')
    sentence = '2 openings were outside their walls and were left out.'
    check(logs.count(sentence) == 1, ('one plain sentence for the step', logs))
    check(not any(RAW_ID.search(text) for text in logs), ('never a raw id', logs))
    check(not any(text.startswith('Dropped opening') for text in logs), logs)
    kept = [o for o in _building('house')['openings'] if o.get('src', {}).get('step') == 'openings:L1']
    check(len(kept) == 1, ('the window that fits stays', kept))


SCENARIOS = (
    scenario_walls_read_the_whole_floor_and_each_wing,
    scenario_whole_floor_walls_settle_on_the_outline,
    scenario_a_wall_two_reads_return_settles_once,
    scenario_recorded_pool_house_reads_every_floor_whole_and_never_twice,
    scenario_a_registration_fitted_to_a_bigger_floor_below_says_the_shapes_do_not_match,
    scenario_a_registration_onto_an_equal_floor_below_settles,
    scenario_a_roof_that_includes_the_porch_pauses_and_says_the_shapes_do_not_match,
    scenario_a_roof_over_its_floor_with_eaves_settles_without_a_pause,
    scenario_buildings_without_a_lot_land_side_by_side,
    scenario_finishes_read_is_told_the_kit_roles_and_ids,
    scenario_finishes_role_with_an_id_outside_the_kit_takes_the_kit_default,
    scenario_recorded_pool_finishes_write_kit_defaults_for_the_roles_it_named,
    scenario_openings_left_out_are_named_once_per_step,
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
