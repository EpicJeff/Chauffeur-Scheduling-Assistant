"""Open-sky regression: generated household geometry, scalar shaders and editor paths."""
import json
from pathlib import Path
import sys

from test_twin_weather_surface_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const {existsSync}=await import('node:fs');
assert.ok(existsSync(new URL(file('static/twin/sky/sky_cover.js'))),'open-to-sky cover model exists');
const {createSkyCover,writeWeatherOpen}=await import(file('static/twin/sky/sky_cover.js'));
const {installWeatherSurface,WEATHER_GLSL}=await import(file('static/twin/sky/weather_surface.js'));
const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));
const {mergeStatic}=await import(file('static/twin/twin_generator.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {createPrecipitation,createSplashSampler}=await import(file('static/twin/sky/precipitation.js'));
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
window.location={href:'http://house.test/house/editor'};
const FT=.3048,close=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);
const plan={buildings:[{id:'b',position:[10,20],rotation:30,levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[10,0],[10,10],[0,10]]}],
 rooms:[],walls:[],roof:{sections:[{id:'r',kind:'gable',rect:[0,0,10,10],plate:10,pitch:4,overhang:2,ridge:'x'}]}}]};
const world=(x,y,z)=>{const a=Math.PI/6;return [(10+x*Math.cos(a)-y*Math.sin(a))*FT,z*FT,-(20+x*Math.sin(a)+y*Math.cos(a))*FT];};
await test('rotated real roof overhang, .6 metre edge, indoor volume and upward roof faces',()=>{
 const cover=createSkyCover(plan);
 close(cover.open(...world(5,5,1)),0);close(cover.open(...world(-1,5,0)),0);
 close(cover.open(...world(-2-.3/FT,5,0)),.5);close(cover.open(...world(-2-.6/FT,5,0)),1);
 close(cover.open(...world(5,5,30)),1);
 const roof=cover.roofHeight(...world(5,5,0));assert.ok(roof>10*FT);
 close(cover.open(world(5,5,0)[0],roof,world(5,5,0)[2],true),1);
 assert.equal(cover.blocked(...world(5,5,1)),true);assert.equal(cover.blocked(...world(5,5,30)),false);
});
await test('attribute survives merge, visibility collapse/restore, transforms and instance ownership',()=>{
 const cover=createSkyCover(plan),root=new THREE.Group(),mat=new THREE.MeshStandardMaterial(),shared=new THREE.BoxGeometry(.1,.1,.1);
 for(const [i,point] of [world(5,5,1),world(30,30,1)].entries()){
  const o=new THREE.Mesh(shared,mat);o.position.fromArray(point);o.userData.pieceId='p'+i;root.add(o);
 }
 writeWeatherOpen(root,cover);mergeStatic(root);
 const o=root.children[0],a=o.geometry.attributes.weatherOpen;assert.ok(a);
 const before=Array.from(a.array);assert.ok(before.includes(0)&&before.includes(1));
 const vis=createPieceVisibility();vis.set(['p0'],[]);vis.apply(root);assert.deepEqual(Array.from(a.array),before);
 vis.restore();assert.deepEqual(Array.from(a.array),before);
 const g=new THREE.BoxGeometry(.1,.1,.1),inst=new THREE.InstancedMesh(g,mat,2);
 inst.setMatrixAt(0,new THREE.Matrix4().makeTranslation(...world(5,5,1)));
 inst.setMatrixAt(1,new THREE.Matrix4().makeTranslation(...world(30,30,1)));root.add(inst);writeWeatherOpen(inst,cover);
 assert.ok(inst.geometry.attributes.weatherOpen.isInstancedBufferAttribute);
 assert.deepEqual(Array.from(inst.geometry.attributes.weatherOpen.array),[0,1]);
});
await test('actual upper slab triangles cover outside the footprint, with an open deck beside them',()=>{
 const p={buildings:[{id:'b',levels:[{id:'L1',elevation:0,ceiling:8,outline:[[0,0],[2,0],[2,2],[0,2]]}],walls:[],rooms:[]}]};
 const cover=createSkyCover(p,new Map([['b',{coverPositions:[],slabPositions:[10,0,10,20,0,10,10,10,10]}]]));
 close(cover.open(12*FT,2*FT,-2*FT),0);close(cover.open(25*FT,2*FT,-2*FT),1);close(cover.open(12*FT,11*FT,-2*FT),1);
 close(cover.open(NaN,0,0),0);
 const surface={coverPositions:[],slabPositions:[10,0,10,20,0,10,10,10,10]},roofs=new Map([['b',surface]]);
 const object=new THREE.Mesh(new THREE.BoxGeometry(.05,.05,.05),new THREE.MeshStandardMaterial());object.position.set(12*FT,2*FT,-2*FT);
 const before=createSkyCover(p,roofs);writeWeatherOpen(object,before);const attribute=object.geometry.attributes.weatherOpen;
 assert.ok(attribute.array.every(v=>v===0));
 surface.slabPositions=[30,0,10,40,0,10,30,10,10];const after=createSkyCover(p,roofs);
 assert.equal(after.staticKey,before.staticKey,'moving only a slab retains the static roof cache');
 writeWeatherOpen(object,after);assert.equal(object.geometry.attributes.weatherOpen,attribute);
 assert.ok(attribute.array.every(v=>v===1),'a moved slab uncovers an unchanged receiver through the cache');
});
await test('household floors, rugs, sofa, stairs, walls and porch are dry; deck, lawn and roof open',async()=>{
 const {rememberImport}=await import(file('static/twin/twin_library.js'));
 const poolHouse=input.plan.buildings.find(b=>b.id==='pool-house'),room=poolHouse.rooms.find(r=>r.kind!=='porch'&&r.state!=='ghost');
 const asset='import-'+'a'.repeat(32),vertices=new Float32Array([-.3,0,-.2,.3,0,-.2,0,.4,.2]);
 const doc={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],meshes:[{primitives:[{attributes:{POSITION:0}}]}],
  buffers:[{uri:'mesh.bin',byteLength:36}],
  bufferViews:[{buffer:0,byteOffset:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[-.3,0,-.2],max:[.3,.4,.2]}]};
 rememberImport({id:asset,model:'model.gltf',files:{'model.gltf':true,'mesh.bin':true}});
 const previousFetch=globalThis.fetch;globalThis.ProgressEvent=class {constructor(type,values){this.type=type;Object.assign(this,values);}};
 globalThis.fetch=async request=>{const url=String(typeof request==='string'?request:request.url);
  return url.includes('/'+asset+'/')?new Response(url.includes('mesh.bin')?Buffer.from(vertices.buffer):JSON.stringify(doc),{status:200}):previousFetch(request);
 };
 poolHouse.items=[{id:'sky-sofa',asset,host:{floor:room.id,u:.45,v:.45}},{id:'sky-rug',asset,host:{floor:room.id,u:.55,v:.55},scale_axes:[1,.01,1]}];
 const twin=buildTwin(input.plan,input.kit,'high',{viewing:true});await twin.ready;
 globalThis.fetch=previousFetch;
 for(const id of ['sky-sofa','sky-rug']){
  const objects=twin.pieces.get('pool-house:'+id);assert.ok(objects?.length,`real imported ${id} rendered`);
  let samples=0;for(const o of objects)for(const r of o.userData.snapRanges||[{start:0,count:o.geometry.attributes.position.count,pieceId:id}])
   if(r.pieceId===id)for(let i=r.start;i<r.start+r.count;i++){close(o.geometry.attributes.weatherOpen.getX(i),0);samples++;}
  assert.ok(samples>0);
 }
 const yard=await buildYard(input.plan,input.kit,'low',{skyCover:twin.skyCover});
 const porch=poolHouse.rooms.find(r=>r.kind==='porch');assert.ok(porch);
 assert.ok(twin.skyCover);let indoor=0,roofs=0,openYard=0,openDeck=0,openLawn=0;const evidence={};
 twin.root.updateMatrixWorld(true);
 twin.root.traverse(o=>{
  if(!o.isMesh||o.layers.isEnabled(31)||!o.geometry.attributes.position)return;
  const attr=o.geometry.attributes.weatherOpen;assert.ok(attr,`attribute on ${o.name}/${o.material?.name}`);
  const pos=o.geometry.attributes.position,norm=o.geometry.attributes.normal;
  for(const r of o.userData.snapRanges||[{start:0,count:pos.count,...o.userData}]){
   let zero=0,one=0;
   for(let i=r.start;i<r.start+r.count;i++){
    const p=new THREE.Vector3().fromBufferAttribute(pos,i).applyMatrix4(o.matrixWorld),v=attr.getX(i);
    assert.ok(Number.isFinite(v)&&v>=0&&v<=1);if(v===0)zero++;if(v===1)one++;
    if(r.buildingId==='pool-house'&&r.kind==='room'&&r.pieceId===porch.id)close(v,0);
    if(twin.skyCover.interior(p.x,p.y,p.z)&&r.kind!=='roof'){close(v,0);indoor++;}
    if(r.kind==='roof'&&norm?.getY(i)>.55&&v===1)roofs++;
   }
   if(zero)evidence[`${r.buildingId}:${r.kind}:${r.pieceId}:${r.part||''}`]=zero;
  }
 });
 yard.group.traverse(o=>{if(o.isMesh){const a=o.geometry.attributes.weatherOpen;assert.ok(a);for(let i=0;i<a.count;i++){
  const v=a.getX(i);assert.ok(Number.isFinite(v)&&v>=0&&v<=1);if(v===1){openYard++;
   if(['lawn','terrain_lawn'].includes(o.material?.name))openLawn++;
   if((o.userData.snapRanges||[]).some(r=>r.kind==='hardscape'&&i>=r.start&&i<r.start+r.count))openDeck++;
  }
 }}});
 assert.ok(indoor>100);assert.ok(roofs>10);assert.ok(openYard>100);
 assert.ok(openDeck>0,'open household paving receives weather');assert.ok(openLawn>0,'open lawn receives weather');
 assert.ok(Object.keys(evidence).some(k=>k.startsWith('pool-house:stair:')));
 assert.ok(Object.keys(evidence).some(k=>k.startsWith('pool-house:room:'+porch.id)));
 const {heightAt}=await import(file('static/twin/twin_roof.js'));
 const {buildingBase,buildingFootprint,inPolygon}=await import(file('static/twin/twin_ground.js'));
 let extensionSamples=0;
 for(const b of input.plan.buildings){const p=twin.roofSurfaces.get(b.id).coverPositions,angle=(b.rotation||0)*Math.PI/180;
  for(let i=0;i<p.length;i+=9){const x=(p[i]+p[i+3]+p[i+6])/3,y=(p[i+1]+p[i+4]+p[i+7])/3,h=(p[i+2]+p[i+5]+p[i+8])/3;
   if(heightAt(b.roof.sections,x,y)!==null||inPolygon(buildingFootprint(b),x,y))continue;
   const wx=((b.position?.[0]||0)+x*Math.cos(angle)-y*Math.sin(angle))*FT,wz=-((b.position?.[1]||0)+x*Math.sin(angle)+y*Math.cos(angle))*FT;
   close(twin.skyCover.open(wx,(buildingBase(input.plan,b)+h)*FT-.1,wz),0);extensionSamples++;
  }
 }
 assert.ok(extensionSamples>0,'real generated awnings cover points outside section roofs and building footprints');
 console.log('SKY_COVER_HOUSEHOLD',JSON.stringify({indoor,roofs,openYard,openDeck,openLawn,extensionSamples,pieces:Object.keys(evidence).length,poolHouse:Object.fromEntries(Object.entries(evidence).filter(([k])=>k.startsWith('pool-house:')&&!k.includes('opening:')))}));
 yard.group.userData.releasePlants?.();
});
await test('all weather terms use exposure, fallback is 1, keys and budgets stay fixed',()=>{
 const scene=new THREE.Scene(),m=new THREE.MeshStandardMaterial(),o=new THREE.Mesh(new THREE.BoxGeometry(),m);scene.add(o);
 const layer=installWeatherSurface(scene);layer.prepare();assert.equal(m.defaultAttributeValues.weatherOpen[0],1);
 const renderer=new Renderer();renderer.toneMapping=THREE.ACESFilmicToneMapping;const cache=programs(renderer),keys=[];
 for(const weather of [{neutral:true},{precip:'rain',rate:1,wetness:1,puddles:1},{precip:'snow',snow_cm:8}]){
  layer.update(weather,2);const shader=programSource(renderer,cache,scene,o,makeLights());keys.push(shader.key);
  assert.ok(shader[2].includes('vWeatherOpen'));assert.ok(!/uniform\s+\w+\s+weatherOpen/.test(shader[2]));
  assert.ok(shader[2].includes('weatherExposure('));
  for(const term of ['weatherWet=weatherExposure(weatherSurface.x,vWeatherOpen)',
    'weatherS=weatherExposure(weatherSnow(weatherUp,weatherSurface.y,weatherEdgeValue),vWeatherOpen)',
    'weatherP=weatherExposure(weatherPuddle(weatherUp,weatherSurface.z,weatherEdgeValue),vWeatherOpen)',
    'weatherRingWeight=smoothstep(.9,.98,weatherUp)*weatherExposure(1.0,vWeatherOpen)',
    'if(weatherRingWeight>0.0)weatherSlope=weatherRipple(vWeatherWorld.xz)*weatherRingWeight'])assert.ok(shader[2].includes(term),term);
 }
 assert.equal(new Set(keys).size,1);
 o.geometry.setAttribute('weatherOpen',new THREE.Float32BufferAttribute(new Float32Array(o.geometry.attributes.position.count),1));
 assert.equal(programSource(renderer,cache,scene,o,makeLights()).key,keys[0],'attribute presence and covered values do not change program keys');
 o.geometry.attributes.weatherOpen.array.fill(1);
 assert.equal(programSource(renderer,cache,scene,o,makeLights()).key,keys[0],'open values keep the same program');
 const body=WEATHER_GLSL.match(/float weatherExposure\(float value, float openSky\) \{([\s\S]*?)\n\}/)[1];
 const exposure=new Function('clamp',`return (value,openSky)=>{${body}}`)((v,a,b)=>Math.max(a,Math.min(b,v)));
 for(const value of [0,.1,.5,1]){close(exposure(value,0),0);close(exposure(value,1),value);close(exposure(value,.5),value*.5);}
 layer.dispose();
});
await test('editor rebuildLevel and settle regenerate exposure after a hosted item moves outdoors',async()=>{
 const el=new Element();el.closest=selector=>selector==='.editor-shell'?el:null;
 const v=await mountTwin(el,{plan:structuredClone(input.plan),kit:input.kit,tier:'low',bake:false});
 const values=()=>{const out=[];v.scene.traverse(o=>{
  for(const r of o.userData.snapRanges||[])if(r.pieceId==='sky-sofa')for(let i=r.start;i<r.start+r.count;i++)out.push(o.geometry.attributes.weatherOpen.getX(i));
  if(o.userData.pieceId==='sky-sofa'&&!o.userData.snapRanges&&o.geometry?.attributes.weatherOpen)out.push(...o.geometry.attributes.weatherOpen.array);
 });return out;};
 assert.ok(values().length);assert.ok(values().every(x=>x===0));
 const flat=structuredClone(v.plan),b=flat.buildings.find(b=>b.id==='pool-house'),item=b.items.find(i=>i.id==='sky-sofa');
 item.host={ground:true,at:[200,200]};
 v.rebuildLevel(b.id,b.levels[0].id,flat,{items:['sky-sofa']});
 assert.ok(values().every(x=>x===1));
 const inside=structuredClone(flat);inside.buildings.find(building=>building.id===b.id).items.find(i=>i.id==='sky-sofa').host=input.plan.buildings.find(b=>b.id==='pool-house').items[0].host;
 await v.settle(inside,{buildingId:b.id,levelId:b.levels[0].id,touched:{items:['sky-sofa']}});
 assert.ok(values().length);assert.ok(values().every(x=>x===0));
 const yard=v.scene.getObjectByName('yard'),snapshot=[];
 yard.traverse(o=>{if(o.geometry?.attributes.weatherOpen)snapshot.push([o,Array.from(o.geometry.attributes.weatherOpen.array)]);});
 const roofPlan=structuredClone(v.plan),roof=roofPlan.buildings.find(building=>building.id===b.id).roof.sections[0];
 roof.overhang=(roof.overhang||0)+4;
 await v.rebuild(roofPlan);
 assert.equal(v.scene.getObjectByName('yard'),yard,'a roof edit reuses the existing yard');
 assert.ok(snapshot.some(([o,values])=>values.some((x,i)=>x!==o.geometry.attributes.weatherOpen.getX(i))),'reused yard receives the edited roof cover');
 v.dispose();
});
await test('coverTop is exactly where blocked starts, on the real household',()=>{
 const cover=createSkyCover(input.plan);let covered=0,open=0,checked=0;
 let seed=7;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
 const f=cover.heightField();const [x0,z0,x1,z1]=f.bounds;
 for(let i=0;i<4000;i++){
  const x=x0+rnd()*(x1-x0),z=z0+rnd()*(z1-z0),top=cover.coverTop(x,z);
  for(const y of [top-.05,top+.05,rnd()*12]){
   if(!Number.isFinite(y))continue;checked++;
   const blocked=cover.blocked(x,y,z),expected=Number.isFinite(top)&&y<top-.002;
   assert.equal(blocked,expected,`blocked(${x},${y},${z}) ${blocked} but coverTop ${top}`);
   blocked?covered++:open++;
  }
 }
 assert.ok(covered>500&&open>500,`both covered and open points were sampled (${covered}/${open})`);
 const i=Math.floor(f.width/2),j=Math.floor(f.height/2),cx=x0+(i+.5)*f.cell,cz=z0+(j+.5)*f.cell,t=cover.coverTop(cx,cz);
 close(f.data[j*f.width+i],Number.isFinite(t)?t-.002:-1e4);
 console.log(`  coverTop agrees with blocked at ${checked} points; field ${f.width}x${f.height} @ ${f.cell} m`);
});
await test('falling particles cull below cover on the GPU, with no per-drop CPU work',()=>{
 const p=createPrecipitation(new THREE.Scene(),{random:()=>.5});p.setPlan(plan);
 assert.equal(p.objects.rain.geometry.attributes.precipOpen,undefined,'no per-drop open attribute is uploaded');
 const camera=new THREE.PerspectiveCamera();camera.position.fromArray(world(-20,5,6));
 p.update(0,{precip:'rain',rate:1},camera);
 const tex=p.uniforms.precipCover.value,b=p.uniforms.precipCoverBounds.value;
 assert.ok(tex?.isDataTexture&&tex.image.width>1&&tex.image.height>1,'the cover height field is baked while it rains');
 // The shader's lookup, in JS: the texel under an indoor point holds a height above it.
 const [x,y,z]=world(5,5,1),u=(x-b.x)/(b.z-b.x),v=(z-b.y)/(b.w-b.y);
 const h=tex.image.data[(Math.floor(v*tex.image.height)*tex.image.width+Math.floor(u*tex.image.width))*2];
 assert.ok(y<h,`indoor drop is below the baked cover (${y} < ${h})`);
 const [ox,oy,oz]=world(-2-1/FT,5,1),ou=(ox-b.x)/(b.z-b.x),ov=(oz-b.y)/(b.w-b.y);
 const outside=ou<0||ov<0||ou>=1||ov>=1?-1e4:tex.image.data[(Math.floor(ov*tex.image.height)*tex.image.width+Math.floor(ou*tex.image.width))*2];
 assert.ok(oy>outside,'a drop beyond the eave edge stays open');
 const vs=p.objects.rain.material.vertexShader;
 assert.ok(vs.includes('if(precipitationCovered(world))')&&vs.includes('texture2D(precipCover,uv).r'),'the vertex shader culls covered drops');
 const before=tex;p.update(1/60,{precip:'rain',rate:1},camera);assert.equal(p.uniforms.precipCover.value,before,'no rebake per frame');
 p.setPlan(structuredClone(plan));p.update(2/60,{precip:'rain',rate:1},camera);assert.notEqual(p.uniforms.precipCover.value,before,'a new cover rebakes');
 p.dispose();
});
finish();
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    household = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    plan = flatten(assemble(household)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit}, timeout=180)
    print(output)
    sys.exit(code)
