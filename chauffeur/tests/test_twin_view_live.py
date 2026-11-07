"""The twin preview in real Chromium: the plan-to-scene generator, the yard,
the Low and High tiers, floor cutaways, night lights, captures and the
library's offline fallback (spec docs/superpowers/specs/
2026-11-06-house-digital-twin-design.md sections 5.1, 8.3, 9.2; plan Task 7).

The seeded plan is the pool house fixture AFTER composition, so the Low
budget is measured with the composed yard (real EZ-Tree plants). Library
downloads are stubbed with tiny valid files: a 2x2 JPEG for every texture,
an empty glTF scene for every model, a 2x2 Radiance HDR for every sky.

Run from chauffeur/:  python tests/test_twin_view_live.py
"""
import io
import json
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_view_live_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_app import live_app  # noqa: E402

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json')
LOW_DRAW_CALLS = 120
LOW_TRIANGLES = 200_000
STATE = {'offline': False}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _jpeg(rgb=(150, 150, 140)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), rgb).save(buf, format='JPEG')
    return buf.getvalue()


def _hdr():
    return b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 2 +X 2\n' + bytes([128, 128, 128, 129]) * 4


EMPTY_GLTF = json.dumps({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}], 'scene': 0}).encode()


class _Resp:
    def __init__(self, data):
        self._d = data

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _stub_urlopen(req, timeout=None):
    if STATE['offline']:
        raise OSError('offline')
    url = req.full_url
    if url.endswith('.gltf'):
        return _Resp(EMPTY_GLTF)
    if url.endswith('.hdr'):
        return _Resp(_hdr())
    if '_nor_gl_' in url:
        return _Resp(_jpeg((128, 128, 255)))          # a flat normal map, not a tilted one
    return _Resp(_jpeg())


def _seed():
    from services import twin_compose, twin_library, twin_plan, twin_store
    twin_library._urlopen = _stub_urlopen
    with open(_FIXTURE, encoding='utf-8') as f:
        plan = twin_plan.normalize(json.load(f))[0]
    plan, _ = twin_compose.compose(plan, twin_library.kit('modern_farmhouse'), seed=1)
    twin_store.push_round(plan, 'draft')
    return plan


SERVED = None
PLAN = None


def _serve():
    global SERVED, PLAN
    if SERVED is None:
        holder = {}
        SERVED = live_app(lambda: holder.setdefault('plan', _seed()))
        PLAN = holder.get('plan')
    return SERVED


def _unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


def _open(page, served, query):
    page.goto(served.url(f'house/twin?{query}'))
    page.wait_for_function('window.__twin && window.__twin.ready === true', timeout=60000)
    time.sleep(1.0)


def _stats(page):
    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
    return page.evaluate('() => window.__twin.stats()')


def scenario_page_boots_and_draws_the_pool_house():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        st = _stats(page)
        print('    renderer:', page.evaluate('() => window.__twin.renderer || ""'))
        check(st['tier'] == 'high' and st['drawCalls'] > 0 and st['triangles'] > 0, st)
        meshes = page.evaluate('() => { let n = 0; window.__twin.scene.traverse(o => { if (o.isMesh) n++; }); return n; }')
        check(meshes > 20, f'a real model: {meshes} meshes')
    check(not _unexpected(s.errors()), s.errors())


def scenario_no_material_uses_transmission():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        bad = page.evaluate('''() => { const out = [];
            window.__twin.scene.traverse(o => { const ms = o.material ? [].concat(o.material) : [];
              ms.forEach(m => { if (m && m.transmission > 0) out.push(m.name || m.type); }); });
            return out; }''')
        check(bad == [], f'no transmission anywhere: {bad}')


def scenario_low_tier_holds_its_budget():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=low')
        for view, cam in (('ext', 'front'), ('ext', 'porch'), ('L1', 'top'), ('L2', 'top')):
            page.evaluate(f'() => {{ window.__twin.setView("{view}"); window.__twin.setCamera("{cam}"); }}')
            st = _stats(page)
            print(f'    low {view}/{cam}: {st["drawCalls"]} calls, {st["triangles"]} tris')
            check(st['tier'] == 'low', st)
            check(st['drawCalls'] <= LOW_DRAW_CALLS, f'{view}/{cam} draw calls {st["drawCalls"]} > {LOW_DRAW_CALLS}')
            check(st['triangles'] <= LOW_TRIANGLES, f'{view}/{cam} triangles {st["triangles"]} > {LOW_TRIANGLES}')
        shadows = page.evaluate('() => window.__twin.renderer3.shadowMap.enabled')
        check(shadows is False, 'Low draws no shadow map')
    check(not _unexpected(s.errors()), s.errors())


