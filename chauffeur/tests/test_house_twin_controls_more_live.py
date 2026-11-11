"""Every device kind's controls in the 3D house, cameras, and Home Assistant's own
cards as "More", in real Chromium (Tasks 4 and 5 of
docs/superpowers/plans/2026-11-11-twin-device-controls.md; briefs
.superpowers/sdd/2026-11-11-twin-device-controls/task-4-brief.md and task-5-brief.md;
spec docs/superpowers/specs/2026-11-11-twin-device-controls-design.md decisions 3, 4
and 6, section 4 exit steps 3 and 4, and the user's answers in section 5).

The house, the fake Home Assistant (it records every service call it is sent), the
panel session and the camera are tests/house_twin_live_harness.py's: read its
docstring. This file adds four Kitchen devices to that fake before the app is served
(placed on the Kitchen floor, u, v):

    Kitchen blind    cover.kitchen_blind            open, position 100, OPEN|CLOSE|SET_POSITION|STOP  (.5, .85)
    Kitchen speaker  media_player.kitchen_speaker   playing, volume 0.3, title and artist, sources   (.15, .45)
    House alarm      alarm_control_panel.house      disarmed, code_format number, code_arm_required,
                                                    ARM_HOME|ARM_AWAY                                (.9, .85)
    Porch camera     camera.porch                   idle, entity_picture with HA's access token      (.5, .45)

and teaches the fake the services they take (set_hvac_mode, set_cover_position,
volume_set, alarm_arm_*, alarm_disarm, ...). The camera's still comes from a patched
ha_api.fetch_binary: '/api/camera_proxy/camera.porch' answers a fresh PNG each time
and counts the fetches. The harness's Thermostat (climate.kitchen: heat, 68, 45-95,
step 1, hvac_modes off/heat/cool, idle), Back door lock, Garage door and Ceiling
light are used as they are.

HA's built-in cards need HA's frontend, which no test has. The More scenarios stand
a small one in through Playwright routes: api/ha/frontend/bundle answers a bundle
whose runtime (api/ha/frontend/runtime/fake-test.js) defines hui-light-card,
hui-thermostat-card, hui-humidifier-card and hui-tile-card as plain elements that
keep their config and draw one button, [data-fake-card-toggle], which calls
hass.callService(domain, 'toggle', {entity_id}) — the real card host's own hass, so
the call goes out through api/ha/card/service and the household grid. The refusal
scenario answers the bundle with {ok: false}.

The hooks and selectors assumed (beside the harness's and the Task 3 ring's):
- window.__twin.live.ring() -> null or {device_id, x, y}; the ring is [data-ring];
  its parts carry data-ring-part as tests/test_twin_controls_js.py lists them
  (target, modes, action, position, open, close, volume, now-playing, lock, unlock,
  arm, disarm, still, center);
- the alarm's code is asked in the page: control_center's sheet (#cc-input-modal,
  window.promptInput) or the ring's own [data-ring-part="code"] with an input and a
  [data-ring-part="code-submit"]; a confirm is control_center's #cc-confirm-modal;
  never a browser dialog (Playwright's 'dialog' event never fires);
- the camera's still is an img in [data-ring-part="still"] whose src is the page's
  base + 'api/house/camera/camera.porch' (plus whatever the page's auth and a
  cache-buster add), refreshed every 2 s while the ring is open;
- the twin page loads static/ha_card_host.js (window.ChauffeurHaCards.mountBuiltin);
- each row of the room panel (#twin-room-panel [data-device-id="<id>"]) offers a
  [data-more] button ("More") that mounts HA's card into the panel through
  ChauffeurHaCards.mountBuiltin with {type, config: {type, entity}, interactive: true}:
  light -> hui-light-card, climate -> hui-thermostat-card, humidifier ->
  hui-humidifier-card, anything else -> hui-tile-card; never for a lock, a garage or
  an alarm. When the mount refuses (resolves false), our own controls for the device
  stand in: its ring opens at the marker, or the row shows the ring builder's parts.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_twin_controls_more_live.py [scenario ...]
"""
import copy
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

