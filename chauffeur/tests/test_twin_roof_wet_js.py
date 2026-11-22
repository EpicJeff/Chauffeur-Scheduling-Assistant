"""Wet roof rivulets and persistent beads: real r187 assembly and executed GLSL math."""
import json
from pathlib import Path
import sys

from test_twin_weather_surface_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const {installWeatherSurface,WEATHER_GLSL}=await import(file('static/twin/sky/weather_surface.js'));
const close=(a,b,eps=1e-6)=>assert.ok(Math.abs(a-b)<=eps,`${a} != ${b}`);
const mix=(a,b,t)=>a+(b-a)*t,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const smoothstep=(a,b,v)=>{const t=clamp((v-a)/(b-a),0,1);return t*t*(3-2*t);};
const fract=x=>x-Math.floor(x);
const v2=(x,y=x)=>({x,y}),v3=(x,y=x,z=x)=>({x,y,z});
const add2=(a,b)=>v2(a.x+b.x,a.y+b.y),sub2=(a,b)=>v2(a.x-b.x,a.y-b.y),mul2=(a,s)=>v2(a.x*s,a.y*s);
const dot2=(a,b)=>a.x*b.x+a.y*b.y,dot3=(a,b)=>a.x*b.x+a.y*b.y+a.z*b.z;

// Check balanced braces and no duplicate declarations within any GLSL block scope.
function checkGlslScopes(source,label){
 const text=source.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
 const stack=[new Set()];
 for(const raw of text.split('\n')){
  const line=raw.trim();
  if(!line||line.startsWith('#'))continue;
  for(const ch of line){
   if(ch==='{')stack.push(new Set());
   else if(ch==='}'){assert.ok(stack.length>1,label+' unbalanced }');stack.pop();}
  }
  const m=line.match(/^(?:float|int|bool|vec[234]|mat[234])\s+([A-Za-z_]\w*)\s*(?:=|;)/);
  if(m&&!line.includes('(')&&stack.length>1){
   const scope=stack.at(-1);
   assert.ok(!scope.has(m[1]),`${label}: duplicate declaration of ${m[1]}`);
   scope.add(m[1]);
  }
 }
 assert.equal(stack.length,1,label+' unbalanced {');
}

