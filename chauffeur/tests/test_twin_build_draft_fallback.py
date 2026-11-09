"""One floor at a time when the whole set does not fit, and rooms read whole
(plan docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md,
Task 9; spec docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md
section 4 (rooms) and section 5 "Per-level fallback"; Task 5 review carry-forwards).

- The fallback runs when the draft is cut off at the output limit (the reader
  returns {'error': ..., 'truncated': True}) or when the draft's first floor
  fails its checks. Within the same 'draft' step it runs draft_level reads in
  order: the first floor; then each next level, with the settled lower levels
  as JSON in its context; then the roof, with all the levels.
- It stops at the first level that returns nothing usable, and that pauses as
  in Task 7: "The drawings could not be read as one building.", Try again
  rereads the drawings.
- The build log says "The drawings were read one floor at a time." once.
- draft_rooms: after the draft settles, one read with the floor pages whole
  plus the settled levels, exterior walls and openings. Rooms and interior
  walls come back in feet and settle as is. A room or wall outside its level's
  outline becomes a ghost with a plain why. A reply with rooms and no walls
  key (no interior walls) still settles its rooms.
- Results read as plain sentences: no log line carries a raw piece id.

How a test tells the draft_level reads apart (assumption, used throughout):
the read's context['level'] is the level id being read ('L1', 'L2', ...) and
'roof' for the roof read. The settled lower levels are context['settled']
['levels'] (the same key the rooms read uses); a JSON string is accepted too.

The reader is a stub keyed by kind (its first argument), built on
test_twin_build's fake (which answers the side 'outline' read harmlessly). The
draft_level answers are the recorded whole-building spike answer split into
its first floor, its upper floor and its roof, in feet.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_draft_fallback.py
"""
import copy
import json
import math
import os
import re
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_draft_fallback_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _pdf, check  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
SPIKE_PATH = os.path.join(RECORDED, 'draft-main-spike-answer.json')
FAILED_WHY = 'The drawings could not be read as one building.'
ONE_FLOOR = 'The drawings were read one floor at a time.'
TRUNCATED = {'error': 'The reply was cut off at the output limit.', 'truncated': True}
DRAFT_KINDS = ('draft', 'draft_level', 'draft_rooms')
MAIN_ROOFS = {'main', 'cross_gable', 'left_wing', 'front_wing', 'right_block',
              'side_wing', 'rear_gable', 'kitchen_bump'}
# Rooms and partitions inside their own level's outline (spike feet).
KITCHEN = {'name': 'Kitchen', 'level': 'L1', 'polygon': [[1, 15], [10, 15], [10, 25], [1, 25]]}
STUDY = {'name': 'Study', 'level': 'L2', 'polygon': [[16, 16], [30, 16], [30, 30], [16, 30]]}
PARTITION_L1 = {'id': 'p1', 'level': 'L1', 'from': [10, 15], 'to': [10, 25],
                'height': 9, 'thickness': 0.33, 'exterior': False}
PARTITION_L2 = {'id': 'p2', 'level': 'L2', 'from': [23, 16], 'to': [23, 30],
                'height': 8, 'thickness': 0.33, 'exterior': False}


# --- fakes and helpers (copied from test_twin_build_draft.py, plus scopes) ------

def spike():
    with open(SPIKE_PATH, encoding='utf-8') as f:
        return json.load(f)


def per_level():
    """The spike answer split into the three draft_level replies, each in the
    prompt's shape: the first floor (with porch and stairs), the upper floor,
    and the roof with its gable openings."""
    b = spike()['building']
    l1, l2 = b['levels']
    walls1 = [w for w in b['walls'] if w['level'] == 'L1']
    walls2 = [w for w in b['walls'] if w['level'] == 'L2']
    ids1, ids2 = {w['id'] for w in walls1}, {w['id'] for w in walls2}
    return {
        'L1': {'building': {'levels': [l1], 'walls': walls1,
                            'openings': [o for o in b['openings'] if o.get('wall') in ids1],
                            'rooms': [], 'porch': b['porch'], 'stairs': b['stairs']},
               'pages': [], 'checks': {}, 'notes': []},
        'L2': {'building': {'levels': [l2], 'walls': walls2,
                            'openings': [o for o in b['openings'] if o.get('wall') in ids2],
                            'rooms': [], 'porch': None, 'stairs': []},
               'pages': [], 'checks': {}, 'notes': []},
        'roof': {'building': {'roof': copy.deepcopy(b['roof']),
                              'openings': [o for o in b['openings'] if 'section' in o]},
                 'pages': [], 'checks': {}, 'notes': []},
    }


