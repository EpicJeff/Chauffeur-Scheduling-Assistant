"""Task 3: production Properties/material builders on the connected household.

Run from chauffeur/: python tests/test_twin_selection_card_js.py. No browser.
UI-generated batches are replayed through TestClient and undone below.
"""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = PRELUDE + r"""
globalThis.fetch=async()=>new Response(JSON.stringify({materials:[],items:[]}));
window.twinObjectSchema=input.objectSchema;
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {createSelection}=await import(file('static/twin/editor/selection.js'));
const {selectionFields}=await import(file('static/twin/editor/selection_fields.js'));
const {selectionSummary,materialSelectionActions}=await import(file('static/twin/editor/selection_card.js'));
const {pieceMaterialSlots,materialsInSelection,replacementOperations,selectUsingMaterial,materialIdForSurface}=await import(file('static/twin/editor/selection_materials.js'));
const {createVisibility}=await import(file('static/twin/editor/visibility.js'));
const {materialLines,contextSurfaceForHit}=await import(file('static/twin/editor/library.js'));
const plan=structuredClone(input.plan),b=plan.buildings[0],bid=b.id,kit=input.kit;
const ref=(kind,pieceId,buildingId)=>({kind,pieceId,...(buildingId?{buildingId}:{})});
const walls=b.walls.filter(w=>w.state!=='ghost').slice(0,3).map(w=>ref('wall',w.id,bid));
const windows=b.openings.filter(o=>o.kind==='window').slice(0,2).map(o=>ref('opening',o.id,bid));
const door=b.openings.find(o=>o.kind==='door'),doorRef=ref('opening',door.id,bid);
const trees=plan.site.planting.slice(0,2).map(p=>ref('planting',p.id));
const host=document.getElementById('piece-card'),scroll=document.createElement('div');document.body.append(scroll);scroll.append(host);
const css=globalThis.getComputedStyle;globalThis.getComputedStyle=node=>node===scroll?{overflowY:'auto',overflow:''}:css?.(node)||{overflowY:'visible',overflow:''};
let selected=null,saves=[],revealed=[],listeners=new Set(),cards;
const library={selected:()=>selected,onSelect:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},reveal:async(...args)=>revealed.push(args)};
const visibility=createVisibility({storage:null});
const selection=createSelection({onChange:()=>cards?.draw(selection.primary())});
const setLibrary=entry=>{selected=entry;for(const fn of [...listeners])fn();};
const draw=()=>cards.draw(selection.primary());
cards=createCards({getPlan:()=>plan,getModel:()=>input.model,getKit:()=>kit,getLabel:()=>'',selectionStore:selection,
  canEdit:()=>true,select:r=>selection.set(r?[r]:[]),library,visibility,view:{state:{view:'ext'}},
  edit:async op=>saves.push(op),op:async op=>saves.push(op),applyBatch:async ops=>saves.push({op:'batch',ops}),
  removeSelection:async()=>{},haLink:{draw(){},state:()=>({available:false})}});
const settle=async()=>{await new Promise(r=>setTimeout(r,0));await cards.queue(async()=>{});await new Promise(r=>setTimeout(r,0));};
const payloads=[];
await test('household_summary_narrows_removes_and_marks_immovable_without_edits',async()=>{
  const room=ref('room',b.rooms[0].id,bid),light=ref('light_fixture','test:light');
  selection.set([...walls,...trees,windows[0],room,light]);
  const summary=host.querySelector('[data-selection-summary]');
  assert.match(summary.textContent,/3 walls · 2 trees · 1 window · 1 room \(moves with its building\) · 1 light/);
  assert.ok(host.querySelector('button').textContent==='Close');
  const narrow=[...summary.querySelectorAll('button')].find(n=>n.textContent==='3 walls');await click(narrow);
  assert.deepEqual(selection.members(),walls);assert.equal(saves.length,0);
  selection.set([...walls,...trees,windows[0]]);
  await fire([...host.querySelector('[data-selection-summary]').querySelectorAll('button')].find(n=>n.textContent==='2 trees'),'click',{metaKey:true});
  assert.deepEqual(selection.members(),[...walls,windows[0]]);assert.equal(saves.length,0);
  assert.ok([...host.querySelectorAll('button')].some(n=>n.textContent==='Narrow to walls (3)'));
});
await test('mixed_field_changes_all_in_one_batch_and_shared_slot_rows',async()=>{
  b.walls.find(w=>w.id===walls[0].pieceId).height=9;b.walls.find(w=>w.id===walls[1].pieceId).height=10;
  selection.set(walls.slice(0,2));
  const height=host.querySelector('[data-field="height"]');assert.equal(height.placeholder,'Mixed');assert.equal(height.value,'');
  height.value='11';await fire(height,'change');await settle();
  const batch=saves.at(-1);assert.equal(batch.op,'batch');assert.equal(batch.ops.length,2);assert.ok(batch.ops.every(op=>op.field==='height'&&op.value===11));payloads.push(batch);
  selection.set(windows);setLibrary({kind:'material',id:'wood_floor',name:'Oak'});
  const row=host.querySelector('[data-library-slot="Frame"]');assert.ok(row);const n=saves.length;
  await click(row.querySelector('[data-slot-use]'));await settle();assert.equal(saves.length,n+1);
  assert.equal(saves.at(-1).ops.length,2);assert.ok(saves.at(-1).ops.every(op=>op.target.part==='window_frame'));payloads.push(saves.at(-1));
});
await test('slot_census_counts_inherited_wall_faces_and_single_door_parts',async()=>{
  const testPlan=structuredClone(plan),tb=testPlan.buildings[0];tb.materials={...tb.materials,siding:{id:'painted_siding'}};
  for(const wall of tb.walls)delete wall.faces;
  const inventory=materialsInSelection(testPlan,walls,kit);
  const expected=walls.flatMap(r=>materialLines({kind:'wall',piece:tb.walls.find(w=>w.id===r.pieceId),building:tb},testPlan,kit)).filter(line=>line.current.id==='painted_siding').length;
  assert.ok(expected>0);assert.equal(inventory.find(row=>row.id==='painted_siding').count,expected);
  const d=tb.openings.find(o=>o.id===door.id);d.materials={door:{id:'wood_floor'},casing:{id:'trim'},window_frame:{id:'black_metal'}};
  assert.equal(materialsInSelection(testPlan,[doorRef],kit).length,3);
  selection.set([doorRef]);const list=host.querySelector('[aria-label="Materials in selection"]');assert.ok(list);
  assert.ok(host.children.indexOf(list)<host.children.indexOf(host.querySelector('[data-library-slot="Door"]')));
});
await test('replacement_only_matching_slots_preserves_tint_uv_defaults_and_slot_filter',async()=>{
  const p=structuredClone(input.plan),pb=p.buildings[0],wr=walls.slice(0,2),dw=pb.openings.find(o=>o.id===door.id);
  pb.materials={...pb.materials,siding:{id:'siding',color:'#abcdef',uv:{u:.2,v:.4,rot:90}}};
  for(const w of pb.walls)delete w.faces;
  dw.materials={door:{id:'siding',color:'#123456',uv:{u:.1,v:.3,rot:270}},casing:{id:'trim'},window_frame:{id:'siding'}};
  const before=JSON.stringify(p);const ops=replacementOperations(p,[...wr,{...doorRef,slots:['door']}],kit.materials.siding?.asset||'siding',{id:'wood_floor'},kit);
  assert.equal(JSON.stringify(p),before);assert.ok(ops.length>=2);
  assert.ok(ops.every(op=>op.op==='set_material'&&!op.target.building&&!op.target.level&&!op.target.site));
  assert.ok(!ops.some(op=>op.target.part==='window_frame'||op.target.part==='casing'));
  const od=ops.find(op=>op.target.part==='door');assert.deepEqual(od.material,{id:'wood_floor',color:'#123456',uv:{u:.1,v:.3,rot:270}});
  const face=ops.find(op=>op.target.wall);assert.deepEqual(face.material,{id:'wood_floor',color:'#abcdef',uv:{u:.2,v:.4,rot:90}});
  payloads.push({op:'batch',ops});
});
await test('materials_list_use_library_disabled_reason_reveal_and_context_choices',async()=>{
  selection.set(walls);setLibrary(null);const list=host.querySelector('[aria-label="Materials in selection"]');
  const use=list.querySelector('[data-slot-use]');assert.ok(use.disabled);assert.match(use.title,/Select a material/);
  setLibrary({kind:'material',id:'wood_floor',name:'Oak'});assert.equal(use.textContent,'Use Oak');assert.ok(!use.disabled);
  const count=saves.length;await click(use);await settle();assert.equal(saves.length,count+1);assert.equal(saves.at(-1).op,'batch');payloads.push(saves.at(-1));
  const live=host.querySelector('[aria-label="Materials in selection"]');await click([...live.querySelectorAll('button')].find(n=>n.textContent==='Show in Library'));await settle();assert.equal(revealed.at(-1)[0],'material');
  await fire(live.querySelector('[data-library-slot]'),'contextmenu');const menu=document.getElementById('editor-context-menu');assert.ok(!menu.hidden);
  assert.ok([...menu.querySelectorAll('button')].some(n=>/in these buildings$/.test(n.textContent)));
  assert.ok([...menu.querySelectorAll('button')].some(n=>/in the yard$/.test(n.textContent)));
});
await test('select_by_material_returns_owners_slots_with_scope_floor_and_visibility',async()=>{
  const p=structuredClone(input.plan),pb=p.buildings[0],other=p.buildings[1];
  p.materials={...p.materials,siding:{id:'shared_finish'},paving:{id:'shared_finish'},patio_concrete:{id:'shared_finish'}};
  for(const building of p.buildings){building.materials={...building.materials,siding:{id:'shared_finish'}};for(const w of building.walls)delete w.faces;}
  const all=selectUsingMaterial(p,'shared_finish',{refs:walls,kit});assert.ok(all.some(r=>r.kind==='wall'&&r.buildingId===bid&&r.slots.length));
  const buildings=selectUsingMaterial(p,'shared_finish',{refs:walls,limit:'buildings',kit});assert.ok(buildings.length);assert.ok(buildings.every(r=>r.buildingId===bid));
  const yard=selectUsingMaterial(p,'shared_finish',{refs:walls,limit:'yard',kit});assert.ok(yard.length);assert.ok(yard.every(r=>!r.buildingId));
  const floor=pb.walls.find(w=>w.id===walls[0].pieceId).level;
  const floorRefs=selectUsingMaterial(p,'shared_finish',{view:{selectionFloor:()=>`${bid}:${floor}`},kit});
  assert.ok(floorRefs.some(r=>!r.buildingId));assert.ok(floorRefs.filter(r=>r.buildingId).every(r=>r.buildingId===bid&&r.level===floor));
  const v=createVisibility({storage:null}),hidden=buildings[0],locked=buildings[1];v.hide(hidden.pieceId);v.lock(locked.pieceId);
  const eligible=selectUsingMaterial(p,'shared_finish',{kit,visibility:v});assert.ok(!eligible.some(r=>r.pieceId===hidden.pieceId||r.pieceId===locked.pieceId));
  v.lock(bid);assert.ok(!selectUsingMaterial(p,'shared_finish',{kit,visibility:v}).some(r=>r.buildingId===bid));
  const wall=pb.walls.find(w=>w.id===walls[0].pieceId),slot=pieceMaterialSlots(p,walls[0],kit).find(slot=>slot.current.id==='shared_finish');
  assert.equal(materialIdForSurface(p,{building:pb,kind:'wall',piece:wall,side:slot.key},kit),'shared_finish');
  const select=createSelection();materialSelectionActions({material:{id:'shared_finish',name:'Finish'},refs:walls,selectionStore:select,getPlan:()=>p,getKit:()=>kit})[0].run();assert.deepEqual(select.members(),all);
});
await test('keep_place_same_kind_add_from_single_and_set_keeps_scroll_focus',async()=>{
  selection.set([walls[0]]);let height=[...host.querySelectorAll('input')].find(n=>n.closest('label')?.textContent==='Height');assert.ok(height);height.focus();scroll.scrollTop=240;
  selection.add(walls[1]);assert.equal(scroll.scrollTop,240);assert.equal(document.activeElement.getAttribute('aria-label'),'Height');assert.ok(host.contains(document.activeElement));
  const frame=()=>{const q=host.querySelector('[data-field="thickness"]');q.focus();scroll.scrollTop=310;};frame();selection.add(walls[2]);assert.equal(scroll.scrollTop,310);assert.equal(document.activeElement.dataset.field,'thickness');assert.ok(host.contains(document.activeElement));
});
await test('unchanged_members_are_skipped_and_poll_keeps_unsaved_input',async()=>{
  const w0=b.walls.find(w=>w.id===walls[0].pieceId),w1=b.walls.find(w=>w.id===walls[1].pieceId);w0.height=9;w1.height=10;
  let field=selectionFields(plan,walls.slice(0,2),{getModel:()=>input.model}).find(f=>f.key==='height');
  assert.equal(field.operations(10).length,1);assert.equal(field.operations(11).length,2);
  w0.height=10;field=selectionFields(plan,walls.slice(0,2),{getModel:()=>input.model}).find(f=>f.key==='height');assert.equal(field.operations(10).length,0);
  selection.set(walls.slice(0,2));const control=host.querySelector('[data-field="height"]');control.value='12';control.focus();draw();
  assert.equal(host.querySelector('[data-field="height"]'),control);assert.equal(control.value,'12');
  selection.set([walls[0]]);selection.set([{...walls[0],slots:['left']}]);
  const list=host.querySelector('[aria-label="Materials in selection"]');assert.equal(list.querySelectorAll('[data-library-slot]').length,1);assert.match(list.textContent,/1 surface/);
});
await test('shared_uv_edits_preserve_each_other_axis_and_model_uses_one_batch',async()=>{
  const pieces=windows.map(r=>b.openings.find(o=>o.id===r.pieceId));
  pieces.forEach((p,i)=>p.materials={...p.materials,window_frame:{id:'wood_floor',uv:{u:.1,v:i?.6:.2,rot:i?90:0}}});
  selection.set(windows);const row=host.querySelector('[data-library-slot="Frame"]'),u=row.querySelector('[data-slot-u]'),v=row.querySelector('[data-slot-v]');
  assert.equal(v.value,'');assert.equal(v.placeholder,'Mixed');u.value='.3';await fire(u,'change');await settle();
  const ops=saves.at(-1).ops;assert.equal(ops.length,2);assert.deepEqual(ops.map(op=>op.material.uv),[{u:.3,v:.2,rot:0},{u:.3,v:.6,rot:90}]);payloads.push(saves.at(-1));
  setLibrary({kind:'window',id:'import:test-window',name:'Test window'});const model=host.querySelector('[data-library-slot="Model"]');assert.ok(model);
  const count=saves.length;await click(model.querySelector('[data-slot-use]'));await settle();assert.equal(saves.length,count+1);assert.equal(saves.at(-1).ops.length,2);assert.ok(saves.at(-1).ops.every(op=>op.properties?.model==='import:test-window'));
});
await test('rendered_context_hits_map_exact_receiving_slots_and_merged_ranges',async()=>{
  const THREE=await import('three');
  const path=structuredClone(plan);path.site.hardscape=[{id:'test:path',kind:'path',points:[[0,0],[10,0]],width:3,edging:'curb',materials:{surface:{id:'stone'},edging:{id:'trim'}}}];
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial());mesh.userData={kind:'hardscape',pieceId:'test:path',bakePart:'curb:0'};
  let surface=contextSurfaceForHit(path,{object:mesh,faceIndex:0,point:new THREE.Vector3()});assert.equal(surface.slot,'edging');assert.equal(materialIdForSurface(path,surface,kit),kit.materials.trim?.asset||'trim');
  mesh.userData={snapRanges:[{start:0,count:3,kind:'hardscape',pieceId:'test:path',bakePart:'curb:0'},{start:3,count:3,kind:'hardscape',pieceId:'test:path',bakePart:'pavers'}]};
  surface=contextSurfaceForHit(path,{object:mesh,faceIndex:1,point:new THREE.Vector3()});assert.equal(surface.slot,'surface');
  const w=b.walls.find(w=>w.id===walls[0].pieceId);mesh.userData={kind:'wall',pieceId:w.id,buildingId:bid,bakePart:'right'};
  surface=contextSurfaceForHit(plan,{object:mesh,faceIndex:0,point:new THREE.Vector3()});assert.equal(surface.slot,'right');
  mesh.userData={kind:'room',pieceId:b.rooms[0].id,buildingId:bid,bakePart:'ceiling'};
  assert.equal(contextSurfaceForHit(plan,{object:mesh,point:new THREE.Vector3()}).slot,'ceiling');
  mesh.geometry.dispose();mesh.material.dispose();
});
await test('porch_foundation_fixture_and_equipment_fields_keep_member_settings',async()=>{
  const porches=plan.buildings.flatMap(owner=>owner.rooms.filter(room=>room.kind==='porch').map(room=>ref('room',room.id,owner.id)));
  assert.ok(porches.length);
  const fields=selectionFields(plan,porches,{getModel:()=>input.model});const lip=fields.find(field=>field.key==='foundation.lip_in');assert.ok(lip);
  const operations=lip.operations(lip.value===1?2:1);assert.ok(operations.length);assert.ok(operations.every(op=>op.op==='set_porch_foundation'&&op.foundation.materials));payloads.push({op:'batch',ops:operations});
  const p=structuredClone(plan);p.light_fixtures={'light.shared':[{id:'shared:area1',shape:'area',at:[0,0,4],size_ft:[2,3],facing:'down'},{id:'shared:area2',shape:'area',at:[1,0,4],size_ft:[4,3],facing:'up'}]};
  let rows=selectionFields(p,[ref('light_fixture','shared:area1'),ref('light_fixture','shared:area2')]);
  const width=rows.find(field=>field.key==='size_ft.0');assert.ok(width.mixed);assert.deepEqual(width.operations(5).map(op=>op.change.size_ft),[[5,3],[5,3]]);assert.ok(rows.find(field=>field.key==='facing').mixed);
  p.effect_fixtures=[{id:'shared:effect1',shape:'point',type:'fire',at:[0,0,0]},{id:'shared:effect2',shape:'point',type:'fire',at:[2,0,0]}];
  rows=selectionFields(p,[ref('effect_fixture','shared:effect1'),ref('effect_fixture','shared:effect2')]);let prompts=0;
  const prompt=window.promptInput;window.promptInput=async()=>String(prompts++?100:0);
  try{const ops=await rows.find(field=>field.key==='sensor').operations('sensor.test');assert.equal(prompts,2);assert.equal(ops.length,2);assert.ok(ops.every(op=>op.change.sensor_min===0&&op.change.sensor_max===100));}finally{window.promptInput=prompt;}
  p.buildings[0].anchors=[{id:'shared:parking1',kind:'parking',width:9,depth:18,host:{floor:b.rooms[0].id,u:.2,v:.2}},{id:'shared:parking2',kind:'parking',width:10,depth:20,host:{floor:b.rooms[0].id,u:.4,v:.4}}];
  rows=selectionFields(p,[ref('anchor','shared:parking1',bid),ref('anchor','shared:parking2',bid)]);assert.deepEqual(rows.find(field=>field.key==='width').operations(11).map(op=>op.value),[11,11]);
});
cards.dispose();console.log('PAYLOADS '+JSON.stringify(payloads));finish();
"""

