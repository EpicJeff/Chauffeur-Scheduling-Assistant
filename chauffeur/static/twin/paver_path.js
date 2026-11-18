import { paverLayout, paverSettings } from './paver_layout.js';

// Yard surfaces and lawn must share the same layout, including a cap refusal.
// Recheck the signature because card changes can mutate the authored record.
const layouts = new WeakMap();
const warned = new Set();
export function yardPaverLayout(path) {
  if (!paverSettings(path)) return null;
  const key = JSON.stringify([path.id, path.points, path.width, path.corner, path.radius, path.smooth, path.pavers]);
  const old = layouts.get(path);
  if (old?.key === key) return old.layout;
  let layout;
  try { layout = paverLayout(path); }
  catch (error) {
    if (error.message !== 'Use larger pavers or a shorter path.') throw error;
    if (!warned.has(key)) {
      console.warn('Paver path ' + (path.id || '') + ': ' + error.message + ' Drawing a solid path.');
      warned.add(key);
    }
    layout = null;
  }
  layouts.set(path, {key, layout});
  return layout;
}
