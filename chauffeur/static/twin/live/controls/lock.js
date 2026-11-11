import { controls, title } from './shared.js';

export function lockControls(options) {
  const c = controls(options);
  // At the marker a plain dial: the state, then Lock and Unlock as pills.
  c.text('state', s => c.ring ? title(s?.state || 'unavailable') : s?.state || 'unavailable', 'stack');
  const pills = c.place('pills');
  const lock = c.button('lock', 'Lock', 'lock', {}, pills), unlock = c.button('unlock', 'Unlock', 'unlock', {}, pills);
  // The verb matching the confirmed state reads as current, the way a chosen chip does.
  if (c.ring) c.watch(s => {
    lock.toggleAttribute('data-current', s?.state === 'locked');
    unlock.toggleAttribute('data-current', s?.state === 'unlocked');
  });
  return c.finish();
}
