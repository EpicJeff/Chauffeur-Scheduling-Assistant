"""Wet-ground SSR: actual Node lifecycle, household field and executed shader math."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node
from test_twin_weather_surface_js import PREFIX
from test_twin_reflection_probes_js import DRIVER as REFLECTION_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {createPost}=await import(file('static/twin/post.js'));
const {WetReflectionPass,SSR_MARCH_GLSL}=await import(file('static/twin/wet_reflections.js'));
const {createSkyCover,HEIGHT_NONE}=await import(file('static/twin/sky/sky_cover.js'));
const {createPrecipitation,collectHardSurfaces,bakeWetGroundField,bakeWetSurfaceField,createWetSurfaceBaker,createSplashSampler}=await import(file('static/twin/sky/precipitation.js'));
const {installWeatherSurface,WEATHER_GLSL}=await import(file('static/twin/sky/weather_surface.js'));
const {groundAt,inPolygon}=await import(file('static/twin/twin_ground.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const FT=.3048,close=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);
function setup(tier='high'){
 const scene=new THREE.Scene(),renderer=new Renderer(),camera=new THREE.PerspectiveCamera(60,1,.1,100);
 const material=new THREE.MeshStandardMaterial();scene.add(new THREE.Mesh(new THREE.PlaneGeometry(),material));
 const weather=installWeatherSurface(scene);weather.prepare();
 const p=createPrecipitation(scene,{tier}),post=createPost(renderer,scene,camera,{tier});
 post.setWetGround({weatherSurface:weather.uniforms.weatherSurface,...p.uniforms});
 return {scene,renderer,camera,material,weather,p,post,dispose(){post.dispose();p.dispose();weather.dispose();material.dispose();}};
}
await test('SSR is constructed only on high/max, in the correct place; dry submits no draw',()=>{
 for(const tier of ['low','medium','high','max']){
  const c=setup(tier);try{
   const pass=c.post.wetReflections,present=['high','max'].includes(tier);
   assert.equal(!!pass,present);const chain=c.post.info().passes;
   assert.equal(chain.includes('WetReflectionPass'),present);
   if(present){assert.equal(chain[chain.indexOf('GTAOPass')+1],'WetReflectionPass');assert.equal(pass.enabled,false);}
   const calls=[],draw=c.renderer.render;c.renderer.render=function(s,eye){calls.push(s.material?.name);return draw.call(this,s,eye);};
   c.post.render();assert.ok(!calls.some(n=>n?.startsWith('wet-reflections')));
   if(!present)continue;
   const key=c.material.customProgramCacheKey(),version=c.material.version;
   for(const [x,z] of [[1,0],[0,1],[0,0],[.01,0]]){
    c.weather.uniforms.weatherSurface.value.set(x,0,z,0);calls.length=0;c.post.render();
    assert.equal(pass.enabled,x>0||z>0);assert.equal(calls.filter(n=>n?.startsWith('wet-reflections')).length,pass.enabled?2:0);
    assert.equal(c.material.customProgramCacheKey(),key);assert.equal(c.material.version,version);
   }
   c.renderer.setPixelRatio(1.5);c.renderer.setSize(731,419);c.post.render();
   assert.equal(pass.target.width,Math.ceil(731*1.5*.5));assert.equal(pass.target.height,Math.ceil(419*1.5*.5));
   c.post.setSize(1920,1080,1);assert.equal(pass.target.width,960);assert.equal(pass.target.height,540);
   const ortho=new THREE.OrthographicCamera(-2,2,2,-2,.1,50);c.post.setCamera(ortho);c.post.render();
   assert.equal(pass.camera,ortho);assert.equal(pass.uniforms.ssrCamera.value.z,0);
   const resources=[pass.target,...pass.materials],freed=new Map();resources.forEach(r=>r.addEventListener('dispose',()=>freed.set(r,(freed.get(r)||0)+1)));
   c.post.dispose();c.post.dispose();resources.forEach(r=>assert.equal(freed.get(r),1));
  }finally{c.dispose();}
 }
});
await test('warm both programs on creation while dry, wait for readiness and restore target',async()=>{
 const r=new Renderer(),scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),warm=[],resolvers=[];
 const saved=new THREE.WebGLRenderTarget(2,2);r.setRenderTarget(saved);
 r.compileAsync=function(mesh){warm.push([mesh.material?.name,this.getRenderTarget()]);return new Promise(resolve=>resolvers.push(resolve));};
 const post=createPost(r,scene,camera),pass=post.wetReflections;
 try{
  assert.equal(r.getRenderTarget(),saved);assert.equal(pass.ready,false);assert.equal(pass.enabled,false);
  assert.deepEqual(warm.filter(([n])=>n?.startsWith('wet-reflections')).map(([n])=>n),['wet-reflections-march','wet-reflections-composite']);
  assert.equal(warm.find(([n])=>n==='wet-reflections-march')[1],pass.target);
  assert.equal(warm.find(([n])=>n==='wet-reflections-composite')[1],post.target);
  pass.uniforms.weatherSurface.value.x=1;pass.uniforms.wetGround.value=new THREE.Texture();pass.uniforms.wetEdge.value=new THREE.Texture();pass.update();
  const calls=[],draw=r.render;r.render=function(s,c){calls.push(s.material?.name);return draw.call(this,s,c);};
  post.render();assert.equal(calls.filter(n=>n?.startsWith('wet-reflections')).length,0);
  resolvers.forEach(resolve=>resolve());await Promise.resolve();await Promise.resolve();
  calls.length=0;post.render();assert.equal(pass.ready,true);assert.equal(calls.filter(n=>n?.startsWith('wet-reflections')).length,2);
  assert.equal(warm.filter(([n])=>n?.startsWith('wet-reflections')).length,2,'no first-wet-frame warm-up');
 }finally{post.dispose();saved.dispose();}
});
await test('RG household field preserves every cover texel and includes every hard surface',()=>{
 const cover=createSkyCover(input.plan),old=cover.heightField(),hard=collectHardSurfaces(input.plan),f=bakeWetGroundField(input.plan,cover);
 assert.equal(f.data.length,f.width*f.height*2);assert.ok(hard.length>0);
 const lookup=(x,z)=>{
  const i=Math.floor((x-f.bounds[0])/f.cell),j=Math.floor((z-f.bounds[1])/f.cell);
  return i<0||j<0||i>=f.width||j>=f.height?[HEIGHT_NONE,HEIGHT_NONE]:Array.from(f.data.slice((j*f.width+i)*2,(j*f.width+i)*2+2));
 };
 for(let j=0;j<f.height;j++)for(let i=0;i<f.width;i++){
  const x=f.bounds[0]+(i+.5)*f.cell,z=f.bounds[1]+(j+.5)*f.cell,top=cover.coverTop(x,z);
  close(f.data[(j*f.width+i)*2],Number.isFinite(top)?top-.002:HEIGHT_NONE);
 }
 for(let j=0;j<old.height;j++)for(let i=0;i<old.width;i++)
  assert.equal(lookup(old.bounds[0]+(i+.5)*old.cell,old.bounds[1]+(j+.5)*old.cell)[0],old.data[j*old.width+i]);
 for(const h of hard)for(const [x,y] of h.polygon){
  assert.ok(f.bounds[0]<=x*FT&&f.bounds[2]>=x*FT);assert.ok(f.bounds[1]<=-y*FT&&f.bounds[3]>=-y*FT);
 }
 const patio=input.plan.site.hardscape.find(h=>h.id==='site:8caf897d40f8465fbdd8bdf6051aaa5b');assert.ok(patio,'household pool-house patio');
 const sample=createSplashSampler(input.plan);
 let patioCount=0,lawn=0,water=0;
 for(let j=0;j<f.height;j++)for(let i=0;i<f.width;i++){
  const x=(f.bounds[0]+(i+.5)*f.cell)/FT,y=-(f.bounds[1]+(j+.5)*f.cell)/FT,g=f.data[(j*f.width+i)*2+1];
  if(inPolygon(input.plan.site.pool.polygon,x,y)){assert.equal(g,HEIGHT_NONE);water++;continue;}
  if(inPolygon(patio.polygon,x,y)){
   const hit=sample(x*FT,-y*FT);
   if(hit?.kind==='hardscape'){close(g,(groundAt(input.plan,x,y)+(patio.elevation||0)+.3)*FT);patioCount++;}
  }
  if(!hard.some(h=>inPolygon(h.polygon,x,y))){assert.equal(g,HEIGHT_NONE);lawn++;}
 }
 assert.ok(patioCount>10&&lawn>100&&water>100);console.log('RG_FIELD',f.width,f.height,{patioCount,lawn,water});
});
await test('field follows paver heights/pad edits; lawn gaps, beds and spa remain empty; lingering wetness rebakes',()=>{
 const plan={site:{terraces:[{polygon:[[-20,-20],[20,-20],[20,20],[-20,20]],height:3,blend:0}],
  hardscape:[{polygon:[[0,0],[10,0],[10,10],[0,10]]}],pool:{polygon:[[2,2],[4,2],[4,4],[2,4]],features:[{kind:'spa',polygon:[[6,6],[8,6],[8,8],[6,8]]}]}}};
 const c=createSkyCover(plan),f=bakeWetGroundField(plan,c),get=(x,y)=>{
  const i=Math.floor((x*FT-f.bounds[0])/f.cell),j=Math.floor((-y*FT-f.bounds[1])/f.cell);return f.data[(j*f.width+i)*2+1];
 };
 close(get(1,1),3.3*FT);assert.equal(get(3,3),HEIGHT_NONE);assert.equal(get(7,7),HEIGHT_NONE);
 const p=createPrecipitation(new THREE.Scene()),eye=new THREE.PerspectiveCamera();p.setPlan(plan,null,c);
 const old=p.uniforms.precipCover.value;p.update(0,{precip:'none',wetness:1,puddles:1},eye);
 const wet=p.uniforms.precipCover.value;assert.notEqual(wet,old);assert.equal(wet.format,THREE.RGFormat);assert.equal(wet.minFilter,THREE.NearestFilter);
 p.update(1,{wetness:1},eye);assert.equal(p.uniforms.precipCover.value,wet);
 p.setPlan(plan,null,c);p.update(2,{puddles:1},eye);assert.notEqual(p.uniforms.precipCover.value,wet,'plan refresh with retained cover invalidates ground too');p.dispose();
 const path={kind:'path',points:[[0,0],[0,20]],width:4,pavers:{layout:'stepping',length_in:24,width_in:24,gap_in:12,lay:'level',joint:'lawn'}};
 const hard=collectHardSurfaces({site:{hardscape:[path]}});assert.ok(hard.length>2);close(hard[0].elevation,1/12);
 const sampler=createSplashSampler({site:{hardscape:[path]}}),x=hard[0].polygon.reduce((s,p)=>s+p[0],0)/hard[0].polygon.length,y=hard[0].polygon.reduce((s,p)=>s+p[1],0)/hard[0].polygon.length;
 close(sampler(x*FT,-y*FT).position[1],FT/12+.006);assert.equal(sampler(1.8*FT,-y*FT),null);
 const stones=bakeWetGroundField({site:{hardscape:[path]}});let tops=0,gaps=0;
 for(let i=1;i<stones.data.length;i+=2){if(stones.data[i]===HEIGHT_NONE)gaps++;else{close(stones.data[i],FT/12);tops++;}}
 assert.ok(tops>5&&gaps>5,'the RG field retains the separate stepping stones and lawn joints');
});
const mix=(a,b,t)=>a+(b-a)*t,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const smoothstep=(a,b,v)=>{const t=clamp((v-a)/(b-a),0,1);return t*t*(3-2*t);};
const scalar=(source,name,dependencies={})=>{
 const m=source.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));assert.ok(m,name);
 const env={mix,clamp,smoothstep,max:Math.max,abs:Math.abs,...dependencies};
 return new Function(...Object.keys(env),`return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(...Object.values(env));
};
await test('actual GLSL mask: rejects lawn, roof, cover, wall and snow; matches film/puddle shapes',()=>{
 const c=setup();try{
  const film=scalar(WEATHER_GLSL,'weatherFilm'),puddle=scalar(WEATHER_GLSL,'weatherPuddle'),snow=scalar(WEATHER_GLSL,'weatherSnow');
  const mask=scalar(c.post.wetReflections.materials[0].fragmentShader,'ssrMask',{weatherFilm:film,weatherPuddle:puddle,weatherSnow:snow});
  const depthMatches=scalar(c.post.wetReflections.materials[0].fragmentShader,'ssrDepthMatches');
  close(depthMatches(10,10),1);close(depthMatches(10,9.5),0);close(depthMatches(10,10.5),0);
  assert.ok(c.post.wetReflections.materials.every(m=>m.fragmentShader.includes('!ssrVisible(vUv,depth)')));
  for(const camera of [new THREE.PerspectiveCamera(60,1,.1,100),new THREE.OrthographicCamera(-1,1,1,-1,.1,100)]){
   const linear=scalar(c.post.wetReflections.materials[0].fragmentShader,'ssrLinearDepth',{ssrCamera:{x:camera.near,y:camera.far,z:camera.isPerspectiveCamera?1:0}});
   for(const distance of [.1,1,10,99]){
    const clip=new THREE.Vector4(0,0,-distance,1).applyMatrix4(camera.projectionMatrix);close(linear((clip.z/clip.w+1)*.5),distance);
   }
  }
  for(const args of [[1,0,-1e4,-1e4,1,1,0,.3],[1,8,-1e4,0,1,1,0,.3],[1,0,4,0,1,1,0,.3],
   [0,0,-1e4,0,1,1,0,.3],[1,0,-1e4,0,1,1,1,.3]])close(mask(...args),0);
  close(mask(1,0,-1e4,0,1,0,0,.3),.45);close(mask(1,0,-1e4,0,1,1,0,.3),1);
  close(mask(1,0,-1e4,0,.2,1,0,.3),0);
  const fract=x=>x-Math.floor(x),hash=(x,y)=>fract(Math.sin(x*127.1+y*311.7)*43758.5453);
  const noise=(x,y)=>{const i=Math.floor(x),j=Math.floor(y),u=smoothstep(0,1,fract(x)),v=smoothstep(0,1,fract(y));return mix(mix(hash(i,j),hash(i+1,j),u),mix(hash(i,j+1),hash(i+1,j+1),u),v);};
  let strong=0,weak=0;
  for(let x=0;x<8;x+=.2)for(let z=0;z<8;z+=.2){
   const edge=noise(x*.35,z*.35)*.67+noise(x*.7+19.1,z*.7+7.7)*.33;
   const amount=mask(1,0,-1e4,0,1,.65,0,edge);close(amount,Math.max(.45,puddle(1,.65,edge)));
   if(amount>.9)strong++;if(amount===.45)weak++;
  }
  assert.ok(strong>50&&weak>50);assert.ok(c.post.wetReflections.materials.every(m=>m.fragmentShader.includes(WEATHER_GLSL)));
 }finally{c.dispose();}
});
await test('execute GLSL march with a synthetic wall/floor depth buffer, sky miss and camera-facing ray',()=>{
 const camera=new THREE.PerspectiveCamera(60,1,.1,100),projection=camera.projectionMatrix;
 const project=p=>{const c=new THREE.Vector4(p.x,p.y,p.z,1).applyMatrix4(projection);return new THREE.Vector2(c.x/c.w*.5+.5,c.y/c.w*.5+.5);};
 const origin=new THREE.Vector3(0,-.95,-3),direction=new THREE.Vector3(0,1,-3).normalize();
 let reads=0,wall=true,empty=false;
 const gap=(p,uv)=>{
  reads++;const ray=new THREE.Vector3(uv.x*2-1,uv.y*2-1,.5).applyMatrix4(camera.projectionMatrixInverse).normalize();
  let distance=100;
  if(!empty){
   if(ray.y<0)distance=Math.min(distance,-ray.z*(-1/ray.y));
   const point=ray.clone().multiplyScalar(-8/ray.z);
   if(wall&&Math.abs(point.x)<3&&point.y>=-1&&point.y<3)distance=Math.min(distance,8);
  }
  return -p.z-distance;
 };
 // Execute the shipped loop and branches. Only vector arithmetic/projection
 // and texture fetch syntax is adapted to THREE's CPU vectors/depth sampler.
 let body=SSR_MARCH_GLSL.split('vec3 ssrMarch(vec3 origin,vec3 direction) {')[1].split('\n}')[0];assert.ok(body);
 const edgeTest='any(lessThanEqual(uv,vec2(0.0)))||any(greaterThanEqual(uv,vec2(1.0)))';assert.ok(body.includes(edgeTest));
 body=body.replace(edgeTest,'uv.x<=0||uv.y<=0||uv.x>=1||uv.y>=1')
  .replaceAll('vec3(0.0)','new THREE.Vector3()').replace('vec3(uv,confidence)','new THREE.Vector3(uv.x,uv.y,confidence)')
  .replace(/origin\+direction\*(travel|middle|hi)/g,'origin.clone().addScaledVector(direction,$1)')
  .replace('ssrLinearDepth(texture2D(ssrDepth,uv).r)','-position.z-ssrGap(position,uv)')
  .replace(/\b(float|vec2|vec3|int)\s+/g,'let ');
 const march=new Function('THREE','ssrProject','ssrGap','ssrCamera','min','smoothstep',`return (origin,direction)=>{${body}}`)(THREE,project,gap,{y:100},Math.min,smoothstep);
 const hit=march(origin,direction);assert.ok(hit.z>.9,'on-screen wall receives a hit');close(hit.x,.5);assert.ok(hit.y>.5);
 assert.ok(reads<=29,'at most 24 march, four refine, one thickness read');console.log('WALL_HIT',hit.toArray(),reads);
 empty=true;assert.equal(march(origin,direction).z,0);empty=false;wall=false;assert.equal(march(origin,direction).z,0);
 reads=0;assert.equal(march(origin,new THREE.Vector3(0,0,1)).z,0);assert.equal(reads,0);
});
await test('mounted high-tier view shares weather and field references; raw capture draws no SSR',async()=>{
 location.search='?test=1';const v=await mountTwin(new Element(),{plan:structuredClone(input.plan),kit:{materials:{}},tier:'high',bake:false});
 try{
  const pass=v.post.wetReflections,u=pass.uniforms;
  assert.equal(u.weatherSurface,v.weatherSurface.uniforms.weatherSurface);assert.equal(u.wetGround,v.precipitation.uniforms.precipCover);
  assert.equal(u.wetGroundBounds,v.precipitation.uniforms.precipCoverBounds);
  v.setWeatherPreview('pouring');v.render();assert.equal(pass.enabled,true);assert.ok(u.wetGround.value.image.width>1);
  const count={value:0},render=pass.render;pass.render=function(...args){count.value++;return render.apply(this,args);};
  v.renderer3.render(v.scene,v.camera);assert.equal(count.value,0,'probes/cubes and planar mirrors render the scene directly');
  v.setUnlit(true);assert.equal(count.value,0);v.setUnlit(false);assert.ok(count.value>0);
  v.setWeatherPreview('clear');v.render();assert.equal(pass.enabled,false);
 }finally{v.dispose();}
});
await test('smooth bilinear wetEdge SDF fills curved walkways and follows rotated roof drip lines within 0.15 m',()=>{
 const sampleBilinear=(f,wx,wz)=>{
  const [x0,z0,x1,z1]=f.bounds,u=(wx-x0)/(x1-x0)*f.width-.5,v=(wz-z0)/(z1-z0)*f.height-.5;
  const i0=Math.max(0,Math.min(f.width-1,Math.floor(u))),j0=Math.max(0,Math.min(f.height-1,Math.floor(v)));
  const i1=Math.min(f.width-1,i0+1),j1=Math.min(f.height-1,j0+1),fx=Math.max(0,Math.min(1,u-i0)),fy=Math.max(0,Math.min(1,v-j0));
  return [0,1,2,3].map(c=>{
   const a=f.data[(j0*f.width+i0)*4+c],b=f.data[(j0*f.width+i1)*4+c],d=f.data[(j1*f.width+i0)*4+c],e=f.data[(j1*f.width+i1)*4+c];
   return (a+(b-a)*fx)*(1-fy)+(d+(e-d)*fx)*fy;
  });
 };
 // Curved 4 ft walkway (like the front walkway): reflection fills width without 0.3 m stair steps.
 const curved={site:{hardscape:[{id:'walk',kind:'path',width:4,smooth:true,points:[[0,0],[10,0],[18,4],[22,12],[22,22]]}]}};
 const hard=collectHardSurfaces(curved),cover=createSkyCover(curved),surf=bakeWetSurfaceField(curved,cover,hard);
 assert.equal(surf.data.length,surf.width*surf.height*4);
 let inside=0,missed=0,spilled=0;
 for(let x=-2;x<26;x+=.15)for(let y=-4;y<24;y+=.15){
  const onWalk=hard.some(h=>inPolygon(h.polygon,x,y)),s=sampleBilinear(surf,x*FT,-y*FT);
  const accepts=s[1]>=-.015&&Math.abs(.3*FT-s[3])<.15;
  if(onWalk){inside++;if(!accepts)missed++;}else if(s[1]>.015)spilled++;
 }
 assert.ok(inside>1000&&missed/inside<.02&&spilled===0,`curved walkway SSR fills width cleanly: missed=${missed}/${inside} spilled=${spilled}`);
 // Rotated roof edge over a paved walkway: drip line within 0.15 m everywhere.
 for(const rot of [357.6,20,45]){
  const p={buildings:[{id:'b',position:[10,10],rotation:rot,levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[20,0],[20,10],[0,10]]}],
   rooms:[],walls:[],roof:{sections:[{id:'r',kind:'gable',rect:[0,0,20,10],plate:10,pitch:4,overhang:2,ridge:'x'}]}}],
   site:{hardscape:[{id:'walk',kind:'path',points:[[4,6],[36,6]],width:6}]}};
  const c=createSkyCover(p),f=bakeWetSurfaceField(p,c);
  let maxErrM=0;
  for(let x=4;x<=36;x+=.25)for(let y=3;y<=9;y+=.25){
   const wx=x*FT,wz=-y*FT,wy=.3*FT,s=sampleBilinear(f,wx,wz);
   const ssrOpen=wy<s[2]?Math.max(0,Math.min(1,s[0]/.6)):1,exact=c.open(wx,wy,wz);
   maxErrM=Math.max(maxErrM,Math.abs(ssrOpen-exact)*.6);
  }
  assert.ok(maxErrM<.15,`SSR cover boundary within 0.15 m at rot=${rot}: ${maxErrM.toFixed(4)}m`);
 }
 // Incremental baker produces identical data to synchronous bakeWetSurfaceField.
 const baker=createWetSurfaceBaker(curved,cover,hard);let steps=0;
 while(!baker.step(0.05)&&steps<5000)steps++;
 assert.ok(baker.done&&steps>0,'incremental baker finishes in bounded slices');
 assert.deepEqual(baker.result.data,surf.data,'incremental baker matches synchronous bake bit-for-bit');
 // Live texture uses HalfFloatType + LinearFilter (always filterable in WebGL2);
 // missing precipEdge falls back to null (never reads 2-channel precipCover).
 const scene=new THREE.Scene(),eye=new THREE.PerspectiveCamera(),p=createPrecipitation(scene),post=createPost(new Renderer(),scene,eye);
 try{
  p.setPlan(curved,null,cover);p.update(0,{precip:'rain',rate:1,wetness:1,puddles:1},eye);
  const edgeTex=p.uniforms.precipEdge.value;
  assert.equal(edgeTex.format,THREE.RGBAFormat);assert.equal(edgeTex.type,THREE.HalfFloatType);
  assert.equal(edgeTex.minFilter,THREE.LinearFilter);assert.ok(edgeTex.image.data instanceof Uint16Array);
  post.wetReflections.bind({weatherSurface:{value:new THREE.Vector4(1,0,1,0)},precipCover:p.uniforms.precipCover,precipCoverBounds:p.uniforms.precipCoverBounds});
  assert.equal(post.wetReflections.uniforms.wetEdge.value,null,'missing precipEdge never falls back to 2-channel precipCover');
  assert.equal(post.wetReflections.enabled,false,'pass stays disabled when wetEdge is null');
 }finally{post.dispose();p.dispose();}
});
finish();
"""

