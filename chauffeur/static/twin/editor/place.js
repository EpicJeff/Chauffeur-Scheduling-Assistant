import { active, report } from './api.js';

const el = id => document.getElementById(id);
const copy = value => structuredClone(value);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const pageKey = row => `${row.source}:${row.page}`;
const roleWords = { floor: 'Floor', roof: 'Roof', elevation: 'Outside view', plot: 'Plot plan',
  survey: 'Survey', landscape: 'Landscape plan', other: 'Other', skip: 'Skip' };
// Use textContent for names, filenames, reader hints and server sentences.
function node(tag, text, attrs = {}) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  for (const [key, value] of Object.entries(attrs)) result.setAttribute(key, value);
  return result;
}
function select(options, value, attrs = {}) {
  const result = node('select', undefined, attrs);
  for (const [id, label] of options) result.append(node('option', label, { value: id }));
  result.value = value;
  return result;
}
function labelled(text, control) {
  const label = node('label', text); label.append(control); return label;
}
function svgNode(tag, attrs) {
  const result = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) result.setAttribute(key, value);
  return result;
}
const points = outline => outline.map(p => p.join(',')).join(' ');
const cleanRow = row => Object.fromEntries(['source', 'page', 'role', 'level', 'box', 'building'].map(k => [k, row[k] ?? null]));

