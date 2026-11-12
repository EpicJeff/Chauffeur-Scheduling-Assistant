"""Real-sun Chromium scenarios. Written for Claude to run; Codex must not run them.

Uses the shared real-house/live-HA harness. Fixed cached site: lat 40, lon 0,
UTC civil clock, south-facing Front camera. No network geocoder or paid reads.
Run from chauffeur/: env -u HA_BASE_URL timeout 300 python tests/test_house_twin_real_sun_live.py
"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

H, check = L.H, L.check
NOON = '2026-06-21T12:00:00Z'
DUSK = '2026-06-21T19:50:00Z'
MIDNIGHT = '2026-06-22T00:00:00Z'


def setup():
    served = L.serve()
    if served is None:
        return None
    L.reset()
    from services import storage, twin_store
    storage.patch_settings({'home_location': 'Real sun fixture home', 'timezone': 'Etc/UTC'})
    storage.set_cached_geocode('Real sun fixture home', 40, 0)
    twin_store.set_front_bearing(180)
    return served


def pin(page, iso):
    page.evaluate('(iso) => { const v=window.__twin; v.setTime("now"); v.setClock(iso); }', iso)
    H.settle(page, 4)


def exterior_mean(page):
    return page.evaluate("""() => {
      const v=window.__twin, r=v.renderer3, gl=r.getContext(), sprites=[];
      v.scene.traverse(o=>{if(o.isSprite){sprites.push([o,o.visible]);o.visible=false;}});
      try {
        r.render(v.scene,v.camera);
        const w=gl.drawingBufferWidth,h=gl.drawingBufferHeight,pixels=new Uint8Array(w*h*4);
        gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
        let sum=0,n=0;
        for(let y=Math.floor(h*.1);y<h*.9;y+=8) for(let x=Math.floor(w*.1);x<w*.9;x+=8) {
          const i=(y*w+x)*4; sum+=.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2]; n++;
        }
        return sum/n;
      } finally { for(const [o,visible] of sprites)o.visible=visible; }
    }""")


def scenario_noon_to_midnight_drops_exterior_luminance():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.evaluate("() => {window.__twin.levels.go({level:'house'},{immediate:true});}")
        pin(page, NOON)
        noon = exterior_mean(page)
        pin(page, MIDNIGHT)
        midnight = exterior_mean(page)
        check(noon > 0 and midnight < noon * .5, ('exterior mean drops >50%', noon, midnight))
        L.no_errors(served)


def scenario_no_new_programs_at_noon_dusk_midnight():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true')
        pin(page, NOON)
        page.evaluate('async () => {const v=window.__twin; await v.renderer3.compileAsync(v.scene,v.camera);}')
        before = page.evaluate('() => window.__twin.renderer3.info.programs.length')
        for iso in [DUSK, MIDNIGHT, NOON]:
            pin(page, iso)
            after = page.evaluate('() => window.__twin.renderer3.info.programs.length')
            check(after == before, ('clock changes compile no programs', iso, before, after))
        L.no_errors(served)


def scenario_now_day_night_buttons_follow_clock_and_aria():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        H.signed_in(page)
        L.open_twin(page, served, query='tier=low&test=1')
        pin(page, MIDNIGHT)
        def pressed(name):
            for value in ('now', 'day', 'night'):
                check(page.locator(f'[data-time="{value}"]').get_attribute('aria-pressed') == str(value == name).lower(),
                      ('pressed time button', name, value))
            check(page.evaluate('() => window.__twin.state.time') == name, 'public time state')
        pressed('now')
        dark = exterior_mean(page)
        page.locator('#twin-settings-gear').click()
        page.click('[data-time="day"]')
        H.settle(page)
        pressed('day')
        check(exterior_mean(page) > dark * 2, 'Day previews local noon despite midnight clock')
        page.click('[data-time="night"]')
        pressed('night')
        page.click('[data-time="now"]')
        pressed('now')
        check(abs(exterior_mean(page) - dark) < max(1, dark * .05), 'Now returns to the pinned midnight')
        # A preview is session-only.
        page.click('[data-time="day"]')
        page.reload()
        page.wait_for_function('() => window.__twin?.ready')
        pressed('now')
        L.no_errors(served)


def scenario_facing_dial_saves_reloads_and_has_keyboard_path():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        H.open_editor(page, served)
        page.click('[data-step="Your files"]')
        page.fill('#place-facing-degrees', '90')
        with page.expect_response(lambda r: '/api/house/editor/place/lot/placement' in r.url and r.request.method == 'PUT') as saved:
            page.locator('#place-facing-form button[type="submit"]').click()
        check(saved.value.status == 200, 'parent can save facing')
        page.wait_for_selector('#place-facing-dial:not([disabled])')
        dial = page.locator('#place-facing-dial')
        dial.focus()
        with page.expect_response(lambda r: '/api/house/editor/place/lot/placement' in r.url and r.request.method == 'PUT'):
            page.keyboard.press('ArrowRight')
        page.reload()
        page.wait_for_function('() => window.__editor?.ready')
        page.click('[data-step="Your files"]')
        page.wait_for_function('() => document.getElementById("place-facing-degrees").value === "91"')
        check(dial.get_attribute('aria-valuenow') == '91', 'dial reloads the saved bearing')
        # Pointer dragging uses the same save path. Drag to the north edge.
        page.wait_for_selector('#place-facing-dial:not([disabled])')
        box = dial.bounding_box()
        with page.expect_response(lambda r: '/api/house/editor/place/lot/placement' in r.url and r.request.method == 'PUT'):
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + 4, steps=6)
            page.mouse.up()
        page.wait_for_function('() => document.getElementById("place-facing-degrees").value === "0"')
        shots = Path(os.environ.get('TWIN_REAL_SUN_OUTPUT', tempfile.gettempdir())) / 'real-sun-shots'
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / 'facing-dial-dark-wall.png'), full_page=True)
        L.no_errors(served)


SCENARIOS = [scenario_noon_to_midnight_drops_exterior_luminance,
             scenario_no_new_programs_at_noon_dusk_midnight,
             scenario_now_day_night_buttons_follow_clock_and_aria,
             scenario_facing_dial_saves_reloads_and_has_keyboard_path]

if __name__ == '__main__':
    L.run(SCENARIOS)
