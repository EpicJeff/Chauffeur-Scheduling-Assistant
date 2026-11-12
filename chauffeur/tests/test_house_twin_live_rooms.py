"""The room panel, Lights mode and the wall panel in the 3D house, in real
Chromium (piece 3 Task 7 of docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md;
brief .superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-7-brief.md; Ruling
Q2: every control obeys the household grid through api/ha/card/service and
window.chfControlFetch; Ruling Q4: the House page links to the 3D house, the
twin does not become the front door).

The house, the fake Home Assistant, the panel session and the camera are
tests/house_twin_live_harness.py's (read its docstring first). The Kitchen's
area holds ten devices (three lights, a plug, a fan, a lock, a garage door, a
thermostat, a temperature sensor, a smoke alarm); the Pendant is not placed.

What the page must give (the brief):
- Tapping a room's floor (not a marker) opens a side panel, #twin-room-panel,
  with a heading that is the room's name, listing every device of the room's
  area, placed or not, one row each carrying data-device-id.
- Controls render only when the marker is `offered`, otherwise the row shows state only:
  lights: a toggle (role=switch, aria-checked from the confirmed state) and a
    brightness slider (<input type=range>, percent) sending light.turn_on
    {entity_id, brightness_pct};
  switches and fans: a toggle (role=switch);
  locks and garage doors: explicit actions with promptConfirm before unlocking/opening;
  climate: the current temperature and the setpoint, with steppers sending
    climate.set_temperature {entity_id, temperature};
  sensors: their reading.
- A mode strip with buttons `Lights` and `All`. In Lights mode each linked room's
  floor glows by the mean brightness / 255 of its lights that are on (dark when
  every light is off), tinted by rgb_color when present; non-light markers dim.
  live.rooms() reports [{building, room, glow, rgb}].
- Under ?panel=true&kiosk=true: the house, the mode strip and the room panel;
  never an editing link.
- The House page has a `3D house` control that opens house/twin and keeps the
  panel and kiosk flags.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_twin_live_rooms.py
"""
import os
import re
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

check = L.check
FAKE = L.FAKE
RAISE = re.compile(r'^\s*(\+|raise|warmer|increase|up\b|higher|turn up)', re.I)

# Floor samples (pool-house local feet) clear of markers, labels and the tops of walls
# seen from aim_kitchen()'s camera.
KITCHEN_SAMPLE = (15.5, 2.5)
HALL_SAMPLE = (19.5, 13.5)
CHANGING_SAMPLE = (28.5, 20.0)


def _panel(page):
    return page.locator('#twin-room-panel')


def _open_room(page, x, y, name):
    L.tap_local_floor(page, x, y)
    try:
        page.wait_for_selector('#twin-room-panel', state='visible', timeout=8000)
    except Exception:
        raise AssertionError(f'tapping the {name} floor opens #twin-room-panel')
    heading = _panel(page).get_by_role('heading', name=name, exact=True)
    check(heading.count() >= 1, ('the panel is titled with the room name', name, _panel(page).inner_text()))


def _row(page, device_id):
    rows = _panel(page).locator(f'[data-device-id="{device_id}"]')
    check(rows.count() == 1, ('one row per device, data-device-id', device_id, rows.count(), _panel(page).inner_text()))
    return rows.first


def _controls(row):
    return {'switches': row.get_by_role('switch').count(),
            'buttons': row.locator('button').count(),
            'sliders': row.locator('input[type="range"]').count(),
            'inputs': row.locator('input, select').count()}


def _checked(row):
    return row.get_by_role('switch').first.get_attribute('aria-checked')


# --- scenarios ---------------------------------------------------------------------

