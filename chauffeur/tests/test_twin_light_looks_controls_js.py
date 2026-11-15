"""Exercise shared device controls and their real live preference transport."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {lightControls} = await import(file('static/twin/live/controls/light.js'));
const {fanControls} = await import(file('static/twin/live/controls/fan.js'));
const checks=[], check=(name,fn)=>checks.push([name,fn]);
const part=(node,name)=>node.querySelector(`[data-ring-part="${name}"]`);
async function setup({compact=false,offered=true,canEdit=true,domain='light',surface='ring',looks={}}={}) {
  const entity=domain+'.pool', attrs=domain==='light'?{effect_list:['Caribbean','Party','Deep Blue'],effect:'Caribbean',supported_color_modes:['rgb'],rgb_color:[255,0,0],brightness:255}:{};
  const t=await rig({devices:[{device_id:'pool',name:'Pool light',entity_id:entity,kind:domain==='input_boolean'?'switch':domain,state:'on',attributes:attrs,offered}],layoutExtra:{can_edit_house:canEdit}});
  t.live.stop();
  const puts=[],reads=[],store=structuredClone(looks), originalApi=t.api;
  let reject=false;
  t.live=await liveModule.mountLive(t.view,{api:async(path,init)=>{
    if(path==='api/house/twin/light-looks') {
      reads.push(init?.method||'GET');
      if(!init?.method)return {ok:true,json:async()=>structuredClone(store)};
      const body=JSON.parse(init.body);puts.push(body);
      if(reject)return {ok:false,status:422,json:async()=>({detail:'refused'})};
      if(body.look)store[body.entity_id]=body.look;else delete store[body.entity_id];
      return {ok:true,json:async()=>({look:body.look||{}})};
    }
    return originalApi(path,init);
  }});
  const row=t.layout.devices[0], state=t.states[entity];
  const options={row,state,control:t.live.control,compact,surface,lightLooks:t.live.lightLooks};
  const node=(domain==='fan'?fanControls:lightControls)(options);document.body.append(node);
  return {...t,node,puts,reads,entity,reject:()=>{reject=true;},cleanup:()=>{node.stop();node.remove();t.live.stop();t.host.remove();}};
}
check('effect_previews_render_assigned_named_and_unknown_dots',async()=>{
  const t=await setup();try {
    const dots=t.node.querySelectorAll('[data-ring-part="effect-look-edit"]');assert.equal(dots.length,3);
    assert.equal(dots[0].querySelector('.twin-look-dot').style.background,'transparent');assert.equal(dots[2].querySelector('.twin-look-dot').style.background,'rgb(0,0,255)');
    await t.live.lightLooks.save(t.entity,{effects:{caribbean:[[255,0,0],[0,0,255]]}});t.node.update(t.states[t.entity]);
    assert.ok(dots[0].querySelector('.twin-look-dot').style.background.includes('linear-gradient'));
    assert.equal(t.node.querySelector('.twin-light-progress').style.stroke,'rgb(188,0,188)');
    assert.ok(part(t.node,'effects-choice'));await press(part(t.node,'effects-choice'));
    assert.equal(t.calls.length,1,'effect chips still call the device');
    assert.equal(t.calls[0].data.effect,'Caribbean');
  }finally{t.cleanup();}
});
check('ordinary_wheel_retains_its_debounced_device_service',async()=>{
  const t=await setup();try {
    const wheel=part(t.node,'wheel');key(wheel,'Home');for(let i=0;i<20;i++)key(wheel,'ArrowRight');
    assert.equal(t.calls.length,0);await wait(300);
    assert.equal(t.calls.length,1);assert.equal(t.calls[0].service,'turn_on');
    assert.deepEqual(t.calls[0].data,{entity_id:t.entity,hs_color:[20,100]});assert.equal(t.puts.length,0);
  }finally{t.cleanup();}
});
check('mounted_ring_and_room_share_editor_and_repaint_after_save',async()=>{
  const t=await setup();try {
    const loadedRevision=t.live.looksRevision();assert.equal(loadedRevision,1);
    t.live.openRing(t.live.marker('pool'));
    const ring=document.querySelector('[data-ring]');
    await press(part(ring,'effect-look-edit'));await press(part(ring,'look-add'));
    const second=ring.querySelectorAll('[data-ring-part="look-wheel"]')[1];key(second,'Home');
    for(let i=0;i<240;i++)key(second,'ArrowRight');
    await press(part(ring,'look-done'));await wait(30);
    assert.deepEqual(t.puts,[{entity_id:t.entity,look:{effects:{caribbean:[[255,0,0],[0,0,255]]}}}]);
    assert.equal(t.live.looksRevision(),loadedRevision+1,'save bumps the same revision as load');
    assert.ok(part(ring,'effect-look-edit').querySelector('.twin-look-dot').style.background.includes('linear-gradient'));
    assert.equal(ring.querySelector('.twin-light-progress').style.stroke,'rgb(188,0,188)');
    Object.defineProperty(t.live.looks(),'toJSON',{value:()=>{throw new Error('room render must not stringify the looks map');}});
    t.live.openRoom('b','r');const panel=document.querySelector('#twin-room-panel');
    assert.ok(part(panel,'effect-look-edit').querySelector('.twin-look-dot').style.background.includes('linear-gradient'));
    await press(part(panel,'effect-look-edit'));assert.equal(panel.querySelectorAll('[data-ring-part="look-wheel"]').length,2);
    assert.equal(t.calls.length,0);assert.deepEqual(t.reads,['GET','PUT']);
  }finally{t.cleanup();}
});
check('compact_readonly_nonparent_and_kiosk_have_no_edit_affordance',async()=>{
  for(const opts of [{compact:true,surface:'panel'},{canEdit:false},{offered:false},{surface:'panel',offered:false}]) {
    const t=await setup(opts);try {
      assert.equal(part(t.node,'effect-look-edit'),null);assert.equal(part(t.node,'fixed-look-edit'),null);
      const readonly=opts.compact||opts.offered===false;
      assert.equal(t.node.querySelectorAll('[data-ring-part="effect-look-dot"]').length,readonly?0:3);
      if(readonly) assert.equal(part(t.node,'effects'),null);
      else for(const chip of t.node.querySelectorAll('[data-ring-part="effects-choice"]')) {
        assert.equal(part(chip,'effect-look-dot').getAttribute('aria-hidden'),'true');
        const name=chip.childNodes.filter(n=>n.getAttribute?.('aria-hidden')!=='true').map(n=>n.textContent).join('');
        assert.equal(name,chip.textContent,'decorative dot adds no accessible text');
      }
    }finally{t.cleanup();}
  }
  for(const query of ['?panel=true','?kiosk=true','?tabs=house']) {
    window.location.search=query;const t=await setup();try {
      assert.equal(part(t.node,'effect-look-edit'),null);assert.equal(t.live.lightLooks.canEdit,false);
    }finally{t.cleanup();window.location.search='';}
  }
});
check('compact_and_readonly_surfaces_only_show_assigned_noninteractive_previews',async()=>{
  for(const opts of [{compact:true,surface:'panel'},{offered:false,surface:'panel'},{offered:false,surface:'ring'}]) {
    const empty=await setup(opts);try {
      assert.equal(part(empty.node,'effects'),null);
      if(opts.surface==='panel') assert.equal(empty.node.childNodes.length,0,'main rendered an empty compact/read-only row');
    }finally{empty.cleanup();}
    const t=await setup({...opts,looks:{'light.pool':{effects:{caribbean:[[0,0,255]]}}}});try {
      const group=part(t.node,'effects');assert.ok(group);
      assert.equal(group.previousElementSibling.textContent,'Effects');
      assert.equal(group.children.length,1);assert.equal(group.querySelector('button'),null);
      const item=part(t.node,'effect-look-preview');assert.equal(item.localName,'span');assert.equal(item.textContent,'Caribbean');
      const dot=part(item,'effect-look-dot');assert.equal(dot.style.background,'rgb(0,0,255)');
      assert.equal(dot.getAttribute('aria-hidden'),'true');await press(item);assert.equal(t.calls.length,0);
    }finally{t.cleanup();}
  }
});
check('unchanged_effect_dot_paint_skips_style_writes',async()=>{
  const t=await setup({canEdit:false});try {
    const dot=part(t.node,'effect-look-dot'), initial=dot.style.background;let writes=0;
    Object.defineProperty(dot.style,'background',{get:()=>initial,set:()=>{writes++;},configurable:true});
    for(let i=0;i<10;i++)t.node.update(t.states[t.entity]);
    assert.equal(writes,0);
  }finally{t.cleanup();}
});
check('editor_stop_registrations_stay_constant_across_open_add_remove_cycles',async()=>{
  const push=Array.prototype.push;let registrations=0;
  Array.prototype.push=function(...items){
    if(items.length===1&&typeof items[0]==='function'&&new Error().stack.includes('onStop'))registrations++;
    return push.apply(this,items);
  };
  let t;
  try {
    t=await setup();const baseline=registrations;
    await press(part(t.node,'effect-look-edit'));const opened=registrations;
    for(let i=0;i<10;i++) {
      await press(part(t.node,'look-add'));await press(part(t.node,'look-remove'));
      assert.equal(registrations,opened,'render must not register more stop handlers');
    }
    await press(part(t.node,'look-cancel'));await press(part(t.node,'effect-look-edit'));
    assert.equal(registrations,baseline,'reopening reuses the control-level editor stop handler');
    assert.ok(baseline>0,'registration probe saw real handlers');
    const wheel=part(t.node,'look-wheel');key(wheel,'ArrowRight');t.node.stop();await wait(250);
    assert.equal(t.puts.length,0);assert.equal(t.calls.length,0);assert.equal(part(t.node,'look-editor'),null);
  }finally{Array.prototype.push=push;t?.cleanup();}
});
check('late_looks_do_not_hold_mount_and_refresh_existing_ring_and_room_controls',async()=>{
  for(const surface of ['ring','room']) {
    const t=await setup();let deliver;
    try {
      t.live.stop();const pending=new Promise(resolve=>{deliver=resolve;});
      const mounted=liveModule.mountLive(t.view,{api:(path,init)=>path==='api/house/twin/light-looks'?pending:t.api(path,init)});
      t.live=await Promise.race([mounted,wait(500).then(()=>{throw new Error('looks GET blocked mount');})]);
      assert.ok(t.live.marker('pool'));assert.equal(t.live.marker('pool').color,'#ff0000');
      assert.equal(t.live.lightLooks.canEdit,false);assert.equal(t.live.looksRevision(),0);
      if(surface==='ring')t.live.openRing(t.live.marker('pool'));else t.live.openRoom('b','r');
      const host=document.querySelector(surface==='ring'?'[data-ring]':'#twin-room-panel');
      assert.ok(part(host,'effects-choice'),'device controls exist before looks arrive');
      assert.equal(part(host,'effect-look-edit'),null);
      deliver({ok:true,json:async()=>({'light.pool':{effects:{caribbean:[[0,0,255]]}}})});await wait(30);
      assert.equal(t.live.marker('pool').color,'#0000ff');assert.equal(t.live.looksRevision(),1);
      assert.equal(t.live.lightLooks.canEdit,true);assert.ok(part(host,'effect-look-edit'));
      assert.equal(part(host,'effect-look-edit').querySelector('.twin-look-dot').style.background,'rgb(0,0,255)');
    }finally{deliver?.({ok:false});t.live.stop();t.cleanup();}
  }
});
check('failed_initial_looks_read_keeps_mount_and_controls_without_editing_or_feedback',async()=>{
  const t=await setup();try {
    t.live.stop();let reads=0;
    t.live=await liveModule.mountLive(t.view,{api:(path,init)=>{
      if(path==='api/house/twin/light-looks'){reads++;return Promise.reject(new Error('offline'));}
      return t.api(path,init);
    }});
    assert.ok(t.live.marker('pool'));assert.equal(t.live.lightLooks.canEdit,false);assert.equal(t.live.looksRevision(),0);
    t.live.openRing(t.live.marker('pool'));const ring=document.querySelector('[data-ring]');
    assert.ok(part(ring,'effects-choice'));assert.equal(part(ring,'effect-look-edit'),null);
    assert.deepEqual(t.live.looks(),{});assert.deepEqual(t.alerts,[]);
    await t.live.refresh();assert.equal(reads,1,'no retry or polling for looks');
  }finally{t.live.stop();t.cleanup();}
});
check('save_palette_is_one_put_with_no_device_call_keyboard_wheel_and_stop_limits',async()=>{
  const t=await setup();try {
    await press(part(t.node,'effect-look-edit'));assert.ok(part(t.node,'look-editor'));
    const wheel=part(t.node,'look-wheel');assert.equal(wheel.getAttribute('role'),'slider');
    key(wheel,'Home');await wait(250);await press(part(t.node,'look-add'));
    const second=t.node.querySelectorAll('[data-ring-part="look-wheel"]')[1];key(second,'Home');
    for(let i=0;i<240;i++)key(second,'ArrowRight');
    await press(part(t.node,'look-done'));await wait(50);
    assert.deepEqual(t.puts,[{entity_id:t.entity,look:{effects:{caribbean:[[255,0,0],[0,0,255]]}}}]);
    assert.equal(t.calls.length,0);assert.equal(part(t.node,'look-editor'),null);
    await press(part(t.node,'effect-look-edit'));
    for(let i=0;i<2;i++)await press(part(t.node,'look-add'));
    assert.equal(t.node.querySelectorAll('[data-ring-part="look-wheel"]').length,4);
    assert.equal(part(t.node,'look-add').disabled,true);
    await press(part(t.node,'look-remove'));assert.equal(t.node.querySelectorAll('[data-ring-part="look-wheel"]').length,3);
    await press(part(t.node,'look-clear'));assert.deepEqual(t.puts.at(-1),{entity_id:t.entity,look:null});
    assert.equal(t.calls.length,0);
  }finally{t.cleanup();}
});
check('failed_save_keeps_confirmed_look_and_editor_and_reports_feedback',async()=>{
  const t=await setup();try {
    await t.live.lightLooks.save(t.entity,{colour:[1,2,3],effects:{caribbean:[[0,0,255]]}});
    t.reject();await press(part(t.node,'effect-look-edit'));key(part(t.node,'look-wheel'),'Home');
    await press(part(t.node,'look-done'));await wait(50);
    assert.deepEqual(t.live.lightLooks.get(t.entity),{colour:[1,2,3],effects:{caribbean:[[0,0,255]]}});
    assert.ok(part(t.node,'look-editor'));assert.ok(t.alerts.some(s=>s.includes('Could not save')));assert.equal(t.calls.length,0);
  }finally{t.cleanup();}
});
check('switch_boolean_fan_and_no_colour_light_offer_one_stop_display_only',async()=>{
  for(const domain of ['switch','input_boolean','fan','light']) {
    const t=await setup({domain,surface:'panel'});try {
      if(domain==='light') {
        t.node.stop();t.node.remove();
        t.states[t.entity].attributes.supported_color_modes=['brightness'];
        t.node=lightControls({row:t.layout.devices[0],state:t.states[t.entity],control:t.live.control,lightLooks:t.live.lightLooks});document.body.append(t.node);
      }
      const open=part(t.node,'fixed-look-edit');assert.ok(open.textContent.includes('display only'));
      await press(open);assert.equal(t.node.querySelectorAll('[data-ring-part="look-wheel"]').length,1);
      assert.equal(part(t.node,'look-add'),null);assert.equal(part(t.node,'look-remove'),null);
      key(part(t.node,'look-wheel'),'Home');await press(part(t.node,'look-done'));await wait(30);
      assert.equal(t.puts.length,1);assert.deepEqual(Object.keys(t.puts[0].look),['colour']);assert.equal(t.calls.length,0);
      await press(open);assert.ok(part(t.node,'look-editor'));t.node.stop();
      assert.equal(part(t.node,'look-editor'),null,'every source, including fan, stops its current editor');
      if(domain==='light'){t.node.stop();t.node.remove();}
    }finally{t.cleanup();}
  }
});
let passed=0;
for(const [name,fn]of checks){try{await fn();passed++;console.log('  ok   '+name);}catch(error){console.error('  FAIL '+name+' '+error.message.slice(0,250));}}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${passed}/${checks.length} light-look control checks passed`);
process.exit(passed===checks.length?0:1);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER, prefix='chauffeur_light_looks_controls_'))
