"""The build streams pieces into the house and Stop ends the paid call
(plan docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md, Task 3;
Review Focus 1, 2, 3 and 5; rulings Q3-Q4 in
.superpowers/sdd/2026-11-10-house-guided-build-piece-4/progress.md).

The pool house's recorded whole-building read (Claude, the product prompt)
is replayed through a streaming stub reader. The stub has the reader's call
shape plus two keywords the engine passes to a reader that accepts them:

    reader(kind, images, context, *, run, step, cancel, on_text)

It feeds the recorded reply's JSON text to on_text in chunks, can wait at a
character index (the test presses Stop there, or lets it go on), honours a
cancel by recording the cost as twin_reads.read_stream does (input plus the
characters produced, twin_cost.record(..., cancelled=True, produced_chars=n))
and raising twin_reads.Cancelled, and can drop the stream part way through a
piece. Called without a cancel (today's engine), it waits 3 s and carries on,
so every test ends in a plain assertion instead of a hang.

Piece events: {type: 'piece', step, stage, kind, piece}, where piece is the
reply's item exactly as written (reply ids and building feet), kind is one of
level, wall, opening, fixture, roof, room, and stage is the open array's
stage: building.levels outline, building.walls walls, building.openings
doors and windows, building.fixtures fixtures, building.roof.sections roofs,
rooms (the rooms read's top-level array) rooms. Stage events:
{type: 'stage', step, stage}; every piece event follows a stage event of its
own stage for that step.

No test spends money or opens a socket: llm_budget.urlopen,
urllib.request.urlopen and socket.create_connection raise if reached.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_stream.py
"""
import copy
import json
import math
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request

# Always a scratch data dir (the engine harness wipes its data dir).
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_stream_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import llm_budget  # noqa: E402
from services import twin_build as tb  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_reads  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import _accept_all, _pdf, check  # noqa: E402


def _no_network(*args, **kwargs):
    raise AssertionError('a test reached the network; every read here is a stub')


llm_budget.urlopen = _no_network
urllib.request.urlopen = _no_network
socket.create_connection = _no_network

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
MODEL = 'anthropic:claude-opus-5-5'
INPUT_TOKENS = 1234
NO_CANCEL_WAIT = 3.0      # a stub called without a cancel gives up waiting after this
STOP_WITHIN = 2.0         # Global Constraints: Stop ends the provider call within 2 s
STAGES = ('scale', 'outline', 'walls', 'rooms', 'doors and windows', 'fixtures', 'roofs', 'finishes', 'yard')
STREAM_THREADS = ('twin-build-', 'twin-outline-', 'twin-heartbeat-')


class _LocalCancelled(RuntimeError):
    """Stands in until twin_reads.Cancelled exists (Task 1)."""


def _cancelled_error():
    return getattr(twin_reads, 'Cancelled', _LocalCancelled)


def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


DRAFT = recorded('draft-pool-house.json')
ROOMS = recorded('draft_rooms-pool-house.json')
WALLS = DRAFT['building']['walls']      # W1-W4 on L1, K1-K4 on L2


# --- the streaming stub reader ---------------------------------------------------

class _Response:
    """What a blocking provider call holds open; Cancel.attach closes it."""

    def __init__(self):
        self.closed = threading.Event()

    def close(self):
        self.closed.set()

    def read(self, *args):
        self.closed.wait(10)
        return b''


