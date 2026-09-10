"""The studio's shared eye: serve the app, walk the house, save screenshots.

Every studio-pipeline agent (set builders, vehicle artist, lighting artist,
art director) iterates through THIS one command instead of hand-rolling
playwright probes:

    python tools/house_probe.py --views exterior,living --out ../probe_shots
    python tools/house_probe.py --views all --quality high
    python tools/house_probe.py --views garage --clip 300,60,900,600
    python tools/house_probe.py --views kitchen --scenery 0.5

Views: exterior, kitchen, living, mudroom, garage, and lean_<zone> for any
zone (lean_board, lean_door, lean_radio, lean_calendar, ...). `all` = the
five room views. Seeds a standard fixture set (two children, a driver, an
event today, three shopping items, three cars of different bodies, two prep
kits with only one of them claimed) so every signal has something honest to
show - including the mudroom bench, which needs a packed AND an unpacked
group to show both of its backpack states. Requires playwright (skips loudly
without it, exit 0 — the same bargain live_app makes).

Run from chauffeur/. Screenshots land as <out>/<view>.png, 1400x1000.
"""
import argparse
import datetime
import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), 'tests'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_house_probe_'))

ROOM_VIEWS = ['exterior', 'kitchen', 'living', 'mudroom', 'garage']

# The renderer wrapper the --budget flag appends to the vendored three
# bundle via route interception. three assigns render as an INSTANCE
# property, so patching WebGLRenderer.prototype.render is a silent no-op
# — the constructor must be wrapped. No production code ships a debug
# handle; this exists only on probed pages.
THREE_WRAP = b"""
;(function () {
  var OR = window.THREE && window.THREE.WebGLRenderer;
  if (!OR) { window.__hpFail = 'no THREE'; return; }
  function W(p) {
    var r = new OR(p);
    window.__hpT0 = window.__hpT0 || performance.now();
    var o = r.render.bind(r);
    r.render = function (s, c) {
      if (window.__hpBuildMs === undefined)
        window.__hpBuildMs = Math.round(performance.now() - window.__hpT0);
      window.__hpScene = s; window.__hpCam = c; window.__hpR = r;
      return o(s, c);
    };
    return r;
  }
  W.prototype = OR.prototype;
  window.THREE.WebGLRenderer = W;
})();
"""

BUDGET_JS = """() => {
  const T = window.THREE, S = window.__hpScene, C = window.__hpCam;
  if (!S || !C) return { err: 'no captured scene' };
  S.updateMatrixWorld(true); C.updateMatrixWorld(true);
  const fr = new T.Frustum().setFromProjectionMatrix(
    new T.Matrix4().multiplyMatrices(C.projectionMatrix, C.matrixWorldInverse));
  const mats = new Set(), geos = new Set(), rows = {};
  let total = 0, visible = 0, inFrustum = 0, tris = 0;
  function vis(o) { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; }
  S.traverse(o => {
    if (!o.isMesh) return;
    total += 1;
    if (o.material && o.material.uuid) mats.add(o.material.uuid);
    if (o.geometry) geos.add(o.geometry.uuid);
    if (!vis(o)) return;
    visible += 1;
    const inst = o.isInstancedMesh ? o.count : 1;
    if (o.frustumCulled && o.geometry) {
      if (!o.geometry.boundingSphere) o.geometry.computeBoundingSphere();
      const sp = o.geometry.boundingSphere.clone().applyMatrix4(o.matrixWorld);
      if (!fr.intersectsSphere(sp)) return;
    }
    inFrustum += 1;
    const g = o.geometry;
    if (g && g.attributes.position)
      tris += inst * (g.index ? g.index.count / 3 : g.attributes.position.count / 3);
    let top = o; while (top.parent && top.parent !== S) top = top.parent;
    let key;
    if (top === o) key = '(loose)';
    else {
      if (!top.userData.__hpN) {
        let n = 0; top.traverse(q => { if (q.isMesh) n += 1; });
        top.userData.__hpN = n;
      }
      key = 'group@' + ['x', 'y', 'z'].map(a => top.position[a].toFixed(1)).join(',') +
            ' n=' + top.userData.__hpN;
    }
    rows[key] = (rows[key] || 0) + 1;
  });
  return { total, visible, inFrustum, tris: Math.round(tris),
           materials: mats.size, geometries: geos.size,
           buildMs: window.__hpBuildMs,
           rows: Object.entries(rows).sort((a, b) => b[1] - a[1]).slice(0, 8) };
}"""


