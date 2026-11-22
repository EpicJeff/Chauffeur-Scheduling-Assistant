"""Fix-round probes, executed by test_twin_clipboard_js on the real modules."""
FIX_DRIVER = r"""
await test('fix1_surface_hits_and_fallback_convert_metres_once_for_plant_fixture_pad',async()=>{
 const THREE=await import('three'),{contextSurfaceForHit,contextPoint}=await import(file('static/twin/editor/library.js'));
 const r=rig(),pad={id:'surface-pad',polygon:[[50,50],[100,50],[100,100],[50,100]],height:0};r.plan.site.terraces.push(pad);
 const mesh=new THREE.Mesh(new THREE.BufferGeometry(),new THREE.MeshBasicMaterial());mesh.userData={kind:'pad',pieceId:pad.id};
 const surface=contextSurfaceForHit(r.plan,{object:mesh,point:new THREE.Vector3(75*.3048,0,-60*.3048)});
 assert.deepEqual(surface.point,[75,60,0]);
 const target={kind:'terraces',id:pad.id,...surface};
 const fx={id:'fixture:00000000-0000-4000-8000-000000000aaa',shape:'point',ref:'ground',at:[20,20,2]};r.plan.light_fixtures={'light.test':[fx]};
 const small={id:'small-pad',polygon:[[20,20],[22,20],[22,22],[20,22]],height:0};r.plan.site.terraces.push(small);
 for(const source of [tree,ref('light_fixture',fx.id),ref('terraces',small.id)]){
  r.c.copy([source]);assert.equal((await r.c.paste({mode:1,target,point:surface.point})).ok,true,r.status());const op=r.posts.at(-1).ops[0];
  const at=op.at||op.fixture?.at||[op.polygon[0][0]+1,op.polygon[0][1]+1];assert.deepEqual(at.slice(0,2),[75,60]);if(op.fixture)assert.equal(at[2],0);
 }
 const pb=r.plan.buildings[0],room=pb.rooms.find(p=>p.state!=='ghost'),q=[0,1].map(i=>room.polygon.reduce((n,p)=>n+p[i],0)/room.polygon.length),a=(pb.rotation||0)*Math.PI/180;
 const xy=[q[0]*Math.cos(a)-q[1]*Math.sin(a)+(pb.position?.[0]||0),q[0]*Math.sin(a)+q[1]*Math.cos(a)+(pb.position?.[1]||0)];
 const raw=[xy[0]*.3048,0,-xy[1]*.3048],point=contextPoint(r.plan,pb,raw);
 r.c.copy([tree]);assert.equal((await r.c.paste({mode:1,target:{kind:'room',id:room.id,building:pb.id,point}})).ok,true,r.status());
 r.posts.at(-1).ops[0].at.forEach((v,i)=>assert.ok(Math.abs(v-xy[i])<1e-7));
 mesh.userData={kind:'room',pieceId:room.id,buildingId:pb.id};const buildingSurface=contextSurfaceForHit(r.plan,{object:mesh,point:new THREE.Vector3(...raw)});
 assert.deepEqual(buildingSurface.point,point);r.c.copy([ref('light_fixture',fx.id)]);
 assert.equal((await r.c.paste({mode:1,target:{...buildingSurface,id:room.id},point:buildingSurface.point})).ok,true,r.status());
 const {fixtureReference}=await import(file('static/twin/live/emitters.js')),saved=r.posts.at(-1).ops[0].fixture;
 assert.ok(Math.abs(saved.at[2]+fixtureReference(r.plan,saved,saved.at))<1e-7);
});
await test('fix2_repeat_ctrl_v_plant_pad_window_and_empty_selection_advance',async()=>{
 for(const kind of ['planting','terraces','opening']){
  const r=rig();let source;
  if(kind==='planting'){r.plan.site.planting[0].at=[30,30];source=tree;}
  if(kind==='terraces'){const p={id:'repeat-pad',polygon:[[20,20],[22,20],[22,22],[20,22]],height:0};r.plan.site.terraces.push(p);source=ref(kind,p.id);}
  if(kind==='opening'){
   const pb=r.plan.buildings[0],wall=pb.walls.find(w=>Math.hypot(...w.to.map((v,i)=>v-w.from[i]))>20&&w.kind!=='separator');
   const p={...pb.openings.find(o=>o.kind==='window'),id:'repeat-window',wall:wall.id,at:3,width:.5};pb.openings=[p];source=ref(kind,p.id,bid);
  }
  r.selection.set([source]);clipboardKey({key:'c',ctrlKey:true,preventDefault(){}},r.c);
  const positions=[];
  for(let n=1;n<=3;n++){
   assert.equal((await clipboardKey({key:'v',ctrlKey:true,preventDefault(){}},r.c)).ok,true,r.status());
   const op=r.posts.at(-1).ops[0];positions.push(kind==='opening'?op.at:kind==='terraces'?op.polygon[0][0]:op.at[0]);
   if(kind==='opening')r.plan.buildings[0].openings.push({...op});else r.plan.site[kind].push({...op});
   assert.doesNotMatch(r.status(),/No valid host/);if(n===2)r.selection.clear();
  }
  assert.equal(new Set(positions).size,3);assert.equal(positions[1]-positions[0],.5);assert.equal(positions[2]-positions[1],.5);assert.equal(r.posts.length,3);
 }
});
await test('fix3_household_36_plants_one_step_edge_refusal_and_cut_in_place',async()=>{
 const r=rig(),refs=r.plan.site.planting.map(p=>ref('planting',p.id));assert.equal(refs.length,36);
 assert.equal((await r.c.duplicate(refs)).ok,true,r.status());assert.equal(r.posts.length,1);
 r.posts[0].ops.forEach((op,i)=>assert.deepEqual(op.at,r.plan.site.planting[i].at.map((v,a)=>v+(a===0?.5:-.5))));packet(r,'fix3 household 36 duplicate');
 const edge=rig();edge.plan.site.lot=[[0,0],[10,0],[10,10],[0,10]];edge.plan.site.planting[0].at=[9.8,5];edge.c.copy([tree]);
 assert.equal((await edge.c.paste()).ok,false);assert.match(edge.status(),/outside the lot/);assert.equal(edge.posts.length,0);
 const cut=rig(),p=cut.plan.site.planting[0];assert.equal((await cut.c.cut([tree])).ok,true);cut.plan.site.planting.shift();cut.raw.site.planting.shift();
 assert.equal((await cut.c.paste()).ok,true,cut.status());assert.deepEqual(cut.posts[1].ops[0].at,p.at);assert.equal(cut.posts[1].ops[0].id,p.id);
});
await test('fix4_cut_same_owner_keeps_flags_cross_owner_gets_new_id_despite_collision',async()=>{
 for(const cross of [false,true]){
  const r=rig(),pb=r.plan.buildings[0],p={id:'owner-prop',asset:'chair',host:{floor:pb.rooms[0].id,u:.5,v:.5}};
  pb.items.push(p);r.raw.buildings[0].items.push(structuredClone(p));const source=ref('item',p.id,bid);r.visibility.hide(p.id);r.visibility.lock(p.id);
  await r.c.cut([source]);pb.items=pb.items.filter(x=>x.id!==p.id);
  if(cross){const other=structuredClone(pb);other.id='other-owner';other.items=[structuredClone(p)];r.plan.buildings.push(other);
   assert.equal((await r.c.paste({mode:2,target:{kind:'room',id:other.rooms[0].id,building:other.id}})).ok,true,r.status());
   assert.notEqual(r.posts[1].ops[0].id,p.id);assert.match(r.status(),/new identity/);assert.equal(r.visibility.isHidden(r.posts[1].ops[0].id),false);
  }else{assert.equal((await r.c.paste()).ok,true,r.status());assert.equal(r.posts[1].ops[0].id,p.id);assert.ok(r.visibility.isHidden(p.id)&&r.visibility.isLocked(p.id));}
 }
 const r=rig(),p=r.plan.site.planting[0];await r.c.cut([tree]);const frozen=r.c.contents();
 // Undo has restored the original in the plan; the clipboard itself is intact.
 assert.deepEqual(r.c.contents(),frozen);assert.equal((await r.c.paste()).ok,true,r.status());
 assert.notEqual(r.posts[1].ops[0].id,p.id);assert.match(r.status(),/new identity/);
});
await test('fix6_native_text_shift_repeat_and_bookmark_key_guards',async()=>{
 const called=[];const c=Object.fromEntries(['copy','cut','paste','duplicate'].map(k=>[k,()=>called.push(k)]));
 const old=globalThis.getSelection;globalThis.getSelection=()=>({isCollapsed:false});
 try{for(const key of ['c','x']){let prevented=false;clipboardKey({key,ctrlKey:true,preventDefault(){prevented=true;}},c);assert.equal(prevented,false);} }
 finally{globalThis.getSelection=old;}
 for(const key of ['c','x','v','d'])clipboardKey({key,ctrlKey:true,shiftKey:true,preventDefault(){assert.fail('shift shortcut consumed');}},c);
 for(const key of ['v','d']){let prevented=false;clipboardKey({key,ctrlKey:true,repeat:true,preventDefault(){prevented=true;}},c);assert.ok(prevented);}
 assert.deepEqual(called,[]);let prevented=false;clipboardKey({key:'d',ctrlKey:true,preventDefault(){prevented=true;}},c);assert.ok(prevented);assert.deepEqual(called,['duplicate']);
});
await test('fix9_opening_inheritance_same_building_and_frozen_cross_building',async()=>{
 const r=rig(),pb=r.plan.buildings[0],p=pb.openings.find(o=>o.id===windowRef.pieceId);delete p.materials;delete p.model;
 r.c.copy([windowRef]);assert.equal((await r.c.paste({mode:3})).ok,true,r.status());assert.equal(r.posts[0].ops[0].materials,undefined);
 const other=structuredClone(pb);other.id='other-building';other.openings=[];r.plan.buildings.push(other);
 assert.equal((await r.c.paste({mode:2,target:{kind:'wall',id:p.wall,building:other.id}})).ok,true,r.status());
 assert.ok(Object.keys(r.posts[1].ops[0].materials).length>0);
});
await test('fix10_duplicate_leaves_cut_clipboard_and_first_paste_identity',async()=>{
 const r=rig(),p=r.plan.site.planting[0],other=ref('planting',r.plan.site.planting[1].id);
 await r.c.cut([tree]);r.plan.site.planting.shift();const frozen=r.c.contents();
 const pending=r.c.duplicate([other]);assert.deepEqual(r.c.contents(),frozen,'clipboard is intact while duplicate saves');
 assert.equal((await pending).ok,true,r.status());assert.deepEqual(r.c.contents(),frozen);
 r.selection.clear();assert.equal((await r.c.paste()).ok,true,r.status());assert.equal(r.posts[2].ops[0].id,p.id);assert.deepEqual(r.posts[2].ops[0].at,p.at);
});
await test('fix11_beds_are_hosts_in_modes_one_and_two',async()=>{
 const r=rig(),bed={id:'host-bed',polygon:[[30,30],[40,30],[40,40],[30,40]],material:'mulch'};r.plan.site.beds.push(bed);r.c.copy([tree]);
 for(const mode of [1,2]){assert.equal((await r.c.paste({mode,target:{kind:'beds',id:bed.id},point:[35,35]})).ok,true,r.status());assert.deepEqual(r.posts.at(-1).ops[0].at,[35,35]);}
});
await test('fix12_shared_cards_offer_plant_height_seed_opening_glass_and_shape_elevation',async()=>{
 window.twinObjectSchema=input.objectSchema;
 const originalFetch=globalThis.fetch;globalThis.fetch=async()=>({ok:true,status:200,text:async()=>'[]'});
 const {drawObjectShelf}=await import(file('static/twin/editor/object_shelf.js')),{drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
 const ops=[],options={canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async o=>ops.push(o),report:e=>{throw e;},ownSlot(){},getPlan:()=>input.plan,getKit:()=>input.kit};
 for(const [record,fields] of [[{kind:'planting',piece:plant,index:0},[['Plant height (ft)','19'],['Plant variation seed','43']]],
  [{kind:'opening',piece:b.openings.find(o=>o.kind==='door'),building:b},[['Door glass','half']]]]){
  const host=document.createElement('div');drawObjectShelf(host,record,options);
  for(const [label,value] of fields){const field=host.querySelector(`[aria-label="${label}"]`);assert.ok(field,label);field.value=value;field.dispatchEvent(new Event('change'));}
 }
 for(const kind of ['beds','pool','yard_rooms']){
  const host=document.createElement('div');drawSiteShapeShelf(host,{kind,piece:{id:'card-'+kind,polygon:[[20,20],[24,20],[24,24],[20,24]]}},options);
  const field=host.querySelector('[aria-label="Height above surface (ft)"]');assert.ok(field,kind);field.value='2';field.dispatchEvent(new Event('change'));
 }await new Promise(r=>setTimeout(r,0));
 assert.ok(ops.some(o=>o.properties?.height===19));assert.ok(ops.some(o=>o.properties?.seed===43));assert.ok(ops.some(o=>o.properties?.glass==='half'));assert.ok(ops.some(o=>o.elevation===2));
 globalThis.fetch=originalFetch;
});
"""


