"""The Home in real chromium against the served app.

Source pins cannot see whether the dollhouse actually boots, whether the
two-level camera enters and leaves, or whether the lean-in still wears the
board's card after the transplant. Drive the real page (source-reading
tests miss runtime breaks): boot at the exterior, walk in, lean in, walk
out — with zero console errors, the live-app harness's whole point.

Run from chauffeur/:  python tests/test_house_live.py
Set HOUSE_SHOTS=<dir> to also save exterior/kitchen/lean-in screenshots.
"""
import copy
import datetime
import io
import math as _math
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

        page.wait_for_selector('#house-glance .glance-next', state='visible')
        check('Soccer practice' in page.inner_text('#house-glance'),
              'exterior uses the next activity from the board hero')
        check(page.inner_text('#house-glance .ss-time').strip(),
              'exterior shows the screensaver clock')
        check(page.inner_text('#house-glance .ss-date').strip(),
              'exterior shows the screensaver date')
        check(page.locator('#house-glance').evaluate(
            "e => getComputedStyle(e).pointerEvents") == 'none',
              'glance overlay must let house taps through')

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
        check(page.evaluate("window.chfHouseMode()") == 'living',
              'a tap on the front of the house walks into the living room')
        check(not page.is_visible('#house-glance'),
              'clock and hero hide inside the house')
        page.evaluate("window.chfHouseExit()")
        page.wait_for_timeout(1100)
        check(page.is_visible('#house-glance .ss-time'),
              'clock returns on exterior without reloading')
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