def _scope(context):
    """Which draft_level read this is: 'L1', 'L2', ... or 'roof' (assumption)."""
    return (context or {}).get('level')


def _settled(context):
    settled = (context or {}).get('settled')
    if isinstance(settled, str):
        settled = json.loads(settled)
    return settled or {}


class FallbackReader(Reader):
    """test_twin_build's fake plus the draft kinds:

    - 'draft' answers `draft` (default: a reply cut off at the output limit);
    - 'draft_level' answers levels[_scope(context)], or {} for a scope it does
      not know (nothing usable);
    - 'draft_rooms' answers `rooms`;
    - anything else (the side 'outline' read included) is test_twin_build's.
    """

    def __init__(self, draft=None, levels=None, rooms=None, **kw):
        super().__init__(**kw)
        self.draft = TRUNCATED if draft is None else draft
        self.levels = per_level() if levels is None else levels
        self.rooms = {'rooms': [], 'walls': []} if rooms is None else rooms
        self.seen = []          # every call with its images and context, in order

    def __call__(self, kind, images, context, *, run, step):
        self.seen.append({'kind': kind, 'step': step, 'images': copy.deepcopy(images),
                          'context': copy.deepcopy(context)})
        if kind in DRAFT_KINDS:
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
        if kind == 'draft':
            return copy.deepcopy(self.draft)
        if kind == 'draft_level':
            return copy.deepcopy(self.levels.get(_scope(context), {}))
        if kind == 'draft_rooms':
            return copy.deepcopy(self.rooms)
        return super().__call__(kind, images, context, run=run, step=step)


def _draft_reads(reader):
    """The draft-kind reads in order, a draft_level read named by its scope."""
    return [c['kind'] if c['kind'] != 'draft_level' else f"draft_level {_scope(c['context'])}"
            for c in reader.seen if c['kind'] in DRAFT_KINDS]


