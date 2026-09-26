"""Hybrid exterior, parking and cabins follow the same sun as the rooms."""
import itertools
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from test_house_hybrid_live import seed, live_app, ha_api, storage

OUT = Path(__file__).resolve().parents[2] / 'scratch/exterior-lighting'


def main():
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    def setup():
        seed()
        storage.patch_settings({'house_hybrid_enabled': True, 'panel_idle_return_seconds': 0})
    served = live_app(setup)
    assert served, 'Playwright required'
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {'window': {'night': False, 'next_sun_change': None}, 'garage': {'cars': [
        {'id': 'ev', 'name': 'Family EV', 'house_artwork': 'ev9-white-black-roof', 'present': True, 'battery_pct': 76},
        {'id': 'gls', 'name': 'Big SUV', 'house_artwork': 'gls450-white-23', 'present': True, 'fuel_pct': 58},
        {'id': 'murano', 'name': 'Commuter', 'house_artwork': 'murano-white', 'present': True, 'fuel_pct': 43},
    ]}, 'curb': {'bus': True}}
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            page.route('**/api/house/state*', lambda r: r.fulfill(content_type='application/json', body=json.dumps(payload)))
            def light(value):
                page.locator('#house-compare-light').evaluate('''(el, value) => {
                    el.value=value; el.dispatchEvent(new Event('change'));
                }''', value)
            def exterior(value):
                page.wait_for_function('''value => {
                    const el=document.getElementById('house-exterior');
                    const imgs=[document.getElementById('exterior-photo'), ...el.querySelectorAll('img[data-src]')];
                    return el.dataset.light===value && imgs.every(i=>i.complete && i.naturalWidth &&
                        i.getAttribute('src')===i.dataset[value==='night'?'srcNight':'src']);
                }''', arg=value)
            def bay(value):
                page.wait_for_function('''value => {
                    const room=document.getElementById('hybrid-garage');
                    const parking=room.dataset.occupied==='true' ? (room.dataset.rightOccupied==='true'?'both':'left')
                        : (room.dataset.rightOccupied==='true'?'right':'empty');
                    const images=[...document.querySelectorAll('#garage-images img')];
                    return room.dataset.light===value && room.dataset.parking===parking && images.length===1 &&
                        images.every(i=>i.complete && i.naturalWidth &&
                            i.getAttribute('src')===i.dataset[parking+(value==='night'?'Night':'')] &&
                            getComputedStyle(i).clipPath==='none' && getComputedStyle(i).maskImage==='none');
                }''', arg=value)
            def cabin(stem, value):
                page.wait_for_function('''([stem,value]) => {
                    const img=document.getElementById('garage-cluster-photo');
                    return !document.getElementById('garage-dashboard').hidden && img.complete && img.naturalWidth &&
                        img.src.includes('/'+stem+(value==='night'?'-night':'')+'.png') &&
                        document.getElementById('garage-dashboard').dataset.light===value;
                }''', arg=[stem, value])
            def refresh():
                page.evaluate('async()=>{await chfHouseRefresh();await chfHouseRefresh()}')
            page.goto(served.url('house?light=night'))
            page.wait_for_function('window.chfExteriorProbe?.().ready')
            exterior('night')
            resources = page.evaluate('performance.getEntriesByType("resource").map(r=>r.name)')
            assert not any('/exterior-model-full-block-empty.png' in url for url in resources), 'No daytime startup flash'
            page.screenshot(path=str(OUT/'exterior-night.png'))
            assert page.locator('.exterior-vehicle-art').evaluate("el=>getComputedStyle(el).filter") != 'none'
            # Night remains consistent through rooms, garage and returning outside.
            for room in ('living', 'kitchen', 'mudroom', 'garage'):
                page.evaluate('(room)=>chfHybridGo(room)', room)
                page.wait_for_function('(room)=>chfHouseMode()===room', arg=room)
                if room == 'garage':
                    bay('night')
                    page.screenshot(path=str(OUT/'garage-night.png'))
                page.evaluate('chfHybridHome()')
                exterior('night')
            # Every parking combination and windshield background in both lighting modes.
            page.set_viewport_size({'width': 2470, 'height': 1236})
            for value in ('day', 'night'):
                light(value); exterior(value)
                for left, right in itertools.product((False, True), repeat=2):
                    payload['garage']['cars'][0]['present'] = left
                    payload['garage']['cars'][1]['present'] = right
                    refresh(); exterior(value)
                    assert page.locator('.exterior-garage-car').count() == int(left)+int(right)
                    page.evaluate('chfHybridGo("garage")'); bay(value)
                    parking = 'both' if left and right else 'left' if left else 'right' if right else 'empty'
                    page.screenshot(path=str(OUT/('garage-'+parking+'-'+value+'.png')))
                    page.evaluate('chfHybridHome()')
                    page.evaluate('chfVehicleCluster("murano")')
                    stem = 'cluster-murano-' + ('driveway' if left and right else 'left' if left else 'right' if right else 'empty')
                    cabin(stem, value); bay(value)
                    assert page.locator('#cluster-energy').inner_text() == '43%'
                    page.screenshot(path=str(OUT/(stem+'-'+value+'.png')))
                    page.locator('#garage-dashboard-back').click()
                    page.wait_for_function('chfHouseMode()==="exterior"')
                for key, stem, level in (('ev', 'cluster-ev9-home', '76%'), ('gls', 'cluster-gls-home', '58%')):
                    page.evaluate('(key)=>chfVehicleCluster(key)', key)
                    cabin(stem, value)
                    assert page.locator('#cluster-energy').inner_text() == level
                    opposite = 'night' if value == 'day' else 'day'
                    light(opposite); cabin(stem, opposite); bay(opposite)
                    light(value); cabin(stem, value)
                    page.screenshot(path=str(OUT/(stem+'-'+value+'.png')))
                    page.locator('#garage-dashboard-back').click()
                    exterior(value)
            # Automatic sunset while inside a car, then navigation back outside.
            payload['window']['next_sun_change'] = (datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat()
            refresh(); light('auto'); exterior('day')
            page.evaluate('chfVehicleCluster("ev")'); cabin('cluster-ev9-home', 'day')
            cabin('cluster-ev9-home', 'night'); bay('night')
            page.locator('#garage-dashboard-back').click(); exterior('night')
            # Phone layout retains the same artwork and live instruments.
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(OUT/'exterior-night-phone.png'))
            page.evaluate('chfHybridGo("garage")')
            payload['garage']['cars'][0]['present'] = False
            refresh(); bay('night')
            assert page.locator('#garage-car').is_hidden()
            assert page.locator('#garage-car-right').is_visible()
            page.screenshot(path=str(OUT/'garage-right-night-phone.png'))
            payload['garage']['cars'][0]['present'] = True
            refresh(); bay('night')
            page.evaluate('chfHybridHome()')
            page.evaluate('chfVehicleCluster("murano")'); cabin('cluster-murano-driveway', 'night')
            assert page.locator('#cluster-energy').inner_text() == '43%'
            page.screenshot(path=str(OUT/'cluster-night-phone.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not served.errors(), served.errors()
        # Hold night responses: a later day choice must win, even after night finishes.
        with served.browser(reduced_motion='reduce') as page:
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            page.route('**/api/house/state*', lambda r: r.fulfill(content_type='application/json', body=json.dumps(payload)))
            held = []
            page.goto(served.url('house?light=day'))
            exterior('day')
            page.evaluate('chfVehicleCluster("ev")'); cabin('cluster-ev9-home', 'day')
            page.route('**/house_hybrid/*-night.png*', lambda r: held.append(r))
            light('night')
            page.wait_for_timeout(150)
            assert held
            light('day'); cabin('cluster-ev9-home', 'day'); exterior('day')
            page.unroute('**/house_hybrid/*-night.png*')
            for route in held:
                route.continue_()
            page.wait_for_load_state('networkidle')
            exterior('day'); bay('day'); cabin('cluster-ev9-home', 'day')
            assert not served.errors(), served.errors()
        print('PASS: hybrid night startup, room navigation, all parking/cabin variants, live lighting, sunset, phone, stale loads')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
