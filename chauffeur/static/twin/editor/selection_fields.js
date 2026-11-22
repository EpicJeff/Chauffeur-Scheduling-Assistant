import { findPiece } from './piece_operations.js';
import { schema, propertyFields, objectOperation, siteShapeKinds, sitePieces } from '../objects.js';
import { shapeCentre, shapeSize, transformShape, shapeOperation } from './site_shapes.js';
import { paverSettings, PAVER_DEFAULTS } from '../paver_layout.js';
import { firePitOptions, roundPit } from '../fire_pits.js';
import { EFFECT_TYPES } from '../effects/driver.js';
import { porchFoundation } from '../twin_porch_foundation.js';
import { facingOptions } from './line_fixture_tool.js';
import { facingNormal } from '../live/fixture_geometry.js';

// Shared with the ordinary Properties card: set fields accept the same units.
export function feetInches(value) {
  const inches = Math.round(Math.abs(value) * 12);
  return `${value < 0 ? '-' : ''}${Math.floor(inches / 12)}'-${inches % 12}"`;
}
export function parseLength(text) {
  text = String(text).trim().replace(/[′’]/g, "'").replace(/[″“”]/g, '"');
  const decimal = '(?:\\d+(?:\\.\\d*)?|\\.\\d+)';
  const match = text.match(new RegExp(`^(-?)(${decimal})\\s*(?:'|ft|feet|foot)\\s*-?\\s*(?:(${decimal})\\s*(?:"|in|inches|inch)?)?$`, 'i'));
  const simple = text.match(new RegExp(`^(-?${decimal})\\s*("|in|inches|inch)?$`, 'i'));
  const value = match ? (match[1] ? -1 : 1) * (Number(match[2]) + Number(match[3] || 0) / 12)
    : simple ? Number(simple[1]) / (simple[2] ? 12 : 1) : NaN;
  if (!text || !Number.isFinite(value)) throw new Error('Use feet and inches, such as 11\'-0", or a number of feet.');
  return value;
}

const ordinaryFields = {
  wall: ['length', 'height', 'thickness', 'exterior'], opening: ['width', 'sill', 'head', 'kind', 'panels', 'at'],
  room: ['name', 'kind', 'floor_offset_ft'], roof: ['kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side'],
  building: ['name', 'position', 'rotation', 'base'], level: ['name', 'elevation', 'ceiling'],
  anchor: ['offset'], item: ['rotation', 'scale', 'offset'],
};
const lengths = new Set(['length', 'height', 'thickness', 'width', 'sill', 'head', 'at', 'plate', 'overhang', 'base', 'elevation', 'ceiling', 'offset', 'floor_offset_ft']);
const labels = { low_side: 'Low side', at: 'Distance along the wall', ridge: 'Ridge', sill: 'Height above floor',
  head: 'Top of opening', plate: 'Wall height under the roof', base: 'Height above ground', elevation: 'Height above ground',
  offset: 'Distance from surface', floor_offset_ft: 'Floor height (relative to this floor)' };
const objectLabels = { rotation: 'Yaw (degrees)', pitch: 'Pitch (degrees)', roll: 'Roll (degrees)', scale: 'Scale (factor)',
  scale_axes: 'X, Y, Z scale', mirror_x: 'Mirror left-right', mirror_y: 'Mirror front-back', casts_shadow: 'Casts shadow',
  visible_in: 'Visible in', tint: 'Material tint', elevation: 'Height above surface (ft)', emissive: 'Emissive',
  emissive_color: 'Glow colour', light_entity: 'Linked HA light (optional)', object_kind: 'Object kind' };
const choiceNames = { room: 'Room', porch: 'Porch', x: 'Left to right', y: 'Front to back', x0: 'Left', x1: 'Right', y0: 'Front', y1: 'Back',
  hip: 'Hip', gable: 'Gable', clip: 'Clipped gable', shed: 'One slope', flat: 'Flat', window: 'Window', door: 'Door',
  slider: 'Sliding door', bifold: 'Folding door', passage: 'Open passage', garage: 'Garage door' };
