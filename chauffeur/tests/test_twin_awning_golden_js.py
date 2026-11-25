"""Walled drawn buffers remain byte-identical to main at 0ec59a62.

Homes without awnings also keep their full buffers and building atlas keys.
Migrated awnings are reported separately; their full batch identities may change.
The optional private export is flattened in memory and piped to Node on stdin.
Only its path, never its contents, enters the temporary job files.
"""
import argparse
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

from test_twin_tree_once_js import PREFIX
from test_twin_untouched_house_js import COMMON
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '0ec59a62'
PRE_MIGRATION = 'a57eb1b3'


def legacy_flatten(model):
    """Run the pre-migration bridge from git, keeping private input in memory."""
    source = subprocess.check_output(['git', 'show', PRE_MIGRATION + ':chauffeur/services/twin_model_bridge.py'],
                                     cwd=ROOT, encoding='utf-8')
    namespace = {'__name__': 'services._awning_legacy_bridge', '__package__': 'services',
                 '__file__': str(ROOT / 'services' / 'twin_model_bridge.py')}
    exec(compile(source, namespace['__file__'], 'exec'), namespace)
    return namespace['flatten'](deepcopy(model))


def baseline_sources(revision=BASELINE):
    sources = {}

    def read(path):
        if path in sources:
            return
        source = subprocess.check_output(
            ['git', 'show', f'{revision}:chauffeur/{path}'], cwd=ROOT, encoding='utf-8')
        sources[path] = source
        for ref in re.findall(r"(?:from|import)\s*['\"](\.[^'\"]+)['\"]", source):
            child = posixpath.normpath(posixpath.join(posixpath.dirname(path), ref))
            if child.startswith('static/twin/'):
                read(child)

    for path in ('static/twin/twin_generator.js', 'static/twin/bake/atlas.js'):
        read(path)
    return sources


# The same two-storey, two-building household as the untouched-house guard.
FIXTURE = COMMON[COMMON.index('const square='):COMMON.index('const hash=')]
FIXTURE_SETUP = r"""
const plans=[['household',fixture()]],household=fixture();
household.buildings[0].roof.sections[0].id='roof-main';
household.buildings[0].roof.extensions=[{id:'awning',kind:'awning',section:'roof-main',wall:'L1w0',
 x0:3,x1:15,depth:3,pitch:3,eave:7,brackets:2,gutter:true}];
plans.push(['household_awning',household]);
// I4: exercise both lost and gained P0 beam reproductions. The old rule is
// attached to roof-main itself, independent of which physical wall is used.
for(const [label,wall,off,parent] of [
 ['gable_side_awning','L1w1',0,'roof-main'],
 ['gable_offset_front','L1w0',.4,'roof-main'],
 ['gable_offset_side','L1w1',.4,'roof-main'],
 ['gable_other_parent','L1w0',0,'hip']]){
 const plan=fixture(),b=plan.buildings[0];b.roof.sections[0].id='roof-main';
 // Both gables must be unowned: otherwise the wall-owned fill path skips
 // the old P0 beam entirely and a trim comparison would be vacuous.
 b.walls=b.walls.filter(w=>w.level!=='L2'||Math.abs(w.to[1]-w.from[1])>1e-5);
 b.roof.sections[0].rect[1]-=off;
 b.roof.extensions=[{id:'awning',kind:'awning',section:parent,wall,x0:3,x1:15,
  depth:3,pitch:3,eave:7,brackets:2,gutter:false}];
 plans.push([label,plan]);
}
"""

