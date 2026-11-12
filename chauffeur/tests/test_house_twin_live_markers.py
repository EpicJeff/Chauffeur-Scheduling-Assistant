"""Live device markers in the 3D house, in real Chromium (piece 3 Task 6 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; brief
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-6-brief.md; Review Focus
4 and 5; Ruling Q2: twin taps obey the household control grid through
api/ha/card/service and window.chfControlFetch).

The house, the fake Home Assistant, the panel session and the camera are
tests/house_twin_live_harness.py's (read its docstring first).

What the page must give (the brief):
- /house/twin asks `api/house/live` (ingress-relative); when it says available,
  twin_view mounts the live layer (static/twin/live/live.js mountLive) and, under
  ?test=1, puts it on window.__twin.live: {refresh(), setMode(), markers(), stop()}.
- One marker per device: a THREE.Sprite in window.__twin.scene whose
  userData.deviceId is the device id, drawn at the route's `at` (lot feet;
  the scene point is (x, z, -y) * 0.3048).
- live.markers() lists plain rows {device_id, kind, entity_id, room, building,
  look, label, stale, dim, offered, placed}; `look` is markerState's.
- The state poll is GET api/ha/card/states (fresh=1 right after a control);
  live.refresh() polls now and resolves once the answer is drawn.
- A tap on a light or switch marker posts api/ha/card/service through
  window.chfControlFetch with {domain: <the entity's domain>, service: 'toggle',
  data: {entity_id}}. (The brief's `homeassistant.toggle` cannot pass that
  route: `homeassistant` is in control_rules.NEVER_DOMAINS and the route answers
  400; the entity's own domain toggles.)
- A lock or garage marker opens a small sheet with buttons named exactly `Lock`
  and `Unlock` (or `Open` and `Close`); Unlock and Open ask promptConfirm
  (#cc-confirm-modal) first; lock.unlock / lock.lock / cover.open_cover /
  cover.close_cover follow.
- The marker shows the state of the next poll, never a flip of its own.
- When the poll fails (an HTTP failure, or the empty answer the route gives when
  Home Assistant is away) every marker keeps its look, is marked stale and is
  drawn dimmed; a tap shows `Home Assistant is not reachable.` (showGlobalAlert)
  and sends nothing.
- With no Home Assistant the house draws with no markers and no state polling.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_twin_live_markers.py
"""
import math
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

check = L.check
FAKE = L.FAKE


def _states_requests(seen, fresh=None):
    out = []
    for method, url, _ in seen:
        path, _, query = url.partition('?')
        if method == 'GET' and path.endswith('/api/ha/card/states'):
            if fresh is None or ('fresh=1' in query) == fresh:
                out.append(url)
    return out


def _ingress_relative(seen):
    bad = [url for _, url, _ in seen if '/house/api/' in url or '/house/twin/api/' in url]
    check(not bad, ('every URL is built from the page base, never one level too deep', bad[:3]))


# --- scenarios ---------------------------------------------------------------------

