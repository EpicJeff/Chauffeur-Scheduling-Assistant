"""Real lights in the 3D house's Lights mode, in real Chromium (brief
.superpowers/sdd/2026-11-10-house-real-lights/brief.md; the node half is
tests/test_twin_real_lights_js.py, which lists the module's assumed shape).

The house, the fake Home Assistant, the panel session and the camera are
tests/house_twin_live_harness.py's (read its docstring first): the Kitchen's
Ceiling light hangs at (9.3, 5.2) pool-house local feet, 10 ft up, and is off;
the Counter lamp (on, 128) and the Pendant (on, 255) are in the Kitchen; the
Changing light is on, rgb (0, 0, 255) at 153; the Hall light is off.
aim_kitchen() looks straight down on the pool house's ground floor from 50 ft.

What the page must give (beyond piece 3's):
- window.__twin.live.lights() -> [{device, at, rgb, intensity, real}] (a light
  that is off, unavailable or stale is absent or has intensity 0 and real false).
- In Lights mode a real THREE.PointLight (decay 2, a finite distance near the
  room's larger span) at each real light's marker, from a fixed pool made once
  (low tier: 4 PointLights); Lights keeps the current time look; `All` releases lamp ownership.
  Day/Night changes background, environment and exposure immediately in either mode.
- The light follows confirmed Home Assistant state only.

How the pixels are read: sample() hides every sprite (markers and room badges),
calls renderer3.render(scene, camera) itself and gl.readPixels in the same task,
then restores the sprites. That relies on readPixels after a render in the same
task (the drawing buffer is intact until the browser composites); it does not
need preserveDrawingBuffer, and DOM labels or controls never get in the way.
Floor points are pool-house local feet at the floor (z 0); every one is chosen
clear of where a glowing fixture 10 ft up projects from this camera.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_twin_real_lights_live.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

check = L.check
FAKE = L.FAKE
H = L.H
FT = L.FT

# Pool-house local feet. The Kitchen is x 0-31 for y 0-12.17 (and x 0-17.75 up to 17.33).
NEAR_CEILING = [(10.3, 5.9), (9.0, 6.4)]          # about a foot from under the Ceiling light
FAR_KITCHEN = [(29.5, 1.5), (29.0, 10.5)]         # the Kitchen's far end, about 20 ft away
HALL_FLOOR = [(19.5, 13.5), (21.0, 15.5)]
CHANGING_ANCHOR = 'anchor:live-changing'
NEAR_CHANGING = [(26.4, 16.2), (27.2, 15.8), (26.2, 17.6)]   # around the Changing room's middle (27.67, 17.08)
KITCHEN_REF = [(5.0, 3.0), (3.0, 9.0)]
OTHER_LIGHTS = ('light.counter_lamp', 'light.pendant', 'light.changing_light')
KITCHEN_SPAN = 31.0
CHANGING_SPAN = 22 - 12.17


# --- page reads ------------------------------------------------------------------------

def lights(page):
    rows = page.evaluate('() => typeof window.__twin.live.lights === "function" ? window.__twin.live.lights() : null')
    check(rows is not None, 'window.__twin.live.lights() is missing: it returns [{device, at, rgb, intensity, real}]')
    return rows


def light(page, device_id):
    rows = [r for r in lights(page) if r.get('device') == device_id]
    check(len(rows) <= 1, ('at most one live.lights() row per light', device_id, rows))
    return rows[0] if rows else None


def is_off(row):
    return row is None or (row.get('intensity') == 0 and row.get('real') is False)


def is_on(row, real=True):
    return row is not None and row.get('intensity', 0) > 0 and (row.get('real') is True if real else True)


POOL_JS = """(FT) => {
    const v = window.__twin, out = [];
    const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
    v.scene.traverse(o => {
        if (!o.isPointLight) return;
        const p = o.getWorldPosition(o.position.clone());
        out.push({id: o.uuid, intensity: o.intensity, shown: shown(o), decay: o.decay, distance: o.distance,
                  shadow: !!o.castShadow, at: [p.x / FT, -p.z / FT, p.y / FT], color: [o.color.r, o.color.g, o.color.b]});
    });
    return out;
}"""


def pool(page):
    return page.evaluate(POOL_JS, FT)


def lit_pool(page):
    return [p for p in pool(page) if p['shown'] and p['intensity'] > 0]


MARKER_SPOT_JS = """([id, FT]) => {
    let out = null;
    window.__twin.scene.traverse(o => {
        if (o.isSprite && o.userData && o.userData.deviceId === id) {
            const p = o.getWorldPosition(o.position.clone()); out = [p.x / FT, -p.z / FT, p.y / FT];
        }
    });
    return out;
}"""


LAMP_HEIGHT = 4.5   # Ruling R1: a light on the floor is a floor lamp, its bulb 4.5 ft up


def lamp_at(page, device_id, floor_lamp=False):
    """The lit pool light at a marker: x, y on it, height the marker's or up to a foot under.

    A floor lamp (floor_lamp=True: the light stands on the floor, its marker at the
    floor) has its light LAMP_HEIGHT above the floor instead."""
    spot = page.evaluate(MARKER_SPOT_JS, [device_id, FT])
    check(spot, ('the marker sprite of', device_id))

    def height(z):
        return abs(z - (spot[2] + LAMP_HEIGHT)) < .05 if floor_lamp else spot[2] - 1.05 <= z <= spot[2] + .05
    hits = [p for p in lit_pool(page) if abs(p['at'][0] - spot[0]) < .2 and abs(p['at'][1] - spot[1]) < .2
            and height(p['at'][2])]
    return hits[0] if hits else None


LOOK_JS = """() => {
    const v = window.__twin, s = v.scene, out = {lights: []};
    s.traverse(o => {
        // The time look is sun, sky and ambient. Lamps (the live pool's PointLights and the
        // decorative RectAreaLights Lights mode switches off) are not part of it.
        if (!o.isLight || o.isPointLight || o.isRectAreaLight) return;
        out.lights.push({type: o.type, id: o.uuid, visible: o.visible, intensity: Math.round(o.intensity * 1e4) / 1e4,
                         color: o.color.getHexString(), ground: o.groundColor ? o.groundColor.getHexString() : null});
    });
    out.lights.sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    const bg = s.background;
    out.background = bg && bg.isColor ? bg.getHexString() : bg ? 'texture:' + bg.uuid : null;
    out.environment = s.environment ? s.environment.uuid : null;
    out.environmentIntensity = s.environmentIntensity;
    out.exposure = v.renderer3.toneMappingExposure;
    out.toneMapping = v.renderer3.toneMapping;
    out.fog = s.fog ? JSON.stringify(s.fog.toJSON ? s.fog.toJSON() : [s.fog.color.getHexString(), s.fog.near, s.fog.far, s.fog.density]) : null;
    out.time = v.state.time;
    return out;
}"""


def look(page):
    return page.evaluate(LOOK_JS)


def sky(state):
    """How much daylight the scene carries: the visible sun, hemisphere and ambient intensities."""
    return sum(l['intensity'] for l in state['lights']
               if l['visible'] and l['type'] in ('DirectionalLight', 'HemisphereLight', 'AmbientLight'))


def hex_lum(value):
    if not value or not isinstance(value, str) or value.startswith('texture:'):
        return None
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


SAMPLE_JS = """([points, FT, r]) => {
    const v = window.__twin, renderer = v.renderer3, gl = renderer.getContext(), canvas = renderer.domElement;
    const hidden = [];
    v.scene.traverse(o => { if (o.isSprite && o.visible) { hidden.push(o); o.visible = false; } });
    try {
        v.camera.updateMatrixWorld(true);
        renderer.render(v.scene, v.camera);
        const w = 2 * r + 1, buf = new Uint8Array(w * w * 4);
        return points.map(at => {
            const p = v.camera.position.clone().set(at[0] * FT, at[2] * FT, -at[1] * FT).project(v.camera);
            const x = Math.round((p.x + 1) / 2 * canvas.width), y = Math.round((p.y + 1) / 2 * canvas.height);
            gl.readPixels(x - r, y - r, w, w, gl.RGBA, gl.UNSIGNED_BYTE, buf);
            const sum = [0, 0, 0];
            for (let i = 0; i < w * w; i++) for (let c = 0; c < 3; c++) sum[c] += buf[i * 4 + c];
            return {rgb: sum.map(s => s / (w * w)), inside: Math.abs(p.x) < .98 && Math.abs(p.y) < .98 && p.z < 1};
        });
    } finally { for (const o of hidden) o.visible = true; }
}"""


SCREEN_PIXELS_JS = """points => {
    const v = window.__twin, renderer = v.renderer3, gl = renderer.getContext(), canvas = renderer.domElement;
    const hidden = [];
    v.scene.traverse(o => { if (o.isSprite && o.visible) { hidden.push(o); o.visible = false; } });
    try {
        renderer.render(v.scene, v.camera);
        return points.map(([x, y]) => {
            const pixel = new Uint8Array(4);
            gl.readPixels(Math.min(canvas.width - 1, Math.floor(x * canvas.width)),
                          Math.min(canvas.height - 1, Math.floor(y * canvas.height)), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
            return Array.from(pixel.slice(0, 3));
        });
    } finally { for (const object of hidden) object.visible = true; }
}"""


def screen_pixels(page, points):
    """Canvas RGB at normalized bottom-left screen coordinates, without markers or HTML overlays."""
    return page.evaluate(SCREEN_PIXELS_JS, points)


def sample(page, local_points, r=3):
    """Mean RGB (0-255, as shown) around each pool-house local floor point; sprites hidden."""
    lots = [L.lot_of_local(page, x, y) + [0.0] for x, y in local_points]
    out = page.evaluate(SAMPLE_JS, [lots, FT, r])
    for point, row in zip(local_points, out):
        check(row['inside'], ('the floor sample is on screen', point))
    return [row['rgb'] for row in out]


def lum(p):
    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]


def mean(values):
    values = list(values)
    return sum(values) / len(values)


def calm(page):
    """Let any fade between looks finish, then a few frames."""
    page.wait_for_timeout(1200)
    H.settle(page, 4)


def mode_button(page, name):
    button = page.get_by_role('button', name=name, exact=True).locator('visible=true')
    check(button.count() == 1, ('one visible mode button', name, button.count()))
    return button.first


def lights_mode(page):
    mode_button(page, 'Lights').click()
    calm(page)


def all_mode(page):
    mode_button(page, 'All').click()
    calm(page)


def set_light(entity_id, state, **attrs):
    row = FAKE.states[entity_id]
    row['state'] = state
    row['attributes'].update(attrs)


def others_off(page):
    for eid in OTHER_LIGHTS:
        set_light(eid, 'off')
    L.refresh(page)


def changing_on_ceiling():
    """The Changing light hung from the Changing room's ceiling (an anchor, like the Kitchen's)."""
    from services import twin_store

    def mutate(before):
        model = copy.deepcopy(before)
        b = H.building(model, L.POOL)
        b['devices'] = [d for d in b.get('devices') or [] if d.get('device') != 'dev-changing-light']
        b['anchors'] = [a for a in b.get('anchors') or [] if a['id'] != CHANGING_ANCHOR] + [
            {'id': CHANGING_ANCHOR, 'kind': 'light', 'host': {'ceiling': L.CHANGING, 'u': 0.5, 'v': 0.5},
             'offset': 0, 'device': 'dev-changing-light'}]
        return model
    twin_store.update_model(mutate, 'edit', note='real lights: the Changing light on its ceiling')


# --- scenarios ------------------------------------------------------------------------

def scenario_lit_kitchen_brightens_near_the_fixture():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        L.aim_kitchen(page)
        page.evaluate("() => window.__twin.setTime('night')")
        others_off(page)
        lights_mode(page)
        check(is_off(light(page, 'dev-k-ceiling')), ('the Ceiling light is off', lights(page)))
        check(lit_pool(page) == [], ('every light off: no pool light is lit', lit_pool(page)))
        off_near, off_far = sample(page, NEAR_CEILING), sample(page, FAR_KITCHEN)

        set_light('light.ceiling_light', 'on', brightness=255)
        L.refresh(page)
        calm(page)
        row = light(page, 'dev-k-ceiling')
        check(is_on(row), ('the Ceiling light is a real light', row))
        check(row['at'] == L.marker(page, 'dev-k-ceiling')['at'], ('at is the marker\'s at', row, L.marker(page, 'dev-k-ceiling')))
        check(abs(row['intensity'] - 1) < .01 and list(row['rgb']) == [255, 241, 201], ('full warm white', row))
        lamp = lamp_at(page, 'dev-k-ceiling')
        check(lamp, ('a lit PointLight hangs at the Ceiling light\'s marker', lit_pool(page),
                     page.evaluate(MARKER_SPOT_JS, ['dev-k-ceiling', FT])))
        check(lamp['decay'] == 2, ('physically based decay', lamp))
        check(0 < lamp['distance'] and .5 * KITCHEN_SPAN * FT <= lamp['distance'] <= 2.5 * KITCHEN_SPAN * FT,
              ('a finite range about the Kitchen\'s larger span', lamp['distance']))
        on_near, on_far = sample(page, NEAR_CEILING), sample(page, FAR_KITCHEN)

        near_rise = mean(lum(a) - lum(b) for a, b in zip(on_near, off_near))
        far_rise = mean(lum(a) - lum(b) for a, b in zip(on_far, off_far))
        detail = {'near_rise': round(near_rise, 1), 'far_rise': round(far_rise, 1),
                  'on_near': [round(lum(p), 1) for p in on_near], 'on_far': [round(lum(p), 1) for p in on_far],
                  'off_near': [round(lum(p), 1) for p in off_near], 'off_far': [round(lum(p), 1) for p in off_far]}
        check(near_rise > 25, ('the floor under the light brightens clearly', detail))
        check(near_rise > far_rise + 15, ('light falls off with distance, not a flat sheet', detail))
        check(mean(lum(p) for p in on_near) > mean(lum(p) for p in on_far) + 10,
              ('under the light is brighter than the far corner of the same room', detail))
        L.no_errors(s)


def scenario_colour_light_tints_the_room():
    s = L.serve()
    if s is None:
        return
    L.reset()
    changing_on_ceiling()
    body = L.facts()
    spot = next(m for m in body['markers'] if m['device_id'] == 'dev-changing-light')
    check(spot['at'][2] >= 8, ('the Changing light hangs from the ceiling', spot))
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            L.open_twin(page, s)
            L.aim_kitchen(page)
            page.evaluate("() => window.__twin.setTime('night')")
            others_off(page)
            lights_mode(page)
            off_near, off_ref = sample(page, NEAR_CHANGING), sample(page, KITCHEN_REF)

            set_light('light.changing_light', 'on', brightness=153, rgb_color=[0, 0, 255])
            L.refresh(page)
            calm(page)
            row = light(page, 'dev-changing-light')
            check(is_on(row) and list(row['rgb']) == [0, 0, 255] and abs(row['intensity'] - .6) < .01,
                  ('a real blue light at 60 percent', row))
            lamp = lamp_at(page, 'dev-changing-light')
            check(lamp, ('a lit PointLight at the Changing light\'s marker', lit_pool(page)))
            check(lamp['color'][2] > .9 and lamp['color'][0] < .05 and lamp['color'][1] < .05, ('the PointLight is blue', lamp))
            check(.5 * CHANGING_SPAN * FT <= lamp['distance'] <= 2.5 * CHANGING_SPAN * FT,
                  ('the range is about the Changing room\'s larger span', lamp['distance']))
            on_near, on_ref = sample(page, NEAR_CHANGING), sample(page, KITCHEN_REF)

            def blue(p):
                return p[2] - p[0]
            tint = mean(blue(a) - blue(b) for a, b in zip(on_near, off_near))
            ref = mean(blue(a) - blue(b) for a, b in zip(on_ref, off_ref))
            detail = {'tint': round(tint, 1), 'ref': round(ref, 1), 'on_near': on_near, 'off_near': off_near}
            check(tint > 15, ('the Changing room turns blue near the light', detail))
            check(abs(ref) < 6, ('the Kitchen across the house does not', detail))
            L.no_errors(s)
    finally:
        L.reset()


def scenario_lights_mode_keeps_the_day():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        others_off(page)
        page.evaluate("() => { window.__twin.setTime('day'); window.__twin.levels.go({level:'house'},{immediate:true}); }")
        calm(page)
        day = look(page)
        grid = [[x / 10, y / 10] for x in range(2, 9) for y in range(2, 9)]
        before = screen_pixels(page, grid)
        before_mean = mean(map(lum, before))
        background = screen_pixels(page, [[.98, .98]])[0]
        lights_mode(page)
        during = screen_pixels(page, grid)
        during_mean = mean(map(lum, during))
        check(before_mean > 0, ('day grid is illuminated', before_mean))
        check(abs(during_mean - before_mean) <= before_mean * .06,
              ('Lights preserves the day within 6 percent', before_mean, during_mean))
        check(screen_pixels(page, [[.98, .98]])[0] == background, 'the sky/background pixel is unchanged')
        check(look(page) == day, ('background, environment, sun, ambient and exposure stay the same', day, look(page)))
        check(lit_pool(page) == [], 'all HA lamps are off')
        lamps = room_lamps(page)
        check(all(l['intensity'] == 0 for l in lamps['lamps']), ('decorative room lamps are off', lamps))
        check(all(value == 0 for value in lamps['fixtures']), ('decorative fixture emissive is off', lamps))

        page.locator('#twin-preview-gear').click()
        page.locator('#twin-time-preview [data-time="night"]').click()
        page.get_by_role('button', name='Close settings', exact=True).click()
        calm(page)
        night_mean = mean(map(lum, screen_pixels(page, grid)))
        check(night_mean < during_mean * .70, ('Night changes the look at once in Lights mode', during_mean, night_mean))
        lamps = room_lamps(page)
        check(all(l['intensity'] == 0 for l in lamps['lamps']), ('Night in Lights keeps decorative lamps off', lamps))
        check(all(value == 0 for value in lamps['fixtures']), ('Night in Lights keeps fixture emissive off', lamps))
        night = look(page)
        check(night['time'] == 'night', night)
        all_mode(page)
        check(look(page) == night, ('All keeps the current Night time look', night, look(page)))
        check_night_lamps(page, 'All restores decorative night lamps')
        page.evaluate("() => window.__twin.setTime('day')")
        calm(page)
        for _ in range(2):
            lights_mode(page)
            all_mode(page)
        check(look(page) == day, ('repeated Lights/All keeps Day', day, look(page)))
        L.no_errors(s)


ROOM_LAMPS_JS = """() => {
    const v = window.__twin, night = v.state.time === 'night', fixtures = [];
    const lamps = (v.roomLights || []).map(l => ({visible: l.visible, intensity: l.intensity, level: l.userData.level,
        own: l.userData.intensity, levelVisible: !!v.groups.levels[l.userData.level]?.visible, inScene: !!l.parent && !!l.parent.parent}));
    v.scene.traverse(o => { for (const m of o.material ? [].concat(o.material) : []) if (m.name === 'fixture') fixtures.push(m.emissiveIntensity); });
    return {night, lamps, fixtures};
}"""


def room_lamps(page):
    return page.evaluate(ROOM_LAMPS_JS)


def check_night_lamps(page, why):
    """The house's own night lamps as the view's rule has them: visible on a shown level at night, at their own
    intensity, and the fixtures glowing."""
    state = room_lamps(page)
    check(state['night'], (why, 'still night', state['night']))
    check(state['lamps'], (why, 'the house has night lamps to check', state))
    wrong = [l for l in state['lamps'] if l['visible'] != l['levelVisible']]
    check(not wrong, (why, 'a night lamp is visible exactly when its level is shown', wrong))
    dark = [l for l in state['lamps'] if l['visible'] and not (l['intensity'] > 0 and l['intensity'] == l['own'])]
    check(not dark, (why, 'a shown night lamp is at its own intensity', dark))
    check(state['fixtures'] and all(value == 2 for value in state['fixtures']),
          (why, 'every fixture glows at night', sorted(set(state['fixtures']))))


def scenario_all_after_a_floor_change_in_lights_follows_the_floor():
    """At night, Lights in Ext, the ground floor shown, then All: the upper floors' night lamps stay off."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        page.evaluate("() => { window.__twin.levels.go({level:'house'},{immediate:true}); window.__twin.setTime('night'); }")
        calm(page)
        check_night_lamps(page, 'night in Ext before Lights')
        lights_mode(page)
        # The first floor view that hides some of the house's night lamps.
        # Floors fade out over ~250 ms since v2.499.801 (zoom level of detail), so wait for
        # each view's fade before reading visibility.
        target = page.evaluate("""async () => {
            const v = window.__twin, levels = v.groups.levels, keys = v.levelKeys();
            const lamps = (v.roomLights || []).map(l => l.userData.level);
            for (const key of keys) {
                {const b=v.plan.buildings.find(b=>b.levels.some(l=>b.id+':'+l.id===key));const f=b.levels.find(l=>b.id+':'+l.id===key);v.levels.go({building:b.id,floor:f.id},{immediate:true});}
                await new Promise(resolve => setTimeout(resolve, 600));
                if (lamps.some(level => !levels[level]?.visible)) return key;
            }
            return null;
        }""")
        if not target:
            # Since v2.499.801 a floor view keeps other buildings visible unless they are in the
            # way (peel), so in a house whose lamps all sit on ground floors no floor view hides
            # one. Nothing here to follow; lamp visibility per level is covered by
            # test_twin_real_lights_js.
            print('    (no floor view hides a night lamp in this house; scenario not applicable)')
            return
        calm(page)
        all_mode(page)
        check_night_lamps(page, 'All after a floor change in Lights')
        page.evaluate("() => window.__twin.levels.go({level:'house'},{immediate:true})")
        calm(page)
        check_night_lamps(page, 'Ext again after All')
        L.no_errors(s)


