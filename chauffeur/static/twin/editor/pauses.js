import { request, report, checkpoint } from './api.js';
import { snapRotation } from './snap.js';
import { pauseWords, sheetMaster, localCentre, turnPlacement } from './words.js';

const rotate = (p, degrees) => {
  const a = degrees * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  return [c * p[0] - s * p[1], s * p[0] + c * p[1]];
};
export function applyRegistration(reg, px) {
  const p = rotate([(px[0] - reg.origin_px[0]) * reg.scale, (reg.origin_px[1] - px[1]) * reg.scale], reg.angle || 0);
  return p.map((v, i) => v + reg.offset[i]);
}
export function invertRegistration(reg, point) {
  const p = rotate(point.map((v, i) => v - reg.offset[i]), -(reg.angle || 0));
  return [reg.origin_px[0] + p[0] / reg.scale, reg.origin_px[1] - p[1] / reg.scale];
}
// Same y flip, scale and angle as services/twin_register.from_two_points.
export function fromTwoPoints(aPx, bPx, aFt, bFt) {
  const pixels = Math.hypot(bPx[0] - aPx[0], bPx[1] - aPx[1]);
  const feet = Math.hypot(bFt[0] - aFt[0], bFt[1] - aFt[1]);
  if (pixels < 1 || feet < .001) throw new Error('Choose two different points, farther apart.');
  const angle = (Math.atan2(bFt[1] - aFt[1], bFt[0] - aFt[0]) - Math.atan2(aPx[1] - bPx[1], bPx[0] - aPx[0])) * 180 / Math.PI;
  return { scale: feet / pixels, angle, origin_px: [...aPx], offset: [...aFt] };
}

