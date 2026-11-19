"""Stage chunks, real material patches, mounted scrub and lawn under Node (no GPU)."""
import json
from pathlib import Path
import sys
from test_twin_yard_reuse_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
// The renderer double otherwise omits the real renderer's scene lifecycle.
const draw=Renderer.prototype.render;
Renderer.prototype.render=function(scene,camera){scene.onBeforeRender?.(this,scene,camera);return draw.call(this,scene,camera);};
const {installStageHaze,stageFade}=await import(file('static/twin/sky/stage_haze.js'));
const {mountTimeScrub}=await import(file('static/twin/sky/time_scrub.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {buildYard,yardPartKeys}=await import(file('static/twin/twin_yard.js'));
const {previewDate}=await import(file('static/twin/sky/look.js'));
await test('scrub dates use today in the household zone, including 24h and DST',()=>{
 const site={lon:-75,timezone:'America/New_York'},now=new Date('2026-06-21T17:00:00Z');
 assert.equal(previewDate(now,6+5/60,site).toISOString(),'2026-06-21T10:05:00.000Z');
 assert.equal(previewDate(now,24,site).toISOString(),'2026-06-22T04:00:00.000Z');
 assert.equal(previewDate(new Date('2026-01-21T17:00:00Z'),6+5/60,site).toISOString(),'2026-01-21T11:05:00.000Z');
 assert.equal(previewDate(now,6+5/60,{lon:-75}).toISOString(),'2026-06-21T11:05:00.000Z');
});
await test('world radial haze endpoints, instancing and stable shared uniforms',()=>{
 const scene=new THREE.Scene(),cube=new THREE.CubeTexture(),sky={cube};
 const haze=installStageHaze(scene,sky),fog=scene.fog;
 haze.set({centre:[3,7],radius:10});
 assert.equal(stageFade([3,7],[3,7],10),0);
 assert.equal(stageFade([13,7],[3,7],10),0);
 assert.ok(Math.abs(stageFade([14.75,7],[3,7],10)-.5)<1e-10);
 assert.equal(stageFade([16.5,7],[3,7],10),1);
 assert.equal(stageFade([30,7],[3,7],10),1);
 const material=new THREE.MeshStandardMaterial(),mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(),material,1);
 scene.add(mesh);let previous=0;material.onBeforeCompile=s=>{previous++;s.uniforms.oldPatch={value:3};};
 haze.prepare();const key=material.customProgramCacheKey(),version=material.version;
 const shader={vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader,uniforms:{}};
 material.onBeforeCompile(shader);assert.equal(previous,1);assert.equal(shader.uniforms.oldPatch.value,3);
 assert.equal(shader.uniforms.stageRing.value.length,40);assert.ok(!('stageSky' in shader.uniforms),'no sky sampler');
 const radius=shader.uniforms.stageRadius,centre=shader.uniforms.stageCentre;
 for(const r of [30,120,1000]) {haze.set({centre:[r,7],radius:r});haze.prepare();assert.equal(scene.fog,fog);assert.equal(material.customProgramCacheKey(),key);assert.equal(material.version,version);assert.equal(radius.value,r);assert.deepEqual(centre.value.toArray(),[r,7]);}
 const chunk=THREE.ShaderChunk.fog_vertex;
 assert.ok(chunk.includes('transformed')&&chunk.includes('instanceMatrix')&&chunk.includes('batchingMatrix')&&chunk.includes('modelMatrix'));
 assert.ok(THREE.ShaderChunk.fog_fragment.includes('stageSkyColour( stageRay )'));
 // A sampler here cost every lit material a texture unit past ANGLE's 16 (owner's console, 2026-11-18).
 assert.ok(!/\bsampler(2D|3D|Cube)\b/.test(THREE.ShaderChunk.fog_pars_fragment+THREE.ShaderChunk.fog_fragment),'haze uses no texture unit');
 assert.ok(THREE.ShaderChunk.fog_fragment.includes('linearToOutputTexel')&&THREE.ShaderChunk.fog_fragment.includes('stageToneMapping'));
 const overlay=new THREE.MeshBasicMaterial({fog:false});scene.add(new THREE.Mesh(new THREE.BoxGeometry(),overlay));
 const original=overlay.onBeforeCompile;haze.prepare();assert.equal(overlay.onBeforeCompile,original);
 const other=new THREE.Scene(),otherCube=new THREE.CubeTexture(),otherHaze=installStageHaze(other,{cube:otherCube});
 const otherMat=new THREE.MeshStandardMaterial();other.add(new THREE.Mesh(new THREE.BoxGeometry(),otherMat));otherHaze.prepare();
 const s={uniforms:{}};otherMat.onBeforeCompile(s);assert.notEqual(s.uniforms.stageRing,shader.uniforms.stageRing,'each scene binds its own ring');
 otherHaze.dispose();haze.dispose();mesh.geometry.dispose();material.dispose();overlay.dispose();otherMat.dispose();
});
await test('every mounted house material keeps its patches and one r187 key across radii',async()=>{
 registerHooks({load(url,ctx,next){if(url.endsWith('three.module.js?stage-keys'))return {format:'module',shortCircuit:true,source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms};'};return next(url,ctx);}});
 const {WebGLPrograms}=await import(file('static/vendor/three-r187/three.module.js')+'?stage-keys');
 const plan=structuredClone(input.plan);plan.site||={};plan.site.lot=[[-30,-30],[100,-30],[100,100],[-30,100]];
 const view=await mountTwin(new Element(),{plan,kit:{materials:{}},tier:'high',bake:false,stage:{centre:[19,-11],radius:200,radius_override:200}});
 try {
  const renderer=view.renderer3;renderer.state={buffers:{depth:{getReversed:()=>false}}};
  const cache=WebGLPrograms(renderer,{get:t=>t},{has:()=>false},{precision:'highp',getMaxPrecision:()=> 'highp'},{},{numPlanes:0,numIntersection:0});
  const lights=Object.fromEntries(['sun','directional','point','spot','spotLightMap','rectArea','hemi','sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'].map(k=>[k,[]]));lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;
  view.setTime('day');view.setView(view.levelKeys()[0]);view.render();
  let markers=0;view.scene.traverse(o=>{if(o.isSprite){markers++;assert.equal(o.material.fog,false,'screen-space navigation markers are unhazed');}});assert.ok(markers>0);
  const rows=[];view.scene.traverse(o=>{for(const m of [].concat(o.material||[]))if(m.fog&&!m.isShaderMaterial){const id=m.isMeshPhysicalMaterial?'physical':m.isMeshStandardMaterial?'standard':m.isMeshMatcapMaterial?'matcap':'basic';const lib=THREE.ShaderLib[id];if(!lib)continue;const s={uniforms:THREE.UniformsUtils.clone(lib.uniforms),vertexShader:lib.vertexShader,fragmentShader:lib.fragmentShader};m.onBeforeCompile(s,renderer);assert.equal(s.uniforms.stageRing.value.length,40,m.name);assert.ok(s.vertexShader.includes('#include <fog_vertex>'),m.name);assert.ok(s.fragmentShader.includes('#include <fog_fragment>'),m.name);rows.push([o,m,cache.getProgramCacheKey(cache.getParameters(m,lights,[],view.scene,o,[]))]);}});
  assert.ok(rows.length>10,'real built house and yard material paths execute');
  for(const radius of [30,120,1000]){await view.setStage({centre:[19,-11],radius,radius_override:radius});view.render();for(const[o,m,key]of rows)assert.equal(cache.getProgramCacheKey(cache.getParameters(m,lights,[],view.scene,o,[])),key,m.name);}
  assert.ok(view.scene.fog,'fog stays mounted');
 }finally{view.dispose();}
});
await test('scrub inputs move the sky and lights, release warms once, expires at 120s',async()=>{
 let idle;const timeout=globalThis.setTimeout,clear=globalThis.clearTimeout;
 globalThis.setTimeout=(fn,ms)=>ms===120000?(idle=fn,76543):timeout(fn,ms);globalThis.clearTimeout=id=>id===76543?undefined:clear(id);
 const view=await mountTwin(new Element(),{plan:input.plan,kit:{materials:{}},tier:'low',bake:false,site:{lat:40,lon:-75,timezone:'America/New_York'}}),slider=new Element('input');
 const scrub=mountTimeScrub(view,slider);let warms=0;view.onTimeLook=()=>warms++;
 try{
  view.setClock('2026-06-21T17:00:00Z');warms=0;
  const sun=view.scene.getObjectByName('real-sun'),fog=view.scene.fog,cube=view.scene.background,env=view.scene.environment;
  sun.shadow.needsUpdate=false;
  for(const h of [12,18,23]){slider.value=String(h);await fire(slider,'input');assert.equal(view.state.time,'scrub');assert.equal(view.state.previewHour,h);assert.equal(warms,0);assert.equal(sun.shadow.needsUpdate,false);}
  assert.equal(sun.intensity,0,'23h moves the actual lights to night');assert.equal(view.scene.background,cube);assert.equal(view.scene.environment,env);assert.equal(view.scene.fog,fog);
  await fire(slider,'change');assert.equal(warms,1);assert.equal(sun.shadow.needsUpdate,true);
  idle();assert.equal(view.state.time,'now');assert.equal(warms,2);
  slider.value='6.083333333333333';await fire(slider,'input');assert.ok(sun.intensity>0,'today at 06:05 EDT is after sunrise');
  await fire(slider,'change');view.setTime('day');assert.equal(view.state.previewHour,null);
  view.scrubTime(23,{commit:true});const saved=view.saveView();
  view.setTime('now');view.restoreView(saved);view.setTime(saved.state.time);
  assert.equal(view.state.time,'scrub');assert.equal(view.state.previewHour,23);
  assert.equal(sun.intensity,0,'idle wake restores both the saved scrub hour and its actual lights');
 }finally{scrub.stop();view.dispose();globalThis.setTimeout=timeout;globalThis.clearTimeout=clear;}
});
await test('lawn continuation is a disc to 1.4R; changing radius rebuilds only terrain',async()=>{
 const plan={buildings:[],materials:{},site:{lot:[[-10,-10],[10,-10],[10,10],[-10,10]],planting:[],furniture:[]}};
 const a={centre:[3,-7],radius:120},b={centre:[3,-7],radius:200};
 const first=yardPartKeys(plan,{},'low',{stage:a}),second=yardPartKeys(plan,{},'low',{stage:b});
 assert.deepEqual(Object.keys(first).filter(k=>first[k]!==second[k]),['terrain']);
 for(const stage of [a,b,{centre:[3,-7],radius:30}]){
  const yard=(await buildYard(plan,{materials:{}},'low',{stage})).group;let farthest=0;
  yard.traverse(o=>{let part=o;while(part&&part.userData.yardPart!=='terrain')part=part.parent;if(!part||!o.geometry)return;const p=o.geometry.attributes.position;for(let i=0;i<p.count;i++)farthest=Math.max(farthest,Math.hypot(p.getX(i)-stage.centre[0],p.getZ(i)-stage.centre[1]));});
  assert.ok(Math.abs(farthest-stage.radius*1.4)<.001,`disc extent ${farthest} wanted ${stage.radius*1.4}`);
 }
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
