"""Environment slice 1 in real Chromium: sky, sun, moon, stars, stage haze, overcast, scrub.

Uses the shared real-house/live-HA harness (fake Home Assistant in-process).
Run from chauffeur/: python tests/test_twin_sky_live.py [OUT_DIR for screenshots]
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

H, check = L.H, L.check
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
TIMES = [('noon', '2026-06-21T12:00:00Z'), ('golden', '2026-06-21T19:05:00Z'), ('dusk', '2026-06-21T19:50:00Z'),
         ('night', '2026-06-22T00:30:00Z')]
SUN = "(() => { let s = null; window.__twin.scene.traverse(o => { if (o.name === 'real-sun') s = o; }); return s ? s.intensity : null; })()"
# Sunlight reaching the house: since slice 2 the light keeps its clear intensity and every lit
# material multiplies it by the cloud transmittance, whose value at the house is cloudShadow.centre().
SUN_AT_HOUSE = "(" + SUN + " * (window.__twin.cloudShadow?.centre?.() ?? 1))"


def setup():
    served = L.serve()
    if served is None:
        return None
    L.reset()
    from services import storage, twin_store
    storage.patch_settings({'home_location': 'Sky fixture home', 'timezone': 'Etc/UTC'})
    storage.set_cached_geocode('Sky fixture home', 40, 0)
    twin_store.set_front_bearing(180)
    return served


def pin(page, iso):
    page.evaluate('(iso) => { const v=window.__twin; v.setTime("now"); v.setClock(iso); }', iso)
    H.settle(page, 30)
    page.wait_for_timeout(600)


def low_look(page):
    page.evaluate("""() => { const v = window.__twin; v.levels.go({level:'house'},{immediate:true});
      const c = v.controls.target.clone(), p = v.camera.position.clone();
      const d = p.clone().sub(c); d.y = Math.max(4, d.length() * .12); v.setCameraState({position: c.clone().add(d).toArray(), target: c.toArray()}); }""")
    H.settle(page, 10)


def scenario_times_of_day_look_right_and_compile_nothing_new():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        L.open_twin(page, served, query='tier=high&test=1')
        low_look(page)
        counts = []
        for name, iso in TIMES:
            pin(page, iso)
            counts.append(page.evaluate('window.__twin.renderer3.info.programs.length'))
            if OUT:
                page.screenshot(path=str(OUT / f'sky_live_{name}.png'))
        # The first visit to each look may warm programs once; a second pass must add none.
        for _, iso in TIMES:
            pin(page, iso)
        again = page.evaluate('window.__twin.renderer3.info.programs.length')
        check(again == counts[-1], ('no programs after the first pass', counts, again))
        check(page.evaluate("window.__twin.scene.background?.isTexture === true"), 'the sky is a texture background')
        L.no_errors(served)


def scenario_overcast_weather_softens_the_sun():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        L.open_twin(page, served, query='tier=high&test=1')
        low_look(page)
        pin(page, TIMES[0][1])
        clear = page.evaluate(SUN)
        L.FAKE.states['weather.home'] = {'entity_id': 'weather.home', 'state': 'cloudy',
                                         'attributes': {'friendly_name': 'Home', 'cloud_coverage': 100, 'temperature': 60}}
        page.wait_for_function(f"{SUN_AT_HOUSE} < {clear} * .5", timeout=40000)
        pin(page, TIMES[0][1])
        if OUT:
            page.screenshot(path=str(OUT / 'sky_live_overcast.png'))
        del L.FAKE.states['weather.home']
        page.wait_for_function(f"{SUN_AT_HOUSE} > {clear} * .9", timeout=40000)
        L.no_errors(served)


def scenario_panel_low_tier_has_sky_and_haze():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        L.open_twin(page, served, query='tier=low&test=1&panel=true&kiosk=true')
        page.evaluate("() => {window.__twin.levels.go({level:'house'},{immediate:true});}")
        pin(page, TIMES[1][1])
        check(page.evaluate("window.__twin.scene.background?.isTexture === true"), 'low tier draws the sky')
        check(page.evaluate("!!window.__twin.scene.fog"), 'low tier has the stage haze')
        if OUT:
            page.screenshot(path=str(OUT / 'sky_live_panel_low.png'))
        L.no_errors(served)


def scenario_time_scrub_moves_the_sun_and_returns():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        L.open_twin(page, served, query='tier=high&test=1')
        pin(page, TIMES[0][1])
        check(page.locator('#twin-time-scrub').count() == 1, 'the time scrub exists')
        before = page.evaluate(SUN)
        # The drawer gear is desk-only; drive the slider the way a person's release does.
        page.evaluate("""() => { const s = document.getElementById('twin-time-scrub'); s.value = '20';
          s.dispatchEvent(new Event('input', {bubbles: true})); s.dispatchEvent(new Event('change', {bubbles: true})); }""")
        H.settle(page, 20)
        check(page.evaluate(SUN) < before, ('evening scrub lowers the sun', before, page.evaluate(SUN)))
        L.no_errors(served)


if __name__ == '__main__':
    H.run([scenario_times_of_day_look_right_and_compile_nothing_new, scenario_overcast_weather_softens_the_sun,
           scenario_panel_low_tier_has_sky_and_haze, scenario_time_scrub_moves_the_sun_and_returns])
