import { controls } from './shared.js';

export function numberControls(options) {
  const c = controls(options), a = c.attrs;
  c.slider('value', 'Value', a.min ?? 0, a.max ?? 100, a.step || 1,
    s => Number(s?.state), 'set_value', value => ({value}), false, a.unit_of_measurement || '');
  return c.finish();
}

export function selectControls(options) {
  const c = controls(options);
  c.chips('options', 'Option', c.attrs.options, s => s?.state, 'select_option', 'option');
  return c.finish();
}

export function buttonControls(options) {
  const c = controls(options);
  c.button('press', options.row.name, 'press');
  return c.finish();
}

export function sirenControls(options) {
  const c = controls(options);
  c.toggle('accessory', options.row.name, s => s?.state === 'on',
    s => s?.state === 'on' ? 'turn_off' : 'turn_on', {}, options.row.name);
  return c.finish();
}

export function valveControls(options) {
  const c = controls(options);
  if (c.has(1)) c.button('open', 'Open', 'open_valve');
  if (c.has(2)) c.button('close', 'Close', 'close_valve');
  if (c.has(4)) c.slider('position', 'Position', 0, 100, 1,
    s => s?.attributes?.current_position, 'set_valve_position', position => ({position}), false, '%');
  if (c.has(8)) c.button('stop', 'Stop', 'stop_valve');
  return c.finish();
}
