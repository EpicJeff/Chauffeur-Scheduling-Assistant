"""Exercise the new editor entry point and fields under Node, without Chromium."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_twin_drag_js import DRIVER as BASE

DRIVER = BASE.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE=await import(three);
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createTerrainTools,snapPadPoint}=await import(file('static/twin/editor/terrain_tools.js'));
const {foundationShelf}=await import(file('static/twin/editor/foundation_shelf.js'));
const nodes=new Map(),shell=new Element();
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
document.createElement=tag=>{const n=new Element();n.tag=tag;n.isConnected=true;return n;};
document.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
document.querySelector=selector=>selector==='.editor-shell'?shell:null;
Element.prototype.querySelectorAll=function(selector){return descendants(this).filter(n=>selector.split(',').includes(n.tag));};
Element.prototype.querySelector=function(selector){return descendants(this).find(n=>n['aria-label']===selector.match(/aria-label="([^"]+)"/)?.[1])||null;};
Element.prototype.getAttribute=function(k){return this[k];};
Element.prototype.setPointerCapture=function(id){this.capture=id;};
Element.prototype.hasPointerCapture=function(id){return this.capture===id;};
Element.prototype.releasePointerCapture=function(){this.capture=null;};
Element.prototype.closest=()=>null;
window.showGlobalAlert=text=>{throw Error(text);};window.promptConfirm=async()=>true;
const plan={buildings:[],site:{lot:[[0,0],[40,0],[40,40],[0,40]],terraces:[],beds:[{id:'bed',polygon:[[5,5],[10,5],[10,10],[5,10]]}]},materials:{}};
const view=await mountTwin(new Element(),{plan,kit,tier:'low',preserveCamera:true});
view.setCameraState({position:[20*.3048,80*.3048,-19.999*.3048],target:[20*.3048,0,-20*.3048]});
const abort=new AbortController(),ops=[], tools={select(){},setTool(name){document.getElementById('rail-select').setAttribute('aria-pressed',String(name==='select'));}};let writable=true;
const op=async operation=>{ops.push(operation);if(operation.op==='add_pad')plan.site.terraces.push({id:'pad',...operation,edges:operation.polygon.map(()=>({edge:'slope'}))});
  if(operation.op==='update_pad')Object.assign(plan.site.terraces[0],operation);
  if(operation.op==='delete_pad')plan.site.terraces=[];
};
const terrain=createTerrainTools({view,tools,getPlan:()=>plan,op,canEdit:()=>writable,signal:abort.signal});
terrain.show();const card=descendants(shell).find(n=>n.id==='terrain-card');
const click=text=>{const b=descendants(card).find(n=>n.textContent===text);assert.ok(b,text);b.dispatchEvent(new Event('click'));};
const change=(title,value)=>{const input=descendants(card).find(n=>n['aria-label']===title);assert.ok(input,title);input.value=String(value);input.dispatchEvent(new Event('change'));};
click('Add pad');change('Pad height (ft)',-4);change('Blend (ft)',8);
const event=p=>{const v=new THREE.Vector3(p[0]*.3048,0,-p[1]*.3048).project(view.camera);return {button:0,pointerId:1,clientX:(v.x+1)*720,clientY:(1-v.y)*450};};
for(const p of [[15,15],[25,15],[25,25],[15,25]]){assert.ok(terrain.pointerDown(event(p)));terrain.pointerUp(event(p),false);}
click('Finish pad');await new Promise(r=>setTimeout(r,0));
assert.equal(ops[0].op,'add_pad');assert.equal(ops[0].height,-4);assert.equal(ops[0].blend,8);assert.equal(ops[0].polygon.length,4);
terrain.choose('terraces','pad');change('Edge 1','sharp');await new Promise(r=>setTimeout(r,0));
assert.equal(ops.at(-1).edges[0].edge,'sharp');
click('Up 0.5 ft');await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).height,-3.5);
const h=terrain.handles()[0];assert.ok(h);
const drag={button:0,pointerId:2,clientX:h.screen[0],clientY:h.screen[1]};
const beforeClick=ops.length;assert.ok(terrain.pointerDown(drag));terrain.pointerUp(drag,false);assert.equal(ops.length,beforeClick,'a corner click creates no history round');
assert.ok(terrain.pointerDown(drag));terrain.pointerMove({...drag,clientX:drag.clientX+15});terrain.pointerUp({...drag,clientX:drag.clientX+15},false);
await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).op,'update_pad');assert.notDeepEqual(ops.at(-1).polygon,ops[0].polygon);
terrain.choose('beds','bed');change('Move east (ft)',3);await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.at(-1),{op:'move_site_item',list:'beds',id:'bed',by:[3,0]});
assert.deepEqual(snapPadPoint([.4,12],plan),[0,12]);
writable=false;const count=ops.length;change('Move east (ft)',5);assert.equal(ops.length,count);writable=true;
const host=new Element(), building={id:'b',base:0,foundation:{mode:'fixed',offset_ft:0,thickness_ft:1}};
let preview;
foundationShelf(host,building,{getPlan:()=>({buildings:[building]}),canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op,report:error=>{throw error;},preview:async plan=>{preview=plan;}});
const mode=descendants(host).find(n=>n['aria-label']==='Foundation mode');mode.value='auto';mode.dispatchEvent(new Event('change'));
await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.at(-1),{op:'set_foundation',building:'b',foundation:{mode:'auto',offset_ft:0,thickness_ft:1}});
const offset=descendants(host).find(n=>n['aria-label']==='Offset (ft)');offset.value='2';offset.dispatchEvent(new Event('input'));
await new Promise(r=>setTimeout(r,210));assert.equal(preview.buildings[0].foundation.offset_ft,2,'foundation input runs a live preview without mutating the model');assert.equal(building.foundation.offset_ft,0);
abort.abort();view.dispose();console.log('Terrain editor draw, edge, nudge, vertex drag, yard move, read-only and foundation fields passed');
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_ground_tools_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=300)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
