"""Exercise the real room shelf without a browser."""
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {createCards}=await import(file('static/twin/editor/cards.js'));
const room={id:'garage',name:'Garage',level:'L1',polygon:[[0,0],[10,0],[10,10],[0,10]],floor_offset_ft:0};
const plan={buildings:[{id:'b',levels:[{id:'L1',elevation:0,ceiling:10}],rooms:[room],walls:[]}],site:{}};
const calls=[],errors=[];let writable=true;
window.showGlobalAlert=message=>errors.push(message);
const save=async operation=>{calls.push(operation);room[operation.field]=operation.value;};
const cards=createCards({getPlan:()=>plan,getLabel:()=> 'Garage',canEdit:()=>writable,edit:save,op:save,ask(){},select(){}});
cards.draw({pieceId:'garage',buildingId:'b'});
const shelf=document.getElementById('piece-card');
const field=()=>shelf.querySelectorAll('label').find(l=>l.textContent.startsWith('Floor height (relative to this floor)')).querySelector('input');
assert.equal(field().value,`0'-0"`);
field().value='-2';await fire(field(),'change');await cards.queue(async()=>{});
assert.deepEqual(calls.at(-1),{op:'set',building:'b',piece:'garage',field:'floor_offset_ft',value:-2});
assert.equal(field().value,`-2'-0"`);
await fire(visibleButtons('Down 0.5 ft',shelf)[0],'click');await Promise.resolve();await cards.queue(async()=>{});
assert.deepEqual(calls.at(-1),{op:'set',building:'b',id:'garage',field:'floor_offset_ft',value:-2.5});
await fire(visibleButtons('Up 0.5 ft',shelf)[0],'click');await Promise.resolve();await cards.queue(async()=>{});
assert.equal(room.floor_offset_ft,-2);assert.equal(calls.length,3);
writable=false;cards.draw();const before=calls.length;
await fire(visibleButtons('Down 0.5 ft',shelf)[0],'click');await Promise.resolve();await cards.queue(async()=>{});
assert.equal(calls.length,before);assert.deepEqual(errors,[]);
console.log('Passed: real room shelf, feet/inches, set operation, +/-0.5 ft nudges and read-only guard');
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code or 0)
