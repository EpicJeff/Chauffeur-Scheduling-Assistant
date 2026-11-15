import * as THREE from 'three';
import { groundAt, buildingGround } from '../twin_ground.js';
import { aimTool } from './aim_tool.js';
import { createLineFixtureTool, facingOptions, areaOutline, screenRay, fixtureStroke, FIXTURE_COLOR } from './line_fixture_tool.js';
import { fixtureReference, resolveFixture } from '../live/emitters.js';
import { facingNormal } from '../live/fixture_glow.js';
import { report as reportError } from './api.js';

const FT = .3048;
const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
const entities = device => [...new Set([device.entity_id, ...(device.entities || []).map(e => typeof e === 'string' ? e : e.entity_id),
  ...(device.controls || []).map(e => e.entity_id), ...(device.accessories || []).map(e => e.entity_id)].filter(e => /^(light|switch|media_player)\./.test(e)))];
const numeric = (value, low = -1e5, high = 1e5) => {
  if (!String(value).trim() || !Number.isFinite(Number(value)) || Number(value) < low || Number(value) > high) throw new Error(`Choose a number from ${low} to ${high}.`);
  return Number(value);
};
function field(root, label, value, save, { locked = false, low, high, step = 'any', type = 'number' } = {}) {
  const wrap = element('label', label), input = element('input'); input.type = type; input.step = step;
  input.value = typeof value === 'number' ? Math.round(value * 100) / 100 : value; input.disabled = locked; if (locked) input.dataset.fixtureLocked = '';
  if (low !== undefined) input.min = low; if (high !== undefined) input.max = high;
  input.setAttribute('aria-label', label); wrap.append(input); root.append(wrap);
  input.addEventListener('change', () => Promise.resolve().then(() => !input.disabled && save(input.value)).catch(reportError)); return input;
}
function actions(root) {
  const node = element('div'); node.className = 'editor-material-actions'; root.append(node); return node;
}
function button(root, text, action, locked) {
  const node = element('button', text); node.type = 'button'; node.disabled = locked;
  node.addEventListener('click', action); root.append(node); return node;
}

