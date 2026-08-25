"""The family packing card, on the thing jsdom cannot answer: a real screen.

`test_packing_card_render.py` proves the markup wires up right in a real DOM;
this drives the real component in real chromium, using
`test_board_card_grid.py`'s bargain (skip rather than fail when playwright is
absent) and its technique — the actual `<script>` this component ships,
loaded into a page it fully controls, so there is nothing left to fake about
whether a tap does what the markup claims it does.

The regression this file exists for: **the board rebuilds every 20 seconds,
and a checklist that resets on poll is worse than no checklist** (the
design's own words). `packingCard`'s poll (`loadPacking`) used to replace
`outings` wholesale every time it ran. Two things followed from that, both
invisible to a source read:

  * a claim still in flight when a poll landed lost the object its own
    response was going to write into — the count that came back from the
    server updated a row nobody was looking at any more;
  * a poll that has not yet caught up with a tap in flight overwrote the
    optimistic count with what the server thought BEFORE that tap, so the
    tick visibly reverted until the claim's own response arrived (if it ever
    found the right object to arrive at).

`scenario_a_poll_racing_a_claim_does_not_reset_the_tick` constructs exactly
that race with a held-open fetch, and is the one that actually falls over on
the code as it stood before this file — see the report for the RED run.

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


# --- one outing, one stepper item — the fixture the tap scenarios share ----

def _one_item_day(packed=0, needed=2):
    return {
        'date': '2026-09-08', 'is_tomorrow': False,
        'outings': [
            {'key': 'd1:soccer', 'driver': 'Dad', 'color': '#2563eb', 'car': 'Van',
             'start': '2026-09-08T16:00:00', 'title': 'Soccer practice',
             'groups': [
                 {'kit_id': 'k1', 'kit': 'Soccer bag', 'people': ['ellie'],
                  'items': [{'key': 'k1:water bottle', 'label': 'Water bottle',
                             'needed': needed, 'packed': packed}]},
             ], 'packed': packed, 'needed': needed},
        ],
    }


# --- a ten-activity Saturday — every outing carries its own driver, time and
# a single needed-one item, so the fixture stays small while still standing
# in for "four activities a day, ten at a weekend" (the sizing brief this
# design was built against).
def _ten_activity_day():
    outings = []
    for i in range(10):
        hour = 7 + i
        packed = 0 if i == 0 else 1        # only the first is unfinished
        outings.append({
            'key': f'd1:ev{i}', 'driver': 'Dad', 'color': '#2563eb', 'car': 'Van',
            'start': f'2026-09-08T{hour:02d}:00:00',
            'title': f'Activity {i + 1}',
            'groups': [{'kit_id': f'k{i}', 'kit': f'Kit {i + 1}', 'people': ['ellie'],
                        'items': [{'key': f'k{i}:item', 'label': f'Item {i + 1}',
                                   'needed': 1, 'packed': packed}]}],
            'packed': packed, 'needed': 1,
        })
    return {'date': '2026-09-08', 'is_tomorrow': False, 'outings': outings}


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
# The claim handler tracks a running count per (outing, item) the same way
# the real endpoint does (packed = the claims filed so far, clamped to
# [0, needed]) — a fixed canned response would itself overwrite an
# optimistic tick with the wrong number the moment it resolved, which is a
# fixture bug indistinguishable from the real one this file exists to catch.
FETCH_STUB = r"""
window.__pk = { day: PK_DAY, dayCalls: 0, posts: [], claimGate: false,
                claimRelease: null, alerts: [], counts: {}, claimFailNext: false };
