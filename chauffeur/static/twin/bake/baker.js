import { assignChannels, CHANNEL_FALLBACK, CHART_STATS, fingerprint } from './atlas.js';
import { renderPage, addRoomBounceAcrossPages, dilateCharts } from './bake_pass.js';
import { withBakeLease } from './bake_lock.js';
import { reachLights } from './reach.js';
import { encodeSlots, decodeSlots, sameSlots } from './slots.js';

export { encodePage, decodePage } from './codec.js';

export function lightKey(atlas, light, slot, bank) {
  const hash=fingerprint();
  hash.add(JSON.stringify(['light-slots-7',light.reach || atlas.key,light.device,light.at]));
  if (slot.assignments) {
    const ranking=[...slot.assignments].sort((a,b)=>a.chartKey<b.chartKey?-1:a.chartKey>b.chartKey?1:0), rank=new Uint8Array(2);
    for (const a of ranking) {
      hash.add(a.chartKey);rank[0]=a.bank;rank[1]=a.channel;hash.add(rank);
    }
  } else hash.add(JSON.stringify([slot.bank,slot.channel]));
  return hash.key();
}

export function bakeLayout(atlas, layout, lights, history) {
  lights = reachLights(atlas.room, lights);
  const slots = assignChannels(atlas.room.rooms, lights, decodeSlots(history,atlas.room.charts.length)), banks = atlas.room.packBanks(lights, slots);
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
      location: location.key(),
      key: lightKey(atlas, light, s, banks[s.bank]) };
  }
  return { slots, banks, offsets, entries, pages: offset, fallback: slots[CHANNEL_FALLBACK],
    ownership:encodeSlots(slots,atlas.room.charts.length),
    ranking:slots[CHART_STATS] || {worstDroppedFraction:0,worstChart:null,droppedCharts:0},
    densities: { room: layout.room.density } };
}

// Whether a stored page exists, without downloading it (M5): If-None-Match: * answers
// 304 for any stored page. Only a 404 is "missing"; any other failure throws (I7).
async function exists(api, url) {
  const r = await api(url, { headers: { 'If-None-Match': '*' } });
  if (r.status === 304 || r.ok) return true;
  if (r.status === 404) return false;
  throw new Error(`Could not read the lightmap (HTTP ${r.status}).`);
}

