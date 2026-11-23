"""Execute captured probes and real standard-material hooks under Node, no browser."""
import sys
from test_twin_untouched_house_js import COMMON, ROOT, run_node

DRIVER = COMMON.replace('export const WebGLRenderer = globalThis.Renderer;',
                        'export class WebGLRenderer { constructor(...args) { return new globalThis.Renderer(...args); } }') + r"""
const R=await import(file('static/twin/reflection_probes.js'));
const Y=await import(file('static/twin/twin_yard.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createUnlit}=await import(file('static/twin/unlit.js'));
const {patchWindowGlow}=await import(file('static/twin/bake/lightmap_material.js'));
const compile=m=>{const s={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};m.onBeforeCompile(s,{});return s;};
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
class CaptureRenderer extends Renderer {
 constructor(){super();Object.assign(this,{coordinateSystem:THREE.WebGLCoordinateSystem,autoClear:false,xr:{enabled:true},toneMapping:THREE.ACESFilmicToneMapping,
  localClippingEnabled:true,clippingPlanes:[new THREE.Plane()],target:{saved:true},face:3,mip:2,viewport:new THREE.Vector4(1,2,300,200),scissor:new THREE.Vector4(3,4,100,90),scissorTest:true,
  color:new THREE.Color('#112233'),alpha:.3,faces:[],mirrors:[],targets:new Set()});this.shadowMap={enabled:true,autoUpdate:true,needsUpdate:true};this.info.autoReset=true;
  Object.assign(this.info.render,{calls:17,triangles:123,frame:8}); }
 getRenderTarget(){return this.target;} getActiveCubeFace(){return this.face;} getActiveMipmapLevel(){return this.mip;}
 setRenderTarget(t,f=0,m=0){this.target=t;this.face=f;this.mip=m;if(t?.isWebGLCubeRenderTarget)this.targets.add(t);}
 getClearColor(c){return c.copy(this.color);} getClearAlpha(){return this.alpha;}
 setClearColor(c,a){this.color.set(c);this.alpha=a;}
 getViewport(v){return v.copy(this.viewport);} setViewport(v){this.viewport.copy(v);}
 getScissor(v){return v.copy(this.scissor);} setScissor(v){this.scissor.copy(v);}
 getScissorTest(){return this.scissorTest;} setScissorTest(v){this.scissorTest=v;}
 getDrawingBufferSize(v){return v.set(1920,1081);}
 render(s,c){s.updateMatrixWorld(true);
  if(s.name==='twin-atmosphere'||s.isMesh)return; // Sky generation/filtering is not a house probe capture.
  if(this.target?.isWebGLRenderTarget&&!this.target.isWebGLCubeRenderTarget){this.mirrors.push(this.target);this.inspectMirror?.(s,c);this.info.render.calls++;this.info.render.triangles+=100;if(this.failMirror)throw Error('mirror failure');return;}
  if(!this.target?.isWebGLCubeRenderTarget)return;this.inspect?.(s,c);this.faces.push([this.target,this.face]);this.info.render.calls++;this.info.render.triangles+=100;
  if(this.fail)throw Error('capture failure');}
}
const state=r=>({target:r.target,face:r.face,mip:r.mip,auto:r.autoClear,xr:r.xr.enabled,tone:r.toneMapping,local:r.localClippingEnabled,
 clipping:r.clippingPlanes,shadow:{...r.shadowMap},info:{...r.info.render},autoInfo:r.info.autoReset,viewport:r.viewport.toArray(),scissor:r.scissor.toArray(),scissorTest:r.scissorTest,color:r.color.getHex(),alpha:r.alpha});
async function setup(tier='medium',p=fixture()){
 const out=G.buildTwin(p,kit(),tier,{viewing:true});await out.ready;
 const yard=(await Y.buildYard(p,kit(),tier)).group;out.groups.site.add(yard);
 const scene=new THREE.Scene();scene.add(out.root);scene.environment=new THREE.Texture();scene.environmentIntensity=.13;
 const sky=new THREE.CubeTexture();scene.background=sky;scene.backgroundIntensity=.7;
 const renderer=new CaptureRenderer();let time=0;const warnings=[];const extra=[];
 const cut=new THREE.Plane(new THREE.Vector3(0,-1,0),2);
 const uncut=()=>{const v=cut.constant;cut.constant=1e6*.3048;return()=>{cut.constant=v;};};
 const manager=R.createReflectionProbes({scene,renderer,tier,sky:()=>sky,now:()=>time,extras:()=>extra,uncut,warn:e=>warnings.push(e)});
 manager.rebuild(p,out.root);
 return {out,yard,scene,renderer,manager,warnings,extra,p,cut,advance(t){time+=t;},round(){manager.frame();time+=1500;for(let i=0;i<4;i++)manager.frame();}};
}
await test('sets_centres_world_boxes_and_four_probe_cap_keep_largest_of_each_kind',async()=>{
 const p=fixture();p.buildings.push(building('tiny',150),building('huge',220));p.buildings[2].levels[0].outline=square(0,0,2);p.buildings[3].levels[0].outline=square(0,0,90);
 p.site.pool.features.push({id:'large-spa',kind:'spa',polygon:square(0,35,12),mode:'raised'});
 const c=await setup('high',p);const info=c.manager.info();assert.equal(info.probes.length,4);
 assert.ok(info.probes.some(p=>p.id==='exterior:huge'));assert.ok(!info.probes.some(p=>p.id==='exterior:tiny'));
 assert.ok(info.probes.some(p=>p.id==='water:pool'));assert.ok(info.probes.every(p=>p.box.min[1]<=0&&p.box.max[1]>=30));
 const pool=info.probes.find(p=>p.id==='water:pool');near(pool.centre[0],13*.3048);near(pool.centre[2],-41*.3048);
 near(pool.box.min[0],-10*.3048);near(pool.box.max[2],12*.3048);
 const allWater=meshes(c.out).filter(o=>o.material.userData.reflection?.kind==='water');assert.ok(allWater.length);
 const tiny=meshes(c.out).find(o=>o.material.userData.reflection?.owner==='tiny').material.userData.reflection;
 assert.ok(tiny.probe&&tiny.probe.kind==='exterior','discarded building uses nearest kept exterior');c.manager.dispose();
});
await test('low_has_no_targets_shader_or_material_changes',async()=>{
 const c=await setup('low');const before=signature(c.out);c.manager.request();c.round();
 assert.deepEqual(c.manager.info(),{tier:'low',probes:[],pending:false});assert.equal(c.renderer.faces.length,0);assert.deepEqual(signature(c.out),before);
 for(const o of meshes(c.out)){assert.ok(!o.material.userData.reflection);assert.ok(o.material.userData.waterSurface||!o.material.premultipliedAlpha,'only the water surface blends its own mirror share');}
 c.manager.dispose();
});
await test('water_shares_calm_draw_and_selects_own_basin_by_vertex_centre',async()=>{
 const p=fixture();p.buildings=[p.buildings[0]];
 const c=await setup('medium',p);const water=meshes(c.out).filter(o=>o.material.userData.waterSurface);
 assert.equal(new Set(water.map(o=>o.material)).size,1,'calm water still shares one material');
 const centres=new Set(water.flatMap(o=>{const a=o.geometry.attributes.reflectionBodyCentre;assert.ok(a);return Array.from({length:a.count},(_,i)=>[a.getX(i),a.getY(i),a.getZ(i)].join(','));}));
 assert.equal(centres.size,2,'pool and spa carry independent centres through static merge');c.round();
 const u=water[0].material.userData.reflection.uniforms;assert.equal(u.waterProbeCount.value,2);
 for(const centre of centres){const body=new THREE.Vector3(...centre.split(',').map(Number));let selected=0;
  u.waterProbeCentre.value.slice(0,2).forEach((p,i)=>{if(p.distanceToSquared(body)<u.waterProbeCentre.value[selected].distanceToSquared(body))selected=i;});
  near(u.waterProbeCentre.value[selected].distanceTo(body),0);assert.equal(u.waterProbeFresh.value[selected],1);}
 c.manager.dispose();
});
for(const failure of [false,true])await test('capture_restores_hidden_objects_and_renderer_even_on_throw_'+failure,async()=>{
 const c=await setup();const hidden=[new THREE.Sprite(),new THREE.Points(),new THREE.LineSegments(),new THREE.Group(),new THREE.Group()];
 hidden[3].userData.effectFixtures=true;hidden[4].userData.reflectionExclude=true;
 hidden.forEach((o,i)=>{o.visible=i!==1;c.scene.add(o);});const sheet=new THREE.Mesh(new THREE.PlaneGeometry(),new THREE.MeshBasicMaterial());c.scene.add(sheet);c.extra.push(sheet);
 const lamp=new THREE.PointLight();lamp.shadow.autoUpdate=true;lamp.shadow.needsUpdate=true;c.scene.add(lamp);
 const saved=state(c.renderer),savedVis=hidden.map(o=>o.visible),bg=c.scene.background,bi=c.scene.backgroundIntensity;
 c.renderer.fail=failure;c.renderer.inspect=()=>{
  assert.ok(hidden.every(o=>!o.visible));assert.ok(!sheet.visible);
  assert.equal(c.renderer.shadowMap.autoUpdate,false);assert.equal(c.renderer.shadowMap.needsUpdate,false);assert.equal(lamp.shadow.needsUpdate,false);
  assert.equal(c.renderer.xr.enabled,false);assert.equal(c.renderer.toneMapping,THREE.NoToneMapping);
  // Clipping as the picture has it, so no material needs a second program;
  // the cut planes are lifted instead, so the cube holds the whole house.
  assert.equal(c.renderer.localClippingEnabled,saved.local);assert.equal(c.renderer.clippingPlanes,saved.clipping);
  assert.equal(c.cut.constant,1e6*.3048);
  assert.equal(c.scene.background,bg);assert.ok(c.scene.background.isCubeTexture);
  assert.equal(c.scene.backgroundIntensity,bi,'capture uses the drawn sky radiance, not the material fill scale');
  for(const o of meshes(c.out))if(o.material.userData.reflection)
   assert.equal(o.visible,o.material.userData.reflection.kind==='ground','mirrors hidden, ground visible in probe capture');
 };
 c.round();assert.deepEqual(state(c.renderer),saved);assert.deepEqual(hidden.map(o=>o.visible),savedVis);assert.equal(sheet.visible,true);
 assert.equal(c.cut.constant,2,'the cut is back after the capture, even on a throw');
 assert.equal(lamp.shadow.autoUpdate,true);assert.equal(lamp.shadow.needsUpdate,true);assert.equal(c.scene.background,bg);assert.equal(c.scene.backgroundIntensity,bi);
 assert.equal(c.manager.info().probes.every(p=>p.fresh),!failure);
 if(failure){assert.equal(c.warnings.length,4);for(const o of meshes(c.out))if(o.material.userData.reflection)assert.equal(o.material.envMap,null);}
 c.manager.dispose();
});
await test('exterior_capture_hides_exact_building_and_keeps_other_buildings',async()=>{
 const c=await setup();let seen=0;c.renderer.inspect=()=>{
  const cube=c.renderer.target;const probe=c.manager.info().probes[c.renderer.targets.size-1];
  if(probe.kind!=='exterior')return;seen++;
  const owner=probe.id.slice(9);const body=meshes(c.out).filter(o=>o.userData.buildingId===owner&&!o.layers.isEnabled(31));
  assert.ok(body.length);assert.ok(body.every(o=>!visibleTree(o)));
  const other=meshes(c.out).filter(o=>o.userData.buildingId!==owner&&o.material.name==='siding');assert.ok(other.some(visibleTree));
 };
 c.round();assert.equal(seen,12);c.manager.dispose();
});
function visibleTree(o){for(let p=o;p;p=p.parent)if(!p.visible)return false;return true;}
await test('bursts_debounce_and_render_one_cube_per_frame_with_no_repeat',async()=>{
 const c=await setup();c.manager.frame();for(let i=0;i<20;i++){c.advance(30);c.manager.request();}
 c.advance(1499);c.manager.frame();assert.equal(c.renderer.faces.length,0);c.advance(1);
 for(let i=1;i<=4;i++){c.manager.frame();assert.equal(c.renderer.faces.length,6*i);}
 for(let i=0;i<20;i++){c.advance(1000);c.manager.frame();}assert.equal(c.renderer.faces.length,24);
 assert.ok(c.manager.info().probes.every(p=>p.captures===1&&p.fresh));assert.equal(c.manager.info().pending,false);c.manager.dispose();
});
await test('no_captures_or_probe_maps_in_unlit_and_resume_requests_round',async()=>{
 const c=await setup();c.round();c.manager.setUnlit(true);const n=c.renderer.faces.length;c.manager.request();c.advance(2000);c.manager.frame();assert.equal(c.renderer.faces.length,n);
 for(const o of meshes(c.out))if(o.material.userData.reflection)assert.equal(o.material.envMap,null);
 const u=createUnlit();u.apply(c.out.root);for(const o of meshes(c.out))if(o.material.isMeshMatcapMaterial){const s={uniforms:{},vertexShader:THREE.ShaderLib.matcap.vertexShader,fragmentShader:THREE.ShaderLib.matcap.fragmentShader};o.material.onBeforeCompile(s,{});assert.ok(!s.fragmentShader.includes('probeDirection'));}
 u.restore();u.dispose();c.manager.setUnlit(false);c.round();assert.ok(c.manager.info().probes.every(p=>p.captures===2));c.manager.dispose();
});
await test('targets_reused_on_rebuild_and_all_disposed_on_change_and_close',async()=>{
 const base=fixture();base.buildings=[base.buildings[0]];
 const c=await setup('medium',base);c.round();const targets=[...c.renderer.targets],disposed=new Set();targets.forEach(t=>t.addEventListener('dispose',()=>disposed.add(t)));
 for(const t of targets){assert.equal(t.width,256);assert.equal(t.texture.type,THREE.HalfFloatType);assert.equal(t.texture.colorSpace,THREE.LinearSRGBColorSpace);assert.equal(t.texture.generateMipmaps,true);assert.equal(t.texture.minFilter,THREE.LinearMipmapLinearFilter);}
 c.manager.rebuild(c.p,c.out.root);c.round();assert.deepEqual([...c.renderer.targets],targets);assert.ok(c.manager.info().probes.every(p=>p.captures===2));
 const p=structuredClone(c.p);p.site.pool=null;c.manager.rebuild(p,c.out.root);assert.equal(disposed.size,2);c.manager.dispose();assert.equal(disposed.size,4);assert.equal(c.manager.info().pending,false);
});
await test('uncaptured_targets_are_disposed_too_and_scene_bounds_work_without_a_lot',async()=>{
 const dispose=THREE.WebGLCubeRenderTarget.prototype.dispose;let count=0;
 THREE.WebGLCubeRenderTarget.prototype.dispose=function(){count++;dispose.call(this);};
 try{const p=fixture();delete p.site.lot;p.buildings[0].rotation=90;
  const c=await setup('max',p),info=c.manager.info();assert.equal(info.probes.length,4);
  assert.ok(info.probes.every(p=>p.box.max[0]>p.box.min[0]&&p.box.max[2]>p.box.min[2]));
  const house=info.probes.find(p=>p.id==='exterior:a');near(house.centre[0],-12*.3048);near(house.centre[2],-20*.3048);near(house.centre[1],2*.3048+1.5);
  c.manager.dispose();assert.equal(count,4);c.manager.frame();assert.equal(c.renderer.faces.length,0);
 }finally{THREE.WebGLCubeRenderTarget.prototype.dispose=dispose;}
});
await test('failed_refresh_uses_sky_and_next_request_can_recover',async()=>{
 const c=await setup('high');c.round();c.renderer.fail=true;c.manager.request();c.round();
 assert.ok(c.manager.info().probes.every(p=>!p.fresh&&p.captures===1));
 for(const o of meshes(c.out))if(o.material.userData.reflection)assert.equal(o.material.envMap,null);
 c.renderer.fail=false;c.manager.request();c.round();assert.ok(c.manager.info().probes.every(p=>p.fresh&&p.captures===2));
 for(const target of c.renderer.targets)assert.equal(target.texture.mipmapsAutoUpdate,true,'CubeCamera throw did not leave mipmaps disabled');c.manager.dispose();
});
await test('live_lights_request_but_identical_values_and_sun_motion_do_not',async()=>{
 const c=await setup();const lamp=new THREE.PointLight();c.scene.add(lamp);c.round();const n=c.renderer.faces.length;
 // Lights are scanned twice a second, not every frame.
 lamp.intensity=2;c.manager.frame();assert.equal(c.manager.info().pending,false);
 c.advance(500);c.manager.frame();assert.equal(c.manager.info().pending,true);c.advance(1500);for(let i=0;i<4;i++)c.manager.frame();assert.equal(c.renderer.faces.length,n+24);
 const sun=new THREE.DirectionalLight();sun.name='real-sun';c.scene.add(sun);for(let i=0;i<10;i++){sun.position.x++;c.advance(1000);c.manager.frame();}assert.equal(c.renderer.faces.length,n+24);c.manager.dispose();
});
await test('real_water_and_baked_glass_hooks_survive_viewing_and_bake_clones',async()=>{
 const c=await setup();
 const water=meshes(c.out).find(o=>o.material.userData.waterSurface).material;
 const ws=compile(water.clone());assert.ok(ws.uniforms.waterTime&&ws.uniforms.waterMotion&&ws.uniforms.probeCentre);assert.ok(ws.fragmentShader.includes('waterSlope('));
 const pane=meshes(c.out).find(o=>o.material.userData.reflection?.kind==='exterior').material;
 const baked=pane.clone(),tints=new THREE.DataTexture(new Uint8Array(4),1,1);
 patchWindowGlow(baked,{banks:[]},{lmTints:{value:tints}});
 for(const material of [baked,baked.clone()]){const s=compile(material);assert.ok(s.uniforms.probeCentre&&s.uniforms.lmTints);assert.ok(s.fragmentShader.includes('totalEmissiveRadiance += glow'));
  assert.ok(s.fragmentShader.includes('reflectVec = probeDirection(reflectVec)'));assert.ok(material.customProgramCacheKey().includes('|box-reflection-3|exterior|twin-window-glow'));}
 c.manager.dispose();
});
await test('late_library_maps_reach_pane_and_its_presentation_clones',async()=>{
 const original=THREE.TextureLoader.prototype.load,delayed=[];
 THREE.TextureLoader.prototype.load=function(url,done){const t=new THREE.Texture({width:4,height:4});delayed.push(()=>done(t));return t;};
 try{
  const p=fixture(),k=kit();p.buildings[0].materials.pane={id:'blend'};k.manifest.blend.maps.base_color='materials/reflection-pane/maps/colour.png';
  const out=G.buildTwin(p,k,'medium',{viewing:true});
  await new Promise(resolve=>setImmediate(resolve));delayed.forEach(done=>done());await out.ready;
  const pane=meshes(out).find(o=>o.material.userData.reflection?.owner==='a').material;assert.ok(pane.map,'map loaded after batching');
  assert.equal(pane.clone().map,pane.map);assert.ok(pane.premultipliedAlpha);
 }finally{THREE.TextureLoader.prototype.load=original;}
});
for(const kind of ['water','exterior'])await test('standard_shader_box_patch_chains_hooks_cache_and_clones_'+kind,()=>{
 const source=new THREE.MeshStandardMaterial({transparent:true,opacity:.26});let calls=0;source.onBeforeCompile=s=>{calls++;s.uniforms.library={value:1};};source.customProgramCacheKey=()=>'library-key';
 const m=R.reflectionMaterial(source,kind,'a'),s=compile(m);assert.equal(calls,1);assert.ok(s.uniforms.library);assert.ok(s.fragmentShader.includes('probeBox('));assert.ok(s.vertexShader.includes('vProbeWorld ='));
 assert.ok(s.fragmentShader.includes(kind==='water'?'waterProbeSample(waterProbeIndex, probeBox':'reflectVec = probeDirection(reflectVec)'));
 const clone=m.clone(),cs=compile(clone);assert.equal(calls,2);assert.equal(cs.uniforms.probeCentre,s.uniforms.probeCentre);assert.equal(clone.customProgramCacheKey(),m.customProgramCacheKey());assert.ok(m.customProgramCacheKey().startsWith('library-key|box-reflection'));
 const other=R.reflectionMaterial(new THREE.MeshStandardMaterial(),kind,'other');assert.equal(other.customProgramCacheKey().split('|box-reflection')[1],m.customProgramCacheKey().split('|box-reflection')[1]);
 assert.throws(()=>m.onBeforeCompile({uniforms:{},vertexShader:'void main(){}',fragmentShader:s.fragmentShader},{}),/Reflection shader missing anchor/);
 const chunk=THREE.ShaderChunk.envmap_physical_pars_fragment;try{THREE.ShaderChunk.envmap_physical_pars_fragment='void noAnchor() {}';assert.throws(()=>compile(m),/Reflection shader missing anchor/);}finally{THREE.ShaderChunk.envmap_physical_pars_fragment=chunk;}
});
await test('water_body_gives_up_the_share_of_light_its_surface_mirrors',()=>{
 const s=compile(R.reflectionMaterial(new THREE.MeshStandardMaterial({transparent:true}),'water','a'));
 const at=n=>s.fragmentShader.indexOf(n);
 const share=s.fragmentShader.match(/if \(waterProbeCount > 0\) \{\s*float waterMirror = ([\d.]+) \+ ([\d.]+) \* pow\(1\.0 - abs\(dot\(normal, geometryViewDir\)\), 5\.0\);/);
 assert.ok(share,'only a mirroring surface dims its body, so low quality is untouched');
 near(+share[1]+ +share[2],1);assert.ok(+share[1]<=.04,'head-on water mirrors almost nothing');
 for(const term of ['directDiffuse','indirectDiffuse']){const line='reflectedLight.'+term+' *= 1.0 - waterMirror;';
  assert.ok(at('#include <lights_fragment_end>')<at(line)&&at(line)<at('#include <opaque_fragment>'),term);}
 const pane=compile(R.reflectionMaterial(new THREE.MeshStandardMaterial({transparent:true,opacity:.26}),'exterior','b'));
 assert.ok(!pane.fragmentShader.includes('waterMirror'));
});
// A camera standing beside the pool, looking across it at eye height.
function poolCamera(c,height=1.7){
 const pool=c.manager.info().probes.find(p=>p.id==='water:pool').centre;
 const camera=new THREE.PerspectiveCamera(50,16/9,.1,500);camera.position.set(pool[0]-9,pool[1]+height,pool[2]+2);
 camera.lookAt(pool[0],pool[1],pool[2]);camera.updateMatrixWorld();return {camera,pool};
}
const planarUniforms=c=>meshes(c.out).find(o=>o.material.userData.waterSurface).material.userData.reflection.uniforms;
for(const failure of [false,true])await test('high_water_mirror_is_the_scene_seen_from_the_reflected_camera_and_restores_everything_'+failure,async()=>{
 const c=await setup('high');c.round();const {camera,pool}=poolCamera(c);
 const hidden=[new THREE.Sprite(),new THREE.LineSegments(),new THREE.Group()];hidden[2].userData.reflectionExclude=true;hidden.forEach(o=>c.scene.add(o));
 const sheet=new THREE.Mesh(new THREE.PlaneGeometry(),new THREE.MeshBasicMaterial());c.scene.add(sheet);c.extra.push(sheet);
 const lamp=new THREE.PointLight();lamp.shadow.autoUpdate=true;lamp.shadow.needsUpdate=true;c.scene.add(lamp);
 // A household's imported model can carry a null name (seen on device 2026-11-18:
 // the name test threw and the mirror gave up for good).
 const nameless=new THREE.LOD();nameless.name=null;nameless.add(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()));c.scene.add(nameless);
 const saved=state(c.renderer);let virtual=null;c.renderer.failMirror=failure;
 c.renderer.inspectMirror=(s,v)=>{virtual=v;
  assert.ok(hidden.every(o=>!o.visible));assert.ok(!sheet.visible);
  for(const o of meshes(c.out))if(o.material.userData.reflection)
   assert.equal(o.visible,o.material.userData.reflection.kind==='ground','mirrors hidden, ground visible in planar mirror');
  assert.equal(c.renderer.shadowMap.autoUpdate,false);assert.equal(c.renderer.shadowMap.needsUpdate,false);
  assert.equal(c.renderer.xr.enabled,false);assert.equal(c.renderer.toneMapping,THREE.NoToneMapping);
  // Same plane count as the picture's own pass: no material is set up again per pass.
  assert.equal(c.renderer.localClippingEnabled,saved.local);assert.equal(c.renderer.clippingPlanes,saved.clipping);
  const t=c.renderer.target;assert.deepEqual([t.width,t.height],[960,540]);assert.equal(t.texture.type,THREE.HalfFloatType);
  assert.equal(t.texture.colorSpace,THREE.LinearSRGBColorSpace);assert.equal(t.texture.generateMipmaps,false);
 };
 c.manager.mirror(camera);
 assert.equal(c.renderer.mirrors.length,1);assert.deepEqual(state(c.renderer),saved);assert.ok(hidden.every(o=>o.visible));assert.ok(sheet.visible);
 assert.equal(lamp.shadow.autoUpdate,true);assert.equal(lamp.shadow.needsUpdate,true,'no light loses its pending shadow');
 for(const o of meshes(c.out))if(o.material.userData.reflection)assert.equal(o.visible,true);
 const u=planarUniforms(c),info=c.manager.info().planar;
 assert.equal(info.active,!failure);assert.equal(u.waterPlanarActive.value,failure?0:1);
 if(failure){assert.equal(c.warnings.length,1);assert.equal(u.waterPlanar.value,null);
  c.renderer.failMirror=false;c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,1,'a failed mirror is not retried every frame');
  c.manager.rebuild(c.p,c.out.root);c.round();c.manager.mirror(camera);assert.equal(c.manager.info().planar.active,true,'a rebuild tries again');c.manager.dispose();return;}
 assert.deepEqual(c.warnings,[],'a nameless object never stops the mirror');
 assert.equal(info.passes,1);assert.deepEqual(info.size,[960,540]);near(u.waterPlanarHeight.value,pool[1]);assert.equal(u.waterPlanar.value,c.renderer.mirrors[0].texture);
 // A point above the water sits in the image where the eye sees its mirror
 // twin below the water, left and right swapped as in any mirror; the water
 // looks the image up through the same matrix, so the swap cancels.
 const eye=new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse);
 for(const [x,y,z] of [[3,2,-1],[-2,.4,4],[6,5,-6]]){
  const above=new THREE.Vector4(pool[0]+x,pool[1]+y,pool[2]+z,1).applyMatrix4(u.waterPlanarMatrix.value);
  const below=new THREE.Vector4(pool[0]+x,pool[1]-y,pool[2]+z,1).applyMatrix4(eye);
  near(above.x/above.w,-below.x/below.w);near(above.y/above.w,below.y/below.w);
 }
 // The image is cut MIRROR_LIFT over the water: the deck and coping around
 // the pool (their undersides, seen from the mirrored camera) and the pool
 // shell are clipped away; what stands higher is kept.
 const depth=y=>{const p=new THREE.Vector4(pool[0]+1,pool[1]+y,pool[2]+1,1).applyMatrix4(virtual.matrixWorldInverse).applyMatrix4(virtual.projectionMatrix);return p.z/p.w;};
 assert.ok(R.MIRROR_LIFT>.3&&R.MIRROR_LIFT<.5,'about a foot: deck and coping height');
 assert.ok(Math.abs(depth(R.MIRROR_LIFT)+1)<1e-4,'the cut is the near plane');assert.ok(depth(.15)<-1,'deck underside is clipped');
 assert.ok(depth(-.5)<-1,'pool shell is clipped');assert.ok(depth(2)>-1);
 // The walk that finds what to hide is not repeated every frame.
 let walks=0;const traverse=c.scene.traverse;c.scene.traverse=function(f){walks++;return traverse.call(this,f);};
 c.manager.setMirrorStillHz(0); // This restoration scenario exercises the original every-frame path.
 for(let i=0;i<5;i++)c.manager.mirror(camera);assert.equal(walks,0);c.advance(500);c.manager.mirror(camera);assert.equal(walks,1);
 c.scene.traverse=traverse;assert.equal(c.manager.info().planar.passes,7);
 c.manager.dispose();
});
await test('water_mirror_is_skipped_where_it_cannot_show_and_medium_never_draws_one',async()=>{
 const c=await setup('high');c.round();const {camera,pool}=poolCamera(c),u=planarUniforms(c);
 const expectOff=(cam,why)=>{const n=c.renderer.mirrors.length;c.manager.mirror(cam);assert.equal(c.renderer.mirrors.length,n,why);assert.equal(u.waterPlanarActive.value,0,why);assert.equal(c.manager.info().planar.active,false,why);};
 c.manager.mirror(camera);assert.equal(u.waterPlanarActive.value,1);
 const away=camera.clone();away.lookAt(pool[0]-90,pool[1],pool[2]);away.updateMatrixWorld();expectOff(away,'water out of view');
 const under=camera.clone();under.position.y=pool[1]-.5;under.updateMatrixWorld();expectOff(under,'camera under the water');
 const ortho=new THREE.OrthographicCamera(-10,10,10,-10,.1,100);ortho.position.set(pool[0],pool[1]+20,pool[2]);ortho.lookAt(pool[0],pool[1],pool[2]);ortho.updateMatrixWorld();expectOff(ortho,'plan camera');
 c.manager.setUnlit(true);expectOff(camera,'unlit');c.manager.setUnlit(false);
 c.manager.mirror(camera);assert.equal(u.waterPlanarActive.value,1,'comes back');
 const target=c.renderer.mirrors[0];let gone=0;target.addEventListener('dispose',()=>gone++);c.manager.dispose();assert.equal(gone,1);
 const m=await setup('medium');m.round();const mc=poolCamera(m).camera;m.manager.mirror(mc);
 assert.equal(m.renderer.mirrors.length,0);assert.ok(!('planar' in m.manager.info()));assert.equal(planarUniforms(m).waterPlanarActive.value,0);m.manager.dispose();
});
await test('water_shader_folds_below_horizon_rays_up_and_reads_the_mirror_image_before_the_cube',()=>{
 const s=compile(R.reflectionMaterial(new THREE.MeshStandardMaterial({transparent:true}),'water','a'));const f=s.fragmentShader,at=n=>f.indexOf(n);
 const fold='reflectVec = normalize(vec3(reflectVec.x, max(abs(reflectVec.y), .12), reflectVec.z));';
 assert.ok(at(fold)>0);assert.ok(at(fold)<at('if (waterPlanarActive > .5'));assert.ok(at('if (waterPlanarActive > .5')<at('waterProbeSample(waterProbeIndex, probeBox'));
 assert.ok(f.includes('texture2D(waterPlanar, clamp(waterClip.xy / waterClip.w * .5 + .5, .002, .998)).rgb'));
 // The image is looked up where the bent ray lands, not at a point slid along the water.
 assert.ok(f.includes('waterPlanarMatrix * vec4(vProbeWorld + reflectVec * 5.0, 1.0)'));assert.ok(!f.includes('waterBend'));
 for(const name of ['waterPlanar','waterPlanarMatrix','waterPlanarActive','waterPlanarHeight'])assert.ok(s.uniforms[name],name);
 assert.equal(s.uniforms.waterPlanarActive.value,0,'a surface nobody drew a mirror for uses the cube');
 const pane=compile(R.reflectionMaterial(new THREE.MeshStandardMaterial({transparent:true,opacity:.26}),'exterior','b'));assert.ok(!pane.fragmentShader.includes('waterPlanar'));
});
await test('mounted_high_view_draws_the_water_mirror_inside_its_own_frame_and_not_when_unlit',async()=>{
 location.search='?test=1';const rendererClass=globalThis.Renderer;globalThis.Renderer=CaptureRenderer;
 const originalLoop=CaptureRenderer.prototype.setAnimationLoop;CaptureRenderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
 let view;try{
  view=await mountTwin(new Element(),{plan:fixture(),kit:kit(),tier:'high',bake:false});
  const pool=view.reflectionInfo().probes.find(p=>p.id==='water:pool').centre;
  const clear=view.scene.background;
  view.renderer3.inspectMirror=(s,c)=>{
   if(c===view.camera)return;
   assert.equal(s.background.name,'twin-sky','the mirror receives the cloudy reflection cube');
   assert.notEqual(s.background,clear,'screen clouds must not be marched over their own cloudy cube');
   assert.equal(s.getObjectByName('twin-celestial').visible,false,'the cube already contains cloud-attenuated bodies/stars');
  };
  view.camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);view.controls.target.set(pool[0],pool[1],pool[2]);view.camera.lookAt(view.controls.target);view.camera.updateMatrixWorld();
  const calls=[];const real=view.renderer3.render;view.renderer3.render=function(s,c){calls.push(this.target?.isWebGLRenderTarget&&!this.target.isWebGLCubeRenderTarget?'mirror':'frame');return real.call(this,s,c);};
  const before=view.reflectionInfo().planar.passes;view.render();assert.equal(view.reflectionInfo().planar.passes,before+1);assert.equal(calls[0],'mirror','the mirror is drawn before the picture that shows it');
  assert.equal(view.scene.background,clear,'the visible sky is restored after the mirror');
  view.setMirrorStillHz(2);const still=view.reflectionInfo().planar.passes;view.render();assert.equal(view.reflectionInfo().planar.passes,still);
  view.reflectionsChanged('lamp');view.render();assert.equal(view.reflectionInfo().planar.passes,still,'lamp request obeys the still mirror interval');
  view.reflectionsChanged();view.render();assert.equal(view.reflectionInfo().planar.passes,still+1,'explicit scene invalidation draws next frame');
  view.setView('ext');assert.ok(view.reflectionInfo().planar.passes>still+1,'view change forces mirror even at unchanged pose');
  const lit=view.reflectionInfo().planar.passes;view.setUnlit(true);view.render();assert.equal(view.reflectionInfo().planar.passes,lit);
 }finally{view?.dispose();CaptureRenderer.prototype.setAnimationLoop=originalLoop;globalThis.Renderer=rendererClass;}
});
await test('warm_ups_compile_for_the_composer_target_and_frames_hold_until_programs_are_ready',async()=>{
 // A program compiled for the canvas (sRGB, ACES) is not the one the composer's
 // half-float target draws with; a frame drawn while one compiles froze the page.
 location.search='?test=1';const rendererClass=globalThis.Renderer;globalThis.Renderer=CaptureRenderer;
 const proto=CaptureRenderer.prototype,originalLoop=proto.setAnimationLoop;proto.setAnimationLoop=function(fn){this.loop=fn;};
 const compiled=[],compiledNames=[];let manual=null;proto.compileAsync=function(s,c){compiled.push(this.target);compiledNames.push(s.material?.name);
  return manual?new Promise(resolve=>manual.push(resolve)):Promise.resolve(s);};
 const originalNow=performance.now;let time=100000;Object.defineProperty(performance,'now',{configurable:true,value:()=>time});
 let view;try{
  view=await mountTwin(new Element(),{plan:fixture(),kit:kit(),tier:'high',bake:false});
  assert.ok(view.post?.target?.isWebGLRenderTarget);assert.ok(compiled.length,'the mount warms its programs');
  assert.ok(compiled.every((t,i)=>t===(compiledNames[i]==='wet-reflections-march'?view.post.wetReflections.target:view.post.target)),
   'every warm-up compiles for its draw destination: SSR march target, otherwise composer target');
  const saved=view.renderer3.getRenderTarget();let draws=0;const real=view.renderer3.render;view.renderer3.render=function(s,c){draws++;return real.call(this,s,c);};
  manual=[];const ready=view.renderer3.compileAsync(view.scene,view.camera);
  assert.equal(view.renderer3.getRenderTarget(),saved,'the renderer target is put back');
  view.render();view.renderer3.loop();assert.equal(draws,0,'no frame draws while programs compile');
  manual.forEach(resolve=>resolve());await ready;assert.ok(draws>0,'the picture draws as soon as they are ready');
  draws=0;view.renderer3.compileAsync(view.scene,view.camera);view.render();assert.equal(draws,0);
  time+=15001;view.render();assert.ok(draws>0,'a compile that never settles holds the picture 15 s at most');
  manual.forEach(resolve=>resolve());manual=null;
  view.setUnlit(true);compiled.length=0;compiledNames.length=0;await view.renderer3.compileAsync(view.scene,view.camera);
  assert.deepEqual(compiled,[null],'the unlit view draws to the canvas and warms for it');
  assert.equal(view.compileBehind()===null,false,'a warm-up for a change not yet shown');
 }finally{view?.dispose();proto.setAnimationLoop=originalLoop;delete proto.compileAsync;globalThis.Renderer=rendererClass;
  Object.defineProperty(performance,'now',{configurable:true,value:originalNow});}
});
await test('glass_mirror_share_covers_the_room_and_the_pane_is_tone_mapped_as_one_surface',()=>{
 const m=R.reflectionMaterial(new THREE.MeshStandardMaterial({transparent:true,opacity:.26}),'exterior','a');const s=compile(m);
 const js=e=>e.replaceAll('diffuseColor.a','alpha').replaceAll('clamp(','clamp(');
 const clamp=(x,a,b)=>Math.min(b,Math.max(a,x));
 const cover=new Function('alpha','paneFade','paneMirror','clamp','return '+js(s.fragmentShader.match(/float paneCover = ([^;]+);/)[1])+';');
 const light=new Function('outgoingLight','totalSpecular','alpha','paneFade','return '+js(s.fragmentShader.match(/vec3 paneLight = ([^;]+);/)[1])+';');
 assert.ok(s.fragmentShader.includes('gl_FragColor = vec4(paneLight / paneCover, paneCover);'));
 const fresnel=s.fragmentShader.match(/float paneFresnel = ([\d.]+) \+ ([\d.]+) \* pow\(1\.0 - abs\(dot\(normal, geometryViewDir\)\), 5\.0\);/);
 near(+fresnel[1]+ +fresnel[2],1);assert.ok(+fresnel[1]>=.04&&+fresnel[1]<=.2,'head-on mirror share stays that of real glazing');
 // No mirror: the cover is the pane's own opacity, as on low quality.
 near(cover(.26,1,0,clamp),.26);
 // A full mirror hides the room entirely, and never more than the fade allows.
 near(cover(.26,1,1,clamp),1);near(cover(.13,.5,1,clamp),.5);
 for(const mirror of [0,.1,.5,1])for(const alpha of [.26,.4,1]){const c=cover(alpha,1,mirror,clamp);assert.ok(c>=alpha-1e-9&&c<=1);}
 assert.ok(cover(0,0,0,clamp)>0,'a fully faded pane never divides by zero');
 // Tint is weighted by the pane's opacity; mirrored light only by the fade.
 near(light(.15+2,2,.26,1),.15*.26+2);near(light(.5+2,2,.13,.5),.5*.13+2*.5);
 // Display-space blending: the surface colour is divided out before tone
 // mapping and three's own premultiply runs after it.
 const at=n=>s.fragmentShader.indexOf(n);
 assert.ok(at('paneLight / paneCover')<at('#include <tonemapping_fragment>'));
 assert.ok(at('#include <tonemapping_fragment>')<at('#include <premultiplied_alpha_fragment>'));
 assert.equal(compile(m.clone()).uniforms.paneBaseOpacity.value,.26);
 assert.equal(m.premultipliedAlpha,true);assert.equal(m.depthWrite,false);
});
await test('shower_interior_opaque_and_cutout_panes_unchanged_and_no_transmission',async()=>{
 const p=fixture();const b=p.buildings[0];b.walls[1].exterior=false;b.openings.push({...b.openings[0],id:'interior',wall:b.walls[1].id});
 b.openings[0].materials={pane:{id:'choice'}};b.openings[1].materials={pane:{id:'chain_link'}};b.openings[2].materials={pane:{id:'blend'}};
 const c=await setup('medium',p);const parts=id=>c.out.pickObjects.get('a:'+id)?.userData.partObjects?.map(p=>p.object)||[];
 for(const id of ['window','slider','interior'])for(const o of parts(id).filter(o=>o.userData.part==='pane'))assert.ok(!o.material.userData.reflection,id);
 assert.ok(parts('bifold').some(o=>o.material.userData.reflection?.kind==='exterior'),'Library blend pane participates');
 const showers=meshes(c.out).filter(o=>o.material.name==='glass'&&!o.material.userData.reflection);assert.ok(showers.length);assert.ok(showers.every(o=>!o.material.premultipliedAlpha));
 for(const o of meshes(c.out))for(const m of [].concat(o.material))assert.ok(!('transmission' in m));c.manager.dispose();
});
await test('exterior_draw_count_and_pane_order_match_without_probe_hooks',async()=>{
 const p=fixture();const low=G.buildTwin(p,kit(),'low',{viewing:true}),med=G.buildTwin(p,kit(),'medium',{viewing:true});await Promise.all([low.ready,med.ready]);
 const draws=o=>rendered(o).map(m=>[m.material.name,m.geometry.attributes.position.count,m.renderOrder]);
 assert.deepEqual(draws(med),draws(low));
 const materials=meshes(med).filter(o=>o.material.userData.reflection?.owner==='a').map(o=>o.material);assert.equal(new Set(materials).size,1,'panes share one building clone');
});
await test('mounted_hook_requests_rebuild_sky_time_and_lit_changes_without_sync_capture',async()=>{
 location.search='?test=1';const rendererClass=globalThis.Renderer;globalThis.Renderer=CaptureRenderer;
 const originalLoop=CaptureRenderer.prototype.setAnimationLoop;CaptureRenderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
 const originalNow=performance.now;let time=100000;Object.defineProperty(performance,'now',{configurable:true,value:()=>time});
 let view;try{
  view=await mountTwin(new Element(),{plan:fixture(),kit:kit(),tier:'medium',bake:false});
  assert.equal(view.reflectionInfo().probes.length,4);assert.equal(view.renderer3.faces.length,0,'mount/rebuild never captures');
  view.renderer3.loop();time+=1500;for(let i=0;i<4;i++)view.renderer3.loop();assert.ok(view.reflectionInfo().probes.every(p=>p.fresh));
  for(const trigger of [()=>view.setTime('night'),()=>view.setTime('day'),()=>view.reflectionsChanged(),()=>view.applySky(new THREE.Texture())]){
   const n=view.renderer3.faces.length;trigger();assert.equal(view.renderer3.faces.length,n,'synchronous apply never captures');assert.equal(view.reflectionInfo().pending,true);
   time+=1500;for(let i=0;i<5;i++)view.renderer3.loop();assert.ok(view.reflectionInfo().probes.every(p=>p.fresh));
  }
  const before=view.reflectionInfo().probes.map(p=>p.captures);view.setClock('2026-06-01T18:00:00Z');assert.equal(view.reflectionInfo().pending,true,'changed sky requests a capture even within the shadow minute gate');
  time+=60000;view.setClock('2026-06-01T18:01:00Z');assert.equal(view.reflectionInfo().pending,true);time+=1500;for(let i=0;i<5;i++)view.renderer3.loop();
  view.setUnlit(true);const n=view.renderer3.faces.length;time+=61000;view.renderer3.loop();assert.equal(view.renderer3.faces.length,n);
  await view.rebuild(fixture());assert.equal(view.renderer3.faces.length,n);view.setUnlit(false);view.renderer3.loop();time+=1500;for(let i=0;i<5;i++)view.renderer3.loop();
  assert.equal(view.reflectionInfo().probes.length,4);assert.ok(view.reflectionInfo().probes.every(p=>p.fresh),'unlit rebuild keeps source bindings');
 }finally{view?.dispose();CaptureRenderer.prototype.setAnimationLoop=originalLoop;globalThis.Renderer=rendererClass;Object.defineProperty(performance,'now',{configurable:true,value:originalNow});}
});

await test('still_mirror_interval_motion_projection_resize_and_forced_refresh_keep_bindings',async()=>{
 const c=await setup('high');c.round();const {camera}=poolCamera(c),u=planarUniforms(c);
 c.manager.mirror(camera);const texture=u.waterPlanar.value, matrix=u.waterPlanarMatrix.value.clone();
 for(let i=0;i<5;i++)c.manager.mirror(camera);
 assert.equal(c.renderer.mirrors.length,1);assert.equal(u.waterPlanar.value,texture);assert.ok(u.waterPlanarMatrix.value.equals(matrix));
 c.advance(99);c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,1);
 c.advance(1);c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,2);
 for(let i=0;i<3;i++){camera.position.x+=.01;c.manager.mirror(camera);}assert.equal(c.renderer.mirrors.length,5);
 camera.fov+=1;camera.updateProjectionMatrix();c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,6);
 c.manager.setMirrorStillHz(2);c.manager.mirror(camera);const count=c.renderer.mirrors.length;
 c.advance(499);c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,count);
 c.advance(1);c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,count+1);
 c.manager.setMirrorStillHz(0);for(let i=0;i<3;i++)c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,count+4);
 c.manager.setMirrorStillHz(2);c.manager.mirror(camera);
 const forced=fn=>{const before=c.renderer.mirrors.length;fn();c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,before+1);};
 forced(()=>c.manager.rebuild(c.p,c.out.root));
 forced(()=>c.manager.request()); // View/level changes take the same explicit invalidation path.
 forced(()=>{c.renderer.getDrawingBufferSize=v=>v.set(1200,800);});
 forced(()=>{c.manager.setUnlit(true);c.manager.mirror(camera);c.manager.setUnlit(false);});
 const away=camera.clone();away.lookAt(camera.position.clone().add(new THREE.Vector3(0,100,0)));c.manager.mirror(away);
 forced(()=>{}); // Water reappears, even with the same saved pose and no elapsed time.
 assert.equal(u.waterPlanar.value,texture);assert.equal(u.waterPlanarActive.value,1);c.manager.dispose();
});
await test('continuous_lamp_changes_coalesce_without_starvation_and_explicit_requests_bypass_throttle',async()=>{
 const c=await setup();const lamp=new THREE.PointLight();c.scene.add(lamp);c.round();
 const rounds=[];let previous=c.manager.info().probes[0].captures;
 for(let i=0;i<30;i++){
  c.advance(500);lamp.intensity++;c.manager.requestLamp();c.manager.frame();
  const current=c.manager.info().probes[0].captures;if(current!==previous){rounds.push(i*500);previous=current;}
  for(let j=0;j<3;j++)c.manager.frame();
 }
 assert.ok(rounds.length>=2,'continuous changes eventually capture');
 for(let i=1;i<rounds.length;i++)assert.ok(rounds[i]-rounds[i-1]>=5000);
 const before=c.manager.info().probes[0].captures;c.manager.request();c.advance(1500);for(let j=0;j<4;j++)c.manager.frame();
 assert.equal(c.manager.info().probes[0].captures,before+1,'explicit scene/time/sky request keeps its original delay');c.manager.dispose();
});
await test('cloud_drift_coalesces_from_first_change_without_hiding_maps_or_restarting_explicit_quiet',async()=>{
 for(const seconds of [4,10,30,60]) {
  const c=await setup();c.manager.setProbeCloudSeconds(seconds);c.round();
  const material=meshes(c.out).find(o=>o.material.userData.reflection?.kind==='exterior').material;
  const map=material.envMap, baseline=c.renderer.faces.length;
  c.manager.requestSky();c.advance(1499);c.manager.requestSky();c.manager.frame();
  assert.equal(c.renderer.faces.length,baseline);assert.equal(material.envMap,map);assert.ok(c.manager.info().probes.every(p=>p.fresh));
  c.advance(seconds*1000-1500);c.manager.requestSky();c.manager.frame();assert.equal(c.renderer.faces.length,baseline);
  c.advance(1);c.manager.requestSky();for(let i=0;i<4;i++)c.manager.frame();
  assert.equal(c.renderer.faces.length,baseline+24,'one round exactly at the interval; repeated requests never postpone it');
  c.manager.requestSky();c.advance(200);c.manager.request();c.advance(1499);c.manager.requestSky();c.manager.frame();
  assert.equal(c.renderer.faces.length,baseline+24);
  c.advance(1);for(let i=0;i<4;i++)c.manager.frame();
  assert.equal(c.renderer.faces.length,baseline+48,'explicit request takes priority before cloud interval');
  assert.equal(c.manager.info().pending,false,'explicit round consumes earlier sky requests');c.manager.dispose();
 }
});
await test('default_cloud_interval_is_30s_and_live_changes_keep_original_pending_time',async()=>{
 const c=await setup();c.round();const baseline=c.renderer.faces.length;
 for(let elapsed=4000;elapsed<=28000;elapsed+=4000){c.advance(4000);c.manager.requestSky();for(let i=0;i<4;i++)c.manager.frame();}
 assert.equal(c.renderer.faces.length,baseline,'four-second drift no longer recaptures four probes every four seconds');
 c.advance(2000);for(let i=0;i<4;i++)c.manager.frame();assert.equal(c.renderer.faces.length,baseline+24);
 c.manager.requestSky();c.advance(10000);c.manager.setProbeCloudSeconds(10);for(let i=0;i<4;i++)c.manager.frame();
 assert.equal(c.renderer.faces.length,baseline+48,'live interval change applies without resetting pending quiet');
 c.manager.dispose();c.manager.requestSky();assert.equal(c.manager.info().pending,false);
 const low=await setup('low');low.manager.requestSky();low.round();assert.equal(low.manager.info().pending,false);assert.equal(low.renderer.faces.length,0);low.manager.dispose();
});
await test('sky_only_requests_and_rounds_leave_still_mirror_on_its_own_interval',async()=>{
 const c=await setup('high');c.round();const {camera}=poolCamera(c);c.manager.setMirrorStillHz(2);c.manager.mirror(camera);
 c.advance(10);c.manager.requestSky();c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,1,'sky request never dirties mirror');
 c.advance(29990);for(let i=0;i<4;i++)c.manager.frame();c.manager.mirror(camera);const count=c.renderer.mirrors.length;
 c.advance(1);c.manager.requestSky();c.manager.frame();c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,count);
 c.manager.request();c.manager.mirror(camera);assert.equal(c.renderer.mirrors.length,count+1,'explicit request still dirties mirror');c.manager.dispose();
});
await test('mounted_cloud_drift_uses_payload_and_live_interval_but_weather_and_time_remain_prompt',async()=>{
 location.search='?test=1';const rendererClass=globalThis.Renderer;globalThis.Renderer=CaptureRenderer;
 const originalLoop=CaptureRenderer.prototype.setAnimationLoop;CaptureRenderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
 const originalNow=performance.now;let time=100000;Object.defineProperty(performance,'now',{configurable:true,value:()=>time});
 let view;try {
  view=await mountTwin(new Element(),{plan:fixture(),kit:kit(),tier:'medium',bake:false,stage:{probe_cloud_s:60}});
  view.setClock('2026-06-01T18:00:00Z');let weather={state:'cloudy'};
  view.live={peek:()=>({'weather.local':weather}),stale:()=>false,stop:()=>{},draw:()=>{}};
  // Noise generation/fade has its own tests. Hold fade settled while running
  // the real sky cube and the twin's real animation/probe entry points.
  view.clouds.frame=()=>{};view.clouds.uniforms.cloudFade.value=1;view.render();
  const frames=n=>{for(let i=0;i<n;i++)view.renderer3.loop();};
  frames(6);time+=1500;frames(4);const baseline=view.renderer3.faces.length;
  assert.equal(baseline,24);assert.ok(view.clouds.active);
  for(let i=0;i<8;i++){time+=4000;frames(8);}
  assert.equal(view.renderer3.faces.length,baseline,'payload 60s interval is used, rather than the 30s default');
  view.setProbeCloudSeconds(10);frames(4);
  assert.equal(view.renderer3.faces.length,baseline+24,'drawer live setter applies to pending drift');
  await view.setStage({probe_cloud_s:4});time+=4000;frames(6);time+=1500;frames(4);
  assert.equal(view.renderer3.faces.length,baseline+48,'editor stage payload also applies interval live');
  view.setProbeCloudSeconds(60);weather={state:'partlycloudy'};view.render();frames(6);time+=1500;frames(4);
  assert.equal(view.renderer3.faces.length,baseline+72,'weather bypasses cloud interval');
  view.setClock('2026-06-01T20:00:00Z');frames(6);time+=1500;frames(4);
  assert.equal(view.renderer3.faces.length,baseline+96,'time of day bypasses cloud interval');
 } finally {view?.dispose();CaptureRenderer.prototype.setAnimationLoop=originalLoop;globalThis.Renderer=rendererClass;Object.defineProperty(performance,'now',{configurable:true,value:originalNow});}
});
await test('ground_receivers_bind_yard_probe_stay_visible_in_reflections_and_leave_non_receivers_unchanged',async()=>{
 const p=fixture();
 p.site.hardscape=[
  {id:'patio_a',polygon:square(4,28,10),material:'paving'},
  {id:'patio_b',polygon:square(66,28,10),material:'paving'},
 ];
 p.site.terraces=[{id:'pad_b',polygon:square(62,26,16,12),height:3,
  edges:[{edge:'sharp',wall:{material:'stone',cap:{thickness_in:2,overhang_in:1},rail:{height:3}},
          stairs:[{at:6,width:4,steps:4}]},{edge:'blend'},{edge:'blend'},{edge:'blend'}]}];
 const c=await setup('high',p);
 // Add an indoor lamp inside building a, an outdoor lamp in the yard, plus a bulb and lightWash.
 const indoorLamp=new THREE.PointLight('#fff1c9',40);indoorLamp.position.set(10*.3048,3,-10*.3048);c.scene.add(indoorLamp);
 const outdoorLamp=new THREE.PointLight('#fff1c9',12);outdoorLamp.position.set(20*.3048,2,-36*.3048);c.scene.add(outdoorLamp);
 const bulb=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());bulb.userData.bulb='dev-1';c.scene.add(bulb);
 const wash=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());wash.userData.lightWash=true;c.scene.add(wash);
 let yardFaces=0,yardBuildingsVisible=false,yardIndoorDimmed=false,yardOutdoorFull=false,groundVisibleInAllCaptures=true;
 const targetsSeen=[];
 c.renderer.inspect=()=>{
  const t=c.renderer.target;if(!targetsSeen.includes(t))targetsSeen.push(t);
  const probe=c.manager.info().probes[targetsSeen.length-1];
  assert.equal(bulb.visible,false,'bulb hidden in captures');
  assert.equal(wash.visible,false,'lightWash hidden in captures');
  for(const o of meshes(c.out))if(o.material.userData.reflection){
   if(o.material.userData.reflection.kind==='ground'){if(!o.visible)groundVisibleInAllCaptures=false;}
   else assert.equal(o.visible,false,'mirror surface hidden in captures');
  }
  if(probe.kind==='yard'){
   yardFaces++;
   const bldgOf=o=>{for(let p=o;p;p=p.parent)if(p.userData?.buildingId)return p.userData.buildingId;return null;};
   const bldgVisible=id=>meshes(c.out).some(o=>bldgOf(o)===id&&o.material.name==='siding'&&!o.layers.isEnabled(31)&&visibleTree(o));
   if(bldgVisible('a')&&bldgVisible('b'))yardBuildingsVisible=true;
   if(indoorLamp.intensity<=1.5)yardIndoorDimmed=true;
   if(outdoorLamp.intensity===12)yardOutdoorFull=true;
  }
 };
 c.round();c.advance(700);c.manager.frame();
 assert.equal(yardFaces,6,'yard probe captured all 6 faces');
 assert.ok(yardBuildingsVisible,'every building stays visible during yard probe capture');
 assert.ok(yardIndoorDimmed,'indoor point light softened during yard capture');
 assert.ok(yardOutdoorFull,'outdoor point light keeps full intensity during yard capture');
 assert.equal(indoorLamp.intensity,40,'indoor point light restored after capture');
 assert.ok(groundVisibleInAllCaptures,'ground meshes remain visible during all probe captures');
 // Ground also stays visible in the high-tier planar pool mirror while mirrors stay hidden.
 const {camera}=poolCamera(c);let mirrorChecked=false;
 c.renderer.inspectMirror=()=>{
  mirrorChecked=true;
  assert.equal(bulb.visible,false);assert.equal(wash.visible,false);
  for(const o of meshes(c.out))if(o.material.userData.reflection)
   assert.equal(o.visible,o.material.userData.reflection.kind==='ground');
 };
 c.manager.mirror(camera);assert.ok(mirrorChecked);
 // High-tier yard probe is 512 (matching sky PMREM), while exterior/water remain 256.
 const info=c.manager.info();
 assert.equal(info.probes.length,4,'stays within 4-probe cap');
 assert.ok(info.probes.some(pr=>pr.kind==='water')&&info.probes.some(pr=>pr.kind==='exterior')&&info.probes.some(pr=>pr.kind==='yard'));
 const all=meshes(c.out).filter(o=>!o.layers.isEnabled(31));
 const ground=all.filter(o=>o.material.userData.reflection?.kind==='ground');
 assert.ok(ground.some(o=>o.userData.yardPart==='hardscape'),'hardscape binds ground');
 assert.ok(ground.some(o=>o.userData.yardPart==='pool'),'pool/spa coping binds ground');
 assert.ok(ground.some(o=>o.userData.yardPart==='retaining_walls'),'retaining wall caps/treads bind ground');
 assert.ok(ground.every(o=>o.material.userData.reflection.probe?.id==='yard:ground'),'all ground receivers bind yard:ground');
 assert.equal(ground[0].material.userData.reflection.probe.target.width,512,'high-tier yard probe matches 512 sky PMREM');
 const extProbe=meshes(c.out).find(o=>o.material.userData.reflection?.kind==='exterior').material.userData.reflection.probe;
 assert.equal(extProbe.target.width,256,'exterior probes stay 256');
 const rwMeshes=all.filter(o=>o.userData.yardPart==='retaining_walls');
 assert.ok(rwMeshes.some(o=>!o.material.userData.reflection),'retaining wall faces/risers/rails stay unbound');
 // Non-receivers must remain completely untouched.
 for(const o of all){
  const m=o.material,r=m.userData.reflection;
  if(o.userData.terrain||m.name==='lawn'||m.userData.seasonLawn||m.userData.materialRole==='lawn')assert.ok(!r,'lawn unbound');
  if(m.name==='roof'||m.userData.materialRole==='roof')assert.ok(!r,'roof unbound');
  if(m.name==='siding'||m.name==='interior_wall')assert.ok(!r,m.name+' unbound');
  if(m.userData.underwater||m.name==='pool tile'||m.name==='waterline tile')assert.ok(!r,'underwater/tile unbound');
  if(m.userData.waterSurface)assert.equal(r?.kind,'water','water keeps water kind');
 }
 const gm=ground[0].material,gs=compile(gm),gr=gm.userData.reflection;
 assert.equal(gm.premultipliedAlpha,false);assert.equal(gm.depthWrite,true);
 assert.ok(gs.fragmentShader.includes('#define REFLECTION_PROBE_GROUND'));
 assert.ok(gs.fragmentShader.includes('reflectVec = probeDirection(reflectVec)'));
 assert.ok(gs.fragmentShader.includes('probeRough')&&gs.fragmentShader.includes('probeGain'));
 assert.ok(!gs.fragmentShader.includes('paneMirror')&&!gs.fragmentShader.includes('waterPlanar'));
 assert.ok(gr.uniforms.probeMax.value.y<gr.probe.box.max.y,'ground proxy ceiling caps below 30 m lot sky');
 assert.ok(info.probes.every(pr=>pr.box.max[1]>=30),'probe box unchanged');
 c.manager.dispose();
 // Plan with hardscape spanning front & back of a building places yard:ground outside the building footprint.
 const split=fixture();split.buildings=[building('a',0)];
 split.site.hardscape=[
  {id:'front_walk',polygon:square(12,-10,16,8),material:'paving'},
  {id:'back_patio',polygon:square(8,28,24,18),material:'paving'},
 ];
 const c2=await setup('medium',split);
 const yp=c2.manager.info().probes.find(pr=>pr.kind==='yard');
 assert.ok(yp,'yard probe created');
 assert.ok(yp.centre[2]<-24*.3048,'placed outside building over larger backyard patio');
 c2.manager.dispose();
});
await test('ground_falls_back_to_sky_cross_fades_and_keeps_old_probe_on_recapture',async()=>{
 const c=await setup('medium');
 const gm=meshes(c.out).find(o=>o.material.userData.reflection?.kind==='ground').material;
 const b=gm.userData.reflection;
 // Pending first capture: sky fallback.
 assert.equal(gm.envMap,null);assert.equal(b.uniforms.probeActive.value,0);
 near(gm.envMapIntensity,c.scene.environmentIntensity);
 // First capture starts smooth fade-in rather than popping straight to 1.
 c.round();
 assert.equal(gm.envMap,b.probe.target.texture);
 const startActive=b.uniforms.probeActive.value;
 assert.ok(startActive>0&&startActive<.1,'fresh capture starts cross-fade near 0');
 c.advance(300);c.manager.frame();
 const midActive=b.uniforms.probeActive.value;
 assert.ok(midActive>.4&&midActive<.6,'mid-fade is smooth');
 c.advance(300);c.manager.frame();
 near(b.uniforms.probeActive.value,1);
 // envMapIntensity tracks live scene.environmentIntensity changes.
 c.scene.environmentIntensity=.42;c.manager.frame();near(gm.envMapIntensity,.42);
 // Recaptures (explicit, lamp, sky) keep the previous cube bound at fade=1 without dipping.
 const boundTex=gm.envMap;
 for(const trigger of [()=>c.manager.request(),()=>c.manager.requestLamp(),()=>c.manager.requestSky()]){
  trigger();c.manager.frame();
  assert.equal(gm.envMap,boundTex,'old capture stays bound while pending');
  near(b.uniforms.probeActive.value,1,'no fade dip during pending recapture');
 }
 c.advance(1500);for(let i=0;i<4;i++)c.manager.frame();
 assert.equal(gm.envMap,boundTex);near(b.uniforms.probeActive.value,1);
 // Capture failure and unlit fall back cleanly to sky.
 c.renderer.fail=true;c.manager.request();c.round();
 assert.equal(gm.envMap,null);assert.equal(b.uniforms.probeActive.value,0);
 c.renderer.fail=false;c.manager.request();c.round();
 assert.equal(gm.envMap,boundTex);assert.ok(b.uniforms.probeActive.value<.1,'recovery re-fades cleanly');
 c.advance(600);c.manager.frame();near(b.uniforms.probeActive.value,1);
 c.manager.setUnlit(true);assert.equal(gm.envMap,null);assert.equal(b.uniforms.probeActive.value,0);
 c.manager.setUnlit(false);c.round();c.advance(600);c.manager.frame();
 assert.equal(gm.envMap,boundTex);near(b.uniforms.probeActive.value,1);
 c.manager.dispose();
});
await test('standard_shader_box_patch_chains_hooks_cache_and_clones_ground',()=>{
 const source=new THREE.MeshStandardMaterial({roughness:.85});let calls=0;
 source.onBeforeCompile=s=>{calls++;s.uniforms.library={value:1};};source.customProgramCacheKey=()=>'library-key';
 const m=R.reflectionMaterial(source,'ground','a'),s=compile(m);
 assert.equal(calls,1);assert.ok(s.uniforms.library);assert.ok(s.fragmentShader.includes('probeBox('));
 assert.ok(s.fragmentShader.includes('#define REFLECTION_PROBE_GROUND'));
 assert.equal(m.premultipliedAlpha,false);assert.equal(m.depthWrite,true);
 const clone=m.clone(),cs=compile(clone);
 assert.equal(calls,2);assert.equal(cs.uniforms.probeCentre,s.uniforms.probeCentre);
 assert.equal(clone.customProgramCacheKey(),m.customProgramCacheKey());
 const other=R.reflectionMaterial(new THREE.MeshStandardMaterial(),'ground','other');
 assert.equal(other.customProgramCacheKey().split('|box-reflection')[1],m.customProgramCacheKey().split('|box-reflection')[1]);
});
finish();
"""

