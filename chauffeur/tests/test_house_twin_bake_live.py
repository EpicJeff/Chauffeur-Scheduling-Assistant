"""Baked room lights in real Chromium on the desktop GPU (Tasks 3, 4 and 5 of
docs/superpowers/plans/2026-11-10-house-baked-lights.md, as amended by Rulings B2-B10 in
.superpowers/sdd/2026-11-10-house-baked-lights/progress.md; the node halves are
tests/test_twin_baker_js.py and tests/test_twin_lightmap_material_js.py).

The house, the fake Home Assistant, the panel session and the camera are
tests/house_twin_live_harness.py's, and the pixel reads are
tests/test_house_twin_real_lights_live.py's (read both docstrings first). The
Kitchen's Ceiling light hangs at (9.3, 5.2) pool-house local feet, 10 ft up, off;
the Counter lamp (on, 128) stands on the Kitchen floor at (12.4, 5.2); the Pendant
(on, 255) is not placed; the Changing light (on, rgb (0, 0, 255) at 153) and the
Hall light (off) stand on their rooms' floors. aim_kitchen() looks straight down
on the pool house's ground floor from 50 ft.

Two kinds of page:
  - the desk: /house/twin?tier=high&test=1 signed in as the parent (H.signed_in),
    the page that bakes (High tier, a parent may upload);
  - the wall: L.open_twin's /house/twin?tier=low&test=1&panel=true as the panel,
    the Pi's tier, which never bakes and only downloads.

Hooks the page must give under ?test=1 (beyond the real-lights ones):
  window.__twin.bake.state() -> {key, baking, paused, done, total, baked, stale}
      key     the atlas key of the house drawn (null until the atlas is ready);
      baking  true while a bake run has work left (also while paused);
      paused  true while that work waits for the person to stop (pointer down or
              camera moving, then 2 s still);
      done, total  this run's lights baked and to bake (0, 0 when idle);
      baked   every id this page has baked since it opened, in order: device ids,
      stale   device ids whose bake is missing or out of date for `key`.
  window.__twin.bake.fresh() -> device ids drawn from a loaded bake right now.
  window.__twin.live.lights() rows carry baked: true for a light drawn from its
      bake (it is then real: false and holds no pool PointLight).
The twin's own controls on the desk: a button named 'Bake lighting now', and
while a run works, visible text 'Baking lights {n} of {m}' (m = total, n the
light at work). The wall shows neither.

Where bakes live: services.twin_bakes under twin_store.DATA_DIR/bakes/<key>/:
numbered page files (KTX2 bytes, Ruling B4; the file name's stem is the page
number) and manifest.json ({pages, lights: {device: {page, channel, key}}}).
The lights a desk bakes are the placed light markers; whether the unplaced
Pendant is baked is not pinned.

A full bake of the household takes minutes on the desktop GPU (Basis UASTC
encoding dominates: about 10 s per 2048 page at the fastest level, about 80 s at
the default one), so the waits are long (BAKE_S).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_twin_bake_live.py [scenario ...]
"""
import copy
import hashlib
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402
import test_house_twin_real_lights_live as RL  # noqa: E402
from live_app import goto_retry  # noqa: E402

check = L.check
FAKE = L.FAKE
H = L.H
FT = L.FT

BAKED = ('dev-k-ceiling', 'dev-k-lamp', 'dev-changing-light', 'dev-hall-light')
BAKE_S = 900.0
KEY_RE = re.compile(r'^[0-9a-f]{16,64}$')
KTX2_MAGIC = bytes([0xab, 0x4b, 0x54, 0x58, 0x20, 0x32, 0x30, 0xbb, 0x0d, 0x0a, 0x1a, 0x0a])
PROGRESS = re.compile(r'Baking lights (\d+) of (\d+)')
BAKE_NOW = 'Bake lighting now'

NEAR_LAMP = [(13.4, 6.2), (11.2, 6.3)]           # about 1.5 ft from the Counter lamp, clear of its bulb
WINDOW = (0.0, 9.5, 4.75)                         # the Kitchen's west window (x 0, y 3.5-14.17, sill 1.5, head 8)
WALL_BESIDE = (0.0, 15.8, 4.75)                   # the same wall past the window's end
EYE = (-20.0, 9.5, 5.5)


# --- the page ------------------------------------------------------------------------------

def wait_live(page):
    try:
        page.wait_for_function('() => !!(window.__twin && window.__twin.live)', timeout=20000)
    except Exception:
        raise AssertionError('window.__twin.live is missing: the live layer did not mount')
    deadline = time.time() + 20
    while time.time() < deadline:
        ids = {m.get('device_id') for m in L.markers(page)}
        if ids >= set(L.NAMES):
            return
        page.wait_for_timeout(200)
    raise AssertionError(('every device has a marker', sorted(ids)))


def wait_bake_hook(page):
    try:
        page.wait_for_function('() => !!(window.__twin && window.__twin.bake && typeof window.__twin.bake.state === "function"'
                               ' && typeof window.__twin.bake.fresh === "function")', timeout=20000)
    except Exception:
        raise AssertionError('window.__twin.bake is missing: the view exposes bake.state() and bake.fresh() under ?test=1')


def open_desk(page, served, query='tier=high&test=1'):
    """The desk: /house/twin on the High tier, signed in as the parent."""
    H.signed_in(page)
    goto_retry(page, served.url(f'house/twin?{query}'))
    page.wait_for_function('() => window.__twin && window.__twin.ready === true', timeout=90000)
    H.settle(page)
    wait_live(page)
    wait_bake_hook(page)


def open_wall(page, served):
    """The wall: the Pi's tier, as the panel."""
    L.open_twin(page, served)
    wait_bake_hook(page)


def reopen(page):
    page.reload()
    page.wait_for_function('() => window.__twin && window.__twin.ready === true', timeout=90000)
    H.settle(page)
    wait_live(page)
    wait_bake_hook(page)


def state(page):
    return page.evaluate('() => window.__twin.bake.state()')


def fresh(page):
    return set(page.evaluate('() => window.__twin.bake.fresh()'))


def wait_baked(page, devices=BAKED, timeout=BAKE_S):
    """Wait until no run is working and every device is drawn from a bake."""
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        last = state(page)
        if last.get('key') and not last.get('baking') and set(devices) <= fresh(page):
            return last
        page.wait_for_timeout(1000)
    raise AssertionError(('the bake never landed', sorted(devices), last, sorted(fresh(page))))


