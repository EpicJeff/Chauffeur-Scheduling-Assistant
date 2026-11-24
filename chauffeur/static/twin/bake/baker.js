import { assignChannels, CHANNEL_FALLBACK, CHART_STATS, fingerprint, atlasMesh } from './atlas.js';
import { renderPage, roomFills, dilateCharts, encodeSumPages, filterCharts } from './bake_pass.js';
import { withBakeLease, bakeHTTPError } from './bake_lock.js';
import { reachLights, lightSource } from './reach.js';
import { placedCopies, occluderHash } from './model_occluders.js';
import { encodeSlots, decodeSlots, sameSlots } from './slots.js';
import { matchesEntry, cheapSignatures } from './freshness.js';
import { keyInputs, sameKeyInputs } from './key_inputs.js';
import { gridLayout, gridPoints, pointsInRange, maskGridIndices, GRID_INVALID, GRID_MASK_RULE } from './grid_layout.js';
import { createGridAccumulator } from './grid_pass.js';
import { encodeGridChunk, decodeGridChunk, MAX_CHUNK_BYTES } from './grid_chunk.js';
import * as THREE from '../../vendor/three-r187/three.module.js';
import { collectStaticOccluders, buildOccluderBVH } from '../live/cone_occluder.js';
import { emitterTable, chooseEmitters } from './model_bricks.js';

export { encodePage, decodePage } from './codec.js';

export function lightKey(atlas, light, slot, bank) {
  return lampKey(atlas, light, slot, true);
}

export function gridKey(atlas, light, slot, bank) {
  return lampKey(atlas, light, slot, false);
}

function lampKey(atlas, light, slot, models) {
  const hash=fingerprint();
  // The grid sees receiving geometry only; pages also see placed occluders.
  hash.add(JSON.stringify([light.signature ? 'light-slots-9' : 'light-slots-8',light.reach || atlas.key,light.device,light.at,
    ...(models ? [light.occluders || ''] : ['grid-mask-2', GRID_MASK_RULE]),
    ...(light.signature ? ['fixtures-2', light.signature, ...(light.kind === 3 ? [] : [null])] : [])]));
  if (slot.assignments) {
    const ranking=[...slot.assignments].sort((a,b)=>a.chartKey<b.chartKey?-1:a.chartKey>b.chartKey?1:0), rank=new Uint8Array(2);
    for (const a of ranking) {
      hash.add(a.chartKey);rank[0]=a.bank;rank[1]=a.channel;hash.add(rank);
    }
  } else hash.add(JSON.stringify([slot.bank,slot.channel]));
  return hash.key();
}

