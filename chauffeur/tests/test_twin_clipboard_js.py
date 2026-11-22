"""Clipboard on the real household modules, queue and authenticated op route.

Run from chauffeur/: python tests/test_twin_clipboard_js.py. No browser.
"""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from twin_editor_dom import PRELUDE, run_node
from twin_clipboard_fix1 import FIX_DRIVER, INTEGRATION as FIX_INTEGRATION, server_checks

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = PRELUDE + r"""
const {createClipboard,clipboardKey}=await import(file('static/twin/editor/clipboard.js'));
const {createSelection}=await import(file('static/twin/editor/selection.js'));
const {createVisibility}=await import(file('static/twin/editor/visibility.js'));
const {pieceMaterialSlots}=await import(file('static/twin/editor/selection_materials.js'));
const {createEditQueue}=await import(file('static/twin/editor/edit_queue.js'));
const cases=[];
const ref=(kind,pieceId,buildingId)=>({kind,pieceId,...(buildingId?{buildingId}:{})});
function rig(source=input.plan,model=input.model) {
 const plan=structuredClone(source),raw=structuredClone(model),selection=createSelection(),visibility=createVisibility({storage:null});
 let status='',posts=[],round=0;
 const queue=createEditQueue({send:async op=>{posts.push(structuredClone(op));return {round:++round,plan,model:raw};}});
 queue.base({round,plan,model:raw});
 const c=createClipboard({getPlan:()=>plan,getModel:()=>raw,getKit:()=>input.kit,selection,visibility,setStatus:s=>status=s,
  applyBatch:ops=>queue.push({op:{op:'batch',ops},label:'Clipboard'}).saved,canEdit:()=>true});
 return {plan,raw,selection,visibility,c,posts,status:()=>status};
}
const b=input.plan.buildings[0],bid=b.id,plant=input.plan.site.planting[0];
const tree=ref('planting',plant.id),windowRef=ref('opening',b.openings.find(o=>o.kind==='window').id,bid);
function packet(r,name,extra={}){cases.push({name,model:structuredClone(r.raw),batches:structuredClone(r.posts),...extra});}
await test('household_tree_rigid_set_all_properties_and_three_modes',async()=>{
 const r=rig(),trees=r.plan.site.planting.slice(0,3).map(p=>ref('planting',p.id));
 const original=r.plan.site.planting.slice(0,3).map(p=>p.at);
 Object.assign(r.plan.site.planting[0],{tint:'#123456',rotation:31,scale:1.4,scale_axes:[1,2,3],elevation:2});
 for(const p of r.plan.site.planting.slice(0,3))p.at=[p.at[0]+5,p.at[1]]; // pending visible preview; confirmed model is older
 r.selection.set(trees);assert.equal(r.c.copy(trees).ok,true);const frozen=r.c.contents();
 assert.equal((await r.c.paste()).ok,true,r.status());assert.equal(r.posts.length,1);
 const ops=r.posts[0].ops;assert.equal(ops.length,3);assert.equal(new Set(ops.map(o=>o.id)).size,3);
 assert.ok(ops.every(op=>op.require_inside===true),'clipboard opts its yard creates into server containment');
 for(let i=1;i<3;i++)for(let axis=0;axis<2;axis++)assert.ok(Math.abs((ops[i].at[axis]-ops[0].at[axis])-(original[i][axis]-original[0][axis]))<1e-7);
 for(const k of ['height','seed','tint','rotation','scale','scale_axes','elevation'])assert.deepEqual(ops[0][k],r.plan.site.planting[0][k]);
 assert.equal(ops[0].at[0],r.plan.site.planting[0].at[0]+.5,'copy uses the visible queued position');
 assert.notDeepEqual(ops[0].at,plant.at);assert.equal(r.selection.members().length,3);assert.deepEqual(r.c.contents(),frozen);
 assert.equal((await r.c.paste({mode:1,target:{kind:'ground'},point:[40,40]})).ok,true,r.status());
 const centre=[0,1].map(a=>(Math.min(...r.posts[1].ops.map(o=>o.at[a]))+Math.max(...r.posts[1].ops.map(o=>o.at[a])))/2);
 assert.deepEqual(centre,[40,40]);
 const pad={id:'clipboard-pad',polygon:[[-10,-10],[90,-10],[90,90],[-10,90]],height:0};r.plan.site.terraces.push(pad);r.raw.site.terraces.push(pad);
 r.selection.set([ref('terraces',pad.id)]);assert.equal((await r.c.paste()).ok,true,r.status());
 assert.deepEqual(r.posts[2].ops.map(o=>o.at),r.posts[1].ops.map(o=>o.at));packet(r,'trees');
});
await test('structure_refused_and_selection_resolution_fallback_names_reason',async()=>{
 const r=rig();assert.equal(r.c.copy([ref('wall',b.walls[0].id,bid)]).ok,false);assert.match(r.status(),/Copy material/);assert.equal(r.c.contents(),null);
 r.c.copy([tree]);r.selection.set([ref('wall',b.walls[0].id,bid)]);
 assert.equal((await r.c.paste()).ok,true);assert.match(r.status(),/No valid host/);
 assert.equal(r.c.canPaste({kind:'opening',id:windowRef.pieceId,building:bid}).ok,false);
 const n=r.posts.length;r.c.copy([windowRef]);assert.equal((await r.c.paste({mode:1,target:{kind:'ground'},point:[0,0]})).ok,false);assert.equal(r.posts.length,n);assert.match(r.status(),/window needs a wall/);
 assert.equal(createClipboard().contents(),null,'a new session is empty');
});
await test('opening_mode3_selected_original_next_clear_grid_spot_and_wall_gone',async()=>{
 const r=rig();r.selection.set([windowRef]);r.c.copy();const source=r.plan.buildings[0].openings.find(o=>o.id===windowRef.pieceId);
 assert.equal((await r.c.paste()).ok,true,r.status());const op=r.posts[0].ops[0];
 assert.equal(op.wall,source.wall);assert.ok(op.at-source.at>=source.width-1e-7);assert.equal((op.at-source.at)/.5,Math.round((op.at-source.at)/.5));packet(r,'window beside original');
 r.plan.buildings[0].walls=r.plan.buildings[0].walls.filter(w=>w.id!==source.wall);const n=r.posts.length;
 assert.equal((await r.c.paste({mode:3})).ok,false);assert.match(r.status(),/wall is gone/);assert.equal(r.posts.length,n);
});
await test('opening_set_rehosts_order_spacing_mode1_mode2_and_atomic_fit_refusal',async()=>{
 const r=rig(),pb=r.plan.buildings[0],rb=r.raw.buildings[0];
 const wall=pb.walls.filter(w=>w.kind!=='separator'&&w.state!=='ghost').sort((a,b)=>Math.hypot(...b.to.map((v,i)=>v-b.from[i]))-Math.hypot(...a.to.map((v,i)=>v-a.from[i])))[0];
 const template=pb.openings.find(o=>o.kind==='window'),a={...structuredClone(template),id:'copy-window-a',wall:wall.id,at:3,width:2,sill:2,head:6,materials:{window_frame:{id:'black_metal',color:'#123456',uv:{u:.2,v:.4,rot:90}}}},z={...structuredClone(a),id:'copy-window-b',at:7};
 pb.openings=[a,z];rb.openings=[structuredClone(a),structuredClone(z)];
 const refs=[ref('opening',a.id,bid),ref('opening',z.id,bid)];r.selection.set(refs);r.c.copy(refs);
 const target={kind:'wall',id:wall.id,building:bid};
 const length=Math.hypot(...wall.to.map((v,i)=>v-wall.from[i]));assert.ok(length>20);
 r.selection.set([ref('wall',wall.id,bid)]);assert.equal((await r.c.paste()).ok,true,r.status());
 assert.ok(Math.abs(r.posts[0].ops[1].at-r.posts[0].ops[0].at-4)<1e-8);assert.equal(r.posts[0].ops[0].at,length/2-2);
 const point=wall.from.map((v,i)=>v+(wall.to[i]-v)*.7);
 assert.equal((await r.c.paste({mode:1,target,point})).ok,true,r.status());
 assert.ok(Math.abs(r.posts[1].ops[0].at-(length*.7-2))<1e-7);assert.deepEqual(r.posts[1].ops[0].materials.window_frame,a.materials.window_frame);
 const n=r.posts.length;assert.equal((await r.c.paste({mode:1,target,point:wall.from})).ok,false);assert.equal(r.posts.length,n);assert.match(r.status(),/do not fit/);packet(r,'rehost windows');
});
await test('every_free_kind_and_pool_feature_carries_its_recipe',async()=>{
 const samples=[
 ['furniture',{id:'copy-chair',asset:'chair',at:[20,20],object_kind:'decor',scale:1.2,tint:'#abcdef',rotation:25,scale_axes:[2,1,1],casts_shadow:false}],
 ['beds',{id:'copy-bed',polygon:[[20,20],[24,20],[24,24],[20,24]],material:'mulch',elevation:1.5,rotation:15,materials:{fill:{id:'mulch',color:'#123456',uv:{u:.2,v:.3,rot:180}}}}],
 ['hardscape',{id:'copy-path',kind:'path',points:[[20,20],[24,20]],width:3,corner:'mitred',smooth:false,edging:'none',material:'paving',joins:['other-path'],pavers:{length_in:12,width_in:6,gap_in:0,layout:'running_bond',rotation:0,edge:'whole',joint:'grass',lay:'ground'}}],
 ['fence',{id:'copy-fence',polyline:[[20,20],[24,20]],height:6,type:'plank',joins:['neighbour']}],
 ['fire_pit',{id:'copy-pit',shape:'round',at:[20,20],radius:2,fuel:'gas',body:'stone',top:'granite',height_in:18,glass:'blue',entity:'switch.fire'}],
 ['terraces',{id:'copy-pad',polygon:[[20,20],[26,20],[26,26],[20,26]],height:1,blend:1,edges:[{edge:'sharp',wall:{material:'block',thickness_in:8,above_in:0,materials:{face:{id:'base',uv:{u:.2,v:.4,rot:90}}}}},{edge:'slope'},{edge:'slope'},{edge:'slope'}]}],
 ];
 for(const [kind,p] of samples){const r=rig();r.plan.site[kind]=[p];r.raw.site[kind]=[structuredClone(p)];const refs=[ref(kind,p.id)];r.selection.set(refs);assert.equal(r.c.copy(refs).ok,true);
  if(kind==='terraces')assert.equal(r.c.canPaste({kind:'room',pieceId:b.rooms[0].id,buildingId:bid}).ok,false);
  assert.equal((await r.c.paste({mode:1,target:{kind:'ground'},point:[30,30]})).ok,true,r.status());const op=r.posts[0].ops[0];assert.ok(!op.joins);for(const k of ['materials','edges','pavers','asset','tint','scale_axes','entity'])if(p[k]!==undefined)assert.deepEqual(op[k],p[k]);packet(r,kind);}
 for(const kind of ['spa','ledge','steps']) {const r=rig(),pool=r.plan.site.pool,outline=pool.polygon;const xs=outline.map(p=>p[0]),ys=outline.map(p=>p[1]),x=Math.min(...xs)+2,y=Math.min(...ys)+5;
  const p={id:`copy-${kind}`,kind,polygon:[[x,y],[x+3,y],[x+3,y+3],[x,y+3]],materials:{interior:{id:'black_metal',color:'#abcdef',uv:{u:.3,v:.4,rot:90}}},...(kind==='spa'?{mode:'raised',raise_in:12,depth_in:36,bench_in:18,bench_width_in:18,spillover:false}:kind==='ledge'?{depth_in:8}:{treads:3,entry_edge:0})};
  pool.features=[p];r.raw.site.pool.features=[structuredClone(p)];const refs=[ref(kind,p.id)];r.c.copy(refs);assert.equal((await r.c.paste({mode:3})).ok,true,r.status());assert.deepEqual(r.posts[0].ops[0].materials,p.materials);assert.equal(r.c.canPaste({kind:'ground'}).ok,false);packet(r,kind);}
});
await test('light_and_effect_keep_bindings_and_settings',async()=>{
 for(const effect of [false,true]) {const r=rig(),kind=effect?'effect_fixture':'light_fixture',id=(effect?'effect:':'fixture:')+'00000000-0000-4000-8000-000000000001';
 const p=effect?{id,type:'fire',shape:'point',ref:'ground',at:[20,20,1],size_min:.5,size_max:2,strength:1,entity:'switch.fire'}:{id,shape:'spot',ref:'ground',at:[20,20,2],aim:[22,20,0],cone_deg:40,softness:.3,share:2};
 if(effect){r.plan.effect_fixtures=[p];r.raw.effect_fixtures=[structuredClone(p)];}else{r.plan.light_fixtures={'light.yard':[p]};r.raw.light_fixtures=structuredClone(r.plan.light_fixtures);}
 const refs=[ref(kind,id)];r.c.copy(refs);assert.equal((await r.c.paste({mode:3})).ok,true,r.status());const op=r.posts[0].ops[0];assert.equal(effect?op.fixture.entity:op.entity_id,effect?'switch.fire':'light.yard');assert.notEqual(op.fixture.id,id);packet(r,kind);}
});
await test('cut_identity_hide_lock_binding_first_paste_only_and_undo_clipboard_unchanged',async()=>{
 const r=rig(),pb=r.plan.buildings[0],rb=r.raw.buildings[0],wall=pb.walls.find(w=>w.state!=='ghost'&&w.kind!=='separator');
 const p={id:'cut-device-anchor',kind:'sensor',host:{wall:wall.id,at:2,z:3,side:'left'},offset:.1,device:'clipboard_device',state:'settled',mirror_x:true};
 pb.anchors.push(p);rb.anchors.push(structuredClone(p));const refs=[ref('anchor',p.id,bid)];
 r.visibility.hide(p.id);r.visibility.lock(p.id);r.selection.set(refs);
 assert.equal(r.c.copy(refs).ok,true);assert.match(r.status(),/without the device binding/);assert.equal((await r.c.paste({mode:3})).ok,true,r.status());assert.equal(r.posts.at(-1).ops[0].device,undefined);packet(r,'copy device loses binding');r.posts.length=0;
 assert.equal((await r.c.cut(refs)).ok,true);assert.equal(r.posts.length,1);assert.equal(r.posts[0].ops.length,1);const frozen=r.c.contents();
 // Model refresh after the delete; Undo puts this record back. Neither read
 // touches the session clipboard.
 pb.anchors=[];rb.anchors=[];pb.anchors.push(structuredClone(p));assert.deepEqual(r.c.contents(),frozen);
 assert.equal(r.posts.length,1,'Undo did not send clipboard operations');pb.anchors=[];
 assert.equal((await r.c.paste({mode:3})).ok,true,r.status());const restored=r.posts[1].ops[0];assert.equal(restored.id,p.id);assert.equal(restored.device,p.device);assert.ok(r.visibility.isHidden(p.id));assert.ok(r.visibility.isLocked(p.id));
 assert.equal((await r.c.paste({mode:3})).ok,true,r.status());assert.notEqual(r.posts[2].ops[0].id,p.id);assert.equal(r.posts[2].ops[0].device,undefined);
 // HTTP replay starts with the original anchor, then delete + first and later paste.
 rb.anchors=[structuredClone(p)];packet(r,'cut device preserves identity',{undoCut:true});
});
await test('copy_paste_material_single_slot_and_same_kind_slots_in_mixed_set',async()=>{
 const r=rig(),pb=r.plan.buildings[0],rb=r.raw.buildings[0],windows=pb.openings.filter(o=>o.kind==='window').slice(0,2);
 const look={id:'black_metal',color:'#123456',uv:{u:.2,v:.6,rot:270}};
 for(const pb of [r.plan.buildings[0],r.raw.buildings[0]])pb.openings.find(o=>o.id===windows[0].id).materials={window_frame:structuredClone(look)};
 const surface={kind:'opening',pieceId:windows[0].id,buildingId:bid,slot:'window_frame'};
 assert.equal(r.c.copyMaterial(surface).ok,true);assert.equal((await r.c.pasteMaterial({...surface,pieceId:windows[1].id})).ok,true,r.status());assert.equal(r.posts[0].ops.length,1);assert.deepEqual(r.posts[0].ops[0].material,look);
 r.selection.set([...windows.map(o=>ref('opening',o.id,bid)),tree]);assert.equal((await r.c.pasteMaterial(surface)).ok,true,r.status());assert.equal(r.posts[1].ops.length,2);assert.ok(r.posts[1].ops.every(o=>JSON.stringify(o.material)===JSON.stringify(look)));packet(r,'material slots');
 const wall={kind:'wall',pieceId:pb.walls[0].id,buildingId:bid,slot:'left'};assert.equal(r.c.copyMaterial(wall).ok,true,'structure look copies');
});
await test('duplicate_one_batch_and_keyboard_text_dialog_guards',async()=>{
 const r=rig();r.selection.set([tree]);assert.equal((await r.c.duplicate()).ok,true);assert.equal(r.posts.length,1);
 for(const tag of ['input','textarea','select']) {const node=document.createElement(tag);for(const key of ['c','x','v','d']){let prevented=false;const count=r.posts.length;assert.equal(clipboardKey({key,ctrlKey:true,target:node,preventDefault(){prevented=true;}},r.c),false);assert.equal(prevented,key==='d');assert.equal(r.posts.length,count);}}
 const node=document.createElement('div');node.isContentEditable=true;assert.equal(clipboardKey({key:'v',metaKey:true,target:node},r.c),false);
 let prevented=false;const event={key:'d',ctrlKey:true,target:document.body,preventDefault(){prevented=true;}};
 assert.equal(clipboardKey(event,r.c,{dialogOpen:true}),false);assert.equal(prevented,true);prevented=false;
 r.selection.set([tree]);await clipboardKey(event,r.c);assert.ok(prevented);assert.equal(r.posts.length,2);assert.equal(r.posts[1].op,'batch');packet(r,'duplicate');
});
await test('hosted_props_and_opening_kinds_preserve_settings',async()=>{
 for(const kind of ['item','anchor']) {const r=rig(),pb=r.plan.buildings[0],rb=r.raw.buildings[0],room=pb.rooms.find(p=>p.state!=='ghost');
  const p=kind==='item'?{id:'copy-prop',asset:'chair',host:{floor:room.id,u:.5,v:.5},rotation:41,scale:1.3,scale_axes:[1,2,1],tint:'#aabbcc',casts_shadow:false,object_kind:'decor'}
   :{id:'copy-anchor',kind:'outlet',host:{floor:room.id,u:.5,v:.5},offset:.3,device:null,mirror_x:true};
  const list=kind==='item'?'items':'anchors';pb[list].push(p);rb[list].push(structuredClone(p));const refs=[ref(kind,p.id,bid)];r.c.copy(refs);
  assert.equal((await r.c.paste({mode:3})).ok,true,r.status());const op=r.posts[0].ops[0];for(const k of ['asset','rotation','scale','scale_axes','tint','casts_shadow','mirror_x','offset'])if(k in p)assert.deepEqual(op[k],p[k]);packet(r,kind);
  if(kind==='item') {const frame=pb.rotation||0;pb.rotation=rb.rotation=0;assert.equal((await r.c.paste({mode:1,target:{kind:'ground'},point:[40,40]})).ok,true,r.status());assert.ok(Math.abs(r.posts.at(-1).ops[0].rotation-((p.rotation+frame)%360+360)%360)<1e-8,'copy keeps its captured world orientation after the original building turns');}
 }
 for(const kind of ['window','door','garage','slider','bifold']) {const r=rig(),pb=r.plan.buildings[0],rb=r.raw.buildings[0],original=pb.openings.find(o=>o.id===windowRef.pieceId);
  const p={...original,kind,width:3,sill:0,head:7,panels:2,model:input.models[kind==='window'?'window':'door'],hinge:'left',swing:'out',...(kind==='garage'?{style:'carriage',lites:'top'}:{}),...(kind==='door'?{glass:'half'}:{}),materials:{window_frame:{id:'black_metal',color:'#aabbcc',uv:{u:.3,v:.7,rot:90}}}};
  pb.openings=pb.openings.map(o=>o.id===p.id?p:o);rb.openings=rb.openings.map(o=>o.id===p.id?structuredClone(p):o);r.c.copy([windowRef]);
  assert.equal((await r.c.paste({mode:3})).ok,true,r.status());const op=r.posts[0].ops[0];for(const k of ['kind','width','sill','head','panels','model','hinge','swing','materials'])assert.deepEqual(op[k],p[k]);packet(r,kind);
 }
});
await test('no_free_wall_spot_and_server_refusal_report_without_clipboard_changes',async()=>{
 const r=rig(),pb=r.plan.buildings[0],p=pb.openings.find(o=>o.id===windowRef.pieceId),wall=pb.walls.find(w=>w.id===p.wall),length=Math.hypot(...wall.to.map((v,i)=>v-wall.from[i]));
 p.at=length/2;p.width=length;Object.assign(r.raw.buildings[0].openings.find(o=>o.id===p.id),p);r.c.copy([windowRef]);
 assert.equal((await r.c.paste({mode:3})).ok,false);assert.match(r.status(),/No free spot/);assert.equal(r.posts.length,0);
 let status='',calls=0;const s=createSelection(),c=createClipboard({getPlan:()=>input.plan,selection:s,setStatus:s=>status=s,applyBatch:async()=>{calls++;throw new Error('Batch member 1: no longer fits');}});
 c.copy([tree]);const held=c.contents();assert.equal((await c.paste({mode:3})).ok,false);assert.match(status,/member 1.*no longer fits/);assert.deepEqual(c.contents(),held);assert.equal(calls,1);
 assert.equal((await c.cut([tree])).ok,false);assert.deepEqual(c.contents(),held);assert.equal(calls,2);
});
await test('bare_and_yard_device_copies_are_visible_unbound_anchors_and_cut_keeps_identity',async()=>{
 for(const yard of [false,true]) {
  const r=rig(),pb=r.plan.buildings[0],rb=r.raw.buildings[0],wall=pb.walls.find(w=>w.state!=='ghost'&&w.kind!=='separator');
  const room={id:'clipboard-yard-room',name:'Yard device room',polygon:[[10,10],[30,10],[30,30],[10,30]]};
  if(yard){r.plan.site.yard_rooms=[room];r.raw.site.yard_rooms=[structuredClone(room)];}
  const p={id:'device:clipboard_device',device:'clipboard_device',host:yard?{yard_room:room.id,u:.5,v:.5}:{wall:wall.id,at:3,z:3,side:'left'},offset:.2,facing_deg:32};
  const owner=yard?r.plan.site:pb,raw=yard?r.raw.site:rb;owner.devices=[p];raw.devices=[structuredClone(p)];const refs=[ref('device',p.id,yard?null:bid)];
  assert.equal(r.c.copy(refs).ok,true,r.status());assert.equal((await r.c.paste({mode:3})).ok,true,r.status());assert.equal(r.posts[0].ops[0].op,'add_anchor');assert.equal(r.posts[0].ops[0].device,undefined);packet(r,yard?'yard device unbound copy':'bare device unbound copy');
  r.posts.length=0;assert.equal((await r.c.cut(refs)).ok,true,r.status());owner.devices=[];raw.devices=[];
  assert.equal((await r.c.paste({mode:3})).ok,true,r.status());assert.equal(r.posts[1].ops[0].op,'place_device');assert.equal(r.posts[1].ops[0].device,p.device);assert.equal(r.selection.primary().pieceId,p.id);
  raw.devices=[structuredClone(p)];packet(r,yard?'yard device cut first paste':'bare device cut first paste',{undoCut:true});
 }
});
await test('mode3_uses_captured_footprint_after_floor_switch_and_lan_uuid_fallback',async()=>{
 const r=rig(),p={id:'copy-box',asset:'chair',at:[20,20]};r.plan.site.furniture=[p];r.raw.site.furniture=[structuredClone(p)];
 let boxes=[{kind:'furniture',pieceId:p.id,box:{min:{x:19*.3048,z:-21*.3048},max:{x:21*.3048,z:-19*.3048}}}],ops=[];
 const c=createClipboard({getPlan:()=>r.plan,getModel:()=>r.raw,view:{selectionWorldBounds:()=>boxes},applyBatch:async batch=>ops.push(batch)});
 c.copy([ref('furniture',p.id)]);boxes=[];assert.equal((await c.paste({mode:3})).ok,true);assert.deepEqual(ops[0][0].at,[20.5,19.5],'large footprints still move exactly one step');
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto'),crypto=globalThis.crypto;
 try {Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:crypto.getRandomValues.bind(crypto)}});assert.equal((await c.paste({mode:3})).ok,true);assert.match(ops[1][0].id,/^furniture:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);}
 finally{Object.defineProperty(globalThis,'crypto',descriptor);}
 boxes=[{kind:'furniture',pieceId:p.id,box:{min:{x:9*.3048,z:-21*.3048},max:{x:11*.3048,z:-19*.3048}}}];
 c.copy([ref('furniture',p.id)]);assert.equal((await c.paste({mode:1,target:{kind:'ground'},point:[40,40]})).ok,true);assert.deepEqual(ops[2][0].at,[40,40],'a stale rendered box must not move the paste point');
});
await test('fixture_surface_modes_glass_refusal_and_mixed_set_height',async()=>{
 const r=rig(),pb=r.plan.buildings[0],wall=pb.walls.find(w=>w.state!=='ghost'&&w.kind!=='separator');
 const p={id:'fixture:00000000-0000-4000-8000-000000000099',shape:'point',ref:'ground',at:[20,20,2],share:2};
 r.plan.light_fixtures={'light.yard':[p]};r.raw.light_fixtures=structuredClone(r.plan.light_fixtures);
 const light=ref('light_fixture',p.id),target={kind:'wall',id:wall.id,building:bid},point=[...wall.from.map((v,i)=>(v+wall.to[i])/2),4];
 r.c.copy([light]);assert.equal((await r.c.paste({mode:1,target,point})).ok,true,r.status());assert.equal(r.posts[0].ops[0].fixture.ref,'floor');assert.ok(Math.abs(r.posts[0].ops[0].fixture.at[2]-4)<1e-8);
 r.selection.set([ref('wall',wall.id,bid)]);assert.equal((await r.c.paste()).ok,true,r.status());assert.equal(r.posts[1].ops[0].fixture.level,wall.level);
 const room=pb.rooms.find(room=>room.state!=='ghost');const n=r.posts.length;
 assert.equal((await r.c.paste({mode:1,target:{kind:'room',id:room.id,building:bid,slot:'pane'},point:[0,0,0]})).ok,false);assert.match(r.status(),/glass/);assert.equal(r.posts.length,n);
 const roof=pb.roof.sections.find(s=>s.rect);assert.equal((await r.c.paste({mode:2,target:{kind:'roof',id:roof.id,building:bid}})).ok,true,r.status());assert.ok(r.posts.at(-1).ops[0].fixture.at[2]>5);
 const prop={id:'mixed-prop',asset:'chair',at:[20,20],object_kind:'decor'};r.plan.site.furniture=[prop];r.raw.site.furniture=[structuredClone(prop)];
 r.c.copy([light,ref('furniture',prop.id)]);assert.equal((await r.c.paste({mode:1,target:{kind:'ground'},point:[40,40]})).ok,true,r.status());assert.equal(r.posts.at(-1).ops.length,2);assert.equal(r.posts.at(-1).ops[0].fixture.at[2],2);
 packet(r,'fixture surface modes and mixed height');
});
console.log('CASES '+JSON.stringify(cases));finish();
"""

