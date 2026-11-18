"""Pure local moves match the household drag preview. Run from chauffeur/."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = r"""
const {LocalMissing, moveGesture, movePreview, applyLocal, moveProblem} = await import(file('static/twin/editor/local_ops.js'));
const {createDrag} = await import(file('static/twin/editor/drag.js'));
const plan = input.flat, before = structuredClone(plan);
const building = plan.buildings.find(b => b.walls.some(w => w.state !== 'ghost'));
const wall = building.walls.find(w => w.state !== 'ghost');
const selection = {kind:'wall', building:building.id, id:wall.id};
const d = wall.to.map((v,i) => v-wall.from[i]), length = Math.hypot(...d);
const normal = [-d[1]/length, d[0]/length];
const operation = {op:'move_wall', building:building.id, wall:wall.id, by:1};
let passed = 0;
const ok = name => {passed++; console.log('  ok ' + name);};
const freeze = value => {
  if (value && typeof value === 'object') { Object.freeze(value); Object.values(value).forEach(freeze); }
};
freeze(plan);

let preview;
const drag = createDrag({model:()=>plan, onCommit:()=>{}, view:{
  screenOfFloor:(x,y)=>[x*1e6,y*1e6], floorAt:(x,y)=>[x/1e6,y/1e6],
  rebuildLevel:(b,l,p)=>{preview=p;}
}});
const start = wall.from.map((v,i)=>(v+wall.to[i])/2);
assert.equal(drag.begin(selection,start),true);
assert.equal(drag.update(start.map((v,i)=>v+normal[i])),true);
assert.ok(preview,'drag must draw the one-foot move');
const moved = applyLocal(plan,operation);
assert.deepEqual(moved.plan,preview);
assert.deepEqual(applyLocal(plan,{...operation,by:normal}).plan,preview);
assert.equal(moved.building,building.id); assert.equal(moved.level,wall.level);
assert.deepEqual(moved.touched,moveGesture(plan,selection).touched);
const joint = moved.plan.buildings.find(b=>b.id===building.id).joints.find(j=>j.id===wall.joints[0]);
const oldJoint = building.joints.find(j=>j.id===wall.joints[0]);
assert.deepEqual(joint.at,oldJoint.at.map((v,i)=>v+normal[i]));
await drag.finish(true);
ok('move_wall_matches_drag_preview');

assert.deepEqual(plan,before);
assert.notEqual(moved.plan,plan); assert.notEqual(moved.plan.site,plan.site);
ok('input_plan_untouched');

assert.throws(()=>applyLocal(plan,{...operation,wall:'nope'}),LocalMissing);
for (const op of [{...operation,building:'nope'},
  {op:'move_joint',building:building.id,joint:'nope',to:[0,0]},
  {op:'move_room',building:building.id,room:'nope',by:[1,0]},
  {op:'move_site_item',list:'planting',id:'nope',by:[1,0]},
  {op:'move_site_item',list:'planting',index:-1,by:[1,0]}]) assert.throws(()=>applyLocal(plan,op),LocalMissing);
ok('missing_piece_throws');

const plant = plan.site.planting[0]; assert.ok(plant);
const plantAt = applyLocal(plan,{op:'move_site_item',list:'planting',id:plant.id,at:[5,6]});
assert.deepEqual(plantAt.plan.site.planting[0].at,[5,6]);
const plantBy = applyLocal(plantAt.plan,{op:'move_site_item',list:'planting',index:0,by:[1,0]});
assert.deepEqual(plantBy.plan.site.planting[0].at,[6,6]);
assert.deepEqual(plantAt.touched,{site:['planting']}); assert.deepEqual(plantBy.touched,{site:['planting']});
assert.equal(plantAt.building,null); assert.equal(plantAt.level,null);
assert.deepEqual(plan,before);
ok('site_item_moves');