def scenario_markers_sit_at_placed_positions():
    s = L.serve()
    if s is None:
        return
    L.reset()
    body = L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        L.open_twin(page, s)
        L.aim_kitchen(page)
        rows = {m['device_id']: m for m in L.markers(page)}
        check(set(rows) == set(L.NAMES), ('live.markers() lists every device once', sorted(rows)))
        route = {m['device_id']: m for m in body['markers']}
        for did, row in rows.items():
            for key in ('device_id', 'kind', 'entity_id', 'room', 'building', 'look', 'label', 'stale', 'dim',
                        'offered', 'placed'):
                check(key in row, ('marker row key', key, row))
            check(row['kind'] == route[did]['kind'] and row['entity_id'] == route[did]['entity_id']
                  and row['room'] == route[did]['room'] and row['offered'] == route[did]['offered']
                  and row['placed'] == route[did]['placed'], ('the row is the route\'s marker', row, route[did]))
            check(row['stale'] is False, ('a fresh poll is not stale', row))
        check(rows['dev-k-lamp']['look'] == 'on' and rows['dev-k-ceiling']['look'] == 'off', rows)
        check(rows['dev-back-lock']['look'] in ('on', 'off') and rows['dev-k-smoke']['look'] in ('on', 'off'), rows)
        check(isinstance(rows['dev-k-lamp']['label'], str) and rows['dev-k-lamp']['label'].strip(), rows['dev-k-lamp'])

        # Each placed device's sprite sits where its `at` projects (12 px); unplaced ones at their auto spot.
        for did in ('dev-k-ceiling', 'dev-k-coffee', 'dev-k-lamp', 'dev-back-lock', 'dev-changing-light',
                    'dev-hall-light', 'dev-k-pendant'):
            page.evaluate('row => window.__twin.levels.go({building:row.building,room:row.room},{immediate:true})', route[did])
            L.H.settle(page)
            sprite = L.sprite(page, did)
            want = L.screen_of_lot(page, route[did]['at'])
            check(sprite['visible'], ('zoomed in, the marker stands alone (not merged into a badge)', did, sprite))
            d = math.dist(sprite['screen'], want)
            check(d <= 12, (f'{did} is drawn {d:.1f} px from its projected `at`', sprite['screen'], want, route[did]['at']))
            check(L.drawn_full(sprite), ('a live marker is drawn at full strength', did, sprite))
        # The ceiling light hangs at the ceiling: its sprite is 10 ft above the floor.
        ceiling = L.sprite(page, 'dev-k-ceiling')
        check(abs(ceiling['world'][1] / L.FT - route['dev-k-ceiling']['at'][2]) < 0.75,
              ('the sprite height is the anchor height', ceiling['world'], route['dev-k-ceiling']['at']))
        # Every device has exactly one sprite.
        for did in L.NAMES:
            check(len(L.sprites(page, did)) == 1, ('one sprite per device', did, L.sprites(page, did)))
        live_calls = [url for m, url, _ in seen if m == 'GET' and url.split('?')[0].endswith('/api/house/live')]
        check(live_calls, 'the page asked api/house/live for the layout')
        check(_states_requests(seen), 'the page polls api/ha/card/states for the state')
        _ingress_relative(seen)
        L.no_errors(s)


def scenario_tap_light_toggles_through_the_card_service():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        seen = L.record(page)
        L.open_twin(page, s)
        L.aim_kitchen(page)
        check(L.marker(page, 'dev-k-ceiling')['look'] == 'off', L.marker(page, 'dev-k-ceiling'))

        start = len(seen)
        L.tap_marker(page, 'dev-k-ceiling')
        check(L.wait_for(page, lambda: len(FAKE.calls_on('light.ceiling_light')) >= 1),
              ('the tap reached Home Assistant', FAKE.calls))
        calls = FAKE.calls_on('light.ceiling_light')
        check(len(calls) == 1 and calls[0][:2] == ('light', 'toggle'), ('one light.toggle', calls))
        posts = L.service_posts(seen[start:])
        check(len(posts) == 1, ('one POST to api/ha/card/service', posts))
        check(posts[0].get('domain') == 'light' and posts[0].get('service') == 'toggle'
              and (posts[0].get('data') or {}).get('entity_id') == 'light.ceiling_light', posts[0])
        # The confirmed state arrives with the fresh poll that follows the control.
        check(L.wait_for(page, lambda: len(_states_requests(seen[start:], fresh=True)) >= 1),
              ('a fresh=1 poll follows the control', _states_requests(seen[start:])))
        L.wait_look(page, 'dev-k-ceiling', 'on')
        check(L.alert(page) is None, ('nothing alerts on a granted tap', L.alert(page)))

        # A switch toggles the same way, and back again.
        L.tap_marker(page, 'dev-k-coffee')
        check(L.wait_for(page, lambda: len(FAKE.calls_on('switch.coffee_plug')) >= 1), FAKE.calls)
        check(FAKE.calls_on('switch.coffee_plug')[0][:2] == ('switch', 'toggle'), FAKE.calls_on('switch.coffee_plug'))
        L.wait_look(page, 'dev-k-coffee', 'on')
        L.tap_marker(page, 'dev-k-coffee')
        check(L.wait_for(page, lambda: len(FAKE.calls_on('switch.coffee_plug')) >= 2), FAKE.calls)
        L.wait_look(page, 'dev-k-coffee', 'off')
        _ingress_relative(seen)
        L.no_errors(s)


