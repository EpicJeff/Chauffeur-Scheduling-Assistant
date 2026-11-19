"""Weather ground history: real routes, HA events and drawer, without HA or a browser."""
import asyncio
import importlib
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_weather_')
os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from services import auth, ha_api, ha_events, settings_registry, storage, twin_weather_state as weather
import main


def sample(condition='sunny', temperature=0, **extra):
    return dict(condition=condition, temperature=temperature, humidity=50, cloud_cover=1,
                sun_altitude=-1, rate={'snowy': .5, 'snowy-rainy': .5, 'rainy': .45}.get(condition, 0), **extra)


class ModelTests(unittest.TestCase):
    def season(self, record, now, temp=20, grass='cool', lat=40, rain=False, usable=True):
        return weather.advance_season(record, sample('rainy' if rain else 'sunny', temp), now,
                                      grass, lat, usable)

    def test_hourly_history_average_bounds_missing_and_old_records(self):
        start = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
        record = None
        for hour in range(300):
            record = self.season(record, start + hour * 3600, hour % 24, rain=True)
            if hour == 70:
                self.assertEqual(weather.season_payload(record, 'cool', True)[1]['avg_temp_c'], None)
            if hour == 71:
                self.assertEqual(weather.season_payload(record, 'cool', True)[1]['history_days'], 3)
            self.assertLessEqual(len(record['temperature_hours']), 240)
            self.assertLessEqual(len(record['rain_hours']), 240)
        lawn, season = weather.season_payload(record, 'cool', True)
        self.assertEqual(lawn['source'], 'history')
        self.assertEqual(season, {'avg_temp_c': 11.5, 'history_days': 10})
        # Repeated reads/events in one hour do not inflate the average or rain count.
        again = self.season(record, start + 299 * 3600 + 600, 11)
        self.assertEqual(len(again['temperature_hours']), 240)
        self.assertEqual(len(again['rain_hours']), 240)
        for old in (None, {'snow_cm': 0, 'wetness': 0, 'updated': start},
                    dict(record, temperature_hours='broken'), dict(record, season_updated=start),
                    dict(record, lawn_target='0'), dict(record, lawn_dormancy=True),
                    dict(record, season_updated=str(record['season_updated'])),
                    dict(record, temperature_hours=[[int((start + 299 * 3600) // 3600), '10']])):
            fresh = self.season(old, start + 300 * 3600)
            self.assertEqual(len(fresh['temperature_hours']), 1)
        missing = self.season(record, start + 300 * 3600, None)
        self.assertEqual(len(missing['temperature_hours']), 239)
        unavailable = self.season(record, start + 300 * 3600, usable=False)
        self.assertEqual(weather.season_payload(unavailable, 'cool', False)[0]['source'], 'calendar')

    def test_calendar_latitude_and_hemisphere(self):
        for lat, cold, summer in [(40, 1, 7), (-35, 7, 1), (70, 1, 7)]:
            for grass, target in [('warm', 1), ('cool', .3)]:
                t = datetime(2026, cold, 15, tzinfo=timezone.utc).timestamp()
                record = self.season(None, t, None, grass, lat, usable=False)
                self.assertEqual(record['lawn_target'], target)
                self.assertEqual(record['lawn_dormancy'], target)
                self.assertEqual(weather.season_payload(record, grass, False)[0]['source'], 'calendar')
            t = datetime(2026, summer, 15, tzinfo=timezone.utc).timestamp()
            self.assertEqual(self.season(None, t, None, 'warm', lat)['lawn_target'], 0)
        t = datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.season(None, t, None, 'warm', 5)['lawn_target'], 0)

    def test_full_year_hourly_targets_rate_limit_and_both_hemispheres(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        for lat in (40, -35):
            for grass in ('warm', 'cool'):
                record = None
                seen = set()
                for hour in range(365 * 24):
                    day = hour / 24
                    local_day = (day + (182 if lat < 0 else 0)) % 365
                    # Seasonal sinusoid plus reproducible daily/hourly noise.
                    temp = 15 + 19 * math.cos(2 * math.pi * (local_day - 200) / 365) + .6 * math.sin(hour * 1.7)
                    if 190 <= local_day < 215: temp = 34 + .3 * math.sin(hour)
                    if 275 <= local_day < 278: temp = -4  # autumn cold snap
                    old = record
                    record = self.season(record, start + hour * 3600, temp, grass, lat)
                    if old:
                        self.assertLessEqual(abs(record['lawn_dormancy'] - old['lawn_dormancy']), 1 / (14 * 24) + 1e-12)
                    lawn, season = weather.season_payload(record, grass, True)
                    avg = season['avg_temp_c']
                    if avg is not None:
                        if grass == 'cool':
                            target = .6 if avg >= 29.4 else .3 if avg < 0 else 0
                            self.assertEqual(record['lawn_target'], target)
                        elif avg > 18.3:
                            self.assertEqual(record['lawn_target'], 0)
                        elif avg < 12.8 and record['frost_cycle'] == weather.frost_cycle(start + hour * 3600, lat):
                            self.assertEqual(record['lawn_target'], 1)
                        seen.add(record['lawn_target'])
                    self.assertLessEqual(len(record['temperature_hours']), 240)
                self.assertTrue(({0, 1} if grass == 'warm' else {0, .3, .6}) <= seen)

    def test_first_frost_hysteresis_rain_threshold_and_two_week_transition(self):
        for lat, month in [(40, 8), (-35, 2)]:
            start = datetime(2026, month, 1, tzinfo=timezone.utc).timestamp()
            record = None
            for hour in range(100): record = self.season(record, start + hour * 3600, 10, 'warm', lat)
            self.assertEqual(record['lawn_target'], 0, 'cool autumn alone is not first frost')
            record = self.season(record, start + 100 * 3600, 0, 'warm', lat)
            self.assertEqual(record['lawn_target'], 1)
            original = record['lawn_dormancy']
            for hour in range(101, 101 + 14 * 24):
                record = self.season(record, start + hour * 3600, 10, 'warm', lat)
            self.assertAlmostEqual(record['lawn_dormancy'], 1)
            self.assertLess(original, 1)
            for hour in range(437, 437 + 240): record = self.season(record, start + hour * 3600, 15, 'warm', lat)
            self.assertEqual(record['lawn_target'], 1, 'hold between thresholds')
            for hour in range(677, 677 + 240): record = self.season(record, start + hour * 3600, 20, 'warm', lat)
            self.assertEqual(record['lawn_target'], 0)
        start = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
        record = None
        for hour in range(100): record = self.season(record, start + hour * 3600, 32, rain=hour < 5)
        self.assertEqual(record['lawn_target'], .6)
        record = self.season(record, start + 100 * 3600, 32, rain=True)
        self.assertEqual(record['lawn_target'], 0, 'six rain hours remove heat dormancy')
        stressed = dict(record, lawn_target=.6, temperature_hours=[[h, 15] for h, _ in record['temperature_hours']])
        changed = self.season(stressed, start + 100 * 3600, 15, 'warm')
        self.assertEqual(changed['lawn_target'], 0, 'warm grass does not inherit cool grass stress')

    def test_frost_resets_at_each_hemispheres_autumn_boundary(self):
        for lat, month in [(40, 8), (-35, 2)]:
            boundary = datetime(2026, month, 1, tzinfo=timezone.utc).timestamp()
            record = self.season(None, boundary - 3600, 0, 'warm', lat)
            self.assertIsNotNone(record['frost_cycle'])
            record = self.season(record, boundary, 10, 'warm', lat)
            self.assertIsNone(record['frost_cycle'], 'last autumn frost cannot trigger this autumn')
            for hour in range(1, 100): record = self.season(record, boundary + hour * 3600, 10, 'warm', lat)
            self.assertEqual(record['lawn_target'], 0)
            record = self.season(record, boundary + 100 * 3600, 0, 'warm', lat)
            self.assertEqual(record['lawn_target'], 1)

    def test_snow_mix_melt_threshold_and_drying_rates(self):
        bare = weather.advance(None, sample('snowy'), 10000)
        snow = weather.advance(bare, sample('snowy'), 10000 + 7200)
        self.assertAlmostEqual(snow['snow_cm'], 2.5)
        mix = weather.advance(bare, sample('snowy-rainy'), 10000 + 7200)
        self.assertAlmostEqual(mix['snow_cm'], 1)
        self.assertEqual(mix['wetness'], 1)
        warm = sample(temperature=5)
        melted = weather.advance(snow, warm, snow['updated'] + 3600)
        self.assertAlmostEqual(melted['snow_cm'], .5)
        self.assertEqual(melted['wetness'], 1)
        self.assertEqual(weather.advance(melted, warm, melted['updated'] + 600)['snow_cm'], 0)
        sun = dict(warm, sun_altitude=.5, cloud_cover=.25)
        self.assertAlmostEqual(weather.advance(snow, sun, snow['updated'] + 1800)['snow_cm'], 1.2)
        for temp, humidity, altitude, tau in [(20, 50, -1, 60), (0, 50, -1, 180),
                                               (10, 50, -1, 120), (20, 95, -1, 120), (20, 50, 1, 30)]:
            wet = dict(bare, wetness=1, last_rain=bare['updated'])
            dry = weather.advance(wet, dict(sample(temperature=temp), humidity=humidity, sun_altitude=altitude),
                                  wet['updated'] + tau * 60)
            self.assertAlmostEqual(dry['wetness'], math.exp(-1))
        tiny = bare
        for i in range(1, 13):
            tiny = weather.advance(tiny, sample('snowy-rainy'), 10000 + i * 600)
        self.assertAlmostEqual(tiny['snow_cm'], 1)
        self.assertEqual(weather.advance(bare, sample('snowy', 2), 13600)['snow_cm'], 0)

    def test_puddle_rain_window_and_record_recovery(self):
        for corrupt in (None, [], 'bad', {}, {'updated': float('nan')},
                        {'updated': 1, 'snow_cm': 2, 'wetness': 1}):
            record = weather.advance(corrupt, sample(), 1000000)
            self.assertEqual((record['snow_cm'], record['wetness']), (0, 0))
        record = weather.advance(None, sample('rainy'), 10000)
        self.assertGreater(weather.puddles(record, 10000), 0)
        self.assertEqual(weather.puddles(record, 10000 + 10801), 0)
        self.assertEqual(weather.puddles(dict(record, wetness=.6), 10000), 0)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.settings_table, storage.app_state_table, storage.members_table,
                      storage.member_tokens_table, storage.trusted_devices_table):
            table.truncate()
        storage.add_member({'id': 'parent', 'name': 'Parent', 'role': 'parent'})
        self.parent = {'X-Member-Token': storage.create_member_token('parent', proof='password')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('wall', 'Wall', 'parent')}
        self.client = TestClient(main.app)
        storage.patch_settings({'service_local_grace': False})
        self.rows = []
        weather._forecast_cache.clear()
        for target, value in [('get_states', lambda: self.rows), ('states_unreachable', lambda: False),
                              ('get_weather_forecast', lambda *a, **k: [])]:
            p = patch.object(ha_api, target, side_effect=value); p.start(); self.addCleanup(p.stop)
        p = patch('services.twin_site.site', return_value={'lat': 40, 'lon': -75})
        p.start(); self.addCleanup(p.stop)

    def entity(self, condition='snowy', **attrs):
        return {'entity_id': 'weather.home', 'state': condition, 'attributes': attrs,
                'last_updated': '2020-01-01T00:00:00Z'}

    def test_season_delivery_restart_grass_save_and_unknown_latitude(self):
        start = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
        self.rows = [self.entity('sunny', temperature=32)]
        for hour in range(80):
            body = weather.update(now=start + hour * 3600)
        self.assertEqual(body['season'], {'avg_temp_c': 32, 'history_days': 80 / 24})
        self.assertEqual(body['lawn']['source'], 'history')
        self.assertEqual(storage.get_app_state(weather.KEY)['lawn_target'], .6)
        before = storage.get_app_state(weather.KEY)
        importlib.reload(weather)
        with patch.object(weather.time, 'time', return_value=start + 79 * 3600), patch.object(auth, 'enforcing', return_value=True):
            body = self.client.get('/api/house/twin/weather-state', headers=self.panel).json()
            self.assertEqual(body['season']['history_days'], 80 / 24)
            self.assertAlmostEqual(body['lawn']['dormancy'], before['lawn_dormancy'])
            with patch.object(storage, 'mark_all_daily_schedules_dirty') as dirty:
                response = self.client.put('/api/house/twin/weather-sources', headers=self.parent,
                                           json={'lawn_grass_type': 'warm'})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['lawn']['grass_type'], 'warm')
                self.assertEqual(storage.get_settings()['lawn_grass_type'], 'warm')
                self.assertEqual(storage.get_app_state(weather.KEY)['lawn_target'], 0, 'save re-evaluates now')
                self.assertEqual(storage.get_app_state(weather.KEY)['temperature_hours'], before['temperature_hours'])
                dirty.assert_not_called()
            for value in ('bad', '', None, 1, [], {}):
                self.assertEqual(self.client.put('/api/house/twin/weather-sources', headers=self.parent,
                                                json={'lawn_grass_type': value}).status_code, 422)
            self.assertIn(self.client.put('/api/house/twin/weather-sources', headers=self.panel,
                                         json={'lawn_grass_type': 'cool'}).status_code, (401, 403))
            with patch('services.twin_site.site', return_value={}):
                source = self.client.get('/api/house/twin/weather-state', headers=self.parent).json()['source']
                self.assertEqual(source['season']['latitude'], 40)
                self.assertEqual(source['season']['latitude_source'], 'fallback: 40 N')
            with patch('services.twin_site.site', return_value={'lat': 40, 'source': 'default'}):
                source = self.client.get('/api/house/twin/weather-state', headers=self.parent).json()['source']
                self.assertEqual(source['season']['latitude_source'], 'fallback: 40 N', 'site already supplies default latitude')
            self.rows = []
            body = self.client.get('/api/house/twin/weather-state', headers=self.parent).json()
            self.assertEqual(body['lawn']['source'], 'calendar')
            self.assertIsNone(body['season']['avg_temp_c'])
            self.assertIn('calendar', body['source']['season']['lawn'])
        self.assertEqual(len(storage.app_state_table.all()), 1)
        from models.schemas import Settings
        self.assertEqual(Settings().lawn_grass_type, 'cool')
        self.assertEqual(Settings(lawn_grass_type='warm').lawn_grass_type, 'warm')

    def test_route_auth_missing_and_source_fallbacks(self):
        url = '/api/house/twin/weather-state'
        self.assertEqual(auth.resolve('GET', url), auth.WALL_OR_SERVICE)
        with patch.object(auth, 'enforcing', return_value=True):
            self.assertIn(self.client.get(url).status_code, (401, 403))
            for headers in (self.parent, self.panel):
                r = self.client.get(url, headers=headers)
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual((body['snow_cm'], body['wetness'], body['puddles']), (0, 0, 0))
                self.assertIsNone(body['source']['entity'])
                self.assertEqual(set(body['source']['missing']), set(weather.QUANTITIES))
        self.rows = [self.entity('rainy')]
        source = self.client.get(url, headers=self.parent).json()['source']
        self.assertIn('temperature', source['missing'])
        self.assertIn('condition', source['fallbacks']['precipitation'])
        self.assertFalse(source['stale'], 'HA can leave an unchanged entity timestamp old for days')
        with patch.object(ha_api, 'states_unreachable', return_value=True):
            body = self.client.get(url, headers=self.parent).json()
            self.assertTrue(body['source']['stale'])
            self.assertEqual(body['wetness'], 0)

    def test_sensors_forecast_units_settings_and_missing(self):
        settings = {'weather_entity': 'weather.home', 'weather_rain_sensor': 'binary_sensor.rain',
                    'weather_temperature_sensor': 'sensor.temp', 'weather_wind_speed_sensor': 'sensor.wind',
                    'weather_wind_direction_sensor': 'sensor.bearing'}
        storage.patch_settings(settings)
        self.rows = [self.entity('rainy', temperature=50, temperature_unit='°F', humidity=95),
                     {'entity_id': 'binary_sensor.rain', 'state': 'off'},
                     {'entity_id': 'sensor.temp', 'state': '32', 'attributes': {'unit_of_measurement': '°F'}},
                     {'entity_id': 'sensor.wind', 'state': '36', 'attributes': {'unit_of_measurement': 'km/h'}},
                     {'entity_id': 'sensor.bearing', 'state': '270'}]
        source = weather.update(now=10000)['source']
        self.assertEqual(source['sensors']['rain']['value'], 0)
        self.assertEqual(source['sensors']['temperature']['value'], 0)
        self.assertEqual(source['sensors']['wind_speed']['value'], 10)
        self.assertEqual(source['sensors']['wind_direction']['value'], 270)
        self.assertNotIn('temperature', source['missing'])
        self.rows[1]['state'] = 'unavailable'
        source = weather.update(now=10600)['source']
        self.assertIsNone(source['sensors']['rain']['value'])
        self.assertIn('weather_rain_sensor', source['missing'])
        with patch.object(ha_api, 'get_weather_forecast', return_value=[
                {'datetime': '1970-01-01T02:00:00Z', 'precipitation': 4}]):
            weather._forecast_cache.clear()
            self.assertEqual(weather.update(now=10000)['source']['values']['rate'], .5)
        self.rows[1].update(state='8', attributes={'unit_of_measurement': 'mm/h'})
        self.assertEqual(weather.update(now=10600)['source']['sensors']['rain']['value'], 1)
        from models.schemas import Settings
        self.assertEqual(Settings(**settings).model_dump(exclude_unset=True), settings)

    def test_persistence_restart_corruption_and_no_house_growth(self):
        storage.patch_settings({'house_twin': {'rounds': [1], 'current': 1}})
        before = storage.get_settings()['house_twin']
        self.rows = [self.entity(temperature=-2, temperature_unit='°C')]
        weather.update(now=10000)
        weather.update(now=13600)
        importlib.reload(weather)
        body = weather.update(now=17200)
        self.assertAlmostEqual(body['snow_cm'], 2.5)
        self.assertEqual(storage.get_settings()['house_twin'], before)
        self.assertEqual(len(storage.app_state_table.all()), 1)
        storage.set_app_state(weather.KEY, {'snow_cm': 'broken'})
        self.assertEqual(weather.update(now=17800)['snow_cm'], 0)
        self.rows = []
        self.assertEqual(weather.update(now=18400)['snow_cm'], 0)
        self.rows = [self.entity(temperature=-2)]
        for corrupt in ({'snow_cm': '2', 'wetness': 1, 'updated': 18400},
                        {'snow_cm': 2, 'wetness': 1, 'updated': 18400, 'forcing': {'rate': 'bad'}}):
            storage.set_app_state(weather.KEY, corrupt)
            self.assertEqual(weather.update(now=19000)['snow_cm'], 0)

    def test_auto_source_uses_same_friendly_name_order_as_glance(self):
        self.rows = [dict(self.entity('sunny', friendly_name='Zulu'), entity_id='weather.z'),
                     dict(self.entity('sunny', friendly_name='Alpha'), entity_id='weather.a')]
        self.assertEqual(weather.update(now=10000)['source']['entity'], 'weather.a')

    def test_changing_a_local_sensor_keeps_existing_ground_history(self):
        self.rows = [self.entity(temperature=-2)]
        weather.update(now=10000)
        before = weather.update(now=13600)['snow_cm']
        storage.patch_settings({'weather_temperature_sensor': 'sensor.local'})
        self.rows.append({'entity_id': 'sensor.local', 'state': '10', 'attributes': {'unit_of_measurement': '°C'}})
        body = weather.update(now=14200)
        self.assertGreater(body['snow_cm'], before)
        self.assertEqual(body['source']['sensors']['temperature']['value'], 10)

    def test_existing_house_stream_includes_optional_local_sensors(self):
        chosen = dict(zip(weather.SENSOR_SETTINGS.values(), ['binary_sensor.rain', 'sensor.wind', 'sensor.bearing', 'sensor.temp']))
        storage.patch_settings(chosen)
        context = ({'buildings': [], 'site': {}}, {'available': True, 'areas': [], 'devices': []})
        with patch.object(main, '_house_ha_context', return_value=context):
            self.assertTrue(set(chosen.values()) <= main._house_stream_entities())
            self.assertFalse(set(chosen.values()) & main._house_stream_entities('kitchen'))
        self.assertIn('weather_settings', main._twin_modules())

    def test_transition_integrates_previous_condition(self):
        self.rows = [self.entity(temperature=-2)]
        weather.update(now=10000)
        self.rows = [self.entity('sunny', temperature=10)]
        self.assertAlmostEqual(weather.update(now=13600)['snow_cm'], 1.25)

    def test_light_mix_accumulates_across_ticks_but_no_visible_trace_below_point_two(self):
        self.rows = [self.entity('snowy-rainy', temperature=-2)]
        weather.update(now=10000)
        self.assertEqual(weather.update(now=10600)['snow_cm'], 0)
        self.assertEqual(weather.update(now=11200)['snow_cm'], 0)
        self.assertAlmostEqual(weather.update(now=11800)['snow_cm'], .25)

    def test_source_settings_save_auth_validation_and_no_schedule_or_house_write(self):
        url = '/api/house/twin/weather-sources'
        self.assertEqual(auth.resolve('PUT', url), auth.PARENTS)
        storage.patch_settings({'house_twin': {'rounds': [7]}, 'unrelated': 'kept'})
        with patch.object(auth, 'enforcing', return_value=True), patch.object(storage, 'mark_all_daily_schedules_dirty') as dirty:
            for headers in ({}, self.panel):
                self.assertIn(self.client.put(url, headers=headers, json={'weather_rain_sensor': ''}).status_code, (401, 403))
            response = self.client.put(url, headers=self.parent, json={'weather_rain_sensor': 'binary_sensor.rain'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['source']['sensors']['rain']['entity'], 'binary_sensor.rain')
            for body in ({'weather_entity': 'sensor.bad'}, {'weather_rain_sensor': 'switch.pool'},
                         {'weather_temperature_sensor': 4}, {'house_twin': {}}, {}, {'weather_entity': 'weather.'}):
                self.assertEqual(self.client.put(url, headers=self.parent, json=body).status_code, 422, body)
            self.assertEqual(storage.get_settings()['weather_rain_sensor'], 'binary_sensor.rain')
            dirty.assert_not_called()
        self.assertEqual(storage.get_settings()['house_twin'], {'rounds': [7]})
        self.assertEqual(storage.get_settings()['unrelated'], 'kept')

    def test_weather_drawer_runtime_load_save_refusal_and_disposal(self):
        from twin_editor_dom import PRELUDE, run_node
        code, output = run_node(PRELUDE + r'''
const {mountWeatherSettings}=await import(file('static/twin/weather_settings.js'));
const calls=[],statuses=[],selected=[];
const source={entity:'weather.home',configured_entity:'',missing:['temperature','precipitation'],
 sensors:{rain:{entity:'binary_sensor.saved',state:'off',unit:'',value:0}},
 season:{latitude:40,latitude_source:'fallback: 40 N',lawn:'growing-season calendar by latitude'},
 fallbacks:{temperature:'no melting',precipitation:'condition intensity'}};
const body={snow_cm:2,wetness:.8,puddles:.5,updated:10000,source};
let fail=false,block=false,releases=[];
const api=async(path,init)=>{
 calls.push([path,init]);
 if(block)await new Promise(r=>releases.push(r));
 if(fail)return {ok:false,json:async()=>({detail:'Source refused.'})};
 return {ok:true,json:async()=>path.includes('entities')?[{entity_id:path.includes('binary_sensor')?'binary_sensor.rain':path.includes('domain=weather')?'weather.home':'sensor.temp',name:'Source'}]:body};
};
window.chfSettingsSaving=()=>statuses.push('saving');window.chfSettingsSaved=(...args)=>statuses.push(args);
const mounted=mountWeatherSettings({setWeatherEntity:id=>selected.push(id)},{api});
const save=document.getElementById('twin-weather-save');assert.equal(save.disabled,true);assert.equal(calls.length,0);
await mounted.reload();assert.equal(save.disabled,false);
const rain=document.getElementById('weather_rain_sensor');assert.equal(rain.value,'binary_sensor.saved');
assert.ok(rain.children.some(o=>o.value==='binary_sensor.saved'),'unavailable saved source remains selectable');
assert.match(textOf(document.getElementById('twin-weather-report')),/condition intensity/);
assert.match(textOf(document.getElementById('twin-weather-report')),/fallback: 40 N/);
assert.match(textOf(document.getElementById('twin-weather-report')),/growing-season calendar/);
rain.value='binary_sensor.rain';click(save);await new Promise(r=>setTimeout(r,0));
const saved=calls.find(([path,init])=>init?.method==='PUT');assert.equal(saved[0],'api/house/twin/weather-sources');
assert.equal(JSON.parse(saved[1].body).weather_rain_sensor,'binary_sensor.rain');assert.equal(Object.keys(JSON.parse(saved[1].body)).length,5);
assert.equal(selected.at(-1),'');assert.equal(statuses.at(-1)[0],true);
fail=true;click(save);await new Promise(r=>setTimeout(r,0));assert.equal(statuses.at(-1)[0],false);assert.match(statuses.at(-1)[1],/refused/);
fail=false;block=true;const pending=mounted.reload();mounted.stop();block=false;releases.forEach(r=>r());await pending;
assert.equal(save.disabled,true);const stopped=calls.length;click(save);await new Promise(r=>setTimeout(r,0));assert.equal(calls.length,stopped);
console.log('weather drawer runtime passed');
''', {'root': ROOT.as_posix()})
        self.assertEqual(code, 0, output)

    def test_real_event_hook_and_ten_minute_tick_without_browser(self):
        async def run():
            calls = []
            done = asyncio.Event()
            clock = [10000]
            actual_update = weather.update
            self.rows = [self.entity(temperature=-2)]
            def update(**kwargs):
                calls.append(actual_update(now=clock[0]))
                if len(calls) >= 3: done.set()
                return {}
            with patch.object(weather, 'update', side_effect=update), patch.object(main, 'TWIN_WEATHER_TICK_S', .05):
                job = asyncio.create_task(main.twin_weather_loop())
                try:
                    for _ in range(100):
                        if calls: break
                        await asyncio.sleep(.001)
                    clock[0] += 3600
                    self.rows = [self.entity('rainy', temperature=-2)]
                    ha_events._publish({'entity_id': 'weather.home', 'new_state': self.entity('rainy')})
                    await asyncio.wait_for(done.wait(), 2)
                    self.assertGreaterEqual(len(calls), 3)
                    self.assertAlmostEqual(storage.get_app_state(weather.KEY)['snow_cm'], 1.25)
                    self.assertEqual(storage.get_app_state(weather.KEY)['wetness'], 1)
                    self.assertEqual([t for _, t in storage.get_app_state(weather.KEY)['temperature_hours']], [-2, -2])
                    self.assertEqual(storage.get_app_state(weather.KEY)['lawn_target'], .3)
                finally:
                    job.cancel()
                    try: await job
                    except asyncio.CancelledError: pass
            self.assertFalse(ha_events._subscribers)
        asyncio.run(run())

    def test_registry_drawer_and_solar_python_agrees_with_slice_one(self):
        self.assertEqual(settings_registry.audit(), {'missing': [], 'stale': []})
        from test_settings_drawer import _elements, _render
        keys = list(weather.SENSOR_SETTINGS.values())
        for query in ('', 'panel=true', 'kiosk=true', 'tabs=twin'):
            rows = _elements(_render('/house/twin', query))
            for key in keys:
                self.assertEqual(sum(a.get('id') == key for a, _ in rows), 0 if query else 1)
        from twin_editor_dom import PRELUDE, run_node
        code, output = run_node(PRELUDE + r'''
const {sunPosition}=await import(file('static/twin/sky/ephemeris.js'));
for(const [time,lat,lon,expected] of input.samples)assert.ok(Math.abs(sunPosition(time*1000,lat,lon).altitude-expected)<1e-9);
console.log('solar parity passed');
''', {'root': ROOT.as_posix(), 'samples': [[t, lat, lon, weather.sun_altitude(t, lat, lon)]
       for t, lat, lon in [(1795104000, 40, -75), (1782043200, 65, 20), (1766275200, -35, 145)]]})
        self.assertEqual(code, 0, output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