from test_twin_cloud_shadow_js import DRIVER as CLOUD_DRIVER

BUDGET_DRIVER = CLOUD_DRIVER.split("await test('lazy CPU texels")[0] + r"""
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
await test('ground_horizon_damp_skip_and_uniform_sampler_budgets',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene();
 renderer.toneMapping=THREE.ACESFilmicToneMapping;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;
 const makePMREM=size=>{const t=new THREE.CubeTexture();t.isPMREMTexture=true;t.mipmaps=[];
  for(let l=0;l<=Math.log2(size)-3;l++)t.mipmaps.push({width:size>>l,height:size>>l});return t;};
 scene.environment=makePMREM(512);
 const probe512=makePMREM(512);
 const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),weather=installWeatherSurface(scene);
 const lights=makeLights();
 lights.directional=[{},{}];lights.directionalShadowMap=[{}];
 lights.point=Array.from({length:4},()=>({}));lights.pointShadowMap=[{},{}];
 lights.spot=[{},{}];lights.spotShadowMap=[{}];lights.rectArea=[{}];lights.hemi=[{}];
 const cache=programs(renderer);
 const cases=[
  ['solid Standard',()=>new THREE.MeshStandardMaterial({name:'paving'})],
  ['solid mapped',()=>new THREE.MeshStandardMaterial({name:'paving',map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()})],
  ['coping Physical',()=>new THREE.MeshPhysicalMaterial({name:'paving',map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()})],
  ['baked 2-bank 8-lamp stress',()=>{const m=new THREE.MeshStandardMaterial({name:'paving',map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()});
   patchLightmaps([m],{banks:Array.from({length:2},()=>new THREE.DataArrayTexture(new Uint8Array(64),4,4,1))},lightmapUniforms(1,8,{fixtures:true}));return m;}],
 ];
 for(const [label,factory] of cases){
  const mb=factory(),ma=factory();
  reflectionMaterial(ma,'ground','yard');
  const ob=new THREE.Mesh(new THREE.BoxGeometry(),mb),oa=new THREE.Mesh(new THREE.BoxGeometry(),ma);
  ob.receiveShadow=oa.receiveShadow=true;scene.add(ob,oa);
  haze.prepare();shadow.prepare();weather.prepare();
  const sb=programSource(renderer,cache,scene,ob,lights),saSky=programSource(renderer,cache,scene,oa,lights);
  ma.envMap=probe512;
  const sa=programSource(renderer,cache,scene,oa,lights);
  assert.equal(saSky.key,sa.key,label+': 512 sky and 512 yard probe share one program cache key');
  const bb=uniformBudget(sb[2]),ba=uniformBudget(sa[2]);
  assert.equal(ba.samplers.length,bb.samplers.length,label+': zero added samplers');
  assert.ok(ba.samplers.length<=16,label+': samplers within 16');
  assert.ok(ba.vectors-bb.vectors<=4,label+': at most 4 added uniform vectors');
  assert.ok(ba.vectors<=224,label+': fragment uniform vectors within 224');
  assert.ok(preprocess(sa[2]).includes('radiance*=mix(weatherHorizonDamp,1.0,probeActive);'),label+': skips horizon damp when probe active');
  assert.ok(preprocess(sb[2]).includes('radiance*=weatherHorizonDamp;'),label+': non-ground keeps horizon damp');
 }
 // Roof and lawn also retain plain horizon damp.
 for(const [name,role] of [['roof','roof'],['lawn','lawn']]){
  const m=new THREE.MeshStandardMaterial({name});m.userData.materialRole=role;
  const o=new THREE.Mesh(new THREE.BoxGeometry(),m);o.receiveShadow=true;scene.add(o);
  haze.prepare();shadow.prepare();weather.prepare();
  const s=programSource(renderer,cache,scene,o,lights);
  assert.ok(preprocess(s[2]).includes('radiance*=weatherHorizonDamp;'),name+': keeps horizon damp');
  assert.ok(!preprocess(s[2]).includes('REFLECTION_PROBE_GROUND'),name+': no ground probe define');
 }
 weather.dispose();shadow.dispose();haze.dispose();
});
finish();
"""

if __name__ == '__main__':
    for script in (DRIVER, BUDGET_DRIVER):
        code, output = run_node(script, {'root': ROOT.as_posix(), 'editable': True})
        print(output)
        if code:
            sys.exit(code)
    sys.exit(0)
