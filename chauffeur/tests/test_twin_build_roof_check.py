"""A roof check after the draft (brief
.superpowers/sdd/2026-11-08-house-editor-whole-building-draft/task-12-brief.md;
spec docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md
section 2b).

The recorded main-house draft made the two-storey centre block r_main a gable
with ridge y and has no dormer; the photo and roof plan show a hip with its
ridge side to side and a front gable dormer. After the draft read (and after
the per-level fallback when it ran) and before the draft settles, the draft
step makes one more read, 'roof_check', and applies its corrections to the
draft fragment's roof before normalize, snap and the checks:

- {changes:[{id:"r_main", kind:"hip", ridge:"x"}], add:[r_dormer]} settles
  r_main as a hip with ridge x and the dormer as its own settled section; the
  reads go draft, roof_check, draft_rooms; while the roof check runs a log line
  "Checking the roof of the <building name> drawings, M:SS so far." goes out
  (on the injectable clock twin_build._clock).
- A section whose settled piece a person edited (src.person) is never changed
  or removed by a correction that names it; a reread of the draft reruns the
  roof check.
- A failed roof check leaves the roof as first read, logs one plain line "The
  roof could not be double-checked; it is shown as first read." and never
  pauses the build.

The reader is a stub keyed by kind (its first argument), built on
test_twin_build's fake like test_twin_build_draft_replay.py: 'draft' answers
the recorded main-house fragment, 'draft_rooms' answers no rooms, 'outline'
answers an error (the quick first look is disposable), 'finishes' answers an
empty materials answer, 'roof_check' answers the test's corrections (or runs a
hook that may block, raise or answer).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_roof_check.py
"""
import copy
import io
import json
import os
import re
import sys
import tempfile
import time
import traceback

# Always a scratch data dir (the engine harness wipes its data dir); keep one
# an importing test module already made.
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_roof_check_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _accept_all, _pdf, check  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
NOT_CHECKED = 'The roof could not be double-checked; it is shown as first read.'
ROOF_BEAT = re.compile(r'^Checking the roof of the Main house drawings, (\d+):(\d\d) so far\.$')
NO_CORRECTIONS = {'changes': [], 'add': [], 'remove': [], 'notes': []}
DORMER = {'id': 'r_dormer', 'kind': 'gable', 'ridge': 'y', 'rect': [22.67, 13.33, 37.33, 26],
          'plate': 20, 'pitch': 12, 'overhang': 1}
CORRECTIONS = {'changes': [{'id': 'r_main', 'kind': 'hip', 'ridge': 'x'}], 'add': [copy.deepcopy(DORMER)],
               'remove': [], 'notes': ['The centre block is a hip with a front gable dormer.']}
READS = ('draft', 'draft_level', 'roof_check', 'draft_rooms')


# --- fixtures, reader and helpers ----------------------------------------------

def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


def recorded_sections():
    return {s['id']: s for s in recorded('draft-main-house.json')['building']['roof']['sections']}


class RoofReader(Reader):
    """Answers the recorded main-house draft by kind, and the roof check with
    the given answer, or with roof_hook(run, images, context) when one is set
    (it may block, raise, or return a replacement answer)."""

    def __init__(self, roof_answer=None, roof_hook=None):
        super().__init__()
        self.draft = recorded('draft-main-house.json')
        self.roof_answer = copy.deepcopy(NO_CORRECTIONS if roof_answer is None else roof_answer)
        self.roof_hook = roof_hook
        self.kinds = []
        self.seen = []

    def __call__(self, kind, images, context, *, run, step):
        self.kinds.append(kind)
        self.seen.append({'kind': kind, 'step': step, 'images': len(images), 'context': copy.deepcopy(context)})
        if kind in ('draft', 'draft_level'):
            return copy.deepcopy(self.draft)
        if kind == 'draft_rooms':
            return {'rooms': [], 'walls': []}
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}
        if kind == 'finishes':
            return {'materials': {}}
        if kind == 'roof_check':
            answer = self.roof_hook(run, images, context) if self.roof_hook else None
            return copy.deepcopy(self.roof_answer if answer is None else answer)
        return super().__call__(kind, images, context, run=run, step=step)


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (90, 120, 160)).save(buf, format='JPEG')
    return buf.getvalue()


def _main_house():
    """The Main house as the household set it up: two floor pages, a roof
    page and one tagged photo."""
    engine_tests._fresh()
    source = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 2, 'role': 'floor', 'level': 'Second floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    ts.save_source('photo', 'house.jpg', _jpeg(), part='house')
    return source