check = L.check
FAKE = L.FAKE
CEILING, CEILING_ID = 'light.ceiling_light', 'dev-k-ceiling'
THERMO, THERMO_ID = 'climate.kitchen', 'dev-k-thermo'
LOCK, LOCK_ID = 'lock.back_door', 'dev-back-lock'
GARAGE_ID = 'dev-garage'
PLUG, PLUG_ID = 'switch.coffee_plug', 'dev-k-coffee'
BLIND, BLIND_ID = 'cover.kitchen_blind', 'dev-k-blind'
SPEAKER, SPEAKER_ID = 'media_player.kitchen_speaker', 'dev-k-speaker'
ALARM, ALARM_ID = 'alarm_control_panel.house', 'dev-k-alarm'
CAMERA, CAMERA_ID = 'camera.porch', 'dev-k-camera'
CAMERA_TOKEN = 'ha-access-token-5eed'
KITCHEN_SAMPLE = (15.5, 2.5)     # an empty stretch of the Kitchen's floor (local feet)

EXTRA = [
    (BLIND_ID, 'Kitchen blind', 'kitchen', BLIND, 'open',
     {'device_class': 'blind', 'current_position': 100, 'supported_features': 1 | 2 | 4 | 8},
     ('floor', L.KITCHEN, .5, .85)),
    (SPEAKER_ID, 'Kitchen speaker', 'kitchen', SPEAKER, 'playing',
     {'volume_level': 0.3, 'is_volume_muted': False, 'media_title': 'So What', 'media_artist': 'Miles Davis',
      'source_list': ['Radio', 'Spotify'], 'source': 'Spotify',
      'entity_picture': '/api/media_player_proxy/media_player.kitchen_speaker?token=abc123&cache=9',
      'supported_features': 1 | 4 | 8 | 16 | 32 | 2048 | 16384},
     ('floor', L.KITCHEN, .15, .45)),
    (ALARM_ID, 'House alarm', 'kitchen', ALARM, 'disarmed',
     {'code_format': 'number', 'code_arm_required': True, 'changed_by': None, 'supported_features': 1 | 2},
     ('floor', L.KITCHEN, .9, .85)),
    (CAMERA_ID, 'Porch camera', 'kitchen', CAMERA, 'idle',
     {'entity_picture': f'/api/camera_proxy/{CAMERA}?token={CAMERA_TOKEN}', 'access_token': CAMERA_TOKEN,
      'frontend_stream_type': None, 'supported_features': 0},
     ('floor', L.KITCHEN, .5, .45)),
]


def _add_devices():
    """The four devices join the harness's fake and its placements (before the app is served)."""
    for row in EXTRA:
        did, name, area, eid, state, attrs, _place = row
        if did in L.NAMES:
            continue
        L.DEVICES.append(row)
        L.NAMES[did] = name
        L.ENTITY[did] = eid
        L.KITCHEN_DEVICES.append(did)
        FAKE.devices.append({'id': did, 'name': name, 'area_id': area, 'entities': [(eid, state, attrs)]})
        state_row = {'entity_id': eid, 'state': state, 'attributes': {'friendly_name': name, **copy.deepcopy(attrs)}}
        FAKE.states[eid] = state_row
        FAKE.initial[eid] = copy.deepcopy(state_row)


def _teach_more():
    """The fake answers the other kinds' services the way Home Assistant does."""
    from services import ha_api
    inner = ha_api.call_service

    def call(domain, service, data=None, **kw):
        data = copy.deepcopy(data or {})
        out = inner(domain, service, data, **kw)
        ids = data.get('entity_id')
        for eid in ([ids] if isinstance(ids, str) else list(ids or [])):
            row = FAKE.states.get(eid)
            if row is None or eid in FAKE.frozen:
                continue
            attrs = row['attributes']
            if service == 'set_hvac_mode':
                row['state'] = data.get('hvac_mode')
            elif service == 'set_temperature':
                for key in ('target_temp_low', 'target_temp_high'):
                    if data.get(key) is not None:
                        attrs[key] = data[key]
            elif service == 'set_cover_position':
                attrs['current_position'] = int(data['position'])
                row['state'] = 'open' if attrs['current_position'] > 0 else 'closed'
            elif domain == 'cover' and service in ('open_cover', 'close_cover') and 'current_position' in attrs:
                attrs['current_position'] = 100 if service == 'open_cover' else 0
            elif service == 'volume_set':
                attrs['volume_level'] = float(data['volume_level'])
            elif service == 'volume_mute':
                attrs['is_volume_muted'] = bool(data['is_volume_muted'])
            elif service.startswith('alarm_arm_'):
                row['state'] = 'armed_' + service[len('alarm_arm_'):]
            elif service == 'alarm_disarm':
                row['state'] = 'disarmed'
        return out
    ha_api.call_service = call


FRAMES = {'n': 0, 'paths': []}