class StreamReader:
    """Replays the recorded draft and rooms replies as streamed text.

    gate_at=(kind, index): stop feeding at that character and wait for Stop
    (cancel) or for .go. end_at=(kind, index): the stream drops there and the
    read answers a plain error, as read_stream does. blocking=True: the draft
    read sends no text until the whole reply lands (a provider without
    streaming); it attaches a response the cancel must close.
    """

    def __init__(self, *, gate_at=None, end_at=None, blocking=False, chunk=48):
        self.texts = {'draft': json.dumps(DRAFT), 'draft_rooms': json.dumps(ROOMS)}
        self.answers = {'draft': DRAFT, 'draft_rooms': ROOMS}
        self.gate_at, self.end_at, self.blocking, self.chunk = gate_at, end_at, blocking, chunk
        self.calls = []
        self.produced = {}
        self.at_gate = threading.Event()
        self.go = threading.Event()
        self.exited = threading.Event()
        self.exited_at = None
        self.response = None

    def kinds(self):
        return [c['kind'] for c in self.calls]

    def __call__(self, kind, images, context, *, run, step, cancel=None, on_text=None, **options):
        self.calls.append({'kind': kind, 'step': step, 'cancel': cancel is not None,
                           'on_text': on_text is not None})
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}   # the first look is disposable
        if kind not in self.texts:
            raise AssertionError(f'unexpected read {kind}')
        try:
            if self.blocking and kind == 'draft':
                return self._blocking(kind, run, cancel, on_text)
            return self._stream(kind, run, cancel, on_text)
        finally:
            if kind == 'draft':
                self.exited_at = time.monotonic()
                self.exited.set()

    def _charge(self, kind, run, produced, *, cancelled):
        usage = {'model': MODEL, 'input_tokens': INPUT_TOKENS,
                 'output_tokens': None if cancelled else max(1, produced // 4),
                 'max_output_tokens': twin_reads.MAX_OUTPUT[kind]}
        tc.record(f'step:{kind}', [usage], run, cancelled=cancelled, produced_chars=produced)

    def _wait(self, cancel):
        """True when the cancel arrived; False when the test let the read go on."""
        deadline = time.monotonic() + (NO_CANCEL_WAIT if cancel is None else 10)
        while time.monotonic() < deadline:
            if cancel is not None and cancel.cancelled:
                return True
            if self.go.wait(0.01):
                return False
        return False

    def _stream(self, kind, run, cancel, on_text):
        text = self.texts[kind]
        gate = self.gate_at[1] if self.gate_at and self.gate_at[0] == kind else None
        end = self.end_at[1] if self.end_at and self.end_at[0] == kind else None
        limit = len(text) if end is None else end
        produced, i = 0, 0
        while i < limit:
            if gate is not None and i >= gate and not self.at_gate.is_set():
                self.at_gate.set()
                if self._wait(cancel):
                    self._charge(kind, run, produced, cancelled=True)
                    raise _cancelled_error()('Read stopped.')
            if cancel is not None and cancel.cancelled:
                self._charge(kind, run, produced, cancelled=True)
                raise _cancelled_error()('Read stopped.')
            j = min(i + self.chunk, limit)
            if gate is not None and i < gate:
                j = min(j, gate)
            produced += j - i
            self.produced[kind] = produced
            if on_text is not None:
                on_text(text[i:j])
            i = j
        if end is not None:
            self._charge(kind, run, produced, cancelled=False)
            return {'error': 'The model reply ended before it was complete.'}
        self._charge(kind, run, produced, cancelled=False)
        return copy.deepcopy(self.answers[kind])

    def _blocking(self, kind, run, cancel, on_text):
        response = self.response = _Response()
        if cancel is not None:
            cancel.attach(response)
        self.at_gate.set()
        deadline = time.monotonic() + (NO_CANCEL_WAIT if cancel is None else 10)
        while time.monotonic() < deadline and not response.closed.is_set() and not self.go.wait(0.01):
            pass
        if response.closed.is_set():
            self.produced[kind] = 0
            self._charge(kind, run, 0, cancelled=True)
            raise _cancelled_error()('Read stopped.')
        text = self.texts[kind]
        self.produced[kind] = len(text)
        if on_text is not None:
            on_text(text)              # a blocking provider yields the whole text once
        self._charge(kind, run, len(text), cancelled=False)
        return copy.deepcopy(self.answers[kind])


# --- reply text positions --------------------------------------------------------

def _text():
    return json.dumps(DRAFT)


def after_wall(k, *, half=False):
    """The character index just past the k-th wall item (1-based); with half,
    half way through the next wall item."""
    text = _text()
    pos = text.index('"walls": [', text.index('"building"'))
    for wall in WALLS[:k]:
        item = json.dumps(wall)
        pos = text.index(item, pos) + len(item)
    if half:
        item = json.dumps(WALLS[k])
        pos = text.index(item, pos) + len(item) // 2
    return pos


def expected_draft_pieces():
    b = DRAFT['building']
    return ([('level', 'outline', p) for p in b['levels']]
            + [('wall', 'walls', p) for p in b['walls']]
            + [('opening', 'doors and windows', p) for p in b['openings']]
            + [('fixture', 'fixtures', p) for p in b.get('fixtures', [])]
            + [('room', 'rooms', p) for p in b.get('rooms', [])]
            + [('roof', 'roofs', p) for p in b['roof']['sections']])


# --- build plumbing --------------------------------------------------------------

def _pool_house():
    """A fresh place with the pool house's two floors and roof sheet, no photos."""
    engine_tests._fresh()
    bid = ts.add_building('Pool house', 'pool_house')['id']
    source = ts.save_source('drawing', 'pool.pdf', _pdf(3), part=bid)
    names = [l['name'] for l in sorted(DRAFT['building']['levels'], key=lambda l: l['elevation'])]
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': names[0], 'box': None, 'building': bid},
        {'source': source, 'page': 2, 'role': 'floor', 'level': names[1], 'box': None, 'building': bid},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': bid}])
    return bid


def _join(timeout=10):
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.name.startswith(STREAM_THREADS):
            t.join(timeout)


def _release(*readers):
    for reader in readers:
        reader.go.set()
    _join()


def _wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(0.02)


def _pieces(status, step):
    return [e for e in status['events'] if e['type'] == 'piece' and e.get('step') == step]


def _settled_seq(status, step):
    return next((e['seq'] for e in status['events'] if e['type'] == 'settled' and e.get('step') == step), None)


def _stream_stages(status, step):
    return [e['stage'] for e in status['events']
            if e['type'] == 'stage' and e.get('step') == step and e.get('stage') is not None]


def _check_stage_events(status, step):
    current = None
    for e in status['events']:
        if e.get('step') != step:
            continue
        if e['type'] == 'stage' and 'stage' in e:
            check(e['stage'] is None or e['stage'] in STAGES, ('stage names are the verbatim list', e))
            current = e['stage']
        if e['type'] == 'piece':
            check(e['stage'] == current,
                  ('every piece follows a stage event of its own stage', e, current))
    stages = _stream_stages(status, step)
    check(all(a != b for a, b in zip(stages, stages[1:])),
          ('a stage event comes only when the open array changes', stages))


def _house(bid):
    plan = ts.current()
    return next((h for h in (plan or {}).get('buildings', []) if h['id'] == bid), None)


def _seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    length2 = ax * ax + ay * ay
    t = 0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / length2))
    return math.dist(p, [a[0] + t * ax, a[1] + t * ay])


