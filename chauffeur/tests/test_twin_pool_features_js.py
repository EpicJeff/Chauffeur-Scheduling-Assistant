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
const plan=features=>({units:'ft',materials:{},buildings:[],site:{terraces:[],pool:{id:'pool',polygon:rect(0,0,30,20),depth:5,coping:1,features}}});
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
await test('no features builds byte-identical geometry to main',async()=>{
 for(const extra of [{},{depth:8,coping:2,elevation:3},{coping:0,materials:{interior:{id:'red_brick_03'}}}]){
  const p=plan(undefined);delete p.site.pool.features;Object.assign(p.site.pool,extra);
  const old=(await baselineBuild(p,input.kit,'low')).group,newGroup=(await buildYard(p,input.kit,'low')).group;
  const raw=g=>meshes(g).map(o=>({positions:Array.from(o.geometry.attributes.position.array),normal:Array.from(o.geometry.attributes.normal.array),uv:Array.from(o.geometry.attributes.uv.array),index:o.geometry.index&&Array.from(o.geometry.index.array),matrix:o.matrix.toArray()}));
  assert.deepEqual(raw(newGroup),raw(old));
 }
});
finish();
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    baseline = subprocess.check_output(['git', 'show', 'main:chauffeur/static/twin/twin_yard.js'], cwd=ROOT, encoding='utf-8')
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit, 'baseline': baseline,
        'manifest': json.loads((ROOT / 'twin_library/manifest.json').read_text(encoding='utf-8'))})
    print(output)
    sys.exit(code or 0)
