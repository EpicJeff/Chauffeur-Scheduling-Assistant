"""Drive the real path shelf controls and queued domain operations under Node."""
import json
import sys
from test_twin_ground_js import PREFIX, ROOT
from twin_editor_dom import run_node

DRIVER = PREFIX + r"""
const {drawSiteShapeShelf,siteMaterialSlots}=await import(file('static/twin/editor/site_shape_shelf.js'));
const {PAVER_DEFAULTS}=await import(file('static/twin/paver_layout.js'));
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
function card(pavers,editable=true){
 const host=new Element(),ops=[],errors=[],record={kind:'hardscape',index:0,piece:{id:'walk',kind:'path',points:[[0,0],[12,0]],width:5,...(pavers===undefined?{}:{pavers})}};
 let pending=Promise.resolve();
 drawSiteShapeShelf(host,record,{canEdit:()=>editable,queue:fn=>pending=pending.then(fn),op:op=>{ops.push(op);Object.assign(record.piece,op);},report:e=>errors.push(e)});
 const control=label=>descendants(host).find(n=>n['aria-label']===label);
 return {host,ops,errors,record,control,async set(label,value){const n=control(label);assert.ok(n,label);n.value=String(value);n.dispatchEvent(new Event('change'));await pending;await Promise.resolve();assert.deepEqual(errors,[]);}};
}
const labels=['Layout','Paver length (in)','Paver width (in)','Gap (in)','Rotation (degrees)','Edges','Joints'];
const solid=card();assert.equal(solid.control('Surface').value,'solid');for(const label of labels)assert.equal(solid.control(label),undefined);
await solid.set('Surface','pavers');assert.equal(solid.ops.length,1);assert.deepEqual(solid.ops[0],{op:'update_site_shape',list:'hardscape',index:0,pavers:PAVER_DEFAULTS});
const p=card({...PAVER_DEFAULTS,gap_in:4});assert.equal(p.control('Surface').value,'pavers');
assert.deepEqual(p.control('Layout').children.map(o=>[o.value,o.textContent]),[['stepping','Stepping stones'],['grid','Grid'],['running_bond','Running bond'],['diagonal','Diagonal'],['herringbone','Herringbone']]);
assert.deepEqual(p.control('Edges').children.map(o=>o.textContent),['Whole pavers only','Cut at the edge']);
assert.deepEqual(p.control('Joints').children.map(o=>o.textContent),['Grass','Gravel','Sand','None']);
await p.set('Layout','herringbone');assert.deepEqual(p.ops.at(-1).pavers,{...PAVER_DEFAULTS,gap_in:4,layout:'herringbone'});
await p.set('Paver length (in)',36);assert.equal(p.ops.length,2);assert.deepEqual(p.ops.at(-1).pavers,{...PAVER_DEFAULTS,gap_in:4,layout:'herringbone',length_in:36});
for(const [label,value,key] of [['Paver width (in)',12,'width_in'],['Gap (in)',6,'gap_in'],['Rotation (degrees)',-15,'rotation'],['Edges','cut','edge'],['Joints','sand','joint']]){
 const before=p.ops.length;await p.set(label,value);assert.equal(p.ops.length,before+1);assert.equal(p.ops.at(-1).pavers[key],value);assert.equal(p.ops.at(-1).pavers.length_in,36);
}
for(const [label,min,max] of [['Paver length (in)',2,60],['Paver width (in)',2,60],['Gap (in)',0,48],['Rotation (degrees)',-90,90]]){
 const n=p.control(label);assert.equal(n.min,String(min));assert.equal(n.max,String(max));
}
await p.set('Surface','solid');assert.deepEqual(p.ops.at(-1).pavers,null);
for(const joint of ['grass','gravel','sand','none']){
 const c=card({...PAVER_DEFAULTS,joint}),slot=descendants(c.host).filter(n=>n.dataset?.materialSlot==='Joint');
 assert.equal(slot.length,['gravel','sand'].includes(joint)?1:0,joint);
 assert.equal(siteMaterialSlots('hardscape',c.record.piece).some(s=>s[0]==='joint'),!!slot.length);
}
for(const joint of ['grass','gravel','sand','none']){
 const c=card({...PAVER_DEFAULTS,joint},false);
 for(const label of ['Surface',...labels])assert.equal(c.control(label).disabled,true,label);
 await c.set('Surface','solid');await c.set('Layout','stepping');assert.equal(c.ops.length,0);
}
console.log('Paver card: solid legacy, switches, full current object, labels, ranges, joint slot and read-only passed');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}, timeout=180)
    print(output)
    sys.exit(code or 0)
