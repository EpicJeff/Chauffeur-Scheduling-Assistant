"""Cloud-shadow CPU fill, material assembly and mounted entry point; no browser/GL."""
import json
from pathlib import Path
import sys
from test_twin_yard_reuse_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
const {installCloudShadow,shadowTransmittance,CLOUD_SHADOW_GLSL}=await import(file('static/twin/sky/cloud_shadow.js'));
const {createCloudNoise,createCloudUniforms}=await import(file('static/twin/sky/clouds.js'));
const {createNoiseVolumeSampler,generateNoiseVolume,sampleVolume}=await import(file('static/twin/sky/cloud_noise.js'));
const {installStageHaze}=await import(file('static/twin/sky/stage_haze.js'));
const {lookAt}=await import(file('static/twin/sky/look.js'));
const {grassMaterial}=await import(file('static/twin/yard_grass.js'));
const {surfaceMaterial}=await import(file('static/twin/effects/water_surface.js'));
const {createWaterSimulation}=await import(file('static/twin/effects/water_sim.js'));
const {underwaterMaterial}=await import(file('static/twin/effects/underwater.js'));
const {sheetMaterial}=await import(file('static/twin/effects/sheet_material.js'));
const {waterMaterial}=await import(file('static/twin/effects/water_material.js'));
const {laminarMesh}=await import(file('static/twin/effects/laminar.js'));
const {buildVapour}=await import(file('static/twin/effects/vapour.js'));
const {patchLightmaps,lightmapUniforms}=await import(file('static/twin/bake/lightmap_material.js'));
const {reflectionMaterial}=await import(file('static/twin/reflection_probes.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {createViewing}=await import(file('static/twin/viewing.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {defaultStage}=await import(file('static/twin/stage_settings.js'));
registerHooks({load(url,ctx,next){
 if(url.endsWith('three.module.js?shadow-keys'))return {format:'module',shortCircuit:true,source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms,WebGLProgram};'};
 return next(url,ctx);
}});
const backend=await import(file('static/vendor/three-r187/three.module.js')+'?shadow-keys');
installStageHaze(new THREE.Scene(),{});
const chunksBefore={...THREE.ShaderChunk};
const expand=s=>s.replace(/#include\s+<([\w\d_]+)>/g,(_,n)=>{assert.equal(typeof THREE.ShaderChunk[n],'string',n);return expand(THREE.ShaderChunk[n]);});
const assemble=(m,r)=>{
 const lib=m.isShaderMaterial?m:THREE.ShaderLib[m.isMeshBasicMaterial?'basic':m.isMeshPhysicalMaterial?'physical':m.isMeshPhongMaterial?'phong':m.isMeshLambertMaterial?'lambert':m.isMeshToonMaterial?'toon':'standard'];
 const s={uniforms:m.isShaderMaterial?m.uniforms:THREE.UniformsUtils.clone(lib.uniforms),vertexShader:lib.vertexShader,fragmentShader:lib.fragmentShader};
 m.onBeforeCompile(s,r);return s;
};
const makeLights=()=>{
 const lights=Object.fromEntries(['sun','directional','point','spot','spotLightMap','rectArea','hemi','sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'].map(k=>[k,[]]));
 lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;return lights;
};
function programs(r) {
 r.state={buffers:{depth:{getReversed:()=>false}}};
 return backend.WebGLPrograms(r,{get:t=>t},{has:()=>false},{precision:'highp',getMaxPrecision:()=> 'highp'},{},{numPlanes:1,numIntersection:0});
}
// Run r187's actual source builder through shaderSource, stopping before link.
// This is source assembly, not a GPU compilation claim.
function programSource(r,cache,scene,object,lights) {
 Object.assign(backend.ShaderChunk,THREE.ShaderChunk);
 const shader=assemble(object.material,r),p=cache.getParameters(object.material,lights,[{}],scene,object,[]);
 Object.assign(p,shader);
 const sources={},stop=new Error('captured');
 const gl={VERTEX_SHADER:1,FRAGMENT_SHADER:2,createProgram:()=>({}),createShader:type=>({type}),
  shaderSource:(s,text)=>sources[s.type]=text,compileShader(){},attachShader(){},bindAttribLocation(){},linkProgram(){throw stop;}};
 const prior=r.getContext;r.getContext=()=>gl;
 try{backend.WebGLProgram(r,'cloud-shadow-test',p,{});}catch(e){if(e!==stop)throw e;}finally{r.getContext=prior;}
 assert.ok(sources[1]&&sources[2],'both final r187 shader sources assembled');return {...sources,key:cache.getProgramCacheKey(p),shader};
}
// Evaluate integer preprocessor conditions, retaining declarations in active
// branches. Count every declared uniform conservatively (even dead code),
// including sampler scalar slots and each array scalar's vector alignment.
function preprocess(source) {
 const macros=new Map(),stack=[];let active=true;const out=[];
 function evaluate(expr) {
  expr=expr.replace(/defined\s*(?:\(\s*(\w+)\s*\)|(\w+))/g,(_,a,b)=>macros.has(a||b)?'1':'0');
  for(let round=0;round<8;round++)expr=expr.replace(/\b[A-Za-z_]\w*\b/g,n=>macros.has(n)?macros.get(n)||'1':'0');
  assert.ok(/^[\d\s().+*/<>=!&|%~^?:-]*$/.test(expr),'integer preprocessor expression '+expr);
  return !!Function('return ('+expr+')')();
 }
 for(const line of source.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'').split('\n')) {
  const d=line.match(/^\s*#\s*(\w+)\s*(.*)/);if(!d){if(active)out.push(line);continue;}
  const [,command,arg]=d;
  if(['if','ifdef','ifndef'].includes(command)){
   const condition=command==='if'?active&&evaluate(arg):command==='ifdef'?macros.has(arg):!macros.has(arg);
   stack.push({parent:active,taken:!!condition});active=active&&condition;
  }else if(command==='elif'){const s=stack.at(-1),condition=s.parent&&!s.taken&&evaluate(arg);active=condition;s.taken||=condition;
  }else if(command==='else'){const s=stack.at(-1);active=s.parent&&!s.taken;s.taken=true;
  }else if(command==='endif'){active=stack.pop().parent;
  }else if(command==='define'&&active){const m=arg.match(/^(\w+)(.*)/);if(!m[2].startsWith('('))macros.set(m[1],m[2].trim());
  }else if(command==='undef'&&active)macros.delete(arg);
 }
 assert.equal(stack.length,0);return out.join('\n').replace(/\b[A-Za-z_]\w*\b/g,n=>macros.get(n)||n);
}
function uniformBudget(source) {
 const text=preprocess(source),types=new Map(),samplers=[];
 const fields=body=>{let count=0;for(const m of body.matchAll(/\b(\w+)\s+([^;{}]+);/g))count+=declaration(m[1],m[2]);return count;};
 function declaration(type,names) {
  const width=types.get(type)||(type.startsWith('mat')?Number(type[3]):1);
  return names.split(',').reduce((s,n)=>{const a=n.match(/\[\s*(\d+)\s*\]/);return s+width*(a?Number(a[1]):1);},0);
 }
 for(const m of text.matchAll(/struct\s+(\w+)\s*\{([^}]+)\};/g))types.set(m[1],fields(m[2]));
 let vectors=0;
 for(const m of text.matchAll(/uniform\s+(?:(?:lowp|mediump|highp)\s+)?(\w+)\s+([^;]+);/g)) {
  vectors+=declaration(m[1],m[2]);if(m[1].includes('sampler'))samplers.push(...m[2].split(',').map(n=>n.trim()));
 }
 return {vectors,samplers};
}
await test('lazy CPU texels match the real volume and periodic trilinear sampler',()=>{
 for(const detail of [false,true]) {
  const lazy=createNoiseVolumeSampler(8,{detail}),image={data:generateNoiseVolume(8,{detail}),width:8};
  for(const uv of [[0,0,0],[1,1,1],[-.37,.4,1.7],[.19,.72,.81]])
   sampleVolume(lazy.image,uv).forEach((v,i)=>assert.ok(Math.abs(v-sampleVolume(image,uv)[i])<1e-12));
 }
});
await test('clear, thick, horizon and below-ground light rays stay finite',()=>{
 const noise=createCloudNoise({size:8,detail:8});
 for(const coverage of [0,.4,1])for(const dir of [[0,1,0],[1,0,0],[0,-1,0]]){
  const t=shadowTransmittance([0,0,0],dir,{...noise,coverage,type:'nimbostratus'});
  assert.ok(Number.isFinite(t)&&t>=0&&t<=1);
  if(!coverage)assert.equal(t,1);
  if(coverage===1&&dir[1]>0)assert.ok(t<.5,'thick cloud blocks sunlight');
 }
 noise.dispose();
});
await test('sun integration uses the model extinction and six quadratic shell samples',()=>{
 const points=[],t=shadowTransmittance([0,0,0],[0,1,0],{coverage:1,type:'nimbostratus'},p=>{points.push(p);return .4;});
 assert.ok(Math.abs(t-Math.exp(-.4*1000*.0025))<1e-10);assert.equal(points.length,6);
 for(let j=0;j<6;j++)assert.ok(Math.abs(points[j][1]-(500+1000*((j/6)**2+((j+1)/6)**2)*.5))<1e-8);
});
await test('execute the shader lookup and light multiplier beneath and outside a cloud',()=>{
 const shadow=installCloudShadow(new THREE.Scene(),{uniforms:createCloudUniforms()});
 const body=name=>CLOUD_SHADOW_GLSL.match(new RegExp('float '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'))[1];
 const grid=Array.from({length:36},(_,i)=>Array.from({length:4},(_,c)=>(i*4+c)%12<6?.2:1));
 const bounds={x:-60,y:-60,z:1/120,w:1};
 const cell=new Function('p','cloudShadowGrid',body('cloudShadowCell').replace('int index=p.y*12+p.x, block=index/4;','const index=p.y*12+p.x, block=Math.trunc(index/4);'));
 const atBody=body('cloudShadowAt')
  .replace('vec2 p=clamp((world-cloudShadowBounds.xy)*cloudShadowBounds.z,0.0,1.0)*11.0;',
   'const p={x:clamp((world.x-cloudShadowBounds.x)*cloudShadowBounds.z)*11,y:clamp((world.y-cloudShadowBounds.y)*cloudShadowBounds.z)*11};')
  .replace('ivec2 a=ivec2(floor(p)),b=min(a+ivec2(1),ivec2(11));vec2 f=fract(p);',
   'const a={x:Math.floor(p.x),y:Math.floor(p.y)},b={x:Math.min(a.x+1,11),y:Math.min(a.y+1,11)},f={x:p.x-a.x,y:p.y-a.y};')
  .replace('float t=','const t=');
 const lookup=new Function('world','cloudShadowBounds','cloudShadowCell','ivec2','mix','min','clamp',atBody);
 const sample=world=>lookup(world,bounds,p=>cell(p,grid),(x,y)=>({x,y}),(a,b,t)=>a*(1-t)+b*t,Math.min,v=>Math.max(0,Math.min(1,v)));
 const forLight=new Function('direction','cloudShadowLight','vCloudWorld','dot','cloudShadowAt',body('cloudShadowForLight')
  .replace('vec3 luminary=mat3(viewMatrix)*cloudShadowLight;','const luminary=cloudShadowLight;'));
 const dot=(a,b)=>a.reduce((sum,v,i)=>sum+v*b[i],0),sun=[0,1,0];
 const statement=THREE.ShaderChunk.lights_fragment_begin.match(/directLight.color \*= cloudShadowForLight\(directLight.direction\);/)[0];
 const shade=new Function('directLight','cloudShadowForLight',statement+'return directLight.color;');
 for(const [x,expected]of [[-40,.2],[40,1],[0,.6],[-1e5,.2],[1e5,1]]) {
  assert.ok(Math.abs(sample({x,y:0})-expected)<1e-12,'packed bilinear lookup');
  assert.ok(Math.abs(shade({direction:sun,color:7},d=>forLight(d,sun,{xz:{x,y:0}},dot,sample))-7*expected)<1e-12,'sun term scaled once');
  assert.equal(shade({direction:[1,0,0],color:3},d=>forLight(d,sun,{xz:{x,y:0}},dot,sample)),3,'other directional light unchanged');
 }
 bounds.w=0;assert.equal(sample({x:-40,y:0}),1,'clear uniform bypass');shadow.dispose();
});
await test('packed grid is bilinear, bounded, throttled, drifting and selects moon at night',()=>{
 const scene=new THREE.Scene(),noise=createCloudNoise({size:16,detail:8}),uniforms=createCloudUniforms(noise),cloud={noise,uniforms};
 const shadow=installCloudShadow(scene,cloud);shadow.set({centre:[40,-20],radius:80});
 uniforms.cloudCoverage.value=.7;uniforms.cloudType.value=1;uniforms.cloudFade.value=1;
 assert.equal(shadow.frame(0),true);assert.ok(shadow.uniforms.cloudShadowGrid.value instanceof Float32Array,'flat: uniform4fv takes it as it stands');
 const first=Array.from(shadow.uniforms.cloudShadowGrid.value);
 assert.equal(first.length,144);assert.ok(new Set(first.map(v=>v.toFixed(4))).size>1);
 const b=shadow.uniforms.cloudShadowBounds.value;
 for(let z=0;z<12;z++)for(let x=0;x<12;x++)assert.ok(Math.abs(shadow.sample(b.x+x/11/b.z,b.y+z/11/b.z)-first[z*12+x])<1e-6);
 assert.ok(Math.abs(shadow.centre()-(first[65]+first[66]+first[77]+first[78])/4)<1e-6);
 assert.equal(shadow.sample(-1e9,-1e9),first[0]);assert.equal(shadow.sample(1e9,1e9),first[143]);
 uniforms.cloudOffset.value.x=4000;assert.equal(shadow.frame(.249),false);assert.equal(shadow.frame(.25),true);
 assert.notDeepEqual(Array.from(shadow.uniforms.cloudShadowGrid.value),first,'wind offset changes the field');
 shadow.set({sunDir:[0,-1,0],moonDir:[.6,.8,0]});shadow.frame(.5);
 assert.deepEqual(shadow.uniforms.cloudShadowLight.value.toArray(),[.6,.8,0]);
 uniforms.cloudCoverage.value=0;shadow.frame(.51);assert.equal(shadow.centre(),1);assert.equal(b.w,0);
 uniforms.cloudCoverage.value=1;uniforms.cloudType.value=4;shadow.frame(.75);assert.ok(shadow.centre()<.5);
 shadow.set({enabled:false});shadow.frame(.751);assert.equal(shadow.centre(),1);assert.equal(b.w,0);
 shadow.dispose();shadow.dispose();noise.dispose();
});
await test('real built-house lit-material census, baked lamps, viewing, grass, water and effects',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene(),noise=createCloudNoise({size:8,detail:8}),uniforms=createCloudUniforms(noise);
 const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{noise,uniforms});
 scene.environment=new THREE.Texture();
 const model=buildTwin(input.plan,{materials:{}},'high',{viewing:true});scene.add(model.root);
 const view={plan:input.plan,scene,roomLights:[],camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},renderer3:renderer};view.camera.position.set(0,30,30);
 const viewing=createViewing(view,model,()=>0,()=>{});
 const rows=[],add=(label,material,instance=false)=>{const geometry=new THREE.BoxGeometry();const o=instance?new THREE.InstancedMesh(geometry,material,1):new THREE.Mesh(geometry,material);scene.add(o);rows.push({label,object:o});return material;};
 for(const name of ['MeshStandardMaterial','MeshPhysicalMaterial','MeshPhongMaterial','MeshLambertMaterial','MeshToonMaterial'])add(name,new THREE[name]());
 const lawn=new THREE.MeshStandardMaterial(),water=new THREE.MeshPhysicalMaterial({transparent:true,opacity:.4});
 add('grass',grassMaterial(lawn),true);add('pool',surfaceMaterial(water).material);
 add('underwater',underwaterMaterial(new THREE.MeshStandardMaterial(),{height:0}).material);
 add('sheet',sheetMaterial());
 add('foam/fountain',waterMaterial());
 const laminar=laminarMesh([0,0,0,1,0,0,0,1,0],[0,0,1,0,0,1],[0,0,0],[0,1,2]);add('laminar/spa',laminar.material);
 const vapour=buildVapour({at:[0,0,0]},{plan:input.plan,origin:[0,0,0]});add('vapour',vapour.group.children[0].material);
 const lm=lightmapUniforms(1,4),page=new THREE.DataArrayTexture(new Uint8Array(64),4,4,1),baked=new THREE.MeshStandardMaterial();
 patchLightmaps([baked],{banks:[page]},lm);add('baked wall',baked);
 const kinds=new Set();model.root.traverse(o=>{if(o.material?.isMeshStandardMaterial){rows.push({label:'built '+o.material.name,object:o});kinds.add(o.material.name);}});
 assert.ok(kinds.has('glass')&&rows.some(r=>r.object.material.clippingPlanes?.length),'actual glass and viewing clones');
 haze.prepare();shadow.prepare();haze.prepare();shadow.prepare();
 const cache=programs(renderer),lights=makeLights();lights.directional=[{},{}];lights.hemi=[{}];
 for(const row of rows) {
  const m=row.object.material,s=assemble(m,renderer),v=expand(s.vertexShader),f=expand(s.fragmentShader);
  assert.equal(s.uniforms.cloudShadowGrid,shadow.uniforms.cloudShadowGrid,row.label+' shared grid');
  assert.equal((v.match(/varying vec3 vCloudWorld;/g)||[]).length,1,row.label+' one varying');
  assert.equal((f.match(/uniform vec4 cloudShadowGrid\[36\]/g)||[]).length,1,row.label+' one grid');
  assert.ok(f.includes('cloudShadowAt(vCloudWorld.xz)'),row.label+' world lookup');
  assert.ok(!/sampler\w*\s+cloudShadow/.test(f),row.label+' no new sampler');
  if(!m.isShaderMaterial)assert.ok(f.includes('directLight.color *= cloudShadowForLight(directLight.direction)'),row.label+' directional term only');
  else {assert.ok(f.includes('float cloudEffectLight=.18+max(0.0,light-.18)*cloudShadowAt(vCloudWorld.xz)'));assert.ok(f.includes('glow'),'lamp glow preserved');}
  row.key=cache.getProgramCacheKey(cache.getParameters(m,lights,[],scene,row.object,[]));row.version=m.version;
 }
 for(const [coverage,type,dir] of [[0,0,[0,1,0]],[.4,1,[.6,.8,0]],[1,4,[1,0,0]],[1,5,[0,-1,0]]]) {
  uniforms.cloudCoverage.value=coverage;uniforms.cloudType.value=type;uniforms.cloudFade.value=1;shadow.set({sunDir:dir,moonDir:[0,1,0]});shadow.frame(coverage+type);
  haze.prepare();shadow.prepare();
  for(const row of rows){const m=row.object.material;assert.equal(cache.getProgramCacheKey(cache.getParameters(m,lights,[],scene,row.object,[])),row.key,row.label+' stable real r187 key');assert.equal(m.version,row.version);}
 }
 const grass=rows.find(r=>r.label==='grass').object.material,clone=grass.clone();add('late grass clone',clone,true);shadow.prepare();haze.prepare();
 assert.equal(clone.customProgramCacheKey(),grass.customProgramCacheKey(),'no nested environment wrappers');
 assert.equal(assemble(clone,renderer).uniforms.cloudShadowGrid,shadow.uniforms.cloudShadowGrid);
 console.log('material census:',rows.length,'materials;', [...kinds].join(', '));
 viewing.dispose();shadow.dispose();haze.dispose();noise.dispose();
});
await test('full r187 heavy shaders retain sampler census and fit guaranteed 224 vectors',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene(),haze=installStageHaze(scene,{}),clouds={uniforms:createCloudUniforms()},shadow=installCloudShadow(scene,clouds);
 renderer.toneMapping=THREE.ACESFilmicToneMapping;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;scene.environment=new THREE.Texture();
 const lights=makeLights();lights.directional=[{},{}];lights.directionalShadowMap=[{}];lights.point=Array.from({length:4},()=>({}));lights.pointShadowMap=[{},{}];
 lights.spot=[{},{}];lights.spotShadowMap=[{}];lights.rectArea=[{}];lights.hemi=[{}];
 const source=new THREE.MeshPhysicalMaterial({map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),transparent:true,opacity:.4});
 const water=surfaceMaterial(source).material;reflectionMaterial(water,'water','pool');
 const body={polygon:[[0,0],[20,0],[20,20],[0,20]],height:0,sources:[{}]},simulation=createWaterSimulation(body);
 const moving=surfaceMaterial(source,body,{tier:'high',simulation});reflectionMaterial(moving.material,'water','pool');
 const wall=new THREE.MeshStandardMaterial({map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()});
 const lm=lightmapUniforms(1,8,{fixtures:true}),banks=Array.from({length:2},()=>new THREE.DataArrayTexture(new Uint8Array(64),4,4,1));patchLightmaps([wall],{banks},lm);
 const cache=programs(renderer),budget=[];
 for(const [label,material] of [['pool physical + four probes + mirror',water],['pool physical + eight ripple sources + field + probes + mirror',moving.material],['two-bank baked wall + eight baked lamps',wall]]) {
  const o=new THREE.Mesh(new THREE.BoxGeometry(),material);o.receiveShadow=true;scene.add(o);haze.prepare();shadow.prepare();
  const final=programSource(renderer,cache,scene,o,lights),after=uniformBudget(final[2]);
  const current={...THREE.ShaderChunk};Object.assign(THREE.ShaderChunk,chunksBefore);
  const before=programSource(renderer,cache,scene,o,lights),base=uniformBudget(before[2]);Object.assign(THREE.ShaderChunk,current);
  assert.deepEqual(after.samplers,base.samplers,label+' zero added texture units');
  assert.ok(after.vectors<=224,label+' conservative fragment vector budget '+after.vectors);
  budget.push({label,...after,addedVectors:after.vectors-base.vectors});
 }
 if(moving.uniforms.waterRippleClock) {
  moving.uniforms.rippleTime.value=12;moving.uniforms.waterBaseOpacity.value=.43;moving.uniforms.rippleStrength.value=[.1,.2,.3,.4,.5,.6,.7,.8];
  assert.deepEqual(moving.uniforms.waterRippleClock.value.toArray(),[12,.43]);
  Array.from(moving.uniforms.waterRippleStrength.value).forEach((v,i)=>assert.ok(Math.abs(v-moving.uniforms.rippleStrength.value[i])<1e-6,'eight original driver values reach packed uniforms'));
 }
 console.log('UNIFORM_BUDGET',JSON.stringify(budget));simulation.dispose();shadow.dispose();haze.dispose();
});
await test('late clones bind each scene once; Basic and Unlit retain a valid world varying',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene(),other=new THREE.Scene();
 const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()});
 const haze2=installStageHaze(other,{}),shadow2=installCloudShadow(other,{uniforms:createCloudUniforms()});
 const grass=grassMaterial(new THREE.MeshStandardMaterial()),geometry=new THREE.BoxGeometry();scene.add(new THREE.Mesh(geometry,grass));
 haze.prepare();shadow.prepare();const key=grass.customProgramCacheKey();
 const clone=grass.clone();other.add(new THREE.Mesh(geometry,clone));
 for(let i=0;i<5;i++){haze2.prepare();shadow2.prepare();}
 assert.equal(clone.customProgramCacheKey(),key);
 const a=assemble(grass,renderer),b=assemble(clone,renderer);
 assert.equal(b.uniforms.cloudShadowGrid,shadow2.uniforms.cloudShadowGrid);assert.notEqual(b.uniforms.cloudShadowGrid,a.uniforms.cloudShadowGrid);
 assert.notEqual(b.uniforms.stageRing,a.uniforms.stageRing);assert.equal(b.uniforms.grassTime,a.uniforms.grassTime);
 const basic=new THREE.MeshBasicMaterial(),mesh=new THREE.Mesh(geometry,basic);other.add(mesh);haze2.prepare();shadow2.prepare();
 const shader=assemble(basic,renderer),v=expand(shader.vertexShader);
 assert.equal((v.match(/varying vec3 vCloudWorld;/g)||[]).length,1,'Basic declares the position used by worldpos_vertex');
 assert.ok(v.includes('vCloudWorld=(modelMatrix*cloudWorld).xyz;'));assert.ok(!('cloudShadowGrid' in shader.uniforms),'unlit material has no solar multiplier');
 shadow2.dispose();haze2.dispose();shadow.dispose();haze.dispose();geometry.dispose();grass.dispose();clone.dispose();basic.dispose();
});
await test('mounted low-tier weather, editor clear look, centre scalar and no double dimming',async()=>{
 const prior=location.search;location.search='?test=1';
 const mount=async(editor=false)=>{const el=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(el);}return mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false,site:{lat:40,lon:-75,front_bearing_deg:180,source:'home_location',timezone:'America/New_York'}});};
 let viewer,editor;
 try {
  viewer=await mount();viewer.setClock('2026-06-21T17:00:00Z');viewer.setTime('day');
  viewer.live={peek:()=>({'weather.home':{state:'rainy',attributes:{cloud_coverage:100}}}),stale:()=>false,draw(){},stop(){}};
  viewer.clouds.uniforms.cloudFade.value=1;viewer.setTime('now');viewer.cloudShadow.frame(performance.now()/1000+1);
  assert.ok(viewer.cloudShadow.centre()<.5,'real mounted weather fills low-tier shadows');
  assert.equal(viewer.scene.getObjectByName('real-sun').intensity,3,'directional intensity is not also globally dimmed');
  const look=lookAt(60,undefined,{overcast:1,sunTransmittance:viewer.cloudShadow.centre()});
  assert.equal(look.sun,3*viewer.cloudShadow.centre());assert.equal(look.ambient,1.8*1.35);
  viewer.live={peek:()=>null,stale:()=>true,draw(){},stop(){}};viewer.setTime('day');assert.equal(viewer.cloudShadow.centre(),1,'stale weather clears immediately');
  editor=await mount(true);editor.live={peek:()=>({'weather.home':{state:'rainy'}}),stale:()=>false,draw(){},stop(){}};editor.clouds.uniforms.cloudFade.value=1;editor.setTime('now');
  assert.equal(editor.cloudShadow.centre(),1);assert.equal(editor.clouds.uniforms.cloudCoverage.value,0);
  const stage=defaultStage(input.plan);console.log('DEFAULT_STAGE',JSON.stringify({...stage,cellMetres:stage.radius*.3048*3/11}));
 }finally{viewer?.dispose();editor?.dispose();location.search=prior;}
});
await test('GPU-noise CPU fill cost, cache reuse and bounded 250 ms cadence',()=>{
 const uniforms=createCloudUniforms(),shadow=installCloudShadow(new THREE.Scene(),{uniforms});
 uniforms.cloudCoverage.value=.7;uniforms.cloudType.value=1;uniforms.cloudFade.value=1;
 const stage=defaultStage(input.plan);shadow.set({centre:stage.centre.map(v=>v*.3048),radius:stage.radius*.3048,sunDir:[.6,.8,0]});
 const timings=[];
 for(let i=0;i<60;i++){uniforms.cloudOffset.value.x=i*4.5;const start=performance.now();assert.equal(shadow.frame(i*.25),true);timings.push(performance.now()-start);}
 const mean=timings.reduce((s,v)=>s+v,0)/timings.length;
 console.log('FILL_COST',JSON.stringify({firstMs:timings[0],meanMs:mean,maxMs:Math.max(...timings),averagePer60HzFrameMs:mean/15,cacheBytes:(128**3+32**3)*5}));
 assert.ok(mean/15<1,'CPU fill under 1 ms per frame on average');shadow.dispose();
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': str(ROOT), 'plan': plan}, timeout=180)
    print(output)
    sys.exit(code or 0)