INTEGRATION = r"""
await test('production_scene_routes_sets_and_restores_single_pad_fixture_cards',async()=>{
 const ed=await mountEditor(makeHousehold());
 try{
  const b=ed.plan.buildings[0],wall={kind:'wall',pieceId:b.walls[0].id,buildingId:b.id},pad={kind:'terraces',pieceId:ed.plan.site.terraces[0].id};
  ed.tools.selectionStore.set([wall,pad,{kind:'light_fixture',pieceId:'fix:yard-1'}]);
  assert.match(ed.dom.pieceCard.textContent,/Selected pieces/);assert.ok(ed.dom.pieceCard.querySelector('[data-selection-summary]'));assert.equal(document.getElementById('terrain-card').hidden,true);
  ed.tools.selectionStore.set([pad]);assert.equal(document.getElementById('terrain-card').hidden,false);assert.match(document.getElementById('terrain-card').textContent,/Ground and yard/);
  ed.tools.selectionStore.set([{kind:'light_fixture',pieceId:'fix:yard-1'}]);assert.ok(ed.dom.pieceCard.dataset.fixtureCard);assert.match(ed.dom.pieceCard.textContent,/Fixtures|light\.yard/);
  assert.equal(ed.ops.length,0);
 }finally{ed.dispose();}
});
await test('rendered_surface_context_entrypoint_selects_slot_owners_without_editing',async()=>{
 const ed=await mountEditor(makeHousehold());
 try{
  const b=ed.plan.buildings[0],wall=b.walls.find(w=>w.exterior&&w.state!=='ghost'),point=wall.from.map((v,i)=>(v+wall.to[i])/2);
  ed.tools.chooseFloor(`${b.id}:${wall.level}`);ed.look([...point,5],b);
  const [clientX,clientY]=ed.pixel([...point,5],b),event={clientX,clientY};
  const surface=ed.library.contextSurfaceAt(event,{kind:'wall',id:wall.id,building:b.id});assert.ok(surface);assert.equal(surface.kind,'wall');
  await fire(ed.canvas,'contextmenu',event);const menu=document.getElementById('editor-context-menu');
  const choose=[...menu.querySelectorAll('button')].find(n=>n.textContent.startsWith('Select all using '));assert.ok(choose,menu.textContent);
  await click(choose);assert.ok(ed.tools.selectionStore.members().length);assert.ok(ed.tools.selectionStore.members().every(r=>r.slots?.length));assert.equal(ed.ops.length,0);
 }finally{ed.dispose();}
});
finish();
"""


