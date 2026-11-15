"""Alpha classification, atlas keys and stale-publication rejection through mountBake."""
import sys
from pathlib import Path
from twin_editor_dom import run_node
from test_twin_alpha_render_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {buildAtlas,atlasMesh}=await import(file('static/twin/bake/atlas.js'));
const {bakeLayout}=await import(file('static/twin/bake/baker.js'));
const {mountBake}=await import(file('static/twin/bake/runtime.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const layout={room:{density:1,page:256,gutter:2}},id='alpha-siding';
const plan={buildings:[{id:'b',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:8,outline:[[0,0],[8,0],[8,8],[0,8]]}],
 rooms:[{id:'r',level:'L1',polygon:[[0,0],[8,0],[8,8],[0,8]]}],
 materials:{siding:{id}},walls:[[[0,0],[8,0]],[[8,0],[8,8]],[[8,8],[0,8]],[[0,8],[0,0]]].map(([from,to],i)=>
 ({id:'w'+i,level:'L1',from,to,height:8,thickness:.5,exterior:true})),openings:[],roofs:[]}],site:{},materials:{}};
const kit=(mode,params={},maps={})=>({materials:{},manifest:{[id]:{household:true,kind:'material',revision:1,
 params:{alpha_mode:mode,...params},maps}}});
