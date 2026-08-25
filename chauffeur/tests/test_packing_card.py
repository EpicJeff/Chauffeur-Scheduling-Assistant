"""The family day card, on the thing jsdom cannot answer: a real screen.

`test_packing_card_render.py` proves the markup wires up right in a real DOM;
this drives the real component in real chromium, using
`test_board_card_grid.py`'s bargain (skip rather than fail when playwright is
absent) and its technique — the actual `<script>` this component ships,
loaded into a page it fully controls, so there is nothing left to fake about
whether a tap does what the markup claims it does.

Rewritten for the family_day_plan reshape (task 3, `docs/family_day_design.md`):
the feed is `blocks`, not `outings`; a block is a container only at two or
more events, with its inner lines always visible; the pill is two states
only (`pkPillState`); nothing auto-expands — `expandedKeys` is a plain Set a
tap toggles, and the board's 30-second poll must never collapse whatever
somebody just opened, exactly as it must never reset a tick in flight. That
last property was already new surface `test_packing_card_render.py` cannot
reach (jsdom never actually schedules a poll racing a real click), so this
file is still where it gets proven.

The regression this file has always existed for: **the board rebuilds every
20 seconds, and a checklist that resets on poll is worse than no checklist**
(the design's own words). `scenario_a_poll_racing_a_claim_does_not_reset_the_tick`
constructs exactly that race with a held-open fetch.

Run from chauffeur/:  python tests/test_packing_card.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_packing_card_'))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')
SCRATCH = tempfile.mkdtemp(prefix='chauffeur_packing_card_run_')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# --- one block, one stepper item — the fixture the tap scenarios share -----
# A bare at-home event block (kind `event`) is enough to carry the shared
# claim mechanics: a container's expansion is identical, just nested under
# one more `data-fd-key` box (proven separately by scenario (f)).

def _one_item_day(packed=0, needed=2):
    return {
        'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
        'blocks': [
            {'kind': 'event', 'key': 'home:1', 'event_id': 1,
             'title': 'Soccer practice',
             'start': '2026-09-08T16:00:00', 'end': '2026-09-08T17:00:00',
             'canceled': False, 'covered_by': None,
             'groups': [
                 {'kit_id': 'k1', 'kit': 'Soccer bag', 'people': ['ellie'],
                  'items': [{'key': 'k1:water bottle', 'label': 'Water bottle',
                             'needed': needed, 'packed': packed}]},
             ], 'packed': packed, 'needed': needed},
        ],
    }


# --- a two-block day: a container beside a plain block — the fixture
# scenario (f) needs to prove one block's expansion leaves its sibling alone.
def _two_block_day():
    return {
        'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
        'blocks': [
            {'kind': 'outing', 'key': 'd1:soccer', 'driver': 'Dad',
             'driver_id': 'd1', 'color': '#2563eb', 'car': 'Van',
             'start': '2026-09-08T16:00:00', 'end': '2026-09-08T18:00:00',
             'events': [
                 {'id': 'soccer', 'title': 'Soccer', 'start': '2026-09-08T16:00:00'},
                 {'id': 'band', 'title': 'Band practice', 'start': '2026-09-08T17:00:00'},
             ],
             'groups': [
                 {'kit_id': 'k1', 'kit': 'Soccer bag', 'people': ['ellie'],
                  'items': [{'key': 'k1:water bottle', 'label': 'Water bottle',
                             'needed': 1, 'packed': 0}]},
             ], 'packed': 0, 'needed': 1},
            {'kind': 'event', 'key': 'home:1', 'event_id': 1, 'title': 'Piano',
             'start': '2026-09-08T09:00:00', 'end': '2026-09-08T09:30:00',
             'canceled': False, 'covered_by': None,
             'groups': [
                 {'kit_id': 'k2', 'kit': 'Music bag', 'people': ['ellie'],
                  'items': [{'key': 'k2:sheet music', 'label': 'Sheet music',
                             'needed': 1, 'packed': 0}]},
             ], 'packed': 0, 'needed': 1},
        ],
    }


# --- a ten-activity Saturday: ten TOP-LEVEL blocks, one of which is a
# three-event container and two of which are bare at-home events — standing
# in for "four activities a day, ten at a weekend" (the sizing brief this
# design was built against) while keeping the fixture small.
def _ten_activity_day():
    blocks = [
        {'kind': 'event', 'key': 'home:1', 'event_id': 1, 'title': 'Piano',
         'start': '2026-09-08T07:00:00', 'end': '2026-09-08T07:30:00',
         'canceled': False, 'covered_by': None, 'groups': [],
         'packed': 0, 'needed': 0},
        {'kind': 'event', 'key': 'home:2', 'event_id': 2, 'title': 'Reading',
         'start': '2026-09-08T08:00:00', 'end': '2026-09-08T08:30:00',
         'canceled': False, 'covered_by': None, 'groups': [],
         'packed': 0, 'needed': 0},
        {'kind': 'outing', 'key': 'd1:triple', 'driver': 'Dad', 'driver_id': 'd1',
         'color': '#2563eb', 'car': 'Van',
         'start': '2026-09-08T09:00:00', 'end': '2026-09-08T13:00:00',
         'events': [
             {'id': 'e1', 'title': 'Soccer', 'start': '2026-09-08T09:00:00'},
             {'id': 'e2', 'title': 'Lunch stop', 'start': '2026-09-08T11:00:00'},
             {'id': 'e3', 'title': 'Band', 'start': '2026-09-08T12:00:00'},
         ],
         'groups': [{'kit_id': 'kt', 'kit': 'Trip bag', 'people': ['ellie'],
                     'items': [{'key': 'kt:water', 'label': 'Water',
                                'needed': 1, 'packed': 0}]}],
         'packed': 0, 'needed': 1},
    ]
    for i in range(7):
        hour = 14 + i
        blocks.append({
            'kind': 'event', 'key': f'act:{i}', 'event_id': 100 + i,
            'title': f'Activity {i + 1}',
            'start': f'2026-09-08T{hour:02d}:00:00',
            'end': f'2026-09-08T{hour:02d}:30:00',
            'canceled': False, 'covered_by': None,
            'groups': [{'kit_id': f'k{i}', 'kit': f'Kit {i + 1}', 'people': ['ellie'],
                        'items': [{'key': f'k{i}:item', 'label': f'Item {i + 1}',
                                   'needed': 1, 'packed': 0}]}],
            'packed': 0, 'needed': 1,
        })
    return {'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [], 'blocks': blocks}


_CACHE = {}


def _alpine_source():
    """The real Alpine build, resolved the way node resolves it — from a
    scratch dir under the user profile, the same trick the jsdom harnesses
    rely on (node walks up looking for `node_modules`). Returns None (having
    said why) rather than raising, so callers can skip cleanly."""
    if 'alpine' in _CACHE:
        return _CACHE['alpine']
    _CACHE['alpine'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — alpine was not resolvable')
        return None
    proc = subprocess.run(
        [node, '-e', "console.log(require.resolve('alpinejs/dist/cdn.js'))"],
        capture_output=True, text=True, cwd=SCRATCH)
    if proc.returncode != 0:
        print('  skip  alpinejs not resolvable — npm install alpinejs')
        return None
    with open(proc.stdout.strip(), encoding='utf-8') as f:
        _CACHE['alpine'] = f.read()
    return _CACHE['alpine']


def _tailwind_css():
    if 'tailwind' in _CACHE:
        return _CACHE['tailwind']
    path = os.path.join(TPL, '..', 'static', 'tailwind.css')
    with open(path, encoding='utf-8') as f:
        _CACHE['tailwind'] = f.read()
    return _CACHE['tailwind']


# The fetch stub every scenario shares, fully controlled from Python through
# `window.__pk`. `api/packing/day` always answers with whatever
# `window.__pk.day` currently holds — a poll that should see "no change" is
# simply a poll that runs again before the test moves that value, which is
# what makes the race scenario constructible on demand rather than by luck.
#
# The claim handler tracks a running count per (block, item) the same way
# the real endpoint does (packed = the claims filed so far, clamped to
# [0, needed]) — a fixed canned response would itself overwrite an
# optimistic tick with the wrong number the moment it resolved, which is a
# fixture bug indistinguishable from the real one this file exists to catch.
# The wire field is still `outing_key` regardless of block kind — that field
# name is the API contract (`main.py::packing_claim`), unchanged by the
# reshape.
FETCH_STUB = r"""
window.__pk = { day: PK_DAY, dayCalls: 0, posts: [], claimGate: false,
                claimRelease: null, alerts: [], counts: {}, claimFailNext: false };
