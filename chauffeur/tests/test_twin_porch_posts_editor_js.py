"""Porch posts editor tests under Node using the real production ES modules."""
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE = await import(three);
globalThis.fetch = async () => new Response(JSON.stringify({ materials: [], items: [], imports: [] }));
window.twinObjectSchema = { kinds: {}, opening: {} };

const { porchPosts, postRef, findPost, POST_SIZE } = await import(file('static/twin/porch_posts.js'));
const { sceneRows, createSceneTree } = await import(file('static/twin/editor/scene_tree.js'));
const { createVisibility } = await import(file('static/twin/editor/visibility.js'));
const { createSelection, createRoomSelection } = await import(file('static/twin/editor/selection.js'));
const { findPiece, deleteOperation } = await import(file('static/twin/editor/piece_operations.js'));
const { createCards } = await import(file('static/twin/editor/cards.js'));
const { createDock, propertyPath } = await import(file('static/twin/editor/dock.js'));
const { createHandles } = await import(file('static/twin/editor/handles.js'));
const { createGizmo } = await import(file('static/twin/editor/gizmo.js'));
const { createSceneTools } = await import(file('static/twin/editor/scene_tools.js'));
const { groupRecord, canTransform, groupTransform, transformOperations, deleteOperations } = await import(file('static/twin/editor/group_transform.js'));
const { selectionBoxes } = await import(file('static/twin/editor/selection_bounds.js'));
const { createMarquee } = await import(file('static/twin/editor/marquee.js'));
const { buildPostSnapTargets, snapPostPoint, postRoofDisabledReason } = await import(file('static/twin/editor/porch_post_shelf.js'));
const { materialLines } = await import(file('static/twin/editor/library.js'));

const near = (a, b, tol = 1e-4) => assert.ok(Math.abs(a - b) <= tol, `${a} near ${b}`);
const flush = async () => { await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0)); };

const household = input.household;
const householdModel = input.model;
const kit = input.kit;

// ---------------------------------------------------------------------------
// 1. Tree rows on the real household fixture + orphan porch + hide/lock
// ---------------------------------------------------------------------------
await test('scene_tree_household_posts_orphan_hide_lock', () => {
  const rows = sceneRows(household);
  // No porch listed twice.
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

  // Orphan porch (no room of the same id) still parents its Post N rows in stored order.
  const orphanPlan = {
    buildings: [{
      id: 'b1', name: 'House', levels: [{ id: 'L1', name: 'Main', elevation: 0, ceiling: 9 }],
      rooms: [], walls: [], openings: [],
      porches: [{ id: 'orphan-porch', name: 'Side Porch', level: 'L1', polygon: [[0, 0], [10, 0], [10, 6], [0, 6]],
        columns: [{ at: [0.5, 0.5], size: 0.5 }, { at: [9.5, 0.5], size: 0.5 }] }],
    }], site: {},
  };
  const orphanRows = sceneRows(orphanPlan);
  assert.equal(orphanRows.filter(r => r.id === 'orphan-porch').length, 1);
  const orphanPosts = orphanRows.filter(r => r.kind === 'porch_post');
  assert.deepEqual(orphanPosts.map(r => [r.name, r.parent.id, r.id]), [
    ['Post 1', 'orphan-porch', 'post:orphan-porch:0'],
    ['Post 2', 'orphan-porch', 'post:orphan-porch:1'],
  ]);

  // Hide and lock per row and inherited from the parent porch.
  const host = document.createElement('div'); host.clientHeight = 400; document.body.append(host);
  const vis = createVisibility({ storage: null });
  let picked = null;
  const tree = createSceneTree({ host, getPlan: () => orphanPlan, getSelection: () => picked,
    select: r => { picked = r; tree.reveal(r.id, r.building); }, visibility: vis,
    floors: { current: () => 'b1:L1', hidden: () => false } });
  tree.reveal('post:orphan-porch:0', 'b1');
  const rowEl = id => host.querySelector(`[data-scene-id="${id}"]`);
  assert.ok(rowEl('post:orphan-porch:0'));
  assert.ok(rowEl('post:orphan-porch:1'));
  click(rowEl('post:orphan-porch:0').querySelector('[data-row-eye]'));
  assert.equal(vis.isHidden('post:orphan-porch:0'), true);
  assert.equal(rowEl('post:orphan-porch:0').style.opacity, '0.5');
  assert.equal(rowEl('post:orphan-porch:1').style.opacity, '1');
  click(rowEl('post:orphan-porch:0').querySelector('[data-row-eye]'));
  assert.equal(vis.isHidden('post:orphan-porch:0'), false);
  // Lock per row
  click(rowEl('post:orphan-porch:1').querySelector('[data-row-lock]'));
  assert.equal(vis.isLocked('post:orphan-porch:1'), true);
  assert.equal(rowEl('post:orphan-porch:1').querySelector('[data-row-lock]').getAttribute('aria-pressed'), 'true');
  assert.equal(vis.isPickable({ kind: 'porch_post', pieceId: 'post:orphan-porch:1', parentPieceId: 'orphan-porch', buildingId: 'b1' }), false);
  click(rowEl('post:orphan-porch:1').querySelector('[data-row-lock]'));
  // Locking or hiding the parent porch locks or hides its posts.
  vis.lock('orphan-porch');
  assert.equal(rowEl('post:orphan-porch:0').querySelector('[data-row-lock]').getAttribute('aria-pressed'), 'true');
  assert.equal(vis.isPickable({ kind: 'porch_post', pieceId: 'post:orphan-porch:0', parentPieceId: 'orphan-porch', buildingId: 'b1' }), false);
  vis.unlock('orphan-porch');
  vis.hide('orphan-porch');
  assert.equal(rowEl('post:orphan-porch:0').style.opacity, '0.5');
  assert.equal(vis.isPickable({ kind: 'porch_post', pieceId: 'post:orphan-porch:0', parentPieceId: 'orphan-porch', buildingId: 'b1' }), false);
  vis.showAll();
  // Visibility prune with derived ids (same logic as editor.js existingPieceIds).
  vis.hide('post:orphan-porch:0');
  const existing = [];
  for (const b of orphanPlan.buildings) for (const post of porchPosts(b)) existing.push(post.id);
  vis.forHouse('house-a', existing);
  assert.equal(vis.isHidden('post:orphan-porch:0'), true, 'derived post id survives visibility prune');
  tree.dispose(); host.remove();
});

