import { icon } from './icons.js';
import { visibilityKind } from '../twin_visibility.js';
import { contains } from '../twin_generator.js';

const label = (piece, kind) => piece.name || `${kind[0].toUpperCase() + kind.slice(1).replaceAll('_', ' ')} ${piece.id}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];

// One ordered ownership tree. Shared walls get one home (the first adjoining
// room); unassigned pieces remain on their floor, never silently disappear.
export function sceneRows(plan) {
  const rows = [], add = (piece, kind, parent, building = null, name = label(piece, kind), extra = {}) => {
    const row = { id: piece.id, key: JSON.stringify([building, piece.id]), kind, name, parent, building, depth: parent ? parent.depth + 1 : 0, ...extra };
    rows.push(row); return row;
  };
  const fixtures = Object.entries(plan?.light_fixtures || {}).flatMap(([entity_id, fs]) => fs.map(f => ({ ...f, entity_id, sceneKind: 'light_fixture' })))
    .concat((plan?.effect_fixtures || []).map(f => ({ ...f, sceneKind: 'effect_fixture' })));
  const assignedFixtures = new Set();
  for (const b of plan?.buildings || []) {
    const building = add(b, 'building', null, b.id), levels = new Map(), rooms = new Map(), pieces = new Map();
    for (const [i, l] of [...(b.levels || [])].sort((a, c) => a.elevation - c.elevation).entries())
      levels.set(l.id, add(l, 'level', building, b.id, ((plan.buildings.length > 1 ? `${b.name || b.id} · ` : '') + (l.name || `Floor ${i + 1}`)), { floorKey: `${b.id}:${l.id}` }));
    for (const r of b.rooms || []) rooms.set(r.id, add(r, 'room', levels.get(r.level) || building, b.id));
    const wallRoom = w => (b.rooms || []).find(r => r.walls?.includes(w.id) || w.joints?.length === 2 && r.joints?.some((id, i, cycle) =>
      [id, cycle[(i + 1) % cycle.length]].every(j => w.joints.includes(j))));
    const parentFor = p => {
      const host = p.host || {}, wall = (b.walls || []).find(w => w.id === (p.wall || host.wall));
      const anchor = (b.anchors || []).find(a => a.id === host.anchor);
      const opening = (b.openings || []).find(o => o.id === host.opening);
      if (anchor) return pieces.get(anchor.id)?.parent || parentFor({ ...anchor, host: { ...anchor.host, anchor: null } });
      if (opening) return pieces.get(opening.id)?.parent || building;
      const room = rooms.get(host.floor || host.ceiling || p.room) || rooms.get(wall && wallRoom(wall)?.id);
      if (room) return room;
      const point = [p.position, p.at, p.path?.[0]].find(v => Array.isArray(v) && v.length >= 2 && v.every(Number.isFinite));
      const spatial = point && (b.rooms || []).find(r => (!p.level || r.level === p.level) && r.polygon && contains(r.polygon, point));
      return rooms.get(spatial?.id) || levels.get(p.level || wall?.level) || building;
    };
    for (const [collection, kind] of [[b.walls,'wall'],[b.openings,'opening'],[b.items,'item'],
      [(b.anchors || []).filter(p => !p.device),'anchor'],[(b.anchors || []).filter(p => p.device),'anchor'],[b.devices,'device'],[b.fixtures,'fixture'],[b.lights,'light']])
      for (const p of collection || []) pieces.set(p.id, add(p, kind, kind === 'wall' ? rooms.get(wallRoom(p)?.id) || levels.get(p.level) || building : parentFor(p), b.id,
        label(p, kind === 'anchor' && p.device ? 'device' : kind), { visibilityKind: p.device ? 'device' : p.object_kind === 'lamp' ? 'fixture' : visibilityKind(kind), piece: p }));
    const roofs = new Map([...(b.roofs || []), ...(b.roof?.sections || [])].map(p => [p.id, p]));
    for (const [collection, kind] of [[b.stairs,'stair'],[[...roofs.values()],'roof'],[b.dormers,'dormer'],[b.solar_zones,'solar_zone'],[b.porches,'porch']])
      // A porch is also a room of the same id (its floor, walls and openings hang there); list it once.
      for (const p of collection || []) if (!(kind === 'porch' && rooms.has(p.id))) add(p, kind, levels.get(p.level) || building, b.id);
    for (const p of (b.roof?.extensions || []).filter(p => p.kind === 'awning'))
      add(p, 'awning', levels.get(p.level) || building, b.id);
    for (const p of fixtures.filter(p => p.building === b.id)) {
      assignedFixtures.add(p.id); add(p, p.sceneKind, parentFor(p), b.id, label(p, p.sceneKind === 'effect_fixture' ? 'effect' : 'light'), { piece: p });
    }
  }
  const yard = add({ id: 'yard' }, 'group', null, null, 'Yard');
  for (const [collection, kind, title] of [['terraces','terraces','Pad'],['hardscape','hardscape','Path / hardscape'],['beds','beds','Planting bed'],['edges','edges','Edge planting'],
    ['pool','pool','Pool'],['fire_pit','fire_pit','Fire pit'],['fence','fence','Fence'],['yard_rooms','yard_rooms','Yard room'],['planting','planting','Plant'],['furniture','furniture','Furniture'],['devices','device','Device']]) {
    for (const [i, p] of list(plan?.site?.[collection]).entries()) {
      const piece = { ...p, id: p.id || `${kind}:${i}` }, row = add(piece, kind, yard, null, p.name || `${title} ${i + 1}`, { piece, visibilityKind: p.object_kind === 'lamp' ? 'fixture' : visibilityKind(kind) });
      if (kind === 'pool') for (const f of p.features || []) add(f, f.kind, row, null, label(f, f.kind), { piece: f, poolId: piece.id });
    }
  }
  for (const p of fixtures.filter(p => !assignedFixtures.has(p.id))) add(p, p.sceneKind, yard, null, label(p, p.sceneKind === 'effect_fixture' ? 'effect' : 'light'), { piece: p });
  // Construction records are grouped above for lookup; flatten in tree order.
  const children = new Map();
  for (const r of rows) { const key = r.parent || null; if (!children.has(key)) children.set(key, []); children.get(key).push(r); }
  const ordered = [], visit = parent => { const siblings = children.get(parent) || []; for (const [index, r] of siblings.entries()) {
    r.position = index + 1; r.siblings = siblings.length; ordered.push(r); visit(r);
  } };
  visit(null); return ordered;
}

// Scene and Layers share the exact button, state and layout vocabulary.
export function createSceneRow({ name, select, hidden, locked, toggleHidden, toggleLocked }) {
  const row = document.createElement('div'); row.className = 'editor-scene-row';
  const title = document.createElement(select ? 'button' : 'span'); title.dataset.rowLabel = ''; title.textContent = name;
  if (select) { title.type = 'button'; title.dataset.sceneSelect = ''; title.tabIndex = -1; title.addEventListener('click', select); }
  row.append(title);
  function control(attr, get, toggle, on, off, glyph, other) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset[attr] = '';
    button.addEventListener('click', event => { event.stopPropagation(); toggle(); }); row.append(button);
    return () => { const value = !!get(); button.setAttribute('aria-pressed', String(value));
      button.setAttribute('aria-label', `${value ? off : on} ${name}`); button.title = `${value ? off : on} ${name}`;
      button.replaceChildren(icon(value ? other : glyph)); };
  }
  const eye = toggleHidden ? control('rowEye', hidden, toggleHidden, 'Hide', 'Show', 'eye', 'eye-off') : () => {};
  const lock = control('rowLock', locked, toggleLocked, 'Lock', 'Unlock', 'unlock', 'lock');
  row.update = () => { row.style.opacity = hidden() ? '0.5' : '1'; eye(); lock(); };
  row.update(); return row;
}

export function createSceneTree({ host, getPlan, getSelection, selection = null, select, visibility, floors, contextMenu }) {
  const life = new AbortController(), signal = life.signal, height = 36;
  let rows = [], active = null, anchorKey = null, mounted = new Map(), children = new Map(), lastSelection = null;
  // Expansion belongs to this editor session, never to the visibility store.
  const expanded = new Map();
  const visibleRows = () => {
    const visible = new Set();
    return rows.filter(r => {
      if (r.parent && (!visible.has(r.parent.key) || !expanded.get(r.parent.key))) return false;
      visible.add(r.key); return true;
    });
  };
  host.classList.add('editor-scene-tree'); host.setAttribute('role', 'tree'); host.setAttribute('aria-label', 'Scene');
  host.setAttribute('aria-multiselectable', 'true');
  const hidden = r => r.kind === 'group'
    ? rows.some(c => c.parent === r) && rows.filter(c => c.parent === r).every(c => visibility?.isHidden(c.id, c.visibilityKind || c.kind))
    : !!(r.kind === 'level' && floors?.hidden(r) || visibility?.isHidden(r.id, r.visibilityKind || r.kind) || r.parent && hidden(r.parent));
  const locked = r => {
    if (r.kind === 'group') return rows.some(c => c.parent === r) && rows.filter(c => c.parent === r).every(c => visibility?.isLocked(c.id, c.visibilityKind || c.kind));
    if (visibility?.isLocked(r.id, r.visibilityKind || r.kind)) return true;
    for (let p = r.parent; p; p = p.parent) if (['building', 'level', 'group'].includes(p.kind) && visibility?.isLocked(p.id)) return true;
    return false;
  };
  const rowToRef = r => {
    const ref = { kind: r.kind, pieceId: r.id };
    if (r.building != null) ref.buildingId = r.building;
    const level = r.kind === 'level' ? r.id : r.piece?.level;
    if (level != null) ref.level = level;
    if (r.piece?.entity_id !== undefined) ref.entity_id = r.piece.entity_id;
    if (r.poolId !== undefined) ref.poolId = r.poolId;
    return ref;
  };
  const primarySelection = () => selection?.primary?.() || getSelection?.() || null;
  const selectedId = () => primarySelection()?.pieceId ?? primarySelection()?.id ?? null;
  const selectedBuilding = () => primarySelection()?.buildingId ?? primarySelection()?.building ?? null;
  const primaryRowKey = () => {
    const id = selectedId();
    if (!id) return null;
    const building = selectedBuilding();
    return rows.find(r => r.id === id && (!building || r.building === building))?.key ?? null;
  };
  function buildSelectedKeys() {
    const exact = new Set(), anyBuilding = new Set();
    const mems = selection?.members?.();
    if (mems?.length) {
      for (const m of mems) exact.add(JSON.stringify([m.buildingId ?? m.building ?? null, m.pieceId ?? m.id]));
      return { exact, anyBuilding };
    }
    const cur = getSelection?.();
    if (Array.isArray(cur?.members) && cur.members.length) {
      for (const m of cur.members) {
        const id = m.pieceId ?? m.id; if (!id) continue;
        const b = m.buildingId ?? m.building ?? null;
        exact.add(JSON.stringify([b, id]));
        if (!b) anyBuilding.add(id);
      }
      return { exact, anyBuilding };
    }
    const id = selectedId(), building = selectedBuilding();
    if (id) {
      exact.add(JSON.stringify([building ?? null, id]));
      if (!building) anyBuilding.add(id);
    }
    return { exact, anyBuilding };
  }
  function paint() {
    const focused = host.contains(document.activeElement) ? { key: document.activeElement.closest('[data-scene-id]')?.dataset.sceneKey,
      control: document.activeElement.dataset.rowEye !== undefined ? 'row-eye' : document.activeElement.dataset.rowLock !== undefined ? 'row-lock'
        : document.activeElement.dataset.rowDisclosure !== undefined ? 'row-disclosure' : document.activeElement.dataset.sceneSelect !== undefined ? 'scene-select' : null } : null;
    const { exact: selectedKeys, anyBuilding: selectedAnyBuilding } = buildSelectedKeys();
    const isRowSelected = r => selectedKeys.has(r.key) || selectedAnyBuilding.has(r.id);
    const visible = visibleRows(), virtual = visible.length > 300;
    // Clamp before calculating the window when collapsing a long branch.
    host.scrollTop = Math.min(host.scrollTop, Math.max(0, visible.length * height - host.clientHeight));
    const start = virtual ? Math.max(0, Math.floor(host.scrollTop / height) - 4) : 0;
    const end = virtual ? Math.min(visible.length, start + Math.ceil((host.clientHeight || 300) / height) + 8) : visible.length;
    // Keep floor Choose buttons in the tree's natural order even outside the
    // virtual window. Existing floor selectors must always find every floor
    // whose building is expanded. Gaps still occupy their exact row heights.
    const rendered = visible.map((r, i) => ({ r, i })).filter(({ r, i }) => i >= start && i < end || r.floorKey);
    const focusKey = rendered.find(({ r }) => active ? r.key === active : isRowSelected(r))?.r.key || visible[start]?.key;
    host.replaceChildren(); mounted = new Map();
    const spacer = size => { const n = document.createElement('div'); n.style.height = `${size}px`; n.setAttribute('aria-hidden', 'true'); host.append(n); };
    let previous = -1;
    for (const { r, i } of rendered) {
      if (i > previous + 1) spacer((i - previous - 1) * height);
      previous = i;
      const isSetMemberRow = item => !item.floorKey && !['group', 'building', 'level'].includes(item.kind);
      const choose = event => {
        active = r.key;
        if (r.kind === 'group') { paint(); return; }
        if (event?.shiftKey) {
          const curVisible = visibleRows();
          const fallbackKey = primaryRowKey();
          const aIdx = curVisible.findIndex(item => item.key === (anchorKey || fallbackKey));
          const bIdx = curVisible.findIndex(item => item.key === r.key);
          const startIdx = aIdx === -1 ? bIdx : Math.min(aIdx, bIdx);
          const endIdx = aIdx === -1 ? bIdx : Math.max(aIdx, bIdx);
          const slice = curVisible.slice(startIdx, endIdx + 1);
          if (aIdx !== -1 && bIdx < aIdx) slice.reverse();
          const refs = slice.filter(item => isSetMemberRow(item) && !hidden(item)).map(rowToRef);
          if (!anchorKey) anchorKey = curVisible[aIdx !== -1 ? aIdx : bIdx]?.key ?? r.key;
          if (!refs.length) return;
          if (select) select(r, { mode: 'range', refs, additive: !!(event.ctrlKey || event.metaKey), event });
          else if (selection) {
            if (event.ctrlKey || event.metaKey) selection.set([...selection.members(), ...refs]);
            else selection.set(refs);
          }
          return;
        }
        anchorKey = r.key;
        if (event?.ctrlKey || event?.metaKey) {
          if (!isSetMemberRow(r)) return;
          const ref = rowToRef(r);
          if (select) select(r, { mode: 'toggle', ref, event });
          else selection?.toggle(ref);
          return;
        }
        if (select) select(r, { mode: 'replace', ref: rowToRef(r), event });
        else selection?.set([rowToRef(r)]);
      };
      const row = createSceneRow({ name: r.name, select: choose, hidden: () => hidden(r), locked: () => locked(r),
        // Awning triangles are merged into their roof section, so an awning
        // cannot independently hide. Keep selection/locking, omit the eye.
        toggleHidden: r.kind === 'awning' ? null : () => {
          const members = selection?.members?.() || [];
          if (members.length > 1 && members.some(ref => ref.pieceId === r.id && (ref.buildingId ?? null) === (r.building ?? null))) {
            visibility?.setMembers(members, { hidden: !hidden(r) }); return;
          }
          if (r.kind === 'level' && floors) {
            const show = hidden(r);
            if (show) for (let p = r; p; p = p.parent) visibility?.show(p.id);
            if (!show || floors.hidden(r)) floors.toggle(r);
            return;
          }
          if (r.kind === 'group') { const action = hidden(r) ? 'show' : 'hide'; for (const c of rows) { for (let p = c.parent; p; p = p.parent) if (p === r) { visibility?.[action](c.id); if (action === 'show') visibility?.showKind(c.visibilityKind || c.kind); break; } } return; }
          if (hidden(r)) { for (let p = r; p; p = p.parent) { visibility?.show(p.id); visibility?.showKind(p.visibilityKind || p.kind); if (p.kind === 'level' && floors?.hidden(p)) floors.toggle(p); } }
          else visibility?.hide(r.id);
        }, toggleLocked: () => {
          const members = selection?.members?.() || [];
          if (members.length > 1 && members.some(ref => ref.pieceId === r.id && (ref.buildingId ?? null) === (r.building ?? null))) {
            visibility?.setMembers(members, { locked: !locked(r) }); return;
          }
          if (r.kind === 'group') {
            const action = locked(r) ? 'unlock' : 'lock';
            for (const c of rows) for (let p = c.parent; p; p = p.parent) if (p === r) { visibility?.[action](c.id); if (action === 'unlock') visibility?.unlockKind(c.visibilityKind || c.kind); break; }
          } else if (locked(r)) for (let p = r; p; p = p.parent) { visibility?.unlock(p.id); visibility?.unlockKind(p.visibilityKind || p.kind); }
          else visibility?.lock(r.id);
        } });
      row.dataset.sceneId = r.id; row.dataset.sceneKey = r.key; row.setAttribute('role', 'treeitem'); row.setAttribute('aria-label', r.name);
      row.setAttribute('aria-level', String(r.depth + 1)); row.setAttribute('aria-posinset', String(r.position)); row.setAttribute('aria-setsize', String(r.siblings));
      row.setAttribute('aria-selected', String(isRowSelected(r))); row.tabIndex = r.key === focusKey ? 0 : -1;
      row.style.paddingLeft = `${r.depth * 12}px`;
      if (children.has(r.key)) {
        const open = !!expanded.get(r.key), disclosure = document.createElement('button');
        row.setAttribute('aria-expanded', String(open));
        disclosure.type = 'button'; disclosure.dataset.rowDisclosure = '';
        disclosure.setAttribute('aria-expanded', String(open));
        disclosure.setAttribute('aria-label', `${open ? 'Collapse' : 'Expand'} ${r.name}`);
        disclosure.title = `${open ? 'Collapse' : 'Expand'} ${r.name}`;
        const glyph = icon('chevron'); glyph.style.transform = open ? '' : 'rotate(-90deg)'; disclosure.append(glyph);
        disclosure.addEventListener('click', event => {
          event.stopPropagation(); active = r.key; expanded.set(r.key, !open); paint();
          mounted.get(r.key)?.querySelector('[data-row-disclosure]').focus({ preventScroll: true });
        });
        row.prepend(disclosure);
      }
      if (r.floorKey) {
        const eye = row.querySelector('[data-row-eye]'), title = row.querySelector('[data-scene-select]');
        eye.dataset.floorVisible = r.floorKey; title.dataset.floor = r.floorKey;
        title.setAttribute('aria-pressed', String(floors?.current?.() === r.floorKey));
        // Per-floor Choose survives as the floor row's primary action.
      }
      row.addEventListener('click', e => { if (e.target === row) choose(e); });
      row.addEventListener('contextmenu', e => { e.preventDefault(); contextMenu?.(e, r); });
      row.addEventListener('focus', () => { active = r.key; });
      row.addEventListener('keydown', e => {
        if (e.target !== row && !e.target.matches('[data-scene-select], [data-row-disclosure]')) return;
        if (e.target.matches('[data-row-disclosure]') && ['Enter', ' '].includes(e.key)) return;
        if (['Enter', ' '].includes(e.key)) { e.preventDefault(); e.stopPropagation(); choose(e); return; }
        if (e.key === 'ArrowRight' && children.has(r.key) && !expanded.get(r.key)
          || e.key === 'ArrowLeft' && children.has(r.key) && expanded.get(r.key)) {
          e.preventDefault(); e.stopPropagation(); active = r.key; expanded.set(r.key, e.key === 'ArrowRight');
          paint(); mounted.get(r.key)?.focus({ preventScroll: true }); return;
        }
        const next = e.key === 'ArrowDown' ? visible[i + 1] : e.key === 'ArrowUp' ? visible[i - 1]
          : e.key === 'Home' ? visible[0] : e.key === 'End' ? visible.at(-1) : e.key === 'ArrowLeft' ? r.parent
            : e.key === 'ArrowRight' ? children.get(r.key)?.[0] : null;
        if (!next) return; e.preventDefault(); e.stopPropagation(); reveal(next.id, next.building); mounted.get(next.key)?.focus({ preventScroll: true });
      });
      mounted.set(r.key, row); host.append(row);
    }
    if (previous < visible.length - 1) spacer((visible.length - previous - 1) * height);
    if (!rows.length) { const p = document.createElement('p'); p.textContent = 'No pieces yet'; host.append(p); }
    if (focused && mounted.has(focused.key)) (focused.control ? mounted.get(focused.key).querySelector(`[data-${focused.control}]`) : mounted.get(focused.key)).focus({ preventScroll: true });
  }
  function reveal(id, building = id === selectedId() ? selectedBuilding() : null) {
    lastSelection = primaryRowKey();
    const row = rows.find(r => r.id === id && (!building || r.building === building)); if (!row) { paint(); return; }
    for (let p = row.parent; p; p = p.parent) expanded.set(p.key, true);
    const visible = visibleRows(), i = visible.indexOf(row), key = row.key; active = key;
    if (visible.length > 300) {
      if (i * height < host.scrollTop || (i + 1) * height > host.scrollTop + host.clientHeight) host.scrollTop = Math.max(0, i * height - height);
    }
    paint(); active = key; mounted.get(key)?.scrollIntoView({ block: 'nearest' });
  }
  function refresh() {
    rows = sceneRows(getPlan()); children = new Map();
    for (const r of rows) {
      if (r.parent) { const siblings = children.get(r.parent.key) || []; siblings.push(r); children.set(r.parent.key, siblings); }
      if (!expanded.has(r.key)) expanded.set(r.key, r.kind === 'building' || r.kind === 'group'
        || r.kind === 'level' && r.floorKey === floors?.current?.());
    }
    const selected = primaryRowKey();
    if (selected !== lastSelection) { lastSelection = selected; reveal(selectedId(), selectedBuilding()); }
    else paint();
  }
  host.addEventListener('scroll', paint, { signal });
  const off = visibility?.subscribe(paint);
  const offSelection = selection?.subscribe?.(() => paint());
  refresh();
  return { refresh, reveal, dispose() { off?.(); offSelection?.(); life.abort(); host.replaceChildren(); } };
}
