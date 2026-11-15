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
OUTPUT = Path(os.environ.get('GLASS_SLOTS_OUTPUT', ROOT / '.tmp-a4/glass-slots-live'))
STATE = {}
SERVED = None


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
        assert not errors, errors
        assert not served.errors(), served.errors()


if __name__ == '__main__':
    failed = 0
    for scenario in [scenario_L1_library_blend_and_leaf_cutout]:
        try:
            scenario()
            print('ok  ', scenario.__name__)
        except Exception:
            failed += 1
            traceback.print_exc()
            print('FAIL', scenario.__name__)
    print(f'{1 - failed}/1 passed')
    sys.exit(bool(failed))
