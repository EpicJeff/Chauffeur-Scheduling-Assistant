"""Thin surfaces (batten faces, trim edges) borrow their host wall's lightmap: no black lines.

The user, 2026-11-14, at night with the fire pit and pool light baked: "The super dark lines on
the batten strips is the most obvious issue." Board-and-batten battens are 0.14 x 0.09 ft
faces; at the outdoor density they covered no texel centre, so the raster wrote nothing and
the shader read black. CPU Node proof: the GPU's centre-sampled raster is emulated (irradiance
of one point light, no shadows), then the real filter and dilation run, and every outward
face is sampled the way the runtime samples it.

Run from chauffeur/: python tests/test_twin_bake_proxy_js.py (HA_BASE_URL unset).
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

# Imported first: it points CHAUFFEUR_DATA_DIR at a scratch directory before the store loads.
from test_twin_lightmap_material_js import household_pool_house
from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {buildAtlas} = await import(file('static/twin/bake/atlas.js'));
const {filterCharts, dilateCharts} = await import(file('static/twin/bake/bake_pass.js'));
const FT = .3048, rect = [[0,0],[12,0],[12,10],[0,10]];
const plan = () => ({generatorVersion: 'test', materials: {}, site: {}, buildings: [{id: 'house', position: [0,0], base: 0,
  foundation: {mode: 'fixed', offset_ft: 0, thickness_ft: 1}, levels: [{id: 'L1', elevation: 0, ceiling: 8, outline: rect}],
  walls: rect.map((p, i) => ({id: 'w' + i, level: 'L1', from: p, to: rect[(i + 1) % 4], thickness: .5, height: 8, exterior: true})),
  rooms: [{id: 'room', level: 'L1', polygon: rect}], openings: [], roof: {sections: []}, anchors: [], items: []}]});
const options = {room: {density: 8, page: 2048, gutter: 2}}, size = options.room.page;
async function bake() {
  const p = plan(), house = buildTwin(p, kit, 'high', {viewing: true}); await house.ready; house.root.updateMatrixWorld(true);
  return {root: house.root, atlas: buildAtlas(house.root, p, options)};
}
let passed = 0, ran = 0;
async function check(name, fn) { ran++; try { await fn(); passed++; console.log('  ok   ' + name); } catch (e) { console.log('  FAIL ' + name + ' ' + e.stack); } }

const {root: houseRoot, atlas} = await bake();
const light = new THREE.Vector3(6 * FT, 4 * FT, 4 * FT);   // outside the south wall (y = 0), 4 ft out, 4 ft up
const irradiance = (world, normal) => { const d = light.clone().sub(world), r = d.length();
  return Math.max(0, normal.dot(d.normalize())) / (r * r); };
// The GPU: a texel is written when its centre lies in one of the chart's faces (in uv3 space).
function raster() {
  const bytes = new Uint8Array(size * size * 4), scale = 60;
  const inTri = (p, a, b, c) => { const s = (p, q, r) => (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1]);
    const d1 = s(p, a, b), d2 = s(p, b, c), d3 = s(p, c, a); return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0)); };
  for (const c of atlas.room.charts) {
    const g = c.mesh.geometry, uv = g.attributes.uv3, pos = g.attributes.position, r = c.rect;
    const normal = new THREE.Vector3().crossVectors(new THREE.Vector3().fromBufferAttribute(pos, c.faces[0] * 3 + 1).sub(new THREE.Vector3().fromBufferAttribute(pos, c.faces[0] * 3)),
      new THREE.Vector3().fromBufferAttribute(pos, c.faces[0] * 3 + 2).sub(new THREE.Vector3().fromBufferAttribute(pos, c.faces[0] * 3))).transformDirection(c.mesh.matrixWorld).normalize();
    for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) {
      const p = [x + .5, y + .5];
      for (const f of c.faces) {
        const t = [0, 1, 2].map(k => [uv.getX(f * 3 + k) * size, uv.getY(f * 3 + k) * size]);
        if (!inTri(p, ...t)) continue;
        const b = new THREE.Triangle(...t.map(q => new THREE.Vector3(q[0], q[1], 0))).getBarycoord(new THREE.Vector3(p[0], p[1], 0), new THREE.Vector3());
        const world = new THREE.Vector3();
        [b.x, b.y, b.z].forEach((w, k) => world.addScaledVector(new THREE.Vector3().fromBufferAttribute(pos, f * 3 + k), w));
        world.applyMatrix4(c.mesh.matrixWorld);
        const q = (y * size + x) * 4; bytes[q] = Math.min(255, Math.round(irradiance(world, normal) * scale)); bytes[q + 3] = 255; break;
      }
    }
  }
  filterCharts(bytes, atlas.room.charts, size); dilateCharts(bytes, atlas.room.charts, size);
  return {bytes, scale};
}
// The runtime: bilinear on the page at a vertex-interpolated uv3.
const sample = (bytes, u, v) => { const fx = u * size - .5, fy = v * size - .5, x0 = Math.floor(fx), y0 = Math.floor(fy), tx = fx - x0, ty = fy - y0;
  const at = (x, y) => bytes[(Math.min(size - 1, Math.max(0, y)) * size + Math.min(size - 1, Math.max(0, x))) * 4];
  return (at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx) * (1 - ty) + (at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx) * ty; };

await check('no_batten_or_siding_face_reads_darker_than_the_light_on_it', () => {
  const {bytes, scale} = raster();
  let faces = 0, worst = Infinity, worstAt = null;
  houseRoot.traverse(m => {
    if (!m.isMesh || m.material.name !== 'siding' || !m.geometry.attributes.uv3) return;
    const pos = m.geometry.attributes.position, uv = m.geometry.attributes.uv3, room = m.geometry.attributes.lmRoom;
    for (let f = 0; f < pos.count / 3; f++) {
      if (room.getX(f * 3) < 0) continue;
      const v = [0, 1, 2].map(k => new THREE.Vector3().fromBufferAttribute(pos, f * 3 + k).applyMatrix4(m.matrixWorld));
      const n = new THREE.Vector3().crossVectors(v[1].clone().sub(v[0]), v[2].clone().sub(v[0])).normalize();
      if (n.z < .9) continue;                                           // faces looking south, at the light
      const centre = v[0].clone().add(v[1]).add(v[2]).multiplyScalar(1 / 3);
      const expect = irradiance(centre, n) * scale; if (expect < 20) continue;
      const got = sample(bytes, [0, 1, 2].reduce((s, k) => s + uv.getX(f * 3 + k), 0) / 3, [0, 1, 2].reduce((s, k) => s + uv.getY(f * 3 + k), 0) / 3);
      faces++; if (got / expect < worst) { worst = got / expect; worstAt = centre.toArray().map(x => +(x / FT).toFixed(2)); }
    }
  });
  assert.ok(faces > 20, `lit siding faces sampled: ${faces}`);
  assert.ok(worst >= .8, `every lit face reads at least 80% of its light (battens included): worst ${worst.toFixed(2)} at ${worstAt}`);
});

await check('thin_faces_are_proxies_with_no_atlas_rect_inside_their_host', () => {
  const proxied = atlas.room.charts.filter(c => c.proxies?.length);
  const count = proxied.reduce((n, c) => n + c.proxies.length, 0);
  assert.ok(count >= 50, `batten faces are proxies: ${count}`);
  for (const c of atlas.room.charts) assert.ok(Math.min(c.rect.w, c.rect.h) >= 2, `every chart that takes a rect holds two texels across: ${JSON.stringify(c.rect)}`);
  for (const c of proxied) for (const p of c.proxies) {
    const uv = p.mesh.geometry.attributes.uv3, page = p.mesh.geometry.attributes.lmLightPage, r = c.rect;
    for (const f of p.faces) for (let k = 0; k < 3; k++) {
      const x = uv.getX(f * 3 + k) * size, y = uv.getY(f * 3 + k) * size;
      assert.ok(x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h, 'a proxy maps inside its host rect');
      assert.equal(page.getX(f * 3 + k), c.page, "and onto the host's page");
      assert.equal(p.mesh.geometry.attributes.lmRoom.getX(f * 3 + k), c.room, "with the host's room");
    }
  }
});

await check('proxy_assignment_and_atlas_key_are_deterministic', async () => {
  const again = await bake();
  const shape = a => a.room.charts.map(c => [c.id, c.rect, (c.proxies || []).map(p => p.faces.join(','))]);
  assert.equal(again.atlas.key, atlas.key, 'the same house gives the same atlas key');
  assert.deepEqual(shape(again.atlas), shape(atlas), 'and the same hosts, rects and proxies');
});
await check('a_proxy_never_hangs_past_its_host', async () => {
  // The pool house (gables, windows, board-and-batten): a full-height batten beside a window
  // once took the short wall piece under the window as its host. Its faces clamped to that
  // piece's edge row, and the batten read as one dark line from the band to the ridge. A
  // batten's front also took the buried end of the wall piece beside it (nearer than the wall,
  // but turned 90 degrees and dark): a host faces the way its proxy faces, and is broad.
  const p = JSON.parse(readFileSync(process.argv[2])).poolHouse, house = buildTwin(p, kit, 'high', {viewing: true});
  await house.ready; house.root.updateMatrixWorld(true);
  const pool = buildAtlas(house.root, p, options), W = (m, i) => new THREE.Vector3().fromBufferAttribute(m.geometry.attributes.position, i).applyMatrix4(m.matrixWorld);
  let count = 0, worst = 0, worstAt = null, turned = 0, narrow = 0;
  const faceNormal = (m, f) => { const a = W(m, f * 3); return W(m, f * 3 + 1).sub(a).cross(W(m, f * 3 + 2).sub(a)).normalize(); };
  for (const c of pool.room.charts) {
    if (!c.proxies) continue;
    const v0 = W(c.mesh, c.faces[0] * 3), n = faceNormal(c.mesh, c.faces[0]);
    if (Math.min(c.rect.w, c.rect.h) < 4) narrow++;
    for (const x of c.proxies) if (x.faces.some(f => faceNormal(x.mesh, f).dot(n) < .9)) turned++;
    const axis = Math.abs(n.y) < .9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
    const u = axis.addScaledVector(n, -axis.dot(n)).normalize(), v = n.clone().cross(u);
    let mu = Infinity, Mu = -Infinity, mv = Infinity, Mv = -Infinity;
    for (const f of c.faces) for (let k = 0; k < 3; k++) { const q = W(c.mesh, f * 3 + k);
      mu = Math.min(mu, q.dot(u)); Mu = Math.max(Mu, q.dot(u)); mv = Math.min(mv, q.dot(v)); Mv = Math.max(Mv, q.dot(v)); }
    for (const x of c.proxies) for (const f of x.faces) for (let k = 0; k < 3; k++) {
      const q = W(x.mesh, f * 3 + k), a = q.dot(u), b = q.dot(v), over = Math.max(mu - a, a - Mu, mv - b, b - Mv) / FT;
      count++; if (over > worst) { worst = over; worstAt = [x.mesh.material.name, c.mesh.material.name, ...q.toArray().map(t => +(t / FT).toFixed(1))]; }
    }
  }
  assert.ok(count > 500, `pool house proxy corners: ${count}`);
  assert.equal(turned, 0, 'every proxy faces the way its host faces');
  assert.equal(narrow, 0, 'and every host is at least four texels across');
  assert.ok(worst <= .26, `no proxy reaches more than a quarter foot past its host: ${worst.toFixed(2)} ft (${worstAt})`);
});
console.log(`${passed}/${ran} passed`);
process.exit(passed === ran ? 0 : 1);
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_bake_proxy_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit, 'poolHouse': household_pool_house()}),
                        encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True,
                                text=True, timeout=600)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr[-3000:])
        return result.returncode


if __name__ == '__main__':
    sys.exit(run())
