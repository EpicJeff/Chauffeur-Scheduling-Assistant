import { controls } from './shared.js';

export function lockControls(options) {
  const c = controls(options);
  c.text('state', s => s?.state || 'unavailable', true);
  c.button('lock', 'Lock', 'lock'); c.button('unlock', 'Unlock', 'unlock');
  return c.finish();
}
