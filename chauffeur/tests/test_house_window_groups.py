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

    def test_saved_trace_distinguishes_removed_from_missing(self):
        from services import storage
        raw=copy.deepcopy(self.spec)
        raw['ground'].append({'slot':15,'span':1,'kind':'window','size':'tall','shutters':False,'story':2})
        settings={'llm_gemini_api_key':'offline'}
        settings_patch=patch.object(hf,'_settings',return_value=settings)
        write_patch=patch.object(hf,'_write',side_effect=settings.update)
        settings_patch.start();write_patch.start()
        self.addCleanup(settings_patch.stop);self.addCleanup(write_patch.stop)
        with patch('services.model_pools.call_pool_json',side_effect=[OBSERVATIONS,raw]):
            spec,notes,error,token=hf.from_photo('image','image/png')
        self.assertIsNone(error)
        record=hf.save_facade('Trace fixture',spec,source='photo',photo_token=token)
        trace=record['photo_trace']
        self.assertEqual(trace['saved_matches'],'draft')
        self.assertTrue(any(g.get('story')==2 for g in trace['raw_configuration']['ground']))
        self.assertFalse(any(g.get('story')==2 for g in record['spec']['ground']))
        self.assertTrue(any('no upper story' in n for n in trace['normalization_notes']))
        exported=next(r for r in hf.list_facades() if r['id']==record['id'])
        self.assertEqual(exported['photo_trace'],trace)
        self.assertNotIn('photo_b64',trace)
        hf._DRAFTS.clear()
        expired=hf.save_facade('Expired',spec,source='photo',photo_token=token)
        self.assertIn('unavailable',expired['photo_trace_status'])

if __name__=='__main__':unittest.main()
