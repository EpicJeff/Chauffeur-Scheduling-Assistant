"""Node checks for the ring of controls at a marker and the light's controls
(Task 3 of docs/superpowers/plans/2026-11-11-twin-device-controls.md; brief
.superpowers/sdd/2026-11-11-twin-device-controls/task-3-brief.md; spec
docs/superpowers/specs/2026-11-11-twin-device-controls-design.md decisions 2, 3, 6
and the user's answers in section 5; plan Review Focus 2, 3 and 4).

The fake DOM and the rig (a mounted live layer over a fake view, a fake Home
Assistant behind api() and window.chfControlFetch that applies what it is sent,
gestures at a marker's projected centre on the canvas) are
tests/twin_live_node_rig.py's; read its docstring. A hold is a pointerdown held
still for 650 ms, then pointerup and (as a mouse does) click at the same spot.

What the live layer gives (the hooks this file assumes; keep them few):
- live.ring() -> null when no ring is open, else {device_id, x, y}: the device
  whose ring is open and the ring's anchor in client pixels, which is the
  marker's projected centre at the current camera.
- The ring is one element carrying the attribute data-ring (and
  data-device-id), attached to the document while open; closing removes or
  hides it.
- Its parts carry data-ring-part:
    center       on/off, role="switch" with aria-checked from the CONFIRMED state
                 (the part itself or one element inside it);
    brightness   an arc, role="slider", aria-valuemin/max/now in percent
                 (aria-valuemax 100; aria-valuenow = round(brightness / 255 * 100));
                 it sends light.turn_on {brightness_pct};
    temperature  an arc, role="slider" in kelvin, aria-valuemin/max from
                 min_color_temp_kelvin / max_color_temp_kelvin and aria-valuenow
                 from color_temp_kelvin; it sends light.turn_on {color_temp_kelvin};
    swatches     buttons, each with an aria-label naming its colour, one of them
                 Blue; Blue sends light.turn_on {rgb_color: [0, 0, 255]} or
                 {hs_color: [240, 100]};
    wheel        the colour wheel (present or not; its gesture is not pinned here);
    effects      one button per effect_list entry, named by it; it sends
                 light.turn_on {effect}.
  Which parts a light shows follows supported_color_modes: onoff alone shows only
  the centre; any other mode adds brightness; color_temp adds temperature; hs, xy,
  rgb, rgbw or rgbww add swatches and the wheel; a non-empty effect_list adds effects.
- An arc is a WAI-ARIA slider: ArrowUp/ArrowRight raise it a step, ArrowDown/
  ArrowLeft lower it; pointer drags on it set it too. While a person moves it the
  arc shows the value they are choosing; one service call goes out once they have
  stopped (settled within 1 s of the last input), carrying the final value; after
  that the arc shows the confirmed state again (a light that ignored the call
  snaps back).
- Gestures (user, 2026-11-11): a tap on a light, switch, outlet or fan toggles it
  through live.control and opens no ring; a hold (500 ms) opens the ring and
  sends nothing, including the click a browser sends when the finger lifts, which
  lands on the ring's own centre (Chromium does this on a touch screen); a press
  that moves (a camera orbit) never opens a ring and never
  toggles. When markers overlap, the one whose centre is nearest the finger is
  the one acted on. A switch's ring is its on/off centre.
- A device the grid does not offer: a tap sends nothing; a hold opens its ring,
  which shows the state and whose every control is disabled (disabled or
  aria-disabled="true"); nothing is sent from it.
- The ring follows the marker when the camera moves (live.draw / view.render).
- Escape, a tap on the scene away from the ring, or a tap elsewhere on the page
  closes it; a tap on the ring itself does not.

Every control goes through live.control (the fake window.chfControlFetch records
{domain, service, data}); no browser dialog is used.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_ring_js.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_live_node_rig as R  # noqa: E402

DRIVER = r"""
const ringNode = () => document.querySelector('[data-ring]');
const ringShown = () => { const node = ringNode(); return !!node && shown(node); };
const part = name => ringNode()?.querySelector(`[data-ring-part="${name}"]`) || null;
const role = (node, name) => !node ? null : node.matches(`[role="${name}"]`) ? node : node.querySelector(`[role="${name}"]`);
const slider = name => role(part(name), 'slider');
const centre = () => role(part('center'), 'switch');
const now = node => Number(node.getAttribute('aria-valuenow'));
const settle = () => wait(1200);
const openRing = () => { assert.equal(typeof globalThis.__live?.ring, 'function', 'live.ring() exists'); return globalThis.__live.ring(); };
async function mount(devices, options) {
  const t = await rig({devices, ...options});
  globalThis.__live = t.live;
  return t;
}
const LAMP = {device_id: 'lamp', name: 'Counter lamp', entity_id: 'light.lamp', kind: 'light', state: 'on',
  attributes: {brightness: 128, supported_color_modes: ['color_temp', 'hs'], color_mode: 'hs', hs_color: [30, 50],
    min_color_temp_kelvin: 2200, max_color_temp_kelvin: 6500, effect_list: ['Rainbow', 'Candle'], effect: null}};