const transforms = {buildings:[{id:'b',levels:[{id:'L'}],walls:[],rooms:[],anchors:[],
  items:[{id:'chair',host:{ground:true,at:[1,2]}}]}],site:{planting:[{id:'tree',at:[0,0]}],
  pool:{id:'pool',polygon:[[0,0],[4,0],[0,4]]},beds:[{id:'bed',polygon:[[0,0],[2,0],[0,2]]}]}};
const transformBefore=structuredClone(transforms), properties={rotation:33,scale:2,scale_axes:[2,1,3]};
for(const target of [{building:'b',id:'chair'},{list:'planting',index:0}]) {
  const result=applyLocal(transforms,{op:'set_object',...target,properties});
  const piece=target.building?result.plan.buildings[0].items[0]:result.plan.site.planting[0];
  for(const [key,value] of Object.entries(properties))assert.deepEqual(piece[key],value);
}
for(const target of [{list:'beds',index:0},{list:'pool',index:0}]) {
  const polygon=[[1,1],[6,1],[1,6]],result=applyLocal(transforms,{op:'update_site_shape',...target,polygon,rotation:15});
  const piece=target.list==='pool'?result.plan.site.pool:result.plan.site.beds[0];assert.deepEqual(piece.polygon,polygon);assert.equal(piece.rotation,15);
}
assert.deepEqual(applyLocal(transforms,{op:'move_hosted',building:'b',id:'chair',host:{ground:true,at:[4,5]}}).plan.buildings[0].items[0].host.at,[4,5]);
assert.throws(()=>applyLocal(transforms,{op:'set_object',building:'b',id:'gone',properties}),LocalMissing);
assert.throws(()=>applyLocal(transforms,{op:'update_site_shape',list:'beds',index:5,rotation:15}),LocalMissing);
assert.deepEqual(transforms,transformBefore);ok('object_and_shape_transforms_are_pure_and_missing_targets_refused');
assert.equal(applyLocal(transforms,{op:'move_hosted',building:'b',id:'opening',at:3}),null,'opening slides retain their existing supplied-preview path');

const splitPlan={buildings:[{id:'s',levels:[{id:'L',footprint:['a','b','c'],outline:[[0,0],[10,0],[10,10]]}],
  joints:[{id:'a',level:'L',at:[0,0]},{id:'b',level:'L',at:[10,0]},{id:'c',level:'L',at:[10,10]}],
  walls:[{id:'w',level:'L',joints:['a','b'],from:[0,0],to:[10,0],footprint:[[0,.25],[10,.25],[10,-.25],[0,-.25]]}],
  rooms:[{id:'r',joints:['a','b','c']}],openings:[],items:[{id:'i',host:{wall:'w',at:7,z:2}}],anchors:[]}]};
const splitSaved=structuredClone(splitPlan),sop={op:'split_wall',building:'s',wall:'w',at:4};
const sb=applyLocal(splitPlan,sop).plan.buildings[0];assert.deepEqual(sb.items[0].host,{wall:'w~2',at:3,z:2});
assert.equal(sb.rooms[0].joints.length,4);assert.deepEqual(sb.walls[0].footprint,[[0,.25],[4,.25],[4,-.25],[0,-.25]]);
assert.deepEqual(sb.walls[1].footprint,[[4,.25],[10,.25],[10,-.25],[4,-.25]]);
assert.deepEqual(applyLocal(splitPlan,sop).plan.buildings[0],sb,'replay IDs stay stable');
assert.deepEqual(splitPlan,splitSaved);assert.equal(applyLocal(splitPlan,{...sop,at:.5}),null);
const sameWall=applyLocal(splitPlan,{op:'move_joint',building:'s',joint:'a',to:[9.5,0]});
assert.equal(sameWall.plan.buildings[0].joints.length,3,'never weld an incident short wall');
ok('split_hosts_footprints_rooms_stable_replay_and_neighbour_weld_exclusion');

assert.equal(applyLocal(plan,{op:'add_opening',building:building.id,wall:wall.id}),null);
for(const op of ['unknown','constructor','toString','__proto__']) assert.equal(applyLocal(plan,{op}),null);
ok('other_ops_return_null');

