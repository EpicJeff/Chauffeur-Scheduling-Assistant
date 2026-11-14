import { request } from './api.js';
// Both the Library and in-place feature slots read this same server catalogue.
export async function readLibraryCatalog() {
  const [library, materials] = await Promise.all([
    request('library'), request('materials', 'GET', undefined, ''),
  ]);
  return { ...library, ...materials };
}
export const materialName = id => String(id || 'Material').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