def scenario_unlock_asks_first():
    s = L.serve()
    if s is None:
        return
    # This household lets the panel work locks and the garage without a PIN.
    L.reset(L.grid(panel={'locks': 'yes', 'garage': 'yes'}, proof={'locks': False, 'garage': False}))
    body = L.facts()
    check(all(m['offered'] for m in body['markers'] if m['kind'] in ('lock', 'garage')), body['markers'])
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s)
        L.aim_kitchen(page)

        def sheet_button(name):
            return page.get_by_role('button', name=name, exact=True).locator('visible=true')

        # Unlock, then Cancel: nothing is sent.
        L.tap_marker(page, 'dev-back-lock')
        check(L.wait_for(page, lambda: sheet_button('Unlock').count() == 1),
              'a lock marker opens a sheet with an Unlock button')
        check(sheet_button('Lock').count() == 1, 'and a Lock button')
        check(not FAKE.calls, ('opening the sheet sends nothing', FAKE.calls))
        sheet_button('Unlock').click()
        page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=5000)
        page.click('#cc-confirm-cancel-btn')
        page.wait_for_timeout(1200)
        check(FAKE.calls_on('lock.back_door') == [], ('a cancelled unlock sends nothing', FAKE.calls))
        check(L.marker(page, 'dev-back-lock')['look'] != 'attention', L.marker(page, 'dev-back-lock'))

        # Unlock, then OK: lock.unlock, and the marker wants attention once the poll says unlocked.
        if sheet_button('Unlock').count() == 0:
            L.tap_marker(page, 'dev-back-lock')
            check(L.wait_for(page, lambda: sheet_button('Unlock').count() == 1), 'the sheet opens again')
        sheet_button('Unlock').click()
        page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=5000)
        page.click('#cc-confirm-execute-btn')
        check(L.wait_for(page, lambda: len(FAKE.calls_on('lock.back_door')) >= 1), FAKE.calls)
        calls = FAKE.calls_on('lock.back_door')
        check(len(calls) == 1 and calls[0][:2] == ('lock', 'unlock'), calls)
        L.wait_look(page, 'dev-back-lock', 'attention')

        # Lock needs no confirmation.
        if sheet_button('Lock').count() == 0:
            L.tap_marker(page, 'dev-back-lock')
            check(L.wait_for(page, lambda: sheet_button('Lock').count() == 1), 'the sheet opens again')
        sheet_button('Lock').click()
        check(L.wait_for(page, lambda: len(FAKE.calls_on('lock.back_door')) >= 2), FAKE.calls)
        check(not page.locator('#cc-confirm-modal').is_visible(), 'locking asks nothing')
        check(FAKE.calls_on('lock.back_door')[1][:2] == ('lock', 'lock'), FAKE.calls_on('lock.back_door'))
        check(L.wait_for(page, lambda: L.marker(page, 'dev-back-lock')['look'] in ('on', 'off'), 15),
              ('locked again once the poll says so', L.marker(page, 'dev-back-lock')))

        # The garage: Open asks first, then cover.open_cover. (The sheet closes after an action or on Escape.)
        if sheet_button('Lock').count():
            page.keyboard.press('Escape')
            page.wait_for_timeout(300)
        L.tap_marker(page, 'dev-garage')
        check(L.wait_for(page, lambda: sheet_button('Open').count() == 1), 'a garage marker offers Open')
        check(sheet_button('Close').count() == 1, 'and Close')
        sheet_button('Open').click()
        page.wait_for_selector('#cc-confirm-modal', state='visible', timeout=5000)
        page.click('#cc-confirm-execute-btn')
        check(L.wait_for(page, lambda: len(FAKE.calls_on('cover.garage_door')) >= 1), FAKE.calls)
        check(FAKE.calls_on('cover.garage_door')[0][:2] == ('cover', 'open_cover'), FAKE.calls_on('cover.garage_door'))
        L.wait_look(page, 'dev-garage', 'attention')
        L.no_errors(s)


