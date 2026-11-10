"""Task 17 runtime proof with real scene tools and household geometry.

The controller's Chromium suite owns the pointer and screenshot acceptance.
Run from chauffeur/: python tests/test_twin_flags_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_twin_handles_js import BOOT_DRIVER

DRIVER = BOOT_DRIVER.split('const b=flat.buildings.find')[0] + r"""
const {createFlags} = await import(file('static/twin/editor/flags.js'));
const {createPanel} = await import(file('static/twin/editor/panel.js'));
const model = JSON.parse(readFileSync(process.argv[2])).model;
const shell=new Element(), descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
Element.prototype.closest=()=>shell;
Element.prototype.after=function(node){(this.parentElement||shell).append(node);};
Element.prototype.before=function(node){(this.parentElement||shell).append(node);};
Element.prototype.toggleAttribute=function(k,on){if(on)this[k]='';else delete this[k];};
Element.prototype.removeAttribute=function(k){delete this[k];};
Element.prototype.querySelectorAll=function(selector){return selector==='button'?descendants(this).filter(n=>n.tagName==='button'):[];};
Element.prototype.querySelector=function(selector){return this.querySelectorAll(selector)[0]||null;};
const create=doc.createElement;
doc.createElement=tag=>{const n=create(tag);n.tagName=tag;return n;};
doc.getElementById('editor-say').append(doc.createElement('button'));
shell.append(doc.getElementById('piece-card'));
let raf=0; const frames=new Map();
globalThis.requestAnimationFrame=fn=>{frames.set(++raf,fn);return raf;};
globalThis.cancelAnimationFrame=id=>frames.delete(id);
const tick=()=>{const batch=[...frames];frames.clear();for(const [,fn]of batch)fn();};
let current=flat;
const view=await mountTwin(new Element(),{plan:current,kit,tier:'low',preserveCamera:true});
const abort=new AbortController(), panel=createPanel({afterSay:async()=>{}}), saved=[];
const tools=createSceneTools({view,getPlan:()=>current,getModel:()=>model,getSheets:()=>({}),
  edit:async()=>{},op:async()=>{},panel,canEdit:()=>true,signal:abort.signal});
const flags=createFlags({view,getModel:()=>model,getPlan:()=>current,tools,panel,canEdit:()=>true,signal:abort.signal,
  op:async operation=>{
    saved.push(operation);
    const b=model.buildings.find(b=>b.id===operation.building);
    if(operation.field==='flag_ok')b.flags.splice(operation.value.index,1);
    else b.proposals=b.proposals.filter(p=>p.id!==operation.id);
    current.buildings.find(p=>p.id===b.id).proposals=b.proposals;
    await view.rebuild(current);tools.refresh();flags.refresh();
  }});