def _house(plan, bid='house'):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _drawn_house():
    """Main house drawings: floor pages Main floor and Upper floor and a roof
    page, no photos, no lot."""
    engine_tests._fresh()
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
    ts.set_page_roles([
        {'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': sheets, 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': None, 'building': 'house'},
        {'source': sheets, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    return sheets


def _bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _raw_ids(house):
    ids = {p['id'] for key in ('walls', 'openings', 'rooms', 'levels', 'stairs')
           for p in house.get(key) or [] if isinstance(p, dict) and p.get('id')}
    ids |= {p['id'] for key in ('sections', 'extensions') for p in house['roof'].get(key) or [] if p.get('id')}
    b = spike()['building']
    ids |= {p['id'] for key in ('walls', 'openings', 'stairs') for p in b[key]}
    ids |= {s['id'] for s in b['roof']['sections'] if '_' in s['id']}   # 'main' is an ordinary word
    ids |= {PARTITION_L1['id'], PARTITION_L2['id']}
    return ids


def _has_raw_id(text, house):
    if re.search(r'\b(wall|opening|room|roof|extension|porch|stair|level):', text):
        return True
    return any(re.search(r'(?<![A-Za-z0-9_])' + re.escape(i) + r'(?![A-Za-z0-9_])', text)
               for i in _raw_ids(house))


def _plain(why, house):
    """A plain sentence: something said, and no raw piece id in it."""
    return isinstance(why, str) and bool(why.strip()) and not _has_raw_id(why, house)


def _logs(st):
    return [e.get('text', '') for e in st['events'] if e['type'] == 'log']


def _spike_open_first_floor():
    """Every first-floor exterior wall shortened 2 ft at each end: no end meets
    another (gaps well past the 1 ft weld), so no L1 wall closes."""
    answer = spike()
    walls = []
    for wall in answer['building']['walls']:
        if wall['level'] != 'L1':
            walls.append(wall)
            continue
        length = math.dist(wall['from'], wall['to'])
        if length < 6:
            continue
        ux, uy = [(wall['to'][i] - wall['from'][i]) / length for i in (0, 1)]
        walls.append({**wall, 'from': [wall['from'][0] + 2 * ux, wall['from'][1] + 2 * uy],
                      'to': [wall['to'][0] - 2 * ux, wall['to'][1] - 2 * uy]})
    answer['building']['walls'] = walls
    kept = {w['id'] for w in walls}
    answer['building']['openings'] = [o for o in answer['building']['openings']
                                       if 'wall' not in o or o['wall'] in kept]   # gable openings stay
    return answer


def _check_whole_house(house, label):
    """The plan holds the spike building, as the whole draft would have left it."""
    levels = sorted(house['levels'], key=lambda l: l['elevation'])
    check([(l['id'], l['name']) for l in levels] == [('L1', 'Main floor'), ('L2', 'Upper floor')],
          (label, 'both levels, named from the pages', [(l['id'], l['name']) for l in levels]))
    check(all(l.get('state') != 'ghost' for l in levels), (label, [(l['id'], l.get('why')) for l in levels]))
    box = _bounds(levels[0]['outline'])
    check(all(abs(a - b) <= 0.5 for a, b in zip(box, [0, -1, 70, 65.33])), (label, 'L1 stays in feet', box))
    check(abs(levels[1]['elevation'] - 10.9) <= 0.5, (label, levels[1]))
    l1 = [w for w in house['walls'] if w['level'] == 'L1' and w.get('exterior')]
    check(len(l1) == 22 and all(w.get('state') == 'settled' for w in l1),
          (label, 'the first floor closes and settles', len(l1), [w.get('state') for w in l1]))
    l2 = [w for w in house['walls'] if w['level'] == 'L2' and w.get('src', {}).get('step') == 'draft']
    check(len(l2) == 12, (label, 'every upper-floor wall is in the plan', len(l2)))
    sections = house['roof']['sections']
    check(len(sections) == 11, (label, 'every roof section is in the plan', len(sections)))
    expected = {tuple(s['rect']) for s in spike()['building']['roof']['sections'] if s['id'] in MAIN_ROOFS}
    settled_rects = {tuple(s.get('read_geometry', {}).get('rect', s['rect'])) for s in sections
                     if s.get('state') != 'ghost'}
    check(expected <= settled_rects, (label, 'the eight main-roof sections settle',
                                      [(s['rect'], s.get('state'), s.get('why')) for s in sections]))
    check(len(house['openings']) >= 20, (label, 'wall and gable openings', len(house['openings'])))
    check(sum('section' in o for o in house['openings']) >= 1, (label, 'the gable windows come with the roof',
                                                                [o for o in house['openings'] if 'section' in o]))
    check(house.get('porch') and len(house['porch'].get('columns') or []) == 4, (label, house.get('porch')))
    check(len(house.get('stairs') or []) == 1, (label, house.get('stairs')))
    extensions = house['roof'].get('extensions') or []
    check(len(extensions) == 1 and extensions[0].get('wall'), (label, 'snap attached the awning', extensions))
    for piece in [*house['walls'], *house['openings'], *sections]:
        if piece.get('src', {}).get('step') != 'draft_rooms':
            check((piece.get('src') or {}).get('step') == 'draft',
                  (label, 'every piece names the draft step', piece.get('src')))


# --- tests ---------------------------------------------------------------------

def test_truncated_draft_runs_per_level():
    _drawn_house()
    reader = FallbackReader()
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', ('a cut-off draft is read one floor at a time',
                                  st['state'], st.get('pause'), _trouble(st), _draft_reads(reader)))
    check(_draft_reads(reader) == ['draft', 'draft_level L1', 'draft_level L2', 'draft_level roof', 'draft_rooms'],
          ('draft, then the first floor, the upper floor and the roof, then rooms', _draft_reads(reader)))
    levels_calls = [c for c in reader.seen if c['kind'] == 'draft_level']
    check(all(c['step'] == 'draft' for c in levels_calls),
          ('the per-level reads run within the draft step', [c['step'] for c in levels_calls]))
    check(all(len(c['images']) >= 1 for c in levels_calls), ('each per-level read sees the drawings',
                                                            [len(c['images']) for c in levels_calls]))
    check([s['id'] for s in tb.status(b)['steps']] == ['draft', 'draft_rooms', 'compose'],
          ('no extra steps: the fallback lives inside the draft step', [s['id'] for s in tb.status(b)['steps']]))
    house = _house(ts.current())
    _check_whole_house(house, 'per-level')
    logs = _logs(st)
    check(logs.count(ONE_FLOOR) == 1, ('the log says it once', [l for l in logs if 'floor at a time' in l]))
    raw = [line for line in logs if _has_raw_id(line, house)]
    check(not raw, ('no log line carries a raw piece id', raw))
    ghosts = [e for e in st['events'] if e['type'] == 'ghost' and e.get('step') == 'draft'
              and e.get('why') != 'First look at the outline while the drawings are read.']
    check(all(_plain(e.get('why'), house) for e in ghosts), ('each ghost has a plain why',
                                                             [e.get('why') for e in ghosts]))


def test_first_floor_failure_runs_per_level():
    _drawn_house()
    reader = FallbackReader(draft=_spike_open_first_floor())
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', ('a draft whose first floor fails is read one floor at a time',
                                  st['state'], st.get('pause'), _trouble(st), _draft_reads(reader)))
    check(_draft_reads(reader) == ['draft', 'draft_level L1', 'draft_level L2', 'draft_level roof', 'draft_rooms'],
          _draft_reads(reader))
    house = _house(ts.current())
    _check_whole_house(house, 'after a failed first floor')
    check(not any(w['level'] == 'L1' and w.get('exterior') and w.get('state') == 'ghost' for w in house['walls']),
          ('none of the failed draft\'s open first-floor walls stay behind',
           [(w['from'], w['to']) for w in house['walls'] if w['level'] == 'L1' and w.get('state') == 'ghost']))
    check(_logs(st).count(ONE_FLOOR) == 1, [l for l in _logs(st) if 'floor at a time' in l])
    check(not any(e['type'] == 'question' and e.get('text') == FAILED_WHY for e in st['events']),
          ('the fallback answered it, so the build never asked', _trouble(st)))