const TOGGLES = [
  LAMP,
  {device_id: 'plug', name: 'Coffee plug', entity_id: 'switch.coffee', kind: 'switch', state: 'off', attributes: {}},
  {device_id: 'kettle', name: 'Kettle', entity_id: 'switch.kettle', kind: 'outlet', state: 'off', attributes: {device_class: 'outlet'}},
  {device_id: 'fan', name: 'Ceiling fan', entity_id: 'fan.ceiling', kind: 'fan', state: 'off', attributes: {}},
];

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('tap_toggles_hold_opens_ring', async () => {
  const t = await mount(TOGGLES);
  try {
    assert.equal(openRing(), null, 'no ring at rest');
    for (const [id, domain, entity] of [['lamp', 'light', 'light.lamp'], ['plug', 'switch', 'switch.coffee'],
                                        ['kettle', 'switch', 'switch.kettle'], ['fan', 'fan', 'fan.ceiling']]) {
      t.calls.length = 0;
      await t.tap(id);
      assert.deepEqual(t.serviceCalls(), [[domain, 'toggle', {entity_id: entity}]], `a tap on ${id} toggles it once: ${JSON.stringify(t.serviceCalls())}`);
      assert.equal(t.live.ring(), null, `a tap on ${id} opens no ring`);
      assert.ok(!ringShown(), 'and draws none');
      const room = document.getElementById('twin-room-panel');
      assert.ok(!room || room.hidden, `a tap on ${id} does not open the room instead`);
    }
    // Hold: the ring opens at the light and nothing is sent, the release and its click included.
    t.calls.length = 0;
    t.states['light.lamp'].state = 'on'; await t.live.refresh();
    await t.hold('lamp');
    assert.deepEqual(t.serviceCalls(), [], `a hold sends nothing: ${JSON.stringify(t.serviceCalls())}`);
    const open = t.live.ring();
    assert.ok(open && open.device_id === 'lamp', `a hold opens the lamp's ring: ${JSON.stringify(open)}`);
    assert.ok(ringShown(), 'the ring is drawn');
    assert.equal(ringNode().getAttribute('data-device-id'), 'lamp', 'the ring names its device');
    // The centre is on/off, from the confirmed state.
    assert.ok(centre(), 'the ring has its on/off centre (role=switch)');
    assert.equal(centre().getAttribute('aria-checked'), 'true', 'the lamp is on');
    await press(centre());
    await wait(60);
    assert.deepEqual(t.serviceCalls(), [['light', 'toggle', {entity_id: 'light.lamp'}]], `the centre toggles once: ${JSON.stringify(t.serviceCalls())}`);
    assert.equal(t.live.ring()?.device_id, 'lamp', 'the ring stays open');
    assert.equal(centre().getAttribute('aria-checked'), 'false', 'and shows the confirmed state after');
    // A switch's ring is its on/off centre.
    t.calls.length = 0;
    await t.hold('plug');
    assert.deepEqual(t.serviceCalls(), [], 'holding the plug sends nothing');
    assert.equal(t.live.ring()?.device_id, 'plug', "a hold opens the plug's ring");
    assert.ok(centre(), "the plug's ring has its centre");
    assert.equal(slider('brightness'), null, 'and no brightness arc');
    // A finger held on the lamp. When it lifts, the browser sends its compatibility mouse
    // events and click to whatever is under it now: the ring's own centre (Chromium does,
    // found in the wall-panel scenario). That click must not toggle the light.
    key(document, 'Escape'); await wait(30);
    t.calls.length = 0;
    const at = t.screenOf('lamp');
    t.pointer('pointerdown', at, {pointerType: 'touch', pointerId: 9});
    await wait(650);
    t.pointer('pointerup', at, {pointerType: 'touch', pointerId: 9, buttons: 0});
    const under = centre() || t.canvas;
    for (const type of ['mousedown', 'mouseup', 'click'])
      under.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, clientX: at[0], clientY: at[1]}));
    await wait(60);
    assert.equal(t.live.ring()?.device_id, 'lamp', 'a touch hold opens the ring');
    assert.deepEqual(t.serviceCalls(), [], `the click that follows the lifted finger toggles nothing: ${JSON.stringify(t.serviceCalls())}`);
    await press(centre()); await wait(60);
    assert.deepEqual(t.serviceCalls(), [['light', 'toggle', {entity_id: 'light.lamp'}]], 'a deliberate tap on the centre after that still toggles');
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

