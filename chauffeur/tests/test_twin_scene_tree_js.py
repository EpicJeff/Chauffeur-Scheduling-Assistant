"""Scene hierarchy, shared layer rows, keyboard and virtual selection under Node."""
from pathlib import Path
import json
import os
import sys
import tempfile
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DRIVER = PRELUDE + r"""
const {createSceneTree, sceneRows}=await import(file('static/twin/editor/scene_tree.js'));
const {createLayers}=await import(file('static/twin/editor/dock.js'));
const {createVisibility}=await import(file('static/twin/editor/visibility.js'));
let plan={buildings:[{id:'b',name:'House',levels:[{id:'L',name:'Ground',elevation:0}],
 rooms:[{id:'r',name:'Kitchen',level:'L',walls:['w']}],walls:[{id:'w',level:'L',joints:['a','b']}],
 openings:[{id:'o',wall:'w',kind:'door'}],items:[{id:'i',host:{floor:'r'}}],anchors:[{id:'a',host:{wall:'w'}},{id:'d',device:'dev',host:{floor:'r'}}],
 roofs:[{id:'roof',level:'L'}],stairs:[{id:'stair',level:'L'}]}],
 light_fixtures:{'light.kitchen':[{id:'light',ref:'floor',building:'b',level:'L',host:{floor:'r'}}]},
 effect_fixtures:[{id:'effect',building:'b',level:'L',host:{floor:'r'}}],
 site:{terraces:[{id:'pad'}],hardscape:[{id:'path'}],beds:[{id:'bed'}],edges:[{id:'edge'}],pool:{id:'pool',features:[{id:'spa',kind:'spa'},{id:'steps',kind:'steps'},{id:'ledge',kind:'ledge'}]},fire_pit:{id:'pit'},fence:[{id:'fence'}],yard_rooms:[{id:'yardroom'}],planting:[{id:'plant'}],furniture:[{id:'chair'}]}};
const rows=sceneRows(plan),by=id=>rows.find(r=>r.id===id);
assert.equal(by('L').parent.id,'b');assert.equal(by('r').parent.id,'L');
for(const id of ['w','o','i','a','d','light','effect'])assert.equal(by(id).parent.id,'r',id);
assert.equal(rows.filter(r=>r.parent?.id==='r').length,7);
assert.equal(by('spa').parent.id,'pool');assert.equal(by('steps').parent.id,'pool');assert.equal(by('ledge').parent.id,'pool');
assert.deepEqual(rows.filter(r=>r.parent?.id==='yard').map(r=>r.id),['pad','path','bed','edge','pool','pit','fence','yardroom','plant','chair']);
console.log('  ok building/floor/room descendants and ordered yard/pool hierarchy');
const scalarAt={buildings:[{id:'b2',levels:[{id:'L2',elevation:0}],rooms:[{id:'r2',level:'L2',polygon:[[0,0],[10,0],[10,10],[0,10]]}],walls:[{id:'w2',level:'L2'}],items:[{id:'shelf',level:'L2',host:{wall:'w2'},at:11}],anchors:[{id:'switch',level:'L2',at:3}]}],site:{}};
const scalarRows=sceneRows(scalarAt);assert.equal(scalarRows.find(r=>r.id==='shelf').parent.id,'L2');assert.equal(scalarRows.find(r=>r.id==='switch').parent.id,'L2');
console.log('  ok a wall-hosted piece whose at is a distance along the wall is not read as a point');
const porchPlan={buildings:[{id:'b3',levels:[{id:'L3',elevation:0}],rooms:[{id:'porch:p',kind:'porch',level:'L3',polygon:[[0,0],[8,0],[8,6],[0,6]]}],porches:[{id:'porch:p',level:'L3',polygon:[[0,0],[8,0],[8,6],[0,6]]}],walls:[],openings:[]}],site:{}};
assert.equal(sceneRows(porchPlan).filter(r=>r.id==='porch:p').length,1);
console.log('  ok a porch that is also a room is listed once');
const pane=document.createElement('div');pane.id='dock-pane-scene';document.body.append(pane);
const floorHost=document.createElement('aside');floorHost.id='editor-floors';pane.append(floorHost);
const host=document.createElement('div');host.clientHeight=160;floorHost.append(host);
const visibility=createVisibility({storage:null});let selected=null;
const tree=createSceneTree({host,getPlan:()=>plan,getSelection:()=>selected,select:r=>{selected=r;tree.reveal(r.id);},visibility,
 floors:{current:()=> 'b:L',hidden:()=>false}});
const row=id=>host.querySelector(`[data-scene-id="${id}"]`);
const disclosure=id=>row(id).querySelector('[data-row-disclosure]');
const beforeExpansion=visibility.snapshot();
assert.equal(disclosure('b').getAttribute('aria-label'),'Collapse House');
assert.equal(disclosure('yard').getAttribute('aria-expanded'),'true');
assert.equal(disclosure('L').getAttribute('aria-expanded'),'true','current floor opens to rooms');
assert.equal(disclosure('r').getAttribute('aria-expanded'),'false','rooms start collapsed');
assert.equal(row('w'),null);
click(disclosure('r'));assert.equal(disclosure('r').getAttribute('aria-label'),'Collapse Kitchen');
assert.equal(row('r').getAttribute('aria-expanded'),'true');assert.ok(row('w'));
click(disclosure('r'));assert.equal(disclosure('r').getAttribute('aria-label'),'Expand Kitchen');
assert.equal(row('w'),null);row('r').focus();
fire(row('r'),'keydown',{key:'ArrowRight'});assert.equal(document.activeElement.dataset.sceneId,'r');assert.ok(row('w'));
fire(row('r'),'keydown',{key:'ArrowRight'});assert.equal(document.activeElement.dataset.sceneId,'w');
fire(row('w'),'keydown',{key:'ArrowLeft'});assert.equal(document.activeElement.dataset.sceneId,'r');
fire(row('r'),'keydown',{key:'ArrowLeft'});assert.equal(row('w'),null);assert.equal(document.activeElement.dataset.sceneId,'r');
fire(row('r'),'keydown',{key:'ArrowLeft'});assert.equal(document.activeElement.dataset.sceneId,'L');
assert.deepEqual(visibility.snapshot(),beforeExpansion,'expansion never enters persistent visibility state');
visibility.hide('r');visibility.lock('L');tree.reveal('w');
assert.equal(disclosure('r').getAttribute('aria-expanded'),'true','view selection opens ancestors');
assert.equal(row('w').style.opacity,'0.5');assert.equal(row('w').querySelector('[data-row-lock]').getAttribute('aria-pressed'),'true');
visibility.showAll();visibility.unlock('L');
click(disclosure('b'));assert.equal(row('L'),null);
selected={id:'w',building:'b'};tree.reveal('w');assert.ok(row('w'));assert.ok(row('L'));
click(disclosure('r'));tree.refresh();assert.equal(row('w'),null,'refresh preserves a collapsed selected branch');tree.reveal('w');
console.log('  ok default expansion, disclosure names/states, ARIA keys, inherited state and selection expands ancestors');
click(row('w').querySelector('[data-scene-select]'));assert.equal(selected.id,'w');assert.equal(selected.building,'b');
assert.equal(row('w').getAttribute('aria-selected'),'true');
click(row('w').querySelector('[data-row-eye]'));assert.equal(visibility.isHidden('w'),true);
assert.equal(row('w').style.opacity,'0.5');assert.equal(row('w').querySelector('[data-row-eye]').getAttribute('aria-label'),'Show Wall w');
assert.equal(row('w').querySelector('[data-row-eye]').getAttribute('aria-pressed'),'true');
visibility.hide('r');assert.equal(row('o').style.opacity,'0.5');visibility.showAll();
click(row('w').querySelector('[data-row-lock]'));assert.equal(visibility.isLocked('w'),true);
assert.equal(row('w').querySelector('[data-row-lock]').getAttribute('aria-label'),'Unlock Wall w');
click(row('w').querySelector('[data-scene-select]'));assert.equal(selected.id,'w','locked row can select');
selected={id:'chair'};tree.reveal('chair');assert.equal(row('chair').getAttribute('aria-selected'),'true');
row('w').focus();fire(row('w'),'keydown',{key:'ArrowDown'});assert.equal(document.activeElement.dataset.sceneId,'o');
fire(document.activeElement,'keydown',{key:'Enter'});assert.equal(selected.id,'o');
console.log('  ok row selection/reveal, inherited hiding, names/pressed and keyboard');
const layers=document.createElement('div');document.body.append(layers);const layerApi=createLayers({host:layers,visibility});
const kinds=['Walls','Rooms (floors and ceilings)','Openings','Roofs','Stairs','Items and furniture','Plants','Yard surfaces','Lights','Effects','Devices'];
assert.deepEqual(layers.querySelectorAll('[data-row-label]').map(n=>n.textContent),kinds);
for(const [name,domains] of [['Items and furniture',['item','anchor','furniture']],['Yard surfaces',['pad','hardscape','bed','edge','pool','fire_pit','fence','yard_room']],['Lights',['fixture']]]){
 const r=layers.querySelectorAll('.editor-scene-row').find(n=>n.querySelector('[data-row-label]').textContent===name);
 click(r.querySelector('[data-row-eye]'));click(r.querySelector('[data-row-lock]'));
 for(const kind of domains){assert.equal(visibility.isHidden('any',kind),true);assert.equal(visibility.isLocked('any',kind),true);}
}
console.log('  ok canonical layer kind groups use the same store');
plan={buildings:[{id:'one',levels:[{id:'L',elevation:0}]},{id:'two',levels:[{id:'L',elevation:0}]}],site:{}};
selected={id:'L',building:'two'};tree.refresh();tree.reveal('L');
for(const floor of host.querySelectorAll('[data-floor]'))assert.equal(floor.closest('[role="treeitem"]').getAttribute('aria-expanded'),null,'leaf floors have no disclosure');
assert.equal(host.querySelectorAll('[data-scene-id="L"]').filter(n=>n.getAttribute('aria-selected')==='true').length,1);
assert.equal(host.querySelector('[data-floor="two:L"]').closest('[data-scene-id]').getAttribute('aria-selected'),'true');
console.log('  ok identical floor ids in different buildings reveal one selected row');
plan={buildings:[{id:'big',levels:[{id:'floor',elevation:0},{id:'upper',elevation:10}],rooms:[{id:'upstairs',level:'upper'}],walls:Array.from({length:650},(_,i)=>({id:'wall'+i,level:'floor'}))},
 {id:'annex',name:'Pool house',levels:[{id:'L1',name:'Main floor',elevation:0}],rooms:[{id:'annex-room',level:'L1'}]}],site:{}};
selected=null;tree.refresh();
assert.equal(disclosure('floor').getAttribute('aria-expanded'),'false','other floors default collapsed');
assert.equal(disclosure('upper').getAttribute('aria-expanded'),'false');assert.equal(row('upstairs'),null);
assert.equal(disclosure('annex').getAttribute('aria-expanded'),'true');
tree.reveal('wall0');assert.ok(host.querySelectorAll('[data-scene-id]').length<100);selected={id:'wall640',building:'big'};tree.reveal('wall640');
assert.equal(row('wall640').getAttribute('aria-selected'),'true');assert.ok(host.scrollTop>0);
const mountedFloors=()=>pane.querySelectorAll('#editor-floors [data-floor]');
assert.deepEqual(mountedFloors().map(n=>n.dataset.floor),['big:floor','big:upper','annex:L1']);
assert.equal(mountedFloors().at(-1).textContent,'Pool house · Main floor');
host.scrollTop=0;fire(host,'scroll');assert.equal(selected.id,'wall640');tree.reveal('wall640');assert.equal(row('wall640').getAttribute('aria-selected'),'true');
assert.equal(mountedFloors().length,3,'all floor Choose controls survive virtual scroll');
plan=input.household;selected=null;tree.refresh();
const householdRows=sceneRows(plan);assert.ok(householdRows.length>300,'real fixture exercises a large hierarchy');
const expectedFloors=plan.buildings.flatMap(b=>b.levels.map(l=>`${b.id}:${l.id}`)).sort();
assert.deepEqual(mountedFloors().map(n=>n.dataset.floor).sort(),expectedFloors);
for(const b of plan.buildings){assert.ok(row(b.id));for(const l of b.levels)assert.ok(host.querySelector(`[data-floor="${b.id}:${l.id}"]`));}
for(const b of plan.buildings)for(const l of b.levels){const wall=b.walls.find(w=>w.level===l.id);if(wall){selected={id:wall.id,building:b.id};tree.reveal(wall.id);assert.ok(row(wall.id));assert.equal(mountedFloors().length,expectedFloors.length);}}
console.log('  ok real normalized household fixture opens and keeps every building floor mounted');
tree.dispose();layerApi.dispose();console.log('  ok >300 rows virtualise and preserve selection across scroll/reveal');
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));
const lampPlan={buildings:[{id:'lamps',position:[0,0],levels:[{id:'L',elevation:0,ceiling:8,outline:[[0,0],[10,0],[10,10],[0,10]]}],
 walls:[],rooms:[{id:'room',level:'L',polygon:[[0,0],[10,0],[10,10],[0,10]]}],openings:[],items:[],
 anchors:[{id:'lamp',kind:'anchor',object_kind:'lamp',host:{floor:'room',u:.5,v:.5}}],roof:{sections:[]}}],site:{},materials:{}};
const generated=buildTwin(lampPlan,{materials:{}},'low',{showAnchors:true});await generated.ready;
let lampRanges=0;generated.root.traverse(o=>{for(const r of o.userData.snapRanges||[])if(r.pieceId==='lamp'){
 assert.equal(r.visibilityKind,'fixture');lampRanges++;
}});assert.ok(lampRanges,'real generated lamps belong to Lights');
const masking=createPieceVisibility();masking.set([],['fixture']);masking.apply(generated.root);
generated.root.traverse(o=>{for(const r of o.userData.snapRanges||[])if(r.pieceId==='lamp'){
 const a=o.geometry.attributes.position.array;for(let i=0;i<r.count*3;i++)assert.equal(a[r.start*3+i],a[r.start*3+i%3]);
}});masking.restore();
console.log('  ok Lights masks actual generated lamp geometry');
"""

if __name__ == '__main__':
    # Same schema-2 push/assemble/flatten boundary used by H.seed / M._prepare.
    # Select scratch storage before importing any service; never use app data.
    with tempfile.TemporaryDirectory(prefix='chauffeur_scene_tree_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_store
        twin_store.push_round(json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')), 'build')
        code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'household': twin_store.current()})
    print(out)
    sys.exit(code)
