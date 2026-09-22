"""Offline street geometry, provider decoding and request-budget regressions."""
import contextlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import harness
from services import house_map as hm
import mapbox_vector_tile


STREETS = [
    [(-350, 20), (45, 20), (100, 45), (135, 90), (135, 350)],
    [(-100, -350), (-100, 20), (-100, 350)],
    [(-350, -100), (-100, -100), (40, -100), (85, -65), (100, 45)],
    [(-350, 110), (0, 110), (55, 140), (135, 140)],
]


def building(cx, cz, width=10, depth=16, turn=0, identity=None, kind='house'):
    c,s=math.cos(turn),math.sin(turn)
    ring=[(cx+x*c+z*s,cz-x*s+z*c) for x,z in
          ((-width/2,-depth/2),(width/2,-depth/2),(width/2,depth/2),(-width/2,depth/2),(-width/2,-depth/2))]
    return {'id':identity,'type':kind,'outline':ring}


class HouseMapTests(unittest.TestCase):
    def test_real_outlines_keep_position_dimensions_and_tile_identity(self):
        a=building(50,0,10,18,.3,'a')
        # The second building straddles a tile boundary. Rejoin its two pieces.
        items=[building(0,0,14,16,identity='home'),a,dict(a,id='buffer-duplicate'),
               building(87.5,0,5,18,identity='b'),building(92.5,0,5,18,identity='b'),
               building(130,0,12,12,identity='garage',kind='garage'),
               building(160,0,12,12,identity='part',kind='building:part')]
        layout=hm.compile_layout([[(-265,28.5),(265,28.5)]],items)
        self.assertEqual(layout['placement'],'footprints')
        self.assertEqual(len(layout['lots']),2)
        self.assertEqual(layout['home']['footprint']['width'],14)
        self.assertEqual(layout['home']['footprint']['depth'],16)
        self.assertEqual(layout,hm.compile_layout([[(-265,28.5),(265,28.5)]],items))
        for lot,x in zip(layout['lots'],(50,90)):
            self.assertAlmostEqual(lot['x'],x,places=3)
            self.assertAlmostEqual(lot['z'],0,places=3)
            self.assertAlmostEqual(lot['footprint']['width'],10,delta=.002)
            self.assertAlmostEqual(lot['footprint']['depth'],18,delta=.002)
        self.assertAlmostEqual(math.cos(layout['lots'][0]['rotation']-.3),1,places=6)

    def test_dense_mapped_houses_are_not_packed_into_standard_yards(self):
        buildings=[building(x,z,10,16,identity=f'{x}:{z}')
                   for x in range(-208,209,26) for z in (-60,0,60,120)]
        layout=hm.compile_layout(STREETS,buildings)
        # These footprints are narrower than the prior minimum 70% garden.
        self.assertGreater(len(layout['lots']),48)
        self.assertLessEqual(len(layout['lots']),128)
        self.assertTrue(all('footprint' in lot for lot in layout['lots']))
        self.assertEqual(sum(p['detail']=='near' for p in layout['lots']),8)

    def test_building_decode_uses_z16_and_preserves_polygons(self):
        poly={'type':'Polygon','coordinates':[[[100,100],[300,100],[300,500],[100,500],[100,100]]]}
        multi={'type':'MultiPolygon','coordinates':[poly['coordinates'],[[[700,100],[900,100],[900,500],[700,500],[700,100]]]]}
        raw=mapbox_vector_tile.encode({'name':'building','features':[
            {'id':1,'geometry':poly,'properties':{'type':'house'}},
            {'id':2,'geometry':multi,'properties':{'type':'building'}},
            {'id':3,'geometry':poly,'properties':{'type':'building:part'}}]},default_options={'y_coord_down':True})
        response=MagicMock();response.__enter__.return_value=response;response.content=raw
        with patch.object(hm.requests,'get',return_value=response) as get,patch.object(hm.maps,'check_usage_limits_and_spikes',return_value=True),patch.object(hm,'compile_layout',return_value={'source':'mapbox'}) as compile_:
            result=hm._fetch(40,-75,'test-token')
            items=compile_.call_args.args[1]
            self.assertEqual(len(items),27)
            self.assertTrue(all(len(b['outline'])==5 for b in items))
            self.assertEqual({b['id'] for b in items},{1,2})
            self.assertEqual(len(compile_.call_args.args[2]),9)
            self.assertEqual(result['footprintStatus'],'available')
            self.assertEqual(sum('/16/' in call.args[0] for call in get.call_args_list),9)

    def test_building_timeout_retains_roads_and_stops_requests(self):
        response=MagicMock();response.__enter__.return_value=response;response.content=b'tile'
        attempts=[]
        def get(url,**kwargs):
            attempts.append(url)
            if '/16/' in url:
                raise hm.requests.Timeout('offline fixture')
            return response
        with patch.object(hm.requests,'get',side_effect=get),patch.object(hm.maps,'check_usage_limits_and_spikes',return_value=True),patch.object(mapbox_vector_tile,'decode',return_value={}),patch.object(hm,'compile_layout',return_value={'source':'mapbox','roads':['preserved']}) as compile_:
            result=hm._fetch(40,-75,'test-token')
            self.assertEqual(result['roads'],['preserved'])
            self.assertEqual(result['footprintStatus'],'unavailable')
            self.assertEqual(sum('/16/' in url for url in attempts),1)
            self.assertEqual(compile_.call_args.args[2],[])

    def test_adjacent_frontages_are_not_alternately_discarded(self):
        road = [[(-265, 28.5), (265, 28.5)]]
        # These 52-wide yards fit at all 54-unit frontages. Include the home
        # footprint: only that parcel should be excluded, not its neighbors.
        buildings = [(x, z) for x in range(-216, 217, 54) for z in (0, 57)]
        lots = hm.compile_layout(road, buildings)['lots']
        for x in range(-216, 217, 54):
            for z in (-.5, 57.5):
                if x == 0 and z == -.5:
                    continue
                self.assertTrue(any(math.dist((x, z), (p['x'], p['z'])) < .02 for p in lots), (x, z, lots))

    def test_sampled_frontages_fit_the_collision_envelope(self):
        lots = hm.compile_layout([[(-265, 28.5), (265, 28.5)]])['lots']
        # Search usable frontage instead of accepting only interval midpoints.
        self.assertEqual(len(lots), 17)

    def test_junction_search_and_scaled_yards(self):
        # A fixed midpoint on either side of the origin clashes with HOME;
        # the junction blocks another midpoint on the opposite side.
        roads = [[(-80,28.5),(64,28.5)],[(24,28.5),(24,66)],
                 [(64,28.5),(88,41),(125,110)], [(-80,28.5),(-130,17)],
                 [(-180,120),(180,120)]]
        layout = hm.compile_layout(roads)
        lots = layout['lots']
        self.assertTrue(any(p['x'] < -50 and abs(p['z']) < 1 for p in lots))
        self.assertTrue(any(p['scale'] < 1 for p in lots))
        self.assertEqual(layout, hm.compile_layout(roads))
        home = hm.parcel({'x':0,'z':0,'rotation':0})
        for i, lot in enumerate(lots):
            self.assertIn(lot['scale'], (1,.85,.7))
            self.assertFalse(hm.parcels_overlap(hm.parcel(lot),home))
            self.assertFalse(hm.street_crosses_parcel(lot,layout['roads']))
            for other in lots[:i]:
                self.assertFalse(hm.parcels_overlap(hm.parcel(lot),hm.parcel(other)))
            setback = 26*lot['scale']+3
            front=(lot['x']+setback*math.sin(lot['rotation']),lot['z']+setback*math.cos(lot['rotation']))
            self.assertLess(min(hm.closest(front,*segment)[0] for segment in layout['roads']),.02)
        self.assertEqual([p['detail'] for p in lots],['near' if i<8 else 'far' for i in range(len(lots))])

    def test_topology_orientation_packing_and_bounds(self):
        layout = hm.compile_layout(STREETS)
        self.assertEqual(layout, hm.compile_layout(STREETS))
        self.assertEqual(layout['source'], 'mapbox')
        self.assertTrue(any(a[0] != b[0] and a[1] != b[1] for a, b in layout['roads']))
        self.assertTrue(any(abs(a[1]-28.5) < .01 for a, b in layout['roads']))
        self.assertTrue(all(abs(v) <= 265 for seg in layout['roads'] for p in seg for v in p))
        self.assertGreater(len(layout['lots']), 8)
        self.assertLessEqual(len(layout['lots']), 48)
        self.assertEqual(sum(p['detail'] == 'near' for p in layout['lots']), 8)
        self.assertTrue(any(p['z'] < 0 for p in layout['lots'][:8]))
        for i, lot in enumerate(layout['lots']):
            p = (lot['x'], lot['z'])
            self.assertFalse(hm.parcels_overlap(hm.parcel(lot), hm.parcel({'x':0, 'z':0, 'rotation':0})))
            for other in layout['lots'][:i]:
                self.assertFalse(hm.parcels_overlap(hm.parcel(lot), hm.parcel(other)))
            self.assertFalse(hm.street_crosses_parcel(lot, layout['roads']))
            # Front of every house reaches its street, with the correct yaw.
            setback = 26*lot['scale']+3
            front = (p[0]+setback*math.sin(lot['rotation']), p[1]+setback*math.cos(lot['rotation']))
            self.assertLess(min(hm.closest(front, a, b)[0] for a, b in layout['roads']), .02)
        # Rotating the map must not mirror or change the neighborhood.
        rotated = [[(-z, x) for x, z in line] for line in STREETS]
        self.assertEqual(layout, hm.compile_layout(rotated))

    def test_unusable_pin_and_geometry(self):
        for lines in ([], [[(0, 0), (0, 0)]], [[(-20, 0), (20, 0)]], [[(-200, 200), (200, 200)]]):
            self.assertIsNone(hm.compile_layout(lines))

    def test_vector_decode_y_down_tile_edges_and_budget(self):
        # Actual MVT encode/decode, not a stub returning GeoJSON. Include a
        # tunnel and motorway which must not become residential frontage.
        features = [{'geometry': {'type': 'LineString', 'coordinates': [[0, 2000], [4096, 2100]]},
                     'properties': {'class': 'street'}}]
        for properties in ({'class': 'motorway'}, {'class': 'street', 'structure': 'tunnel'}):
            features.append({'geometry': features[0]['geometry'], 'properties': properties})
        tile = mapbox_vector_tile.encode({'name': 'road', 'features': features}, default_options={'y_coord_down': True})
        response = MagicMock()
        response.__enter__.return_value = response
        response.content = tile
        with patch.object(hm.requests, 'get', return_value=response) as fetch, patch.object(hm.maps, 'check_usage_limits_and_spikes', return_value=True) as budget, patch.object(hm, 'compile_layout', return_value={'source': 'mapbox'}) as compile_:
            hm._fetch(40, -75, 'test-token')
            self.assertLessEqual(fetch.call_count, 13)
            self.assertEqual(fetch.call_count, budget.call_count)
            lines = compile_.call_args.args[0]
            self.assertEqual(len(lines), fetch.call_count-9)
            self.assertEqual(sum('/16/' in call.args[0] for call in fetch.call_args_list),9)
            self.assertTrue(all(b[1] > a[1] for a, b in lines))
            self.assertTrue(all(call.kwargs['timeout'] == (3, 5) for call in fetch.call_args_list))

    def test_cache_failure_cooldown_home_change_and_disable(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(hm.storage, 'DB_PATH', str(Path(directory)/'db.json')))
            home = stack.enter_context(patch.object(hm.maps, 'get_home_location', return_value='Test home'))
            stack.enter_context(patch.object(hm.maps, 'get_mapbox_api_key', return_value='private-token'))
            disabled = stack.enter_context(patch.object(hm.maps, 'get_map_option', return_value=False))
            stack.enter_context(patch.object(hm.maps, 'geocode_address', return_value=(40, -75)))
            precision = stack.enter_context(patch.object(hm.storage, 'get_cached_geocode', return_value={'precision': 'exact'}))
            fetch = stack.enter_context(patch.object(hm, '_fetch', return_value=hm.compile_layout(STREETS)))
            # An upgrade must not retain the sparse layout for twelve hours.
            legacy_key = hm.hashlib.sha256(b'Test home|private-token|4').hexdigest()
            (Path(directory)/'house_map.json').write_text(json.dumps({'key':legacy_key, 'until':hm.time.time()+3600,
                                                                    'layout':{'source':'mapbox','lots':[]}}))
            self.assertEqual(hm.neighborhood_layout(cached_only=True)['source'], 'generated')
            fetch.assert_not_called()
            result = hm.neighborhood_layout()
            self.assertEqual(result, hm.neighborhood_layout())
            self.assertEqual(fetch.call_count, 1)
            raw = (Path(directory)/'house_map.json').read_text()
            self.assertNotIn('Test home', raw)
            self.assertNotIn('private-token', raw)
            disabled.return_value = True
            self.assertEqual(hm.neighborhood_layout()['source'], 'generated')
            disabled.return_value = False
            home.return_value = 'Different home'
            fetch.side_effect = TimeoutError('provider failure')
            self.assertEqual(hm.neighborhood_layout()['source'], 'generated')
            hm.neighborhood_layout()
            self.assertEqual(fetch.call_count, 2)
            home.return_value = 'City pin'
            precision.return_value = {'precision': 'city'}
            hm.neighborhood_layout()
            self.assertEqual(fetch.call_count, 2)


if __name__ == '__main__':
    unittest.main()
