"""Offline regressions for foreground overload rotation and bounded fallback."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch
from services import model_pools as pools

SETTINGS={'model_pool_flash':'gemini-a,gemini-b,gemini-c','model_pool_lite':'gemini-lite'}

class OverloadTests(unittest.TestCase):
    def setUp(self):pools.reset_cooldowns()
    def tearDown(self):pools.reset_cooldowns()
    def call(self,**kw):
        return pools.call_pool_json('vision','offline','system','user',settings=SETTINGS,**kw)

    def test_503_rotates_and_next_request_skips_overloaded_models(self):
        seen=[]
        def request(*args,**kw):
            seen.append(args[3])
            self.assertEqual(kw['transient_retries'],0)
            if args[3] in ('gemini-a','gemini-b'):raise RuntimeError('HTTP Error 503: Service Unavailable')
            return {'ok':True}
        with patch('services.llm._call_llm_json',request),patch.object(pools.time,'time',return_value=1000):
            self.assertTrue(self.call(max_models=10)['ok'])
            self.assertTrue(self.call(max_models=10)['ok'])
        self.assertEqual(seen,['gemini-a','gemini-b','gemini-c','gemini-c'])
        with patch.object(pools.time,'time',return_value=1121):
            self.assertEqual(pools.models_for('vision',SETTINGS)[0],'gemini-a')

    def test_lite_reached_after_flash_overload(self):
        def request(*args,**kw):
            if args[3]!='gemini-lite':raise RuntimeError('HTTP Error 503')
            return {'ok':True}
        with patch('services.llm._call_llm_json',request):
            self.assertEqual(self.call(max_models=10,total_timeout_s=120)['_model'],'gemini-lite')


    def test_time_budget_limits_attempt_timeout_and_stops(self):
        clock=[0];timeouts=[]
        def request(*args,**kw):
            timeouts.append(kw['timeout_s']);clock[0]+=70 if len(timeouts)==1 else 50
            raise RuntimeError('HTTP Error 503')
        with patch('services.llm._call_llm_json',request),patch.object(pools.time,'monotonic',lambda:clock[0]):
            result=self.call(max_models=10,timeout_s=90,total_timeout_s=120)
        self.assertEqual(timeouts,[90,50])
        self.assertIn('time budget',result['error'])

    def test_request_cap_and_background_single_attempt(self):
        with patch('services.llm._call_llm_json',side_effect=RuntimeError('HTTP Error 503')) as request:
            self.call(max_models=2)
            self.assertEqual(request.call_count,2)
            request.reset_mock()
            self.call(max_models=10,background=True,total_timeout_s=120)
            self.assertEqual(request.call_count,1)

    def test_overload_does_not_shorten_existing_quota_cooldown(self):
        with patch.object(pools.time,'time',return_value=1000):
            pools.note_failure('gemini-a','HTTP 404 not found')
            until=pools._cooldowns['gemini-a']
            pools.note_failure('gemini-a','HTTP 503')
            self.assertEqual(pools._cooldowns['gemini-a'],until)

if __name__=='__main__':unittest.main()
