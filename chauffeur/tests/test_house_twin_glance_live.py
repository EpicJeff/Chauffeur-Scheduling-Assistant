"""Chromium scenarios for Claude to run. Codex must not run this file.

Uses the shared real-house/fake-HA harness, with actual server SSE pushes.
Run from chauffeur/: env -u HA_BASE_URL timeout 300 python tests/test_house_twin_glance_live.py
Optional TWIN_GLANCE_OUTPUT writes screenshots outside the repository.
"""
import time
import copy
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

check = L.check


def tiles(*entities):
    return [{'entity': entity, 'icon': 'thermometer' if entity.startswith(('sensor.kitchen_temperature', 'climate.')) else 'gauge', 'label': ''}
            for entity in entities]


GLANCE_TILES = [{'entity': 'sensor.glance_battery', 'icon': 'battery', 'label': ''},
               {'entity': 'sensor.glance_solar', 'icon': 'solar', 'label': 'Solar'},
               {'entity': 'sensor.kitchen_temperature', 'icon': 'thermometer', 'label': ''}]


def setup():
    served = L.serve()
    if served is None:
        return None
    L.reset()
    from services import storage, twin_glance
    L.FAKE.states.update({
        'sensor.glance_battery': {'entity_id': 'sensor.glance_battery', 'state': '99.9', 'attributes': {'friendly_name': 'Battery', 'device_class': 'battery', 'unit_of_measurement': '%'}},
        'sensor.glance_solar': {'entity_id': 'sensor.glance_solar', 'state': '5800', 'attributes': {'friendly_name': 'Solar', 'device_class': 'power', 'unit_of_measurement': 'W'}},
        'weather.first': {'entity_id': 'weather.first', 'state': 'rainy', 'attributes': {'temperature': 5, 'temperature_unit': '°C'}},
        'weather.garden': {'entity_id': 'weather.garden', 'state': 'partlycloudy', 'attributes': {'temperature': 73.6, 'temperature_unit': '°F'}},
    })
    storage.patch_settings({'weather_entity': 'weather.garden'})
    chosen = tiles('sensor.kitchen_temperature', 'climate.kitchen')
    twin_glance.save(chosen, False)
    twin_glance.save(chosen, False, 'panel-live')
    return served


def push(eid, **changes):
    from services import ha_events
    row = copy.deepcopy(L.FAKE.states[eid])
    if 'attributes' in changes:
        row['attributes'].update(changes.pop('attributes'))
    row.update(changes)
    L.FAKE.states[eid] = row
    ha_events._publish({'entity_id': eid, 'new_state': row})


def shot(page, name):
    if os.environ.get('TWIN_GLANCE_OUTPUT'):
        out = Path(os.environ['TWIN_GLANCE_OUTPUT'])
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / name), full_page=True)


def orb_coverage(page, cover_selector):
    """The screensaver covers a still-visible orb; inspect actual paint order."""
    return page.evaluate("""selector => {
      const orb = document.getElementById('panel-chat-orb'), cover = document.querySelector(selector);
      if (!orb || !cover) return {present: false};
      const box = orb.getBoundingClientRect(), style = getComputedStyle(orb);
      const visible = box.width > 0 && box.height > 0 && style.display !== 'none' &&
        style.visibility !== 'hidden' && Number(style.opacity) > 0;
      const stack = document.elementsFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      const orbIndex = stack.findIndex(node => node === orb || orb.contains(node));
      const coverIndex = stack.findIndex(node => node === cover || cover.contains(node));
      return {present: true, visible, covered: visible && coverIndex >= 0 && (orbIndex < 0 || coverIndex < orbIndex),
        orbIndex, coverIndex, hiddenClass: orb.classList.contains('panel-chat-hidden')};
    }""", cover_selector)


def floor_rgb(page):
    return page.evaluate("""room => {
      const v=window.__twin; let out;
      v.scene.traverse(o=>{if(o.userData.lightWash?.room===room && o.userData.lightWash?.building==='pool-house')
        out={rgb:o.material.color.toArray(),visible:o.parent.visible,opacity:o.material.opacity};});
      return out;
    }""", L.KITCHEN)


def no_glance_argyle_overlap(page):
    # Measure the real panel orb (or the desk chat bar), including responsive
    # sizing and shelf placement, rather than assuming a pixel footprint.
    page.wait_for_function("""() => {
      const argyle=document.getElementById('panel-chat-orb') || document.getElementById('chat-overlay-container');
      const items=[...document.querySelectorAll('#twin-glance > [data-entity]')];
      if (!argyle || !items.length) return false;
      const orb=argyle.getBoundingClientRect();
      return orb.width > 0 && orb.height > 0 && items.every(item => {
        const r=item.getBoundingClientRect();
        return r.width > 0 && r.height > 0 &&
          !(r.left < orb.right && r.right > orb.left && r.top < orb.bottom && r.bottom > orb.top);
      });
    }""", timeout=3000)
    check(True, 'no glance item bounding box intersects Argyle')


