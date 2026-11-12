"""The ring of light controls at a light in the 3D house, in real Chromium (Task 3 of
docs/superpowers/plans/2026-11-11-twin-device-controls.md; brief
.superpowers/sdd/2026-11-11-twin-device-controls/task-3-brief.md; spec
docs/superpowers/specs/2026-11-11-twin-device-controls-design.md section 4, exit
steps 1 and 2, and the user's answers in section 5). Task 4 adds its scenarios here.

The house, the fake Home Assistant (it records every service call it is sent), the
panel session and the camera are tests/house_twin_live_harness.py's: read its
docstring. This file also teaches the fake the light's colour services (rgb_color,
hs_color, color_temp_kelvin, effect), the way Home Assistant answers them, and
honours the harness's `frozen` set (a light that ignores what it is sent).

The kitchen light is the Ceiling light (light.ceiling_light, dev-k-ceiling, on the
Kitchen's ceiling anchor). For the colour scenarios it is made a colour light:
on, brightness 255, supported_color_modes color_temp and hs, 3000 K.

The hooks the page gives under ?test=1 (beside the harness's):
- window.__twin.live.ring() -> null, or {device_id, x, y}: the open ring's device
  and its anchor in client pixels (the marker's projected centre).
- The ring element carries data-ring and data-device-id; its parts carry
  data-ring-part: center (role=switch), brightness (role=slider, percent),
  temperature (role=slider, kelvin), swatches (buttons with aria-label colour
  names, one Blue), wheel, effects. Arcs follow the WAI-ARIA slider keys.
- window.__twin.live.lights() rows {device, rgb, intensity, real, baked} (shipped
  with real lights): the light in the scene, real-time or baked.

What the scenarios prove:
- a tap on the Ceiling light toggles it through api/ha/card/service and opens no
  ring; the marker shows the confirmed state within a second; a light that
  ignores the call keeps its old look (never an optimistic flip); a tap on the
  Ceiling fan toggles the fan (it no longer opens the room);
- a press held 500 ms opens the ring at the light and sends nothing; the
  brightness arc sends light.turn_on {brightness_pct: 40} once, and blue sends
  light.turn_on with rgb_color [0, 0, 255] or hs_color [240, 100]; the marker, the
  ring and the light drawn in the scene (Lights mode) follow only the confirmed
  state: with the light frozen nothing they show moves;
- at the wall panel (?panel=true&kiosk=true, a touch screen) a touch hold opens the
  ring and sends nothing (when the finger lifts Chromium sends a click to the ring's
  centre, now under it; that click must not toggle), its targets are at least 44 px, a touch tap picks blue, a touch drag on
  the brightness arc sends one call, and a touch on the scene away from the ring
  closes it.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_twin_controls_live.py
"""
import colorsys
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

check = L.check
FAKE = L.FAKE
CEILING, CEILING_ID = 'light.ceiling_light', 'dev-k-ceiling'
FAN, FAN_ID = 'fan.kitchen_fan', 'dev-k-fan'
BLUE_HS = (240, 100)


def _teach_colour():
    """The fake answers a light's colour services the way Home Assistant does."""
    from services import ha_api
    inner = ha_api.call_service

    def call(domain, service, data=None, **kw):
        data = copy.deepcopy(data or {})
        out = inner(domain, service, data, **kw)
        ids = data.get('entity_id')
        for eid in ([ids] if isinstance(ids, str) else list(ids or [])):
            row = FAKE.states.get(eid)
            if row is None or eid in FAKE.frozen or domain != 'light' or service != 'turn_on':
                continue
            attrs = row['attributes']
            if data.get('rgb_color') is not None:
                rgb = [int(v) for v in data['rgb_color']]
                h, s, _v = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))
                attrs.update(rgb_color=rgb, hs_color=[round(h * 360, 3), round(s * 100, 3)], color_mode='hs')
                attrs.pop('color_temp_kelvin', None)
            if data.get('hs_color') is not None:
                h, s = (float(v) for v in data['hs_color'])
                rgb = [round(v * 255) for v in colorsys.hsv_to_rgb(h / 360, s / 100, 1)]
                attrs.update(hs_color=[h, s], rgb_color=rgb, color_mode='hs')
                attrs.pop('color_temp_kelvin', None)
            if data.get('color_temp_kelvin') is not None:
                attrs.update(color_temp_kelvin=int(data['color_temp_kelvin']), color_mode='color_temp')
                attrs.pop('rgb_color', None)
                attrs.pop('hs_color', None)
            if data.get('effect') is not None:
                attrs['effect'] = data['effect']
        return out
    ha_api.call_service = call