def server_checks(client, headers, model):
    from copy import deepcopy
    from unittest.mock import patch
    from services import twin_store
    twin_store.update_model(lambda _: deepcopy(model), kind='build')
    before = twin_store.current_model()
    plant = before['site']['planting'][0]
    outside = [10000, 10000]
    poly = [[10000, 10000], [10004, 10000], [10004, 10004], [10000, 10004]]
    creates = [
        {'op': 'add_site_item', 'list': 'planting', 'asset': plant.get('asset') or plant['preset'], 'at': outside},
        {'op': 'add_site_item', 'list': 'furniture', 'asset': 'chair', 'at': outside},
        {'op': 'add_pad', 'polygon': poly, 'height': 0},
        *({'op': 'add_site_shape', 'list': name, 'polygon': poly} for name in ('beds', 'hardscape', 'edges')),
        {'op': 'add_site_shape', 'list': 'hardscape', 'kind': 'path', 'points': poly[:2], 'width': 3},
        {'op': 'add_site_shape', 'list': 'fence', 'polyline': poly[:2], 'height': 6},
        {'op': 'add_site_shape', 'list': 'fire_pit', 'at': outside, 'radius': 2},
    ]
    for op in creates:
        answer = client.post('/api/house/editor/op', headers=headers, json={'op': {'op': 'batch', 'ops': [op]}})
        assert answer.status_code == 400 and 'lot' in answer.text.lower(), (op, answer.text)
        assert twin_store.current_model() == before, 'outside-lot batch published nothing'
    print(f'  ok Fix 3 HTTP: {len(creates)} outside-lot create paths refuse atomically')

    building = before['buildings'][0]
    door = next(p for p in building['openings'] if p['kind'] == 'door')
    bed = before['site']['beds'][0]
    changes = [
        {'op': 'set_object', 'list': 'planting', 'id': plant['id'], 'properties': {'height': 19, 'seed': 2345678901}},
        {'op': 'set_object', 'building': building['id'], 'id': door['id'], 'properties': {'glass': 'half'}},
        {'op': 'set', 'building': building['id'], 'id': door['id'], 'field': 'panels', 'value': 3},
        {'op': 'update_site_shape', 'list': 'beds', 'id': bed['id'], 'elevation': 2},
    ]
    for op in changes:
        answer = client.post('/api/house/editor/op', headers=headers, json={'op': op})
        assert answer.status_code == 200, (op, answer.text)
    saved = twin_store.current_model()
    assert saved['site']['planting'][0]['height'] == 19 and saved['site']['planting'][0]['seed'] == 2345678901
    saved_door = next(p for p in saved['buildings'][0]['openings'] if p['id'] == door['id'])
    assert saved_door['glass'] == 'half' and saved_door['panels'] == 3
    assert saved['site']['beds'][0]['elevation'] == 2
    for name in ('pool', 'yard_rooms'):
        if name == 'yard_rooms':
            answer = client.post('/api/house/editor/op', headers=headers, json={'op': {'op': 'add_site_shape', 'list': name,
                'id': 'elevation-room', 'polygon': [[20, 20], [24, 20], [24, 24], [20, 24]], 'elevation': 1}})
            assert answer.status_code == 200, answer.text
        op = {'op': 'update_site_shape', 'list': name, 'index': 0, 'elevation': 3}
        if name == 'yard_rooms':
            op['id'] = 'elevation-room'
        answer = client.post('/api/house/editor/op', headers=headers, json={'op': op})
        assert answer.status_code == 200, answer.text
    print('  ok Fix 12 HTTP: plant height/seed, opening glass/panels, shape elevation updates')

    wall = building['walls'][0]
    ops = [{'op': 'add_anchor', 'building': building['id'], 'id': f'restore-{i}', 'kind': 'sensor',
            'host': {'wall': wall['id'], 'at': 2+i, 'z': 3, 'side': 'left'}, 'device': f'restore_device_{i}'} for i in range(2)]
    for available in (True, False):
        twin_store.update_model(lambda _: deepcopy(before), kind='build')
        catalogue = {'available': available, 'devices': [{'device_id': o['device'], 'kind': 'sensor',
                    'name': o['device'], 'entity_id': f'sensor.restore_{i}'} for i, o in enumerate(ops)], 'areas': []}
        with patch('services.twin_ha.safe_catalogue', return_value=catalogue) as fetch:
            answer = client.post('/api/house/editor/op', headers=headers, json={'op': {'op': 'batch', 'ops': ops}})
        assert answer.status_code == 200, answer.text
        assert fetch.call_count == 1, fetch.call_count
    print('  ok Fix 13 HTTP: two restored anchors fetch one catalogue, including unavailable HA')