def scenario_climate_kitchen_warm_at_80_cool_at_60():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served)
        L.aim_kitchen(page)
        page.get_by_role('button', name='Climate', exact=True).click()
        page.wait_for_timeout(1000)  # allow the actual SSE subscriber to attach
        push('climate.kitchen', attributes={'current_temperature': 80, 'unit_of_measurement': '°F'})
        page.wait_for_function('() => window.__twin.live.state("climate.kitchen").attributes.current_temperature===80', timeout=3000)
        warm = floor_rgb(page)
        check(warm['visible'] and warm['rgb'][0] > warm['rgb'][2], ('warm floor', warm))
        # Labels repaint on the next batched frame, like the wash.
        page.wait_for_function("() => (document.querySelector('.twin-climate-labels')?.textContent || '').includes('80°F')", timeout=3000)
        check('80°F' in page.locator('.twin-climate-labels').inner_text(), 'current and target label')
        shot(page, 'climate-warm.png')
        push('climate.kitchen', attributes={'current_temperature': 60})
        page.wait_for_function('() => window.__twin.live.state("climate.kitchen").attributes.current_temperature===60', timeout=3000)
        # The wash repaints on the next batched frame after the push, so wait for it.
        deadline = time.time() + 3
        cool = floor_rgb(page)
        while not cool['rgb'][2] > cool['rgb'][0] and time.time() < deadline:
            page.wait_for_timeout(100)
            cool = floor_rgb(page)
        check(cool['rgb'][2] > cool['rgb'][0], ('cool floor', cool))
        shot(page, 'climate-cool.png')
        L.no_errors(served)


def scenario_glance_order_live_push_and_unavailable():
    glance_order_live_push_and_unavailable('tier=low&test=1&panel=true&kiosk=true', 'glance-bottom.png')


def scenario_desk_glance_order_live_push_and_unavailable():
    glance_order_live_push_and_unavailable('tier=low&test=1', 'glance-bottom-desk.png')


def glance_order_live_push_and_unavailable(query, screenshot):
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query=query)
        page.wait_for_selector('#twin-glance [data-entity="sensor.kitchen_temperature"]')
        ids = page.locator('#twin-glance > div').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.entity)')
        check(ids == ['sensor.kitchen_temperature', 'climate.kitchen'], ids)
        check(page.locator('#twin-glance').count() == 1, 'one bar')
        no_glance_argyle_overlap(page)
        check(page.locator('#twin-glance [data-entity="climate.kitchen"] strong').inner_text() == '70 °F', 'thermostat current reading, not its mode')
        page.wait_for_timeout(1000)
        push('sensor.kitchen_temperature', state='76.5')
        page.wait_for_function('() => document.querySelector("#twin-glance").textContent.includes("77 °F")', timeout=3000)
        push('sensor.kitchen_temperature', state='unavailable')
        page.wait_for_function("() => document.querySelector('[data-entity=\"sensor.kitchen_temperature\"] strong').textContent === '—'", timeout=3000)
        no_glance_argyle_overlap(page)
        shot(page, screenshot)
        L.no_errors(served)