_teach_colour()


def _colour_light():
    """The Ceiling light as a colour light, on at full brightness and 3000 K."""
    row = FAKE.states[CEILING]
    row['state'] = 'on'
    row['attributes'].update(brightness=255, supported_color_modes=['color_temp', 'hs'], color_mode='color_temp',
                             color_temp_kelvin=3000, min_color_temp_kelvin=2000, max_color_temp_kelvin=6500,
                             supported_features=44)


def _open(page, s, query='tier=low&test=1&panel=true', ceiling='off'):
    """The harness's open_twin, waiting for the Ceiling light's own starting look."""
    L.open_twin(page, s, query=query, live=False)
    try:
        page.wait_for_function('() => !!(window.__twin && window.__twin.live)', timeout=20000)
    except Exception:
        raise AssertionError('window.__twin.live is missing: the live layer did not mount')
    check(L.wait_for(page, lambda: {m.get('device_id') for m in L.markers(page)} >= set(L.NAMES)
                     and L.marker(page, CEILING_ID).get('look') == ceiling, 20),
          ('every device has a marker drawn with its state', [(m.get('device_id'), m.get('look')) for m in L.markers(page)]))


def _ring_hook(page):
    check(page.evaluate('() => typeof window.__twin.live.ring === "function"'),
          'window.__twin.live.ring() is missing: the live layer reports the open ring (null when none)')


def _ring(page):
    return page.evaluate('() => window.__twin.live.ring()')


def _posts(seen, start=0):
    return [(p.get('domain'), p.get('service'), p.get('data')) for p in L.service_posts(seen[start:])]


def _look_within(page, device_id, look, seconds):
    """The marker shows `look` within `seconds` of now (in-page, no polling gap)."""
    try:
        page.wait_for_function('([id, look]) => window.__twin.live.markers().find(m => m.device_id === id).look === look',
                               arg=[device_id, look], timeout=int(seconds * 1000))
        return True
    except Exception:
        return False


def _light(page, device_id=CEILING_ID):
    rows = [r for r in page.evaluate('() => window.__twin.live.lights()') if r.get('device') == device_id]
    check(len(rows) == 1, ('live.lights() has one row for the light', device_id, rows))
    return rows[0]


def _state(page, entity_id=CEILING):
    return page.evaluate('(id) => window.__twin.live.states()[id]', entity_id)


def _hold(page, device_id, ms=700):
    sx, sy = L.sprite(page, device_id)['screen']
    L.on_canvas(page, sx, sy)
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.wait_for_timeout(ms)
    page.mouse.up()
    L.H.settle(page)
    return sx, sy


PART_JS = """(name) => {
    const ring = document.querySelector('[data-ring]');
    const part = ring && ring.querySelector(`[data-ring-part="${name}"]`);
    if (!part) return null;
    const slider = part.matches('[role="slider"]') ? part : part.querySelector('[role="slider"]');
    const node = slider || part, r = node.getBoundingClientRect();
    return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height,
            now: slider ? Number(slider.getAttribute('aria-valuenow')) : null};
}"""


def _part(page, name):
    return page.evaluate(PART_JS, name)


SET_ARC_JS = """([name, target]) => {
    const arc = () => {
        const part = document.querySelector(`[data-ring] [data-ring-part="${name}"]`);
        return part && (part.matches('[role="slider"]') ? part : part.querySelector('[role="slider"]'));
    };
    const value = () => Number(arc().getAttribute('aria-valuenow'));
    if (!arc()) return null;
    arc().focus();
    for (let guard = 0; guard < 400 && value() !== target; guard++)
        arc().dispatchEvent(new KeyboardEvent('keydown', {key: value() < target ? 'ArrowUp' : 'ArrowDown', bubbles: true, cancelable: true}));
    return value();
}"""