def _png(n):
    from PIL import Image
    image = Image.new('RGB', (16, 12), ((40 * n) % 256, (90 + 60 * n) % 256, 200))
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def _teach_camera():
    """HA's camera_proxy, behind the server: a fresh frame each fetch, counted."""
    from services import ha_api
    inner = ha_api.fetch_binary

    def fetch(path, *a, **kw):
        if str(path).startswith(f'/api/camera_proxy/{CAMERA}'):
            FRAMES['n'] += 1
            FRAMES['paths'].append(path)
            return _png(FRAMES['n']), 'image/png'
        return inner(path, *a, **kw)
    ha_api.fetch_binary = fetch


_add_devices()
_teach_more()
_teach_camera()


def _offering(**kinds):
    """The default grid, with the panel offered these kinds outright (no proof)."""
    return L.grid(panel={k: 'yes' for k in kinds}, proof={k: False for k in kinds})


# --- the page ------------------------------------------------------------------------

def _open(page, s, query='tier=low&test=1&panel=true'):
    L.open_twin(page, s, query=query, live=False)
    try:
        page.wait_for_function('() => !!(window.__twin && window.__twin.live)', timeout=20000)
    except Exception:
        raise AssertionError('window.__twin.live is missing: the live layer did not mount')
    L.wait_markers(page)
    check(page.evaluate('() => typeof window.__twin.live.ring === "function"'),
          'window.__twin.live.ring() is missing: the live layer reports the open ring (null when none)')


def _ring(page):
    return page.evaluate('() => window.__twin.live.ring()')


def _posts(seen, start=0):
    return [(p.get('domain'), p.get('service'), p.get('data')) for p in L.service_posts(seen[start:])]


def _tap_open(page, device_id, seen):
    """A tap on the marker opens its ring and sends nothing."""
    start = len(seen)
    L.tap_marker(page, device_id)
    check(L.wait_for(page, lambda: (_ring(page) or {}).get('device_id') == device_id, 4),
          (f'a tap on {L.NAMES[device_id]} opens its ring', _ring(page)))
    check(_posts(seen, start) == [], ('opening a ring sends nothing', _posts(seen, start)))


def _ensure_ring(page, device_id, seen):
    """A click in a page-level sheet may close the ring; open it again when it did."""
    if (_ring(page) or {}).get('device_id') != device_id:
        _tap_open(page, device_id, seen)


PART_JS = """(name) => {
    const ring = document.querySelector('[data-ring]');
    const part = ring && ring.querySelector(`[data-ring-part="${name}"]`);
    if (!part) return null;
    const style = getComputedStyle(part);
    if (part.hidden || style.display === 'none' || style.visibility === 'hidden') return null;
    const slider = part.matches('[role="slider"]') ? part : part.querySelector('[role="slider"]');
    const node = slider || part.querySelector('button, [role="button"], [role="switch"]') || part, r = node.getBoundingClientRect();
    return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height, text: part.textContent,
            now: slider ? Number(slider.getAttribute('aria-valuenow')) : null};
}"""


def _part(page, name):
    return page.evaluate(PART_JS, name)


def _need(page, name):
    got = _part(page, name)
    check(got, (f'the ring has its [data-ring-part="{name}"]', name))
    return got


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


CHIPS_JS = """(name) => {
    const part = document.querySelector(`[data-ring] [data-ring-part="${name}"]`);
    if (!part) return null;
    const norm = s => String(s || '').trim().toLowerCase().replace(/[\\s_\\/-]+/g, '_');
    return [...part.querySelectorAll('button, [role="button"], [role="radio"]')].map(n => {
        const r = n.getBoundingClientRect();
        return {name: norm(n.textContent || n.getAttribute('aria-label')), x: r.left + r.width / 2, y: r.top + r.height / 2,
                pressed: n.getAttribute('aria-pressed') === 'true' || n.getAttribute('aria-checked') === 'true'};
    });
}"""


def _chips(page, name):
    return page.evaluate(CHIPS_JS, name) or []


def _chip_at(page, name, value):
    rows = [c for c in _chips(page, name) if c['name'] == value]
    check(rows, (f'a {value} chip in [data-ring-part="{name}"]', [c['name'] for c in _chips(page, name)]))
    return rows[0]['x'], rows[0]['y']


def _click_part(page, name):
    at = _need(page, name)
    page.mouse.click(at['x'], at['y'])


def _modal(page, selector):
    return page.locator(selector).is_visible()


