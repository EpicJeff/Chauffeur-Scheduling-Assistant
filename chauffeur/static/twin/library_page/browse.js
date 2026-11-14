import { base } from '../twin_library.js';
import { node, button } from './properties.js';

// Browse online: search a CC0 library through this server, pick a resolution,
// Add, and follow the one-at-a-time download job until the material exists.
const SOURCES = [['polyhaven', 'Poly Haven'], ['ambientcg', 'ambientCG']];
const LICENCE = 'CC0';
const SEARCH_DELAY = 300, POLL_EVERY = 500, POLL_RETRIES = 5;
const INTERRUPTED = 'The download was interrupted, most likely by a Chauffeur restart. Try again.';
const LOST = 'Chauffeur stopped answering about this download. It may still finish; if it does, it will appear in the catalogue.';
const sourceLabel = id => SOURCES.find(([value]) => value === id)?.[1] || id;
const size = value => Number.parseFloat(value) || 0;

// 2k when offered, otherwise the offered size nearest to it (the smaller on a tie).
export function pickResolution(offered = []) {
  if (offered.includes('2k')) return '2k';
  return [...offered].sort((a, b) => Math.abs(size(a) - 2) - Math.abs(size(b) - 2) || size(a) - size(b))[0] ?? null;
}

// open(id) shows a material in the editor, refresh() reloads the catalogue rows and
// selection() counts the person's picks, so a late job never steals the editor.
export function mountBrowse(host, { api, open, refresh, selection, signal, onToggle = () => {} }) {
  let source = SOURCES[0][0], searched = false, turn = 0, timer;
  const jobs = new Map(), cards = new Map();
  const wait = ms => new Promise(resolve => {
    const done = () => { clearTimeout(id); signal.removeEventListener('abort', done); resolve(); };
    const id = setTimeout(done, ms);
    signal.addEventListener('abort', done, { once: true });
  });
  signal.addEventListener('abort', () => clearTimeout(timer), { once: true });

  host.replaceChildren();
  const header = node('div', null, 'library-header'), close = button('Close', 'browse-close', () => hide(), signal);
  header.append(node('h2', 'Browse online'), close);
  const switcher = node('div', null, 'editor-actions');
  switcher.setAttribute('role', 'group'); switcher.setAttribute('aria-label', 'Online library');
  for (const [value, label] of SOURCES) {
    const control = button(label, 'browse-source', () => {
      // The active source runs again too: that is how a failed search is retried.
      source = value; paintSources(); return run();
    }, signal);
    control.dataset.browseSource = value; switcher.append(control);
  }
  const search = node('input'); search.type = 'search'; search.dataset.browseSearch = '';
  search.placeholder = 'Search online materials'; search.setAttribute('aria-label', 'Search online materials');
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, SEARCH_DELAY); }, { signal });
  const status = node('output', null, 'place-muted'); status.dataset.browseStatus = ''; status.setAttribute('aria-live', 'polite');
  const grid = node('div', null, 'library-grid library-browse-grid');
  host.append(header, node('p', `Poly Haven and ambientCG share their materials as ${LICENCE}: free for any use. Added materials download once into your Library.`, 'place-muted'),
    switcher, search, status, grid);
  paintSources();

  function paintSources() {
    switcher.querySelectorAll('button').forEach(control => control.setAttribute('aria-pressed', String(control.dataset.browseSource === source)));
  }
  async function run() {
    clearTimeout(timer);
    const mine = ++turn, query = search.value.trim();
    status.textContent = `Searching ${sourceLabel(source)}…`;
    try {
      const { results } = await api(`materials/sources/${encodeURIComponent(source)}?q=${encodeURIComponent(query)}`);
      if (signal.aborted || mine !== turn) return;
      searched = true; draw(results || []);
      status.textContent = results?.length ? `${results.length} ${results.length === 1 ? 'material' : 'materials'} from ${sourceLabel(source)}`
        : `Nothing on ${sourceLabel(source)} matches.`;
    } catch (error) {
      if (signal.aborted || mine !== turn) return;
      // Offline is said here; the rest of the Library keeps working.
      draw([]); status.textContent = error.message || String(error);
    }
  }
  function draw(rows) {
    cards.clear(); grid.replaceChildren();
    for (const row of rows) {
      const key = `${row.source}:${row.source_id}`, card = node('div', null, 'library-browse-card');
      card.dataset.browseResult = key;
      const image = node('img'); image.alt = ''; image.width = 112; image.height = 96; image.loading = 'lazy';
      image.addEventListener('error', () => image.removeAttribute('src'), { once: true });
      const url = base() + row.thumbnail; image.src = window.chfAuthUrl ? window.chfAuthUrl(url) : url;
      const credit = node('small');
      if (row.source_url) {
        const link = node('a', sourceLabel(row.source)); link.href = row.source_url;
        link.setAttribute('target', '_blank'); link.setAttribute('rel', 'noopener noreferrer');
        credit.append(link, ` · ${LICENCE}`);
      } else credit.textContent = `${sourceLabel(row.source)} · ${LICENCE}`;
      const resolution = node('select'); resolution.dataset.resolution = '';
      resolution.setAttribute('aria-label', `Resolution for ${row.name}`);
      for (const value of row.resolutions || []) { const option = node('option', value); option.value = value; resolution.append(option); }
      const chosen = pickResolution(row.resolutions || []); if (chosen) resolution.value = chosen;
      const add = button('Add', 'add', () => start(row, key, resolution.value), signal);
      add.setAttribute('aria-label', `Add ${row.name}`);
      const progress = node('output', null, 'place-muted');
      const controls = node('div', null, 'library-browse-add'); controls.append(resolution, add);
      card.append(image, node('span', row.name), credit, controls, progress);
      grid.append(card);
      cards.set(key, { card, resolution, add, progress, offered: !!chosen });
      paint(key);
    }
  }
  // A job outlives a redraw: the card for its row, if drawn, shows its state.
  function paint(key) {
    const view = cards.get(key); if (!view) return;
    const job = jobs.get(key);
    view.add.disabled = !!job?.busy || !view.offered;
    view.resolution.disabled = !!job?.busy || !view.offered;
    view.progress.textContent = job?.text || (view.offered ? '' : 'No download size within limits.');
  }
  function note(key, text, busy = true) { jobs.set(key, { text, busy }); paint(key); }
  async function start(row, key, resolution) {
    if (jobs.get(key)?.busy || !resolution) return;
    const picked = selection();
    note(key, 'Starting…');
    try {
      const { job_id: id } = await api(`materials/sources/${encodeURIComponent(row.source)}/${encodeURIComponent(row.source_id)}/download`,
        'POST', { resolution });
      note(key, 'Waiting to download…');
      for (let misses = 0; ;) {
        await wait(POLL_EVERY);
        if (signal.aborted) return;
        let job;
        try { job = await api('materials/jobs/' + encodeURIComponent(id)); misses = 0; }
        catch (error) {
          if (signal.aborted) return;
          if (error.status === 404) throw new Error(INTERRUPTED);
          // A blip is retried; past that the job may still finish on the server.
          if (++misses <= POLL_RETRIES) continue;
          note(key, 'Lost track; it may still finish', false);
          window.showGlobalAlert(LOST);
          await refresh().catch(() => {});
          return;
        }
        if (signal.aborted) return;
        if (job.state === 'failed') throw new Error(job.error || 'The download failed. Try again.');
        if (job.state === 'done') {
          note(key, `Added at ${resolution}`, false);
          // The material exists now; a failure to open it is not a failed Add. Open it only
          // when the person is still here for it: Browse open and no other pick since Add.
          try {
            if (!host.hidden && selection() === picked) await open(job.material_id); else await refresh();
          } catch (error) { if (!signal.aborted) window.showGlobalAlert(error.message || String(error)); }
          return;
        }
        note(key, job.state === 'queued' ? 'Waiting for other downloads…'
          : `Downloading ${Math.round((Number(job.progress) || 0) * 100)}%`);
      }
    } catch (error) {
      if (signal.aborted) return;
      note(key, 'Not added', false);
      window.showGlobalAlert(error.message || String(error));
    }
  }
  function show() { host.hidden = false; onToggle(true); return searched ? Promise.resolve() : run(); }
  function hide() { host.hidden = true; onToggle(false); }
  hide();
  return { show, hide, get shown() { return !host.hidden; } };
}
