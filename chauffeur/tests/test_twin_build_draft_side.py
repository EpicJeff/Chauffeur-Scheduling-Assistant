"""Around the draft read: a quick outline ghost, a heartbeat and page anchors
(plan docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md,
Task 8; spec docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md
section 1 "Running two reads at once", section 2 "Level ids and sheet
registrations", section 7; controller ruling R13 puts these tests here).

- The draft step starts the existing outline read of the first floor page on
  a side thread before the draft call. Its outline lands as one ghost event per
  edge, why "First look at the outline while the drawings are read.", before
  the draft settles. It never settles anything, and it is dropped when it fails
  or lands after the draft.
- The cost checkpoint is checked once before the step (ruling R14: one
  twin_cost.require_clear() before either read, existing semantics), and the
  step carries step['estimate'] = estimate('draft', n) + estimate('outline', 1).
- While the draft call runs, a log line goes out at least every 15 s:
  "Reading the <building name> drawings as one set, M:SS so far.", on the
  injectable clock twin_build._clock.
- Each draft answer page with two or more valid anchors gets a registration
  fitted through twin_store.crop_to_master and twin_register.from_points;
  bad or too few anchors give no registration and no error.

The reader is a stub keyed by kind (its first argument), built on
test_twin_build's fake. The draft answer is the recorded whole-building spike
answer, in feet.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_draft_side.py
"""
import copy
import io
import json
import math
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_build_draft_side_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_register  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _pdf, check  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
SPIKE_PATH = os.path.join(RECORDED, 'draft-main-spike-answer.json')
FULL = [0, 0, 1, 1]
FIRST_LOOK = 'First look at the outline while the drawings are read.'
HEARTBEAT = re.compile(r'^Reading the Main house drawings as one set, (\d+):(\d\d) so far\.$')
# Paper sizes in points, one per page, so every whole-page image differs.
SIZES = [(1224, 792), (1008, 792), (792, 612)]
LEVEL_IDS = {'Main floor': 'L1', 'Upper floor': 'L2'}
# Outline corners of each level in the spike answer (feet).
CORNERS = {'L1': [[0, 14.33], [70, 22], [59, 65.33], [0, 54]],
           'L2': [[14.33, 14.33], [37, 13.33], [37, 52], [14.33, 52]]}
OUTLINE_EDGES = 4   # test_twin_build's fake outline answer is a 4-corner L1


# --- fakes and helpers (copied from test_twin_build_draft.py, plus hooks) -------

def spike():
    with open(SPIKE_PATH, encoding='utf-8') as f:
        return json.load(f)


class SideReader(Reader):
    """test_twin_build's fake plus the draft kinds, with hooks:

    - 'draft' answers the spike (or a given answer), after draft_hook(run,
      images, context) runs on the calling thread; a hook that returns a dict
      answers that instead.
    - 'draft_level' answers the same answer; 'draft_rooms' answers nothing.
    - 'outline' runs outline_hook(run) first (it may block, raise or return a
      replacement answer), then answers test_twin_build's 4-corner outline.
    """

    def __init__(self, answer=None, rooms=None, draft_hook=None, outline_hook=None):
        super().__init__()
        self.answer = spike() if answer is None else answer
        self.rooms = {'rooms': [], 'walls': []} if rooms is None else rooms
        self.draft_hook, self.outline_hook = draft_hook, outline_hook
        self.seen = []
        self.threads = {}
        self.draft_started = threading.Event()
        self.draft_returned = threading.Event()
        self.outline_answering = threading.Event()
        self.outline_returned = threading.Event()

    def __call__(self, kind, images, context, *, run, step):
        self.seen.append({'kind': kind, 'step': step, 'images': copy.deepcopy(images),
                          'context': copy.deepcopy(context), 'run': run})
        self.threads.setdefault(kind, threading.get_ident())
        if kind == 'draft':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            self.draft_started.set()
            try:
                answer = self.draft_hook(run, images, context) if self.draft_hook else None
                return copy.deepcopy(self.answer if answer is None else answer)
            finally:
                self.draft_returned.set()
        if kind == 'draft_level':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.answer)
        if kind == 'draft_rooms':
            self.calls.append({'kind': kind, 'step': step, 'context': copy.deepcopy(context), 'images': len(images)})
            return copy.deepcopy(self.rooms)
        if kind == 'outline':
            try:
                replacement = self.outline_hook(run) if self.outline_hook else None
                answer = super().__call__(kind, images, context, run=run, step=step)
                self.outline_answering.set()
                return answer if replacement is None else replacement
            finally:
                self.outline_returned.set()
        return super().__call__(kind, images, context, run=run, step=step)