def _handle_asks(page, code, done, seconds=10.0):
    """Answer what the page asks until `done()`: confirms (accepted) and the alarm code
    (control_center's input sheet, or the ring's own code sheet). Counts each kind."""
    import time
    asked = {'confirm': 0, 'code': 0}
    deadline = time.time() + seconds
    while time.time() < deadline:
        if done():
            return asked
        if _modal(page, '#cc-confirm-modal'):
            asked['confirm'] += 1
            page.click('#cc-confirm-execute-btn')
        elif _modal(page, '#cc-input-modal'):
            asked['code'] += 1
            page.fill('#cc-input-field', code)
            page.click('#cc-input-ok-btn')
        elif page.locator('[data-ring-part="code"]').count() and page.locator('[data-ring-part="code"]').first.is_visible():
            asked['code'] += 1
            sheet = page.locator('[data-ring-part="code"]').first
            sheet.locator('input').first.fill(code)
            sheet.locator('[data-ring-part="code-submit"]').first.click()
        page.wait_for_timeout(150)
    check(done(), ('the action finished once the page\'s questions were answered', asked))
    return asked


# --- Task 4 ----------------------------------------------------------------------------

def scenario_thermostat_arc_sets_70_and_cool():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)
        _tap_open(page, THERMO_ID, seen)
        check(_need(page, 'target')['now'] == 68, ('the setpoint handle shows 68', _part(page, 'target')))
        check('idle' in (_need(page, 'action')['text'] or '').lower(), ('hvac_action is shown', _part(page, 'action')))

        start = len(seen)
        _set_arc(page, 'target', 70)
        check(L.wait_for(page, lambda: FAKE.states[THERMO]['attributes'].get('temperature') == 70, 5),
              ('Home Assistant is set to 70', FAKE.states[THERMO], _posts(seen, start)))
        page.wait_for_timeout(1200)
        check(_posts(seen, start) == [('climate', 'set_temperature', {'temperature': 70, 'entity_id': THERMO})],
              ('one set_temperature, the final value', _posts(seen, start)))
        check(_part(page, 'target')['now'] == 70, ('the handle shows the confirmed 70', _part(page, 'target')))

        check([c['name'] for c in _chips(page, 'modes')] == ['off', 'heat', 'cool'], ('a chip per hvac mode', _chips(page, 'modes')))
        start = len(seen)
        page.mouse.click(*_chip_at(page, 'modes', 'cool'))
        check(L.wait_for(page, lambda: FAKE.states[THERMO]['state'] == 'cool', 5), ('Home Assistant is set to cool', FAKE.states[THERMO]))
        check(_posts(seen, start) == [('climate', 'set_hvac_mode', {'hvac_mode': 'cool', 'entity_id': THERMO})], _posts(seen, start))
        check(L.wait_for(page, lambda: [c['name'] for c in _chips(page, 'modes') if c['pressed']] == ['cool'], 3),
              ('the ring shows the confirmed mode', _chips(page, 'modes')))
        state = FAKE.states[THERMO]
        check(state['state'] == 'cool' and state['attributes']['temperature'] == 70, ('Home Assistant shows both', state))
        check(not _modal(page, '#cc-confirm-modal'), 'nothing on a thermostat asks')
        L.no_errors(s)


def scenario_blind_to_half():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)
        _tap_open(page, BLIND_ID, seen)
        check(_need(page, 'position')['now'] == 100, ('the position arc shows 100', _part(page, 'position')))
        start = len(seen)
        _set_arc(page, 'position', 50)
        check(L.wait_for(page, lambda: FAKE.states[BLIND]['attributes'].get('current_position') == 50, 5),
              ('the blind goes to half', FAKE.states[BLIND], _posts(seen, start)))
        page.wait_for_timeout(1200)
        check(_posts(seen, start) == [('cover', 'set_cover_position', {'position': 50, 'entity_id': BLIND})],
              ('one call, the final position', _posts(seen, start)))
        check(_part(page, 'position')['now'] == 50, ('the arc shows the confirmed 50', _part(page, 'position')))
        # A blind's Close and Open never ask (a garage's Open does).
        for verb, service, state in (('close', 'close_cover', 'closed'), ('open', 'open_cover', 'open')):
            _ensure_ring(page, BLIND_ID, seen)
            start = len(seen)
            _click_part(page, verb)
            check(L.wait_for(page, lambda: FAKE.states[BLIND]['state'] == state, 5),
                  (f'{verb} reaches Home Assistant without a question', FAKE.states[BLIND], _modal(page, '#cc-confirm-modal')))
            check(_posts(seen, start) == [('cover', service, {'entity_id': BLIND})], _posts(seen, start))
            check(not _modal(page, '#cc-confirm-modal'), f'a blind\'s {verb} asks nothing')
        L.no_errors(s)