check('drag_never_opens_a_ring', async () => {
  const t = await mount(TOGGLES);
  try {
    // A slow orbit that starts on the marker: it outlasts the hold time while moving.
    const [x, y] = t.screenOf('lamp');
    t.pointer('pointerdown', [x, y]);
    for (let i = 1; i <= 8; i++) { await wait(90); t.pointer('pointermove', [x + i * 8, y + i * 3]); }
    t.pointer('pointerup', [x + 64, y + 24]);
    await wait(80);
    assert.equal(t.live.ring(), null, 'a slow drag opens no ring');
    assert.deepEqual(t.serviceCalls(), [], 'and toggles nothing');
    // A quick flick away, then a rest: still a drag.
    t.pointer('pointerdown', [x, y]); await wait(20);
    t.pointer('pointermove', [x + 40, y]); await wait(650);
    t.pointer('pointerup', [x + 40, y]); await wait(80);
    assert.equal(t.live.ring(), null, 'a drag that then rests opens no ring');
    assert.deepEqual(t.serviceCalls(), [], 'and toggles nothing');
    assert.ok(!ringShown());
  } finally { t.cleanup(); }
  // Two markers drawn over each other (2 ft apart: each centre lies inside the other's 44 px target):
  // the one whose centre is under the finger is the one acted on.
  const u = await mount([
    {device_id: 'a', name: 'Lamp A', entity_id: 'light.a', kind: 'light', state: 'off', attributes: {supported_color_modes: ['brightness']}, at: [0, 4, 2]},
    {device_id: 'b', name: 'Lamp B', entity_id: 'light.b', kind: 'light', state: 'off', attributes: {supported_color_modes: ['brightness']}, at: [2, 4, 2]},
  ]);
  try {
    const [ax] = u.screenOf('a'), [bx] = u.screenOf('b');
    assert.ok(Math.abs(bx - ax) < 22, `fixture: each marker's centre is inside the other's target (${ax}, ${bx})`);
    await u.hold('b');
    assert.equal(u.live.ring()?.device_id, 'b', `a hold on B's centre opens B's ring, not A's: ${JSON.stringify(u.live.ring())}`);
    await u.hold('a');
    assert.equal(u.live.ring()?.device_id, 'a', "a hold on A's centre opens A's ring");
    key(document, 'Escape'); await wait(30);
    u.calls.length = 0;
    await u.tap('b');
    assert.deepEqual(u.serviceCalls(), [['light', 'toggle', {entity_id: 'light.b'}]], `a tap on B's centre toggles B: ${JSON.stringify(u.serviceCalls())}`);
  } finally { u.cleanup(); }
});

check('ring_follows_the_marker', async () => {
  const t = await mount(TOGGLES);
  try {
    await t.hold('lamp');
    const first = t.live.ring();
    assert.ok(first, 'the ring opened');
    const [x0, y0] = t.screenOf('lamp');
    assert.ok(Math.hypot(first.x - x0, first.y - y0) <= 2, `the ring is anchored on the marker: ${JSON.stringify(first)} vs ${[x0, y0]}`);
    const style = JSON.stringify(ringNode().style);
    t.camera.position.set(9, 38, 6); t.camera.up.set(0, 1, 0); t.camera.lookAt(3, 0, -1); t.camera.updateMatrixWorld(true);
    t.view.render(); await wait(40); t.view.render();
    const [x1, y1] = t.screenOf('lamp');
    assert.ok(Math.hypot(x1 - x0, y1 - y0) > 20, 'fixture: the camera move moves the marker on screen');
    const moved = t.live.ring();
    assert.ok(moved && Math.hypot(moved.x - x1, moved.y - y1) <= 2, `the ring follows the marker: ${JSON.stringify(moved)} vs ${[x1, y1]}`);
    assert.notEqual(JSON.stringify(ringNode().style), style, "the ring element's position changed with it");
    // A poll keeps it open and in place.
    await t.live.refresh();
    assert.equal(t.live.ring()?.device_id, 'lamp', 'a poll leaves the ring open');
  } finally { t.cleanup(); }
});

