"""Node checks for the 3D house's device-kind and mode registries (Task 1 of
docs/superpowers/plans/2026-11-11-twin-device-controls.md; brief
.superpowers/sdd/2026-11-11-twin-device-controls/task-1-brief.md; spec
docs/superpowers/specs/2026-11-11-twin-device-controls-design.md decision 1).

The fake DOM and the live rig are tests/twin_live_node_rig.py's (read its
docstring). Three checks:

every_existing_kind_behaves_as_before
  PASSES TODAY and must keep passing through the refactor. The table
  tests/fixtures/twin_live/kinds_before_registry.json was captured from the code
  before the registries (main v2.499.787, merge 832178a8), by running this very
  file's table builder against it. It pins, per kind:
  - markers.js markerState(kind, state, attributes, entityId) -> {look, label}
    over every kind the catalogue gives (light, switch, outlet, fan, lock,
    garage, blinds, climate, sensor, camera, media, other) plus 'alarm', many
    states, sensor device classes, and the alarm panel known by its entity id;
  - markers.js markerTexture(kind, look, count?) -> the icon drawn on the
    marker's canvas (a hash of what the 2D context drew, transform applied),
    every kind and look, and the room badge's count;
  - room_panel.js deviceActions(row, state, control, {compact}) -> the controls
    (tags, attributes, text, values, disabled) for each kind, offered or not,
    compact (marker sheet) or not (room panel), and what each control sends when
    pressed: through the shared live.control (it carries confirmsUnsafe) and
    through a plain control (the builder asks promptConfirm itself), with the
    confirm's words.
  The signatures above stay as they are; registries sit behind them. Do not
  recapture the table to make it pass. Tasks 3-4 rebuild some kinds' controls on
  purpose; the commit that does so says which rows of the deviceActions table it
  replaces and why, and the looks and icons stay pinned.

a_new_kind_registers_without_core_edits
  static/twin/live/kinds.js exports
      registerKind({id, match(entity), icon, look(state), quick, ring, panel, unsafe})
      kindOf(entity) -> the registration (an object carrying .id)
  - kindOf(row) for the rows today's code knows: a light row -> id 'light'; a row of
    kind 'other' whose entity is alarm_control_panel.* -> id 'alarm' (today's
    iconKind); every catalogue kind -> its own id.
  - match(entity) receives the layout row ({kind, entity_id, ...}); a registered
    kind's match wins over the fallback kind that catches the rest.
  - icon(ctx) draws the glyph on the marker's 96 px canvas 2D context; the layer's
    marker texture for a row of that kind calls it.
  - look(state) receives Home Assistant's state object ({state, attributes}) and
    returns 'on' | 'off' | 'attention' | 'unavailable': the marker's look follows it.
  - quick is the service a tap sends through live.control (null/absent: a tap does not
    send); the test kind's quick 'toggle' makes a tap send valve.toggle once.
  - unsafe is a map {service: verb}; live.control asks promptConfirm once before an
    unsafe service of that kind (the confirm names the device and the verb), and
    nothing before another. (Today's unlock/open/open_cover/alarm_disarm confirms
    stay; the test kind's verb, drain, is one no core file knows.)
  - panel({row, state, control}) returns the node the room panel shows for that
    device; its control is live.control.
  The test kind is registered from the test, before mounting; no core file names it.

modes_register_and_switch
  static/twin/live/modes.js exports registerMode({id, label, enter, update, leave})
  and modes() -> the registrations in order. Lights ({id 'lights', label 'Lights'})
  and All ({id 'all', label 'All'}) are the first two and carry enter/update/leave
  functions. A mode registered before mounting gets a button in the #twin-modes strip
  labelled with its label. Pressing it (or live.setMode(id)) calls its enter once with
  a context {view, live}; while it is the mode, each state update calls its update;
  switching away calls its leave once and stops its updates. The pressed button carries
  aria-pressed="true", the others "false". live.setMode(null) still means All.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_kinds_js.py
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_live_node_rig as R  # noqa: E402

PINNED = Path(__file__).resolve().parent / 'fixtures' / 'twin_live' / 'kinds_before_registry.json'

DRIVER = r"""
const markers = await import(file('static/twin/live/markers.js'));
const panel = await import(file('static/twin/live/room_panel.js'));

