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
const entries=[{id:'painted_trim',name:'Painted trim',color:'#f4f3ef'},{id:'wood_planks',name:'Wood planks',color:'#998877'},{id:'lattice',name:'Lattice',color:'#f4f3ef'}];
let fetches=0;globalThis.fetch=async url=>{assert.ok(url.endsWith('/api/house/editor/library'));fetches++;return {ok:true,text:async()=>JSON.stringify({materials:entries,items:[]})};};
const calls=[],errors=[];let locked=false;
const node=materialSlot({label:'Posts',value:null,defaultLabel:'Trim',defaultColor:'#ffffff',quickPicks:[entries[1]],
 readOnly:()=>locked,onChange:async v=>calls.push(v),report:e=>errors.push(e.message)});document.body.append(node);
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
assert.ok(textOf(node).includes('Default: Trim'));
await click(byText(node,'Change'));assert.equal(fetches,1);assert.equal(calls.length,0,'opening is never a history step');
assert.equal(node.querySelectorAll('[data-material]')[0].dataset.material,'wood_planks','quick picks first');
assert.equal(node.querySelectorAll('[data-material]').length,3,'quick picks deduplicated');
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
// Yard features (user, 2026-11-13): each part's slot sits in the shared yard shape card.
{
  const {drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
  const square=[[0,0],[6,0],[6,4],[0,4]];
  for(const [kind,piece,parts] of [
    ['fence',{id:'f',polyline:[[0,0],[4,0]],height:6},['Boards','Posts','Rails']],
    ['fire_pit',{id:'p',at:[0,0],radius:2,fuel:'wood'},['Body']],
    ['fire_pit',{id:'g',at:[0,0],radius:2,fuel:'gas'},['Body','Top']],
    ['hardscape',{id:'h',polygon:square},['Surface']],
    ['hardscape',{id:'w',kind:'path',points:[[0,0],[9,0]],width:3,edging:'curb'},['Surface','Curb']],
    ['beds',{id:'b',polygon:square},['Fill']],
    ['pool',{id:'pool',polygon:square},['Coping','Interior']],
    ['edges',{id:'edge',polygon:square},['Strip']]]){
    const host=document.createElement('div'),sent=[];document.body.append(host);
    drawSiteShapeShelf(host,{kind,index:0,piece},{canEdit:()=>true,queue:work=>Promise.resolve().then(work),op:async o=>sent.push(o),
      report:e=>{throw e;},getKit:()=>input.kit,getRecord:()=>({kind,index:0,piece})});
    assert.deepEqual(host.querySelectorAll('[data-material-slot]').map(n=>n.dataset.materialSlot),parts,`${kind} slots`);
    if(!parts.length)continue;
    for(const label of parts){
      const slot=host.querySelector(`[data-material-slot="${label}"]`),before=sent.length;
      await click(byText(slot,'Change'));await click(slot.querySelector('[data-material="wood_planks"]'));
      const part={Boards:'boards',Posts:'posts',Rails:'rails',Body:'body',Top:'top',Surface:'surface',Curb:'edging',Fill:'fill',Coping:'coping',Interior:'interior',Strip:'strip'}[label];
      assert.equal(sent.length,before+1);
      assert.deepEqual(sent.at(-1),{op:'update_site_shape',list:kind,index:0,materials:{[part]:{id:'wood_planks',color:'#998877'}}},`${kind} ${label}: one op`);
      await click(byText(slot,'Change'));await click(byText(slot,'Use default'));
      assert.equal(sent.length,before+2);assert.deepEqual(sent.at(-1).materials,{[part]:null});
    }
  }
  const host=document.createElement('div');document.body.append(host);
  drawSiteShapeShelf(host,{kind:'beds',index:0,piece:{id:'b',polygon:square,materials:{fill:{id:'wood_planks'}}}},{canEdit:()=>false,queue:w=>w(),op:()=>{throw Error('read-only wrote');},report:e=>{throw e;}});
  const slot=host.querySelector('[data-material-slot]');
  assert.ok(textOf(slot).includes('Wood planks'));assert.equal(slot.querySelectorAll('button,input').length,0,'read-only');
  console.log('Passed: yard shape card slots per feature, one op per choice, read-only');
}

// Real yard room card -> source feature -> shared material slot. Legacy rooms
// match their copied outline; new references survive an independent room move.
{
  const square=[[0,0],[6,0],[6,4],[0,4]], sent=[], selections=[];
  const plan={buildings:[],site:{pool:{id:'pool',polygon:square},hardscape:[{id:'patio',polygon:square.map(p=>[p[0]+20,p[1]])}],
    fire_pit:[{id:'pit',at:[40,0],radius:2,fuel:'gas'}],yard_rooms:[]}};
  let writable=true;
  const cards=createCards({getPlan:()=>plan,getKit:()=>input.kit,getLabel:()=> 'Yard room',canEdit:()=>writable,
    edit(){},op:async o=>sent.push(o),ask(){},select:s=>selections.push(s)});
  const host=document.getElementById('piece-card');
  for(const [kind,id,label,part,polygon] of [
    ['pool','pool','Pool','coping',square],
    ['hardscape','patio','Path / hardscape','surface',plan.site.hardscape[0].polygon],
    ['fire_pit','pit','Fire pit','body',Array.from({length:32},(_,i)=>[40+3.5*Math.cos(i*Math.PI/16),3.5*Math.sin(i*Math.PI/16)])]]){
    const room={id:'yard-'+id,name:'Yard room',polygon};plan.site.yard_rooms=[room];
    for(const referenced of [false,true]){
      if(referenced){room.feature={list:kind,id};room.polygon=polygon.map(p=>[p[0]+100,p[1]+100]);}
      cards.draw({pieceId:room.id,buildingId:null});
      const link=byText(host,`Edit ${label} materials`);assert.ok(link,`${id}: ${referenced?'referenced':'legacy'} room has a material link`);
      const before=sent.length;await click(link);assert.equal(sent.length,before,'navigation is not a history step');
      assert.deepEqual(selections.at(-1),{pieceId:id,buildingId:null});
      const slot=host.querySelector('[data-material-slot]');assert.ok(slot);
      await click(byText(slot,'Change'));await click(slot.querySelector('[data-material="wood_planks"]'));await cards.queue(async()=>{});
      assert.equal(sent.length,before+1);assert.deepEqual(sent.at(-1),{op:'update_site_shape',list:kind,index:0,materials:{[part]:{id:'wood_planks',color:'#998877'}}});
    }
    writable=false;cards.draw({pieceId:room.id,buildingId:null});
    assert.ok(byText(host,`Edit ${label} materials`).disabled,'read-only room card');writable=true;
  }
  plan.site.yard_rooms=[{id:'gone',name:'Deleted source',polygon:square,feature:{list:'pool',id:'missing'}}];
  cards.draw({pieceId:'gone',buildingId:null});assert.equal(byText(host,'Edit Pool materials'),undefined,'deleted source never retargets a different feature');
  console.log('Passed: pool/patio/fire-pit yard room card links, legacy and moved references, no-op navigation, one material op, read-only and deleted source');
}

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
assert.equal(field('Skirt'),undefined,'no Lattice/Panel selector');
assert.ok(!shown(slot('Skirt'))&&!shown(slot('Solid base'))&&shown(slot('Posts and beam')));
for(const [label,value,key]of [['Post width (in)','10','post_in'],['Post shape','round','post_shape'],['Post spacing (ft)','5','spacing_ft']]){
 const before=ops.length;field(label).value=value;await fire(field(label),'change');await cards.queue(async()=>{});
 assert.equal(ops.length,before+1);assert.equal(room.foundation[key],key==='post_shape'?value:Number(value));
}
field('Foundation').value='enclosed';await fire(field('Foundation'),'change');await cards.queue(async()=>{});
assert.ok(shown(slot('Skirt'))&&shown(slot('Posts and beam'))&&!shown(slot('Solid base')));
assert.equal(field('Skirt'),undefined);
assert.ok(textOf(slot('Skirt')).includes('Default: Lattice'));
let before=ops.length;await click(byText(slot('Skirt'),'Change'));await click(slot('Skirt').querySelector('[data-material="wood_planks"]'));await cards.queue(async()=>{});
assert.equal(ops.length,before+1);assert.deepEqual(room.foundation.materials.skirt,{id:'wood_planks',color:'#998877'});
assert.equal(ops.at(-1).op,'set_porch_foundation');assert.equal(room.foundation.post_in,10,'material change preserves other fields');
await click(byText(slot('Skirt'),'Change'));await click(byText(slot('Skirt'),'Use default'));await cards.queue(async()=>{});
assert.equal(room.foundation.materials.skirt,null);assert.equal(ops.length,before+2);
assert.ok(textOf(slot('Skirt')).includes('Default: Lattice'));
await click(byText(slot('Skirt'),'Change'));await click(slot('Skirt').querySelector('[data-material="lattice"]'));await cards.queue(async()=>{});
assert.deepEqual(room.foundation.materials.skirt,{id:'lattice',color:'#f4f3ef'});assert.equal(ops.length,before+3);
assert.ok(!Object.hasOwn(ops.at(-1).foundation,'skirt'));
field('Foundation').value='solid';await fire(field('Foundation'),'change');await cards.queue(async()=>{});
assert.ok(!shown(field('Post width (in)'))&&!shown(field('Post shape'))&&!shown(field('Post spacing (ft)')));
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