export function createBaker(view, { renderer, atlas, layout, lights, api, codec, force = false,
  round = view.round ?? null, owner = null }) {
  const plan = view.plan, enabled = ['high', 'max'].includes(view.tier);
  let packed, assignmentHistory;
  const path = `api/house/bakes/${atlas.key}`;
  const who = owner || [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('');
  let cancelled = false, manifest = null, done = 0, total = 0, busy = false;
  const unavailable = new Set();
  // Bake lighting now re-bakes every light, but each keeps its stored entry
  // (same key) until its new bake lands, so panels never drop to real-time mid-run (M6).
  const redo = new Set();
  const valid = () => !cancelled && view.plan === plan;
  const readManifest = async () => {
    const response = await api(path);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Could not read the bake manifest (HTTP ${response.status}).`);
    return response.json();
  };
  const isStale = device => packed.entries[device] && (redo.has(device) || manifest.lights[device]?.key !== packed.entries[device].key ||
    manifest.lights[device]?.location !== packed.entries[device].location);
  const ready = enabled ? readManifest().then(async m => {
    assignmentHistory=m?.ownership;
    packed=bakeLayout(atlas,layout,lights,assignmentHistory);
    if(force) for(const l of lights) if(packed.entries[l.device]) redo.add(l.device);
    manifest = m || { pages: packed.pages, lights: {} };
    if (m) {
      const ids = new Set(Object.values(m.lights).flatMap(e => e.pages || [e.page]));
      const missing = new Set();
      for (const p of ids) if (!(await exists(api, `${path}/${p}.png`))) missing.add(p);
      manifest = { ...manifest, lights: { ...manifest.lights } };
      for (const [id, e] of Object.entries(manifest.lights)) if ((e.pages || [e.page]).some(p => missing.has(p))) { unavailable.add(id); delete manifest.lights[id]; }
    }
    total = lights.filter(l => isStale(l.device)).length;
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
      const decoded = await codec.decode(new Uint8Array(await r.arrayBuffer()));
      if (decoded.width === size && decoded.height === size) return decoded.channels;
    } else if (r.status !== 404) throw new Error(`Could not read the lightmap (HTTP ${r.status}).`);
    return Array.from({ length: count }, () => new Uint8Array(size * size));
  }
  async function bakeStep() {
    if (!valid()) return null;
    // Another desk may have baked lights since this one last looked.
    const latest = await readManifest();
    if(latest?.ownership && !sameSlots(latest.ownership,assignmentHistory)) {
      assignmentHistory=latest.ownership;
      packed=bakeLayout(atlas,layout,lights,assignmentHistory);
    }
    if (latest) {
      for (const [device, e] of Object.entries(latest.lights))
        if (!unavailable.has(device) && !redo.has(device)) manifest.lights[device] = e;
    }
    const stale = lights.filter(l => isStale(l.device)).map(l => l.device), id = stale[0];
    if (!id) return null;
    const light = lights.find(l => l.device === id), s = packed.slots[id];
    const size = layout.room.page;
    const owned=new Map(s.assignments?.map(a=>[a.chart,a]));
    const charts = packed.banks.flatMap(bank=>bank.charts.flatMap(c=>{
      const a=owned.get(c.id);
      return a?.bank===bank.bank || !s.assignments && bank.bank===s.bank && (s.receivers || [s.room]).includes(c.room)
        ? [{...c,page:c.page+packed.offsets[bank.bank],channel:a?.channel ?? s.channel}] : [];
    }));
    const pages = [...new Set(charts.map(c => c.page))];
    const uploads = [], rendered = [];
    for (const p of pages) {
      const page = p;
      const mine = charts.filter(c => c.page === p);
      const pixels = await renderPage(view, renderer, mine, size, light, layout, atlas, {deferBounce:true});
      if (!valid()) return null;
      rendered.push({page, charts:mine, bytes:pixels});
    }
    addRoomBounceAcrossPages(rendered,size);
    // Pad each chart's unwritten texels after bounce, so padding carries the bounced value too.
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
      next.lights[device] = expected;
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
    next.lights[id] = packed.entries[id];
    // Which round this desk baked and whether it is whole (Ruling B15: the editor's chip).
    const left = new Set(redo); left.delete(id);
    next.round = round;
    next.complete = !left.size && lights.every(l => !packed.entries[l.device] ||
      next.lights[l.device]?.key === packed.entries[l.device].key);
    for (const { page, bytes } of uploads) {
      if (!valid()) return null;
      const r = await api(`${path}/${page}.png`, { method: 'POST', headers: { 'Content-Type': 'image/ktx2' }, body: bytes });
      if (!r.ok) throw new Error('Could not save the lightmap.');
    }
    if (!valid()) return null;
    const r = await api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(next) });
    if (!r.ok) throw new Error('Could not save the bake manifest.');
    manifest = next; assignmentHistory=packed.ownership; redo.delete(id); done++;
    unavailable.delete(id);
    return id;
  }
  async function bakeNext() {
    await ready;
    if (!enabled || !valid() || busy) return null;
    if (!lights.some(l => isStale(l.device))) return null;
    busy = true;
    try { return await withBakeLease(api, path, who, valid, bakeStep); } finally { busy = false; }
  }
  // Record that this round's bake is whole when nothing was left to bake (B15).
  async function settle() {
    await ready;
    if (!enabled || !valid() || lights.some(l => isStale(l.device))) return false;
    if (manifest.round === round && manifest.complete === true) return false;
    return withBakeLease(api, path, who, valid, async () => {
      const latest = await readManifest();
      if (!latest || !valid() || (latest.round === round && latest.complete === true)) return false;
      const whole = lights.every(l => !packed.entries[l.device] || latest.lights[l.device]?.key === packed.entries[l.device].key);
      if (!whole) return false;
      const r = await api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...latest, round, complete: true }) });
      if (!r.ok) throw new Error('Could not save the bake manifest.');
      manifest = { ...latest, round, complete: true };
      return true;
    });
  }
  return { staleLights, bakeNext, settle, cancel() { cancelled = true; }, progress: () => ({ done, total }) };
}
