import { mountTwin } from '../twin_view.js';
import { request, createPolling, idleInterval, buildInterval, checkpoint, plain, report } from './api.js';
import { createPanel } from './panel.js';

const el = id => document.getElementById(id);
const emptyPlan = () => ({ schema: 'chauffeur.twin.plan/2', units: 'ft', buildings: [], site: {}, materials: {} });

export async function boot() {
  const hooks = window.__editor = { ready: false };
  let view = null, snapshot = { plan: null, rounds: [], cost: {}, build: null };
  let sheets = { sources: [], page_roles: [] }, rows = [], confirmed = false;
  let currentBuild = null, ghostBuild = null, renderedGhosts = 0, lastScene = '';
  let uploadsBusy = false, rolesBusy = false, building = false;
  const ghosts = new Map(), prompted = new Set();
  const panel = createPanel({ afterSay: async () => { await polling.pollNow(true); } });

  function setStatus(text) { el('editor-status').textContent = plain(text); }
  function syncBuildButton() {
    el('editor-build').disabled = !confirmed || uploadsBusy || rolesBusy || building || currentBuild?.state === 'running';
  }
  function cost(value) { el('editor-cost').textContent = `$${Number(value || 0).toFixed(2)}`; }
  function countGhosts(plan) {
    if (!plan || typeof plan !== 'object') return 0;
    return (plan.state === 'ghost' ? 1 : 0) + Object.values(plan).reduce((n, value) =>
      n + (value && typeof value === 'object' ? countGhosts(value) : 0), 0);
  }
  function previewPlan() {
    const plan = structuredClone(snapshot.plan || emptyPlan());
    // Outlines awaiting a person's approval live in events, never in saved
    // rounds. Give each one a temporary floor using the existing scene builder.
    for (const [stepId, event] of ghosts) {
      const outline = event.piece?.outline;
      if (!outline?.length) continue;
      const step = currentBuild?.steps.find(item => item.id === stepId);
      const owner = sheets.page_roles.find(row => row.source === step?.source && row.page === step?.page);
      const house = plan.buildings.find(item => item.id === (owner?.building || 'house'));
      const level = house?.levels.find(item => item.id === step?.level);
      const elevation = level?.elevation ?? Math.max(0, Number((step?.level || 'L1').slice(1)) - 1) * 9;
      plan.buildings.push({
        id: `editor-preview:${stepId}`, name: step?.label || 'Floor outline',
        position: house?.position || [0, 0], rotation: house?.rotation || 0, base: house?.base || 0,
        levels: [{ id: 'preview', name: 'Outline', elevation: elevation + .04, ceiling: 9, state: 'ghost' }],
        walls: [], openings: [], rooms: [{ id: 'outline', level: 'preview', polygon: outline }],
        roof: { sections: [] },
      });
    }
    return plan;
  }
  async function renderScene() {
    const plan = previewPlan(), signature = JSON.stringify(plan);
    if (view && signature !== lastScene) {
      await view.rebuild(plan);
      view.scene.background?.set?.('#171e27');
      lastScene = signature;
    }
    renderedGhosts = countGhosts(plan);
    drawFloors();
  }
  function drawFloors() {
    const host = el('editor-floors'); host.replaceChildren();
    const title = document.createElement('span'); title.textContent = 'Floors'; host.append(title);
    const levels = (snapshot.plan?.buildings || []).flatMap(house => house.levels.map(level => ({ house, level })));
    if (!levels.length && currentBuild) {
      for (const step of currentBuild.steps.filter(step => ['outline', 'registration'].includes(step.kind))) {
        const label = document.createElement('p'); label.textContent = plain(step.level_name || step.level); host.append(label);
      }
    } else if (!levels.length) {
      const label = document.createElement('p'); label.textContent = 'No floors yet'; host.append(label);
    }
    for (const { house, level } of levels.reverse()) {
      const button = document.createElement('button'); button.type = 'button';
      const key = `${house.id}:${level.id}`;
      button.textContent = plain(level.name || level.id);
      button.setAttribute('aria-pressed', String(view?.state.view === key));
      button.addEventListener('click', () => { view?.setView(key); drawFloors(); }); host.append(button);
    }
  }
  function drawTimeline(build) {
    const steps = build?.steps || [], done = steps.filter(step => step.status === 'done').length;
    el('editor-progress').max = steps.length || 1; el('editor-progress').value = done;
    el('editor-step-count').textContent = steps.length ? `${done} of ${steps.length} steps` : '0 steps';
    el('editor-time-note').textContent = build?.state === 'paused' ? 'Argyle is waiting for you to check this step.'
      : build?.state === 'done' ? 'Your house is ready to explore.' : 'Your build will appear here, one step at a time.';
  }
  function drawPages() {
    const host = el('editor-pages'); host.replaceChildren();
    for (const [index, row] of rows.entries()) {
      const source = sheets.sources.find(source => source.id === row.source);
      const group = document.createElement('fieldset'); group.className = 'editor-page';
      const legend = document.createElement('legend'); legend.textContent = plain(`${source?.filename || 'Drawing'} · page ${row.page}`);
      const roleLabel = document.createElement('label'); roleLabel.textContent = 'This page shows';
      const select = document.createElement('select'); select.dataset.pageRole = ''; select.id = `editor-role-${index}`;
      for (const [value, label] of [['floor', 'Floor'], ['roof', 'Roof'], ['plot', 'Lot'], ['elevation', 'Outside view'], ['other', 'Other'], ['skip', 'Skip']]) {
        const option = document.createElement('option'); option.value = value; option.textContent = label; select.append(option);
      }
      select.value = row.role;
      const levelLabel = document.createElement('label'); levelLabel.textContent = 'Level name';
      const input = document.createElement('input'); input.type = 'text'; input.maxLength = 80;
      input.value = row.level || ''; input.placeholder = 'For example, Main floor';
      select.addEventListener('change', () => { row.role = select.value; confirmed = false; syncBuildButton(); });
      input.addEventListener('input', () => { row.level = input.value.trim() || null; confirmed = false; syncBuildButton(); });
      roleLabel.append(select); levelLabel.append(input); group.append(legend, roleLabel, levelLabel);
      if (row.box) { const crop = document.createElement('p'); crop.textContent = 'One part of this page'; group.append(crop); }
      host.append(group);
    }
    el('editor-suggest-roles').disabled = rolesBusy || uploadsBusy || !sheets.sources.some(source => source.kind === 'drawing');
    el('editor-confirm-roles').disabled = rolesBusy || uploadsBusy || !rows.length;
    syncBuildButton();
  }
  async function loadSheets() {
    sheets = await request('sheets');
    rows = sheets.page_roles.map(row => ({ ...row }));
    const missing = [];
    for (const source of sheets.sources.filter(source => source.kind === 'drawing')) {
      for (let page = 1; page <= source.pages; page++) {
        if (!rows.some(row => row.source === source.id && row.page === page)) {
          missing.push({ source: source.id, page, role: 'other', level: null, box: null, building: 'house' });
        }
      }
    }
    rows.push(...missing);
    confirmed = missing.length === 0 && rows.some(row => row.role === 'floor');
    el('editor-upload').hidden = sheets.sources.length > 0 && confirmed;
    el('editor-source-count').textContent = `${sheets.sources.filter(source => source.kind === 'drawing').reduce((n, source) => n + source.pages, 0)} sheets · ${sheets.sources.filter(source => source.kind === 'photo').length} photos`;
    drawPages();
  }
  const polling = createPolling({
    async onState(state) {
      if (!state.build && currentBuild) {
        currentBuild = null; ghostBuild = null; ghosts.clear(); panel.reset(); drawTimeline(null);
        await loadSheets();
      }
      snapshot = state; cost(state.cost?.total);
      await renderScene(); syncBuildButton();
      if (!currentBuild) setStatus(confirmed ? 'Ready to build' : 'Add drawings to begin');
    },
    async onBuild(build) {
      if (ghostBuild !== build.id) { ghosts.clear(); ghostBuild = build.id; }
      currentBuild = build;
      for (const event of build.events || []) {
        if (event.type === 'ghost') ghosts.set(event.step, event);
        if (event.type === 'settled') ghosts.delete(event.step);
      }
      panel.events(build); drawTimeline(build); syncBuildButton();
      const step = build.steps.find(step => step.status === 'running' || step.status === 'paused');
      setStatus(build.state === 'running' ? `Argyle is building${step ? ' · ' + step.label : ''}`
        : build.state === 'paused' ? 'Check this step with Argyle'
          : build.state === 'done' ? 'House ready' : build.state === 'checkpoint' ? 'Spending checkpoint' : 'Build stopped');
      // Each new event batch can carry saved pieces, temporary outlines or
      // new costs. Read their owning state before rebuilding the scene.
      if (build.events?.length) await polling.refreshState();
      else await renderScene();
      if (build.state === 'checkpoint') {
        const detail = [...(build.events || [])].reverse().find(event => event.type === 'checkpoint')
          || { checkpoint: snapshot.cost?.blocking, total: snapshot.cost?.total };
        const key = `${build.id}:${detail.checkpoint}`;
        if (detail.checkpoint && !prompted.has(key)) {
          prompted.add(key);
          if (await checkpoint(detail)) await request(`build/${build.id}/resume`, 'POST', {});
        }
      }
    },
    onError(error) { if (!error.shown && !error.cancelled) setStatus(error.message || 'Connection paused. Trying again…'); },
  });

  el('editor-source-files').addEventListener('change', async event => {
    if (uploadsBusy) return;
    uploadsBusy = true; drawPages();
    try {
      for (const file of event.target.files) {
        if (!['application/pdf', 'image/jpeg', 'image/png'].includes(file.type)) throw new Error('Choose a PDF, JPEG or PNG file.');
        el('editor-upload-status').textContent = plain(`Uploading ${file.name}…`);
        const data = new FormData(); data.append('kind', file.type === 'application/pdf' ? 'drawing' : 'photo'); data.append('file', file);
        await request('sources', 'POST', data, 'twin');
      }
      await loadSheets();
      el('editor-upload-status').textContent = 'Check each page, then confirm.';
    } catch (error) { report(error); }
    finally { uploadsBusy = false; event.target.value = ''; drawPages(); }
  });
  el('editor-suggest-roles').addEventListener('click', async () => {
    rolesBusy = true; drawPages();
    try {
      // Suggestions remain local until the person confirms the complete list.
      for (const source of sheets.sources.filter(source => source.kind === 'drawing')) {
        const result = await request('sheets/suggest', 'POST', { source: source.id });
        const suggestedPages = new Set(result.rows.map(row => row.page));
        rows = rows.filter(row => row.source !== source.id || !suggestedPages.has(row.page)).concat(result.rows);
      }
      confirmed = false;
      el('editor-upload-status').textContent = 'These are suggestions. Check the roles and level names, then confirm.';
    } catch (error) { report(error); }
    finally { rolesBusy = false; drawPages(); await polling.pollNow(true).catch(report); }
  });
  el('editor-confirm-roles').addEventListener('click', async () => {
    rolesBusy = true; drawPages();
    try {
      const result = await request('sheets/roles', 'PUT', { rows });
      sheets.page_roles = result.page_roles;
      confirmed = result.page_roles.some(row => row.role === 'floor');
      el('editor-upload-status').textContent = confirmed ? 'Pages confirmed. You can build now.' : 'Choose at least one floor page to build.';
      setStatus(confirmed ? 'Ready to build' : 'Choose a floor page');
    } catch (error) { report(error); }
    finally { rolesBusy = false; drawPages(); }
  });
  el('editor-build').addEventListener('click', async () => {
    building = true; syncBuildButton();
    try {
      const result = await request('build', 'POST', {
        building: { id: 'house', name: 'Main house' },
        photos: sheets.sources.filter(source => source.kind === 'photo').map(source => source.id),
      });
      el('editor-upload').hidden = true;
      await polling.follow(result.id);
    } catch (error) { report(error); }
    finally { building = false; syncBuildButton(); }
  });
  el('editor-manage-sources').addEventListener('click', () => {
    el('editor-upload').hidden = !el('editor-upload').hidden;
    el('editor-menu').open = false;
    if (!el('editor-upload').hidden) el('editor-source-files').focus();
  });

  if (new URLSearchParams(location.search).get('test') === '1') Object.assign(hooks, {
    ghostCount: () => renderedGhosts, build: () => currentBuild,
    pollNow: () => polling.pollNow(true).catch(report), idleInterval, buildInterval,
    isEmpty: () => sheets.sources.length === 0,
  });
  window.addEventListener('pagehide', () => { polling.stop(); view?.dispose(); }, { once: true });
  try {
    await loadSheets();
    const kit = await request('kit/modern_farmhouse', 'GET', undefined, 'twin');
    view = await mountTwin(el('editor-scene'), { plan: emptyPlan(), kit });
    // The editor uses the mockup's dark work surface; the shared preview keeps
    // its own daylight sky, with the same renderer and lighting.
    view.scene.background?.set?.('#171e27');
    await polling.start();
    view.scene.background?.set?.('#171e27');
    hooks.ready = true;
  } catch (error) {
    setStatus(error.status === 401 || error.status === 403 ? 'Sign in to edit your house' : 'Could not open the house. Reload to try again.');
    if (error.status !== 401 && error.status !== 403) report(error);
  }
}