CANVAS_TEXTURE_COUNT_WRAP = b"""
;(function () {
  var OriginalCanvasTexture = window.THREE.CanvasTexture;
  function CountedCanvasTexture() {
    window.__canvasTextureMints = (window.__canvasTextureMints || 0) + 1;
    return Reflect.construct(OriginalCanvasTexture,
      Array.prototype.slice.call(arguments), CountedCanvasTexture);
  }
  CountedCanvasTexture.prototype = OriginalCanvasTexture.prototype;
  window.THREE.CanvasTexture = CountedCanvasTexture;
})();
"""

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

    Two full focus cycles must settle to the SAME texture count, and the
    second cycle must mint no CanvasTextures. The first cycle creates each
    reusable blank variant. The second must find both blank and live faces
    in the cache. Renderer memory alone cannot catch repeated replacement
    churn because Three reports the same steady count after disposal.
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
            _patched = fh.read() + THREE_WRAP + CANVAS_TEXTURE_COUNT_WRAP
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
        mints1 = page.evaluate('window.__canvasTextureMints')
        c2 = cycle()
        mints2 = page.evaluate('window.__canvasTextureMints')
        check(c1['g'] == c2['g'],
              'geometries must stay flat across focus cycles: %r -> %r'
              % (c1, c2))
        check(c1['t'] == c2['t'],
              'mkTex leaks a texture per repaint: cycle1=%d cycle2=%d - '
              'every replaced CanvasTexture must be disposed on overwrite'
              % (c1['t'], c2['t']))
        check(mints1 == mints2,
              'focus revisits must reuse blank/live CanvasTextures: %d -> %d'
              % (mints1, mints2))

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
    """Two rectangles, two block roofs: the footprint pin and the
    authored mask table.

    MASSING ARC 1 (spec 2026-09-16-regular-house-orbit-design.md,
    sections 2 and 3). The registered set is the spec's kept+new lists
    and nothing else; the deleted massing may not survive under any
    name. The roof slopes still run north/south on both blocks.

    VIEW-VOLUME MASKING (spec 2026-09-16 masking, task 3): the solver's
    per-piece verdicts are gone. A piece's verdict in a room view is
    'masked' exactly when the build-time mask for that room cut some of
    it (maskedFraction > 0) and 'solid' otherwise; the exterior has no
    mask and keeps every piece solid. EXPECTED below names, per view,
    the pieces the mask MUST cut (more than a tenth of their area) and
    the pieces it MUST leave whole, each with its derivation from the
    mask (P: the pyramid from the room camera through the room box's
    silhouette; W: behind the box's front faces; masked = P and not W).
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
        # MASSING ARC 1 (spec section 2): the footprint pin. KEPT is the
        # spec's own "kept as-is" list, NEW its "new pieces" list, and
        # DELETED_PREFIXES every name the spec deletes -- so a piece that
        # quietly survives the massing cull fails here by name.
        # VIEW-VOLUME MASKING (task 4, spec section 5): the x 6.85 splits
        # the cutaway-ownership fix made (v2.499.41: roof_main_west /
        # roof_main_east, south_wall / south_wall_east) are folded back.
        # The mask cuts a piece only where it stands between a room
        # camera and that room's box, so one street wall and one roof
        # over the whole main block are exactly what the regular-house
        # spec named: roof_main's four pieces, south_wall in one run
        # x -7.15..14.65.
        # STUDY REFIT (2026-09-16): patio_slider is retired. Its glass
        # moved to the study's own opening (living_study_door, unchanged
        # by name) and the opening it used to fill at z 5.80 wears the
        # plain interior door the study gave up -- east_room_door.
        KEPT = {'north_wall', 'north_cladding', 'west_wall', 'west_skirt',
                'west_cladding', 'south_wall', 'garage_shell', 'garage_door',
                'east_room_door', 'living_back_room_door', 'living_study_door',
                'yard', 'roof_main_north', 'roof_main_south',
                'roof_main_end_west', 'roof_main_end_east'}
        NEW = {'east_wall', 'east_partition', 'north_wall_east',
               'garage_block_north', 'garage_block_west', 'mudroom_front',
               'garage_block_roof_north', 'garage_block_roof_south',
               'garage_block_roof_end_west', 'garage_block_roof_end_east',
               'back_door', 'future_room_partition'}
        DELETED_PREFIXES = ('massing_', 'mudroom_cross_roof', 'mudroom_roof',
                            'living_roof', 'mudroom_front_cladding',
                            'mudroom_east_finish')
        hand_names = KEPT | NEW
        hand = {n for n in names if not n.startswith('facade_')}
        check(KEPT <= hand, f'kept pieces missing: {sorted(KEPT - hand)}')
        check(NEW <= hand, f'new pieces missing: {sorted(NEW - hand)}')
        check(not [n for n in hand if n.startswith(DELETED_PREFIXES)],
              'deleted pieces still registered: '
              f'{[n for n in hand if n.startswith(DELETED_PREFIXES)]}')
        check(hand == hand_names,
              f'unexpected hand pieces: {sorted(hand - hand_names)}')
        generated = sorted(n for n in names if n.startswith('facade_'))
        check(set(names) == hand_names | set(generated),
              'nothing registers that is neither hand-authored nor generated: %r'
              % sorted(set(names) - hand_names - set(generated)))
        # Every generated piece traces back to a CANONICAL feature: the
        # name carries its own face, kind and slot, and shellGable's
        # _west/_east/_front suffixes ride on the end.
        import re as _re
        from services import house_facade as _hf
        canon = {(f['slot'], f['kind'])
                 for f in _hf.CANONICAL['ground'] + _hf.CANONICAL['roof']}
        slots = _hf.slot_table()
        check(generated, 'the elevation must register generated pieces')
        # face names can themselves carry an underscore now (garage_block),
        # so the alternation is built from the actual faces rather than a
        # bare [a-z]+ that would stop at the first one.
        faces_pat = '|'.join(sorted({s['face'] for s in slots}, key=len, reverse=True))
        for gen in generated:
            m = _re.match(r'^facade_(' + faces_pat + r')_([a-z_]+?)_(\d+)(_[a-z_]+)?$', gen)
            check(m is not None,
                  'generated name must read facade_<face>_<kind>_<slot>: ' + gen)
            face, kind, slot = m.group(1), m.group(2), int(m.group(3))
            check(slots[slot]['face'] == face,
                  '%s names slot %d, which is on the %s face' % (gen, slot, slots[slot]['face']))
            check((slot, kind) in canon,
                  '%s must come from a CANONICAL feature' % gen)
        # arc 4 prerequisite (spec §6): AO occluders come FROM the registry.
        # south_wall/east_wall's registered box is fabBox() of the WHOLE
        # group, which may run larger than the old hand row once porch/trim
        # decor is folded in (measured: south_wall's registered z-range
        # runs 13.95-19.8 against the hand row's tight 14.2-14.55, and
        # east_wall's x-min sits 0.06 outside the old exact-match
        # tolerance) -- so this asserts CONTAINMENT (the registered box
        # covers the hand row's old footprint within tol), not equality.
        occ = page.evaluate("window.chfAoOccluders()")
        def contains_box(b, tol=0.05):
            return any(o[0] <= b[0] + tol and o[1] >= b[1] - tol and
                       o[2] <= b[2] + tol and o[3] >= b[3] - tol and
                       o[4] <= b[4] + tol and o[5] >= b[5] - tol
                       for o in occ)
        # MASSING ARC 1: the south wall is the whole main front now
        # (x -7.15..14.65) and the piece at x 6.5..6.85 is east_partition,
        # the interior wall the old east_wall became; the main's own east
        # side stands out at x 14.65. All three still occlude.
        # one run again (task 4): the great room's front AND the study's
        # street face are the same registered box.
        check(contains_box([-6.5, 14.5, 0.0, 5.6, 14.2, 14.55]),
              'south_wall must occlude via its registered box')
        # 14.20, not 14.55: the fix wave stopped the partition at SWZ0,
        # the south wall's INNER face, so its end stops being coplanar
        # with the street siding (a coplanar plaster end draws a pale
        # stripe down the front elevation). It still occludes the whole
        # run; only the last 0.35 of it belongs to south_wall now.
        check(contains_box([6.5, 6.85, 0.0, 5.6, -5.725, 14.20]),
              'east_partition must occlude via its registered box')
        check(contains_box([14.30, 14.65, 0.0, 5.6, -5.725, 14.55]),
              'east_wall must occlude via its registered box')
        wallish = [f for f in fab if abs(f['n'][1]) < 0.5]
        check(len(occ) >= len(wallish),
              f'every wall-like piece contributes an occluder: {len(occ)} < {len(wallish)}')
        by_name = {f['name']: f for f in fab}
        # MASSING ARC 1 (spec section 3): two block roofs, both at the
        # same eave (GARAGE_BLOCK.eave IS EXT_TOP4 = 5.6), so their south
        # decks share one eave line -- what makes a roof feature run
        # coplanar across the old garage/mudroom boundary. shellGable's
        # deck box bottom is the eave edge of that deck, so comparing the
        # two boxes' y-min is comparing the two eave lines.
        check(abs(by_name['garage_block_roof_south']['box'][2] -
                  by_name['roof_main_south']['box'][2]) < 0.02,
              'both block roofs must start at the same eave height: %r vs %r'
              % (by_name['garage_block_roof_south']['box'][2],
                 by_name['roof_main_south']['box'][2]))
        # VIEW-VOLUME MASKING (task 4): the main roof is ONE roof again.
        # Each slope deck runs the whole block plus one overhang at each
        # end (x -7.15 - 0.32 .. 14.65 + 0.32; the deck box also holds
        # the eave trim, which is the same length), and nothing of it
        # ends or starts at the old 6.85 split.
        for side in ('north', 'south'):
            d = by_name['roof_main_' + side]['box']
            check(abs(d[0] - (-7.15 - 0.32)) < 0.05 and
                  abs(d[1] - (14.65 + 0.32)) < 0.05,
                  'the main roof deck runs the whole block plus its '
                  'overhangs (%s): %r' % (side, d))
        # roof_main reaches the main block's own east wall: the east
        # gable end sits one overhang past FULL_HOUSE.east (14.65) and
        # its rake board 0.08 further still.
        check(14.65 <= by_name['roof_main_end_east']['box'][1] <= 14.65 + 0.32 + 0.20,
              'roof_main must reach the east wall + one overhang: %r'
              % by_name['roof_main_end_east']['box'][1])
        # The two side decks of one block roof share a ridge and a pitch:
        # mirrored normals, same |y|.
        north = by_name['roof_main_north']['normal']
        south = by_name['roof_main_south']['normal']
        check(abs(north[1] - south[1]) < 0.001 and
              abs(north[2] + south[2]) < 0.001 and north[2] < 0 < south[2],
              'the main roof must be two mirrored slopes: %r %r' % (north, south))
        # MASSING ARC 1 (spec section 3): the canonical row is what the
        # scene reports building from, and window.HOUSE_ROOF_FORMS is
        # absent here, so both blocks must read gable / ridge x.
        check(page.evaluate('window.chfRoofForms()') ==
              {'main': {'form': 'gable', 'ridge': 'x'},
               'garage': {'form': 'gable', 'ridge': 'x'}},
              'the canonical block roofs are gables with an east-west '
              'ridge: %r' % page.evaluate('window.chfRoofForms()'))
        # VIEW-VOLUME MASKING (task 4, spec section 5): the verdict
        # machinery is retired -- no row carries an owners table, a
        # cutaway room, a two-sided flag, a hide/ghost mode, a plane or
        # a pad any more. The yard's hide is a mask fact now (fraction 1
        # in every room view, pinned per view below), not a mode.
        RETIRED = ('owners', 'cutawayRoom', 'twoSided', 'mode', 'plane', 'pad')
        leftovers = sorted('%s.%s' % (f['name'], k) for f in fab for k in RETIRED if k in f)
        check(not leftovers, 'retired verdict fields still reported: %r' % leftovers[:6])
        check(all(f['visible'] for f in fab),
              'exterior boot: every piece visible (solid): %r' % fab)

        # VIEW-VOLUME MASKING (task 3): per view, the pieces the mask must
        # cut (> 0.1 of their surface) and must leave whole (exactly 0).
        # Room boxes (chfRoomMask): kitchen x -10.39..6.5 z -5.8..5.8;
        # living x -6.5..6.5 z 5.1..14.22; study x 6.92..15.25 z
        # 7.12..14.45; garage x -17.96..-12.83 z 2.21..9.76; mudroom x
        # -12.6..-6.8 z 2.36..8.3; every one y 0..5.6 (floor to eave).
        EXPECTED = {
            # the sealed house: no mask at all
            'exterior': {'masked': [], 'whole': []},
            # RULING 3 (fix round 1): the yard (yardG whole) hides in every
            # room view, fraction 1, as the old mode:'hide' verdict did.
            # RULING 1: a facade roof feature drops whole below a fifth
            # kept -- the porch gable's decks in the living view.
            # kitchen -- HOME_POS (4.64, 13.8, 23.0), high in the street.
            # The box's near face (z 5.8) is INSIDE the open great room:
            # the pyramid's floor plane, through the camera and the box's
            # bottom-south edge, crosses the street wall's plane at y 6.9
            # -- above the wall (5.6). So the street wall, its windows,
            # its door and the porch are between the camera and the
            # LIVING room only, and stay. What is in the way is the roof:
            # the south deck comes off from the eave to where the ray to
            # the far-top edge crosses it (z ~7.9); the porch gable's two
            # decks stand in that same cone above the eave; and because
            # the kitchen box runs west to x -10.39 (the pantry nook
            # behind the great room's west wall, tagged kitchen), the
            # main roof's west gable end, the mudroom's east gable end,
            # the west wall's living-room run and its exterior skirt all
            # stand between the street camera and that nook.
            # TASK 4 (un-split): roof_main_south is the whole block's
            # deck now, so the kitchen's cut (0.47 of the old west half,
            # 14.32 of the deck's 22.44 run) reads ~0.30 of the one deck
            # -- still > 0.1; the north deck takes a hairline at its west
            # end (0.006 of the old half), so it is neither list.
            'kitchen': {'masked': ['roof_main_south', 'roof_main_end_west',
                                   'garage_block_roof_end_east', 'west_wall',
                                   'west_skirt', 'facade_main_gable_8_west',
                                   'facade_main_gable_8_east'],
                        'whole': ['south_wall', 'facade_main_window_7',
                                  'facade_main_window_9', 'facade_main_window_12',
                                  'facade_main_door_10', 'facade_main_porch_8',
                                  'east_partition', 'east_wall', 'north_wall',
                                  'north_wall_east', 'future_room_partition',
                                  'facade_main_window_15', 'facade_main_window_16',
                                  'garage_door', 'garage_block_west']},
            # living -- LIV_POS (0, 12.8, 26.5). The box reaches the
            # street wall's inner face (14.22 vs 14.20), so the wall
            # straddles the box's south face and is cut by P alone: the
            # room's silhouette projected onto it, nearly all of it. Its
            # windows 7/9/12 and door 10 are kits in that wall (centre
            # masked, whole). The south deck comes off from the eave to
            # z ~10; the porch gable's decks and front stand in the cone.
            # The porch itself (fix round 1: NOT a kit, clipped per mesh):
            # its slab, steps and rails lie under the pyramid's floor
            # plane (a ray to the room's floor passes 2.9 above the porch
            # at z 17) and stay; its eave beam and post tops stand in the
            # cone and are cut (0.13 of the row). The study's windows
            # are east of the pyramid's x span; its street face and its
            # roof are the EAST PARTS of south_wall and roof_main_south
            # (task 4, one wall and one deck again), which the pyramid
            # cuts only over the great room -- the study's own run of
            # both stands, pinned by remnant vertex in
            # scenario_a_room_cutaway_leaves_other_rooms_enclosed. The
            # kitchen's north wall is behind the box, inside W.
            'living': {'masked': ['south_wall', 'roof_main_south',
                                  'facade_main_window_7', 'facade_main_window_9',
                                  'facade_main_window_12', 'facade_main_door_10',
                                  'facade_main_gable_8_west', 'facade_main_gable_8_east',
                                  'facade_main_gable_8_front', 'facade_main_porch_8'],
                       'whole': ['facade_main_window_15', 'facade_main_window_16',
                                 'east_partition', 'east_wall', 'north_wall',
                                 'north_wall_east', 'future_room_partition',
                                 'roof_main_north',
                                 'garage_door', 'mudroom_front']},
            # garage -- GARAGE_POS (-18.0, 10.5, 21.3), 0.04 west of the
            # box's west face: south, top and (a sliver of) west faces
            # are front. The garage door fills the south face: kit,
            # centre masked, whole. The bay gable's front and decks and
            # the block roof's south deck are cut where the cone passes
            # to the box's top face. The north wall of the block, the
            # mudroom's own front and the main block are outside P or
            # inside W.
            'garage': {'masked': ['garage_door', 'facade_garage_block_gable_0_front',
                                  'facade_garage_block_gable_0_west',
                                  'facade_garage_block_gable_0_east',
                                  'garage_block_roof_south'],
                       'whole': ['garage_block_north', 'garage_block_west',
                                 'mudroom_front', 'west_wall', 'south_wall',
                                 'north_wall', 'roof_main_south']},
            # mudroom -- MUD_POS (-3.4, 6.2, 11.2), in the great room
            # east of the box, just above the eave, south of it. The
            # great room's west wall (slab x -7.15..-6.8) touches the
            # box's east face and is cut where the box projects onto it;
            # its exterior skirt and cladding stand behind it in the
            # same cone; mudroom_front's inner layer (z 7.94..8.3)
            # straddles the south face and is cut where it stands in P.
            # The garage-block roof: a camera 0.6 above the eave sees the
            # top face edge-on, so the deck is grazed at its overhang and
            # no more -- the room is seen THROUGH the wall, not the roof.
            'mudroom': {'masked': ['west_wall', 'west_cladding', 'west_skirt',
                                   'mudroom_front'],
                        'whole': ['garage_door', 'garage_block_north',
                                  'garage_block_west', 'south_wall', 'north_wall',
                                  'roof_main_south', 'east_partition']},
            # study -- STUDY_POS (7.02, 4.75, 18.82), east of the old
            # split line and below the eave: the south face is the only
            # front face. The street face straddles it (the study floor
            # reaches z 14.45, the wall's inner face is 14.20) and is cut
            # by P alone -- TASK 4: that face is the east 7.8 of the one
            # 21.8-wide south_wall, so 0.97 of the old south_wall_east
            # reads ~0.35 of the whole wall (> 0.1; the great room's run
            # of it stands, pinned by remnant vertex in
            # scenario_a_room_cutaway_leaves_other_rooms_enclosed).
            # Windows 15/16 are kits in it, whole. east_partition is
            # beside the camera (x 6.44..6.85 < 6.92), not between it and
            # the room: the study keeps its own west wall as a backdrop.
            # The roof is above a camera that looks level into the room:
            # the top face is not front; the north deck stays whole and
            # the south deck is grazed at its overhang only (0.013 of the
            # old east half, ~0.005 of the one deck -- neither list). The
            # great room's windows are outside the pyramid's x span.
            'study': {'masked': ['south_wall', 'facade_main_window_15',
                                 'facade_main_window_16'],
                      'whole': ['east_partition', 'facade_main_window_7',
                                'facade_main_window_12', 'north_wall', 'north_wall_east',
                                'roof_main_north', 'living_study_door',
                                'east_room_door', 'garage_door']},
        }
        for view in EXPECTED:
            if view != 'exterior':
                EXPECTED[view]['masked'].append('yard')
        for view, expected in EXPECTED.items():
            if view == 'exterior':
                page.evaluate("window.chfHouseExit && window.chfHouseExit()")
            elif view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % view)
            page.wait_for_timeout(1400)
            fab = page.evaluate("window.chfShellFabric()")
            by_view = {f['name']: f for f in fab}
            offed = sorted(f['name'] for f in fab if f['verdict'] != 'solid')
            # the verdict IS the fraction: 'masked' exactly where the mask
            # took something, 'solid' everywhere else
            if view == 'exterior':
                check(offed == [], 'exterior must mask NOTHING (the '
                      'sealed house, spec section 4): %r' % offed)
            else:
                cut = sorted(f['name'] for f in fab if f['maskedFraction'][view] > 0)
                check(offed == cut,
                      '%s: verdict masked <=> maskedFraction > 0, got %r vs %r'
                      % (view, offed, cut))
                for name in expected['masked']:
                    check(by_view[name]['maskedFraction'][view] > 0.1,
                          '%s: %s must be cut (> 0.1), got %r'
                          % (view, name, by_view[name]['maskedFraction'][view]))
                for name in expected['whole']:
                    check(by_view[name]['maskedFraction'][view] == 0,
                          '%s: %s must be whole, got %r'
                          % (view, name, by_view[name]['maskedFraction'][view]))
            # Task 4 sanity (spec section 3's own words: "the point of the
            # table is that a human wrote the expectation down") -- a mask
            # bug that cut everything (e.g. an inverted P plane) would
            # still slip past a membership check alone; this catches it
            # directly. Exterior's own emptiness is the sealed-house half
            # of the same guard (spec section 4: "Exterior: every piece
            # SOLID").
            check(len(offed) < len(fab),
                  '%s: the mask must not cut EVERY registered piece: %r'
                  % (view, offed))
            check(not any(f.get('edgesVisible') for f in fab),
                  '%s: cutaway wireframes must stay hidden: %r' % (view, fab))

            if view == 'mudroom':
                # west_wall receives the masked verdict (the great room's
                # wall opens onto the mudroom), but the touch-first
                # cutaway leaves its permanent edges hidden.
                west = [f for f in fab if f['name'] == 'west_wall'][0]
                check(west['verdict'] == 'masked',
                      "west_wall must verdict 'masked' in the mudroom, not "
                      "just non-solid: %r" % west)
                check(west.get('edgesVisible') is False,
                      'west_wall cutaway must not draw permanent wireframes')

        # The calendar's support stays visible just like the adjacent pantry.
        # Decor must not move the partition's visibility plane past its card.
        for zone in ['calendar', 'board']:
            page.evaluate("window.chfKitchenFocus(%r)" % zone)
            page.wait_for_function("window.chfNavProbe({settled:true})")
            wall = next(f for f in page.evaluate('chfShellFabric()')
                        if f['name'] == 'west_wall')
            check(wall['visible'], zone + ' must keep its plaster backing')

        page.evaluate("window.chfHouseEnterRoom('mudroom')")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        door_hit = page.evaluate("window.chfNavProbe({zone:'door'})")
        check(door_hit is not None, 'card-bearing door must be tappable')
        page.mouse.click(door_hit['cx'], door_hit['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})")
        check(page.evaluate("window.chfNavProbe({settled:true}).focused") == 'door',
              'tapping the visible garage connection must focus the hero')

        for piece in ['south_wall', 'facade_main_gable_8_front']:
            page.evaluate("window.chfHouseExit()")
            page.wait_for_function("window.chfNavProbe({settled:true})")
            hit = page.evaluate("window.chfNavProbe({piece:%r})" % piece)
            check(hit is not None, '%s must be reachable from exterior' % piece)
            page.mouse.click(hit['cx'], hit['cy'])
            page.wait_for_function("window.chfNavProbe({settled:true})")
            check(page.evaluate("window.chfHouseMode()") == 'living',
                  '%s on the front facade must enter living' % piece)

        # MASSING ARC 1: east_wall is the roomless piece now -- the main
        # block's own east elevation fronts the study and two UNBUILT
        # rooms, so no single room owns a tap on it and it stays inert,
        # exactly as the massing it replaced did.
        page.evaluate("window.chfHouseExit()")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        hit = page.evaluate("window.chfNavProbe({piece:'east_wall'})")
        check(hit is not None, 'the east elevation must have a reachable surface')
        page.mouse.click(hit['cx'], hit['cy'])
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'the roomless east elevation must stay inert')

        # The opening at z 5.80 is the east room's plain interior door
        # now (STUDY REFIT: the glass went to the study). It keeps the
        # slider's registration semantics exactly -- room 'kitchen', a
        # leaf on each face -- so a camera standing in the east room
        # still taps through to the kitchen.
        page.evaluate("window.chfHouseCam(12,2.6,5.6,6.9,2,5.8)")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        hit = page.evaluate("window.chfNavProbe({piece:'east_room_door'})")
        check(hit is not None,
              "the east room's door must be reachable from that room")
        page.mouse.click(hit['cx'], hit['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})")
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              "the east room's door must enter the kitchen")

        # High quality chamfers the radio face. Its fallback projection must
        # use the radio's world X face after the parent rotates 90 degrees;
        # projecting the Z edge collapses the music card to a few pixels.
        page.evaluate("window.chfHouseEnterRoom('living')")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        radio_hit = page.evaluate("window.chfNavProbe({zone:'radio'})")
        check(radio_hit is not None, 'high-tier radio must have a reachable face')
        page.mouse.click(radio_hit['cx'], radio_hit['cy'])
        page.wait_for_selector('#overlay-music', state='visible', timeout=20000)
        music_box = page.locator('#focus-overlay').bounding_box()
        check(music_box and music_box['width'] > 200,
              'high-tier music card must use the radio face, got %r'
              % music_box)

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_a_room_cutaway_leaves_other_rooms_enclosed():
    """A room's cutaway removes only what stands between its camera and
    the room.

    Cutaway-ownership fix (brief .superpowers/sdd/2026-09-16-cutaway-
    ownership/brief.md) first stated the user's rule: "Those rooms
    should remain and their walls and roofs should remain. You should
    only be seeing the thing you are looking at." It enforced it with an
    `owners` table and a solver that refused to ghost a non-owner's
    piece. VIEW-VOLUME MASKING (spec 2026-09-16 masking, task 3) enforces
    the same rule geometrically: per room, a build-time mask cuts a piece
    exactly where it lies between the room camera and the room's
    eave-high box, and nowhere else. So the general law is now: in every
    room view, every piece with maskedFraction 0 is whole and visible,
    every piece with maskedFraction > 0 is 'masked', and no kept vertex
    of the room's shell lies inside the mask (chfRoomShellLeak 0). The
    specific pieces the bug was reported on are then pinned by name from
    the living AND the kitchen, exactly as before. Task 4 retired the
    `owners` rows and folded the x 6.85 splits back (one south_wall, one
    roof_main), so the east rooms' street face and roof are now the EAST
    PARTS of pieces the great room's cameras also cut -- the enclosure
    law is pinned there by remnant vertex, not by a whole-piece 0.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        fab = page.evaluate("window.chfShellFabric()")
        check(all('maskedFraction' in f for f in fab),
              'every fabric row must report its maskedFraction per room')

        # The general law, per room view.
        for view in ('kitchen', 'living', 'study', 'garage', 'mudroom'):
            if view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % view)
            page.wait_for_timeout(1400)
            rows = page.evaluate("window.chfShellFabric()")
            wrong = sorted(f['name'] for f in rows
                           if (f['maskedFraction'][view] == 0) != (f['verdict'] == 'solid'))
            check(not wrong,
                  "%s: a piece leaves exactly when the mask cut it: %r" % (view, wrong))
            hidden_whole = sorted(f['name'] for f in rows
                                  if f['maskedFraction'][view] == 0 and not f['visible'])
            check(not hidden_whole,
                  "%s: an untouched piece never hides: %r" % (view, hidden_whole))
            check(page.evaluate("window.chfRoomShellShown()") == view,
                  '%s: its own shell is the visible one' % view)
            leak = page.evaluate("window.chfRoomShellLeak(%r, 2000)" % view)
            check(leak == 0, '%s: no kept vertex inside the mask (got %r)' % (view, leak))

        # The reported pieces, pinned by name. From the living room and
        # from the kitchen the study and the two future rooms keep their
        # own walls: every one is east of the pyramid's x span from both
        # street cameras (the great room's boxes end at x 6.5).
        EAST_ENCLOSURE = ['east_partition', 'east_wall',
                          'future_room_partition', 'north_wall_east']
        # TASK 4: their street face and their roof are the east parts of
        # ONE south_wall (x -7.15..14.65) and ONE roof_main_south, so a
        # whole-piece 0 cannot say they stand any more. Two pins say it
        # instead. (1) The living's cut of south_wall cannot exceed the
        # great room's share of the wall: the wall's three boxes are the
        # same height and thickness the whole run, so area goes with
        # width, and the pyramid's x span at the wall is the box's own
        # (-6.5..6.5, 13 of 21.8 = 0.596); the old 14-wide segment read
        # 0.871, which is 0.559 of the one wall. Pinned 0.5 < f < 0.6.
        # (2) The study's run of the wall (x > 6.85) and of the south
        # deck leave remnant vertices in the living shell -- the piece
        # stands there, cut only over the great room. The north deck
        # is not cut from the living at all (0), and from the kitchen
        # only at a hairline (< 0.01; its old west half read 0.006).
        for view in ('living', 'kitchen'):
            if view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % view)
            page.wait_for_timeout(1400)
            by = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}
            for name in EAST_ENCLOSURE:
                check(name in by, '%s must be registered' % name)
                check(by[name]['maskedFraction'][view] == 0 and by[name]['verdict'] == 'solid',
                      "%s: %s must stay whole, got %r / %r"
                      % (view, name, by[name]['maskedFraction'][view], by[name]['verdict']))
            check(by['roof_main_north']['maskedFraction'][view] < 0.01,
                  '%s: the north deck is not between a street camera and '
                  'the great room, got %r' % (view, by['roof_main_north']['maskedFraction'][view]))
            for piece in ('south_wall', 'roof_main_south'):
                verts = page.evaluate("window.chfRoomShellVerts(%r, %r, 4000)" % (view, piece))
                east = [p for p in verts if p[0] > 6.85]
                check(by[piece]['maskedFraction'][view] == 0 or east,
                      "%s: the study's run of %s (x > 6.85) must stand in the "
                      'shell, got fraction %r and %d remnant vertices east of '
                      'the old split' % (view, piece, by[piece]['maskedFraction'][view], len(east)))
            if view == 'living':
                check(0.5 < by['south_wall']['maskedFraction']['living'] < 0.6,
                      "living: south_wall is cut over the great room's run only "
                      '(0.559 derived), got %r' % by['south_wall']['maskedFraction']['living'])

        # The study's OWN cutaway: its street face -- the east 7.8 of the
        # one south_wall -- is cut along the room's silhouette and the
        # great room's run of the same wall stays (remnant vertices west
        # of x 6.5). Its roof is NOT cut: STUDY_POS (y 4.75) stands below
        # the eave looking level into the room, so the box's top face is
        # not a front face and no ray to the walled volume passes through
        # the roof -- the old solver hid the whole east half of the roof
        # by cutawayRoom, which is exactly the kind of whole-piece surgery
        # the mask retires. The one south deck is grazed at its overhang
        # at most (0.013 of the old east half, 8.12 of 22.44 = ~0.005).
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1400)
        by = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}
        for name in ('roof_main_north', 'roof_main_end_east', 'roof_main_end_west'):
            check(by[name]['maskedFraction']['study'] < 0.01,
                  "study: %s must stay (whole or a hairline), got %r"
                  % (name, by[name]['maskedFraction']['study']))
        check(by['roof_main_south']['maskedFraction']['study'] < 0.05,
              "study: the deck over the study is grazed at most, got %r"
              % by['roof_main_south']['maskedFraction']['study'])
        # 0.97 of the old 7.8-wide segment is 0.347 of the 21.8 wall;
        # the cut cannot exceed the study's share (7.8 / 21.8 = 0.358).
        check(by['south_wall']['verdict'] == 'masked' and
              0.3 < by['south_wall']['maskedFraction']['study'] < 0.36,
              "study: its street face (the east run of south_wall) must be "
              'cut, got %r' % by['south_wall']['maskedFraction']['study'])
        west = [p for p in page.evaluate("window.chfRoomShellVerts('study', 'south_wall', 4000)")
                if p[0] < 6.5]
        check(west, "study: the great room's run of south_wall must stand in the shell")


