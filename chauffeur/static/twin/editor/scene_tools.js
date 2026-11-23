import { objectOperation, transformObject, siteShapeKinds } from '../objects.js';
import { isObject } from './object_shelf.js';
import { report, idleInterval } from './api.js';
import { createCards, findPiece, feetInches } from './cards.js';
import { createHaLink } from './ha_link.js';
import { readMaterialNames, materialName } from './material_catalog.js';
import { snapPoint, snapRotation } from './snap.js';
import { sheetMaster, localCentre } from './words.js';
import { createSelection, createRoomSelection } from './selection.js';
import { createMarquee } from './marquee.js';
import { createDrag } from './drag.js';
import { createDimensions } from './dimensions.js';
import { createGizmo } from './gizmo.js';
import { createHandles } from './handles.js';
import { contains } from '../twin_generator.js';
import { createPicker, DRAG_THRESHOLD_PX } from './picking.js';
import { createMeasure } from './measure.js';
import { createContextMenu } from './context_menu.js';
import { moveToAction } from './move_to_action.js';
import { icon } from './icons.js';
import { drawMaterialsList, materialSelectionActions } from './selection_card.js';
import { pieceMaterialSlots, materialIdForSurface } from './selection_materials.js';
import { createSceneTree } from './scene_tree.js';
import { createLayers } from './dock.js';
import { shapeOperation, shapeCentre, transformShape } from './site_shapes.js';
import { deleteOperations, groupTransform, transformOperations } from './group_transform.js';
import { createClipboard, clipboardKey } from './clipboard.js';
import { dialogOpen } from './dialog.js';
import { contextPoint } from './library.js';

const rotatePoint = (p, angle) => {
  const a = angle * Math.PI / 180;
  return [Math.cos(a) * p[0] - Math.sin(a) * p[1], Math.sin(a) * p[0] + Math.cos(a) * p[1]];
};

