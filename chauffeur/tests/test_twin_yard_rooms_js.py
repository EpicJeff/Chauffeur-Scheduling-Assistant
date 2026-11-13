"""Run yard-room navigation and live controls through the mounted JS paths."""
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node
from twin_live_node_rig import run as run_live

ROOT = Path(__file__).resolve().parents[1]

NAVIGATION = PRELUDE + r"""
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {deviceAtLevel} = await import(file('static/twin/levels.js'));
const rect = (x,y) => [[x,y],[x+10,y],[x+10,y+10],[x,y+10]];
const b = {id:'b',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:8,outline:rect(0,0)}],
 rooms:[{id:'inside',level:'L1',polygon:rect(0,0)}],walls:[],openings:[],lights:[],roof:{sections:[]}};
const host = new Element(); document.body.append(host);
const v = await mountTwin(host,{plan:{buildings:[b],site:{
 terraces:[{polygon:[[15,-5],[55,-5],[55,15],[15,15]],height:4,blend:0}],
 yard_rooms:[{id:'pool',name:'Pool deck',polygon:rect(20,0)},{id:'grill',name:'Grill',polygon:rect(40,0)}]},materials:{}},
 kit:{materials:{}},tier:'low',bake:false});
await test('yard House target, top framing, selected outline, back and directional swipes',()=>{
 const l = v.levels; assert.equal(l.snapshot().level,'house'); l.draw();
 const button = host.querySelector('[data-level-room="pool"]'); assert.ok(button); assert.equal(button.hidden,false); click(button);
 assert.deepEqual(l.snapshot(),{level:'room',building:null,floor:null,room:'pool'});
 l.go({room:'pool'},{immediate:true});
 assert.equal(v.controls.enableRotate,false); assert.equal(v.state.view,'ext');
 assert.ok(Math.abs(v.controls.target.x - 25 * .3048) < 1e-6);
 assert.ok(Math.abs(v.controls.target.y - 4 * .3048) < 1e-6);
 assert.ok(Math.abs(v.controls.target.z + 5 * .3048) < 1e-6);
 assert.ok(v.camera.position.clone().sub(v.controls.target).normalize().y > .9999);
 assert.ok(v.scene.getObjectByName('yard-room-outline:pool').visible);
 assert.equal(v.scene.getObjectByName('yard-room-outline:grill').visible,false);
 assert.equal(textOf(document.getElementById('twin-path')),'House \u203a Pool deck');
 assert.ok(l.swipe(80,0)); assert.equal(l.snapshot().room,'grill');
 assert.equal(l.swipe(80,0),false); assert.equal(l.snapshot().room,'grill');
 assert.ok(l.up()); assert.equal(l.snapshot().level,'house');
 assert.equal(v.scene.getObjectByName('yard-room-outline:grill').visible,false);
 l.go({building:'b',room:'inside'},{immediate:true});
 assert.ok(l.swipe(80,0)); assert.equal(l.snapshot().room,'pool');
});
await test('yard attention markers are limited to House and their own room',()=>{
 const row = {yard:true,building:null,room:'pool',look:'attention'};
 for (const level of ['floor','building']) assert.equal(deviceAtLevel({level,building:'b'},row),false);
 assert.ok(deviceAtLevel({level:'house'},row));
 assert.ok(deviceAtLevel({level:'room',building:null,room:'pool'},row));
 assert.equal(deviceAtLevel({level:'room',building:null,room:'grill'},row),false);
});
await test('editor yard selection outline uses lot feet once and clears on deselection',async()=>{
 const THREE = await import('three');
 const shell = new Element(); shell.className = 'editor-shell';
 const editorHost = new Element(); shell.append(editorHost); document.body.append(shell);
 const editor = await mountTwin(editorHost,{plan:structuredClone(v.plan),kit:{materials:{}},tier:'low',bake:false});
 const selectionLines = () => { const found = []; editor.scene.traverse(o=>{
   if (o.isLine && o.userData.isHover === false) found.push(o);
 }); return found; };
 try {
  editor.setSelection({selected:{kind:'yard_rooms',id:'pool',building:null},hover:null,room:null});
  editor.scene.updateMatrixWorld(true);
  const lines = selectionLines(); assert.equal(lines.length,1);
  const first = new THREE.Vector3().fromBufferAttribute(lines[0].geometry.attributes.position,0).applyMatrix4(lines[0].matrixWorld);
  assert.ok(Math.abs(first.x - 20 * .3048) < 1e-6,'lot x receives only the scene feet scale');
  assert.ok(Math.abs(first.y - (4 + .06) * .3048) < 1e-6,'outline rests above local ground');
  assert.ok(Math.abs(first.z) < 1e-6);
  editor.setSelection({selected:null,hover:null,room:null});
  assert.equal(selectionLines().length,0,'deselection removes the editor outline');
 } finally { editor.dispose(); shell.remove(); }
});
v.dispose(); finish();
"""

