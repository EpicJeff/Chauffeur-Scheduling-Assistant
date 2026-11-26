// Shared by visualizations as well as the selector; strings retain the embed API.
export const MODE_STORAGE_KEY = 'chauffeur.twin.modes.v1';
export const modeShows = (selection, id) => selection === 'all' || selection === id
  || (selection instanceof Set ? selection.has(id) : Array.isArray(selection) && selection.includes(id));

export function modeName(selection, ids) {
  if (ids.every(id => selection.has(id))) return 'all';
  return selection.size === 0 ? 'none' : selection.size === 1 ? [...selection][0] : 'custom';
}

export function readModes(ids) {
  try {
    const saved = JSON.parse(window.localStorage.getItem(MODE_STORAGE_KEY));
    if (Array.isArray(saved) && saved.every(id => ids.includes(id))) return new Set(saved);
  } catch { /* Storage may be disabled, unavailable or corrupt. */ }
  return new Set(ids);
}

export function saveModes(selection) {
  try { window.localStorage.setItem(MODE_STORAGE_KEY, JSON.stringify([...selection])); }
  catch { /* The live controls still work without device storage. */ }
}
