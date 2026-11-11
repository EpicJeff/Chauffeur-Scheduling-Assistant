import { controls, element } from './shared.js';

export function alarmControls(options) {
  const c = controls(options), a = c.attrs;
  const group = c.part(element('div'), 'arm'); group.className = 'twin-light-effects';
  async function code(arm) {
    if (!a.code_format || arm && !a.code_arm_required) return {};
    const value = await window.promptInput('Alarm code', 'Enter your alarm code.', {type: 'password'});
    return value == null || value === '' ? null : {code: value};
  }
  for (const [bit, mode] of [[1, 'home'], [2, 'away'], [4, 'night'], [16, 'custom_bypass'], [32, 'vacation']]) {
    if (!c.has(bit) && !(a.supported_features == null && bit <= 2)) continue;
    const node = c.button('arm-choice', `Arm ${mode.replace(/_/g, ' ')}`, 'alarm_arm_' + mode, () => code(true));
    group.append(node);
  }
  // The builder's side card is attached at finish; group the arm buttons inside it.
  const disarm = c.button('disarm', 'Disarm', 'alarm_disarm', () => code(false));
  disarm.parentElement.append(group);
  c.text('state', s => s?.state || 'unavailable', true);
  return c.finish();
}
