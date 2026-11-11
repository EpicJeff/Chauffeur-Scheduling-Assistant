import { mountTwin } from '../twin_view.js';
import { runDirector } from '../twin_director.js';
import { request, createPolling, idleInterval, buildInterval, checkpoint, plain, report, active, session } from './api.js';
import * as api from './api.js';
import { createPanel } from './panel.js';
import { createSceneTools } from './scene_tools.js';
import { createDraw } from './draw.js';
import { createHistory } from './history.js';
import { createPauses, applyRegistration, invertRegistration } from './pauses.js';
import { createTimeline } from './timeline.js';
import { createPlace } from './place.js';
import { createRoofTools } from './roof_tools.js';
import { createLotTools, streetView, streetSegment } from './lot_tools.js';
import { createLibrary } from './library.js';
import { createFlags } from './flags.js';
import { createDevicePlacement } from './device_placement.js';
import { createBuildGhosts } from './build_ghosts.js';
import { createStatusChip } from './status_chip.js';

const el = id => document.getElementById(id);
const emptyPlan = () => ({ schema: 'chauffeur.twin.plan/2', units: 'ft', buildings: [], site: {}, materials: {} });

export async function boot() {
  const hooks = window.__editor = { ready: false };
  let view = null, snapshot = { plan: null, rounds: [], cost: {}, build: null };
  let sheets = { sources: [], page_roles: [] };
  let currentBuild = null, ghostBuild = null, renderedGhosts = 0, lastScene = '';
  let resuming = false, stopping = false;
  let menuBusy = false, directing = false, downloading = false, advancedBase = null;
  let tools = null, draw = null, history = null, pauses = null, timeline = null, place = null, library = null, previewing = false, lastSummary = '';
  let roofTools = null, lot = null, flags = null, devices = null, aimed = false;
  let buildGhosts = null;
  const statusChip = createStatusChip(el('editor-chip')), seenBuildRounds = new Set();
  const lifecycle = new AbortController();
  const listen = (node, type, handler) => node.addEventListener(type, handler, { signal: lifecycle.signal });
  const ghosts = new Map(), prompted = new Set();
  const panel = createPanel({ afterSay: async () => { await polling.pollNow(true); },
    acceptPause: async () => {
      if (currentBuild?.state !== 'paused' || !currentBuild.pause) return false;
      if (currentBuild.pause.kind === 'draft') { pauses?.show(); return true; }
      await pauses?.accept(); return true;
    } });
  const canEdit = () => !previewing && !session.signedOut && !menuBusy && !directing;
  const currentRound = () => [...snapshot.rounds].reverse().find(row => !row.stale)?.id ?? null;
  function summary(text) {
    lastSummary = text;
    panel.message(text);
  }
  const edit = change => history.perform(() => editNow(change));
  const applyOp = operation => history.perform(() => applyOpNow(operation));
  async function editNow(change) {
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
  // `saved` runs as soon as the round is saved, before the scene rebuild (the
  // roof tools select the new piece then). `settle: false` returns once the
  // round is saved and read back; the scene rebuild follows. The lot tools
  // already show the building where it landed.
  async function applyOpNow(operation, { saved, settle = true } = {}) {
    if (!canEdit()) throw new Error('Use Back to now before changing your house.');
    const result = await api.op(operation);
    snapshot = { ...snapshot, plan: result.plan, model: result.model };
    saved?.(result);
    // The card shows the saved change at once (a device reads Placed); the
    // scene rebuild below can take seconds on a large house.
    tools?.refreshCard();
    const line = document.createElement('li'); line.textContent = plain(result.words); el('editor-log').append(line);
    lastSummary = result.words;
    if (!settle) {
      await polling.refreshState(); timeline?.sync(currentBuild);
      renderScene().catch(report);
      return result;
    }
    await renderScene();
    await polling.refreshState(); timeline?.sync(currentBuild);
    return result;
  }

  function setStatus(text) { el('editor-status').textContent = plain(text); }
  function syncBuildButton() {
    syncChip();
    history?.sync();
    // Reaching ready requires successful parent-only editor API requests.
    el('menu-record').hidden = !hooks.ready || session.signedOut;
    el('menu-record').disabled = !hooks.ready || session.signedOut || downloading;
    place?.sync(sheets, { ...snapshot, buildState: currentBuild });
    el('editor-check-step').hidden = previewing || currentBuild?.state !== 'paused' || !pauses?.dismissed();
    el('editor-resume').hidden = previewing || !['stopped', 'checkpoint'].includes(currentBuild?.state);
    el('editor-resume').disabled = !canEdit() || !hooks.ready || resuming;
    el('editor-stop').hidden = !active(currentBuild);
    el('editor-stop').disabled = session.signedOut || stopping;
    const busy = !canEdit() || !hooks.ready || resuming || active(currentBuild);
    for (const id of ['menu-director', 'menu-advanced', 'menu-start-over', 'menu-reset-spend']) el(id).disabled = busy;
    el('menu-start-over').disabled = !canEdit() || !hooks.ready || resuming
      || currentBuild?.state === 'running';
    el('menu-director').disabled ||= !snapshot.plan?.buildings?.length;
    el('advanced-save').disabled = busy;
    panel.readOnly(!canEdit());
  }
  function syncChip() {
    statusChip.update({ state: currentBuild?.state, pause: currentBuild?.pause,
      cost: snapshot.cost?.total || 0, estimate: currentBuild?.state === 'running' ? snapshot.cost?.estimate : null });
  }
  function countGhosts(plan) {
    if (!plan || typeof plan !== 'object') return 0;
    return (plan.state === 'ghost' ? 1 : 0) + Object.values(plan).reduce((n, value) =>
      n + (value && typeof value === 'object' ? countGhosts(value) : 0), 0);
  }
  function previewPlan() {
    const plan = structuredClone(snapshot.plan || emptyPlan());
    const savedPause = currentBuild?.pause;
    const pause = savedPause && pauses?.current()?.step === savedPause.step ? pauses.current() : savedPause;
    if (pause?.kind === 'lot_placement' && pause.transform && currentBuild.part !== 'lot') {
      const step = currentBuild.steps.find(s => s.id === pause.step);
      const owner = step?.id === 'fit' ? currentBuild.part
        : sheets.page_roles.find(row => row.source === step?.source && row.page === step?.page)?.building || currentBuild.part || 'house';
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
      const house = plan.buildings.find(item => item.id === (owner?.building || currentBuild?.part || 'house'));
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
    if (tools?.dragging() || lot?.dragging()) return;
    const plan = timeline?.preview() || previewPlan(), signature = JSON.stringify(plan);
    const changed = signature !== lastScene;
    if (view && changed) {
      await view.rebuild(plan);
      view.scene.background?.set?.('#171e27');
      lastScene = signature;
      // The first view of the house: from the street, past the yard's plants (M3).
      const eye = !aimed && streetView(plan, streetSegment(sheets.place, plan));
      if (eye) { aimed = true; view.aim(eye.position, eye.target); }
    }
    renderedGhosts = countGhosts(plan);
    buildGhosts?.sync();
    for (const round of snapshot.rounds || []) {
      if (seenBuildRounds.has(round.id)) continue;
      seenBuildRounds.add(round.id);
      buildGhosts?.settle(round);
    }
    drawFloors();
    tools?.refresh();
    library?.refresh();
    devices?.refresh();
    flags?.refresh();
    pauses?.sync();
    timeline?.sync(currentBuild);
    // Read the Home Assistant link beside the scene, never before it: a slow or
    // unreachable Home Assistant must not hold the editor's start, a poll or a save.
    tools?.refreshLink(changed).then(() => devices?.refresh()).catch(report);
  }
  function drawFloors() {
    tools?.drawFloors();
  }
  function drawTimeline(build) {
    timeline?.sync(build);
  }
  async function loadSheets() {
    sheets = await request('sheets');
    const photos = sheets.sources.filter(source => source.kind === 'photo').length;
    el('editor-source-count').textContent = `${sheets.sources.filter(source => source.kind === 'drawing').reduce((n, source) => n + source.pages, 0)} sheets \u00b7 ${photos} ${photos === 1 ? 'photo' : 'photos'}`;
    place?.sync(sheets, { ...snapshot, buildState: currentBuild });
  }
  const polling = createPolling({
    async onState(state) {
      if (!state.build && currentBuild) {
        currentBuild = null; ghostBuild = null; ghosts.clear(); buildGhosts?.clear(); panel.reset(); drawTimeline(null);
        await loadSheets();
      }
      snapshot = state;
      syncBuildButton();
      if (!currentBuild) setStatus(sheets.page_roles.some(row => ['floor', 'plot'].includes(row.role)) ? 'Ready to build' : 'Add drawings to begin');
    },
    async onBuild(build) {
      if (ghostBuild !== build.id) {
        ghosts.clear(); buildGhosts?.clear(); ghostBuild = build.id;
        seenBuildRounds.clear();
        for (const round of snapshot.rounds || []) seenBuildRounds.add(round.id);
      }
      // Yield once per new question, while allowing uploads if the person
      // reopens Your place during the same pause.
      if (['paused', 'checkpoint'].includes(build.state) && place?.isOpen()
        && (currentBuild?.id !== build.id || currentBuild?.state !== build.state
          || currentBuild?.pause?.step !== build.pause?.step)) place.close();
      const showPieces = build.state === 'running' || currentBuild?.state === 'running' || buildGhosts?.count() > 0;
      currentBuild = build;
      for (const event of build.events || []) {
        if (event.type === 'stream_reset') buildGhosts?.clear(event.step);
        if (event.type === 'piece' && showPieces && build.steps.find(s => s.id === event.step)?.status !== 'done')
          buildGhosts?.add({ ...event, building: event.building || build.part || 'house' });
        if (event.type === 'ghost') ghosts.set(event.step, event);
        if (event.type === 'settled') ghosts.delete(event.step);
      }
      if (['paused', 'stopped', 'failed'].includes(build.state)) {
        for (const [step, event] of ghosts) {
          if (event.why === 'First look at the outline while the drawings are read.') ghosts.delete(step);
        }
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
        await loadSheets();
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

  place = createPlace({ request, getSheets: () => sheets,
    reload: async () => { await polling.pollNow(true); await loadSheets(); },
    follow: id => polling.follow(id), canEdit: () => canEdit() && !resuming && !stopping, panel, lotTools: () => lot });

  listen(el('editor-resume'), 'click', async () => {
    if (!canEdit() || resuming || !['stopped', 'checkpoint'].includes(currentBuild?.state)) return;
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
  listen(el('editor-stop'), 'click', async () => {
    if (session.signedOut || stopping || !active(currentBuild)) return;
    stopping = true; syncBuildButton();
    try {
      await request(`build/${encodeURIComponent(currentBuild.id)}/stop`, 'POST', {});
      await polling.follow(currentBuild.id);
    } catch (error) { report(error); }
    finally { stopping = false; syncBuildButton(); }
  });
  listen(el('editor-manage-sources'), 'click', () => place.open());
  listen(el('menu-upload'), 'click', () => place.open());
  listen(el('menu-record'), 'click', async () => {
    if (!hooks.ready || session.signedOut || downloading) return;
    downloading = true; syncBuildButton();
    try {
      const record = await request('record');
      const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url; link.download = `house-build-record-${new Date().toISOString().slice(0, 10)}.json`;
      try { document.body.append(link); link.click(); }
      finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
      el('editor-menu').open = false;
    } catch (error) { report(error); }
    finally { downloading = false; syncBuildButton(); }
  });
  listen(el('menu-director'), 'click', async () => {
    if (!canEdit() || active(currentBuild) || !view || !snapshot.plan?.buildings?.length) return;
    directing = true; syncBuildButton(); timeline?.sync(); el('editor-menu').open = false;
    panel.message('Starting art director. Comparing four views with your photos, up to five rounds.');
    try {
      await polling.pollNow(true);
      await runDirector(view, {
        base: currentRound(), signal: lifecycle.signal,
        critique: body => request('critique', 'POST', body, 'twin'),
        log: text => panel.message(text),
        onRound: async () => { await polling.pollNow(true); },
      });
    } catch (error) {
      panel.message(error.cancelled ? 'Art director stopped at the spending checkpoint.' : error.message);
      report(error);
    } finally {
      directing = false;
      await polling.pollNow(true).catch(report);
      syncBuildButton(); timeline?.sync();
    }
  });
  listen(el('menu-advanced'), 'click', async () => {
    if (!canEdit() || active(currentBuild)) return;
    menuBusy = true; syncBuildButton(); el('editor-menu').open = false;
    try {
      await polling.pollNow(true);
      el('advanced-plan').value = JSON.stringify(snapshot.plan || emptyPlan(), null, 2);
      el('advanced-reason').value = ''; advancedBase = currentRound();
      el('editor-advanced').hidden = false;
      el('advanced-plan').focus();
    } catch (error) { report(error); }
    finally { menuBusy = false; syncBuildButton(); }
  });
  listen(el('advanced-close'), 'click', () => {
    el('editor-advanced').hidden = true;
    el('editor-menu').querySelector('summary').focus();
  });
  listen(el('advanced-form'), 'submit', async event => {
    event.preventDefault();
    if (!canEdit() || active(currentBuild)) return;
    const reason = el('advanced-reason').value.trim();
    if (!reason) { report(new Error('Give a reason for this hand edit before saving.')); return; }
    let plan;
    try { plan = JSON.parse(el('advanced-plan').value); }
    catch { report(new Error('The plan must be valid JSON.')); return; }
    menuBusy = true; syncBuildButton();
    try {
      await request('plan', 'PUT', { plan, reason, base: advancedBase }, 'twin');
      await polling.pollNow(true);
      advancedBase = currentRound();
      el('advanced-plan').value = JSON.stringify(snapshot.plan, null, 2);
      el('advanced-reason').value = '';
      summary('Plan saved. Your reason was recorded with each fix.');
    } catch (error) {
      if (error.status === 409) {
        try {
          if (await window.promptConfirm('Plan changed elsewhere',
            'Reload it? Your unsaved text will be replaced.', 'Reload', 'Keep editing')) {
            await polling.pollNow(true);
            advancedBase = currentRound();
            el('advanced-plan').value = JSON.stringify(snapshot.plan || emptyPlan(), null, 2);
          }
        } catch (failure) { report(failure); }
      } else report(error);
    } finally { menuBusy = false; syncBuildButton(); }
  });
  listen(el('menu-reset-spend'), 'click', async () => {
    if (!canEdit() || active(currentBuild)) return;
    menuBusy = true; syncBuildButton(); el('editor-menu').open = false;
    try {
      await polling.pollNow(true);
      const confirm = await window.promptInput('Reset spend total?',
        `The current total is $${Number(snapshot.cost?.total || 0).toFixed(2)}. Type reset to clear it. This cannot be undone.`,
        { placeholder: 'reset', okText: 'Reset' });
      if (confirm === null) return;
      if (confirm !== 'reset') { report(new Error('Type reset to reset the spend total.')); return; }
      await request('cost/reset', 'POST', { confirm });
      await polling.pollNow(true);
      summary('Spend total reset.');
    } catch (error) { report(error); }
    finally { menuBusy = false; syncBuildButton(); }
  });
  listen(el('menu-start-over'), 'click', async () => {
    if (!canEdit() || currentBuild?.state === 'running') return;
    menuBusy = true; syncBuildButton(); el('editor-menu').open = false;
    try {
      if (!await window.promptConfirm('Start over?',
        'This clears the house, its history and the uploaded drawings and photos. The spend total stays.',
        'Start over', 'Keep it')) return;
      await request('start-over', 'POST', {});
      currentBuild = null; ghostBuild = null; ghosts.clear(); prompted.clear();
      panel.reset(); tools?.select(null); pauses?.dismiss(); draw?.cancel(); history?.clear();
      el('editor-advanced').hidden = true; advancedBase = null;
      await polling.pollNow(true);
      await loadSheets();
      place.open();
      await timeline?.now();
      summary('House cleared. The spend total stays.');
      setStatus('Add drawings to begin');
    } catch (error) { report(error); }
    finally { menuBusy = false; syncBuildButton(); }
  });
  listen(el('editor-check-step'), 'click', () => {
    tools?.select(null); draw?.cancel(); pauses?.show();
  });

  if (new URLSearchParams(location.search).get('test') === '1') Object.assign(hooks, {
    ghostCount: () => renderedGhosts, build: () => currentBuild,
    pollNow: () => polling.pollNow(true).catch(report), idleInterval, buildInterval,
    followBuild: id => { polling.follow(id).catch(report); },
    currentInterval: polling.currentInterval, signOutNotices: () => session.notices, polling: polling.polling,
    isEmpty: () => !snapshot.plan?.buildings?.length && sheets.sources.length === 0,
  });
  const signedOut = () => { polling.stop(); syncBuildButton(); setStatus('Home Assistant signed the tab out'); };
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
    polling.stop(); buildGhosts?.clear(); view?.dispose(); lifecycle.abort(); panel.dispose();
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
    buildGhosts = createBuildGhosts(view);
    if (new URLSearchParams(location.search).get('test') === '1') hooks.buildGhosts = buildGhosts;
    view.showAnchors = true;
    const onInteract = () => { pauses?.dismiss(); syncBuildButton(); };
    history = createHistory({ getRound: currentRound, getBuild: () => currentBuild,
      canEdit, signal: lifecycle.signal, latest: () => polling.refreshState(),
      refresh: async () => { draw?.cancel(); await polling.refreshState(); await renderScene(); } });
    tools = createSceneTools({ view, getPlan: () => timeline?.preview() || snapshot.plan, getModel: () => snapshot.model, getKit: () => kit, getSheets: () => sheets,
      pickSite: (x, y) => library?.pickSite(x, y), pickMaterial: surface => library?.pick(surface),
      edit, op: applyOp, panel, canEdit, signal: lifecycle.signal, onInteract, api, addDormer: () => roofTools?.addDormer() });
    library = createLibrary({ view, kit, getPlan: () => timeline?.preview() || snapshot.plan, tools,
      op: applyOp, canEdit, signal: lifecycle.signal, onInteract });
    flags = createFlags({ view, getModel: () => snapshot.model, getPlan: () => snapshot.plan,
      tools, panel, op: applyOp, canEdit, signal: lifecycle.signal, onInteract });
    draw = createDraw({ view, tools, getPlan: () => snapshot.plan, op: operation => applyOpNow(operation),
      gesture: history.perform, canEdit, panel, signal: lifecycle.signal, onInteract });
    roofTools = createRoofTools({ view, tools, getPlan: () => snapshot.plan,
      op: (operation, options) => history.perform(() => applyOpNow(operation, options)),
      canEdit, panel, signal: lifecycle.signal, onInteract, cancelDrawing: draw.cancel });
    pauses = createPauses({ view, getBuild: () => currentBuild, getGhost: step => ghosts.get(step),
      getSheets: () => sheets, refresh: () => polling.pollNow(true), preview: () => renderScene().catch(report),
      visibilityChanged: syncBuildButton, canEdit, signal: lifecycle.signal });
    lot = createLotTools({ view, getPlan: () => timeline?.preview() || snapshot.plan, getSheets: () => sheets,
      getSelection: tools.selection, select: tools.select, pauses, signal: lifecycle.signal,
      canEdit: () => canEdit() && (!active(currentBuild) || !!pauses.lotPlacement()),
      op: operations => history.perform(async () => { for (const operation of operations) await applyOpNow(operation, { settle: false }); }),
      // The lot card frees itself once the place rows are fresh; the scene
      // rebuild (seconds for a refitted house) follows on the poll's tick.
      reload: async () => { await loadSheets(); polling.pollNow(true).catch(report); } });
    devices = createDevicePlacement({ view, tools, library, getPlan: () => timeline?.preview() || snapshot.plan,
      op: applyOp, canEdit, signal: lifecycle.signal,
      prepare() { onInteract(); roofTools.cancel(); draw.cancel(); } });
    view.live = { draw: devices.draw, stop: devices.stop };
    tools.delegate({
      pick: flags.pick,
      pointerDown: event => devices.pointerDown(event) || lot.pointerDown(event) || pauses.pointerDown(event) || roofTools.pointerDown(event) || draw.pointerDown(event) || library.pointerDown(event),
      pointerMove: event => lot.pointerMove(event) || pauses.pointerMove(event) || roofTools.pointerMove(event) || draw.pointerMove(event) || library.pointerMove(event),
      pointerUp: (event, cancel) => devices.pointerUp(event, cancel) || lot.pointerUp(event, cancel) || pauses.pointerUp(event, cancel) || roofTools.pointerUp(event, cancel) || draw.pointerUp(event, cancel) || library.pointerUp(event, cancel),
      floorChanged() { devices.cancel(); roofTools.cancel(); draw.floorChanged(); }, cancel() { devices.cancel(); roofTools.cancel(); draw.cancel(); },
    });
    timeline = createTimeline({ getState: () => snapshot, render: renderScene, signal: lifecycle.signal,
      canScrub: () => !menuBusy && !directing,
      log(summary) { const line = document.createElement('li'); line.textContent = summary; el('editor-log').append(line); lastSummary = summary; },
      onPreview(value) {
        previewing = value; devices.cancel(); roofTools.cancel(); draw.cancel(); tools.select(null); pauses.dismiss(); panel.readOnly(value);
        tools.refreshCard(); syncBuildButton();
        for (const id of ['move', 'rotate', 'draw-room', 'draw-wall', 'split-room', 'add-door', 'add-window', 'add-anchor', 'add-level', 'delete', 'roof']) el(`rail-${id}`).disabled = value;
        if (!value) pauses.resume();
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
    if (new URLSearchParams(location.search).get('test') === '1') window.__twinEditor = {
      haLink: tools.haLink,
      selection: tools.selection, handles: () => [...tools.handles(), ...lot.handles()], op: applyOp,
      underlay: lot.underlay, lotHandles: lot.lotHandles, lotSuggestions: lot.lotSuggestions,
      flags: flags.flags, proposals: flags.proposals,
      get lastDragFrameMs() { return tools.lastDragFrameMs; },
    };
    // The editor uses the mockup's dark work surface; the shared preview keeps
    // its own daylight sky, with the same renderer and lighting.
    view.scene.background?.set?.('#171e27');
    await polling.resume();
    view.scene.background?.set?.('#171e27');
    hooks.ready = true;
    syncBuildButton();
    if (!sheets.place?.buildings?.length && !sheets.sources.some(source => source.part === 'lot')) place.open();
  } catch (error) {
    setStatus(error.signedOut ? 'Home Assistant signed the tab out'
      : error.status === 401 || error.status === 403 ? 'Sign in to edit your house' : 'Could not open the house. Reload to try again.');
    if (error.status !== 401 && error.status !== 403) report(error);
  }
}