def scenario_speaker_volume():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)
        _tap_open(page, SPEAKER_ID, seen)
        text = _need(page, 'now-playing')['text'] or ''
        check('So What' in text and 'Miles Davis' in text, ('the title and artist as text', text))
        check(_need(page, 'volume')['now'] == 30, ('the volume arc shows 30', _part(page, 'volume')))
        start = len(seen)
        _set_arc(page, 'volume', 55)
        check(L.wait_for(page, lambda: abs(FAKE.states[SPEAKER]['attributes']['volume_level'] - 0.55) < 1e-6, 5),
              ('the speaker is at 55%', FAKE.states[SPEAKER]['attributes'], _posts(seen, start)))
        page.wait_for_timeout(1200)
        posts = _posts(seen, start)
        check(len(posts) == 1 and posts[0][:2] == ('media_player', 'volume_set')
              and abs(float(posts[0][2].get('volume_level')) - 0.55) < 1e-6 and posts[0][2].get('entity_id') == SPEAKER,
              ('one volume_set at 0.55', posts))
        check(_part(page, 'volume')['now'] == 55, ('the arc shows the confirmed volume', _part(page, 'volume')))
        # No artwork: it would need Home Assistant's authentication.
        check(page.evaluate("() => document.querySelectorAll('[data-ring] img, [data-ring] picture').length") == 0, 'no picture in the ring')
        asked = [url for _m, url, _b in seen if 'media_player_proxy' in url or 'abc123' in url]
        check(not asked, ('the page never asks for the artwork', asked))
        L.no_errors(s)


def scenario_unlock_asks_once():
    s = L.serve()
    if s is None:
        return
    L.reset(_offering(locks=True))
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)
        _tap_open(page, LOCK_ID, seen)
        check(not _modal(page, '#cc-confirm-modal'), 'opening the lock\'s ring asks nothing')
        check((_need(page, 'unlock')['text'] or '').strip().lower() == 'unlock', _part(page, 'unlock'))
        start = len(seen)
        _click_part(page, 'unlock')
        asked = _handle_asks(page, '', lambda: FAKE.states[LOCK]['state'] == 'unlocked')
        check(asked == {'confirm': 1, 'code': 0}, ('Unlock asks exactly once', asked))
        page.wait_for_timeout(1200)
        check(not _modal(page, '#cc-confirm-modal'), 'and never a second time')
        check(_posts(seen, start) == [('lock', 'unlock', {'entity_id': LOCK})], ('one unlock', _posts(seen, start)))
        # Lock asks nothing.
        _ensure_ring(page, LOCK_ID, seen)
        start = len(seen)
        _click_part(page, 'lock')
        check(L.wait_for(page, lambda: FAKE.states[LOCK]['state'] == 'locked', 5), ('Lock locks', FAKE.states[LOCK]))
        check(not _modal(page, '#cc-confirm-modal'), 'Lock asks nothing')
        check(_posts(seen, start) == [('lock', 'lock', {'entity_id': LOCK})], _posts(seen, start))
        # Unlock, then Cancel: nothing is sent.
        _ensure_ring(page, LOCK_ID, seen)
        start = len(seen)
        _click_part(page, 'unlock')
        page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=5000)
        page.click('#cc-confirm-cancel-btn')
        page.wait_for_timeout(1500)
        check(_posts(seen, start) == [] and FAKE.states[LOCK]['state'] == 'locked', ('a cancelled Unlock sends nothing', _posts(seen, start)))
        L.no_errors(s)


