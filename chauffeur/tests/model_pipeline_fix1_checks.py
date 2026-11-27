"""Fix-round runtime regressions; invoked by test_model_parts_pipeline_js.py."""
import subprocess
from pathlib import Path
import twin_live_node_rig as rig
from twin_live_node_rig import run

DRIVER = r'''
// Expose cache state only in this test module instance. Production exports stay unchanged.
registerHooks({load(url,ctx,next){
 if(url.endsWith('/static/twin/twin_library.js')){
  const r=next(url,{...ctx,format:'module'});return {...r,format:'module',source:r.source.toString()+'\nexport const __cacheForTest=modelCache;'};
 }
 if(url.endsWith('/twin_yard.js?baseline'))return {format:'module',source:config.mainYard,shortCircuit:true};
 return next(url,ctx);
},resolve(spec,ctx,next){
 if(spec==='@dgreenheck/ez-tree')return {url:'data:text/javascript,'+encodeURIComponent(`import {Group} from '${file('static/vendor/three-r187/three.module.js')}';export class Tree extends Group {}`),shortCircuit:true};
 return next(spec,ctx);
}});
globalThis.ProgressEvent=class {constructor(type,values){Object.assign(this,values);}};
globalThis.FileReader=class {readAsArrayBuffer(b){b.arrayBuffer().then(v=>{this.result=v;this.onloadend?.();});}};
globalThis.requestIdleCallback=fn=>setTimeout(fn,0);globalThis.cancelIdleCallback=clearTimeout;
const lib=await import(file('static/twin/twin_library.js'));
const levels=await import(file('static/twin/model_levels.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {placeCarModel}=await import(file('static/twin/live/cars.js'));
const {GLTFExporter}=await import(file('static/vendor/three-r187/addons/exporters/GLTFExporter.js'));
const {GLTFLoader}=await import(file('static/vendor/three-r187/addons/loaders/GLTFLoader.js'));
const rawFetch=globalThis.fetch;
const meshes=root=>{const a=[];root.traverse(o=>{if(o.isMesh)a.push(o);});return a;};
const makeSource=(points=[-2,0,0, 4,0,0, 0,2,1])=>{
 const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(points,3));
 return new THREE.Mesh(g,new THREE.MeshStandardMaterial({name:'Wood'}));
};
const source=makeSource(),originalBytes=await new GLTFExporter().parseAsync(source,{binary:true});
let serial=0;const fresh=extra=>({id:'import-'+(++serial).toString(16).padStart(32,'0'),name:'test model',model:'original.glb',files:{'original.glb':true},lods:[],revision:0,...extra});
function serveFiles(files={},observe=()=>{}){globalThis.fetch=async(input,opts={})=>{
 const url=typeof input==='string'?input:input.url;if(/^(data:|blob:)/.test(url))return rawFetch(input,opts);
 observe(url,opts);return new Response(files[new URL(url,window.location.href).pathname.split('/').at(-1)]||originalBytes);
};}
const planFor=id=>({units:'ft',materials:{},site:{},buildings:[{id:'b',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:9}],walls:[],openings:[],roof:{sections:[]},rooms:[{id:'r',level:'L1',state:'settled',polygon:[[0,0],[10,0],[10,10],[0,10]]}],items:[{id:'chair',asset:id,object_kind:'furniture',host:{floor:'r',u:.5,v:.5},state:'settled'}]}]});
const failures=[];
async function check(name,fn){if(config.only&&config.only!==name)return;try{await fn();console.log('PASS '+name);}catch(e){failures.push(name);console.log('FAIL '+name+': '+e.stack);}}

// Use r187's actual parameter/key functions, without a GL context. Only the
// standard-material branch runs; the custom-shader cache is never consulted.
const bundle=readFileSync(new URL(file('static/vendor/three-r187/three.module.js')),'utf8');
const programSource=bundle.slice(bundle.indexOf('function WebGLPrograms('),bundle.indexOf('function WebGLProperties('));
const WebGLPrograms=Function('THREE',`const {${Object.keys(THREE).filter(k=>/^[A-Za-z_$][\w$]*$/.test(k)).join(',')}}=THREE;class WebGLShaderCache{};${programSource};return WebGLPrograms;`)(THREE);
const renderer={getRenderTarget:()=>null,state:{buffers:{depth:{getReversed:()=>false}}},shadowMap:{enabled:true,type:THREE.PCFShadowMap},toneMapping:THREE.NoToneMapping,outputColorSpace:THREE.SRGBColorSpace};
const programs=WebGLPrograms(renderer,{get:()=>null},{has:()=>false},{precision:'highp',logarithmicDepthBuffer:false,getMaxPrecision:x=>x},{},{numPlanes:0,numIntersection:0});
const lights={sun:[],directional:[],point:[],spot:[],spotLightMap:[],rectArea:[],hemi:[],sunShadowMap:[],directionalShadowMap:[],pointShadowMap:[],spotShadowMap:[],numSpotLightShadowsWithMaps:0,numLightProbes:0};
function keys(root){const scene=new THREE.Scene();return meshes(root).map(m=>programs.getProgramCacheKey(programs.getParameters(m.material,lights,[],scene,m,[]))).sort();}

await check('A_program_keys_survive_stamp_regeneration',async()=>{
 const r=fresh();lib.rememberImport(r);const files={};serveFiles(files);
 const before=buildTwin(planFor(r.id),{},'high');await before.ready;
 const authored=await lib.loadModel(r.id,{},undefined,{editor:true,source:true});let current=r;
 const attached=await levels.buildLevels(r,authored,{patch:async changes=>(current={...current,...changes,revision:1}),upload:async(fs,p,s,d)=>{
  files[d.lod]=await fs[0].arrayBuffer();current={...current,revision:current.revision+1,files:{...current.files,[d.lod]:true},lods:[...current.lods,{name:d.lod,percent:d.percent,revision:1}]};return current;
 }});lib.rememberImport(attached);
 const after=buildTwin(planFor(r.id),{},'high',{reuseMaterials:before.materials});await after.ready;
 assert.deepEqual(keys(after.root),keys(before.root),'every mesh retains the actual three.js program key');
 // A second unchanged build must retain its material owner too: disposing the
 // old owner must not drop the last warmed reference before the replacement.
 const beforeMaterial=before.pieces.get('b:chair')[0].material,afterMaterial=after.pieces.get('b:chair')[0].material;
 assert.equal(afterMaterial,beforeMaterial,'an editor-only stamp/derived upload must retain the warmed original material');
});
await check('B1_html_413_backs_off',async()=>{
 const sizes=[];globalThis.fetch=async(url,opts)=>{
  if(url.endsWith('/uploads'))return new Response(JSON.stringify({upload_id:'html413',chunk_bytes:2097152}));
  if(opts.method==='PUT'){sizes.push(opts.body.size);return opts.body.size>1048576?new Response('<html>too large</html>',{status:413}):new Response('{}');}
  return new Response(JSON.stringify({id:'done'}));
 };
 assert.equal((await levels.uploadFiles([new File([new Uint8Array(2*1048576)],'chair.glb')])).id,'done');
 assert.deepEqual(sizes,[2097152,1048576,1048576]);
});
await check('B2_car_height_and_turn_keep_spot_rotation',async()=>{
 for(const turn of [0,90]){
  const model=new THREE.Mesh(new THREE.BoxGeometry(4,1,1),new THREE.MeshStandardMaterial());
  model.userData.modelRecord={fix:{height_m:.9,turn}};model.rotation.y=turn*Math.PI/180;
  const car=placeCarModel(model,{at:[0,0,0],rotation:37,width:9,depth:18});car.updateMatrixWorld(true);
  assert.ok(Math.abs(car.rotation.y-127*Math.PI/180)<1e-8,'parking angle plus automatic/fixed quarter turn');
  const direction=new THREE.Vector3(0,0,1).transformDirection(model.matrixWorld);
  assert.ok(Math.abs(direction.x-Math.sin(127*Math.PI/180))<1e-6,'loaded fix applied exactly once');
 }
});
await check('B3_interrupted_stamp_resumes_keyless_levels',async()=>{
 const controller=new AbortController(),r=fresh({lods:[{name:'lod1.glb',percent:25},{name:'lod2.glb',percent:5}]});let stamped;
 await assert.rejects(levels.buildLevels(r,source,{signal:controller.signal,patch:async changes=>{stamped={...r,...changes,revision:1};controller.abort();return stamped;},upload:()=>assert.fail()}));
 const uploaded=[];await levels.buildLevels(stamped,source,{upload:async(fs,p,s,d)=>{uploaded.push(d.lod);return {...stamped,revision:2};}});
 assert.deepEqual(uploaded,['lod1.glb','lod2.glb']);
});
await check('B3_completed_queue_uses_normalised_record',async()=>{
 const r=fresh({parts_version:1,lods:[{name:'lod1.glb',revision:1},{name:'lod2.glb',revision:1}]});let sourceLoads=0;
 globalThis.fetch=async(input)=>{const url=typeof input==='string'?input:input.url;
  if(url.endsWith('/imports'))return new Response(JSON.stringify([r]));
  if(url.endsWith('/import-settings'))return new Response('{}');
  if(/original\.glb/.test(url)){sourceLoads++;return new Response(originalBytes);}
  throw new Error('completed model should issue no generation requests: '+url);
 };
 await lib.importedModels(true);
 const host=document.createElement('div');document.body.append(host);
 for(const id of ['library-import-files','library-status','library-jobs']){const n=document.createElement('input');n.id=id;host.append(n);}
 const life=new AbortController();const {mountImports}=await import(file('static/twin/editor/imports.js'));
 mountImports({canvas:document.createElement('canvas'),kit:{},canEdit:()=>true,signal:life.signal,changed:async()=>{}});
 await wait(150);life.abort();host.remove();assert.equal(sourceLoads,0,'fully generated models never load a source');
});
await check('B4_yard_lamp_ranges_and_fixture_filter_match_main',async()=>{
 const r=fresh();lib.rememberImport(r);serveFiles();
 const p={units:'ft',buildings:[],materials:{},site:{furniture:[{id:'lamp',asset:r.id,at:[0,0],object_kind:'lamp'}]}};
 const baseline=await import(file('static/twin/twin_yard.js')+'?baseline');
 const old=await baseline.buildYard(p,{},'low',{viewing:true}),now=await buildYard(p,{},'low',{viewing:true});
 const ranges=root=>meshes(root).flatMap(m=>m.userData.snapRanges||[]).filter(r=>r.pieceId==='lamp').map(({partKey,...r})=>JSON.parse(JSON.stringify(r)));
 assert.deepEqual(ranges(now.group),ranges(old.group),'main yard ranges including visibilityKind/bakePart/ghost');
 const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));const visibility=createPieceVisibility();
 const lamp=meshes(now.group).find(m=>m.userData.snapRanges?.some(r=>r.pieceId==='lamp'));
 const before=Array.from(lamp.geometry.attributes.position.array);visibility.set([],['fixture']);visibility.apply(now.group);
 assert.notDeepEqual(Array.from(lamp.geometry.attributes.position.array),before,'fixtures filter hides lamp triangles');visibility.restore();
});
await check('B5_retained_lod_weather_can_clip',async()=>{
 const r=fresh({parts_version:1,lods:[{name:'lod1.glb',percent:25,revision:1}],files:{'original.glb':true,'lod1.glb':true}});lib.rememberImport(r);serveFiles();
 const built=buildTwin(planFor(r.id),{},'high',{viewing:true});await built.ready;
 const sky=readFileSync(new URL(file('static/twin/sky/sky_cover.js')),'utf8');
 const canClip=Function('clipSkipKinds',sky.slice(sky.indexOf('function canClip('),sky.indexOf('function changedEdges('))+';return canClip;')(new Set(['roof','wall','room','floor','ceiling','trim','opening','fixture','furniture','planting']));
 const retained=built.pieces.get('b:chair');assert.ok(retained.some(m=>m.userData.modelLod));
 assert.ok(retained.every(m=>canClip(m.geometry,m)),'untouched LOD mesh remains eligible for weather clipping');
});
await check('B6_heavy_without_size_uses_measured_standin',async()=>{
 const r=fresh({triangles:300001});lib.rememberImport(r);serveFiles();
 const model=await lib.loadModel(r.id,{},undefined,{tier:'low'});assert.equal(model.userData.heavyStandIn,true);
});
await check('B7_part_never_inherits_tinted_wall_instance',async()=>{
 const kit={manifest:{paint_white:{household:true,kind:'material',revision:1,params:{tint:'#ffffff'}}},materials:{siding:{id:'paint_white',color:'#334455'}}};
 const tinted=lib.kitMaterial('siding',kit,'high'),cache=new Map([['siding',tinted]]);
 const bound=lib.modelMaterialKit(kit,'high',cache,r=>cache.get(r));
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial());mesh.userData.partKey='Wood';
 lib.applyPartMaterials(mesh,{id:'paint-test',parts:[{key:'Wood',has_uv:true}],materials:{Wood:{material:'paint_white'}}},{},bound);
 assert.notEqual(mesh.material,tinted);assert.equal(mesh.material.color.getHexString(),'ffffff');
 assert.equal(mesh.material.userData.materialKey,lib.materialKey({id:'paint_white'},mesh.material.name,'high',kit.manifest));
 const builtinKit={materials:{}},builtinCache=new Map();
 const builtin=lib.materialSlot({id:'black_metal'},'siding',builtinKit,'high',builtinCache,()=>assert.fail());
 assert.equal(lib.modelMaterialKit(builtinKit,'high',builtinCache,()=>assert.fail()).modelMaterial('black_metal'),builtin,'built-in slots use their untinted materialSlot key too');
});
await check('B8_geometry_and_authored_uvs_are_shared_without_json',async()=>{
 const g=new THREE.BoxGeometry(),material=new THREE.MeshStandardMaterial(),root=new THREE.Mesh(g,material);root.userData.partKey='Wood';
 const a=root.clone(true),b=root.clone(true),kit={manifest:{oak:{household:true,kind:'material',params:{tile_ft:[2,3]}}},materials:{}};
 const record={id:'uv-budget',parts:[{key:'Wood',has_uv:true}],materials:{Wood:{material:'oak',texture:'model',tiles:2}}};
 lib.applyPartMaterials(a,record,{},kit);lib.applyPartMaterials(b,record,{},kit);
 assert.equal(a.geometry,b.geometry,'one geometry per UV choice');
 for(const attr of ['position','normal'])assert.equal(a.geometry.attributes[attr].array,g.attributes[attr].array);
 assert.equal(a.geometry.index.array,g.index.array);assert.notEqual(a.geometry.attributes.uv,g.attributes.uv);
 assert.ok(a.userData.uvOriginal);assert.equal(Object.prototype.propertyIsEnumerable.call(a.userData,'uvOriginal'),false);
 assert.ok(!JSON.stringify(a.userData).includes('uvOriginal'));assert.ok(!JSON.stringify(a.clone(true).userData).includes('uvOriginal'));
 const imported=fresh({parts_version:1,parts:[{key:'Wood',has_uv:false}],materials:{Wood:{material:'oak'}}});
 lib.rememberImport(imported);serveFiles();const loaded=await lib.loadModel(imported.id,kit,undefined,{editor:true});
 lib.applyPartMaterials(loaded,imported,{Wood:{material:'original'}},kit);
 assert.ok(meshes(loaded).every(m=>m.geometry.userData.bakeExcluded),'restoring UVs preserves the model render-only classification');
 const plainRecord=fresh({parts_version:1,parts:[{key:'Wood',has_uv:false}]});lib.rememberImport(plainRecord);serveFiles();
 const plain=await lib.loadModel(plainRecord.id,kit,undefined,{editor:true}),copy=plain.clone(true);
 lib.applyPartMaterials(copy,{...plainRecord,materials:{Wood:{material:'oak'}}},{},kit);
 for(const attr of ['position','normal'])assert.equal(meshes(copy)[0].geometry.attributes[attr].array,meshes(plain)[0].geometry.attributes[attr].array,'loaded source buffers stay shared too');
});
await check('B9_source_job_leaves_no_model_cache_entry',async()=>{
 const r=fresh();lib.rememberImport(r);serveFiles();const authored=await lib.loadModel(r.id,{},undefined,{source:true,editor:true});
 await levels.buildLevels(r,authored,{patch:async c=>({...r,...c,revision:1}),upload:async()=>({...r,parts_version:1,revision:2})});lib.disposeObject(authored);
 assert.ok(![...lib.__cacheForTest.keys()].some(k=>k.includes(r.id)),'uncached authored source is released by its job');
});
await check('B10_auth_urls_equal_main_with_one_token',async()=>{
 const auth=window.chfAuthUrl;window.chfAuthUrl=url=>url+(url.includes('?')?'&':'?')+'member_token=test';
 try{for(const revision of [0,2]){
  const r=fresh({parts_version:1,lod_percent:[60,25,5],lods:[{name:'lod0.glb',percent:60,revision}],files:{'original.glb':true,'lod0.glb':true}});lib.rememberImport(r);const urls=[];serveFiles({},u=>urls.push(u));
  assert.ok(await lib.loadModel(r.id,{},undefined,{editor:true}));
  const expected=new URL(lib.base()+'api/house/twin/imports/'+r.id+'/lod0.glb',window.location.href);if(revision)expected.searchParams.set('v',revision);
  expected.searchParams.set('member_token','test');assert.equal(urls[0],expected.href,'main resource URL plus positive revision only');
 }}finally{window.chfAuthUrl=auth;}
});
await check('B11_builtin_asset_key_stable_on_first_read',async()=>{
 const id='fix1_builtin',asset={kind:'model',model:'chair.glb',files:{'chair.glb':true}},kit={manifest:{[id]:asset}};
 const before=JSON.stringify(lib.modelAssetKey(id,kit));globalThis.fetch=async()=>new Response(JSON.stringify({...asset,id,builtin:true,revision:0,lod_percent:[100,25,5],lods:[],parts:[]}));
 await lib.modelRecord(id);assert.equal(JSON.stringify(lib.modelAssetKey(id,kit)),before);
 const implicitId='fix1_builtin_implicit',implicit={kind:'model',files:{'chair.glb':true}},implicitKit={manifest:{[implicitId]:implicit}};
 const implicitBefore=JSON.stringify(lib.modelAssetKey(implicitId,implicitKit));
 globalThis.fetch=async()=>new Response(JSON.stringify({...implicit,id:implicitId,model:'chair.glb',builtin:true,revision:0,lod_percent:[100,25,5],lods:[],parts:[]}));
 await lib.modelRecord(implicitId);assert.equal(JSON.stringify(lib.modelAssetKey(implicitId,implicitKit)),implicitBefore,'the manifest can leave model implicit, as real Poly Haven entries do');
});
await check('B11b_levels_share_full_offset',async()=>{
 const full=await new GLTFExporter().parseAsync(makeSource(),{binary:true});const mid=await new GLTFExporter().parseAsync(makeSource([-2,0,0,2,0,0,0,2,1]),{binary:true});
 const r=fresh({parts_version:1,lods:[{name:'lod1.glb',percent:25,revision:1}],files:{'original.glb':true,'lod1.glb':true}});lib.rememberImport(r);serveFiles({'original.glb':full,'lod1.glb':mid});
 const model=await lib.loadModel(r.id,{},undefined,{tier:'high'});model.updateMatrixWorld(true);assert.ok(model.isLOD);
 const fullBox=new THREE.Box3().setFromObject(model.levels[0].object),midBox=new THREE.Box3().setFromObject(model.levels[1].object);
 assert.ok(Math.abs(midBox.min.x-fullBox.min.x)<1e-6,'shared authored extreme stays at level 0 position');
 const preview=await lib.loadModel(r.id,{},undefined,{editor:true,lodName:'lod1.glb'});
 assert.ok(Math.abs(new THREE.Box3().setFromObject(preview).min.x-fullBox.min.x)<1e-6,'a standalone mid preview uses the same level 0 origin');
 const farRecord=fresh({...r,id:undefined,lods:[{name:'lod2.glb',percent:5,revision:1}],files:{'original.glb':true,'lod2.glb':true}});
 farRecord.id='import-'+(++serial).toString(16).padStart(32,'0');lib.rememberImport(farRecord);serveFiles({'original.glb':full,'lod2.glb':mid});
 const low=await lib.loadModel(farRecord.id,{},undefined,{tier:'low'});
 assert.ok(Math.abs(new THREE.Box3().setFromObject(low).min.x-fullBox.min.x)<1e-6,'low uses the same full-level origin');
 // Newly generated far files carry their anchor and must not fetch a heavy
 // original just to find that origin. Exercise actual export/reparse extras.
 const anchored=fresh();lib.rememberImport(anchored);const generated={};serveFiles({'original.glb':full});
 const authored=await lib.loadModel(anchored.id,{},undefined,{source:true,editor:true});let latest=anchored;
 await levels.buildLevels(anchored,authored,{patch:async c=>(latest={...latest,...c,revision:1}),upload:async(fs,p,s,d)=>{
  generated[d.lod]=await fs[0].arrayBuffer();latest={...latest,revision:latest.revision+1,files:{...latest.files,[d.lod]:true},lods:[...latest.lods,{name:d.lod,percent:d.percent,revision:1}]};return latest;
 }});lib.disposeObject(authored);
 const parsed=await new GLTFLoader().parseAsync(generated['lod2.glb'],'');
 meshes(parsed.scene)[0].geometry.attributes.position.setX(1,2);
 generated['lod2.glb']=await new GLTFExporter().parseAsync(parsed.scene,{binary:true});
 const urls=[];serveFiles(generated,u=>urls.push(u));
 const anchoredLow=await lib.loadModel(anchored.id,{},undefined,{tier:'low'});
 assert.ok(Math.abs(new THREE.Box3().setFromObject(anchoredLow).min.x-fullBox.min.x)<1e-6);
 assert.ok(urls.every(u=>!u.includes('original.glb')),'anchor extras avoid downloading the original on low');
});
await check('B12_negative_record_cache_retries_after_ttl',async()=>{
 let reads=0;const id='fix1_absent';globalThis.fetch=async()=>{reads++;return new Response('{}',{status:404});};
 await assert.rejects(lib.modelRecord(id));await assert.rejects(lib.modelRecord(id));assert.equal(reads,1);
 const oldNow=Date.now;Date.now=()=>oldNow()+31000;try{await assert.rejects(lib.modelRecord(id));}finally{Date.now=oldNow;}assert.equal(reads,2);
 lib.rememberImport({id,revision:1,parts:[]});assert.equal((await lib.modelRecord(id)).revision,1);
});
assert.deepEqual(escaped,[]);assert.deepEqual(domErrors,[]);
if(failures.length)throw new Error('Fix-round failures: '+failures.join(', '));
'''

def run_checks(only=None):
    app = Path(__file__).resolve().parents[1]
    main_yard = subprocess.run(['git', 'show', '02a6f0aeb16ada1b1c0866f2664a57d60c92b78c:chauffeur/static/twin/twin_yard.js'], cwd=app,
                               capture_output=True, text=True, encoding='utf-8', check=True).stdout
    rig.PRELUDE = rig.PRELUDE.replace("  return url.startsWith('file:')", "  if(url.endsWith('/static/twin/twin_library.js')) { const r=next(url,{...ctx,format:'module'});return {...r,format:'module',source:r.source.toString()+'\\nexport const __cacheForTest=modelCache;'};}\n  return url.startsWith('file:')")
    return run(DRIVER, {'mainYard': main_yard, 'only': only}, prefix='.pipeline_fix1_', timeout=180)

if __name__ == '__main__':
    import sys
    sys.exit(run_checks(sys.argv[1] if len(sys.argv) > 1 else None))
