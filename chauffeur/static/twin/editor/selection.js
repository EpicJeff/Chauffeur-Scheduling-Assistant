// Room context is independent of the piece whose card is open.
export function createSelection({ view, getModel, onChange }) {
  let selected = null, room = null, hovered = null, ghosted = 0;
  let walls = [], allowed = [];
  const normalize = pick => pick && {
    kind: pick.kind, id: pick.id ?? pick.pieceId,
    building: pick.building ?? pick.buildingId, level: pick.level,
  };
  const building = id => getModel()?.buildings?.find(b => b.id === id);
  function roomContext(pick) {
    const b = building(pick.building), r = b?.rooms?.find(r => r.id === pick.id);
    if (!r) return null;
    const cycle = r.joints || [];
    const pairs = new Set(cycle.map((id, i) => [id, cycle[(i + 1) % cycle.length]].sort().join('\n')));
    const boundary = (b.walls || []).filter(w => w.joints?.length === 2 && pairs.has([...w.joints].sort().join('\n')));
    const ids = new Set([r.id, ...boundary.map(w => w.id)]);
    const belongs = host => host && (ids.has(host.wall) || host.floor === r.id || host.ceiling === r.id);
    for (const list of ['openings', 'anchors', 'items']) for (const piece of b[list] || []) {
      if (ids.has(piece.wall) || belongs(piece.host)) ids.add(piece.id);
    }
    return { kind: 'room', id: r.id, building: b.id, level: r.level,
      walls: boundary.map(w => w.id), allowed: [...ids] };
  }
  const inside = pick => !room || (pick && pick.building === room.building && allowed.includes(pick.id));
  function paint() {
    ghosted = view.setSelection?.({ selected, hover: hovered,
      room: room && { ...room, walls, allowed } }) || 0;
  }
  function current() {
    return { kind: selected?.kind ?? null, id: selected?.id ?? null,
      building: selected?.building ?? null, level: selected?.level ?? null,
      room: room?.id ?? null, ghosted,
      tinted: { floor: room?.id ?? null, walls: [...walls] }, hover: hovered && { ...hovered } };
  }
  function changed() { paint(); onChange?.(current()); }
  function clear() {
    selected = room = hovered = null; walls = []; allowed = []; changed();
  }
  function focusRoom(id, buildingId) {
    const pick = typeof id === 'object' ? normalize(id) : { id, building: buildingId };
    const context = pick && roomContext(pick);
    if (!context) { clear(); return; }
    room = { kind: 'room', id: context.id, building: context.building, level: context.level };
    walls = context.walls; allowed = context.allowed; selected = { ...room }; hovered = null; changed();
  }
  function back() {
    hovered = null;
    if (room && selected?.id !== room.id) { selected = { ...room }; changed(); }
    else clear();
  }
  function select(value) {
    const pick = normalize(value);
    if (!pick || !inside(pick)) { back(); return; }
    if (pick.kind === 'room') { focusRoom(pick); return; }
    if (['building', 'level'].includes(pick.kind)) {
      room = null; walls = []; allowed = [];
    }
    selected = pick; hovered = null; changed();
  }
  function hover(value) {
    const pick = normalize(value), next = pick && inside(pick) ? pick : null;
    if (JSON.stringify(next) === JSON.stringify(hovered)) return;
    hovered = next; paint();
  }
  function refresh() {
    if (room) {
      const context = roomContext(room);
      if (!context) { clear(); return; }
      walls = context.walls; allowed = context.allowed;
      if (!inside(selected)) selected = { ...room };
    }
    changed();
  }
  return { hover, select, clear, current, focusRoom, back, refresh };
}
