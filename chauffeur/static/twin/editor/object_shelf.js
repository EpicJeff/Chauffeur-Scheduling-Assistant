import { schema, propertyFields, objectOperation } from '../objects.js';
import { libUrl } from '../twin_library.js';
import { request } from './api.js';
import { createSlotRow, idleLibrary } from './slot_row.js';

const labels = { rotation: 'Yaw (degrees)', pitch: 'Pitch (degrees)', roll: 'Roll (degrees)', scale: 'Scale (factor)', scale_axes: 'X, Y, Z scale', mirror_x: 'Mirror left-right', mirror_y: 'Mirror front-back', casts_shadow: 'Casts shadow', visible_in: 'Visible in', tint: 'Material tint', elevation: 'Height above surface (ft)', emissive: 'Emissive', emissive_color: 'Glow colour', light_entity: 'Linked HA light (optional)', object_kind: 'Object kind' };
export const isObject = record => record && (['item', 'planting', 'furniture'].includes(record.kind) || record.kind === 'anchor' && !record.piece.device);

let entityList = 0;
// Text entry always works, including when HA is disconnected or the linked
// entity is temporarily missing. Suggestions use the existing entity endpoint.
export function linkEntityPicker(input, domains = ['light', 'switch', 'input_boolean', 'fan']) {
  const list = document.createElement('datalist'); list.id = 'twin-entity-' + ++entityList;
  input.setAttribute('list', list.id); input.placeholder = 'switch.fire_pit'; input.parentElement.append(list);
  Promise.allSettled(domains.map(async domain => {
    const response = await fetch((window.chfBase ?? '../') + 'api/ha/entities?domain=' + domain);
    if (!response.ok) return [];
    const rows = await response.json(); return Array.isArray(rows) ? rows : [];
  })).then(results => {
    for (const row of results.flatMap(r => r.status === 'fulfilled' ? r.value : [])) {
      const option = document.createElement('option'); option.value = row.entity_id;
      option.label = row.attributes?.friendly_name || row.name || row.entity_id; list.append(option);
    }
  });
}

export function drawObjectShelf(host, record, { canEdit, queue, op, report, getRecord = () => record, devices = [], library = idleLibrary, ownSlot = () => {} }) {
  const { piece, kind } = record;
  const section = document.createElement('section'); section.setAttribute('aria-label', 'Object properties'); host.append(section);
  const advanced = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = 'Advanced'; advanced.append(summary);
  const save = properties => queue(() => canEdit() && op(objectOperation(record, properties))).catch(report);
  const s = schema();
  if (!s) return;
  if (kind !== 'opening') {
    const coordinates = piece.host ? Object.keys(piece.host).filter(key => typeof piece.host[key] === 'number') : ['x', 'y'];
    for (const [index, coordinate] of coordinates.entries()) {
      const label = document.createElement('label'); label.textContent = piece.host ? ({u: 'Across room (%)', v: 'Along room (%)', at: 'Along surface (ft)', z: 'Height on surface (ft)', edge: 'Roof edge'}[coordinate] || coordinate) : `Position ${coordinate} (ft)`;
      const input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.setAttribute('aria-label', label.textContent);
      input.value = piece.host ? piece.host[coordinate] * (['u', 'v'].includes(coordinate) ? 100 : 1) : piece.at[index]; input.disabled = !canEdit();
      input.addEventListener('change', () => {
        if (!canEdit() || !input.value.trim()) return;
        const value = Number(input.value) / (piece.host && ['u', 'v'].includes(coordinate) ? 100 : 1);
        queue(() => {
          const current = getRecord()?.piece; if (!current) return;
          return op(current.host ? { op: 'move_hosted', building: record.building.id, id: piece.id, host: { ...current.host, [coordinate]: value } }
            : { op: 'move_site_item', list: kind, index: record.index, at: current.at.map((v, i) => i === index ? value : v) });
        }).catch(report);
      });
      label.append(input); section.append(label);
    }
  }
  const fields = kind === 'opening' ? s.opening : { object_kind: { type: 'choice', choices: Object.keys(s.kinds), default: kind === 'planting' ? 'plant' : 'furniture' }, ...propertyFields(piece, kind) };
  for (const [field, spec] of Object.entries(fields)) {
    if (spec.type === 'object' || spec.free && piece.host || spec.kind && spec.kind !== piece.kind || field === 'model' || kind === 'item' && ['scale', 'rotation'].includes(field)) continue;
    const label = document.createElement('label'); label.textContent = spec.label || labels[field] || field[0].toUpperCase() + field.slice(1);
    const input = document.createElement(spec.type === 'choice' ? 'select' : 'input');
    input.setAttribute('aria-label', label.textContent);
    if (spec.choices) for (const value of spec.choices) { const option = document.createElement('option'); option.value = value; option.textContent = spec.labels?.[value] || value; input.append(option); }
    const value = piece[field] ?? spec.default;
    if (spec.type === 'boolean') { input.type = 'checkbox'; input.checked = !!value; }
    else {
      if (!spec.choices) input.type = ['number', 'angle'].includes(spec.type) ? 'number' : 'text';
      input.value = Array.isArray(value) ? value.join(', ') : value ?? '';
      if (input.type === 'number') { input.step = 'any'; input.min = spec.min ?? -360; input.max = spec.max ?? 360; }
    }
    input.disabled = !canEdit();
    input.addEventListener('change', () => {
      if (!canEdit()) return;
      let next = spec.type === 'boolean' ? input.checked : ['number', 'angle'].includes(spec.type) ? Number(input.value) : input.value;
      if (['number', 'angle'].includes(spec.type) && !input.value.trim()) { report(new Error('Use a finite number.')); return; }
      if (spec.type === 'axes') next = input.value.split(',').map(Number);
      if (spec.type === 'visibility') next = input.value.split(',').map(s => s.trim()).filter(Boolean);
      if (['color', 'light'].includes(spec.type) && !next) next = null;
      save({ [field]: next });
    });
    label.append(input); (spec.advanced ? advanced : section).append(label);
    if (field === 'light_entity') linkEntityPicker(input, ['light', 'switch']);
  }
  if (kind !== 'opening') { section.append(advanced); return; }
  if (piece.kind === 'garage' && !record.building.devices?.some(placed => placed.host?.opening === piece.id
    && devices.some(device => device.device_id === placed.device && device.kind === 'garage' && device.entity_id?.startsWith('cover.')))) {
    const hint = document.createElement('p'); hint.textContent = 'Opens and closes with the garage door device placed on it.'; section.append(hint);
  }
  drawOpeningModelSlot(section, record, { canEdit, queue, op, report, library, ownSlot });
}