def scenario_views_cut_the_house():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        vis = '() => { const g = window.__twin.groups; return {roof: g.roof.visible, full: g.gableFull.visible, cut: g.gableCut.visible, L2: g.levels.L2.visible, L1: g.levels.L1.visible}; }'
        page.evaluate('() => window.__twin.setView("ext")')
        v = page.evaluate(vis)
        check(v['roof'] and v['full'] and not v['cut'] and v['L1'] and v['L2'], f'exterior: {v}')
        page.evaluate('() => window.__twin.setView("L2")')
        v = page.evaluate(vis)
        check(not v['roof'] and not v['full'] and v['cut'] and v['L2'] and v['L1'], f'upstairs: {v}')
        page.evaluate('() => window.__twin.setView("L1")')
        v = page.evaluate(vis)
        check(not v['roof'] and not v['full'] and not v['cut'] and not v['L2'] and v['L1'], f'ground floor: {v}')


def scenario_night_lights_rooms():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        page.evaluate('() => window.__twin.setTime("night")')
        n = page.evaluate('() => window.__twin.roomLights.filter(l => l.visible).length')
        want = sum(len(b['lights']) for b in PLAN['buildings'])
        check(n == want, f'{n} lit of {want} fixtures')
        page.evaluate('() => window.__twin.setTime("day")')
        check(page.evaluate('() => window.__twin.roomLights.filter(l => l.visible).length') == 0, 'off by day')


def scenario_capture_returns_pngs():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        shots = page.evaluate('() => window.__twin.capture(["front", "top"], 640, 400)')
        check(len(shots) == 2 and all(x.startswith('data:image/png;base64,') for x in shots), [x[:40] for x in shots])
        dims = page.evaluate('''async (u) => { const i = new Image(); i.src = u; await i.decode();
                                return [i.naturalWidth, i.naturalHeight]; }''', shots[0])
        check(dims == [640, 400], dims)
        if os.environ.get('TWIN_SHOTS'):
            import base64
            for name in ('front', 'porch', 'rear', 'top'):
                data = page.evaluate(f'() => window.__twin.capture(["{name}"], 1280, 800)')[0]
                with open(os.path.join(os.environ['TWIN_SHOTS'], f'high_{name}.png'), 'wb') as f:
                    f.write(base64.b64decode(data.split(',', 1)[1]))
    if os.environ.get('TWIN_SHOTS'):
        import base64
        with s.browser(launch_args=GPU_ARGS) as page:
            _open(page, s, 'tier=low')
            for name in ('front', 'porch', 'rear', 'top'):
                data = page.evaluate(f'() => window.__twin.capture(["{name}"], 1280, 800)')[0]
                with open(os.path.join(os.environ['TWIN_SHOTS'], f'low_{name}.png'), 'wb') as f:
                    f.write(base64.b64decode(data.split(',', 1)[1]))


def scenario_textured_materials_are_not_tinted_dark():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        page.wait_for_timeout(1500)
        tinted = page.evaluate('''() => { const out = [];
            window.__twin.scene.traverse(o => [].concat(o.material || []).forEach(m => {
              if (m && m.map && m.map.image && m.color && m.color.getHexString() !== 'ffffff') out.push(m.name || m.type); }));
            return out; }''')
        check(tinted == [], f'a loaded texture is shown as it is, never multiplied by the kit colour: {tinted[:5]}')


def scenario_captures_are_tone_mapped_like_the_screen():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        mean = '''async (u) => { const i = new Image(); i.src = u; await i.decode();
            const c = document.createElement('canvas'); c.width = 64; c.height = 40;
            const x = c.getContext('2d'); x.drawImage(i, 0, 0, 64, 40);
            const d = x.getImageData(0, 0, 64, 40).data; let t = 0;
            for (let k = 0; k < d.length; k += 4) t += d[k] + d[k + 1] + d[k + 2];
            return t / (d.length / 4) / 3; }'''
        page.evaluate('() => { window.__twin.renderer3.toneMappingExposure = 0.4; }')
        dark = page.evaluate(mean, page.evaluate('() => window.__twin.capture(["front"], 320, 200)')[0])
        page.evaluate('() => { window.__twin.renderer3.toneMappingExposure = 2.5; }')
        bright = page.evaluate(mean, page.evaluate('() => window.__twin.capture(["front"], 320, 200)')[0])
        check(bright - dark > 20, f'exposure reaches the capture (tone mapped like the screen): {dark:.1f} -> {bright:.1f}')


