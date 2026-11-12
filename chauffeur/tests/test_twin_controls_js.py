"""Node checks for the controls of every device kind at its marker (Task 4 of
docs/superpowers/plans/2026-11-11-twin-device-controls.md, plus the camera ring of
Task 5; briefs .superpowers/sdd/2026-11-11-twin-device-controls/task-4-brief.md and
task-5-brief.md; spec docs/superpowers/specs/2026-11-11-twin-device-controls-design.md
decisions 2, 3 and 6 and the user's answers in section 5; plan Global Constraints and
Review Focus 3 and 4).

The fake DOM and the rig (a mounted live layer over a fake view, a fake Home
Assistant behind api() and window.chfControlFetch, gestures at a marker's projected
centre) are tests/twin_live_node_rig.py's: read its docstring. This file teaches the
rig's fake the services of the other kinds (set_hvac_mode, set_percentage,
set_cover_position, volume_set, alarm_arm_night, ...) the way Home Assistant answers
them, and stubs window.promptInput (it answers t.code) and the browser dialogs
(alert, confirm, prompt: recorded, never to be called).

Fixtures carry Home Assistant's own attribute shapes, supported_features bits included:
  climate        TARGET_TEMPERATURE 1, TARGET_TEMPERATURE_RANGE 2, FAN_MODE 8, PRESET_MODE 16,
                 TURN_OFF 128, TURN_ON 256
  fan            SET_SPEED 1, OSCILLATE 2, DIRECTION 4, PRESET_MODE 8, TURN_OFF 16, TURN_ON 32
  cover          OPEN 1, CLOSE 2, SET_POSITION 4, STOP 8, OPEN_TILT 16, CLOSE_TILT 32,
                 STOP_TILT 64, SET_TILT_POSITION 128
  media_player   PAUSE 1, VOLUME_SET 4, VOLUME_MUTE 8, PREVIOUS_TRACK 16, NEXT_TRACK 32,
                 SELECT_SOURCE 2048, PLAY 16384
  alarm panel    ARM_HOME 1, ARM_AWAY 2, ARM_NIGHT 4, TRIGGER 8, ARM_CUSTOM_BYPASS 16, ARM_VACATION 32
  vacuum         PAUSE 4, STOP 8, RETURN_HOME 16, LOCATE 512, STATE 4096, START 8192
  humidifier     MODES 1
  water_heater   TARGET_TEMPERATURE 1, OPERATION_MODE 2, ON_OFF 8
The layout's `kind` is what services/twin_ha.py sends today: climate, fan, blinds,
garage, media, lock, camera, sensor; 'other' for alarm_control_panel, vacuum,
humidifier, water_heater, scene and script (the kind registry matches those by the
entity's domain, as it already does for alarm_control_panel).

The interfaces this file assumes beyond Task 3's (keep them few):
- each kind's ring is drawn by its builder in static/twin/live/controls/<kind>.js
  (climate, fan, cover, media, lock, alarm, vacuum, humidifier, water_heater, scene,
  camera), registered in kinds.js; the room panel's row for the kind uses the same
  builder;
- ring parts carry data-ring-part (an arc is a WAI-ARIA slider: the part or one
  role="slider" inside it, aria-valuemin/max/now; arrow keys step it; one call goes
  out once the person stops, settled within 1 s, then the arc shows the confirmed
  state; a chip list is the part holding one button per choice, named by its text
  (HA's own value title-cased: compared case-, space- and underscore-blind), the
  current one aria-pressed="true"; a single action is a button, or the part holding
  one):
    climate      target (one handle: temperature) or target-low and target-high (two
                 handles, heat_cool / a range: target_temp_low / target_temp_high), in
                 the entity's own min_temp..max_temp at target_temp_step; current (text
                 with current_temperature); modes (hvac_modes -> set_hvac_mode);
                 fan-modes (fan_modes -> set_fan_mode) and presets (preset_modes ->
                 set_preset_mode) only when supported; action (text naming hvac_action)
    fan          center (role=switch); speed (percent at percentage_step -> set_percentage);
                 oscillate (role=switch -> oscillate); direction (-> set_direction);
                 presets (-> set_preset_mode); each only when supported
    cover        open, stop, close (-> open_cover / stop_cover / close_cover); position
                 (-> set_cover_position); tilt (-> set_cover_tilt_position); each only
                 when supported. A garage's open asks once; a blind's never asks.
    media        play (-> media_play_pause, or media_pause while playing); previous, next;
                 volume (percent -> volume_set {volume_level 0..1}); mute (role=switch ->
                 volume_mute); sources (a select of source_list, or one button per source
                 -> select_source); now-playing (title and artist as text). No artwork.
    lock         lock, unlock (unlock asks once)
    alarm        arm (one button per supported arm mode: "Arm home", "Arm away", "Arm
                 night", "Arm vacation", "Arm custom bypass"); disarm (asks once). When
                 code_format is set (and, to arm, code_arm_required), a code is asked for
                 in-page: either window.promptInput (control_center's sheet) or the
                 ring's own [data-ring-part="code"] holding an input and a
                 [data-ring-part="code-submit"] button; the code rides the call as
                 data.code. Never alert/confirm/prompt.
    vacuum       start, pause, return (-> return_to_base), locate; each only when supported
    humidifier   center (role=switch); target (min_humidity..max_humidity, humidity ->
                 set_humidity); modes (available_modes -> set_mode)
    water_heater center (role=switch: on unless the state is off -> turn_on / turn_off);
                 target (min_temp..max_temp, temperature -> set_temperature); modes
                 (operation_list -> set_operation_mode)
    camera       still: an img (the part or inside it) showing frames fetched from
                 page-relative base() + 'api/house/camera/<entity_id>' (a cache-buster
                 may follow) with the page's identity in headers, never a token in the
                 URL (review L5); the next fetch goes 2 s after the last one answered,
                 never while one is pending, each with a deadline (review M2); none
                 after the ring closes; a 403 says why and stops asking
- a tap on a scene or a script runs it (scene.turn_on / script.turn_on) and opens no
  ring; a tap on any other kind here opens its ring and sends nothing;
- a sensor's ring shows its value and unit (a contact sensor says open/closed) and
  holds no control;
- a device the grid does not offer: its ring holds no live control and sends nothing,
  and its room row offers no More (review M1);
- a garage door never gets a position or tilt arc on either surface, and any call
  that would raise it asks the Open question first (review H1);
- a thermostat shows two handles whenever it carries target_temp_low/high and no
  single setpoint, whatever its mode is called (auto included; review L4).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_controls_js.py [check ...]
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_live_node_rig as R  # noqa: E402

DRIVER = r"""
const ringNode = () => document.querySelector('[data-ring]');
const ringShown = () => { const node = ringNode(); return !!node && shown(node); };
const part = name => { const node = ringNode()?.querySelector(`[data-ring-part="${name}"]`) || null; return node && shown(node) ? node : null; };
const role = (node, name) => !node ? null : node.matches(`[role="${name}"]`) ? node : node.querySelector(`[role="${name}"]`);
const slider = name => role(part(name), 'slider');
const toggleOf = name => role(part(name), 'switch');
const now = node => Number(node.getAttribute('aria-valuenow'));
const range = node => ['aria-valuemin', 'aria-valuemax', 'aria-valuenow'].map(k => Number(node.getAttribute(k)));
const norm = s => String(s ?? '').trim().toLowerCase().replace(/[\s_\/-]+/g, '_');
const CLICKABLE = 'button, [role="button"], [role="radio"], [role="switch"]';
const buttonsIn = node => !node ? [] : [...(node.matches(CLICKABLE) ? [node] : []), ...node.querySelectorAll(CLICKABLE)];
const nameOf = node => norm(node.textContent || node.getAttribute('aria-label'));
const chips = name => buttonsIn(part(name)).map(nameOf);
const chip = (name, value) => buttonsIn(part(name)).find(node => nameOf(node) === norm(value)) || null;
const pressed = name => buttonsIn(part(name)).filter(node => node.getAttribute('aria-pressed') === 'true' || node.getAttribute('aria-checked') === 'true').map(nameOf);
const action = name => buttonsIn(part(name))[0] || null;
const ringText = () => ringNode()?.textContent || '';
// The same lookups, failing with the part's name when it is missing.
const arc = name => { const node = slider(name); assert.ok(node, `a [data-ring-part="${name}"] arc (role=slider)`); return node; };
const act = name => { const node = action(name); assert.ok(node, `a [data-ring-part="${name}"] control`); return node; };
const pick = (name, value) => { const node = chip(name, value); assert.ok(node, `a ${value} chip in [data-ring-part="${name}"]: ${JSON.stringify(chips(name))}`); return node; };
const flip = name => { const node = toggleOf(name); assert.ok(node, `a [data-ring-part="${name}"] switch (role=switch)`); return node; };
const settle = () => wait(1200);
const escape = async () => { key(document, 'Escape'); await wait(30); };
const steps = async (name, keyName, n) => { for (let i = 0; i < n; i++) { key(arc(name), keyName); await wait(15); } };

