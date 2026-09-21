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

    def test_generation_and_revision_preserve_full_raw_notes(self):
        hf._PHOTO_RUNS.clear()
        raw=copy.deepcopy(hf.CANONICAL);raw['unexpressed']=['a'*150]
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
            'services.model_pools.call_pool_json',side_effect=[OBSERVATIONS,raw,{'revised':raw,'reasons':[]}]) as api:
            spec,notes,error,token=hf.from_photo('long-note','image/png')
            self.assertIsNone(error)
            self.assertEqual(len(spec['unexpressed'][0]),80)
            revised,error=hf.critique(token,'render')
            self.assertIsNone(error)
            self.assertIsNotNone(revised['revised'])
            self.assertEqual(api.call_count,3)
        trace=hf._DRAFTS[token]['photo_trace']
        self.assertEqual(trace['raw_configuration']['unexpressed'],raw['unexpressed'])
        self.assertEqual(trace['revision_raw']['unexpressed'],raw['unexpressed'])
        self.assertTrue(any('unexpressed descriptions normalized' in n for n in notes))
        bad=copy.deepcopy(raw);bad['blocks']['main']['roof']=None
        self.assertTrue(hf._validate_photo_model(bad,[])[1])

if __name__=='__main__':unittest.main()
