import { request } from './api.js';
// Both the Library and in-place feature slots read this same server catalogue.
export async function readLibraryCatalog() {
  const [library, materials] = await Promise.all([
    request('library'), request('materials', 'GET', undefined, ''),
  ]);
  learn(materials);
  document.dispatchEvent(new CustomEvent('chf-material-catalogue', { detail: materials }));
  return { ...library, ...materials };
}
// Household materials are named by the person; their ids say nothing.
const names = new Map();
const learn = materials => { for (const row of materials?.materials || []) if (row?.id && row.name) names.set(row.id, row.name); };
// For the selection card's lines: the names only, with no catalogue signal.
export async function readMaterialNames() { learn(await request('materials', 'GET', undefined, '')); }
export const materialName = id => names.get(id) || String(id || 'Material').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