def wait_until(page, cond, seconds, why):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cond():
            return
        page.wait_for_timeout(250)
    check(cond(), why)


def bake_requests(page):
    """(method, path) of every request the page makes to api/house/bakes/, in order."""
    seen = []

    def on_request(request):
        if '/api/house/bakes/' in request.url:
            seen.append((request.method, request.url.split('?')[0].split('/api/house/bakes/', 1)[1]))
    page.on('request', on_request)
    return seen


def writes(seen, since=0):
    # The server lease (Ruling B17) is not bake data: writes are page uploads and manifests.
    return [(m, p) for m, p in seen[since:] if m != 'GET' and not p.endswith('/lease')]


def baked_row(page, device_id):
    return RL.light(page, device_id)


def is_baked(row):
    return row is not None and row.get('baked') is True and row.get('real') is False and row.get('intensity', 0) > 0


def programs(page):
    return page.evaluate('() => window.__twin.renderer3.info.programs.length')


def sample_at(page, local_points, r=3):
    """Mean RGB around pool-house local points (x, y, z feet above the ground); sprites hidden."""
    lots = [L.lot_of_local(page, x, y) + [z] for x, y, z in local_points]
    out = page.evaluate(RL.SAMPLE_JS, [lots, FT, r])
    for point, row in zip(local_points, out):
        check(row['inside'], ('the sample is on screen', point))
    return [row['rgb'] for row in out]


def aim_local(page, eye, target):
    lot_eye = L.lot_of_local(page, eye[0], eye[1]) + [eye[2]]
    lot_target = L.lot_of_local(page, target[0], target[1]) + [target[2]]
    page.evaluate('([e, t]) => window.__twin.aim(e, t)', [lot_eye, lot_target])
    H.settle(page, 3)


def only_on(page, entity_id, **attrs):
    """Every light off but this one, on with these attributes."""
    for eid in ('light.ceiling_light', 'light.counter_lamp', 'light.pendant', 'light.changing_light', 'light.hall_light'):
        if eid != entity_id:
            RL.set_light(eid, 'off')
    if entity_id:
        RL.set_light(entity_id, 'on', **attrs)
    L.refresh(page)
    RL.calm(page)


def track_errors(page):
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
    return errors


# --- the store -----------------------------------------------------------------------------

def bake_dir(key):
    from services import twin_store
    return os.path.join(twin_store.DATA_DIR, 'bakes', key)


def page_files(key):
    """{page number: sha256} of the stored page files of a key."""
    folder, out = bake_dir(key), {}
    if not os.path.isdir(folder):
        return out
    for name in os.listdir(folder):
        if name == 'manifest.json':
            continue
        stem = name.split('.')[0]
        with open(os.path.join(folder, name), 'rb') as f:
            out[int(stem) if stem.isdigit() else name] = hashlib.sha256(f.read()).hexdigest()
    return out


def page_bytes(key, page_no):
    folder = bake_dir(key)
    for name in os.listdir(folder):
        if name.split('.')[0] == str(page_no):
            with open(os.path.join(folder, name), 'rb') as f:
                return f.read()
    return None


def stored_manifest(key):
    from services import twin_bakes
    try:
        return twin_bakes.read_manifest(key)
    except FileNotFoundError:
        return None


def clear_bakes():
    from services import twin_bakes
    twin_bakes.prune(set())


def ktx2_problem(data):
    """None when the bytes are one whole KTX2 file: magic, header and every level inside the file."""
    if data is None:
        return 'missing'
    if data[:12] != KTX2_MAGIC:
        return 'not KTX2 (magic)'
    if len(data) < 80:
        return 'shorter than a KTX2 header'
    levels = max(1, int.from_bytes(data[40:44], 'little'))
    if len(data) < 80 + 24 * levels:
        return 'level index cut short'
    for i in range(levels):
        at = 80 + 24 * i
        offset = int.from_bytes(data[at:at + 8], 'little')
        length = int.from_bytes(data[at + 8:at + 16], 'little')
        if offset + length > len(data):
            return f'level {i} runs past the end ({offset} + {length} > {len(data)})'
    return None


def move_hall_light(u=.25, v=.3):
    from services import twin_store

    def mutate(before):
        model = copy.deepcopy(before)
        for d in H.building(model, L.POOL).get('devices') or []:
            if d.get('device') == 'dev-hall-light':
                d['host'] = {'floor': L.HALL, 'u': u, 'v': v}
        return model
    twin_store.update_model(mutate, 'edit', note='bake: the Hall light moved by hand')


def lum(p):
    return RL.lum(p)


def mean(values):
    return RL.mean(values)


def desk_baked(served, page):
    """Open the desk and wait until its bake has landed (at once when bakes are stored)."""
    open_desk(page, served)
    return wait_baked(page)


def kitchen_rise(page, points=None):
    """Ceiling light off -> on in Lights mode over the Kitchen: (near rise, far rise, detail)."""
    L.aim_kitchen(page)
    only_on(page, None)
    page.evaluate("() => window.__twin.setTime('night')")
    RL.lights_mode(page)
    near, far = points or RL.NEAR_CEILING, RL.FAR_KITCHEN
    off_near, off_far = RL.sample(page, near), RL.sample(page, far)
    only_on(page, 'light.ceiling_light', brightness=255)
    on_near, on_far = RL.sample(page, near), RL.sample(page, far)
    near_rise = mean(lum(a) - lum(b) for a, b in zip(on_near, off_near))
    far_rise = mean(lum(a) - lum(b) for a, b in zip(on_far, off_far))
    return near_rise, far_rise, {'near_rise': round(near_rise, 1), 'far_rise': round(far_rise, 1),
                                 'on_near': [round(lum(p), 1) for p in on_near], 'on_far': [round(lum(p), 1) for p in on_far]}


# --- scenarios -----------------------------------------------------------------------------

