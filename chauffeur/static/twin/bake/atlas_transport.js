import * as THREE from '../../vendor/three-r187/three.module.js';
import { packBanks, fingerprint } from './atlas.js';

export function covered(root) {
  const meshes = [];
  root.traverse(m => {
    if (m.isMesh && m.userData.merged && !m.layers.isEnabled(31) && !Array.isArray(m.material) &&
      !m.material.transparent && m.material.name !== 'fixture' && m.geometry?.attributes.position) meshes.push(m);
  });
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
  root.updateMatrixWorld(true);
  const meshes = covered(root).map(m => {
    let buildingId;
    for (let p = m; p && !buildingId; p = p.parent) buildingId = p.userData.buildingId;
    return { geometry: geometryData(m.geometry), matrix: m.matrixWorld.toArray(), name: m.material.name, buildingId };
  });
  const hash = fingerprint();
  // Geometry and room outlines drive the cache. Device movement does not.
  hash.add('atlas-worker-2'); hash.add(JSON.stringify([layout, plan.generatorVersion, plan.buildings?.map(b => ({
    id: b.id, rooms: b.rooms, levels: b.levels }))]));
  for (const m of meshes) {
    hash.add(JSON.stringify([m.matrix, m.name, m.buildingId]));
    for (const [name, a] of Object.entries(m.geometry.attributes)) { hash.add(name); hash.add(a.array); }
    if (m.geometry.index) hash.add(m.geometry.index);
  }
  return { meshes, plan, layout, cacheKey: hash.key() };
}
export function packAtlas(atlas, meshes) {
  const charts = list => list.map(c => ({ ...c, mesh: meshes.indexOf(c.mesh) }));
  return { key: atlas.key, sky: { ...atlas.sky, charts: charts(atlas.sky.charts) },
    room: { pages: atlas.room.pages, rooms: atlas.room.rooms, charts: charts(atlas.room.charts) },
    geometries: meshes.map(m => geometryData(m.geometry)) };
}
export function applyAtlas(data, root, layout) {
  const meshes = covered(root);
  data.geometries.forEach((g, i) => { const old = meshes[i].geometry; meshes[i].geometry = geometryFrom(g); old.dispose(); });
  const charts = list => list.map(c => ({ ...c, mesh: meshes[c.mesh] }));
  const room = { ...data.room, charts: charts(data.room.charts) };
  room.packBanks = lights => packBanks(room, lights, layout.room);
  return { key: data.key, sky: { ...data.sky, charts: charts(data.sky.charts) }, room };
}
