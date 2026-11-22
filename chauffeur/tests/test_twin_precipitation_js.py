"""Precipitation lifecycle and real household mount, executed in Node without GL."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node
from test_twin_cloud_shadow_js import DRIVER as CLOUD_DRIVER
from test_twin_reflection_probes_js import DRIVER as REFLECTION_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {existsSync}=await import('node:fs');
assert.ok(existsSync(new URL(file('static/twin/sky/precipitation.js'))),'precipitation module exists');
const {createPrecipitation,precipitationCounts,precipitationVelocity,createSplashSampler,wrappedPosition}=await import(file('static/twin/sky/precipitation.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const weather=(precip='rain',rate=1)=>({precip,rate,windMps:0,windToDeg:90});
const splashCamera=()=>{const c=new THREE.PerspectiveCamera(38,16/9,.1,1000);c.position.set(0,1.6,0);c.lookAt(0,.1,-3);c.updateMatrixWorld();return c;};
await test('Pouring concentrates 20-40 live splashes per square metre on visible near ground, with declining density and rain rate',()=>{
 const metrics=[];
 for(const [tier,sigma] of [['low',.30],['high',.55],['max',.65]])for(const rate of tier==='high'?[1,.45,.1]:[1]){
  let seed=0x98765432;
  const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
  const camera=splashCamera(),p=createPrecipitation(new THREE.Scene(),{tier,random});
  p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}});
  p.objects.rain.onBeforeRender({getDrawingBufferSize:v=>v.set(1920,1080)});
  const direction=new THREE.Vector3(0,-.6,.5).unproject(camera).sub(camera.position).normalize();
  const centre=camera.position.clone().addScaledVector(direction,(.3*.3048+.006-camera.position.y)/direction.y);
  const counts=[0,0,0],position=new THREE.Vector3();let observations=0;
  for(let frame=0;frame<=900;frame++){
   const now=frame/60;p.update(now,weather('rain',rate),camera);
   if(frame<120)continue;
   observations++;
   for(const ring of p.splashes){
    const a=ring.data;
    for(let i=0;i<ring.count;i++){
     const age=now-a.splashBorn.getX(i);if(age<0||age>a.splashShape.getZ(i))continue;
     position.fromBufferAttribute(a.splashPosition,i);
     const r=Math.hypot(position.x-centre.x,position.z-centre.z);
     if(r<sigma)counts[0]++;else if(r<2*sigma)counts[1]++;else if(r<3*sigma)counts[2]++;
     const depth=-position.clone().applyMatrix4(camera.matrixWorldInverse).z;
     assert.ok(.04*.7*camera.projectionMatrix.elements[5]*540/depth>=2,'no unresolved splash birth');
     position.project(camera);assert.ok(Math.abs(position.x)<1&&Math.abs(position.y)<1,'every birth is in the frustum');
    }
   }
  }
  const density=counts.map((n,i)=>n/observations/(Math.PI*sigma*sigma*(2*i+1)));
  if(rate===1){assert.ok(density[0]>=20&&density[0]<=40,`${tier}: ${density}`);assert.ok(density[0]>density[1]*1.5&&density[1]>density[2]*1.5);}
  metrics.push({tier,rate,density});p.dispose();
 }
 const high=metrics.filter(v=>v.tier==='high');
 assert.ok(high[1].density[0]/high[0].density[0]>.25&&high[1].density[0]/high[0].density[0]<.45,'Rain about a third');
 assert.ok(high[2].density[0]<high[0].density[0]*.1,'Drizzle few');
 console.log('NEAR_SPLASH_DENSITY',JSON.stringify(metrics));
});
await test('debug hook fills chosen or random variants, freezes actual shader age, clears and resumes, and respects indoor hiding',()=>{
 let debugNow=20;const p=createPrecipitation(new THREE.Scene(),{random:()=>.5,debugClock:()=>debugNow}),camera=splashCamera();
 p.setPlan({site:{pool:{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}}});
 p.update(20,weather(),camera);
 for(const [index,variant] of ['crown','jet','scatter'].entries()){
  assert.equal(p.debugSplashes({at:[0,0,-1],radius:.5,count:40,variant,freezeAge:.08}),40);
  p.update(40,weather(),camera);assert.equal(p.uniforms.splashTime.value,20+.08+(index?20:0));
  debugNow=40;
  const ring=p.splashes[index],a=ring.data;
  assert.equal(ring.count,40);assert.ok(ring.lods.some(o=>o.visible));
  assert.ok(p.splashes.every((r,i)=>i===index||r.lods.every(o=>!o.visible)));
  for(let i=0;i<40;i++){
   assert.ok(Math.hypot(a.splashPosition.getX(i),a.splashPosition.getZ(i)+1)<=.501);
   assert.ok(Math.abs(p.uniforms.splashTime.value-a.splashBorn.getX(i)-.08)<1e-5);
  }
 }
 assert.equal(p.debugSplashes({at:[0,0,-1],radius:0,count:100,variant:null,freezeAge:.08}),100,'random hook uses free slots without losing requested instances');
 p.update(41,weather(),camera,{unlit:true});assert.ok(p.splashes.every(r=>r.lods.every(o=>!o.visible)));
 p.update(42,weather(),camera);assert.ok(p.splashes.some(r=>r.lods.some(o=>o.visible)));
 debugNow=42;p.debugSplashes(null);assert.equal(p.uniforms.splashTime.value,42);assert.ok(p.splashes.every(r=>r.lods.every(o=>!o.visible)&&r.count===0));
 p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}});
 p.update(43,weather(),camera);assert.ok(p.splashes.some(r=>r.lods.some(o=>o.visible)),'normal births resume');
 debugNow=43;p.debugSplashes({at:[0,0,-1],count:2,variant:'scatter'});p.update(43.31,weather(),camera);
 assert.ok(p.splashes.every(r=>r.lods.every(o=>!o.visible)),'without freezeAge, debug births age and expire without automatic replacements');
 const roofPlan={buildings:[{id:'b',levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[40,0],[40,40],[0,40]]}],rooms:[],walls:[],
  roof:{sections:[{id:'r',kind:'flat',rect:[0,0,40,40],plate:10}]}}]};
 p.setPlan(roofPlan);
 assert.equal(p.debugSplashes({at:[2,0,-2],count:10,variant:'crown',freezeAge:.08}),0,'debug injection cannot place water under a roof');
 camera.position.set(2,1.6,-2);camera.updateMatrixWorld();p.update(44,weather(),camera);
 assert.ok(p.splashes.every(r=>r.lods.every(o=>!o.visible)),'camera indoors hides debug water too');
 p.dispose();
});
await test('falling volume surrounds the camera even with a distant orbit target and supplies drops in macro views',()=>{
 let seed=17;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
 const p=createPrecipitation(new THREE.Scene(),{tier:'low',random}),point=new THREE.Vector3(),seedValue=new THREE.Vector3();
 for(const height of [.35,1,1.6]){
  const camera=splashCamera();camera.position.set(30,height,-40);const target=new THREE.Vector3(30,0,-40.2);camera.lookAt(target);camera.updateMatrixWorld();
  p.update(0,weather(),camera,{target});
  assert.equal(p.uniforms.precipAnchor.value.x,camera.position.x);assert.equal(p.uniforms.precipAnchor.value.z,camera.position.z);
  const seeds=p.objects.rain.geometry.attributes.precipSeed,box=p.uniforms.precipBox.value.toArray(),anchor=p.uniforms.precipAnchor.value.toArray();
  let nearby=0,visible=0;
  for(let i=0;i<seeds.count;i++){
   seedValue.fromBufferAttribute(seeds,i);point.fromArray(wrappedPosition(seedValue.toArray(),[0,0,0],anchor,box));
   const distance=point.distanceTo(camera.position);
   if(distance>.12&&distance<1)nearby++;
   const view=point.clone().applyMatrix4(camera.matrixWorldInverse);point.project(camera);
   if(distance>.12&&distance<1&&-view.z>=.08&&Math.abs(point.x)<1&&Math.abs(point.y)<1&&point.z>=-1&&point.z<=1)visible++;
  }
  assert.ok(nearby>80&&visible>4,`${height}m: ${nearby} nearby / ${visible} in frustum`);
  console.log('CLOSE_RAIN_VOLUME',JSON.stringify({height,nearby,visible,box}));
 }
 const camera=splashCamera();camera.position.set(100,1.6,100);p.update(1,weather(),camera,{target:new THREE.Vector3(-100,0,-100)});
 assert.equal(p.uniforms.precipAnchor.value.x,100);assert.equal(p.uniforms.precipAnchor.value.z,100);p.dispose();
});
await test('three actual 3D water meshes: deterministic random variants, yaw, size and life within the original slot/rate caps',()=>{
 const build=()=>{
  let seed=0x12345678;
  const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
  const p=createPrecipitation(new THREE.Scene(),{tier:'high',random}),camera=splashCamera();
  p.setPlan({site:{pool:{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}}});
  p.update(0,weather(),camera);for(let t=1;t<=180;t++)p.update(t/60,weather(),camera);
  return p;
 };
 const p=build(),again=build();
 assert.deepEqual(p.splashes.map(r=>r.object.geometry.userData.variant),['crown','jet','scatter']);
 let total=0;
 for(let k=0;k<3;k++){
  const ring=p.splashes[k],g=ring.object.geometry,a=ring.data;
  assert.ok(g.isInstancedBufferGeometry&&g.index.count>=24);assert.equal(g.groups.length,0,'one indexed draw per variant');
  assert.ok(!(ring.object.material instanceof Array));assert.equal(ring.object.material.forceSinglePass,true);
  assert.ok(ring.lods.some(o=>o.visible));assert.ok(ring.count>40,'random stream uses every variant');
  total+=ring.lods.reduce((n,o)=>n+o.geometry.instanceCount,0);
  assert.deepEqual(a.splashBorn.array,again.splashes[k].data.splashBorn.array);
  assert.deepEqual(a.splashShape.array,again.splashes[k].data.splashShape.array);
  const y=[],size=[],life=[],yaw=[];
  for(let i=0;i<g.attributes.position.count;i++){assert.ok(Number.isFinite(g.attributes.normal.getY(i)));y.push(g.attributes.position.getY(i));}
  assert.ok(Math.max(...y)-Math.min(...y)>.5,'volume, not a camera-facing quad');
  for(let i=0;i<ring.count;i++){
   yaw.push(a.splashShape.getX(i));size.push(a.splashShape.getY(i));life.push(a.splashShape.getZ(i));
  }
  assert.ok(Math.min(...yaw)<.5&&Math.max(...yaw)>5.5);
  assert.ok(Math.min(...size)>=.699&&Math.max(...size)<=1.301&&Math.max(...size)-Math.min(...size)>.5);
  assert.ok(Math.min(...life)>=.119&&Math.max(...life)<=.301&&Math.max(...life)-Math.min(...life)>.14);
  if(k===0)assert.ok(g.userData.droplets===16);
  if(k===2)assert.ok(g.userData.droplets>=4&&g.userData.droplets<=8);
 }
 assert.ok(total<=192);
 p.update(3.31,weather('rain',.00001),splashCamera());
 assert.ok(p.splashes.every(r=>r.lods.every(o=>!o.visible)),'each individual lifetime expires');
 p.dispose();again.dispose();
});
await test('instance rim count, jitter and heights vary; dielectric faces stay clear and grazing edges/glints brighten',()=>{
 let rng=12345;const random=()=>{rng=(Math.imul(rng,1664525)+1013904223)>>>0;return rng/4294967296;};
 const p=createPrecipitation(new THREE.Scene(),{random}),m=p.objects.splash.material;
 const fn=(name,args,helpers={})=>{
  const source=(name.startsWith('splashRim')?m.vertexShader:m.fragmentShader);
  const body=source.match(new RegExp('float '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'))[1];
  return new Function(...args,...Object.keys(helpers),body.replace(/\bfloat\b/g,'let'));
 };
 const fract=x=>x-Math.floor(x),clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 const count=fn('splashRimCount',['seed','floor','fract']);
 const jitter=fn('splashRimJitter',['point','seed','fract','sin']);
 const height=fn('splashRimHeight',['point','seed','splashRimJitter']);
 const counts=new Set(),heights=[];
 p.debugSplashes({at:[0,0,-1],count:64,variant:'crown'});
 const shape=p.splashes[0].data.splashShape;
 for(let i=0;i<64;i++){
  const seed=shape.getX(i)/6.283185,n=count(seed,Math.floor,fract);counts.add(n);assert.ok(n>=10&&n<=16);
  const hs=Array.from({length:n},(_,j)=>height(j,seed,(p,s)=>jitter(p,s,fract,Math.sin)));
  assert.ok(Math.max(...hs)-Math.min(...hs)>.15);heights.push(hs[0]);
 }
 assert.equal(counts.size,7);assert.ok(Math.max(...heights)-Math.min(...heights)>.4);
 const f=fn('splashFresnel',['cosine','clamp','pow']);
 const fresnel=c=>f(c,clamp,Math.pow);
 const coverage=fn('splashCoverage',['cosine','thickness','bead','splashFresnel','exp','max','pow','clamp']);
 const alpha=(c,t,b)=>coverage(c,t,b,fresnel,Math.exp,Math.max,Math.pow,clamp);
 for(const thickness of [.00007,.00065]){
  const face=alpha(1,thickness,0),rim=alpha(.05,thickness,0);
  assert.ok(face<.04&&rim>.75&&rim>face*15);
  // Repeated clear faces have no additive diffuse white contribution.
  assert.ok(1-Math.pow(1-face,4)<.15);
 }
 assert.ok(alpha(.3,.004,1)>alpha(.3,.00007,0),'bead edges darker/more refractive than sheet');
 const vec=(x,y,z)=>new THREE.Vector3(x,y,z);
 const specBody=m.fragmentShader.match(/float splashSpecular\([^)]*\) \{([\s\S]*?)\n\}/)[1]
  .replace('vec3 halfVector=v+l;','let halfVector=v.clone().add(l);')
  .replace('vec3 h=halfVector/max(length(halfVector),.0001);','let h=halfVector.divideScalar(max(length(halfVector),.0001));');
 const spec=new Function('n','v','l','splashFresnel','max','length','dot','pow',specBody);
 const highlight=angle=>spec(vec(Math.sin(angle),Math.cos(angle),0),vec(0,1,0),vec(0,1,0),fresnel,Math.max,v=>v.length(),(a,b)=>a.dot(b),Math.pow);
 assert.ok(highlight(0)>2&&highlight(.15)<highlight(0)*.001,'sharp sun core');
 const glint=fn('splashGlintCoverage',['specular','sunPeak','environmentPeak','fresnel','exp','max']);
 const core=glint(highlight(0),1,.5,.02,Math.exp,Math.max);
 assert.ok(core>.95,'sun core can brighten even a head-on clear face');
 assert.equal(glint(0,1,.5,.02,Math.exp,Math.max),0,'no diffuse coverage outside glints');
 assert.equal(glint(highlight(0),0,0,.02,Math.exp,Math.max),0,'no sun glint at night');
 assert.equal(m.depthWrite,false);assert.equal(m.blending,THREE.NormalBlending);
 console.log('CLEAR_WATER_OPTICS',JSON.stringify({face:alpha(1,.00065,0),grazing:alpha(.05,.00065,0),sunCore:highlight(0)}));p.dispose();
});
await test('Pouring sun peaks follow shared sun-disc visibility at every distance; clear small flicks remain unchanged',async()=>{
 const {previewWeather,sunDiscVisibility}=await import(file('static/twin/sky/weather.js'));
 const {WEATHER_GLSL}=await import(file('static/twin/sky/weather_surface.js'));
 const p=createPrecipitation(new THREE.Scene()),fs=p.objects.splash.material.fragmentShader;
 const smoothstep=(a,b,v)=>{let t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
 const mix=(a,b,t)=>a+(b-a)*t;
 const scalar=(source,name,args)=>new Function(...args,source.match(new RegExp('float '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'))[1].replace(/\bfloat\b/g,'let'));
 const limit=scalar(fs,'splashCloseSun',['specular','visibility','coverage','sunPeak','pixels','smoothstep','min','max','mix']);
 const energy=scalar(fs,'splashCloseEnergy',['energy','pixels','mix','min','smoothstep']);
 const evaluate=(raw,visibility,cover,peak,pixels)=>limit(raw,visibility,cover,peak,pixels,smoothstep,Math.min,Math.max,mix);
 // The actual vendored standard-material GGX functions, not a hand-authored
 // reference lobe. Wet hardscape uses F0 .04 and weatherRoughness(.12/.03).
 const chunks=Object.values(THREE.ShaderChunk).join('\n');
 const D=scalar(chunks,'D_GGX',['alpha','dotNH','pow2','RECIPROCAL_PI']);
 const V=scalar(chunks,'V_GGX_SmithCorrelated',['alpha','dotNL','dotNV','pow2','sqrt','max','EPSILON']);
 const F=scalar(chunks,'F_Schlick',['f0','f90','dotVH','exp2']);
 const roughness=scalar(WEATHER_GLSL,'weatherRoughness',['original','wet','puddle','snow','mix']);
 const sq=x=>x*x;
 const wetPeak=puddle=>{
  const rough=Math.max(.0525,roughness(.85,1,puddle,0,mix));
  return F(.04,1,1,x=>2**x)*V(sq(rough),1,1,sq,Math.sqrt,Math.max,1e-6)*D(sq(rough),1,sq,1/Math.PI);
 };
 const clear=sunDiscVisibility(previewWeather('clear'),1),partly=sunDiscVisibility({clouds:{coverage:.4}},.6),pouring=sunDiscVisibility(previewWeather('pouring'),.045);
 assert.equal(clear,1);assert.ok(partly>.2&&partly<.7,'partly cloudy keeps partial sun visibility');assert.ok(pouring<clear/20,'pouring sun disc hidden');
 for(const coverage of [.02,.035,.8])for(const sun of [.01,1,3,7])for(const raw of [.01,2.451,100,10000])for(const pixels of [28,32,64]){
  const output=evaluate(raw,pouring,coverage,sun,pixels)*sun/coverage;
  const sunny=evaluate(raw,clear,coverage,sun,pixels)*sun/coverage;
  for(const puddle of [0,1])assert.ok(output<=wetPeak(puddle)*sun*pouring+1e-12,'same-light splash peak <= real wet-deck GGX peak');
  assert.ok(output<=1&&output<=sunny/20,'no close HDR; Pouring at least 20x lower than clear sky');
  assert.equal(evaluate(raw,0,coverage,sun,64),0);
  for(const small of [3,8,16,24]){
   assert.equal(evaluate(raw,clear,coverage,sun,small),raw,'clear small splash sun response unchanged');
   assert.ok(Math.abs(evaluate(raw,partly,coverage,sun,small)-raw*partly)<1e-12,'small splashes scale directly with shared sun visibility');
   assert.ok(evaluate(raw,pouring,coverage,sun,small)<=raw/20,'Pouring removes bright sun from distant/mid splashes too');
  }
 }
 assert.ok(fs.includes('dot(splashSunColour,vec3(.2126,.7152,.0722))*splashSunVisibility'),'sunShare follows sun visibility so overcast flecks stay soft');
 for(const pixels of [3,16,24])assert.equal(energy(20,pixels,mix,Math.min,smoothstep),20);
 assert.equal(energy(20,64,mix,Math.min,smoothstep),1,'resolved total RGB energy also has no HDR blow-out');
 p.update(0,weather(),splashCamera(),{sunVisibility:pouring});
 assert.ok(p.splashes.every(r=>r.lods.every(o=>o.material.uniforms.splashSunVisibility.value===pouring)));
 console.log('CLOSE_SUN_LIMIT',JSON.stringify({clearVisibility:clear,partlyVisibility:partly,pouringVisibility:pouring,wetDeckGGXPeak:wetPeak(0),clearPeak:evaluate(100,clear,.035,3,64)*3/.035,pouringPeak:evaluate(100,pouring,.035,3,64)*3/.035}));p.dispose();
});
await test('natural and debug jets require real standing water, including pool and exact puddle mask',async()=>{
 const {standingWaterAt}=await import(file('static/twin/sky/weather_surface.js'));
 const p=createPrecipitation(new THREE.Scene(),{random:()=>.5}),camera=splashCamera();
 const polygon=[[-200,-200],[200,-200],[200,200],[-200,200]];
 p.setPlan({site:{hardscape:[{polygon}]}});
 for(const wet of [0,.3,1]){
  const w={...weather(),wetness:wet,puddles:0};p.update(0,w,camera);for(let i=1;i<30;i++)p.update(i/60,w,camera);
  assert.equal(p.splashes[1].count,0);assert.equal(p.debugSplashes({at:[0,.3*.3048,-1],variant:'jet',count:10}),0);p.debugSplashes(null);
 }
 const wet={...weather(),wetness:1,puddles:1};p.update(2,wet,camera);
 let water=0,dry=0;
 for(let x=-5;x<5;x+=.25)for(let z=-5;z<0;z+=.25){
  const expected=standingWaterAt(x,z,1,wet)>.5;
  const n=p.debugSplashes({at:[x,.3*.3048,z],variant:'jet',count:1});
  assert.equal(n,expected?1:0);if(expected)water++;else dry++;
 }
 assert.ok(water>0&&dry>0);p.debugSplashes(null);p.setPlan({site:{pool:{polygon}}});
 p.update(3,weather(),camera);for(let i=1;i<30;i++)p.update(3+i/60,weather(),camera);
 assert.ok(p.splashes[1].count>0);assert.equal(p.debugSplashes({at:[0,0,-1],variant:'jet',count:10}),10);p.dispose();
});
await test('small projected impacts brighten with scene light, retain clear close faces and never emit at night',()=>{
 const p=createPrecipitation(new THREE.Scene()),fs=p.objects.splash.material.fragmentShader;
 const smoothstep=(a,b,v)=>{let t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),mix=(a,b,t)=>a+(b-a)*t;
 const scalar=(name,args)=>new Function(...args,fs.match(new RegExp('float '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'))[1]);
 const weight=scalar('splashDistanceWeight',['pixels','smoothstep']);
 const w=pixels=>weight(pixels,smoothstep);
 const coverage=scalar('splashDistanceCoverage',['pixels','feature','light','splashDistanceWeight','clamp']);
 const brightness=scalar('splashDistanceBrightness',['pixels','sunShare','highlight','splashDistanceWeight','mix']);
 const energy=(pixels,light,sun=0,highlight=0)=>coverage(pixels,1,light,w,clamp)*brightness(pixels,sun,highlight,w,mix)*light;
 for(const pixels of [3,8,16]){
  assert.ok(energy(pixels,.5)>energy(64,.5));assert.ok(energy(pixels,.5)>energy(pixels,.005)*100);
  assert.equal(energy(pixels,0),0);assert.ok(energy(pixels,.5,1,1)>energy(pixels,.5,1,0),'sun narrows the bright core');
  assert.equal(coverage(pixels,0,.5,w,clamp),0,'base does not become an opaque distant cup');
 }
 assert.equal(w(32),0);assert.equal(w(64),0,'clear macro shading unchanged');
 console.log('DISTANT_SPLASH_ENERGY',JSON.stringify([3,8,16,32,64].map(pixels=>({pixels,overcast:energy(pixels,.5),night:energy(pixels,.005)}))));p.dispose();
});
await test('thin transmitted water is neutral under a grey environment, with only slight thick-water absorption',()=>{
 const p=createPrecipitation(new THREE.Scene()),fs=p.objects.splash.material.fragmentShader;
 const body=fs.match(/vec3 splashTransmittedColour\([^)]*\) \{([\s\S]*?)\n\}/)[1]
  .replace('vec3 absorption=mix(vec3(18.0),vec3(18.0,17.5,17.0),smoothstep(.01,.08,thickness));','let absorption=mix([18,18,18],[18,17.5,17],smoothstep(.01,.08,thickness));')
  .replace('return environment*exp(-absorption*path)*.065;','return environment.map((v,i)=>v*Math.exp(-absorption[i]*path)*.065);')
  .replace(/\bfloat\b/g,'let');
 const smoothstep=(a,b,v)=>{let t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
 const colour=new Function('environment','thickness','cosine','max','mix','smoothstep',body);
 const sample=(e,t,c)=>colour(e,t,c,Math.max,(a,b,t)=>a.map((v,i)=>v+(b[i]-v)*t),smoothstep);
 for(const t of [.00007,.00065,.005])for(const c of [.05,.3,1]){
  const rgb=sample([.5,.5,.5],t,c);assert.ok(Math.max(...rgb)-Math.min(...rgb)<1e-12);assert.ok(rgb[0]>0&&rgb[0]<.5);
 }
 assert.deepEqual(sample([0,0,0],.00065,1),[0,0,0]);
 const thick=sample([.5,.5,.5],.05,1);assert.ok(thick[2]>thick[0]&&thick[2]/thick[0]<1.05);
 console.log('NEUTRAL_TRANSMISSION',JSON.stringify(sample([.5,.5,.5],.00065,.3)));p.dispose();
});
await test('two LODs partition the same 192 slots and meet High/Low submitted triangle budgets even when every impact is close',async()=>{
 const {splashGeometry,splashProjectedPixels}=await import(file('static/twin/sky/splash_shapes.js'));
 const metrics=[];
 for(const [tier,budget] of [['low',15000],['high',40000]]){
  let total=0;const cost={};
  for(const variant of ['crown','jet','scatter']){
   const pair=[0,1].map(lod=>splashGeometry(variant,tier,lod));
   cost[variant]=pair.map(g=>g.index.count/3);assert.ok(cost[variant][0]>cost[variant][1]);
   total+=Math.max(...cost[variant])*64;
   if(variant==='crown'){
    assert.equal(pair[0].userData.droplets,tier==='low'?8:16);
    const a=pair[0].attributes;let rim=0,upper=0;const bands=new Set();
    for(let i=0;i<a.position.count;i++)if(a.splashPiece.getX(i)===0){
     const t=a.position.getY(i);bands.add(t);rim+=t===1?1:0;upper+=t===.75?1:0;
    }
    assert.equal(rim,tier==='low'?64:96,'same close silhouette sampling as round 2');
    assert.equal(bands.size,5,'all four close height bands remain');if(tier==='high')assert.equal(upper,96);
   }
   for(const g of pair){assert.equal(g.groups.length,0);g.dispose();}
  }
  assert.ok(total<=budget);metrics.push({tier,cost,maxSubmitted:total,budget});
  let seed=17;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
  const p=createPrecipitation(new THREE.Scene(),{tier,random,debugClock:()=>5}),camera=splashCamera();
  p.setPlan({site:{pool:{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}}});
  p.update(5,weather(),camera);assert.equal(p.debugSplashes({at:[0,0,-1],radius:0,count:192,freezeAge:.05}),192);
  const matrix=camera.matrixWorldInverse.elements;
  for(const ring of p.splashes)for(let i=0;i<ring.count;i++)ring.data.splashPosition.setXYZ(i,0,0,i%2?-15:-.7);
  p.update(5,weather(),camera);
  let live=0;
  for(const ring of p.splashes){
   assert.ok(ring.lods.every(o=>o.geometry.instanceCount>0),'both resolutions selected by actual projected size');
   for(const object of ring.lods){
    const g=object.geometry;live+=g.instanceCount;
    for(let i=0;i<g.instanceCount;i++){
     const a=g.attributes,x=a.splashPosition.getX(i),y=a.splashPosition.getY(i),z=a.splashPosition.getZ(i);
     const depth=-(matrix[2]*x+matrix[6]*y+matrix[10]*z+matrix[14]);
     const px=splashProjectedPixels(depth,a.splashShape.getY(i),camera.projectionMatrix.elements[5],720);
     assert.equal(g.userData.lod,px>=24?0:1);
    }
   }
  }
  assert.equal(live,192,'no duplicated or missing LOD impacts');
  assert.ok(Object.values(p.objects).reduce((n,o)=>n+(o.name.startsWith('weather-splash')?o.geometry.index.count/3*o.geometry.instanceCount:0),0)<=budget);
  p.dispose();
 }
 assert.equal(splashProjectedPixels(2,1,2,1000,true),58);console.log('SPLASH_LOD_BUDGET',JSON.stringify(metrics));
});
await test('water receives the scene environment, actual sun irradiance and night light without new programs',()=>{
 const scene=new THREE.Scene(),environment=new THREE.CubeTexture();scene.environment=environment;scene.environmentIntensity=.6;
 const p=createPrecipitation(scene),camera=new THREE.PerspectiveCamera(),direction=new THREE.Vector3(.3,.8,.5).normalize();
 const colour=new THREE.Color(.8,.7,.6);
 for(const light of [[1,1,1],[.003,.004,.009]]){
  p.update(0,weather(),camera,{light,sunDirection:direction,sunColour:colour});
  for(const ring of p.splashes){
   const u=ring.object.material.uniforms;
   assert.equal(u.splashEnvironment.value,environment);assert.equal(u.splashEnvironmentGain.value,.6);
   assert.deepEqual(u.touchLight.value.toArray(),light);assert.deepEqual(u.splashSunDirection.value,direction);assert.deepEqual(u.splashSunColour.value,colour);
  }
 }
 const fs=p.objects.splash.material.fragmentShader;
 const body=fs.match(/float splashFresnel\(float cosine\) \{([\s\S]*?)\n\}/)[1];
 const fresnel=new Function('cosine','clamp','pow',body);
 const f=c=>fresnel(c,(v,a,b)=>Math.max(a,Math.min(b,v)),Math.pow);
 assert.equal(f(1),.02);assert.equal(f(0),1);assert.ok(f(.2)>f(.8));
 p.dispose();environment.dispose();
});
await test('rain shows in every orbit view while the camera is outside, and hides indoors',()=>{
 // Owner 2026-11-19: rain stopped in room and floor views while still orbiting outside.
 const p=createPrecipitation(new THREE.Scene(),{tier:'low'}),eye=new THREE.PerspectiveCamera();
 const target=new THREE.Vector3();eye.position.set(0,5,20);eye.lookAt(target);eye.updateMatrixWorld();
 for(const level of ['house','floor','room','building'])for(const kind of ['rain','snow','mix','hail']){
  p.update(1,weather(kind),eye,{target,level});
  assert.equal(p.objects[kind==='mix'?'rain':kind].visible,true,level+' '+kind+' outside shows');
  assert.equal(p.uniforms.precipCutaway.value,level==='house'?0:1,'a cutaway also clears rain above the hidden roof');
 }
 for(const degrees of [54.9,55,55.1,89.9]){
  eye.position.set(0,30*Math.sin(degrees*Math.PI/180),30*Math.cos(degrees*Math.PI/180));eye.lookAt(target);eye.updateMatrixWorld();
  p.update(2,weather(),eye,{target,level:'house'});assert.equal(p.objects.rain.visible,true,'steep orbit '+degrees);
 }
 const plan={buildings:[{id:'b',position:[0,0],rotation:0,levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[40,0],[40,40],[0,40]]}],
  rooms:[],walls:[],roof:{sections:[{id:'r',kind:'gable',rect:[0,0,40,40],plate:10,pitch:4,overhang:1,ridge:'x'}]}}]};
 p.setPlan(plan);
 eye.position.set(20*.3048,5*.3048,-20*.3048);eye.updateMatrixWorld();
 p.update(3,weather(),eye,{target:eye.position.clone(),level:'room'});
 assert.ok(Object.values(p.objects).every(o=>!o.visible),'a camera under the roof is indoors: nothing falls');
 eye.position.set(-30*.3048,5*.3048,-20*.3048);eye.updateMatrixWorld();
 p.update(4,weather(),eye,{target:new THREE.Vector3(),level:'room'});assert.equal(p.objects.rain.visible,true,'outside again');
 p.dispose();
});
await test('verbatim tier budgets, intensity, mixed weather, invalid input and neutral',()=>{
 for(const [tier,n] of Object.entries({low:3000,medium:4000,high:8000,max:12000})){
  assert.deepEqual(precipitationCounts(tier,weather()),{rain:n,snow:0,hail:0});
  assert.equal(precipitationCounts(tier,weather('snow')).snow,n/2);
  assert.equal(precipitationCounts(tier,weather('hail')).hail,n*.3);
  assert.equal(precipitationCounts(tier,weather('rain',.4)).rain,Math.floor(n*.4));
  assert.deepEqual(precipitationCounts(tier,weather('mix')),{rain:n/2,snow:n/4,hail:0});
  for(const w of [weather('rain',0),weather('rain',NaN),weather('none'),{...weather(),neutral:true}])
   assert.deepEqual(precipitationCounts(tier,w),{rain:0,snow:0,hail:0});
 }
});
await test('physical wind toward compass bearing and only precipitation slows for reduced motion',()=>{
 const w={...weather('snow'),windMps:10,windToDeg:90};
 const v=precipitationVelocity('snow',w,180),r=precipitationVelocity('snow',w,180,true);
 assert.ok(v[0]>0&&Math.abs(v[2])<1e-8);assert.equal(v[1],-.9);
 for(let i=0;i<3;i++)assert.ok(Math.abs(r[i]-v[i]*.35)<1e-9);
 assert.ok(Math.abs(precipitationVelocity('rain',{...w,windToDeg:0},90)[0]-10)<1e-8);
 assert.deepEqual(precipitationVelocity('rain',{windMps:NaN,windToDeg:NaN},NaN),[0,-14,0]);
});
await test('rain projected width has a 1.25 pixel floor, viewport tracks the target and rate controls opacity',()=>{
 const scene=new THREE.Scene(),p=createPrecipitation(scene,{tier:'low'}),camera=new THREE.PerspectiveCamera(60,16/9,.05,500);
 const material=p.objects.rain.material,body=material.vertexShader.match(/float precipitationWidth\(float pixels,float kind\) \{([\s\S]*?)\n\}/)[1];
 const width=new Function('clamp',`return (pixels,kind)=>{${body}}`)((v,a,b)=>Math.max(a,Math.min(b,v)));
 for(const [w,h] of [[1600,900],[1920,1080],[960,540],[320,240]]){
  p.objects.rain.onBeforeRender({getDrawingBufferSize:out=>out.set(w,h)});
  assert.deepEqual(p.uniforms.precipViewport.value.toArray(),[w,h]);
  for(const depth of [.1,1,5,20,40,64,100,500])for(const angle of [0,.4,1.57]){
   const side=new THREE.Vector4(Math.cos(angle)*.018,Math.sin(angle)*.018,0,0).applyMatrix4(camera.projectionMatrix);
   const physical=Math.hypot(side.x*w*.5,side.y*h*.5)/depth;
   assert.ok(width(physical,0)>=1.25);assert.equal(width(physical,1),physical);assert.equal(width(physical,2),physical);
  }
 }
 assert.ok(material.vertexShader.includes('side*position.x*width)*2.0/viewport*gl_Position.w'),'width expands in clip space independently of length');
 assert.ok(material.fragmentShader.includes('mix(.35,.85,precipRate)'),'alpha scales with rain rate');
 p.update(0,{precip:'rain',rate:.45},camera);assert.equal(p.uniforms.precipRate.value,.45);
 p.update(1,{precip:'rain',rate:1},camera);assert.equal(p.uniforms.precipRate.value,1);
 assert.deepEqual(p.uniforms.precipColour.value.toArray(),[.6,.7,.8]);
 assert.ok(material.fragmentShader.includes('precipColour*(precipKind<.5?1.2:1.0)'),'only rain lifts the sky tint');p.dispose();
});
await test('rain length floors fade below 4 px to a dot, with independent width and a safe close-eye segment',()=>{
 const p=createPrecipitation(new THREE.Scene()),m=p.objects.rain.material;
 const body=m.vertexShader.match(/float precipitationLength\(float pixels,float kind,float rate\) \{([\s\S]*?)\n\}/)[1];
 const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);};
 const length=new Function('max','min','mix','clamp','smoothstep',`return (pixels,kind,rate)=>{${body}}`)(Math.max,Math.min,(a,b,t)=>a+(b-a)*t,(v,a,b)=>Math.max(a,Math.min(b,v)),smoothstep);
 assert.equal(length(0,0,1),1.25,'camera-axis streak is a dot');
 for(const pixels of [.01,.1,1,2,3])assert.ok(length(pixels,0,1)<10,'sub-4px streak floor fades out');
 for(const rate of [.45,1])for(const viewport of [[1920,1080],[960,540],[320,240]])for(const depth of [2.5,3,20,60,100,500])for(const velocity of [[0,-14,0],[5,-14,4],[0,0,0],[0,0,-14]]){
  const camera=new THREE.PerspectiveCamera(38,viewport[0]/viewport[1],.1,1000),eye=new THREE.Vector4(.1,.2,-depth,1);
  const fall=new THREE.Vector3(...velocity);if(fall.length()>1e-5)fall.normalize();else fall.set(0,-1,0);
  const project=v=>v.applyMatrix4(camera.projectionMatrix),clip=project(eye.clone());
  const head=project(eye.clone().add(new THREE.Vector4(...fall.toArray(),0).multiplyScalar(.35)));
  const tail=project(eye.clone().sub(new THREE.Vector4(...fall.toArray(),0).multiplyScalar(.35)));
  const delta=new THREE.Vector2((head.x/Math.max(Math.abs(head.w),.0001)-tail.x/Math.max(Math.abs(tail.w),.0001))*viewport[0]*.5,
    (head.y/Math.max(Math.abs(head.w),.0001)-tail.y/Math.max(Math.abs(tail.w),.0001))*viewport[1]*.5);
  const physical=delta.length(),direction=physical>1e-5?delta.clone().divideScalar(Math.max(physical,1e-5)):new THREE.Vector2(0,-1);
  const pixels=length(physical,0,rate);if(physical>=4)assert.ok(pixels>=(rate===1?10:6));else assert.ok(pixels<(rate===1?10:6));
  for(const kind of [1,2])assert.equal(length(physical,kind,rate),physical,'snow/hail keep physical length');
  const side=new THREE.Vector2(-direction.y,direction.x),corners=[];
  for(const [x,y] of [[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]]){
   const offset=direction.clone().multiplyScalar(y*pixels).addScaledVector(side,x*1.25);
   const c=clip.clone();c.x+=offset.x*2/viewport[0]*clip.w;c.y+=offset.y*2/viewport[1]*clip.w;
   corners.push(new THREE.Vector2(c.x/c.w*viewport[0]*.5,c.y/c.w*viewport[1]*.5));assert.ok(c.toArray().every(Number.isFinite));
  }
  assert.ok(Math.abs(corners[0].distanceTo(corners[1])-1.25)<1e-8,'length floor never stretches width');
  assert.ok(Math.abs(corners[1].distanceTo(corners[2])-pixels)<1e-8);
  assert.ok(Math.abs(direction.dot(side))<1e-9);
 }
 assert.ok(m.vertexShader.includes('direction*position.y*streakLength'));
 assert.ok(m.vertexShader.includes('eye.xy+=side*position.x*size.x+direction*position.y*size.y;'),'snow/hail preserve physical billboards, including top view');
 assert.ok(m.vertexShader.includes('if(distance(world,cameraPosition)<(precipKind<.5?.06:3.0)){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}'));
 assert.ok(m.vertexShader.includes('float segment=precipitationSegment(-eye.z);'));
 assert.ok(m.fragmentShader.includes('if(distance(particleWorld,cameraPosition)<(precipKind<.5?.06:3.0))discard;'));
 assert.ok(m.fragmentShader.includes('smoothstep(halfExtent*.8,halfExtent,edge)'),'outer fifth of focus box fades');
 assert.ok(!m.fragmentShader.includes('smoothstep(40.0,64.0'));p.dispose();
});
await test('off-axis eye-plane drops cannot project huge quads, from any camera orientation',()=>{
 const p=createPrecipitation(new THREE.Scene()),shader=p.objects.rain.material.vertexShader;
 const body=name=>shader.match(new RegExp('(?:float|bool) '+name+'\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}'))[1];
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)),mix=(a,b,t)=>a+(b-a)*t;
 const smoothstep=(a,b,x)=>{const t=clamp((x-a)/(b-a),0,1);return t*t*(3-2*t);};
 const visible=new Function('depth','kind',body('precipitationVisibleDepth'));
 const segment=new Function('depth','min','max',body('precipitationSegment'));
 const width=new Function('pixels','kind','clamp',body('precipitationWidth'));
 const length=new Function('pixels','kind','rate','max','min','mix','clamp','smoothstep',body('precipitationLength'));
 assert.ok(shader.includes('if(!precipitationVisibleDepth(-eye.z,precipKind))'),'actual vertex path rejects forward depth before projection');
 const lens=new THREE.PerspectiveCamera(38,16/9,.1,1000),eye=new THREE.Vector4(0,4,-.1,1),fall=new THREE.Vector4(0,-14,4,0).normalize().multiplyScalar(.35);
 const clip=eye.clone().applyMatrix4(lens.projectionMatrix),head=eye.clone().add(fall).applyMatrix4(lens.projectionMatrix),tail=eye.clone().sub(fall).applyMatrix4(lens.projectionMatrix);
 const oldLength=Math.abs(head.y/Math.max(Math.abs(head.w),.0001)-tail.y/Math.max(Math.abs(tail.w),.0001))*540;
 const oldWidth=.018*lens.projectionMatrix.elements[0]*960/.1,centreY=clip.y/clip.w*540;
 assert.ok(Math.hypot(4,.1)>3&&oldWidth>200&&oldLength/2>Math.abs(centreY)+540,'old radial cull admits a broad vertical quad that actually crosses the entire viewport');
 assert.equal(visible(.01,0),false,'eye-plane drops still cull');
 assert.equal(visible(.1,0),true,'rain can reach close views');
 assert.equal(visible(.1,1),false,'snow keeps its previous cull');
 console.log('NEAR_PLANE_REGRESSION',JSON.stringify({oldWidth,oldLength,centreY,radial:Math.hypot(4,.1)}));
 for(const pose of [[0,0,0],[90,55,35],[-10,7,-12]])for(const direction of [[0,0,-1],[1,0,0],[0,1,0],[.2,-.4,.6]]){
  const camera=new THREE.PerspectiveCamera(38,16/9,.1,1000);camera.position.fromArray(pose);
  camera.lookAt(camera.position.clone().add(new THREE.Vector3(...direction)));camera.updateMatrixWorld();
  for(const z of [-.0001,-.01,-.079,-.081,-.1,-.3,-1,-2.99,-3,-3.49,-3.5,-4,-12,-100])for(const x of [-100,-4,0,4,100]){
   const local=new THREE.Vector3(x,.2,z),world=local.clone().applyMatrix4(camera.matrixWorld),eye=world.clone().applyMatrix4(camera.matrixWorldInverse);
   const accepted=visible(-eye.z,0);if(-z<.08)assert.equal(accepted,false,'radially distant but eye-plane drop is culled');
   if(!accepted)continue;
   const physicalSegment=segment(-eye.z,Math.min,Math.max);
   assert.ok(-eye.z-physicalSegment*.5>0,'both endpoints stay in front of the eye, even at 8 cm');
   const w=width(.018*camera.projectionMatrix.elements[0]*960/Math.max(-eye.z,.0001),0,clamp);
   // Eye-plane endpoints used to produce >100,000 px at z=-.01. The actual
   // shader functions now bound even pathological projection inputs.
   for(const projected of [0,1,4,10,100,10000,1e8]){
    const h=length(projected,0,1,Math.max,Math.min,mix,clamp,smoothstep);
    assert.ok(w>=1.25&&w<=2.5&&h>=1.25&&h<=96&&Number.isFinite(w*h));
   }
  }
 }
 p.dispose();
});
await test('actual fade function scales with box edges and excludes near-camera drops',()=>{
 const p=createPrecipitation(new THREE.Scene());
 const body=p.objects.rain.material.fragmentShader.match(/float precipitationFade\(float nearStart,float nearEnd,float boxWeight\)\{([\s\S]*?)\n\}/)[1].replace(/\bfloat /g,'const ');
 const distance=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i]));
 const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/Math.max(b-a,.0001)));return t*t*(3-2*t);};
 const fade=new Function('particleWorld','cameraPosition','precipRadius','precipFog','precipCentre','precipAnchor','precipBox','distance','smoothstep','max','exp','nearStart','nearEnd','boxWeight','mix',body);
 const world=(x,y,z)=>Object.assign([x,y,z],{xz:[x,z]});
 for(const d of [.3,.5,1,4]){
  const alpha=fade(world(10,5,0),[10,5,d],10000,0,[0,0],world(0,0,0),{x:2},distance,smoothstep,Math.max,Math.exp,.03,.06,0,(a,b,t)=>a+(b-a)*t);
  assert.equal(alpha,1,'close splashes survive both the old three-metre fade and the falling-box edge');
 }
 assert.ok(p.objects.splash.material.fragmentShader.includes('precipitationFade(.03,.06,0.0)'),'actual splash fragment uses that fade');
 for(const h of [18,30,64]){
  const evaluate=(x,d=10)=>fade(world(x,5,0),[x,5,d],10000,0,[0,0],world(0,0,0),{x:2*h},distance,smoothstep,Math.max,Math.exp,.06,.12,1,(a,b,t)=>a+(b-a)*t);
  assert.equal(evaluate(.8*h),1);assert.ok(Math.abs(evaluate(.9*h)-.5)<1e-9);
  assert.equal(evaluate(h),0);assert.equal(evaluate(2*h),0);
  for(const d of [0,.01,.06])assert.equal(evaluate(0,d),0);
  for(const d of [.3,.5,1,3])assert.equal(evaluate(0,d),1,'close rain has no three-metre fade hole');
  assert.equal(evaluate(0,3.5),1);assert.equal(evaluate(0,100),1,'camera distance no longer removes rain at the house');
 }
 const fogFade=fade(world(0,5,0),[0,5,150],10000,3.912/300,[0,0],world(0,0,0),{x:128},distance,smoothstep,Math.max,Math.exp,.06,.12,1,(a,b,t)=>a+(b-a)*t);
 assert.ok(Math.abs(fogFade-Math.exp(-3.912/2))<1e-10,'particle veil uses camera distance');
 p.dispose();
});
await test('expired and eye-plane splash slots are culled before rasterizing their quad',()=>{
 const p=createPrecipitation(new THREE.Scene()),shader=p.objects.splash.material.vertexShader;
 const body=shader.match(/bool splashVisible\(float age,float depth\) \{([\s\S]*?)\n\}/)[1],visible=new Function('age','depth',body);
 for(const age of [-1000,-.01,0,.1,.419,.42,.421,100])for(const depth of [-10,0,.02,.03,.1,.3,.5,1,3,3.49,3.5,10,100])
  assert.equal(visible(age,depth),age>=0&&age<=.3&&depth>=.03);
 assert.ok(shader.indexOf('if(!splashVisible(splashAge,-eye.z))')>=0);
 assert.ok(shader.indexOf('if(splashAge>splashLife||precipCutaway')<shader.indexOf('float grow='),'lifetime and signed depth gate the actual vertex path before expansion');
 p.dispose();
});
await test('focus box wraps in shader coordinates without moving every seed',()=>{
 const p=wrappedPosition([.1,.2,.3],[4,-5,6],[10,20,30]);
 const moved=wrappedPosition([.1,.2,.3],[4,-5,6],[11,21,31]);
 assert.deepEqual(moved,p,'a small camera move keeps the same world particles');
 const far=wrappedPosition([.1,.2,.3],[4,-5,6],[1000,2000,3000]);
 for(let i=0;i<3;i++)assert.ok(Math.abs(far[i]-[1000,2000,3000][i])<=[64,48,64][i]);
 const scene=new THREE.Scene(),pfx=createPrecipitation(scene,{tier:'low'}),camera=new THREE.PerspectiveCamera();
 const seeds=pfx.objects.rain.geometry.attributes.precipSeed,version=seeds.version,copy=seeds.array.slice();
 const target=new THREE.Vector3(10,0,20);
 pfx.update(0,weather(),camera,{target});camera.position.set(100,80,-50);pfx.update(1,weather(),camera,{target});
 assert.equal(pfx.uniforms.precipAnchor.value.x,100);assert.equal(pfx.uniforms.precipAnchor.value.z,-50);
 assert.deepEqual(pfx.uniforms.precipBox.value.toArray(),[128,88,128]);
 assert.equal(pfx.uniforms.precipAnchor.value.y,44);assert.equal(seeds.version,version);assert.deepEqual(seeds.array,copy);
 for(const eye of [[10,1,20],[10,10,60],[10,200,420]]){
  camera.position.fromArray(eye);pfx.update(2,weather(),camera,{target});
  const box=pfx.uniforms.precipBox.value,anchor=pfx.uniforms.precipAnchor.value;
  assert.equal(box.x,2*Math.max(1,Math.min(64,.75*camera.position.distanceTo(target))));
  assert.equal(box.z,box.x);assert.equal(anchor.y-box.y/2,0);
  assert.equal(anchor.y+box.y/2,Math.max(1,25*Math.min(1,box.x*box.x/1296),camera.position.y+Math.max(.8,Math.min(8,box.x*.2))));
  const world=wrappedPosition([.1,.2,.3],[4,-5,6],anchor.toArray(),box.toArray());
  world.forEach((v,i)=>assert.ok(Math.abs(v-anchor.getComponent(i))<=box.getComponent(i)/2));
 }
 assert.equal(seeds.version,version);assert.deepEqual(seeds.array,copy);
 pfx.setPlan({site:{terraces:[{polygon:[[0,0],[100,0],[100,100],[0,100]],height:10,blend:0}]}});
 camera.position.set(10,5,-10);target.set(10,0,-10);pfx.update(3,weather(),camera,{target});
 assert.ok(Math.abs(pfx.uniforms.precipAnchor.value.y-pfx.uniforms.precipBox.value.y/2-3.048)<1e-9,'bottom follows ground under target');
 assert.ok(pfx.objects.rain.material.vertexShader.includes('mod('));pfx.dispose();
});
await test('hard upward splash sampling uses layered ground, path, deck and roof heights; samples pool/spa water; excludes beds, grass and interiors',()=>{
 const plan={site:{terraces:[{polygon:[[0,0],[20,0],[20,20],[0,20]],height:3,blend:0,material:'lawn'}],
  hardscape:[{polygon:[[0,0],[10,0],[10,10],[0,10]],elevation:1},{kind:'path',points:[[25,0],[25,20]],width:4}],
  beds:[{polygon:[[1,1],[3,1],[3,3],[1,3]]}],pool:{polygon:[[4,4],[6,4],[6,6],[4,6]],features:[{kind:'spa',polygon:[[7,7],[9,7],[9,9],[7,9]]}]}},
  buildings:[{id:'b',position:[40,0],rotation:90,base:2,levels:[{id:'l',elevation:0,outline:[[0,0],[10,0],[10,10],[0,10]]}],porches:[{polygon:[[12,0],[16,0],[16,4],[12,4]],floor:5}]}]};
 const roofs=new Map([['b',{sections:[{kind:'flat',rect:[0,0,10,10],plate:12}]}]]),sample=createSplashSampler(plan,roofs);
 assert.ok(Math.abs(sample(1.5*.3048,-5*.3048).position[1]-4.3*.3048-.006)<1e-8);
 for(const [x,y] of [[2,2],[15,15],[100,100]])assert.equal(sample(x*.3048,-y*.3048),null);
 assert.equal(sample(5*.3048,-5*.3048).kind,'water');
 assert.ok(Math.abs(sample(5*.3048,-5*.3048).position[1]-(3-.12-.25)*.3048-.006)<1e-8);
 assert.ok(Math.abs(sample(8*.3048,-8*.3048).position[1]-(3-.12+.45+1-2/12)*.3048-.006)<1e-8);
 assert.ok(sample(25*.3048,-5*.3048));
 assert.ok(Math.abs(sample(38*.3048,-14*.3048).position[1]-7*.3048-.006)<1e-8,'rotated deck');
 const roof=sample(35*.3048,-5*.3048);assert.equal(roof.kind,'roof');assert.ok(Math.abs(roof.position[1]-14*.3048-.006)<1e-8);
 const interior=createSplashSampler(plan,new Map());assert.equal(interior(35*.3048,-5*.3048),null);
});
await test('fixed material identities/keys, one draw per kind plus splashes, bounded spawning and disposal',()=>{
 let randomCalls=0;
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),p=createPrecipitation(scene,{tier:'high',random:()=>{randomCalls++;return .5;}});
 camera.copy(splashCamera());camera.updateMatrixWorld();
 p.setStage({centre:[0,0],radius:100});
 p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}},new Map());randomCalls=0;
 const entries=Object.values(p.objects),materials=entries.map(o=>o.material),keys=materials.map(m=>m.customProgramCacheKey()),versions=materials.map(m=>m.version);
 let time=0;
 for(const kind of ['none','rain','snow','mix','hail','rain']){
  p.update(time++,weather(kind),camera);p.update(time++,weather(kind),camera);
  assert.equal(entries.filter(o=>o.visible&&o.geometry.instanceCount>0).length,{none:0,rain:2,snow:1,mix:3,hail:1}[kind],kind+' draw submissions');
 }
 assert.ok(randomCalls/7<=6*12,'bounded catch-up after stalls');
 assert.ok(p.objects.splash.geometry.instanceCount<=192);
 assert.deepEqual(entries.map(o=>o.material),materials);assert.deepEqual(materials.map(m=>m.customProgramCacheKey()),keys);assert.deepEqual(materials.map(m=>m.version),versions);
 assert.equal(entries.length,9);
 for(const o of entries){assert.equal(o.castShadow,false);assert.equal(o.receiveShadow,false);assert.equal(o.layers.isEnabled(31),false);assert.equal(o.material.lights,false);assert.equal(o.material.depthWrite,false);assert.equal(o.material.forceSinglePass,true,'flat double-sided particles submit once');assert.deepEqual(o.raycast(),undefined);}
 p.update(3,{...weather(),neutral:true},camera);assert.ok(entries.every(o=>!o.visible));
 p.update(4,weather(),camera,{unlit:true});assert.ok(entries.every(o=>!o.visible));
 let released=0;for(const o of entries){o.geometry.addEventListener('dispose',()=>released++);o.material.addEventListener('dispose',()=>released++);}
 p.dispose();p.dispose();assert.equal(released,18);assert.equal(scene.children.length,0);
});
await test('rain splashes have bounded real-time lifetime/rate and do not multiply on reduced-motion or stale frames',()=>{
 let rng=0;const random=()=>{rng++;return .5;},scene=new THREE.Scene(),camera=splashCamera();
 const p=createPrecipitation(scene,{tier:'low',random});
 p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}});rng=0;
 p.update(0,weather(),camera);
 for(let t=1;t<=100;t++)p.update(t/100,weather(),camera,{reduced:true});
 assert.ok(rng/7>=119&&rng/7<=120,'120 candidate samples per second on low, motion does not slow the weather rate');
 const born=p.splashes[2].data.splashBorn.array;
 assert.ok(born.some(t=>t>=.58&&t<=1));assert.equal(p.splashes.some(r=>r.lods.some(o=>o.visible)),true);
 const count=rng;p.update(1000,weather(),camera);assert.ok((rng-count)/7<=12,'bounded catch-up after long sleep');
 p.update(1001,weather('snow'),camera);assert.equal(p.splashes.some(r=>r.lods.some(o=>o.visible)),false);assert.ok(born.every(t=>t<0));
 p.dispose();
});
await test('steep roof blocks the deck beneath it, and sampler refresh follows edits',()=>{
 const plan={buildings:[{id:'b',levels:[{id:'l',elevation:0}],porches:[{polygon:[[0,0],[20,0],[20,20],[0,20]],floor:2}]}]};
 const roofs=new Map([['b',{sections:[{kind:'shed',rect:[0,0,20,20],plate:20,pitch:24,low_side:'x0'}]}]]);
 assert.equal(createSplashSampler(plan,roofs)(5*.3048,-5*.3048),null,'no sprite under a steep roof');
 const p=createPrecipitation(new THREE.Scene(),{tier:'low',random:()=>.5}),camera=splashCamera();
 p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}});p.update(0,weather(),camera);p.update(1,weather(),camera);
 assert.equal(p.splashes.some(r=>r.lods.some(o=>o.visible)),true);p.setPlan({});p.update(2,weather(),camera);assert.equal(p.splashes.some(r=>r.lods.some(o=>o.visible)),false);p.dispose();
});
await test('paver paths splash on the stones at their actual height, never the lawn gaps',async()=>{
 const {yardPaverLayout}=await import(file('static/twin/paver_path.js'));
 const path={kind:'path',id:'stepping',points:[[0,0],[0,20]],width:4,pavers:{layout:'stepping',length_in:24,width_in:24,gap_in:12,lay:'level',joint:'lawn'}};
 const layout=yardPaverLayout(path),sample=createSplashSampler({site:{hardscape:[path]}});
 assert.ok(layout.pavers.length>1);const centre=layout.pavers[0].centre,hit=sample(centre[0]*.3048,-centre[1]*.3048);
 assert.ok(hit);assert.ok(Math.abs(hit.position[1]-(1/12)*.3048-.006)<1e-8,'paver tops stand one inch over grade');
 assert.equal(sample(1.8*.3048,-centre[1]*.3048),null,'lawn beside the stepping stones is not hardscape');
});
await test('same precipitation draws over cloud composite and before bloom; AO excludes it',async()=>{
 const {createPost}=await import(file('static/twin/post.js'));
 const {createCloudPass}=await import(file('static/twin/sky/cloud_pass.js'));
 const {createCloudNoise}=await import(file('static/twin/sky/clouds.js'));
 const r=new Renderer(),scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),noise=createCloudNoise({size:8,detail:4});
 const cloud=createCloudPass(r,{tier:'high',noise}),p=createPrecipitation(scene,{tier:'low'});p.update(0,weather('mix'),camera);
 cloud.update({coverage:1,type:'nimbostratus'});cloud.frame(1);
 const post=createPost(r,scene,camera,{clouds:cloud}),calls=[],draw=r.render;
 r.render=function(s,c){
  if(s===scene)calls.push({scene:true,override:!!s.overrideMaterial,visible:Object.values(p.objects).filter(o=>o.visible&&o.layers.test(c.layers)).map(o=>o.name)});
  else calls.push({name:s.material?.name,fragment:s.material?.fragmentShader});
  return draw.call(this,s,c);
 };
 post.render();const composite=calls.findIndex(c=>c.name==='twin-cloud-composite');
 const particles=calls.findIndex(c=>c.visible?.includes('weather-rain'));
 assert.ok(particles>composite&&composite>=0);
 assert.ok(calls.slice(0,particles).filter(c=>c.scene).every(c=>!c.visible.length),'beauty opaque/AO omit precipitation');
 assert.ok(calls.slice(particles+1).some(c=>c.fragment?.includes('luminosityThreshold')),'bloom follows precipitation');
 cloud.update({coverage:0,type:'none'});calls.length=0;post.render();assert.equal(calls.filter(c=>c.visible?.includes('weather-rain')).length,1,'clear composer draws each kind once');
 calls.length=0;r.render(scene,camera);assert.equal(calls[0].visible.length,2,'plain canvas draws the same rain and snow');
 post.dispose();cloud.dispose();noise.dispose();p.dispose();
});
await test('real household mount: previews, editor neutral/Live, Unlit, captures, hide/lock and cleanup',async()=>{
 let v,e;try{
  const mount=async(editor=false)=>{const el=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(el);}return mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});};
  v=await mount();e=await mount(true);assert.ok(v.precipitation);assert.ok(e.precipitation);
  const states={'weather.home':{state:'pouring',attributes:{}}};
  for(const x of [v,e])x.live={peek:()=>states,stale:()=>false,draw(){},stop(){},closeRoom(){}};
 v.setTime('day');e.setTime('day');assert.equal(v.precipitation.objects.rain.geometry.instanceCount,3000);assert.equal(e.precipitation.objects.rain.visible,false);
 const day=v.precipitation.uniforms.touchLight.value.length();
 assert.equal(v.precipitation.uniforms.splashEnvironment.value,v.scene.environment,'the mounted splash samples the fixed scene PMREM cube');
 v.setTime('night');assert.ok(v.precipitation.uniforms.touchLight.value.length()<day*.2,'actual scene light darkens water at night');
 v.setTime('day');
  const mats=Object.values(v.precipitation.objects).map(o=>o.material.uuid);
  const building=v.plan.buildings.find(b=>b.rooms?.length),room=building.rooms.find(r=>r.state!=='ghost');
  for(const level of [{building:building.id,floor:room.level},{building:building.id,room:room.id}]){
   v.levels.go(level,{immediate:true});v.render();
   // Owner 2026-11-19: a floor or room focus still orbits outside, so rain keeps falling
   // (drops over the rooms are culled by the cover field on the GPU).
   assert.ok(v.precipitation.objects.rain.visible&&v.precipitation.objects.rain.geometry.instanceCount>0,'real floor/room levels keep the rain while orbiting outside');
  }
  v.levels.go({level:'house'},{immediate:true});v.render();assert.equal(v.precipitation.objects.rain.visible,true);
  e.setLiveWeather(true);e.setView(e.levelKeys()[0]);e.render();assert.equal(e.precipitation.objects.rain.visible,true,'an editor floor view orbits outside, so it keeps the rain');e.setView('ext');
  const {sunDiscVisibility}=await import(file('static/twin/sky/weather.js'));
  let clearVisibility=0,pouringVisibility=1;
  for(const name of ['clear','rain','pouring','snow','fog','thunderstorm']){
   v.setWeatherPreview(name);assert.equal(v.precipitation.objects.snow.visible,name==='snow');
   const expected=sunDiscVisibility(v.weather,v.cloudShadow.centre());
   const visibility=v.precipitation.uniforms.splashSunVisibility.value;
   assert.ok(Math.abs(visibility-expected)<1e-10,'mounted sun visibility follows sunDiscVisibility (cloud cover, transmittance and haze)');
   if(name==='clear')clearVisibility=visibility;if(name==='pouring')pouringVisibility=visibility;
  }
  assert.ok(clearVisibility>.99&&pouringVisibility<clearVisibility*.00001);
  e.setLiveWeather(true);assert.equal(e.precipitation.objects.rain.visible,true);
  v.setUnlit(true);assert.ok(Object.values(v.precipitation.objects).every(o=>!o.visible));v.setUnlit(false);v.setTime('now');
  assert.equal(v.precipitation.objects.rain.visible,true);assert.deepEqual(Object.values(v.precipitation.objects).map(o=>o.material.uuid),mats);
  const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));const visibility=createPieceVisibility();visibility.set(new Set(),new Set(['effect','planting','roof','hardscape']));visibility.apply(v.scene);
  assert.equal(v.precipitation.objects.rain.visible,true);visibility.restore();
  const sample=createSplashSampler(v.plan,v.roofSurfaces);let hits=0;
  for(let x=-30;x<180;x+=4)for(let y=-30;y<180;y+=4){const hit=sample(x*.3048,-y*.3048);if(hit){hits++;assert.ok(hit.position.every(Number.isFinite));assert.ok(hit.normal[1]>.55);}}
  assert.ok(hits>0,'actual household has splash receivers');
 }finally{v?.dispose();e?.dispose();}
});
await test('1920x1080 household low-tier frustum census uses identical seeds before and after',async()=>{
 let v,p;try{
  const el=new Element();el.clientWidth=1920;el.clientHeight=1080;
  v=await mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});
  v.camera.aspect=1920/1080;v.camera.updateProjectionMatrix();v.levels.go({level:'house'},{immediate:true});
  let rng=0x12345678;p=createPrecipitation(new THREE.Scene(),{tier:'low',random:()=>{rng=(Math.imul(rng,1664525)+1013904223)>>>0;return rng/4294967296;}});
  p.setPlan(v.plan,v.roofSurfaces);
  const seed=p.objects.rain.geometry.attributes.precipSeed,version=seed.version,copy=seed.array.slice();
  for(const framing of ['house','weather-harness']){
   if(framing==='weather-harness'){
    // Exactly horizon_look() in test_twin_weather_live.py, without a browser.
    const c=v.controls.target.clone(),d=v.camera.position.clone().sub(c);d.y=Math.max(3,d.length()*.08);
    v.setCameraState({position:c.clone().add(d).toArray(),target:c.toArray()});
   }
   v.camera.updateMatrixWorld(true);
   const eye=v.camera.position,target=v.controls.target,houseDistance=eye.distanceTo(target);
   const frustum=new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(v.camera.projectionMatrix,v.camera.matrixWorldInverse));
   for(const rate of [.45,1]){
    p.update(0,weather('rain',rate),v.camera,{target});
    const count=p.objects.rain.geometry.instanceCount,box=p.uniforms.precipBox.value.toArray(),anchor=p.uniforms.precipAnchor.value.toArray();
    const results={};
    for(const before of [true,false]){
     let inside=0,nearer=0,nonzeroFade=0;
     for(let i=0;i<count;i++){
      const s=Array.from(seed.array.subarray(i*3,i*3+3));
      const world=new THREE.Vector3(...wrappedPosition(s,[0,0,0],before?eye.toArray():anchor,before?[128,96,128]:box));
      if(!frustum.containsPoint(world))continue;inside++;
      const distance=world.distanceTo(eye);if(distance>=houseDistance)continue;nearer++;
      const radial=Math.hypot(world.x-anchor[0],world.z-anchor[2]);
      if(distance>(before?.8:2.5)&&(before?distance<64:radial<box[0]/2))nonzeroFade++;
     }
     results[before?'before':'after']={inside,nearer,nonzeroFade};
    }
    assert.ok(results.after.nearer>results.before.nearer,'density rises in front of the house');
    assert.ok(results.after.nonzeroFade>results.before.nonzeroFade,'extra instances survive distance and near fades');
    console.log('FRUSTUM_CENSUS',JSON.stringify({framing,rate,count,eye:eye.toArray(),target:target.toArray(),houseDistance,box,anchor,...results}));
   }
  }
  assert.equal(seed.version,version);assert.deepEqual(seed.array,copy);
 }finally{p?.dispose();v?.dispose();}
});
await test('hiding under cover and resuming outside is never sticky across repeated cycles, and low pose beside a 2 ft pit is uncovered',async()=>{
 const {createSkyCover}=await import(file('static/twin/sky/sky_cover.js'));
 const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
 const {createPost}=await import(file('static/twin/post.js'));
 const idleQueue=[];let nextIdle=1;
 const prevRic=globalThis.requestIdleCallback,prevCic=globalThis.cancelIdleCallback;
 globalThis.requestIdleCallback=cb=>{const id=nextIdle++;idleQueue.push({id,cb});return id;};
 globalThis.cancelIdleCallback=id=>{const i=idleQueue.findIndex(x=>x.id===id);if(i>=0)idleQueue.splice(i,1);};
 const drainIdle=(max=100)=>{let n=0;while(idleQueue.length&&n<max){idleQueue.shift().cb({timeRemaining:()=>4,didTimeout:false});n++;}return n;};
 const syntheticPlan={
  buildings:[{id:'house',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[20,0],[20,20],[0,20]]}],
   rooms:[],walls:[],roof:{sections:[{id:'r',kind:'flat',rect:[0,0,20,20],plate:10}]}}],
  site:{hardscape:[{id:'deck',polygon:[[22,-4],[52,-4],[52,24],[22,24]]}],
   furniture:[{id:'fire-pit',kind:'fire_pit',at:[36,10],radius:2,height:2}]},
 };
 const scene=new THREE.Scene(),renderer=new Renderer(),camera=splashCamera();
 const ws=installWeatherSurface(scene),p=createPrecipitation(scene,{tier:'high'});
 const post=createPost(renderer,scene,camera,{tier:'high'});
 post.setWetGround({weatherSurface:ws.uniforms.weatherSurface,...p.uniforms});
 const pouring={precip:'rain',rate:1,wetness:1,puddles:1,windMps:3,windToDeg:90,neutral:false};
 let t=10;
 try{
  const synCover=createSkyCover(syntheticPlan);
  p.setPlan(syntheticPlan,null,synCover);
  assert.equal(p.uniforms.precipEdge.value,null,'setPlan clears stale edge texture until fresh field finishes');
  assert.ok(drainIdle()>0,'idle callback incrementally bakes wet edge field');
  assert.ok(p.uniforms.precipEdge.value,'uploadEdge populates precipEdge after idle bake');
  assert.ok(p.uniforms.precipCoverBounds.value.z>p.uniforms.precipCoverBounds.value.x,'uploadEdge syncs precipCoverBounds immediately');
  ws.update(pouring,t);
  // Low pose 0.4 m above the open deck, 0.9 m beside the 2 ft fire pit is NOT covered.
  const pitX=36*.3048,pitZ=-10*.3048,deckY=.3*.3048;
  camera.position.set(pitX-.9,deckY+.4,pitZ);camera.lookAt(pitX,deckY+.2,pitZ);camera.updateMatrixWorld();
  assert.equal(synCover.coverTop(camera.position.x,camera.position.z),-Infinity,'open deck beside 2 ft fire pit has no roof cover');
  for(let i=0;i<10;i++){t+=.05;ws.update(pouring,t);p.update(t,pouring,camera,{target:new THREE.Vector3(pitX,deckY,pitZ)});post.wetReflections.update();}
  assert.equal(p.objects.rain.visible,true,'rain draws at 0.4 m beside 2 ft fire pit');
  assert.equal(p.objects.rain.geometry.instanceCount,8000);
  assert.ok(p.splashes.some(r=>r.lods.some(o=>o.visible)),'splashes draw beside low fire pit');
  assert.equal(post.wetReflections.enabled,true,'SSR active beside low fire pit');
  // Repeatedly enter cover (under roof) and return outside across 5 cycles.
  let edgeBefore=p.uniforms.precipEdge.value;
  for(let cycle=0;cycle<5;cycle++){
   camera.position.set(3,1.6,-3);camera.lookAt(4,1.0,-4);camera.updateMatrixWorld();
   assert.ok(Number.isFinite(synCover.coverTop(camera.position.x,camera.position.z))&&camera.position.y<synCover.coverTop(camera.position.x,camera.position.z));
   t+=.05;ws.update(pouring,t);p.update(t,pouring,camera);post.wetReflections.update();
   assert.equal(p.objects.rain.visible,false,`cycle ${cycle}: rain hidden under cover`);
   assert.equal(p.objects.rain.geometry.instanceCount,0,`cycle ${cycle}: rain count 0 under cover`);
   assert.ok(p.splashes.every(r=>r.lods.every(o=>!o.visible)),`cycle ${cycle}: splashes hidden under cover`);
   assert.equal(ws.uniforms.weatherSurface.value.x,1,`cycle ${cycle}: wetness stays intact under cover`);
   assert.equal(ws.uniforms.weatherSurface.value.z,1,`cycle ${cycle}: puddles stay intact under cover`);
   assert.equal(p.uniforms.precipEdge.value,edgeBefore,`cycle ${cycle}: precipEdge intact under cover`);
   assert.equal(post.wetReflections.enabled,true,`cycle ${cycle}: SSR reflection field intact under cover`);
   // Also exercise a plan refresh + idle completion while covered on cycle 2.
   if(cycle===2){
    p.setPlan(syntheticPlan,null,synCover);drainIdle();
    t+=.05;ws.update(pouring,t);p.update(t,pouring,camera);post.wetReflections.update();
    assert.equal(p.objects.rain.visible,false,'still hidden under cover after refresh');
    assert.ok(p.uniforms.precipEdge.value&&post.wetReflections.enabled,'idle upload works while covered');
    edgeBefore=p.uniforms.precipEdge.value;
   }
   camera.position.set(pitX-.9,deckY+.4,pitZ);camera.lookAt(pitX,deckY+.2,pitZ);camera.updateMatrixWorld();
   for(let f=0;f<8;f++){t+=.05;ws.update(pouring,t);p.update(t,pouring,camera,{target:new THREE.Vector3(pitX,deckY,pitZ)});post.wetReflections.update();}
   assert.equal(p.objects.rain.visible,true,`cycle ${cycle}: rain resumes after leaving cover`);
   assert.equal(p.objects.rain.geometry.instanceCount,8000,`cycle ${cycle}: full rain count resumes`);
   assert.ok(p.splashes.some(r=>r.lods.some(o=>o.visible)),`cycle ${cycle}: splashes resume after leaving cover`);
   assert.equal(ws.uniforms.weatherSurface.value.x,1,`cycle ${cycle}: wetness intact after leaving cover`);
   assert.ok(p.uniforms.precipEdge.value&&p.uniforms.precipCover.value,`cycle ${cycle}: fields intact after leaving cover`);
   assert.equal(post.wetReflections.enabled,true,`cycle ${cycle}: SSR enabled after leaving cover`);
  }
  // Real household fire pit: exact close pose (0.9 m away, 0.4 m above deck) + full 360-degree ring.
  const hhCover=createSkyCover(input.plan);
  p.setPlan(input.plan,null,hhCover);drainIdle(200);
  const pit=[18.112871651337194,.0974,-39.503949940810244];
  for(let k=0;k<12;k++){
   const a=k*Math.PI/6,cx=pit[0]+Math.cos(a)*.9,cz=pit[2]+Math.sin(a)*.9;
   assert.equal(hhCover.coverTop(cx,cz),-Infinity,`household pit ring angle ${k*30}deg uncovered`);
  }
  camera.position.set(17.224,pit[1]+.4,-39.360);camera.lookAt(pit[0],pit[1],pit[2]);camera.updateMatrixWorld();
  for(let f=0;f<10;f++){t+=.05;ws.update(pouring,t);p.update(t,pouring,camera,{target:new THREE.Vector3(...pit)});post.wetReflections.update();}
  assert.equal(p.objects.rain.visible,true,'household pit close pose draws rain');
  assert.equal(p.objects.rain.geometry.instanceCount,8000);
  assert.ok(p.splashes.some(r=>r.lods.some(o=>o.visible)),'household pit close pose draws splashes');
  assert.equal(post.wetReflections.enabled,true,'household pit close pose keeps wet SSR active');
 }finally{
  post.dispose();p.dispose();ws.dispose();
  if(prevRic===undefined)delete globalThis.requestIdleCallback;else globalThis.requestIdleCallback=prevRic;
  if(prevCic===undefined)delete globalThis.cancelIdleCallback;else globalThis.cancelIdleCallback=prevCic;
 }
});
finish();
"""