def scenario_refused_tap_shows_rulebook_message_and_no_flip():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page:
            L.open_twin(page, s)
            L.aim_kitchen(page)
            check(L.marker(page, 'dev-k-ceiling')['offered'] is True, 'the layout offered the light')

            # The household turns panel lights off after the layout was read: the rulebook refuses.
            L.set_grid(L.grid(panel={'lights': 'no'}))
            L.tap_marker(page, 'dev-k-ceiling')
            check(L.wait_for(page, lambda: L.alert(page) is not None),
                  'chfControlFetch shows the rulebook\'s refusal')
            check(L.alert(page) == L.PANEL_NO_LIGHTS, ('the rulebook\'s own words', L.alert(page)))
            check(FAKE.calls == [], ('nothing reached Home Assistant', FAKE.calls))
            check(L.marker(page, 'dev-k-ceiling')['look'] == 'off', ('no optimistic flip', L.marker(page, 'dev-k-ceiling')))
            L.refresh(page)
            check(L.marker(page, 'dev-k-ceiling')['look'] == 'off', ('still off after the poll', L.marker(page, 'dev-k-ceiling')))
            L.close_alert(page)

            # Panel lights need someone to say who they are: the PIN path appears; Cancel sends nothing.
            L.set_grid(L.grid(panel={'lights': 'ask'}))
            L.tap_marker(page, 'dev-k-ceiling')
            page.wait_for_selector('#cc-choice-modal', state='visible', timeout=8000)
            check(page.inner_text('#cc-choice-title').strip() == L.WHO, page.inner_text('#cc-choice-title'))
            page.click('#cc-choice-cancel-btn')
            page.wait_for_timeout(1200)
            check(FAKE.calls == [], ('a cancelled identification sends nothing', FAKE.calls))
            L.refresh(page)
            check(L.marker(page, 'dev-k-ceiling')['look'] == 'off', L.marker(page, 'dev-k-ceiling'))

            # Allowed, but the house never gets there: the marker keeps what the house reports.
            L.set_grid(L.grid())
            FAKE.frozen = {'light.ceiling_light'}
            L.tap_marker(page, 'dev-k-ceiling')
            check(L.wait_for(page, lambda: len(FAKE.calls_on('light.ceiling_light')) == 1), FAKE.calls)
            page.wait_for_timeout(300)
            check(L.marker(page, 'dev-k-ceiling')['look'] == 'off', ('never flipped by the tap itself', L.marker(page, 'dev-k-ceiling')))
            L.refresh(page)
            check(L.marker(page, 'dev-k-ceiling')['look'] == 'off',
                  ('the house stayed off, so the marker stays off', L.marker(page, 'dev-k-ceiling')))
            L.no_errors(s)
    finally:
        L.set_grid(L.grid())
        FAKE.frozen = set()


def scenario_ha_stops_answering_dims_markers():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page, L.LogWatch() as log:
            L.open_twin(page, s)
            L.aim_kitchen(page)
            before = {m['device_id']: m['look'] for m in L.markers(page)}

            # Home Assistant goes away: the states route answers empty, the service answers 503.
            FAKE.available = False
            L.refresh(page)
            rows = {m['device_id']: m for m in L.markers(page)}
            check(set(rows) == set(before), ('the markers stay on the house', sorted(rows)))
            for did, row in rows.items():
                check(row['stale'] is True and row['dim'] is True, ('stale and dimmed', row))
                check(row['look'] == before[did], ('the last state is kept', did, before[did], row['look']))
            check(L.drawn_dim(L.sprite(page, 'dev-k-ceiling')), ('drawn dimmed', L.sprite(page, 'dev-k-ceiling')))

            L.tap_marker(page, 'dev-k-ceiling')
            check(L.wait_for(page, lambda: L.alert(page) is not None), 'a stale tap explains itself')
            check(L.alert(page) == L.UNREACHABLE, ('the unreachable copy', L.alert(page)))
            check(FAKE.calls == [], ('nothing was sent', FAKE.calls))
            L.close_alert(page)

            # It comes back: the next poll is fresh again.
            FAKE.available = True
            L.refresh(page)
            rows = {m['device_id']: m for m in L.markers(page)}
            check(all(r['stale'] is False and r['dim'] is False for r in rows.values()), list(rows.values()))
            check(L.drawn_full(L.sprite(page, 'dev-k-ceiling')), L.sprite(page, 'dev-k-ceiling'))

            # The add-on itself stops answering the poll: stale too.
            page.route('**/api/ha/card/states*', lambda route: route.abort())
            L.refresh(page)
            rows = {m['device_id']: m for m in L.markers(page)}
            check(all(r['stale'] is True and r['dim'] is True for r in rows.values()),
                  ('a failed poll makes every marker stale', list(rows.values())[:2]))
            check(rows['dev-k-lamp']['look'] == 'on', rows['dev-k-lamp'])
            page.unroute('**/api/ha/card/states*')
            L.refresh(page)
            check(all(r['stale'] is False for r in L.markers(page)), 'fresh again')
            L.no_errors(s)
            check(log.records == [], ('nothing logs an error', [r.getMessage() for r in log.records]))
    finally:
        FAKE.available = True


