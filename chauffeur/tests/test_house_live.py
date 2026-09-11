"""The Home in real chromium against the served app.

Source pins cannot see whether the dollhouse actually boots, whether the
two-level camera enters and leaves, or whether the lean-in still wears the
board's card after the transplant. Drive the real page (source-reading
tests miss runtime breaks): boot at the exterior, walk in, lean in, walk
out — with zero console errors, the live-app harness's whole point.

Run from chauffeur/:  python tests/test_house_live.py
Set HOUSE_SHOTS=<dir> to also save exterior/kitchen/lean-in screenshots.
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_house_live_'))

from live_app import live_app


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


INVARIANT_JS = """() => {
  const S = window.__hpScene;
  if (!S) return { err: 'no scene captured' };
  // use classifies EVERY mesh (merged included) into its material's
  // zone-usage set, so a merged mesh that somehow crossed a zone
  // boundary is still caught. mats/geos/meshes stay scoped to the
  // never-merged survivors, because the ratio gates below measure how
  // much of THAT population batched — merged output would flatter the
  // ratio without reflecting new sharing.
  const use = new Map(), geos = new Set(), mats = new Set();
  let meshes = 0;
  S.traverse(o => {
    if (!o.isMesh || !o.material || Array.isArray(o.material)) return;
    let z = '';
    for (let p = o; p; p = p.parent)
      if (p.userData && p.userData.zone) { z = p.userData.zone; break; }
    if (!use.has(o.material.uuid)) use.set(o.material.uuid, new Set());
    use.get(o.material.uuid).add(z);
    if (o.userData && o.userData.merged) return;
    meshes += 1;
    mats.add(o.material.uuid);
    if (o.geometry) geos.add(o.geometry.uuid);
  });
  let crossing = 0;
  use.forEach(s => { if (s.size > 1) crossing += 1; });
  return { meshes, materials: mats.size, geometries: geos.size, crossing };
}"""


def _seed():
    """An event TODAY whatever the clock says (the overlay-live idiom), so
    the wall calendar's card has something to show on the lean-in."""
    from services import storage
    now = datetime.datetime.now().replace(microsecond=0)
    late = now.replace(hour=23, minute=59, second=0)
    start = now + datetime.timedelta(minutes=45)
    end = start + datetime.timedelta(hours=1)
    if end > late:
        start, end = now - datetime.timedelta(minutes=5), late
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color': '#38bdf8'})
    # Pin the cache FUNCTION, not the row: the server's own boot refresh
    # rebuilds the cache from the (empty) calendars moments after boot and
    # would silently erase a seeded row mid-test (test_kitchen_state idiom).
    sched = {
        'events': [{'id': 'e1', 'title': 'Soccer practice',
                    'start': start.isoformat(), 'end': end.isoformat()}],
        'assignments': {'e1': 'd1'},
    }
    storage.get_cached_schedule = lambda: sched
    # H2: two cars through the real model (no HA entities: both present,
    # no warnings, garage calm) so the garage has someone to park.
    from models.schemas import Car as CarModel
    storage.add_car(CarModel(name='Red Truck', body_type='truck',
                             color_code='#c9473d', seat_capacity=4).model_dump())
    storage.add_car(CarModel(name='Blue Minivan', body_type='minivan',
                             color_code='#3b82f6', seat_capacity=7).model_dump())
    # H3: children hang backpacks in the mudroom
    storage.add_member({'id': 'k1', 'name': 'Maya', 'role': 'child'})
    storage.add_member({'id': 'k2', 'name': 'Finn', 'role': 'child'})


