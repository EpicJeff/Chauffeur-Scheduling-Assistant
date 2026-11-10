const noHa = 'Home Assistant is not connected, so areas and devices are hidden.';
const goneArea = "This room's Home Assistant area is gone; pick another.";

export function createHaLink({ api, onCommit, signal, getPlan, canEdit = () => true }) {
  let latest = null, pending = null, queued = null, placement = null;
  const blinking = new Set();
  const element = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const listen = (node, type, action) => node.addEventListener(type, () => {
    if (!signal?.aborted) Promise.resolve().then(action).catch(api.report);
  }, { signal });
  const button = (text, action) => {
    const node = element('button', text); node.type = 'button';
    listen(node, 'click', action);
    return node;
  };
  const commit = (room, value) => onCommit({ op: 'set', building: room.building,
    id: room.id, field: 'ha_area', value });

  function isPlaced(device) {
    const plan = getPlan?.();
    return plan ? plan.buildings.some(b => b.anchors?.some(a => a.device === device.device_id)
      || b.devices?.some(d => d.device === device.device_id)) : !!device.placed;
  }

  async function pickSpot(room, device) {
    if (!canEdit()) return;
    placement?.cancel();
    const anchors = placement?.anchors(room).filter(a => !a.device && a.kind === device.kind) || [];
    const choice = await window.promptChoice('Pick a spot', `Where does ${device.name} belong?`, [
      ...anchors.map((a, i) => ({ value: a.id, label: a.name || `${device.kind} spot ${i + 1}` })),
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
      actions.append(button('Pick a spot', () => pickSpot(room, device)));
      if (device.kind === 'light') actions.append(button('Blink', () => blink(device)));
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
    }));
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
      if (!signal?.aborted) latest = { available: false, areas: [], floors: [], rooms: [], unlinked: [], devices: [] };
      return latest;
    }).finally(() => { pending = null; });
    return pending;
  }

  function roomSection(room) {
    const section = element('section');
    if (!latest) return section;
    if (!latest.available) { section.append(element('p', noHa)); return section; }
    const row = latest.rooms?.find(r => r.room === room.id && r.building === room.building);
    const value = room.ha_area ?? row?.ha_area ?? '';
    const areas = latest.areas || [];
    const selected = areas.find(a => a.area_id === value || a.name.toLowerCase() === String(value).toLowerCase())?.area_id ?? value;
    const label = element('label', 'Home Assistant area'), select = element('select');
    select.setAttribute('aria-label', 'Home Assistant area');
    const option = (value, name) => {
      const node = element('option', name); node.value = value; return node;
    };
    select.append(option('', 'No area'));
    const grouped = new Set();
    for (const floor of latest.floors || []) {
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
    listen(select, 'change', async () => {
      const picked = select.value;
      try { await commit(room, picked); }
      catch (error) { select.value = selected; throw error; }
    });
    label.append(select); section.append(label);
    if (row?.gone) section.append(element('p', goneArea));
    if (!value && row?.suggested) {
      const id = typeof row.suggested === 'string' ? row.suggested : row.suggested.area_id;
      const area = areas.find(a => a.area_id === id) || row.suggested;
      if (area?.name) {
        const suggestion = element('div'); suggestion.className = 'editor-material-line';
        suggestion.append(element('p', `Suggested: ${area.name}`), button('Use', () => commit(room, id)));
        section.append(suggestion);
      }
    }
    if (selected && !row?.gone && areas.some(a => a.area_id === selected))
      section.append(devicesSection(room, selected, row?.notes));
    return section;
  }

  function buildingSection(building) {
    const section = element('section');
    if (!latest?.available || !latest.unlinked?.length) return section;
    section.append(element('h3', 'Areas with no room'));
    const actions = element('div'); actions.className = 'editor-actions';
    for (const area of latest.unlinked) actions.append(button(area.name, async () => {
      const rooms = building.rooms || [];
      const id = await window.promptChoice('Choose a room', `Which room belongs to ${area.name}?`,
        rooms.map(r => ({ value: r.id, label: r.name || 'Room' })));
      if (signal?.aborted || id === null) return;
      const room = rooms.find(r => r.id === id);
      if (room) await commit({ ...room, building: building.id }, area.area_id);
    }));
    section.append(actions);
    return section;
  }

  return { refresh, roomSection, buildingSection, anchorSection, state: () => latest,
    cancelPlacement() { placement?.cancel(); },
    setPlacement(value) { placement = value; } };
}
