import { contains } from '../twin_generator.js';
import { materialLines } from './library.js';

const report = error => {
  if (!error.shown && !error.cancelled) window.showGlobalAlert(error.message || 'Could not save this change.');
};

// Keep this list aligned with twin_edit.EDITABLE; the server validates every save.
const fields = {
  wall: ['height', 'thickness', 'exterior'], opening: ['width', 'sill', 'head', 'kind', 'panels', 'at'],
  room: ['name', 'ha_area'], roof: ['kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side', 'ends'],
  building: ['name', 'position', 'rotation', 'base'], level: ['name', 'elevation', 'ceiling'],
};
const lengths = new Set(['height', 'thickness', 'width', 'sill', 'head', 'at', 'plate', 'overhang', 'base', 'elevation', 'ceiling']);
const labels = { ha_area: 'Home Assistant area', low_side: 'Low side', at: 'Distance along the wall', ridge: 'Ridge',
  sill: 'Height above floor', head: 'Top of opening', plate: 'Wall height under the roof', base: 'Height above ground', elevation: 'Height above ground' };
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
  for (const kind of ['planting', 'furniture']) {
    const index = plan?.site?.[kind]?.findIndex((p, i) => (p.id || `${kind}:${i}`) === pieceId) ?? -1;
    if (index >= 0 && !buildingId) return { piece: { ...plan.site[kind][index], id: pieceId }, kind, index, building: null };
  }
  const building = plan?.buildings.find(b => b.id === buildingId);
  if (!building) return null;
  if (building.id === pieceId) return { piece: building, building, kind: 'building' };
  for (const [list, kind] of [['levels', 'level'], ['walls', 'wall'], ['openings', 'opening'], ['rooms', 'room'], ['stairs', 'stair'], ['anchors', 'anchor'], ['items', 'item'], ['fixtures', 'fixture'], ['lights', 'light']]) {
    const piece = building[list]?.find(p => p.id === pieceId);
    if (piece) return { piece, building, kind };
  }
  const piece = building.roof?.sections?.find(p => p.id === pieceId);
  return piece ? { piece, building, kind: 'roof' } : null;
}