// What Home Assistant does with the services the rig's fake does not know.
function apply(row, {domain, service, data: d}) {
  const a = row.attributes;
  if (service === 'set_temperature') for (const k of ['temperature', 'target_temp_low', 'target_temp_high']) if (d[k] !== undefined) a[k] = d[k];
  if (service === 'set_hvac_mode') row.state = d.hvac_mode;
  if (service === 'set_fan_mode') a.fan_mode = d.fan_mode;
  if (service === 'set_preset_mode') a.preset_mode = d.preset_mode;
  if (service === 'set_percentage') { a.percentage = d.percentage; row.state = d.percentage > 0 ? 'on' : 'off'; }
  if (service === 'oscillate') a.oscillating = d.oscillating;
  if (service === 'set_direction') a.direction = d.direction;
  if (service === 'set_cover_position') { a.current_position = d.position; row.state = d.position > 0 ? 'open' : 'closed'; }
  if (service === 'set_cover_tilt_position') a.current_tilt_position = d.tilt_position;
  if (domain === 'cover' && service === 'open_cover' && a.current_position !== undefined) a.current_position = 100;
  if (domain === 'cover' && service === 'close_cover' && a.current_position !== undefined) a.current_position = 0;
  if (service === 'volume_set') a.volume_level = d.volume_level;
  if (service === 'volume_mute') a.is_volume_muted = d.is_volume_muted;
  if (service === 'select_source') a.source = d.source;
  if (service === 'media_play_pause') row.state = row.state === 'playing' ? 'paused' : 'playing';
  if (service === 'media_pause') row.state = 'paused';
  if (service === 'media_play') row.state = 'playing';
  if (service === 'alarm_arm_night') row.state = 'armed_night';
  if (domain === 'vacuum') row.state = {start: 'cleaning', pause: 'paused', return_to_base: 'returning'}[service] || row.state;
  if (service === 'set_humidity') a.humidity = d.humidity;
  if (service === 'set_mode') a.mode = d.mode;
  if (service === 'set_operation_mode') { a.operation_mode = d.operation_mode; row.state = d.operation_mode; }
}

// Markers on a grid that fits the rig's camera (about 29 px per foot, 48 x 34 ft in view).
const spot = i => [-20 + (i % 9) * 5, [-10, 0, 10][Math.floor(i / 9) % 3], 2];
async function mount(devices, options = {}) {
  const t = await rig({...options, devices: devices.map((d, i) => ({...structuredClone(d), at: d.at || spot(i)}))});
  globalThis.__live = t.live;
  t.inputs = []; t.code = '1234'; t.dialogs = [];
  window.promptInput = async (...args) => { t.inputs.push(args); return t.code; };
  for (const name of ['alert', 'confirm', 'prompt']) {
    const fn = (...args) => { t.dialogs.push([name, ...args]); return name === 'confirm' ? true : null; };
    window[name] = fn; globalThis[name] = fn;
  }
  const inner = window.chfControlFetch;
  window.chfControlFetch = async (url, options) => {
    const response = await inner(url, options);
    const call = JSON.parse(options.body), row = t.states[call.data.entity_id];
    if (row && !t.frozen.has(call.data.entity_id)) apply(row, call);
    return response;
  };
  return t;
}
async function open(t, id, how = 'tap') {
  await escape();
  t.calls.length = 0;
  await t[how](id);
  assert.equal(t.live.ring()?.device_id, id, `a ${how} on ${id} opens its ring: ${JSON.stringify(t.live.ring())}`);
  assert.ok(ringShown(), `${id}: the ring is drawn`);
  assert.deepEqual(t.serviceCalls(), [], `opening ${id}'s ring sends nothing: ${JSON.stringify(t.serviceCalls())}`);
}
async function sent(t, fn) {
  t.calls.length = 0;
  await fn();
  await wait(80);
  return t.serviceCalls();
}
// The code a Home Assistant alarm asks for: control_center's promptInput, or the ring's own sheet.
async function answerCode(t, before) {
  for (let i = 0; i < 40; i++) {
    if (t.inputs.length > before) return 'promptInput';
    const sheet = document.querySelectorAll('[data-ring-part="code"]').find(node => shown(node));
    if (sheet) {
      const input = sheet.querySelector('input');
      assert.ok(input, 'the in-page code sheet has an input');
      input.value = t.code; input.dispatchEvent(new Event('input', {bubbles: true}));
      const submit = sheet.querySelector('[data-ring-part="code-submit"]');
      assert.ok(submit, 'the code sheet has its [data-ring-part="code-submit"] button');
      await press(submit);
      return 'sheet';
    }
    await wait(25);
  }
  assert.fail('no code was asked for: neither window.promptInput nor an in-page [data-ring-part="code"] sheet');
}

// ------------------------------------------------------------------ fixtures
const dev = (id, entity_id, kind, state, attributes, extra = {}) => ({device_id: id, name: id, entity_id, kind, state,
  attributes: {friendly_name: id, ...attributes}, ...extra});
const HEAT = dev('heat', 'climate.living', 'climate', 'heat', {hvac_modes: ['off', 'heat', 'cool', 'heat_cool'],
  min_temp: 45, max_temp: 95, target_temp_step: 1, current_temperature: 66, temperature: 68, target_temp_low: null,
  target_temp_high: null, hvac_action: 'heating', fan_modes: ['auto', 'on'], fan_mode: 'auto',
  preset_modes: ['none', 'away', 'eco'], preset_mode: 'none', supported_features: 1 | 8 | 16 | 128 | 256});
const RANGE = dev('range', 'climate.upstairs', 'climate', 'heat_cool', {hvac_modes: ['off', 'heat_cool'],
  min_temp: 50, max_temp: 90, target_temp_step: 1, current_temperature: 72, temperature: null,
  target_temp_low: 68, target_temp_high: 76, hvac_action: 'idle', supported_features: 2 | 128 | 256});
const COOL_C = dev('coolc', 'climate.bedroom', 'climate', 'cool', {hvac_modes: ['off', 'cool', 'heat'],
  min_temp: 16, max_temp: 30, target_temp_step: .5, current_temperature: 27, temperature: 29.5,
  hvac_action: 'cooling', supported_features: 1 | 128 | 256});
const FAN = dev('fan', 'fan.bedroom', 'fan', 'on', {percentage: 33, percentage_step: 100 / 3, oscillating: false,
  direction: 'forward', preset_modes: ['auto', 'sleep'], preset_mode: null, supported_features: 1 | 2 | 4 | 8 | 16 | 32});