def scenario_bake_runs_on_idle_and_lands():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = bake_requests(page)
        open_desk(page, s)
        wait_until(page, lambda: state(page).get('baking') or set(BAKED) <= fresh(page), 60,
                   ('a bake starts by itself on an open desk', state(page)))
        st = wait_baked(page)
        check(KEY_RE.match(st['key'] or ''), ('the atlas key', st))
        check(set(BAKED) <= set(st['baked']), ('this page baked every placed light', st))
        check('sky' not in st['baked'], ('only room lights bake', st))
        check(st['stale'] == [] or not set(BAKED) & set(st['stale']), ('nothing placed is left stale', st))
        key = st['key']
        m = stored_manifest(key)
        check(m and set(BAKED) <= set(m['lights']), ('the manifest lists every baked light', m))
        files = page_files(key)
        check(files, ('pages are stored under the key', bake_dir(key)))
        for number in files:
            check(ktx2_problem(page_bytes(key, number)) is None, ('a stored page is a whole KTX2 file (Ruling B4)', number,
                                                                    ktx2_problem(page_bytes(key, number))))
        for entry in m['lights'].values():
            check(entry['page'] in files, ('every page the manifest names is stored', entry, sorted(files)))
        w = writes(seen)
        check(w and all(p.startswith(key) for _, p in w), ('every upload is under the drawn atlas key', w))
        check(w[-1] == ('PUT', key), ('the manifest is written last', w[-6:]))
        check(any(m_ == 'POST' for m_, _ in w), ('pages were uploaded', w))

        # A new page finds the bake: nothing stale, nothing uploaded, every light drawn baked.
        before = len(seen)
        reopen(page)
        wait_until(page, lambda: set(BAKED) <= fresh(page), 120, ('a reopened desk draws the stored bake', sorted(fresh(page))))
        page.wait_for_timeout(6000)
        st = state(page)
        check(st['baked'] == [] and not st['baking'], ('a reopened desk bakes nothing', st))
        check(writes(seen, before) == [], ('and uploads nothing', writes(seen, before)))
        L.no_errors(s)


def scenario_baked_light_does_not_cross_a_wall():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        desk_baked(s, page)
        L.aim_kitchen(page)
        only_on(page, None)
        page.evaluate("() => window.__twin.setTime('night')")
        RL.lights_mode(page)
        rooms_next_door = RL.HALL_FLOOR + RL.NEAR_CHANGING
        off_next, off_near = RL.sample(page, rooms_next_door), RL.sample(page, RL.NEAR_CEILING)
        only_on(page, 'light.ceiling_light', brightness=255)
        row = baked_row(page, 'dev-k-ceiling')
        check(is_baked(row), ('the Ceiling light draws from its bake', row))
        check(RL.lamp_at(page, 'dev-k-ceiling') is None, ('a baked light holds no pool PointLight', RL.lit_pool(page)))
        on_next, on_near = RL.sample(page, rooms_next_door), RL.sample(page, RL.NEAR_CEILING)
        near_rise = mean(lum(a) - lum(b) for a, b in zip(on_near, off_near))
        check(near_rise > 25, ('the Kitchen floor under the light brightens', round(near_rise, 1)))
        crossed = [(pt, round(lum(a) - lum(b), 1)) for pt, a, b in zip(rooms_next_door, on_next, off_next) if abs(lum(a) - lum(b)) > 3]
        check(not crossed, ('no baked light lands in the Hall or the Changing room through the wall (+-3)', crossed))
        L.no_errors(s)


def scenario_moving_a_light_rebakes_only_it():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            seen = bake_requests(page)
            st = desk_baked(s, page)
            key = st['key']
            files_before, m_before = page_files(key), stored_manifest(key)
            L.aim_kitchen(page)
            only_on(page, 'light.ceiling_light', brightness=255)
            page.evaluate("() => window.__twin.setTime('night')")
            RL.lights_mode(page)
            kitchen_before = RL.sample(page, RL.NEAR_CEILING + RL.KITCHEN_REF)

            move_hall_light()
            before = len(seen)
            reopen(page)
            wait_until(page, lambda: 'dev-hall-light' in state(page)['baked'] and not state(page)['baking'], BAKE_S,
                       ('the moved Hall light re-bakes', state(page)))
            st = state(page)
            check(st['key'] == key, ('moving a light changes no geometry: the same atlas key', key, st['key']))
            check(st['baked'] == ['dev-hall-light'], ('only the moved light re-bakes (Review Focus 4)', st['baked']))
            m_after = stored_manifest(key)
            check(m_after['lights']['dev-hall-light']['key'] != m_before['lights']['dev-hall-light']['key'],
                  ('the Hall light has a new key', m_before['lights']['dev-hall-light'], m_after['lights']['dev-hall-light']))
            for did in ('dev-k-ceiling', 'dev-k-lamp', 'dev-changing-light'):
                check(m_after['lights'][did] == m_before['lights'][did], ('the other lights keep their entries', did))
            files_after = page_files(key)
            changed = sorted(n for n in files_after if files_after.get(n) != files_before.get(n))
            # With reach a light spans several pages (its 'pages'); only those may be rewritten.
            hall = m_after['lights']['dev-hall-light']
            check(changed and set(changed) <= set(hall.get('pages') or [hall['page']]),
                  ("only the Hall light's pages are rewritten", changed, hall))
            check(all(m_ in ('POST', 'PUT') for m_, _ in writes(seen, before)), writes(seen, before))

            # The Kitchen's channels on that page keep their light.
            L.aim_kitchen(page)
            only_on(page, 'light.ceiling_light', brightness=255)
            page.evaluate("() => window.__twin.setTime('night')")
            RL.lights_mode(page)
            check(is_baked(baked_row(page, 'dev-k-ceiling')), ('the Ceiling light draws baked', baked_row(page, 'dev-k-ceiling')))
            kitchen_after = RL.sample(page, RL.NEAR_CEILING + RL.KITCHEN_REF)
            drift = [round(lum(a) - lum(b), 1) for a, b in zip(kitchen_after, kitchen_before)]
            check(all(abs(d) <= 3 for d in drift), ('the Kitchen lights exactly as before the Hall light moved', drift))
            L.no_errors(s)
    finally:
        L.reset()