def scenario_alarm_code_sheet_not_a_dialog():
    s = L.serve()
    if s is None:
        return
    L.reset(_offering(alarm=True))
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        dialogs = []

        def on_dialog(dialog):
            dialogs.append((dialog.type, dialog.message))
            dialog.dismiss()
        page.on('dialog', on_dialog)
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)
        _tap_open(page, ALARM_ID, seen)
        names = sorted(c['name'] for c in _chips(page, 'arm'))
        check(names == ['arm_away', 'arm_home'], ('one Arm button per supported mode (ARM_HOME | ARM_AWAY)', names))
        start = len(seen)
        page.mouse.click(*_chip_at(page, 'arm', 'arm_away'))
        asked = _handle_asks(page, '1234', lambda: FAKE.states[ALARM]['state'] == 'armed_away')
        check(asked == {'confirm': 0, 'code': 1}, ('arming asks for the code, in the page, and nothing else', asked))
        check(_posts(seen, start) == [('alarm_control_panel', 'alarm_arm_away', {'code': '1234', 'entity_id': ALARM})],
              _posts(seen, start))
        _ensure_ring(page, ALARM_ID, seen)
        start = len(seen)
        _click_part(page, 'disarm')
        asked = _handle_asks(page, '1234', lambda: FAKE.states[ALARM]['state'] == 'disarmed')
        check(asked == {'confirm': 1, 'code': 1}, ('Disarm asks once, and for the code', asked))
        check(_posts(seen, start) == [('alarm_control_panel', 'alarm_disarm', {'code': '1234', 'entity_id': ALARM})],
              _posts(seen, start))
        check(dialogs == [], ('never a browser dialog', dialogs))
        L.no_errors(s)


# --- Task 5: the camera -------------------------------------------------------------------

STILL_JS = """() => {
    const part = document.querySelector('[data-ring] [data-ring-part="still"]');
    const img = part && (part.matches('img') ? part : part.querySelector('img'));
    return img ? {src: img.currentSrc || img.src, attr: img.getAttribute('src') || '', loaded: img.complete && img.naturalWidth > 0} : null;
}"""


def scenario_camera_ring_shows_a_still_and_refreshes():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)
        before = FRAMES['n']
        _tap_open(page, CAMERA_ID, seen)
        check(L.wait_for(page, lambda: (page.evaluate(STILL_JS) or {}).get('loaded'), 8),
              ('the ring shows the camera\'s still', page.evaluate(STILL_JS), FRAMES['n'] - before))
        first = page.evaluate(STILL_JS)
        check('api/house/camera/' + CAMERA in first['src'], ('the still comes through the server\'s camera route', first))
        check(not first['attr'].startswith('/'), ('page-relative, never root-relative', first))
        check(CAMERA_TOKEN not in first['src'] and 'camera_proxy' not in first['src'], ('never HA\'s own path or token', first))
        check(FRAMES['n'] > before, ('the server fetched HA\'s camera_proxy', FRAMES))
        n1 = FRAMES['n']
        check(L.wait_for(page, lambda: FRAMES['n'] > n1 and (page.evaluate(STILL_JS) or {}).get('src') != first['src']
                         and (page.evaluate(STILL_JS) or {}).get('loaded'), 4.5),
              ('the still refreshes every 2 s', FRAMES['n'] - n1, page.evaluate(STILL_JS)))
        page.keyboard.press('Escape')
        check(L.wait_for(page, lambda: _ring(page) is None, 3), 'Escape closes the ring')
        n2 = FRAMES['n']
        page.wait_for_timeout(3000)
        check(FRAMES['n'] <= n2 + 1, ('no more stills once the ring is closed', FRAMES['n'] - n2))
        leaked = [url for _m, url, _b in seen if 'camera_proxy' in url or CAMERA_TOKEN in url]
        check(not leaked, ('the page never asks Home Assistant\'s camera path or carries its token', leaked))
        L.no_errors(s)


# --- Task 5: Home Assistant's own cards as More ------------------------------------------

FAKE_RUNTIME_JS = r"""
(() => {
  const loader = function () { return true; };
  loader.e = () => Promise.resolve();
  class FakeCard extends HTMLElement {
    setConfig(config) { this.config = config; this.draw(); }
    set hass(hass) { this._hass = hass; this.draw(); }
    get hass() { return this._hass; }
    draw() {
      if (!this.config || !this._hass || this._toggle) return;
      this._toggle = document.createElement('button');
      this._toggle.type = 'button';
      this._toggle.setAttribute('data-fake-card-toggle', '');
      this._toggle.textContent = 'Card: toggle ' + this.config.entity;
      this._toggle.style.cssText = 'display:block;min-width:160px;min-height:44px';
      this._toggle.addEventListener('click', () => {
        const entity = this.config.entity, domain = String(entity).split('.')[0];
        this.dataset.result = 'pending';
        this._hass.callService(domain, 'toggle', {entity_id: entity})
          .then(() => { this.dataset.result = 'ok'; }, error => { this.dataset.result = 'refused ' + (error && error.status); });
      });
      this.append(this._toggle);
    }
  }
  for (const type of ['light', 'thermostat', 'humidifier', 'tile', 'alarm-panel', 'entities', 'button'])
    if (!customElements.get('hui-' + type + '-card')) customElements.define('hui-' + type + '-card', class extends FakeCard {});
  window.__haWpr = loader;
})();
"""


