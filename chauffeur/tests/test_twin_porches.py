"""Several porches, and a joint report that names only real gaps (task 7b of
docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md; spec
docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md
section 3 "a screened porch is a porch with its roof", section 5 porch-roof
support, section 6a joint report; ruling R17). Written before the code.

A. Several porches.
  - twin_plan.normalize keeps `porches: [{id, polygon, floor, columns,
    screened?}]` beside the legacy single `porch` (unchanged). Each porch is
    validated as `porch` is today; `screened` is kept only when boolean; a
    missing id becomes `porch-<n>`; an invalid porch is dropped with a plain
    note.
  - PROMPTS['draft'] and PROMPTS['draft_level'] ask for every open or screened
    porch in `porches`; parse('draft', ...) accepts `porches` (and still
    `porch`, which becomes porches[0] on the plan).
  - _check_draft: a porch roof section is supported when any porch polygon or
    column of ANY porch lies under it.
B. twin_joints.report stops flagging a roof edge (or plate) that lies inside
   another section's rect (grown by 0.5 ft) or inside any level's outline, and
   still flags an outer edge more than 1.5 ft from any wall.

The draft build uses the stub-reader harness of tests/test_twin_build_draft.py
on the recorded main-house spike answer, with the rear porch added to
`porches`: polygon x 14.33-30.67, y 52-66 (under the rear_porch roof section,
rect [14.33, 50, 30.67, 66]), with 4 columns at its corners.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_porches.py
"""
import copy
import json
import math
import os
import re
import sys
import tempfile
import traceback

# Before any services import: never the real data dir.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_porches_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_compose as tc  # noqa: E402
from services import twin_library as tl  # noqa: E402
from services import twin_joints as tj  # noqa: E402
from services import twin_plan as tp  # noqa: E402
from services import twin_reads as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _accept_all, _pdf, check  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
SPIKE_PATH = os.path.join(RECORDED, 'draft-main-spike-answer.json')
UNSUPPORTED_WHY = 'This porch roof has no porch or columns beneath it.'

REAR_POLYGON = [[14.33, 52], [30.67, 52], [30.67, 66], [14.33, 66]]
REAR_COLUMNS = [{'at': [14.75, 52.42], 'size': 0.83}, {'at': [30.25, 52.42], 'size': 0.83},
                {'at': [30.25, 65.58], 'size': 0.83}, {'at': [14.75, 65.58], 'size': 0.83}]
REAR_PORCH_RECT = (14.33, 50, 30.67, 66)
FRONT_PORCH_RECTS = {(14.33, 6.33, 23.08, 14.33), (23.08, 6.33, 37, 13.33)}


# --- stub reader (copied from tests/test_twin_build_draft.py) -------------------

def spike():
    with open(SPIKE_PATH, encoding='utf-8') as f:
        return json.load(f)


def rear_porch(screened=None):
    porch = {'polygon': copy.deepcopy(REAR_POLYGON), 'floor': 0, 'columns': copy.deepcopy(REAR_COLUMNS)}
    if screened is not None:
        porch['screened'] = screened
    return porch


def spike_with_porches():
    """The spike answer with its front porch and the rear porch in `porches`,
    and no legacy `porch`."""
    answer = spike()
    front = answer['building'].pop('porch')
    answer['building']['porches'] = [front, rear_porch(screened=True)]
    return answer


class DraftReader(Reader):
    """test_twin_build's fake, plus the draft kinds: 'draft' answers the spike
    (or a given answer), 'draft_level' answers the same building, 'draft_rooms'
    answers nothing."""

    def __init__(self, answer=None, rooms=None, **kw):
        super().__init__(**kw)
        self.answer = spike() if answer is None else answer
        self.rooms = {'rooms': [], 'walls': []} if rooms is None else rooms
        self.seen = []

    def __call__(self, kind, images, context, *, run, step):
        self.seen.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context)})
        if kind in ('draft', 'draft_level'):
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.answer)
        if kind == 'draft_rooms':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.rooms)
        return super().__call__(kind, images, context, run=run, step=step)