export function createPauses({ view, getBuild, getGhost, getSheets, refresh, preview, visibilityChanged, canEdit, signal }) {
  const el = id => document.getElementById(id), host = el('pause-card'), canvas = view.renderer3.domElement;
  let key = null, pause = null, step = null, buildId = null, floorKey = null;
  let mode = null, pins = [], drag = null, busy = false, lastAnswer = null, dismissed = false, masterSize = null;
  let original = null, adjusted = false, referenceKey = null, lastPin = null;
  let costBuild = null, costSeq = 0, cumulativeCost = 0, pendingCost = null;
  const stepCosts = new Map();
  function readCosts(build) {
    if (!build) return;
    if (costBuild !== build.id) {
      costBuild = build.id; costSeq = 0; cumulativeCost = 0; pendingCost = null; stepCosts.clear();
    }
    for (const event of build.events || []) {
      if (event.seq <= costSeq) continue;
      costSeq = event.seq;
      if (event.type === 'cost' && Number.isFinite(event.cost)) {
        // The runner emits its cumulative cost immediately before each step's
        // result. Keep that read's delta, including a genuine zero-cost read.
        pendingCost = Math.max(0, event.cost - cumulativeCost); cumulativeCost = event.cost;
      } else if (event.step && pendingCost !== null) {
        stepCosts.set(event.step, pendingCost); pendingCost = null;
      }
    }
  }
  function instruction() {
    el('pause-instruction').textContent = mode === 'pin'
      ? ['Tap a point on the blue outline, then its matching spot on the floor below.', 'Tap where that point belongs on the floor below.', 'Tap a second point on the blue outline, farther away.', 'Tap where the second point belongs on the floor below.'][pins.length]
      : mode === 'drag' ? 'Drag the blue outline along the floor. Choose Looks right when it is in place.'
        : adjusted ? 'This is a preview. Choose Looks right to keep it.' : '';
  }
  function disable(value) { busy = value; host.querySelectorAll('button, input').forEach(b => { b.disabled = value || !canEdit(); }); }
  async function answer(decision) {
    if (busy || !canEdit() || !pause) return;
    disable(true);
    const payload = { step: pause.step, decision };
    try {
      await request(`build/${encodeURIComponent(buildId)}/answer`, 'POST', payload);
      lastAnswer = payload; mode = null; pins = []; host.hidden = true; visibilityChanged?.(); await refresh();
    } finally { disable(false); }
  }
  async function showSheet() {
    let url = (window.chfBase ?? '../') + `api/house/editor/sheets/${encodeURIComponent(step.source)}/${step.page}.png`;
    if (window.chfAuthUrl) url = window.chfAuthUrl(url);
    const frame = view.plan.buildings.find(b => b.levels.some(l => `${b.id}:${l.id}` === floorKey));
    if (!frame || !pause?.registration) return;
    const levelId = frame.levels.find(l => `${frame.id}:${l.id}` === floorKey).id;
    masterSize = sheetMaster(getSheets(), step.source, step.page);
    view.setSheet({ url, reg: original.registration, masterSize, buildingId: frame.id, levelId });
  }
  function sync() {
    const build = getBuild(), next = build?.state === 'paused' && build.pause;
    readCosts(build);
    if (!next) { stopDrag(); clearPins(); host.hidden = true; pause = null; original = null; key = null; mode = null; visibilityChanged?.(); return; }
    // Seq may advance for unrelated events; only a new pause or a re-read reframes.
    const identity = `${build.id}:${next.step}:${JSON.stringify(next.registration || next.transform)}`;
    if (identity !== key) {
      key = identity; original = structuredClone(next); pause = structuredClone(next); adjusted = false;
      buildId = build.id; dismissed = false; mode = null; pins = []; masterSize = null; lastPin = null;
      step = build.steps.find(s => s.id === pause.step);
      const preview = view.plan.buildings.find(b => b.id === `editor-preview:${pause.step}`);
      const owner = getSheets().page_roles.find(r => r.source === step?.source && r.page === step?.page)?.building || 'house';
      floorKey = preview ? `${preview.id}:${preview.levels[0].id}` : `${owner}:${step?.level || view.plan.buildings.find(b => b.id === owner)?.levels[0]?.id}`;
      const house = view.plan.buildings.find(b => b.id === owner);
      const elevation = preview?.levels[0].elevation ?? house?.levels.find(l => l.id === step?.level)?.elevation ?? Infinity;
      const below = house?.levels.filter(l => l.elevation < elevation - .1).sort((a, b) => b.elevation - a.elevation)[0];
      referenceKey = below ? `${owner}:${below.id}` : floorKey;
      if (view.groups?.levels[floorKey]) {
        view.setView(floorKey);
        const otherKeys = view.plan.buildings.filter(b => b.id === owner).flatMap(b => b.levels
          .filter(l => l.elevation <= (preview?.levels[0].elevation ?? Infinity)).map(l => `${b.id}:${l.id}`));
        view.showLevels([floorKey, ...otherKeys]); view.setCamera('top');
        showSheet().catch(report);
      }
      el('pause-title').textContent = step?.label || 'Check this outline';
      el('pause-reason').textContent = pauseWords(pause);
      el('pause-turn-label').hidden = pause.kind !== 'lot_placement';
      el('pause-turn').value = pause.transform?.rotation || 0;
      el('pause-pin').hidden = pause.kind !== 'level_registration';
      instruction();
    }
    step = build.steps.find(s => s.id === pause.step);
    const lastCost = step?.last_cost ?? step?.cost ?? stepCosts.get(pause.step);
    el('pause-reread').textContent = Number.isFinite(lastCost) ? `Re-read · last $${lastCost.toFixed(2)}` : 'Re-read · last cost $— (unavailable)';
    el('pause-reread').title = 'Reads this drawing again and adds to the running cost.';
    host.hidden = dismissed || !canEdit();
    disable(busy); anchor(); visibilityChanged?.();
  }
  function anchor() {
    if (host.hidden || !floorKey) return;
    const pointsToAnchor = outline();
    const rect = canvas.getBoundingClientRect();
    const points = pointsToAnchor.map(p => view.screenOfFloor(...p, floorKey)).filter(Boolean);
    const right = points.length ? Math.max(...points.map(p => p[0])) + 18 : rect.right - 310;
    const top = points.length ? Math.min(...points.map(p => p[1])) : rect.top + 160;
    host.style.left = `${Math.max(rect.left + 84, Math.min(rect.right - host.offsetWidth - 18, right))}px`;
    host.style.top = `${Math.max(rect.top + 84, Math.min(rect.bottom - host.offsetHeight - 130, top))}px`;
  }
  function changed() {
    adjusted = true; instruction(); preview?.();
  }
  function outline() {
    const points = getGhost(pause?.step)?.piece?.outline || getGhost(pause?.step)?.piece?.lot || [];
    return pause?.registration && original?.registration
      ? points.map(p => applyRegistration(pause.registration, invertRegistration(original.registration, p))) : points;
  }
  function shift(by) {
    if (pause.kind === 'lot_placement') pause.transform.position = pause.transform.position.map((v, i) => v + by[i]);
    else pause.registration.offset = pause.registration.offset.map((v, i) => v + by[i]);
    changed();
  }
  function clearPins() {
    pins = []; el('editor-pin-marks').replaceChildren(); delete host.dataset.pinning;
    el('pause-pin').setAttribute('aria-pressed', 'false');
  }
  function stopDrag() {
    if (!drag) return;
    const start = drag; drag = null; view.controls.enabled = start.enabled;
    if (canvas.hasPointerCapture(start.pointerId)) canvas.releasePointerCapture(start.pointerId);
    el('editor-drag-outline').setAttribute('points', '');
  }
  signal.addEventListener('abort', stopDrag, { once: true });
  el('pause-accept').addEventListener('click', () => answer(adjusted
    ? pause.kind === 'lot_placement' ? { transform: pause.transform } : { registration: pause.registration }
    : { accept: true }).catch(report), { signal });
  el('pause-pin').addEventListener('click', () => {
    mode = 'pin'; pins = []; el('editor-pin-marks').replaceChildren(); instruction(); el('pause-pin').setAttribute('aria-pressed', 'true');
    // Keep the card away from the four point targets while pinning.
    host.dataset.pinning = 'true';
  }, { signal });
  el('pause-drag').addEventListener('click', () => { mode = 'drag'; pins = []; instruction(); }, { signal });
  el('pause-cancel').addEventListener('click', () => {
    stopDrag(); mode = null; clearPins(); pause = structuredClone(original); adjusted = false; lastPin = null;
    el('pause-turn').value = pause.transform?.rotation || 0; instruction(); preview?.();
  }, { signal });
  el('pause-turn').addEventListener('change', () => {
    const angle = Number(el('pause-turn').value);
    if (el('pause-turn').value.trim() && Number.isFinite(angle) && pause?.transform) {
      const owner = getSheets().page_roles.find(r => r.source === step.source && r.page === step.page)?.building || 'house';
      const house = view.plan.buildings.find(b => b.id === owner);
      Object.assign(pause.transform, turnPlacement(pause.transform, snapRotation(angle), house ? localCentre(house) : [0, 0]));
      changed();
    } else report(new Error('Use a finite number of degrees.'));
  }, { signal });
  el('pause-reread').addEventListener('click', async () => {
    if (busy || !canEdit()) return;
    if (!await window.promptConfirm('Re-read this drawing?', `${el('pause-reread').textContent}. Reading again adds to the running cost.`, 'Re-read', 'Cancel')) return;
    disable(true);
    try {
      await request(`build/${encodeURIComponent(buildId)}/reread`, 'POST', { step: pause.step });
      key = null; host.hidden = true; await refresh();
    } catch (error) {
      if (error.status === 409 && error.detail?.checkpoint) await checkpoint(error.detail).catch(report);
      else report(error);
    } finally { disable(false); }
  }, { signal });
  const marker = (point, key) => {
    const p = view.screenOfFloor(...point, key); if (!p) return;
    const dot = document.createElement('span'); dot.className = 'editor-pin-dot'; dot.textContent = String(pins.length);
    dot.style.left = `${p[0]}px`; dot.style.top = `${p[1]}px`; el('editor-pin-marks').append(dot);
  };
  return {
    sync, anchor, lastAnswer: () => lastAnswer, clearLastAnswer() { lastAnswer = null; },
    current: () => pause, sheetMaster: () => masterSize, pinCheck: () => lastPin,
    dismissed: () => dismissed,
    show() { dismissed = false; sync(); },
    resume() { dismissed = false; sync(); },
    dismiss() { stopDrag(); dismissed = true; host.hidden = true; mode = null; clearPins(); visibilityChanged?.(); },
    dragPauseGhost(dx, dy) {
      if (!pause || busy || !canEdit()) return;
      const p = outline()[0] || [0, 0], screen = view.screenOfFloor(...p, floorKey); if (!screen) return;
      const a = view.floorAt(...screen, floorKey), b = view.floorAt(screen[0] + dx, screen[1] + dy, floorKey);
      if (a && b) shift(b.map((v, i) => v - a[i]));
    },
    screenOfGhostUV(u, v) {
      const points = outline().length ? outline() : [[0, 0], [70, 65]];
      const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
      return view.screenOfFloor(Math.min(...xs) + u * (Math.max(...xs) - Math.min(...xs)), Math.max(...ys) - v * (Math.max(...ys) - Math.min(...ys)), floorKey);
    },
    screenOfSheetUV(u, v) {
      if (!pause) return null;
      if (!masterSize) return null;
      return view.screenOfFloor(...applyRegistration(original.registration, [u * masterSize[0], v * masterSize[1]]), referenceKey);
    },
    pointerDown(event) {
      if (!mode || !pause || busy || !canEdit()) return false;
      if (drag) return true;
      const targetKey = mode === 'pin' && pins.length % 2 ? referenceKey : floorKey;
      const point = view.floorAt(event.clientX, event.clientY, targetKey); if (!point) return true;
      if (mode === 'pin') {
        pins.push(pins.length % 2 === 0 ? invertRegistration(pause.registration, point) : point);
        marker(point, targetKey);
        if (pins.length === 4) {
          try {
            const registration = fromTwoPoints(pins[0], pins[2], pins[1], pins[3]);
            const landed = applyRegistration(registration, pins[2]);
            lastPin = { error_ft: Math.hypot(landed[0] - pins[3][0], landed[1] - pins[3][1]) };
            pause.registration = registration; mode = null; clearPins(); changed();
          } catch (error) { pins = []; instruction(); report(error); }
        } else instruction();
      } else {
        drag = { point, pointerId: event.pointerId, enabled: view.controls.enabled }; view.controls.enabled = false;
        canvas.setPointerCapture(event.pointerId);
      }
      return true;
    },
    pointerMove(event) {
      if (!drag || event.pointerId !== drag.pointerId) return false;
      const point = view.floorAt(event.clientX, event.clientY, floorKey);
      if (point) {
        el('pause-instruction').textContent = 'Let go to preview this place, then choose Looks right.';
        let points = outline();
        if (pause.kind === 'lot_placement') {
          const owner = getSheets().page_roles.find(r => r.source === step.source && r.page === step.page)?.building || 'house';
          const building = view.plan.buildings.find(b => b.id === owner);
          points = (building?.levels[0]?.outline || building?.walls.flatMap(w => [w.from, w.to]) || []).map(p => {
            const point = rotate(p, pause.transform.rotation); return point.map((v, i) => v + pause.transform.position[i]);
          });
        }
        const by = point.map((v, i) => v - drag.point[i]);
        el('editor-drag-outline').setAttribute('points', points.map(p => view.screenOfFloor(p[0] + by[0], p[1] + by[1], floorKey))
          .filter(Boolean).map(p => p.join(',')).join(' '));
      }
      return true;
    },
    pointerUp(event, cancel) {
      if (!drag || event.pointerId !== drag.pointerId) return false;
      const start = drag; stopDrag();
      const point = view.floorAt(event.clientX, event.clientY, floorKey);
      if (cancel || !point) { instruction(); return true; }
      const by = point.map((v, i) => v - start.point[i]);
      if (Math.hypot(...by) < .01) return true;
      shift(by); return true;
    },
  };
}
