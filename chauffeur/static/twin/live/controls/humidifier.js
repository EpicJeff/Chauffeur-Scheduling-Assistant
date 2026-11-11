import { controls } from './shared.js';

export function humidifierControls(options) {
  const c = controls(options), a = c.attrs;
  c.toggle('center', 'Power', s => s?.state === 'on', 'toggle');
  c.slider('target', 'Humidity', a.min_humidity ?? 0, a.max_humidity ?? 100, 1, s => s?.attributes?.humidity,
    'set_humidity', v => ({humidity: v}), false, '%');
  if (c.has(1)) c.chips('modes', 'Mode', a.available_modes, s => s?.attributes?.mode, 'set_mode', 'mode');
  return c.finish();
}
