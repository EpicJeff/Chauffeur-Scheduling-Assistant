"""Object shelf events and object lamps in the existing real-light pool."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from twin_live_node_rig import PRELUDE, run

DRIVER = r"""
const objects = await import(file('static/twin/objects.js'));
window.twinObjectSchema = JSON.parse(readFileSync(root + '/static/twin/object_schema.json'));
const {drawObjectShelf} = await import(file('static/twin/editor/object_shelf.js'));
const host=document.createElement('div');document.body.append(host);
const record={piece:{id:'chair',at:[1,2]},kind:'furniture',index:0,building:null};
const saved=[];let pending=Promise.resolve();
drawObjectShelf(host,record,{canEdit:()=>true,queue:work=>pending=pending.then(work),op:async op=>saved.push(op),report:error=>{throw error;}});
const scale=host.querySelector('[aria-label="Scale (factor)"]');assert.ok(scale);scale.value='1.5';scale.dispatchEvent(new Event('change'));await pending;
assert.deepEqual(saved.pop(),{op:'set_object',list:'furniture',index:0,properties:{scale:1.5}});
const tint=host.querySelector('[aria-label="Material tint"]');tint.value='#abcdef';tint.dispatchEvent(new Event('change'));await pending;
assert.equal(saved.pop().properties.tint,'#abcdef');
const shadow=host.querySelector('[aria-label="Casts shadow"]');shadow.checked=false;shadow.dispatchEvent(new Event('change'));await pending;
assert.equal(saved.pop().properties.casts_shadow,false);
assert.ok(host.querySelector('details'));host.remove();
assert.deepEqual(domErrors,[]);console.log('ok actual shelf saves exact scale, tint and shadow through model ops');

const {mountModes}=await import(file('static/twin/live/modes.js'));
const controls=document.createElement('div');controls.id='twin-controls';document.body.append(controls);
const scene=new THREE.Scene(), lamp=objects.applyObject(new THREE.Mesh(new THREE.BoxGeometry(1,2,1),new THREE.MeshStandardMaterial()),
 {id:'lamp',object_kind:'lamp',light_entity:'light.desk',emissive_color:'#ffffff'},{units:1,id:'b:lamp'});scene.add(lamp);
const canvas=document.createElement('canvas');document.body.append(canvas);
const view={scene,tier:'low',renderer3:{domElement:canvas},camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},
 groups:{levels:{'b:L1':new THREE.Group()}},plan:{buildings:[{id:'b',items:[{id:'lamp',host:{floor:'room',u:.5,v:.5}}],rooms:[{id:'room',level:'L1'}],walls:[],levels:[]}]} };
const states={'light.desk':{state:'on',attributes:{brightness:128,rgb_color:[0,64,255]}}};
const live={layout:()=>({markers:[],rooms:[]}),peek:()=>states,stale:()=>false,rooms:()=>[],subscribe:()=>()=>{},
 energy:()=>({}),setMode(){},getMode:()=> 'all'};
const modes=mountModes(view,live);modes.setMode('lights');
let rows=modes.lights();assert.equal(rows.length,1);assert.equal(rows[0].device,'object:b:lamp');assert.equal(rows[0].real,true);
assert.deepEqual(rows[0].rgb,[0,64,255]);assert.ok(Math.abs(lamp.material.emissiveIntensity-128/255)<.00001);
const pool=[];scene.traverse(o=>{if(o.isPointLight)pool.push(o);});assert.equal(pool.length,4);
const material=lamp.material;states['light.desk'].state='off';modes.update();assert.equal(material.emissiveIntensity,0);
states['light.desk'].state='on';modes.update();assert.equal(lamp.material,material);assert.equal(pool.filter(l=>l.parent).length,4);
view.groups.levels['b:L1'].visible=false;modes.draw();assert.equal(modes.lights()[0].real,false);
modes.stop();controls.remove();console.log('ok linked object lamp follows HA state in the same fixed four-light pool, retains material and follows floor visibility');
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER, timeout=90))