CAPTURE_DRIVER = REFLECTION_DRIVER.split("await test(")[0] + r"""
const {createPost}=await import(file('static/twin/post.js'));
const {createPrecipitation}=await import(file('static/twin/sky/precipitation.js'));
await test('actual reflection probes and planar mirror never execute SSR, including capture failures',async()=>{
 const c=await setup('high'),camera=new THREE.PerspectiveCamera(60,16/9,.05,200),post=createPost(c.renderer,c.scene,camera),p=createPrecipitation(c.scene);
 post.setWetGround({weatherSurface:{value:new THREE.Vector4(1,0,1,0)},...p.uniforms});post.wetReflections.update();
 const calls=[],draw=c.renderer.render;
 c.renderer.render=function(s,c){if(s.material?.name?.startsWith('wet-reflections'))calls.push(s.material.name);return draw.call(this,s,c);};
 try{
  c.round();assert.ok(c.renderer.faces.length>=6);
  const pool=c.manager.info().probes.find(p=>p.id==='water:pool').centre;
  camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);camera.lookAt(new THREE.Vector3(...pool));camera.updateMatrixWorld();
  c.manager.mirror(camera);assert.ok(c.renderer.mirrors.length>0);
  c.renderer.fail=true;c.manager.request();c.round();c.renderer.failMirror=true;c.manager.mirror(camera);
  assert.equal(calls.length,0);assert.equal(post.wetReflections.enabled,true,'capture cannot mutate post state or shared weather');
 }finally{post.dispose();p.dispose();c.manager.dispose();}
});
finish();
"""