export function createCards({ getPlan, getKit = () => ({}), getLabel, getSelection = () => ({}), getFieldLabels = () => ({}), edit, op, ask, canEdit, select }) {
  const host = document.getElementById('piece-card');
  let selection = null, pending = Promise.resolve(), inputs = new Map(), headingNode = null, acceptButton = null, pitchNote = null, layout = null;
  const endNames = { x0: 'Left end', x1: 'Right end', y0: 'Front end', y1: 'Back end' };
  const fieldValue = (piece, field) => field.startsWith('ends.') ? (piece.ends?.[field.slice(5)] ?? piece.kind) : piece[field];
  const title = ({ kind, piece, building }) => {
    const name = kind === 'opening' ? (piece.kind === 'window' ? 'Window' : 'Door')
      : piece.name || piece.preset || (kind === 'roof' ? 'Roof section' : kind[0].toUpperCase() + kind.slice(1));
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
  const display = (field, value) => lengths.has(field) ? feetInches(value || 0)
    : field === 'position' ? (value || [0, 0]).map(feetInches).join(', ') : String(value ?? '');
  const raw = input => input.type === 'checkbox' ? input.checked : input.value;
  const roofFlags = record => record?.kind === 'roof' && record.piece.block && !record.piece.dormer_of
    ? (record.building.roof.flags || []).filter(flag => flag.block_rect?.length === 4
      && flag.block_rect.every((v, i) => Math.abs(v - record.piece.block[i]) <= 1)) : [];
  function draw(next = selection) {
    const record = next && findPiece(getPlan(), next.pieceId, next.buildingId);
    const materials = record ? materialLines(record, getPlan(), getKit()) : [];
    const flags = roofFlags(record);
    const nextLayout = JSON.stringify([record?.kind === 'roof' ? `${record.piece.kind}:${record.piece.ridge}:${JSON.stringify(flags)}` : record?.kind, materials]);
    host.hidden = !record;
    if (record && layout === nextLayout && selection?.pieceId === next.pieceId && selection?.buildingId === next.buildingId) {
      headingNode.textContent = title(record);
      if (pitchNote) pitchNote.hidden = record.piece.pitch_source !== 'photos';
      if (acceptButton) acceptButton.hidden = record.piece.state !== 'ghost' && !flags.length;
      host.querySelectorAll('button').forEach(b => { b.disabled = !canEdit(); });
      // A save or poll refreshes clean values without replacing anyone's input.
      for (const [field, state] of inputs) {
        const { input } = state;
        if (document.activeElement !== input && raw(input) === state.baseline && !state.queued) {
          if (field === 'exterior') input.checked = !!record.piece[field];
          else input.value = display(field, fieldValue(record.piece, field));
          state.baseline = raw(input);
        }
        input.disabled = !canEdit();
      }
      return;
    }
    selection = next; layout = nextLayout; host.replaceChildren(); inputs = new Map(); acceptButton = null; pitchNote = null;
    if (!record) return;
    const { piece, kind, building } = record;
    const heading = headingNode = document.createElement('h3'); heading.textContent = title(record);
    const close = button('Close', () => select(null)); close.setAttribute('aria-label', 'Close piece card');
    host.append(heading, close);
    for (const material of materials) {
      const row = document.createElement('div'); row.className = 'editor-material-line';
      const words = document.createElement('div'), label = document.createElement('span'), text = document.createElement('p');
      label.textContent = material.label; text.textContent = material.text; words.append(label, text); row.append(words);
      if (material.clear) row.append(button('Clear', async () => {
        if (canEdit()) await op({ op: 'set_material', building: building.id, target: material.target, material: null });
      }));
      host.append(row);
    }
    if (kind === 'roof') {
      pitchNote = document.createElement('p'); pitchNote.textContent = 'Estimated from photos';
      pitchNote.hidden = piece.pitch_source !== 'photos'; host.append(pitchNote);
      for (const flag of flags) {
        const note = document.createElement('p'); note.textContent = flag.text; host.append(note);
      }
    }
    const form = document.createElement('form'); form.addEventListener('submit', event => event.preventDefault()); host.append(form);
    const more = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = 'More'; more.append(summary);
    const cardFields = (fields[kind] || []).flatMap(field => field !== 'ends' ? [field]
      : ['gable', 'hip'].includes(piece.kind) ? [`ends.${piece.ridge}0`, `ends.${piece.ridge}1`] : []);
    for (const field of cardFields) {
      const end = field.startsWith('ends.') ? field.slice(5) : null;
      const label = document.createElement('label'); label.textContent = end ? endNames[end]
        : getFieldLabels()[field] || labels[field] || field[0].toUpperCase() + field.slice(1);
      let input;
      const choices = field === 'kind' ? (kind === 'roof' ? ['hip', 'gable', 'shed', 'flat'] : ['window', 'door', 'slider', 'bifold', 'passage', 'garage'])
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
      input.value = display(field, initial);
      if (field === 'exterior') input.checked = !!initial;
      input.disabled = !canEdit();
      const state = { input, baseline: raw(input), queued: 0, lastQueued: undefined };
      inputs.set(field, state);
      const save = () => {
        if (!canEdit()) return;
        const typed = raw(input);
        if (typed === (state.queued ? state.lastQueued : state.baseline)) return;
        try {
          const value = field === 'exterior' ? input.checked : lengths.has(field) ? parseLength(input.value)
            : field === 'position' ? input.value.split(',').map(parseLength)
              : ['pitch', 'rotation', 'panels'].includes(field) ? Number(input.value) : input.value;
          if (['pitch', 'rotation', 'panels'].includes(field) && (!input.value.trim() || !Number.isFinite(value)))
            throw new Error('Use a finite number.');
          if (field === 'panels' && (!Number.isInteger(value) || value < 1)) throw new Error('Use a whole number of panels, at least 1.');
          if (field === 'position' && value.length !== 2) throw new Error('Use two distances, separated by a comma.');
          ++state.queued; state.lastQueued = typed;
          pending = pending.then(async () => {
            const current = findPiece(getPlan(), piece.id, building.id)?.piece;
            const savedField = end ? 'ends' : field;
            const savedValue = end ? { ...current?.ends, [end]: value } : value;
            if (current && JSON.stringify(current[savedField]) !== JSON.stringify(savedValue))
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
      if (field === 'pitch') { const unit = document.createElement('span'); unit.textContent = 'in 12'; label.append(unit); }
      (['ridge', 'low_side'].includes(field) ? more : form).append(label);
    }
    if (more.children.length > 1) form.append(more);
    host.append(button('Ask Argyle about this', () => ask(selection)));
    if (piece.state === 'ghost' || flags.length) {
      acceptButton = button('Looks right', async () => { await pending; await edit({ op: 'accept', building: building.id, pieces: [piece.id] }); draw(); });
      host.append(acceptButton);
    }
    host.append(button('Delete', async () => {
      if (!canEdit()) return;
      if (!await window.promptConfirm(`Delete ${getLabel(selection)}?`, 'Attached doors or windows may also be removed. The timeline keeps the earlier house.', 'Delete', 'Cancel')) return;
      await pending;
      if (['planting', 'furniture'].includes(kind)) await op({ op: 'delete_site_item', list: kind, index: record.index });
      else await edit({ op: 'delete', building: building.id, piece: piece.id });
      select(null);
    }));
  }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = !canEdit();
    node.addEventListener('click', () => Promise.resolve().then(action).catch(report)); return node;
  }
  return { draw };
}