def scenario_study_sits_inside_the_main_block():
    """Regular house + orbit, task 1: the study lives inside the main
    rectangle (x 6.85..14.65, z 7.65..14.55), not in the old front wing
    that used to project past it. chfStudyBox() unions the study's
    furniture root, its house-scale architecture, and its zone proxies
    into one world Box3, exactly as scenario_shell_fabric_registry
    already reads chfShellFabric() for the shell -- a read-only debug
    hook, not a new gameplay surface.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1400)

        check(page.evaluate("typeof window.chfStudyBox === 'function'"),
              'chfStudyBox must exist so a test can pin the study to its '
              'own world bounding box without guessing at scene internals')
        box = page.evaluate("window.chfStudyBox()")
        check(box is not None, 'chfStudyBox must report a box once the '
              'study has been entered')
        check(box[5] <= 14.56,
              'the study must not reach past the main block\'s street '
              'face (z 14.55): max z %r' % (box[5],))
        check(box[4] >= 7.5,
              'the study must sit south of the future rooms (z 7.65 is '
              'its new north wall): min z %r' % (box[4],))


def scenario_the_study_faces_east_behind_glass_doors():
    """STUDY REFIT (2026-09-16, .superpowers/sdd/2026-09-16-study-refit).

    Two user requests in one pass.

    (A) DOORS. "The patio door is still there even though the patio
    turned into a regular inside room. That door might actually make a
    good door for the study as those commonly have double glass doors.
    And then use the study's regular interior door on that other room."
    So the glazing moved to the study's own opening at z 9.93 -- which
    keeps the name `living_study_door`, its registration, its room
    stamping and its parent-PIN gate -- and the opening at z 5.80 wears
    the plain interior door, registered `east_room_door` with the
    slider's old semantics (normal [1,0,0], room 'kitchen'; it was
    twoSided and ownerless under the verdict solver, which task 4 of the
    masking arc retired -- a kit now, whole or nothing by its box).
    `patio_slider` is retired by name.

    (B) THE STUDY FACES EAST. "The study layout doesn't make sense now
    that the patio is gone. The window needs to be on the east wall and
    the items on the east wall need to move to the north wall." The
    east wall is the only EXTERIOR wall the room has, and the house
    already carries a pane on it at z 11.10, so the window lines up
    with it; the shelf/library/board wall turns onto the north wall,
    which is the interior one it shares with the east room.

    Both halves are asserted from the scene itself -- the fabric
    registry for the doors, the study's own zone proxies for the window
    and the board -- never from a constant the code also reads.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)

        # ---- A: the doors swapped -------------------------------------
        fab = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}
        check('patio_slider' not in fab,
              'patio_slider must be retired by name, not left registered '
              'beside its replacement')
        door = fab.get('east_room_door')
        check(door is not None,
              "the east room's opening must register as east_room_door; "
              'registered: %r' % sorted(fab))
        check(door and door['room'] == 'kitchen',
              "east_room_door keeps the slider's room stamping so a tap "
              'on it still enters the kitchen, got %r'
              % (door and door['room'],))
        check(door and door['normal'] == [1, 0, 0],
              "east_room_door keeps the slider's normal (it stands in the "
              'east partition, facing x), got %r' % (door and door['normal'],))
        check(door and 'twoSided' not in door and 'owners' not in door,
              'the verdict fields are retired (masking task 4): an opening '
              'is a kit the mask keeps or drops whole, got %r'
              % (door and sorted(door),))

        glass = fab.get('living_study_door')
        check(glass is not None,
              'the study door keeps its name through the glazing swap')
        check(glass and glass['interiorGlow'] == 0,
              "the study's glass is INTERIOR glazing -- both sides of it "
              'are indoors -- so it never takes the exterior night glow, '
              'got %r' % (glass and glass['interiorGlow'],))
        span = glass['box'][5] - glass['box'][4] if glass else 0
        check(span > 2.6,
              'the double doors must fill the widened 2.65 opening at '
              'z 9.93, got a %.2f span' % span)

        # the entry survived the builder swap: the doors are still the
        # study's own tap, and test_house_life_live walks the PIN behind it.
        page.evaluate("window.chfHouseEnterRoom('living')")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        check(page.evaluate("window.chfNavProbe({action:'study'})") is not None,
              'the glass doors must still carry the study entry')

        # ---- B: the study faces east ----------------------------------
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1400)
        check(page.evaluate("typeof window.chfStudyZone === 'function'"),
              'chfStudyZone must exist so a test can pin which wall a '
              "study signal hangs on, read off the room's own zone proxy")
        win = page.evaluate("window.chfStudyZone('study_window')")
        check(win is not None, 'the study window zone must report a box')
        wx = (win[0] + win[1]) / 2 if win else 0
        wz = (win[4] + win[5]) / 2 if win else 0
        check(wx > 14.0,
              'the study window must hang on the EAST wall (x 14.52), '
              'got centre x %r' % wx)
        check(abs(wz - 11.10) < .35,
              "the study window must line up with the house's own east "
              'pane at z 11.10, got centre z %r' % wz)
        for key in ('study_board', 'study_binders'):
            zb = page.evaluate("window.chfStudyZone(%r)" % key)
            check(zb is not None, '%s must report a box' % key)
            cz = (zb[4] + zb[5]) / 2 if zb else 0
            check(7.6 < cz < 8.6,
                  '%s must have turned onto the NORTH wall (z 7.71), got '
                  'centre z %r' % (key, cz))
            cx = (zb[0] + zb[1]) / 2 if zb else 0
            # east of the study door's corner (the west partition is at
            # x 6.85): the turned set runs world x 8.57..13.76 of a
            # 6.92..14.18 wall, biased as far east as the wall map --
            # the one other thing hanging on the north wall -- allows.
            check(cx > 8.4,
                  '%s must sit on the north wall east of the study door '
                  'corner, got centre x %r' % (key, cx))

        # the room itself did not grow: a rigid turn moves nothing out.
        box = page.evaluate("window.chfStudyBox()")
        check(box is not None and box[1] <= 14.60 and box[0] >= 6.80,
              'the refit must stay between the partition and the east '
              'wall: x %r' % (box and [box[0], box[1]],))
        check(box is not None and box[5] <= 14.56 and box[4] >= 7.5,
              'the refit must stay inside the study: z %r'
              % (box and [box[4], box[5]],))


