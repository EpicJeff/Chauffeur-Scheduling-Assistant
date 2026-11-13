"""Shared material-slot DOM and the real porch card: one change, one op."""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {materialSlot}=await import(file('static/twin/editor/material_slot.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {porchFoundation}=await import(file('static/twin/twin_porch_foundation.js'));
const entries=[{id:'painted_trim',name:'Painted trim',color:'#f4f3ef'},{id:'wood_planks',name:'Wood planks',color:'#998877'}];
let fetches=0;globalThis.fetch=async url=>{assert.ok(url.endsWith('/api/house/editor/library'));fetches++;return {ok:true,text:async()=>JSON.stringify({materials:entries,items:[]})};};
const calls=[],errors=[];let locked=false;
const node=materialSlot({label:'Posts',value:null,defaultLabel:'Trim',defaultColor:'#ffffff',quickPicks:[entries[1]],
 readOnly:()=>locked,onChange:async v=>calls.push(v),report:e=>errors.push(e.message)});document.body.append(node);
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
assert.ok(textOf(node).includes('Default: Trim'));
await click(byText(node,'Change'));assert.equal(fetches,1);assert.equal(calls.length,0,'opening is never a history step');
assert.equal(node.querySelectorAll('[data-material]')[0].dataset.material,'wood_planks','quick picks first');
assert.equal(node.querySelectorAll('[data-material]').length,2,'quick picks deduplicated');
await click(node.querySelector('[data-material="wood_planks"]'));assert.deepEqual(calls,[{id:'wood_planks',color:'#998877'}]);
assert.ok(textOf(node).includes('Wood planks'));
await click(byText(node,'Change'));await click(node.querySelector('[data-material="wood_planks"]'));assert.equal(calls.length,1,'reselect is no op');
// Reselect leaves the chooser open and still permits clearing/tinting.
const tint=node.querySelector('input[type="color"]');tint.value='#abcdef';await fire(tint,'change');
assert.deepEqual(calls.at(-1),{id:'wood_planks',color:'#abcdef'});assert.equal(calls.length,2);
await click(byText(node,'Change'));await click(byText(node,'Use default'));assert.equal(calls.at(-1),null);assert.equal(calls.length,3);
assert.ok(textOf(node).includes('Default: Trim'));
locked=true;await click(byText(node,'Change'));assert.equal(node.querySelector('[role="group"]'),null);assert.equal(calls.length,3);
const readonly=materialSlot({label:'Solid',value:{id:'wood_planks'},defaultLabel:'Stone',readOnly:true,onChange:()=>{throw Error('read-only wrote');}});
assert.equal(readonly.querySelectorAll('button,input').length,0);assert.ok(textOf(readonly).includes('Wood planks'));
const idOnly=materialSlot({label:'Solid',value:{id:'base'},defaultLabel:'Stone',kit:input.kit,readOnly:true});
assert.equal(idOnly.querySelector('i').style.backgroundColor,input.kit.materials.base.color);
assert.ok(textOf(idOnly).includes('Stacked stone wall'));
// A failed save is visible, keeps the chosen/default value, and may be retried.
const failed=materialSlot({label:'Skirt',defaultLabel:'Trim',onChange:async()=>{throw Error('save failed');},report:e=>errors.push(e.message)});document.body.append(failed);
await click(byText(failed,'Change'));await click(failed.querySelector('[data-material="wood_planks"]'));assert.ok(textOf(failed).includes('Default: Trim'));assert.deepEqual(errors,['save failed']);
console.log('Passed: shared slot catalogue, swatch/name, choose, quick picks, tint, default, duplicate suppression, read-only and error');

const square=[[0,0],[12,0],[12,8],[0,8]];
const room={id:'porch',kind:'porch',level:'L1',name:'Porch',polygon:square,foundation:{type:'posts'}};
const building={id:'b',position:[0,0],base:2,levels:[{id:'L1',elevation:0,ceiling:10}],rooms:[room],walls:[],openings:[],anchors:[],items:[],stairs:[]};
const plan={buildings:[building],site:{terraces:[]}};let writable=true;const ops=[];
window.showGlobalAlert=message=>errors.push(message);
const cards=createCards({getPlan:()=>plan,getKit:()=>input.kit,getLabel:()=> 'Porch',canEdit:()=>writable,edit(){},
 op:async operation=>{ops.push(structuredClone(operation));room.foundation=operation.foundation;},ask(){},select(){}});
cards.draw({pieceId:'porch',buildingId:'b'});const host=document.getElementById('piece-card');
const field=label=>host.querySelectorAll('input,select').find(n=>n.getAttribute('aria-label')===label);
const slot=label=>host.querySelector(`[data-material-slot="${label}"]`);
assert.ok(shown(field('Post width (in)'))&&shown(field('Post shape'))&&shown(field('Post spacing (ft)')));
assert.ok(!shown(field('Skirt'))&&!shown(slot('Solid base'))&&shown(slot('Posts and beam')));
for(const [label,value,key]of [['Post width (in)','10','post_in'],['Post shape','round','post_shape'],['Post spacing (ft)','5','spacing_ft']]){
 const before=ops.length;field(label).value=value;await fire(field(label),'change');await cards.queue(async()=>{});
 assert.equal(ops.length,before+1);assert.equal(room.foundation[key],key==='post_shape'?value:Number(value));
}
field('Foundation').value='enclosed';await fire(field('Foundation'),'change');await cards.queue(async()=>{});
assert.ok(shown(field('Skirt'))&&shown(slot('Skirt'))&&shown(slot('Posts and beam'))&&!shown(slot('Solid base')));
field('Skirt').value='panel';await fire(field('Skirt'),'change');await cards.queue(async()=>{});
assert.ok(textOf(slot('Skirt')).includes('Default: Siding'));
let before=ops.length;await click(byText(slot('Skirt'),'Change'));await click(slot('Skirt').querySelector('[data-material="wood_planks"]'));await cards.queue(async()=>{});
assert.equal(ops.length,before+1);assert.deepEqual(room.foundation.materials.skirt,{id:'wood_planks',color:'#998877'});
assert.equal(ops.at(-1).op,'set_porch_foundation');assert.equal(room.foundation.post_in,10,'material change preserves other fields');
await click(byText(slot('Skirt'),'Change'));await click(byText(slot('Skirt'),'Use default'));await cards.queue(async()=>{});
assert.equal(room.foundation.materials.skirt,null);assert.equal(ops.length,before+2);
field('Foundation').value='solid';await fire(field('Foundation'),'change');await cards.queue(async()=>{});
assert.ok(!shown(field('Post width (in)'))&&!shown(field('Post shape'))&&!shown(field('Post spacing (ft)'))&&!shown(field('Skirt')));
assert.ok(shown(slot('Solid base'))&&!shown(slot('Skirt'))&&!shown(slot('Posts and beam')));
field('Floor overhang (in)').value='2.5';await fire(field('Floor overhang (in)'),'change');await cards.queue(async()=>{});assert.equal(room.foundation.lip_in,2.5);
before=ops.length;
for(const [label,value]of [['Floor overhang (in)','5'],['Post width (in)','3'],['Post spacing (ft)','13']]){
 field(label).value=value;await fire(field(label),'change');await cards.queue(async()=>{});assert.equal(ops.length,before);
}
// Undo redraw and the grade note reflect current terrain/height, including auto base.
room.foundation=porchFoundation();cards.draw();assert.equal(field('Foundation').value,'posts');assert.ok(shown(field('Post width (in)')));
assert.ok(!textOf(host).includes('Slab on grade'));
building.base=.5;cards.draw();assert.ok(textOf(host).includes('Slab on grade'));
building.foundation={mode:'auto',offset_ft:2};cards.draw();assert.ok(!textOf(host).includes('Slab on grade'));
writable=false;cards.draw();assert.ok(field('Foundation').disabled);assert.equal(slot('Posts and beam').querySelectorAll('button,input').length,0);
field('Foundation').value='solid';await fire(field('Foundation'),'change');await cards.queue(async()=>{});assert.equal(ops.length,before);
console.log('Passed: real card fields by type, post properties, default skirt role, slots/one op, ranges, undo, grade note and read-only');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit})
    print(output)
    sys.exit(code or 0)
