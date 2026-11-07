import { mountTwin } from '../twin_view.js';
import { request, createPolling, idleInterval, buildInterval, checkpoint, plain, report, active, session } from './api.js';
import { createPanel } from './panel.js';
import { createSceneTools } from './scene_tools.js';
import { createPlanView } from './plan_view.js';
import { createPauses, applyRegistration, invertRegistration } from './pauses.js';
import { createTimeline } from './timeline.js';

const el = id => document.getElementById(id);
const emptyPlan = () => ({ schema: 'chauffeur.twin.plan/2', units: 'ft', buildings: [], site: {}, materials: {} });

export async function boot() {
  const hooks = window.__editor = { ready: false };
  let view = null, snapshot = { plan: null, rounds: [], cost: {}, build: null };
  let sheets = { sources: [], page_roles: [] }, rows = [], confirmed = false;
  let currentBuild = null, ghostBuild = null, renderedGhosts = 0, lastScene = '';
  let uploadsBusy = false, rolesBusy = false, building = false, resuming = false;
  let sourcesOpen = false;
  let tools = null, planView = null, pauses = null, timeline = null, previewing = false, lastSummary = '';
  const lifecycle = new AbortController();
  const listen = (node, type, handler) => node.addEventListener(type, handler, { signal: lifecycle.signal });
  const ghosts = new Map(), prompted = new Set();
  const panel = createPanel({ afterSay: async () => { await polling.pollNow(true); } });
  const canEdit = () => !previewing && !session.signedOut;
  async function edit(change) {
    if (!canEdit()) throw new Error('Use Back to now before changing your house.');
    let result;
    for (const op of Array.isArray(change) ? change : [change]) {
      result = await request('edit', 'POST', { edit: op });
      const line = document.createElement('li'); line.textContent = plain(result.summary); el('editor-log').append(line);
    }
    [snapshot, sheets] = await Promise.all([request('state'), request('sheets')]);
    await renderScene(); timeline?.sync(currentBuild);
    lastSummary = result.summary;
    return result;
  }

  function setStatus(text) { el('editor-status').textContent = plain(text); }
  function syncBuildButton() {
    el('editor-build').disabled = previewing || !hooks.ready || !confirmed || uploadsBusy || rolesBusy || building || resuming || active(currentBuild);
    el('editor-check-step').hidden = previewing || currentBuild?.state !== 'paused' || !pauses?.dismissed();
    el('editor-resume').hidden = previewing || !['stopped', 'checkpoint'].includes(currentBuild?.state);
    el('editor-resume').disabled = !hooks.ready || building || resuming || session.signedOut;
  }
  function cost(value) { el('editor-cost').textContent = `$${Number(value || 0).toFixed(2)}`; }
  function countGhosts(plan) {
    if (!plan || typeof plan !== 'object') return 0;
    return (plan.state === 'ghost' ? 1 : 0) + Object.values(plan).reduce((n, value) =>
      n + (value && typeof value === 'object' ? countGhosts(value) : 0), 0);
  }
  function previewPlan() {
    const plan = structuredClone(snapshot.plan || emptyPlan());
    const savedPause = currentBuild?.pause;
    const pause = savedPause && pauses?.current()?.step === savedPause.step ? pauses.current() : savedPause;
    if (pause?.kind === 'lot_placement' && pause.transform) {
      const step = currentBuild.steps.find(s => s.id === pause.step);
      const owner = sheets.page_roles.find(row => row.source === step?.source && row.page === step?.page)?.building || 'house';
      const house = plan.buildings.find(b => b.id === owner);
      if (house) Object.assign(house, structuredClone(pause.transform));
    }
    // Outlines awaiting a person's approval live in events, never in saved
    // rounds. Give each one a temporary floor using the existing scene builder.
    for (const [stepId, event] of ghosts) {
      let outline = event.piece?.outline || event.piece?.lot;
      if (!outline?.length) continue;
      if (pause?.step === stepId && pause.registration && savedPause?.registration)
        outline = outline.map(p => applyRegistration(pause.registration, invertRegistration(savedPause.registration, p)));
      if (event.piece.lot) plan.site.lot = outline;
      const step = currentBuild?.steps.find(item => item.id === stepId);
      const owner = sheets.page_roles.find(row => row.source === step?.source && row.page === step?.page);
      const house = plan.buildings.find(item => item.id === (owner?.building || 'house'));
      const level = house?.levels.find(item => item.id === step?.level);
      const elevation = level?.elevation ?? Math.max(0, Number((step?.level || 'L1').slice(1)) - 1) * 9;
      plan.buildings.push({
        id: `editor-preview:${stepId}`, name: step?.label || 'Floor outline',
        position: event.piece.lot ? [0, 0] : house?.position || [0, 0],
        rotation: event.piece.lot ? 0 : house?.rotation || 0, base: event.piece.lot ? 0 : house?.base || 0,
        levels: [{ id: 'preview', name: 'Outline', elevation: elevation + .04, ceiling: 9, state: 'ghost' }],
        walls: [], openings: [], rooms: [{ id: 'outline', level: 'preview', polygon: outline }],
        roof: { sections: [] },
      });
    }
    return plan;
  }
  async function renderScene() {
    const plan = timeline?.preview() || previewPlan(), signature = JSON.stringify(plan);
    if (view && signature !== lastScene) {
      await view.rebuild(plan);
      view.scene.background?.set?.('#171e27');
      lastScene = signature;
    }
    renderedGhosts = countGhosts(plan);
    drawFloors();
    tools?.refresh();
    pauses?.sync();
    timeline?.sync(currentBuild);
  }
  function drawFloors() {
    tools?.drawFloors();
  }
  function drawTimeline(build) {
    timeline?.sync(build);
  }
  function drawPages() {
    const host = el('editor-pages'); host.replaceChildren();
    for (const [index, row] of rows.entries()) {
      const source = sheets.sources.find(source => source.id === row.source);
      const group = document.createElement('fieldset'); group.className = 'editor-page';
      const legend = document.createElement('legend'); legend.textContent = `${source?.filename || 'Drawing'} · page ${row.page}`;
      const thumbnail = document.createElement('img'); thumbnail.alt = `Page ${row.page} of ${source?.filename || 'drawing'}`;
      thumbnail.loading = 'lazy';
      const url = (window.chfBase ?? '../') + `api/house/editor/sheets/${encodeURIComponent(row.source)}/${row.page}.png`;
      thumbnail.src = window.chfAuthUrl ? window.chfAuthUrl(url) : url;
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
      roleLabel.append(select); levelLabel.append(input); group.append(legend, thumbnail, roleLabel, levelLabel);
      if (row.box) { const crop = document.createElement('p'); crop.textContent = 'One part of this page'; group.append(crop); }
      host.append(group);
    }
    el('editor-suggest-roles').disabled = rolesBusy || uploadsBusy || !sheets.sources.some(source =>
      source.kind === 'drawing' && !sheets.page_roles.some(row => row.source === source.id));
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
    el('editor-upload').hidden = !!snapshot.build && !sourcesOpen;
    const photos = sheets.sources.filter(source => source.kind === 'photo').length;
    el('editor-source-count').textContent = `${sheets.sources.filter(source => source.kind === 'drawing').reduce((n, source) => n + source.pages, 0)} sheets · ${photos} ${photos === 1 ? 'photo' : 'photos'}`;
    drawPages();
  }
  const polling = createPolling({
    async onState(state) {
      if (!state.build && currentBuild) {
        currentBuild = null; ghostBuild = null; ghosts.clear(); panel.reset(); drawTimeline(null);
        await loadSheets();
      }
      snapshot = state; cost(state.cost?.total);
      el('editor-upload').hidden = !!state.build && !sourcesOpen;
      syncBuildButton();
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
        : build.state === 'paused' ? 'Argyle is waiting for you'
          : build.state === 'done' ? 'House ready' : build.state === 'checkpoint' ? 'Spending checkpoint' : 'Build stopped');
      // Each new event batch can carry saved pieces, temporary outlines or
      // new costs. Read their owning state before rebuilding the scene.
      if (build.events?.length) {
        await polling.refreshState();
        sheets = await request('sheets');
      }
      if (build.state === 'checkpoint') {
        const detail = [...(build.events || [])].reverse().find(event => event.type === 'checkpoint')
          || { checkpoint: build.checkpoint || snapshot.cost?.blocking, total: build.total ?? snapshot.cost?.total };
        const key = `${build.id}:${detail.checkpoint}`;
        if (detail.checkpoint && !prompted.has(key)) {
          if (await checkpoint(detail)) {
            await request(`build/${build.id}/resume`, 'POST', {});
            prompted.add(key);
            build.state = 'running';
            setStatus('Argyle is building');
          } else {
            await request(`build/${build.id}/stop`, 'POST', {});
            build.state = 'stopped';
            setStatus('Build stopped');
          }
          syncBuildButton();
        }
      }
    },
    onTick: renderScene,
    onError(error) {
      if (error.signedOut) setStatus('Home Assistant signed the tab out');
      else if (!error.shown && !error.cancelled) setStatus(error.message || 'Connection paused. Trying again…');
    },
  });

  listen(el('editor-source-files'), 'change', async event => {
    if (!canEdit() || uploadsBusy) return;
    uploadsBusy = true; drawPages();
    try {
      const rejected = [];
      for (const file of event.target.files) {
        if (!['application/pdf', 'image/jpeg', 'image/png'].includes(file.type)) { rejected.push(`${file.name}: choose a PDF, JPEG or PNG file.`); continue; }
        el('editor-upload-status').textContent = plain(`Uploading ${file.name}…`);
        const data = new FormData(); data.append('kind', file.type === 'application/pdf' ? 'drawing' : 'photo'); data.append('file', file);
        try { await request('sources', 'POST', data, 'twin'); }
        catch (error) { rejected.push(`${file.name}: ${error.message}`); if (error.signedOut) break; }
      }
      el('editor-upload-status').textContent = rejected.length ? rejected.join('\n') : 'Check each page, then confirm.';
    } catch (error) { report(error); }
    finally {
      await loadSheets().catch(report);
      uploadsBusy = false; event.target.value = ''; drawPages();
    }
  });
  listen(el('editor-suggest-roles'), 'click', async () => {
    if (!canEdit()) return;
    rolesBusy = true; drawPages();
    try {
      // Suggestions remain local until the person confirms the complete list.
      for (const source of sheets.sources.filter(source => source.kind === 'drawing'
        && !sheets.page_roles.some(row => row.source === source.id))) {
        const result = await request('sheets/suggest', 'POST', { source: source.id });
        const suggestedPages = new Set(result.rows.map(row => row.page));
        rows = rows.filter(row => row.source !== source.id || !suggestedPages.has(row.page)).concat(result.rows);
      }
      confirmed = false;
      el('editor-upload-status').textContent = 'These are suggestions. Check the roles and level names, then confirm.';
    } catch (error) { report(error); }
    finally { rolesBusy = false; drawPages(); await polling.pollNow(true).catch(report); }
  });
  listen(el('editor-confirm-roles'), 'click', async () => {
    if (!canEdit()) return;
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
  listen(el('editor-build'), 'click', async () => {
    if (!canEdit() || building || resuming || active(currentBuild) || !confirmed) return;
    building = true; syncBuildButton();
    try {
      if (snapshot.plan?.buildings?.length && !await window.promptConfirm('Build your house again?',
        'This reads the drawings again and adds to the running cost. Continue?', 'Build again', 'Cancel')) return;
      const result = await request('build', 'POST', {
        building: { id: 'house', name: 'Main house' },
        photos: sheets.sources.filter(source => source.kind === 'photo').map(source => source.id),
      });
      el('editor-upload').hidden = true;
      sourcesOpen = false;
      await polling.follow(result.id);
    } catch (error) { report(error); }
    finally { building = false; syncBuildButton(); }
  });
  listen(el('editor-resume'), 'click', async () => {
    if (!canEdit() || building || resuming || !['stopped', 'checkpoint'].includes(currentBuild?.state)) return;
    const id = currentBuild.id;
    resuming = true; syncBuildButton();
    try {
      // Recheck spending before resuming cached work, including a build
      // stopped at a checkpoint in an earlier tab or add-on session.
      await polling.refreshState();
      if (snapshot.cost?.blocking && !await checkpoint({ checkpoint: snapshot.cost.blocking, total: snapshot.cost.total })) return;
      await request(`build/${encodeURIComponent(id)}/resume`, 'POST', {});
      await polling.follow(id);
    } catch (error) { report(error); }
    finally { resuming = false; syncBuildButton(); }
  });
  listen(el('editor-manage-sources'), 'click', () => {
    el('editor-upload').hidden = !el('editor-upload').hidden;
    sourcesOpen = !el('editor-upload').hidden;
    el('editor-menu').open = false;
    if (!el('editor-upload').hidden) el('editor-source-files').focus();
  });
  listen(el('editor-check-step'), 'click', () => {
    tools?.select(null); planView?.leavePlan(); pauses?.show();
  });

  if (new URLSearchParams(location.search).get('test') === '1') Object.assign(hooks, {
    ghostCount: () => renderedGhosts, build: () => currentBuild,
    pollNow: () => polling.pollNow(true).catch(report), idleInterval, buildInterval,
    followBuild: id => { polling.follow(id).catch(report); },
    currentInterval: polling.currentInterval, signOutNotices: () => session.notices, polling: polling.polling,
    isEmpty: () => sheets.sources.length === 0,
  });
  const signedOut = () => { polling.stop(); setStatus('Home Assistant signed the tab out'); };
  const foreground = () => { if (!document.hidden) polling.resume().catch(report); else polling.stop(); };
  window.addEventListener('editor-signed-out', signedOut);
  document.addEventListener('visibilitychange', foreground);
  window.addEventListener('focus', foreground);
  // A successful answer in this tab should be reflected immediately, even
  // when the paused build is on its one-minute idle cadence.
  const originalFetch = window.fetch;
  const watchAnswers = async (input, init) => {
    const response = await originalFetch(input, init);
    const url = typeof input === 'string' ? input : input.url;
    if (response.ok && /\/api\/house\/editor\/build\/[^/]+\/(answer|reread)$/.test(url)
        && (init?.method || input?.method || 'GET').toUpperCase() === 'POST' && currentBuild) {
      polling.follow(currentBuild.id).catch(report);
    }
    return response;
  };
  window.fetch = watchAnswers;
  window.addEventListener('pagehide', () => {
    polling.stop(); view?.dispose(); lifecycle.abort(); panel.dispose();
    window.removeEventListener('editor-signed-out', signedOut);
    document.removeEventListener('visibilitychange', foreground);
    window.removeEventListener('focus', foreground);
    if (window.fetch === watchAnswers) window.fetch = originalFetch;
  }, { once: true });
  const restore = event => {
    if (event.persisted) { window.removeEventListener('pageshow', restore); boot(); }
  };
  window.addEventListener('pageshow', restore);
  try {
    await loadSheets();
    const kit = await request('kit/modern_farmhouse', 'GET', undefined, 'twin');
    view = await mountTwin(el('editor-scene'), { plan: emptyPlan(), kit, preserveCamera: true });
    const onInteract = () => { pauses?.dismiss(); syncBuildButton(); };
    tools = createSceneTools({ view, getPlan: () => timeline?.preview() || snapshot.plan, getSheets: () => sheets,
      edit, panel, canEdit, signal: lifecycle.signal, onInteract });
    planView = createPlanView({ view, tools, edit, canEdit, signal: lifecycle.signal, onInteract });
    pauses = createPauses({ view, getBuild: () => currentBuild, getGhost: step => ghosts.get(step),
      getSheets: () => sheets, refresh: () => polling.pollNow(true), preview: () => renderScene().catch(report),
      visibilityChanged: syncBuildButton, canEdit, signal: lifecycle.signal });
    tools.delegate({
      pointerDown: event => pauses.pointerDown(event) || planView.pointerDown(event),
      pointerMove: event => pauses.pointerMove(event),
      pointerUp: (event, cancel) => pauses.pointerUp(event, cancel),
      floorChanged: planView.floorChanged, leavePlan: planView.leavePlan, cancel: planView.cancel,
    });
    timeline = createTimeline({ getState: () => snapshot, render: renderScene, signal: lifecycle.signal,
      log(summary) { const line = document.createElement('li'); line.textContent = summary; el('editor-log').append(line); lastSummary = summary; },
      onPreview(value) {
        previewing = value; tools.select(null); pauses.dismiss(); panel.readOnly(value);
        tools.refreshCard(); syncBuildButton();
        for (const id of ['rail-move', 'rail-rotate', 'plan-add-wall', 'plan-add-door', 'plan-add-window', 'editor-confirm-roles', 'editor-suggest-roles', 'editor-source-files']) el(id).disabled = value;
        if (!value) { drawPages(); pauses.resume(); }
      },
    });
    if (new URLSearchParams(location.search).get('test') === '1') Object.assign(hooks, {
      clickPiece: (pieceId, buildingId) => { onInteract(); tools.select({ pieceId, buildingId }); },
      selected: tools.selected, lastSummary: () => lastSummary,
      dragPiece: tools.dragPiece, rotateBuilding: tools.rotateBuilding,
      cameraKind: view.cameraKind, screenOfFloor: view.screenOfFloor,
      screenOfGhostUV: pauses.screenOfGhostUV, screenOfSheetUV: pauses.screenOfSheetUV,
      lastAnswer: pauses.lastAnswer, scrubTo: timeline.scrubTo, roundCount: timeline.roundCount,
      pause: pauses.current, sheetMaster: pauses.sheetMaster, pinCheck: pauses.pinCheck,
      buildingCentre: tools.buildingCentre, clearLastAnswer: pauses.clearLastAnswer, dragPauseGhost: pauses.dragPauseGhost,
    });
    // The editor uses the mockup's dark work surface; the shared preview keeps
    // its own daylight sky, with the same renderer and lighting.
    view.scene.background?.set?.('#171e27');
    await polling.resume();
    view.scene.background?.set?.('#171e27');
    hooks.ready = true;
    syncBuildButton();
  } catch (error) {
    setStatus(error.signedOut ? 'Home Assistant signed the tab out'
      : error.status === 401 || error.status === 403 ? 'Sign in to edit your house' : 'Could not open the house. Reload to try again.');
    if (error.status !== 401 && error.status !== 403) report(error);
  }
}