# The facade spec §2.2 pins the canonical facade to the elevation it
# replaces. Exterior boot, quality=high, INVARIANT_JS `meshes` (the
# never-merged survivors only), counted where this scenario runs in the
# file -- so the two cars, two backpacks and hero card the earlier
# scenarios seeded into the shared temp data dir are in the scene too,
# identically before and after. Measured on a bare server (nothing
# seeded) the same build counts 1732, against 1724 at HEAD 34dcf7c
# before buildElevation() existed.
#
# The canonical build lands at 1732, +8, and every one of the eight is
# the SAME mesh standing unmerged rather than a new or a lost one.
# mergeStatic merges within one registered piece and needs four items on
# one material; two buckets only ever reached that floor because a
# feature shared its wall's group, and spec §6 puts every generated
# feature in a registered piece of its own:
#   +4  south_wall's baseboard and the front door's three casing boards
#       (all 0xe4ddd1 sharp) were one 4-item bucket; the door is
#       facade_main_door_10 now, so 1 + 3 survivors stand instead.
#   +4  the old wing wall's two corner boards and its two window sill
#       boards (FARMHOUSE.trim sharp) were one 4-item bucket; the
#       windows are facade_wing_window_15/16 now, so 2 + 1 + 1 survive.
#
# MASSING ARC 1 re-records this RED-first: 1873 -> 1840, a net -33 in
# the same in-file position (standalone, with only this scenario's own
# seed, the same build counts 1699 -- the 141-mesh gap is the seeded
# cars/backpacks/hero card the earlier scenarios leave in the shared
# temp data dir, exactly as before).
#
# -33 NET, not -33 pieces: this counts UNMERGED SURVIVORS, and both
# sides of the change merge well. Gone: TWENTY-FOUR registered names,
# recounted name by name against the pre-arc registry pin at 2fb22a4
# (its own expected-name list, 41 hand pieces) minus the 16 this arc
# keeps minus east_wall, which is rebuilt in a new plane but keeps its
# name -- 41 - 17 = 24:
#   massing_east_front_south/east/patio                          3
#   massing_front_roof_north/south/end_east                      3
#   massing_east_back_north/east/patio                           3
#   massing_back_roof_shed/back/front                            3
#   massing_service_north/west/south                             3
#   massing_service_roof_north/south/end_west                    3
#   mudroom_cross_roof_north/south                               2
#   mudroom_roof, mudroom_front_cladding, mudroom_east_finish,
#   living_roof                                                  4
# plus the terrace slab and its furniture. Two of the 24 retire the
# NAME only -- mudroom_roof's street wall/door folds into mudroom_front
# and mudroom_east_finish folds into west_wall, both at identity -- so
# 22 pieces of geometry actually left the scene. But a shell piece is a
# handful of same-material boxes that mergeStatic already collapsed
# inside its own group, and the yard furniture was mostly folded into
# instanceYard's InstancedMeshes, so neither was ever costing survivors
# in proportion to its size. Added: east_wall's three windows, north_wall_east and
# its window, the back door, the garage block's three walls, the block
# roof's two end pieces, two future-room floors, future_room_partition
# and the back patio slab. The pin's job is to catch the NEXT
# unintended change; the direction (fewer) is the arc's own thesis.
#
# CUTAWAY OWNERSHIP (fix 2026-09-16) re-records it RED-first once more:
# 1840 -> 1849, +9, every one of the nine derived from the two splits
# rather than measured and accepted. Standalone (only this scenario's
# own seed) the same build counts 1708 against 1699 before the fix --
# the same +9, and the same 141-mesh seeded gap as before, which is
# what says the delta is the split and nothing else.
#   +6  roof_main becomes roof_main_west + roof_main_east. Each half
#       still builds 2 slope decks + 2 eave trims + 2 ridge caps (6),
#       so the pair costs 12 where one roof cost 6: +6 there. The GABLE
#       ENDS are a wash: the one roof built two (each a gable infill
#       plus two rake boards, 3 meshes), and the two halves build one
#       outer end each -- `ends [-1]` west, `ends [1]` east -- because
#       the split is an interior line and a gable there would be a wall
#       through the middle of the attic. 2 x 3 before, 2 x 3 after.
#   +3  south_wall becomes south_wall + south_wall_east: the same
#       three-box idiom (plaster half, siding half, baseboard) twice.
# Neither split adds a merge survivor beyond its own boxes: mergeStatic
# needs four items on one material inside ONE registered piece, and
# every one of these boxes is a different material or a lone member of
# its bucket on both sides of the change.
#
# STUDY REFIT (2026-09-16) re-records it RED-first again: 1849 -> 1865,
# +16. This pin counts every never-merged mesh in the SCENE, not only
# the elevation, so interior pieces do move it -- and this pass swaps
# two interior doors and rebuilds two of the study's own walls. The
# exterior elevation itself is untouched in COUNT: the study's own east
# pane changed SIZE (1.35 x 2.70 at y 2.80 -> 2.02 x 1.34 at y 1.95, to
# be the same window the room has behind it) and shellWindow builds the
# same eight meshes at any size.
# Standalone (only this scenario's own seed) the same build counts 1724
# against 1708 before the refit -- the same +16, and the same 141-mesh
# seeded gap, which is what says the delta is this pass and nothing else.
#   +13 living_study_door: the plain interiorDoor's 7 meshes (leaf, two
#       panels, head casing, two side casings, knob) become the glazed
#       pair's 20 -- 2 lites, 2 hanging stiles, 4 rails, the meeting
#       stile, 8 handle parts (a plate and a knob per leaf per face)
#       and 3 casing/lining boxes.
#   +17 east_room_door is new: two interiorDoor leaves, one per face of
#       a cut opening (7 each), plus the cut's own head and two jambs.
#       Both doors are house_features fixtures, added to the scene after
#       the build's mergeStatic pass, so every one of them survives.
#    -8 patio_slider is retired. Its twelve frame-coloured boxes were
#       already ONE merged mesh, which this pin does not count; the
#       survivors that leave with it are 2 unique panes (forceUnique
#       glass), 2 trim sills, 2 wood pulls and 2 stoop sills.
#    -3 east_partition crosses the merge threshold. Its C.wall boxes go
#       from three (the three wall segments) to five (plus a header over
#       each door opening), and four on one material inside one
#       registered piece is exactly what mergeStatic folds: three
#       survivors become none.
#    -3 house_study's north wall. The window's four-box opening (left,
#       right, under, over) left it; it is one solid run now, because it
#       is the interior wall the shelves and the board hang on.
#
# FIX ROUND 1 (v2.499.44) re-records it RED-first once more, 1865 -> 1868,
# +3, and the exterior elevation's own count still has not moved: every
# piece in both passes is interior.
#    +3 house_study's EAST wall. The first cut gave the room no east wall
#       of its own -- it let the block's `east_wall` slab stand in for
#       one and left the old `box('east', ...)` dead inside that slab,
#       which is why the room read cream on the north and charcoal on
#       the east. The room has its own again, built the way the north
#       wall is: the four boxes around the window (east-north, -south,
#       -low, -high) where one dead box used to be.
#    +1 VAULTED PARTITIONS (2026-09-16). Four interior wall sections
#       rise from the eave to the roof deck, and only ONE of them shows
#       up here: mergeStatic folds east_partition's section into that
#       group's existing five-box plaster bucket and the garage's into
#       the garage shell's five-box siding bucket (this count skips
#       merged output by design), and the study's two walls grew in
#       HEIGHT rather than in number. future_room_partition's group
#       holds two boxes now, under mergeStatic's four-item floor, so its
#       section stays its own draw. The exterior elevation itself has
#       not moved a millimetre: every piece in this arc is interior.
#
# VIEW-VOLUME MASKING (task 3, v2.499.53 / fix round 1 v2.499.54)
# re-records it RED-first, 1869 -> 2026, +157, and the exterior
# elevation's own count has still not moved: the full shell is merged
# exactly as before (its patterned buckets keep their one full composite;
# the per-room stand-ins are merged output, which this count skips), and
# the exterior draws the same 1432 meshes it did (probe --budget,
# before/after). The +157 are the five room shells' unmerged REMNANTS --
# the cut-off faces of fabric meshes and their caps, merged per mirrored
# ROW (so a composite keeps its row's shellOf ancestry) and therefore
# loose wherever a row's remnants or caps stay under mergeStatic's
# four-item floor: kitchen 57, living 20, study 14, garage 8, mudroom 58.
# Most are west_wall's own props (a picture frame, a shelf, a sconce part
# -- each on its own material, 25 in the kitchen shell and 34 in the
# mudroom's) cut where they stand between the street camera and the
# pantry nook, or between the mudroom camera and the mudroom. Hidden
# shells count all the same: this pin walks the scene, not the frustum.
# (Standalone -- only this scenario's own seed -- the same build counts
# 1885, the same 141-mesh seeded gap as every earlier entry.)
#
# VIEW-VOLUME MASKING task 4 (v2.499.55) re-records it RED-first,
# 2026 -> 2017, -9: the x 6.85 splits are folded back, so the exterior
# elevation's own count MOVES for the first time since the facade arc
# -- fewer pieces, the arc's own thesis. Derived first (-9), then
# measured: 2017 here, and standalone (only this scenario's own seed)
# 1876 against 1885 before -- the same -9 and the same 141-mesh seeded
# gap, which is what says the delta is the un-split and nothing else:
#   -3  south_wall_east's three boxes (plaster half, siding half,
#       baseboard) fold into south_wall's own three: the same three
#       materials, each still a lone member of its bucket (under
#       mergeStatic's four-item floor), so three survivors become none.
#   -6  roof_main_west + roof_main_east become roof_main. Each half
#       built 2 slope decks + 2 eave trims + 2 ridge caps (6), all on
#       different materials inside their own registered groups; one
#       roof builds 6 where the pair built 12. The gable ends are a
#       wash: one outer end per half before, two ends on the one roof
#       after (3 meshes each, either way).
#    0  the room shells' remnants and caps (merged per mirrored row,
#       loose under the four-item floor): the one wall's and the one
#       deck's remnants per room merge into the same number of
#       composites the two halves' did -- measured, not assumed.
#
# ROOF VALLEYS, masking task 5 (v2.499.56) re-records it RED-first,
# 2017 -> 2015, -2: the two facade gables lose what was buried under
# the block roofs (clipBuried, at build), so the pieces the exterior
# draws and the remnants the room shells cut both change. Derived from
# a per-row census (scratch/valley-shellrows-{before,after}.txt), then
# measured: 2015 here.
#   +6  exterior: each gable SIDE group was deck + eave trim + ridge cap,
#       three materials, three survivors. After the clip the porch
#       gable's deck and trim are each two convex pieces (above the
#       main deck; below it in front of the wall) and its ridge cap one
#       (its buried back gone) -- 5 face meshes on the same three
#       materials plus 5 section caps, which reach mergeStatic's floor
#       and fold into one composite: 5 survivors, +2 per side, +4. The
#       bay gable's deck splits the same way, its trim keeps only its
#       front stub and its cap its front: 4 survivors, +1 per side, +2.
#       The two front groups (infill + rakes) stand in front of the
#       wall and are untouched.
#   -8  kitchen shell: the porch gable's two side rows each left 6 loose
#       remnants (three faces, three caps); the buried back that stood
#       in the kitchen's cone is gone, so each row leaves two face
#       remnants and its caps merge (4 -> a composite): 2 + 1 merged.
#   +4  garage shell: the bay gable's two side rows each leave 4
#       remnants where they left 2 (the above-deck piece and the cap
#       are cut separately now).
#   -4  mudroom shell: the bay gable's east deck was grazed (0.09) at
#       its buried back only; nothing of it stands in the mudroom's
#       cone now (fraction 0), so its 4 remnants are gone.
CANONICAL_EXTERIOR_MESHES = 2015


# ---- VAULTED PARTITIONS (2026-09-16) ---------------------------------
# The roof's own arithmetic, re-derived HERE from the spec's dimensions
# (docs/superpowers/specs/2026-09-16-regular-house-orbit-design.md section
# 2: the main block x -7.15..14.65, z -6.10..14.55, eave 5.6; the garage
# block z -6.10..10.10, same eave; family pitch pi/8 on both) rather than
# read back out of the scene that also uses it. house.js's roofVault()
# and shellGable() each derive the same numbers a third and a second
# time, so a change to any one of the three fails a pin here.
#
#   ridge = eave + 0.18 + half * tan(pitch)        the deck's CENTRE plane
#   under = ridge - d * tan(pitch) - 0.09/cos(pitch)    its LOWER face,
#           measured down the vertical, d from the ridge line
_VAULT_PITCH = _math.pi / 8
_VAULT_GAP = 0.02          # house.js holds every wall top this far under
_MAIN_BLOCK = (-6.10, 14.55, 5.6)
_GARAGE_BLOCK = (-6.10, 10.10, 5.6)


def _deck_underside(block, at):
    north, south, eave = block
    half = (south - north) / 2.0
    ridge_y = eave + 0.18 + half * _math.tan(_VAULT_PITCH)
    return (ridge_y - abs(at - (north + south) / 2.0) * _math.tan(_VAULT_PITCH)
            - 0.09 / _math.cos(_VAULT_PITCH))


