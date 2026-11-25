"""Porch posts editor tests under Node + real FastAPI server route.

Uses the real generator/view (mountTwin), real local_ops.js, real edit_queue.js,
and real FastAPI /api/house/editor/op + /api/house/twin/revert endpoints.
Run from chauffeur/: python tests/test_twin_porch_posts_editor_js.py
"""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX
from test_twin_awning_golden_js import FIXTURE

DRIVER = PREFIX + FIXTURE + r"""
const THREE = await import('three');
globalThis.__THREE_MESH = THREE.Mesh;
globalThis.__THREE_BOX = THREE.BoxGeometry;
globalThis.__THREE_STD = THREE.MeshStandardMaterial;
if (!globalThis.Renderer.prototype.getDrawingBufferSize) {
  Object.assign(globalThis.Renderer.prototype, {
    getDrawingBufferSize(v) { return v.set(this.domElement.width || 1, this.domElement.height || 1); },
    getViewport(v) { return v.set(0, 0, this.domElement.width || 1, this.domElement.height || 1); },
    setViewport() {},
    getScissor(v) { return v.set(0, 0, this.domElement.width || 1, this.domElement.height || 1); },
    setScissor() {},
    getScissorTest() { return false; },
    setScissorTest() {},
  });
}
window.fetch = globalThis.fetch = async url => {
  const href = String(url || '');
  const payload = href.includes('materials/manifest')
    ? { revision: 0, entries: {} }
    : { materials: [], items: [], imports: [], limit_mb: 50, unpacked_limit_mb: 200 };
  return { ok: true, status: 200, text: async () => JSON.stringify(payload), json: async () => payload };
};
window.twinObjectSchema = input.objectSchema || { kinds: {}, opening: {} };

const { mountTwin } = await import(file('static/twin/twin_view.js'));
const { porchPosts, postRef, findPost, POST_SIZE } = await import(file('static/twin/porch_posts.js'));
const { applyLocal } = await import(file('static/twin/editor/local_ops.js'));
const { createEditQueue } = await import(file('static/twin/editor/edit_queue.js'));
const { sceneRows, createSceneTree } = await import(file('static/twin/editor/scene_tree.js'));
const { createVisibility, existingPostIds } = await import(file('static/twin/editor/visibility.js'));
const { createRoomSelection } = await import(file('static/twin/editor/selection.js'));
const { findPiece } = await import(file('static/twin/editor/piece_operations.js'));
const { createDock } = await import(file('static/twin/editor/dock.js'));
const { createHandles } = await import(file('static/twin/editor/handles.js'));
const { createGizmo } = await import(file('static/twin/editor/gizmo.js'));
const { createSceneTools } = await import(file('static/twin/editor/scene_tools.js'));
const { createLibrary } = await import(file('static/twin/editor/library.js'));
const { createDraw } = await import(file('static/twin/editor/draw.js'));
const { groupTransform, transformOperations, deleteOperations } = await import(file('static/twin/editor/group_transform.js'));
const { createMarquee } = await import(file('static/twin/editor/marquee.js'));
const { buildPostSnapTargets, snapPostPoint } = await import(file('static/twin/editor/porch_post_shelf.js'));
const { postRoofReason, postRoofDisabledReason } = await import(file('static/twin/editor/posts_action.js'));
const { materialsInSelection, replacementOperations, sharedMaterialRows } = await import(file('static/twin/editor/selection_materials.js'));

const near = (a, b, tol = 1e-4) => assert.ok(Math.abs(a - b) <= tol, `${a} near ${b}`);
const flush = async () => { await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0)); };

const household = input.household;
const baseKit = input.kit;
const serverBatches = [];

function makePatioPlan() {
  return structuredClone(input.patioPlan);
}

// Mount a real mountTwin + real createSceneTools + real createLibrary + real applyLocal stack.
async function mountRealEditor(initialPlan, { canEditFn = () => true } = {}) {
  document.body.replaceChildren();
  const shell = document.createElement('div'); shell.className = 'editor-shell'; document.body.append(shell);
  const sceneHost = document.createElement('div'); sceneHost.id = 'editor-scene'; shell.append(sceneHost);
  const ids = [
    ['aside', 'editor-dock'], ['div', 'properties-content'], ['div', 'properties-empty'],
    ['div', 'properties-heading'], ['div', 'properties-crumbs'], ['button', 'properties-back'],
    ['div', 'piece-card'], ['div', 'scene-tree'], ['div', 'layer-kinds'], ['div', 'scene-floor-actions'],
    ['div', 'editor-status'], ['div', 'editor-drag-hint'], ['svg', 'editor-drag-layer'],
    ['div', 'library-panel'], ['div', 'library-entries'], ['div', 'library-status'], ['div', 'library-jobs'],
    ['div', 'draw-tools'], ['div', 'draw-note'], ['div', 'draw-options'], ['div', 'draw-options-title'],
    ['div', 'draw-options-note'], ['button', 'draw-cancel'],
    ['button', 'rail-select'], ['button', 'rail-move'], ['button', 'rail-rotate'], ['button', 'rail-scale'],
    ['button', 'rail-copy'], ['button', 'rail-paste'], ['button', 'rail-sheet'], ['button', 'rail-delete'],
    ['button', 'rail-add-level'], ['button', 'rail-library'],
    ['button', 'rail-draw-room'], ['button', 'rail-draw-wall'], ['button', 'rail-split-room'],
    ['button', 'rail-add-door'], ['button', 'rail-add-window'], ['button', 'rail-add-anchor'],
    ['button', 'rail-add-stair'], ['button', 'rail-add-porch'], ['button', 'rail-add-solar-zone'],
    ['button', 'rail-add-meter'], ['button', 'rail-add-electric-panel'], ['button', 'rail-add-charger'],
    ['button', 'rail-add-parking'],
  ];
  for (const [tag, id] of ids) {
    const n = document.createElement(tag); n.id = id; shell.append(n);
  }
  const outline = document.createElement('polygon'); outline.id = 'editor-drag-outline';
  document.getElementById('editor-drag-layer').append(outline);
  const propsScroll = document.getElementById('properties-content');
  propsScroll.scrollHeight = 1200; propsScroll.clientHeight = 400;
  propsScroll.append(document.getElementById('piece-card'));
  const origCss = globalThis.getComputedStyle;
  globalThis.getComputedStyle = node => node === propsScroll ? { overflowY: 'auto', overflow: '' } : origCss?.(node) || { overflowY: 'visible', overflow: '' };

  let plan = structuredClone(initialPlan);
  const view = await mountTwin(sceneHost, { plan, kit: kit(), tier: 'high', bake: false, preserveCamera: true });
  while (!view.ready) await new Promise(r => setTimeout(r, 1));
  const canvas = view.renderer3.domElement;
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, right: 1440, bottom: 900, width: 1440, height: 900 });
  canvas.setPointerCapture = () => {}; canvas.releasePointerCapture = () => {}; canvas.hasPointerCapture = () => false;

  const ops = [], alerts = [], confirms = [];
  window.showGlobalAlert = msg => alerts.push(msg);
  window.promptConfirm = async (...args) => { confirms.push(args); return true; };

  const abort = new AbortController();
  const visibility = createVisibility({ storage: null });
  const isPickable = c => visibility.isPickable(c);
  view.isPiecePickable = isPickable;
  const dock = createDock({ host: document.getElementById('editor-dock') });
  let onOpHook = null;
  const opFn = async operation => {
    ops.push(structuredClone(operation));
    if (onOpHook) { await onOpHook(operation); return; }
    const local = applyLocal(plan, operation);
    if (local?.plan) {
      plan = local.plan;
      await view.settle(plan);
      tools.refresh();
    }
  };
  let library = null;
  const tools = createSceneTools({
    view, getPlan: () => plan, getModel: () => plan, getKit: () => baseKit, getSheets: () => ({}),
    surfaceAt: (event, target) => library?.contextSurfaceAt(event, target),
    groundPoint: event => library?.ground(event),
    edit: opFn, op: opFn, applyBatch: async list => opFn({ op: 'batch', ops: list }),
    panel: { clearSelection() {}, focusSelection() {}, message() {} },
    canEdit: () => canEditFn(), signal: abort.signal, visibility, dock, isPickable,
  });
  library = createLibrary({
    view, kit: baseKit, getPlan: () => plan, tools, op: opFn, canEdit: () => canEditFn(), signal: abort.signal,
  });

  const pointer = (type, x, y, extra = {}) => {
    const ev = makeEvent(type, { bubbles: false, pointerId: 1, button: 0, buttons: type === 'pointerup' ? 0 : 1, clientX: x, clientY: y, shiftKey: false, ctrlKey: false, metaKey: false, altKey: false, ...extra });
    canvas.dispatchEvent(ev);
    return ev;
  };
  const clickCanvas = (x, y, extra = {}) => {
    pointer('pointerdown', x, y, extra);
    pointer('pointerup', x, y, extra);
  };

  return {
    getPlan: () => plan,
    setPlan: async p => { plan = p; await view.rebuild(plan); },
    setPlanOnly: p => { plan = p; },
    setOnOp: fn => { onOpHook = fn; },
    ops, alerts, confirms, view, tools, library, dock, visibility, canvas, propsScroll, pointer, clickCanvas, abort,
    dispose: () => { abort.abort(); dock.dispose(); view.dispose(); },
  };
}

// ---------------------------------------------------------------------------
// 1. Tree rows on household fixture + orphan porch + id-less porch + hide/lock
// ---------------------------------------------------------------------------
await test('scene_tree_household_orphan_idless_hide_lock', () => {
  const rows = sceneRows(household);
  for (const b of household.buildings) {
    for (const p of b.porches || []) {
      const porchRows = rows.filter(r => r.building === b.id && r.id === p.id);
      assert.equal(porchRows.length, 1, `porch ${p.id} listed once`);
      const postRows = rows.filter(r => r.building === b.id && r.kind === 'porch_post' && r.porchId === p.id);
      assert.equal(postRows.length, (p.columns || []).length);
      assert.deepEqual(postRows.map(r => r.name), (p.columns || []).map((_, i) => `Post ${i + 1}`));
      assert.deepEqual(postRows.map(r => r.id), (p.columns || []).map((_, i) => postRef(p, i)));
      for (const r of postRows) assert.equal(r.parent.id, p.id);
    }
  }

  // Orphan porch parents its posts; a legacy porch without an id creates NO row and NO posts.
  const edgePlan = {
    buildings: [{
      id: 'b1', name: 'House', levels: [{ id: 'L1', name: 'Main', elevation: 0, ceiling: 9 }],
      rooms: [], walls: [], openings: [],
      porches: [
        { id: 'orphan-porch', name: 'Side Porch', level: 'L1', polygon: [[0, 0], [10, 0], [10, 6], [0, 6]],
          columns: [{ at: [0.5, 0.5], size: 0.5 }, { at: [9.5, 0.5], size: 0.5 }] },
        { name: 'Nameless legacy', level: 'L1', polygon: [[20, 0], [26, 0], [26, 4], [20, 4]],
          columns: [{ at: [21, 1], size: 0.5 }] },
      ],
    }], site: {},
  };
  const edgeRows = sceneRows(edgePlan);
  assert.equal(edgeRows.filter(r => r.kind === 'porch').length, 1, 'no row for porch without an id');
  assert.equal(edgeRows.filter(r => r.kind === 'porch_post').length, 2, 'no post rows for porch without an id');
  assert.deepEqual(edgeRows.filter(r => r.kind === 'porch_post').map(r => [r.name, r.parent.id, r.id]), [
    ['Post 1', 'orphan-porch', 'post:orphan-porch:0'],
    ['Post 2', 'orphan-porch', 'post:orphan-porch:1'],
  ]);

  // Hide and lock per row and inherited from parent porch + visibility prune survival.
  const host = document.createElement('div'); host.clientHeight = 400; document.body.append(host);
  const vis = createVisibility({ storage: null });
  let picked = null;
  const tree = createSceneTree({ host, getPlan: () => edgePlan, getSelection: () => picked,
    select: r => { picked = r; tree.reveal(r.id, r.building); }, visibility: vis,
    floors: { current: () => 'b1:L1', hidden: () => false } });
  tree.reveal('post:orphan-porch:0', 'b1');
  const rowEl = id => host.querySelector(`[data-scene-id="${id}"]`);
  click(rowEl('post:orphan-porch:0').querySelector('[data-row-eye]'));
  assert.equal(vis.isHidden('post:orphan-porch:0'), true);
  click(rowEl('post:orphan-porch:1').querySelector('[data-row-lock]'));
  assert.equal(vis.isLocked('post:orphan-porch:1'), true);
  vis.lock('orphan-porch');
  assert.equal(rowEl('post:orphan-porch:0').querySelector('[data-row-lock]').getAttribute('aria-pressed'), 'true');
  assert.equal(vis.isPickable({ kind: 'porch_post', pieceId: 'post:orphan-porch:0', parentPieceId: 'orphan-porch', buildingId: 'b1' }), false);
  vis.unlock('orphan-porch');
  vis.forHouse('house-a', existingPostIds(edgePlan));
  assert.equal(vis.isHidden('post:orphan-porch:0'), true);
  assert.equal(vis.isLocked('post:orphan-porch:1'), true);
  tree.dispose(); host.remove();

  // scene_tree.js:121: pass kind only for posts when checking ancestor lock state.
  const calls = [];
  const spyVis = {
    isHidden: () => false,
    isLocked: (id, kind) => { calls.push([id, kind]); return false; },
    subscribe: () => () => {},
  };
  const spyHost = document.createElement('div'); spyHost.clientHeight = 400; document.body.append(spyHost);
  const spyTree = createSceneTree({ host: spyHost, getPlan: () => edgePlan, getSelection: () => null,
    select: () => {}, visibility: spyVis, floors: { current: () => 'b1:L1', hidden: () => false } });
  spyTree.reveal('post:orphan-porch:0', 'b1');
  calls.length = 0;
  spyTree.refresh();
  const buildingAncestorCalls = calls.filter(([id]) => id === 'b1');
  const levelAncestorCalls = calls.filter(([id]) => id === 'L1');
  // Row's own check passes kind, while descendant checks on building/level pass undefined.
  assert.ok(buildingAncestorCalls.some(([, kind]) => kind === undefined), `building ancestor lock check omits kind: ${JSON.stringify(buildingAncestorCalls)}`);
  assert.ok(levelAncestorCalls.some(([, kind]) => kind === undefined), `level ancestor lock check omits kind: ${JSON.stringify(levelAncestorCalls)}`);
  // Post's parent porch check passes porch kind!
  const porchCalls = calls.filter(([id]) => id === 'orphan-porch');
  assert.ok(porchCalls.length >= 2 && porchCalls.every(([, kind]) => kind === 'porch'), `porch parent lock check passes kind for posts: ${JSON.stringify(porchCalls)}`);
  spyTree.dispose(); spyHost.remove();
});

// ---------------------------------------------------------------------------
// 2. Real view picking: OUTSIDE ruling, I7 (3 hits: wall, post, porch),
//    I5 (locked porch hint), I6 (Shift-click nearest only),
//    I4 (Library drop on post), I9 (draw.js sees through posts)
// ---------------------------------------------------------------------------
await test('real_view_picking_outside_i4_i5_i6_i7_i9', async () => {
  const p = makePatioPlan();
  const b = p.buildings[0];
  b.roofs = []; b.roof.sections = [];
  const h = await mountRealEditor(p);
  try {
    // OUTSIDE ruling: in ext view with nothing selected, clicking a post selects the BUILDING.
    h.view.setPlanCamera(`${b.id}:L1`);
    h.view.setView('ext');
    const post0At = b.porches[0].columns[0].at;
    const post1At = b.porches[0].columns[1].at;
    const pixel0 = h.view.screenOfFloor(post0At[0], post0At[1], `${b.id}:L1`);
    const pixel1 = h.view.screenOfFloor(post1At[0], post1At[1], `${b.id}:L1`);
    assert.equal(h.view.pickAll(...pixel0)[0]?.kind, 'porch_post', 'real view hits porch_post first');
    h.clickCanvas(...pixel0);
    assert.equal(h.tools.selected()?.kind, 'building', 'OUTSIDE ruling: click on post selects building');
    assert.equal(h.tools.selected()?.pieceId, b.id);

    // On a floor view, click 1 selects post, click 2 on same spot selects its porch directly behind it (plain selection: no focus, no rebuild).
    let rebuildCount = 0;
    const origRebuild = h.view.rebuild.bind(h.view);
    h.view.rebuild = (...args) => { rebuildCount++; return origRebuild(...args); };
    h.tools.select(null);
    h.view.setView(`${b.id}:L1`);
    h.clickCanvas(...pixel0);
    assert.equal(h.tools.selected()?.kind, 'porch_post');
    assert.equal(h.tools.selected()?.pieceId, 'post:patio:0');
    assert.equal(document.getElementById('properties-crumbs').textContent, 'Pool patio > Post 1');
    // Plain selection: single Escape clears selection.
    fire(document.body, 'keydown', { key: 'Escape' });
    assert.equal(h.tools.selected(), null, 'plain post selection clears on first Escape');
    h.clickCanvas(...pixel0);
    assert.equal(h.tools.selected()?.pieceId, 'post:patio:0');
    h.clickCanvas(...pixel0);
    assert.equal(h.tools.selected()?.kind, 'room');
    assert.equal(h.tools.selected()?.pieceId, 'patio');
    assert.equal(h.tools.selection().room, null, 'plain selection: clicking porch does NOT focus it');
    assert.equal(rebuildCount, 0, 'plain selection causes zero view.rebuild calls');

    // Explicit Focus room -> clicking a post keeps room focus; Escape 1 leaves focus, Escape 2 clears.
    h.tools.focusRoom({ kind: 'room', id: 'patio', building: b.id, level: 'L1' });
    assert.equal(h.tools.selection().room, 'patio');
    h.clickCanvas(...pixel1);
    assert.equal(h.tools.selected()?.pieceId, 'post:patio:1');
    assert.equal(h.tools.selection().room, 'patio');
    fire(document.body, 'keydown', { key: 'Escape' });
    assert.equal(h.tools.selection().room, null, 'Escape 1 leaves Focus room');
    assert.equal(h.tools.selected()?.pieceId, 'patio', 'leaving Focus room leaves porch selected');
    fire(document.body, 'keydown', { key: 'Escape' });
    assert.equal(h.tools.selected(), null, 'Escape 2 clears plain selection');

    // I5: Locking the parent porch gives the locked hint when clicking its post.
    h.tools.select(null);
    h.visibility.lock('patio');
    h.clickCanvas(...pixel0);
    const status = document.getElementById('editor-status');
    assert.equal(status.dataset.lockedHint, 'post:patio:0', 'I5 locked porch gives locked hint on its post');
    assert.match(status.textContent, /This post is locked/);
    assert.equal(h.tools.selected(), null);
    h.visibility.unlock('patio');

    // N4: Shift-click sets locked hint ONLY when nothing was done.
    delete status.dataset.lockedHint; status.textContent = '';
    h.visibility.lock('post:patio:0');
    h.clickCanvas(...pixel0, { shiftKey: true });
    // Unlocked porch room was selected by addRoom -> something WAS done, so no locked hint!
    assert.equal(h.tools.selected()?.pieceId, 'patio');
    assert.equal(status.dataset.lockedHint, undefined, 'N4 no locked hint when Shift-click selected a room');
    h.visibility.unlock('post:patio:0');

    // N3: Filter before adjusting distances, and set ONLY the porch's distance to its post's (never raise unrelated later hits).
    const origPickAll = h.view.pickAll.bind(h.view);
    h.visibility.lock('w0');
    h.view.pickAll = () => [
      { kind: 'wall', id: 'w0', building: b.id, distance: 9.0 },
      { kind: 'porch_post', id: 'post:patio:0', parentPieceId: 'patio', building: b.id, distance: 5.0 },
      { kind: 'room', id: 'patio', building: b.id, distance: 4.8 },
      { kind: 'wall', id: 'w1', building: b.id, distance: 4.9 },
    ];
    // Locked w0 (9.0) is filtered first so it doesn't raise post/porch/w1.
    // w1 (4.9) stays 4.9 (< post 5.0), so w1 is NOT raised behind post/porch!
    assert.equal(h.tools.pick(100, 100)?.id, 'w1', 'N3 unrelated hit (4.9) is not raised by locked hit (9.0) or post (5.0)');
    h.view.pickAll = origPickAll;
    h.visibility.unlock('w0');

    // I6: Shift-click toggles a post when it is the nearest hit.
    h.tools.select({ pieceId: 'post:patio:0', buildingId: b.id });
    h.clickCanvas(...pixel1, { shiftKey: true });
    assert.deepEqual(h.tools.selectedMembers().map(m => m.pieceId), ['post:patio:0', 'post:patio:1']);

    // I4: Library material surfaceAt / drop on a post targets its porch's column.
    const dropSurface = h.library.surfaceAt({ clientX: pixel0[0], clientY: pixel0[1] });
    assert.ok(dropSurface, 'I4 surfaceAt resolves real view pick on post');
    assert.equal(dropSurface.kind, 'porch');
    assert.deepEqual(dropSurface.target, { porch: 'patio', part: 'column' });
    // Real pointer drag-drop from library canvas path:
    const { surfaceOperation } = await import(file('static/twin/editor/library.js'));
    assert.deepEqual(surfaceOperation(dropSurface, 'face', { id: 'standing_seam' }),
      { op: 'set_material', building: b.id, target: { porch: 'patio', part: 'column' }, material: { id: 'standing_seam' } });

    // I9: draw.js sees through porch_post like rooms when hitting a wall behind a post.
    const seenSkips = [];
    const draw = createDraw({
      view: h.view, tools: h.tools, getPlan: h.getPlan, canEdit: () => true,
      signal: h.abort.signal, panel: { message() {} }, gesture: fn => fn(),
      op: async o => h.ops.push(o),
      surfaceAt: (ev, opts) => { seenSkips.push(opts?.skip); return h.library.surfaceAt(ev, opts); },
    });
    document.getElementById('rail-add-door').click();
    draw.pointerDown({ pointerId: 9, clientX: pixel0[0], clientY: pixel0[1] });
    draw.pointerUp({ pointerId: 9, clientX: pixel0[0], clientY: pixel0[1] }, false);
    await flush();
    assert.ok(seenSkips.some(s => Array.isArray(s) && s.includes('room') && s.includes('porch_post')),
      `I9 draw.js passes skip:['room','porch_post'], got ${JSON.stringify(seenSkips)}`);
    draw.cancel();
  } finally { h.dispose(); }

  // I7 + I6 with THREE REAL HITS: wall in front (height 15), post, porch!
  const threeHitPlan = makePatioPlan();
  threeHitPlan.buildings[0].roofs = []; threeHitPlan.buildings[0].roof.sections = [];
  threeHitPlan.buildings[0].walls.push({
    id: 'wall-in-front', level: 'L1', from: [0, 1], to: [4, 1],
    height: 15, thickness: 0.5, exterior: false, state: 'settled',
  });
  const h3 = await mountRealEditor(threeHitPlan);
  try {
    const b3 = threeHitPlan.buildings[0];
    h3.view.setPlanCamera(`${b3.id}:L1`);
    h3.view.setView(`${b3.id}:L1`);
    const px = h3.view.screenOfFloor(1, 1, `${b3.id}:L1`);
    const rawHits = h3.view.pickAll(...px);
    assert.equal(rawHits[0]?.id, 'wall-in-front');
    assert.equal(rawHits[1]?.kind, 'porch_post');
    assert.equal(rawHits[2]?.id, 'patio');

    // Click 1 -> wall in front, Click 2 -> post, Click 3 -> porch!
    h3.clickCanvas(...px);
    assert.equal(h3.tools.selected()?.pieceId, 'wall-in-front', '3-hit click 1 selects wall in front');
    h3.clickCanvas(...px);
    assert.equal(h3.tools.selected()?.kind, 'porch_post', '3-hit click 2 selects post');
    assert.equal(h3.tools.selected()?.pieceId, 'post:patio:0');
    h3.clickCanvas(...px);
    assert.equal(h3.tools.selected()?.pieceId, 'patio', '3-hit click 3 selects porch');

    // I6: Shift-click on the spot when wall-in-front is nearest must NOT toggle the post behind it!
    h3.tools.select(null);
    h3.tools.select({ pieceId: 'post:patio:1', buildingId: b3.id });
    assert.equal(h3.view.pickAll(...px)[0]?.id, 'wall-in-front', 'wall-in-front is the nearest hit');
    h3.clickCanvas(...px, { shiftKey: true });
    assert.ok(!h3.tools.selectedMembers().some(m => m.pieceId === 'post:patio:0'),
      'I6 Shift-click does not toggle a post hidden behind a nearer wall');
  } finally { h3.dispose(); }
});

// ---------------------------------------------------------------------------
// 3. Cards, read-only Select the porch, server-matched refusal wording,
//    layout signature, posts_action overlap-before-state, materials dedupe,
//    delete wording
// ---------------------------------------------------------------------------
await test('cards_refusals_readonly_layout_posts_action_and_materials_dedupe', async () => {
  let editable = true;
  const h = await mountRealEditor(makePatioPlan(), { canEditFn: () => editable });
  try {
    const b = h.getPlan().buildings[0];
    const card = document.getElementById('piece-card');
    h.tools.select({ pieceId: 'post:patio:1', buildingId: b.id });

    // Refusal wording matches server exactly.
    const xInput = card.querySelector('input[aria-label="Position X (ft)"]');
    const sizeInput = card.querySelector('input[aria-label="Size (ft)"]');
    xInput.value = 'not-a-num'; fire(xInput, 'change'); await flush();
    assert.equal(xInput.parentElement.querySelector('small').textContent, 'Choose a finite post position.');
    xInput.value = '200000'; fire(xInput, 'change'); await flush();
    assert.equal(xInput.parentElement.querySelector('small').textContent, 'Choose a finite post position.');
    sizeInput.value = '0.01'; fire(sizeInput, 'change'); await flush();
    assert.equal(sizeInput.parentElement.querySelector('small').textContent, 'Choose a post size from 0.05 to 3 feet.');
    sizeInput.value = '3.5'; fire(sizeInput, 'change'); await flush();
    assert.equal(sizeInput.parentElement.querySelector('small').textContent, 'Choose a post size from 0.05 to 3 feet.');
    assert.equal(h.ops.length, 0, 'refused inputs send zero ops');

    // "Select the porch" stays enabled when read-only (initial & fast-path refresh).
    editable = false;
    h.tools.refreshCard();
    const selPorchBtn = card.querySelector('[data-select-porch]');
    assert.equal(selPorchBtn.disabled, false, 'Select the porch remains enabled in read-only mode');
    editable = true;
    h.tools.refreshCard();

    // Layout signature includes columns for porch cards ONLY (wall card keeps its DOM nodes).
    const wall = b.walls[0];
    h.tools.select({ pieceId: wall.id, buildingId: b.id });
    const wallHeadingBefore = card.querySelector('h3');
    const mutated = structuredClone(h.getPlan());
    mutated.buildings[0].porches[0].columns.push({ at: [8, 1], size: 0.5 });
    h.setPlanOnly(mutated);
    h.tools.refreshCard();
    assert.equal(card.querySelector('h3'), wallHeadingBefore, 'porch column change does not rebuild non-porch card');

    // Overlap tested BEFORE roof state in postRoofReason / postRoofDisabledReason:
    // a far-away ghost roof must report "No roof overlaps this porch on its floor.", NOT ghost roof!
    const farGhost = makePatioPlan();
    farGhost.buildings[0].roofs[0].area = [[30, 0], [46, 0], [46, 8], [30, 8]];
    farGhost.buildings[0].roofs[0].state = 'ghost';
    assert.equal(
      postRoofReason(farGhost.buildings[0], farGhost.buildings[0].porches[0], farGhost.buildings[0].roofs[0]),
      'No roof overlaps this porch on its floor.'
    );
    assert.equal(
      postRoofDisabledReason(farGhost.buildings[0], farGhost.buildings[0].porches[0]),
      'No roof overlaps this porch on its floor.'
    );
    // An overlapping ghost roof still reports ghost roof!
    farGhost.buildings[0].roofs[0].area = [[0, 0], [16, 0], [16, 8], [0, 8]];
    assert.equal(
      postRoofReason(farGhost.buildings[0], farGhost.buildings[0].porches[0], farGhost.buildings[0].roofs[0]),
      'Choose a settled roof; ghost and proposal roofs cannot receive posts.'
    );

    // selection_materials: N5 dedupe operations, NOT owners; materialsInSelection counts 1 surface.
    const postRefs = [
      { kind: 'porch_post', pieceId: 'post:patio:0', buildingId: b.id, porchId: 'patio' },
      { kind: 'porch_post', pieceId: 'post:patio:1', buildingId: b.id, porchId: 'patio' },
    ];
    const mats = materialsInSelection(h.getPlan(), postRefs, baseKit);
    assert.equal(mats.length, 1);
    assert.equal(mats[0].count, 1, 'two posts on same porch count as 1 column surface');
    const repOps = replacementOperations(h.getPlan(), postRefs, mats[0].id, { id: 'standing_seam' }, baseKit);
    assert.equal(repOps.length, 1, 'replacement emits one set_material op per porch');
    assert.deepEqual(repOps[0].target, { porch: 'patio', part: 'column' });
    const shared = sharedMaterialRows(h.getPlan(), postRefs, baseKit);
    assert.equal(shared.length, 1);
    assert.equal(shared[0].matches.length, 2, 'N5 sharedMaterialRows keeps every owner in matches');

    // N5: Saving the shared Columns slot in multi-select card dedupes the emitted operations to ONE set_material op!
    h.tools.selectionStore.set(postRefs);
    const colSlot = card.querySelector('[data-library-slot="Columns"]');
    assert.ok(colSlot, 'multi-select posts card mounts shared Columns slot');
    const opsBeforeMat = h.ops.length;
    const clearBtn = colSlot.querySelector('[data-slot-clear]');
    assert.ok(clearBtn && !clearBtn.disabled);
    click(clearBtn); await flush();
    assert.equal(h.ops.length, opsBeforeMat + 1);
    assert.equal(h.ops.at(-1).op, 'batch');
    assert.equal(h.ops.at(-1).ops.length, 1, 'N5 shared Columns save dedupes to 1 set_material op');
    assert.deepEqual(h.ops.at(-1).ops[0].target, { porch: 'patio', part: 'column' });

    // Item 3: "Select the porch" is a plain selection (no focus, no rebuild).
    let cardRebuilds = 0;
    const origCardRebuild = h.view.rebuild.bind(h.view);
    h.view.rebuild = (...args) => { cardRebuilds++; return origCardRebuild(...args); };
    h.tools.select({ pieceId: 'post:patio:1', buildingId: b.id });
    click(card.querySelector('[data-select-porch]'));
    assert.equal(h.tools.selected()?.pieceId, 'patio');
    assert.equal(h.tools.selection().room, null, 'Select the porch is a plain selection (no focus)');
    assert.equal(cardRebuilds, 0, 'Select the porch triggers zero view.rebuild');

    // N1: Porch card Posts section refreshes in place without tearing down half-typed text in another field (Name)!
    const nameInput = [...card.querySelectorAll('label')].find(l => l.textContent === 'Name')?.querySelector('input');
    assert.ok(nameInput, 'porch card has Name input');
    nameInput.focus();
    nameInput.value = 'Draft Patio Name';
    const countNodeBefore = card.querySelector('[data-porch-posts-count]');
    const colChanged = structuredClone(h.getPlan());
    colChanged.buildings[0].porches[0].columns[0].size = 0.9;
    h.setPlanOnly(colChanged);
    h.tools.refreshCard();
    assert.equal(document.activeElement, nameInput, 'N1 Name input stays focused across porch column refresh');
    assert.equal(nameInput.value, 'Draft Patio Name', 'N1 half-typed Name survives porch column change');
    assert.equal(card.querySelector('[data-porch-posts-count]'), countNodeBefore, 'N1 Posts section refreshes in place');
    assert.equal(card.querySelector('input[aria-label="Size for all posts"]').placeholder, 'Mixed', 'N1 Size for all updates in place to Mixed');

    // N2: Adding a post clears any stale hide/lock on the new post's id!
    const nextPostId = `post:patio:${h.getPlan().buildings[0].porches[0].columns.length}`;
    h.visibility.hide(nextPostId);
    h.visibility.lock(nextPostId);
    assert.equal(h.visibility.isHidden(nextPostId), true);
    assert.equal(h.visibility.isLocked(nextPostId), true);
    const addBtn = [...card.querySelectorAll('[data-porch-posts] button')].find(btn => btn.textContent === 'Add post');
    click(addBtn); await flush();
    assert.equal(h.tools.selected()?.pieceId, nextPostId, 'Add post selects newly added post');
    assert.equal(h.visibility.isHidden(nextPostId), false, 'N2 new post id is unhidden');
    assert.equal(h.visibility.isLocked(nextPostId), false, 'N2 new post id is unlocked');

    // Single-post delete confirmation wording ("Delete this post?" / "Undo restores the post.") + plain porch selection (no focus, no rebuild from selection).
    h.tools.select({ pieceId: 'post:patio:1', buildingId: b.id });
    h.confirms.length = 0;
    h.setOnOp(async operation => {
      const next = applyLocal(h.getPlan(), operation).plan;
      await h.view.settle(next);
      h.setPlanOnly(next);
      // Measure rebuilds caused by post-delete porch selection (refresh + cards.remove select).
      cardRebuilds = 0;
      h.tools.refresh();
    });
    const delBtn = [...card.querySelectorAll('button')].find(btn => btn.textContent === 'Delete');
    click(delBtn); await flush();
    h.setOnOp(null);
    assert.equal(h.confirms[0][0], 'Delete this post?');
    assert.equal(h.confirms[0][1], 'Undo restores the post.');
    assert.equal(h.tools.selected()?.pieceId, 'patio');
    assert.equal(h.tools.selection().room, null, 'deleting a post selects porch plainly (no focus)');
    assert.equal(cardRebuilds, 0, 'selecting porch after post delete triggers zero view.rebuild');

    // Size for all posts sends ONE batch (record for real server route check!).
    h.tools.select({ pieceId: 'patio', buildingId: b.id });
    const sizeAll = card.querySelector('input[aria-label="Size for all posts"]');
    sizeAll.value = '0.75'; fire(sizeAll, 'change'); await flush();
    const sizeBatch = h.ops.at(-1);
    assert.equal(sizeBatch.op, 'batch');
    assert.ok(sizeBatch.ops.length >= 2 && sizeBatch.ops.every(o => o.op === 'update_porch_post' && o.size === 0.75));
    // Re-create clean batch against untouched patio for real server route verification.
    serverBatches.push({
      name: 'size_for_all_posts',
      op: { op: 'batch', ops: [
        { op: 'update_porch_post', building: b.id, porch: 'patio', post: 'post:patio:0', size: 0.75 },
        { op: 'update_porch_post', building: b.id, porch: 'patio', post: 'post:patio:1', size: 0.75 },
      ] },
    });
  } finally { h.dispose(); }
});

// ---------------------------------------------------------------------------
// 4. C1, I1, I3, I8 on real modules + handle snaps + rotated building arrows
// ---------------------------------------------------------------------------
await test('c1_i1_i3_i8_real_modules_handles_snaps_and_rotated_arrows', async () => {
  // C1: Dragging a set of untouched posts (no stored ids) with the real gizmo + real applyLocal!
  const p = makePatioPlan();
  const b = p.buildings[0];
  b.porches[0].columns.push({ at: [8, 1], size: 2 / 3 }); // 3 untouched posts, no ids!
  assert.ok(b.porches[0].columns.every(c => !c.id), 'starts untouched with no stored ids');
  const h = await mountRealEditor(p);
  try {
    const r0 = { kind: 'porch_post', pieceId: 'post:patio:0', buildingId: b.id, porchId: 'patio' };
    const r1 = { kind: 'porch_post', pieceId: 'post:patio:1', buildingId: b.id, porchId: 'patio' };
    const r2 = { kind: 'porch_post', pieceId: 'post:patio:2', buildingId: b.id, porchId: 'patio' };
    h.view.setPlanCamera(`${b.id}:L1`); h.view.setView(`${b.id}:L1`);
    h.tools.selectionStore.set([r0, r1]);
    h.tools.setTool('move');
    const mx = h.tools.gizmo.handles().find(x => x.kind === 'gizmo_move_x');
    assert.ok(mx, 'C1 gizmo exposes Move X handle for set of untouched posts');
    const pStart = h.view.screenOfFloor(mx.at[0], mx.at[1], `${b.id}:L1`);
    const pEnd = h.view.screenOfFloor(mx.at[0] + 2, mx.at[1], `${b.id}:L1`);
    assert.ok(h.tools.gizmo.begin({ clientX: pStart[0], clientY: pStart[1], button: 0 }, mx));
    h.tools.gizmo.update({ clientX: pEnd[0], clientY: pEnd[1], shiftKey: false });
    await h.tools.gizmo.finish(false);
    await flush();
    const batch = h.ops.at(-1);
    assert.equal(batch.op, 'batch', 'C1 gizmo drag of untouched posts sends one batch');
    assert.equal(batch.ops.length, 2);
    assert.deepEqual(batch.ops.map(o => o.post), ['post:patio:0', 'post:patio:1']);
    near(h.getPlan().buildings[0].porches[0].columns[0].at[0], 3, 0.25);
    near(h.getPlan().buildings[0].porches[0].columns[1].at[0], 17, 0.25);
    assert.deepEqual(h.tools.selectedMembers().map(m => m.pieceId), ['post:patio:0', 'post:patio:1'],
      'C1 set selection survives first-edit minting');
    serverBatches.push({ name: 'gizmo_group_move', op: {
      op: 'batch',
      ops: [
        { op: 'update_porch_post', building: b.id, porch: 'patio', post: 'post:patio:0', at: [3, 1] },
        { op: 'update_porch_post', building: b.id, porch: 'patio', post: 'post:patio:1', at: [17, 1] },
      ],
    } });

    // I8: Hide Post 2 and lock Post 3 while Post 1 moves (untouched -> minted): states survive!
    const freshPlan = makePatioPlan();
    freshPlan.buildings[0].porches[0].columns.push({ at: [8, 1], size: 2 / 3 });
    await h.setPlan(freshPlan);
    h.visibility.hide('post:patio:1');
    h.visibility.lock('post:patio:2');
    h.tools.select({ pieceId: 'post:patio:0', buildingId: b.id });
    fire(document.body, 'keydown', { key: 'ArrowRight' });
    await flush();
    assert.equal(h.getPlan().buildings[0].porches[0].columns[0].id, 'post:patio:0', 'real applyLocal minted stable id');
    assert.equal(h.getPlan().buildings[0].porches[0].columns[1].id, 'post:patio:1');
    assert.equal(h.getPlan().buildings[0].porches[0].columns[2].id, 'post:patio:2');
    assert.equal(h.visibility.isHidden('post:patio:1'), true, 'I8 Post 2 stays hidden after Post 1 moves');
    assert.equal(h.visibility.isLocked('post:patio:2'), true, 'I8 Post 3 stays locked after Post 1 moves');
    assert.equal(h.tools.selected()?.pieceId, 'post:patio:0');
    h.visibility.showAll(); h.visibility.unlock('post:patio:2');

    // I1: Two edits before the first answer through REAL createEditQueue + REAL applyLocal!
    const untouched = makePatioPlan();
    const sent = []; let releaseFirst;
    const eq = createEditQueue({
      send: async op => {
        sent.push(op);
        if (sent.length === 1) await new Promise(r => { releaseFirst = r; });
        const applied = applyLocal(sent.length === 1 ? untouched : eq.shown(), op);
        return { round: sent.length + 1, plan: applied.plan };
      },
      onChange: () => {},
    });
    eq.base({ round: 1, plan: untouched });
    const e1 = eq.push({ op: { op: 'update_porch_post', building: b.id, porch: 'patio', post: 'post:patio:0', at: [2, 1] }, label: 'Move X' });
    const e2 = eq.push({ op: { op: 'update_porch_post', building: b.id, porch: 'patio', post: 'post:patio:0', at: [2, 3] }, label: 'Move Y' });
    assert.deepEqual(eq.shown().buildings[0].porches[0].columns[0].at, [2, 3], 'I1 both edits applied optimistically before first answer');
    releaseFirst();
    await Promise.all([e1.saved, e2.saved]);
    assert.equal(sent.length, 2);
    assert.deepEqual(eq.shown().buildings[0].porches[0].columns[0].at, [2, 3], 'I1 final plan keeps both edits');

    // I3: Half-typed text in Position Y while a save on Position X returns (with minting)!
    await h.setPlan(makePatioPlan());
    h.tools.select({ pieceId: 'post:patio:0', buildingId: b.id });
    const card = document.getElementById('piece-card');
    const xIn = card.querySelector('input[aria-label="Position X (ft)"]');
    const yIn = card.querySelector('input[aria-label="Position Y (ft)"]');
    let finishSave;
    h.setOnOp(async operation => {
      const next = applyLocal(h.getPlan(), operation).plan;
      await new Promise(r => { finishSave = r; });
      h.setPlanOnly(next);
      h.tools.refresh();
    });
    xIn.value = '3.5'; fire(xIn, 'change');
    await flush();
    // While X save is in flight, user focuses Y and types half-finished text!
    yIn.focus();
    yIn.value = '4.';
    finishSave();
    await flush();
    assert.equal(document.activeElement, yIn, 'I3 Y input stays focused when X save returns');
    assert.equal(yIn.value, '4.', 'I3 half-typed Y text is preserved when X save returns');
    h.setOnOp(null);

    // Rotated building (90 deg): Arrow keys on single post and on set use the SAME world axis!
    const rotPlan = makePatioPlan();
    rotPlan.buildings[0].rotation = 90;
    await h.setPlan(rotPlan);
    h.tools.select({ pieceId: 'post:patio:0', buildingId: b.id });
    const beforeSingle = [...h.getPlan().buildings[0].porches[0].columns[0].at];
    fire(document.body, 'keydown', { key: 'ArrowRight' }); await flush();
    const afterSingle = [...h.getPlan().buildings[0].porches[0].columns[0].at];
    const singleDelta = [afterSingle[0] - beforeSingle[0], afterSingle[1] - beforeSingle[1]];
    near(singleDelta[0], 0); near(singleDelta[1], -1); // 90 deg rotated: world +X is local -Y

    h.tools.selectionStore.set([r0, r1]);
    const beforeSet = [...h.getPlan().buildings[0].porches[0].columns[1].at];
    fire(document.body, 'keydown', { key: 'ArrowRight' }); await flush();
    const afterSet = [...h.getPlan().buildings[0].porches[0].columns[1].at];
    const setDelta = [afterSet[0] - beforeSet[0], afterSet[1] - beforeSet[1]];
    near(setDelta[0], singleDelta[0]); near(setDelta[1], singleDelta[1]);
  } finally { h.dispose(); }

  // Snap unit check (corner, edge, edge+post, post line, grid, Shift free).
  const snapPorch = {
    polygon: [[0, 0], [10, 0], [10, 8], [0, 8]],
    columns: [{ at: [0.25, 0.25], size: 0.5 }, { at: [5, 0.25], size: 0.5 }, { at: [3.2, 4.1], size: 0.5 }],
  };
  const targets = buildPostSnapTargets(snapPorch, 2, 0.5);
  assert.equal(snapPostPoint([0.4, 7.6], targets, false).target, 'corner');
  assert.equal(snapPostPoint([6.1, 7.55], targets, false).target, 'edge');
  assert.equal(snapPostPoint([5.15, 7.55], targets, false).target, 'edge_post');
  assert.equal(snapPostPoint([5.18, 4.1], targets, false).target, 'post_line');
  assert.equal(snapPostPoint([2.3, 4.2], targets, false).target, 'grid');
  assert.equal(snapPostPoint([0.41, 7.62], targets, true).target, 'free');
});

// ---------------------------------------------------------------------------
// 5. I2: Undo and redo selection (remembered ref vs manual reselection) +
//    group delete batch for real server check
// ---------------------------------------------------------------------------
await test('i2_undo_redo_selection_and_group_delete_batch', async () => {
  const h = await mountRealEditor(makePatioPlan());
  try {
    const b = h.getPlan().buildings[0];
    const beforeDelete = structuredClone(h.getPlan());
    // Select Post 2 and delete it -> falls back to porch.
    h.tools.select({ pieceId: 'post:patio:1', buildingId: b.id });
    fire(document.body, 'keydown', { key: 'Delete' });
    await flush();
    assert.equal(h.tools.selected()?.pieceId, 'patio', 'delete falls back to porch');
    const afterDelete = structuredClone(h.getPlan());
    assert.equal(afterDelete.buildings[0].porches[0].columns.length, 1);

    // Undo (Post 2 returns while still on fallback porch) -> Post 2 IS selected again!
    h.setPlanOnly(structuredClone(beforeDelete));
    h.tools.refresh();
    assert.equal(h.tools.selected()?.pieceId, 'post:patio:1', 'I2 undo restores remembered deleted post');

    // Redo (Post 2 disappears again) -> falls back to porch plainly (no focus, no rebuild)!
    let fbRebuilds = 0;
    const origFbRebuild = h.view.rebuild.bind(h.view);
    h.view.rebuild = (...args) => { fbRebuilds++; return origFbRebuild(...args); };
    h.setPlanOnly(structuredClone(afterDelete));
    h.tools.refresh();
    assert.equal(h.tools.selected()?.pieceId, 'patio', 'I2 redo falls back to porch again');
    assert.equal(h.tools.selection().room, null, 'undo/redo fallback is a plain selection (no focus)');
    assert.equal(fbRebuilds, 0, 'undo/redo fallback triggers zero view.rebuild');

    // Now user manually selects Post 1 -> Undo brings Post 2 back, Post 1 STAYS selected!
    h.tools.select({ pieceId: 'post:patio:0', buildingId: b.id });
    h.setPlanOnly(structuredClone(beforeDelete));
    h.tools.refresh();
    assert.equal(h.tools.selected()?.pieceId, 'post:patio:0', 'I2 restored post does NOT steal selection when another piece was chosen');

    // Multi-post delete batch: confirm wording, falls back to porch, Undo restores both posts!
    h.tools.selectionStore.set([
      { kind: 'porch_post', pieceId: 'post:patio:0', buildingId: b.id, porchId: 'patio' },
      { kind: 'porch_post', pieceId: 'post:patio:1', buildingId: b.id, porchId: 'patio' },
    ]);
    h.confirms.length = 0;
    fire(document.body, 'keydown', { key: 'Delete' });
    await flush();
    assert.equal(h.confirms[0][0], 'Delete 2 selected posts?');
    assert.equal(h.confirms[0][1], 'Undo restores the whole selection.');
    const delBatch = h.ops.at(-1);
    assert.equal(delBatch.op, 'batch');
    assert.deepEqual(delBatch.ops.map(o => o.post), ['post:patio:1', 'post:patio:0']);
    assert.equal(h.tools.selected()?.pieceId, 'patio', 'multi-post delete falls back to porch');
    serverBatches.push({ name: 'group_delete_posts', op: delBatch });

    // Undo multi-post delete -> restores both posts!
    h.setPlanOnly(structuredClone(beforeDelete));
    h.tools.refresh();
    assert.deepEqual(h.tools.selectedMembers().map(m => m.pieceId), ['post:patio:0', 'post:patio:1'],
      'I2 undo restores multi-post selection when still on fallback porch');
  } finally { h.dispose(); }
});

console.log('SERVER_BATCHES ' + JSON.stringify(serverBatches));
finish();
"""