check('light_ring_parts_follow_supported_color_modes', async () => {
  const light = (id, modes, extra = {}) => ({device_id: id, name: id, entity_id: `light.${id}`, kind: 'light', state: 'on',
    attributes: {brightness: 200, supported_color_modes: modes, ...extra}});
  const LIGHTS = [
    light('onoff', ['onoff']),
    light('dim', ['brightness']),
    light('white', ['color_temp'], {min_color_temp_kelvin: 2200, max_color_temp_kelvin: 6500, color_temp_kelvin: 3000, color_mode: 'color_temp'}),
    light('hs', ['hs'], {hs_color: [30, 50], color_mode: 'hs'}),
    light('rgb', ['rgb'], {rgb_color: [255, 0, 0], color_mode: 'rgb'}),
    light('xy', ['xy'], {xy_color: [.3, .3], color_mode: 'xy'}),
    light('rgbww', ['rgbww'], {rgbww_color: [255, 0, 0, 0, 0], color_mode: 'rgbww'}),
    light('full', ['color_temp', 'xy'], {min_color_temp_kelvin: 2000, max_color_temp_kelvin: 6535, color_temp_kelvin: 4000,
      color_mode: 'color_temp', effect_list: ['Rainbow', 'Candle'], effect: null}),
    light('noeffects', ['hs'], {effect_list: []}),
  ];
  const t = await mount(LIGHTS, {spacing: 6});
  const want = {
    onoff: [], dim: ['brightness'], white: ['brightness', 'temperature'], hs: ['brightness', 'swatches', 'wheel'],
    rgb: ['brightness', 'swatches', 'wheel'], xy: ['brightness', 'swatches', 'wheel'], rgbww: ['brightness', 'swatches', 'wheel'],
    full: ['brightness', 'temperature', 'swatches', 'wheel', 'effects'], noeffects: ['brightness', 'swatches', 'wheel'],
  };
  try {
    for (const row of LIGHTS) {
      await t.hold(row.device_id);
      assert.equal(t.live.ring()?.device_id, row.device_id, `${row.device_id}: the ring opens`);
      assert.ok(centre(), `${row.device_id}: on/off in the centre`);
      const parts = ['brightness', 'temperature', 'swatches', 'wheel', 'effects'].filter(name => part(name) && shown(part(name)));
      assert.deepEqual(parts, want[row.device_id], `${row.device_id} (${row.attributes.supported_color_modes}): the ring's parts`);
      if (part('brightness')) {
        const arc = slider('brightness');
        assert.ok(arc, `${row.device_id}: the brightness arc is a role=slider`);
        assert.equal(arc.getAttribute('aria-valuemax'), '100', 'brightness is in percent');
        assert.equal(now(arc), Math.round(200 / 255 * 100), `${row.device_id}: the arc shows the brightness`);
      }
      key(document, 'Escape'); await wait(30);
    }
    // The temperature arc is in kelvin within the light's own range, and sends color_temp_kelvin.
    await t.hold('white');
    const arc = slider('temperature');
    assert.ok(arc, 'the temperature arc is a role=slider');
    assert.deepEqual(['aria-valuemin', 'aria-valuemax', 'aria-valuenow'].map(k => Number(arc.getAttribute(k))), [2200, 6500, 3000],
      'the arc spans the light\'s kelvin range and shows its temperature');
    t.calls.length = 0;
    key(arc, 'ArrowUp'); key(arc, 'ArrowUp');
    await settle();
    const calls = t.serviceCalls();
    assert.equal(calls.length, 1, `one call for the temperature: ${JSON.stringify(calls)}`);
    const [domain, service, data] = calls[0];
    assert.deepEqual([domain, service, Object.keys(data).sort()], ['light', 'turn_on', ['color_temp_kelvin', 'entity_id']], JSON.stringify(calls[0]));
    assert.ok(data.color_temp_kelvin > 3000 && data.color_temp_kelvin <= 6500, `raised within range: ${data.color_temp_kelvin}`);
    key(document, 'Escape'); await wait(30);
    // Blue, and an effect.
    await t.hold('full');
    const swatches = part('swatches');
    const blue = swatches.querySelectorAll('button, [role="button"], [role="radio"]').find(n => /blue/i.test(n.getAttribute('aria-label') || ''));
    assert.ok(blue, `a Blue swatch (aria-label): ${swatches.querySelectorAll('button, [role="button"], [role="radio"]').map(n => n.getAttribute('aria-label'))}`);
    t.calls.length = 0;
    await press(blue); await wait(60);
    const sent = t.serviceCalls();
    assert.equal(sent.length, 1, `Blue sends once: ${JSON.stringify(sent)}`);
    const colour = sent[0][2];
    const isBlue = JSON.stringify(colour.rgb_color) === '[0,0,255]' ||
      Array.isArray(colour.hs_color) && Math.abs(colour.hs_color[0] - 240) <= 1 && Math.abs(colour.hs_color[1] - 100) <= 1;
    assert.ok(sent[0][0] === 'light' && sent[0][1] === 'turn_on' && isBlue && colour.entity_id === 'light.full', `Blue is blue: ${JSON.stringify(sent[0])}`);
    const chips = part('effects').querySelectorAll('button, [role="button"], [role="radio"]');
    assert.deepEqual(chips.map(n => n.textContent.trim()), ['Rainbow', 'Candle'], 'one chip per effect, named by it');
    t.calls.length = 0;
    await press(chips[1]); await wait(60);
    assert.deepEqual(t.serviceCalls(), [['light', 'turn_on', {effect: 'Candle', entity_id: 'light.full'}]], 'an effect chip sends its effect');
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

check('arc_drags_are_debounced', async () => {
  const t = await mount(TOGGLES);
  try {
    await t.hold('lamp');
    let arc = slider('brightness');
    assert.ok(arc, 'the lamp has a brightness arc');
    assert.equal(now(arc), 50, 'it shows 128 / 255 as 50%');
    // A burst of steps: nothing goes out while it lasts; one call with the final value after.
    t.calls.length = 0;
    for (let i = 0; i < 5; i++) {
      key(arc, 'ArrowUp');
      assert.deepEqual(t.serviceCalls(), [], `nothing is sent while the arc moves (step ${i + 1})`);
      await wait(20);
    }
    const chosen = now(slider('brightness'));
    assert.ok(chosen > 50, `the arc shows the value being chosen: ${chosen}`);
    await settle();
    assert.deepEqual(t.serviceCalls(), [['light', 'turn_on', {brightness_pct: chosen, entity_id: 'light.lamp'}]],
      `one call, the final value: ${JSON.stringify(t.serviceCalls())}`);
    assert.equal(now(slider('brightness')), chosen, 'after, the arc shows the confirmed value');
    // Two quick pointer drags on the arc: nothing while dragging, at most one call after,
    // carrying what the arc shows.
    arc = slider('brightness');
    const at = t.live.ring();
    t.calls.length = 0;
    for (const path of [[[at.x + 90, at.y], [at.x + 70, at.y - 60], [at.x, at.y - 90]], [[at.x, at.y - 90], [at.x - 60, at.y - 70], [at.x - 90, at.y]]]) {
      arc.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true, clientX: path[0][0], clientY: path[0][1], pointerId: 3, buttons: 1}));
      for (const [x, y] of path.slice(1)) {
        await wait(15);
        arc.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 3, buttons: 1}));
        assert.deepEqual(t.serviceCalls(), [], 'nothing is sent during a drag');
      }
      arc.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, cancelable: true, clientX: path.at(-1)[0], clientY: path.at(-1)[1], pointerId: 3}));
      await wait(30);
    }
    await settle();
    const sent = t.serviceCalls();
    assert.ok(sent.length <= 1, `two quick drags send at most once: ${JSON.stringify(sent)}`);
    if (sent.length) assert.equal(sent[0][2].brightness_pct, now(slider('brightness')), 'carrying the value the arc shows');
    // A light that ignores the call: the arc goes back to the confirmed brightness.
    const before = now(slider('brightness'));
    t.frozen.add('light.lamp');
    t.calls.length = 0;
    for (let i = 0; i < 3; i++) { key(slider('brightness'), 'ArrowDown'); await wait(20); }
    await settle();
    assert.equal(t.serviceCalls().length, 1, `sent once: ${JSON.stringify(t.serviceCalls())}`);
    assert.equal(now(slider('brightness')), before, 'the arc shows the confirmed brightness, never the unconfirmed one');
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

