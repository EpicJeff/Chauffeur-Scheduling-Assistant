import { linkEntityPicker } from './object_shelf.js';
import { EFFECT_TYPES } from '../effects/driver.js';
import { effectLanding } from '../effects/water_ripples.js';
import { resolveFixture } from '../live/emitters.js';

export const effectLabels = Object.fromEntries(Object.entries(EFFECT_TYPES).map(([type, row]) => [type, row.label]));
// A placed effect keeps its shape, so the card offers only the types that shape can be.
export const effectShapes = Object.fromEntries(Object.entries(EFFECT_TYPES).map(([type, row]) => [type, row.shapes]));

// Path effects use the same placement schema as lights. Freeing just the
// dragged point must leave every other mounting anchor intact.
export function effectPathOperation(fixture, path, index) {
  return { op: 'update_effect_fixture', id: fixture.id, change: { path,
    ...(fixture.anchors ? { anchors: fixture.anchors.map((anchor, i) => i === index ? null : anchor) } : {}) } };
}

export function effectCard({ id, getPlan, canEdit, op, onMove, removeSelection, report, helpers }) {
  const { element, field, actions, button, numeric } = helpers;
  const finite = value => numeric(value, -Number.MAX_VALUE, Number.MAX_VALUE);
  const root = element('section'); root.dataset.effectId = id;
  const current = () => getPlan().effect_fixtures?.find(f => f.id === id);
  const f = current(); if (!f) return root;
  root.append(element('h3', f.name || effectLabels[f.type]));
  let pending = Promise.resolve();
  const save = work => { pending = pending.then(() => canEdit() && current() && work()).catch(report); return pending; };
  const change = delta => save(() => op({ op: 'update_effect_fixture', id, change: delta }));
  const options = element('label', 'Type'), select = element('select'); select.setAttribute('aria-label', 'Type');
  for (const [value, title] of Object.entries(effectLabels)) if (effectShapes[value].includes(f.shape)) { const option = element('option', title); option.value = value; select.append(option); }
  select.value = f.type; select.disabled = !canEdit(); select.addEventListener('change', () => change({ type: select.value })); options.append(select); root.append(options);
  field(root, 'Name', f.name || '', v => change({ name: v.trim() || null }), { type: 'text', locked: !canEdit() }).maxLength = 80;
  const switchInput = field(root, 'Switch', f.entity || '', v => change({ entity: v.trim() || null }), { type: 'text', locked: !canEdit() });
  linkEntityPicker(switchInput, ['switch', 'light', 'input_boolean', 'fan', 'binary_sensor', 'climate', 'water_heater']); switchInput.placeholder = 'Optional switch or heater';
  button(actions(root), 'Clear switch', () => change({ entity: null }), !canEdit());
  const sensorInput = field(root, 'Sensor', f.sensor || '', v => save(async () => {
    const sensor = v.trim();
    if (!sensor) return op({ op: 'update_effect_fixture', id, change: { sensor: null, sensor_min: null, sensor_max: null } });
    let attribute = current().sensor_attribute;
    if (!/^(sensor|number|input_number)\./.test(sensor) && !attribute) {
      attribute = await window.promptInput('Sensor attribute', 'Numeric attribute to read, such as current_temperature or percentage.', { value: '' });
      if (!attribute?.trim() || !canEdit()) { sensorInput.value = current()?.sensor || ''; return; }
      attribute = attribute.trim();
    }
    let { sensor_min, sensor_max } = current();
    if (!Number.isFinite(sensor_min) || !Number.isFinite(sensor_max)) {
      const low = await window.promptInput('Sensor minimum', 'Value at the minimum effect size.', { value: '0' });
      if (low === null || low === undefined || !canEdit()) { sensorInput.value = current()?.sensor || ''; return; }
      const high = await window.promptInput('Sensor maximum', 'Value at the maximum effect size. A lower value inverts the range.', { value: '100' });
      if (high === null || high === undefined || !canEdit()) { sensorInput.value = current()?.sensor || ''; return; }
      sensor_min = finite(low); sensor_max = finite(high);
    }
    if (sensor_min === sensor_max) throw new Error('Sensor minimum and maximum must differ.');
    await op({ op: 'update_effect_fixture', id, change: { sensor, sensor_min, sensor_max, ...(attribute ? { sensor_attribute: attribute } : {}) } });
  }), { type: 'text', locked: !canEdit() });
  linkEntityPicker(sensorInput, ['sensor', 'number', 'input_number', 'fan', 'climate', 'water_heater', 'light', 'cover', 'valve']); sensorInput.placeholder = 'Optional numeric sensor';
  const attributeInput = field(root, 'Attribute', f.sensor_attribute || '', v => change({ sensor_attribute: v.trim() || null }), { type: 'text', locked: !canEdit() || !f.sensor });
  attributeInput.placeholder = 'Empty reads the sensor state';
  const attributes = element('datalist'); attributes.id = 'effect-attributes-' + id.slice(7);
  attributeInput.setAttribute('list', attributes.id); attributeInput.parentElement.append(attributes);
  if (f.sensor) Promise.resolve().then(async () => {
    const response = await fetch((window.chfBase ?? '../') + 'api/ha/card/states');
    if (!response.ok) return;
    const rows = await response.json();
    if (rows.reachable === false) return;
    const entity = rows.states?.[f.sensor];
    for (const [name, value] of Object.entries(entity?.attributes || {})) if ((typeof value === 'number' || typeof value === 'string' && value.trim()) && Number.isFinite(Number(value))) {
      const option = element('option'); option.value = name; attributes.append(option);
    }
  }).catch(() => {});
  button(actions(root), 'Clear sensor', () => change({ sensor: null, sensor_min: null, sensor_max: null }), !canEdit());
  if (f.sensor) {
    field(root, 'Sensor min', f.sensor_min, v => change({ sensor_min: finite(v) }), { locked: !canEdit() });
    field(root, 'Sensor max', f.sensor_max, v => change({ sensor_max: finite(v) }), { locked: !canEdit() });
  }
  const defaults = [EFFECT_TYPES[f.type].size_min, EFFECT_TYPES[f.type].size_max];
  if (['point','line'].includes(f.shape)) field(root, 'Offset (ft)', f.offset_ft ?? 0, v => change({ offset_ft: numeric(v, -50, 50) }), { locked: !canEdit(), low: -50, high: 50 });
  field(root, 'Size at min (ft)', f.size_min ?? defaults[0], v => change({ size_min: numeric(v, 0, 30) }), { locked: !canEdit(), low: 0, high: 30 });
  field(root, 'Size at max (ft)', f.size_max ?? defaults[1], v => change({ size_max: numeric(v, 0, 30) }), { locked: !canEdit(), low: 0, high: 30 });
  field(root, 'Level (%)', (f.strength ?? 1) * 100, v => change({ strength: numeric(v, 0, 100) / 100 }), { locked: !canEdit(), low: 0, high: 100 });
  if (['waterfall', 'sheer'].includes(f.type)) {
    field(root, 'Drop (ft)', f.drop_ft ?? '', v => change({ drop_ft: v.trim() ? numeric(v, .1, 40) : null }), { locked: !canEdit(), low: .1, high: 40 });
    root.append(element('p', 'Leave Drop blank for the pool, spa or ground below.'));
  }
  if (f.type === 'spa_jet' && !effectLanding(getPlan(), resolveFixture(f, getPlan()).at).body) root.append(element('p', 'Spa jet needs pool or spa water within 3 ft. Move it to the water’s edge.'));
  if (f.orphaned || f.detached) root.append(element('p', f.orphan_reason || f.detached_reason || 'The mounting reference is missing.'));
  const row = actions(root);
  button(row, f.shape === 'line' ? 'Redraw' : 'Move', () => { if (canEdit()) onMove?.(current()); }, !canEdit());
  button(row, 'Delete', () => save(async () => {
    const removed = removeSelection?.(id); if (removed) return removed;
    if (await window.promptConfirm('Delete this effect?', 'Undo restores the effect.', 'Delete', 'Cancel') && canEdit()) await op({ op: 'delete_effect_fixture', id });
  }), !canEdit());
  return root;
}
