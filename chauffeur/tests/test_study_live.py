"""Study quality pass: real GPU lifecycle, zone detail reuse, and fallback."""
import os
import tempfile
from pathlib import Path
import sys

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='study_live_'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_app import live_app

FURNITURE = {
    'board': {'pins': [{'kind': 'insight', 'label': 'Plan the fall schedule', 'warn': True}]},
    'desk': [{'line': 'Prepare the weekend', 'open_steps': 2, 'due': True}],
    'tray': {'count': 1, 'items': [{'title': 'School permission form'}]},
    'stickies': {'count': 1, 'worst': 'approve', 'items': [{'line': 'Review the outing'}]},
    'calendar': {'days': [{'date': '2026-09-14', 'unassigned': 1, 'events': []}]},
    'window': {'ready': True, 'worse': [], 'label': 'A steady week', 'signs': []},
    'keys': [{'name': 'Family car', 'low': True, 'fuel_pct': 18}],
    'contracts': {'count': 1, 'items': [{'title': 'Weekend agreement'}]},
    'binders': [{'title': 'Piano', 'pulled': True, 'week': 2}],
    'gauges': {'think': 2, 'think_cap': 10, 'research': 1, 'research_cap': 10, 'ingest_errors': 0},
    'monitor': {'clusters': [{'name': 'Jordan', 'count': 3}]},
    'map': {'trips': [{'id': 'trip1', 'title': 'Fall break', 'location': 'Mountains', 'upcoming': True}]},
}


def main():
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_viewport_size({'width': 1400, 'height': 1000})
        page.route('**/api/study/state', lambda route: route.fulfill(json={'furniture': FURNITURE}))
        page.goto(served.url('study'), wait_until='domcontentloaded')
        page.wait_for_function('window.STUDY && STUDY.zones.binders.summary')
        page.wait_for_timeout(5500)
        frames = page.evaluate('STUDY.renderer.info.render.frame')
        page.wait_for_timeout(600)
        assert page.evaluate('STUDY.renderer.info.render.frame') == frames, 'quiet Study must stop rendering'
        assert page.evaluate('STUDY.renderer.getPixelRatio()') == 1
        # Every semantic target paints and reuses its canvases after a visit.
        for zone in FURNITURE:
            assert page.evaluate('(z) => STUDY.leanInto(z)', zone), zone
            page.wait_for_timeout(50)
        page.keyboard.press('Escape')
        page.wait_for_timeout(5000)
        memory = page.evaluate('({...STUDY.renderer.info.memory})')
        for zone in FURNITURE:
            assert page.evaluate('(z) => STUDY.leanInto(z)', zone), zone
            page.wait_for_timeout(50)
        page.keyboard.press('Escape')
        page.wait_for_timeout(5000)
        assert page.evaluate('({...STUDY.renderer.info.memory})') == memory, 'repeated visits must reuse GPU resources'
        assert page.evaluate('STUDY.leanedZone()') is None
        page.goto(served.url('study?quality=low'), wait_until='domcontentloaded')
        page.wait_for_function('window.STUDY && STUDY.renderer.info.render.calls > 0')
        assert not page.evaluate('STUDY.renderer.shadowMap.enabled')
        page.goto(served.url('study?quality=2d'), wait_until='domcontentloaded')
        page.wait_for_selector('#fallback', state='visible')
        assert 'Intake' in page.locator('#fallback').inner_text()
        assert not errors, errors
    print('test_study_live OK')


if __name__ == '__main__':
    main()