(window.__pk.day.blocks || []).forEach(function (b) {
    (b.groups || []).forEach(function (g) {
        (g.items || []).forEach(function (it) {
            window.__pk.counts[b.key + '::' + it.key] = it.packed;
        });
    });
});
window.fetch = function (url, opt) {
    url = String(url);
    if (url.indexOf('api/packing/day') !== -1) {
        window.__pk.dayCalls++;
        // A real `fetch().json()` deserializes a FRESH object graph every
        // time — handing back the literal same reference would hide exactly
        // the bug this file exists to catch, since nothing would ever be
        // orphaned by a poll that never actually produces new objects.
        var snapshot = JSON.parse(JSON.stringify(window.__pk.day));
        return Promise.resolve({ ok: true,
            json: function () { return Promise.resolve(snapshot); } });
    }
    if (url.indexOf('api/packing/claim') !== -1) {
        var body = JSON.parse((opt && opt.body) || '{}');
        window.__pk.posts.push(body);
        var key = body.outing_key + '::' + body.item_key;
        // A once-only failure the test arms ahead of the tap: the POST never
        // applies (no count update), so `pkClaim`'s catch rolls the local
        // count back and re-fetches to reconcile with whatever the server
        // (here, `window.__pk.day`, moved independently by the test to stand
        // in for "another device already changed this") actually thinks.
        if (window.__pk.claimFailNext) {
            window.__pk.claimFailNext = false;
            return Promise.resolve({ ok: false,
                json: function () { return Promise.resolve({ ok: false }); } });
        }
        var cur = Math.max(0, (window.__pk.counts[key] || 0) + (body.delta || 0));
        window.__pk.counts[key] = cur;
        var answer = { ok: true,
            json: function () { return Promise.resolve({ ok: true, packed: cur, xp: 0 }); } };
        if (window.__pk.claimGate) {
            return new Promise(function (resolve) { window.__pk.claimRelease = function () { resolve(answer); }; });
        }
        return Promise.resolve(answer);
    }
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); } });
};
window.showGlobalAlert = function (msg) { window.__pk.alerts.push(msg); };
"""


def _render_html(cfg, day_json, tile_width=480):
    """The real macro AND the real logic script, through the app's own Jinja
    environment so `{% import %}` / `{% include %}` resolve against the real
    files — the same split `board_tile_body.html` / `home.html` make between
    them. Alpine and the fetch stub are plain inline scripts, in DOCUMENT
    ORDER ahead of Alpine's own boot, the same ordering `set_content` gives
    every other harness in this repo that fakes a network."""
    import main
    cfg_json = json.dumps({'data': cfg})
    stub = FETCH_STUB.replace('PK_DAY', json.dumps(day_json))
    alpine = _alpine_source()
    src = (
        "{% import 'components/packing_card.html' as packing %}"
        "<!doctype html><html><head><style>" + _tailwind_css() + "</style></head>"
        "<body style=\"background:#111827;margin:0;padding:24px\">"
        "<script>" + stub + "</script>"
        "<div style=\"width:" + str(tile_width) + "px\" class=\"tile\">"
        "<div id=\"pk-root\" x-data='packingCard(" + cfg_json + ", \"\")' "
        "x-init=\"startPacking()\">"
        "{{ packing.rows() }}"
        "</div>"
        "{% include 'components/agenda_row.html' %}"
        "{% include 'components/packing_card.html' %}"
        "</div>"
        "<script>" + alpine + "</script>"
        "</body></html>"
    )
    return main.templates.env.from_string(src).render()


def _boot(pw_page, cfg, day_json, tile_width=480):
    pw_page.set_content(_render_html(cfg, day_json, tile_width))
    pw_page.wait_for_function(
        "document.getElementById('pk-root') && window.Alpine "
        "&& Alpine.$data(document.getElementById('pk-root')).pkLoaded === true",
        timeout=5000)
    return pw_page


def _chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  skip  playwright not installed — the packing card was not run")
        return None
    if _alpine_source() is None:
        return None
    return sync_playwright


def _row(page, key):
    return page.locator(f'#pk-root [data-fd-key="{key}"]')


def _expand(page, key):
    """The only way any item reaches the DOM now: a tap on the block's own
    header button. `_row(...).locator('button').first` is safe to use as the
    header even after other buttons exist elsewhere on the page, since it is
    scoped to this one block's wrapper."""
    _row(page, key).locator('button').first.click()


