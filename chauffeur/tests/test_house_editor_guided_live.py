"""The guided build in real Chromium, Tasks 5 and 6 (plan
docs/superpowers/plans/2026-11-10-house-guided-build-piece-4.md; briefs
task-5-brief.md and task-6-brief.md and Ruling Q9 in
.superpowers/sdd/2026-11-10-house-guided-build-piece-4/; Review Focus 4).
Tasks 7 and 8 keep their scenarios in tests/test_house_editor_steps_live.py.

The served house is the household's (tests/fixtures/twin_model/household-
2026-11-09.json, through house_editor_model_harness) with the pool house
stripped to its two levels: no walls, openings, rooms or roofs. The pool house
stands at [70.55, 142.20] turned 270 degrees, so a piece drawn without its
building's transform lands somewhere else. Its drawings are a blank 3-page PDF
with page roles (main floor, second floor, roof). A build of the pool house
(POST api/house/editor/build {part: 'pool-house'}, then the editor's own
followBuild test hook) reads the drawings once as `draft`, then `draft_rooms`.

No model is called. A stub streaming reader replaces twin_reads.read,
twin_reads.read_stream and twin_build._REAL_READER in this process; the
network is closed (llm_budget.urlopen raises). The stub replays the pool
house's recorded draft (tests/fixtures/twin_reads/recorded/claude/
draft-pool-house.json) as text through on_text, at a pace the browser can
watch, and holds the draft half way through its fourth wall on a
threading.Event (the gate). By then the two levels and walls W1-W3 have
arrived whole. A cancel (Stop) is honoured as twin_reads.read_stream does:
the stub records input plus the characters produced
(twin_cost.record(..., cancelled=True, produced_chars=n)) and raises
twin_reads.Cancelled.

Test hooks assumed (under ?test=1):
  window.__editor.buildGhosts.count()  build ghosts drawn now
  window.__editor.buildGhosts.seqs()   the piece-event seqs of the ghosts drawn
                                       now, in the order they were drawn
  window.__editor.build(), followBuild(id)  (exist today)

DOM assumed: #editor-chip, the status chip in #editor-top; its visible text
says Working or Waiting on you, `$x.xx so far` and, while a build runs,
`about $x.xx`; the Stop button sits inside it (a button whose text is Stop).
api/house/editor/state carries cost.total (the ledger, today) and
cost.estimate: the running build's remaining estimate in dollars.

A ghost in the scene: a visible mesh or line whose material is transparent
with opacity below 1, whose world box (under 30 m across, padded 0.15 m)
contains the point.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_guided_live.py
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_editor_model_harness as H  # noqa: E402  (sets the data dir, drops HA_BASE_URL)

check = H.check
B = 'pool-house'
MODEL = 'anthropic:claude-opus-5-5'
INPUT_TOKENS = 100_000           # a whole-building read's input: $0.40 at the Opus rate
STOP_WITHIN = 2.0                # Global Constraints: Stop ends the provider call within 2 s
REQUEST_SLACK = 0.5              # the Stop request's own round trip from the click
RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
STATE = {}


def _recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


DRAFT = _recorded('draft-pool-house.json')
ROOMS = _recorded('draft_rooms-pool-house.json')
WALLS = DRAFT['building']['walls']      # W1-W4 on L1, K1-K4 on L2
LEVELS = DRAFT['building']['levels']


def _after_wall(k, *, half=False):
    """The character index just past the k-th wall item; with half, half way through the next."""
    text = json.dumps(DRAFT)
    pos = text.index('"walls": [', text.index('"building"'))
    for wall in WALLS[:k]:
        item = json.dumps(wall)
        pos = text.index(item, pos) + len(item)
    if half:
        item = json.dumps(WALLS[k])
        pos = text.index(item, pos) + len(item) // 2
    return pos


GATE = _after_wall(3, half=True)        # levels L1, L2 and walls W1-W3 whole; W4 half way
KEPT = WALLS[:3]
AT_GATE = len(LEVELS) + len(KEPT)       # the piece events published by the gate


def _mid(wall, z=5.0):
    return [(wall['from'][0] + wall['to'][0]) / 2, (wall['from'][1] + wall['to'][1]) / 2, z]


CENTRE = [15.5, 11.0, 5.0]              # inside the L1 outline, away from every wall


# --- the stub streaming reader -------------------------------------------------------

class _LocalCancelled(RuntimeError):
    """Stands in until twin_reads.Cancelled exists (Task 1)."""


def _cancelled_error():
    from services import twin_reads
    return getattr(twin_reads, 'Cancelled', _LocalCancelled)


class LiveStreamReader:
    """Replays the recorded pool-house draft and rooms replies as streamed text.

    The draft stops at `gate` until .go is set or the read is cancelled. Text
    goes out in `chunk` characters every `delay` seconds before the gate (slow
    enough for the browser to see pieces arrive across polls) and quickly
    after it. Called without a cancel (today's engine), the gate waits for .go
    (every scenario sets it on the way out).
    """

    def __init__(self, *, gate=GATE, chunk=16, delay=0.1):
        self.texts = {'draft': json.dumps(DRAFT), 'draft_rooms': json.dumps(ROOMS)}
        self.answers = {'draft': DRAFT, 'draft_rooms': ROOMS}
        self.gate, self.chunk, self.delay = gate, chunk, delay
        self.calls = []
        self.produced = {}
        self.at_gate = threading.Event()
        self.go = threading.Event()
        self.exited = threading.Event()
        self.exited_at = None

    def __call__(self, kind, images, context, *, run, step, cancel=None, on_text=None, **_options):
        self.calls.append({'kind': kind, 'step': step, 'cancel': cancel is not None, 'on_text': on_text is not None})
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}      # the first look is disposable
        if kind not in self.texts:
            return {'error': f'This test has no {kind} reply.'}
        try:
            return self._stream(kind, run, cancel, on_text)
        finally:
            if kind == 'draft':
                self.exited_at = time.monotonic()
                self.exited.set()

    def _charge(self, kind, run, produced, *, cancelled):
        from services import twin_cost, twin_reads
        usage = {'model': MODEL, 'input_tokens': INPUT_TOKENS,
                 'output_tokens': None if cancelled else max(1, produced // 4),
                 'max_output_tokens': twin_reads.MAX_OUTPUT[kind]}
        try:
            twin_cost.record(f'step:{kind}', [usage], run, cancelled=cancelled, produced_chars=produced)
        except TypeError:                       # before Task 1's keywords
            twin_cost.record(f'step:{kind}', [usage], run)

    def _stream(self, kind, run, cancel, on_text):
        text = self.texts[kind]
        gate = self.gate if kind == 'draft' else None
        produced, i, gated = 0, 0, False
        while i < len(text):
            if gate is not None and i >= gate and not gated:
                gated = True
                self.at_gate.set()
                deadline = time.monotonic() + 120
                while not self.go.wait(0.01):
                    if (cancel is not None and cancel.cancelled) or time.monotonic() > deadline:
                        break
            if cancel is not None and cancel.cancelled:
                self._charge(kind, run, produced, cancelled=True)
                raise _cancelled_error()('Read stopped.')
            j = min(i + self.chunk, len(text))
            if gate is not None and i < gate:
                j = min(j, gate)
            produced += j - i
            self.produced[kind] = produced
            if on_text is not None:
                on_text(text[i:j])
            i = j
            time.sleep(self.delay if gate is not None and not gated else 0.002)
        self._charge(kind, run, produced, cancelled=False)
        return copy.deepcopy(self.answers[kind])


def _install(reader):
    """Every read in the served app goes to this stub."""
    from services import twin_build, twin_reads
    STATE['reader'] = reader

    def read_stream(kind, context, images, *, cancel, on_text, run, step, **_options):
        return reader(kind, images, context, run=run, step=step, cancel=cancel, on_text=on_text)

    twin_reads.read = reader
    twin_reads.read_stream = read_stream
    twin_build._REAL_READER = reader
    return reader


# --- seed and serve ------------------------------------------------------------------

def _strip_pool_house(plan):
    pool = H.building(plan, B)
    for key in ('walls', 'openings', 'rooms', 'stairs', 'porches', 'fixtures', 'lights', 'anchors', 'items'):
        if isinstance(pool.get(key), list):
            pool[key] = []
    pool['roof'] = {'sections': []}
    return plan


def _pdf(pages, w=1224, h=792):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _seed():
    H.seed(_strip_pool_house)
    from services import llm_budget, twin_cost, twin_store as ts

    def _no_network(*args, **kwargs):
        raise AssertionError('a read reached the network; every read here is the stub')

    llm_budget.urlopen = _no_network
    source = ts.save_source('drawing', 'pool.pdf', _pdf(3), part=B)
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': 'main floor', 'box': None, 'building': B},
        {'source': source, 'page': 2, 'role': 'floor', 'level': 'second floor', 'box': None, 'building': B},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': B}])
    # Earlier spend, so the chip's figure is never a bare $0.00.
    twin_cost.record('step:draft', [{'model': MODEL, 'input_tokens': 50_000, 'output_tokens': 20_000}], 'earlier-build')
    _install(LiveStreamReader())


def _serve():
    if 'served' not in H._SERVED:
        H._SERVED['served'] = H.live_app(_seed)
    return H._SERVED['served']


def _quiet_engine():
    """No build in flight: release the stub, stop anything active, wait for the workers."""
    from services import twin_build as tb
    reader = STATE.get('reader')
    if reader is not None:
        reader.go.set()
    for bid, build in list(tb._BUILDS.items()):
        if build.get('state') in tb._ACTIVE:
            try:
                tb.stop(bid)
            except Exception:
                pass
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.name.startswith(('twin-build-', 'twin-outline-', 'twin-heartbeat-')):
            t.join(30)


def _fresh(**reader_options):
    """A pool house with no pieces again and a fresh stub; returns the stub."""
    from services import twin_store as ts
    _quiet_engine()
    ts.push_round(_strip_pool_house(H.household_plan()), 'build')
    return _install(LiveStreamReader(**reader_options))


# --- the page --------------------------------------------------------------------------

def _api(page, method, path, body=None):
    return page.evaluate("""async ([method, path, body]) => {
        const r = await fetch(window.chfBase + 'api/house/editor/' + path, {
            method, headers: {'Content-Type': 'application/json'},
            body: body === null ? undefined : JSON.stringify(body)});
        return {status: r.status, body: await r.json().catch(() => null)};
    }""", [method, path, body])


def _start(page):
    """Build the pool house and have this tab follow it; returns the build id."""
    r = _api(page, 'POST', 'build', {'part': B})
    check(r['status'] == 200 and (r['body'] or {}).get('id'), ('test setup: the pool house build starts', r))
    bid = r['body']['id']
    page.evaluate('id => window.__editor.followBuild(id)', bid)
    return bid


def _ghosts(page):
    """window.__editor.buildGhosts.count(), required to exist."""
    got = page.evaluate("""() => {
        const g = window.__editor && window.__editor.buildGhosts;
        return g && typeof g.count === 'function' ? g.count() : null; }""")
    check(got is not None, 'window.__editor.buildGhosts.count() is missing: the editor sets it under ?test=1 (Task 5 hook)')
    return got


def _ghost_seqs(page):
    got = page.evaluate("""() => {
        const g = window.__editor && window.__editor.buildGhosts;
        return g && typeof g.seqs === 'function' ? g.seqs() : null; }""")
    check(got is not None, 'window.__editor.buildGhosts.seqs() is missing: the editor sets it under ?test=1 (Task 5 hook)')
    return got


def _server_pieces(bid, step='draft'):
    from services import twin_build as tb
    return [e for e in tb.status(bid)['events'] if e.get('type') == 'piece' and e.get('step') == step]


def _step_status(bid, step='draft'):
    from services import twin_build as tb
    return next((s['status'] for s in tb.status(bid)['steps'] if s['id'] == step), None)


def _build_state(page):
    return page.evaluate('() => { const b = window.__editor.build(); return b ? b.state : null; }')


GHOSTS_AT = """([points, bid]) => {""" + H._TO_SCENE + """
    const view = window.__twin;
    view.scene.updateMatrixWorld(true);
    const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
    const mats = o => (Array.isArray(o.material) ? o.material : [o.material]).filter(Boolean);
    const boxes = [];
    view.scene.traverse(o => {
        if (!(o.isMesh || o.isLine) || !shown(o) || !mats(o).some(m => m.transparent && m.opacity < 1)) return;
        let bx = null;
        if (o.isInstancedMesh) { o.computeBoundingBox(); bx = o.boundingBox && o.boundingBox.clone().applyMatrix4(o.matrixWorld); }
        else if (o.geometry) {
            if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
            bx = o.geometry.boundingBox && o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld);
        }
        if (!bx || bx.isEmpty()) return;
        if (Math.hypot(bx.max.x - bx.min.x, bx.max.y - bx.min.y, bx.max.z - bx.min.z) > 30) return;
        boxes.push(bx.expandByScalar(0.15));
    });
    return points.map(p => { const [x, y, z] = toScene(p, bid); return boxes.filter(b => b.containsPoint({x, y, z})).length; });
}"""

RAW_AT = """(points) => {
    const view = window.__twin;
    view.scene.updateMatrixWorld(true);
    const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
    const mats = o => (Array.isArray(o.material) ? o.material : [o.material]).filter(Boolean);
    const boxes = [];
    view.scene.traverse(o => {
        if (!(o.isMesh || o.isLine) || !shown(o) || !mats(o).some(m => m.transparent && m.opacity < 1)) return;
        if (!o.geometry) return;
        if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
        const bx = o.geometry.boundingBox && o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld);
        if (!bx || bx.isEmpty()) return;
        if (Math.hypot(bx.max.x - bx.min.x, bx.max.y - bx.min.y, bx.max.z - bx.min.z) > 30) return;
        boxes.push(bx.expandByScalar(0.15));
    });
    return points.map(([x, y, z]) => boxes.filter(b => b.containsPoint({x: x * %r, y: z * %r, z: -y * %r})).length);
}""" % (H.FT, H.FT, H.FT)


def _ghosts_at(page, points):
    """How many translucent things contain each pool-house point (building feet)."""
    return page.evaluate(GHOSTS_AT, [points, B])


def _raw_at(page, points):
    """The same, at the points' raw feet with no building transform."""
    return page.evaluate(RAW_AT, points)


