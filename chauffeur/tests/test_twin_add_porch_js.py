"""Real Draw/Properties entry points over the household, using server op results."""
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_porch_js_')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin_live_node_rig import run
from test_twin_editor_shell_js import page
from services import twin_model_bridge as bridge, twin_model_ops as ops, twin_library

DRIVER = r"""
const el=id=>document.getElementById(id);
const nodes=config.nodes.map(n=>document.createElement(n.tag));
config.nodes.forEach((n,i)=>{for(const [k,v] of Object.entries(n.attrs))nodes[i].setAttribute(k,v??'');
 if(!['script','style'].includes(n.tag))nodes[i].textContent=n.text;
 (n.parent===null?document.body:nodes[n.parent]).append(nodes[i]);});
globalThis.getComputedStyle=node=>({overflowY:node.id==='properties-content'?'auto':'visible',overflow:'visible'});
const {createDraw}=await import(file('static/twin/editor/draw.js')),
 {createDock}=await import(file('static/twin/editor/dock.js')),
 {createCards}=await import(file('static/twin/editor/cards.js')),
 {icon}=await import(file('static/twin/editor/icons.js'));
window.showGlobalAlert=message=>assert.fail(message);
window.promptInput=()=>assert.fail('adding a porch never prompts for a name');
window.promptConfirm=async()=>true;
let plan=structuredClone(config.plan),selection=null,armed=null;
const writes=[],abort=new AbortController(),canvas=document.createElement('canvas');document.body.append(canvas);
const view={renderer3:{domElement:canvas},controls:{enabled:true},screenOfFloor:(x,y)=>[x*20,y*20],floorAt:(x,y)=>[x/20,y/20]};
const dock=createDock({host:el('editor-dock')});
const floor=()=>{const building=plan.buildings.find(b=>b.id===config.operation.building);
 return {building,level:building.levels.find(l=>l.id===config.operation.level),key:building.id+':'+config.operation.level};};
let savingGate=null;
const tools={floor,selection:()=>({}),setTool:t=>armed=t,select:value=>{selection=value;cards.draw(value);}};
const op=async operation=>{writes.push(structuredClone(operation));if(savingGate)await savingGate;
 if(operation.op==='add_porch')plan=structuredClone(config.results[operation.roof]);
 else if(operation.op==='set_room_kind')plan=structuredClone(config.kinds[operation.kind]);
 else if(operation.op==='delete')plan=structuredClone(config.deleted);else assert.fail(JSON.stringify(operation));};
const cards=createCards({dock,getPlan:()=>plan,getLabel:()=>'',getSelection:()=>({}),edit:()=>assert.fail('Type uses model ops'),op,ask(){},canEdit:()=>true,select:tools.select});
const draw=createDraw({dock,view,tools,getPlan:()=>plan,op,gesture:f=>f(),canEdit:()=>true,signal:abort.signal,panel:{message:assert.fail}});
const event=p=>({pointerId:7,clientX:p[0]*20,clientY:p[1]*20});
const drag=async(a,b)=>{draw.pointerDown(event(a));draw.pointerMove(event(b));draw.pointerUp(event(b),false);await wait(40);};
const click=async p=>{draw.pointerDown(event(p));draw.pointerUp(event(p),false);await wait(10);};
const polygon=config.operation.polygon, a=polygon[0], b=polygon[2];
assert.notEqual(icon('add-porch').querySelector('path').getAttribute('d'),icon('select').querySelector('path').getAttribute('d'));
for(const roof of ['shed','gable','none']){
 plan=structuredClone(config.plan);selection=null;await press(el('rail-add-porch'));
 assert.equal(armed,'add-porch');assert.equal(el('draw-note').textContent,'Drag out from an outside wall.');
 const input=el('draw-options').querySelector('select[aria-label="Roof"]');assert.ok(input);
 assert.deepEqual(input.children.map(n=>n.textContent),['Shed','Gable','None']);
 input.value=roof;input.dispatchEvent(new Event('change',{bubbles:true}));
 let release;savingGate=new Promise(resolve=>release=resolve);
 await drag(a,b);assert.equal(selection,null,'do not select before save returns');release();savingGate=null;await wait(50);
 assert.deepEqual(writes.at(-1),{...config.operation,roof});
 assert.equal(armed,'select');assert.equal(selection.pieceId,config.porch);
 assert.ok(!el('piece-card').hidden);assert.match(el('properties-crumbs').textContent,/Porch/);
}
console.log('  ok household rectangle sends one operation for each roof and opens the saved porch card');
plan=structuredClone(config.plan);await press(el('rail-add-porch'));
let count=writes.length;
await drag([1000,1000],[1008,1006]);assert.equal(writes.length,count);
assert.equal(el('draw-note').textContent,'Draw the porch against an outside wall.');
draw.cancel();await press(el('rail-add-porch'));
for(const p of [...polygon,polygon[0]])await click(p);
assert.equal(writes.length,count+1);assert.deepEqual(writes.at(-1).polygon,polygon);
console.log('  ok click corners close once; unattached outlines refuse in the status line');
// The first corner is 0.75 ft away: the porch tool's wall reach is exactly 1 ft.
plan=structuredClone(config.plan);await press(el('rail-add-porch'));
const near=a.map((v,i)=>v+config.normal[i]*.75);await drag(near,b);
assert.deepEqual(writes.at(-1).polygon,polygon);
console.log('  ok snaps an attached edge within one foot of the exterior wall');
// Room Type retains the same Properties scroll and focused field on rebuild.
for(const kind of ['room','porch']){
 const input=el('piece-card').querySelector('select[aria-label="Type"]');assert.ok(input);
 assert.deepEqual(input.children.map(n=>n.textContent),['Room','Porch']);
 const scroll=el('properties-content');scroll.scrollTop=160;input.focus();input.value=kind;
 input.dispatchEvent(new Event('change',{bubbles:true}));await wait(80);
 assert.deepEqual(writes.at(-1),{op:'set_room_kind',building:config.operation.building,room:config.porch,kind});
 assert.equal(scroll.scrollTop,160);assert.equal(document.activeElement.getAttribute('aria-label'),'Type');
 assert.equal(!!el('piece-card').querySelector('select[aria-label="Foundation"]'),kind==='porch');
}
console.log('  ok Type changes both ways through one model op and keeps Properties in place');
const {buildTwin,allPorches}=await import(file('static/twin/twin_generator.js'));
const porchKey=config.operation.building+':'+config.porch;
assert.ok(buildTwin(plan,config.kit,'low').pieces.has(porchKey));
await press(el('piece-card').querySelectorAll('button').find(n=>n.textContent==='Delete'));
assert.deepEqual(writes.at(-1),{op:'delete',building:config.operation.building,id:config.porch});
assert.ok(!allPorches(plan.buildings.find(b=>b.id===config.operation.building)).some(p=>p.id===config.porch));
assert.ok(!buildTwin(plan,config.kit,'low').pieces.has(porchKey),'no remaining porch slab or posts');
// A leftover can still be found, selected and deleted through its own card.
plan=structuredClone(config.orphan);cards.draw({pieceId:config.porch,buildingId:config.operation.building});
await press(el('piece-card').querySelectorAll('button').find(n=>n.textContent==='Delete'));
assert.deepEqual(writes.at(-1),{op:'delete',building:config.operation.building,id:config.porch});
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);draw.cancel();abort.abort();dock.dispose();
console.log('  ok Delete on a porch or leftover removes its generated floor/posts through one model op');
"""


