import { base } from '../twin_library.js';

// Hosted equipment uses the same card queue as the ordinary property fields.
export function createEquipmentShelf({ canEdit, queue, op, report, parseLength, feetInches, onSaved,
  api = path => fetch(base() + path) }) {
  let choices = null, loading = null, current = null;
  const element = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  async function load() {
    if (choices) return choices;
    if (!loading) loading = Promise.allSettled(['api/ha/card/states', 'api/house/twin/energy'].map(async path => {
      const response = await api(path);
      if (!response.ok) throw new Error('Choices unavailable');
      return response.json();
    })).then(([ha, fleet]) => {
      choices = {
        states: ha.status === 'fulfilled' ? ha.value.states || {} : {},
        cars: fleet.status === 'fulfilled' && Array.isArray(fleet.value.cars) ? fleet.value.cars : [],
      };
      return choices;
    });
    return loading;
  }
  function options(input, field, value) {
    const rows = [['', field === 'car' ? 'Unassigned' : 'None']];
    if (field === 'car') {
      for (const car of choices?.cars || []) rows.push([String(car.id), car.name || String(car.id)]);
    } else {
      for (const [id, state] of Object.entries(choices?.states || {}).sort(([a], [b]) => a.localeCompare(b))) {
        if (!['w', 'kw', 'mw'].includes(String(state.attributes?.unit_of_measurement || '').toLowerCase())) continue;
        rows.push([id, `${state.attributes?.friendly_name || id} (${id})`]);
      }
    }
    if (value && !rows.some(([id]) => id === value)) rows.push([value, `${value} (saved; unavailable)`]);
    input.replaceChildren(...rows.map(([id, name]) => {
      const option = element('option', name); option.value = id; return option;
    }));
    input.value = value;
  }
  const display = (field, piece) => ['width', 'depth'].includes(field)
    ? feetInches(piece[field] ?? (field === 'width' ? 9 : 18)) : String(piece[field] ?? (field === 'rotation' ? 0 : ''));
  function refresh(record) {
    if (!current || current.id !== record.piece.id || current.building !== record.building.id) return;
    for (const [field, state] of current.fields) {
      state.input.disabled = !canEdit();
      if (document.activeElement === state.input || state.queued || state.input.value !== state.baseline) continue;
      const value = display(field, record.piece);
      if (state.input.tagName === 'SELECT') options(state.input, field, value);
      else state.input.value = value;
      state.baseline = state.input.value;
    }
  }
  function draw(host, record) {
    const { piece, building } = record, section = element('section'); host.append(section);
    const card = current = { id: piece.id, building: building.id, fields: new Map() };
    const fields = piece.kind === 'charger'
      ? [['name', 'Name'], ['power', 'Power entity'], ['car', 'Dedicated car (optional)']]
      : [['car', 'Assigned car (optional)'], ['width', 'Width'], ['depth', 'Length'], ['rotation', 'Turn (degrees)']];
    for (const [field, title] of fields) {
      const label = element('label', title), picker = ['car', 'power'].includes(field);
      const input = element(picker ? 'select' : 'input');
      if (!picker) { input.type = 'text'; if (field === 'name') input.maxLength = 100; }
      input.setAttribute('aria-label', title); input.dataset.equipmentField = field;
      const value = display(field, piece);
      if (picker) options(input, field, value); else input.value = value;
      input.disabled = !canEdit();
      const state = { input, baseline: input.value, queued: 0, lastQueued: undefined }; card.fields.set(field, state);
      const save = () => {
        if (!canEdit()) return;
        const typed = input.value;
        if (typed === (state.queued ? state.lastQueued : state.baseline)) return;
        let next;
        try {
          next = picker ? typed || null : ['width', 'depth'].includes(field) ? parseLength(typed)
            : field === 'rotation' ? Number(typed.replace(/°/g, '')) : typed.trim();
          if (['width', 'depth'].includes(field) && next <= 0) throw new Error('Use a size greater than zero.');
          if (field === 'rotation' && (!typed.trim() || !Number.isFinite(next))) throw new Error('Use a finite number of degrees.');
          if (field === 'name' && !next) throw new Error('Give the charger a name.');
        } catch (error) { report(error); return; }
        ++state.queued; state.lastQueued = typed;
        queue(async () => {
          if (!canEdit()) return;
          await op({ op: 'set', building: building.id, id: piece.id, field, value: next });
          state.baseline = typed;
        }).catch(report).finally(() => { --state.queued; if (current === card) onSaved?.(); });
      };
      input.addEventListener('change', save);
      input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); save(); } });
      label.append(input); section.append(label);
    }
    load().then(() => {
      if (current !== card) return;
      for (const [field, state] of card.fields) {
        if (state.input.tagName !== 'SELECT' || document.activeElement === state.input) continue;
        options(state.input, field, state.input.value);
      }
    });
  }
  return { draw, refresh };
}
