import { assignChannels } from './atlas.js';
import { renderPage } from './bake_pass.js';
import { withBakeLease } from './bake_lock.js';

export { encodePage, decodePage } from './codec.js';

export function lightKey(atlas, light, slot, bank) {
  const text = JSON.stringify([atlas.key, light.device, light.at, slot,
    bank.rooms.map(r => [r.room, r.region])]);
  const h = [0x811c9dc5, 0x9e3779b9, 0x85ebca6b, 0xc2b2ae35];
  for (let k = 0; k < text.length; k++) for (let i = 0; i < 4; i++) h[i] = Math.imul(h[i] ^ text.charCodeAt(k), 0x01000193 + i * 2);
  return h.map(x => (x >>> 0).toString(16).padStart(8, '0')).join('');
}

export function bakeLayout(atlas, layout, lights) {
  const slots = assignChannels(atlas.room.rooms, lights), banks = atlas.room.packBanks(lights);
  let offset = atlas.sky.pages;
  const offsets = banks.map(b => { const n = offset; offset += b.pages; return n; });
  const entries = {};
  for (const light of lights) {
    const s = slots[light.device]; if (!s) continue;
    const region = banks[s.bank].rooms.find(r => r.room === s.room)?.region;
    if (!region) continue;
    entries[light.device] = { page: offsets[s.bank] + region.page, channel: s.channel,
      key: lightKey(atlas, light, s, banks[s.bank]) };
  }
  return { slots, banks, offsets, entries, pages: offset,
    densities: { sky: layout.sky.density, room: layout.room.density } };
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
  const packed = bakeLayout(atlas, layout, lights), path = `api/house/bakes/${atlas.key}`;
  const who = owner || [...globalThis.crypto.getRandomValues(new Uint32Array(4))].map(x => x.toString(16)).join('');
  let cancelled = false, manifest = null, done = 0, total = 0, busy = false;
  const unavailable = new Set();
  // Bake lighting now re-bakes the sky and every light, but each keeps its stored entry
  // (same key) until its new bake lands, so panels never drop to real-time mid-run (M6).
  const redo = new Set(force ? ['sky', ...lights.filter(l => packed.entries[l.device]).map(l => l.device)] : []);
  const valid = () => !cancelled && view.plan === plan;
  const readManifest = async () => {
    const response = await api(path);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Could not read the bake manifest (HTTP ${response.status}).`);
    return response.json();
  };
  const isStale = device => packed.entries[device] && (redo.has(device) || manifest.lights[device]?.key !== packed.entries[device].key);
  const ready = enabled ? readManifest().then(async m => {
    manifest = m || { pages: packed.pages, lights: {}, sky: null };
    if (m) {
      const ids = new Set(Object.values(m.lights).map(e => e.page));
      if (m.sky) for (let p = 0; p < atlas.sky.pages; p++) ids.add(p);
      const missing = new Set();
      for (const p of ids) if (!(await exists(api, `${path}/${p}.png`))) missing.add(p);
      manifest = { ...manifest, lights: { ...manifest.lights } };
      for (const [id, e] of Object.entries(manifest.lights)) if (missing.has(e.page)) { unavailable.add(id); delete manifest.lights[id]; }
      if ([...missing].some(p => p < atlas.sky.pages)) manifest.sky = null;
    }
    total = lights.filter(l => isStale(l.device)).length;
  }) : Promise.resolve();
  async function staleLights() {
    await ready;
    return enabled && valid() ? lights.filter(l => isStale(l.device)).map(l => l.device) : [];
  }
  const skyDue = () => !manifest.sky || redo.has('sky');
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
    // Another desk may have baked lights (or the sky) since this one last looked.
    const latest = await readManifest();
    if (latest) {
      for (const [device, e] of Object.entries(latest.lights))
        if (!unavailable.has(device) && !redo.has(device)) manifest.lights[device] = e;
      if (latest.sky && !manifest.sky && !unavailable.has('sky')) manifest.sky = latest.sky;
    }
    const stale = lights.filter(l => isStale(l.device)).map(l => l.device), id = skyDue() ? 'sky' : stale[0];
    if (!id) return null;
    const sky = id === 'sky', light = lights.find(l => l.device === id), s = packed.slots[id];
    const bank = sky ? atlas.sky : packed.banks[s.bank], size = sky ? layout.sky.page : layout.room.page;
    const charts = sky ? bank.charts : bank.charts.filter(c => c.room === s.room);
    const pages = sky ? Array.from({ length: bank.pages }, (_, p) => p) : [...new Set(charts.map(c => c.page))];
    const uploads = [];
    for (const p of pages) {
      const page = p + (sky ? 0 : packed.offsets[s.bank]);
      const mine = charts.filter(c => c.page === p);
      const pixels = await renderPage(view, renderer, mine, size, sky, light, layout, atlas);
      if (!valid()) return null;
      const channels = sky ? [new Uint8Array(size * size)] : await pageData(page, size, 2);
      // Replace only this room's charts, never a neighbour or the other light.
      for (const c of mine) {
        const r = c.rect;
        for (let y = Math.max(0, r.y - 2); y < Math.min(size, r.y + r.h + 2); y++)
          for (let x = Math.max(0, r.x - 2); x < Math.min(size, r.x + r.w + 2); x++) {
            const sx = Math.max(r.x, Math.min(r.x + r.w - 1, x)), sy = Math.max(r.y, Math.min(r.y + r.h - 1, y));
            channels[sky ? 0 : s.channel][y * size + x] = pixels[(sy * size + sx) * 4];
          }
      }
      const bytes = await codec.encode({ width: size, height: size, channels: sky ? [channels[0]] : channels });
      uploads.push({ page, bytes });
    }
    if (sky) {
      // Bank zero reserves unlit rooms too. Publish its empty pages before naming the
      // layout; a later light can use them without moving a room. A page already stored
      // is left alone (M5).
      let empty;
      for (let page = atlas.sky.pages; page < packed.pages; page++) {
        if (await exists(api, `${path}/${page}.png`)) continue;
        if (!empty) empty = await codec.encode({ width: layout.room.page, height: layout.room.page,
          channels: [new Uint8Array(layout.room.page ** 2), new Uint8Array(layout.room.page ** 2)] });
        uploads.push({ page, bytes: empty });
      }
    }
    if (!valid()) return null;
    const next = { ...manifest, pages: packed.pages, densities: packed.densities,
      formats: Array(packed.pages).fill('ktx2'), lights: { ...manifest.lights } };
    for (const [device, entry] of Object.entries(next.lights))
      if (entry.key !== packed.entries[device]?.key || unavailable.has(device)) delete next.lights[device];
    // Sparse banks can change the global offsets of later, unchanged banks.
    // Move their existing bytes rather than re-baking those lights. Read all
    // sources before the first upload so overlapping moves cannot eat data.
    const moves = new Map();
    for (const [device, entry] of Object.entries(next.lights)) {
      const expected = packed.entries[device];
      if (entry.page !== expected.page && !moves.has(expected.page)) {
        const r = await api(`${path}/${entry.page}.png`);
        if (!r.ok) throw new Error('Could not preserve the later light bank.');
        moves.set(expected.page, new Uint8Array(await r.arrayBuffer()));
      }
      next.lights[device] = expected;
    }
    for (const [page, bytes] of moves) uploads.push({ page, bytes });
    if (sky) next.sky = { page: 0, channel: 0, pages: atlas.sky.pages };
    else next.lights[id] = packed.entries[id];
    // Which round this desk baked and whether it is whole (Ruling B15: the editor's chip).
    const left = new Set(redo); left.delete(id);
    next.round = round;
    next.complete = !!next.sky && !left.size && lights.every(l => !packed.entries[l.device] ||
      next.lights[l.device]?.key === packed.entries[l.device].key);
    for (const { page, bytes } of uploads) {
      if (!valid()) return null;
      const r = await api(`${path}/${page}.png`, { method: 'POST', headers: { 'Content-Type': 'image/ktx2' }, body: bytes });
      if (!r.ok) throw new Error('Could not save the lightmap.');
    }
    if (!valid()) return null;
    const r = await api(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(next) });
    if (!r.ok) throw new Error('Could not save the bake manifest.');
    manifest = next; redo.delete(id); if (!sky) done++;
    unavailable.delete(id);
    return id;
  }
  async function bakeNext() {
    await ready;
    if (!enabled || !valid() || busy) return null;
    if (!skyDue() && !lights.some(l => isStale(l.device))) return null;
    busy = true;
    try { return await withBakeLease(api, path, who, valid, bakeStep); } finally { busy = false; }
  }
  // Record that this round's bake is whole when nothing was left to bake (B15).
  async function settle() {
    await ready;
    if (!enabled || !valid() || skyDue() || lights.some(l => isStale(l.device))) return false;
    if (manifest.round === round && manifest.complete === true) return false;
    return withBakeLease(api, path, who, valid, async () => {
      const latest = await readManifest();
      if (!latest || !valid() || (latest.round === round && latest.complete === true)) return false;
      const whole = !!latest.sky && lights.every(l => !packed.entries[l.device] || latest.lights[l.device]?.key === packed.entries[l.device].key);
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
