"""Real buildYard geometry, including the untouched baseline loaded from git main."""
import json
from pathlib import Path
import subprocess
import sys
from test_twin_yard_material_slots_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import(three);
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {buildYard:baselineBuild}=await import(data(input.baseline.replace(/from '(\.\/[^']+)'/g,(_,p)=>`from '${file('static/twin/'+p.slice(2))}'`)));
const rect=(x,y,w=4,h=4)=>[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
// A pool with a coping is seated 0.12 ft into the ground. These pools are raised by as much,
// so every height below reads against the pool's datum at 0.
const SEAT=.12,plan=features=>({units:'ft',materials:{},buildings:[],site:{terraces:[],pool:{id:'pool',polygon:rect(0,0,30,20),depth:5,coping:1,elevation:SEAT,features}}});
const near=(a,b)=>assert.ok(Math.abs(a-b)<2e-5,`${a} != ${b}`);
const build=async(features,extra={})=>{const p=plan(features);Object.assign(p.site.pool,extra);return (await buildYard(p,input.kit,'low')).group;};
const meshes=g=>{const out=[];g.traverse(o=>{if(o.isMesh)out.push(o);});return out;};
function tris(g,material=null){g.updateMatrixWorld(true);return meshes(g).filter(m=>!material||m.material.name===material).flatMap(o=>{
 const p=o.geometry.attributes.position;if(!p)return [];const ids=o.geometry.index?.array||Array.from({length:p.count},(_,i)=>i),out=[];
 for(let i=0;i<ids.length;i+=3)out.push(Array.from(ids.slice(i,i+3),j=>new THREE.Vector3().fromBufferAttribute(p,j).applyMatrix4(o.matrixWorld).toArray()));
 return out;
});}
const cross=(a,b,p)=>(b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]);
const hasPoint=(t,x,y)=>{const p=t.map(v=>[v[0],-v[2]]),s=p.map((a,i)=>cross(a,p[(i+1)%3],[x,y]));return Math.abs(cross(p[0],p[1],p[2]))>1e-6&&(s.every(v=>v>=-1e-5)||s.every(v=>v<=1e-5));};
const horizontal=(t,y)=>t.every(p=>Math.abs(p[1]-y)<2e-5);
const topAt=(g,x,y,z,material=null)=>tris(g,material).some(t=>horizontal(t,z)&&hasPoint(t,x,y));
const geometry=g=>tris(g).map(t=>JSON.stringify(t)).sort();
const verticalWater=g=>tris(g,'water').filter(t=>Math.max(...t.map(p=>p[1]))-Math.min(...t.map(p=>p[1]))>1e-4);
const {buildPoolFeatures}=await import(file('static/twin/pool_features.js'));
const {buildPoolFeatures:oldFeatures}=await import(data(input.oldFeatures.replace(/from '(\.\/[^']+)'/g,(_,p)=>`from '${file('static/twin/'+p.slice(2))}'`)));
function spaOnly(feature,depth=5,builder=buildPoolFeatures,height=0){
 const g=new THREE.Group(),materials=new Map();
 const material=name=>{if(!materials.has(name))materials.set(name,new THREE.MeshStandardMaterial({name,side:THREE.DoubleSide}));return materials.get(name);};
 builder(g,{polygon:rect(0,0,30,20),depth,features:[{id:'spa',kind:'spa',polygon:rect(10,4,8,8),spillover:false,...feature}]},height,
  {mat:role=>material(role),plain:name=>material(name),water:material('water')});
 return g;
}
const ray=(g,origin,direction)=>{g.updateMatrixWorld(true);return new THREE.Raycaster(new THREE.Vector3(...origin),new THREE.Vector3(...direction)).intersectObjects(g.children,true);};
const solidHits=(g,origin,direction)=>ray(g,origin,direction).filter(h=>h.object.material.name!=='water');
await test('raised and flush spa shells reach the pool floor with no underwater gap; deeper shells stay unchanged',()=>{
 for(const mode of ['raised','flush'])for(const height of [0,2]){
  const water=height+(mode==='raised'?.45+1-2/12:-.25),floor=water-3,poolFloor=height-5;
  const g=spaOnly({mode,depth_in:36},5,buildPoolFeatures,height);
  near(Math.min(...tris(g).flat().map(p=>p[1])),poolFloor);
  for(const y of [poolFloor+.05,(poolFloor+floor)/2,floor-.05]){
   const hit=solidHits(g,[5,y,-8],[1,0,0])[0];assert.ok(hit,'pool-side ray hits wall below spa floor');near(hit.point.x,10);
   assert.equal(hit.object.material.name,'pool tile');
  }
  const deep={mode,depth_in:48,bench_width_in:0};
  const now=spaOnly(deep,2,buildPoolFeatures,height),old=spaOnly(deep,2,oldFeatures,height);
  assert.deepEqual(geometry(now),geometry(old),'deeper-than-pool spa keeps its old shell');
 }
});
await test('default bench has a closed seat ring and riser around a smaller visible footwell',()=>{
 const water=.45+1-2/12,floor=water-3,seat=water-1.5,g=spaOnly({});
 // The wall is as wide as the pool's coping (1 ft by default), so the basin is 11..17 by 5..11.
 for(const [x,y] of [[11.6,8],[16.4,8],[14,5.6],[14,10.4]]){
  assert.ok(topAt(g,x,y,seat,'pool tile'),'seat on each side');
  near(solidHits(g,[x,water+.1,-y],[0,-1,0])[0].point.y,seat);
 }
 near(solidHits(g,[14,water+.1,-8],[0,-1,0])[0].point.y,floor);
 const hit=solidHits(g,[14,(floor+seat)/2,-8],[-1,0,0])[0];near(hit.point.x,12.5);assert.equal(hit.object.material.name,'pool tile');
 // Rays from above cover the whole basin; only the middle reaches the floor.
 let floorSamples=0,seatSamples=0;
 for(let x=11.1;x<16.95;x+=.3)for(let y=5.1;y<10.95;y+=.3){
  const top=solidHits(g,[x,water+.1,-y],[0,-1,0])[0];assert.ok(top,'no open face in basin');
  if(Math.abs(top.point.y-floor)<2e-5)floorSamples++;else {near(top.point.y,seat);seatSamples++;}
 }
 assert.ok(floorSamples>0&&seatSamples>floorSamples,'bench reduces the visible floor');
 const custom=spaOnly({bench_in:12,bench_width_in:12});assert.ok(topAt(custom,11.6,8,water-1,'pool tile'));
 const noBench=spaOnly({bench_width_in:0});assert.equal(meshes(g).length,meshes(noBench).length+1,'one bench mesh, shared interior material');
 assert.equal(meshes(g)[0].material,meshes(g)[1].material);
});
await test('zero width and seats at or below the floor omit only the bench',()=>{
 const off=spaOnly({bench_width_in:0});
 for(const extra of [{bench_in:36},{bench_in:40},{bench_in:30,depth_in:24}]){
  const expected=spaOnly({...extra,bench_width_in:0}),g=spaOnly(extra);
  assert.deepEqual(geometry(g),geometry(expected));assert.equal(meshes(g).length,meshes(expected).length);
 }
 const old=spaOnly({bench_width_in:0},5,oldFeatures);
 assert.equal(meshes(off).length,meshes(old).length,'pool-floor fix adds no meshes');
 assert.deepEqual(geometry(spaOnly({bench_in:36})),geometry(off));
});
await test('small, narrow and concave footwells remain inside the basin with valid winding and finite positions',async()=>{
 const {inPolygon,segmentIntersection}=await import(file('static/twin/twin_ground.js'));
 const area=p=>p.reduce((s,a,i)=>{const b=p[(i+1)%p.length];return s+a[0]*b[1]-a[1]*b[0];},0);
 for(const outline of [rect(1,1,3),rect(1,1,.1,.1),[[1,1],[7,1],[7,7],[4,7],[4,3],[3,3],[3,7],[1,7]],
  [[1,1],[5,1],[5,5],[3.02,5],[3.02,2],[3,2],[3,5],[1,5]]])for(const poly of [outline,[...outline].reverse()]){
  const g=spaOnly({polygon:poly,bench_width_in:36});assert.ok(tris(g).flat(2).every(Number.isFinite));
  // Read the outlines actually passed to the seat extrusion, not a second offset implementation.
  const bench=meshes(g)[1],shape=bench.geometry.parameters.shapes;
  const points=path=>path.getPoints().map(p=>[p.x,p.y]).filter((p,i,a)=>i===0||Math.hypot(p[0]-a[0][0],p[1]-a[0][1])>1e-9);
  const inner=points(shape),footwell=points(shape.holes[0]);
  assert.equal(Math.sign(area(footwell)),Math.sign(area(inner)));assert.ok(Math.abs(area(footwell))<Math.abs(area(inner)));
  for(const [i,a] of footwell.entries()){
   const b=footwell[(i+1)%footwell.length];assert.ok(inPolygon(inner,...a));
   assert.ok(!inner.some((c,j)=>segmentIntersection(a,b,c,inner[(j+1)%inner.length])));
   assert.ok(!footwell.some((c,j)=>j>i+1&&!(i===0&&j===footwell.length-1)&&segmentIntersection(a,b,c,footwell[(j+1)%footwell.length])));
  }
 }
});
await test('bench edits rebuild only the pool part and invalidate the real bake layout',async()=>{
 const Y=await import(file('static/twin/twin_yard.js')),A=await import(file('static/twin/bake/atlas.js'));
 const p=plan([{id:'spa',kind:'spa',polygon:rect(10,4,8,8),spillover:false}]),k=input.kit;
 const first=await Y.buildYard(p,k,'low'),keys=Y.yardPartKeys(p,k,'low');
 const baked=A.buildAtlas(first.group,p,{room:{density:1,page:256,gutter:2}}).key;
 for(const [field,value] of [['bench_in',24],['bench_width_in',12]]){
  const next=structuredClone(p);next.site.pool.features[0][field]=value;
  const changed=Y.yardPartKeys(next,k,'low');assert.notEqual(changed.pool,keys.pool);
  for(const part of Object.keys(keys).filter(k=>k!=='pool'))assert.equal(changed[part],keys[part]);
  const rebuilt=await Y.buildYard(next,k,'low',{previous:first.group});
  assert.notDeepEqual(geometry(rebuilt.group),geometry(first.group));
  assert.notEqual(A.buildAtlas(rebuilt.group,next,{room:{density:1,page:256,gutter:2}}).key,baked);
 }
});
await test('ledge is its authored water depth below the pool water',async()=>{
 const g=await build([{id:'l',kind:'ledge',polygon:rect(1,1,8,6),depth_in:12}]);
 assert.ok(topAt(g,3,3,-1.25,'pool tile'));assert.ok(topAt(g,3,3,-.25,'water'));
 assert.ok(tris(g,'pool tile').some(t=>hasPoint(t,3,1)&&t.some(p=>Math.abs(p[1]+1.25)<1e-5)));
});
await test('tread bands descend away from every entry edge with even risers',async()=>{
 for(const edge of [0,1,2,3]){
  const g=await build([{id:'s',kind:'steps',polygon:rect(1,1,8,8),entry_edge:edge,treads:3}]);
  for(let i=0;i<3;i++){
   const distance=(i+.5)*8/3,point=edge===0?[5,1+distance]:edge===1?[9-distance,5]:edge===2?[5,9-distance]:[1+distance,5];
   assert.ok(topAt(g,...point,-5*(i+1)/4,'pool tile'),`edge ${edge} tread ${i}`);
  }
 }
});
await test('raised spa wall and coping heights, waterline, own basin and shared water material',async()=>{
 const g=await build([{id:'spa',kind:'spa',polygon:rect(26,4,8,8),mode:'raised',raise_in:18,depth_in:36,spillover:false}]);
 const wallTop=.3+18/12,copingTop=.45+18/12,water=copingTop-2/12;
 assert.ok(topAt(g,26.08,6,wallTop,'base'));assert.ok(topAt(g,26.1,6,copingTop,'paving'));
 assert.ok(topAt(g,28,6,water,'water'));assert.ok(topAt(g,28,6,water-3,'pool tile'));
 assert.equal(new Set(meshes(g).filter(m=>m.material.name==='water').map(m=>m.material)).size,1);
});
await test('flush spa water equals pool water and coping equals pool coping',async()=>{
 const g=await build([{id:'spa',kind:'spa',polygon:rect(26,4,8,8),mode:'flush',raise_in:24,depth_in:36}]);
 assert.ok(topAt(g,28,6,-.25,'water'));assert.ok(topAt(g,20,6,-.25,'water'));
 assert.ok(topAt(g,26.1,6,.45,'paving'));assert.equal(verticalWater(g).length,0);
});
await test('pool features bake as opaque receivers and their water never does',async()=>{
 // Every light bakes (2026-11-13): ledge, steps, spa basin, walls and coping receive baked
 // light; pool and spa water and the spillover sheet are transparent and stay out.
 const {atlasMesh}=await import(file('static/twin/bake/atlas.js'));
 const g=await build([{id:'l',kind:'ledge',polygon:rect(1,1,8,6),depth_in:12},{id:'s',kind:'steps',polygon:rect(1,12,6,6),entry_edge:3,treads:3},
  {id:'spa',kind:'spa',polygon:rect(26,4,8,8),mode:'raised',raise_in:18,depth_in:36,spillover:true}]);
 const received=new Set(),water=[];
 g.traverse(o=>{if(!o.isMesh)return;if(o.material.name==='water')water.push(atlasMesh(o));else if(atlasMesh(o))received.add(o.material.name);});
 assert.ok(received.has('pool tile'),`pool tile (floor, walls, ledge, steps, spa basin) receives: ${[...received]}`);
 assert.ok(received.has('base'),`the raised spa wall receives: ${[...received]}`);
 assert.ok(water.length&&water.every(v=>!v),'pool, spa and spillover water (merged) never bake: '+JSON.stringify(water));
});
await test('spa cuts the pool water and coping for inside, crossing, touching and overlapping outlines',async()=>{
 for(const poly of [rect(2,2,8,8),rect(26,4,8,8),rect(30,4,8,8),[[26,4],[34,4],[34,8],[29,8],[29,12],[26,12]]]){
  const g=await build([{id:'spa',kind:'spa',polygon:poly,mode:'raised',raise_in:12,spillover:false}]);
  assert.ok(topAt(g,15,15,-.25,'water'),'the remaining pool still has water');
  for(let x=.25;x<32;x+=.5)for(let y=.25;y<20;y+=.5){
   const inside=poly.reduce((v,a,i)=>{const b=poly[(i+1)%poly.length];return (a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]?!v:v;},false);
   if(inside){assert.ok(!topAt(g,x,y,-.25,'water'),'no pool water inside spa');assert.ok(!topAt(g,x,y,.45,'paving'),'no pool coping through spa');}
  }
 }
 const g=await build([{id:'a',kind:'spa',polygon:rect(25,4,8,8),spillover:false},{id:'b',kind:'spa',polygon:rect(27,6,8,8),spillover:false}]);
 assert.ok(!topAt(g,28,8,-.25,'water'),'overlapping cutters keep a union hole');
 const covered=await build([{id:'all',kind:'spa',polygon:rect(-1,-1,32,22),spillover:false}]);
 assert.ok(!topAt(covered,15,10,-.25,'water'),'a spa may cover the whole original pool');
 assert.ok(topAt(covered,15,10,.45+1-2/12,'water'),'its own basin still draws');
});
await test('spillover only draws on raised touching or overlapping spas with it enabled',async()=>{
 for(const [mode,x,spillover,expected] of [['raised',26,true,true],['raised',30,true,true],['raised',31,true,false],['raised',26,false,false],['flush',26,true,false]]){
  const g=await build([{id:'spa',kind:'spa',polygon:rect(x,4,8,8),mode,raise_in:12,spillover}]);
  assert.equal(verticalWater(g).length>0,expected,`${mode} ${x} ${spillover}`);
  for(const mesh of meshes(g).filter(m=>m.material.name==='water'))assert.ok(mesh.material.transparent&&!mesh.material.depthWrite);
 }
 const corner=await build([{id:'corner',kind:'spa',polygon:[[-2,-2],[2,2],[4,0],[0,-4]],spillover:true}]);
 assert.ok(verticalWater(corner).length,'a shared edge crossing a pool corner still spills');
 assert.ok(tris(corner).flat(2).every(Number.isFinite),'duplicate corner crossings never create zero-length sheets');
});
await test('small and narrow concave spa basins stay inside their authored outline',async()=>{
 const {inPolygon}=await import(file('static/twin/twin_ground.js'));
 for(const poly of [rect(1,1,.1,.1),[[1,1],[5,1],[5,5],[3.02,5],[3.02,2],[3,2],[3,5],[1,5]]]){
  const g=await build([{id:'small',kind:'spa',polygon:poly,spillover:false}]);
  const water=tris(g,'water').filter(t=>horizontal(t,.45+1-2/12));assert.ok(water.length);
  for(const t of water)for(const p of t)assert.ok(inPolygon(poly,p[0],-p[2]),'basin water stays within spa');
 }
});
await test('spa slots and inherited pool interior change materials without changing triangles',async()=>{
 const features=[{id:'ledge',kind:'ledge',polygon:rect(1,1),depth_in:10},{id:'steps',kind:'steps',polygon:rect(1,8),treads:3,entry_edge:3},
  {id:'spa',kind:'spa',polygon:rect(26,4,8,8),mode:'raised',raise_in:12,spillover:false}];
 const plain=await build(features),slotted=structuredClone(features);
 slotted[2].materials={coping:{id:'red_brick_03',color:'#aa3322'},interior:{id:'mocha_oak_veneer',color:'#336699'},wall:{id:'red_brick_03',color:'#112233'}};
 const g=await build(slotted);assert.deepEqual(geometry(g),geometry(plain));
 for(const color of ['aa3322','336699','112233'])assert.ok(meshes(g).some(m=>m.material.color.getHexString()===color));
 const inherited=await build(features,{materials:{interior:{id:'red_brick_03',color:'#abcdef'},coping:{id:'mocha_oak_veneer',color:'#123456'}}});
 assert.deepEqual(geometry(inherited),geometry(plain));assert.ok(!meshes(inherited).some(m=>m.material.name==='pool tile'));
});
const heights=(g,material)=>tris(g,material).flat().map(p=>p[1]);
await test('waterline tile runs all round the pool, from under the water to the coping',async()=>{
 const g=await build(undefined);
 near(Math.max(...heights(g,'pool tile')),-.5);near(Math.min(...heights(g,'waterline tile')),-.5);near(Math.max(...heights(g,'waterline tile')),.3);
 for(const [x,y] of [[15,-.1],[30.1,10],[15,20.1],[-.1,10]])assert.ok(tris(g,'waterline tile').some(t=>hasPoint(t,x,y)),`band on the wall at ${x},${y}`);
 const slotted=await build(undefined,{materials:{waterline:{id:'red_brick_03',color:'#aa3322'}}});
 assert.deepEqual(geometry(slotted),geometry(g));assert.ok(!meshes(slotted).some(m=>m.material.name==='waterline tile'));
 assert.ok(meshes(slotted).some(m=>m.material.color.getHexString()==='aa3322'));
 const shallow=await build(undefined,{depth:.4});assert.ok(tris(shallow).flat(2).every(Number.isFinite));
});
await test('raised spa: cladding above the pool water, pool finish below it, waterline tile round its own water',async()=>{
 const g=await build([{id:'spa',kind:'spa',polygon:rect(10,4,8,8),mode:'raised',raise_in:18,depth_in:36,spillover:false}]);
 near(Math.min(...heights(g,'base')),-.25);near(Math.max(...heights(g,'base')),.3+18/12);
 const outer=tris(g,'pool tile').filter(t=>hasPoint(t,10.05,8));
 assert.ok(outer.length&&outer.every(t=>t.every(p=>p[1]<=-.25+1e-5)),'under the water the outer wall is pool tile');
 const water=.45+18/12-2/12;assert.ok(tris(g,'waterline tile').some(t=>hasPoint(t,10.75,8)&&t.some(p=>Math.abs(p[1]-(water-.25))<1e-5)));
 const clad=await build([{id:'spa',kind:'spa',polygon:rect(10,4,8,8),mode:'raised',raise_in:18,spillover:false,materials:{wall:{id:'red_brick_03',color:'#112233'}}}]);
 const painted=meshes(clad).filter(m=>m.material.color.getHexString()==='112233');clad.updateMatrixWorld(true);
 assert.ok(painted.length);for(const m of painted){const b=new THREE.Box3().setFromObject(m);assert.ok(b.min.y>=-.25-1e-5,'the cladding slot never paints under the water');}
});
await test('flush spa: no cladding, the outer wall is pool finish with the pool waterline tile',async()=>{
 const g=await build([{id:'spa',kind:'spa',polygon:rect(10,4,8,8),mode:'flush',depth_in:36,materials:{wall:{id:'red_brick_03',color:'#112233'}}}]);
 assert.ok(!meshes(g).some(m=>m.material.name==='base'||m.material.color.getHexString()==='112233'));
 const outer=tris(g).filter(t=>hasPoint(t,10.05,8));
 assert.ok(outer.some(t=>t.every(p=>p[1]<=-.5+1e-5)));
 assert.ok(tris(g,'waterline tile').some(t=>hasPoint(t,10.05,8)&&t.some(p=>Math.abs(p[1]-.3)<1e-5)));
});
await test('steps beside a tanning ledge start level with it; steps elsewhere keep their own risers',async()=>{
 const ledge={id:'l',kind:'ledge',polygon:rect(1,1,8,6),depth_in:10},top=-.25-10/12;
 const g=await build([ledge,{id:'s',kind:'steps',polygon:rect(9,1,4,6),entry_edge:3,treads:3}]);
 assert.ok(topAt(g,5,4,top,'pool tile'));
 for(let i=0;i<3;i++)assert.ok([9.6,11,12.4].some(x=>topAt(g,x,4,top-(top+5)*i/3,'pool tile')),`tread ${i}`);
 assert.ok(topAt(g,9.6,4,top,'pool tile'),'the first tread meets the ledge');
 const apart=await build([ledge,{id:'s',kind:'steps',polygon:rect(20,10,4,6),entry_edge:3,treads:3}]);
 for(let i=0;i<3;i++)assert.ok([20.6,22,23.4].some(x=>topAt(apart,x,13,-5*(i+1)/4,'pool tile')),`free tread ${i}`);
});
await test('no features: all but the waterline band equals the pool before it',async()=>{
 for(const extra of [{},{depth:8,coping:2,elevation:3},{coping:0,materials:{interior:{id:'red_brick_03'}}}]){
  const p=plan(undefined);delete p.site.pool.features;Object.assign(p.site.pool,{elevation:0},extra);
  // The pool before it had no seat: raise today's pool by the seat to compare like with like.
  const seated={...p,site:{...p.site,pool:{...p.site.pool,elevation:(extra.elevation||0)+((extra.coping??1)>0?SEAT:0)}}};
  const old=(await baselineBuild(p,input.kit,'low')).group,newGroup=(await buildYard(seated,input.kit,'low')).group;
  const raw=g=>meshes(g).map(o=>({positions:Array.from(o.geometry.attributes.position.array),normal:Array.from(o.geometry.attributes.normal.array),uv:Array.from(o.geometry.attributes.uv.array),index:o.geometry.index&&Array.from(o.geometry.index.array),matrix:o.matrix.toArray()}));
  // The wall now splits at the band, 0.5 ft under the pool's datum; every other level face is unchanged.
  const level=g=>tris(g).filter(t=>horizontal(t,t[0][1])&&Math.abs(t[0][1]-((extra.elevation||0)-.5))>1e-4).map(t=>JSON.stringify(t.map(p=>p.map(v=>Math.round(v*1e4)/1e4+0)))).sort();
  // The fill under the coping adds level faces of its own, from just under the ground to the
  // coping's underside and outside the wall; every face the pool had before is still there.
  const before=level(old),after=level(newGroup),had=new Set(before),extra2=after.filter(t=>!had.has(t));
  assert.deepEqual(after.filter(t=>had.has(t)),before);
  assert.equal(extra2.length>0,(extra.coping??1)>.25);
  for(const t of extra2.map(t=>JSON.parse(t)))assert.ok(t.every(p=>[SEAT-.05,.3].some(z=>Math.abs(p[1]-(extra.elevation||0)-z)<1e-4)
   &&!(p[0]>-.24&&p[0]<30.24&&-p[2]>-.24&&-p[2]<20.24)),'only the fill under the coping is new');
 }
});
await test('the coping sits on a fill from the ground up, outside the pool wall, no deeper than the ground',async()=>{
 const g=await build(undefined);
 for(const [x,y] of [[15,-.6],[30.6,10],[15,20.6],[-.6,10],[-.6,-.6]]){
  assert.ok(topAt(g,x,y,SEAT-.05,'paving'),`fill under the coping at ${x},${y}`);assert.ok(topAt(g,x,y,.45,'paving'));
 }
 for(const [x,y] of [[15,-.1],[-.1,10],[15,-1.1]])assert.ok(!topAt(g,x,y,SEAT-.05),'not in the wall, not beyond the coping');
 const hit=solidHits(g,[-3,.15,-10],[1,0,0])[0];near(hit.point.x,-1);assert.equal(hit.object.material.name,'paving');
 assert.equal(solidHits(g,[-3,0,-10],[1,0,0]).filter(h=>Math.abs(h.point.x+1)<1e-3).length,0,'no band of coping below the ground');
 const none=await build(undefined,{coping:0});assert.ok(!tris(none).some(t=>horizontal(t,SEAT-.05)));
 const cut=await build([{id:'spa',kind:'spa',polygon:rect(26,4,8,8),spillover:false}]);
 assert.ok(!topAt(cut,30.6,8,SEAT-.05),'a spa that crosses the edge cuts the fill as it cuts the coping');
});
await test('a pool with a coping is seated so its coping top meets the paving beside it',async()=>{
 const yard=async extra=>{const p=plan(undefined);delete p.site.pool.elevation;Object.assign(p.site.pool,extra);
  p.site.hardscape=[{id:'patio',kind:'patio',polygon:rect(-10,-12,50,12)}];return (await buildYard(p,input.kit,'low')).group;};
 const g=await yard({});
 // Paving top at 0.3 ft; the coping top 0.03 ft over it, never in its plane; water 0.7 ft under the coping.
 assert.ok(topAt(g,15,-5,.3));assert.ok(topAt(g,15,-.5,.33,'paving'));assert.ok(!topAt(g,15,-.5,.45));assert.ok(topAt(g,15,10,-.37,'water'));
 const raised=await yard({elevation:2});assert.ok(topAt(raised,15,-.5,2.33,'paving'));
 // No coping, no seat: the wall top stays level with the paving.
 const bare=await yard({coping:0});assert.ok(topAt(bare,15,10,-.25,'water'));assert.ok(!topAt(bare,15,10,-.37,'water'));
});
await test('paving beside the pool stands no slab edge round a spa inside the pool',async()=>{
 const yard=async(spa,patio)=>{const p=plan([{id:'spa',kind:'spa',polygon:spa,mode:'flush',spillover:false}]);
  p.site.hardscape=[{id:'patio',kind:'patio',polygon:patio}];return (await buildYard(p,input.kit,'low')).group;};
 // Slab edges are the only upright paving faces between the ground and the slab top.
 const edges=(g,x0,y0,x1,y1)=>tris(g).filter(t=>t.every(p=>p[1]>-1e-4&&p[1]<.3+1e-4)&&Math.max(...t.map(p=>p[1]))-Math.min(...t.map(p=>p[1]))>.2
  &&t.every(p=>p[0]>x0-1e-3&&p[0]<x1+1e-3&&-p[2]>y0-1e-3&&-p[2]<y1+1e-3)).length;
 // A patio along the pool's low-y edge; the corner spa's edge lies on the same line.
 assert.equal(edges(await yard(rect(0,0,7,7),rect(-10,-12,50,12)),0,.5,7,7),0,'no slab edge inside the pool');
 // A spa that reaches out of the pool into the patio still cuts it.
 assert.ok(edges(await yard(rect(10,-3,7,7),rect(-10,-12,50,12)),10,-3,17,-.5)>0,'the patio is cut where the spa reaches into it');
});
await test('a spa wall and its coping are as wide as the pool coping',async()=>{
 const spa={id:'spa',kind:'spa',polygon:rect(10,4,8,8),mode:'raised',raise_in:12,spillover:false},top=.45+1;
 for(const [coping,width] of [[1,1],[2,2],[.5,.5],[0,.3]]){
  const g=await build([spa],{coping,elevation:coping>0?SEAT:0});
  for(const [x,y] of [[10+width-.05,8],[18-width+.05,8],[14,4+width-.05],[14,12-width+.05]])assert.ok(topAt(g,x,y,top,'paving'),`coping ${coping} covers ${x},${y}`);
  for(const [x,y] of [[10+width+.05,8],[18-width-.05,8]])assert.ok(!topAt(g,x,y,top,'paving'),`coping ${coping} stops before ${x},${y}`);
  assert.ok(topAt(g,10+width+.05,8,top-2/12,'water'),'the water starts where the coping ends');
 }
 const flush=await build([{...spa,mode:'flush'}]);
 assert.ok(topAt(flush,10.9,8,.45,'paving'));assert.ok(!topAt(flush,11.1,8,.45,'paving'));
});
await test('a flush spa in the pool corner shares the pool wall: coping only on its two inside edges',async()=>{
 const corner={id:'spa',kind:'spa',polygon:rect(0,0,8,8),mode:'flush',depth_in:36};
 for(const poly of [corner.polygon,[...corner.polygon].reverse()]){
  const g=await build([{...corner,polygon:poly}]);
  for(const [x,y] of [[7.5,4],[4,7.5],[7.5,7.5],[7.5,.2],[.2,7.5]])assert.ok(topAt(g,x,y,.45,'paving'),`coping on the inside edge at ${x},${y}`);
  for(const [x,y] of [[.5,4],[4,.5],[.5,.5],[6.9,6.9]])assert.ok(!topAt(g,x,y,.45,'paving'),`no spa coping at ${x},${y}`);
  for(const [x,y] of [[.1,4],[4,.1],[.1,.1],[6.9,6.9]])assert.ok(topAt(g,x,y,-.25,'water'),`spa water reaches the pool wall at ${x},${y}`);
  for(const [x,y] of [[.2,4],[4,.2]])assert.ok(!topAt(g,x,y,.3),'no second wall inside the pool wall');
  assert.ok(topAt(g,7.8,4,.3)&&topAt(g,7.2,4,.3),'the inside edges keep their wall');
  assert.ok(topAt(g,-.5,4,.45,'paving')&&topAt(g,4,-.5,.45,'paving'),'the pool coping runs past the spa');
  // The bench still runs all round, against the pool wall too.
  assert.ok(topAt(g,.5,4,-.25-1.5)&&topAt(g,6.5,4,-.25-1.5));
  assert.ok(tris(g).flat(2).every(Number.isFinite));
 }
 const one=await build([{...corner,polygon:rect(10,0,8,8)}]);
 assert.ok(!topAt(one,14,.5,.45,'paving'));for(const [x,y] of [[10.5,4],[17.5,4],[14,7.5]])assert.ok(topAt(one,x,y,.45,'paving'));
 const raised=await build([{...corner,mode:'raised',raise_in:12,spillover:false}]);
 for(const [x,y] of [[.5,4],[4,.5],[7.5,4],[4,7.5]])assert.ok(topAt(raised,x,y,.45+1,'paving'),'a raised spa keeps its wall and coping all round');
 const whole=await build([{...corner,polygon:rect(0,0,30,20)}]);assert.ok(topAt(whole,15,10,-.25,'water'));
});
finish();
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    baseline = subprocess.check_output(['git', 'show', '6b054474:chauffeur/static/twin/twin_yard.js'], cwd=ROOT, encoding='utf-8')
    old_features = subprocess.check_output(['git', 'show', 'HEAD:chauffeur/static/twin/pool_features.js'], cwd=ROOT, encoding='utf-8')
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit, 'baseline': baseline, 'oldFeatures': old_features,
        'manifest': json.loads((ROOT / 'twin_library/manifest.json').read_text(encoding='utf-8'))})
    print(output)
    sys.exit(code or 0)
