"""Legacy draft adapter keeps finite recovery and strict shape validation."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services import house_facade as hf
from photo_helpers import photo_response

class PhotoBoundsTests(unittest.TestCase):
    def setUp(self):
        hf._PHOTO_RUNS.clear()

    def model(self,height):
        obj=copy.deepcopy(hf.CANONICAL)
        for name in ('main','garage'):
            obj['blocks'][name]['base']={'material':'stone','body':'stone_grey','height':height}
        return obj

    def test_finite_ranges_recover_without_mutation(self):
        for height in (-4, 9):
            raw=self.model(height); original=copy.deepcopy(raw);notes=[]
            clean,errors=hf._validate_photo_model(raw,notes)
            self.assertEqual(errors,[])
            self.assertEqual(raw,original)
            self.assertTrue(notes)
            self.assertTrue(.6<=clean['blocks']['main']['base']['height']<=1.8)

    def test_nonfinite_and_missing_structure_stay_invalid(self):
        for height in (float('nan'),float('inf'),'tall'):
            self.assertTrue(hf._validate_photo_model(self.model(height),[])[1])
        raw=self.model(1);del raw['blocks']['main']['roof']
        self.assertTrue(hf._validate_photo_model(raw,[])[1])

if __name__=='__main__':unittest.main()
