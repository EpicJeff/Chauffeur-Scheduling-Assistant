"""Execute alpha rendering and legacy-look comparisons in Node, without a GPU."""
import subprocess
import sys
from pathlib import Path

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '\n'.join(line for line in PRELUDE.splitlines()
                   if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url:data(`import {Group} from '${three}'; export class Tree extends Group {}`),shortCircuit:true};
  if (spec === 'three')""")
DRIVER = PREFIX + r"""
const THREE = await import('three');
const lib = await import(file('static/twin/twin_library.js'));
const mainURLs = new Map();
function mainURL(path) {
  if (mainURLs.has(path)) return mainURLs.get(path);
  const source = input.mainSources[path].replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g, (_, a, s, b) => {
    const url = new URL(s, file(path)).href;
    const ref = Object.keys(input.mainSources).find(p => file(p) === url);
    return a + (ref ? mainURL(ref) : url) + b;
  });
  const url = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
  mainURLs.set(path, url); return url;
}
const legacy = await import(mainURL('static/twin/twin_library.js'));
const requests = [];
let hold = false;
THREE.TextureLoader.prototype.load = function(url, done) {
  const texture = new THREE.Texture({width:4,height:4,url}); texture.name = url;
  requests.push({url, texture});
  if (!hold) queueMicrotask(() => done(texture));
  return texture;
};
const make = (id, params, maps = {}) => ({materials:{floor:{id}},manifest:{[id]:{
  household:true,kind:'material',revision:7,params,maps,
}}});
const flags = m => [m.alphaTest,m.transparent,m.opacity,m.side,m.depthWrite,m.alphaMap];
const look = m => ({color:m.color.getHexString(),opacity:m.opacity,transparent:m.transparent,
  roughness:m.roughness,depthWrite:m.depthWrite,side:m.side,name:m.name});
const ready = async m => { await m.userData.ready; return m; };
const modes = () => assert.equal(typeof lib.alphaModeOf, 'function', 'alphaModeOf is not a function');