def scenario_tap_kitchen_opens_its_devices():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        L.open_twin(page, s)
        L.aim_kitchen(page)
        _open_room(page, *KITCHEN_SAMPLE, 'Kitchen')
        check(L.service_posts(seen) == [], ('opening a room sends nothing', L.service_posts(seen)))
        text = _panel(page).inner_text()
        for did in L.KITCHEN_DEVICES:
            check(L.NAMES[did] in _row(page, did).inner_text(), ('the row names its device', did, _row(page, did).inner_text()))
        for other in ('Changing light', 'Hall light'):
            check(other not in text, ('only the Kitchen area\'s devices', other, text))

        # Sensors show their reading; the thermostat its temperature and setpoint.
        check('71.2' in _row(page, 'dev-k-temp').inner_text(), _row(page, 'dev-k-temp').inner_text())
        thermo = _row(page, 'dev-k-thermo')
        check('70' in thermo.inner_text() and '68' in thermo.inner_text(), ('current 70, setpoint 68', thermo.inner_text()))

        # A light's toggle goes through the card service; the switch shows the confirmed state.
        ceiling = _row(page, 'dev-k-ceiling')
        check(ceiling.get_by_role('switch').count() == 1, ('a light row has one toggle (role=switch)', _controls(ceiling)))
        check(_checked(ceiling) == 'false', ('the toggle reads the light\'s state', _checked(ceiling)))
        start = len(seen)
        ceiling.get_by_role('switch').first.click()
        check(L.wait_for(page, lambda: len(FAKE.calls_on('light.ceiling_light')) >= 1), ('the toggle reached Home Assistant', FAKE.calls))
        call = FAKE.calls_on('light.ceiling_light')[0]
        check(call[0] == 'light' and call[1] in ('toggle', 'turn_on'), call)
        posts = L.service_posts(seen[start:])
        check(len(posts) == 1 and posts[0].get('domain') == 'light'
              and (posts[0].get('data') or {}).get('entity_id') == 'light.ceiling_light', ('through api/ha/card/service', posts))
        check(L.wait_for(page, lambda: _checked(_row(page, 'dev-k-ceiling')) == 'true', 15),
              ('on once the poll says on', _checked(_row(page, 'dev-k-ceiling'))))
        L.wait_look(page, 'dev-k-ceiling', 'on')

        # The fan toggles in its own domain.
        fan = _row(page, 'dev-k-fan')
        check(fan.get_by_role('switch').count() == 1, _controls(fan))
        fan.get_by_role('switch').first.click()
        check(L.wait_for(page, lambda: len(FAKE.calls_on('fan.kitchen_fan')) >= 1), FAKE.calls)
        check(FAKE.calls_on('fan.kitchen_fan')[0][0] == 'fan', FAKE.calls_on('fan.kitchen_fan'))

        # The setpoint steps by the thermostat's own step.
        raise_button = _row(page, 'dev-k-thermo').get_by_role('button', name=RAISE)
        check(raise_button.count() == 1, ('one stepper raises the setpoint', _row(page, 'dev-k-thermo').inner_html()[:400]))
        raise_button.first.click()
        check(L.wait_for(page, lambda: len(FAKE.calls_on('climate.kitchen')) >= 1), FAKE.calls)
        call = FAKE.calls_on('climate.kitchen')[-1]
        check(call[:2] == ('climate', 'set_temperature') and abs(float(call[2].get('temperature')) - 69) < 1e-6, call)

        # The Pendant has no spot of its own yet, and it is still listed with its control.
        pendant = _row(page, 'dev-k-pendant')
        check(pendant.get_by_role('switch').count() == 1, _controls(pendant))
        L.no_errors(s)


