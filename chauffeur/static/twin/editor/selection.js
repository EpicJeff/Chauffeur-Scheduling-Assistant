import { allPorches } from '../gutter_presence.js';

// Selection store (Ruling 1): ordered list of piece references (last-added = primary()),
// with strict no-op guards and a member-only onChange/subscribe payload.
// Room-focus navigation lives in createRoomSelection (kept compatible with callers
// passing `{ view, getModel }` to createSelection).
import { porchPosts, postRef } from '../porch_posts.js';

function refKey(ref) {
  if (!ref) return null;
  const pieceId = ref.pieceId ?? ref.id ?? null;
  if (!pieceId) return null;
  const buildingId = ref.buildingId ?? ref.building ?? null;
  return JSON.stringify([buildingId, pieceId]);
}

function normalizeRef(ref) {
  if (!ref) return null;
  const pieceId = ref.pieceId ?? ref.id ?? null;
  if (!pieceId) return null;
  const buildingId = ref.buildingId ?? ref.building ?? null;
  const out = { kind: ref.kind ?? null, pieceId };
  if (buildingId !== null && buildingId !== undefined) out.buildingId = buildingId;
  if (ref.level !== undefined && ref.level !== null) out.level = ref.level;
  if (ref.slots !== undefined) out.slots = Array.isArray(ref.slots) ? [...new Set(ref.slots)] : ref.slots;
  if (ref.entity_id !== undefined) out.entity_id = ref.entity_id;
  if (ref.poolId !== undefined) out.poolId = ref.poolId;
  if (ref.porchId !== undefined || ref.parentPieceId !== undefined) out.porchId = ref.porchId ?? ref.parentPieceId;
  return out;
}

function cloneRef(ref) {
  if (!ref) return null;
  const out = { ...ref };
  if (Array.isArray(ref.slots)) out.slots = [...ref.slots];
  return out;
}

