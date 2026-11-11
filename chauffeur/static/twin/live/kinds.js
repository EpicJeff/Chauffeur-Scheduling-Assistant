import { lightControls } from './controls/light.js';

const registrations = new Map();

export function registerKind(kind) {
  registrations.set(kind.id, kind);
  return kind;
}

export function kindOf(row) {
  return [...registrations.values()].reverse().find(kind => kind.id !== 'other' && kind.match(row))
    || registrations.get(row.kind) || registrations.get('other');
}

const CONTACTS = ['door', 'window', 'opening', 'garage_door'];
const UNSAFE = { unlock: 'Unlock', open: 'Open', open_cover: 'Open', alarm_disarm: 'Disarm' };
export async function confirmUnsafe(name, service, row) {
  const label = row && kindOf(row).unsafe?.[service] || UNSAFE[service];
  return !label || !!await window.promptConfirm(`${label} ${name}?`, 'Are you sure?', label, 'Cancel');
}

export function stateLabel(kind, state, attributes) {
  const attrs = attributes || {}, value = String(state ?? 'unknown');
  const contact = kind === 'sensor' && CONTACTS.includes(attrs.device_class) && ['on', 'off'].includes(value);
  return contact ? (value === 'on' ? 'open' : 'closed')
    : value + (kind === 'sensor' && attrs.unit_of_measurement ? ` ${attrs.unit_of_measurement}` : '');
}

function look(kind, state) {
  const attrs = state?.attributes || {}, value = String(state?.state ?? 'unknown');
  if (['unknown', 'unavailable'].includes(value)) return 'unavailable';
  const attention = kind === 'lock' && ['unlocked', 'unlocking', 'open', 'opening', 'jammed'].includes(value)
    || kind === 'garage' && ['open', 'opening'].includes(value)
    || kind === 'alarm' && ['triggered', 'pending', 'arming'].includes(value)
    || kind === 'sensor' && [...CONTACTS, 'smoke', 'moisture', 'gas'].includes(attrs.device_class) && value === 'on';
  const off = ['off', 'closed', 'locked', 'idle', 'standby'].includes(value) || kind === 'alarm' && value === 'disarmed';
  return attention ? 'attention' : off ? 'off' : 'on';
}

function drawing(ctx) {
  return {
    line(points) { ctx.beginPath(); points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.stroke(); },
    circle(x, y, r) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke(); },
  };
}

function lightIcon(ctx) {
  const { line, circle } = drawing(ctx);
  circle(48, 39, 17); line([[38, 55], [39, 65], [57, 65], [58, 55]]); line([[41, 73], [55, 73]]);
}
function lockIcon(ctx) {
  const { line } = drawing(ctx);
  ctx.strokeRect(29, 43, 38, 29); ctx.beginPath(); ctx.arc(48, 43, 13, Math.PI, 0); ctx.stroke();
  line([[48, 54], [48, 62]]);
}
function garageIcon(ctx) {
  const { line } = drawing(ctx);
  line([[24, 69], [24, 32], [72, 32], [72, 69]]);
  for (const y of [42, 52, 62]) line([[30, y], [66, y]]);
}
const blindsIcon = garageIcon;
function switchIcon(ctx) {
  const { line } = drawing(ctx);
  ctx.beginPath(); ctx.arc(48, 49, 23, -Math.PI * .32, Math.PI * 1.32); ctx.stroke(); line([[48, 22], [48, 46]]);
}
const outletIcon = switchIcon;
function fanIcon(ctx) {
  const { circle } = drawing(ctx);
  circle(48, 48, 5);
  for (let i = 0; i < 3; i++) {
    ctx.save(); ctx.translate(48, 48); ctx.rotate(i * Math.PI * 2 / 3);
    ctx.beginPath(); ctx.ellipse(0, -18, 11, 16, .3, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
  }
}
function climateIcon(ctx) {
  const { line, circle } = drawing(ctx);
  circle(48, 64, 10); line([[43, 54], [43, 26], [53, 26], [53, 54]]);
}
function sensorIcon(ctx) {
  const { line, circle } = drawing(ctx);
  circle(48, 48, 25); line([[31, 49], [39, 49], [44, 36], [51, 61], [57, 49], [65, 49]]);
}
function cameraIcon(ctx) {
  const { circle } = drawing(ctx);
  ctx.strokeRect(23, 33, 50, 35); circle(48, 50, 12);
}
function mediaIcon(ctx) {
  const { line } = drawing(ctx);
  line([[38, 27], [66, 48], [38, 69], [38, 27]]);
}
function alarmIcon(ctx) {
  const { line } = drawing(ctx);
  line([[48, 22], [72, 32], [67, 60], [48, 74], [29, 60], [24, 32], [48, 22]]);
}
function otherIcon(ctx) {
  const { line, circle } = drawing(ctx);
  circle(48, 48, 24); line([[48, 37], [48, 59]]); line([[37, 48], [59, 48]]);
}

const element = (tag, text) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
};

