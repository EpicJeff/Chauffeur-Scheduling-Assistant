"""The shared asset row: selection, accepted pointer drops and optional controls."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const module=await import(file('static/twin/editor/slot_row.js')).catch(()=>({}));
await test('slot row builder exists',()=>assert.equal(typeof module.createSlotRow,'function'));
if(!module.createSlotRow)finish();
const {createSlotRow}=module;
let selected=null;const subscribers=new Set(),reveals=[],calls=[];
const library={selected:()=>selected,onSelect:fn=>{subscribers.add(fn);return()=>subscribers.delete(fn);},reveal:(...args)=>reveals.push(args)};
const select=entry=>{selected=entry;for(const fn of subscribers)fn(entry);};
const stone={kind:'material',id:'stone',name:'Family stone',thumb:'/stone.png'};
const door={kind:'door',id:'door',name:'Oak door'};
let current=null;
const row=createSlotRow({label:'Outside',subject:'outside face material',accepts:e=>e.kind==='material',current:()=>current,
 apply:entry=>calls.push(entry),clear:()=>calls.push(null),library});
document.body.append(row.element);
const use=()=>row.element.querySelector('[data-slot-use]');
const swatch=()=>row.element.querySelector('[data-slot-swatch]');
await test('selection updates visible rows without rebuilding Properties',async()=>{
 assert.equal(use().disabled,true);assert.equal(use().getAttribute('aria-label'),'Use selected');
 assert.equal(row.element.querySelector('[data-slot-name]').textContent,'Default');
 const label=row.element.querySelector('[data-slot-label]');assert.equal(use().getAttribute('aria-describedby'),label.id);
 select(stone);assert.equal(use().disabled,false);assert.equal(use().getAttribute('aria-label'),'Use Family stone');
 await click(use());assert.equal(calls.at(-1),stone);
 select(door);assert.equal(use().disabled,true);assert.equal(use().getAttribute('aria-label'),'Use selected');
 await click(use());assert.equal(calls.length,1,'wrong kind never applies even if an event is dispatched');
 select(null);assert.equal(use().disabled,true);
});
await test('swatch reveals only on click and refresh draws current asset',async()=>{
 current=stone;row.refresh();assert.equal(row.element.querySelector('[data-slot-name]').textContent,'Family stone');
 assert.equal(swatch().getAttribute('aria-label'),'Show the outside face material in the Library');
 assert.equal(swatch().querySelector('img').src,'/stone.png');
 await fire(row.element,'pointerenter');swatch().focus();assert.equal(reveals.length,0);
 await click(swatch());assert.deepEqual(reveals,[['material','stone']]);
 current={id:'tint',kind:'material',name:'Tint',color:'#123456'};row.refresh();assert.equal(swatch().style.backgroundColor,'#123456');
 await click(row.element.querySelector('[data-slot-clear]'));assert.equal(calls.at(-1),null);
 current=null;row.refresh();assert.equal(swatch().disabled,true);assert.ok(swatch().classList.contains('editor-slot-empty'));
});
await test('optional detail preserves provenance and refresh; absent or empty detail keeps the name',()=>{
 let detail='Porch roof metal, set here';
 const described=createSlotRow({label:'Roof',accepts:()=>true,current:()=>stone,detail:()=>detail,apply(){},library});
 const name=described.element.querySelector('[data-slot-name]');
 assert.equal(name.textContent,'Porch roof metal, set here');
 detail='Bake siding, from the building';described.refresh();assert.equal(name.textContent,detail);
 detail='House look';described.refresh();assert.equal(name.textContent,'House look');
 detail='';described.refresh();assert.equal(name.textContent,stone.name);
 assert.equal(row.element.querySelector('[data-slot-name]').textContent,'Default','ordinary empty row retains its fallback');
 described.dispose();
});
await test('accepted pointer payload highlights and applies; other kinds do neither',async()=>{
 const send=(phase,entry)=>fire(row.element,'chf-library-slot-drag',{detail:{phase,entry}});
 await send('over',stone);assert.ok(row.element.classList.contains('editor-slot-dragover'));
 await send('leave',stone);assert.ok(!row.element.classList.contains('editor-slot-dragover'));
 const before=calls.length;await send('over',door);assert.ok(!row.element.classList.contains('editor-slot-dragover'));
 await send('drop',door);assert.equal(calls.length,before);
 await send('drop',stone);assert.equal(calls.at(-1),stone);assert.ok(!row.element.classList.contains('editor-slot-dragover'));
});
await test('model predicate distinguishes door and window and default can say Generated',async()=>{
 const model=createSlotRow({label:'Model',accepts:e=>e.kind==='door',current:()=>({name:'Generated'}),apply:e=>calls.push(e),clear:()=>calls.push({model:null}),library});
 select(stone);assert.equal(model.element.querySelector('[data-slot-use]').disabled,true);
 select({kind:'window',id:'window',name:'Window'});assert.equal(model.element.querySelector('[data-slot-use]').disabled,true);
 select(door);await click(model.element.querySelector('[data-slot-use]'));assert.equal(calls.at(-1),door);
 assert.equal(model.element.querySelector('[data-slot-name]').textContent,'Generated');model.dispose();
});
await test('reset and tint are opt in with the existing accessible names and values',async()=>{
 assert.equal(row.element.querySelector('input'),null);assert.equal(row.element.querySelector('[data-slot-reset]'),null);
 const tintCalls=[],optional=createSlotRow({label:'Slab',accepts:e=>e.kind==='material',current:()=>stone,apply(){},clear(){},library,
 reset:{label:'Clear for this floor',run:()=>tintCalls.push('reset')},
 tint:{value:()=>'#abc123',set:v=>tintCalls.push(v),clear:()=>tintCalls.push('clear')}});
 assert.equal(optional.element.querySelector('input').getAttribute('aria-label'),'Slab override tint');
 assert.equal(optional.element.querySelector('input').value,'#abc123');
 optional.element.querySelector('input').value='#456789';await fire(optional.element.querySelector('input'),'change');
 await click(optional.element.querySelector('[data-slot-reset]'));
 await click(optional.element.querySelectorAll('button').find(b=>b.textContent==='Clear override'));
 assert.deepEqual(tintCalls,['#456789','reset','clear']);optional.dispose();
});
await test('swatch reports a rejected catalogue reveal',async()=>{
 const errors=[],previous=window.showGlobalAlert;window.showGlobalAlert=text=>errors.push(text);
 const failed=createSlotRow({label:'Floor',accepts:()=>true,current:()=>stone,apply(){},clear(){},library:{...library,reveal:async()=>{throw Error('Catalogue unavailable');}}});
 await click(failed.element.querySelector('[data-slot-swatch]'));
 assert.deepEqual(errors,['Catalogue unavailable']);failed.dispose();window.showGlobalAlert=previous;
});
await test('dispose releases selection subscription and controls',async()=>{
 const button=use(),before=calls.length;row.dispose();select(stone);assert.equal(button.disabled,true);assert.equal(subscribers.size,0);
 await click(button);assert.equal(calls.length,before,'disposed row does not assign');
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(out)
    sys.exit(code)