def test_fallback_level_context_has_lower_levels():
    _drawn_house()
    reader = FallbackReader()
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st), _draft_reads(reader)))
    calls = {_scope(c['context']): c['context'] for c in reader.seen if c['kind'] == 'draft_level'}
    check(set(calls) == {'L1', 'L2', 'roof'}, ('one read per level and one for the roof', list(calls)))
    for scope, context in calls.items():
        try:
            json.dumps(context)
        except (TypeError, ValueError) as exc:
            raise AssertionError(('the context goes to the model as JSON', scope, exc))
    first = _settled(calls['L1'])
    check(not first.get('levels'), ('the first floor is read with nothing settled below it', first.get('levels')))
    upper = _settled(calls['L2'])
    lower = upper.get('levels') or []
    check([l.get('id') for l in lower] == ['L1'], ('the upper floor is read with the settled first floor',
                                                  [l.get('id') for l in lower]))
    check(all(abs(a - b) <= 0.5 for a, b in zip(_bounds(lower[0].get('outline') or [[0, 0]]), [0, -1, 70, 65.33]))
          and abs(lower[0].get('elevation', 99)) <= 0.5,
          ('the settled first floor in feet, as read', lower[0]))
    if 'walls' in upper:
        check(upper['walls'] and all(w.get('level') == 'L1' for w in upper['walls']),
              ('only the lower level\'s walls go with it', {w.get('level') for w in upper['walls']}))
    roof = _settled(calls['roof'])
    check(sorted(l.get('id') for l in roof.get('levels') or []) == ['L1', 'L2'],
          ('the roof is read with all the levels', [l.get('id') for l in roof.get('levels') or []]))
    l2 = next(l for l in roof['levels'] if l.get('id') == 'L2')
    check(all(abs(a - b) <= 0.5 for a, b in zip(_bounds(l2.get('outline') or [[0, 0]]), [14.33, 13.33, 37, 52]))
          and abs(l2.get('elevation', 0) - 10.9) <= 0.5, ('the settled upper floor in feet, as read', l2))