# ── (a) a ten-activity Saturday stays readable ──────────────────────────────

def scenario_a_ten_activity_saturday_stays_readable():
    """One row per BLOCK — not per event — is the density shape this design
    was sized for ("four activities a day, ten at a weekend"). The
    three-event container's inner lines are always visible without a tap;
    nothing else is, because nothing auto-expands any more. Readability is a
    real-layout question: the rows must actually stack without overlapping
    and without spilling past the tile's own width, which jsdom cannot see at
    all (it does no layout)."""
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []},
                  _ten_activity_day(), tile_width=480)
            rows = page.locator('#pk-root [data-fd-key]')
            check(rows.count() == 10,
                  f"a ten-block day drew {rows.count()} top-level rows, not one per block")
            inner = page.locator('#pk-root .fd-inner-line')
            check(inner.count() == 3,
                  f"the three-event container should show three always-visible "
                  f"inner lines, drew {inner.count()}")
            inner_texts = inner.all_inner_texts()
            for title in ('Soccer', 'Lunch stop', 'Band'):
                check(any(title in t for t in inner_texts),
                      f"an inner line for {title!r} is missing: {inner_texts}")
            # Nothing auto-expands: no claim controls (tick or stepper) exist
            # anywhere in the DOM before any tap, and every button visible is
            # exactly one header per block.
            buttons = page.locator('#pk-root button')
            check(buttons.count() == 10,
                  f"nothing should be expanded yet, but {buttons.count()} buttons "
                  f"exist (want exactly 10 row headers)")
            # Rows stack without overlapping and stay inside the tile — the
            # geometry a source read cannot see at all.
            boxes = [rows.nth(i).bounding_box() for i in range(10)]
            check(all(b is not None for b in boxes), "a row failed to lay out at all")
            for prev, cur in zip(boxes, boxes[1:]):
                check(cur['y'] + 0.5 >= prev['y'] + prev['height'],
                      f"two blocks overlap: {prev} then {cur}")
                check(prev['height'] > 20,
                      f"a row collapsed to {prev['height']}px — unreadable")
            tile_width = page.locator('#pk-root').bounding_box()['width']
            check(all(b['width'] <= tile_width + 1 for b in boxes),
                  f"a row ({[b['width'] for b in boxes]}) ran wider than the "
                  f"tile ({tile_width})")
        finally:
            browser.close()