const title = value => value[0].toUpperCase() + value.slice(1);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const numeric = input => {
  if (!String(input).trim() || !Number.isFinite(Number(input))) throw new Error('Use a finite number.');
  return Number(input);
};
const bounded = (input, min = -1e5, max = 1e5) => {
  const value = numeric(input);
  if (value < min || value > max) throw new Error(`Choose a number from ${min} to ${max}.`);
  return value;
};
const choice = values => values.map(value => Array.isArray(value) ? { value: value[0], label: value[1] } : { value, label: choiceNames[value] || title(String(value)) });

function recordFor(plan, ref, lookup) {
  const id = ref.pieceId ?? ref.id, bid = ref.buildingId ?? ref.building;
  if (['light_fixture', 'effect_fixture'].includes(ref.kind)) {
    const effect = ref.kind === 'effect_fixture';
    const entity_id = ref.entity_id || Object.keys(plan.light_fixtures || {}).find(entity => plan.light_fixtures[entity].some(piece => piece.id === id));
    const piece = (effect ? plan.effect_fixtures : plan.light_fixtures?.[entity_id])?.find(piece => piece.id === id);
    return piece && { kind: ref.kind, piece, entity_id };
  }
  if (ref.kind === 'terraces') {
    const index = sitePieces(plan.site?.terraces).findIndex(piece => piece.id === id);
    return index >= 0 ? { kind: 'terraces', index, piece: sitePieces(plan.site.terraces)[index] } : null;
  }
  return lookup ? lookup(id, bid) : findPiece(plan, id, bid);
}