def scenario_idle_orbits_moves_bar_and_tap_restores_camera():
    served = setup()
    if served is None:
        return
    from services import twin_glance
    twin_glance.save(tiles('sensor.kitchen_temperature'), True, 'panel-live')
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true&idle_ms=4000')
        L.aim_kitchen(page)
        page.mouse.move(900, 800)
        before = page.evaluate("""() => {
          const v=window.__twin; window.__originalBar=document.getElementById('twin-glance');
          return {view:v.state.view,camera:v.cameraKind(),position:v.camera.position.toArray(),
            quaternion:v.camera.quaternion.toArray(),target:v.controls.target.toArray(),zoom:v.camera.zoom};
        }""")
        page.wait_for_function('() => window.__twin.idle.active()', timeout=10000)
        check(page.locator('#twin-idle-clock').is_visible(), 'clock is visible')
        check(page.locator('#twin-idle-clock .ss-time').inner_text(), 'shared clock has time')
        check(page.locator('#twin-idle-clock #twin-glance').count() == 1, 'bar moved into time card')
        check(page.evaluate('() => document.getElementById("twin-glance")===window.__originalBar'), 'same bar identity')
        a = page.evaluate('() => window.__twin.camera.position.toArray()')
        page.wait_for_timeout(500)
        check(a != page.evaluate('() => window.__twin.camera.position.toArray()'), 'camera orbits')
        check(page.locator('#panel-screensaver').count() == 0, 'no photo screensaver over twin idle')
        shot(page, 'idle-clock-glance-hero.png')
        page.dispatch_event('body', 'pointerdown', {'pointerId': 1, 'pointerType': 'touch', 'clientX': 1200, 'clientY': 900})
        after = page.evaluate("""() => {const v=window.__twin;return {view:v.state.view,camera:v.cameraKind(),
          position:v.camera.position.toArray(),quaternion:v.camera.quaternion.toArray(),target:v.controls.target.toArray(),zoom:v.camera.zoom};}""")
        check(after == before, ('exact restored camera', before, after))
        check(page.locator('#twin-glance-home #twin-glance').count() == 1, 'bar returns to bottom')
        no_glance_argyle_overlap(page)
        L.no_errors(served)


def scenario_second_idle_cycle_adds_no_shader_programs():
    served = setup()
    if served is None:
        return
    from services import twin_glance
    twin_glance.save(tiles('sensor.kitchen_temperature'), True, 'panel-live')
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true&idle_ms=2500')
        page.wait_for_function('() => window.__twin.idle.active()', timeout=10000)
        page.wait_for_timeout(500)
        before = page.evaluate('() => window.__twin.renderer3.info.programs.length')
        page.dispatch_event('body', 'keydown', {'key': 'Escape'})
        page.wait_for_function('() => !window.__twin.idle.active()')
        page.wait_for_function('() => window.__twin.idle.active()', timeout=10000)
        page.wait_for_timeout(500)
        after = page.evaluate('() => window.__twin.renderer3.info.programs.length')
        check(after == before, ('no shader programs after first idle cycle', before, after))
        L.no_errors(served)


def scenario_three_formatted_tiles_idle_weather_and_shared_glass():
    served = setup()
    if served is None:
        return
    from services import twin_glance
    twin_glance.save(GLANCE_TILES, True, 'panel-live')
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true&idle_ms=5000')
        page.wait_for_function('() => document.querySelector("#twin-glance")?.textContent.includes("5.8 kW")')
        expected = [('sensor.glance_battery', '100 %', 'battery'), ('sensor.glance_solar', '5.8 kW', 'solar'), ('sensor.kitchen_temperature', '71 °F', 'thermometer')]
        for entity, value, icon in expected:
            tile = page.locator(f'#twin-glance [data-entity="{entity}"]')
            check(tile.locator('strong').inner_text() == value, (entity, 'formatted value'))
            check(tile.locator(f'svg[data-glance-icon="{icon}"]').count() == 1, (entity, 'chosen icon'))
        check(page.locator('#twin-glance [data-glance-label]').all_inner_texts() == ['Solar'], 'only explicit label shown')
        check(page.locator('#twin-glance [data-glance-unit]').all_inner_texts() == ['%', 'kW', '°F'], 'small units')
        no_glance_argyle_overlap(page)
        original = page.locator('#twin-glance').evaluate('(node) => (window.__tileBar = node, true)')
        page.wait_for_function('() => window.__twin.idle.active()', timeout=12000)
        check(original and page.evaluate('() => document.getElementById("twin-glance") === window.__tileBar'), 'same bar in idle')
        check(page.locator('#twin-idle-clock .ss-time').inner_text(), 'time remains visible')
        check(page.locator('#twin-idle-clock .ss-date').inner_text(), 'date remains visible')
        check(page.locator('#twin-idle-weather svg[data-glance-icon="cloud-sun"]').count() == 1, 'household weather icon')
        check(page.locator('#twin-idle-weather strong').inner_text() == '74 °F', 'household current temperature')
        check(page.locator('#twin-idle-weather small').inner_text() == 'Partly cloudy', 'condition in words')
        for entity, value, icon in expected:
            check(page.locator(f'#twin-idle-clock #twin-glance [data-entity="{entity}"] strong').inner_text() == value, 'same idle tile value')
        check(page.locator('#twin-idle-clock').evaluate('(n) => getComputedStyle(n).borderRadius') == '24px', 'glass card radius')
        check(page.locator('#twin-idle-clock .ss-time').evaluate('(n) => getComputedStyle(n).fontWeight') == '200', 'thin clock')
        check(page.locator('#twin-glance strong').evaluate_all('(nodes) => nodes.every(n => n.scrollWidth <= n.clientWidth + 1)'), 'values never ellipsise')
        shot(page, 'idle-card.png')
        L.no_errors(served)