# ── (b) tapping + moves the item count and the block's pill ────────────────

def scenario_tapping_plus_moves_the_item_and_the_outing_fraction():
    """Items no longer draw before a tap, so this expands the block first,
    then ticks the stepper item to its cap and watches the pill go from
    amber ("N to pack") down to the done state at zero remaining."""
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []}, _one_item_day(0, 2))
            row = _row(page, 'home:1')
            check(row.locator('.pk-pill-amber').count() == 1
                  and '2 to pack' in row.locator('.pk-pill-amber').inner_text(),
                  "the block should start with an amber '2 to pack' pill")
            _expand(page, 'home:1')
            plus = row.locator('button:text-is("+")')
            count = plus.locator('xpath=preceding-sibling::span[1]')
            check(count.inner_text() == '0/2', f"the stepper did not start at 0/2: {count.inner_text()}")
            plus.click()
            check(count.inner_text() == '1/2', f"the tap did not move the item's count: {count.inner_text()}")
            check('1 to pack' in row.locator('.pk-pill-amber').inner_text(),
                  f"the pill did not decrement: {row.locator('.pk-pill-amber').inner_text()}")
            plus.click()
            check(count.inner_text() == '2/2', f"a second tap did not reach 2/2: {count.inner_text()}")
            check(row.locator('.pk-pill-amber').count() == 0,
                  "the pill is still amber at zero remaining")
            check(row.locator('.pk-pill-done').count() == 1,
                  "the pill did not flip to the done state at zero remaining")
            posts = page.evaluate("window.__pk.posts")
            check(len(posts) == 2, f"two taps should file two claims, filed {len(posts)}")
        finally:
            browser.close()