// ---------------------------------------------------------------------------
// Helper to build a rich test scene + full createSceneTools stack
// ---------------------------------------------------------------------------
function makeScenePlan() {
  return {
    schema: 'chauffeur.twin.plan/2', units: 'ft',
    buildings: [{
      id: 'b1', name: 'Pool House', position: [0, 0], rotation: 0, base: 0,
      levels: [{ id: 'L1', name: 'Main floor', elevation: 0, ceiling: 9 }],
      joints: [
        { id: 'j0', level: 'L1', at: [0, 0] }, { id: 'j1', level: 'L1', at: [10, 0] },
        { id: 'j2', level: 'L1', at: [10, 8] }, { id: 'j3', level: 'L1', at: [0, 8] },
      ],
      walls: [
        { id: 'w0', level: 'L1', joints: ['j3', 'j2'], from: [0, 8], to: [10, 8], thickness: 0.5, height: 9, exterior: true },
      ],
      rooms: [{
        id: 'porch1', name: 'Pool Porch', kind: 'porch', level: 'L1',
        joints: ['j0', 'j1', 'j2', 'j3'],
        polygon: [[0, 0], [10, 0], [10, 8], [0, 8]],
      }],
      openings: [], items: [], anchors: [], stairs: [], dormers: [],
      porches: [{
        id: 'porch1', name: 'Pool Porch', level: 'L1', floor: 0,
        polygon: [[0, 0], [10, 0], [10, 8], [0, 8]],
        columns: [
          { at: [0.25, 0.25], size: 0.5 },
          { at: [5, 0.25], size: 0.5 },
          { at: [9.75, 0.25], size: 0.5 },
        ],
      }],
      roofs: [{
        id: 'r1', name: 'Porch Roof', level: 'L1', kind: 'shed', plate: 9, pitch: 3,
        area: [[0, 0], [10, 0], [10, 8], [0, 8]],
        edges: [{ setting: 'sloped' }, { setting: 'gable' }, { setting: 'gable' }, { setting: 'gable' }],
      }],
      roof: { sections: [{ id: 'r1', roof: 'r1', kind: 'shed', level: 'L1', rect: [0, 0, 10, 8], plate: 9, pitch: 3 }] },
    }],
    site: {}, materials: {},
  };
}

