import { controls } from './shared.js';

export function coverControls(options) {
  const c = controls(options);
  // Older integrations omit the mask but still expose open/close.
  const legacy = c.attrs.supported_features == null;
  if (c.has(1) || legacy) c.button('open', 'Open', 'open_cover');
  if (c.has(8)) c.button('stop', 'Stop', 'stop_cover');
  if (c.has(2) || legacy) c.button('close', 'Close', 'close_cover');
  c.text('state', s => s?.state || 'unavailable', true);
  if (c.has(4)) c.slider('position', 'Position', 0, 100, 1, s => s?.attributes?.current_position,
    'set_cover_position', v => ({position: v}), false, '%');
  if (c.has(128)) c.slider('tilt', 'Tilt', 0, 100, 1, s => s?.attributes?.current_tilt_position,
    'set_cover_tilt_position', v => ({tilt_position: v}), true, '%');
  return c.finish();
}
