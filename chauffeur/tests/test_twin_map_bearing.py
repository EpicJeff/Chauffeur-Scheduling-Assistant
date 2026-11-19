"""Offline map north, persisted override and real auth/worker entry points."""
import contextlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_map_bearing_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_twin_ha_routes import Ctx
from services import auth, house_map as hm, storage, twin_site, twin_store

SAVE = '/api/house/editor/place/lot/placement'
CLEAR = '/api/house/editor/place/lot/bearing/map'


def tiles(turn=0, footprint=True):
    c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    rotate = lambda p: [p[0]*c-p[1]*s, p[0]*s+p[1]*c]
    return {'lines': [[rotate(p) for p in [(-100, 30), (100, 30)]]],
            'buildings': [{'outline': [rotate(p) for p in [(-8,-6),(8,-6),(8,6),(-8,6),(-8,-6)]]}] if footprint else []}


def wait_jobs():
    for job in list(twin_site._jobs.values()):
        job.join(5)
        assert not job.is_alive(), 'bearing job did not finish'


class BearingTests(unittest.TestCase):
    def test_true_metre_footprint_and_rotation(self):
        for turn in (0, 30, -75, 180):
            result = hm.street_bearing(40, -75, tiles(turn))
            # In the east/south frame this rotation takes south toward west.
            self.assertAlmostEqual(result['bearing_deg'], (180+turn)%360, delta=1)
            self.assertEqual(result['source'], 'footprint')

    def test_edge_normal_not_geocode_to_street_ray(self):
        data = tiles()
        data['buildings'][0]['outline'] = [[x+4,y] for x,y in data['buildings'][0]['outline']]
        data['lines'] = [[[-100,30],[100,45]]]
        self.assertAlmostEqual(hm.street_bearing(40,-75,data)['bearing_deg'], 180, delta=1)

    def test_street_fallback_and_missing(self):
        self.assertEqual(hm.street_bearing(40,-75,tiles(0,False)), {'bearing_deg':180.,'source':'street'})
        self.assertIsNone(hm.street_bearing(40,-75,{}))
        self.assertIsNone(hm.street_bearing(40,-75,{'lines':[[[-10,0],[10,0]]]}))

    def test_site_precedence_and_no_fetch(self):
        with Ctx(), patch.object(hm,'_fetch',side_effect=AssertionError('network forbidden')), \
                patch.object(hm.maps,'geocode_address',side_effect=AssertionError('network forbidden')):
            twin_store.set_front_bearing(91)
            twin_store.set_map_bearing({'bearing_deg':180,'source':'footprint'})
            self.assertEqual(twin_site.site()['front_bearing_source'], 'dial')
            twin_store.clear_front_bearing_override()
            site = twin_site.site()
            self.assertEqual((site['front_bearing_deg'],site['front_bearing_source'],site['map_bearing_deg']), (180,'map',180))
            twin_store.set_map_bearing(None)
            self.assertEqual((twin_site.site()['front_bearing_deg'],twin_site.site()['front_bearing_source']), (91,'dial'))

    def test_legacy_dial_yields_to_map_and_default_is_explicit(self):
        with Ctx(), patch.object(twin_store,'place',return_value={'lot':{}}):
            self.assertEqual(twin_site.site()['front_bearing_source'],'default')
        with Ctx(), patch.object(twin_store,'place',return_value={'lot':{'front_bearing_deg':91,'map_bearing_deg':180}}):
            self.assertEqual((twin_site.site()['front_bearing_deg'],twin_site.site()['front_bearing_source']),(180,'map'))

    def test_fetch_emits_bearing_even_without_a_display_layout(self):
        import mapbox_vector_tile
        from unittest.mock import MagicMock
        tile = mapbox_vector_tile.encode({'name':'road','features':[{
            'geometry':{'type':'LineString','coordinates':[[0,2500],[4096,2500]]},
            'properties':{'class':'street'}}]},default_options={'y_coord_down':True})
        response = MagicMock()
        response.__enter__.return_value = response
        response.content = tile
        with patch.object(hm.requests,'get',return_value=response), patch.object(hm.maps,'check_usage_limits_and_spikes',return_value=True), \
                patch.object(hm,'compile_layout',return_value=None), patch.object(hm,'street_bearing',return_value={'bearing_deg':180,'source':'street'}) as bearing:
            result = hm._fetch(40,-75,'test-token')
            self.assertEqual(result['bearing'],{'bearing_deg':180,'source':'street'})
            self.assertTrue(bearing.call_args.args[2]['lines'])

    def test_put_and_clear_routes_and_tiers(self):
        with Ctx() as c:
            twin_store.set_map_bearing({'bearing_deg':180,'source':'street'})
            self.assertEqual(c.client.put(SAVE,headers=c.mum,json={'front_bearing_deg':92}).status_code,200)
            self.assertTrue(twin_store.place()['lot']['front_bearing_override'])
            for headers in (c.kid,c.panel,c.visitor):
                self.assertEqual(c.client.post(CLEAR,headers=headers).status_code,403)
            self.assertEqual(c.client.post(CLEAR,headers=c.mum).status_code,200)
            self.assertFalse(twin_store.place()['lot']['front_bearing_override'])
            self.assertEqual(twin_site.site()['front_bearing_deg'],180)
            self.assertEqual(auth.resolve('POST',CLEAR),auth.PARENTS)

    def test_worker_once_per_key_off_thread_and_location_change(self):
        with Ctx() as c, tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(storage,'DB_PATH',str(Path(directory)/'db.json')))
            home = stack.enter_context(patch.object(hm.maps,'get_home_location',return_value='First home'))
            stack.enter_context(patch.object(hm.maps,'get_mapbox_api_key',return_value='test-token'))
            stack.enter_context(patch.object(hm.maps,'get_map_option',return_value=False))
            stack.enter_context(patch.object(hm.maps,'geocode_address',return_value=(40,-75)))
            stack.enter_context(patch.object(storage,'get_cached_geocode',return_value={'lat':40,'lon':-75,'precision':'exact'}))
            thread_ids = []
            def fetch(*args):
                thread_ids.append(threading.get_ident())
                self.assertEqual(threading.current_thread().name,'twin-map-bearing')
                return {'source':'mapbox','bearing':{'bearing_deg':180 if len(thread_ids)==1 else 210,'source':'footprint'}}
            mock = stack.enter_context(patch.object(hm,'_fetch',side_effect=fetch))
            for expected in (180,210):
                c.client.get('/api/house/twin',headers=c.panel)
                wait_jobs()
                self.assertEqual(twin_site.site()['front_bearing_deg'],expected)
                for _ in range(3):
                    c.client.get('/api/house/editor/state',headers=c.mum)
                wait_jobs()
                self.assertEqual(mock.call_count,len(thread_ids))
                home.return_value = 'Second home'
            self.assertEqual(mock.call_count,2)
            self.assertNotIn(threading.get_ident(),thread_ids)
            # A restart reuses the attempt record even after the scene TTL.
            with patch.object(twin_site,'_results',{}), patch.object(twin_site,'_jobs',{}):
                twin_store.set_map_bearing(None)
                twin_site.start_bearing_job()
                self.assertEqual(twin_site.site()['front_bearing_deg'],210)
                self.assertEqual(mock.call_count,2)
            home.return_value = ''
            twin_site.start_bearing_job()
            self.assertNotIn('map_bearing_deg',twin_site.site())

    def test_page_hooks_and_slow_stale_worker(self):
        with Ctx() as c, tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            import main
            twin_store.clear_front_bearing_override()
            stack.enter_context(patch.object(storage,'DB_PATH',str(Path(directory)/'db.json')))
            home = stack.enter_context(patch.object(hm.maps,'get_home_location',return_value='Old home'))
            stack.enter_context(patch.object(hm.maps,'get_mapbox_api_key',return_value='test-token'))
            stack.enter_context(patch.object(hm.maps,'get_map_option',return_value=False))
            stack.enter_context(patch.object(main.templates,'TemplateResponse',return_value=main.JSONResponse({})))
            entered, release = threading.Event(), threading.Event()
            def lookup():
                entered.set()
                self.assertTrue(release.wait(5))
                return {'bearing':{'bearing_deg':123,'source':'street'}}
            mock = stack.enter_context(patch.object(hm,'neighborhood_layout',side_effect=lookup))
            try:
                self.assertEqual(c.client.get('/house/twin').status_code,200)
                self.assertTrue(entered.wait(2))
                self.assertEqual(c.client.get('/house/editor').status_code,200)
                self.assertEqual(mock.call_count,1)
                home.return_value = 'New home'
            finally:
                release.set()
                wait_jobs()
            self.assertNotIn('map_bearing_deg',twin_site.site())
            twin_site.start_bearing_job()
            wait_jobs()
            self.assertEqual(twin_site.site()['front_bearing_deg'],123)
            self.assertEqual(mock.call_count,2)

    def test_missing_map_and_failure_are_cooled_down_offline_fallbacks(self):
        with Ctx(), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(storage,'DB_PATH',str(Path(directory)/'db.json')))
            stack.enter_context(patch.object(hm.maps,'get_home_location',return_value='Unavailable map'))
            token = stack.enter_context(patch.object(hm.maps,'get_mapbox_api_key',return_value=None))
            stack.enter_context(patch.object(hm.maps,'get_map_option',return_value=False))
            fetch = stack.enter_context(patch.object(hm,'neighborhood_layout',side_effect=RuntimeError('offline')))
            twin_store.set_front_bearing(91)
            twin_site.start_bearing_job()
            fetch.assert_not_called()
            token.return_value = 'test-token'
            for _ in range(3):
                twin_site.start_bearing_job()
                wait_jobs()
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(twin_site.site()['front_bearing_deg'],91)
            self.assertIsNone(json.loads((Path(directory)/'house_map_bearing.json').read_text())['bearing'])

    def test_failed_and_no_match_retry_after_24_hours_in_memory_and_on_restart(self):
        for failure in (RuntimeError('offline'), {'bearing':None}):
            for restart in (False, True):
                with self.subTest(failure=failure,restart=restart), Ctx(), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                    path = Path(directory)/'house_map_bearing.json'
                    stack.enter_context(patch.object(storage,'DB_PATH',str(Path(directory)/'db.json')))
                    stack.enter_context(patch.object(hm,'lookup_context',return_value=(None,None,'retry-key')))
                    clock = stack.enter_context(patch('services.twin_site.time.time',return_value=100000.))
                    fetch = stack.enter_context(patch.object(hm,'neighborhood_layout',side_effect=[failure,{'bearing':{'bearing_deg':210,'source':'street'}}]))
                    twin_site.start_bearing_job();wait_jobs()
                    if restart:
                        stack.enter_context(patch.object(twin_site,'_results',{}))
                        stack.enter_context(patch.object(twin_site,'_jobs',{}))
                    clock.return_value += 86400-1
                    twin_site.start_bearing_job();wait_jobs();self.assertEqual(fetch.call_count,1)
                    clock.return_value += 1
                    twin_site.start_bearing_job();wait_jobs();self.assertEqual(fetch.call_count,2)
                    self.assertEqual(json.loads(path.read_text())['bearing']['bearing_deg'],210)
                    clock.return_value += 86400*10
                    twin_site.start_bearing_job();wait_jobs();self.assertEqual(fetch.call_count,2,'successful bearing stays cached')

    def test_legacy_failed_record_without_timestamp_can_retry(self):
        with Ctx(), tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'house_map_bearing.json'
            path.write_text(json.dumps({'key':'legacy','bearing':None}))
            with patch.object(storage,'DB_PATH',str(Path(directory)/'db.json')), patch.object(hm,'lookup_context',return_value=(None,None,'legacy')), \
                    patch.object(hm,'neighborhood_layout',return_value={'bearing':{'bearing_deg':180,'source':'street'}}) as fetch:
                twin_site.start_bearing_job();wait_jobs();self.assertEqual(fetch.call_count,1)


if __name__ == '__main__':
    unittest.main()