SOURCE_DRIVER = PREFIX + r"""
const {createPost}=await import(file('static/twin/post.js'));
const {createPrecipitation}=await import(file('static/twin/sky/precipitation.js'));
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
await test('r187 final post sources assemble; no lit uniform, sampler, chunk or program-key changes',()=>{
 const scene=new THREE.Scene(),r=new Renderer(),eye=new THREE.PerspectiveCamera(),std=new THREE.MeshStandardMaterial();
 const object=new THREE.Mesh(new THREE.PlaneGeometry(),std);scene.add(object);const weather=installWeatherSurface(scene);weather.prepare();
 r.toneMapping=THREE.ACESFilmicToneMapping;
 const cache=programs(r),lights=makeLights(),before=programSource(r,cache,scene,object,lights),chunks={...THREE.ShaderChunk};
 const p=createPrecipitation(scene),post=createPost(r,scene,eye),pass=post.wetReflections;
 post.setWetGround({weatherSurface:weather.uniforms.weatherSurface,...p.uniforms});
 try{
  for(const quad of [pass.gather,pass.composite]){
   const source=programSource(r,cache,scene,quad._mesh,lights);
   assert.ok(source[1]&&!source[2].includes('#include'));const budget=uniformBudget(source[2]);
   assert.ok(budget.samplers.length<=6);console.log(quad.material.name,budget);
  }
  for(const [wet,puddle] of [[0,0],[1,0],[0,1],[1,1],[0,0]]){
   weather.uniforms.weatherSurface.value.set(wet,0,puddle,0);post.render();
   const after=programSource(r,cache,scene,object,lights);
   assert.equal(after.key,before.key);assert.deepEqual(Object.keys(after.shader.uniforms),Object.keys(before.shader.uniforms));
   assert.deepEqual(uniformBudget(after[2]),uniformBudget(before[2]));assert.equal(after[2],before[2]);assert.deepEqual(THREE.ShaderChunk,chunks);
  }
 }finally{post.dispose();p.dispose();weather.dispose();std.dispose();}
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