def _seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    length2 = ax * ax + ay * ay
    t = 0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / length2))
    return math.dist(p, [a[0] + t * ax, a[1] + t * ay])


def _drawn_along(page, wall, tol=0.05):
    """Ids of the scene plan's pool-house walls lying along a reply wall that the scene draws."""
    plan = page.evaluate('() => window.__twin.plan')
    pool = next((b for b in plan.get('buildings') or [] if b['id'] == B), None)
    if pool is None:
        return []
    drawn = set(page.evaluate('(bid) => window.__twin.pieceIds(bid)', B))
    return [w['id'] for w in pool.get('walls') or [] if w.get('level') == wall['level'] and w.get('state') != 'ghost'
            and _seg_dist(w['from'], wall['from'], wall['to']) <= tol
            and _seg_dist(w['to'], wall['from'], wall['to']) <= tol and w['id'] in drawn]


def _wait(page, predicate, timeout, what):
    deadline = time.time() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.time() > deadline:
            raise AssertionError(what)
        page.wait_for_timeout(100)


def _stop_button(page):
    """The visible Stop: the chip's (Task 6) or the top bar's until then."""
    return page.locator('#editor-chip button:text-is("Stop"):visible, #editor-stop:visible').first


def _chip_text(page):
    chip = page.locator('#editor-chip')
    check(chip.count() == 1, '#editor-chip, the status chip, is missing from the top bar (Task 6)')
    return ' '.join(chip.inner_text().split())