export function createSceneTools({ view, getPlan, getModel, getKit, getSheets, edit, op, applyBatch = (ops, options) => op({ op: 'batch', ops }, options), panel, canEdit, signal, onInteract, addDormer, siteHits, pickSite, padHits, fixtureHits, isPickable = () => true, visibility, library, api, onDrawFeature, dock, openHouseMaterials, surfaceAt, groundPoint }) {
  const el = id => document.getElementById(id), canvas = view.renderer3.domElement;
  const measureLayer = document.createElement('div'); measureLayer.className = 'editor-measure'; canvas.parentElement.append(measureLayer);
  const measure = createMeasure({ view, getPlan, layer: measureLayer });
  signal.addEventListener('abort', () => { measure.disarm(); measureLayer.remove(); }, { once: true });
  let selection = null, tool = 'select', levelKey = null, sheetOn = false, gesture = null, delegate = null, pointerId = null;
  let ownsGesture = false, handles = null, gizmo = null, controlsBeforePress = null;
  let roofRooms = new Set(), roofRoomBuilding = null;
  let split = null, splitStatus = '';
  let sceneTree = null, refreshingSelection = false, syncingStore = false, seedingDelegate = false, prevPrimaryKind = null;
  function cancelSplit(text = splitStatus) {
    if (!split) return;
    split = null; el('editor-status').textContent = text; canvas.style.cursor = tool === 'select' ? '' : 'crosshair';
  }
  function armSplit({ piece, building }) {
    if (!canEdit()) return;
    delegate?.cancel?.(); setTool('select'); splitStatus = el('editor-status').textContent;
    split = { wall: piece.id, building: building.id }; canvas.style.cursor = 'crosshair';
    el('editor-status').textContent = 'Click the wall where it should split. Esc cancels.';
  }
  function pointerArmedDown(event) {
    if (!split) return false;
    const target = split, hit = view.pickAll(event.clientX, event.clientY).find(p => p.kind === 'wall');
    cancelSplit();
    if (!canEdit() || hit?.id !== target.wall || hit.building !== target.building) return true;
    splitAt(target, hit, event); return true;
  }
  function wallPoint(target, hit, event) {
    const b = getPlan().buildings.find(b => b.id === target.building), w = b?.walls.find(w => w.id === target.wall);
    if (!w) return null;
    const point = hit.point ? rotatePoint([hit.point[0] / .3048 - (b.position?.[0] || 0),
      -hit.point[2] / .3048 - (b.position?.[1] || 0)], -(b.rotation || 0))
      : view.floorAt(event.clientX, event.clientY, `${b.id}:${w.level}`);
    if (!point) return null;
    const d = w.to.map((v, i) => v - w.from[i]), length = Math.hypot(...d);
    return { wall: w, length, at: point.reduce((n, v, i) => n + (v - w.from[i]) * d[i] / length, 0) };
  }
  function splitAt(target, hit, event) {
    const spot = wallPoint(target, hit, event);
    if (!spot || !canEdit()) return;
    const { length } = spot; let { at } = spot;
    if (at < 1 - 1e-9 || length - at < 1 - 1e-9) { el('editor-status').textContent = 'A wall must be at least 1 ft long.'; return true; }
    at = Math.abs(at - length / 2) <= .5 + 1e-9 ? length / 2 : Math.floor(at * 12 + 1e-9) / 12;
    cards.queue(() => canEdit() && op({ op: 'split_wall', ...target, at })).catch(report);
  }
  const pointers = new Set(), cancelledEscapes = new WeakSet();
  const dimensions = createDimensions({ view, onCommit: op, canEdit, signal, getHandles: () => [...(handles?.handles() || []), ...(gizmo?.handles() || [])] });
  function drawDimensions(plan = getPlan(), state = roomSelection.current(), problem = null) {
    if (!isPickable(state)) state = {};
    const building = plan?.buildings.find(b => b.id === state.building);
    const room = building?.rooms.find(r => r.id === (state.kind === 'room' ? state.id : state.room));
    const piece = building?.walls.find(w => state.kind === 'wall' && w.id === state.id)
      || (problem && building?.walls.find(w => w.state !== 'ghost' && w.level === state.level
        && w.joints?.some(id => state.kind === 'joint' ? id === state.id : room?.joints?.includes(id))));
    dimensions.show({ building, piece, room, problem });
  }
  const drag = createDrag({ view, model: getPlan, onPreview(plan, state, problem) {
    handles?.show(plan); drawDimensions(plan, state, problem);
  }, onCommit(operation, options) {
    if (operation.op === 'move_wall') {
      const wall = getPlan().buildings.find(b => b.id === operation.building).walls.find(w => w.id === operation.wall);
      const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
      operation = { ...operation, by: (-d[1] * operation.by[0] + d[0] * operation.by[1]) / length };
    }
    return op(operation, { ...options, drag: true, selection });
  } });
  const getLabel = item => {
    const label = getSheets().piece_labels?.find(p => p.piece === item.pieceId && p.building === item.buildingId)?.label;
    const record = findPiece(getPlan(), item.pieceId, item.buildingId);
    return label || record?.piece.name || `${record?.kind || 'piece'} ${item.pieceId}`;
  };
  const isDelegateKind = kind => ['terraces', 'light_fixture', 'effect_fixture', 'device'].includes(kind);
  const isExcludedSetKind = kind => ['building', 'level', 'group', 'floor'].includes(kind);
  const stepBackOrClear = () => {
    if (selectionStore.members().length > 1) selectionStore.clear();
    else roomSelection.back();
  };
  function delegatePickFor(ref) {
    if (!ref) return null;
    const plan = getPlan();
    if (ref.kind === 'terraces') return { kind: 'terraces', id: ref.pieceId, pieceId: ref.pieceId, building: null };
    if (ref.kind === 'effect_fixture') return { kind: 'effect_fixture', id: ref.pieceId, pieceId: ref.pieceId, effectId: ref.pieceId, fixtureId: ref.pieceId, building: ref.buildingId ?? null };
    if (ref.kind === 'light_fixture') {
      let entity_id = ref.entity_id;
      if (!entity_id) {
        for (const [eid, fs] of Object.entries(plan?.light_fixtures || {})) {
          if ((fs || []).some(f => f.id === ref.pieceId)) { entity_id = eid; break; }
        }
      }
      return { kind: 'light_fixture', id: ref.pieceId, pieceId: ref.pieceId, fixtureId: ref.pieceId, entity_id, building: ref.buildingId ?? null };
    }
    if (ref.kind === 'device') {
      const piece = (ref.buildingId
        ? plan?.buildings?.find(b => b.id === ref.buildingId)?.devices
        : plan?.site?.devices)?.find(d => d.id === ref.pieceId);
      return { kind: 'device', id: ref.pieceId, pieceId: ref.pieceId, building: ref.buildingId ?? null, name: piece?.name || ref.pieceId, piece };
    }
    return null;
  }
  function openDelegateCard(ref) {
    if (!ref || !isDelegateKind(ref.kind)) return false;
    const target = delegatePickFor(ref);
    if (!target) return false;
    seedingDelegate = true;
    try {
      return !!(delegate?.selectTree?.(target) || delegate?.selectPick?.(target));
    } finally {
      seedingDelegate = false;
    }
  }
  function applySelectionState(state, primaryRef = selectionStore.primary()) {
    const changed = (selection?.pieceId ?? null) !== (state.id ?? null) || (selection?.buildingId ?? null) !== (state.building ?? null);
    const previousKind = prevPrimaryKind;
    prevPrimaryKind = primaryRef?.kind ?? state.kind ?? null;
    if (split && (state.id !== split.wall || state.building !== split.building)) cancelSplit();
    if (!state.room || state.building !== roofRoomBuilding || !roofRooms.has(state.room)) {
      roofRooms = new Set(state.room ? [state.room] : []); roofRoomBuilding = state.building;
    }
    selection = state.id ? { pieceId: state.id, buildingId: state.building, kind: state.kind, room: state.room } : null;
    if (!selection) panel.clearSelection();
    if (state.level) levelKey = `${state.building}:${state.level}`;
    if (selectionStore.members().length > 1) {
      delegate?.selectionChanged?.({ ...state, id: '__selection_set__' });
      cards.draw(selection);
    } else if (primaryRef && isDelegateKind(primaryRef.kind)) {
      if (primaryRef.kind === 'terraces') {
        const cardEl = el('piece-card');
        if (cardEl?.dataset.fixtureCard) {
          cardEl.dispatchEvent(new Event('fixturecardrelease'));
          cardEl.hidden = true;
        }
        cards.draw(null);
        const cur = delegate?.visibilitySelection?.();
        if (cur?.id !== primaryRef.pieceId || document.getElementById('terrain-card')?.hidden) {
          openDelegateCard(primaryRef);
        }
      } else {
        delegate?.selectionChanged?.(state);
        const cur = delegate?.visibilitySelection?.();
        const cardEl = el('piece-card');
        if (!cardEl?.dataset.fixtureCard || cur?.id !== primaryRef.pieceId) {
          openDelegateCard(primaryRef);
        }
      }
    } else {
      if (changed && !selection) {
        const cardEl = el('piece-card');
        if (cardEl?.dataset.fixtureCard && !seedingDelegate) {
          cardEl.dispatchEvent(new Event('fixturecardrelease'));
          cardEl.hidden = true;
          dock?.properties.clear(cardEl);
        }
        if (previousKind === 'terraces') {
          delegate?.selectionChanged?.({ ...state, id: '__cleared__' });
        }
      }
      cards.draw(selection);
      delegate?.selectionChanged?.(state);
    }
    handles?.refresh(); gizmo?.draw();
    drawDimensions(getPlan(), state);
    if (!refreshingSelection || changed) sceneTree?.reveal(state.id, state.building);
  }
  const selectionStore = createSelection({
    onChange(members) {
      if (syncingStore) return;
      const primaryRef = members.length ? members[members.length - 1] : null;
      // Clear room focus here (caller), not inside the pure member store (Ruling 1).
      if (roomSelection.current().room && (!members.length || members.length > 1 || !roomSelection.inside(primaryRef))) {
        roomSelection.clearRoom();
      }
      const state = roomSelection.sync(primaryRef);
      applySelectionState(state, primaryRef);
    },
  });
  const roomSelection = createRoomSelection({
    view,
    getModel,
    getMembers: () => selectionStore.members(),
    onSync(state) {
      syncingStore = true;
      try {
        const ref = state.id ? toSelectionRef(state) : null;
        selectionStore.set(ref ? [ref] : []);
      } finally {
        syncingStore = false;
      }
    },
    onChange: state => applySelectionState(state),
  });
  function refreshClipboardButtons() {
    for (const [name, state] of [['copy', clipboard.canCopy()], ['paste', clipboard.canPaste()]]) {
      const button = el(`rail-${name}`);
      if (button) { button.disabled = !state.ok; button.title = state.ok ? name === 'copy' ? 'Copy (Ctrl/Cmd+C)' : 'Paste (Ctrl/Cmd+V)' : state.reason; }
    }
  }
  const clipboard = createClipboard({ getPlan, getModel, getKit, selection: selectionStore, applyBatch, canEdit, view, visibility,
    setStatus: text => { el('editor-status').textContent = text; }, onChange: refreshClipboardButtons });
  selectionStore.subscribe(refreshClipboardButtons);
  refreshClipboardButtons();
  if (library) library.materialMenu = (event, surface) => contextMenu.open(event, { slotSurface: surface });
  function toSelectionRef(picked) {
    if (!picked) return null;
    const id = picked.pieceId ?? picked.id;
    if (!id) return null;
    const building = picked.buildingId ?? picked.building ?? null;
    const record = findPiece(getPlan(), id, building);
    if (record) {
      const ref = { kind: record.kind, pieceId: record.piece.id };
      if (record.building) {
        ref.buildingId = record.building.id;
        const level = record.kind === 'level' ? record.piece.id
          : record.piece.level
            || record.building.walls?.find(w => w.id === (record.piece.wall || record.piece.host?.wall))?.level
            || record.building.rooms?.find(r => r.id === (record.piece.host?.floor || record.piece.host?.ceiling))?.level
            || picked.level || null;
        if (level != null) ref.level = level;
      }
      if (record.poolId !== undefined) ref.poolId = record.poolId;
      return ref;
    }
    const plan = getPlan();
    let kind = picked.kind ?? null;
    let entity_id = picked.entity_id ?? picked.piece?.entity_id;
    if (kind === 'pad') kind = 'terraces';
    else if (kind === 'effect') kind = 'effect_fixture';
    else if (kind === 'fixture' && !building) {
      for (const [eid, fs] of Object.entries(plan?.light_fixtures || {})) {
        if ((fs || []).some(f => f.id === id)) { kind = 'light_fixture'; entity_id ||= eid; break; }
      }
    } else if (kind === 'light_fixture' && !entity_id) {
      for (const [eid, fs] of Object.entries(plan?.light_fixtures || {})) {
        if ((fs || []).some(f => f.id === id)) { entity_id = eid; break; }
      }
    }
    const ref = { kind, pieceId: id };
    if (building != null) ref.buildingId = building;
    if (picked.level != null) ref.level = picked.level;
    if (entity_id !== undefined) ref.entity_id = entity_id;
    if (picked.poolId !== undefined) ref.poolId = picked.poolId;
    return ref;
  }
  function pieceExists(plan, ref) {
    if (!plan || !ref) return false;
    const id = ref.pieceId ?? ref.id;
    if (!id) return false;
    const buildingId = ref.buildingId ?? ref.building ?? null;
    if (findPiece(plan, id, buildingId)) return true;
    if (ref.kind === 'terraces') return (plan.site?.terraces || []).some((p, i) => (p.id || `terraces:${i}`) === id);
    if (ref.kind === 'light_fixture') return Object.values(plan.light_fixtures || {}).some(fs => (fs || []).some(f => f.id === id));
    if (ref.kind === 'effect_fixture') return (plan.effect_fixtures || []).some(f => f.id === id);
    if (ref.kind === 'device') {
      if (buildingId) return (plan.buildings?.find(b => b.id === buildingId)?.devices || []).some(d => d.id === id);
      return (plan.site?.devices || []).some(d => d.id === id);
    }
    return false;
  }
  function seedDelegateSelection() {
    if (selectionStore.members().length) return;
    const active = delegate?.visibilitySelection?.();
    if (!active?.id) return;
    const ref = toSelectionRef(active);
    if (ref) selectionStore.add(ref);
  }
  // Area picks and placements wait behind the card's own field saves (cards.queue).
  const haLink = createHaLink({ api, onCommit: operation => cards.queue(() => op(operation)), signal, getPlan, canEdit });
  let linkReadAt = 0;
  const cards = createCards({ getPlan, getModel, getKit, getLabel, getSelection: roomSelection.current, getFieldLabels: () => getSheets().field_labels || {}, edit: change => change.op === 'set' && change.field === 'rotation'
    ? rotate(change.building, change.value - (getPlan().buildings.find(b => b.id === change.building)?.rotation || 0)) : edit(change),
    dock, op, applyBatch, selectionStore, visibility, view, chooseDestination, addDormer, canEdit, select, library, haLink, onDrawFeature, openHouseMaterials, removeSelection: () => selectionStore.members().length > 1 ? removeSelected() : null, splitWall: armSplit, loadMaterialNames: readMaterialNames, preview: plan => view.rebuild(plan, { preserveYard: true }), ask: item => panel.focusSelection(item, getLabel(item)) });
  signal?.addEventListener('abort', () => cards.dispose(), { once: true });
  const handleSelection = () => isPickable(roomSelection.current()) ? roomSelection.current() : {};
  handles = createHandles({ view, getPlan, getSelection: () => selectionStore.members().length > 1 ? {} : handleSelection(), getTool: () => tool, canEdit, drag, onCommit: (operation, options) => op(operation, { ...options, drag: true, selection }),
    onPreview: drawDimensions, onClick: cards.showRoofEdge, signal });
  const gizmoLayer = document.createElement('div'); gizmoLayer.className = 'editor-handles'; canvas.parentElement.append(gizmoLayer);
  gizmo = createGizmo({ view, layer: gizmoLayer, getPlan, getSelection: handleSelection, getMembers: () => selectionStore.members(), isPickable, getTool: () => tool, canEdit, applyBatch,
    onPreview: plan => delegate?.preview?.(plan),
    op: (operation, options) => op(operation, { ...options, selection: selection?.buildingId ? selection : { kind: selection?.kind, id: selection?.pieceId } }) });
  view.controls.addEventListener('change', gizmo.draw);
  canvas.parentElement.addEventListener('twinrebuilt', gizmo.draw, { signal });
  window.addEventListener('resize', gizmo.draw, { signal });
  // The shell can resize the canvas without a window resize (generation
  // and status rows). Reproject every existing controls-change subscriber.
  if (typeof ResizeObserver !== 'undefined') {
    const resize = new ResizeObserver(() => view.controls.dispatchEvent({ type: 'change' }));
    resize.observe(canvas.parentElement);
    signal.addEventListener('abort', () => resize.disconnect(), { once: true });
  }
  signal.addEventListener('abort', () => { gizmo.finish(true); gizmoLayer.remove(); view.controls.removeEventListener('change', gizmo.draw); }, { once: true });
  const hasHandles = ({ kind, piece, building }) => piece.state !== 'ghost'
    && (['wall', 'joint', 'room', 'roof', 'dormer', 'solar_zone', 'stair'].includes(kind)
      || kind === 'opening' && building.walls.some(w => w.id === piece.wall)
      || ['anchor', 'item'].includes(kind) && !!piece.host);
  const listen = (node, event, fn, options = {}) => node.addEventListener(event, fn, { ...options, signal });
  function levels() {
    const buildings = getPlan()?.buildings || [];
    return buildings.flatMap(b => [...b.levels].sort((a, c) => a.elevation - c.elevation)
      .map((l, i) => ({ key: `${b.id}:${l.id}`, building: b, level: l,
        label: (buildings.length > 1 ? `${b.name || b.id} \u00b7 ` : '') + (l.name || `Floor ${i + 1}`) })));
  }
  function floor() {
    const list = levels();
    return list.find(l => l.key === levelKey) || list[0];
  }
  function select(item) {
    if (!canEdit() && item) return;
    if (!item) {
      if (seedingDelegate) return;
      roomSelection.clear();
      return;
    }
    const record = findPiece(getPlan(), item.id ?? item.pieceId, item.building ?? item.buildingId);
    if (!record) return;
    if (!record.building) {
      roomSelection.clear(); roomSelection.select({ kind: record.kind, id: record.piece.id }); return;
    }
    const level = record.kind === 'level' ? record.piece.id : record.piece.level
      || record.building.walls.find(w => w.id === (record.piece.wall || record.piece.host?.wall))?.level;
    if (['roof', 'dormer', 'solar_zone', 'building', 'level'].includes(record.kind) && roomSelection.current().room) roomSelection.clear();
    roomSelection.select({ kind: record.kind, id: record.piece.id, building: record.building.id, level });
  }
  let contextPicking = false;
  function sceneCandidate(item) {
    if (item?.kind === 'roof') {
      const building = getPlan()?.buildings.find(b => b.id === item.building);
      const section = building?.roof?.sections.find(s => s.id === item.id);
      const dormer = building?.dormers?.find(d => d.id === item.id);
      if (dormer) return { ...item, kind: 'dormer', level: section?.level };
      if (section?.roof) item = { ...item, id: section.roof, pieceId: section.roof, level: section.level };
    }
    const record = item?.kind === 'roof' && findPiece(getPlan(), item.id, item.building);
    const markedRoof = record && (record.piece.state === 'ghost' || record.piece.block
      && record.building.roof.flags?.some(flag => flag.block_rect?.length === 4
        && flag.block_rect.every((v, i) => Math.abs(v - record.piece.block[i]) <= 1)));
    // Existing needs-checking markers still open their own correction card.
    if (!contextPicking && item?.building && !['solar_zone','anchor'].includes(item.kind) && !markedRoof && view.state.view === 'ext' && !roomSelection.current().id)
      return { ...item, kind: 'building', id: item.building, pieceId: item.building, level: null };
    return item;
  }
  const picker = createPicker({ isPickable, sources: [
    (x, y) => { const item = delegate?.pick?.(x, y); return item ? [item] : []; },
    (x, y) => view.pickAll(x, y).filter(isPickable).map(sceneCandidate),
    (x, y) => siteHits ? siteHits(x, y) : [pickSite?.(x, y)].filter(Boolean),
    (x, y) => padHits?.(x, y) || [],
    (x, y) => fixtureHits?.(x, y) || [],
  ] });
  const pick = (x, y) => picker.peek(x, y);
  const marquee = createMarquee({
    view,
    selection: selectionStore,
    visibility,
    getPlan,
    isEmpty: event => {
      contextPicking = true;
      try { return picker.at(event.clientX, event.clientY).length === 0; }
      finally { contextPicking = false; }
    },
  });
  signal.addEventListener('abort', () => marquee.dispose(), { once: true });
  // A locked piece cannot be clicked in the view; when it is the nearest thing under the
  // pointer, say so instead of silently selecting what lies behind it (owner report 2026-11-19).
  const LOCKED_WORDS = { roof: 'This roof section', dormer: 'This dormer', wall: 'This wall', room: 'This room', opening: 'This opening',
    stair: 'This stair', item: 'This item', anchor: 'This anchor', solar_zone: 'This solar zone' };
  function lockedHint(x, y, picked) {
    const status = document.getElementById('editor-status');
    if (!status || !visibility?.isLocked) return;
    const nearest = (view.pickAll?.(x, y) || []).find(hit => !visibility.isHidden?.(hit.id, hit.kind));
    if (!nearest || !visibility.isLocked(nearest.id, nearest.kind)) { delete status.dataset.lockedHint; return; }
    if (picked && picked.id === nearest.id) return;
    status.textContent = `${LOCKED_WORDS[nearest.kind] || 'This piece'} is locked. Unlock it in Layers or the Scene tree to select it here.`;
    status.dataset.lockedHint = nearest.id;
  }
  // Context actions use the same ranked picker, but retain the actual piece
  // under the pointer in the exterior view instead of its navigation parent.
  let contextMaterialWarning = false;
  // Household materials are named by the person, and the right-click menu
  // labels them before any card or the Library has loaded the names.
  let materialNamesRequested = false;
  function requestMaterialNames() {
    if (materialNamesRequested) return;
    materialNamesRequested = true;
    readMaterialNames().catch(error => { materialNamesRequested = false; materialWarning(error); });
  }
  requestMaterialNames();
  function materialWarning(error) {
    if (!contextMaterialWarning) { console.warn('Could not look up the context material.', error); contextMaterialWarning = true; }
  }
  function contextMaterialActions(target) {
    try {
      if (target.materialSurface === false) return [];
      const surface = target.materialSurface;
      const fallbackRef = toSelectionRef(target);
      const slots = !surface && fallbackRef ? pieceMaterialSlots(getPlan(), fallbackRef, getKit()) : [];
      const id = surface ? materialIdForSurface(getPlan(), surface, getKit()) : (slots.find(slot => slot.key === target.part) || (slots.length === 1 ? slots[0] : null))?.current?.id;
      const material = id && (typeof id === 'string' ? { id, name: materialName(id) } : id);
      return material ? materialSelectionActions({ material, refs: selectionStore.members().length ? selectionStore.members() : [fallbackRef].filter(Boolean), selectionStore, getPlan, getKit, view, visibility }) : [];
    } catch (error) { materialWarning(error); return []; }
  }
  function sceneContextItems(target) {
    if (target.slotSurface) return [];
    const materialActions = contextMaterialActions(target);
    if (target.empty) return [{ label: 'Show all hidden', run: () => visibility?.showAll() }];
    const members = selectionStore.members();
    if (members.length > 1 && members.some(ref => ref.pieceId === target.id && (ref.buildingId ?? null) === (target.building ?? null))) {
      return [...materialActions, ...[['Move', 'move'], ['Turn', 'rotate'], ['Scale', 'scale']].map(([label, tool]) => ({ label, disabled: !canEdit(), run: () => setTool(tool) })),
        { label: 'Delete', disabled: !canEdit(), run: removeSelected }, ...visibilityActions(target.id, target.kind)];
    }
    if (target.floor) {
      const row = levels().find(row => row.key === target.floor); if (!row) return [];
      const visible = () => !!view.groups?.levels[row.key]?.visible && !visibility?.isHidden(row.level.id);
      const show = value => { onInteract?.(); select({ id: row.level.id, building: row.building.id });
        if (value) visibility?.show(row.level.id);
        const keys = levels().filter(r => r.key === row.key ? value : !!view.groups?.levels[r.key]?.visible).map(r => r.key); view.showLevels(keys); drawFloors(); };
      return [{ label: 'Show', run: () => show(true), disabled: visible() }, { label: 'Hide', run: () => show(false), disabled: !visible() },
        { label: 'Choose', run: () => chooseFloor(row.key) }, ...visibilityActions(row.level.id, 'level').slice(1)];
    }
    const visibilityActionsForTarget = visibilityActions(target.id, target.visibilityKind || target.kind);
    if (['light_fixture', 'effect_fixture', 'terraces', 'device'].includes(target.kind)) return [...materialActions,
      { label: 'Select', run: () => selectTreeRow(target) }, ...visibilityActionsForTarget];
    const record = findPiece(getPlan(), target.id, target.building); if (!record) return [];
    const action = (label, run) => ({ label, disabled: !canEdit(), run: () => {
      if (!canEdit() || !findPiece(getPlan(), target.id, target.building)) return;
      delegate?.cancel?.(); setTool('select'); select(target);
      // Selection inside a different focused room first backs out. An explicit
      // menu action must still reach the chosen target on this same action.
      if (roomSelection.current().id !== target.id || roomSelection.current().building !== (target.building ?? null)) {
        roomSelection.clear(); select(target);
      }
      onInteract?.(); return run();
    } });
    const result = [...materialActions, action('Select', () => {})];
    if (record.kind === 'wall') {
      result.push(action('Split wall here', () => splitAt({ building: target.building, wall: target.id }, target, target)));
      for (const kind of ['door', 'window']) result.push(action(`Add ${kind} here`, () => {
        const spot = wallPoint({ building: target.building, wall: target.id }, target, target);
        if (!spot) return;
        if (spot.length < 3) { window.showGlobalAlert(`That wall is too short for a 3 foot ${kind}.`); return; }
        return cards.queue(() => canEdit() && op({ op: 'add_opening', building: target.building, wall: target.id, kind, width: 3,
          at: spot.length < 4 ? spot.length / 2 : Math.max(2, Math.min(spot.length - 2, spot.at)) }));
      }));
    } else if (record.kind === 'room') result.push(action('Split room', () => el('rail-split-room').click()));
    else if (!record.building && (isObject(record) || siteShapeKinds.includes(record.kind))) {
      for (const [label, name] of [['Move', 'move'], ['Turn', 'rotate'], ['Scale', 'scale']]) result.push(action(label, () => setTool(name)));
      // Shapes have no mirror operation. Only objects expose the existing mirror fields.
      if (isObject(record)) for (const [label, field] of [['Mirror left-right', 'mirror_x'], ['Mirror front-back', 'mirror_y']])
        result.push(action(label, () => cards.queue(() => {
          const latest = findPiece(getPlan(), target.id, target.building);
          return canEdit() && latest && op(objectOperation(latest, { [field]: !latest.piece[field] }));
        })));
    }
    if (['wall', 'room', 'opening', 'item', 'anchor'].includes(record.kind) || !record.building)
      result.push(action('Delete', () => cards.remove()));
    return [...result, ...visibilityActions(target.id, record.piece.device ? 'device' : record.piece.object_kind === 'lamp' ? 'fixture' : record.kind)];
  }
  function clipboardActions(target) {
    if (target.floor) return [];
    const members = selectionStore.members(), ref = toSelectionRef(target);
    const refs = ref && !members.some(r => r.pieceId === ref.pieceId && r.buildingId === ref.buildingId) ? [ref] : members;
    const surface = target.slotSurface || target.materialSurface || target;
    let slot = null;
    try { slot = clipboard.slotFor(surface); } catch (error) { materialWarning(error); }
    if (target.slotSurface) return [
      { label: 'Copy material', disabled: !slot, run: () => clipboard.copyMaterial(surface) },
      { label: 'Paste material', disabled: !slot || !clipboard.hasMaterial() || !canEdit(), reason: 'Copy a material first.', run: () => clipboard.pasteMaterial(surface) }];
    const eligible = clipboard.canCopy(refs), landing = { ...target, ...(!target.materialSurface && target.point ? {
      point: contextPoint(getPlan(), getPlan()?.buildings?.find(b => b.id === (target.building || target.buildingId)), target.point)
    } : {}), ...(target.materialSurface || {}) };
    const readiness = clipboard.canPaste(target.empty ? { kind: 'ground' } : landing);
    return [
      { label: 'Copy', disabled: !eligible.ok, reason: eligible.reason, run: () => clipboard.copy(refs) },
      { label: 'Cut', disabled: !eligible.ok || !canEdit(), reason: eligible.reason, run: () => clipboard.cut(refs) },
      { label: 'Paste', disabled: !readiness.ok, reason: readiness.reason, run: () => clipboard.paste(target.empty
        ? { mode: 1, target: { kind: 'ground' }, point: groundPoint?.(target) }
        : { mode: target.clientX === undefined ? 2 : 1, target: landing, point: target.materialSurface?.point }) },
      { label: 'Duplicate', disabled: !eligible.ok || !canEdit(), reason: eligible.reason, run: () => clipboard.duplicate(refs) },
      ...(!target.empty ? [moveToAction({ refs, getPlan, getLabel, applyBatch, selectionStore, canEdit, chooseDestination, queue: cards.queue })].filter(Boolean) : []),
      ...(slot ? [{ label: 'Copy material', run: () => clipboard.copyMaterial(surface) },
        { label: 'Paste material', disabled: !clipboard.hasMaterial() || !canEdit(), reason: 'Copy a material first.', run: () => clipboard.pasteMaterial(surface) }] : [])];
  }
  const contextMenu = createContextMenu({ signal, items: target => [...clipboardActions(target), ...sceneContextItems(target)] });
  function visibilityActions(id, kind) {
    if (!visibility || !id) return [];
    const refs = selectionStore.members(), members = refs.length > 1 && refs.some(r => r.pieceId === id) ? refs : null;
    return [{ label: visibility.isHidden(id, kind) ? 'Show' : 'Hide', run: () => {
      if (members) { visibility.setMembers(members, { hidden: !visibility.isHidden(id, kind) }); return; }
      if (visibility.isHidden(id, kind)) { visibility.show(id); visibility.showKind(kind); } else visibility.hide(id);
    } }, { label: visibility.isLocked(id, kind) ? 'Unlock' : 'Lock', run: () => {
      if (members) { visibility.setMembers(members, { locked: !visibility.isLocked(id, kind) }); return; }
      if (visibility.isLocked(id, kind)) { visibility.unlock(id); visibility.unlockKind(kind); } else visibility.lock(id);
    } }];
  }
  async function removeSelected() {
    if (!canEdit()) return;
    const refs = selectionStore.members();
    if (refs.length < 2) return cards.remove();
    if (!await window.promptConfirm(`Delete ${refs.length} selected pieces?`, 'Attached doors or windows may also be removed. Undo restores the whole selection.', 'Delete', 'Cancel')) return;
    return cards.queue(async () => {
      if (!canEdit()) return;
      await applyBatch(deleteOperations(getPlan(), refs, getModel?.()));
      selectionStore.clear();
    });
  }
  listen(canvas, 'contextmenu', event => {
    event.preventDefault();
    if (ownsGesture) return;
    contextPicking = true;
    let target; try { target = picker.at(event.clientX, event.clientY)[0]; } finally { contextPicking = false; }
    let materialSurface = null;
    try { materialSurface = target && surfaceAt?.(event, target); } catch (error) { materialWarning(error); materialSurface = false; }
    contextMenu.open(event, target ? { ...target, materialSurface, clientX: event.clientX, clientY: event.clientY } : { empty: true, clientX: event.clientX, clientY: event.clientY });
  });
  // Each source exposes hit(event) and begin(event, handle); its existing
  // pointerMove/pointerUp methods keep ownership through release or cancel.
  function handleHit(event) {
    const sources = selectionStore.members().length > 1 ? [gizmo] : [gizmo, handles, ...(delegate?.handleSources || [])];
    for (const source of new Set(sources)) {
      const handle = source?.hit?.(event);
      if (handle) return { source, handle };
    }
    return null;
  }
  function setTool(name) {
    measure.disarm();
    cancelSplit();
    if (name !== 'select') haLink.cancelPlacement();
    tool = name; onInteract?.();
    for (const id of ['select', 'move', 'rotate', 'scale', 'measure', 'draw-room', 'draw-wall', 'split-room', 'add-door', 'add-window', 'add-anchor', 'add-stair', 'add-solar-zone', 'add-meter', 'add-electric-panel', 'add-charger', 'add-parking']) el(`rail-${id}`)?.setAttribute('aria-pressed', String(id === name));
    handles.refresh(); gizmo.draw();
    for (const source of delegate?.handleSources || []) source.draw?.();
    canvas.style.cursor = name === 'move' ? 'grab' : name === 'select' ? '' : 'crosshair';
    if (name === 'measure') measure.arm();
  }
  async function sheet(key = floor()?.key, show = !sheetOn) {
    const target = levels().find(l => l.key === key); if (!target) return;
    sheetOn = show; el('rail-sheet').setAttribute('aria-pressed', String(show));
    el('layer-sheet')?.setAttribute('aria-pressed', String(show));
    if (!show) { view.setSheet(null); return; }
    const sheets = getSheets();
    const registration = sheets.registrations?.find(row => row.level === target.level.id && sheets.page_roles.some(role =>
      role.source === row.source && role.page === row.page && (role.building || 'house') === target.building.id));
    if (!registration) {
      sheetOn = false; el('rail-sheet').setAttribute('aria-pressed', 'false');
      el('layer-sheet')?.setAttribute('aria-pressed', 'false');
      panel.message('This floor does not have a lined-up drawing yet. Check its outline with Argyle first.'); return;
    }
    let url = (window.chfBase ?? '../') + `api/house/editor/sheets/${encodeURIComponent(registration.source)}/${registration.page}.png`;
    if (window.chfAuthUrl) url = window.chfAuthUrl(url);
    view.setSheet({ url, buildingId: target.building.id, levelId: target.level.id, reg: registration.reg,
      masterSize: sheetMaster(sheets, registration.source, registration.page) });
  }
  function chooseFloor(key) {
    measure.disarm();
    levelKey = key; onInteract?.(); view.setView(key); view.showLevels([key]);
    roomSelection.clear();
    const target = levels().find(row => row.key === key);
    if (target) select({ pieceId: target.level.id, buildingId: target.building.id });
    if (sheetOn) sheet(key, true).catch(report);
    delegate?.floorChanged?.(); drawFloors();
  }
  async function chooseDestination(key) {
    delegate?.cancel?.(); setTool('select');
    if (key !== 'site') { chooseFloor(key); return; }
    measure.disarm(); onInteract?.(); roomSelection.clear();
    view.setView('ext'); view.showLevels(null);
    await view.setEditableLevel(null); drawFloors();
  }
  function drawFloorList(host, actionsOnly = false) {
    const focused = document.activeElement?.dataset.floor;
    const signature = JSON.stringify(levels().map(row => [row.key, row.label]));
    if (host.dataset.levels !== signature) {
      host.dataset.levels = signature; host.replaceChildren();
      const title = document.createElement('span'); title.textContent = 'Floors'; host.append(title);
      for (const row of actionsOnly ? [] : levels().reverse()) {
        const group = document.createElement('div'); group.className = 'editor-floor-row';
        const button = document.createElement('button'); button.type = 'button'; button.dataset.floor = row.key;
        button.textContent = row.label; button.addEventListener('click', () => chooseFloor(row.key));
        const toggle = document.createElement('button'); toggle.type = 'button'; toggle.dataset.floorVisible = row.key;
        const eye = icon('eye'); eye.setAttribute('width', '20'); eye.setAttribute('height', '20'); toggle.append(eye);
        toggle.setAttribute('aria-label', `Show ${row.label}`);
        toggle.addEventListener('click', () => {
          onInteract?.();
          toggle.setAttribute('aria-pressed', String(toggle.getAttribute('aria-pressed') !== 'true'));
          const keys = [...host.querySelectorAll('[data-floor-visible][aria-pressed="true"]')].map(node => node.dataset.floorVisible);
          view.showLevels(keys); drawFloors();
        });
        group.append(toggle, button); host.append(group);
        group.addEventListener('contextmenu', event => { event.preventDefault(); contextMenu.open(event, { floor: row.key }); }, { signal });
        if (focused === row.key) button.focus({ preventScroll: true });
      }
      const all = document.createElement('button'); all.type = 'button'; all.textContent = 'All floors';
      all.addEventListener('click', () => {
        onInteract?.();
        if (!['roof', 'dormer'].includes(roomSelection.current().kind)) roomSelection.clear();
        view.setView('ext'); view.showLevels(null);
        view.setEditableLevel(null).catch(report); drawFloors();
      }); host.append(all);
      for (const kind of ['Floor', 'Building']) {
        const details = document.createElement('button'); details.type = 'button'; details.textContent = kind === 'Floor' ? 'Change this floor' : 'Change the house';
        details.addEventListener('click', () => {
          const target = floor(); if (!target) return;
          onInteract?.(); select({ pieceId: kind === 'Floor' ? target.level.id : target.building.id, buildingId: target.building.id });
        }); host.append(details);
      }
      if (!levels().length) { const note = document.createElement('p'); note.textContent = 'No floors yet'; host.append(note); }
    }
    host.querySelectorAll('[data-floor]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.floor === floor()?.key)));
    host.querySelectorAll('[data-floor-visible]').forEach(node => node.setAttribute('aria-pressed', String(!!view.groups?.levels[node.dataset.floorVisible]?.visible)));
  }
  function drawFloors() {
    if (dock && sceneTree) { drawFloorList(el('scene-floor-actions'), true); sceneTree.refresh(); }
    else if (el('editor-floors')) drawFloorList(el('editor-floors'));
    if (el('editor-floor-picker')) drawFloorList(el('editor-floor-picker'));
    if (el('editor-floor-add')) el('editor-floor-add').disabled = !floor() || !canEdit();
  }
  function selectTreeRow(row, options = null) {
    onInteract?.();
    if (options?.mode === 'toggle') {
      if (row.floorKey || isExcludedSetKind(row.kind) || isExcludedSetKind(options.ref?.kind)) return;
      setTool('select');
      const ref = toSelectionRef(options.ref || row);
      if (ref && !isExcludedSetKind(ref.kind)) {
        seedDelegateSelection();
        selectionStore.toggle(ref);
      }
      return;
    }
    if (options?.mode === 'range') {
      const refs = (options.refs || [])
        .filter(r => !r?.floorKey && !isExcludedSetKind(r?.kind))
        .map(r => toSelectionRef(r) || r)
        .filter(ref => ref && !isExcludedSetKind(ref.kind));
      if (!refs.length) return;
      setTool('select');
      if (options.additive) {
        seedDelegateSelection();
        selectionStore.set([...selectionStore.members(), ...refs]);
      } else {
        delegate?.cancel?.();
        selectionStore.set(refs);
      }
      return;
    }
    delegate?.cancel?.(); setTool('select');
    if (row.floorKey) chooseFloor(row.floorKey);
    else if (!delegate?.selectTree?.(row) && !delegate?.selectPick?.({ ...row, fixtureId: row.id, entity_id: row.piece?.entity_id, effectId: row.kind === 'effect_fixture' ? row.id : undefined })) {
      // Explicit tree picks must cross an existing focused-room boundary.
      roomSelection.clear(); select(row);
    }
  }
  if (dock && visibility) {
    sceneTree = createSceneTree({ host: el('scene-tree'), getPlan,
      getSelection: () => selection || delegate?.visibilitySelection?.(), selection: selectionStore, select: selectTreeRow, visibility,
      floors: { hidden: row => view.groups?.levels[row.floorKey]?.visible === false, current: () => floor()?.key,
        toggle(row) {
          const show = view.groups?.levels[row.floorKey]?.visible === false || visibility.isHidden(row.id);
          if (show) visibility.show(row.id);
          view.showLevels(levels().filter(r => r.key === row.floorKey ? show : view.groups?.levels[r.key]?.visible !== false).map(r => r.key)); drawFloors();
        } },
      contextMenu: (event, row) => contextMenu.open(event, row.floorKey ? { floor: row.floorKey } : row) });
    const layers = createLayers({ host: el('layer-kinds'), visibility });
    const offResize = dock.onResize?.(() => sceneTree.refresh());
    const offShow = dock.onShow?.(tab => { if (tab === 'scene') sceneTree.refresh(); });
    signal.addEventListener('abort', () => { sceneTree.dispose(); layers.dispose(); offResize?.(); offShow?.(); }, { once: true });
  }
  function pieceAnchor(item) {
    const record = findPiece(getPlan(), item.pieceId, item.buildingId); if (!record) return null;
    const { piece, building, kind } = record;
    const level = piece.level || building.walls.find(w => w.id === piece.wall)?.level || building.levels[0]?.id;
    const points = piece.from ? [piece.from, piece.to] : piece.polygon || piece.rect && [[piece.rect[0], piece.rect[1]], [piece.rect[2], piece.rect[3]]];
    const wall = kind === 'opening' && building.walls.find(w => w.id === piece.wall);
    const length = wall && Math.hypot(wall.to[0] - wall.from[0], wall.to[1] - wall.from[1]);
    const point = wall && length ? wall.from.map((v, i) => v + (wall.to[i] - v) * piece.at / length)
      : piece.from || (points?.length ? [0, 1].map(axis => points.reduce((n, p) => n + p[axis], 0) / points.length) : piece.position || [0, 0]);
    return { point, key: `${building.id}:${level}`, record };
  }
  async function move(item, from, to) {
    if (!canEdit() || !from || !to) return;
    const anchor = pieceAnchor(item); if (!anchor) return;
    const walls = anchor.record.building.walls.filter(w => w.level === anchor.key.slice(item.buildingId.length + 1) && w.id !== item.pieceId);
    const by = [to[0] - from[0], to[1] - from[1]];
    const { kind, piece, building } = anchor.record;
    if (hasHandles(anchor.record)) return;
    let destination = anchor.point.map((v, i) => v + by[i]);
    if (kind === 'opening') {
      const wall = building.walls.find(w => w.id === piece.wall); if (!wall) return;
      const d = wall.to.map((v, i) => v - wall.from[i]), length = Math.hypot(...d);
      const at = Math.max(piece.width / 2, Math.min(length - piece.width / 2, destination.reduce((n, v, i) => n + (v - wall.from[i]) * d[i] / length, 0)));
      destination = wall.from.map((v, i) => v + d[i] * at / length);
    } else destination = snapPoint(destination, walls, { exclude: kind === 'wall' ? [piece.from, piece.to] : [] });
    const delta = destination.map((v, i) => v - anchor.point[i]);
    if (Math.hypot(...delta) < .001) return;
    await edit({ op: 'move', piece: item.pieceId, building: item.buildingId, by: delta }); cards.draw(selection);
  }
  async function rotate(buildingId, delta) {
    if (!canEdit()) return;
    const building = getPlan()?.buildings.find(b => b.id === buildingId); if (!building) return;
    const to = snapRotation((building.rotation || 0) + delta);
    if (Math.abs(to - (building.rotation || 0)) < .001) return;
    await edit({ op: 'rotate', building: buildingId, to, about: localCentre(building) }); cards.draw(selection);
  }
  async function dragPiece(pieceId, buildingId, dx, dy) {
    const item = { pieceId, buildingId }; select(item);
    const anchor = pieceAnchor(item); if (!anchor) return;
    if (hasHandles(anchor.record)) return;
    const p = view.screenOfFloor(...anchor.point, anchor.key); if (!p) return;
    await move(item, view.floorAt(...p, anchor.key), view.floorAt(p[0] + dx, p[1] + dy, anchor.key));
  }
  // Capture before OrbitControls so a floor drag never turns into a camera drag.
  listen(canvas, 'pointerdown', event => {
    // Alt-drag belongs to the camera even over handles. Defer the existing
    // corner-removal shortcut until release proves this was only an Alt-click.
    if (view.editorCamera && event.pointerType !== 'touch' && event.button === 0 && event.altKey) {
      if (pointerId === null && canEdit()) {
        const hit = handleHit(event), h = hit?.handle;
        if (h?.kind === 'site_vertex' || h && !h.kind && !h.insert && Number.isInteger(h.index)) {
          pointers.add(event.pointerId); pointerId = event.pointerId;
          gesture = { altOrbit: true, hit, press: event, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
        }
      }
      return;
    }
    pointers.add(event.pointerId);
    if (pointerId !== null) {
      if (ownsGesture) event.stopImmediatePropagation();
      else { gesture = null; pointerId = null; } // A pinch cancels the passive tap.
      return;
    }
    if (pointers.size > 1) return;
    if (event.button !== 0) return;
    controlsBeforePress = view.controls.enabled;
    if (!canEdit()) {
      if (delegate?.pointerBrowse?.(event)) {
        pointerId = event.pointerId; ownsGesture = !view.controls.enabled;
        if (ownsGesture) event.stopImmediatePropagation();
      }
      return;
    }
    pointerId = event.pointerId;
    if (measure.active()) {
      gesture = { measuring: true, selecting: true, x: event.clientX, y: event.clientY, pointerId }; return;
    }
    if (delegate?.pointerArmedDown?.(event)) { ownsGesture = true; event.stopImmediatePropagation(); return; }
    const hit = (event.ctrlKey || event.metaKey) ? null : handleHit(event);
    if (hit) {
      const enabled = view.controls.enabled, started = hit.source.begin(event, hit.handle);
      gesture = { x: event.clientX, y: event.clientY, pointerId, dragging: true, source: hit.source, started, enabled };
      ownsGesture = true; onInteract?.(); view.controls.enabled = false;
      canvas.setPointerCapture(event.pointerId); event.stopImmediatePropagation(); return;
    }
    let body = null;
    if (['move', 'rotate', ...(selectionStore.members().length > 1 ? ['scale'] : [])].includes(tool)) {
      const current = roomSelection.current();
      let picked = picker.at(event.clientX, event.clientY)[0];
      if (picked?.building && view.state.view === 'ext' && current.kind === 'building')
        picked = { ...picked, id: picked.building, kind: 'building' };
      if (!(event.ctrlKey || event.metaKey) && selectionStore.members().length > 1 && picked && selectionStore.members().some(ref => ref.pieceId === picked.id && (ref.buildingId ?? null) === (picked.building ?? null))) {
        const handle = { kind: tool === 'move' ? 'gizmo_move_free' : tool === 'rotate' ? 'gizmo_turn' : 'gizmo_scale' };
        const started = gizmo.begin(event, handle);
        gesture = { x: event.clientX, y: event.clientY, pointerId, dragging: true, source: gizmo, started, enabled: controlsBeforePress };
        ownsGesture = true; onInteract?.(); view.controls.enabled = false;
        canvas.setPointerCapture(event.pointerId); event.stopImmediatePropagation(); return;
      }
      // Check the nearest shared pick before a body delegate can claim a
      // building through a yard item, or select and move in one press.
      if (!current.id || !picked || picked.id !== current.id || picked.building !== current.building || picked.kind !== current.kind) {
        gesture = { x: event.clientX, y: event.clientY, pointerId, selecting: true }; return;
      }
      body = { ...picked, pieceId: picked.id, buildingId: picked.building };
    }
    if (selectionStore.members().length < 2 && delegate?.pointerDown?.(event)) {
      gesture = { delegated: true, enabled: controlsBeforePress };
      ownsGesture = true; event.stopImmediatePropagation(); return;
    }
    if (event.shiftKey && tool === 'select') {
      gesture = { x: event.clientX, y: event.clientY, pointerId, selecting: true, addRoom: true }; return;
    }
    if (tool === 'select' && !body && event.pointerType !== 'touch' && marquee.pointerDown(event)) {
      gesture = { x: event.clientX, y: event.clientY, pointerId, marquee: true, enabled: controlsBeforePress };
      ownsGesture = true; event.stopImmediatePropagation(); return;
    }
    // A passive piece press still clicks/selects. In the editor a mouse drag
    // starts a marquee at the threshold point; touch keeps its camera path.
    gesture = { x: event.clientX, y: event.clientY, pointerId, selecting: true, enabled: controlsBeforePress };
    if (!body?.building) return;
    onInteract?.();
    const anchor = pieceAnchor(body); if (!anchor) return;
    if (hasHandles(anchor.record)) return;
    const start = view.floorAt(event.clientX, event.clientY, anchor.key); if (!start) return;
    const centre = localCentre(anchor.record.building);
    gesture = { item: body, start, key: anchor.key, centre, pointerId, x: event.clientX, y: event.clientY, enabled: view.controls.enabled };
    ownsGesture = true;
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); event.stopImmediatePropagation();
  }, { capture: true });
  listen(canvas, 'pointermove', event => {
    if (!pointers.size && !event.buttons && tool === 'select' && canEdit()) roomSelection.hover(pick(event.clientX, event.clientY));
    if (event.pointerId !== pointerId) return;
    if (gesture?.altOrbit) {
      gesture.moved ||= Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) >= DRAG_THRESHOLD_PX;
      return;
    }
    if (gesture?.marquee) { marquee.pointerMove(event); return; }
    if (gesture?.dragging && gesture.source !== handles) {
      if (gesture.started) gesture.source.pointerMove?.(event, { free: !!event.shiftKey });
      return;
    }
    if (gesture?.dragging && !gesture.started) return;
    if (!gesture?.dragging && delegate?.pointerMove?.(event)) return;
    if (!gesture || gesture.delegated) return;
    if (gesture.selecting) {
      if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) >= DRAG_THRESHOLD_PX) {
        gesture.moved = true;
        if (view.editorCamera && event.pointerType !== 'touch' && !gesture.measuring && !gesture.addRoom
          && marquee.pointerDown(event, { fromPiece: true })) {
          gesture.enabled = controlsBeforePress;
          gesture.marquee = true; ownsGesture = true; event.stopImmediatePropagation();
        }
      }
      return;
    }
    if (gesture.dragging) {
      if (gesture.moved || Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) >= DRAG_THRESHOLD_PX) {
        gesture.moved = true;
        try { handles.update(event, { free: !!event.shiftKey }); } catch (error) { finish(event, true); report(error); }
      }
      return;
    }
    if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) < DRAG_THRESHOLD_PX) return;
    const end = view.floorAt(event.clientX, event.clientY, gesture.key); if (!end) return;
    const hint = el('editor-drag-hint'); hint.hidden = false; hint.style.left = `${event.clientX + 18}px`; hint.style.top = `${event.clientY + 18}px`;
    hint.textContent = tool === 'move' ? `${feetInches(Math.hypot(end[0] - gesture.start[0], end[1] - gesture.start[1]))} along the floor` : `${Math.round(turn(gesture, end))}°`;
    const record = findPiece(getPlan(), gesture.item.pieceId, gesture.item.buildingId);
    const piece = record?.piece;
    let outline = piece?.polygon || (piece?.from ? [piece.from, piece.to] : null);
    if (piece?.rect) { const [x0, y0, x1, y1] = piece.rect; outline = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]; }
    if (tool === 'rotate') outline = record?.building.levels[0]?.outline || record?.building.walls.flatMap(w => [w.from, w.to]);
    if (outline) {
      const angle = (snapRotation((record.building.rotation || 0) + turn(gesture, end)) - (record.building.rotation || 0)) * Math.PI / 180;
      const points = outline.map(point => {
        if (tool === 'move') return point.map((v, i) => v + end[i] - gesture.start[i]);
        const x = point[0] - gesture.centre[0], y = point[1] - gesture.centre[1];
        return [gesture.centre[0] + Math.cos(angle) * x - Math.sin(angle) * y, gesture.centre[1] + Math.sin(angle) * x + Math.cos(angle) * y];
      }).map(p => view.screenOfFloor(...p, gesture.key)).filter(Boolean);
      el('editor-drag-outline').setAttribute('points', points.map(p => p.join(',')).join(' '));
    }
  });
  function turn(g, end) {
    let delta = (Math.atan2(end[1] - g.centre[1], end[0] - g.centre[0]) - Math.atan2(g.start[1] - g.centre[1], g.start[0] - g.centre[0])) * 180 / Math.PI;
    delta = (delta + 540) % 360 - 180; return delta;
  }
  const finish = (event, cancel = false, typedOwner = null) => {
    const tracked = pointers.delete(event.pointerId);
    if (event.pointerId !== pointerId) { if (ownsGesture && tracked) event.stopImmediatePropagation(); return; }
    const owned = ownsGesture, g = gesture;
    pointerId = null; ownsGesture = false; gesture = null;
    el('editor-drag-hint').hidden = true;
    el('editor-drag-outline').setAttribute('points', '');
    if (g?.altOrbit) {
      if (cancel || g.moved || Math.hypot(event.clientX - g.x, event.clientY - g.y) >= DRAG_THRESHOLD_PX || !canEdit()) return;
      const enabled = view.controls.enabled;
      try {
        if (g.hit.source.begin(g.press, g.hit.handle)) {
          if (g.hit.source === handles) handles.finish(false, true).catch(report);
          else g.hit.source.pointerUp?.(event, false);
        }
      } finally {
        view.controls.enabled = enabled;
        if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      }
      return;
    }
    if (typedOwner) {
      view.controls.enabled = g?.enabled ?? controlsBeforePress;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      Promise.resolve(typedOwner.commit(typedOwner.typedValue())).catch(report); return;
    }
    if (g?.marquee) {
      if (cancel) marquee.cancel();
      else {
        const dragged = marquee.pointerUp(event);
        if (dragged) onInteract?.();
        else if (!(event.ctrlKey || event.metaKey || event.altKey)) {
          onInteract?.();
          roofRooms.clear();
          lockedHint(event.clientX, event.clientY, null);
          if (!delegate?.selectPick?.(null)) stepBackOrClear();
          else sceneTree?.reveal(delegate?.visibilitySelection?.()?.id);
        }
      }
      view.controls.enabled = g.enabled;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      return;
    }
    if (!g?.dragging) {
      const handled = delegate?.pointerUp?.(event, cancel);
      if (owned) {
        view.controls.enabled = controlsBeforePress;
        if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      }
      if (handled || !g || g.delegated) return;
    }
    if (g.dragging) {
      if (g.source !== handles && g.started) g.source.pointerUp?.(event, cancel);
      view.controls.enabled = g.enabled;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      if (g.source === handles && g.started) handles.finish(cancel || !g.moved, !cancel && !g.moved).catch(report);
      return;
    }
    if (g.selecting) {
      if (g.measuring) return;
      if (!cancel && !g.moved && Math.hypot(event.clientX - g.x, event.clientY - g.y) < DRAG_THRESHOLD_PX) {
        onInteract?.();
        if (g.addRoom) {
          const target = floor(), p = target && view.floorAt(event.clientX, event.clientY, target.key);
          const room = p && target.building.rooms.find(r => r.level === target.level.id && r.state !== 'ghost' && contains(r.polygon, p));
          if (room) {
            if (roofRoomBuilding !== target.building.id || !roofRooms.size) roomSelection.focusRoom(room.id, target.building.id);
            roofRooms.add(room.id); roofRoomBuilding = target.building.id;
          }
        } else if (event.ctrlKey || event.metaKey) {
          roofRooms.clear();
          contextPicking = true;
          let picked;
          try { picked = picker.at(event.clientX, event.clientY)[0] || null; }
          finally { contextPicking = false; }
          picker.reset();
          lockedHint(event.clientX, event.clientY, picked);
          if (picked) {
            seedDelegateSelection();
            const ref = toSelectionRef(picked);
            if (ref && !isExcludedSetKind(ref.kind)) selectionStore.toggle(ref);
          }
        } else {
          roofRooms.clear();
          const picked = picker.click(event.clientX, event.clientY);
          lockedHint(event.clientX, event.clientY, picked);
          if (!picked) {
            if (!delegate?.selectPick?.(null)) stepBackOrClear();
            else sceneTree?.reveal(delegate?.visibilitySelection?.()?.id);
          } else if (!delegate?.selectPick?.(picked)) roomSelection.select(picked);
          else sceneTree?.reveal(delegate?.visibilitySelection?.()?.id);
        }
      }
      return;
    }
    view.controls.enabled = g.enabled;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (cancel || Math.hypot(event.clientX - g.x, event.clientY - g.y) < DRAG_THRESHOLD_PX) return;
    const end = view.floorAt(event.clientX, event.clientY, g.key);
    if (end) (tool === 'rotate' ? rotate(g.item.buildingId, turn(g, end)) : move(g.item, g.start, end)).catch(report);
  };
  listen(canvas, 'pointerup', finish);
  listen(canvas, 'pointercancel', event => finish(event, true));
  listen(window, 'pointerup', finish, { capture: true });
  listen(window, 'pointercancel', event => finish(event, true), { capture: true });
  listen(document, 'pointerup', finish, { capture: true });
  listen(document, 'pointercancel', event => finish(event, true), { capture: true });
  listen(canvas, 'lostpointercapture', event => finish(event, true));
  listen(canvas, 'pointerleave', () => { if (!pointers.size) roomSelection.hover(null); });
  listen(canvas.parentElement, 'twinerror', event => report(event.detail));
  listen(document, 'keydown', event => {
    clipboardKey(event, clipboard, { canEdit: canEdit(), dialogOpen: ownsGesture || dialogOpen() });
  });
  listen(document, 'keydown', event => {
    if (event.defaultPrevented || !canEdit() || event.ctrlKey || event.metaKey || event.altKey
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || dialogOpen()) return;
    if (visibility && event.key.toLowerCase() === 'h') {
      if (ownsGesture || event.target.isContentEditable) return;
      const selected = delegate?.visibilitySelection?.() || selection;
      if (event.shiftKey) { event.preventDefault(); visibility.showAll(); }
      else if (selectionStore.members().length > 1) { event.preventDefault(); visibility.setMembers(selectionStore.members(), { hidden: true }); }
      else if (selected) { event.preventDefault(); visibility.hide(selected.pieceId ?? selected.id); }
      return;
    }
    if (selectionStore.members().length > 1) {
      if (event.key === 'Delete') { event.preventDefault(); removeSelected().catch(report); return; }
      const key = event.key.toLowerCase(), arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
      const action = arrows[event.key] ? 'move' : key === 'r' ? 'rotate' : ['[', ']'].includes(key) ? 'scale' : null;
      if (!action) return;
      event.preventDefault();
      cards.queue(() => {
        if (!canEdit()) return;
        const group = groupTransform(getPlan(), selectionStore.members(), action, { boxes: view.selectionWorldBounds?.() || [], isPickable });
        if (group) return applyBatch(transformOperations(group, arrows[event.key] ? { by: arrows[event.key] }
          : action === 'rotate' ? { angle: event.shiftKey ? -15 : 15 } : { factor: key === '[' ? 1 / 1.1 : 1.1 }));
      }).catch(report); return;
    }
    const record = selection && findPiece(getPlan(), selection.pieceId, selection.buildingId);
    if (!record || !isObject(record) && record.kind !== 'opening' && record.building) return;
    if (event.key === 'Delete') { event.preventDefault(); cards.remove().catch(report); return; }
    if (!record.building && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      const by = [{ ArrowLeft: -1, ArrowRight: 1 }[event.key] || 0, { ArrowDown: -1, ArrowUp: 1 }[event.key] || 0];
      cards.queue(() => canEdit() && op(record.poolId
        ? shapeOperation(record, transformShape(record.piece, { centre: shapeCentre(record.piece).map((v, i) => v + by[i]) }))
        : { op: 'move_site_item', list: record.kind, index: record.index, by })).catch(report); return;
    }
    if (!isObject(record)) return;
    const key = event.key.toLowerCase();
    if (!['r', '[', ']'].includes(key)) return;
    event.preventDefault();
    const target = { id: record.piece.id, building: record.building?.id };
    cards.queue(() => {
      if (!canEdit()) return;
      const current = findPiece(getPlan(), target.id, target.building);
      if (!current) return;
      return op(objectOperation(current, transformObject(current.piece, key === 'r' ? 'rotate' : 'scale', key === 'r' ? event.shiftKey : key === '[')));
    }).catch(report);
  });
  const canEscape = event => event.key === 'Escape' && !event.defaultPrevented
    && !event.target.closest?.('input, textarea, select, [contenteditable="true"]')
    && !dialogOpen();
  // Cancel the owner before a card's capture listener can close it or change
  // selection. Idle Escape stays in bubble, after the card's own close action.
  listen(document, 'keydown', event => {
    if (document.querySelector('#editor-dialog:not([hidden]), #editor-context-menu:not([hidden])')) return;
    if (measure.active() && canEscape(event)) {
      setTool('select'); event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    if (split && event.key === 'Escape' && !event.defaultPrevented) {
      cancelSplit(); event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    if (gesture?.altOrbit && canEscape(event)) {
      gesture.moved = true; event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    if ((marquee.active() || gesture?.marquee) && canEscape(event)) {
      const g = gesture, pid = pointerId;
      marquee.cancel();
      gesture = null; pointerId = null; ownsGesture = false;
      if (g) view.controls.enabled = g.enabled;
      if (pid !== null && canvas.hasPointerCapture(pid)) canvas.releasePointerCapture(pid);
      event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    if (ownsGesture && pointerId !== null && !event.defaultPrevented && (canEdit() || event.key === 'Escape')) {
      for (const source of new Set([gesture?.source, gizmo, handles, ...(delegate?.handleSources || []), delegate])) {
        const result = source?.key?.(event);
        if (!result) continue;
        event.preventDefault(); event.stopImmediatePropagation();
        if (result === 'commit') finish({ pointerId }, false, source);
        else if (result === 'cancel') finish({ pointerId }, true);
        return;
      }
    }
    if (!canEscape(event) || !ownsGesture || pointerId === null) return;
    const armed = !gesture;
    finish({ pointerId }, true);
    // Armed tools still receive Escape to leave their placement/drawing mode.
    // Their press is already cancelled; this same key must not also go back.
    if (armed) { cancelledEscapes.add(event); return; }
    event.preventDefault(); event.stopImmediatePropagation();
  }, { capture: true });
  listen(document, 'keydown', event => {
    if (!canEscape(event) || cancelledEscapes.has(event)) return;
    stepBackOrClear();
  });
  signal.addEventListener('abort', () => { if (gesture && !gesture.selecting) view.controls.enabled = gesture.enabled;
    if (gesture?.dragging && gesture.source !== handles && gesture.started) gesture.source.pointerUp?.({ pointerId }, true);
    if (handles.active()) handles.finish(true).catch(report);
    gesture = null; pointerId = null; ownsGesture = false; pointers.clear(); }, { once: true });
  for (const id of ['select', 'move', 'rotate', 'scale']) {
    el(`rail-${id}`).disabled = false; listen(el(`rail-${id}`), 'click', () => { delegate?.cancel?.(); setTool(id); });
  }
  for (const name of ['copy', 'paste']) if (el(`rail-${name}`)) listen(el(`rail-${name}`), 'click', () => clipboard[name]());
  if (el('rail-measure')) {
    el('rail-measure').disabled = false;
    listen(el('rail-measure'), 'click', () => { if (canEdit()) { delegate?.cancel?.(); setTool('measure'); } });
  }
  el('rail-sheet').disabled = false; listen(el('rail-sheet'), 'click', () => { onInteract?.(); sheet().catch(report); });
  document.querySelectorAll('[data-editor-camera]').forEach(button => listen(button, 'click', () => {
    onInteract?.(); delegate?.cancel?.();
    if (button.dataset.editorCamera === 'top' && floor()) view.setTopCamera(floor().key);
    else view.setCamera(button.dataset.editorCamera);
  }));
  return {
    clipboard,
    visibility,
    visibilityChanged() { picker.reset(); handles.refresh(); gizmo.draw(); drawDimensions(); delegate?.visibilityChanged?.(); },
    revealSelection() { sceneTree?.reveal(delegate?.visibilitySelection?.()?.id || selection?.pieceId); },
    openContextMenu: (event, target) => contextMenu.open(event, target),
    pointerArmedDown,
    haLink,
    deleteSelected: removeSelected,
    applyBatch,
    drawMaterialsList(host, options) { return drawMaterialsList(host, { getPlan, getKit, selectionStore, applyBatch, canEdit, library, queue: cards.queue, loadNames: cards.loadNames, report, view, visibility, ...options }); },
    select, pick, selected: () => selection, selection: roomSelection.current,
    selectionStore, selectedMembers: () => selectionStore.members(),
    dragPiece, rotateBuilding: rotate, floor, chooseFloor, drawFloors, sheet, setTool,
    gizmo, handles: () => [...handles.handles(), ...gizmo.handles()],
    selectedRooms: () => roofRooms.size ? [...roofRooms] : null,
    // A press on the selected piece's handle belongs to the handle, never to a yard item behind it.
    handleAt: event => !!handleHit(event),
    get lastDragFrameMs() { return gizmo.lastDragFrameMs ?? handles.lastDragFrameMs; }, clearDragFrame: () => { handles.clearDragFrame(); gizmo.clearDragFrame(); }, dragging: () => handles.active() || gizmo.active(),
    buildingCentre(id) { const b = getPlan()?.buildings.find(b => b.id === id); return b && rotatePoint(localCentre(b), b.rotation || 0).map((v, i) => v + (b.position?.[i] || 0)); },
    delegate(value) { delegate = value; },
    refresh() {
      refreshClipboardButtons();
      drawFloors();
      const plan = getPlan();
      const currentMembers = selectionStore.members();
      const surviving = currentMembers.filter(ref => pieceExists(plan, ref));
      if (surviving.length !== currentMembers.length) {
        if (!surviving.length) select(null);
        else {
          refreshingSelection = true;
          try { selectionStore.set(surviving); } finally { refreshingSelection = false; }
        }
      } else {
        refreshingSelection = true;
        try { roomSelection.refresh(); } finally { refreshingSelection = false; }
      }
    },
    refreshCard() { cards.draw(selection); },
    // The card's area section redraws once the link answers; the scene never waits on it.
    // The link is read when the house changed, while a room, building or anchor card
    // is open, and otherwise once per idle interval: never on every build poll.
    refreshLink(changed = true) {
      const record = selection && findPiece(getPlan(), selection.pieceId, selection.buildingId);
      const open = ['room', 'building', 'anchor'].includes(record?.kind);
      if (!changed && !open && haLink.state() && Date.now() - linkReadAt < idleInterval) return Promise.resolve(haLink.state());
      linkReadAt = Date.now();
      return haLink.refresh().then(() => { if (!signal?.aborted) cards.draw(selection); }).catch(report);
    },
  };
}
