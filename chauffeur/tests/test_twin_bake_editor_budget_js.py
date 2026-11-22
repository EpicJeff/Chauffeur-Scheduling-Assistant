"""Full household High parent: three committed edits have no idle atlas work."""
import json
import sys
from twin_editor_dom import run_node
import test_twin_bake_editor_keys_js as K

# Instrument the real entry points, not source-text assertions or geometry fakes.
PREFIX=K.PREFIX.replace("if (url.endsWith('/twin_generator.js')) {", r"""if (/\/(source|baker|lightmap_material|runtime|atlas|atlas_transport)\.js$/.test(url)) {
    const loaded=next(url,{...ctx,format:'module'});let source=String(loaded.source);
    const name=url.endsWith('/source.js')?'bakeSource':url.endsWith('/baker.js')?'bakeLayout':url.endsWith('/lightmap_material.js')?'loadAtlas':url.endsWith('/atlas.js')?'buildAtlas':url.endsWith('/atlas_transport.js')?'atlasJob':'bakeLights';
    const async=name==='loadAtlas'?'async ':'';
    source=source.replace('export '+async+'function '+name+'(',async+'function '+name+'Impl(')+
      '\nexport '+async+'function '+name+'(...args){if(globalThis.__calls)globalThis.__calls["'+name+'"]++;const t=performance.now();try{return '+name+'Impl(...args);}finally{if(globalThis.__cost!=null&&"'+name+'"==="bakeLights")globalThis.__cost+=performance.now()-t;}}';
    if(name==='bakeLights')source=source.replace('function editorFreshness(m) {','function editorFreshnessImpl(m) {').replace('async function loadPages() {',
      'function editorFreshness(m){const t=performance.now();try{return editorFreshnessImpl(m);}finally{if(globalThis.__cost!=null)globalThis.__cost+=performance.now()-t;}}\n  async function loadPages() {');
    return {...loaded,format:'module',source};
  }
  if (url.endsWith('/twin_generator.js')) {""").replace(
    "const t=performance.now();const result=buildTwinImpl(...args);",
    "if(globalThis.__calls)globalThis.__calls.buildTwin++;const t=performance.now();const result=buildTwinImpl(...args);")

