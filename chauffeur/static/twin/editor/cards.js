import { drawObjectShelf, isObject } from './object_shelf.js';
import { solarLayout } from '../twin_solar.js';
import { contains } from '../twin_generator.js';
import { materialLines } from './library.js';
import { createEquipmentShelf } from './equipment_shelf.js';
import { foundationShelf } from './foundation_shelf.js';
import { siteRecord, siteShapeKinds, siteShapeLabels } from '../objects.js';
import { drawSiteShapeShelf } from './site_shape_shelf.js';

const report = error => {
  if (!error.shown && !error.cancelled) window.showGlobalAlert(error.message || 'Could not save this change.');
};

// Keep this list aligned with twin_edit.EDITABLE; the server validates every save.
const fields = {
  wall: ['height', 'thickness', 'exterior'], opening: ['width', 'sill', 'head', 'kind', 'panels', 'at'],
  room: ['name', 'floor_offset_ft'], roof: ['kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side', 'ends'],
  building: ['name', 'position', 'rotation', 'base'], level: ['name', 'elevation', 'ceiling'],
  // Hosted pieces save through model ops (twin_model_ops: set, move_hosted).
  anchor: ['offset'], item: ['rotation', 'scale', 'offset'],
};
const lengths = new Set(['height', 'thickness', 'width', 'sill', 'head', 'at', 'plate', 'overhang', 'base', 'elevation', 'ceiling', 'offset', 'floor_offset_ft']);
const labels = { low_side: 'Low side', at: 'Distance along the wall', ridge: 'Ridge',
  sill: 'Height above floor', head: 'Top of opening', plate: 'Wall height under the roof', base: 'Height above ground', elevation: 'Height above ground',
  offset: 'Distance from surface', floor_offset_ft: 'Floor height (relative to this floor)' };
const hostedLabels = { rotation: 'Turn', scale: 'Size' };
const units = { pitch: 'in 12', rotation: '°', scale: '%' };
export function feetInches(value) {
  const inches = Math.round(Math.abs(value) * 12);
  return `${value < 0 ? '-' : ''}${Math.floor(inches / 12)}'-${inches % 12}"`;
}
export function parseLength(text) {
  text = text.trim().replace(/[′’]/g, "'").replace(/[″“”]/g, '"');
  const decimal = '(?:\\d+(?:\\.\\d*)?|\\.\\d+)';
  const match = text.match(new RegExp(`^(-?)(${decimal})\\s*(?:'|ft|feet|foot)\\s*-?\\s*(?:(${decimal})\\s*(?:"|in|inches|inch)?)?$`, 'i'));
  const simple = text.match(new RegExp(`^(-?${decimal})\\s*("|in|inches|inch)?$`, 'i'));
  const value = match ? (match[1] ? -1 : 1) * (Number(match[2]) + Number(match[3] || 0) / 12)
    : simple ? Number(simple[1]) / (simple[2] ? 12 : 1) : NaN;
  if (!text || !Number.isFinite(value)) throw new Error('Use feet and inches, such as 11\'-0", or a number of feet.');
  return value;
}
export function findPiece(plan, pieceId, buildingId) {
  const site = !buildingId && siteRecord(plan, pieceId);
  if (site) return site;
  const building = plan?.buildings.find(b => b.id === buildingId);
  if (!building) return null;
  if (building.id === pieceId) return { piece: building, building, kind: 'building' };
  for (const [list, kind] of [['solar_zones', 'solar_zone'], ['levels', 'level'], ['walls', 'wall'], ['openings', 'opening'], ['rooms', 'room'], ['stairs', 'stair'], ['anchors', 'anchor'], ['items', 'item'], ['fixtures', 'fixture'], ['lights', 'light']]) {
    const piece = building[list]?.find(p => p.id === pieceId);
    if (piece) return { piece, building, kind };
  }
  const section = building.roof?.sections?.find(p => p.id === pieceId);
  const dormer = building.dormers?.find(p => p.id === pieceId);
  if (dormer) return { piece: section || dormer, building, kind: 'dormer' };
  const piece = section || building.roofs?.find(p => p.id === pieceId);
  if (piece) return { piece, building, kind: 'roof' };
  const proposal = building.proposals?.find(p => (p.id || p.piece.id) === pieceId);
  return proposal ? { piece: { ...proposal.piece, id: proposal.id || proposal.piece.id }, building, kind: 'proposal' } : null;
}

