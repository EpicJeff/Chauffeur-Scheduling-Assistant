"""Current weather is readable outside and in the kitchen; hybrid scenery follows it."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from test_house_hybrid_live import seed, live_app, ha_api, storage
from test_house_kitchen_live import surface_fixtures

OUT = Path(__file__).resolve().parents[2] / 'scratch/exterior-weather'


def main():
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    def setup():
        seed()
        storage.patch_settings({'house_hybrid_enabled': True, 'panel_idle_return_seconds': 0})
    served = live_app(setup)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {'window': {'cond': 'sunny', 'temp': 72, 'temp_unit': '°F', 'night': False},
               'garage': {'cars': [
                   {'id': 'ev', 'name': 'Family EV', 'house_artwork': 'ev9-white-black-roof', 'present': False},
                   {'id': 'gls', 'name': 'Big SUV', 'house_artwork': 'gls450-white-23', 'present': True},
                   {'id': 'murano', 'name': 'Commuter', 'house_artwork': 'murano-white', 'present': True}]}}
    start = datetime.now(timezone.utc)+timedelta(hours=1)
    hero = {'all_done': False, 'next': {'title': 'Soccer practice', 'at': start.strftime('%H:%M'),
            'driver': 'Parent', 'start': start.isoformat(), 'end': (start+timedelta(hours=1)).isoformat()}}
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            page.route('**/api/house/state*', lambda r: r.fulfill(json=payload))
            page.route('**/api/home_board?widgets=hero', lambda r: r.fulfill(json={'hero': hero}))
            surface_fixtures(page)
            page.goto(served.url('house?light=day'))
            page.wait_for_function('window.chfExteriorProbe?.().ready')
            reading = page.locator('#house-glance .house-current-weather')
            page.wait_for_function('document.querySelector("#house-glance .weather-temperature").textContent==="72°F"')
            assert reading.is_visible()
            assert reading.locator('.weather-condition').inner_text() == 'Sunny'
            def refresh():
                page.evaluate('async()=>{await chfHouseRefresh();await chfHouseRefresh()}')
                page.wait_for_function('''()=>{
                    const scene=document.getElementById('house-exterior');
                    return scene.dataset.weather===scene.dataset.weatherRequested &&
                        [...scene.querySelectorAll('img[data-src]')].every(img=>img.complete && img.naturalWidth &&
                        img.getAttribute('src')===img.dataset[scene.dataset.light==='night'?'srcNight':'src']);
                }''')
            def light(value):
                page.locator('#house-compare-light').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("change"))}', value)
                page.wait_for_function('(value)=>document.getElementById("house-exterior").dataset.light===value', arg=value)
            for value in ('day', 'night'):
                light(value)
                for cond, kind in [('sunny','clear'),('cloudy','cloudy'),('rainy','rain'),('snowy','snow'),('fog','fog'),('unavailable','unknown')]:
                    payload['window']['cond'] = cond
                    refresh()
                    assert page.locator('#house-exterior').get_attribute('data-weather') == kind
                    assert page.locator('#exterior-weather').count() == 0, 'Use generated scenes, not procedural overlays'
                    assert page.locator('#exterior-pictures').evaluate('el=>getComputedStyle(el).filter') == 'none'
                    if kind not in ('clear','unknown'):
                        assert 'exterior-weather-'+kind+'-'+value+'.png' in page.locator('#exterior-photo').get_attribute('src')
                        assert 'exterior-weather-vehicles-'+kind+'-'+value+'.png' in page.locator('.exterior-scene-patch').get_attribute('src')
                        assert 'exterior-weather-vehicles-'+kind+'-'+value+'.png' in page.locator('.exterior-garage-layer img').get_attribute('src')
                    page.screenshot(path=str(OUT/(kind+'-'+value+'.png')))
                    plane=page.locator('#exterior-traffic').bounding_box()
                    page.screenshot(path=str(OUT/('vehicles-'+kind+'-'+value+'.png')), clip={
                        'x':plane['x']+plane['width']*.44, 'y':plane['y']+plane['height']*.59,
                        'width':plane['width']*.30, 'height':plane['height']*.30})
            # Missing readings must clear the previous temperature, while 0 and negatives are real.
            assert reading.locator('.weather-temperature').inner_text() == '—'
            assert reading.locator('.weather-condition').inner_text() == 'Weather unavailable'
            for temp, expected in [(0,'0°C'),(-4.5,'-4°C'),(None,'—')]:
                payload['window'].update(cond='snowy', temp=temp, temp_unit='°C')
                refresh()
                assert reading.locator('.weather-temperature').inner_text() == expected
            payload['window'].update(cond='rainy', temp=18, temp_unit='°C')
            refresh()
            page.emulate_media(reduced_motion='no-preference')
            # The weather cannot steal vehicle clicks.
            page.locator('[data-vehicle=driveway-car]').click()
            page.wait_for_selector('#garage-dashboard:visible')
            page.locator('#garage-dashboard-back').click()
            page.wait_for_selector('#house-glance:visible')
            # The same current reading appears above the kitchen forecast.
            page.evaluate('async()=>{await chfHybridGo("kitchen");chfKitchenVisit("weather")}')
            current = page.locator('#house-life .house-current-weather')
            current.wait_for(state='visible')
            assert current.locator('.weather-temperature').inner_text() == '18°C'
            assert current.locator('.weather-condition').inner_text() == 'Rain'
            page.wait_for_selector('.house-weather-days')
            page.screenshot(path=str(OUT/'kitchen-current-weather.png'))
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_function('''()=>{const days=document.querySelectorAll('.house-weather-days>div');return days[days.length-1].getBoundingClientRect().bottom<=document.querySelector('#kitchen-controls .house-life-body').getBoundingClientRect().bottom+1;}''')
            page.screenshot(path=str(OUT/'kitchen-current-weather-phone.png'))
            page.evaluate('chfHybridHome()')
            page.wait_for_selector('#house-glance:visible')
            page.emulate_media(reduced_motion='reduce')
            for width, height in ((1400,900),(390,844),(844,390)):
                page.set_viewport_size({'width':width,'height':height})
                page.wait_for_selector('#house-glance .glance-next:visible')
                clock = page.locator('#house-glance .glance-clock').bounding_box()
                card = page.locator('#house-glance .glance-next').bounding_box()
                box = reading.bounding_box()
                assert 0 <= box['x'] and box['x']+box['width'] <= width
                assert 0 <= box['y'] and box['y']+box['height'] <= height
                assert (clock['x']+clock['width'] <= card['x'] or card['x']+card['width'] <= clock['x'] or
                        clock['y']+clock['height'] <= card['y'] or card['y']+card['height'] <= clock['y']), (clock,card)
                if width == 390:
                    for room in ('living','kitchen'):
                        marker = page.locator('#house-hints [data-room='+room+']').bounding_box()
                        assert card['y']+card['height'] <= marker['y'], (card,marker)
                page.screenshot(path=str(OUT/f'weather-clock-{width}.png'))
            assert not served.errors(), served.errors()
            # Delayed rain artwork must never overwrite a later clear-weather update.
            payload['window']['cond'] = 'sunny'; refresh()
            held = []
            page.route('**/house_hybrid/*rain-night.png*', lambda r: held.append(r))
            # Clear the loader cache by reloading before holding the first rain request.
            page.reload(); page.wait_for_function('window.chfExteriorProbe?.().ready')
            light('night')
            payload['window']['cond'] = 'rainy'
            page.evaluate('async()=>{await chfHouseRefresh();await chfHouseRefresh()}')
            page.wait_for_timeout(150)
            assert held
            payload['window']['cond'] = 'sunny'; refresh()
            page.unroute('**/house_hybrid/*rain-night.png*')
            for route in held: route.continue_()
            page.wait_for_load_state('networkidle')
            assert page.locator('#house-exterior').get_attribute('data-weather') == 'clear'
            assert 'exterior-model-full-block-empty-night.png' in page.locator('#exterior-photo').get_attribute('src')
            assert not served.errors(), served.errors()
            print('PASS current weather, units, missing data, generated day/night scenes, stale loads, navigation, kitchen and clock/hero layouts')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
