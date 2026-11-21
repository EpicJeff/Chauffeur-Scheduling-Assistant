"""A render nested inside a material's setup must not move the next material's texture units.

Owner, 2026-11-20 (desktop, ANGLE D3D11, 16 texture units): `Trying to use 17 /
18 / 19 texture units while this GPU supports only 16` on the pool water,
with no bake in the house. Traced in Chromium on the owner's house: the
water's setProgram resets the unit counter, then three regenerates the
reflection probe's PMREM (a nested renderer.render) inside the same
setProgram. At the end of that nested render three r187 restored the counter
the OUTER render had at its start (the last material of the previous frame,
9 units), not the counter at the nesting point (0). The water's twelve
samplers then took units 9..20, and on a 16-unit GPU the last five never
bound. The vendored three.module.js now restores the value the nested render
saw at its own start (VENDORED.md lists the patch).

This draws the same sequence with the vendored three in Chromium: a frame
whose last material uses nine textures, then a cube capture, then a frame
with a material whose envMap is that capture. The envMap must sit on a low
unit, not after the previous frame's nine.

Run from chauffeur/: python tests/test_twin_texture_units_live.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'static/vendor/three-r187'
ORIGIN = 'http://three.test/'

PAGE = """<!doctype html><html><body><script type="module">
import * as THREE from './three.module.js';
const renderer = new THREE.WebGLRenderer();
renderer.setSize(64, 64);
const gl = renderer.getContext();
const texel = () => { const t = new THREE.DataTexture(new Uint8Array([200, 200, 200, 255]), 1, 1); t.needsUpdate = true; return t; };
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, .1, 100); camera.position.set(0, 0, 5);
// Nine samplers: the counter is at nine when the frame ends.
const many = new THREE.MeshStandardMaterial({ map: texel(), normalMap: texel(), roughnessMap: texel(), metalnessMap: texel(),
  aoMap: texel(), emissiveMap: texel(), alphaMap: texel(), bumpMap: texel(), lightMap: texel(), transparent: true });
scene.add(new THREE.Mesh(new THREE.PlaneGeometry(1, 1), many));
renderer.render(scene, camera);
const target = new THREE.WebGLCubeRenderTarget(16);
new THREE.CubeCamera(.1, 10, target).update(renderer, scene);
// Its envMap is a fresh capture: three builds the PMREM inside this material's setProgram.
const probe = new THREE.MeshStandardMaterial({ envMap: target.texture, roughness: .4 });
const ball = new THREE.Mesh(new THREE.SphereGeometry(.5), probe); ball.position.x = 1.2;
scene.add(ball);
renderer.render(scene, camera);
const program = renderer.properties.get(probe).currentProgram.program;
const units = {}; const count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
for (let i = 0; i < count; i++) { const u = gl.getActiveUniform(program, i);
  if ([gl.SAMPLER_2D, gl.SAMPLER_CUBE, gl.SAMPLER_2D_ARRAY].includes(u.type)) units[u.name] = gl.getUniform(program, gl.getUniformLocation(program, u.name)); }
window.result = { units, samplers: Object.keys(units).length, error: gl.getError() };
</script></body></html>"""


def _serve(route):
    name = route.request.url[len(ORIGIN):].split('?')[0]
    if name == 'index.html':
        return route.fulfill(body=PAGE, content_type='text/html')
    path = VENDOR / name
    if path.is_file():
        return route.fulfill(path=str(path), content_type='text/javascript')
    return route.fulfill(status=404, body='')


def test_nested_pmrem_keeps_the_material_on_its_own_units():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('  skip  playwright not installed')
        return
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist'])
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route(ORIGIN + '**', _serve)
            page.goto(ORIGIN + 'index.html')
            page.wait_for_function('() => window.result', timeout=30000)
            result = page.evaluate('() => window.result')
        finally:
            browser.close()
    assert not errors, errors
    units = result['units']
    assert 'envMap' in units, units
    # Units belong to this material alone: every sampler sits below its own count.
    assert max(units.values()) < result['samplers'], units
    assert units['envMap'] < 9, units


if __name__ == '__main__':
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok  ', name)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print('FAIL', name, exc)
    print(f'{1 - failed}/1 passed')
    sys.exit(1 if failed else 0)
