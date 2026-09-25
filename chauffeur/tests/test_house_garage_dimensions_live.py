"""Real model geometry: double/single width ratio and equal parking depths."""
import argparse
import base64
import json
import math
from pathlib import Path
from test_house_facade_live import live_app, _seed, DAY_LOCK_JS, SEED_RNG_JS
from services import house_facade as hf, ha_api


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True)
    out = Path(parser.parse_args().out).resolve(); out.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    row = json.loads((root/'static/house_hybrid/exterior-study/my-house-garage-corrected.json').read_text())
    spec = row['spec']
    assert not hf.validate_block_model(spec)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(_seed)
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.set_viewport_size({'width':1536, 'height':1024})
            page.add_init_script(DAY_LOCK_JS); page.add_init_script(SEED_RNG_JS)
            page.route('**/api/v2/chat/stream*', lambda r:r.fulfill(status=204, body=''))
            page.goto(served.url('house?quality=high&day=1&editor=1&angle=0&draft='+hf.issue_draft(spec)))
            page.wait_for_function('window.chfNavProbe && chfNavProbe({settled:true})', timeout=120000)
            assert page.evaluate('chfFacade()') == spec
            def extent(name, axis):
                vertices = page.evaluate('(n)=>chfFabricVertices(n)', name)
                assert vertices, name
                return max(v[axis] for v in vertices)-min(v[axis] for v in vertices)
            dimensions = {
                'main_door_width': extent('garage_block_west_head', 2),
                'single_door_width': extent('garage_popout_header', 0),
                # The full garage block slab, including the portion that the
                # interior navigation calls mudroom, defines parking depth.
                'main_bay_depth': extent('garage_void_floor', 0),
                'single_bay_depth': extent('garage_popout_floor', 2),
            }
            assert math.isclose(dimensions['main_door_width'], 6, abs_tol=.001), dimensions
            assert math.isclose(dimensions['single_door_width']/dimensions['main_door_width'], .5, abs_tol=.001), dimensions
            assert math.isclose(dimensions['main_bay_depth'], dimensions['single_bay_depth'], abs_tol=.001), dimensions
            assert math.isclose(dimensions['single_bay_depth'], 11.05, abs_tol=.001), dimensions
            assert extent('garage_popout_roof_end_west', 2) >= dimensions['single_bay_depth']
            for angle in (0,1,7):
                page.evaluate('(a)=>chfOrbitTo(a)', angle)
                page.wait_for_function('chfNavProbe({settled:true})', timeout=60000)
                page.wait_for_timeout(800)
                data = page.evaluate('chfCapture()')
                (out/f'model-{angle}.png').write_bytes(base64.b64decode(data.split(',',1)[1]))
            assert not served.errors(), served.errors()
            (out/'dimensions.json').write_text(json.dumps(dimensions, indent=2)+'\n')
            print('PASS:', dimensions, flush=True)
    finally: served.stop()


if __name__ == '__main__': main()
