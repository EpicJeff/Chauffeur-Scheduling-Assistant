"""Actual material hook assembly and r187 cache keys with stage haze; no GPU/browser."""
import json
from pathlib import Path
import sys

from test_twin_yard_reuse_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
const {installStageHaze,STAGE_RING_DEPRESSIONS,stageRingDirection}=await import(file('static/twin/sky/stage_haze.js'));
const {createSky,sampleRadiance}=await import(file('static/twin/sky/atmosphere.js'));
const {patchLightmaps,lightmapUniforms,setLightTint}=await import(file('static/twin/bake/lightmap_material.js'));
const {grassMaterial}=await import(file('static/twin/yard_grass.js'));
const {surfaceMaterial}=await import(file('static/twin/effects/water_surface.js'));
const {kitMaterial,disposeObject}=await import(file('static/twin/twin_library.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {createViewing}=await import(file('static/twin/viewing.js'));
registerHooks({load(url,ctx,next){
 if(url.endsWith('three.module.js?stage-material-keys'))return {format:'module',shortCircuit:true,source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms};'};
 return next(url,ctx);
}});
const {WebGLPrograms}=await import(file('static/vendor/three-r187/three.module.js')+'?stage-material-keys');
const expand=source=>source.replace(/#include\s+<([\w\d_]+)>/g,(_,name)=>{
 assert.equal(typeof THREE.ShaderChunk[name],'string','vendored chunk '+name+' exists');return expand(THREE.ShaderChunk[name]);
});
const assemble=(material,renderer)=>{
 const lib=THREE.ShaderLib[material.isMeshBasicMaterial?'basic':material.isMeshPhysicalMaterial?'physical':'standard'];
 const shader={uniforms:THREE.UniformsUtils.clone(lib.uniforms),vertexShader:lib.vertexShader,fragmentShader:lib.fragmentShader};
 material.onBeforeCompile(shader,renderer);return shader;
};
const verifyHaze=(shader,cube,label)=>{
 assert.equal(shader.uniforms.stageRing?.value?.length,40,label+' carries this sky ring');assert.ok(!('stageSky' in shader.uniforms),label+' no sky sampler');
 const vertex=expand(shader.vertexShader),fragment=expand(shader.fragmentShader);
 assert.ok(!/#include\s+</.test(vertex+fragment),label+' resolves every include');
 assert.equal((vertex.match(/varying vec3 vStageWorld;/g)||[]).length,1,label+' one vertex varying');
 assert.equal((fragment.match(/uniform float stageRadius\b/g)||[]).length,1,label+' one fragment uniform block');
 assert.ok(vertex.includes('vStageWorld = ( modelMatrix * stageWorld ).xyz;'),label+' world position');
 assert.ok(vertex.includes('stageWorld = instanceMatrix * stageWorld;'),label+' instances included');
 assert.ok(fragment.includes('stageSkyColour( stageRay )')&&fragment.includes('gl_FragColor.rgb = mix('),label+' horizon mix');
 assert.ok(!/samplerCube stage/.test(fragment),label+' haze adds no texture unit');
 return {vertex,fragment};
};
const lights=Object.fromEntries(['sun','directional','point','spot','spotLightMap','rectArea','hemi','sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'].map(k=>[k,[]]));
lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;
function keyReader(renderer,scene){
 renderer.state={buffers:{depth:{getReversed:()=>false}}};
 const clipping={numPlanes:0,numIntersection:0};
 const cache=WebGLPrograms(renderer,{get:t=>t},{has:()=>false},{precision:'highp',getMaxPrecision:()=> 'highp'},{},clipping);
 return object=>{const material=object.material;clipping.numPlanes=material.clippingPlanes?.length||0;
  const parameters=cache.getParameters(material,lights,[],scene,object,[]);
  assert.equal(parameters.fog,true);assert.equal(parameters.useFog,true);
  return cache.getProgramCacheKey(parameters);
 };
}
await test('stock, real bake, viewing, grass, water, granite and glass keep patches and keys',()=>{
 const renderer=new Renderer(),sky=createSky(renderer,{tier:'high'}),scene=new THREE.Scene();
 scene.environment=sky.environment;scene.background=sky.cube;
 const haze=installStageHaze(scene,sky),fog=scene.fog,environment=scene.environment;
 const model=buildTwin(input.plan,{materials:{}},'high',{viewing:true});scene.add(model.root);
 const originalMaterials=new Map();model.root.traverse(o=>{if(o.material)originalMaterials.set(o,o.material);});
 const view={plan:input.plan,scene,roomLights:[],camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},renderer3:renderer};
 view.camera.position.set(0,30,30);
 const viewing=createViewing(view,model,()=>0,()=>{});
 const rows=[],add=(label,material,instanced=false)=>{
  const geometry=new THREE.BoxGeometry();
  const object=instanced?new THREE.InstancedMesh(geometry,material,1):new THREE.Mesh(geometry,material);
  scene.add(object);rows.push({label,object,material});return object;
 };
 add('stock',new THREE.MeshStandardMaterial());
 const baked=new THREE.MeshStandardMaterial(),lm=lightmapUniforms(1,2),page=new THREE.DataArrayTexture(new Uint8Array(64),4,4,1);
 patchLightmaps([baked],{banks:[page]},lm);add('lightmap',baked);
 const lawn=new THREE.MeshStandardMaterial({color:'#58783b'}),waterSource=new THREE.MeshStandardMaterial({transparent:true,opacity:.4});
 add('grass',grassMaterial(lawn),true);add('water',surfaceMaterial(waterSource).material);
 add('granite',kitMaterial('granite',{materials:{granite:{color:'#3b3d40',roughness:.22}}},'high'));
 let glass,clone;model.root.traverse(o=>{
  if(!o.isMesh||!o.material?.isMeshStandardMaterial||!o.material.clippingPlanes?.length)return;
  if(o.material.name==='glass')glass||=o;else clone||=o;
 });
 assert.ok(glass,'fixture builds actual glass through the generator');assert.ok(clone,'actual viewing channel creates a clipped clone');
 assert.equal(glass.material.transparent,true);assert.equal(glass.material.depthWrite,false);
 assert.notEqual(clone.material,originalMaterials.get(clone));assert.equal(clone.material.transparent,true);
 rows.push({label:'glass',object:glass,material:glass.material},{label:'viewing',object:clone,material:clone.material});
 const before=rows.map(({material})=>assemble(material,renderer));haze.prepare();
 const key=keyReader(renderer,scene);
 rows.forEach((row,i)=>{
  const shader=assemble(row.material,renderer),expanded=verifyHaze(shader,sky.cube,row.label);
  assert.equal(shader.vertexShader,before[i].vertexShader,row.label+' keeps the original vertex patch');
  assert.equal(shader.fragmentShader,before[i].fragmentShader,row.label+' keeps the original fragment patch');
  Object.assign(row,{shader,expanded,key:key(row.object),version:row.material.version,hook:row.material.onBeforeCompile});
 });
 const byName=Object.fromEntries(rows.map(r=>[r.label,r]));
 assert.equal(byName.lightmap.shader.uniforms.lmTints,lm.lmTints);
 assert.equal(byName.lightmap.shader.uniforms.lmBank0.value,page);
 assert.ok(byName.lightmap.expanded.fragment.includes('vec3 lmFill = vec3(0.0)')&&byName.lightmap.expanded.vertex.includes('vLmUV = uv3; vLmRoom = lmRoom;'));
 assert.equal(byName.grass.shader.uniforms.grassTime,byName.grass.material.userData.grassUniforms.grassTime);
 assert.ok(byName.grass.expanded.vertex.includes('float grassKeep')&&byName.grass.expanded.fragment.includes('lawnBlade'));
 assert.equal(byName.water.shader.uniforms.waterTime,byName.water.material.userData.waterSurface.waterTime);
 assert.ok(byName.water.expanded.fragment.includes('waterSlope')&&byName.water.expanded.vertex.includes('vWaterWorld ='));
 assert.equal(byName.granite.shader.uniforms.graniteTint.value,byName.granite.material.color);
 assert.ok(byName.granite.expanded.fragment.includes('neutralStone'));
 for(const radius of [30,120,1000])for(const [alt,overcast]of [[60,0],[2,.4],[-20,1]]){
  haze.set({centre:[radius/10,7],radius});
  sky.update({sunDir:[Math.cos(alt*Math.PI/180),Math.sin(alt*Math.PI/180),0],overcast,force:true});
  setLightTint(lm,0,0,[255,230,180],radius/1000);haze.prepare();
  assert.equal(scene.fog,fog);assert.equal(scene.environment,environment);
  for(const row of rows){assert.equal(key(row.object),row.key,row.label+' real r187 key');assert.equal(row.material.version,row.version);
   assert.equal(row.material.onBeforeCompile,row.hook);assert.equal(row.shader.uniforms.stageRadius.value,radius);
   assert.deepEqual(row.shader.uniforms.stageCentre.value.toArray(),[radius/10,7]);}
 }
 viewing.dispose();for(const [object,material]of originalMaterials)assert.equal(object.material,material,'viewing restores originals');
 for(const row of rows.filter(r=>!['glass','viewing'].includes(r.label))){row.object.geometry.dispose();row.material.dispose();}
 lawn.dispose();waterSource.dispose();page.dispose();lm.lmTints.value.dispose();lm.lmRegions.value.dispose();
 haze.dispose();sky.dispose();disposeObject(model.root);
});
await test('clones of already haze-wrapped grass and water keep one key and original uniforms',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene(),cube=new THREE.CubeTexture(),haze=installStageHaze(scene,{cube});
 const lawn=new THREE.MeshStandardMaterial(),sourceWater=new THREE.MeshStandardMaterial({transparent:true,opacity:.4});
 const materials=[grassMaterial(lawn),surfaceMaterial(sourceWater).material],geometry=new THREE.BoxGeometry();
 const originals=materials.map(m=>new THREE.Mesh(geometry,m));scene.add(...originals);haze.prepare();
 const key=keyReader(renderer,scene),snapshots=originals.map(o=>({key:key(o),hook:o.material.onBeforeCompile,shader:assemble(o.material,renderer)}));
 for(const [i,original]of originals.entries()){
  const clone=original.clone();clone.material=original.material.clone();scene.add(clone);haze.prepare();
  assert.equal(clone.material.customProgramCacheKey(),original.material.customProgramCacheKey());
  assert.equal(key(clone),snapshots[i].key,'one actual r187 key for each material kind');
  assert.equal((clone.material.customProgramCacheKey().match(/\|stage-haze-1/g)||[]).length,1,'no nested haze suffix');
  const shader=assemble(clone.material,renderer);verifyHaze(shader,cube,i?'water clone':'grass clone');
  const uniform=i?'waterTime':'grassTime';assert.equal(shader.uniforms[uniform],snapshots[i].shader.uniforms[uniform]);
  assert.equal(original.material.onBeforeCompile,snapshots[i].hook,'preparing clone preserves original hook');
  assert.equal(key(original),snapshots[i].key,'preparing clone preserves original key');
  const otherScene=new THREE.Scene(),otherCube=new THREE.CubeTexture(),otherHaze=installStageHaze(otherScene,{cube:otherCube});
  const other=new THREE.Mesh(geometry,clone.material.clone());otherScene.add(other);otherHaze.prepare();otherHaze.set({radius:333});
  const otherShader=assemble(other.material,renderer);verifyHaze(otherShader,otherCube,'other scene');
  assert.equal(otherShader.uniforms.stageRadius.value,333);assert.notEqual(otherShader.uniforms.stageRing,snapshots[i].shader.uniforms.stageRing,'each scene binds its own ring');
  assert.notEqual(otherShader.uniforms.stageRadius,snapshots[i].shader.uniforms.stageRadius,'scene bindings stay independent');
  assert.equal(other.material.customProgramCacheKey(),original.material.customProgramCacheKey());
  other.material.dispose();otherCube.dispose();otherHaze.dispose();clone.material.dispose();
 }
 materials.forEach(m=>m.dispose());lawn.dispose();sourceWater.dispose();geometry.dispose();cube.dispose();haze.dispose();
});
await test('below-horizon haze samples the background cube view direction on canvas and composer',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene(),sky=createSky(renderer),haze=installStageHaze(scene,sky);
 const material=new THREE.MeshStandardMaterial(),mesh=new THREE.Mesh(new THREE.BoxGeometry(),material);scene.add(mesh);haze.prepare();
 const target=new THREE.WebGLRenderTarget(8,8,{type:THREE.HalfFloatType,colorSpace:THREE.LinearSRGBColorSpace});
 const chunk=THREE.ShaderChunk.fog_fragment;
 // Evaluate the installed chunk's direction/sampler expressions, with a CPU
 // cube lookup. The renderer double has no rasterizer or GLSL compiler.
 const viewExpr=chunk.match(/vec3 stageView = ([^;]+);/)[1]
   .replace(/-vec3\( viewMatrix\[0\]\.z, viewMatrix\[1\]\.z, viewMatrix\[2\]\.z \)/,'cameraDirection.clone()')
   .replace('vStageWorld - cameraPosition','vStageWorld.clone().sub(cameraPosition)');
 const viewRay=new Function('isOrthographic','cameraDirection','vStageWorld','cameraPosition',`return ${viewExpr};`);
 const rayExpr=chunk.match(/vec3 stageRay = ([^;]+);/)[1]
   .replace(/stageView \/ max\( stageLength, (\S+) \)/,'stageView.clone().divideScalar(max(stageLength,$1))');
 const ray=new Function('stageView','stageLength','max','vec3',`return ${rayExpr};`);
 assert.equal(chunk.match(/vec3 stageColour = ([^;]+);/)[1],'stageSkyColour( stageRay )');
 // A JS port of the installed stageSkyColour: 8 azimuths x depressions 0, 2, 6, 15, 40 degrees, bilinear.
 const bands=STAGE_RING_DEPRESSIONS;
 const ringColour=(ring,r)=>{
   let az=Math.atan2(r.z,r.x)/(Math.PI*2)*8;if(az<0)az+=8;
   const dep=Math.asin(Math.max(-1,Math.min(1,-r.y)))*180/Math.PI;
   let el=4;if(dep<=0)el=0;else for(let i=0;i<4;i++)if(dep<bands[i+1]){el=i+(dep-bands[i])/(bands[i+1]-bands[i]);break;}
   const a0=Math.floor(az),e0=Math.floor(el),e1=Math.min(e0+1,4),fa=az-a0,fe=el-e0,at=(a,e)=>ring[e*8+(a%8)];
   const lo=at(a0,e0).clone().lerp(at(a0+1,e0),fa),hi=at(a0,e1).clone().lerp(at(a0+1,e1),fa);return lo.lerp(hi,fe).toArray();
 };
 const vec3=(...v)=>new THREE.Vector3(...v),camera=vec3(3,80,20);
 for(const active of [null,target])for(const ortho of [false,true])for(const alt of [-1,-5,-20,-70,-90])for(const sunAlt of [60,4,-20]) {
   const a=alt*Math.PI/180,d=vec3(Math.cos(a)*.6,Math.sin(a),Math.cos(a)*.8);
   const state={sunDir:[Math.cos(sunAlt*Math.PI/180),Math.sin(sunAlt*Math.PI/180),0],overcast:.4};
   sky.update({...state,force:true});renderer.setRenderTarget(active);scene.onBeforeRender(renderer,scene,new THREE.PerspectiveCamera());
   const shader=assemble(material,renderer);assert.equal(shader.uniforms.stageCanvas.value,active?0:1);
   const v=viewRay(ortho,d,camera.clone().addScaledVector(d,100),camera),r=ray(v,v.length(),Math.max,vec3);
   assert.ok(r.distanceTo(d)<1e-12,'actual haze ray preserves downward elevation');
   haze.refresh();
   const rgb=ringColour(shader.uniforms.stageRing.value,r),background=sampleRadiance(d,state);
   // The ring is a gradient fit of the same radiance: close everywhere, exact on its nodes.
   rgb.forEach((v,i)=>assert.ok(Math.abs(v-background[i])<=Math.max(.03,.25*background[i]),`haze ${v} near background ${background[i]} at ${alt} deg`));
   for(const [a,e] of [[0,0],[3,2],[5,4]]){const n=new THREE.Vector3(...stageRingDirection(a,e));
     ringColour(shader.uniforms.stageRing.value,n).forEach((v,i)=>assert.ok(Math.abs(v-sampleRadiance(n.toArray(),state)[i])<1e-6,'ring node equals the sky'));}
 }
 const zero=ray(vec3(0,0,0),0,Math.max,vec3);assert.deepEqual(zero.toArray(),[0,-1,0]);
 target.dispose();mesh.geometry.dispose();material.dispose();haze.dispose();sky.dispose();
});
await test('untonemapped bulb haze follows canvas, half-float target and exposure by uniforms',()=>{
 const renderer=new Renderer();renderer.toneMapping=THREE.ACESFilmicToneMapping;
 const scene=new THREE.Scene(),cube=new THREE.CubeTexture(),haze=installStageHaze(scene,{cube});
 const material=new THREE.MeshBasicMaterial({color:'#ffffff',toneMapped:false,fog:true});
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(),material);scene.add(mesh);
 const target=new THREE.WebGLRenderTarget(8,8,{type:THREE.HalfFloatType,colorSpace:THREE.LinearSRGBColorSpace});
 const key=keyReader(renderer,scene),keys=new Map(),version=material.version;
 let previousShader;
 for(const exposure of [1,1.2,.7])for(const active of [null,target]){
  renderer.toneMappingExposure=exposure;renderer.setRenderTarget(active);
  haze.set({radius:120*exposure});scene.onBeforeRender(renderer,scene,new THREE.PerspectiveCamera());
  const shader=assemble(material,renderer),expanded=verifyHaze(shader,cube,'untonemapped bulb');
  assert.equal(shader.uniforms.stageCanvas?.value,active?0:1,'canvas tone mapping is independent of bulb toneMapped');
  assert.equal(shader.uniforms.stageExposure?.value,exposure,'shared exposure follows renderer');
  if(previousShader){assert.equal(shader.uniforms.stageCanvas,previousShader.uniforms.stageCanvas);assert.equal(shader.uniforms.stageExposure,previousShader.uniforms.stageExposure);}
  assert.ok(expanded.fragment.includes('stageCanvas')&&expanded.fragment.includes('stageExposure'));
  assert.ok(!THREE.ShaderChunk.fog_fragment.includes('#ifdef TONE_MAPPING'),'horizon conversion applies even without a bulb tone-mapping define');
  const label=active?'half-float':'canvas',current=key(mesh);if(keys.has(label))assert.equal(current,keys.get(label),label+' key stable across exposure/radius');else keys.set(label,current);
  assert.equal(material.toneMapped,false);assert.equal(material.version,version);previousShader=shader;
 }
 target.dispose();mesh.geometry.dispose();material.dispose();cube.dispose();haze.dispose();
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
