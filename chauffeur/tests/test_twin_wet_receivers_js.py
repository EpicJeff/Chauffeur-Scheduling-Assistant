"""Wet receivers over household + authored overlap/coping/cap/stair fixture; no GL."""
import json
import os
from pathlib import Path
import subprocess
import sys

from test_twin_tree_once_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
const P=await import(file('static/twin/sky/precipitation.js'));
const C=await import(file('static/twin/sky/wet_caps.js'));
const {createSkyCover,HEIGHT_NONE}=await import(file('static/twin/sky/sky_cover.js'));
const {poolDatum,inPolygon}=await import(file('static/twin/twin_ground.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
const {WetReflectionPass}=await import(file('static/twin/wet_reflections.js'));
const {buildPadEdge}=await import(file('static/twin/pad_edge_geometry.js'));
const {buildAtlas,atlasMesh}=await import(file('static/twin/bake/atlas.js'));
const FT=.3048,close=(a,b,e=.002)=>assert.ok(Math.abs(a-b)<e,`${a} != ${b}`);
const plan=input.cases;
function sample(f,x,y,channels=4){
 const u=(x*FT-f.bounds[0])/f.cell-.5,v=(-y*FT-f.bounds[1])/f.cell-.5;
 const i=Math.floor(u),j=Math.floor(v),a=u-i,b=v-j;
 const at=(i,j,k)=>f.data[(Math.max(0,Math.min(f.height-1,j))*f.width+Math.max(0,Math.min(f.width-1,i)))*channels+k];
 return Array.from({length:channels},(_,k)=>(at(i,j,k)*(1-a)+at(i+1,j,k)*a)*(1-b)+(at(i,j+1,k)*(1-a)+at(i+1,j+1,k)*a)*b);
}
const cover=createSkyCover(plan),field=P.bakeWetSurfaceField(plan,cover);
await test('curved paving over mulch receives across its width in both bakers; water remains excluded',()=>{
 const coarse=P.bakeWetGroundField(plan,cover),hard=P.collectHardSurfaces(plan).filter(h=>h.bounds[0]<15);
 let checked=0;
 for(let j=0;j<field.height;j++)for(let i=0;i<field.width;i++){
  const k=(j*field.width+i)*4,x=(field.bounds[0]+(i+.5)*field.cell)/FT,y=-(field.bounds[1]+(j+.5)*field.cell)/FT;
  if(hard.some(h=>inPolygon(h.polygon,x,y))){assert.ok(field.data[k+1]>=0);checked++;}
 }
 assert.ok(checked>100);
 for(const [x,y] of [[25,12],[44,18],[28,6]]) {assert.ok(sample(field,x,y)[1]<0);assert.equal(sample(coarse,x,y,2)[1],HEIGHT_NONE);}
 for(let j=0;j<coarse.height;j++)for(let i=0;i<coarse.width;i++){
  const x=(coarse.bounds[0]+(i+.5)*coarse.cell)/FT,y=-(coarse.bounds[1]+(j+.5)*coarse.cell)/FT;
  if(hard.some(h=>inPolygon(h.polygon,x,y)))close(coarse.data[(j*coarse.width+i)*2+1],.3*FT);
 }
 const raised=structuredClone(plan);raised.site.beds[0].elevation=1;
 const high=P.bakeWetSurfaceField(raised),low=P.bakeWetGroundField(raised);
 assert.ok(sample(high,6,12)[1]<0);assert.equal(sample(low,6,12,2)[1],HEIGHT_NONE);
});
await test('pool and raised/flush spa coping carry their own heights, shared flush edges stay empty',()=>{
 const h=poolDatum(plan,plan.site.pool);
 for(const [x,y,top] of [[23.5,12,h+.45],[44,21.5,h+.45+1.5],[31.5,6,h+.45]]){
  const c=sample(field.caps,x,y,2);assert.ok(c[0]>0,`${x},${y}: ${c}`);close(c[1],top*FT);
 }
 assert.ok(sample(field.caps,24.5,6,2)[0]<0,'flush shared side has no extra coping');
 assert.ok(sample(field.caps,36,12,2)[0]<0,'pool water is no cap');
});
await test('seat-wall caps and exposed stair treads match the actual emit path; no internal prism seams',()=>{
 const tops=[];for(let i=0;i<4;i++)buildPadEdge(plan,plan.site.terraces[0],i,g=>g.dispose(),(polygon,top)=>tops.push({polygon,top}));
 let wall=0,stair=0;
 for(const t of tops){
  const [x,y]=t.polygon.reduce((s,p)=>[s[0]+p[0]/t.polygon.length,s[1]+p[1]/t.polygon.length],[0,0]);
  const c=sample(field.caps,x,y,2);assert.ok(c[0]>0,JSON.stringify({t,c}));close(c[1],t.top*FT);
  if(t.top>4)wall++;else stair++;
 }
 assert.ok(wall>5&&stair>1);
 for(let x=60.5;x<69.5;x+=.25)assert.ok(sample(field.caps,x,.3,2)[0]>0,'no cap segment seam');
 assert.ok(field.bounds[2]>70*FT,'caps outside paving extend the shared bounds');
});
await test('execute production GLSL receiver gates: caps, deck seam, vertical face, snow, dry and drip line',()=>{
 const pass=new WetReflectionPass(new THREE.PerspectiveCamera(),{depthTexture:null,normalTexture:null}),src=pass.materials[0].fragmentShader;
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x)),smoothstep=(a,b,x)=>{const t=clamp((x-a)/(b-a),0,1);return t*t*(3-2*t);};
 const scalar=(name,env={})=>{const m=src.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));assert.ok(m,name);
  const args={clamp,smoothstep,abs:Math.abs,max:Math.max,...env};return new Function(...Object.keys(args),`return (${m[1].replace(/float /g,'')})=>{${m[2].replace(/\bfloat\b/g,'let')}}`)(...Object.values(args));};
 const hard=scalar('ssrHardWeight'),open=scalar('ssrOpen'),film=scalar('weatherFilm'),puddle=scalar('weatherPuddle'),snow=scalar('weatherSnow');
 const mask=scalar('ssrMask',{weatherFilm:film,weatherPuddle:puddle,weatherSnow:snow});
 // Execute ssrReceiver itself: translate only GLSL vector/texture operations.
 // All branches, tolerances, cap/deck OR, cover and weather maths stay verbatim.
 const body=src.match(/float ssrReceiver\([^)]*\) \{([\s\S]*?)\n\}/)[1]
  .replace('vec3 world=(ssrWorld*vec4(position,1.0)).xyz;','let world=position;')
  .replace('float up=(mat3(ssrWorld)*normal).y;','let up=normal.y;')
  .replace('vec2 uv=(world.xz-wetGroundBounds.xy)/max(wetGroundBounds.zw-wetGroundBounds.xy,vec2(.0001));','let uv={x:world.x,z:world.z};')
  .replace('any(lessThan(uv,vec2(0.0)))||any(greaterThanEqual(uv,vec2(1.0)))','world.x<bounds[0]||world.z<bounds[1]||world.x>=bounds[2]||world.z>=bounds[3]')
  .replace('texture2D(wetCaps,uv).rg','texture2D(wetCaps,uv)')
  .replace('weatherEdge(world.xz)','.3').replace(/\b(float|vec2|vec4)\s+/g,'let ');
 const makeReceiver=(f,weather={x:1,y:0,z:1})=>new Function('ssrHardWeight','ssrOpen','ssrMask','weatherPuddle','texture2D','wetEdge','wetCaps','bounds','weatherSurface',
  `return (position,normal)=>{let ssrPuddle;${body}}`)(hard,open,mask,puddle,(which,p)=>{
   const a=sample(which==='edge'?f:f.caps,p.x/FT,-p.z/FT,which==='edge'?4:2);
   return which==='edge'?{r:a[0],g:a[1],b:a[2],a:a[3]}:{r:a[0],g:a[1]};
  },'edge','caps',f.bounds,weather);
 const receiver=makeReceiver(field);
 for(const [x,y] of [[23.5,12],[65,.3],[44,21.5]]){
  const c=sample(field.caps,x,y,2),f=sample(field,x,y),h=c[1];
  assert.equal(hard(h,f[1],f[3],c[0],c[1]),1);assert.ok(mask(1,h,-1e4,h,1,1,0,.3)>0);
  const world={x:x*FT,y:h,z:-y*FT};assert.ok(receiver(world,{y:1})>0);assert.equal(receiver(world,{y:0}),0);
  assert.equal(makeReceiver(field,{x:0,y:0,z:0})(world,{y:1}),0);assert.equal(makeReceiver(field,{x:1,y:1,z:1})(world,{y:1}),0);
  assert.equal(mask(0,h,-1e4,h,1,1,0,.3),0);assert.equal(mask(1,h,-1e4,h,1,1,1,.3),0);assert.equal(mask(1,h,-1e4,h,0,0,0,.3),0);
 }
 const noCaps=P.bakeWetSurfaceField(plan,cover,P.collectHardSurfaces(plan),{caps:[]});
 for(const [x,y] of [[22,12],[50,12],[65,1.5]]) {const f=sample(field,x,y),old=sample(noCaps,x,y);close(f[3],old[3]);close(hard(f[3],f[1],f[3],...sample(field.caps,x,y,2)),hard(old[3],old[1],old[3],-1,HEIGHT_NONE));}
 for(const r of [.00001,.01,.1,.59,.8])assert.equal(open(0,r,4),1);
 assert.equal(open(0,-.01,4),0);assert.equal(open(5,-.5,4),1);
 const eave={buildings:[{id:'b',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:12,outline:[[0,0],[20,0],[20,10],[0,10]]}],walls:[],rooms:[],
  roof:{sections:[{id:'r',kind:'gable',rect:[0,0,20,10],plate:12,pitch:4,overhang:2,ridge:'x'}]}}],site:{hardscape:[{polygon:[[-5,-6],[25,-6],[25,0],[-5,0]]}]}};
 const ef=P.bakeWetSurfaceField(eave),er=makeReceiver(ef);
 for(const feet of [.4,.8,1.2,1.6]){
  const y=-2-feet,f=sample(ef,10,y);assert.ok(f[0]>0&&f[0]<.6,'within the former outside fade');
  close(er({x:10*FT,y:.3*FT,z:-y*FT},{y:1}),1);
 }
 assert.equal(er({x:10*FT,y:.3*FT,z:1.6*FT},{y:1}),0,'under the eave stays sheltered');
 const capOnly=structuredClone(eave);capOnly.site={pool:{polygon:[[8,-3],[14,-3],[14,3],[8,3]],coping:1}};
 const cf=P.bakeWetSurfaceField(capOnly),cr=makeReceiver(cf),top=(poolDatum(capOnly,capOnly.site.pool)+.45)*FT;
 assert.ok(sample(cf,14.5,1)[0]<0,'cover was baked beside a cap without any hardscape');
 assert.equal(cr({x:14.5*FT,y:top,z:-FT},{y:1}),0,'covered cap stays dry');
 assert.ok(cr({x:10*FT,y:top,z:3.5*FT},{y:1})>0,'cap beyond drip line reflects without hardscape');
 pass.dispose();
});
await test('household and spa coping use solid weather; basin stays submerged; water stays water',async()=>{
 for(const p of [input.plan,plan]){
  const scene=new THREE.Scene(),yard=await buildYard(p,input.kit,'low',{viewing:false});scene.add(yard.group);
  const weather=installWeatherSurface(scene);weather.prepare();let coping=0,inside=0,water=0;
  yard.group.traverse(o=>{if(!o.isMesh)return;const key=o.material.customProgramCacheKey();
   const ranges=o.userData.snapRanges||[o.userData];
   if(ranges.some(r=>r.bakePart==='coping'&&['pool','spa'].includes(r.kind))){assert.ok(key.includes('weather-surface-solid-1'),key);assert.ok(!o.material.userData.underwater);coping++;}
   if(ranges.some(r=>r.kind==='ledge'))assert.ok(key.includes('weather-surface-submerged-1'),'underwater ledge top stays submerged, even with a coping finish');
   if(o.material.userData.underwater){assert.ok(key.includes('weather-surface-submerged-1'));inside++;}
   if(o.material.userData.waterSurface){assert.ok(key.includes('weather-surface-water-1'));water++;}
 });assert.ok(coping&&inside&&water,`${coping}/${inside}/${water}`);
 // Atlas binding must still reach the drawn coping after its material changes.
 const root=new THREE.Group();scene.add(root);root.add(yard.group);root.updateMatrixWorld(true);
 const atlas=buildAtlas(root,p,{room:{density:1,page:1024,gutter:2}});let bound=0;
 yard.group.traverse(o=>{if(!o.isMesh||!atlasMesh(o))return;const attr=o.geometry.attributes.lmRoom;
  for(const r of o.userData.snapRanges||[])if(r.bakePart==='coping')for(let i=r.start;i<r.start+r.count;i+=3){
   const pos=o.geometry.attributes.position,A=new THREE.Vector3().fromBufferAttribute(pos,i),B=new THREE.Vector3().fromBufferAttribute(pos,i+1),D=new THREE.Vector3().fromBufferAttribute(pos,i+2);
   if(new THREE.Triangle(A,B,D).getArea()<1e-9)continue;assert.ok(attr.getX(i)>=0,'coping face has a lightmap');bound++;
  }
 });assert.ok(bound>0);weather.dispose();
 }
});
await test('idle cap bake is identical to synchronous bake; texture binding, plan replacement and disposal',()=>{
 const b=P.createWetSurfaceBaker(plan,cover);let steps=0;while(!b.step(0)){assert.ok(++steps<10000);}assert.ok(steps>5);
 assert.deepEqual(b.result.data,field.data);assert.deepEqual(b.result.caps.data,field.caps.data);
 const p=P.createPrecipitation(new THREE.Scene()),eye=new THREE.PerspectiveCamera();p.setPlan(plan);p.update(0,{wetness:1},eye);
 const tex=p.uniforms.precipCaps.value;assert.equal(tex.format,THREE.RGFormat);assert.equal(tex.type,THREE.HalfFloatType);assert.equal(tex.minFilter,THREE.LinearFilter);
 const pass=new WetReflectionPass(eye,{depthTexture:null,normalTexture:null});pass.bind({weatherSurface:{value:new THREE.Vector4()},...p.uniforms});
 assert.equal(pass.uniforms.wetCaps,p.uniforms.precipCaps);
 let oldDisposed=0,newDisposed=0;tex.addEventListener('dispose',()=>oldDisposed++);
 p.setPlan(plan);assert.equal(oldDisposed,1);assert.equal(p.uniforms.precipCaps.value,null);p.update(1,{puddles:1},eye);
 const next=p.uniforms.precipCaps.value;assert.notEqual(next,tex);next.addEventListener('dispose',()=>newDisposed++);p.dispose();p.dispose();assert.equal(newDisposed,1);pass.dispose();
});
await test('cap dilation keeps each top and chooses the nearest top in the gap',()=>{
 const rect=(a,b)=>[[a,0],[b,0],[b,3],[a,3]];
 const caps=[{polygon:rect(0,1),bounds:[0,0,1,3],top:2},{polygon:rect(2,3),bounds:[2,0,3,3],top:5}];
 const f=C.createCapBaker(caps,{width:16,height:12,bounds:[-.3,-1.2,2.1,.6]}).finish();
 for(let j=0;j<f.height;j++)for(let i=0;i<f.width;i++){
  const x=(f.bounds[0]+(i+.5)*f.cell)/FT,y=-(f.bounds[1]+(j+.5)*f.cell)/FT,k=(j*f.width+i)*2;
  if(y<.3||y>2.7)continue;
  if(x>0&&x<1){assert.ok(f.data[k]>0);close(f.data[k+1],2*FT);}
  if(x>2&&x<3){assert.ok(f.data[k]>0);close(f.data[k+1],5*FT);}
  if(x>1&&x<2){assert.ok(f.data[k]<0);close(f.data[k+1],(x<1.5?2:5)*FT);}
 }
});
await test('actual idle callback bakes and replaces the cap texture; cancellation cannot upload an old plan',()=>{
 const request=globalThis.requestIdleCallback,cancel=globalThis.cancelIdleCallback,queue=new Map();let id=0;
 globalThis.requestIdleCallback=fn=>{queue.set(++id,fn);return id;};globalThis.cancelIdleCallback=id=>queue.delete(id);
 const p=P.createPrecipitation(new THREE.Scene());
 try {
  p.setPlan(plan);assert.equal(queue.size,1);
  p.setPlan(input.plan);assert.equal(queue.size,1,'old callback cancelled');
  let steps=0;while(queue.size){const [id,fn]=queue.entries().next().value;queue.delete(id);fn({timeRemaining:()=>1});assert.ok(++steps<10000);}
  assert.ok(steps>1);const expected=P.bakeWetSurfaceField(input.plan);
  assert.deepEqual(Array.from(p.uniforms.precipCaps.value.image.data),Array.from(expected.caps.data,THREE.DataUtils.toHalfFloat));
  p.setPlan(plan);assert.equal(queue.size,1);p.dispose();assert.equal(queue.size,0);
 }finally{p.dispose();globalThis.requestIdleCallback=request;globalThis.cancelIdleCallback=cancel;}
});
await test('drawn pool/spa/pad triangle attributes match main across the intentional material split',async()=>{
 const source=input.baselineYard.replace(/(from\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>a+new URL(s,file('static/twin/twin_yard.js')).href+b);
 const old=await import('data:text/javascript,'+encodeURIComponent(source));
 const current=await buildYard(plan,input.kit,'low'),previous=await old.buildYard(plan,input.kit,'low');
 const triangles=yard=>{yard.group.updateMatrixWorld(true);const faces=[];
  yard.group.traverse(o=>{if(!o.isMesh||o.isInstancedMesh)return;const g=o.geometry.index?o.geometry.toNonIndexed():o.geometry;
   for(let i=0;i<g.attributes.position.count;i+=3){const face=[];for(let k=i;k<i+3;k++){
    const pos=new THREE.Vector3().fromBufferAttribute(g.attributes.position,k).applyMatrix4(o.matrixWorld);
    face.push([...pos.toArray(),...['normal','uv','weatherOpen'].flatMap(name=>{const a=g.attributes[name];return a?Array.from({length:a.itemSize},(_,j)=>a.getComponent(k,j)):[];})]);
   }faces.push(JSON.stringify(face));}
   if(g!==o.geometry)g.dispose();
  });return faces.sort();};
 assert.deepEqual(triangles(current),triangles(previous));
});
await test('measured household bake time and owned buffer/texture bytes, against main bed exclusion',async()=>{
 const base=input.baseline.replace(/(from\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>a+new URL(s,file('static/twin/sky/precipitation.js')).href+b);
 const old=await import('data:text/javascript,'+encodeURIComponent(base));
 const c=createSkyCover(input.plan),hard=P.collectHardSurfaces(input.plan),caps=C.collectCapSurfaces(input.plan),f=P.bakeWetSurfaceField(input.plan,c,hard,{caps});
 const median=fn=>{const times=[];for(let i=0;i<23;i++){const start=performance.now();fn();if(i>=5)times.push(performance.now()-start);}return times.sort((a,b)=>a-b)[Math.floor(times.length/2)];};
 const oldField=old.bakeWetSurfaceField(input.plan,c,hard);
 const bedField=P.bakeWetSurfaceField(input.plan,c,hard,{caps:[]});
 let recovered=0;for(let i=1;i<bedField.data.length;i+=4)if(oldField.data[i]<=0&&bedField.data[i]>0)recovered++;
 const caseCaps=C.collectCapSurfaces(plan);
 const stats={dimensions:[f.width,f.height],capSurfaces:caps.length,recoveredBedCells:recovered,
  mainGroundMs:median(()=>old.bakeWetGroundField(input.plan,c,hard)),groundMs:median(()=>P.bakeWetGroundField(input.plan,c,hard,[])),
  mainEdgeMs:median(()=>old.bakeWetSurfaceField(input.plan,c,hard)),bedOnlyEdgeMs:median(()=>P.bakeWetSurfaceField(input.plan,c,hard,{caps:[]})),
  capsCollectMs:median(()=>C.collectCapSurfaces(input.plan)),capsRasterMs:median(()=>C.createCapBaker(caps,f).finish()),
  capsPackMs:median(()=>{const h=new Uint16Array(f.caps.data.length);for(let i=0;i<h.length;i++)h[i]=THREE.DataUtils.toHalfFloat(f.caps.data[i]);}),
  fullEdgeMs:median(()=>P.bakeWetSurfaceField(input.plan,c,hard)),capsFloatBytes:f.caps.data.byteLength,capsHalfBytes:f.caps.data.length*2,
  mainEdgeBytes:old.bakeWetSurfaceField(input.plan,c,hard).data.byteLength,edgeBytes:f.data.byteLength,
  caseDimensions:[field.width,field.height],caseCapSurfaces:caseCaps.length,caseCapsHalfBytes:field.caps.data.length*2,
  caseCapsCollectMs:median(()=>C.collectCapSurfaces(plan)),caseCapsRasterMs:median(()=>C.createCapBaker(caseCaps,field).finish())};
 console.log('WET_COST '+JSON.stringify(stats));
 assert.ok(caps.length>0&&stats.capsHalfBytes===f.width*f.height*4);
});
finish();
"""

if __name__ == '__main__':
    os.environ.pop('HA_BASE_URL', None)
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    baseline = subprocess.check_output(['git', 'show', 'main:chauffeur/static/twin/sky/precipitation.js'], cwd=ROOT, encoding='utf-8')
    baseline_yard = subprocess.check_output(['git', 'show', 'main:chauffeur/static/twin/twin_yard.js'], cwd=ROOT, encoding='utf-8')
    driver = DRIVER
    if '--cost-only' in sys.argv:
        driver = driver.replace('async function test(name, fn) {', "async function test(name, fn) {\n  if (!name.startsWith('measured')) return;")
    code, output = run_node(driver, {'root': ROOT.as_posix(), 'plan': flatten(assemble(fixture)[0]), 'kit': kit,
        'cases': json.loads((ROOT / 'tests/fixtures/twin_model/wet-receivers.json').read_text(encoding='utf-8')), 'baseline': baseline,
        'baselineYard': baseline_yard}, timeout=240)
    print(output)
    sys.exit(code or 0)