check('unoffered_ring_is_read_only', async () => {
  const t = await mount([{...LAMP, device_id: 'ro', entity_id: 'light.ro', name: 'Guest lamp', offered: false}]);
  try {
    await t.tap('ro');
    assert.deepEqual(t.serviceCalls(), [], 'a tap on an unoffered light sends nothing');
    await t.hold('ro');
    assert.equal(t.live.ring()?.device_id, 'ro', 'a hold opens its ring to show its state');
    assert.ok(centre(), 'the ring shows on/off');
    assert.equal(centre().getAttribute('aria-checked'), 'true', 'from the state');
    const controls = ringNode().querySelectorAll('button, input, select, [role="slider"], [role="switch"], [role="radio"]');
    assert.ok(controls.length >= 1, 'the ring has its parts');
    const live = controls.filter(n => !isDisabled(n));
    assert.deepEqual(live.map(n => n.getAttribute('data-ring-part') || n.getAttribute('aria-label') || n.textContent), [],
      'every control in an unoffered ring is disabled');
    const values = () => controls.filter(n => n.getAttribute('role') === 'slider').map(n => n.getAttribute('aria-valuenow'));
    const shownBefore = values();
    for (const node of controls) {
      await press(node);
      if (node.getAttribute('role') === 'slider') for (const name of ['ArrowUp', 'ArrowUp', 'ArrowRight', 'End']) key(node, name);
    }
    await settle();
    assert.deepEqual(t.serviceCalls(), [], `nothing is sent from a read-only ring: ${JSON.stringify(t.serviceCalls())}`);
    assert.deepEqual(values(), shownBefore, 'a read-only arc never moves off the state it shows');
    assert.equal(centre().getAttribute('aria-checked'), 'true', 'nor does its centre');
  } finally { t.cleanup(); }
});

