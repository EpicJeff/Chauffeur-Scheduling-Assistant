"""Model variants use the actual mode pool warm-up, off the switch handler."""
import sys
from twin_live_node_rig import run
DRIVER = r"""
const {createModelWarmup}=await import(file('static/twin/bake/model_warmup.js'));
const t=await rig({devices:[{device_id:'lamp',name:'Lamp',kind:'light',entity_id:'light.a',state:'on',attributes:{brightness:255}}]});
let models;
try{
 t.live.stop();t.view.tier='high';
 const queue=[],ready=new WeakSet();let clicking=false;
 t.view.renderer3.compileAsync=(root,camera,scene)=>{
  assert.equal(clicking,false,'no compilation in click handler');
  if(root===t.view.scene)return Promise.resolve(); // existing surface warmer
  assert.equal(scene,t.view.scene);assert.equal(camera,t.view.camera);
  const mats=[];root.traverse(o=>{if(o.material)mats.push(...[].concat(o.material));});
  const pool=[];scene.traverseVisible(o=>{if(o.isPointLight)pool.push(o);});
  return new Promise(resolve=>queue.push({mats,points:pool.length,resolve(){mats.forEach(m=>ready.add(m));resolve();}}));
 };
 t.live=await liveModule.mountLive(t.view,{api:t.api});
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial()),original=mesh.material;
 t.view.scene.add(mesh);t.view.scene.updateMatrixWorld(true);
 const shared={mvBricks:{value:null},mvLamps:{value:null},mvSize:{value:new THREE.Vector4()}};
 models=createModelWarmup(t.view,shared);t.view.bake={models,fresh:()=>[],light(){}};models.prepare(mesh);models.setEnabled(true);
 t.live.setModes([]);const work=models.queue();
 for(let i=0;i<100&&queue.length<2;i++)await wait(1);
 assert.equal(queue.length,2);assert.deepEqual(queue.map(q=>q.points).sort((a,b)=>a-b),[0,16],'same actual pool-off/on counts as surface warmer');
 assert.equal(mesh.material,original);queue[0].resolve();await wait(1);assert.equal(mesh.material,original);
 queue[1].resolve();await work;assert.notEqual(mesh.material,original);
 const before=queue.length;clicking=true;try{await press(document.querySelector('[data-mode="lights"]'));}finally{clicking=false;}
 assert.equal(queue.length,before,'mode switch requests no new model compile');assert.ok(ready.has(mesh.material));
 const installed=mesh.material;
 await t.view.onTimeLook();assert.equal(mesh.material,installed,'time-look leaves ready models installed');
 assert.equal(queue.length,before,'unchanged time-look adds no model round');
 console.log('Passed: test_model_variants_in_real_modes_warm_and_no_click_compile');
}finally{models?.stop();t.cleanup();}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);

// Held-program rig: compileAsync deliberately acknowledges ONLY the front pass
// of transparent DoubleSide materials, just like vendored r187. The detector
// checks the shader/state being DRAWN, including each side, across instances.
function harness({programPolling=false}={}){
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(60,1,.01,100),host=new EventTarget();
 camera.position.set(0,0,5);camera.lookAt(0,0,0);
 const pool=new THREE.PointLight();pool.visible=false;scene.add(pool);
 const gates=[],ready=new Set(),owned=new Set(),disposals=new Map(),liveProgramMaterials=new Set();let rounds=0,walks=0,frames=0,checks=0;
 const updateCamera=camera.updateMatrixWorld.bind(camera);camera.updateMatrixWorld=(...args)=>{checks++;return updateCamera(...args);};
 const traverse=scene.traverseVisible.bind(scene);scene.traverseVisible=fn=>{walks++;traverse(fn);};
 const geometryKey=o=>[!!o.geometry.attributes.normal,!!o.geometry.attributes.tangent].join('|');
 const key=(m,state,side,geometry)=>`${m.customProgramCacheKey()}|${state}|${side}|${!!m.transparent}|${!!m.map}|${geometry}`;
 const view={scene,camera,controls:new THREE.EventDispatcher(),renderer3:{domElement:{parentElement:host}},
  live:{warm(compile){rounds++;const was=pool.visible;pool.visible=true;try{return compile();}finally{pool.visible=was;}}},
  render(){frames++;traverse(o=>{for(const m of o.material?[].concat(o.material):[])if(m.customProgramCacheKey().includes('|mv-1')){
   const sides=m.transparent&&m.side===THREE.DoubleSide&&!m.forceSinglePass?[THREE.BackSide,THREE.FrontSide]:[m.side];
   for(const side of sides)assert.ok(ready.has(key(m,pool.visible,side,geometryKey(o))),'frame stall: program missing for drawn light state/side/geometry');
  }});}};
 const properties=new WeakMap();let polls=0;
 if(programPolling)view.renderer3.properties={get(m){if(!properties.has(m))properties.set(m,{programs:new Map()});return properties.get(m);}};
 view.renderer3.compileAsync=(root,eye,target)=>{
  assert.notEqual(root,scene);assert.equal(eye,camera);assert.equal(target,scene);
  const entries=[];root.traverse(o=>{if(o.material)for(const m of [].concat(o.material))entries.push({m,geometry:geometryKey(o)});});
  const mats=entries.map(e=>e.m);for(const m of mats)if(!owned.has(m)){
   owned.add(m);disposals.set(m,0);m.addEventListener('dispose',()=>disposals.set(m,disposals.get(m)+1));
  }const state=pool.visible;
  for(const e of entries){
   e.key=key(e.m,state,e.m.transparent&&e.m.side===THREE.DoubleSide&&!e.m.forceSinglePass?THREE.FrontSide:e.m.side,e.geometry);
   if(programPolling){const p=view.renderer3.properties.get(e.m);
    if(!p.listening){p.listening=true;liveProgramMaterials.add(e.m);e.m.addEventListener('dispose',()=>{
     for(const program of p.programs.values())program.program=undefined;
     p.programs.clear();delete p.currentProgram;properties.delete(e.m);liveProgramMaterials.delete(e.m);
    });}
    if(!p.programs.has(e.key))p.programs.set(e.key,{program:{},cacheKey:e.key,done:false,isReady(){polls++;return this.done;}});
    e.program=p.programs.get(e.key);p.currentProgram=e.program;
   }
  }
  function release(e){ready.add(e.key);if(e.program)e.program.done=true;}
  return new Promise((resolve,reject)=>gates.push({mats,entries,state,settled:false,reject,
   resolve(){this.settled=true;entries.forEach(release);resolve();},
   resolveCurrent(){this.settled=true;assert.ok(programPolling);for(const e of entries)if(view.renderer3.properties.get(e.m).currentProgram===e.program)release(e);resolve();}}));
 };
 const models=createModelWarmup(view,{mvBricks:{value:null},mvLamps:{value:null},mvSize:{value:new THREE.Vector4()}});
 models.setEnabled(true);
 function add(material=new THREE.MeshStandardMaterial()){
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(.2,.2,.2),material);scene.add(mesh);scene.updateMatrixWorld(true);models.prepare(mesh);return mesh;
 }
 return {scene,camera,host,pool,view,gates,owned,disposals,liveProgramMaterials,models,add,rounds:()=>rounds,walks:()=>walks,frames:()=>frames,checks:()=>checks,polls:()=>polls};
}
async function until(test){for(let i=0;i<500&&!test();i++)await wait(1);assert.ok(test(),'held compile did not start');}
async function finish(h,work,count){await until(()=>h.gates.length===count);h.gates.filter(g=>!g.settled).forEach(g=>g.resolve());await work;await wait(1);}

{
 const h=harness(),mesh=h.add(),original=mesh.material;
 await finish(h,h.models.queue(),2);const installed=mesh.material,rounds=h.rounds(),walks=h.walks();
 mesh.position.x=100;h.scene.updateMatrixWorld(true);h.host.dispatchEvent(new Event('twinviewchange'));await h.models.queue();
 mesh.position.x=0;h.scene.updateMatrixWorld(true);h.view.controls.dispatchEvent({type:'change'});await h.models.queue();await wait(300);
 assert.equal(mesh.material,installed);assert.equal(h.rounds(),rounds);assert.equal(h.gates.length,2);assert.equal(h.walks(),walks,'ready orbit has no scene walks');
 for(let i=0;i<60;i++){await h.models.warm();assert.equal(mesh.material,installed);h.view.render();}
 assert.equal(h.rounds(),rounds);assert.equal(h.owned.size,2,'unchanged clock ticks create no clones');
 h.models.stop();assert.equal(mesh.material,original);
 console.log('Passed: test_ready_orbit_and_60_clock_ticks_keep_clones_without_rounds');
}
{
 const h=harness(),a=h.add(),b=h.add(new THREE.MeshStandardMaterial({color:'red'})),original=a.material;
 await finish(h,h.models.queue(),2);const old=a.material,other=b.material;
 original.map=new THREE.Texture();original.needsUpdate=true;original.dispatchEvent({type:'materialparamschange'});
 await until(()=>h.gates.length===4);assert.equal(a.material,old);assert.equal(b.material,other);h.view.render();
 assert.ok(h.gates.slice(2).every(g=>g.mats.length===1),'only changed material re-cloned');
 await finish(h,h.models.queue(),4);assert.notEqual(a.material,old);assert.equal(b.material,other);
 const late=h.add(new THREE.MeshStandardMaterial({color:'blue'})),before=h.owned.size;
 await finish(h,h.models.queue(),6);assert.ok(h.gates.slice(4).every(g=>g.mats.length===1),'late yard/model compiles new bindings only');
 assert.equal(h.owned.size-before,2);assert.equal(b.material,other);assert.notEqual(late.material.customProgramCacheKey().indexOf('|mv-1'),-1);
 h.models.stop();console.log('Passed: test_local_material_change_and_late_load_are_incremental');
}
{
 const h=harness(),source=new THREE.MeshStandardMaterial();source.userData.ready=Promise.resolve();
 const a=h.add(source),b=h.add(source);await finish(h,h.models.queue(),2);
 assert.equal(a.material,b.material,'one shared material per variant, not per mesh');assert.equal(h.owned.size,2);
 const installed=a.material,rounds=h.rounds();h.pool.visible=true;const late=h.add(source);const work=h.models.queue();await work;
 assert.equal(h.gates.length,2);assert.equal(h.rounds(),rounds,'already-resolved ready promise / shared late binding needs no round');
 assert.equal(a.material,installed);assert.equal(late.material,installed,'active clone shared even when late copy arrives in another light state');h.models.stop();console.log('Passed: test_shared_material_and_settled_ready_promise_do_not_rebuild');
}
{
 const h=harness(),source=new THREE.MeshStandardMaterial(),original=[source,source],mesh=h.add(original);
 await finish(h,h.models.queue(),2);assert.equal(mesh.material[0],mesh.material[1]);assert.equal(h.owned.size,2);
 let disposed=0;for(const m of h.owned)m.addEventListener('dispose',()=>disposed++);
 h.models.stop();assert.equal(mesh.material,original);assert.equal(disposed,2);
 console.log('Passed: test_repeated_material_array_slots_share_clones_and_release_once');
}
{
 const h=harness(),mesh=h.add(new THREE.MeshStandardMaterial({transparent:true,side:THREE.DoubleSide})),original=mesh.material;
 const work=h.models.queue();await until(()=>h.gates.length===4);
 h.gates.filter(g=>g.mats[0].side===THREE.DoubleSide).forEach(g=>g.resolve());await wait(1);
 assert.equal(mesh.material,original,'front program alone cannot swap');
 const backs=h.gates.filter(g=>g.mats[0].side===THREE.BackSide);assert.equal(backs.length,2);
 backs[0].resolve();await wait(1);assert.equal(mesh.material,original,'pool back pass still pending');
 backs[1].resolve();await work;assert.notEqual(mesh.material,original);h.view.render();h.pool.visible=true;h.view.render();
 h.models.stop();console.log('Passed: test_transparent_double_side_waits_for_both_programs_in_each_state');
}
{
 const h=harness(),mesh=h.add(),original=mesh.material,work=h.models.queue();await until(()=>h.gates.length===2);
 let disposed=0;for(const m of h.owned)m.addEventListener('dispose',()=>disposed++);
 h.models.stop();await work;assert.equal(disposed,0);assert.equal(mesh.material,original);
 h.gates[0].resolve();await wait(1);assert.equal(disposed,0);
 h.gates[1].resolve();await wait(1);assert.equal(disposed,h.owned.size);assert.equal(mesh.material,original);
 await wait(1);assert.equal(disposed,h.owned.size,'exactly once');
 console.log('Passed: test_cancelled_linking_clones_dispose_only_after_all_settle');
}
for(const action of ['disable','supersede-hidden']){
 const h=harness(),mesh=h.add(),source=mesh.material,work=h.models.queue();await until(()=>h.gates.length===2);
 let disposed=0;for(const m of h.owned)m.addEventListener('dispose',()=>disposed++);
 if(action==='disable')h.models.setEnabled(false);
 else {source.needsUpdate=true;source.dispatchEvent({type:'materialparamschange'});mesh.visible=false;}
 assert.equal(disposed,0);h.gates.forEach(g=>g.resolve());await work;await wait(10);
 assert.equal(disposed,2,'cancelled/superseded programs released as soon as linking settles');assert.equal(mesh.material,source);
 assert.equal(h.gates.length,2,'hidden replacement never compiles');h.models.stop();
 console.log('Passed: test_linking_lifetime_'+action);
}
{
 const h=harness(),mesh=h.add(),original=mesh.material,work=h.models.queue();await until(()=>h.gates.length===2);
 let disposed=0;for(const m of h.owned)m.addEventListener('dispose',()=>disposed++);
 mesh.visible=false;h.models.retain(new Set());assert.equal(disposed,0);
 h.gates.forEach(g=>g.resolve());await work;assert.equal(disposed,h.owned.size,'cancelled hidden/removed clones released promptly');assert.equal(mesh.material,original);
 h.models.stop();console.log('Passed: test_yard_removal_releases_pending_hidden_clones_after_settle');
}
{
 const h=harness(),mesh=h.add(),original=mesh.material,work=h.models.queue();await until(()=>h.gates.length===2);
 h.scene.add(new THREE.SpotLight());h.gates.forEach(g=>g.resolve());await work;
 assert.equal(mesh.material,original,'current light key was not compiled: no stale swap');
 await until(()=>h.gates.length===4);await finish(h,h.models.queue(),4);h.view.render();assert.notEqual(mesh.material,original);
 h.models.stop();console.log('Passed: test_changed_light_state_before_swap_requests_missing_variants');
}
{
 const h=harness();h.add();await finish(h,h.models.queue(),2);
 const gate=new THREE.Group();gate.visible=false;h.scene.add(gate);
 const mesh=h.add(new THREE.MeshStandardMaterial({color:'green'}));gate.add(mesh);
 const before=h.gates.length,rounds=h.rounds();
 for(let i=0;i<20;i++)h.view.controls.dispatchEvent({type:'change'});
 await wait(300);assert.equal(h.gates.length,before);assert.equal(h.rounds(),rounds);
 const walks=h.walks(),checks=h.checks();await wait(650);assert.equal(h.walks(),walks,'no 600ms visibility polling tail');assert.equal(h.checks(),checks,'no repeated empty eligibility rounds');
 gate.visible=true;h.host.dispatchEvent(new Event('twinviewchange'));await until(()=>h.gates.length===4);await finish(h,h.models.queue(),4);
 h.models.stop();console.log('Passed: test_gesture_checks_are_coalesced_without_polling_tail');
}
{
 const h=harness(),a=h.add(),b=h.add(new THREE.MeshStandardMaterial({color:'red'})),original=b.material;
 b.position.set(15,0,0);h.scene.updateMatrixWorld(true);
 const work=h.models.queue();await until(()=>h.gates.length===2);
 h.camera.lookAt(b.position);h.camera.updateMatrixWorld();
 for(let i=0;i<5;i++)h.view.controls.dispatchEvent({type:'change'});
 // Let the throttled check fire while compile is held, so there is no pending
 // camera event or polling tail to rescue the second mesh after settlement.
 await wait(300);h.gates.forEach(g=>g.resolve());await work;
 await until(()=>h.gates.length===4);await finish(h,h.models.queue(),4);
 assert.notEqual(b.material,original,'current frustum rechecked without a further event');
 assert.ok(a.material.customProgramCacheKey().includes('|mv-1'));h.models.stop();
 console.log('Passed: test_camera_move_during_compile_is_rechecked_after_settle');
}
for(const transparent of [false,true]){
 const h=harness({programPolling:true}),source=new THREE.MeshStandardMaterial({normalMap:new THREE.Texture(),transparent,side:transparent?THREE.DoubleSide:THREE.FrontSide});
 const a=h.add(source),b=h.add(source);
 b.geometry.setAttribute('tangent',new THREE.Float32BufferAttribute(new Float32Array(b.geometry.attributes.position.count*4),4));h.models.prepare(b);
 const work=h.models.queue(),count=transparent?4:2;await until(()=>h.gates.length===count);
 for(const g of h.gates){assert.equal(g.entries.length,2,'one stand-in for each geometry signature');assert.equal(new Set(g.mats).size,1,'geometry variants share the material clone');g.resolveCurrent();}
 await wait(30);assert.equal(a.material,source);assert.equal(b.material,source,'last currentProgram being ready is insufficient');assert.ok(h.polls()>0);
 for(const g of h.gates)g.resolve();await work;assert.equal(a.material,b.material);assert.notEqual(a.material,source);
 assert.equal(h.owned.size,transparent?4:2,'no per-geometry material clones');h.view.render();h.pool.visible=true;h.view.render();
 h.models.stop();console.log('Passed: test_all_shared_geometry_programs_wait_before_swap_'+transparent);
}
{
 const h=harness({programPolling:true}),source=new THREE.MeshStandardMaterial({normalMap:new THREE.Texture()}),a=h.add(source);
 await finish(h,h.models.queue(),2);const installed=a.material,b=h.add(source);
 b.geometry.setAttribute('tangent',new THREE.Float32BufferAttribute(new Float32Array(b.geometry.attributes.position.count*4),4));h.models.prepare(b);
 const work=h.models.queue();await until(()=>h.gates.length===4);assert.equal(a.material,installed);assert.equal(b.material,source);h.view.render();
 assert.ok(h.gates.slice(2).every(g=>g.entries.length===1&&g.entries[0].geometry.endsWith('|true')),'late geometry warms only its missing signature');
 await finish(h,work,4);assert.equal(b.material,installed);assert.equal(h.owned.size,2);h.view.render();
 h.models.stop();console.log('Passed: test_late_shared_geometry_warms_missing_programs_without_recloning');
}
{
 const h=harness({programPolling:true}),source=new THREE.MeshStandardMaterial({normalMap:new THREE.Texture()}),a=h.add(source),b=h.add(source);
 b.geometry.setAttribute('tangent',new THREE.Float32BufferAttribute(new Float32Array(b.geometry.attributes.position.count*4),4));h.models.prepare(b);
 const work=h.models.queue();await until(()=>h.gates.length===2);h.gates.forEach(g=>g.resolveCurrent());await wait(20);
 let disposed=0;for(const m of h.owned)m.addEventListener('dispose',()=>disposed++);
 h.models.stop();await work;assert.equal(disposed,0,'stop also waits for non-current geometry programs');
 h.gates.forEach(g=>g.resolve());await wait(20);assert.equal(disposed,2);assert.equal(a.material,source);assert.equal(b.material,source);
 console.log('Passed: test_stop_waits_for_every_shared_geometry_program');
}
// These cases are based on reviewer probe_warmup3.py P3/P4/P5. Keep the
// compileAsync gate as the readiness floor even when program internals vanish.
{
 const h=harness(),A=new THREE.MeshStandardMaterial({color:'red'}),B=new THREE.MeshStandardMaterial({color:'blue'}),X=new THREE.MeshStandardMaterial({color:'green'});
 const mesh=h.add([A,B]);mesh.geometry.clearGroups();mesh.geometry.addGroup(0,18,0);mesh.geometry.addGroup(18,18,1);
 await finish(h,h.models.queue(),2);const [cA]=mesh.material;
 mesh.material=[cA,X];h.models.prepare(mesh);
 assert.equal(mesh.material[0],A);assert.equal(mesh.material[1],X);assert.equal(h.disposals.get(cA),1);
 cA.clone=()=>{throw Error('must not clone the disposed, stale array slot');};
 await finish(h,h.models.queue(),4);assert.ok(mesh.material.every(m=>m.customProgramCacheKey().includes('|mv-1')));
 assert.ok(mesh.material.every(m=>!h.disposals.get(m)));h.models.stop();
 assert.equal(mesh.material[0],A);assert.equal(mesh.material[1],X);
 console.log('Passed: test_partial_material_replacement_rebinds_live_slots');
}
{
 const h=harness(),mesh=h.add(),original=mesh.material,program={program:{}};
 const programs=new Map([['k',program]]);h.view.renderer3.properties={get:()=>({programs})};
 const warn=console.warn;let warnings=0;console.warn=()=>warnings++;
 try{
  const work=h.models.queue();await until(()=>h.gates.length===2);await wait(20);
  assert.equal(mesh.material,original,'compileAsync still owns readiness when isReady is absent');
  h.gates.forEach(g=>g.resolve());let settled=false;work.then(()=>settled=true);await until(()=>settled);
  assert.notEqual(mesh.material,original);assert.equal(warnings,0);h.view.render();
 }finally{console.warn=warn;h.models.stop();}
 console.log('Passed: test_program_without_isReady_falls_back_to_compileAsync');
}
for(const termination of ['destroyed','nonboolean','unheld']){
 const h=harness(),mesh=h.add(),original=mesh.material;let calls=0;
 const program={program:{},isReady(){calls++;return false;}},programs=new Map([['k',program]]);
 h.view.renderer3.properties={get:()=>({programs})};
 const work=h.models.queue();await until(()=>h.gates.length===2);h.gates.forEach(g=>g.resolve());
 await wait(20);assert.equal(mesh.material,original);assert.ok(calls>0,'actually held by the polled program');
 if(termination==='destroyed')program.program=undefined;
 else if(termination==='nonboolean')program.isReady=()=>null;
 else programs.delete('k');
 let settled=false;work.then(()=>settled=true);await until(()=>settled);assert.notEqual(mesh.material,original);
 const after=calls;await wait(30);assert.equal(calls,after,'completed readiness poll leaves no timer');h.models.stop();
 console.log('Passed: test_program_readiness_settles_when_'+termination);
}
for(const action of ['stop','disable']){
 const h=harness({programPolling:true});h.add();const work=h.models.queue();await until(()=>h.gates.length===2);await wait(20);
 if(action==='stop')h.models.stop();else h.models.setEnabled(false);
 await work;const calls=h.polls();await wait(30);assert.equal(h.polls(),calls,'cancelled round stops readiness polling');
 assert.ok([...h.disposals.values()].every(n=>n===0),'pending compileAsync still protects linking clones');
 h.gates.forEach(g=>g.resolve());await until(()=>h.liveProgramMaterials.size===0);
 assert.ok([...h.disposals.values()].every(n=>n===1));h.models.stop();
 console.log('Passed: test_cancelled_readiness_poll_stops_'+action);
}
{
 const h=harness({programPolling:true}),source=new THREE.MeshStandardMaterial({normalMap:new THREE.Texture()}),a=h.add(source);
 await finish(h,h.models.queue(),2);const old=[...h.owned],installed=a.material,b=h.add(source);
 b.geometry.setAttribute('tangent',new THREE.Float32BufferAttribute(new Float32Array(b.geometry.attributes.position.count*4),4));h.models.prepare(b);
 const abandoned=h.models.queue();await until(()=>h.gates.length===4);installed.dispose();
 let settled=false;abandoned.then(()=>settled=true);await until(()=>settled);
 assert.equal(a.material,source);assert.equal(b.material,source,'externally disposed clones cannot swap or remain installed');
 const next=h.models.queue();await until(()=>h.gates.length===6);
 assert.ok(h.gates.slice(4).every(g=>g.mats.every(m=>!old.includes(m))),'next queue uses fresh clone records');
 // The retired round cannot block this fresh round, even while its upstream
 // compileAsync promises remain held. They still protect its live references.
 h.gates.slice(2,4).forEach(g=>g.resolve());await until(()=>old.every(m=>h.disposals.get(m)===1));
 h.gates.slice(4).forEach(g=>g.resolve());await next;assert.notEqual(a.material,source);assert.equal(a.material,b.material);
 h.models.stop();await until(()=>h.liveProgramMaterials.size===0);
 assert.ok([...h.disposals.values()].every(n=>n===1),'no leaked or double-disposed clone records');
 console.log('Passed: test_disposed_clone_mid_link_settles_and_next_round_is_fresh');
}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);process.exit(0);
"""
if __name__=='__main__':sys.exit(run(DRIVER))
