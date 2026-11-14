"""Node regression proof for connected drag dependencies and preview work.

Uses real household geometry with CPU renderer/DOM doubles. Chromium still
owns the 33 ms GPU gate; these checks make no timing claim.
Run from chauffeur/: python tests/test_twin_drag_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {root, flat, kit} = JSON.parse(readFileSync(process.argv[2]));
const file = p => pathToFileURL(root + '/' + p).href;
const data = source => 'data:text/javascript,' + encodeURIComponent(source);
const three = file('static/vendor/three-r187/three.module.js');
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url: data(`export * from '${three}'; export const WebGLRenderer = globalThis.Renderer;`), shortCircuit: true};
  if (spec === 'three/addons/controls/OrbitControls.js') return {url: data(`import {EventDispatcher,Vector3} from '${three}';
    export class OrbitControls extends EventDispatcher {
      constructor(camera){super();this.object=camera;this.target=new Vector3();this.enabled=true;}
      update(){this.object.lookAt(this.target);this.object.updateMatrixWorld();} dispose(){}
    }`), shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true};
  if (spec === './twin_yard.js') return {url: data(`import {Group} from '${three}'; export const yardKey=(p,k,t,o)=>JSON.stringify([p.site,t,o]); export const yardMaterialKey=(p,k,t)=>JSON.stringify([p.materials,k.materials,t]); export async function buildYard(){globalThis.yardBuilds=(globalThis.yardBuilds||0)+1;const group=new Group();group.name='test-yard';return {group};}`), shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format:'module'}), format:'module'} : next(url, ctx);
}});
class Element extends EventTarget {
  constructor(){super();this.children=[];this.style={};this.dataset={};this.clientWidth=1440;this.clientHeight=900;}
  getBoundingClientRect(){return {left:0,top:0,right:1440,bottom:900,width:1440,height:900};}
  append(...nodes){this.children.push(...nodes);for(const n of nodes)n.parentElement=this;}
  appendChild(node){this.append(node);}
  replaceChildren(){for(const n of this.children)n.parentElement=null;this.children=[];}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);}
  closest(){return this;} setAttribute(k,v){this[k]=v;}
  getContext(){return {getExtension:()=>null};}
}
globalThis.window = new Element();
globalThis.document = Object.assign(new EventTarget(),{createElement:()=>new Element(),getElementById:()=>null});
globalThis.location = {search:'?test=1&tier=low'};
globalThis.getComputedStyle = ()=>({getPropertyValue:()=>''});
globalThis.CustomEvent = class extends Event {constructor(name,opts){super(name);this.detail=opts.detail;}};
globalThis.ResizeObserver = class {observe(){} disconnect(){}};
let renders = 0;
globalThis.Renderer = class {
  constructor(){this.domElement=new Element();this.shadowMap={};this.info={render:{calls:0,triangles:0},reset(){}};}
  setPixelRatio(){} getContext(){return {getExtension:()=>null};} setSize(){} setAnimationLoop(){}
  render(scene){renders++;scene.updateMatrixWorld(true);} dispose(){} forceContextLoss(){}
};
const {createDrag, piecesOnMovedJoints} = await import(file('static/twin/editor/drag.js'));
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createDimensions, placeDimensionLabel} = await import(file('static/twin/editor/dimensions.js'));
const {contains, stairHoles, buildTwin} = await import(file('static/twin/twin_generator.js'));
const {disposeObject} = await import(file('static/twin/twin_library.js'));
let passed = 0;
const ok = text => {passed++; console.log('  ok ' + text);};
const rectangle = [[0,0],[10,0],[10,10],[0,10]];
for (const point of [[0,0],[10,5],[5,10],[0,5],[5,5]]) assert.ok(contains(rectangle,point));
assert.equal(contains(rectangle,[11,5]),false);
const stairs = {levels:[{elevation:-10},{elevation:0}],stairs:[{from:[2,2],to:[2,8],width:4,rise_to:0}]};
assert.deepEqual(stairHoles(stairs,stairs.levels[0]),[]);
assert.deepEqual(stairHoles(stairs,stairs.levels[1]),[[[0,2],[0,8],[4,8],[4,2]]]);
ok('shared containment includes edges and stair holes use the bearing level, including a basement');

let zoom = 20, snapped;
const snapModel = {buildings:[{id:'snap',levels:[{id:'L1',elevation:0}],walls:[],rooms:[],anchors:[],items:[],
  joints:[{id:'moving',level:'L1',at:[0,0]},{id:'target',level:'L1',at:[3,0]}]}]};
const snapDrag = createDrag({model:()=>snapModel,view:{
  screenOfFloor:(x,y)=>[x*zoom,y*zoom],floorAt:(x,y)=>[x/zoom,y/zoom],rebuildLevel:(b,l,p)=>{snapped=p.buildings[0].joints[0].at;}
},onCommit:()=>{}});
const snapSelection={kind:'joint',id:'moving',building:'snap'};
for(const [scale,x,expected] of [[20,2.5,3],[100,2.5,2.5],[100,2.8,3],[5,1.5,1.5],[5,2.1,3]]) {
  zoom=scale;assert.ok(snapDrag.begin(snapSelection,[0,0]));snapDrag.update([x,0]);
  assert.ok(Math.abs(snapped[0]-expected)<1e-6,`${scale}px/ft: ${snapped}`);await snapDrag.finish(true);
}
ok('R45 uses 12 screen pixels: a joint half a foot away snaps at 20px/ft, with both reach clamps');

// Live t12: dragging a wall across its neighbour snaps it onto the neighbour's
// line on the way (the midpoint snaps to wall N), which collapses the attached wall to zero length. That
// frame has no direction and deformed the scene into NaN; it is skipped.
const collapseModel={buildings:[{id:'c',levels:[{id:'L1',elevation:0}],rooms:[],openings:[],anchors:[],items:[],
  joints:[{id:'j1',level:'L1',at:[0,0]},{id:'j2',level:'L1',at:[0,5]},{id:'j3',level:'L1',at:[4,5]},{id:'j4',level:'L1',at:[4,0]}],
  walls:[{id:'W',level:'L1',from:[0,0],to:[0,5],joints:['j1','j2']},{id:'A',level:'L1',from:[0,5],to:[4,5],joints:['j2','j3']},
    {id:'N',level:'L1',from:[4,5],to:[4,0],joints:['j3','j4']}]}]};
const collapseFrames=[], collapseOps=[];
const collapseDrag=createDrag({model:()=>collapseModel,onCommit:op=>collapseOps.push(op),view:{
  screenOfFloor:(x,y)=>[x*20,y*20],floorAt:(x,y)=>[x/20,y/20],
  rebuildLevel:(b,l,p)=>collapseFrames.push(p.buildings[0].walls.slice(0,2).map(w=>Math.hypot(w.to[0]-w.from[0],w.to[1]-w.from[1])))}});
assert.ok(collapseDrag.begin({kind:'wall',id:'W',building:'c'},[0,2.5]));
assert.ok(collapseDrag.update([2,2.5]));assert.equal(collapseFrames.length,1);
assert.ok(collapseDrag.update([3.9,2.5]),'the gesture stays live');
assert.equal(collapseFrames.length,1,'a frame that collapses the attached wall is never drawn');
assert.ok(collapseDrag.update([6,2.5]));assert.equal(collapseFrames.length,2,'drawing resumes once the wall has length again');
assert.ok(collapseFrames.flat().every(length=>length>1e-6),`no drawn frame holds a zero-length wall: ${JSON.stringify(collapseFrames)}`);
await collapseDrag.finish();
assert.ok(Math.abs(collapseOps[0].by[0]-6)<1e-6&&Math.abs(collapseOps[0].by[1])<1e-6,`release posts the drawn move: ${JSON.stringify(collapseOps)}`);
ok('a drag frame that snaps a wall onto a corner and collapses its neighbour is skipped, never drawn as NaN');

const pickPlan={buildings:[{id:'pick',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:6},{id:'L2',elevation:6,ceiling:6}],
  walls:[],openings:[],anchors:[],items:[],roof:{sections:[]},rooms:[
    {id:'lower',level:'L1',polygon:rectangle},{id:'upper',level:'L2',polygon:rectangle}]}],site:{},materials:{}};
const pickView=await mountTwin(new Element(),{plan:pickPlan,kit,tier:'low',preserveCamera:true});
pickView.setSelection({selected:{kind:'room',id:'lower',building:'pick',level:'L1'},room:{id:'lower',building:'pick',level:'L1',allowed:['lower'],walls:[]}});
while(!pickView.ready)await new Promise(r=>setTimeout(r,1));
pickView.setView('ext');pickView.setCameraState({position:[5*.3048,30*.3048,-4.999*.3048],target:[5*.3048,0,-5*.3048]});
const pixel=pickView.screenOfFloor(5,5,'pick:L1');
assert.equal(pickView.pieceInfo('upper','pick').opacity,.25);
assert.equal(pickView.pick(...pixel)?.id,'lower','ray passes through the ghosted upper floor to the focused room');
const ProjectionThree=await import(three);
Object.assign(pickPlan.buildings[0],{rotation:31,base:2,position:[3,4]});
for(const kind of ['perspective','top']){
  if(kind==='top')pickView.setPlanCamera('pick:L2');
  const angle=31*Math.PI/180;
  const expected=new ProjectionThree.Vector3((Math.cos(angle)*2-Math.sin(angle)*3+3)*.3048,
    (2+6+9)*.3048,-(Math.sin(angle)*2+Math.cos(angle)*3+4)*.3048).project(pickView.camera);
  const top=pickView.screenOfFloor(2,3,'pick:L2',9);
  assert.ok(Math.hypot(top[0]-(expected.x+1)*720,top[1]-(1-expected.y)*450)<1e-6,
    `${kind}: wall top uses live camera, building rotation/position, base and level elevation`);
}
pickView.dispose();
ok('perspective picks pass through a ghosted floor to the focused room below');
ok('height-aware level projection matches actual Three.js perspective and plan camera transforms');

const bandBuilding={id:'band',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:9},{id:'L2',elevation:9,ceiling:9}],
  rooms:[],walls:[{id:'outer',level:'L2',from:[0,0],to:[10,0],thickness:.5,height:9,exterior:true,footprint:[[0,-.25],[10,-.25],[10,.25],[0,.25]]}],
  openings:[],anchors:[],items:[],roof:{sections:[]}};
const band=buildTwin({buildings:[bandBuilding],site:{},materials:{}},kit,'low',{editableLevel:'band:L2'});await band.ready;
assert.ok(band.pieces.get('band:floor:L2').some(o=>o.material.name==='siding'),'outer storey band takes siding');
assert.ok(band.pieces.get('band:floor:L2').every(o=>o.material.name!=='interior_wall'));
disposeObject(band.root);
ok('exterior storey band uses the siding cascade');

// Pure screen-space placement: no DOM, camera, renderer or model state.
const rectangleDistance=(point,centre,size)=>Math.hypot(Math.max(0,Math.abs(point[0]-centre[0])-size.width/2),
  Math.max(0,Math.abs(point[1]-centre[1])-size.height/2));
const clearLabel=options=>{
  const before=JSON.stringify(options), centre=placeDimensionLabel(options);
  assert.ok(centre?.every(Number.isFinite));
  const midpoint=options.wall[0].map((v,i)=>(v+options.wall[1][i])/2);
  for(const point of [...options.handles,midpoint])assert.ok(rectangleDistance(point,centre,options.size)>=24,
    `label ${centre} clears handle ${point} by 24px`);
  assert.equal(JSON.stringify(options),before,'placement never mutates its inputs');
  return centre;
};
const labelSize={width:80,height:44};
assert.deepEqual(clearLabel({wall:[[0,0],[400,0]],neighbour:[[0,100],[400,100]],handles:[],size:labelSize}),[100,50],
  'unobstructed gap label starts at 25% of the wall, halfway across the gap');
for(const wall of [[[400,500],[612,500]],[[504,400],[504,600]],[[400,400],[600,600]]]) {
  const d=wall[1].map((v,i)=>v-wall[0][i]), length=Math.hypot(...d), normal=[-d[1]/length,d[0]/length];
  const neighbour=wall.map(p=>p.map((v,i)=>v+normal[i]*1));
  // Narrow projected gaps model the refusal press point even if handles()
  // has not yet refreshed. The wall midpoint is protected by the function.
  clearLabel({wall,neighbour,handles:[],size:labelSize});
  const handles=Array.from({length:20},(_,i)=>wall[0].map((v,j)=>v+d[j]*i/19+normal[j]*.5));
  const options={wall,neighbour,handles,size:labelSize};
  assert.deepEqual(clearLabel(options),clearLabel({...options,handles:[...handles].reverse()}),'handle ordering cannot affect placement');
  for(const outside of [-1,1])clearLabel({wall,handles,size:labelSize,outside});
}
for(const outside of [-1,1]) {
  const centre=clearLabel({wall:[[0,0],[400,0]],handles:[[100,outside*38],[200,0]],size:labelSize,outside});
  assert.ok(outside*centre[1]-labelSize.height/2>=16,'length label keeps R47a wall-line clearance');
}
assert.equal(placeDimensionLabel({wall:[[1,1],[1,1]],handles:[],size:labelSize}),null);
assert.equal(placeDimensionLabel({wall:[[0,0],[400,0]],neighbour:[[0,0],[0,100]],handles:[],size:labelSize}),null);
ok('pure R47b placement starts gap labels at one quarter and clears the wall midpoint and every handle by 24px');

// Controller case: this observed centre overlaps the real 47x44 button.
const refusalGrab=[506,500], refusalSize={width:47,height:44};
assert.equal(rectangleDistance(refusalGrab,[490.151,520.841],refusalSize),0);
const refusalPlacement={wall:[[506,541.682],[506,458.318]],neighbour:[[474.302,541.682],[474.302,458.318]],
  handles:[refusalGrab],size:refusalSize};
for(const height of [1,18,44]) {
  const centre=placeDimensionLabel({...refusalPlacement,size:{width:47,height}});
  assert.ok(rectangleDistance(refusalGrab,centre,refusalSize)>=24,
    `the real 47x44 box clears (506,500), including an early ${height}px height measurement: ${centre}`);
}
ok('exact t12 refusal box 47x44 clears (506,500) by 24px even when an early height measurement is smaller');

// R47c: the visible face is not its floor-level midpoint. Measure clearance
// against whole polygon edges/interior, independently of the placement code.
const polygonDistance=(polygon,centre,size)=>{
  const corners=[[-1,-1],[1,-1],[1,1],[-1,1]].map(([x,y])=>[centre[0]+x*size.width/2,centre[1]+y*size.height/2]);
  if(corners.some(p=>contains(polygon,p))||polygon.some(p=>rectangleDistance(p,centre,size)===0))return 0;
  const cross=(a,b,p)=>(b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]);
  const pointSegment=(p,a,b)=>{
    const d=b.map((v,i)=>v-a[i]), t=Math.max(0,Math.min(1,d.reduce((n,v,i)=>n+v*(p[i]-a[i]),0)/(d[0]**2+d[1]**2||1)));
    return Math.hypot(...p.map((v,i)=>v-a[i]-t*d[i]));
  };
  let distance=Infinity;
  for(const [i,a]of polygon.entries())for(const [j,c]of corners.entries()){
    const b=polygon[(i+1)%polygon.length],d=corners[(j+1)%4];
    if(cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0)return 0;
    distance=Math.min(distance,pointSegment(a,c,d),pointSegment(b,c,d),pointSegment(c,a,b),pointSegment(d,a,b));
  }
  return distance;
};
const refusalQuad=[[520,570],[520,530],[492,450],[492,490]];
const silhouettePlacement={wall:refusalQuad.slice(0,2),neighbour:[[488.302,570],[488.302,530]],
  avoid:refusalQuad,handles:[],size:refusalSize};
assert.ok(contains(refusalQuad,refusalGrab),'the visible face includes the controller press point');
assert.equal(rectangleDistance(refusalGrab,[490.151,520.841],refusalSize),0);
assert.ok(rectangleDistance([520,550],[490.151,520.841],refusalSize)>0,'floor midpoint differs from the visible face');
const silhouetteCentre=placeDimensionLabel(silhouettePlacement);
assert.ok(polygonDistance(refusalQuad,silhouetteCentre,refusalSize)>=24,'47x44 label box clears the entire wall quad, including (506,500)');
assert.ok(rectangleDistance(refusalGrab,silhouetteCentre,refusalSize)>=24);
for(const polygon of [refusalQuad,[...refusalQuad].reverse(),[[100,100],[900,130],[750,350],[150,300]]]){
  const options={wall:polygon.slice(0,2),avoid:polygon,handles:[[90,100],[450,400]],size:labelSize};
  const before=JSON.stringify(options),centre=placeDimensionLabel(options);
  assert.ok(polygonDistance(polygon,centre,labelSize)>=24,'edges and face interior stay outside the expanded label box');
  for(const p of options.handles)assert.ok(rectangleDistance(p,centre,labelSize)>=24);
  assert.equal(JSON.stringify(options),before);
}
const confined={wall:[[-1000,100],[1000,100]],neighbour:[[-1000,140],[1000,140]],
  avoid:[[-1000,100],[1000,100],[1000,180],[-1000,180]],size:labelSize,
  bounds:{left:0,top:0,right:400,bottom:300}};
const oppositeCentre=placeDimensionLabel(confined);
assert.ok(oppositeCentre[1]<100,'switch sides when no along-wall shift fits in the viewport');
assert.ok(polygonDistance(confined.avoid,oppositeCentre,labelSize)>=24);
assert.equal(placeDimensionLabel({...confined,avoid:[[-1000,0],[1000,0],[1000,300],[-1000,300]]}),null,
  'hide when neither side nor an along-wall shift fits');
ok('R47c whole-box clearance avoids the projected 3D quad, shifts along the wall, switches sides or hides');

// Live t12 inputs, read from the page (wall CROSSER at x 17.75, plan view,
// 16.13 px/ft). (506,500) is NOT on the wall or a handle: it is the drag's
// waypoint (22, 14.75), 4.25 ft out in the gap, on the track the wall handle
// (437,500) travels along. The quad and handle rules alone leave the label at
// (490.151,520.841), covering it; the handle's track must be kept clear too.
const liveWall=[[437.0415916275405,541.6809366813886],[437.04201872713236,458.3193291838163]];
const liveRow={wall:liveWall,neighbour:[[543.2607535035289,541.6809366813886],[543.2604382880617,436.7530477510132]],
  avoid:[...liveWall,[428.67230121450683,453.08909603920245],[428.67176066658766,546.8709041847746]],
  handles:[[650.8125,541.671875],[543.25,541.671875],[437.03125,541.671875],[437.03125,458.3125],[150.640625,458.3125],
    [431.46875,573.9375],[437.03125,500]],
  size:{width:46.671875,height:44},outside:1,bounds:{left:0,top:0,right:1008,bottom:1000}};
const liveTrack=[[437.0418051780175,499.99999999999943],[420.90730040163646,499.9999999999996]];
const untracked=placeDimensionLabel(liveRow);
assert.ok(Math.hypot(untracked[0]-490.151,untracked[1]-520.841)<.01,`without the track the live label lands where t12 saw it: ${untracked}`);
assert.equal(rectangleDistance([505.6134504776369,500],untracked,liveRow.size),0,'and covers the drag waypoint');
const liveBefore=JSON.stringify(liveRow), tracked=placeDimensionLabel({...liveRow,paths:[liveTrack]});
assert.equal(JSON.stringify(liveRow),liveBefore);
for(const waypoint of [[505.6134504776369,500],[570.1514695831612,500],[437.0418051780175,500]])
  assert.ok(rectangleDistance(waypoint,tracked,liveRow.size)>=24,`live label ${tracked} clears drag waypoint ${waypoint} by 24px`);
assert.ok(polygonDistance(liveRow.avoid,tracked,liveRow.size)>=24,'and still clears the wall quad');
for(const p of liveRow.handles)assert.ok(rectangleDistance(p,tracked,liveRow.size)>=24,`and still clears handle ${p}`);
assert.ok(Math.abs(tracked[0]-490.151)<.01,'it slides along the wall, staying halfway across the gap');
ok('live t12 case: the distance label keeps 24px off the wall handle track, the quad and every handle');

let labelZoom=20, oblique=false, labelHandles=[];
const dimensionHost=new Element(), dimensionView={renderer3:{domElement:new Element()},controls:new EventTarget(),
  screenOfFloor:(x,y)=>[200+x*labelZoom+(oblique?y*labelZoom*.6:0),200+y*labelZoom*(oblique?.1:1)]};
dimensionHost.append(dimensionView.renderer3.domElement);
const dimensionAbort=new AbortController(), labelOps=[];
const labelDimensions=createDimensions({view:dimensionView,canEdit:()=>true,onCommit:op=>labelOps.push(op),signal:dimensionAbort.signal,getHandles:()=>labelHandles});
const labelWall={id:'wall',level:'L1',from:[0,0],to:[10,0],joints:['a','b']};
const labelBuilding={id:'label',walls:[labelWall,{id:'parallel',level:'L1',from:[0,10],to:[10,10]}]};
const createElement=document.createElement;
document.createElement=tag=>{const node=createElement(tag);if(tag==='button')node.getBoundingClientRect=()=>({width:80,height:44});return node;};
const showLabels=room=>labelDimensions.show({building:labelBuilding,piece:labelWall,room:{polygon:room}});
showLabels(rectangle);
const labelNodes=dimensionHost.children.at(-1).children;
assert.equal(labelNodes[1].style.left,'250px','gap label is one quarter along the selected wall');assert.equal(labelNodes[1].style.top,'300px','gap label is midway between both walls');
for(const zoom of [.1,1,20,100]) for(const skew of [false,true]) {
  labelZoom=zoom;oblique=skew;showLabels(rectangle);
  const nearest=Number.parseFloat(labelNodes[0].style.top)+22;
  assert.ok(200-nearest>=16-1e-6,`${zoom}px/ft, oblique=${skew}: nearest edge is ${200-nearest}px away`);
  assert.equal(labelNodes[0].hidden,false);
  showLabels([[0,0],[10,0],[10,-10],[0,-10]]);
  assert.ok(Number.parseFloat(labelNodes[0].style.top)-22-200>=16-1e-6,'opposite focused-room side stays clear too');
}
labelZoom=20;oblique=false;labelHandles=[{kind:'room',at:[5,5,0]}];showLabels(rectangle);
assert.equal(labelNodes[1].style.top,'300px','gap label stays at the gap midpoint while clearing its handle');
assert.ok(rectangleDistance([300,300],[Number.parseFloat(labelNodes[1].style.left),Number.parseFloat(labelNodes[1].style.top)],labelSize)>=24,'gap button clears the room handle by 24px');
labelZoom=1;oblique=false;
labelHandles=[{kind:'joint',at:[5,-38,0]}];showLabels(rectangle);
assert.ok(rectangleDistance([205,162],[Number.parseFloat(labelNodes[0].style.left),Number.parseFloat(labelNodes[0].style.top)],labelSize)>=24,'a concave-room handle beyond the wall line stays 24px outside the clickable box');
labelZoom=20;labelHandles=[{kind:'wall',id:'wall',at:[5,0,0]}];showLabels(rectangle);
assert.ok(Math.abs(Number.parseFloat(labelNodes[1].style.left)-300)-labelSize.width/2>=24,
  `the gap label leaves the wall handle's drag track (x 300) 24px clear: ${labelNodes[1].style.left}`);
assert.equal(labelNodes[1].style.top,'300px','and stays halfway across the gap');
labelHandles=[{kind:'wall',id:'other',at:[5,0,0]}];showLabels(rectangle);
assert.equal(labelNodes[1].style.left,'250px','the handle of another wall draws no track for this wall');
window.promptInput=async()=>"12'-0\"";
labelNodes[0].dispatchEvent(new Event('click'));await new Promise(r=>setImmediate(r));
assert.equal(labelOps[0].op,'move_joint');assert.deepEqual(labelOps[0].to,[12,0]);
window.promptInput=async()=>"8'-0\"";
labelNodes[1].dispatchEvent(new Event('click'));await new Promise(r=>setImmediate(r));
assert.equal(labelOps[1].op,'move_wall');assert.deepEqual(labelOps[1].by,[-0,2],'distance label keeps its click-to-type operation');
document.createElement=createElement;dimensionAbort.abort();
ok('rendered labels use pure R47b placement at every zoom and oblique view; length and distance labels retain click-to-type');

// Retained buttons must follow their current rendered box after layout/font
// changes, even though their displayed distance and text have not changed.
let preciseWidth=47, preciseHeight=1, horizontal=false;
const preciseHost=new Element(), preciseView={renderer3:{domElement:new Element()},controls:new EventTarget(),screenOfFloor:(x,y)=>{
  const point=[506+x*(31.698/(79/12)),541.682-y*8.3364];
  return horizontal?[506+point[1]-500,500+point[0]-506]:point;
}};
preciseHost.append(preciseView.renderer3.domElement);
document.createElement=tag=>{const node=createElement(tag);if(tag==='button')node.getBoundingClientRect=()=>({width:preciseWidth,height:preciseHeight});return node;};
const OriginalResizeObserver=globalThis.ResizeObserver;let sizeChanged;
const observedButtons=new Set();
globalThis.ResizeObserver=class {constructor(callback){sizeChanged=callback;}observe(node){observedButtons.add(node);}unobserve(node){observedButtons.delete(node);}disconnect(){observedButtons.clear();}};
const preciseAbort=new AbortController();
const preciseDimensions=createDimensions({view:preciseView,canEdit:()=>true,onCommit:()=>{},signal:preciseAbort.signal,getHandles:()=>[]});
const preciseWall={id:'refusal',level:'L1',from:[0,0],to:[0,10],joints:['a','b']};
preciseDimensions.show({building:{id:'refusal-house',walls:[preciseWall,{id:'neighbour',level:'L1',from:[-79/12,0],to:[-79/12,10]}]},piece:preciseWall});
const preciseButton=preciseHost.children.at(-1).children[1];
assert.equal(preciseButton['aria-label'],"Distance to wall: 6'-7\"");
const assertPreciseBox=()=>assert.ok(rectangleDistance(refusalGrab,[parseFloat(preciseButton.style.left),parseFloat(preciseButton.style.top)],
  {width:preciseWidth,height:44})>=24,'actual button box clears the press point by 24px');
assertPreciseBox();
preciseHeight=44;horizontal=true;preciseView.controls.dispatchEvent(new Event('change'));assertPreciseBox();
assert.ok(observedButtons.has(preciseButton));
preciseWidth=147;sizeChanged([{target:preciseButton}]);assertPreciseBox();
assert.equal(preciseHost.children.at(-1).children[1],preciseButton,'size changes retain the same clickable button');
preciseAbort.abort();assert.equal(observedButtons.size,0);globalThis.ResizeObserver=OriginalResizeObserver;document.createElement=createElement;
ok('retained neighbour label uses its current rendered size after a layout change without a text change');

// Execute the caller with distinct floor/top projections and elevated handles.
// A floor-only midpoint would miss the controller's visible-face press point.
const faceHost=new Element(),projectionHeights=[];
const faceView={renderer3:{domElement:new Element()},controls:new EventTarget(),screenOfFloor:(x,y,key,z=0)=>{
  projectionHeights.push(z);return [520+x*(31.698/(79/12))-z*2.8,570-y*4-z*8];
}};
faceHost.append(faceView.renderer3.domElement);
document.createElement=tag=>{const node=createElement(tag);if(tag==='button')node.getBoundingClientRect=()=>refusalSize;return node;};
const faceWall={...preciseWall,height:10},faceAbort=new AbortController();
const faceDimensions=createDimensions({view:faceView,canEdit:()=>true,onCommit:()=>{},signal:faceAbort.signal,
  getHandles:()=>[{kind:'wall',id:faceWall.id,at:[0,5,17]}]});
faceDimensions.show({building:{id:'face',levels:[{id:'L1',elevation:12,ceiling:10}],walls:[faceWall,
  {id:'neighbour',level:'L1',from:[-79/12,0],to:[-79/12,10]}]},piece:faceWall});
assert.ok(projectionHeights.includes(10),'caller projects the top at wall height');
assert.ok(projectionHeights.includes(5),'handle height is relative to its level, not projected onto the floor');
for(const node of faceHost.children.at(-1).children){
  assert.equal(node.hidden,false);
  const centre=[parseFloat(node.style.left),parseFloat(node.style.top)];
  assert.ok(polygonDistance(refusalQuad,centre,refusalSize)>=24,'DOM caller passes the full projected quad to placement');
  assert.ok(rectangleDistance([506,510],centre,refusalSize)>=24,'elevated handle also clears the full label box');
}
faceAbort.abort();document.createElement=createElement;
ok('dimensions caller protects actual wall height and level-relative 3D handle projections');

const deps = piecesOnMovedJoints({
  walls:[{id:'wall',joints:['a','b']},{id:'stem',joints:['b','c']},{id:'remote',joints:['d','e']}],
  rooms:[{id:'left',joints:['a','b','c']},{id:'crossing',joints:['derived','d','e']},{id:'far',joints:['d','e','f']}],
  openings:[{id:'door',wall:'wall'},{id:'remote-door',wall:'remote'}],
  anchors:[{id:'switch',host:{wall:'stem'}},{id:'roof',host:{roof:'roof'}},{id:'ground',host:{ground:true,at:[0,0]}}],
  items:[{id:'chair',host:{floor:'left'}},{id:'light',host:{ceiling:'crossing'}},{id:'far-chair',host:{floor:'far'}}],
}, ['b','derived']);
assert.deepEqual(deps,{walls:['wall','stem'],rooms:['left','crossing'],openings:['door'],anchors:['switch'],items:['chair','light']});
ok('joint dependencies include attached walls, derived room crossings and hosts, excluding remote pieces');

// Exact plan ids survive both batching modes, including persisted T splits.
for (const editableLevel of [null,'main-house:L1']) {
  const twin = buildTwin(flat, kit, 'low', {editableLevel}); await twin.ready;
  let split = 0;
  for (const b of flat.buildings) for (const wall of b.walls) {
    const key = b.id + ':' + wall.id;
    if (wall.kind === 'separator') {
      assert.equal(twin.pieceBounds.has(key),false);
      assert.equal(twin.pickObjects.has(key),false);
    } else {
      assert.ok(twin.pieceBounds.has(key), 'registered wall: ' + key);
      assert.equal(twin.pickObjects.get(key).userData.pieceId, wall.id);
      assert.ok(twin.pieces.get(key).every(o=>o.parent), 'registry holds live render objects');
      if (wall.id.includes('~')) split++;
    }
  }
  assert.ok(split > 0, 'fixture exercises R31b ids');
  disposeObject(twin.root);
}
ok('batched and focused household solid walls retain exact plan ids; separators stay absent');

const host = new Element(), view = await mountTwin(host,{plan:flat,kit,tier:'low',preserveCamera:true});
await view.setEditableLevel('main-house:L1'); view.setView('main-house:L1');
// Keep the geometry-transport fixture close enough that remote extensions are outside R45's reach.
view.camera.zoom=8;view.camera.updateProjectionMatrix();
const b = flat.buildings.find(b=>b.id==='main-house'), original = JSON.stringify(flat);
const roomA = 'room:070aa0ca32b94170968a5e2cbf0fcc6f', roomB = 'room:6ae35a0dcd044566b9f9956dd1b2b4e3';
const wallId = 'wall:738a2cbddd52469a968bac0b57b29ebc', wall = b.walls.find(w=>w.id===wallId);
const sel = {kind:'wall',id:wallId,building:b.id,level:'L1',room:roomA};
view.setSelection({selected:sel,room:{kind:'room',building:b.id,level:'L1',id:roomA,walls:[wallId],allowed:[wallId,roomA]}});
const selectionValue={selected:sel,room:{kind:'room',building:b.id,level:'L1',id:roomA,walls:[wallId],allowed:[wallId,roomA]}};
const hoverMaterials=new Map(), selectedLines=[];let hoverDisposals=0;
view.scene.traverse(o=>{
  if(o.isMesh&&o.material){hoverMaterials.set(o,o.material);for(const m of [].concat(o.material))m.addEventListener('dispose',()=>hoverDisposals++);}
  if(o.userData.selectionKey&&!o.userData.isHover)selectedLines.push(o);
});
for(const hover of [{kind:'wall',id:wallId,building:b.id}, {kind:'room',id:roomA,building:b.id}, null]) {
  view.setSelection({...selectionValue,hover});
  for(const [o,m] of hoverMaterials)assert.equal(o.material,m,'hover retains tint and ghost materials');
  for(const line of selectedLines)assert.ok(line.parent,'hover retains selected outlines');
}
assert.equal(hoverDisposals,0);
ok('hover only swaps hover outlines, retaining room and yard materials and the selected outline');

const abort = new AbortController(), ops = [];
const dimensions = createDimensions({view,onCommit:op=>ops.push(op),canEdit:()=>true,signal:abort.signal});
let preview;
const drag = createDrag({view,model:()=>flat,onCommit:op=>ops.push(op),onPreview:p=>{
  preview=p;const building=p.buildings.find(b=>b.id===sel.building);
  dimensions.show({building,piece:building.walls.find(w=>w.id===wallId)});
}});
const extent = id => {const box=view.worldBox(id,b.id);return box.max[1]-box.min[1];};
const a0=extent(roomA), b0=extent(roomB), box0=view.worldBox(wallId,b.id);
const roofs=JSON.stringify(view.roofStats());
const materials=new Map(); let disposed=0;
view.scene.traverse(o=>{if(o.material) {materials.set(o,o.material); for(const m of [].concat(o.material))m.addEventListener('dispose',()=>disposed++);}
});
assert.ok(drag.begin(sel,[2.5,wall.from[1]]));
let labels;
for(let step=1;step<=12;step++) {
  const before=renders; assert.ok(drag.update([2.5,wall.from[1]-step/12]));
  assert.equal(renders-before,1,'one render submission per preview');
  assert.equal(disposed,0,'no scene-wide selection material disposal');
  for(const [o,m] of materials)assert.equal(o.material,m,'selection material identity is retained');
  const now=host.children.at(-1).children;
  if(labels)assert.deepEqual(now,labels,'dimension buttons are reused through the gesture');
  labels=[...now];
  assert.ok(drag.lastDragFrameMs>0);
}
assert.equal(labels.length,3);
assert.equal(ops.length,0); assert.equal(JSON.stringify(flat),original);
assert.equal(JSON.stringify(view.roofStats()),roofs);
const cos=Math.cos((b.rotation||0)*Math.PI/180);
assert.ok(Math.abs(extent(roomA)-a0+cos)<.02,'one adjacent floor shrinks');
assert.ok(Math.abs(extent(roomB)-b0-cos)<.02,'the other adjacent floor grows');
assert.notDeepEqual(view.worldBox(wallId,b.id),box0);
await drag.finish(); assert.equal(ops.length,1); assert.equal(ops[0].op,'move_wall');
assert.ok(Math.abs(ops[0].by[1]+1)<.02);
ok('real household buffers and both floors preview with retained materials, labels and one release op');

// The retained button must use the latest distance and operation, not the
// first preview's closure. Set the southern gap to its current value - 1 ft.
const latest = preview.buildings.find(row=>row.id===b.id);
const currentY = latest.walls.find(w=>w.id===wallId).from[1];
window.promptInput=async()=>`10'-0"`;
labels[1].dispatchEvent(new Event('click')); await new Promise(r=>setImmediate(r));
assert.equal(ops.length,2); assert.equal(ops[1].op,'move_wall');
assert.ok(Math.abs(ops[1].by[1]-(14.333333333333334+10-currentY))<.01,'button uses the current gap');
view.rebuildLevel(b.id,'L1',flat);
assert.ok(drag.begin(sel,[2.5,wall.from[1]])); drag.update([2.5,wall.from[1]-2]); await drag.finish(true);
assert.equal(ops.length,2);
const reset=view.worldBox(wallId,b.id);
assert.ok(Math.abs(reset.min[0]-box0.min[0])<.001 && Math.abs(reset.max[1]-box0.max[1])<.001);
ok('retained dimension button commits its latest value and cancellation restores geometry without an op');

const perfWall = b.walls.find(w=>w.id==='wall:27baac0e440145c2aaeab79271823cba');
const perfSelection = {kind:'wall',id:perfWall.id,building:b.id,level:'L1'};
const perfBox = view.worldBox(perfWall.id,b.id), otherBox = view.worldBox(wallId,b.id);
let touched;
const rebuildLevel = view.rebuildLevel.bind(view);
view.rebuildLevel = (building,level,plan,pieces)=>{touched=pieces;rebuildLevel(building,level,plan,pieces);};
const refused = createDrag({view,model:()=>flat,onCommit:()=>{throw new Error('refused');}});
assert.ok(refused.begin(perfSelection,[52.5,perfWall.from[1]]));
for(let step=1;step<=12;step++)refused.update([52.5,perfWall.from[1]+step/4]);
assert.ok(touched.walls.length < b.walls.filter(w=>w.level==='L1').length);
assert.ok(touched.rooms.includes('room:b3fc2ad6ea584ed3a9ac77f47983dd61'));
assert.ok(touched.rooms.includes('room:e7b4abf892a4489ba8142fe31395d15c'));
assert.deepEqual(view.worldBox(wallId,b.id),otherBox,'unconnected wall bounds stay untouched');
assert.notDeepEqual(view.worldBox(perfWall.id,b.id),perfBox);
await assert.rejects(refused.finish(),/refused/);
const rolledBack = view.worldBox(perfWall.id,b.id);
assert.ok(Math.abs(rolledBack.min[0]-perfBox.min[0])<.001 && Math.abs(rolledBack.max[1]-perfBox.max[1])<.001);
ok('P3 wall passes only its connected pieces and a refused release rolls back the preview');
const yard = view.groups.site.getObjectByName('test-yard'), yardCount=globalThis.yardBuilds;
const waitReady=async()=>{while(!view.ready)await new Promise(r=>setTimeout(r,1));};
view.setSelection({selected:null,room:null,hover:null});await waitReady();
assert.equal(view.groups.site.getObjectByName('test-yard'),yard);
assert.equal(globalThis.yardBuilds,yardCount);
const batchedCount=()=>{let n=0;view.scene.traverse(o=>{if(o.isMesh&&!o.layers.isEnabled(31))n++;});return n;};
const batched=batchedCount();
view.setSelection(selectionValue);await waitReady();assert.ok(batchedCount()>batched);
view.setSelection({selected:{kind:'building',id:b.id,building:b.id},room:null});await waitReady();
assert.equal(batchedCount(),batched,'selecting the building returns focused geometry to batches');
await view.setEditableLevel('pool-house:L1');await view.setEditableLevel('main-house:L2');await view.setEditableLevel(null);
assert.equal(globalThis.yardBuilds,yardCount,'floor switches never regenerate yard trees');
assert.equal(view.groups.site.getObjectByName('test-yard'),yard);
ok('leaving focus restores batches; selecting buildings and switching floors preserve the same yard');
abort.abort(); view.dispose();
console.log(`${passed}/${passed} passed`);
"""


def run():
    if not shutil.which('node'):
        print('SKIP node is unavailable')
        return
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    paths = []
    try:
        for suffix, content in [('.mjs', DRIVER), ('.json', json.dumps({'root':ROOT.as_posix(),'flat':flat,'kit':kit}))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_drag_', delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([shutil.which('node'), str(paths[0]), str(paths[1])], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