def scenario_ha_stops_answering_after_a_warm_cache_dims_markers():
    """Task 6 review C1 / Ruling Q13, against the real states path.

    The real ha_api.get_states serves its cached copy when the fetch fails, so once
    Home Assistant has answered, card/states keeps answering the OLD, non-empty states
    when it goes away (the fake's own get_states answers [] and hid this). Ruling Q13:
    that answer carries reachable: false and the live layer treats it as a failed poll.
    FAKE.real_states_cache() runs the real get_states and its cache; only the HTTP call
    is faked."""
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    try:
        with FAKE.real_states_cache(), s.browser(launch_args=L.GPU_ARGS) as page, L.LogWatch() as log:
            seen = L.record(page)
            L.open_twin(page, s)
            L.aim_kitchen(page)
            # Home Assistant has answered through the real cache: every marker is fresh.
            rows = {m['device_id']: m for m in L.markers(page)}
            check(all(r['stale'] is False and r['dim'] is False for r in rows.values()),
                  ('the first real fetch is fresh', list(rows.values())[:2]))
            before = {did: r['look'] for did, r in rows.items()}

            # Home Assistant goes away. Wait out get_states' 5 s ttl so the next poll makes a real
            # fetch, which fails, and the route serves the warm cache.
            FAKE.available = False
            page.wait_for_timeout(5500)
            L.refresh(page)
            rows = {m['device_id']: m for m in L.markers(page)}
            check(set(rows) == set(before), ('the markers stay on the house', sorted(rows)))
            for did, row in rows.items():
                check(row['stale'] is True and row['dim'] is True,
                      ('a stale copy served because the fetch failed is a failed poll: stale and dimmed', row))
                check(row['look'] == before[did], ('the last state is kept', did, before[did], row['look']))
            check(L.drawn_dim(L.sprite(page, 'dev-k-ceiling')), ('drawn dimmed', L.sprite(page, 'dev-k-ceiling')))

            # A tap explains itself and sends nothing (not even a POST that the route then refuses).
            start = len(seen)
            L.tap_marker(page, 'dev-k-ceiling')
            check(L.wait_for(page, lambda: L.alert(page) is not None), 'a stale tap explains itself')
            check(L.alert(page) == L.UNREACHABLE, ('the unreachable copy', L.alert(page)))
            page.wait_for_timeout(500)
            check(L.service_posts(seen[start:]) == [],
                  ('a stale tap posts nothing to api/ha/card/service', L.service_posts(seen[start:])))
            check(FAKE.calls == [], ('nothing was sent', FAKE.calls))
            L.close_alert(page)

            # It comes back: the next real fetch is fresh again.
            FAKE.available = True
            L.refresh(page)
            rows = {m['device_id']: m for m in L.markers(page)}
            check(all(r['stale'] is False and r['dim'] is False for r in rows.values()),
                  ('fresh once Home Assistant answers again', list(rows.values())[:2]))
            check(L.drawn_full(L.sprite(page, 'dev-k-ceiling')), L.sprite(page, 'dev-k-ceiling'))
            L.no_errors(s)
            check(log.records == [], ('nothing logs an error', [r.getMessage() for r in log.records]))
    finally:
        FAKE.available = True