export function createCards({ getPlan, getKit = () => ({}), getLabel, getSelection = () => ({}), getFieldLabels = () => ({}), edit, op, addDormer, ask, canEdit, select, pickMaterial, haLink, preview }) {
  const host = document.getElementById('piece-card');
  let selection = null, pending = Promise.resolve(), inputs = new Map(), headingNode = null, acceptButton = null, pitchNote = null, layout = null;
  let edgeIndex = null;
  let haSection = null;
  const equipmentShelf = createEquipmentShelf({ canEdit, queue, op, report, parseLength, feetInches, onSaved: () => draw() });
  const endNames = { x0: 'Left end', x1: 'Right end', y0: 'Front end', y1: 'Back end' };
  const fieldValue = (piece, field) => field.startsWith('ends.') ? (piece.ends?.[field.slice(5)] ?? piece.kind) : piece[field];
  const title = ({ kind, piece, building }) => {
    const name = kind==='solar_zone'?'Solar zone':kind==='anchor' && ['meter','electric_panel','charger','parking'].includes(piece.kind)?(piece.name || ({meter:'Meter',electric_panel:'Electric panel',charger:'Charger',parking:'Parking spot'}[piece.kind])):kind === 'opening' ? (piece.kind === 'window' ? 'Window' : 'Door')
      : piece.name || piece.preset || siteShapeLabels[kind] || (kind === 'roof' ? 'Roof section' : kind[0].toUpperCase() + kind.slice(1));
    if (!['wall', 'opening'].includes(kind)) return name;
    const wall = kind === 'wall' ? piece : building.walls.find(w => w.id === (piece.wall || piece.host?.wall));
    const room = building.rooms?.find(r => r.id === getSelection().room);
    if (!wall || !room?.polygon?.length) return name;
    const [a, b] = [wall.from, wall.to], length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (!length) return name;
    let nx = (b[1] - a[1]) / length, ny = -(b[0] - a[0]) / length;
    const x = (a[0] + b[0]) / 2 + .25 * nx, y = (a[1] + b[1]) / 2 + .25 * ny;
    if (contains(room.polygon, [x, y])) { nx = -nx; ny = -ny; }
    const angle = (building.rotation || 0) * Math.PI / 180;
    const east = Math.cos(angle) * nx - Math.sin(angle) * ny, north = Math.sin(angle) * nx + Math.cos(angle) * ny;
    const direction = Math.abs(east) >= Math.abs(north) ? east > 0 ? 'east' : 'west' : north > 0 ? 'north' : 'south';
    const wallName = `${room.name || 'Room'}, ${direction} wall`;
    return kind === 'wall' ? wallName : `${name}, ${(room.name || 'Room').toLowerCase()} ${direction} wall`;
  };
  const display = (field, value, kind) => kind && hostedLabels[field]
    ? String(field === 'scale' ? Math.round((value ?? 1) * 100) : Math.round((value ?? 0) * 100) / 100)
    : lengths.has(field) ? feetInches(value || 0)
      : field === 'position' ? (value || [0, 0]).map(feetInches).join(', ') : String(value ?? '');
  const hosted = kind => kind === 'anchor' || kind === 'item';
  const raw = input => input.type === 'checkbox' ? input.checked : input.value;
  const roofFlags = record => record?.kind === 'roof' && record.piece.block && !record.piece.dormer_of
    ? (record.building.roof.flags || []).filter(flag => flag.block_rect?.length === 4
      && flag.block_rect.every((v, i) => Math.abs(v - record.piece.block[i]) <= 1)) : [];
  // The Home Assistant section redraws only when what it shows changes, and
  // never pulls a pick-list out from under a person (ha_link.js draw).
  function drawHaSection(record) {
    if (haSection) haLink.draw(haSection, record);
  }
  function draw(next = selection) {
    if (next?.pieceId !== selection?.pieceId || next?.buildingId !== selection?.buildingId) edgeIndex = null;
    const record = next && findPiece(getPlan(), next.pieceId, next.buildingId);
    if (record?.kind === 'proposal') { host.hidden = true; return; }
    const roof = record?.kind === 'roof' && record.building.roofs?.find(r => r.id === record.piece.id);
    if (roof && edgeIndex !== null) { drawEdge(next, record, roof); return; }
    const materials = record ? materialLines(record, getPlan(), getKit()) : [];
    const flags = roofFlags(record);
    const nextLayout = JSON.stringify([record?.kind === 'building' ? `building:${JSON.stringify(record.piece.foundation)}` : record?.kind === 'roof' ? `${record.piece.kind}:${record.piece.ridge}:${JSON.stringify(flags)}` : record?.kind==='solar_zone'?JSON.stringify(record.piece):record?.kind==='anchor'?`${record.kind}:${record.piece.kind}`:record?.kind, materials, !!pickMaterial, record && siteShapeKinds.includes(record.kind) ? [record.piece, canEdit()] : record && (isObject(record) || record.kind === 'opening') ? record.piece : null]);
    host.hidden = !record;
    // Object properties participate in the layout signature. A completed Size
    // save must not detach Turn while the person is typing the next edit.
    const editingItem = record?.kind === 'item' && [...inputs.values()].some(({ input, baseline, queued }) =>
      document.activeElement === input || queued || raw(input) !== baseline);
    if (record && (layout === nextLayout || editingItem) && selection?.pieceId === next.pieceId && selection?.buildingId === next.buildingId) {
      headingNode.textContent = title(record);
      if (pitchNote) pitchNote.hidden = record.piece.pitch_source !== 'photos';
      if (acceptButton) acceptButton.hidden = record.piece.state !== 'ghost' && !flags.length;
      host.querySelectorAll('button').forEach(b => { b.disabled = !canEdit(); });
      // A save or poll refreshes clean values without replacing anyone's input.
      for (const [field, state] of inputs) {
        const { input } = state;
        if (document.activeElement !== input && raw(input) === state.baseline && !state.queued) {
          if (field === 'exterior') input.checked = !!record.piece[field];
          else input.value = display(field, fieldValue(record.piece, field), hosted(record.kind) && record.kind);
          state.baseline = raw(input);
        }
        input.disabled = !canEdit();
      }
      drawHaSection(record);
      if (kindIsEquipment(record)) equipmentShelf.refresh(record);
      return;
    }
    selection = next; layout = nextLayout; host.replaceChildren(); inputs = new Map(); acceptButton = null; pitchNote = null;
    haSection = null;
    if (!record) return;
    const { piece, kind, building } = record;
    const heading = headingNode = document.createElement('h3'); heading.textContent = title(record);
    const close = button('Close', () => select(null)); close.setAttribute('aria-label', 'Close piece card');
    host.append(heading, close);
    for (const material of materials) {
      const row = document.createElement('div'); row.className = 'editor-material-line';
      const words = document.createElement('div'), label = document.createElement('span'), text = document.createElement('p');
      label.textContent = material.label; text.textContent = material.text; words.append(label, text); row.append(words);
      const actions = document.createElement('div'); actions.className = 'editor-material-actions';
      if (pickMaterial && material.surface) {
        const change = button('Change', () => pickMaterial(material.surface));
        change.setAttribute('aria-label', `Change the ${material.label.toLowerCase()} material`);
        actions.append(change);
      }
      if (material.clear) actions.append(button('Clear', async () => {
        if (canEdit()) await op({ op: 'set_material', building: building.id, target: material.target, material: null });
      }));
      if (material.reset) actions.append(button(material.reset.label, async () => {
        if (canEdit()) await op({ op: 'set_material', building: building.id, target: material.reset.target, material: null });
      }));
      if (actions.children.length) row.append(actions);
      host.append(row);
    }
    if (kind === 'roof') {
      pitchNote = document.createElement('p'); pitchNote.textContent = 'Estimated from photos';
      pitchNote.hidden = piece.pitch_source !== 'photos'; host.append(pitchNote);
      for (const flag of flags) {
        const note = document.createElement('p'); note.textContent = flag.text; host.append(note);
      }
      if (roof && op) {
        roof.edges.forEach((edge, index) => host.append(button(`Edge ${index + 1}: ${edge.setting === 'clip' ? 'Clipped' : edge.setting === 'gable' ? 'Gable' : 'Sloped'}`, () => {
          edgeIndex = index; layout = null; draw();
        })));
        if (addDormer) host.append(button('Add dormer', addDormer));
      }
    }
    if(kind==='roof' || kind==='solar_zone'){
      host.append(button('Solar ribbon starts here',()=>op({op:'set_solar_source',building:building.id,roof:kind==='solar_zone'?piece.roof:piece.roof || piece.id})));
    }
    if(kind==='solar_zone'){
      const total=document.createElement('p');total.textContent=`${solarLayout(piece).length} panels`;host.append(total);
      const saveZone=change=>{pending=pending.then(()=>op({op:'update_solar_zone',building:building.id,id:piece.id,...change})).catch(report);return pending;};
      for(const [field,text] of [['rect','Zone rectangle (u, v, u2, v2 in feet)'],['panel_width','Panel width'],['panel_height','Panel height'],['orientation','Orientation'],['gap','Gap'],['setback','Setback'],['count','Panel count (empty fills zone)'],['entity','Production sensor (optional)']]){
        const label=document.createElement('label');label.textContent=text;
        const input=document.createElement(field==='orientation'?'select':'input');
        if(field==='orientation')for(const value of ['portrait','landscape']){const option=document.createElement('option');option.value=value;option.textContent=value;input.append(option);}
        else input.type='text';
        input.value=field==='rect'?piece.rect.join(', '):['panel_width','panel_height','gap','setback'].includes(field)?feetInches(piece[field]):piece[field] ?? '';
        input.disabled=!canEdit();input.setAttribute('aria-label',text);
        input.addEventListener('change',()=>{if(!canEdit())return;try{
          const value=field==='rect'?input.value.split(',').map(parseLength):['panel_width','panel_height','gap','setback'].includes(field)?parseLength(input.value):field==='count'?(input.value.trim()?Number(input.value):null):input.value || null;
          saveZone({[field]:value}).then(()=>{layout=null;draw();});
        }catch(error){report(error);}});label.append(input);host.append(label);
      }
    }
    if (kindIsEquipment(record)) equipmentShelf.draw(host, record);
    if (kind === 'building') foundationShelf(host, piece, { getPlan, canEdit, queue, op, report, preview });
    if (isObject(record) || kind === 'opening') drawObjectShelf(host, record, { canEdit, queue, op, report,
      getRecord: () => findPiece(getPlan(), piece.id, building?.id) });
    if (siteShapeKinds.includes(kind)) {
      drawSiteShapeShelf(host, record, { canEdit, queue, op, report,
        getRecord: () => findPiece(getPlan(), piece.id, null), onSaved: () => { layout = null; draw(); } });
      const note = document.createElement('p'); note.textContent = 'Drag the move handle or use the arrow keys (one foot).'; host.append(note);
      for (const [axis, text] of ['Move east (ft)', 'Move north (ft)'].entries()) {
        const label = document.createElement('label'); label.textContent = text;
        const input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.value = '0';
        input.disabled = !canEdit(); input.setAttribute('aria-label', text); label.append(input); host.append(label);
        input.addEventListener('change', () => {
          if (!canEdit() || !input.value.trim()) return;
          const amount = Number(input.value);
          if (!Number.isFinite(amount)) { report(new Error('Use a finite number of feet.')); return; }
          queue(() => canEdit() && op({ op: 'move_site_item', list: kind, index: record.index, by: axis ? [0, amount] : [amount, 0] })).catch(report);
        });
      }
    }
    const form = document.createElement('form'); form.addEventListener('submit', event => event.preventDefault()); host.append(form);
    const more = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = 'More'; more.append(summary);
    const cardFields = (kind === 'roof' && roof && !piece.rect ? []
      : fields[kind === 'dormer' && piece.rect ? 'roof' : kind] || []).flatMap(field => field !== 'ends' ? [field]
      : ['gable', 'hip'].includes(piece.kind) ? [`ends.${piece.ridge}0`, `ends.${piece.ridge}1`] : []);
    for (const field of cardFields) {
      const end = field.startsWith('ends.') ? field.slice(5) : null;
      const label = document.createElement('label'); label.textContent = end ? endNames[end]
        : field === 'base' && kind === 'building' ? 'Fixed base above lot datum'
          : hosted(kind) && hostedLabels[field] || getFieldLabels()[field] || labels[field] || field[0].toUpperCase() + field.slice(1);
      let input;
      const choices = field === 'kind' ? (['roof', 'dormer'].includes(kind) ? ['hip', 'gable', 'shed', 'flat'] : ['window', 'door', 'slider', 'bifold', 'passage', 'garage'])
        : end ? ['gable', 'hip', 'clip'] : field === 'ridge' ? ['x', 'y'] : field === 'low_side' ? ['x0', 'x1', 'y0', 'y1'] : null;
      if (choices) {
        input = document.createElement('select');
        choices.forEach(value => {
          const option = document.createElement('option'); option.value = value;
          option.textContent = ({ x: 'Left to right', y: 'Front to back', x0: 'Left', x1: 'Right', y0: 'Front', y1: 'Back',
            hip: 'Hip', gable: 'Gable', clip: 'Clipped gable', shed: 'One slope', flat: 'Flat', window: 'Window', door: 'Door', slider: 'Sliding door',
            bifold: 'Folding door', passage: 'Open passage', garage: 'Garage door' })[value];
          input.append(option);
        });
      } else { input = document.createElement('input'); input.type = field === 'exterior' ? 'checkbox' : 'text'; }
      const initial = fieldValue(piece, field);
      input.value = display(field, initial, hosted(kind) && kind);
      if (field === 'exterior') input.checked = !!initial;
      input.disabled = !canEdit();
      const state = { input, baseline: raw(input), queued: 0, lastQueued: undefined };
      inputs.set(field, state);
      const save = () => {
        if (!canEdit()) return;
        const typed = raw(input);
        if (typed === (state.queued ? state.lastQueued : state.baseline)) return;
        try {
          let value = field === 'exterior' ? input.checked : lengths.has(field) ? parseLength(input.value)
            : field === 'position' ? input.value.split(',').map(parseLength)
              : ['pitch', 'rotation', 'panels', 'scale'].includes(field) ? Number(input.value.replace(/[°%]/g, '')) : input.value;
          if (['pitch', 'rotation', 'panels', 'scale'].includes(field) && (!input.value.trim() || !Number.isFinite(value)))
            throw new Error('Use a finite number.');
          if (field === 'scale') value /= 100;
          if (field === 'panels' && (!Number.isInteger(value) || value < 1)) throw new Error('Use a whole number of panels, at least 1.');
          if (field === 'position' && value.length !== 2) throw new Error('Use two distances, separated by a comma.');
          ++state.queued; state.lastQueued = typed;
          pending = pending.then(async () => {
            const current = findPiece(getPlan(), piece.id, building.id)?.piece;
            const savedField = end ? 'ends' : field;
            const savedValue = end ? { ...current?.ends, [end]: value } : value;
            if (current && hosted(kind)) {
              if (JSON.stringify(current[field] ?? (field === 'scale' ? 1 : 0)) !== JSON.stringify(value))
                await op(field === 'offset' ? { op: 'move_hosted', building: building.id, id: piece.id, offset: value }
                  : { op: 'set', building: building.id, id: piece.id, field, value });
            } else if (current && JSON.stringify(current[savedField]) !== JSON.stringify(savedValue))
              await edit({ op: 'set', building: building.id, piece: piece.id, field: savedField, value: savedValue });
            state.baseline = typed;
          }).catch(report).finally(() => {
            --state.queued;
            if (selection?.pieceId === piece.id && selection?.buildingId === building.id) draw();
          });
        } catch (error) { report(error); }
      };
      input.addEventListener('change', save);
      input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save(); } });
      label.append(input);
      if (field === 'floor_offset_ft') for (const [text, delta] of [['Down 0.5 ft', -.5], ['Up 0.5 ft', .5]]) {
        const nudge = button(text, () => queue(async () => {
          if (!canEdit()) return;
          const current = findPiece(getPlan(), piece.id, building.id)?.piece;
          if (current) await op({ op: 'set', building: building.id, id: piece.id, field,
            value: (current.floor_offset_ft || 0) + delta });
          draw();
        }));
        nudge.type = 'button'; label.append(nudge);
      }
      if (field === 'pitch' || hosted(kind) && units[field]) { const unit = document.createElement('span'); unit.textContent = units[field]; label.append(unit); }
      (['ridge', 'low_side'].includes(field) ? more : form).append(label);
    }
    if (more.children.length > 1) form.append(more);
    if (haLink && ['room', 'building', 'anchor'].includes(kind) && !['meter','electric_panel','charger','parking'].includes(piece.kind)) {
      haSection = document.createElement('section'); host.append(haSection); drawHaSection(record);
    }
    host.append(button('Ask Argyle about this', () => ask(selection)));
    if (piece.state === 'ghost' || flags.length) {
      acceptButton = button('Looks right', async () => { await pending; await edit({ op: 'accept', building: building.id, pieces: [piece.id] }); draw(); });
      host.append(acceptButton);
    }
    host.append(button('Delete', remove));
  }
  async function remove() {
    const record = selection && findPiece(getPlan(), selection.pieceId, selection.buildingId);
    if (!record) return;
    const { kind, piece, building } = record;
    const roof = kind === 'roof' && building.roofs?.find(r => r.id === piece.id);
      if (!canEdit()) return;
      if (!await window.promptConfirm(`Delete ${getLabel(selection)}?`, 'Attached doors or windows may also be removed. The timeline keeps the earlier house.', 'Delete', 'Cancel')) return;
      await pending;
      if (!building) await op({ op: 'delete_site_item', list: kind, index: record.index });
      else if ((kind==='solar_zone' || roof && !piece.rect) && op) await op({ op: 'delete', building: building.id, id: piece.id });
      else await edit({ op: 'delete', building: building.id, piece: piece.id });
      select(null);

  }
  function drawEdge(next, record, roof) {
    const edge = roof.edges[edgeIndex];
    if (!edge) { edgeIndex = null; layout = null; draw(next); return; }
    const signature = `edge:${edgeIndex}:${JSON.stringify(edge)}:${canEdit()}`;
    selection = next; host.hidden = false;
    if (layout === signature) return;
    layout = signature; host.replaceChildren(); inputs = new Map();
    const heading = document.createElement('h3'); heading.textContent = `Roof edge ${edgeIndex + 1}`;
    host.append(heading, button('Back to roof', () => { edgeIndex = null; layout = null; draw(); }));
    const index = edgeIndex, building = record.building.id;
    const save = change => {
      if (!canEdit()) return;
      pending = pending.then(() => {
        const current = getPlan().buildings.find(b => b.id === building)?.roofs.find(r => r.id === roof.id);
        return op({ op: 'set_roof_edge', building, roof: roof.id, edge: index,
          setting: current?.edges[index].setting || roof.edges[index].setting, ...change });
      }).catch(report).finally(() => draw());
      return pending;
    };
    for (const [setting, label] of [['sloped', 'Sloped'], ['gable', 'Gable'], ['clip', 'Clipped']]) {
      const choice = button(label, () => save({ setting }));
      choice.setAttribute('aria-pressed', String(edge.setting === setting)); host.append(choice);
    }
    const label = document.createElement('label'); label.textContent = 'Pitch';
    const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.max = '24'; input.step = 'any';
    input.setAttribute('aria-label', 'Pitch'); input.value = edge.pitch ?? roof.pitch ?? 6; input.disabled = !canEdit();
    let baseline = String(input.value);
    const savePitch = () => {
      if (String(input.value) === baseline) return;
      const pitch = Number(input.value);
      if (!input.value.trim() || !Number.isFinite(pitch) || pitch < 0 || pitch > 24) {
        report(new Error('Choose a pitch from 0 to 24 in 12.')); return;
      }
      baseline = String(input.value); save({ pitch });
    };
    input.addEventListener('change', savePitch);
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); savePitch(); } });
    label.append(input); const unit = document.createElement('span'); unit.textContent = 'in 12'; label.append(unit); host.append(label);
  }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = !canEdit();
    node.addEventListener('click', () => Promise.resolve().then(action).catch(report)); return node;
  }
  function kindIsEquipment(record) { return record.kind === 'anchor' && ['charger', 'parking'].includes(record.piece.kind); }
  // A change from outside the fields (the area pick, Use, a device placement)
  // waits behind any field save still running, as Delete does, rather than
  // being refused while the house finishes that save.
  function queue(work) {
    const run = pending.then(() => work());
    pending = run.catch(() => {});
    return run;
  }
  return { draw, queue, remove, edge(handle) {
    const next = { pieceId: handle.id, buildingId: handle.building };
    selection = next; edgeIndex = handle.edge; layout = null; draw(next);
  } };
}