const meshes=root=>{const a=[];root.traverse(o=>{if(atlasMesh(o))a.push(o);});return a;};
async function scene(mode,tier='low',params={},maps={}){
 const out=buildTwin(plan,kit(mode,params,maps),tier);
 // Deliberately do not await optional maps: classification is synchronous.
 const receivers=meshes(out.root),siding=receivers.filter(m=>m.material.name==='siding');
 const atlas=buildAtlas(out.root,plan,layout);
 return {out,atlas,count:receivers.length,siding:siding.length};
}
// Run the actual atlas worker module; only the browser's message boundary is faked.
let workerId=0;globalThis.alphaWorkerScopes={};
registerHooks({load(url,ctx,next){
 const result=next(url,ctx),n=new URL(url).searchParams.get('alphaWorker');
 if(!n)return result;
 const source=typeof result.source==='string'?result.source:new TextDecoder().decode(result.source);
 return {...result,source:`const self=globalThis.alphaWorkerScopes[${JSON.stringify(n)}];\n`+source};
}});
globalThis.Worker=class{
 constructor(url){const n=String(++workerId),target=new URL(url);
  this.scope={postMessage:data=>queueMicrotask(()=>this.onmessage?.({data}))};globalThis.alphaWorkerScopes[n]=this.scope;
  target.searchParams.set('alphaWorker',n);this.loaded=import(target.href);
 }
 postMessage(data){this.loaded.then(()=>this.scope.onmessage({data})).catch(error=>this.onerror?.({error}));}
 terminate(){}
};
const lights=[{device:'lamp',building:'b',level:'L1',room:'r',at:[4,4,6]}];
const live={markers:lights.map(l=>({...l,device_id:l.device,kind:'light',placed:true}))};
function stored(old){
 const packed=bakeLayout(old.atlas,layout,lights);
 const manifest={complete:true,round:1,densities:{room:1},lights:packed.entries,ownership:packed.ownership};
 const calls=[];
 return {calls,api:async path=>{
  calls.push(path);
  if(path==='api/house/live')return new Response(JSON.stringify(live));
  if(path===`api/house/bakes/${old.atlas.key}`)return new Response(JSON.stringify(manifest));
  if(path.startsWith(`api/house/bakes/${old.atlas.key}/`))return new Response(new Uint8Array([1,2,3]));
  return new Response('{}',{status:404});
 }};
}
await test('flipping_alpha_mode_changes_the_atlas_key_and_drops_the_stored_bake',async()=>{
 for(const mode of ['cutout','blend'])for(const reverse of [false,true]){
  const old=await scene(reverse?mode:'opaque'),next=await scene(reverse?'opaque':mode);
  let controller;
  try{
   assert.notEqual(next.atlas.key,old.atlas.key);
   const opaque=reverse?next:old,alpha=reverse?old:next;
   assert.ok(opaque.siding>0);assert.equal(alpha.siding,0);
   assert.equal(alpha.count,opaque.count-opaque.siding,'only siding receivers leave the atlas');
   const server=stored(old),view={plan,ready:true,tier:'low',controls:new THREE.EventDispatcher(),
    renderer3:new Renderer(),render(){}};
   controller=mountBake(view,next.out.root,{layout,poll:0,api:server.api});await controller.refresh();
   assert.equal(controller.state().key,next.atlas.key);assert.equal(controller.state().error,null);
   assert.deepEqual(controller.fresh(),[]);assert.deepEqual(controller.state().baked,[]);
   assert.equal(controller.held(),null,'unbaked runtime allocates no shadowmask arrays');
   assert.equal(controller.packing(),null);assert.equal(controller.state().baking,false);
   assert.ok(server.calls.includes(`api/house/bakes/${next.atlas.key}`));
   assert.ok(!server.calls.some(p=>p.startsWith(`api/house/bakes/${old.atlas.key}`)));
   next.out.root.traverse(o=>{for(const m of [].concat(o.material||[])){
    assert.ok(!m.lightMap);assert.equal(m.userData.lmOriginalKey,undefined,'no shadowmask shader patch');
    assert.ok(!Object.values(m).some(t=>t?.isDataArrayTexture||t?.isCompressedArrayTexture));
   }});
  }finally{controller?.stop();disposeObject(old.out.root);disposeObject(next.out.root);}
 }
});
await test('opacity_or_cutoff_change_keeps_the_key',async()=>{
 for(const [mode,key,values] of [['blend','opacity',[.4,.6]],['cutout','alpha_cutoff',[0,.7]]]){
  const a=await scene(mode,'low',{[key]:values[0]}),b=await scene(mode,'low',{[key]:values[1]});
  assert.equal(a.atlas.key,b.atlas.key);assert.equal(a.count,b.count);disposeObject(a.out.root);disposeObject(b.out.root);
 }
});
await test('low_and_high_tiers_build_the_same_key_with_a_cutout_material',async()=>{
 const load=THREE.TextureLoader.prototype.load,requested=[];
 THREE.TextureLoader.prototype.load=function(url){requested.push(url);return new THREE.Texture();};
 let low,high;
 try{const maps={opacity:'materials/held/opacity.png'};
  low=await scene('cutout','low',{},maps);high=await scene('cutout','high',{},maps);
  assert.ok(requested.length);assert.equal(low.atlas.key,high.atlas.key);assert.equal(low.count,high.count);
 }finally{THREE.TextureLoader.prototype.load=load;if(low)disposeObject(low.out.root);if(high)disposeObject(high.out.root);}
});
await test('mounted_mode_flip_remounts_bake_at_the_new_key',async()=>{
 const nativeFetch=globalThis.fetch,k=kit('opaque'),old=await scene('opaque'),server=stored(old);let v;
 globalThis.fetch=async url=>{
  const path=String(url).replace(/^\//,'');
  if(path==='api/house/twin/materials/manifest')return new Response(JSON.stringify({revision:1,entries:k.manifest}));
  return server.api(path);
 };
 try{v=await mountTwin(new Element(),{plan,kit:k,tier:'low',bake:true});
  await v.bake.refresh();const oldController=v.bake,oldKey=oldController.state().key;
  k.manifest[id]={...k.manifest[id],revision:2,params:{alpha_mode:'blend',opacity:.4}};
  await v.refreshMaterials([id]);await v.bake.refresh();
  assert.notEqual(v.bake,oldController);assert.notEqual(v.bake.state().key,oldKey);
  assert.equal(v.bake.state().error,null);assert.equal(v.bake.held(),null);assert.deepEqual(v.bake.fresh(),[]);
 }finally{v?.dispose();globalThis.fetch=nativeFetch;disposeObject(old.out.root);}
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code or 0)
