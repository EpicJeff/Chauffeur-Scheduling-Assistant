"""Run real LOD simplification/export and binary chunk upload, without Chromium."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_drag_js import DRIVER as BASE

ROOT = Path(__file__).resolve().parents[1]
DRIVER = BASE.split('const {createDrag, piecesOnMovedJoints}')[0] + r'''
const THREE=await import(three);
const {generateVersions,mountImports}=await import(file('static/twin/editor/imports.js'));
const {handleLodMessage}=await import(file('static/twin/lod_worker.js'));
const {GLTFLoader}=await import(file('static/vendor/three-r187/addons/loaders/GLTFLoader.js'));
globalThis.ProgressEvent=class {constructor(type,values){Object.assign(this,values);}};
globalThis.FileReader=class {
 readAsArrayBuffer(blob){blob.arrayBuffer().then(value=>{this.result=value;this.onloadend?.();});}
 readAsDataURL(blob){blob.arrayBuffer().then(value=>{this.result='data:'+blob.type+';base64,'+Buffer.from(value).toString('base64');this.onloadend?.();});}
};
Element.prototype.toDataURL=()=> 'data:image/png;base64,preview';
window.chfBase='../';window.location={href:'http://house.test/house/editor'};
let workerStarts=0,workerStops=0;
window.chfLodWorker={worker:file('static/twin/lod_worker.js')+'?v=1',simplifier:file('static/vendor/meshoptimizer-1.3.0/meshopt_simplifier.js')+'?v=1'};
globalThis.Worker=class {
 constructor(url,options){assert.equal(url,window.chfLodWorker.worker);assert.equal(options.type,'module');workerStarts++;}
 postMessage(message,transfers){
  const copy=structuredClone(message,{transfer:transfers});
  setTimeout(()=>handleLodMessage(copy,(data,transfers)=>{
   if(!this.stopped)this.onmessage({data:structuredClone(data,{transfer:transfers})});
  }),0);
 }
 terminate(){this.stopped=true;workerStops++;}
};
const source=new THREE.Group(),geometry=new THREE.SphereGeometry(2,112,112),material=new THREE.MeshStandardMaterial();
const mesh=new THREE.Mesh(geometry,material);source.add(mesh);
const id='import-'+ '8'.repeat(32),entry={id,kind:'car',model:'original.glb',files:{'original.glb':true},lods:[]};
let upload=null,buffer=null,calls=[];
globalThis.fetch=async (input,opts={})=>{
 const url=typeof input==='string'?input:input.url;
 const reply=value=>new Response(JSON.stringify(value),{status:200});calls.push([url,opts.method]);
 if(url.endsWith('/imports/uploads')){
  upload=JSON.parse(opts.body);assert.equal(upload.asset_id,id);assert.ok(['lod1.glb','lod2.glb'].includes(upload.lod));
  assert.deepEqual(upload.files,[{name:upload.lod,size:upload.size}]);buffer=new Uint8Array();return reply({upload_id:'derived',chunk_bytes:4194304});
 }
 if(url.endsWith('/derived/0')){buffer=new Uint8Array(await opts.body.arrayBuffer());assert.equal(buffer.byteLength,upload.size);return reply({received:buffer.byteLength,index:1});}
 if(url.endsWith('/derived/finish')){
  assert.equal(new DataView(buffer.buffer).getUint32(0,true),0x46546c67,'actual binary GLB');
  const decoded=await new GLTFLoader().parseAsync(buffer.buffer,'');let triangles=0;
  decoded.scene.traverse(o=>{if(o.isMesh)triangles+=(o.geometry.index?.count||o.geometry.attributes.position.count)/3;});
  entry.lods.push({name:upload.lod,triangles,bytes:buffer.byteLength});entry.files[upload.lod]=true;return reply(entry);
 }
 throw new Error('Unexpected derived request '+url);
};
const progress=[];
const abort=new AbortController(),rows=await generateVersions(entry,source,abort.signal,text=>progress.push(text));
assert.equal(rows.length,2,'generation must reach exporter and uploads instead of swallowing an error');
assert.deepEqual(entry.lods.map(l=>l.name),['lod1.glb','lod2.glb']);
rows.forEach((row,i)=>assert.equal(row.triangles,entry.lods[i].triangles));
assert.ok(entry.lods[1].bytes<entry.lods[0].bytes);assert.equal(source.children[0].geometry,geometry);assert.equal(source.children[0].material,material);
assert.equal(calls.length,6);assert.ok(rows.every(r=>r.picture.startsWith('data:image/png')));
assert.deepEqual(progress,['Making lighter versions… 1 of 2','Making lighter versions… 2 of 2']);
assert.equal(workerStarts,2);assert.equal(workerStops,2,'both versions release their worker');
console.log('ok actual LOD generation, GLTFExporter binary export, two chunk uploads on same import, decoded counts and compact bytes');
globalThis.fetch=async()=>{throw new Error('upload offline');};
assert.deepEqual(await generateVersions(entry,source,new AbortController().signal),[]);
abort.abort();assert.deepEqual(await generateVersions(entry,source,abort.signal),[]);
console.log('ok failed and cancelled optional generation return quietly and preserve original');

const ProtocolWorker=globalThis.Worker;delete globalThis.Worker;
const huge=new THREE.Mesh(new THREE.SphereGeometry(2,390,390),material);
const skipped=await generateVersions(entry,huge,new AbortController().signal);
assert.equal(skipped.length,0);assert.match(skipped.note,/200,000 triangles.*worker is unavailable/);
assert.equal(huge.geometry.attributes.position.count,391*391);
console.log('ok no-worker oversized mesh returns no LODs, keeps its original and reports the quiet skip reason');

// Drive the actual add() entry point, including loadModel and details(), with
// a manually advanced rAF queue. Generation must wait until after dialog paint.
const {GLTFExporter}=await import(file('static/vendor/three-r187/addons/exporters/GLTFExporter.js'));
const modelBytes=await new GLTFExporter().parseAsync(source,{binary:true});
const picker=new Element(),status=new Element(),scene=new Element(),host=new Element(),canvas=new Element();
host.append(scene);picker.files=[new File([modelBytes],'dialog.glb')];
document.getElementById=id=>({'library-import-files':picker,'library-status':status,'editor-scene':scene}[id]||null);
Element.prototype.focus=function(){};
Object.defineProperty(Element.prototype,'isConnected',{get(){return !!this.parentElement;}});
window.twinObjectSchema={kinds:{car:{},furniture:{},door:{},window:{}}};
window.showGlobalAlert=message=>{throw new Error(message);};
const fresh={id:'import-'+'9'.repeat(32),name:'dialog',model:'original.glb',files:{'original.glb':true},lods:[]};
let deleted=false;
globalThis.fetch=async(input,opts={})=>{
 const url=typeof input==='string'?input:input.url;
 const json=value=>new Response(JSON.stringify(value));
 if(url.endsWith('/import-settings'))return json({limit_mb:50,unpacked_limit_mb:200});
 if(url.endsWith('/imports/uploads'))return json({upload_id:'dialog',chunk_bytes:4194304});
 if(url.endsWith('/dialog/0'))return json({});
 if(url.endsWith('/dialog/finish'))return json(fresh);
 if(url.includes(fresh.id)&&url.endsWith('original.glb'))return new Response(modelBytes);
 if(url.endsWith('/imports/'+fresh.id)&&opts.method==='DELETE'){deleted=true;return json({});}
 if(url.endsWith('/imports'))return json([]);
 throw new Error('unexpected dialog request '+url);
};
const frames=[];globalThis.requestAnimationFrame=fn=>{frames.push(fn);return frames.length;};
globalThis.cancelAnimationFrame=()=>{};
globalThis.requestIdleCallback=fn=>setTimeout(fn,0);globalThis.cancelIdleCallback=clearTimeout;
const lifecycle=new AbortController();
mountImports({canvas,kit:{},canEdit:()=>true,signal:lifecycle.signal,changed:async()=>{}});
picker.dispatchEvent(new Event('change'));
for(let i=0;i<100&&!host.children.some(n=>n.role==='dialog');i++)await new Promise(r=>setTimeout(r,5));
const dialog=host.children.find(n=>n.role==='dialog');assert.ok(dialog,'details() appended the actual import dialog');
const text=dialog.children.find(n=>n.textContent==='Making lighter versions…');assert.ok(text);
assert.equal(frames.length,1);assert.equal(text.textContent,'Making lighter versions…','generation has not started before rAF');
frames.shift()();await new Promise(r=>setTimeout(r,0));
assert.equal(text.textContent,'Making lighter versions…','first rAF leaves the dialog a paint opportunity');
assert.equal(frames.length,1);
frames.shift()();await new Promise(r=>setTimeout(r,0));
assert.equal(text.textContent,'Making lighter versions… 1 of 2','generation starts after dialog render and frame');
// Cancel while generation awaits its next frame; cleanup must not depend on
// another frame arriving (a closed/background tab may never deliver one).
dialog.children.find(n=>n.textContent==='Cancel').dispatchEvent(new Event('click'));
for(let i=0;i<100&&!deleted;i++)await new Promise(r=>setTimeout(r,5));
assert.equal(deleted,true);assert.equal(host.children.some(n=>n.role==='dialog'),false);
lifecycle.abort();delete globalThis.requestAnimationFrame;
console.log('ok actual mountImports/add renders details before two fake animation frames start generation; Cancel cleans up without another frame');

// Accept more imports while the first worker is deliberately blocked. The
// foreground picker must be free, with exactly one background job at a time.
globalThis.Worker=ProtocolWorker;
let releaseWorker;
const workerGate=new Promise(resolve=>{releaseWorker=resolve;});
let activeWorkers=0,maxWorkers=0;
globalThis.Worker=class extends ProtocolWorker {
 constructor(...args){super(...args);activeWorkers++;maxWorkers=Math.max(maxWorkers,activeWorkers);}
 postMessage(...args){workerGate.then(()=>{if(!this.stopped)super.postMessage(...args);});}
 terminate(){if(!this.stopped)activeWorkers--;super.terminate();}
};
const entries=new Map(),uploads=new Map(),derived=[],changes=[];
let picked=0,uploadSerial=0;
globalThis.fetch=async(input,opts={})=>{
 const url=typeof input==='string'?input:input.url,json=value=>new Response(JSON.stringify(value));
 if(url.endsWith('/import-settings'))return json({limit_mb:50,unpacked_limit_mb:200});
 if(url.endsWith('/imports'))return json([...entries.values()]);
 if(url.endsWith('/imports/uploads')){
  const body=JSON.parse(opts.body),key='queue'+(++uploadSerial);uploads.set(key,body);
  return json({upload_id:key,chunk_bytes:4194304});
 }
 const chunk=url.match(/\/(queue\d+)\/(0|finish)$/);
 if(chunk){
  const body=uploads.get(chunk[1]);if(chunk[2]==='0')return json({});
  if(body.asset_id){const e=entries.get(body.asset_id);assert.ok(e,'cancelled/deleted entries never upload');
   e.lods.push({name:body.lod});e.files[body.lod]=true;derived.push([e.id,body.lod]);return json(e);}
  const e={...fresh,id:'import-'+String(++picked).repeat(32),name:body.name,lods:[],files:{'original.glb':true}};
  entries.set(e.id,e);return json(e);
 }
 const asset=url.match(/\/(import-\d{32})(?:\/original.glb)?$/);
 if(asset){const e=entries.get(asset[1]);
  if(url.endsWith('original.glb'))return new Response(modelBytes);
  if(opts.method==='PATCH'){Object.assign(e,JSON.parse(opts.body));return json(e);}
  if(opts.method==='DELETE'){entries.delete(asset[1]);return json({});}
 }
 throw new Error('unexpected queue request '+url);
};
const queueLife=new AbortController();
const queueControl=mountImports({canvas,kit:{},canEdit:()=>true,signal:queueLife.signal,changed:async(e,options)=>changes.push([e?.id,options])});
const until=async(test,label,pump=false)=>{
 for(let i=0;i<2000&&!test();i++){
  if(pump){const batch=frames.splice(0);batch.forEach(fn=>fn());}
  await new Promise(r=>setTimeout(r,2));
 }
 assert.ok(test(),label);
};
globalThis.requestAnimationFrame=fn=>{frames.push(fn);return frames.length;};
const open=async name=>{
 picker.value=name+'.glb';picker.files=[new File([modelBytes],name+'.glb')];picker.dispatchEvent(new Event('change'));
 await until(()=>host.children.some(n=>n.role==='dialog'),'next import dialog opens while worker is blocked');
 return host.children.find(n=>n.role==='dialog');
};
const accept=async dialog=>{dialog.dispatchEvent(new Event('submit',{cancelable:true}));
 await until(()=>status.textContent!=='Loading model…'&&picker.value==='','accept releases the picker');};
const firstDialog=await open('First');
firstDialog.children.find(n=>n.textContent==='Name').children[0].value='Kia EV9';
await accept(firstDialog);
await until(()=>activeWorkers===1,'first job reaches the worker',true);
await accept(await open('Second'));
const cancelled=await open('Cancelled');cancelled.children.find(n=>n.textContent==='Cancel').dispatchEvent(new Event('click'));
await until(()=>!entries.has('import-'+'3'.repeat(32))&&picker.value==='','queued Cancel deletes its import');
await accept(await open('Deleted'));
const removed='import-'+'4'.repeat(32);queueControl.cancel(removed);entries.delete(removed);
assert.match(status.textContent,/Making lighter versions for Kia EV9/);
assert.equal(derived.length,0,'acceptance does not await optional generation');
assert.equal(activeWorkers,1,'later imports do not start another worker');
releaseWorker();
await until(()=>derived.length===4,'both accepted originals finish their background versions',true);
await until(()=>activeWorkers===0,'workers are released',true);
assert.equal(maxWorkers,1);
assert.deepEqual(derived.map(([id,name])=>[id.at(-1),name]),[['1','lod1.glb'],['1','lod2.glb'],['2','lod1.glb'],['2','lod2.glb']]);
assert.equal(changes.filter(([,options])=>options?.added).length,3);
assert.ok(changes.some(([id,options])=>id.endsWith('2')&&!options),'background metadata reaches the library');
let heldWorker=false;
globalThis.Worker=class extends ProtocolWorker {postMessage(){heldWorker=true;}};
await accept(await open('Close active'));
await until(()=>heldWorker,'closing scenario reaches an active worker',true);
await accept(await open('Close queued'));
const beforeCloseStops=workerStops;queueLife.abort();
await until(()=>workerStops>beforeCloseStops,'closing terminates the active worker');
assert.equal(derived.length,4,'closing cancels active and pending jobs without uploading');
delete globalThis.requestAnimationFrame;
const {forgetImport}=await import(file('static/twin/twin_library.js'));
for(const e of entries.values())forgetImport(e.id);
console.log('ok accepting consecutive imports frees the picker during a blocked worker; one queue survives imports, cancels and deletion');

// Existing imports take the same worker/export/upload path in background.
globalThis.Worker=ProtocolWorker;
const background={...fresh,id:'import-'+'7'.repeat(32),lods:[]};
let derivedName,backgroundUploads=0;
globalThis.fetch=async(input,opts={})=>{
 const url=typeof input==='string'?input:input.url;
 const json=value=>new Response(JSON.stringify(value));
 if(url.endsWith('/import-settings'))return json({limit_mb:50,unpacked_limit_mb:200});
 if(url.endsWith('/imports'))return json([background]);
 if(url.includes(background.id)&&url.endsWith('original.glb'))return new Response(modelBytes);
 if(url.endsWith('/imports/uploads')){
  const body=JSON.parse(opts.body);assert.equal(body.asset_id,background.id);derivedName=body.lod;
  return json({upload_id:'background',chunk_bytes:4194304});
 }
 if(url.endsWith('/background/0'))return json({});
 if(url.endsWith('/background/finish')){
  backgroundUploads++;background.lods.push({name:derivedName});background.files[derivedName]=true;return json(background);
 }
 throw new Error('unexpected background request '+url);
};
const backgroundLife=new AbortController(),workersBefore=workerStarts;
mountImports({canvas,kit:{},canEdit:()=>true,signal:backgroundLife.signal,changed:async()=>{}});
for(let i=0;i<1000&&backgroundUploads<2;i++)await new Promise(r=>setTimeout(r,5));
backgroundLife.abort();
assert.equal(backgroundUploads,2);assert.equal(workerStarts-workersBefore,2);
assert.deepEqual(background.lods.map(l=>l.name),['lod1.glb','lod2.glb']);
console.log('ok existing-import background job uses the same worker, real exporter and derived upload path');
'''

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='lod_export_') as temp:
        driver, config = Path(temp) / 'driver.mjs', Path(temp) / 'config.json'
        driver.write_text(DRIVER, encoding='utf-8')
        config.write_text(json.dumps({'root': ROOT.as_posix()}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(config)], capture_output=True, text=True, timeout=280)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