def _fake_frontend(page, ok=True):
    """HA's frontend bundle, stood in by Playwright routes (see the module docstring)."""
    bundle = ({'ok': True, 'version': 'test', 'runtime': 'api/ha/frontend/runtime/fake-test.js', 'cards': {},
               'chunks': [], 'eager_modules': [], 'config': {}, 'entities': {}, 'devices': {}, 'areas': {}, 'i18n': {}}
              if ok else {'ok': False, 'error': 'no Home Assistant frontend in this test'})
    page.route('**/api/ha/frontend/bundle*', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps(bundle)))
    page.route('**/api/ha/frontend/runtime/fake-test.js*', lambda route: route.fulfill(
        status=200, content_type='text/javascript', body=FAKE_RUNTIME_JS))
    page.route('**/api/ha/frontend/theme/**', lambda route: route.fulfill(status=200, content_type='text/css', body=''))


def _responses(page):
    rows = []
    page.on('response', lambda r: rows.append((r.url.split('?')[0], r.status)))
    return rows


def _open_kitchen(page):
    L.tap_local_floor(page, *KITCHEN_SAMPLE)
    try:
        page.wait_for_selector('#twin-room-panel', state='visible', timeout=8000)
    except Exception:
        raise AssertionError('tapping the Kitchen floor opens #twin-room-panel')


def _row(device_id):
    return f'#twin-room-panel [data-device-id="{device_id}"]'


def _more(page, device_id):
    button = page.locator(_row(device_id) + ' [data-more]')
    check(button.count() == 1, (f'{L.NAMES[device_id]}\'s row in the room panel has one More ([data-more])', button.count()))
    check(button.first.inner_text().strip() == 'More', ('the button says More', button.first.inner_text()))
    button.first.click()


def _card(page, tag, entity, seconds=8.0):
    js = """([tag, entity]) => [...document.querySelectorAll('#twin-room-panel ' + tag)]
        .some(el => el.config && el.config.entity === entity && el.isConnected)"""
    return L.wait_for(page, lambda: page.evaluate(js, [tag, entity]), seconds)


def scenario_more_opens_the_ha_light_card_and_it_controls_through_the_grid():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        _fake_frontend(page)
        seen = L.record(page)
        statuses = _responses(page)
        _open(page, s)
        check(page.evaluate("() => !!(window.ChauffeurHaCards && typeof window.ChauffeurHaCards.mountBuiltin === 'function')"),
              'the twin page loads static/ha_card_host.js (window.ChauffeurHaCards.mountBuiltin)')
        L.aim_kitchen(page)
        _open_kitchen(page)
        _more(page, CEILING_ID)
        check(_card(page, 'hui-light-card', CEILING), ('More mounts Home Assistant\'s light card for the light',
                                                       page.evaluate("() => [...document.querySelectorAll('#twin-room-panel *')].map(n => n.localName).filter(n => n.startsWith('hui-'))")))

        # The card's own control reaches Home Assistant through the card service and the grid.
        start = len(seen)
        page.locator('#twin-room-panel hui-light-card [data-fake-card-toggle]').first.click()
        check(L.wait_for(page, lambda: FAKE.states[CEILING]['state'] == 'on', 5),
              ('the card turns the light on', FAKE.states[CEILING]['state'], _posts(seen, start),
               page.evaluate("() => document.querySelector('#twin-room-panel hui-light-card')?.dataset.result")))
        check(_posts(seen, start) == [('light', 'toggle', {'entity_id': CEILING})], ('through api/ha/card/service', _posts(seen, start)))
        L.refresh(page)
        check(L.marker(page, CEILING_ID)['look'] == 'on', ('the marker shows it', L.marker(page, CEILING_ID)))

        # The grid stands behind the card: lights refused at the panel, the card's toggle is refused.
        L.set_grid(L.grid(panel={'lights': 'no'}))
        calls = len(FAKE.calls_on(CEILING))
        start = len(seen)
        page.locator('#twin-room-panel hui-light-card [data-fake-card-toggle]').first.click()
        check(L.wait_for(page, lambda: any(url.endswith('/api/ha/card/service') and code == 403 for url, code in statuses), 5),
              ('the server refuses the card\'s call by the grid', statuses[-5:]))
        page.wait_for_timeout(800)
        check(len(FAKE.calls_on(CEILING)) == calls and FAKE.states[CEILING]['state'] == 'on',
              ('nothing reached Home Assistant', FAKE.calls_on(CEILING)))
        L.set_grid(L.grid())
        L.close_alert(page)

        # A thermostat gets HA's thermostat card; a plug gets the tile.
        _more(page, THERMO_ID)
        check(_card(page, 'hui-thermostat-card', THERMO), 'More on the thermostat mounts the thermostat card')
        _more(page, PLUG_ID)
        check(_card(page, 'hui-tile-card', PLUG), 'More on a plug mounts the tile card')
        errors = [e for e in L.H.unexpected(s.errors()) if '403' not in e]
        check(not errors, errors)