// ------------------------------------------------------------- the pinned table
const KINDS = ['light', 'switch', 'outlet', 'fan', 'lock', 'garage', 'blinds', 'climate', 'sensor', 'camera', 'media', 'alarm', 'other'];
const STATES = ['on', 'off', 'unavailable', 'unknown', null, 'locked', 'unlocked', 'unlocking', 'jammed', 'open', 'opening',
  'closed', 'heat', 'idle', 'playing', 'standby', 'triggered', 'pending', 'arming', 'disarmed', 'armed_away', '71.2'];
const SENSOR_CLASSES = ['door', 'window', 'opening', 'garage_door', 'smoke', 'moisture', 'gas', 'motion', 'temperature'];
const LOOKS = ['on', 'off', 'attention', 'unavailable'];

function stateTable() {
  const out = {};
  const put = (kind, attrs, entity, states = STATES) => {
    for (const state of states) {
      const r = markers.markerState(kind, state, attrs, entity);
      out[[kind, String(state), JSON.stringify(attrs), entity].join('|')] = `${r.look}|${r.label}`;
    }
  };
  for (const kind of KINDS) put(kind, {}, '');
  for (const kind of ['sensor', 'climate', 'light']) put(kind, {unit_of_measurement: '°F'}, '');
  for (const cls of SENSOR_CLASSES) {
    put('sensor', {device_class: cls}, '', ['on', 'off', 'unavailable', '71.2']);
    put('sensor', {device_class: cls}, `binary_sensor.${cls}`, ['on', 'off']);
  }
  for (const kind of ['other', 'alarm', 'sensor']) put(kind, {}, 'alarm_control_panel.house');
  put('light', undefined, '', ['on', 'off']); put('light', null, '', ['on', 'off']);
  put('garage', {device_class: 'garage'}, 'cover.garage_door', ['open', 'opening', 'closed', 'closing']);
  return out;
}

function iconTable() {
  const out = {};
  for (const kind of [...KINDS, 'room', 'anything-else']) for (const look of LOOKS) {
    const texture = markers.markerTexture(kind, look);
    out[`${kind}|${look}`] = iconHash(texture.image.__log);
    texture.dispose?.();
  }
  for (const [count, look] of [[3, 'off'], [12, 'attention'], [0, 'off']]) {
    const texture = markers.markerTexture('room', look, count);
    out[`room|${look}|${count}`] = iconHash(texture.image.__log);
  }
  return out;
}

const DEVICES = [
  ['light', 'light.lamp', [['off', {}], ['on', {brightness: 128}], ['on', {}]]],
  ['switch', 'switch.plug', [['on', {}], ['off', {}]]],
  ['outlet', 'switch.kettle', [['off', {device_class: 'outlet'}]]],
  ['fan', 'fan.ceiling', [['on', {}], ['off', {}]]],
  ['lock', 'lock.back_door', [['locked', {}], ['unlocked', {}]]],
  ['garage', 'cover.garage_door', [['closed', {device_class: 'garage'}]]],
  ['blinds', 'cover.blind', [['open', {current_position: 50}]]],
  ['climate', 'climate.hall', [['heat', {temperature: 68, target_temp_step: 1, min_temp: 45, max_temp: 95, current_temperature: 70}],
    ['heat', {temperature: 95, target_temp_step: .5, min_temp: 45, max_temp: 95}], ['off', {}]]],
  ['sensor', 'sensor.kitchen_temperature', [['71.2', {unit_of_measurement: '°F'}]]],
  ['camera', 'camera.porch', [['idle', {}]]],
  ['media', 'media_player.den', [['playing', {volume_level: .4}]]],
  ['other', 'alarm_control_panel.house', [['armed_home', {}]]],
  ['alarm', 'alarm_control_panel.house', [['disarmed', {}]]],
  ['other', 'scene.movie', [['scening', {}]]],
];
const controlsOf = node => node.querySelectorAll('button, input, select');

