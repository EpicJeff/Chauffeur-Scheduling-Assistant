import * as THREE from 'three';
import { keepPlace } from './keep_place.js';
import { groundAt, buildingGround } from '../twin_ground.js';
import { aimTool } from './aim_tool.js';
import { createLineFixtureTool, facingOptions, areaOutline, screenRay, fixtureStroke, FIXTURE_COLOR } from './line_fixture_tool.js';
import { fixtureReference, resolveFixture } from '../live/emitters.js';
import { facingNormal } from '../live/fixture_glow.js';
import { report as reportError } from './api.js';
import { effectCard, effectLabels, effectShapes, effectPathOperation } from './effects.js';
import { DRAG_THRESHOLD_PX, HANDLE_HIT_PX } from './picking.js';
import { createGizmo } from './gizmo.js';
import { propertyPath } from './dock.js';

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

export function fixtureCard({ entity_id, getPlan, canEdit, op, onAdd, onAddEffect, onMove, onAim, onReattach, removeSelection, report = reportError }) {
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
    if (['point','line'].includes(f.shape)) field(row, 'Offset (ft)', f.offset_ft ?? 0, v => change({ offset_ft: numeric(v, -50, 50) }), { locked: !canEdit(), low: -50, high: 50 });
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
        choice('Snap host kind', f.snap.host.kind, [['retaining_wall','Retaining wall cap'],['hardscape','Patio, path or deck'],['step','Step nose'],['wall','Wall top'],['fence','Fence top'],['pool','Pool coping'],['spa','Spa rim']], v => snapChange(s => s.host.kind = v));
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
          const fixture = current(), path = structuredClone(fixture.path); path[j][i] = numeric(v);
          const anchors = fixture.anchors?.map((anchor,k) => k === j ? null : anchor);
          return op({op:'update_light_fixture',entity_id,id:f.id,change:{path,...(anchors ? {anchors} : {})}});
        }), {locked:!canEdit()});
        button(rowActions, 'Add path point', () => save(() => {
          const fixture = current(), path = structuredClone(fixture.path), a = path.at(-2), b = path.at(-1); path.push(b.map((v,i) => v + v - a[i]));
          return op({op:'update_light_fixture',entity_id,id:f.id,change:{path,...(fixture.anchors ? {anchors:[...fixture.anchors,null]} : {})}});
        }), !canEdit() || f.path.length >= 64);
        button(rowActions, 'Remove last point', () => save(() => {
          const fixture = current(); return op({op:'update_light_fixture',entity_id,id:f.id,change:{path:fixture.path.slice(0,-1),...(fixture.anchors ? {anchors:fixture.anchors.slice(0,-1)} : {})}});
        }), !canEdit() || f.path.length <= 2);
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
      const removed = removeSelection?.(f.id); if (removed) return removed;
      if (await window.promptConfirm('Delete this fixture?', 'Undo restores the fixture.', 'Delete', 'Cancel') && canEdit())
        await op({ op: 'delete_light_fixture', entity_id, id: f.id });
    }), !canEdit());
    row.append(rowActions);
  }
  const addActions = actions(root);
  for (const shape of ['point', 'spot']) button(addActions, `Add ${shape} fixtures`, () => { if (canEdit()) onAdd?.(entity_id, shape); }, !canEdit());
  for (const shape of ['line', 'area']) button(addActions, `Add ${shape} fixture`, () => { if (canEdit()) onAdd?.(entity_id, shape); }, !canEdit());
  if (onAddEffect) button(addActions, 'Add effect', () => onAddEffect(entity_id).catch(report), !canEdit());
  return root;
}

export function cameraView(plan, marker) {
  const saved = plan.camera_views?.[marker.entity_id];
  if (saved) return { at: [...marker.at], aim: [...saved.aim], fov_deg: saved.fov_deg };
  const at = [...marker.at], angle = (marker.facing_deg ?? marker.orientation ?? 0) * Math.PI / 180;
  return { at, aim: [at[0] + 20 * Math.cos(angle), at[1] + 20 * Math.sin(angle), at[2]], fov_deg: 90 };
}

