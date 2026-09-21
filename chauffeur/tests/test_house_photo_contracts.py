"""Prompt/transport contracts and auditable retry accounting; no provider traffic."""
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf, house_photo_schema as schema, llm, model_pools
from photo_helpers import OBSERVATIONS

class PhotoContracts(unittest.TestCase):
    def test_revision_contract_has_no_fraction_examples(self):
        prompt=hf._revision_prompt()
        self.assertNotIn('as a FRACTION',prompt)
        self.assertNotIn('"at":',prompt)
        self.assertNotIn('"width": 0..1',prompt)
        self.assertIn('"slot":',prompt)
        data=json.loads((Path(__file__).parent/'fixtures/house_photo_malformed_revision.json').read_text())
        for raw in data.values():
            original=copy.deepcopy(raw)
            _,errors=hf._revision_model(raw,[])
            self.assertTrue(any('canonical slot/span' in e for e in errors))
            self.assertEqual(raw,original)
        malformed=copy.deepcopy(hf.CANONICAL)
        malformed['upper']=[{'slot':8,'span':1,'kind':'window'}]
        del malformed['blocks']['garage']['body']
        _,errors=hf._revision_model(malformed,[])
        self.assertIn('blocks.garage.body missing',errors)
        self.assertIn('upper[0].roof missing',errors)

    def test_schemas_constrain_coordinate_and_upper_shapes(self):
        for fractional in (False,True):
            s=schema.house_schema(fractional=fractional)
            upper=s['properties']['upper']['items']
            self.assertIn('roof',upper['required'])
            self.assertNotIn('kind',upper['properties'])
            self.assertFalse(upper['additionalProperties'])
            self.assertEqual(set(upper['properties'])-{'roof'}, {'block','at','width'} if fractional else {'slot','span'})
            self.assertIn('body',s['properties']['blocks']['properties']['garage']['required'])
        self.assertIn('corrected_observations',schema.review_schema()['required'])

    def test_schema_reaches_gemini_http_payload(self):
        sent=[]
        def urlopen(req,**kw):
            sent.append(json.loads(req.data))
            return io.BytesIO(json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}]}).encode())
        with patch('services.llm_budget.urlopen',side_effect=urlopen),patch.object(model_pools,'models_for',return_value=['gemini-2.5-flash']):
            result=model_pools.call_pool_json('vision','offline','system','user',strict_json=True,
                response_schema=schema.review_schema(),max_models=1)
        self.assertTrue(result['ok'])
        cfg=sent[0]['generationConfig']
        self.assertEqual(cfg['responseMimeType'],'application/json')
        self.assertEqual(cfg['responseJsonSchema'],schema.review_schema())


if __name__=='__main__':unittest.main()
