"""Run the bounded Gemini guitar experiment against an isolated served house.

From chauffeur/: python tools/author_house_object.py --out ../scratch/guitar-job
 --settings-file ../data/chauffeur_db.json --model gemini-3.5-flash

Reads only the ordinary Gemini key. Never uses a paid-key setting. Real household
data is not seeded or sent. --render-only re-renders saved recipes without API calls.
Requires Playwright/Chromium on the worker host (not on the wall panel).
"""
import argparse
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]


def read_key(settings_file):
    key = os.environ.get('GEMINI_API_KEY')
    if key:
        return key
    if settings_file:
        data = json.loads(Path(settings_file).read_text(encoding='utf-8'))
        rows = data.get('settings', {})
        rows = rows.values() if isinstance(rows, dict) else rows
        return next((r['llm_gemini_api_key'] for r in rows if r.get('llm_gemini_api_key')), '')
    return ''


class HouseRenderer:
    def __init__(self, served, page, directory):
        self.served, self.page, self.directory = served, page, Path(directory).resolve()
        self.recipe = None
        self.frozen_state = None
        from house_probe import THREE_WRAP
        def three(route):
            response = route.fetch()
            route.fulfill(response=response, body=response.body() + THREE_WRAP)
        def world(route):
            response = route.fetch()
            wrapper = """
;(function(){var original=HouseWorld.build;HouseWorld.build=function(T,d,programs){
var world=original(T,d,programs),entry=world.entries.find(e=>e.key==='program-guitar-acoustic');
var recipe=RECIPE,asset=null;
if(entry && recipe!==null){while(entry.group.children.length)entry.group.remove(entry.group.children[0]);asset=HouseRecipe.build(T,recipe,d);entry.group.add(asset.group);}
window.__authorEntry=entry;var dispose=world.dispose;world.dispose=function(){if(asset)asset.dispose();dispose();};return world;};})();
""".replace('RECIPE', json.dumps(self.recipe))
            route.fulfill(response=response, body=response.body() + b'\n' +
                          (ROOT / 'static/house_recipe.js').read_bytes() + wrapper.encode())
        def state(route):
            if self.frozen_state is None:
                self.frozen_state = route.fetch().json()
                self.frozen_state['program_objects'] = [{'id': 'author-guitar', 'kind': 'guitar',
                    'variant': 'acoustic', 'member_name': 'Alex', 'title': 'Learn acoustic guitar', 'color': '#58978b'}]
            route.fulfill(json=self.frozen_state)
        page.route('**/three*.js*', three)
        page.route('**/house_world.js*', world)
        page.route('**/api/house/state*', state)
        page.route('**/api/v2/chat/stream*', lambda r:r.fulfill(content_type='text/event-stream',body=': authoring fixture\n\n'))
        page.add_init_script("window.__authorTapped=null;addEventListener('chf-house-program',e=>{window.__authorTapped=e.detail;e.stopImmediatePropagation();},true);")
        page.set_viewport_size({'width': 1400, 'height': 1000})

    def __call__(self, label, recipe):
        self.recipe = recipe
        page = self.page
        started = time.perf_counter()
        error_start = len(self.served.errors())
        page.goto(self.served.url('house?quality=high&panel=true'))
        page.wait_for_function('window.__authorEntry && window.__hpScene && chfHouseState()')
        page.evaluate("chfHouseEnterRoom('living')")
        page.wait_for_function("chfNavProbe({settled:true}) && chfHouseMode()==='living'")
        page.wait_for_timeout(900)
        # Hide HUD only for matched art plates; tap checks still hit real geometry.
        page.add_style_tag(content='.house-life-dock,.house-exterior-glance,#house-hints,.house-hint,.argyle-fab{visibility:hidden!important}')
        room = self.directory / (label + '-room.png')
        detail = self.directory / (label + '-detail.png')
        page.screenshot(path=str(room))
        metrics = page.evaluate("""() => {
          const g=__authorEntry.group,T=THREE;g.updateMatrixWorld(true);
          const b=new T.Box3().setFromObject(g),origin=g.getWorldPosition(new T.Vector3());
          let meshes=0,triangles=0;g.traverse(o=>{if(o.isMesh){meshes++;triangles+=(o.geometry.index?o.geometry.index.count:o.geometry.attributes.position.count)/3;}});
          let samples=[];for(let i=0;i<7;i++){let start=performance.now();__hpR.render(__hpScene,__hpCam);samples.push(performance.now()-start);}samples.sort((a,b)=>a-b);
          return {meshes,triangles,minimum:b.isEmpty()?[null,null,null]:b.min.sub(origin).toArray(),maximum:b.isEmpty()?[null,null,null]:b.max.sub(origin).toArray(),
                  scene_draw_calls:__hpR.info.render.calls,scene_triangles:__hpR.info.render.triangles,
                  render_cpu_ms_median:samples[3],gpu_geometries:__hpR.info.memory.geometries,
                  gpu_textures:__hpR.info.memory.textures};
        }""")
        if recipe is None or recipe['parts']:
            point = page.evaluate("chfNavProbe({world:'program-guitar-acoustic'})")
            metrics['tap_visible'] = bool(point)
            if point:
                # Capture listener stops lesson launch; this tests real mesh-to-program mapping.
                page.mouse.click(point['cx'], point['cy'])
                page.wait_for_timeout(100)
                metrics['tap_correct'] = page.evaluate("Array.isArray(__authorTapped) && __authorTapped.includes('author-guitar')")
            else:
                metrics['tap_correct'] = False
        # Fixed camera close-up, never fit to the candidate's bounds (fair scale comparison).
        page.evaluate("""() => {
          __hpCam.position.set(6.7,3.0,13.8);__hpCam.lookAt(3.4,1.30,7.0);
          __hpCam.updateMatrixWorld(true);__hpR.render(__hpScene,__hpCam);
        }""")
        # Direct canvas export avoids HTML lesson errors or subsequent animation moving the camera.
        import base64
        encoded = page.evaluate("() => {__hpR.render(__hpScene,__hpCam);return __hpR.domElement.toDataURL('image/png').split(',')[1];}")
        detail.write_bytes(base64.b64decode(encoded))
        metrics['room_image'], metrics['detail_image'] = str(room), str(detail)
        metrics['seconds'] = round(time.perf_counter() - started, 2)
        errors = self.served.errors()[error_start:]
        metrics['browser_errors'] = errors
        lo, hi = metrics['minimum'], metrics['maximum']
        metrics['bounds_pass'] = all(v is not None for v in lo+hi) and (
            lo[0]>=-.72 and hi[0]<=.72 and lo[1]>=-.03 and hi[1]<=2.8 and lo[2]>=-.65 and hi[2]<=.65)
        metrics['gate_pass'] = bool(metrics['bounds_pass'] and metrics.get('tap_correct') and
                                    metrics['triangles']<=25000 and metrics['meshes']<=140 and not metrics['browser_errors'])
        print(label, json.dumps({k:v for k,v in metrics.items() if not k.endswith('_image')}), flush=True)
        return metrics