def scenario_no_ha_twin_renders_without_markers():
    s = L.serve()
    if s is None:
        return
    L.reset()
    FAKE.available = False
    try:
        with s.browser(launch_args=L.GPU_ARGS) as page, L.LogWatch() as log:
            seen = L.record(page)
            L.open_twin(page, s, live=False)
            st = page.evaluate('() => window.__twin.stats()')
            check(st['drawCalls'] > 0, ('the house draws', st))
            check(L.wait_for(page, lambda: any(m == 'GET' and u.split('?')[0].endswith('/api/house/live')
                                               for m, u, _ in seen), 10),
                  'the twin asks api/house/live whether Home Assistant is there')
            page.wait_for_timeout(3000)
            n = page.evaluate('''() => { let n = 0; window.__twin.scene.traverse(o => {
                if (o.isSprite && o.userData && o.userData.deviceId) n++; }); return n; }''')
            check(n == 0, ('no marker sprites with no Home Assistant', n))
            listed = page.evaluate('() => window.__twin.live ? window.__twin.live.markers() : []')
            check(listed == [], ('no markers', listed))
            check(_states_requests(seen) == [], ('no state polling with no Home Assistant', _states_requests(seen)))
            check(page.get_by_role('button', name='Lights', exact=True).locator('visible=true').count() == 0,
                  'no Lights mode with no Home Assistant')
            check(L.alert(page) is None, ('nothing alerts', L.alert(page)))
            _ingress_relative(seen)
            L.no_errors(s)
            check(log.records == [], ('nothing logs an error', [r.getMessage() for r in log.records]))
    finally:
        FAKE.available = True


CLUMP_IDS = ['dev-k-lamp', 'dev-k-coffee', 'dev-k-temp']


def clump_fixture(page, body, stacked=False):
    """Only change the live layout response; never the household's saved placements."""
    fixture = copy.deepcopy(body)
    origin = next(row['at'] for row in fixture['markers'] if row['device_id'] == CLUMP_IDS[0])
    for index, row in enumerate(fixture['markers']):
        if row['device_id'] in CLUMP_IDS:
            offset = 0 if stacked else CLUMP_IDS.index(row['device_id']) * .45
            row['at'] = [origin[0] + offset, origin[1], 2]
        else:
            row['at'] = [origin[0] + 200 + index * 20, origin[1], 2]
    page.route('**/api/house/live', lambda route: route.fulfill(json=fixture))


CLUMP_BADGE_JS = """(ids) => {
    const v=window.__twin,r=v.renderer3.domElement.getBoundingClientRect();let result=null;
    v.camera.updateMatrixWorld(true);
    v.scene.traverse(o=>{
        if(!o.isSprite || !o.visible || !o.userData.cluster || ids.some(id=>!o.userData.cluster.includes(id)))return;
        const p=o.position.clone().project(v.camera);
        result={count:o.userData.count,canvasText:o.material.map.image.getContext('2d').getImageData(0,0,96,96).data.some(n=>n>0),
          x:r.left+(p.x+1)*r.width/2+(.5-o.center.x)*44,y:r.top+(1-p.y)*r.height/2+(o.center.y-.5)*44};
    });return result;
}"""


