"""Shared drawing, path geometry, receiver grid and real editor shelf under Node."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE=await import(three);
const {createSiteDrawing,snapSitePoint}=await import(file('static/twin/editor/site_drawing.js'));
const {pathOutline,pathCentreline,pathSurfacePolygons,pathPresets}=await import(file('static/twin/path_shapes.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {authoredGeometry}=await import(file('static/twin/bake/fingerprint.js'));
const {closedShape}=await import(file('static/twin/editor/site_shapes.js'));
const {drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
const {createHistory}=await import(file('static/twin/editor/history.js'));
const {vertexHandles,editVertex}=await import(file('static/twin/editor/polygon_handles.js'));
const {firePitRings,placedPit}=await import(file('static/twin/fire_pits.js'));
const {inPolygon}=await import(file('static/twin/twin_ground.js'));
const nodes=new Map();document.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};document.querySelector=()=>null;
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} near ${b}`);
const plan={buildings:[{position:[0,0],rotation:0,levels:[{id:'L1',outline:[[0,0],[10,0],[10,10],[0,10]]}],
 walls:[{exterior:true,level:'L1',from:[0,0],to:[10,0],footprint:[[0,-.25],[10,-.25],[10,.25],[0,.25]]}]}],
 site:{lot:[[-10,-10],[40,-10],[40,40],[-10,40]],terraces:[{id:'pad',polygon:[[15,5],[25,5],[25,15],[15,15]],height:-2,blend:0}]}};
const ops=[];let round=0;
const abort=new AbortController(), history=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>true,refresh:async()=>{},signal:abort.signal});
const draw=createSiteDrawing({getPlan:()=>plan,commit:operation=>history.perform(async()=>{ops.push(structuredClone(operation));round++;})});
near(snapSitePoint([4,.1],plan)[1],-.25);
assert.deepEqual(snapSitePoint([15.3,8],plan),[15,8]);
assert.deepEqual(snapSitePoint([29.6,25],{site:{beds:[{polygon:[[30,20],[35,20],[35,30],[30,30]]}]}}),[30,25],'legacy shapes without IDs still snap');
assert.deepEqual(snapSitePoint([29.6,25],{site:{pool:{polygon:[[30,20],[35,20],[35,30],[30,30]]}}}),[30,25],'legacy pool still snaps');
draw.start('beds');const materialBefore=new THREE.MeshStandardMaterial().id;
for(const p of [[2,.1],[8,.1],[15.3,8],[10,12],[2,10]])draw.add(p);
draw.move([1,5]);assert.equal(draw.preview().length,6);assert.equal(ops.length,0);
assert.equal(new THREE.MeshStandardMaterial().id,materialBefore+1,'drawing allocates no materials');
await draw.finish();assert.equal(ops.length,1);assert.equal(ops[0].polygon.length,5);assert.equal(ops[0].polygon[0][1],-.25);assert.equal(ops[0].polygon[2][0],15);
assert.equal(round,1,'one history step for the whole bed');assert.equal(nodes.get('rail-undo').disabled,false);
draw.start('terraces',{height:-2,blend:6});for(const p of [[1,1],[5,1],[5,5],[1,5]])draw.add(p,true);
draw.back();assert.equal(draw.current().points.length,3);await draw.finish();assert.equal(ops.at(-1).op,'add_pad');
draw.start('beds');draw.add([1,.1],true);near(draw.current().points[0][1],.1);draw.cancel();assert.equal(draw.current(),null);
draw.start('path',pathPresets.paver);draw.add([1,1],true);draw.add([8,1],true);await draw.finish();assert.equal(ops.at(-1).kind,'path');
for(const shape of ['round','square','rect','outline']) {
 const before=round, materials=new THREE.MeshStandardMaterial().id;
 const options={shape,...(shape==='round'?{radius:2}:shape==='square'?{side:4}:shape==='rect'?{width:4,depth:6}:{})};
 draw.start('fire_pit',options);
 for(const p of shape==='outline'?[[0,0],[6,0],[6,2],[2,2],[2,6],[0,6]]:[[5,5]])draw.add(p,true);
 draw.move([6,6],true);assert.equal(round,before);assert.equal(new THREE.MeshStandardMaterial().id,materials+1);
 await draw.finish();assert.equal(round,before+1);assert.equal(ops.at(-1).shape,shape);
 const pit=shape==='outline'?{shape,polygon:ops.at(-1).polygon}:placedPit(shape,ops.at(-1).at,options);
 const {outer,inner}=firePitRings(pit);assert.equal(inner.length,outer.length);assert.ok(inner.every(p=>inPolygon(outer,...p)));
 assert.ok(inner.flat().every(Number.isFinite));
 const site=await buildYard({buildings:[],site:{fire_pit:pit}},kit,'low');site.group.updateMatrixWorld(true);
 const wall=site.group.children.find(o=>o.material?.name==='base'),bowl=site.group.children.find(o=>o.material?.name==='counter');assert.ok(wall&&bowl,shape+' wall and inset bowl');
 const positions=wall.geometry.attributes.position;
 for(const p of outer)assert.ok(Array.from({length:positions.count},(_,i)=>[positions.getX(i),-positions.getZ(i)]).some(q=>Math.hypot(q[0]-p[0],q[1]-p[1])<1e-5),shape+' wall follows authored outline');
 const bp=bowl.geometry.attributes.position;for(let i=0;i<bp.count;i++)assert.ok(inPolygon(outer,bp.getX(i),-bp.getZ(i)),shape+' bowl stays inside');
 const ray=new THREE.Raycaster(new THREE.Vector3(1,10,-1),new THREE.Vector3(0,-1,0));
 const centre=shape==='outline'?[1,1]:[5,5];ray.ray.origin.set(centre[0],10,-centre[1]);
 assert.equal(ray.intersectObject(wall).length,0,shape+' ring is hollow');assert.ok(ray.intersectObject(bowl).length,shape+' inset fire bowl is present');
}
let beforeFence=round;draw.start('fence',{height:6,style:'wood'});for(const p of [[1,1],[5,1],[5,5]])draw.add(p,true);assert.equal(round,beforeFence);await draw.finish();assert.equal(round,beforeFence+1);assert.equal(ops.at(-1).polyline.length,3);
let path={kind:'path',points:[[0,0],[10,0]],width:4};
assert.deepEqual(pathOutline(path),[[0,2],[10,2],[10,-2],[0,-2]]);
path.points.push([10,10]);let outline=pathOutline(path);assert.equal(outline.length,6);assert.ok(outline.every(p=>p.every(Number.isFinite)));assert.ok(Math.max(...outline.flat())<=12);
const rounded={...path,corner:'rounded'};assert.ok(pathCentreline(rounded).length>3);assert.ok(pathOutline(rounded).length>6);
const smooth=pathCentreline({...path,points:[[0,0],[8,0],[10,8],[18,10]],smooth:true});assert.ok(smooth.length>25);
for(const knot of [[0,0],[8,0],[10,8],[18,10]])assert.ok(smooth.some(p=>p.every((v,i)=>v===knot[i])),'smooth curve passes through its authored points');
for(let i=1;i<smooth.length;i++)assert.ok(Math.hypot(...smooth[i].map((v,k)=>v-smooth[i-1][k]))<=1.000001);
for(const points of [[[0,0],[10,0],[.01,.001]],[[0,0],[10,0],[0,0]],[[0,0],[10,10],[0,10],[10,0]]]) {
 const p={...path,points};assert.ok(pathOutline(p).flat().every(Number.isFinite));assert.ok(pathSurfacePolygons(p).flat(2).every(Number.isFinite));
}
const source={buildings:[],materials:{},site:{terraces:[{id:'lower',polygon:[[10,0],[30,0],[30,20],[10,20]],height:-4,blend:0},...plan.site.terraces],hardscape:[{kind:'path',id:'walk',points:[[16,9],[24,9]],width:3,material:'patio_concrete',edging:'curb'}]}};
const beforeKey=authoredGeometry({...source,site:{terraces:source.site.terraces}});assert.notEqual(authoredGeometry(source),beforeKey);
const yard=await buildYard(source,kit,'low'), high=await buildYard(source,kit,'high');
const geometry=g=>{const out=[];g.traverse(o=>{if(o.isMesh){assert.equal(o.geometry.userData.bakeExcluded,false);out.push(...o.geometry.attributes.position.array);}});return out;};
const lowGeometry=geometry(yard.group);assert.deepEqual(lowGeometry,geometry(high.group),'one foot receiver grid is independent of tier');
assert.ok(lowGeometry.every(Number.isFinite));const ys=lowGeometry.filter((_,i)=>i%3===1);near(Math.max(...ys),-1.45);near(Math.min(...ys),-2);
const noCurb=structuredClone(source);noCurb.site.hardscape[0].edging='none';const plain=geometry((await buildYard(noCurb,kit,'low')).group);assert.ok(lowGeometry.length>plain.length);near(Math.max(...plain.filter((_,i)=>i%3===1)),-1.7);
const border=await buildYard({site:{edges:[{polygon:[[0,0],[10,0],[10,10],[0,10]],material:'mulch'}]},buildings:[]},kit,'low');
border.group.updateMatrixWorld(true);
const borderRay=new THREE.Raycaster(new THREE.Vector3(5,10,-5),new THREE.Vector3(0,-1,0));
assert.equal(borderRay.intersectObject(border.group,true).length,0,'planting edges remain borders, not filled beds');
borderRay.ray.origin.set(5,10,0);assert.ok(borderRay.intersectObject(border.group,true).length,'planting border is visible on Low');
const record={kind:'hardscape',index:0,piece:source.site.hardscape[0]};assert.equal(closedShape(record),false);
const hs=vertexHandles(record.piece.points,false);assert.equal(hs.length,3);assert.equal(editVertex(record.piece.points,{index:0},[0,0],{remove:true,closed:false}).length,2);
const host=new Element(), descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);let pending=Promise.resolve(), changed=[];
drawSiteShapeShelf(host,record,{canEdit:()=>true,queue:fn=>pending=pending.then(fn),op:op=>{changed.push(op);Object.assign(record.piece,op);},report:e=>{throw e;}});
for(const [label,value] of [['Width (ft)',4],['Corner style','rounded'],['Smooth curve','yes'],['Material','paving'],['Edging','curb']]) {
 const input=descendants(host).find(n=>n['aria-label']===label);assert.ok(input,label);input.value=String(value);input.dispatchEvent(new Event('change'));await pending;
}
assert.equal(record.piece.width,4);assert.equal(record.piece.smooth,true);assert.equal(record.piece.material,'paving');assert.equal(changed.length,5);
abort.abort();console.log('Shared drawing, wall/pad snaps, one-step history, path offsets/curves/hairpins, curb, drape, receiver grid, bake key and shelf passed');
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_site_draw_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=180)
        print(result.stdout, end='')
        assert result.returncode == 0, result.stderr


if __name__ == '__main__':
    run()
