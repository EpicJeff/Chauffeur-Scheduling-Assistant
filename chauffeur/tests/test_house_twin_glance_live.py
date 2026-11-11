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


def setup():
    served = L.serve()
    if served is None:
        return None
    L.reset()
    from services import twin_glance
    twin_glance.save(['sensor.kitchen_temperature', 'climate.kitchen'], False, 'panel-live')
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
        page.wait_for_function('() => document.querySelector("#twin-glance").textContent.includes("76.5 °F")', timeout=3000)
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
    twin_glance.save(['sensor.kitchen_temperature'], True, 'panel-live')
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
    twin_glance.save(['sensor.kitchen_temperature'], True, 'panel-live')
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


SCENARIOS = [scenario_climate_kitchen_warm_at_80_cool_at_60,
             scenario_glance_order_live_push_and_unavailable,
             scenario_desk_glance_order_live_push_and_unavailable,
             scenario_idle_orbits_moves_bar_and_tap_restores_camera,
             scenario_second_idle_cycle_adds_no_shader_programs]

if __name__ == '__main__':
    L.run(SCENARIOS)
