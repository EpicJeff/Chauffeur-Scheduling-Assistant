// The shell owns presentation only. Cards keep their nodes, field queues and
// domain actions; a tool temporarily takes Properties without losing selection.
export function createDock({ host }) {
  const el = id => document.getElementById(id), life = new AbortController();
  const listen = (node, type, fn, options = {}) => node.addEventListener(type, fn, { ...options, signal: life.signal });
  const content = el('properties-content'), empty = el('properties-empty');
  const crumbs = el('properties-crumbs'), back = el('properties-back'), splitter = el('dock-splitter');
  const pages = new Map(), resized = new Set(), tabChanged = new Set();
  let page = null, tool = null, top = 42, drag = null, active = 'scene';
  const notify = () => { for (const fn of resized) fn(); };
  function show(tab) {
    if (!['scene', 'layers', 'library', 'argyle'].includes(tab)) return;
    active = tab;
    for (const button of host.querySelectorAll('[data-dock-tab]')) {
      const selected = button.dataset.dockTab === tab;
      button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
      el('dock-pane-' + button.dataset.dockTab).hidden = !selected;
    }
    el('rail-library')?.setAttribute('aria-pressed', String(tab === 'library'));
    for (const fn of tabChanged) fn(tab);
  }
  function paint(reveal = false) {
    const current = tool || page, state = current && pages.get(current);
    for (const [node, value] of pages) value.slot.hidden = node !== current;
    empty.hidden = !!state;
    crumbs.textContent = state?.crumbs?.map(c => typeof c === 'string' ? c : c.label).join(' > ') || 'Properties';
    back.disabled = !state?.back;
    if (reveal) el('properties-heading').scrollIntoView({ block: 'nearest' });
  }
  const api = {
    render(node, { crumbs = [], back = null, tool: armed = false, reveal = true } = {}) {
      if (!node) return;
      let state = pages.get(node);
      if (!state) {
        const slot = document.createElement('div'); slot.className = 'properties-page';
        content.append(slot); slot.append(node); state = { slot }; pages.set(node, state);
      }
      Object.assign(state, { crumbs, back }); node.hidden = false;
      if (armed) tool = node;
      else {
        if (tool === node) tool = null;
        if (reveal || !page || page === node) {
          if (page !== node) state.previous = page;
          page = node;
        }
      }
      paint(reveal);
    },
    clear(node = null) {
      if (!node) { page = null; tool = null; }
      else {
        if (page === node) {
          const previous = pages.get(node)?.previous;
          page = previous && !previous.hidden ? previous : null;
        }
        if (tool === node) tool = null;
      }
      paint();
    },
  };
  listen(back, 'click', () => pages.get(tool || page)?.back?.());
  for (const button of host.querySelectorAll('[data-dock-tab]')) {
    listen(button, 'click', () => show(button.dataset.dockTab));
    listen(button, 'keydown', event => {
      const tabs = [...host.querySelectorAll('[data-dock-tab]')], index = tabs.indexOf(button);
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next === null) return;
      event.preventDefault(); show(tabs[next].dataset.dockTab); tabs[next].focus();
    });
  }
  function size(value) {
    top = Math.max(20, Math.min(70, value));
    host.style.setProperty('--dock-top-height', `${top}%`);
    splitter.setAttribute('aria-valuenow', String(Math.round(top))); notify();
  }
  listen(splitter, 'pointerdown', event => {
    if (event.button !== 0) return;
    drag = event.pointerId; splitter.setPointerCapture(drag); event.preventDefault();
  });
  listen(splitter, 'pointermove', event => {
    if (drag !== event.pointerId) return;
    const rect = host.getBoundingClientRect(); size((event.clientY - rect.top) / rect.height * 100);
  });
  const release = event => {
    if (drag !== event.pointerId) return;
    if (splitter.hasPointerCapture(drag)) splitter.releasePointerCapture(drag); drag = null;
  };
  listen(splitter, 'pointerup', release); listen(splitter, 'pointercancel', release);
  listen(splitter, 'keydown', event => {
    const delta = event.key === 'ArrowUp' ? -5 : event.key === 'ArrowDown' ? 5 : 0;
    if (!delta && !['Home', 'End'].includes(event.key)) return;
    event.preventDefault(); size(event.key === 'Home' ? 20 : event.key === 'End' ? 70 : top + delta);
  });
  listen(window, 'resize', notify);
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(notify);
  observer?.observe(host);
  show('scene'); paint();
  return { show, current: () => active, properties: api,
    onShow(fn) { tabChanged.add(fn); return () => tabChanged.delete(fn); },
    onResize(fn) { resized.add(fn); return () => resized.delete(fn); },
    dispose() {
      life.abort(); observer?.disconnect(); resized.clear(); tabChanged.clear(); api.clear();
      for (const [node, { slot }] of pages) {
        if (node.parentElement === slot) { node.hidden = true; content.append(node); }
        slot.remove();
      }
      pages.clear();
    },
  };
}

// A shared path for every piece card and a device's Fixtures child page.
// The room selected by the picker wins on a wall shared by two rooms.
export function propertyPath(record, state = {}, select = () => {}) {
  if (!record) return { crumbs: [], back: null };
  const { piece, building, kind } = record;
  const pick = id => () => select(id ? { pieceId: id, buildingId: building?.id ?? null } : null);
  if (!building) return { crumbs: ['Yard', piece.name || kind.replaceAll('_', ' ')], back: pick(piece.feature?.feature || null) };
  if (kind === 'building') return { crumbs: [building.name || building.id], back: pick(null) };
  const wall = kind === 'wall' ? piece : building.walls?.find(w => w.id === (piece.wall || piece.host?.wall));
  const room = building.rooms?.find(r => r.id === (kind === 'room' ? piece.id : state.room || piece.host?.floor || piece.host?.ceiling
    || building.anchors?.find(a => a.id === piece.host?.anchor)?.host?.floor))
    || building.rooms?.find(r => wall && (r.walls?.includes(wall.id) || r.joints?.some((id, i, cycle) =>
      wall.joints?.length === 2 && [id, cycle[(i + 1) % cycle.length]].every(joint => wall.joints.includes(joint)))));
  const level = building.levels?.find(l => l.id === (kind === 'level' ? piece.id : piece.level || wall?.level || room?.level));
  const crumbs = [];
  if (level) crumbs.push(level.name || level.id);
  if (room) crumbs.push(room.name || 'Room');
  if (!['room', 'level'].includes(kind)) crumbs.push(piece.name || (kind === 'building' ? building.id : kind[0].toUpperCase() + kind.slice(1)));
  return { crumbs, back: pick(kind === 'building' ? null : kind === 'level' ? building.id : kind === 'room' ? level?.id : room?.id || level?.id || building.id) };
}