async function actionTable() {
  const out = {};
  for (const [kind, entity, variants] of DEVICES) for (const [state, attrs] of variants) for (const offered of [true, false])
    for (const compact of [false, true]) {
      const row = {device_id: 'd', name: 'Thing', entity_id: entity, entities: [entity], kind, offered, area_id: 'kitchen'};
      const st = {entity_id: entity, state, attributes: attrs};
      const build = control => panel.deviceActions(row, structuredClone(st), control, {compact});
      const shape = ser(build(Object.assign(async () => true, {confirmsUnsafe: true})));
      const sends = [];
      const count = controlsOf(build(Object.assign(async () => true, {confirmsUnsafe: true}))).length;
      for (let i = 0; i < count; i++) for (const variant of ['shared', 'plain']) {
        const calls = [], confirms = [];
        window.promptConfirm = async (...args) => { confirms.push(args); return true; };
        const record = async (...args) => { calls.push(args); return true; };
        const control = variant === 'shared' ? Object.assign(record, {confirmsUnsafe: true}) : record;
        const node = controlsOf(build(control))[i];
        if (node.localName === 'input') { node.value = '40'; node.dispatchEvent(new Event('change', {bubbles: true})); }
        else node.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
        await wait(5);
        sends.push([i, variant, node.disabled ? 'disabled' : 'enabled', calls, confirms]);
      }
      out[[kind, entity, state, JSON.stringify(attrs), offered ? 'offered' : 'unoffered', compact ? 'compact' : 'full'].join('|')] = {shape, sends};
    }
  return out;
}

async function table() {
  return {states: stateTable(), icons: iconTable(), actions: await actionTable()};
}

if (config.capture) {
  writeFileSync(config.capture, JSON.stringify(await table(), null, 1) + '\n');
  console.log('captured ' + config.capture);
  process.exit(0);
}

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check('every_existing_kind_behaves_as_before', async () => {
  const pinned = JSON.parse(readFileSync(config.pinned, 'utf8'));
  const now = await table();
  for (const part of ['states', 'icons', 'actions']) {
    const want = pinned[part], got = now[part];
    const keys = [...new Set([...Object.keys(want), ...Object.keys(got)])];
    const diffs = keys.filter(k => JSON.stringify(want[k]) !== JSON.stringify(got[k]));
    assert.equal(diffs.length, 0, `${part}: ${diffs.length} of ${keys.length} rows changed; first: ` +
      diffs.slice(0, 3).map(k => `${k}: was ${JSON.stringify(want[k])?.slice(0, 300)} now ${JSON.stringify(got[k])?.slice(0, 300)}`).join(' ;; '));
  }
});

