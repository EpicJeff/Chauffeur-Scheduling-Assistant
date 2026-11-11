"""Exercise the colour wheel, room-builder lifecycle and retargeted hold release.

Run from chauffeur/: python tests/test_twin_ring_edges_js.py
"""
import sys

import twin_live_node_rig as R

DRIVER = r"""
const lamp = {device_id: 'lamp', name: 'Lamp', entity_id: 'light.lamp', kind: 'light', state: 'on',
  attributes: {supported_color_modes: ['color_temp', 'hs'], brightness: 128, hs_color: [30, 50],
    color_temp_kelvin: 3000, min_color_temp_kelvin: 2200, max_color_temp_kelvin: 6500, effect_list: ['Candle']}};
const checks = [];
const check = (name, fn) => checks.push([name, fn]);
const part = name => document.querySelector(`[data-ring] [data-ring-part="${name}"]`);

check('release_retargeted_to_the_new_centre_does_not_toggle', async () => {
  const t = await rig({devices: [lamp]});
  try {
    const at = t.screenOf('lamp'); t.pointer('pointerdown', at); await wait(650);
    const centre = part('center'); assert.ok(centre);
    centre.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, cancelable: true,
      clientX: at[0], clientY: at[1], pointerId: 1}));
    centre.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    await wait(60); assert.deepEqual(t.serviceCalls(), []);
    await press(centre); assert.equal(t.serviceCalls().length, 1);
  } finally { t.cleanup(); }
});

check('wheel_sends_one_colour_and_returns_to_confirmed_state', async () => {
  const t = await rig({devices: [lamp]});
  try {
    await t.hold('lamp'); const wheel = part('wheel');
    key(wheel, 'End'); key(wheel, 'ArrowLeft'); key(wheel, 'ArrowLeft');
    assert.deepEqual(t.serviceCalls(), []); await wait(350);
    assert.deepEqual(t.serviceCalls(), [['light', 'turn_on', {hs_color: [358, 50], entity_id: 'light.lamp'}]]);
    assert.equal(wheel.getAttribute('aria-valuenow'), '358');
    t.calls.length = 0; t.frozen.add('light.lamp');
    key(wheel, 'Home'); await wait(350);
    assert.equal(t.serviceCalls().length, 1);
    assert.equal(wheel.getAttribute('aria-valuenow'), '358');
    assert.deepEqual(t.live.states()['light.lamp'].attributes.hs_color, [358, 50]);
  } finally { t.cleanup(); }
});

check('room_controls_keep_focus_and_confirm_the_shared_light_values', async () => {
  const t = await rig({devices: [lamp]});
  try {
    t.live.openRoom('b', 'r'); const panel = document.getElementById('twin-room-panel');
    const inputs = panel.querySelectorAll('input'); assert.equal(inputs.length, 2);
    const brightness = inputs.find(n => /brightness$/.test(n.getAttribute('aria-label')));
    const temperature = inputs.find(n => /temperature$/.test(n.getAttribute('aria-label')));
    assert.deepEqual([temperature.min, temperature.max, temperature.value], ['2200', '6500', '3000']);
    assert.ok(panel.querySelector('[role="slider"]'), 'the same colour wheel is available in the row');
    brightness.focus(); brightness.value = '40'; brightness.dispatchEvent(new Event('input'));
    t.states['light.lamp'].attributes.color_temp_kelvin = 4000; await t.live.refresh();
    assert.equal(panel.querySelectorAll('input')[0], brightness);
    assert.equal(document.activeElement, brightness); assert.equal(brightness.value, '40');
    t.frozen.add('light.lamp'); brightness.dispatchEvent(new Event('change')); await wait(80);
    assert.deepEqual(t.serviceCalls(), [['light', 'turn_on', {brightness_pct: 40, entity_id: 'light.lamp'}]]);
    assert.equal(brightness.value, '50', 'an ignored row command returns to confirmed brightness');
  } finally { t.cleanup(); }
});

check('closing_and_stopping_cancel_pending_arc_commands', async () => {
  const t = await rig({devices: [lamp]});
  try {
    await t.hold('lamp'); key(part('brightness'), 'ArrowUp'); key(document, 'Escape');
    await wait(350); assert.deepEqual(t.serviceCalls(), []);
    await t.hold('lamp'); key(part('brightness'), 'ArrowUp'); t.live.stop();
    await wait(350); assert.deepEqual(t.serviceCalls(), []);
  } finally { t.cleanup(); }
});

check('fan_ring_keeps_the_existing_toggle_and_confirmed_state', async () => {
  const t = await rig({devices: [{device_id: 'fan', name: 'Fan', entity_id: 'fan.ceiling', kind: 'fan', state: 'off'}]});
  try {
    await t.hold('fan');
    const toggle = () => document.querySelector('[data-ring] [role="switch"]');
    await press(toggle());
    assert.deepEqual(t.serviceCalls(), [['fan', 'toggle', {entity_id: 'fan.ceiling'}]]);
    assert.equal(toggle().getAttribute('aria-checked'), 'true');
  } finally { t.cleanup(); }
});

let passed = 0;
for (const [name, fn] of checks) {
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + error.stack); }
}
assert.deepEqual(domErrors, []);
assert.deepEqual(escaped, []);
console.log(`${passed}/${checks.length} passed`);
process.exit(passed === checks.length ? 0 : 1);
"""


if __name__ == '__main__':
    sys.exit(1 if R.run(DRIVER, prefix='chauffeur_ring_edges_', timeout=30) else 0)