// Returns data and existing per-piece operations; the card submits this entire
// array to applyBatch once. No selected member or plan record is mutated here.
export function selectionFields(plan, refs, { getModel = () => null, getFieldLabels = () => ({}), lookup } = {}) {
  if (!refs?.length || new Set(refs.map(ref => ref.kind)).size !== 1) return [];
  const records = refs.map(ref => recordFor(plan, ref, lookup));
  if (records.some(record => !record) || new Set(records.map(record => record.kind)).size !== 1) return [];
  const rows = records.map(record => fieldsFor(record));
  const result = [];
  for (const [key, first] of rows[0]) {
    if (!rows.every(row => row.has(key))) continue;
    const members = rows.map(row => row.get(key));
    if (members.some(member => member.type !== first.type)) continue;
    let choices = first.choices;
    if (choices) {
      choices = choices.filter(option => members.every(member => member.choices?.some(other => same(other.value, option.value))));
      if (!choices.length) continue;
    }
    const value = first.value, mixed = members.some(member => !same(member.value, value));
    result.push({ ...first, key, value, mixed, choices, display: mixed ? 'Mixed' : first.format(value),
      operations: next => {
        const changed = members.filter(member => !same(member.value, next));
        if (!changed.some(member => member.asyncOperation)) return changed.flatMap(member => member.operation(next));
        return (async () => {
          const ops = [], shared = {};
          for (const member of changed) ops.push(...[await member.operation(next, shared)].flat());
          return ops;
        })();
      } });
  }
  return result;

  function fieldsFor(record) {
    const { piece, kind, building } = record, rows = new Map();
    function add(key, label, value, operation, options = {}) {
      const type = options.type || 'number';
      rows.set(key, { key, label, type, value, format: options.format || (v => Array.isArray(v) ? v.join(', ') : String(v ?? '')),
        parse: options.parse || (type === 'number' ? numeric : type === 'checkbox' ? v => !!v : v => String(v)),
        choices: options.choices ? choice(options.choices) : undefined, operation, ...options,
        ...(options.choices ? { choices: choice(options.choices) } : {}) });
    }
    function set(field, value) {
      const owner = getModel()?.buildings?.find(row => row.id === building.id);
      const modern = ['anchor', 'item'].includes(kind) || ['walls', 'openings', 'rooms', 'levels', 'roofs', 'dormers'].some(list => owner?.[list]?.some(row => row.id === piece.id));
      return { op: 'set', building: building.id, [modern ? 'id' : 'piece']: piece.id, field, value };
    }
    const hosted = ['item', 'anchor'].includes(kind);
    const effectiveKind = kind === 'dormer' && piece.rect ? 'roof' : kind;
    const ordinary = effectiveKind === 'roof' && building.roofs?.some(roof => roof.id === piece.id) && !piece.rect ? [] : ordinaryFields[effectiveKind] || [];
    for (const field of ordinary) {
      if (field === 'length' && !piece.joints?.[1]) continue;
      const value = field === 'length' ? Math.hypot(...piece.to.map((n, i) => n - piece.from[i]))
        : field === 'kind' && kind === 'room' ? piece.kind || 'room' : hosted && ['rotation', 'scale'].includes(field) ? piece[field] ?? (field === 'scale' ? 1 : 0) : piece[field] ?? (field === 'floor_offset_ft' ? 0 : '');
      const choices = field === 'kind' ? (kind === 'room' ? ['room', 'porch'] : effectiveKind === 'roof' ? ['hip', 'gable', 'shed', 'flat'] : ['window', 'door', 'slider', 'bifold', 'passage', 'garage'])
        : field === 'ridge' ? ['x', 'y'] : field === 'low_side' ? ['x0', 'x1', 'y0', 'y1'] : null;
      const label = kind === 'room' && field === 'kind' ? 'Type' : field === 'base' && kind === 'building' ? 'Fixed base above lot datum'
        : hosted && ({ rotation: 'Turn', scale: 'Size' })[field] || getFieldLabels()[field] || labels[field] || title(field);
      const parse = field === 'exterior' ? v => !!v : lengths.has(field) ? parseLength
        : field === 'position' ? input => { const value = String(input).split(',').map(parseLength); if (value.length !== 2) throw new Error('Use two distances, separated by a comma.'); return value; }
          : ['pitch', 'rotation', 'panels', 'scale'].includes(field) ? input => {
            let value = numeric(String(input).replace(/[°%]/g, ''));
            if (field === 'scale') value /= 100;
            if (field === 'panels' && (!Number.isInteger(value) || value < 1)) throw new Error('Use a whole number of panels, at least 1.');
            return value;
          } : String;
      const format = hosted && ['rotation', 'scale'].includes(field) ? v => String(field === 'scale' ? Math.round(v * 100) : Math.round(v * 100) / 100)
        : lengths.has(field) ? v => feetInches(v || 0) : field === 'position' ? v => (v || [0, 0]).map(feetInches).join(', ') : v => String(v ?? '');
      add(field, label, value, next => {
        if (field === 'length') {
          if (!(next > 0 && value > 0)) throw new Error('Use a positive length for a wall with two ends.');
          return { op: 'move_joint', building: building.id, joint: piece.joints[1], to: piece.from.map((n, i) => n + (piece.to[i] - n) * next / value) };
        }
        if (kind === 'room' && field === 'kind') return { op: 'set_room_kind', building: building.id, room: piece.id, kind: next };
        if (hosted && field === 'offset') return { op: 'move_hosted', building: building.id, id: piece.id, offset: next };
        return set(field, next);
      }, { type: choices ? 'select' : field === 'exterior' ? 'checkbox' : 'text', choices, parse, format });
    }
    if (effectiveKind === 'roof' && ['hip', 'gable'].includes(piece.kind)) for (const end of [`${piece.ridge}0`, `${piece.ridge}1`]) {
      add(`ends.${end}`, ({ x0: 'Left end', x1: 'Right end', y0: 'Front end', y1: 'Back end' })[end], piece.ends?.[end] ?? piece.kind,
        next => set('ends', { ...piece.ends, [end]: next }), { type: 'select', choices: ['gable', 'hip', 'clip'] });
    }
    const object = ['planting', 'furniture', 'item'].includes(kind) || kind === 'anchor' && !piece.device;
    if ((object || kind === 'opening') && schema()) {
      const s = schema();
      const specs = kind === 'opening' ? s.opening : { object_kind: { type: 'choice', choices: Object.keys(s.kinds), default: kind === 'planting' ? 'plant' : 'furniture' }, ...propertyFields(piece, kind) };
      for (const [field, spec] of Object.entries(specs)) {
        if (spec.free && piece.host || spec.kind && spec.kind !== piece.kind || field === 'model' || kind === 'item' && ['scale', 'rotation'].includes(field)) continue;
        const parse = spec.type === 'boolean' ? v => !!v : ['number', 'angle'].includes(spec.type) ? numeric
          : spec.type === 'axes' ? input => String(input).split(',').map(numeric)
            : spec.type === 'visibility' ? input => String(input).split(',').map(value => value.trim()).filter(Boolean)
              : ['color', 'light'].includes(spec.type) ? input => String(input) || null : String;
        add(field, spec.label || objectLabels[field] || title(field), piece[field] ?? spec.default,
          next => objectOperation(record, { [field]: next }), { type: spec.type === 'choice' ? 'select' : spec.type === 'boolean' ? 'checkbox' : ['number', 'angle'].includes(spec.type) ? 'number' : 'text',
            choices: spec.choices?.map(value => [value, spec.labels?.[value] || value]), parse });
      }
      if (kind !== 'opening') {
        const coordinates = piece.host ? Object.keys(piece.host).filter(key => typeof piece.host[key] === 'number') : ['x', 'y'];
        coordinates.forEach((coordinate, index) => add(`position.${coordinate}`, piece.host ? ({ u: 'Across room (%)', v: 'Along room (%)', at: 'Along surface (ft)', z: 'Height on surface (ft)', edge: 'Roof edge' })[coordinate] || coordinate : `Position ${coordinate} (ft)`,
          piece.host ? piece.host[coordinate] * (['u', 'v'].includes(coordinate) ? 100 : 1) : piece.at[index],
          next => piece.host ? { op: 'move_hosted', building: building.id, id: piece.id, host: { ...piece.host, [coordinate]: next / (['u', 'v'].includes(coordinate) ? 100 : 1) } }
            : { op: 'move_site_item', list: kind, index: record.index, at: piece.at.map((value, i) => i === index ? next : value) }));
      }
    }
    if (kind === 'room' && piece.kind === 'porch') {
      const foundation = porchFoundation(piece.foundation);
      for (const [field, label, choices, range] of [['type', 'Foundation', ['posts', 'enclosed', 'solid']],
        ['post_in', 'Post width (in)', null, [4, 16]], ['post_shape', 'Post shape', ['square', 'round']],
        ['spacing_ft', 'Post spacing (ft)', null, [4, 12]], ['lip_in', 'Floor overhang (in)', null, [0, 4]]]) {
        add(`foundation.${field}`, label, foundation[field], value => {
          const next = { ...porchFoundation(piece.foundation), [field]: value };
          delete next.material;
          return { op: 'set_porch_foundation', building: building.id, id: piece.id, foundation: next };
        }, { type: choices ? 'select' : 'number', choices, parse: choices ? String : value => bounded(value, ...range) });
      }
    }
    if (kind === 'anchor' && ['charger', 'parking'].includes(piece.kind)) {
      const fields = piece.kind === 'charger' ? [['name', 'Name'], ['power', 'Power entity'], ['car', 'Dedicated car (optional)']]
        : [['car', 'Assigned car (optional)'], ['width', 'Width'], ['depth', 'Length'], ['rotation', 'Turn (degrees)']];
      for (const [field, label] of fields) {
        const dimension = ['width', 'depth'].includes(field), picker = ['power', 'car'].includes(field);
        add(field, label, piece[field] ?? (dimension ? field === 'width' ? 9 : 18 : field === 'rotation' ? 0 : picker ? null : ''),
          value => ({ op: 'set', building: building.id, id: piece.id, field, value }),
          { type: 'text', format: value => dimension ? feetInches(value) : String(value ?? ''), parse: value => {
            if (picker) return String(value) || null;
            if (field === 'rotation') return numeric(String(value).replace(/°/g, ''));
            if (dimension) { const next = parseLength(value); if (!(next > 0)) throw new Error('Use a size greater than zero.'); return next; }
            const next = String(value).trim(); if (!next) throw new Error('Give the charger a name.'); return next;
          } });
      }
    }
    if (kind === 'solar_zone') {
      for (const [field, label] of [['rect', 'Zone rectangle (u, v, u2, v2 in feet)'], ['panel_width', 'Panel width'], ['panel_height', 'Panel height'],
        ['orientation', 'Orientation'], ['gap', 'Gap'], ['setback', 'Setback'], ['count', 'Panel count (empty fills zone)'], ['entity', 'Production sensor (optional)']]) {
        const dimension = ['panel_width', 'panel_height', 'gap', 'setback'].includes(field);
        add(field, label, piece[field] ?? (['count', 'entity'].includes(field) ? null : ''), value => ({ op: 'update_solar_zone', building: building.id, id: piece.id, [field]: value }),
          { type: field === 'orientation' ? 'select' : 'text', choices: field === 'orientation' ? ['portrait', 'landscape'] : null,
            format: value => field === 'rect' ? value.join(', ') : dimension ? feetInches(value) : String(value ?? ''),
            parse: value => field === 'rect' ? String(value).split(',').map(parseLength) : dimension ? parseLength(value)
              : field === 'count' ? String(value).trim() ? numeric(value) : null : String(value) || null });
      }
    }
    if (kind === 'stair') {
      const from = building.levels.find(level => level.id === piece.level);
      const targets = building.levels.filter(level => level.elevation > from.elevation).sort((a, b) => a.elevation - b.elevation);
      for (const [field, label, value, choices] of [['width', 'Width (ft)', piece.width ?? 3, null],
        ['to_level', 'To level', piece.to_level || targets.find(level => level.elevation === piece.rise_to)?.id || '', targets.map(level => [level.id, level.name || level.id])],
        ['style', 'Style', piece.style || 'solid', ['solid', 'open']], ['rail', 'Rails', piece.rail || 'none', ['none', 'left', 'right', 'both']]]) {
        add(field, label, value, next => ({ op: 'update_stair', building: building.id, id: piece.id, [field]: next }),
          { type: choices ? 'select' : 'number', choices, parse: choices ? String : value => bounded(value, 2, 8) });
      }
    }
    if (siteShapeKinds.includes(kind) || ['ledge', 'steps', 'spa', 'terraces'].includes(kind)) shapeFields(record, add);
    if (['light_fixture', 'effect_fixture'].includes(kind)) fixtureFields(record, add);
    return rows;
  }
}

