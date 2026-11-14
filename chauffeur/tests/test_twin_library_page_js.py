"""Library page event paths with real DOM controls and real three materials."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const textures=[];
THREE.TextureLoader.prototype.load=function(url,done){textures.push(url);const t=new THREE.Texture({width:32,height:32});queueMicrotask(()=>done(t));return t;};
const {mountLibraryPage,libraryApi}=await import(file('static/twin/library_page/page.js'));
const {createPreview}=await import(file('static/twin/library_page/preview.js'));
const {libraryMaterialHref}=await import(file('static/twin/editor/library.js'));
const clone=x=>structuredClone(x), pause=ms=>new Promise(r=>setTimeout(r,ms));
const edit=(input,type,fields)=>{Object.assign(input,fields);return fire(input,type);};
const params={tint:'#ffffff',roughness:null,metalness:null,normal_scale:1,normal_convention:'gl',ao_intensity:1,tile_ft:[4,4],rotation_deg:0,random_offset:false};
const record=(id='material-test',source='user')=>({id,name:id,source,revision:1,maps:{},params:clone(params),licence:'CC0',source_snapshot:source==='user'?{maps:{},params:clone(params)}:null});
let drawn,drawnScene;
const render=Renderer.prototype.render;
Renderer.prototype.render=function(scene,camera){drawnScene=scene;scene.traverse(n=>{if(n.userData.librarySample)drawn=n;});return render.call(this,scene,camera);};
async function setup(first=record(),hooks={}){
 const host=document.createElement('main');document.body.append(host);
 const calls=[],alerts=[];let saved=clone(first),rejectPatch=false,refuseDelete=false;
 window.showGlobalAlert=t=>alerts.push(t);window.promptConfirm=async()=>true;
 for(const name of ['alert','confirm','prompt'])window[name]=()=>{throw Error('browser dialog');};
 const api=async(path,method='GET',body)=>{
  calls.push({path,method,body:body instanceof Blob?body:clone(body)});
  if(path==='materials'&&method==='GET')return {materials:[first,record('brick','builtin'),record('download','polyhaven')].map(r=>({...r,builtin:r.source==='builtin'}))};
  if(method==='DELETE'&&!path.includes('/maps/')){if(refuseDelete)throw Error('Used on 3 surfaces: Main House walls (2), Fence boards (1)');return {archived:false};}
  if(method==='PATCH'){
   await hooks.patch?.(body);
   if(rejectPatch)throw Error('roughness must be from 0 to 2.');
   saved={...saved,...body,params:{...saved.params,...body.params},revision:saved.revision+1};
  }
  if(method==='POST'&&path.includes('/maps/'))saved.maps[path.split('/').at(-1)]='maps/hash.png';
  if(method==='DELETE'&&path.includes('/maps/'))delete saved.maps[path.split('/').at(-1)];
  if(path.endsWith('/duplicate')||path==='materials'&&method==='POST')saved=record('material-copy');
  return clone(saved);
 };
 location.search='?material='+first.id;
 const page=mountLibraryPage(host,{api});await page.ready;tick();
 const field=(key,type='number')=>host.querySelector(`[data-param="${key}"][type="${type}"]`);
 const action=name=>host.querySelector(`[data-action="${name}"]`);
 return {host,page,calls,alerts,field,action,get saved(){return saved;},set reject(v){rejectPatch=v;},set refuse(v){refuseDelete=v;}};
}
await test('param_change_updates_preview_without_fetch',async()=>{
 const c=await setup();await edit(c.field('roughness','checkbox'),'change',{checked:false});
 c.calls.length=0;const m=drawn.material,version=m.version;
 await edit(c.field('roughness','range'),'input',{value:'0.4'});
 assert.equal(m.roughness,.4);assert.equal(c.calls.length,0);
 await pause(140);await edit(c.field('roughness','range'),'input',{value:'1.2'});
 assert.equal(m.roughness,1.2);assert.equal(m.version,version,'uniform edits must not recompile');
 await pause(210);assert.equal(c.calls.length,0);await pause(120);
 const patches=c.calls.filter(c=>c.method==='PATCH');assert.equal(patches.length,1);assert.equal(patches[0].body.params.roughness,1.2);c.page.stop();
});
await test('auto_toggles_and_numeric_ranges',async()=>{
 const c=await setup();assert.equal(c.field('metalness','checkbox').checked,true);
 await edit(c.field('metalness','checkbox'),'change',{checked:false});
 await edit(c.field('metalness'),'input',{value:'1.5'});assert.equal(drawn.material.metalness,1.5);
 await edit(c.field('metalness','checkbox'),'change',{checked:true});assert.equal(drawn.material.metalness,0);
 for(const [key,min,max] of [['roughness','0','2'],['metalness','0','2'],['normal_scale','0','4'],['ao_intensity','0','2'],['tile_ft.0','0.25','200'],['tile_ft.1','0.25','200'],['rotation_deg','0','359']]){
  assert.equal(c.field(key).min,min);assert.equal(c.field(key).max,max);
 }
 c.page.stop();await pause(10);
});
await test('failed_patch_restores_server_value_and_reason',async()=>{
 const c=await setup();c.reject=true;await edit(c.field('normal_scale','range'),'input',{value:'3'});
 c.saved.params.normal_scale=.75;
 assert.equal(drawn.material.normalScale.x,3);await pause(340);
 assert.equal(drawn.material.normalScale.x,.75);assert.equal(Number(c.field('normal_scale').value),.75);
 assert.deepEqual(c.alerts,['roughness must be from 0 to 2.']);c.page.stop();
});
await test('builtin_shows_duplicate_not_edit',async()=>{
 const c=await setup(record('brick','builtin'));assert.ok(c.action('duplicate'));
 assert.equal(c.action('delete'),null);assert.equal(c.action('undo'),null);
 assert.equal(c.host.querySelector('[data-param]'),null);
 assert.equal(c.host.querySelector('input[type="file"]'),null);
 await click(c.action('duplicate'));assert.ok(c.calls.some(x=>x.path==='materials/brick/duplicate'&&x.method==='POST'));c.page.stop();
});
await test('delete_refusal_shows_reason_no_dialog',async()=>{
 const c=await setup();c.refuse=true;await click(c.action('delete'));
 assert.deepEqual(c.alerts,['Used on 3 surfaces: Main House walls (2), Fence boards (1)']);c.page.stop();
});
await test('undo_redo_call_routes_and_flush_pending',async()=>{
 const c=await setup();await edit(c.field('normal_scale'),'input',{value:'2'});
 await click(c.action('undo'));await click(c.action('redo'));await click(c.action('reset'));
 assert.deepEqual(c.calls.filter(x=>x.method!=='GET').map(x=>[x.path,x.method]),[
  ['materials/material-test','PATCH'],['materials/material-test/undo','POST'],['materials/material-test/redo','POST'],['materials/material-test/reset','POST']]);c.page.stop();
});
await test('map_replace_local_preview_and_clear_raw_bytes',async()=>{
 const c=await setup();const input=c.host.querySelector('[data-slot="normal"] input[type="file"]');
 const blob=new Blob(['raw image bytes'],{type:'image/png'});input.files=[blob];
 await fire(input,'change');assert.ok(textures.some(u=>u.startsWith('blob:')));
 const upload=c.calls.find(x=>x.method==='POST');assert.equal(upload.path,'materials/material-test/maps/normal');assert.equal(upload.body,blob);
 await click(c.host.querySelector('[data-slot="normal"] [data-action="clear"]'));
 assert.ok(c.calls.some(x=>x.method==='DELETE'&&x.path==='materials/material-test/maps/normal'));c.page.stop();
});
await test('filter_search_new_and_no_snapshot_reset',async()=>{
 const r=record();r.source_snapshot=null;const c=await setup(r);assert.equal(c.action('reset'),null);
 const search=c.host.querySelector('[data-library-search]');await edit(search,'input',{value:'brick'});
 assert.equal(c.host.querySelectorAll('[data-material]').length,1);
 await edit(search,'input',{value:''});await edit(c.host.querySelector('[data-library-source]'),'change',{value:'downloaded'});
 assert.equal(c.host.querySelectorAll('[data-material]').length,1);
 await click(c.action('new'));assert.ok(c.calls.some(x=>x.path==='materials'&&x.method==='POST'));c.page.stop();
});
await test('preview_shapes_light_scale_and_dispose',async()=>{
 const canvas=document.createElement('canvas'),p=createPreview(canvas);p.setMaterial(record(),params);
 for(const shape of ['sphere','cube','wall','ground']){p.setShape(shape);tick();assert.ok(drawn.geometry);if(shape==='wall')assert.equal(Math.max(...drawn.geometry.attributes.uv.array),8);}
 const figure=drawnScene.getObjectByName('6 ft scale figure');assert.ok(figure);
 assert.ok(Math.abs(new THREE.Box3().setFromObject(figure).getSize(new THREE.Vector3()).y-6*.3048)<1e-6);
 const m=drawn.material;let disposed=0;m.addEventListener('dispose',()=>disposed++);
 p.setLight('sun');p.setLight('studio');p.dispose();assert.equal(disposed,1);
});
await test('slow_patch_keeps_newer_preview_and_serializes_writes',async()=>{
 let release;const gate=new Promise(r=>{release=r;});let count=0;
 const c=await setup(record(),{patch:async()=>{if(++count===1)await gate;}});
 await edit(c.field('normal_scale'),'input',{value:'2'});await pause(310);
 await edit(c.field('normal_scale'),'input',{value:'3'});await pause(310);
 assert.equal(count,1);assert.equal(drawn.material.normalScale.x,3);
 release();await pause(30);assert.equal(count,2);assert.equal(drawn.material.normalScale.x,3);
 assert.equal(c.saved.params.normal_scale,3);c.page.stop();
});
await test('mapped_params_keep_textures_and_shader_without_fetch',async()=>{
 const r=record();r.maps={base_color:'maps/base.jpg',normal:'maps/normal.png',orm:'maps/orm.png'};
 const c=await setup(r);await pause(10);const m=drawn.material,map=m.map,version=m.version,loads=textures.length;
 c.calls.length=0;await edit(c.field('tile_ft.0'),'input',{value:'8'});
 await edit(c.field('rotation_deg'),'input',{value:'90'});
 await fire(Object.assign(c.host.querySelector('[data-field="normal_convention"]'),{value:'dx'}),'change');
 assert.equal(m.map,map);assert.equal(textures.length,loads);assert.equal(c.calls.length,0);assert.equal(m.version,version);
 assert.equal(m.normalScale.y,-1);assert.deepEqual(m.map.repeat.toArray(),[1/8,1/4]);assert.equal(m.map.rotation,Math.PI/2);
 c.page.stop();await pause(10);
});
await test('default_api_uses_ingress_raw_bytes_and_server_reason',async()=>{
 const calls=[];window.chfBase='/api/hassio_ingress/test/';
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify(options.method==='PATCH'?{detail:'Server reason'}:{id:'material-test'}),{status:options.method==='PATCH'?400:200});};
 const raw=new Blob(['bytes']);await libraryApi('materials/material-test/maps/normal','POST',raw);
 assert.equal(calls[0].url,'/api/hassio_ingress/test/api/house/materials/material-test/maps/normal');assert.equal(calls[0].options.body,raw);
 await assert.rejects(()=>libraryApi('materials/material-test','PATCH',{name:''}),/Server reason/);
});
await test('late_map_attachment_draws_latest_params',async()=>{
 const load=THREE.TextureLoader.prototype.load,held=[];
 THREE.TextureLoader.prototype.load=function(url,done){held.push(()=>done(new THREE.Texture({width:32,height:32})));return new THREE.Texture();};
 const p=createPreview(document.createElement('canvas')),r=record('material-late');r.maps={roughness:'maps/late-rough.png',normal:'maps/late-normal.png'};
 p.setMaterial(r,r.params);p.setMaterial(r,{...r.params,roughness:.3});held[0]();await pause(5);tick();
 assert.equal(drawn.material.roughness,.3);held[1]();await pause(5);tick();assert.equal(drawn.material.roughness,.3);
 p.dispose();THREE.TextureLoader.prototype.load=load;
});
await test('edit_in_library_link_carries_id',async()=>{
 window.chfBase='/api/hassio_ingress/token/';assert.equal(libraryMaterialHref('brick & stone'),'/api/hassio_ingress/token/house/library?material=brick%20%26%20stone');
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)