LIVE = r"""
const {roomFacts} = await import(file('static/twin/live/room_cards.js'));
const {groundAt} = await import(file('static/twin/twin_ground.js'));
const checks = [], check = (name, fn) => checks.push([name,fn]);
const yard = {building:null,level:null,room:'patio',yard:true,name:'Patio',area_id:'patio',lights:[],
 polygon_world:[[-10,-10],[10,-10],[10,10],[-10,10]]};
const t = await rig({rooms:[yard],devices:[
 {device_id:'explicit',name:'Moved lamp',kind:'light',entity_id:'light.moved',state:'on',area_id:'garage',at:[0,0,2],attributes:{brightness:128}},
 {device_id:'area',name:'Patio plug',kind:'switch',entity_id:'switch.patio',state:'on',area_id:'patio'},
]});
t.live.stop();
Object.assign(t.layout.devices[0],{building:null,room:'patio',yard:true});
t.layout.markers = [{...t.layout.devices[0],building:null,level:null,room:'patio',yard:true,at:[0,0,2],placed:true}];
t.view.plan.site = {yard_rooms:[{id:'patio',name:'Patio',polygon:yard.polygon_world}],
 terraces:[{polygon:yard.polygon_world,height:6,blend:0}]};
let navigation = {level:'house',building:null,floor:null,room:null};
t.view.levels = {snapshot:()=>({...navigation}),tap:()=>false};
t.live = await liveModule.mountLive(t.view,{api:t.api}); assert.ok(t.live,'yard live layer mounts');
check('mounted yard marker uses terrain plus offset and hides in floor views',()=>{
 const sprite = t.sprite('explicit'); assert.ok(sprite);
 assert.ok(Math.abs(sprite.position.y - (groundAt(t.view.plan,0,0) + 2) * FT) < 1e-6);
 t.live.draw(); assert.equal(sprite.visible,true);
 navigation = {level:'floor',building:'b',floor:'L1',room:null}; t.live.draw(); assert.equal(sprite.visible,false);
 navigation = {level:'room',building:null,floor:null,room:'patio'}; t.live.draw(); assert.equal(sprite.visible,true);
 navigation = {level:'room',building:null,floor:null,room:'other'}; t.live.draw(); assert.equal(sprite.visible,false);
});
check('yard card and room panel include explicit devices outside the HA area',async()=>{
 const facts = roomFacts(yard,t.layout.devices,t.states);
 assert.ok(facts.some(f=>f.text==='1 on'),'outside-area placed light contributes to the shared facts');
 const card = t.host.querySelector('[data-room-card]'); assert.ok(card); assert.match(card.textContent,/Patio/); assert.match(card.textContent,/1 on/);
 assert.deepEqual(t.live.devices('patio',yard).map(d=>d.device_id).sort(),['area','explicit']);
 t.live.openRoom(null,'patio');
 const panel = document.getElementById('twin-room-panel'); assert.equal(panel.hidden,false);
 const nodes = panel.querySelectorAll('[data-device-id]'); assert.equal(nodes.length,2);
 const explicit = nodes.find(node=>node.dataset.deviceId==='explicit'); assert.ok(explicit);
 const toggle = explicit.querySelector('button[role="switch"]'); assert.ok(toggle); assert.equal(toggle.getAttribute('aria-checked'),'true');
 await press(toggle); assert.equal(t.calls.at(-1).data.entity_id,'light.moved'); assert.equal(t.calls.at(-1).service,'toggle');
 assert.equal(t.states['light.moved'].state,'off');
});
let failed = 0;
try { for (const [name,fn] of checks) { try { await fn(); console.log('  ok  ',name); } catch(error) {failed++;console.error('  FAIL',name,error.stack);} } }
finally { t.cleanup(); }
assert.deepEqual(domErrors,[]); assert.deepEqual(escaped,[]);
console.log(`${checks.length-failed}/${checks.length} yard live checks passed`); process.exit(failed?1:0);
"""


if __name__ == '__main__':
    code, output = run_node(NAVIGATION, {'root': ROOT.as_posix()})
    print(output)
    live_code = run_live(LIVE, prefix='chauffeur_yard_rooms_')
    sys.exit(code or live_code or 0)