def scenario_brightness_slider_sets_percent():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        L.open_twin(page, s)
        L.aim_kitchen(page)
        _open_room(page, *KITCHEN_SAMPLE, 'Kitchen')
        lamp = _row(page, 'dev-k-lamp')
        slider = lamp.locator('input[type="range"]')
        check(slider.count() == 1, ('a light row has a brightness slider', _controls(lamp)))
        check(abs(float(slider.first.input_value()) - 50) <= 1, ('128 / 255 reads as 50 percent', slider.first.input_value()))
        check(_row(page, 'dev-k-coffee').locator('input[type="range"]').count() == 0, 'a plug has no slider')
        start = len(seen)
        slider.first.fill('40')
        check(L.wait_for(page, lambda: len(FAKE.calls_on('light.counter_lamp')) >= 1), ('the slider reached Home Assistant', FAKE.calls))
        calls = FAKE.calls_on('light.counter_lamp')
        check(all(c[:2] == ('light', 'turn_on') for c in calls), calls)
        check(calls[-1][2].get('brightness_pct') == 40, ('brightness_pct 40', calls[-1]))
        posts = L.service_posts(seen[start:])
        check(posts and posts[-1].get('domain') == 'light' and posts[-1].get('service') == 'turn_on'
              and (posts[-1].get('data') or {}).get('brightness_pct') == 40, ('through api/ha/card/service', posts))
        L.refresh(page)
        check(abs(float(_row(page, 'dev-k-lamp').locator('input[type="range"]').first.input_value()) - 40) <= 1,
              'the slider reads the confirmed brightness')
        L.no_errors(s)


def scenario_lights_mode_lights_rooms():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        # The twin follows the real sun and Lights mode never changes the time: pin night so
        # the glow is judged the same whatever hour the test runs.
        page.evaluate("() => window.__twin.setTime('night')")
        L.aim_kitchen(page)
        lights = page.get_by_role('button', name='Lights', exact=True).locator('visible=true')
        everything = page.get_by_role('button', name='All', exact=True).locator('visible=true')
        check(lights.count() == 1 and everything.count() == 1, ('the mode strip: Lights and All', lights.count(), everything.count()))

        def samples():
            out = {}
            for name, (x, y) in (('kitchen', KITCHEN_SAMPLE), ('hall', HALL_SAMPLE), ('changing', CHANGING_SAMPLE)):
                lot = L.lot_of_local(page, x, y)
                sx, sy = L.screen_of_lot(page, [lot[0], lot[1], 0.0])
                L.on_canvas(page, sx, sy)
                out[name] = L.pixel(page, sx, sy)
            return out

        def lum(p):
            return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]

        H = L.H
        H.settle(page, 3)
        plain = samples()

        lights.first.click()
        H.settle(page, 4)
        rooms = {r['room']: r for r in page.evaluate('() => window.__twin.live.rooms()')}
        kitchen, changing, hall = rooms.get(L.KITCHEN), rooms.get(L.CHANGING), rooms.get(L.HALL)
        check(kitchen and changing and hall, ('live.rooms() lists the linked rooms', sorted(rooms)))
        check(abs(kitchen['glow'] - (128 / 255 + 1) / 2) < 0.01, ('the Kitchen: mean of its lights that are on', kitchen))
        check(not kitchen.get('rgb'), ('no colour without rgb_color', kitchen))
        check(abs(changing['glow'] - 0.6) < 0.01 and list(changing.get('rgb') or []) == [0, 0, 255], changing)
        check(hall['glow'] == 0, ('every light off: dark', hall))
        rows = L.markers(page)
        for m in rows:
            want = m['kind'] != 'light'
            check(m['dim'] is want, ('Lights mode dims what is not a light', m))
        check(L.drawn_dim(L.sprite(page, 'dev-back-lock')), ('the lock is drawn dimmed', L.sprite(page, 'dev-back-lock')))
        check(L.drawn_full(L.sprite(page, 'dev-k-lamp')), ('a light is drawn full', L.sprite(page, 'dev-k-lamp')))
        lit = samples()
        rise = (lum(lit['kitchen']) - lum(lit['hall'])) - (lum(plain['kitchen']) - lum(plain['hall']))
        check(rise > 20, ('the Kitchen glows against the dark Hall', round(rise, 1), plain, lit))
        tint = ((lit['changing'][2] - lit['changing'][0]) - (lit['hall'][2] - lit['hall'][0])) \
            - ((plain['changing'][2] - plain['changing'][0]) - (plain['hall'][2] - plain['hall'][0]))
        check(tint > 15, ('the Changing room glows blue', round(tint, 1), plain, lit))

        everything.first.click()
        H.settle(page, 4)
        check(all(m['dim'] is False for m in L.markers(page)), ('All undims every marker', L.markers(page)[:3]))
        back = samples()
        check(abs(lum(back['kitchen']) - lum(plain['kitchen'])) < 12, ('All puts the floors back', plain, back))
        L.no_errors(s)


