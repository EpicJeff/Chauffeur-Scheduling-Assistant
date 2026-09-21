"""Photo base-height recovery without extra model calls or relaxed structure checks."""
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

    def test_both_passes_clamp_and_explain_without_mutating_response(self):
        for stage in ('describe','critique'):
            obj=self.model(4)
            obj['blocks']['garage']['base']['height']=0.2
            original=copy.deepcopy(obj)
            response=obj if stage=='describe' else {'reasons':['match stone base'],'revised':obj}
            with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch('services.model_pools.call_pool_json',side_effect=lambda *a, **k: photo_response(a[2], response)) as call:
                hf._PHOTO_RUNS.clear()
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
                self.assertEqual(call.call_count,2 if stage=='describe' else 1)
            self.assertEqual(obj,original)

    def test_numeric_dimension_recovery_in_both_passes(self):
        obj=self.model(4)
        obj['pitch_deg']=80
        obj['blocks']['main']['depth']=20
        obj['blocks']['garage']['depth']=-3
        obj['blocks']['main']['roof']['pitch_deg']=5
        obj['blocks']['garage']['side_door']={'style':'carriage','leaves':1,
            'width':20,'height':0,'front_setback':10,'projection':8}
        obj['upper']=[{'slot':6,'span':2,'roof':{'form':'gable','ridge':'x','pitch_deg':90}}]
        original=copy.deepcopy(obj)
        expected=['house.pitch_deg','blocks.main.depth','blocks.garage.depth',
                  'blocks.main.roof.pitch_deg','upper[0].roof.pitch_deg',
                  'blocks.garage.side_door.width','blocks.garage.side_door.height',
                  'blocks.garage.side_door.front_setback','blocks.garage.side_door.projection']
        self.assertTrue(hf.validate_block_model(obj))
        for stage in ('describe','critique'):
            response=obj if stage=='describe' else {'revised':obj,'reasons':[]}
            with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch('services.model_pools.call_pool_json',side_effect=lambda *a, **k: photo_response(a[2], response)) as call:
                hf._PHOTO_RUNS.clear()
                if stage=='describe':spec,notes,error,_=hf.from_photo('AAAA','image/jpeg')
                else:
                    token=hf.issue_draft(hf.CANONICAL,'AAAA','image/jpeg')
                    result,error=hf.critique(token,'iVBOR')
                    spec,notes=result['revised'],result['reasons']
                self.assertIsNone(error)
                self.assertIsNotNone(spec)
                self.assertEqual(hf.validate_block_model(spec),[])
                for field in expected:self.assertTrue(any(field+' adjusted' in n for n in notes),field)
                self.assertEqual(call.call_count,3 if stage=='describe' else 1)
            self.assertEqual(obj,original)

    def test_invalid_types_and_nonfinite_heights_still_rejected(self):
        for value in ('1.2',True,None,float('nan'),float('inf')):
            with self.subTest(value=value),patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch('services.model_pools.call_pool_json',side_effect=lambda *a, **k: photo_response(a[2], self.model(value))):
                hf._PHOTO_RUNS.clear()
                spec,_,error,_=hf.from_photo('AAAA','image/jpeg')
                self.assertIsNone(spec)
                self.assertIn('base.height',error)

    def test_null_base_and_valid_height_unchanged(self):
        obj=self.model(1.2);obj['blocks']['garage']['base']=None
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch('services.model_pools.call_pool_json',side_effect=lambda *a, **k: photo_response(a[2], obj)):
            spec,notes,error,_=hf.from_photo('AAAA','image/jpeg')
        self.assertIsNone(error)
        self.assertEqual(spec['blocks']['main']['base']['height'],1.2)
        self.assertIsNone(spec['blocks']['garage']['base'])
        self.assertFalse(any('base.height' in n for n in notes))

if __name__=='__main__':unittest.main()