def _set_arc(page, name, target):
    """Move an arc to `target` with its arrow keys in one burst (no gap a debounce could split)."""
    got = page.evaluate(SET_ARC_JS, [name, target])
    check(got == target, (f'the {name} arc reaches {target} by its arrow keys', got))


BLUE_JS = """() => {
    const part = document.querySelector('[data-ring] [data-ring-part="swatches"]');
    const blue = part && [...part.querySelectorAll('button, [role="button"], [role="radio"]')]
        .find(n => /blue/i.test(n.getAttribute('aria-label') || ''));
    if (!blue) return null;
    const r = blue.getBoundingClientRect();
    return [r.left + r.width / 2, r.top + r.height / 2];
}"""


def _blue(page):
    at = page.evaluate(BLUE_JS)
    check(at, 'the ring has a Blue swatch (aria-label)')
    return at


def _is_blue(data):
    rgb, hs = data.get('rgb_color'), data.get('hs_color')
    return (rgb is not None and list(rgb) == [0, 0, 255]) or (
        hs is not None and abs(float(hs[0]) - BLUE_HS[0]) <= 1 and abs(float(hs[1]) - BLUE_HS[1]) <= 1)


# --- scenarios ---------------------------------------------------------------------

def scenario_tap_toggles_kitchen_light():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)

        start = len(seen)
        L.tap_marker(page, CEILING_ID)
        check(_look_within(page, CEILING_ID, 'on', 1.5),
              ('a tap turns the light on; the marker shows it within a second', L.marker(page, CEILING_ID)))
        check(_posts(seen, start) == [('light', 'toggle', {'entity_id': CEILING})], ('one toggle, through the card service', _posts(seen, start)))
        check([c[:2] for c in FAKE.calls_on(CEILING)] == [('light', 'toggle')], FAKE.calls)

        # A light that ignores the call: the marker keeps the confirmed look.
        FAKE.frozen = {CEILING}
        start = len(seen)
        L.tap_marker(page, CEILING_ID)
        check(L.wait_for(page, lambda: len(_posts(seen, start)) == 1, 5), ('the second tap is sent', _posts(seen, start)))
        page.wait_for_timeout(1500)
        check(L.marker(page, CEILING_ID)['look'] == 'on', ('never an optimistic flip', L.marker(page, CEILING_ID)))
        FAKE.frozen = set()

        # A fan toggles too (user, 2026-11-11), and does not open the room instead.
        start = len(seen)
        L.tap_marker(page, FAN_ID)
        check(_look_within(page, FAN_ID, 'on', 1.5), ('a tap turns the fan on', L.marker(page, FAN_ID)))
        check(_posts(seen, start) == [('fan', 'toggle', {'entity_id': FAN})], ('the fan toggles in its own domain', _posts(seen, start)))
        check(not page.locator('#twin-room-panel').is_visible(), 'a tap on the fan does not open the room panel')
        _ring_hook(page)
        check(_ring(page) is None, ('a tap opens no ring', _ring(page)))
        L.no_errors(s)