await test('cutout_sets_alpha_test_and_double_side', async () => {
  modes();
  const kit = make('cutout', {alpha_mode:'cutout',alpha_cutoff:.4}, {opacity:'materials/cutout/opacity.png'});
  const m = lib.kitMaterial('floor',kit,'high');
  assert.equal(lib.alphaModeOf(kit.manifest.cutout,{}),'cutout');
  assert.equal(m.alphaTest,.4); assert.equal(m.side,THREE.DoubleSide); assert.equal(m.transparent,false);
  assert.equal(m.userData.alphaMode,'cutout'); await ready(m);
  assert.ok(m.alphaMap?.isTexture); assert.equal(m.alphaMap.image,requests.at(-1).texture.image);
  assert.equal(m.alphaMap.colorSpace,THREE.NoColorSpace); m.dispose();
});
await test('cutout_cutoff_is_always_positive', async () => {
  for (const cutoff of [0,.001,.4,1]) for (const tier of ['low','high']) {
    const m=lib.kitMaterial('floor',make('cutoff-'+cutoff,{alpha_mode:'cutout',alpha_cutoff:cutoff}),tier);
    assert.equal(m.alphaTest,Math.max(cutoff,.01)); assert.ok(m.alphaTest>0); m.dispose();
  }
});
await test('blend_sets_opacity_and_no_depth_write', async () => {
  modes();
  const m = lib.kitMaterial('floor',make('blend',{alpha_mode:'blend',opacity:.35},
    {opacity:'materials/blend/opacity.png'}),'high');
  assert.equal(m.transparent,true); assert.equal(m.opacity,.35); assert.equal(m.depthWrite,false);
  assert.equal(m.alphaTest,0); assert.equal(m.userData.alphaMode,'blend'); assert.ok(!(m.transmission > 0));
  await ready(m); assert.ok(m.alphaMap); m.dispose();
});
await test('mode_flags_are_set_before_any_map_loads_and_on_low_tier', async () => {
  modes(); hold = true;
  try {
    for (const tier of ['low','high']) for (const mode of ['opaque','cutout','blend']) {
      const id = 'held-' + tier + mode, before = requests.length;
      const kit = make(id,{alpha_mode:mode,opacity:.35,alpha_cutoff:.4},Object.fromEntries(
        ['base_color','normal','roughness','opacity'].map(slot => [slot,`materials/${id}/${slot}.png`])));
      const m = lib.kitMaterial('floor',kit,tier);
      assert.deepEqual(flags(m), [mode === 'cutout' ? .4 : 0, mode === 'blend', mode === 'blend' ? .35 : 1,
        mode === 'cutout' ? THREE.DoubleSide : THREE.FrontSide, mode !== 'blend', null]);
      assert.equal(m.userData.alphaMode,mode);
      const urls = requests.slice(before).map(r=>r.url.split('/').at(-1));
      assert.equal(urls.includes('opacity.png'),mode !== 'opaque');
      if (tier === 'low') assert.deepEqual(urls.sort(),mode === 'opaque' ? ['base_color.png'] : ['base_color.png','opacity.png']);
      m.dispose();
    }
  } finally { hold = false; }
});
await test('opaque_entry_is_unchanged', async () => {
  modes(); assert.equal(lib.alphaModeOf(undefined,{}),'opaque');
  for (const tier of ['low','high']) for (const params of [{},{alpha_mode:'opaque',opacity:.2,alpha_cutoff:.7}]) {
    const kit = make('opaque-'+tier+'-'+Object.keys(params).length,params,{
      ...Object.fromEntries(['base_color','normal','roughness'].map(slot=>[slot,`materials/opaque-${tier}-${Object.keys(params).length}/${slot}.png`]))}), ref = kit.materials.floor;
    lib.refreshMaterials([ref.id]); const start = requests.length;
    const a = await ready(lib.kitMaterial('floor',kit,tier));
    const newRequests = requests.slice(start).map(r=>r.url);
    legacy.refreshMaterials([ref.id]); const middle = requests.length;
    const b = await ready(legacy.kitMaterial('floor',kit,tier));
    assert.deepEqual(newRequests,requests.slice(middle).map(r=>r.url));
    assert.equal(newRequests.length,tier === 'low' ? 1 : 3);
    assert.deepEqual(flags(a),flags(b));
    assert.equal(lib.materialKey(ref,'floor',tier,kit.manifest),legacy.materialKey(ref,'floor',tier,kit.manifest));
    const keys = ['opaque','cutout','blend'].map(mode=>lib.materialKey(ref,'floor',tier,
      {[ref.id]:{...kit.manifest[ref.id],params:{alpha_mode:mode}}}));
    assert.equal(new Set(keys).size,3); a.dispose(); b.dispose();
  }
  const m = new THREE.MeshStandardMaterial();
  for (const mode of ['blend','cutout','opaque']) {
    const kit = make('reset',{alpha_mode:mode,opacity:.35,alpha_cutoff:.4});
    lib.applyMaterialParams(m,kit.manifest.reset,kit.materials.floor,'floor','low');
  }
  assert.deepEqual(flags(m),flags(new THREE.MeshStandardMaterial())); m.dispose();
});
await test('lattice_keeps_its_look', async () => {
  modes();
  const kit = {materials:{lattice:{pattern:'lattice',color:'#f4f3ef'}},manifest:{}};
  for (const tier of ['low','high']) {
    const a = lib.kitMaterial('lattice',kit,tier), b = legacy.kitMaterial('lattice',kit,tier);
    assert.equal(a.alphaTest,b.alphaTest); assert.equal(a.side,b.side);
    assert.deepEqual(a.alphaMap.image,b.alphaMap.image); assert.equal(a.userData.alphaMode,'cutout');
    assert.equal(lib.alphaModeOf({params:{alpha_mode:'blend'}},kit.materials.lattice),'cutout');
    // Lattice keys already encode the pattern and must retain their old bytes.
    assert.equal(lib.materialKey(kit.materials.lattice,'lattice',tier,{}),legacy.materialKey(kit.materials.lattice,'lattice',tier,{}));
    a.dispose(); b.dispose();
  }
  for (const alpha_mode of ['opaque','cutout','blend']) {
    const ref={id:'lattice-record',pattern:'lattice',color:'#f4f3ef'};
    const manifest={'lattice-record':{household:true,revision:2,params:{alpha_mode}}};
    assert.equal(lib.materialKey(ref,'lattice','high',manifest),legacy.materialKey(ref,'lattice','high',manifest));
  }
  const kit2 = make('household-lattice',{alpha_mode:'blend',alpha_cutoff:.2},
    {opacity:'materials/household-lattice/opacity.png'});
  kit2.materials.floor.pattern = 'lattice';
  const m = await ready(lib.kitMaterial('floor',kit2,'low'));
  assert.equal(m.userData.alphaMode,'cutout'); assert.equal(m.alphaTest,.5);
  assert.equal(m.alphaMap.image.width,128); assert.equal(m.alphaMap.image.height,128); m.dispose();
});
await test('styled_fade_copies_cutout_values_without_replacing_the_fade', async () => {
  const source=await ready(lib.kitMaterial('floor',make('styled-cutout',
    {alpha_mode:'cutout',alpha_cutoff:.3},{opacity:'materials/styled-cutout/opacity.png'}),'low'));
  const target=new THREE.MeshStandardMaterial({transparent:true,opacity:.18,depthWrite:false});
  target.userData.styledFade=true;lib.copyMaterialParams(source,target);
  assert.deepEqual([target.transparent,target.opacity,target.depthWrite],[true,.18,false]);
  assert.equal(target.alphaTest,.3);assert.equal(target.alphaMap,source.alphaMap);assert.equal(target.side,THREE.DoubleSide);
  assert.equal(target.userData.alphaMode,'cutout');assert.equal(target.userData.styledFade,true);
  target.dispose();source.dispose();
});
await test('copy_carries_mode_between_instances', async () => {
  const source = await ready(lib.kitMaterial('floor',make('copy',{alpha_mode:'blend',opacity:.35}),'high'));
  const target = new THREE.MeshStandardMaterial(); lib.copyMaterialParams(source,target);
  assert.equal(target.transparent,true); assert.equal(target.opacity,.35); assert.equal(target.depthWrite,false);
  assert.equal(target.userData.alphaMode,'blend');
  const viewing = new THREE.MeshStandardMaterial({transparent:true,opacity:.1,depthWrite:true});
  viewing.userData.viewingOpaque = true; lib.copyMaterialParams(source,viewing);
  assert.equal(viewing.transparent,true); assert.equal(viewing.opacity,.1); assert.equal(viewing.depthWrite,true);
  assert.equal(viewing.userData.viewingOpaque,true,'copy retains the viewing clone classification');
  assert.equal(viewing.userData.viewingOpacity,.35); assert.equal(viewing.userData.viewingDepthWrite,false);
  // Exercise the real viewing owner: a hidden upper floor must stay hidden
  // during refresh, then restore the new source opacity when shown again.
  const {createViewing} = await import(file('static/twin/viewing.js'));
  const root = new THREE.Group(), groups = {levels:{}};
  for (const id of ['roof','gableFull','gableCut','site']) { groups[id] = new THREE.Group(); root.add(groups[id]); }
  const outline = [[0,0],[10,0],[10,10],[0,10]];
  const levels = [0,10].map((elevation,i)=>({id:'L'+(i+1),elevation,ceiling:10,outline}));
  const meshes = levels.map(l=>{
    const group = new THREE.Group(); group.userData.levelKey = 'house:'+l.id;
    groups.levels['house:'+l.id] = group; root.add(group);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(1,1,1),source); group.add(mesh); return mesh;
  });
  const view = {plan:{buildings:[{id:'house',levels,walls:[],position:[0,0]}]},
    camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},roomLights:[],renderer3:{shadowMap:{}}};
  view.camera.position.set(0,50,50);
  const owner = createViewing(view,{root,groups},()=>0,()=>{}, {explicit:true});
  owner.select('house:L1'); owner.update(0); owner.update(300);
  assert.equal(meshes[1].material.opacity,0);
  source.opacity = .7; owner.refresh(source);
  assert.equal(meshes[0].material.opacity,.7); assert.equal(meshes[0].material.depthWrite,false);
  assert.equal(meshes[1].material.opacity,0,'refresh retains the upper floor fade');
  owner.select('ext'); owner.update(600); owner.update(900);
  assert.equal(meshes[1].material.opacity,.7,'viewing restores the refreshed source opacity');
  assert.equal(meshes[1].material.depthWrite,false);
  // The bake runtime adopts a clone of a viewing clone, then refreshes it.
  const adopted=meshes[0].material.clone(); owner.adopt(meshes[0].material,adopted);
  source.opacity=.8; source.color.set('#abc123'); source.roughness=.2;
  source.userData.materialRevision=8; owner.refresh(source);
  assert.equal(adopted.opacity,.8); assert.equal(adopted.depthWrite,false);
  assert.equal(adopted.color.getHexString(),'abc123');assert.equal(adopted.roughness,.2);
  assert.equal(adopted.userData.materialRevision,8);
  owner.dispose(); lib.disposeObject(root);
  source.dispose(); target.dispose(); viewing.dispose();
});
await test('viewing_cutout_keeps_alpha_test', async () => {
  const {createViewing}=await import(file('static/twin/viewing.js'));
  const source=lib.kitMaterial('floor',make('view-cutout',{alpha_mode:'cutout',alpha_cutoff:.4}),'low');
  const root=new THREE.Group(), groups={levels:{}};
  for(const id of ['roof','gableFull','gableCut','site']){groups[id]=new THREE.Group();root.add(groups[id]);}
  const group=new THREE.Group();groups.levels['b:L1']=group;root.add(group);
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(),source);group.add(mesh);
  const view={plan:{buildings:[{id:'b',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:10,outline:[[0,0],[10,0],[10,10],[0,10]]}],walls:[]}]},
    camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},roomLights:[],renderer3:{shadowMap:{}}};
  const owner=createViewing(view,{root,groups},()=>0,()=>{},{explicit:true});
  assert.equal(mesh.material.alphaTest,.4);assert.equal(mesh.material.userData.viewingOpaque,true);
  source.alphaTest=.7;owner.refresh(source);assert.equal(mesh.material.alphaTest,.7);
  owner.dispose();lib.disposeObject(root);
});
await test('builtin_looks_equal_todays_materials', async () => {
  const {builtinMaterial} = await import(file('static/twin/surface_kinds.js'));
  const {buildTwin} = await import(mainURL('static/twin/twin_generator.js'));
  const {buildYard} = await import(mainURL('static/twin/twin_yard.js'));
  const twin = buildTwin(input.plan,input.kit,'low'); await twin.ready;
  const yard = await buildYard({buildings:[],site:{pool:{polygon:[[0,0],[10,0],[10,10],[0,10]],depth:4}}},input.kit,'low');
  for (const id of ['glass','screen','water']) {
    let old; (id === 'water' ? yard.group : twin.root).traverse(o=>{
      if (o.material?.name === id) old = o.material;
    });
    assert.ok(old,'baseline draws '+id); const m = builtinMaterial(id);
    assert.deepEqual(look(m),look(old)); assert.ok(!(m.transmission > 0)); m.dispose();
  }
  lib.disposeObject(twin.root); lib.disposeObject(yard.group);
});
await test('slot_naming_a_builtin_resolves', async () => {
  const {builtinMaterial} = await import(file('static/twin/surface_kinds.js'));
  const cache = new Map(), fallback = () => { throw Error('builtin must not fall back to kit'); };
  for (const id of ['glass','screen','water']) {
    const m = lib.materialSlot({id},id,{},'low',cache,fallback), expected = builtinMaterial(id);
    assert.deepEqual(look(m),look(expected));
    assert.equal(lib.materialSlot({id},id,{},'low',cache,fallback),m);
    const tinted = lib.materialSlot({id,color:'#ff0011'},'pane',{},'low',cache,fallback);
    assert.equal(tinted.color.getHexString(),'ff0011'); assert.equal(tinted.name,'pane');
    assert.equal(m.color.getHexString(),expected.color.getHexString()); expected.dispose();
  }
  for (const m of cache.values()) m.dispose();
});
finish();
"""

if __name__ == '__main__':
    import json
    paths = ['static/twin/' + name for name in ['twin_library.js', 'twin_generator.js', 'twin_yard.js']]
    sources = {path: subprocess.check_output(['git', 'show', '49d96582:chauffeur/' + path],
               cwd=ROOT, encoding='utf-8') for path in paths}
    plan = {'buildings': [{'id': 'house', 'position': [0, 0],
            'levels': [{'id': 'L1', 'elevation': 0, 'ceiling': 9}],
            'walls': [{'id': 'wall', 'level': 'L1', 'from': [0, 0], 'to': [10, 0],
                       'height': 9, 'thickness': .5, 'exterior': True}],
            'rooms': [], 'openings': [{'id': 'window', 'wall': 'wall', 'level': 'L1',
                       'kind': 'window', 'at': 2, 'width': 4, 'sill': 3, 'head': 7}],
            'porches': [{'id': 'porch', 'floor': 0, 'screened': True,
                         'polygon': [[0, -6], [10, -6], [10, 0], [0, 0]]}]}], 'materials': {}, 'site': {}}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'mainSources': sources,
                                    'plan': plan, 'kit': {'materials': {}, 'manifest': {}}})
    print(output)
    sys.exit(code or 0)
