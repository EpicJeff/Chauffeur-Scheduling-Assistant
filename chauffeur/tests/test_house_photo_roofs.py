"""Roof interpretation and bounded structural correction; no provider requests."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
from services.house_photo import validate_observations, reconcile_observations, structural_issues
from photo_helpers import OBSERVATIONS

DATA=json.loads((Path(__file__).parent/'fixtures/house_photo_roof_structure.json').read_text())

class RoofStructure(unittest.TestCase):
    def setUp(self):
        hf._PHOTO_RUNS.clear()
        hf._DRAFTS.clear()
        self.obs=copy.deepcopy(OBSERVATIONS)
        self.obs['roofs']=[{'at':.63,'width':.34,'story':1,'ridge':'x','front_gable':'cross',
                            'evidence':'Roof slope continues laterally behind the front triangle.'}]

    def test_authored_cross_roof_vs_latest_failure(self):
        self.assertEqual(validate_observations(self.obs),[])
        self.assertEqual(structural_issues({**DATA['authored_spec'], 'upper':[]},self.obs),[])
        issues=structural_issues(DATA['failed_spec'],self.obs)
        self.assertTrue(any('supporting story' in x for x in issues))
        self.assertTrue(any('underlying ridge=x' in x for x in issues))
        self.assertTrue(any('cross-gable' in x for x in issues))
        wrong=copy.deepcopy(DATA['authored_spec']);wrong['upper']=[]
        wrong['blocks']['garage']['roof']['ridge']='z';wrong['roof']=[r for r in wrong['roof'] if r['slot']!=0]
        self.assertTrue(any('underlying ridge=x' in x for x in structural_issues(wrong,self.obs)))
        # Reflect both observation and house: the roof meaning does not change.
        correct=copy.deepcopy(DATA['authored_spec']);correct['upper']=[];correct['mirror']=False
        self.obs['roofs'][0]['at']=.03
        self.assertEqual(structural_issues(correct,self.obs),[])

    def test_unknown_and_invalid_roof_observations(self):
        self.obs['roofs'][0].update(ridge='unknown',front_gable='unknown')
        self.assertEqual(validate_observations(self.obs),[])
        for field,value in [('story',True),('ridge','parallel'),('evidence','')]:
            bad=copy.deepcopy(self.obs);bad['roofs'][0][field]=value
            self.assertTrue(validate_observations(bad))
        self.obs['roofs'][0].update(ridge='z',front_gable='cross')
        self.assertEqual(validate_observations(self.obs),[])
        self.assertEqual(reconcile_observations(self.obs)['roofs'][0]['ridge'],'unknown')
        self.assertEqual(validate_observations(OBSERVATIONS),[])

    def test_conflicting_interpretations_continue_without_extra_calls(self):
        for ridge, gable in [('z', 'cross'), ('x', 'end')]:
            hf._PHOTO_RUNS.clear()
            observed=copy.deepcopy(OBSERVATIONS)
            observed['roofs']=[{'at':0,'width':1/3,'story':1,'ridge':ridge,
                                'front_gable':gable,'evidence':'Visible triangle and roof slope.'}]
            original=copy.deepcopy(observed)
            with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                    'services.model_pools.call_pool_json',side_effect=[observed,copy.deepcopy(hf.CANONICAL)]) as api:
                spec,notes,error,token=hf.from_photo('conflicting-roof','image/png')
                self.assertIsNone(error)
                self.assertIsNotNone(spec)
                self.assertEqual(api.call_count,2)
                self.assertEqual(hf.from_photo('conflicting-roof','image/png')[3],token)
                self.assertEqual(api.call_count,2)
                sent=api.call_args.args[3]
                self.assertIn('"ridge":"unknown"',sent)
                self.assertIn('"front_gable":"unknown"',sent)
            self.assertEqual(observed,original)
            self.assertTrue(any('conflicting ridge=' in note for note in notes))
            trace=hf._DRAFTS[token]['photo_trace']
            self.assertEqual(trace['raw_observations'],original)
            self.assertEqual(trace['observations']['roofs'][0]['ridge'],'unknown')
            self.assertEqual(trace['observations']['roofs'][0]['evidence'],original['roofs'][0]['evidence'])
            self.assertEqual(reconcile_observations(trace['observations']),trace['observations'])

    def test_porch_triangle_does_not_require_extra_gable(self):
        spec=copy.deepcopy(hf.CANONICAL)
        spec['roof']=[];spec['upper']=[]
        spec['ground']=[{'kind':'porch','slot':8,'span':6,'roof':'mixed','gable_offset':1,'gable_span':2}]
        obs=copy.deepcopy(OBSERVATIONS);obs['gables']=[{'at':.5,'width':2/18}]
        self.assertEqual(structural_issues(spec,obs),[])

    def test_correction_budget_failure_and_regression(self):
        for response,status in [({'error':'503 unavailable'},'failed'),(DATA['failed_spec'],'withheld')]:
            hf._PHOTO_RUNS.clear()
            steps=iter([self.obs, DATA['failed_spec'],response])
            def provider(*args,**kw):
                kw['attempts'].append('offline')
                return copy.deepcopy(next(steps))
            with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                    'services.model_pools.call_pool_json',side_effect=provider) as api:
                spec,notes,error,token=hf.from_photo('fixture','image/png')
            self.assertIsNone(error)
            self.assertEqual(spec,hf.normalize(DATA['failed_spec'])[0])
            self.assertEqual(api.call_count,3)
            self.assertEqual(api.call_args.kwargs['max_models'],1)
            self.assertEqual(hf._DRAFTS[token]['photo_trace']['automatic_correction']['status'],status)
        hf._PHOTO_RUNS.clear()
        def exhausted(*args,**kw):
            kw['attempts'].extend(['offline']*kw['max_models'])
            return copy.deepcopy(self.obs if args[2]==hf.OBSERVATION_PROMPT else DATA['failed_spec'])
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                'services.model_pools.call_pool_json',side_effect=exhausted) as api:
            _,_,error,token=hf.from_photo('fixture','image/png')
        self.assertIsNone(error)
        self.assertEqual(api.call_count,2)
        self.assertEqual(len(hf._DRAFTS[token]['photo_trace']['attempts']),6)
        self.assertEqual(hf._DRAFTS[token]['photo_trace']['automatic_correction']['status'],'budget_exhausted')

if __name__=='__main__':unittest.main()
