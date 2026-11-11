import { controls, title } from './shared.js';

export function coverControls(options) {
  const c = controls(options);
  // Older integrations omit the mask but still expose open/close.
  const legacy = c.attrs.supported_features == null;
  const arcs = c.has(4) || c.has(128);
  const slide = () => {
    if (c.has(4)) c.slider('position', 'Position', 0, 100, 1, s => s?.attributes?.current_position,
      'set_cover_position', v => ({position: v}), false, '%');
    if (c.has(128)) c.slider('tilt', 'Tilt', 0, 100, 1, s => s?.attributes?.current_tilt_position,
      'set_cover_tilt_position', v => ({tilt_position: v}), true, '%');
  };
  // At the marker, with an arc the verbs are a row of round buttons across the dial's middle
  // (HA's cover controls: up, stop, down); without one, a plain dial names the state above them.
  if (c.ring) slide();
  if (c.ring && !arcs) c.text('state', s => title(s?.state || 'unavailable'), 'stack');
  const where = !c.ring ? c.root : arcs ? c.place('row') : c.place('pills');
  const open = (c.has(1) || legacy) && c.button('open', 'Open', 'open_cover', {}, where, arcs && 'up');
  if (c.has(8)) c.button('stop', 'Stop', 'stop_cover', {}, where, arcs && 'stop');
  const close = (c.has(2) || legacy) && c.button('close', 'Close', 'close_cover', {}, where, arcs && 'down');
  // A plain dial's verb that matches the confirmed state reads as current (lock.js).
  if (c.ring && !arcs) c.watch(s => {
    if (open) open.toggleAttribute('data-current', s?.state === 'open');
    if (close) close.toggleAttribute('data-current', s?.state === 'closed');
  });
  if (!c.ring) { c.text('state', s => s?.state || 'unavailable', c.root); slide(); }
  else if (arcs && !c.has(128)) c.text('state', s => title(s?.state || 'unavailable'), 'below');
  return c.finish();
}