def scenario_no_tiles_keeps_idle_clock_and_unavailable_weather_is_graceful():
    served = setup()
    if served is None:
        return
    from services import twin_glance
    twin_glance.save([], True)
    twin_glance.save(None, True, 'panel-live')
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true&idle_ms=2500')
        check(page.locator('#twin-glance').is_hidden(), 'empty bottom bar hidden despite energy and weather states')
        page.wait_for_function('() => window.__twin.idle.active()', timeout=10000)
        check(page.locator('#twin-glance').is_hidden(), 'empty idle row hidden')
        check(page.locator('#twin-idle-clock .ss-time').inner_text(), 'clock without tiles')
        check(page.locator('#twin-idle-weather svg').count() == 1, 'weather without tiles')
        check(page.locator('#twin-idle-weather small').inner_text() == 'Partly cloudy', 'condition without tiles')
        shot(page, 'idle-card-empty.png')
        push('weather.garden', state='unavailable')
        page.wait_for_function('() => document.getElementById("twin-idle-weather").hidden', timeout=4000)
        check(page.locator('#twin-idle-clock .ss-time').inner_text(), 'clock survives unavailable weather')
        L.no_errors(served)


def scenario_twelve_tiles_wrap_in_idle_without_truncating_values():
    served = setup()
    if served is None:
        return
    from services import twin_glance
    chosen = []
    for i in range(12):
        entity = f'sensor.glance_{i}'
        L.FAKE.states[entity] = {'entity_id': entity, 'state': str(1000 + i * 1000), 'attributes': {'unit_of_measurement': 'W'}}
        chosen.append({'entity': entity, 'icon': 'power', 'label': 'Load ' + str(i + 1)})
    twin_glance.save(chosen, True, 'panel-live')
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1024, 'height': 768})
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true&idle_ms=3000')
        page.wait_for_selector('#twin-glance > div:nth-child(12)')
        check(page.locator('#twin-glance').evaluate('(n) => getComputedStyle(n).flexWrap') == 'nowrap', 'compact bottom row')
        page.wait_for_function('() => window.__twin.idle.active()', timeout=10000)
        check(page.locator('#twin-glance > div').count() == 12, 'all twelve tiles retained')
        check(page.locator('#twin-glance > div').evaluate_all('(nodes) => new Set(nodes.map(n => n.getBoundingClientRect().top)).size > 1'), 'idle row wraps when needed')
        check(page.locator('#twin-glance strong').evaluate_all('(nodes) => nodes.every(n => n.scrollWidth <= n.clientWidth + 1 && getComputedStyle(n).textOverflow !== "ellipsis")'), 'all values readable')
        shot(page, 'idle-card-twelve.png')
        L.no_errors(served)


