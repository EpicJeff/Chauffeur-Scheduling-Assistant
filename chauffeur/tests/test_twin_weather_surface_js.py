"""Weather surfaces: execute hooks and scalar GLSL, real r187 sources; no browser/GL."""
import json
from pathlib import Path
import sys

from test_twin_cloud_shadow_js import DRIVER as CLOUD_DRIVER
from test_twin_tree_once_js import PREFIX as TREE_PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
# Reuse the actual r187 source builder, preprocessor and conservative census.
PREFIX = CLOUD_DRIVER.split("await test('lazy CPU texels")[0]
DRIVER = PREFIX + r"""
const {existsSync}=await import('node:fs');
const path=file('static/twin/sky/weather_surface.js');
assert.ok(existsSync(new URL(path)), 'Task 3 weather surface module exists');
const {installWeatherSurface,WEATHER_GLSL}=await import(path);
const {kitMaterial}=await import(file('static/twin/twin_library.js'));
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
const dummyShadow=installCloudShadow(new THREE.Scene(),{uniforms:createCloudUniforms()});
const weatherBefore={...THREE.ShaderChunk};
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const mix=(a,b,t)=>a+(b-a)*t,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const smoothstep=(a,b,v)=>{const t=clamp((v-a)/(b-a),0,1);return t*t*(3-2*t);};
// Execute the scalar functions actually installed in GLSL, not a CPU duplicate.
const scalar=name=>{
 const m=WEATHER_GLSL.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));
 assert.ok(m,name+' GLSL function');
 return new Function('mix','clamp','smoothstep',`return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(mix,clamp,smoothstep);
};
await test('one packed vector: ground units, bounded rate/phase, neutral and rain-only ripples',()=>{
 const layer=installWeatherSurface(new THREE.Scene());
 assert.deepEqual(Object.keys(layer.uniforms),['weatherSurface']);
 for(const precip of ['none','snow','hail','rain','mix']){
  layer.update({wetness:1,snow_cm:8,puddles:1,rate:1,precip},2);
  const u=layer.uniforms.weatherSurface.value;
  assert.deepEqual(u.toArray().slice(0,3),[1,1,1]);
  assert.equal(Math.floor(u.w)/255,['rain','mix'].includes(precip)?1:0);
  close(u.w-Math.floor(u.w),.5);
 }
 for(const seconds of [0,3.999,4,1e10,NaN]){
  layer.update({wetness:NaN,snow_cm:Infinity,puddles:-1,rate:Infinity,precip:'rain'},seconds);
  assert.ok(layer.uniforms.weatherSurface.value.toArray().every(Number.isFinite));
 }
 for(const seconds of [3.999999999,4,7.999999999]){
  layer.update({precip:'rain',rate:1},seconds);
  const uploaded=new Float32Array(layer.uniforms.weatherSurface.value.toArray());
  assert.equal(Math.floor(uploaded[3]),255,'GPU float rounding never spills phase into rain rate');
 }
 layer.update({wetness:1,snow_cm:8,puddles:1,rate:1,precip:'rain',neutral:true},2);
 assert.deepEqual(layer.uniforms.weatherSurface.value.toArray(),[0,0,0,0]);layer.dispose();
});
await test('executed wet and snow/puddle curves preserve identity and slope rules',()=>{
 const wet=scalar('weatherWetScale'),rough=scalar('weatherRoughness');
 close(wet(1,0,1),.65);assert.ok(wet(.01,0,1)>.9);assert.ok(wet(1,1,1)>.9);
 close(wet(.3,0,0),1);close(rough(.8,1,0,0),.15);close(rough(.8,1,1,0),.03);
 close(rough(.8,1,1,1),.7);
 const snow=scalar('weatherSnow'),puddle=scalar('weatherPuddle');
 for(const y of [-1,0,.55])close(snow(y,1,.5),0);
 close(snow(.85,1,.5),1);close(snow(1,0,.5),0);
 assert.ok(snow(.7,1,.5)>0&&snow(.7,1,.5)<1);
 for(const y of [-1,.55,.85,.9])close(puddle(y,1,.5),0);
 close(puddle(1,0,.5),0);assert.ok(puddle(1,1,.5)>.99);
 assert.ok(puddle(1,.5,.1)>puddle(1,.5,.9),'world noise breaks the puddle edge');
 assert.ok(snow(1,.5,.1)>snow(1,.5,.9),'world noise breaks the snow edge');
});
await test('built house and household: every lit kind, grass, baked lamps, water, effects and viewing clones',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene();renderer.toneMapping=THREE.ACESFilmicToneMapping;
 const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installWeatherSurface(scene);
 scene.environment=new THREE.Texture();
 const model=buildTwin(input.plan,{materials:{}},'high',{viewing:true});scene.add(model.root);
 // Scene-linear diffuse luminance at unit irradiance (Lambert, 1/pi), using
 // actual fixture material colours; texture modulation/specular are excluded.
 const luminance=c=>c[0]*.2126+c[1]*.7152+c[2]*.0722;
 for(const role of ['wall','lawn']){
  let material;model.root.traverse(o=>{for(const m of [].concat(o.material||[]))if(!material&&m.isMeshStandardMaterial&&(m.name===(role==='wall'?'siding':role)||m.userData.materialRole===role))material=m;});
  if(role==='lawn')material=kitMaterial('lawn',{materials:{lawn:{...input.kit.materials.lawn,...input.plan.materials?.lawn}}},'high');
  assert.ok(material,role+' measured material');
  if(material){const rgb=material.color.toArray(),dry=luminance(rgb)/Math.PI,scale=scalar('weatherWetScale')(luminance(rgb),material.metalness,1);
   console.log('WEATHER_WET_LUMINANCE',JSON.stringify({fixture:input.label,role,rgb,dry,wet:dry*scale,darkerPercent:(1-scale)*100,roughnessDry:material.roughness,roughnessWet:scalar('weatherRoughness')(material.roughness,1,0,0)}));}
  if(role==='lawn')material.dispose();
 }
 const view={plan:input.plan,scene,roomLights:[],camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},renderer3:renderer};view.camera.position.set(0,30,30);
 const viewing=createViewing(view,model,()=>0,()=>{}),rows=[];
 const add=(label,material,instance=false)=>{const o=instance?new THREE.InstancedMesh(new THREE.BoxGeometry(),material,1):new THREE.Mesh(new THREE.BoxGeometry(),material);scene.add(o);rows.push({label,object:o});return material;};
 for(const name of ['MeshStandardMaterial','MeshPhysicalMaterial','MeshLambertMaterial','MeshPhongMaterial','MeshToonMaterial'])add(name,new THREE[name]());
 add('shallow roof',new THREE.MeshStandardMaterial({name:'roof'}));
 const roleRoof=new THREE.MeshStandardMaterial({name:'household roof finish'});roleRoof.userData.materialRole='roof';add('roof role',roleRoof);
 add('grass',grassMaterial(new THREE.MeshStandardMaterial()),true);
 add('pool',surfaceMaterial(new THREE.MeshPhysicalMaterial()).material);
 add('spa',surfaceMaterial(new THREE.MeshPhysicalMaterial()).material);
 add('underwater',underwaterMaterial(new THREE.MeshStandardMaterial(),{height:0}).material);
 add('sheet',sheetMaterial());add('foam/fountain',waterMaterial());
 add('laminar',laminarMesh([0,0,0,1,0,0,0,1,0],[0,0,1,0,0,1],[0,0,0],[0,1,2]).material);
 add('vapour',buildVapour({at:[0,0,0]},{plan:input.plan,origin:[0,0,0]}).group.children[0].material);
 const lm=lightmapUniforms(1,4),baked=new THREE.MeshStandardMaterial();
 patchLightmaps([baked],{banks:[new THREE.DataArrayTexture(new Uint8Array(64),4,4,1)]},lm);add('baked wall',baked);
 model.root.traverse(o=>{if(o.material?.isMeshStandardMaterial)rows.push({label:'built '+o.material.name,object:o});});
 assert.ok(rows.some(r=>r.object.material.clippingPlanes?.length),'real viewing clones');
 const cache=programs(renderer),lights=makeLights();lights.directional=[{},{}];lights.hemi=[{}];
 haze.prepare();shadow.prepare();layer.prepare();
 const census=[];
 for(const row of rows){
  const m=row.object.material,final=programSource(renderer,cache,scene,row.object,lights),f=preprocess(final[2]),v=preprocess(final[1]);
  assert.equal(final.shader.uniforms.weatherSurface,layer.uniforms.weatherSurface,row.label+' scene binding');
  assert.equal((f.match(/uniform vec4 weatherSurface;/g)||[]).length,1,row.label+' one vector');
  assert.equal((v.match(/(?:varying|out) vec3 vWeatherWorld;/g)||[]).length,1,row.label+' one world varying');
  assert.ok(!/sampler\w*\s+weather/.test(f));
  const current={...THREE.ShaderChunk};Object.assign(THREE.ShaderChunk,weatherBefore);
  const base=uniformBudget(programSource(renderer,cache,scene,row.object,lights)[2]);Object.assign(THREE.ShaderChunk,current);
  assert.deepEqual(uniformBudget(final[2]).samplers,base.samplers,row.label+' expanded sampler census');
  if(['pool','spa','sheet'].includes(row.label)){
   assert.ok(f.includes('weatherRipple(vWeatherWorld.xz)'),row.label+' rain ripples');
   assert.ok(!f.includes('diffuseColor.rgb *= weatherWetScale'),row.label+' no wet/snow/puddle changes');
  }else if(row.label==='underwater'||row.label==='vapour'){
   assert.ok(!f.includes('normal +=')||!f.includes('weatherRipple(vWeatherWorld.xz)'),'submerged/vapour no rain surface');
  }else if(!m.isShaderMaterial){
   assert.ok(f.includes('diffuseColor.rgb *= weatherWetScale'),row.label+' wet');
   assert.ok(f.includes('weatherSnow(weatherUp'),row.label+' snow');
   if(m.name==='roof'||m.userData.materialRole==='roof'){
    // A 4:12 roof has normal.y=.949 and passes .9; slope alone cannot exclude it.
    assert.ok(!f.includes('weatherPuddle(weatherUp'),row.label+' roof never collects puddles');
   }
   if(row.label==='grass')assert.ok(f.indexOf('roughnessFactor = mix(.96, .53, vGrass.x)')<f.indexOf('roughnessFactor=weatherRoughness'),'weather follows grass roughness override');
   if(row.label==='baked wall'){
    assert.ok(f.indexOf('diffuseColor.rgb *= weatherWetScale')<f.indexOf('material.diffuseColor ='),'weather albedo enters BRDF before baked lamp terms');
    assert.ok(f.includes('lmIncident.direction = lmDir')&&f.includes('lmTints'),'baked light path retained');
   }
  }
  row.key=final.key;row.version=m.version;census.push({label:row.label,...uniformBudget(final[2])});
 }
 assert.notEqual(rows.find(r=>r.label==='shallow roof').key,rows.find(r=>r.label==='MeshStandardMaterial').key,'roof and ordinary surfaces have distinct structural keys');
 for(const precip of ['none','rain','snow','mix','hail'])for(const neutral of [false,true]){
  layer.update({wetness:1,snow_cm:8,puddles:1,precip,rate:1,neutral},13.7);layer.prepare();
  for(const row of rows){assert.equal(programSource(renderer,cache,scene,row.object,lights).key,row.key);assert.equal(row.object.material.version,row.version);}
 }
 const grass=rows.find(r=>r.label==='grass').object.material,clone=add('late grass clone',grass.clone(),true);
 layer.prepare();haze.prepare();shadow.prepare();assert.equal(clone.customProgramCacheKey(),grass.customProgramCacheKey());
 const other=new THREE.Scene(),otherLayer=installWeatherSurface(other);other.add(new THREE.Mesh(new THREE.BoxGeometry(),clone));otherLayer.prepare();
 assert.equal(assemble(clone,renderer).uniforms.weatherSurface,otherLayer.uniforms.weatherSurface);
 console.log('WEATHER_CENSUS',JSON.stringify({fixture:input.label,count:rows.length,kinds:[...new Set(census.map(r=>r.label))]}));
 otherLayer.dispose();viewing.dispose();layer.dispose();shadow.dispose();haze.dispose();
});
await test('real r187 heavy stress shaders add zero samplers and exactly one vector, at most 224',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene(),haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installWeatherSurface(scene);
 renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;scene.environment=new THREE.Texture();
 const lights=makeLights();lights.directional=[{},{}];lights.directionalShadowMap=[{}];lights.point=Array.from({length:4},()=>({}));lights.pointShadowMap=[{},{}];lights.spot=[{},{}];lights.spotShadowMap=[{}];lights.rectArea=[{}];lights.hemi=[{}];
 const source=new THREE.MeshPhysicalMaterial({map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),transparent:true,opacity:.4});
 const water=surfaceMaterial(source).material;reflectionMaterial(water,'water','pool');
 const body={polygon:[[0,0],[20,0],[20,20],[0,20]],height:0,sources:[{}]},simulation=createWaterSimulation(body);
 const moving=surfaceMaterial(source,body,{tier:'high',simulation});reflectionMaterial(moving.material,'water','pool');
 const wall=new THREE.MeshStandardMaterial({map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()});
 patchLightmaps([wall],{banks:Array.from({length:2},()=>new THREE.DataArrayTexture(new Uint8Array(64),4,4,1))},lightmapUniforms(1,8,{fixtures:true}));
 const cache=programs(renderer),budgets=[];
 for(const [label,material]of [['pool probes mirror',water],['pool eight sources field probes mirror',moving.material],['two-bank wall eight lamps',wall]]){
  const o=new THREE.Mesh(new THREE.BoxGeometry(),material);o.receiveShadow=true;scene.add(o);haze.prepare();shadow.prepare();layer.prepare();
  const after=uniformBudget(programSource(renderer,cache,scene,o,lights)[2]);
  const current={...THREE.ShaderChunk};Object.assign(THREE.ShaderChunk,weatherBefore);
  const base=uniformBudget(programSource(renderer,cache,scene,o,lights)[2]);Object.assign(THREE.ShaderChunk,current);
  assert.deepEqual(after.samplers,base.samplers,label+' no sampler');
  assert.equal(after.vectors-base.vectors,1,label+' packed budget');assert.ok(after.vectors<=224,label+' '+after.vectors);
  budgets.push({label,before:base.vectors,after:after.vectors,samplers:after.samplers.length});
 }
 assert.equal(budgets[1].before,223);assert.equal(budgets[1].after,224);
 console.log('WEATHER_BUDGET',JSON.stringify(budgets));simulation.dispose();layer.dispose();shadow.dispose();haze.dispose();
});
await test('mounted view reads replacement weather at render time and neutral restores zero',async()=>{
 const prior=location.search;location.search='?test=1';let viewer,editor;
 const mount=async(neutral=false)=>{const el=new Element();if(neutral){const shell=new Element();shell.className='editor-shell';shell.append(el);}return mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});};
 try{
  viewer=await mount();assert.ok(viewer.weatherSurface,'installed at mount');
  viewer.setWeatherPreview('rain');let u=viewer.weatherSurface.uniforms.weatherSurface.value;
  assert.equal(u.x,1);assert.equal(u.z,1);assert.ok(Math.floor(u.w)>0);
  const old=viewer.weather;viewer.setWeatherPreview('snow');assert.notEqual(viewer.weather,old);assert.equal(u.y,1);assert.equal(u.z,0);assert.equal(Math.floor(u.w),0);
  viewer.setWeatherPreview('clear');assert.deepEqual(u.toArray().slice(0,3),[0,0,0]);
  editor=await mount(true);assert.deepEqual(editor.weatherSurface.uniforms.weatherSurface.value.toArray(),[0,0,0,0]);
  editor.setWeatherPreview('rain');assert.equal(editor.weatherSurface.uniforms.weatherSurface.value.x,1);
  editor.setWeatherPreview(null);assert.deepEqual(editor.weatherSurface.uniforms.weatherSurface.value.toArray(),[0,0,0,0]);
 }finally{viewer?.dispose();editor?.dispose();location.search=prior;}
});
dummyShadow.dispose();finish();
"""

