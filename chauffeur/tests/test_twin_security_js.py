"""Security attention, camera direction and existing refusal/confirm controls."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {securityAttention,securityItem,cameraDirection}=await import(file('static/twin/live/security.js'));
const checks=[],check=(n,f)=>checks.push([n,f]);
check('unlocked/open loud, resting locked/closed quiet',()=>{
 for(const [kind,id,on,off,dc] of [['lock','lock.d','unlocked','locked'],['sensor','binary_sensor.d','on','off','door'],['sensor','binary_sensor.w','on','off','window'],['garage','cover.g','open','closed','garage']]){
 const row={kind,entity_id:id};assert.equal(securityAttention(row,{state:on,attributes:{device_class:dc}}),true);assert.equal(securityAttention(row,{state:off,attributes:{device_class:dc}}),false);
 assert.equal(securityAttention(row,{state:'unavailable'}),false);}
 assert.equal(securityAttention({kind:'light',entity_id:'light.a'},{state:'on'}),false);
});
check('foreground includes contacts, garage, alarm, cameras',()=>{
 for(const kind of ['lock','garage','alarm','camera'])assert.equal(securityItem({kind},{}),true);
 assert.equal(securityItem({kind:'sensor',entity_id:'binary_sensor.x'},{attributes:{device_class:'window'}}),true);
 assert.equal(securityItem({kind:'sensor',entity_id:'sensor.x'},{attributes:{device_class:'temperature'}}),false);
});
check('placed camera facing wins; indoor points to room; outdoor away',()=>{
 assert.deepEqual(cameraDirection({at:[2,3,5],facing_deg:0,room:'r'},[0,0],[0,0]),[1,0]);
 const rotated=cameraDirection({at:[2,3,5],orientation:90},null,[0,0]);assert.ok(Math.abs(rotated[0])<1e-6);assert.equal(rotated[1],1);
 assert.deepEqual(cameraDirection({at:[10,0,5],room:'r'},[0,0],[20,0]),[-1,0]);
 assert.deepEqual(cameraDirection({at:[10,0,5]},null,[0,0]),[1,0]);
 assert.deepEqual(cameraDirection({at:[10,0,5],room:'r',outdoor:true},[0,0],[0,0]),[1,0]);
});
check('mounted mode updates red emphasis and alarm legend then cleans up',async()=>{
 const t=await rig({devices:[{device_id:'door',name:'Back door',entity_id:'lock.back',kind:'lock',state:'unlocked'},
 {device_id:'contact',name:'Window',entity_id:'binary_sensor.window',kind:'sensor',state:'on',attributes:{device_class:'window'}},
 {device_id:'alarm',name:'Alarm',entity_id:'alarm_control_panel.a',kind:'alarm',state:'armed_home'},
 {device_id:'light',name:'Light',entity_id:'light.a',kind:'light',state:'on'}]});
 try{t.live.setMode('security');const red=[];t.view.scene.traverse(o=>{if(o.userData.securityAttention)red.push(o);});
 assert.equal(red.filter(o=>o.visible).length,2);assert.match(document.getElementById('twin-mode-legend').textContent,/armed home/);
 assert.equal(t.live.marker('door').dim,false);assert.equal(t.live.marker('light').dim,true);
 t.states['lock.back'].state='locked';t.states['binary_sensor.window'].state='off';await t.live.refresh();assert.equal(red.filter(o=>o.visible).length,0);
 t.live.setMode('all');assert.equal(red.filter(o=>o.visible).length,0);
 }finally{t.cleanup();}assert.equal(t.view.scene.children.filter(o=>o.children.some(c=>c.userData.securityAttention)).length,0);
});
check('unoffered camera keeps 25 foot cone and existing refusal',async()=>{
 const t=await rig({devices:[{device_id:'camera',name:'Camera',entity_id:'camera.k',kind:'camera',state:'idle',offered:false}]});
 try{t.live.setMode('security');let cone;t.view.scene.traverse(o=>{if(o.userData.cameraCone)cone=o;});assert.ok(cone.visible);assert.equal(cone.userData.cameraCone.length_ft,25);
 await t.tap('camera');assert.equal(t.serviceCalls().length,0);assert.ok(document.querySelector('[data-ring]'));t.live.setMode('all');assert.equal(cone.visible,false);
 }finally{t.cleanup();}
});
check('Security lock tap retains unsafe confirmation',async()=>{
 const t=await rig({devices:[{device_id:'door',name:'Back door',entity_id:'lock.back',kind:'lock',state:'locked'}]});
 try{t.live.setMode('security');await t.tap('door');const button=[...document.querySelector('[data-ring]').querySelectorAll('button')].find(b=>/unlock/i.test(b.textContent));assert.ok(button);t.confirm=false;await press(button);assert.equal(t.confirms.length,1);assert.equal(t.serviceCalls().length,0);}finally{t.cleanup();}
});
let failed=0;for(const[n,f]of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);console.log(`${checks.length-failed}/${checks.length} security checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    sys.exit(run(DRIVER))