def scenario_panel_kiosk_has_no_editing():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s, query='tier=low&test=1&panel=true&kiosk=true')
        L.aim_kitchen(page)
        check(page.get_by_role('button', name='Lights', exact=True).locator('visible=true').count() == 1, 'the mode strip shows Lights')
        check(page.get_by_role('button', name='All', exact=True).locator('visible=true').count() == 1, 'and All')

        def editing():
            return page.evaluate('''() => [...document.querySelectorAll('a[href], button')].filter(e => {
                const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                if (!r.width || !r.height || s.visibility === 'hidden' || s.display === 'none') return false;
                const href = e.getAttribute('href') || '', text = (e.textContent || '').trim();
                return /editor|config|admin/.test(href) || /^Edit\\b/.test(text) || /^(Pick a spot|Blink)$/.test(text);
            }).map(e => e.outerHTML.slice(0, 160))''')
        check(page.locator('#twin-edit').count() == 0, 'no Edit the house link on the wall')
        check(editing() == [], ('no editing link on the wall', editing()))
        _open_room(page, *KITCHEN_SAMPLE, 'Kitchen')
        check(_panel(page).locator('a[href]').count() == 0, ('the room panel holds no links', _panel(page).inner_html()[:400]))
        check(editing() == [], ('no editing link with the room panel open', editing()))
        L.no_errors(s)


KITCHEN_BADGE_JS = """(room) => {
    // The Kitchen's room badge as drawn: its sprite's projected spot, moved by sprite.center
    // (live.js pushes neighbouring badges apart that way). null when no badge is drawn.
    const v = window.__twin, camera = v.camera, r = v.renderer3.domElement.getBoundingClientRect();
    const shown = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
    let out = null;
    v.scene.traverse(o => {
        if (out || !o.isSprite || !o.userData || !o.userData.room || o.userData.room.room !== room || !shown(o)) return;
        camera.updateMatrixWorld(true); o.updateMatrixWorld(true);
        const p = o.getWorldPosition(o.position.clone()).project(camera);
        out = [r.left + (p.x + 1) * r.width / 2 + (0.5 - o.center.x) * 52,
               r.top + (1 - p.y) * r.height / 2 + (o.center.y - 0.5) * 52];
    });
    return out;
}"""



def _visible_room_spot(page, room):
    """A client pixel where a tap meets the room's floor, nothing drawn over it; None if none."""
    points = page.evaluate("""(room) => {
        const b = window.__twin.plan.buildings.find(b => (b.rooms || []).some(r => r.id === room));
        const poly = b.rooms.find(r => r.id === room).polygon, xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
        const out = [], x0 = Math.min(...xs), y0 = Math.min(...ys), w = Math.max(...xs) - x0, h = Math.max(...ys) - y0;
        for (let i = 1; i < 8; i++) for (let j = 1; j < 8; j++) out.push([x0 + w * i / 8, y0 + h * j / 8]);
        return out;
    }""", room)
    for x, y in [KITCHEN_SAMPLE, *points]:
        lot = L.lot_of_local(page, x, y)
        sx, sy = L.screen_of_lot(page, [lot[0], lot[1], 0.0])
        if page.evaluate("""([x, y, room]) => {
            const v = window.__twin, canvas = v.renderer3.domElement, p = v.pick(x, y);
            return document.elementFromPoint(x, y) === canvas && p?.kind === 'room' && p.id === room;
        }""", [sx, sy, room]):
            return sx, sy
    return None


