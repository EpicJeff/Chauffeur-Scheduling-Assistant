"""Task 4: migrated awning draw buffers and rain paths match 0ec59a62.

Private plans, when requested, travel only on stdin. Fixtures are synthetic.
"""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Deliberately import before running Node: this is the test-first migration gate.
from services.twin_awning_migration import migrate_awnings
from test_twin_awning_golden_js import DRIVER as GOLDEN_DRIVER, FIXTURE, PRE_MIGRATION, baseline_sources, legacy_flatten
from twin_editor_dom import run_node


def fixture():
    outline = [[0, 0], [20, 0], [20, 12], [0, 12]]
    return {'schema': 2, 'units': 'ft', 'materials': {}, 'site': {}, 'buildings': [{
        'id': 'b', 'position': [0, 0], 'base': 0, 'rotation': 0,
        'levels': [{'id': 'L1', 'elevation': 0, 'ceiling': 8, 'outline': outline}],
        'walls': [{'id': 'w'+str(i), 'from': a, 'to': outline[(i+1) % 4],
                   'level': 'L1', 'height': 8, 'thickness': .5, 'exterior': True}
                  for i, a in enumerate(outline)],
        'rooms': [], 'openings': [], 'porches': [], 'lights': [], 'items': [], 'anchors': [],
        'roof': {'sections': [{'id': 'main', 'roof': 'main', 'level': 'L1', 'kind': 'gable',
                              'rect': [0, 0, 20, 12], 'ridge': 'x', 'plate': 8, 'pitch': 4, 'overhang': 1}],
                 'extensions': [{'id': 'shade', 'kind': 'awning', 'section': 'main', 'wall': 'w0',
                                 'x0': 3, 'x1': 15, 'depth': 3, 'pitch': 3, 'eave': 7,
                                 'brackets': 2, 'gutter': False,
                                 'src': {'sheet': 'fixture', 'page': 0, 'step': 'roof'}}], 'flags': []}}]}


