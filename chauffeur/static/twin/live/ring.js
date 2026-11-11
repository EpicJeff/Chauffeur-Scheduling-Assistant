import { kindOf } from './kinds.js';

// The host owns gestures and positioning; kinds own the controls it mounts.
export function mountRing(view, live, {hit, position, tap, scene, dismiss}) {
  const canvas = view.renderer3.domElement, events = new AbortController();
  const root = document.createElement('aside'); root.className = 'twin-device-ring'; root.hidden = true;
  root.setAttribute('data-ring', ''); root.setAttribute('role', 'dialog'); document.body.append(root);
  let row = null, builder = null, signature = '', anchor = null, pointer = null, holdTimer = null;
  let suppressClick = false, suppressTimer = null;
  const options = {signal: events.signal};
  const inside = event => root.contains?.(event.target);
  function close() {
    builder?.stop?.(); builder = null; row = null; anchor = null; signature = '';
    root.hidden = true; root.replaceChildren();
  }
  function draw() {
    if (!row) return;
    const at = position(row.device_id);
    if (!at) { close(); return; }
    anchor = {device_id: row.device_id, x: at.x, y: at.y};
    root.style.left = `${at.x}px`; root.style.top = `${at.y}px`;
  }
  function update() {
    if (!row) return;
    const state = live.states()[row.entity_id], kind = kindOf(row);
    const attrs = state?.attributes || {};
    const key = JSON.stringify([row.device_id, row.offered, attrs.supported_color_modes, attrs.effect_list,
      attrs.min_color_temp_kelvin, attrs.max_color_temp_kelvin, attrs.min_mireds, attrs.max_mireds,
      kind.ring ? null : state]);
    if (signature === key && builder?.update) { builder.update(state); return; }
    if (signature === key) return;
    signature = key; builder?.stop?.(); root.replaceChildren();
    root.setAttribute('data-device-id', row.device_id); root.setAttribute('aria-label', row.name);
    const title = document.createElement('h2'); title.textContent = row.name; root.append(title);
    if (!kind.ring) {
      const status = document.createElement('p'); status.className = 'twin-ring-status';
      status.textContent = live.markers().find(marker => marker.device_id === row.device_id)?.label || state?.state || 'unavailable';
      root.append(status);
    }
    builder = (kind.ring || kind.panel)({row, state, control: live.control, surface: 'ring',
      getState: () => live.states()[row.entity_id]});
    root.append(builder);
  }
  function open(next) {
    close(); dismiss(); row = next; root.hidden = false; update(); draw();
  }
  function cancel() { clearTimeout(holdTimer); holdTimer = null; pointer = null; }
  function down(event) {
    if (event.button > 0 || event.isPrimary === false) { cancel(); return; }
    // A deliberate new pointer sequence is allowed, even immediately after a hold.
    suppressClick = false; clearTimeout(suppressTimer);
    cancel();
    pointer = {id: event.pointerId, x: event.clientX, y: event.clientY, row: hit(event), moved: false, held: false};
    const start = pointer;
    if (start.row) holdTimer = setTimeout(() => {
      if (pointer !== start || start.moved) return;
      start.held = true; suppressClick = true; open(start.row);
    }, 500);
  }
  function move(event) {
    if (!pointer || pointer.id !== event.pointerId) return;
    if (Math.hypot(pointer.x - event.clientX, pointer.y - event.clientY) > 6) {
      pointer.moved = true; clearTimeout(holdTimer);
    }
  }
  function up(event) {
    const start = pointer;
    if (!start || start.id !== event.pointerId) return;
    move(event); cancel();
    if (start.held) {
      event.preventDefault(); suppressClick = true;
      clearTimeout(suppressTimer); suppressTimer = setTimeout(() => { suppressClick = false; }, 1000);
      return;
    }
    if (start.moved) return;
    if (start.row) {
      if (kindOf(start.row).quick) { close(); tap(start.row); }
      else open(start.row);
    } else if (row) close();
    else scene(event);
  }
  canvas.addEventListener('pointerdown', down, options);
  canvas.addEventListener('pointermove', move, options);
  canvas.addEventListener('pointerup', up, options);
  canvas.addEventListener('pointercancel', cancel, options);
  document.addEventListener('pointerup', event => { if (event.target !== canvas) up(event); }, {...options, capture: true});
  document.addEventListener('pointermove', event => { if (event.target !== canvas) move(event); }, {...options, capture: true});
  document.addEventListener('pointercancel', cancel, {...options, capture: true});
  canvas.addEventListener('contextmenu', event => { if (pointer?.row || row) event.preventDefault(); }, options);
  // Capture the compatibility click wherever the released finger retargets it, including
  // the newly mounted centre. A fresh pointerdown distinguishes the next deliberate tap.
  document.addEventListener('click', event => {
    if (suppressClick) {
      event.preventDefault(); event.stopImmediatePropagation(); suppressClick = false; clearTimeout(suppressTimer); return;
    }
    if (row && event.target !== canvas && !inside(event)) close();
  }, {...options, capture: true});
  document.addEventListener('pointerdown', event => {
    suppressClick = false; clearTimeout(suppressTimer);
    if (event.target !== canvas) cancel();
  }, {...options, capture: true});
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); }, options);
  const unsubscribe = live.subscribe(update);
  return {
    open, close, draw, current: () => anchor && {...anchor},
    stop() { cancel(); clearTimeout(suppressTimer); close(); unsubscribe(); events.abort(); root.remove(); },
  };
}