INTEGRATION = r"""
await test('fix7_alert_modal_blocks_scene_clipboard_through_shared_dialog_guard',async()=>{
 const ed=await mountEditor(makeHousehold());try{
  ed.tools.selectionStore.set([{kind:'planting',pieceId:ed.plan.site.planting[0].id}]);ed.tools.clipboard.copy();
  const alert=document.createElement('div');alert.id='cc-alert-modal';document.body.append(alert);
  const before=ed.ops.length;await fire(document,'keydown',{key:'d',ctrlKey:true});await new Promise(r=>setTimeout(r,0));assert.equal(ed.ops.length,before);
  alert.className='hidden';await fire(document,'keydown',{key:'d',ctrlKey:true});await new Promise(r=>setTimeout(r,0));assert.equal(ed.ops.length,before+1);alert.remove();
 }finally{ed.dispose();}
});
await test('fix8_pad_edge_slot_context_menu_copies_and_pastes_material',async()=>{
 const ed=await mountEditor(makeHousehold());try{
  const p=ed.plan.site.terraces[0];p.edges=p.polygon.map(()=>({edge:'sharp',wall:{material:'block',thickness_in:8,above_in:0}}));ed.terrain.choose('terraces',p.id);
  const currentRow=()=>[...document.getElementById('terrain-card').querySelectorAll('[data-library-slot]')].find(n=>/Edge 1 .*face/i.test(n.dataset.librarySlot));let row=currentRow();assert.ok(row,'pad edge wall face slot');
  const event=await fire(row,'contextmenu',{clientX:20,clientY:30});let menu=document.getElementById('editor-context-menu');
  const copy=[...menu.querySelectorAll('button')].find(b=>b.textContent==='Copy material');assert.ok(copy);await click(copy);
  row=currentRow();assert.ok(row);
  await fire(row,'contextmenu',{clientX:20,clientY:30});menu=document.getElementById('editor-context-menu');
  await click([...menu.querySelectorAll('button')].find(b=>b.textContent==='Paste material'));await new Promise(r=>setTimeout(r,0));assert.equal(ed.ops.at(-1).operation.op,'batch');
 }finally{ed.dispose();}
});
"""