def scenario_lock_has_no_more_card():
    s = L.serve()
    if s is None:
        return
    L.reset(_offering(locks=True, garage=True, alarm=True))
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        _fake_frontend(page)
        _open(page, s)
        L.aim_kitchen(page)
        _open_kitchen(page)
        for device_id in (LOCK_ID, GARAGE_ID, ALARM_ID):
            check(page.locator(_row(device_id)).count() == 1, (f'{L.NAMES[device_id]} has its row', device_id))
            check(page.locator(_row(device_id) + ' [data-more]').count() == 0,
                  (f'{L.NAMES[device_id]} has no More: a hosted card would skip our confirm', device_id))
        for device_id in (CEILING_ID, THERMO_ID, SPEAKER_ID):
            check(page.locator(_row(device_id) + ' [data-more]').count() == 1, (f'{L.NAMES[device_id]} has its More', device_id))
        check(page.evaluate("() => document.querySelectorAll('hui-tile-card, hui-alarm-panel-card, hui-entities-card').length") == 0,
              'no card was mounted for them')
        L.no_errors(s)


CENTRE_JS = """(id) => {
    const shown = node => { if (!node) return false; const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const ring = window.__twin.live.ring();
    const inRing = ring && ring.device_id === id && document.querySelector('[data-ring] [data-ring-part="center"]');
    const inRow = document.querySelector(`#twin-room-panel [data-device-id="${id}"] [data-ring-part="center"]`);
    const part = shown(inRing) ? inRing : shown(inRow) ? inRow : null;
    if (!part) return null;
    const node = part.matches('[role="switch"], button') ? part : part.querySelector('[role="switch"], button') || part;
    const r = node.getBoundingClientRect();
    return {where: part === inRing ? 'ring' : 'row', x: r.left + r.width / 2, y: r.top + r.height / 2};
}"""


def scenario_card_refusal_falls_back_to_our_ring():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        _fake_frontend(page, ok=False)
        seen = L.record(page)
        _open(page, s)
        L.aim_kitchen(page)
        _open_kitchen(page)
        _more(page, CEILING_ID)
        check(L.wait_for(page, lambda: page.evaluate(CENTRE_JS, CEILING_ID), 8),
              ('when HA\'s card refuses to mount, our own controls stand in (the ring at the light, or its parts in the row)',
               _ring(page), page.locator(_row(CEILING_ID)).inner_text() if page.locator(_row(CEILING_ID)).count() else None))
        check(page.evaluate("() => document.querySelectorAll('hui-light-card').length") == 0, 'no card element is left behind')
        at = page.evaluate(CENTRE_JS, CEILING_ID)
        start = len(seen)
        page.mouse.click(at['x'], at['y'])
        check(L.wait_for(page, lambda: FAKE.states[CEILING]['state'] == 'on', 5),
              ('our fallback controls the light', at, _posts(seen, start)))
        check(_posts(seen, start) == [('light', 'toggle', {'entity_id': CEILING})], _posts(seen, start))
        L.no_errors(s)


SCENARIOS = [
    scenario_thermostat_arc_sets_70_and_cool,
    scenario_blind_to_half,
    scenario_speaker_volume,
    scenario_unlock_asks_once,
    scenario_alarm_code_sheet_not_a_dialog,
    scenario_camera_ring_shows_a_still_and_refreshes,
    scenario_more_opens_the_ha_light_card_and_it_controls_through_the_grid,
    scenario_lock_has_no_more_card,
    scenario_card_refusal_falls_back_to_our_ring,
]


if __name__ == '__main__':
    wanted = set(sys.argv[1:])
    L.run([fn for fn in SCENARIOS if not wanted or fn.__name__ in wanted])
