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

def faced_analysis(data):
    """Synthetic labeled evidence for compiler tests, not model recognition proof."""
    a=copy.deepcopy(data);a.update(schema_version=2,coordinate_frame='house_front',observations=[])
    for layer in ('volumes','porches','gables','dormers','openings','finishes'):
        for row in a[layer]:
            row['face']='front'
            if 'id' in row:a['observations'].append({'feature':row['id'],'image':1,'face':'front',
                'box':{'x':row['at'],'y':.2,'width':row['width'],'height':.5},'evidence':'Synthetic primary evidence.'})
    return a

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

    def test_porch_openings_resolve_to_wall_without_changing_geometry(self):
        a=copy.deepcopy(DATA)
        porch=a['porches'][0]
        openings=[o for o in a['openings'] if o['owner']==porch['owner'] and o['level']=='ground']
        self.assertTrue(any(o['kind']=='door' for o in openings))
        self.assertTrue(any(o['kind']=='window' for o in openings))
        expected=compile_analysis(a)[0]
        for o in openings:o['owner']=porch['id']
        original=copy.deepcopy(a)
        self.assertEqual(validate_analysis(a),[])
        spec,notes,trace=compile_analysis(a)
        self.assertEqual(a,original)
        for key in ('ground','roof','upper','blocks'):
            self.assertEqual(spec[key],expected[key])
        self.assertTrue(any('porch' in n and 'wall' in n for n in notes))
        for o in openings:
            mapped=next(m for m in trace['mapping'] if m['id']==o['id'])
            self.assertEqual(mapped['owner'],porch['id'])
            self.assertEqual(mapped['wall_owner'],porch['owner'])
        for change in ('missing','upper','outside'):
            bad=copy.deepcopy(a);o=next(o for o in bad['openings'] if o['owner']==porch['id'])
            if change=='missing':o['owner']='nonexistent'
            if change=='upper':o['level']='upper'
            if change=='outside':o['at']=0
            self.assertTrue(validate_analysis(bad),change)
            with self.assertRaises(ValueError):compile_analysis(bad)

    def test_redundant_attic_labels_and_small_boundary_overlap(self):
        a=copy.deepcopy(DATA)
        attic=next(o for o in a['openings'] if o['level']=='attic')
        attic['level']='upper'
        a['volumes'][0]['width']+=.01
        original=copy.deepcopy(a)
        self.assertTrue(validate_analysis(a))
        spec,notes,trace=compile_analysis(a)
        self.assertEqual(a,original)
        self.assertEqual(len(spec['upper']),1)
        self.assertTrue(any('resolved to attic' in n for n in notes))
        self.assertTrue(any('overlap shared' in n for n in notes))
        self.assertEqual(validate_analysis(trace['prepared_analysis']),[])
        self.assertEqual(hf.validate_block_model(spec),[])
        self.assertEqual(compile_analysis(trace['prepared_analysis'])[0]['ground'],spec['ground'])
        a['volumes'][0]['width']+=.15
        with self.assertRaisesRegex(ValueError,'wall volumes overlap:'):
            compile_analysis(a)

    def test_multiple_photos_cache_labels_and_review_order(self):
        hf._PHOTO_RUNS.clear()
        extra=[{'mime':'image/png','b64':'side','view':'front-right'},
               {'mime':'image/jpeg','b64':'back','view':'rear'}]
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                'services.model_pools.call_pool_json',return_value=copy.deepcopy(DATA)) as api:
            spec,_,err,token=hf.from_photo('front','image/png',extra)
            self.assertIsNone(err)
            self.assertEqual([p['b64'] for p in api.call_args.kwargs['images']],['front','side','back'])
            self.assertIn('image 2: front-right',api.call_args.args[3])
            self.assertEqual(hf.from_photo('front','image/png',extra)[3],token)
            self.assertEqual(api.call_count,1)
            changed=copy.deepcopy(extra);changed[0]['view']='left'
            self.assertNotEqual(hf.from_photo('front','image/png',changed)[3],token)
            changed[0]['b64']='other'
            hf.from_photo('front','image/png',changed)
            self.assertEqual(api.call_count,3)
            api.return_value={'analysis':copy.deepcopy(DATA),'reasons':['Compared all reference views.']}
            result,err=hf.critique(token,'render',automatic=True)
            self.assertIsNone(err)
            self.assertEqual([p['b64'] for p in api.call_args.kwargs['images']],['front','side','back','render'])
            self.assertIn('LAST image',api.call_args.args[2])
            self.assertEqual(hf._DRAFTS[token]['photo_trace']['photo_views'],['primary front','front-right','rear'])
            self.assertNotIn('b64',hf._DRAFTS[token]['photo_trace'])
            self.assertIsNotNone(hf.from_photo('front','image/png',extra*2)[2])

    def test_multipart_multi_photo_validation(self):
        import main
        import asyncio
        from types import SimpleNamespace
        class Client:
            def post(self,path,files):
                rows=list(files.items()) if isinstance(files,dict) else files
                body=b''
                for name,item in rows:
                    filename,value,*mime=item
                    if isinstance(value,str):value=value.encode()
                    header=f'--testboundary\r\nContent-Disposition: form-data; name="{name}"'
                    if filename:header+=f'; filename="{filename}"'
                    if mime:header+='\r\nContent-Type: '+mime[0]
                    body+=header.encode()+b'\r\n\r\n'+value+b'\r\n'
                body+=b'--testboundary--\r\n';messages=[];sent=False
                async def receive():
                    nonlocal sent
                    if not sent:
                        sent=True;return {'type':'http.request','body':body,'more_body':False}
                    await asyncio.sleep(3600)
                async def send(message):messages.append(message)
                scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1',
                    'method':'POST','scheme':'http','path':path,'raw_path':path.encode(),
                    'query_string':b'','root_path':'','server':('test',80),'client':('127.0.0.1',123),
                    'headers':[(b'content-type',b'multipart/form-data; boundary=testboundary')]}
                asyncio.run(main.app(scope,receive,send))
                return SimpleNamespace(status_code=next(m['status'] for m in messages if m['type']=='http.response.start'))
        client=Client()
        with patch.object(hf,'from_photo',return_value=(None,[],'offline',None)) as service:
            photo=('front.png',b'front','image/png')
            response=client.post('/api/house/facades/photo',files=[('photo',photo),
                ('supplemental',('side.jpg',b'side','image/jpeg')),('views',(None,'front-right'))])
            self.assertEqual(response.status_code,200)
            self.assertEqual(service.call_args.kwargs['supplemental'][0]['view'],'front-right')
            self.assertEqual(client.post('/api/house/facades/photo',files={'photo':photo}).status_code,200)
            for files in ([('photo',photo),('supplemental',photo)],
                          [('photo',photo),('supplemental',photo),('views',(None,'invalid'))],
                          [('photo',photo)]+[('supplemental',photo),('views',(None,'rear'))]*3,
                          [('photo',('bad.txt',b'no','text/plain'))]):
                self.assertEqual(client.post('/api/house/facades/photo',files=files).status_code,400)
            self.assertEqual(service.call_count,2)

    def test_photo10_side_garage_does_not_take_front_slots(self):
        trace=json.loads((Path(__file__).parent/'fixtures/house_photo10_trace.json').read_text())
        raw=trace['review_analysis']
        self.assertTrue(any(o['kind']=='garage_door' for o in compile_analysis(raw)[0]['ground']))
        a=faced_analysis(raw)
        door=next(o for o in a['openings'] if o['id']=='O11');door['face']='right'
        evidence=next(o for o in a['observations'] if o['feature']=='O11')
        evidence.update(face='right',image=3)
        spec,notes,compiled=compile_analysis(a)
        self.assertTrue(spec['mirror'])
        self.assertEqual(spec['blocks']['garage']['orientation'],'side')
        self.assertEqual(spec['blocks']['garage']['side_door']['leaves'],2)
        self.assertFalse(any(o['kind']=='garage_door' for o in spec['ground']))
        self.assertTrue(any(o['id']=='O11' for o in compiled['face_projection']['excluded_faces']))
        self.assertFalse(any('dropped a window' in n for n in notes))
        self.assertEqual(hf.validate_block_model(spec),[])

    def test_side_evidence_never_creates_front_story_or_roof(self):
        a=faced_analysis(DATA);expected=compile_analysis(a)[0]
        side=copy.deepcopy(a['volumes'][0]);side.update(id='side-wall',face='left',stories='two')
        side['roof']['ridge']='parallel'
        a['volumes'].append(side)
        gable={'id':'side-end','owner':'side-wall','face':'left','at':0,'width':1,'kind':'end','evidence':'Side-facing triangle.'}
        a['gables'].append(gable)
        for r in (side,gable):a['observations'].append({'feature':r['id'],'image':2,'face':'left',
            'box':{'x':.1,'y':.1,'width':.5,'height':.5},'evidence':'Synthetic side evidence.'})
        spec,_,_=compile_analysis(a)
        for key in ('upper','roof','ground'):self.assertEqual(spec[key],expected[key])
        bad=copy.deepcopy(a);bad['observations'][0]['image']=2
        with self.assertRaisesRegex(ValueError,'primary-photo evidence'):compile_analysis(bad)
        bad=copy.deepcopy(a);bad['observations'][0]['face']='rear'
        with self.assertRaisesRegex(ValueError,'face conflicts'):compile_analysis(bad)
        bad=copy.deepcopy(a)
        attic=next(o for o in bad['openings'] if o['level']=='attic')
        obs=next(o for o in bad['observations'] if o['feature']==attic['id'])
        obs['box'].update(y=.75,height=.1)
        with self.assertRaisesRegex(ValueError,'outside its owner'):compile_analysis(bad)
        bad=copy.deepcopy(a);bad['coordinate_frame']='camera'
        with self.assertRaises(ValueError):compile_analysis(bad)
        with self.assertRaisesRegex(ValueError,'not supplied'):
            hf._validate_photo_sources(a,[{}])

    def test_uncertain_structural_review_is_not_auto_applied(self):
        hf._PHOTO_RUNS.clear();a=faced_analysis(DATA)
        checks={k:'matched' for k in ('wall_faces','story_boundaries','roof_directions','opening_ownership','porch_placement')}
        checks['story_boundaries']='uncertain'
        review={'analysis':copy.deepcopy(a),'reasons':['The eave is obscured.'],'structural_review':checks}
        with patch.object(hf,'_settings',return_value={'llm_gemini_api_key':'offline'}),patch(
                'services.model_pools.call_pool_json',side_effect=[a,review]) as api:
            spec,_,error,token=hf.from_photo('faces','image/png')
            self.assertIsNone(error)
            result,error=hf.critique(token,'render',automatic=True)
            self.assertIsNone(error)
            self.assertIsNone(result['revised'])
            self.assertEqual(hf._DRAFTS[token]['spec'],spec)
            self.assertIn('story_boundaries',result['reasons'][0])
            self.assertEqual(api.call_count,2)
            checks['story_boundaries']='matched'
            api.side_effect=None;api.return_value=review
            result,error=hf.critique(token,'render',automatic=True)
            self.assertIsNone(error)
            self.assertIsNotNone(result['revised'])

    def test_supplemental_only_opening_remains_unplaced_not_fatal(self):
        a=faced_analysis(DATA)
        opening=next(o for o in a['openings'] if o['kind']=='window' and o['level']=='upper')
        obs=next(o for o in a['observations'] if o['feature']==opening['id']);obs['image']=2
        raw=copy.deepcopy(a)
        spec,notes,trace=compile_analysis(a)
        self.assertEqual(a,raw)
        self.assertEqual(trace['face_projection']['unplaced_openings'],[opening['id']])
        self.assertFalse(any(m['id']==opening['id'] for m in trace['mapping']))
        self.assertEqual(sum(o.get('story')==2 for o in spec['ground']),2)
        self.assertTrue(any('front placement unresolved' in n for n in notes))
        self.assertEqual(hf.validate_block_model(spec),[])

    def test_collective_finish_evidence_is_not_a_geometry_reference(self):
        a=faced_analysis(DATA);expected=compile_analysis(a)[0]
        obs={'feature':'finishes','image':1,'face':'front',
            'box':{'x':0,'y':0,'width':1,'height':1},'evidence':'Painted masonry and batten.'}
        a['observations'].append(obs)
        self.assertEqual(compile_analysis(a)[0],expected)
        for feature,face in (('missing-feature','front'),):
            obs.update(feature=feature,face=face)
            with self.assertRaises(ValueError):compile_analysis(a)

    def test_optional_evidence_cannot_abort_or_change_front_geometry(self):
        a=faced_analysis(DATA);expected=compile_analysis(a)[0]
        a['observations'].append({'feature':'finishes','image':2,'face':'rear',
            'box':{'x':0,'y':0,'width':1,'height':1},'evidence':'Rear siding.'})
        side=copy.deepcopy(a['volumes'][0]);side.update(id='v_garage_side',face='right')
        a['volumes'].append(side)
        a['openings'].append({'id':'side-door','owner':'v_garage_side','at':0,'width':.5,
            'kind':'garage_door','face':'right','level':'ground','count':2,'size':'tall','shutters':False})
        raw=copy.deepcopy(a)
        spec,notes,trace=compile_analysis(a)
        for key in ('blocks','ground','roof','upper','mirror'):self.assertEqual(spec[key],expected[key])
        self.assertEqual(a,raw)
        self.assertFalse(trace['face_projection']['side_garage'])
        self.assertEqual(set(trace['face_projection']['unevidenced_features']),{'v_garage_side','side-door'})
        self.assertTrue(any('no matching finish band' in n for n in notes))
        self.assertTrue(any('non-front feature lacks image evidence' in n for n in notes))
        # Evidence for a door can establish side entry even when its unused parent
        # side-volume annotation has no independent box.
        a['observations'].append({'feature':'side-door','image':2,'face':'right',
            'box':{'x':.1,'y':.1,'width':.3,'height':.3},'evidence':'Visible side door.'})
        spec,_,trace=compile_analysis(a)
        self.assertTrue(trace['face_projection']['side_garage'])
        self.assertEqual(spec['blocks']['garage']['orientation'],'side')
        # Core front massing still cannot be synthesized from missing evidence.
        a['observations']=[o for o in a['observations'] if o['feature']!=a['volumes'][0]['id']]
        with self.assertRaisesRegex(ValueError,'front structure'):compile_analysis(a)

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
