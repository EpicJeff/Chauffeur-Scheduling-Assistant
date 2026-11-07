// Kept dependency-free so the length parser can also run outside the browser.
const report = error => {
  if (!error.shown && !error.cancelled) window.showGlobalAlert(error.message || 'Could not save this change.');
};

// Keep this list aligned with twin_edit.EDITABLE; the server validates every save.
const fields = {
  wall: ['height', 'thickness', 'exterior'], opening: ['width', 'sill', 'head', 'kind', 'panels', 'at'],
  room: ['name', 'ha_area'], roof: ['kind', 'pitch', 'plate', 'overhang', 'ridge', 'low_side'],
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

export function createCards({ getPlan, getLabel, getFieldLabels = () => ({}), edit, ask, canEdit, select }) {
  const host = document.getElementById('piece-card');
  let selection = null, pending = Promise.resolve(), inputs = new Map(), headingNode = null, acceptButton = null, pitchNote = null;
  const title = ({ kind, piece }) => kind === 'opening' ? (piece.kind === 'window' ? 'Window' : 'Door')
    : piece.name || (kind === 'roof' ? 'Roof section' : kind[0].toUpperCase() + kind.slice(1));
  const display = (field, value) => lengths.has(field) ? feetInches(value || 0)
    : field === 'position' ? (value || [0, 0]).map(feetInches).join(', ') : String(value ?? '');
  const raw = input => input.type === 'checkbox' ? input.checked : input.value;
  function draw(next = selection) {
    const record = next && findPiece(getPlan(), next.pieceId, next.buildingId);
    host.hidden = !record;
    if (record && selection?.pieceId === next.pieceId && selection?.buildingId === next.buildingId) {
      headingNode.textContent = title(record);
      if (pitchNote) pitchNote.hidden = record.piece.pitch_source !== 'photos';
      if (acceptButton) acceptButton.hidden = record.piece.state !== 'ghost';
      host.querySelectorAll('button').forEach(b => { b.disabled = !canEdit(); });
      // A save or poll refreshes clean values without replacing anyone's input.
      for (const [field, state] of inputs) {
        const { input } = state;
        if (document.activeElement !== input && raw(input) === state.baseline && !state.queued) {
          if (field === 'exterior') input.checked = !!record.piece[field];
          else input.value = display(field, record.piece[field]);
          state.baseline = raw(input);
        }
        input.disabled = !canEdit();
      }
      return;
    }
    selection = next; host.replaceChildren(); inputs = new Map(); acceptButton = null; pitchNote = null;
    if (!record) return;
    const { piece, kind, building } = record;
    const heading = headingNode = document.createElement('h3'); heading.textContent = title(record);
    const close = button('Close', () => select(null)); close.setAttribute('aria-label', 'Close piece card');
    host.append(heading, close);
    if (kind === 'roof') {
      pitchNote = document.createElement('p'); pitchNote.textContent = 'Estimated from photos';
      pitchNote.hidden = piece.pitch_source !== 'photos'; host.append(pitchNote);
    }
    const form = document.createElement('form'); form.addEventListener('submit', event => event.preventDefault()); host.append(form);
    const more = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = 'More'; more.append(summary);
    for (const field of fields[kind] || []) {
      const label = document.createElement('label'); label.textContent = getFieldLabels()[field] || labels[field] || field[0].toUpperCase() + field.slice(1);
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
            if (current && JSON.stringify(current[field]) !== JSON.stringify(value))
              await edit({ op: 'set', building: building.id, piece: piece.id, field, value });
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
    if (piece.state === 'ghost') {
      acceptButton = button('Looks right', async () => { await pending; await edit({ op: 'accept', building: building.id, pieces: [piece.id] }); draw(); });
      host.append(acceptButton);
    }
    host.append(button('Delete', async () => {
      if (!canEdit()) return;
      if (!await window.promptConfirm(`Delete ${getLabel(selection)}?`, 'Attached doors or windows may also be removed. The timeline keeps the earlier house.', 'Delete', 'Cancel')) return;
      await pending;
      await edit({ op: 'delete', building: building.id, piece: piece.id }); select(null);
    }));
  }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = !canEdit();
    node.addEventListener('click', () => Promise.resolve().then(action).catch(report)); return node;
  }
  return { draw };
}