function shapeFields(record, add) {
  const { piece: p, kind } = record;
  const save = change => kind === 'terraces' ? { op: 'update_pad', id: p.id, ...change } : shapeOperation(record, change);
  const field = (key, label, value, change = value => ({ [key]: value }), options = {}) => add(key, label, value, value => save(change(value)), options);
  const select = (key, label, value, choices, change) => field(key, label, value, change, { type: 'select', choices });
  if (kind === 'yard_rooms') { field('name', 'Name', p.name, value => ({ name: value.trim() }), { type: 'text' }); }
  const centre = shapeCentre(p), size = shapeSize(p);
  for (const [i, axis] of ['X', 'Y'].entries()) field(`centre.${i}`, `Centre ${axis} (ft)`, centre[i], value => transformShape(p, { centre: centre.map((v, j) => j === i ? value : v) }));
  if (!['fence', 'ledge', 'steps', 'spa'].includes(kind)) field('rotation', 'Angle (degrees)', p.rotation || 0, rotation => transformShape(p, { rotation }));
  if (kind === 'fire_pit' && roundPit(p)) field('radius', 'Radius (ft)', p.radius ?? 2);
  else for (const [i, name] of (p.kind === 'path' ? ['Centre line X span (ft)', 'Centre line Y span (ft)'] : ['Width (ft)', 'Depth (ft)']).entries()) field(`size.${i}`, name, size[i], value => {
    if (!(value > 0 && size[i] > 0)) throw new Error('Use a positive size on an axis with a nonzero span.');
    return transformShape(p, { scale: [0, 1].map(j => j === i ? value / size[i] : 1) });
  });
  if (kind === 'terraces') { field('height', 'Height (ft)', p.height || 0); return; }
  if (['beds', 'hardscape', 'edges', 'pool'].includes(kind)) select('material', 'Material', p.material === 'concrete' ? 'patio_concrete' : p.material || ({ beds: 'mulch', edges: 'lawn' })[kind] || 'paving',
    [['mulch', 'Mulch'], ['patio_concrete', 'Concrete'], ['paving', 'Pavers'], ['lawn', 'Grass'], ['base', 'Stone'], ['fence', 'Wood']]);
  if (kind === 'fire_pit') {
    if (firePitOptions(p).detailed) select('fuel', 'Fuel', p.fuel || 'wood', [['wood', 'Wood'], ['gas', 'Gas']]);
    select('body', 'Body', p.body || 'stone', [['stone', 'Stone'], ['brick', 'Brick'], ['concrete', 'Concrete']]);
    select('top', 'Top', p.top ?? (p.fuel === 'gas' ? 'granite' : 'none'), [['none', 'None'], ['granite', 'Granite'], ['concrete', 'Concrete']]);
    field('height_in', 'Height (in)', p.height_in ?? (p.fuel === 'gas' ? 18 : 16.8));
    if (p.fuel === 'gas') select('glass', 'Fire glass colour', p.glass || 'amber', [['amber', 'Amber'], ['blue', 'Blue'], ['clear', 'Clear']]);
    field('entity', 'Linked switch', p.entity || '', value => ({ entity: value.trim() || null }), { type: 'text' });
  }
  if (p.kind === 'path') {
    const pavers = paverSettings(p);
    select('pavers', 'Surface', pavers ? 'pavers' : 'solid', [['solid', 'Solid'], ['pavers', 'Pavers']], value => ({ pavers: value === 'pavers' ? { ...PAVER_DEFAULTS } : null }));
    if (pavers) {
      const change = (key, value) => ({ pavers: { ...PAVER_DEFAULTS, ...p.pavers, [key]: value } });
      for (const [key, label, choices] of [ ['layout', 'Layout', ['stepping', 'grid', 'running_bond', 'diagonal', 'herringbone']], ['edge', 'Edges', [['whole', 'Whole pavers only'], ['cut', 'Cut at the edge']]], ['joint', 'Joints', ['grass', 'gravel', 'sand', 'none']], ['lay', 'Lay', [['ground', 'Follow the ground'], ['level', 'Level']]] ]) select(`pavers.${key}`, label, pavers[key], choices, value => change(key, value));
      for (const [key, label] of [['length_in', 'Paver length (in)'], ['width_in', 'Paver width (in)'], ['gap_in', 'Gap (in)'], ['rotation', 'Rotation (degrees)']]) field(`pavers.${key}`, label, pavers[key], value => change(key, value));
    }
    field('width', 'Width (ft)', p.width ?? 3);
    select('corner', 'Corner style', p.corner || 'mitred', ['mitred', 'rounded']);
    field('radius', 'Corner radius (ft)', p.radius ?? p.width ?? 3);
    select('smooth', 'Smooth curve', p.smooth ? 'yes' : 'no', [['no', 'No'], ['yes', 'Yes']], value => ({ smooth: value === 'yes' }));
    select('edging', 'Edging', p.edging || 'none', [['none', 'None'], ['curb', 'Curb (0.25 ft high, 0.5 ft wide)']]);
  }
  if (kind === 'pool') { field('depth', 'Pool depth (ft)', p.depth ?? 5); field('coping', 'Coping (ft)', p.coping ?? 1); }
  if (['ledge', 'spa'].includes(kind)) field('depth_in', 'Water depth (in)', p.depth_in ?? (kind === 'ledge' ? 10 : 36));
  if (kind === 'steps') {
    field('treads', 'Treads', p.treads ?? 3);
    add('entry_edge', 'Entry edge', p.entry_edge ?? 0, value => save({ entry_edge: value }),
      { type: 'select', choices: p.polygon.map((_, i) => [String(i), `Edge ${i + 1}`]), parse: numeric });
  }
  if (kind === 'spa') {
    field('bench_in', 'Bench seat depth (in)', p.bench_in ?? 18); field('bench_width_in', 'Bench width (in)', p.bench_width_in ?? 18);
    select('mode', 'Mode', p.mode ?? 'raised', ['raised', 'flush']);
    if ((p.mode ?? 'raised') === 'raised') field('raise_in', 'Raise above deck (in)', p.raise_in ?? 12);
    select('spillover', 'Spillover', (p.spillover ?? true) ? 'yes' : 'no', [['yes', 'Yes'], ['no', 'No']], value => ({ spillover: value === 'yes' }));
  }
  if (kind === 'fence') { select('type', 'Fence type', p.type || 'plank', [['plank', 'Wood plank'], ['picket', 'Picket'], ['metal', 'Metal picket'], ['panel', 'Panel']]); field('height', 'Height (ft)', p.height ?? 6); if ('style' in p) field('style', 'Style', p.style, undefined, { type: 'text' }); }
}

