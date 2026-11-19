import { mountTwin } from '../twin_view.js';
import { mountLighting } from './lighting.js';
import { runDirector } from '../twin_director.js';
import { request, createPolling, idleInterval, buildInterval, checkpoint, plain, report, active, session } from './api.js';
import * as api from './api.js';
import { createPanel } from './panel.js';
import { createSceneTools } from './scene_tools.js';
import { createDraw } from './draw.js';
import { createHistory } from './history.js';
import { mountHouses } from './houses.js';
import { createPauses, applyRegistration, invertRegistration } from './pauses.js';
import { createTimeline } from './timeline.js';
import { createPlace } from './place.js';
import { createRoofTools } from './roof_tools.js';
import { createLotTools, streetView, streetSegment } from './lot_tools.js';
import { createTerrainTools } from './terrain_tools.js';
import { createLibrary } from './library.js';
import { createFlags } from './flags.js';
import { createDevicePlacement } from './device_placement.js';
import { createBuildGhosts } from './build_ghosts.js';
import { createStatusChip } from './status_chip.js';
import { createSteps } from './steps.js';
import { createChecks } from './checks.js';
import { createEditQueue } from './edit_queue.js';
import { applyLocal, LocalMissing } from './local_ops.js';
import { mountIcons } from './icons.js';
import { createDock } from './dock.js';

const el = id => document.getElementById(id);
const STREAM_ONLY = new Set(['piece', 'stage', 'stream_reset', 'log']);
const emptyPlan = () => ({ schema: 'chauffeur.twin.plan/2', units: 'ft', buildings: [], site: {}, materials: {} });