// Scales are rendered output. Layout only adopts a previously published scale;
// an unbaked sum has none and cannot become fresh.
export function bakeLayout(atlas, layout, lights, history, published = {}) {
  let prior, ownershipReset = false;
  try { prior = decodeSlots(history, atlas.room.charts.length); }
  catch (error) {
    if (error.message !== 'Invalid lightmap ownership history.') throw error;
    // History is an optimization, never a prerequisite for displaying a house.
    // A different chart set or damaged manifest needs a fresh assignment and
    // a rebuild of every light; none of its published channels can be trusted.
    prior = new Map(); ownershipReset = true; published = {};
  }
  const copies = placedCopies(atlas.room.plan);
  lights = reachLights(atlas.room, lights).map(l => ({...l,
    occluders: occluderHash(copies, lightSource(atlas.room.plan, l).source, l.range),
    ...(l.kind === 3 ? {scale: Number.isFinite(published[l.device]?.scale) && published[l.device].scale > 0
      ? published[l.device].scale : undefined} : {})}));
  const slots = assignChannels(atlas.room.rooms, lights, prior), banks = atlas.room.packBanks(lights, slots);
  let offset = 0;
  // Geometry reserves a fixed address stride, even when its trailing pages are
  // unlit. A lamp reaching a new page must not shift another bank's stored bytes.
  const offsets = banks.map(b => { const n = offset; offset += b.addressPages ?? b.pages; return n; });
  const entries = {};
  const byChart=banks.map(b=>new Map(b.charts.map(c=>[c.id,c])));
  const address=new Int32Array(12);
  for (const light of lights) {
    const s = slots[light.device]; if (!s) continue;
    const location=fingerprint(), usedPages=new Set();
    const visit=(c,bank)=>{
      if (!c) return;
      usedPages.add(offsets[bank]+c.page);
      const r=c.rect,s=c.sourceRegion;
      address[0]=c.id;address[1]=bank;address[2]=c.page;
      address[3]=r.x;address[4]=r.y;address[5]=r.w;address[6]=r.h;
      address[7]=s?.page ?? -1;address[8]=s?.x ?? -1;address[9]=s?.y ?? -1;
      address[10]=s?.w ?? -1;address[11]=s?.h ?? -1;
      location.add(address);
    };
    if (s.assignments) for (const a of s.assignments) visit(byChart[a.bank].get(a.chart),a.bank);
    else for (const c of banks[s.bank].charts) if ((s.receivers || [s.room]).includes(c.room)) visit(c,s.bank);
    const pages=[...usedPages].sort((a,b)=>a-b);
    if (!pages.length) continue;
    entries[light.device] = { page: pages[0], pages, channel: s.channel,
      ...(light.kind === 3 ? {scale: light.scale} : {}),
      location: location.key(),
      grid: gridKey(atlas, light, s, banks[s.bank]),
      gridRule: GRID_MASK_RULE,
      key: lightKey(atlas, light, s, banks[s.bank]) };
  }
  return { lights, slots, banks, offsets, entries, pages: offset,
    ...(ownershipReset ? {ownershipReset:true} : {}), fallback: slots[CHANNEL_FALLBACK],
    ownership:encodeSlots(slots,atlas.room.charts.length),
    ranking:slots[CHART_STATS] || {worstDroppedFraction:0,worstChart:null,droppedCharts:0},
    densities: { room: layout.room.density } };
}

export function realtimeReason(packed, id) {
  if (packed.entries[id]) return null;
  const light = packed.lights.find(l => l.device === id);
  return light ? light.receivingCharts?.length ? 'fallback' : 'no reach' : null;
}

// Whether a stored page exists, without downloading it (M5): If-None-Match: * answers
// 304 for any stored page. Only a 404 is "missing"; any other failure throws (I7).
async function exists(api, url) {
  const r = await api(url, { headers: { 'If-None-Match': '*' } });
  if (r.status === 304 || r.ok) return true;
  if (r.status === 404) return false;
  throw new Error(`Could not read the lightmap (HTTP ${r.status}).`);
}

