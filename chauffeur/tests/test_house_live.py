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
import io
import os
import sys
import tempfile

from PIL import Image

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
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color_code': '#38bdf8'})
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
        # Final-fix wave (promoted from this scenario's own 9b-deferred
        # minor): this runs at quality=low, which is exactly the tier the
        # DETAIL<2 tyre-cylinder fallback and the two !SHADOWS contact-
        # shadow rings (+ their raw MeshBasicMaterials) used to mint fresh,
        # uncached, every rebuild -- disposed by nothing when the old car
        # group is torn down above, so the renderer's own geometry ledger
        # only ever grew. Both are now cgeo-keyed (tyre like cyl()'s own
        # cache; rings like ysh()'s K5 discs) so every wheel/ring across
        # both cars resolves to the same handful of shared objects and a
        # rebuild mints nothing new. Impossible to assert before that fix
        # (it never held); RED-proven against stashed pre-fix house.js,
        # GREEN after (see final-fix-report.md).
        check(g2['geometries'] == g1['geometries'],
              'geometry ledger must stay flat across a multi-car rebuild '
              'triggered by ONE car changing, at quality=low: %r -> %r'
              % (g1, g2))

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


def scenario_shell_fabric_registry():
    """Expanded shell: authored verdicts, visible ghost lines, real entries.

    The roof slopes now run north/south. Kitchen sees the south roof and
    east gable between its camera and subject. Living sees the south roof
    and all three porch faces; mudroom and garage see the service roof's
    south slope. Exterior has no subject and keeps every piece solid.
    See the Task 8 report for the geometry and corridor derivation.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        # DAY_LOCK_JS (Task 3): the mudroom door's hero card renders a
        # live leave-in-N-minutes countdown off the real wall clock
        # (house.js's isNight()/countdown maths read `new Date()`
        # directly), which would otherwise drift the mudroom screenshot's
        # pixels test-run to test-run for reasons that have nothing to do
        # with ghost edges. Registered before goto() so it wins the race
        # against house.js's own module-scope closures, same idiom as the
        # other live scenarios in this file that already need it.
        page.add_init_script(DAY_LOCK_JS)
        # quality=high, wait_for_selector + a 2200ms settle: the same
        # boot idiom tools/house_probe.py uses ahead of its own reads,
        # not the has_room-and-skip dance the other scenarios in this
        # file use -- there is nothing tier-dependent to skip here: every
        # regFabric() call site sits outside any DETAIL/quality
        # conditional (read at implementation time), so the registry's
        # shape does not depend on which tier boots.
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        fab = page.evaluate("window.chfShellFabric()")
        names = sorted(f['name'] for f in fab)
        expected_names = {
            'east_wall', 'garage_door', 'garage_shell', 'living_roof',
            'mudroom_roof', 'north_wall', 'north_cladding', 'south_wall',
            'west_skirt', 'west_wall', 'yard', 'patio_slider',
            'roof_main_north', 'roof_main_south',
            'roof_main_end_west', 'roof_main_end_east',
            'porch_roof_west', 'porch_roof_east', 'porch_roof_front',
            'massing_east_front_south', 'massing_east_front_east',
            'massing_east_front_patio', 'massing_front_roof_north',
            'massing_front_roof_south', 'massing_front_roof_end_east',
            'massing_east_back_north', 'massing_east_back_east',
            'massing_east_back_patio', 'massing_back_roof_shed',
            'massing_back_roof_back', 'mudroom_front_cladding', 'west_cladding',
            'massing_back_roof_front', 'massing_service_north',
            'massing_service_west', 'massing_service_south',
            'massing_service_roof_north', 'massing_service_roof_south',
            'massing_service_roof_end_west', 'garage_gable_west',
            'garage_gable_east', 'garage_gable_front',
        }
        check(set(names) == expected_names,
              'expanded registry must contain exactly the authored pieces: %r' % names)
        by_name = {f['name']: f for f in fab}
        # Equal main/service eaves and a side roof that drains east, away
        # from the main wall: geometry regressions called out by the user.
        check(abs(by_name['roof_main_end_east']['box'][2] -
                  by_name['massing_service_roof_end_west']['box'][2]) < 0.02,
              'main and service gables must start at the same eave height')
        check(all(abs(a - b) < 0.001 for a, b in zip(
                  by_name['roof_main_south']['normal'],
                  by_name['massing_front_roof_south']['normal'])),
              'front-right roof must match the main roof pitch')
        shed_normal = by_name['massing_back_roof_shed']['normal']
        check(shed_normal[0] > 0 and shed_normal[1] > 0 and
              abs(shed_normal[2]) < 0.001,
              'side shed must drain east, away from the main house')
        yard = [f for f in fab if f['name'] == 'yard'][0]
        check(yard['mode'] == 'hide', 'yard is the one authored hide piece')
        check(all(f['visible'] for f in fab),
              'exterior boot: every piece visible (solid): %r' % fab)

        EXPECTED = {
            'exterior': [],
            'kitchen': ['east_wall', 'south_wall', 'roof_main_south',
                        'roof_main_end_east', 'porch_roof_east',
                        'massing_east_front_south', 'massing_east_front_east',
                        'massing_front_roof_north', 'massing_front_roof_south',
                        'massing_front_roof_end_east', 'massing_back_roof_shed',
                        'patio_slider', 'massing_back_roof_front',
                        'massing_east_back_east', 'massing_east_back_patio', 'yard'],
            'garage': ['garage_door', 'garage_shell', 'mudroom_roof',
                       'garage_gable_west', 'garage_gable_east', 'garage_gable_front',
                       'massing_service_roof_south', 'mudroom_front_cladding', 'yard'],
            'mudroom': ['mudroom_roof', 'west_skirt', 'west_wall', 'west_cladding',
                        'massing_service_roof_south', 'mudroom_front_cladding', 'yard'],
            'living': ['south_wall', 'roof_main_south', 'porch_roof_west',
                       'porch_roof_east', 'porch_roof_front',
                       'massing_front_roof_north', 'massing_front_roof_south', 'yard'],
        }
        for view, expected in EXPECTED.items():
            if view == 'exterior':
                page.evaluate("window.chfHouseExit && window.chfHouseExit()")
            elif view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % view)
            page.wait_for_timeout(1400)
            fab = page.evaluate("window.chfShellFabric()")
            offed = sorted(f['name'] for f in fab if f['verdict'] != 'solid')
            check(offed == sorted(expected),
                  '%s: solver must match the authored expanded-shell set, got %r'
                  % (view, offed))
            # Task 4 sanity (spec section 3's own words: "the point of the
            # table is that a human wrote the expectation down") -- eleven
            # pieces now exist, so a solver bug that ghosted everything
            # (e.g. an inverted camOut/subIn) would still slip past a
            # membership check alone; this catches it directly. Exterior's
            # own emptiness is the sealed-house half of the same guard
            # (spec section 4: "Exterior: every piece SOLID").
            check(len(offed) < len(fab),
                  '%s: solver must not ghost EVERY registered piece: %r'
                  % (view, offed))
            if view == 'exterior':
                check(offed == [], 'exterior must ghost NOTHING (the '
                      'sealed house, spec section 4): %r' % offed)

            if view == 'mudroom':
                # Task 3: west_wall is this view's one 'ghost' piece (the
                # LEGACY row above), so it carries both halves of the
                # proof -- the verdict string, and the pixels that verdict
                # is now supposed to cause. 'hide'/'ghost' both land in
                # `offed` above; only a verdict-string and a pixel check
                # tell them apart.
                west = [f for f in fab if f['name'] == 'west_wall'][0]
                check(west['verdict'] == 'ghost',
                      "west_wall must verdict 'ghost' in the mudroom, not "
                      "just non-solid: %r" % west)
                check(west.get('edgesVisible') is True,
                      'west_wall edges group must be visible while its '
                      'verdict is ghost: %r' % west)

                # Same mudroom camera and crop as v2.496.0 (466 pixels).
                # Keep the existing 350-pixel floor through the expansion.
                png = page.screenshot()
                im = Image.open(io.BytesIO(png)).convert('RGB')
                box = (1000, 160, 1240, 240)
                tgt, tol = (0x2d, 0x20, 0x18), 60
                crop = im.crop(box)
                cw, ch = crop.size
                pix = crop.load()
                n = sum(1 for cy in range(ch) for cx in range(cw)
                        if max(abs(pix[cx, cy][0] - tgt[0]),
                               abs(pix[cx, cy][1] - tgt[1]),
                               abs(pix[cx, cy][2] - tgt[2])) <= tol)
                check(n >= 350,
                      'west_wall ghost edges must paint >= 350 dark-line '
                      'pixels in the wall crop %r (tolerance %d of '
                      '#2d2018; this environment measures 466 here at '
                      'v2.495.0, not the 3736 the prior report claimed -- '
                      'see comment above; retightened 2026-09-12): '
                      'got %d' % (box, tol, n))

        for piece in ['south_wall', 'porch_roof_front']:
            page.evaluate("window.chfHouseExit()")
            page.wait_for_function("window.chfNavProbe({settled:true})")
            hit = page.evaluate("window.chfNavProbe({piece:%r})" % piece)
            check(hit is not None, '%s must be reachable from exterior' % piece)
            page.mouse.click(hit['cx'], hit['cy'])
            page.wait_for_function("window.chfNavProbe({settled:true})")
            check(page.evaluate("window.chfHouseMode()") == 'kitchen',
                  '%s must enter the kitchen' % piece)

        page.evaluate("window.chfHouseExit()")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        hit = page.evaluate("window.chfNavProbe({piece:'massing_east_front_east'})")
        check(hit is not None, 'unbuilt wing must have a reachable exterior surface')
        page.mouse.click(hit['cx'], hit['cy'])
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'unbuilt wing must stay inert')

        page.evaluate("window.chfHouseCam(21,6.5,7,6.9,2,6)")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        hit = page.evaluate("window.chfNavProbe({piece:'patio_slider'})")
        check(hit is not None, 'slider must be reachable from the terrace')
        page.mouse.click(hit['cx'], hit['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})")
        check(page.evaluate("window.chfHouseMode()") == 'living',
              'patio slider must enter living')

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_navigation_real_mouse():
    """Real clicks cover all four exterior entries, cross-room zones and
    fabric, a zone lean-in, two-step return, inert props, and sky exit.

    Project geometry through the current camera; verify candidate pixels
    with the production hit readers before clicking. Low quality keeps
    this behavioral scenario quick. Both high and low explicitly force
    the quality tier and disable automatic demotion.

    The service roof supplies the visible mudroom entry; the deeper porch
    now obscures the old west-skirt target. Garage supplies a sky pixel; the main room's
    roof surrounds its camera. The high-quality registry scenario retains
    separate geometry, ghost-edge pixel, and exterior-entry checks.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=low'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(1800)

        check(page.evaluate("typeof window.chfNavProbe === 'function'"),
              'chfNavProbe must exist for a real-mouse test to derive its '
              'own pixels, never a hard-coded screen point')

        def probe(spec_js):
            page.wait_for_function("window.chfNavProbe({settled:true})",
                                   timeout=20000)
            p = page.evaluate('window.chfNavProbe(%s)' % spec_js)
            check(p is not None, 'no reachable canvas pixel for %s' % spec_js)
            return p

        def enter(room):
            if room == 'exterior':
                page.evaluate("window.chfHouseExit && window.chfHouseExit()")
            elif room == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % room)
            page.wait_for_function(
                "window.chfNavProbe({settled:true})", timeout=20000)

        # The front service slope faces the built mudroom. Its back slope
        # covers the unbuilt extension and remains inert. The garage has
        # its own visible street-facing gable and door.
        enter('exterior')
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'must start at the sealed exterior')
        p = probe("{piece:'massing_service_roof_south'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'mudroom',
              'exterior tap on the service roof must enter the mudroom -- it '
              'fronts mudroom by the same street-adjacency rule as '
              'west_wall (spec section 5): %r' % p)

        # (2) east_wall now fronts LIVING (Task 7 corrects the file's own
        # prior 'kitchen' stamp -- east_wall closes the dollhouse's east
        # SIDE, against living's own floor run, not the kitchen's).
        enter('exterior')
        p = probe("{piece:'east_wall'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'living',
              'exterior tap on east_wall must enter living, not kitchen: '
              '%r' % p)

        enter('exterior')
        p = probe("{piece:'south_wall'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'exterior tap on south_wall must enter kitchen: %r' % p)

        # (3) garage_shell fronts garage (already true pre-Task-7 via
        # gtag's per-mesh stamps -- pinned here as a still-must-hold
        # regression guard now that it also carries an explicit
        # regFabric room field).
        enter('exterior')
        p = probe("{piece:'garage_gable_front'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'garage',
              'exterior tap on the garage gable must enter the garage: %r' % p)

        # spec section 5, rule 2: a zone belonging to ANOTHER room
        # navigates there -- replaces the old cross-room null-and-eject
        # this task deletes. radio is ZONE_ROOM-mapped to living but
        # sits in the shared open great room, visible from the kitchen's
        # own camera.
        enter('kitchen')
        p = probe("{zone:'radio'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'living',
              "tapping the radio's zone from the kitchen must walk into "
              'living, never eject to the exterior: %r' % p)

        # Rule 3 must also work without a zone behind the tapped wall.
        enter('kitchen')
        p = probe("{piece:'west_wall',zoneless:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'mudroom',
              'a zoneless west-wall tap must enter mudroom: %r' % p)

        # spec section 5, rule 1: a zone in the CURRENT room still leans
        # in (unchanged) -- a real click on the board, not the
        # programmatic chfKitchenFocus hand path, which stayed green
        # through the whole bug this task fixes and so proves nothing
        # about onTap.
        enter('kitchen')
        page.evaluate("window.__navEvents = []; "
                       "window.addEventListener('chf-kitchen-focus', "
                       "function (e) { window.__navEvents.push(e.detail); });")
        p = probe("{zone:'board'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'leaning into the board must stay in the kitchen: %r' % p)
        events = page.evaluate("window.__navEvents")
        check(any(e.get('zone') == 'board' for e in events),
              "a real tap on the board must fire the SAME chf-kitchen-"
              'focus event the card overlay listens for: %r' % events)

        # A blank tap while leaned in first returns to the kitchen view.
        p = probe("{empty:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        state = page.evaluate("window.chfNavProbe({settled:true})")
        check(state == {'mode': 'kitchen', 'focused': None},
              'blank lean-in tap must return to room level: %r' % state)
        check(not page.is_visible('#focus-overlay'),
              'returning to room level must dismiss the focused card')

        # spec section 5, rule 4: the current room's OWN zoneless props
        # are INERT -- the exact bug report's own reproduction (an island
        # mis-tap no longer ejects to the sealed exterior). enterRoom
        # no-ops when already in that room (mode === name), so the board
        # lean-in just above would otherwise still be "focused" here --
        # out to the exterior and back, guaranteeing unfocused, so this
        # exercises rule 4 and not the kitchen's own (unrelated,
        # unchanged) two-step walk-out.
        enter('exterior')
        enter('kitchen')
        check(not page.is_visible('#focus-overlay'),
              'must start this check unfocused, or a leftover lean-in '
              'card would make the inert assertion below meaningless')
        p = probe("{point:[-0.4,1.085,0.9]}")   # the island counter top
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'a mis-tap on the island must stay in the kitchen, not '
              'eject to the sealed exterior (the reported bug): %r' % p)
        check(not page.is_visible('#focus-overlay'),
              'the island mis-tap must not mount a lean-in card either -- '
              'truly inert, not an accidental lean')

        # spec section 5, rule 5: sky (or yard) still exits, unchanged --
        # living_roof carries no geometry (open-concept, never built) so
        # its own room has no sky pixel today; garage does (see docstring).
        enter('garage')
        p = probe("{sky:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'a sky tap must still exit to the exterior: %r' % p)

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_shell_without_room_is_inert():
    """Exercise an unbuilt shell using existing walls as fixture geometry.

    Clear room tags before registration, so the real stamping, merging,
    and pointer paths all run. A fixture zone behind the west wall proves
    that the visible roomless shell blocks an otherwise actionable zone.
    """
    served = live_app()
    if served is None:
        return
    with open('static/house.js', encoding='utf-8') as f:
        source = f.read()
    anchor = '    function regFabric(group, o) {'
    check(source.count(anchor) == 1, 'fixture needs the registration entry')
    source = source.replace(anchor, anchor + """
      if (o.name === 'south_wall' || o.name === 'west_wall') {
        o.room = null;
        group.traverse(function (m) { delete m.userData.room; });
      }
      if (o.name === 'west_wall') {
        var behind = new T.Mesh(new T.BoxGeometry(0.05, 12, 40),
                                new T.MeshBasicMaterial());
        behind.position.set(-7.5, 2.8, 4.4);
        behind.userData.zone = 'radio';
        scene.add(behind);
      }
    """)
    with served.browser() as page:
        page.route('**/house.js*', lambda route: route.fulfill(
            content_type='application/javascript', body=source))
        page.goto(served.url('house?quality=low'))
        page.wait_for_function(
            'window.chfNavProbe && window.chfNavProbe({settled:true})',
            timeout=30000)
        p = page.evaluate("window.chfNavProbe({piece:'south_wall'})")
        check(p is not None, 'roomless south wall must have a street pixel')
        page.mouse.click(p['cx'], p['cy'])
        check(page.evaluate('window.chfHouseMode()') == 'exterior',
              'roomless exterior shell must stay inert')
        page.evaluate('window.chfHouseEnter()')
        page.wait_for_function('window.chfNavProbe({settled:true})')
        p = page.evaluate("window.chfNavProbe({piece:'west_wall'})")
        check(p is not None, 'roomless west wall must have an interior pixel')
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function('window.chfNavProbe({settled:true})')
        check(page.evaluate('window.chfNavProbe({settled:true})') ==
              {'mode': 'kitchen', 'focused': None},
              'roomless shell must not open a room or zone behind it')


if __name__ == '__main__':
    scenario_the_house_boots_enters_and_leans_in()
    scenario_leanin_focus_cycles_do_not_leak_textures()
    scenario_fridge_magnets_rebuild_shares_geometry()
    scenario_garage_rebuild_does_not_touch_plaque_textures()
    scenario_shell_fabric_registry()
    scenario_navigation_real_mouse()
    scenario_shell_without_room_is_inert()
    print("test_house_live OK")
