import { controls } from './shared.js';

export function sceneControls(options) {
  const c = controls(options);
  c.text('state', s => s?.state || 'unavailable', true);
  c.button('run', 'Run', 'turn_on');
  return c.finish();
}