// Single and set Properties share the same Library acceptance/reveal path.
// The set card supplies one assignment that batches all of its per-piece ops.
export function drawOpeningModelSlot(host, record, { canEdit, queue, op, report,
  library = idleLibrary, ownSlot = () => {}, records = [record], assign }) {
  const expected = record.piece.kind === 'window' ? 'window' : 'door';
  let entries = [], currentId = record.piece.model || null, disposed = false;
  let mixed = records.some(row => (row.piece.model || null) !== currentId);
  const current = () => {
    if (mixed) return { name: 'Mixed' };
    if (!currentId) return { name: 'Generated' };
    const entry = entries.find(entry => entry.id === currentId) || window.twinManifest?.[currentId];
    return { id: currentId, kind: expected, name: entry?.name || currentId,
      thumb: entry?.thumb || entry?.thumbnail_url || (entry?.thumbnail ? libUrl(currentId, entry.thumbnail) : null) };
  };
  const assignModel = async id => {
    if (!canEdit()) return;
    if (assign) await assign(id);
    else await queue(() => canEdit() && op(objectOperation(record, { model: id })));
    currentId = id; mixed = false;
  };
  const row = createSlotRow({ label: 'Model', subject: `${expected} model`, library,
    readOnly: () => !canEdit(), current,
    accepts: entry => entry.kind === expected || entry.kind === 'furniture' && (entry.object_kind === expected || entry.category === expected),
    apply: entry => {
      const previous = entries.find(row => row.id === entry.id) || window.twinManifest?.[entry.id];
      entries = [...entries.filter(row => row.id !== entry.id), { ...previous, ...entry }];
      return assignModel(entry.id);
    }, clear: () => assignModel(null) });
  host.append(row.element);
  ownSlot({ ...row, dispose() { disposed = true; row.dispose(); } });
  request('imports', 'GET', undefined, 'twin').then(imports => {
    if (disposed) return;
    entries = [...imports.filter(entry => !entry.archived && !entries.some(row => row.id === entry.id)), ...entries]; row.refresh();
  }).catch(report);
  return row;
}