SOURCE_DRIVER = CLOUD_DRIVER.split("await test('lazy CPU texels")[0] + r"""
const {createPrecipitation}=await import(file('static/twin/sky/precipitation.js'));
await test('actual r187 source assembly and keys: all kinds warmed at mount, stable programs, splash-only environment sampler, no shared lit changes',()=>{
 const scene=new THREE.Scene(),r=new Renderer(),p=createPrecipitation(scene,{tier:'max'}),eye=new THREE.PerspectiveCamera(),cache=programs(r),lights=makeLights();
 r.toneMapping=THREE.ACESFilmicToneMapping;
 const chunks={...THREE.ShaderChunk},std=new THREE.MeshStandardMaterial(),stdKey=std.customProgramCacheKey();
 for(const target of [null,new THREE.WebGLRenderTarget(8,8,{type:THREE.HalfFloatType})]){
  r.setRenderTarget(target);const keys=new Map();
  for(const o of Object.values(p.objects)){
   const s=programSource(r,cache,scene,o,lights);keys.set(o,s.key);const budget=uniformBudget(s[2]);
   assert.equal(budget.samplers.length,o.name.startsWith('weather-splash')?1:0);assert.ok(budget.vectors<24);
   if(o.name.startsWith('weather-splash')){
    assert.ok(s[2].includes('textureLod(splashEnvironment,reflect(-v,n),0.0)'));
    assert.ok(s[2].includes('splashFresnel(dot(n,v))')&&s[2].includes('splashSpecular(n,v,normalize(splashSunDirection))'));
    assert.deepEqual(uniformBudget(s[1]).samplers,['precipCover']);
   }assert.ok(s[1].includes('projectionMatrix'));assert.ok(s[2].includes('precipSafe'));
   assert.ok(!s[2].includes('#include'));console.log(o.name,'fragment vectors',budget.vectors);
  }
  assert.equal(new Set(keys.values()).size,2,'falling kinds share a program, splashes have their own');
  for(const precip of ['none','rain','snow','mix','hail'])for(const neutral of [true,false]){
   p.update(100,{precip,neutral,rate:1,windMps:20,windToDeg:270,fog:.7},eye,{colour:[.015,.02,.03]});
   for(const o of Object.values(p.objects))assert.equal(programSource(r,cache,scene,o,lights).key,keys.get(o));
  }
  for(const position of [[0,0,0],[5,40,10],[200,80,-100]]){
   eye.position.fromArray(position);p.update(101,{precip:'rain',rate:.45},eye,{target:new THREE.Vector3(10,0,-10)});
   for(const o of Object.values(p.objects))assert.equal(programSource(r,cache,scene,o,lights).key,keys.get(o),'focus/box changes are uniforms only');
  }
  target?.dispose();
 }
 assert.deepEqual(THREE.ShaderChunk,chunks);assert.equal(std.customProgramCacheKey(),stdKey);std.dispose();p.dispose();
});
finish();
"""