(window.__pk.day.outings || []).forEach(function (o) {
    (o.groups || []).forEach(function (g) {
        (g.items || []).forEach(function (it) {
            window.__pk.counts[o.key + '::' + it.key] = it.packed;
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


# ── (a) a ten-activity Saturday stays readable ──────────────────────────────

def scenario_a_ten_activity_saturday_stays_readable():
    """One row per outing, one expanded — the density shape this design was
    sized for ("four activities a day, ten at a weekend"). Readability is a
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
            rows = page.locator('#pk-root .rounded-2xl')
            check(rows.count() == 10,
                  f"a ten-activity day drew {rows.count()} rows, not one per outing")
            # Exactly one row's group content is open — the first unfinished
            # outing, the one look worth taking without a tap at all.
            expanded = page.locator('#pk-root .border-t.border-gray-800')
            check(expanded.count() == 1,
                  f"{expanded.count()} outings are expanded at once, not one")
            expanded_row = expanded.first.locator('xpath=..')
            check('Activity 1' in expanded_row.inner_text(),
                  f"the expanded row is not the first unfinished outing: "
                  f"{expanded_row.inner_text()[:80]!r}")
            # Rows stack without overlapping and stay inside the tile — the
            # geometry a source read cannot see at all.
            boxes = [rows.nth(i).bounding_box() for i in range(10)]
            check(all(b is not None for b in boxes), "a row failed to lay out at all")
            for prev, cur in zip(boxes, boxes[1:]):
                check(cur['y'] + 0.5 >= prev['y'] + prev['height'],
                      f"two outing rows overlap: {prev} then {cur}")
                check(prev['height'] > 20,
                      f"a row collapsed to {prev['height']}px — unreadable")
            tile_width = page.locator('#pk-root').bounding_box()['width']
            check(all(b['width'] <= tile_width + 1 for b in boxes),
                  f"a row ({[b['width'] for b in boxes]}) ran wider than the "
                  f"tile ({tile_width})")
        finally:
            browser.close()


# ── (b) tapping + moves the item count and the outing's progress ───────────

def scenario_tapping_plus_moves_the_item_and_the_outing_fraction():
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []}, _one_item_day(0, 2))
            plus = page.locator('#pk-root button:text-is("+")')
            count = plus.locator('xpath=preceding-sibling::span[1]')
            outing_badge = page.locator('#pk-root span.font-black').first
            check(count.inner_text() == '0/2', f"the stepper did not start at 0/2: {count.inner_text()}")
            check(outing_badge.inner_text() == '0/2',
                  f"the outing's own fraction did not start at 0/2: {outing_badge.inner_text()}")
            plus.click()
            check(count.inner_text() == '1/2', f"the tap did not move the item's count: {count.inner_text()}")
            check(outing_badge.inner_text() == '1/2',
                  f"the tap did not move the outing's own fraction: {outing_badge.inner_text()}")
            plus.click()
            check(count.inner_text() == '2/2', f"a second tap did not reach 2/2: {count.inner_text()}")
            check(outing_badge.inner_text() == '2/2',
                  f"the outing did not reach 2/2: {outing_badge.inner_text()}")
            posts = page.evaluate("window.__pk.posts")
            check(len(posts) == 2, f"two taps should file two claims, filed {len(posts)}")
        finally:
            browser.close()


# ── (c) THE regression: a poll racing a claim must not reset the tick ──────

def scenario_a_poll_racing_a_claim_does_not_reset_the_tick():
    """The board's own poll fires on a clock a tap knows nothing about. This
    holds the claim's response open, taps `+`, and forces a poll to land
    WHILE that response is still pending — with the poll answering exactly
    the pre-tap data, the same shape a poll that has not yet caught up with a
    just-filed claim would have. The count must stay at the tapped value
    throughout, and must still be right once the claim's own response
    finally lands.

    This is the scenario that falls over on the card as it stood before this
    task: `loadPacking` replaced `outings` wholesale, so the racing poll's
    stale numbers overwrote the optimistic tick, and the claim's own
    response — arriving after — wrote into an object no longer in `outings`
    and never reached the screen at all.
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

            plus = page.locator('#pk-root button:text-is("+")')
            count = plus.locator('xpath=preceding-sibling::span[1]')
            outing_badge = page.locator('#pk-root span.font-black').first

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
            check(outing_badge.inner_text() == '1/2',
                  f"the outing's own fraction was reset by the racing poll: "
                  f"{outing_badge.inner_text()}")

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
            check(outing_badge.inner_text() == '1/2',
                  f"the outing's fraction did not settle either: {outing_badge.inner_text()}")
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
    rolled-back local one."""
    sp = _chromium()
    if sp is None:
        return
    with sp() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _boot(page, {'interactive': True, 'members': []}, _one_item_day(0, 2))
            plus = page.locator('#pk-root button:text-is("+")')
            count = plus.locator('xpath=preceding-sibling::span[1]')
            outing_badge = page.locator('#pk-root span.font-black').first
            check(count.inner_text() == '0/2', f"the stepper did not start at 0/2: {count.inner_text()}")

            # Arm the next claim POST to fail, and move the "server" to a
            # count (1) that is neither the pre-tap value (0) nor whatever the
            # optimistic tap will show (1 momentarily, then rolled back to 0)
            # — distinct enough that landing on it can only mean the
            # reconcile's GET actually won, not a coincidence.
            page.evaluate("window.__pk.claimFailNext = true")
            page.evaluate(
                "window.__pk.day.outings[0].groups[0].items[0].packed = 1;"
                "window.__pk.day.outings[0].packed = 1;"
                "window.__pk.counts['d1:soccer::k1:water bottle'] = 1;")

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
            check(outing_badge.inner_text() == '1/2',
                  f"the outing's own fraction did not reconcile either: "
                  f"{outing_badge.inner_text()}")
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
            plus = page.locator('#pk-root button:text-is("+")')
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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing-card browser scenarios passed")
