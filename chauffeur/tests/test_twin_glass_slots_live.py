"""Glass/slots Chromium scenarios. A4 writes L1; Claude runs it at landing.

Run from chauffeur/: python tests/test_twin_glass_slots_live.py
Uses the real Library page, HTTP writes, image decode and WebGL preview.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_glass_slots_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from PIL import Image, ImageDraw  # noqa: E402
from live_app import live_app  # noqa: E402

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
OUTPUT = Path(os.environ['GLASS_SLOTS_OUTPUT']) if 'GLASS_SLOTS_OUTPUT' in os.environ else Path(
    tempfile.mkdtemp(prefix='chauffeur_glass_slots_shots_'))
STATE = {}
SERVED = None


def _unexpected(errors):
    return [e for e in errors if not e.startswith('Failed to load resource')]


def _seed():
    from services import storage, twin_library, twin_materials
    from test_twin_view_live import _stub_urlopen
    # Built-in catalogue thumbnails use the twin's tiny offline JPEG fixtures.
    twin_library._urlopen = _stub_urlopen
    storage.patch_settings({'auth_enforce': True})
    storage.add_member({'id': 'alpha-parent', 'name': 'Pat', 'role': 'parent', 'email': 'pat@example.com'})
    storage.set_member_password('alpha-parent', 'correct horse battery staple')
    STATE['token'] = storage.create_member_token('alpha-parent')
    for key, name in [('blend', 'Preview glass'), ('leaf', 'Leaf cutout')]:
        STATE[key] = twin_materials.create({'name': name, 'params': {'tint': '#e8f5d4'}}, 'alpha-parent')['id']
    # The recorded house has a gable main roof and a separate shed porch roof.
    # Keep its rooms, openings, porch and yard for the wall-size editor screenshot.
    from services import twin_store
    plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    building = next(b for b in plan['buildings'] if b['id'] == 'pool-house')
    for key, kind, name, tint in [('roof_main', 'gable', 'Main roof shingles', '#635b55'),
                                   ('roof_porch', 'shed', 'Porch roof metal', '#85949b')]:
        section = next(s for s in building['roof']['sections'] if s['kind'] == kind)
        section['name'] = 'Main roof' if kind == 'gable' else 'Porch roof'
        section.pop('material', None)
        STATE[key] = section['id']
        STATE[key + '_material'] = twin_materials.create(
            {'name': name, 'params': {'tint': tint, 'roughness': .8 if kind == 'gable' else .4}},
            'alpha-parent')['id']
    twin_store.push_round(plan, 'build')


def _serve():
    global SERVED
    if SERVED is None:
        SERVED = live_app(_seed)
    return SERVED


def _settle(page):
    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


def _pixel(canvas):
    # Canvas screenshots work with WebGL's default preserveDrawingBuffer=false.
    image = Image.open(io.BytesIO(canvas.screenshot())).convert('RGB')
    return image.getpixel((image.width // 2, image.height // 2))


def _number(page, key, value):
    page.locator(f'[data-param="{key}"][type="range"]').evaluate('''(input, value) => {
        input.value = String(value); input.dispatchEvent(new Event('input', {bubbles: true}));
    }''', value)
    _settle(page)


def _saved(page, mid, mode, opacity=None):
    page.wait_for_function('''async ({mid, mode, opacity}) => {
        const response = await fetch(window.chfBase + 'api/house/materials/' + mid);
        if (!response.ok) return false;
        const row = await response.json();
        return row.params.alpha_mode === mode && (opacity === null || row.params.opacity === opacity);
    }''', arg={'mid': mid, 'mode': mode, 'opacity': opacity}, timeout=15000)


def scenario_L1_library_blend_and_leaf_cutout():
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for L1 visual verification')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as page:
        # Match house_editor_model_harness.signed_in: a real parent session.
        page.add_init_script('''if (location.protocol.startsWith('http')) { try {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        } catch (e) {} }''' % json.dumps(STATE['token']))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(served.url('house/library?material=' + STATE['blend']))
        page.wait_for_function('() => !!window.materialLibraryPage')
        page.evaluate('() => window.materialLibraryPage.ready')
        page.locator('[data-action="wall"]').click()
        canvas = page.locator('#material-library canvas')
        mode = page.locator('[data-param="alpha_mode"]')
        _settle(page)
        opaque = _pixel(canvas)
        mode.select_option('blend')
        opacity = page.locator('[data-param="opacity"][type="range"]')
        opacity.wait_for(state='visible')
        _number(page, 'opacity', .4)
        _saved(page, STATE['blend'], 'blend', .4)
        blended = _pixel(canvas)
        assert sum(abs(a - b) for a, b in zip(opaque, blended)) > 12, (opaque, blended)
        page.screenshot(path=str(OUTPUT / 'L1-library-blend-dark.png'), full_page=True)

        page.locator(f'[data-material="{STATE["leaf"]}"]').click()
        page.wait_for_function("() => document.querySelector('[data-field=\"name\"]')?.value === 'Leaf cutout'")
        image = Image.new('RGBA', (64, 64), (40, 130, 60, 0))
        ImageDraw.Draw(image).ellipse((8, 6, 52, 58), fill=(40, 130, 60, 255))
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        page.locator('[data-slot="base_color"] input[type="file"]').set_input_files({
            'name': 'leaf_basecolor.png', 'mimeType': 'image/png', 'buffer': buf.getvalue()})
        _saved(page, STATE['leaf'], 'cutout')
        page.wait_for_function("() => document.querySelector('[data-param=\"alpha_mode\"]')?.value === 'cutout'")
        assert mode.input_value() == 'cutout'
        mask = page.locator('[data-slot="opacity"] img')
        mask.wait_for(state='visible')
        page.wait_for_function("() => {const img=document.querySelector('[data-slot=\"opacity\"] img'); return img?.complete && img.naturalWidth > 0;}")
        assert 'From the base colour' in page.locator('[data-slot="opacity"]').inner_text()
        assert page.locator('[data-param="alpha_cutoff"][type="range"]').is_visible()
        page.screenshot(path=str(OUTPUT / 'L1-library-leaf-dark.png'), full_page=True)
        assert not _unexpected(errors), _unexpected(errors)
        assert not served.errors(), served.errors()


def scenario_L_roof_two_materials():
    """Set two ordinary Library materials through the existing roof card row."""
    served = _serve()
    if served is None:
        raise AssertionError('Chromium is required for roof material visual verification')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with served.browser(launch_args=GPU_ARGS, color_scheme='dark') as page:
        page.set_viewport_size({'width': 1920, 'height': 1080})
        page.add_init_script('''if (location.protocol.startsWith('http')) { try {
            localStorage.setItem('chauffeur_admin_token', %s);
            localStorage.setItem('chauffeur_admin_token_for', 'alpha-parent');
            localStorage.setItem('chauffeur_theme', 'dark');
        } catch (e) {} }''' % json.dumps(STATE['token']))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(served.url('house/editor?tier=high&test=1'))
        page.wait_for_function('() => window.__editor?.ready && window.__twinEditor && window.__twin?.ready', timeout=90000)
        if page.locator('#place-view').is_visible():
            page.locator('#place-close').click()
        for key in ['roof_main', 'roof_porch']:
            rid, mid = STATE[key], STATE[key + '_material']
            page.evaluate('(id) => window.__editor.clickPiece(id, "pool-house")', rid)
            row = page.locator('#piece-card .editor-material-line').filter(has=page.get_by_text('Roof', exact=True))
            row.get_by_role('button', name='Change the roof material', exact=True).click()
            page.locator(f'#library-entries [data-material="{mid}"]').click()
            page.locator('#material-chooser').get_by_role('button', name='This roof', exact=True).click()
            page.wait_for_function('''({rid, mid}) => {
                const b = window.__twin.plan.buildings.find(b => b.id === 'pool-house');
                return b.roof.sections.some(s => (s.id === rid || s.roof === rid) && s.material?.id === mid);
            }''', arg={'rid': rid, 'mid': mid})
            # The Library panel stays open after a pick and covers the piece card.
            if page.locator('#library-panel').is_visible():
                page.locator('#rail-library').click()
        expected = sorted([STATE['roof_main_material'], STATE['roof_porch_material']])
        page.wait_for_function('''expected => {
            const ids = new Set();
            window.__twin.scene.traverse(o => {
                if (!o.isMesh || o.layers.isEnabled(31) || o.material?.name !== 'roof') return;
                let b = o; while (b && !b.userData.buildingId) b = b.parent;
                if (b?.userData.buildingId === 'pool-house' && o.material.userData.materialId)
                    ids.add(o.material.userData.materialId);
            });
            return JSON.stringify([...ids].sort()) === JSON.stringify(expected);
        }''', arg=expected)
        page.evaluate('''() => {
            const view = window.__twin, b = view.plan.buildings.find(b => b.id === 'pool-house');
            const angle = (b.rotation || 0) * Math.PI / 180;
            const world = ([x,y,z]) => [
                (Math.cos(angle)*x-Math.sin(angle)*y+b.position[0])*.3048,
                (z+(b.base||0))*.3048,
                -(Math.sin(angle)*x+Math.cos(angle)*y+b.position[1])*.3048];
            view.setCamera('front');
            view.setCameraState({position:world([65,-48,46]),target:world([19,11,7])});
        }''')
        _settle(page)
        # The line names the material the person made, never its id.
        page.locator('#piece-card .editor-material-line').get_by_text('Porch roof metal, set here').wait_for()
        page.screenshot(path=str(OUTPUT / 'L-roof-two-materials-dark-wall.png'), full_page=True)
        assert not _unexpected(errors), _unexpected(errors)
        assert not served.errors(), served.errors()


if __name__ == '__main__':
    failed = 0
    scenarios = [scenario_L1_library_blend_and_leaf_cutout, scenario_L_roof_two_materials]
    for scenario in scenarios:
        try:
            scenario()
            print('ok  ', scenario.__name__)
        except Exception:
            failed += 1
            traceback.print_exc()
            print('FAIL', scenario.__name__)
    print(f'{len(scenarios) - failed}/{len(scenarios)} passed')
    print(f'Screenshots: {OUTPUT}')
    sys.exit(bool(failed))
