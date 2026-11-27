"""Per-copy part texture controls run through the shared slot-row builder."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {drawObjectShelf}=await import(file('static/twin/editor/object_shelf.js'));
const {rememberImport}=await import(file('static/twin/twin_library.js'));
const {resolvePart}=await import(file('static/twin/model_parts.js'));
window.twinObjectSchema=input.schema;
const asset='import-copy-textures';
const parts=[{key:'Wood',name:'Wood',has_uv:true},{key:'Glass',name:'Glass',has_uv:false}];
const model={id:asset,revision:1,parts,parts_version:1,materials:{Wood:{material:'oak',texture:'model',tiles:2}}};
rememberImport(model);
globalThis.fetch=async url=>{throw Error('unexpected request '+url);};
const copies=[{id:'a',asset,at:[0,0],model_materials:{Glass:{material:'original'}}},{id:'b',asset,at:[1,1]}];
let selected={id:'oak',kind:'material',name:'Oak'};const listeners=new Set(),ops=[];
const library={selected:()=>selected,onSelect:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},reveal:async()=>{}};
const slots=[],host=document.createElement('div');document.body.append(host);
drawObjectShelf(host,{kind:'item',piece:copies[0],building:{id:'b'}},{getRecord:()=>({kind:'item',piece:copies[0],building:{id:'b'}}),
 canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async o=>{ops.push(o);Object.assign(copies[0],o.properties);},
 library,ownSlot:s=>slots.push(s),report:e=>{throw e;}});
await new Promise(r=>setTimeout(r,25));
const wood=host.querySelector('[data-model-part="Wood"]'),glass=host.querySelector('[data-model-part="Glass"]');
const mode=wood.querySelector('[data-slot-texture]'),tiles=wood.querySelector('[data-slot-tiles]');
await test('inherited_texture_is_visible_read_only',async()=>{
 assert.ok(mode);assert.equal(mode.value,'model');assert.equal(mode.disabled,true);assert.equal(tiles.value,'2');assert.equal(tiles.disabled,true);
 assert.match(textOf(wood),/texture.*model.*Library/i);assert.equal(ops.length,0);
});
await test('explicit_copy_material_allows_model_uv_and_tiles_without_changing_other_copy',async()=>{
 await click(wood.querySelector('[data-slot-use]'));
 assert.equal(mode.disabled,false);assert.equal(mode.value,'real');assert.equal(tiles.parentElement.hidden,true);
 mode.value='model';await fire(mode,'change');
 assert.equal(tiles.parentElement.hidden,false);tiles.value='3';await fire(tiles,'change');
 assert.deepEqual(ops.at(-1),{op:'set_object',building:'b',id:'a',properties:{model_materials:{Glass:{material:'original'},Wood:{material:'oak',texture:'model',tiles:3}}}});
 assert.equal(copies[1].model_materials,undefined);assert.deepEqual(model.materials.Wood,{material:'oak',texture:'model',tiles:2});
 assert.deepEqual(resolvePart(parts[0],model.materials,copies[0].model_materials),{source:'copy',material:'oak',texture:'model',tiles:3});
 mode.value='real';await fire(mode,'change');
 assert.deepEqual(ops.at(-1).properties.model_materials.Wood,{material:'oak',texture:'real'},'Real size sends no tiles, as required by the server');
 assert.equal(tiles.parentElement.hidden,true);
 mode.value='real';await fire(mode,'change');
 assert.deepEqual(ops.at(-1).properties.model_materials.Wood,{material:'oak',texture:'real'},'Real size must omit tiles for server validation');
 assert.equal(tiles.parentElement.hidden,true);
 await click(wood.querySelector('[data-slot-clear]'));assert.equal(ops.at(-1).properties.model_materials.Wood,undefined);
 assert.deepEqual(ops.at(-1).properties.model_materials.Glass,{material:'original'});
 assert.equal(mode.disabled,true);assert.equal(mode.value,'model');assert.equal(tiles.value,'2');
});
await test('parts_without_uv_disable_models_own_and_original_rows_disable_texture_edits',async()=>{
 const mode=glass.querySelector('[data-slot-texture]');assert.equal(mode.disabled,true);
 await click(glass.querySelector('[data-slot-use]'));assert.equal(mode.disabled,false);
 assert.equal(mode.querySelectorAll('option').find(o=>o.value==='model').disabled,true);
 assert.equal(glass.querySelector('[data-slot-tiles]').parentElement.hidden,true);
 await click(glass.querySelector('[data-slot-reset]'));assert.equal(mode.disabled,true);
});
slots.forEach(s=>s.dispose());finish();
"""

if __name__ == '__main__':
    import json
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(),
        'schema': json.loads((ROOT / 'static/twin/object_schema.json').read_text())})
    print(output)
    sys.exit(code)