def main():
    os.environ.pop('HA_BASE_URL', None)
    with tempfile.TemporaryDirectory(prefix='chauffeur_selection_card_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_store, twin_library
        from test_twin_model_ops_more import _client, _people, _enforced
        logging.getLogger('httpx').setLevel(logging.WARNING)
        fixture = json.loads((ROOT/'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf8'))
        twin_store.push_round(fixture, 'build')
        payload = {'root': ROOT.as_posix(), 'plan': twin_store.current(), 'model': twin_store.current_model(),
                   'kit': twin_library.kit('modern_farmhouse'),
                   'objectSchema': json.loads((ROOT/'static/twin/object_schema.json').read_text(encoding='utf8'))}
        code, output = run_node(DRIVER, payload, timeout=180)
        print('\n'.join(line for line in output.splitlines() if not line.startswith('PAYLOADS ')))
        assert code == 0, output
        batches = json.loads(next(line[9:] for line in output.splitlines() if line.startswith('PAYLOADS ')))
        with _enforced():
            client, headers = _client(), _people()['parent']
            for batch in batches:
                before, round_id, rounds = twin_store.current_model(), twin_store.current_id(), len(twin_store.rounds())
                response = client.post('/api/house/editor/op', headers=headers, json={'op': batch})
                assert response.status_code == 200, (batch, response.text)
                after = twin_store.current_model()
                assert len(twin_store.rounds()) == rounds + 1, 'one batch is one undo step'
                assert after.get('materials') == before.get('materials'), 'house defaults stay unchanged'
                assert [b.get('materials') for b in after['buildings']] == [b.get('materials') for b in before['buildings']], 'building defaults stay unchanged'
                response = client.post('/api/house/twin/revert', headers=headers, json={'round': round_id})
                assert response.status_code == 200 and twin_store.current_model() == before
                if batch['ops'][0].get('field') == 'height':
                    ids = {op.get('id') or op.get('piece') for op in batch['ops']}
                    assert all(w['height'] == 11 for b in after['buildings'] for w in b['walls'] if w['id'] in ids)
            before, rounds = twin_store.current_model(), twin_store.rounds()
            refused = {'op': 'batch', 'ops': [batches[0]['ops'][0], {**batches[0]['ops'][1], 'id': 'missing', 'piece': 'missing'}]}
            response = client.post('/api/house/editor/op', headers=headers, json={'op': refused})
            assert response.status_code == 400, response.text
            error = response.json(); assert error['member'] == 1 and 'missing' in error['error'] and error['reason']
            assert twin_store.current_model() == before and twin_store.rounds() == rounds
            print(f'PASS {len(batches)} UI-generated batches accepted, one history step and undo restores; refusal is atomic')
        from test_twin_selection_js import DRIVER as SCENE_DRIVER
        # Reuse the real household/scene construction, running this task's cases.
        scene_driver = SCENE_DRIVER.rsplit('finish();', 1)[0].replace('await test(', 'await skipPriorScenario(')
        scene_driver = scene_driver.replace('siteHits: (x, y) =>', 'surfaceAt: (event, target) => library?.contextSurfaceAt(event, target), siteHits: (x, y) =>')
        scene_driver = scene_driver.replace('return { plan, dom, view, canvas, tools, visibility, terrain, devices, ops,', 'return { plan, dom, view, canvas, tools, visibility, terrain, devices, library, ops,')
        code, output = run_node('const skipPriorScenario=async()=>{};\n' + scene_driver + INTEGRATION,
                                {**payload, 'flat': payload['plan']}, timeout=180)
        print(output)
        assert code == 0, output
        from test_twin_group_transform_js import check_editor_batch_path
        assert check_editor_batch_path() == 0, 'real boot refusal status, queue and undo/redo'


if __name__ == '__main__':
    main()
