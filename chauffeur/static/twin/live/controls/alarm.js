import { controls, element, title } from './shared.js';

export function alarmControls(options) {
  const c = controls(options), a = c.attrs;
  async function code(arm) {
    if (!a.code_format || arm && !a.code_arm_required) return {};
    const value = await window.promptInput('Alarm code', 'Enter your alarm code.', {type: 'password'});
    return value == null || value === '' ? null : {code: value};
  }
  // At the marker a plain dial: the state, then Disarm and one Arm per supported mode as pills.
  if (c.ring) c.text('state', s => title(s?.state || 'unavailable'), 'stack');
  const pills = c.place('pills');
  const disarm = c.button('disarm', 'Disarm', 'alarm_disarm', () => code(false), pills);
  const group = c.part(element('div'), 'arm'); group.className = c.ring ? 'twin-alarm-arm' : 'twin-light-effects';
  pills.append(group);
  const arms = [];
  for (const [bit, mode] of [[1, 'home'], [2, 'away'], [4, 'night'], [16, 'custom_bypass'], [32, 'vacation']]) {
    if (!c.has(bit) && !(a.supported_features == null && bit <= 2)) continue;
    arms.push([mode, c.button('arm-choice', `Arm ${mode.replace(/_/g, ' ')}`, 'alarm_arm_' + mode, () => code(true), group)]);
  }
  if (!c.ring) c.text('state', s => s?.state || 'unavailable', c.root);
  // The verb matching the confirmed state reads as current, the way a chosen chip does.
  else c.watch(s => {
    disarm.toggleAttribute('data-current', s?.state === 'disarmed');
    for (const [mode, node] of arms) node.toggleAttribute('data-current', s?.state === 'armed_' + mode);
  });
  return c.finish();
}
