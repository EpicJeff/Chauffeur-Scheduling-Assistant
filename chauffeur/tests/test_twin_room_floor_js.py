"""CPU geometry acceptance; no Chromium or GPU claims."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {hostPoint,parkingPoint} = await import(file('static/twin/twin_hosts.js'));
const {openingFloor,roomFloor,foundationPieces} = await import(file('static/twin/twin_floors.js'));
const {buildingBase,groundAt} = await import(file('static/twin/twin_ground.js'));
const {parkingObjects,lotPoint} = await import(file('static/twin/live/energy_geometry.js'));
const {buildAtlas} = await import(file('static/twin/bake/atlas.js'));
const {authoredGeometry} = await import(file('static/twin/bake/fingerprint.js'));
const {lightSource} = await import(file('static/twin/bake/reach.js'));
const {cutHeight} = await import(file('static/twin/viewing.js'));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-4,`${a} != ${b}`);
const square=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
const outline=square(0,0,20,10),level={id:'L1',elevation:0,ceiling:10,outline};
const b={id:'b',position:[0,0],base:2,levels:[level],foundation:{mode:'fixed',thickness_ft:1},
 rooms:[{id:'living',level:'L1',polygon:square(0,0,10,10)},
  {id:'garage',level:'L1',polygon:square(10,0,20,10),floor_offset_ft:-2}],
 walls:[...outline.map((p,i)=>({id:`w${i}`,from:p,to:outline[(i+1)%4],level:'L1',height:10,thickness:.5,exterior:true})),
  {id:'shared',from:[10,0],to:[10,10],level:'L1',height:10,thickness:.5,exterior:false}],
 openings:[{id:'garage-door',wall:'w1',at:5,width:6,sill:0,head:7,kind:'garage'},
  {id:'inside-door',wall:'shared',at:5,width:3,sill:0,head:7,kind:'door'}],
 roof:{sections:[]},anchors:[{id:'park',kind:'parking',host:{floor:'garage',u:.5,v:.5}}],items:[],
 fixtures:[{id:'seat',kind:'sofa',level:'L1',rect:[12,2,14,4],height:3}]};
const plan={buildings:[b],site:{},materials:{}};
const twin=buildTwin(plan,kit,'low',{viewing:true,editableLevel:'b:L1'});await twin.ready;twin.root.updateMatrixWorld(true);
function topAt(x,y,role,model=twin){
 const meshes=[];model.root.traverse(o=>{if(o.isMesh&&o.material.name===role&&!o.layers.isEnabled(31))meshes.push(o);});
 const ray=new THREE.Raycaster(new THREE.Vector3(x*.3048,30,-y*.3048),new THREE.Vector3(0,-1,0));
 const hit=ray.intersectObjects(meshes,false)[0];assert.ok(hit,`missing ${role} at ${x},${y}`);return hit.point.y/.3048;
}
near(topAt(15,5,'floor'),0);near(topAt(5,5,'floor'),2);
near(topAt(15,5,'patio_concrete'),0);near(topAt(5,5,'patio_concrete'),2);
const bounds=(id,role)=>{const box=new THREE.Box3();for(const o of twin.pieces.get(`b:${id}`)||[])if(o.isMesh&&(!role||o.material.name===role))box.expandByObject(o);assert.ok(!box.isEmpty(),id);return box;};
near(bounds('shared').min.y/.3048,0);near(bounds('shared').max.y/.3048,12);
near(bounds('seat').min.y/.3048,0);
// Frames share a static batch: inspect the vertices at each opening, not the
// whole batch's bounds (which also contains the neighbouring opening).
function frameBottomAt(x) {let bottom=Infinity;twin.root.traverse(o=>{
 if(!o.isMesh||o.material.name!=='window_frame')return;const p=o.geometry.attributes.position;
 for(let i=0;i<p.count;i++){const q=new THREE.Vector3().fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);
  if(Math.abs(q.x/.3048-x)<.5)bottom=Math.min(bottom,q.y/.3048);}});return bottom;}
near(frameBottomAt(20),-.08);near(frameBottomAt(10),1.92);
assert.deepEqual(openingFloor(b,b.walls[4],5),{offset:0,step_down_ft:2});
near(lotPoint(b,hostPoint(b,{floor:'garage',u:.5,v:.5}),plan)[2],0);
near(lotPoint(b,parkingPoint(b,b.anchors[0],plan,0,groundAt),plan)[2],0);
near(parkingObjects({plan})[0].at[2],.08); // existing decal inset above grade
near(hostPoint(b,{ceiling:'garage',u:.5,v:.5})[2],10);
near(lightSource(plan,{building:'b',level:'L1',room:'garage',at:[15,5,0]}).source.y/.3048,4.5);
near(lightSource(plan,{building:'b',level:'L1',room:'garage',at:[15,5,12]}).source.y/.3048,11.8);
// One unsplit exterior wall borders both rooms: its bottom changes along it.
const south=twin.pieces.get('b:w0').filter(o=>o.isMesh&&!o.userData.viewingWalls);
let low=false,high=false;for(const o of south){const p=o.geometry.attributes.position;
 for(let i=0;i<p.count;i++){const q=new THREE.Vector3().fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);
  if(q.x/.3048>11&&Math.abs(q.y)<1e-5)low=true;if(q.x/.3048<9&&Math.abs(q.y/.3048-2)<1e-5)high=true;}}
assert.ok(low&&high,'long exterior wall follows each room floor');
// Concrete includes the wall footprint outside the room line.
const widened=structuredClone(b);widened.levels[0].outline=square(-.5,-.5,20.5,10.5);
const contour=widened.levels[0].outline;
const parts=foundationPieces(widened,level,THREE.ShapeUtils.triangulateShape(contour.map(p=>new THREE.Vector2(...p)),[]).map(ids=>ids.map(i=>contour[i])));
assert.ok(parts.some(p=>p.top===-2&&p.polygon.some(q=>q[0]>20)),'no exterior garage plinth');
const atlas=buildAtlas(twin.root,plan,{room:{density:1,page:256}});
const garageIndex=atlas.room.rooms.findIndex(r=>r.id==='garage');
assert.ok(atlas.room.charts.some(c=>c.room===garageIndex),'sunken floor remains an owned bake receiver');
const changed=structuredClone(plan);changed.buildings[0].rooms[1].floor_offset_ft=-1;
assert.notEqual(authoredGeometry(changed),authoredGeometry(plan),'authored offset participates in the geometry key');
const next=buildTwin(changed,kit,'low');await next.ready;
assert.notEqual(buildAtlas(next.root,changed,{room:{density:1,page:256}}).key,atlas.key,'offset invalidates bake');
assert.ok(b.base+roomFloor(level,b.rooms[1])<b.base+level.elevation+cutHeight(level),'sunken slab lies below level cut');
const upperPlan=structuredClone(plan),ub=upperPlan.buildings[0];
ub.levels.push({...level,id:'L2',elevation:10});
ub.rooms.push(...ub.rooms.map(r=>({...r,id:'upper-'+r.id,level:'L2'})));
ub.walls.push(...ub.walls.map(w=>({...w,id:'upper-'+w.id,level:'L2'})));
ub.walls.find(w=>w.id==='upper-w1').footprint=[[19.75,0],[20.25,0],[20.25,10],[19.75,10]];
const upper=buildTwin(upperPlan,kit,'low',{editableLevel:'b:L2'});await upper.ready;upper.root.updateMatrixWorld(true);
near(topAt(15,5,'floor',upper),10);near(topAt(5,5,'floor',upper),12);
const filler=new THREE.Box3();for(const o of upper.pieces.get('b:floor:L2')||[])filler.expandByObject(o);
near(filler.max.y/.3048,10); // wall-footprint slab follows the sunken upper room too
const raised=structuredClone(plan);raised.buildings[0].rooms[1].floor_offset_ft=2;
const raisedTwin=buildTwin(raised,kit,'low');await raisedTwin.ready;raisedTwin.root.updateMatrixWorld(true);
near(topAt(15,5,'floor',raisedTwin),4);
assert.deepEqual(openingFloor(raised.buildings[0],raised.buildings[0].walls[4],5),{offset:2,step_down_ft:2});
b.foundation={mode:'auto',offset_ft:2,thickness_ft:1};near(buildingBase(plan,b),2);
near(buildingBase(plan,b)+roomFloor(level,b.rooms[1]),0);
// Both floors can be sunken; an interior opening still uses the higher floor.
b.rooms[0].floor_offset_ft=-1;assert.deepEqual(openingFloor(b,b.walls[4],5),{offset:-1,step_down_ft:1});
console.log('Passed: actual slabs, wall bottoms, opening frames, floor hosts, parking/energy, foundation footprint, bake key/receiver, cut and auto base');
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='room_floor_node_') as d:
        driver, data = Path(d)/'driver.mjs', Path(d)/'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=120)
        print(result.stdout, end='')
        assert result.returncode == 0, result.stderr


if __name__ == '__main__':
    run()
