"""Security attention, camera direction, occluded cones and existing refusal/confirm controls."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin_live_node_rig import run  # noqa: E402
from services.twin_model_bridge import assemble, flatten  # noqa: E402

DRIVER = r"""
const {securityAttention,securityItem,cameraDirection,mountSecurity}=await import(file('static/twin/live/security.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {buildingGround}=await import(file('static/twin/twin_ground.js'));
const checks=[],check=(n,f)=>checks.push([n,f]);
check('unlocked/open loud, resting locked/closed quiet',()=>{
 for(const [kind,id,on,off,dc] of [['lock','lock.d','unlocked','locked'],['sensor','binary_sensor.d','on','off','door'],['sensor','binary_sensor.w','on','off','window'],['garage','cover.g','open','closed','garage']]){
 const row={kind,entity_id:id};assert.equal(securityAttention(row,{state:on,attributes:{device_class:dc}}),true);assert.equal(securityAttention(row,{state:off,attributes:{device_class:dc}}),false);
 assert.equal(securityAttention(row,{state:'unavailable'}),false);}
 assert.equal(securityAttention({kind:'light',entity_id:'light.a'},{state:'on'}),false);
});
check('foreground includes contacts, garage, alarm, cameras',()=>{
 for(const kind of ['lock','garage','alarm','camera'])assert.equal(securityItem({kind},{}),true);
 assert.equal(securityItem({kind:'sensor',entity_id:'binary_sensor.x'},{attributes:{device_class:'window'}}),true);
 assert.equal(securityItem({kind:'sensor',entity_id:'sensor.x'},{attributes:{device_class:'temperature'}}),false);
});
check('placed camera facing wins; indoor points to room; outdoor away',()=>{
 assert.deepEqual(cameraDirection({at:[2,3,5],facing_deg:0,room:'r'},[0,0],[0,0]),[1,0]);
 const rotated=cameraDirection({at:[2,3,5],orientation:90},null,[0,0]);assert.ok(Math.abs(rotated[0])<1e-6);assert.equal(rotated[1],1);
 assert.deepEqual(cameraDirection({at:[10,0,5],room:'r'},[0,0],[20,0]),[-1,0]);
 assert.deepEqual(cameraDirection({at:[10,0,5]},null,[0,0]),[1,0]);
 assert.deepEqual(cameraDirection({at:[10,0,5],room:'r',outdoor:true},[0,0],[0,0]),[1,0]);
});
check('mounted mode updates red emphasis and alarm legend then cleans up',async()=>{
 const t=await rig({devices:[{device_id:'door',name:'Back door',entity_id:'lock.back',kind:'lock',state:'unlocked'},
 {device_id:'contact',name:'Window',entity_id:'binary_sensor.window',kind:'sensor',state:'on',attributes:{device_class:'window'}},
 {device_id:'alarm',name:'Alarm',entity_id:'alarm_control_panel.a',kind:'alarm',state:'armed_home'},
 {device_id:'light',name:'Light',entity_id:'light.a',kind:'light',state:'on'}]});
 try{t.live.setMode('security');const red=[];t.view.scene.traverse(o=>{if(o.userData.securityAttention)red.push(o);});
 assert.equal(red.filter(o=>o.visible).length,2);assert.match(document.getElementById('twin-mode-legend').textContent,/armed home/);
 assert.equal(t.live.marker('door').dim,false);assert.equal(t.live.marker('light').dim,false);assert.equal(t.sprite('light').visible,false);
 t.states['lock.back'].state='locked';t.states['binary_sensor.window'].state='off';await t.live.refresh();assert.equal(red.filter(o=>o.visible).length,0);
 t.live.setMode('all');assert.equal(red.filter(o=>o.visible).length,0);
 }finally{t.cleanup();}assert.equal(t.view.scene.children.filter(o=>o.children.some(c=>c.userData.securityAttention)).length,0);
});
check('unoffered camera keeps 25 foot cone and existing refusal',async()=>{
 const t=await rig({devices:[{device_id:'camera',name:'Camera',entity_id:'camera.k',kind:'camera',state:'idle',offered:false}]});
 try{t.live.setMode('security');let cone;t.view.scene.traverse(o=>{if(o.userData.cameraCone)cone=o;});assert.ok(cone.visible);assert.equal(cone.userData.cameraCone.length_ft,25);
 await t.tap('camera');assert.equal(t.serviceCalls().length,0);assert.ok(document.querySelector('[data-ring]'));t.live.setMode('all');assert.equal(cone.visible,true);
 t.live.toggleMode('security');assert.equal(cone.visible,false);t.live.toggleMode('security');assert.equal(cone.visible,true);
 }finally{t.cleanup();}
});
check('Security lock tap retains unsafe confirmation',async()=>{
 const t=await rig({devices:[{device_id:'door',name:'Back door',entity_id:'lock.back',kind:'lock',state:'locked'}]});
 try{t.live.setMode('security');await t.tap('door');const button=[...document.querySelector('[data-ring]').querySelectorAll('button')].find(b=>/unlock/i.test(b.textContent));assert.ok(button);t.confirm=false;await press(button);assert.equal(t.confirms.length,1);assert.equal(t.serviceCalls().length,0);}finally{t.cleanup();}
});
check('cones stop at blocking wall, never self-hit mount wall, and use faint depth-tested materials',()=>{
 const scene=new THREE.Scene(),canvas=new El('canvas'),host=new El('main');host.append(canvas);
 // Mount wall at x = 0 (face at x = 0.25 ft), blocking wall at x = 10 ft (thickness 0.5 ft -> face at 9.75 ft).
 const mountWall=new THREE.Mesh(new THREE.BoxGeometry(.5*FT,30*FT,40*FT),new THREE.MeshStandardMaterial({name:'siding'}));
 mountWall.position.set(0,5*FT,0);scene.add(mountWall);
 const blockWall=new THREE.Mesh(new THREE.BoxGeometry(.5*FT,30*FT,40*FT),new THREE.MeshStandardMaterial({name:'interior_wall'}));
 blockWall.position.set(10*FT,5*FT,0);scene.add(blockWall);
 const marker={kind:'camera',device_id:'cam1',entity_id:'camera.wall',at:[.25,0,5],building:null,facing_deg:0};
 const layout={markers:[marker],rooms:[],camera_views:{'camera.wall':{aim:[25.25,0,5],fov_deg:60}}};
 const view={scene,renderer3:{domElement:canvas},plan:{buildings:[],site:{}}};
 const live={layout:()=>layout,stale:()=>false,state:()=>({state:'idle'}),peek:()=>({})};
 const layer=mountSecurity({view,live});
 try{
  layer.update('security');
  const cone=layer.warmObjects().find(o=>o.userData.cameraCone);
  assert.ok(cone&&cone.visible);
  const rim=cone.children[0],fill=cone.children[1];
  assert.equal(rim.isLineSegments,true);assert.equal(fill.isMesh,true);
  for(const m of [rim.material,fill.material]){
   assert.equal(m.depthTest,true);assert.equal(m.depthWrite,false);assert.equal(m.toneMapped,false);assert.equal(m.fog,false);
  }
  assert.ok(fill.material.opacity>0&&fill.material.opacity<0.05,`fill opacity ${fill.material.opacity}`);
  assert.ok(rim.material.opacity>fill.material.opacity,'rim stronger than fill');
  const pos=fill.geometry.attributes.position,origin=new THREE.Vector3(.25*FT,5*FT,0);
  let maxX=-Infinity,maxDist=0;
  for(let i=1;i<pos.count;i++){
   const p=new THREE.Vector3().fromBufferAttribute(pos,i);
   maxX=Math.max(maxX,p.x);maxDist=Math.max(maxDist,p.distanceTo(origin));
  }
  assert.ok(maxDist>8*FT,`camera must not self-hit its mount wall (maxDist=${(maxDist/FT).toFixed(2)} ft)`);
  assert.ok(maxX<=9.76*FT,`cone must stop at the blocking wall at 9.75 ft (maxX=${(maxX/FT).toFixed(2)} ft)`);
 }finally{layer.stop();}
});
check('length cap, fov angle, swaying-plant exclusion, and rebuild only on aim/house change (not per frame)',()=>{
 const scene=new THREE.Scene(),canvas=new El('canvas'),host=new El('main');host.append(canvas);
 // Add a swaying plant and grass right in front of the camera: must NOT occlude the cone.
 const plant=new THREE.Mesh(new THREE.BoxGeometry(2,4,4),new THREE.MeshStandardMaterial({name:'leaves'}));
 plant.userData.yardPart='plants';plant.position.set(5*FT,5*FT,0);scene.add(plant);
 const grass=new THREE.Mesh(new THREE.BoxGeometry(2,4,4),new THREE.MeshStandardMaterial({name:'lawn'}));
 grass.userData.yardGrass=true;grass.position.set(6*FT,5*FT,0);scene.add(grass);
 const marker={kind:'camera',device_id:'cam2',entity_id:'camera.open',at:[0,0,5],building:null};
 const camView={aim:[15,0,5],fov_deg:40};
 const layout={markers:[marker],rooms:[],camera_views:{'camera.open':camView}};
 const view={scene,renderer3:{domElement:canvas},plan:{buildings:[],site:{}}};
 const live={layout:()=>layout,stale:()=>false,state:()=>({state:'idle'}),peek:()=>({})};
 const layer=mountSecurity({view,live});
 try{
  const cone=layer.warmObjects().find(o=>o.userData.cameraCone);
  assert.equal(cone.userData.cameraCone.rebuilds,1);
  assert.equal(cone.userData.cameraCone.hits,0,'swaying plants and grass must not clip the cone');
  const measure=(axisVec,expectedLenFt,expectedHalfDeg)=>{
   const pos=cone.children[1].geometry.attributes.position,origin=new THREE.Vector3(0,5*FT,0);
   let maxDist=0,maxAngle=0;
   for(let i=1;i<pos.count;i++){
    const v=new THREE.Vector3().fromBufferAttribute(pos,i).sub(origin);
    const d=v.length();maxDist=Math.max(maxDist,d);
    if(d>1e-5)maxAngle=Math.max(maxAngle,Math.acos(Math.max(-1,Math.min(1,v.dot(axisVec)/d)))*180/Math.PI);
   }
   assert.ok(Math.abs(maxDist-expectedLenFt*FT)<1e-3,`length cap ${maxDist/FT} vs ${expectedLenFt}`);
   assert.ok(Math.abs(maxAngle-expectedHalfDeg)<.5,`fov half-angle ${maxAngle} vs ${expectedHalfDeg}`);
  };
  measure(new THREE.Vector3(1,0,0),15,20);
  // Repeated updates with unchanged aim do NOT rebuild; there is no per-frame draw().
  assert.equal(typeof layer.draw,'undefined','no per-frame draw raycasting');
  for(let i=0;i<10;i++)layer.update('security');
  assert.equal(cone.userData.cameraCone.rebuilds,1,'unchanged aim must not rebuild');
  // Changing aim + fov triggers one rebuild.
  camView.aim=[0,20,5];camView.fov_deg=120;
  layer.update('security');
  assert.equal(cone.userData.cameraCone.rebuilds,2,'aim/fov change rebuilds cone');
  measure(new THREE.Vector3(0,0,-1),20,60);
  // House rebuild event triggers rebuild against updated geometry.
  const wall=new THREE.Mesh(new THREE.BoxGeometry(20*FT,12*FT,.5*FT),new THREE.MeshStandardMaterial({name:'siding'}));
  wall.position.set(0,6*FT,-8*FT);scene.add(wall);
  host.dispatchEvent(new Event('twinrebuilt'));
  assert.equal(cone.userData.cameraCone.rebuilds,3,'twinrebuilt rebuilds cones');
  assert.ok(cone.userData.cameraCone.hits>0,'newly built wall now clips the cone');
 }finally{layer.stop();}
});
check('real household fixture: indoor pool-house camera clips inside room and never pokes through roof',async()=>{
 const plan=config.household_plan;
 const twin=buildTwin(plan,{materials:{}},'high',{viewing:true});
 await twin.ready;
 const scene=new THREE.Scene();scene.add(twin.root);
 const canvas=new El('canvas'),host=new El('main');host.append(canvas);
 const b=plan.buildings.find(x=>x.id==='pool-house')||plan.buildings[0];
 const room=b.rooms.find(r=>r.polygon?.length>=3&&r.level===b.levels[0].id)||b.rooms[0];
 const cx=room.polygon.reduce((s,p)=>s+p[0],0)/room.polygon.length;
 const cy=room.polygon.reduce((s,p)=>s+p[1],0)/room.polygon.length;
 const ang=(b.rotation||0)*Math.PI/180,base=buildingGround(plan,b);
 const wx=(b.position?.[0]||0)+cx*Math.cos(ang)-cy*Math.sin(ang);
 const wy=(b.position?.[1]||0)+cx*Math.sin(ang)+cy*Math.cos(ang);
 const ceiling=(b.levels.find(l=>l.id===room.level)?.ceiling||9);
 // Compute building's world bounding box to prove the indoor cone stays inside it.
 scene.updateMatrixWorld(true);
 const bBox=new THREE.Box3();
 twin.root.traverse(o=>{if(o.isMesh&&!o.layers.isEnabled(31)&&o.visible)bBox.expandByObject(o);});
 // Place a 40 ft cone indoors near the ceiling aiming upward-diagonally toward the roof/walls.
 const marker={kind:'camera',device_id:'real-indoor',entity_id:'camera.real_indoor',at:[wx,wy,ceiling-1],building:b.id,room:room.id};
 const layout={markers:[marker],rooms:[],camera_views:{'camera.real_indoor':{aim:[wx+35,wy+15,ceiling+12],fov_deg:90}}};
 const view={scene,groups:twin.groups,renderer3:{domElement:canvas},plan};
 const live={layout:()=>layout,stale:()=>false,state:()=>({state:'idle'}),peek:()=>({})};
 const layer=mountSecurity({view,live});
 try{
  const cone=layer.warmObjects().find(o=>o.userData.cameraCone);
  const meta=cone.userData.cameraCone;
  assert.equal(meta.rays,289);assert.equal(meta.triangles,576);
  assert.ok(meta.occluderTris>500,'real household geometry indexed');
  assert.ok(meta.hits===meta.rays,`indoor camera aimed at roof/walls must clip every ray (${meta.hits}/${meta.rays})`);
  const pos=cone.children[1].geometry.attributes.position;
  const ceilingY=(base+ceiling)*FT;
  let maxY=-Infinity;
  for(let i=0;i<pos.count;i++)maxY=Math.max(maxY,pos.getY(i));
  assert.ok(maxY<=bBox.max.y+.05,`indoor cone must not poke out above roof (${maxY.toFixed(2)} vs ${bBox.max.y.toFixed(2)})`);
  assert.ok(maxY<=ceilingY+.35,`indoor cone stops at room ceiling/roof (${(maxY/FT).toFixed(2)} ft vs ${(ceilingY/FT).toFixed(2)} ft)`);
 }finally{layer.stop();}
});
let failed=0;for(const[n,f]of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);console.log(`${checks.length-failed}/${checks.length} security checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    household_plan = flatten(assemble(fixture)[0])
    sys.exit(run(DRIVER, {'household_plan': household_plan}))
