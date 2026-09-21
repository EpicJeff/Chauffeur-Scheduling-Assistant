"""Descriptive observations must not block otherwise usable photo analysis."""
import copy
import json
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
from services.house_photo import normalize_observation_notes, validate_observations
from photo_helpers import OBSERVATIONS

class ObservationNotes(unittest.TestCase):
    def test_variations_preserve_descriptions(self):
        variants=['White brick on the porch', {'porch':'white brick','roof':'charcoal'},
                  [{'region':'porch','material':'brick'},'Dark shingles'],None,[],[None,42,False,'Brick']]
        for key in ('materials','uncertain'):
            for value in variants:
                with self.subTest(key=key,value=value):
                    raw=copy.deepcopy(OBSERVATIONS);raw[key]=value
                    original=copy.deepcopy(raw)
                    clean=normalize_observation_notes(raw)
                    self.assertEqual(validate_observations(clean),[])
                    self.assertEqual(raw,original)
                    self.assertEqual(normalize_observation_notes(clean),clean)
                    if isinstance(value,dict):self.assertEqual(json.loads(clean[key][0]),value)
                    if isinstance(value,str):self.assertEqual(clean[key][0],value)
        raw=copy.deepcopy(OBSERVATIONS);del raw['materials'];del raw['uncertain']
        self.assertEqual(validate_observations(normalize_observation_notes(raw)),[])

    def test_geometry_is_not_relaxed(self):
        raw=copy.deepcopy(OBSERVATIONS);raw['materials']={'roof':'shingles'}
        raw['sections'][0]['width']='wide'
        self.assertIn('invalid sections bounds',validate_observations(normalize_observation_notes(raw)))
        self.assertEqual(normalize_observation_notes(None),None)


if __name__=='__main__':unittest.main()