def _along(house, wall, tol=0.05):
    """Walls on the read wall's level lying along its segment (both ends on it)."""
    return [w for w in house['walls'] if w['level'] == wall['level']
            and math.dist(w['from'], w['to']) > 0.1
            and _seg_dist(w['from'], wall['from'], wall['to']) <= tol
            and _seg_dist(w['to'], wall['from'], wall['to']) <= tol]


def _covered_once(house, wall):
    return len({w['id'].split('~')[0] for w in _along(house, wall)}) == 1


def _run_entries(b, stage=None):
    return [e for e in tc.entries() if e.get('run') == b and (stage is None or e.get('stage') == stage)]


def _check_spend_matches_ledger(b):
    shown = tb.status(b)['cost']
    ledger = math.fsum(e['usd'] for e in _run_entries(b))
    check(abs(shown - ledger) < 1e-9, ('the build shows exactly the ledger spend for its run', shown, ledger))


def _draft_rounds(since):
    return [r for r in ts.rounds()[since:] if r['kind'] == 'build' and (r.get('step') or {}).get('id') == 'draft']


def _stop(b, reader):
    """Press Stop at the reader's gate; return seconds until the read ended."""
    check(reader.at_gate.wait(10), 'test setup: the draft read reached the gate')
    pressed = time.monotonic()
    tb.stop(b)
    ended = reader.exited.wait(STOP_WITHIN + 0.5)
    took = (reader.exited_at - pressed) if ended and reader.exited_at else None
    check(ended and took is not None and took <= STOP_WITHIN,
          ('Stop ends the paid call within 2 s', took, reader.calls[-1:]))
    return took


