"""Node tests for the light-visibility grid debug view and editor bake stats."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const { gridLayout, gridPoints, GRID_INVALID } = await import(file('static/twin/bake/grid_layout.js'));
const { encodeGridChunk } = await import(file('static/twin/bake/grid_chunk.js'));
const { mountModelLighting } = await import(file('static/twin/bake/model_lighting.js'));
const { mountGridDebug } = await import(file('static/twin/bake/grid_debug.js'));
const { formatBakeGridStatus } = await import(file('static/twin/bake/runtime.js'));

// Minimal DOM double supporting select/options, events, removal and queries.
class DomNode extends EventTarget {
  constructor(tag = 'div') {
    super();
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.style = { cssText: '' };
    this.dataset = {};
    this.attributes = {};
    this.className = '';
    this.id = '';
    this.value = '';
    this._text = '';
  }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) {
    for (const c of this.children) c.parentElement = null;
    this.children.length = 0;
    this._text = String(v ?? '');
  }
  get options() {
    // HTMLOptionsCollection is iterable with .length, not an Array (no .some()).
    const list = this.children.filter(c => c.tagName === 'OPTION');
    const col = { length: list.length, [Symbol.iterator]: () => list[Symbol.iterator]() };
    list.forEach((o, i) => { col[i] = o; });
    return col;
  }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'id') this.id = String(v);
    if (k === 'class') this.className = String(v);
  }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  append(...nodes) {
    for (const n of nodes) {
      if (typeof n === 'string') {
        const t = new DomNode('#text');
        t._text = n;
        n = t;
      }
      if (n.parentElement) n.remove();
      n.parentElement = this;
      this.children.push(n);
    }
  }
  appendChild(n) { this.append(n); return n; }
  replaceChildren(...nodes) {
    for (const c of this.children) c.parentElement = null;
    this.children.length = 0;
    this._text = '';
    this.append(...nodes);
  }
  remove() {
    const p = this.parentElement;
    if (p) {
      const i = p.children.indexOf(this);
      if (i >= 0) p.children.splice(i, 1);
      this.parentElement = null;
    }
  }
  descendants() { return this.children.flatMap(c => [c, ...c.descendants()]); }
  querySelector(sel) {
    const tag = sel.toUpperCase();
    return this.descendants().find(n => n.tagName === tag) || null;
  }
}

const body = new DomNode('body');
globalThis.document = {
  body,
  createElement: tag => new DomNode(tag),
  createTextNode: text => { const n = new DomNode('#text'); n._text = String(text); return n; },
};

const plan = {
  buildings: [{
    id: 'b', position: [0, 0],
    levels: [{ id: 'l', elevation: 0, ceiling: 8 }],
    rooms: [{ id: 'r', level: 'l', polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] }],
    walls: [],
  }],
  site: {},
};
const layout = gridLayout(plan);
const allPoints = gridPoints(layout);

function makeView() {
  const host = new DomNode('div');
  body.append(host);
  const scene = new THREE.Scene();
  let renders = 0;
  const view = {
    scene,
    plan,
    renderer3: { domElement: { parentElement: host } },
    render() { renders++; },
    live: {
      layout: () => ({
        markers: [
          { device_id: 'lamp-a', name: 'Kitchen Ceiling', entity_id: 'light.kitchen' },
          { device_id: 'lamp-b', name: 'Hall Sconce', entity_id: 'light.hall' },
        ],
      }),
    },
  };
  return { view, host, scene, renders: () => renders };
}

// 1. Core colour test: 0 -> black, 254 -> white, 255 -> red (+ mid-grey 127).
{
  const { view, host, scene } = makeView();
  const indices = new Uint32Array([0, 1, 2, 3]);
  const values = new Uint8Array([0, 254, GRID_INVALID, 127]);
  const chunks = new Map([['lamp-a', { layoutHash: layout.hash, device: 'lamp-a', emitters: 1, indices, values }]]);
  const dbg = mountGridDebug(view, { layout, chunks });

  const pts = scene.children.find(o => o.isPoints);
  assert.ok(pts, 'creates a THREE.Points in view.scene');
  assert.equal(pts.visible, false, 'points start hidden before choosing a lamp');
  assert.equal(pts.layers.isEnabled(31), true, 'points have layer 31 enabled for bake/post exclusion');
  assert.equal(pts.layers.isEnabled(0), true, 'points stay on layer 0 so the main camera draws them');

  // Verify picking exclusion via raycast no-op.
  const hits = [];
  pts.raycast(new THREE.Raycaster(), hits);
  assert.equal(hits.length, 0, 'points cannot be picked by a raycaster');

  dbg.setLamp('lamp-a');
  assert.equal(pts.visible, true, 'points become visible after setLamp');
  const pos = pts.geometry.attributes.position;
  const col = pts.geometry.attributes.color;
  assert.equal(pos.count, 4);
  assert.equal(col.count, 4);

  // Positions match gridPoints(layout) for indices 0..3.
  for (let i = 0; i < 4; i++) {
    assert.ok(Math.abs(pos.getX(i) - allPoints[i * 3]) < 1e-6);
    assert.ok(Math.abs(pos.getY(i) - allPoints[i * 3 + 1]) < 1e-6);
    assert.ok(Math.abs(pos.getZ(i) - allPoints[i * 3 + 2]) < 1e-6);
  }

  // Value 0 -> black (0, 0, 0)
  assert.deepEqual([col.getX(0), col.getY(0), col.getZ(0)], [0, 0, 0], 'value 0 is black');
  // Value 254 -> white (1, 1, 1)
  assert.deepEqual([col.getX(1), col.getY(1), col.getZ(1)], [1, 1, 1], 'value 254 is white');
  // Value 255 -> red (1, 0, 0)
  assert.deepEqual([col.getX(2), col.getY(2), col.getZ(2)], [1, 0, 0], 'value 255 is red');
  // Value 127 -> grey (0.5, 0.5, 0.5)
  assert.ok(Math.abs(col.getX(3) - 0.5) < 1e-5 && Math.abs(col.getY(3) - 0.5) < 1e-5 && Math.abs(col.getZ(3) - 0.5) < 1e-5, 'value 127 is mid-grey');

  dbg.stop();
  host.remove();
  console.log('Passed: test_debug_points_colours');
}

// 2. Multi-emitter chunk colours: max valid emitter visibility, all-255 -> red.
{
  const { view, host, scene } = makeView();
  const indices = new Uint32Array([0, 1, 2]);
  const values = new Uint8Array([
    0, 0,
    64, 254,
    GRID_INVALID, GRID_INVALID,
  ]);
  const chunks = new Map([['lamp-multi', { layoutHash: layout.hash, device: 'lamp-multi', emitters: 2, indices, values }]]);
  const dbg = mountGridDebug(view, { layout, chunks });
  dbg.setLamp('lamp-multi');
  const pts = scene.children.find(o => o.isPoints);
  const col = pts.geometry.attributes.color;
  assert.deepEqual([col.getX(0), col.getY(0), col.getZ(0)], [0, 0, 0]);
  assert.deepEqual([col.getX(1), col.getY(1), col.getZ(1)], [1, 1, 1]);
  assert.deepEqual([col.getX(2), col.getY(2), col.getZ(2)], [1, 0, 0]);
  dbg.stop();
  host.remove();
  console.log('Passed: test_multi_emitter_chunk_colours');
}

// 3. Select lists lamps, reacts to change event, and stop() removes + disposes everything.
{
  const { view, host, scene } = makeView();
  const chunks = new Map([
    ['lamp-a', { layoutHash: layout.hash, device: 'lamp-a', emitters: 1, indices: new Uint32Array([0, 1]), values: new Uint8Array([0, 254]) }],
    ['lamp-b', { layoutHash: layout.hash, device: 'lamp-b', emitters: 1, indices: new Uint32Array([2]), values: new Uint8Array([255]) }],
  ]);
  const dbg = mountGridDebug(view, { layout, chunks });
  const pts = scene.children.find(o => o.isPoints);
  const select = host.querySelector('select');
  assert.ok(select, 'a small select is mounted');
  const values = Array.from(select.options, o => o.value);
  assert.ok(values.includes('') && values.includes('lamp-a') && values.includes('lamp-b'), 'select lists off + all lamps');
  assert.equal(Array.from(select.options).find(o => o.value === 'lamp-a').textContent, 'Kitchen Ceiling');

  // Selecting via DOM change event switches the points.
  select.value = 'lamp-b';
  select.dispatchEvent(new Event('change'));
  assert.equal(pts.visible, true);
  assert.equal(pts.geometry.attributes.position.count, 1);
  assert.deepEqual([pts.geometry.attributes.color.getX(0), pts.geometry.attributes.color.getY(0), pts.geometry.attributes.color.getZ(0)], [1, 0, 0]);

  // Choosing empty value hides points again.
  select.value = '';
  select.dispatchEvent(new Event('change'));
  assert.equal(pts.visible, false);

  // Track geometry and material disposal on stop().
  let geoDisposed = 0, matDisposed = 0;
  pts.geometry.addEventListener('dispose', () => { geoDisposed++; });
  pts.material.addEventListener('dispose', () => { matDisposed++; });

  dbg.stop();
  assert.equal(scene.children.includes(pts), false, 'stop() removes points from scene');
  assert.equal(host.querySelector('select'), null, 'stop() removes select from DOM');
  assert.equal(geoDisposed, 1, 'stop() disposes geometry');
  assert.equal(matDisposed, 1, 'stop() disposes material');

  // Idempotent stop().
  dbg.stop();
  assert.equal(geoDisposed, 1);
  assert.equal(matDisposed, 1);
  host.remove();
  console.log('Passed: test_select_and_stop_disposal');
}

// 4. Live integration with real mountModelLighting (late attach + chunk arrival).
{
  const { view, host, scene } = makeView();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute([.3, .3, -.3, .7, .3, -.3, .3, .7, -.3], 3));
  g.computeVertexNormals();
  g.userData.bakeExcluded = true;
  const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial());
  mesh.userData.pieceId = 'chair-1';
  scene.add(mesh);

  const indices = new Uint32Array([0, 1, 2]);
  const chunkBytes = await encodeGridChunk({
    layoutHash: layout.hash, device: 'lamp-a', emitters: 1,
    indices, values: new Uint8Array([0, 254, 255]),
  });
  const models = mountModelLighting(view, {
    manifest: { key: 'atlas', lights: { 'lamp-a': { grid: 'chunk-a', gridLayout: layout.hash } } },
    layout,
    fresh: new Set(['lamp-a']),
    tints: new Map([['lamp-a', new THREE.Color(1, 1, 1)]]),
    lights: [{ device: 'lamp-a', absolute: true, at: [5, 5, 6], range: 20 }],
    api: async () => new Response(chunkBytes),
  });

  // Mount debug before chunks finish loading, then attach & update.
  const dbg = mountGridDebug(view, null);
  dbg.attach(models);
  await models.update(['lamp-a']);

  const select = host.querySelector('select');
  assert.ok(Array.from(select.options).some(o => o.value === 'lamp-a'), 'select populates when modelLighting finishes building');
  dbg.setLamp('lamp-a');
  const pts = scene.children.find(o => o.isPoints);
  assert.equal(pts.visible, true);
  assert.equal(pts.geometry.attributes.position.count, 3);
  const col = pts.geometry.attributes.color;
  assert.deepEqual([col.getX(0), col.getY(0), col.getZ(0)], [0, 0, 0]);
  assert.deepEqual([col.getX(1), col.getY(1), col.getZ(1)], [1, 1, 1]);
  assert.deepEqual([col.getX(2), col.getY(2), col.getZ(2)], [1, 0, 0]);

  dbg.stop();
  models.stop();
  host.remove();
  console.log('Passed: test_integrates_with_mountModelLighting');
}

// 5. Real modelLighting tracks foldedOrDropped model count and feeds status text.
{
  const { view, host, scene } = makeView();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute([.3, .3, -.3, .7, .3, -.3, .3, .7, -.3], 3));
  g.computeVertexNormals();
  g.userData.bakeExcluded = true;
  const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial());
  mesh.userData.pieceId = 'crowded-chair';
  scene.add(mesh);

  const allIdx = Uint32Array.from({ length: layout.count }, (_, i) => i);
  const allVis = new Uint8Array(layout.count).fill(254);
  const lights = [];
  const manifestLights = {};
  const blobs = new Map();
  for (let n = 0; n < 9; n++) {
    const id = `lamp-${n}`;
    lights.push({ device: id, absolute: true, at: [2 + n * 0.5, 2, 6], range: 25 });
    manifestLights[id] = { grid: `chunk-${n}`, gridLayout: layout.hash };
    blobs.set(`chunk-${n}`, await encodeGridChunk({
      layoutHash: layout.hash, device: id, emitters: 1, indices: allIdx, values: allVis,
    }));
  }
  const fresh = lights.map(l => l.device);
  const models = mountModelLighting(view, {
    manifest: { key: 'atlas', lights: manifestLights },
    layout,
    fresh: new Set(fresh),
    tints: new Map(fresh.map(id => [id, new THREE.Color(1, 1, 1)])),
    lights,
    api: async path => new Response(blobs.get(path.split('/').at(-1).slice(0, -4))),
  });
  await models.update(fresh);
  const st = models.stats();
  assert.equal(st.bricks, 1);
  assert.equal(st.dropped, 1, '9th emitter is dropped');
  assert.equal(st.foldedOrDropped, 1, '1 model folded or dropped lamps');
  assert.equal(
    formatBakeGridStatus({ points: 1000, bytes: 2048 }, st),
    'Grid 1000 points, 2 KB · 1 models folded or dropped lamps',
  );
  models.stop();
  host.remove();
  console.log('Passed: test_folded_or_dropped_model_count');
}

// 6. Editor status text formatting after a bake (with and without folded/dropped models).
{
  assert.equal(formatBakeGridStatus(null), '');
  assert.equal(formatBakeGridStatus({ points: 0, bytes: 0 }), '');
  assert.equal(formatBakeGridStatus({ points: 18356, bytes: 24576 }), 'Grid 18356 points, 24 KB');
  assert.equal(formatBakeGridStatus({ points: 100, bytes: 512 }, { foldedOrDropped: 0 }), 'Grid 100 points, 1 KB');
  assert.equal(
    formatBakeGridStatus({ points: 18356, bytes: 24576 }, { foldedOrDropped: 3 }),
    'Grid 18356 points, 24 KB · 3 models folded or dropped lamps',
  );
  assert.equal(
    formatBakeGridStatus({ points: 500, bytes: 2048 }, { folded: 2, dropped: 1 }),
    'Grid 500 points, 2 KB · 3 models folded or dropped lamps',
  );
  console.log('Passed: test_editor_status_text_format');
}

process.exit(0);
"""


def run():
    with tempfile.TemporaryDirectory(prefix='chauffeur_grid_debug_') as directory:
        driver = Path(directory) / 'driver.mjs'
        data = Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': {}}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True,
                                text=True, encoding='utf-8', timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='', file=sys.stderr)
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    run()
