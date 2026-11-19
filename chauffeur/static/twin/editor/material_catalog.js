import { request } from './api.js';
import { resolveSurfaceMaterial } from '../surface_material.js';

// The renderer owns inheritance; editor owners only describe their receiving slot.
export function surfaceDescription(plan, surface, kit = {}) {
  const resolution = resolveSurfaceMaterial(plan, { ...surface, kit });
  const current = describeMaterial({...resolution.ref, id:resolution.source.id}, kit);
  // Two kit roles can share a texture asset while keeping different tints.
  current.color = describeMaterial(resolution.ref, kit)?.color || current.color;
  const name = materialName(resolution.source.id);
  const inherited = !surface.ref?.id;
  const prefix = { level: 'From this floor', room: 'From the room', surface:surface.parentLabel }[resolution.source.kind] || 'House default';
  return { ...resolution, current, inherited, text: inherited ? `${prefix}: ${name}` : `${name}, set here` };
}
// Both the Library and in-place feature slots read this same server catalogue.
export async function readLibraryCatalog() {
  const [library, materials] = await Promise.all([
    request('library'), request('materials', 'GET', undefined, ''),
  ]);
  learn(materials);
  document.dispatchEvent(new CustomEvent('chf-material-catalogue', { detail: materials }));
  // The server's placement kind stays furniture. Model slots also need the
  // manifest's door/window classification, without changing 3D drop behavior.
  const items = (library.items || []).map(entry => {
    const manifest = window.twinManifest?.[entry.id];
    return { ...entry, ...(manifest?.object_kind ? { object_kind: manifest.object_kind } : {}),
      ...(manifest?.category ? { category: manifest.category } : {}) };
  });
  return { ...library, ...materials, items };
}
// Household materials are named by the person; their ids say nothing.
const names = new Map(), records = new Map();
const learn = materials => { for (const row of materials?.materials || []) if (row?.id) {
  records.set(row.id, row); if (row.name) names.set(row.id, row.name);
} };
// For the selection card's lines: the names only, with no catalogue signal.
export async function readMaterialNames() { learn(await request('materials', 'GET', undefined, '')); }
export const materialName = id => names.get(id) || String(id || 'Material').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
export function describeMaterial(ref, kit = {}) {
  if (!ref) return null;
  const id = ref.id || ref.asset, entry = records.get(id), role = kit.materials?.[id]
    || Object.values(kit.materials || {}).find(row => row.asset === id);
  return { id, name: entry?.name || materialName(id), thumb: entry?.thumbnail_url || null,
    color: ref.color || entry?.color || role?.color };
}