def _stopped_with(b, predicate=lambda st: True):
    st = _wait_for(lambda: (lambda s: s if s['state'] == 'stopped' and predicate(s) else None)(tb.status(b)),
                   STOP_WITHIN)
    check(st, ('the build reads stopped once the cancel returns', tb.status(b)['state']))
    return st


def _continue(b, reader):
    """Continue; refused only while the cancel itself is still in progress."""
    deadline = time.monotonic() + STOP_WITHIN
    while True:
        try:
            tb.resume(b, reader=reader, inline=True)
            return _accept_all(b)
        except ValueError as exc:
            if 'stopping' not in str(exc).lower() or time.monotonic() > deadline:
                raise AssertionError(('Continue is refused after the Stop returned', str(exc))) from None
            time.sleep(0.05)


def _draft_step(b):
    return next(s for s in tb._BUILDS[b]['steps'] if s['id'] == 'draft')


def _check_partial_round(bid, since, k):
    """One partial round holds the levels and the first k walls, nothing more of the draft."""
    partial = [r for r in _draft_rounds(since) if r.get('partial') is True]
    complete = [r for r in _draft_rounds(since) if not r.get('partial')]
    check(len(partial) == 1, ('the complete pieces are published as one partial build round',
                              [(r['kind'], r.get('step'), r.get('partial')) for r in ts.rounds()[since:]]))
    check(not complete, ('the stopped draft never settles as a complete round', complete))
    house = _house(bid)
    check(house is not None, 'the partial round is the current house')
    levels = {l['id']: l for l in house['levels']}
    for level in DRAFT['building']['levels']:
        got = levels.get(level['id'])
        check(got is not None and len(got['outline']) == len(level['outline'])
              and all(min(math.dist(p, q) for q in got['outline']) <= 0.05 for p in level['outline']),
              ('each level that arrived whole is kept', level['id'], got and got.get('outline')))
    for wall in WALLS[:k]:
        check(_covered_once(house, wall), ('each wall that arrived whole is kept once', wall['id'],
                                           [(w['level'], w['from'], w['to']) for w in house['walls']]))
    half = WALLS[k]
    check(not _along(house, half, tol=0.5), ('the half wall at the cut is discarded', half))
    for wall in WALLS[k + 1:]:
        check(not _along(house, wall, tol=0.5), ('no wall that had not arrived appears', wall))
    check(not [o for o in house['openings'] if o.get('src', {}).get('step') == 'draft'],
          ('no opening had arrived, so none is kept', house['openings']))
    return house


# --- tests -------------------------------------------------------------------------

