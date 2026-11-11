import { controls } from './shared.js';

export function vacuumControls(options) {
  const c = controls(options);
  c.text('state', s => s?.state || 'unavailable', true);
  for (const [bit, name, label, service] of [[8192, 'start', 'Start', 'start'], [4, 'pause', 'Pause', 'pause'],
    [16, 'return', 'Return to dock', 'return_to_base'], [512, 'locate', 'Locate', 'locate']]) {
    if (c.has(bit)) c.button(name, label, service);
  }
  return c.finish();
}