const FAN_BASIC = dev('fanbasic', 'fan.attic', 'fan', 'off', {supported_features: 16 | 32});
const BLIND = dev('blind', 'cover.living_blind', 'blinds', 'open', {device_class: 'blind', current_position: 100,
  current_tilt_position: 50, supported_features: 255});
const SHADE = dev('shade', 'cover.porch_shade', 'blinds', 'closed', {device_class: 'shade', supported_features: 1 | 2});
const GARAGE = dev('garage', 'cover.garage', 'garage', 'closed', {device_class: 'garage', supported_features: 1 | 2});
// ratgdo, Z-Wave and several Tuya openers report SET_POSITION (and STOP).
const GARAGE_POS = dev('garagepos', 'cover.garage_two', 'garage', 'closed', {device_class: 'garage', current_position: 0,
  supported_features: 1 | 2 | 4 | 8 | 128, current_tilt_position: 0});
const AUTO = dev('auto', 'climate.hall', 'climate', 'auto', {hvac_modes: ['off', 'auto'], min_temp: 50, max_temp: 90,
  target_temp_step: 1, current_temperature: 70, temperature: null, target_temp_low: 66, target_temp_high: 74,
  hvac_action: 'idle', supported_features: 2 | 128 | 256});
const SPEAKER = dev('speaker', 'media_player.kitchen', 'media', 'playing', {volume_level: .3, is_volume_muted: false,
  media_title: 'So What', media_artist: 'Miles Davis', source_list: ['Radio', 'Spotify', 'TV'], source: 'Spotify',
  entity_picture: '/api/media_player_proxy/media_player.kitchen?token=abc123&cache=9',
  supported_features: 1 | 4 | 8 | 16 | 32 | 2048 | 16384});
const TV = dev('tv', 'media_player.den_tv', 'media', 'paused', {volume_level: .2, supported_features: 1 | 4 | 16384});
const LOCK = dev('lock', 'lock.front_door', 'lock', 'locked', {});
const ALARM = dev('alarm', 'alarm_control_panel.house', 'other', 'disarmed', {code_format: 'number',
  code_arm_required: true, changed_by: null, supported_features: 1 | 2 | 4});
const ALARM_NOCODE = dev('shedalarm', 'alarm_control_panel.shed', 'other', 'armed_away', {code_format: null,
  code_arm_required: false, supported_features: 1 | 2});
const VACUUM = dev('vacuum', 'vacuum.downstairs', 'other', 'docked', {battery_level: 90, fan_speed: 'standard',
  fan_speed_list: ['quiet', 'standard', 'max'], supported_features: 4 | 8 | 16 | 512 | 4096 | 8192});
const VAC_BASIC = dev('vacbasic', 'vacuum.upstairs', 'other', 'docked', {supported_features: 4 | 16 | 4096 | 8192});
const HUMID = dev('humid', 'humidifier.bedroom', 'other', 'on', {humidity: 45, current_humidity: 38, min_humidity: 30,
  max_humidity: 80, available_modes: ['normal', 'eco', 'boost'], mode: 'normal', device_class: 'humidifier', supported_features: 1});
const WATER = dev('water', 'water_heater.tank', 'other', 'eco', {min_temp: 110, max_temp: 140, temperature: 120,
  current_temperature: 118, target_temp_high: null, target_temp_low: null,
  operation_list: ['off', 'eco', 'electric', 'performance'], operation_mode: 'eco', supported_features: 1 | 2 | 8});