export function createPlace({ request, getSheets, reload, follow, canEdit, panel }) {
  const host = el('place-view'), map = el('place-map');
  let sheets = getSheets(), snapshot = {}, rows = [], saved = [], busy = false, signature = '', returnFocus = null;
  let footprints = new Map(), savedFootprints = new Map(), streetEdge = null, lotSignature = '';
  let selected = null, drawing = null, drag = null;
  const suggestionDrafts = new Map();
  const place = () => sheets.place || { buildings: [], lot: {}, photo_tags: {} };
  const parts = () => [{ id: 'lot', name: 'Lot' }, ...place().buildings];
  const kinds = () => (sheets.kinds || []).map(k => [k.id, k.label]);
  const buildActive = () => active(snapshot.buildState || (snapshot.build ? { state: 'running' } : null));
  const stopped = (duringBuild = false) => busy || !canEdit() || (!duringBuild && buildActive());
  const grouped = list => {
    const pages = new Map();
    for (const row of list) { const key = pageKey(row); if (!pages.has(key)) pages.set(key, []); pages.get(key).push(cleanRow(row)); }
    return [...pages].sort(([a], [b]) => a.localeCompare(b));
  };
  const dirty = () => !same(grouped(rows), grouped(saved));
  const plot = () => saved.find(row => row.building === 'lot' && row.role === 'plot');
  const plotConfirmed = () => !!plot() && rows.some(row => same(cleanRow(row), plot()));
  const hasDrawings = id => rows.some(row => row.building === id);
  const ready = id => id === 'lot' ? !!plot() : saved.some(row => row.building === id && row.role === 'floor')
    || (!hasDrawings(id) && !!place().buildings.find(b => b.id === id)?.footprint);
  const sheetURL = (source, page) => {
    const url = (window.chfBase ?? '../') + `api/house/editor/sheets/${encodeURIComponent(source)}/${page}.png`;
    return window.chfAuthUrl ? window.chfAuthUrl(url) : url;
  };
  function status(text) { el('place-status').textContent = text; }
  function controls() {
    const blocked = stopped();
    host.querySelectorAll('input, select, button').forEach(control => {
      if (control.id !== 'place-close') control.disabled = control.matches('[data-place-upload], [data-place-tag]') ? stopped(true) : blocked;
    });
    host.querySelectorAll('[data-place-build]').forEach(button => {
      button.disabled = blocked || dirty() || !ready(button.dataset.placeBuild);
    });
    host.querySelectorAll('[data-place-suggest]').forEach(button => {
      const source = sheets.sources.find(s => s.id === button.dataset.placeSuggest);
      const assigned = Array.from({ length: source?.pages || 0 }, (_, i) => i + 1)
        .every(page => saved.some(row => row.source === source.id && row.page === page));
      button.disabled = blocked || assigned;
      button.title = !canEdit() ? 'Return to editing before suggesting page roles.'
        : busy ? 'Wait for the current change to finish.'
          : buildActive() ? 'Wait until the build finishes before suggesting page roles.'
            : assigned ? 'Page roles are already saved for this document. You can change each role by hand.'
              : button.getAttribute('aria-label');
    });
    el('place-build').disabled = blocked || dirty() || !parts().some(part => ready(part.id));
    el('place-confirm-pages').disabled = blocked || !rows.length;
    el('place-read-plot').disabled = blocked || !plotConfirmed();
    el('place-suggest-photos').disabled = blocked || !(sheets.sources || []).some(s => s.kind === 'photo');
    el('place-confirm-placement').disabled = blocked || !place().lot?.read;
    el('place-turn').disabled = blocked || !selected;
    host.setAttribute('aria-busy', String(busy));
  }
  async function work(action, duringBuild = false) {
    if (stopped(duringBuild)) return;
    busy = true; controls();
    try { await action(); }
    catch (error) { report(error); }
    finally { busy = false; controls(); }
  }
  async function mutate(path, method, body) {
    const result = await request(path, method, body);
    await reload();
    if (result.summary) { status(result.summary); panel.message(result.summary); }
    return result;
  }
  const patch = (id, body) => mutate(`place/buildings/${encodeURIComponent(id)}`, 'PATCH', body);
  async function paid(title, key, action) {
    const estimate = sheets.estimates?.[key];
    const cost = Number.isFinite(estimate) ? `about $${estimate.toFixed(2)}` : null;
    if (await window.promptConfirm(title, cost ? `This will cost ${cost}. Continue?`
      : 'This reads your documents and adds to the running cost. Continue?', 'Continue', 'Cancel')) await action();
  }
  function close() {
    host.hidden = true; drawing = null; drag = null;
    delete map.dataset.drawing;
    for (const child of document.querySelector('.editor-shell').children) if (child !== host) child.inert = false;
    if (returnFocus?.isConnected && !returnFocus.closest('[hidden]')) returnFocus.focus();
    else el('editor-menu').querySelector('summary').focus();
  }
  function open() {
    returnFocus = document.activeElement;
    host.hidden = false;
    el('editor-menu').open = false;
    for (const child of document.querySelector('.editor-shell').children) if (child !== host) child.inert = true;
    render(); el('place-close').focus();
  }
  function pageRows(source, page) { return rows.filter(row => row.source === source && row.page === page); }
  async function move(row, part) {
    const onPage = pageRows(row.source, row.page), stored = saved.filter(r => pageKey(r) === pageKey(row));
    // A move explicitly accepts this page's draft regions, without confirming
    // the other pages. A fresh Other page uses the server's R8 creation rule.
    let region = onPage.indexOf(row);
    if (!stored.length && onPage.length === 1 && row.role === 'other' && !row.box) region = null;
    else if (!same(onPage.map(cleanRow), stored.map(cleanRow))) {
      await request('sheets/roles', 'PUT', { rows: [...saved.filter(r => pageKey(r) !== pageKey(row)), ...onPage].map(cleanRow) });
    }
    await mutate('place/pages/move', 'POST', { source: row.source, page: row.page, part,
      ...(region === null ? {} : { region }) });
  }
  function pagePreview(source, page, box) {
    const image = node('img', undefined, { src: sheetURL(source.id, page),
      alt: `${box ? 'Part of page' : 'Page'} ${page} of ${source.filename}`, loading: 'lazy' });
    if (!box) return image;
    const [x0, y0, x1, y1] = box, width = x1 - x0, height = y1 - y0;
    const crop = node('div', undefined, { class: 'place-region-preview' });
    Object.assign(image.style, { width: `${100 / width}%`, height: `${100 / height}%`,
      left: `${-100 * x0 / width}%`, top: `${-100 * y0 / height}%` });
    image.addEventListener('load', () => {
      const ratio = width * image.naturalWidth / (height * image.naturalHeight);
      crop.style.aspectRatio = String(ratio);
      crop.style.width = `min(100%, ${140 * ratio}px)`;
    });
    crop.append(image); return crop;
  }
  function pageCard(source, page, part) {
    const card = node('fieldset', undefined, { class: 'editor-page', 'data-place-page': `${source.id}:${page}` });
    card.append(node('legend', `${source.filename} · page ${page}`));
    for (const row of pageRows(source.id, page).filter(row => row.building === part)) {
      const region = node('div', undefined, { class: 'place-region' });
      region.append(pagePreview(source, page, row.box));
      if (row.box) region.append(node('p', 'One part of this page', { class: 'place-region-caption' }));
      const roles = sheets.roles?.[part === 'lot' ? 'lot' : 'building'] || [];
      const role = select(roles.map(id => [id, roleWords[id]]), row.role, { 'data-place-role': '' });
      role.addEventListener('change', () => { row.role = role.value; if (part === 'lot') row.level = null; controls(); });
      region.append(labelled('This page shows', role));
      if (part !== 'lot') {
        const level = node('input', undefined, { type: 'text', maxlength: '80', 'data-place-level': '', placeholder: 'For example, Main floor' });
        level.value = row.level || '';
        level.addEventListener('input', () => { row.level = level.value.trim() || null; controls(); });
        region.append(labelled('Level name', level));
      }
      const mover = select([['', 'Choose a part'], ...parts().filter(p => p.id !== part).map(p => [p.id, p.name])], '', { 'data-place-move': '' });
      mover.addEventListener('change', () => { if (mover.value) work(() => move(row, mover.value)); });
      region.append(labelled('Move to', mover));
      if (row.elsewhere && parts().some(p => p.id === row.elsewhere && p.id !== part)) {
        const hint = node('div', undefined, { 'data-place-hint': '' });
        hint.append(node('p', row.hint || `Page ${page} looks like the ${parts().find(p => p.id === row.elsewhere).name}.`));
        const button = node('button', 'Move it', { type: 'button' });
        button.addEventListener('click', () => work(() => move(row, row.elsewhere)));
        hint.append(button); region.append(hint);
      }
      card.append(region);
    }
    return card;
  }
  function photoCard(source) {
    const card = node('fieldset', undefined, { class: 'editor-page place-photo', 'data-place-photo': source.id });
    card.append(node('legend', source.filename), node('p', 'This photo shows'));
    const tags = place().photo_tags[source.id]?.length ? place().photo_tags[source.id] : ['lot'];
    const buttons = node('div', undefined, { class: 'editor-actions' });
    for (const part of parts()) {
      const button = node('button', part.name, { type: 'button', 'data-place-tag': part.id, 'aria-pressed': String(tags.includes(part.id)) });
      button.addEventListener('click', () => work(() => mutate(`place/photos/${encodeURIComponent(source.id)}`, 'PUT', {
        parts: tags.includes(part.id) ? tags.filter(id => id !== part.id) : [...tags, part.id] }), true)); buttons.append(button);
    }
    card.append(buttons); return card;
  }
  function shellCard(building) {
    const shell = node('fieldset', undefined, { class: 'place-shell', 'data-place-shell': building.id });
    shell.append(node('legend', 'Shape without drawings'));
    for (const [name, label, low, high, step] of [['storeys', 'Storeys', 1, 4, 1], ['wall_height', 'Wall height in feet', 6, 20, .5], ['pitch', 'Roof pitch, in 12', 0, 24, .5]]) {
      const input = node('input', undefined, { type: 'number', name, min: low, max: high, step }); input.value = building.shell[name];
      input.addEventListener('change', () => work(() => patch(building.id, { shell: { [name]: Number(input.value) } })));
      shell.append(labelled(label, input));
    }
    for (const [name, label, values] of [['roof', 'Roof', ['gable', 'hip', 'shed', 'flat']], ['door_side', 'Door side', ['front', 'back', 'left', 'right']]]) {
      const input = select(values.map(v => [v, v[0].toUpperCase() + v.slice(1)]), building.shell[name], { name });
      input.addEventListener('change', () => work(() => patch(building.id, { shell: { [name]: input.value } })));
      shell.append(labelled(label, input));
    }
    const size = node('form', undefined, { class: 'place-size', 'data-place-size': '' });
    const fp = footprints.get(building.id), extent = axis => fp?.length ? Math.max(...fp.map(p => p[axis])) - Math.min(...fp.map(p => p[axis])) : '';
    for (const [name, label, axis] of [['width', 'Width in feet', 0], ['depth', 'Depth in feet', 1]]) {
      const input = node('input', undefined, { type: 'number', name, min: '.1', step: 'any', required: '' });
      input.value = extent(axis); size.append(labelled(label, input));
    }
    size.append(node('button', 'Set size', { type: 'submit' }));
    size.addEventListener('submit', event => {
      event.preventDefault();
      work(() => {
        const width = Number(size.elements.width.value), depth = Number(size.elements.depth.value);
        const [x, y] = footprints.get(building.id)?.[0] || [0, 0];
        return patch(building.id, { footprint: [[x, y], [x + width, y], [x + width, y + depth], [x, y + depth]], footprint_from: 'typed' });
      });
    });
    shell.append(size);
    if (place().lot?.read || place().lot?.placement) {
      const draw = node('button', 'Draw on the lot', { type: 'button', 'data-place-draw': '' });
      draw.addEventListener('click', () => {
        drawing = building.id; selected = building.id; map.dataset.drawing = 'true';
        el('place-map-note').textContent = `Drag a rectangle on the lot for ${building.name}.`;
        map.scrollIntoView({ block: 'center', behavior: 'smooth' }); controls();
      }); shell.append(draw);
    }
    return shell;
  }
  function partCard(part) {
    const lot = part.id === 'lot';
    const card = node('section', undefined, { class: 'place-card', ...(lot ? { id: 'place-lot' } : { 'data-place-building': part.id }) });
    const head = node('header'); head.append(node('h3', part.name));
    if (!lot) head.append(node('span', sheets.kinds.find(k => k.id === part.kind)?.label || 'Other'));
    card.append(head);
    if (!lot) {
      const details = node('details'); details.append(node('summary', 'Name and kind'));
      const name = node('input', undefined, { type: 'text', maxlength: '100' }); name.value = part.name;
      name.addEventListener('change', () => work(() => patch(part.id, { name: name.value.trim() })));
      const kind = select(kinds(), part.kind);
      kind.addEventListener('change', () => work(() => patch(part.id, { kind: kind.value })));
      details.append(labelled('Name', name), labelled('Kind', kind));
      const remove = node('button', 'Remove building', { type: 'button' });
      remove.addEventListener('click', () => work(async () => {
        if (await window.promptConfirm(`Remove ${part.name}?`, 'Only a building without pages or built pieces can be removed.', 'Remove', 'Keep it'))
          await mutate(`place/buildings/${encodeURIComponent(part.id)}`, 'DELETE');
      })); details.append(remove); card.append(details);
    }
    const upload = node('input', undefined, { type: 'file', multiple: '', accept: 'application/pdf,image/jpeg,image/png', 'data-place-upload': part.id });
    upload.addEventListener('change', event => {
      const files = Array.from(event.target.files);
      work(async () => {
        const errors = []; let added = 0;
        for (const file of files) {
          if (!['application/pdf', 'image/jpeg', 'image/png'].includes(file.type)) { errors.push(`${file.name} could not be added: Choose a PDF, JPEG or PNG file.`); continue; }
          status(`Uploading ${file.name}…`);
          const data = new FormData(); data.append('part', part.id); data.append('kind', file.type === 'application/pdf' ? 'drawing' : 'photo'); data.append('file', file);
          try { await request('sources', 'POST', data, 'twin'); added++; }
          catch (error) { errors.push(`${file.name} could not be added: ${error.message}`); if (error.signedOut) break; }
        }
        await reload(); status(added ? 'Files added. Check each drawing page, then confirm.' : 'No files were added. Check the errors and try again.');
        if (errors.length) report(new Error(errors.join('\n')));
      }, true).finally(() => { upload.value = ''; });
    });
    card.append(labelled('Add drawings or photos', upload));
    let documents = 0;
    for (const source of sheets.sources.filter(s => s.kind === 'drawing')) {
      const pages = [...new Set(rows.filter(r => r.source === source.id && r.building === part.id).map(r => r.page))];
      if (!pages.length) continue;
      documents += pages.length;
      for (const page of pages) card.append(pageCard(source, page, part.id));
      const suggest = node('button', 'Suggest page roles', { type: 'button', 'data-place-suggest': source.id,
        'aria-label': `Suggest page roles for ${source.filename}` });
      suggest.addEventListener('click', () => work(() => paid('Suggest page roles?', 'roles', async () => {
        const result = await request('sheets/suggest', 'POST', { source: source.id });
        const assigned = new Set(saved.filter(r => r.source === source.id).map(r => r.page));
        const suggestions = result.rows.filter(r => !assigned.has(r.page));
        const suggested = new Set(suggestions.map(r => r.page));
        // Preserve the page order even when a reader lists the pages differently.
        const byPage = new Map();
        for (let page = 1; page <= source.pages; page++) byPage.set(page, suggestions.filter(r => r.page === page)
          .map(r => ({ ...r, source: source.id, building: r.building ?? source.part })));
        rows = rows.filter(r => r.source !== source.id || !suggested.has(r.page));
        rows.push(...[...byPage.values()].flat());
        status('These are suggestions. Check the roles and level names, then confirm.'); render();
      }))); card.append(suggest);
    }
    const photos = sheets.sources.filter(s => s.kind === 'photo' && (place().photo_tags[s.id]?.length ? place().photo_tags[s.id] : ['lot']).includes(part.id));
    for (const photo of photos) card.append(photoCard(photo));
    if (!documents && !photos.length) card.append(node('p', 'No drawings or photos yet.', { class: 'place-muted' }));
    if (!lot && !hasDrawings(part.id)) card.append(shellCard(part));
    const build = node('button', lot ? 'Build the lot' : 'Build this building', { type: 'button', 'data-place-build': part.id, class: 'place-primary' });
    build.addEventListener('click', () => work(() => buildPart(part.id))); card.append(build);
    return card;
  }
  async function buildPart(part) {
    await paid(part === 'place' ? 'Build your place?' : part === 'lot' ? 'Build the lot?' : 'Build this building?', 'build', async () => {
      const result = await request('build', 'POST', { part });
      close(); await follow(result.id);
    });
  }
  function plotSuggestions() {
    const host = el('place-suggestions'); host.replaceChildren();
    const read = place().lot?.read;
    for (const suggestion of read?.suggestions || []) {
      if (suggestion.state !== 'open') continue;
      const card = node('section', undefined, { class: 'editor-page', 'data-place-suggestion': suggestion.id });
      card.append(node('h3', suggestion.name || 'Building footprint'), node('p', `${suggestion.size_ft.map(n => Number(n).toFixed(1)).join(' by ')} feet · ${suggestion.where}`));
      const draftKey = `${read.id}:${suggestion.id}`;
      if (!suggestionDrafts.has(draftKey)) suggestionDrafts.set(draftKey, { name: suggestion.name || '', kind: 'other', building: '' });
      const draft = suggestionDrafts.get(draftKey);
      const name = node('input', undefined, { type: 'text', maxlength: '100', 'data-suggestion-name': '' }); name.value = draft.name;
      name.addEventListener('input', () => { draft.name = name.value; });
      const kind = select(kinds(), draft.kind, { 'data-suggestion-kind': '' }); kind.addEventListener('change', () => { draft.kind = kind.value; });
      const match = select([['', 'New building'], ...place().buildings.map(b => [b.id, b.name])], draft.building, { 'data-suggestion-match': '' });
      match.addEventListener('change', () => { draft.building = match.value; });
      const answer = action => work(() => mutate(`place/plot/suggestions/${encodeURIComponent(suggestion.id)}`, 'POST', {
        action, read: read.id, ...(draft.building ? { building: draft.building } : { name: draft.name.trim(), kind: draft.kind }) }));
      const accept = node('button', 'Accept', { type: 'button', 'data-suggestion-accept': '' }); accept.addEventListener('click', () => answer('accept'));
      const dismiss = node('button', 'Dismiss', { type: 'button', 'data-suggestion-dismiss': '' }); dismiss.addEventListener('click', () => answer('dismiss'));
      card.append(labelled('Match to', match), labelled('Name', name), labelled('Kind', kind), accept, dismiss); host.append(card);
    }
  }
  function photoSuggestions() {
    const host = el('place-photo-suggestions'); host.replaceChildren();
    for (const photo of place().photo_read?.photos || []) {
      const tags = place().photo_tags[photo.source] || ['lot'];
      for (const id of photo.parts.filter(id => !tags.includes(id))) {
        const part = parts().find(p => p.id === id); if (!part) continue;
        const row = node('div', undefined, { 'data-photo-suggestion': '', class: 'editor-page' });
        row.append(node('p', `${sheets.sources.find(s => s.id === photo.source)?.filename || 'Photo'} · Also shows ${part.name}`));
        const add = node('button', 'Add', { type: 'button' });
        add.addEventListener('click', () => work(() => mutate(`place/photos/${encodeURIComponent(photo.source)}`, 'PUT', { parts: [...tags, id] })));
        row.append(add); host.append(row);
      }
    }
    for (const suggestion of place().photo_read?.shells || []) {
      const building = place().buildings.find(b => b.id === suggestion.building);
      if (!building || hasDrawings(building.id) || building.shell_from === 'photos') continue;
      const shell = Object.fromEntries(['storeys', 'roof', 'pitch'].map(key => [key, suggestion[key]]));
      const row = node('div', undefined, { 'data-shell-suggestion': building.id, class: 'editor-page' });
      row.append(node('p', `${building.name} · From photos: ${shell.storeys} ${shell.storeys === 1 ? 'storey' : 'storeys'}, ${shell.roof}, ${shell.pitch} in 12`));
      const use = node('button', 'Use these', { type: 'button' });
      use.addEventListener('click', () => work(() => patch(building.id, { shell, shell_from: 'photos' }))); row.append(use); host.append(row);
    }
  }
  function drawMap() {
    const lot = place().lot, read = lot?.read;
    const outline = read?.lot || lot?.placement?.outline;
    el('place-placement').hidden = !outline?.length;
    map.replaceChildren();
    if (!outline?.length) return;
    const all = [...outline, ...[...footprints.values()].flat()];
    const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    const x = Math.min(...xs), y = Math.min(...ys), w = Math.max(...xs) - x, h = Math.max(...ys) - y;
    const pad = Math.max(w, h) * .08 || 10;
    map.setAttribute('viewBox', `${x - pad} ${y - pad} ${w + 2 * pad} ${h + 2 * pad}`);
    if (read?.matrix) map.append(svgNode('image', { href: sheetURL(read.source, read.page), x: 0, y: 0, width: 1, height: 1,
      preserveAspectRatio: 'none', transform: `matrix(${read.matrix.join(' ')})`, opacity: '.38' }));
    map.append(svgNode('polygon', { points: points(outline), class: 'place-lot-outline' }));
    outline.forEach((a, i) => {
      const b = outline[(i + 1) % outline.length];
      const edge = svgNode('g', { 'data-place-edge': i, tabindex: 0, role: 'button', 'aria-label': `Make lot edge ${i + 1} the street` });
      edge.append(svgNode('line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1],
        class: streetEdge?.includes(i) && streetEdge?.includes((i + 1) % outline.length) ? 'place-street' : 'place-edge' }));
      // Give even horizontal and vertical edges a real, tappable bounding box.
      const length = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, thickness = Math.max(w, h) * .015;
      const dx = (b[1] - a[1]) / length * thickness, dy = -(b[0] - a[0]) / length * thickness;
      edge.append(svgNode('polygon', { points: points([[a[0] + dx, a[1] + dy], [b[0] + dx, b[1] + dy],
        [b[0] - dx, b[1] - dy], [a[0] - dx, a[1] - dy]]), fill: 'transparent', class: 'place-edge-hit' }));
      const choose = () => { if (stopped()) return; streetEdge = [i, (i + 1) % outline.length]; drawMap(); };
      edge.addEventListener('click', choose);
      edge.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); choose(); } }); map.append(edge);
    });
    const scale = Math.min(map.clientWidth / (w + 2 * pad), map.clientHeight / (h + 2 * pad)) || 1;
    const fontSize = 13 / scale;
    for (const [id, outline] of footprints) {
      const name = place().buildings.find(b => b.id === id)?.name || 'Building';
      const group = svgNode('g', { class: 'place-map-footprint' });
      const polygon = svgNode('polygon', { points: points(outline), 'data-place-footprint': id, tabindex: 0, role: 'button',
        'aria-label': `Place ${name}`,
        class: selected === id ? 'place-footprint place-selected' : 'place-footprint' });
      const title = svgNode('title', {}); title.textContent = name; polygon.append(title);
      polygon.addEventListener('focus', () => selectFootprint(id));
      // Arrow keys move one foot; the same confirmation saves keyboard and pointer changes.
      polygon.addEventListener('keydown', event => {
        const by = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
        if (!by || stopped()) return;
        event.preventDefault(); footprints.set(id, footprints.get(id).map(p => p.map((v, i) => v + by[i])));
        drawMap(); map.querySelector(`[data-place-footprint="${CSS.escape(id)}"]`)?.focus();
      });
      const centre = [0, 1].map(i => outline.reduce((n, p) => n + p[i], 0) / outline.length);
      const width = Math.max(...outline.map(p => p[0])) - Math.min(...outline.map(p => p[0]));
      const height = Math.max(...outline.map(p => p[1])) - Math.min(...outline.map(p => p[1]));
      const small = width < fontSize * (name.length * .65 + 1) || height < fontSize * 1.5;
      const text = svgNode('text', { x: centre[0], y: centre[1],
        class: `place-map-label${small ? ' place-map-label-small' : ''}`, 'font-size': fontSize });
      text.textContent = name; group.append(polygon, text); map.append(group);
    }
  }
  function selectFootprint(id) {
    selected = id;
    map.querySelectorAll('[data-place-footprint]').forEach(polygon => {
      polygon.classList.toggle('place-selected', polygon.dataset.placeFootprint === id);
    });
    controls();
  }
  function render() {
    const addKind = el('place-add-kind'), chosenKind = addKind.value;
    addKind.replaceChildren(...kinds().map(([value, label]) => node('option', label, { value })));
    if (kinds().some(([id]) => id === chosenKind)) addKind.value = chosenKind;
    el('place-cards').replaceChildren(...parts().map(partCard));
    for (const [id, title, key] of [['place-read-plot', 'Read the plot plan', 'plot'], ['place-suggest-photos', 'Suggest from photos', 'photos']])
      el(id).textContent = `${title} · about $${Number(sheets.estimates?.[key] || 0).toFixed(2)}`;
    plotSuggestions(); photoSuggestions(); drawMap(); controls();
  }
  function sync(nextSheets, nextSnapshot) {
    const nextSignature = JSON.stringify([nextSheets, nextSnapshot.build, nextSnapshot.buildState?.state, canEdit()]);
    snapshot = nextSnapshot;
    if (signature === nextSignature) { controls(); return; }
    signature = nextSignature;
    const previousSaved = saved;
    sheets = nextSheets; saved = (sheets.page_roles || []).map(cleanRow);
    const nextRows = [];
    for (const source of sheets.sources || []) {
      if (source.kind !== 'drawing') continue;
      for (let page = 1; page <= source.pages; page++) {
        const key = `${source.id}:${page}`, old = previousSaved.filter(r => pageKey(r) === key), now = saved.filter(r => pageKey(r) === key);
        const draft = rows.filter(r => pageKey(r) === key);
        nextRows.push(...copy(same(old, now) && draft.length ? draft : now.length ? now
          : [{ source: source.id, page, building: source.part, role: 'other', level: null, box: null }]));
      }
    }
    rows = nextRows;
    const latest = new Map();
    for (const building of place().buildings) {
      latest.set(building.id, copy(building.footprint));
      if (!same(savedFootprints.get(building.id), building.footprint)) {
        if (building.footprint) footprints.set(building.id, copy(building.footprint)); else footprints.delete(building.id);
      }
    }
    for (const id of footprints.keys()) if (!latest.has(id)) footprints.delete(id);
    if (selected && !latest.has(selected)) selected = null;
    savedFootprints = latest;
    const lot = place().lot, nextLot = JSON.stringify([lot?.read?.id, lot?.read?.matrix, lot?.placement]);
    if (nextLot !== lotSignature) {
      streetEdge = copy(lot?.read?.street_edge || lot?.placement?.street_edge || null); lotSignature = nextLot;
    }
    render();
  }
  el('place-close').addEventListener('click', close);
  host.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const focusable = [...host.querySelectorAll('button, input, select, summary, [tabindex="0"]')].filter(n => !n.disabled && n.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  el('place-add-form').addEventListener('submit', event => {
    event.preventDefault(); work(async () => {
      await mutate('place/buildings', 'POST', { name: el('place-add-name').value.trim(), kind: el('place-add-kind').value });
      el('place-add-name').value = '';
    });
  });
  el('place-confirm-pages').addEventListener('click', () => work(async () => {
    await request('sheets/roles', 'PUT', { rows: rows.map(cleanRow) }); await reload(); status('Pages confirmed. You can build now.');
  }));
  el('place-read-plot').addEventListener('click', () => work(() => paid('Read the plot plan?', 'plot', async () => {
    await request('place/plot/read', 'POST', {}); await reload(); status('Check each footprint before accepting it.');
  })));
  el('place-suggest-photos').addEventListener('click', () => work(() => paid('Suggest from photos?', 'photos', async () => {
    await request('place/photos/suggest', 'POST', {}); await reload(); status('Check the photo suggestions before adding them.');
  })));
  el('place-build').addEventListener('click', () => work(() => buildPart('place')));
  el('place-confirm-placement').addEventListener('click', () => work(async () => {
    // When the street changes the server reprojects untouched plot footprints.
    const changed = [...footprints].filter(([id, outline]) => !same(outline, savedFootprints.get(id)));
    await mutate('place/lot/placement', 'PUT', { street_edge: streetEdge, footprints: changed.map(([building, outline]) => ({ building, outline })) });
    status('Placement confirmed.');
  }));
  el('place-turn').addEventListener('click', () => {
    if (stopped() || !selected || !footprints.has(selected)) return;
    const outline = footprints.get(selected), centre = [0, 1].map(i => outline.reduce((sum, p) => sum + p[i], 0) / outline.length);
    footprints.set(selected, outline.map(([x, y]) => [centre[0] - (y - centre[1]), centre[1] + (x - centre[0])])); drawMap();
  });
  const world = event => {
    const point = new DOMPoint(event.clientX, event.clientY); return point.matrixTransform(map.getScreenCTM().inverse());
  };
  map.addEventListener('pointerdown', event => {
    if (stopped() || event.button !== 0) return;
    const id = event.target.closest('[data-place-footprint]')?.dataset.placeFootprint;
    if (!drawing && !id) return;
    event.preventDefault();
    const p = world(event); selectFootprint(drawing || id);
    drag = { id: selected, start: [p.x, p.y], outline: copy(footprints.get(selected) || []), pointer: event.pointerId, drawing: !!drawing };
    map.setPointerCapture(event.pointerId); controls();
  });
  map.addEventListener('pointermove', event => {
    if (!drag || drag.pointer !== event.pointerId) return;
    const p = world(event), [x, y] = drag.start;
    const outline = drag.drawing ? [[Math.min(x, p.x), Math.min(y, p.y)], [Math.max(x, p.x), Math.min(y, p.y)],
      [Math.max(x, p.x), Math.max(y, p.y)], [Math.min(x, p.x), Math.max(y, p.y)]]
      : drag.outline.map(q => [q[0] + p.x - x, q[1] + p.y - y]);
    footprints.set(drag.id, outline);
    let polygon = [...map.querySelectorAll('[data-place-footprint]')].find(n => n.dataset.placeFootprint === drag.id);
    if (!polygon) { polygon = svgNode('polygon', { 'data-place-footprint': drag.id, class: 'place-footprint place-selected' }); map.append(polygon); }
    polygon.setAttribute('points', points(outline));
  });
  function endDrag(event) {
    if (!drag || drag.pointer !== event.pointerId) return;
    const start = drag; drag = null;
    if (map.hasPointerCapture(event.pointerId)) map.releasePointerCapture(event.pointerId);
    if (event.type === 'pointercancel') {
      if (start.outline.length) footprints.set(start.id, start.outline); else footprints.delete(start.id);
    } else if (start.drawing) {
      const outline = footprints.get(start.id);
      if (outline?.length) work(async () => {
        try { await patch(start.id, { footprint: outline, footprint_from: 'drawn' }); }
        catch (error) {
          if (start.outline.length) footprints.set(start.id, start.outline); else footprints.delete(start.id);
          drawMap(); throw error;
        }
      });
      drawing = null; delete map.dataset.drawing;
    }
    el('place-map-note').textContent = 'Tap a lot edge for the street. Drag a building to place it, or select it and use the arrow keys.';
    drawMap(); controls();
  }
  map.addEventListener('pointerup', endDrag); map.addEventListener('pointercancel', endDrag);
  return { open, close, isOpen: () => !host.hidden, sync };
}
