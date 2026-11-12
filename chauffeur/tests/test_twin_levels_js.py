"""Viewer level acceptance on the mounted view; no browser or GPU."""
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node
ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const T = await import('three');
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {LEVEL_TUNING:C, roomNeighbour, deviceAtLevel} = await import(file('static/twin/levels.js'));
let clock=1000;Object.defineProperty(performance,'now',{value:()=>clock});
const settle=v=>{clock+=401;tick();v.render();clock+=401;tick();v.render();};
const rect=(x,y,w,h)=>[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
const outline=rect(0,0,30,20);
function building(id,position=[0,0],two=true){
 const levels=[{id:'L1',name:'1st floor',elevation:0,ceiling:10,outline},...(two?[{id:'L2',name:'2nd floor',elevation:10,ceiling:10,outline}]:[])];
 return {id,name:id==='main'?'Main House':id,position,levels,
 walls:levels.flatMap(l=>outline.map((p,i)=>({id:l.id+'w'+i,level:l.id,from:p,to:outline[(i+1)%4],height:10,thickness:.5,exterior:true}))),
 rooms:[{id:'kitchen',name:'Kitchen',level:'L1',polygon:rect(15,0,15,20)},{id:'hall',name:'Hall',level:'L1',polygon:rect(0,0,15,20)},
 ...(two?[{id:'bed',name:'Bedroom',level:'L2',polygon:outline}]:[])],openings:[],lights:[],
 roof:{sections:[{id:'roof',rect:[0,0,30,20],plate:two?20:10,pitch:8,kind:'gable',ridge:'x',overhang:0}]}};
}
async function mounted(list=[building('main'),building('annex',[50,0],false)]){
 const host=new Element();document.body.append(host);
 return mountTwin(host,{plan:{buildings:list,site:{},materials:{}},kit:{materials:{}},tier:'low',bake:false});
}
const pose=v=>({position:v.camera.position.toArray(),target:v.controls.target.toArray(),state:v.levels.snapshot()});
await test('mounted transitions both directions and top-down blends inside the ease',async()=>{
 const v=await mounted();try{
  const l=v.levels;assert.equal(l.snapshot().level,'house');assert.equal(v.controls.enablePan,false);
  l.go({building:'main'});settle(v);assert.equal(l.snapshot().level,'building');assert.equal(v.controls.enableRotate,true);
  const start=v.camera.position.clone();l.go({building:'main',floor:'L1'});clock+=200;tick();
  assert.ok(start.distanceTo(v.camera.position)>.1);assert.equal(v.cameraTransition,true);
  settle(v);assert.equal(l.snapshot().level,'floor');assert.equal(v.controls.enableRotate,false);
  const axis=v.camera.position.clone().sub(v.controls.target).normalize();assert.ok(axis.y>.9999);
  assert.equal(v.groups.levels['main:L2'].visible,false);assert.equal(v.groups.levels['annex:L1'].visible,true);
  l.go({building:'main',room:'kitchen'});settle(v);assert.equal(l.snapshot().room,'kitchen');
  l.up();settle(v);assert.equal(l.snapshot().level,'floor');l.up();settle(v);assert.equal(l.snapshot().level,'building');
  l.up();settle(v);assert.equal(l.snapshot().level,'house');assert.equal(v.groups.roof.visible,true);
 }finally{v.dispose();}
});
await test('one building omits House, one floor skips icons but every room remains reachable',async()=>{
 const v=await mounted([building('only',[0,0],false)]);try{
  assert.equal(v.levels.snapshot().level,'floor');assert.deepEqual(v.levels.path().map(p=>p.text),['only','1st floor']);
  assert.equal(document.querySelectorAll('.twin-level-targets button').filter(b=>shown(b)).length,0);
  v.levels.go({building:'only',room:'kitchen'});settle(v);v.levels.up();settle(v);
  assert.equal(v.levels.snapshot().level,'floor');assert.equal(v.levels.up(),false);
 }finally{v.dispose();}
 const w=await mounted([building('only')]);try{assert.equal(w.levels.snapshot().level,'building');w.levels.down();settle(w);assert.equal(w.levels.snapshot().floor,'L1');}finally{w.dispose();}
});
await test('zoom commit, bounded zoom, spring-back and no room at pinch centre',async()=>{
 const v=await mounted();try{
  const l=v.levels;assert.equal(l.zoomEnd(.95),'stay');assert.equal(l.zoomEnd(.75),'spring');settle(v);
  assert.equal(l.snapshot().level,'house');assert.equal(l.zoomEnd(.65),'down');settle(v);
  l.go({building:'main'},{immediate:true});assert.equal(l.zoomEnd(.65),'down');settle(v);assert.equal(l.snapshot().level,'floor');
  const oldPick=v.pick,oldFloor=v.floorAt;v.pick=()=>null;v.floorAt=()=>[100,100];
  assert.equal(l.zoomEnd(.6,[700,450]),'spring');settle(v);assert.equal(l.snapshot().level,'floor');
  v.pick=()=>({kind:'room',building:'main',id:'kitchen'});assert.equal(l.zoomEnd(.6,[700,450]),'down');settle(v);
  assert.equal(l.snapshot().room,'kitchen');assert.equal(l.zoomEnd(1.5),'up');settle(v);assert.equal(l.snapshot().level,'floor');
  assert.equal(l.zoomEnd(1.5),'up');settle(v);assert.equal(l.snapshot().level,'building');
  v.pick=oldPick;v.floorAt=oldFloor;
 }finally{v.dispose();}
});
await test('room neighbours use cone, nearest centroid, shared wall tie and ignore no neighbour',()=>{
 const room=(id,p,level='L1')=>({id,polygon:p,level});
 const from=room('from',rect(0,0,10,10));
 const nearest=room('near',rect(10,0,10,10)),far=room('far',rect(30,0,10,10)),outside=room('outside',rect(1,20,10,10));
 assert.equal(roomNeighbour([from,far,nearest,outside],'from',[1,0]).id,'near');
 assert.equal(roomNeighbour([from,outside],'from',[1,0]),null);
 assert.equal(roomNeighbour([from,room('upstairs',rect(10,0,10,10),'L2')],'from',[1,0]),null);
 const little=room('little',rect(10,4,10,2)); // same centroid and distance, 2ft shared edge
 assert.equal(roomNeighbour([from,little,nearest],'from',[1,0]).id,'near');
 assert.equal(roomNeighbour([from,nearest],'from',[-1,0]),null);
 const boundary=room('diagonal',rect(10,10,10,10));assert.equal(roomNeighbour([from,boundary],'from',[1,0]).id,'diagonal');
});
await test('room swipe follows screen direction on rotated buildings, Floor ignores drag',async()=>{
 const b=building('main');b.rotation=90;const v=await mounted([b]);try{
  v.levels.go({building:'main',room:'kitchen'},{immediate:true});
  assert.equal(v.levels.swipe(0,80),true);settle(v);assert.equal(v.levels.snapshot().room,'hall');
  assert.equal(v.levels.swipe(0,80),false);assert.equal(v.levels.swipe(2,2),false);
  v.levels.up();settle(v);const before=pose(v);assert.equal(v.levels.swipe(80,0),false);assert.deepEqual(pose(v),before);
 }finally{v.dispose();}
});
await test('attention is visible at every level; ordinary devices only inside the selected room',()=>{
 const row={building:'main',room:'kitchen',look:'off'};
 for(const level of ['house','building','floor','room']){
  const s={level,building:'main',floor:'L1',room:'kitchen'};
  assert.equal(deviceAtLevel(s,row),level==='room');assert.equal(deviceAtLevel(s,{...row,look:'attention'}),true);
  assert.equal(deviceAtLevel(s,{...row,building:'annex'}),false);
 }
});
await test('path chip text and actual button jumps',async()=>{
 const v=await mounted();try{
  v.levels.go({building:'main',room:'bed'},{immediate:true});
  assert.equal(textOf(document.getElementById('twin-path')),'House \u203a Main House \u203a 2nd floor \u203a Bedroom');
  await click(document.querySelector('[data-path-level="floor"]'));settle(v);assert.equal(v.levels.snapshot().floor,'L2');
  await click(document.querySelector('[data-path-level="building"]'));settle(v);assert.equal(v.levels.snapshot().level,'building');
  await click(document.querySelector('[data-path-level="house"]'));settle(v);assert.equal(v.levels.snapshot().level,'house');
 }finally{v.dispose();}
});
await test('actual building and floor icon buttons navigate without HA; textures are cached',async()=>{
 const v=await mounted();try{
  await click(document.querySelector('[data-level-building="main"]:not([data-level-floor])'));settle(v);
  assert.equal(v.levels.snapshot().level,'building');
  await click(document.querySelector('[data-level-building="main"][data-level-floor="L1"]'));settle(v);
  assert.equal(v.levels.snapshot().level,'floor');
  const sprites=v.scene.getObjectByName('level-targets').children;const floor=sprites.filter(o=>o.material.map===sprites[1].material.map);
  assert.ok(floor.length>=3,'all floors share the cached texture');
 }finally{v.dispose();}
});
await test('level round trips retain every geometry and material identity',async()=>{
 const v=await mounted();try{
  const before=[];v.scene.traverse(o=>{if(o.geometry||o.material)before.push([o,o.geometry,o.material]);});
  for(let i=0;i<2;i++)for(const state of [{building:'main'},{building:'main',floor:'L1'},{building:'main',room:'kitchen'},{building:'main',floor:'L2'},{level:'house'}]){v.levels.go(state);settle(v);}
  before.forEach(([o,g,m])=>{assert.equal(o.geometry,g);assert.equal(o.material,m);});
 }finally{v.dispose();}
});
finish();
"""
BOOT = PRELUDE + r"""
// A wall template has neither settings nor time controls. Execute the actual
// swallowed-exception entry point, not merely mountTwin or a source search.
for(const id of ['twin-canvas','twin-status','twin-tier','twin-glance-home','twin-controls','twin-idle','twin-idle-clock','twin-idle-next','twin-idle-weather']){
 const node=new Element();node.id=id;node.style.setProperty=()=>{};document.body.append(node);
}
document.getElementById=id=>document.querySelector('#'+id);
location.search='?test=1&tier=low&panel=true&kiosk=true';
const outline=[[0,0],[30,0],[30,20],[0,20]],b={id:'b',name:'House',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:8,outline}],
 rooms:[{id:'r',name:'Room',level:'L1',polygon:outline}],walls:[],openings:[],lights:[],roof:{sections:[]}};
