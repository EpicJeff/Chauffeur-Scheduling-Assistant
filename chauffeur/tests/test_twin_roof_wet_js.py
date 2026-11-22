"""Wet roof rivulets, persistent beads, porosity and dielectric film: real r187 assembly and live sliced GLSL."""
import subprocess
import sys
from pathlib import Path

from test_twin_weather_surface_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]


def main_weather_source():
    try:
        return subprocess.check_output(
            ['git', 'show', '7a23b5f1:chauffeur/static/twin/sky/weather_surface.js'],
            cwd=ROOT, encoding='utf-8', stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None


DRIVER = PREFIX + r"""
const {installWeatherSurface,WEATHER_GLSL}=await import(file('static/twin/sky/weather_surface.js'));
// Capture THREE.ShaderChunk after haze & cloud-shadow install, before weather_surface ever installs.
const BEFORE_WEATHER=(()=>{
 const s=new THREE.Scene(),h=installStageHaze(s,{}),c=installCloudShadow(s,{uniforms:createCloudUniforms()});
 h.dispose();c.dispose();return {...THREE.ShaderChunk};
})();
const close=(a,b,eps=1e-6)=>assert.ok(Math.abs(a-b)<=eps,`${a} != ${b}`);
const mix=(a,b,t)=>typeof a==='object'?(a.z!==undefined?{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z:a.z+(b.z-a.z)*t}:{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t}):a+(b-a)*t;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const smoothstep=(a,b,v)=>{const t=clamp((v-a)/(b-a),0,1);return t*t*(3-2*t);};
const step=(a,v)=>v<a?0:1;
const fract=x=>x-Math.floor(x);
const v2=(x,y=x)=>({x,y}),v3=(x,y=x,z=x)=>({x,y,z});
const add=(a,b)=>a.z!==undefined?v3(a.x+b.x,a.y+b.y,a.z+b.z):v2(a.x+b.x,a.y+b.y);
const sub=(a,b)=>a.z!==undefined?v3(a.x-b.x,a.y-b.y,a.z-b.z):v2(a.x-b.x,a.y-b.y);
const mul=(a,b)=>typeof b==='number'?(a.z!==undefined?v3(a.x*b,a.y*b,a.z*b):v2(a.x*b,a.y*b)):(a.z!==undefined?v3(a.x*b.x,a.y*b.y,a.z*b.z):v2(a.x*b.x,a.y*b.y));
const dot=(a,b)=>a.z!==undefined?a.x*b.x+a.y*b.y+a.z*b.z:a.x*b.x+a.y*b.y;
const len=a=>a.z!==undefined?Math.hypot(a.x,a.y,a.z):Math.hypot(a.x,a.y);
const norm=a=>{const l=len(a)||1;return mul(a,1/l);};
const refl=(I,N)=>{const d=2*dot(N,I);return sub(I,mul(N,d));};
const neg=a=>mul(a,-1);

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

// Extract the balanced brace block starting at `fromIndex`.
function braceBlock(src,fromIndex){
 const start=src.indexOf('{',fromIndex);
 assert.ok(start>=0,'opening brace found');
 let depth=0;
 for(let i=start;i<src.length;i++){
  if(src[i]==='{')depth++;
  else if(src[i]==='}'){depth--;if(depth===0)return src.slice(fromIndex,i+1);}
 }
 throw new Error('unbalanced brace block');
}

// Build live JS evaluators directly from the installed WEATHER_GLSL and the real
// preprocessed THREE.ShaderChunk.normal_fragment_maps (no hand-retyped APPLY).
function buildEvaluators(){
 const installed=installWeatherSurface(new THREE.Scene());installed.dispose();
 const roofGlsl=preprocess('#define WEATHER_SURFACE_ROOF\n'+WEATHER_GLSL);
 const body=(type,name)=>{
  const m=roofGlsl.match(new RegExp(type+' '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'));
  assert.ok(m,name+' found in roof GLSL');return m[1];
 };
 const scalar=name=>{
  const m=roofGlsl.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));
  assert.ok(m,name);
  return new Function('mix','clamp','smoothstep','max','min','abs','sin','step',
   `return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(mix,clamp,smoothstep,Math.max,Math.min,Math.abs,Math.sin,step);
 };
 const ringHash=new Function('p','fract',body('vec3','weatherRingHash')
  .replace('vec3 q=fract(vec3(p.x,p.y,p.x)*vec3(.1031,.1030,.0973));','let q={x:fract(p.x*.1031),y:fract(p.y*.1030),z:fract(p.x*.0973)};')
  .replace('q+=dot(q,q.yxz+33.33);','const d=q.x*(q.y+33.33)+q.y*(q.x+33.33)+q.z*(q.z+33.33);q={x:q.x+d,y:q.y+d,z:q.z+d};')
  .replace('return fract((q.xxy+q.yzz)*q.zyx);','return {x:fract((q.x+q.y)*q.z),y:fract((q.x+q.z)*q.y),z:fract((q.y+q.z)*q.x)};'));
 const hash=p=>ringHash(p,fract);
 const dropRadius=scalar('weatherDropRadius'),dropDensity=scalar('weatherDropDensity'),spotFn=scalar('weatherSpot'),dropTone=scalar('weatherDropTone');
 const dropCell=new Function('id','cellSize','up','weatherRingHash','weatherDropRadius','weatherDropDensity','fract',body('vec4','weatherDropCell')
  .replace('vec3 random=','let random=').replace('float radius=','let radius=')
  .replace('vec2 centre=vec2(radius)+random.xy*(1.0-2.0*radius);','let centre={x:radius+random.x*(1-2*radius),y:radius+random.y*(1-2*radius)};')
  .replace('float arrival=','let arrival=')
  .replace('vec4(centre,radius,fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival)','({x:centre.x,y:centre.y,z:radius,w:fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival})'));
 const cell=(id,size,up)=>dropCell(id,size,up,hash,dropRadius,dropDensity,fract);

 // Translate live weatherRoofRivulets from WEATHER_GLSL.
 const rivBody=body('vec3','weatherRoofRivulets')
  .replaceAll('vec3(0.0)','v3(0,0,0)')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/vec2\(([^)]+)\)/g,'v2($1)')
  .replace(/\b(?:float|vec3) (?=\w+=)/g,'let ');
 const rivRaw=new Function('uv','wet','rate','phase','dx','dy',
  'v2','v3','smoothstep','abs','floor','fract','sin','cos','mix','clamp','max','length','weatherRingHash',rivBody);
 const rivulets=(uv,wet,rate,phase,dx,dy)=>rivRaw(
  uv,wet,rate,phase,dx,dy,v2,v3,smoothstep,Math.abs,Math.floor,fract,Math.sin,Math.cos,mix,clamp,Math.max,len,hash);

 // Translate live weatherRoofBeads from WEATHER_GLSL.
 const beadBody=body('vec3','weatherRoofBeads')
  .replace('vec2 p=uv*29.4118,id=floor(p);','let p=mul(uv,29.4118),id=v2(Math.floor(p.x),Math.floor(p.y));')
  .replace('vec2 centre=vec2(radius)+h.xy*(1.0-2.0*radius);','let centre=v2(radius+h.x*(1-2*radius),radius+h.y*(1-2*radius));')
  .replace('vec2 q=(fract(p)-centre)/radius;','let q=mul(sub(v2(fract(p.x),fract(p.y)),centre),1/radius);')
  .replace('q*(dome*.78*disc*vis)','mul(q,dome*.78*disc*vis)')
  .replace('vec3(mul(q,dome*.78*disc*vis),mix(avgCov,disc,vis))','((_s)=>v3(_s.x,_s.y,mix(avgCov,disc,vis)))(mul(q,dome*.78*disc*vis))')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/\b(?:float|vec3) (?=\w+=)/g,'let ');
 const beadRaw=new Function('uv','wet','dx','dy','up',
  'v2','v3','sub','mul','dot','sqrt','max','clamp','smoothstep','mix','fract','step','weatherDropDensity','weatherRingHash',beadBody);
 const beads=(uv,wet,dx,dy,up)=>beadRaw(
  uv,wet,dx,dy,up,v2,v3,sub,mul,dot,Math.sqrt,Math.max,clamp,smoothstep,mix,fract,step,dropDensity,hash);

 // Non-roof weatherDrops evaluator for roof-vs-solid comparison at wet=1.
 const dropLayerBody=body('float','weatherDropLayer')
  .replace('vec2 p=world/cellSize,id=floor(p);','let p=v2(world.x/cellSize,world.y/cellSize),id=v2(Math.floor(p.x),Math.floor(p.y));')
  .replace('vec2 local=fract(p)-spot.xy;','let local=sub(v2(fract(p.x),fract(p.y)),spot);')
  .replace('vec2 direction=local/max(d,.001);','let direction=mul(local,1/max(d,.001));')
  .replace(/\b(?:float|vec4) (?=\w+=)/g,'let ');
 const dropLayerRaw=new Function('world','wet','dx','dy','cellSize','up','weatherDropCell','weatherSpot','weatherDropTone','sub','mul','v2','fract','length','dot','max','abs','smoothstep','mix',dropLayerBody);
 const dropLayer=(world,wet,dx,dy,size,up)=>dropLayerRaw(world,wet,dx,dy,size,up,cell,spotFn,dropTone,sub,mul,v2,fract,len,dot,Math.max,Math.abs,smoothstep,mix);
 const dropsRaw=new Function('world','wet','dx','dy','up','smoothstep','abs','v2','add','weatherDropLayer',body('float','weatherDrops')
  .replace('vec2 stretch=vec2(1.0,1.0-.35*vertical);','let stretch=v2(1,1-.35*vertical);')
  .replace('world*=stretch;dx*=stretch;dy*=stretch;','world=v2(world.x*stretch.x,world.y*stretch.y);dx=v2(dx.x*stretch.x,dx.y*stretch.y);dy=v2(dy.x*stretch.x,dy.y*stretch.y);')
  .replace('mat2 rotation=mat2(.8,.6,-.6,.8);','const rotation=p=>v2(.8*p.x-.6*p.y,.6*p.x+.8*p.y);')
  .replace('rotation*world+vec2(1.731,4.913)','add(rotation(world),v2(1.731,4.913))')
  .replaceAll('rotation*dx','rotation(dx)').replaceAll('rotation*dy','rotation(dy)').replace(/\bfloat (?=\w+=)/g,'let '));
 const solidDrops=(world,wet,dx,dy,up)=>dropsRaw(world,wet,dx,dy,up,smoothstep,Math.abs,v2,add,dropLayer);

 const wHash=p=>fract(Math.sin(p.x*127.1+p.y*311.7)*43758.5453);
 const wNoise=p=>{const ix=Math.floor(p.x),iy=Math.floor(p.y),fx=fract(p.x),fy=fract(p.y),u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);
  return mix(mix(wHash(v2(ix,iy)),wHash(v2(ix+1,iy)),u),mix(wHash(v2(ix,iy+1)),wHash(v2(ix+1,iy+1)),u),v);};
 const wEdge=p=>wNoise(mul(p,.35))*.67+wNoise(add(mul(p,.7),v2(19.1,7.7)))*.33;

 // Collect all scalar weather* helpers directly from WEATHER_GLSL.
 const scalarNames=[...roofGlsl.matchAll(/float (weather\w+)\(([^)]*)\) \{/g)]
  .filter(m=>!m[2].includes('vec')).map(m=>m[1]);
 const scalarFns=Object.fromEntries(scalarNames.map(n=>[n,scalar(n)]));

 // Slice the REAL preprocessed roof APPLY block from THREE.ShaderChunk.normal_fragment_maps
 // and compile it into a live JS evaluator (identity viewMatrix so world == view space).
 const roofPre=preprocess('#define STANDARD\n#define WEATHER_SURFACE_ACTIVE\n#define WEATHER_SURFACE_ROOF\n'+THREE.ShaderChunk.normal_fragment_maps);
 const roofIfStart=roofPre.indexOf('if(vWeatherOpen>0.0&&weatherSurface.x');
 assert.ok(roofIfStart>=0,'live roof APPLY block found');
 let roofApplySrc=braceBlock(roofPre,roofIfStart);
 // Strip comments and translate GLSL vector expressions mechanically without changing any formula.
 roofApplySrc=roofApplySrc
  .replace(/\/\/[^\n]*/g,'')
  .replaceAll('vWeatherWorld.xz','v2(vWeatherWorld.x,vWeatherWorld.z)')
  .replaceAll('vWeatherWorld.zy','v2(vWeatherWorld.z,vWeatherWorld.y)')
  .replaceAll('vWeatherWorld.xy','v2(vWeatherWorld.x,vWeatherWorld.y)')
  .replaceAll('weatherWorldDx.xz','v2(weatherWorldDx.x,weatherWorldDx.z)')
  .replaceAll('weatherWorldDx.zy','v2(weatherWorldDx.z,weatherWorldDx.y)')
  .replaceAll('weatherWorldDx.xy','v2(weatherWorldDx.x,weatherWorldDx.y)')
  .replaceAll('weatherWorldDy.xz','v2(weatherWorldDy.x,weatherWorldDy.z)')
  .replaceAll('weatherWorldDy.zy','v2(weatherWorldDy.z,weatherWorldDy.y)')
  .replaceAll('weatherWorldDy.xy','v2(weatherWorldDy.x,weatherWorldDy.y)')
  .replaceAll('weatherFace.xz','v2(weatherFace.x,weatherFace.z)')
  .replace('v2(vWeatherWorld.x,vWeatherWorld.z)*.8','mul(v2(vWeatherWorld.x,vWeatherWorld.z),.8)')
  .replace('v2(weatherFace.x,weatherFace.z)/roofSlopeSin','mul(v2(weatherFace.x,weatherFace.z),1/roofSlopeSin)')
  .replace('weatherRoofRivulets(roofUv,roofWetRaw,roofRate,roofPhase,roofDx,roofDy)*(roofSlopeMask*roofRivWeight)',
   'mul(weatherRoofRivulets(roofUv,roofWetRaw,roofRate,roofPhase,roofDx,roofDy),roofSlopeMask*roofRivWeight)')
  .replace('weatherRoofBeads(v2(vWeatherWorld.x,vWeatherWorld.z),roofWetRaw,v2(weatherWorldDx.x,weatherWorldDx.z),v2(weatherWorldDy.x,weatherWorldDy.z),weatherUp)*roofBeadWeight',
   'mul(weatherRoofBeads(v2(vWeatherWorld.x,vWeatherWorld.z),roofWetRaw,v2(weatherWorldDx.x,weatherWorldDx.z),v2(weatherWorldDy.x,weatherWorldDy.z),weatherUp),roofBeadWeight)')
  .replace('diffuseColor.rgb *= ','diffuseColor.rgb = mul(diffuseColor.rgb, ')
  .replace(/(diffuseColor\.rgb = mul\(diffuseColor\.rgb, [^;]+);/,'$1);')
  .replace('vec3(.2126,.7152,.0722)','v3(.2126,.7152,.0722)')
  .replace('vec3(.85,.87,.9)','v3(.85,.87,.9)')
  .replace('vec3(0.0)','v3(0,0,0)')
  .replace('vec2(0.0)','v2(0,0)')
  .replace('mat3(viewMatrix)*((roofAcrossDir*roofRiv.x+roofDownDir*roofRiv.y+vec3(roofBead.x,0.0,roofBead.y)*roofBeadKeep)*(1.0-weatherS))',
   'mul(add(add(mul(roofAcrossDir,roofRiv.x),mul(roofDownDir,roofRiv.y)),mul(v3(roofBead.x,0,roofBead.y),roofBeadKeep)),1-weatherS)')
  .replace('normal+mul(','add(normal,mul(')
  .replace(/(vec3 weatherNormal=add\(normal,mul\([^;]+);/,'$1);')
  .replace('weatherNormal/max(length(weatherNormal),.0001)','mul(weatherNormal,1/max(length(weatherNormal),.0001))')
  .replace('reflect(-roofViewDir,normal)','reflect(neg(roofViewDir),normal)')
  .replace(/vec3\(([^)]+)\)/g,'v3($1)')
  .replace(/vec2\(([^)]+)\)/g,'v2($1)')
  .replace(/\b(?:float|bool|vec2|vec3) (?=\w+\s*=)/g,'let ');

 const roofApplyFn=new Function(
  'weatherSurface','vWeatherWorld','vWeatherOpen','weatherWorldDx','weatherWorldDy','nonPerturbedNormal','normal','vViewPosition','diffuseColor','roughnessFactor','metalnessFactor','viewMatrix',
  'inverseTransformDirection','v2','v3','add','sub','mul','dot','length','normalize','reflect','neg','mix','clamp','smoothstep','abs','min','max','floor','fract',
  'weatherNoise','weatherEdge','weatherRipple','weatherRoofRivulets','weatherRoofBeads',...scalarNames,
  `let weatherHorizonDamp=1.0;
   let _roofAcrossDir=null,_roofDownDir=null,_roofRiv=v3(0,0,0),_roofBead=v3(0,0,0),_roofWaterCov=0,_roofCoatWeight=0,_roofReflected=v3(0,1,0);
   ${roofApplySrc.replace('weatherHorizonDamp=mix(1.0,roofHorizon*roofSheen,roofWetNoSnow);',
    'weatherHorizonDamp=mix(1.0,roofHorizon*roofSheen,roofWetNoSnow);_roofAcrossDir=roofAcrossDir;_roofDownDir=roofDownDir;_roofRiv=roofRiv;_roofBead=roofBead;_roofWaterCov=roofWaterCov;_roofCoatWeight=roofCoatWeight;_roofReflected=roofReflected;')}
   return {color:diffuseColor.rgb,roughness:roughnessFactor,metalness:metalnessFactor,normal,horizonDamp:weatherHorizonDamp,
    acrossDir:_roofAcrossDir,downDir:_roofDownDir,riv:_roofRiv,bead:_roofBead,waterCov:_roofWaterCov,coatWeight:_roofCoatWeight,reflY:_roofReflected.y};`
 );

 function evalRoofApply({world,face,dxWorld=v3(0.003,0,0),dyWorld=v3(0,0,0.003),wet=0,snow=0,puddles=0,rate=0,phase=0,open=1,roughness=0.45,metalness=0.45,albedo=0.04,viewDir=v3(0,0.45,0.89),mapNormal=null}){
  const rgb=typeof albedo==='number'?v3(albedo,albedo,albedo):v3(albedo[0],albedo[1],albedo[2]);
  const w4={x:wet,y:snow,z:puddles,w:Math.round(rate*255)+(rate>0?Math.min(phase,1-1/32768):phase)};
  const n0=norm(face),nMap=mapNormal?norm(mapNormal):n0;
  return roofApplyFn(
   w4,world,open,dxWorld,dyWorld,n0,nMap,viewDir,{rgb},roughness,metalness,null,
   (d)=>norm(d),v2,v3,add,sub,mul,dot,len,norm,refl,neg,mix,clamp,smoothstep,Math.abs,Math.min,Math.max,Math.floor,fract,
   wNoise,wEdge,()=>v2(0,0),rivulets,beads,...scalarNames.map(n=>scalarFns[n]),
  );
 }

 // Slice the REAL preprocessed solid APPLY block for bright-metal vs painted-metal checks.
 const solidPre=preprocess('#define STANDARD\n#define WEATHER_SURFACE_ACTIVE\n'+THREE.ShaderChunk.normal_fragment_maps);
 const solidSliceStart=solidPre.indexOf('float weatherFilmValue=');
 const solidSliceEnd=solidPre.indexOf('float weatherRingWeight=');
 assert.ok(solidSliceStart>=0&&solidSliceEnd>solidSliceStart,'live solid APPLY slice found');
 const solidBody=solidPre.slice(solidSliceStart,solidSliceEnd)
  .replace(/\/\/[^\n]*/g,'')
  .replace(/#[^\n]*/g,'')
  .replaceAll('vWeatherWorld.xz','v2(vWeatherWorld.x,vWeatherWorld.z)')
  .replace('weatherPlane*vec2(12.0,.7)','mul(weatherPlane,v2(12,.7))')
  .replace('dot(diffuseColor.rgb,vec3(.2126,.7152,.0722))','dot(diffuseColor.rgb,v3(.2126,.7152,.0722))')
  .replace('diffuseColor.rgb *= ','diffuseColor.rgb = mul(diffuseColor.rgb, ')
  .replace(/(diffuseColor\.rgb = mul\(diffuseColor\.rgb, [^;]+);/,'$1);')
  .replace('vec3(.85,.87,.9)','v3(.85,.87,.9)')
  .replace(/\b(?:float|bool) (?=\w+\s*=)/g,'let ');
 const solidApplyFn=new Function(
  'weatherSurface','vWeatherWorld','vWeatherOpen','weatherUp','weatherDrop','weatherPlane','diffuseColor','roughnessFactor','metalnessFactor',
  'v2','v3','mul','dot','mix','clamp','smoothstep','abs','max','weatherNoise','weatherEdge',...scalarNames,
  `let weatherMetal=metalnessFactor,weatherWet=weatherExposure(weatherSurface.x,vWeatherOpen);
   ${solidBody}
   return {color:diffuseColor.rgb,roughness:roughnessFactor,metalness:metalnessFactor,waterFilmCov:weatherWaterFilmCov};`
 );
 function evalSolidApply({albedo=0.4,metalness=0.6,roughness=0.45,wet=1,snow=0,puddles=0,open=1,up=1}){
  const rgb=typeof albedo==='number'?v3(albedo,albedo,albedo):v3(albedo[0],albedo[1],albedo[2]);
  return solidApplyFn(
   {x:wet,y:snow,z:puddles,w:0},v3(1.2,0.5,2.3),open,up,0,v2(1.2,2.3),{rgb},roughness,metalness,
   v2,v3,mul,dot,mix,clamp,smoothstep,Math.abs,Math.max,wNoise,wEdge,...scalarNames.map(n=>scalarFns[n]),
  );
 }

 return {rivulets,beads,solidDrops,evalRoofApply,evalSolidApply,rivBody,
  porosityFn:scalarFns.weatherPorosity,darkenWetFn:scalarFns.weatherDarkenWet,
  wetRoughFn:scalarFns.weatherWetRoughness,waterFilmFn:scalarFns.weatherWaterFilm,
  wetScale:scalarFns.weatherWetScale,roughFn:scalarFns.weatherRoughness};
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
  assert.ok(!f.includes('roofSeamRib'),label+' drops normal-map seam heuristic');
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

await test('non-roof programs compile without any roof code and water/sheet/submerged/effect match main byte-for-byte',async()=>{
 const assembleSet=(installFn)=>{
  const renderer=new Renderer(),scene=new THREE.Scene();
  renderer.toneMapping=THREE.ACESFilmicToneMapping;scene.environment=new THREE.Texture();
  const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),layer=installFn(scene);
  const lights=makeLights();lights.directional=[{},{}];lights.hemi=[{}];
  const cache=programs(renderer);
  const items=[
   ['solid',new THREE.MeshStandardMaterial({name:'siding'}),'weather-surface-solid-1',false],
   ['lawn',new THREE.MeshStandardMaterial({name:'lawn'}),'weather-surface-lawn-1',false],
   ['grass',grassMaterial(new THREE.MeshStandardMaterial()),'weather-surface-lawn-1',true],
   ['water',surfaceMaterial(new THREE.MeshPhysicalMaterial()).material,'weather-surface-water-1',false],
   ['sheet',sheetMaterial(),'weather-surface-water-1',false],
   ['submerged',underwaterMaterial(new THREE.MeshStandardMaterial(),{height:0}).material,'weather-surface-submerged-1',false],
   ['effect',waterMaterial(),'weather-surface-effect-1',false],
  ];
  const out={};
  for(const [label,mat,expectedTag,inst] of items){
   const o=inst?new THREE.InstancedMesh(new THREE.BoxGeometry(),mat,1):new THREE.Mesh(new THREE.BoxGeometry(),mat);
   scene.add(o);haze.prepare();shadow.prepare();layer.prepare();
   const src=programSource(renderer,cache,scene,o,lights);
   const b=uniformBudget(src[2]);
   out[label]={expectedTag,customKey:mat.customProgramCacheKey(),key:src.key,vsPre:preprocess(src[1]),fsPre:preprocess(src[2]),vectors:b.vectors,samplers:b.samplers.length};
  }
  layer.dispose();shadow.dispose();haze.dispose();
  return out;
 };

 const branch=assembleSet(installWeatherSurface);
 for(const [label,row] of Object.entries(branch)){
  assert.ok(row.key.includes(row.expectedTag),`${label} key retains ${row.expectedTag}`);
  checkGlslScopes(row.fsPre,label);
  for(const forbidden of ['weatherRoofRivulets','weatherRoofBeads','roofAcrossDir','roofDownDir','roofRiv','roofBead']){
   assert.ok(!row.fsPre.includes(forbidden),`${label} preprocessed source must not contain ${forbidden}`);
  }
  if(['water','sheet','submerged','effect'].includes(label)){
   for(const forbidden of ['weatherPorosity','weatherDarkenWet','weatherWetRoughness','weatherWaterFilm']){
    assert.ok(!row.fsPre.includes(forbidden),`${label} water/submerged/effect must not include porosity/film helpers`);
   }
  }else{
   assert.ok(row.fsPre.includes('weatherPorosity(')&&row.fsPre.includes('weatherDarkenWet(')&&row.fsPre.includes('weatherWaterFilm('),`${label} uses shared porosity and dielectric film model`);
  }
  assert.ok(row.vectors<=224&&row.samplers<=16,label+' within budget');
 }

 if(input.mainSource){
  const withBranch={...THREE.ShaderChunk};
  try{
   Object.assign(THREE.ShaderChunk,BEFORE_WEATHER);
   const mainSrc=input.mainSource.replace("'./stage_haze.js'",JSON.stringify(file('static/twin/sky/stage_haze.js')));
   const mainMod=await import('data:text/javascript;base64,'+Buffer.from(mainSrc).toString('base64'));
   const main=assembleSet(mainMod.installWeatherSurface);
   for(const label of Object.keys(branch)){
    assert.equal(branch[label].customKey,main[label].customKey,`${label} customProgramCacheKey matches main`);
    assert.equal(branch[label].vsPre,main[label].vsPre,`${label} vertex shader matches main byte-for-byte`);
    assert.equal(branch[label].vectors,main[label].vectors,`${label} uniform vectors match main`);
    assert.equal(branch[label].samplers,main[label].samplers,`${label} sampler count matches main`);
    if(['water','sheet','submerged','effect'].includes(label)){
     assert.equal(branch[label].fsPre,main[label].fsPre,`${label} fragment shader matches main byte-for-byte`);
    }
   }
  }finally{
   Object.assign(THREE.ShaderChunk,withBranch);
  }
 }
});

const ev=buildEvaluators();

await test('dry roof (wetness 0) matches main identically even while raining; snow cover wins over full wetness',()=>{
 const face=v3(0,Math.cos(0.4),Math.sin(0.4));
 const dx=v3(0.004,0,0),dy=v3(0,-0.002,0.003);
 for(const rate of [0,1])for(const phase of [0,0.37,0.89]){
  for(let i=0;i<25;i++){
   const world=v3(i*0.13-1.5,3.5-i*0.04,i*0.11);
   const r=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:0,snow:0,rate,phase,roughness:0.45,metalness:0.45,albedo:0.04});
   close(r.color.x,0.04);close(r.roughness,0.45);close(r.metalness,0.45);
   close(r.horizonDamp,1.0);
   close(r.normal.x,face.x);close(r.normal.y,face.y);close(r.normal.z,face.z);
  }
 }
 for(let i=0;i<25;i++){
  const world=v3(i*0.17,4.0,i*0.09);
  const s=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:1,snow:1,rate:1,phase:0.5,roughness:0.45,metalness:0.45,albedo:0.04});
  close(s.color.x,0.85,1e-5);close(s.color.y,0.87,1e-5);close(s.color.z,0.90,1e-5);
  close(s.roughness,0.7);close(s.metalness,0.0);
  close(s.horizonDamp,1.0);
  close(s.normal.x,face.x);close(s.normal.y,face.y);close(s.normal.z,face.z);
 }
});

await test('rivulets align with the downhill direction on arbitrarily rotated pitched faces, flow while raining and freeze when rain stops',()=>{
 const dx=v2(0.003,0),dy=v2(0,0.003);
 for(const azDeg of [0,35,120,245,357.6])for(const pitchRatio of [4/12,6/12,10/12]){
  const az=azDeg*Math.PI/180,pitch=Math.atan(pitchRatio);
  const face=v3(Math.sin(pitch)*Math.cos(az),Math.cos(pitch),Math.sin(pitch)*Math.sin(az));
  const out=ev.evalRoofApply({world:v3(2,4,-3),face,dxWorld:v3(0.003,0,0),dyWorld:v3(0,0,0.003),wet:1,rate:1,phase:0.2});
  close(len(out.acrossDir),1,1e-5);close(len(out.downDir),1,1e-5);
  close(dot(out.acrossDir,face),0,1e-5);close(dot(out.downDir,face),0,1e-5);
  close(dot(out.acrossDir,out.downDir),0,1e-5);
  assert.ok(out.downDir.y<-0.1,'downDir points strictly downhill');
  close(out.acrossDir.y,0,1e-5);
 }
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
 const pMatch=ev.rivBody.match(/p1=uv\.y\*\(([\d.]+)\+h\.y\*([\d.]+)\)/);
 const ampMatch=ev.rivBody.match(/sin\(p1\)\*\(([\d.]+)\//);
 assert.ok(pMatch&&ampMatch,'wander parameters found in live GLSL');
 const maxF1=Number(pMatch[1])+Number(pMatch[2]),wanderAmpM=Number(ampMatch[1]);
 assert.ok(wanderAmpM<=0.015,`wander amplitude <= 1.5 cm (${wanderAmpM}m)`);
 assert.ok(2*Math.PI/maxF1>=6.0,`long wander wavelength >= 6 m (${(2*Math.PI/maxF1).toFixed(2)}m)`);

 let motionPour=0,motionStop=0,wrapErr=0,movedDown=0,movedUp=0;
 for(let i=0;i<300;i++){
  const p=v2((i%30)*0.08,Math.floor(i/30)*0.21);
  const a=ev.rivulets(p,1,1,0.10,dx,dy);
  const b=ev.rivulets(p,1,1,0.35,dx,dy);
  motionPour+=Math.abs(b.z-a.z)+Math.abs(b.y-a.y);
  const shift=ev.rivulets(v2(p.x,p.y+0.14),1,1,0.10+0.05,dx,dy);
  const opp=ev.rivulets(v2(p.x,p.y-0.14),1,1,0.10+0.05,dx,dy);
  movedDown+=Math.abs(shift.z-a.z);movedUp+=Math.abs(opp.z-a.z);
  const w0=ev.rivulets(p,1,1,0.0,dx,dy),w1=ev.rivulets(p,1,1,1.0,dx,dy);
  wrapErr=Math.max(wrapErr,Math.abs(w1.z-w0.z),Math.abs(w1.x-w0.x),Math.abs(w1.y-w0.y));
  const s0=ev.evalRoofApply({world:v3(p.x,4,p.y),face:v3(0,0.894,0.447),wet:1,rate:0,phase:0.1});
  const s1=ev.evalRoofApply({world:v3(p.x,4,p.y),face:v3(0,0.894,0.447),wet:1,rate:0,phase:0.73});
  motionStop+=Math.abs(s1.riv.z-s0.riv.z)+Math.abs(s1.normal.x-s0.normal.x)+Math.abs(s1.normal.y-s0.normal.y)+Math.abs(s1.roughness-s0.roughness);
 }
 assert.ok(motionPour>0.5,`rivulets animate while raining (${motionPour.toFixed(3)})`);
 assert.ok(movedDown<movedUp,`rivulet surges travel downhill (${movedDown.toFixed(3)} < ${movedUp.toFixed(3)})`);
 assert.ok(wrapErr<1e-5,`4-second clock wrap is seamless (${wrapErr})`);
 assert.equal(motionStop,0,'stopped rain (rate=0, wetness=1) yields strictly static wet streaks');
 console.log('RIVULET_METRICS',JSON.stringify({alignRatio:+alignRatio.toFixed(2),peakCov:+peakCov.toFixed(3),minCov:+minCov.toFixed(3),wanderAmpM,motionPour:+motionPour.toFixed(3),wrapErr}));
});

await test('bright bare metals keep metalness and diffuse when wet; dark painted roofs still get untinted dielectric film; light roofs stay bounded',()=>{
 // Blocking item 1: solid bright metals (galvanized conduit #a7adb3 ~0.415 linear, metalness 0.6;
 // chain-link 0.65; gas fire-pit pan 0.85) must NOT turn into diffuse plastic when wet.
 const conduitDry=ev.evalSolidApply({albedo:0.415,metalness:0.60,roughness:0.45,wet:0});
 const conduitWet=ev.evalSolidApply({albedo:0.415,metalness:0.60,roughness:0.45,wet:1});
 close(conduitWet.metalness,0.60,1e-4);
 const conduitDiffDry=conduitDry.color.x*(1-conduitDry.metalness);
 const conduitDiffWet=conduitWet.color.x*(1-conduitWet.metalness);
 assert.ok(Math.abs(conduitDiffWet-conduitDiffDry)<0.01,`galvanized conduit keeps diffuse (${conduitDiffDry.toFixed(3)} -> ${conduitDiffWet.toFixed(3)})`);
 const chainWet=ev.evalSolidApply({albedo:0.38,metalness:0.65,roughness:0.45,wet:1});
 const panWet=ev.evalSolidApply({albedo:0.35,metalness:0.85,roughness:0.35,wet:1});
 close(chainWet.metalness,0.65,1e-4);
 close(panWet.metalness,0.85,1e-4);
 // Bright metal on a roof face also stays metallic and unboosted.
 const face=v3(0,0.894,0.447);
 const brightMetalRoof=ev.evalRoofApply({world:v3(1.1,4,1.3),face,wet:1,rate:0,roughness:0.35,metalness:0.65,albedo:0.42});
 close(brightMetalRoof.metalness,0.65,1e-4);
 assert.ok(brightMetalRoof.horizonDamp<=1.01,`bright metal roof is not sheen-boosted (${brightMetalRoof.horizonDamp.toFixed(3)})`);

 // Dark painted metal roof (#2f3133 linear ~0.028, #3a2e27 bronze, metalness 0.45) still gets untinted dielectric film.
 const darkBronze=[0.042,0.027,0.020];
 const darkRoof=ev.evalRoofApply({world:v3(1.1,4,1.3),face,wet:1,rate:1,phase:0.3,roughness:0.45,metalness:0.45,albedo:darkBronze});
 assert.ok(darkRoof.metalness<0.05,`dark painted metal roof drops metalness under water film (0.45 -> ${darkRoof.metalness.toFixed(4)})`);
 const f0R3=darkBronze.map(c=>mix(0.04,c,0.45));
 const f0R5=darkBronze.map(c=>mix(0.04,c,darkRoof.metalness));
 const chroma=rgb=>Math.max(...rgb)-Math.min(...rgb);
 const luma=rgb=>rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
 assert.ok(chroma(f0R5)<chroma(f0R3)*0.15,'wet dark metal roof specular F0 is untinted (near-grey)');
 assert.ok(luma(f0R5)>luma(f0R3)*1.10,'wet dark metal roof dielectric F0 is brighter than round 3 tinted F0');

 // Item 4: light smooth non-metal roofs (white membrane, glazed tile) with residual wetness (rate=0)
 // under bright sky stay within a sane bound (no 1.5-3.9x radiance blowout).
 for(const [name,albedo,roughness] of [['white membrane',0.82,0.28],['glazed tile',0.48,0.18],['light stucco roof',0.55,0.35]]){
  for(const viewDir of [v3(0,0.45,0.89),v3(0,0.08,0.997),v3(0,0.85,0.52)]){
   const lightRoof=ev.evalRoofApply({world:v3(0.7,4,1.1),face,wet:1,rate:0,roughness,metalness:0.0,albedo,viewDir});
   assert.ok(lightRoof.horizonDamp<=1.01,`${name} residual wetness under bright sky stays bounded (${lightRoof.horizonDamp.toFixed(3)})`);
   close(lightRoof.coatWeight,0,1e-5);
  }
 }
 // Dark painted solid trim (albedo 0.04, metalness 0.45) still gets dielectric film; snow zeroes metalness even on bright metal.
 const darkTrimWet=ev.evalSolidApply({albedo:0.04,metalness:0.45,roughness:0.45,wet:1});
 assert.ok(darkTrimWet.metalness<0.05,`dark painted solid trim gets dielectric film (${darkTrimWet.metalness.toFixed(4)})`);
 const conduitSnow=ev.evalSolidApply({albedo:0.415,metalness:0.60,roughness:0.45,wet:1,snow:1});
 close(conduitSnow.metalness,0,1e-4);
});

await test('shared porosity: ordering, darkening, gloss, porous shingle vs metal roof',()=>{
 const pMetal=ev.porosityFn(1.0,0.45),pTile=ev.porosityFn(0.0,0.45),pMetalRoof=ev.porosityFn(0.45,0.45),pConcrete=ev.porosityFn(0.0,0.85),pShingle=ev.porosityFn(0.0,0.90);
 assert.ok(pMetal<pTile&&pTile<pConcrete,'porosity ordering: metal < semi-smooth tile < rough concrete');
 assert.ok(pMetalRoof<0.15&&pConcrete>=0.99&&pShingle>=0.99,'painted metal low porosity, concrete/shingles high');
 const lum=0.6;
 const dMetal=1-ev.wetScale(lum,1.0,ev.darkenWetFn(pMetal,1.0));
 const dTile=1-ev.wetScale(lum,0.0,ev.darkenWetFn(ev.porosityFn(0.0,0.22),1.0));
 const dPorousEarly=1-ev.wetScale(lum,0.0,ev.darkenWetFn(pConcrete,0.4));
 const dPorousFull=1-ev.wetScale(lum,0.0,ev.darkenWetFn(pConcrete,1.0));
 assert.ok(dMetal<0.02,`metal barely darkens (${dMetal.toFixed(4)})`);
 assert.ok(dTile<0.08,`smooth tile barely darkens (${dTile.toFixed(4)})`);
 assert.ok(dPorousEarly>0.22&&dPorousFull>0.48,`porous darkens early and strongly (${dPorousEarly.toFixed(3)} -> ${dPorousFull.toFixed(3)})`);
 for(const [m,r] of [[1.0,0.35],[0.45,0.45],[0.0,0.22],[0.0,0.85]]){
  const p=ev.porosityFn(m,r);
  close(ev.wetScale(0.6,m,ev.darkenWetFn(p,0)),1.0);
  close(ev.wetRoughFn(r,p,0),r);
  close(ev.waterFilmFn(p,0,0),0);
 }
 for(const w of [0.3,0.6,1.0]){
  const rMetal=ev.wetRoughFn(0.45,pMetal,w);
  const rSmooth=ev.wetRoughFn(0.30,ev.porosityFn(0.0,0.30),w);
  const rPorous=ev.wetRoughFn(0.85,pConcrete,w);
  assert.ok(rMetal<rPorous&&rSmooth<rPorous,`at wet=${w}, metal & smooth < porous`);
  close(ev.roughFn(rPorous,0,1,0),0.03);
 }
 assert.ok(ev.wetRoughFn(0.85,pConcrete,1.0)>0.35,'porous concrete/shingle stays well above thin-film roughness without puddles');
 assert.ok(ev.wetRoughFn(0.45,pMetal,1.0)<=0.12,'wet metal reaches thin-film roughness');
 close(ev.waterFilmFn(1.0,0.5,0.0),0);
 close(ev.waterFilmFn(1.0,0.5,1.0),1.0);

 const face=v3(0,0.894,0.447),dx=v3(0.002,0,0),dy=v3(0,0,0.002);
 let metalRiv=0,shingleRiv=0,metalBead=0,shingleBead=0,metalRough=0,shingleRough=0,shingleDark=0,metalDark=0,metalEffSum=0;
 for(let i=0;i<240;i++){
  const world=v3((i%24)*0.07,4.0,Math.floor(i/24)*0.11);
  const rm=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:1,rate:1,phase:0.3,roughness:0.45,metalness:0.45,albedo:0.06});
  const rs=ev.evalRoofApply({world,face,dxWorld:dx,dyWorld:dy,wet:1,rate:1,phase:0.3,roughness:0.88,metalness:0.0,albedo:0.30});
  metalRiv+=rm.riv.z;shingleRiv+=rs.riv.z;
  metalBead+=rm.bead.z;shingleBead+=rs.bead.z;
  metalRough+=rm.roughness;shingleRough+=rs.roughness;
  metalDark+=1-rm.color.x/0.06;shingleDark+=1-rs.color.x/0.30;
  metalEffSum+=rm.metalness;
 }
 assert.ok(metalEffSum/240<0.05,`wet dark metal roof effective metalness drops (${(metalEffSum/240).toFixed(4)})`);
 assert.ok(shingleRiv<metalRiv*0.25,`rivulets much fainter on porous shingles (${shingleRiv.toFixed(2)} vs ${metalRiv.toFixed(2)})`);
 assert.equal(shingleBead,0,'beads soak into porous shingle roof');
 assert.ok(metalBead>5,'beads remain on impervious metal roof');
 assert.ok(shingleRough/240>0.32&&metalRough/240<0.15,`porous roof keeps soft sheen (${(shingleRough/240).toFixed(3)}) vs glossy metal (${(metalRough/240).toFixed(3)})`);
 assert.ok(shingleDark/240>metalDark/240*2,'porous shingle roof darkens significantly more than metal roof');
 console.log('POROSITY_ROOF',JSON.stringify({metalEff:+(metalEffSum/240).toFixed(4),metalRough:+(metalRough/240).toFixed(3),shingleRough:+(shingleRough/240).toFixed(3),metalRiv:+metalRiv.toFixed(2),shingleRiv:+shingleRiv.toFixed(2)}));
});

await test('beads stay at wetness=1 on roofs only, wet film stays glossy with no blanket damp, and near-flat roofs have zero basis jump',()=>{
 const dx=v2(0.001,0),dy=v2(0,0.001);
 let roofBeadCov=0,roofBeadSlope=0,solidDropSum=0,hits=0;
 let minRough=1,maxFilmRough=0,minFilmRough=1,minSkyFilmDamp=Infinity,maxRivDamp=0;
 const face=v3(0,0.894,0.447),skyView=v3(0,0.45,0.89);
 for(let i=0;i<600;i++){
  const u=(i%30)*0.043,v=Math.floor(i/30)*0.047;
  const b=ev.beads(v2(u,v),1,dx,dy,face.y);
  roofBeadCov+=b.z;roofBeadSlope+=Math.hypot(b.x,b.y);
  if(b.z>0.5)hits++;
  solidDropSum+=ev.solidDrops(v2(u,v),1,dx,dy,face.y);
  const frag=ev.evalRoofApply({world:v3(u,4,v),face,dxWorld:v3(0.001,0,0),dyWorld:v3(0,0,0.001),wet:1,rate:1,phase:0.3,roughness:0.45,metalness:0.45,albedo:0.04,viewDir:skyView});
  minRough=Math.min(minRough,frag.roughness);
  if(frag.waterCov<0.02){
   maxFilmRough=Math.max(maxFilmRough,frag.roughness);minFilmRough=Math.min(minFilmRough,frag.roughness);
   if(frag.reflY>=0.5)minSkyFilmDamp=Math.min(minSkyFilmDamp,frag.horizonDamp);
  }
  if(frag.riv.z>0.5)maxRivDamp=Math.max(maxRivDamp,frag.horizonDamp);
  assert.ok(frag.color.x>0.0395&&frag.color.x<=0.04,'dark metal roof has no dark bead dots');
 }
 assert.equal(solidDropSum,0,'non-roof surfaces still remove drop stains at wetness=1');
 assert.ok(hits>30&&roofBeadCov/600>0.05,`beads remain present on roofs at wetness=1 (hits=${hits}, avg=${(roofBeadCov/600).toFixed(4)})`);
 assert.ok(roofBeadSlope/600>0.01,'beads perturb normals as raised domes');
 assert.ok(minRough<=0.055,`rivulets/beads reach low glossy roughness (${minRough.toFixed(4)})`);
 assert.ok(minFilmRough>=0.075&&maxFilmRough<=0.16,`between-rivulet metal film roughness stays glossy (${minFilmRough.toFixed(3)}..${maxFilmRough.toFixed(3)})`);
 assert.ok(minSkyFilmDamp>=1.0,`no blanket horizon damp darkening on upward sky reflections (${minSkyFilmDamp.toFixed(3)})`);
 assert.ok(maxRivDamp>minSkyFilmDamp*1.12,`calm rivulets lift gently within the sky sheen (${maxRivDamp.toFixed(2)} vs ${minSkyFilmDamp.toFixed(2)})`);

 const grazing=ev.evalRoofApply({world:v3(0.5,4,0.5),face:v3(0,0.94,0.34),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0,viewDir:v3(0,0.05,0.999)});
 const headOn=ev.evalRoofApply({world:v3(0.5,4,0.5),face:v3(0,0.707,0.707),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0,viewDir:v3(0,0.65,0.76)});
 assert.ok(grazing.horizonDamp>headOn.horizonDamp*0.95,'grazing sky reflection stays bright');
 const belowHorizon=ev.evalRoofApply({world:v3(0.5,4,0.5),face:v3(0,0.28,0.96),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:0,phase:0,viewDir:v3(0,0.85,0.52)});
 assert.ok(belowHorizon.reflY<0.04&&belowHorizon.horizonDamp<0.6,`rays pointing at/below horizon still damp (${belowHorizon.reflY.toFixed(2)} -> ${belowHorizon.horizonDamp.toFixed(2)})`);

 // Item 5: barrel-tile/embossed normal map perturbation does not inject fake runnels.
 const flatPan=ev.evalRoofApply({world:v3(0.11,4,0.3),face,dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:1,phase:0.2,roughness:0.88,metalness:0.0,albedo:0.25});
 const embossed=ev.evalRoofApply({world:v3(0.11,4,0.3),face,mapNormal:v3(0.35,0.85,0.39),dxWorld:v3(0.01,0,0),dyWorld:v3(0,0,0.01),wet:1,rate:1,phase:0.2,roughness:0.88,metalness:0.0,albedo:0.25});
 close(embossed.roughness,flatPan.roughness,1e-6);

 // Item 6: flat and near-flat smooth-shaded roofs stay finite with ZERO jump across slopeSin = 0.001 at every azimuth.
 const flat=ev.evalRoofApply({world:v3(1.2,4,2.3),face:v3(0,1,0),dxWorld:v3(0.001,0,0),dyWorld:v3(0,0,0.001),wet:1,rate:1,phase:0.5});
 assert.ok([flat.roughness,flat.color.x,flat.horizonDamp,flat.normal.x,flat.normal.y,flat.normal.z].every(Number.isFinite),'flat roof stays finite');
 close(flat.riv.z,0);close(flat.riv.x,0);close(flat.riv.y,0);
 for(const azDeg of [0,90,180,270]){
  const az=azDeg*Math.PI/180;
  let prev=null,prevS=0;
  for(const s of [0,0.0005,0.0009,0.0011,0.002,0.01,0.019,0.021,0.025]){
   const f=v3(s*Math.cos(az),Math.sqrt(1-s*s),s*Math.sin(az));
   const cur=ev.evalRoofApply({world:v3(1.23,4,2.37),face:f,dxWorld:v3(0.003,0,0),dyWorld:v3(0,0,0.003),wet:1,rate:1,phase:0.3});
   assert.ok([cur.roughness,cur.horizonDamp,cur.normal.x,cur.normal.y,cur.normal.z].every(Number.isFinite));
   if(prev){
    const ds=s-prevS;
    if(s<=0.019)close(cur.roughness,prev.roughness,1e-5);
    assert.ok(Math.abs(cur.horizonDamp-prev.horizonDamp)<8.0*ds+1e-3,`continuous near-flat horizonDamp at az=${azDeg} s=${s} (d=${Math.abs(cur.horizonDamp-prev.horizonDamp).toFixed(5)}, ds=${ds})`);
    assert.ok(len(sub(cur.normal,prev.normal))<2.0*ds+1e-3,`continuous near-flat normal at az=${azDeg} s=${s} (d=${len(sub(cur.normal,prev.normal)).toFixed(5)}, ds=${ds})`);
   }
   prev=cur;prevS=s;
  }
 }
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
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'mainSource': main_weather_source()}, timeout=180)
    print(output)
    sys.exit(code)
