import { sitePoints } from '../objects.js';
import { editVertex } from './polygon_handles.js';
import { shapeKey, shapeCentre, shapeSize, transformShape, shapeOperation, closedShape } from './site_shapes.js';
import { roundPit, firePitOptions } from '../fire_pits.js';
import { linkEntityPicker } from './object_shelf.js';
import { pathOutline } from '../path_shapes.js';
import { materialSlot } from './material_slot.js';

const title = word => word[0].toUpperCase() + word.slice(1);
const ROLE_WORDS = { patio_concrete: 'Concrete', paving: 'Pavers', base: 'Stone', fence: 'Wood', mulch: 'Mulch', granite: 'Granite', lawn: 'Grass' };
// The parts of each yard feature that take a Library material, with the look each part has
// by default (user, 2026-11-13: every feature gets a material slot).
export function siteMaterialSlots(kind, piece) {
  const role = piece.material === 'concrete' ? 'patio_concrete' : piece.material;
  if (kind === 'fire_pit') {
    const top = piece.top ?? (piece.fuel === 'gas' ? 'granite' : 'none');
    return [['body', 'Body', title(piece.body || 'stone')], ...(top === 'none' ? [] : [['top', 'Top', title(top)]])];
  }
  if (kind === 'hardscape') return [['surface', 'Surface', ROLE_WORDS[role || 'paving'] || title(role)],
    ...(piece.kind === 'path' && piece.edging === 'curb' ? [['edging', 'Curb', 'Concrete']] : [])];
  if (kind === 'beds') return [['fill', 'Fill', ROLE_WORDS[role || 'mulch'] || title(role)]];
  if (kind === 'fence') return [['boards', 'Boards', 'Wood'], ['posts', 'Posts', 'Wood'], ['rails', 'Rails', 'Wood']];
  return [];
}