# ── (c) THE regression: a poll racing a claim must not reset the tick, and
#        must not collapse a block somebody just opened ────────────────────

def scenario_a_poll_racing_a_claim_does_not_reset_the_tick():
    """The board's own poll fires on a clock a tap knows nothing about. This
    expands the block, holds the claim's response open, taps `+`, and forces
    a poll to land WHILE that response is still pending — with the poll
    answering exactly the pre-tap data, the same shape a poll that has not
    yet caught up with a just-filed claim would have. The count must stay at
    the tapped value throughout, and must still be right once the claim's
    own response finally lands. `expandedKeys` survival is new surface this
    reshape introduced: a poll rebuilding `blocks` wholesale must not also
    reset which block a person just tapped open.
    """
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []}, _one_item_day(0, 2))
            check(page.evaluate("window.__pk.dayCalls") == 1,
                  "the mount did not do its one initial GET")

            _expand(page, 'home:1')
            row = _row(page, 'home:1')
            plus = row.locator('button:text-is("+")')
            count = plus.locator('xpath=preceding-sibling::span[1]')

            # Hold the claim's response open, then tap.
            page.evaluate("window.__pk.claimGate = true")
            plus.click()
            check(count.inner_text() == '1/2',
                  f"the optimistic tap did not move the count at all: {count.inner_text()}")

            # A poll lands WHILE the claim above is still waiting on its
            # answer, and sees exactly the pre-tap data — the fetch stub's
            # `day` was never moved, so this is the poll racing the tap.
            page.evaluate(
                "Alpine.$data(document.getElementById('pk-root')).loadPacking()")
            check(page.evaluate("window.__pk.dayCalls") == 2,
                  "the manual poll never actually fetched")
            check(count.inner_text() == '1/2',
                  f"a poll that has not caught up with the tap reset the tick "
                  f"back to what the server thought before it: {count.inner_text()}")
            # The block must still be open — a poll rebuilding `blocks`
            # wholesale collapsing whatever was just tapped open would be as
            # unusable as one that reset a tick.
            check(plus.count() == 1,
                  "the racing poll collapsed the block someone just expanded")

            # Now let the claim's own response land, with the server's real
            # answer — and confirm it reaches the CURRENT row, not an object
            # the racing poll above already replaced.
            page.evaluate("window.__pk.claimRelease()")
            page.wait_for_function(
                "Alpine.$data(document.getElementById('pk-root')).pkPending.size === 0",
                timeout=2000)
            check(count.inner_text() == '1/2',
                  f"the claim's own response did not settle on the count the "
                  f"tap made: {count.inner_text()}")
            check(not page.evaluate("window.__pk.alerts.length"),
                  f"the tick survived but still complained: {page.evaluate('window.__pk.alerts')}")
        finally:
            browser.close()


# ── (c2) a failed claim rolls back AND the reconciling re-fetch actually
#         adopts what the server says, rather than the guard silently
#         re-discarding it ─────────────────────────────────────────────────