function mountEditorHarness(initialPlan) {
  // Minimal DOM nodes expected by createSceneTools + createDock + createCards
  document.body.replaceChildren();
  const ids = [
    ['div', 'editor-scene'], ['aside', 'editor-dock'], ['div', 'properties-content'], ['div', 'properties-empty'],
    ['div', 'properties-heading'], ['div', 'properties-crumbs'], ['button', 'properties-back'],
    ['div', 'piece-card'], ['div', 'scene-tree'], ['div', 'layer-kinds'], ['div', 'scene-floor-actions'],
    ['div', 'editor-status'], ['div', 'editor-drag-hint'], ['svg', 'editor-drag-layer'],
    ['button', 'rail-select'], ['button', 'rail-move'], ['button', 'rail-rotate'], ['button', 'rail-scale'],
    ['button', 'rail-copy'], ['button', 'rail-paste'], ['button', 'rail-sheet'],
  ];
  for (const [tag, id] of ids) {
    const n = document.createElement(tag); n.id = id; document.body.append(n);
  }
  const outline = document.createElement('polygon'); outline.id = 'editor-drag-outline';
  document.getElementById('editor-drag-layer').append(outline);
  const propsScroll = document.getElementById('properties-content');
  propsScroll.scrollHeight = 1200; propsScroll.clientHeight = 400;
  propsScroll.append(document.getElementById('piece-card'));
  const origCss = globalThis.getComputedStyle;
  globalThis.getComputedStyle = node => node === propsScroll ? { overflowY: 'auto', overflow: '' } : origCss?.(node) || { overflowY: 'visible', overflow: '' };

  const canvas = document.createElement('canvas');
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, right: 1000, bottom: 1000, width: 1000, height: 1000 });
  canvas.setPointerCapture = () => {}; canvas.releasePointerCapture = () => {}; canvas.hasPointerCapture = () => false;
  document.getElementById('editor-scene').append(canvas);

  const camera = new THREE.OrthographicCamera(-20, 20, 20, -20, 0.01, 1000);
  camera.position.set(5 * 0.3048, 100, -4 * 0.3048 + 0.001);
  camera.lookAt(5 * 0.3048, 0, -4 * 0.3048);
  camera.updateMatrixWorld(true);
  const world = p => new THREE.Vector3(p[0] * 0.3048, (p[2] || 0) * 0.3048, -p[1] * 0.3048);
  const screenOf = p => { const v = world(p).project(camera); return [(v.x + 1) * 500, (1 - v.y) * 500]; };

  let plan = structuredClone(initialPlan);
  let pickQueue = [];
  let boundsBoxes = [];
  const ops = [], alerts = [];
  window.showGlobalAlert = msg => alerts.push(msg);
  window.promptConfirm = async () => true;

  const view = {
    camera, renderer3: { domElement: canvas }, controls: Object.assign(new THREE.EventDispatcher(), { enabled: true }),
    state: { view: 'ext' }, groups: { levels: { 'b1:L1': { visible: true } } },
    pickAll: () => pickQueue.map(item => ({ ...item })),
    pick: () => pickQueue[0] ? { ...pickQueue[0] } : null,
    setSelection: () => 0,
    setView: v => { view.state.view = v; },
    showLevels: () => {},
    setEditableLevel: async () => {},
    floorAt: () => [5, 4],
    screenOfFloor: (x, y) => screenOf([x, y, 0]),
    selectionBounds: () => boundsBoxes,
    selectionWorldBounds: () => [],
    rebuildLevel: () => {},
    previewSelectionBox: () => {},
    previewSelectionGroup: () => {},
  };

  const abort = new AbortController();
  const visibility = createVisibility({ storage: null });
  const dock = createDock({ host: document.getElementById('editor-dock') });
  let onOpHook = null;
  const opFn = async operation => {
    ops.push(structuredClone(operation));
    if (onOpHook) onOpHook(operation);
  };
  const tools = createSceneTools({
    view, getPlan: () => plan, getModel: () => plan, getKit: () => kit, getSheets: () => ({}),
    edit: opFn, op: opFn, applyBatch: async list => opFn({ op: 'batch', ops: list }),
    panel: { clearSelection() {}, focusSelection() {}, message() {} },
    canEdit: () => true, signal: abort.signal, visibility, dock,
    isPickable: c => visibility.isPickable(c),
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
    getPlan: () => plan, setPlan: p => { plan = p; },
    setPick: list => { pickQueue = list; },
    setBounds: list => { boundsBoxes = list; },
    setOnOp: fn => { onOpHook = fn; },
    ops, alerts, view, tools, dock, visibility, canvas, propsScroll, screenOf, pointer, clickCanvas,
    dispose: () => { abort.abort(); dock.dispose(); },
  };
}

// ---------------------------------------------------------------------------
// 2. Selection from tree & injected pick record (Outside, whole-porch proxy,
//    second click to porch) + focused porch room + breadcrumb
// ---------------------------------------------------------------------------
await test('selection_pick_traps_focused_room_and_breadcrumb', async () => {
  const h = mountEditorHarness(makeScenePlan());
  const post1Ref = 'post:porch1:1';
  // Inject whole-porch proxy CLOSER than the post AND view === 'ext' with nothing selected!
  h.setPick([
    { kind: 'room', id: 'porch1', building: 'b1', distance: 4.5 },
    { kind: 'porch_post', pieceId: post1Ref, parentPieceId: 'porch1', distance: 5.0 },
  ]);
  h.clickCanvas(500, 500);
  assert.equal(h.tools.selected()?.kind, 'porch_post', 'post wins over closer whole-porch proxy and skips Outside building promotion');
  assert.equal(h.tools.selected()?.pieceId, post1Ref);
  assert.equal(document.getElementById('properties-crumbs').textContent, 'Pool Porch > Post 2');
  const card = document.getElementById('piece-card');
  assert.equal(card.querySelector('h3').textContent, 'Post 2 \u00b7 Pool Porch');

  // Second click on the exact same spot selects the porch below it.
  h.clickCanvas(500, 500);
  assert.equal(h.tools.selected()?.kind, 'room');
  assert.equal(h.tools.selected()?.pieceId, 'porch1');

  // Porch room is now focused! Clicking the post keeps room focus.
  assert.equal(h.tools.selection().room, 'porch1');
  h.setPick([
    { kind: 'porch_post', pieceId: post1Ref, parentPieceId: 'porch1', building: 'b1', distance: 4.5 },
    { kind: 'room', id: 'porch1', building: 'b1', distance: 5.0 },
  ]);
  h.clickCanvas(520, 520);
  assert.equal(h.tools.selected()?.pieceId, post1Ref);
  assert.equal(h.tools.selection().room, 'porch1', 'post stays inside focused porch roomContext.allowed');

  // Escape backs out to porch room, second Escape clears.
  const esc = () => fire(document.body, 'keydown', { key: 'Escape' });
  esc();
  assert.equal(h.tools.selected()?.pieceId, 'porch1');
  esc();
  assert.equal(h.tools.selected(), null);

  // Selection from Scene tree row.
  const treeHost = document.getElementById('scene-tree');
  const porchRow = treeHost.querySelector('[data-scene-id="porch1"]');
  if (porchRow.getAttribute('aria-expanded') !== 'true') click(porchRow.querySelector('[data-row-disclosure]'));
  const post2Row = treeHost.querySelector(`[data-scene-id="${post1Ref}"]`);
  assert.ok(post2Row, 'Post 2 row visible under expanded porch');
  click(post2Row.querySelector('[data-scene-select]'));
  assert.equal(h.tools.selected()?.pieceId, post1Ref);

  // Connected-model roomContext (porches_detail instead of porches) also allows posts.
  const modelWithDetail = {
    buildings: [{
      id: 'b1', levels: [{ id: 'L1', elevation: 0 }], walls: [],
      rooms: [{ id: 'porch1', kind: 'porch', level: 'L1', joints: [] }],
      porches_detail: [{ id: 'porch1', columns: [{ at: [1, 1], size: 0.5 }, { id: 'post:minted1', at: [5, 1], size: 0.5 }] }],
    }],
  };
  const rs = createRoomSelection({ view: { setSelection: () => 0 }, getModel: () => modelWithDetail });
  rs.focusRoom('porch1', 'b1');
  rs.select({ kind: 'porch_post', id: 'post:porch1:0', building: 'b1' });
  assert.equal(rs.current().id, 'post:porch1:0');
  assert.equal(rs.current().room, 'porch1');
  rs.select({ kind: 'porch_post', id: 'post:minted1', building: 'b1' });
  assert.equal(rs.current().id, 'post:minted1');
  assert.equal(rs.current().room, 'porch1');
  h.dispose();
});