def scenario_baked_kitchen_lights_like_the_real_one():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        desk_baked(s, page)
        near_rise, far_rise, detail = kitchen_rise(page)
        row = baked_row(page, 'dev-k-ceiling')
        check(is_baked(row) and abs(row['intensity'] - 1) < .01 and list(row['rgb']) == [255, 241, 201], ('full warm white, baked', row))
        check(RL.lamp_at(page, 'dev-k-ceiling') is None, ('no pool PointLight for a baked light', RL.lit_pool(page)))
        check(near_rise > 25, ('the floor under the baked light brightens clearly', detail))
        check(near_rise > far_rise + 15, ('baked light falls off with distance', detail))
        check(mean(detail['on_near']) > mean(detail['on_far']) + 10, ('under the light is brighter than the far corner', detail))
        L.no_errors(s)
    # The real-time light on the wall with every bake page refused: the baked rise is the real one's, within 2x.
    L.reset()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        page.route('**/api/house/bakes/*/*', lambda route: route.fulfill(status=404, content_type='application/json', body='{"detail":"Not Found"}'))
        open_wall(page, s)
        real_rise, _, real_detail = kitchen_rise(page)
        check(RL.is_on(RL.light(page, 'dev-k-ceiling')), ('with no bake the Ceiling light is real-time', RL.light(page, 'dev-k-ceiling')))
        check(.5 * real_rise <= near_rise <= 2 * real_rise, ('the baked light is about as bright as the real one',
                                                             {'baked': detail, 'real': real_detail}))


def scenario_toggle_is_exact():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        desk_baked(s, page)
        L.aim_kitchen(page)
        only_on(page, None)
        page.evaluate("() => window.__twin.setTime('night')")
        RL.lights_mode(page)
        points = RL.NEAR_CEILING + RL.FAR_KITCHEN + RL.HALL_FLOOR
        off1 = RL.sample(page, points)
        count = programs(page)
        only_on(page, 'light.ceiling_light', brightness=255)
        check(is_baked(baked_row(page, 'dev-k-ceiling')), ('on, baked', baked_row(page, 'dev-k-ceiling')))
        on = RL.sample(page, points)
        check(lum(on[0]) - lum(off1[0]) > 25, ('the light is on', on[0], off1[0]))
        only_on(page, 'light.ceiling_light', brightness=128)
        only_on(page, None)
        off2 = RL.sample(page, points)
        moved = [(pt, [round(a - b, 1) for a, b in zip(p2, p1)]) for pt, p1, p2 in zip(points, off1, off2)
                 if any(abs(a - b) > 2 for a, b in zip(p2, p1))]
        check(not moved, ('off returns every pixel to its unlit value (+-2 per channel)', moved))
        check(programs(page) == count, ('on, dim and off compile no shader (fixed uniforms)', count, programs(page)))
        L.no_errors(s)


def scenario_colour_follows_live():
    s = L.serve()
    if s is None:
        return
    L.reset()
    RL.changing_on_ceiling()
    L.facts()
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            desk_baked(s, page)
            L.aim_kitchen(page)
            only_on(page, None)
            page.evaluate("() => window.__twin.setTime('night')")
            RL.lights_mode(page)
            off_near, off_ref = RL.sample(page, RL.NEAR_CHANGING), RL.sample(page, RL.KITCHEN_REF)
            only_on(page, 'light.changing_light', brightness=153, rgb_color=[0, 0, 255])
            row = baked_row(page, 'dev-changing-light')
            check(is_baked(row) and list(row['rgb']) == [0, 0, 255] and abs(row['intensity'] - .6) < .01, ('a baked blue light at 60 percent', row))
            check(RL.lamp_at(page, 'dev-changing-light') is None, ('no pool PointLight for it', RL.lit_pool(page)))
            count = programs(page)
            blue_near, blue_ref = RL.sample(page, RL.NEAR_CHANGING), RL.sample(page, RL.KITCHEN_REF)

            def tint(after, before, a, b):
                return mean((p[a] - p[b]) - (q[a] - q[b]) for p, q in zip(after, before))
            check(tint(blue_near, off_near, 2, 0) > 15, ('the Changing room turns blue', blue_near, off_near))
            check(abs(tint(blue_ref, off_ref, 2, 0)) < 6, ('the Kitchen does not', blue_ref, off_ref))
            only_on(page, 'light.changing_light', brightness=153, rgb_color=[255, 0, 0])
            red_near = RL.sample(page, RL.NEAR_CHANGING)
            check(tint(red_near, off_near, 0, 2) > 15, ('red now: the colour follows live', red_near, off_near))
            check(list(baked_row(page, 'dev-changing-light')['rgb']) == [255, 0, 0], baked_row(page, 'dev-changing-light'))
            check(programs(page) == count, ('a colour change compiles no shader', count, programs(page)))
            L.no_errors(s)
    finally:
        L.reset()


def scenario_lit_room_glows_through_its_windows_from_outside():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        desk_baked(s, page)
        page.evaluate("() => window.__twin.setView('ext')")
        aim_local(page, EYE, WINDOW)
        only_on(page, None)
        page.evaluate("() => window.__twin.setTime('night')")
        RL.lights_mode(page)
        off_window, off_wall = sample_at(page, [WINDOW, WALL_BESIDE])
        RL.set_light('light.ceiling_light', 'on', brightness=255)
        RL.set_light('light.counter_lamp', 'on', brightness=255)
        L.refresh(page)
        RL.calm(page)
        for did in ('dev-k-ceiling', 'dev-k-lamp'):
            check(is_baked(baked_row(page, did)), ('the Kitchen lights draw baked', did, baked_row(page, did)))
        on_window, on_wall = sample_at(page, [WINDOW, WALL_BESIDE])
        detail = {'window': [round(lum(off_window), 1), round(lum(on_window), 1)], 'wall': [round(lum(off_wall), 1), round(lum(on_wall), 1)]}
        check(lum(on_window) - lum(off_window) > 15, ('the lit Kitchen glows through its window from outside', detail))
        check(abs(lum(on_wall) - lum(off_wall)) <= 4, ('the wall beside it does not', detail))
        L.no_errors(s)