def _seed():
    from services import storage
    from models.schemas import Car
    storage.add_member({'id': 'k1', 'name': 'Maya', 'role': 'child'})
    storage.add_member({'id': 'k2', 'name': 'Finn', 'role': 'child'})
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color_code': '#38bdf8'})
    now = datetime.datetime.now().replace(microsecond=0)
    start = now + datetime.timedelta(minutes=45)
    sched = {'events': [{'id': 'e1', 'title': 'Soccer practice',
                         'start': start.isoformat(),
                         'end': (start + datetime.timedelta(hours=1)).isoformat()}],
             'assignments': {'e1': 'd1'}}
    storage.get_cached_schedule = lambda: sched
    # Items must hang off a real LIST. The pantry counts every item
    # regardless of list (kitchen_room._board), but the shopping CARD the
    # pantry wears on lean-in fetches per list — so list-less fixture items
    # made the shelves empty and the card say "Nothing on this list" at the
    # same time. The API always assigns a list; the fixture must too.
    from models.schemas import ShoppingList
    _list = ShoppingList(name='Groceries', is_default=True).model_dump()
    storage.add_shopping_list(_list)
    for n in ('Milk', 'Eggs', 'Bread'):
        storage.add_shopping_item({'id': uuid.uuid4().hex, 'name': n,
                                   'list_id': _list['id'],
                                   'is_checked': False, 'created_at': 1})
    # FOUR cars, because two is the number the garage bay holds and every
    # scaling bug in this room hides above it. Each one carries a different
    # telemetry state so a single screenshot judges the whole ladder: fuel,
    # charge, a car low enough to warn, and one that is out.
    storage.add_car(Car(name='Red Truck', body_type='truck',
                        color_code='#c9473d', seat_capacity=4,
                        ha_fuel_entity='sensor.truck_fuel').model_dump())
    storage.add_car(Car(name='Blue Minivan', body_type='minivan',
                        color_code='#3b82f6', seat_capacity=7,
                        ha_battery_entity='sensor.minivan_battery',
                        ha_range_entity='sensor.minivan_range').model_dump())
    storage.add_car(Car(name='Green Wagon', body_type='wagon',
                        color_code='#5f8f4e', seat_capacity=5,
                        ha_fuel_entity='sensor.wagon_fuel').model_dump())
    storage.add_car(Car(name='Silver Hatch', body_type='hatch',
                        color_code='#9aa2a9', seat_capacity=5,
                        ha_device_tracker='device_tracker.hatch',
                        ha_battery_entity='sensor.hatch_battery').model_dump())
    # No Home Assistant here, so the entities above read as nothing and every
    # car would come back "resting" — the same hole the weather stub below
    # fills. Patch the two readers the fleet is built from (the idiom
    # tests/test_house_state.py already uses) rather than ha_api itself, so
    # nothing else in the app starts believing there is an HA.
    from services import cars as cars_svc
    _LEVELS = {'Red Truck': {'battery_pct': None, 'fuel_pct': 68.0, 'range': 340.0},
               'Blue Minivan': {'battery_pct': 82.0, 'fuel_pct': None, 'range': 208.0},
               'Green Wagon': {'battery_pct': None, 'fuel_pct': 14.0, 'range': 41.0},
               'Silver Hatch': {'battery_pct': 47.0, 'fuel_pct': None, 'range': 96.0}}
    cars_svc.car_levels = lambda c: dict(_LEVELS.get(
        (c.get('name') if isinstance(c, dict) else None) or '',
        {'battery_pct': None, 'fuel_pct': None, 'range': None}))
    cars_svc.car_location = lambda c: (
        {'state': 'not_home'}
        if (c.get('name') if isinstance(c, dict) else None) == 'Silver Hatch'
        else None)
    # the mudroom bench draws one backpack per PACKING GROUP, open while the
    # group is still short. Two kits match the seeded event, and only one of
    # them is claimed, so a screenshot carries both states at once — the same
    # reason the window carries a forecast.
    from models.schemas import PrepKit
    for kit in (PrepKit(id='kit_soccer', name='Soccer bag',
                        items=['Water bottle', 'Shin guards'],
                        keywords=['soccer']),
                PrepKit(id='kit_snack', name='Team snack',
                        items=['Orange slices', 'Cooler'],
                        keywords=['soccer'], per_person=False)):
        storage.add_prep_kit(kit.model_dump())
    for item in ('kit_soccer:water bottle', 'kit_soccer:shin guards'):
        storage.add_packing_claim('d1:e1', item, now.date().isoformat())
    # the window is a zone too: with no HA there is no forecast, so the pane
    # renders blank and the weather signal cannot be judged in a screenshot.
    from services import ha_api
    ha_api.get_weather_forecast = lambda _e=None: [
        {'condition': 'partlycloudy', 'temperature': 86,
         'precipitation_probability': 10},
        {'condition': 'sunny', 'temperature': 93, 'precipitation_probability': 0},
        {'condition': 'rainy', 'temperature': 85,
         'precipitation_probability': 60}]