tools.delegate({pick:flags.pick});
flags.refresh();tick();
const count=descendants(shell).find(n=>n.id==='editor-flag-count');
assert.ok(count); const total=model.buildings.reduce((n,b)=>n+b.flags.length,0);
assert.equal(count.textContent,`${total} things to check`);
assert.equal(flags.flags().markers.length,total);
const world=(b,p)=>{
  const a=(b.rotation||0)*Math.PI/180,pos=b.position||[0,0];
  return new (view.camera.position.constructor)((Math.cos(a)*p[0]-Math.sin(a)*p[1]+pos[0])*.3048,
    (p[2]+(b.base||0))*.3048,-(Math.sin(a)*p[0]+Math.cos(a)*p[1]+pos[1])*.3048);
};
const visited=new Set();
for(let i=0;i<total;i++){
  count.dispatchEvent(new Event('click'));tick();
  const state=flags.flags(),c=state.current,b=model.buildings.find(b=>b.id===c.building),f=b.flags[c.index];
  assert.ok(!visited.has(c.building+':'+c.index));visited.add(c.building+':'+c.index);
  assert.equal(c.text,f.text);
  const lv=b.levels.find(l=>l.id===f.level);
  if(lv){const p=world(b,[...f.at,lv.elevation]).project(view.camera);assert.ok(Math.abs(p.x)<.01&&Math.abs(p.y)<.01);}
  if(typeof f.piece==='string'&&b.walls.some(w=>w.id===f.piece))assert.equal(tools.selection().id,f.piece);
  if(f.separators)assert.deepEqual(state.highlighted.slice().sort(),f.separators.slice().sort());
}
console.log('  ok count walks all household flags, focuses their points, selects pieces and highlights grouped separators');
const review=descendants(shell).find(n=>n.id==='review-card');
assert.ok(review&&!review.hidden);
const btn=label=>review.children.find(n=>n.tagName==='button'&&n.textContent===label);
const fix=btn('Fix it');fix.dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,0));tick();
assert.equal(flags.flags().count,total);assert.equal(saved.length,0);assert.equal(review.hidden,true);
count.dispatchEvent(new Event('click'));tick();
btn('Looks right').dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,30));tick();
assert.equal(saved.length,1);assert.equal(saved[0].field,'flag_ok');assert.equal(flags.flags().count,total-1);
assert.equal(flags.flags().current,null);assert.equal(flags.flags().markers.length,total-1);
console.log('  ok Fix it keeps the flag; Looks right posts once and removes its marker and current card');
const b=model.buildings.find(b=>b.id===B),bf=current.buildings.find(b=>b.id===B);
const north=bf.walls.find(w=>w.id==='wall:d60289b4c26b487db5145bdeb22d530e');
const p={id:north.id+':proposal',kind:'wall',against:north.id,piece:{...north,id:north.id+':proposal',
  from:[north.from[0],north.from[1]+2],to:[north.to[0],north.to[1]+2],state:'proposal'}};
b.proposals=[p];bf.proposals=b.proposals;flags.refresh();
tools.chooseFloor(B+':L1');
view.setCameraState({position:world(b,[8,13.33,30]).toArray(),target:world(b,[8,19.33,5]).toArray()});
tick();
const at=world(b,[8,19.33,5]).project(view.camera),canvas=view.renderer3.domElement;
for(const type of ['pointerdown','pointerup']){
  const event=new Event(type,{bubbles:true});Object.assign(event,{pointerId:1,button:0,clientX:(at.x+1)*720,clientY:(1-at.y)*450});
  canvas.dispatchEvent(event);
}
tick();assert.equal(tools.selection().kind,'proposal');assert.equal(tools.selection().id,p.id);
assert.ok(btn('Use this')&&btn('Dismiss'));assert.equal(review.hidden,false);
btn('Use this').dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,30));tick();
assert.deepEqual(saved.at(-1),{op:'accept_proposal',building:B,id:p.id});assert.equal(flags.proposals().length,0);
assert.notEqual(tools.selection().kind,'proposal');
console.log('  ok a real camera ray and scene-tools pointer select the proposal; Use this clears the ghost and selection');
b.proposals=[p];bf.proposals=b.proposals;flags.refresh();tools.select({id:p.id,building:B});tick();
btn('Dismiss').dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,30));tick();
assert.deepEqual(saved.at(-1),{op:'dismiss_proposal',building:B,id:p.id});assert.equal(flags.proposals().length,0);
assert.ok(bf.walls.some(w=>w.id===north.id&&w.from[1]===north.from[1]));
console.log('  ok Dismiss posts its own operation and preserves the person wall');
abort.abort();panel.dispose();view.dispose();assert.equal(frames.size,0);
console.log('4/4 passed');
"""


def run():
    if not shutil.which('node'):
        print('SKIP node is unavailable')
        return
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = assemble(fixture)[0]
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    paths = []
    try:
        for suffix, content in [('.mjs', DRIVER), ('.json', json.dumps({
                'root': ROOT.as_posix(), 'model': model, 'flat': flatten(model), 'kit': kit}))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_flags_', delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([shutil.which('node'), str(paths[0]), str(paths[1])], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
