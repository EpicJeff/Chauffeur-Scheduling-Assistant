"""The baked lights as a shadowmask, on the desktop GPU (real Chromium, real shaders).

The user, 2026-11-14, on the pool house gable at night: "The quality in the close compare
shot is still pretty rough" (mottled blotches, streaks along battens, muddy falloff). The bake
used to store irradiance (falloff x N.L x visibility, 8 bits, at the chart's density); now a
page stores only visibility, and the material lights each pixel as the live light does.

These checks run the real bake pass (bake/bake_pass.js renderPage) and the real material
patch (bake/lightmap_material.js patchLightmaps) on a bare scene in the twin page: a 12 x 8 ft
wall at z = 0 facing +z, charted at 8 texels/ft on a 256 page, and a point lamp 4 ft in
front of it. Nothing else in the house is drawn; the twin page only provides the import map.

  visibility_is_a_fraction_of_the_lamp     every stored texel is in 0..255; an open wall reads
                                           fully lit without specks; a box casts an umbra and
                                           a soft penumbra
  a_lit_wall_follows_the_live_falloff      the patched material on that wall matches the live
                                           PointLight's diffuse term pixel by pixel (no
                                           mottling: the ratio barely varies)
  a_normal_map_turns_toward_the_lamp       a normal map tilted toward +x brightens under a lamp
                                           on the +x side and darkens under one on the -x side
  brightness_and_colour_need_no_rebake     the tint halves the light and colours it; no new
                                           program and no material version change
  a_proxy_shades_by_its_own_normal         a batten side reading the wall's texels is lit by
                                           its own normal, not the wall's
  an_unbaked_light_adds_nothing            a zero tint (the light is not fresh, so live lights
                                           draw it) contributes nothing: no double counting

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_shadowmask_live.py
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

SCENE = r"""
async () => {
  const THREE = await import('three'), B = window.chfBase;
  const P = await import(B + 'static/twin/bake/bake_pass.js');
  const M = await import(B + 'static/twin/bake/lightmap_material.js');
  const FT = .3048, SIZE = 256, DENSITY = 8, W = 12, H = 8, RECT = { x: 2, y: 2, w: W * DENSITY, h: H * DENSITY };
  const CANDELA = 40, REACH = 30 * FT;
  const renderer = new THREE.WebGLRenderer({ antialias: false });
  renderer.setSize(64, 64); renderer.toneMapping = THREE.NoToneMapping;
  const out = {};
  const plane = (w, h, transform, uv) => {
    const g = new THREE.PlaneGeometry(w * FT, h * FT).toNonIndexed(); transform(g);
    g.setAttribute('uv3', new THREE.Float32BufferAttribute(Array.from({ length: g.attributes.position.count }, (_, i) => uv(
      new THREE.Vector3().fromBufferAttribute(g.attributes.position, i))).flat(), 2));
    g.setAttribute('lmRoom', new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count), 1));
    return g;
  };
  const wallUV = p => [(RECT.x + p.x / FT * DENSITY) / SIZE, (RECT.y + p.y / FT * DENSITY) / SIZE];
  const wallGeometry = () => plane(W, H, g => g.translate(W * FT / 2, H * FT / 2, 0), wallUV);
  const lamp = at => ({ device: 'lamp', absolute: true, at: [at[0], -at[2], at[1]], range: 30 });
  async function bake(at, blockers = []) {
    const scene = new THREE.Scene(), wall = new THREE.Mesh(wallGeometry(), new THREE.MeshStandardMaterial({ name: 'siding' }));
    wall.userData.merged = true; scene.add(wall);
    for (const b of blockers) { b.userData.merged = true; scene.add(b); }
    scene.updateMatrixWorld(true);
    const chart = { id: 0, mesh: wall, faces: [0, 1], rect: RECT, page: 0, room: 0, outdoor: false };
    const bytes = await P.renderPage({ scene, plan: {} }, renderer, [chart], SIZE, lamp(at), { room: { page: SIZE } }, { room: { charts: [chart] } });
    const vis = [];
    for (let y = RECT.y; y < RECT.y + RECT.h; y++) for (let x = RECT.x; x < RECT.x + RECT.w; x++) vis.push(bytes[(y * SIZE + x) * 4]);
    return { bytes, vis };
  }
  // --- visibility ---
  const open = await bake([6, 4, 4]);
  const box = new THREE.Mesh(new THREE.BoxGeometry(1 * FT, 1 * FT, 1 * FT), new THREE.MeshStandardMaterial({ name: 'siding' }));
  box.position.set(6 * FT, 4 * FT, 1.5 * FT);
  const shaded = await bake([6, 4, 4], [box]);
  out.visibility = { openMin: Math.min(...open.vis), openBelow250: open.vis.filter(v => v < 250).length, count: open.vis.length,
    allBytes: open.vis.every(v => v >= 0 && v <= 255),
    umbra: shaded.vis.filter(v => v === 0).length, penumbra: shaded.vis.filter(v => v > 10 && v < 245).length, lit: shaded.vis.filter(v => v === 255).length };
  // --- shading ---
  const page = new THREE.DataArrayTexture(new Uint8Array(SIZE * SIZE * 4), SIZE, SIZE, 1);
  for (let i = 0; i < SIZE * SIZE; i++) page.image.data[i * 4] = open.bytes[i * 4];
  page.format = THREE.RGBAFormat; page.minFilter = page.magFilter = THREE.LinearFilter; page.generateMipmaps = false; page.needsUpdate = true;
  const packed = { banks: [{ charts: [{ id: 0, page: 0, rect: RECT, sourceRegion: RECT }] }], slots: { lamp: { assignments: [{ chart: 0, bank: 0, channel: 0 }] } } };
  const uniforms = M.chartLightmapUniforms(1, packed, [{ device: 'lamp' }], SIZE, [[0]]);
  const source = at => new THREE.Vector3(at[0] * FT, at[1] * FT, at[2] * FT);
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], 1);
  const target = new THREE.WebGLRenderTarget(48, 32, { type: THREE.FloatType });
  const view = (mesh, camera) => {
    const scene = new THREE.Scene(); scene.add(mesh); renderer.setRenderTarget(target); renderer.setClearColor(0, 0); renderer.clear();
    renderer.render(scene, camera); const px = new Float32Array(48 * 32 * 4); renderer.readRenderTargetPixels(target, 0, 0, 48, 32, px);
    renderer.setRenderTarget(null); return px;
  };
  const front = new THREE.OrthographicCamera(0, W * FT, H * FT, 0, .1, 10); front.position.set(0, 0, 5); front.updateMatrixWorld(true);
  const patched = extra => { const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, metalness: 0, ...extra }); M.patchLightmaps([m], { banks: [page] }, uniforms); return m; };
  const expected = (p, n, at) => { const l = source(at).sub(p), d = l.length();
    return CANDELA * Math.max(0, 1 - (d / REACH) ** 4) ** 2 / Math.max(d * d, .01) * Math.max(0, n.dot(l.normalize())) / Math.PI; };
  const flat = patched(), wall = new THREE.Mesh(wallGeometry(), flat);
  M.setLightSource(uniforms, 0, 0, source([6, 4, 4]), REACH);
  const px = view(wall, front), ratios = [];
  for (let j = 2; j < 30; j++) for (let i = 2; i < 46; i++) {
    const p = new THREE.Vector3((i + .5) / 48 * W * FT, (j + .5) / 32 * H * FT, 0);
    ratios.push(px[(j * 48 + i) * 4] / expected(p, new THREE.Vector3(0, 0, 1), [6, 4, 4]));
  }
  const mean = ratios.reduce((a, b) => a + b, 0) / ratios.length;
  out.falloff = { mean, std: Math.sqrt(ratios.reduce((a, b) => a + (b - mean) ** 2, 0) / ratios.length), min: Math.min(...ratios), max: Math.max(...ratios) };
  // --- brightness and colour ---
  const programs = renderer.info.programs.length, version = flat.version, centre = (j, i) => (j * 48 + i) * 4;
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], .5); const half = view(wall, front);
  M.setLightTint(uniforms, 0, 0, [255, 0, 0], 1); const red = view(wall, front);
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], 0); const off = view(wall, front);
  out.tint = { full: px[centre(16, 24)], half: half[centre(16, 24)], redR: red[centre(16, 24)], redG: red[centre(16, 24) + 1],
    off: Math.max(...off.filter((v, i) => i % 4 < 3)), programs: [programs, renderer.info.programs.length], versions: [version, flat.version] };
  M.setLightTint(uniforms, 0, 0, [255, 255, 255], 1);
  // --- normal map: a constant tangent-space normal leaning 30 degrees toward +x (u) ---
  const tilt = new THREE.DataTexture(new Uint8Array([Math.round((.5 + .5 * .5) * 255), 128, Math.round((.5 + .5 * .866) * 255), 255]), 1, 1);
  tilt.needsUpdate = true;
  const bumpy = new THREE.Mesh(wallGeometry(), patched({ normalMap: tilt }));
  const at = side => { M.setLightSource(uniforms, 0, 0, source([side, 4, 2]), REACH); return [view(wall, front)[centre(16, 24)], view(bumpy, front)[centre(16, 24)]]; };
  const east = at(11), west = at(1);
  out.normalMap = { east, west };
  M.setLightSource(uniforms, 0, 0, source([6, 4, 4]), REACH);
  // --- a proxy: a 0.5 ft batten side facing +x at x = 3 ft, reading the wall's texels there ---
  const sideUV = p => wallUV(new THREE.Vector3(3 * FT, p.y, 0));
  const side = new THREE.Mesh(plane(.5, H, g => { g.rotateY(Math.PI / 2); g.translate(3 * FT, H * FT / 2, .25 * FT); }, sideUV), patched());
  const eastCam = new THREE.OrthographicCamera(-.25 * FT, .25 * FT, H * FT, 0, .1, 10); eastCam.position.set(3 * FT + 2, 0, .25 * FT); eastCam.lookAt(-10, 0, .25 * FT);
  eastCam.updateMatrixWorld(true);
  M.setLightSource(uniforms, 0, 0, source([11, 4, 4]), REACH);
  const sidePx = view(side, eastCam), row = 16, p = new THREE.Vector3(3 * FT, (row + .5) / 32 * H * FT, .25 * FT);
  out.proxy = { got: sidePx[centre(row, 24)], own: expected(p, new THREE.Vector3(1, 0, 0), [11, 4, 4]), host: expected(p, new THREE.Vector3(0, 0, 1), [11, 4, 4]) };
  renderer.dispose();
  return out;
}
"""


def run():
    served = L.serve()
    L.reset()
    failures = []
    with served.browser(launch_args=L.GPU_ARGS) as page:
        page.set_viewport_size({'width': 1200, 'height': 800})
        L.H.signed_in(page)
        L.open_twin(page, served, query='tier=high&test=1')
        result = page.evaluate(SCENE)
    print('MEASURED', json.dumps(result))
    v, f, t, n, p = result['visibility'], result['falloff'], result['tint'], result['normalMap'], result['proxy']

    def check(name, fn):
        try:
            fn()
            print('  ok   ' + name)
        except AssertionError as error:
            failures.append(name)
            print('  FAIL ' + name + ' ' + str(error)[:600])
            traceback.print_exc(limit=1)

    def visibility():
        assert v['allBytes'], 'every stored texel is a visibility byte'
        assert v['openBelow250'] <= v['count'] * .005, f'an open wall reads fully seen, no specks: {v}'
        assert v['umbra'] > 50 and v['penumbra'] > 20 and v['lit'] > v['count'] / 2, f'a box casts an umbra and a soft edge: {v}'

    def falloff():
        assert abs(f['mean'] - 1) < .04, f'the wall matches the live light: {f}'
        assert f['std'] < .02 and f['min'] > .93 and f['max'] < 1.07, f'and evenly, with no mottling: {f}'

    def normal_map():
        assert n['east'][1] > n['east'][0] * 1.1, f'tilted toward +x: brighter under the east lamp {n}'
        assert n['west'][1] < n['west'][0] * .9, f'and darker under the west one {n}'

    def tint():
        assert abs(t['half'] / t['full'] - .5) < .01, f'brightness halves the light: {t}'
        assert t['redR'] > 0 and t['redG'] == 0, f'and colour colours it: {t}'
        assert t['programs'][0] == t['programs'][1] and t['versions'][0] == t['versions'][1], f'with no new program: {t}'

    def proxy():
        assert abs(p['got'] / p['own'] - 1) < .05, f'a batten side is lit by its own normal: {p}'
        assert abs(p['got'] - p['host']) > p['own'] * .2, f'not the wall\'s: {p}'

    def unbaked():
        assert t['off'] == 0, f'a zero tint adds nothing: {t}'

    check('visibility_is_a_fraction_of_the_lamp', visibility)
    check('a_lit_wall_follows_the_live_falloff', falloff)
    check('a_normal_map_turns_toward_the_lamp', normal_map)
    check('brightness_and_colour_need_no_rebake', tint)
    check('a_proxy_shades_by_its_own_normal', proxy)
    check('an_unbaked_light_adds_nothing', unbaked)
    print(f'{6 - len(failures)}/6 passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(run())