export async function boot() {
  const hooks = window.__editor = { ready: false };
  let view = null, snapshot = { plan: null, rounds: [], cost: {}, build: null };
  let sheets = { sources: [], page_roles: [] };
  let currentBuild = null, ghostBuild = null, renderedGhosts = 0, lastScene = '';
  let resuming = false, stopping = false;
  let menuBusy = false, directing = false, downloading = false, advancedBase = null;
  let tools = null, draw = null, history = null, pauses = null, timeline = null, place = null, library = null, previewing = false, lastSummary = '';
  let roofTools = null, lot = null, flags = null, devices = null, terrain = null, aimed = false;
  let buildGhosts = null, checks = null, houses = null, drawingStarted = false;
  const statusChip = createStatusChip(el('editor-chip')), seenBuildRounds = new Set();
  const lifecycle = new AbortController();
  const dock = createDock({ host: el('editor-dock') });
  lifecycle.signal.addEventListener('abort', () => dock.dispose(), { once: true });
  const listen = (node, type, handler, options = {}) => node.addEventListener(type, handler, { ...options, signal: lifecycle.signal });
  const ghosts = new Map(), prompted = new Set();
  const panel = createPanel({ dock, afterSay: async () => { await polling.pollNow(true); },
    acceptPause: async () => {
      if (currentBuild?.state !== 'paused' || !currentBuild.pause) return false;
      if (currentBuild.pause.kind === 'draft') { pauses?.show(); return true; }
      await pauses?.accept(); return true;
    } });
  const canEdit = () => !previewing && !session.signedOut && !menuBusy && !directing;
  const stepState = () => ({ model: snapshot.model, sheets, build: currentBuild });
  const steps = createSteps(el('editor-steps'), { state: stepState(), onOpen(name) {
    if (name === 'Check it') { place?.close(false); checks?.show(); }
    else { checks?.dismiss(false); place?.open(name); }
  } });
  // The generation strip is absent in manual editing. Keep every setup step
  // reachable from Your place using the same builder and opening path.
  const placeSteps = createSteps(el('place-steps'), { state: stepState(), onOpen: name => steps.open(name) });
  // Keep the panel's check queue and its handler; only its display home moves.
  const checkCount = el('editor-flag-count');
  if (checkCount) el('editor-statusbar').append(checkCount);
  mountIcons(el('editor-toolbar'));
  const header = el('editor-top'), toolbar = el('editor-toolbar'), statusbar = el('editor-statusbar');
  function sizeShell() {
    const style = document.querySelector('.editor-shell').style;
    style.setProperty('--editor-header-bottom', `${header.getBoundingClientRect().bottom + 8}px`);
    style.setProperty('--editor-toolbar-bottom', `${toolbar.getBoundingClientRect().bottom}px`);
    style.setProperty('--editor-status-height', `${statusbar.getBoundingClientRect().height}px`);
    style.setProperty('--editor-rail-right', '16px');
  }
  // Menu panels are fixed so horizontal toolbar scrolling never clips them.
  for (const menu of document.querySelectorAll('.editor-toolbar-menu')) {
    listen(menu, 'toggle', () => {
      if (!menu.open) return;
      for (const other of document.querySelectorAll('.editor-toolbar-menu')) if (other !== menu) other.open = false;
      const box = menu.getBoundingClientRect();
      const panel = menu.querySelector('div, nav');
      if (panel) panel.style.left = `${Math.max(8, Math.min(box.left, window.innerWidth - 290))}px`;
    });
    listen(menu, 'click', event => {
      const action = event.target.closest?.('button, a');
      if (action && !action.disabled) menu.open = false;
    });
  }
  listen(document, 'pointerdown', event => {
    for (const menu of document.querySelectorAll('.editor-toolbar-menu')) if (menu.open && !menu.contains(event.target)) menu.open = false;
  });
  listen(document, 'keydown', event => {
    if (event.key !== 'Escape' || event.defaultPrevented) return;
    const menu = [...document.querySelectorAll('.editor-toolbar-menu')].find(menu => menu.open);
    if (!menu) return;
    menu.open = false; menu.querySelector('summary')?.focus(); event.preventDefault(); event.stopImmediatePropagation();
  }, { capture: true });
  listen(el('editor-floor-add'), 'click', () => el('rail-add-level').click());
  listen(el('properties-your-place'), 'click', () => steps.open('Your files'));
  listen(el('properties-house-materials'), 'click', () => {
    const building = tools?.floor()?.building || shownPlan()?.buildings?.[0];
    if (building) tools.select({ pieceId: building.id, buildingId: building.id });
    else steps.open('Your files');
  });
  // Existing controls remain the owners of these two layer actions.
  listen(el('layer-sheet'), 'click', () => el('rail-sheet').click());
  dock.onResize(sizeShell);
  if (typeof ResizeObserver !== 'undefined') {
    const observer = new ResizeObserver(sizeShell);
    observer.observe(header);
    observer.observe(statusbar);
    lifecycle.signal.addEventListener('abort', () => observer.disconnect(), { once: true });
  }
  const currentRound = () => [...snapshot.rounds].reverse().find(row => !row.stale)?.id ?? null;
  const roundOf = state => state.current_round ?? state.round ?? [...(state.rounds || [])].reverse().find(row => !row.stale)?.id ?? null;
  const opInfo = new WeakMap();
  let pushing = false, optimistic = 0, sceneWork = Promise.resolve(), refusedSelection = null, queueSignedOut = false, rollback = false;
  const queueOptions = {
    async send(operation) {
      const info = opInfo.get(operation);
      await info.ready;
      info.before = currentRound();
      let result;
      try { result = await api.sendOp(operation, info.timing); }
      catch (error) {
        error.shown = true;
        if (info.ready && [400, 409, 422].includes(error.status)) {
          if (!rollback && refusedSelection === null) refusedSelection = info.selection;
          rollback = true;
        }
        throw error;
      }
      info.answer = performance.now();
      info.haveRound = result.round;
      const round = roundOf(result);
      // A poll may already have delivered a newer foreign round.
      if (round >= currentRound() || currentRound() == null) {
        snapshot = { ...snapshot, plan: result.plan, model: result.model };
        if (!snapshot.rounds.some(row => row.id === round)) snapshot.rounds = [...snapshot.rounds, { id: round }].slice(-50);
      }
      info.after = round;
      return { ...result, round };
    },
    onChange(change) {
      syncSaveState();
      const rebuild = rollback || change.dropped.length > 0;
      rollback = false;
      if (!pushing && optimistic && change.plan && JSON.stringify(change.plan) !== lastScene) {
        sceneWork = sceneWork.catch(report).then(async () => {
          const plan = queue.shown(), signature = JSON.stringify(plan);
          if (signature === lastScene) return;
          if (rebuild) await view?.rebuild(plan);
          else await settleView(plan, {});
          lastScene = signature;
          tools?.refresh(); library?.refresh();
        });
      }
      if (change.refused.length || change.dropped.length) {
        const first = change.refused[0];
        let text = first ? `${first.label} was not saved: ${first.reason}` : '';
        if (change.dropped.length) text += `${text ? '\n' : ''}Also undone because it needed that change: ${change.dropped.join(', ')}.`;
        window.showGlobalAlert(text);
        tools?.select(refusedSelection); refusedSelection = null;
      }
    },
    onSignedOut() { queueSignedOut = true; api.noticeSignedOut(); },
  };
  let queue = createEditQueue(queueOptions);
  const shownPlan = () => queue.shown() || snapshot.plan;
  function syncSaveState() {
    const state = queue.state(), count = state.unsaved || state.saving;
    el('editor-save-state').textContent = state.saved ? 'Saved'
      : `${state.unsaved ? '' : 'Saving '}${count} ${count === 1 ? 'change' : 'changes'}${state.unsaved ? ' not saved' : ''}`;
    el('editor-toolbar-save-state').textContent = el('editor-save-state').textContent;
  }
  async function settleView(plan, info) {
    const selection = info.selection ?? tools?.selected?.() ?? null;
    const buildingId = info.buildingId ?? selection?.buildingId ?? selection?.building ?? null;
    const building = view.plan?.buildings?.find(b => b.id === buildingId);
    const id = selection?.pieceId ?? selection?.id;
    const piece = ['walls', 'rooms', 'openings', 'joints', 'anchors', 'items']
      .flatMap(list => building?.[list] || []).find(p => p.id === id);
    const result = await view.settle(plan, { buildingId, levelId: info.levelId ?? piece?.level ?? null,
      touched: info.touched ?? null, selection });
    if (result.selection !== selection) tools?.select(result.selection);
    return result;
  }
  function summary(text) {
    lastSummary = text;
    panel.message(text);
  }
  const edit = change => history.perform(() => editNow(change));
  const applyOp = (operation, { drag = false, local = null, label = '', selection = null } = {}) => {
    let release;
    const ready = new Promise(resolve => { release = resolve; });
    const step = {};
    const saved = applyOpNow(operation, { drag, local, label, selection, ready, step });
    saved.catch(() => {});
    return history.perform(() => { release(); return saved; }, { step: () => step });
  };
  async function editNow(change) {
    if (!canEdit()) throw new Error('Use Back to now before changing your house.');
    let result;
    for (const op of Array.isArray(change) ? change : [change]) {
      result = await request('edit', 'POST', { edit: op });
      const line = document.createElement('li'); line.textContent = plain(result.summary); el('editor-log').append(line);
    }
    await polling.refreshState(); sheets = await request('sheets');
    await renderScene(); timeline?.sync(currentBuild);
    lastSummary = result.summary;
    return result;
  }
  // `saved` runs as soon as the round is saved, before the scene rebuild (the
  // roof tools select the new piece then). `settle: false` returns once the
  // round is saved and read back; the scene rebuild follows. The lot tools
  // already show the building where it landed.
  async function applyOpNow(operation, { saved, settle = true, drag = false, local = null, label = '', selection = null, ready = null, step = {} } = {}) {
    if (!canEdit()) throw new Error('Use Back to now before changing your house.');
    const timing = api.beginEdit(operation);
    timing.drag_frame = drag ? tools?.lastDragFrameMs ?? null : null;
    if (drag) tools?.clearDragFrame?.();
    const info = { ready, timing };
    operation = { ...operation }; opInfo.set(operation, info);
    const labels = { move_wall: 'Moving the wall', move_joint: 'Moving the corner', move_room: 'Moving the room',
      move_site_item: operation.list === 'planting' ? 'Moving the plant' : 'Moving the item',
      move_opening: 'Moving the opening', move_anchor: 'Moving the anchor', move_item: 'Moving the item' };
    label ||= labels[operation.op] || 'That change';
    selection ||= tools?.selected?.() || null;
    info.selection = selection;
    const kept = !!local;
    // Missing local targets are judged by the queue, which drops dependencies.
    if (!local) {
      try { local = applyLocal(shownPlan(), operation)?.plan || null; }
      catch (error) { if (!(error instanceof LocalMissing)) console.warn('Local preview failed', error); }
    }
    if (local) ++optimistic;
    pushing = true;
    // Multi-round drawing/lot gestures already own the history lane. Their
    // remaining rounds must finish before a later release can send; feeding
    // their answers back as bases also replays that release's local preview.
    const queued = ready ? queue.push({ op: operation, label, selection, local }) : {
      saved: queueOptions.send(operation).then(result => { queue.base(result); return result; }).catch(error => {
        if ([401, 403].includes(error.status)) queueOptions.onSignedOut();
        else report({ message: `${label} was not saved: ${error.message}` });
        throw error;
      }),
    };
    pushing = false;
    let frame = null;
    if (local) {
      // Walls and hosted pieces already have drawable preview buffers. Site
      // gestures have only an outline, so settle their local geometry now.
      // A shape's vertex, turn or size drag also draws only an outline: without
      // this settle an equal answer never redrew it (owner, 2026-11-18: pavers
      // stayed put after moving a path point).
      if (!kept || ['move_site_item', 'update_site_shape'].includes(operation.op)) await settleView(queue.shown(), { selection });
      lastScene = JSON.stringify(queue.shown());
      frame = api.observeEditFrame(view, timing);
      frame.catch(report);
      tools?.refreshCard();
    }
    let result;
    try { result = await queued.saved; }
    catch (error) {
      error.shown = true;
      await sceneWork;
      if (local) --optimistic;
      throw error;
    }
    Object.assign(step, { before: info.before, after: info.after });
    saved?.(result);
    // The card shows the saved change at once (a device reads Placed); the
    // scene rebuild below can take seconds on a large house.
    tools?.refreshCard();
    const line = document.createElement('li'); line.textContent = plain(result.words); el('editor-log').append(line);
    lastSummary = result.words;
    const refresh = async () => {
      const stop = api.span(timing, 'refresh_state');
      try { await polling.refreshState(info.haveRound); timeline?.sync(currentBuild); }
      finally { stop(); }
    };
    const rebuild = async () => {
      const stop = api.span(timing, 'rebuild');
      try { await sceneWork; await renderScene(timing); }
      finally { stop(); }
      return { frame: api.observeEditFrame(view, timing) };
    };
    if (local) {
      // An equal authoritative answer keeps the release frame. Task 6 can
      // settle differing pieces without a whole-house rebuild.
      (async () => {
        try {
          await sceneWork;
          const settled = view.afterNextRender ? view.afterNextRender() : new Promise(resolve => requestAnimationFrame(resolve));
          await Promise.all([frame, settled]);
          timing.settle = performance.now() - info.answer;
          await refresh();
          api.keepEdit(timing);
        } finally { --optimistic; }
      })().catch(report);
      return result;
    }
    if (!settle) {
      await refresh();
      rebuild().then(({ frame }) => frame).then(() => api.keepEdit(timing)).catch(report);
      return result;
    }
    // Observe the frame without holding up state refresh or the history queue.
    // refresh_state can overlap first_frame, or finish after it.
    ({ frame } = await rebuild());
    try { await refresh(); }
    finally { frame.then(() => api.keepEdit(timing)).catch(report); }
    return result;
  }

  function setStatus(text) { el('editor-status').textContent = plain(text); }
  function syncBuildButton() {
    syncSaveState();
    syncChip();
    steps.render(stepState());
    placeSteps.render(stepState());
    el('editor-genbar').hidden = !directing && !['running', 'paused', 'stopped', 'checkpoint'].includes(currentBuild?.state);
    el('editor-house-name').textContent = snapshot.plan?.name || snapshot.plan?.buildings?.[0]?.name || 'House editor';
    el('editor-front-door').hidden = drawingStarted || !!sheets.place?.buildings?.length || !!sheets.sources?.length
      || !!snapshot.model?.buildings?.length || !!sheets.place?.lot?.read || !!snapshot.plan?.site?.lot?.length;
    history?.sync();
    houses?.sync();
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
    el('rail-add-effect').disabled = busy;
    for (const id of ['menu-director', 'menu-advanced', 'menu-start-over', 'menu-reset-spend']) el(id).disabled = busy;
    el('menu-start-over').disabled = !canEdit() || !hooks.ready || resuming
      || currentBuild?.state === 'running';
    el('menu-director').disabled ||= !snapshot.plan?.buildings?.length;
    el('advanced-save').disabled = busy;
    panel.readOnly(!canEdit());
  }
  function syncChip() {
    statusChip.update({ state: currentBuild?.state, pause: currentBuild?.pause,
      cost: snapshot.cost?.total || 0, bake: snapshot.bake,
      estimate: ['running', 'stopped', 'checkpoint'].includes(currentBuild?.state) ? snapshot.cost?.estimate ?? null : null });
  }
  function countGhosts(plan) {
    if (!plan || typeof plan !== 'object') return 0;
    return (plan.state === 'ghost' ? 1 : 0) + Object.values(plan).reduce((n, value) =>
      n + (value && typeof value === 'object' ? countGhosts(value) : 0), 0);
  }
  function previewPlan() {
    const plan = structuredClone(shownPlan() || emptyPlan());
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
  async function renderScene(timing = null) {
    view?.setSite?.(snapshot.site);
    if (tools?.dragging() || lot?.dragging()) return;
    const plan = timeline?.preview() || previewPlan(), signature = JSON.stringify(plan);
    const changed = signature !== lastScene;
    if (view && changed) {
      await view.rebuild(plan, { timing });
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
    checks?.sync();
    timeline?.sync(currentBuild);
    // Read the Home Assistant link beside the scene, never before it: a slow or
    // unreachable Home Assistant must not hold the editor's start, a poll or a save.
    tools?.refreshLink(changed).then(() => { devices?.refresh(); place?.refreshLink?.().catch(report); }).catch(report);
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
    syncBuildButton();
  }
  const polling = createPolling({
    async onState(state) {
      const round = roundOf(state);
      pushing = true;
      const accepted = queue.base({ round, plan: 'plan' in state ? state.plan : snapshot.plan, model: 'model' in state ? state.model : snapshot.model });
      if (accepted && queueSignedOut) { queueSignedOut = false; queue.resume(); }
      pushing = false;
      if (!accepted) return;
      if (!state.build && currentBuild) {
        currentBuild = null; ghostBuild = null; ghosts.clear(); buildGhosts?.clear(); panel.reset(); drawTimeline(null);
        await loadSheets();
      }
      snapshot = { ...snapshot, ...state };
      syncBuildButton();
      // A house with pieces and no drawings to build from is not waiting for drawings.
      const built = (snapshot.model?.buildings || []).some(b => b.walls?.length || b.rooms?.length || b.roofs?.length);
      if (!currentBuild) setStatus(sheets.page_roles.some(row => ['floor', 'plot'].includes(row.role)) ? 'Ready to build'
        : built ? 'House ready' : drawingStarted ? 'Drawing by hand' : 'Add drawings to begin');
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
        if (event.type === 'stream_reset') buildGhosts?.clear(event.step, event.after);
        if (event.type === 'stage' && event.frame) buildGhosts?.add(event);
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
      // A batch can carry saved pieces, temporary outlines or new costs: read their owning state
      // before rebuilding the scene. Streamed pieces, stages, resets and log lines change nothing
      // /state or /sheets return, so a streaming read does not reload the house twice a second.
      // A cost event still reloads, so the chip keeps matching the ledger.
      if ((build.events || []).some(event => !STREAM_ONLY.has(event.type))) {
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
    follow: id => polling.follow(id), canEdit: () => canEdit() && !resuming && !stopping, panel, lotTools: () => lot,
    onClose: () => steps.close(), getLink: () => tools?.haLink, getPlan: shownPlan });

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
  listen(el('editor-manage-sources'), 'click', () => steps.open('Your files'));
  api.mountEditTiming({ toggle: el('menu-edit-timing'), overlay: el('editor-edit-timing'), send: el('menu-send-timing'),
    signal: lifecycle.signal, post: body => request('perf', 'POST', body, 'twin'), report,
    force: new URLSearchParams(location.search).get('timing') === '1' });
  listen(el('menu-upload'), 'click', () => steps.open('Your files'));
  listen(el('editor-add-files'), 'click', () => steps.open('Your files'));
  listen(el('editor-draw-myself'), 'click', async () => {
    if (!canEdit() || !hooks.ready) return;
    el('editor-draw-myself').disabled = true;
    try {
      if (!snapshot.plan?.buildings?.length) {
        const part = sheets.place?.buildings?.[0] || (await request('place/buildings', 'POST', { name: 'My house', kind: 'main_house' })).building;
        const plan = structuredClone(snapshot.plan || emptyPlan());
        plan.buildings.push({ id: part.id, name: part.name, position: [0, 0], rotation: 0, base: 0,
          levels: [{ id: 'L1', name: 'Main floor', elevation: 0, ceiling: 9 }],
          walls: [], openings: [], rooms: [], roof: { sections: [] } });
        await request('plan', 'PUT', { plan, reason: 'Start drawing my house.', base: currentRound() }, 'twin');
        await polling.pollNow(true); await loadSheets();
      }
      drawingStarted = true; syncBuildButton();
      if (!currentBuild && !sheets.page_roles?.some(row => ['floor', 'plot'].includes(row.role))) setStatus('Drawing by hand');
      place.close(); tools.chooseFloor(tools.floor().key); tools.select(null);
      el('rail-draw-wall').click();
    } catch (error) { report(error); }
    finally { el('editor-draw-myself').disabled = false; }
  });
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
      dock.show('argyle');
      el('editor-advanced').scrollIntoView({ block: 'nearest' });
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
      await history.perform(() => request('start-over', 'POST', {}));
      queue = createEditQueue(queueOptions);
      snapshot = { plan: null, rounds: [], cost: snapshot.cost, build: null };
      currentBuild = null; ghostBuild = null; ghosts.clear(); prompted.clear();
      panel.reset(); tools?.select(null); pauses?.dismiss(); draw?.cancel(); history?.clear();
      el('editor-advanced').hidden = true; advancedBase = null;
      await polling.pollNow(true);
      await loadSheets();
      drawingStarted = false; steps.close();
      await timeline?.now();
      summary('House cleared. The spend total stays.');
      setStatus('Add drawings to begin');
    } catch (error) { report(error); }
    finally { menuBusy = false; syncBuildButton(); }
  });
  listen(el('editor-check-step'), 'click', () => {
    tools?.select(null); draw?.cancel(); steps.open('Check it');
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
  listen(window, 'beforeunload', event => {
    if (!queue.pending()) return;
    event.preventDefault(); event.returnValue = '';
  });
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
    view = await mountTwin(el('editor-scene'), { plan: emptyPlan(), kit, preserveCamera: true, bake: false });
    mountLighting(view, el('editor-lighting'), { signal: lifecycle.signal });
    buildGhosts = createBuildGhosts(view);
    if (new URLSearchParams(location.search).get('test') === '1') hooks.buildGhosts = buildGhosts;
    view.showAnchors = true;
    const onInteract = () => { checks?.dismiss(); pauses?.dismiss(); syncBuildButton(); };
    history = createHistory({ getRound: currentRound, getBuild: () => currentBuild,
      canEdit, signal: lifecycle.signal, latest: () => polling.refreshState(),
      onError: error => setStatus(error.message || 'Could not save this change. Try again.'),
      refresh: async () => { draw?.cancel(); await polling.refreshState(); await loadSheets(); await renderScene(); } });
    houses = mountHouses({ history, signal: lifecycle.signal,
      canLoad: () => canEdit() && !active(currentBuild),
      async capture() {
        view.render();
        const canvas = document.createElement('canvas'); canvas.width = 240; canvas.height = 160;
        canvas.getContext('2d').drawImage(view.renderer3.domElement, 0, 0, 240, 160);
        return canvas.toDataURL('image/png');
      },
      async afterLoad(result) {
        tools?.select(null); draw?.cancel(); pauses?.dismiss();
        // The write succeeded: preserve its Undo step even if a read or redraw fails.
        if (!snapshot.rounds.some(row => row.id === result.round)) snapshot.rounds.push({ id: result.round, kind: 'load' });
        await polling.refreshState(); await loadSheets(); await renderScene();
      },
    });
    tools = createSceneTools({ dock, view, getPlan: () => timeline?.preview() || shownPlan(), getModel: () => snapshot.model, getKit: () => kit, getSheets: () => sheets,
      siteHits: (x, y) => library?.siteHits(x, y) || [],
      padHits: (x, y) => terrain?.padHits?.(x, y) || [], fixtureHits: (x, y) => devices?.fixtureHits?.(x, y) || [],
      pickMaterial: surface => library?.pick(surface), onDrawFeature: kind => terrain?.startDrawing(kind),
      edit, op: applyOp, panel, canEdit, signal: lifecycle.signal, onInteract, api, addDormer: () => roofTools?.addDormer() });
    library = createLibrary({ dock, view, kit, getPlan: () => timeline?.preview() || shownPlan(), tools,
      op: applyOp, canEdit, signal: lifecycle.signal, onInteract });
    flags = createFlags({ view, getModel: () => snapshot.model, getPlan: shownPlan,
      tools, panel, op: applyOp, canEdit, signal: lifecycle.signal, onInteract, managed: true,
      onReview: item => checks?.show(item) });
    draw = createDraw({ dock, cancelOtherDrawing: () => { terrain?.cancel(); lot?.cancel(); }, view, tools, getPlan: shownPlan, op: operation => applyOpNow(operation),
      gesture: history.perform, canEdit, panel, signal: lifecycle.signal, onInteract, surfaceAt: (event, options) => library.surfaceAt(event, options), groundPoint: event => library.ground(event) });
    roofTools = createRoofTools({ dock, view, tools, getPlan: shownPlan,
      op: (operation, options) => history.perform(() => applyOpNow(operation, options)),
      canEdit, panel, signal: lifecycle.signal, onInteract, cancelDrawing: draw.cancel });
    pauses = createPauses({ dock, view, getBuild: () => currentBuild, getGhost: step => ghosts.get(step),
      getSheets: () => sheets, refresh: () => polling.pollNow(true), preview: () => renderScene().catch(report),
      visibilityChanged: syncBuildButton, canEdit, signal: lifecycle.signal, guided: true });
    checks = createChecks(view, { dock, api, getBuild: () => currentBuild, getModel: () => snapshot.model,
      getPlan: shownPlan, tools, panel, canEdit, signal: lifecycle.signal, op: applyOp, flags, pauses,
      onClose: () => steps.close() });
    lot = createLotTools({ dock, view, getPlan: () => timeline?.preview() || shownPlan(), getSheets: () => sheets,
      getSelection: tools.selection, select: tools.select, pauses, signal: lifecycle.signal,
      canEdit: () => canEdit() && (!active(currentBuild) || !!pauses.lotPlacement()),
      op: operations => history.perform(async () => { for (const operation of operations) await applyOpNow(operation, { settle: false }); }),
      // The lot card frees itself once the place rows are fresh; the scene
      // rebuild (seconds for a refitted house) follows on the poll's tick.
      reload: async () => { await loadSheets(); polling.pollNow(true).catch(report); } });
    devices = createDevicePlacement({ dock, view, tools, library, getPlan: () => timeline?.preview() || shownPlan(),
      op: applyOp, canEdit, signal: lifecycle.signal,
      prepare() { onInteract(); roofTools.cancel(); draw.cancel(); } });
    el('rail-add-effect').addEventListener('click', () => {
      if (canEdit()) devices.addEffect().catch(report);
    }, {signal: lifecycle.signal});
    terrain = createTerrainTools({ dock, view, tools, getPlan: () => timeline?.preview() || shownPlan(),
      op: applyOp, canEdit, signal: lifecycle.signal,
      getKit: () => kit,
      prepare() { onInteract(); devices.cancel(); roofTools.cancel(); draw.cancel(); lot.cancel(); } });
    view.live = { draw: devices.draw, stop: devices.stop };
    tools.delegate({
      preview: plan => library.preview(plan), key: event => library.key(event), typedValue: () => library.typedValue(), commit: value => library.commit(value),
      handleSources: [tools.gizmo, terrain, lot, devices.fixtureHandles],
      selectPick: hit => hit?.kind === 'terraces' && (terrain.choose('terraces', hit.id), true) || devices.selectFixturePick(hit),
      selectionChanged: state => { terrain.selectionChanged(state); library.refresh(); },
      pick: flags.pick, pointerBrowse: event => devices.pointerBrowse(event),
      pointerArmedDown: event => tools.pointerArmedDown(event) || terrain.pointerArmedDown(event) || devices.pointerArmedDown(event) || lot.pointerArmedDown(event) || pauses.pointerDown(event) || roofTools.pointerDown(event) || draw.pointerDown(event),
      pointerDown: event => devices.pointerDown(event) || lot.pointerDown(event) || library.pointerDown(event),
      pointerMove: event => terrain.pointerMove(event) || devices.pointerMove(event) || lot.pointerMove(event) || pauses.pointerMove(event) || roofTools.pointerMove(event) || draw.pointerMove(event) || library.pointerMove(event),
      pointerUp: (event, cancel) => terrain.pointerUp(event, cancel) || devices.pointerUp(event, cancel) || lot.pointerUp(event, cancel) || pauses.pointerUp(event, cancel) || roofTools.pointerUp(event, cancel) || draw.pointerUp(event, cancel) || library.pointerUp(event, cancel),
      floorChanged() { terrain.cancel(); devices.cancel(); roofTools.cancel(); draw.floorChanged(); }, cancel() { terrain.cancel(); devices.cancel(); roofTools.cancel(); draw.cancel(); },
    });
    timeline = createTimeline({ dock, getState: () => snapshot, render: renderScene, signal: lifecycle.signal,
      canScrub: () => !menuBusy && !directing,
      log(summary) { const line = document.createElement('li'); line.textContent = summary; el('editor-log').append(line); lastSummary = summary; },
      onPreview(value) {
        previewing = value; terrain.cancel(); devices.cancel(); roofTools.cancel(); draw.cancel(); tools.select(null); pauses.dismiss(); panel.readOnly(value);
        tools.refreshCard(); syncBuildButton();
        for (const id of ['move', 'rotate', 'scale', 'draw-room', 'draw-wall', 'split-room', 'add-door', 'add-window', 'add-anchor', 'add-level', 'delete', 'roof']) el(`rail-${id}`).disabled = value;
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
      terrain,
      underlay: lot.underlay, lotHandles: lot.lotHandles, lotSuggestions: lot.lotSuggestions,
      flags: flags.flags, proposals: flags.proposals,
      get lastDragFrameMs() { return tools.lastDragFrameMs; },
    };
    // The editor uses the mockup's dark work surface; the shared preview keeps
    // its own daylight sky, with the same renderer and lighting.
    view.scene.background?.set?.('#171e27');
    await polling.resume();
    try {
      const session = await request('session', 'POST');
      if (session.cleaned) {
        await polling.refreshState(); await renderScene();
        if (session.saved) window.showGlobalAlert(`Older history was cleared. A copy of the house was saved as ${session.saved.name}.`);
      }
    } catch (error) { report(error); }
    view.scene.background?.set?.('#171e27');
    hooks.ready = true;
    syncBuildButton();
  } catch (error) {
    setStatus(error.signedOut ? 'Home Assistant signed the tab out'
      : error.status === 401 || error.status === 403 ? 'Sign in to edit your house' : 'Could not open the house. Reload to try again.');
    if (error.status !== 401 && error.status !== 403) report(error);
  }
}
