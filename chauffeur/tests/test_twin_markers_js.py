"""Node checks for the 3D house's device markers (piece 3 Task 6 of
docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; brief
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-6-brief.md).

static/twin/live/markers.js runs in node (three resolves to the vendored r187):

    markerState(kind, state, attributes) -> {look: 'on'|'off'|'attention'|'unavailable', label: str}
    levelOfDetail(markers, pxPerFoot) -> {badges: [{building, room, count, attention}],
                                          markers: [device_id], labels: bool}

What this file assumes of markers.js (the implementer matches these):
- Both are named exports and pure: importing the module touches no DOM
  (no document or canvas at module load), so node can import it.
- `kind` is the catalogue's device kind (twin_ha: light, switch, fan, lock,
  garage, climate, sensor, ...); a binary sensor is kind 'sensor' and its
  class rides in attributes.device_class.
- attention: a lock 'unlocked'; a garage 'open' or 'opening'; a sensor whose
  device_class is smoke, moisture or gas and whose state is 'on'.
  unavailable: state 'unavailable' or 'unknown', for any kind (it beats attention).
  Otherwise 'on' or 'off'.
- `label` is a non-empty string; a sensor's label carries its reading.
- levelOfDetail: `pxPerFoot` is how many screen pixels one foot of floor covers
  at the marker. Far out (2 px per foot) every room's markers merge into one
  badge {building, room, count, attention: any marker in it is 'attention'} and
  no marker stands alone; labels are off. Zoomed in (25 px per foot; the live
  scenarios run at about 29) there are no badges, every marker stands alone and
  labels are on. A room is keyed by building and room together.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_markers_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {root} = JSON.parse(readFileSync(process.argv[2]));
const file = p => pathToFileURL(root + '/' + p).href;
const three = file('static/vendor/three-r187/three.module.js');
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url: three, shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format:'module'}), format:'module'} : next(url, ctx);
}});

const mod = await import(file('static/twin/live/markers.js'));
const {markerState, levelOfDetail} = mod;
let passed = 0;
const checks = [];
const check = (name, fn) => checks.push([name, fn]);
const ok = name => { passed++; console.log('  ok   ' + name); };
const LOOKS = ['on', 'off', 'attention', 'unavailable'];

check('marker_states_cover_attention_and_unavailable', () => {
  assert.equal(typeof markerState, 'function', 'markers.js exports markerState');
  const S = (kind, state, attrs = {}) => {
    const out = markerState(kind, state, attrs);
    assert.ok(out && LOOKS.includes(out.look), `${kind} ${state}: look is one of ${LOOKS}: ${JSON.stringify(out)}`);
    assert.ok(typeof out.label === 'string' && out.label.trim(), `${kind} ${state}: a label: ${JSON.stringify(out)}`);
    return out;
  };
  // On and off.
  assert.equal(S('light', 'on').look, 'on');
  assert.equal(S('light', 'off').look, 'off');
  assert.equal(S('switch', 'on').look, 'on');
  assert.equal(S('switch', 'off').look, 'off');
  assert.equal(S('fan', 'on').look, 'on');
  assert.equal(S('fan', 'off').look, 'off');
  // A lock wants attention when unlocked, not when locked.
  assert.equal(S('lock', 'unlocked').look, 'attention');
  assert.ok(['on', 'off'].includes(S('lock', 'locked').look), 'a locked lock is calm');
  // A garage door wants attention while open or opening.
  assert.equal(S('garage', 'open', {device_class: 'garage'}).look, 'attention');
  assert.equal(S('garage', 'opening', {device_class: 'garage'}).look, 'attention');
  assert.ok(['on', 'off'].includes(S('garage', 'closed', {device_class: 'garage'}).look), 'a closed garage is calm');
  // Smoke, moisture and gas sensors want attention when on; other classes do not.
  for (const cls of ['smoke', 'moisture', 'gas']) {
    assert.equal(S('sensor', 'on', {device_class: cls}).look, 'attention', `${cls} on`);
    assert.ok(['on', 'off'].includes(S('sensor', 'off', {device_class: cls}).look), `${cls} off is calm`);
  }
  for (const cls of ['motion', 'door', 'occupancy']) {
    assert.notEqual(S('sensor', 'on', {device_class: cls}).look, 'attention', `${cls} on is not an alarm`);
  }
  // Unavailable and unknown, whatever the kind; unavailable beats attention.
  for (const kind of ['light', 'switch', 'fan', 'lock', 'garage', 'climate', 'sensor', 'other']) {
    assert.equal(S(kind, 'unavailable').look, 'unavailable', `${kind} unavailable`);
    assert.equal(S(kind, 'unknown').look, 'unavailable', `${kind} unknown`);
  }
  assert.equal(S('sensor', 'unavailable', {device_class: 'smoke'}).look, 'unavailable');
  // A reading is the sensor's label; missing attributes never throw.
  assert.ok(S('sensor', '71.2', {unit_of_measurement: '°F', device_class: 'temperature'}).label.includes('71.2'),
    'a sensor label carries its reading');
  for (const attrs of [undefined, null]) {
    const out = markerState('light', 'on', attrs);
    assert.equal(out.look, 'on', `attributes ${attrs} still read`);
  }
  // Labels differ between states a person must tell apart.
  assert.notEqual(S('lock', 'locked').label, S('lock', 'unlocked').label, 'locked and unlocked read differently');
  assert.notEqual(S('garage', 'open').label, S('garage', 'closed').label, 'open and closed read differently');
});

check('room_badge_merges_at_far_zoom', () => {
  assert.equal(typeof levelOfDetail, 'function', 'markers.js exports levelOfDetail');
  const items = [
    {device_id: 'k-light', building: 'pool', room: 'kitchen', look: 'off', kind: 'light'},
    {device_id: 'k-lamp', building: 'pool', room: 'kitchen', look: 'on', kind: 'light'},
    {device_id: 'k-lock', building: 'pool', room: 'kitchen', look: 'attention', kind: 'lock'},
    {device_id: 'h-light', building: 'pool', room: 'hall', look: 'off', kind: 'light'},
    {device_id: 'h-plug', building: 'pool', room: 'hall', look: 'unavailable', kind: 'switch'},
    {device_id: 'm-light', building: 'main', room: 'kitchen', look: 'on', kind: 'light'},
    {device_id: 'm-fan', building: 'main', room: 'kitchen', look: 'off', kind: 'fan'},
  ];
  const ids = list => (list || []).map(m => (m && typeof m === 'object') ? m.device_id : m).sort();
  const far = levelOfDetail(items, 2);
  assert.ok(far && Array.isArray(far.badges), `far: badges: ${JSON.stringify(far)}`);
  const badge = (b, r) => far.badges.filter(x => x.building === b && x.room === r);
  assert.equal(far.badges.length, 3, `one badge per room, rooms keyed by building and room: ${JSON.stringify(far.badges)}`);
  const kitchen = badge('pool', 'kitchen'), hall = badge('pool', 'hall'), main = badge('main', 'kitchen');
  assert.ok(kitchen.length === 1 && hall.length === 1 && main.length === 1, JSON.stringify(far.badges));
  assert.equal(kitchen[0].count, 3, 'the Kitchen badge counts its three markers');
  assert.equal(kitchen[0].attention, true, 'an unlocked lock shows on the badge');
  assert.equal(hall[0].count, 2);
  assert.equal(hall[0].attention, false, 'an unavailable plug is not attention');
  assert.equal(main[0].count, 2);
  assert.equal(main[0].attention, false);
  assert.deepEqual(ids(far.markers), [], 'far out, no marker stands alone');
  assert.equal(far.labels, false, 'no labels far out');

  const near = levelOfDetail(items, 25);
  assert.ok(near && Array.isArray(near.badges), JSON.stringify(near));
  assert.deepEqual(near.badges, [], 'zoomed in, no badges');
  assert.deepEqual(ids(near.markers), ids(items), 'zoomed in, every marker stands alone');
  assert.equal(near.labels, true, 'labels appear zoomed in');

  const empty = levelOfDetail([], 2);
  assert.deepEqual(empty.badges, [], 'no markers, no badges');
});

for (const [name, fn] of checks) {
  try { await fn(); ok(name); }
  catch (error) { console.log('  FAIL ' + name + ' ' + String(error && error.message || error).split('\n')[0].slice(0, 400)); }
}
console.log(`${passed}/${checks.length} passed`);
process.exit(passed === checks.length ? 0 : 1);
"""


def run():
    node = shutil.which('node')
    if not node:
        print('  skip  node is unavailable')
        return 0
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix()}))):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_markers_',
                                             delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([node, str(paths[0]), str(paths[1])], capture_output=True, text=True,
                                encoding='utf-8', timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:], end='')
        return result.returncode
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