def scenario_mid_zoom_clump_is_one_count_then_tap_separates_it():
    s = L.serve()
    if s is None:
        return
    L.reset()
    body = L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        clump_fixture(page, body)
        L.open_twin(page, s)
        L.aim_kitchen(page)
        # Ordinary devices live inside Room; keep the level's fitted camera.
        page.evaluate('state => window.__twin.levels.go(state,{immediate:true})', {'building':L.POOL,'room':L.KITCHEN})
        L.H.settle(page)
        badge = page.evaluate(CLUMP_BADGE_JS, CLUMP_IDS)
        check(badge and badge['count'] == 3 and badge['canvasText'], ('one textured badge reads 3', badge))
        check(all(not L.sprite(page, did)['visible'] for did in CLUMP_IDS), 'members are hidden')
        check(page.locator('.twin-live-labels span:visible').count() == 0, 'no labels at mid zoom')
        pose = page.evaluate('() => window.__twin.camera.position.toArray()')
        page.mouse.click(badge['x'], badge['y'])
        check(L.wait_for(page, lambda: all(L.sprite(page, did)['visible'] for did in CLUMP_IDS), 8), 'tap reveals all three')
        check(page.evaluate('() => window.__twin.camera.position.toArray()') == pose, 'fan preserves Room framing')
        positions = page.evaluate('''ids=>{const v=window.__twin,r=v.renderer3.domElement.getBoundingClientRect(),out=[];
          v.scene.traverse(o=>{if(!o.isSprite||!ids.includes(o.userData.deviceId))return;const p=o.position.clone().project(v.camera);
          out.push([r.left+(p.x+1)*r.width/2+(.5-o.center.x)*44,r.top+(1-p.y)*r.height/2+(o.center.y-.5)*44]);});return out;}''', CLUMP_IDS)
        check(all(math.dist(a, b) >= 52 for i, a in enumerate(positions) for b in positions[i + 1:]), positions)
        L.no_errors(s)


def scenario_stacked_clump_fans_and_member_controls_still_work():
    s = L.serve()
    if s is None:
        return
    L.reset()
    body = L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        clump_fixture(page, body, stacked=True)
        L.open_twin(page, s)
        L.aim_kitchen(page)
        page.evaluate('''() => {const v=window.__twin;v.controls.minDistance=v.camera.position.distanceTo(v.controls.target);}''')
        badge = page.evaluate(CLUMP_BADGE_JS, CLUMP_IDS)
        check(badge and badge['count'] == 3, badge)
        page.mouse.click(badge['x'], badge['y'])
        check(L.wait_for(page, lambda: all(L.sprite(page, did)['visible'] for did in CLUMP_IDS), 8), 'stacked members fan at limit')
        # The sprite's world position stays saved; sprite.center offsets its drawn and hit centre.
        points = page.evaluate('''ids=>{const v=window.__twin,r=v.renderer3.domElement.getBoundingClientRect(),out=[];
          v.scene.traverse(o=>{if(!o.isSprite||!ids.includes(o.userData.deviceId))return;const p=o.position.clone().project(v.camera);
          out.push([r.left+(p.x+1)*r.width/2+(.5-o.center.x)*44,r.top+(1-p.y)*r.height/2+(o.center.y-.5)*44,o.userData.deviceId]);});return out;}''', CLUMP_IDS)
        # The tap recentres the camera on the clump first, so the fan circles the clump's
        # current centre, not where the badge was before the tap.
        centre = [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]
        check(len(points) == 3 and all(abs(math.dist(p[:2], centre) - 60) < 1 for p in points), points)
        check(page.locator('.twin-live-labels span:visible').count() >= 3, 'fan members have labels')
        lamp = next(p for p in points if p[2] == 'dev-k-lamp')
        page.mouse.click(*lamp[:2])
        check(L.wait_for(page, lambda: len(FAKE.calls_on('light.counter_lamp')) == 1), 'fan tap toggles')
        page.mouse.move(*lamp[:2]); page.mouse.down(); page.wait_for_timeout(650); page.mouse.up()
        check(page.locator('[data-ring]:visible').count() == 1, 'fan hold opens ring')
        page.keyboard.press('Escape')
        L.H.settle(page)
        check(page.evaluate(CLUMP_BADGE_JS, CLUMP_IDS) is not None, 'Escape closes the fan')
        L.no_errors(s)


SCENARIOS = [
    scenario_mid_zoom_clump_is_one_count_then_tap_separates_it,
    scenario_stacked_clump_fans_and_member_controls_still_work,
    scenario_markers_sit_at_placed_positions,
    scenario_tap_light_toggles_through_the_card_service,
    scenario_unlock_asks_first,
    scenario_refused_tap_shows_rulebook_message_and_no_flip,
    scenario_ha_stops_answering_dims_markers,
    scenario_ha_stops_answering_after_a_warm_cache_dims_markers,
    scenario_no_ha_twin_renders_without_markers,
]


if __name__ == '__main__':
    L.run(SCENARIOS)
