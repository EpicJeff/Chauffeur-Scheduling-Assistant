"""Viewer navigation in Chromium. Written for Claude; do not run in Codex.

Run from chauffeur/, HA_BASE_URL unset, with a 300-second outer timeout.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import house_twin_live_harness as L

check = L.check


def pinch_out(page):
    """A real two-finger zoom-out, ending before the level ease starts."""
    cdp = page.context.new_cdp_session(page)
    try:
        def fingers(gap):
            return [{'x': 700 - gap / 2, 'y': 500, 'id': 1},
                    {'x': 700 + gap / 2, 'y': 500, 'id': 2}]
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': fingers(240)})
        for gap in (210, 170, 130, 90):
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': fingers(gap)})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        page.wait_for_timeout(600)
    finally:
        cdp.detach()


def scenario_wall_building_floor_room_swipe_and_two_pinches():
    served = L.serve()
    if served is None:
        return
    L.reset()
    L.facts()
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        check(page.locator('[data-view], [data-camera], #twin-views').count() == 0,
              'floor and named camera buttons are absent')
        page.locator(f'[data-level-building="{L.POOL}"]:not([data-level-floor])').click()
        page.wait_for_timeout(450)
        check(page.evaluate('() => window.__twin.levels.snapshot().level') == 'building', 'building icon focuses it')
        page.locator(f'[data-level-building="{L.POOL}"][data-level-floor="L1"]').click()
        page.wait_for_timeout(450)
        floor = page.evaluate('''() => {
          const v=window.__twin,axis=v.camera.position.clone().sub(v.controls.target).normalize();
          return {state:v.levels.snapshot(),top:axis.y,upper:v.groups.levels['pool-house:L2'].visible};
        }''')
        check(floor['state']['level'] == 'floor' and floor['top'] > .9999 and not floor['upper'], floor)
        pair = page.evaluate('''async bid => {
          const v=window.__twin,b=v.plan.buildings.find(b=>b.id===bid),a=-(b.rotation||0)*Math.PI/180;
          const {roomNeighbour}=await import(new URL(window.chfBase+'static/twin/levels.js',location.href).href);
          for(const r of b.rooms.filter(r=>r.level==='L1' && v.live.markers().some(m=>m.building===bid&&m.room===r.id))) {
            const key=JSON.stringify([bid,r.id]);
            const card=[...document.querySelectorAll('[data-room-card]')].find(node=>node.dataset.roomCard===key);
            if(!card || card.hidden || !card.getClientRects().length)continue;
            const neighbour=roomNeighbour(b.rooms,r.id,[-Math.cos(a),-Math.sin(a)]);
            if(neighbour)return {id:r.id,key,next:neighbour.id};
          }
          throw Error('navigation fixture must contain a left neighbour');
        }''', L.POOL)
        card = page.locator(f"[data-room-card='{pair['key']}']:visible")
        card.click()
        page.wait_for_timeout(450)
        check(page.evaluate('() => window.__twin.levels.snapshot().room') == pair['id'], 'room card enters Room')
        shown = page.evaluate('''() => {const v=window.__twin,out=[];v.scene.traverse(o=>{
          if(o.isSprite&&o.visible&&o.userData.deviceId)out.push(v.live.marker(o.userData.deviceId));
        });return out;}''')
        check(shown and all(row['room'] == pair['id'] or row['look'] == 'attention' for row in shown), shown)
        page.mouse.move(720, 650)
        page.mouse.down()
        page.mouse.move(600, 650, steps=10)
        page.mouse.up()
        page.wait_for_timeout(450)
        check(page.evaluate('() => window.__twin.levels.snapshot().room') == pair['next'], 'left swipe reaches nearest neighbour')
        pinch_out(page)
        check(page.evaluate('() => window.__twin.levels.snapshot().level') == 'floor', 'first pinch returns to Floor')
        pinch_out(page)
        check(page.evaluate('() => window.__twin.levels.snapshot().level') == 'building', 'second pinch returns to Building')
        L.no_errors(served)


def scenario_time_preview_is_in_the_house_drawer():
    served = L.serve()
    if served is None:
        return
    L.reset()
    for query in ('tier=low&test=1', 'tier=low&test=1&panel=true&kiosk=true'):
        with served.browser(launch_args=L.GPU_ARGS) as page:
            if 'panel=true' not in query:
                L.H.signed_in(page)
            L.open_twin(page, served, query=query)
            check(page.locator('#twin-controls [data-time]').count() == 0, 'time preview left the control strip')
            gear = '#twin-preview-gear' if 'panel=true' in query else '#twin-settings-gear'
            page.locator(gear).click()
            check(page.locator('[role="dialog"][aria-label="House settings"]').is_visible(), 'shared drawer opens')
            for time in ('day', 'night', 'now'):
                control = page.locator(f'#twin-time-preview [data-time="{time}"]')
                control.click()
                check(page.evaluate('() => window.__twin.state.time') == time, 'drawer preview works')
                check(control.get_attribute('aria-pressed') == 'true', 'selected preview is accessible')
            if 'panel=true' in query:
                check(page.locator('#twin-glance-settings, #twin-energy-settings').count() == 0,
                      'wall drawer contains only session-local preview')
            page.get_by_role('button', name='Close settings', exact=True).click()
            # The drawer animates shut: it must be gone within its transition, not the same instant.
            try:
                page.locator('[role="dialog"][aria-label="House settings"]').wait_for(state='hidden', timeout=3000)
                closed = True
            except Exception:
                closed = False
            check(closed, 'drawer closes')
            L.no_errors(served)


def scenario_second_level_round_trip_adds_no_gpu_programs():
    served = L.serve()
    if served is None:
        return
    L.reset()
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')

        def cycle():
            for state in ({'level': 'house'}, {'building': L.POOL}, {'building': L.POOL, 'floor': 'L1'},
                          {'building': L.POOL, 'room': L.KITCHEN}, {'building': L.POOL, 'floor': 'L2'}, {'level': 'house'}):
                page.evaluate('state => window.__twin.levels.go(state)', state)
                page.wait_for_timeout(450)

        cycle()
        page.evaluate('''() => {const gl=window.__twin.renderer3.getContext(),create=gl.createProgram.bind(gl);
          window.__levelPrograms=0;gl.createProgram=(...args)=>{window.__levelPrograms++;return create(...args);};}''')
        before = page.evaluate('() => window.__twin.renderer3.info.programs.length')
        cycle()
        check(page.evaluate('() => [window.__levelPrograms,window.__twin.renderer3.info.programs.length]') == [0, before],
              'second round trip creates no programs')
        L.no_errors(served)


if __name__ == '__main__':
    L.run([scenario_wall_building_floor_room_swipe_and_two_pinches,
           scenario_time_preview_is_in_the_house_drawer,
           scenario_second_level_round_trip_adds_no_gpu_programs])
