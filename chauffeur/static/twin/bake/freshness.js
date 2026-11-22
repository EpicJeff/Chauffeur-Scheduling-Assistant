import { fingerprint } from './geometry_key.js';

// Exact freshness inside a pressed run and in the unchanged viewer.
export function matchesEntry(expected, stored) {
  return !!expected && !!stored && expected.key === stored.key && expected.location === stored.location &&
    expected.channel === stored.channel && expected.scale === stored.scale &&
    JSON.stringify(expected.pages) === JSON.stringify(stored.pages);
}

export function pageDamage(manifest, page, digest, size) {
  const saved = manifest?.pageIntegrity?.[page];
  return saved && ((saved.digest && digest && saved.digest !== digest) ||
    (size != null && saved.size !== size)) ? `Lightmap page ${page}: damaged stored page` : null;
}
// Chip-only evidence. Never walks geometry, computes reach or assigns channels.
// The recorded ownership and the entire light set make additions/removals
// conservative; a press still uses matchesEntry to decide what actually bakes.
export function cheapSignatures(lights, ownership, entries = {}) {
  const hash = fingerprint();
  hash.add(JSON.stringify(['editor-lights-1', lights.map(l => l.device).sort(), ownership || null]));
  const slots = hash.key();
  return Object.fromEntries(lights.map(l => {
    const h = fingerprint(), e = entries[l.device];
    h.add(JSON.stringify([slots, l.device, l.members || null, l.at, l.building, l.level, l.room, !!l.yard,
      !!l.absolute, l.range ?? null, l.kind || 0, l.signature || null, e?.channel,
      l.kind === 3 ? e?.scale : null]));
    return [l.device, h.key()];
  }));
}