LATE_SKY_JS = """async () => {
    const THREE = await import('three'), v = window.__twin;
    if (typeof v.applySky !== 'function') return 'window.__twin.applySky is missing (a ?test=1 hook: the late sky path)';
    const data = new Float32Array([0.6, 0.7, 0.9, 1, 0.5, 0.6, 0.8, 1]);
    const texture = new THREE.DataTexture(data, 2, 1, THREE.RGBAFormat, THREE.FloatType);
    texture.mapping = THREE.EquirectangularReflectionMapping; texture.needsUpdate = true;
    v.applySky(texture);
    return null;
}"""


def scenario_a_sky_arriving_in_lights_is_the_sky_after_all():
    """The sky can land late (loadSky's onLate). Arriving during Lights mode, it is the day's sky after All."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        page.evaluate("() => window.__twin.setTime('day')")
        calm(page)
        before = look(page)['environment']
        lights_mode(page)
        check(look(page)['environment'] == before, ('Lights keeps the current day environment', look(page)))
        missing = page.evaluate(LATE_SKY_JS)
        check(missing is None, missing)
        calm(page)
        check(look(page)['environment'] is not None and look(page)['environment'] != before, ('the late day sky appears immediately in Lights mode', look(page)))
        all_mode(page)
        after = look(page)
        page.evaluate('() => window.__twin.setTime(window.__twin.state.time)')
        calm(page)
        current = look(page)
        check(after['environment'] is not None and after['environment'] != before,
              ('All lights the day with the sky that arrived, not the one it found', before, after['environment']))
        check(after == current, ('All is the day as the view draws it now', after, current))
        L.no_errors(s)


def scenario_a_rebuild_in_lights_keeps_the_night_lamps_after_all():
    """A house rebuilt while in Lights mode at night gets its night lamps and glowing fixtures back on All."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        page.evaluate("() => { window.__twin.levels.go({level:'house'},{immediate:true}); window.__twin.setTime('night'); }")
        calm(page)
        check_night_lamps(page, 'night before Lights')
        night = look(page)
        lights_mode(page)
        page.evaluate('async () => { await window.__twin.rebuild(window.__twin.plan, {preserveYard: true}); }')
        calm(page)
        state = room_lamps(page)
        check(all(l['intensity'] == 0 for l in state['lamps']), ('the rebuilt night lamps stay off in Lights', state))
        all_mode(page)
        check_night_lamps(page, 'All after a rebuild in Lights')
        after = look(page)
        check({k: after[k] for k in ('background', 'environment', 'exposure', 'time')}
              == {k: night[k] for k in ('background', 'environment', 'exposure', 'time')},
              ('All after a rebuild is the night it found', night, after))
        L.no_errors(s)