def scenario_interior_walls_rise_to_the_roof():
    """Vaulted partitions, and wall above every interior door.

    User report (2026-09-16, a screenshot of the living view): "Look at
    the left side vs the right side. There isn't any geometry on the
    right side to cover the top part. In a real house there would either
    be dropped ceilings with attic space above or vaulted ceilings where
    the walls go all the way up. Assume vaulted ceilings, so the walls
    should go all the way up. Also, even without that assumption, there
    are sections of the wall above two of the doors that are missing."

    Two pins, because the two halves of that report are two different
    facts. A registered piece's BOX says the group grew to the deck --
    that is the vault. Only a RAY says there is plaster at a particular
    point -- that is the header, and the wall between a door head and
    the roof above it. Both are read at the exterior, where the cutaway
    solver leaves every piece solid.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        fab = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}

        # ---- the vault: every partition tops out at the deck ----------
        ridge_y = _deck_underside(_MAIN_BLOCK, (-6.10 + 14.55) / 2.0)
        tops = [
            # east_partition runs ALONG the main block's slope axis and
            # crosses the ridge at z 4.225, so its own top IS the ridge.
            ('east_partition', ridge_y, 0.05),
            # future_room_partition runs ACROSS it at z 1.50; its top is
            # cut square at the lower of its two faces (z 1.325).
            ('future_room_partition', _deck_underside(_MAIN_BLOCK, 1.325), 0.05),
            # the garage/mudroom wall: the garage block's ridge (z 2.00)
            # crosses its north end, so that end is its tallest point.
            ('garage_shell', _deck_underside(_GARAGE_BLOCK, 2.00), 0.05),
        ]
        for name, want, tol in tops:
            f = fab.get(name)
            check(f is not None, 'missing fabric piece %r' % name)
            got = f['box'][3]
            check(abs(got - (want - _VAULT_GAP)) <= tol,
                  '%s must rise to the roof underside %.3f (less the %.2f '
                  'no-z-fight gap), got a box topping out at %.3f'
                  % (name, want, _VAULT_GAP, got))
        check(fab['east_partition']['box'][3] >= ridge_y - 0.2,
              'the east partition reaches the ridge, not merely higher '
              'than it was: %.3f' % fab['east_partition']['box'][3])

        # ---- the ray: wall where a wall belongs -----------------------
        # Every ray starts in the great room (or in the garage) and is
        # fired at the partition; EAST rays go +x, NORTH rays +z.
        EAST, NORTH = [1, 0, 0], [0, 0, 1]
        rays = [
            # the two door headers (shipped v2.499.44, pinned here so the
            # vault above them cannot be built by deleting them)
            ([0, 4.60, 9.93], EAST, 'east_partition',
             "wall above the study's glass doors (head 3.75)"),
            ([0, 3.60, 5.80], EAST, 'east_partition',
             "wall above the east room's plain door (head 3.05)"),
            # the vault itself: over each door, and over the ridge
            ([0, 7.00, 9.93], EAST, 'east_partition',
             'the vault over the study door, 1.4 above the old wall head'),
            ([0, 9.50, 4.225], EAST, 'east_partition',
             'the vault at the ridge line'),
            ([10.0, 6.50, -1.0], NORTH, 'future_room_partition',
             'the vault over the back-room partition'),
            # fired from the MUDROOM side, westward: the garage's own
            # half of this wall is behind `facade_garage_block_gable_0`,
            # a generated roof feature that reaches back into the bay.
            ([-10.0, 7.00, 6.0], [-1, 0, 0], 'garage_shell',
             'the vault over the garage/mudroom wall'),
        ]
        for origin, direction, want_name, why in rays:
            hit = page.evaluate('([o, d]) => window.chfRayFabric(o, d)',
                                [origin, direction])
            check(hit and hit['name'] == want_name,
                  'a ray from %r toward %r must hit %s -- %s -- got %r'
                  % (origin, direction, want_name, why, hit))

        # No new registered names: the arc GREW four groups, it did not
        # add a piece. (scenario_shell_fabric_registry owns the full
        # KEPT/NEW table; this is the one-line statement of the law.)
        names = sorted(fab)
        check(not [n for n in names if 'vault' in n],
              'the vault registers nothing of its own: %r' % names)

        # ---- the study's own north wall -------------------------------
        # INTERIOR (the east room is on the far side of it) and authored
        # 4.45 tall for a standalone page with its own shell. It is not
        # registered fabric -- house_study.js builds the room's
        # architecture itself -- so it is read from the study's own world
        # box, which chfStudyBox only reports once the room is visible.
        # After this arc that wall is the tallest thing in the room.
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1600)
        want = _deck_underside(_MAIN_BLOCK, 7.71) - _VAULT_GAP
        got = page.evaluate('window.chfStudyBox()')
        check(got and abs(got[3] - want) <= 0.06,
              "the study's north wall must rise to the deck at z 7.71 "
              '(%.3f), the study box tops out at %r' % (want, got and got[3]))


def scenario_canonical_facade_pins_the_hand_built_elevation():
    """The canonical facade builds the elevation it replaced.

    Facade spec §2.2: CANONICAL is today's street face, snapped onto the
    slot grid. Pixel positions move (no slot width reproduces the old
    hand-typed x values); the mesh count and the spec the scene was built
    from do not. §2 also makes the slot table single-source: house.js
    computes it in JS, services/house_facade.py in Python, and this pins
    the two against each other slot by slot so they can never drift.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        # INVARIANT_JS reads window.__hpScene, which only the probe's
        # THREE_WRAP captures -- same route idiom as the boot scenario.
        from house_probe import THREE_WRAP
        with open('static/vendor/three.min.js', 'rb') as fh:
            _patched = fh.read() + THREE_WRAP
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=_patched))
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        inv = page.evaluate(INVARIANT_JS)
        check(not inv.get('err'), 'mesh probe captured the scene: %r' % inv)
        check(inv['meshes'] == CANONICAL_EXTERIOR_MESHES,
              'canonical facade builds the same exterior mesh count: '
              '%d != %d' % (inv['meshes'], CANONICAL_EXTERIOR_MESHES))
        from services import house_facade as hf
        check(page.evaluate('window.chfFacade()') == hf.CANONICAL,
              'the scene is built from CANONICAL, not a hand literal')
        # CANONICAL_JS (house.js's no-injection fallback) also equals
        # CANONICAL, so the check above passes either way. These two say
        # which one the scene actually used: the server injected a spec,
        # and the scene was built from THAT object.
        check(page.evaluate("!!(window.HOUSE_FACADE && window.HOUSE_FACADE.spec)"),
              'the server injected the facade')
        check(page.evaluate("window.chfFacade() === window.HOUSE_FACADE.spec"),
              'the scene built from the injected spec, not the fallback')
        js_slots = page.evaluate('window.chfFacadeSlots()')
        py_slots = hf.slot_table()
        check(len(js_slots) == len(py_slots),
              'same slot count: %d vs %d' % (len(js_slots), len(py_slots)))
        for a, b in zip(js_slots, py_slots):
            for k in ('x0', 'x1', 'cx', 'z', 'eave'):
                check(abs(a[k] - b[k]) < 1e-6,
                      'slot %d %s: %r vs %r' % (b['i'], k, a[k], b[k]))
            for k in ('face', 'room', 'roof'):
                check(a[k] == b[k],
                      'slot %d %s: %r vs %r' % (b['i'], k, a[k], b[k]))
            # masking task 4: the slot table carries no owners any more
            # on either side (the mask decides what a room view removes)
            check('owners' not in a and 'owners' not in b,
                  'slot %d: owners retired, got %r / %r' % (b['i'], sorted(a), sorted(b)))
        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_worst_case_facade_builds_clean():
    """Spec §8: the heaviest spec the caps allow builds with no console
    errors, registers every feature, and the generated front door still
    navigates.

    The saved 'worst' record and the active-facade setting are process-wide
    state living in the module's shared CHAUFFEUR_DATA_DIR (every scenario
    in this file serves its own app against the same temp data dir), so a
    `finally` restores canonical and deletes the saved record no matter how
    the browser half of this scenario ends -- later scenarios (the
    canonical pin, in particular) must still see canonical.
    """
    from services import house_facade as hf
    served = live_app(lambda: (_seed(), hf.save_facade('worst', hf.worst_case(), activate=True)))
    if served is None:
        return
    try:
        with served.browser() as page:
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.add_init_script(DAY_LOCK_JS)
            page.goto(served.url('house?quality=high'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_timeout(2600)
            check(not errors, f'worst case builds clean: {errors[:3]}')
            spec = page.evaluate('window.chfFacade()')
            check(spec == hf.worst_case(), 'built from the worst case')
            fab = page.evaluate('window.chfShellFabric()')
            names = {f['name'] for f in fab}
            for g in spec['ground']:
                if g['kind'] in ('window', 'door', 'porch'):
                    face = hf.slot_table()[g['slot']]['face']
                    check(f"facade_{face}_{g['kind']}_{g['slot']}" in names, f'registered: {g}')
            for r in spec['roof']:
                face = hf.slot_table()[r['slot']]['face']
                prefix = f"facade_{face}_{r['kind']}_{r['slot']}"
                check(any(n == prefix or n.startswith(prefix + '_') for n in names), f'registered: {r}')
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            p = page.evaluate("window.chfNavProbe({entry:'front_door'})")
            check(p is not None, 'the generated front door is tappable')
            page.mouse.click(p['cx'], p['cy'])
            page.wait_for_function("window.chfNavProbe({settled:true}) && window.chfHouseMode() === 'living'", timeout=20000)
    finally:
        for r in hf.list_facades():
            if r.get('id') != hf.CANONICAL_ID and r.get('name') == 'worst':
                hf.delete_facade(r['id'])
        hf.set_active(hf.CANONICAL_ID)


def scenario_navigation_real_mouse():
    """Real clicks cover every exterior entry the street view can see,
    cross-room zones and fabric, a zone lean-in, two-step return, inert
    props, and sky exit.

    Project geometry through the current camera; verify candidate pixels
    with the production hit readers before clicking. Low quality keeps
    this behavioral scenario quick. Both high and low explicitly force
    the quality tier and disable automatic demotion.

    The garage block roof's south deck supplies the visible mudroom
    entry; the deeper porch now obscures the old west-skirt target.
    Garage supplies a sky pixel; the main room's roof surrounds its
    camera. The kitchen's own exterior entry is the back door on the
    north wall, which stop 0 cannot see, so this scenario orbits to stop
    5 to click it (massing arc 1, spec section 4). The high-quality
    registry scenario retains separate geometry, cutaway, and
    exterior-entry checks.
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

        # MASSING ARC 1 (spec sections 2 and 4): the Kitchen marker moved
        # off the patio slider (interior now) onto the new back door, and
        # the Mudroom marker follows its deck's rename
        # (mudroom_cross_roof_south -> garage_block_roof_south). The
        # back door is on the main's NORTH wall, which stop 0 cannot see,
        # so three markers draw at the resting view; the Kitchen one
        # arrives further down, at the orbit stop that can see it.
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#house-hints:not([hidden]) .house-hint').length === 3",
            timeout=10000)
        hints = page.locator('#house-hints .house-hint')
        exterior_targets = set(hints.evaluate_all(
            "els => els.map(e => e.dataset.target)"))
        check(exterior_targets == {
            'front_door', 'garage_block_roof_south', 'garage_front'},
              'persistent exterior markers must identify every room entrance '
              'the street view can see')
        check(page.locator('#house-hints').evaluate(
            "e => getComputedStyle(e).pointerEvents") == 'none',
              'discovery markers must never intercept mouse or touch input')
        living_hint = page.locator(
            '#house-hints .house-hint[data-target="front_door"]')
        check(living_hint.locator('svg').count() == 5,
              'living-room marker must preview music, critters, tasks, '
              'programs and the parent Study')

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

        enter('kitchen')
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#house-hints:not([hidden]) .house-hint').length === 5",
            timeout=10000)
        kitchen_hints = page.locator('#house-hints .house-hint')
        check(set(kitchen_hints.evaluate_all(
            "els => els.map(e => e.dataset.target)")) == {
                'fridge', 'counter', 'board', 'calendar', 'window'},
              'persistent kitchen markers must identify every actual zone')
        check(all(n == 1 for n in kitchen_hints.locator('svg').evaluate_all(
            "els => els.map(e => e.closest('.house-hint').querySelectorAll('svg').length)")),
              'each interior item marker must carry one feature icon')

        # The front service slope faces the built mudroom. Its back slope
        # covers the unbuilt extension and remains inert. The garage has
        # its own visible street-facing gable and door.
        enter('exterior')
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'must start at the sealed exterior')
        p = probe("{piece:'garage_block_roof_south'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'mudroom',
              'exterior tap on the block roof south deck must enter the '
              'mudroom -- slopeRooms gives that deck to the mudroom, the '
              'same street-adjacency rule as west_wall (spec section 5): '
              '%r' % p)
        # the mudroom's own street FACE is behind the porch and the main
        # block from here, exactly as its predecessor band was: the probe
        # says so, which is why the marker rides the deck above it. The
        # orbit's south-west stops (1 and 2) do see the face -- that is
        # scenario_orbit_eight_stops' mudroom_front probe.
        enter('exterior')
        check(page.evaluate("window.chfNavProbe({piece:'mudroom_front'})") is None,
              'the mudroom street face is not visible from the street view')

        enter('exterior')
        p = probe("{piece:'south_wall'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'living',
              'exterior tap on the front facade must enter living: %r' % p)

        enter('exterior')
        p = probe("{entry:'front_door'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'living',
              'exterior tap on the front door must enter living: %r' % p)

        # The kitchen's exterior entry is the back door on the main's NORTH
        # wall, which the street view cannot see (the marker set pinned
        # above is the whole proof: back_door is not in it). The orbit is
        # what reaches it. Stop 5 is the one used here: with a0 = 43.55
        # degrees measured from +x toward +z, stop 5 sits at 268.55
        # degrees -- within a degree and a half of straight off the north
        # wall -- so the door is as face-on as this house ever gets it,
        # and the garage block (all of it west of x -7.15) stands clear of
        # the sight line to a door at x -2.0. Stops 4 and 6 also see it;
        # 5 sees it squarest. scenario_orbit_eight_stops walks all eight.
        enter('exterior')
        page.evaluate('window.chfOrbitTo(5)')
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        page.wait_for_function(
            "() => [...document.querySelectorAll('#house-hints .house-hint')]"
            ".some(e => e.dataset.target === 'back_door')", timeout=10000)
        check(page.evaluate(
            "[...document.querySelectorAll('#house-hints .house-hint')]"
            ".some(e => e.dataset.target === 'back_door')"),
              'the Kitchen marker is drawn at the stop that can see the '
              'back door')
        p = probe("{entry:'back_door'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'a real click on the back door must enter the kitchen: %r' % p)
        enter('exterior')
        check(page.evaluate('window.chfOrbitStop()') == 5,
              'leaving a room returns to the stop it was entered from')
        page.evaluate('window.chfOrbitTo(0)')
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)

        # (3) garage_shell fronts garage (already true pre-Task-7 via
        # gtag's per-mesh stamps -- pinned here as a still-must-hold
        # regression guard now that it also carries an explicit
        # regFabric room field).
        enter('exterior')
        p = probe("{front:'garage_front'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'garage',
              'exterior tap on the garage gable must enter the garage: %r' % p)

        # Every depth has an explicit way back. This matters most in the
        # garage: its close car view contains almost no sky or yard to tap.
        back = page.locator('#house-back')
        check(back.is_visible(), 'room view must expose a back control')
        check('Exterior' in back.inner_text(),
              'room-level back control must name the exterior destination')
        p = probe("{zone:'garage'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfNavProbe({settled:true})") ==
              {'mode': 'garage', 'focused': 'garage'},
              'car tap must reach the garage detail view')
        check('Garage' in back.inner_text(),
              'focused back control must name the room destination')
        back.click()
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfNavProbe({settled:true})") ==
              {'mode': 'garage', 'focused': None},
              'first back press must restore the full garage view')
        back.click()
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'second back press must restore the exterior view')

        # The button supplements the old background gesture. Even when a
        # detail is focused, visible sky or lawn still exits directly.
        enter('garage')
        page.evaluate("window.chfKitchenFocus('garage')")
        page.wait_for_function(
            "window.chfNavProbe({settled:true}) && "
            "window.chfNavProbe({settled:true}).focused === 'garage'",
            timeout=20000)
        # Put the focused state at the full-room camera so the garage's
        # known sky pixel is visible; chfHouseCam changes only the eye.
        page.evaluate("window.chfHouseCam(-14.05,9.6,21.3,-15.45,1.75,6.05)")
        page.wait_for_timeout(100)
        p = probe("{sky:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'visible sky must exit directly even while detail is focused')

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

        # spec section 5, rule 5: sky OR yard exits. The garage camera sees
        # no sky since the envelope arc (its frame is interior, roofs and
        # lawn), so probe for any exit pixel -- the same test onTap runs.
        enter('garage')
        p = probe("{exit:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'a sky or yard tap must still exit to the exterior: %r' % p)

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))



def scenario_orbit_eight_stops():
    """Spec 2026-09-16 section 4: eight tweened stops around the pivot; every
    stop settles clean, draws at least one marker, and every entrance is
    reachable from some stop."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high&angle=3'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 3, '?angle=3 boots at stop 3')
        seen = {}
        for k in range(8):
            page.evaluate('window.chfOrbitTo(%d)' % k)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            # the markers are DEFERRED (scheduleHint, 1600 ms) so they cannot
            # flicker mid-tween: settle alone is 850 ms too early to count them.
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll("
                    "'#house-hints:not([hidden]) .house-hint').length >= 1",
                    timeout=6000)
            except Exception:
                pass
            check(page.evaluate('window.chfHouseMode()') == 'exterior',
                  'orbit never leaves the exterior')
            n = page.locator('#house-hints:not([hidden]) .house-hint').count()
            check(n >= 1, 'stop %d draws at least one marker (got %d)' % (k, n))
            for spec in ("{entry:'front_door'}", "{entry:'back_door'}",
                         "{piece:'mudroom_front'}", "{front:'garage'}"):
                if page.evaluate('window.chfNavProbe(%s)' % spec):
                    seen.setdefault(spec, k)
        check(len(seen) == 4,
              'every entrance reachable from some stop: %r' % (seen,))
        # a swipe steps once
        before = page.evaluate('window.chfOrbitStop()')
        box = page.locator('#room canvas').bounding_box()
        page.mouse.move(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.5)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.5, steps=8)
        page.mouse.up()
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'a left swipe advances one stop')
        check(page.evaluate('window.chfHouseMode()') == 'exterior',
              'a swipe must not double as a tap into a room')
        page.keyboard.press('ArrowLeft')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before, 'ArrowLeft steps back')
        # the chevrons are the hand path: exterior only, and they step
        page.wait_for_selector('.house-orbit[data-dir="1"]:not([hidden])', timeout=10000)
        page.click('.house-orbit[data-dir="1"]')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'the right chevron steps one stop')
        page.click('.house-orbit[data-dir="-1"]')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'the left chevron steps back')
        # The arrows belong to the HOUSE, not to whatever the person is
        # typing into on top of it. /house carries the Argyle textarea
        # (control_center.html #chat-input) and the music widget's search
        # box and volume slider, none of which set `house-card-open`, and
        # none of whose own handlers stop an arrow key from bubbling to
        # window -- so an unguarded branch turns "move the caret back one
        # character" into an 850 ms camera tween plus a solveShell.
        page.focus('#chat-input')
        page.keyboard.type('what time is soccer')
        page.keyboard.press('ArrowLeft')
        page.wait_for_timeout(1200)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'an arrow key inside a text field must not turn the house')
        check(page.evaluate("document.getElementById('chat-input').value")
              == 'what time is soccer',
              'the text field keeps what was typed into it')
        page.evaluate("document.getElementById('chat-input').value = '';"
                      "document.getElementById('chat-input').blur()")
        page.keyboard.press('ArrowRight')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'and with nothing focused the same key still steps the ring')
        page.keyboard.press('ArrowLeft')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'back to where the chevrons left it')
        # entering a room and leaving returns to the CURRENT stop
        page.evaluate("window.chfOrbitTo(5)")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        page.evaluate("window.chfHouseEnter()")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitTo(2)') is False,
              'a room ignores orbit input (spec section 4: rooms stay fixed '
              'dioramas)')
        check(page.locator('.house-orbit[data-dir="1"]').is_hidden(),
              'the chevrons belong to the exterior only')
        page.evaluate("window.chfHouseExit()")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 5,
              'exit returns to the stop you left from')
        check(not errors, 'zero console errors across the orbit: %r' % (errors[:3],))