def scenario_hold_opens_ring_and_sets_brightness_and_colour():
    s = L.serve()
    if s is None:
        return
    L.reset()
    _colour_light()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        _open(page, s, ceiling='on')
        L.aim_kitchen(page)
        _ring_hook(page)
        # Lights mode draws the light in the scene (real-time or baked).
        page.evaluate("() => window.__twin.live.setMode('lights')")
        L.H.settle(page, 3)
        before = _light(page)
        check(abs(before['intensity'] - 1) < .01, ('the light is on at full brightness', before))

        start = len(seen)
        sx, sy = _hold(page, CEILING_ID)
        check(_posts(seen, start) == [], ('a hold sends nothing', _posts(seen, start)))
        ring = _ring(page)
        check(ring and ring.get('device_id') == CEILING_ID, ('a hold opens the light\'s ring', ring))
        check(abs(ring['x'] - sx) <= 3 and abs(ring['y'] - sy) <= 3, ('the ring is anchored on the light', ring, (sx, sy)))
        centre = _part(page, 'center')
        check(centre and abs(centre['x'] - sx) <= 8 and abs(centre['y'] - sy) <= 8, ('on/off sits on the light', centre, (sx, sy)))
        for name in ('brightness', 'temperature', 'swatches'):
            check(_part(page, name), (f'the colour light\'s ring has its {name}', name))
        check(_part(page, 'brightness')['now'] == 100, _part(page, 'brightness'))

        # Frozen: the call goes out once; nothing on screen moves.
        FAKE.frozen = {CEILING}
        start = len(seen)
        _set_arc(page, 'brightness', 40)
        check(L.wait_for(page, lambda: len(_posts(seen, start)) >= 1, 5), 'the brightness is sent')
        page.wait_for_timeout(1500)
        check(_posts(seen, start) == [('light', 'turn_on', {'brightness_pct': 40, 'entity_id': CEILING})],
              ('one call, the final value', _posts(seen, start)))
        check(_state(page)['attributes']['brightness'] == 255, _state(page))
        check(abs(_light(page)['intensity'] - 1) < .01, ('the light in the scene keeps the confirmed brightness', _light(page)))
        check(_part(page, 'brightness')['now'] == 100, ('the arc returns to the confirmed brightness', _part(page, 'brightness')))
        FAKE.frozen = set()

        # Confirmed: 40% reaches the arc and the light in the scene.
        start = len(seen)
        _set_arc(page, 'brightness', 40)
        check(L.wait_for(page, lambda: abs(_light(page)['intensity'] - 102 / 255) < .01, 5),
              ('the light in the scene follows the confirmed 40%', _light(page)))
        check(_posts(seen, start) == [('light', 'turn_on', {'brightness_pct': 40, 'entity_id': CEILING})], _posts(seen, start))
        check(_part(page, 'brightness')['now'] == 40, _part(page, 'brightness'))
        check(L.marker(page, CEILING_ID)['look'] == 'on', L.marker(page, CEILING_ID))

        # Blue, first frozen (nothing moves), then confirmed.
        colour = _light(page)['rgb']
        FAKE.frozen = {CEILING}
        start = len(seen)
        page.mouse.click(*_blue(page))
        check(L.wait_for(page, lambda: len(_posts(seen, start)) == 1, 5), ('blue is sent', _posts(seen, start)))
        page.wait_for_timeout(1200)
        check(_light(page)['rgb'] == colour, ('the light keeps its confirmed colour', _light(page), colour))
        FAKE.frozen = set()
        start = len(seen)
        page.mouse.click(*_blue(page))
        check(L.wait_for(page, lambda: _light(page)['rgb'] == [0, 0, 255], 5), ('the light in the scene turns blue', _light(page)))
        posts = _posts(seen, start)
        check(len(posts) == 1 and posts[0][:2] == ('light', 'turn_on') and _is_blue(posts[0][2])
              and posts[0][2].get('entity_id') == CEILING, ('one blue turn_on', posts))
        row = _light(page)
        check(row['real'] or row['baked'], ('the light is drawn (real-time or baked)', row))
        check(_ring(page) and _ring(page)['device_id'] == CEILING_ID, 'the ring stays open while it is used')
        L.no_errors(s)


TOUCH_TARGETS_JS = """() => [...document.querySelectorAll('[data-ring] button, [data-ring] input, [data-ring] [role="switch"],'
    + ' [data-ring] [role="slider"], [data-ring] [role="radio"], [data-ring] [role="button"]')]
    .map(n => { const r = n.getBoundingClientRect(); return {name: n.getAttribute('aria-label') || n.getAttribute('data-ring-part')
        || n.textContent.trim(), w: r.width, h: r.height}; })
    .filter(r => r.w > 0 && r.h > 0)"""

ARC_POINTS_JS = """() => {
    const part = document.querySelector('[data-ring] [data-ring-part="brightness"]');
    const arc = part && (part.matches('[role="slider"]') ? part : part.querySelector('[role="slider"]'));
    if (!arc) return null;
    // Whole-pixel points well inside the arc: every point within 4 px of one is the arc too.
    const on = (x, y) => { const node = document.elementFromPoint(x, y); return !!node && (node === arc || arc.contains(node)); };
    const r = arc.getBoundingClientRect(), hits = [];
    for (let i = 0; i <= 24; i++) for (let j = 0; j <= 24; j++) {
        const x = Math.round(r.left + r.width * i / 24), y = Math.round(r.top + r.height * j / 24);
        if ([[0, 0], [4, 0], [-4, 0], [0, 4], [0, -4]].every(([dx, dy]) => on(x + dx, y + dy))) hits.push([x, y]);
    }
    let best = null, far = -1;
    for (const a of hits) for (const b of hits) { const d = Math.hypot(a[0] - b[0], a[1] - b[1]); if (d > far) { far = d; best = [a, b]; } }
    return best;
}"""


