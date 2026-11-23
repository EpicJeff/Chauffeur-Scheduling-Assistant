// Debug overlay (?grid=1): visualises one lamp's decoded light-visibility grid
// as coloured THREE.Points (black..white = 0..1 visibility, red = 255 invalid).
// Layer 31 excludes the cloud from bake, AO, reflection probes and view fades;
// layer 0 stays enabled so the main camera draws it, and raycast is a no-op.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { gridPoints, GRID_INVALID } from './grid_layout.js';

export function mountGridDebug(view, modelLighting = null) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(0), 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(0), 3));
  // RawShaderMaterial keeps its program cache key independent of scene light
  // counts and render targets, so ?grid=1 adds at most 1 shader program total.
  const material = new THREE.RawShaderMaterial({
    uniforms: { size: { value: 6 } },
    vertexShader: 'precision highp float;\nuniform mat4 modelViewMatrix;\nuniform mat4 projectionMatrix;\nuniform float size;\nattribute vec3 position;\nattribute vec3 color;\nvarying vec3 vColor;\nvoid main() {\n  vColor = color;\n  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);\n  gl_PointSize = size;\n}',
    fragmentShader: 'precision highp float;\nvarying vec3 vColor;\nvoid main() {\n  vec2 d = gl_PointCoord - 0.5;\n  if (dot(d, d) > 0.25) discard;\n  gl_FragColor = vec4(vColor, 1.0);\n}',
    fog: false,
    toneMapped: false,
  });
  const points = new THREE.Points(geometry, material);
  points.name = 'twin-grid-debug-points';
  points.userData.noOcclusion = true;
  points.layers.enable(31);
  points.raycast = () => {};
  points.frustumCulled = false;
  points.visible = false;
  view.scene.add(points);

  // Small glass lamp picker styled from house_twin.html tokens and frame_meter.js.
  const host = view.renderer3?.domElement?.parentElement || document.body;
  const box = document.createElement('div');
  box.id = 'twin-grid-debug';
  box.className = 'twin-grid-debug';
  box.style.cssText = 'position:fixed;left:16px;top:144px;z-index:9999;display:flex;align-items:center;gap:8px;' +
    'padding:6px 10px;border:1px solid var(--twinBorder,rgba(255,255,255,.12));border-radius:12px;' +
    'background:var(--twinGlassStrong,rgba(17,19,24,.82));backdrop-filter:blur(16px);' +
    'color:var(--twinText,#f4f5f7);font:12px/1.4 system-ui,sans-serif;max-width:min(360px,calc(100vw - 32px))';

  const label = document.createElement('label');
  label.textContent = 'Grid';
  label.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin:0;white-space:nowrap';

  const select = document.createElement('select');
  select.setAttribute('aria-label', 'Grid debug lamp');
  select.style.cssText = 'padding:4px 8px;border:1px solid var(--twinBorder,rgba(255,255,255,.16));border-radius:8px;' +
    'background:var(--twinGlassStrong,rgba(17,19,24,.92));color:var(--twinText,#f4f5f7);font:inherit;max-width:210px';
  label.appendChild(select);

  const countEl = document.createElement('span');
  countEl.dataset.gridCount = '';
  countEl.style.cssText = 'color:var(--twinTextDim,#a3a9b6);font:11px/1.4 ui-monospace,Consolas,monospace;white-space:nowrap';

  box.append(label, countEl);
  host?.appendChild(box);

  // Taps on the picker must not orbit or select the house (frame_meter.js:15).
  const domListeners = [];
  for (const name of ['pointerdown', 'pointerup', 'click']) {
    const fn = event => event.stopPropagation();
    box.addEventListener(name, fn);
    domListeners.push([name, fn]);
  }

  let stopped = false;
  let source = null;
  let unsubscribe = null;
  let currentDevice = '';
  let cachedLayoutKey = null;
  let cachedPoints = null;

  function chunkMap() {
    const raw = source?.chunks;
    if (!raw) return new Map();
    return raw instanceof Map ? raw : new Map(Object.entries(raw));
  }

  function layoutPoints() {
    if (source?.points) return source.points;
    const layout = source?.layout;
    if (!layout) return null;
    const key = layout.hash || layout;
    if (key !== cachedLayoutKey || !cachedPoints) {
      cachedLayoutKey = key;
      cachedPoints = gridPoints(layout);
    }
    return cachedPoints;
  }

  function lampLabel(device) {
    const markers = view.live?.layout?.()?.markers;
    if (Array.isArray(markers)) {
      const m = markers.find(row => row.device_id === device);
      if (m?.name) return m.name;
      if (m?.entity_id) return m.entity_id;
    }
    return device;
  }

  function clearPoints(chunksSize = 0) {
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(0), 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(0), 3));
    points.visible = false;
    countEl.textContent = chunksSize ? 'Off' : 'No grid';
  }

  function setLamp(device) {
    if (stopped) return;
    currentDevice = device ? String(device) : '';
    const chunks = chunkMap();
    const hasOption = !currentDevice || Array.from(select.options).some(o => o.value === currentDevice);
    if (hasOption) select.value = currentDevice;

    const chunk = currentDevice ? chunks.get(currentDevice) : null;
    const allPoints = chunk ? layoutPoints() : null;
    if (!chunk || !allPoints || !chunk.indices?.length) {
      clearPoints(chunks.size);
      view.render?.();
      return;
    }

    const count = chunk.indices.length;
    const emitters = chunk.emitters || 1;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const idx = chunk.indices;
    const vals = chunk.values;

    for (let i = 0; i < count; i++) {
      const gi = idx[i] * 3;
      const o = i * 3;
      positions[o] = allPoints[gi];
      positions[o + 1] = allPoints[gi + 1];
      positions[o + 2] = allPoints[gi + 2];

      if (emitters === 1) {
        const v = vals[i];
        if (v === GRID_INVALID) {
          colors[o] = 1; colors[o + 1] = 0; colors[o + 2] = 0;
        } else {
          const c = Math.max(0, Math.min(254, v)) / 254;
          colors[o] = c; colors[o + 1] = c; colors[o + 2] = c;
        }
      } else {
        const base = i * emitters;
        let maxV = -1;
        for (let e = 0; e < emitters; e++) {
          const v = vals[base + e];
          if (v !== GRID_INVALID && v > maxV) maxV = v;
        }
        if (maxV < 0) {
          colors[o] = 1; colors[o + 1] = 0; colors[o + 2] = 0;
        } else {
          const c = Math.max(0, Math.min(254, maxV)) / 254;
          colors[o] = c; colors[o + 1] = c; colors[o + 2] = c;
        }
      }
    }

    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    geometry.computeBoundingSphere();
    points.visible = true;
    countEl.textContent = `${count} pts`;
    view.render?.();
  }

  function sync() {
    if (stopped) return;
    const chunks = chunkMap();
    const devices = [...chunks.keys()].sort((a, b) => lampLabel(a).localeCompare(lampLabel(b)) || a.localeCompare(b));
    const options = [];
    const none = document.createElement('option');
    none.value = '';
    none.textContent = devices.length ? 'Off' : 'No baked grid';
    options.push(none);
    for (const id of devices) {
      const opt = document.createElement('option');
      opt.value = id;
      opt.textContent = lampLabel(id);
      options.push(opt);
    }
    select.replaceChildren(...options);
    if (currentDevice && chunks.has(currentDevice)) {
      select.value = currentDevice;
      setLamp(currentDevice);
    } else {
      select.value = '';
      clearPoints(chunks.size);
    }
  }

  const onChange = () => setLamp(select.value);
  select.addEventListener('change', onChange);

  function attach(next) {
    if (stopped) return;
    if (source === next && next) { sync(); return; }
    unsubscribe?.();
    unsubscribe = null;
    source = next || null;
    cachedLayoutKey = null;
    cachedPoints = null;
    if (source?.subscribe) unsubscribe = source.subscribe(sync);
    sync();
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    unsubscribe?.();
    unsubscribe = null;
    source = null;
    cachedPoints = null;
    select.removeEventListener('change', onChange);
    for (const [name, fn] of domListeners) box.removeEventListener(name, fn);
    domListeners.length = 0;
    box.remove();
    points.removeFromParent();
    geometry.dispose();
    material.dispose();
    if (view.gridDebug === api) view.gridDebug = null;
    view.render?.();
  }

  const api = {
    setLamp,
    stop,
    attach,
    get points() { return points; },
    get select() { return select; },
  };
  attach(modelLighting || view.bake?.models || null);
  return api;
}
