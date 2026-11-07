import { request, report, checkpoint } from './api.js';
import { snapRotation } from './snap.js';

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

export function createPauses({ view, getBuild, getGhost, getSheets, refresh, canEdit, signal }) {
  const el = id => document.getElementById(id), host = el('pause-card'), canvas = view.renderer3.domElement;
  let key = null, pause = null, step = null, buildId = null, floorKey = null;
  let mode = null, pins = [], drag = null, busy = false, lastAnswer = null, dismissed = false, imageSize = null;
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
      ? ['Tap a point on the blue outline.', 'Tap where that point belongs on the drawing.', 'Tap a second point on the blue outline, farther away.', 'Tap where the second point belongs on the drawing.'][pins.length]
      : mode === 'drag' ? 'Drag the blue outline along the floor, then let go to keep its new place.' : '';
  }
  function disable(value) { busy = value; host.querySelectorAll('button, input').forEach(b => { b.disabled = value || !canEdit(); }); }
  async function answer(decision) {
    if (busy || !canEdit() || !pause) return;
    disable(true);
    const payload = { step: pause.step, decision };
    try {
      await request(`build/${encodeURIComponent(buildId)}/answer`, 'POST', payload);
      lastAnswer = payload; mode = null; pins = []; host.hidden = true; await refresh();
    } finally { disable(false); }
  }
  async function showSheet() {
    let url = (window.chfBase ?? '../') + `api/house/editor/sheets/${encodeURIComponent(step.source)}/${step.page}.png`;
    if (window.chfAuthUrl) url = window.chfAuthUrl(url);
    const frame = view.plan.buildings.find(b => b.levels.some(l => `${b.id}:${l.id}` === floorKey));
    if (!frame || !pause?.registration) return;
    const levelId = frame.levels.find(l => `${frame.id}:${l.id}` === floorKey).id;
    view.setSheet({ url, reg: pause.registration, buildingId: frame.id, levelId });
    const version = key;
    const image = new Image();
    image.onload = () => { if (version === key) imageSize = [image.naturalWidth, image.naturalHeight]; };
    image.src = url;
  }
  function sync() {
    const build = getBuild(), next = build?.state === 'paused' && build.pause;
    readCosts(build);
    if (!next) { host.hidden = true; pause = null; key = null; mode = null; return; }
    // Seq may advance for unrelated events; only a new pause or a re-read reframes.
    const identity = `${build.id}:${next.step}:${JSON.stringify(next.registration)}`;
    if (identity !== key) {
      key = identity; pause = next; buildId = build.id; dismissed = false; mode = null; pins = []; imageSize = null;
      step = build.steps.find(s => s.id === pause.step);
      const preview = view.plan.buildings.find(b => b.id === `editor-preview:${pause.step}`);
      const owner = getSheets().page_roles.find(r => r.source === step?.source && r.page === step?.page)?.building || 'house';
      floorKey = preview ? `${preview.id}:${preview.levels[0].id}` : `${owner}:${step?.level || view.plan.buildings.find(b => b.id === owner)?.levels[0]?.id}`;
      if (view.groups?.levels[floorKey]) {
        view.setView(floorKey);
        const otherKeys = view.plan.buildings.filter(b => b.id === owner).flatMap(b => b.levels
          .filter(l => l.elevation <= (preview?.levels[0].elevation ?? Infinity)).map(l => `${b.id}:${l.id}`));
        view.showLevels([floorKey, ...otherKeys]); view.setCamera('top');
        showSheet().catch(report);
      }
      el('pause-title').textContent = step?.label || 'Check this outline';
      const confidence = Number(pause.confidence);
      el('pause-reason').textContent = `${pause.why || 'Does this outline match your drawing?'} ${confidence >= .8 ? 'Sure' : confidence >= .5 ? 'Fairly sure' : 'Unsure'}.`;
      el('pause-turn-label').hidden = pause.kind !== 'lot_placement';
      el('pause-turn').value = pause.transform?.rotation || 0;
      el('pause-pin').hidden = pause.kind === 'lot_placement';
      instruction();
    }
    step = build.steps.find(s => s.id === pause.step);
    const lastCost = step?.last_cost ?? step?.cost ?? stepCosts.get(pause.step);
    el('pause-reread').textContent = Number.isFinite(lastCost) ? `Re-read · last $${lastCost.toFixed(2)}` : 'Re-read · last cost $— (unavailable)';
    el('pause-reread').title = 'Reads this drawing again and adds to the running cost.';
    host.hidden = dismissed || !canEdit();
    disable(busy); anchor();
  }
  function anchor() {
    if (host.hidden || !floorKey) return;
    const outline = getGhost(pause?.step)?.piece?.outline || getGhost(pause?.step)?.piece?.lot;
    const rect = canvas.getBoundingClientRect();
    const points = outline?.map(p => view.screenOfFloor(...p, floorKey)).filter(Boolean) || [];
    const right = points.length ? Math.max(...points.map(p => p[0])) + 18 : rect.right - 310;
    const top = points.length ? Math.min(...points.map(p => p[1])) : rect.top + 160;
    host.style.left = `${Math.max(rect.left + 84, Math.min(rect.right - host.offsetWidth - 18, right))}px`;
    host.style.top = `${Math.max(rect.top + 84, Math.min(rect.bottom - host.offsetHeight - 130, top))}px`;
  }
  el('pause-accept').addEventListener('click', () => answer({ accept: true }).catch(report), { signal });
  el('pause-pin').addEventListener('click', () => {
    mode = 'pin'; pins = []; el('editor-pin-marks').replaceChildren(); instruction(); el('pause-pin').setAttribute('aria-pressed', 'true');
    // Keep the card away from the four point targets while pinning.
    host.dataset.pinning = 'true';
  }, { signal });
  el('pause-drag').addEventListener('click', () => { mode = 'drag'; pins = []; instruction(); }, { signal });
  el('pause-cancel').addEventListener('click', () => {
    mode = null; pins = []; instruction(); el('editor-pin-marks').replaceChildren(); delete host.dataset.pinning; el('pause-pin').setAttribute('aria-pressed', 'false');
  }, { signal });
  el('pause-turn').addEventListener('change', () => {
    const angle = Number(el('pause-turn').value);
    if (Number.isFinite(angle)) answer({ transform: { ...pause.transform, rotation: snapRotation(angle) } }).catch(report);
  }, { signal });
  el('pause-reread').addEventListener('click', async () => {
    if (busy || !canEdit()) return;
    disable(true);
    try {
      await request(`build/${encodeURIComponent(buildId)}/reread`, 'POST', { step: pause.step });
      key = null; host.hidden = true; await refresh();
    } catch (error) {
      if (error.status === 409 && error.detail?.checkpoint) await checkpoint(error.detail).catch(report);
      else report(error);
    } finally { disable(false); }
  }, { signal });
  const marker = point => {
    const p = view.screenOfFloor(...point, floorKey); if (!p) return;
    const dot = document.createElement('span'); dot.className = 'editor-pin-dot'; dot.textContent = String(pins.length);
    dot.style.left = `${p[0]}px`; dot.style.top = `${p[1]}px`; el('editor-pin-marks').append(dot);
  };
  return {
    sync, anchor, lastAnswer: () => lastAnswer,
    show() { key = null; dismissed = false; sync(); },
    resume() { dismissed = false; sync(); },
    dismiss() { dismissed = true; host.hidden = true; mode = null; pins = []; el('editor-pin-marks').replaceChildren(); delete host.dataset.pinning; },
    screenOfGhostUV(u, v) {
      const outline = getGhost(pause?.step)?.piece?.outline || getGhost(pause?.step)?.piece?.lot || [[0, 0], [70, 65]];
      const xs = outline.map(p => p[0]), ys = outline.map(p => p[1]);
      return view.screenOfFloor(Math.min(...xs) + u * (Math.max(...xs) - Math.min(...xs)), Math.max(...ys) - v * (Math.max(...ys) - Math.min(...ys)), floorKey);
    },
    screenOfSheetUV(u, v) {
      if (!pause) return null;
      const size = imageSize || [2048, 2048];
      return view.screenOfFloor(...applyRegistration(pause.registration, [u * size[0], v * size[1]]), floorKey);
    },
    pointerDown(event) {
      if (!mode || !pause || busy || !canEdit()) return false;
      const point = view.floorAt(event.clientX, event.clientY, floorKey); if (!point) return true;
      if (mode === 'pin') {
        pins.push(pins.length % 2 === 0 ? invertRegistration(pause.registration, point) : point);
        marker(point);
        if (pins.length === 4) {
          try {
            const registration = fromTwoPoints(pins[0], pins[2], pins[1], pins[3]);
            mode = null; el('editor-pin-marks').replaceChildren(); delete host.dataset.pinning;
            answer({ registration }).catch(report);
          } catch (error) { pins = []; instruction(); report(error); }
        } else instruction();
      } else {
        drag = { point, enabled: view.controls.enabled }; view.controls.enabled = false;
        canvas.setPointerCapture(event.pointerId);
      }
      return true;
    },
    pointerMove(event) {
      if (!drag) return false;
      const point = view.floorAt(event.clientX, event.clientY, floorKey);
      if (point) {
        el('pause-instruction').textContent = 'Let go to keep this place.';
        let outline = getGhost(pause.step)?.piece?.outline || getGhost(pause.step)?.piece?.lot || [];
        if (pause.kind === 'lot_placement') {
          const owner = getSheets().page_roles.find(r => r.source === step.source && r.page === step.page)?.building || 'house';
          const building = view.plan.buildings.find(b => b.id === owner);
          outline = (building?.levels[0]?.outline || building?.walls.flatMap(w => [w.from, w.to]) || []).map(p => {
            const point = rotate(p, pause.transform.rotation); return point.map((v, i) => v + pause.transform.position[i]);
          });
        }
        const by = point.map((v, i) => v - drag.point[i]);
        el('editor-drag-outline').setAttribute('points', outline.map(p => view.screenOfFloor(p[0] + by[0], p[1] + by[1], floorKey))
          .filter(Boolean).map(p => p.join(',')).join(' '));
      }
      return true;
    },
    pointerUp(event, cancel) {
      if (!drag) return false;
      el('editor-drag-outline').setAttribute('points', '');
      const start = drag; drag = null; view.controls.enabled = start.enabled;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      const point = view.floorAt(event.clientX, event.clientY, floorKey);
      if (cancel || !point) { instruction(); return true; }
      const by = point.map((v, i) => v - start.point[i]);
      if (Math.hypot(...by) < .01) return true;
      const decision = pause.kind === 'lot_placement'
        ? { transform: { ...pause.transform, position: pause.transform.position.map((v, i) => v + by[i]) } }
        : { registration: { ...pause.registration, offset: pause.registration.offset.map((v, i) => v + by[i]) } };
      answer(decision).catch(report); return true;
    },
  };
}
