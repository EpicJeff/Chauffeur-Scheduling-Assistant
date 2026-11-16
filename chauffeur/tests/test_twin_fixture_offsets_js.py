"""Resolved offsets reach the effect drop, fire emitters and bake signature."""
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {resolveFixture,resolveEmitters,emitterSignature}=await import(file('static/twin/live/emitters.js'));
const {bakeLights}=await import(file('static/twin/bake/runtime.js'));
const {buildEffects}=await import(file('static/twin/effects/index.js'));
const {effectLanding,rippleSources}=await import(file('static/twin/effects/water_ripples.js'));
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
const plan={buildings:[],site:{lot:[[0,0],[50,0],[50,50],[0,50]],pool:{id:'pool',polygon:[[0,0],[30,0],[30,30],[0,30]]}}};
const line={id:'line',shape:'line',ref:'absolute',path:[[5,5,4],[15,5,4]],facing:'out'};
for(const f of [{id:'point',shape:'point',ref:'absolute',at:[10,10,4]},line,{...line,snap:{host:{kind:'pool',id:'pool'},edge:{from:[0,0],to:[30,0]},t0:0,t1:1}}])await test('offset_resolves_'+f.shape+'_'+!!f.snap,()=>{
 const input={...f,offset_ft:-1},before=JSON.stringify(input),base=resolveFixture(f,plan),moved=resolveFixture(input,plan);
 const a=base.path||[base.at],b=moved.path||[moved.at];a.forEach((p,i)=>{close(b[i][0],p[0]);close(b[i][1],p[1]);close(b[i][2],p[2]-1);});assert.equal(JSON.stringify(input),before);
});
await test('offset_reaches_light_bake_key_and_fire_emitters',()=>{
 const p={...plan,light_fixtures:{'light.a':[{...line,offset_ft:0}]}},layout={markers:[],...p};
 const first=bakeLights(layout,null,p)[0],before=emitterSignature(resolveEmitters(layout,{},p));p.light_fixtures['light.a'][0].offset_ft=2;
 const second=bakeLights(layout,null,p)[0];assert.notEqual(second.signature,first.signature);assert.notEqual(emitterSignature(resolveEmitters(layout,{},p)),before);
 const fire={id:'fire',type:'fire',shape:'point',ref:'absolute',at:[10,10,0]},base=resolveEmitters({}, {}, {...plan,effect_fixtures:[fire]})[0];
 const raised=resolveEmitters({}, {}, {...plan,effect_fixtures:[{...fire,offset_ft:3}]})[0];close(raised.at[2],base.at[2]+3);
});
for(const type of ['waterfall','sheer'])await test(type+'_drop_and_ripple_landing_use_offset_height',()=>{
 const f={...line,type,size_min:1,size_max:1},p={...plan,effect_fixtures:[f]},base=buildEffects(p,{editor:true}).fixtures[0];
 f.offset_ft=2;const moved=buildEffects(p,{editor:true}).fixtures[0];close(moved.position[2],base.position[2]+2);
 const bounds=row=>new THREE.Box3().setFromObject(row.group),a=bounds(base),b=bounds(moved);
 close(b.max.y,a.max.y+2);close(b.min.y,a.min.y);close(b.min.y,effectLanding(p,moved.position).height);
 assert.equal(rippleSources(p)[0].id,'pool');
 f.drop_ft=moved.position[2]-effectLanding(p,moved.position).height;assert.equal(rippleSources(p).length,1);
 f.offset_ft=0;assert.equal(rippleSources(p).length,0,'manual drop hits water only at offset launch height');
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)