def _drawn_house():
    """Main house drawings: floor pages Main floor and Upper floor, a roof page.
    No photos, no lot."""
    engine_tests._fresh()
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(3))
    ts.set_page_roles([
        {'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': sheets, 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': None, 'building': 'house'},
        {'source': sheets, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    return sheets


def _house(plan, bid='house'):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _rect_of(section):
    return tuple(round(v, 2) for v in section.get('read_geometry', {}).get('rect', section['rect']))


def _near_rect(a, b, tol=0.6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _same_polygon(a, b, tol=0.6):
    return len(a) == len(b) and all(any(math.dist(p, q) <= tol for q in b) for p in a)


def _build(answer):
    _drawn_house()
    reader = DraftReader(answer=answer)
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    return st, _house(ts.current())


# --- plan helpers --------------------------------------------------------------

L1 = {'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 10,
      'outline': [[0, 0], [30, 0], [30, 20], [0, 20]]}


def _plan(**building):
    return {'units': 'ft', 'site': {}, 'materials': {},
            'buildings': [{'id': 'house', 'name': 'Main house', 'position': [0, 0], 'rotation': 0,
                           'levels': [copy.deepcopy(L1)], 'walls': [], 'openings': [], 'rooms': [],
                           'roof': {'sections': [], 'extensions': []}, **copy.deepcopy(building)}]}


def _porch_notes(notes):
    return [n for n in notes if 'porch' in n.lower()]


# --- A. twin_plan --------------------------------------------------------------

def test_plan_keeps_two_porches_with_ids_and_screened():
    front = {'polygon': [[0, -8], [30, -8], [30, 0], [0, 0]], 'floor': 0.5,
             'columns': [{'at': [0.5, -7.5], 'size': 0.8}, {'at': [29.5, -7.5], 'size': 0.8}],
             'screened': False}
    rear = {'id': 'rear', 'polygon': [[5, 20], [25, 20], [25, 32], [5, 32]], 'floor': 0,
            'columns': [{'at': [5.5, 31.5], 'size': 0.8}, {'at': [24.5, 31.5], 'size': 0.8}],
            'screened': True}
    normalized, notes = tp.normalize(_plan(porches=[front, rear]))
    b = normalized['buildings'][0]
    porches = b.get('porches')
    check(isinstance(porches, list) and len(porches) == 2, ('both porches are kept', porches, notes))
    check(porches[0].get('id') == 'porch-1', ('a porch with no id gets porch-<n>', porches[0].get('id')))
    check(porches[1].get('id') == 'rear', ('a supplied id stays', porches[1].get('id')))
    check(porches[0].get('screened') is False and porches[1].get('screened') is True,
          ('screened stays when boolean', [p.get('screened') for p in porches]))
    check(porches[0]['polygon'] == front['polygon'] and porches[1]['polygon'] == rear['polygon'],
          ('polygons unchanged', porches))
    check(len(porches[0]['columns']) == 2 and len(porches[1]['columns']) == 2, porches)
    check(porches[0]['floor'] == 0.5 and porches[1]['floor'] == 0, porches)
    check(not _porch_notes(notes), ('valid porches raise no note', notes))
    # Stable: normalizing the result again keeps the same ids and notes nothing.
    again, notes2 = tp.normalize(normalized)
    check([p['id'] for p in again['buildings'][0]['porches']] == ['porch-1', 'rear'],
          ('ids are stable', again['buildings'][0]['porches']))
    check(not _porch_notes(notes2), notes2)


def test_plan_drops_invalid_porch_with_plain_note():
    good = {'polygon': [[0, -8], [30, -8], [30, 0], [0, 0]], 'floor': 0,
            'columns': [{'at': [0.5, -7.5], 'size': 0.8}, {'at': [3, -7.5], 'size': -1}]}
    bad = {'polygon': [[0, 20], [10, 20]], 'floor': 0}          # two points: no polygon
    odd = {'polygon': [[5, 20], [25, 20], [25, 32], [5, 32]], 'floor': 0, 'screened': 'yes'}
    normalized, notes = tp.normalize(_plan(porches=[good, bad, odd]))
    porches = normalized['buildings'][0].get('porches') or []
    check(len(porches) == 2, ('the invalid porch is dropped, the others kept', porches, notes))
    check(len(porches[0]['columns']) == 1, ('an invalid column is dropped as for porch', porches[0]['columns']))
    check('screened' not in porches[1], ('a non-boolean screened is not kept', porches[1]))
    porch_notes = _porch_notes(notes)
    check(any(n.startswith('Dropped') for n in porch_notes), ('a plain note names the dropped porch', notes))
    check(all(n.endswith('.') and not re.search(r'[{}\[\]]', n) for n in porch_notes),
          ('plain sentences, no raw data', porch_notes))
    ids = [p['id'] for p in porches]
    check(all(re.fullmatch(r'porch-\d+', i) for i in ids) and len(set(ids)) == 2, ('porch-<n> ids', ids))


def test_plan_legacy_porch_unchanged():
    """Guard: the legacy single porch keeps working as today."""
    porch = {'polygon': [[0, -8], [30, -8], [30, 0], [0, 0]], 'floor': 0,
             'columns': [{'at': [0.5, -7.5], 'size': 0.8}]}
    normalized, notes = tp.normalize(_plan(porch=porch))
    b = normalized['buildings'][0]
    check(b.get('porch') == porch, ('the legacy porch is kept as is', b.get('porch'), notes))
    check(not _porch_notes(notes), notes)


# --- A. twin_reads -------------------------------------------------------------

def test_prompts_ask_for_porches():
    for kind in ('draft', 'draft_level'):
        prompt = tr.PROMPTS[kind]
        check('porches' in prompt, (kind, 'the prompt asks for porches'))
        check('screened' in prompt.lower(), (kind, 'the prompt names screened porches'))
        check(re.search(r'porches\s*:\s*\[', prompt) or re.search(r'roof:\{sections,extensions\},porches', prompt)
              or 'porches,' in prompt or ',porches' in prompt,
              (kind, 'porches is part of the requested shape'))
    draft = tr.PROMPTS['draft']
    check(re.search(r'\b(rear|side)\b[^.]*porch|porch[^.]*\b(rear|side)\b', draft, re.I),
          'the draft prompt asks for every porch: front, rear and side')


def test_parse_accepts_porches():
    answer = spike_with_porches()
    out, problems = tr.parse('draft', answer)
    building = out.get('building') or {}
    porches = building.get('porches')
    check(isinstance(porches, list) and len(porches) == 2, ('parse keeps porches', porches, problems))
    check(not [p for p in problems if 'porch' in p], ('no porch problems', problems))
    rear = porches[1]
    check(rear.get('polygon') == REAR_POLYGON, rear)
    check(len(rear.get('columns') or []) == 4 and rear['columns'][0] == REAR_COLUMNS[0], rear)
    check(rear.get('screened') is True, ('screened is kept', rear))
    check(porches[0].get('polygon') == spike()['building']['porch']['polygon'], porches[0])
    # An invalid porch is dropped, the rest kept.
    broken = spike_with_porches()
    broken['building']['porches'].append({'polygon': [[0, 0], [1, 1]], 'floor': 0})
    out, problems = tr.parse('draft', broken)
    check(len(out['building'].get('porches') or []) == 2, ('an invalid porch is dropped', out['building'].get('porches')))
    check(any('porches' in p for p in problems), ('the problem names porches', problems))
    # The per-level read accepts porches too.
    level = {'building': {'levels': [copy.deepcopy(answer['building']['levels'][0])],
                          'walls': [], 'openings': [], 'rooms': [], 'stairs': [],
                          'porches': copy.deepcopy(answer['building']['porches'])}}
    out, problems = tr.parse('draft_level', level)
    check(len((out.get('building') or {}).get('porches') or []) == 2, ('draft_level keeps porches', out, problems))


def test_parse_still_accepts_porch():
    """Guard: the legacy single porch still parses."""
    out, problems = tr.parse('draft', spike())
    porch = (out.get('building') or {}).get('porch')
    check(porch and len(porch.get('columns') or []) == 4, ('porch still parses', porch, problems))


# --- A. the draft build --------------------------------------------------------

def test_draft_rear_porch_supports_its_roof():
    st, house = _build(spike_with_porches())
    porches = house.get('porches') or []
    check(len(porches) == 2, ('both porches reach the plan', porches))
    rear = next((p for p in porches if _same_polygon(p.get('polygon', []), REAR_POLYGON)), None)
    check(rear is not None, ('the rear porch is on the plan', porches))
    check(len(rear.get('columns') or []) == 4, rear)
    check(rear.get('screened') is True, ('screened survives the build', rear))
    check(all(isinstance(p.get('id'), str) and p['id'] for p in porches), [p.get('id') for p in porches])
    sections = house['roof']['sections']
    over_rear = [s for s in sections if _near_rect(_rect_of(s), REAR_PORCH_RECT)]
    check(len(over_rear) == 1, ('the rear porch roof is in the plan', [_rect_of(s) for s in sections]))
    check(over_rear[0].get('state') != 'ghost',
          ('a rear porch under the rear_porch section settles it', over_rear[0].get('state'), over_rear[0].get('why')))
    front = [s for s in sections if any(_near_rect(_rect_of(s), r) for r in FRONT_PORCH_RECTS)]
    check(len(front) == 2 and all(s.get('state') != 'ghost' for s in front),
          ('the front porch in porches still supports its roofs', [(s.get('state'), s.get('why')) for s in front]))
    ghosts = [e for e in st['events'] if e['type'] == 'ghost' and e.get('why') == UNSUPPORTED_WHY]
    check(not ghosts, ('no porch roof ghost', [e.get('piece', {}).get('rect') for e in ghosts]))


def test_draft_rear_porch_columns_alone_support_its_roof():
    """Columns of any porch count, even when that porch's polygon is elsewhere."""
    answer = spike_with_porches()
    rear = answer['building']['porches'][1]
    rear['polygon'] = [[14.33, 66.5], [30.67, 66.5], [30.67, 70], [14.33, 70]]   # beyond the roof
    rear['columns'] = [{'at': [20, 60], 'size': 0.83}, {'at': [25, 60], 'size': 0.83}]
    st, house = _build(answer)
    over_rear = [s for s in house['roof']['sections'] if _near_rect(_rect_of(s), REAR_PORCH_RECT)]
    check(len(over_rear) == 1 and over_rear[0].get('state') != 'ghost',
          ('columns of a second porch under the section settle it', [(s.get('state'), s.get('why')) for s in over_rear]))


def test_draft_legacy_porch_becomes_first_porch():
    st, house = _build(spike())
    porches = house.get('porches') or []
    front = spike()['building']['porch']
    check(len(porches) >= 1 and _same_polygon(porches[0].get('polygon', []), front['polygon']),
          ('a read porch becomes porches[0] on the plan', porches))
    check(len(porches[0].get('columns') or []) == 4, porches[0])
    over_rear = [s for s in house['roof']['sections'] if _near_rect(_rect_of(s), REAR_PORCH_RECT)]
    check(len(over_rear) == 1 and over_rear[0].get('state') == 'ghost'
          and over_rear[0].get('why') == UNSUPPORTED_WHY,
          ('with no rear porch read, the rear porch roof stays a ghost', [(s.get('state'), s.get('why')) for s in over_rear]))


# --- B. twin_joints.report -----------------------------------------------------

# The 8 main sections' inner edges, as report() words them on the spike after
# normalize + snap before this task (side, feet). Each is an edge that runs
# over the house: inside another section's rect or inside a level's outline.
MAIN_INNER = {('front', '12.7'), ('left', '5.7'), ('front', '28.7'), ('left', '26'), ('front', '2.7'),
              ('rear', '8.7'), ('right', '15'), ('rear', '25.3')}
EDGE_LINE = re.compile(r'roof edges? over the (\w+) (?:is|are) ([\d.]+) ft from any wall')


def _snapped(building_raw):
    normalized, _ = tp.normalize({'units': 'ft', 'site': {}, 'materials': {}, 'buildings': [building_raw]})
    building = normalized['buildings'][0]
    tj.snap(building)
    return building


def test_report_spike_inner_edges_silent():
    building = _snapped(spike()['building'])
    lines = tj.report(building)
    flagged = {m.groups() for line in lines for m in [EDGE_LINE.search(line)] if m}
    check(not flagged & MAIN_INNER, ('no roof edge line for a main section inner edge', sorted(flagged & MAIN_INNER), lines))
    check(not [line for line in lines if 'roof plate' in line], ('no roof plate line', lines))
    check(not [line for line in lines if 'no wall beneath' in line], ('no roof edge without a wall', lines))


def _walls(x0, y0, x1, y1):
    corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return [{'id': f'w{i}', 'level': 'L1', 'from': corners[i], 'to': corners[(i + 1) % 4], 'height': 10,
             'thickness': 0.5, 'exterior': True, 'state': 'settled'} for i in range(4)]


def _section(sid, rect):
    return {'id': sid, 'kind': 'gable', 'rect': list(rect), 'ridge': 'x', 'pitch': 6, 'plate': 10,
            'overhang': 1, 'pitch_source': 'drawn', 'state': 'settled'}


def _lone(sections, outline=True):
    level = copy.deepcopy(L1)
    if not outline:
        level.pop('outline')
    return _snapped({'id': 'house', 'name': 'Main house', 'position': [0, 0], 'rotation': 0,
                     'levels': [level], 'walls': _walls(0, 0, 30, 20), 'openings': [], 'rooms': [],
                     'roof': {'sections': sections, 'extensions': []}})


def test_report_lone_outer_edge_still_flagged():
    """Guard: an outer edge 2 ft off its wall still reports one line."""
    lines = tj.report(_lone([_section('a', [0, 0, 30, 22])]))
    check(lines == ['A roof edge over the rear is 2 ft from any wall.'], lines)


def test_report_edge_inside_neighbour_rect_silent():
    # b's edges lie inside a's rect grown by 0.5 ft (its rear edge is 0.3 ft
    # past a's): they are inner joints. a's rear edge, 2 ft off the wall, is not.
    lines = tj.report(_lone([_section('a', [0, 0, 30, 22]), _section('b', [10, 5, 20, 22.3])], outline=False))
    check(lines == ['A roof edge over the rear is 2 ft from any wall.'],
          ('only the outer edge is reported', lines))


def test_report_edge_inside_outline_silent():
    # The section's left edge runs across the floor, 10 ft from any wall, inside the outline.
    lines = tj.report(_lone([_section('a', [10, 0, 30, 20])]))
    check(lines == [], ('an edge inside the outline is not a gap', lines))


def test_report_outline_boundary_keeps_plate_check():
    section = _section('a', [0, 0, 30, 20])
    section['plate'] = 12
    lines = tj.report(_lone([section]))
    check(lines == ['A roof plate over the front is 2 ft above its wall tops.'], lines)


def test_report_outline_boundary_keeps_missing_wall_check():
    house = _lone([_section('a', [0, 0, 30, 20])])
    house['walls'] = [w for w in house['walls'] if w['id'] != 'w2']
    lines = tj.report(house)
    check('A roof edge over the rear is 20 ft from any wall.' in lines, lines)


def test_report_internal_cross_gable_keeps_plate_check():
    cross = _section('cross', [10, 0, 20, 10])
    cross['plate'] = 12
    lines = tj.report(_lone([_section('main', [0, 0, 30, 20]), cross]))
    check(lines == ['A roof plate over the front is 2 ft above its wall tops.'], lines)


def test_all_porches_deduplicates_aliases_without_mutation():
    front = dict(rear_porch(), id='front')
    rear = dict(rear_porch(), id='rear')
    moved_alias = dict(front, polygon=[[0, 0], [1, 0], [1, 1]])
    for alias in (moved_alias, {k: v for k, v in front.items() if k != 'id'}):
        house = {'porches': [front, copy.deepcopy(front), rear], 'porch': alias}
        before = copy.deepcopy(house)
        got = tp.porches(house)
        check(got == [front, rear], ('id first; polygon only without an id', got))
        check(got[0] is front and house == before, 'no copying or mutation of pieces')
    check(tp.porches({'porch': front}) == [front], 'legacy-only porch')
    check(tp.porches({'porches': [front, rear], 'porch': rear}) == [front, rear],
          'a shared legacy reference does not reorder the collection')
    check(tp.porches({}) == [], 'no porches')
    unique = dict(rear_porch(), polygon=[[0, 0], [1, 0], [1, 1]])
    check(tp.porches({'porches': [front], 'porch': unique}) == [unique, front],
          'a distinct legacy porch stays first')


def test_compose_porches_collection_keeps_clearance_and_foundations():
    from test_twin_compose import _plan as compose_plan
    legacy = compose_plan()
    collection = copy.deepcopy(legacy)
    for house in collection['buildings']:
        if house.get('porch'):
            house['porches'] = [dict(house.pop('porch'), id='side')]
    before = copy.deepcopy(collection)
    old_geometry = tc._building_geometry(legacy['buildings'], [])
    new_geometry = tc._building_geometry(collection['buildings'], [])
    check(old_geometry[1] and old_geometry == new_geometry,
          ('collection porch participates in clearance and foundation geometry', new_geometry[1]))
    expected, old_notes = tc.compose(legacy, tl.kit('modern_farmhouse'), seed=1)
    actual, new_notes = tc.compose(collection, tl.kit('modern_farmhouse'), seed=1)
    check(actual['site'] == expected['site'] and new_notes == old_notes,
          'collection porch preserves the legacy yard clearances and foundations')
    check(collection == before, 'composition does not mutate the collection plan')


TESTS = (
    test_plan_keeps_two_porches_with_ids_and_screened,
    test_plan_drops_invalid_porch_with_plain_note,
    test_plan_legacy_porch_unchanged,
    test_prompts_ask_for_porches,
    test_parse_accepts_porches,
    test_parse_still_accepts_porch,
    test_draft_rear_porch_supports_its_roof,
    test_draft_rear_porch_columns_alone_support_its_roof,
    test_draft_legacy_porch_becomes_first_porch,
    test_report_spike_inner_edges_silent,
    test_report_lone_outer_edge_still_flagged,
    test_report_edge_inside_neighbour_rect_silent,
    test_report_edge_inside_outline_silent,
    test_report_outline_boundary_keeps_plate_check,
    test_report_outline_boundary_keeps_missing_wall_check,
    test_report_internal_cross_gable_keeps_plate_check,
    test_all_porches_deduplicates_aliases_without_mutation,
    test_compose_porches_collection_keeps_clearance_and_foundations,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