def _settle(page, quiet_frames=30, timeout=25000):
    """Hold until the overlay has said the same thing for `quiet_frames`
    consecutive animation frames.

    FRAMES, not milliseconds, and that is the whole trick: the condition is
    polled on rAF, so a busy main thread hands out one look per frame and a
    quiet one hands out sixty a second. Thirty ticks is therefore half a
    second of genuinely free main thread — which cannot be accumulated while
    the room is still tweening, still rendering, or still waiting on a fetch
    whose continuation has not been let in yet. A wall-clock nap cannot tell
    those apart, which is exactly how the pantry photographed empty.

    A zone with no card of its own (the tip-only lean-in) settles here too:
    the overlay stays hidden, that is its answer, and thirty quiet frames say
    the room has finished deciding.
    """
    page.evaluate("window.__chfSettle = null")
    try:
        page.wait_for_function(
            """(want) => {
                 const ov = document.getElementById('focus-overlay');
                 const on = !!ov && getComputedStyle(ov).display !== 'none';
                 const now = (on ? '1|' + (ov.innerText || '') : '0');
                 const s = window.__chfSettle;
                 if (!s || s.seen !== now) {
                     window.__chfSettle = { seen: now, ticks: 0 };
                     return false;
                 }
                 s.ticks += 1;
                 return s.ticks >= want;
               }""",
            arg=quiet_frames, timeout=timeout)
    except Exception:
        print('  note: never settled inside the budget — the shot is whatever '
              'was on screen, and may be mid-load')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--views', default='exterior')
    ap.add_argument('--quality', default='high',
                    choices=['high', 'medium', 'low'])
    ap.add_argument('--out', default=os.environ.get('HOUSE_PROBE_OUT',
                                                    'probe_shots'))
    ap.add_argument('--clip', default='',
                    help='x,y,w,h crop of the 1400x1000 page')
    ap.add_argument('--no-seed', action='store_true')
    ap.add_argument('--cam', default='',
                    help='px,py,pz,ax,ay,az camera override, applied after '
                         'the view is entered (studio viewfinder)')
    ap.add_argument('--scenery', default='',
                    help='0..1 scenery-recession override, so a value can be '
                         'trialled without editing house.js. 0 = nothing '
                         'recedes; 1 = maximum. Applies to room views only '
                         '(the exterior is always 0).')
    ap.add_argument('--budget', action='store_true',
                    help='wrap the renderer and print per-view draw-budget '
                         'numbers (meshes, in-frustum, tris, unique '
                         'materials/geometries, build ms)')
    args = ap.parse_args()

    views = ROOM_VIEWS[:] if args.views == 'all' else [
        v.strip() for v in args.views.split(',') if v.strip()]
    os.makedirs(args.out, exist_ok=True)

    from live_app import live_app
    served = live_app(None if args.no_seed else _seed)
    if served is None:
        print('SKIP: playwright not installed')
        return 0

    clip = None
    if args.clip:
        x, y, w, h = [int(v) for v in args.clip.split(',')]
        clip = {'x': x, 'y': y, 'width': w, 'height': h}

    with served.browser() as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text)
                if m.type == 'error' else None)
        if args.budget:
            with open('static/vendor/three.min.js', 'rb') as fh:
                patched = fh.read() + THREE_WRAP
            page.route('**/three.min.js*', lambda route: route.fulfill(
                status=200, content_type='application/javascript',
                body=patched))
        page.goto(served.url('house?quality=' + args.quality))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        if args.scenery != '':
            # set once: the knob is a module-level value, and every room
            # change re-applies it. The stats come back so a probe run says
            # how much of the scene actually stepped back.
            print('scenery', page.evaluate(
                'window.chfHouseScenery(' + str(float(args.scenery)) + ')'))
        for view in views:
            if view == 'exterior':
                page.evaluate("window.chfHouseExit && window.chfHouseExit()")
            elif view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            elif view.startswith('lean_'):
                page.evaluate(
                    "window.chfKitchenFocus(" + repr(view[5:]) + ")")
            else:
                page.evaluate(
                    "window.chfHouseEnterRoom(" + repr(view) + ")")
            # A lean-in is a SEQUENCE, and no nap can time it. The room tween
            # (850 ms), the zone tween (650 ms), the focus event, the board
            # fetch, and then whatever reads the mounted card makes of its
            # own — and at --quality high one software-WebGL frame of this
            # scene costs about 2.3 s, so the whole sequence occupies nine
            # seconds of blocked main thread. A screenshot queued behind that
            # is SERVICED the instant the frame ends, which is before the
            # card's reads have landed however long the nap was: at 2800 the
            # pantry photographed as a blank card while its list sat in the
            # DOM 600 ms later. So wait for the card to stop CHANGING.
            if view.startswith('lean_'):
                _settle(page)
            else:
                page.wait_for_timeout(1500)
            if args.cam:
                page.evaluate('window.chfHouseCam(' + args.cam + ')')
                page.wait_for_timeout(400)
            path = os.path.join(args.out, view + '.png')
            page.screenshot(path=path, clip=clip)
            print('shot', path)
            if args.budget:
                b = page.evaluate(BUDGET_JS)
                if b.get('err'):
                    print('budget', view, 'ERR', b['err'])
                else:
                    print('budget %-9s meshes=%d visible=%d inFrustum=%d '
                          'tris=%d materials=%d geometries=%d buildMs=%s'
                          % (view, b['total'], b['visible'], b['inFrustum'],
                             b['tris'], b['materials'], b['geometries'],
                             b['buildMs']))
                    for k, v in b['rows']:
                        print('    %5d  %s' % (v, k))
        if errors:
            print('CONSOLE ERRORS:', errors[:5])
            return 1
    print('ok: no console errors')
    return 0


if __name__ == '__main__':
    sys.exit(main())
