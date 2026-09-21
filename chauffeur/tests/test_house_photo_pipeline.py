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

    def test_three_calls_cached_and_regression_withheld(self):
        replies = [DATA['observations'], DATA['My house'], {'revised':DATA['My house - photo'],'reasons':['Changed massing']}]
        with patch('services.model_pools.call_pool_json', side_effect=self.provider(replies)) as api:
            spec, notes, err, token = hf.from_photo('image','image/png')
            self.assertIsNone(err)
            self.assertEqual(hf.from_photo('image','image/png')[3],token)
            self.assertEqual(api.call_count,2)
            result, err = hf.critique(token,'render')
            self.assertIsNone(result['revised'])
            self.assertTrue(any('withheld' in x for x in result['reasons']))
            self.assertEqual(result['requests_total'],3)
            hf.critique(token,'render')
            self.assertEqual(api.call_count,3)
            self.assertIn('Observations:', api.call_args.args[3])
            self.assertIn('Return exactly this shape',api.call_args.args[2])

    def test_correction_accepts_authored_structure(self):
        with patch('services.model_pools.call_pool_json', side_effect=self.provider([DATA['observations'],DATA['My house - photo'],{'revised':DATA['My house'],'reasons':['Fix second story']}])):
            _, notes, err, token = hf.from_photo('image','image/png')
            self.assertIsNone(err)
            self.assertTrue(any('Needs review' in x for x in notes))
            result, _ = hf.critique(token,'render')
            self.assertIsNotNone(result['revised'])
            self.assertEqual(structural_issues(result['revised'],DATA['observations']),[])

    def test_retry_reuses_observations_and_budget(self):
        def call(*args, **kw):
            if args[2] == hf.OBSERVATION_PROMPT:
                kw['attempts'].append('flash')
                return copy.deepcopy(DATA['observations'])
            kw['attempts'].extend(['busy'] * kw['max_models'])
            return {'error':'503 unavailable'}
        with patch('services.model_pools.call_pool_json',side_effect=call) as api:
            for _ in range(4):
                self.assertIsNotNone(hf.from_photo('image','image/png')[2])
            self.assertEqual(api.call_count,5)  # analysis once, four explicit translation attempts
            self.assertEqual(len(next(iter(hf._PHOTO_RUNS.values()))['attempts']),13)

    def test_six_request_ceiling_includes_pool_fallbacks(self):
        budgets = []
        def call(*args, **kw):
            budgets.append(kw['max_models'])
            kw['attempts'].extend(['flash'] * kw['max_models'])
            if len(budgets) == 1: return copy.deepcopy(DATA['observations'])
            if len(budgets) == 2: return copy.deepcopy(DATA['My house'])
            return {'revised':copy.deepcopy(DATA['My house']), 'reasons':[]}
        with patch('services.model_pools.call_pool_json', side_effect=call):
            _, _, error, token = hf.from_photo('image','image/png')
            self.assertIsNone(error)
            result, _ = hf.critique(token,'render')
            self.assertEqual(result['requests_total'],9)
            self.assertEqual(budgets,[3,3,3])
            hf.from_photo('image','image/png')
            hf.critique(token,'render')
            self.assertEqual(budgets,[3,3,3])

    def test_failed_critique_can_resume_without_rebuilding(self):
        replies = [DATA['observations'],DATA['My house'], {'error':'503'},
                   {'revised':DATA['My house'],'reasons':[]}]
        with patch('services.model_pools.call_pool_json', side_effect=self.provider(replies)) as api:
            _, _, _, token = hf.from_photo('image','image/png')
            first, _ = hf.critique(token,'render')
            self.assertIsNone(first['revised'])
            second, _ = hf.critique(token,'render')
            self.assertIsNotNone(second['revised'])
            self.assertEqual(second['requests_total'],4)
            self.assertEqual(api.call_count,4)
            for call in api.call_args_list:
                self.assertEqual(call.kwargs['thinking_level'],'low')
                self.assertEqual(call.kwargs['max_output_tokens'],16384)

    def test_invalid_observations_never_translate(self):
        with patch('services.model_pools.call_pool_json',side_effect=self.provider([{}])) as api:
            self.assertIn('invalid photo observations',hf.from_photo('image','image/png')[2])
            self.assertEqual(api.call_count,1)

if __name__ == '__main__':
    unittest.main()
