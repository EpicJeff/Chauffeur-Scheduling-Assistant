"""A light that is a control of another device is still a light: it bakes and it lights live.

Owner 2026-11-20: the Pool Lounge camera (an Arlo VMC5040) carries a spotlight entity. The
twin calls that device a camera, the spotlight hung off it as a control, and both the bake
(lightsOf, kind === 'light') and the live lamps (resolveEmitters' legacy markers) skipped it,
so it never baked. Same for a recessed fixture's second light entity (its trim ring). Runs
the production modules in node: lightMarkers, the bake's light list and the live emitters.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_twin_tree_once_js import PREFIX  # noqa: E402
from twin_editor_dom import run_node  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

DRIVER = PREFIX + r"""
window.chfBase=file('');
const {lightMarkers,resolveEmitters}=await import(file('static/twin/live/emitters.js'));
const {lightsOf,bakeLights}=await import(file('static/twin/bake/runtime.js'));
const plan={buildings:[{id:'pool-house',levels:[{id:'L1',elevation:0,ceiling:10}],
  rooms:[{id:'lounge',level:'L1',polygon:[[0,0],[20,0],[20,20],[0,20]]}]}],site:{}};
const at={building:'pool-house',level:'L1',room:'lounge',placed:true};
const camera={...at,device_id:'cam',name:'Pool House Lounge',kind:'camera',entity_id:'camera.pool_house_lounge',
  entities:['camera.pool_house_lounge','light.pool_house_lounge','switch.pool_house_lounge_siren'],at:[4,4,10],
  accessories:[{entity_id:'light.pool_house_lounge',name:'Spotlight',kind:'light',offered:true},
               {entity_id:'switch.pool_house_lounge_siren',name:'Siren',kind:'switch',offered:true}]};
const recessed={...at,device_id:'rec',name:'Recessed 1',kind:'light',entity_id:'light.rec_main',
  entities:['light.rec_main','light.rec_trim'],at:[10,10,10],
  accessories:[{entity_id:'light.rec_trim',name:'trim',kind:'light',offered:true}]};
const lock={...at,device_id:'lock',name:'Door',kind:'lock',entity_id:'lock.door',entities:['lock.door'],at:[1,1,4],accessories:[]};
const layout={markers:[camera,recessed,lock]};

const lights=lightMarkers(layout);
assert.deepEqual(lights.map(m=>m.device_id),['cam|light.pool_house_lounge','rec','rec|light.rec_trim'],
  'a camera spotlight and a trim ring are lights; a siren and a lock are not');
const spot=lights[0];
assert.equal(spot.entity_id,'light.pool_house_lounge');assert.equal(spot.kind,'light');
assert.deepEqual(spot.at,camera.at,'the spotlight sits at its device');
assert.equal(spot.accessory_of,'cam');assert.equal(spot.name,'Pool House Lounge Spotlight');
assert.equal(layout.markers[0].kind,'camera','the device marker itself is untouched');

assert.deepEqual(lightsOf(layout).map(l=>l.device).sort(),['cam|light.pool_house_lounge','rec','rec|light.rec_trim'],
  'the bake takes every light, whatever device carries it');
assert.deepEqual(bakeLights(layout,null,plan).flatMap(l=>l.members||[l.device]).sort(),['cam|light.pool_house_lounge','rec','rec|light.rec_trim']);

// Off lights bake too: the bake list never reads state.
const emitters=resolveEmitters(layout,{'light.pool_house_lounge':{state:'on',attributes:{brightness:255}},
  'light.rec_main':{state:'off',attributes:{}},'light.rec_trim':{state:'on',attributes:{brightness:128}}},plan);
const byId=Object.fromEntries(emitters.map(e=>[e.marker.device_id,e]));
assert.ok(byId['cam|light.pool_house_lounge']?.on,'the spotlight lights live with its own entity');
assert.equal(byId['rec'].on,false,'the main light follows its own entity');
assert.ok(byId['rec|light.rec_trim'].on && byId['rec|light.rec_trim'].brightness<1,'the trim follows its own entity');

// A fixture drawn for the spotlight's entity takes over from the plain marker, as for any light.
const drawn={...layout,light_fixtures:{'light.pool_house_lounge':[{id:'fixture:s',shape:'point',ref:'absolute',at:[4,4,9]}]}};
assert.deepEqual(bakeLights(drawn,null,plan).flatMap(l=>l.members||[l.device]).sort(),['light.pool_house_lounge','rec','rec|light.rec_trim'],
  'a drawn fixture replaces the marker light');
assert.ok(!resolveEmitters(drawn,{},plan).some(e=>e.legacy&&e.marker.device_id==='cam|light.pool_house_lounge'));
// Lights at one spot share one bake channel (owner 2026-11-21): the recessed main and its trim
// ring become one shared slot; a lone light keeps its own id; fixtures and object lamps never group.
const {shareColocated,SHARED_PREFIX}=await import(file('static/twin/bake/runtime.js'));
const shared=bakeLights(layout,null,plan);
const group=shared.find(l=>l.members);
assert.deepEqual(group.members,['rec','rec|light.rec_trim'],'main and trim share');
assert.equal(group.device,SHARED_PREFIX+'rec+rec|light.rec_trim');
assert.ok(shared.some(l=>l.device==='cam|light.pool_house_lounge'&&!l.members),'a light alone at its spot keeps its id');
assert.equal(shared.length,2);
const loose=shareColocated([{device:'a',at:[1,1,9],room:'r'},{device:'fx',at:[1,1,9],room:'r',emitters:[{}]},
  {device:'object:o',at:[1,1,9],absolute:true},{device:'b',at:[1,1.5,9],room:'r'}]);
assert.deepEqual(loose.map(l=>l.device),['a','fx','object:o','b'],'fixtures, object lamps and other spots stay apart');

// The shared slot's tint is the sum of its members' linear colours; black when the slot is not fresh.
const {tintSum}=await import(file('static/twin/bake/lightmap_material.js'));
const both=tintSum([{rgb:[255,255,255],intensity:.5},{rgb:[255,0,0],intensity:.5}]);
assert.ok(Math.abs(both.r-1)<1e-6 && Math.abs(both.g-.5)<1e-6,'members add');
assert.equal(tintSum([{rgb:[255,255,255],intensity:1}],false).r,0,'not fresh: black');
console.log('PASS accessory lights bake and light live');
process.exit(0);
"""


def main():
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output, flush=True)
    if code is None:
        return
    assert code == 0, output


if __name__ == '__main__':
    main()