def test_fallback_stops_and_pauses_on_empty_level():
    empty = {'building': {'levels': [], 'walls': []}, 'pages': [], 'checks': {}, 'notes': []}
    for name, broken, reads in (
            ('empty upper floor', 'L2', ['draft', 'draft_level L1', 'draft_level L2']),
            ('empty first floor', 'L1', ['draft', 'draft_level L1'])):
        _drawn_house()
        levels = per_level()
        levels[broken] = copy.deepcopy(empty)
        reader = FallbackReader(levels=levels)
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
        st = tb.status(b)
        check(st['state'] == 'paused', (name, 'a level with nothing usable pauses',
                                        st['state'], _trouble(st), _draft_reads(reader)))
        check(st['pause']['step'] == 'draft' and st['pause']['why'] == FAILED_WHY, (name, st['pause']))
        check(_draft_reads(reader) == reads, (name, 'it stops at the first level with nothing usable: '
                                              'no later level, no roof, no rooms', _draft_reads(reader)))
        # The pause survives a restart, as every paused build does.
        tb._forget()
        tb.recover()
        st = tb.status(b)
        check(st['state'] == 'paused' and st['pause']['step'] == 'draft', (name, 'after a restart', st['state'], st['pause']))
        # Try again rereads the drawings.
        good = FallbackReader(draft=spike())
        tb.reread(b, 'draft', reader=good, inline=True)
        st = tb.status(b)
        check(st['state'] == 'done', (name, 'Try again reads it again', st['state'], st.get('pause'), _trouble(st)))
        check(_draft_reads(good) == ['draft', 'draft_rooms'], (name, 'a whole draft needs no fallback',
                                                              _draft_reads(good)))
        house = _house(ts.current())
        l1 = [w for w in house['walls'] if w['level'] == 'L1' and w.get('exterior')]
        check(len(l1) == 22 and all(w.get('state') == 'settled' for w in l1), (name, [w.get('state') for w in l1]))


def test_fallback_failed_upper_floor_is_ghost_and_still_reads_roof():
    _drawn_house()
    levels = per_level()
    upper = levels['L2']['building']
    # The lower floor ends at x=70 here; this readable floor projects 3 ft.
    outline = [[14.33, 23], [73, 23], [73, 40], [14.33, 40]]
    upper['levels'][0]['outline'] = outline
    upper['walls'] = [{'id': f'upper-{i}', 'level': 'L2', 'from': a, 'to': b,
                       'height': 9, 'thickness': .5, 'exterior': True}
                      for i, (a, b) in enumerate(zip(outline, outline[1:] + outline[:1]))]
    upper['openings'] = []
    reader = FallbackReader(levels=levels)
    build = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(build)
    check(st['state'] == 'done' and not st.get('pause'), (st['state'], st.get('pause'), _trouble(st)))
    check(_draft_reads(reader) == ['draft', 'draft_level L1', 'draft_level L2', 'draft_level roof', 'draft_rooms'],
          _draft_reads(reader))
    house = _house(ts.current())
    upper = next(l for l in house['levels'] if l['id'] == 'L2')
    why = 'The upper floor extends more than 2 ft beyond the floor below.'
    check(upper.get('state') == 'ghost' and upper.get('why') == why, upper)
    walls = [w for w in house['walls'] if w['level'] == 'L2' and w.get('exterior')]
    check(len(walls) == 4 and all(w.get('state') == 'ghost' and w.get('why') == why for w in walls), walls)
    roof_context = next(c['context'] for c in reader.seen
                        if c['kind'] == 'draft_level' and _scope(c['context']) == 'roof')
    check([l['id'] for l in _settled(roof_context)['levels']] == ['L1'],
          ('only settled levels reach the next read', _settled(roof_context)))
    check(not any(e['type'] == 'question' for e in st['events']), _trouble(st))