CAPTURE_DRIVER = REFLECTION_DRIVER.split("await test(")[0] + r"""
const {createPrecipitation}=await import(file('static/twin/sky/precipitation.js'));
await test('real probe/mirror passes hide precipitation and restore it after successful and failed captures',async()=>{
 const c=await setup('high'),p=createPrecipitation(c.scene,{tier:'high'}),camera=new THREE.PerspectiveCamera(60,16/9,.05,200);
 c.extra.push(p.group);p.update(0,{precip:'rain',rate:1},camera);
 let cube=0,mirror=0;
 c.renderer.inspect=()=>{cube++;assert.equal(p.group.visible,false);};
 c.round();assert.ok(cube>=6);assert.equal(p.group.visible,true);
 const pool=c.manager.info().probes.find(p=>p.id==='water:pool').centre;
 camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);camera.lookAt(new THREE.Vector3(...pool));camera.updateMatrixWorld();
 c.renderer.inspectMirror=()=>{mirror++;assert.equal(p.group.visible,false);};
 c.manager.mirror(camera);assert.ok(mirror>0);assert.equal(p.group.visible,true);
 c.renderer.fail=true;c.manager.request();c.round();assert.equal(p.group.visible,true);
 c.renderer.failMirror=true;c.manager.mirror(camera);assert.equal(p.group.visible,true);
 p.dispose();c.manager.dispose();
});
await test('real high-tier mount warms hidden precipitation materials for the composer, and excludes them from mirror',async()=>{
 location.search='?test=1';const original=globalThis.Renderer,loop=CaptureRenderer.prototype.setAnimationLoop;
 globalThis.Renderer=CaptureRenderer;CaptureRenderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
 const warm=[],compile=CaptureRenderer.prototype.compileAsync;
 CaptureRenderer.prototype.compileAsync=function(s,c){s.traverse(o=>{if(o.name?.startsWith('weather-')&&o.material)warm.push([o.name,this.target,o.visible]);});return Promise.resolve();};
 let v;try{
  v=await mountTwin(new Element(),{plan:fixture(),kit:kit(),tier:'high',bake:false});await Promise.resolve();
  assert.equal(new Set(warm.map(r=>r[0])).size,9);assert.ok(warm.every(r=>r[1]===v.post.target),'warm against the picture destination');
  v.setWeatherPreview('pouring');await new Promise(resolve=>setTimeout(resolve,0));v.render();
  assert.equal(v.precipitation.objects.rain.visible,true,'rain appears after asynchronous warmup releases the frame');
  const pool=v.reflectionInfo().probes.find(p=>p.id==='water:pool').centre;
  v.camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);v.controls.target.set(...pool);v.camera.lookAt(v.controls.target);v.camera.updateMatrixWorld();
  let draws=0;v.renderer3.inspectMirror=(s,c)=>{if(c===v.camera)return;draws++;assert.equal(v.precipitation.group.visible,false);};v.render();
  assert.ok(draws>0);assert.equal(v.precipitation.group.visible,true);assert.equal(v.precipitation.objects.rain.visible,true);
 }finally{v?.dispose();globalThis.Renderer=original;CaptureRenderer.prototype.setAnimationLoop=loop;if(compile)CaptureRenderer.prototype.compileAsync=compile;else delete CaptureRenderer.prototype.compileAsync;}
});
await test('neutral editor warms every precipitation program before a person selects Live weather',async()=>{
 location.search='?test=1';const original=globalThis.Renderer,compile=CaptureRenderer.prototype.compileAsync;
 globalThis.Renderer=CaptureRenderer;const warm=[];
 CaptureRenderer.prototype.compileAsync=function(s,c){s.traverse(o=>{if(o.name?.startsWith('weather-')&&o.material)warm.push(o.name);});return Promise.resolve();};
 let v;try{
  const el=new Element();el.closest=selector=>selector==='.editor-shell'?el:null;
  v=await mountTwin(el,{plan:fixture(),kit:kit(),tier:'high',bake:false});
  assert.equal(new Set(warm).size,9,'editor warms all hidden precipitation materials');
  assert.ok(Object.values(v.precipitation.objects).every(o=>!o.visible));
 }finally{v?.dispose();globalThis.Renderer=original;if(compile)CaptureRenderer.prototype.compileAsync=compile;else delete CaptureRenderer.prototype.compileAsync;}
});
finish();
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    plan = flatten(assemble(fixture)[0])
    failed = False
    for driver in [DRIVER, SOURCE_DRIVER, CAPTURE_DRIVER]:
        code, output = run_node(driver, {'root': ROOT.as_posix(), 'plan': plan}, timeout=180)
        print(output)
        failed |= bool(code)
    sys.exit(1 if failed else 0)
