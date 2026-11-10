const noHa = 'Home Assistant is not connected, so areas and devices are hidden.';
const goneArea = "This room's Home Assistant area is gone; pick another.";

export function createHaLink({ api, onCommit, signal }) {
  let latest = null, pending = null;
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

  function refresh() {
    if (signal?.aborted) return Promise.resolve(latest);
    if (pending) return pending;
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

  return { refresh, roomSection, buildingSection, state: () => latest };
}
