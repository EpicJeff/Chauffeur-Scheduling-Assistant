import { kindOf } from './kinds.js';
import { controlShape } from './controls/shared.js';

// The dial's size (its CSS box), the gap kept from the screen's edges, and the gap to the side card.
const DIAL = 280, EDGE = 8, SPACE = 12;

// The host owns gestures and positioning; kinds own the controls it mounts.
export function mountRing(view, live, {hit, position, tap, scene, dismiss, moved = () => {}}) {
  const canvas = view.renderer3.domElement, events = new AbortController();
  const root = document.createElement('aside'); root.className = 'twin-device-ring'; root.hidden = true;
  root.setAttribute('data-ring', ''); root.setAttribute('role', 'dialog'); document.body.append(root);
  let row = null, builder = null, signature = '', anchor = null, pointer = null, holdTimer = null;
  let suppressClick = false, suppressTimer = null, placed = '';
  const options = {signal: events.signal};
  const inside = event => root.contains?.(event.target);
  // The marker labels keep clear of the ring: the layer hears whenever it lands somewhere new.
  function settle(key) { if (placed !== key) { placed = key; moved(); } }
  function close() {
    builder?.stop?.(); builder = null; row = null; anchor = null; signature = '';
    root.hidden = true; root.replaceChildren(); settle('');
  }
  // The ring stays whole on screen: inside the viewport and above the wall's shelf and its
  // fade strip. It sits on the marker wherever that fits and slides in from an edge where it
  // does not; the kind's side card goes on whichever side has room (below on a narrow screen).
  function safeArea() {
    const width = window.innerWidth || 0, height = window.innerHeight || 0;
    let bottom = height - EDGE;
    for (const id of ['panel-fade', 'panel-shelf']) {
      const box = document.getElementById?.(id)?.getBoundingClientRect?.();
      if (box?.height > 0 && box.top > 0) bottom = Math.min(bottom, box.top - EDGE);
    }
    // The floor and mode pickers: the dial may cover them (it sits on the light), the side card
    // keeps below them whenever it fits.
    let bar = EDGE;
    for (const node of document.querySelectorAll?.('#twin-controls > *') || []) {
      const box = node.getBoundingClientRect?.();
      if (box?.height > 0) bar = Math.max(bar, box.bottom + EDGE);
    }
    return {left: EDGE, top: EDGE, right: width - EDGE, bottom, bar};
  }
  function draw() {
    if (!row) return;
    const at = position(row.device_id);
    if (!at) { close(); return; }
    anchor = {device_id: row.device_id, x: at.x, y: at.y};
    const safe = safeArea(), side = builder?.side || null, title = root.firstElementChild;
    if (!(safe.right > safe.left && safe.bottom > safe.top)) {
      root.style.left = `${at.x}px`; root.style.top = `${at.y}px`; settle(`${at.x}|${at.y}`); return;
    }
    const width = root.offsetWidth || DIAL, height = root.offsetHeight || DIAL, half = width / 2;
    const head = title?.localName === 'h2' ? (title.offsetHeight || 0) + 6 : 0;
    const sideWidth = side?.offsetWidth || 0, sideHeight = side?.offsetHeight || 0;
    let place = null;
    if (side) {
      const right = safe.right - at.x - half, left = at.x - half - safe.left;
      place = safe.right - safe.left < width + SPACE + sideWidth ? 'below'
        : right >= sideWidth + SPACE || right >= left ? 'right' : 'left';
    }
    const fit = (value, low, high) => Math.max(low, Math.min(high, value));
    const x = fit(at.x, safe.left + half + (place === 'left' ? sideWidth + SPACE : 0),
      safe.right - half - (place === 'right' ? sideWidth + SPACE : 0));
    const y = fit(at.y, safe.top + head + DIAL / 2,
      safe.bottom - height + DIAL / 2 - (place === 'below' ? sideHeight + SPACE : 0));
    root.style.left = `${Math.round(x)}px`; root.style.top = `${Math.round(y)}px`;
    if (side) {
      const top = y - DIAL / 2;
      side.style.left = place === 'right' ? `${width + SPACE}px` : place === 'left' ? `${-sideWidth - SPACE}px` : '0px';
      side.style.top = `${Math.round(place === 'below' ? height + SPACE
        : fit(height / 2 - sideHeight / 2, (safe.bottom - safe.bar >= sideHeight ? safe.bar : safe.top) - top,
          safe.bottom - top - sideHeight))}px`;
      root.setAttribute('data-side', place);
    } else root.removeAttribute('data-side');
    settle([root.style.left, root.style.top, width, height, place, side?.style.top].join('|'));
  }
  function update() {
    if (!row) return;
    const state = live.states()[row.entity_id], kind = kindOf(row);
    const key = JSON.stringify([row.device_id, row.offered, controlShape(state),
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
    draw();
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
    } else {
      // A tap on the scene does what it did when the marker's sheet was open: the ring closes
      // and the tap still lands (a room's floor opens the room; empty scenery backs out).
      if (row) close();
      scene(event);
    }
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
    if (row && event.target !== canvas && !inside(event)
        && !event.target?.closest?.('#cc-input-modal, #cc-confirm-modal')) close();
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