check('ring_closes_on_outside_tap_and_escape', async () => {
  const t = await mount(TOGGLES);
  try {
    await t.hold('lamp');
    assert.ok(t.live.ring(), 'open');
    key(document, 'Escape'); await wait(30);
    assert.equal(t.live.ring(), null, 'Escape closes the ring');
    assert.ok(!ringShown(), 'and it is no longer drawn');
    await t.hold('lamp');
    assert.ok(t.live.ring(), 'open again');
    t.calls.length = 0;
    await t.tapAt([1300, 940]);
    assert.equal(t.live.ring(), null, 'a tap on the scene away from the ring closes it');
    assert.deepEqual(t.serviceCalls(), [], 'and sends nothing');
    await t.hold('lamp');
    for (const type of ['pointerdown', 'pointerup']) document.body.dispatchEvent(new PointerEvent(type, {bubbles: true, cancelable: true, clientX: 5, clientY: 5}));
    document.body.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, clientX: 5, clientY: 5}));
    await wait(40);
    assert.equal(t.live.ring(), null, 'a tap elsewhere on the page closes it');
    await t.hold('lamp');
    await press(ringNode());
    assert.equal(t.live.ring()?.device_id, 'lamp', 'a tap on the ring itself keeps it open');
    if (part('brightness')) { await press(part('brightness')); assert.ok(t.live.ring(), 'a tap on one of its parts keeps it open'); }
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

const only = process.argv.slice(3);
let passed = 0, ran = 0;
for (const [name, fn] of checks) {
  if (only.length && !only.includes(name)) continue;
  ran++;
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 900)); }
}
if (escaped.length) console.log('  note: escaped ' + escaped.slice(0, 3).join(' | ').slice(0, 600));
console.log(`${passed}/${ran} passed`);
process.exit(passed === ran ? 0 : 1);
"""


def run(only=()):
    return R.run(DRIVER, {}, prefix='chauffeur_twin_ring_', timeout=240, args=list(only))


if __name__ == '__main__':
    sys.exit(1 if run(sys.argv[1:]) else 0)