def _house():
    return next(b for b in ts.current()['buildings'] if b['id'] == 'house')


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _read_rect(section):
    return (section.get('read_geometry') or {}).get('rect') or section['rect']


def _at(house, rect, tol=0.05):
    """Roof sections read at rect (each coordinate within tol ft)."""
    return [s for s in house['roof']['sections']
            if all(abs(a - b) <= tol for a, b in zip(_read_rect(s), rect))]


def _roof(house):
    return sorted((s['kind'], s.get('ridge'), s.get('low_side'), [round(v, 2) for v in _read_rect(s)],
                   s.get('state')) for s in house['roof']['sections'])


def _order(reader):
    return [k for k in reader.kinds if k in READS]


def _build(reader):
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', ('the build finishes', st['state'], st.get('pause'), _trouble(st)))
    return b, st


def _roof_as_read(house, why):
    """Every recorded section is in the plan, settled, with its read kind and ridge."""
    wanted = recorded_sections()
    for sid, section in wanted.items():
        found = _at(house, section['rect'])
        check(len(found) == 1, (why, sid, 'is in the plan once', len(found), _roof(house)))
        got = found[0]
        check(got.get('state') != 'ghost', (why, sid, 'settles', got.get('why')))
        check((got['kind'], got.get('ridge'), got.get('low_side'))
              == (section['kind'], section.get('ridge'), section.get('low_side')),
              (why, sid, 'keeps the kind and ridge it was read with',
               (got['kind'], got.get('ridge'), got.get('low_side')), section))
    check(len(house['roof']['sections']) == len(wanted),
          (why, 'no section added or lost', len(house['roof']['sections']), _roof(house)))


# Background builds (copied from test_twin_build_draft_side.py).

def _events(run):
    """The build's events without the lock, safe from inside a reader call."""
    build = tb._BUILDS.get(run)
    return list(build['events']) if build else []


def _draft_settled(events):
    return [e for e in events if e['type'] == 'settled' and e.get('step') == 'draft']


