"""Saved personal vehicle assignments, live parking, and three real clusters."""
import itertools
from pathlib import Path
from test_house_hybrid_live import live_app, ha_api, storage
from models.schemas import Car

OUT = Path(__file__).resolve().parents[2] / 'scratch/personal-vehicles'
PROFILES = {'ev': 'ev9-white-black-roof', 'gls': 'gls450-white-23', 'murano': 'murano-white'}
NAMES = {'ev': 'Family EV', 'gls': 'Big SUV', 'murano': 'Commuter'}
states = {}


def seed():
    storage.add_driver({'id': 'owner', 'name': 'Owner'})
    storage.patch_settings({'house_hybrid_enabled': True, 'panel_idle_return_seconds': 0})
    for key in PROFILES:
        storage.add_car(Car(id=key, name=NAMES[key], body_type='suv', allowed_driver_ids=['owner'],
                            ha_device_tracker='device_tracker.'+key,
                            ha_battery_entity='sensor.ev_energy' if key == 'ev' else None,
                            ha_fuel_entity='sensor.'+key+'_energy' if key != 'ev' else None,
                            ha_range_entity='sensor.'+key+'_range').model_dump())
        states['device_tracker.'+key] = {'state': 'home'}
        states['sensor.'+key+'_energy'] = {'state': {'ev': '76', 'gls': '58', 'murano': '43'}[key]}
        states['sensor.'+key+'_range'] = {'state': {'ev': '242', 'gls': '318', 'murano': '190'}[key], 'attributes': {'unit_of_measurement': 'mi'}}