INTEGRATION = r"""
await test('mounted_clipboard_toolbar_keyboard_and_context_entrypoints',async()=>{
 const ed=await mountEditor(makeHousehold());
 try {
  const plants=ed.plan.site.planting.slice(0,2),refs=plants.map(p=>({kind:'planting',pieceId:p.id}));ed.tools.selectionStore.set(refs);
  assert.equal(document.getElementById('rail-copy').disabled,false);await click(document.getElementById('rail-copy'));assert.equal(ed.tools.clipboard.contents().entries.length,2);
  assert.equal(document.getElementById('rail-paste').disabled,false);await click(document.getElementById('rail-paste'));await new Promise(r=>setTimeout(r,0));
  assert.equal(ed.ops.length,1);assert.equal(ed.ops[0].operation.op,'batch');assert.equal(ed.ops[0].operation.ops.length,2);
  const field=document.createElement('input');document.body.append(field);const before=ed.ops.length;
  for(const key of ['c','x','v','d'])await fire(document,'keydown',{key,ctrlKey:true,target:field});assert.equal(ed.ops.length,before);
  ed.tools.selectionStore.set(refs);await fire(document,'keydown',{key:'d',metaKey:true});await new Promise(r=>setTimeout(r,0));assert.equal(ed.ops.length,before+1,document.getElementById('editor-status').textContent);assert.equal(ed.ops.at(-1).operation.ops.length,2);
  ed.tools.openContextMenu({clientX:20,clientY:30},{kind:'planting',id:plants[0].id});const menu=document.getElementById('editor-context-menu');
  assert.ok(['Copy','Cut','Paste','Duplicate'].every(label=>[...menu.querySelectorAll('button')].some(b=>b.textContent===label)));
 }finally{ed.dispose();}
});
await test('mounted_slot_row_material_menu_uses_one_batch_for_set',async()=>{
 const ed=await mountEditor(makeHousehold());
 try {
  const b=ed.plan.buildings[0],windows=b.openings.filter(o=>o.kind==='window').slice(0,2),refs=windows.map(o=>({kind:'opening',pieceId:o.id,buildingId:b.id}));
  windows[0].materials={window_frame:{id:'black_metal',color:'#123456',uv:{u:.2,v:.4,rot:90}}};
  ed.tools.selectionStore.set([refs[0]]);let row=ed.dom.pieceCard.querySelector('[data-library-slot="Frame"]');assert.ok(row);
  await fire(row,'contextmenu',{clientX:20,clientY:30});let menu=document.getElementById('editor-context-menu');
  await click([...menu.querySelectorAll('button')].find(b=>b.textContent==='Copy material'));
  ed.tools.selectionStore.set(refs);row=ed.dom.pieceCard.querySelector('[data-library-slot="Frame"]');assert.ok(row);
  await fire(row,'contextmenu',{clientX:20,clientY:30});menu=document.getElementById('editor-context-menu');await click([...menu.querySelectorAll('button')].find(b=>b.textContent==='Paste material'));
  await new Promise(r=>setTimeout(r,0));assert.equal(ed.ops.length,1);assert.equal(ed.ops[0].operation.op,'batch');assert.equal(ed.ops[0].operation.ops.length,2);assert.ok(ed.ops[0].operation.ops.every(o=>o.material.uv.rot===90&&o.material.color==='#123456'));
 }finally{ed.dispose();}
});
finish();
"""