const SCENE = dev('scene', 'scene.movie_night', 'other', '2026-11-10T20:00:00+00:00', {});
const SCRIPT = dev('script', 'script.goodnight', 'other', 'off', {last_triggered: null, mode: 'single'});
const SENSOR = dev('temp', 'sensor.porch_temperature', 'sensor', '54.3', {unit_of_measurement: '°F', device_class: 'temperature', state_class: 'measurement'});
const DOOR = dev('door', 'binary_sensor.front_door', 'sensor', 'on', {device_class: 'door'});
const CAMERA = dev('camera', 'camera.porch', 'camera', 'idle', {entity_picture: '/api/camera_proxy/camera.porch?token=cafe5eed',
  access_token: 'cafe5eed', frontend_stream_type: null, supported_features: 0});

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('tap_opens_the_ring_of_every_kind_that_does_not_toggle', async () => {
  const kinds = [HEAT, BLIND, GARAGE, SPEAKER, LOCK, ALARM, VACUUM, HUMID, WATER, CAMERA, SENSOR];
  const t = await mount(kinds);
  try {
    for (const row of kinds) await open(t, row.device_id);
    assert.deepEqual(t.confirms, [], 'a tap asks nothing');
    assert.deepEqual(t.dialogs, [], 'no browser dialog');
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

check('scene_and_script_tap_runs_them', async () => {
  const t = await mount([SCENE, SCRIPT]);
  try {
    for (const [id, domain, entity] of [['scene', 'scene', 'scene.movie_night'], ['script', 'script', 'script.goodnight']]) {
      const calls = await sent(t, () => t.tap(id));
      assert.deepEqual(calls, [[domain, 'turn_on', {entity_id: entity}]], `a tap on the ${id} runs it once: ${JSON.stringify(calls)}`);
      assert.equal(t.live.ring(), null, `a tap on the ${id} opens no ring`);
      const room = document.getElementById('twin-room-panel');
      assert.ok(!room || room.hidden, `nor the room`);
    }
    assert.deepEqual(t.confirms, [], 'running a scene or a script asks nothing');
  } finally { t.cleanup(); }
});

check('climate_one_handle_for_heat_or_cool', async () => {
  const t = await mount([HEAT, COOL_C]);
  try {
    await open(t, 'heat');
    const target = slider('target');
    assert.ok(target, 'one setpoint handle: [data-ring-part="target"] role=slider');
    assert.equal(part('target-low'), null, 'no low handle outside a range');
    assert.equal(part('target-high'), null, 'no high handle outside a range');
    assert.deepEqual(range(target), [45, 95, 68], 'the handle spans min_temp..max_temp and shows the setpoint');
    assert.ok(part('current') && /66/.test(part('current').textContent), `the current temperature is shown: ${part('current')?.textContent}`);
    t.calls.length = 0;
    await steps('target', 'ArrowUp', 2);
    assert.deepEqual(t.serviceCalls(), [], 'nothing is sent while the handle moves');
    assert.equal(now(slider('target')), 70, 'the handle shows the value being chosen');
    await settle();
    assert.deepEqual(t.serviceCalls(), [['climate', 'set_temperature', {temperature: 70, entity_id: 'climate.living'}]],
      `one call, the final setpoint: ${JSON.stringify(t.serviceCalls())}`);
    assert.equal(now(slider('target')), 70, 'the handle shows the confirmed setpoint');
    // A frozen thermostat: the handle goes back to what it reports.
    t.frozen.add('climate.living'); t.calls.length = 0;
    await steps('target', 'ArrowDown', 3); await settle();
    assert.equal(t.serviceCalls().length, 1, 'sent once');
    assert.equal(now(slider('target')), 70, 'the handle shows the confirmed setpoint, never the unconfirmed one');
    t.frozen.clear();
    // Celsius at half degrees, against its own maximum.
    await open(t, 'coolc');
    assert.deepEqual(range(arc('target')), [16, 30, 29.5], 'a Celsius thermostat in its own range');
    await steps('target', 'ArrowUp', 3); await settle();
    assert.deepEqual(t.serviceCalls(), [['climate', 'set_temperature', {temperature: 30, entity_id: 'climate.bedroom'}]],
      `the handle stops at max_temp: ${JSON.stringify(t.serviceCalls())}`);
    t.calls.length = 0;
    await steps('target', 'ArrowDown', 1); await settle();
    assert.deepEqual(t.serviceCalls(), [['climate', 'set_temperature', {temperature: 29.5, entity_id: 'climate.bedroom'}]],
      `one step is target_temp_step (0.5): ${JSON.stringify(t.serviceCalls())}`);
    assert.equal(now(slider('target')), 29.5);
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

check('climate_two_handles_for_heat_cool', async () => {
  const t = await mount([RANGE]);
  try {
    await open(t, 'range');
    assert.equal(part('target'), null, 'a range has no single handle');
    const low = slider('target-low'), high = slider('target-high');
    assert.ok(low && high, 'two handles: target-low and target-high');
    assert.deepEqual(range(low), [50, 90, 68], 'the low handle: target_temp_low in min..max');
    assert.deepEqual(range(high), [50, 90, 76], 'the high handle: target_temp_high in min..max');
    await steps('target-high', 'ArrowUp', 1); await settle();
    assert.deepEqual(t.serviceCalls(), [['climate', 'set_temperature', {target_temp_low: 68, target_temp_high: 77, entity_id: 'climate.upstairs'}]],
      `moving the high end sends both ends: ${JSON.stringify(t.serviceCalls())}`);
    t.calls.length = 0;
    await steps('target-low', 'ArrowDown', 2); await settle();
    assert.deepEqual(t.serviceCalls(), [['climate', 'set_temperature', {target_temp_low: 66, target_temp_high: 77, entity_id: 'climate.upstairs'}]],
      `moving the low end keeps the confirmed high end: ${JSON.stringify(t.serviceCalls())}`);
    assert.deepEqual([now(slider('target-low')), now(slider('target-high'))], [66, 77], 'both handles show the confirmed range');
    assert.ok(part('action') && /idle/i.test(part('action').textContent), `hvac_action idle is shown: ${part('action')?.textContent}`);
  } finally { t.cleanup(); }
});

check('climate_mode_chips_and_action', async () => {
  const t = await mount([HEAT, COOL_C]);
  try {
    await open(t, 'heat');
    assert.deepEqual(chips('modes'), ['off', 'heat', 'cool', 'heat_cool'], 'one chip per hvac_modes entry, in order');
    assert.deepEqual(pressed('modes'), ['heat'], 'the current mode is pressed');
    assert.ok(part('action') && /heating/i.test(part('action').textContent), `hvac_action heating is shown: ${part('action')?.textContent}`);
    const calls = await sent(t, () => press(pick('modes', 'cool')));
    assert.deepEqual(calls, [['climate', 'set_hvac_mode', {hvac_mode: 'cool', entity_id: 'climate.living'}]], JSON.stringify(calls));
    assert.deepEqual(pressed('modes'), ['cool'], 'the confirmed mode is pressed after');
    await open(t, 'coolc');
    assert.ok(/cooling/i.test(part('action')?.textContent || ''), 'hvac_action cooling is shown');
    assert.deepEqual(t.confirms, [], 'no climate control asks');
  } finally { t.cleanup(); }
});

check('climate_fan_and_preset_chips_only_when_supported', async () => {
  const t = await mount([HEAT, RANGE, COOL_C]);
  try {
    await open(t, 'heat');
    assert.deepEqual(chips('fan-modes'), ['auto', 'on'], 'fan mode chips from fan_modes');
    assert.deepEqual(chips('presets'), ['none', 'away', 'eco'], 'preset chips from preset_modes');
    let calls = await sent(t, () => press(pick('fan-modes', 'on')));
    assert.deepEqual(calls, [['climate', 'set_fan_mode', {fan_mode: 'on', entity_id: 'climate.living'}]], JSON.stringify(calls));
    calls = await sent(t, () => press(pick('presets', 'eco')));
    assert.deepEqual(calls, [['climate', 'set_preset_mode', {preset_mode: 'eco', entity_id: 'climate.living'}]], JSON.stringify(calls));
    assert.deepEqual([pressed('fan-modes'), pressed('presets')], [['on'], ['eco']], 'the confirmed fan mode and preset are pressed');
    for (const id of ['range', 'coolc']) {
      await open(t, id);
      assert.equal(part('fan-modes'), null, `${id} has no FAN_MODE: no fan chips`);
      assert.equal(part('presets'), null, `${id} has no PRESET_MODE: no preset chips`);
    }
  } finally { t.cleanup(); }
});

check('fan_ring_follows_its_features', async () => {
  const t = await mount([FAN, FAN_BASIC]);
  try {
    await open(t, 'fan', 'hold');
    assert.equal(toggleOf('center')?.getAttribute('aria-checked'), 'true', 'on/off in the centre');
    const speed = slider('speed');
    assert.ok(speed, 'a speed arc');
    assert.deepEqual([range(speed)[1], Math.round(range(speed)[2])], [100, 33], 'the arc is in percent and shows the speed');
    await steps('speed', 'ArrowUp', 1); await settle();
    const calls = t.serviceCalls();
    assert.ok(calls.length === 1 && calls[0][0] === 'fan' && calls[0][1] === 'set_percentage' && calls[0][2].entity_id === 'fan.bedroom'
      && [66, 67].includes(calls[0][2].percentage), `one step is percentage_step (33 -> 67): ${JSON.stringify(calls)}`);
    let more = await sent(t, () => press(flip('oscillate')));
    assert.deepEqual(more, [['fan', 'oscillate', {oscillating: true, entity_id: 'fan.bedroom'}]], JSON.stringify(more));
    assert.equal(toggleOf('oscillate').getAttribute('aria-checked'), 'true', 'oscillate shows the confirmed state');
    more = await sent(t, () => press(act('direction')));
    assert.deepEqual(more, [['fan', 'set_direction', {direction: 'reverse', entity_id: 'fan.bedroom'}]], JSON.stringify(more));
    assert.deepEqual(chips('presets'), ['auto', 'sleep'], 'preset chips from preset_modes');
    more = await sent(t, () => press(pick('presets', 'sleep')));
    assert.deepEqual(more, [['fan', 'set_preset_mode', {preset_mode: 'sleep', entity_id: 'fan.bedroom'}]], JSON.stringify(more));
    await open(t, 'fanbasic', 'hold');
    assert.ok(toggleOf('center'), 'a plain fan has its on/off');
    for (const name of ['speed', 'oscillate', 'direction', 'presets']) assert.equal(part(name), null, `a plain fan has no ${name}`);
  } finally { t.cleanup(); }
});

check('cover_position_tilt_and_buttons', async () => {
  const t = await mount([BLIND, SHADE]);
  try {
    await open(t, 'blind');
    assert.deepEqual(range(arc('position')), [0, 100, 100], 'a position arc in percent at current_position');
    assert.deepEqual(range(arc('tilt')), [0, 100, 50], 'a tilt arc at current_tilt_position');
    await steps('position', 'ArrowDown', 3); await settle();
    assert.deepEqual(t.serviceCalls(), [['cover', 'set_cover_position', {position: 97, entity_id: 'cover.living_blind'}]], JSON.stringify(t.serviceCalls()));
    assert.equal(now(slider('position')), 97, 'the arc shows the confirmed position');
    t.calls.length = 0;
    await steps('tilt', 'ArrowUp', 2); await settle();
    assert.deepEqual(t.serviceCalls(), [['cover', 'set_cover_tilt_position', {tilt_position: 52, entity_id: 'cover.living_blind'}]], JSON.stringify(t.serviceCalls()));
    for (const [name, service] of [['stop', 'stop_cover'], ['close', 'close_cover'], ['open', 'open_cover']]) {
      const calls = await sent(t, () => press(act(name)));
      assert.deepEqual(calls, [['cover', service, {entity_id: 'cover.living_blind'}]], `${name}: ${JSON.stringify(calls)}`);
    }
    assert.deepEqual(t.confirms, [], 'a blind never asks, its Open included');
    await open(t, 'shade');
    assert.ok(action('open') && action('close'), 'open and close');
    for (const name of ['stop', 'position', 'tilt']) assert.equal(part(name), null, `a shade without the feature has no ${name}`);
  } finally { t.cleanup(); }
});

check('garage_open_confirms_once', async () => {
  const t = await mount([GARAGE]);
  try {
    await open(t, 'garage');
    assert.deepEqual(t.confirms, [], 'opening the ring asks nothing');
    let calls = await sent(t, () => press(act('open')));
    assert.equal(t.confirms.length, 1, `Open asks exactly once: ${JSON.stringify(t.confirms)}`);
    assert.deepEqual(calls, [['cover', 'open_cover', {entity_id: 'cover.garage'}]], JSON.stringify(calls));
    calls = await sent(t, () => press(act('close')));
    assert.equal(t.confirms.length, 1, 'Close asks nothing');
    assert.deepEqual(calls, [['cover', 'close_cover', {entity_id: 'cover.garage'}]], JSON.stringify(calls));
    t.confirm = false;
    calls = await sent(t, () => press(act('open')));
    assert.equal(t.confirms.length, 2, 'asked again');
    assert.deepEqual(calls, [], 'a declined Open sends nothing');
    assert.deepEqual(t.dialogs, [], 'no browser dialog');
  } finally { t.cleanup(); }
});

check('garage_position_never_skips_the_confirm', async () => {
  const t = await mount([GARAGE_POS]);
  try {
    await open(t, 'garagepos');
    for (const name of ['position', 'tilt']) assert.equal(part(name), null, `a garage has no ${name} arc on its ring`);
    assert.ok(action('open') && action('close') && action('stop'), 'Open, Stop and Close stay');
    await escape();
    t.live.openRoom('b', 'r');
    await wait(60);
    const row = document.getElementById('twin-room-panel')?.querySelector('[data-device-id="garagepos"]');
    assert.ok(row, "the garage's room row");
    assert.deepEqual(row.querySelectorAll('input, [role="slider"]').map(n => n.getAttribute('aria-label')), [],
      'and no position or tilt range in its room row');
    t.live.closeRoom();
    // Any other path that would raise the door asks the Open question first, once.
    t.confirm = false; t.calls.length = 0;
    let ok = await t.live.control('cover.garage_two', 'set_cover_position', {position: 100});
    assert.equal(ok, false, 'declined');
    assert.equal(t.confirms.length, 1, `raising the door asks once: ${JSON.stringify(t.confirms)}`);
    assert.ok(/open/i.test(t.confirms[0][0]), `the Open question: ${JSON.stringify(t.confirms[0])}`);
    assert.deepEqual(t.serviceCalls(), [], 'a declined raise sends nothing');
    t.confirm = true;
    ok = await t.live.control('cover.garage_two', 'set_cover_position', {position: 40});
    assert.equal(t.confirms.length, 2, 'asked again, and accepted');
    assert.deepEqual(t.serviceCalls(), [['cover', 'set_cover_position', {position: 40, entity_id: 'cover.garage_two'}]], JSON.stringify(t.serviceCalls()));
    t.calls.length = 0;
    t.states['cover.garage_two'].attributes.current_position = 40; await t.live.refresh(true);
    await t.live.control('cover.garage_two', 'set_cover_position', {position: 0});
    assert.equal(t.confirms.length, 2, 'lowering it asks nothing');
    assert.deepEqual(t.serviceCalls(), [['cover', 'set_cover_position', {position: 0, entity_id: 'cover.garage_two'}]], JSON.stringify(t.serviceCalls()));
    assert.deepEqual(t.dialogs, [], 'no browser dialog');
  } finally { t.cleanup(); }
});

check('climate_two_handles_whenever_a_range_is_carried', async () => {
  const t = await mount([AUTO]);
  try {
    await open(t, 'auto');
    assert.equal(part('target'), null, 'an auto thermostat carrying a range has no single handle');
    const low = slider('target-low'), high = slider('target-high');
    assert.ok(low && high, 'two handles in auto: target-low and target-high');
    assert.deepEqual([range(low), range(high)], [[50, 90, 66], [50, 90, 74]], 'at the range HA reports');
    await steps('target-low', 'ArrowUp', 1); await settle();
    assert.deepEqual(t.serviceCalls(), [['climate', 'set_temperature', {target_temp_low: 67, target_temp_high: 74, entity_id: 'climate.hall'}]],
      JSON.stringify(t.serviceCalls()));
    await escape();
    t.live.openRoom('b', 'r');
    await wait(60);
    const row = document.getElementById('twin-room-panel')?.querySelector('[data-device-id="auto"]');
    assert.equal(row.querySelectorAll('input').filter(n => n.type === 'range').length, 2, "and two ranges in the room's row");
  } finally { t.cleanup(); }
});

check('more_only_for_offered_devices', async () => {
  const t = await mount([FAN, {...FAN_BASIC, offered: false}, {...SPEAKER, offered: false}]);
  try {
    window.ChauffeurHaCards = {mounted: [], setStates() {}, unmount() {},
      async mountBuiltin(host, spec) { this.mounted.push(spec); return true; }};
    t.live.openRoom('b', 'r');
    await wait(60);
    const panel = document.getElementById('twin-room-panel');
    const more = id => panel.querySelector(`[data-device-id="${id}"] [data-more]`);
    assert.ok(more('fan'), 'an offered fan has its More');
    for (const id of ['fanbasic', 'speaker'])
      assert.equal(more(id), null, `${id}: a device the grid does not offer has no More (its row is read-only)`);
    await press(more('fan'));
    await wait(40);
    assert.deepEqual(window.ChauffeurHaCards.mounted.map(spec => [spec.config.entity, spec.interactive]), [['fan.bedroom', true]],
      JSON.stringify(window.ChauffeurHaCards.mounted));
  } finally { delete window.ChauffeurHaCards; t.cleanup(); }
});

check('media_ring_play_volume_mute_source', async () => {
  const t = await mount([SPEAKER, TV]);
  try {
    await open(t, 'speaker');
    const text = part('now-playing')?.textContent || '';
    assert.ok(/So What/.test(text) && /Miles Davis/.test(text), `title and artist as text: ${JSON.stringify(text)}`);
    let calls = await sent(t, () => press(act('play')));
    assert.ok(calls.length === 1 && calls[0][0] === 'media_player' && ['media_play_pause', 'media_pause'].includes(calls[0][1])
      && JSON.stringify(calls[0][2]) === JSON.stringify({entity_id: 'media_player.kitchen'}), `play/pause once: ${JSON.stringify(calls)}`);
    for (const [name, service] of [['next', 'media_next_track'], ['previous', 'media_previous_track']]) {
      calls = await sent(t, () => press(act(name)));
      assert.deepEqual(calls, [['media_player', service, {entity_id: 'media_player.kitchen'}]], `${name}: ${JSON.stringify(calls)}`);
    }
    assert.deepEqual([range(arc('volume'))[1], Math.round(now(slider('volume')))], [100, 30], 'a volume arc in percent');
    t.calls.length = 0;
    await steps('volume', 'ArrowUp', 5); await settle();
    calls = t.serviceCalls();
    assert.ok(calls.length === 1 && calls[0][1] === 'volume_set' && Math.abs(calls[0][2].volume_level - .35) < .001
      && calls[0][2].entity_id === 'media_player.kitchen', `one volume_set at 0.35: ${JSON.stringify(calls)}`);
    assert.equal(Math.round(now(slider('volume'))), 35, 'the arc shows the confirmed volume');
    assert.equal(toggleOf('mute')?.getAttribute('aria-checked'), 'false', 'mute from is_volume_muted');
    calls = await sent(t, () => press(flip('mute')));
    assert.deepEqual(calls, [['media_player', 'volume_mute', {is_volume_muted: true, entity_id: 'media_player.kitchen'}]], JSON.stringify(calls));
    assert.equal(toggleOf('mute').getAttribute('aria-checked'), 'true');
    const sources = part('sources');
    assert.ok(sources, 'a source list');
    const select = sources.matches('select') ? sources : sources.querySelector('select');
    calls = await sent(t, async () => {
      if (select) {
        assert.deepEqual(select.querySelectorAll('option').map(o => o.textContent.trim()), ['Radio', 'Spotify', 'TV'], 'the options are source_list');
        select.value = 'Radio'; select.dispatchEvent(new Event('change', {bubbles: true}));
      } else {
        assert.deepEqual(chips('sources'), ['radio', 'spotify', 'tv'], 'one button per source');
        await press(pick('sources', 'Radio'));
      }
    });
    assert.deepEqual(calls, [['media_player', 'select_source', {source: 'Radio', entity_id: 'media_player.kitchen'}]], JSON.stringify(calls));
    // No artwork: it lives behind Home Assistant's authentication.
    const ring = ringNode();
    assert.equal(ring.querySelectorAll('img, image, picture').length, 0, 'no picture in the ring');
    const painted = [ring, ...ring.querySelectorAll('*')].filter(n => /url\(/.test(String(n.style.backgroundImage || n.style.background || '')));
    assert.deepEqual(painted.map(n => n.localName), [], 'no background picture either');
    assert.ok(!/media_player_proxy|entity_picture|abc123/.test(JSON.stringify(ser(ring))), 'the ring never names the artwork');
    await open(t, 'tv');
    assert.ok(action('play') && slider('volume'), 'a plain TV: play/pause and volume');
    for (const name of ['previous', 'next', 'mute', 'sources']) assert.equal(part(name), null, `a TV without the feature has no ${name}`);
    assert.deepEqual(t.confirms, [], 'no media control asks');
  } finally { t.cleanup(); }
});

check('lock_unlock_confirms_once', async () => {
  const t = await mount([LOCK]);
  try {
    await open(t, 'lock');
    assert.ok(/^lock$/i.test(action('lock')?.textContent.trim()) && /^unlock$/i.test(action('unlock')?.textContent.trim()),
      'plain verbs: Lock and Unlock');
    let calls = await sent(t, () => press(act('unlock')));
    assert.equal(t.confirms.length, 1, `Unlock asks exactly once: ${JSON.stringify(t.confirms)}`);
    assert.deepEqual(calls, [['lock', 'unlock', {entity_id: 'lock.front_door'}]], JSON.stringify(calls));
    calls = await sent(t, () => press(act('lock')));
    assert.equal(t.confirms.length, 1, 'Lock asks nothing');
    assert.deepEqual(calls, [['lock', 'lock', {entity_id: 'lock.front_door'}]], JSON.stringify(calls));
    t.confirm = false;
    calls = await sent(t, () => press(act('unlock')));
    assert.deepEqual([t.confirms.length, calls], [2, []], 'a declined Unlock sends nothing');
    assert.deepEqual(t.dialogs, [], 'no browser dialog');
  } finally { t.cleanup(); }
});

check('alarm_modes_from_features_and_an_in_page_code', async () => {
  const t = await mount([ALARM, ALARM_NOCODE]);
  try {
    await open(t, 'alarm');
    assert.deepEqual(chips('arm').sort(), ['arm_away', 'arm_home', 'arm_night'], 'one Arm button per supported mode (1|2|4)');
    assert.ok(action('disarm'), 'a Disarm');
    // Arming with code_arm_required asks for the code in the page, and nothing else.
    let before = t.inputs.length;
    t.calls.length = 0;
    await press(pick('arm', 'Arm away'));
    const how = await answerCode(t, before);
    await wait(120);
    assert.deepEqual(t.serviceCalls(), [['alarm_control_panel', 'alarm_arm_away', {code: '1234', entity_id: 'alarm_control_panel.house'}]],
      `armed away with the code (${how}): ${JSON.stringify(t.serviceCalls())}`);
    assert.deepEqual(t.confirms, [], 'arming asks no confirm');
    // Disarm: one confirm, and the code.
    before = t.inputs.length;
    t.calls.length = 0;
    await press(act('disarm'));
    await answerCode(t, before);
    await wait(120);
    assert.equal(t.confirms.length, 1, `Disarm asks exactly once: ${JSON.stringify(t.confirms)}`);
    assert.deepEqual(t.serviceCalls(), [['alarm_control_panel', 'alarm_disarm', {code: '1234', entity_id: 'alarm_control_panel.house'}]],
      JSON.stringify(t.serviceCalls()));
    // No code_format: no code is asked for.
    await open(t, 'shedalarm');
    assert.deepEqual(chips('arm').sort(), ['arm_away', 'arm_home'], 'only the modes the panel supports (1|2)');
    before = t.inputs.length;
    let calls = await sent(t, () => press(act('disarm')));
    assert.equal(t.confirms.length, 2, 'Disarm asks once');
    assert.deepEqual(calls, [['alarm_control_panel', 'alarm_disarm', {entity_id: 'alarm_control_panel.shed'}]], `no code: ${JSON.stringify(calls)}`);
    assert.equal(t.inputs.length, before, 'no code asked for');
    assert.ok(!document.querySelectorAll('[data-ring-part="code"]').some(node => shown(node)), 'no code sheet shown');
    calls = await sent(t, () => press(pick('arm', 'Arm home')));
    assert.deepEqual(calls, [['alarm_control_panel', 'alarm_arm_home', {entity_id: 'alarm_control_panel.shed'}]], JSON.stringify(calls));
    assert.deepEqual(t.dialogs, [], `never a browser dialog: ${JSON.stringify(t.dialogs)}`);
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

check('vacuum_actions_follow_its_features', async () => {
  const t = await mount([VACUUM, VAC_BASIC]);
  try {
    await open(t, 'vacuum');
    for (const [name, service] of [['start', 'start'], ['pause', 'pause'], ['return', 'return_to_base'], ['locate', 'locate']]) {
      const calls = await sent(t, () => press(act(name)));
      assert.deepEqual(calls, [['vacuum', service, {entity_id: 'vacuum.downstairs'}]], `${name}: ${JSON.stringify(calls)}`);
    }
    await open(t, 'vacbasic');
    assert.ok(action('start') && action('pause') && action('return'), 'start, pause and return');
    assert.equal(part('locate'), null, 'no LOCATE: no locate');
  } finally { t.cleanup(); }
});

check('humidifier_ring', async () => {
  const t = await mount([HUMID]);
  try {
    await open(t, 'humid');
    assert.equal(toggleOf('center')?.getAttribute('aria-checked'), 'true', 'on/off in the centre');
    assert.deepEqual(range(arc('target')), [30, 80, 45], 'a target arc: min_humidity..max_humidity at humidity');
    await steps('target', 'ArrowUp', 2); await settle();
    assert.deepEqual(t.serviceCalls(), [['humidifier', 'set_humidity', {humidity: 47, entity_id: 'humidifier.bedroom'}]], JSON.stringify(t.serviceCalls()));
    assert.deepEqual(chips('modes'), ['normal', 'eco', 'boost'], 'mode chips from available_modes');
    assert.deepEqual(pressed('modes'), ['normal']);
    let calls = await sent(t, () => press(pick('modes', 'eco')));
    assert.deepEqual(calls, [['humidifier', 'set_mode', {mode: 'eco', entity_id: 'humidifier.bedroom'}]], JSON.stringify(calls));
    calls = await sent(t, () => press(flip('center')));
    assert.ok(calls.length === 1 && calls[0][0] === 'humidifier' && ['toggle', 'turn_off'].includes(calls[0][1]), `off: ${JSON.stringify(calls)}`);
    assert.equal(toggleOf('center').getAttribute('aria-checked'), 'false', 'the centre shows the confirmed state');
  } finally { t.cleanup(); }
});

check('water_heater_ring', async () => {
  const t = await mount([WATER]);
  try {
    await open(t, 'water');
    assert.deepEqual(range(arc('target')), [110, 140, 120], 'a target arc: min_temp..max_temp at temperature');
    await steps('target', 'ArrowUp', 2); await settle();
    assert.deepEqual(t.serviceCalls(), [['water_heater', 'set_temperature', {temperature: 122, entity_id: 'water_heater.tank'}]], JSON.stringify(t.serviceCalls()));
    assert.deepEqual(chips('modes'), ['off', 'eco', 'electric', 'performance'], 'mode chips from operation_list');
    assert.deepEqual(pressed('modes'), ['eco']);
    let calls = await sent(t, () => press(pick('modes', 'performance')));
    assert.deepEqual(calls, [['water_heater', 'set_operation_mode', {operation_mode: 'performance', entity_id: 'water_heater.tank'}]], JSON.stringify(calls));
    assert.equal(toggleOf('center')?.getAttribute('aria-checked'), 'true', 'a heater in a mode is on');
    calls = await sent(t, () => press(flip('center')));
    assert.deepEqual(calls, [['water_heater', 'turn_off', {entity_id: 'water_heater.tank'}]], JSON.stringify(calls));
    assert.equal(toggleOf('center').getAttribute('aria-checked'), 'false');
  } finally { t.cleanup(); }
});

check('sensors_are_read_only', async () => {
  const t = await mount([SENSOR, DOOR]);
  try {
    await open(t, 'temp');
    assert.ok(/54\.3/.test(ringText()) && /°F/.test(ringText()), `the value and its unit: ${JSON.stringify(ringText())}`);
    assert.equal(ringNode().querySelectorAll('[role="slider"], [role="switch"], input, select').length, 0, 'no control');
    for (const node of buttonsIn(ringNode())) await press(node);
    await settle();
    assert.deepEqual(t.serviceCalls(), [], 'nothing is sent from a sensor');
    await open(t, 'door');
    assert.ok(/open/i.test(ringText()), `a contact sensor says open: ${JSON.stringify(ringText())}`);
    for (const node of buttonsIn(ringNode())) await press(node);
    await settle();
    assert.deepEqual(t.serviceCalls(), [], 'nothing is sent from a sensor');
  } finally { t.cleanup(); }
});

check('camera_ring_shows_a_still_that_refreshes', async () => {
  // The server's camera route, faked at fetch: each answer a fresh frame, or held back
  // (gate), or a refusal (status).
  const asked = []; let gate = null, status = 200, n = 0;
  const realFetch = globalThis.fetch;
  globalThis.fetch = window.fetch = async (url, options = {}) => {
    asked.push({url: String(url), options});
    if (gate) await gate.promise;
    if (options.signal?.aborted) throw new DOMException('aborted', 'AbortError');
    if (status !== 200) return new Response(JSON.stringify({detail: 'This camera is not available here.'}), {status, headers: {'Content-Type': 'application/json'}});
    return new Response(new Blob([new Uint8Array([137, 80, 78, 71, ++n])], {type: 'image/png'}), {status: 200, headers: {'Content-Type': 'image/png'}});
  };
  const hold = () => { let release; const promise = new Promise(r => { release = r; }); gate = {promise, release}; };
  window.chfPersonToken = () => 'member-sekrit';
  const t = await mount([CAMERA]);
  try {
    await open(t, 'camera');
    const still = part('still');
    assert.ok(still, 'a [data-ring-part="still"]');
    const img = () => { const node = part('still'); return node && (node.localName === 'img' ? node : node.querySelector('img')); };
    const src = () => String(img()?.src || img()?.getAttribute('src') || '');
    assert.ok(img(), 'the still is an img');
    await wait(100);
    assert.ok(asked.length >= 1, 'the ring asks for a frame');
    const first = asked[0];
    assert.ok(first.url.includes('api/house/camera/camera.porch'), `through the server's camera route: ${first.url}`);
    assert.ok(!first.url.startsWith('/'), `page-relative (base() + 'api/...'), never root-relative: ${first.url}`);
    assert.ok(!/camera_proxy|cafe5eed|token=/.test(first.url), `no token and never Home Assistant's own path in the URL: ${first.url}`);
    assert.equal(new Headers(first.options.headers || {}).get('X-Member-Token'), 'member-sekrit', 'the person rides a header, as chfAuthUrl would');
    assert.ok(first.options.signal && typeof first.options.signal.aborted === 'boolean', 'each frame has a deadline (an AbortSignal)');
    assert.ok(src().startsWith('blob:'), `the frame is shown from memory: ${src()}`);
    const shown = src();
    await wait(2400);
    assert.ok(asked.length >= 2 && src() !== shown && src().startsWith('blob:'), `refreshed within 2 s: ${asked.length} asks, ${shown} -> ${src()}`);
    // A camera (or Home Assistant) that does not answer: no pile of requests behind it.
    hold();
    await wait(2300);
    const pending = asked.length;
    await wait(4500);
    assert.equal(asked.length, pending, `nothing more is asked while a frame is pending: ${asked.length - pending} more`);
    gate.release(); gate = null;
    await wait(2400);
    assert.ok(asked.length > pending, 'and the refresh carries on once it answers');
    const last = img();
    await escape();
    assert.equal(t.live.ring(), null, 'Escape closes it');
    const after = String(last.src || ''), count = asked.length;
    await wait(2400);
    assert.equal(asked.length, count, 'no frame is asked for once the ring is closed');
    assert.ok(asked.at(-1).options.signal.aborted || String(last.src || '') === after, 'an open request goes with it');
    // A refusal by the grid says why and stops asking.
    status = 403;
    await open(t, 'camera');
    await wait(300);
    assert.ok(/not available here/.test(ringText()), `the refusal is said: ${ringText()}`);
    const refused = asked.length;
    await wait(2400);
    assert.equal(asked.length, refused, 'and nothing more is asked');
    assert.deepEqual(t.serviceCalls(), [], 'a camera sends nothing');
  } finally { gate?.release(); globalThis.fetch = window.fetch = realFetch; delete window.chfPersonToken; t.cleanup(); }
});

const CAMERA_ACCESSORIES = [
  {entity_id:'light.front_spotlight', name:'Spotlight', kind:'light', offered:true},
  {entity_id:'switch.front_privacy', name:'Privacy mode', kind:'switch', offered:true},
  {entity_id:'input_boolean.front_ir', name:'Infrared', kind:'switch', offered:true},
  {entity_id:'siren.front', name:'Siren', kind:'other', offered:true},
  {entity_id:'button.front_restart', name:'Restart', kind:'other', offered:true},
];
async function accessoryCamera({cameraOffered = false, spotlightOffered = true} = {}) {
  const accessories = structuredClone(CAMERA_ACCESSORIES); accessories[0].offered = spotlightOffered;
  const extraStates = Object.fromEntries(accessories.map(a => [a.entity_id, {state:'off', attributes:{}}]));
  extraStates['binary_sensor.front_motion'] = {state:'on', attributes:{device_class:'motion'}};
  return mount([{...CAMERA, name:'Front camera', offered:cameraOffered, accessories,
    entities:[CAMERA.entity_id, ...accessories.map(a => a.entity_id), 'binary_sensor.front_motion']}], {extraStates});
}
const accessory = (root, entity) => root.querySelector(`[data-accessory="${entity}"]`);
check('camera_ring_accessories_use_their_own_entity_and_permission', async () => {
  const t = await accessoryCamera();
  try {
    await open(t, 'camera', 'hold');
    assert.ok(!part('still'), 'a refused camera never asks for a frame');
    for (const a of CAMERA_ACCESSORIES) assert.ok(accessory(ringNode(), a.entity_id).textContent.includes(a.name));
    const spotlight = accessory(ringNode(), 'light.front_spotlight').querySelector('[role="switch"]');
    assert.equal(spotlight.getAttribute('aria-label'), 'Spotlight');
    assert.equal(spotlight.getAttribute('aria-checked'), 'false');
    let calls = await sent(t, () => press(spotlight));
    assert.deepEqual(calls, [['light','toggle',{entity_id:'light.front_spotlight'}]]);
    assert.equal(spotlight.getAttribute('aria-checked'), 'true');
    assert.equal(t.live.ring().device_id, 'camera');
    const privacy = accessory(ringNode(), 'switch.front_privacy').querySelector('[role="switch"]');
    calls = await sent(t, () => press(privacy));
    assert.deepEqual(calls, [['switch','toggle',{entity_id:'switch.front_privacy'}]]);
    for (const [id, domain, service] of [['input_boolean.front_ir','input_boolean','toggle'],
      ['siren.front','siren','turn_on'], ['siren.front','siren','turn_off'], ['button.front_restart','button','press']]) {
      calls = await sent(t, () => press(accessory(ringNode(), id).querySelector('button')));
      assert.deepEqual(calls, [[domain, service, {entity_id:id}]]);
    }
    t.states['light.front_spotlight'].state = 'off'; await t.live.refresh();
    assert.equal(spotlight.getAttribute('aria-checked'), 'false', 'secondary-only state pushes update in place');
    assert.ok(!accessory(ringNode(), 'binary_sensor.front_motion'), 'sensors are not accessory controls');
    assert.equal(await t.live.control('binary_sensor.front_motion', 'toggle'), false);
    assert.deepEqual(domErrors, []);
  } finally { t.cleanup(); }
});
check('camera_unoffered_accessory_is_state_only_on_both_surfaces', async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(new Blob(['frame']), {status:200});
  const t = await accessoryCamera({cameraOffered:true, spotlightOffered:false});
  try {
    await open(t, 'camera', 'hold');
    assert.ok(part('still'), 'camera allowed independently');
    let item = accessory(ringNode(), 'light.front_spotlight');
    assert.match(item.textContent, /Spotlight: Off/);
    assert.equal(item.querySelector('button'), null);
    assert.equal(await t.live.control('light.front_spotlight', 'toggle'), false);
    await escape(); t.live.openRoom('b', 'r'); await wait(50);
    item = accessory(document.getElementById('twin-room-panel'), 'light.front_spotlight');
    assert.match(item.textContent, /Spotlight: Off/); assert.equal(item.querySelector('button'), null);
    t.states['light.front_spotlight'].state = 'on'; await t.live.refresh();
    assert.match(item.textContent, /Spotlight: On/);
    assert.deepEqual(t.serviceCalls(), []);
  } finally { t.cleanup(); globalThis.fetch = realFetch; }
});
check('camera_room_row_has_the_same_accessory_controls', async () => {
  const t = await accessoryCamera();
  try {
    t.live.openRoom('b','r'); await wait(50);
    const panel = document.getElementById('twin-room-panel');
    const row = panel.querySelector('[data-device-id="camera"]');
    const spotlight = accessory(row, 'light.front_spotlight').querySelector('[role="switch"]');
    assert.equal(spotlight.getAttribute('aria-label'), 'Spotlight');
    const calls = await sent(t, () => press(spotlight));
    assert.deepEqual(calls, [['light','toggle',{entity_id:'light.front_spotlight'}]]);
    assert.equal(spotlight.getAttribute('aria-checked'), 'true');
    t.states['switch.front_privacy'].state = 'on'; await t.live.refresh();
    assert.equal(accessory(row,'switch.front_privacy').querySelector('[role="switch"]').getAttribute('aria-checked'), 'true');
    assert.deepEqual(domErrors, []);
  } finally { t.cleanup(); }
});

check('every_kind_unoffered_is_read_only', async () => {
  const rows = [HEAT, FAN, BLIND, GARAGE, SPEAKER, LOCK, ALARM, VACUUM, HUMID, WATER, SCENE, SCRIPT]
    .map(row => ({...row, offered: false}));
  const t = await mount(rows);
  try {
    for (const id of ['scene', 'script']) {
      const calls = await sent(t, () => t.tap(id));
      assert.deepEqual(calls, [], `a tap on an unoffered ${id} runs nothing`);
    }
    for (const row of rows.filter(r => !['scene', 'script'].includes(r.device_id))) {
      await open(t, row.device_id, 'hold');
      const controls = ringNode().querySelectorAll('button, input, select, [role="slider"], [role="switch"], [role="radio"]');
      const live = controls.filter(n => !isDisabled(n));
      assert.deepEqual(live.map(n => n.getAttribute('data-ring-part') || n.getAttribute('aria-label') || n.textContent), [],
        `${row.device_id}: every control in an unoffered ring is disabled`);
      for (const node of controls) {
        await press(node);
        if (node.getAttribute('role') === 'slider') for (const name of ['ArrowUp', 'ArrowDown', 'End']) key(node, name);
      }
    }
    await settle();
    assert.deepEqual(t.serviceCalls(), [], `nothing is sent from a read-only ring: ${JSON.stringify(t.serviceCalls())}`);
    assert.deepEqual([t.confirms, t.inputs], [[], []], 'and nothing is asked');
  } finally { t.cleanup(); }
});

check('room_panel_rows_use_the_same_builders', async () => {
  const t = await mount([HEAT, BLIND, SPEAKER]);
  try {
    t.live.openRoom('b', 'r');
    await wait(60);
    const panel = document.getElementById('twin-room-panel');
    assert.ok(panel && !panel.hidden, 'the room panel opens');
    const row = id => panel.querySelector(`[data-device-id="${id}"]`);
    const named = (node, text) => buttonsIn(node).find(n => nameOf(n) === norm(text)) || null;
    const arcs = node => node.querySelectorAll('input, [role="slider"]').filter(n => n.type === 'range' || n.getAttribute('role') === 'slider');
    for (const mode of ['off', 'heat', 'cool', 'heat_cool']) assert.ok(named(row('heat'), mode), `the thermostat's row has the ${mode} chip`);
    let calls = await sent(t, () => press(named(row('heat'), 'cool')));
    assert.deepEqual(calls, [['climate', 'set_hvac_mode', {hvac_mode: 'cool', entity_id: 'climate.living'}]], JSON.stringify(calls));
    assert.ok(arcs(row('heat')).length >= 1, "the thermostat's row sets its setpoint");
    for (const verb of ['open', 'stop', 'close']) assert.ok(named(row('blind'), verb), `the blind's row has ${verb}`);
    assert.ok(arcs(row('blind')).length >= 2, "the blind's row sets its position and tilt");
    calls = await sent(t, () => press(named(row('blind'), 'close')));
    assert.deepEqual(calls, [['cover', 'close_cover', {entity_id: 'cover.living_blind'}]], JSON.stringify(calls));
    assert.ok(arcs(row('speaker')).length >= 1, "the speaker's row sets its volume");
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

const only = process.argv.slice(3);
let passed = 0, ran = 0;
for (const [name, fn] of checks) {
  if (only.length && !only.includes(name)) continue;
  ran++;
  domErrors.length = 0;
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 900)); }
}
if (escaped.length) console.log('  note: escaped ' + escaped.slice(0, 3).join(' | ').slice(0, 600));
console.log(`${passed}/${ran} passed`);
process.exit(passed === ran ? 0 : 1);
"""


def run(only=()):
    return R.run(DRIVER, {}, prefix='chauffeur_twin_controls_', timeout=400, args=list(only))


if __name__ == '__main__':
    sys.exit(1 if run(sys.argv[1:]) else 0)
