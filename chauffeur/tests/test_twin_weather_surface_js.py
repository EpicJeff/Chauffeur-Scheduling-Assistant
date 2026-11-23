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
const {installWeatherSurface,WEATHER_GLSL,standingWaterAt}=await import(path);
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
 return new Function('mix','clamp','smoothstep','max','exp','abs','sin','step',`return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(mix,clamp,smoothstep,Math.max,Math.exp,Math.abs,Math.sin,(a,v)=>v<a?0:1);
};
{
// Execute the installed vector functions with only GLSL's vector arithmetic
// translated. All constants, gates, radii, waves and AA come from production.
const v2=(x,y=x)=>({x,y}),fract=x=>x-Math.floor(x),dot=(a,b)=>a.x*b.x+a.y*b.y;
const sub=(a,b)=>v2(a.x-b.x,a.y-b.y),div=(a,b)=>v2(a.x/b,a.y/b);
const vecBody=(name,type='vec2')=>{
 const m=WEATHER_GLSL.match(new RegExp(type+' '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'));
 assert.ok(m,name);return m[1];
};
const ringHash=new Function('p','fract',vecBody('weatherRingHash','vec3')
 .replace('vec3 q=fract(vec3(p.x,p.y,p.x)*vec3(.1031,.1030,.0973));','let q={x:fract(p.x*.1031),y:fract(p.y*.1030),z:fract(p.x*.0973)};')
 .replace('q+=dot(q,q.yxz+33.33);','const d=q.x*(q.y+33.33)+q.y*(q.x+33.33)+q.z*(q.z+33.33);q={x:q.x+d,y:q.y+d,z:q.z+d};')
 .replace('return fract((q.xxy+q.yzz)*q.zyx);','return {x:fract((q.x+q.y)*q.z),y:fract((q.x+q.z)*q.y),z:fract((q.y+q.z)*q.x)};'));
const hash=p=>ringHash(p,fract);
const radius=scalar('weatherDropRadius');
const dropCell=new Function('id','cellSize','up','weatherRingHash','weatherDropRadius','weatherDropDensity','fract',vecBody('weatherDropCell','vec4')
 .replace('vec3 random=','let random=').replace('float radius=','let radius=')
 .replace('vec2 centre=vec2(radius)+random.xy*(1.0-2.0*radius);','let centre={x:radius+random.x*(1-2*radius),y:radius+random.y*(1-2*radius)};')
 .replace('float arrival=','let arrival=')
 .replace('vec4(centre,radius,fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival)','({x:centre.x,y:centre.y,z:radius,w:fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival})'));
const density=scalar('weatherDropDensity'),spotCoverage=scalar('weatherSpot'),dropTone=scalar('weatherDropTone');
const cell=(id,size=.047,up=1)=>dropCell(id,size,up,hash,radius,density,fract);
const layerBody=vecBody('weatherDropLayer','float')
 .replace('vec2 p=world/cellSize,id=floor(p);','let p=div(world,cellSize),id=v2(Math.floor(p.x),Math.floor(p.y));')
 .replace('vec2 local=fract(p)-spot.xy;','let local=sub(v2(fract(p.x),fract(p.y)),spot);')
 .replace('vec2 direction=local/max(d,.001);','let direction=div(local,max(d,.001));')
 .replace(/\b(?:float|vec4) (?=\w+=)/g,'let ');
const layerFn=new Function('world','wet','dx','dy','cellSize','up','weatherDropCell','weatherSpot','weatherDropTone','div','sub','v2','fract','length','dot','max','abs','smoothstep','mix',layerBody);
const layer=(world,wet,dx,dy,size,up)=>layerFn(world,wet,dx,dy,size,up,cell,spotCoverage,dropTone,div,sub,v2,fract,p=>Math.hypot(p.x,p.y),dot,Math.max,Math.abs,smoothstep,mix);
const dropsFn=new Function('world','wet','dx','dy','up','smoothstep','abs','v2','weatherDropLayer',vecBody('weatherDrops','float')
 .replace('vec2 stretch=vec2(1.0,1.0-.35*vertical);','let stretch=v2(1,1-.35*vertical);')
 .replace('world*=stretch;dx*=stretch;dy*=stretch;','world=v2(world.x*stretch.x,world.y*stretch.y);dx=v2(dx.x*stretch.x,dx.y*stretch.y);dy=v2(dy.x*stretch.x,dy.y*stretch.y);')
 .replace('mat2 rotation=mat2(.8,.6,-.6,.8);','const rotation=p=>({x:.8*p.x-.6*p.y,y:.6*p.x+.8*p.y});')
 .replace('rotation*world+vec2(1.731,4.913)','({x:rotation(world).x+1.731,y:rotation(world).y+4.913})')
 .replaceAll('rotation*dx','rotation(dx)').replaceAll('rotation*dy','rotation(dy)').replace(/\bfloat (?=\w+=)/g,'let '));
await test('production drop centres lose the lattice, physical radii and sparse vertical stains, empty cells and derivative integration survive',()=>{
 const bins=Array(10).fill(0),radii=[];let empty=0,samples=0;
 for(let x=-60;x<60;x++)for(let y=-60;y<60;y++){
  const c=cell(v2(x,y));if(c.w>1){empty++;continue;}
  assert.ok(c.x>=c.z&&c.y>=c.z&&c.x<=1-c.z&&c.y<=1-c.z,'complete discs within cells');
  // The second layer's inverse rotation/offset is the actual world centre.
  const rx=(x+c.x)*.047-1.731,ry=(y+c.y)*.047-4.913;
  const worldX=.8*rx+.6*ry;
  bins[Math.floor(fract(worldX/.03)*10)]++;radii.push(c.z*.047);samples++;
 }
 const mean=samples/10;
 assert.ok(bins.every(n=>Math.abs(n-mean)<mean*.08),'centres modulo the former 3cm lattice approach uniform');
 assert.ok(Math.max(...radii)/Math.min(...radii)>3);
 assert.ok(empty/14400>.17&&empty/14400<.23);
 assert.ok(radii.filter(r=>r>=.0025&&r<=.0075).length/radii.length>=.9);
 let horizontal=0,vertical=0;
 for(let x=-60;x<60;x++)for(let y=-60;y<60;y++){
  horizontal+=cell(v2(x,y),.031,1).w<=1?1:0;vertical+=cell(v2(x,y),.031,0).w<=1?1:0;
 }
 assert.ok(vertical/horizontal<=1/3);console.log('VERTICAL_SPOT_DENSITY',vertical/horizontal);
 for(const wet of [0,.1,.3,.6,1]){
  let total=0;
  for(let i=0;i<300;i++){
   const world=v2(i*.0137,i*.0311),value=dropsFn(world,wet,v2(.0001,0),v2(0,.0001),1,smoothstep,Math.abs,v2,layer);
   assert.ok(Number.isFinite(value)&&value>=0&&value<=1);total+=value;
  }
  if(wet===0||wet===1)assert.equal(total,0);else assert.ok(total>0);
 }
 const tone=scalar('weatherDropTone');
 assert.ok(tone(.1,.2,.8)>tone(.3,.2,.8));assert.equal(tone(1,.2,.8),0);
 let coarse=0;
 for(let i=0;i<100;i++)coarse+=dropsFn(v2(i*.0317,i*.019),.2,v2(1,0),v2(0,1),1,smoothstep,Math.abs,v2,layer);
 assert.ok(coarse>0&&coarse/100<.3,'distant stains integrate to nonzero bounded area');
 let cx=2,c=cell(v2(cx,3),.047,1);while(c.w>1){cx++;c=cell(v2(cx,3),.047,1);}
 const wet=Math.min(.65,c.w*.35+.03),r=c.z*.047;
 const centre=v2((cx+c.x)*.047,(3+c.y)*.047),dx=v2(.000001,0),dy=v2(0,.000001);
 {
  const middle=layer(centre,wet,dx,dy,.047,1),edge=layer(v2(centre.x+r,centre.y),wet,dx,dy,.047,1);
  assert.ok(middle>edge&&edge>0,'soft half-strength stain boundary');
 }

 console.log('DROP_DISTRIBUTION',JSON.stringify({bins,radiusRatio:Math.max(...radii)/Math.min(...radii),empty:empty/14400,inRange:radii.filter(r=>r>=.0025&&r<=.0075).length/radii.length,minRadius:Math.min(...radii),maxRadius:Math.max(...radii)}));
});
await test('overcast owner-eye patio luminance never increases through the complete wetness ramp',async()=>{
 // Execute the installed material block, including its exposure, colour,
 // gloss, puddle and horizon wiring; use the production drops above.
 const installed=installWeatherSurface(new THREE.Scene());installed.dispose();
 const apply=preprocess('#define STANDARD\n#define WEATHER_SURFACE_ACTIVE\n'+THREE.ShaderChunk.normal_fragment_maps);
 let body=apply.slice(apply.indexOf('float weatherFilmValue='),apply.indexOf('metalnessFactor=mix('))
  .replace(/\b(?:float|bool) (?=\w+=)/g,'let ')
  .replace('dot(diffuseColor.rgb,vec3(.2126,.7152,.0722))','diffuseColor.rgb')
  .replace('vec3(.85,.87,.9)','.87').replace('weatherPlane*vec2(12.0,.7)','weatherPlane');
 const names=[...WEATHER_GLSL.matchAll(/float (weather\w+)\(([^)]*)\) \{/g)]
  .filter(m=>!m[2].includes('vec')).map(m=>m[1]);
 const functions=names.map(scalar);
 const surface=new Function('wet','drop','edge','albedo','original','open',...names,'mix','abs','weatherEdge',
  `const weatherSurface={x:wet,y:0,z:wet},vWeatherOpen=open,weatherUp=1,weatherMetal=0,weatherDrop=drop,weatherPlane=0,vWeatherWorld={xz:0};
   let weatherWet=wet*open,roughnessFactor=original;const diffuseColor={rgb:albedo};
   ${body}\nreturn {albedo:diffuseColor.rgb,roughness:roughnessFactor,gloss:weatherGlossValue,puddle:weatherP,snow:weatherS,wet:weatherWet};`);
 // r187 uses a 16x16 half-float DFG LUT, not the old analytic approximation.
 // Sample its actual data with WebGL's linear/clamp rules.
 const source=readFileSync(new URL(file('static/vendor/three-r187/three.module.js')),'utf8');
 const data=Function('return ['+source.match(/const DATA = new Uint16Array\( \[([\s\S]*?)\] \);/)[1]+']')().map(x=>THREE.DataUtils.fromHalfFloat(x));
 assert.equal(data.length,16*16*2);
 const dfg=(rough,nv)=>{const x=rough*16-.5,y=nv*16-.5,ix=Math.floor(x),iy=Math.floor(y);
  const at=(x,y,c)=>data[(clamp(y,0,15)*16+clamp(x,0,15))*2+c];
  return Object.fromEntries(['x','y'].map((key,c)=>[key,mix(mix(at(ix,iy,c),at(ix+1,iy,c),x-ix),mix(at(ix,iy+1,c),at(ix+1,iy+1,c),x-ix),y-iy)]));};
 const physical=preprocess(THREE.ShaderChunk.lights_physical_pars_fragment);
 const scatterBody=physical.match(/void computeMultiscattering\([^)]*\) \{([\s\S]*?)\n\}/)[1]
  .replace(/\b(?:vec3|float) /g,'let ');
 const scatter=new Function('fab','specularColor','specularF90',`let singleScatter=0,multiScatter=0;${scatterBody};return {single:singleScatter,multi:multiScatter};`);
 // Execute r187's indirect-light combination, scalarized for a neutral sky.
 const indirectBody=physical.slice(physical.indexOf('vec3 diffuse = material.diffuseContribution'),physical.indexOf('reflectedLight.indirectSpecular += indirectSpecular;'))
  .replace(/\b(?:vec3|float) /g,'let ');
 const indirect=new Function('material','totalScatteringDielectric','radiance','singleScattering','multiScattering','irradiance','RECIPROCAL_PI',indirectBody+'\nreturn indirectSpecular+indirectDiffuse;');
 const horizon=scalar('weatherHorizon');
 const damping=new Function('nv','weatherWet','weatherGlossValue','weatherP','weatherS','weatherHorizon','smoothstep',
  'return '+apply.match(/weatherHorizonDamp=([^;]+);/)[1].replace('weatherReflected.y','nv').replace(/\bmax\(/g,'Math.max('));
 const light=(s,nv,diffuseSky)=>{const f=scatter(dfg(Math.max(.0525,s.roughness),nv),.04,1),damp=damping(nv,s.wet,s.gloss,s.puddle,s.snow,horizon,smoothstep);
  return indirect({diffuseContribution:s.albedo},f.single+f.multi,.6*damp,f.single,f.multi,.6*Math.PI*diffuseSky,1/Math.PI);};
 const {buildingFootprint,groundAt}=await import(file('static/twin/twin_ground.js'));
 const b=input.plan.buildings.find(b=>['pool-house','pool_house'].includes(b.id)),ft=.3048,a=(b.rotation||0)*Math.PI/180;
 const world=([x,y])=>[(b.position?.[0]||0)+x*Math.cos(a)-y*Math.sin(a),(b.position?.[1]||0)+x*Math.sin(a)+y*Math.cos(a)];
 const bounds=points=>{const lo=[0,1].map(i=>Math.min(...points.map(p=>p[i]))),hi=[0,1].map(i=>Math.max(...points.map(p=>p[i])));return {lo,hi,centre:lo.map((x,i)=>(x+hi[i])/2)};};
 const house=bounds(buildingFootprint(b).map(world)),pool=bounds(input.plan.site.pool.polygon);
 const d=pool.centre.map((x,i)=>x-house.centre[i]),length=Math.hypot(...d);d.forEach((x,i)=>d[i]=x/length);
 const edge=Math.min(...d.map((x,i)=>Math.abs(x)>1e-9?(house.hi[i]-house.lo[i])/2/Math.abs(x):Infinity));
 const eye=house.centre.map((x,i)=>x+d[i]*(edge+12.5/ft)),ground=groundAt(input.plan,...eye)*ft;
 const camera=new THREE.PerspectiveCamera(38,1600/900,.1,1000);camera.position.set(eye[0]*ft,ground+1.6,-eye[1]*ft);
 camera.lookAt(house.centre[0]*ft,ground,-house.centre[1]*ft);camera.updateMatrixWorld(true);
 const plane=new THREE.Plane(new THREE.Vector3(0,1,0),-ground),ray=new THREE.Raycaster();
 const hit=(x,y)=>{ray.setFromCamera(new THREE.Vector2(x/800-1,1-y/450),camera);return ray.ray.intersectPlane(plane,new THREE.Vector3());};
 const samples=[];
 for(let y=502;y<570;y+=4)for(let x=952;x<1500;x+=8){
  const p=hit(x,y),px=hit(x+1,y),py=hit(x,y+1),nv=camera.position.clone().sub(p).normalize().y;
  samples.push({world:v2(p.x,p.z),dx:v2(px.x-p.x,px.z-p.z),dy:v2(py.x-p.x,py.z-p.z),nv});
 }
 const m=kitMaterial('paving',{materials:{...input.kit.materials,...input.plan.materials}},'high');
 const albedo=m.color.r*.2126+m.color.g*.7152+m.color.b*.0722;assert.equal(m.metalness,0);
 for(const open of [1,.5])for(const diffuseSky of [1,.5]){
  const rows=[];
  for(let step=0;step<=10;step++){
   const wet=step/10;let total=0;
   for(const p of samples){
    const drop=dropsFn(p.world,wet,p.dx,p.dy,1,smoothstep,Math.abs,v2,layer);
    const edgeNoise=(()=>{const h=(x,y)=>fract(Math.sin(x*127.1+y*311.7)*43758.5453);
     const noise=(x,y)=>{const ix=Math.floor(x),iy=Math.floor(y),fx=fract(x),fy=fract(y),u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);return mix(mix(h(ix,iy),h(ix+1,iy),u),mix(h(ix,iy+1),h(ix+1,iy+1),u),v);};
     return noise(p.world.x*.35,p.world.y*.35)*.67+noise(p.world.x*.7+19.1,p.world.y*.7+7.7)*.33;})();
    total+=light(surface(wet,drop,edgeNoise,albedo,m.roughness,open,...functions,mix,Math.abs,()=>edgeNoise),p.nv,diffuseSky);
   }
   rows.push(total/samples.length);
  }
  console.log('OWNER_OVERCAST_LUMINANCE',JSON.stringify({fixture:input.label,open,diffuseSky,albedo,roughness:m.roughness,nv:[Math.min(...samples.map(p=>p.nv)),Math.max(...samples.map(p=>p.nv))],rows}));
  rows.slice(1).forEach((v,i)=>assert.ok(v<=rows[i]+1e-6,`wetness ${i/10}->${(i+1)/10}: ${rows[i]} -> ${v}`));
  assert.ok(rows.at(-1)<rows[0]*.88,'saturated patio clearly darker than dry');
 }
 m.dispose();
});
await test('CPU splash standing-water eligibility matches the installed GLSL puddle/film mask',()=>{
 const hashBody=vecBody('weatherHash','float').replace('dot(p,vec2(127.1,311.7))','(p.x*127.1+p.y*311.7)');
 const shaderHash=new Function('p','fract','sin',hashBody);
 const noiseBody=vecBody('weatherNoise','float')
  .replace('vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);','let i=v2(Math.floor(p.x),Math.floor(p.y)),f=v2(fract(p.x),fract(p.y));f=v2(f.x*f.x*(3-2*f.x),f.y*f.y*(3-2*f.y));')
  .replace('i+vec2(1.0,0.0)','v2(i.x+1,i.y)').replace('i+vec2(1.0)','v2(i.x+1,i.y+1)').replace('i+vec2(0.0,1.0)','v2(i.x,i.y+1)');
 const shaderNoise=new Function('p','weatherHash','v2','fract','mix',noiseBody);
 const noise=p=>shaderNoise(p,p=>shaderHash(p,fract,Math.sin),v2,fract,mix);
 const edgeBody=vecBody('weatherEdge','float').replace('p*.35','v2(p.x*.35,p.y*.35)').replace('p*.7+vec2(19.1,7.7)','v2(p.x*.7+19.1,p.y*.7+7.7)');
 const edgeFn=new Function('p','weatherNoise','v2',edgeBody);
 for(let i=0;i<500;i++)for(const amount of [0,.25,.7,1]){
  const x=i*.037-10,z=i*.093-20,wet=.2+(i%10)*.1,up=i%5?1:.8;
  const edge=edgeFn(v2(x,z),noise,v2);
  const expected=scalar('weatherPuddle')(up,amount,edge)*scalar('weatherFilm')(wet);
  close(standingWaterAt(x,z,up,{wetness:wet,puddles:amount}),expected);
 }
 close(standingWaterAt(1,2,1,{neutral:true,wetness:1,puddles:1}),0);
});
function ripple(water,rate,clock,world,footprint){
 let body=preprocess((water?'#define WEATHER_SURFACE_WATER\n':'')+WEATHER_GLSL);
 body=body.match(/vec2 weatherRipple\(vec2 world\) \{([\s\S]*?)\n\}/)[1]
  .replace('vec3 fromEye=vWeatherWorld-cameraPosition;','let fromEye={x:0,y:0,z:8};')
  .replace('vec2 cell=floor(world/.6),slope=vec2(0.0);','let cell=v2(Math.floor(world.x/.6),Math.floor(world.y/.6)),slope=v2(0);')
  .replace('vec2 midCell=floor(world/.6-.5);','let midCell=v2(Math.floor(world.x/.6-.5),Math.floor(world.y/.6-.5));')
  .replace('vec2 dx=weatherWorldDx.xz,dy=weatherWorldDy.xz;','let dx=v2(footprint,0),dy=v2(0,footprint);')
  .replace('int y=impact/width,x=impact-y*width;','let y=Math.trunc(impact/width),x=impact-y*width;')
  .replace('midCell+vec2(float(x),float(y))','v2(midCell.x+x,midCell.y+y)')
  .replace('cell+vec2(float(x-1),float(y-1))','v2(cell.x+x-1,cell.y+y-1)')
  .replace('vec2 centre=(id+random.yz)*.6;','let centre=v2((id.x+random.y)*.6,(id.y+random.z)*.6);')
  .replace('vec2 delta=world-centre;','let delta=sub(world,centre);')
  .replace('vec2 direction=delta/max(d,.001);','let direction=div(delta,max(d,.001));')
  .replace('slope+=direction*band*fade*visible*strength*1.414214*support*farFade*(mid?1.0:nearFade);','let amp=band*fade*visible*strength*1.414214*support*farFade*(mid?1:nearFade);slope.x+=direction.x*amp;slope.y+=direction.y*amp;')
  .replaceAll('vec2(0.0)','v2(0)').replace(/\b(?:float|vec2|vec3|int|bool) (?=\w+=)/g,'let ');
 const fn=new Function('world','weatherSurface','footprint','v2','sub','div','dot','floor','fract','int','length','abs','max','smoothstep','weatherRingCount','weatherRingHash','weatherRingStrength','weatherRingSupport','weatherRingBand',body);
 return point=>fn(point,{w:Math.round(rate*255)+clock/64},footprint,v2,sub,div,(a,b)=>dot(a,b)+(a.z??0)*(b.z??0),Math.floor,fract,Math.trunc,p=>Math.hypot(p.x,p.y),Math.abs,Math.max,smoothstep,scalar('weatherRingCount'),hash,scalar('weatherRingStrength'),scalar('weatherRingSupport'),scalar('weatherRingBand'));
}
await test('executed puddle and pool rain slopes match at equal rates and screen footprints',()=>{
 for(const rate of [.1,.45,1])for(const footprint of [.001,.01,.03]){
  let puddlePower=0,poolPower=0;
  for(const clock of [.07,.23,.51,.89]){
   const a=ripple(false,rate,clock,null,footprint),b=ripple(true,rate,clock,null,footprint);
   for(let i=0;i<1200;i++){
    const point=v2((i%40)*.037,Math.floor(i/40)*.043),p=a(point),q=b(point);
    puddlePower+=dot(p,p);poolPower+=dot(q,q);
   }
  }
  assert.ok(poolPower>0);const ratio=Math.sqrt(puddlePower/poolPower);
  assert.ok(ratio>=1/1.5&&ratio<=1.5);console.log('PUDDLE_POOL_SLOPE',JSON.stringify({rate,footprint,ratio}));
 }
});
}
await test('one packed vector: ground units, bounded rate/phase, neutral and rain-only ripples',()=>{
 const layer=installWeatherSurface(new THREE.Scene());
 assert.deepEqual(Object.keys(layer.uniforms),['weatherSurface']);
 for(const precip of ['none','snow','hail','rain','mix']){
  layer.update({wetness:1,snow_cm:8,puddles:1,rate:1,precip},32);
  const u=layer.uniforms.weatherSurface.value;
  assert.deepEqual(u.toArray().slice(0,3),[1,1,1]);
  assert.equal(Math.floor(u.w)/255,['rain','mix'].includes(precip)?1:0);
  close(u.w-Math.floor(u.w),.5);
 }
 for(const seconds of [0,3.999,4,63.999,64,1e10,NaN]){
  layer.update({wetness:NaN,snow_cm:Infinity,puddles:-1,rate:Infinity,precip:'rain'},seconds);
  assert.ok(layer.uniforms.weatherSurface.value.toArray().every(Number.isFinite));
 }
 for(const seconds of [3.999999999,4,7.999999999,63.999999999,64,127.999999999]){
  layer.update({precip:'rain',rate:1},seconds);
  const uploaded=new Float32Array(layer.uniforms.weatherSurface.value.toArray());
  assert.equal(Math.floor(uploaded[3]),255,'GPU float rounding never spills phase into rain rate');
 }
 layer.update({wetness:1,snow_cm:8,puddles:1,rate:1,precip:'rain',neutral:true},2);
 assert.deepEqual(layer.uniforms.weatherSurface.value.toArray(),[0,0,0,0]);layer.dispose();
});
await test('executed wet and snow/puddle curves preserve identity and slope rules',()=>{
 const wet=scalar('weatherWetScale'),rough=scalar('weatherRoughness');
 close(wet(1,0,1),.5);assert.ok(wet(.01,0,1)>.9);assert.ok(wet(1,1,1)>.9);
 close(wet(.3,0,0),1);close(rough(.8,1,0,0),.12);close(rough(.8,1,1,0),.03);
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
await test('executed drop, film, lawn and rain-density progression',()=>{
 const spot=scalar('weatherSpot'),film=scalar('weatherFilm'),gloss=scalar('weatherGloss');
 const lawn=scalar('weatherLawnPuddle'),puddle=scalar('weatherPuddle'),strength=scalar('weatherRingStrength'),band=scalar('weatherRingBand');
 let previous=-1;
 for(const wet of [.1,.3,.5,.9]){
  let coverage=0;for(let i=0;i<1000;i++)coverage+=mix(spot(wet,(i+.5)/1000,.5),1,film(wet))/1000;
  assert.ok(coverage>previous);previous=coverage;
  assert.ok(film(wet)>=0&&film(wet)<=1);assert.ok(gloss(wet,.5)>=0&&gloss(wet,.5)<=1);
  console.log('WEATHER_SPOT_COVERAGE',wet,coverage);
 }
 let lastCoverage=-1;
 for(const amount of [0,.1,.3,.6,.8,1]){
  let coverage=0;for(let i=0;i<1000;i++)coverage+=puddle(1,amount,(i+.5)/1000)/1000;
  assert.ok(coverage>lastCoverage,'puddle hollows grow into connected patches');lastCoverage=coverage;
  console.log('WEATHER_PUDDLE_COVERAGE',amount,coverage);
  if(amount<=.8)close(lawn(amount),0);else assert.ok(lawn(amount)>0&&lawn(amount)<.5);
  close(puddle(0,amount,.3),0);
 }
 let lastDensity=-1,lastPower=-1;
 for(const rate of [0,.1,.45,.8,1]){
  let active=0,power=0;
  for(let i=0;i<1000;i++){
   const amp=strength(rate,(i+.5)/1000);active+=amp>0?1/1000:0;
   for(let j=0;j<100;j++){const wave=amp*band(j/100,.6);assert.ok(Number.isFinite(wave));power+=wave*wave/100000;}
  }
  const density=active*3/(.6*.6);
  assert.ok(density>lastDensity&&power>lastPower);lastDensity=density;lastPower=power;
  if(rate===0){close(density,0);close(power,0);}
  console.log('WEATHER_RINGS',JSON.stringify({rate,hitsPerM2Second:density,activePerM2:active/(.6*.6),rms:Math.sqrt(power)}));
 }
});
await test('ring work is bounded by distance and skipped before covered, vertical and lawn calls',()=>{
 const count=scalar('weatherRingCount');
 const support=scalar('weatherRingSupport');
 for(const age of [0,.2,.5,1]){close(support(age*.46,age),1);close(support(age*.46+.18,age),0);assert.ok(support(age*.46+.16,age)>0&&support(age*.46+.16,age)<1);}
 for(const [distance,n]of [[0,9],[8,9],[15,9],[17.99,9],[18,4],[28,4],[35.99,4],[36,0],[100,0]])close(count(distance*distance),n);
 assert.ok(!WEATHER_GLSL.includes('layer<2'),'one nine-neighbour layer keeps the same 8.33 hits/m2/s at 3 Hz');
 const ripple=WEATHER_GLSL.split('vec2 weatherRipple(vec2 world) {')[1];
 assert.ok(ripple.includes('clock*3.0+random.x'),'one layer maintains the original impact arrival rate');
 assert.ok(ripple.indexOf('if(rate<=0.0)')<ripple.indexOf('weatherRingHash(id)'));
 assert.ok(ripple.indexOf('if(count==0.0)')<ripple.indexOf('for(int impact='));
 assert.ok(ripple.indexOf('if(count==4.0&&!mid)continue;')<ripple.indexOf('weatherRingHash(id)'));
 assert.ok(ripple.indexOf('if(visible<=0.0)continue;')<ripple.indexOf('weatherRingBand(d/ringScale,age)'));
 assert.ok(ripple.indexOf('if(support<=0.0)continue;')<ripple.indexOf('weatherRingBand(d/ringScale,age)'));
 assert.ok(!ripple.includes('weatherHash('),'no sine hashes in the ring loop');
 assert.ok(!ripple.includes('dFdx(')&&!ripple.includes('dFdy('),'derivatives must be captured before receiver gates');
 const hash=WEATHER_GLSL.split('vec3 weatherRingHash(vec2 p) {')[1].split('\n}')[0];
 assert.ok(!hash.includes('sin(')&&hash.includes('fract('),'ring arrival/centre hash has no transcendental');
 const scene=new THREE.Scene(),layer=installWeatherSurface(scene),material=new THREE.MeshStandardMaterial();scene.add(new THREE.Mesh(new THREE.BoxGeometry(),material));layer.prepare();
 const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};material.onBeforeCompile(shader,{});
 const f=expand(shader.fragmentShader);
 assert.ok(f.indexOf('weatherWorldDx=dFdx(vWeatherWorld)')<f.indexOf('if(vWeatherOpen>0.0&&'),'world derivatives precede divergent exposure/receiving gates');
 assert.ok(f.includes('if(vWeatherOpen>0.0&&weatherSurface.x+'),'covered faces skip all surface work');
 assert.ok(f.includes('if(weatherRingWeight>0.0)weatherSlope=weatherRipple(vWeatherWorld.xz)*weatherRingWeight;'),'zero upward/exposure/snow/lawn weight skips the loop');
 assert.ok(f.indexOf('weatherSurface.x>0.0&&weatherSurface.x<.9?weatherDrops')>0,'full gloss bypasses unused drop hashes');
 layer.dispose();material.dispose();
});
await test('runtime ripple loop visits exactly the original cells in the original order',()=>{
 const loop=WEATHER_GLSL.match(/int impacts=int\(count\);([\s\S]*?)    vec3 random=/)[0].split('    vec3 random=')[0]
  .replace('int y=impact/width,x=impact-y*width;','let y=Math.trunc(impact/width),x=impact-y*width;')
  .replace('midCell+vec2(float(x),float(y))','add(midCell,vec2(float(x),float(y)))')
  .replace('cell+vec2(float(x-1),float(y-1))','add(cell,vec2(float(x-1),float(y-1)))')
  .replace(/\b(?:int|vec2|bool) (?=\w+=)/g,'let ');
 const visit=new Function('count','cell','midCell','vec2','add','int','float','const cells=[];'+loop+'cells.push([id.x,id.y]);} return cells;');
 const vec2=(x,y)=>({x,y}),add=(a,b)=>vec2(a.x+b.x,a.y+b.y);
 for(const cx of [-100,-2,-1,0,1,2,100])for(const cy of [-2,-1,0,1,2])
 for(const fx of [0,.000001,.499999,.5,.500001,.999999])for(const fy of [0,.499999,.5,.999999])for(const count of [4,9]){
  const world=vec2((cx+fx)*.6,(cy+fy)*.6),cell=vec2(Math.floor(world.x/.6),Math.floor(world.y/.6));
  const mid=vec2(Math.floor(world.x/.6-.5),Math.floor(world.y/.6-.5)),expected=[];
  for(let y=-1;y<=1;y++)for(let x=-1;x<=1;x++){
   const id=add(cell,vec2(x,y)),middle=id.x>=mid.x&&id.x<=mid.x+1&&id.y>=mid.y&&id.y<=mid.y+1;
   if(count===4&&!middle)continue;expected.push([id.x,id.y]);
  }
  assert.deepEqual(visit(count,cell,mid,vec2,add,Math.trunc,Number),expected);
 }
});
// Spatial scalar port of the GLSL hash/noise, sampled over an 8 m patch.
// The colour/gloss/coverage curves below execute their actual GLSL bodies.
const fract=v=>v-Math.floor(v),hash=(x,y)=>fract(Math.sin(x*127.1+y*311.7)*43758.5453);
const noise=(x,y)=>{const ix=Math.floor(x),iy=Math.floor(y),fx=fract(x),fy=fract(y),a=fx*fx*(3-2*fx),b=fy*fy*(3-2*fy);
 return mix(mix(hash(ix,iy),hash(ix+1,iy),a),mix(hash(ix,iy+1),hash(ix+1,iy+1),a),b);};
await test('spatial progression: measured paving, coping stone, lawn and vertical wall',()=>{
 const wetScale=scalar('weatherWetScale'),spot=scalar('weatherSpot'),film=scalar('weatherFilm'),gloss=scalar('weatherGloss');
 const puddle=scalar('weatherPuddle'),lawnPuddle=scalar('weatherLawnPuddle'),rough=scalar('weatherRoughness');
 const materials={...input.kit.materials,...input.plan.materials};
 for(const [role,receivingRole] of [['paving','paving'],['coping stone','paving'],['lawn','lawn'],['wall','siding']]){
  const m=kitMaterial(receivingRole,{materials},'high'),rgb=m.color.toArray();
  const lum=rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722,dry=lum/Math.PI,isLawn=role==='lawn',vertical=role==='wall';
  let lastLum=dry,lastRough=m.roughness;
  for(const wet of [.1,.3,.6,1]){
   let meanLum=0,meanRough=0,meanPuddle=0;
   for(let i=0;i<96;i++)for(let j=0;j<96;j++){
    const x=i*.0831+.0137,y=j*.0837+.0071,ix=Math.floor(x/.03),iy=Math.floor(y/.03);
    const radius=mix(.28,.48,hash(ix+17.3,iy+17.3)),disc=Math.hypot(fract(x/.03)-.5,fract(y/.03)-.5)<radius?1:0;
    const drop=spot(wet,hash(ix,iy),disc),f=film(wet);
    const coverage=gloss(wet,drop),g=coverage*(vertical?mix(.45,1,noise(x*12,y*.7)):1);
    const edge=noise(x*.35,y*.35)*.67+noise(x*.7+19.1,y*.7+7.7)*.33;
    const p=puddle(vertical?0:1,wet,edge)*f*(isLawn?lawnPuddle(wet):1);
    meanLum+=dry*(wetScale(isLawn?Math.max(lum,.35):lum,m.metalness,coverage))/9216;
    meanRough+=(isLawn?rough(mix(m.roughness,.42,g),0,p,0):rough(m.roughness,g,p,0))/9216;
    meanPuddle+=p/9216;
   }
   assert.ok(meanLum<lastLum&&meanRough<lastRough,role+' darkens and gains gloss');lastLum=meanLum;lastRough=meanRough;
   if(vertical||(isLawn&&wet<=.8))close(meanPuddle,0);
   console.log('WEATHER_PROGRESSION',JSON.stringify({fixture:input.label,role,wetness:wet,rgb,dry,roughnessDry:m.roughness,luminance:meanLum,roughness:meanRough,puddle:meanPuddle}));
  }
  m.dispose();
 }
 close(wetScale(1,0,.25/.5),.75,'a fresh resolved impact darkens 25 percent');
 // Wet ground keeps its sky reflection only where the reflected ray rises (owner 2026-11-19).
 const horizon=scalar('weatherHorizon');close(horizon(0,1),.22);close(horizon(.6,1),1);close(horizon(0,0),1);
 assert.ok(horizon(.2,1)>horizon(.05,1)&&horizon(.2,1)<1,'damping eases in as the reflection rises');
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
  if(material){const rgb=material.color.toArray(),dry=luminance(rgb)/Math.PI,scale=scalar('weatherWetScale')(role==='lawn'?Math.max(luminance(rgb),.35):luminance(rgb),material.metalness,1);
   console.log('WEATHER_WET_LUMINANCE',JSON.stringify({fixture:input.label,role,rgb,dry,wet:dry*scale,darkerPercent:(1-scale)*100,roughnessDry:material.roughness,roughnessWet:role==='lawn' ? .42 : scalar('weatherRoughness')(material.roughness,1,0,0)}));}
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
   if(row.label!=='sheet')assert.ok(f.includes('clock=waterTime'),row.label+' uses existing continuous water clock');
  }else if(row.label==='underwater'||row.label==='vapour'){
   assert.ok(!f.includes('normal +=')||!f.includes('weatherRipple(vWeatherWorld.xz)'),'submerged/vapour no rain surface');
  }else if(!m.isShaderMaterial){
   assert.ok(f.includes('diffuseColor.rgb *= weatherWetScale'),row.label+' wet');
   assert.ok(f.includes('weatherSnow(weatherUp'),row.label+' snow');
   if(m.name==='roof'||m.userData.materialRole==='roof'){
    // A 4:12 roof has normal.y=.949 and passes .9; slope alone cannot exclude it.
    assert.ok(!f.includes('weatherPuddle(weatherUp'),row.label+' roof never collects puddles');
    assert.ok(f.includes('weatherRoofRivulets(')&&f.includes('weatherRoofFilm('),row.label+' roof rivulets and moving water film');
   }
   if(row.label==='grass'){
    assert.ok(f.indexOf('roughnessFactor = mix(.96, .53, vGrass.x)')<f.indexOf('roughnessFactor=weatherRoughness'),'weather follows grass roughness override');
    assert.ok(f.includes('weatherP*=weatherLawnPuddle(weatherSurface.z)')&&f.includes('weatherRingWeight*=weatherP')&&f.includes('if(weatherRingWeight>0.0)weatherSlope=weatherRipple'),'blades exclude standing water/rings until the lawn threshold, before evaluating rings');
    assert.ok(f.includes('mix(roughnessFactor,.42,weatherGlossValue)'),'blades gain modest gloss');
   }
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
 for(const [wet,seconds] of [[0,0],[.1,9],[.3,27],[.6,54],[1,90]]){
  layer.update({wetness:wet,puddles:wet,precip:'rain',rate:1},seconds);layer.prepare();
  for(const row of rows){assert.equal(programSource(renderer,cache,scene,row.object,lights).key,row.key,'progression keeps program keys');assert.equal(row.object.material.version,row.version);}
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
 const prior=location.search,realNow=Date.now;let clock=realNow();Date.now=()=>clock;location.search='?test=1';let viewer,editor;
 const mount=async(neutral=false)=>{const el=new Element();if(neutral){const shell=new Element();shell.className='editor-shell';shell.append(el);}return mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});};
 try{
  viewer=await mount();assert.ok(viewer.weatherSurface,'installed at mount');
  viewer.setWeatherPreview('rain');let u=viewer.weatherSurface.uniforms.weatherSurface.value;
  assert.equal(u.x,0);assert.equal(u.z,0);assert.ok(Math.floor(u.w)>0);
  for(const [seconds,wet] of [[45,.5],[45,1],[29,1]]){
   clock+=seconds*1000;viewer.setCameraState(viewer.cameraState());assert.equal(u.x,wet);assert.equal(u.z,wet);
  }
  const old=viewer.weather;viewer.setWeatherPreview('snow');assert.notEqual(viewer.weather,old);assert.equal(u.y,1);assert.equal(u.z,0);assert.equal(Math.floor(u.w),0);
  viewer.setWeatherPreview('clear');assert.deepEqual(u.toArray().slice(0,3),[0,0,0]);
  editor=await mount(true);assert.deepEqual(editor.weatherSurface.uniforms.weatherSurface.value.toArray(),[0,0,0,0]);
  editor.setWeatherPreview('rain');assert.equal(editor.weatherSurface.uniforms.weatherSurface.value.x,0);
  editor.setWeatherPreview(null);assert.deepEqual(editor.weatherSurface.uniforms.weatherSurface.value.toArray(),[0,0,0,0]);
 }finally{viewer?.dispose();editor?.dispose();location.search=prior;Date.now=realNow;}
});
await test('overcast sun specular drops >=20x under Pouring while diffuse stays on the cloud model and lamps stay full',async()=>{
 const {sunAirVisibility,sunDiscVisibility,previewWeather,weatherState}=await import(file('static/twin/sky/weather.js'));
 const {CLOUD_SHADOW_GLSL}=await import(file('static/twin/sky/cloud_shadow.js'));
 const specBody=CLOUD_SHADOW_GLSL.match(/float cloudSpecForLight\([^)]*\) \{([\s\S]*?)\n\}/)[1]
  .replace('vec3 luminary=mat3(viewMatrix)*cloudShadowLight;','const luminary=cloudShadowLight;');
 const specFn=new Function('direction','airVisibility','cloudShadowLight','cloudShadowValue','dot','smoothstep','clamp',specBody);
 const dot3=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
 const sunDir=[0,Math.SQRT1_2,Math.SQRT1_2],lampDir=[1,0,0];
 const evalDirect=(weather,cloudT,dir=sunDir)=>{
  const air=sunAirVisibility(weather);
  const diffuse=dot3(dir,sunDir)>.99999?cloudT:1;
  const specScale=specFn(dir,air,sunDir,cloudT,dot3,smoothstep,clamp);
  return {diffuse,specular:diffuse*specScale,disc:sunDiscVisibility(weather,cloudT)};
 };
 const clear=evalDirect(previewWeather('clear'),1);
 const partlyGap=evalDirect(weatherState({state:'partlycloudy',attributes:{}}),1);
 const partlyEdge=evalDirect(weatherState({state:'partlycloudy',attributes:{}}),.6);
 const cloudy=evalDirect(weatherState({state:'cloudy',attributes:{}}),.045);
 const pouring=evalDirect(previewWeather('pouring'),.045);
 const lampUnderPouring=evalDirect(previewWeather('pouring'),.045,lampDir);
 assert.equal(clear.diffuse,1);assert.equal(clear.specular,1);
 assert.equal(partlyGap.specular,1,'clear gap in partly cloudy keeps full sun highlight');
 assert.ok(partlyEdge.specular>.2&&partlyEdge.specular<clear.specular,'partly cloudy keeps partial highlight');
 assert.ok(cloudy.specular<clear.specular/20,'heavy cloudy suppresses sharp sun highlight');
 assert.ok(pouring.specular<=clear.specular/20,'Pouring sun specular is at least 20x smaller than clear sky');
 assert.equal(pouring.diffuse,.045,'Pouring diffuse stays strictly on the existing cloud shadow model');
 assert.equal(pouring.specular,pouring.disc,'lit specular multiplier matches shared sunDiscVisibility exactly');
 assert.equal(partlyEdge.specular,partlyEdge.disc,'partly cloudy lit specular matches shared sunDiscVisibility');
 assert.equal(lampUnderPouring.specular,1,'non-sun lights keep full specular during Pouring');
 // Verify mounted view writes sun obscuration into the packed stageRing[4].w lane with no extra uniform.
 const el=new Element(),v=await mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});
 try{
  const ringOf=()=>{v.scene.onBeforeRender(v.renderer3,v.scene,v.camera);let found=null;v.scene.traverse(o=>{for(const m of [].concat(o.material||[])){if(m.fog&&m.isMeshStandardMaterial&&!found){const s={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};m.onBeforeCompile(s,{});found=s.uniforms.stageRing?.value;}}});return found;};
  v.setWeatherPreview('clear');v.render();const ring=ringOf();assert.ok(ring);
  close(1-ring[19],1);
  v.setWeatherPreview('pouring');v.render();close(1-ring[19],0);
  v.setWeatherPreview('fog');v.render();close(1-ring[19],0);
 }finally{v.dispose();}
});
dummyShadow.dispose();finish();
"""

TREE_DRIVER = TREE_PREFIX + r"""
const THREE=await import('three');
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {installWeatherSurface,WEATHER_GLSL,standingWaterAt}=await import(file('static/twin/sky/weather_surface.js'));
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
 haze.set({centre:[0,0],radius:100,extinction:3.912/300});haze.prepare();wind.prepare();layer.prepare();layer.update({snow_cm:8,fog:1},0);
 const mix=(a,b,t)=>a+(b-a)*t,smoothstep=(a,b,v)=>{const t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
 const scalar=name=>{const m=WEATHER_GLSL.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));return new Function('mix','smoothstep',`return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(mix,smoothstep);};
 const snow=scalar('weatherSnow'),wet=scalar('weatherWetScale'),rough=scalar('weatherRoughness');
 let samples=0;
 scene.traverse(o=>{if(o.material?.userData.plantWind!=='leaves')return;
  const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};o.material.onBeforeCompile(shader,{});
  assert.equal(shader.uniforms.weatherSurface.value.y,1);assert.equal(shader.uniforms.stageRadius.value,100);assert.equal(shader.uniforms.stageRing.value[3],Math.fround(3.912/300));
  const expand=s=>s.replace(/#include\s+<([\w\d_]+)>/g,(_,n)=>expand(THREE.ShaderChunk[n]));
  const fragment=expand(shader.fragmentShader);
  assert.ok(fragment.includes('weatherSnow(weatherUp')&&fragment.includes('normal *= faceDirection'));
  assert.ok(fragment.includes('mix( gl_FragColor.rgb, stageColour, max( stageFade, stageFog ) )'));
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
