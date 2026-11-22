import * as THREE from 'three';
import { groundAt } from '../twin_ground.js';
import { dialogOpen } from './dialog.js';

const FT = .3048, EASE = .1;
const LOOK_RADIANS = .15 * Math.PI / 180, LOOK_PITCH = 89 * Math.PI / 180;
const FLY_KEYS = new Set(['w', 'a', 's', 'd', 'q', 'e']);
const SPEED_KEY = 'chauffeur_editor_fly_speed';
let sessionSpeed = null;

// Mounted only by the editor view. OrbitControls owns Alt-orbit, pan, wheel
// dolly and touch; this owns right-button mouselook and the fly chord.
export function mountEditorCamera(view, host) {
  if (sessionSpeed === null) {
    sessionSpeed = 12;
    try {
      const saved = Number(window.sessionStorage?.getItem(SPEED_KEY));
      if (Number.isFinite(saved) && saved > 0) sessionSpeed = THREE.MathUtils.clamp(saved, 1, 200);
    } catch { /* Session storage can be unavailable in private/embedded views. */ }
  }
  const { controls, renderer3 } = view, canvas = renderer3.domElement;
  controls.mouseButtons = { LEFT: null, MIDDLE: THREE.MOUSE.PAN, RIGHT: null };
  controls.screenSpacePanning = true;
  const orbitMin = controls.minPolarAngle, orbitMax = controls.maxPolarAngle;
  const lifecycle = new AbortController(), keys = new Set();
  const listen = (node, type, fn, options = {}) => node.addEventListener(type, fn, { ...options, signal: lifecycle.signal });
  const forward = new THREE.Vector3(), right = new THREE.Vector3(), up = new THREE.Vector3(), delta = new THREE.Vector3();
  let held = false, dragged = false, pressX = 0, pressY = 0, pointer = null, pendingMenu = null;
  let lastX = 0, lastY = 0;
  let previous = null, vx = 0, vy = 0, vz = 0, hideTimer = null, ignoreRepeats = false;
  const readout = document.createElement('output');
  readout.className = 'editor-camera-speed'; readout.hidden = true;
  readout.setAttribute('role', 'status'); host.append(readout);

  function blocked(target = document.activeElement) {
    return !!(target?.isContentEditable || target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])')
      || dialogOpen());
  }
  function stop() { keys.clear(); vx = vy = vz = 0; previous = null; }
  function reset() { held = false; pointer = null; pendingMenu = null; ignoreRepeats = false; stop(); }
  function moved(event, look = true) {
    if (!held || event.pointerId !== pointer) return;
    if (Math.hypot(event.clientX - pressX, event.clientY - pressY) >= 4) dragged = true;
    const dx = event.clientX - lastX, dy = event.clientY - lastY;
    lastX = event.clientX; lastY = event.clientY;
    const camera = view.camera;
    if (!look || (!dx && !dy) || !controls.enabled || blocked() || camera.isOrthographicCamera) return;
    const distance = camera.position.distanceTo(controls.target);
    camera.getWorldDirection(forward);
    const yaw = Math.atan2(forward.x, -forward.z) + dx * LOOK_RADIANS;
    const pitch = THREE.MathUtils.clamp(Math.asin(THREE.MathUtils.clamp(forward.y, -1, 1)) - dy * LOOK_RADIANS, -LOOK_PITCH, LOOK_PITCH);
    forward.set(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch));
    controls.target.copy(camera.position).addScaledVector(forward, distance);
    // Keep subsequent wheel/fly/render updates from snapping this view back
    // into the orbit cone. Alt-orbit and touch restore their original limits.
    controls.minPolarAngle = 0;
    controls.maxPolarAngle = Math.PI;
    controls.update();
  }
  // OrbitControls swaps rotate/pan when a modifier is down. Preserve these
  // editor bindings under Shift/Ctrl too, without changing its touch handling.
  listen(canvas, 'pointerdown', event => {
    if (event.pointerType === 'touch') {
      controls.minPolarAngle = orbitMin; controls.maxPolarAngle = orbitMax; return;
    }
    const modified = event.ctrlKey || event.metaKey || event.shiftKey;
    controls.mouseButtons.LEFT = event.button === 0 && event.altKey && !blocked()
      ? (modified ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE) : null;
    controls.mouseButtons.MIDDLE = modified ? THREE.MOUSE.ROTATE : THREE.MOUSE.PAN;
    if (event.button === 0 && event.altKey && controls.enabled && !blocked()) {
      controls.minPolarAngle = orbitMin; controls.maxPolarAngle = orbitMax;
    }
  }, { capture: true });
  listen(canvas, 'pointerdown', event => {
    if (event.pointerType === 'touch' || event.button !== 2) return;
    stop(); held = true; dragged = false; pendingMenu = null; ignoreRepeats = false;
    pressX = lastX = event.clientX; pressY = lastY = event.clientY; pointer = event.pointerId;
  }, { capture: true });
  listen(window, 'pointermove', moved, { capture: true });
  listen(document, 'pointermove', moved, { capture: true });
  listen(canvas, 'pointermove', moved, { capture: true });
  function release(event) {
    controls.mouseButtons.LEFT = null; controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN;
    if (!held || event.pointerId !== pointer) return;
    moved(event, false);
    const menu = pendingMenu;
    held = false; pointer = null; pendingMenu = null; ignoreRepeats = false; stop();
    // Some platforms emit contextmenu on press. Defer it until we know this
    // was a click; Windows emits it on release and follows the normal path.
    if (menu && !dragged) canvas.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
      button: 2, clientX: menu.x, clientY: menu.y }));
  }
  listen(window, 'pointerup', release, { capture: true });
  listen(document, 'pointerup', release, { capture: true });
  listen(canvas, 'pointerup', release, { capture: true });
  listen(canvas, 'contextmenu', event => {
    if (event.button !== 2 && !held) { dragged = false; return; }
    if (!held && !dragged) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (held) pendingMenu = { x: event.clientX, y: event.clientY };
  }, { capture: true });
  // A new click ends suppression from the preceding right drag. Keyboard
  // context-menu requests also keep their ordinary path.
  listen(canvas, 'pointerdown', event => { if (event.button !== 2) dragged = false; }, { capture: true });
  listen(canvas, 'wheel', event => {
    if (!held || !controls.enabled || blocked() || !event.deltaY) return;
    event.preventDefault(); event.stopImmediatePropagation();
    sessionSpeed = THREE.MathUtils.clamp(sessionSpeed * (event.deltaY < 0 ? 1.25 : 1 / 1.25), 1, 200);
    try { window.sessionStorage?.setItem(SPEED_KEY, String(sessionSpeed)); } catch { /* Keep the in-memory session value. */ }
    readout.textContent = `Speed ${Math.round(sessionSpeed)} ft/s`; readout.hidden = false;
    clearTimeout(hideTimer); hideTimer = setTimeout(() => { readout.hidden = true; }, 1000);
  }, { capture: true, passive: false });
  listen(window, 'keydown', event => {
    if (event.defaultPrevented || blocked(event.target) || blocked()) return;
    if (event.key === 'Escape' && (keys.size || vx || vy || vz)) {
      stop(); ignoreRepeats = true; dragged = true; event.preventDefault(); event.stopImmediatePropagation(); return;
    }
    const key = event.key.toLowerCase();
    if (!held || !FLY_KEYS.has(key)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (ignoreRepeats && event.repeat) return;
    ignoreRepeats = false;
    if (controls.enabled) {
      if (!keys.size && !vx && !vy && !vz) previous = performance.now();
      keys.add(key); dragged = true;
    }
  }, { capture: true });
  listen(window, 'keyup', event => {
    const key = event.key.toLowerCase();
    if (!keys.delete(key) && (!held || !FLY_KEYS.has(key) || blocked(event.target))) return;
    event.preventDefault(); event.stopImmediatePropagation();
  }, { capture: true });
  listen(window, 'blur', reset);
  listen(document, 'visibilitychange', reset);
  listen(window, 'pointercancel', reset, { capture: true });
  listen(document, 'pointercancel', reset, { capture: true });
  listen(canvas, 'pointercancel', reset, { capture: true });

  function frame(now) {
    if (!held || !controls.enabled || blocked()) { stop(); return false; }
    if (!keys.size && Math.abs(vx) + Math.abs(vy) + Math.abs(vz) < .00001) { stop(); return false; }
    const dt = previous === null ? 0 : Math.max(0, (now - previous) / 1000);
    previous = now;
    let tx = +keys.has('d') - +keys.has('a');
    let ty = +keys.has('e') - +keys.has('q');
    let tz = +keys.has('w') - +keys.has('s');
    const speed = sessionSpeed / (Math.hypot(tx, ty, tz) || 1);
    tx *= speed; ty *= speed; tz *= speed;
    const decay = Math.exp(-dt / EASE), integral = EASE * (1 - decay);
    // Exact integral of exponential easing: the same elapsed time produces
    // the same travel at 30, 60 or 144 Hz. All vectors are lifetime scratch.
    const dx = tx * dt + (vx - tx) * integral;
    const dy = ty * dt + (vy - ty) * integral;
    const dz = tz * dt + (vz - tz) * integral;
    vx = tx + (vx - tx) * decay; vy = ty + (vy - ty) * decay; vz = tz + (vz - tz) * decay;
    const camera = view.camera;
    right.set(1, 0, 0).applyQuaternion(camera.quaternion);
    if (camera.isOrthographicCamera) {
      up.set(0, 1, 0).applyQuaternion(camera.quaternion);
      delta.copy(right).multiplyScalar(dx * FT).addScaledVector(up, dz * FT);
      const span = Math.max(.001, camera.top - camera.bottom);
      camera.zoom = THREE.MathUtils.clamp(camera.zoom * Math.exp(dy * FT / span), controls.minZoom ?? 0, controls.maxZoom ?? Infinity);
      camera.updateProjectionMatrix();
    } else {
      camera.getWorldDirection(forward);
      delta.copy(right).multiplyScalar(dx * FT).addScaledVector(forward, dz * FT);
      delta.y += dy * FT;
    }
    const floor = groundAt(view.plan, (camera.position.x + delta.x) / FT, -(camera.position.z + delta.z) / FT) * FT + .2;
    delta.y = Math.max(delta.y, floor - camera.position.y);
    camera.position.add(delta); controls.target.add(delta);
    controls.update();
    return true;
  }
  return { frame, stop, speed: () => sessionSpeed, active: () => !!(keys.size || vx || vy || vz),
    dispose() { reset(); lifecycle.abort(); clearTimeout(hideTimer); readout.remove(); } };
}
