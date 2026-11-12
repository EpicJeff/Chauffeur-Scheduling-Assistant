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
          for(const r of b.rooms.filter(r=>r.level==='L1')) {
            const neighbour=roomNeighbour(b.rooms,r.id,[-Math.cos(a),-Math.sin(a)]);
            if(neighbour)return {id:r.id,name:r.name,next:neighbour.id};
          }
          throw Error('navigation fixture must contain a left neighbour');
        }''', L.POOL)
        card = page.locator('[data-room-card]').filter(has=page.get_by_text(pair['name'], exact=True))
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
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1')
        check(page.locator('#twin-controls [data-time]').count() == 0, 'time preview left the control strip')
        page.evaluate("() => window.dispatchEvent(new CustomEvent('chf-settings-open',{detail:{tab:'twin'}}))")
        for time in ('day', 'night', 'now'):
            page.locator(f'#twin-time-preview [data-time="{time}"]').click()
            check(page.evaluate('() => window.__twin.state.time') == time, 'drawer preview works')
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
