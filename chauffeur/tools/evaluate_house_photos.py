"""Opt-in, bounded live comparison. Run from the repository root; never saves facades.

Example: python chauffeur/tools/evaluate_house_photos.py --live
  --settings data/chauffeur_db.json --out scratch/photo-comparison
Requires the app's Playwright test dependencies. Outputs contain public references,
raw model responses and renders, never settings or image payloads. Labels stay local.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def score(structure, case):
    """Coarse pre-labeled checks, not an architectural ground-truth oracle."""
    volumes = structure.get('volumes', [])
    checks = []
    for expected in case['regions']:
        for fraction in (.25,.5,.75):
            x = expected['at'] + expected['width']*fraction
            found = next((v for v in volumes if v['at'] <= x < v['at']+v['width']), None)
            roof_scored=expected.get('score_roof',True)
            ridge=bool(found and found['roof']['ridge']==expected['ridge']) if roof_scored else None
            form=bool(found and found['roof']['form']==expected['form']) if roof_scored and expected.get('score_form',True) else None
            checks.append({'at': x, 'stories': bool(found and found['stories']==expected['stories']),
                           'ridge':ridge, 'form':form})
    boundaries = [v['at'] for v in volumes if v['at'] > .05]
    expected_edges = [v['at'] for v in case['regions'][1:]]
    tolerance = .15 if case['id']=='hood' else .12
    massing = len(volumes)==len(case['regions']) and all(any(abs(a-b)<=tolerance for b in boundaries) for a in expected_edges)
    broad_porch = sum(p['width'] for p in structure.get('porches',[]) if p['roof']!='open') > .25
    return {'regions':checks, 'stories':all(c['stories'] for c in checks),
            'roof_directions':all(c['ridge'] for c in checks if c['ridge'] is not None) if any(c['ridge'] is not None for c in checks) else None,
            'roof_forms':all(c['form'] for c in checks if c['form'] is not None) if any(c['form'] is not None for c in checks) else None,
            'massing_widths':massing if case.get('score_massing',True) else None,
            'broad_porch':broad_porch==case['covered_porch'],
            'note':'Three samples per labeled region; requires visual adjudication. Small entry covers and projections are not scored automatically.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true',help='Explicitly enable provider requests')
    p.add_argument('--settings',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--manifest',type=Path,default=ROOT/'chauffeur/tests/fixtures/house_photo_eval/manifest.json')
    p.add_argument('--models',default='gemini-3.1-flash-lite,gemini-2.5-flash')
    p.add_argument('--max-requests',type=int,default=24)
    p.add_argument('--deadline',type=int,default=600,help='Seconds; each request also has the existing timeout')
    p.add_argument('--cases',default='',help='Optional comma-separated subset of manifest IDs')
    p.add_argument('--structure-only',action='store_true',help='Measure recognition without review/detail requests')
    p.add_argument('--structure-prompt-file',type=Path,help='Experiment override; does not edit production prompts')
    p.add_argument('--comparison-prompt-file',type=Path,help='Paired structure-only baseline/candidate experiment')
    p.add_argument('--repeats',type=int,default=1,help='Paired experiment repetitions, 1..3')
    args=p.parse_args()
    if not args.live:p.error('--live required; this tool sends real provider requests')
    if not 1<=args.repeats<=3:p.error('repeats must be 1..3')
    if args.comparison_prompt_file and (not args.structure_only or args.structure_prompt_file):p.error('comparison requires structure-only and no other prompt override')
    if args.repeats!=1 and not args.comparison_prompt_file:p.error('repeats requires comparison-prompt-file')
    if not 1<=args.max_requests<=36 or not 1<=args.deadline<=1200:p.error('request cap 1..36, deadline 1..1200')
    models=args.models.split(',')
    if not models or any(not m.startswith('gemini-') or 'flash' not in m for m in models):p.error('Flash/Lite model IDs only')
    args.out.mkdir(parents=True,exist_ok=True)
    output=args.out/'results.json'
    if output.exists():p.error('refusing to overwrite/repeat an existing evaluation')
    settings_path=args.settings.resolve()
    if settings_path.suffix=='.sqlite3':
        with sqlite3.connect('file:'+settings_path.as_posix()+'?mode=ro',uri=True) as db:
            settings=json.loads(db.execute('select data from settings limit 1').fetchone()[0])
    else:settings=next(iter(json.loads(settings_path.read_text())['settings'].values()))
    key=settings.get('llm_gemini_api_key')
    if not key or not key.startswith('AIza'):p.error('configured free Gemini key required')
    manifest=json.loads(args.manifest.read_text())
    cases=[c for c in manifest['cases'] if not args.cases or c['id'] in args.cases.split(',')]
    if not cases:p.error('no cases selected')
    photos={}
    for case in cases:
        path=ROOT/case['image']
        if not path.exists():
            if not case.get('download_url'):p.error('missing reference '+str(path))
            with urllib.request.urlopen(case['download_url'],timeout=30) as response: data=response.read(8_000_001)
            if len(data)>8_000_000:raise ValueError('reference too large')
            if hashlib.sha256(data).hexdigest()!=case['sha256']:raise ValueError('reference hash changed')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=case['sha256']:raise ValueError('reference hash changed: '+case['id'])
        photos[case['id']]=base64.b64encode(data).decode()
    os.environ['CHAUFFEUR_DATA_DIR']=tempfile.mkdtemp(prefix='house_eval_')
    sys.path[:0]=[str(ROOT/'chauffeur'),str(ROOT/'chauffeur/tests')]
    from services import house_facade as hf, house_photo_structure as hs, model_pools, llm_budget, ha_api
    from live_app import live_app
    from house_live_common import _seed, DAY_LOCK_JS, SEED_RNG_JS
    if args.structure_prompt_file:
        hs.STRUCTURE_PROMPT=args.structure_prompt_file.read_text(encoding='utf-8')
    prompts={'baseline':hs.STRUCTURE_PROMPT}
    if args.comparison_prompt_file:prompts['candidate']=args.comparison_prompt_file.read_text(encoding='utf-8')
    budget_path=settings_path.parent/'llm_budget.sqlite3'
    llm_budget.sqlite3=types.SimpleNamespace(connect=lambda _path,**kw:sqlite3.connect(budget_path,**kw))
    result={'models':models,'max_requests':args.max_requests,'deadline_seconds':args.deadline,
            'structure_only':args.structure_only,'score_version':4,'prompts':prompts,'manifest':manifest,'events':[],'jobs':[],
            'structure_prompt_sha256':hashlib.sha256(hs.STRUCTURE_PROMPT.encode()).hexdigest(),
            'detail_prompt_sha256':hashlib.sha256(hs.DETAIL_PROMPT.encode()).hexdigest(), 'wire_requests':0}
    jobs=[{'id':case['id'],'model':model,'variant':variant,'repeat':repeat+1,'state':'upload','retries':0}
          for repeat in range(args.repeats) for case in cases for model in models
          for variant in (list(prompts) if repeat%2==0 else list(reversed(prompts)))]
    result['jobs']=jobs
    current=None;deadline=time.monotonic()+args.deadline
    def save():output.write_text(json.dumps(result,indent=2)+'\n')
    original_call=model_pools.call_pool_json
    def call(*a,**kw):
        if result['wire_requests']>=args.max_requests or time.monotonic()>=deadline:raise RuntimeError('Evaluation bound reached')
        pinned={'llm_gemini_api_key':key,'model_pool_flash':current['model']}
        kw.update(settings=pinned,max_models=1,timeout_s=min(90,deadline-time.monotonic()),total_timeout_s=min(90,deadline-time.monotonic()))
        attempts=kw.get('attempts',[]);before=len(attempts);started=time.monotonic()
        response=original_call(*a,**kw)
        count=len(attempts)-before;result['wire_requests']+=count
        props=kw['response_schema']['properties']
        stage='review' if 'structure' in props else 'details' if 'openings' in props else 'structure'
        event={'case':current['id'],'model':current['model'],'variant':current['variant'],'repeat':current['repeat'],'stage':stage,'wire_requests':count,
               'seconds':round(time.monotonic()-started,2),'image_count':len(kw.get('images',[])), 'response':copy.deepcopy(response)}
        result['events'].append(event);save()
        print(json.dumps({k:v for k,v in event.items() if k!='response'}),flush=True)
        return response
    model_pools.call_pool_json=call
    hf._settings=lambda:{'llm_gemini_api_key':key,'model_pool_flash':current['model']}
    ha_api.get_states=lambda *a,**kw:[];ha_api.get_state=lambda *a,**kw:None
    save();served=live_app(_seed)
    if not served:raise RuntimeError('Browser unavailable')
    try:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS);page.add_init_script(SEED_RNG_JS)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=200,body=''))
            page.route('**/api/house/facades/critique*',lambda r:r.abort())
            while time.monotonic()<deadline and result['wire_requests']<args.max_requests:
                pending=[j for j in jobs if j['state'] in ('upload','review')]
                if not pending:break
                ready=[j for j in pending if model_pools._cooldowns.get(j['model'],0)<=time.time() and j.get('retry_at',0)<=time.time()]
                if not ready:time.sleep(2);continue
                current=ready[0];case=next(c for c in cases if c['id']==current['id'])
                hs.STRUCTURE_PROMPT=prompts[current['variant']]
                error=None
                if current['state']=='upload':
                    # Photo caches are input-keyed in production. Each model needs its own analysis.
                    hf._PHOTO_RUNS.clear()
                    spec,notes,error,token=hf.from_photo(photos[case['id']],'image/jpeg')
                    current.update(notes=notes,upload_error=error)
                    if not error:
                        current.update(token=token,initial_spec=spec,state='review')
                        entry=hf.draft_for(token)
                        current['initial_score']=score(entry['structure'],case)
                        current['deterministic']=hs.compile_structure(entry['structure'])==hs.compile_structure(copy.deepcopy(entry['structure']))
                        if args.structure_only:current['state']='complete'
                if current['state']=='review' and not error:
                    token=current['token'];entry=hf.draft_for(token)
                    if not current.get('render'):
                        # A plain draft prevents UI automation from spending an uncounted request.
                        plain=hf.issue_draft(entry['spec'])
                        page.goto(served.url('house')+'?draft='+plain+'&quality=high&day=1&editor=1')
                        page.wait_for_function('window.chfFacade && window.chfFacade() && window.chfNavProbe({settled:true})',timeout=120000)
                        encoded=page.evaluate('window.chfCapture()').split(',',1)[1]
                        name=current['model']+'-'+current['id']+'.png'
                        (args.out/name).write_bytes(base64.b64decode(encoded));current['render']=name
                    encoded=base64.b64encode((args.out/current['render']).read_bytes()).decode()
                    completed,error=hf.critique(token,encoded,automatic=True)
                    current['completion']=completed;current['trace']=copy.deepcopy(entry['photo_trace'])
                    if entry.get('reviewed_structure'):
                        current['reviewed_score']=score(entry['reviewed_structure']['structure'],case)
                    if current['trace'].get('detail_geometry_preserved'):
                        current['state']='complete'
                    else:error=error or current['trace'].get('detail_error') or current['trace'].get('review_error') or 'incomplete review'
                if error:
                    current['last_error']=error
                    transient=any(code in error for code in ('503','502','504','429','paused','timeout','time budget'))
                    if transient and current['retries']<1:
                        current['retries']+=1;current['retry_at']=time.time()+125
                    else:current['state']='failed'
                save()
    finally:
        served.stop()
        result['stopped_with_pending']=any(j['state'] in ('upload','review') for j in jobs)
        save()
    print('DONE '+str(output)+' wire_requests='+str(result['wire_requests']),flush=True)


if __name__=='__main__':main()