const g = moveGesture(plan,selection), gBefore = structuredClone(g);
assert.ok(g.moved instanceof Set); assert.ok(g.oldWalls instanceof Map); assert.deepEqual(g.normal,normal);
assert.deepEqual(movePreview(plan,g,normal),moved.plan);
assert.deepEqual(movePreview(plan,g,normal),movePreview(plan,g,normal));
assert.deepEqual(g,gBefore); assert.deepEqual(plan,before);
ok('gesture_and_preview_are_pure');

for (const kind of ['joint','room']) {
  const piece = building[kind==='joint'?'joints':'rooms'].find(p=>p.state!=='ghost');
  const s = {kind,building:building.id,id:piece.id}, by = [.25,-.5];
  const op = {op:'move_'+kind,building:building.id,[kind]:piece.id};
  if(kind==='joint') op.to=piece.at.map((v,i)=>v+by[i]); else op.by=by;
  const result = applyLocal(plan,op), gesture = moveGesture(plan,s);
  assert.deepEqual(result.plan,movePreview(plan,gesture,by));
  assert.equal(result.level,piece.level); assert.deepEqual(result.touched,gesture.touched);
  const b = result.plan.buildings.find(b=>b.id===building.id);
  for(const id of gesture.moved) assert.deepEqual(b.joints.find(j=>j.id===id).at,
    building.joints.find(j=>j.id===id).at.map((v,i)=>v+by[i]));
}
assert.deepEqual(plan,before);
ok('joint_and_room_moves');

const ghost = structuredClone(plan);
ghost.buildings.find(b=>b.id===building.id).walls.find(w=>w.id===wall.id).state='ghost';
assert.throws(()=>moveGesture(ghost,selection),LocalMissing);
assert.throws(()=>applyLocal(ghost,operation),LocalMissing);
assert.equal(createDrag({model:ghost,view:{}}).begin(selection,[0,0]),false);
assert.equal(createDrag({model:plan,view:{}}).begin({...selection,id:'nope'},[0,0]),false);
ok('ghost_and_missing_drag_still_refused');

const shape = {id:'shape',at:[1,2],polygon:[[0,0],[2,0],[2,2]],points:[[3,4]],polyline:[[5,6],[7,8]],
  features:[{polygon:[[1,1],[2,1],[2,2]]}]};
for(const singleton of [false,true]) {
  const source = {...plan,site:{pool:singleton?shape:[shape]}}, saved = structuredClone(source);
  const result = applyLocal(source,{op:'move_site_item',list:'pool',...(singleton?{}:{id:'shape'}),by:[1,0]});
  const piece = singleton?result.plan.site.pool:result.plan.site.pool[0];
  assert.deepEqual(piece.at,[2,2]);
  for(const key of ['polygon','points','polyline']) assert.deepEqual(piece[key],shape[key].map(p=>[p[0]+1,p[1]]));
  assert.deepEqual(piece.features[0].polygon,[[2,1],[3,1],[3,2]]);
  assert.deepEqual(result.touched,{site:['pool']}); assert.deepEqual(source,saved);
}
ok('site_shapes_and_pool_features_translate');

const noAt = {...plan,site:{beds:[{id:'bed',polygon:[[0,0],[1,0],[1,1]]}]}};
assert.equal(applyLocal(noAt,{op:'move_site_item',list:'beds',id:'bed',at:[5,6]}),null);
assert.throws(()=>applyLocal(plan,{op:'move_site_item',list:'nope',id:'nope',by:[1,0]}),LocalMissing);
ok('site_shape_at_falls_back_and_missing_list_throws');

const collapse = {buildings:[{id:'c',levels:[{id:'L1',elevation:0}],rooms:[],
  joints:[{id:'a',level:'L1',at:[0,0]},{id:'b',level:'L1',at:[0,5]},
    {id:'c',level:'L1',at:[4,5]}],walls:[
    {id:'W',level:'L1',from:[0,0],to:[0,5],joints:['a','b']},
    {id:'A',level:'L1',from:[0,5],to:[4,5],joints:['b','c']}]}]};
