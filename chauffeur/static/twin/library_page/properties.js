import { libUrl, materialUrl } from '../twin_library.js';

export const slots = [['base_color', 'Base colour'], ['normal', 'Normal'], ['roughness', 'Roughness'],
  ['metalness', 'Metalness'], ['ao', 'AO'], ['orm', 'ORM'], ['height', 'Height']];
export const defaults = { tint: '#ffffff', roughness: null, metalness: null, normal_scale: 1,
  normal_convention: 'gl', ao_intensity: 1, tile_ft: [4, 4], rotation_deg: 0, random_offset: false };

export function node(tag, text, className) {
  const out = document.createElement(tag);
  if (text) out.textContent = text;
  if (className) out.className = className;
  return out;
}
export function button(text, action, run, signal) {
  const out = node('button', text); out.type = 'button'; out.dataset.action = action;
  out.addEventListener('click', run, { signal }); return out;
}
export function mapUrl(entry, slot) {
  if (entry.previewMaps?.[slot]) return entry.previewMaps[slot];
  const path = entry.maps?.[slot];
  return !path ? null : entry.source === 'builtin' ? libUrl(entry.id, path)
    : materialUrl(path.startsWith('materials/') ? path : `materials/${entry.id}/${path}`);
}

export function mountProperties(host, entry, { change, replaceMap, clearMap, signal }) {
  host.replaceChildren();
  const readonly = entry.source === 'builtin', controls = [];
  host.append(node('h2', 'Properties'));
  if (readonly) host.append(node('p', 'Built-in material. Duplicate to edit.', 'place-muted'));
  function textField(key, label) {
    const row = node('label', label), input = node('input'); input.type = 'text';
    input.value = entry[key] || ''; input.disabled = readonly; input.dataset.field = key;
    input.addEventListener('change', () => change({ [key]: input.value }), { signal });
    row.append(input); host.append(row); controls.push(() => { input.value = entry[key] || ''; });
  }
  textField('name', 'Name'); textField('licence', 'Licence');
  const source = node('p', `Source: ${entry.source} · Revision ${entry.revision}`, 'place-muted'); host.append(source);
  for (const [slot, label] of slots) {
    const row = node('section', null, 'library-map'); row.dataset.slot = slot;
    const title = node('h3', label), image = node('img'); image.alt = `${label} map`; image.width = image.height = 64;
    const url = mapUrl(entry, slot); if (url) image.src = url; else image.hidden = true;
    row.append(title, image, node('span', url ? '' : 'No map', 'place-muted'));
    if (!readonly) {
      const label = node('label', 'Replace', 'library-replace'), input = node('input');
      input.type = 'file'; input.accept = 'image/*'; input.setAttribute('aria-label', `Replace ${title.textContent}`);
      input.addEventListener('change', async () => {
        const file = input.files?.[0]; if (file) await replaceMap(slot, file); input.value = '';
      }, { signal });
      label.append(input); row.append(label, button('Clear', 'clear', () => clearMap(slot), signal));
    }
    if (slot === 'normal') {
      const label = node('label', 'Normal convention'), select = node('select');
      for (const [value, text] of [['gl', 'GL'], ['dx', 'DX']]) { const option = node('option', text); option.value = value; select.append(option); }
      select.value = entry.params.normal_convention; select.disabled = readonly;
      select.dataset.field = 'normal_convention';
      select.addEventListener('change', () => change({ params: { normal_convention: select.value } }), { signal });
      controls.push(() => { select.value = entry.params.normal_convention; }); label.append(select); row.append(label);
    }
    if (slot === 'orm') row.append(node('p', 'R: AO · G: Roughness · B: Metalness. ORM takes priority over separate maps.', 'place-muted'));
    if (slot === 'height') row.append(node('p', 'Stored for future displacement; not rendered.', 'place-muted'));
    host.append(row);
  }
  const valueAt = key => key.startsWith('tile_ft.') ? entry.params.tile_ft[Number(key.at(-1))] : entry.params[key];
  const param = (key, value) => change({ params: key.startsWith('tile_ft.')
    ? { tile_ft: entry.params.tile_ft.map((v, i) => i === Number(key.at(-1)) ? value : v) } : { [key]: value } });
  for (const [key, title, min, max, step] of [
    ['roughness', 'Roughness', 0, 2, .01], ['metalness', 'Metalness', 0, 2, .01],
    ['normal_scale', 'Normal scale', 0, 4, .01], ['ao_intensity', 'AO intensity', 0, 2, .01],
    ['tile_ft.0', 'Tile width (ft)', .25, 200, .25], ['tile_ft.1', 'Tile height (ft)', .25, 200, .25],
    ['rotation_deg', 'Rotation (°)', 0, 359, 1],
  ]) {
    const row = node('div', null, 'library-param'), label = node('span', title); row.append(label);
    if (readonly) { row.append(node('output', String(valueAt(key) ?? 'Auto'))); host.append(row); continue; }
    let auto;
    if (key === 'roughness' || key === 'metalness') {
      const label = node('label', 'Auto'); auto = node('input'); auto.type = 'checkbox'; auto.dataset.param = key;
      auto.setAttribute('aria-label', `${title} Auto`);
      auto.addEventListener('change', () => param(key, auto.checked ? null : 1), { signal }); label.prepend(auto); row.append(label);
    }
    const pair = node('div', null, 'library-numeric'), inputs = [];
    for (const type of ['range', 'number']) {
      const input = node('input'); input.type = type; input.min = String(min); input.max = String(max); input.step = String(step);
      input.dataset.param = key; input.setAttribute('aria-label', `${title}${type === 'range' ? ' slider' : ''}`);
      input.addEventListener('input', () => {
        const value = Number(input.value);
        if (input.value !== '' && Number.isFinite(value) && value >= min && value <= max) param(key, value);
      }, { signal }); pair.append(input); inputs.push(input);
    }
    controls.push(() => { const value = valueAt(key); if (auto) auto.checked = value == null;
      pair.hidden = value == null; inputs.forEach(input => { input.value = String(value ?? 1); }); });
    row.append(pair); host.append(row);
  }
  for (const [key, title, type] of [['tint', 'Tint', 'color'], ['random_offset', 'Random UV offset per surface', 'checkbox']]) {
    const row = node('label', title), input = node('input'); input.type = type; input.disabled = readonly;
    if (!readonly) input.dataset.param = key;
    input.addEventListener(type === 'color' ? 'input' : 'change', () => param(key, type === 'checkbox' ? input.checked : input.value), { signal });
    controls.push(() => { if (type === 'checkbox') input.checked = !!valueAt(key); else input.value = valueAt(key); });
    row.prepend(input); host.append(row);
  }
  const sync = next => { entry = next; controls.forEach(update => update()); source.textContent = `Source: ${entry.source} · Revision ${entry.revision}`; };
  sync(entry); return { sync };
}