def _money(text, pattern):
    m = re.search(pattern, text)
    return float(m.group(1).replace(',', '')) if m else None


def _spend(text):
    return _money(text, r'\$(\d[\d,]*\.\d\d) so far')


def _about(text):
    return _money(text, r'about \$(\d[\d,]*\.\d\d)')


def _ledger():
    from services import twin_cost
    return math.fsum(e['usd'] for e in twin_cost.entries())


def _open(page, s):
    H.open_editor(page, s)
    check(_ghosts(page) == 0, ('a page opened with no build streaming shows no build ghosts', _ghosts(page)))


def _wait_gate(page, reader, bid, timeout=60):
    """Wait until the draft is held at the gate and this tab drew every piece so far."""
    check(reader.at_gate.wait(timeout), ('test setup: the draft read reached the gate', reader.calls))
    pieces = _wait(page, lambda: (lambda p: p if len(p) >= AT_GATE else None)(_server_pieces(bid)), 10,
                   ('the engine publishes a piece event for each level and whole wall',
                    len(_server_pieces(bid)), reader.calls))
    check(len(pieces) == AT_GATE and [e['piece'].get('id') for e in pieces] == [l['id'] for l in LEVELS] + [w['id'] for w in KEPT],
          ('test setup: the levels and W1-W3 have arrived, the half wall has not',
           [(e['kind'], e['piece'].get('id')) for e in pieces]))
    _wait(page, lambda: _ghosts(page) == AT_GATE, 10,
          ('every piece that arrived is drawn as one ghost, and nothing else', _ghosts(page), AT_GATE))
    return pieces


