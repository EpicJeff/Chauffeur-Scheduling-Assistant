"""Runtime proof for model parts, levels and real household placement paths.

The checked-in untouched golden was captured before the Task 4 implementation.
GPU draw/program counts require the browser gate; CPU mesh counts are not GPU counts.
"""
import json
from pathlib import Path
import sys
import tempfile

from twin_live_node_rig import run

DRIVER = r'''
globalThis.ProgressEvent=class {constructor(type,values){Object.assign(this,values);}};
globalThis.FileReader=class {
 readAsArrayBuffer(blob){blob.arrayBuffer().then(value=>{this.result=value;this.onloadend?.();});}
 readAsDataURL(blob){blob.arrayBuffer().then(value=>{this.result='data:'+blob.type+';base64,'+Buffer.from(value).toString('base64');this.onloadend?.();});}
};
globalThis.requestIdleCallback=fn=>setTimeout(fn,0);globalThis.cancelIdleCallback=clearTimeout;
const {GLTFExporter}=await import(file('static/vendor/three-r187/addons/exporters/GLTFExporter.js'));
const {GLTFLoader}=await import(file('static/vendor/three-r187/addons/loaders/GLTFLoader.js'));
const lib=await import(file('static/twin/twin_library.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {applyObject,fitOpening}=await import(file('static/twin/objects.js'));
const {placeCarModel}=await import(file('static/twin/live/cars.js'));
const source=new THREE.Group();
for(const [i,name] of ['Wood','','Wood','Glass'].entries()){
 const g=new THREE.SphereGeometry(.2,12,12);if(i===1)g.deleteAttribute('uv');
 const m=new THREE.MeshStandardMaterial({name,transparent:name==='Glass',opacity:name==='Glass'?.4:1});
 const mesh=new THREE.Mesh(g,m);mesh.position.set(i*.5,.2,0);source.add(mesh);
}
const bytes=await new GLTFExporter().parseAsync(source,{binary:true});
const nativeFetch=globalThis.fetch,requests=[],records=new Map();
globalThis.fetch=async(input,opts={})=>{
 const url=typeof input==='string'?input:input.url;
 if(/^(data:|blob:)/.test(url))return nativeFetch(input,opts);
 requests.push(url);
 const match=url.match(/\/models\/([^/?]+)$/);
 if(match){const r=records.get(match[1]);return new Response(JSON.stringify(r||{}),{status:r?200:404});}
 return new Response(bytes);
};
const id='import-'+'d4'.repeat(16);
const entry={id,model:'original.glb',kind:'furniture',files:{'original.glb':true},lods:[]};
records.set(id,entry);lib.rememberImport(entry);
const meshes=root=>{const out=[];root.traverse(o=>{if(o.isMesh)out.push(o);});return out;};
const summary=root=>{
 root.updateMatrixWorld(true);const ms=meshes(root),box=new THREE.Box3().setFromObject(root);
 return {meshes:ms.length,materials:ms.map(o=>[].concat(o.material).map(m=>m.name)),
 triangles:ms.reduce((n,o)=>n+(o.geometry.index?.count||o.geometry.attributes.position.count)/3,0),
 bounds:[...box.min.toArray(),...box.max.toArray()].map(v=>Math.round(v*1e6)/1e6)};
};
const plan=structuredClone(config.flat),house=plan.buildings.find(b=>b.rooms.some(r=>r.state!=='ghost'));
const room=house.rooms.find(r=>r.state!=='ghost');house.items=[];
for(let i=0;i<2;i++)house.items.push({id:'parts-copy-'+i,asset:id,object_kind:'furniture',state:'settled',host:{floor:room.id,u:.3+i*.3,v:.5}});
const kit=structuredClone(config.kit);kit.manifest={};
const untouched=await lib.loadModel(id,kit,undefined,{editor:true});assert.ok(untouched);
const built=buildTwin(plan,kit,'high',{viewing:true});await built.ready;
const snapshot={loaded:summary(untouched),household:summary(built.root)};
if(config.capture){writeFileSync(config.golden,JSON.stringify(snapshot,null,2)+'\n');console.log('captured untouched main golden',JSON.stringify(snapshot));process.exit(0);}
assert.deepEqual(snapshot,JSON.parse(readFileSync(config.golden)),'untouched_render_identical');
console.log('ok untouched_render_identical: loadModel and two copies in the household equal pre-change main');

const levels=await import(file('static/twin/model_levels.js'));
const parts=levels.stampParts(source);assert.deepEqual(parts.map(p=>p.key),['Wood','unnamed','Wood~2','Glass']);
assert.equal(parts[1].has_uv,false);assert.equal(parts[3].opaque,false);
const uploads=[],patches=[];let revision=7;
const legacy={...entry,lods:[{name:'lod1.glb',percent:25},{name:'lod2.glb',percent:5}]};
const result=await levels.buildLevels(legacy,source,{
 patch:async changes=>{patches.push(changes);return {...legacy,...changes,revision:++revision};},
 upload:async(files,progress,signal,derived)=>{
  assert.equal(patches.length,1,'stamp before upload');assert.ok(derived.percent);
  const parsed=await new GLTFLoader().parseAsync(await files[0].arrayBuffer(),'');
  const keys=new Set(meshes(parsed.scene).flatMap(o=>[].concat(o.material).map(m=>m.userData.partKey)));
  assert.deepEqual([...keys].sort(),parts.map(p=>p.key).sort(),'keys_survive_export_roundtrip');
  uploads.push(derived);return {...legacy,...patches[0],revision:++revision};
 }
});
assert.deepEqual(uploads.map(u=>[u.lod,u.percent]),[['lod1.glb',25],['lod2.glb',5]],'regenerate each legacy level exactly once');
assert.equal(result.revision,10,'newest upload record returned');
const completed={...legacy,parts_version:1,lods:legacy.lods.map(l=>({...l,revision:1}))};
let skipped=0;await levels.buildLevels(completed,source,{patch:()=>assert.fail(),upload:()=>skipped++});assert.equal(skipped,0);
const fullUploads=[];await levels.buildLevels({...completed,lod_percent:[60,25,5]},source,{
 upload:async(files,p,s,d)=>{fullUploads.push(d);return {...legacy,parts_version:1};}
});assert.deepEqual(fullUploads.map(u=>[u.lod,u.percent]),[['lod0.glb',60]]);
const abort=new AbortController();abort.abort();await assert.rejects(levels.buildLevels(legacy,source,{signal:abort.signal,patch:()=>assert.fail(),upload:()=>assert.fail()}));
await assert.rejects(levels.buildLevels(legacy,source,{patch:async()=>{throw Object.assign(new Error('conflict'),{status:409,record:legacy});},upload:()=>assert.fail()}),e=>e.status===409);
console.log('ok keys_survive_export_roundtrip, legacy regeneration, missing full, cancellation and conflict propagation');

const materialKit={manifest:{oak:{kind:'material',household:true,params:{tile_ft:[2,3]}},walnut:{kind:'material',household:true,params:{tile_ft:[4,5]}}},materials:{floor:{id:'oak'}}};
const cache=new Map(),role=r=>{if(!cache.has(r))cache.set(r,lib.kitMaterial(r,materialKit,'high'));return cache.get(r);};
materialKit.modelMaterial=id=>lib.materialSlot({id},'floor',materialKit,'high',cache,role);
const record={...entry,parts,parts_version:1,materials:{Wood:{material:'oak'}}};
const original=await lib.loadModel(id,kit,undefined,{editor:true});
const copies=[0,1,2].map(()=>original.clone(true));
for(const c of copies)lib.applyPartMaterials(c,record,{},materialKit);
const wood=c=>meshes(c).find(m=>m.userData.partKey==='Wood');
assert.equal(wood(copies[0]).material,role('floor'));assert.equal(wood(copies[1]).material,role('floor'),'model_default_on_every_copy');
lib.applyPartMaterials(copies[0],record,{Wood:{material:'walnut',texture:'model',tiles:2}},materialKit);
lib.applyPartMaterials(copies[1],record,{Wood:{material:'original'}},materialKit);
assert.equal(wood(copies[0]).material,materialKit.modelMaterial('walnut'));
assert.equal(wood(copies[1]).material.name,'Wood');assert.equal(wood(copies[2]).material,role('floor'));
const uv=wood(copies[0]).geometry.attributes.uv.array,uvOriginal=wood(copies[0]).userData.uvOriginal;
for(let i=0;i<uv.length;i++)assert.ok(Math.abs(uv[i]-uvOriginal[i]*2*[4,5][i%2])<1e-5,'uv_modes model');
const {boxUvFeet}=await import(file('static/twin/model_parts.js'));
lib.applyPartMaterials(copies[0],record,{unnamed:{material:'oak',texture:'model'}},materialKit);
const noUv=meshes(copies[0]).find(m=>m.userData.partKey==='unnamed');
assert.deepEqual(noUv.geometry.attributes.uv.array,boxUvFeet(noUv.geometry.attributes.position.array,noUv.geometry.attributes.normal.array,1));
assert.equal(wood(copies[1]).geometry.attributes.uv.array.length,wood(original).geometry.attributes.uv.array.length);
let warns=0;const warn=console.warn;console.warn=()=>warns++;
for(let i=0;i<2;i++)lib.applyPartMaterials(copies[0],record,{Wood:{material:'missing'}},materialKit);
console.warn=warn;assert.equal(warns,1);assert.equal(wood(copies[0]).material.name,'Wood','stale_override_falls_back');
console.log('ok model_default_on_every_copy, copy_override_and_original, uv_modes, shared material identity and stale_override_falls_back');

const fullId='import-'+'f4'.repeat(16),fullRecord={...record,id:fullId,revision:12,lod_percent:[60,25,5],fix:{height_m:.9,turn:90},lods:[{name:'lod0.glb',percent:60,revision:3}],files:{'original.glb':true,'lod0.glb':true}};
records.set(fullId,fullRecord);lib.rememberImport(fullRecord);requests.length=0;
for(const editor of [true,false]){
 const model=await lib.loadModel(fullId,materialKit,undefined,{editor});assert.ok(model);
 assert.ok(Math.abs(new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3()).y-.9)<1e-3,'fix_applies_everywhere');
 const item=model.clone(true);applyObject(item,{id:'fixed'});assert.ok(Math.abs(new THREE.Box3().setFromObject(item).getSize(new THREE.Vector3()).y*.3048-.9)<1e-3);
 const parked=placeCarModel(model.clone(true),{at:[0,0,0],rotation:37,width:9,depth:18});
 assert.ok(Math.abs(new THREE.Box3().setFromObject(parked).getSize(new THREE.Vector3()).y-.9)<1e-3);
 assert.equal(parked.rotation.y,37*Math.PI/180+Math.PI/2,'car fix replaces only automatic turn, preserving parking yaw');
 const parkedSize=new THREE.Box3().setFromObject(parked).getSize(new THREE.Vector3()),loadedSize=new THREE.Box3().setFromObject(model.clone(true).rotateY(37*Math.PI/180)).getSize(new THREE.Vector3());
 assert.ok(parkedSize.distanceTo(loadedSize)<1e-5,'car keeps the loaded fixed orientation exactly once');
 const opening=fitOpening(model.clone(true),3,7,.5);assert.ok(Math.abs(new THREE.Box3().setFromObject(opening).getSize(new THREE.Vector3()).y-7)<1e-5);
}
assert.ok(requests.some(u=>/lod0\.glb\?v=3$/.test(u)));assert.ok(!requests.some(u=>u.includes('original.glb')),'full_level_used');
assert.equal((await lib.modelRecord(fullId)).revision,12);
const modelRanges=[];for(const objects of built.pieces.values())for(const o of objects)for(const range of o.userData.snapRanges||[])if(range.pieceId?.startsWith('parts-copy-'))modelRanges.push(range);
assert.ok(modelRanges.length>=8);assert.ok(modelRanges.every(r=>parts.some(p=>p.key===r.partKey)),'snapranges_carry_part');
console.log('ok full_level_used, version URLs, fix_applies_everywhere including car yaw/opening fit and snapranges_carry_part');

// Exercise the real builder's wall cache, rather than an injected material
// function alone. Two model copies share the very same existing wall instance.
const defaultPlan=structuredClone(plan),defaultKit={...kit,manifest:materialKit.manifest};
for(const b of defaultPlan.buildings)b.materials={...b.materials,siding:{id:'oak'}};
let latest=await lib.modelRecord(id);lib.rememberImport({...latest,revision:latest.revision+1,materials:{}});
const beforeDefault=buildTwin(defaultPlan,defaultKit,'high',{viewing:true});await beforeDefault.ready;
latest=await lib.modelRecord(id);lib.rememberImport({...latest,revision:latest.revision+1,materials:{Wood:{material:'oak'}}});
const afterDefault=buildTwin(defaultPlan,defaultKit,'high',{viewing:true});await afterDefault.ready;
const wallMaterial=meshes(afterDefault.root).find(o=>!o.geometry.userData.bakeExcluded&&o.material?.userData.materialId==='oak')?.material;
assert.ok(wallMaterial,'fixture has an oak wall');
for(let i=0;i<2;i++){
 const ms=afterDefault.pieces.get(`${house.id}:parts-copy-${i}`);
 assert.ok(ms.some(o=>o.material===wallMaterial&&o.userData.snapRanges?.some(r=>r.partKey==='Wood')),'default uses the actual wall instance');
}
const structuralCost=root=>({meshes:meshes(root).length,materials:new Set(meshes(root).flatMap(m=>[].concat(m.material))).size,triangles:summary(root).triangles});
console.log('CPU fixture structural cost (not GPU draws/programs): '+JSON.stringify({before:structuralCost(beforeDefault.root),after:structuralCost(afterDefault.root)}));
assert.equal(structuralCost(beforeDefault.root).triangles,structuralCost(afterDefault.root).triangles);

// The built-in record path has no import-catalog snapshot to seed its cache.
const apiId='pipeline_builtin',apiRecord={id:apiId,revision:1,parts:[],fix:{turn:90}};let reads=0;
globalThis.fetch=async()=>{reads++;return new Response(JSON.stringify(apiRecord));};
const [ra,rb]=await Promise.all([lib.modelRecord(apiId),lib.modelRecord(apiId)]);assert.equal(ra,rb);assert.equal(reads,1);
apiRecord.revision=2;assert.equal((await lib.modelRecord(apiId,{refresh:true})).revision,2);assert.equal(reads,2);

// Run the actual parts PATCH, binary chunk PUT and finish chain. Each attach
// changes the record revision, and a later PATCH must use the returned record.
const protocolId='import-'+'a4'.repeat(16);let protocolRecord={...entry,id:protocolId,revision:0},uploadBody,uploaded;
const protocol=[];
globalThis.fetch=async(input,opts={})=>{
 const url=typeof input==='string'?input:input.url;const reply=d=>new Response(JSON.stringify(d));
 if(url.endsWith('/models/'+protocolId)){
  const body=JSON.parse(opts.body);assert.equal(body.revision,protocolRecord.revision);assert.equal(body.parts_version,1);assert.equal(body.parts.length,4);
  protocol.push('stamp');protocolRecord={...protocolRecord,...body,revision:protocolRecord.revision+1};return reply(protocolRecord);
 }
 if(url.endsWith('/imports/uploads')){uploadBody=JSON.parse(opts.body);protocol.push(uploadBody.lod);assert.ok(uploadBody.percent);return reply({upload_id:'parts',chunk_bytes:4194304});}
 if(url.endsWith('/parts/0')){uploaded=await opts.body.arrayBuffer();assert.equal(uploaded.byteLength,uploadBody.size);return reply({});}
 if(url.endsWith('/parts/finish')){
  const decoded=await new GLTFLoader().parseAsync(uploaded,'');assert.equal(new Set(meshes(decoded.scene).map(m=>m.material.userData.partKey)).size,4);
  protocolRecord={...protocolRecord,revision:protocolRecord.revision+1,lods:[...protocolRecord.lods,{name:uploadBody.lod,percent:uploadBody.percent,revision:1}]};return reply(protocolRecord);
 }
 throw new Error('Unexpected protocol request '+url);
};
const attached=await levels.buildLevels(protocolRecord,source);
assert.deepEqual(protocol,['stamp','lod1.glb','lod2.glb']);assert.equal(attached.revision,3);
assert.equal((await lib.modelRecord(protocolId)).revision,3);
console.log('ok real household wall identity, record revision cache/refresh and actual stamp/export/chunk-upload/finish protocol');

const {generateLevel}=await import(file('static/twin/model_lods.js'));
const fullSource=new THREE.Mesh(new THREE.SphereGeometry(1,64,64),new THREE.MeshStandardMaterial());fullSource.material.userData.partKey='full';
const simplifiedFull=await generateLevel(fullSource,60);
assert.ok(simplifiedFull.geometry.index.count<fullSource.geometry.index.count*.66,'full below 100 uses the simplifier');
assert.equal(simplifiedFull.material.userData.partKey,'full');

// Source loading always gets the authored original, even after a full-level
// replacement/fix/default was saved. The export path must not bake them twice.
globalThis.fetch=async(input,opts={})=>{const url=typeof input==='string'?input:input.url;if(/^(data:|blob:)/.test(url))return nativeFetch(input,opts);requests.push(url);return new Response(bytes);};
requests.length=0;const raw=await lib.loadModel(fullId,materialKit,undefined,{editor:true,source:true});
assert.ok(requests.some(u=>u.endsWith('original.glb')));assert.ok(!requests.some(u=>u.includes('lod0.glb')));
assert.ok(Math.abs(new THREE.Box3().setFromObject(raw).getSize(new THREE.Vector3()).y-.4)<1e-5);
assert.equal(meshes(raw)[0].material.name,'Wood');

registerHooks({resolve(spec,ctx,next){if(spec==='@dgreenheck/ez-tree')return {url:'data:text/javascript,'+encodeURIComponent(`import {Group} from '${file('static/vendor/three-r187/three.module.js')}';export class Tree extends Group {}`),shortCircuit:true};return next(spec,ctx);}});
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const yardPlan={units:'ft',buildings:[],materials:{},site:{furniture:[{id:'yard-chair',asset:fullId,at:[0,0],model_materials:{Wood:{material:'walnut'}}}],planting:[{id:'yard-plant',asset:fullId,at:[3,0],model_materials:{Wood:{material:'original'}}}]}};
const yard=await buildYard(yardPlan,materialKit,'low',{viewing:true});
const ranges=meshes(yard.group).flatMap(m=>(m.userData.snapRanges||[]).map(r=>({m,r}))).filter(({r})=>['yard-chair','yard-plant'].includes(r.pieceId));
for(const pieceId of ['yard-chair','yard-plant'])assert.ok(ranges.filter(({r})=>r.pieceId===pieceId).length>=4);
assert.ok(ranges.every(({r})=>parts.some(p=>p.key===r.partKey)));
assert.ok(ranges.some(({m,r})=>r.pieceId==='yard-chair'&&r.partKey==='Wood'&&m.material.userData.materialId==='walnut'));
assert.ok(ranges.some(({m,r})=>r.pieceId==='yard-plant'&&r.partKey==='Wood'&&m.material.name==='Wood'));
console.log('ok actual full simplification, authored-source loading and yard furniture/planting overrides and snap ranges');
assert.deepEqual(escaped,[]);assert.deepEqual(domErrors,[]);
'''

if __name__ == '__main__':
    app = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(app))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((app / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text())
    kit = json.loads((app / 'twin_kits/modern_farmhouse.json').read_text())
    kit['manifest'] = {}
    tempfile.tempdir = str(app.parent / '.codex-tmp')
    result = run(DRIVER, {'flat': flatten(assemble(fixture)[0]), 'kit': kit,
        'golden': str(app / 'tests/fixtures/twin_model/model-pipeline-untouched.json'),
        'capture': '--capture-golden' in sys.argv}, prefix='.model_pipeline_', timeout=180)
    if result or '--capture-golden' in sys.argv:
        sys.exit(result)
    from model_pipeline_fix1_checks import run_checks
    result = run_checks()
    if result:
        sys.exit(result)
    from model_pipeline_fix2_checks import run_checks as run_fix2_checks
    result = run_fix2_checks()
    if result:
        sys.exit(result)
    from model_pipeline_fix3_checks import run_checks as run_fix3_checks
    sys.exit(run_fix3_checks())
