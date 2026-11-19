import * as THREE from '../../vendor/three-r187/three.module.js';
import { packBanks, fingerprint, atlasMesh, heightfieldExtent, prepareReceivers } from './atlas.js';
import { authoredGeometry } from './geometry_key.js';
import { bakeSource } from './source.js';
import { bindReceivers } from './bindings.js';

export function covered(root) {
  const meshes = [];
  root.traverse(m => { if (atlasMesh(m)) meshes.push(m); });
  return meshes;
}
export function geometryData(g) {
  return { attributes: Object.fromEntries(Object.entries(g.attributes).map(([name, a]) =>
    [name, { array: a.array.slice(), itemSize: a.itemSize, normalized: a.normalized }])),
    index: g.index?.array.slice() || null, userData: g.userData };
}
export function geometryFrom(data) {
  const g = new THREE.BufferGeometry();
  for (const [name, a] of Object.entries(data.attributes)) g.setAttribute(name, new THREE.BufferAttribute(a.array, a.itemSize, a.normalized));
  if (data.index) g.setIndex(new THREE.BufferAttribute(data.index, 1));
  g.userData = data.userData; return g;
}
export function buffers(data) {
  const list = [];
  const visit = v => {
    if (!v || typeof v !== 'object') return;
    if (ArrayBuffer.isView(v)) { if (!list.includes(v.buffer)) list.push(v.buffer); }
    else for (const x of Object.values(v)) visit(x);
  };
  visit(data); return list;
}
export function atlasJob(root, plan, layout) {
  const source=bakeSource(root),neutral=source!==root;root=source;
  root.updateMatrixWorld(true);
  const meshes = covered(root).map(m => {
    let buildingId;
    for (let p = m; p && !buildingId; p = p.parent) buildingId = p.userData.buildingId;
    return { geometry: geometryData(m.geometry), matrix: m.matrixWorld.toArray(), name: m.material.name, buildingId };
  });
  const hash = fingerprint(), uvs = fingerprint();
  // Geometry and room outlines drive the cache. Device movement does not.
  hash.add('atlas-worker-reach-12'); hash.add(authoredGeometry(plan)); hash.add(JSON.stringify(layout));
  for (const m of meshes) {
    hash.add(JSON.stringify([m.matrix, m.name, m.buildingId]));
    // Graded terrain's grid is tiered; its shape is authored (lot, terraces): one key per house.
    if (m.geometry.userData?.bakeHeightfield) { hash.add(JSON.stringify(['heightfield', heightfieldExtent(geometryFrom(m.geometry))])); continue; }
    // Base uv is hashed once, into uvKey, which the input key then folds in.
    for (const [name, a] of Object.entries(m.geometry.attributes)) { hash.add(name); if (name !== 'uv') hash.add(a.array); }
    if (m.geometry.index) hash.add(m.geometry.index);
    uvs.add(m.geometry.attributes.uv?.array || new Float32Array(0)); uvs.add('|');
  }
  if(!neutral)hash.add('uv:' + uvs.key());
  // The layout key ignores base uv, but the cached result carries clipped geometry with
  // it: uvKey says which base uv that geometry holds (see loadAtlas).
  return { meshes, plan, layout, cacheKey: hash.key(), uvKey: neutral?'neutral-surface-topology':uvs.key() };
}
export function packAtlas(atlas, meshes) {
  if (atlas.sourceRoot) meshes=atlas.transportMeshes || covered(atlas.sourceRoot);
  const charts = list => list.map(c => ({ ...c, mesh: meshes.indexOf(c.mesh),
    ...(c.proxies ? { proxies: c.proxies.map(p => ({ mesh: meshes.indexOf(p.mesh), faces: p.faces })) } : {}) }));
  return { key: atlas.key,
    room: { pages: atlas.room.pages, rooms: atlas.room.rooms, plan: atlas.room.plan, charts: charts(atlas.room.charts) },
    geometries: meshes.map(m => geometryData(m.geometry)) };
}
export function applyAtlas(data, root, layout) {
  const source=bakeSource(root),meshes = covered(source);
  data.geometries.forEach((g, i) => { const old = meshes[i].geometry; meshes[i].geometry = geometryFrom(g); old.dispose(); });
  const charts = list => list.map(c => ({ ...c, mesh: meshes[c.mesh],
    ...(c.proxies ? { proxies: c.proxies.map(p => ({ mesh: meshes[p.mesh], faces: p.faces })) } : {}) }));
  const room = { ...data.room, charts: charts(data.room.charts) };
  room.packBanks = (lights, slots) => packBanks(room, lights, layout.room, slots);
  const atlas={key:data.key,room};
  if(source!==root){atlas.sourceRoot=source;bindReceivers(atlas,prepareReceivers(root,room.plan));}
  return atlas;
}
