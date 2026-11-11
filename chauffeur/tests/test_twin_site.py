"""Exercise the real twin payload and existing placement save with auth on."""
import os
import sys
import tempfile
import traceback
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_real_sun_site_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_twin_ha_routes import Ctx, check
from services import auth, storage, twin_store

READ = '/api/house/twin'
SAVE = '/api/house/editor/place/lot/placement'


def test_cached_site_payload():
    with Ctx() as c, patch.object(storage, 'get_cached_geocode', return_value={'lat': '40.1', 'lon': '-75.2'}):
        c.extra.update(home_location='A home address', timezone='America/New_York')
        response = c.client.get(READ, headers=c.panel)
        check(response.status_code == 200, response.text)
        site = response.json()['site']
        check(site['lat'] == 40.1 and site['lon'] == -75.2 and site['source'] == 'home_location', site)
        check(site['timezone'] == 'America/New_York', site)
        check(c.client.get('/api/house/editor/state', headers=c.mum).json()['site'] == site, 'same editor site')


def test_missing_and_failed_geocode():
    with Ctx() as c:
        for address, cached in [('', None), ('Unknown home', None), ('Broken cache', {'lat': 'NaN', 'lon': 0})]:
            c.extra['home_location'] = address
            with patch.object(storage, 'get_cached_geocode', return_value=cached):
                site = c.client.get(READ, headers=c.panel).json()['site']
                check(site['lat'] == 40 and site['lon'] is None and site['source'] == 'default', site)
        with patch.object(storage, 'get_cached_geocode', side_effect=RuntimeError('offline')):
            check(c.client.get(READ, headers=c.panel).json()['site']['source'] == 'default', 'cache unavailable')


def test_parent_saves_and_reloads_bearing_without_drawings():
    with Ctx() as c:
        response = c.client.put(SAVE, headers=c.mum, json={'front_bearing_deg': 92})
        check(response.status_code == 200, response.text)
        check(response.json()['lot']['front_bearing_deg'] == 92, response.text)
        check(c.client.get(READ, headers=c.panel).json()['site']['front_bearing_deg'] == 92, 'public read')
        check(c.client.get('/api/house/editor/sheets', headers=c.mum).json()['place']['lot']['front_bearing_deg'] == 92, 'editor reload')


def test_child_wall_and_guest_cannot_save():
    with Ctx() as c:
        twin_store.set_front_bearing(180)
        for headers in (c.kid, c.panel, c.visitor):
            response = c.client.put(SAVE, headers=headers, json={'front_bearing_deg': 17})
            check(response.status_code == 403, response.text)
        check(twin_store.place()['lot']['front_bearing_deg'] == 180, 'refusals preserve bearing')
        check(auth.resolve('GET', READ) == auth.WALL_OR_SERVICE, 'site read tier')
        check(auth.resolve('PUT', SAVE) == auth.PARENTS, 'existing save tier')


def test_invalid_bearings_preserve_saved_value():
    with Ctx() as c:
        twin_store.set_front_bearing(180)
        for value in (-1, 360, None, True, '90'):
            response = c.client.put(SAVE, headers=c.mum, json={'front_bearing_deg': value})
            check(response.status_code == 400, (value, response.text))
        check(twin_store.place()['lot']['front_bearing_deg'] == 180, 'invalid input preserves bearing')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok', test.__name__)
        except Exception:
            traceback.print_exc()
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
