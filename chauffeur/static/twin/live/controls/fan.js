import { controls } from './shared.js';

export function fanControls(options) {
  const c = controls(options), a = c.attrs;
  c.toggle('center', 'Power', s => s?.state === 'on', 'toggle');
  if (c.has(1)) c.slider('speed', 'Speed', 0, 100, a.percentage_step || 1, s => s?.attributes?.percentage,
    'set_percentage', v => ({percentage: Math.round(v)}), false, '%');
  if (c.has(2)) c.toggle('oscillate', 'Oscillate', s => s?.attributes?.oscillating, 'oscillate',
    s => ({oscillating: !s?.attributes?.oscillating}));
  if (c.has(4)) c.button('direction', 'Reverse direction', 'set_direction',
    s => ({direction: s?.attributes?.direction === 'forward' ? 'reverse' : 'forward'}));
  if (c.has(8)) c.chips('presets', 'Preset', a.preset_modes, s => s?.attributes?.preset_mode, 'set_preset_mode', 'preset_mode');
  return c.finish();
}