def scenario_orbit_swipe_works_under_a_real_finger():
    """MASSING ARC 1 fix wave: the swipe on a TOUCH surface.

    `scenario_orbit_eight_stops` drives the swipe with `page.mouse`, which
    never exercises the gesture the wall panel actually gets. On a touch
    surface the browser owns the drag first: past its pan slop it claims
    the gesture, fires `pointercancel`, and `pointerup` never arrives on
    the canvas at all -- so a swipe handler built on pointerdown/pointerup
    alone is inert on the one surface that has no mouse. house.html's
    `#room canvas { touch-action: none }` is what stops the browser
    claiming it (the page cannot scroll anyway); house.js's
    `pointercancel` listener is the belt to that brace.

    Driven through CDP `Input.dispatchTouchEvent` rather than
    `page.touchscreen.tap` (which can only tap) in a context built with
    `has_touch=True`, so the events carry `pointerType: 'touch'` and the
    real touch-action machinery runs.
    """
    served = live_app(_seed)
    if served is None:
        return
    with served.browser(has_touch=True) as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=low&angle=2'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 2, '?angle=2 boots at stop 2')
        # the canvas must actually refuse the browser's own gestures, or the
        # drag below is a pan and the handler never hears its end.
        ta = page.evaluate(
            "getComputedStyle(document.querySelector('#room canvas')).touchAction")
        check(ta == 'none', "the canvas takes the gesture itself: touch-action %r" % ta)
        cdp = page.context.new_cdp_session(page)
        box = page.locator('#room canvas').bounding_box()
        y = box['y'] + box['height'] * 0.5
        x0 = box['x'] + box['width'] * 0.7
        x1 = box['x'] + box['width'] * 0.3
        check(abs(x1 - x0) >= 60, 'the drag clears the 60px threshold')

        def touch(kind, x=None):
            pts = [] if x is None else [{'x': x, 'y': y}]
            cdp.send('Input.dispatchTouchEvent',
                     {'type': kind, 'touchPoints': pts})

        before = page.evaluate('window.chfOrbitStop()')
        touch('touchStart', x0)
        for i in range(1, 9):                     # eight moves, past the slop
            touch('touchMove', x0 + (x1 - x0) * i / 8.0)
        touch('touchEnd')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'a finger dragged left advances one stop (was %d, now %d)'
              % (before, page.evaluate('window.chfOrbitStop()')))
        check(page.evaluate('window.chfHouseMode()') == 'exterior',
              'a swipe must not double as a tap into a room')
        # and back the other way, so direction is pinned too
        touch('touchStart', x1)
        for i in range(1, 9):
            touch('touchMove', x1 + (x0 - x1) * i / 8.0)
        touch('touchEnd')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'a finger dragged right steps back')
        # a cancelled gesture leaves nothing armed: the next plain tap must
        # still read as a tap, not pair with the abandoned start point.
        touch('touchStart', x0)
        touch('touchMove', x1)
        touch('touchCancel')
        page.wait_for_timeout(200)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'a cancelled drag turns nothing')
        check(not errors, 'zero console errors across the touch swipe: %r'
              % (errors[:3],))


def scenario_idle_return_snaps_the_orbit_home():
    """Spec 2026-09-16 sections 4/7: the panel's idle-return timer snaps the
    orbit back to stop 0, so the wall always rests on the street view.

    The timer is shortened through the setting the panel actually reads
    (`panel_idle_return_seconds`, served on /api/panel/profile as
    `idle_seconds`) rather than by stubbing the fetch: nav.html's
    `chfIdleRemaining` floors every period at three seconds, so the
    alternative -- a stale `chfPanelLastInput` written by an init script --
    would collapse the SCREENSAVER's period to the same three seconds and
    race it, and a screensaver that wins defers the return entirely
    (`_chfSsPendingHome`). The init script here carries the recorder instead.

    /house is not the home board, so nav.html's `goHome` navigates the panel
    away after the snap; the snap is caught on its way out through the
    house's own `chf-house-orbit` event (parked in sessionStorage, which
    survives the navigation) and the navigation itself is asserted after it.
    """
    from services import storage
    served = live_app(_seed)
    if served is None:
        return
    before = dict(storage.get_settings())
    storage.update_settings(dict(before, panel_idle_return_seconds=10))
    try:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.add_init_script(
                "window.addEventListener('chf-house-orbit', function (e) {"
                "  try { sessionStorage.setItem('chfOrbitSeen',"
                "    String(e.detail.stop)); } catch (err) {}"
                "});")
            page.goto(served.url('house?quality=low&panel=true&angle=5'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})",
                                   timeout=20000)
            check(page.evaluate('window.chfOrbitStop()') == 5,
                  'the panel starts the idle wait off the street view')
            check(page.evaluate("sessionStorage.getItem('chfOrbitSeen')") is None,
                  'nothing has moved the orbit yet')
            # No input of any kind from here: every listener nav.html arms
            # (pointerdown/keydown/wheel/touchstart) would restart the clock.
            page.wait_for_url('**/home*', timeout=40000)
            check(page.evaluate("sessionStorage.getItem('chfOrbitSeen')") == '0',
                  'the idle return snapped the orbit to stop 0 before the '
                  'panel went home')
    finally:
        storage.update_settings(before)


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


