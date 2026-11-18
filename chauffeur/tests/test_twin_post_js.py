"""Execute the real r187 composer/passes and mounted view under node; no browser."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node
from test_twin_build_draft_pause_js import EDITOR_STUBS

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE = await import('three');
const {EffectComposer} = await import('three/addons/postprocessing/EffectComposer.js');
const {RenderPass} = await import('three/addons/postprocessing/RenderPass.js');
const {GTAOPass} = await import('three/addons/postprocessing/GTAOPass.js');
const {OutputPass} = await import('three/addons/postprocessing/OutputPass.js');
const {UnrealBloomPass} = await import('three/addons/postprocessing/UnrealBloomPass.js');
const {createPost, EMITTER_GAIN} = await import(file('static/twin/post.js'));
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {TIERS} = await import(file('static/twin/twin_tiers.js'));
const {buildGrass} = await import(file('static/twin/yard_grass.js'));
const {surfaceMaterial} = await import(file('static/twin/effects/water_surface.js'));
const {underwaterMaterial} = await import(file('static/twin/effects/underwater.js'));
const {buildEffects} = await import(file('static/twin/effects/index.js'));
const passes = {}, events = [], targets = new Set(), composers = [];
let composeCount = 0;
const addPass = EffectComposer.prototype.addPass;
EffectComposer.prototype.addPass = function(pass) {
  if(!composers.includes(this))composers.push(this);
  return addPass.call(this,pass);
};
const compose = EffectComposer.prototype.render;
EffectComposer.prototype.render = function(...args) { ++composeCount; return compose.apply(this,args); };
for (const Type of [RenderPass,GTAOPass,UnrealBloomPass,OutputPass]) {
  const draw = Type.prototype.render;
  Type.prototype.render = function(...args) { passes[Type.name] = this; events.push(Type.name); return draw.apply(this,args); };
}
const plain = Renderer.prototype.render;
Renderer.prototype.render = function(scene,camera) {
  plain.call(this,scene,camera);
  if(this.info.autoReset)this.info.reset();
  const normal = !!scene.overrideMaterial;
  this.inspect?.({scene,camera,normal,target:this.getRenderTarget()});
  if(this.getRenderTarget()?.isWebGLRenderTarget)targets.add(this.getRenderTarget());
  this.info.render.calls += scene.isScene ? (normal ? 19 : 37) : 1;
  this.info.render.triangles += scene.isScene ? (normal ? 1900 : 3700) : 1;
};
const near = (a,b) => assert.ok(Math.abs(a-b)<1e-6, `${a} != ${b}`);
const state = r => ({target:r.getRenderTarget(),face:r.getActiveCubeFace(),mip:r.getActiveMipmapLevel(),
  auto:r.autoClear,infoAuto:r.info.autoReset,tone:r.toneMapping,color:r.getClearColor(new THREE.Color()).toArray(),alpha:r.getClearAlpha()});
function setup(samples=4) {
  const renderer = new Renderer(), scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(38,1,.1,1000);
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.setSize(640,400);
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()));
  const post = createPost(renderer,scene,camera,{samples});
  return {renderer,scene,camera,post};
}
async function mount(tier='high',perf=false) {
  location.search = `?test=1&tier=${tier}${perf?'&perf=1':''}`;
  const host = new Element();
  const view = await mountTwin(host,{plan:structuredClone(input.plan),kit:{materials:{}},tier,bake:false});
  return {host,view};
}
await test('tiers opt in above low; low mounts with no composer or targets and renders plainly',async()=>{
  assert.deepEqual(Object.values(TIERS).map(t=>t.occlusion),[false,true,true,true]);
  const before = composeCount, built = composers.length; targets.clear();
  const {view} = await mount('low');
  try { assert.equal(view.post,null); view.render(); assert.equal(composeCount,before); assert.equal(composers.length,built); assert.equal(targets.size,0);
    assert.equal(view.stats().drawCalls,37); assert.equal(view.stats().triangles,3700);
  } finally {view.dispose();}
});
await test('high mounts real render occlusion output chain with half-float four-sample buffers',async()=>{
  const {view} = await mount();
  try {
    events.length=0; targets.clear(); view.render();
    assert.deepEqual(view.post.info().passes,['RenderPass','GTAOPass','UnrealBloomPass','OutputPass']);
    assert.deepEqual(events,['RenderPass','GTAOPass','UnrealBloomPass','OutputPass']);
    const beautyTargets=[...targets].filter(t=>t.samples===4);
    assert.equal(beautyTargets.length,2);
    for(const t of beautyTargets)assert.equal(t.texture.type,THREE.HalfFloatType);
    const ao=passes.GTAOPass;
    near(ao.gtaoMaterial.uniforms.radius.value,1);near(ao.blendIntensity,.7);
    near(ao.gtaoMaterial.uniforms.scale.value,1.5);near(ao.gtaoMaterial.uniforms.thickness.value,2);
    assert.equal(ao.gtaoMaterial.defines.SCREEN_SPACE_RADIUS,0);near(ao.gtaoMaterial.uniforms.distanceFallOff.value,.6);
    assert.equal(ao.output,GTAOPass.OUTPUT.Default);assert.equal(ao.pdMaterial.uniforms.radius.value,8);
  } finally {view.dispose();}
});
await test('glow sits before the output transform and its threshold follows exposure above paper white',async()=>{
  const {view} = await mount();
  try {
    view.setTime('day');view.render();const glow=passes.UnrealBloomPass;
    near(glow.strength,.25);near(glow.radius,.45);
    near(glow.threshold*view.renderer3.toneMappingExposure,1.6);
    // Only what a pixel has over the threshold glows, so a brightly lit wall does not glow whole.
    const pass=glow.materialHighPassFilter.fragmentShader;
    assert.ok(pass.includes('gl_FragColor = mix( outputColor, texel * max( 0.0, 1.0 - luminosityThreshold / max( v, 1e-4 ) ), alpha );'));
    assert.ok(!pass.includes('mix( outputColor, texel, alpha )'));
    near(glow.highPassUniforms.luminosityThreshold.value,glow.threshold);
    const day=glow.threshold;
    view.setTime('night');view.render();
    assert.notEqual(glow.threshold,day);near(glow.threshold*view.renderer3.toneMappingExposure,1.6);
    view.post.tune({bloom:{strength:.1,radius:.2,threshold:2}});view.render();
    near(glow.strength,.1);near(glow.radius,.2);near(glow.threshold*view.renderer3.toneMappingExposure,2);
  } finally {view.dispose();}
});
await test('the glow and the output read a held value: not-a-number is black and neither passes its ceiling',()=>{
  const c=setup();
  try {
    c.post.render();
    for(const [material,name,ceiling] of [[passes.UnrealBloomPass.materialHighPassFilter,'texel','luminosityThreshold * 2.2'],[passes.OutputPass.material,'gl_FragColor','4096.0']]) {
      const source=material.fragmentShader;
      assert.ok(source.includes(`float held( float v ) { return v >= 0.0 ? min( v, ${ceiling} ) : 0.0; }`),name);
      const read=source.indexOf('texture2D( tDiffuse, vUv );'),held=source.indexOf(`${name}.rgb = vec3( held( ${name}.r ), held( ${name}.g ), held( ${name}.b ) );`);
      assert.ok(read>0&&held>read,name);
      // Nothing reads the sample between the lookup and the guard.
      assert.equal(source.slice(read+'texture2D( tDiffuse, vUv );'.length,held).trim(),'');
      assert.equal(source.split('void main()').length,2);
    }
  } finally {c.post.dispose();}
});
await test('lamps are drawn brighter than white only where the glow chain runs',async()=>{
  assert.equal(EMITTER_GAIN,3);
  const high=await mount();
  try {assert.equal(high.view.emitterGain,3);} finally {high.view.dispose();}
  const low=await mount('low');
  try {assert.equal(low.view.emitterGain,1);} finally {low.view.dispose();}
});
await test('unlit bypasses the composer then lit returns with current exposure',async()=>{
  const {view} = await mount();
  try {
    view.setTime('day');const day=view.renderer3.toneMappingExposure;
    const before=composeCount;view.setUnlit(true);view.render();assert.equal(composeCount,before);
    assert.equal(view.stats().drawCalls,37);
    view.setUnlit(false);assert.ok(composeCount>before);
    view.setTime('night');view.render();assert.notEqual(view.renderer3.toneMappingExposure,day);
    near(passes.OutputPass.uniforms.toneMappingExposure.value,view.renderer3.toneMappingExposure);
    assert.ok('ACES_FILMIC_TONE_MAPPING' in passes.OutputPass.material.defines);
    assert.ok('SRGB_TRANSFER' in passes.OutputPass.material.defines);
    assert.equal(view.renderer3.toneMapping,THREE.ACESFilmicToneMapping);
  } finally {view.dispose();}
});
await test('mounted resize reaches all composer targets at the current pixel ratio',async()=>{
  const previous=globalThis.ResizeObserver; let resized;
  globalThis.ResizeObserver=class {constructor(fn){resized=fn;}observe(){}disconnect(){}};
  let view;
  try {
    const mounted=await mount();view=mounted.view;mounted.host.clientWidth=731;mounted.host.clientHeight=419;
    view.renderer3.setPixelRatio(1.5);resized();
    assert.deepEqual(view.post.info().size,{width:731,height:419,pixelRatio:1.5});
    near(passes.GTAOPass.width,731*1.5);near(passes.GTAOPass.height,419*1.5);
  } finally {view?.dispose();globalThis.ResizeObserver=previous;}
});
await test('perf meter pixel-ratio clicks resize post on the next frame and stop restores it',async()=>{
  const {view,host}=await mount('high',true);
  try {
    const button=host.querySelector('.twin-frame-meter button'), ratio=view.renderer3.getPixelRatio();
    await click(button);view.render();near(view.post.info().size.pixelRatio,ratio*.75);
    await click(button);view.render();near(view.post.info().size.pixelRatio,ratio*.5);
    view.meter.stop();view.render();near(view.post.info().size.pixelRatio,ratio);
  } finally {view.dispose();}
});
for(const fail of [false,true])await test('thumbnail output uses post at custom size and restores size and camera '+fail,async()=>{
  const {view}=await mount();
  try {
    view.renderer3.setPixelRatio(1.5);view.render();const saved=view.post.info().size,camera=view.camera;
    const old=view.renderer3.domElement.toDataURL, reads=[];
    view.renderer3.domElement.toDataURL=()=>{
      assert.deepEqual(view.post.info().size,{width:320,height:200,pixelRatio:1});
      assert.equal(events.at(-1),'OutputPass');reads.push(view.camera);
      if(fail)throw Error('canvas copy failed');return 'data:image/png;base64,test';
    };
    try {
      if(fail)await assert.rejects(view.capture(['front','back'],320,200),/canvas copy failed/);
      else assert.equal((await view.capture(['front','back'],320,200)).length,2);
    } finally {view.renderer3.domElement.toDataURL=old;}
    assert.ok(reads.length);assert.deepEqual(view.post.info().size,saved);assert.equal(view.camera,camera);
    assert.equal(passes.RenderPass.camera,camera);assert.equal(passes.GTAOPass.camera,camera);
  } finally {view.dispose();}
});
await test('plan camera and restored perspective reach every camera-bearing pass and shader define',async()=>{
  const {view}=await mount();
  try {
    const saved=view.saveView(), building=input.plan.buildings[0],key=building.id+':'+building.levels[0].id;
    view.setPlanCamera(key);assert.ok(view.camera.isOrthographicCamera);
    for(const p of [passes.RenderPass,passes.GTAOPass])assert.equal(p.camera,view.camera);
    assert.equal(passes.GTAOPass.gtaoMaterial.defines.PERSPECTIVE_CAMERA,0);
    assert.equal(passes.GTAOPass.depthRenderMaterial.defines.PERSPECTIVE_CAMERA,0);
    view.restoreView(saved);assert.ok(view.camera.isPerspectiveCamera);
    for(const p of [passes.RenderPass,passes.GTAOPass])assert.equal(p.camera,view.camera);
    assert.equal(passes.GTAOPass.gtaoMaterial.defines.PERSPECTIVE_CAMERA,1);
    // A thumbnail temporarily uses perspective and must restore the plan camera too.
    view.setPlanCamera(key);const ortho=view.camera;view.renderer3.domElement.toDataURL=()=>'';
    await view.capture(['front'],80,60);assert.equal(view.camera,ortho);
    assert.equal(passes.GTAOPass.camera,ortho);assert.equal(passes.GTAOPass.gtaoMaterial.defines.PERSPECTIVE_CAMERA,0);
  } finally {view.dispose();}
});
function excludedObjects() {
  const lawn=buildGrass({buildings:[],site:{lot:[[0,0],[40,0],[40,40],[0,40]]}},{materials:{}},'medium',new THREE.MeshStandardMaterial());
  assert.ok(lawn.mesh?.userData.noOcclusion);
  const source=new THREE.MeshStandardMaterial(), water=surfaceMaterial(source,null,{tier:'high'}).material;
  const underwater=underwaterMaterial(source,{height:0,polygon:[[0,0],[10,0],[10,10],[0,10]]},{tier:'high'}).material;
  assert.ok(water.userData.noOcclusion);assert.ok(underwater.clone().userData.noOcclusion);
  const mesh=m=>new THREE.Mesh(new THREE.PlaneGeometry(),m);
  const fx=buildEffects({effect_fixtures:[{id:'f',type:'fountain',at:[0,0,0],strength:1}]},{editor:true});
  assert.ok(fx.group.userData.noOcclusion);
  const objects=[lawn.mesh,mesh(water),mesh(underwater),mesh(water.clone()),fx.group,
    mesh(new THREE.MeshPhysicalMaterial({transparent:true})),mesh(new THREE.MeshStandardMaterial({alphaTest:.5})),
    new THREE.Sprite(),new THREE.Line(),new THREE.Points(),new THREE.BoxHelper(),
    mesh(new THREE.MeshBasicMaterial({depthTest:false})),new THREE.Group(),new THREE.Group(),new THREE.Group(),new THREE.Group()];
  objects[12].userData.ghost=true;objects[13].userData.noOcclusion=true;
  objects[14].userData.preview=true;objects[15].layers.set(31);
  const initiallyHidden=mesh(new THREE.MeshStandardMaterial({transparent:true}));initiallyHidden.visible=false;objects.push(initiallyHidden);
  return objects;
}
for(const fail of [false,true])await test('real lawn water cards glass sprites helpers hidden only for prepass and restored '+fail,()=>{
  const c=setup(), objects=excludedObjects(), visible=objects.map(o=>o.visible);
  c.scene.add(...objects);let beauty=0,normals=0;
  c.renderer.inspect=({scene,normal})=>{
    if(scene!==c.scene)return;
    if(normal){++normals;assert.ok(objects.every(o=>!o.visible));assert.equal(c.scene.children[0].visible,true);
      assert.equal(c.renderer.shadowMap.enabled,false);if(fail)throw Error('depth prepass failed');}
    else {++beauty;assert.deepEqual(objects.map(o=>o.visible),visible);}
  };
  try {
    if(fail)assert.throws(()=>c.post.render(),/depth prepass failed/);else c.post.render();
    assert.equal(beauty,1);assert.equal(normals,1);assert.deepEqual(objects.map(o=>o.visible),visible);
    assert.equal(c.scene.overrideMaterial,null);
  } finally {c.post.dispose();objects.forEach(o=>o.traverse(n=>{n.geometry?.dispose();[].concat(n.material||[]).forEach(m=>m.dispose());}));}
});
await test('a faded-in solid copy and glass stay in the prepass; a fading copy and other see-through leave it',()=>{
  const c=setup(), mesh=m=>new THREE.Mesh(new THREE.PlaneGeometry(),m);
  const copy=(depthWrite)=>{const m=new THREE.MeshStandardMaterial({transparent:true,depthWrite});m.userData.viewingOpaque=true;return m;};
  const glass=new THREE.MeshStandardMaterial({name:'glass',transparent:true,opacity:.26,depthWrite:false});
  const solid=mesh(copy(true)),fading=mesh(copy(false)),pane=mesh(glass),veil=mesh(new THREE.MeshStandardMaterial({transparent:true}));
  c.scene.add(solid,fading,pane,veil);let normals=0;
  c.renderer.inspect=({scene,normal})=>{
    if(scene!==c.scene||!normal)return;++normals;
    assert.deepEqual([solid,fading,pane,veil].map(o=>o.visible),[true,false,true,false]);
  };
  try {c.post.render();assert.equal(normals,1);assert.ok([solid,fading,pane,veil].every(o=>o.visible));}
  finally {c.post.dispose();}
});
for(const fail of [false,true])await test('a clipped mesh draws the prepass with its own planes and gets its material back '+fail,()=>{
  const c=setup(), plane=new THREE.Plane(new THREE.Vector3(0,-1,0),3), other=new THREE.Plane(new THREE.Vector3(0,-1,0),6);
  const cut=p=>{const m=new THREE.MeshStandardMaterial({transparent:true,clippingPlanes:[p]});m.userData.viewingOpaque=true;return m;};
  const a=cut(plane),b=cut(plane),d=cut(other),free=new THREE.MeshStandardMaterial();
  const one=new THREE.Mesh(new THREE.BoxGeometry(),a),two=new THREE.Mesh(new THREE.BoxGeometry(),[b,free]),three=new THREE.Mesh(new THREE.BoxGeometry(),d);
  c.scene.add(one,two,three);let seen=[],disposed=0;
  c.renderer.inspect=({scene,normal})=>{
    if(scene!==c.scene||!normal)return;
    const n=one.material;seen.push(n);
    assert.ok(n.isMeshNormalMaterial);assert.equal(n.allowOverride,false);assert.equal(n.clippingPlanes[0],plane);
    assert.equal(two.material[0],n);assert.equal(two.material[1].allowOverride,true);assert.ok(!two.material[1].clippingPlanes?.length);
    assert.equal(three.material.clippingPlanes[0],other);assert.notEqual(three.material,n);
    if(!n.listened){n.listened=true;n.addEventListener('dispose',()=>++disposed);}
    if(fail)throw Error('prepass');
  };
  try {
    if(fail)assert.throws(()=>c.post.render(),/prepass/);else c.post.render();
    assert.equal(one.material,a);assert.deepEqual(two.material,[b,free]);assert.equal(three.material,d);
    c.renderer.inspect=null;
    // The same plane reuses one normal material; a plane no longer drawn frees its own.
    if(!fail){c.renderer.inspect=({scene,normal})=>{if(scene===c.scene&&normal)assert.equal(one.material,seen[0]);};c.post.render();c.renderer.inspect=null;}
    c.scene.remove(one,two);c.post.render();assert.equal(disposed,1);
  } finally {c.post.dispose();}
});
for(const fail of [false,true])await test('composer restores renderer state between frames including failed prepass '+fail,()=>{
  const c=setup();c.scene.background=new THREE.Color('#7799bb');const bg=c.scene.background;
  c.scene.fog=new THREE.Fog('#667788',10,100);const fog=c.scene.fog;
  c.renderer.setRenderTarget(new THREE.WebGLRenderTarget(20,20),3,2);
  c.renderer.autoClear=false;c.renderer.info.autoReset=true;c.renderer.setClearColor('#123456',.3);
  const saved=state(c.renderer);
  c.renderer.inspect=({scene,normal})=>{if(scene===c.scene&&normal&&fail)throw Error('prepass');};
  try {
    if(fail)assert.throws(()=>c.post.render(),/prepass/);else c.post.render();
    assert.deepEqual(state(c.renderer),saved);assert.equal(c.scene.background,bg);assert.equal(c.scene.fog,fog);
    // Offscreen callers retain their direct path and caller-owned target.
    c.renderer.inspect=null;c.renderer.render(new THREE.Scene(),c.camera);assert.deepEqual(state(c.renderer),saved);
  } finally {c.post.dispose();saved.target.dispose();}
});
await test('clear background survives ACES and exposure while fog remains scene-linear',()=>{
  const c=setup();c.scene.fog=new THREE.Fog('#667788',10,100);const fog=c.scene.fog;
  const inputMatrix=new THREE.Matrix3().set(.59719,.35458,.04823,.076,.90834,.01566,.0284,.13383,.83777);
  const outputMatrix=new THREE.Matrix3().set(1.60475,-.53108,-.07367,-.10208,1.10813,-.00605,-.00327,-.07276,1.07602);
  const fit=x=>(x*(x+.0245786)-.000090537)/(x*(.983729*x+.432951)+.238081);
  try {
    for(const [hex,exposure] of [['#7799bb',1.1],['#101a30',.7],['#000000',1]]) {
      c.scene.background=new THREE.Color(hex);const bg=c.scene.background;c.renderer.toneMappingExposure=exposure;
      c.renderer.inspect=({scene,normal})=>{if(scene!==c.scene)return;
        if(normal){assert.equal(scene.background,null);return;}
        assert.equal(scene.fog,fog);
        const v=new THREE.Vector3(scene.background.r,scene.background.g,scene.background.b).multiplyScalar(exposure/.6).applyMatrix3(inputMatrix);
        v.set(fit(v.x),fit(v.y),fit(v.z)).applyMatrix3(outputMatrix);
        v.toArray().forEach((n,i)=>near(n,bg.toArray()[i]));
      };
      c.post.render();assert.equal(c.scene.background,bg);
      near(passes.OutputPass.uniforms.toneMappingExposure.value,exposure);
    }
  } finally {c.post.dispose();}
});
await test('stats and afterNextRender describe only the main scene not normals or fullscreen work',async()=>{
  const {view}=await mount();
  try {
    const next=view.afterNextRender();view.render();tick();const detail=await next;
    assert.equal(view.stats().drawCalls,37);assert.equal(view.stats().triangles,3700);
    assert.equal(detail.draw_calls,37);assert.equal(detail.triangles,3700);
    assert.ok(view.renderer3.info.render.calls>37);assert.ok(view.renderer3.info.render.triangles>3700);
    view.setUnlit(true);view.render();assert.equal(view.stats().drawCalls,37);
  } finally {view.dispose();}
});
await test('saved-house thumbnail callback in the real editor boot renders through the view',async()=>{
  const {view}=await mount();globalThis.__postEditorView=view;
  const source=input.editor_stubs
    .replace("export const mountTwin = async () => ({ scene: {}, rebuild: async p => { globalThis.rendered = p; } });",
      "export const mountTwin = async () => globalThis.__postEditorView;")
    .replace("export const mountHouses = () => ({ sync() {} });",
      "export const mountHouses = options => (globalThis.__postHouseOptions=options,{sync(){}});");
  const url=data(source);
  registerHooks({resolve(spec,ctx,next){
    if(ctx.parentURL===file('static/twin/editor/editor.js'))return {url,shortCircuit:true};
    return next(spec,ctx);
  }});
  globalThis.sheets={sources:[],page_roles:[],place:{buildings:[]}};
  const old=Element.prototype.toDataURL;
  Element.prototype.toDataURL=()=>{assert.equal(events.at(-1),'OutputPass');return 'data:image/png;base64,house';};
  try {
    const {boot}=await import(file('static/twin/editor/editor.js'));await boot();assert.ok(window.__editor.ready);
    const before=composeCount;
    assert.equal(await globalThis.__postHouseOptions.capture(),'data:image/png;base64,house');
    assert.equal(composeCount,before+1);
  } finally {Element.prototype.toDataURL=old;view.dispose();}
});
const glowResources=glow=>[glow.renderTargetBright,...glow.renderTargetsHorizontal,...glow.renderTargetsVertical,
  glow.materialHighPassFilter,...glow.separableBlurMaterials,glow.compositeMaterial,glow.blendMaterial];
await test('dispose frees both composer targets all AO and glow targets textures and shader materials once',()=>{
  const c=setup();targets.clear();c.post.render();
  const ao=passes.GTAOPass,out=passes.OutputPass,glow=passes.UnrealBloomPass;
  const resources=new Set([...targets,...glowResources(glow),ao.normalRenderTarget,ao.gtaoRenderTarget,ao.pdRenderTarget,
    ao.normalRenderTarget.depthTexture,ao.gtaoNoiseTexture,ao.pdNoiseTexture,ao.normalMaterial,
    ao.gtaoMaterial,ao.pdMaterial,ao.copyMaterial,ao.depthRenderMaterial,ao.blendMaterial,out.material,composers.at(-1).copyPass.material]);
  // WebGLRenderer disposes a target's depth texture in its GPU deallocator;
  // this harness has no GPU listener, so assert ownership through the target.
  resources.delete(ao.normalRenderTarget.depthTexture);
  const counts=new Map();resources.forEach(r=>r.addEventListener('dispose',()=>counts.set(r,(counts.get(r)||0)+1)));
  c.post.dispose();c.post.dispose();assert.equal(c.post.info().enabled,false);
  resources.forEach(r=>assert.equal(counts.get(r),1,r.constructor.name));
});
await test('disposal before the first frame releases unrendered targets and materials too',()=>{
  const c=setup(),composer=composers.at(-1),ao=composer.passes[1];
  const resources=[composer.renderTarget1,composer.renderTarget2,ao.normalRenderTarget,ao.gtaoRenderTarget,ao.pdRenderTarget,
    ao.gtaoNoiseTexture,ao.pdNoiseTexture,ao.normalMaterial,ao.gtaoMaterial,ao.pdMaterial,ao.copyMaterial,
    ao.depthRenderMaterial,ao.blendMaterial,...glowResources(composer.passes[2]),composer.passes[3].material,composer.copyPass.material];
  const freed=new Set();resources.forEach(r=>r.addEventListener('dispose',()=>freed.add(r)));
  c.post.dispose();assert.equal(freed.size,resources.length);
});
await test('mounted view disposal releases its post targets and repeated disposal is harmless',async()=>{
  const {view}=await mount(),composer=composers.at(-1),ao=composer.passes[1];
  const resources=[composer.renderTarget1,composer.renderTarget2,ao.normalRenderTarget,ao.gtaoRenderTarget,ao.pdRenderTarget];
  const counts=new Map();resources.forEach(r=>r.addEventListener('dispose',()=>counts.set(r,(counts.get(r)||0)+1)));
  view.dispose();view.dispose();assert.equal(view.post.info().enabled,false);
  resources.forEach(r=>assert.equal(counts.get(r),1));
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'editor_stubs': EDITOR_STUBS})
    print(out)
    sys.exit(code or 0)