def _check_kept_walls_settled(page):
    """W1-W3 stand settled in the scene; no ghost is left on them; the half wall never appears."""
    for wall in KEPT:
        check(_drawn_along(page, wall), ('a wall that had arrived whole stays and is drawn settled', wall['id']))
    check(not _drawn_along(page, WALLS[3], tol=0.5), ('the half wall at the cut is not kept', WALLS[3]))
    hits = _ghosts_at(page, [_mid(w) for w in KEPT])
    check(hits == [0] * len(KEPT), ('no ghost is left on a settled wall: it is solid now', hits))


# --- Task 5 ----------------------------------------------------------------------------

def scenario_pieces_appear_one_by_one():
    s = _serve()
    if s is None:
        return
    reader = _fresh()
    try:
        with s.browser(launch_args=H.GPU_ARGS) as page:
            _open(page, s)
            points = [_mid(w) for w in KEPT] + [CENTRE]
            check(_ghosts_at(page, points) == [0] * len(points),
                  ('test setup: nothing translucent where the pool house walls will go', _ghosts_at(page, points)))
            raw_before = _raw_at(page, [_mid(w) for w in KEPT])
            bid = _start(page)
            seen, deadline = [], time.time() + 90
            while time.time() < deadline and not reader.at_gate.is_set():
                count = _ghosts(page)
                arrived = len(_server_pieces(bid))
                check(count <= arrived, ('a ghost for a piece that has not arrived', count, arrived))
                if not seen or seen[-1] != count:
                    seen.append(count)
                page.wait_for_timeout(100)
            check(_step_status(bid) == 'running', ('test setup: the draft has not settled', _step_status(bid)))
            _wait_gate(page, reader, bid)
            seen.append(_ghosts(page))
            rising = sorted(set(c for c in seen if c > 0))
            check(len(rising) >= 3 and seen == sorted(seen),
                  ('the ghosts rise piece by piece across polls while the drawings are read', seen))
            hits = _ghosts_at(page, [_mid(w) for w in KEPT] + [CENTRE])
            check(all(h > hits[-1] for h in hits[:-1]),
                  ('each arrived wall is drawn translucent where it stands in the pool house', hits))
            check(_raw_at(page, [_mid(w) for w in KEPT]) == raw_before,
                  ('the ghosts are placed by the pool house\'s position and turn, not at the reply\'s raw feet',
                   _raw_at(page, [_mid(w) for w in KEPT]), raw_before))
            check(_step_status(bid) == 'running' and _build_state(page) == 'running',
                  ('the step has not settled while its ghosts show', _step_status(bid), _build_state(page)))
            page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_guided_ghosts.png'))
            reader.go.set()
            _wait(page, lambda: _build_state(page) == 'done', 90,
                  ('the released build finishes', _build_state(page)))
            _wait(page, lambda: _ghosts(page) == 0, 15, ('every ghost settles once its round lands', _ghosts(page)))
            for wall in WALLS[:4]:
                _wait(page, lambda: _drawn_along(page, wall), 15, ('the settled wall is drawn', wall['id']))
    finally:
        _quiet_engine()
    check(not H.unexpected(s.errors()), s.errors())