def test_fallback_heartbeat_during_each_level_read():
    _drawn_house()
    reader = FallbackReader()
    now = [1000.0]
    observed = {}
    pattern = re.compile(r'^Reading the Main house drawings one floor at a time, (\d+):(\d\d) so far\.$')

    def blocked_read(kind, images, context, *, run, step):
        if kind == 'draft_level':
            start_seq = tb.status(run)['events'][-1]['seq']
            for elapsed in (15, 30, 45, 50):
                now[0] = 1000.0 + elapsed
                if elapsed != 50:
                    deadline = time.monotonic() + 1
                    while time.monotonic() < deadline:
                        beats = [e for e in tb.status(run)['events'] if e['seq'] > start_seq
                                 and e['type'] == 'log' and pattern.match(e.get('text') or '')]
                        if len(beats) >= elapsed // 15:
                            break
                        time.sleep(.01)
            observed[_scope(context)] = [e for e in tb.status(run)['events'] if e['seq'] > start_seq
                                        and e['type'] == 'log' and pattern.match(e.get('text') or '')]
            now[0] = 1000.0
        return reader(kind, images, context, run=run, step=step)

    with patch.object(tb, '_clock', lambda: now[0]):
        build = tb.start({'part': 'house'}, reader=blocked_read, inline=True)
    st = tb.status(build)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    check(set(observed) == {'L1', 'L2', 'roof'}, observed)
    house = _house(ts.current())
    for scope, beats in observed.items():
        check(len(beats) >= 3, (scope, '50 s blocked: at least three building-named heartbeats', beats))
        times = [int(m.group(1)) * 60 + int(m.group(2)) for m in (pattern.match(e['text']) for e in beats)]
        check(times == sorted(times) and 45 <= max(times) <= 50, (scope, times))
        check(all(e.get('step') == 'draft' and not _has_raw_id(e['text'], house) for e in beats), beats)


def test_fallback_floor_porch_columns_win_over_roof_reply():
    for field, shift in (('porch', 0), ('porches', .25)):
        _drawn_house()
        levels = per_level()
        floor_porch = levels['L1']['building']['porch']
        roof_porch = copy.deepcopy(floor_porch)
        roof_porch['columns'] = []
        roof_porch['polygon'] = [[x + shift, y] for x, y in roof_porch['polygon']]
        # A separate roof-only porch is still useful and must be kept.
        separate = {'polygon': [[80, 0], [90, 0], [90, 8], [80, 8]], 'floor': 0, 'columns': []}
        roof = levels['roof']['building']
        roof['porches'] = [separate]
        if field == 'porch':
            roof['porch'] = roof_porch
        else:
            roof['porches'].append(roof_porch)
        reader = FallbackReader(levels=levels)
        build = tb.start({'part': 'house'}, reader=reader, inline=True)
        st = tb.status(build)
        check(st['state'] == 'done', (field, st['state'], st.get('pause'), _trouble(st)))
        porches = tb.twin_plan.porches(_house(ts.current()))
        check(len(porches) == 2, (field, 'one floor porch and one distinct roof-only porch', porches))
        porch = next((p for p in porches if p['polygon'] == floor_porch['polygon']), None)
        check(porch is not None and porch.get('state') == 'settled'
              and porch['columns'] == floor_porch['columns'] and len(porch['columns']) == 4,
              (field, 'the floor read owns the four columns', porch))
        check(any(p['polygon'] == separate['polygon'] for p in porches), (field, porches))


def test_fallback_real_reader_checkpoint_already_checked():
    _drawn_house()
    reader = FallbackReader()
    options = []

    def real_read(kind, images, context, *, run, step, checkpoint_checked=False):
        if kind == 'draft_level':
            options.append((_scope(context), checkpoint_checked))
        return reader(kind, images, context, run=run, step=step)

    with patch.object(tb, '_REAL_READER', real_read):
        build = tb.start({'part': 'house'}, reader=real_read, inline=True)
    st = tb.status(build)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    check(options == [('L1', True), ('L2', True), ('roof', True)], options)


