"""Photo description lengths must not reject valid geometry."""
import copy
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
from photo_helpers import OBSERVATIONS

class PhotoDescriptions(unittest.TestCase):
    def test_long_excess_and_variant_notes_are_bounded_without_mutation(self):
        for value in [['x'*81],['x'*200]*12,'Metal roofing',None,{'detail':'x'*120},[None,42,{'detail':'metal'},'']]:
            raw=copy.deepcopy(hf.CANONICAL);raw['unexpressed']=value
            original=copy.deepcopy(raw);notes=[]
            clean,errors=hf._validate_photo_model(raw,notes)
            self.assertEqual(errors,[])
            self.assertEqual(raw,original)
            self.assertLessEqual(len(clean['unexpressed']),hf.UNEXPRESSED_MAX)
            self.assertTrue(all(isinstance(x,str) and len(x)<=hf.UNEXPRESSED_LEN for x in clean['unexpressed']))
            self.assertTrue(notes)
            self.assertEqual(hf._validate_photo_model(clean,[])[0],clean)
        self.assertTrue(hf.validate_block_model(original))  # normal validation remains strict


if __name__=='__main__':unittest.main()