def scenario_the_house_boots_enters_and_leans_in():
    # Seed AFTER boot: startup refresh rebuilds the schedule cache, so a
    # cache written before the server comes up is gone by the first request.
    served = live_app()
    if served is None:
        return
    _seed()
    shots = os.environ.get('HOUSE_SHOTS', '')
    with served.browser() as page:
        from house_probe import THREE_WRAP
        with open('static/vendor/three.min.js', 'rb') as fh:
            _patched = fh.read() + THREE_WRAP
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=_patched))
        # ?quality=low on purpose: GPU-less machines still exercise the full
        # build path (low skips PBR/shadows but builds every mesh), and the
        # boot benchmark cannot demote-and-reload mid-test on a forced tier.
        page.goto(served.url('house?quality=low'))
        page.wait_for_timeout(1800)   # boot, benchmark warmup, first paint
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfHouseEnter === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        # L6 (batching spec): the house is stamped, not guessed. A tap on
        # the house walks in; a tap on the sky stays a view.
        check(page.evaluate("typeof window.chfHouseMode === 'function'"),
              'chfHouseMode reports the room')
        cbox = page.evaluate(
            "(() => { const r = document.querySelector('#room canvas')"
            ".getBoundingClientRect();"
            " return {x: r.x, y: r.y, w: r.width, h: r.height}; })()")
        page.mouse.click(cbox['x'] + cbox['w'] * 0.5,
                         cbox['y'] + cbox['h'] * 0.55)
        page.wait_for_timeout(1100)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'a tap on the house walks into the kitchen')
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)
        page.mouse.click(cbox['x'] + 24, cbox['y'] + 24)
        page.wait_for_timeout(1100)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'a tap on the sky stays a view')

        if shots:
            page.screenshot(path=os.path.join(shots, 'house_exterior.png'))

        page.evaluate("window.chfHouseEnter()")
        page.wait_for_timeout(1100)   # 850ms tween + settle
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_kitchen.png'))

        # the lean-in still wears the board's card after the transplant
        page.evaluate("window.chfKitchenFocus('calendar')")
        page.wait_for_selector('#overlay-calendar .agenda-event', timeout=8000)
        check(page.is_visible('#focus-overlay'),
              "the lean-in still wears the board's card")
        check('Soccer practice' in page.inner_text('#overlay-calendar'),
              "the Family Day card names the seeded event")
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_leanin.png'))

        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)
        check(not page.is_visible('#focus-overlay'),
              "walking out drops the lean-in card")

        # H2: the garage is a room too
        check(page.evaluate("typeof window.chfHouseEnterGarage === 'function'"),
              "the garage hand path exists")
        page.evaluate("window.chfHouseEnterGarage()")
        page.wait_for_timeout(1100)
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_garage.png'))
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)

        # H3: the mudroom owns the door — the hero card follows it there
        page.evaluate("window.chfHouseEnterRoom('mudroom')")
        page.wait_for_timeout(1100)
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_mudroom.png'))
        page.evaluate("window.chfKitchenFocus('door')")
        page.wait_for_selector('#overlay-door >> text=Soccer practice',
                               timeout=8000)
        check(page.is_visible('#focus-overlay'),
              "the door's hero card mounts in the mudroom")
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)

        # H3: the living room owns the radio — the music widget follows
        page.evaluate("window.chfHouseEnterRoom('living')")
        page.wait_for_timeout(1100)
        if shots:
            page.screenshot(path=os.path.join(shots, 'house_living.png'))
        page.evaluate("window.chfKitchenFocus('radio')")
        page.wait_for_selector('#overlay-music', state='visible', timeout=8000)
        check(page.is_visible('#overlay-music'),
              "the radio still wears the music widget in its new room")
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))

        # L1 (batching spec): no material serves two masters. A material
        # used by any zone mesh is used by that zone alone; scenery
        # sharing is free. And the cache must actually be ON: a scene
        # where every mesh still owns a private material has not batched.
        inv = page.evaluate(INVARIANT_JS)
        check(not inv.get('err'), 'sharing probe captured the scene')
        check(inv['crossing'] == 0,
              'no material crosses a zone boundary: %r' % inv)
        # B3 fix round 1 (batching spec): INVARIANT_JS excludes any mesh
        # stamped userData.merged (house.js's mergeStatic sets it on every
        # merged mesh it builds) from `meshes`/`materials`/`geometries`,
        # so those three count only the never-merged survivors: zone
        # meshes (L4), NO_MERGE-fenced statics, transparent-material
        # meshes, meshes whose material was never marked shared, and
        # buckets that never reached mergeStatic's 4-item floor. That
        # population is smaller AND less shared than either the pre-merge
        # whole scene (Task 3/4: meshes=1006) or the post-merge whole
        # scene this task's first round counted (merged output included:
        # meshes=510, materials=409, geometries=442) — merge-eligibility
        # already REQUIRES a shared material AND 4+ same-bucket
        # instances, so survivors are drawn from exactly the categories
        # least likely to share (one-offs by design, or simply under the
        # floor). Fix round 2 (final review): `crossing` no longer shares
        # that exclusion — merged meshes ARE classified into the
        # per-material zone-usage map, so a merge that somehow bucketed
        # two zones' fabric together still trips this gate; only the
        # three survivor counts stay scoped to the never-merged.
        #
        # That means the ORIGINAL pre-merge thresholds (materials <=
        # meshes*0.5, geometries <= meshes*0.8), calibrated against the
        # whole 1006-mesh scene, do NOT hold over this narrower survivor
        # population — checked here, not assumed: three-run-stable at
        # quality=low, meshes=462, materials=380 (ratio 0.822),
        # geometries=394 (ratio 0.853), both above 0.5/0.8. 0.87 / 0.90
        # clear that measured pair with the same ~0.05 absolute margin
        # the previous round used, while still catching a fully dead
        # cache: a dead material cache also starves mergeStatic's own
        # same-material buckets (nothing merges), reverting straight to
        # the raw pre-cache population — meshes=materials=geometries=
        # 1006, ratio 1.0, comfortably caught by either ceiling.
        check(inv['materials'] <= inv['meshes'] * 0.87,
              'the material cache is live: %r' % inv)
        # Geometries are NOT preserved by merging the way materials are —
        # correcting this task's first-round comment, which claimed
        # merging left the numerator untouched. A merged mesh keeps
        # wearing its bucket's ORIGINAL material object, so that uuid
        # stays in the distinct-material set as long as any draw
        # (survivor or merged) still wears it — materials really is a
        # preserved set at whole-scene scope. But mergeGeoms always
        # builds one brand-new BufferGeometry per bucket, so every
        # original per-instance geometry a bucket consumed is orphaned
        # off the scene graph the moment its owner mesh is removed:
        # whole-scene geometries measured 741 pre-merge -> 442 post-merge
        # at this same quality=low scenario (Task 3/4's own three-run-
        # stable pre-merge number). The numerator moved; it was never
        # untouched. 0.90 is 0.047 above the measured, three-run-stable
        # 0.853 survivor ratio.
        check(inv['geometries'] <= inv['meshes'] * 0.90,
              'the geometry cache is live: %r' % inv)


