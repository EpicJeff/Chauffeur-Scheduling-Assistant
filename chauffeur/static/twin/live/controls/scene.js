import { controls } from './shared.js';

export function sceneControls(options) {
  const c = controls(options);
  const script = String(options.row?.entity_id || '').startsWith('script.');
  c.text('state', s => c.ring ? (script ? 'Script' : 'Scene') : s?.state || 'unavailable', 'stack');
  c.button('run', 'Run', 'turn_on', {}, c.place('pills'));
  return c.finish();
}
