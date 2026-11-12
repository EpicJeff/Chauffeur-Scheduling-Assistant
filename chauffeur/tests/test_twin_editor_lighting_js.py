"""Execute editor lighting controls and real mounted view in Node; no Chromium."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE = await import('three');
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {mountLighting} = await import(file('static/twin/editor/lighting.js'));
const {createUnlit} = await import(file('static/twin/unlit.js'));
function controls() {
  const host = new Element();
  for (const name of ['day','night','now','unlit']) {
    const button = new Element('button'); button.dataset.editorLighting = name; host.append(button);
  }
  return host;
}
function storage(saved) {
  const data = new Map(saved ? [['chf.editor.lighting',saved]] : []);
  return {getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
}
async function mount(editor=true) {
  const host = new Element();
  if (editor) { const shell = new Element(); shell.className='editor-shell'; shell.append(host); }
  return mountTwin(host,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'high',bake:false,
    site:{source:'home_location',lat:40,lon:0,timezone:'Etc/UTC'}});
}
await test('editor mounts in Day even at midnight and keeps Now clock-following', async()=>{
  const v=await mount();
  try {
    v.setClock('2026-06-22T00:00:00Z'); assert.equal(v.state.time,'day');
    assert.ok(v.scene.getObjectByName('real-sun').intensity>0);
    v.setTime('now'); assert.equal(v.scene.getObjectByName('real-sun').intensity,0);
    v.setClock('2026-06-22T12:00:00Z'); assert.ok(v.scene.getObjectByName('real-sun').intensity>0);
  } finally {v.dispose();}
});
await test('control defaults Day and persists/reloads every choice through clicks',async()=>{
  const v=await mount(), host=controls(), device=storage();
  try {
    const lighting=mountLighting(v,host,{storage:device}); assert.equal(lighting.choice(),'day');
    for (const mode of ['night','now','unlit','day']) {
      await click(host.querySelector(`[data-editor-lighting="${mode}"]`));
      assert.equal(device.getItem('chf.editor.lighting'),mode);
      assert.equal(v.state.unlit,mode==='unlit');
      assert.equal(v.state.time,mode==='unlit'?'day':mode);
      assert.equal(host.querySelector('[aria-pressed="true"]').dataset.editorLighting,mode);
      assert.equal(mountLighting(v,controls(),{storage:device}).choice(),mode);
    }
  } finally {v.dispose();}
});
await test('invalid and unavailable device storage fall back to usable Day',async()=>{
  const v=await mount();
  try {
    assert.equal(mountLighting(v,controls(),{storage:storage('bad')}).choice(),'day');
    const broken={getItem(){throw Error('private');},setItem(){throw Error('private');}};
    const lighting=mountLighting(v,controls(),{storage:broken});
    lighting.select('night'); assert.equal(v.state.time,'night');
    lighting.select('invalid'); assert.equal(v.state.time,'night');
  } finally {v.dispose();}
});
await test('injected idle clock keeps editor previews fixed and twin previews expire at 120s',async()=>{
  const editor=await mount(), twin=await mount(false);
  const oldSet=globalThis.setTimeout, oldClear=globalThis.clearTimeout;
  let now=0, serial=0; const timers=new Map();
  globalThis.setTimeout=(fn,ms)=>{const id=++serial;timers.set(id,{fn,at:now+ms});return id;};
  globalThis.clearTimeout=id=>timers.delete(id);
  const advance=ms=>{now+=ms;for(const [id,t] of [...timers])if(t.at<=now){timers.delete(id);t.fn();}};
  try {
    assert.equal(twin.state.time,'now');
    for(const mode of ['day','night']) {
      editor.setTime(mode); twin.setTime(mode);
      advance(119999); assert.equal(twin.state.time,mode);
      advance(1); assert.equal(twin.state.time,'now'); assert.equal(editor.state.time,mode);
      editor.expireTimePreview(); assert.equal(editor.state.time,mode);
    }
    twin.setTime('day'); twin.setTime('now'); advance(120000); assert.equal(twin.state.time,'now');
  } finally {globalThis.setTimeout=oldSet;globalThis.clearTimeout=oldClear;editor.dispose();twin.dispose();}
});
await test('Unlit swaps actual meshes and arrays then restores identical objects and material refs',async()=>{
  const v=await mount(), originals=[];
  try {
    v.scene.traverse(o=>{if(o.isMesh)originals.push([o,o.material,o.castShadow,o.receiveShadow]);});
    v.setUnlit(true);
    assert.ok(originals.some(([o,m])=>o.material!==m));
    for(const [o] of originals) { assert.equal(o.castShadow,false);assert.equal(o.receiveShadow,false); }
    v.setUnlit(false);
    for(const [o,m,cast,receive] of originals) {
      assert.ok(o.parent);assert.equal(o.material,m);assert.equal(o.castShadow,cast);assert.equal(o.receiveShadow,receive);
    }
  } finally {v.dispose();}
});
await test('Unlit has no light/environment/shadow work and restores the lit configuration',async()=>{
  const v=await mount();
  try {
    const environment=v.scene.environment, enabled=v.renderer3.shadowMap.enabled, auto=v.renderer3.shadowMap.autoUpdate;
    v.setUnlit(true);v.setTime('night');
    v.scene.traverse(o=>{if(o.isLight)assert.equal(o.intensity,0);});
    assert.equal(v.scene.environment,null);assert.equal(v.renderer3.shadowMap.enabled,enabled);
    assert.equal(v.renderer3.shadowMap.autoUpdate,false);assert.equal(v.renderer3.shadowMap.needsUpdate,false);
    v.setUnlit(false);assert.equal(v.scene.environment,environment);assert.equal(v.renderer3.shadowMap.autoUpdate,auto);
    v.setTime('day');assert.ok(v.scene.getObjectByName('real-sun').intensity>0);
  } finally {v.dispose();}
});
await test('rebuild and preserved yard stay Unlit; leaving restores new lit materials',async()=>{
  const v=await mount();
  try {
    v.setUnlit(true);await v.rebuild(structuredClone(input.plan),{preserveYard:true});
    assert.equal(v.state.unlit,true);assert.equal(v.scene.environment,null);
    let count=0;v.scene.traverse(o=>{for(const m of [].concat(o.material||[]))if(m.isMeshMatcapMaterial)count++;});assert.ok(count>0);
    v.setUnlit(false);
    v.scene.traverse(o=>{for(const m of [].concat(o.material||[]))assert.ok(!m.isMeshMatcapMaterial);});
  } finally {v.dispose();}
});
await test('glass and plants retain colour, map, transparency, alphaTest and side',()=>{
  const root=new THREE.Group(), map=new THREE.Texture();
  const glass=new THREE.MeshStandardMaterial({color:'#aaccee',transparent:true,opacity:.3,depthWrite:false});
  const plant=new THREE.MeshStandardMaterial({color:'#337744',map,alphaTest:.5,side:THREE.DoubleSide});
  const materials=[glass,plant], mesh=new THREE.Mesh(new THREE.BoxGeometry(),materials);root.add(mesh);
  const unlit=createUnlit();
  try {
    unlit.apply(root);assert.notEqual(mesh.material,materials);
    for(let i=0;i<2;i++)for(const key of ['map','opacity','transparent','alphaTest','side','depthWrite'])
      assert.equal(mesh.material[i][key],materials[i][key]);
    assert.ok(mesh.material[1].color.equals(plant.color));assert.equal(mesh.material[1].lightMap,undefined);
    unlit.restore();assert.equal(mesh.material,materials);
  } finally {unlit.dispose();glass.dispose();plant.dispose();map.dispose();mesh.geometry.dispose();}
});
await test('cached replacements survive toggles and dispose only on source or view disposal',()=>{
  const root=new THREE.Group(), source=new THREE.MeshStandardMaterial(), mesh=new THREE.Mesh(new THREE.BoxGeometry(),source);
  root.add(mesh);const unlit=createUnlit();unlit.apply(root);
  const first=mesh.material, matcap=first.matcap;let disposed=0,textureDisposed=0;
  first.addEventListener('dispose',()=>disposed++);matcap.addEventListener('dispose',()=>textureDisposed++);
  for(let i=0;i<4;i++){unlit.restore();assert.equal(mesh.material,source);unlit.apply(root);assert.equal(mesh.material,first);}
  assert.equal(disposed,0);unlit.restore();source.dispose();assert.equal(disposed,1);
  unlit.dispose();assert.equal(textureDisposed,1);mesh.geometry.dispose();
});
await test('basic ghosts and overlays keep their original materials',()=>{
  const root=new THREE.Group(), source=new THREE.MeshBasicMaterial({transparent:true,opacity:.25});
  const ghost=new THREE.Mesh(new THREE.BoxGeometry(),source);root.add(ghost);
  const unlit=createUnlit();unlit.apply(root);assert.equal(ghost.material,source);
  unlit.dispose();assert.equal(ghost.material,source);source.dispose();ghost.geometry.dispose();
});
await test('shared replacements follow late textures and material edits without losing shadow flags',()=>{
  const root=new THREE.Group(),source=new THREE.MeshStandardMaterial(),geometry=new THREE.BoxGeometry();
  const a=new THREE.Mesh(geometry,source),b=new THREE.Mesh(geometry,source);root.add(a,b);
  a.castShadow=a.receiveShadow=true;
  const unlit=createUnlit();unlit.apply(root);const first=a.material;
  assert.equal(first,b.material);
  const texture=new THREE.Texture();source.map=texture;source.color.set('#112233');
  unlit.apply(root);assert.equal(a.material,first);assert.equal(first.map,texture);assert.ok(first.color.equals(source.color));
  const changed=source.clone();a.material=changed;unlit.apply(root);
  unlit.restore();assert.equal(a.material,changed);assert.equal(b.material,source);
  assert.equal(a.castShadow,true);assert.equal(a.receiveShadow,true);
  unlit.dispose();changed.dispose();source.dispose();texture.dispose();geometry.dispose();
});
await test('selection and faded floors can change while Unlit without losing original ownership',async()=>{
  const v=await mount();
  try {
    v.setUnlit(true);const key=v.levelKeys()[0],b=v.plan.buildings[0];
    v.showLevels([key],{faint:[key]});
    v.setSelection({selected:{building:b.id,id:b.walls[0].id,kind:'wall'},hover:null,room:null});
    assert.equal(v.state.unlit,true);
    v.setUnlit(false);
    v.scene.traverse(o=>{for(const m of [].concat(o.material||[]))assert.ok(!m.isMeshMatcapMaterial);});
    v.setSelection({selected:null,hover:null,room:null});v.showLevels(null);
    v.setUnlit(true);v.setUnlit(false);
  } finally {v.dispose();}
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