def scenario_wall_picks_a_floor_then_opens_the_kitchen():
    """Reach Kitchen through the building and floor icons, then open its hand controls."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        L.open_twin(page, s, query='tier=low&test=1&panel=true&kiosk=true')
        check(page.evaluate('() => window.__twin.state.view') == 'ext', 'the wall lands on the Exterior')
        page.locator(f'[data-level-building="{L.POOL}"]:not([data-level-floor])').click()
        page.wait_for_timeout(450)
        page.locator(f'[data-level-building="{L.POOL}"][data-level-floor="L1"]').click()
        L.H.settle(page, 3)
        check(page.evaluate('() => window.__twin.state.view') == L.FLOOR, 'the floor control picks the floor')
        # Picking a floor moves the camera; locate the Kitchen only once it has come to rest,
        # or the click lands where the badge was a moment ago.
        camera = '() => window.__twin.camera.position.toArray().map(v => v.toFixed(3)).join()'
        for _ in range(20):
            before = page.evaluate(camera)
            page.wait_for_timeout(250)
            if page.evaluate(camera) == before:
                break
        L.H.settle(page)
        card = page.locator('[data-room-card]').filter(has=page.get_by_text('Kitchen', exact=True))
        card.click()
        page.wait_for_timeout(450)
        check(page.evaluate('() => window.__twin.levels.snapshot().room') == L.KITCHEN, 'card enters Kitchen')
        # A floor tap inside Room retains the full panel, including unplaced devices.
        page.evaluate('([b,r]) => window.__twin.live.openRoom(b,r)', [L.POOL,L.KITCHEN])
        spot = 'room card'
        try:
            page.wait_for_selector('#twin-room-panel', state='visible', timeout=8000)
        except Exception:
            raise AssertionError(('a tap on the Kitchen after picking its floor opens #twin-room-panel',
                                  'badge' if spot else 'floor', spot))
        check(_panel(page).get_by_role('heading', name='Kitchen', exact=True).count() >= 1,
              ('the panel is the Kitchen', _panel(page).inner_text()))
        for did in L.KITCHEN_DEVICES:
            check(L.NAMES[did] in _row(page, did).inner_text(), ('the row names its device', did))
        check(L.service_posts(seen) == [] and FAKE.calls == [], ('reaching a room sends nothing', L.service_posts(seen), FAKE.calls))
        L.no_errors(s)


def scenario_house_page_links_to_the_3d_house():
    s = L.serve()
    if s is None:
        return
    L.reset()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.as_panel(page)
        L.goto_retry(page, s.url('house?panel=true&kiosk=true&quality=low'))
        control = page.get_by_role('link', name='3D house', exact=True).or_(
            page.get_by_role('button', name='3D house', exact=True)).locator('visible=true')
        try:
            control.first.wait_for(state='visible', timeout=60000)
        except Exception:
            raise AssertionError('the House page shows a `3D house` control')
        check(control.count() == 1, ('one 3D house control', control.count()))
        control.first.click()
        page.wait_for_url(re.compile(r'/house/twin/?\?'), timeout=30000)
        url = urlparse(page.url)
        query = parse_qs(url.query)
        check(url.path.rstrip('/').endswith('/house/twin'), url.path)
        check(query.get('panel') == ['true'] and query.get('kiosk') == ['true'], ('the wall flags ride along', page.url))
        page.wait_for_function('() => window.__twin && window.__twin.ready === true', timeout=90000)
        check(page.locator('#twin-edit').count() == 0, 'the wall twin offers no editing')
        L.no_errors(s)


def scenario_room_panel_respects_the_grid():
    s = L.serve()
    if s is None:
        return
    L.reset()   # the default grid: the panel works lights, switches and climate; never locks or the garage
    body = L.facts()
    offered = {m['device_id']: m['offered'] for m in body['markers']}
    check(offered['dev-back-lock'] is False and offered['dev-garage'] is False and offered['dev-k-ceiling'] is True, offered)
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            seen = L.record(page)
            L.open_twin(page, s)
            L.aim_kitchen(page)
            # Tapping the lock marker shows its state; nothing acts.
            L.tap_marker(page, 'dev-back-lock')
            page.wait_for_timeout(1000)
            check(page.get_by_role('button', name='Unlock', exact=True).locator('visible=true').count() == 0,
                  'an unoffered lock has no Unlock')
            check(L.service_posts(seen) == [] and FAKE.calls == [], ('nothing is sent', L.service_posts(seen), FAKE.calls))

            if page.locator('#twin-room-panel').is_visible():
                page.keyboard.press('Escape')
                L.H.settle(page)
            _open_room(page, *KITCHEN_SAMPLE, 'Kitchen')
            lock = _row(page, 'dev-back-lock')
            check(_controls(lock) == {'switches': 0, 'buttons': 0, 'sliders': 0, 'inputs': 0},
                  ('the lock row shows state only', _controls(lock), lock.inner_text()))
            check('locked' in lock.inner_text().lower(), ('the lock state is shown', lock.inner_text()))
            garage = _row(page, 'dev-garage')
            check(_controls(garage)['buttons'] == 0 and _controls(garage)['switches'] == 0, _controls(garage))
            check('closed' in garage.inner_text().lower(), garage.inner_text())
            check(_row(page, 'dev-k-ceiling').get_by_role('switch').count() == 1, 'the light is offered')
            check(_row(page, 'dev-k-thermo').locator('button').count() >= 1, 'the thermostat is offered')
            check(L.service_posts(seen) == [] and FAKE.calls == [], ('still nothing sent', L.service_posts(seen), FAKE.calls))

        # The household turns panel lights off: the next page shows the light's state only.
        L.set_grid(L.grid(panel={'lights': 'no'}))
        with s.browser(launch_args=L.GPU_ARGS) as page:
            L.open_twin(page, s)
            L.aim_kitchen(page)
            check(L.marker(page, 'dev-k-ceiling')['offered'] is False, L.marker(page, 'dev-k-ceiling'))
            _open_room(page, *KITCHEN_SAMPLE, 'Kitchen')
            ceiling = _row(page, 'dev-k-ceiling')
            check(_controls(ceiling)['switches'] == 0 and _controls(ceiling)['sliders'] == 0,
                  ('an unoffered light shows state only', _controls(ceiling)))
            check('off' in ceiling.inner_text().lower(), ceiling.inner_text())
            check(_row(page, 'dev-k-fan').get_by_role('switch').count() == 1, 'switches and fans are still offered')
            L.no_errors(s)
    finally:
        L.set_grid(L.grid())


def scenario_wall_recovers_when_home_assistant_returns():
    """Final review I2: the wall loaded while Home Assistant was away (no markers, a tap on
    the Kitchen does nothing). Home Assistant comes back; within the retry window (45 s,
    run forward on the page's clock) the layer mounts with no reload, the markers draw and
    the Kitchen opens."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    FAKE.available = False
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            seen = L.record(page)
            page.clock.install()
            L.open_twin(page, s, query='tier=low&test=1&panel=true&kiosk=true', live=False)
            check(L.wait_for(page, lambda: any(m == 'GET' and u.split('?')[0].endswith('/api/house/live')
                                               for m, u, _ in seen), 10), 'the wall asks api/house/live')
            page.wait_for_timeout(1500)
            check(not page.evaluate('() => !!window.__twin.live'), 'no live layer while Home Assistant is away')
            loads = [u for m, u, _ in seen if m == 'GET' and '/house/twin?' in u]
            FAKE.available = True
            # The clock jump is for the live layer's retry; it would also fire the lighting
            # bake's 30 s worker timeout, which is not under test here.
            page.evaluate('() => window.__twin.bake?.stop()')
            page.clock.fast_forward(46000)
            try:
                page.wait_for_function('() => !!(window.__twin && window.__twin.live)', timeout=20000)
            except Exception:
                raise AssertionError('Home Assistant is back: the live layer mounts within the retry window')
            L.wait_markers(page)
            check([u for m, u, _ in seen if m == 'GET' and '/house/twin?' in u] == loads, 'no reload')
            L.aim_kitchen(page)
            _open_room(page, *KITCHEN_SAMPLE, 'Kitchen')
            for did in L.KITCHEN_DEVICES:
                check(L.NAMES[did] in _row(page, did).inner_text(), ('the row names its device', did))
            L.no_errors(s)
    finally:
        FAKE.available = True


def _far_room_cards(page):
    L.aim_kitchen(page)
    page.evaluate("([b,f]) => {const v=window.__twin;v.levels.go({building:b,floor:f},{immediate:true});v.live.setMode('all');v.render();}", [L.POOL,'L1'])
    L.H.settle(page)


def scenario_far_all_room_card_has_live_facts_and_climate_keeps_round_badges():
    s = L.serve()
    if s is None:
        return
    L.reset()
    body = L.facts()
    # Exercise the room temperature sensor without a thermostat taking precedence.
    for row in body['devices']:
        if row['device_id'] == 'dev-k-thermo':
            row['area_id'] = 'elsewhere'
    FAKE.states['light.pendant']['state'] = 'off'
    with s.browser(launch_args=L.GPU_ARGS) as page:
        page.route('**/api/house/live', lambda route: route.fulfill(json=body))
        L.open_twin(page, s)
        _far_room_cards(page)
        card = page.locator('[data-room-card]').filter(has=page.get_by_text('Kitchen', exact=True))
        check(card.count() == 1 and card.is_visible(), 'Kitchen has one visible card')
        check('71°' in card.inner_text() and '1 on' in card.inner_text(), card.inner_text())
        page.evaluate('''() => {window.__roomCard=document.querySelector('[data-room-card]:not([hidden])');}''')
        FAKE.states['sensor.kitchen_temperature']['state'] = '73.1'
        L.refresh(page)
        check('73°' in card.inner_text(), 'card follows the state poll')
        page.get_by_role('button', name='Climate', exact=True).click()
        check(card.is_visible(), 'Floor keeps its room navigation cards in Climate')
        check(page.evaluate('() => window.__twin.levels.snapshot().level') == 'floor', 'mode preserves Floor navigation')
        page.get_by_role('button', name='All', exact=True).click()
        check(card.is_visible(), 'All restores the card')
        check(page.evaluate('''() => window.__roomCard.isConnected'''), 'mode changes reuse the same room nodes')
        card.click()
        page.wait_for_timeout(450)
        check(page.evaluate('() => window.__twin.levels.snapshot().room') == L.KITCHEN, 'card enters Room and reveals devices')
        L.no_errors(s)


def scenario_room_cards_zoom_round_trip_and_mode_change_compile_no_programs():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)

        def cycle():
            _far_room_cards(page)
            L.aim_kitchen(page)
            page.get_by_role('button', name='Climate', exact=True).click()
            L.H.settle(page)
            _far_room_cards(page)

        cycle()
        page.evaluate('''() => {const gl=window.__twin.renderer3.getContext(),create=gl.createProgram.bind(gl);
          window.__roomPrograms=0;gl.createProgram=(...args)=>{window.__roomPrograms++;return create(...args);};}''')
        before = page.evaluate('() => window.__twin.renderer3.info.programs.length')
        cycle()
        after = page.evaluate('() => [window.__roomPrograms,window.__twin.renderer3.info.programs.length]')
        check(after == [0, before], ('no new programs after first pass', before, after))
        L.no_errors(s)


SCENARIOS = [
    scenario_far_all_room_card_has_live_facts_and_climate_keeps_round_badges,
    scenario_room_cards_zoom_round_trip_and_mode_change_compile_no_programs,
    scenario_wall_recovers_when_home_assistant_returns,
    scenario_tap_kitchen_opens_its_devices,
    scenario_brightness_slider_sets_percent,
    scenario_lights_mode_lights_rooms,
    scenario_panel_kiosk_has_no_editing,
    scenario_wall_picks_a_floor_then_opens_the_kitchen,
    scenario_house_page_links_to_the_3d_house,
    scenario_room_panel_respects_the_grid,
]


if __name__ == '__main__':
    L.run(SCENARIOS)
