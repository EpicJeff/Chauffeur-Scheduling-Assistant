"""Explicit window groups and saved photo diagnostics; no provider calls."""
import copy
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
from photo_helpers import OBSERVATIONS

class WindowGroups(unittest.TestCase):
    def setUp(self):
        hf._PHOTO_RUNS.clear()
        self.spec=copy.deepcopy(hf.CANONICAL)
        self.spec['ground']=[{'slot':7,'span':3,'kind':'window','size':'tall','shutters':True,'story':1,'count':3}]

    def test_count_roundtrip_and_existing_single_unchanged(self):
        self.assertEqual(hf.validate_block_model(self.spec),[])
        clean,notes=hf.normalize(self.spec)
        self.assertEqual(clean['ground'][0]['count'],3)
        self.assertEqual(hf.normalize(clean)[0],clean)
        self.assertEqual(hf.normalize(hf.CANONICAL)[0],hf.CANONICAL)
        for count in [0,5,1.5,True]:
            bad=copy.deepcopy(self.spec);bad['ground'][0]['count']=count
            self.assertTrue(any('.count' in e for e in hf.validate_block_model(bad)))

    def test_clipped_group_fits_remaining_wall(self):
        self.spec['ground'][0].update(slot=17,span=3)
        clean,notes=hf.normalize(self.spec)
        self.assertEqual(clean['ground'][0]['span'],1)
        self.assertNotIn('count',clean['ground'][0])
        self.assertTrue(any('reduced' in n for n in notes))


if __name__=='__main__':unittest.main()