def write_report(directory, job):
    directory = Path(directory)
    lines = ['# Gemini guitar authoring experiment', '',
             'Status: **' + job['status'] + '**. Generated assets are previews; nothing is published.', '',
             'Model: `' + job['model'] + '`. Three-call limit; no paid-key fallback or automatic retries.',
             'Uses synthetic household data. Maker gets room context, not the authored guitar source.', '',
             '| Stage | Seconds | Input tokens | Output tokens | Thinking tokens |',
             '|---|---:|---:|---:|---:|']
    for c in job['calls']:
        m=c['metrics']
        lines.append(f"| {c['stage']} ({c['status']}) | {c.get('seconds','?')} | {m.get('promptTokenCount','?')} | {m.get('candidatesTokenCount','?')} | {m.get('thoughtsTokenCount','?')} |")
    if job.get('previous_pilot'):
        previous=json.loads((Path(job['previous_pilot'])/'job.json').read_text(encoding='utf-8'))
        lines += ['', 'Earlier pilot: '+str(len(previous['calls']))+' additional requests. '+previous.get('outcome',''),
                  'Reported usage from earlier pilot: '+str(sum(c.get('metrics',{}).get('totalTokenCount',0) for c in previous['calls']))+
                  ' tokens; the timed-out request has unknown usage. Failed requests are not free of quota cost.', '']
    lines += ['', '| Asset | Meshes | Triangles | Scene draws | Render CPU ms | Tap | Bounds |',
              '|---|---:|---:|---:|---:|---|---|']
    for label,r in job['renders'].items():
        if label=='context':continue
        lines.append(f"| {label} | {r.get('meshes','—')} | {r.get('triangles','—')} | {r.get('scene_draw_calls','—')} | {round(r.get('render_cpu_ms_median',0),2)} | {r.get('tap_correct',False)} | {r.get('bounds_pass',False)} |")
    lines += ['', 'CPU timings are short browser measurements on this workstation, not GPU timings or wall-panel FPS.',
              'The model judge reviews the first candidate. Any correction still needs human visual review.',
              job.get('budget_note',''), '']
    for label in ('baseline','candidate','final'):
        if job['renders'].get(label,{}).get('detail_image'):
            lines += [f'## {label.title()}', '', f'![{label} room]({label}-room.png)', '', f'![{label} detail]({label}-detail.png)', '']
    (directory/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    figures=[]
    for label in ('baseline','candidate','final'):
        r=job['renders'].get(label,{})
        if not r.get('detail_image'):continue
        figures.append(f'<article><h2>{label.title()}</h2><p>{r["meshes"]} meshes · {r["triangles"]:,} triangles · '
                       f'Tap: {r.get("tap_correct",False)} · Bounds: {r.get("bounds_pass",False)}</p>'
                       f'<a href="{label}-detail.png"><img src="{label}-detail.png" alt="{label} close view"></a>'
                       f'<a href="{label}-room.png"><img src="{label}-room.png" alt="{label} room view"></a></article>')
    review=directory/'review.json'
    critique=html.escape(review.read_text(encoding='utf-8')) if review.exists() else 'Not run yet.'
    (directory/'comparison.html').write_text('''<!doctype html><meta charset="utf-8"><title>Guitar authoring comparison</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{font:16px system-ui;background:#eee9df;color:#292d30;margin:24px}h1{margin-bottom:8px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px}
article{background:#fffaf0;border-radius:16px;padding:16px}img{width:100%;border-radius:8px}
pre{white-space:pre-wrap}a{color:#276c67}p{line-height:1.5}
</style><h1>Guitar authoring comparison</h1><p>Same house, placement, lighting and fixed cameras.
Gemini receives room context and constrained geometry tools, without the authored guitar source.</p>
<p>Three-call pilot. Generated results require human review. Nothing is published. <a href="report.md">Measurements</a></p>
<main>''' + ''.join(figures) + '</main><details><summary>Gemini critique of the first candidate</summary><pre>' + critique + '</pre></details>',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    parser.add_argument('--settings-file')
    parser.add_argument('--model',default='gemini-3.5-flash')
    parser.add_argument('--render-only',action='store_true')
    args=parser.parse_args()
    key=read_key(args.settings_file)
    if not args.render_only and not key:
        parser.error('Set GEMINI_API_KEY or pass --settings-file containing the ordinary Gemini key')
    # Isolate BEFORE importing storage/main; never migrate or write the live database.
    os.environ['CHAUFFEUR_DATA_DIR']=tempfile.mkdtemp(prefix='chauffeur_author_')
    os.environ.pop('HA_BASE_URL',None);os.environ.pop('HA_TOKEN',None)
    from test_house_live import live_app,_seed
    from services import house_authoring
    served=live_app()
    if served is None:
        raise RuntimeError('Playwright and Chromium required for authoring')
    _seed()
    directory=Path(args.out).resolve();directory.mkdir(parents=True,exist_ok=True)
    try:
        with served.browser() as page:
            renderer=HouseRenderer(served,page,directory)
            if args.render_only:
                job=house_authoring.create(directory,args.model)
                for label,file in [('baseline',None),('candidate','design.json'),('final','correction.json')]:
                    if file and not (directory/file).exists():continue
                    recipe=json.loads((directory/file).read_text(encoding='utf-8')) if file else None
                    if recipe:house_authoring.validate(recipe)
                    job['renders'][label]=renderer(label,recipe)
                house_authoring._save(directory/'job.json',job)
            else:
                api_request=house_authoring.gemini_request(key,args.model)
                def request(stage,prompt,images,metrics):
                    print('Gemini stage:',stage,flush=True)
                    result=api_request(stage,prompt,images,metrics)
                    print('Gemini usage:',json.dumps(metrics),flush=True)
                    return result
                try:
                    job=house_authoring.run(directory,args.model,request,renderer)
                except Exception:
                    if (directory/'job.json').exists():
                        write_report(directory,json.loads((directory/'job.json').read_text(encoding='utf-8')))
                    raise
            write_report(directory,job)
            print('Report:',directory/'report.md',flush=True)
    finally:
        served.stop()


if __name__=='__main__':
    main()
