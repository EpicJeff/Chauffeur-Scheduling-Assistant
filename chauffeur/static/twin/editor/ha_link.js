const noHa = 'Home Assistant is not connected, so areas and devices are hidden.';
const goneArea = "This room's Home Assistant area is gone; pick another.";
const unavailable = () => ({ available: false, areas: [], floors: [], rooms: [], unlinked: [], devices: [] });

export function createHaLink({ api, onCommit, signal, getPlan, canEdit = () => true }) {
  let latest = null, pending = null, queued = null, placement = null;
  const blinking = new Set(), drawn = new WeakMap();
  const element = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const listen = (node, type, action) => node.addEventListener(type, () => {
    if (!signal?.aborted) Promise.resolve().then(action).catch(api.report);
  }, { signal });
  // `focus` names the control so a redraw can hand keyboard focus to its successor.
  const button = (text, action, focus) => {
    const node = element('button', text); node.type = 'button';
    if (focus) node.dataset.haFocus = focus;
    listen(node, 'click', action);
    return node;
  };
  const commit = (room, value) => onCommit({ op: 'set', building: room.building,
    id: room.id, field: 'ha_area', value });
  const byLevel = floors => [...floors || []].sort((a, b) =>
    (a.level ?? Infinity) - (b.level ?? Infinity) || String(a.name).localeCompare(String(b.name)));

  function isPlaced(device) {
    const plan = getPlan?.();
    return plan ? plan.buildings.some(b => b.anchors?.some(a => a.device === device.device_id)
      || b.devices?.some(d => d.device === device.device_id)) : !!device.placed;
  }
  // The area id a room shows: its stored value, matched to an area by id or name.
  function chosen(room) {
    const row = latest?.rooms?.find(r => r.room === room.id && r.building === room.building);
    const value = room.ha_area ?? row?.ha_area ?? '';
    const areas = latest?.areas || [];
    const area = areas.find(a => a.area_id === value || a.name.toLowerCase() === String(value).toLowerCase());
    return { row, value, selected: area?.area_id ?? value, known: !!area };
  }

  // An unnamed spot says what it is for and where it sits: 'Light spot 1 on the ceiling'.
  function spotName(kind, index, host = {}) {
    const where = host.ceiling ? ' on the ceiling' : host.floor ? ' on the floor' : host.wall ? ' on a wall' : host.opening ? ' by a door' : '';
    return `${String(kind || 'device').charAt(0).toUpperCase()}${String(kind || 'device').slice(1)} spot ${index + 1}${where}`;
  }

  async function pickSpot(room, device) {
    if (!canEdit()) return;
    placement?.cancel();
    const anchors = placement?.anchors(room).filter(a => !a.device && a.kind === device.kind) || [];
    const choice = await window.promptChoice('Pick a spot', `Where does ${device.name} belong?`, [
      ...anchors.map((a, i) => ({ value: a.id, label: a.name || spotName(device.kind, i, a.host) })),
      { value: 'wall', label: 'On a wall' }, { value: 'ceiling', label: 'On the ceiling' },
    ]);
    if (signal?.aborted || !canEdit() || choice == null) return;
    if (choice === 'wall' || choice === 'ceiling') placement?.arm(device, choice);
    else if (anchors.some(a => a.id === choice)) await onCommit({ op: 'place_device', device: device.device_id, anchor: choice });
  }

  async function blink(device) {
    if (!canEdit() || blinking.has(device.device_id)) return;
    blinking.add(device.device_id);
    try { await api.request('identify', 'POST', { device_id: device.device_id }, 'ha'); }
    catch { if (!signal?.aborted) window.showGlobalAlert('Could not blink that light.'); }
    finally { blinking.delete(device.device_id); }
  }

  function devicesSection(room, area, notes) {
    const section = element('section');
    section.append(element('h3', 'Devices'));
    for (const device of latest.devices || []) {
      if (device.area_id !== area) continue;
      const row = element('div'); row.className = 'editor-material-line editor-device-row';
      const words = element('div'), actions = element('div'); actions.className = 'editor-material-actions';
      words.append(element('p', device.name), element('span', device.kind), element('span', isPlaced(device) ? 'Placed' : 'Not placed yet'));
      actions.append(button('Pick a spot', () => pickSpot(room, device), `spot:${device.device_id}`));
      if (device.kind === 'light') actions.append(button('Blink', () => blink(device), `blink:${device.device_id}`));
      row.addEventListener('pointerdown', event => placement?.startDrag(event, device), { signal });
      row.append(words, actions); section.append(row);
    }
    for (const note of notes || []) section.append(element('p', note));
    return section;
  }

  function anchorSection(anchor) {
    const section = element('section');
    if (!latest?.available || !anchor.device) return section;
    const device = latest.devices?.find(d => d.device_id === anchor.device);
    section.className = 'editor-material-line';
    section.append(element('p', device?.name || anchor.device), button('Remove', () => {
      if (canEdit()) return onCommit({ op: 'unplace_device', device: anchor.device });
    }, 'remove'));
    return section;
  }

  function refresh() {
    if (signal?.aborted) return Promise.resolve(latest);
    // A read asked for while one is out (a save landed meanwhile) follows it, so
    // the answer kept is never older than the last change.
    if (pending) return queued ||= pending.then(() => { queued = null; return refresh(); });
    pending = api.request('link', 'GET', undefined, 'ha').then(data => {
      if (!signal?.aborted) latest = data;
      return latest;
    }).catch(() => {
      // A dropped read keeps the last good answer; the server itself answers
      // available: false when Home Assistant is away.
      if (!signal?.aborted && !latest) latest = unavailable();
      return latest;
    }).finally(() => { pending = null; });
    return pending;
  }

  function roomSection(room) {
    const section = element('section');
    section.dataset.haRoom = `${room.building}|${room.id}`;
    if (!latest) return section;
    if (!latest.available) { section.append(element('p', noHa)); return section; }
    const { row, value, selected, known } = chosen(room);
    const areas = latest.areas || [];
    const label = element('label', 'Home Assistant area'), select = element('select');
    select.setAttribute('aria-label', 'Home Assistant area');
    select.dataset.haFocus = 'area';
    const option = (value, name) => {
      const node = element('option', name); node.value = value; return node;
    };
    select.append(option('', 'No area'));
    // A gone area stays shown as the current choice; it cannot be picked again.
    if (selected && !known) { const gone = option(selected, String(selected)); gone.disabled = true; select.append(gone); }
    const grouped = new Set();
    for (const floor of byLevel(latest.floors)) {
      const members = areas.filter(a => a.floor_id === floor.floor_id);
      if (!members.length) continue;
      const group = element('optgroup'); group.label = floor.name;
      for (const area of members) {
        group.append(option(area.area_id, area.name)); grouped.add(area.area_id);
      }
      select.append(group);
    }
    for (const area of areas) if (!grouped.has(area.area_id)) select.append(option(area.area_id, area.name));
    select.value = selected;
    select.dataset.saved = selected;
    listen(select, 'change', async () => {
      const picked = select.value;
      try { await commit(room, picked); }
      catch (error) { select.value = select.dataset.saved; throw error; }
    });
    label.append(select); section.append(label);
    if (row?.gone) section.append(element('p', goneArea));
    if (!value && row?.suggested) {
      const id = typeof row.suggested === 'string' ? row.suggested : row.suggested.area_id;
      const area = areas.find(a => a.area_id === id) || row.suggested;
      if (area?.name) {
        const suggestion = element('div'); suggestion.className = 'editor-material-line';
        suggestion.append(element('p', `Suggested: ${area.name}`), button('Use', () => commit(room, id), 'use'));
        section.append(suggestion);
      }
    }
    if (selected && !row?.gone && known) section.append(devicesSection(room, selected, row?.notes));
    return section;
  }

  // Rooms a person can link: never a ghost the build only proposed. Each names
  // its floor, because two floors often hold rooms of the same name.
  function choosable(building) {
    const levels = building.levels || [];
    return (building.rooms || []).filter(r => r.state !== 'ghost').map(r => {
      const level = levels.find(l => l.id === r.level);
      return { room: r, label: level?.name ? `${r.name || 'Room'} · ${level.name}` : r.name || 'Room' };
    });
  }

  function buildingSection(building) {
    const section = element('section');
    if (!latest?.available || !latest.unlinked?.length) return section;
    section.append(element('h3', 'Areas with no room'));
    const actions = element('div'); actions.className = 'editor-actions';
    for (const area of latest.unlinked) actions.append(button(area.name, async () => {
      const rooms = choosable(building);
      const id = await window.promptChoice('Choose a room', `Which room belongs to ${area.name}?`,
        rooms.map(({ room, label }) => ({ value: room.id, label })));
      if (signal?.aborted || id == null) return;
      const room = rooms.find(r => r.room.id === id)?.room;
      if (room) await commit({ ...room, building: building.id }, area.area_id);
    }, `unlinked:${area.area_id}`));
    section.append(actions);
    return section;
  }

  // What a card's section shows, kept small: it redraws only when this changes.
  function key({ kind, piece, building }) {
    if (!latest) return 'none';
    const base = [kind, building?.id, piece?.id, latest.available, canEdit()];
    if (!latest.available) return JSON.stringify(base);
    if (kind === 'anchor') {
      const device = latest.devices?.find(d => d.device_id === piece.device);
      return JSON.stringify([...base, piece.device || null, device?.name || null]);
    }
    if (kind === 'room') {
      const { row, selected } = chosen({ ...piece, room: piece.id, building: building.id });
      const devices = (latest.devices || []).filter(d => d.area_id === selected)
        .map(d => [d.device_id, d.name, d.kind, isPlaced(d)]);
      return JSON.stringify([...base, piece.ha_area, row, latest.areas, latest.floors, devices]);
    }
    return JSON.stringify([...base, latest.unlinked, choosable(building).map(({ room, label }) => [room.id, label])]);
  }

  // Draw a card's Home Assistant section into `host`. A person's focus is kept:
  // the area pick-list they are in stays in place (an open list never shuts
  // under them), and any other control they were on hands focus to its successor.
  function draw(host, record) {
    const next = key(record);
    if (drawn.get(host) === next) return false;
    drawn.set(host, next);
    const fresh = record.kind === 'room'
      ? roomSection({ ...record.piece, room: record.piece.id, building: record.building.id })
      : record.kind === 'anchor' ? anchorSection(record.piece) : buildingSection(record.building);
    const focused = document.activeElement, old = host.firstElementChild;
    const inside = focused && focused !== host && host.contains(focused) ? focused : null;
    const kept = inside?.localName === 'select' && old?.dataset?.haRoom
      && old.dataset.haRoom === fresh.dataset?.haRoom ? inside.closest('label') : null;
    const freshLabel = kept && fresh.querySelector('label');
    if (kept && freshLabel) {
      for (const child of [...old.children]) if (child !== kept) child.remove();
      const saved = freshLabel.querySelector('select')?.dataset.saved;
      if (saved !== undefined) inside.dataset.saved = saved;
      old.append(...[...fresh.children].filter(child => child !== freshLabel));
    } else {
      host.replaceChildren(fresh);
      const name = inside?.dataset?.haFocus;
      if (name) [...host.querySelectorAll('select, button')].find(n => n.dataset.haFocus === name)?.focus();
    }
    host.querySelectorAll('select, button').forEach(node => { node.disabled = !canEdit(); });
    return true;
  }

  return { refresh, roomSection, buildingSection, anchorSection, draw, state: () => latest,
    cancelPlacement() { placement?.cancel(); },
    setPlacement(value) { placement = value; } };
}