export function createBaker(view, { renderer, atlas, layout, lights, api: request, codec, force = false, forceRound = null,
  round = view.round ?? null, lighting = view.lighting ?? null, owner = null, damaged = [], inspectLegacy = false,
  onGrid = () => {}, damagedGrids = [] }) {
  const plan = view.bakePlan || view.plan, enabled = ['high', 'max'].includes(view.tier);
  const inputLights = lights; // reachLights adds derived, metre-valued ranges.
  const inputs = keyInputs(view);
  const bakeView = Object.create(view); bakeView.plan = plan;
  let packed, assignmentHistory;
  const path = `api/house/bakes/${atlas.key}`;
  const who = owner || [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('');
  let cancelled = false, manifest = null, busy = false;
  let checkpoint = async () => {};
  let runGridLayout = null, grid = {points: 0, bytes: 0, ms: 0, maskMs: 0, foldedOrDropped: 0};
  const gridCache = new Map();
  const gridReceipts = new Map();
  const missingGrids = new Set(damagedGrids);
  const runChunks = new Map();
  const runGrids = new Map();
  let statsWarned = false;
  // Geometry alone defines the layout; validity is cached lazily per light.
  function gridData() {
    runGridLayout ||= gridLayout(plan);
    const cached = gridCache.get(runGridLayout.hash);
    if (cached) return cached;
    const start = performance.now(), points = gridPoints(runGridLayout);
    const root = view.bake?.occlusionRoot?.() || view.scene;
    const meshes = collectStaticOccluders(root, bakeView).filter(o =>
      atlasMesh(o) && o.material.name !== 'glass' && !o.geometry?.userData.bakeHeightfield);
    const bvh = buildOccluderBVH(meshes, null, {facing:true});
    const bvhMs = performance.now() - start;
    const data = {layout: runGridLayout, points, bvh, mask: new Uint8Array(runGridLayout.count), bvhMs};
    gridCache.set(runGridLayout.hash, data);
    return data;
  }
  const api = async (url, init) => {
    await checkpoint();
    const writing = ['POST', 'PUT'].includes(init?.method);
    if (writing) {
      const headers = new Headers(init.headers); headers.set('X-Bake-Owner', who);
      init = { ...init, headers };
    }
    const r = await request(url, init);
    if (r.status === 401) throw bakeHTTPError('Could not access the bake', 401);
    if (writing && r.status === 409) throw bakeHTTPError('Lost the bake lease', 409);
    await checkpoint();
    return r;
  };
  const unavailable = new Set();
  const damagedPages = new Set(damaged);
  const legacyPages = new Map();
  const signatures = m => cheapSignatures(inputLights, m.ownership, m.lights);
  const realtime = m => {
    const cheap = signatures(m);
    return Object.fromEntries(packed.lights.filter(l => !packed.entries[l.device]).map(l =>
      [l.device, {cheap: cheap[l.device], reason: realtimeReason(packed, l.device)}]));
  };
  const signed = m => {
    m = {...m, lights: Object.fromEntries(Object.entries(m.lights).filter(([id]) => !realtimeReason(packed, id)))};
    const cheap = signatures(m);
    return { ...m, lighting, keyInputs: inputs, realtime: realtime(m), lights: Object.fromEntries(Object.entries(m.lights).map(([id, e]) =>
      [id, matchesEntry(packed.entries[id], e) ? { ...e, cheap: cheap[id] } : e])) };
  };
  const unsigned = m => {
    const cheap = signatures(m);
    return m.lighting !== lighting || !sameKeyInputs(m.keyInputs, inputs) || JSON.stringify(m.realtime || {}) !== JSON.stringify(realtime(m)) ||
      lights.some(l => packed.entries[l.device] && m.lights[l.device]?.cheap !== cheap[l.device]);
  };
  // Legacy bytes were read before the lease. Only migrate the exact version
  // inspected then; a newer desk's page/receipt always wins under this lease.
  async function legacyUpload(page, legacy, latest) {
    if (latest?.pageIntegrity?.[page] || !legacy.etag) return false;
    const r = await api(`${path}/${page}.png`, {headers: {'If-None-Match': legacy.etag}});
    if (r.status === 304) return true;
    if (r.ok || r.status === 404) return false;
    throw new Error(`Could not read the lightmap (HTTP ${r.status}).`);
  }
  // Re-bake all lighting re-bakes every light, but each keeps its stored entry
  // (same key) until its new bake lands, so panels never drop to real-time mid-run (M6).
  let activeForce = forceRound || (force ? [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('') : null);
  let forcePending = !!activeForce;
  const valid = () => !cancelled && (view.bakePlan || view.plan) === plan;
  const readManifest = async () => {
    const response = await api(path);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Could not read the bake manifest (HTTP ${response.status}).`);
    const stored = await response.json();
    // Another stale light's page entry can be pruned while this run advances;
    // its previously published grid still exists and remains reusable.
    for (const e of Object.values(stored.lights || {})) if (e.grid && e.gridLayout && e.gridRule === GRID_MASK_RULE && !missingGrids.has(e.grid)) gridReceipts.set(e.grid, e.gridLayout);
    return stored;
  };
  const pagesStale = device => packed.entries[device] && (
    lights.find(l => l.device === device)?.kind === 3 && !(packed.entries[device].scale > 0) ||
    (activeForce && manifest.lights[device]?.forceRound !== activeForce) || !matchesEntry(packed.entries[device], manifest.lights[device]));
  const isStale = device => pagesStale(device) || packed.entries[device] && (
    missingGrids.has(packed.entries[device].grid) ||
    manifest.lights[device]?.gridRule !== GRID_MASK_RULE ||
    manifest.lights[device]?.grid !== packed.entries[device].grid ||
    manifest.lights[device]?.gridLayout !== (runGridLayout ||= gridLayout(plan)).hash);
  const ready = enabled ? readManifest().then(async m => {
    await view.bake?.idle?.();
    if (!valid()) return;
    assignmentHistory=m?.ownership;
    packed=bakeLayout(atlas,layout,lights,assignmentHistory,m?.lights);
    lights=packed.lights;
    if (m?.forceRound === activeForce) forcePending = false;
    if (!forcePending) activeForce = m?.forceRound || null;
    manifest = m && !packed.ownershipReset ? m : { pages: packed.pages, lights: {} };
    if (m && !packed.ownershipReset) {
      const ids = new Set(Object.values(m.lights).flatMap(e => e.pages || [e.page]));
      const missing = new Set();
      for (const p of ids) if (!(await exists(api, `${path}/${p}.png`))) missing.add(p);
      // Only a pressed baker validates unsigned legacy bytes. A valid page can
      // be republished under the lease to record stat-backed integrity, without
      // re-rendering its lights; damaged legacy pages need their channels back.
      for (const p of ids) if (inspectLegacy && !missing.has(p) && !m.pageIntegrity?.[p]) {
        const r = await api(`${path}/${p}.png`);
        if (!r.ok) throw new Error(`Could not read the lightmap (HTTP ${r.status}).`);
        const bytes = new Uint8Array(await r.arrayBuffer());
        try {
          const decoded = await codec.decode(bytes);
          if (decoded.width !== layout.room.page || decoded.height !== layout.room.page) throw new Error('A lightmap page does not fit its array.');
          legacyPages.set(p, {bytes, etag: r.headers.get('etag')});
        } catch { damagedPages.add(p); missing.add(p); }
      }
      manifest = { ...manifest, lights: { ...manifest.lights } };
      for (const [id, e] of Object.entries(manifest.lights)) if ((e.pages || [e.page]).some(p => damagedPages.has(p) || missing.has(p))) {
        unavailable.add(id); delete manifest.lights[id];
      }
    }
  }) : Promise.resolve();
  async function staleLights() {
    await ready;
    return enabled && valid() ? lights.filter(l => isStale(l.device)).map(l => l.device) : [];
  }
  // A page's channels, or blank ones when it was never written (404). Any other failure
  // aborts the step before anything is uploaded (I7).
  async function pageData(page, size, count) {
    const r = await api(`${path}/${page}.png`);
    if (r.ok) {
      const bytes = new Uint8Array(await r.arrayBuffer());
      try {
        // A previous attempt may have uploaded a valid page before its manifest
        // PUT failed. Decode those channels and preserve finished-light work.
        const decoded = await codec.decode(bytes);
        if (decoded.width === size && decoded.height === size) return decoded.channels;
      } catch (error) { if (!activeForce && !damagedPages.has(page)) throw error; }
    } else if (r.status !== 404) throw new Error(`Could not read the lightmap (HTTP ${r.status}).`);
    return Array.from({ length: count }, () => new Uint8Array(size * size));
  }
  async function bakeStep() {
    if (!valid()) return null;
    // Another desk may have baked lights since this one last looked.
    const latest = await readManifest();
    if(latest?.ownership && !sameSlots(latest.ownership,assignmentHistory)) {
      assignmentHistory=latest.ownership;
      packed=bakeLayout(atlas,layout,lights,assignmentHistory,latest?.lights);
      lights=packed.lights;
    }
    // A reload or another desk can have advanced this same force while we waited.
    if (!forcePending) activeForce = latest?.forceRound || null;
    if (packed.ownershipReset) manifest = { ...manifest, lights: {} };
    if (latest && !packed.ownershipReset) {
      for (const [id, entry] of Object.entries(packed.entries)) if (lights.find(l => l.device === id)?.kind === 3)
        entry.scale = Number.isFinite(latest.lights[id]?.scale) && latest.lights[id].scale > 0
          ? latest.lights[id].scale : undefined;
      for (const [device, e] of Object.entries(latest.lights))
        if (!unavailable.has(device)) manifest.lights[device] = e;
    }
    if (activeForce) manifest.forceRound = activeForce;
    else delete manifest.forceRound;
    if (forcePending && latest?.forceRound !== activeForce && lights.some(l => isStale(l.device))) {
      // Persist intent under the lease BEFORE GPU work, including the first light.
      const start = { ...(latest || manifest), lights: { ...manifest.lights },
        ...(packed.ownershipReset ? { ownership: packed.ownership } : {}), forceRound: activeForce, complete: false };
      const r = await api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(start) });
      if (!r.ok) throw new Error('Could not save the bake manifest.');
      manifest = start;
    }
    forcePending = false;
    const stale = lights.filter(l => isStale(l.device)).map(l => l.device), id = stale[0];
    if (!id) return null;
    const light = lights.find(l => l.device === id), s = packed.slots[id];
    const gridOnly = !pagesStale(id);
    const size = layout.room.page;
    const owned=new Map(s.assignments?.map(a=>[a.chart,a]));
    const charts = packed.banks.flatMap(bank=>bank.charts.flatMap(c=>{
      const a=owned.get(c.id);
      return a?.bank===bank.bank || !s.assignments && bank.bank===s.bank && (s.receivers || [s.room]).includes(c.room)
        ? [{...c,page:c.page+packed.offsets[bank.bank],channel:a?.channel ?? s.channel}] : [];
    }));
    const pages = [...new Set(charts.map(c => c.page))];
    const uploads = [], rendered = [];
    const entry = packed.entries[id];
    runGridLayout ||= gridLayout(plan);
    const existingGrid = !activeForce && gridReceipts.get(entry.grid) === runGridLayout.hash;
    let gridUpload = null, accumulator = null, data = null, indices = null;
    let lightGrid = {points: 0, bytes: 0, ms: 0, maskMs: 0, foldedOrDropped: 0};
    try {
      if (entry.grid && !existingGrid) {
        await view.bake?.idle?.();
        if (!valid()) return null;
        data = gridData();
        const {source, range} = lightSource(plan, light);
        indices = pointsInRange(data.layout, data.points, source, range);
        const measured = await maskGridIndices(data.points, data.bvh, data.layout, indices, data.mask, async () => {
          await checkpoint();
          if (view.bake?.state?.().paused || view.ready === false || view.yardSettling) await view.bake?.idle?.();
          if (!valid()) throw new Error('The bake round changed.');
        });
        lightGrid = {points: indices.length, bytes: 0, ms: 0, foldedOrDropped: 0, ...measured, bvhMs: data.bvhMs};
        data.bvhMs = 0;
        const start = performance.now();
        accumulator = createGridAccumulator(renderer, data.points, indices, light.emitters?.length || 1);
        lightGrid.ms += performance.now() - start;
      }
      if (lightGrid.points) grid = {...lightGrid};
      onGrid({...grid});
      for (const [pageIndex, p] of pages.entries()) {
        if (gridOnly && !accumulator) break;
        if (gridOnly && pageIndex > 0) break;
        const page = p;
        const mine = charts.filter(c => c.page === p);
        // A live/manifest read can span the start of an editor gesture. Check
        // again before even clearing a render target, as well as between samples.
        await view.bake?.idle?.();
        if (!valid()) return null;
        const onSample = accumulator && pageIndex === 0 ? (texture, sample, far) => {
          const start = performance.now();
          accumulator.sample(texture, sample.source, far, sample.emitter ?? 0, sample.visibilityWeight ?? sample.weight);
          lightGrid.ms += performance.now() - start;
        } : null;
        const pixels = await renderPage(bakeView, renderer, mine, size, light, layout, atlas, {deferBounce:true, deferSumEncoding:true, checkpoint, onSample});
        await checkpoint();
        if (!valid()) return null;
        if (!gridOnly) rendered.push({page, charts:mine, ...(light.kind === 3 ? pixels : {bytes:pixels})});
      }
      if (accumulator) {
        const start = performance.now(), values = accumulator.read(), emitters = light.emitters?.length || 1;
        for (let i = 0; i < indices.length; i++) if (data.mask[indices[i]] === 2) values.fill(GRID_INVALID, i * emitters, (i + 1) * emitters);
        lightGrid.ms += performance.now() - start;
        gridUpload = await encodeGridChunk({layoutHash: data.layout.hash, device: id, emitters, indices, values});
        if (gridUpload.length > MAX_CHUNK_BYTES) throw new Error('Grid chunk exceeds 8 MiB.');
        if (gridUpload[0] !== 0x1f || gridUpload[1] !== 0x8b) throw new Error('Grid compression is unavailable.');
        lightGrid.bytes = gridUpload.length;
        runChunks.set(id, {indices, values, emitters});
        entry.gridLayout = data.layout.hash;
      } else if (existingGrid) entry.gridLayout = runGridLayout.hash;
      if (lightGrid.points) grid = {...lightGrid};
      onGrid({...grid});
    } finally { accumulator?.dispose(); }
    if (light.kind === 3 && !gridOnly) {
      const scale = await encodeSumPages(rendered, size);
      if (!valid()) return null;
      light.scale = scale;
      for (const r of rendered) { filterCharts(r.bytes, r.charts, size); delete r.irradiance; }
      packed.entries[id].scale = light.scale;
    }
    // The room fill travels in the manifest entry; the pages hold visibility only.
    const fill = gridOnly ? manifest.lights[id].fill : roomFills(rendered, size, light);
    for (const r of rendered) dilateCharts(r.bytes, r.charts, size);
    for (const {page, charts:mine, bytes:pixels} of rendered) {
      const channels = await pageData(page, size, 2);
      // Replace only this light's receiving charts and channel.
      for (const c of mine) {
        const r = c.rect;
        for (let y = Math.max(0, r.y - 2); y < Math.min(size, r.y + r.h + 2); y++)
          for (let x = Math.max(0, r.x - 2); x < Math.min(size, r.x + r.w + 2); x++) {
            const sx = Math.max(r.x, Math.min(r.x + r.w - 1, x)), sy = Math.max(r.y, Math.min(r.y + r.h - 1, y));
            channels[c.channel][y * size + x] = pixels[(sy * size + sx) * 4];
          }
      }
      const bytes = await codec.encode({ width: size, height: size, channels });
      uploads.push({ page, bytes });
    }
    if (!valid()) return null;
    const next = { ...manifest, pages: packed.pages, densities: packed.densities, ownership:packed.ownership,
      formats: Array(packed.pages).fill('ktx2'), lights: { ...manifest.lights } };
    for (const [device, entry] of Object.entries(next.lights))
      if (entry.key !== packed.entries[device]?.key || entry.location !== packed.entries[device]?.location || unavailable.has(device)) delete next.lights[device];
    // Sparse banks can change the global offsets of later, unchanged banks.
    // Move their existing bytes rather than re-baking those lights. Read all
    // sources before the first upload so overlapping moves cannot eat data.
    const moves = new Map();
    for (const [device, entry] of Object.entries(next.lights)) {
      const expected = packed.entries[device];
      for (let i = 0; i < expected.pages.length; i++) {
        const page = expected.pages[i], before = (entry.pages || [entry.page])[i];
        if (before === page || moves.has(page)) continue;
        const r = await api(`${path}/${before}.png`);
        if (!r.ok) throw new Error('Could not preserve the later light bank.');
        moves.set(page, new Uint8Array(await r.arrayBuffer()));
      }
      next.lights[device] = { ...expected,
        ...(expected.grid && expected.grid === entry.grid && entry.gridLayout ? {gridLayout: entry.gridLayout} : {}),
        ...(entry.forceRound ? { forceRound: entry.forceRound } : {}), ...(entry.fill ? { fill: entry.fill } : {}) };
    }
    for (const [page, bytes] of moves) uploads.push({ page, bytes });
    // Bank zero reserves unlit rooms too. Publish any missing reserved pages
    // before the manifest names the layout; leave every stored page alone.
    let empty;
    for (let page = 0; page < packed.pages; page++) {
      if (uploads.some(upload => upload.page === page) || await exists(api, `${path}/${page}.png`)) continue;
      if (!empty) empty = await codec.encode({ width: size, height: size,
        channels: [new Uint8Array(size * size), new Uint8Array(size * size)] });
      uploads.push({ page, bytes: empty });
    }
    delete next.sky; // Ignore legacy sky metadata when publishing room lights.
    next.lights[id] = { ...packed.entries[id], fill, ...(activeForce ? { forceRound: activeForce } : {}) };
    // Which house round was baked and whether it is whole.
    next.round = round;
    next.complete = lights.every(l => !packed.entries[l.device] ||
      matchesEntry(packed.entries[l.device], next.lights[l.device]) &&
      (!activeForce || next.lights[l.device]?.forceRound === activeForce));
    if (next.complete) delete next.forceRound;
    next.pageIntegrity = { ...manifest.pageIntegrity, ...latest?.pageIntegrity };
    for (const [page, legacy] of legacyPages)
      if (!uploads.some(u => u.page === page) && await legacyUpload(page, legacy, latest)) uploads.push({ page, bytes: legacy.bytes });
    for (const { page, bytes } of uploads) {
      if (!valid()) return null;
      const r = await api(`${path}/${page}.png`, { method: 'POST', headers: { 'Content-Type': 'image/ktx2' }, body: bytes });
      if (!r.ok) throw new Error('Could not save the lightmap.');
      const saved = await r.json();
      next.pageIntegrity[page] = { size: bytes.length, digest: saved.digest || saved.etag,
        ...(saved.version ? { version: saved.version } : {}) };
    }
    if (!valid()) return null;
    if (gridUpload) {
      const r = await api(`${path}/grid/${entry.grid}.bin`, {method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: gridUpload});
      if (!r.ok) throw new Error('Could not save the light-visibility grid.');
    }
    if (!valid()) return null;
    const published = signed(next);
    const r = await api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(published) });
    if (!r.ok) throw new Error('Could not save the bake manifest.');
    manifest = published; assignmentHistory=packed.ownership; packed.ownershipReset=false; legacyPages.clear();
    if (gridUpload) missingGrids.delete(entry.grid);
    if (gridUpload) runGrids.set(id, {...lightGrid});
    unavailable.delete(id);
    return id;
  }
  async function bakeNext() {
    await ready;
    if (!enabled || !valid() || busy) return null;
    if (!lights.some(l => isStale(l.device))) return null;
    busy = true;
    try {
      return await withBakeLease(request, path, who, valid, async check => {
        checkpoint = check;
        try { return await bakeStep(); } finally { checkpoint = async () => {}; }
      });
    } finally { busy = false; }
  }
  // Record that this round's bake is whole when nothing was left to bake (B15).
  async function settleManifest() {
    await ready;
    if (!enabled || !valid() || lights.some(l => isStale(l.device))) return false;
    if (manifest.round === round && manifest.complete === true && !unsigned(manifest) && !legacyPages.size) return false;
    return withBakeLease(request, path, who, valid, async check => {
      await check();
      const latest = await readManifest() || {pages: packed.pages, lights: {}, ownership: packed.ownership,
        densities: packed.densities, formats: Array(packed.pages).fill('ktx2')};
      if (!valid() || (latest.round === round && latest.complete === true && !unsigned(latest) && !legacyPages.size)) return false;
      const whole = lights.every(l => !packed.entries[l.device] || matchesEntry(packed.entries[l.device], latest.lights[l.device]) &&
        (!latest.forceRound || latest.lights[l.device]?.forceRound === latest.forceRound));
      if (!whole) return false;
      const next = signed({ ...latest, round, complete: true }); delete next.forceRound;
      next.pageIntegrity = { ...latest.pageIntegrity };
      for (const [page, legacy] of legacyPages) {
        if (!(await legacyUpload(page, legacy, latest))) continue;
        const {bytes} = legacy;
        const r = await api(`${path}/${page}.png`, { method: 'POST', headers: { 'Content-Type': 'image/ktx2' }, body: bytes });
        if (!r.ok) throw new Error('Could not save the lightmap.');
        const saved = await r.json();
        next.pageIntegrity[page] = {size: bytes.length, digest: saved.digest || saved.etag,
          ...(saved.version ? {version: saved.version} : {})};
      }
      await check();
      const r = await api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next) });
      if (!r.ok) throw new Error('Could not save the bake manifest.');
      manifest = next;
      legacyPages.clear();
      return true;
    });
  }
  async function settle() {
    try {
      const result = await settleManifest();
      if (enabled && manifest && packed && valid()) {
        try {
          const copies = placedCopies(plan);
          if (runGrids.size || copies.length) {
            runGridLayout ||= gridLayout(plan);
            const totals = {points:0, bytes:0, ms:0, maskMs:0, foldedOrDropped:0};
            for (const g of runGrids.values()) for (const k of ['points', 'bytes', 'ms', 'maskMs']) totals[k] += g[k] || 0;
            // Stats use plan placement centres (metres); loaded viewer mesh bounds
            // are unavailable in the editor's display:false bake.
            // A partial rebake can still fold against lamps reused from storage.
            for (const l of copies.length ? lights : []) {
              const e = manifest.lights[l.device];
              if (runChunks.has(l.device) || !e?.grid || isStale(l.device)) continue;
              const r = await api(`${path}/grid/${e.grid}.bin`);
              if (!r.ok) throw new Error('Could not read the light-visibility grid for model stats.');
              const bytes = new Uint8Array(await r.arrayBuffer());
              const chunk = await decodeGridChunk(bytes);
              if (!valid()) return result;
              if (chunk.device !== l.device || chunk.layoutHash !== runGridLayout.hash) throw new Error('Grid stats layout mismatch.');
              runChunks.set(l.device, chunk);
              if (!runGrids.size) { totals.points += chunk.indices.length; totals.bytes += bytes.length; }
            }
            const table = emitterTable(lights, new Set(runChunks.keys()), manifest, {plan});
            for (const copy of copies) {
              const centre = new THREE.Vector3(...copy.at);
              const half = new THREE.Vector3(...copy.scale.map(v => Math.max(.01, Math.abs(v) * .1524)));
              centre.y += half.y;
              const box = new THREE.Box3(centre.clone().sub(half), centre.clone().add(half));
              const chosen = chooseEmitters(box, table, {layout:runGridLayout, chunks:runChunks});
              if (chosen.folded || chosen.dropped) totals.foldedOrDropped++;
            }
            grid = {...grid, ...totals};
            onGrid({...grid});
          }
        } catch (error) {
          if (!statsWarned) { statsWarned = true; console.warn('Model lighting stats unavailable:', error); }
          if (valid()) { grid = {...grid, foldedOrDropped:0}; onGrid({...grid}); }
        }
      }
      return result;
    } finally { gridCache.clear(); gridReceipts.clear(); runChunks.clear(); runGrids.clear(); runGridLayout = null; }
  }
  return { staleLights, bakeNext, settle, forcePending: () => forcePending, cancel() { cancelled = true; gridCache.clear(); gridReceipts.clear(); runChunks.clear(); runGrids.clear(); runGridLayout = null; }, progress: () => ({
    done: packed && manifest ? lights.length - lights.filter(l => isStale(l.device)).length : 0,
    total: enabled ? lights.length : 0,
    grid: {...grid},
  }) };
}
