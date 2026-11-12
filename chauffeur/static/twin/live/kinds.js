import { lightControls } from './controls/light.js';
import { climateControls } from './controls/climate.js';
import { fanControls } from './controls/fan.js';
import { coverControls } from './controls/cover.js';
import { mediaControls } from './controls/media.js';
import { lockControls } from './controls/lock.js';
import { alarmControls } from './controls/alarm.js';
import { vacuumControls } from './controls/vacuum.js';
import { humidifierControls } from './controls/humidifier.js';
import { waterHeaterControls } from './controls/water_heater.js';
import { sceneControls } from './controls/scene.js';
import { cameraControls } from './controls/camera.js';

const registrations = new Map();
const DOMAINS = {alarm: 'alarm_control_panel', vacuum: 'vacuum', humidifier: 'humidifier',
  water_heater: 'water_heater', scene: 'scene', script: 'script'};

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
// The question a call needs before it goes, or null. A kind's entry is a label, or a
// function of the call's data and the confirmed state (a garage raised by position is
// an Open: review H1).
export function unsafeLabel(row, service, data = {}, state = null) {
  const entry = row ? kindOf(row).unsafe?.[service] : UNSAFE[service];
  return typeof entry === 'function' ? entry(data || {}, state) || null : entry || null;
}
export async function confirmUnsafe(name, service, row, data = {}, state = null) {
  const label = unsafeLabel(row, service, data, state);
  return !label || !!await window.promptConfirm(`${label} ${name}?`, 'Are you sure?', label, 'Cancel');
}
// A garage door going up by any path is an Open: a position above the confirmed one
// (an unknown position counts as closed).
const raises = (data, state) => {
  const to = Number(data.position), from = Number(state?.attributes?.current_position);
  return Number.isFinite(to) && to > (Number.isFinite(from) ? from : 0) ? 'Open' : null;
};

export function stateLabel(kind, state, attributes) {
  const attrs = attributes || {}, value = String(state ?? 'unknown');
  const contact = kind === 'sensor' && CONTACTS.includes(attrs.device_class) && ['on', 'off'].includes(value);
  return contact ? (value === 'on' ? 'open' : 'closed')
    : value + (kind === 'sensor' && attrs.unit_of_measurement ? ` ${attrs.unit_of_measurement}` : '');
}

function look(kind, state) {
  const attrs = state?.attributes || {}, value = String(state?.state ?? 'unknown');
  if (['unknown', 'unavailable'].includes(value)) return 'unavailable';
  const attention = kind === 'lock' && ['unlocked', 'locking', 'unlocking', 'open', 'opening', 'jammed'].includes(value)
    || kind === 'garage' && ['open', 'opening'].includes(value)
    || kind === 'alarm' && ['triggered', 'pending', 'arming'].includes(value)
    || kind === 'sensor' && [...CONTACTS, 'smoke', 'moisture', 'gas'].includes(attrs.device_class) && value === 'on';
  const off = ['off', 'closed', 'idle', 'standby'].includes(value) || value === 'locked' && kind !== 'lock'
    || kind === 'media' && value === 'paused' || kind === 'alarm' && value === 'disarmed';
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
        if (!control.confirmsUnsafe && !await confirmUnsafe(row.name, service, row, data, state)) return;
        node.disabled = true;
        try { await control(row.entity_id, service, data); }
        finally { node.disabled = false; }
      });
      actions.append(node); return node;
    };
    if (row.offered) draw?.({row, state, attrs: state?.attributes || {}, compact, button});
    actions.update = () => {};
    return actions;
  };
}
const emptyPanel = legacyPanel();

for (const [id, icon, panel, quick, unsafe] of [
  ['light', lightIcon, lightControls, 'toggle'], ['switch', switchIcon, lightControls, 'toggle'],
  ['outlet', outletIcon, lightControls, 'toggle'], ['fan', fanIcon, fanControls, 'toggle'],
  ['lock', lockIcon, lockControls, null, {unlock: 'Unlock'}],
  ['garage', garageIcon, coverControls, null, {open: 'Open', open_cover: 'Open', set_cover_position: raises}],
  ['blinds', blindsIcon, coverControls],
  ['climate', climateIcon, climateControls], ['sensor', sensorIcon, emptyPanel],
  ['camera', cameraIcon, cameraControls], ['media', mediaIcon, mediaControls],
  ['alarm', alarmIcon, alarmControls, null, {alarm_disarm: 'Disarm'}], ['other', otherIcon, emptyPanel],
  ['vacuum', otherIcon, vacuumControls], ['humidifier', otherIcon, humidifierControls],
  ['water_heater', otherIcon, waterHeaterControls], ['scene', otherIcon, sceneControls, 'turn_on'],
  ['script', otherIcon, sceneControls, 'turn_on'],
]) {
  registerKind({id, icon, quick: quick || null, unsafe: unsafe || {},
    match: row => row.kind === id || !!DOMAINS[id] && String(row.entity_id || '').startsWith(DOMAINS[id] + '.'),
    look: state => look(id, state), ring: panel !== emptyPanel ? panel : null, panel});
}