PROGRAM_KEYS_JS = """() => window.__twin.renderer3.info.programs.map(p => p.id + ' ' + p.cacheKey.split(',')[0])"""


def scenario_first_lights_entry_compiles_no_lit_shader():
    """The live layer compiles Lights mode's programs at mount (renderer3.compileAsync with the pool shown), so
    the first tap on Lights compiles no lit shader on the panel; at most a plain unlit one."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        L.aim_kitchen(page)
        calm(page)
        before = set(page.evaluate(PROGRAM_KEYS_JS))
        lights_mode(page)
        check(lit_pool(page), ('lights are on in Lights mode', lights(page)))
        new = sorted(set(page.evaluate(PROGRAM_KEYS_JS)) - before)
        lit = [key for key in new if key.split(' ', 1)[1] not in ('basic', 'sprite')]
        check(not lit, ('the first Lights entry compiles no lit shader: they were warmed at mount', new))
        L.no_errors(s)


HOLD_JS = """() => {
    const original = window.chfControlFetch;
    window.__heldControl = {original, held: false};
    let release; const gate = new Promise(resolve => { release = resolve; });
    window.__releaseControl = () => release();
    window.chfControlFetch = async (...args) => {
        const response = await original(...args);
        window.__heldControl.held = true;
        await gate;
        return response;
    };
}"""


def scenario_tap_off_turns_the_light_off_after_confirmed_state():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            L.open_twin(page, s)
            L.aim_kitchen(page)
            page.evaluate("() => window.__twin.setTime('night')")
            lights_mode(page)
            row = light(page, 'dev-k-lamp')
            check(is_on(row) and abs(row['intensity'] - 128 / 255) < .01, ('the Counter lamp is a real light at 50 percent', row))
            check(lamp_at(page, 'dev-k-lamp', floor_lamp=True), ('a lit PointLight at the Counter lamp', lit_pool(page)))
            count = len(pool(page))
            H.settle(page, 6)
            programs = page.evaluate('() => window.__twin.renderer3.info.programs.length')

            # Home Assistant takes the call but the lamp stays on; the response is held.
            FAKE.frozen.add('light.counter_lamp')
            page.evaluate(HOLD_JS)
            start = len(FAKE.calls)
            L.tap_marker(page, 'dev-k-lamp')
            check(L.wait_for(page, lambda: page.evaluate('() => window.__heldControl.held')),
                  'the tap reached Home Assistant and its answer is held')
            check(FAKE.calls[start:] and FAKE.calls[-1][:2] == ('light', 'toggle'), FAKE.calls[start:])
            check(is_on(light(page, 'dev-k-lamp')), ('no optimistic flip: still on while the answer is out', light(page, 'dev-k-lamp')))
            check(lamp_at(page, 'dev-k-lamp', floor_lamp=True), 'the PointLight stays lit while the answer is out')
            page.evaluate('() => window.__releaseControl()')
            page.wait_for_timeout(800)
            L.refresh(page)
            check(is_on(light(page, 'dev-k-lamp')), ('Home Assistant still says on: the light stays on', light(page, 'dev-k-lamp')))
            page.evaluate('() => { window.chfControlFetch = window.__heldControl.original; }')

            # Home Assistant turns it off: the light goes out once the state says so.
            FAKE.frozen.clear()
            L.tap_marker(page, 'dev-k-lamp')
            check(L.wait_for(page, lambda: is_off(light(page, 'dev-k-lamp')), 15),
                  ('off once Home Assistant confirms', light(page, 'dev-k-lamp')))
            check(FAKE.states['light.counter_lamp']['state'] == 'off', FAKE.states['light.counter_lamp'])
            calm(page)
            check(lamp_at(page, 'dev-k-lamp', floor_lamp=True) is None, ('no lit PointLight at the lamp', lit_pool(page)))
            check(len(pool(page)) == count, ('the pool keeps its size', count, len(pool(page))))
            check(page.evaluate('() => window.__twin.renderer3.info.programs.length') == programs,
                  ('turning a light off compiles no shader', programs,
                   page.evaluate('() => window.__twin.renderer3.info.programs.length')))
            L.no_errors(s)
    finally:
        FAKE.frozen.clear()


def scenario_ha_unreachable_draws_lights_off():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            L.open_twin(page, s)
            L.aim_kitchen(page)
            page.evaluate("() => window.__twin.setTime('night')")
            day = look(page)
            lights_mode(page)
            for did in ('dev-k-lamp', 'dev-k-pendant', 'dev-changing-light'):
                check(is_on(light(page, did)), ('on before the outage', did, light(page, did)))
            check(len(lit_pool(page)) == 3, ('three lights, three lit PointLights', lit_pool(page)))

            def dark(why):
                rows = lights(page)
                check(all(is_off(r) for r in rows), (why, 'every light draws off', rows))
                check(lit_pool(page) == [], (why, 'no PointLight lit', lit_pool(page)))
                check(look(page) == day, (why, 'the scene keeps its current time look', look(page)))
                rows = {m['device_id']: m for m in L.markers(page)}
                check(all(m['stale'] is True and m['dim'] is True for m in rows.values()), (why, 'markers stale and dimmed'))
                check(rows['dev-k-lamp']['look'] == 'on', (why, 'the marker keeps its last state', rows['dev-k-lamp']))
                check(L.drawn_dim(L.sprite(page, 'dev-k-lamp')), (why, 'the lamp marker is drawn dimmed'))

            FAKE.available = False
            L.refresh(page)
            calm(page)
            dark('Home Assistant away')

            FAKE.available = True
            L.refresh(page)
            calm(page)
            check(is_on(light(page, 'dev-k-lamp')) and len(lit_pool(page)) == 3, ('back: the lights come on', lights(page)))

            page.route('**/api/ha/card/states*', lambda route: route.abort())
            L.refresh(page)
            calm(page)
            dark('the poll fails')
            page.unroute('**/api/ha/card/states*')
            L.refresh(page)
            calm(page)
            check(is_on(light(page, 'dev-k-lamp')), ('fresh again', lights(page)))
            L.no_errors(s)
    finally:
        FAKE.available = True


def scenario_wall_panel_lights_mode():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s, query='tier=low&test=1&panel=true&kiosk=true')
        L.aim_kitchen(page)
        page.evaluate("() => window.__twin.setTime('night')")
        day = look(page)
        count = len(pool(page))
        check(count == 4, ('the low tier holds a pool of four PointLights from the start', count))
        mode_button(page, 'Lights').click()   # one tap
        calm(page)
        check(mode_button(page, 'Lights').get_attribute('aria-pressed') == 'true', 'Lights reads pressed')
        for did in ('dev-k-lamp', 'dev-k-pendant', 'dev-changing-light'):
            check(is_on(light(page, did)), ('on the wall, the light is real', did, lights_rows(page)))
        check(len(lit_pool(page)) == 3, ('three lit PointLights', lit_pool(page)))
        check(len(pool(page)) == count, ('the pool did not grow', count, len(pool(page))))
        check(look(page) == day, ('Lights keeps the wall time look', look(page)))
        mode_button(page, 'All').click()   # one tap back
        calm(page)
        check(look(page) == day, ('All restores the wall\'s look', day, look(page)))
        check(lit_pool(page) == [], ('All: no pool light lit', lit_pool(page)))
        L.no_errors(s)


def lights_rows(page):
    return page.evaluate('() => window.__twin.live.lights ? window.__twin.live.lights() : null')


SCENARIOS = [
    scenario_lit_kitchen_brightens_near_the_fixture,
    scenario_colour_light_tints_the_room,
    scenario_lights_mode_keeps_the_day,
    scenario_tap_off_turns_the_light_off_after_confirmed_state,
    scenario_ha_unreachable_draws_lights_off,
    scenario_wall_panel_lights_mode,
    scenario_all_after_a_floor_change_in_lights_follows_the_floor,
    scenario_a_sky_arriving_in_lights_is_the_sky_after_all,
    scenario_a_rebuild_in_lights_keeps_the_night_lamps_after_all,
    scenario_first_lights_entry_compiles_no_lit_shader,
]


if __name__ == '__main__':
    L.run(SCENARIOS)
