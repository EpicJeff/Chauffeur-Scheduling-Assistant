"""Loose-texture suffixes and actual Library drop/input event paths (no browser)."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {slotForFilename}=await import(file('static/twin/library_page/texture_slots.js'));
const THREE=await import('three'), loaded=[];
THREE.TextureLoader.prototype.load=function(url,done){loaded.push(url);const t=new THREE.Texture({width:32,height:32});queueMicrotask(()=>done(t));return t;};
const {mountLibraryPage}=await import(file('static/twin/library_page/page.js'));
const pause=ms=>new Promise(r=>setTimeout(r,ms)), clone=x=>structuredClone(x);
const image=name=>new File(['raw bytes of '+name],name,{type:'image/png'});
const deferred=()=>{let resolve;return {promise:new Promise(r=>{resolve=r;}),resolve};};
const until=async fn=>{for(let i=0;i<100&&!fn();i++)await pause(2);assert.ok(fn(),'timed out waiting for event path');};
const originalCreate=URL.createObjectURL,originalRevoke=URL.revokeObjectURL;
let created=[],revoked=[];
URL.createObjectURL=blob=>{const url=originalCreate(blob);created.push(url);return url;};
URL.revokeObjectURL=url=>{revoked.push(url);originalRevoke(url);};
const record=(id='material-test',source='user')=>({id,name:id,source,revision:1,maps:{},params:{tint:'#ffffff',roughness:null,metalness:null,normal_scale:1,normal_convention:'gl',ao_intensity:1,tile_ft:[4,4],rotation_deg:0,random_offset:false}});
async function setup(hooks={},first=record()){
 created=[];revoked=[];loaded.length=0;
 const host=document.createElement('main');document.body.append(host);
 const records=new Map([[first.id,clone(first)],['material-other',record('material-other')]]),calls=[],alerts=[],prompts=[],progress=[];
 window.showGlobalAlert=text=>alerts.push(text);window.promptConfirm=async()=>true;
 window.promptInput=async(...args)=>{prompts.push(args);return hooks.prompt?hooks.prompt(...args):null;};
 for(const name of ['alert','confirm','prompt'])window[name]=()=>{throw Error('browser dialog');};
 const api=async(path,method='GET',body)=>{
  calls.push({path,method,body:body instanceof Blob?body:clone(body)});
  if(path==='materials'){
   if(method==='GET')return {materials:[...records.values()]};
   const made=record('material-new');records.set(made.id,made);return clone(made);
  }
  const [,id,,slot]=path.split('/');let saved=records.get(id);
  if(method==='POST'&&slot){
   progress.push(host.querySelector('[role="status"]').textContent);
   await hooks.upload?.(slot,body);
   saved.maps[slot]='maps/'+slot+'-server.png';saved.revision++;
  }
  if(method==='PATCH'){
   await hooks.patch?.(body);
   saved={...saved,...body,maps:{...saved.maps,...body.maps},params:{...saved.params,...body.params},revision:saved.revision+1};records.set(id,saved);
  }
  return clone(saved);
 };
 location.search='?material='+first.id;
 const page=mountLibraryPage(host,{api});await page.ready;tick();
 const panel=host.querySelector('.library-properties');
 const drop=(files,target=panel)=>fire(target,'drop',{dataTransfer:{files,types:['Files']}});
 return {host,panel,page,calls,alerts,prompts,progress,records,drop,stop(){page.stop();host.remove();}};
}
await test('suffix_table',async()=>{
 const groups=[
  ['base_color',undefined,['basecolor','albedo','diff','diffuse','color','col']],
  ['normal','gl',['normalgl','nor_gl','normal']],['normal','dx',['normaldx','nor_dx']],
  ['roughness',undefined,['rough','roughness']],['metalness',undefined,['metal','metalness','metallic']],
  ['ao',undefined,['ao','occlusion','ambientocclusion']],['orm',undefined,['arm','orm']],
  ['height',undefined,['height','disp','displacement']]];
 for(const [slot,convention,names] of groups)for(const suffix of names){
  const expected=convention?{slot,convention}:{slot};
  for(const name of [`brick_${suffix}.png`,`brick-${suffix.toUpperCase()}.WEBP`,`x_${suffix}_2k.jpg`])assert.deepEqual(slotForFilename(name),expected,name);
 }
 for(const [suffix,slot,convention] of [['Color','base_color'],['NormalGL','normal','gl'],['NormalDX','normal','dx'],['Roughness','roughness'],['Metalness','metalness'],['AmbientOcclusion','ao']])
  assert.deepEqual(slotForFilename(`X_2K-JPG_${suffix}.jpg`),convention?{slot,convention}:{slot});
});
await test('suffix_boundaries_and_unknowns',async()=>{
 for(const name of ['brick.png','brick_discolor.png','rough_brick.png','x_normal_notes.png','x_ao_backup.jpg','x_colored.webp'])assert.equal(slotForFilename(name),null,name);
});
await test('drop_uploads_each_to_its_slot_and_previews_locally',async()=>{
 const gate=deferred();let uploads=0;
 const c=await setup({upload:async()=>{if(++uploads===1)await gate.promise;}});
 const files=[image('brick_diff_2k.jpg'),image('brick_rough.png'),image('brick_arm_2k.png')];
 const done=c.drop(files);await until(()=>uploads===1);
 assert.equal(created.length,1);assert.ok(loaded.includes(created[0]));assert.equal(revoked.length,0);
 assert.equal(c.host.querySelector('[data-slot="base_color"] img').src,created[0]);
 assert.equal(c.calls.filter(x=>x.method==='POST').length,1,'one upload at a time');
 gate.resolve();await done;
 const posts=c.calls.filter(x=>x.method==='POST');assert.deepEqual(posts.map(x=>x.path.split('/').at(-1)),['base_color','roughness','orm']);
 posts.forEach((post,i)=>assert.equal(post.body,files[i],'upload original raw File'));
 assert.deepEqual(c.progress,['Uploading 1 of 3: brick_diff_2k.jpg','Uploading 2 of 3: brick_rough.png','Uploading 3 of 3: brick_arm_2k.png']);
 assert.deepEqual(revoked,created);assert.ok(c.host.querySelector('[data-slot="base_color"] img').src.includes('base_color-server.png'));
 c.stop();assert.deepEqual(revoked,created);
});
await test('zone_bubbles_once_and_touch_input_uses_same_flow',async()=>{
 const c=await setup();const zone=c.host.querySelector('[data-texture-drop]');assert.ok(zone);assert.match(textOf(zone),/Drop textures/);
 await c.drop([image('x_ao.png')],zone);
 const input=c.host.querySelector('[data-texture-files]');assert.ok(input.multiple);assert.match(input.accept,/png|image/);
 input.files=[image('x_height.png'),image('x_metal.png')];await fire(input,'change');
 assert.deepEqual(c.calls.filter(x=>x.method==='POST').map(x=>x.path.split('/').at(-1)),['ao','height','metalness']);assert.equal(input.value,'');c.stop();
});
await test('unknown_file_asks_slot_via_promptInput',async()=>{
 const c=await setup({prompt:async()=> 'roughness'});await c.drop([image('brick.png')]);
 assert.equal(c.prompts.length,1);assert.match(c.prompts[0].join(' '),/brick.png/);
 for(const slot of ['base_color','normal','roughness','metalness','ao','orm','height'])assert.ok(c.prompts[0][1].includes(slot));
 assert.ok(c.calls.some(x=>x.path.endsWith('/maps/roughness')&&x.method==='POST'));c.stop();
});
await test('cancel_skips_only_that_file',async()=>{
 const c=await setup();await c.drop([image('unknown.png'),image('x_ao.png')]);
 assert.equal(c.prompts.length,1);assert.equal(c.calls.filter(x=>x.method==='POST').length,1);assert.equal(created.length,1);c.stop();
});
await test('invalid_slot_is_reprompted_not_sent_to_server',async()=>{
 let count=0;const c=await setup({prompt:async()=>++count===1?'bad/slot':'base_color'});await c.drop([image('unknown.png')]);
 assert.equal(count,2);assert.ok(c.calls.some(x=>x.path.endsWith('/maps/base_color')));assert.ok(!c.calls.some(x=>x.path.includes('bad/slot')));c.stop();
});
await test('normal_convention_and_slot_share_patch',async()=>{
 const first=record();first.params.normal_convention='dx';const c=await setup({},first);
 for(const [name,convention] of [['brick_normal.png','gl'],['brick_nor_dx_2k.png','dx'],['brick_NormalGL.webp','gl'],['brick_normaldx.png','dx']]){
  const before=c.calls.length;await c.drop([image(name)]);const writes=c.calls.slice(before).filter(x=>x.method!=='GET');
  assert.deepEqual(writes.map(x=>x.method),['POST','PATCH']);
  assert.deepEqual(writes[1].body,{maps:{normal:'maps/normal-server.png'},params:{normal_convention:convention}});
  assert.equal(c.records.get('material-test').params.normal_convention,convention);
  assert.equal(c.host.querySelector('[data-field="normal_convention"]').value,convention);
 }c.stop();
});
await test('refusals_restore_previous_map_and_continue',async()=>{
 const first=record();first.maps.base_color='maps/old.png';
 const c=await setup({upload:async slot=>{if(slot==='base_color')throw Error('Truncated image; choose a complete image.');if(slot==='roughness')throw Error('Each image must be at most 40 MB.');}},first);
 await c.drop([image('x_color.png'),image('x_rough.png'),image('x_metal.png')]);
 assert.deepEqual(c.alerts,['Truncated image; choose a complete image.','Each image must be at most 40 MB.']);
 assert.equal(c.calls.filter(x=>x.method==='POST').length,3);assert.ok(c.host.querySelector('[data-slot="base_color"] img').src.endsWith('/maps/old.png'));
 assert.deepEqual(revoked,created);assert.equal(c.host.querySelector('[data-texture-files]').disabled,false);c.stop();
});
await test('batch_keeps_original_material_when_selection_changes',async()=>{
 const gate=deferred();let n=0;const c=await setup({upload:async()=>{if(++n===1)await gate.promise;}});
 const done=c.drop([image('x_diff.png'),image('x_rough.png')]);await until(()=>n===1);
 const selecting=click(c.host.querySelector('[data-material="material-other"]'));gate.resolve();await selecting;await done;
 assert.ok(c.calls.filter(x=>x.method==='POST').every(x=>x.path.startsWith('materials/material-test/')));
 assert.deepEqual(c.records.get('material-other').maps,{});assert.equal(c.host.querySelector('[data-field="name"]').value,'material-other');c.stop();
});
await test('stop_revokes_active_url_once_and_stops_remaining_files',async()=>{
 const gate=deferred();let n=0;const c=await setup({upload:async()=>{n++;await gate.promise;}});
 const done=c.drop([image('x_diff.png'),image('x_rough.png')]);await until(()=>n===1);c.stop();assert.deepEqual(revoked,created);
 gate.resolve();await done;assert.equal(n,1);assert.deepEqual(revoked,created);
});
await test('builtin_cannot_receive_drops_and_stop_removes_handlers',async()=>{
 const c=await setup({},record('brick','builtin'));assert.equal(c.host.querySelector('[data-texture-files]'),null);
 await c.drop([image('x_diff.png')]);assert.equal(c.calls.filter(x=>x.method!=='GET').length,0);assert.equal(created.length,0);
 c.stop();await c.drop([image('x_diff.png')]);assert.equal(created.length,0);
});
await test('new_material_then_drop_and_pending_parameters_survive',async()=>{
 const c=await setup();await click(c.host.querySelector('[data-action="new"]'));
 const tint=c.host.querySelector('[data-param="tint"]');tint.value='#123456';await fire(tint,'input');
 await c.drop([image('x_nor_dx_2k.png')]);
 const writes=c.calls.filter(x=>x.method!=='GET');assert.equal(writes[1].method,'PATCH');assert.equal(writes[1].body.params.tint,'#123456');
 assert.ok(writes.filter(x=>x.path.includes('/maps/')).every(x=>x.path.startsWith('materials/material-new/')));
 assert.equal(c.records.get('material-new').params.tint,'#123456');c.stop();
});
await test('dragover_prevents_file_navigation_and_duplicate_drop_while_busy',async()=>{
 const gate=deferred();let n=0;const c=await setup({upload:async()=>{n++;await gate.promise;}});
 const event=await fire(c.panel,'dragover',{dataTransfer:{types:['Files']}});assert.equal(event.defaultPrevented,true);
 const done=c.drop([image('x_ao.png')]);await until(()=>n===1);await c.drop([image('x_rough.png')]);assert.equal(n,1);
 gate.resolve();await done;c.stop();
});
await test('progress_stays_visible_when_pending_parameter_save_finishes',async()=>{
 const gate=deferred();let n=0;const c=await setup({upload:async()=>{n++;await gate.promise;}});
 const tint=c.host.querySelector('[data-param="tint"]');tint.value='#345678';await fire(tint,'input');
 const done=c.drop([image('brick_rough.png')]);await until(()=>n===1);
 assert.equal(c.host.querySelector('[role="status"]').textContent,'Uploading 1 of 1: brick_rough.png');
 gate.resolve();await done;c.stop();
});
await test('only_one_upload_across_material_selections',async()=>{
 const first=deferred(),second=deferred();let n=0;const c=await setup({upload:async()=>{if(++n===1)await first.promise;else await second.promise;}});
 const done=c.drop([image('x_ao.png'),image('x_rough.png')]);await until(()=>n===1);
 const selecting=click(c.host.querySelector('[data-material="material-other"]'));
 first.resolve();await selecting;await until(()=>n===2);
 assert.equal(c.host.querySelector('[data-texture-files]').disabled,true);
 await c.drop([image('x_color.png')]);assert.equal(n,2);
 second.resolve();await done;
 assert.equal(c.host.querySelector('[data-texture-files]').disabled,false);c.stop();
});
await test('normal_patch_refusal_shows_reason_retains_ingested_map_and_continues',async()=>{
 const c=await setup({patch:async body=>{if(body.params?.normal_convention)throw Error('The normal convention could not be saved.');}});
 await c.drop([image('x_normaldx.png'),image('x_color.png')]);
 assert.deepEqual(c.alerts,['The normal convention could not be saved.']);
 assert.equal(c.records.get('material-test').params.normal_convention,'gl');
 assert.ok(c.host.querySelector('[data-slot="normal"] img').src.endsWith('/maps/normal-server.png'));
 assert.equal(c.calls.filter(x=>x.method==='POST').length,2);assert.deepEqual(revoked,created);c.stop();
});
await test('stop_during_unmatched_prompt_does_not_upload',async()=>{
 const gate=deferred();const c=await setup({prompt:()=>gate.promise});
 const done=c.drop([image('unknown.png'),image('x_color.png')]);await until(()=>c.prompts.length===1);
 c.stop();gate.resolve('normal');await done;assert.equal(created.length,0);assert.equal(c.calls.filter(x=>x.method==='POST').length,0);
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)