MEM_JS = ("() => ({t: window.__hpR.info.memory.textures, "
          "g: window.__hpR.info.memory.geometries})")

# Fix round 1: shrinks any long-lived setInterval (house.js's poll() is
# wired to POLL_MS=60000) down to a fraction of a second, browser-side
# only -- house.js itself is untouched. Without this, driving a SECOND
# real poll -> applyState cycle through the actual network path (rather
# than faking the client-side call) would cost a real 60-second wait per
# scenario. kitchen_overlay.js's 1000ms hero countdown ticker is under
# the >2000 guard on purpose and keeps its own real cadence.
#
# ALSO wraps window.fetch to skip a tick while a previous
# /api/house/state (or /api/kitchen/state) call is still in flight, so
# this shrunk interval cannot itself pile up overlapping polls under
# load. This narrows, but does not by itself close, a request-
# concurrency window investigated in depth on the garage scenario (see
# _settle_confirmed below, which carries the full forensic trail and is
# the mitigation actually confirmed to hold under `python tools/test.py`'s
# full parallel sweep) -- kept here because fewer overlapping requests is
# a good property for a polling test regardless.
FAST_POLL_INIT_JS = """
  (function () {
    var real = window.setInterval;
    var realFetch = window.fetch.bind(window);
    var pending = false;
    window.fetch = function (input, init) {
      var url = (typeof input === 'string') ? input :
                 ((input && input.url) || '');
      var isState = url.indexOf('/api/house/state') !== -1 ||
                    url.indexOf('/api/kitchen/state') !== -1;
      if (isState) pending = true;
      var p = realFetch(input, init);
      if (isState) {
        var clear = function () { pending = false; };
        p.then(clear, clear);
      }
      return p;
    };
    window.setInterval = function (fn, ms) {
      if (!(ms && ms > 2000)) return real(fn, ms);
      return real(function () { if (!pending) fn(); }, 250);
    };
  })();
"""

DAY_LOCK_JS = 'Date.prototype.getHours = function () { return 14; };'

MAGNET_JS = """() => {
  const S = window.__hpScene;
  if (!S) return null;
  let n = 0;
  S.traverse(o => {
    // The fridge magnet box is the only 0.22x0.22x0.03 BoxGeometry the
    // room builds (house.js cgeo key 'b|0.22|0.22|0.03') -- identifying
    // magnets by their geometry's own parameters, rather than reaching
    // for the (unexposed) `webgl.magnets` group handle, needs no new
    // debug hook in house.js itself.
    if (o.isMesh && o.geometry && o.geometry.parameters &&
        o.geometry.parameters.width === 0.22 &&
        o.geometry.parameters.height === 0.22 &&
        o.geometry.parameters.depth === 0.03) n += 1;
  });
  return { magnets: n, geometries: window.__hpR.info.memory.geometries,
           textures: window.__hpR.info.memory.textures };
}"""

