"""Pure local moves match the household drag preview. Run from chauffeur/."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = r"""
const {LocalMissing, moveGesture, movePreview, applyLocal} = await import(file('static/twin/editor/local_ops.js'));
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
"""


def run():
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    flat = flatten(assemble(fixture)[0])
    code, output = run_node(PRELUDE + DRIVER, {'root': ROOT.as_posix(), 'flat': flat})
    print(output, end='')
    if code is not None:
        assert code == 0, output


if __name__ == '__main__':
    run()