def main():
    import main as app_module
    app_module.refresh_schedule_logic = lambda *a, **kw: None
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda entity, *a, **kw: states.get(entity)
    OUT.mkdir(parents=True, exist_ok=True)
    served = live_app(seed)
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.set_default_timeout(30000)
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            def mode(value):
                page.wait_for_function('(m)=>window.chfHouseMode?.()===m', arg=value)
            def refresh():
                # Drain any poll started before the fixture changed, then fetch fresh state.
                page.evaluate('async()=>{await chfHouseRefresh();await chfHouseRefresh()}')
            def outside():
                page.evaluate('chfHybridHome()'); mode('exterior')
            def open_cluster(key):
                selector = '[data-vehicle=driveway-car]' if key == 'murano' else '.exterior-garage-car[data-vehicle='+key+']'
                page.locator(selector).click()
                page.wait_for_selector('#garage-dashboard:visible')
                assert page.locator('#garage-dashboard').get_attribute('data-vehicle') == key
                assert page.locator('#cluster-vehicle').inner_text() == NAMES[key]
            # Real saved fleet with no assignment must not inherit a demo car.
            page.goto(served.url('house?scene=garage'))
            mode('garage')
            assert page.locator('#garage-car').is_hidden()
            assert page.locator('#garage-car-right').is_hidden()
            # Assign through the actual config UI and check persistence/API.
            page.goto(served.url('config'))
            page.wait_for_function('window.Alpine && Alpine.$data(document.body).cars.length===3')
            for key, profile in PROFILES.items():
                page.evaluate('(id)=>{const app=Alpine.$data(document.body);app.activeTab="family";app.editCar(app.cars.find(c=>c.id===id))}', key)
                page.get_by_label('House vehicle appearance', exact=True).select_option(profile)
                page.evaluate('async()=>{await Alpine.$data(document.body).submitCar()}')
                saved = next(c for c in page.request.get(served.url('api/cars')).json() if c['id'] == key)
                assert saved['house_artwork'] == profile
                page.evaluate('(car)=>Alpine.$data(document.body).editCar(car)', saved)
                assert page.get_by_label('House vehicle appearance', exact=True).input_value() == profile
            feed = page.request.get(served.url('api/house/state')).json()['garage']['cars']
            assert {c['id']: c['house_artwork'] for c in feed} == PROFILES
            # Preview-only URL overrides must have no effect on the live page.
            page.goto(served.url('house?garage_car=gls&driveway_car=ev&traffic_demo=1'))
            page.wait_for_function('window.chfExteriorProbe?.().ready')
            for selector in ('#exterior-room-shortcuts', '#exterior-traffic-shortcuts', '#exterior-layer-controls'):
                assert page.locator(selector).is_hidden(), selector
            assert page.evaluate('typeof THREE') == 'undefined'
            page.screenshot(path=str(OUT/'live-exterior.png'))
            for left, right, drive in itertools.product((False, True), repeat=3):
                for key, home in zip(PROFILES, (left, right, drive)):
                    states['device_tracker.'+key]['state'] = 'home' if home else 'not_home'
                refresh()
                assert page.locator('.exterior-garage-car[data-bay=left]').count() == int(left)
                assert page.locator('.exterior-garage-car[data-bay=right]').count() == int(right)
                assert page.locator('[data-vehicle=driveway-car]').count() == int(drive)
                page.evaluate('async()=>{await chfHybridGo("garage")}'); mode('garage')
                assert page.locator('#hybrid-garage').get_attribute('data-occupied') == str(left).lower()
                assert page.locator('#hybrid-garage').get_attribute('data-right-occupied') == str(right).lower()
                assert page.locator('#garage-car').is_visible() == left
                assert page.locator('#garage-car-right').is_visible() == right
                assert page.locator('#garage-presence').is_hidden()
                if left and right:
                    page.screenshot(path=str(OUT/'live-garage.png'))
                outside()
            # All three clusters use the correct profile and that saved car's telemetry.
            for key, energy in (('ev', '76%'), ('gls', '58%'), ('murano', '43%')):
                open_cluster(key)
                assert page.locator('#garage-dashboard').get_attribute('data-profile') == PROFILES[key]
                assert page.locator('#cluster-energy').inner_text() == energy
                assert page.locator('#cluster-energy-label').inner_text() == ('BATTERY' if key == 'ev' else 'FUEL')
                assert page.locator('#cluster-range').inner_text() == {'ev':'242','gls':'318','murano':'190'}[key]
                page.screenshot(path=str(OUT/(key+'-cluster.png')))
                page.set_viewport_size({'width':390, 'height':844})
                box = page.locator('#garage-cluster-ui').bounding_box()
                assert box['x'] >= 0 and box['x']+box['width'] <= 390, box
                page.screenshot(path=str(OUT/(key+'-cluster-phone.png')))
                page.set_viewport_size({'width':1400, 'height':1000})
                page.locator('#garage-dashboard-back').click(); mode('exterior')
            # Both in-garage cars open their own cluster and return to the bay.
            page.evaluate('async()=>{await chfHybridGo("garage")}'); mode('garage')
            for selector, key in (('#garage-car','ev'), ('#garage-car-right','gls')):
                page.locator(selector).click(); page.wait_for_selector('#garage-dashboard:visible')
                assert page.locator('#garage-dashboard').get_attribute('data-vehicle') == key
                page.locator('#garage-dashboard-back').click(); mode('garage')
            outside(); open_cluster('gls')
            states['sensor.gls_energy']['state'] = 'unavailable'
            states['sensor.gls_range']['state'] = 'unavailable'
            refresh()
            assert page.locator('#cluster-energy').inner_text() == '\u2014'
            assert page.locator('#cluster-range').inner_text() == '\u2014'
            page.locator('#garage-dashboard-back').click(); mode('exterior')
            # Driveway windshield shows the same arriving/leaving cars as the House.
            open_cluster('murano')
            for left, right, file in ((False,True,'right'),(False,False,'empty'),(True,False,'left'),(True,True,'driveway')):
                states['device_tracker.ev']['state'] = 'home' if left else 'not_home'
                states['device_tracker.gls']['state'] = 'home' if right else 'not_home'
                refresh()
                page.wait_for_function('(file)=>document.getElementById("garage-cluster-photo").getAttribute("src").includes("cluster-murano-"+file+(chfHouseNight?"-night":"")+".png")', arg=file)
            states['device_tracker.murano']['state'] = 'not_home'; refresh(); mode('exterior')
            assert page.locator('#garage-dashboard').is_hidden()
            # Missing tracker data must not manufacture a home vehicle.
            states['device_tracker.ev']['state'] = 'unavailable'; refresh()
            assert page.locator('.exterior-garage-car[data-bay=left]').count() == 0
            assert not served.errors(), served.errors()
            print('PASS saved assignments, clean live UI, eight presence combinations, three clusters, matching windshield states, phone layout and unavailable telemetry')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