def _wait(predicate, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _rest(b, timeout=60):
    """Wait until the build leaves running and its worker is no longer busy."""
    ok = _wait(lambda: tb.status(b)['state'] != 'running' and not tb._WORKERS.get(b, {}).get('busy'), timeout)
    check(ok, ('the build came to rest', tb.status(b)['state']))
    return tb.status(b)


def _finish(b, limit=20):
    for _ in range(limit):
        st = _rest(b)
        if st['state'] != 'paused':
            return st
        tb.answer(b, st['pause']['step'], {'accept': True})
    raise AssertionError('too many pauses')


def _fake_clock():
    now = [1000.0]
    saved = tb.__dict__.get('_clock', None)
    tb._clock = lambda: now[0]
    return now, saved


def _restore_clock(saved):
    if saved is None:
        tb.__dict__.pop('_clock', None)
    else:
        tb._clock = saved


# --- tests ---------------------------------------------------------------------

def test_corrections_settle_hip_and_dormer():
    wanted = recorded_sections()
    check(wanted['r_main']['kind'] == 'gable' and wanted['r_main']['ridge'] == 'y' and 'r_dormer' not in wanted,
          ('test setup: the recorded centre block is a front gable with no dormer', wanted['r_main']))
    _main_house()
    reader = RoofReader(CORRECTIONS)
    _, st = _build(reader)
    check(reader.kinds.count('roof_check') == 1, ('one roof check read', reader.kinds))
    house = _house()

    main = _at(house, wanted['r_main']['rect'])
    check(len(main) == 1, ('the centre block is one section', _roof(house)))
    check(main[0]['kind'] == 'hip' and main[0].get('ridge') == 'x',
          ('r_main settles as a hip with its ridge side to side', main[0]['kind'], main[0].get('ridge')))
    check(main[0].get('state') != 'ghost', ('the corrected centre block settles', main[0].get('why')))

    dormer = _at(house, DORMER['rect'])
    check(len(dormer) == 1, ('the added dormer is its own section', _roof(house)))
    d = dormer[0]
    check(d['kind'] == 'gable' and d.get('ridge') == 'y' and abs(d['plate'] - 20) <= 0.01,
          ('the dormer is a gable, ridge toward the main ridge, at the upper plate',
           d['kind'], d.get('ridge'), d['plate']))
    check(d.get('state') != 'ghost', ('the dormer settles', d.get('why')))
    check(d.get('src', {}).get('step') == 'draft', ('the dormer is part of the draft', d.get('src')))

    # Every other section is left as read.
    for sid, section in wanted.items():
        if sid == 'r_main':
            continue
        found = _at(house, section['rect'])
        check(len(found) == 1 and found[0]['kind'] == section['kind']
              and found[0].get('ridge') == section.get('ridge') and found[0].get('state') != 'ghost',
              (sid, 'a section the check does not name is left as read', [(s['kind'], s.get('ridge'), s.get('state'))
                                                                         for s in found]))
    check(len(house['roof']['sections']) == len(wanted) + 1, ('ten read sections and the dormer', _roof(house)))
    check(not [e for e in st['events'] if e['type'] == 'log' and e.get('text') == NOT_CHECKED],
          'a roof check that answered is not reported as failed')


def test_roof_check_between_draft_and_rooms():
    _main_house()
    reader = RoofReader(CORRECTIONS)
    _build(reader)
    check(_order(reader) == ['draft', 'roof_check', 'draft_rooms'],
          ('the reads go draft, roof_check, draft_rooms', reader.kinds))
    call = next(c for c in reader.seen if c['kind'] == 'roof_check')
    check(call['step'] == 'draft', ('the roof check runs inside the draft step', call['step']))
    # Images: the roof page and the tagged photo (no floor pages, no elevations here).
    check(call['images'] == 2, ('the roof check sees the roof page and the photo', call['images']))
    context = call['context']
    check((context.get('building') or {}).get('name') == 'Main house',
          ('the roof check context names the building', context.get('building')))
    sections = context.get('sections')
    check(isinstance(sections, list), ('the read roof sections go in context["sections"]', sorted(context)))
    wanted = recorded_sections()
    check(sorted(s.get('id') for s in sections) == sorted(wanted),
          ('every read section is offered by its draft id', [s.get('id') for s in sections]))
    for section in sections:
        source = wanted[section['id']]
        for field in ('kind', 'rect', 'plate', 'pitch', 'overhang'):
            check(section.get(field) == source[field],
                  (section['id'], field, 'is given as read', section.get(field), source[field]))
        check(section.get('ridge') == source.get('ridge') and section.get('low_side') == source.get('low_side'),
              (section['id'], 'ridge and low side as read', section))
    levels = context.get('levels')
    check(isinstance(levels, list) and len(levels) == 2
          and all(isinstance(l.get('outline'), list) and 'elevation' in l for l in levels),
          ('each level\'s outline and elevation go in the context', levels))


def test_roof_check_heartbeat():
    _main_house()
    now, saved = _fake_clock()
    try:
        def roof_hook(run, images, context):
            # The roof check is blocked for 20 s on the fake clock; at the 15 s
            # mark give the heartbeat a moment (real time) to go out.
            for elapsed in range(1, 21):
                now[0] += 1.0
                if elapsed == 15:
                    _wait(lambda: any(e['type'] == 'log' and ROOF_BEAT.match(e.get('text') or '')
                                      for e in _events(run)), 5)
                else:
                    time.sleep(0.005)
            return None

        reader = RoofReader(NO_CORRECTIONS, roof_hook=roof_hook)
        b = tb.start({'part': 'house'}, reader=reader, inline=False)
        st = _finish(b)
    finally:
        _restore_clock(saved)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    check(reader.kinds.count('roof_check') == 1, ('test setup: the roof check was read', reader.kinds))
    events = tb.status(b)['events']
    beats = [e for e in events if e['type'] == 'log' and ROOF_BEAT.match(e.get('text') or '')]
    logs = [e.get('text') for e in events if e['type'] == 'log']
    check(beats, ('20 s of roof check: a heartbeat line naming the building', logs))
    times = [int(m.group(1)) * 60 + int(m.group(2)) for m in (ROOF_BEAT.match(e['text']) for e in beats)]
    check(all(15 <= t <= 21 for t in times), ('M:SS counts the roof check so far', [e['text'] for e in beats]))
    check(all(e.get('step') == 'draft' for e in beats), ('the heartbeat belongs to the draft step', beats))
    settled = _draft_settled(events)
    check(settled and all(e['seq'] < settled[0]['seq'] for e in beats),
          ('the heartbeat runs before the draft settles', [e['seq'] for e in beats], settled[:1]))


def test_person_edited_section_left_alone():
    wanted = recorded_sections()
    _main_house()
    b, _ = _build(RoofReader(NO_CORRECTIONS))
    house = _house()
    mine = {}
    for sid in ('r_main', 'r_left'):
        found = _at(house, wanted[sid]['rect'])
        check(len(found) == 1, ('test setup: the read section settled', sid, _roof(house)))
        twin_edit.save({'op': 'set', 'building': 'house', 'piece': found[0]['id'], 'field': 'pitch', 'value': 6}, 'p1')
        mine[sid] = found[0]['id']
    house = _house()
    for sid, pid in mine.items():
        piece = next(s for s in house['roof']['sections'] if s['id'] == pid)
        check((piece.get('src') or {}).get('person') and piece['pitch'] == 6,
              ('test setup: the person edited the section', sid, piece.get('src'), piece['pitch']))

    # The roof check names both: it would turn r_main into a smaller hip and
    # remove r_left. It also corrects r_garage, which nobody edited.
    shrunk = [14.33, 13.33, 37.33, 46]
    answer = {'changes': [{'id': 'r_main', 'kind': 'hip', 'ridge': 'x', 'rect': shrunk},
                          {'id': 'r_garage', 'kind': 'hip'}],
              'add': [], 'remove': ['r_left'], 'notes': []}
    reader = RoofReader(answer)
    tb.reread(b, 'draft', reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', ('the reread finishes', st['state'], st.get('pause'), _trouble(st)))
    check(reader.kinds.count('roof_check') == 1, ('a reread of the draft reruns the roof check', reader.kinds))
    house = _house()
    by_id = {s['id']: s for s in house['roof']['sections']}

    for sid, kind, ridge in (('r_main', 'gable', 'y'), ('r_left', 'gable', 'x')):
        piece = by_id.get(mine[sid])
        check(piece is not None, (sid, 'a person-edited section is never removed', _roof(house)))
        check(piece['kind'] == kind and piece.get('ridge') == ridge and piece['pitch'] == 6
              and (piece.get('src') or {}).get('person'),
              (sid, 'a person-edited section is never changed', piece['kind'], piece.get('ridge'),
               piece['pitch'], piece.get('src')))
        check(all(abs(a - b) <= 0.05 for a, b in zip(_read_rect(piece), wanted[sid]['rect'])),
              (sid, 'it keeps its place', _read_rect(piece)))
        check([s['id'] for s in _at(house, wanted[sid]['rect'], tol=1.0)] == [mine[sid]],
              (sid, 'no second section beside the person\'s', _roof(house)))
    check(not _at(house, shrunk, tol=0.5), ('the correction to the person\'s section is not added beside it',
                                            _roof(house)))
    garage = _at(house, wanted['r_garage']['rect'])
    check(len(garage) == 1 and garage[0]['kind'] == 'hip',
          ('a correction to a section nobody edited still applies', [(s['kind'], s.get('ridge')) for s in garage]))


def test_roof_check_failure_keeps_roof():
    def error_reply(run, images, context):
        return {'error': 'The model did not answer in 240 s.'}

    def raises(run, images, context):
        raise RuntimeError('the roof check broke')

    for name, hook in (('error reply', error_reply), ('raises', raises)):
        _main_house()
        reader = RoofReader(roof_hook=hook)
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
        st = tb.status(b)
        check(reader.kinds.count('roof_check') == 1, (name, 'test setup: the roof check was read', reader.kinds))
        check(st['state'] == 'done', (name, 'a failed roof check never pauses or stops the build',
                                      st['state'], st.get('pause'), _trouble(st)))
        check(not _trouble(st), (name, 'no error and no question', _trouble(st)))
        lines = [e for e in st['events'] if e['type'] == 'log' and e.get('text') == NOT_CHECKED]
        check(len(lines) == 1, (name, 'one plain line says the roof was not double-checked',
                                [e.get('text') for e in st['events'] if e['type'] == 'log']))
        check(lines[0].get('step') == 'draft', (name, 'the line belongs to the draft step', lines[0]))
        check(_order(reader) == ['draft', 'roof_check', 'draft_rooms'], (name, 'the rooms read still runs', reader.kinds))
        _roof_as_read(_house(), name)


TESTS = (
    test_corrections_settle_hip_and_dormer,
    test_roof_check_between_draft_and_rooms,
    test_roof_check_heartbeat,
    test_person_edited_section_left_alone,
    test_roof_check_failure_keeps_roof,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