check('a_new_kind_registers_without_core_edits', async () => {
  const kinds = await import(file('static/twin/live/kinds.js'));
  assert.equal(typeof kinds.registerKind, 'function', 'kinds.js exports registerKind');
  assert.equal(typeof kinds.kindOf, 'function', 'kinds.js exports kindOf');
  const id = row => kinds.kindOf(row)?.id;
  for (const kind of ['light', 'switch', 'outlet', 'fan', 'lock', 'garage', 'blinds', 'climate', 'sensor', 'camera', 'media'])
    assert.equal(id({kind, entity_id: `x.${kind}`}), kind, `kindOf a ${kind} row is the ${kind} kind`);
  assert.equal(id({kind: 'other', entity_id: 'alarm_control_panel.house'}), 'alarm', 'an alarm panel is known by its domain');
  assert.equal(id({kind: 'alarm', entity_id: 'alarm_control_panel.house'}), 'alarm');
  const fallback = id({kind: 'other', entity_id: 'valve.sprinkler'});
  assert.ok(fallback, 'an unknown row still resolves to a fallback kind');

  let drawn = 0;
  const panels = [];
  kinds.registerKind({
    id: 'sprinkler',
    match: entity => String(entity?.entity_id || '').startsWith('valve.'),
    icon: ctx => { drawn++; ctx.fillRect(40, 40, 16, 16); },
    look: state => state?.state === 'open' ? 'attention' : 'off',
    quick: 'toggle',
    ring: null,
    panel: ({row, state, control}) => {
      const node = document.createElement('button'); node.type = 'button'; node.dataset.test = 'sprinkler-panel';
      node.textContent = `Water ${row.name} (${state?.state})`;
      node.addEventListener('click', () => control(row.entity_id, 'close'));
      panels.push(node); return node;
    },
    unsafe: {drain: 'Drain'},
  });
  assert.equal(id({kind: 'other', entity_id: 'valve.sprinkler'}), 'sprinkler', 'the registered kind wins over the fallback');
  assert.equal(id({kind: 'light', entity_id: 'light.lamp'}), 'light', 'and leaves the others alone');

  const t = await rig({devices: [
    {device_id: 'valve', name: 'Front sprinkler', entity_id: 'valve.sprinkler', kind: 'other', state: 'open', attributes: {}},
    {device_id: 'lamp', name: 'Lamp', entity_id: 'light.lamp', kind: 'light', state: 'off', attributes: {}},
  ]});
  try {
    const marker = () => t.live.markers().find(m => m.device_id === 'valve');
    assert.equal(marker().look, 'attention', `the marker's look comes from the kind's look(state): ${JSON.stringify(marker())}`);
    assert.ok(drawn > 0, "the marker's texture is drawn by the kind's icon");
    // A tap sends the kind's quick service once, through the shared control path.
    await t.tap('valve');
    assert.deepEqual(t.serviceCalls(), [['valve', 'toggle', {entity_id: 'valve.sprinkler'}]],
      `a tap on the sprinkler sends its quick service: ${JSON.stringify(t.serviceCalls())}`);
    // The kind's unsafe services ask once, the rest ask nothing.
    t.calls.length = 0; t.confirms.length = 0;
    await t.live.control('valve.sprinkler', 'drain');
    assert.equal(t.confirms.length, 1, `the kind's unsafe drain asks once (${t.confirms.length})`);
    assert.ok(JSON.stringify(t.confirms[0]).includes('Front sprinkler') && JSON.stringify(t.confirms[0]).includes('Drain'),
      `the confirm names the device and the verb: ${JSON.stringify(t.confirms[0])}`);
    assert.deepEqual(t.serviceCalls(), [['valve', 'drain', {entity_id: 'valve.sprinkler'}]]);
    t.calls.length = 0; t.confirms.length = 0;
    await t.live.control('valve.sprinkler', 'close');
    assert.equal(t.confirms.length, 0, 'close asks nothing');
    // The room panel shows the kind's panel node, wired to live.control.
    t.live.openRoom('b', 'r');
    const room = document.getElementById('twin-room-panel');
    assert.ok(room && !room.hidden, 'the room panel opens');
    const row = room.querySelectorAll('[data-device-id]').find(n => n.dataset.deviceId === 'valve');
    assert.ok(row, 'the room lists the sprinkler');
    const node = row.querySelector('[data-test="sprinkler-panel"]');
    assert.ok(node, `the sprinkler's row holds its kind's panel node: ${row.textContent}`);
    t.calls.length = 0;
    await press(node);
    assert.deepEqual(t.serviceCalls(), [['valve', 'close', {entity_id: 'valve.sprinkler'}]], 'its control is live.control');
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

check('modes_register_and_switch', async () => {
  const mod = await import(file('static/twin/live/modes.js'));
  assert.equal(typeof mod.registerMode, 'function', 'modes.js exports registerMode');
  assert.equal(typeof mod.modes, 'function', 'modes.js exports modes()');
  const listed = mod.modes();
  assert.deepEqual(listed.slice(0, 2).map(m => [m.id, m.label]), [['lights', 'Lights'], ['all', 'All']],
    `Lights and All are the first registrations: ${JSON.stringify(listed.map(m => m.id))}`);
  for (const m of listed.slice(0, 2)) for (const fn of ['enter', 'update', 'leave'])
    assert.equal(typeof m[fn], 'function', `${m.id} registers ${fn}`);
  const log = [];
  let context = null;
  mod.registerMode({id: 'test', label: 'Test mode',
    enter(ctx) { context = ctx; log.push('enter'); }, update() { log.push('update'); }, leave() { log.push('leave'); }});
  assert.ok(mod.modes().some(m => m.id === 'test'), 'the test mode is listed');
  const t = await rig({devices: [{device_id: 'lamp', name: 'Lamp', entity_id: 'light.lamp', kind: 'light', state: 'on', attributes: {brightness: 200}}]});
  try {
    const strip = document.getElementById('twin-modes');
    assert.ok(strip, 'the mode strip is drawn');
    const button = label => strip.querySelectorAll('button').find(b => b.textContent.trim() === label);
    for (const label of ['Lights', 'All', 'Test mode']) assert.ok(button(label), `the strip has a ${label} button`);
    const pressed = () => strip.querySelectorAll('button').filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.textContent.trim());
    assert.deepEqual(log, [], 'nothing entered before a press');
    await press(button('Test mode'));
    assert.deepEqual(log.filter(x => x !== 'update').slice(0, 1), ['enter'], `pressing Test mode enters it: ${log}`);
    assert.equal(log.filter(x => x === 'enter').length, 1, 'once');
    assert.ok(context && context.live === t.live && context.view === t.view, 'enter gets {view, live}');
    assert.deepEqual(pressed(), ['Test mode'], `only the Test button is pressed: ${pressed()}`);
    const updates = log.filter(x => x === 'update').length;
    t.states['light.lamp'].state = 'off';
    await t.live.refresh();
    assert.ok(log.filter(x => x === 'update').length > updates, 'a state update reaches the active mode');
    t.live.setMode('lights');
    assert.equal(log.filter(x => x === 'leave').length, 1, `switching to Lights leaves Test once: ${log}`);
    assert.deepEqual(pressed(), ['Lights']);
    const after = log.length;
    await t.live.refresh();
    assert.equal(log.length, after, `a mode that was left gets no more updates: ${log.slice(after)}`);
    t.live.setMode('test');
    assert.equal(log.filter(x => x === 'enter').length, 2, 'setMode(id) enters a registered mode');
    t.live.setMode(null);
    assert.equal(log.filter(x => x === 'leave').length, 2, 'setMode(null) leaves it');
    assert.deepEqual(pressed(), ['All'], 'and null still means All');
    assert.deepEqual(domErrors, [], 'no listener threw');
  } finally { t.cleanup(); }
});

let passed = 0;
for (const [name, fn] of checks) {
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 900)); }
}
if (escaped.length) console.log('  note: escaped ' + escaped.slice(0, 3).join(' | ').slice(0, 600));
console.log(`${passed}/${checks.length} passed`);
process.exit(passed === checks.length ? 0 : 1);
"""


def run(config=None):
    return R.run(DRIVER, {'pinned': PINNED.as_posix(), **(config or {})}, prefix='chauffeur_twin_kinds_')


def _reached(start):
    """Every module under static/twin that `start` imports, directly or not."""
    import re
    twin = R.ROOT / 'static' / 'twin'
    seen, todo = set(), [twin / start]
    while todo:
        path = todo.pop()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for spec in re.findall(r"""(?:^|\n)\s*(?:import|export)[^'"]*?from\s*['"](\.[^'"]+)['"]""", path.read_text(encoding='utf-8')):
            todo.append((path.parent / spec).resolve())
    # Vendor modules (three, lucide) sit outside static/twin and are covered by
    # test_twin_import_maps.py; this check is about the twin's own modules.
    return {p.relative_to(twin.resolve()).as_posix()[:-3] for p in (q.resolve() for q in seen)
            if p.is_relative_to(twin.resolve())}


def _mapped(template):
    """The static/twin modules a page's import map versions."""
    import re
    text = (R.ROOT / 'templates' / template).read_text(encoding='utf-8')
    names = set(re.findall(r"static/twin/([a-z_/]+)\.js", text))
    for group in re.findall(r"{%\s*for name in \[([^\]]*)\]", text):
        names.update(re.findall(r"'([a-z_/]+)'", group))
    return names


def import_maps_version_every_live_module():
    """A module the live layer loads but a page's import map does not list loads
    unversioned there, so a stale copy can outlive an upgrade (review L8)."""
    reached = {m for m in _reached('live/live.js') if m.startswith(('live/', 'bake/'))}
    for template in ('house_twin.html', 'house_editor.html'):
        missing = sorted(reached - _mapped(template))
        if missing:
            print(f'  FAIL import_maps_version_every_live_module {template} leaves out {missing}')
            return 1
    print('  ok   import_maps_version_every_live_module')
    return 0


if __name__ == '__main__':
    sys.exit(1 if (run() | import_maps_version_every_live_module()) else 0)
