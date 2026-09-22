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


class HouseMapTests(unittest.TestCase):
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
            self.assertGreaterEqual(math.hypot(*p), 59.99)
            self.assertGreaterEqual(min(hm.closest(p, a, b)[0] for a, b in layout['roads']), 26.99)
            for other in layout['lots'][:i]:
                self.assertGreaterEqual(math.dist(p, (other['x'], other['z'])), 57.99)
                self.assertFalse(hm.parcels_overlap(hm.parcel(lot), hm.parcel(other)))
            self.assertFalse(hm.street_crosses_parcel(lot, layout['roads']))
            # Front of every house reaches its street, with the correct yaw.
            front = (p[0]+29*math.sin(lot['rotation']), p[1]+29*math.cos(lot['rotation']))
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
            self.assertLessEqual(fetch.call_count, 4)
            self.assertEqual(fetch.call_count, budget.call_count)
            lines = compile_.call_args.args[0]
            self.assertEqual(len(lines), fetch.call_count)
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
