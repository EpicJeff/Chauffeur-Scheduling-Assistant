"""Household PBR rendering under Node with the real vendored three materials.

Only image transport and canvas drawing are doubled; no browser or packages.
Built-in snapshot captured from main f87f43e06417cd5cde583215f0587a91c3f21895
(kitMaterial, kit and manifest), before implementing household rendering.
"""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_SNAPSHOT = json.loads(r'''{
"low:siding": {"color":"#c3c6c2","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:trim": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:lattice": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":["generated lattice: 1.5in strips / 4in centres",[2.1213203435596424,2.1213203435596424]],"alphaTest":0.5,"side":2,"shader":null},
"low:window_frame": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:roof": {"color":"#3a2e27","roughness":0.45,"metalness":0.45,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:porch_ceiling": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:base": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/stacked_stone_wall/stacked_stone_wall_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:door": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/mocha_oak_veneer/mocha_oak_veneer_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:floor": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_floor/wood_floor_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:interior_wall": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/white_plaster_02/white_plaster_02_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:paving": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/stone_tiles/stone_tiles_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:lawn": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/leafy_grass/leafy_grass_diff_1k.jpg",[0.125,0.125]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:mulch": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/yellow_flower_mulch/yellow_flower_mulch_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:fence": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_planks/wood_planks_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:counter": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/granite_tile/granite_tile_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:stainless": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/metal_plate/metal_plate_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:porch_brick": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/red_brick_03/red_brick_03_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:granite": {"color":"#3b3d40","roughness":0.22,"metalness":0,"maps":[["/api/house/twin/library/granite_tile/granite_tile_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":"granite-neutral-light-1"},
"low:retaining_block": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/concrete_floor_02/concrete_floor_02_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:retaining_timber": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_planks/wood_planks_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"low:patio_concrete": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/concrete_floor_02/concrete_floor_02_diff_1k.jpg",[0.25,0.25]],null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:siding": {"color":"#c3c6c2","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:trim": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:lattice": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":["generated lattice: 1.5in strips / 4in centres",[2.1213203435596424,2.1213203435596424]],"alphaTest":0.5,"side":2,"shader":null},
"medium:window_frame": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:roof": {"color":"#3a2e27","roughness":0.45,"metalness":0.45,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:porch_ceiling": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:base": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/stacked_stone_wall/stacked_stone_wall_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stacked_stone_wall/stacked_stone_wall_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stacked_stone_wall/stacked_stone_wall_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:door": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/mocha_oak_veneer/mocha_oak_veneer_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/mocha_oak_veneer/mocha_oak_veneer_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/mocha_oak_veneer/mocha_oak_veneer_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:floor": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_floor/wood_floor_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_floor/wood_floor_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_floor/wood_floor_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:interior_wall": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/white_plaster_02/white_plaster_02_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/white_plaster_02/white_plaster_02_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/white_plaster_02/white_plaster_02_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:paving": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/stone_tiles/stone_tiles_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stone_tiles/stone_tiles_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stone_tiles/stone_tiles_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:lawn": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/leafy_grass/leafy_grass_diff_1k.jpg",[0.125,0.125]],["/api/house/twin/library/leafy_grass/leafy_grass_nor_gl_1k.jpg",[0.125,0.125]],["/api/house/twin/library/leafy_grass/leafy_grass_rough_1k.jpg",[0.125,0.125]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:mulch": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/yellow_flower_mulch/yellow_flower_mulch_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/yellow_flower_mulch/yellow_flower_mulch_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/yellow_flower_mulch/yellow_flower_mulch_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:fence": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_planks/wood_planks_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:counter": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/granite_tile/granite_tile_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:stainless": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/metal_plate/metal_plate_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/metal_plate/metal_plate_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/metal_plate/metal_plate_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:porch_brick": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/red_brick_03/red_brick_03_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/red_brick_03/red_brick_03_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/red_brick_03/red_brick_03_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:granite": {"color":"#3b3d40","roughness":0.22,"metalness":0,"maps":[["/api/house/twin/library/granite_tile/granite_tile_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":"granite-neutral-light-1"},
"medium:retaining_block": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/concrete_floor_02/concrete_floor_02_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:retaining_timber": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_planks/wood_planks_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"medium:patio_concrete": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/concrete_floor_02/concrete_floor_02_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:siding": {"color":"#c3c6c2","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:trim": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:lattice": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":["generated lattice: 1.5in strips / 4in centres",[2.1213203435596424,2.1213203435596424]],"alphaTest":0.5,"side":2,"shader":null},
"high:window_frame": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:roof": {"color":"#3a2e27","roughness":0.45,"metalness":0.45,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:porch_ceiling": {"color":"#f4f3ef","roughness":0.85,"metalness":0,"maps":[null,null,null],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:base": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/stacked_stone_wall/stacked_stone_wall_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stacked_stone_wall/stacked_stone_wall_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stacked_stone_wall/stacked_stone_wall_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:door": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/mocha_oak_veneer/mocha_oak_veneer_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/mocha_oak_veneer/mocha_oak_veneer_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/mocha_oak_veneer/mocha_oak_veneer_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:floor": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_floor/wood_floor_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_floor/wood_floor_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_floor/wood_floor_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:interior_wall": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/white_plaster_02/white_plaster_02_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/white_plaster_02/white_plaster_02_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/white_plaster_02/white_plaster_02_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:paving": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/stone_tiles/stone_tiles_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stone_tiles/stone_tiles_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/stone_tiles/stone_tiles_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:lawn": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/leafy_grass/leafy_grass_diff_1k.jpg",[0.125,0.125]],["/api/house/twin/library/leafy_grass/leafy_grass_nor_gl_1k.jpg",[0.125,0.125]],["/api/house/twin/library/leafy_grass/leafy_grass_rough_1k.jpg",[0.125,0.125]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:mulch": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/yellow_flower_mulch/yellow_flower_mulch_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/yellow_flower_mulch/yellow_flower_mulch_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/yellow_flower_mulch/yellow_flower_mulch_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:fence": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_planks/wood_planks_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:counter": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/granite_tile/granite_tile_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:stainless": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/metal_plate/metal_plate_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/metal_plate/metal_plate_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/metal_plate/metal_plate_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:porch_brick": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/red_brick_03/red_brick_03_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/red_brick_03/red_brick_03_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/red_brick_03/red_brick_03_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:granite": {"color":"#3b3d40","roughness":0.22,"metalness":0,"maps":[["/api/house/twin/library/granite_tile/granite_tile_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/granite_tile/granite_tile_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":"granite-neutral-light-1"},
"high:retaining_block": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/concrete_floor_02/concrete_floor_02_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:retaining_timber": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/wood_planks/wood_planks_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/wood_planks/wood_planks_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null},
"high:patio_concrete": {"color":"#ffffff","roughness":0.85,"metalness":0,"maps":[["/api/house/twin/library/concrete_floor_02/concrete_floor_02_diff_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_nor_gl_1k.jpg",[0.25,0.25]],["/api/house/twin/library/concrete_floor_02/concrete_floor_02_rough_1k.jpg",[0.25,0.25]]],"alpha":null,"alphaTest":0,"side":0,"shader":null}
}''')
SETUP = r"""
const THREE = await import('three');
const requests = [], failures = new Set(), held = new Map();
let hold = false, draws = 0;
THREE.TextureLoader.prototype.load = function(url, done, progress, error) {
  requests.push(url);
  const texture = new THREE.Texture({width:4096,height:2048,url}); texture.name = url;
  const complete = () => failures.has(url) ? error(new Error('image failed')) : done(texture);
  if (hold) held.set(url, complete); else queueMicrotask(complete);
  return texture;
};
Element.prototype.getContext = function() { return {drawImage: image => {draws++;this.sourceUrl=image.url;}}; };
const hex = m => '#' + m.color.getHexString();
const properties = ['map','normalMap','roughnessMap','metalnessMap','aoMap'];
const snapshot = m => ({color:hex(m),roughness:m.roughness,metalness:m.metalness,
  maps:properties.slice(0,3).map(p=>m[p] ? [m[p].name,m[p].repeat.toArray()] : null),
  alpha:m.alphaMap ? [m.alphaMap.name,m.alphaMap.repeat.toArray()] : null,
  alphaTest:m.alphaTest,side:m.side,shader:m.name==='granite'?m.customProgramCacheKey():null});
const params = {tint:'#789abc',roughness:.62,metalness:.27,normal_scale:1.7,
  normal_convention:'dx',ao_intensity:1.4,tile_ft:[6,3],rotation_deg:90,random_offset:false};
const entry = (id='material-test',slots=['base_color','normal','roughness','metalness','ao','height']) => ({
  kind:'material',household:true,revision:7,
  maps:Object.fromEntries(slots.map(s=>[s,`materials/${id}/maps/${s}.${s==='base_color'?'jpg':'png'}`])),
  params:{...params}});
const kitFor = (id,e,role='interior_wall',ref={}) => ({materials:{[role]:{asset:id,...ref}},manifest:{[id]:e}});
const ready = async m => {await m.userData.ready;return m;};
"""
PREFIX = '\n'.join(line for line in PRELUDE.splitlines() if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url:data(`import {Group} from '${three}'; export class Tree extends Group {}`),shortCircuit:true};
  if (spec === 'three')""")
DRIVER = PREFIX + SETUP + r"""
const library = await import(file('static/twin/twin_library.js'));
const {kitMaterial,materialSlot,libUrl,materialKey,applyMaterialParams} = library;
await test('builtin_materials_unchanged',async()=>{
  // Literal main snapshot; the test never reads main or recomputes expectations.
  const got={};
  for(const tier of ['low','medium','high'])for(const role of Object.keys(input.kit.materials)){
    const m=await ready(kitMaterial(role,input.kit,tier));got[tier+':'+role]=snapshot(m);m.dispose();
  }
  assert.deepEqual(got,input.builtinSnapshot);
});
await test('household_maps_and_params_applied',async()=>{
  const e=entry(),m=await ready(kitMaterial('interior_wall',kitFor('material-test',e),'high'));
  for(const [property,slot] of properties.map((p,i)=>[p,['base_color','normal','roughness','metalness','ao'][i]])){
    assert.ok(m[property],property);
    assert.ok(requests.includes('/api/house/twin/'+e.maps[slot]),slot+' URL');
    assert.equal(m[property].name,'/api/house/twin/'+e.maps[slot],property+' uses its own slot');
    assert.deepEqual(m[property].repeat.toArray(),[1/6,1/3]);
    assert.equal(m[property].rotation,Math.PI/2);assert.equal(m[property].channel,0);
    assert.equal(m[property].colorSpace,property==='map'?THREE.SRGBColorSpace:THREE.NoColorSpace);
  }
  assert.deepEqual(m.normalScale.toArray(),[1.7,-1.7]);assert.equal(m.aoMapIntensity,1.4);
  assert.equal(m.roughness,.62);assert.equal(m.metalness,.27);assert.equal(hex(m),'#789abc');
  assert.equal(m.displacementMap,null,'height is stored only');
  assert.ok(!requests.some(u=>u.endsWith('/height.png')));
  m.dispose();
});
await test('orm_shares_one_texture',async()=>{
  const e=entry('material-orm',['base_color','normal','roughness','metalness','ao','orm']);
  const before=requests.length,m=await ready(kitMaterial('roof',kitFor('material-orm',e,'roof'),'medium'));
  assert.ok(m.aoMap);assert.equal(m.roughnessMap,m.metalnessMap);assert.equal(m.aoMap,m.metalnessMap);
  assert.ok(requests.slice(before).some(u=>u.endsWith('/orm.png')));
  assert.ok(!requests.slice(before).some(u=>/\/(roughness|metalness|ao)\.png$/.test(u)));
  assert.equal(m.metalness,.27,'household multiplier also applies on roofs');m.dispose();
});
await test('low_tier_base_colour_only',async()=>{
  const e=entry('material-low'),before=requests.length;
  const m=await ready(kitMaterial('interior_wall',kitFor('material-low',e),'low'));
  assert.ok(m.map);for(const p of properties.slice(1))assert.equal(m[p],null);
  assert.deepEqual(requests.slice(before),['/api/house/twin/'+e.maps.base_color]);
  assert.deepEqual([m.map.image.width,m.map.image.height],[512,256]);m.dispose();
});
await test('slot_color_replaces_tint',async()=>{
  const e=entry('material-color'),kit=kitFor('material-color',e),cache=new Map();
  const get=value=>materialSlot(value,'interior_wall',kit,'high',cache,()=>{throw Error('household routed to built-in role');});
  const plain=await ready(get({id:'material-color'})),tinted=await ready(get({id:'material-color',color:'#123456'}));
  assert.equal(hex(plain),'#789abc');assert.equal(hex(tinted),'#123456');assert.notEqual(plain,tinted);
  assert.equal(get({id:'material-color'}),plain,'same role and ref share one draw state');
  plain.dispose();tinted.dispose();
});
await test('same_material_two_roles_two_instances',async()=>{
  const e=entry('material-roles',[]),kit=kitFor('material-roles',e),cache=new Map();
  const a=materialSlot({id:'material-roles'},'roof',kit,'high',cache,()=>{});
  const b=materialSlot({id:'material-roles'},'interior_wall',kit,'high',cache,()=>{});
  assert.notEqual(a,b);assert.equal(a.name,'roof');assert.equal(b.name,'interior_wall');
  a.dispose();b.dispose();
});
await test('id_only_household_role_uses_tint_in_building_and_yard',async()=>{
  const {buildTwin}=await import(file('static/twin/twin_generator.js'));
  const {buildYard}=await import(file('static/twin/twin_yard.js'));
  const id='material-builder',e=entry(id,[]),kit={...input.kit,manifest:{[id]:e}};
  const plan=structuredClone(input.plan);plan.materials={roof:{id}};
  plan.buildings[0].roof={sections:[{id:'roof',kind:'shed',rect:[0,0,10,10],plate:12,pitch:2,overhang:0,low_side:'y0'}]};
  const building=buildTwin(plan,kit,'high');await building.ready;
  const roof=[...building.materials.values()].find(m=>m.name==='roof');assert.ok(roof);
  assert.equal(hex(roof),params.tint,'id-only building role does not inherit the kit tint');
  const yard=await buildYard({buildings:[],materials:{fence:{id}},site:{fence:[{polyline:[[0,0],[2,0]],height:3}]}},kit,'high');
  const fence=[...yard.group.userData.materials.values()].find(m=>m.name==='fence');assert.ok(fence);
  assert.equal(hex(fence),params.tint,'id-only yard role does not inherit the kit tint');
  for(const m of [...building.materials.values(),...yard.group.userData.materials.values()])m.dispose();
});
await test('revision_changes_key',async()=>{
  assert.equal(typeof materialKey,'function');
  const id='material-revision',e=entry(id,[]),kit=kitFor(id,e),value={id},cache=new Map();
  const key=materialKey(value,'roof','high',kit.manifest);
  assert.equal(key,JSON.stringify(['m',id,7,'high','roof',null,['roof']]));
  for(const [role,flags]of [['granite',['granite']],['lattice',['lattice']],['interior_wall',[]]])
    assert.deepEqual(JSON.parse(materialKey({...value,...(role==='lattice'?{pattern:'lattice'}:{})},role,'high',kit.manifest)).at(-1),flags);
  const first=materialSlot(value,'roof',kit,'high',cache,()=>{});e.revision++;
  assert.notEqual(materialKey(value,'roof','high',kit.manifest),key);
  const second=materialSlot(value,'roof',kit,'high',cache,()=>{});assert.notEqual(first,second);
  assert.notEqual(materialKey(value,'roof','low',kit.manifest),materialKey(value,'roof','high',kit.manifest));
  first.dispose();second.dispose();
});
await test('lib_url_ingress_auth_and_encoded_paths',()=>{
  const saved=window.chfBase;window.chfBase='/ingress/token/';window.chfAuthUrl=u=>u+'?auth=ok';
  try{
    assert.equal(libUrl('material a','materials/material a/maps/base color.jpg'),'/ingress/token/api/house/twin/materials/material%20a/maps/base%20color.jpg?auth=ok');
    assert.equal(libUrl('import-a','a b.glb'),'/ingress/token/api/house/twin/imports/import-a/a%20b.glb?auth=ok');
    assert.equal(libUrl('stone','a b.jpg'),'/ingress/token/api/house/twin/library/stone/a%20b.jpg?auth=ok');
  }finally{window.chfBase=saved;delete window.chfAuthUrl;}
});
await test('tier_caps_and_downsample_cache',async()=>{
  const id='material-caps',e=entry(id,['base_color']),kit=kitFor(id,e);
  for(const [tier,cap]of [['low',512],['medium',1024],['high',2048]]){
    const before=draws,a=await ready(kitMaterial('interior_wall',kit,tier)),b=await ready(kitMaterial('interior_wall',kit,tier));
    assert.ok(a.map);assert.deepEqual([a.map.image.width,a.map.image.height],[cap,cap/2]);
    assert.equal(draws-before,1,'downsample once per URL/tier');assert.notEqual(a.map,b.map);
    assert.equal(a.map.image,b.map.image,'the decoded tier image is shared');a.dispose();b.dispose();
  }
  assert.equal(requests.filter(u=>u.endsWith('/material-caps/maps/base_color.jpg')).length,1,'decode master once');
});
await test('preview_helper_params_defaults_and_gl_normals',async()=>{
  assert.equal(typeof applyMaterialParams,'function');
  const m=new THREE.MeshStandardMaterial(),e=entry('material-preview',['normal']);e.params.normal_convention='gl';
  assert.equal(applyMaterialParams(m,e,{color:'#abcdef'},'interior_wall','high'),m);
  await ready(m);assert.equal(m.name,'interior_wall');assert.equal(hex(m),'#abcdef');
  assert.deepEqual(m.normalScale.toArray(),[1.7,1.7]);
  assert.equal(m.roughness,.62,'spec: scalar is kept even without a roughness map');m.dispose();
  const plain=new THREE.MeshStandardMaterial();applyMaterialParams(plain,{maps:{},params:{}},{},'roof','low');
  await ready(plain);assert.equal(hex(plain),'#ffffff');assert.equal(plain.roughness,1);assert.equal(plain.metalness,1);plain.dispose();
});
await test('dispose_releases_owned_maps_and_blocks_late_assignment',async()=>{
  const id='material-dispose',e=entry(id,['orm']),m=await ready(kitMaterial('roof',kitFor(id,e,'roof'),'high'));
  assert.ok(m.aoMap);let disposed=0;m.aoMap.addEventListener('dispose',()=>disposed++);m.dispose();
  assert.equal(disposed,1,'ORM is disposed once');
  hold=true;
  const late=kitMaterial('interior_wall',kitFor('material-late',entry('material-late',['base_color'])),'high');
  late.dispose();hold=false;for(const complete of held.values())complete();held.clear();await ready(late);
  assert.equal(late.map,null,'a disposed material cannot acquire a late texture');
});
await test('failed_map_does_not_poison_future_loads',async()=>{
  const id='material-failure',e=entry(id,['base_color']),url='/api/house/twin/'+e.maps.base_color;
  failures.add(url);const m=await ready(kitMaterial('interior_wall',kitFor(id,e),'high'));
  assert.equal(m.map,null);assert.equal(hex(m),params.tint);m.dispose();failures.delete(url);
  const retry=await ready(kitMaterial('interior_wall',kitFor(id,e),'high'));assert.ok(retry.map);retry.dispose();
});
finish();
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = json.loads((ROOT / 'twin_library/manifest.json').read_text(encoding='utf-8'))
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit, 'plan': plan, 'builtinSnapshot': BUILTIN_SNAPSHOT})
    print(output)
    sys.exit(code or 0)