def scenario_ground_reaches_beyond_the_lot():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        hit = page.evaluate('''async () => { const THREE = await import('three');
            const r = new THREE.Raycaster(); const FT = 0.3048;
            r.set(new THREE.Vector3(200 * FT, 200, -0 * FT), new THREE.Vector3(0, -1, 0));
            const hits = r.intersectObject(window.__twin.scene, true);
            return hits.length ? hits[0].point.y : null; }''')
        check(hit is not None and abs(hit) < 1.0, f'ground under a point 60 ft outside the lot: {hit}')


def scenario_no_requests_go_one_level_too_deep():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        bad = []
        page.on('request', lambda r: ('/house/api/' in r.url or '/house/static/' in r.url) and bad.append(r.url))
        _open(page, s, 'tier=high')
        page.wait_for_timeout(1500)
        check(not bad, f'every URL is built from the page base (admin gate included): {bad[:4]}')


def scenario_rebuilds_do_not_leak():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s, 'tier=high')
        mem = '() => ({g: window.__twin.renderer3.info.memory.geometries, t: window.__twin.renderer3.info.memory.textures})'
        page.evaluate('async () => { const p = window.__twin.plan; await window.__twin.rebuild(p); }')
        page.wait_for_timeout(800)
        first = page.evaluate(mem)
        for _ in range(3):
            page.evaluate('async () => { const p = window.__twin.plan; await window.__twin.rebuild(p); }')
            page.wait_for_timeout(800)
        last = page.evaluate(mem)
        check(last['g'] <= first['g'] and last['t'] <= first['t'], f'geometries/textures flat across rebuilds: {first} -> {last}')


def scenario_probe_posts_a_result():
    s = _serve()
    if s is None:
        return
    from services import auth
    check(auth.resolve('POST', '/api/house/twin/perf') == auth.WALL_OR_SERVICE, 'a panel may post its own numbers')
    check(auth.resolve('GET', '/api/house/twin/perf') == auth.PARENTS, 'reading them is for parents')
    with s.browser(launch_args=GPU_ARGS) as page:
        page.goto(s.url('house/twin?tier=low&probe=1&probe_s=3&hud=1'))
        page.wait_for_function('window.__twinProbe && window.__twinProbe.posted === true', timeout=90000)
        check(page.is_visible('#twin-hud'), 'the hud shows fps and draw calls')
        res = page.request.get(s.url('api/house/twin/perf')).json()
    rows = res.get('results', [])
    check(len(rows) >= 1, res)
    r = rows[-1]
    check(r['tier'] == 'low' and r['fpsAvg'] > 0 and r['fpsP5'] > 0 and r['drawCalls'] > 0 and r['triangles'] > 0
          and r['gpu'] and r['ua'] and r['at'], r)


def scenario_library_urls_carry_the_device_token():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        seen = []
        page.on('request', lambda r: '/api/house/twin/library/' in r.url and seen.append(r.url))
        page.add_init_script("localStorage.setItem('chauffeur_device_token', 'probe-device')")
        _open(page, s, 'tier=high')
        check(seen, 'library assets were requested')
        missing = [u for u in seen if 'device_token=probe-device' not in u]
        check(not missing, f'loader URLs carry auth (chfAuthUrl): {missing[:3]}')


def scenario_page_draws_with_the_library_offline():
    s = _serve()
    if s is None:
        return
    from services import twin_store
    import shutil
    shutil.rmtree(os.path.join(twin_store.DATA_DIR, 'library'), ignore_errors=True)
    STATE['offline'] = True
    try:
        with s.browser(launch_args=GPU_ARGS) as page:
            _open(page, s, 'tier=high')
            st = _stats(page)
            check(st['drawCalls'] > 0, 'still draws with every asset missing')
        check(not _unexpected(s.errors()), s.errors())
    finally:
        STATE['offline'] = False


if __name__ == '__main__':
    for fn in (scenario_page_boots_and_draws_the_pool_house,
               scenario_no_material_uses_transmission,
               scenario_low_tier_holds_its_budget,
               scenario_views_cut_the_house,
               scenario_night_lights_rooms,
               scenario_capture_returns_pngs,
               scenario_textured_materials_are_not_tinted_dark,
               scenario_captures_are_tone_mapped_like_the_screen,
               scenario_ground_reaches_beyond_the_lot,
               scenario_no_requests_go_one_level_too_deep,
               scenario_rebuilds_do_not_leak,
               scenario_probe_posts_a_result,
               scenario_library_urls_carry_the_device_token,
               scenario_page_draws_with_the_library_offline):
        fn()
        print('  ok ', fn.__name__)
