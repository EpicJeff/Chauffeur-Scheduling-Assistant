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


    def test_porch_triangle_does_not_require_extra_gable(self):
        spec=copy.deepcopy(hf.CANONICAL)
        spec['roof']=[];spec['upper']=[]
        spec['ground']=[{'kind':'porch','slot':8,'span':6,'roof':'mixed','gable_offset':1,'gable_span':2}]
        obs=copy.deepcopy(OBSERVATIONS);obs['gables']=[{'at':.5,'width':2/18}]
        self.assertEqual(structural_issues(spec,obs),[])


if __name__=='__main__':unittest.main()
