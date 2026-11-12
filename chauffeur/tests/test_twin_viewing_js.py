"""Execute viewing math, generated cuts and mounted twin in Node, using real r187 keys.

No GPU is faked as proof of compilation: the key test executes WebGLPrograms'
actual getParameters/getProgramCacheKey. The live companion counts createProgram.
Run from chauffeur/, with HA_BASE_URL unset; no Chromium is launched here.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
// Export the vendored renderer's private key calculator for this test only.
registerHooks({load(url,ctx,next) {
  if(url.endsWith('three.module.js?viewing-keys')) return {format:'module',shortCircuit:true,
    source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms};'};
  return next(url,ctx);
}});
const {WebGLPrograms} = await import(file('static/vendor/three-r187/three.module.js')+'?viewing-keys');
const OriginalRenderer = globalThis.Renderer;
globalThis.Renderer = class extends OriginalRenderer {
  constructor() {super();this.keys=new Set();this.newPrograms=0;this.outputColorSpace=THREE.SRGBColorSpace;
    this.state={buffers:{depth:{getReversed:()=>false}}};this.getRenderTarget=()=>null;
    this.clipping={numPlanes:0,numIntersection:0};
    this.cache=WebGLPrograms(this,{get:()=>null},{has:()=>false},
      {precision:'highp',getMaxPrecision:()=> 'highp'}, {},this.clipping);
  }
  compileAsync(scene,camera) {this.collect(scene,camera);return Promise.resolve();}
  collect(scene,camera) {
    const names=['sun','directional','point','spot','spotLightMap','rectArea','hemi','sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'];
    const lights=Object.fromEntries(names.map(k=>[k,[]]));lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;
    scene.traverseVisible(o=>{if(o.isRectAreaLight)lights.rectArea.push(o);if(o.isPointLight)lights.point.push(o);
      if(o.isDirectionalLight)lights.directional.push(o);if(o.isHemisphereLight)lights.hemi.push(o);});
    scene.traverseVisible(o=>{if(!o.geometry || !o.material || !o.layers.test(camera.layers))return;
      for(const m of [].concat(o.material)) {
        this.clipping.numPlanes=m.clippingPlanes?.length||0;
        const key=this.cache.getProgramCacheKey(this.cache.getParameters(m,lights,[],scene,o,[]));
        if(!this.keys.has(key)){this.keys.add(key);this.newPrograms++;}
      }
    });
  }
  render(scene,camera){super.render(scene,camera);this.collect(scene,camera);}
};
const THREE = await import('three');
const M = await import(file('static/twin/viewing.js'));
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {atlasMesh} = await import(file('static/twin/bake/atlas.js'));
const {occluders} = await import(file('static/twin/bake/bake_pass.js'));
const {buildAtlas} = await import(file('static/twin/bake/atlas.js'));
function building(id,position=[0,0],two=true) {
  const outline=[[0,0],[30,0],[30,20],[0,20]];
  const levels=[{id:'L1',elevation:0,ceiling:10,outline},...(two?[{id:'L2',elevation:10,ceiling:10,outline}]:[])];
  return {id,name:id,position,levels,
    walls:levels.flatMap(l=>outline.map((p,i)=>({id:`${l.id}:w${i}`,level:l.id,from:p,to:outline[(i+1)%4],height:10,thickness:.5,exterior:true}))),
    rooms:levels.map(l=>({id:`${l.id}:room`,name:'Room',level:l.id,polygon:outline})),
    openings:[{id:'door',wall:'L1:w0',level:'L1',at:8,width:3,sill:0,head:7,kind:'door'},
      {id:'window',wall:'L1:w2',level:'L1',at:10,width:4,sill:3,head:8,kind:'window'}],
    roof:{sections:[{id:'roof',rect:[0,0,30,20],plate:two?20:10,pitch:8,kind:'gable',ridge:'x',overhang:0}]},
    lights:levels.map(l=>({level:l.id,at:[15,10],kind:'recessed'}))};
}
function plan(){return {buildings:[building('main'),building('detached',[40,0],false)],site:{},materials:{}};}
async function mounted(editor=false) {
  const host=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(host);}
  return mountTwin(host,{plan:plan(),kit:{materials:{}},tier:'low',bake:false});
}
let clock=0;
function step(v,distance,height=1,x=15,y=10) {
  v.controls.target.set(x*.3048,height*.3048,-y*.3048);
  v.camera.position.set(x*.3048,(height+distance)*.3048,-y*.3048);v.controls.update();
  v.render();clock+=300; v.renderer3.loop?.();
}
// Drive the real animation loop with a deterministic clock, including 250ms settles.
globalThis.Renderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
const time=performance.now.bind(performance);let fakeNow=1000;
Object.defineProperty(performance,'now',{value:()=>fakeNow});
function settle(v){fakeNow+=300;v.render();}
function zoom(v,d,h=1,x=15,y=10){step(v,d,h,x,y);settle(v);}
const roof=(v,id='main')=>v.groups.roof.children.find(g=>g.userData.buildingId===id);
function opacity(group){let value=null;group.traverse(o=>{if(o.isMesh&&!o.layers.isEnabled(31))value??=o.material.opacity;});return value;}
await test('fade band is clamped, eased, continuous and hysteresis resists threshold noise',()=>{
  assert.equal(M.fadeAlpha(0,10,20),0);assert.equal(M.fadeAlpha(30,10,20),1);
  assert.equal(M.fadeAlpha(15,10,20),.5);
  assert.ok(Math.abs(M.fadeAlpha(20-1e-5,10,20)-1)<1e-9);
  let active=false;for(const d of [20,19.9,20.1,19.8])active=M.bandActive(d,20,active,.5);
  assert.equal(active,false);active=M.bandActive(19,20,active,.5);assert.equal(active,true);
  for(const d of [20,19.9,20.1,20.4])assert.equal(M.bandActive(d,20,active,.5),true);
  assert.equal(M.bandActive(21,20,active,.5),false);
});
await test('floor selection uses target height and transformed floor outlines',()=>{
  const b=building('b',[20,30]);b.rotation=90;
  assert.equal(M.nearestFloor(b.levels,1).id,'L1');assert.equal(M.nearestFloor(b.levels,9).id,'L2');
  const points=M.floorOutline(b,b.levels[0]);assert.ok(Math.abs(points[2][0])<1e-10);assert.equal(points[2][1],60);
});
await test('sampled peel finds front buildings and trees, excludes behind and beside',()=>{
  const box=(x,y,h=20)=>({min:[x,y,0],max:[x+5,y+5,h]});
  const obstacles=[{id:'front',box:box(10,-2)},{id:'tree',box:box(20,-2,40)},
    {id:'behind',box:box(-20,-2)},{id:'beside',box:box(10,20)}];
  assert.deepEqual([...M.peelSet([40,0,10],[[0,0,1],[0,2,1]],obstacles)],['front','tree']);
});
await test('actual tree domain fades and restores its original materials on controller disposal',()=>{
  const p=plan(),model=buildTwin(p,{materials:{}},'low',{viewing:true}),scene=new THREE.Scene();scene.add(model.root);
  const tree=new THREE.Group(),source=new THREE.MeshStandardMaterial({alphaTest:.45,side:THREE.DoubleSide});
  tree.userData.viewingTree=true;tree.add(new THREE.Mesh(new THREE.BoxGeometry(3,35,3).translate(43,17.5,-10),source));model.groups.site.add(tree);
  const view={plan:p,scene,roomLights:[],camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3(15*.3048,.3048,-10*.3048)},renderer3:{shadowMap:{}}};
  view.camera.position.set(60*.3048,15*.3048,-10*.3048);
  const controller=M.createViewing(view,model,()=>0,()=>{});
  view.camera.position.set(15*.3048,80*.3048,-10*.3048);controller.update(900);
  view.camera.position.set(60*.3048,15*.3048,-10*.3048);controller.select('main:L1');
  controller.update(1000);assert.ok(tree.children[0].material.opacity>0&&tree.children[0].material.opacity<1);
  assert.equal(tree.visible,true);controller.update(1300);
  assert.equal(tree.children[0].material.opacity,0);assert.equal(tree.visible,false);assert.equal(tree.children[0].material.forceSinglePass,true);
  view.camera.position.set(15*.3048,25*.3048,-10*.3048);controller.update(1400);
  assert.equal(tree.visible,true);assert.ok(tree.children[0].material.opacity>0&&tree.children[0].material.opacity<1);
  controller.update(1700);
  assert.equal(tree.children[0].material.opacity,1);assert.equal(tree.visible,true);controller.dispose();assert.equal(tree.children[0].material,source);
});
await test('cut height is four feet below ceiling, bounded for short levels',()=>{
  assert.equal(M.cutHeight({ceiling:10}),6);assert.equal(M.cutHeight({ceiling:9}),5);
  assert.equal(M.cutHeight({ceiling:3}),1);
});
await test('generated variants have closed horizontal caps on all four gabled walls',()=>{
  const p=plan(), model=buildTwin(p,{materials:{}},'low',{viewing:true});
  let caps=0,groups=0;
  model.root.traverse(g=>{if(g.userData.viewingWalls!=='cut')return;groups++;
    const elevation=g.name.includes('L2')?10:0;
    g.traverse(o=>{if(!o.isMesh || o.material.name==='glass')return;const a=o.geometry.attributes.position,n=o.geometry.attributes.normal;
      for(let i=0;i<a.count;i+=3)if(n.getY(i)>.9 && [i,i+1,i+2].every(j=>Math.abs(a.getY(j)-elevation-6)<1e-4))caps++;
    });
  });assert.equal(groups,3);assert.ok(caps>=24,`cap triangles: ${caps}`);
});
await test('cut slabs have continuous plain tops without batten teeth, including mitred footprints',()=>{
  const p=plan();p.buildings=p.buildings.slice(0,1);
  p.buildings[0].openings=[];
  const first=p.buildings[0].walls[0];
  // Connected-model footprint path and the legacy extrusion path must both cap.
  first.footprint=[[0,0],[30,0],[29.5,.5],[.5,.5]];
  const model=buildTwin(p,{materials:{siding:{asset:'board_and_batten'}}},'low',{viewing:true});
  let tops=0,area=0;
  const group=model.groups.levels['main:L1'].children.flatMap(g=>g.children).find(g=>g.userData.viewingWalls==='cut');
  assert.ok(group);
  group.traverse(o=>{
    if(!o.isMesh||o.layers.isEnabled(31))return;
    const a=o.geometry.attributes.position,n=o.geometry.attributes.normal;
    for(let i=0;i<a.count;i+=3)if(n.getY(i)>.9&&[i,i+1,i+2].every(j=>Math.abs(a.getY(j)-6)<1e-4)){
      assert.equal(o.material.name,'viewing_wall_top','cap uses a plain plan tone');
      tops++;
      area+=Math.abs((a.getX(i+1)-a.getX(i))*(a.getZ(i+2)-a.getZ(i))-(a.getZ(i+1)-a.getZ(i))*(a.getX(i+2)-a.getX(i)))/2;
    }
  });
  // Perimeter * thickness, minus the two mitred triangles on the first wall.
  assert.ok(tops>=8);assert.ok(Math.abs(area-49.75)<1e-3,`solid top area without relief: ${area}`);
});
await test('mounted cut caps stay strictly inside the clip plane at fractional world heights',async()=>{
  const p=plan();const b=p.buildings[0];b.base=.137;b.rotation=27.3;
  b.levels[1].elevation=10.113;b.levels[1].ceiling=9.271;
  const v=await mountTwin(new Element(),{plan:p,kit:{materials:{siding:{asset:'board_and_batten'}}},tier:'low',bake:false});
  try {
    v.setView('main:L2');settle(v);v.scene.updateMatrixWorld(true);
    let caps=0;
    v.groups.levels['main:L2'].traverse(o=>{
      if(!o.isMesh||o.material.name!=='viewing_wall_top')return;
      const a=o.geometry.attributes.position;
      for(let i=0;i<a.count;i++){
        const point=new THREE.Vector3().fromBufferAttribute(a,i).applyMatrix4(o.matrixWorld);
        assert.ok(o.material.clippingPlanes[0].distanceToPoint(point)>1e-5,'cap survives GPU clip rounding');caps++;
      }
    });
    assert.ok(caps>0,'renderable cap geometry exists');
  } finally {v.dispose();}
});
await test('viewer levels peel roofs and upper floors; distance alone never changes levels',async()=>{
  const v=await mounted();try {
    for(const d of [70,38,25]){zoom(v,d);assert.equal(v.state.view,'ext');assert.equal(opacity(roof(v)),1);}
    v.levels.go({building:'main'},{immediate:true});settle(v);assert.equal(opacity(roof(v)),1);
    v.levels.go({building:'main',floor:'L2'},{immediate:true});settle(v);
    assert.equal(v.state.view,'main:L2');assert.equal(opacity(roof(v)),0);assert.equal(opacity(roof(v,'detached')),1);
    v.levels.go({building:'main',floor:'L1'},{immediate:true});settle(v);assert.equal(v.groups.levels['main:L2'].visible,false);
    for(const d of [34,33.9,34.1,70]){zoom(v,d);assert.equal(v.state.view,'main:L1');}
    v.levels.go({level:'house'},{immediate:true});settle(v);assert.equal(opacity(roof(v)),1);
    v.levels.go({building:'detached',floor:'L1'},{immediate:true});settle(v);assert.equal(opacity(roof(v)),1);
  } finally {v.dispose();}
});
await test('floor level pins cutaway and peels foreground; level up restores it',async()=>{
  const v=await mounted();try {
    v.levels.go({building:'main',floor:'L1'},{immediate:true});settle(v);assert.equal(v.viewingState().pinned,'main:L1');
    assert.ok(Math.abs(v.controls.target.x/.3048-15)<.01);
    v.controls.target.set(15*.3048,.3048,-10*.3048);v.camera.position.set(60*.3048,15*.3048,-10*.3048);v.render();settle(v);
    assert.equal(opacity(roof(v,'detached')),0);assert.equal(roof(v,'detached').visible,false);
    assert.equal(v.groups.levels['detached:L1'].visible,false);assert.equal(v.groups.levels['main:L2'].visible,false);
    zoom(v,70);assert.equal(v.viewingState().pinned,'main:L1');
    v.levels.up();fakeNow+=401;tick();settle(v);assert.equal(v.viewingState().pinned,null);assert.equal(v.state.view,'ext');
    assert.equal(roof(v,'detached').visible,true);
  } finally {v.dispose();}
});
await test('an exterior-distance pin survives orbit, pan, zoom-in and return to its starting distance',async()=>{
  const p=plan(),model=buildTwin(p,{materials:{}},'low',{viewing:true});
  const v={plan:p,camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3(15*.3048,.3048,-10*.3048)},
    roomLights:model.roomLights,renderer3:{shadowMap:{}}};
  v.camera.position.copy(v.controls.target).add(new THREE.Vector3(0,90*.3048,0));
  let selected;const c=M.createViewing(v,model,()=>0,key=>selected=key);
  const update=()=>{c.update(fakeNow);fakeNow+=300;c.update(fakeNow);};
  try {
    c.select('main:L1');update();assert.equal(selected,'main:L1');
    assert.equal(c.snapshot().pinned,'main:L1');assert.equal(model.groups.levels['main:L2'].visible,false);
    v.camera.position.copy(v.controls.target).add(new THREE.Vector3(90*.3048,0,0));update();
    v.camera.position.x+=10*.3048;v.controls.target.x+=10*.3048;update();
    v.camera.position.copy(v.controls.target).add(new THREE.Vector3(0,30*.3048,0));update();
    v.camera.position.copy(v.controls.target).add(new THREE.Vector3(0,110*.3048,0));update();
    assert.equal(c.snapshot().pinned,'main:L1');assert.equal(selected,'main:L1');
    v.camera.position.y=v.controls.target.y+114*.3048;update();
    assert.equal(c.snapshot().pinned,null);assert.equal(selected,'ext');
    c.select('main:L2');update();assert.equal(c.snapshot().pinned,'main:L2');
    c.select('ext');update();assert.equal(c.snapshot().pinned,null);assert.equal(selected,'ext');
  } finally {c.dispose();}
});
await test('viewer zoom release uses the level range and commit threshold; another floor reframes',async()=>{
  const v=await mounted();try {
    v.levels.go({building:'main',floor:'L1'},{immediate:true});settle(v);
    assert.equal(v.levels.zoomEnd(1.24),'spring');fakeNow+=401;tick();settle(v);assert.equal(v.viewingState().pinned,'main:L1');
    v.levels.go({building:'main',floor:'L2'},{immediate:true});settle(v);assert.equal(v.viewingState().pinned,'main:L2');
    assert.equal(v.levels.zoomEnd(1.5),'up');fakeNow+=401;tick();settle(v);assert.equal(v.viewingState().pinned,null);
    assert.equal(v.levels.snapshot().level,'building');
  } finally {v.dispose();}
});
await test('production setView exposes state and preserves legacy single-building visibility within the fade',async()=>{
  const search=location.search;location.search='?tier=high';
  const p=plan();p.buildings.length=1;
  const v=await mountTwin(new Element(),{plan:p,kit:{materials:{}},tier:'high',bake:false});
  try {
    for(const id of ['L2','L1','ext']) {
      v.setView(id);settle(v);
      const s=v.viewingState(),g=v.groups;
      assert.equal(s.selected,id==='ext'?'ext':`main:${id}`);
      assert.equal(s.pinned,id==='ext'?null:`main:${id}`);
      assert.equal(g.roof.visible,id==='ext');assert.equal(g.gableFull.visible,id==='ext');
      assert.equal(g.gableCut.visible,id==='L2');
      assert.equal(g.levels.L2.visible,id!=='L1');assert.equal(g.levels.L1.visible,true);
    }
  } finally {v.dispose();location.search=search;}
});
await test('fade advances while camera keeps moving and finishes at 250ms',async()=>{
  const v=await mounted();try {
    v.levels.go({building:'main',floor:'L1'},{immediate:true});
    for(let i=0;i<12;i++){fakeNow+=16;step(v,38-i*.1);}
    assert.ok(opacity(roof(v))<.15,opacity(roof(v)));
    settle(v);assert.equal(opacity(roof(v)),0);
  } finally {v.dispose();}
});
await test('prepared materials retain atlas eligibility and baked clones follow opacity/clipping',async()=>{
  const v=await mounted();try {
    let mesh;roof(v).traverse(o=>{if(o.isMesh&&atlasMesh(o))mesh??=o;});assert.ok(mesh);
    const source=mesh.material, baked=source.clone();v.prepareViewingMaterial(source,baked);mesh.material=baked;
    v.levels.go({building:'main',floor:'L1'},{immediate:true});settle(v);assert.equal(baked.opacity,0);assert.equal(baked.clippingPlanes[0],source.clippingPlanes[0]);
    v.levels.go({level:'house'},{immediate:true});settle(v);assert.equal(baked.opacity,1);assert.equal(atlasMesh(mesh),true);
    const blocked=occluders(v);assert.ok(blocked.children.length>0);
    const cuts=new Set();v.scene.traverse(o=>{if(o.userData.viewingWalls==='cut')o.traverse(m=>{if(m.geometry)cuts.add(m.geometry);});});
    assert.ok(blocked.children.every(m=>!cuts.has(m.geometry)));
    mesh.material=source;baked.dispose();
  } finally {v.dispose();}
});
await test('real r187 program-key set never grows after warm across zoom and floor pins',async()=>{
  const v=await mounted();try {
    const keys=[...v.renderer3.keys].sort(), before=v.renderer3.newPrograms;
    for(let pass=0;pass<3;pass++) {
      for(const d of [70,47,40,38,34,28,20,28,34,40,47,70])zoom(v,d);
      v.levels.go({building:'main',floor:'L1'},{immediate:true});settle(v);
      v.controls.target.set(15*.3048,.3048,-10*.3048);v.camera.position.set(60*.3048,15*.3048,-10*.3048);
      v.render();settle(v);assert.equal(roof(v,'detached').visible,false);
      v.levels.go({building:'main',floor:'L2'},{immediate:true});settle(v);v.levels.go({level:'house'},{immediate:true});settle(v);
    }
    assert.deepEqual([...v.renderer3.keys].sort(),keys);assert.equal(v.renderer3.newPrograms,before);
    console.log(`    real r187 keys=${keys.length}, new after warm=${v.renderer3.newPrograms-before}`);
    // A negative control proves the recorder notices an opaque/transparent flip.
    let m;roof(v).traverse(o=>{if(o.isMesh&&!o.layers.isEnabled(31))m??=o.material;});m.transparent=false;v.render();
    assert.ok(v.renderer3.newPrograms>before,'key recorder detects an unprepared opaque variant');m.transparent=true;
  } finally {v.dispose();}
});
await test('cut variants keep matching Low/High room atlas keys',async()=>{
  const p=plan(),kit={materials:{}},low=buildTwin(p,kit,'low',{viewing:true}),high=buildTwin(p,kit,'high',{viewing:true});
  await Promise.all([low.ready,high.ready]);
  const view=model=>({plan:p,scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},renderer3:{shadowMap:{}},roomLights:model.roomLights});
  const lv=view(low),hv=view(high);lv.scene.add(low.root);hv.scene.add(high.root);
  const lc=M.createViewing(lv,low,()=>0,()=>{}),hc=M.createViewing(hv,high,()=>0,()=>{});
  const options={room:{density:1,page:256,gutter:2}};
  const la=buildAtlas(low.root,p,options),ha=buildAtlas(high.root,p,options);
  assert.equal(la.key,ha.key);assert.ok(la.room.charts.length>0);
  lc.dispose();hc.dispose();
});
await test('stationary Low viewing work is cheap and creates no materials or geometry',async()=>{
  const v=await mounted();try {
    zoom(v,25);const before=[];v.scene.traverse(o=>{if(o.geometry)before.push([o,o.geometry,o.material]);});
    const start=time();for(let i=0;i<3000;i++)v.render();const ms=(time()-start)/3000;
    for(const [o,g,m]of before){assert.equal(o.geometry,g);assert.equal(o.material,m);}
    console.log(`    Node mounted Low CPU frame (stub GPU): ${ms.toFixed(3)} ms`);assert.ok(ms<10,ms);
  } finally {v.dispose();}
});
await test('editor retains explicit floor visibility and no viewing cut domains',async()=>{
  const v=await mounted(true);try {
    assert.deepEqual(v.viewingState(),{selected:'ext',pinned:null,channels:[]});v.setView('main:L1');zoom(v,70);
    assert.equal(v.viewingState().pinned,'main:L1');
    assert.equal(v.state.view,'main:L1');assert.equal(v.groups.levels['detached:L1'].visible,false);
    let cuts=0;v.scene.traverse(o=>{if(o.userData.viewingWalls)cuts++;});assert.equal(cuts,0);
  } finally {v.dispose();}
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=280)
    print(out)
    sys.exit(code or 0)