const collapseBefore = structuredClone(collapse), cg = moveGesture(collapse,{kind:'wall',building:'c',id:'W'});
assert.equal(movePreview(collapse,cg,[4,0]),null);
assert.equal(applyLocal(collapse,{op:'move_wall',building:'c',wall:'W',by:[4,0]}),null);
assert.deepEqual(collapse,collapseBefore);
ok('collapsed_wall_returns_null');
console.log(`${passed}/${passed} local-op checks passed`);

// Keep an actual household wall and its hosts, isolated from unrelated rooms
// so each refusal has one cause. All after geometry comes from movePreview.
function checkFixture() {
  const source = structuredClone(plan), b = source.buildings.find(b => b.id === building.id);
  const w = b.walls.find(w => w.state !== 'ghost' && Math.hypot(...delta2(w.to,w.from)) > 8);
  b.walls = [w]; b.rooms = []; b.joints = b.joints.filter(j => w.joints.includes(j.id));
  b.openings = []; b.anchors = []; b.items = [];
  const axis = delta2(w.to,w.from), length = Math.hypot(...axis);
  return {source,b,w,length,axis:axis.map(v=>v/length)};
}
const delta2 = (a,b) => a.map((v,i)=>v-b[i]);
function shorten(f, length) {
  return movePreview(f.source,moveGesture(f.source,{kind:'joint',building:f.b.id,id:f.w.joints[1]}),
    f.axis.map(v=>v*(length-f.length)));
}
let shortText, narrowText, crossText;
await test('short_wall_problem', () => {
  const f = checkFixture(), saved = structuredClone(f.source), after = shorten(f,.5);
  shortText = moveProblem(f.source,after,f.b.id);
  assert.equal(shortText,'A wall must be at least 1 ft long.');
  assert.equal(moveProblem(f.source,shorten(f,1),f.b.id),null);
  assert.deepEqual(f.source,saved);
});
await test('narrow_door_problem', () => {
  for (const name of ['openings','anchors','items']) {
    const f = checkFixture();
    f.b[name] = [{id:'hosted',width:3,...(name==='openings'?{wall:f.w.id}:{host:{wall:f.w.id,at:2,side:'left'}})}];
    narrowText = moveProblem(f.source,shorten(f,3.5),f.b.id);
    assert.equal(narrowText,'That would leave the door narrower than its wall.');
    assert.equal(moveProblem(f.source,shorten(f,4),f.b.id),null);
    assert.equal(moveProblem(f.source,shorten(f,.5),f.b.id),'A wall must be at least 1 ft long.');
    // Only shortening, not translation/lengthening, invokes host clearance.
    f.b[name][0].width = f.length + 2;
    assert.equal(moveProblem(f.source,shorten(f,f.length+1),f.b.id),null);
  }
});
function addLine(f, a, b, level=f.w.level, state='settled') {
  const id = 'obstacle';
  f.b.joints.push({id:id+'a',level,at:a},{id:id+'b',level,at:b});
  f.b.walls.push({id,level,state,from:a,to:b,joints:[id+'a',id+'b']});
}
function along(f, x, y) {
  return f.w.from.map((v,i)=>v+f.axis[i]*x+[-f.axis[1],f.axis[0]][i]*y);
}
function translate(f, distance) {
  return movePreview(f.source,moveGesture(f.source,{kind:'wall',building:f.b.id,id:f.w.id}),
    [-f.axis[1]*distance,f.axis[0]*distance]);
}
await test('crossing_problem', () => {
  const f = checkFixture(); addLine(f,along(f,2,1),along(f,2,3));
  crossText = moveProblem(f.source,translate(f,2),f.b.id);
  assert.equal(crossText,'That would cross another wall.');
  const overlap = checkFixture(); addLine(overlap,along(overlap,2,2),along(overlap,4,2));
  assert.equal(moveProblem(overlap.source,translate(overlap,2),overlap.b.id),crossText);
});
await test('clean_move_has_no_problem', () => {
  const f = checkFixture(); assert.equal(moveProblem(f.source,translate(f,1),f.b.id),null);
  for (const mode of ['other_level','ghost','existing_crossing','existing_overlap','endpoint']) {
    const f = checkFixture();
    if (mode==='existing_overlap') addLine(f,along(f,2,0),along(f,4,0));
    else addLine(f,along(f,2,mode==='existing_crossing'?-2:1),along(f,2,3),
      mode==='other_level'?'another-level':f.w.level,mode==='ghost'?'ghost':'settled');
    const after = mode==='existing_overlap' ? shorten(f,f.length-1) : translate(f,mode==='endpoint'?1:2);
    assert.equal(moveProblem(f.source,after,f.b.id),null,mode);
  }
  // An unchanged short wall is not a new problem.
  const small = shorten(f,.5); assert.equal(moveProblem(small,small,f.b.id),null);
});
await test('texts_match_server', () => {
  assert.deepEqual([shortText,narrowText,crossText],input.serverTexts);
});
await test('drag_problem_displays_clears_and_still_releases', async () => {
  const {createDimensions} = await import(file('static/twin/editor/dimensions.js'));
  const f = checkFixture(), canvas = document.createElement('canvas'), host = document.createElement('div');
  document.body.append(host); host.append(canvas);
  const abort = new AbortController(), commits = [], frames = [];
  const view = {renderer3:{domElement:canvas},controls:new Element('controls'),
    screenOfFloor:(x,y)=>[700+(x-f.w.from[0])*100,400+(y-f.w.from[1])*100],
    floorAt:(x,y)=>[(x-700)/100+f.w.from[0],(y-400)/100+f.w.from[1]],
    rebuildLevel() {}};
  const dimensions = createDimensions({view,canEdit:()=>true,onCommit:()=>{},signal:abort.signal});
  const status = document.getElementById('editor-status'); status.textContent = 'Ready';
  const drag = createDrag({view,model:f.source,onPreview(p,s,problem) {
    const b = p.buildings.find(b=>b.id===f.b.id);
    dimensions.show({building:b,piece:b.walls.find(w=>w.id===f.w.id),problem});
    frames.push(problem ?? null);
  },onCommit(op) {
    assert.equal(status.textContent,'Ready','clears before waiting for the server'); commits.push(op);
  }});
  const selection = {kind:'joint',building:f.b.id,id:f.w.joints[1]};
  assert.ok(drag.begin(selection,f.w.to)); drag.update(along(f,.5,0));
  assert.equal(frames.at(-1),input.serverTexts[0]);
  assert.equal(status.textContent,input.serverTexts[0]);
  assert.ok(host.querySelector('[data-dimension="Wall length"]').textContent.includes(input.serverTexts[0]));
  status.textContent = 'Ready'; // A normal editor refresh during the gesture.
  drag.update(along(f,.5,0)); assert.equal(status.textContent,input.serverTexts[0]);
  drag.update(along(f,4,0));
  assert.equal(status.textContent,'Ready');
  assert.ok(!host.textContent.includes(input.serverTexts[0]));
  drag.update(along(f,.5,0)); await drag.finish();
  assert.equal(commits.length,1); assert.equal(commits[0].op,'move_joint');
  assert.ok(!host.textContent.includes(input.serverTexts[0]));
  assert.ok(drag.begin(selection,f.w.to)); drag.update(along(f,.5,0));
  status.textContent = 'A newer status'; await drag.finish(true);
  assert.equal(status.textContent,'A newer status','does not overwrite a newer editor status');
  assert.ok(!host.textContent.includes(input.serverTexts[0])); assert.equal(commits.length,1);
  abort.abort(); host.remove();
});
await test('collapsed_drag_keeps_the_last_drawn_frame', async () => {
  // A wall dragged onto its neighbour's corner has no direction; the drag keeps
  // and releases the last drawn frame, as it did before the checks existed.
  const f = checkFixture(), drawn = [], notices = [], ops = [];
  const drag = createDrag({model:f.source,view:{screenOfFloor:(x,y)=>[x*1e6,y*1e6],
    floorAt:(x,y)=>[x/1e6,y/1e6],rebuildLevel:(b,l,p)=>drawn.push(p)},
    onPreview:(p,s,problem)=>notices.push(problem ?? null),onCommit:(op,options)=>{ ops.push({op,options}); }});
  assert.ok(drag.begin({kind:'joint',building:f.b.id,id:f.w.joints[1]},f.w.to));
  drag.update(f.w.from);
  assert.equal(drawn.length,0); assert.equal(notices.length,0);
  await drag.finish();
  assert.equal(ops.length,0,'nothing drawn, nothing sent');
  assert.ok(drag.begin({kind:'joint',building:f.b.id,id:f.w.joints[1]},f.w.to));
  drag.update(along(f,4,0)); const kept = drawn.at(-1); drag.update(f.w.from);
  assert.equal(drawn.at(-1),kept);
  await drag.finish();
  assert.equal(notices.at(-1),null); assert.equal(ops.length,1);
  assert.ok(Math.hypot(...ops[0].op.to.map((v,i)=>v-along(f,4,0)[i])) < 1e-9); assert.equal(ops[0].options.local,kept);
});
await test('scene_tools_connects_joint_warning_to_label_and_status', async () => {
  registerHooks({resolve(spec,ctx,next) {
    if (!ctx.parentURL?.endsWith('/scene_tools.js')) return next(spec,ctx);
    const stubs = {
      './cards.js': `export * from '${file('static/twin/editor/cards.js')}'; export const createCards=()=>({});`,
      './handles.js': `export const createHandles=options=>{globalThis.sceneDrag=options.drag;return {show(){},refresh(){},handles:()=>[],active:()=>false};};`,
      './ha_link.js': 'export const createHaLink=()=>({});',
    };
    return stubs[spec] ? {url:data(stubs[spec]),shortCircuit:true} : next(spec,ctx);
  }});
  const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
  const f = checkFixture(), host = document.createElement('div'), canvas = document.createElement('canvas');
  document.body.append(host); host.append(canvas);
  const abort = new AbortController(), commits = [], status = document.getElementById('editor-status');
  status.textContent = 'Ready';
  const view = {renderer3:{domElement:canvas},controls:new Element('controls'),
    screenOfFloor:(x,y)=>[x*1e6,y*1e6],floorAt:(x,y)=>[x/1e6,y/1e6],rebuildLevel(){}};
  createSceneTools({view,getPlan:()=>f.source,getModel:()=>f.source,getKit:()=>({}),getSheets:()=>({}),
    canEdit:()=>true,op:op=>commits.push(op),signal:abort.signal});
  sceneDrag.begin({kind:'joint',building:f.b.id,id:f.w.joints[1],level:f.w.level},f.w.to);
  sceneDrag.update(along(f,.5,0));
  assert.equal(status.textContent,input.serverTexts[0]);
  assert.ok(host.querySelector('[data-dimension="Wall length"]').textContent.includes(input.serverTexts[0]));
  await sceneDrag.finish(); assert.equal(status.textContent,'Ready'); assert.equal(commits.length,1);
  assert.ok(!host.textContent.includes(input.serverTexts[0]));
  abort.abort(); host.remove();
});
finish();
"""


def run():
    from services.twin_model_bridge import assemble, flatten
    from services import twin_model_ops
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    flat = flatten(assemble(fixture)[0])
    code, output = run_node(PRELUDE + DRIVER, {'root': ROOT.as_posix(), 'flat': flat,
        'serverTexts': [twin_model_ops._SHORT, twin_model_ops._NARROW, twin_model_ops._CROSS]})
    print(output, end='')
    if code is not None:
        assert code == 0, output


if __name__ == '__main__':
    run()
