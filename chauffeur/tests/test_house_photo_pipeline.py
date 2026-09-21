"""Offline architecture benchmark, mirror coordinates, budgets, cache and revision gates."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
from services.house_photo import validate_observations, structural_issues

DATA = json.loads((Path(__file__).parent / 'fixtures/house_photo_benchmark.json').read_text())

class PipelineTests(unittest.TestCase):
    def setUp(self):
        hf._PHOTO_RUNS.clear()
        hf._DRAFTS.clear()
        self.settings = patch.object(hf, '_settings', return_value={'llm_gemini_api_key':'offline'})
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_real_saved_benchmark(self):
        observed = DATA['observations']
        self.assertEqual(validate_observations(observed), [])
        self.assertEqual(structural_issues(DATA['My house'], observed), [])
        bad = structural_issues(DATA['My house - photo'], observed)
        self.assertTrue(any('orientation' in x for x in bad))
        self.assertTrue(any('Second-story' in x for x in bad))
        self.assertTrue(any('Porch' in x for x in bad))
        no_windows = copy.deepcopy(DATA['My house'])
        no_windows['ground'] = [g for g in no_windows['ground'] if g.get('story') != 2]
        self.assertTrue(any('window groups' in x for x in structural_issues(no_windows, observed)))

    def test_mirrored_photo_coordinates_and_porch_offset(self):
        photo = {'mirror': True, 'upper':[{'block':'main','at':1/3,'width':2/3}],
                 'ground':[{'block':'main','at':1/3,'width':2/3,'kind':'porch','roof':'mixed','gable_offset':0,'gable_span':4}]}
        converted = hf._snap_fractions(photo, [], photo_coordinates=True)
        self.assertEqual((converted['upper'][0]['slot'], converted['upper'][0]['span']), (6,8))
        self.assertEqual(converted['ground'][0]['gable_offset'],4)
        self.assertNotIn('slot',photo['upper'][0])

    def provider(self, responses):
        items = iter(responses)
        def call(*args, **kw):
            kw['attempts'].append('offline-flash')
            return copy.deepcopy(next(items))
        return call







if __name__ == '__main__':
    unittest.main()