// ---------------------------------------------------------------------------
// 3. Card fields, typed values refused/accepted, in-place keepPlace,
//    Columns material + note, Select the porch, Porch card Posts section,
//    Add post, Size for all (one batch), disabled Move posts with reason
// ---------------------------------------------------------------------------
await test('cards_fields_validation_keep_place_add_size_all_and_move_posts_reason', async () => {
  const h = mountEditorHarness(makeScenePlan());
  const card = document.getElementById('piece-card');
  const post1Ref = 'post:porch1:1';
  h.tools.select({ pieceId: post1Ref, buildingId: 'b1' });

  // Verify post card fields & wording.
  assert.equal(card.querySelector('h3').textContent, 'Post 2 \u00b7 Pool Porch');
  const xInput = card.querySelector('input[aria-label="Position X (ft)"]');
  const yInput = card.querySelector('input[aria-label="Position Y (ft)"]');
  const sizeInput = card.querySelector('input[aria-label="Size (ft)"]');
  assert.equal(xInput.value, '5');
  assert.equal(yInput.value, '0.25');
  assert.equal(sizeInput.value, '0.5');
  assert.ok(card.querySelector('[data-library-slot="Columns"]'), 'Columns material slot present');
  assert.match(card.querySelector('[data-post-material-note]').textContent, /all posts of this porch/i);
  assert.ok(card.querySelector('[data-select-porch]').textContent === 'Select the porch');

  // Typed values refused: invalid X, invalid Y, out-of-range / blank Size -> 0 ops, aria-invalid="true"
  const beforeOps = h.ops.length;
  for (const [inp, bad] of [[xInput, 'not-a-num'], [xInput, ''], [yInput, 'abc'], [sizeInput, '0.01'], [sizeInput, '3.5'], [sizeInput, '0'], [sizeInput, '']]) {
    inp.value = bad;
    fire(inp, 'change');
    await flush();
    assert.equal(h.ops.length, beforeOps, `refused "${bad}" sends 0 ops`);
    assert.equal(inp.getAttribute('aria-invalid'), 'true', `refused "${bad}" marks aria-invalid`);
  }

  // Typed values accepted + scroll and focus kept across update AND across derived -> minted id!
  h.propsScroll.scrollTop = 180;
  xInput.focus();
  h.setOnOp(operation => {
    const next = structuredClone(h.getPlan());
    const cols = next.buildings[0].porches[0].columns;
    // Simulate server minting ids on first post op!
    cols.forEach((c, i) => { c.id = `post:mint${i}`; });
    if (operation.at) cols[1].at = operation.at;
    if (operation.size) cols[1].size = operation.size;
    h.setPlan(next);
    h.tools.refresh();
  });
  xInput.value = '6.25';
  fire(xInput, 'change');
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'update_porch_post', building: 'b1', porch: 'porch1', post: post1Ref, at: [6.25, 0.25] });
  assert.equal(h.tools.selected().pieceId, 'post:mint1', 'reselected minted id at same porch & index');
  assert.equal(h.propsScroll.scrollTop, 180, 'keepPlace preserves scroll across minting');
  assert.equal(document.activeElement.getAttribute('aria-label'), 'Position X (ft)', 'keepPlace preserves focused control across minting');

  // Accept feet-inches syntax on Y and valid size.
  const y2 = card.querySelector('input[aria-label="Position Y (ft)"]');
  y2.value = "1'-6\"";
  fire(y2, 'change');
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'update_porch_post', building: 'b1', porch: 'porch1', post: 'post:mint1', at: [6.25, 1.5] });

  const s2 = card.querySelector('input[aria-label="Size (ft)"]');
  s2.value = '0.75';
  fire(s2, 'change');
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'update_porch_post', building: 'b1', porch: 'porch1', post: 'post:mint1', size: 0.75 });

  // Select the porch button -> opens porch card with Posts section.
  click(card.querySelector('[data-select-porch]'));
  assert.equal(h.tools.selected().pieceId, 'porch1');
  const postsSection = card.querySelector('[data-porch-posts]');
  assert.ok(postsSection, 'Porch card has Posts section');
  assert.equal(postsSection.querySelector('[data-porch-posts-count]').textContent, '3 posts');

  // Porch now has mixed sizes (0.5, 0.75, 0.5) -> Move posts to the roof is shown DISABLED with postRoofReason!
  const moveRoofBtn = [...postsSection.querySelectorAll('button')].find(b => b.textContent === 'Move posts to the roof');
  assert.ok(moveRoofBtn, 'Move posts to the roof shown even when ineligible');
  assert.equal(moveRoofBtn.disabled, true);
  const reasonEl = postsSection.querySelector('[data-post-roof-reason]');
  assert.ok(reasonEl && reasonEl.textContent.includes('same size'), `shows postRoofReason: ${reasonEl?.textContent}`);

  // Size for all posts shows Mixed placeholder; invalid value refused; valid value sends ONE batch!
  const sizeAll = postsSection.querySelector('input[aria-label="Size for all posts"]');
  assert.equal(sizeAll.placeholder, 'Mixed');
  assert.equal(sizeAll.value, '');
  const opsBeforeBad = h.ops.length;
  sizeAll.value = '99';
  fire(sizeAll, 'change');
  await flush();
  assert.equal(h.ops.length, opsBeforeBad);
  assert.equal(sizeAll.getAttribute('aria-invalid'), 'true');

  h.setOnOp(operation => {
    const next = structuredClone(h.getPlan());
    const cols = next.buildings[0].porches[0].columns;
    for (const sub of operation.ops || []) {
      const col = cols.find(c => c.id === sub.post);
      if (col && sub.size) col.size = sub.size;
    }
    h.setPlan(next);
    h.tools.refresh();
  });
  h.propsScroll.scrollTop = 140;
  sizeAll.focus();
  sizeAll.value = '0.6';
  fire(sizeAll, 'change');
  await flush();
  const batchOp = h.ops.at(-1);
  assert.equal(batchOp.op, 'batch', 'Size for all sends one batch');
  assert.equal(batchOp.ops.length, 3);
  assert.ok(batchOp.ops.every(o => o.op === 'update_porch_post' && o.size === 0.6));
  assert.equal(h.propsScroll.scrollTop, 140, 'porch card keepPlace preserves scroll on column layout change');
  assert.equal(document.activeElement.getAttribute('aria-label'), 'Size for all posts', 'porch card keeps focus');
  // Now all sizes are uniform 0.6 and under shed roof -> Move posts to the roof becomes ENABLED!
  const enabledMoveBtn = [...card.querySelectorAll('button')].find(b => b.textContent === 'Move posts to the roof');
  assert.ok(enabledMoveBtn && !enabledMoveBtn.disabled, 'Move posts enables when columns become uniform under shed roof');

  // Add post sends add_porch_post and selects the new post!
  h.setOnOp(operation => {
    if (operation.op === 'add_porch_post') {
      const next = structuredClone(h.getPlan());
      next.buildings[0].porches[0].columns.push({ id: 'post:mint3', at: [5, 4], size: 0.6 });
      h.setPlan(next);
    }
  });
  const addBtn = [...card.querySelectorAll('button')].find(b => b.textContent === 'Add post');
  click(addBtn);
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'add_porch_post', building: 'b1', porch: 'porch1' });
  assert.equal(h.tools.selected().pieceId, 'post:mint3', 'Add post selects the newly added post');
  assert.equal(card.querySelector('h3').textContent, 'Post 4 \u00b7 Pool Porch');

  // Also check postRoofDisabledReason on household fixture porch 1 (mixed sizes) and porch with no roof.
  const noRoofPlan = makeScenePlan(); noRoofPlan.buildings[0].roofs = []; noRoofPlan.buildings[0].roof.sections = [];
  assert.match(postRoofDisabledReason(noRoofPlan.buildings[0], noRoofPlan.buildings[0].porches[0]), /No roof overlaps/);
  h.dispose();
});

