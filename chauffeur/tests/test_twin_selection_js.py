"""Task 1: selection store, Ctrl-click, marquee, Scene tree multi-select (no browser).

Runs the production ES modules under Node against the real normalized household
fixture with real yard geometry (walls, openings, roofs, plants, grass, pads, fixtures).
Run from chauffeur/: python tests/test_twin_selection_js.py
"""
import json
from pathlib import Path
import sys
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = PREFIX + r"""
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

const { mountTwin } = await import(file('static/twin/twin_view.js'));
const { createSelection } = await import(file('static/twin/editor/selection.js'));
const { createMarquee, MARQUEE_THRESHOLD_PX } = await import(file('static/twin/editor/marquee.js'));
const { selectionBoxes, selectionBoxFor } = await import(file('static/twin/editor/selection_bounds.js'));
const { createSceneTools } = await import(file('static/twin/editor/scene_tools.js'));
const { createLibrary } = await import(file('static/twin/editor/library.js'));
const { createTerrainTools } = await import(file('static/twin/editor/terrain_tools.js'));
const { createDevicePlacement } = await import(file('static/twin/editor/device_placement.js'));
const { createVisibility } = await import(file('static/twin/editor/visibility.js'));
const { createDock } = await import(file('static/twin/editor/dock.js'));

const FT = 0.3048;

// Model browser capture-then-bubble and stopImmediatePropagation on document keydown
// so Escape priority (marquee before selection) is exercised faithfully.
const rawDocAdd = document.addEventListener.bind(document);
const rawDocDispatch = document.dispatchEvent.bind(document);
let docKeyListeners = [];
document.addEventListener = (type, fn, options = {}) => {
  if (type !== 'keydown') return rawDocAdd(type, fn, options);
  const capture = options === true || !!options?.capture;
  const signal = typeof options === 'object' ? options?.signal : null;
  if (signal?.aborted || !fn) return;
  const entry = { fn, capture, signal };
  docKeyListeners.push(entry);
  signal?.addEventListener('abort', () => { docKeyListeners = docKeyListeners.filter(e => e !== entry); }, { once: true });
};
document.dispatchEvent = event => {
  if (event.type !== 'keydown') return rawDocDispatch(event);
  if (!event.target) event.target = document.body;
  let stopped = false;
  event.stopImmediatePropagation = () => { stopped = true; event._stopped = true; };
  for (const capture of [true, false]) {
    for (const entry of [...docKeyListeners]) {
      if (stopped) return !event.defaultPrevented;
      if (entry.capture === capture && !entry.signal?.aborted) entry.fn(event);
    }
  }
  return !event.defaultPrevented;
};

// Return valid manifest payload for material_watch.js and library payload for catalog reads.
window.fetch = globalThis.fetch = async url => {
  const href = String(url || '');
  const payload = href.includes('materials/manifest')
    ? { revision: 0, entries: {} }
    : { materials: [], items: [], imports: [], limit_mb: 50, unpacked_limit_mb: 200 };
  return {
    ok: true, status: 200,
    text: async () => JSON.stringify(payload),
    json: async () => payload,
  };
};
window.twinObjectSchema = input.objectSchema;

// ---------------------------------------------------------------------------
// 1. Pure selection store unit test (Ruling 1 + strict no-op guard)
// ---------------------------------------------------------------------------
await test('selection_store_pure_unit_and_noop_guard', () => {
  const seen = [], subSeen = [];
  const sel = createSelection({ onChange: members => seen.push(members) });
  const off = sel.subscribe(members => subSeen.push(members));

  assert.deepEqual(sel.members(), []);
  assert.equal(sel.primary(), null);
  assert.equal(sel.has({ kind: 'wall', pieceId: 'w1', buildingId: 'b1' }), false);

  // No-op guard on empty store: clear/remove/narrow/toggle(null)/set([]) do not notify.
  sel.clear();
  sel.set([]);
  sel.remove({ kind: 'wall', pieceId: 'missing', buildingId: 'b1' });
  sel.narrow('wall');
  assert.equal(sel.toggle(null), false);
  assert.equal(seen.length, 0, 'no notification on empty no-op calls');
  assert.equal(subSeen.length, 0);

  const w1 = { kind: 'wall', pieceId: 'w1', buildingId: 'b1', slots: ['left'] };
  const w2 = { kind: 'wall', pieceId: 'w2', buildingId: 'b1' };
  const t1 = { kind: 'planting', pieceId: 'tree:1' };

  sel.add(w1);
  assert.equal(seen.length, 1);
  assert.ok(Array.isArray(seen[0]), 'onChange payload is members array (Ruling 1)');
  assert.equal('room' in seen[0], false, 'payload has no room-focus fields');
  assert.deepEqual(sel.primary(), w1);
  assert.equal(sel.has(w1), true);
  assert.equal(sel.has({ pieceId: 'w1', buildingId: 'b1' }), true);

  // Returned refs and slots are defensive clones.
  const copy = sel.primary();
  copy.slots.push('right');
  assert.deepEqual(sel.primary().slots, ['left']);
  const memCopy = sel.members();
  memCopy.pop();
  assert.equal(sel.members().length, 1);

  // Adding an identical existing member is a no-op (no notification).
  sel.add({ ...w1 });
  assert.equal(seen.length, 1, 'duplicate add does not notify');

  sel.add(w2);
  assert.equal(seen.length, 2);
  // Adding an earlier member without new slots keeps order/primary and does not notify.
  sel.add({ kind: 'wall', pieceId: 'w1', buildingId: 'b1' });
  assert.deepEqual(sel.members().map(r => r.pieceId), ['w1', 'w2']);
  assert.equal(sel.primary().pieceId, 'w2', 'primary() stays last added');
  assert.equal(seen.length, 2, 're-adding existing member does not notify');

  // set() with identical ordered members is a no-op.
  sel.set([w1, w2]);
  assert.equal(seen.length, 2, 'set() with identical order & primary does not notify');

  // set() with different order changes primary and DOES notify.
  sel.set([w2, w1]);
  assert.equal(seen.length, 3, 'set() changing order/primary notifies');
  assert.equal(sel.primary().pieceId, 'w1');
  sel.set([w1, w2]);
  assert.equal(seen.length, 4);

  sel.add(t1);
  assert.deepEqual(sel.members().map(r => r.pieceId), ['w1', 'w2', 'tree:1']);
  assert.equal(sel.primary().pieceId, 'tree:1', 'primary() is last member added');

  // kinds() groups by kind preserving insertion order
  const byKind = sel.kinds();
  assert.ok(byKind instanceof Map);
  assert.deepEqual([...byKind.keys()], ['wall', 'planting']);
  assert.deepEqual(byKind.get('wall').map(r => r.pieceId), ['w1', 'w2']);
  assert.deepEqual(byKind.get('planting').map(r => r.pieceId), ['tree:1']);

  // toggle removes an existing member and updates primary()
  assert.equal(sel.toggle(t1), false);
  assert.equal(sel.has(t1), false);
  assert.equal(sel.primary().pieceId, 'w2');
  assert.equal(sel.toggle(t1), true);
  assert.equal(sel.primary().pieceId, 'tree:1');

  // narrow(kind) keeps only that kind; calling narrow again is a no-op
  sel.narrow('wall');
  const afterNarrow = seen.length;
  assert.deepEqual(sel.members().map(r => r.pieceId), ['w1', 'w2']);
  sel.narrow('wall');
  assert.equal(seen.length, afterNarrow, 'narrow() when already narrowed does not notify');

  // remove(missing) is a no-op; remove(w2) promotes w1
  sel.remove(t1);
  assert.equal(seen.length, afterNarrow, 'remove() of non-member does not notify');
  sel.remove(w2);
  assert.deepEqual(sel.members().map(r => r.pieceId), ['w1']);
  assert.equal(sel.primary().pieceId, 'w1');

  // set(refs) replaces and deduplicates; same pieceId in different buildings are distinct
  sel.set([t1, w2, t1]);
  assert.deepEqual(sel.members().map(r => r.pieceId), ['tree:1', 'w2']);
  assert.equal(sel.primary().pieceId, 'w2');
  sel.set([w1, { ...w1, buildingId: 'b2' }]);
  assert.equal(sel.members().length, 2);

  // subscribe / unsubscribe and onChange stay in sync; clear() once notifies, second clear() is no-op
  assert.equal(seen.length, subSeen.length);
  const beforeOff = subSeen.length;
  off();
  sel.clear();
  assert.deepEqual(sel.members(), []);
  assert.equal(sel.primary(), null);
  assert.equal(subSeen.length, beforeOff, 'unsubscribed listener stops receiving updates');
  assert.equal(seen.length, beforeOff + 1, 'onChange receives clear');
  sel.clear();
  assert.equal(seen.length, beforeOff + 1, 'second clear() on empty store does not notify');
});

// ---------------------------------------------------------------------------
// Helper: mount real editor scene + real yard + tools + dock + Scene tree
// ---------------------------------------------------------------------------
function makeHousehold() {
  const flat = structuredClone(input.flat);
  flat.site = flat.site || {};
  flat.site.terraces = flat.site.terraces?.length ? flat.site.terraces : [
    { id: 'pad:yard-1', height: 1, blend: 4, polygon: [[160, 160], [180, 160], [180, 180], [160, 180]] },
  ];
  flat.site.planting = [
    ...(flat.site.planting || []),
    { id: 'plant:canopy', kind: 'tree', preset: 'oak', height: 18, scale_axes: [2.2, 1, 2.2], at: [195, 195], seed: 7 },
    { id: 'plant:ghost-yard', kind: 'tree', preset: 'oak', height: 10, at: [200, 190], seed: 3, state: 'ghost' },
  ];
  flat.light_fixtures = {
    ...(flat.light_fixtures || {}),
    'light.yard': [
      { id: 'fix:yard-1', shape: 'point', ref: 'ground', at: [205, 205, 4] },
      { id: 'fix:line-1', shape: 'line', ref: 'absolute', path: [[212, 205, 3], [220, 205, 3]] },
    ],
  };
  flat.effect_fixtures = [
    ...(flat.effect_fixtures || []),
    { id: 'eff:yard-1', type: 'fire', shape: 'point', ref: 'ground', at: [210, 205, 1], size_min: 0.2, size_max: 1 },
  ];
  // Add a ghost wall on pool-house L1 to verify ghosts never enter bounds/marquee.
  const ph = flat.buildings.find(b => b.id === 'pool-house');
  if (ph) {
    ph.walls.push({
      id: 'wall:ghost-test', level: 'L1', from: [0, 0], to: [8, 0],
      height: 8, thickness: 0.5, exterior: false, state: 'ghost',
    });
  }
  return flat;
}

function buildEditorDom() {
  document.body.replaceChildren();
  const shell = document.createElement('main');
  shell.className = 'editor-shell';
  document.body.append(shell);
  const sceneHost = document.createElement('div');
  sceneHost.id = 'editor-scene';
  shell.append(sceneHost);

  for (const id of ['select', 'move', 'rotate', 'scale', 'measure', 'sheet', 'library', 'ground']) {
    const b = document.createElement('button');
    b.id = `rail-${id}`;
    b.setAttribute('aria-pressed', id === 'select' ? 'true' : 'false');
    shell.append(b);
  }
  const status = document.createElement('output'); status.id = 'editor-status'; shell.append(status);
  const hint = document.createElement('output'); hint.id = 'editor-drag-hint'; hint.hidden = true; shell.append(hint);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.id = 'editor-drag-layer';
  const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon'); poly.id = 'editor-drag-outline';
  poly.setAttribute('points', '');
  svg.append(poly); shell.append(svg);

  // Device placement / fixture tool containers
  const devTools = document.createElement('section'); devTools.id = 'device-tools'; devTools.hidden = true;
  const devNote = document.createElement('p'); devNote.id = 'device-note';
  const devCancel = document.createElement('button'); devCancel.id = 'device-cancel';
  devTools.append(devNote, devCancel); shell.append(devTools);
  const devOpts = document.createElement('section'); devOpts.id = 'device-options'; devOpts.hidden = true;
  const devOptsNote = document.createElement('p'); devOptsNote.id = 'device-options-note';
  devOpts.append(devOptsNote); shell.append(devOpts);

  // Dock + Scene tree + Properties
  const dockHost = document.createElement('aside'); dockHost.id = 'editor-dock'; shell.append(dockHost);
  const tabs = document.createElement('div'); tabs.id = 'dock-tabs'; dockHost.append(tabs);
  for (const tab of ['scene', 'layers', 'library', 'argyle']) {
    const b = document.createElement('button'); b.id = `dock-tab-${tab}`; b.dataset.dockTab = tab; tabs.append(b);
    const pane = document.createElement('section'); pane.id = `dock-pane-${tab}`; pane.hidden = tab !== 'scene'; dockHost.append(pane);
  }
  const floors = document.createElement('aside'); floors.id = 'editor-floors';
  const sceneTreeHost = document.createElement('div'); sceneTreeHost.id = 'scene-tree'; sceneTreeHost.clientHeight = 400;
  const floorActions = document.createElement('div'); floorActions.id = 'scene-floor-actions';
  floors.append(sceneTreeHost, floorActions);
  document.getElementById('dock-pane-scene').append(floors);
  const sceneYard = document.createElement('div'); sceneYard.id = 'scene-yard'; document.getElementById('dock-pane-scene').append(sceneYard);
  const layerKinds = document.createElement('div'); layerKinds.id = 'layer-kinds'; document.getElementById('dock-pane-layers').append(layerKinds);
  const layerGrade = document.createElement('button'); layerGrade.id = 'layer-grade'; document.getElementById('dock-pane-layers').append(layerGrade);
  const libPanel = document.createElement('aside'); libPanel.id = 'library-panel'; document.getElementById('dock-pane-library').append(libPanel);
  const splitter = document.createElement('div'); splitter.id = 'dock-splitter'; dockHost.append(splitter);
  const props = document.createElement('section'); props.id = 'dock-properties'; dockHost.append(props);
  const heading = document.createElement('header'); heading.id = 'properties-heading';
  const back = document.createElement('button'); back.id = 'properties-back';
  const crumbs = document.createElement('h2'); crumbs.id = 'properties-crumbs';
  heading.append(back, crumbs);
  const empty = document.createElement('div'); empty.id = 'properties-empty';
  const propsContent = document.createElement('div'); propsContent.id = 'properties-content';
  const pieceCard = document.createElement('aside'); pieceCard.id = 'piece-card'; pieceCard.hidden = true;
  propsContent.append(pieceCard);
  props.append(heading, empty, propsContent);

  return { shell, sceneHost, sceneTreeHost, dockHost, pieceCard };
}

async function mountEditor(plan = makeHousehold(), tier = 'low') {
  location.search = '?test=1';
  const dom = buildEditorDom();
  const view = await mountTwin(dom.sceneHost, { plan, kit: input.kit, tier, bake: false, preserveCamera: true });
  while (!view.ready) await new Promise(r => setTimeout(r, 1));
  const abort = new AbortController();
  const ops = [];
  const visibility = createVisibility({ storage: null });
  view.isPiecePickable = visibility.isPickable;
  const dock = createDock({ host: dom.dockHost });
  let library = null, terrain = null, devices = null;
  const tools = createSceneTools({
    dock, view, visibility, isPickable: visibility.isPickable,
    getPlan: () => plan, getModel: () => plan, getKit: () => input.kit, getSheets: () => ({}),
    op: async (operation, options) => { ops.push({ operation, options }); },
    edit: async change => { ops.push({ operation: change }); },
    panel: { clearSelection() {}, focusSelection() {}, message() {} },
    canEdit: () => true, signal: abort.signal,
    siteHits: (x, y) => library?.siteHits(x, y) || [],
    padHits: (x, y) => terrain?.padHits?.(x, y) || [],
    fixtureHits: (x, y) => devices?.fixtureHits?.(x, y) || [],
  });
  library = createLibrary({ dock, view, kit: input.kit, getPlan: () => plan, tools, op: async o => ops.push(o), canEdit: () => true, signal: abort.signal });
  devices = createDevicePlacement({ dock, view, tools, library, getPlan: () => plan, op: async o => ops.push(o), canEdit: () => true, signal: abort.signal, prepare() { terrain?.cancel(); } });
  terrain = createTerrainTools({ dock, view, tools, library, getPlan: () => plan, getKit: () => input.kit, op: async o => ops.push(o), canEdit: () => true, signal: abort.signal, prepare() { devices?.cancel(); } });
  devices.refresh();
  terrain.refresh();
  tools.delegate({
    visibilityChanged: () => library.refresh(),
    visibilitySelection: () => terrain.visibilitySelection?.() || devices.fixtureHandles.visibilitySelection?.(),
    preview: p => library.preview(p),
    handleSources: [tools.gizmo, terrain, devices.fixtureHandles],
    selectPick: hit => hit?.kind === 'terraces' && (terrain.choose('terraces', hit.id), true) || devices.selectFixturePick(hit),
    selectTree: devices.selectScene,
    selectionChanged: state => { terrain.selectionChanged(state); library.refresh(); },
    pointerDown: event => devices.pointerDown(event) || library.pointerDown(event),
    pointerMove: event => terrain.pointerMove(event) || devices.pointerMove(event) || library.pointerMove(event),
    pointerUp: (event, cancel) => terrain.pointerUp(event, cancel) || devices.pointerUp(event, cancel) || library.pointerUp(event, cancel),
    cancel() { terrain.cancel(); devices.cancel(); },
  });
  const offVis = visibility.subscribe(({ hidden, hiddenKinds }) => {
    view.setHiddenPieces(hidden, hiddenKinds);
    tools.visibilityChanged();
    library.refresh();
    terrain.refresh();
    devices.refresh();
  });
  abort.signal.addEventListener('abort', () => { offVis(); dock.dispose(); }, { once: true });

  const canvas = view.renderer3.domElement;
  const world = (p, b = null) => {
    const angle = (b?.rotation || 0) * Math.PI / 180, pos = b?.position || [0, 0];
    return new THREE.Vector3(
      (Math.cos(angle) * p[0] - Math.sin(angle) * p[1] + pos[0]) * FT,
      ((p[2] || 0) + (b?.base || 0)) * FT,
      -(Math.sin(angle) * p[0] + Math.cos(angle) * p[1] + pos[1]) * FT,
    );
  };
  const look = (targetPt, b = null, height = 160) => {
    view.setCameraState({ position: world([targetPt[0], targetPt[1] - 0.01, height], b).toArray(), target: world(targetPt, b).toArray() });
  };
  const projectWorld = v => {
    view.camera.updateMatrixWorld(true);
    const p = v.clone().project(view.camera);
    const r = canvas.getBoundingClientRect();
    return [r.left + (p.x + 1) * r.width / 2, r.top + (1 - p.y) * r.height / 2];
  };
  const pixel = (pt, b = null) => projectWorld(world(pt, b));
  const pointer = (type, pt, extra = {}) => fire(canvas, type, { pointerId: 1, button: 0, buttons: type === 'pointerdown' ? 1 : 0, clientX: pt[0], clientY: pt[1], ...extra });
  const clickAt = async (pt, extra = {}) => { await pointer('pointerdown', pt, extra); await pointer('pointerup', pt, extra); };
  const dragBox = async (a, b, extra = {}) => {
    await pointer('pointerdown', a, extra);
    await pointer('pointermove', [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], extra);
    await pointer('pointermove', b, extra);
    await pointer('pointerup', b, extra);
  };
  const isObjectVisible = o => {
    for (let p = o; p; p = p.parent) if (p.visible === false) return false;
    return true;
  };
  const outlinesFor = () => {
    const ids = new Set();
    view.scene.traverse(o => {
      if ((o.isLine || o.isLineSegments) && isObjectVisible(o) && o.userData?.pieceId && !o.userData.isHover) ids.add(o.userData.pieceId);
    });
    return ids;
  };
  const visibleOutlineObjectsFor = id => {
    const out = [];
    view.scene.traverse(o => {
      if ((o.isLine || o.isLineSegments) && isObjectVisible(o) && o.userData?.pieceId === id && !o.userData.isHover) out.push(o);
    });
    return out;
  };
  const dispose = () => { abort.abort(); view.dispose(); };
  return { plan, dom, view, canvas, tools, visibility, terrain, devices, ops, look, pixel, projectWorld, pointer, clickAt, dragBox, outlinesFor, visibleOutlineObjectsFor, dispose };
}

// ---------------------------------------------------------------------------
// 2. Real household yard geometry: rendered bounds, canopy clipping,
//    level/building/floor excluded, ghosts & grass skipped, instance cache,
//    #editor-drag-outline overlay, whole-inside, floor/room views, Esc
// ---------------------------------------------------------------------------
await test('real_household_yard_marquee_bounds_grass_ghosts_exclusions_and_cache', async () => {
  const ed = await mountEditor(makeHousehold(), 'high');
  try {
    // Attach a real InstancedMesh of plants in view.groups.site to test per-instance bounds & caching
    const instGeo = new THREE.BoxGeometry(2 * FT, 8 * FT, 2 * FT).translate(0, 4 * FT, 0);
    const instMat = new THREE.MeshStandardMaterial({ color: '#4a7a3a' });
    const instPlants = new THREE.InstancedMesh(instGeo, instMat, 2);
    instPlants.userData.instances = [
      { pieceId: 'plant:inst-a', kind: 'planting' },
      { pieceId: 'plant:inst-b', kind: 'planting' },
    ];
    instPlants.setMatrixAt(0, new THREE.Matrix4().makeTranslation(200, 0, -200));
    instPlants.setMatrixAt(1, new THREE.Matrix4().makeTranslation(240, 0, -200));
    instPlants.instanceMatrix.needsUpdate = true;
    ed.view.groups.site.add(instPlants);

    // Instrument REAL household lawn tiles (yardGrass InstancedMesh built by buildYard):
    // lawn blades must NEVER be walked or allocated per blade during selectionBounds/marquee.
    const realGrassTiles = [];
    ed.view.groups.site.traverse(o => {
      if (o.isInstancedMesh && o.userData?.yardGrass) realGrassTiles.push(o);
    });
    assert.ok(realGrassTiles.length > 0, 'real household lawn has yardGrass InstancedMesh tiles');
    let realGrassReads = 0;
    const restoreGrass = realGrassTiles.map(tile => {
      const origGet = tile.getMatrixAt.bind(tile);
      const origPiece = tile.userData.instancePiece;
      tile.getMatrixAt = (i, t) => { realGrassReads++; return origGet(i, t); };
      if (origPiece) tile.userData.instancePiece = i => { realGrassReads++; return origPiece(i); };
      return () => { tile.getMatrixAt = origGet; if (origPiece) tile.userData.instancePiece = origPiece; };
    });

    // Frame the yard cluster around [195..220, 195..210] where real canopy tree,
    // inst-a, fix:yard-1, fix:line-1, eff:yard-1 live.
    ed.view.setView('ext');
    ed.look([205, 200, 0], null, 130);

    // Instrument getMatrixAt and Box3.applyMatrix4 on instPlants (under FT=0.3048 float64 scale!)
    // to verify BOTH local instance cache AND float64 world-matrix cache across repeat calls.
    let matrixReads = 0;
    const realGetMatrixAt = instPlants.getMatrixAt.bind(instPlants);
    instPlants.getMatrixAt = (i, target) => { matrixReads++; return realGetMatrixAt(i, target); };

    const bounds1 = ed.view.selectionBounds();
    assert.equal(matrixReads, 2, 'first bounds call reads each instance matrix once');
    assert.equal(realGrassReads, 0, 'real household lawn yardGrass tiles were NEVER read');

    // Second call with unchanged float64 matrixWorld (FT = 0.3048) must reuse world boxes too.
    const bounds2 = ed.view.selectionBounds();
    assert.equal(matrixReads, 2, 'second bounds call reuses cached instance boxes (0 reads)');
    assert.equal(realGrassReads, 0, 'real household lawn yardGrass tiles still never read');

    // Verify Float64Array world-matrix cache key does not miss on non-float32-exact FT = 0.3048 scale.
    const f64Group = new THREE.Group();
    f64Group.scale.setScalar(FT);
    const f64Inst = new THREE.InstancedMesh(instGeo, instMat, 2);
    f64Inst.userData.instances = [{ pieceId: 'plant:f64-a', kind: 'planting' }, { pieceId: 'plant:f64-b', kind: 'planting' }];
    f64Inst.setMatrixAt(0, new THREE.Matrix4().makeTranslation(10, 0, -10));
    f64Inst.setMatrixAt(1, new THREE.Matrix4().makeTranslation(20, 0, -20));
    f64Inst.instanceMatrix.needsUpdate = true;
    f64Group.add(f64Inst);
    let applyCalls = 0;
    const origApply = THREE.Box3.prototype.applyMatrix4;
    THREE.Box3.prototype.applyMatrix4 = function(m) { applyCalls++; return origApply.call(this, m); };
    try {
      selectionBoxes({ yard: f64Group, visible: () => true });
      const afterFirst = applyCalls;
      assert.ok(afterFirst >= 2, 'first call computes world boxes under FT=0.3048');
      selectionBoxes({ yard: f64Group, visible: () => true });
      assert.equal(applyCalls, afterFirst, 'second call reuses cached float64 world boxes (0 applyMatrix4 calls)');
    } finally {
      THREE.Box3.prototype.applyMatrix4 = origApply;
    }

    instPlants.instanceMatrix.needsUpdate = true;
    ed.view.selectionBounds();
    assert.equal(matrixReads, 4, 'bumping instanceMatrix.version invalidates instance box cache');

    // Ghosts (both building wall ghost AND yard planting ghost), levels, buildings and floor slabs excluded.
    assert.ok(!bounds1.some(r => r.pieceId === 'wall:ghost-test'), 'ghost building wall skipped');
    assert.ok(!bounds1.some(r => r.pieceId === 'plant:ghost-yard'), 'ghost yard planting skipped');
    assert.ok(!bounds1.some(r => ['level', 'building', 'floor'].includes(r.kind)), 'level/building/floor excluded');
    assert.ok(!bounds1.some(r => String(r.pieceId).startsWith('floor:')), 'floor:* slabs excluded');

    // Real household wide-canopy tree (rendered geometry, not heuristic):
    const treeBound = bounds2.find(r => r.pieceId === 'plant:canopy');
    assert.ok(treeBound, 'real household canopy tree has rendered bounds');
    assert.ok(treeBound.bounds.right - treeBound.bounds.left > 20, 'canopy tree has wide rendered screen bounds');

    // A marquee cutting through the canopy does NOT select the tree; enclosing it DOES.
    const standSel = createSelection();
    const standMarquee = createMarquee({ view: ed.view, selection: standSel, visibility: ed.visibility, getPlan: () => ed.plan });
    const origPickAll = ed.view.pickAll;
    ed.view.pickAll = () => { throw new Error('marquee must never raycast'); };
    try {
      const mDrag = (box, extra = {}) => {
        assert.equal(standMarquee.pointerDown({ button: 0, pointerId: 9, clientX: box.left, clientY: box.top, ...extra }), true);
        standMarquee.pointerMove({ pointerId: 9, clientX: box.right, clientY: box.bottom, ...extra });
        assert.equal(standMarquee.pointerUp({ pointerId: 9, clientX: box.right, clientY: box.bottom, ...extra }), true);
      };
      // Touch pointerdown never starts a marquee
      assert.equal(standMarquee.pointerDown({ button: 0, pointerId: 12, pointerType: 'touch', clientX: 10, clientY: 10 }), false, 'touch never starts marquee');
      // Cutting through the left edge of the real canopy:
      mDrag({ left: treeBound.bounds.left + 4, top: treeBound.bounds.top - 5, right: treeBound.bounds.right + 5, bottom: treeBound.bounds.bottom + 5 });
      assert.ok(!standSel.has({ pieceId: 'plant:canopy' }), 'marquee cutting through real canopy does NOT select tree');
      // Enclosing the full rendered canopy:
      mDrag({ left: treeBound.bounds.left - 2, top: treeBound.bounds.top - 2, right: treeBound.bounds.right + 2, bottom: treeBound.bounds.bottom + 2 });
      assert.ok(standSel.has({ pieceId: 'plant:canopy' }), 'marquee enclosing full rendered canopy DOES select tree');

      // Real fixtures (point, line, effect) & instanced plants:
      const instABound = bounds2.find(r => r.pieceId === 'plant:inst-a');
      const instBBound = bounds2.find(r => r.pieceId === 'plant:inst-b');
      assert.ok(instABound && instBBound, 'both plant instances have independent bounds');
      mDrag({ left: instABound.bounds.left - 2, top: instABound.bounds.top - 2, right: instABound.bounds.right + 2, bottom: instABound.bounds.bottom + 2 });
      assert.ok(standSel.has({ pieceId: 'plant:inst-a' }) && !standSel.has({ pieceId: 'plant:inst-b' }), 'instanced plants selected per instance');

      // Ctrl-marquee adds inst-b, Alt-marquee removes inst-b
      mDrag({ left: instBBound.bounds.left - 2, top: instBBound.bounds.top - 2, right: instBBound.bounds.right + 2, bottom: instBBound.bounds.bottom + 2 }, { ctrlKey: true });
      assert.deepEqual(standSel.members().map(r => r.pieceId).sort(), ['plant:inst-a', 'plant:inst-b']);
      mDrag({ left: instBBound.bounds.left - 2, top: instBBound.bounds.top - 2, right: instBBound.bounds.right + 2, bottom: instBBound.bounds.bottom + 2 }, { altKey: true });
      assert.deepEqual(standSel.members().map(r => r.pieceId), ['plant:inst-a']);

      // Fixtures (point, line, effect) in real scene; ghost yard item skipped:
      const allBox = { left: -10000, top: -10000, right: 10000, bottom: 10000 };
      mDrag(allBox);
      const allIds = standSel.members().map(r => r.pieceId);
      assert.ok(allIds.includes('fix:yard-1'), 'point light fixture selected');
      assert.ok(allIds.includes('fix:line-1'), 'line light fixture selected');
      assert.ok(allIds.includes('eff:yard-1'), 'effect fixture selected');
      assert.ok(!allIds.includes('wall:ghost-test'), 'ghost wall never selected by marquee');
      assert.ok(!allIds.includes('plant:ghost-yard'), 'ghost yard item never selected by marquee');
      assert.ok(standSel.members().every(r => !['level', 'building', 'floor'].includes(r.kind)), 'level/building/floor never become marquee members');
      assert.equal(realGrassReads, 0, 'full marquee over real household never touched real yardGrass blades');

      // Restore grass wrappers before visibility.hide (twin_visibility intentionally reads grass tiles for pad hiding)
      restoreGrass.forEach(fn => fn());

      // Hidden and locked skipped by marquee
      ed.visibility.hide('fix:yard-1');
      ed.visibility.lock('eff:yard-1');
      mDrag(allBox);
      assert.ok(!standSel.has({ pieceId: 'fix:yard-1' }), 'hidden fixture skipped');
      assert.ok(!standSel.has({ pieceId: 'eff:yard-1' }), 'locked fixture skipped');
      ed.visibility.showAll();
      ed.visibility.unlock('eff:yard-1');
    } finally {
      ed.view.pickAll = origPickAll;
      standMarquee.dispose();
    }

    // Touch pointerdown on empty space does NOT start a marquee and leaves controls enabled
    const dragOutline = document.getElementById('editor-drag-outline');
    ed.view.controls.enabled = true;
    await ed.pointer('pointerdown', [10, 10], { pointerId: 20, pointerType: 'touch' });
    assert.equal(ed.view.controls.enabled, true, 'touch on empty space leaves OrbitControls enabled');
    await ed.pointer('pointermove', [120, 120], { pointerId: 20, pointerType: 'touch' });
    assert.equal(dragOutline.getAttribute('points'), '', 'touch drag on empty space draws no marquee');
    await ed.pointer('pointerdown', [40, 40], { pointerId: 21, pointerType: 'touch' });
    assert.equal(ed.view.controls.enabled, true, 'second finger keeps controls enabled for pinch/orbit');
    await ed.pointer('pointerup', [40, 40], { pointerId: 21, pointerType: 'touch' });
    await ed.pointer('pointerup', [120, 120], { pointerId: 20, pointerType: 'touch' });

    // Hovering a yard item must NOT traverse view.scene or clone boxes for unrelated pieces
    ed.view.refreshSelection(); // cold cache so hover genuinely resolves the target box
    let sceneTraverses = 0, selectionTraverses = 0, hoverBoxClones = 0;
    const origTraverse = ed.view.scene.traverse.bind(ed.view.scene);
    const origBoxClone = THREE.Box3.prototype.clone;
    ed.view.scene.traverse = fn => {
      sceneTraverses++;
      const stack = String(new Error().stack || '');
      if (!stack.includes('startEnvironmentFrame') && !stack.includes('drawMirror')) selectionTraverses++;
      return origTraverse(fn);
    };
    THREE.Box3.prototype.clone = function() { hoverBoxClones++; return origBoxClone.call(this); };
    try {
      // Direct selectionBoxFor on the yard canopy tree: literally 0 scene.traverse and 1 Box3 clone
      const directBox = selectionBoxFor({ yard: ed.view.groups.site, scene: ed.view.scene, plan: ed.plan, visible: () => true, pieceId: 'plant:canopy', kind: 'planting' });
      assert.ok(directBox && !directBox.box.isEmpty(), 'selectionBoxFor resolves target yard plant');
      assert.equal(sceneTraverses, 0, 'selectionBoxFor never calls scene.traverse');
      assert.equal(hoverBoxClones, 1, 'selectionBoxFor clones only the target Box3');

      hoverBoxClones = 0;
      const pCanopy = ed.pixel([195, 195, 4]);
      await fire(ed.canvas, 'pointermove', { pointerId: 1, buttons: 0, clientX: pCanopy[0], clientY: pCanopy[1] });
      assert.equal(selectionTraverses, 0, 'hovering a yard item never triggers scene.traverse outside render frame');
      assert.ok(hoverBoxClones <= 3, `cold yard hover clones only target box, got ${hoverBoxClones}`);
      // Hover off and back onto the same yard item -> cached in hoverBoxCache, minimal clones
      await fire(ed.canvas, 'pointermove', { pointerId: 1, buttons: 0, clientX: 5, clientY: 5 });
      hoverBoxClones = 0;
      await fire(ed.canvas, 'pointermove', { pointerId: 1, buttons: 0, clientX: pCanopy[0], clientY: pCanopy[1] });
      assert.equal(selectionTraverses, 0, 'repeat yard hover never calls scene.traverse outside render frame');
      assert.ok(hoverBoxClones <= 1, `cached repeat yard hover clones at most 1 box, got ${hoverBoxClones}`);
    } finally {
      ed.view.scene.traverse = origTraverse;
      THREE.Box3.prototype.clone = origBoxClone;
    }

    // Marquee threshold (< 4 px stays a click) & shared #editor-drag-outline overlay (no .editor-marquee)
    assert.equal(MARQUEE_THRESHOLD_PX, 4);
    assert.equal(document.querySelector('.editor-marquee'), null, 'no .editor-marquee div created');
    ed.tools.selectionStore.set([{ kind: 'planting', pieceId: 'plant:inst-a' }]);
    await ed.pointer('pointerdown', [10, 10]);
    await ed.pointer('pointermove', [120, 120]);
    assert.equal(dragOutline.getAttribute('points'), '10,10 120,10 120,120 10,120', 'marquee draws on existing #editor-drag-outline');
    await fire(document, 'keydown', { key: 'Escape' });
    assert.equal(dragOutline.getAttribute('points'), '', 'first Escape clears #editor-drag-outline');
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), ['plant:inst-a'], 'first Escape keeps existing selection');
    await ed.pointer('pointerup', [120, 120]);
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), ['plant:inst-a'], 'releasing cancelled marquee does not change selection');
    await fire(document, 'keydown', { key: 'Escape' });
    assert.deepEqual(ed.tools.selectionStore.members(), [], 'second Escape clears the selection');

    // Outlines for every selected member (VISIBLE outlines only, and exactly ONE per yard piece!)
    const outlineMembers = ['planting', 'light_fixture', 'effect_fixture'].map(k => bounds2.find(r => r.kind === k)).filter(Boolean);
    ed.tools.selectionStore.set(outlineMembers);
    const outlined = ed.outlinesFor();
    for (const ref of outlineMembers) assert.ok(outlined.has(ref.pieceId), `visible outline drawn for ${ref.kind}:${ref.pieceId}`);

    // Single visible outline on selected yard plant, and outline updates after yard rebuild (deferYard)
    ed.tools.select({ kind: 'planting', id: 'plant:canopy' });
    const canopyOutlinesBefore = ed.visibleOutlineObjectsFor('plant:canopy');
    assert.equal(canopyOutlinesBefore.length, 1, 'exactly ONE visible outline for selected yard plant (no duplicate library outline)');
    const oldBoxCenter = canopyOutlinesBefore[0].box.getCenter(new THREE.Vector3());
    // Move the plant and rebuild with yardLater (exercises deferYard paintSelection)
    const canopyRec = ed.plan.site.planting.find(p => p.id === 'plant:canopy');
    canopyRec.at = [215, 205];
    const yardDone = new Promise(resolve => ed.dom.sceneHost.addEventListener('twinyardrebuilt', resolve, { once: true }));
    await ed.view.rebuild(ed.plan, { yardLater: true });
    await yardDone;
    const canopyOutlinesAfter = ed.visibleOutlineObjectsFor('plant:canopy');
    assert.equal(canopyOutlinesAfter.length, 1, 'still exactly ONE visible outline after yard rebuild');
    const newBoxCenter = canopyOutlinesAfter[0].box.getCenter(new THREE.Vector3());
    assert.ok(newBoxCenter.distanceTo(oldBoxCenter) > 15 * FT, 'plant outline moved to new rendered bounds after deferYard');
    const expectedCenterX = 215 * FT, expectedCenterZ = -205 * FT;
    assert.ok(Math.abs(newBoxCenter.x - expectedCenterX) < 1 && Math.abs(newBoxCenter.z - expectedCenterZ) < 1, 'outline matches new rendered plant position');

    // View-level Ctrl-click on light fixture then effect fixture: both become members & effect card shows
    ed.tools.select(null);
    ed.look([208, 205, 2], null, 45);
    const fixRoot = ed.view.scene.getObjectByName('editor-light-fixtures');
    const lightMesh = fixRoot.children.find(m => m.userData.fixtureId === 'fix:yard-1');
    const effectMesh = fixRoot.children.find(m => m.userData.effectId === 'eff:yard-1');
    assert.ok(lightMesh && effectMesh, 'real fixture meshes exist in scene');
    const pLight = ed.projectWorld(lightMesh.position);
    const pEffect = ed.projectWorld(effectMesh.position);
    await ed.clickAt(pLight, { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), ['fix:yard-1']);
    assert.equal(ed.dom.pieceCard.hidden, false);
    await ed.clickAt(pEffect, { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), ['fix:yard-1', 'eff:yard-1'], 'view-level Ctrl-click adds both light and effect fixtures');
    assert.equal(ed.dom.pieceCard.hidden, false, 'effect fixture card is visible');
    assert.ok(ed.dom.pieceCard.querySelector('[data-selection-summary]'), 'multiple fixtures show the set card');
    assert.ok(ed.outlinesFor().has('fix:yard-1') && ed.outlinesFor().has('eff:yard-1'), 'both fixtures have visible outlines');

    // Moving a selected fixture + devices.refresh() updates its outline box (no stale box)
    const oldEffCenter = ed.visibleOutlineObjectsFor('eff:yard-1')[0].box.getCenter(new THREE.Vector3());
    const effRec = ed.plan.effect_fixtures.find(f => f.id === 'eff:yard-1');
    effRec.at = [214, 209, 1];
    ed.devices.refresh();
    const newEffCenter = ed.visibleOutlineObjectsFor('eff:yard-1')[0].box.getCenter(new THREE.Vector3());
    assert.ok(newEffCenter.distanceTo(oldEffCenter) > 4 * FT, 'fixture outline updates after fixture redraw');

    // Floor view limits marquee to that floor + yard only (skips other buildings & L2)
    const main = ed.plan.buildings.find(b => b.id === 'main-house');
    assert.ok(main.levels.some(l => l.id === 'L1') && main.levels.some(l => l.id === 'L2'));
    ed.view.setView('main-house:L1');
    ed.look([100, 100, 0], null, 550);
    await ed.dragBox([5, 5], [1435, 895]);
    const floorMembers = ed.tools.selectionStore.members();
    assert.ok(floorMembers.some(r => r.buildingId === 'main-house' && r.kind === 'wall'), 'selects main-house L1 walls');
    assert.ok(floorMembers.some(r => r.buildingId === 'main-house' && r.kind === 'opening'), 'selects main-house L1 openings');
    assert.ok(floorMembers.some(r => !r.buildingId && r.kind === 'planting'), 'floor view still includes yard');
    assert.ok(floorMembers.every(r => !r.buildingId || r.buildingId === 'main-house'), 'floor view skips pool-house');
    const l2Ids = new Set([...main.walls, ...main.rooms, ...main.openings].filter(p => p.level === 'L2').map(p => p.id));
    assert.ok(floorMembers.every(r => !l2Ids.has(r.pieceId)), 'floor view skips L2');
    assert.ok(floorMembers.every(r => !['level', 'building', 'floor'].includes(r.kind)), 'no level/building/floor in floor marquee');

    assert.equal(ed.ops.length, 0, 'marquee never writes an op or history entry');
    instPlants.removeFromParent();
    instGeo.dispose(); instMat.dispose();
  } finally {
    ed.dispose();
  }
});

// ---------------------------------------------------------------------------
// 3. Ctrl-click toggle, plain replace, empty clear, outlines, AND
//    Ctrl-click on a selected wall's handle bypasses handle drag and toggles
// ---------------------------------------------------------------------------
await test('ctrl_click_toggle_plain_replace_empty_clear_and_handle_bypass', async () => {
  const ed = await mountEditor(makeHousehold(), 'low');
  try {
    const B = 'pool-house';
    const b = ed.plan.buildings.find(x => x.id === B);
    const walls = b.walls.filter(w => w.level === 'L1' && w.kind !== 'separator' && w.state !== 'ghost');
    assert.ok(walls.length >= 2);
    ed.view.setView(`${B}:L1`);
    const midOf = w => [(w.from[0] + w.to[0]) / 2, (w.from[1] + w.to[1]) / 2, 4];
    const avg = [0, 1].map(axis => walls.reduce((s, w) => s + (w.from[axis] + w.to[axis]) / 2, 0) / walls.length);
    ed.look([avg[0], avg[1], 0], b, 90);
    const pickableWalls = walls.filter(w => ed.view.pick(...ed.pixel(midOf(w), b))?.id === w.id);
    assert.ok(pickableWalls.length >= 2);
    const wA = pickableWalls[0], wB = pickableWalls[1];
    const pA = ed.pixel(midOf(wA), b);
    const pB = ed.pixel(midOf(wB), b);

    // Plain click selects wall A
    await ed.clickAt(pA);
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [wA.id]);
    assert.equal(ed.tools.selection().id, wA.id);
    assert.equal(ed.dom.pieceCard.hidden, false);
    assert.ok(ed.outlinesFor().has(wA.id));

    // Ctrl-click on selected wall A's handles (endpoint joint handle & midpoint wall handle)
    // bypasses handle drag and ACTUALLY toggles membership.
    const wallHandles = ed.tools.handles();
    const jointHandle = wallHandles.find(h => h.kind === 'joint');
    const wallHandle = wallHandles.find(h => h.kind === 'wall');
    assert.ok(jointHandle && wallHandle, 'selected wall exposes joint endpoint and wall handles');
    const jPt = ed.pixel(jointHandle.at, b);
    assert.equal(ed.tools.handleAt({ button: 0, clientX: jPt[0], clientY: jPt[1] }), true, 'plain press hits joint endpoint handle');
    const beforeJointMembers = ed.tools.selectionStore.members().map(r => r.pieceId);
    await ed.pointer('pointerdown', jPt, { ctrlKey: true });
    assert.equal(ed.tools.dragging(), false, 'Ctrl-press on endpoint handle does NOT start handle drag');
    await ed.pointer('pointerup', jPt, { ctrlKey: true });
    const afterJointMembers = ed.tools.selectionStore.members().map(r => r.pieceId);
    assert.notDeepEqual(afterJointMembers, beforeJointMembers, 'Ctrl-click on joint handle actually toggles membership');
    assert.equal(ed.ops.length, 0, 'Ctrl-click on endpoint handle records no op');

    // Re-select wall A and Ctrl-click its wall handle to toggle it OFF cleanly
    await ed.clickAt(pA);
    assert.equal(ed.tools.selectionStore.has({ pieceId: wA.id, buildingId: B }), true);
    const wPt = ed.pixel(wallHandle.at, b);
    assert.equal(ed.tools.handleAt({ button: 0, clientX: wPt[0], clientY: wPt[1] }), true, 'plain press hits wall handle');
    await ed.clickAt(wPt, { ctrlKey: true });
    assert.equal(ed.tools.dragging(), false, 'Ctrl-click on wall handle does not drag');
    assert.equal(ed.tools.selectionStore.has({ pieceId: wA.id, buildingId: B }), false, 'Ctrl-click on handle toggles wall off');
    assert.equal(ed.ops.length, 0, 'Ctrl-click on handle records no op');

    // Room focus: plain click on empty space with a room focused and one boundary wall selected
    // steps BACK to the room (preserving room focus); with >1 member it clears the whole set.
    const room = b.rooms.find(r => r.level === 'L1' && r.state !== 'ghost');
    ed.tools.select({ kind: 'room', id: room.id, building: B });
    assert.equal(ed.tools.selection().room, null, 'plain room selection does not focus');
    ed.tools.focusRoom({ kind: 'room', id: room.id, building: B });
    assert.equal(ed.tools.selection().room, room.id, 'explicit room is focused');
    const boundaryWall = ed.tools.selection().tinted.walls[0];
    assert.ok(boundaryWall, 'room has boundary wall');
    ed.tools.select({ kind: 'wall', id: boundaryWall, building: B });
    assert.equal(ed.tools.selection().room, room.id);
    assert.equal(ed.tools.selection().id, boundaryWall);
    await ed.clickAt([10, 10]); // plain click on empty space -> steps back to room!
    assert.equal(ed.tools.selection().room, room.id, 'empty click with 1 wall in focused room keeps room focus');
    assert.equal(ed.tools.selection().id, room.id, 'empty click steps back to the focused room');
    await ed.clickAt([10, 10]); // second empty click clears room focus
    assert.equal(ed.tools.selection().room, null);
    assert.equal(ed.tools.selection().id, null);

    // Re-select wall A, Ctrl-click adds wall B, outlines cover both
    await ed.clickAt(pA);
    await ed.clickAt(pB, { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [wA.id, wB.id]);
    assert.equal(ed.tools.selection().id, wB.id);
    const outlined = ed.outlinesFor();
    assert.ok(outlined.has(wA.id) && outlined.has(wB.id));

    // Ctrl-click removes wall A; Cmd-click adds it back; plain click replaces
    await ed.clickAt(pA, { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [wB.id]);
    await ed.clickAt(pA, { metaKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [wB.id, wA.id]);
    await ed.clickAt(pB);
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [wB.id]);

    // Empty click clears whole set
    await ed.clickAt(pA, { ctrlKey: true });
    await ed.clickAt([10, 10]);
    assert.deepEqual(ed.tools.selectionStore.members(), []);
    assert.equal(ed.tools.selection().id, null);
    assert.equal(ed.dom.pieceCard.hidden, true);
    assert.equal(ed.ops.length, 0);
  } finally {
    ed.dispose();
  }
});

// ---------------------------------------------------------------------------
// 4. Scene tree Ctrl/Shift, locked tree-only, AND Ctrl-toggled pad/fixture card
// ---------------------------------------------------------------------------
await test('scene_tree_ctrl_shift_locked_and_ctrl_toggled_pad_and_fixture_cards', async () => {
  const ed = await mountEditor(makeHousehold(), 'low');
  try {
    const B = 'pool-house';
    const b = ed.plan.buildings.find(x => x.id === B);
    const room = b.rooms.find(r => r.level === 'L1');
    ed.tools.chooseFloor(`${B}:L1`);
    ed.tools.selectionStore.set([{ kind: 'room', pieceId: room.id, buildingId: B }]);
    ed.tools.refresh();

    const tree = ed.dom.sceneTreeHost;
    const rowOf = id => tree.querySelector(`[data-scene-id="${id}"]`);
    const labelOf = id => rowOf(id).querySelector('[data-scene-select]');

    const disc = rowOf(room.id)?.querySelector('[data-row-disclosure]');
    if (disc && disc.getAttribute('aria-expanded') === 'false') await click(disc);

    const wallSet = new Set(b.walls.map(w => w.id));
    const roomWalls = tree.querySelectorAll('[data-scene-id]')
      .map(n => n.dataset.sceneId)
      .filter(id => wallSet.has(id))
      .map(id => b.walls.find(w => w.id === id));
    assert.ok(roomWalls.length >= 3);
    const [r0, r1, r2] = roomWalls;

    // Plain click r0, lock r1, Ctrl-click r1 in Scene tree
    await fire(labelOf(r0.id), 'click');
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [r0.id]);
    ed.visibility.lock(r1.id);
    assert.equal(ed.visibility.isPickable({ id: r1.id, kind: 'wall', building: B }), false);
    await fire(labelOf(r1.id), 'click', { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [r0.id, r1.id]);
    assert.equal(rowOf(r0.id).getAttribute('aria-selected'), 'true');
    assert.equal(rowOf(r1.id).getAttribute('aria-selected'), 'true');
    assert.ok(ed.outlinesFor().has(r0.id) && ed.outlinesFor().has(r1.id));

    // Ctrl-click removes r0; Shift-click skips hidden r1
    await fire(labelOf(r0.id), 'click', { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [r1.id]);
    ed.visibility.unlock(r1.id);
    await fire(labelOf(r0.id), 'click');
    ed.visibility.hide(r1.id);
    await fire(labelOf(r2.id), 'click', { shiftKey: true });
    const rangeIds = ed.tools.selectionStore.members().map(r => r.pieceId);
    assert.ok(rangeIds.includes(r0.id) && rangeIds.includes(r2.id) && !rangeIds.includes(r1.id));
    ed.visibility.showAll();

    // A mixed set containing a pad shows its set card; narrowing reaches terrain.
    const padId = ed.plan.site.terraces[0].id;
    assert.ok(rowOf(padId), 'pad row is present in Scene tree under Yard');
    await fire(labelOf(r0.id), 'click');
    await fire(labelOf(padId), 'click', { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [r0.id, padId], 'multi-selection retains wall and pad');
    assert.equal(ed.tools.selectionStore.primary().pieceId, padId, 'pad is primary');
    const terrainCard = document.getElementById('terrain-card');
    const narrowSummary = async text => {
      const summary = ed.dom.pieceCard.querySelector('[data-selection-summary]'); assert.ok(summary);
      const entry = [...summary.querySelectorAll('button')].find(b => b.textContent === text); assert.ok(entry, text); await fire(entry, 'click');
    };
    assert.equal(terrainCard.hidden, true, 'multiple pieces show the set card');
    await narrowSummary('1 pad');
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [padId], 'summary narrows to pad');
    assert.ok(!terrainCard.hidden, 'narrowing opens #terrain-card');
    assert.match(terrainCard.textContent, /Delete|Height|Ground and yard/, 'terrain card renders pad controls');

    // Restore the mixed set using the Scene tree, then narrow to the light.
    await fire(labelOf(r0.id), 'click'); await fire(labelOf(padId), 'click', { ctrlKey: true });
    await fire(labelOf('fix:yard-1'), 'click', { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [r0.id, padId, 'fix:yard-1']);
    assert.equal(ed.tools.selectionStore.primary().pieceId, 'fix:yard-1');
    assert.equal(ed.dom.pieceCard.hidden, false, 'Ctrl-toggled light fixture shows #piece-card');
    assert.ok(ed.dom.pieceCard.querySelector('[data-selection-summary]'), 'mixed set card is active');
    await narrowSummary('1 light');
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), ['fix:yard-1']);
    assert.ok(ed.dom.pieceCard.dataset.fixtureCard, 'narrowing opens the fixture card');
    assert.match(ed.dom.pieceCard.textContent, /Fixtures|light\.yard/, 'fixture card renders fixture controls');
    assert.equal(terrainCard.hidden, true, 'previous terrain card closes when fixture becomes primary');

    await fire(labelOf(r0.id), 'click'); await fire(labelOf(padId), 'click', { ctrlKey: true });
    await fire(labelOf('fix:yard-1'), 'click', { ctrlKey: true });
    // Ctrl-toggled EFFECT FIXTURE retains the set card.
    await fire(labelOf('eff:yard-1'), 'click', { ctrlKey: true });
    assert.equal(ed.tools.selectionStore.primary().pieceId, 'eff:yard-1');
    assert.equal(ed.dom.pieceCard.hidden, false, 'Ctrl-toggled effect fixture shows #piece-card');
    assert.ok(ed.dom.pieceCard.querySelector('[data-selection-summary]'));

    // Removing fixtures leaves the wall/pad set; narrowing still reaches terrain.
    await fire(labelOf('eff:yard-1'), 'click', { ctrlKey: true });
    await fire(labelOf('fix:yard-1'), 'click', { ctrlKey: true });
    assert.equal(ed.tools.selectionStore.primary().pieceId, padId);
    assert.ok(ed.dom.pieceCard.querySelector('[data-selection-summary]'), 'wall and pad still show a set');
    await narrowSummary('1 pad');
    assert.equal(terrainCard.hidden, false, 'summary still reaches the pad card after removing fixtures');

    // Ctrl-click on building row and floor/level row never adds building or level refs to the store
    await fire(labelOf(r0.id), 'click');
    const buildingRow = rowOf(B);
    const levelRow = tree.querySelector(`[data-floor="${B}:L1"]`)?.closest('[data-scene-id]');
    assert.ok(buildingRow && levelRow, 'building and level rows exist in Scene tree');
    await fire(buildingRow.querySelector('[data-scene-select]'), 'click', { ctrlKey: true });
    await fire(levelRow.querySelector('[data-scene-select]'), 'click', { ctrlKey: true });
    assert.deepEqual(ed.tools.selectionStore.members().map(r => r.pieceId), [r0.id], 'Ctrl-click on building/level adds neither');
    // Shift-range across building/level rows excludes building and level refs
    await fire(buildingRow.querySelector('[data-scene-select]'), 'click', { shiftKey: true });
    assert.ok(ed.tools.selectionStore.members().every(r => !['building', 'level', 'group'].includes(r.kind)), 'Shift-range across building/level rows adds no building or level refs');

    // Store updates from the view mirror back to Scene tree
    ed.tools.selectionStore.set([
      { kind: 'wall', pieceId: r0.id, buildingId: B },
      { kind: 'wall', pieceId: r1.id, buildingId: B },
    ]);
    assert.equal(rowOf(r0.id).getAttribute('aria-selected'), 'true');
    assert.equal(rowOf(r1.id).getAttribute('aria-selected'), 'true');
    assert.equal(rowOf(r2.id).getAttribute('aria-selected'), 'false');

    assert.equal(ed.ops.length, 0, 'Scene tree selection never writes an op');
  } finally {
    ed.dispose();
  }
});

finish();
"""

if __name__ == '__main__':
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    object_schema = json.loads((ROOT / 'static/twin/object_schema.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {
        'root': ROOT.as_posix(),
        'flat': flat,
        'kit': kit,
        'objectSchema': object_schema,
    }, timeout=180)
    print(out)
    sys.exit(code or 0)
