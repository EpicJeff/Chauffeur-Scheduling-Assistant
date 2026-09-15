"""Repeatable Study art-direction captures; uses isolated fixture storage."""
import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.pop('HA_BASE_URL', None)
os.environ.pop('HA_TOKEN', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='study_probe_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live_app import live_app

parser = argparse.ArgumentParser()
parser.add_argument('--out', default='../scratch/study-pass')
parser.add_argument('--active', action='store_true')
parser.add_argument('--night', action='store_true')
parser.add_argument('--quality', choices=['high', 'medium', 'low'], default='high')
args = parser.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
served = live_app()
with served.browser() as page:
    page.set_viewport_size({'width': 1400, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.add_init_script('Date.prototype.getHours = function () { return %d; };' % (22 if args.night else 14))
    from test_study_live import FURNITURE
    page.route('**/api/study/state', lambda r: r.fulfill(json={'furniture': FURNITURE if args.active else {}}))
    page.goto(served.url('study?quality=' + args.quality), wait_until='domcontentloaded')
    page.wait_for_function('window.STUDY && window.STUDY.renderer.info.render.calls > 0')
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out / 'overview.png'))
    if args.active:
        for zone in ('board', 'binders', 'tray'):
            page.evaluate('(z) => STUDY.leanInto(z)', zone)
            page.wait_for_timeout(4000)
            page.screenshot(path=str(out / (zone + '.png')))
    print(page.evaluate('({calls:STUDY.renderer.info.render.calls,triangles:STUDY.renderer.info.render.triangles,geometries:STUDY.renderer.info.memory.geometries,textures:STUDY.renderer.info.memory.textures})'))
    print('ERRORS', errors)
    assert not errors