// ---------------------------------------------------------------------------
// 4. Drag handle with every snap mode (corner, edge, other post line, grid, Shift)
//    + one operation per gesture + snap lines computed once + Gizmo Move only
// ---------------------------------------------------------------------------
await test('handles_drag_snapping_shift_one_op_and_gizmo_plan_only', async () => {
  const plan = makeScenePlan();
  // Columns: [0.25, 0.25], [5, 0.25], [9.75, 0.25], add [3.2, 4.1] as post 3 (size 0.5 -> inset = 0.25)
  plan.buildings[0].porches[0].columns.push({ at: [3.2, 4.1], size: 0.5 });
  const porch = plan.buildings[0].porches[0];

  // Unit check of snapPostPoint for all snap modes
  const targets = buildPostSnapTargets(porch, 3, 0.5);
  // Inset corner (0.25, 7.75)
  let snapped = snapPostPoint([0.4, 7.6], targets, false);
  assert.equal(snapped.target, 'corner'); near(snapped.point[0], 0.25); near(snapped.point[1], 7.75);
  // Inset edge (y = 7.75)
  snapped = snapPostPoint([6.1, 7.55], targets, false);
  assert.equal(snapped.target, 'edge'); near(snapped.point[0], 6.0); near(snapped.point[1], 7.75);
  // Edge intersected with another post's X line (post 1 at x = 5)
  snapped = snapPostPoint([5.15, 7.55], targets, false);
  assert.equal(snapped.target, 'edge_post'); near(snapped.point[0], 5.0); near(snapped.point[1], 7.75);
  // Other post's X line in interior (post 1 at x = 5)
  snapped = snapPostPoint([5.18, 4.1], targets, false);
  assert.equal(snapped.target, 'post_line'); near(snapped.point[0], 5.0); near(snapped.point[1], 4.0);
  // Grid snap (0.5 ft) away from edges and other post lines
  snapped = snapPostPoint([2.3, 4.2], targets, false);
  assert.equal(snapped.target, 'grid'); near(snapped.point[0], 2.5); near(snapped.point[1], 4.0);
  // Shift frees completely
  snapped = snapPostPoint([0.41, 7.62], targets, true);
  assert.equal(snapped.target, 'free'); near(snapped.point[0], 0.41); near(snapped.point[1], 7.62);

  // Real createHandles drag test with Three.js camera
  const host = document.createElement('div'), canvas = document.createElement('canvas');
  document.body.append(host); host.append(canvas);
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, right: 1000, bottom: 1000, width: 1000, height: 1000 });
  const camera = new THREE.OrthographicCamera(-20, 20, 20, -20, 0.01, 1000);
  camera.position.set(5 * 0.3048, 100, -4 * 0.3048 + 0.001);
  camera.lookAt(5 * 0.3048, 0, -4 * 0.3048);
  camera.updateMatrixWorld(true);
  const world = p => new THREE.Vector3(p[0] * 0.3048, (p[2] || 0) * 0.3048, -p[1] * 0.3048);
  const evAt = (p, extra = {}) => { const v = world(p).project(camera); return { clientX: (v.x + 1) * 500, clientY: (1 - v.y) * 500, button: 0, shiftKey: false, ...extra }; };
  const view = { camera, renderer3: { domElement: canvas }, controls: new THREE.EventDispatcher(), groups: { levels: { 'b1:L1': { visible: true } } }, rebuildLevel: () => {} };
  const selected = { kind: 'porch_post', id: 'post:porch1:3', building: 'b1', level: 'L1', porchId: 'porch1' };
  const committed = [], previews = [];
  const abort = new AbortController();
  const handles = createHandles({
    view, getPlan: () => plan, getSelection: () => selected, getTool: () => 'select', canEdit: () => true,
    drag: { clearDragFrame() {} }, onCommit: async op => committed.push(op), onPreview: p => previews.push(p), signal: abort.signal,
  });

  const hs = handles.handles();
  assert.equal(hs.length, 1);
  assert.equal(hs[0].kind, 'porch_post');

  // Multi-update drag -> snaps to inset corner (0.25, 7.75), emits EXACTLY ONE op on release!
  assert.ok(handles.begin(evAt(hs[0].at)));
  handles.update(evAt([2.3, 4.2, 0]));
  handles.update(evAt([5.15, 7.55, 0]));
  handles.update(evAt([0.4, 7.6, 0]));
  assert.equal(committed.length, 0, 'no commit before release');
  assert.ok(previews.length >= 3, 'live preview updates during drag');
  await handles.finish(false);
  assert.equal(committed.length, 1, 'exactly one op per drag gesture');
  assert.equal(committed[0].op, 'update_porch_post');
  assert.equal(committed[0].post, 'post:porch1:3');
  near(committed[0].at[0], 0.25); near(committed[0].at[1], 7.75);

  // Shift drag frees from snap!
  assert.ok(handles.begin(evAt(hs[0].at)));
  handles.update(evAt([0.41, 7.62, 0], { shiftKey: true }), { free: true });
  await handles.finish(false);
  assert.equal(committed.length, 2);
  near(committed[1].at[0], 0.41); near(committed[1].at[1], 7.62);

  // Cancel sends 0 ops
  assert.ok(handles.begin(evAt(hs[0].at)));
  handles.update(evAt([6, 6, 0]));
  await handles.finish(true);
  assert.equal(committed.length, 2, 'cancelled drag sends 0 ops');

  // Gizmo: Move in plan only (no rotate, no scale)
  let tool = 'move';
  const gOps = [], gLayer = document.createElement('div'); host.append(gLayer);
  const gizmo = createGizmo({ view, layer: gLayer, getPlan: () => plan, getSelection: () => selected, getTool: () => tool, op: async op => gOps.push(op) });
  gizmo.draw();
  assert.deepEqual(gizmo.handles().map(h => h.kind), ['gizmo_move_x', 'gizmo_move_y', 'gizmo_move_free']);
  const mx = gizmo.handles().find(h => h.kind === 'gizmo_move_x');
  assert.ok(gizmo.begin(evAt(mx.at), mx));
  gizmo.update(evAt([mx.at[0] + 2.2, mx.at[1] + 5, mx.at[2]]));
  await gizmo.finish(false);
  assert.equal(gOps.length, 1);
  assert.equal(gOps[0].op, 'update_porch_post');
  near(gOps[0].at[0], 3.2 + 2.0); near(gOps[0].at[1], 4.1);
  tool = 'rotate'; gizmo.draw(); assert.equal(gizmo.handles().length, 0, 'no Rotate gizmo for porch_post');
  tool = 'scale'; gizmo.draw(); assert.equal(gizmo.handles().length, 0, 'no Scale gizmo for porch_post');
  abort.abort(); host.remove();
});