// Build live JS evaluators directly from the installed WEATHER_GLSL roof functions.
function buildRoofEvaluators(){
 const roofGlsl=preprocess('#define WEATHER_SURFACE_ROOF\n'+WEATHER_GLSL);
 const body=(type,name)=>{
  const m=roofGlsl.match(new RegExp(type+' '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'));
  assert.ok(m,name+' found in roof GLSL');return m[1];
 };
 const scalar=name=>{
  const m=roofGlsl.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));
  assert.ok(m,name);
  return new Function('mix','clamp','smoothstep','max','abs','sin','step',
   `return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(mix,clamp,smoothstep,Math.max,Math.abs,Math.sin,(a,v)=>v<a?0:1);
 };
 const ringHash=new Function('p','fract',body('vec3','weatherRingHash')
  .replace('vec3 q=fract(vec3(p.x,p.y,p.x)*vec3(.1031,.1030,.0973));','let q={x:fract(p.x*.1031),y:fract(p.y*.1030),z:fract(p.x*.0973)};')
  .replace('q+=dot(q,q.yxz+33.33);','const d=q.x*(q.y+33.33)+q.y*(q.x+33.33)+q.z*(q.z+33.33);q={x:q.x+d,y:q.y+d,z:q.z+d};')
  .replace('return fract((q.xxy+q.yzz)*q.zyx);','return {x:fract((q.x+q.y)*q.z),y:fract((q.x+q.z)*q.y),z:fract((q.y+q.z)*q.x)};'));
 const hash=p=>ringHash(p,fract);
 const dropRadius=scalar('weatherDropRadius'),dropDensity=scalar('weatherDropDensity'),spotFn=scalar('weatherSpot');
 const dropCell=new Function('id','cellSize','up','weatherRingHash','weatherDropRadius','weatherDropDensity','fract',body('vec4','weatherDropCell')
  .replace('vec3 random=','let random=').replace('float radius=','let radius=')
  .replace('vec2 centre=vec2(radius)+random.xy*(1.0-2.0*radius);','let centre={x:radius+random.x*(1-2*radius),y:radius+random.y*(1-2*radius)};')
  .replace('float arrival=','let arrival=')
  .replace('vec4(centre,radius,fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival)','({x:centre.x,y:centre.y,z:radius,w:fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival})'));
 const cell=(id,size,up)=>dropCell(id,size,up,hash,dropRadius,dropDensity,fract);

 // Translate weatherRoofRivuletLayer from live WEATHER_GLSL.
 const rivLayerBody=body('vec3','weatherRoofRivuletLayer')
  .replaceAll('vec3(0.0)','v3(0,0,0)')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/vec2\(([^)]+)\)/g,'v2($1)')
  .replace(/\b(?:float|vec3) (?=\w+=)/g,'let ');
 const rivLayerRaw=new Function('uv','wet','rate','phase','dx','dy','cellW','seed',
  'v2','v3','smoothstep','abs','floor','fract','sin','cos','mix','clamp','max','length','weatherRingHash',rivLayerBody);
 const rivLayer=(uv,wet,rate,phase,dx,dy,cellW,seed)=>rivLayerRaw(
  uv,wet,rate,phase,dx,dy,cellW,seed,v2,v3,smoothstep,Math.abs,Math.floor,fract,Math.sin,Math.cos,mix,clamp,Math.max,p=>Math.hypot(p.x,p.y),hash);

 // Translate weatherRoofRivulets from live WEATHER_GLSL.
 const rivBody=body('vec3','weatherRoofRivulets')
  .replace('uv+vec2(.25,3.71)','add2(uv,v2(.25,3.71))')
  .replace('vec3(a.xy+b.xy,a.z+b.z-a.z*b.z)','v3(a.x+b.x,a.y+b.y,a.z+b.z-a.z*b.z)')
  .replace(/\bvec3 (?=\w+=)/g,'let ');
 const rivRaw=new Function('uv','wet','rate','phase','dx','dy','weatherRoofRivuletLayer','add2','v2','v3',rivBody);
 const rivulets=(uv,wet,rate,phase,dx,dy)=>rivRaw(uv,wet,rate,phase,dx,dy,rivLayer,add2,v2,v3);

 // Translate weatherRoofBeadLayer and weatherRoofBeads from live WEATHER_GLSL.
 const beadLayerBody=body('vec3','weatherRoofBeadLayer')
  .replaceAll('vec3(0.0)','v3(0,0,0)')
  .replace('vec2 p=uv/cellSize,id=floor(p);','let p=v2(uv.x/cellSize,uv.y/cellSize),id=v2(Math.floor(p.x),Math.floor(p.y));')
  .replace('vec2 centre=clamp(spot.xy,vec2(radius),vec2(1.0-radius));','let centre=v2(clamp(spot.x,radius,1-radius),clamp(spot.y,radius,1-radius));')
  .replace('vec2 q=(fract(p)-centre)/max(radius,.001);','let q=mul2(sub2(v2(fract(p.x),fract(p.y)),centre),1/max(radius,.001));')
  .replace('vec2 slope=q*dome*.78*arrived*disc*vis;','let slope=mul2(q,dome*.78*arrived*disc*vis);')
  .replace('vec3(slope,mix(avgCov,arrived*disc,vis))','v3(slope.x,slope.y,mix(avgCov,arrived*disc,vis))')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/vec2\(([^)]+)\)/g,'v2($1)')
  .replace(/\b(?:float|vec4) (?=\w+=)/g,'let ');
 const beadLayerRaw=new Function('uv','wet','dx','dy','cellSize','up',
  'v2','v3','sub2','mul2','dot','sqrt','abs','max','min','clamp','smoothstep','mix','fract','length','weatherDropDensity','weatherDropCell','weatherSpot',beadLayerBody);
 const beadLayer=(uv,wet,dx,dy,cellSize,up)=>beadLayerRaw(
  uv,wet,dx,dy,cellSize,up,v2,v3,sub2,mul2,dot2,Math.sqrt,Math.abs,Math.max,Math.min,clamp,smoothstep,mix,fract,p=>Math.hypot(p.x,p.y),dropDensity,cell,spotFn);

 const beadsBody=body('vec3','weatherRoofBeads')
  .replace('mat2 rot=mat2(.8,.6,-.6,.8);','const rot=p=>v2(.8*p.x-.6*p.y,.6*p.x+.8*p.y);')
  .replace('rot*uv+vec2(1.731,4.913)','add2(rot(uv),v2(1.731,4.913))')
  .replaceAll('rot*dx','rot(dx)').replaceAll('rot*dy','rot(dy)')
  .replace('vec2 slopeB=vec2(.8*b.x+.6*b.y,-.6*b.x+.8*b.y);','let slopeB=v2(.8*b.x+.6*b.y,-.6*b.x+.8*b.y);')
  .replace('vec3(a.xy+slopeB,a.z+b.z-a.z*b.z)','v3(a.x+slopeB.x,a.y+slopeB.y,a.z+b.z-a.z*b.z)')
  .replace(/\bvec3 (?=\w+=)/g,'let ');
 const beadsRaw=new Function('uv','wet','dx','dy','up','weatherRoofBeadLayer','add2','v2','v3',beadsBody);
 const beads=(uv,wet,dx,dy,up)=>beadsRaw(uv,wet,dx,dy,up,beadLayer,add2,v2,v3);

 // Non-roof weatherDrops evaluator for roof-vs-solid bead comparison at wet=1.
 const dropTone=scalar('weatherDropTone');
 const dropLayerBody=body('float','weatherDropLayer')
  .replace('vec2 p=world/cellSize,id=floor(p);','let p=v2(world.x/cellSize,world.y/cellSize),id=v2(Math.floor(p.x),Math.floor(p.y));')
  .replace('vec2 local=fract(p)-spot.xy;','let local=sub2(v2(fract(p.x),fract(p.y)),spot);')
  .replace('vec2 direction=local/max(d,.001);','let direction=mul2(local,1/max(d,.001));')
  .replace(/\b(?:float|vec4) (?=\w+=)/g,'let ');
 const dropLayerRaw=new Function('world','wet','dx','dy','cellSize','up','weatherDropCell','weatherSpot','weatherDropTone','sub2','mul2','v2','fract','length','dot','max','abs','smoothstep','mix',dropLayerBody);
 const dropLayer=(world,wet,dx,dy,size,up)=>dropLayerRaw(world,wet,dx,dy,size,up,cell,spotFn,dropTone,sub2,mul2,v2,fract,p=>Math.hypot(p.x,p.y),dot2,Math.max,Math.abs,smoothstep,mix);
 const dropsRaw=new Function('world','wet','dx','dy','up','smoothstep','abs','v2','add2','weatherDropLayer',body('float','weatherDrops')
  .replace('vec2 stretch=vec2(1.0,1.0-.35*vertical);','let stretch=v2(1,1-.35*vertical);')
  .replace('world*=stretch;dx*=stretch;dy*=stretch;','world=v2(world.x*stretch.x,world.y*stretch.y);dx=v2(dx.x*stretch.x,dx.y*stretch.y);dy=v2(dy.x*stretch.x,dy.y*stretch.y);')
  .replace('mat2 rotation=mat2(.8,.6,-.6,.8);','const rotation=p=>v2(.8*p.x-.6*p.y,.6*p.x+.8*p.y);')
  .replace('rotation*world+vec2(1.731,4.913)','add2(rotation(world),v2(1.731,4.913))')
  .replaceAll('rotation*dx','rotation(dx)').replaceAll('rotation*dy','rotation(dy)').replace(/\bfloat (?=\w+=)/g,'let '));
 const solidDrops=(world,wet,dx,dy,up)=>dropsRaw(world,wet,dx,dy,up,smoothstep,Math.abs,v2,add2,dropLayer);

 // Roof noise & basis evaluator matching APPLY.
 const wHash=(x,y)=>fract(Math.sin(x*127.1+y*311.7)*43758.5453);
 const wNoise=(x,y)=>{const ix=Math.floor(x),iy=Math.floor(y),fx=fract(x),fy=fract(y),u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);
  return mix(mix(wHash(ix,iy),wHash(ix+1,iy),u),mix(wHash(ix,iy+1),wHash(ix+1,iy+1),u),v);};
 const wetScale=scalar('weatherWetScale'),snowFn=scalar('weatherSnow'),exposure=scalar('weatherExposure'),horizonFn=scalar('weatherHorizon');
 const porosityFn=scalar('weatherPorosity'),darkenWetFn=scalar('weatherDarkenWet'),wetRoughFn=scalar('weatherWetRoughness'),roughFn=scalar('weatherRoughness'),waterFilmFn=scalar('weatherWaterFilm');

 function evalRoofFragment({world,face,dxWorld,dyWorld,wet,snow=0,rate=0,phase=0,open=1,roughness=0.45,metalness=0.45,albedo=0.04,viewDir=v3(0,0.45,0.89),seamAcrossDelta=0}){
  const weatherUp=face.y;
  const slopeSin=Math.hypot(face.x,face.z);
  const horiz=slopeSin>0.001?v2(face.x/slopeSin,face.z/slopeSin):v2(1,0);
  const acrossDir=v3(horiz.y,0,-horiz.x);
  const downDir=v3(horiz.x*weatherUp,-slopeSin,horiz.y*weatherUp);
  const uv=v2(dot3(world,acrossDir),dot3(world,downDir));
  const dx=v2(dot3(dxWorld,acrossDir),dot3(dxWorld,downDir));
  const dy=v2(dot3(dyWorld,acrossDir),dot3(dyWorld,downDir));
  const upMask=smoothstep(0.05,0.25,weatherUp);
  const slopeMask=smoothstep(0.02,0.12,slopeSin)*upMask;
  const activePhase=rate>0?phase:0;
  const roofWetRaw=exposure(wet,open)*upMask;
  const porosity=porosityFn(metalness,roughness);
  const impervious=1-porosity;
  const rivWeight=mix(0.12,1.0,impervious*impervious);
  const beadWeight=smoothstep(0.25,0.75,impervious);
  const riv=roofWetRaw>0&&slopeMask>0?rivulets(uv,roofWetRaw,rate,activePhase,dx,dy):v3(0,0,0);
  riv.x*=slopeMask*rivWeight;riv.y*=slopeMask*rivWeight;riv.z*=slopeMask*rivWeight;
  const bead=roofWetRaw>0&&beadWeight>0?beads(uv,roofWetRaw,dx,dy,weatherUp):v3(0,0,0);
  bead.x*=beadWeight;bead.y*=beadWeight;bead.z*=beadWeight;
  const seamRib=smoothstep(0.06,0.28,Math.abs(seamAcrossDelta));
  const activeFlow=smoothstep(0,0.35,rate);
  const seamPhi=6.2831853*(uv.y/1.25-2*activePhase+fract(uv.x*1.73));
  const seamVis=1-smoothstep(0.025,0.065,Math.hypot(dx.x,dy.x));
  const seamRun=seamRib*mix(0.68,0.48+0.58*(0.5+0.5*Math.sin(seamPhi)),activeFlow)*smoothstep(0.08,0.55,roofWetRaw)*slopeMask*seamVis*rivWeight;
  const channelCov=clamp(Math.max(riv.z,seamRun*0.65),0,1);
  const beadKeep=1-channelCov;
  const slope=v2(riv.x+bead.x*beadKeep,riv.y+bead.y*beadKeep-Math.cos(seamPhi)*0.12*activeFlow*seamRun);
  const waterCov=clamp(channelCov+bead.z*beadKeep,0,1);
  const weatherWet=exposure(wet,open);
  const weatherGlossValue=weatherWet*mix(0.65,1.0,wNoise(uv.x*2.2,uv.y*0.3));
  const filmVar=weatherWet>0?clamp((weatherGlossValue/weatherWet-0.65)/0.35,0,1):0;
  const weatherS=exposure(snowFn(weatherUp,snow,0.5),open);
  let color=albedo*wetScale(albedo,metalness,darkenWetFn(porosity,weatherWet));
  color=mix(color,0.87,weatherS);
  const baseWet=wetRoughFn(roughness,porosity,roofWetRaw);
  let roofRough=mix(baseWet,Math.min(baseWet,mix(0.14,0.08,filmVar)),impervious*roofWetRaw);
  roofRough=mix(roofRough,clamp(baseWet*mix(0.82,1.12,filmVar),0.045,1.0),porosity*roofWetRaw);
  roofRough=mix(roofRough,Math.min(roofRough,0.05),bead.z*beadKeep*roofWetRaw);
  roofRough=mix(roofRough,Math.min(roofRough,0.045),channelCov*roofWetRaw);
  const finalRough=mix(roofRough,0.7,weatherS);
  const filmCov=Math.max(waterFilmFn(porosity,weatherWet,0),waterCov*roofWetRaw);
  const finalMetal=mix(metalness,0,Math.max(filmCov,weatherS));
  const nx=face.x+(acrossDir.x*slope.x+downDir.x*slope.y)*(1-weatherS);
  const ny=face.y+(acrossDir.y*slope.x+downDir.y*slope.y)*(1-weatherS);
  const nz=face.z+(acrossDir.z*slope.x+downDir.z*slope.y)*(1-weatherS);
  const nLen=Math.max(Math.hypot(nx,ny,nz),0.0001);
  const normal=v3(nx/nLen,ny/nLen,nz/nLen);
  const vLen=Math.hypot(viewDir.x,viewDir.y,viewDir.z);
  const V=v3(viewDir.x/vLen,viewDir.y/vLen,viewDir.z/vLen);
  const iv=v3(-V.x,-V.y,-V.z);
  const dn=dot3(iv,normal);
  const reflY=iv.y-2*dn*normal.y;
  const roofWetNoSnow=roofWetRaw*(1-weatherS);
  const roofHorizon=horizonFn(reflY,roofWetNoSnow);
  const roofNoV=clamp(dot3(normal,V),0,1);
  const roofGrazing=(1-roofNoV)*(1-roofNoV);
  const roofSkyGrad=smoothstep(0.15,0.95,reflY);
  const roofCoatWeight=(1-smoothstep(0.15,0.65,albedo*metalness))*impervious;
  const roofFilmSheen=mix(1.50,2.25,clamp(roofGrazing*0.75+roofSkyGrad*0.45,0,1))*mix(0.90,1.08,filmVar);
  const roofWaterGlint=mix(0,1.35,waterCov)*(0.70+0.45*roofSkyGrad);
  const roofSheen=mix(1.0,roofFilmSheen+roofWaterGlint,roofCoatWeight);
  const horizonDamp=mix(1.0,roofHorizon*roofSheen,roofWetNoSnow);
  return {acrossDir,downDir,uv,porosity,rivWeight,beadWeight,filmCov,riv,bead,seamRun,channelCov,slope,waterCov,color,roughness:finalRough,metalness:finalMetal,normal,horizonDamp,reflY,snow:weatherS};
 }
 return {rivulets,beads,solidDrops,evalRoofFragment,porosityFn,darkenWetFn,wetRoughFn,waterFilmFn,wetScale,roughFn,rivLayerBody};
}

await test('roof programs assemble across all lit material kinds and stay strictly within the 224-vector / 16-sampler budget',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene();
 renderer.toneMapping=THREE.ACESFilmicToneMapping;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;
 scene.environment=new THREE.Texture();
 const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installWeatherSurface(scene);
 const stressLights=makeLights();
 stressLights.directional=[{},{}];stressLights.directionalShadowMap=[{}];
 stressLights.point=Array.from({length:4},()=>({}));stressLights.pointShadowMap=[{},{}];
 stressLights.spot=[{},{}];stressLights.spotShadowMap=[{},{}];
 stressLights.rectArea=[{}];stressLights.hemi=[{}];
 const cache=programs(renderer);
 const cases=[
  ['roof Standard',new THREE.MeshStandardMaterial({name:'roof',metalness:.45,roughness:.45})],
  ['roof Physical',new THREE.MeshPhysicalMaterial({name:'roof',metalness:.45,roughness:.45})],
  ['roof Lambert',new THREE.MeshLambertMaterial({name:'roof'})],
  ['roof Phong',new THREE.MeshPhongMaterial({name:'roof'})],
  ['roof Toon',new THREE.MeshToonMaterial({name:'roof'})],
  ['roof role mapped',Object.assign(new THREE.MeshStandardMaterial({name:'standing_seam',map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()}),{userData:{materialRole:'roof'}})],
 ];
 const roofBaked=new THREE.MeshStandardMaterial({name:'roof',metalness:.45,roughness:.45,map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),aoMap:new THREE.Texture()});
 patchLightmaps([roofBaked],{banks:Array.from({length:2},()=>new THREE.DataArrayTexture(new Uint8Array(64),4,4,1))},lightmapUniforms(1,8,{fixtures:true}));
 cases.push(['roof baked 2-bank 8-lamp stress',roofBaked]);
 const budgets=[];
 for(const [label,mat] of cases){
  const o=new THREE.Mesh(new THREE.BoxGeometry(),mat);o.receiveShadow=true;scene.add(o);
  haze.prepare();shadow.prepare();layer.prepare();
  const src=programSource(renderer,cache,scene,o,stressLights);
  assert.ok(!src[2].includes('#include'),label+' expanded all includes');
  const f=preprocess(src[2]);
  checkGlslScopes(f,label);
  assert.ok(f.includes('weatherRoofRivulets(')&&f.includes('weatherRoofBeads('),label+' uses roof rivulets and beads');
  assert.ok(!f.includes('weatherPuddle(weatherUp'),label+' excludes puddles');
  const b=uniformBudget(src[2]);
  assert.ok(b.vectors<=224,`${label} vectors ${b.vectors} > 224`);
  assert.ok(b.samplers.length<=16,`${label} samplers ${b.samplers.length} > 16`);
  budgets.push({label,vectors:b.vectors,samplers:b.samplers.length});
 }
 assert.equal(budgets[0].vectors,182,'roof Standard stress vectors unchanged');
 assert.equal(budgets[5].vectors,188,'roof mapped stress vectors unchanged');
 assert.equal(budgets[6].vectors,191,'roof baked 2-bank 8-lamp stress vectors unchanged');
 console.log('ROOF_BUDGETS',JSON.stringify(budgets));
 layer.dispose();shadow.dispose();haze.dispose();
});

await test('non-roof programs compile without any roof code and keep their exact keys and budgets',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene();
 renderer.toneMapping=THREE.ACESFilmicToneMapping;scene.environment=new THREE.Texture();
 const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installWeatherSurface(scene);
 const lights=makeLights();lights.directional=[{},{}];lights.hemi=[{}];
 const cache=programs(renderer);
 const solid=new THREE.MeshStandardMaterial({name:'siding'});
 const lawn=new THREE.MeshStandardMaterial({name:'lawn'});
 const grass=grassMaterial(new THREE.MeshStandardMaterial());
 const water=surfaceMaterial(new THREE.MeshPhysicalMaterial()).material;
 const submerged=underwaterMaterial(new THREE.MeshStandardMaterial(),{height:0}).material;
 const sheet=sheetMaterial();
 const fountain=waterMaterial();
 const nonRoofs=[
  ['solid',solid,'weather-surface-solid-1',false],
  ['lawn',lawn,'weather-surface-lawn-1',false],
  ['grass',grass,'weather-surface-lawn-1',true],
  ['water',water,'weather-surface-water-1',false],
  ['sheet',sheet,'weather-surface-water-1',false],
  ['submerged',submerged,'weather-surface-submerged-1',false],
  ['effect',fountain,'weather-surface-effect-1',false],
 ];
 for(const [label,mat,expectedTag,inst] of nonRoofs){
  const o=inst?new THREE.InstancedMesh(new THREE.BoxGeometry(),mat,1):new THREE.Mesh(new THREE.BoxGeometry(),mat);
  scene.add(o);haze.prepare();shadow.prepare();layer.prepare();
  const src=programSource(renderer,cache,scene,o,lights);
  assert.ok(src.key.includes(expectedTag),`${label} key retains ${expectedTag}`);
  const f=preprocess(src[2]);
  checkGlslScopes(f,label);
  for(const forbidden of ['weatherRoofRivulets','weatherRoofRivuletLayer','weatherRoofBeads','weatherRoofBeadLayer','roofAcrossDir','roofDownDir','roofRiv','roofBead']){
   assert.ok(!f.includes(forbidden),`${label} preprocessed source must not contain ${forbidden}`);
  }
  if(['water','sheet','submerged','effect'].includes(label)){
   for(const forbidden of ['weatherPorosity','weatherDarkenWet','weatherWetRoughness','weatherWaterFilm']){
    assert.ok(!f.includes(forbidden),`${label} water/submerged/effect must not include porosity/film helpers`);
   }
  }else{
   assert.ok(f.includes('weatherPorosity(')&&f.includes('weatherDarkenWet(')&&f.includes('weatherWaterFilm('),`${label} uses shared porosity and dielectric film model`);
  }
  const b=uniformBudget(src[2]);
  assert.ok(b.vectors<=224&&b.samplers.length<=16,label+' within budget');
 }
 layer.dispose();shadow.dispose();haze.dispose();
});

const ev=buildRoofEvaluators();

await test('dry roof (wetness 0) matches main identically even while raining; snow cover wins over full wetness',()=>{
 const face=v3(0,Math.cos(0.4),Math.sin(0.4));
 const dx=v3(0.004,0,0),dy=v3(0,-0.002,0.003);
 for(const rate of [0,1])for(const phase of [0,0.37,0.89]){
  for(let i=0;i<25;i++){
   const world=v3(i*0.13-1.5,3.5-i*0.04,i*0.11);
   const r=ev.evalRoofFragment({world,face,dxWorld:dx,dyWorld:dy,wet:0,snow:0,rate,phase,roughness:0.45,metalness:0.45,albedo:0.04});
   close(r.color,0.04);close(r.roughness,0.45);close(r.metalness,0.45);
   close(r.horizonDamp,1.0);
   close(r.normal.x,face.x);close(r.normal.y,face.y);close(r.normal.z,face.z);
  }
 }
 // Full snow overrides full wetness, rivulets, and beads completely.
 for(let i=0;i<25;i++){
  const world=v3(i*0.17,4.0,i*0.09);
  const s=ev.evalRoofFragment({world,face,dxWorld:dx,dyWorld:dy,wet:1,snow:1,rate:1,phase:0.5,roughness:0.45,metalness:0.45,albedo:0.04});
  close(s.color,0.87);close(s.roughness,0.7);close(s.metalness,0.0);
  close(s.horizonDamp,1.0);
  close(s.normal.x,face.x);close(s.normal.y,face.y);close(s.normal.z,face.z);
 }
});

await test('rivulets align with the downhill direction on arbitrarily rotated pitched faces, flow while raining and freeze when rain stops',()=>{
 const dx=v2(0.003,0),dy=v2(0,0.003);
 // Check orthonormal downhill basis on multiple roof azimuths and pitches.
 for(const azDeg of [0,35,120,245,357.6])for(const pitchRatio of [4/12,6/12,10/12]){
  const az=azDeg*Math.PI/180,pitch=Math.atan(pitchRatio);
  const face=v3(Math.sin(pitch)*Math.cos(az),Math.cos(pitch),Math.sin(pitch)*Math.sin(az));
  const out=ev.evalRoofFragment({world:v3(2,4,-3),face,dxWorld:v3(0.003,0,0),dyWorld:v3(0,0,0.003),wet:1,rate:1,phase:0.2});
  close(Math.hypot(out.acrossDir.x,out.acrossDir.y,out.acrossDir.z),1,1e-5);
  close(Math.hypot(out.downDir.x,out.downDir.y,out.downDir.z),1,1e-5);
  close(dot3(out.acrossDir,face),0,1e-5);
  close(dot3(out.downDir,face),0,1e-5);
  close(dot3(out.acrossDir,out.downDir),0,1e-5);
  assert.ok(out.downDir.y<-0.1,'downDir points strictly downhill');
  close(out.acrossDir.y,0,1e-5);
 }
 // Measure directional alignment: step 3 cm ACROSS vs 3 cm ALONG the slope.
 // Channels run downhill, so across-slope changes are far larger than along-slope changes.
 let acrossDiff=0,alongDiff=0,samples=0,peakCov=0,minCov=1,slopeMag=0;
 for(let iu=0;iu<120;iu++)for(let iv=0;iv<20;iv++){
  const u=iu*0.025,v=iv*0.18;
  const c=ev.rivulets(v2(u,v),1,1,0.25,dx,dy);
  const cu=ev.rivulets(v2(u+0.03,v),1,1,0.25,dx,dy);
  const cv=ev.rivulets(v2(u,v+0.03),1,1,0.25,dx,dy);
  acrossDiff+=Math.abs(cu.z-c.z);
  alongDiff+=Math.abs(cv.z-c.z);
  peakCov=Math.max(peakCov,c.z);minCov=Math.min(minCov,c.z);
  slopeMag+=Math.hypot(c.x,c.y);samples++;
 }
 const alignRatio=acrossDiff/Math.max(alongDiff,1e-9);
 assert.ok(alignRatio>6.0,`straighter rivulets align tightly downhill (across/along diff ratio=${alignRatio.toFixed(2)})`);
 assert.ok(peakCov>0.60&&minCov<0.05,'rivulets form distinct wet channels between film gaps');
 assert.ok(slopeMag/samples>0.002&&slopeMag/samples<0.025,`calm rivulet normal tilt (${(slopeMag/samples).toFixed(4)})`);
 // Verify wander amplitude (<= 1.5 cm) and long wander wavelength (>= 4 m) from live GLSL.
 const fMatch=ev.rivLayerBody.match(/f1=([\d.]+)\+h\.y\*([\d.]+),f2=([\d.]+)\+h\.x\*([\d.]+)/);
 const ampMatch=ev.rivLayerBody.match(/wanderM=.*?\*([\d.]+);/);
 assert.ok(fMatch&&ampMatch,'wander parameters found in live GLSL');
 const maxF1=Number(fMatch[1])+Number(fMatch[2]),maxF2=Number(fMatch[3])+Number(fMatch[4]),wanderAmpM=Number(ampMatch[1]);
 assert.ok(wanderAmpM<=0.015,`wander amplitude <= 1.5 cm (${wanderAmpM}m)`);
 assert.ok(2*Math.PI/maxF1>=7.0&&2*Math.PI/maxF2>=4.0,`long wander wavelengths: primary=${(2*Math.PI/maxF1).toFixed(2)}m secondary=${(2*Math.PI/maxF2).toFixed(2)}m`);

 // Motion while raining (rate > 0), downhill direction, seamless at 4-second wrap, and static when rate = 0.
 let motionPour=0,motionStop=0,wrapErr=0;
 let movedDown=0,movedUp=0;
 for(let i=0;i<300;i++){
  const p=v2((i%30)*0.08,Math.floor(i/30)*0.21);
  const a=ev.rivulets(p,1,1,0.10,dx,dy);
  const b=ev.rivulets(p,1,1,0.35,dx,dy);
  motionPour+=Math.abs(b.z-a.z)+Math.abs(b.y-a.y);
  // Check flow travels downhill (+v): advancing phase by dt shifts profile to larger v.
  const shift=ev.rivulets(v2(p.x,p.y+0.14),1,1,0.10+0.05,dx,dy);
  const opp=ev.rivulets(v2(p.x,p.y-0.14),1,1,0.10+0.05,dx,dy);
  movedDown+=Math.abs(shift.z-a.z);movedUp+=Math.abs(opp.z-a.z);
  // Seamless wrap across phase 0 -> 1.
  const w0=ev.rivulets(p,1,1,0.0,dx,dy),w1=ev.rivulets(p,1,1,1.0,dx,dy);
  wrapErr=Math.max(wrapErr,Math.abs(w1.z-w0.z),Math.abs(w1.x-w0.x),Math.abs(w1.y-w0.y));
  // When rate = 0, APPLY zeroes roofPhase before calling weatherRoofRivulets, AND activeFlow = 0.
  const s0=ev.evalRoofFragment({world:v3(p.x,4,p.y),face:v3(0,0.894,0.447),dxWorld:v3(0.003,0,0),dyWorld:v3(0,0,0.003),wet:1,rate:0,phase:0.1});
  const s1=ev.evalRoofFragment({world:v3(p.x,4,p.y),face:v3(0,0.894,0.447),dxWorld:v3(0.003,0,0),dyWorld:v3(0,0,0.003),wet:1,rate:0,phase:0.73});
  motionStop+=Math.abs(s1.riv.z-s0.riv.z)+Math.abs(s1.normal.x-s0.normal.x)+Math.abs(s1.normal.y-s0.normal.y)+Math.abs(s1.roughness-s0.roughness);
 }
 assert.ok(motionPour>0.5,`rivulets animate while raining (${motionPour.toFixed(3)})`);
 assert.ok(movedDown<movedUp,`rivulet surges travel downhill (${movedDown.toFixed(3)} < ${movedUp.toFixed(3)})`);
 assert.ok(wrapErr<1e-5,`4-second clock wrap is seamless (${wrapErr})`);
 assert.equal(motionStop,0,'stopped rain (rate=0, wetness=1) yields strictly static wet streaks');
 console.log('RIVULET_METRICS',JSON.stringify({alignRatio:+alignRatio.toFixed(2),peakCov:+peakCov.toFixed(3),minCov:+minCov.toFixed(3),wanderAmpM,motionPour:+motionPour.toFixed(3),wrapErr}));
});

await test('shared porosity & dielectric water film: ordering, darkening, gloss, untinted wet metal F0, puddles and dry identity',()=>{
 const pMetal=ev.porosityFn(1.0,0.45),pTile=ev.porosityFn(0.0,0.45),pMetalRoof=ev.porosityFn(0.45,0.45),pConcrete=ev.porosityFn(0.0,0.85),pShingle=ev.porosityFn(0.0,0.90);
 assert.ok(pMetal<pTile&&pTile<pConcrete,'porosity ordering: metal < semi-smooth tile < rough concrete');
 assert.ok(pMetalRoof<0.15&&pConcrete>=0.99&&pShingle>=0.99,'painted metal low porosity, concrete/shingles high');
 // Darkening: porous darkens strongly and early; metal/smooth barely darken.
 const lum=0.6;
 const dMetal=1-ev.wetScale(lum,1.0,ev.darkenWetFn(pMetal,1.0));
 const dTile=1-ev.wetScale(lum,0.0,ev.darkenWetFn(ev.porosityFn(0.0,0.22),1.0));
 const dPorousEarly=1-ev.wetScale(lum,0.0,ev.darkenWetFn(pConcrete,0.4));
 const dPorousFull=1-ev.wetScale(lum,0.0,ev.darkenWetFn(pConcrete,1.0));
 assert.ok(dMetal<0.02,`metal barely darkens (${dMetal.toFixed(4)})`);
 assert.ok(dTile<0.08,`smooth tile barely darkens (${dTile.toFixed(4)})`);
 assert.ok(dPorousEarly>0.22&&dPorousFull>0.48,`porous darkens early and strongly (${dPorousEarly.toFixed(3)} -> ${dPorousFull.toFixed(3)})`);
 // Wetness 0 equals dry for every material.
 for(const [m,r] of [[1.0,0.35],[0.45,0.45],[0.0,0.22],[0.0,0.85]]){
  const p=ev.porosityFn(m,r);
  close(ev.wetScale(0.6,m,ev.darkenWetFn(p,0)),1.0);
  close(ev.wetRoughFn(r,p,0),r);
  close(ev.waterFilmFn(p,0,0),0);
 }
 // Gloss: metal/smooth reach low thin-film roughness faster than porous; puddles always water-glossy (0.03).
 for(const w of [0.3,0.6,1.0]){
  const rMetal=ev.wetRoughFn(0.45,pMetal,w);
  const rSmooth=ev.wetRoughFn(0.30,ev.porosityFn(0.0,0.30),w);
  const rPorous=ev.wetRoughFn(0.85,pConcrete,w);
  assert.ok(rMetal<rPorous&&rSmooth<rPorous,`at wet=${w}, metal(${rMetal.toFixed(3)}) & smooth(${rSmooth.toFixed(3)}) < porous(${rPorous.toFixed(3)})`);
  close(ev.roughFn(rPorous,0,1,0),0.03);
  close(ev.roughFn(rMetal,0,1,0),0.03);
 }
 assert.ok(ev.wetRoughFn(0.85,pConcrete,1.0)>0.35,'porous concrete/shingle stays well above thin-film roughness without puddles');
 assert.ok(ev.wetRoughFn(0.45,pMetal,1.0)<=0.12,'wet metal reaches thin-film roughness');

 // Dielectric water film: under full film, dark metal's effective metalness drops so F0 becomes untinted
 // (near-grey) and brighter than round 3's tinted dark-metal F0; porous before saturation keeps metalness.
 const darkBronze=[0.042,0.027,0.020]; // #3a2e27 linear
 const metalFilmCov=ev.waterFilmFn(pMetalRoof,1.0,0.0);
 const wetMetalEff=mix(0.45,0.0,metalFilmCov);
 assert.ok(wetMetalEff<0.05,`dark metal effective metalness drops under full film (0.45 -> ${wetMetalEff.toFixed(4)})`);
 const f0R3=darkBronze.map(c=>mix(0.04,c,0.45));
 const f0R4=darkBronze.map(c=>mix(0.04,c,wetMetalEff));
 const chroma=rgb=>Math.max(...rgb)-Math.min(...rgb);
 const luma=rgb=>rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
 assert.ok(chroma(f0R4)<chroma(f0R3)*0.15,'wet dark metal specular F0 is untinted (near-grey)');
 assert.ok(luma(f0R4)>luma(f0R3)*1.10,'wet dark metal dielectric F0 is brighter than round 3 tinted F0');
 // Porous surface before saturation (wet = 0.5, no puddle) keeps metalness and moderate sheen; puddle flips to full dielectric.
 close(ev.waterFilmFn(1.0,0.5,0.0),0);
 close(ev.waterFilmFn(1.0,0.5,1.0),1.0);

 // Metal roof vs porous asphalt/wood shingle roof at identical wetness & pouring rain.
 const face=v3(0,0.894,0.447),dx=v3(0.002,0,0),dy=v3(0,0,0.002);
 let metalRiv=0,shingleRiv=0,metalBead=0,shingleBead=0,metalRough=0,shingleRough=0,shingleDark=0,metalDark=0,metalEffSum=0;
 for(let i=0;i<240;i++){
  const world=v3((i%24)*0.07,4.0,Math.floor(i/24)*0.11);
  const rm=ev.evalRoofFragment({world,face,dxWorld:dx,dyWorld:dy,wet:1,rate:1,phase:0.3,roughness:0.45,metalness:0.45,albedo:0.30});
  const rs=ev.evalRoofFragment({world,face,dxWorld:dx,dyWorld:dy,wet:1,rate:1,phase:0.3,roughness:0.88,metalness:0.0,albedo:0.30});
  metalRiv+=rm.riv.z;shingleRiv+=rs.riv.z;
  metalBead+=rm.bead.z;shingleBead+=rs.bead.z;
  metalRough+=rm.roughness;shingleRough+=rs.roughness;
  metalDark+=1-rm.color/0.30;shingleDark+=1-rs.color/0.30;
  metalEffSum+=rm.metalness;
 }
 assert.ok(metalEffSum/240<0.05,`wet metal roof effective metalness drops (${(metalEffSum/240).toFixed(4)})`);
 assert.ok(shingleRiv<metalRiv*0.25,`rivulets much fainter on porous shingles (${shingleRiv.toFixed(2)} vs ${metalRiv.toFixed(2)})`);
 assert.equal(shingleBead,0,'beads soak into porous shingle roof');
 assert.ok(metalBead>5,'beads remain on impervious metal roof');
 assert.ok(shingleRough/240>0.32&&metalRough/240<0.15,`porous roof keeps soft sheen (${(shingleRough/240).toFixed(3)}) vs glossy metal (${(metalRough/240).toFixed(3)})`);
 assert.ok(shingleDark/240>metalDark/240*2,'porous shingle roof darkens significantly more than metal roof');
 console.log('POROSITY_ROOF',JSON.stringify({metalEff:+(metalEffSum/240).toFixed(4),metalRough:+(metalRough/240).toFixed(3),shingleRough:+(shingleRough/240).toFixed(3),metalRiv:+metalRiv.toFixed(2),shingleRiv:+shingleRiv.toFixed(2),metalDark:+(metalDark/240).toFixed(3),shingleDark:+(shingleDark/240).toFixed(3)}));
});

await test('beads stay at wetness=1 on roofs only, wet film stays glossy (0.08-0.15) with no blanket damp, seams bias runnels, flat roofs stay finite',()=>{
 const dx=v2(0.001,0),dy=v2(0,0.001);
 let roofBeadCov=0,roofBeadSlope=0,solidDropSum=0,hits=0;
 let minRough=1,maxFilmRough=0,minFilmRough=1,minSkyFilmDamp=Infinity,maxRivDamp=0;
 const face=v3(0,0.894,0.447);
 const skyView=v3(0,0.45,0.89);
 for(let i=0;i<600;i++){
  const u=(i%30)*0.043,v=Math.floor(i/30)*0.047;
  const b=ev.beads(v2(u,v),1,dx,dy,face.y);
  roofBeadCov+=b.z;roofBeadSlope+=Math.hypot(b.x,b.y);
  if(b.z>0.5)hits++;
  solidDropSum+=ev.solidDrops(v2(u,v),1,dx,dy,face.y);
  const frag=ev.evalRoofFragment({world:v3(u,4,v),face,dxWorld:v3(0.001,0,0),dyWorld:v3(0,0,0.001),wet:1,rate:1,phase:0.3,roughness:0.45,metalness:0.45,albedo:0.04,viewDir:skyView});
  minRough=Math.min(minRough,frag.roughness);
  if(frag.waterCov<0.02){
   maxFilmRough=Math.max(maxFilmRough,frag.roughness);minFilmRough=Math.min(minFilmRough,frag.roughness);
   if(frag.reflY>=0.5)minSkyFilmDamp=Math.min(minSkyFilmDamp,frag.horizonDamp);
  }
  if(frag.riv.z>0.5)maxRivDamp=Math.max(maxRivDamp,frag.horizonDamp);
  // Dark metal albedo is never spotted with darker dots (uniform weatherWetScale ~0.999).
  assert.ok(frag.color>0.0395&&frag.color<=0.04,'dark metal roof has no dark bead dots');
 }
 assert.equal(solidDropSum,0,'non-roof surfaces still remove drop stains at wetness=1');
 assert.ok(hits>30&&roofBeadCov/600>0.05,'beads remain present on roofs at wetness=1');
 assert.ok(roofBeadSlope/600>0.01,'beads perturb normals as raised domes');
 assert.ok(minRough<=0.055,`rivulets/beads reach low glossy roughness (${minRough.toFixed(4)})`);
 assert.ok(minFilmRough>=0.075&&maxFilmRough<=0.16,`between-rivulet metal film roughness stays glossy (${minFilmRough.toFixed(3)}..${maxFilmRough.toFixed(3)})`);
 assert.ok(minSkyFilmDamp>=1.0,`no blanket horizon damp darkening on upward sky reflections (${minSkyFilmDamp.toFixed(3)})`);
 assert.ok(maxRivDamp>minSkyFilmDamp*1.12,`calm rivulets lift gently within the sky sheen (${maxRivDamp.toFixed(2)} vs ${minSkyFilmDamp.toFixed(2)})`);

 // Horizon-pointing ray still damps cleanly via weatherHorizon; grazing view brightens sky sheen.
 const grazing=ev.evalRoofFragment({world:v3(0.5,4,0.5),face:v3(0,0.94,0.34),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0,viewDir:v3(0,0.05,0.999)});
 const headOn=ev.evalRoofFragment({world:v3(0.5,4,0.5),face:v3(0,0.707,0.707),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0,viewDir:v3(0,0.65,0.76)});
 assert.ok(grazing.horizonDamp>headOn.horizonDamp*0.95,'grazing sky reflection stays bright');
 const belowHorizon=ev.evalRoofFragment({world:v3(0.5,4,0.5),face:v3(0,0.28,0.96),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0,viewDir:v3(0,0.85,0.52)});
 assert.ok(belowHorizon.reflY<0.04&&belowHorizon.horizonDamp<0.6,`rays pointing at/below horizon still damp (${belowHorizon.reflY.toFixed(2)} -> ${belowHorizon.horizonDamp.toFixed(2)})`);

 // Standing-seam rib biases straight water runnels along seam lines when present, zero on unmapped roofs.
 const flatPan=ev.evalRoofFragment({world:v3(0.11,4,0.3),face,dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:1,phase:0.2,seamAcrossDelta:0});
 const onSeam=ev.evalRoofFragment({world:v3(0.11,4,0.3),face,dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:1,phase:0.2,seamAcrossDelta:0.35});
 close(flatPan.seamRun,0);assert.ok(onSeam.seamRun>0.2&&onSeam.roughness<flatPan.roughness&&onSeam.roughness<=0.11,'standing-seam rib gains calm glossy runnel');
 const seamStop0=ev.evalRoofFragment({world:v3(0.11,4,0.3),face,dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0.1,seamAcrossDelta:0.35});
 const seamStop1=ev.evalRoofFragment({world:v3(0.11,4,0.3),face,dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0.8,seamAcrossDelta:0.35});
 close(seamStop0.seamRun,seamStop1.seamRun);

 // Flat roof (pitch 0, slopeSin = 0): zero rivulets, nonzero beads, zero NaNs.
 const flat=ev.evalRoofFragment({world:v3(1.2,4,2.3),face:v3(0,1,0),dxWorld:v3(0.001,0,0),dyWorld:v3(0,0,0.001),wet:1,rate:1,phase:0.5});
 assert.ok([flat.roughness,flat.color,flat.horizonDamp,flat.normal.x,flat.normal.y,flat.normal.z].every(Number.isFinite),'flat roof stays finite');
 close(flat.riv.z,0);close(flat.riv.x,0);close(flat.riv.y,0);
 console.log('BEAD_METRICS',JSON.stringify({hits,avgBeadCov:+(roofBeadCov/600).toFixed(4),minRough:+minRough.toFixed(4),filmRange:[+minFilmRough.toFixed(3),+maxFilmRough.toFixed(3)],minSkyFilmDamp:+minSkyFilmDamp.toFixed(3),maxRivDamp:+maxRivDamp.toFixed(3)}));
});

await test('detail stays sharp at 1-1.5 cm/px mid distance and fades cleanly to constant average at overview footprints',()=>{
 const sampleStats=(px)=>{
  const dx=v2(px,0),dy=v2(0,px);
  const rivC=[],beadC=[];let rivSlope=0,beadSlope=0;
  for(let i=0;i<400;i++){
   const p=v2((i%40)*0.097,Math.floor(i/40)*0.173);
   const r=ev.rivulets(p,1,1,0.4,dx,dy),b=ev.beads(p,1,dx,dy,0.894);
   rivC.push(r.z);beadC.push(b.z);
   rivSlope+=Math.hypot(r.x,r.y);beadSlope+=Math.hypot(b.x,b.y);
  }
  const stat=arr=>{const m=arr.reduce((s,v)=>s+v,0)/arr.length;const v=arr.reduce((s,x)=>s+(x-m)*(x-m),0)/arr.length;return {mean:m,std:Math.sqrt(v)};};
  return {riv:stat(rivC),bead:stat(beadC),rivSlope:rivSlope/400,beadSlope:beadSlope/400};
 };
 const near=sampleStats(0.0015),mid1cm=sampleStats(0.010),mid15cm=sampleStats(0.015),far=sampleStats(0.08);
 console.log('LOD_FILTER',JSON.stringify({near,mid1cm,mid15cm,far}));
 assert.ok(near.riv.std>0.06&&near.rivSlope>0.001,'near rivulets have calm contrast and normal tilt');
 assert.ok(near.bead.std>0.15&&near.beadSlope>0.01,'near beads have strong contrast and dome tilt');
 assert.ok(mid1cm.riv.std>0.06&&mid1cm.rivSlope>0.001,'1 cm/px owner-view rivulets retain full contrast');
 assert.ok(mid15cm.riv.std>0.06&&mid15cm.rivSlope>0.001,'1.5 cm/px upper-roof rivulets retain full contrast');
 assert.ok(far.riv.std<1e-6&&far.rivSlope<1e-6,'overview rivulets filter to exact constant average with zero normal shimmer');
 assert.ok(far.bead.std<1e-6&&far.beadSlope<1e-6,'overview beads filter to exact constant average with zero normal shimmer');
 assert.ok(far.riv.mean>0.01&&far.riv.mean<0.12,'overview rivulet average stays in calm coverage range');
 assert.ok(far.bead.mean>0.04&&far.bead.mean<0.25,'overview bead average stays in realistic coverage range');
});

finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(code)
