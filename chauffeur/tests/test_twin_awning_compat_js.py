"""Migrated extension ids use the ordinary roof card and scene controls."""
from copy import deepcopy
import os
import sys
from twin_editor_dom import PRELUDE, run_node
from test_twin_awning_readers import ROOT, building, old_extension
from services.twin_model_bridge import assemble, flatten

DRIVER = PRELUDE + r"""
const {sceneRows}=await import(file('static/twin/editor/scene_tree.js'));
const {createCards,findPiece}=await import(file('static/twin/editor/cards.js'));
const {deleteOperation}=await import(file('static/twin/editor/piece_operations.js'));
const plan=structuredClone(input.plan),model=structuredClone(input.model),host=document.getElementById('piece-card');
const stale={pieceId:'shade',buildingId:'b',kind:'awning'};
await test('migrated scene row is an ordinary independently selectable roof labelled Awning',()=>{
 const rows=sceneRows(plan).filter(r=>r.id==='shade');assert.equal(rows.length,1);
 assert.equal(rows[0].kind,'roof');assert.ok(rows[0].name.startsWith('Awning'),rows[0].name);assert.equal(rows[0].parent.id,'L1');
});
await test('a stale extension selection edits and deletes the preserved roof id through the roof form',async()=>{
 const edits=[],ops=[];window.showGlobalAlert=message=>{throw Error(message);};
 assert.equal(findPiece(plan,stale.pieceId,stale.buildingId).kind,'roof');
 const cards=createCards({getPlan:()=>plan,getModel:()=>model,getKit:()=>({}),getLabel:()=> 'Roof',getSelection:()=>stale,
  canEdit:()=>true,select(){},ask(){},edit:async operation=>edits.push(operation),op:async operation=>ops.push(operation)});
 cards.draw(stale);assert.ok(host.querySelector('h3').textContent.startsWith('Awning'));
 const label=host.querySelectorAll('label').find(n=>n.textContent.startsWith('Pitch'));assert.ok(label,'ordinary roof pitch form');
 const control=label.querySelector('input');control.value='4';fire(control,'change');await tick();await cards.queue(()=>{});await tick();
 assert.deepEqual(edits,[{op:'set',building:'b',piece:'shade',field:'pitch',value:4}]);
 assert.deepEqual(deleteOperation(plan,stale,model),{op:'delete',building:'b',id:'shade'});
});
await test('stale duplicated extension metadata never adds a second special scene row',()=>{
 plan.buildings[0].roof.extensions=[{id:'shade',kind:'awning',section:'main'}];
 assert.equal(sceneRows(plan).filter(r=>r.id==='shade').length,1);
});
finish();
"""

if __name__ == '__main__':
    b=building()
    b['roof']['sections']=b['roof']['sections'][:1]
    b['roof']['extensions']=[old_extension()]
    model,_=assemble({'units':'ft','buildings':[b]})
    code,output=run_node(DRIVER,{'root':ROOT.as_posix(),'model':model,'plan':flatten(model)})
    print(output,end='')
    sys.exit(code or 0)