def _touch(cdp, kind, points):
    cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [{'x': x, 'y': y, 'id': 1} for x, y in points]})


def scenario_ring_works_on_the_wall_panel():
    s = L.serve()
    if s is None:
        return
    L.reset()
    _colour_light()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS, has_touch=True) as page:
        seen = L.record(page)
        _open(page, s, query='tier=low&test=1&panel=true&kiosk=true', ceiling='on')
        L.aim_kitchen(page)
        _ring_hook(page)
        cdp = page.context.new_cdp_session(page)

        # A touch held still opens the ring and sends nothing.
        sx, sy = L.sprite(page, CEILING_ID)['screen']
        L.on_canvas(page, sx, sy)
        start = len(seen)
        _touch(cdp, 'touchStart', [(sx, sy)])
        page.wait_for_timeout(700)
        _touch(cdp, 'touchEnd', [])
        L.H.settle(page)
        page.wait_for_timeout(200)
        check(_posts(seen, start) == [], ('a touch hold sends nothing', _posts(seen, start)))
        ring = _ring(page)
        check(ring and ring.get('device_id') == CEILING_ID, ('a touch hold opens the ring at the wall', ring))

        # Every target is at least 44 px either way.
        targets = page.evaluate(TOUCH_TARGETS_JS)
        check(targets, 'the ring has touch targets')
        small = [t for t in targets if t['w'] < 43.5 or t['h'] < 43.5]
        check(not small, ('ring targets are 44 px at the wall', small))

        # A touch tap picks blue.
        start = len(seen)
        bx, by = _blue(page)
        page.touchscreen.tap(bx, by)
        check(L.wait_for(page, lambda: (_state(page)['attributes'].get('rgb_color') or []) == [0, 0, 255], 5),
              ('a touch on Blue turns the light blue', _state(page)['attributes'], _posts(seen, start)))
        posts = _posts(seen, start)
        check(len(posts) == 1 and _is_blue(posts[0][2]), ('one blue turn_on', posts))

        # A touch drag along the brightness arc sends one call, once the finger lifts.
        points = page.evaluate(ARC_POINTS_JS)
        check(points and points[0] != points[1], ('the brightness arc can be touched', points))
        (x0, y0), (x1, y1) = points
        start = len(seen)
        _touch(cdp, 'touchStart', [(x0, y0)])
        for i in range(1, 9):
            page.wait_for_timeout(30)
            _touch(cdp, 'touchMove', [(x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8)])
        check(_posts(seen, start) == [], ('nothing is sent while the finger drags', _posts(seen, start)))
        _touch(cdp, 'touchEnd', [])
        check(L.wait_for(page, lambda: len(_posts(seen, start)) >= 1, 5), 'the drag is sent once the finger lifts')
        page.wait_for_timeout(1500)
        posts = _posts(seen, start)
        check(len(posts) == 1 and posts[0][:2] == ('light', 'turn_on') and isinstance(posts[0][2].get('brightness_pct'), int)
              and 0 <= posts[0][2]['brightness_pct'] <= 100, ('one brightness call for the whole drag', posts))
        check(_part(page, 'brightness')['now'] == posts[0][2]['brightness_pct'], ('the arc shows the confirmed value', _part(page, 'brightness'), posts))

        # A touch on the scene away from the ring closes it.
        spot = page.evaluate("""() => {
            const canvas = window.__twin.renderer3.domElement, r = canvas.getBoundingClientRect();
            const ring = document.querySelector('[data-ring]').getBoundingClientRect();
            for (const [fx, fy] of [[.92, .12], [.92, .8], [.08, .8], [.08, .12], [.5, .9]]) {
                const x = r.left + r.width * fx, y = r.top + r.height * fy;
                if (document.elementFromPoint(x, y) === canvas && (x < ring.left - 20 || x > ring.right + 20 || y < ring.top - 20 || y > ring.bottom + 20))
                    return [x, y];
            }
            return null;
        }""")
        check(spot, 'fixture: an open stretch of scene away from the ring')
        start = len(seen)
        page.touchscreen.tap(*spot)
        check(L.wait_for(page, lambda: _ring(page) is None, 3), ('a touch away from the ring closes it', _ring(page)))
        check(_posts(seen, start) == [], ('and sends nothing', _posts(seen, start)))
        L.no_errors(s)


