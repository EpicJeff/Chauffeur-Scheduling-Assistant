import { kindOf } from './kinds.js';
import { base } from '../twin_library.js';
import { deviceControls, deviceControlShape } from './controls/device.js';
export { confirmUnsafe } from './kinds.js';

const element = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
};

export function deviceActions(row, state, control, { compact = false, getState, getEntityState } = {}) {
  return deviceControls({row, state, control, compact, getState, getEntityState});
}

export function mountRoomPanel(live) {
  const panel = element('aside'); panel.id = 'twin-room-panel'; panel.className = 'twin-device-sheet'; panel.hidden = true;
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-labelledby', 'twin-room-title');
  const header = element('header'), title = element('h2'); title.id = 'twin-room-title';
  const close = element('button', 'Close'); close.type = 'button';
  header.className = 'twin-device-actions'; header.append(title, close);
  const body = element('div'); body.className = 'twin-room-devices'; panel.append(header, body); document.body.append(panel);
  const empty = element('p', 'No devices in this room.');
  let room = null, shown = null, sequence = 0;
  const widgets = new Map();
  function stop(widget) {
    widget.disposed = true; widget.actions.stop?.();
    if (widget.cardId) window.ChauffeurHaCards?.unmount(widget.cardId);
  }
  function clear() {
    for (const widget of widgets.values()) stop(widget);
    widgets.clear(); body.replaceChildren();
  }
  function addMore(widget, row) {
    const kind = kindOf(row).id;
    if (['lock', 'garage', 'alarm'].includes(kind)) return;
    // A device the grid does not offer is read-only here: HA's own card would draw live
    // controls the server then refuses (review M1).
    if (!row.offered) return;
    const more = element('button', 'More'); more.type = 'button'; more.setAttribute('data-more', '');
    const bar = element('div'); bar.className = 'twin-device-actions'; bar.append(more);
    const host = element('div'); host.hidden = true; widget.node.append(bar, host);
    widget.cardId = `twin-card-${row.device_id}-${++sequence}`;
    more.addEventListener('click', async () => {
      if (widget.disposed || more.disabled) return;
      more.disabled = true;
      const type = {light: 'light', climate: 'thermostat', humidifier: 'humidifier'}[kind] || 'tile';
      let mounted = false;
      try {
        host.hidden = false;
        // The card is drawn with the house as this layer knows it now; renders keep it current.
        window.ChauffeurHaCards?.setStates?.(live.peek());
        mounted = !!await window.ChauffeurHaCards?.mountBuiltin(host, {
          id: widget.cardId, type, config: {type, entity: row.entity_id}, interactive: true, apiBase: base(),
        });
      } catch { /* Our controls remain available when HA's frontend is away. */ }
      finally { more.disabled = false; }
      if (widget.disposed) { window.ChauffeurHaCards?.unmount(widget.cardId); return; }
      host.hidden = !mounted; widget.hosted = mounted;
      if (!mounted) { host.replaceChildren(); live.openRing(row); }
    });
  }
  // A poll that changes nothing in this room leaves its rows alone, so a press that spans
  // the poll still lands and focus stays put (review M2).
  function render() {
    if (!room) return;
    // Read without a copy (review M3); HA's own cards hear the house only while one is up.
    const rows = live.devices(room.area_id, room), states = live.peek();
    if ([...widgets.values()].some(widget => widget.hosted)) window.ChauffeurHaCards?.setStates(states);
    const key = JSON.stringify([room.area_id, rows.map(row => [row.device_id, row.offered, row.label,
      states[row.entity_id]?.state, states[row.entity_id]?.attributes,
      row.accessories?.map(a => [a, states[a.entity_id]])])]);
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
      stop(widget); widget.node.remove(); widgets.delete(id);
    }
    for (const row of rows) {
      const state = states[row.entity_id], attrs = state?.attributes || {};
      const shape = deviceControlShape(row, state, live.state);
      let widget = widgets.get(row.device_id);
      if (!widget || shape !== widget.shape || !widget.actions.update) {
        const node = widget?.node || element('section');
        if (widget) stop(widget);
        node.className = 'twin-room-device'; node.dataset.deviceId = row.device_id; node.dataset.kind = kindOf(row).id;
        const name = element('h3'), status = element('p');
        const actions = deviceActions(row, state, live.control, {getState: () => live.state(row.entity_id), getEntityState: live.state});
        node.replaceChildren(name, status, actions);
        widget = {node, name, status, actions, shape}; widgets.set(row.device_id, widget);
        addMore(widget, row);
      }
      const {node, name, status, actions} = widget;
      name.textContent = row.name; status.textContent = row.label; actions.update?.(state);
      // The status line says the room's temperature and the setpoint (both ends of a range).
      if (row.kind === 'climate') status.textContent = `${row.label} · Current ${attrs.current_temperature ?? '—'} · Setpoint ${attrs.temperature
        ?? (attrs.target_temp_low != null ? `${attrs.target_temp_low}–${attrs.target_temp_high}` : '—')}`;
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
      if (!next?.area_id && !next?.yard) { hide(); return; }
      room = next; shown = null; title.textContent = room.name || 'Room'; panel.hidden = false; render();
    },
    close: hide,
    stop() { unsubscribe(); clear(); panel.remove(); },
  };
}
