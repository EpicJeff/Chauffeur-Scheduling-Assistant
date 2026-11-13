import { schema, propertyFields, objectOperation } from '../objects.js';
import { libUrl } from '../twin_library.js';
import { request } from './api.js';

const labels = { rotation: 'Yaw (degrees)', pitch: 'Pitch (degrees)', roll: 'Roll (degrees)', scale: 'Scale (factor)', scale_axes: 'X, Y, Z scale', casts_shadow: 'Casts shadow', visible_in: 'Visible in', tint: 'Material tint', elevation: 'Height above surface (ft)', emissive: 'Emissive', emissive_color: 'Glow colour', light_entity: 'Linked HA light (optional)', object_kind: 'Object kind' };
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

export function drawObjectShelf(host, record, { canEdit, queue, op, report, getRecord = () => record }) {
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
    if (spec.free && piece.host || field === 'model' || kind === 'item' && ['scale', 'rotation'].includes(field)) continue;
    const label = document.createElement('label'); label.textContent = labels[field] || field[0].toUpperCase() + field.slice(1);
    const input = document.createElement(spec.type === 'choice' ? 'select' : 'input');
    input.setAttribute('aria-label', label.textContent);
    if (spec.choices) for (const value of spec.choices) { const option = document.createElement('option'); option.value = value; option.textContent = value; input.append(option); }
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
  const title = document.createElement('h4'); title.textContent = 'Model'; section.append(title);
  const grid = document.createElement('div'); grid.className = 'object-model-grid'; section.append(grid);
  const button = (name, id, entry) => {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = name; node.disabled = !canEdit();
    node.setAttribute('aria-pressed', String((piece.model || null) === id));
    if (entry?.thumbnail) { const image = document.createElement('img'); image.src = libUrl(id, entry.thumbnail); image.alt = ''; node.prepend(image); }
    node.addEventListener('click', () => save({ model: id })); grid.append(node);
  };
  button('Generated', null);
  request('imports', 'GET', undefined, 'twin').then(entries => {
    if (!section.isConnected) return;
    const expected = piece.kind === 'window' ? 'window' : 'door';
    for (const entry of entries.filter(e => !e.archived && e.kind === expected)) button(entry.name, entry.id, entry);
    for (const [id, entry] of Object.entries(window.twinManifest || {}))
      if (entry.kind === 'model' && (entry.object_kind === expected || entry.category === expected)) button(entry.name || id, id, entry);
  }).catch(report);
}
