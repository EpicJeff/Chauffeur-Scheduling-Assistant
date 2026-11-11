import { controls } from './shared.js';

export function climateControls(options) {
  const c = controls(options), a = c.attrs;
  const min = a.min_temp ?? 0, max = a.max_temp ?? 100, step = a.target_temp_step || 1;
  const range = options.state?.state === 'heat_cool' && c.has(2);
  if (range) {
    c.slider('target-low', 'Low', min, max, step, s => s?.attributes?.target_temp_low, 'set_temperature',
      (v, s) => ({target_temp_low: Math.min(v, s.attributes.target_temp_high), target_temp_high: s.attributes.target_temp_high}));
    c.slider('target-high', 'High', min, max, step, s => s?.attributes?.target_temp_high, 'set_temperature',
      (v, s) => ({target_temp_low: s.attributes.target_temp_low, target_temp_high: Math.max(v, s.attributes.target_temp_low)}), true);
  } else if (c.has(1) || Number.isFinite(a.temperature)) {
    c.slider('target', 'Target', min, max, step, s => s?.attributes?.temperature, 'set_temperature', v => ({temperature: v}));
    if (options.surface !== 'ring' && !options.compact) {
      for (const [label, delta] of [['Lower', -step], ['Raise', step]]) {
        const node = c.button(label.toLowerCase(), label, 'set_temperature', s => {
          const value = Number((s.attributes.temperature + delta).toFixed(3));
          return value >= min && value <= max ? {temperature: value} : null;
        });
        c.watch(s => { node.disabled = !options.row.offered || !Number.isFinite(s?.attributes?.temperature)
          || s.attributes.temperature + delta < min || s.attributes.temperature + delta > max; });
      }
    }
  }
  c.text('current', s => `Current ${s?.attributes?.current_temperature ?? '—'}`, true);
  c.text('action', s => s?.attributes?.hvac_action || 'idle', true);
  c.chips('modes', 'Mode', a.hvac_modes, s => s?.state, 'set_hvac_mode', 'hvac_mode');
  if (c.has(8)) c.chips('fan-modes', 'Fan', a.fan_modes, s => s?.attributes?.fan_mode, 'set_fan_mode', 'fan_mode');
  if (c.has(16)) c.chips('presets', 'Preset', a.preset_modes, s => s?.attributes?.preset_mode, 'set_preset_mode', 'preset_mode');
  return c.finish();
}