export function fixtureCard({ entity_id, getPlan, canEdit, op, onAdd, onMove, onAim, onReattach, report = reportError }) {
  const root = element('section'); root.dataset.fixtureEntity = entity_id;
  root.append(element('h3', `Fixtures · ${entity_id}`));
  let pending = Promise.resolve();
  const save = work => { pending = pending.then(() => canEdit() && work()).catch(report); return pending; };
  field(root, 'Output (lm)', getPlan().light_fixtures_meta?.[entity_id]?.output_lm ?? 503,
    v => save(() => op({ op: 'set_light_output', entity_id, output_lm: numeric(v, 0, 1e6) })), { locked: !canEdit(), low: 0, high: 1e6 });
  const rows = getPlan().light_fixtures?.[entity_id] || [];
  if (!rows.length) root.append(element('p', 'No fixtures yet. This entity uses its device light.'));
  for (const f of rows) {
    const row = element('details'), summary = element('summary', `${f.shape[0].toUpperCase() + f.shape.slice(1)} · ${f.id.slice(-8)}${f.detached ? ' · detached' : ''}`);
    row.dataset.fixtureId = f.id; row.append(summary); root.append(row);
    const rowActions = element('div'); rowActions.className = 'editor-material-actions';
    const current = () => getPlan().light_fixtures?.[entity_id]?.find(r => r.id === f.id) || f;
    const change = delta => save(() => op({ op: 'update_light_fixture', entity_id, id: f.id, change: delta }));
    const choice = (name, value, options, apply) => {
      const label = element('label', name), select = element('select'); select.setAttribute('aria-label', name);
      for (const [v, text] of options) { const option = element('option', text); option.value = v; select.append(option); }
      select.value = value; select.disabled = !canEdit(); select.addEventListener('change', () => { if (canEdit()) apply(select.value); }); label.append(select); row.append(label); return select;
    };
    row.append(element('p', `Reference: ${f.ref}${f.ref === 'floor' ? ` · ${f.building} · ${f.level}` : ''}`));
    if (f.at) for (const [i, name] of ['East (ft)', 'North (ft)', 'Height (ft)'].entries()) {
      field(row, name, f.at[i], v => save(() => {
        const current = getPlan().light_fixtures?.[entity_id]?.find(r => r.id === f.id) || f;
        const at = [...current.at]; at[i] = numeric(v);
        return op({ op: 'update_light_fixture', entity_id, id: f.id, change: { at } });
      }), { locked: !canEdit() });
    }
    field(row, 'Share', f.share ?? '', v => change({ share: v.trim() ? numeric(v, 0, 1e6) : null }), { locked: !canEdit(), low: 0, high: 1e6 });
    row.append(element('p', 'Leave Share blank for automatic output sharing.'));
    if (f.shape === 'spot') {
      for (const [i, name] of ['Aim east (ft)', 'Aim north (ft)', 'Aim height (ft)'].entries()) field(row, name, f.aim[i], v => save(() => {
        const aim = [...(getPlan().light_fixtures?.[entity_id]?.find(r => r.id === f.id) || f).aim]; aim[i] = numeric(v);
        return op({ op: 'update_light_fixture', entity_id, id: f.id, change: { aim } });
      }), { locked: !canEdit() });
      field(row, 'Cone (degrees)', f.cone_deg ?? 90, v => change({ cone_deg: numeric(v, 10, 160) }), { locked: !canEdit(), low: 10, high: 160 });
      field(row, 'Softness', f.softness ?? .3, v => change({ softness: numeric(v, 0, 1) }), { locked: !canEdit(), low: 0, high: 1, step: '.05' });
      button(rowActions, 'Aim', () => { if (canEdit()) onAim?.(entity_id, f); }, !canEdit());
    }
    if (f.shape === 'line') {
      field(row, 'Width (in)', f.width_in ?? .5, v => change({ width_in: numeric(v, .25, 2) }), { locked: !canEdit(), low: .25, high: 2 });
      const select = choice('Facing', f.facing, facingOptions(f.snap?.host.kind, f.facing), v => change({ facing: v }));
      if (f.snap?.host.kind === 'step' && f.facing !== 'out') [...select.children].find(option => option.value === f.facing).disabled = true;
      if (f.snap) {
        const snapChange = apply => save(() => { const snap = structuredClone(current().snap); apply(snap); return op({ op:'update_light_fixture', entity_id, id:f.id, change:{snap, ...(snap.host.kind === 'step' ? {facing:'out'} : {})} }); });
        choice('Snap host kind', f.snap.host.kind, [['retaining_wall','Retaining wall cap'],['hardscape','Patio, path or deck'],['step','Step nose'],['wall','Wall top'],['fence','Fence top']], v => snapChange(s => s.host.kind = v));
        field(row, 'Snap host id', f.snap.host.id, v => { if (!v.trim()) throw new Error('Choose a host id.'); return snapChange(s => s.host.id = v.trim()); }, { type:'text', locked:!canEdit() });
        for (const end of ['from','to']) for (const [i, name] of ['east','north'].entries()) field(row, `Edge ${end} ${name} (ft)`, f.snap.edge[end][i], v => snapChange(s => s.edge[end][i] = numeric(v)), {locked:!canEdit()});
        for (const key of ['t0','t1']) field(row, key, f.snap[key], v => snapChange(s => s[key] = numeric(v,0,1)), {locked:!canEdit(),low:0,high:1});
        button(rowActions, f.detached ? 'Reattach' : 'Pick another edge', () => { if (canEdit()) onReattach?.(entity_id, current()); }, !canEdit());
        if (f.detached) button(rowActions, 'Keep as drawn', () => save(() => {
          const fixture = current(), plan = getPlan(), drawn = resolveFixture(fixture, plan);
          const free = resolveFixture({...fixture, snap:null, ref:'absolute'}, plan);
          // Preserve the current lift and host stand-off; the free resolver still applies its own vertical offset.
          const path = fixture.path.map((p,i) => p.map((v,k) => v + drawn.path[i][k] - free.path[i][k]));
          // A free run faces right of its drawn direction; keep the side the host gave it.
          const flip = ['out','in'].includes(fixture.facing) && drawn.normal && free.normal && drawn.normal.reduce((sum,v,k) => sum + v * free.normal[k], 0) < 0;
          return op({op:'update_light_fixture',entity_id,id:f.id,change:{snap:null,ref:'absolute',path,...(flip ? {facing:fixture.facing === 'out' ? 'in' : 'out'} : {})}});
        }), !canEdit());
      } else {
        for (const [j, point] of f.path.entries()) for (const [i, name] of ['east','north','height'].entries()) field(row, `Point ${j + 1} ${name} (ft)`, point[i], v => save(() => {
          const path = structuredClone(current().path); path[j][i] = numeric(v); return op({op:'update_light_fixture',entity_id,id:f.id,change:{path}});
        }), {locked:!canEdit()});
        button(rowActions, 'Add path point', () => save(() => {
          const path = structuredClone(current().path), a = path.at(-2), b = path.at(-1); path.push(b.map((v,i) => v + v - a[i]));
          return op({op:'update_light_fixture',entity_id,id:f.id,change:{path}});
        }), !canEdit() || f.path.length >= 64);
        button(rowActions, 'Remove last point', () => change({path:current().path.slice(0,-1)}), !canEdit() || f.path.length <= 2);
      }
      if (f.detached) row.append(element('p', `Detached: ${f.detached_reason || f.orphan_reason || 'this run no longer follows its edge.'} Reattach this run or keep its last path as drawn.`));
    }
    if (f.shape === 'area') {
      for (const [i, name] of ['Width (ft)','Height of panel (ft)'].entries()) field(row, name, f.size_ft[i], v => save(() => {
        const size_ft = [...current().size_ft]; size_ft[i] = numeric(v,.001); return op({op:'update_light_fixture',entity_id,id:f.id,change:{size_ft}});
      }), {locked:!canEdit(),low:.001});
      choice('Facing', Array.isArray(f.facing) ? 'normal' : f.facing, [['down','Down'],['out','Out'],['up','Up'],['normal','Custom normal']], v => change({facing:v === 'normal' ? facingNormal(current().facing) : v}));
      for (const [i, name] of ['Normal east','Normal north','Normal up'].entries()) field(row, name, facingNormal(f.facing)[i], v => save(() => {
        const facing = facingNormal(current().facing); facing[i] = numeric(v,-1,1);
        if (Math.hypot(...facing) <= 1e-8) throw new Error('Choose a nonzero facing normal.'); return op({op:'update_light_fixture',entity_id,id:f.id,change:{facing}});
      }), {locked:!canEdit(),low:-1,high:1});
      field(row, 'Rotation (degrees)', f.rotation_deg ?? 0, v => change({rotation_deg:numeric(v)}), {locked:!canEdit()});
    }
    if (f.orphaned) row.append(element('p', f.orphan_reason || 'The floor reference is missing.'));
    button(rowActions, f.shape === 'line' ? 'Redraw' : 'Move', () => { if (canEdit()) onMove?.(entity_id, current()); }, !canEdit());
    button(rowActions, 'Duplicate', () => save(() => {
      const copy = structuredClone(current());
      for (const key of ['id','orphaned','orphan_reason','detached']) delete copy[key];
      return op({ op: 'add_light_fixture', entity_id, fixture: copy });
    }), !canEdit());
    button(rowActions, 'Delete', () => save(async () => {
      if (await window.promptConfirm('Delete this fixture?', 'Undo restores the fixture.', 'Delete', 'Cancel') && canEdit())
        await op({ op: 'delete_light_fixture', entity_id, id: f.id });
    }), !canEdit());
    row.append(rowActions);
  }
  const addActions = actions(root);
  for (const shape of ['point', 'spot']) button(addActions, `Add ${shape} fixtures`, () => { if (canEdit()) onAdd?.(entity_id, shape); }, !canEdit());
  for (const shape of ['line', 'area']) button(addActions, `Add ${shape} fixture`, () => { if (canEdit()) onAdd?.(entity_id, shape); }, !canEdit());
  return root;
}