def scenario_stop_mid_walls_keeps_the_walls():
    s = _serve()
    if s is None:
        return
    reader = _fresh(chunk=64, delay=0.02)
    try:
        with s.browser(launch_args=H.GPU_ARGS) as page:
            _open(page, s)
            bid = _start(page)
            _wait_gate(page, reader, bid)
            stop = _stop_button(page)
            check(stop.count() == 1, 'Stop is visible while the drawings are read')
            pressed = time.monotonic()
            stop.click()
            check(reader.exited.wait(STOP_WITHIN + REQUEST_SLACK) and reader.exited_at - pressed <= STOP_WITHIN + REQUEST_SLACK,
                  ('Stop ends the paid read within 2 s', reader.exited_at and reader.exited_at - pressed, reader.calls))
            _wait(page, lambda: _build_state(page) == 'stopped', 5, ('the build reads stopped', _build_state(page)))
            from services import twin_store as ts
            _wait(page, lambda: any(r.get('partial') and (r.get('step') or {}).get('id') == 'draft' for r in ts.rounds()), 5,
                  ('the walls that arrived are published as a partial round', ts.rounds()[-3:]))
            _wait(page, lambda: _ghosts(page) == 0, 10,
                  ('the kept pieces settle with the partial round: no ghost is left', _ghosts(page)))
            _wait(page, lambda: all(_drawn_along(page, w) for w in KEPT), 10,
                  ('the walls shown before Stop stay, settled', [bool(_drawn_along(page, w)) for w in KEPT]))
            _check_kept_walls_settled(page)
            page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_guided_stopped.png'))
    finally:
        _quiet_engine()
    check(not H.unexpected(s.errors()), s.errors())


