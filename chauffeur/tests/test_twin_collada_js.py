"""Real vendored Collada/KMZ/TGA parsers with a fixture-only XML DOM, no packages."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from collada_fixture import dae, TGA
from test_twin_drag_js import DRIVER as BASE

ROOT = Path(__file__).resolve().parents[1]

DRIVER = BASE.split('const {createDrag, piecesOnMovedJoints}')[0] + r'''
const fixture = JSON.parse(readFileSync(process.argv[2]));
// Node has no XML DOM. Only the DOM is adapted; all Collada interpretation,
// geometry, material creation, unit conversion and KMZ decoding are real r187.
class XMLNode {
 constructor(row){this.nodeName=row.name;this.nodeType=1;this.attrs=row.attrs||{};this.text=row.text||'';this.childNodes=(row.children||[]).map(r=>new XMLNode(r));}
 get textContent(){return this.text+this.childNodes.map(c=>c.textContent).join('');}
 set textContent(value){this.text=value;this.childNodes=[];}
 getAttribute(name){return this.attrs[name]??null;}
 setAttribute(name,value){this.attrs[name]=String(value);}
 hasAttribute(name){return Object.hasOwn(this.attrs,name);}
 getElementsByTagName(name){return this.childNodes.flatMap(c=>[...(c.nodeName===name?[c]:[]),...c.getElementsByTagName(name)]);}
 querySelector(selector){
  const attr=selector.match(/^\[(id|sid)="([^"]+)"\]$/);
  if(attr)return this.descendants().find(n=>n.getAttribute(attr[1])===attr[2])||null;
  let nodes=[this];for(const tag of selector.split(' '))nodes=nodes.flatMap(n=>n.getElementsByTagName(tag));return nodes[0]||null;
 }
 descendants(){return this.childNodes.flatMap(c=>[c,...c.descendants()]);}
}
globalThis.DOMParser=class {parseFromString(text){
 const doc=new XMLNode({name:'#document'}),stack=[doc];
 const decode=s=>s.replaceAll('&lt;','<').replaceAll('&quot;','"').replaceAll('&amp;','&');
 for(const part of text.match(/<[^>]*>|[^<]+/g)||[]){
  if(part.startsWith('<?')||part.startsWith('<!'))continue;
  if(part.startsWith('</')){stack.pop();continue;}
  if(part.startsWith('<')){
   const name=part.match(/^<([^\s/>]+)/)[1],attrs={};
   for(const [,key,value] of part.matchAll(/([^\s=]+)="([^"]*)"/g))attrs[key]=decode(value);
   const node=new XMLNode({name,attrs});stack.at(-1).childNodes.push(node);
   if(!part.endsWith('/>'))stack.push(node);
  }else stack.at(-1).text+=decode(part);
 }
 return doc;
}};
globalThis.XMLSerializer=class{serializeToString(doc){
 const escape=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
 const write=n=>n.nodeName==='#document'?n.childNodes.map(write).join(''):`<${n.nodeName}${Object.entries(n.attrs).map(([k,v])=>` ${k}="${escape(v)}"`).join('')}>${escape(n.text)}${n.childNodes.map(write).join('')}</${n.nodeName}>`;
 return write(doc);
}};
globalThis.ProgressEvent=class{constructor(type,values){Object.assign(this,values);}};
globalThis.self=globalThis;
const THREE=await import(three);
const {ColladaLoader}=await import(file('static/vendor/three-r187/addons/loaders/ColladaLoader.js'));
const {KMZLoader}=await import(file('static/vendor/three-r187/addons/loaders/KMZLoader.js'));
const {GLTFLoader}=await import(file('static/vendor/three-r187/addons/loaders/GLTFLoader.js'));
const {zipSync,strToU8}=await import(file('static/vendor/three-r187/addons/libs/fflate.module.js'));
const objects=await import(file('static/twin/objects.js'));
const {modelLoader}=await import(file('static/twin/import_loaders.js'));
const {rememberImport,loadModel,disposeObject}=await import(file('static/twin/twin_library.js'));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} near ${b}`);
const text=fixture.dae;
const direct=new ColladaLoader().parse(text,'');
const bounds=new THREE.Box3().setFromObject(direct.scene).getSize(new THREE.Vector3());
near(bounds.x,2.54);near(bounds.y,5.08);near(bounds.z,1.27);
near(direct.scene.rotation.x,-Math.PI/2);near(direct.scene.scale.x,.0254);
console.log('ok real ColladaLoader converts authored inches and Z_UP exactly once');

window.location={href:'http://house.test/house/editor'};window.chfBase='../';
window.chfAuthUrl=url=>url+(url.includes('?')?'&':'?')+'member_token=test';
const nativeFetch=globalThis.fetch, fetched=[];
let response=text;
globalThis.fetch=async input=>{
 const url=typeof input==='string'?input:input.url;
 if(url.startsWith('blob:'))return nativeFetch(input);
 fetched.push(url);return new Response(response,{status:200});
};
function check(model){
 assert.ok(model);const box=new THREE.Box3().setFromObject(model),size=box.getSize(new THREE.Vector3());
 near(size.x,2.54);near(size.y,5.08);near(size.z,1.27);
 near(box.min.y,0);near(box.min.x+box.max.x,0);near(box.min.z+box.max.z,0);
 assert.equal(objects.modelBudget(model,{resizeTextures:false}).triangles,1);
 let material;model.traverse(o=>{if(o.isMesh)material=o.material;});
 assert.equal(material.type,'MeshStandardMaterial');near(material.roughness,.7);near(material.metalness,0);
 near(material.opacity,.6);assert.equal(material.transparent,true);return material;
}
for(const [suffix,body] of [['dae',text],['kmz',zipSync({'models/scene.dae':strToU8(text)})]]){
 response=body;const id='import-'+(suffix==='dae'?'a':'b').repeat(32),name='nested/model.'+suffix;
 rememberImport({id,model:name,files:{[name]:true}});
 const model=await loadModel(id,{});check(model);
 let authoredMaterial;direct.scene.traverse(o=>{if(o.isMesh)authoredMaterial=o.material;});
 const standard=check(model);standard.color.toArray().forEach((v,i)=>near(v,authoredMaterial.color.toArray()[i]));
 assert.ok(fetched.some(u=>u.includes(`/imports/${id}/${name}?member_token=test`)));
 disposeObject(model);
}
console.log('ok extension-selected DAE and real KMZ load with page-relative auth, metre size, bottom-centre and standard materials');
response=text.replaceAll('phong','lambert');
const lambertId='import-'+'7'.repeat(32);rememberImport({id:lambertId,model:'lambert.dae',files:{'lambert.dae':true}});
const lambert=await loadModel(lambertId,{});check(lambert);disposeObject(lambert);
for(const [name,type] of [['a.GLB',GLTFLoader],['a.gltf',GLTFLoader],['a.DAE',ColladaLoader],['a.KMZ',KMZLoader]]){
 assert.ok(modelLoader(name,new THREE.LoadingManager(),{[name]:true}) instanceof type);
}
console.log('ok loader selection covers glTF, GLB, Collada and KMZ');

for(const uri of ['../../secret.png','https://evil.test/x.png','/outside.png','file:///C:/x.png']){
 const bad=fixture.textured.replace('../textures/texture.tga',uri);
 const loader=modelLoader('models/scene.dae',new THREE.LoadingManager(),{'models/scene.dae':true,'textures/texture.tga':true});
 assert.throws(()=>loader.parse(bad,''),/included resources/);
 const kmz=modelLoader('a.kmz',new THREE.LoadingManager(),{});
 assert.throws(()=>kmz.parse(zipSync({'models/scene.dae':strToU8(bad),'textures/texture.tga':new Uint8Array(fixture.tga)}).buffer),/included resources/);
 kmz.release();
}
const badId='import-'+'c'.repeat(32);response=fixture.textured.replace('../textures/texture.tga','https://evil.test/x.png');
rememberImport({id:badId,model:'bad.dae',files:{'bad.dae':true}});
assert.equal(await loadModel(badId,{}),null);assert.ok(!fetched.some(u=>u.includes('evil.test')));
console.log('ok actual load path and both parsers refuse outside texture paths before fetching');

// Real TGALoader exercises asynchronous texture readiness and exact nested KMZ
// lookup. Browser image decoding of PNG is covered by the written live scenario.
const originalFetch=globalThis.fetch;
globalThis.fetch=async input=>{
 const url=typeof input==='string'?input:input.url;
 if(url.includes('texture.tga')){fetched.push(url);return new Response(new Uint8Array(fixture.tga));}
 return originalFetch(input);
};
for(const suffix of ['dae','kmz']){
 const id='import-'+(suffix==='dae'?'d':'e').repeat(32), name=suffix==='dae'?'models/scene.dae':'scene.kmz';
 response=suffix==='dae'?fixture.textured:zipSync({
  'models/scene.dae':strToU8(fixture.textured), 'textures/texture.tga':new Uint8Array(fixture.tga),
  'other/texture.tga':new Uint8Array([0]),
  'doc.kml':strToU8('<kml><Placemark><Model><Link><href>models/scene.dae</href></Link></Model></Placemark></kml>'),
 });
 rememberImport({id,model:name,files:{[name]:true,'textures/texture.tga':true}});
 const loaded=await loadModel(id,{}),material=check(loaded);
 assert.ok(material.map?.image?.data);assert.equal(material.map.image.width,1);
 assert.deepEqual([...material.map.image.data].slice(0,3),[160,80,40]);
 disposeObject(loaded);
}
assert.ok(fetched.some(u=>u.endsWith('texture.tga?member_token=test')));
console.log('ok real TGA textures finish before cloning; nested KMZ uses exact included texture, with original material map');

// Exercise the editor entry point through chunk upload, preview and the submit
// handler: the PATCH must carry the loaded count, not the pending null metadata.
const {mountImports}=await import(file('static/twin/editor/imports.js'));
window.twinObjectSchema=JSON.parse(readFileSync(root+'/static/twin/object_schema.json'));
Element.prototype.focus=function(){};Element.prototype.toDataURL=()=> 'data:image/png;base64,fixture';
const nodes=new Map(), host=new Element();
document.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
document.getElementById('editor-scene').parentElement=host;
host.append=function(card){queueMicrotask(()=>card.dispatchEvent(new Event('submit',{cancelable:true})));};
const editorId='import-'+'f'.repeat(32),entry={id:editorId,name:'Fixture',model:'scene.dae',files:{'scene.dae':true},triangles:null};
let patchBody,changed;
const completed=new Promise(resolve=>{changed=resolve;});
globalThis.fetch=async(input,options={})=>{
 const url=typeof input==='string'?input:input.url;
 const reply=value=>new Response(JSON.stringify(value),{status:200});
 if(url.includes('import-settings'))return reply({limit_mb:50,unpacked_limit_mb:200});
 if(url.endsWith('/imports/uploads'))return reply({upload_id:'fixture',chunk_bytes:4194304});
 if(url.endsWith('/fixture/0'))return reply({received:text.length,index:1});
 if(url.endsWith('/fixture/finish'))return reply(entry);
 if(options.method==='PATCH'){patchBody=JSON.parse(options.body);return reply({...entry,...patchBody});}
 if(url.endsWith('/api/house/twin/imports'))return reply([{...entry,...patchBody}]);
 if(url.includes('/imports/'+editorId+'/scene.dae'))return new Response(text);
 throw new Error('Unexpected editor request: '+url);
};
const abort=new AbortController();
mountImports({canvas:new Element(),kit:{},canEdit:()=>true,signal:abort.signal,changed});
const picked=new Blob([text]);picked.name='scene.dae';
const picker=document.getElementById('library-import-files');picker.files=[picked];picker.dispatchEvent(new Event('change'));
await Promise.race([completed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Editor did not confirm: '+document.getElementById('library-status').textContent)),2000))]);
assert.equal(patchBody.triangles,1);patchBody.size.forEach((v,i)=>near(v,[2.54,5.08,1.27][i]));abort.abort();
console.log('ok actual editor chunk upload, preview and confirmation PATCH send the measured triangle count and metre size');
'''


def run():
    with tempfile.TemporaryDirectory(prefix='collada_node_') as temp:
        driver, config = Path(temp) / 'driver.mjs', Path(temp) / 'config.json'
        driver.write_text(DRIVER, encoding='utf-8')
        config.write_text(json.dumps({'root': ROOT.as_posix(),
            'dae': dae().decode(), 'textured': dae('../textures/texture.tga').decode(), 'tga': list(TGA)}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(config)], capture_output=True, text=True, timeout=90)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