def test_rooms_read_settles_rooms_and_interior_walls():
    for name, draft in (('whole draft', spike()), ('one floor at a time', None)):
        _drawn_house()
        reader = FallbackReader(draft=draft, rooms={'rooms': [KITCHEN, STUDY], 'walls': [PARTITION_L1, PARTITION_L2]})
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
        st = tb.status(b)
        check(st['state'] == 'done', (name, st['state'], st.get('pause'), _trouble(st), _draft_reads(reader)))
        rooms_calls = [c for c in reader.seen if c['kind'] == 'draft_rooms']
        check(len(rooms_calls) == 1, (name, 'one rooms read', _draft_reads(reader)))
        check(_draft_reads(reader)[-1] == 'draft_rooms', (name, 'rooms are read after the draft settles',
                                                          _draft_reads(reader)))
        call = rooms_calls[0]
        check(len(call['images']) == 2, (name, 'the rooms read sees the two floor pages whole', len(call['images'])))
        settled = _settled(call['context'])
        check({'levels', 'walls', 'openings'} <= set(settled), (name, sorted(settled)))
        check(sorted(l.get('id') for l in settled['levels']) == ['L1', 'L2'],
              (name, 'with both settled levels', [l.get('id') for l in settled['levels']]))
        check(len(settled['walls']) >= 22 and all(w.get('exterior') for w in settled['walls'])
              and all(w.get('state') != 'ghost' for w in settled['walls']),
              (name, 'with the settled exterior walls', len(settled['walls'])))
        check({'L1', 'L2'} <= {w.get('level') for w in settled['walls']},
              (name, 'from both levels', {w.get('level') for w in settled['walls']}))
        check(len(settled['openings']) >= 18, (name, 'with the settled openings', len(settled['openings'])))

        house = _house(ts.current())
        rooms = {r['name']: r for r in house['rooms'] if r.get('src', {}).get('step') == 'draft_rooms'}
        check(set(rooms) == {'Kitchen', 'Study'}, (name, 'both rooms are in the plan', list(rooms)))
        for room, given in ((rooms['Kitchen'], KITCHEN), (rooms['Study'], STUDY)):
            check(room.get('state') == 'settled' and room['level'] == given['level']
                  and room['polygon'] == given['polygon'], (name, 'each room settles in feet as is', room))
        walls = [w for w in house['walls'] if w.get('src', {}).get('step') == 'draft_rooms']
        check(len(walls) == 2 and all(w.get('state') == 'settled' and not w.get('exterior') for w in walls),
              (name, 'both interior walls settle', walls))
        got = {(w['level'], tuple(w['from']), tuple(w['to'])) for w in walls}
        check(got == {('L1', (10, 15), (10, 25)), ('L2', (23, 16), (23, 30))}, (name, 'walls in feet as is', got))
        events = [e for e in st['events'] if e['type'] == 'settled' and e.get('step') == 'draft_rooms']
        pieces = [p for e in events for p in e.get('pieces', [])]
        check(len([p for p in pieces if 'polygon' in p and p.get('name') in ('Kitchen', 'Study')]) == 2
              and len([p for p in pieces if 'from' in p and 'to' in p]) == 2,
              (name, 'the rooms and walls settle in the rooms step', len(pieces)))


def test_room_outside_outline_is_ghost():
    _drawn_house()
    # Inside the first floor but outside the upper floor (which ends at x = 37).
    stray_room = {'name': 'Loft', 'level': 'L2', 'polygon': [[50, 30], [56, 30], [56, 36], [50, 36]]}
    stray_l2 = {'id': 'p3', 'level': 'L2', 'from': [50, 30], 'to': [56, 30],
                'height': 8, 'thickness': 0.33, 'exterior': False}
    # Outside the first floor (which ends at x = 70).
    stray_l1 = {'id': 'p4', 'level': 'L1', 'from': [80, 30], 'to': [90, 30],
                'height': 9, 'thickness': 0.33, 'exterior': False}
    reader = FallbackReader(draft=spike(), rooms={'rooms': [KITCHEN, stray_room],
                                                  'walls': [PARTITION_L1, stray_l2, stray_l1]})
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', ('a stray room never pauses', st['state'], st.get('pause'), _trouble(st)))
    house = _house(ts.current())
    rooms = {r['name']: r for r in house['rooms'] if r.get('src', {}).get('step') == 'draft_rooms'}
    check(rooms.get('Kitchen', {}).get('state') == 'settled', ('the room inside settles', rooms.get('Kitchen')))
    loft = rooms.get('Loft')
    check(loft is not None and loft.get('state') == 'ghost', ('the room outside its level stays, as a ghost', loft))
    check(_plain(loft.get('why'), house), ('with a plain why', loft.get('why')))
    walls = {(w['level'], tuple(w['from'])): w for w in house['walls'] if w.get('src', {}).get('step') == 'draft_rooms'}
    inside = walls.get(('L1', (10, 15)))
    check(inside is not None and inside.get('state') == 'settled', ('the partition inside settles', inside))
    for key in (('L2', (50, 30)), ('L1', (80, 30))):
        wall = walls.get(key)
        check(wall is not None and wall.get('state') == 'ghost', ('a wall outside its level stays, as a ghost', key, wall))
        check(_plain(wall.get('why'), house), ('with a plain why', key, wall.get('why')))
    ghost_ids = {loft['id']} | {w['id'] for k, w in walls.items() if k != ('L1', (10, 15))}
    events = [e for e in st['events'] if e['type'] == 'ghost' and e.get('step') == 'draft_rooms']
    check(ghost_ids <= {(e.get('piece') or {}).get('id') for e in events},
          ('a ghost event for each stray piece', [e.get('piece') for e in events]))
    check(all(_plain(e.get('why'), house) for e in events), [e.get('why') for e in events])
    settled = [p for e in st['events'] if e['type'] == 'settled' and e.get('step') == 'draft_rooms'
               for p in e.get('pieces', [])]
    check(not any(p.get('id') in ghost_ids for p in settled), 'a ghost is never in the settled event')
    raw = [line for line in _logs(st) if _has_raw_id(line, house)]
    check(not raw, ('no log line carries a raw piece id', raw))


