"""Architecture IR -> deterministic house: geometry, ownership, repeatability and live route seams."""
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import harness
from services import house_facade as hf, model_pools, llm_budget
from services.house_photo_compiler import compile_analysis, validate_analysis, ANALYSIS_PROMPT
DATA=json.loads((Path(__file__).parent/'fixtures/house_photo_architecture_v1.json').read_text())

class CompilerTests(unittest.TestCase):
    def test_reference_shape_and_units_are_deterministic(self):
        original=copy.deepcopy(DATA)
        spec,notes,trace=compile_analysis(DATA)
        self.assertEqual(DATA,original)
        self.assertEqual((spec,notes,trace),compile_analysis(DATA))
        self.assertTrue(spec['mirror'])
        self.assertEqual(spec['upper'][0]['span'],7)  # whole facade .35*18, never .35*12
        self.assertEqual(len(spec['upper']),1)
        self.assertEqual(spec['blocks']['garage']['roof']['ridge'],'x')
        self.assertTrue(any(r['slot']==0 and r['window'] for r in spec['roof']))
        self.assertEqual(sum(o.get('story')==2 for o in spec['ground']),3)
        self.assertTrue(any(o.get('count')==3 for o in spec['ground']))
        self.assertEqual(hf.validate_block_model(spec),[])
        self.assertEqual(hf.normalize(spec)[0],spec)

    def test_photo8_volume_is_not_split_into_two_roof_towers(self):
        a=json.loads((Path(__file__).parent/'fixtures/house_photo8_analysis.json').read_text())
        original=copy.deepcopy(a)
        spec,notes,trace=compile_analysis(a)
        self.assertEqual(a,original)
        right=next(r for r in trace['mapping'] if r['id']=='vol_right')
        self.assertEqual(right['slots'],[[0,6]])
        self.assertEqual(len(spec['upper']),2)
        self.assertEqual(sum(u['roof']['ridge']=='z' for u in spec['upper']),1)
        self.assertFalse(any('gable clipped' in n for n in notes))
        self.assertEqual(sum(o.get('story')==2 for o in spec['ground']),4)
        self.assertEqual(hf.validate_block_model(spec),[])
        # Compiler must not silently turn incorrect observations into our reference.
        self.assertEqual(spec['upper'][0]['roof']['ridge'],'z')
        self.assertTrue(any('proportions fitted' in n for n in notes))
        for layer in ('volumes','porches','gables','dormers','openings','finishes'):
            for row in a[layer]:row['at']=round(1-row['at']-row['width'],8)
        a['garage_side']='left'
        reflected=compile_analysis(a)[0]
        for key in ('ground','roof','upper'):
            self.assertEqual(reflected[key],spec[key])

    def test_roof_story_and_known_orientation_matrix(self):
        for form in ('gable','hip'):
            for ridge in ('parallel','perpendicular'):
                for stories in ('one','two'):
                    for side in ('left','right'):
                        a=copy.deepcopy(DATA)
                        a.update(garage_side=side,porches=[],gables=[],dormers=[],openings=[],finishes=[])
                        a['volumes']=[{'id':'house','at':0,'width':1,'stories':stories,
                            'projection':'flush','roof':{'form':form,'ridge':ridge,
                            'pitch':'medium','evidence':'Fixture'},'evidence':'Fixture'}]
                        with self.subTest(form=form,ridge=ridge,stories=stories,side=side):
                            spec,notes,trace=compile_analysis(a)
                            self.assertEqual(hf.validate_block_model(spec),[])
                            self.assertEqual(spec['mirror'],side=='right')
                            self.assertEqual(spec['blocks']['main']['roof']['form'],form)
                            self.assertEqual(bool(spec['upper']),stories=='two')
                            self.assertEqual(hf.normalize(spec)[0],spec)

    def test_reflection_preserves_dimensions_and_counts(self):
        reflected=copy.deepcopy(DATA)
        for layer in ('volumes','porches','gables','dormers','openings','finishes'):
            for row in reflected[layer]:row['at']=round(1-row['at']-row['width'],8)
        spec,_,_=compile_analysis(reflected)
        self.assertFalse(spec['mirror'])
        expected=compile_analysis(DATA)[0]
        self.assertEqual(spec['ground'],expected['ground'])
        self.assertEqual(spec['roof'],expected['roof'])
        self.assertEqual(spec['upper'],expected['upper'])

    def test_porch_gable_does_not_change_building_roof(self):
        spec,_,trace=compile_analysis(DATA)
        porch=next(x for x in spec['ground'] if x['kind']=='porch')
        self.assertEqual(porch['roof'],'mixed')
        self.assertEqual(spec['blocks']['main']['roof']['ridge'],'x')
        self.assertEqual(len(spec['roof']),2)

    def test_owner_and_coordinate_errors_cannot_become_geometry(self):
        for change in ('block-coordinates','bad-owner','overlap','fake-upstairs','outside'):
            a=copy.deepcopy(DATA)
            if change=='block-coordinates':a['openings'][0]['block']='main'
            if change=='bad-owner':a['gables'][0]['owner']='missing'
            if change=='overlap':a['volumes'][1]['at']=.1
            if change=='fake-upstairs':a['openings'][0]['level']='upper'
            if change=='outside':a['openings'][0]['width']=1
            self.assertTrue(validate_analysis(a),change)
            with self.assertRaises(ValueError):compile_analysis(a)

    def test_single_story_end_roof_and_unknowns(self):
        a=copy.deepcopy(DATA)
        a['volumes']=[{'id':'wall','at':0,'width':1,'stories':'one','projection':'unknown',
                       'roof':{'form':'gable','ridge':'perpendicular','pitch':'unknown','evidence':'End triangle'},'evidence':'One wall'}]
        a.update(porches=[],openings=[],finishes=[],gables=[])
        spec,notes,_=compile_analysis(a)
        self.assertEqual(spec['upper'],[])
        self.assertEqual(spec['roof'],[])
        self.assertTrue(any('unknown roof pitch' in n for n in notes))
        self.assertEqual(hf.validate_block_model(spec),[])

    def test_dormer_ownership_and_unrepresentable_density(self):
        a=copy.deepcopy(DATA)
        a['dormers']=[{'id':'dormer','owner':'left','at':.05,'width':.12,'roof':'shed','window':True}]
        spec,notes,trace=compile_analysis(a)
        self.assertTrue(any(r['kind']=='shed' for r in spec['roof']))
        a['openings'] += [dict(a['openings'][0],id='extra'+str(i)) for i in range(8)]
        spec,notes,_=compile_analysis(a)
        self.assertTrue(any('cannot fit' in n for n in notes))
        self.assertEqual(hf.validate_block_model(spec),[])

    def test_saved_analysis_and_review_provenance_survive_export(self):
        hf._PHOTO_RUNS.clear()
        settings={'llm_gemini_api_key':'offline'}
        with patch.object(hf,'_settings',return_value=settings),patch.object(hf,'_write',side_effect=settings.update),patch(
                'services.model_pools.call_pool_json',return_value=copy.deepcopy(DATA)):
            spec,_,_,token=hf.from_photo('export-analysis','image/png')
            record=hf.save_facade('Compiled fixture',spec,source='photo',photo_token=token)
        self.assertEqual(record['photo_trace']['analysis'],DATA)
        self.assertEqual(record['photo_trace']['saved_matches'],'draft')
        self.assertTrue(record['photo_trace']['compilation']['mapping'])

    def test_upload_and_review_are_single_flight(self):
        hf._PHOTO_RUNS.clear()
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        started,release=Event(),Event()
        def provider(*args,**kw):
            started.set();release.wait(5);return copy.deepcopy(DATA)
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                'services.model_pools.call_pool_json',side_effect=provider) as api,ThreadPoolExecutor() as pool:
            pending=pool.submit(hf.from_photo,'locked','image/png')
            self.assertTrue(started.wait(2))
            self.assertIn('progress',hf.from_photo('locked','image/png')[2])
            release.set();_,_,error,token=pending.result()
            self.assertIsNone(error)
            self.assertEqual(api.call_count,1)
        started.clear();release.clear()
        def review(*args,**kw):
            started.set();release.wait(5);return {'analysis':copy.deepcopy(DATA),'reasons':['Compared visible roof planes.']}
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                'services.model_pools.call_pool_json',side_effect=review) as api,ThreadPoolExecutor() as pool:
            pending=pool.submit(hf.critique,token,'render')
            self.assertTrue(started.wait(2))
            self.assertIn('progress',hf.critique(token,'render')[1])
            release.set();self.assertIsNone(pending.result()[1])
            self.assertEqual(api.call_count,1)

    def test_pipeline_one_analysis_and_review_recompile(self):
        hf._PHOTO_RUNS.clear()
        replies=iter([DATA,{'analysis':DATA,'reasons':['Window positions verified against photo.']}])
        def provider(*args,**kw):
            kw['attempts'].append('offline')
            self.assertNotIn('Draft JSON:',args[3])
            return copy.deepcopy(next(replies))
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                'services.model_pools.call_pool_json',side_effect=provider) as api:
            spec,notes,error,token=hf.from_photo('new-analysis','image/png')
            self.assertIsNone(error)
            self.assertEqual(api.call_count,1)
            self.assertEqual(api.call_args.args[2],ANALYSIS_PROMPT)
            self.assertEqual(hf.from_photo('new-analysis','image/png')[3],token)
            result,error=hf.critique(token,'render',automatic=True)
            self.assertIsNone(error)
            self.assertEqual(result['revised'],spec)
            self.assertEqual(api.call_count,2)
            hf.critique(token,'render',automatic=True)
            self.assertEqual(api.call_count,2)
        trace=hf._DRAFTS[token]['photo_trace']
        self.assertEqual(trace['pipeline'],'deterministic_v1')
        self.assertEqual(trace['analysis'],DATA)
        self.assertEqual(trace['review_analysis'],DATA)
        self.assertNotIn('raw_configuration',trace)
        self.assertEqual(trace['requests_total'],2)

    def test_invalid_analysis_and_failed_review_leave_safe_state(self):
        hf._PHOTO_RUNS.clear()
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                'services.model_pools.call_pool_json',side_effect=[{},DATA,{'error':'paused','deferred':True,'retry_at':123}]):
            self.assertIsNotNone(hf.from_photo('invalid','image/png')[2])
            spec,_,error,token=hf.from_photo('invalid','image/png')
            self.assertIsNone(error)
            result,error=hf.critique(token,'render',automatic=True)
            self.assertIsNone(result['revised'])
            self.assertEqual(result['retry_at'],123)
            self.assertEqual(hf._DRAFTS[token]['spec'],spec)
            self.assertIsNone(hf._DRAFTS[token]['result'])

    def test_wire_accounting_ignores_local_deferrals(self):
        sent=[];attempts=[]
        def reserve(key,model):
            if model=='gemini-blocked':raise llm_budget.Deferred('paused',999)
            return 1
        def http(req,**kw):
            sent.append(req.full_url)
            return io.BytesIO(json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}]}).encode())
        with patch.object(model_pools,'models_for',return_value=['gemini-blocked','gemini-ready']),patch.object(
                llm_budget,'_reserve',side_effect=reserve),patch.object(llm_budget,'_finish'),patch('urllib.request.urlopen',side_effect=http):
            result=model_pools.call_pool_json('vision','offline','system','user',max_models=1,attempts=attempts)
        self.assertTrue(result['ok'])
        self.assertEqual(attempts,['gemini-ready'])
        self.assertEqual(len(sent),1)
        with patch.object(model_pools,'models_for',return_value=['gemini-blocked']),patch.object(
                llm_budget,'_reserve',side_effect=llm_budget.Deferred('paused',999)):
            result=model_pools.call_pool_json('vision','offline','s','u',attempts=attempts)
        self.assertTrue(result['deferred'])
        self.assertEqual(attempts,['gemini-ready'])

if __name__=='__main__':unittest.main()
