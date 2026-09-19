"""Photo base-height recovery without extra model calls or relaxed structure checks."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services import house_facade as hf

class PhotoBoundsTests(unittest.TestCase):
    def model(self,height):
        obj=copy.deepcopy(hf.CANONICAL)
        for name in ('main','garage'):
            obj['blocks'][name]['base']={'material':'stone','body':'stone_grey','height':height}
        return obj

    def test_both_passes_clamp_and_explain_without_mutating_response(self):
        for stage in ('describe','critique'):
            obj=self.model(4)
            obj['blocks']['garage']['base']['height']=0.2
            original=copy.deepcopy(obj)
            response=obj if stage=='describe' else {'reasons':['match stone base'],'revised':obj}
            with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch('services.model_pools.call_pool_json',return_value=response) as call:
                if stage=='describe':
                    spec,notes,error,token=hf.from_photo('AAAA','image/jpeg')
                else:
                    token=hf.issue_draft(hf.CANONICAL,'AAAA','image/jpeg')
                    result,error=hf.critique(token,'iVBOR')
                    spec,notes=result['revised'],result['reasons']
                self.assertIsNone(error)
                self.assertIsNotNone(spec)
                self.assertEqual(spec['blocks']['main']['base']['height'],1.8)
                self.assertEqual(spec['blocks']['garage']['base']['height'],0.6)
                self.assertTrue(any('main.base.height' in n for n in notes))
                self.assertTrue(any('garage.base.height' in n for n in notes))
                self.assertEqual(call.call_count,1)
            self.assertEqual(obj,original)

    def test_invalid_types_and_nonfinite_heights_still_rejected(self):
        for value in ('1.2',True,None,float('nan'),float('inf')):
            with self.subTest(value=value),patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch('services.model_pools.call_pool_json',return_value=self.model(value)):
                spec,_,error,_=hf.from_photo('AAAA','image/jpeg')
                self.assertIsNone(spec)
                self.assertIn('base.height',error)

    def test_null_base_and_valid_height_unchanged(self):
        obj=self.model(1.2);obj['blocks']['garage']['base']=None
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch('services.model_pools.call_pool_json',return_value=obj):
            spec,notes,error,_=hf.from_photo('AAAA','image/jpeg')
        self.assertIsNone(error)
        self.assertEqual(spec['blocks']['main']['base']['height'],1.2)
        self.assertIsNone(spec['blocks']['garage']['base'])
        self.assertFalse(any('base.height' in n for n in notes))

if __name__=='__main__':unittest.main()
