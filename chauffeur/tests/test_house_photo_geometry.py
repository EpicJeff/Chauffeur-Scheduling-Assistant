"""Replay the missing openings / duplicate end-gable photo regression offline."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
from services.house_photo import restore_missing_upper_windows

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/house_photo_missing_openings.json').read_text())

class PhotoGeometry(unittest.TestCase):

    def test_only_redundant_full_end_removed(self):
        raw=copy.deepcopy(hf.CANONICAL)
        raw['blocks']['garage']['roof'].update(ridge='z')
        raw['roof']=[{'slot':0,'span':3,'kind':'gable','window':True}]
        spec,_=hf.normalize(raw)
        self.assertEqual(spec['roof'],raw['roof'])
        raw['upper']=[{'slot':8,'span':6,'roof':{'form':'gable','ridge':'z','pitch_deg':30}}]
        raw['roof']=[{'slot':8,'span':6,'kind':'gable','window':True}]
        spec,_=hf.normalize(raw)
        self.assertEqual(spec['roof'],[])
        self.assertTrue(spec['upper'][0]['roof']['window'])
        self.assertEqual(hf.normalize(spec)[0],spec)

    def test_partial_and_ambiguous_windows_not_guessed(self):
        spec,_=hf.normalize(FIXTURE['before_normalization'])
        obs=copy.deepcopy(FIXTURE['observations'])
        spec['ground'].append({'slot':9,'span':1,'kind':'window','story':2})
        self.assertEqual(restore_missing_upper_windows(spec,obs),[])
        spec['ground'].pop()
        obs['upper']*=2
        self.assertEqual(restore_missing_upper_windows(spec,obs),[])

if __name__=='__main__':unittest.main()
