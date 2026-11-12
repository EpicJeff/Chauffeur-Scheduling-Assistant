"""Real three.js/GLTFLoader geometry, the shared schema, handles and history."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_twin_drag_js import DRIVER as BASE

DRIVER = BASE.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE = await import(three);
const objects = await import(file('static/twin/objects.js'));
window.twinObjectSchema = JSON.parse(readFileSync(root + '/static/twin/object_schema.json'));
const { GLTFLoader } = await import(file('static/vendor/three-r187/addons/loaders/GLTFLoader.js'));
globalThis.ProgressEvent = class {constructor(type, values){this.type=type;Object.assign(this,values);}};
const vertices = new Float32Array([-1,0,-.1,1,0,-.1,0,2,.1]);
const documentGLTF = {asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],
  meshes:[{primitives:[{attributes:{POSITION:0}}]}], buffers:[{uri:'data:application/octet-stream;base64,'+Buffer.from(vertices.buffer).toString('base64'),byteLength:36}],
  bufferViews:[{buffer:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-1,0,-.1],max:[1,2,.1]}]};
const loaded = await new GLTFLoader().parseAsync(JSON.stringify(documentGLTF),'');
const normal = objects.normaliseModel(loaded.scene);
const box = new THREE.Box3().setFromObject(normal), size = box.getSize(new THREE.Vector3());
const near=(a,b)=>assert.ok(Math.abs(a-b)<.00001,`${a} near ${b}`);
near(box.min.y,0);near(box.min.x+box.max.x,0);near(box.min.z+box.max.z,0);near(size.y,2);
assert.equal(objects.modelBudget(normal,{resizeTextures:false}).triangles,1);
assert.equal(objects.suggestKind([.9,2.1,.1]),'door');
assert.equal(objects.suggestKind([1.4,1,.1]),'window');
assert.equal(objects.suggestKind([1,1,1]),'furniture');
const fitted = objects.fitOpening(normal,4,7,.25);
const fitBox = new THREE.Box3().setFromObject(fitted), dimensions = fitBox.getSize(new THREE.Vector3());
near(dimensions.x,4);near(dimensions.y,7);assert.ok(dimensions.z<=.250001);near(fitBox.min.y,0);
assert.deepEqual(Object.keys(objects.propertyFields({object_kind:'lamp'})).sort(),[...Object.keys(window.twinObjectSchema.common),...Object.keys(window.twinObjectSchema.kinds.lamp)].sort());
assert.deepEqual(objects.propertyValue({},'visible_in'),['viewer','editor']);
const shared = new THREE.MeshStandardMaterial({color:'#ffffff'}), chair = new THREE.Mesh(new THREE.BoxGeometry(1,1,1),shared);
objects.applyObject(chair,{scale:1.5,rotation:90,pitch:15,roll:10,tint:'#224466',casts_shadow:false},{units:1});
near(chair.scale.x,1.5);near(chair.rotation.y,Math.PI/2);assert.equal(chair.castShadow,false);
assert.equal(shared.color.getHexString(),'ffffff');assert.equal(chair.material.color.getHexString(),'224466');
console.log('ok glTF metres, bottom-centre, budget, kind suggestion, opening fit, schema and isolated material properties');

// Exercise the actual import loader including its URL authentication for a
// nested glTF and relative buffer, rather than just calling the geometry helper.
const {rememberImport,loadModel} = await import(file('static/twin/twin_library.js'));
window.location={href:'http://house.test/ingress/house/editor'};window.chfBase='/ingress/';
window.chfAuthUrl=url=>url+(url.includes('?')?'&':'?')+'member_token=test';
const asset='import-'+ '1'.repeat(32), doc=structuredClone(documentGLTF);doc.buffers[0].uri='../mesh.bin';
rememberImport({id:asset,model:'nested/model.gltf',files:{'nested/model.gltf':true,'mesh.bin':true}});
const fetched=[];globalThis.fetch=async input=>{
 const url=typeof input==='string'?input:input.url;fetched.push(url);
 return new Response(url.includes('mesh.bin')?Buffer.from(vertices.buffer):JSON.stringify(doc),{status:200,headers:{'content-type':url.includes('mesh.bin')?'application/octet-stream':'model/gltf+json'}});
};
const imported=await loadModel(asset,{});assert.ok(imported);
assert.ok(fetched.some(u=>u.includes('/imports/'+asset+'/mesh.bin?member_token=test')));
near(new THREE.Box3().setFromObject(imported).min.y,0);
console.log('ok authenticated nested glTF import loads its included relative buffer');
// The real pages use a page-relative base ('../'): the model URL must resolve against the
// page, not the model's folder, or the loader refuses its own file (browser bug 2026-11-12).
window.location={href:'http://house.test/house/editor'};window.chfBase='../';
const relativeAsset='import-'+'2'.repeat(32);
rememberImport({id:relativeAsset,model:'nested/model.gltf',files:{'nested/model.gltf':true,'mesh.bin':true}});
fetched.length=0;
assert.ok(await loadModel(relativeAsset,{}),'a page-relative base still loads the import');
assert.ok(fetched.some(u=>u.includes('/imports/'+relativeAsset+'/nested/model.gltf')),fetched.join(' '));
window.location={href:'http://house.test/ingress/house/editor'};window.chfBase='/ingress/';
console.log('ok a page-relative base loads an import');

const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const openingBuilding=flat.buildings.find(b=>b.openings.some(o=>o.wall && o.state!=='ghost'));
const opening=openingBuilding.openings.find(o=>o.wall && o.state!=='ghost');
const dimensionsBefore=[opening.width,opening.head,opening.sill];opening.model=asset;
const built=buildTwin(flat,kit,'low');await built.ready;
const rendered=built.pieces.get(`${openingBuilding.id}:${opening.id}`);
assert.ok(rendered?.length,'modelled opening remains a selectable piece');
assert.ok(rendered.some(o=>!o.userData.pendingImport),'the real opening builder replaced its placeholder');
assert.deepEqual([opening.width,opening.head,opening.sill],dimensionsBefore);
const {disposeObject}=await import(file('static/twin/twin_library.js'));disposeObject(built.root);delete opening.model;
console.log('ok actual asynchronous opening builder replaces its placeholder and retains the opening cut dimensions');

// Real canvas rays reach both object handles. The editor's existing history
// owns undo/redo, so each release must be exactly one history.perform.
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const {createHistory}=await import(file('static/twin/editor/history.js'));
const nodes=new Map();document.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};document.querySelector=()=>null;
const view=await mountTwin(new Element(),{plan:flat,kit,tier:'low',preserveCamera:true});
let source=flat, round=1;source.site.furniture=[{id:'free-chair',at:[0,0],scale:1,rotation:0}];
const snapshots=new Map([[1,structuredClone(source)]]), abort=new AbortController();
const selected={kind:'furniture',id:'free-chair',building:null};
const history=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>true,refresh:async()=>{},signal:abort.signal});
let commits=0;
const handles=createHandles({view,getPlan:()=>source,getSelection:()=>selected,canEdit:()=>true,drag:{},signal:abort.signal,
 onCommit:operation=>history.perform(async()=>{commits++;assert.equal(operation.op,'set_object');Object.assign(source.site.furniture[operation.index],operation.properties);snapshots.set(++round,structuredClone(source));})});
view.camera.position.set(0,30,.01);view.camera.lookAt(0,0,0);view.camera.updateMatrixWorld(true);
function event(at){const p=new THREE.Vector3(at[0]*.3048,at[2]*.3048,-at[1]*.3048).project(view.camera);return {clientX:(p.x+1)*720,clientY:(1-p.y)*450};}
let handle=handles.handles().find(h=>h.kind==='object_rotate');assert.ok(handle);
assert.ok(handles.begin(event(handle.at)));handles.update(event([0,2,0]));await handles.finish();
near(source.site.furniture[0].rotation,90);assert.equal(commits,1);
handle=handles.handles().find(h=>h.kind==='object_scale');assert.ok(handles.begin(event(handle.at)));
handles.update(event(handle.at.map(n=>n*1.5)));await handles.finish();near(source.site.furniture[0].scale,1.5);assert.equal(commits,2);
const scaleBeforeCancel=source.site.furniture[0].scale;
handle=handles.handles().find(h=>h.kind==='object_scale');handles.begin(event(handle.at));handles.update(event(handle.at.map(n=>n*2)));await handles.finish(true);
assert.equal(commits,2);near(source.site.furniture[0].scale,scaleBeforeCancel);
globalThis.fetch=async(_url,options)=>{const body=JSON.parse(options.body);source=structuredClone(snapshots.get(body.round));snapshots.set(++round,structuredClone(source));return {ok:true,text:async()=>JSON.stringify({round})};};
nodes.get('rail-undo').dispatchEvent(new Event('click'));await new Promise(resolve=>setTimeout(resolve,10));near(source.site.furniture[0].scale,1);
nodes.get('rail-redo').dispatchEvent(new Event('click'));await new Promise(resolve=>setTimeout(resolve,10));near(source.site.furniture[0].scale,1.5);
assert.deepEqual(objects.transformObject({rotation:0},'rotate',true),{rotation:345});
near(objects.transformObject({scale:1},'scale').scale,1.1);
abort.abort();view.dispose();console.log('ok real rotate/scale handle gestures post once, cancel, undo and redo');
"""


def run():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text())
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text()); kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='twin_objects_node_') as temp:
        driver, config = Path(temp) / 'driver.mjs', Path(temp) / 'config.json'
        driver.write_text(DRIVER, encoding='utf-8'); config.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': flat, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(config)], capture_output=True, text=True, timeout=90)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