def scenario_clipper_cuts_convex_meshes():
    """Spec 2026-09-16 masking §3: the clipper is exact on a unit cube."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=low'))
        page.wait_for_selector('#room canvas', timeout=20000)
        r = page.evaluate("""() => {
          const C = window.HouseClip;
          if (!C) return {missing: true};
          const v = (x,y,z,u=0,w=0) => ({p:[x,y,z], uv:[u,w]});
          // unit cube 0..1, twelve triangles, slot 0, outward winding
          const q = (a,b,c,d) => [{a,b,c,slot:0},{a,b:c,c:d,slot:0}];
          const P = [v(0,0,0),v(1,0,0),v(1,1,0),v(0,1,0),v(0,0,1),v(1,0,1),v(1,1,1),v(0,1,1)];
          const tris = [].concat(
            q(P[0],P[3],P[2],P[1]), q(P[4],P[5],P[6],P[7]),   // z=0 (facing -z), z=1
            q(P[0],P[1],P[5],P[4]), q(P[3],P[7],P[6],P[2]),   // y=0, y=1
            q(P[0],P[4],P[7],P[3]), q(P[1],P[2],P[6],P[5]));  // x=0, x=1
          const area0 = C.triArea(tris, 0);
          const half = C.clipTris(tris, {n:[1,0,0], d:0.5}, 1);   // keep x >= 0.5
          const kept0 = C.triArea(half, 0), cap = C.triArea(half, 1);
          const out = C.subtractTris(tris, [{n:[1,0,0], d:0.5}, {n:[0,1,0], d:0.5}], 1);
          const outArea = C.triArea(out, 0);
          const m = C.maskPlanes([0, 10, 10], [-1, 1, 0, 2, -1, 1]);
          return {area0, kept0, cap, outArea, nP: m.P.length, nW: m.W.length,
                  inside: C.pointMasked([0, 5, 5], m), behind: C.pointMasked([0, 1, -3], m),
                  outsideCone: C.pointMasked([8, 5, 5], m)};
        }""")
        check(not r.get('missing'), 'window.HouseClip is loaded on /house')
        check(abs(r['area0'] - 6.0) < 1e-6, f"unit cube area 6, got {r['area0']}")
        check(abs(r['kept0'] - 3.0) < 1e-6, f"half cube keeps 3 of the original faces' area, got {r['kept0']}")
        check(abs(r['cap'] - 1.0) < 1e-6, f"one unit cap, got {r['cap']}")
        check(abs(r['outArea'] - 4.5) < 1e-6, f"cube minus its +x+y quarter keeps 4.5 original area, got {r['outArea']}")
        check(r['nP'] >= 4 and r['nW'] >= 1, f"mask planes built: P {r['nP']} W {r['nW']}")
        check(r['inside'] is True, 'a point between the camera and the box is masked')
        check(r['behind'] is False, 'a point beyond the box is kept')
        check(r['outsideCone'] is False, 'a point outside the silhouette is kept')


def scenario_every_fabric_mesh_is_convex_or_a_kit():
    """Task 2 (view-volume masking spec section 3): solids come from the
    builders. chfFabricConvexity() reads each row's `convexity`, scanned
    at registration time (regFabric(), refreshed by refabConvexity() for
    west_wall/mudroom_front/yard's own late folds) -- not a live
    traversal, and not a single bulk pass over FABRIC either, since
    house_features.js's door fixtures register even later than that
    (through syncWorld()'s first call). Registration always happens
    while a row's own meshes are still individual box()/extrude meshes,
    before any merge pass fuses them -- the same population Task 3's
    buildRoomShells() clips -- so a windowed wall built from ordinary
    box() meshes is expected to be fully convex, never a kit: merging
    those boxes into one composite happens later and neither this check
    nor Task 3's clip ever sees it.

    A non-kit row's unstamped meshes (`nonconvex`, a list of geometry
    type names) must all be a recognized non-box primitive -- a lathe,
    torus, cylinder, sphere, swept tube, or an InstancedMesh (exempt from
    the mask outright: kept whole, never even considered for a per-mesh
    keep/drop) -- never a plain BoxGeometry/tiledBoxGeo mesh (or a
    hand-built convex BufferGeometry, e.g. a chamfered box built directly
    instead of through box()) that simply missed its stamp, which is a
    bug, not an allowed shape. A kit row (a door, window, porch, garage
    door or the coach lamp) is kept or dropped WHOLE regardless of what
    is inside it, and the exact set of kit rows is pinned below -- this
    is the regression v2.499.50 actually shipped (nine ordinary windowed
    walls wrongly marked kit), so "at least one row is a kit" alone is
    not enough.
    """
    # ExtrudeGeometry and ShapeGeometry are deliberately ABSENT from this
    # set, not an oversight: every in-repo ExtrudeGeometry site inside a
    # non-kit row is already stamped directly by this task (shellGable's
    # decks/ends, vaultSection), so the only way either name reaches
    # `nonconvex` at all is a NEW extrude/shape site nobody has stamped
    # yet -- and unlike a lathe or a swept tube, an extrude or a shape is
    # not unconditionally non-convex (a Shape with a hole is not convex,
    # but a plain one is). Allowing them here would let a future missed
    # stamp on a genuinely convex (and clippable) mesh quietly pass as
    # "unknown non-box shape, fine" instead of failing loudly. Only
    # TorusGeometry and TubeGeometry are always non-convex (a revolved or
    # swept curve can never be a flat-sided polytope), so only those two
    # join the primitives already seen in this build.
    ALLOWED_NONCONVEX = {'LatheGeometry', 'TorusGeometry', 'CylinderGeometry',
                         'SphereGeometry', 'TubeGeometry', 'InstancedMesh'}
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        rows = page.evaluate("window.chfFabricConvexity()")
        check(rows, 'chfFabricConvexity reports at least one fabric row')
        by_name = {r['name']: r for r in rows}
        bad = []
        for r in rows:
            if r['kit']:
                continue
            disallowed = [t for t in r['nonconvex'] if t not in ALLOWED_NONCONVEX]
            if disallowed:
                bad.append((r['name'], r['convex'], r['meshes'], disallowed))
        check(not bad,
              'every non-kit row must be convex or a recognized non-box '
              'primitive: %r' % bad)
        check(any(r['kit'] for r in rows),
              'at least one row is a kit (a door/window/porch/lamp assembly)')
        door = by_name.get('living_study_door')
        check(door is not None and door['kit'],
              f"living_study_door is a kit: {door}")
        wall = by_name.get('south_wall')
        check(wall is not None and not wall['kit'] and
              wall['meshes'] > 0 and wall['convex'] == wall['meshes'],
              f"south_wall is fully convex: {wall}")
        # Corrected (v2.499.51): a windowed wall is NOT a kit -- its
        # boxes clip pre-merge like any other box, exactly what the
        # first version of this scenario got wrong.
        for name in ('east_wall', 'east_partition', 'north_cladding',
                     'north_wall_east', 'garage_block_west', 'west_cladding',
                     'garage_shell', 'yard', 'mudroom_front', 'west_wall'):
            row = by_name.get(name)
            check(row is not None and not row['kit'],
                  f"{name} clips pre-merge, not a kit: {row}")
        # Fix round 1 (v2.499.52): pin the kit SET exactly, not just "at
        # least one exists" -- v2.499.50's regression was nine ordinary
        # windowed walls wrongly marked kit, and a test that only checks
        # "some row is a kit" would never have caught that. Generated
        # kits are named 'facade_<face>_<window|door>_<slot>' (windowAt/
        # doorAt); dormerAt/gableAt/hipEndAt generate facade_ names too
        # but are never kits, so the kind is matched explicitly rather
        # than accepting every facade_ name. The PORCH (porchAt) is not
        # a kit either (task 3 fix round 1 ruling): every piece of it is
        # a box(), so it clips per mesh -- the kit test's box centre sat
        # under the room's floor line and kept the porch roof standing
        # across the living view.
        import re as _re3
        kits = {r['name'] for r in rows if r['kit']}
        expected = {n for n in by_name
                    if _re3.match(r'^facade_.*_(window|door)_\d+$', n)}
        porches = [by_name[n] for n in by_name if _re3.match(r'^facade_.*_porch_\d+$', n)]
        check(porches, 'the canonical elevation has a porch')
        for row in porches:
            check(not row['kit'] and row['meshes'] > 0 and row['convex'] == row['meshes'],
                  f"the porch clips per mesh -- every piece a convex box: {row}")
        expected |= {'garage_door', 'back_door', 'living_study_door',
                     'east_room_door', 'living_back_room_door'}
        check(kits == expected,
              f"kit set is exactly the door/window/porch/lamp list: "
              f"extra={sorted(kits - expected)} missing={sorted(expected - kits)}")


ROOMS = ['kitchen', 'living', 'study', 'garage', 'mudroom']


def scenario_room_masks_cut_only_what_blocks_the_room():
    """Spec 2026-09-16 masking section 2/7: per room, only what stands
    between the camera and the room's eave-high box is cut; everything
    else is whole.

    Every pin below carries its derivation from the mask itself (P: the
    pyramid from the room camera through the box's silhouette; W: behind
    the box's front faces; masked = P and not W), read against the room
    boxes chfRoomMask() reports (kitchen x -10.39..6.5 z -5.8..5.8,
    living x -6.5..6.5 z 5.1..14.22, study x 6.92..15.25 z 7.12..14.45,
    garage x -17.96..-12.83 z 2.21..9.76, mudroom x -12.6..-6.8 z
    2.36..8.3, all y 0..5.6) and the room cameras (HOME_POS 4.64,13.8,23;
    LIV_POS 0,12.8,26.5; STUDY_POS 7.02,4.75,18.82; GARAGE_POS
    -18,10.5,21.3; MUD_POS -3.4,6.2,11.2). Where the task brief's first
    draft of this scenario guessed differently (kitchen: south_wall
    "mostly cut"; study: east_partition "cut"), the geometry says
    otherwise and the pin follows the geometry -- see each comment.

    Names (task 4): the main roof and the street wall are ONE piece
    each again (roof_main_south over the whole block, south_wall x
    -7.15..14.65), so every fraction pinned on them is the old split
    piece's fraction scaled by that piece's share of the whole -- area
    goes with width for the wall (same height and thickness the whole
    run) and for the deck (same span the whole run): the old west half
    of the roof was 14.32 of the deck's 22.44 (0.638), the east 8.12
    (0.362); the old south_wall 14.0 of 21.8 (0.642), south_wall_east
    7.8 (0.358). Each pin below carries its own derivation.
    """
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        fab = page.evaluate('window.chfShellFabric()')
        by = {f['name']: f for f in fab}
        check('maskedFraction' in by['south_wall'], 'rows report maskedFraction per room')
        for f in fab:
            check(set(f['maskedFraction']) == set(ROOMS),
                  f"{f['name']}: a fraction for every room camera, got {sorted(f['maskedFraction'])}")
            check(all(0 <= v <= 1 for v in f['maskedFraction'].values()),
                  f"{f['name']}: fractions are 0..1: {f['maskedFraction']}")
        def frac(name, room):
            return by[name]['maskedFraction'][room]
        # THE GREAT ROOM. Both cameras stand in the street, high (y 12.8 /
        # 13.8), looking down over the front of the house.
        #   living: its box reaches the street wall's inner face (z
        #   14.22 vs 14.20), so the wall straddles the box's south face
        #   and is judged entirely "in front": its cut is P alone, the
        #   room's silhouette projected onto the wall -- nearly the whole
        #   wall between x -6.5 and 6.5 (measured 0.87). The south deck of
        #   the roof over it is cut from the eave up to where the ray to
        #   the box's far-top edge (z 5.1, y 5.6) crosses the deck, z ~10
        #   (measured 0.33). The street windows 7/9/12 and door 10 sit in
        #   the cut wall: kits, box centre masked, dropped whole (1.0).
        # RULING 2 (fix round 1): the street wall straddles the box's
        # south face (inner face 14.20, box 14.22); the straddle rule
        # moves W to the wall's own depth so the cut is P alone -- the
        # silhouette of a 13 x 5.6 box on the wall. TASK 4: the wall is
        # the whole 21.8 run, so the old 0.87 of the 14-wide great-room
        # segment is 0.87 * 0.642 = 0.56 of the one wall; a raw plane
        # would keep the inner sliver and read ~0.3. Pinned > 0.5 (and
        # < 0.6: the pyramid's x span at the wall is the box's 13 of
        # 21.8 = 0.596, the most the living can ever take).
        check(0.5 < frac('south_wall', 'living') < 0.6, f"living: south_wall cut on its silhouette over the great room's run, got {frac('south_wall', 'living')}")
        # the south deck: the old west half's 0.33 is 0.33 * 0.638 = 0.21
        # of the one deck; pinned > 0.1
        check(frac('roof_main_south', 'living') > 0.1, f"living: roof_main_south cut over the room, got {frac('roof_main_south', 'living')}")
        for kit in ('facade_main_window_7', 'facade_main_window_9', 'facade_main_window_12', 'facade_main_door_10'):
            check(frac(kit, 'living') == 1, f'living: {kit} goes whole with the wall it sits in')
        # PORCH (fix round 1 ruling): not a kit -- its boxes clip per
        # mesh. The porch ROW is the slab, step, posts, rails and the
        # eave beam; its roof decks are the facade_main_gable_8_* rows
        # (dropped whole above). What stands in the pyramid is the beam
        # and the tops of the posts -- 13% of the row's surface (the
        # slab, step and rails under the pyramid's floor plane are most
        # of it) -- so the row reads 0.13, not the > 0.4 a roof deck in
        # the row would have given. Pinned > 0.1 with remnants present.
        check(frac('facade_main_porch_8', 'living') > 0.1,
              f"living: the porch beam and post tops are cut, got {frac('facade_main_porch_8', 'living')}")
        # RULING 1 (fix round 1): a facade roof feature (gable/dormer/hip
        # end piece) is dropped WHOLE when the mask would keep less than
        # a fifth of it -- the porch gable's two decks kept 14% and stood
        # as floating shards outside the pyramid -- and clipped normally
        # otherwise (its front kept 30%, the kitchen keeps a quarter of
        # each deck).
        # ROOF VALLEYS (task 5): the decks no longer carry their buried
        # back under the main roof; what stood in the kitchen's cone was
        # mostly that back (the cone's floor crosses z 12 at y 4.97, the
        # buried deck reached 6.84 there), so the kitchen's cut of what
        # remains reads 0.20 where it read 0.25 -- measured, the pin
        # widened to hold it.
        for deck in ('facade_main_gable_8_west', 'facade_main_gable_8_east'):
            check(frac(deck, 'living') == 1, f'living: {deck} drops whole below a fifth kept, got {frac(deck, "living")}')
            check(0.15 < frac(deck, 'kitchen') < 0.3, f'kitchen: {deck} keeps its clipped part, got {frac(deck, "kitchen")}')
        check(0.5 < frac('facade_main_gable_8_front', 'living') < 0.8,
              f"living: the porch gable front is clipped, not dropped, got {frac('facade_main_gable_8_front', 'living')}")
        #   kitchen: the box's near face is z 5.8, INSIDE the open great
        #   room. The pyramid's floor plane runs from HOME_POS through
        #   the box's bottom-south edge (y 0, z 5.8) and crosses the
        #   street wall's plane (z 14.4) at y 6.9 -- above the wall's top
        #   (5.6). Every ray from the kitchen camera to the kitchen box
        #   clears the street wall; it stands between the camera and the
        #   LIVING room, not the kitchen, so it stays (0), and so do the
        #   street windows, the door and the porch. What does block the
        #   kitchen is the roof: the ray to the far-top edge (z -5.8, y
        #   5.6) crosses the south deck at z ~7.9, so the deck comes off
        #   from the eave to there (measured 0.47).
        check(frac('south_wall', 'kitchen') == 0, f"kitchen: south_wall clears every ray to the kitchen box, got {frac('south_wall', 'kitchen')}")
        # the old west half's 0.47 is 0.47 * 0.638 = 0.30 of the one
        # deck; pinned > 0.1
        check(frac('roof_main_south', 'kitchen') > 0.1, f"kitchen: roof_main_south cut over the room, got {frac('roof_main_south', 'kitchen')}")
        for kit in ('facade_main_window_7', 'facade_main_window_9', 'facade_main_window_12', 'facade_main_door_10'):
            check(frac(kit, 'kitchen') == 0, f'kitchen: {kit} is not between the street camera and the kitchen')
        # Nothing east of the great room is between either camera and
        # either room: the study's own walls and windows, the east wall,
        # the future rooms' partitions and the kitchen's own north wall
        # (behind the box, inside W) all stay whole. (The study's street
        # face and roof are the east parts of south_wall / roof_main_south
        # now -- pinned standing by remnant vertex in
        # scenario_a_room_cutaway_leaves_other_rooms_enclosed.)
        for room in ('kitchen', 'living'):
            for whole in ('east_partition', 'east_wall', 'north_wall_east', 'future_room_partition',
                          'facade_main_window_15', 'facade_main_window_16', 'north_wall'):
                check(frac(whole, room) == 0, f'{room}: {whole} untouched, got {frac(whole, room)}')
        # RULING 3 (fix round 1): the yard (yardG, the registered row) is
        # hidden whole in every room view and shown at the exterior --
        # its exempt instanced planting doubled every room's triangles
        # when it drew. Fraction 1 everywhere, like a dropped kit.
        for room in ROOMS:
            check(frac('yard', room) == 1, f'{room}: the yard hides whole, got {frac("yard", room)}')
        # THE STUDY. STUDY_POS stands east of the old split line (x 7.02
        # > 6.92, the box's west face) and low (y 4.75 < the eave), so
        # the only front face is the south one: masked = inside the
        # pyramid through the south face's four edges, south of the box.
        # Its street face -- TASK 4: the east 7.8 of the one south_wall
        # -- straddles that face (the study floor reaches z 14.45, the
        # wall's inner face is 14.20) and is cut by P alone: 0.97 of the
        # old segment, 0.97 * 0.358 = 0.35 of the whole wall; its two
        # windows 15/16 are kits in that wall, dropped whole.
        # east_partition (x 6.44..6.85) is beside the camera, west of the
        # box's west face: NOT between camera and room, whole -- the
        # brief's draft pinned it "cut", which was the pre-refit camera
        # at x 5.85. Window 7 and the kitchen's north wall are outside
        # the pyramid's x span. The roof is above a camera that looks
        # level into the room: the top face is not front; the north deck
        # stays and the south deck is grazed at its overhang only (0.013
        # of the old east half, 0.013 * 0.362 = 0.005 of the one deck).
        # RULING 2: the study floor reaches 0.25 into the street wall;
        # the straddle rule cuts the wall by P alone; a raw plane would
        # keep the inner 0.25 and read ~0.1 of the whole wall. Pinned
        # > 0.3, and < 0.36 (the study's share, 7.8 / 21.8 = 0.358, is
        # the most the study can ever take).
        check(0.3 < frac('south_wall', 'study') < 0.36, f"study: its street face is cut on its silhouette, got {frac('south_wall', 'study')}")
        for kit in ('facade_main_window_15', 'facade_main_window_16'):
            check(frac(kit, 'study') == 1, f'study: {kit} goes whole with the street face')
        for whole in ('east_partition', 'facade_main_window_7', 'north_wall',
                      'roof_main_north', 'living_study_door'):
            check(frac(whole, 'study') == 0, f'study: {whole} whole, got {frac(whole, "study")}')
        check(frac('roof_main_south', 'study') < 0.05, f"study: the south deck is grazed at most, got {frac('roof_main_south', 'study')}")
        # THE MUDROOM. MUD_POS stands in the great room, east of the
        # mudroom's east face (x -3.4 > -6.8), just above the eave (y 6.2)
        # and south of the box (z 11.2 > 8.3): three front faces. The
        # great room's west wall (west_wall, slab x -7.15..-6.8) touches
        # the box's east face and is cut where the box projects onto it
        # (measured 0.37), with its exterior skirt and cladding behind
        # it; mudroom_front (the street wall's inner layer at z 7.94..8.3
        # straddles the south face) is cut where it stands in P (0.52).
        # The garage-block roof over the room: a camera 0.6 above the
        # eave sees the top face almost edge-on, so the pyramid's top
        # plane grazes the deck only at its overhang -- a sliver (0.003),
        # not the deck; the walled volume is seen THROUGH the wall, not
        # through the roof. The garage's own walls are not in the way.
        check(frac('west_wall', 'mudroom') > 0.2, f"mudroom: the great room's west wall opens, got {frac('west_wall', 'mudroom')}")
        check(frac('mudroom_front', 'mudroom') > 0.3, f"mudroom: the street wall's inner layer opens, got {frac('mudroom_front', 'mudroom')}")
        check(0 <= frac('garage_block_roof_south', 'mudroom') < 0.1,
              f"mudroom: the garage-block south deck is grazed at most, got {frac('garage_block_roof_south', 'mudroom')}")
        check(frac('garage_shell', 'mudroom') < 0.1, 'mudroom: the garage walls stay whole')
        # THE GARAGE. GARAGE_POS stands in the driveway, high (y 10.5),
        # 0.04 west of the box's west face: south, top and (barely) west
        # faces are front. The garage door fills the box's south face --
        # a kit, box centre masked, dropped whole; the bay's own gable
        # front over it and the south deck of the block roof are cut
        # where the pyramid passes through them to the box's top face.
        check(frac('garage_door', 'garage') == 1, 'garage: the garage door goes whole')
        check(frac('facade_garage_block_gable_0_front', 'garage') > 0.5, 'garage: the bay gable front is cut')
        check(frac('garage_block_roof_south', 'garage') > 0.1, 'garage: the south deck over the bay is cut')
        for whole in ('mudroom_front', 'west_wall', 'south_wall', 'north_wall', 'garage_block_west'):
            check(frac(whole, 'garage') == 0, f'garage: {whole} whole, got {frac(whole, "garage")}')
        # exterior: nothing masked
        page.evaluate('window.chfHouseExit()')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        fab = page.evaluate('window.chfShellFabric()')
        check(all(f['verdict'] == 'solid' for f in fab), 'exterior: every piece solid')
        check(page.evaluate('window.chfRoomShellShown()') is None, 'exterior: no room shell shown')
        check(page.evaluate('window.chfMaskLeak(null)') == 0, 'exterior: every source shown, every stand-in hidden')
        check(all(f['visible'] for f in fab), 'exterior: every row visible')
        # RULING 2, the direct pin: in the living and study shells no kept
        # vertex of the near wall lies inside P behind the box's near
        # face (z > near face - WALL_T4): the inner sliver a raw W plane
        # would leave is gone. Sampled the way chfRoomShellLeak samples.
        # RULING 1, the direct pin: the living shell holds no remnant of
        # the dropped porch decks; the kitchen shell holds their quarter.
        WALL_T4 = 0.35
        def inside_P(mask, p, eps=1e-3):
            return all(pl['n'][0]*p[0] + pl['n'][1]*p[1] + pl['n'][2]*p[2] - pl['d'] > eps
                       for pl in mask['P'])
        for room, wall in (('living', 'south_wall'), ('study', 'south_wall')):
            mask = page.evaluate(f"window.chfRoomMask('{room}')")
            verts = page.evaluate(f"window.chfRoomShellVerts('{room}', '{wall}', 4000)")
            check(verts, f'{room}: the near wall leaves remnants in the shell')
            near = mask['box'][5] - WALL_T4
            sliver = [p for p in verts if inside_P(mask, p) and p[2] > near]
            check(not sliver, f'{room}: {len(sliver)} kept {wall} vertices inside P behind the near face (inner sliver survived): {sliver[:3]}')
        check(page.evaluate("window.chfRoomShellVerts('living', 'facade_main_porch_8', 100)"),
              'living shell: the porch leaves remnants (its posts and cut deck)')
        for deck in ('facade_main_gable_8_west', 'facade_main_gable_8_east'):
            check(page.evaluate(f"window.chfRoomShellVerts('living', '{deck}', 100)") == [],
                  f'living shell: no {deck} remnant')
            check(page.evaluate(f"window.chfRoomShellVerts('kitchen', '{deck}', 100)"),
                  f'kitchen shell: {deck} clipped quarter present')
        # each room view shows its shell; the swap happened
        for room in ROOMS:
            page.evaluate(f"window.chfHouseEnterRoom('{room}')")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            shown = page.evaluate('window.chfRoomShellShown()')
            check(shown == room, f'{room}: its room shell is the visible one (got {shown})')
            # sampled kept vertices lie outside the mask
            bad = page.evaluate(f"window.chfRoomShellLeak('{room}', 2000)")
            check(bad == 0, f'{room}: no kept vertex inside the mask (got {bad})')
            # fix round 1: every toggled object is in the state this view
            # wants -- a source mesh whose pattern names the room is hidden
            # even when its ROW group is toggled too (a roof feature
            # dropped whole in one view and clipped in another: the early
            # return that skipped such a row's members left the porch
            # deck's source standing in the kitchen cone)
            check(page.evaluate(f"window.chfMaskLeak('{room}')") == 0,
                  f'{room}: no toggled object in the wrong state')
            rows = page.evaluate('window.chfShellFabric()')
            for f in rows:
                want = 'masked' if f['maskedFraction'][room] > 0 else 'solid'
                check(f['verdict'] == want, f"{room}: {f['name']} verdict {f['verdict']} vs fraction {f['maskedFraction'][room]}")
                if f['maskedFraction'][room] == 1:
                    check(not f['visible'], f"{room}: {f['name']} masked whole is hidden")
        check(not served.errors(), f'console clean: {served.errors()[:3]}')


# ---- ROOF VALLEYS (masking spec section 6) ----------------------------
# A facade gable or dormer is built on a block roof deck. Nothing of it
# may exist UNDER that deck inside the house: the part below the parent
# deck's centre plane and behind the street face is cut at build (the
# valley clip), so the mask, which keeps everything inside a room's own
# volume, has nothing buried left to draw. The plane comes from the
# scene (chfRoofPlane: deckPlane, the one derivation shellGable places
# its own decks by); the face line from the slot table.
FEATURE_JS = r"""() => {
  const out = [];
  window.chfShellFabric().forEach(f => {
    const m = /^facade_(garage_block|main)_(gable|dormer|hip_end)_(\d+)/.exec(f.name);
    if (m) out.push({ name: f.name, face: m[1], kind: m[2], slot: +m[3] });
  });
  return out;
}"""
# `proudAtWall`: a gable's ridge cap is level, so its top is as high at
# the wall line as anywhere; the piece's highest vertex against the deck
# plane's height at the wall (ridge x: the same across the face) is the
# ridge's stand over the deck there, plus the cap's 0.125 over the ridge
# line.
VERTEX_AUDIT_JS = """(arg) => {
  const pl = window.chfRoofPlane(arg.face), vs = window.chfFabricVertices(arg.name);
  const faceZ = window.chfFacadeSlots().find(s => s.face === arg.face).z;
  const wallY = (pl.d - pl.n[2] * faceZ) / pl.n[1];
  let buried = 0, worst = 1e9, top = -1e9, n = vs.length;
  vs.forEach(p => {
    const s = pl.n[0]*p[0] + pl.n[1]*p[1] + pl.n[2]*p[2] - pl.d;
    if (p[2] < faceZ - 0.05) { if (s < worst) worst = s; if (s < -0.05) buried++; }
    if (p[1] > top) top = p[1];
  });
  return { n, buried, worst, proudAtWall: top - wallY };
}"""


def _audit_roof_features(page):
    feats = page.evaluate(FEATURE_JS)
    check(feats, 'the facade has roof features')
    seen = {}
    for f in feats:
        if f['kind'] == 'hip_end':
            continue          # a fin standing on the wall line, in front of it
        a = page.evaluate(VERTEX_AUDIT_JS, f)
        check(a['n'] > 0, f"{f['name']}: has vertices")
        check(a['buried'] == 0,
              f"{f['name']}: {a['buried']} of {a['n']} vertices below the "
              f"{f['face']} deck plane behind the face (lowest {a['worst']:.3f})")
        seen[f['name']] = a
    return seen


def scenario_roof_features_stop_at_the_roof_line():
    """Spec 2026-09-16 masking section 6: every vertex of a facade gable or
    dormer behind the street face sits at or above the block deck it sits
    on; a gable's ridge stands proud of that deck at the wall.

    The porch gable (canonical gable_8) keeps the porch's own eave (4.8:
    it IS the porch roof, on the porch posts), so in FRONT of the wall its
    low eaves pass under the main eave as they always have -- the audit
    is 'nothing buried behind the face', not 'nothing below the plane
    anywhere'. Its ridge still stands proud at the wall: 7.505 against
    the deck plane's 5.78 there, 1.725 (its rise 2.525 less the 0.8 the
    porch eave sits under the block eave). The garage bay gable's eave is
    the block eave, so it stands proud by its whole rise (1.92)."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        pl = page.evaluate("window.chfRoofPlane('main')")
        check(pl and abs(pl['n'][1] - _math.cos(_VAULT_PITCH)) < 1e-6
              and abs(pl['n'][2] - _math.sin(_VAULT_PITCH)) < 1e-6,
              f'the main street deck plane tilts up and south at pi/8: {pl}')
        # the plane's height at the wall line is the block eave + 0.18
        y_wall = (pl['d'] - pl['n'][2] * 14.55) / pl['n'][1]
        check(abs(y_wall - 5.78) < 1e-3, f'main deck plane at the wall: {y_wall:.3f} != 5.78')
        seen = _audit_roof_features(page)
        for name, proud in (('facade_main_gable_8_west', 1.725),
                            ('facade_main_gable_8_east', 1.725),
                            ('facade_garage_block_gable_0_west', 1.92),
                            ('facade_garage_block_gable_0_east', 1.92)):
            check(name in seen, f'{name} audited')
            # the ridge cap's top adds 0.125 over the ridge line
            got = seen[name]['proudAtWall']
            check(proud - 0.05 < got < proud + 0.2,
                  f'{name}: stands {got:.3f} proud of the deck at the wall, want ~{proud}')
        check(not served.errors(), f'console clean: {served.errors()[:3]}')


