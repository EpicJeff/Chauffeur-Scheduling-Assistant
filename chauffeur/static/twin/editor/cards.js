import { report } from './api.js';

// Keep this list aligned with twin_edit.EDITABLE; the server validates every save.
const fields = {
  wall: ['height', 'thickness', 'exterior'], opening: ['width', 'sill', 'head', 'kind', 'panels', 'at'],
  room: ['name', 'ha_area'], roof: ['kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side'],
  building: ['name', 'position', 'rotation', 'base'], level: ['name', 'elevation', 'ceiling'],
};
const lengths = new Set(['height', 'thickness', 'width', 'sill', 'head', 'at', 'plate', 'overhang', 'base', 'elevation', 'ceiling']);
const labels = { ha_area: 'Home Assistant area', low_side: 'Low side', at: 'At', ridge: 'Ridge' };
export function feetInches(value) {
  const inches = Math.round(Math.abs(value) * 12);
  return `${value < 0 ? '-' : ''}${Math.floor(inches / 12)}'-${inches % 12}"`;
}
export function parseLength(text) {
  text = text.trim().replace(/[′’]/g, "'").replace(/[″“”]/g, '"');
  const match = text.match(/^(-?)(\d+(?:\.\d+)?)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*"?$/);
  const value = match ? (match[1] ? -1 : 1) * (Number(match[2]) + Number(match[3] || 0) / 12) : Number(text.replace(/"$/, '')) / (text.endsWith('"') ? 12 : 1);
  if (!text || !Number.isFinite(value)) throw new Error('Use feet and inches, such as 11\'-0", or a number of feet.');
  return value;
}
export function findPiece(plan, pieceId, buildingId) {
  const building = plan?.buildings.find(b => b.id === buildingId);
  if (!building) return null;
  if (building.id === pieceId) return { piece: building, building, kind: 'building' };
  for (const [list, kind] of [['levels', 'level'], ['walls', 'wall'], ['openings', 'opening'], ['rooms', 'room'], ['stairs', 'stair'], ['fixtures', 'fixture'], ['lights', 'light']]) {
    const piece = building[list]?.find(p => p.id === pieceId);
    if (piece) return { piece, building, kind };
  }
  const piece = building.roof?.sections?.find(p => p.id === pieceId);
  return piece ? { piece, building, kind: 'roof' } : null;
}

export function createCards({ getPlan, edit, ask, canEdit, select }) {
  const host = document.getElementById('piece-card');
  let selection = null, busy = false;
  function draw(next = selection) {
    selection = next; host.replaceChildren();
    const record = next && findPiece(getPlan(), next.pieceId, next.buildingId);
    host.hidden = !record;
    if (!record) return;
    const { piece, kind, building } = record;
    const heading = document.createElement('h3'); heading.textContent = piece.name || (kind === 'roof' ? 'Roof section' : kind[0].toUpperCase() + kind.slice(1));
    const close = button('Close', () => select(null)); close.setAttribute('aria-label', 'Close piece card');
    host.append(heading, close);
    const form = document.createElement('form'); form.addEventListener('submit', event => event.preventDefault()); host.append(form);
    const more = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = 'More'; more.append(summary);
    for (const field of fields[kind] || []) {
      const label = document.createElement('label'); label.textContent = labels[field] || field[0].toUpperCase() + field.slice(1);
      let input;
      const choices = field === 'kind' ? (kind === 'roof' ? ['hip', 'gable', 'shed', 'flat'] : ['window', 'door', 'slider', 'bifold', 'passage', 'garage'])
        : field === 'ridge' ? ['x', 'y'] : field === 'low_side' ? ['x0', 'x1', 'y0', 'y1'] : null;
      if (choices) {
        input = document.createElement('select');
        choices.forEach(value => {
          const option = document.createElement('option'); option.value = value;
          option.textContent = ({ x: 'Left to right', y: 'Front to back', x0: 'Left', x1: 'Right', y0: 'Front', y1: 'Back',
            hip: 'Hip', gable: 'Gable', shed: 'One slope', flat: 'Flat', window: 'Window', door: 'Door', slider: 'Sliding door',
            bifold: 'Folding door', passage: 'Open passage', garage: 'Garage door' })[value];
          input.append(option);
        });
      } else { input = document.createElement('input'); input.type = field === 'exterior' ? 'checkbox' : 'text'; }
      const initial = piece[field];
      input.value = lengths.has(field) ? feetInches(initial || 0) : field === 'position' ? (initial || [0, 0]).map(feetInches).join(', ') : String(initial ?? '');
      if (field === 'exterior') input.checked = !!initial;
      input.disabled = !canEdit() || busy;
      let saving = false;
      const save = async () => {
        if (saving || busy || !canEdit()) return;
        try {
          const value = field === 'exterior' ? input.checked : lengths.has(field) ? parseLength(input.value)
            : field === 'position' ? input.value.split(',').map(parseLength)
              : ['pitch', 'rotation', 'panels'].includes(field) ? Number(input.value) : input.value;
          if (JSON.stringify(value) === JSON.stringify(initial)) return;
          saving = true; busy = true; input.disabled = true;
          await edit({ op: 'set', building: building.id, piece: piece.id, field, value });
        } catch (error) { report(error); }
        finally { saving = false; busy = false; draw(); }
      };
      input.addEventListener('change', save);
      input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save(); } });
      label.append(input);
      if (field === 'pitch') { const unit = document.createElement('span'); unit.textContent = 'in 12'; label.append(unit); }
      (['ridge', 'low_side'].includes(field) ? more : form).append(label);
    }
    if (more.children.length > 1) form.append(more);
    host.append(button('Ask Argyle about this', () => ask(selection)));
    if (piece.state === 'ghost') host.append(button('Looks right', async () => { await edit({ op: 'accept', building: building.id, pieces: [piece.id] }); draw(); }));
    host.append(button('Delete', async () => {
      if (!canEdit() || busy) return;
      if (!await window.promptConfirm('Delete this piece?', 'Attached doors or windows may also be removed. The timeline keeps the earlier house.', 'Delete', 'Cancel')) return;
      await edit({ op: 'delete', building: building.id, piece: piece.id }); select(null);
    }));
  }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = !canEdit() || busy;
    node.addEventListener('click', () => Promise.resolve().then(action).catch(report)); return node;
  }
  return { draw };
}