def test_pieces_arrive_in_order_before_the_step_settles():
    bid = _pool_house()
    reader = StreamReader(gate_at=('draft', after_wall(3, half=True)))
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        check(reader.at_gate.wait(10), 'test setup: the draft read reached the gate')
        live = _wait_for(lambda: (lambda s: s if len(_pieces(s, 'draft')) >= 5 else None)(tb.status(b)), 2)
        st = live or tb.status(b)
        got = [(e['kind'], e['stage'], e['piece']) for e in _pieces(st, 'draft')]
        check(got == expected_draft_pieces()[:5],
              ('while the draft is still being read, the two levels and three whole walls have arrived, '
               'in order, and the half wall has not', [(k, s) for k, s, _ in got], reader.calls))
        draft = next(s for s in st['steps'] if s['id'] == 'draft')
        check(draft['status'] == 'running', ('the step has not settled yet', draft['status']))
        check(not _draft_rounds(0), ('nothing is published before the read ends', ts.rounds()))
        stages = _stream_stages(st, 'draft')
        check(stages[-1:] == ['walls'], ('the open array is the walls', stages))
        _check_stage_events(st, 'draft')
    finally:
        _release(reader)
    st = _accept_all(b)
    check(st['state'] == 'done', ('the streamed build finishes', st['state'], st.get('pause')))
    got = [(e['kind'], e['stage'], e['piece']) for e in _pieces(st, 'draft')]
    check(got == expected_draft_pieces(),
          ('every piece of the reply arrives once, in reply order, as written',
           [(k, s) for k, s, _ in got]))
    for e in _pieces(st, 'draft') + _pieces(st, 'draft_rooms'):
        check({'seq', 'type', 'step', 'stage', 'kind', 'piece'} <= e.keys(), ('piece event shape', e))
    settled = _settled_seq(st, 'draft')
    check(settled is not None and all(e['seq'] < settled for e in _pieces(st, 'draft')),
          ('every draft piece arrives before the draft settles', settled))
    stages = _stream_stages(st, 'draft')
    order = iter(stages)
    check(all(s in order for s in ('outline', 'walls', 'doors and windows', 'roofs')),
          ('the draft stages follow the reply', stages))
    _check_stage_events(st, 'draft')
    rooms = [(e['kind'], e['stage'], e['piece']) for e in _pieces(st, 'draft_rooms') if e['kind'] == 'room']
    check(rooms == [('room', 'rooms', r) for r in ROOMS['rooms']],
          ('the rooms read streams its rooms too', [(k, s) for k, s, _ in rooms]))
    settled = _settled_seq(st, 'draft_rooms')
    check(settled is not None and all(e['seq'] < settled for e in _pieces(st, 'draft_rooms')),
          ('every room arrives before the rooms step settles', settled))
    _check_stage_events(st, 'draft_rooms')


def test_stop_mid_walls_keeps_complete_walls_and_charges_produced():
    bid = _pool_house()
    cut = after_wall(5, half=True)          # W1-W4 and K1 whole, K2 half way
    reader = StreamReader(gate_at=('draft', cut))
    since = len(ts.rounds())
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        _stop(b, reader)
        st = _stopped_with(b, lambda s: any(r.get('partial') for r in _draft_rounds(since)))
        check(any(c['kind'] == 'draft' and c['cancel'] and c['on_text'] for c in reader.calls),
              ('the draft read is given a cancel and on_text', reader.calls))
        got = [(e['kind'], e['piece']) for e in _pieces(st, 'draft')]
        check(got == [(k, p) for k, _, p in expected_draft_pieces()[:7]],
              ('the pieces that arrived whole were shown, the half piece never', [k for k, _ in got]))
        _check_partial_round(bid, since, 5)
        check(_draft_step(b)['status'] != 'done', ('the stopped step is still to do', _draft_step(b)['status']))
        drafts = _run_entries(b, 'step:draft')
        check(len(drafts) == 1, ('one ledger entry for the stopped call, recorded once', drafts))
        check(reader.produced.get('draft') == cut, ('test setup: the stub produced up to the cut', reader.produced))
        entry = drafts[0]
        check(entry['input_tokens'] == INPUT_TOKENS and entry['output_tokens'] == cut // 4,
              ('the stopped call is charged its input plus the output produced', entry))
        check(entry['output_tokens'] < twin_reads.MAX_OUTPUT['draft'], ('never the output limit', entry))
        _check_spend_matches_ledger(b)
    finally:
        _release(reader)