// Uses the object shelf's labels, number inputs and Advanced disclosure.
export function drawSiteShapeShelf(host, record, { canEdit, queue, op, report, getRecord = () => record, onSaved = () => {}, haAvailable = false, onMakeRoom = () => {}, getKit = () => ({}) }) {
  const section = document.createElement('section'); section.setAttribute('aria-label', 'Yard shape properties'); host.append(section);
  const advanced = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = 'Advanced'; advanced.append(summary);
  const save = change => queue(async () => {
    if (!canEdit()) return;
    const current = getRecord(); if (!current) return;
    await op(shapeOperation(current, typeof change === 'function' ? change(current.piece) : change));
  }).catch(report).finally(onSaved);
  function field(text, value, change, parent = section, numeric = true, allowEmpty = false) {
    const label = document.createElement('label'); label.textContent = text;
    const input = document.createElement('input'); input.type = numeric ? 'number' : 'text'; input.step = 'any'; input.value = value; input.disabled = !canEdit(); input.setAttribute('aria-label', text);
    input.addEventListener('change', () => {
      if (!canEdit()) return;
      if (!allowEmpty && !input.value.trim() || numeric && !Number.isFinite(Number(input.value))) { report(new Error('Use a finite number.')); onSaved(); return; }
      save(p => change(p, numeric ? Number(input.value) : input.value));
    });
    label.append(input); parent.append(label); return input;
  }
  function choice(text, value, values, change) {
    const label = document.createElement('label'); label.textContent = text;
    const input = document.createElement('select'); input.setAttribute('aria-label', text); input.disabled = !canEdit();
    for (const [id, title] of values) { const option = document.createElement('option'); option.value = id; option.textContent = title; option.disabled = id === ''; input.append(option); }
    input.value = value; input.addEventListener('change', () => { if (canEdit()) save(change(input.value)); });
    label.append(input); section.append(label);
  }
  const { piece, kind } = record, centre = shapeCentre(piece), size = shapeSize(piece);
  const path = piece.kind === 'path';
  if (kind === 'yard_rooms') {
    const name = field('Name', piece.name, (_, name) => ({ name: name.trim() }), section, false);
    name.maxLength = 40; name.minLength = 1;
    if (!haAvailable) field('Home Assistant area', piece.ha_area || '', (_, ha_area) => ({ ha_area: ha_area.trim() || null }), section, false, true);
  }
  if (['pool', 'hardscape', 'beds', 'fire_pit'].includes(kind) && (piece.polygon || path || kind === 'fire_pit')) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Make this a room'; button.disabled = !canEdit();
    button.addEventListener('click', () => queue(async () => {
      if (!canEdit()) return;
      const current = getRecord(); if (!current) return;
      await op(current.piece.kind === 'path'
        ? { op: 'add_site_shape', list: 'yard_rooms', name: (current.piece.name || 'Path').slice(0, 40), polygon: pathOutline(current.piece) }
        : { op: 'make_yard_room', list: current.kind, id: current.piece.id });
      onMakeRoom();
    }).catch(report));
    section.append(button);
  }
  if (kind === 'fire_pit') {
    const gas = piece.fuel === 'gas';
    const legacy = !firePitOptions(piece).detailed;
    choice('Fuel', legacy ? '' : piece.fuel || 'wood', [...(legacy ? [['', 'Wood (original ring)']] : []), ['wood', 'Wood'], ['gas', 'Gas']], fuel => ({fuel}));
    choice('Body', piece.body || 'stone', [['stone', 'Stone'], ['brick', 'Brick'], ['concrete', 'Concrete']], body => ({body}));
    choice('Top', piece.top ?? (gas ? 'granite' : 'none'), [['none', 'None'], ['granite', 'Granite'], ['concrete', 'Concrete']], top => ({top}));
    const height = field('Height (in)', piece.height_in ?? (gas ? 18 : 16.8), (_, height_in) => ({height_in})); height.min = '6'; height.max = '30';
    if (gas) choice('Fire glass colour', piece.glass || 'amber', [['amber', 'Amber'], ['blue', 'Blue'], ['clear', 'Clear']], glass => ({glass}));
    const entity = field('Linked switch', piece.entity || '', (_, entity) => ({entity: entity.trim() || null}), section, false, true);
    linkEntityPicker(entity);
  }
  if (['beds', 'hardscape', 'edges', 'pool'].includes(kind)) choice('Material', piece.material === 'concrete' ? 'patio_concrete' : piece.material || (kind === 'beds' ? 'mulch' : kind === 'edges' ? 'lawn' : 'paving'),
    [['mulch', 'Mulch'], ['patio_concrete', 'Concrete'], ['paving', 'Pavers'], ['lawn', 'Grass'], ['base', 'Stone'], ['fence', 'Wood']], material => ({ material }));
  // One op per change: { materials: { part: slot or null } } (null is the default look).
  for (const [part, label, defaultLabel] of siteMaterialSlots(kind, piece)) section.append(materialSlot({
    label, value: piece.materials?.[part] || null, defaultLabel, kit: getKit(), readOnly: () => !canEdit(), report,
    onChange: slot => queue(async () => {
      const current = getRecord(); if (!current) return;
      await op(shapeOperation(current, { materials: { [part]: slot } }));
    }).finally(onSaved) }));
  if (path) {
    const width = field('Width (ft)', piece.width ?? 3, (_, width) => ({ width })); width.min = '1'; width.max = '30';
    choice('Corner style', piece.corner || 'mitred', [['mitred', 'Mitred'], ['rounded', 'Rounded']], corner => ({ corner }));
    field('Corner radius (ft)', piece.radius ?? piece.width ?? 3, (_, radius) => ({ radius }));
    choice('Smooth curve', piece.smooth ? 'yes' : 'no', [['no', 'No'], ['yes', 'Yes']], smooth => ({ smooth: smooth === 'yes' }));
    choice('Edging', piece.edging || 'none', [['none', 'None'], ['curb', 'Curb (0.25 ft high, 0.5 ft wide)']], edging => ({ edging }));
  }
  for (const [i, axis] of ['X', 'Y'].entries()) field(`Centre ${axis} (ft)`, centre[i], (p, v) => transformShape(p, { centre: shapeCentre(p).map((n, j) => j === i ? v : n) }));
  if (kind === 'fire_pit' && roundPit(piece)) {
    field('Radius (ft)', piece.radius ?? 2, (_, radius) => ({ radius }));
    field('Angle (degrees)', piece.rotation || 0, (p, rotation) => transformShape(p, { rotation }));
  }
  else {
    if (kind !== 'fence') {
      field('Angle (degrees)', piece.rotation || 0, (p, rotation) => transformShape(p, { rotation }));
      field('Size (%)', 100, (p, percent) => {
        if (!(percent > 0)) throw new Error('Use a positive size.');
        return transformShape(p, { scale: [percent / 100, percent / 100] });
      });
    }
    for (const [i, title] of (path ? ['Centre line X span (ft)', 'Centre line Y span (ft)'] : ['Width (ft)', 'Depth (ft)']).entries()) field(title, size[i], (p, v) => {
      const current = shapeSize(p)[i];
      if (!(v > 0 && current > 0)) throw new Error('Use a positive size on an axis with a nonzero span.');
      return transformShape(p, { scale: [0, 1].map(j => j === i ? v / current : 1) });
    });
    for (const [i, axis] of ['X', 'Y'].entries()) field(`${axis} scale (%)`, 100, (p, v) => {
      if (!(v > 0)) throw new Error('Use a positive scale.');
      return transformShape(p, { scale: [0, 1].map(j => j === i ? v / 100 : 1) });
    }, advanced);
    const note = document.createElement('p'); note.textContent = 'Drag corners to reshape. Drag or tap + to add a corner. Alt-click a corner to remove it. Turn snaps to 15 degrees; hold Shift for free turn.'; section.append(note);
    sitePoints(piece).forEach((point, index) => {
      for (const [axis, text] of ['X', 'Y'].entries()) field(`Point ${index + 1} ${text} (ft)`, point[axis], (p, v) => ({ [shapeKey(p)]: editVertex(sitePoints(p), { index }, sitePoints(p)[index].map((n, i) => i === axis ? v : n)) }), advanced);
      const button = document.createElement('button'); button.type = 'button'; button.textContent = `Remove corner ${index + 1}`;
      button.disabled = !canEdit() || sitePoints(piece).length <= (closedShape(record) ? 3 : 2);
      button.addEventListener('click', () => save(p => ({ [shapeKey(p)]: editVertex(sitePoints(p), { index }, point, { remove: true, closed: closedShape(record) }) }))); advanced.append(button);
    });
  }
  if (kind === 'pool') {
    field('Pool depth (ft)', piece.depth ?? 5, (_, depth) => ({ depth }));
    field('Coping (ft)', piece.coping ?? 1, (_, coping) => ({ coping }));
  }
  if (kind === 'fence') {
    const height = field('Height (ft)', piece.height ?? 6, (_, height) => ({ height })); height.min = '2'; height.max = '10';
    if ('style' in piece) field('Style', piece.style, (_, style) => ({ style }), section, false);
  }
  section.append(advanced);
}