def test_rooms_reply_without_walls_settles_rooms():
    _drawn_house()
    reader = FallbackReader(draft=spike(), rooms={'rooms': [KITCHEN, STUDY]})
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    house = _house(ts.current())
    rooms = {r['name']: r for r in house['rooms'] if r.get('src', {}).get('step') == 'draft_rooms'}
    check(set(rooms) == {'Kitchen', 'Study'}, ('a reply with no interior walls still settles its rooms',
                                               [r.get('name') for r in house['rooms']]))
    check(all(r.get('state') == 'settled' for r in rooms.values()), [r.get('state') for r in rooms.values()])
    check(not [w for w in house['walls'] if w.get('src', {}).get('step') == 'draft_rooms'],
          'no interior walls were read, so none settle')
    rooms_logs = [e.get('text') for e in st['events'] if e['type'] == 'log' and e.get('step') == 'draft_rooms']
    check('Some parts of this drawing need checking.' not in rooms_logs,
          ('a reply without interior walls is a whole answer, not a problem', rooms_logs))


def test_empty_whole_draft_uses_per_floor_fallback():
    _drawn_house()
    reader = FallbackReader(draft={'building': {'levels': []}})
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    check(tb.status(b)['state'] == 'done', tb.status(b))
    check(_draft_reads(reader) == ['draft', 'draft_level L1', 'draft_level L2', 'draft_level roof', 'draft_rooms'],
          _draft_reads(reader))


def test_fallback_heartbeat_uses_one_start_time_across_floors():
    _drawn_house()
    reader = FallbackReader()
    now, starts = [1000.0], []
    original = tb._start_draft_heartbeat
    def heartbeat(*args, **kwargs):
        if args[-1] == 'one floor at a time':
            starts.append(kwargs['started'])
        return original(*args, **kwargs)
    def read(kind, images, context, **kwargs):
        if kind == 'draft_level':
            now[0] += 45
        return reader(kind, images, context, **kwargs)
    with patch.object(tb, '_clock', lambda: now[0]), patch.object(tb, '_start_draft_heartbeat', side_effect=heartbeat):
        b = tb.start({'part': 'house'}, reader=read, inline=True)
    check(tb.status(b)['state'] == 'done', tb.status(b))
    check(starts == [1000.0, 1000.0, 1000.0], starts)


def test_draft_read_error_names_the_drawings():
    _drawn_house()
    b = tb.start({'part': 'house'}, reader=FallbackReader(draft={'error': 'read timed out'}), inline=True)
    st = tb.status(b)
    check(st['state'] == 'stopped', st)
    lines = [e['text'] for e in st['events'] if e['type'] == 'question' and e.get('step') == 'draft']
    check(lines == ['The drawings could not be read.'], lines)


TESTS = (
    test_empty_whole_draft_uses_per_floor_fallback,
    test_fallback_heartbeat_uses_one_start_time_across_floors,
    test_draft_read_error_names_the_drawings,
    test_truncated_draft_runs_per_level,
    test_first_floor_failure_runs_per_level,
    test_fallback_level_context_has_lower_levels,
    test_fallback_stops_and_pauses_on_empty_level,
    test_fallback_failed_upper_floor_is_ghost_and_still_reads_roof,
    test_fallback_heartbeat_during_each_level_read,
    test_fallback_floor_porch_columns_win_over_roof_reply,
    test_fallback_real_reader_checkpoint_already_checked,
    test_rooms_read_settles_rooms_and_interior_walls,
    test_room_outside_outline_is_ghost,
    test_rooms_reply_without_walls_settles_rooms,
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