def test_stop_before_first_piece_keeps_nothing_and_charges_input():
    bid = _pool_house()
    reader = StreamReader(gate_at=('draft', 0))          # Stop in the connect / first-byte window
    since = len(ts.rounds())
    before = copy.deepcopy(ts.current())
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        _stop(b, reader)
        st = _stopped_with(b)
        check(not _pieces(st, 'draft'), ('nothing arrived, so no piece was shown', _pieces(st, 'draft')))
        check(len(ts.rounds()) == since and ts.current() == before,
              ('a Stop before the first piece publishes nothing', ts.rounds()[since:]))
        drafts = _run_entries(b, 'step:draft')
        check(len(drafts) == 1 and drafts[0]['output_tokens'] == 0 and drafts[0]['input_tokens'] > 0,
              ('a Stop before the first byte is charged its input only', drafts))
        _check_spend_matches_ledger(b)
    finally:
        _release(reader)
    again = StreamReader()
    st = _continue(b, again)
    check(st['state'] == 'done', ('Continue after an early Stop builds the house', st['state'], st.get('pause')))
    check(again.kinds().count('draft') == 1, ('Continue reads the stopped step again', again.kinds()))
    house = _house(bid)
    check(all(_covered_once(house, w) for w in WALLS), ('every wall is built once', house['walls']))


def test_continue_after_stop_rereads_on_the_model_as_it_stands():
    bid = _pool_house()
    reader = StreamReader(gate_at=('draft', after_wall(5, half=True)))
    since = len(ts.rounds())
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        _stop(b, reader)
        _stopped_with(b, lambda s: any(r.get('partial') for r in _draft_rounds(since)))
        kept = {w['id'] for w in _check_partial_round(bid, since, 5)['walls']
                if w.get('src', {}).get('step') == 'draft'}
    finally:
        _release(reader)
    check(len(kept) >= 5, ('test setup: the partial round holds the five whole walls', kept))
    again = StreamReader()
    st = _continue(b, again)
    check(st['state'] == 'done', ('Continue finishes the build', st['state'], st.get('pause')))
    check(again.kinds().count('draft') == 1 and again.kinds().count('draft_rooms') == 1,
          ('Continue reads the stopped step again, then the later steps', again.kinds()))
    house = _house(bid)
    ids = {w['id'] for w in house['walls']}
    check(kept <= ids, ('the re-read lands on the kept walls instead of beside them', kept - ids))
    for wall in WALLS:
        check(_covered_once(house, wall), ('each wall of the reply is built exactly once', wall['id'],
                                           [(w['id'], w['from'], w['to']) for w in _along(house, wall)]))
    complete = [r for r in _draft_rounds(since) if not r.get('partial')]
    check(len(complete) == 1, ('the re-read settles as one complete round', _draft_rounds(since)))
    check(len(_run_entries(b, 'step:draft')) == 2, ('the stopped call and the re-read are both on the ledger',
                                                    _run_entries(b, 'step:draft')))
    _check_spend_matches_ledger(b)


def test_continue_after_a_hand_delete_does_not_resurrect_it():
    bid = _pool_house()
    reader = StreamReader(gate_at=('draft', after_wall(5, half=True)))
    since = len(ts.rounds())
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        _stop(b, reader)
        _stopped_with(b, lambda s: any(r.get('partial') for r in _draft_rounds(since)))
        house = _check_partial_round(bid, since, 5)
    finally:
        _release(reader)
    k1, w2 = WALLS[4], WALLS[1]            # K1 on L2 deleted, W2 on L1 moved 1 ft out
    deleted = _along(house, k1)
    check(len(deleted) == 1, ('test setup: K1 is one wall', deleted))
    twin_edit.save({'op': 'delete', 'piece': deleted[0]['id']}, 'p1')
    moved = _along(_house(bid), w2)
    check(len(moved) == 1, ('test setup: W2 is one wall', moved))
    moved_id = moved[0]['id']
    twin_edit.save({'op': 'move', 'piece': moved_id, 'by': [1, 0]}, 'p1')
    placed = next(w for w in _house(bid)['walls'] if w['id'] == moved_id)
    check(placed['src'].get('person') and abs(placed['from'][0] - 32) < 0.01,
          ('test setup: the moved wall is the person\'s, at x 32', placed))
    st = _continue(b, StreamReader())
    check(st['state'] == 'done', ('Continue after a hand fix finishes', st['state'], st.get('pause')))
    house = _house(bid)
    check(not _along(house, k1, tol=0.5), ('the wall deleted by hand stays deleted (tombstone)',
                                           [(w['level'], w['from'], w['to']) for w in house['walls']]))
    after = next((w for w in house['walls'] if w['id'] == moved_id), None)
    check(after is not None and after['src'].get('person')
          and abs(after['from'][0] - 32) < 0.01 and abs(after['to'][0] - 32) < 0.01,
          ('the wall moved by hand stays where the person put it, and stays theirs', after))
    check(not _along(house, w2, tol=0.25), ('the moved wall is not read back in at its old place',
                                            [(w['id'], w['from'], w['to']) for w in _along(house, w2, tol=0.25)]))