def cases():
    result = []
    for name in ['ordinary', 'no-wall', 'second-storey', 'person-edit', 'ghost', 'gutter', 'zero-brackets', 'absent-brackets', 'low-pitch']:
        old = fixture()
        b, aw = old['buildings'][0], old['buildings'][0]['roof']['extensions'][0]
        if name == 'no-wall':
            b['walls'] = []
        elif name == 'second-storey':
            b['levels'].append({'id': 'L2', 'elevation': 9, 'ceiling': 8, 'outline': deepcopy(b['levels'][0]['outline'])})
            b['walls'].extend([{**deepcopy(w), 'id': 'upper-'+w['id'], 'level': 'L2'} for w in b['walls']])
            b['roof']['sections'][0].update(plate=17, level='L2')
            aw.update(eave=15, wall='upper-w0', level='L2')
        elif name == 'person-edit':
            aw.update(x1=17.25, depth=4.25, pitch=2.5, eave=7.1, brackets=3)
            aw['src']['person'] = True
        elif name == 'ghost':
            aw['state'] = 'ghost'
        elif name == 'gutter':
            aw['gutter'] = True
        elif name == 'zero-brackets':
            aw['brackets'] = 0
        elif name == 'absent-brackets':
            del aw['brackets']
        elif name == 'low-pitch':
            aw['pitch'] = .5
        new, notes = migrate_awnings(old)
        result.append({'name': name, 'old': old, 'current': new, 'notes': notes})
    # I1: preserve the exact legacy wall frame on both span axes. Host
    # acceptance is independent of placement, including real diagonals.
    for side in (0, 1):
        for angle in (None, .5, 2, 45):
            for stored in (False, True):
                old = fixture()
                b = old['buildings'][0]
                wall = b['walls'][side]
                skew = .0011 if angle is None else math.tan(math.radians(angle)) * (20 if side == 0 else 12)
                wall['to'][1 if side == 0 else 0] += -skew if side == 0 else skew
                b['walls'] = [wall]  # only this eligible wall, also for the unbound case
                if side == 1:
                    wall['from'][0], wall['to'][0] = 5, 5+skew
                    b['roof']['sections'][0]['rect'][2] = 5
                    b['levels'][0]['outline'] = [[0, 0], wall['from'], wall['to'], [0, 12]]
                else:
                    # Keep the former unbound nearest-wall sample within its
                    # unchanged 2 ft search cap even on the 45-degree case.
                    b['roof']['sections'][0]['rect'][1] = wall['to'][1]*9/20
                aw = b['roof']['extensions'][0]
                aw.update(x0=3 if side == 0 else 1, x1=15 if side == 0 else 9, depth=4)
                if stored:
                    aw['wall'] = wall['id']
                else:
                    aw.pop('wall')
                name = 'skew-%s-%s-%s' % (side, '0011' if angle is None else angle, 'stored' if stored else 'unbound')
                new, notes = migrate_awnings(old)
                result.append({'name': name, 'old': old, 'current': new, 'notes': notes,
                               'hosted': angle is None or angle <= 1})
    # M1/M2: the old slab finish resolves from the building, while gutters
    # inherit their parent's slot. A level/unused old awning slot cannot win.
    old = fixture()
    b = old['buildings'][0]
    b['materials'] = {'roof': {'id': 'roof', 'color': '#aa3311'}}
    b['levels'][0]['materials'] = {'roof': {'id': 'roof', 'color': '#1144aa'}}
    b['roof']['sections'][0]['materials'] = {'gutter': {'id': 'gutter', 'color': '#ff0000'}}
    b['roof']['extensions'][0]['materials'] = {'roof': {'id': 'roof', 'color': '#11aa44'}}
    new, notes = migrate_awnings(old)
    result.append({'name': 'level-finish', 'old': old, 'current': new, 'notes': notes})
    old = fixture()
    old['buildings'][0]['roof']['sections'][0]['materials'] = {'gutter': {'id': 'gutter', 'color': '#ff0000'}}
    old['buildings'][0]['roof']['extensions'][0]['gutter'] = True
    new, notes = migrate_awnings(old)
    result.append({'name': 'parent-gutter', 'old': old, 'current': new, 'notes': notes})
    for count in (14, 3.0, 2.5, True):
        old = fixture()
        old['buildings'][0]['roof']['extensions'][0]['brackets'] = count
        new, notes = migrate_awnings(old)
        result.append({'name': 'count-'+str(count), 'old': old, 'current': new, 'notes': notes})
    old = fixture()
    old['buildings'][0]['roof']['extensions'][0].update(state='ghost', gutter=True)
    new, notes = migrate_awnings(old)
    result.append({'name': 'ghost-gutter', 'old': old, 'current': new, 'notes': notes})
    old = fixture()
    old['buildings'][0]['roof']['extensions'] = [{'id': 'continuation', 'kind': 'shed_continuation',
        'section': 'main', 'to_x': 26, 'pitch': 3, 'overhang': 1}]
    new, notes = migrate_awnings(old)
    result.append({'name': 'shed-continuation', 'old': old, 'current': new, 'notes': notes})
    return result


