import { controls, title } from './shared.js';

export function vacuumControls(options) {
  const c = controls(options);
  // At the marker a plain dial: the state, then the vacuum's verbs as pills.
  c.text('state', s => c.ring ? title(s?.state || 'unavailable') : s?.state || 'unavailable', 'stack');
  const pills = c.place('pills');
  for (const [bit, name, label, service] of [[8192, 'start', 'Start', 'start'], [4, 'pause', 'Pause', 'pause'],
    [16, 'return', 'Return to dock', 'return_to_base'], [512, 'locate', 'Locate', 'locate']]) {
    if (!c.has(bit)) continue;
    const node = c.button(name, label, service, {}, pills);
    // Two pills to a row in the dial: the dock verb takes its short name there.
    if (c.ring && name === 'return') { node.textContent = 'Dock'; node.setAttribute('aria-label', label); }
  }
  return c.finish();
}
