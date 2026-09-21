"""Visual review may correct mistaken observations without weakening geometry checks."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf
DATA=json.loads((Path(__file__).parent/'fixtures/house_photo_visual_review.json').read_text())

class VisualReview(unittest.TestCase):
    def setUp(self):
        self.token=hf.issue_draft(DATA['spec'],'original-photo','image/jpeg')
        hf._DRAFTS[self.token]['observations']=copy.deepcopy(DATA['observations'])
        self.corrected=copy.deepcopy(DATA['observations'])
        self.corrected['upper']=self.corrected['upper'][:1]
        self.corrected['roofs'][2].update(story=1,ridge='x',front_gable='cross')
        self.spec=copy.deepcopy(DATA['spec'])
        self.spec['upper']=[u for u in self.spec['upper'] if u['slot']>=6]
        self.spec['blocks']['garage']['roof']['ridge']='x'
        self.spec['roof'].append({'slot':0,'span':6,'kind':'gable','window':True})
        self.spec,_=hf.normalize(self.spec)
        self.reply={'revised':self.spec,'corrected_observations':self.corrected,
                    'observation_corrections':['The right window sits in an attic triangle; the roof slope continues behind it.'],
                    'reasons':['Lowered right wing and restored the parallel ridge with a cross-gable.']}
        self.settings=patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'})
        self.settings.start();self.addCleanup(self.settings.stop)

    def test_consistent_but_wrong_initial_analysis_can_be_corrected(self):
        self.assertEqual(hf.structural_issues(DATA['spec'],DATA['observations']),[])
        with patch('services.model_pools.call_pool_json',return_value=self.reply) as api:
            result,error=hf.critique(self.token,'draft-render',automatic=True)
            self.assertIsNone(error);self.assertEqual(result['revised'],self.spec)
            self.assertEqual(api.call_args.kwargs['max_models'],1)
            self.assertEqual([i['b64'] for i in api.call_args.kwargs['images']],['original-photo','draft-render'])
            hf.critique(self.token,'draft-render',automatic=True)
            self.assertEqual(api.call_count,1)
        trace=hf._DRAFTS[self.token]['photo_trace']
        self.assertEqual(trace['revision_observations'],self.corrected)
        self.assertEqual(hf._DRAFTS[self.token]['observations'],DATA['observations'])

    def test_changed_observations_need_evidence_and_consistent_revision(self):
        for change in ('no-evidence','bad-geometry','wrong-revision'):
            hf._DRAFTS[self.token]['result']=None
            reply=copy.deepcopy(self.reply)
            if change=='no-evidence':reply['observation_corrections']=[]
            if change=='bad-geometry':reply['corrected_observations']['roofs'][2]['width']=-1
            if change=='wrong-revision':reply['revised']=DATA['spec']
            with patch('services.model_pools.call_pool_json',return_value=reply):
                result,_=hf.critique(self.token,'render',automatic=True)
            self.assertIsNone(result['revised'],change)
            self.assertEqual(hf._DRAFTS[self.token]['spec'],DATA['spec'])

    def test_failed_automatic_review_can_retry_manually(self):
        with patch('services.model_pools.call_pool_json',side_effect=[{'error':'503'},self.reply]) as api:
            failed,_=hf.critique(self.token,'render',automatic=True)
            self.assertIsNone(failed['revised'])
            recovered,_=hf.critique(self.token,'render')
            self.assertEqual(recovered['revised'],self.spec)
            self.assertEqual([c.kwargs['max_models'] for c in api.call_args_list],[1,3])

if __name__=='__main__':unittest.main()
