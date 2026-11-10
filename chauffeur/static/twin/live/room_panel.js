const element = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
};

// The services that open the house up ask first. live.control asks for every surface
// (it carries confirmsUnsafe); a builder handed any other control asks itself, never twice.
const UNSAFE = { unlock: 'Unlock', open: 'Open', open_cover: 'Open', alarm_disarm: 'Disarm' };
export async function confirmUnsafe(name, service) {
  const label = UNSAFE[service];
  return !label || !!await window.promptConfirm(`${label} ${name}?`, 'Are you sure?', label, 'Cancel');
}

// One action builder for marker sheets and room rows; both use live.control.
export function deviceActions(row, state, control, { compact = false } = {}) {
  const actions = element('div'); actions.className = 'twin-device-actions';
  const attrs = state?.attributes || {};
  const button = (label, service, data = {}) => {
    const node = element('button', label); node.type = 'button';
    node.addEventListener('click', async () => {
      if (!control.confirmsUnsafe && !await confirmUnsafe(row.name, service)) return;
      node.disabled = true;
      try { await control(row.entity_id, service, data); }
      finally { node.disabled = false; }
    });
    actions.append(node); return node;
  };
  if (!row.offered) return actions;
  if (!compact && ['light', 'switch', 'outlet', 'fan'].includes(row.kind)) {
    const toggle = button(state?.state === 'on' ? 'On' : 'Off', 'toggle');
    toggle.setAttribute('role', 'switch'); toggle.setAttribute('aria-label', row.name);
    toggle.setAttribute('aria-checked', String(state?.state === 'on'));
    if (row.kind === 'light') {
      const label = element('label', 'Brightness');
      const slider = element('input'); slider.type = 'range'; slider.min = '0'; slider.max = '100'; slider.step = '1';
      slider.value = String(Math.round((attrs.brightness ?? 0) / 255 * 100));
      slider.setAttribute('aria-label', `${row.name} brightness`);
      slider.addEventListener('change', async () => {
        slider.disabled = true;
        try {
          if (!await control(row.entity_id, 'turn_on', { brightness_pct: Number(slider.value) }))
            slider.value = String(Math.round((attrs.brightness ?? 0) / 255 * 100));
        }
        finally { slider.disabled = false; }
      });
      label.append(slider); actions.append(label);
    }
  }
  if (row.kind === 'lock') { button('Lock', 'lock'); button('Unlock', 'unlock'); }
  if (row.kind === 'garage') { button('Open', 'open_cover'); button('Close', 'close_cover'); }
  if (row.entity_id.startsWith('alarm_control_panel.')) {
    button('Arm home', 'alarm_arm_home'); button('Arm away', 'alarm_arm_away'); button('Disarm', 'alarm_disarm');
  }
  if (!compact && row.kind === 'climate' && Number.isFinite(attrs.temperature)) {
    const step = Number(attrs.target_temp_step) > 0 ? Number(attrs.target_temp_step) : 1;
    for (const [label, delta] of [['Lower', -step], ['Raise', step]]) {
      const temperature = Math.round((attrs.temperature + delta) * 1000) / 1000;
      const node = button(label, 'set_temperature', { temperature });
      node.disabled = temperature < (attrs.min_temp ?? -Infinity) || temperature > (attrs.max_temp ?? Infinity);
    }
  }
  return actions;
}

export function mountRoomPanel(live) {
  const panel = element('aside'); panel.id = 'twin-room-panel'; panel.className = 'twin-device-sheet'; panel.hidden = true;
  panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-labelledby', 'twin-room-title');
  const header = element('header'), title = element('h2'); title.id = 'twin-room-title';
  const close = element('button', 'Close'); close.type = 'button';
  header.className = 'twin-device-actions'; header.append(title, close);
  const body = element('div'); body.className = 'twin-room-devices'; panel.append(header, body); document.body.append(panel);
  let room = null, shown = null;
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
    body.replaceChildren();
    for (const row of rows) {
      const node = element('section'); node.className = 'twin-room-device'; node.dataset.deviceId = row.device_id;
      const name = element('h3', row.name), status = element('p', row.label);
      const state = states[row.entity_id], attrs = state?.attributes || {};
      if (row.kind === 'climate') status.textContent = `${row.label} · Current ${attrs.current_temperature ?? '—'} · Setpoint ${attrs.temperature ?? '—'}`;
      node.append(name, status, deviceActions(row, state, live.control)); body.append(node);
    }
    if (!rows.length) body.append(element('p', 'No devices in this room.'));
    body.scrollTop = scroll;
    if (focusId) {
      const row = [...body.children].find(node => node.dataset.deviceId === focusId);
      [...(row?.querySelectorAll('button, input') || [])].find(node =>
        (node.getAttribute('aria-label') || node.textContent) === focusLabel)?.focus({ preventScroll: true });
    }
  }
  const unsubscribe = live.subscribe(render);
  function hide() { room = null; shown = null; panel.hidden = true; }
  close.addEventListener('click', hide);
  return {
    open(next) {
      if (!next?.area_id) { hide(); return; }
      room = next; shown = null; title.textContent = room.name || 'Room'; panel.hidden = false; render();
    },
    close: hide,
    stop() { unsubscribe(); panel.remove(); },
  };
}
