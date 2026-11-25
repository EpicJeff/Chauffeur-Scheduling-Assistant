import * as THREE from 'three';
import { PICK_LAYER } from './twin_generator.js';
import { scaleStyledFadeAlpha } from './twin_library.js';

// Presentation owns materials and draw groups, never receiving topology. Geometry
// may be shared by several objects: save and restore its groups exactly once.
export function createSelectionFocus({ compile, render, failed }) {
  const originals = new Map(), geometries = new Map(), variants = new Map(), warmed = new Set();
  const display = materials => materials.length === 1 ? materials[0] : materials;
  let revision = 0, activeRoot = null, activeKey = null, ready = Promise.resolve();
  function restore() {
    ++revision; activeRoot = activeKey = null;
    for (const [object, base] of originals) {
      object.material = base.material;
      object.removeEventListener('bakepresentationstart', base.beforeBake);
      object.removeEventListener('bakepresentationend', base.afterBake);
    }
    for (const [geometry, base] of geometries) geometry.groups = base.groups;
    originals.clear(); geometries.clear();
  }
  function variant(source, mode, color) {
    if (!mode) return source;
    if (!variants.has(source)) variants.set(source, new Map());
    const cache = variants.get(source), key = `${mode}:${color}`;
    if (cache.has(key)) return cache.get(key);
    const next = source.clone();
    next.onBeforeCompile = source.onBeforeCompile;
    next.customProgramCacheKey = source.customProgramCacheKey;
    next.defaultAttributeValues = source.defaultAttributeValues;
    if (mode === 'ghost') {
      next.userData.styledFade = true; next.opacity = .25;
      next.transparent = true; next.depthWrite = false;
      scaleStyledFadeAlpha(source, next);
    } else {
      next.color?.lerp(new THREE.Color(color), .32); next.userData.selectionTint = color;
    }
    cache.set(key, next); return next;
  }
  function syncMaterials(sync) {
    for (const [source, cache] of variants) for (const material of cache.values()) sync(source, material);
  }
  function apply(root, room, accent, wallTint, { pieces, site } = {}) {
    const key = room && JSON.stringify([room, accent, wallTint]);
    if (root === activeRoot && key === activeKey) return ready;
    restore();
    if (!root || !room) return ready = Promise.resolve();
    activeRoot = root; activeKey = key;
    const stamp = revision, pending = [], warm = new THREE.Group(), warmKeys = new Set();
    const allowed = new Set(room.allowed || []), walls = new Set(room.walls || []), eligible = new Set();
    // Match the original focus scope: registered pieces and the site domain.
    for (const objects of pieces?.values() || []) for (const object of objects) eligible.add(object);
    site?.traverse(object => eligible.add(object));
    const grouped = new Map();
    for (const object of eligible) {
      if (!object.material || !object.geometry || object.layers.isEnabled(PICK_LAYER)) continue;
      let geometry = object.geometry;
      if (!grouped.has(geometry)) grouped.set(geometry, { groups: geometry.groups, baking: 0 });
      let geometryBase = grouped.get(geometry);
      const followGeometry = () => {
        if (geometry === object.geometry) return false;
        const previous = geometry; geometry = object.geometry;
        geometryBase = geometries.get(geometry) || grouped.get(geometry) || { groups: geometry.groups, baking: 0 };
        grouped.set(geometry, geometryBase);
        if (originals.has(object)) {
          geometries.set(geometry, geometryBase);
          if (![...originals.keys()].some(o => o.geometry === previous)) geometries.delete(previous);
        }
        return true;
      };
      let source = object.material;
      const inLevel = () => {
        for (let p = object; p; p = p.parent) if (p.userData.levelKey) return p.userData.levelKey === `${room.building}:${room.level}`;
        return false;
      };
      const mode = data => room.kind === 'level' && inLevel() ? [null, null]
        : data.buildingId === room.building && allowed.has(data.pieceId)
          ? data.pieceId === room.id ? ['tint', accent] : walls.has(data.pieceId) ? ['tint', wallTint] : [null, null]
          : ['ghost', null];
      const partition = () => {
        followGeometry();
        const sources = [].concat(source), baseGroups = geometryBase.groups;
        const ranges = object.userData.snapRanges || geometry.userData.snapRanges || [];
        const count = geometry.index?.count ?? geometry.attributes.position?.count ?? 0;
        const bounds = new Set([0, count]);
        for (const range of [...ranges, ...baseGroups]) {
          bounds.add(Math.max(0, Math.min(count, range.start)));
          bounds.add(Math.max(0, Math.min(count, range.start + range.count)));
        }
        const cuts = [...bounds].sort((a,b) => a-b), groups = [], materials = [], indices = new Map();
        for (let i=0; i<cuts.length-1; i++) {
          const start=cuts[i], length=cuts[i+1]-start;
          if (!length) continue;
          const owner = ranges.find(r => r.start <= start && r.start+r.count > start);
          const group = baseGroups.find(g => g.start <= start && g.start+g.count > start);
          const [style,color] = mode(ranges.length ? owner || {} : object.userData);
          const material = variant(sources[group?.materialIndex ?? 0] || sources[0],style,color);
          if (!indices.has(material)) { indices.set(material,materials.length); materials.push(material); }
          const materialIndex=indices.get(material), last=groups.at(-1);
          if (last?.materialIndex === materialIndex && last.start+last.count === start) last.count += length;
          else groups.push({start,count:length,materialIndex});
        }
        return {groups,materials};
      };
      const next=partition();
      if (next.materials.length===1 && next.materials[0]===source) continue;
      pending.push({object,partition,retarget: material => {source=material;},
        beforeBake() { followGeometry(); if (!geometryBase.baking++) geometry.groups=geometryBase.groups; },
        afterBake() {
          const last = --geometryBase.baking === 0, replaced = followGeometry();
          if (last && !replaced) geometryBase.groups=geometry.groups;
          const next=partition();
          if (last || replaced) geometry.groups=next.groups;
          object.material=display(next.materials);
        },
        rememberGeometry() { followGeometry(); geometries.set(geometry,geometryBase); }
      });
      for (const material of next.materials) {
        const key=`${material.uuid}:${object.type}:${!!object.isInstancedMesh}:${Object.keys(geometry.attributes)}`;
        if (warmed.has(key) || warmKeys.has(key)) continue;
        warmKeys.add(key);
        const standin=object.clone(false); standin.material=material; warm.add(standin);
      }
    }
    const adopt = () => {
      if (stamp !== revision) return;
      for (const key of warmKeys) warmed.add(key);
      const applied = new Set();
      for (const {object,partition,retarget,beforeBake,afterBake,rememberGeometry} of pending) {
        // Imports can finish while shaders warm. Adopt the material now owned
        // by the object, never the stale material from before compilation.
        const base={material:object.material,partition,retarget,beforeBake,afterBake};
        retarget(base.material); rememberGeometry();
        originals.set(object,base);
        object.addEventListener('bakepresentationstart',base.beforeBake);
        object.addEventListener('bakepresentationend',base.afterBake);
        const next=partition();
        if (!applied.has(object.geometry)) {object.geometry.groups=next.groups;applied.add(object.geometry);}
        object.material=display(next.materials);
      }
      render();
    };
    const compilation=warm.children.length ? compile?.(warm) : null;
    if (!compilation) {adopt();return ready=Promise.resolve();}
    return ready=Promise.resolve(compilation).then(adopt).catch(error=>{if(stamp===revision)failed?.(error);});
  }
  function refreshRanges(changed) {
    const applied=new Set();
    for (const [object,base] of originals) {
      const ranges=object.userData.snapRanges || object.geometry.userData.snapRanges;
      if (ranges ? !ranges.some(r=>changed.has(`${r.buildingId}:${r.pieceId}`))
        : !changed.has(`${object.userData.buildingId}:${object.userData.pieceId}`)) continue;
      const next=base.partition();
      if (!applied.has(object.geometry)) {object.geometry.groups=next.groups;applied.add(object.geometry);}
      object.material=display(next.materials);
    }
  }
  const baseMaterial=object=>originals.get(object)?.material;
  function replaceMaterial(object,expected,material) {
    const base=originals.get(object);
    if (!base || base.material!==expected) return false;
    base.material=material;base.retarget(material);
    const next=base.partition();object.geometry.groups=next.groups;object.material=display(next.materials);return true;
  }
  function dispose() {
    restore();
    for (const cache of variants.values()) for (const material of cache.values()) material.dispose();
    variants.clear();warmed.clear();
  }
  return {apply,restore,refreshRanges,baseMaterial,replaceMaterial,syncMaterials,dispose};
}