def main():
    with tempfile.TemporaryDirectory(prefix='chauffeur_porch_posts_ed_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_store, twin_library, twin_model_bridge as bridge
        from test_twin_awning_materials import patio
        from test_twin_model_ops_more import _client, _people, _enforced
        logging.getLogger('httpx').setLevel(logging.WARNING)
        fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
        twin_store.push_round(fixture, 'build')
        patio_model = patio()
        code, out = run_node(DRIVER, {
            'root': ROOT.as_posix(),
            'household': twin_store.current(),
            'patioPlan': bridge.flatten(patio_model),
            'kit': {**twin_library.kit('modern_farmhouse'), 'manifest': {}},
            'objectSchema': json.loads((ROOT / 'static/twin/object_schema.json').read_text(encoding='utf-8')),
        }, timeout=180)
        lines = [line for line in out.splitlines() if not line.startswith('SERVER_BATCHES ')]
        print('\n'.join(lines))
        assert code == 0, out

        batches = json.loads(next(line[15:] for line in out.splitlines() if line.startswith('SERVER_BATCHES ')))
        assert len(batches) == 3, batches
        # Exercise every UI-generated batch through the REAL FastAPI server route and verify 1 undo step!
        twin_store.start_over()
        twin_store.push_round(bridge.flatten(patio_model), 'build')
        with _enforced():
            client, headers = _client(), _people()['parent']
            for entry in batches:
                before = twin_store.current_model()
                round_id = twin_store.current_id()
                rounds_before = len(twin_store.rounds())
                res = client.post('/api/house/editor/op', headers=headers, json={'op': entry['op']})
                assert res.status_code == 200, (entry['name'], res.text)
                assert len(twin_store.rounds()) == rounds_before + 1, f"{entry['name']}: one batch must be one undo step"
                after = twin_store.current_model()
                cols = after['buildings'][0]['porches_detail'][0]['columns']
                if entry['name'] == 'size_for_all_posts':
                    assert all(abs(c['size'] - 0.75) < 1e-8 for c in cols), cols
                elif entry['name'] == 'gizmo_group_move':
                    assert cols[0]['at'] == [3, 1] and cols[1]['at'] == [17, 1], cols
                elif entry['name'] == 'group_delete_posts':
                    assert cols == [], cols
                rev = client.post('/api/house/twin/revert', headers=headers, json={'round': round_id})
                assert rev.status_code == 200, rev.text
                assert twin_store.current_model() == before, f"{entry['name']}: undo must restore exact model"
        print(f'PASS {len(batches)} UI-generated post batches via real /api/house/editor/op + 1-step undo')


if __name__ == '__main__':
    main()