DRIVER = GOLDEN_DRIVER[:GOLDEN_DRIVER.index(FIXTURE)] + FIXTURE.replace('const kit=()', 'let kit=()') + r"""
const oldRain=await import(urls.get('static/twin/sky/eave_streams.js'));
const oldGutters=await import(urls.get('static/twin/gutters.js'));
const rain=await import(file('static/twin/sky/eave_streams.js'));
const gutters=await import(file('static/twin/gutters.js'));
let useDefaultKit=false;const defaultKit=kit;kit=()=>{const k=defaultKit();if(!useDefaultKit)k.materials.roof.asset='standing_seam';return k;};
function vertices(list){const points=[];for(const m of list){const p=m.geometry.attributes.position,index=m.geometry.index,v=new THREE.Vector3();
 for(let i=0;i<(index?.count??p.count);i++){v.fromBufferAttribute(p,index?index.getX(i):i).applyMatrix4(m.matrixWorld).divideScalar(.3048);points.push(v.toArray());}}
 return points;}
function category(m){if(m.userData.surfaceKind==='gutter')return 'gutters';
 if((m.userData.part||'').startsWith('support:'))return 'brackets';
 const p=m.geometry.parameters;if(p?.width===.065&&p.height===.08)return 'seams';
 if(p?.width===.3&&p.height===.3)return 'brackets';
 return 'slab';}
const finishEvidence=list=>[...new Set(list.map(m=>JSON.stringify([material(m.material),m.material.color?.getHexString()??null])))].sort();
function geometryDelta(before,after){const a=vertices(before),b=vertices(after),distance=(p,q)=>Math.hypot(...p.map((v,i)=>v-q[i]));
 const nearest=(a,b)=>Math.max(0,...a.map(p=>Math.min(Infinity,...b.map(q=>distance(p,q)))));
 const ordered=points=>[...points].sort((p,q)=>p[0]-q[0]||p[1]-q[1]||p[2]-q[2]);
 const x=ordered(a),y=ordered(b),paired=a.length===b.length?Math.max(0,...x.map((p,i)=>distance(p,y[i]))):null;
 return {old_triangles:a.length/3,current_triangles:b.length/3,old_vertices:a.length,current_vertices:b.length,
  nearest_max_ft:Math.max(nearest(a,b),nearest(b,a)),ordered_max_ft:paired};}
const round=value=>typeof value==='number'?Math.round(value*1e6)/1e6:Array.isArray(value)?value.map(round)
 :value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([k,v])=>[k,round(v)])):value;
const sorted=value=>value.map(round).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
function rainEvidence(plan,out,module,gutterModule,captured=true){const runs=gutterModule.gutterRuns(plan,out.roofSurfaces),spouts=gutterModule.downspouts(plan,runs),
 flow=module.eaveInstances(plan,out.roofSurfaces,kit(),captured?{runs,spouts}:null);
 return {runs:sorted(runs.map(r=>({length:r.length,segments:r.segments.map(s=>({a:s.a,b:s.b,outward:s.outward}))}))),
  spouts:sorted(spouts.map(s=>({top:s.top,mount:s.mount,path:s.path,outlet:s.outlet,share:s.share}))),
  eaves:sorted(flow.eaves.map(e=>({a:e.a,b:e.b,outward:e.outward,pan:e.pan,pitch:e.pitch,gridStart:e.gridStart}))),
  streams:sorted(flow.instances.map(i=>({top:i.top,bottom:i.bottom,landing:i.landing,seed:i.seed,rank:i.rank,
   cellStep:i.cellStep,sheetCap:i.sheetCap,angle:i.angle,eaveS:i.eaveS,catchment:i.catchment,catchmentFt:i.catchmentFt}))),
  pours:sorted(flow.pours.map(i=>({top:i.top,bottom:i.bottom,catchment:i.catchment,catchmentFt:i.catchmentFt})))};}
for(const c of input.cases)await test(c.name+'_migration_runtime',async()=>{
 const old=await build(c.old,oldG,true),current=await build(c.current,G,!['ghost','no-wall','ghost-gutter'].includes(c.name)),b=c.current.buildings[0];
 assert.equal((b.roof.extensions||[]).length,0,'no obsolete extension remains');
 if(c.name==='shed-continuation'){
  assert.ok(b.roof.sections.some(s=>s.id==='continuation'&&s.kind==='shed'&&!isSupported(s)),'continuation is ordinary shed roof');
  assert.ok(current.out.pickObjects.get('b:continuation'),'ordinary shed remains selectable');
 }else{
  const s=b.roof.sections.find(s=>s.id==='shade');assert.ok(isSupported(s));
  assert.equal(s.thickness_ft,.3);assert.equal(s.fascia,false);
  if(c.name==='no-wall'){
   assert.equal(s.host,undefined);assert.equal(s.state,'ghost');
   const objects=(current.out.pieces.get('b:shade')||[]).filter(o=>o.isMesh);
   assert.ok(objects.length>0&&objects.every(m=>m.userData.ghost),'lost wall stays fixable as a ghost');
  }else if(['ghost','ghost-gutter'].includes(c.name)){
   const objects=(current.out.pieces.get('b:shade')||[]).filter(o=>o.isMesh),delta=geometryDelta(old.awnings,objects);
   console.log('MIGRATION_GEOMETRY '+JSON.stringify({fixture:c.name,part:'ghost-group',...delta}));
   assert.equal(delta.current_triangles,delta.old_triangles);assert.ok(delta.nearest_max_ft<=.01,'ghost group vertices keep the ordinary roof shape');
   assert.ok(delta.ordered_max_ft<=.01,'ghost group vertex-by-vertex comparison');
   assert.ok(objects.length>0&&objects.every(m=>m.userData.ghost),'ghost state carries into the drawn ghost batch');
  }
  else for(const part of ['slab','seams','brackets','gutters']){
   const before=old.awnings.filter(m=>category(m)===part),after=current.awnings.filter(m=>category(m)===part),delta=geometryDelta(before,after);
   console.log('MIGRATION_GEOMETRY '+JSON.stringify({fixture:c.name,part,...delta}));
   assert.equal(delta.current_triangles,delta.old_triangles,part+' triangle count');
   assert.ok(delta.nearest_max_ft<=.01,part+' vertex maximum distance '+delta.nearest_max_ft+' ft');
   assert.ok(delta.ordered_max_ft<=.01,part+' sorted vertex-by-vertex maximum distance '+delta.ordered_max_ft+' ft');
   assert.deepEqual(finishEvidence(after),finishEvidence(before),part+' uses the same material key, colour and flags');
  }
  const pick=current.out.pickObjects.get('b:shade');assert.ok(pick?.geometry.attributes.position.count>0,'migrated roof has a real roof pick');
  if(c.hosted!==undefined)assert.equal(!!s.host,c.hosted,'host accepts one degree without changing placement');
  if(c.name==='ghost-gutter'){assert.equal(gutters.gutterRuns(c.current,current.out.roofSurfaces).length,0,'a ghost has no solid gutter or spout');assert.ok(!(current.out.pieces.get('b:shade')||[]).some(m=>m.userData.surfaceKind==='gutter'));}
  if(s.support.count>0)assert.ok((pick.userData.partObjects||[]).some(p=>(p.object.userData.part||'').startsWith('support:')),'support parts can be picked');
  if(c.name==='person-edit')assert.equal(s.src.person,true);
 }
 dispose(old.out);dispose(current.out);for(const m of [...old.awnings,...current.awnings])m.geometry.dispose();
 if(c.name==='ordinary'){
  const before=await build(c.old,oldG),after=await build(c.current,G),levels=[];
  after.out.root.traverse(node=>{if(node.userData.supportedRoof===true)levels.push(stats(meshes(node)));});
  console.log('FIXTURE_MIGRATION_COST '+JSON.stringify({before:stats(meshes(before.out.root)),after:stats(meshes(after.out.root)),supported_per_level:levels}));
  assert.equal(levels.length,1);assert.equal(levels[0].draws,2);assert.equal(levels[0].triangles,132);
  dispose(before.out);dispose(after.out);
 }
});
if(input.cases.some(c=>c.name==='skew-0-0.5-stored'))await test('ordinary_rotated_roof_can_enable_fascia',async()=>{
 const c=input.cases.find(c=>c.name==='skew-0-0.5-stored');if(!c)return;
 const plan=structuredClone(c.current),s=plan.buildings[0].roof.sections.find(s=>isSupported(s));s.fascia=true;plan.buildings[0].materials={...plan.buildings[0].materials,fascia:{id:'trim',color:'#e713ae'}};
 const current=await build(plan,G,true);
 const observed=current.awnings.map(m=>({color:m.material.color?.getHexString(),key:m.material.userData.materialKey,triangles:(m.geometry.index?.count??m.geometry.attributes.position.count)/3}));
 console.log('ROTATED_FASCIA '+JSON.stringify(observed));
 assert.ok(observed.some(m=>m.color==='e713ae'&&m.triangles>=8),'ordinary fascia field remains usable after rotation '+JSON.stringify(observed));
 dispose(current.out);for(const m of current.awnings)m.geometry.dispose();
});
if(input.cases.some(c=>c.name==='ghost-gutter'))await test('ghost_gutter_cold_streams_equal_0ec59a62',async()=>{
 const c=input.cases.find(c=>c.name==='ghost-gutter'),old=await build(c.old,oldG),current=await build(c.current,G);
 try{
  const before=rainEvidence(c.old,old.out,oldRain,oldGutters,false),after=rainEvidence(c.current,current.out,rain,gutters,false);
  assert.ok(before.streams.length>0,'the old ghost keeps its eave streams without a gutter snapshot');
  console.log('GHOST_COLD_RAIN '+JSON.stringify({oldEaves:before.eaves.length,currentEaves:after.eaves.length,oldStreams:before.streams.length,currentStreams:after.streams.length}));
  for(const key of ['runs','spouts','eaves','streams','pours'])assert.deepEqual(after[key],before[key],key+' cold ghost physical output');
 }finally{dispose(old.out);dispose(current.out);}
});
for(const c of input.cases.filter(c=>!['no-wall','ghost','ghost-gutter','shed-continuation'].includes(c.name)))await test(c.name+'_rain_paths_equal_0ec59a62',async()=>{
 const old=await build(c.old,oldG),current=await build(c.current,G),before=rainEvidence(c.old,old.out,oldRain,oldGutters),after=rainEvidence(c.current,current.out,rain,gutters);
 console.log('MIGRATION_RAIN '+JSON.stringify({fixture:c.name,old:Object.fromEntries(Object.entries(before).map(([k,v])=>[k,v.length])),
  current:Object.fromEntries(Object.entries(after).map(([k,v])=>[k,v.length]))}));
 for(const key of ['runs','spouts','eaves','streams','pours']){
  if(c.name.startsWith('skew-')){
   const same=(a,b,path)=>{assert.equal(typeof a,typeof b,path);if(typeof a==='number')assert.ok(Math.abs(a-b)<=1e-5,path+' numerical difference '+Math.abs(a-b));
    else if(a&&typeof a==='object'){assert.deepEqual(Object.keys(a),Object.keys(b),path+' keys');for(const k of Object.keys(a))same(a[k],b[k],path+'.'+k);}else assert.equal(a,b,path);};
   same(after[key],before[key],key);
  }else assert.deepEqual(after[key],before[key],key+' physical output');
 }dispose(old.out);dispose(current.out);
});
if(input.ownerExport){useDefaultKit=true;const owner=JSON.parse(readFileSync(0,'utf-8'));
 if(input.measureOnly){
  const beforeURLs=new Map(),paths=Object.keys(input.beforeSources);
  for(const [path,original] of Object.entries(input.beforeSources)){
   const source=original.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{const url=new URL(s,file(path)).href,ref=paths.find(p=>file(p)===url);return a+(ref?'timing:'+ref:url)+b;});
   beforeURLs.set(path,'data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  }
  registerHooks({resolve(spec,ctx,next){return spec.startsWith('timing:')?{url:beforeURLs.get(spec.slice(7)),shortCircuit:true}:next(spec,ctx);}});
  const beforeModule=await import(beforeURLs.get('static/twin/twin_generator.js'));
  await test('owner_build_ms_median_five',async()=>{const times={before:[],after:[]};
   for(const [module,plan] of [[beforeModule,owner.old],[G,owner.current]]){const b=await build(plan,module);dispose(b.out);}
   for(let i=0;i<5;i++)for(const [label,module,plan] of i%2?[['after',G,owner.current],['before',beforeModule,owner.old]]:[['before',beforeModule,owner.old],['after',G,owner.current]]){
    const b=await build(plan,module);times[label].push(b.ms);dispose(b.out);
   }
   const median=a=>[...a].sort((a,b)=>a-b)[2];console.log('MIGRATION_BUILD_MS '+JSON.stringify({baseline:input.beforeCommit,samples:times,median:{before:median(times.before),after:median(times.after)}}));
  });
 }else{
  await test('owner_migrated_geometry_and_walled_hash_equal_0ec59a62',async()=>{
   const oldIds=owner.old.buildings.flatMap(b=>(b.roof?.extensions||[]).filter(e=>e.kind==='awning').map(e=>b.id+':'+e.id)).sort(),
    newIds=owner.current.buildings.flatMap(b=>(b.roof?.sections||[]).filter(isSupported).map(s=>b.id+':'+(s.roof||s.id))).sort();
   assert.deepEqual(newIds,oldIds,'the same owner roof ids migrate exactly once');
   console.log('OWNER_MIGRATION_RECORDS '+JSON.stringify({before_awnings:oldIds.length,after_supported:newIds.length,ids_hash:sha(newIds),remaining_extensions:owner.current.buildings.reduce((n,b)=>n+(b.roof?.extensions||[]).length,0)}));
   const old=await build(owner.old,oldG,true),current=await build(owner.current,G,true),before=stats(meshes(old.out.root)),after=stats(meshes(current.out.root));
   console.log('OWNER_WALLED '+JSON.stringify({old:before,current:after}));assert.equal(after.hash,before.hash,'owner walled buffers');
   const parts={};for(const part of ['slab','seams','brackets','gutters']){
    const delta=geometryDelta(old.awnings.filter(m=>category(m)===part),current.awnings.filter(m=>category(m)===part));parts[part]=delta;
    assert.equal(delta.current_triangles,delta.old_triangles,part+' owner triangles');assert.ok(delta.ordered_max_ft<=.01,part+' owner vertex-by-vertex tolerance');
    assert.deepEqual(finishEvidence(current.awnings.filter(m=>category(m)===part)),finishEvidence(old.awnings.filter(m=>category(m)===part)),part+' owner material, colour and flags');
   }
   console.log('OWNER_MIGRATION_GEOMETRY '+JSON.stringify(parts));dispose(old.out);dispose(current.out);
   for(const m of [...old.awnings,...current.awnings])m.geometry.dispose();
  });
  await test('owner_gutters_and_streams_keep_physical_output',async()=>{
   const old=await build(owner.old,oldG),current=await build(owner.current,G),before=rainEvidence(owner.old,old.out,oldRain,oldGutters),after=rainEvidence(owner.current,current.out,rain,gutters);
   const perLevel=[];current.out.root.traverse(node=>{if(node.userData.supportedRoof===true){const cost=stats(meshes(node));
    perLevel.push({level_hash:sha(node.name),draws:cost.draws,meshes:cost.meshes,triangles:cost.triangles});}});
   console.log('OWNER_MIGRATION_COST '+JSON.stringify({before:stats(meshes(old.out.root)),after:stats(meshes(current.out.root)),supported_per_level:perLevel}));
   const summary={};for(const key of Object.keys(before)){summary[key]={old:before[key].length,current:after[key].length,old_hash:sha(before[key]),current_hash:sha(after[key])};}
   console.log('OWNER_MIGRATION_RAIN '+JSON.stringify(summary));
   if(sha(after.streams)!==sha(before.streams)&&after.streams.length===before.streams.length){const fields={};
    const maxDelta=(a,b)=>typeof a==='number'&&typeof b==='number'?Math.abs(a-b):Array.isArray(a)&&Array.isArray(b)?Math.max(0,...a.map((v,i)=>maxDelta(v,b[i]))):null;
    for(let i=0;i<after.streams.length;i++)for(const key of Object.keys(after.streams[i]))if(JSON.stringify(after.streams[i][key])!==JSON.stringify(before.streams[i][key])){
     const row=fields[key]||={changed:0,max_delta:0};row.changed++;row.max_delta=Math.max(row.max_delta,maxDelta(after.streams[i][key],before.streams[i][key])||0);
    }console.log('OWNER_STREAM_FIELD_DELTAS '+JSON.stringify(fields));
   }
   for(const key of Object.keys(before))assert.equal(sha(after[key]),sha(before[key]),key+' owner physical output hash');
   dispose(old.out);dispose(current.out);
  });
 }
}
finish();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-export', type=Path)
    parser.add_argument('--measure-only', action='store_true', help='Quiet owner build medians of five against pre-migration git runtime')
    parser.add_argument('--owner-only', action='store_true', help='Run only owner evidence, without repeating public fixtures')
    args = parser.parse_args()
    payload = {'root': ROOT.as_posix(), 'sources': baseline_sources(), 'cases': [] if args.measure_only or args.owner_only else cases(),
               'ownerExport': str(args.owner_export) if args.owner_export else None, 'measureOnly': args.measure_only}
    if not args.owner_export:
        code, output = run_node(DRIVER, payload, timeout=300)
    else:
        if args.measure_only:
            payload.update(beforeSources=baseline_sources(PRE_MIGRATION), beforeCommit=PRE_MIGRATION)
        from services.twin_model_bridge import flatten as flatten_model
        model = json.loads(args.owner_export.read_text(encoding='utf-8'))['model']
        old = legacy_flatten(model)
        current = flatten_model(migrate_awnings(model)[0])
        stdin = json.dumps({'old': old, 'current': current})
        with tempfile.TemporaryDirectory(prefix='awning_migration_') as directory:
            driver, job = Path(directory) / 'driver.mjs', Path(directory) / 'job.json'
            driver.write_text(DRIVER, encoding='utf-8')
            job.write_text(json.dumps(payload), encoding='utf-8')
            result = subprocess.run([shutil.which('node'), str(driver), str(job)], input=stdin,
                                    text=True, encoding='utf-8', capture_output=True, timeout=900)
            code, output = result.returncode, result.stdout + result.stderr
    print(output.strip())
    return 1 if code is None else code


if __name__ == '__main__':
    raise SystemExit(main())