def scenario_pi_tier_draws_baked_lights():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        key = desk_baked(s, page)['key']
    # A partial bake (Review Focus 3): the Changing light is not in the manifest yet.
    from services import twin_bakes
    m = stored_manifest(key)
    m['lights'].pop('dev-changing-light', None)
    twin_bakes.save_manifest(key, m)
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            seen = bake_requests(page)
            open_wall(page, s)
            wait_until(page, lambda: {'dev-k-ceiling', 'dev-k-lamp', 'dev-hall-light'} <= fresh(page), 120,
                       ('the wall loads the stored bake', state(page), sorted(fresh(page))))
            check(state(page)['key'] == key, ('the wall draws the same atlas key', state(page), key))
            check('dev-changing-light' not in fresh(page), ('a light missing from the manifest is not drawn baked', sorted(fresh(page))))
            L.aim_kitchen(page)
            page.evaluate("() => window.__twin.setTime('night')")
            RL.lights_mode(page)
            lamp = baked_row(page, 'dev-k-lamp')
            check(is_baked(lamp), ('on the Pi the Counter lamp draws from its bake', lamp))
            check(RL.lamp_at(page, 'dev-k-lamp', floor_lamp=True) is None, ('and holds no pool PointLight', RL.lit_pool(page)))
            changing = RL.light(page, 'dev-changing-light')
            check(RL.is_on(changing) and changing.get('baked') is not True, ('the unbaked Changing light is real-time', changing))
            check(RL.lamp_at(page, 'dev-changing-light', floor_lamp=True), ('with its pool PointLight', RL.lit_pool(page)))
            check(len(RL.pool(page)) == 4, ('the Pi keeps its pool of four', len(RL.pool(page))))
            # The Counter lamp (on at 128) alone lifts these spots to ~200-219 of 255, where the
            # tone curve squeezes any further rise: measure the ceiling light from the lamp off.
            RL.set_light('light.counter_lamp', 'off')
            L.refresh(page)
            RL.calm(page)
            off_near = RL.sample(page, RL.NEAR_CEILING)
            RL.set_light('light.ceiling_light', 'on', brightness=255)
            L.refresh(page)
            RL.calm(page)
            check(is_baked(baked_row(page, 'dev-k-ceiling')), ('the Ceiling light draws baked on the Pi', baked_row(page, 'dev-k-ceiling')))
            on_near = RL.sample(page, RL.NEAR_CEILING)
            rise = mean(lum(a) - lum(b) for a, b in zip(on_near, off_near))
            check(rise > 25, ('the Pi lights the Kitchen from the bake', round(rise, 1)))
            RL.set_light('light.counter_lamp', 'on', brightness=128)
            check(writes(seen) == [], ('the Pi never uploads', writes(seen)))
            check(not state(page)['baking'] and state(page)['baked'] == [], ('the Pi never bakes', state(page)))
            L.no_errors(s)

            # Every page fetch 404s: every light falls back to real-time, and nothing errors.
            page.route('**/api/house/bakes/*/*', lambda route: route.fulfill(status=404, content_type='application/json', body='{"detail":"Not Found"}'))
            reopen(page)
            page.wait_for_timeout(8000)
            check(fresh(page) == set(), ('no page, no baked light', sorted(fresh(page))))
            L.aim_kitchen(page)
            page.evaluate("() => window.__twin.setTime('night')")
            RL.lights_mode(page)
            lamp = RL.light(page, 'dev-k-lamp')
            check(RL.is_on(lamp) and lamp.get('baked') is not True, ('the Counter lamp falls back to real-time', lamp))
            L.no_errors(s)
    finally:
        L.reset()


def scenario_no_bake_behaves_like_783():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = bake_requests(page)
        open_wall(page, s)
        page.wait_for_timeout(5000)
        check(fresh(page) == set(), ('no bake: nothing drawn baked', sorted(fresh(page))))
        check(len(RL.pool(page)) == 4, ('the low pool of four', len(RL.pool(page))))
        near_rise, far_rise, detail = kitchen_rise(page)
        row = RL.light(page, 'dev-k-ceiling')
        check(RL.is_on(row) and row.get('baked') is not True, ('the Ceiling light is real-time, as in v2.499.783', row))
        check(RL.lamp_at(page, 'dev-k-ceiling'), ('a lit PointLight at the Ceiling light', RL.lit_pool(page)))
        check(near_rise > 25 and near_rise > far_rise + 15, ('v2.499.783\'s real light', detail))
        check(writes(seen) == [], ('the wall uploads nothing', writes(seen)))
        L.no_errors(s)


def scenario_bake_pauses_while_dragging():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        open_desk(page, s)
        wait_until(page, lambda: state(page).get('baking') and not state(page).get('paused') and state(page).get('total', 0) >= 2, 120,
                   ('a bake starts by itself', state(page)))
        box = page.locator('#twin-canvas canvas').bounding_box()
        cx, cy = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        try:
            page.mouse.move(cx + 30, cy + 10, steps=4)
            page.wait_for_timeout(500)
            first = state(page)
            check(first['paused'] and first['baking'], ('a drag pauses the bake', first))
            marks = []
            for i in range(30):
                page.mouse.move(cx + 30 + 40 * ((i % 4) - 1.5), cy + 10 + 20 * ((i % 3) - 1), steps=2)
                page.wait_for_timeout(120)
                marks.append(state(page))
            check(all(st['paused'] for st in marks), ('paused for as long as the camera moves', [st['paused'] for st in marks]))
            check(marks[-1]['done'] - first['done'] <= 1, ('no new light is baked while dragging (one in flight may land)',
                                                           first['done'], marks[-1]['done']))
        finally:
            page.mouse.up()
        page.wait_for_timeout(1000)
        check(state(page)['paused'], ('still paused a second after letting go (2 s still)', state(page)))
        held = state(page)['done']
        wait_until(page, lambda: not state(page)['paused'] and (state(page)['done'] > held or not state(page)['baking']), 120,
                   ('the bake resumes once the view is still', state(page)))
        L.no_errors(s)


def scenario_bake_now_rebakes_everything():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = bake_requests(page)
        st = desk_baked(s, page)
        key, m = st['key'], stored_manifest(st['key'])
        already, before = len(st['baked']), len(seen)
        button = page.get_by_role('button', name=BAKE_NOW, exact=True).locator('visible=true')
        check(button.count() == 1, (f'one visible {BAKE_NOW!r} button on the desk', button.count()))
        button.first.click()
        wait_until(page, lambda: state(page)['baking'], 30, ('the button starts a run', state(page)))
        check(state(page)['total'] >= len(BAKED), ('the run counts every light', state(page)))
        st = wait_baked(page)
        again = st['baked'][already:]
        check(set(BAKED) == set(again), ('every room light bakes again', again))
        posted = {p.split('/')[-1].split('.')[0] for m_, p in writes(seen, before) if m_ == 'POST'}
        named = {str(e['page']) for e in m['lights'].values()}
        check(named <= posted, ('every page is uploaded again', sorted(named), sorted(posted)))
        check(all(stored_manifest(key)['lights'][d]['key'] == m['lights'][d]['key'] for d in BAKED),
              ('nothing moved: the light keys stay', m['lights'], stored_manifest(key)['lights']))
        L.no_errors(s)