def scenario_two_tabs_see_the_same_pieces():
    # Review Focus 4: two tabs on the editor during a streaming build see the
    # same pieces in order, and a Stop from either ends it (here, the second).
    # The second tab is a second page of the same Chromium (its own context),
    # signed in as the same parent.
    s = _serve()
    if s is None:
        return
    reader = _fresh()
    errors_b = []
    try:
        with s.browser(launch_args=H.GPU_ARGS) as page:
            _open(page, s)
            bid = _start(page)
            _wait(page, lambda: _server_pieces(bid), 60, ('test setup: the first piece arrives', reader.calls))
            other = page.context.browser.new_page(viewport={'width': 1400, 'height': 1000})
            other.on('pageerror', lambda e: errors_b.append(str(e)))
            other.on('console', lambda m: m.type == 'error' and errors_b.append(m.text))
            try:
                H.open_editor(other, s)
                pieces = _wait_gate(page, reader, bid)
                _wait(other, lambda: _ghosts(other) == AT_GATE, 15,
                      ('the second tab draws the same pieces', _ghosts(other), AT_GATE))
                order = [e['seq'] for e in pieces]
                got_a, got_b = _ghost_seqs(page), _ghost_seqs(other)
                check(got_a == order and got_b == order,
                      ('both tabs show the same pieces in the order they arrived', got_a, got_b, order))
                stop = _stop_button(other)
                check(stop.count() == 1, 'Stop is visible in the second tab too')
                pressed = time.monotonic()
                stop.click()
                check(reader.exited.wait(STOP_WITHIN + REQUEST_SLACK)
                      and reader.exited_at - pressed <= STOP_WITHIN + REQUEST_SLACK,
                      ('a Stop from the second tab ends the paid read within 2 s',
                       reader.exited_at and reader.exited_at - pressed))
                for tab, name in ((other, 'the tab that stopped'), (page, 'the tab that started')):
                    _wait(tab, lambda: _build_state(tab) == 'stopped', 8, (f'{name} reads stopped', _build_state(tab)))
                    _wait(tab, lambda: _ghosts(tab) == 0, 10, (f'{name} settles the kept pieces', _ghosts(tab)))
                    _wait(tab, lambda: all(_drawn_along(tab, w) for w in KEPT), 10,
                          (f'{name} shows the kept walls', [bool(_drawn_along(tab, w)) for w in KEPT]))
                    _check_kept_walls_settled(tab)
            finally:
                other.close()
    finally:
        _quiet_engine()
    check(not H.unexpected(s.errors() + errors_b), s.errors() + errors_b)


