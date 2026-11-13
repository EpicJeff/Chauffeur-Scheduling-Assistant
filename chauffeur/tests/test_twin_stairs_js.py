"""Real generator/atlas geometry, legacy bytes, rail pitch and derived doorway steps."""
import json
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node
from twin_solid_normals import NORMAL_CHECKS

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + NORMAL_CHECKS + r"""
const THREE=await import(three);
const {buildTwin,boxGeometry,polygon,stairHoles}=await import(file('static/twin/twin_generator.js'));
const {stairGeometry,doorwaySteps}=await import(file('static/twin/twin_stairs.js'));
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const {authoredGeometry}=await import(file('static/twin/bake/fingerprint.js'));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);
const square=(a,b,c,d)=>[[a,b],[c,b],[c,d],[a,d]];
const stair={id:'stairs',level:'L1',from:[2,4],to:[14,4],width:3,rise_to:9,risers:15};
// Compare every attribute byte with the pre-feature loop, including arbitrary rotation.
for(const s of [stair,{...stair,from:[1.3,4.7],to:[12.55,15.125]}]){
 const parts=stairGeometry(s,0,boxGeometry);assert.equal(parts.length,s.risers);
 const dx=s.to[0]-s.from[0],dy=s.to[1]-s.from[1],length=Math.hypot(dx,dy),angle=Math.atan2(dy,dx);
 for(let i=0;i<s.risers;i++){
  const run=length/s.risers,height=(s.rise_to-0)*(i+1)/s.risers;
  const old=boxGeometry(run,height,s.width).rotateY(angle).translate(s.from[0]+dx*(i+.5)/s.risers,height/2,-s.from[1]-dy*(i+.5)/s.risers);
  for(const key of Object.keys(old.attributes))assert.deepEqual(Buffer.from(parts[i].geometry.attributes[key].array.buffer),Buffer.from(old.attributes[key].array.buffer),key);
  assert.deepEqual(parts[i].geometry.index.array,old.index.array);
 }
}
const open=stairGeometry({...stair,style:'open',rail:'both'},0,boxGeometry);
assert.equal(open.filter(p=>p.part==='tread').length,15);
assert.equal(open.filter(p=>p.part==='stringer').length,2);
assert.equal(open.filter(p=>p.part==='solid'||p.part==='riser').length,0);
assert.equal(open.filter(p=>p.part==='handrail').length,2);
for(const part of open){
 part.geometry.computeBoundingBox();const centre=part.geometry.boundingBox.getCenter(new THREE.Vector3());
 for(const t of trianglesOf(part.geometry))assert.ok(t.normal.dot(t.centre.clone().sub(centre))>0,'closed box faces outward');
}
for(const rail of open.filter(p=>p.part==='handrail')){
 const p=rail.geometry.attributes.position;
 for(let i=0;i<p.count;i++){
  // At every nosing, pitch line = first rise + rise/run * distance.
  const above=(p.getY(i)-(.6+(p.getX(i)-2)*9/12))*12;
  assert.ok(above>=34&&above<=38,`handrail ${above} inches above nosings`);
 }
}
for(const [rail,count] of [['none',0],['left',1],['right',1],['both',2]])
 assert.equal(stairGeometry({...stair,style:'open',rail},0,boxGeometry).filter(p=>p.part==='handrail').length,count);
const outline=square(0,0,30,20);
const b={id:'b',position:[0,0],base:0,levels:[{id:'L1',elevation:0,ceiling:9,outline},{id:'L2',elevation:9,ceiling:9,outline}],
 rooms:[{id:'high',level:'L1',polygon:square(0,0,15,20)},
  {id:'low',level:'L1',polygon:square(15,0,30,20),floor_offset_ft:-1.5,floor_material:{id:'wood_floor',color:'#987654'}},
  {id:'upper',level:'L2',polygon:outline}],
 walls:[{id:'shared',from:[15,0],to:[15,20],thickness:.5,height:9,level:'L1'}],
 openings:[{id:'door',wall:'shared',kind:'door',at:10,width:3,sill:0,head:7}],
 stairs:[{...stair,style:'open',rail:'both'}],roof:{sections:[]},anchors:[],items:[],fixtures:[]};
const plan={buildings:[b],site:{},materials:{}};
const steps=doorwaySteps(b,b.openings[0]);assert.equal(steps.length,3);
for(const s of steps){
 near(s.riser,.5);assert.equal(s.room.id,'low');assert.ok(s.polygon.every(p=>p[0]>=15.25));
 near(Math.max(...s.polygon.map(p=>p[1]))-Math.min(...s.polygon.map(p=>p[1])),3);
 near(Math.max(...s.polygon.map(p=>p[0]))-Math.min(...s.polygon.map(p=>p[0])),11/12);
 checkBoundaryNormals(polygon(s.polygon,s.bottom,s.top),s.polygon,{bottom:s.bottom,top:s.top,label:'door step'});
}
assert.equal(doorwaySteps(b,{...b.openings[0],kind:'window',step_down_ft:1.5}).length,0);
const reversed=structuredClone(b);reversed.walls[0].from=[15,20];reversed.walls[0].to=[15,0];
assert.ok(doorwaySteps(reversed,reversed.openings[0]).every(s=>s.polygon.every(p=>p[0]>=15.25)),'wall direction does not pick the side');
const swapped=structuredClone(b);swapped.rooms[0].floor_offset_ft=-3;
assert.ok(doorwaySteps(swapped,swapped.openings[0]).every(s=>s.polygon.every(p=>p[0]<=14.75)),'left lower room');
const flat=structuredClone(b);flat.rooms[1].floor_offset_ft=0;
assert.equal(doorwaySteps(flat,flat.openings[0]).length,0);
const edited=structuredClone(plan);edited.buildings[0].stairs[0].to=[18,6];edited.buildings[0].stairs[0].width=4;
assert.notDeepEqual(stairHoles(b,b.levels[1]),stairHoles(edited.buildings[0],b.levels[1]));
assert.equal(stairHoles(b,b.levels[0]).length,0);
const highStair={...stair,level:'L2',rise_to:18};
assert.equal(stairHoles({...b,stairs:[highStair]},b.levels[1]).length,0,'starting floor never gets a hole');
const make=async(p,tier='low')=>{const twin=buildTwin(p,input.kit,tier,{editableLevel:'b:L1'});await twin.ready;twin.root.updateMatrixWorld(true);return twin;};
const twin=await make(plan);
const drawnSteps=twin.pieces.get('b:door').filter(o=>o.isMesh&&!o.layers.isEnabled(31)&&o.material.name==='floor');
assert.ok(drawnSteps.some(o=>o.material.color.getHexString()==='987654'),'steps use lower room floor material');
const windowPlan=structuredClone(plan);windowPlan.buildings[0].openings[0].kind='window';
const windowTwin=await make(windowPlan);
assert.equal((windowTwin.pieces.get('b:door')||[]).filter(o=>o.isMesh&&!o.layers.isEnabled(31)&&o.material.name==='floor').length,0,'generator draws no window steps');
const key=p=>authoredGeometry(p);
assert.notEqual(key(plan),key(edited));
const offset=structuredClone(plan);offset.buildings[0].rooms[1].floor_offset_ft=0;
assert.notEqual(key(plan),key(offset));
const atlas=(t,p)=>buildAtlas(t.root,p,{room:{density:1,page:512}}).key;
assert.notEqual(atlas(twin,plan),atlas(await make(edited),edited));
assert.notEqual(atlas(twin,plan),atlas(await make(offset),offset),'room offset that creates doorway steps invalidates actual atlas');
const tierKeys=[];
for(const tier of ['low','medium','high']){
 const t=await make(plan,tier);tierKeys.push(buildAtlas(t.root,plan,{room:{density:1,page:512}}).key);
 const stepMesh=t.pieces.get('b:door').filter(o=>o.isMesh&&!o.layers.isEnabled(31)&&o.material.name==='floor');
 assert.ok(stepMesh.length,'derived steps drawn by generator in every tier');
}
assert.equal(new Set(tierKeys).size,1,'same authored stair/step bake across tiers');
// Test the real generated upper floor via a downward ray, including the edited hole.
for(const [p,x,expected] of [[plan,15.5,true],[edited,15.5,false]]){
 const t=await make(p);const floor=t.pieces.get('b:upper').filter(o=>o.isMesh&&!o.layers.isEnabled(31)&&o.material.name==='floor');
 const ray=new THREE.Raycaster(new THREE.Vector3(x*.3048,12*.3048,-5*.3048),new THREE.Vector3(0,-1,0));
 assert.equal(ray.intersectObjects(floor,false).length>0,expected,'edited stair arrival cuts actual floor');
}
console.log('Passed: legacy attribute bytes, open treads/stringers, pitched rails, outward normals, lower-side derived steps/window skip, edited floor hole and tier-stable bake invalidation');
"""


if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit})
    print(output)
    sys.exit(code or 0)