export function cameraView(plan, marker) {
  const saved = plan.camera_views?.[marker.entity_id];
  if (saved) return { at: [...marker.at], aim: [...saved.aim], fov_deg: saved.fov_deg };
  const at = [...marker.at], angle = (marker.facing_deg ?? marker.orientation ?? 0) * Math.PI / 180;
  return { at, aim: [at[0] + 20 * Math.cos(angle), at[1] + 20 * Math.sin(angle), at[2]], fov_deg: 90 };
}

export function createFixtureEditor({ view, tools, library, getPlan, op, canEdit, signal, prepare = () => {}, report = reportError, getCameraMarker }) {
  const canvas = view.renderer3.domElement, root = new THREE.Group(), el = id => document.getElementById(id);
  const ray = new THREE.Raycaster(); ray.params.Line.threshold = .08; view.scene.add(root); root.name = 'editor-light-fixtures';
  let mode = null, press = null, aiming = null, slider = null, cardDevice = null, cardKey = null, signature = null;
  function height(f, at) {
    if (f.ref === 'ground') return groundAt(getPlan(), ...at);
    const b = getPlan().buildings?.find(b => b.id === f.building);
    const level = b?.levels.find(l => l.id === f.level);
    return f.ref === 'floor' && level ? (b.base || 0) + buildingGround(getPlan(), b) + level.elevation : 0;
  }
  const absolute = (f, p) => [p[0], p[1], p[2] + height(f, p)];
  function surface(event, standOff = false) {
    const hit = library.surfaceAt(event);
    if (hit) {
      const b = hit.building, a = (b.rotation || 0) * Math.PI / 180, p = b.position || [0, 0];
      let [x, y, z] = hit.point;
      let normal = [0,0,hit.surface === 'ceiling' ? -1 : 1];
      if (standOff && hit.kind === 'wall' && hit.piece && hit.side) {
        const [dx, dy] = hit.piece.to.map((v, i) => v - hit.piece.from[i]), length = Math.hypot(dx, dy);
        const offset = (hit.piece.thickness / 2 + 1 / 12) * (hit.side === 'left' ? 1 : -1);
        if (length) { x -= dy / length * offset; y += dx / length * offset; }
        const sign = hit.side === 'left' ? 1 : -1;
        normal = length ? [sign * (-dy * Math.cos(a) - dx * Math.sin(a)) / length, sign * (-dy * Math.sin(a) + dx * Math.cos(a)) / length, 0] : normal;
      } else if (standOff && hit.kind === 'room') z += (hit.surface === 'ceiling' ? -1 : 1) / 12;
      return { at: [p[0] + x * Math.cos(a) - y * Math.sin(a), p[1] + x * Math.sin(a) + y * Math.cos(a),
        z + (b.base || 0) + buildingGround(getPlan(), b)], building: b.id, level: hit.level, normal,
        ceiling: hit.kind === 'room' && hit.surface === 'ceiling', floor: (b.levels.find(l => l.id === hit.level)?.elevation || 0)
          + (hit.room?.floor_offset_ft || 0) + (b.base || 0) + buildingGround(getPlan(), b) };
    }
    const p = library.ground(event); return p && { at: [...p, groundAt(getPlan(), ...p)], ground: true, normal:[0,0,1] };
  }
  const shapeTool = createLineFixtureTool({ view, getPlan, surface, canEdit, report, host: el('device-tools'), onDone: cancel,
    encode(fixture, hit) {
      const context = hit.ground ? {ref:'ground'} : {ref:'floor',building:hit.building,level:hit.level};
      const local = p => [p[0],p[1],p[2] - height(context,p)];
      return {...fixture,...context,...(fixture.path ? {path:fixture.path.map(local)} : {at:local(fixture.at)})};
    },
    commit: (active, fixture) => {
      if (!canEdit()) return false;
      return op(active.fixture ? {op:'update_light_fixture',entity_id:active.entity_id,id:active.fixture.id,change:fixture}
        : {op:'add_light_fixture',entity_id:active.entity_id,fixture});
    } });
  function release() {
    if (!press) return; view.controls.enabled = press.enabled;
    if (canvas.hasPointerCapture(press.pointer)) canvas.releasePointerCapture(press.pointer); press = null;
  }
  function cancel() {
    release(); aiming?.stop(); aiming = null; shapeTool.stop(); shapeTool.preview.removeFromParent(); slider?.parentElement.remove(); slider = null; mode = null;
    el('device-tools').hidden = true; canvas.style.cursor = ''; el('device-cancel').textContent = 'Cancel placement';
  }
  function start(next, text) {
    cancel(); prepare(); tools.setTool('select'); mode = next;
    el('device-note').textContent = text; el('device-tools').hidden = false; el('device-cancel').textContent = 'Done'; canvas.style.cursor = 'crosshair';
  }
  function add(entity_id, shape) {
    if (canEdit() && ['point', 'spot'].includes(shape)) start({ kind: 'add', entity_id, shape }, `Click to add ${shape} fixtures. Done ends placement; Escape cancels.`);
    else if (canEdit() && ['line','area'].includes(shape)) startShape(entity_id, shape === 'area' ? 'area' : 'draw');
  }
  function startShape(entity_id, kind, fixture) {
    start({kind:'shape'}, kind === 'area' ? 'Drag a rectangle, choose its facing, then Finish. Escape cancels the rectangle; Done saves a complete rectangle and ends the mode.'
      : 'Draw points or Snap to edge; drag along an edge for a shorter run. Enter or Finish completes a drawing; Backspace removes a point. Escape cancels the gesture; Done saves a drawing with at least two points and ends the mode.');
    shapeTool.start({entity_id,kind,fixture});
    root.add(shapeTool.preview);
  }
  function reattach(entity_id, f) { if (canEdit()) startShape(entity_id, 'snap', f); }
  function move(entity_id, f) {
    if (!canEdit()) return;
    if (f.shape === 'line') startShape(entity_id, f.snap ? 'snap' : 'draw', f);
    else start({ kind: 'move', entity_id, f }, 'Click a surface to move this fixture.');
  }
  function startAim(at, aim, cone, commit, camera = false) {
    start({ kind: 'aim' }, 'Drag to aim on the ground or a wall. Done ends aiming; Escape cancels the current drag.');
    aiming = aimTool({ at, aim, cone_deg: cone, onCommit: async value => { if (canEdit()) await commit(value); } }); root.add(aiming.preview);
    slider = field(el('device-tools'), camera ? 'Field of view (degrees)' : 'Cone (degrees)', cone, () => {
      if (canEdit()) aiming?.commit().catch(report);
    }, { type: 'range', low: 10, high: 160, step: 1 });
    slider.addEventListener('input', () => { if (canEdit()) aiming?.cone(Number(slider.value)); });
  }
  function aim(entity_id, f) {
    if (!canEdit()) return;
    startAim(absolute(f, f.at), absolute(f, f.aim), f.cone_deg ?? 90, value => {
      const p = value.aim; return op({ op: 'update_light_fixture', entity_id, id: f.id,
        change: { aim: [p[0], p[1], p[2] - height(f, p)], cone_deg: value.cone_deg } });
    });
  }
  function aimCamera(marker) {
    if (!canEdit()) return;
    const current = cameraView(getPlan(), marker);
    startAim(current.at, current.aim, current.fov_deg, value => op({ op: 'set_camera_view', entity_id: marker.entity_id,
      view: { aim: value.aim, fov_deg: value.cone_deg } }), true);
  }
  function drawFixtures(host, device) {
    for (const entity_id of entities(device)) host.append(fixtureCard({ entity_id, getPlan, canEdit, op, onAdd: add, onMove: move, onAim: aim, onReattach: reattach, report }));
    if (device.kind === 'camera' || device.entity_id?.startsWith('camera.')) {
      const marker = getCameraMarker?.(device);
      if (marker) {
        const row = element('section'); row.append(element('h3', 'Camera view'));
        const value = cameraView(getPlan(), marker); row.append(element('p', `Aim: ${value.aim.map(n => Math.round(n * 100) / 100).join(', ')} ft · Field of view: ${value.fov_deg}°`));
        button(actions(row), 'Aim camera', () => { const current = getCameraMarker?.(device); if (current) aimCamera(current); }, !canEdit()); host.append(row);
      } else host.append(element('p', 'Place this camera to set its view.'));
    }
  }
  function deviceLink(host, device) {
    const camera = device.kind === 'camera' || device.entity_id?.startsWith('camera.');
    if (!camera && !entities(device).length) return;
    const open = button(host, camera ? 'Fixtures and camera view' : 'Fixtures', () => showDevice(device), false); open.dataset.fixtureBrowse = '';
  }
  function showDevice(device, id = null) {
    tools.select(null); cardDevice = device; cardKey = null; refreshCard();
    const row = id && [...el('piece-card').querySelectorAll('[data-fixture-id]')].find(r => r.dataset.fixtureId === id);
    if (row) { row.open = true; row.scrollIntoView({ block: 'nearest' }); }
  }
  function releaseCard() {
    cardDevice = null; cardKey = null; delete el('piece-card').dataset.fixtureCard;
  }
  el('piece-card').addEventListener('fixturecardrelease', releaseCard, { signal });
  function refreshCard() {
    if (!cardDevice) return;
    const host = el('piece-card');
    if (host.dataset.stairDraft || cardKey !== null && !host.dataset.fixtureCard) { releaseCard(); return; }
    const key = JSON.stringify([getPlan().light_fixtures, getPlan().light_fixtures_meta, getPlan().camera_views, getPlan().buildings, getPlan().site?.devices, getPlan().site?.terraces, canEdit()]);
    if (key === cardKey) return;
    const open = [...host.querySelectorAll('[data-fixture-id]')].filter(r => r.open).map(r => r.dataset.fixtureId);
    cardKey = key; host.replaceChildren(); host.dataset.fixtureCard = cardDevice.device_id; host.hidden = false;
    host.append(element('h3', cardDevice.name)); button(host, 'Close', () => { releaseCard(); host.hidden = true; }, false);
    drawFixtures(host, cardDevice);
    for (const row of host.querySelectorAll('[data-fixture-id]')) row.open = open.includes(row.dataset.fixtureId);
  }
  function pick(event) {
    screenRay(ray, view, event);
    draw(); root.updateMatrixWorld(true);
    const hit = ray.intersectObjects(root.children, true).find(h => h.object.visible && h.object.userData.fixtureId);
    if (!hit) return null;
    const piece = view.pick(event.clientX, event.clientY);
    if (piece?.point && ray.ray.origin.distanceTo(new THREE.Vector3(...piece.point)) < hit.distance - .2) return null;
    return hit.object.userData;
  }
  function pointerDown(event) {
    if (event.button !== 0) return false;
    const picked = !mode && pick(event);
    if (!mode && !picked || mode && !canEdit()) return false;
    if (mode?.kind === 'shape' && !shapeTool.down(event)) return false;
    press = { pointer: event.pointerId, x: event.clientX, y: event.clientY, enabled: view.controls.enabled, picked };
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); aiming?.begin(); return true;
  }
  function pointerMove(event) {
    if (mode?.kind === 'shape' && canEdit()) return shapeTool.move(event);
    if (!press || press.pointer !== event.pointerId) return false;
    if (aiming && canEdit()) { const p = surface(event); if (p) aiming.move(p.at); } return true;
  }
  async function finish(event, cancelled) {
    const p = press; release();
    if (p.picked) {
      if (!cancelled && Math.hypot(event.clientX - p.x, event.clientY - p.y) < 3) {
        const device = tools.haLink.state()?.devices?.find(d => entities(d).includes(p.picked.entity_id));
        showDevice(device || { device_id: p.picked.entity_id, entity_id: p.picked.entity_id, name: p.picked.entity_id }, p.picked.fixtureId);
      } return;
    }
    if (mode?.kind === 'shape') { await shapeTool.up(event, cancelled); return; }
    if (aiming) { if (!cancelled && canEdit()) { const hit = surface(event); if (hit) aiming.move(hit.at); } await aiming.end(cancelled || !canEdit()); return; }
    if (cancelled || !canEdit() || !mode || Math.hypot(event.clientX - p.x, event.clientY - p.y) >= 3) return;
    const hit = surface(event, true); if (!hit) return;
    const active = mode, ref = hit.ground ? 'ground' : 'floor', base = ref === 'ground' ? groundAt(getPlan(), ...hit.at) : height({ ref, building: hit.building, level: hit.level }, hit.at);
    if (active.kind === 'move') {
      const context = { ref, ...(ref === 'floor' ? { building: hit.building, level: hit.level } : {}) };
      const change = { ...context, at: [hit.at[0], hit.at[1], hit.at[2] - base] };
      if (active.f.aim) { const target = absolute(active.f, active.f.aim); change.aim = [target[0], target[1], target[2] - height(context, target)]; }
      await op({ op: 'update_light_fixture', entity_id: active.entity_id, id: active.f.id, change });
      if (mode === active) cancel(); return;
    }
    const f = { shape: active.shape, ref, at: [hit.at[0], hit.at[1], hit.at[2] - base],
      ...(ref === 'floor' ? { building: hit.building, level: hit.level } : {}) };
    if (f.shape === 'spot') Object.assign(f, { aim: hit.ceiling ? [f.at[0], f.at[1], hit.floor - base] : [f.at[0] + 20, f.at[1], f.at[2]], cone_deg: 90, softness: .3 });
    await op({ op: 'add_light_fixture', entity_id: active.entity_id, fixture: f });
  }
  function pointerUp(event, cancelled = false) {
    if (!press || press.pointer !== event.pointerId) return false;
    return finish(event, cancelled).catch(report);
  }
  function draw() {
    for (const mesh of root.children) if (mesh.userData.fixtureId) {
      const { building, level } = mesh.userData;
      mesh.visible = !building || view.groups?.levels[`${building}:${level}`]?.visible !== false;
    }
  }
  function refresh() {
    if (mode && !canEdit()) cancel(); refreshCard();
    const plan = getPlan(), next = JSON.stringify([plan.light_fixtures, plan.buildings, plan.site?.terraces]); if (signature === next) { draw(); return; } signature = next;
    for (const child of [...root.children]) if (child !== aiming?.preview && child !== shapeTool.preview) { child.geometry?.dispose(); child.material?.dispose(); child.removeFromParent(); }
    for (const [entity_id, rows] of Object.entries(getPlan().light_fixtures || {})) for (const f of rows) {
      const at = f.at || f.path?.[0]; if (!at) continue;
      const kind = f.snap?.host.kind, building = ['wall','step'].includes(kind) && plan.buildings?.find(b => b[kind === 'wall' ? 'walls' : 'stairs']?.some(p => p.id === f.snap.host.id));
      const piece = building && building[kind === 'wall' ? 'walls' : 'stairs'].find(p => p.id === f.snap.host.id);
      const toAbsolute = p => [p[0],p[1],p[2] + fixtureReference(plan, f, p)];
      let mesh;
      if (f.shape === 'line' || f.shape === 'area') {
        const points = f.shape === 'line' ? f.path.map(toAbsolute) : areaOutline({...f,at:toAbsolute(f.at)});
        mesh = fixtureStroke(points);
      } else {
        const p = toAbsolute(at); mesh = new THREE.Mesh(new THREE.SphereGeometry(.12, 10, 6), new THREE.MeshBasicMaterial({ color: FIXTURE_COLOR, toneMapped: false }));
        mesh.position.set(p[0] * FT, p[2] * FT, -p[1] * FT);
      }
      mesh.renderOrder = 21;
      mesh.userData = { fixtureId: f.id, entity_id, building: building?.id || (f.ref === 'floor' ? f.building : null), level: piece?.level || f.level }; root.add(mesh);
    }
    draw();
  }
  el('device-cancel').addEventListener('click', () => { if (mode?.kind === 'shape') { release(); shapeTool.done().catch(report); } else if (mode) cancel(); }, { signal });
  canvas.addEventListener('pointermove', event => { if (mode?.kind === 'shape' && !press) pointerMove(event); }, {signal});
  document.addEventListener('keydown', event => {
    if (!mode || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), #cc-alert-modal:not(.hidden), dialog[open]')) return;
    if (mode.kind === 'shape' && (event.key === 'Escape' || !event.target.closest?.('input,textarea,select,button,a,[contenteditable="true"]') && ['Enter','Backspace'].includes(event.key))) {
      if (event.key === 'Escape') release();
      if (!shapeTool.key(event) && event.key === 'Escape') cancel();
      event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    if (event.key === 'Escape') {
      if (aiming && press) { release(); aiming.end(true).catch(report); } else cancel();
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, { signal, capture: true });
  signal.addEventListener('abort', () => { cancel(); if (el('piece-card').dataset.fixtureCard) { releaseCard(); el('piece-card').hidden = true; } root.traverse(o => { o.geometry?.dispose(); o.material?.dispose(); }); root.removeFromParent(); }, { once: true });
  return { add, move, aim, aimCamera, drawFixtures, deviceLink, showDevice, pointerDown, pointerMove, pointerUp, cancel, refresh, draw, active: () => !!mode };
}
