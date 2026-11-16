"""Point snap performance and real generated host geometry under Node."""
import json
import sys
from pathlib import Path
from test_twin_yard_material_slots_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
const {performance}=await import('node:perf_hooks');
const {createPointSnap}=await import(file('static/twin/editor/point_snap.js'));
const canvas=document.createElement('canvas'),camera=new THREE.PerspectiveCamera(50,1440/900,.01,1000),scene=new THREE.Group();
camera.position.set(0,12,10);camera.lookAt(0,0,0);camera.updateMatrixWorld(true);
const view={scene,camera,renderer3:{domElement:canvas},pick:()=>null};
const geometry=new THREE.BoxGeometry(.8,.5,.8,12,12,12),material=new THREE.MeshBasicMaterial();
for(let i=0;i<300;i++) {const m=new THREE.Mesh(geometry,material);m.position.set((i%20-10)*1.1,0,(Math.floor(i/20)-7)*1.1);scene.add(m);}
const terrain=new THREE.Mesh(new THREE.PlaneGeometry(40,40,225,225).rotateX(-Math.PI/2),material);terrain.position.y=-.4;terrain.userData.terrain=true;scene.add(terrain);
scene.updateMatrixWorld(true);
let triangles=0;scene.traverse(o=>{if(o.isMesh)triangles+=(o.geometry.index?.count||o.geometry.attributes.position.count)/3;});
assert.ok(scene.children.length>=300&&triangles>=500000);
let builds=0;const snap=createPointSnap(view,()=>({}),{onFeatures:()=>builds++});
snap.pick({clientX:720,clientY:450});const first=builds;snap.pick({clientX:721,clientY:451});
if(!input.baseline) {assert.ok(first>0,'world feature build seam called');assert.equal(builds,first,'second pick reuses world features');}
const start=performance.now();
for(let i=0;i<50;i++)snap.pick({clientX:680+i*1.5,clientY:430+i*.5});
const mean=(performance.now()-start)/50;
console.log(`PERF ${input.baseline?'before':'after'}: ${mean.toFixed(3)} ms mean, 50 moving picks, ${scene.children.length} meshes, ${triangles} triangles; budget 12 ms (slow CI)`);
if(!input.baseline)assert.ok(mean<12,`mean ${mean} ms exceeds 12 ms slow-CI budget`);
const frameChecks=[];
if(!input.baseline) {
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const plan={units:'ft',materials:{},buildings:[],site:{terraces:[],pool:{id:'pool',polygon:[[0,0],[30,0],[30,20],[0,20]],coping:1,depth:5,
 features:[{id:'spa',kind:'spa',polygon:[[10,5],[18,5],[18,13],[10,13]],raise_in:12,mode:'raised'}]},
 fence:[{id:'fence',polyline:[[40,0],[48,0]],height:6}],hardscape:[{id:'patio',polygon:[[55,0],[65,0],[65,10],[55,10]]}]}};
const yard=await buildYard(plan,input.kit,'low');yard.group.scale.setScalar(.3048);
view.scene=yard.group;view.pick=()=>null;
const point=p=>new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048);
function aim(p) {const target=point(p);camera.position.copy(target).add(new THREE.Vector3(0,8,0));camera.up.set(0,0,-1);camera.lookAt(target);camera.updateMatrixWorld(true);}
function event(p,dx=0,dy=0) {const v=point(p).project(camera);return {clientX:(v.x+1)*720+dx,clientY:(1-v.y)*450+dy};}
const near=(a,b)=>a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<2e-5,JSON.stringify({a,b})));
const real=createPointSnap(view,()=>plan);
for(const [kind,id,p] of [['spa','spa',[18,13,1.33]],['pool','pool',[0,0,.33]],['fence','fence',[39.83,-.17,6.3]],['hardscape','patio',[55,0,.3]]]) {
 aim(p);const hit=real.pick(event(p));assert.ok(hit,kind);assert.equal(hit.vertex,true,kind);near(hit.at,p);assert.deepEqual(hit.anchor?.host,{kind,id});
 frameChecks.push({plan,anchor:hit.anchor,at:hit.at});console.log(`ok real generated ${kind} vertex with stable ${id} anchor`);
}
// Unidentified scenery cannot steal a nearby identified vertex/edge.
{
 aim([55,0,.3]);const anonymous=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),material);
 anonymous.position.copy(point([55,0,.3]));anonymous.position.y-=.5;anonymous.position.x-=.5;anonymous.position.z+=.5;
 yard.group.updateMatrixWorld(true);const holder=new THREE.Group();holder.add(anonymous);view.scene=new THREE.Group();view.scene.add(yard.group,holder);
 const hit=createPointSnap(view,()=>plan).pick(event([55,0,.3],1,0));assert.equal(hit.anchor?.host.id,'patio');assert.equal(hit.vertex,true);
 holder.removeFromParent();view.scene=yard.group;console.log('ok nearby stable host and vertex preference');
}
// A wall vertex below the coping, viewed from outside, also names the spa.
{
 const p=[18,13,1.18],target=point(p);camera.position.copy(target).add(new THREE.Vector3(3,1,-3));camera.up.set(0,1,0);camera.lookAt(target);camera.updateMatrixWorld(true);
 const hit=real.pick(event(p));assert.ok(hit);assert.equal(hit.anchor?.host.kind,'spa');assert.equal(hit.anchor.host.id,'spa');
 frameChecks.push({plan,anchor:hit.anchor,at:hit.at});console.log('ok generated spa wall anchor');
}
// Real spillover geometry is present, but cannot steal the coping corner.
let water=0;yard.group.traverse(o=>{if(o.isMesh&&o.material.name==='water')water++;});assert.ok(water>0);
aim([18,13,1.33]);const rim=real.pick(event([18,13,1.33],1,1));near(rim.at,[18,13,1.33]);assert.equal(rim.anchor.host.kind,'spa');
{
 const onlyWater=new THREE.Group();yard.group.traverse(o=>{if(o.isMesh&&o.material.name==='water')onlyWater.add(o.clone());});onlyWater.scale.setScalar(.3048);view.scene=onlyWater;
 assert.equal(createPointSnap(view,()=>plan).pick(event([18,13,1.33])),null,'water and spillovers alone never lock');view.scene=yard.group;
}
// Cached world features invalidate only for geometry/transform changes.
{
 let rebuilt=0,changed=null;view.scene=scene;camera.position.set(0,12,10);camera.up.set(0,1,0);camera.lookAt(0,0,0);camera.updateMatrixWorld(true);
 const cached=createPointSnap(view,()=>({}),{onFeatures:mesh=>{rebuilt++;changed=mesh;}});
 cached.pick({clientX:720,clientY:450});const n=rebuilt;assert.ok(n>0&&n<300,'far meshes rejected before feature building');cached.pick({clientX:720,clientY:450});assert.equal(rebuilt,n);
 changed.position.y+=.01;cached.pick({clientX:720,clientY:450});assert.equal(rebuilt,n+1);
 geometry.attributes.position.needsUpdate=true;cached.pick({clientX:720,clientY:450});assert.equal(rebuilt,2*n+1);
 console.log('ok feature seam: second pick reuses, mesh transform and shared geometry edits invalidate');
}
// The sampled ground occludes buried edges without ever becoming a lock.
{
 view.scene=new THREE.Group();const solid=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),material),lawn=new THREE.Mesh(new THREE.PlaneGeometry(20,20,30,30).rotateX(-Math.PI/2),material);
 solid.position.set(0,-1,0);lawn.userData.terrain=true;view.scene.add(solid,lawn);aim([0,0,-.5/.3048]);
 const target=[.5/.3048,-.5/.3048,-.5/.3048],snap=createPointSnap(view,()=>({}));assert.equal(snap.pick(event(target)),null);
 lawn.visible=false;assert.ok(snap.pick(event(target)),'terrain visibility respected');lawn.visible=true;solid.position.y=1;
 aim([0,0,1.5/.3048]);assert.ok(snap.pick(event([.5/.3048,-.5/.3048,1.5/.3048])),'previous occlusion cannot poison the next pick');
 console.log('ok cached terrain occludes below-ground locks, respects visibility, and never supplies features');
}
// House owners survive the same real generator and material batching.
{
 const {buildTwin}=await import(file('static/twin/twin_generator.js'));
 const b={id:'house',position:[0,0],rotation:0,base:0,levels:[{id:'L1',elevation:0,ceiling:9,outline:[[0,0],[10,0],[10,10],[0,10]]}],
 joints:[{id:'a',at:[0,0]},{id:'b',at:[10,0]}],walls:[{id:'wall',level:'L1',joints:['a','b'],from:[0,0],to:[10,0],height:9,thickness:.5,exterior:true}],rooms:[],openings:[],stairs:[],anchors:[],
 roof:{sections:[{id:'roof',kind:'shed',rect:[0,0,10,10],plate:9,pitch:2,overhang:0,low_side:'y0'}]},
 fixtures:[{id:'table',kind:'table',level:'L1',rect:[20,0,24,4],height:3}],items:[{id:'table',asset:'missing-test-asset',host:{ground:true,at:[22,2]},rotation:0}]};
 const housePlan={units:'ft',materials:{},buildings:[b],site:{terraces:[]}},twin=buildTwin(housePlan,input.kit,'low');await twin.ready;view.scene=twin.root;
 for(const [kind,id] of [['wall','wall'],['roof','roof'],['item','table']]) {
  let target=null;twin.root.updateMatrixWorld(true);
  twin.root.traverse(o=>{
   if(!o.isMesh||o.layers.isEnabled(31))return;
   const ranges=o.geometry.userData.snapRanges || [{start:0,count:o.geometry.index?.count||o.geometry.attributes.position.count,...o.userData}];
   for(const r of ranges)if(r.kind===kind&&r.pieceId===id) {
    const pos=o.geometry.attributes.position;
    for(let i=r.start;i<r.start+r.count;i++) {
     const v=new THREE.Vector3().fromBufferAttribute(pos,o.geometry.index?o.geometry.index.getX(i):i).applyMatrix4(o.matrixWorld);
     if(!target||v.y>target.y)target=v;
    }
   }
  });
  assert.ok(target,kind+' render identity');
  // Isolate the owner's render meshes so another roof face cannot cover a wall edge.
  const isolated=new THREE.Group();twin.root.traverse(o=>{if(o.isMesh&&!o.layers.isEnabled(31)&&((o.userData.kind===kind&&o.userData.pieceId===id)||o.geometry.userData.snapRanges?.some(r=>r.kind===kind&&r.pieceId===id))) {
   const m=o.clone();m.matrix.copy(o.matrixWorld);m.matrixAutoUpdate=false;isolated.add(m);
  }});view.scene=isolated;
  camera.position.copy(target).add(new THREE.Vector3(2,8,3));camera.up.set(0,1,0);camera.lookAt(target);camera.updateMatrixWorld(true);
  const p=[target.x/.3048,-target.z/.3048,target.y/.3048],hit=createPointSnap(view,()=>housePlan).pick(event(p));
  assert.ok(hit,kind);assert.equal(hit.anchor?.host.kind,kind);assert.equal(hit.anchor.host.id,id);assert.equal(hit.anchor.host.building,'house');
  frameChecks.push({plan:housePlan,anchor:hit.anchor,at:hit.at});console.log(`ok real generated ${kind} edge anchors to house/${id}`);
 }
}
}
console.log('FRAME_CHECKS '+JSON.stringify(frameChecks));
console.log('Passed: performance/cache, generated yard/house owners, source filtering, host priority and terrain occlusion');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit, 'baseline': '--baseline' in sys.argv})
    lines = output.splitlines()
    print('\n'.join(line for line in lines if not line.startswith('FRAME_CHECKS ')))
    if not code:
        sys.path.insert(0, str(ROOT))
        from services.twin_fixtures import _anchor_frame, _anchor_transform
        frames = json.loads(next(line[13:] for line in lines if line.startswith('FRAME_CHECKS ')))
        for check in frames:
            frame = _anchor_frame(check['plan'], check['anchor']['host'])
            assert frame, check
            point = _anchor_transform(check['anchor']['local'], frame[1])
            assert all(abs(a-b) < 1e-6 for a, b in zip(point, check['at'])), check
        print(f'ok FRAME_CHECKS real generated geometry matches server: {len(frames)}/{len(frames)}')
    sys.exit(code or 0)
