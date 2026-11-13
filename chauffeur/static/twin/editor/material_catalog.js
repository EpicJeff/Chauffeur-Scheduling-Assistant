import { request } from './api.js';
// Both the Library and in-place feature slots read this same server catalogue.
export const readLibraryCatalog = () => request('library');
export const materialName = id => String(id || 'Material').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