// ---------------------------------------------------------------------------
// 5. Arrow keys, Delete by key/menu/card, Reselect after delete -> porch,
//    Sets: Shift select, marquee, group move & delete in one batch
// ---------------------------------------------------------------------------
await test('arrows_delete_paths_reselect_and_sets', async () => {
  const h = mountEditorHarness(makeScenePlan());
  const post0 = 'post:porch1:0', post1 = 'post:porch1:1', post2 = 'post:porch1:2';
  h.tools.select({ pieceId: post1, buildingId: 'b1' });

  // Arrow key nudge (ArrowRight -> +1 X, ArrowUp -> +1 Y)
  const key = (k, extra = {}) => fire(document.body, 'keydown', { key: k, ...extra });
  key('ArrowRight');
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'update_porch_post', building: 'b1', porch: 'porch1', post: post1, at: [6, 0.25] });
  key('ArrowUp');
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'update_porch_post', building: 'b1', porch: 'porch1', post: post1, at: [5, 1.25] });

  // Delete by Delete key -> sends delete_porch_post and selects the porch!
  key('Delete');
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'delete_porch_post', building: 'b1', porch: 'porch1', post: post1 });
  assert.equal(h.tools.selected()?.pieceId, 'porch1', 'Delete key selects porch afterwards');

  // Delete by right-click context menu!
  h.tools.select({ pieceId: post0, buildingId: 'b1' });
  h.tools.openContextMenu({ clientX: 200, clientY: 200 }, { kind: 'porch_post', id: post0, building: 'b1' });
  const menu = document.getElementById('editor-context-menu');
  assert.ok(menu && !menu.hidden);
  const delMenuBtn = [...menu.querySelectorAll('button')].find(b => b.textContent === 'Delete');
  assert.ok(delMenuBtn, 'right-click menu has Delete for porch_post');
  click(delMenuBtn);
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'delete_porch_post', building: 'b1', porch: 'porch1', post: post0 });
  assert.equal(h.tools.selected()?.pieceId, 'porch1', 'right-click Delete selects porch afterwards');

  // Delete by card Delete button!
  h.tools.select({ pieceId: post2, buildingId: 'b1' });
  const cardDelBtn = [...document.getElementById('piece-card').querySelectorAll('button')].find(b => b.textContent === 'Delete');
  assert.ok(cardDelBtn);
  click(cardDelBtn);
  await flush();
  assert.deepEqual(h.ops.at(-1), { op: 'delete_porch_post', building: 'b1', porch: 'porch1', post: post2 });
  assert.equal(h.tools.selected()?.pieceId, 'porch1', 'card Delete selects porch afterwards');

  // Reselect after delete via refresh() when a post disappears from plan (e.g. external/server update)
  const mintedPlan = makeScenePlan();
  mintedPlan.buildings[0].porches[0].columns.forEach((c, i) => { c.id = `post:m${i}`; });
  h.setPlan(mintedPlan);
  h.tools.select({ pieceId: 'post:m1', buildingId: 'b1' });
  const afterDel = structuredClone(mintedPlan);
  afterDel.buildings[0].porches[0].columns.splice(1, 1);
  h.setPlan(afterDel);
  h.tools.refresh();
  assert.equal(h.tools.selected()?.pieceId, 'porch1', 'refresh selects porch when selected post is deleted');

  // Multi-select via Shift-click on 3D canvas + marquee!
  h.setPlan(makeScenePlan());
  h.tools.select({ pieceId: post0, buildingId: 'b1' });
  assert.deepEqual(h.tools.selectedMembers().map(m => m.pieceId), [post0], 'post0 selected before Shift-click');
  h.setPick([{ kind: 'porch_post', pieceId: post2, parentPieceId: 'porch1', building: 'b1', distance: 5 }]);
  h.clickCanvas(600, 600, { shiftKey: true });
  assert.deepEqual(h.tools.selectedMembers().map(m => m.pieceId), [post0, post2], `Shift-click adds post to selection set (got ${JSON.stringify(h.tools.selectedMembers())}, room=${h.tools.selection().room})`);
  assert.match(document.getElementById('piece-card').querySelector('[data-selection-summary]').textContent, /2 posts/);

  // Marquee selection of posts via selectionBoxes + createMarquee!
  const fakeProxy = { visible: true, parent: null, userData: { levelKey: 'b1:L1' } };
  const fakeTwin = {
    root: { updateMatrixWorld() {} },
    pieceBounds: new Map([
      ['b1:post:porch1:0', { data: { kind: 'porch_post', pieceId: post0, buildingId: 'b1', parentPieceId: 'porch1' }, box: new THREE.Box3(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0.5, 2, 0)), group: { matrixWorld: new THREE.Matrix4() } }],
      ['b1:post:porch1:1', { data: { kind: 'porch_post', pieceId: post1, buildingId: 'b1', parentPieceId: 'porch1' }, box: new THREE.Box3(new THREE.Vector3(1.4, 0, -1), new THREE.Vector3(1.7, 2, 0)), group: { matrixWorld: new THREE.Matrix4() } }],
    ]),
    pickObjects: new Map([['b1:post:porch1:0', fakeProxy], ['b1:post:porch1:1', fakeProxy]]),
  };
  const boxes = selectionBoxes({ twin: fakeTwin, plan: h.getPlan() });
  assert.equal(boxes.filter(b => b.kind === 'porch_post').length, 2, 'selectionBoxes includes porch_post proxies');
  assert.equal(boxes[0].porchId, 'porch1');
  h.setBounds([
    { kind: 'porch_post', pieceId: post0, buildingId: 'b1', porchId: 'porch1', bounds: { left: 100, right: 120, top: 100, bottom: 120 } },
    { kind: 'porch_post', pieceId: post1, buildingId: 'b1', porchId: 'porch1', bounds: { left: 200, right: 220, top: 100, bottom: 120 } },
  ]);
  const mq = createMarquee({ view: h.view, selection: h.tools.selectionStore, visibility: h.visibility, getPlan: h.getPlan });
  mq.pointerDown({ clientX: 50, clientY: 50, button: 0, pointerId: 2 });
  mq.pointerMove({ clientX: 250, clientY: 250, pointerId: 2 });
  mq.pointerUp({ clientX: 250, clientY: 250, pointerId: 2 });
  assert.deepEqual(h.tools.selectedMembers().map(m => m.pieceId), [post0, post1], 'marquee selects both posts');

  // Group move (arrow key & groupTransform) sends ONE batch of update_porch_post!
  const gMove = groupTransform(h.getPlan(), h.tools.selectedMembers(), 'move');
  assert.ok(gMove && gMove.records.length === 2);
  assert.equal(groupTransform(h.getPlan(), h.tools.selectedMembers(), 'rotate'), null, 'posts cannot rotate in group');
  assert.equal(groupTransform(h.getPlan(), h.tools.selectedMembers(), 'scale'), null, 'posts cannot scale in group');
  const moveOps = transformOperations(gMove, { by: [2, -1] });
  assert.equal(moveOps.length, 2);
  assert.deepEqual(moveOps, [
    { op: 'update_porch_post', building: 'b1', porch: 'porch1', post: post0, at: [2.25, -0.75] },
    { op: 'update_porch_post', building: 'b1', porch: 'porch1', post: post1, at: [7, -0.75] },
  ]);
  key('ArrowRight');
  await flush();
  assert.equal(h.ops.at(-1).op, 'batch');
  assert.equal(h.ops.at(-1).ops.length, 2);
  assert.ok(h.ops.at(-1).ops.every(o => o.op === 'update_porch_post'));

  // Group delete sends ONE batch (ordered safely descending derived index and before porch delete) and selects porch!
  const delBatchWithPorch = deleteOperations(h.getPlan(), [
    { kind: 'room', pieceId: 'porch1', buildingId: 'b1' },
    { kind: 'porch_post', pieceId: post0, buildingId: 'b1', porchId: 'porch1' },
    { kind: 'porch_post', pieceId: post1, buildingId: 'b1', porchId: 'porch1' },
  ]);
  assert.deepEqual(delBatchWithPorch.map(o => [o.op, o.post || o.id]), [
    ['delete_porch_post', post1],
    ['delete_porch_post', post0],
    ['delete', 'porch1'],
  ]);
  key('Delete');
  await flush();
  assert.equal(h.ops.at(-1).op, 'batch');
  assert.deepEqual(h.ops.at(-1).ops.map(o => o.post), [post1, post0]);
  assert.equal(h.tools.selected()?.pieceId, 'porch1', 'group post delete on one porch selects the porch');

  h.dispose();
});

finish();
"""


def main():
    with tempfile.TemporaryDirectory(prefix='chauffeur_porch_posts_ed_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_store, twin_library
        fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
        twin_store.push_round(fixture, 'build')
        code, out = run_node(DRIVER, {
            'root': ROOT.as_posix(),
            'household': twin_store.current(),
            'model': twin_store.current_model(),
            'kit': {**twin_library.kit('modern_farmhouse'), 'manifest': {}},
        })
    print(out)
    sys.exit(code)


if __name__ == '__main__':
    main()