DRIVER=PREFIX+r"""
const {bakeLights}=await import(file('static/twin/bake/runtime.js'));
const {cheapSignatures}=await import(file('static/twin/bake/freshness.js'));
const {keyInputs}=await import(file('static/twin/bake/key_inputs.js'));
const {realtimeReason}=await import(file('static/twin/bake/baker.js'));
const kit=structuredClone(input.kit),plan=structuredClone(input.plan),layout={room:{density:1,page:256,gutter:2}};
const live={markers:plan.buildings.flatMap(b=>(b.rooms||[]).map((r,i)=>({device_id:b.id+':'+r.id,kind:'light',placed:true,building:b.id,level:r.level,room:r.id,
 at:[r.polygon.reduce((n,p)=>n+p[0],0)/r.polygon.length,r.polygon.reduce((n,p)=>n+p[1],0)/r.polygon.length,6]})))};
const viewer=await mountTwin(host(false),{plan:structuredClone(plan),kit,tier:'high',bake:false});
const atlas=buildAtlas(viewer.scene.children.find(isBakeRoot),viewer.plan,layout);
const lights=bakeLights(live,viewer.scene.children.find(isBakeRoot),plan),packed=bakeLayout(atlas,layout,lights);
const cheap=cheapSignatures(lights,packed.ownership,packed.entries),digest='"'+'a'.repeat(64)+'"';
const manifest={round:42,complete:true,keyInputs:keyInputs(viewer),pages:packed.pages,ownership:packed.ownership,
 lights:Object.fromEntries(Object.entries(packed.entries).map(([id,e])=>[id,{...e,cheap:cheap[id]}])),
 realtime:Object.fromEntries(lights.filter(l=>!packed.entries[l.device]).map(l=>[l.device,{cheap:cheap[l.device],reason:realtimeReason(packed,l.device)}])),
 pageIntegrity:Object.fromEntries(Array.from({length:packed.pages},(_,p)=>[p,{size:100,digest}]))};
let checks=0,fullPages=0;
const bake={host:new Element(),poll:0,api:async(path,init)=>{
 if(path.endsWith('/lease')){assert.equal(JSON.parse(init.body).action,'check');checks++;return new Response('{"free":true}');}
 if(path==='api/house/live')return new Response(JSON.stringify(live));
 if(path==='api/house/bakes')return new Response(JSON.stringify({key:atlas.key,manifest}));
 if(path.endsWith('.png')){if(init?.headers?.['If-None-Match']!=='*')fullPages++;return new Response(null,{status:304,headers:{'X-Bake-Size':'100','X-Bake-Digest':digest}});}
 throw new Error('Unexpected background request '+path);
}};
const editor=await mountTwin(host(true),{plan,kit,tier:'high',round:42,bake});
try{
 await editor.bake.idle();await editor.bake.refresh();
 await test('same_round_input_stamp_checks_only_compute_cheap_status_under_16ms',async()=>{
  const samples=[];
  for(const field of ['atlas','materials','stage']){
   const saved=manifest.keyInputs[field];manifest.keyInputs[field]='previous-'+saved;
   globalThis.__calls={buildTwin:0,bakeSource:0,bakeLayout:0,loadAtlas:0,buildAtlas:0,atlasJob:0,bakeLights:0};globalThis.__cost=0;
   await editor.bake.refresh();
   const calls={...globalThis.__calls},ms=globalThis.__cost;globalThis.__calls=null;globalThis.__cost=null;
   assert.deepEqual({...calls,bakeLights:0},{buildTwin:0,bakeSource:0,bakeLayout:0,loadAtlas:0,buildAtlas:0,atlasJob:0,bakeLights:0});
   assert.ok(ms<16,'same-round input stamps exceeded 16 ms: '+ms);
   assert.equal(editor.bake.state().stale.length,lights.length);
   assert.equal(editor.bake.packing(),null);assert.equal(editor.bake.held(),null);
   manifest.keyInputs[field]=saved;samples.push({field,ms,calls});
  }
  await editor.bake.refresh();assert.equal(editor.bake.state().stale.length,0);
  console.log('STAMP_COSTS '+JSON.stringify(samples));
 });
 await test('three_committed_household_wall_edits_only_compute_cheap_status_under_16ms',async()=>{
  const samples=[];
  for(let i=0;i<3;i++){
   const next=structuredClone(input.plan);next.buildings[0].walls[0].to[0]+=.01*(i+1);editor.round=43+i;
   globalThis.__calls={buildTwin:0,bakeSource:0,bakeLayout:0,loadAtlas:0,buildAtlas:0,atlasJob:0,bakeLights:0};globalThis.__cost=0;
   const result=await editor.settle(next,{});assert.equal(result.path,'deform');
   await editor.bake.idle();await editor.bake.refresh();
   const calls={...globalThis.__calls},ms=globalThis.__cost;globalThis.__calls=null;globalThis.__cost=null;
   // Mount initialization and one explicit poll may both compute status. The
   // total is a stricter budget than timing only a single signature comparison.
   assert.deepEqual({...calls,bakeLights:0},{buildTwin:0,bakeSource:0,bakeLayout:0,loadAtlas:0,buildAtlas:0,atlasJob:0,bakeLights:0});
   assert.ok(calls.bakeLights>0);assert.ok(ms<16,'cheap freshness exceeded 16 ms: '+ms);
   assert.equal(editor.bake.packing(),null);assert.equal(editor.bake.held(),null);
   assert.equal(bake.host.querySelectorAll('output')[0].textContent,'Lighting out of date since your edits');
   samples.push({ms,calls,lights:lights.length,charts:atlas.room.charts.length,ownershipBytes:JSON.stringify(packed.ownership).length});
  }
  assert.ok(checks>=3);assert.equal(fullPages,0);console.log('CHEAP_COSTS '+JSON.stringify(samples));
 });
}finally{editor.dispose();viewer.dispose();}
finish();
"""
if __name__ == '__main__':
    K.B.household_pool_house()
    plan=K.B.twin_store.current()
    kit=json.loads((K.S.ROOT/'twin_kits/modern_farmhouse.json').read_text(encoding='utf8'));kit['manifest']={}
    code,out=run_node(DRIVER,{'root':K.S.ROOT.as_posix(),'plan':plan,'kit':kit},timeout=480)
    print(out);sys.exit(code or 0)