TREE_DRIVER = TREE_PREFIX + r"""
const THREE=await import('three');
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {installWeatherSurface,WEATHER_GLSL}=await import(file('static/twin/sky/weather_surface.js'));
const {installPlantWind}=await import(file('static/twin/sky/wind.js'));
const {installStageHaze,stageFade}=await import(file('static/twin/sky/stage_haze.js'));
await test('actual vendored oak and shrub leaves and branches receive snow after wind, including clones',async()=>{
 const plan={buildings:[],site:{planting:[{id:'tree',preset:'Oak Small',seed:7,height:15,at:[0,0]},{id:'shrub',preset:'Bush 1',height:3,at:[10,0]}]}};
 const {group}=await buildYard(plan,{materials:{}},'high',{viewing:true});
 const scene=new THREE.Scene();scene.add(group);
 const wind=installPlantWind(scene,{tier:'high'}),layer=installWeatherSurface(scene);wind.prepare();layer.prepare();
 const expand=s=>s.replace(/#include\s+<([\w\d_]+)>/g,(_,n)=>expand(THREE.ShaderChunk[n]));
 const materials=new Set();scene.traverse(o=>{for(const m of [].concat(o.material||[]))if(m.userData.plantWind)materials.add(m);});
 assert.ok([...materials].some(m=>m.userData.plantWind==='leaves'));assert.ok([...materials].some(m=>m.userData.plantWind==='branches'));
 for(const m of materials){
  const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};m.onBeforeCompile(shader,{});
  assert.ok(expand(shader.fragmentShader).includes('weatherSnow(weatherUp'));assert.ok(expand(shader.vertexShader).includes('plantHeight'));
  assert.equal(shader.uniforms.weatherSurface,layer.uniforms.weatherSurface);
  const clone=m.clone();scene.add(new THREE.Mesh(new THREE.BoxGeometry(),clone));wind.prepare();layer.prepare();assert.equal(clone.customProgramCacheKey(),m.customProgramCacheKey());
 }
 layer.update({snow_cm:8},12);assert.equal(layer.uniforms.weatherSurface.value.y,1);
 layer.dispose();wind.dispose();group.userData.releasePlants?.();
});
await test('actual leaf fragment scalar port: snow cover 1 plus fog 1 is finite on both card faces',async()=>{
 const plan={buildings:[],site:{planting:[{id:'tree',preset:'Oak Small',seed:7,height:15,at:[0,0]}]}};
 const {group}=await buildYard(plan,{materials:{}},'high',{viewing:true}),scene=new THREE.Scene();scene.add(group);scene.updateMatrixWorld(true);
 const haze=installStageHaze(scene,{}),wind=installPlantWind(scene),layer=installWeatherSurface(scene);
 haze.set({centre:[0,0],radius:100,fog:1});haze.prepare();wind.prepare();layer.prepare();layer.update({snow_cm:8,fog:1},0);
 const mix=(a,b,t)=>a+(b-a)*t,smoothstep=(a,b,v)=>{const t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
 const scalar=name=>{const m=WEATHER_GLSL.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));return new Function('mix','smoothstep',`return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(mix,smoothstep);};
 const snow=scalar('weatherSnow'),wet=scalar('weatherWetScale'),rough=scalar('weatherRoughness');
 let samples=0;
 scene.traverse(o=>{if(o.material?.userData.plantWind!=='leaves')return;
  const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};o.material.onBeforeCompile(shader,{});
  assert.equal(shader.uniforms.weatherSurface.value.y,1);assert.ok(Math.abs(shader.uniforms.stageRadius.value-15)<1e-8);
  const expand=s=>s.replace(/#include\s+<([\w\d_]+)>/g,(_,n)=>expand(THREE.ShaderChunk[n]));
  const fragment=expand(shader.fragmentShader);
  assert.ok(fragment.includes('weatherSnow(weatherUp')&&fragment.includes('normal *= faceDirection'));
  assert.ok(fragment.includes('mix( gl_FragColor.rgb, stageColour, stageFade )'));
  const normals=o.geometry.attributes.normal,positions=o.geometry.attributes.position,matrix=new THREE.Matrix3().getNormalMatrix(o.matrixWorld);
  for(let i=0;i<normals.count;i++)for(const face of [-1,1]){
   const n=new THREE.Vector3().fromBufferAttribute(normals,i).applyMatrix3(matrix).normalize().multiplyScalar(face);
   const position=new THREE.Vector3().fromBufferAttribute(positions,i).applyMatrix4(o.matrixWorld);
   for(const edge of [0,.5,1]){
    const cover=snow(n.y,1,edge),r=rough(.9,0,0,cover);
    assert.ok(Number.isFinite(r)&&r>=0);
    // Scalar port of weather albedo -> non-negative diffuse irradiance/PI ->
    // output conversion -> radial fog mix. Vertex sway only moves positions.
    const rgb=[.025,.12,.01].map((c,k)=>mix(c*wet(.09,0,0),[.85,.87,.9][k],cover));
    for(const fade of [stageFade([position.x,position.z],[0,0],15),stageFade([17.625,0],[0,0],15),1])
    for(const irradiance of [0,.002,.5,2])for(const [k,c] of rgb.entries()){
     const lit=c*irradiance/Math.PI;
     const output=lit<=.0031308?lit*12.92:1.055*Math.pow(Math.max(lit,0),1/2.4)-.055;
     const result=mix(output,[.7,.72,.75][k],fade);
     assert.ok(Number.isFinite(result)&&result>=0,`${i}/${face}/${cover}/${fade}/${result}`);samples++;
    }
   }
  }
 });
 assert.ok(samples>1000);console.log('WEATHER_LEAF_SNOW_FOG_SCALARS',samples);
 layer.dispose();wind.dispose();haze.dispose();group.userData.releasePlants?.();
});finish();
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    household = flatten(assemble(fixture)[0])
    poolhouse = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    failed = False
    for label, plan in [('poolhouse', poolhouse), ('household', household)]:
        code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'label': label, 'kit': kit}, timeout=180)
        print(output)
        failed |= bool(code)
    code, output = run_node(TREE_DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    failed |= bool(code)
    sys.exit(1 if failed else 0)