function sameSlots(a, b) {
  if (a === b) return true;
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function sameRef(a, b) {
  return refKey(a) === refKey(b) && (a.kind ?? null) === (b.kind ?? null) && sameSlots(a.slots, b.slots);
}

function sameList(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (!sameRef(a[i], b[i])) return false;
  return true;
}

export function createSelection(options = {}) {
  if (options?.view) return createRoomSelection(options);
  const { onChange } = options || {};
  let list = [];
  const listeners = new Set();

  function members() {
    return list.map(cloneRef);
  }

  function primary() {
    return list.length ? cloneRef(list[list.length - 1]) : null;
  }

  function has(ref) {
    const key = refKey(ref);
    return !!key && list.some(item => refKey(item) === key);
  }

  function notify() {
    const snapshot = members();
    onChange?.(snapshot);
    for (const fn of [...listeners]) fn(snapshot);
  }

  function set(refs) {
    const next = [], seen = new Map();
    for (const raw of refs || []) {
      const ref = normalizeRef(raw);
      if (!ref) continue;
      const key = refKey(ref);
      if (seen.has(key)) {
        const existing = seen.get(key);
        if (Array.isArray(ref.slots)) {
          existing.slots = [...new Set([...(existing.slots || []), ...ref.slots])];
        }
      } else {
        seen.set(key, ref);
        next.push(ref);
      }
    }
    if (sameList(list, next)) return;
    list = next;
    notify();
  }

  function add(ref) {
    const norm = normalizeRef(ref);
    if (!norm) return;
    const key = refKey(norm);
    const index = list.findIndex(item => refKey(item) === key);
    if (index !== -1) {
      if (!Array.isArray(norm.slots)) return;
      const existing = list[index];
      const merged = [...new Set([...(existing.slots || []), ...norm.slots])];
      if (sameSlots(existing.slots, merged)) return;
      existing.slots = merged;
      notify();
      return;
    }
    list.push(norm);
    notify();
  }

  function remove(ref) {
    const key = refKey(ref);
    if (!key) return;
    const next = list.filter(item => refKey(item) !== key);
    if (next.length === list.length) return;
    list = next;
    notify();
  }

  function toggle(ref) {
    if (!normalizeRef(ref)) return false;
    if (has(ref)) {
      remove(ref);
      return false;
    }
    add(ref);
    return true;
  }

  function clear() {
    if (!list.length) return;
    list = [];
    notify();
  }

  function kinds() {
    const map = new Map();
    for (const item of list) {
      const k = item.kind ?? null;
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(cloneRef(item));
    }
    return map;
  }

  function narrow(kind) {
    const next = list.filter(item => item.kind === kind);
    if (next.length === list.length) return;
    list = next;
    notify();
  }

  function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  return { members, primary, set, add, remove, toggle, clear, has, kinds, narrow, subscribe };
}

function toViewPick(ref) {
  if (!ref) return null;
  const out = {
    kind: ref.kind ?? null,
    id: ref.pieceId ?? ref.id ?? null,
    pieceId: ref.pieceId ?? ref.id ?? null,
    building: ref.buildingId ?? ref.building ?? null,
    buildingId: ref.buildingId ?? ref.building ?? null,
    level: ref.level ?? null,
  };
  if (ref.entity_id !== undefined) out.entity_id = ref.entity_id;
  if (ref.poolId !== undefined) out.poolId = ref.poolId;
  if (ref.porchId !== undefined || ref.parentPieceId !== undefined) out.porchId = ref.porchId ?? ref.parentPieceId;
  return out;
}

// Room-focus and hover controller for the 3D view.
export function createRoomSelection({ view, getModel, getPlan, onChange, onSync, getMembers } = {}) {
  let selected = null, room = null, hovered = null, ghosted = 0;
  let walls = [], allowed = [];

  const normalize = pick => pick && {
    kind: pick.kind ?? null,
    id: pick.id ?? pick.pieceId ?? null,
    building: pick.building ?? pick.buildingId ?? null,
    level: pick.level ?? null,
    ...(pick.porchId !== undefined || pick.parentPieceId !== undefined ? { porchId: pick.porchId ?? pick.parentPieceId } : {}),
  };
  const building = id => getModel?.()?.buildings?.find(b => b.id === id) || getPlan?.()?.buildings?.find(b => b.id === id);

  function roomContext(pick) {
    const b = building(pick.building);
    if (pick.kind === 'level' && b?.levels?.some(l => l.id === pick.id)) {
      const ids = new Set([pick.id, ...(view?.levelFocusMembers?.(b.id, pick.id) || [])]);
      for (const list of ['walls', 'rooms', 'joints', 'fixtures', 'lights', 'stairs', 'awnings', 'porches', 'solar_zones'])
        for (const p of b[list] || []) if (p.level === pick.id) ids.add(p.id);
      for (const post of porchPosts(b)) if ((b.rooms?.find(r=>r.id===post.porchId)?.level || post.porch.level || b.levels[0]?.id) === pick.id) ids.add(post.id);
      for (const detail of b.porches_detail || []) if ((b.rooms?.find(r=>r.id===detail.id)?.level || detail.level || b.levels[0]?.id) === pick.id)
        for (let i=0;i<(detail.columns || []).length;i++) ids.add(postRef(detail,i));
      for (const list of ['openings', 'anchors', 'items']) for (const p of b[list] || [])
        if (p.level === pick.id || ids.has(p.wall || p.host?.wall || p.host?.floor || p.host?.ceiling)) ids.add(p.id);
      return { kind: 'level', id: pick.id, building: b.id, level: pick.id, walls: [], allowed: [...ids] };
    }
    const r = [...(b?.rooms || []), ...allPorches(b || {})].find(r => r.id === pick.id);
    if (!r) return null;
    const cycle = r.joints || [];
    const pairs = new Set(cycle.map((id, i) => [id, cycle[(i + 1) % cycle.length]].sort().join('\n')));
    const boundary = (b.walls || []).filter(w => w.joints?.length === 2 && pairs.has([...w.joints].sort().join('\n')));
    const ids = new Set([r.id, ...boundary.map(w => w.id)]);
    const belongs = host => host && (ids.has(host.wall) || host.floor === r.id || host.ceiling === r.id);
    for (const collection of ['openings', 'anchors', 'items']) for (const piece of b[collection] || []) {
      if (ids.has(piece.wall) || belongs(piece.host)) ids.add(piece.id);
    }
    const sources = [getModel?.()?.buildings?.find(x => x.id === pick.building), getPlan?.()?.buildings?.find(x => x.id === pick.building)].filter(Boolean);
    for (const src of sources) {
      for (const post of porchPosts(src)) if (post.porchId === r.id) ids.add(post.id);
      for (const detail of src.porches_detail || []) {
        if (detail?.id === r.id) for (let i = 0; i < (detail.columns || []).length; i++) ids.add(postRef(detail, i));
      }
    }
    return {
      kind: pick.kind === 'porch' || !b.rooms?.includes(r) ? 'porch' : 'room', id: r.id, building: b.id, level: r.level || b.levels?.[0]?.id,
      walls: boundary.map(w => w.id), allowed: [...ids],
    };
  }

  const inside = pick => !room || (pick && (pick.buildingId ?? pick.building ?? null) === room.building && (allowed.includes(pick.pieceId ?? pick.id) || allowed.includes(pick.parentPieceId ?? pick.porchId)));
  const clearRoom = () => { room = null; walls = []; allowed = []; };

  function paint() {
    const members = getMembers ? getMembers().map(toViewPick) : selected ? [toViewPick(selected)] : [];
    ghosted = view?.setSelection?.({
      selected: toViewPick(selected),
      members,
      hover: hovered,
      room: room && { ...room, walls, allowed },
    }) || 0;
  }

  function current() {
    return {
      kind: selected?.kind ?? null,
      id: selected?.id ?? null,
      pieceId: selected?.id ?? null,
      building: selected?.building ?? null,
      buildingId: selected?.building ?? null,
      level: selected?.level ?? null,
      room: room?.id ?? null,
      focusKind: room?.kind ?? null,
      ghosted,
      tinted: { floor: room?.id ?? null, walls: [...walls] },
      hover: hovered && { ...hovered },
    };
  }

  function changed(syncMembers = true) {
    if (syncMembers) onSync?.(current());
    paint();
    onChange?.(current());
  }

  function clear() {
    selected = null;
    clearRoom();
    hovered = null;
    changed(true);
  }

  function focusRoom(id, buildingId) {
    const pick = typeof id === 'object' ? normalize(id) : { id, building: buildingId };
    const context = pick && roomContext(pick);
    if (!context) { clear(); return; }
    room = { kind: context.kind, id: context.id, building: context.building, level: context.level };
    walls = context.walls; allowed = context.allowed;
    selected = { ...room };
    hovered = null;
    changed(true);
  }

  function leaveRoom() {
    if (!room) return;
    selected = { ...room }; clearRoom(); hovered = null; changed(true);
  }

  function back() {
    hovered = null;
    if (room && selected?.id !== room.id) { selected = { ...room }; changed(true); }
    else clear();
  }

  function select(value) {
    const pick = normalize(value);
    if (pick && room && pick.kind !== 'proposal' && !inside(pick) && pick.building === room.building) {
      const context = roomContext(room);
      if (context) { walls = context.walls; allowed = context.allowed; }
    }
    if (!pick || pick.kind !== 'proposal' && !inside(pick)) { back(); return; }
    if (['building', 'level', 'proposal'].includes(pick.kind)) clearRoom();
    if (['room', 'porch'].includes(pick.kind) && !pick.level) {
      const b = building(pick.building);
      pick.level = [...(b?.rooms || []), ...allPorches(b || {})].find(r => r.id === pick.id)?.level ?? b?.levels?.[0]?.id ?? null;
    }
    if (pick.kind === 'level') pick.level = pick.id;
    selected = pick;
    hovered = null;
    changed(true);
  }

  function hover(value) {
    const pick = normalize(value), next = pick && inside(pick) ? pick : null;
    if (JSON.stringify(next) === JSON.stringify(hovered)) return;
    hovered = next;
    paint();
  }

  // Sync primary/view state from an external member store update without clearing
  // or mutating room focus on its own (caller decides when to call clearRoom()).
  function sync(primaryRef) {
    selected = primaryRef ? normalize(primaryRef) : null;
    hovered = null;
    paint();
    return current();
  }

  function refresh() {
    if (room) {
      const context = roomContext(room);
      if (!context) { clear(); return; }
      walls = context.walls; allowed = context.allowed;
      if (selected && !inside(selected)) selected = { ...room };
    }
    changed(false);
  }

  return { hover, select, clear, clearRoom, inside, sync, current, focusRoom, leaveRoom, back, refresh };
}
