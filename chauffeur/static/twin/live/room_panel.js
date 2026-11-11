import { kindOf } from './kinds.js';
export { confirmUnsafe } from './kinds.js';

const element = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
};

export function deviceActions(row, state, control, { compact = false, getState } = {}) {
  return kindOf(row).panel({row, state, control, compact, getState});
}

export function mountRoomPanel(live) {
  const panel = element('aside'); panel.id = 'twin-room-panel'; panel.className = 'twin-device-sheet'; panel.hidden = true;
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-labelledby', 'twin-room-title');
  const header = element('header'), title = element('h2'); title.id = 'twin-room-title';
  const close = element('button', 'Close'); close.type = 'button';
  header.className = 'twin-device-actions'; header.append(title, close);
  const body = element('div'); body.className = 'twin-room-devices'; panel.append(header, body); document.body.append(panel);
  const empty = element('p', 'No devices in this room.');
  let room = null, shown = null;
  const widgets = new Map();
  function clear() {
    for (const widget of widgets.values()) widget.actions.stop?.();
    widgets.clear(); body.replaceChildren();
  }
  // A poll that changes nothing in this room leaves its rows alone, so a press that spans
  // the poll still lands and focus stays put (review M2).
  function render() {
    if (!room) return;
    const rows = live.devices(room.area_id), states = live.states();
    const key = JSON.stringify([room.area_id, rows.map(row => [row.device_id, row.offered, row.label,
      states[row.entity_id]?.state, states[row.entity_id]?.attributes])]);
    if (key === shown) return;
    shown = key;
    const active = document.activeElement;
    const focusId = active?.closest('[data-device-id]')?.dataset.deviceId;
    const focusLabel = active?.getAttribute('aria-label') || active?.textContent;
    const scroll = body.scrollTop;
    const ids = new Set(rows.map(row => row.device_id));
    empty.remove();
    for (const [id, widget] of widgets) {
      if (ids.has(id)) continue;
      widget.actions.stop?.(); widget.node.remove(); widgets.delete(id);
    }
    for (const row of rows) {
      const state = states[row.entity_id], attrs = state?.attributes || {};
      const shape = JSON.stringify([row.kind, row.offered, attrs.supported_color_modes, attrs.effect_list,
        attrs.min_color_temp_kelvin, attrs.max_color_temp_kelvin, attrs.min_mireds, attrs.max_mireds]);
      let widget = widgets.get(row.device_id);
      if (!widget || shape !== widget.shape || !widget.actions.update) {
        const node = widget?.node || element('section');
        widget?.actions.stop?.();
        node.className = 'twin-room-device'; node.dataset.deviceId = row.device_id;
        const name = element('h3'), status = element('p');
        const actions = deviceActions(row, state, live.control, {getState: () => live.states()[row.entity_id]});
        node.replaceChildren(name, status, actions);
        widget = {node, name, status, actions, shape}; widgets.set(row.device_id, widget);
      }
      const {node, name, status, actions} = widget;
      name.textContent = row.name; status.textContent = row.label; actions.update?.(state);
      if (row.kind === 'climate') status.textContent = `${row.label} · Current ${attrs.current_temperature ?? '—'} · Setpoint ${attrs.temperature ?? '—'}`;
      if (node.parentElement !== body) body.append(node);
    }
    if (!rows.length) body.append(empty);
    body.scrollTop = scroll;
    if (focusId) {
      const row = [...body.children].find(node => node.dataset.deviceId === focusId);
      [...(row?.querySelectorAll('button, input') || [])].find(node =>
        (node.getAttribute('aria-label') || node.textContent) === focusLabel)?.focus({ preventScroll: true });
    }
  }
  const unsubscribe = live.subscribe(render);
  function hide() { room = null; shown = null; panel.hidden = true; clear(); }
  close.addEventListener('click', hide);
  return {
    open(next) {
      if (!next?.area_id) { hide(); return; }
      room = next; shown = null; title.textContent = room.name || 'Room'; panel.hidden = false; render();
    },
    close: hide,
    stop() { unsubscribe(); clear(); panel.remove(); },
  };
}