GARAGE_PLAQUE_JS = """() => {
  const S = window.__hpScene;
  if (!S) return null;
  let plates = 0, validMaps = 0;
  // Fix round 2 (test-rigor): each matching plaque's OWN texture uuid,
  // collected in traversal order. carsG is fully cleared and rebuilt in
  // `cars` array order on every payload change (syncGarage), and that
  // array order is the server's own storage.get_all_cars() order, which
  // this scenario never mutates after _seed() -- so position i here
  // names the SAME car before and after the flip, with no need to guess
  // which index is Red Truck's. A texture's uuid changes ONLY when
  // mkTex mints a fresh CanvasTexture (its cache MISSED because that
  // car's own [name, battery_pct, fuel_pct, warn] payload changed); a
  // cache HIT hands back the exact same object, same uuid.
  const texUuids = [];
  S.traverse(o => {
    // The car plaque's PlaneGeometry(1.5, 0.75) (house.js cgeo key
    // 'pq|1.5|0.75') is the only geometry of that exact size -- car BODY
    // meshes carry the SAME userData.zone/room ('garage') the plaque
    // does (buildCar's `tag()` stamps every part), so a zone/room filter
    // alone would over-match; the geometry's own dimensions single out
    // plaques only.
    if (o.isMesh && o.geometry && o.geometry.parameters &&
        o.geometry.parameters.width === 1.5 &&
        o.geometry.parameters.height === 0.75) {
      plates += 1;
      const img = o.material && o.material.map && o.material.map.image;
      if (img && img.width === 256 && img.height === 128) validMaps += 1;
      texUuids.push(o.material && o.material.map && o.material.map.uuid);
    }
  });
  return { plates: plates, validMaps: validMaps, texUuids: texUuids,
           textures: window.__hpR.info.memory.textures,
           geometries: window.__hpR.info.memory.geometries };
}"""


def _settle(page, js, keys, max_wait_ms=15000, interval_ms=400):
    """Poll `js` until every one of `keys` agrees across two consecutive
    reads (Fix round 1 hardening).

    window.__hpR.info.memory.{geometries,textures} are three.js RENDERER
    UPLOAD counters, not scene-graph snapshots: a room/camera change can
    bring geometry the renderer had never drawn before into its own
    tracking over the next several frames, with nothing this task's fix
    touches running again in between. Measured directly: a fixed-sleep
    version of the garage scenario read geometries=322 immediately after
    chfHouseEnterGarage() and 334 five real seconds later with NO other
    state change in between, then held flat at 334 for 25 more seconds --
    a one-time settle, not a leak. That same fixed-sleep version passed
    standalone but FAILED under `python tools/test.py`'s full parallel
    sweep (322->334 landing on the wrong side of the before/after read),
    because a busy sweep stretches exactly the window this settle needs.
    Polling until the reading stops moving, rather than guessing a
    duration that happens to cover it on one machine under one load, is
    what makes the before/after comparison mean what it says either way.
    """
    last = page.evaluate(js)
    waited = 0
    while waited < max_wait_ms:
        page.wait_for_timeout(interval_ms)
        waited += interval_ms
        cur = page.evaluate(js)
        if all(cur[k] == last[k] for k in keys):
            return cur
        last = cur
    return last


def _wait_for(page, js, key, target, max_wait_ms=15000, interval_ms=400):
    """Poll `js` until `key` reaches `target` (Fix round 1 hardening).

    Used before _settle so the two never fight each other: _settle alone
    would happily report "settled" on the OLD value if two consecutive
    reads land before a poll-triggered change has arrived at all. This
    waits for the actual functional change first; _settle then absorbs
    any rendering catch-up that follows it.
    """
    waited = 0
    while waited < max_wait_ms:
        cur = page.evaluate(js)
        if cur[key] == target:
            return cur
        page.wait_for_timeout(interval_ms)
        waited += interval_ms
    return page.evaluate(js)


def _settle_confirmed(page, js, keys, rounds=3, gap_ms=1500, **settle_kw):
    """_settle, then re-settle `rounds - 1` more times, `gap_ms` apart,
    requiring the SAME reading every time (Fix round 1 hardening).

    One _settle pass only asks for two consecutive short-interval reads
    to agree, which a value still genuinely moving on a multi-second
    timescale (the room-entry upload-count settle _settle's own docstring
    measures) can satisfy by accident on a momentary plateau. Grew out of
    investigating the garage scenario's own flip, which turned out to be
    a DIFFERENT problem this helper cannot fix by construction: an
    earlier version of that scenario drove the flip via a live,
    concurrently-polled monkeypatch, and the wrong reading it sometimes
    produced was not a transient flicker but a genuine extra mint that
    then stayed stable forever -- no amount of re-settling reads a
    permanent wrong answer as anything but consistent. That case is fixed
    at its source (route interception instead of a shared mutable
    global, see that scenario's own docstring); this helper stays useful
    on its own terms for the timescale _settle documents, at the cost of
    a few extra seconds when a reading is still legitimately moving.
    """
    prev = _settle(page, js, keys, **settle_kw)
    for _ in range(rounds - 1):
        page.wait_for_timeout(gap_ms)
        cur = _settle(page, js, keys, **settle_kw)
        if all(cur[k] == prev[k] for k in keys):
            return cur
        prev = cur
    return prev