# --- Task 6 ----------------------------------------------------------------------------

def scenario_stop_is_visible_while_working():
    s = _serve()
    if s is None:
        return
    reader = _fresh(chunk=64, delay=0.02)
    try:
        with s.browser(launch_args=H.GPU_ARGS) as page:
            H.open_editor(page, s)       # the chip needs no Task 5 hook
            text = _chip_text(page)
            check(page.locator('#editor-top #editor-chip').is_visible(), 'the chip is always in view in the top bar')
            check('Working' not in text and page.locator('#editor-chip button:text-is("Stop"):visible').count() == 0,
                  ('no build runs yet: no Working, no Stop', text))
            bid = _start(page)
            chip_stop = page.locator('#editor-chip button:text-is("Stop")')
            _wait(page, lambda: 'Working' in _chip_text(page) and chip_stop.first.is_visible(), 5,
                  ('a running build shows Working with Stop inside the chip', _chip_text(page)))
            check(reader.at_gate.wait(30), 'test setup: the draft read reached the gate')
            for _ in range(5):                        # Stop stays in view for the whole read
                text = _chip_text(page)
                check(re.search(r'\bWorking\b', text) and 'Waiting on you' not in text, ('the chip says Working', text))
                check(chip_stop.count() == 1 and chip_stop.is_visible(), ('Stop is visible inside the chip while Working', text))
                page.wait_for_timeout(400)
            estimate = (_api(page, 'GET', 'state')['body'].get('cost') or {}).get('estimate')
            check(isinstance(estimate, (int, float)) and estimate > 0,
                  ('api/house/editor/state carries the running build\'s estimate as cost.estimate', estimate))
            shown = _about(_chip_text(page))
            check(shown is not None and abs(shown - estimate) <= 0.005 + 1e-9,
                  ('the chip shows the estimate as about $x.xx', _chip_text(page), estimate))
            page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_guided_chip_working.png'))
            chip_stop.click()
            _wait(page, lambda: _build_state(page) == 'stopped', 5, ('Stop in the chip stops the build', _build_state(page)))
            _wait(page, lambda: not re.search(r'\bWorking\b', _chip_text(page)), 5,
                  ('a stopped build no longer says Working', _chip_text(page)))
            check(chip_stop.count() == 0 or not chip_stop.first.is_visible(), 'Stop leaves the chip once nothing runs')
    finally:
        _quiet_engine()
    check(not H.unexpected(s.errors()), s.errors())


def scenario_chip_spend_matches_the_ledger():
    # The piece-4 exit check: the spend on screen equals the sum of twin_cost
    # ledger entries for the household, before, during and after a stopped read.
    s = _serve()
    if s is None:
        return
    reader = _fresh(chunk=64, delay=0.02)
    try:
        with s.browser(launch_args=H.GPU_ARGS) as page:
            H.open_editor(page, s)       # the chip needs no Task 5 hook
            before = _ledger()
            check(before > 0, ('test setup: there is earlier spend', before))
            _wait(page, lambda: (lambda v: v is not None and abs(v - _ledger()) <= 0.005 + 1e-9)(_spend(_chip_text(page))), 5,
                  ('the chip shows the ledger total as $x.xx so far', _chip_text(page), _ledger()))
            bid = _start(page)
            check(reader.at_gate.wait(30), 'test setup: the draft read reached the gate')
            _wait(page, lambda: (lambda v: v is not None and abs(v - _ledger()) <= 0.005 + 1e-9)(_spend(_chip_text(page))), 5,
                  ('while the drawings are read the chip still shows the ledger total', _chip_text(page), _ledger()))
            _stop_button(page).click()
            from services import twin_cost
            _wait(page, lambda: [e for e in twin_cost.entries() if e.get('run') == bid and e.get('stage') == 'step:draft'], 5,
                  ('the stopped read is charged in the ledger', [e for e in twin_cost.entries() if e.get('run') == bid]))
            after = _ledger()
            check(after - before >= 0.01, ('test setup: the stopped read cost at least a cent', before, after))
            _wait(page, lambda: (lambda v: v is not None and abs(v - _ledger()) <= 0.005 + 1e-9)(_spend(_chip_text(page))), 10,
                  ('after Stop the chip shows the new ledger total', _chip_text(page), _ledger()))
            check(abs(_ledger() - after) < 1e-9, ('nothing more was charged after the Stop', after, _ledger()))
    finally:
        _quiet_engine()
    check(not H.unexpected(s.errors()), s.errors())


