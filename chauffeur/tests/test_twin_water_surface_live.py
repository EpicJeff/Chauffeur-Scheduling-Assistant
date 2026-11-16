"""Real editor WebGL water: tier motion, mapped materials, night and draw budget.

Run from chauffeur/: python tests/test_twin_water_surface_live.py.
All app data and screenshots belong to isolated temporary directories.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_water_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from PIL import Image, ImageChops, ImageStat  # noqa: E402
from live_app import live_app  # noqa: E402

OUTPUT = Path(os.environ.get('WATER_SURFACE_OUTPUT') or tempfile.mkdtemp(prefix='chauffeur_water_shots_'))
STATE = {}
SERVED = None
BASELINE = {path: subprocess.check_output(['git', 'show', 'HEAD:chauffeur/' + path],
            cwd=ROOT, encoding='utf-8') for path in
            ['static/twin/twin_yard.js', 'static/twin/pool_features.js']}


def _rect(x, y, width, height=None):
    height = height or width
    return [[x, y], [x+width, y], [x+width, y+height], [x, y+height]]


def _seed():
    from services import storage, twin_library, twin_materials, twin_store
    from test_twin_view_live import _stub_urlopen
    twin_library._urlopen = _stub_urlopen
    storage.patch_settings({'auth_enforce': True})
    storage.add_member({'id': 'water-parent', 'name': 'Water test', 'role': 'parent', 'email': 'water@example.com'})
    storage.set_member_password('water-parent', 'correct horse battery staple')
    STATE['token'] = storage.create_member_token('water-parent')
    STATE['water'] = twin_materials.create({'name': 'Pool water',
        'params': {'tint': '#7fd0e6', 'roughness': .1}}, 'water-parent')['id']
    STATE['tile'] = twin_materials.create({'name': 'Pool tile',
        'params': {'tint': '#e8e3cf', 'roughness': .45}}, 'water-parent')['id']
    plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    # Keep a real authored house in the editor, clear of the close water camera.
    for building in plan['buildings']:
        building['position'] = [100, 100]
    plan['site'] = {'lot': _rect(-12, -12, 70), 'pool': {
        'id': 'pool', 'polygon': _rect(0, 0, 32, 24), 'elevation': .12, 'depth': 5,
        'coping': 1, 'materials': {'water': {'id': STATE['water']}, 'interior': {'id': STATE['tile']}},
        'features': [{'id': 'ledge', 'kind': 'ledge', 'polygon': _rect(1, 1, 8, 5), 'depth_in': 12},
                     {'id': 'steps', 'kind': 'steps', 'polygon': _rect(1, 15, 7, 7), 'entry_edge': 0, 'treads': 3},
                     {'id': 'flush', 'kind': 'spa', 'polygon': _rect(24, 16, 8), 'mode': 'flush', 'depth_in': 36},
                     {'id': 'raised', 'kind': 'spa', 'polygon': _rect(24, 1, 8), 'mode': 'raised',
                      'raise_in': 18, 'depth_in': 36, 'spillover': False}]},
        'hardscape': [{'id': 'paving', 'polygon': _rect(-4, -4, 40, 32), 'material': 'paving'}]}
    twin_store.push_round(plan, 'build')
    # A flat plan does not own fixtures, so the fountain goes on the connected model.
    fountain = {'id': 'effect:7b0e5a52-6c1f-4f0e-9b5e-2f6d1c3a9e10', 'type': 'fountain', 'shape': 'point',
                'ref': 'absolute', 'at': [16, 10, -.13], 'size_min': 3, 'size_max': 3, 'strength': 1}
    twin_store.update_model(lambda model: {**model, 'effect_fixtures': [fountain]})
    assert twin_store.current_model().get('effect_fixtures'), 'the store dropped the fountain'


def _serve():
    global SERVED
    if SERVED is None:
        SERVED = live_app(_seed)
    return SERVED


def _settle(page):
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def _water_shot(page, name):
    canvas = page.locator('canvas[data-water-live]')
    image = Image.open(io.BytesIO(canvas.screenshot())).convert('RGB')
    # Central water only: exclude sky, UI and the simulation's off-screen targets.
    w, h = image.size
    image = image.crop((int(w*.27), int(h*.30), int(w*.67), int(h*.70)))
    image.save(OUTPUT / name)
    return image


def scenario_tier(tier):
    served = _serve()
    if served is None:
        raise AssertionError('Chromium unavailable: water was not visually verified')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=['--enable-gpu', '--use-angle=d3d11', '--ignore-gpu-blocklist']) as page:
        page.set_viewport_size({'width': 1600, 'height': 1000})
        page.add_init_script('''if(location.protocol.startsWith('http')) {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'water-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        }''' % json.dumps(STATE['token']))
        page.goto(served.url('house/editor?test=1&tier=' + tier))
        page.wait_for_function('() => window.__editor?.ready && window.__twin?.ready', timeout=90000, polling=500)
        if page.locator('#place-view').is_visible():
            page.locator('#place-close').click()
        page.evaluate('''() => {
            const v=window.__twin;v.renderer3.domElement.dataset.waterLive='1'; v.setClock('2026-06-21T16:00:00Z'); v.setTime('day');
            v.setCamera('front');v.setCameraState({position:[5,8,5], target:[4.8,-.1,-3.5]});
        }''')
        page.wait_for_timeout(1500)
        _settle(page)
        # Exercise mapped Library clones in the actual renderer. These three map
        # variants compile distinct USE_MAP/USE_NORMALMAP/USE_ROUGHNESSMAP paths.
        page.evaluate('''async () => {
            const THREE=await import('three'), v=window.__twin, yard=v.scene.getObjectByName('yard');
            const texture=new THREE.DataTexture(new Uint8Array([170,210,220,255,80,150,180,255,80,150,180,255,170,210,220,255]),2,2);
            texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.repeat.set(12,12);texture.needsUpdate=true;
            const normal=new THREE.DataTexture(new Uint8Array([128,128,255,255]),1,1);normal.needsUpdate=true;
            const materials=new Set();yard.traverse(o=>{if(o.isMesh&&o.material.userData.materialId)materials.add(o.material);});
            if(![...materials].some(m=>m.userData.waterSurface)||![...materials].some(m=>m.userData.underwater))throw Error('Library water/tile fixture missing');
            for(const m of materials){m.map=texture;m.normalMap=normal;m.roughnessMap=texture;m.needsUpdate=true;}
            window.__waterTestTextures=[texture,normal];v.renderer3.compile(v.scene,v.camera);v.render();
        }''')
        page.wait_for_timeout(1000)
        first = _water_shot(page, tier + '-water-a.png')
        page.wait_for_timeout(1100)
        second = _water_shot(page, tier + '-water-b.png')
        delta = sum(ImageStat.Stat(ImageChops.difference(first, second)).sum)
        if tier == 'low':
            assert delta == 0, ('lowest tier must remain still', delta)
        else:
            assert delta > 100, ('water must visibly move', tier, delta)
        result = page.evaluate(r'''async ({tier,baseline}) => {
            const v=window.__twin, yard=v.scene.getObjectByName('yard'), water=yard.userData.water;
            if(!water)throw Error('Missing water controller');
            if(water.simulations.size!==(tier==='high'?1:0))throw Error('Wrong simulation allocation');
            if(tier==='high'){
                const gl=v.renderer3.getContext();
                if(gl.getExtension('EXT_color_buffer_float')&&![...water.simulations.values()].every(s=>s.uniforms.waterFieldActive.value===1))throw Error('Capable GPU did not step the visible water');
            }
            const sourceUrl=path=>new URL(window.chfBase+path,location.href).href;
            const data=source=>'data:text/javascript;base64,'+btoa(unescape(encodeURIComponent(source)));
            const rewrite=(path,source,featureUrl)=>source.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,
                (_,a,s,b)=>a+(s==='./pool_features.js'?featureUrl:new URL(s,sourceUrl(path)).href)+b);
            const feature=data(rewrite('static/twin/pool_features.js',baseline['static/twin/pool_features.js']));
            const old=await import(data(rewrite('static/twin/twin_yard.js',baseline['static/twin/twin_yard.js'],feature)));
            const before=await old.buildYard(v.plan,{materials:{},manifest:window.twinManifest},tier);
            const count=g=>g.children.filter(o=>o.isMesh&&o.userData.yardPart==='pool').length;
            const poolBefore=count(before.group),poolAfter=count(yard);
            // The frame bound measures the same real camera/scene with HEAD's yard.
            yard.visible=false;yard.parent.add(before.group);v.render();const frameBefore=v.stats().drawCalls;
            before.group.removeFromParent();yard.visible=true;v.render();const frameAfter=v.stats().drawCalls;
            return {poolBefore,poolAfter,frameBefore,frameAfter,animated:water.surfaces[0].uniforms.waterTime.value};
        }''', {'tier': tier, 'baseline': BASELINE})
        assert result['poolAfter'] <= result['poolBefore'] + 6, result
        # At most six material/level splits, also drawn once by the shadow pass.
        assert result['frameAfter'] <= result['frameBefore'] + 12, result
        page.evaluate("() => {window.__twin.setTime('night');window.__twin.render();}")
        _settle(page)
        assert page.evaluate("() => window.__twin.scene.getObjectByName('yard').userData.water.submerged.every(row=>row.uniforms.waterSun.value===0)")
        _water_shot(page, tier + '-night.png')
        errors = [e for e in served.errors() if not e.startswith('Failed to load resource')]
        assert not errors, errors
        print('DRAW_BUDGET', tier, json.dumps(result), 'pixel_delta', delta)


if __name__ == '__main__':
    failed = 0
    for current in ['low', 'medium', 'high']:
        try:
            scenario_tier(current)
            print('ok  ', current)
        except Exception:
            failed += 1
            traceback.print_exc()
            print('FAIL', current)
    print(f'{3-failed}/3 passed; screenshots: {OUTPUT}')
    if SERVED:
        SERVED.stop()
    sys.exit(bool(failed))