def scenario_a_failed_claims_reconcile_adopts_the_server_count():
    """`pkClaim`'s catch path rolls the optimistic tick back to `prev`, alerts,
    and re-fetches so the card recovers the server's real count. Fix round
    finding #2: that re-fetch used to run while the item's key was STILL
    marked pending (`pkPending.delete(key)` lived only in the `finally`,
    after the catch's own `await this.loadPacking()` had already resolved),
    so `loadPacking()`'s own pending-guard — the thing rule 2's poll-race fix
    added — saw a pending key during the very re-fetch meant to clear it, kept
    the just-rolled-back LOCAL count instead of the incoming one, and threw
    away the server's answer this fetch exists to recover in the first place.

    This arms a claim to fail once, moves the fixture's `day` (the stand-in
    for the server, e.g. another device having already ticked this item) to a
    count that differs from both the pre-tap and rolled-back value, taps, and
    asserts the card lands on the SERVER's number, not stuck at the
    rolled-back local one. Field rename only from the pre-reshape version:
    `window.__pk.day.blocks[0]` in place of `.outings[0]`, and the block
    expanded first since items no longer draw before a tap."""
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []}, _one_item_day(0, 2))
            _expand(page, 'home:1')
            row = _row(page, 'home:1')
            plus = row.locator('button:text-is("+")')
            count = plus.locator('xpath=preceding-sibling::span[1]')
            check(count.inner_text() == '0/2', f"the stepper did not start at 0/2: {count.inner_text()}")

            # Arm the next claim POST to fail, and move the "server" to a
            # count (1) that is neither the pre-tap value (0) nor whatever the
            # optimistic tap will show (1 momentarily, then rolled back to 0)
            # — distinct enough that landing on it can only mean the
            # reconcile's GET actually won, not a coincidence.
            page.evaluate("window.__pk.claimFailNext = true")
            page.evaluate(
                "window.__pk.day.blocks[0].groups[0].items[0].packed = 1;"
                "window.__pk.day.blocks[0].packed = 1;"
                "window.__pk.counts['home:1::k1:water bottle'] = 1;")

            plus.click()
            check(count.inner_text() == '1/2',
                  f"the optimistic tap did not move the count at all: {count.inner_text()}")

            # Let the failed POST, the rollback, and the reconciling re-fetch
            # all settle.
            page.wait_for_function(
                "Alpine.$data(document.getElementById('pk-root')).pkPending.size === 0",
                timeout=5000)
            check(page.evaluate("window.__pk.alerts.length") == 1,
                  f"a failed claim should alert exactly once: {page.evaluate('window.__pk.alerts')}")
            check(count.inner_text() == '1/2',
                  f"the reconcile did not adopt the server's count (1) — it "
                  f"landed on {count.inner_text()!r} instead, which is what a "
                  f"pending guard still held during the reconcile would produce")
        finally:
            browser.close()


# ── (d) an item at `needed` cannot be pushed past it ────────────────────────

def scenario_an_item_at_needed_cannot_be_pushed_past_it():
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []}, _one_item_day(1, 2))
            _expand(page, 'home:1')
            row = _row(page, 'home:1')
            plus = row.locator('button:text-is("+")')
            count = plus.locator('xpath=preceding-sibling::span[1]')
            plus.click()
            check(count.inner_text() == '2/2', f"the tap to the cap did not land: {count.inner_text()}")
            check(plus.is_disabled(), "an item at `needed` still has a live + button")
            posts_before = page.evaluate("window.__pk.posts.length")
            # A real browser refuses to fire a click handler on a genuinely
            # disabled button, even forced — which is the point of asserting
            # this in chromium rather than trusting the `disabled` attribute
            # read alone.
            plus.click(force=True)
            check(count.inner_text() == '2/2',
                  f"forcing the tap past `needed` moved the count anyway: {count.inner_text()}")
            check(page.evaluate("window.__pk.posts.length") == posts_before,
                  "a click on a disabled + button still filed a claim")
        finally:
            browser.close()


# ── (e) expanding one block leaves the others at rest ───────────────────────

def scenario_expanding_one_block_leaves_the_others_at_rest():
    """Tap one block open on a shared wall and the next person's block must
    not move — `expandedKeys` is per-key, not a single "the open one" slot.
    This taps the container and checks its own items reached the DOM while
    the sibling block still shows none of its own."""
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []}, _two_block_day())
            container = _row(page, 'd1:soccer')
            sibling = _row(page, 'home:1')
            check('Water bottle' not in container.inner_text(),
                  "the container's items drew before any tap")
            check('Sheet music' not in sibling.inner_text(),
                  "the sibling's items drew before any tap")

            _expand(page, 'd1:soccer')

            check('Water bottle' in container.inner_text(),
                  f"the tapped container's own item did not reach the DOM: "
                  f"{container.inner_text()[:200]}")
            check('Sheet music' not in sibling.inner_text(),
                  f"expanding the container also expanded its sibling: "
                  f"{sibling.inner_text()[:200]}")
        finally:
            browser.close()


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    ran_for_real = _chromium() is not None
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    if ran_for_real:
        print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing-card browser "
              f"scenarios passed (chromium actually ran)")
    else:
        print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing-card browser "
              f"scenarios passed (SKIPPED — playwright/chromium/node/alpine "
              f"was not available; nothing was actually proven)")