def scenario_leanin_focus_cycles_do_not_leak_textures():
    """Task 13: mkTex (house.js) minted a fresh CanvasTexture on every
    repaint and never disposed the one it replaced, so every lean-in and
    lean-out orphaned a texture on the GPU permanently — measured before
    the fix at +4 textures per calendar+pet focus cycle, monotonic,
    12 -> 43 over 8 cycles while geometries stayed flat (the geometry
    side was already fixed, task 9b/55f4b25).

    Two full focus cycles must settle to the SAME texture count. The
    first cycle still mints: every face's blank/real payload pairing is
    being created for the first time under focus. The second cycle must
    find both payloads already cached and dispose-swapped rather than
    minting a third and fourth copy — that steady-state equality is
    exactly what the pre-fix code fails, by +4.
    """
    served = live_app()
    if served is None:
        return
    _seed()
    with served.browser() as page:
        # Fix round 1 (minor): day-lock the clock like house_probe.py
        # --day does, so a weather/sky repaint crossing the 07:00/19:00
        # night-rig boundary mid-run cannot perturb the texture/geometry
        # counts this scenario reads and turn a permanent sweep gate into
        # an occasional flake.
        page.add_init_script(
            'Date.prototype.getHours = function () { return 14; };')
        from house_probe import THREE_WRAP
        with open('static/vendor/three.min.js', 'rb') as fh:
            _patched = fh.read() + THREE_WRAP
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=_patched))
        page.goto(served.url('house?quality=low'))
        page.wait_for_timeout(1800)   # boot, benchmark warmup, first paint
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfHouseEnter === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        # Fix round 1 hardening: house.js's OWN boot sequence calls
        # webgl.clearPaint() (texCache = {}, no disposal -- a KNOWN,
        # pre-existing, out-of-scope one-time drop, see task-13-report.md)
        # from `document.fonts.ready.then(...)`, then repaints every face
        # from scratch. That is a second, uncounted wave of texture
        # mints landing on top of whatever this scenario already read as
        # a baseline if fonts happen to settle late -- reproduced twice
        # under `python tools/test.py`'s full parallel sweep (never
        # standalone), textures/geometries jumping between this
        # scenario's two readings for a reason that has nothing to do
        # with this task's fix. Awaiting the SAME promise here schedules
        # after house.js's own .then() (registered first, at page load),
        # so by the time this call returns, that one-time reset has
        # already run -- this scenario's baseline is taken AFTER it,
        # never straddling it.
        page.evaluate("() => document.fonts.ready")

        page.evaluate("window.chfHouseEnter()")
        page.wait_for_timeout(1100)   # 850ms tween + settle

        def cycle():
            # Mirrors the controller's repro (leanin_tex_leak_probe.py,
            # scratchpad): calendar in/out, then pet in/out. Pet lives in
            # the living room (ZONE_ROOM), so this also crosses a room
            # change every cycle, exactly like the real lean-in path.
            #
            # Fix round 1 (minor): the chfKitchenFocus(null) calls below
            # are NO-OPS — window.chfKitchenFocus guards on `!ZONES[key]`
            # and ZONES has no null key, so the call returns immediately.
            # This scenario still exercises the blank<->real repaint
            # because calendar (kitchen) and pet (living) are CROSS-ROOM:
            # chfKitchenFocus('pet') calls enterRoom('living', ...), and
            # enterRoom itself clears `focused` and calls announceFocus(
            # null) whenever the room actually changes — that is what
            # restores the calendar face from its blank. If pet's
            # ZONE_ROOM entry is ever changed to 'kitchen' (same room as
            # calendar), this reliance breaks silently: no room change
            # means no enterRoom-driven clear, focus would jump straight
            # from 'calendar' to 'pet' without a restore in between, and
            # this test's cycle1==cycle2 assertion would still pass, but
            # trivially — flat because too little repainted to tell a
            # leaky mkTex from a fixed one, not because the fix held.
            page.evaluate("window.chfKitchenFocus('calendar')")
            page.wait_for_timeout(1400)
            page.evaluate("window.chfKitchenFocus(null)")
            page.wait_for_timeout(1000)
            page.evaluate("window.chfKitchenFocus('pet')")
            page.wait_for_timeout(1400)
            page.evaluate("window.chfKitchenFocus(null)")
            page.wait_for_timeout(1000)
            return page.evaluate(MEM_JS)

        c1 = cycle()
        c2 = cycle()
        check(c1['g'] == c2['g'],
              'geometries must stay flat across focus cycles: %r -> %r'
              % (c1, c2))
        check(c1['t'] == c2['t'],
              'mkTex leaks a texture per repaint: cycle1=%d cycle2=%d - '
              'every replaced CanvasTexture must be disposed on overwrite'
              % (c1['t'], c2['t']))

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_fridge_magnets_rebuild_shares_geometry():
    """Task 13 fix round 1 (IMPORTANT 1): the magnets half of the task-13
    fix (applyState's rebuild, house.js ~7557-7578 -- dispose materials on
    removal, share the box geometry through cgeo) shipped with ZERO
    runtime coverage. No fixture anywhere seeded fridge.new_moments above
    0, so wantMagnets was always 0 and the whole rebuild branch never ran
    in any prior test -- the repo's own standing rule ("every critical
    path needs a test that RUNS it") was unmet.

    This drives TWO different, non-zero magnet counts through the REAL
    poll -> applyState path in ONE page session (not a page reload, which
    would only ever exercise the empty-to-N first build, never the
    N-to-M REBUILD the fix actually touches): intercepting
    `/api/house/state` rewrites just the `fridge.new_moments` field on
    the genuine server response, and FAST_POLL_INIT_JS shrinks house.js's
    own 60-second poll interval so the second real poll lands in about a
    second instead of a minute.

    The rebuild (3 magnets -> 6 magnets) must free the 3 old magnets'
    meshes while the shared box geometry's count stays flat -- the
    discriminating case the brief called for: an un-cgeo'd mint-per-
    magnet implementation would show geometries move WITH the magnet
    count (+3 here); the shipped cgeo-routed implementation must not.
    """
    served = live_app()
    if served is None:
        return
    _seed()
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script(FAST_POLL_INIT_JS)
        from house_probe import THREE_WRAP
        with open('static/vendor/three.min.js', 'rb') as fh:
            _patched = fh.read() + THREE_WRAP
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=_patched))

        # A FLAG, not a call-count: FAST_POLL_INIT_JS's shrunk interval
        # fires every ~250ms with no natural stopping point, and by the
        # time this test gets around to reading m1 several ticks may
        # already have landed (page.goto()'s own load time is not part
        # of this test's wait budget, so it cannot be bounded against a
        # fixed tick count). Any number of polls before `go['flip']`
        # turns true must all still read 3 -- idempotent by construction
        # -- so there is nothing to race: m1 is safe to read whenever we
        # get to it, and flipping the flag only AFTER that read is what
        # guarantees the NEXT poll (whichever tick it lands on) is the
        # first one to answer 6.
        go = {'flip': False}
        hits = {'n': 0}

        def _state_route(route):
            resp = route.fetch()
            body = resp.json()
            body.setdefault('fridge', {})['new_moments'] = 6 if go['flip'] else 3
            hits['n'] += 1
            hdrs = dict(resp.headers)
            hdrs['cache-control'] = 'no-store'   # force every poll onto
            route.fulfill(response=resp, json=body, headers=hdrs)  # the network, never the disk cache

        page.route('**/api/house/state*', _state_route)

        page.goto(served.url('house?quality=low'))
        page.wait_for_timeout(1800)   # boot, benchmark warmup, first paint
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfHouseEnter === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        # Fix round 1 hardening: house.js's OWN boot sequence calls
        # webgl.clearPaint() (texCache = {}, no disposal -- a KNOWN,
        # pre-existing, out-of-scope one-time drop, see task-13-report.md)
        # from `document.fonts.ready.then(...)`, then repaints every face
        # from scratch. That is a second, uncounted wave of texture
        # mints landing on top of whatever this scenario already read as
        # a baseline if fonts happen to settle late -- reproduced twice
        # under `python tools/test.py`'s full parallel sweep (never
        # standalone), textures/geometries jumping between this
        # scenario's two readings for a reason that has nothing to do
        # with this task's fix. Awaiting the SAME promise here schedules
        # after house.js's own .then() (registered first, at page load),
        # so by the time this call returns, that one-time reset has
        # already run -- this scenario's baseline is taken AFTER it,
        # never straddling it.
        page.evaluate("() => document.fonts.ready")

        page.evaluate("window.chfHouseEnter()")
        page.wait_for_timeout(1100)   # 850ms tween + settle

        # _settle (not a fixed sleep): entering the kitchen can still be
        # bringing its own never-before-drawn geometry into the
        # renderer's own upload count for the next several frames, which
        # would otherwise show up as noise indistinguishable from a real
        # magnets-related change once compared against m2.
        m1 = _settle(page, MAGNET_JS, ('geometries',))
        check(hits['n'] >= 1, 'the state route was never hit: %r' % hits)
        check(m1['magnets'] == 3,
              'first poll (fridge.new_moments=3) must mint 3 magnets: %r'
              % m1)

        # only now may a poll answer 6 -- the shrunk interval brings that
        # SECOND, different payload through the same poll -> applyState
        # path within a few hundred ms. _wait_for the functional change
        # first (the rebuild actually landing), THEN _settle geometries
        # on top of it, so the two concerns (did it rebuild? did the
        # renderer finish uploading afterwards?) never get conflated.
        go['flip'] = True
        _wait_for(page, MAGNET_JS, 'magnets', 6)
        m2 = _settle(page, MAGNET_JS, ('geometries',))
        check(m2['magnets'] == 6,
              'second poll (fridge.new_moments=6) must rebuild to 6 '
              'magnets: %r' % m2)
        check(m2['geometries'] == m1['geometries'],
              'the magnet box geometry is cgeo-shared (one box for every '
              'magnet), so a COUNT change must not mint new geometries: '
              '%r -> %r' % (m1, m2))

        # the shrunk interval keeps firing until the context closes;
        # stop intercepting so no route callback can still be mid-fetch
        # against a disposed request context on the way out (Playwright's
        # own suggestion for exactly this shape of teardown race).
        page.unroute_all(behavior='ignoreErrors')

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_garage_rebuild_does_not_touch_plaque_textures():
    """Task 13 fix round 1 (IMPORTANT 2a/2b): the report's first draft
    framed the carPlates/mkTex interaction as a rare departed-then-
    returned edge. It is not: syncGarage's rebuild GUARD hashes all nine
    of every car's fields ([id, name, color, body, seats, present, warn,
    battery_pct, fuel_pct]), while carTex's own CACHE KEY is only four of
    them ([name, battery_pct, fuel_pct, warn]) -- so ANY car's telemetry
    tick rebuilds the WHOLE garage, and with 2+ cars present that is
    routine, not rare.

    Verified by source (not assumed): the vendored three.js (r150)
    Texture.prototype.dispose() is exactly
    `dispatchEvent({type:'dispose'})` -- it never touches `.image` -- so
    the old report's "blank plaque" phrasing was never possible; the real
    cost was a silent GPU re-upload of an already-correct canvas. Because
    that is a WebGL-internal resource-accounting artifact (it nets back
    to the SAME renderer.info.memory.textures count after a settled
    render, disposed-then-reuploaded, exactly like an unflipped car's
    texture would either way), there is no pre-fix/post-fix DELTA this
    scenario could catch the way the mkTex leak scenario catches
    +4/cycle -- this is a POST-FIX execution and sanity proof instead: it
    exercises the exact changed lines (carPlates no longer disposes
    `.material.map`) under a real multi-car rebuild, and would still
    catch a broken edit (wrong object, wrong count, a thrown exception)
    or a reintroduced leak.

    Flip delivered by ROUTE INTERCEPTION, not a live monkeypatch
    (forensics, fix round 1): an earlier version of this scenario
    flipped Red Truck's telemetry by reassigning cars_svc.car_levels on
    the running server (live_app() runs uvicorn in-process, on a thread,
    per tests/live_app.py). That function is read by whatever thread is
    handling a /api/house/state request at the time, and this test's own
    main thread reassigns it concurrently while the shrunk-interval poll
    keeps requests arriving -- a genuine, if rare, unsynchronized-shared-
    state race, not a house.js defect. Reproduced and diagnosed directly
    (console + response instrumentation, scratch-only, not committed)
    under 12 concurrent copies of this same file: the server twice
    emitted, ~0.2ms apart, one response WITH the flip and one WITHOUT it
    for the same transition; storage.get_all_cars() and
    cars_svc.fleet_status(), called directly from the test at the exact
    instants of both readings during a captured failure, were byte-
    identical for the untouched car both times, proving the DATA layer
    was never at fault. Waiting for the flip to "stabilize" could not
    fix this, because the wrong reading it produced was not transient --
    once the race minted an extra texture it stayed minted, permanently,
    same as a real leak would. The actual fix is to stop racing at all:
    like the magnets scenario above, the flip now rewrites the real
    server's own JSON at the network boundary (route.fetch() + mutate +
    fulfill), read and written only from this single Python object, the
    same idiom already proven stable across every run of that scenario.
    """
    served = live_app()
    if served is None:
        return
    # This test file's scenarios all share ONE temp data dir/DB for the
    # whole process (CHAUFFEUR_DATA_DIR is set once at import time), and
    # _seed() is not idempotent -- every earlier scenario in this run
    # already added its own 'Red Truck'/'Blue Minivan' pair. Truncate
    # first so THIS scenario's plaque-count assertions mean what they
    # say (exactly the two cars seeded here), regardless of run order.
    from services import storage
    storage.cars_table.truncate()
    _seed()   # H2: Red Truck + Blue Minivan, both present, no HA telemetry
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script(FAST_POLL_INIT_JS)
        from house_probe import THREE_WRAP
        with open('static/vendor/three.min.js', 'rb') as fh:
            _patched = fh.read() + THREE_WRAP
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=_patched))

        # Flip ONE car's telemetry -- Red Truck only -- at the network
        # boundary. go['flip'] is read and written only by this Python
        # object; no server-side global is ever mutated, so there is
        # nothing for a concurrently-handled request to race.
        go = {'flip': False}
        hits = {'n': 0}

        def _state_route(route):
            resp = route.fetch()
            body = resp.json()
            if go['flip']:
                for c in (body.get('garage') or {}).get('cars') or []:
                    if c.get('name') == 'Red Truck':
                        c['battery_pct'] = 22.0
                        c['warn'] = True
            hits['n'] += 1
            hdrs = dict(resp.headers)
            hdrs['cache-control'] = 'no-store'
            route.fulfill(response=resp, json=body, headers=hdrs)

        page.route('**/api/house/state*', _state_route)

        page.goto(served.url('house?quality=low'))
        page.wait_for_timeout(1800)
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfHouseEnter === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        # Fix round 1 hardening: house.js's own document.fonts.ready.
        # then(...) callback (a KNOWN, pre-existing, out-of-scope one-time
        # texCache reset, see task-13-report.md) is registered at page
        # load, before this call is ever reached -- awaiting the SAME
        # promise here schedules after it, so by the time this returns,
        # that one-time reset (if it fires at all on this run -- it is a
        # no-op before `state` holds anything, which it usually does not
        # yet at that point in boot) is behind this scenario, not
        # straddling its readings.
        page.evaluate("() => document.fonts.ready")

        page.evaluate("window.chfHouseEnterGarage()")
        page.wait_for_timeout(1100)

        # _settle_confirmed: entering a room can still be bringing its
        # own never-before-drawn geometry into the renderer's own upload
        # count for the next several frames (see _settle) -- kept
        # confirmed (not a single pass) as cheap extra headroom now that
        # the flip itself is race-free.
        g1 = _settle_confirmed(page, GARAGE_PLAQUE_JS, ('geometries', 'textures'))
        # Fix round 2 (test-rigor): mirrors the fridge magnets scenario's
        # own hits['n'] check above -- proof the route interception is
        # actually firing, not silently no-opping on a URL pattern miss.
        check(hits['n'] >= 1, 'the state route was never hit: %r' % hits)
        check(g1['plates'] == 2, 'both seeded cars wear a plaque: %r' % g1)
        check(g1['validMaps'] == 2,
              'both plaques start with a real 256x128 canvas map: %r' % g1)

        go['flip'] = True
        page.wait_for_timeout(2500)   # the shrunk interval re-polls
        g2 = _settle_confirmed(page, GARAGE_PLAQUE_JS, ('geometries', 'textures'))

        check(g2['plates'] == 2,
              "the OTHER car's plaque must survive the rebuild too: %r"
              % g2)
        check(g2['validMaps'] == 2,
              'no plaque goes blank/undefined after the rebuild -- '
              'confirms the corrected 2a characterization ("silent '
              're-upload", never a blank plaque): %r' % g2)
        check(g2['textures'] == g1['textures'],
              'texture ledger must stay flat across a multi-car rebuild '
              'triggered by ONE car changing: %r -> %r' % (g1, g2))

        # Fix round 2 (test-rigor): everything above is a NEGATIVE proof
        # (nothing broke) and would pass identically whether the rebuild
        # actually ran or the route interception silently no-opped and
        # nothing rebuilt at all -- a flat ledger and a steady plate/
        # validMaps count describe both outcomes the same way. This is
        # the missing POSITIVE proof: Red Truck's flipped fields
        # (battery_pct None -> 22.0, warn False -> True) are two of
        # carTex's own four-field cache key ([name, battery_pct,
        # fuel_pct, warn]), so mkTex MUST cache-miss and mint a brand
        # new CanvasTexture -- a new uuid -- for that one plaque, while
        # Blue Minivan's completely untouched payload MUST stay a cache
        # HIT (same object, same uuid). Compared by POSITION rather than
        # a hardcoded "index 0 is Red Truck" guess: g1 and g2 are the
        # same browser session with no car added/removed/reordered in
        # between (the flip mutates the HTTP response body only, never
        # the DB row storage.get_all_cars() reads), so position i in g1
        # and position i in g2 name the same car either way, and exactly
        # one position may legitimately move.
        check(len(g1['texUuids']) == 2 and len(g2['texUuids']) == 2,
              'expected exactly two plaque textures both times: %r -> %r'
              % (g1['texUuids'], g2['texUuids']))
        changed = sum(1 for a, b in zip(g1['texUuids'], g2['texUuids'])
                      if a != b)
        check(changed == 1,
              "exactly one plaque -- the flipped car's -- must mint a "
              "NEW texture identity (cache miss on its changed payload) "
              "while the untouched car keeps its cached one (cache hit, "
              "same uuid): %r -> %r" % (g1['texUuids'], g2['texUuids']))

        page.unroute_all(behavior='ignoreErrors')

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


if __name__ == '__main__':
    scenario_the_house_boots_enters_and_leans_in()
    scenario_leanin_focus_cycles_do_not_leak_textures()
    scenario_fridge_magnets_rebuild_shares_geometry()
    scenario_garage_rebuild_does_not_touch_plaque_textures()
    print("test_house_live OK")