def scenario_progress_words():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        open_desk(page, s)
        wait_until(page, lambda: state(page)['baking'], 120, ('a bake starts by itself', state(page)))
        words = page.get_by_text(PROGRESS).locator('visible=true')
        wait_until(page, lambda: words.count() >= 1, 20, ('the desk shows "Baking lights {n} of {m}" while it works', state(page)))
        seen = set()
        for _ in range(20):
            if not state(page)['baking']:
                break
            texts = [t for t in words.all_inner_texts() if PROGRESS.search(t)]
            if not texts:
                break
            st_before = state(page)
            n, total = map(int, PROGRESS.search(texts[0]).groups())
            st_after = state(page)
            check(total in (st_before['total'], st_after['total']), ('m is the run\'s total', texts[0], st_before, st_after))
            check(1 <= n <= total, ('1 <= n <= m', texts[0]))
            check(st_before['done'] <= n <= st_after['done'] + 1, ('n is the light at work', texts[0], st_before, st_after))
            seen.add(n)
            page.wait_for_timeout(1500)
        wait_baked(page)
        H.settle(page, 3)
        check(page.get_by_text(re.compile(r'Baking lights')).locator('visible=true').count() == 0, 'the words go once the bake is done')
        button = page.get_by_role('button', name=BAKE_NOW, exact=True).locator('visible=true')
        check(button.count() == 1 and button.first.is_enabled(), (f'{BAKE_NOW!r} is offered on the desk', button.count()))
        L.no_errors(s)
    with s.browser(launch_args=L.GPU_ARGS) as page:
        open_wall(page, s)
        page.wait_for_timeout(3000)
        check(page.get_by_role('button', name=BAKE_NOW, exact=True).locator('visible=true').count() == 0,
              f'the wall (it never bakes) offers no {BAKE_NOW!r}')
        check(page.get_by_text(re.compile(r'Baking lights')).locator('visible=true').count() == 0, 'nor progress words')
        L.no_errors(s)


def scenario_two_tabs_bake_without_tearing():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        open_desk(page, s)
        # A second tab of the same browser (same localStorage and IndexedDB, as real tabs share).
        with page.expect_popup() as popup:
            page.evaluate('(url) => { window.open(url, "_blank"); }', s.url('house/twin?tier=high&test=1'))
        other = popup.value
        other.set_viewport_size({'width': 1400, 'height': 1000})
        other_errors = track_errors(other)
        other.wait_for_function('() => window.__twin && window.__twin.ready === true', timeout=90000)
        H.settle(other)
        wait_live(other)
        wait_bake_hook(other)
        first, second = wait_baked(page), wait_baked(other)
        check(first['key'] == second['key'], ('both tabs end on the same key (Review Focus 2)', first['key'], second['key']))
        key = first['key']
        m = stored_manifest(key)
        check(set(BAKED) <= set(m['lights']), ('the manifest lists every light', m))
        files = page_files(key)
        torn = {n: ktx2_problem(page_bytes(key, n)) for n in files if ktx2_problem(page_bytes(key, n))}
        check(not torn, ('no stored page is torn', torn))
        for entry in list(m['lights'].values()):
            check(entry['page'] in files, ('every page the manifest names exists', entry, sorted(files)))

        # Neither tab's write lost the other's channel: each Kitchen light lights the floor on its own.
        reopen(other)
        wait_until(other, lambda: set(BAKED) <= fresh(other), 120, ('the reopened tab draws the bake', sorted(fresh(other))))
        L.aim_kitchen(other)
        only_on(other, None)
        other.evaluate("() => window.__twin.setTime('night')")
        RL.lights_mode(other)
        dark_ceiling, dark_lamp = RL.sample(other, RL.NEAR_CEILING), RL.sample(other, NEAR_LAMP)
        only_on(other, 'light.ceiling_light', brightness=255)
        check(is_baked(baked_row(other, 'dev-k-ceiling')), baked_row(other, 'dev-k-ceiling'))
        ceiling = mean(lum(a) - lum(b) for a, b in zip(RL.sample(other, RL.NEAR_CEILING), dark_ceiling))
        only_on(other, 'light.counter_lamp', brightness=255)
        check(is_baked(baked_row(other, 'dev-k-lamp')), baked_row(other, 'dev-k-lamp'))
        lamp = mean(lum(a) - lum(b) for a, b in zip(RL.sample(other, NEAR_LAMP), dark_lamp))
        check(ceiling > 25 and lamp > 25, ('both Kitchen lights kept their channel', round(ceiling, 1), round(lamp, 1)))
        L.no_errors(s)
        check(not H.unexpected(other_errors), H.unexpected(other_errors))


def other_page(page):
    """A second, separate browser context on the same browser (another machine's cookies)."""
    context = page.context.browser.new_context(viewport={'width': 1400, 'height': 1000})
    return context, context.new_page()


