import { controls } from './shared.js';

export function waterHeaterControls(options) {
  const c = controls(options), a = c.attrs;
  if (c.has(8)) c.toggle('center', 'Power', s => s?.state !== 'off', s => s?.state === 'off' ? 'turn_on' : 'turn_off');
  if (c.has(1)) c.slider('target', 'Target', a.min_temp ?? 30, a.max_temp ?? 90, a.target_temp_step || 1,
    s => s?.attributes?.temperature, 'set_temperature', v => ({temperature: v}));
  if (c.has(2)) c.chips('modes', 'Mode', a.operation_list, s => s?.attributes?.operation_mode || s?.state,
    'set_operation_mode', 'operation_mode');
  return c.finish();
}