function legacyPanel(draw) {
  return ({row, state, control, compact = false}) => {
    const actions = element('div'); actions.className = 'twin-device-actions';
    const button = (label, service, data = {}) => {
      const node = element('button', label); node.type = 'button';
      node.addEventListener('click', async () => {
        if (!control.confirmsUnsafe && !await confirmUnsafe(row.name, service, row)) return;
        node.disabled = true;
        try { await control(row.entity_id, service, data); }
        finally { node.disabled = false; }
      });
      actions.append(node); return node;
    };
    if (row.offered) draw?.({row, state, attrs: state?.attributes || {}, compact, button});
    return actions;
  };
}
const fanPanel = legacyPanel(({row, state, compact, button}) => {
  if (compact) return;
  const toggle = button(state?.state === 'on' ? 'On' : 'Off', 'toggle');
  toggle.setAttribute('role', 'switch'); toggle.setAttribute('aria-label', row.name);
  toggle.setAttribute('aria-checked', String(state?.state === 'on'));
});
const lockPanel = legacyPanel(({button}) => { button('Lock', 'lock'); button('Unlock', 'unlock'); });
const garagePanel = legacyPanel(({button}) => { button('Open', 'open_cover'); button('Close', 'close_cover'); });
const alarmPanel = legacyPanel(({row, button}) => {
  if (!row.entity_id.startsWith('alarm_control_panel.')) return;
  button('Arm home', 'alarm_arm_home'); button('Arm away', 'alarm_arm_away'); button('Disarm', 'alarm_disarm');
});
const climatePanel = legacyPanel(({attrs, compact, button}) => {
  if (compact || !Number.isFinite(attrs.temperature)) return;
  const step = Number(attrs.target_temp_step) > 0 ? Number(attrs.target_temp_step) : 1;
  for (const [label, delta] of [['Lower', -step], ['Raise', step]]) {
    const temperature = Math.round((attrs.temperature + delta) * 1000) / 1000;
    const node = button(label, 'set_temperature', {temperature});
    node.disabled = temperature < (attrs.min_temp ?? -Infinity) || temperature > (attrs.max_temp ?? Infinity);
  }
});
const emptyPanel = legacyPanel();

for (const [id, icon, panel, quick, unsafe] of [
  ['light', lightIcon, lightControls, 'toggle'], ['switch', switchIcon, lightControls, 'toggle'],
  ['outlet', outletIcon, lightControls, 'toggle'], ['fan', fanIcon, fanPanel, 'toggle'],
  ['lock', lockIcon, lockPanel, null, {unlock: 'Unlock'}],
  ['garage', garageIcon, garagePanel, null, {open: 'Open', open_cover: 'Open'}], ['blinds', blindsIcon, emptyPanel],
  ['climate', climateIcon, climatePanel], ['sensor', sensorIcon, emptyPanel],
  ['camera', cameraIcon, emptyPanel], ['media', mediaIcon, emptyPanel],
  ['alarm', alarmIcon, alarmPanel, null, {alarm_disarm: 'Disarm'}], ['other', otherIcon, emptyPanel],
]) {
  registerKind({id, icon, quick: quick || null, unsafe: unsafe || {},
    match: row => id === 'alarm' ? row.kind === 'alarm' || String(row.entity_id || '').startsWith('alarm_control_panel.') : row.kind === id,
    look: state => look(id, state), ring: panel === lightControls ? lightControls : null, panel});
}