def scenario_wall_opened_before_the_bake_picks_it_up():
    """I1: a wall that opens before any bake draws the bake once a desk lands it, without a reload."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    with s.browser(launch_args=L.GPU_ARGS) as wall:
        seen = bake_requests(wall)
        open_wall(wall, s)
        wait_until(wall, lambda: bool(state(wall).get('key')), 120, ('the wall computes its atlas key', state(wall)))
        wall.wait_for_timeout(3000)
        check(fresh(wall) == set(), ('no bake yet: nothing drawn baked', sorted(fresh(wall))))
        wall_key = state(wall)['key']
        context, desk = other_page(wall)
        try:
            desk_errors = track_errors(desk)
            open_desk(desk, s)
            st = wait_baked(desk)
            check(st['key'] == wall_key, ('the wall polls the very key the desk bakes', wall_key, st['key']))
            check(not H.unexpected(desk_errors), H.unexpected(desk_errors))
        finally:
            context.close()
        wait_until(wall, lambda: set(BAKED) <= fresh(wall), 90,
                   ('the wall picks the bake up without a reload', state(wall), sorted(fresh(wall))))
        L.aim_kitchen(wall)
        wall.evaluate("() => window.__twin.setTime('night')")
        RL.lights_mode(wall)
        check(is_baked(baked_row(wall, 'dev-k-lamp')), ('the Counter lamp now draws from its bake', baked_row(wall, 'dev-k-lamp')))
        check(writes(seen) == [], ('the wall uploads nothing', writes(seen)))
        L.no_errors(s)


def scenario_terraces_foundation_and_heavy_import_share_the_wall_bake():
    """Written for Claude to run: actual render detail differs; key/UV ownership must not."""
    import json
    import struct
    from services import twin_imports, twin_store

    s = L.serve()
    if s is None:
        return
    L.reset()
    clear_bakes()
    # A real indexed heavy import, using the existing objects-live fixture pattern.
    count = 300001
    positions = struct.pack('<9f', -1, 0, -1, 1, 0, -1, 0, 2, 1)
    indices = struct.pack('<3H', 0, 1, 2) * count
    doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
           'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
           'buffers': [{'uri': 'mesh.bin', 'byteLength': len(positions) + len(indices)}],
           'bufferViews': [{'buffer': 0, 'byteLength': len(positions)},
                           {'buffer': 0, 'byteOffset': len(positions), 'byteLength': len(indices)}],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
                          'min': [-1, 0, -1], 'max': [1, 2, 1]},
                         {'bufferView': 1, 'componentType': 5123, 'count': count * 3, 'type': 'SCALAR'}]}
    imported = twin_imports.create({'model.gltf': json.dumps(doc).encode(), 'mesh.bin': positions + indices},
                                   'Bake key car', 'car')
    twin_imports.rename(imported['id'], 'Bake key car', size=[2, 2, 2])

    def place(model):
        lot = model['site']['lot']
        x, y = lot[0]
        pad = [[x, y], [x + 12, y], [x + 12, y + 12], [x, y + 12]]
        model['site']['terraces'].append({'id': 'bake-key-pad', 'polygon': pad, 'height': -2, 'blend': 3,
                                          'edges': [{'edge': 'slope'} for _ in pad]})
        model['site']['hardscape'].append({'id': 'bake-key-patio', 'polygon': pad, 'material': 'concrete'})
        model['site']['furniture'].append({'id': 'bake-key-car', 'asset': imported['id'], 'kind': 'car',
                                           'at': [x + 6, y + 6], 'scale': 1, 'rotation': 0})
        H.building(model, L.POOL)['foundation'] = {'mode': 'auto', 'offset_ft': .5, 'thickness_ft': 1}
        return model

    try:
        twin_store.update_model(place, 'edit', note='bake identity terrain/import regression')
        with s.browser(launch_args=L.GPU_ARGS) as wall:
            seen = bake_requests(wall)
            wall_models = []
            wall.on('request', lambda request: wall_models.append(request.url)
                    if f"/{imported['id']}/model.gltf" in request.url else None)
            L.open_twin(wall, s, query='tier=low&test=1&panel=true&kiosk=true')
            wait_bake_hook(wall)
            wait_until(wall, lambda: bool(state(wall).get('key')), 120, 'wall computes its key')
            wall_key = state(wall)['key']
            check(fresh(wall) == set(), 'wall starts without any bake')
            context, desk = other_page(wall)
            try:
                desk_models = []
                desk.on('request', lambda request: desk_models.append(request.url)
                        if f"/{imported['id']}/model.gltf" in request.url else None)
                open_desk(desk, s)
                check(wait_baked(desk)['key'] == wall_key, 'authored terrain/import key is shared')
                check(desk_models and not wall_models, 'High fetches the model; Low keeps its stand-in')
                terrain_count = """() => {let n=0; window.__twin.groups.site.traverse(m=>{
                    if(m.userData.terrain) n+=m.geometry.attributes.position.count;}); return n;}"""
                check(desk.evaluate(terrain_count) > wall.evaluate(terrain_count), 'lawn render grids still differ by tier')
            finally:
                context.close()
            wait_until(wall, lambda: set(BAKED) <= fresh(wall), 120, 'wall picks up terrain/import bake')
            check(writes(seen) == [], 'kiosk wall uploads nothing')
            check(not state(wall)['baking'] and state(wall)['baked'] == [], 'kiosk wall never bakes')
            L.no_errors(s)
    finally:
        L.reset()
        twin_imports.delete(imported['id'])


def scenario_editor_never_bakes_and_says_when_lights_wait():
    """Ruling B15: the editor never bakes; its chip says when the lights wait to re-bake."""
    from services import twin_bakes, twin_store
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    behind = 'ab' * 20
    twin_bakes.save_manifest(behind, {'pages': 1, 'lights': {},
                                      'round': (twin_store.current_id() or 0) + 1000, 'complete': True})
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = bake_requests(page)
        H.signed_in(page)
        goto_retry(page, s.url('house/editor?tier=high&test=1'))
        page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=90000)
        page.wait_for_function('() => window.__twin && window.__twin.ready === true', timeout=90000)
        page.wait_for_timeout(8000)
        check(seen == [], ('the editor never reads or writes a bake', seen[:6]))
        check(page.evaluate('() => !window.__twin.bake'), 'the editor mounts no bake controller')
        check(page.get_by_role('button', name=BAKE_NOW, exact=True).count() == 0, f'the editor offers no {BAKE_NOW!r}')
        chip = page.locator('#editor-chip')
        check('Lights wait to re-bake' in chip.inner_text(), ('the chip says the lights wait', chip.inner_text()))
        L.no_errors(s)
    clear_bakes()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        open_desk(page, s)
        wait_baked(page)
    check(twin_bakes.status(twin_store.current_id()) == {'waiting': False},
          ('a desk bake of the current round clears the wait', twin_bakes.status(twin_store.current_id())))
    with s.browser(launch_args=L.GPU_ARGS) as page:
        H.signed_in(page)
        goto_retry(page, s.url('house/editor?tier=high&test=1'))
        page.wait_for_function('window.__editor && window.__editor.ready === true', timeout=90000)
        page.wait_for_timeout(2000)
        check('re-bake' not in page.locator('#editor-chip').inner_text(), ('nothing to say once baked', page.locator('#editor-chip').inner_text()))
        L.no_errors(s)


def scenario_day_ground_is_even_after_the_bake():
    """Only room lights bake: a bake landing must not mottle the open daylight lawn."""
    from statistics import pstdev
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    clear_bakes()
    # Hold uploads until the initial samples exist; then resume the real baker.
    with s.browser(launch_args=L.GPU_ARGS) as page:
        gate = {'hold': True}
        held = []
        def hold_upload(route):
            if gate['hold'] and route.request.method == 'POST' and route.request.url.endswith('.png'):
                held.append(route)
            else:
                route.continue_()
        page.route('**/api/house/bakes/**', hold_upload)
        open_desk(page, s)
        page.evaluate("() => { window.__twin.setTime('day'); window.__twin.setView('ext'); window.__twin.setCamera('front'); }")
        H.settle(page, 4)
        points = page.evaluate("""async () => {
            const THREE = await import('three'), v = window.__twin, ray = new THREE.Raycaster();
            v.scene.updateMatrixWorld(true); v.camera.updateMatrixWorld(true);
            const meshes = [];
            v.scene.traverse(o => { if (o.isMesh && !o.layers.isEnabled(31)) {
                let shown = true; for (let p = o; p; p = p.parent) shown &&= p.visible;
                if (shown) meshes.push(o);
            }});
            const points = [];
            for (let y = .12; y < .65; y += .045)
                for (let x = .12; x < .9; x += .045) {
                    ray.setFromCamera(new THREE.Vector2(x * 2 - 1, y * 2 - 1), v.camera);
                    const hit = ray.intersectObjects(meshes, false)[0];
                    if (hit?.object.material?.name === 'lawn') points.push([x, y]);
                }
            return points.length < 20 ? points : Array.from({length: 20}, (_, i) => points[Math.floor(i * (points.length - 1) / 19)]);
        }""")
        check(len(points) == 20, ('20 visible pixels hit open lawn', points))
        check(not fresh(page), 'before sample precedes publication of any room bake')
        before = [lum(pixel) for pixel in RL.screen_pixels(page, points)]
        spread_before = pstdev(before)
        gate['hold'] = False
        page.unroute('**/api/house/bakes/**', hold_upload)
        for route in held:
            route.continue_()
        wait_baked(page)
        H.settle(page, 4)
        after = [lum(pixel) for pixel in RL.screen_pixels(page, points)]
        spread_after = pstdev(after)
        check(spread_after <= spread_before * 1.25 + 2,
              ('ground stays even when room bakes land', spread_before, spread_after, before, after))
        L.no_errors(s)


def scenario_open_plan_light_crosses_the_invisible_wall():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    from services import twin_store

    def open_plan(before):
        model = copy.deepcopy(before)
        b = H.building(model, L.POOL)
        wall = next(w for w in b['walls'] if w['id'] == 'wall:9adea4c38eb2430697cf47d4ddee9d2a')
        wall.update(kind='separator', thickness=0, src={'person': True})
        b['openings'] = [o for o in b.get('openings', []) if o.get('wall') != wall['id']]
        return model

    twin_store.update_model(open_plan, 'edit', note='reach test: Kitchen and Hall share an invisible wall')
    clear_bakes()
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            desk_baked(s, page)
            L.aim_kitchen(page)
            page.evaluate("() => window.__twin.setTime('night')")
            RL.lights_mode(page)
            only_on(page, None)
            points = [(20, 13.2, .02), (21, 13.5, .02)]
            solid = [(27.2, 17.5, .02)]
            off = sample_at(page, points + solid)
            count = programs(page)
            only_on(page, 'light.ceiling_light', brightness=255)
            check(is_baked(baked_row(page, 'dev-k-ceiling')), 'the test uses baked light')
            on = sample_at(page, points + solid)
            rise = [lum(a) - lum(b) for a, b in zip(on, off)]
            check(mean(rise[:2]) > 3, ('the neighbouring floor past the invisible wall brightens', rise))
            check(abs(rise[2]) <= 3, ('the Changing floor behind its solid wall stays dark', rise))
            check(programs(page) == count, 'turning on the cross-room bake compiles nothing')
            L.no_errors(s)
    finally:
        L.reset()


def scenario_light_spills_through_a_window():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        desk_baked(s, page)
        L.aim_kitchen(page)
        # aim_kitchen frames the room only; widen to take in the ground outside the
        # west window (same view, centred between the room and the samples, higher up).
        page.evaluate("""([bid, key, x, y, h]) => {
            const v = window.__twin, b = v.plan.buildings.find(item => item.id === bid);
            const a = (b.rotation || 0) * Math.PI / 180;
            const wx = Math.cos(a) * x - Math.sin(a) * y + (b.position?.[0] || 0);
            const wy = Math.sin(a) * x + Math.cos(a) * y + (b.position?.[1] || 0);
            v.setView(key);
            v.aim([wx, wy - 0.5, h], [wx, wy, 0]);
        }""", [L.POOL, L.FLOOR, 2, 15, 75])
        H.settle(page, 3)
        page.evaluate("() => window.__twin.setTime('night')")
        RL.lights_mode(page)
        # Ceiling -> west window -> ground; the control ray meets solid wall
        # beyond the end of the glazing. Both points are outside the house.
        points = [(-3, 9.5, .02), (-3.5, 10.5, .02), (-3, 24, .02)]
        only_on(page, None)
        off = sample_at(page, points)
        only_on(page, 'light.ceiling_light', brightness=255)
        check(is_baked(baked_row(page, 'dev-k-ceiling')), 'the spill uses a fresh bake')
        on = sample_at(page, points)
        rise = [lum(a) - lum(b) for a, b in zip(on, off)]
        check(mean(rise[:2]) > 3, ('ground beyond the glazed window brightens at Night', rise))
        check(abs(rise[2]) <= 3, ('ground behind the solid wall stays dark', rise))
        L.no_errors(s)


SCENARIOS = [
    scenario_open_plan_light_crosses_the_invisible_wall,
    scenario_light_spills_through_a_window,
    scenario_bake_runs_on_idle_and_lands,
    scenario_baked_light_does_not_cross_a_wall,
    scenario_moving_a_light_rebakes_only_it,
    scenario_baked_kitchen_lights_like_the_real_one,
    scenario_toggle_is_exact,
    scenario_colour_follows_live,
    scenario_lit_room_glows_through_its_windows_from_outside,
    scenario_pi_tier_draws_baked_lights,
    scenario_no_bake_behaves_like_783,
    scenario_bake_pauses_while_dragging,
    scenario_bake_now_rebakes_everything,
    scenario_progress_words,
    scenario_two_tabs_bake_without_tearing,
    scenario_wall_opened_before_the_bake_picks_it_up,
    scenario_terraces_foundation_and_heavy_import_share_the_wall_bake,
    scenario_editor_never_bakes_and_says_when_lights_wait,
    scenario_day_ground_is_even_after_the_bake,
]


if __name__ == '__main__':
    wanted = sys.argv[1:]
    L.run([fn for fn in SCENARIOS if not wanted or fn.__name__ in wanted])