def configuration():
    model = bridge.assemble(json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')))[0]
    # Find a real, clear exterior edge; do not replace the household with a toy.
    for building in model['buildings']:
        points = ops._positions(building)
        for wall in building['walls']:
            if not wall.get('exterior') or wall.get('kind') == 'separator': continue
            a, b = (points[j] for j in wall['joints'])
            dx, dy = b[0]-a[0], b[1]-a[1]
            length = (dx*dx+dy*dy)**.5
            if length < 8 or abs(dx)*abs(dy) > 1e-8: continue
            # Follow the rectangle gesture's fixed corner ordering.
            along = 0 if dx else 1
            lo = list(a); lo[along] = math.ceil((a[along]+b[along])/2 - 4)
            hi = list(lo); hi[along] += 8
            for sign in (-1,1):
                normal = [-dy/length*sign, dx/length*sign]
                start = lo; end = [hi[i]+normal[i]*6 for i in (0,1)]
                across = 1-along
                end[across] = math.ceil(end[across]) if normal[across] > 0 else math.floor(end[across])
                polygon = [start, [end[0],start[1]],end,[start[0],end[1]]]
                operation = dict(op='add_porch',building=building['id'],level=wall['level'],polygon=polygon,roof='shed',host_wall=wall['id'])
                try: changed = ops.apply(model, operation)[0]
                except ValueError: continue
                ids = {r['id'] for r in building['rooms']}
                porch = next(r['id'] for r in next(b for b in changed['buildings'] if b['id']==building['id'])['rooms'] if r['id'] not in ids)
                results = {roof:bridge.flatten(ops.apply(model,dict(operation,roof=roof))[0]) for roof in ('shed','gable','none')}
                kinds = {kind:bridge.flatten(ops.apply(changed,dict(op='set_room_kind',building=building['id'],room=porch,kind=kind))[0]) for kind in ('room','porch')}
                deleted = bridge.flatten(ops.apply(changed,dict(op='delete',building=building['id'],id=porch))[0])
                orphan = json.loads(json.dumps(results['shed']))
                orphan_building = next(b for b in orphan['buildings'] if b['id'] == building['id'])
                orphan_building['rooms'] = [r for r in orphan_building['rooms'] if r['id'] != porch]
                return dict(nodes=page().nodes,plan=bridge.flatten(model),operation=operation,results=results,kinds=kinds,deleted=deleted,orphan=orphan,
                            porch=porch,normal=normal,kit={**twin_library.kit('modern_farmhouse'),'manifest':{}})
    raise AssertionError('No clear household exterior edge found')


if __name__ == '__main__':
    assert shutil.which('node'), 'Node is required'
    sys.exit(run(DRIVER, configuration(), timeout=45))