function fixtureFields(record, add) {
  const { piece: p, kind, entity_id } = record, effect = kind === 'effect_fixture';
  const save = change => ({ op: effect ? 'update_effect_fixture' : 'update_light_fixture', id: p.id, ...(!effect ? { entity_id } : {}), change });
  const field = (key, label, value, min, max, options = {}) => add(key, label, value, value => save({ [key]: value }), { parse: value => bounded(value, min, max), ...options });
  if (p.at) ['East (ft)', 'North (ft)', 'Height (ft)'].forEach((label, i) => add(`at.${i}`, label, p.at[i], value => save({ at: p.at.map((v, j) => i === j ? value : v) })));
  if (['point', 'line'].includes(p.shape)) field('offset_ft', 'Offset (ft)', p.offset_ft ?? 0, -50, 50);
  if (p.shape === 'line') add('facing', 'Facing', p.facing || 'down', facing => save({ facing }),
    { type: 'select', choices: facingOptions(p.snap?.host.kind, p.facing).filter(([value]) => p.snap?.host.kind !== 'step' || value === 'out') });
  if (effect) {
    add('type', 'Type', p.type, value => save({ type: value }), { type: 'select', choices: Object.entries(EFFECT_TYPES)
      .filter(([, row]) => row.shapes.includes(p.shape)).map(([value, row]) => [value, row.label]) });
    field('name', 'Name', p.name || null, undefined, undefined, { type: 'text', parse: value => String(value).trim() || null });
    field('entity', 'Switch', p.entity || null, undefined, undefined, { type: 'text', parse: value => String(value).trim() || null });
    add('sensor', 'Sensor', p.sensor || '', async (sensor, shared) => {
      if (!sensor) return save({ sensor: null, sensor_min: null, sensor_max: null });
      let attribute = p.sensor_attribute;
      const ask = async (key, title, detail, value) => {
        if (!(key in shared)) {
          const answer = await window.promptInput(title, detail, { value });
          if (answer === null || answer === undefined) { const error = new Error('Sensor change cancelled.'); error.cancelled = true; throw error; }
          shared[key] = answer;
        }
        return shared[key];
      };
      if (!/^(sensor|number|input_number)\./.test(sensor) && !attribute) {
        attribute = String(await ask('attribute', 'Sensor attribute', 'Numeric attribute to read, such as current_temperature or percentage.', '')).trim();
        if (!attribute) { const error = new Error('Sensor change cancelled.'); error.cancelled = true; throw error; }
      }
      let { sensor_min, sensor_max } = p;
      if (!Number.isFinite(sensor_min) || !Number.isFinite(sensor_max)) {
        sensor_min = numeric(await ask('minimum', 'Sensor minimum', 'Value at the minimum effect size.', '0'));
        sensor_max = numeric(await ask('maximum', 'Sensor maximum', 'Value at the maximum effect size. A lower value inverts the range.', '100'));
      }
      if (sensor_min === sensor_max) throw new Error('Sensor minimum and maximum must differ.');
      return save({ sensor, sensor_min, sensor_max, ...(attribute ? { sensor_attribute: attribute } : {}) });
    }, { type: 'text', parse: value => String(value).trim(), asyncOperation: true });
    if (p.sensor) {
      field('sensor_attribute', 'Attribute', p.sensor_attribute || null, undefined, undefined, { type: 'text', parse: value => String(value).trim() || null });
      field('sensor_min', 'Sensor min', p.sensor_min); field('sensor_max', 'Sensor max', p.sensor_max);
    }
    field('strength', 'Level (%)', p.strength ?? 1, 0, 1, { format: value => String(value * 100), parse: value => bounded(value, 0, 100) / 100 });
    field('size_min', 'Size at min (ft)', p.size_min ?? EFFECT_TYPES[p.type]?.size_min, 0, 30);
    field('size_max', 'Size at max (ft)', p.size_max ?? EFFECT_TYPES[p.type]?.size_max, 0, 30);
    if (['waterfall', 'sheer'].includes(p.type)) field('drop_ft', 'Drop (ft)', p.drop_ft ?? null, .1, 40, { parse: value => String(value).trim() ? bounded(value, .1, 40) : null });
    return;
  }
  field('share', 'Share', p.share ?? null, 0, 1e6, { parse: value => String(value).trim() ? bounded(value, 0, 1e6) : null });
  if (p.shape === 'spot') {
    ['Aim east (ft)', 'Aim north (ft)', 'Aim height (ft)'].forEach((label, i) => add(`aim.${i}`, label, p.aim[i], value => save({ aim: p.aim.map((v, j) => i === j ? value : v) })));
    field('cone_deg', 'Cone (degrees)', p.cone_deg ?? 90, 10, 160); field('softness', 'Softness', p.softness ?? .3, 0, 1);
  }
  if (p.shape === 'line') field('width_in', 'Width (in)', p.width_in ?? .5, .25, 2);
  if (p.shape === 'area') {
    add('facing', 'Facing', Array.isArray(p.facing) ? 'normal' : p.facing || 'down', value => save({ facing: value === 'normal' ? facingNormal(p.facing) : value }),
      { type: 'select', choices: [['down', 'Down'], ['out', 'Out'], ['up', 'Up'], ['normal', 'Custom normal']] });
    ['Normal east', 'Normal north', 'Normal up'].forEach((label, i) => add(`facing.${i}`, label, facingNormal(p.facing)[i], value => {
      const facing = facingNormal(p.facing); facing[i] = value;
      if (Math.hypot(...facing) <= 1e-8) throw new Error('Choose a nonzero facing normal.');
      return save({ facing });
    }, { parse: value => bounded(value, -1, 1) }));
    ['Width (ft)', 'Height of panel (ft)'].forEach((label, i) => add(`size_ft.${i}`, label, p.size_ft[i], value => save({ size_ft: p.size_ft.map((v, j) => i === j ? value : v) }), { parse: value => bounded(value, .001) }));
    field('rotation_deg', 'Rotation (degrees)', p.rotation_deg ?? 0);
  }
}