def main():
    os.environ.pop('HA_BASE_URL', None)
    with tempfile.TemporaryDirectory(prefix='chauffeur_clipboard_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_store, twin_library
        from services import twin_imports
        from test_twin_model_ops_more import _client, _people, _enforced
        logging.getLogger('httpx').setLevel(logging.WARNING)
        fixture = json.loads((ROOT/'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf8'))
        twin_store.push_round(fixture, 'build')
        models = {'window': 'import-' + '0' * 32, 'door': 'import-' + '1' * 32}
        # Isolated Library metadata fixtures exercise the real typed-model
        # validator and lookup, without using anybody's household asset files.
        for kind, asset_id in models.items():
            folder = twin_imports.root() / asset_id
            folder.mkdir(parents=True)
            (folder/'test.gltf').write_text(json.dumps({'asset': {'version': '2.0'}, 'scenes': [{}], 'scene': 0}), encoding='utf8')
            (folder/twin_imports.META).write_text(json.dumps({'id': asset_id, 'kind': kind,
                'name': 'Clipboard test ' + kind, 'model': 'test.gltf', 'files': {'test.gltf': True}}), encoding='utf8')
        payload = {'root': ROOT.as_posix(), 'plan': twin_store.current(), 'model': twin_store.current_model(),
                   'kit': twin_library.kit('modern_farmhouse'),
                   'objectSchema': json.loads((ROOT/'static/twin/object_schema.json').read_text(encoding='utf8')), 'models': models}
        code, output = run_node(DRIVER.replace("console.log('CASES '", FIX_DRIVER + "console.log('CASES '"), payload, timeout=180)
        print('\n'.join(line for line in output.splitlines() if not line.startswith('CASES ')))
        assert code == 0, chr(10).join(line for line in output.splitlines() if not line.startswith('CASES '))
        cases = json.loads(next(line[6:] for line in output.splitlines() if line.startswith('CASES ')))
        passed = 0
        with _enforced():
            client, headers = _client(), _people()['parent']
            for case in cases:
                twin_store.update_model(lambda _: case['model'], kind='build')
                for batch in case['batches']:
                    for member in batch['ops']:
                        if member['op'] in ('add_site_shape', 'add_site_item', 'add_pad'):
                            assert member.get('require_inside') is True, 'every clipboard yard create opts in'
                    before, round_id, count = twin_store.current_model(), twin_store.current_id(), len(twin_store.rounds())
                    answer = client.post('/api/house/editor/op', headers=headers, json={'op': batch})
                    assert answer.status_code == 200, (case['name'], batch, answer.text,
                        [{k: o.get(k) for k in ('id', 'wall', 'at', 'width')} for b in before['buildings'] for o in b['openings'] if any(op.get('wall') == o.get('wall') for op in batch['ops'])])
                    after = twin_store.current_model()
                    assert len(twin_store.rounds()) == min(50, count + 1), 'one action, one round'
                    def find(node, pid):
                        if isinstance(node, dict):
                            if node.get('id') == pid:
                                return node
                            return next((found for v in node.values() if (found := find(v, pid)) is not None), None)
                        if isinstance(node, list):
                            return next((found for v in node if (found := find(v, pid)) is not None), None)
                        return None
                    for op in batch['ops']:
                        if op['op'].startswith('add_'):
                            pid = op.get('id') or op.get('fixture', {}).get('id')
                            saved = find(after, pid)
                            assert pid and saved is not None, (case['name'], 'explicit id lost', pid)
                            recipe = op.get('fixture') or op
                            for field in ('asset', 'model', 'width', 'head', 'sill', 'panels', 'glass', 'hinge', 'swing', 'style', 'lites',
                                          'scale', 'scale_axes', 'rotation', 'tint', 'height', 'seed', 'casts_shadow', 'visible_in', 'elevation', 'facing_deg',
                                          'materials', 'pavers', 'edges', 'power', 'car', 'entity', 'sensor', 'strength'):
                                if field in recipe:
                                    assert saved.get(field) == recipe[field], (case['name'], field, saved.get(field), recipe[field])
                            if op.get('device'):
                                assert saved.get('device') == op['device'], 'cut binding lost on the restored anchor'
                            elif op['op'] == 'add_anchor':
                                assert not saved.get('device'), 'copied anchor must be unbound'
                        if op.get('device') and op['op'] != 'unplace_device':
                            assert op['device'] in json.dumps(after), 'cut binding lost'
                    answer = client.post('/api/house/twin/revert', headers=headers, json={'round': round_id})
                    assert answer.status_code == 200 and twin_store.current_model() == before, 'Undo must restore the whole batch'
                    # Restore the successful result to replay cut -> paste -> later paste.
                    if case.get('undoCut'):
                        twin_store.update_model(lambda _: after, kind='build')
                    passed += 1
                print('  ok HTTP', case['name'])
            # Explicit identities must refuse duplicates, including two creates
            # within one batch, and never publish a half-paste.
            reference_model = twin_store.current_model()
            reference_model['site']['beds'][0]['materials'] = {'fill': {'id': 'black_metal'}}
            twin_store.update_model(lambda _: reference_model)
            before, count = twin_store.current_model(), len(twin_store.rounds())
            plant = payload['plan']['site']['planting'][0]
            op = {'op': 'add_site_item', 'list': 'planting', 'id': 'black_metal', 'asset': plant['preset'], 'at': [20, 20]}
            answer = client.post('/api/house/editor/op', headers=headers, json={'op': {'op': 'batch', 'ops': [op, op]}})
            assert answer.status_code == 400 and answer.json()['member'] == 1, answer.text
            assert twin_store.current_model() == before and len(twin_store.rounds()) == count
            server_checks(client, headers, payload['model'])
            print(f'PASS {passed} HTTP create/material/cut batches, one undo each; duplicate-id refusal atomic')
        from test_twin_selection_js import DRIVER as SCENE_DRIVER
        scene = SCENE_DRIVER.rsplit('finish();', 1)[0].replace('await test(', 'await skipPriorScenario(')
        scene = scene.replace('let library = null, terrain = null, devices = null;',
            "let library = null, terrain = null, devices = null; const slotLibrary={selected:()=>library?.selected()||null,onSelect:fn=>library?.onSelect(fn)||(()=>{}),reveal:(...args)=>library?.reveal(...args)};")
        scene = scene.replace('siteHits: (x, y) =>', 'library: slotLibrary, surfaceAt: (event,target)=>library?.contextSurfaceAt(event,target), groundPoint:event=>library?.ground(event), siteHits: (x, y) =>')
        scene = scene.replace('terrain = createTerrainTools(', 'library.materialMenu=(...args)=>slotLibrary.materialMenu?.(...args); terrain = createTerrainTools(')
        code, output = run_node('const skipPriorScenario=async()=>{};\n' + scene + INTEGRATION.replace('finish();', FIX_INTEGRATION + 'finish();'),
                                {**payload, 'flat': payload['plan']}, timeout=180)
        print(output)
        assert code == 0, output


if __name__ == '__main__':
    main()