def test_stream_ending_mid_piece_reports_and_offers_read_again():
    bid = _pool_house()
    reader = StreamReader(end_at=('draft', after_wall(5, half=True)))   # the connection drops inside K2
    since = len(ts.rounds())
    b = tb.start({'part': bid}, reader=reader, inline=True)
    _join()
    st = tb.status(b)
    check(st['state'] == 'stopped', ('a dropped stream leaves the build stopped, not failed', st['state']))
    check(_draft_step(b)['status'] != 'done', ('the dropped step is still to do', _draft_step(b)['status']))
    got = [(e['kind'], e['piece']) for e in _pieces(st, 'draft')]
    check(got == [(k, p) for k, _, p in expected_draft_pieces()[:7]],
          ('the whole pieces were shown and the half piece discarded', [k for k, _ in got]))
    _check_partial_round(bid, since, 5)
    said = [e for e in st['events'] if e['type'] in ('question', 'error') and e.get('step') == 'draft']
    check(said, ('the step reports what happened', st['events'][-5:]))
    text = said[-1]['text']
    check(not any(word in text for word in ('JSON', 'json', 'Traceback', 'Exception', '{', 'parse')),
          ('the report is plain words', text))
    check('again' in text.lower(), ('the report offers reading it again', text))
    check(not tb._cache_path(tb._BUILDS[b], _draft_step(b)).is_file(),
          'a dropped reply is never kept as the paid answer')
    again = StreamReader()
    tb.reread(b, 'draft', reader=again, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', ('Read it again finishes the build', st['state'], st.get('pause')))
    check(again.kinds().count('draft') == 1, ('Read it again is a fresh read', again.kinds()))
    house = _house(bid)
    check(all(_covered_once(house, w) for w in WALLS), ('every wall is built once after the re-read',
                                                        [(w['level'], w['from'], w['to']) for w in house['walls']]))


def test_paid_reply_cache_never_holds_a_partial():
    bid = _pool_house()
    reader = StreamReader(gate_at=('draft', after_wall(5, half=True)))
    since = len(ts.rounds())
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        _stop(b, reader)
        _stopped_with(b, lambda s: any(r.get('partial') for r in _draft_rounds(since)))
        path = tb._cache_path(tb._BUILDS[b], _draft_step(b))
        check(not path.is_file(), ('a stopped reply is never cached as the paid answer', str(path)))
        steps = path.parent
        cached = sorted(p.name for p in steps.glob('*.json')) if steps.is_dir() else []
        check(not cached, ('nothing from the stopped read is cached', cached))
    finally:
        _release(reader)
    again = StreamReader()
    st = _continue(b, again)
    check(st['state'] == 'done', ('Continue finishes', st['state'], st.get('pause')))
    check(again.kinds().count('draft') == 1, ('the stopped reply is not reused; the step is read again',
                                              again.kinds()))
    path = tb._cache_path(tb._BUILDS[b], _draft_step(b))
    if path.is_file():
        result = json.loads(path.read_text(encoding='utf-8'))
        walls = result.get('fragment', {}).get('building', {}).get('walls', [])
        check(len(walls) == len(WALLS), ('the cached answer is the whole reply', len(walls)))


def test_blocking_provider_still_stops():
    # Review Focus 5 (ruling Q3): no streaming, Stop closes the socket.
    bid = _pool_house()
    reader = StreamReader(blocking=True)
    since = len(ts.rounds())
    b = tb.start({'part': bid}, reader=reader, inline=False)
    try:
        _stop(b, reader)
        check(reader.response is not None and reader.response.closed.is_set(),
              'Stop closes the blocking call\'s response (the socket)')
        st = _stopped_with(b)
        check(not _pieces(st, 'draft') and len(ts.rounds()) == since,
              ('nothing had landed, so nothing is shown or kept', _pieces(st, 'draft'), ts.rounds()[since:]))
        drafts = _run_entries(b, 'step:draft')
        check(len(drafts) == 1 and drafts[0]['output_tokens'] == 0 and drafts[0]['input_tokens'] > 0,
              ('the closed call is charged its input only', drafts))
        _check_spend_matches_ledger(b)
    finally:
        _release(reader)
    seq = tb.status(b)['seq']
    again = StreamReader(blocking=True)
    again.go.set()                              # the reply lands whole
    st = _continue(b, again)
    check(st['state'] == 'done', ('a blocking read still builds', st['state'], st.get('pause')))
    fresh = [e for e in _pieces(st, 'draft') if e['seq'] > seq]
    check([(e['kind'], e['stage'], e['piece']) for e in fresh] == expected_draft_pieces(),
          ('the pieces appear when the reply lands, in order', [e['kind'] for e in fresh]))
    settled = max((e['seq'] for e in st['events'] if e['type'] == 'settled' and e.get('step') == 'draft'),
                  default=None)
    check(settled is not None and all(e['seq'] < settled for e in fresh),
          ('they arrive before the step settles', settled))


def test_the_product_reader_streams_the_draft():
    # With no reader given, the draft read goes through twin_reads.read_stream
    # (looked up at call time, ruling Q4 signature), so Stop reaches the provider.
    bid = _pool_house()
    replay = StreamReader()
    streamed, blocking = [], []

    def fake_read_stream(kind, context, images, *, cancel, on_text, run, step):
        streamed.append({'kind': kind, 'cancel': cancel, 'on_text': on_text})
        check(callable(on_text) and hasattr(cancel, 'cancel') and hasattr(cancel, 'cancelled'),
              ('read_stream gets a cancel handle and on_text', cancel, on_text))
        return replay(kind, images, context, run=run, step=step, cancel=cancel, on_text=on_text)

    def fake_read(kind, images, context, *, run, step, **options):
        blocking.append(kind)
        return replay(kind, images, context, run=run, step=step)

    saved = (twin_reads.read, getattr(twin_reads, 'read_stream', None), tb._REAL_READER)
    twin_reads.read, twin_reads.read_stream, tb._REAL_READER = fake_read, fake_read_stream, fake_read
    try:
        b = tb.start({'part': bid}, inline=True)
        _join()
        st = _accept_all(b)
    finally:
        twin_reads.read, tb._REAL_READER = saved[0], saved[2]
        if saved[1] is None:
            del twin_reads.read_stream
        else:
            twin_reads.read_stream = saved[1]
    check(any(c['kind'] == 'draft' for c in streamed) and 'draft' not in blocking,
          ('the product reader streams the draft read', [c['kind'] for c in streamed], blocking))
    check(st['state'] == 'done', ('the streamed product read builds', st['state'], st.get('pause')))
    got = [(e['kind'], e['stage'], e['piece']) for e in _pieces(st, 'draft')]
    check(got == expected_draft_pieces(), ('its pieces arrive in order', [k for k, _, _ in got]))


TESTS = (
    test_pieces_arrive_in_order_before_the_step_settles,
    test_stop_mid_walls_keeps_complete_walls_and_charges_produced,
    test_stop_before_first_piece_keeps_nothing_and_charges_input,
    test_continue_after_stop_rereads_on_the_model_as_it_stands,
    test_continue_after_a_hand_delete_does_not_resurrect_it,
    test_stream_ending_mid_piece_reports_and_offers_read_again,
    test_paid_reply_cache_never_holds_a_partial,
    test_blocking_provider_still_stops,
    test_the_product_reader_streams_the_draft,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:600])
        else:
            print('  ok  ', fn.__name__)
        finally:
            _join()
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
