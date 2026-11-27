import { schema, propertyFields, objectOperation } from '../objects.js';
import { libUrl, modelRecord } from '../twin_library.js';
import { request } from './api.js';
import { createSlotRow, idleLibrary } from './slot_row.js';
import { describeMaterial } from './material_catalog.js';
import { prepareModelParts } from './model_records.js';
import { resolvePart } from '../model_parts.js';

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

export function drawObjectShelf(host, record, { canEdit, queue, op, report, getRecord = () => record, getKit = () => ({}), devices = [], library = idleLibrary, ownSlot = () => {} }) {
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
  if (kind !== 'opening') {
    drawModelParts(section, record, { canEdit, queue, op, report, getRecord, getKit, library, ownSlot });
    section.append(advanced); return;
  }
  if (piece.kind === 'garage' && !record.building.devices?.some(placed => placed.host?.opening === piece.id
    && devices.some(device => device.device_id === placed.device && device.kind === 'garage' && device.entity_id?.startsWith('cover.')))) {
    const hint = document.createElement('p'); hint.textContent = 'Opens and closes with the garage door device placed on it.'; section.append(hint);
  }
  drawOpeningModelSlot(section, record, { canEdit, queue, op, report, getRecord, getKit, library, ownSlot });
}

// Single and set Properties share the same Library acceptance/reveal path.
// The set card supplies one assignment that batches all of its per-piece ops.
export function drawOpeningModelSlot(host, record, { canEdit, queue, op, report,
  library = idleLibrary, ownSlot = () => {}, records = [record], assign, getRecord = () => record, getKit = () => ({}) }) {
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
  if (records.length === 1) drawModelParts(host, record, { canEdit, queue, op, report, getRecord, getKit, library, ownSlot });
  return row;
}

// The same rows own hosted objects, yard copies and opening models. Keep the
// part map out of the schema's generic fields; each save reads the latest copy.
function drawModelParts(host, record, { canEdit, queue, op, report, getRecord = () => record, getKit, library, ownSlot }) {
  const asset = (record.kind === 'opening' ? record.piece.model : record.piece.asset)?.replace(/^polyhaven:/, '');
  if (!asset) return;
  let disposed = false, reported = false, model = null, materials = record.piece.model_materials || {}, signature = null;
  const rows = [], section = document.createElement('section');
  const readModel = () => canEdit() ? prepareModelParts(asset, getKit()) : modelRecord(asset);
  const readFailed = error => { if (!disposed && !reported) { reported = true; report(error); } };
  const catalogueChanged = () => { if (!disposed) rows.forEach(row => row.refresh()); };
  document.addEventListener('chf-material-catalogue', catalogueChanged);
  section.setAttribute('aria-label', 'Parts');
  ownSlot({ refresh() {
    materials = getRecord()?.piece.model_materials || {};
    readModel().then(showParts).catch(readFailed);
  }, dispose() { disposed = true; document.removeEventListener('chf-material-catalogue', catalogueChanged); rows.forEach(row => row.dispose()); } });
  function showParts(nextModel) {
    if (disposed) return;
    model = nextModel;
    const nextSignature = JSON.stringify((model.parts || []).map(part => [part.key,part.name,part.has_uv]));
    if (nextSignature === signature) { rows.forEach(row => row.refresh()); return; }
    signature = nextSignature;
    rows.forEach(row => row.dispose()); rows.length = 0; section.replaceChildren();
    if (!model.parts?.length) { section.remove(); return; }
    const heading = document.createElement('h3'); heading.textContent = 'Parts'; section.append(heading); host.append(section);
    const save = (key, value) => queue(async () => {
      if (!canEdit()) return;
      const current = getRecord(); if (!current) return;
      if ((current.kind === 'opening' ? current.piece.model : current.piece.asset)?.replace(/^polyhaven:/, '') !== asset)
        throw new Error('That copy now uses a different model.');
      const next = { ...(current.piece.model_materials || materials) };
      const entry = typeof value === 'function' ? value(next[key]) : value;
      if (entry) next[key] = entry; else delete next[key];
      await op(objectOperation(current, { model_materials:next }));
      materials = next;
    });
    for (const part of model.parts) {
      const ref = () => materials[part.key] || model.materials?.[part.key];
      const original = () => ref()?.material === 'original';
      const ownMaterial = () => !!materials[part.key]?.material && materials[part.key].material !== 'original';
      const label = part.key !== part.name ? part.key : part.name;
      const current = () => !ref() || original() ? { name:label } : { ...describeMaterial({id:ref().material}, getKit()), kind:'material' };
      const row = createSlotRow({ label, subject:`${label} part material`, library,
        readOnly:() => !canEdit(), accepts:entry => entry.kind === 'material', current,
        inherited:() => !materials[part.key],
        detail:() => {
          const provenance = original() ? 'original (this copy)' : materials[part.key] ? current().name
            : model.materials?.[part.key] ? `${current().name}, from the model` : 'original';
          return ownMaterial() || original() ? provenance : `${provenance}; texture is set on the model in the Library`;
        },
        texture:{ value:() => resolvePart(part, model.materials, materials), editable:ownMaterial, hasUv:() => !!part.has_uv,
          setField:(field, value) => save(part.key, entry => {
            if (!entry?.material || entry.material === 'original') throw new Error('Choose a material for this copy before changing its texture.');
            const next = { ...entry, texture:entry.texture || 'real', [field]:value };
            if (next.texture === 'model') next.tiles ??= 1;
            else delete next.tiles;
            return next;
          }) },
        apply:entry => save(part.key, {material:entry.id}),
        clear:{ enabled:() => !!materials[part.key], run:() => save(part.key, null) },
        reset:{label:'Use original',enabled:() => !!ref()?.material && !original(),run:() => save(part.key, {material:'original'})} });
      row.element.dataset.modelPart = part.key;
      section.append(row.element); rows.push(row);
    }
  }
  readModel().then(showParts).catch(readFailed);
}