def scenario_idle_corners_match_the_real_screensaver_offsets():
    served = setup()
    if served is None:
        return
    from services import twin_glance
    twin_glance.save(GLANCE_TILES, True, 'panel-live')
    hero = {'all_done': False, 'next': {'title': 'Placement check', 'at': '4:00 PM',
            'driver': 'Parent', 'start': '2099-01-01T16:00:00Z', 'end': '2099-01-01T17:00:00Z'}}
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1400, 'height': 1000})
        page.route('**/api/home_board*', lambda route: route.fulfill(json={'hero': hero, 'tiles': []}))
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true&idle_ms=2500')
        page.wait_for_function('() => window.__twin.idle.active()', timeout=10000)
        page.wait_for_selector('#twin-idle-next:visible')
        twin = page.evaluate("""() => {
          const clock = document.getElementById('twin-idle-clock').getBoundingClientRect();
          const next = document.getElementById('twin-idle-next').getBoundingClientRect();
          const usable = document.getElementById('twin-idle').getBoundingClientRect();
          return {clock: clock.toJSON(), next: next.toJSON(), width: innerWidth, height: innerHeight,
            shelf: innerHeight - usable.bottom,
            offsets: {left: clock.left, bottom: usable.bottom - clock.bottom,
              right: innerWidth - next.right, top: next.top}, heroWidth: next.width};
        }""")
        clock, next_card = twin['clock'], twin['next']
        check(clock['x'] + clock['width'] / 2 <= twin['width'] / 2,
              ('clock in left half', clock))
        check(clock['y'] + clock['height'] / 2 >= twin['height'] / 2,
              ('clock in lower half', clock))
        check(next_card['x'] + next_card['width'] / 2 >= twin['width'] / 2
              and next_card['y'] + next_card['height'] / 2 <= twin['height'] / 2,
              ('compact hero in upper-right quadrant', next_card))
        check(clock['bottom'] <= twin['height'] - twin['shelf'], 'clock clears the panel shelf')
        check(clock['top'] >= next_card['bottom'] or clock['right'] <= next_card['left'],
              ('clock and hero do not overlap', clock, next_card))
        check(clock['width'] < 880 and clock['width'] <= .92 * twin['width'] + 1,
              ('three-tile card hugs its content instead of filling the cap', clock))
        page.wait_for_function("""() => {
          const head = document.getElementById('twin-idle-head');
          const time = head.firstElementChild.getBoundingClientRect();
          const weather = document.getElementById('twin-idle-weather').getBoundingClientRect();
          return Math.abs(weather.left - time.right - 48) <= 1;
        }""")
        twin_orb = orb_coverage(page, '#twin-canvas')
        check(twin_orb['present'] and twin_orb['covered'] and not twin_orb['hiddenClass'],
              ('opaque scene covers the orb without hiding/moving it', twin_orb))
        # The orb may geometrically share the card's edge, but it cannot paint
        # through it: the opaque scene covers it, just as the screensaver does.
        shot(page, 'idle-placement.png')
        page.dispatch_event('body', 'keydown', {'key': 'Escape'})
        page.wait_for_function('() => !window.__twin.idle.active()')
        check(not orb_coverage(page, '#twin-canvas')['covered'], 'wake restores the orb in front of the scene')

        # Open the actual nav screensaver in the same browser/context, at the
        # same viewport. Compare its measured edges, not a hand-built CSS probe.
        # The harness page owns its context (no second page), so reuse it.
        saver = page
        try:
            saver.set_viewport_size({'width': twin['width'], 'height': twin['height']})
            L.as_panel(saver)
            saver.route('**/api/panel/profile*', lambda route: route.fulfill(json={
                'theme': 'dark', 'tabs': [], 'widgets': [], 'backgrounds': {}, 'idle_seconds': 0,
                'screensaver': {'idle_seconds': .15, 'dwell_seconds': 20, 'source': 'photos'}}))
            saver.route('**/api/panel/screensaver*', lambda route: route.fulfill(json={'urls': []}))
            saver.route('**/api/home_board*', lambda route: route.fulfill(json={'hero': hero, 'tiles': []}))
            L.goto_retry(saver, served.url('home?panel=true&kiosk=true'))
            saver.wait_for_selector('#panel-screensaver #panel-ss-next:visible', timeout=15000)
            actual = saver.evaluate("""() => {
              const clock = document.getElementById('panel-ss-clock').getBoundingClientRect();
              const next = document.getElementById('panel-ss-next').getBoundingClientRect();
              return {offsets: {left: clock.left, bottom: innerHeight - clock.bottom,
                right: innerWidth - next.right, top: next.top}, heroWidth: next.width};
            }""")
            for edge in ('left', 'bottom', 'right', 'top'):
                check(abs(twin['offsets'][edge] - actual['offsets'][edge]) <= 1,
                      ('same screensaver offset (bottom measured above the twin shelf)', edge, twin, actual))
            check(abs(twin['heroWidth'] - actual['heroWidth']) <= 1, 'same responsive compact hero width')
            saver_orb = orb_coverage(saver, '#panel-screensaver')
            check(saver_orb['present'] and saver_orb['covered'] and not saver_orb['hiddenClass'],
                  ('real screensaver covers, rather than hides, its orb', saver_orb))
            check(twin_orb['visible'] == saver_orb['visible'] and twin_orb['covered'] == saver_orb['covered'],
                  ('idle mirrors the screensaver orb treatment', twin_orb, saver_orb))
        finally:
            pass
        L.no_errors(served)


SCENARIOS = [scenario_climate_kitchen_warm_at_80_cool_at_60,
             scenario_glance_order_live_push_and_unavailable,
             scenario_desk_glance_order_live_push_and_unavailable,
             scenario_idle_orbits_moves_bar_and_tap_restores_camera,
             scenario_second_idle_cycle_adds_no_shader_programs,
             scenario_three_formatted_tiles_idle_weather_and_shared_glass,
             scenario_no_tiles_keeps_idle_clock_and_unavailable_weather_is_graceful,
             scenario_twelve_tiles_wrap_in_idle_without_truncating_values,
             scenario_idle_corners_match_the_real_screensaver_offsets]

if __name__ == '__main__':
    L.run(SCENARIOS)