# --- final whole-branch review I1 ---------------------------------------------------------

def _without_pool_house(plan):
    plan['buildings'] = [b for b in plan['buildings'] if b['id'] != B]
    return plan


def scenario_a_fresh_building_shows_its_ghosts_rising():
    # The pool house was removed from the house (or the house started over): it stays in Your
    # place with its drawings, but the plan has no pool house until the build's first round lands.
    s = _serve()
    if s is None:
        return
    reader = _fresh()
    from services import twin_build as tb, twin_store as ts
    ts.push_round(_without_pool_house(H.household_plan()), 'build')
    try:
        with s.browser(launch_args=H.GPU_ARGS) as page:
            _open(page, s)
            check(page.evaluate("bid => !(window.__twin.plan.buildings || []).some(b => b.id === bid)", B),
                  'test setup: the scene has no pool house')
            bid = _start(page)
            seen, deadline = [], time.time() + 90
            while time.time() < deadline and not reader.at_gate.is_set():
                count = _ghosts(page)
                arrived = len(_server_pieces(bid))
                check(count <= arrived, ('a ghost for a piece that has not arrived', count, arrived))
                if not seen or seen[-1] != count:
                    seen.append(count)
                page.wait_for_timeout(100)
            _wait_gate(page, reader, bid)
            seen.append(_ghosts(page))
            rising = sorted(set(c for c in seen if c > 0))
            check(len(rising) >= 3 and seen == sorted(seen),
                  ('a building\'s first build shows its ghosts rising piece by piece', seen))
            check(page.evaluate("bid => !(window.__twin.plan.buildings || []).some(b => b.id === bid)", B),
                  'test setup: no round has landed yet, the scene still has no pool house')
            stage = next(e for e in tb.status(bid)['events'] if e['type'] == 'stage' and e.get('frame'))
            frame = stage['frame']
            a = math.radians(frame.get('rotation') or 0)
            px, py = frame['position']

            def at(p):
                return [math.cos(a) * p[0] - math.sin(a) * p[1] + px, math.sin(a) * p[0] + math.cos(a) * p[1] + py,
                        p[2] + (frame.get('base') or 0)]
            hits = _raw_at(page, [at(_mid(w)) for w in KEPT])
            check(all(h > 0 for h in hits), ('each arrived wall stands where the engine will place the pool house', hits, frame))
            page.screenshot(path=os.path.join(tempfile.gettempdir(), 'house_guided_fresh_building.png'))
            reader.go.set()
            _wait(page, lambda: _step_status(bid) == 'done', 60,
                  ('the released read lands as a round', [(x['id'], x['status']) for x in tb.status(bid)['steps']]))
            _wait(page, lambda: not [q for q in _ghost_seqs(page) if q <= _server_pieces(bid)[-1]['seq']], 15,
                  ('the read ghosts settle once its round lands', _ghost_seqs(page)))
            pool = next(b for b in ts.current()['buildings'] if b['id'] == B)
            check(pool['position'] == frame['position'] and (pool.get('rotation') or 0) == (frame.get('rotation') or 0),
                  ('the round put the pool house where its ghosts stood', pool['position'], frame))
    finally:
        _quiet_engine()
    check(not H.unexpected(s.errors()), s.errors())


SCENARIOS = [
    scenario_a_fresh_building_shows_its_ghosts_rising,
    scenario_pieces_appear_one_by_one,
    scenario_stop_mid_walls_keeps_the_walls,
    scenario_two_tabs_see_the_same_pieces,
    scenario_stop_is_visible_while_working,
    scenario_chip_spend_matches_the_ledger,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
