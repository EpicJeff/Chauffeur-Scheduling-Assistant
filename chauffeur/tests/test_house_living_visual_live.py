"""Living-room day/night captures, draw budgets, and navigation-mask checks.

Run from chauffeur/: python tests/test_house_living_visual_live.py --out <dir>
Uses temporary fixture data and the shared house_probe renderer instrumentation.
Render submission timings are CPU measurements, not device FPS or GPU timings.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_living_review_')

from house_probe import _seed, THREE_WRAP, BUDGET_JS
from house_live_common import SEED_RNG_JS
from live_app import live_app
from services import ha_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=tempfile.mkdtemp(prefix='living_shots_'))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(_seed)
    assert served, 'Playwright is required for the visual review'
    from services import house_room
    payload = house_room.state(since_ts=0)
    three = (ROOT / 'static/vendor/three.min.js').read_bytes() + THREE_WRAP
    stats = {}
    try:
        for quality in ('high', 'low'):
            with served.browser(reduced_motion='reduce') as page:
                page.set_default_timeout(120000)
                page.add_init_script(SEED_RNG_JS)
                page.route('**/three.min.js*', lambda r: r.fulfill(
                    status=200, content_type='application/javascript', body=three))
                page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(
                    status=204, content_type='text/event-stream', body=''))
                page.route('**/api/house/state*', lambda r: r.fulfill(
                    status=200, content_type='application/json', body=json.dumps(payload)))
                for night in (False, True):
                    payload['window'] = {
                        'cond': 'clear-night' if night else 'sunny', 'night': night,
                        'temp': 72, 'calm': True, 'next_sun_change': None,
                    }
                    page.goto(served.url('house?quality=' + quality),
                              wait_until='domcontentloaded', timeout=120000)
                    page.wait_for_function('window.chfNavProbe && chfNavProbe({settled:true})')
                    page.evaluate("chfHouseEnterRoom('living')")
                    page.wait_for_function("chfHouseMode()==='living' && chfNavProbe({settled:true})")
                    page.wait_for_function("document.querySelectorAll('.house-hint').length>0")
                    page.wait_for_function('''() => {
                        const labels=Array.from(document.querySelectorAll('.house-hint-label')).map(e=>e.textContent.trim());
                        return ['Radio','Critters','Home ledger','Program book'].every(label=>labels.includes(label));
                    }''')
                    page.evaluate('chfCapture()')
                    name = quality + ('-night' if night else '-day')
                    page.screenshot(path=str(out / (name + '.png')))
                    result = stats[name] = page.evaluate(BUDGET_JS)
                    result['actualDraws'] = page.evaluate('window.__hpR.info.render.calls')
                    result['pointLights'] = page.evaluate('''() => {
                        let count=0;window.__hpScene.traverse(o=>{if(o.isPointLight)count++});
                        return count;
                    }''')
                    result['maskLeaks'] = page.evaluate("chfMaskLeak('living')")
                    result['renderSubmitMs'] = page.evaluate('''() => {
                        const r=window.__hpR, times=[];
                        for(let i=0;i<3;i++) {
                            const t=performance.now();r.render(window.__hpScene,window.__hpCam);
                            times.push(Math.round(performance.now()-t));
                        }
                        return times;
                    }''')
                    page.evaluate('chfHouseExit()')
                    page.wait_for_function("chfHouseMode()==='exterior' && chfNavProbe({settled:true})")
                    result['exitMaskLeaks'] = page.evaluate('chfMaskLeak(null)')
                    assert result['maskLeaks'] == result['exitMaskLeaks'] == 0, result
                    if quality == 'low':
                        assert result['pointLights'] == 0, result
                    assert not served.errors(), served.errors()
                    print(name, json.dumps(result), flush=True)
                    (out / 'stats.json').write_text(json.dumps(stats, indent=2), encoding='utf-8')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
