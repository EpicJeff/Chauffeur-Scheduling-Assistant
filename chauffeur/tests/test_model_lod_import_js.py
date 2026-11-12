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
const {generateVersions}=await import(file('static/twin/editor/imports.js'));
const {GLTFLoader}=await import(file('static/vendor/three-r187/addons/loaders/GLTFLoader.js'));
globalThis.ProgressEvent=class {constructor(type,values){Object.assign(this,values);}};
globalThis.FileReader=class {
 readAsArrayBuffer(blob){blob.arrayBuffer().then(value=>{this.result=value;this.onloadend?.();});}
 readAsDataURL(blob){blob.arrayBuffer().then(value=>{this.result='data:'+blob.type+';base64,'+Buffer.from(value).toString('base64');this.onloadend?.();});}
};
Element.prototype.toDataURL=()=> 'data:image/png;base64,preview';
window.chfBase='../';window.location={href:'http://house.test/house/editor'};
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
const abort=new AbortController(),rows=await generateVersions(entry,source,abort.signal);
assert.equal(rows.length,2,'generation must reach exporter and uploads instead of swallowing an error');
assert.deepEqual(entry.lods.map(l=>l.name),['lod1.glb','lod2.glb']);
rows.forEach((row,i)=>assert.equal(row.triangles,entry.lods[i].triangles));
assert.ok(entry.lods[1].bytes<entry.lods[0].bytes);assert.equal(source.children[0].geometry,geometry);assert.equal(source.children[0].material,material);
assert.equal(calls.length,6);assert.ok(rows.every(r=>r.picture.startsWith('data:image/png')));
console.log('ok actual LOD generation, GLTFExporter binary export, two chunk uploads on same import, decoded counts and compact bytes');
globalThis.fetch=async()=>{throw new Error('upload offline');};
assert.deepEqual(await generateVersions(entry,source,new AbortController().signal),[]);
abort.abort();assert.deepEqual(await generateVersions(entry,source,abort.signal),[]);
console.log('ok failed and cancelled optional generation return quietly and preserve original');
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
