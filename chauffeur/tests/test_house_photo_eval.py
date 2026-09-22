"""Evaluation labels must not turn ambiguity or boundary hits into a model win."""
import importlib.util
from pathlib import Path
import unittest

module = importlib.util.spec_from_file_location('house_eval', Path(__file__).parents[1]/'tools/evaluate_house_photos.py')
evaluation = importlib.util.module_from_spec(module)
module.loader.exec_module(evaluation)


class EvaluationScoreTests(unittest.TestCase):
    def test_wrong_half_roof_is_not_hidden_by_a_midpoint_boundary(self):
        case={'id':'test','covered_porch':False,'regions':[
            {'at':0,'width':1,'stories':'one','form':'gable','ridge':'perpendicular'}]}
        structure={'volumes':[
            {'at':0,'width':.5,'stories':'one','roof':{'form':'gable','ridge':'perpendicular'}},
            {'at':.5,'width':.5,'stories':'one','roof':{'form':'gable','ridge':'parallel'}}]}
        result=evaluation.score(structure,case)
        self.assertTrue(result['stories'])
        self.assertFalse(result['roof_directions'])

    def test_ambiguous_labels_are_unscored_not_successful(self):
        case={'id':'test','covered_porch':False,'score_massing':False,'regions':[
            {'at':0,'width':1,'stories':'one','form':'gable','ridge':'parallel','score_roof':False}]}
        result=evaluation.score({'volumes':[]},case)
        self.assertIsNone(result['roof_directions'])
        self.assertIsNone(result['massing_widths'])
        self.assertFalse(result['stories'])

    def test_uncertain_form_does_not_hide_known_ridge_direction(self):
        case={'id':'test','covered_porch':False,'regions':[
            {'at':0,'width':1,'stories':'one','form':'gable','ridge':'parallel','score_form':False}]}
        structure={'volumes':[{'at':0,'width':1,'stories':'one','roof':{'form':'hip','ridge':'perpendicular'}}]}
        result=evaluation.score(structure,case)
        self.assertIsNone(result['roof_forms'])
        self.assertFalse(result['roof_directions'])


if __name__=='__main__':unittest.main()