def scenario_camera_spotlight_keeps_camera_marker_and_controls():
    """Written for the controller's Chromium run; camera refusal stays in force."""
    s = L.serve()
    if s is None:
        return
    L.reset(L.grid(panel={'other': 'no', 'lights': 'yes', 'switches': 'yes'}))
    device = next(d for d in FAKE.devices if d['id'] == CEILING_ID)
    before = copy.deepcopy(device)
    camera, privacy = 'camera.front', 'switch.front_privacy'
    try:
        device['name'] = 'Front camera'
        device['entities'].extend([(camera, 'idle', {}), (privacy, 'off', {})])
        FAKE.states[CEILING]['attributes']['friendly_name'] = 'Front camera Spotlight'
        FAKE.states[camera] = {'entity_id': camera, 'state': 'idle', 'attributes': {'friendly_name': 'Front camera'}}
        FAKE.states[privacy] = {'entity_id': privacy, 'state': 'off', 'attributes': {'friendly_name': 'Front camera Privacy mode'}}
        body = L.facts()
        marker = next(m for m in body['markers'] if m['device_id'] == CEILING_ID)
        check(marker['kind'] == 'camera' and marker['entity_id'] == camera and marker['placed'], marker)
        check(any(CEILING in r['lights'] for r in body['rooms']), 'spotlight remains a room light')
        with s.browser(launch_args=L.GPU_ARGS) as page:
            seen = L.record(page)
            _open(page, s, query='tier=low&test=1&panel=true&kiosk=true', ceiling='on')
            L.aim_kitchen(page)
            check(L.marker(page, CEILING_ID)['kind'] == 'camera', 'camera marker, not a light')
            start = len(seen)
            _hold(page, CEILING_ID)
            check(_ring(page)['device_id'] == CEILING_ID, 'hold opens the camera ring')
            check(_posts(seen, start) == [], 'opening the ring sends no control')
            ring = page.locator('[data-ring]')
            spotlight = ring.get_by_role('switch', name='Spotlight', exact=True)
            check(spotlight.is_visible(), 'Spotlight is available while camera viewing is refused')
            spotlight.click()
            check(L.wait_for(page, lambda: _posts(seen, start) == [('light', 'toggle', {'entity_id': CEILING})], 5),
                  ('toggle uses the spotlight entity', _posts(seen, start)))
            check(spotlight.get_attribute('aria-checked') == 'true', 'confirmed spotlight is on')
            check(ring.get_by_role('switch', name='Privacy mode', exact=True).is_visible(), 'privacy toggle')
            check(ring.locator('[data-ring-part="still"]').count() == 0, 'no camera frame bypasses the household grid')
            page.keyboard.press('Escape')
            page.evaluate('([building, room]) => window.__twin.live.openRoom(building, room)', [marker['building'], marker['room']])
            row = page.locator(f'#twin-room-panel [data-device-id="{CEILING_ID}"]')
            row.get_by_role('switch', name='Spotlight', exact=True).click()
            check(L.wait_for(page, lambda: len(_posts(seen, start)) == 2, 5), 'room panel also toggles spotlight')
            check(_posts(seen, start)[-1] == ('light', 'toggle', {'entity_id': CEILING}), _posts(seen, start))
            L.no_errors(s)
    finally:
        device.clear()
        device.update(before)
        L.reset()


SCENARIOS = [
    scenario_tap_toggles_kitchen_light,
    scenario_hold_opens_ring_and_sets_brightness_and_colour,
    scenario_ring_works_on_the_wall_panel,
    scenario_camera_spotlight_keeps_camera_marker_and_controls,
]


if __name__ == '__main__':
    wanted = set(sys.argv[1:])
    L.run([fn for fn in SCENARIOS if not wanted or fn.__name__ in wanted])
