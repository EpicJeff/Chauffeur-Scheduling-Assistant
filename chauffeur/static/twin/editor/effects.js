import { linkEntityPicker } from './object_shelf.js';

export const effectLabels = { waterfall: 'Waterfall', fountain: 'Fountain jet', bubbler: 'Bubbler', fire: 'Fire' };
const sizes = { waterfall: [.3, 1.5], fountain: [1, 6], bubbler: [.3, 1.5], fire: [.5, 2] };
// A placed effect keeps its shape, so the card offers only the types that shape can be.
const shapes = { waterfall: ['line'], fountain: ['point'], bubbler: ['point'], fire: ['point', 'line'] };

export function effectCard({ id, getPlan, canEdit, op, onMove, report, helpers }) {
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
  for (const [value, title] of Object.entries(effectLabels)) if (shapes[value].includes(f.shape)) { const option = element('option', title); option.value = value; select.append(option); }
  select.value = f.type; select.disabled = !canEdit(); select.addEventListener('change', () => change({ type: select.value })); options.append(select); root.append(options);
  field(root, 'Name', f.name || '', v => change({ name: v.trim() || null }), { type: 'text', locked: !canEdit() }).maxLength = 80;
  const switchInput = field(root, 'Switch', f.entity || '', v => change({ entity: v.trim() || null }), { type: 'text', locked: !canEdit() });
  linkEntityPicker(switchInput, ['switch', 'light', 'input_boolean', 'fan']); switchInput.placeholder = 'Optional switch';
  button(actions(root), 'Clear switch', () => change({ entity: null }), !canEdit());
  const sensorInput = field(root, 'Sensor', f.sensor || '', v => save(async () => {
    const sensor = v.trim();
    if (!sensor) return op({ op: 'update_effect_fixture', id, change: { sensor: null, sensor_min: null, sensor_max: null } });
    let { sensor_min, sensor_max } = current();
    if (!Number.isFinite(sensor_min) || !Number.isFinite(sensor_max)) {
      const low = await window.promptInput('Sensor minimum', 'Value at the minimum effect size.', { value: '0' });
      if (low === null || low === undefined || !canEdit()) { sensorInput.value = current()?.sensor || ''; return; }
      const high = await window.promptInput('Sensor maximum', 'Value at the maximum effect size. A lower value inverts the range.', { value: '100' });
      if (high === null || high === undefined || !canEdit()) { sensorInput.value = current()?.sensor || ''; return; }
      sensor_min = finite(low); sensor_max = finite(high);
    }
    if (sensor_min === sensor_max) throw new Error('Sensor minimum and maximum must differ.');
    await op({ op: 'update_effect_fixture', id, change: { sensor, sensor_min, sensor_max } });
  }), { type: 'text', locked: !canEdit() });
  linkEntityPicker(sensorInput, ['sensor', 'number', 'input_number']); sensorInput.placeholder = 'Optional numeric sensor';
  button(actions(root), 'Clear sensor', () => change({ sensor: null, sensor_min: null, sensor_max: null }), !canEdit());
  if (f.sensor) {
    field(root, 'Sensor min', f.sensor_min, v => change({ sensor_min: finite(v) }), { locked: !canEdit() });
    field(root, 'Sensor max', f.sensor_max, v => change({ sensor_max: finite(v) }), { locked: !canEdit() });
  }
  const defaults = sizes[f.type];
  field(root, 'Size at min (ft)', f.size_min ?? defaults[0], v => change({ size_min: numeric(v, 0, 30) }), { locked: !canEdit(), low: 0, high: 30 });
  field(root, 'Size at max (ft)', f.size_max ?? defaults[1], v => change({ size_max: numeric(v, 0, 30) }), { locked: !canEdit(), low: 0, high: 30 });
  field(root, 'Level (%)', (f.strength ?? 1) * 100, v => change({ strength: numeric(v, 0, 100) / 100 }), { locked: !canEdit(), low: 0, high: 100 });
  if (f.type === 'waterfall') {
    field(root, 'Drop (ft)', f.drop_ft ?? '', v => change({ drop_ft: v.trim() ? numeric(v, .1, 40) : null }), { locked: !canEdit(), low: .1, high: 40 });
    root.append(element('p', 'Leave Drop blank for the pool, spa or ground below.'));
  }
  if (f.orphaned || f.detached) root.append(element('p', f.orphan_reason || f.detached_reason || 'The mounting reference is missing.'));
  const row = actions(root);
  button(row, f.shape === 'line' ? 'Redraw' : 'Move', () => { if (canEdit()) onMove?.(current()); }, !canEdit());
  button(row, 'Delete', () => save(async () => {
    if (await window.promptConfirm('Delete this effect?', 'Undo restores the effect.', 'Delete', 'Cancel') && canEdit()) await op({ op: 'delete_effect_fixture', id });
  }), !canEdit());
  return root;
}