export function createFixtureEditor({ view, tools, library, getPlan, op, canEdit, signal, prepare = () => {}, report = reportError, getCameraMarker, bindCancel = true, dock }) {
  const removeSelection = id => {
    const refs = tools.selectedMembers?.() || [];
    return refs.length > 1 && refs.some(r => r.pieceId === id) ? tools.deleteSelected() : null;
  };
  const canvas = view.renderer3.domElement, root = new THREE.Group(), el = id => document.getElementById(id);
  const ray = new THREE.Raycaster(); ray.params.Line.threshold = .08; view.scene.add(root); root.name = 'editor-light-fixtures';
  const handleLayer = element('div'); handleLayer.className = 'editor-handles'; canvas.parentElement.append(handleLayer);
  let mode = null, press = null, aiming = null, slider = null, cardDevice = null, cardEffect = null, cardKey = null, signature = null;
  let cardLight = null, pointHandles = [];
  let devicePath = [], deviceReturn = null;
  let deviceParent = false, deviceAnchor = false;
  const options = dock ? el('device-options') : el('device-tools');
  const gizmoLayer = element('div'); gizmoLayer.className = 'editor-handles'; canvas.parentElement.append(gizmoLayer);
  const gizmo = createGizmo({ view, layer: gizmoLayer, getPlan, canEdit: () => canEdit() && !mode,
    getSelection: () => cardLight && view.isPiecePickable?.({kind:'fixture',id:cardLight.id}) !== false ? { kind: 'light_fixture', ...cardLight } : null,
    getTool: () => ['move', 'rotate', 'scale'].find(id => el(`rail-${id}`).getAttribute('aria-pressed') === 'true'), op,
    onPreview(plan) {
      const fixture = cardLight && plan.light_fixtures?.[cardLight.entity_id]?.find(f => f.id === cardLight.id);
      const mesh = fixture && root.children.find(mesh => mesh.userData.fixtureId === fixture.id);
      if (mesh && fixture.at) {
        mesh.position.set(fixture.at[0] * FT, (fixture.at[2] + fixtureReference(plan, fixture, fixture.at) + (fixture.offset_ft || 0)) * FT, -fixture.at[1] * FT);
        view.refreshSelection?.();
      }
    } });
  const helpers = { element, numeric, field, actions, button };
  const effectPlacement = f => f;
  function effectFields(f) {
    const { width_in, ...placement } = f;
    return placement;
  }
  const effectEntities = device => [...new Set([device.entity_id, ...(device.entities || []).map(e => typeof e === 'string' ? e : e.entity_id),
    ...(device.controls || []).map(e => e.entity_id), ...(device.accessories || []).map(e => e.entity_id)].filter(e => /^(switch|light|input_boolean|fan|binary_sensor|climate|water_heater)\./.test(e)))];
  function height(f, at) {
    if (f.ref === 'ground') return groundAt(getPlan(), ...at);
    const b = getPlan().buildings?.find(b => b.id === f.building);
    const level = b?.levels.find(l => l.id === f.level);
    return f.ref === 'floor' && level ? (b.base || 0) + buildingGround(getPlan(), b) + level.elevation : 0;
  }
  const absolute = (f, p) => [p[0], p[1], p[2] + height(f, p)];
  function surface(event, standOff = false) {
    const hit = library.surfaceAt(event);
    // Pool and spa water answer the pick with no building: that is a ground placement.
    if (hit?.building) {
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
  const shapeTool = createLineFixtureTool({ view, getPlan, surface, canEdit, report, host: options,
    finishHost: dock ? el('device-tools') : null, onDone: cancel,
    encode(fixture, hit) {
      if (hit.snapped || fixture.anchors?.some(Boolean)) return {...fixture,ref:'absolute'};
      const context = hit.ground ? {ref:'ground'} : {ref:'floor',building:hit.building,level:hit.level};
      const local = p => [p[0],p[1],p[2] - height(context,p)];
      return {...fixture,...context,...(fixture.path ? {path:fixture.path.map(local)} : {at:local(fixture.at)})};
    },
    commit: (active, fixture) => {
      if (!canEdit()) return false;
      if ((fixture.snap || fixture.shape !== 'line') && active.fixture?.anchors) fixture = {...fixture,anchors:null};
      if (active.effectType) return op(active.fixture
        ? { op: 'update_effect_fixture', id: active.fixture.id, change: effectFields(fixture) }
        : { op: 'add_effect_fixture', fixture: { ...effectFields(fixture), type: active.effectType, ...(active.entity_id ? { entity: active.entity_id } : {}) } });
      return op(active.fixture ? {op:'update_light_fixture',entity_id:active.entity_id,id:active.fixture.id,change:fixture}
        : {op:'add_light_fixture',entity_id:active.entity_id,fixture});
    } });
  function release() {
    if (!press) return; view.controls.enabled = press.enabled;
    if (canvas.hasPointerCapture(press.pointer)) canvas.releasePointerCapture(press.pointer); press = null;
  }
  function cancel() {
    const point = press?.point;
    release(); aiming?.stop(); aiming = null; shapeTool.stop(); shapeTool.preview.removeFromParent(); slider?.parentElement.remove(); slider = null; mode = null;
    el('device-tools').hidden = true; canvas.style.cursor = ''; el('device-cancel').textContent = 'Cancel placement';
    dock?.properties.clear(options);
    if (point) previewPoint(point, point.fixture.path);
    drawHandles();
  }
  function start(next, text, short = text) {
    cancel(); prepare(); tools.setTool('select'); mode = next;
    el('device-note').textContent = dock ? short : text; el('device-tools').hidden = false; el('device-cancel').textContent = 'Done'; canvas.style.cursor = 'crosshair';
    if (dock) {
      el('device-options-note').textContent = text;
      dock.properties.render(options, { crumbs: [next.kind === 'aim' ? 'Aim' : 'Placement options'], tool: true, back: cancel });
    }
  }
  function add(entity_id, shape) {
    if (canEdit() && ['point', 'spot'].includes(shape)) start({ kind: 'add', entity_id, shape }, `Click to add ${shape} fixtures. Done ends placement; Escape cancels.`);
    else if (canEdit() && ['line','area'].includes(shape)) startShape(entity_id, shape === 'area' ? 'area' : 'draw');
  }
  async function addEffect(entity_id = null) {
    if (!canEdit()) return;
    if (!/^(switch|light|input_boolean|fan|binary_sensor|climate|water_heater)\./.test(entity_id || '')) entity_id = null;
    const type = await window.promptChoice('Add effect', 'Choose the effect to place.', Object.entries(effectLabels).map(([value, label]) => ({ value, label })));
    if (!type || !canEdit()) return;
    const shape = effectShapes[type].length > 1 ? await window.promptChoice(`${effectLabels[type]} shape`, type === 'fire' ? 'Place one flame or draw a row of flames.' : 'Place one nozzle or draw a run of nozzles.', [{ value: 'point', label: 'Point' }, { value: 'line', label: 'Line' }])
      : effectShapes[type][0];
    if (!shape || !canEdit()) return;
    if (shape === 'line') startShape(entity_id, 'draw', null, type);
    else start({ kind: 'add', entity_id, shape, effectType: type }, 'Click to add effects. Done ends placement; Escape cancels.');
  }
  function startShape(entity_id, kind, fixture, effectType = null) {
    start({kind:'shape'}, kind === 'area' ? 'Drag a rectangle, choose its facing, then Finish. Escape cancels the rectangle; Done saves a complete rectangle and ends the mode.'
      : 'Draw points or Snap to edge; drag along an edge for a shorter run. Enter or Finish completes a drawing; Backspace removes a point. Escape cancels the gesture; Done saves a drawing with at least two points and ends the mode.',
      kind === 'area' ? 'Drag a rectangle. Finish saves it; Done ends placement.' : 'Draw points or snap to an edge. Finish saves; Done ends placement.');
    shapeTool.start({entity_id,kind,fixture,effectType});
    root.add(shapeTool.preview);
  }
  function reattach(entity_id, f) { if (canEdit()) startShape(entity_id, 'snap', f); }
  function move(entity_id, f) {
    if (!canEdit()) return;
    if (f.shape === 'line') startShape(entity_id, f.snap ? 'snap' : 'draw', f);
    else start({ kind: 'move', entity_id, f }, 'Click a surface to move this fixture.');
  }
  function moveEffect(f) {
    if (!f || !canEdit()) return;
    if (f.shape === 'line') startShape(f.entity, f.snap ? 'snap' : 'draw', effectPlacement(f), f.type);
    else start({ kind: 'move', effectType: f.type, f: effectPlacement(f) }, 'Click a surface to move this effect.');
  }
  function startAim(at, aim, cone, commit, camera = false) {
    start({ kind: 'aim' }, 'Drag to aim on the ground or a wall. Done ends aiming; Escape cancels the current drag.');
    aiming = aimTool({ at, aim, cone_deg: cone, onCommit: async value => { if (canEdit()) await commit(value); } }); root.add(aiming.preview);
    slider = field(options, camera ? 'Field of view (degrees)' : 'Cone (degrees)', cone, () => {
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
    for (const entity_id of entities(device)) host.append(fixtureCard({ entity_id, getPlan, canEdit, op, onAdd: add, onAddEffect: addEffect, onMove: move, onAim: aim, onReattach: reattach, removeSelection, report }));
    const linked = effectEntities(device);
    if (!entities(device).length && linked.length) button(actions(host), 'Add effect', () => addEffect(linked[0]).catch(report), !canEdit());
    for (const f of getPlan().effect_fixtures || []) if (linked.includes(f.entity)) host.append(effectCard({ id: f.id, getPlan, canEdit, op, onMove: moveEffect, removeSelection, report, helpers }));
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
    if (!camera && !entities(device).length && !effectEntities(device).length) return;
    const open = button(host, camera ? 'Fixtures and camera view' : 'Fixtures', () => showDevice(device), false); open.dataset.fixtureBrowse = '';
  }
  function showDevice(device, id = null) {
    const returning = cardDevice?.device_id === device.device_id, previousPath = devicePath, previousReturn = deviceReturn;
    const state = tools.selection();
    let owner = null, binding = null;
    for (const b of getPlan().buildings || []) {
      const found = [...(b.anchors || []), ...(b.devices || [])].find(p => p.device === device.device_id);
      if (found) { owner = b; binding = found; break; }
    }
    owner ||= getPlan().buildings?.find(b => b.id === state.building);
    const roomId = state.room || binding?.host?.floor || binding?.host?.ceiling;
    const room = owner?.rooms?.find(r => r.id === roomId || device.area_id && r.ha_area === device.area_id);
    deviceAnchor = !!binding && !!owner?.anchors?.includes(binding); deviceParent = false;
    deviceReturn = binding && owner?.anchors?.includes(binding) ? { pieceId: binding.id, buildingId: owner.id }
      : room ? { pieceId: room.id, buildingId: owner.id } : tools.selected?.() || null;
    devicePath = owner ? propertyPath({ kind: 'anchor', piece: binding || { name: device.name, level: room?.level, host: { floor: room?.id } }, building: owner }, state).crumbs : ['Yard'];
    if (binding || owner) devicePath = [...devicePath.slice(0, -1), device.name || device.device_id];
    else devicePath.push(device.name || device.device_id);
    if (!owner && returning) { devicePath = previousPath; deviceReturn = previousReturn; }
    tools.select(null); cardEffect = null; cardDevice = device; cardLight = id ? { entity_id: entities(device).find(entity => getPlan().light_fixtures?.[entity]?.some(f => f.id === id)), id } : null;
    cardKey = null; refreshCard(); tools.revealSelection?.();
    const row = id && [...el('piece-card').querySelectorAll('[data-fixture-id]')].find(r => r.dataset.fixtureId === id);
    if (row) { row.open = true; row.scrollIntoView({ block: 'nearest' }); }
  }
  function showEffect(id) {
    deviceReturn = null; deviceParent = false;
    tools.select(null); cardDevice = null; cardLight = null; cardEffect = id; cardKey = null; refreshCard(); tools.revealSelection?.();
  }
  function releaseCard() {
    cardDevice = null; cardEffect = null; cardLight = null; cardKey = null; delete el('piece-card').dataset.fixtureCard;
    drawHandles();
  }
  function backToDevice() {
    // HA devices placed directly on a surface have no anchor piece to select.
    // Their existing HA section is the parent page; Back again reaches the room.
    if (dock && cardDevice && !deviceAnchor && !deviceParent && tools.haLink?.anchorSection) {
      deviceParent = true; cardKey = null; refreshCard(); return;
    }
    const target = deviceReturn;
    releaseCard(); el('piece-card').hidden = true; dock?.properties.clear(el('piece-card'));
    tools.select(target);
  }
  el('piece-card').addEventListener('fixturecardrelease', releaseCard, { signal });
  function refreshCard() {
    // Same card, new data: rebuild in place without losing the scroll offset or focus.
    return keepPlace(el('piece-card'), refreshCardNow);
  }
  function refreshCardNow() {
    if (!cardDevice && !cardEffect) return;
    const host = el('piece-card');
    if (host.dataset.stairDraft || cardKey !== null && !host.dataset.fixtureCard) { releaseCard(); return; }
    const key = JSON.stringify([cardEffect, deviceParent, getPlan().effect_fixtures, getPlan().light_fixtures, getPlan().light_fixtures_meta, getPlan().camera_views, getPlan().buildings, getPlan().site?.devices, getPlan().site?.terraces, getPlan().site?.pool, canEdit()]);
    if (key === cardKey) return;
    const open = [...host.querySelectorAll('[data-fixture-id]')].filter(r => r.open).map(r => r.dataset.fixtureId);
    cardKey = key; host.replaceChildren(); host.dataset.fixtureCard = cardEffect || cardDevice.device_id; host.hidden = false;
    dock?.properties.render(host, { crumbs: cardEffect ? ['Yard', 'Effect'] : [...devicePath, ...(deviceParent ? [] : ['Fixtures'])], back: backToDevice });
    button(host, 'Close', backToDevice, false);
    if (cardEffect) {
      if (!getPlan().effect_fixtures?.some(f => f.id === cardEffect)) { releaseCard(); host.hidden = true; return; }
      host.append(effectCard({ id: cardEffect, getPlan, canEdit, op, onMove: moveEffect, removeSelection, report, helpers }));
    } else {
      host.prepend(element('h3', cardDevice.name));
      if (deviceParent) host.append(tools.haLink.anchorSection({ device: cardDevice.device_id }));
      else drawFixtures(host, cardDevice);
    }
    for (const row of host.querySelectorAll('[data-fixture-id]')) {
      row.open = open.includes(row.dataset.fixtureId);
      let wasOpen = row.open;
      row.addEventListener('toggle', () => {
        // Native toggle events are queued. Restoring open cards during a
        // refresh (or an event from a replaced row) must not change selection.
        if (!host.contains(row) || wasOpen === row.open) return;
        wasOpen = row.open;
        if (row.open) cardLight = { entity_id: row.closest('[data-fixture-entity]').dataset.fixtureEntity, id: row.dataset.fixtureId };
        else if (cardLight?.id === row.dataset.fixtureId) cardLight = null;
        drawHandles();
      });
    }
    drawHandles();
  }
  function hits(x, y) {
    const event = { clientX: x, clientY: y };
    view.camera.updateMatrixWorld(true);
    screenRay(ray, view, event);
    draw(); root.updateMatrixWorld(true);
    const intersections = ray.intersectObjects(root.children, true).filter(hit => hit.object.visible && hit.object.userData.fixtureId && view.isPiecePickable?.(hit.object.userData) !== false);
    if (!intersections.length) return [];
    const piece = view.pick(event.clientX, event.clientY);
    const depth = piece?.point ? ray.ray.origin.distanceTo(new THREE.Vector3(...piece.point)) : Infinity, seen = new Set();
    return intersections.filter(hit => {
      const data = hit.object.userData;
      if (depth < hit.distance - .2 || seen.has(data.fixtureId)) return false;
      seen.add(data.fixtureId); return true;
    }).map(hit => {
      const data = hit.object.userData;
      return { ...data, kind: data.effectId ? 'effect_fixture' : 'light_fixture', id: data.effectId || data.fixtureId,
        building: data.building || null, pieceId: data.effectId || data.fixtureId, buildingId: data.building || null,
        distance: hit.distance, point: hit.point.toArray() };
    });
  }
  function selectPick(picked) {
    if (!['light_fixture', 'effect_fixture'].includes(picked?.kind)) return false;
    if (picked.effectId) showEffect(picked.effectId);
    else {
      const device = tools.haLink.state()?.devices?.find(d => entities(d).includes(picked.entity_id));
      showDevice(device || { device_id: picked.entity_id, entity_id: picked.entity_id, name: picked.entity_id }, picked.fixtureId);
    }
    return true;
  }
  function selectedLine() {
    const f = cardEffect ? getPlan()?.effect_fixtures?.find(f => f.id === cardEffect)
      : cardLight && getPlan()?.light_fixtures?.[cardLight.entity_id]?.find(f => f.id === cardLight.id);
    return !mode && canEdit() && f?.path && !f.snap && (f.ref !== 'floor' || view.groups?.levels[`${f.building}:${f.level}`]?.visible !== false) ? f : null;
  }
  function drawHandles() {
    gizmo.draw();
    handleLayer.replaceChildren(); pointHandles = [];
    const fixture = selectedLine(); if (!fixture) return;
    if (view.isPiecePickable?.({id:fixture.id,kind:cardEffect ? 'effect' : 'fixture'}) === false) return;
    view.camera.updateMatrixWorld(true);
    const rect = canvas.getBoundingClientRect(), active = press?.point;
    const path = resolveFixture(active ? { ...fixture, path: active.path } : fixture, getPlan()).path;
    path.forEach((at, index) => {
      const p = new THREE.Vector3(at[0] * FT, at[2] * FT, -at[1] * FT).project(view.camera);
      if (p.z < -1 || p.z > 1) return;
      const screen = [rect.left + (p.x + 1) * rect.width / 2, rect.top + (1 - p.y) * rect.height / 2];
      const node = element('span'); node.className = 'editor-handle editor-lot-handle'; node.dataset.fixturePoint = String(index);
      node.setAttribute('aria-hidden', 'true'); node.style.left = `${screen[0]}px`; node.style.top = `${screen[1]}px`; handleLayer.append(node);
      pointHandles.push({ index, at, screen, id: fixture.id });
    });
  }
  function hit(event) {
    const transform = gizmo.hit(event); if (transform) return transform;
    if (event.button !== 0 || !['select', 'move'].some(id => el(`rail-${id}`).getAttribute('aria-pressed') === 'true')) return null;
    drawHandles();
    return pointHandles.slice().sort((a, b) => Math.hypot(a.screen[0] - event.clientX, a.screen[1] - event.clientY)
      - Math.hypot(b.screen[0] - event.clientX, b.screen[1] - event.clientY))
      .find(h => Math.hypot(h.screen[0] - event.clientX, h.screen[1] - event.clientY) <= HANDLE_HIT_PX) || null;
  }
  function onPointPlane(event, z) {
    view.camera.updateMatrixWorld(true); screenRay(ray, view, event);
    const point = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -z * FT), new THREE.Vector3());
    return point && [point.x / FT, -point.z / FT];
  }
  function begin(event, handle = hit(event)) {
    if (handle?.kind?.startsWith('gizmo_')) return gizmo.begin(event, handle);
    const fixture = selectedLine();
    if (press || !fixture || !handle || handle.id !== fixture.id || event.button !== 0) return false;
    const at = resolveFixture(fixture, getPlan()).path[handle.index], start = onPointPlane(event, at[2]); if (!start) return false;
    press = { pointer: event.pointerId, x: event.clientX, y: event.clientY, enabled: view.controls.enabled,
      point: { fixture: structuredClone(fixture), index: handle.index, at, start, path: structuredClone(fixture.path),
        entity_id: cardLight?.entity_id, effect: !!cardEffect }, moved: false };
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); return true;
  }
  function previewPoint(point, path) {
    const mesh = root.children.find(mesh => mesh.userData.fixtureId === point.fixture.id); if (!mesh) return;
    const stroke = fixtureStroke(resolveFixture({ ...point.fixture, path }, getPlan()).path);
    mesh.geometry.dispose(); mesh.geometry = stroke.geometry; stroke.material.dispose();
    view.refreshSelection?.();
  }
  function pointerDown(event) {
    if (event.button !== 0) return false;
    const picked = !mode && hits(event.clientX, event.clientY)[0];
    if (!mode && !picked || mode && !canEdit()) return false;
    if (mode?.kind === 'shape' && !shapeTool.down(event)) return false;
    press = { pointer: event.pointerId, x: event.clientX, y: event.clientY, enabled: view.controls.enabled, picked };
    // Passive browsing observes the click without capturing navigation. The
    // editable scene uses hits/selectPick through its shared picker instead.
    if (picked) return true;
    view.controls.enabled = false; canvas.setPointerCapture(event.pointerId); aiming?.begin(); return true;
  }
  function pointerMove(event) {
    if (gizmo.active()) { gizmo.update(event, { free: !!event.shiftKey }); return true; }
    if (mode?.kind === 'shape' && canEdit()) return shapeTool.move(event);
    if (!press || press.pointer !== event.pointerId) return false;
    press.moved ||= Math.hypot(event.clientX - press.x, event.clientY - press.y) >= DRAG_THRESHOLD_PX;
    if (press.point) {
      if (!press.moved || !canEdit()) return true;
      const g = press.point, p = onPointPlane(event, g.at[2]); if (!p) return true;
      const old = g.fixture.path[g.index], at = [old[0] + p[0] - g.start[0], old[1] + p[1] - g.start[1], old[2]];
      // A ground reference may change as the point crosses a slope. Keep the
      // dragged point on its original world-height plane, including its lift.
      at[2] += fixtureReference(getPlan(), g.fixture, old) - fixtureReference(getPlan(), g.fixture, at);
      g.path[g.index] = at; previewPoint(g, g.path); drawHandles(); return true;
    }
    if (aiming && canEdit()) { const p = surface(event); if (p) aiming.move(p.at); } return true;
  }
  async function finish(event, cancelled) {
    if (press.point && !cancelled) pointerMove(event);
    const p = press; release();
    if (p.point) {
      const g = p.point;
      try {
        if (!cancelled && canEdit() && p.moved && JSON.stringify(g.path) !== JSON.stringify(g.fixture.path)) {
          await op(g.effect ? effectPathOperation(g.fixture, g.path, g.index)
            : { op: 'update_light_fixture', entity_id: g.entity_id, id: g.fixture.id, change: { path: g.path,
              ...(g.fixture.anchors ? { anchors: g.fixture.anchors.map((anchor, i) => i === g.index ? null : anchor) } : {}) } });
        }
      } finally {
        const current = g.effect ? getPlan()?.effect_fixtures?.find(f => f.id === g.fixture.id)
          : getPlan()?.light_fixtures?.[g.entity_id]?.find(f => f.id === g.fixture.id);
        // A save may answer after another fixture was selected or another
        // point drag began. Restore only this fixture's own current preview.
        previewPoint(g, press?.point?.fixture.id === g.fixture.id ? press.point.path : (current || g.fixture).path);
        drawHandles();
      }
      return;
    }
    if (p.picked) {
      if (!cancelled && !p.moved && Math.hypot(event.clientX - p.x, event.clientY - p.y) < DRAG_THRESHOLD_PX) selectPick(p.picked);
      return;
    }
    if (mode?.kind === 'shape') { await shapeTool.up(event, cancelled); return; }
    if (aiming) { if (!cancelled && canEdit()) { const hit = surface(event); if (hit) aiming.move(hit.at); } await aiming.end(cancelled || !canEdit()); return; }
    if (cancelled || !canEdit() || !mode || Math.hypot(event.clientX - p.x, event.clientY - p.y) >= DRAG_THRESHOLD_PX) return;
    const hit = surface(event, true); if (!hit) return;
    const active = mode, ref = hit.ground ? 'ground' : 'floor', base = ref === 'ground' ? groundAt(getPlan(), ...hit.at) : height({ ref, building: hit.building, level: hit.level }, hit.at);
    if (active.kind === 'move') {
      const context = { ref, ...(ref === 'floor' ? { building: hit.building, level: hit.level } : {}) };
      const change = { ...context, at: [hit.at[0], hit.at[1], hit.at[2] - base] };
      if (active.f.aim) { const target = absolute(active.f, active.f.aim); change.aim = [target[0], target[1], target[2] - height(context, target)]; }
      await op(active.effectType ? { op: 'update_effect_fixture', id: active.f.id, change: effectFields(change) }
        : { op: 'update_light_fixture', entity_id: active.entity_id, id: active.f.id, change });
      if (mode === active) cancel(); return;
    }
    const f = { shape: active.shape, ref, at: [hit.at[0], hit.at[1], hit.at[2] - base],
      ...(ref === 'floor' ? { building: hit.building, level: hit.level } : {}) };
    if (f.shape === 'spot') Object.assign(f, { aim: hit.ceiling ? [f.at[0], f.at[1], hit.floor - base] : [f.at[0] + 20, f.at[1], f.at[2]], cone_deg: 90, softness: .3 });
    await op(active.effectType ? { op: 'add_effect_fixture', fixture: { ...effectFields(f), type: active.effectType, ...(active.entity_id ? { entity: active.entity_id } : {}) } }
      : { op: 'add_light_fixture', entity_id: active.entity_id, fixture: f });
  }
  function pointerUp(event, cancelled = false) {
    if (gizmo.active()) { gizmo.pointerUp(event, cancelled).catch(report); return true; }
    if (!press || press.pointer !== event.pointerId) return false;
    return finish(event, cancelled).catch(report);
  }
  function draw() {
    for (const mesh of root.children) if (mesh.userData.fixtureId) {
      const { building, level } = mesh.userData;
      mesh.visible = !view.isPieceHidden?.(mesh.userData) && (!building || view.groups?.levels[`${building}:${level}`]?.visible !== false);
    }
    drawHandles();
  }
  function refresh() {
    if (mode && !canEdit()) cancel(); refreshCard();
    // A household with no house yet has no plan: draw no fixtures rather than stop the editor opening.
    const plan = getPlan() || {}, next = JSON.stringify([plan.light_fixtures, plan.effect_fixtures, plan.buildings, plan.site?.terraces]); if (signature === next) { draw(); return; } signature = next;
    for (const child of [...root.children]) if (child !== aiming?.preview && child !== shapeTool.preview) { child.geometry?.dispose(); child.material?.dispose(); child.removeFromParent(); }
    const rows = [...Object.entries(plan.light_fixtures || {}).flatMap(([entity_id, fixtures]) => fixtures.map(f => ({ entity_id, f }))),
      ...(plan.effect_fixtures || []).map(f => ({ entity_id: f.entity, f: effectPlacement(f), effectId: f.id }))];
    for (const { entity_id, f, effectId } of rows) {
      const at = f.at || f.path?.[0]; if (!at) continue;
      const kind = f.snap?.host.kind, building = ['wall','step'].includes(kind) && plan.buildings?.find(b => b[kind === 'wall' ? 'walls' : 'stairs']?.some(p => p.id === f.snap.host.id));
      const piece = building && building[kind === 'wall' ? 'walls' : 'stairs'].find(p => p.id === f.snap.host.id);
      const toAbsolute = p => [p[0],p[1],p[2] + fixtureReference(plan, f, p)];
      const resolved = ['point','line'].includes(f.shape) ? resolveFixture(f, plan) : null;
      let mesh;
      if (f.shape === 'line' || f.shape === 'area') {
        const points = f.shape === 'line' ? resolved.path : areaOutline({...f,at:toAbsolute(f.at)});
        mesh = fixtureStroke(points);
      } else {
        const p = resolved?.at || toAbsolute(at); mesh = new THREE.Mesh(new THREE.SphereGeometry(.12, 10, 6), new THREE.MeshBasicMaterial({ fog: false, color: FIXTURE_COLOR, toneMapped: false }));
        mesh.position.set(p[0] * FT, p[2] * FT, -p[1] * FT);
      }
      mesh.renderOrder = 21;
      mesh.userData = { fixtureId: f.id, effectId, entity_id, building: building?.id || (f.ref === 'floor' ? f.building : null), level: piece?.level || f.level }; root.add(mesh);
      Object.assign(mesh.userData, {pieceId:effectId || f.id,kind:effectId ? 'effect' : 'fixture'});
    }
    draw();
    view.refreshSelection?.();
  }
  function finishPlacement() {
    if (mode?.kind === 'shape') { release(); shapeTool.done().catch(report); }
    else if (mode) cancel();
  }
  if (bindCancel) el('device-cancel').addEventListener('click', finishPlacement, { signal });
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
  view.controls.addEventListener?.('change', drawHandles);
  signal.addEventListener('abort', () => { cancel(); if (el('piece-card').dataset.fixtureCard) { releaseCard(); el('piece-card').hidden = true; } root.traverse(o => { o.geometry?.dispose(); o.material?.dispose(); }); root.removeFromParent();
    view.controls.removeEventListener?.('change', drawHandles); gizmo.finish(true); gizmoLayer.remove(); handleLayer.remove(); }, { once: true });
  return { add, addEffect, showEffect, move, aim, aimCamera, drawFixtures, deviceLink, showDevice, hits, selectPick, finishPlacement,
    visibilitySelection: () => {
      if (cardEffect) return { id: cardEffect, kind: 'effect' };
      if (cardLight) return { id: cardLight.id, kind: 'fixture' };
      if (!cardDevice) return null;
      const plan = getPlan(), p = [...(plan?.buildings || []).flatMap(b => [...(b.anchors || []), ...(b.devices || [])]), ...(plan?.site?.devices || [])].find(p => p.device === cardDevice.device_id);
      return p ? { id: p.id, kind: 'device' } : null;
    },
    hit, begin, key: gizmo.key, typedValue: gizmo.typedValue, commit: gizmo.commit,
    handles: () => { drawHandles(); return [...gizmo.handles(), ...pointHandles]; }, pointerDown, pointerMove, pointerUp, cancel, refresh, draw, active: () => !!mode };
}