def scenario_a_saved_gable_over_the_study_stays_outside():
    """User report (2026-09-16): a SAVED facade with a gable over the study
    put a shingled wedge with white battens beside the study's glass
    doors, inside the house, in the living view. The gable's decks and
    eave trims ran back and down under the main roof; the mask keeps
    everything inside the room, so it drew them. Reproduced at HEAD with
    a span-3 gable at slot 13 (x 5.57..11.02: it straddles the study
    partition at 6.85, so its buried west deck stood in the great room
    beside the study doors -- scratch/valley-before-13/study-gable-
    living.png); a gable wholly over the study (slot 14) buries the same
    way but the partition hides it from the living camera. After the
    valley clip no vertex of that gable is below the main deck behind
    the wall, and the gable takes the height rule (eave = the block
    eave: ridge = plane + its own rise, 1.894 on a span of 3)."""
    from services import house_facade as hf
    spec = copy.deepcopy(hf.CANONICAL)
    spec['roof'].append({'slot': 13, 'span': 3, 'kind': 'gable'})
    served = live_app(lambda: (_seed(), hf.save_facade('study gable', hf.normalize(spec)[0], activate=True)))
    if served is None:
        return
    try:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.goto(served.url('house?quality=high'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            built = page.evaluate('window.chfFacade()')
            check(any(r['slot'] == 13 and r['kind'] == 'gable' for r in built['roof']),
                  'the saved facade with the study gable is what built')
            seen = _audit_roof_features(page)
            for side in ('west', 'east'):
                a = seen.get(f'facade_main_gable_13_{side}')
                check(a, f'the study gable {side} deck is registered')
                check(1.894 - 0.05 < a['proudAtWall'] < 1.894 + 0.2,
                      f"study gable {side}: stands {a['proudAtWall']:.3f} proud at the wall, want ~1.894")
            # LOOKED at from the living (HOUSE_SHOTS): nothing of the
            # gable lies in the house (behind the wall, under the deck);
            # the audit above is the same statement vertex by vertex
            page.evaluate("window.chfHouseEnterRoom('living')")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            shots = os.environ.get('HOUSE_SHOTS')
            if shots:
                os.makedirs(shots, exist_ok=True)
                page.screenshot(path=os.path.join(shots, 'study-gable-living.png'))
            check(not served.errors(), f'console clean: {served.errors()[:3]}')
    finally:
        for r in hf.list_facades():
            if r.get('id') != hf.CANONICAL_ID and r.get('name') == 'study gable':
                hf.delete_facade(r['id'])
        hf.set_active(hf.CANONICAL_ID)


if __name__ == '__main__':
    scenario_the_house_boots_enters_and_leans_in()
    scenario_leanin_focus_cycles_do_not_leak_textures()
    scenario_fridge_magnets_rebuild_shares_geometry()
    scenario_garage_rebuild_does_not_touch_plaque_textures()
    scenario_shell_fabric_registry()
    scenario_a_room_cutaway_leaves_other_rooms_enclosed()
    scenario_study_sits_inside_the_main_block()
    scenario_the_study_faces_east_behind_glass_doors()
    scenario_interior_walls_rise_to_the_roof()
    scenario_canonical_facade_pins_the_hand_built_elevation()
    scenario_navigation_real_mouse()
    scenario_orbit_eight_stops()
    scenario_orbit_swipe_works_under_a_real_finger()
    scenario_idle_return_snaps_the_orbit_home()
    scenario_shell_without_room_is_inert()
    scenario_worst_case_facade_builds_clean()
    scenario_clipper_cuts_convex_meshes()
    scenario_every_fabric_mesh_is_convex_or_a_kit()
    scenario_room_masks_cut_only_what_blocks_the_room()
    scenario_roof_features_stop_at_the_roof_line()
    scenario_a_saved_gable_over_the_study_stays_outside()
    print("test_house_live OK")