DRIVER = PREFIX + r"""
const THREE=await import('three');
const {createHash}=await import('node:crypto');
const urls=new Map(), paths=Object.keys(input.sources);
// Legacy extensions share their parent's piece id and are merged by material.
// Test-only interception removes ONLY meshes emitted by the awning block just
// before batching. Keep the extension record (it also controls legacy gable
// trim and gutters). Full unfiltered drawn output is compared separately.
function instrument(source){
 const start=source.indexOf("} else if (extension.kind === 'awning') {"),
       end=source.indexOf('\n    if (buildingHasGutters',start),
       batch='  for (const g of mergeGroups) batch(';
 assert.ok(source.includes(batch),'awning/batch interception anchor');
 if(start>=0){assert.ok(end>start,'legacy awning block end');
 const block=source.slice(start,end).replace(/\bmesh\(/g,'goldenAwningMesh(');
 source=source.slice(0,start)+block.replace("} else if (extension.kind === 'awning') {",
  `} else if (extension.kind === 'awning') {
   const goldenAwningMesh=(...args)=>{const object=mesh(...args);
    globalThis.__goldenAwnings?.push(object);return object;};`)+source.slice(end);
 }
 const assign='Object.assign(object.userData, data);';
 assert.ok(source.includes(assign),'supported mesh observation point');
 source=source.replace(assign,assign+`\n      if(activeSurface?.support?.kind && activeSurface.support.kind!=='walls')
       globalThis.__goldenAwnings?.push(object);`);
 // Awning gutters/downspouts already share a material bucket with the roof.
 // Split that bucket only in the isolated build, using the segment's porch id.
 const gutterStart='function buildGutterGeometry(b, base, runs, spouts, resolveFinish) {';
 const gutterPart='parts.push({ geometry, mat: bucket.mat, ref: bucket.ref, seed: bucket.seed });';
 const gutterLoop='for (const { geometry: gutterGeo, mat: matGutter, ref: refGutter, seed } of gutterParts) {';
 for(const anchor of [gutterStart,gutterPart,gutterLoop])assert.ok(source.includes(anchor),'awning gutter interception anchor');
 source=source.replace(gutterStart,gutterStart+`
  const originalFinish=resolveFinish;resolveFinish=seg=>{const info=originalFinish(seg);
   const awning=globalThis.__goldenAwnings&&(b.roof?.extensions?.some(e=>e.kind==='awning'&&e.id===seg?.porch)
    ||b.roof?.sections?.some(s=>s.support?.kind&&s.support.kind!=='walls'&&(s.roof||s.id)===seg?.roof));
   return awning?{...info,key:info.key+':golden-awning',goldenAwning:true}:info;};`)
  .replace('seed: info.seed, positions: [], uvs: []','seed: info.seed, goldenAwning: info.goldenAwning, positions: [], uvs: []')
  .replace(gutterPart,'parts.push({ geometry, mat: bucket.mat, ref: bucket.ref, seed: bucket.seed, goldenAwning: bucket.goldenAwning });')
  .replace(gutterLoop,gutterLoop.replace('seed }','seed, goldenAwning }'))
  .replace("gMesh.userData.surfaceKind = 'gutter';","if(goldenAwning)globalThis.__goldenAwnings.push(gMesh);\n        gMesh.userData.surfaceKind = 'gutter';");
 return source.replace(batch,`  if(globalThis.__goldenAwnings)for(const m of new Set(globalThis.__goldenAwnings)){
   m.updateWorldMatrix(true,false);m.removeFromParent();}
`+batch);
}
for(const [path,original] of Object.entries(input.sources)){
 let source=path.endsWith('/twin_generator.js')?instrument(original):original;
 source=source.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
  const url=new URL(s,file(path)).href,ref=paths.find(p=>file(p)===url);
  return a+(ref?'baseline:'+ref:url)+b;
 });
 urls.set(path,'data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
}
registerHooks({resolve(spec,ctx,next){return spec.startsWith('baseline:')
 ?{url:urls.get(spec.slice(9)),shortCircuit:true}:next(spec,ctx);},
 load(url,ctx,next){const result=next(url,ctx);
  if(url!==file('static/twin/twin_generator.js'))return result;
  let source=String(result.source);
  if(input.legacySpatialTrim){const anchor='if (section.gable_beam === true)';assert.ok(source.includes(anchor));
   source=source.replace(anchor,`if(section.id==='roof-main' && !alongX && allSections.some(s=>isSupported(s)
    && Math.abs(s.rect[3]-y0)<1e-5 && s.rect[0]<x1 && s.rect[2]>x0))`);}
  return {...result,source:instrument(source)};}});
// This import deliberately fails on main before any comparison can pass.
const {SUPPORT_KINDS,isSupported}=await import(file('static/twin/roof_supports.js'));
const {roofMesh,roofEnvelope}=await import(file('static/twin/twin_roof.js'));
const G=await import(file('static/twin/twin_generator.js'));
const A=await import(file('static/twin/bake/atlas.js'));
const oldG=await import(urls.get('static/twin/twin_generator.js'));
const oldA=await import(urls.get('static/twin/bake/atlas.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const {releaseBakeSource}=await import(file('static/twin/bake/source.js'));
const sha=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const bytes=a=>a?createHash('sha256').update(new Uint8Array(a.buffer,a.byteOffset,a.byteLength)).digest('hex'):null;
const attr=a=>a?[a.array.constructor.name,a.itemSize,a.normalized,bytes(a.array)]:null;
const material=m=>[m.name,m.userData.materialKey??null,m.transparent,m.alphaTest,m.opacity,m.side,m.depthWrite,m.depthTest];
const row=m=>[m.name,m.layers.mask,Array.isArray(m.material)?m.material.map(material):material(m.material),
 m.matrixWorld.elements,['position','uv','normal'].map(k=>[k,attr(m.geometry.attributes[k])]),attr(m.geometry.index),
 m.geometry.groups,m.geometry.drawRange,m.isInstancedMesh?m.count:null];
const meshes=root=>{const list=[];root.traverseVisible(m=>{
 if(m.isMesh&&!m.layers.isEnabled(31)&& (Array.isArray(m.material)?m.material.some(x=>x.visible):m.material.visible))list.push(m);
});return list;};
function stats(list){return {hash:sha(list.map(row)),meshes:list.length,
 draws:list.reduce((n,m)=>n+(Array.isArray(m.material)?m.geometry.groups.filter(g=>m.material[g.materialIndex]?.visible).length:1),0),
 triangles:list.reduce((n,m)=>n+(m.geometry.index?.count??m.geometry.attributes.position.count)/3*(m.isInstancedMesh?m.count:1),0)};}
const layout={room:{density:1,page:2048,gutter:2}};
function atlasEvidence(atlas){const charts=atlas.room.charts.map(c=>[c.id,c.key,c.room,c.page,c.rect,c.density,c.outdoor,
 c.field??null,c.faces,c.mesh.name,material(c.mesh.material),c.mesh.matrixWorld.elements,
 (c.proxies||[]).map(p=>[p.mesh.name,p.faces])]);
 return {key:atlas.key,charts:charts.length,order_hash:sha(charts),
  lightmap_hash:sha([...new Set(atlas.room.charts.map(c=>c.mesh))].map(m=>
   [attr(m.geometry.attributes.uv3),attr(m.geometry.attributes.lmLightPage)]))};}
async function build(plan,module,isolated=false){
 globalThis.__goldenAwnings=isolated?[]:undefined;
 const start=performance.now(),out=module.buildTwin(structuredClone(plan),kit(),'high',{viewing:true});
 await out.ready;const ms=performance.now()-start;out.root.updateMatrixWorld(true);
 const awnings=globalThis.__goldenAwnings||[];globalThis.__goldenAwnings=undefined;
 return {out,ms,awnings};
}
function dispose(out){releaseBakeSource(out.root);disposeObject(out.root);}
async function evidence(plan,module,atlasModule){
 const full=await build(plan,module),all=stats(meshes(full.out.root));
 // Atlas for each building, plus the full house. Run after hashing drawn data:
 // buildAtlas prepares/clips receiving buffers and must not mask a draw change.
 const atlases=[];
 for(const building of plan.buildings||[]){
  const p=structuredClone(plan);p.buildings=[structuredClone(building)];
  const s=await build(p,module);atlases.push(atlasEvidence(atlasModule.buildAtlas(s.out.root,p,layout)));dispose(s.out);
 }
 const atlas=atlasEvidence(atlasModule.buildAtlas(full.out.root,plan,layout));dispose(full.out);
 const split=await build(plan,module,true),walled=stats(meshes(split.out.root)),awning=stats(split.awnings);
 dispose(split.out);for(const m of split.awnings)m.geometry.dispose();
 return {walled_hash:walled.hash,walled,awning,full:all,atlas,building_atlases:atlases,
  sections_supported:(plan.buildings||[]).reduce((n,b)=>n+(b.roof?.sections||[]).filter(isSupported).length,0)};
}
""" + FIXTURE + r"""
await test('support_predicate_and_grouped_envelope_contract',()=>{
 assert.deepEqual(SUPPORT_KINDS,['walls','bracket','corbel','brace','cable','post']);
 for(const s of [{},{support:{}},{support:{kind:'walls'}},{support:{kind:''}}])assert.equal(isSupported(s),false);
 for(const kind of SUPPORT_KINDS.slice(1))assert.equal(isSupported({support:{kind}}),true);
 const sections=fixture().buildings[0].roof.sections;
 for(const options of [{},{retainLower:true,exclude:[[],[]],materialKey:f=>String(f.section)}]){
  const grouped=roofEnvelope(sections,options);
  assert.deepEqual(grouped.walled,roofMesh(sections,options));
  assert.deepEqual(grouped.supported,roofMesh([],options));
 }
 assert.deepEqual(roofEnvelope([]),{walled:roofMesh([]),supported:roofMesh([])});
 // Overlapping supported and walled roofs must never clip each other. Both
 // outputs retain roofMesh's LOCAL section indices and exact empty shape.
 const supported={...sections[0],id:'supported',support:{kind:'bracket'},plate:7};
 const mixed=[sections[0],supported,sections[1]],options={retainLower:true};
 assert.deepEqual(roofEnvelope(mixed,options),{
  walled:roofMesh([sections[0],sections[1]],options),supported:roofMesh([supported],options)});
});
const plans=input.fixtures.map(c=>[c.label,c.old,c.current]);
if(input.ownerExport){const c=JSON.parse(readFileSync(0,'utf-8'));plans.push(['owner',c.old,c.current]);}
for(const [label,plan,changed] of plans)await test(label+'_equals_0ec59a62',async()=>{
 if(input.withoutGableBeam)for(const b of changed.buildings||[])for(const s of b.roof?.sections||[])delete s.gable_beam;
 const baseline=await evidence(plan,oldG,oldA),current=await evidence(changed,G,A);
 console.log('GOLDEN '+JSON.stringify({fixture:label,baseline:input.baseline,old:baseline,current}));
 const oldAwnings=(plan.buildings||[]).flatMap(b=>(b.roof?.extensions||[]).filter(e=>e.kind==='awning'));
 assert.equal(current.sections_supported,oldAwnings.length);
 assert.equal(current.walled_hash,baseline.walled_hash,'walled drawn hash');
 if(!oldAwnings.length)assert.deepEqual(current.full,baseline.full,'all drawn meshes, materials, buffers and counts');
 assert.deepEqual(current.walled,baseline.walled,'walled counts');
 if(!oldAwnings.length)assert.deepEqual(current.awning,baseline.awning,'legacy awning geometry separately');
 if(label!=='household')assert.ok(current.awning.triangles>0,'fixture must exercise legacy awning geometry');
 if(!oldAwnings.length){
  assert.deepEqual(current.atlas,baseline.atlas,'house atlas and lightmap keys/order');
  assert.deepEqual(current.building_atlases,baseline.building_atlases,'per-building atlas and lightmap keys/order');
 }
 if(input.measure&&label==='owner'){
  const times={baseline:[],current:[]};
  // One warm-up per module, then five samples each, alternating order.
  for(const module of [oldG,G]){const s=await build(module===G?changed:plan,module);dispose(s.out);}
  for(let i=0;i<5;i++)for(const [name,module] of i%2?[['current',G],['baseline',oldG]]:[['baseline',oldG],['current',G]]){
   const s=await build(module===G?changed:plan,module);times[name].push(s.ms);dispose(s.out);
  }
  const med=a=>[...a].sort((a,b)=>a-b)[2];
  console.log('BUILD_MS '+JSON.stringify({samples:times,median:{baseline:med(times.baseline),current:med(times.current)}}));
 }
});
finish();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-export', type=Path)
    parser.add_argument('--owner-only', action='store_true', help='Run only optional native owner evidence')
    parser.add_argument('--legacy-spatial-trim', action='store_true', help='Test-only negative proof: restore the reviewed spatial trim dependency in memory')
    parser.add_argument('--without-gable-beam', action='store_true', help='Test-only negative proof: remove the migrated parent trim field in memory')
    parser.add_argument('--measure', action='store_true', help='Node build medians of five, owner export required')
    args = parser.parse_args()
    if args.measure and not args.owner_export:
        parser.error('--measure requires --owner-export')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node is required for the golden test')
    sys.path.insert(0, str(ROOT))
    from services.twin_awning_migration import migrate_awnings
    code, output = run_node(PREFIX + FIXTURE + FIXTURE_SETUP + '\nconsole.log("FIXTURE_PLANS "+JSON.stringify(plans));',
                            {'root': ROOT.as_posix()}, timeout=60)
    if code != 0:
        raise RuntimeError(output)
    synthetic = json.loads(next(line[14:] for line in output.splitlines() if line.startswith('FIXTURE_PLANS ')))
    fixtures = [{'label': label, 'old': old, 'current': migrate_awnings(old)[0]} for label, old in synthetic]
    payload = {'root': ROOT.as_posix(), 'baseline': BASELINE, 'sources': baseline_sources(), 'fixtures': [] if args.owner_only else fixtures,
               'ownerExport': str(args.owner_export) if args.owner_export else None, 'measure': args.measure, 'withoutGableBeam': args.without_gable_beam, 'legacySpatialTrim': args.legacy_spatial_trim}
    stdin = None
    if args.owner_export:
        from services.twin_model_bridge import flatten as flatten_model
        model = json.loads(args.owner_export.read_text(encoding='utf-8'))['model']
        old = legacy_flatten(model)
        current = flatten_model(migrate_awnings(model)[0])
        stdin = json.dumps({'old': old, 'current': current})
    with tempfile.TemporaryDirectory(prefix='twin_awning_golden_') as directory:
        driver, job = Path(directory) / 'driver.mjs', Path(directory) / 'job.json'
        driver.write_text(DRIVER, encoding='utf-8')
        job.write_text(json.dumps(payload), encoding='utf-8')
        result = subprocess.run([node, str(driver), str(job)], input=stdin,
                                text=True, encoding='utf-8', timeout=900)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