globalThis.fetch=async path=>String(path).endsWith('api/house/twin')?{ok:true,json:async()=>({plan:{buildings:[b],site:{},materials:{}},kit_id:'kit'})}
 :String(path).includes('api/house/twin/kit/')?{ok:true,json:async()=>({materials:{}})}:{ok:false,status:503,json:async()=>({available:false})};
await import(file('static/twin/twin_view.js'));
await new Promise(resolve=>setTimeout(resolve,50));
await test('actual wall boot survives absent drawer, absent HA and starts idle/glance/navigation',()=>{
 assert.equal(document.getElementById('twin-status').hidden,true,document.getElementById('twin-status').textContent);
 assert.equal(window.__twin?.ready,true);assert.ok(window.__twin.idle);assert.ok(window.__twin.glance);
 assert.equal(window.__twin.levels.snapshot().level,'floor');assert.equal(document.getElementById('twin-time-preview'),null);
});
window.dispatchEvent(new Event('pagehide'));finish();
"""
GESTURES = r"""
const {OrbitControls} = await import('three/addons/controls/OrbitControls.js');
const {createLevels,LEVEL_TUNING:C} = await import(file('static/twin/levels.js'));
const t=await rig({devices:[{device_id:'a',name:'Lamp',kind:'light',entity_id:'light.a',state:'off',at:[0,0,2]}]});
const outline=[[-40,-10],[40,-10],[40,20],[-40,20]];
t.view.plan.buildings[0].levels.push({id:'L2',elevation:10,ceiling:9,outline});
t.view.plan.buildings[0].levels[0].outline=outline;
t.view.plan.buildings[0].rooms=[{id:'r',level:'L1',polygon:[[0,-10],[40,-10],[40,20],[0,20]]},{id:'left',level:'L1',polygon:[[-40,-10],[0,-10],[0,20],[-40,20]]}];
t.view.plan.buildings.push({...structuredClone(t.view.plan.buildings[0]),id:'annex',position:[100,0]});
t.camera.up.set(0,1,0);t.view.state={view:'ext'};
t.view.controls=new OrbitControls(t.camera,t.canvas);
t.view.levels=createLevels(t.view,{host:t.host,visibility:key=>{t.view.state.view=key;}});
const l=t.view.levels, controls=t.view.controls;
let passed=0,total=0;
async function check(name,fn){total++;try{await fn();passed++;console.log('  ok   '+name);}catch(e){console.error('  FAIL '+name,e);}}
const wheel=deltaY=>t.canvas.dispatchEvent(new MouseEvent('wheel',{bubbles:true,cancelable:true,clientX:700,clientY:500,deltaY,deltaMode:0}));
const pointer=(type,id,x,y)=>t.canvas.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,pointerId:id,pointerType:'touch',isPrimary:id===1,clientX:x,clientY:y,pageX:x,pageY:y,button:0}));
await check('real OrbitControls wheel springs below threshold then commits down and up',async()=>{
 l.go({building:'b'},{immediate:true});const fitted=l.distance();
 wheel(-400);await wait(650);assert.equal(l.snapshot().level,'building');
 assert.ok(Math.abs(t.camera.position.distanceTo(controls.target)/fitted-.85)<.001);
 l.go({building:'b'},{immediate:true});wheel(-1000);await wait(650);assert.equal(l.snapshot().level,'floor');
 wheel(1000);await wait(650);assert.equal(l.snapshot().level,'building');
});
await check('real touch pinch commits once at gesture end and retains OrbitControls',async()=>{
 l.go({building:'b'},{immediate:true});
 pointer('pointerdown',1,650,500);pointer('pointerdown',2,750,500);
 pointer('pointermove',1,580,500);pointer('pointermove',2,820,500);
 assert.equal(l.snapshot().level,'building');
 pointer('pointerup',2,820,500);pointer('pointerup',1,580,500);await wait(450);
 assert.equal(l.snapshot().level,'floor');assert.equal(t.view.controls,controls);assert.equal(controls.enablePan,false);
});
await check('House drag orbits without pan and Floor drag leaves the pose unchanged',async()=>{
 l.go({level:'house'},{immediate:true});const start=t.camera.position.clone(),target=controls.target.clone();
 const mouse=(type,x,y)=>t.canvas.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,pointerType:'mouse',pointerId:8,clientX:x,clientY:y,pageX:x,pageY:y,button:0}));
 mouse('pointerdown',700,500);mouse('pointermove',800,520);mouse('pointerup',800,520);
 assert.ok(start.distanceTo(t.camera.position)>.01);assert.ok(target.equals(controls.target));
 l.go({building:'b',floor:'L1'},{immediate:true});const before=t.camera.position.clone();
 mouse('pointerdown',700,500);mouse('pointermove',800,520);mouse('pointerup',800,520);
 assert.ok(before.equals(t.camera.position));assert.equal(l.snapshot().level,'floor');
});
await check('real Room swipe snaps left and a swipe past the edge is ignored',async()=>{
 l.go({building:'b',room:'r'},{immediate:true});
 pointer('pointerdown',1,700,500);pointer('pointermove',1,600,500);pointer('pointerup',1,600,500);await wait(450);
 assert.equal(l.snapshot().room,'left');
 const before=t.camera.position.clone();
 pointer('pointerdown',1,700,500);pointer('pointermove',1,600,500);pointer('pointerup',1,600,500);await wait(450);
 assert.equal(l.snapshot().room,'left');assert.ok(before.equals(t.camera.position));assert.equal(t.calls.length,0);
});
l.stop();controls.dispose();t.cleanup();assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${passed}/${total} real-control gesture checks passed`);process.exit(passed===total?0:1);
"""
if __name__ == '__main__':
    from twin_live_node_rig import run
    code,out=run_node(DRIVER,{'root':ROOT.as_posix()},timeout=280)
    print(out)
    boot_code,boot_out=run_node(BOOT,{'root':ROOT.as_posix()},timeout=280)
    print(boot_out)
    gestures=run(GESTURES, prefix='chauffeur_levels_gestures_',timeout=280)
    sys.exit(code or boot_code or gestures or 0)