def _read_kinds(reader):
    return [c['kind'] for c in reader.calls]


def _house(plan, bid='house'):
    return next(b for b in plan['buildings'] if b['id'] == bid)


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _sized_pdf(sizes):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for w, h in sizes:
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _drawn_house(*, sized=False):
    """Main house drawings: floor pages Main floor and Upper floor and a roof
    page, no photos, no lot. Sized pages give every page its own image."""
    engine_tests._fresh()
    data = _sized_pdf(SIZES) if sized else _pdf(3)
    sheets = ts.save_source('drawing', 'house.pdf', data)   # legacy upload: Main house, id house
    ts.set_page_roles([
        {'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': sheets, 'page': 2, 'role': 'floor', 'level': 'Upper floor', 'box': None, 'building': 'house'},
        {'source': sheets, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    return sheets


def _events(run):
    """The build's events without the lock, safe from inside a reader call."""
    build = tb._BUILDS.get(run)
    return list(build['events']) if build else []


def _first_look(events):
    return [e for e in events if e['type'] == 'ghost' and e.get('why') == FIRST_LOOK]


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


def _spend_to(usd):
    """Put usd of earlier spend in the ledger (Opus input at $4 per million)."""
    tc.record('earlier', [{'model': 'anthropic:claude-opus-5-5', 'input_tokens': round(usd / 4 * 1e6),
                           'output_tokens': 0}])
    check(abs(tc.total() - usd) < 1e-4, ('test setup: the ledger holds the earlier spend', tc.total(), usd))


def _page_of(sheets, b64):
    for page in (1, 2, 3):
        if ts.crop(sheets, page, FULL, max_side=2576)['b64'] == b64:
            return page
    return None


def _truth(master, level, angle):
    """A sheet registration that lays the level's outline inside the page."""
    width, height = master
    outline = next(l['outline'] for l in spike()['building']['levels'] if l['id'] == level)
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    scale = max((max(xs) - min(xs)) / (0.5 * width), (max(ys) - min(ys)) / (0.5 * height))
    return twin_register.make(scale, angle, origin_px=[0.25 * width, 0.75 * height], offset=[min(xs), min(ys)])


def _anchored_answer(sheets, images, context):
    """The spike answer plus a pages entry per floor page, anchors at four
    outline corners mapped through a known registration per page. Returns
    (answer, {page: (level, crop, anchors)})."""
    answer = spike()
    entries = context.get('pages') or []
    indexes = [e.get('image') for e in entries]
    base = min(indexes) if indexes and all(type(i) is int for i in indexes) else 0
    expected, pages = {}, []
    for entry in entries:
        if entry.get('role') != 'floor' or entry.get('level_name') not in LEVEL_IDS:
            continue
        level = LEVEL_IDS[entry['level_name']]
        page = _page_of(sheets, images[entry['image'] - base]['b64'])
        crop = ts.crop(sheets, page, FULL, max_side=2576)
        truth = _truth(crop['master'], level, 0.0 if level == 'L1' else 2.0)
        anchors = []
        for at in CORNERS[level]:
            px = twin_register.invert(truth, at)
            uv = [px[0] / crop['master'][0], px[1] / crop['master'][1]]
            check(all(0.02 < c < 0.98 for c in uv), ('test setup: anchors inside the image', level, uv))
            anchors.append({'px': uv, 'at': list(at)})
        pages.append({'image': entry['image'], 'level': level, 'anchors': anchors})
        expected[page] = (level, crop, anchors)
    answer['pages'] = pages
    return answer, expected


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

def test_outline_ghost_first():
    _drawn_house()
    reader = SideReader()
    seen = {}

    def outline_hook(run):
        # The outline read runs alongside the draft: wait for the draft call.
        seen['alongside'] = reader.draft_started.wait(5)

    def draft_hook(run, images, context):
        # The draft blocks until the outline has answered and its ghost is out.
        seen['outline_answered'] = reader.outline_answering.wait(10)
        seen['ghost_during_draft'] = _wait(lambda: len(_first_look(_events(run))) >= OUTLINE_EDGES, 3)

    reader.outline_hook, reader.draft_hook = outline_hook, draft_hook
    b = tb.start({'part': 'house'}, reader=reader, inline=False)
    st = _finish(b)
    reader.outline_returned.wait(10)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    kinds = _read_kinds(reader)
    check(kinds.count('draft') == 1, ('one draft read', kinds))
    outline_calls = [c for c in reader.seen if c['kind'] == 'outline']
    check(len(outline_calls) == 1, ('one quick outline read', [c['kind'] for c in reader.seen]))
    check(len(outline_calls[0]['images']) == 1, ('the outline read sees the first floor page', len(outline_calls[0]['images'])))
    check(seen.get('alongside'), ('the outline read runs while the draft read is in flight', seen))
    check(reader.threads['outline'] != reader.threads['draft'], 'the outline read runs on a side thread')
    check(seen.get('outline_answered'), ('the outline answered before the draft returned', seen))

    events = tb.status(b)['events']
    ghosts = _first_look(events)
    settled = _draft_settled(events)
    check(len(ghosts) == OUTLINE_EDGES, ('one ghost event per outline edge', len(ghosts),
                                         [e for e in events if e['type'] == 'ghost'][:3]))
    check(len(settled) == 1, ('the draft settles once', len(settled)))
    check(all(g['seq'] < settled[0]['seq'] for g in ghosts),
          ('the outline ghost comes before the draft settles', [g['seq'] for g in ghosts], settled[0]['seq']))
    # It never settles anything.
    plan = ts.current()
    check(FIRST_LOOK not in json.dumps(plan), 'the first-look outline never lands in the plan')
    house = _house(plan)
    check(all((w.get('src') or {}).get('step') in ('draft', 'draft_rooms') for w in house['walls']),
          ('every wall comes from the draft, none from the quick outline',
           sorted({(w.get('src') or {}).get('step') for w in house['walls']}, key=str)))


def test_outline_late_dropped():
    # Lands after the draft: the draft returns at once, the outline waits for
    # the draft to settle (or 5 s, if the engine wrongly waits for it).
    _drawn_house()
    reader = SideReader()

    def late(run):
        reader.draft_returned.wait(10)
        _wait(lambda: bool(_draft_settled(_events(run))), 5)

    reader.outline_hook = late
    b = tb.start({'part': 'house'}, reader=reader, inline=False)
    st = _finish(b)
    check(reader.outline_returned.wait(15), 'test setup: the outline read was made and returned')
    time.sleep(0.5)   # room for a wrongly late ghost to arrive
    st = tb.status(b)
    check(st['state'] == 'done', ('a late outline never holds the build up', st['state'], st.get('pause'), _trouble(st)))
    check(not _first_look(st['events']), ('a late outline is dropped', _first_look(st['events'])[:2]))
    check(not _trouble(st), ('dropped silently', _trouble(st)))
    check(FIRST_LOOK not in json.dumps(ts.current()), 'nothing of the late outline in the plan')

    # Fails: an unsuccessful reply, or a reader that raises.
    def error_reply(run):
        return {'error': 'The model did not answer in 120 s.'}

    def raises(run):
        raise RuntimeError('the outline read broke')

    for name, hook in (('error reply', error_reply), ('raises', raises)):
        _drawn_house()
        reader = SideReader(outline_hook=hook)
        b = tb.start({'part': 'house'}, reader=reader, inline=False)
        st = _finish(b)
        reader.outline_returned.wait(10)
        time.sleep(0.3)
        st = tb.status(b)
        check(st['state'] == 'done', (name, 'a failed outline never stops the build', st['state'], st.get('pause'), _trouble(st)))
        check('outline' in [c['kind'] for c in reader.seen], (name, 'test setup: the outline read was made'))
        check(not _first_look(st['events']), (name, 'a failed outline draws nothing'))
        check(not _trouble(st), (name, 'dropped silently', _trouble(st)))


def test_heartbeat_every_15s():
    _drawn_house()
    now, saved = _fake_clock()
    try:
        reader = SideReader()

        def draft_hook(run, images, context):
            # Advance the fake clock 50 s in 1 s ticks; at each 15 s mark give
            # the heartbeat a moment (real time) to go out.
            for elapsed in range(1, 51):
                now[0] += 1.0
                due = elapsed // 15
                if elapsed % 15 == 0:
                    _wait(lambda: len([e for e in _events(run) if e['type'] == 'log'
                                       and HEARTBEAT.match(e.get('text') or '')]) >= due, 5)
                else:
                    time.sleep(0.005)

        reader.draft_hook = draft_hook
        b = tb.start({'part': 'house'}, reader=reader, inline=False)
        st = _finish(b)
        reader.outline_returned.wait(10)
    finally:
        _restore_clock(saved)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    events = tb.status(b)['events']
    beats = [e for e in events if e['type'] == 'log' and HEARTBEAT.match(e.get('text') or '')]
    logs = [e.get('text') for e in events if e['type'] == 'log']
    check(len(beats) >= 3, ('50 s of draft read: at least 3 heartbeat lines naming the building', logs))
    times = [int(m.group(1)) * 60 + int(m.group(2)) for m in (HEARTBEAT.match(e['text']) for e in beats)]
    check(times == sorted(times) and max(times) >= 45 and max(times) <= 51,
          ('M:SS counts the draft read so far', [e['text'] for e in beats]))
    settled = _draft_settled(events)
    check(settled and all(e['seq'] < settled[0]['seq'] for e in beats),
          ('the heartbeat runs while the draft read is in flight', [e['seq'] for e in beats], settled[:1]))


def test_background_failures_are_logged():
    for failure in ('reply', 'exception'):
        _drawn_house()

        def outline_hook(run):
            if failure == 'exception':
                raise RuntimeError('outline failed')
            return {'error': 'outline failed'}

        with patch.object(tb.logger, 'info') as info:
            reader = SideReader(outline_hook=outline_hook)
            b = tb.start({'part': 'house'}, reader=reader, inline=False)
            st = _finish(b)
            check(_wait(lambda: bool(info.call_args_list), 5), 'a failed first look is logged')
            info.assert_any_call('First-look outline dropped', exc_info=True)
        check(st['state'] == 'done', ('an outline failure leaves the draft working', failure, st['state']))

    _drawn_house()
    logged = threading.Event()
    escaped = []
    calls = []

    def clock():
        if threading.current_thread().name.startswith('twin-heartbeat-'):
            calls.append('heartbeat')
            raise RuntimeError('heartbeat clock failed')
        return 1000.0

    def log_failure(message, **options):
        check(message == 'Draft heartbeat stopped' and options.get('exc_info') is True,
              ('heartbeat logs its exception', message, options))
        logged.set()

    reader = SideReader(draft_hook=lambda *args: logged.wait(5) and None)
    with patch.object(tb, '_clock', clock), patch.object(tb.logger, 'info', side_effect=log_failure), \
            patch.object(threading, 'excepthook', side_effect=lambda args: escaped.append(args)):
        b = tb.start({'part': 'house'}, reader=reader, inline=False)
        st = _finish(b)
    check(logged.is_set(), 'heartbeat failure was caught and logged')
    check(calls == ['heartbeat'] and not escaped, ('the heartbeat returns without an uncaught exception', calls, escaped))
    check(st['state'] == 'done', ('the draft still settles', st['state'], _trouble(st)))


def test_patched_default_reader_needs_no_internal_options():
    _drawn_house()
    # This strict fake has no checkpoint_checked keyword, even when installed
    # as the module's default reader after twin_build has been imported.
    reader = SideReader()
    with patch.object(tb.twin_reads, 'read', reader):
        b = tb.start({'part': 'house'}, inline=False)
        st = _finish(b)
    check(st['state'] == 'done', ('a replaced default reader keeps its own signature', st['state'], _trouble(st)))
    check(reader.outline_returned.wait(5), 'the replacement outline reader also runs')
    check({'draft', 'outline'} <= set(_read_kinds(reader)), ('both reads use the replacement', _read_kinds(reader)))


def test_checkpoint_combined_estimate():
    # R30: check once before draft/outline, then again before roof_check.
    # Three draft pages, one roof page, no photos.
    combined = tc.estimate('draft', 3) + tc.estimate('outline', 1) + tc.estimate('roof_check', 1)
    real = tc.require_clear
    calls = []
    reader = None

    def counted():
        build = next(iter(tb._BUILDS.values()), None)
        stages = [e for e in (build['events'] if build else []) if e['type'] == 'stage']
        calls.append({'stage': stages[-1].get('step') if stages else None,
                      'reads_before': [c['kind'] for c in (reader.seen if reader else [])
                                        if c['kind'] in ('draft', 'outline', 'roof_check')]})
        return real()

    tc.require_clear = counted
    try:
        # a. The ledger is already past an unacknowledged checkpoint: no read starts.
        _drawn_house()
        _spend_to(10.5)
        reader = SideReader()
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
        st = _rest(b)
        time.sleep(0.3)   # room for a wrongly started side read to be called
        check(st['state'] == 'checkpoint', ('the build stops at the checkpoint as other steps do',
                                            st['state'], _trouble(st)))
        points = [e for e in st['events'] if e['type'] == 'checkpoint']
        check(points and points[-1].get('step') == 'draft' and points[-1].get('checkpoint') == 10.0,
              ('the checkpoint names the draft step and $10', points[-1:]))
        kinds = [c['kind'] for c in reader.seen]
        check('draft' not in kinds and 'outline' not in kinds, ('neither read is made', kinds))
        check(next(s for s in st['steps'] if s['id'] == 'draft')['status'] == 'pending', st['steps'][:1])

        # b. The ledger is clear: check before the paired reads and before the roof check.
        _drawn_house()
        calls.clear()
        reader = SideReader()
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
        st = _finish(b)
        _wait(lambda: reader.outline_returned.is_set(), 5)
        time.sleep(0.3)
    finally:
        tc.require_clear = real
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    kinds = [c['kind'] for c in reader.seen]
    check(kinds.count('draft') == 1 and kinds.count('outline') == 1, ('both reads are made once', kinds))
    for_draft = [c for c in calls if c['stage'] == 'draft']
    check(len(for_draft) == 2, ('require_clear is called before the pair and before roof_check', calls))
    check(for_draft[0]['reads_before'] == [], ('it is called before either read starts', for_draft))
    check(for_draft[1]['reads_before'].count('draft') == 1
          and 'roof_check' not in for_draft[1]['reads_before'],
          ('the second check is after the draft and before roof_check; the side read may still run', for_draft))
    step = next(s for s in st['steps'] if s['id'] == 'draft')
    check(isinstance(step.get('estimate'), (int, float)) and abs(step['estimate'] - combined) < 1e-6,
          ('the draft step carries the combined estimate as step["estimate"]', step.get('estimate'), combined))


def test_anchor_registration_upper_floor():
    sheets = _drawn_house(sized=True)
    reader = SideReader()
    expected = {}

    def draft_hook(run, images, context):
        answer, found = _anchored_answer(sheets, images, context)
        expected.update(found)
        return answer

    reader.draft_hook = draft_hook
    b = tb.start({'part': 'house'}, reader=reader, inline=False)
    st = _finish(b)
    reader.outline_returned.wait(10)
    check(st['state'] == 'done', (st['state'], st.get('pause'), _trouble(st)))
    check(sorted(expected) == [1, 2], ('test setup: both floor pages carry anchors', sorted(expected)))
    for page in (2, 1):
        level, crop, anchors = expected[page]
        reg = ts.registration(sheets, page, level)
        check(isinstance(reg, dict), ('the floor page gets a registration from its anchors', page, level,
                                      ts.registrations()))
        for anchor in anchors:
            got = twin_register.apply(reg, ts.crop_to_master(crop, anchor['px']))
            check(math.dist(got, anchor['at']) <= 0.5,
                  ('an anchor maps back to its feet', level, anchor, [round(v, 2) for v in got]))
    check(not _trouble(st), _trouble(st))


def test_bad_anchors_no_registration():
    def run_with(pages_for):
        sheets = _drawn_house(sized=True)
        reader = SideReader()

        def draft_hook(run, images, context):
            answer, _ = _anchored_answer(sheets, images, context)
            answer['pages'] = pages_for(answer['pages'])
            return answer

        reader.draft_hook = draft_hook
        b = tb.start({'part': 'house'}, reader=reader, inline=False)
        st = _finish(b)
        reader.outline_returned.wait(10)
        return sheets, st, reader

    def by_level(pages):
        return {p['level']: p for p in pages}

    def outside_and_too_few(pages):
        # L1: one anchor inside 0..1, two outside. L2: a single anchor.
        out = by_level(pages)
        l1, l2 = out['L1'], out['L2']
        l1['anchors'] = [{**l1['anchors'][0], 'px': [1.4, 0.2]}, {**l1['anchors'][1], 'px': [0.3, -0.1]},
                         l1['anchors'][2]]
        l2['anchors'] = l2['anchors'][:1]
        return [l1, l2]

    def coincident_and_unknown_image(pages):
        # L1: every anchor at the same image point. L2: anchors on one spot in feet.
        # And an entry for an image the draft was never sent.
        out = by_level(pages)
        l1, l2 = out['L1'], out['L2']
        l1['anchors'] = [{**a, 'px': list(l1['anchors'][0]['px'])} for a in l1['anchors']]
        l2['anchors'] = [{**a, 'at': [20.0, 30.0]} for a in l2['anchors']]
        stray = {'image': 99, 'level': 'L1', 'anchors': copy.deepcopy(by_level(pages)['L1']['anchors'])}
        return [l1, l2, stray]

    def none(pages):
        return []

    for name, pages_for in (('outside 0..1 and too few', outside_and_too_few),
                            ('coincident points and an unknown image', coincident_and_unknown_image),
                            ('no pages at all', none)):
        sheets, st, reader = run_with(pages_for)
        check(st['state'] == 'done', (name, 'bad anchors never pause or fail the build', st['state'],
                                      st.get('pause'), _trouble(st)))
        check(not [e for e in st['events'] if e['type'] == 'error'], (name, 'no error', _trouble(st)))
        check(ts.registration(sheets, 1, 'L1') is None and ts.registration(sheets, 2, 'L2') is None,
              (name, 'no registration from bad anchors', ts.registrations()))
        house = _house(ts.current())
        check(len(house['walls']) >= 28, (name, 'the building still settles', len(house['walls'])))


def test_registration_keeps_person_clears_stale_and_survives_write_error():
    from unittest.mock import patch
    sheets = _drawn_house()
    crop = ts.crop(sheets, 1, FULL, max_side=2576)
    result = {'fragment': spike(), 'sheets': [
        {'image': 0, 'role': 'floor', 'source': sheets, 'page': 1, 'crop': crop},
        {'image': 1, 'role': 'floor', 'source': sheets, 'page': 2, 'crop': crop}]}
    anchors = [{'px': [0, 0], 'at': [0, 0]}, {'px': [1, 0], 'at': [70, 0]}]
    result['fragment']['pages'] = [{'image': 0, 'level': 'L1', 'anchors': anchors}]
    person = dict(twin_register.make(.1), source='person')
    ts.set_registration(sheets, 1, 'L1', person)
    ts.set_registration(sheets, 2, 'L2', dict(twin_register.make(.2), source='draft'))
    tb._register_draft(result)
    check(ts.registration(sheets, 1, 'L1') == person, 'keep the person registration')
    check(ts.registration(sheets, 2, 'L2') is None, 'unanchored floor loses stale registration')
    ts.clear_registration(sheets, 1, 'L1')
    result['fragment']['pages'].append({'image': 1, 'level': 'L2', 'anchors': anchors})
    saved = ts.set_registration
    def write(source, page, level, reg):
        if page == 1:
            raise OSError('sheet registration unavailable')
        return saved(source, page, level, reg)
    with patch.object(ts, 'set_registration', side_effect=write):
        tb._register_draft(result)
    check(ts.registration(sheets, 1, 'L1') is None and ts.registration(sheets, 2, 'L2') is not None,
          'one failed page does not block another page')


def test_draft_anchors_replace_only_nonperson_registrations():
    for origin in (None, 'person'):
        sheets = _drawn_house(sized=True)
        old = twin_register.make(.1, offset=[100, 200])
        if origin:
            old['source'] = origin
        ts.set_registration(sheets, 1, 'L1', old)
        reader = SideReader()
        expected = {}
        def draft_hook(run, images, context):
            answer, found = _anchored_answer(sheets, images, context)
            expected.update(found)
            return answer
        reader.draft_hook = draft_hook
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
        check(tb.status(b)['state'] == 'done', _trouble(tb.status(b)))
        saved = ts.registration(sheets, 1, 'L1')
        if origin == 'person':
            check(saved == old, saved)
        else:
            level, crop, anchors = expected[1]
            check(saved != old and saved['source'] == 'draft', saved)
            for anchor in anchors:
                check(math.dist(twin_register.apply(saved, ts.crop_to_master(crop, anchor['px'])),
                                anchor['at']) < .01, (saved, anchor))


TESTS = (
    test_draft_anchors_replace_only_nonperson_registrations,
    test_registration_keeps_person_clears_stale_and_survives_write_error,
    test_outline_ghost_first,
    test_outline_late_dropped,
    test_heartbeat_every_15s,
    test_background_failures_are_logged,
    test_patched_default_reader_needs_no_internal_options,
    test_checkpoint_combined_estimate,
    test_anchor_registration_upper_floor,
    test_bad_anchors_no_registration,
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
