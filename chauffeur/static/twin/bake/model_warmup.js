// Compile detached model stand-ins in tasks. Installed materials and program
// references survive visibility/uniform changes; linking programs are never freed.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { patchModelLighting } from './model_light_material.js';

// Only program-affecting features, never vertex contents/counts or transforms.
function geometryKey(mesh) {
  const {attributes:a, morphAttributes:m} = mesh.geometry;
  return [!!a.position, !!a.normal, !!a.tangent, a.color?.itemSize || 0,
    !!a.uv, !!a.uv1, !!a.uv2, !!a.uv3,
    m.position?.length ?? -1, m.normal?.length ?? -1, m.color?.length ?? -1,
    !!mesh.isSkinnedMesh, !!mesh.isInstancedMesh, !!mesh.instanceColor, !!mesh.morphTexture,
    !!mesh.isBatchedMesh, !!mesh._colorsTexture].join('|');
}
const sameSlots = (a, b) => a === b || (Array.isArray(a) && Array.isArray(b) &&
  a.length === b.length && a.every((m,i) => m === b[i]));

export function createModelWarmup(view, uniforms) {
  const bindings = new Map(), sources = new Map(), records = new Set(), waiting = new Set();
  const disposedMaterials = new WeakSet(), disposingMaterials = new WeakSet();
  let stopped = false, enabled = false, task = null, visibilityTimer = null, lastCheck = -Infinity;
  const currentMaterial = mesh => view.modelMaterial?.(mesh) || mesh.material;
  function assign(b, expected, next) {
    const current = currentMaterial(b.mesh);
    if (!sameSlots(current, expected)) return false;
    if (view.replaceModelMaterial) return view.replaceModelMaterial(b.mesh, current, next);
    b.mesh.material = next; return true;
  }
  function installedSlot(b, material, index) {
    const r = b.installedRecords[index];
    return !!r && [...r.variants.values()].some(v => v.material === material);
  }
  function restore(b) {
    if (b.installed) {
      const current = currentMaterial(b.mesh), slots = [].concat(current);
      const next = slots.map((m,i) => installedSlot(b, m, i) ? b.originals[i] : m);
      if (next.some((m,i) => m !== slots[i])) assign(b, current, sameSlots(next, b.originals) ? b.original : Array.isArray(current) ? next : next[0]);
    }
    b.installed = null; b.installedRecords = [];
  }
  function recordOnMesh(r, mesh) {
    const live = [].concat(currentMaterial(mesh), mesh.material);
    return [...r.variants.values()].some(v => live.includes(v.material) || (v.back && live.includes(v.back)));
  }
  function collect() {
    const used = new Set();
    for (const b of bindings.values()) for (const r of [...b.records, ...b.installedRecords]) used.add(r);
    for (const r of records) if (!used.has(r) && !r.linking) {
      // Presentation owners can wrap arrays or temporarily retain slots. Never
      // release a program reference that is still installed on a tracked mesh.
      if ([...r.meshes].some(mesh => recordOnMesh(r, mesh))) continue;
      for (const {material, back} of r.variants.values()) for (const m of [material, back]) if (m && !disposedMaterials.has(m)) {
        disposingMaterials.add(m);
        try { m.dispose(); } finally { disposingMaterials.delete(m); }
      }
      records.delete(r);
    }
  }
  function record(source) {
    const r = {source, variants:new Map(), active:null, linking:0, meshes:new Set()}; records.add(r); return r;
  }
  // Texture owners increment version when their asynchronous maps arrive. A
  // resolved ready promise alone is not a material change (notably late copies).
  function sourceEntry(source) {
    let entry = sources.get(source); if (entry) return entry;
    entry = {record:record(source), bindings:new Set(), version:source.version}; sources.set(source, entry);
    entry.sync = () => {
      if (stopped || !entry.bindings.size) return;
      entry.version = source.version; entry.record = record(source);
      for (const b of entry.bindings) { b.records = b.originals.map(m => sources.get(m).record); waiting.add(b); }
      collect(); queue();
    };
    source.addEventListener('materialparamschange', entry.sync);
    source.userData.ready?.then?.(() => {
      if (source.version !== entry.version) entry.sync();
    }, () => {});
    return entry;
  }
  function remove(b) {
    const previous = new Set([...b.records, ...b.installedRecords]);
    restore(b); waiting.delete(b); bindings.delete(b.mesh);
    for (const r of previous) if (!recordOnMesh(r, b.mesh)) r.meshes.delete(b.mesh);
    for (const source of new Set(b.originals)) {
      const entry = sources.get(source); entry.bindings.delete(b);
      if (!entry.bindings.size) { source.removeEventListener('materialparamschange', entry.sync); sources.delete(source); }
    }
    collect();
  }
  function prepare(mesh) {
    let b = bindings.get(mesh), material = currentMaterial(mesh);
    if (b && (sameSlots(material, b.original) || ([].concat(material).length === b.originals.length &&
        [].concat(material).every((m,i) => installedSlot(b, m, i))))) {
      if (!sameSlots(material, b.original)) b.installed = material;
      const signature = geometryKey(mesh);
      if (signature !== b.signature) { b.signature = signature; waiting.add(b); }
      return;
    }
    if (b) { remove(b); material = currentMaterial(mesh); }
    b = {mesh, original:material, originals:[].concat(material), installed:null, installedRecords:[], signature:geometryKey(mesh)};
    b.records = b.originals.map(m => sourceEntry(m).record);
    for (const m of b.originals) sources.get(m).bindings.add(b);
    bindings.set(mesh, b); waiting.add(b);
  }
  function retireRecord(r) {
    const entry = sources.get(r.source);
    if (entry?.record === r) entry.record = record(r.source);
    for (const b of bindings.values()) {
      if (b.installedRecords.includes(r)) restore(b);
      if (b.records.includes(r)) { b.records = b.originals.map(m => sources.get(m).record); waiting.add(b); }
    }
  }
  function clone(source, r) {
    const material = source.clone();
    material.addEventListener('dispose', () => {
      disposedMaterials.add(material);
      if (disposingMaterials.has(material)) return;
      // Yard disposal can remove a live shared clone while its new geometry
      // links. Restore its bindings and give the next queue fresh records now;
      // the cancelled round retains its other references until safe cleanup.
      retireRecord(r);
      if (task?.records?.has(r)) cancel();
      else if (task) task.checkRequested = true;
    });
    material.onBeforeCompile = source.onBeforeCompile;
    material.customProgramCacheKey = source.customProgramCacheKey;
    if (source.emissive) {
      material.emissive = source.emissive;
      Object.defineProperty(material, 'emissiveIntensity', {configurable:true,
        get:() => source.emissiveIntensity, set:value => { source.emissiveIntensity = value; }});
    }
    if (view.prepareModelMaterial) view.prepareModelMaterial(source, material);
    else view.prepareViewingMaterial?.(source, material);
    patchModelLighting(material, uniforms); return material;
  }
  function lightKey() {
    const lights = [];
    view.scene.traverseVisible(o => {
      if (o.isLight && (!view.camera?.layers || o.layers.test(view.camera.layers))) lights.push(`${o.type}:${!!o.castShadow}:${!!o.map}`);
    });
    return lights.sort().join('|');
  }
  function visible(mesh, frustum) {
    let attached = false;
    for (let p = mesh; p; p = p.parent) { if (!p.visible) return false; if (p === view.scene) attached = true; }
    return attached && (!view.camera?.layers || mesh.layers.test(view.camera.layers)) &&
      (!frustum || !mesh.frustumCulled || frustum.intersectsObject(mesh));
  }
  function cameraFrustum() {
    if (!view.camera?.projectionMatrix || !view.camera.matrixWorldInverse) return null;
    view.camera.updateMatrixWorld();
    return new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(view.camera.projectionMatrix, view.camera.matrixWorldInverse));
  }
  function programDone({material, key, program}) {
    if (disposedMaterials.has(material) || program?.program === undefined || typeof program?.isReady !== 'function') return true;
    if (view.renderer3.properties?.get(material)?.programs?.get(key) !== program) return true;
    // Deleted programs/context loss can return null. Unknown representations
    // fall back to the compileAsync promise instead of rejecting or hanging.
    try { return program.isReady() !== false; } catch { return true; }
  }
  function programsReady(materials, round) {
    // One material can own several geometry programs. r187 compileAsync polls
    // only currentProgram, which later stand-ins (or draws) overwrite. Snapshot
    // every submitted program and use the same nonblocking KHR readiness query.
    const programs = materials.flatMap(material => [...(view.renderer3.properties?.get(material)?.programs || [])]
      .map(([key, program]) => ({material, key, program})));
    round.programs.push(...programs);
    if (!programs.length) return Promise.resolve(); // CPU-only renderer fakes
    return new Promise(resolve => {
      let timer;
      const finish = () => { clearTimeout(timer); round.stopWaiting.delete(finish); resolve(); };
      round.stopWaiting.add(finish);
      const check = () => {
        if (round.cancelled || stopped || programs.every(programDone)) finish();
        else timer = setTimeout(check, 10);
      };
      check();
    });
  }
  function releaseLinks(round, touched) {
    // Readiness polling is cancelled with the round. After compileAsync settles,
    // retirement alone must still protect any non-current geometry program that
    // is genuinely linking (I4). It cannot hold task or block a later queue.
    const retire = () => {
      if (!round.programs.every(programDone)) { setTimeout(retire, 10); return; }
      for (const r of touched) r.linking = 0;
      collect();
    };
    retire();
  }
  function queue() {
    // In particular, an orbit of already-ready models never traverses the scene
    // or touches the light rig, its shadows or the mode warm-up path.
    if (stopped || !enabled || !waiting.size) return Promise.resolve();
    if (task) { task.checkRequested = true; return task.promise; }
    let done;
    const promise = new Promise(resolve => { done = resolve; });
    const round = task = {promise, done, cancelled:false, checkRequested:false, timer:null, programs:[], stopWaiting:new Set()};
    round.timer = setTimeout(async () => {
      round.timer = null;
      if (round.cancelled || stopped) { if (task === round) task = null; done(); return; }
      const frustum = cameraFrustum();
      const selected = [...waiting].filter(b => visible(b.mesh, frustum));
      const selectedRecords = new Map();
      for (const b of selected) for (const r of b.records) {
        if (!selectedRecords.has(r)) selectedRecords.set(r, new Map());
        selectedRecords.get(r).set(b.signature, b.mesh); r.meshes.add(b.mesh);
      }
      const targets = new Map(selected.map(b => [b, b.records.slice()]));
      const pending = [], touched = new Set(), seen = new Set(), coverage = new Map();
      round.records = touched;
      let failed = false, installed = false, retry = false;
      const submit = root => {
        if (!root.children.length) return;
        try {
          pending.push(Promise.resolve(view.compileModelMaterials ? view.compileModelMaterials(root) : view.renderer3.compileAsync(root, view.camera, view.scene)));
          const materials = new Set(); root.traverse(o => { for (const m of [].concat(o.material || [])) materials.add(m); });
          pending.push(programsReady([...materials], round));
        }
        catch (error) { pending.push(Promise.reject(error)); }
      };
      try {
        if (!selected.length) return;
        const compile = () => {
          const key = lightKey(); if (seen.has(key)) return; seen.add(key);
          const root = new THREE.Group(), backs = new THREE.Group();
          for (const [r, meshes] of selectedRecords) {
            let variant = r.variants.get(key);
            const missing = [...meshes].filter(([signature]) => !variant?.signatures.has(signature));
            if (!missing.length) continue;
            if (!variant) {
              variant = {material:clone(r.source, r), back:null, signatures:new Set()}; r.variants.set(key, variant);
            }
            const {material} = variant;
            r.linking++; touched.add(r);
            // r187 prepares both sides but compileAsync polls currentProgram
            // (the front). Pin the back program to its own material and wait too.
            if (!variant.back && material.transparent && material.side === THREE.DoubleSide && !material.forceSinglePass) {
              variant.back = clone(r.source, r); variant.back.side = THREE.BackSide;
            }
            coverage.set(variant, missing.map(([signature]) => signature));
            for (const [,mesh] of missing) {
              const proxy = mesh.clone(false); proxy.material = material; root.add(proxy);
              if (variant.back) { const back = mesh.clone(false); back.material = variant.back; backs.add(back); }
            }
          }
          submit(root); submit(backs);
        };
        compile();
        // No rig toggles when this round merely attaches an already-warm shared
        // material to a late mesh. Only missing programs need the variant list.
        if (pending.length) {
          const variants = view.live?.warm?.(compile); if (variants) pending.push(Promise.resolve(variants));
        }
        // Settle ALL submissions before releasing any reference, even on failure.
        const results = await Promise.allSettled(pending);
        const error = results.find(result => result.status === 'rejected');
        if (error) throw error.reason;
        if (stopped || !enabled || round.cancelled) return;
        for (const [variant, signatures] of coverage) for (const signature of signatures) variant.signatures.add(signature);
        const key = lightKey();
        if (!seen.has(key)) { retry = true; return; }
        for (const b of selected) {
          const wanted = targets.get(b);
          if (bindings.get(b.mesh) !== b || wanted.some((r,i) => r !== b.records[i])) { retry = true; continue; }
          if (!wanted.every(r => r.variants.get(key)?.signatures.has(b.signature))) { retry = true; continue; }
          // Retain the installed clone across additional light states. Other
          // variant instances keep every program warm in Three's shared cache.
          const materials = wanted.map(r => r.active ||= r.variants.get(key).material);
          const next = Array.isArray(b.original) ? materials : materials[0];
          if (assign(b, b.installed || b.original, next)) {
            b.installed = next; b.installedRecords = wanted; waiting.delete(b); installed = true;
          }
        }
      } catch (error) {
        // A synchronous rig/preparation error may follow earlier submissions.
        // Those programs must finish linking before cleanup on this path too.
        await Promise.allSettled(pending);
        failed = true;
        if (!stopped && !round.cancelled) console.warn('Model lighting program unavailable:', error);
        // Failed candidates do not retry on every gesture. A material/state
        // change can explicitly request another generation.
        for (const b of selected) waiting.delete(b);
        for (const r of touched) {
          if (sources.get(r.source)?.record === r) sources.get(r.source).record = record(r.source);
          for (const b of bindings.values()) if (b.records.includes(r)) b.records = b.originals.map(m => sources.get(m).record);
        }
      } finally {
        releaseLinks(round, touched);
        if (task === round) task = null;
        done();
        if (installed) view.render?.();
        // New bindings/material generations that arrived during this round are
        // eligible, without restarting any of its completed material programs.
        if (!failed && !round.cancelled && !stopped) {
          if (retry || round.checkRequested) queue(); // The next task reads the CURRENT camera.
          else if ([...waiting].some(b => !targets.has(b) && visible(b.mesh, frustum))) queue();
        }
      }
    }, 0);
    return promise;
  }
  const host = view.renderer3.domElement.parentElement;
  function changed() {
    if (stopped || !enabled || !waiting.size) return;
    if (task) { task.checkRequested = true; return; }
    if (visibilityTimer !== null) return;
    visibilityTimer = setTimeout(() => { visibilityTimer = null; lastCheck = performance.now(); queue(); }, Math.max(0, 250 - (performance.now() - lastCheck)));
  }
  function cancel() {
    if (!task) return;
    task.cancelled = true; task.done();
    for (const finish of [...task.stopWaiting]) finish();
    // A scheduled round owns no programs yet. A running round cleans up only
    // after all its compile promises settle.
    if (task.timer !== null) clearTimeout(task.timer);
    task = null;
  }
  host?.addEventListener('twinviewchange', changed);
  view.controls?.addEventListener?.('change', changed);
  return {
    prepare, queue,
    setEnabled(value) {
      if (enabled === value) return; enabled = value;
      if (!value) {
        cancel();
        for (const [source,e] of sources) if (e.record.variants.size) e.record = record(source);
        for (const b of bindings.values()) { restore(b); waiting.add(b); b.records = b.originals.map(m => sources.get(m).record); }
        collect();
      }
    },
    retain(meshes) { for (const [mesh,b] of bindings) if (!meshes.has(mesh)) remove(b); },
    warm() {
      if (stopped || !enabled) return Promise.resolve();
      const key = lightKey();
      for (const b of bindings.values()) if (!b.records.every(r => r.variants.get(key)?.signatures.has(b.signature))) waiting.add(b);
      return queue();
    },
    stop() {
      if (stopped) return; stopped = true; cancel(); clearTimeout(visibilityTimer);
      host?.removeEventListener('twinviewchange', changed); view.controls?.removeEventListener?.('change', changed);
      for (const b of [...bindings.values()]) remove(b);
      collect();
    },
  };
}
