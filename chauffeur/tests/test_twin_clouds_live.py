"""Environment slice 2 in real Chromium: clouds from the weather entity.

Uses the shared live-HA harness (fake Home Assistant in-process), the panel view at a
chosen tier (no sign-in overlay). Run from chauffeur/: python tests/test_twin_clouds_live.py [OUT_DIR]
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import house_twin_live_harness as L

H, check = L.H, L.check
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
NOON, GOLDEN, NIGHT = '2026-06-21T12:00:00Z', '2026-06-21T19:05:00Z', '2026-06-22T00:30:00Z'
WEATHER = {
    'clear': ('sunny', 0),
    'partly': ('partlycloudy', 40),
    'cloudy': ('cloudy', 85),
    'overcast_rain': ('rainy', 100),
    'storm': ('lightning-rainy', 100),
}


def setup():
    served = L.serve()
    if served is None:
        return None
    L.reset()
    from services import storage, twin_store
    storage.patch_settings({'home_location': 'Cloud fixture home', 'timezone': 'Etc/UTC'})
    storage.set_cached_geocode('Cloud fixture home', 40, 0)
    twin_store.set_front_bearing(180)
    return served


def weather(kind):
    condition, cover = WEATHER[kind]
    L.FAKE.states['weather.home'] = {'entity_id': 'weather.home', 'state': condition,
                                     'attributes': {'friendly_name': 'Home', 'cloud_coverage': cover, 'temperature': 60,
                                                    'wind_speed': 15, 'wind_bearing': 270, 'wind_speed_unit': 'km/h'}}


def pin(page, iso):
    page.evaluate('(iso) => { const v=window.__twin; v.setTime("now"); v.setClock(iso); }', iso)
    H.settle(page, 30)
    page.wait_for_timeout(800)


def horizon_look(page):
    page.evaluate("""() => { const v = window.__twin; v.levels.go({level:'house'},{immediate:true});
      const c = v.controls.target.clone(), p = v.camera.position.clone();
      const d = p.clone().sub(c); d.y = Math.max(3, d.length() * .08); v.setCameraState({position: c.clone().add(d).toArray(), target: c.toArray()}); }""")
    H.settle(page, 10)


def coverage(page):
    return page.evaluate('window.__twin.clouds?.uniforms?.cloudCoverage?.value ?? null')


def scenario_clouds_follow_the_weather_and_compile_nothing_new():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1600, 'height': 900})
        L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true')
        horizon_look(page)
        programs = []
        for kind in ('clear', 'partly', 'cloudy', 'overcast_rain', 'storm'):
            weather(kind)
            want = WEATHER[kind][1] / 100
            page.wait_for_function(f'Math.abs((window.__twin.clouds?.uniforms?.cloudCoverage?.value ?? -1) - {want}) < .02', timeout=40000)
            for name, iso in (('noon', NOON), ('golden', GOLDEN), ('night', NIGHT)):
                pin(page, iso)
                if OUT:
                    page.screenshot(path=str(OUT / f'clouds_{kind}_{name}.png'))
            programs.append(page.evaluate('window.__twin.renderer3.info.programs.length'))
        check(len(set(programs[1:])) == 1, ('no new programs across weather after the first', programs))
        L.no_errors(served)


def scenario_cloud_pass_cost_is_reported():
    served = setup()
    if served is None:
        return
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1920, 'height': 1080})
        L.open_twin(page, served, query='tier=high&test=1&panel=true&kiosk=true')
        horizon_look(page)
        pin(page, NOON)
        def frame_ms():
            return page.evaluate("""() => new Promise(done => { const t = []; let last = performance.now(), n = 0;
              const step = now => { t.push(now - last); last = now; if (++n < 90) requestAnimationFrame(step); else { t.sort((a,b)=>a-b); done(t[Math.floor(t.length/2)]); } };
              requestAnimationFrame(step); })""")
        weather('clear'); page.wait_for_timeout(15000); clear = frame_ms()
        weather('cloudy'); page.wait_for_function('(window.__twin.clouds?.uniforms?.cloudCoverage?.value ?? 0) > .8', timeout=40000)
        page.wait_for_timeout(3000); cloudy = frame_ms()
        print(f'CLOUD_COST median frame ms clear={clear:.2f} cloudy={cloudy:.2f} delta={cloudy - clear:.2f}')
        L.no_errors(served)


if __name__ == '__main__':
    H.run([scenario_clouds_follow_the_weather_and_compile_nothing_new, scenario_cloud_pass_cost_is_reported])
