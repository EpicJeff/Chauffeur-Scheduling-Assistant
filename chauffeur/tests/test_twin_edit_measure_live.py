"""Real editor timing, restoration, CLI errors and optional-browser skips."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from twin_edit_measure import measure, MeasurementSkipped
import twin_edit_measure as measuring

ROOT = Path(__file__).resolve().parents[1]
RESULT = None


def fixture_result():
    global RESULT
    if RESULT is None:
        RESULT = measure(runs=1, tier='low')
    return RESULT


def fixture_run_reports_every_field():
    result = fixture_result()
    assert result['house'] == 'fixture' and result['tier'] == 'low' and result['runs'] == 1
    assert set(result['scene']) == {'meshes', 'draw_calls', 'triangles', 'buildings', 'levels'}
    assert all(isinstance(v, (int, float)) for v in result['scene'].values())
    assert set(result['ops']) == {'move_wall', 'move_site_item'}
    wall = result['ops']['move_wall']
    assert wall['refused'] is None and wall['runs'] == 1
    assert wall['total']['median'] > 0
    assert set(wall['total']) == {'median', 'min', 'max'}
    for name in ('request', 'parse', 'rebuild', 'first_frame'):
        assert isinstance(wall[name]['median'], (int, float)), name
    assert set(wall['server']) == {'lock', 'apply', 'normalize', 'round', 'read', 'response'}
    assert all(isinstance(v, (int, float)) for v in wall['server'].values())
    assert {'generate', 'batch', 'yard', 'materials', 'dispose', 'bake_stop'} <= set(wall['detail'])
    assert all(isinstance(v, (int, float)) for v in wall['detail'].values())
    assert wall['bytes'] > 0
    assert set(result['drag_frame_ms']) == {'median', 'max', 'frames'}
    assert result['idle_frame_ms']['median'] > 0


def house_is_unchanged_after():
    original = measuring._measure_page
    snapshots = []

    def observe(page, *args, **kwargs):
        # The seeded fixture is stored as drawn; loading a saved house derives
        # it. Settle through one save and load first so both reads are derived.
        safe = measuring._request(page, 'api/house/editor/houses', 'POST', {'name': 'Settle'})['save']['id']
        measuring._request(page, f'api/house/editor/houses/{safe}/load', 'POST')
        measuring._request(page, f'api/house/editor/houses/{safe}', 'DELETE')
        before = measuring._state(page)['plan']
        result = original(page, *args, **kwargs)
        after = measuring._state(page)['plan']
        snapshots.append((before, after))
        return result

    # Exercise an even run too: warm-up must not leave an extra forward move.
    with patch.object(measuring, '_measure_page', observe):
        measure(runs=2, tier='low')
    assert snapshots and all(before == after for before, after in snapshots)


def bad_file_exits_2():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', encoding='utf-8', delete=False) as handle:
        handle.write('{}')
        path = Path(handle.name)
    try:
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'tests/twin_edit_measure.py'),
                                 '--house', str(path)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 2, result
        lines = (result.stdout + result.stderr).strip().splitlines()
        assert len(lines) == 1 and 'Traceback' not in lines[0], lines
    finally:
        path.unlink(missing_ok=True)


def no_movable_wall_exits_2():
    document = {'format': 'chauffeur-house', 'format_version': 1, 'name': 'Empty',
                'model': {'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'buildings': [], 'site': {}},
                'state': {'place': {'buildings': [], 'lot': {}, 'photo_tags': {}},
                          'sources': [], 'page_roles': [], 'registrations': []}}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', encoding='utf-8', delete=False) as handle:
        json.dump(document, handle)
        path = Path(handle.name)
    try:
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'tests/twin_edit_measure.py'),
                                 '--house', str(path)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 2, result
        lines = (result.stdout + result.stderr).strip().splitlines()
        assert len(lines) == 1 and 'Traceback' not in lines[0], lines
        # The house loader refuses an empty house before the wall search runs.
        assert 'building' in lines[0].lower() or 'movable wall' in lines[0].lower(), lines
    finally:
        path.unlink(missing_ok=True)


def refusal_is_reported():
    result = measure(runs=1, tier='low', wall='no-such-wall')
    assert isinstance(result['ops']['move_wall']['refused'], str)
    assert result['ops']['move_wall']['refused']
    planting = result['ops']['move_site_item']
    assert planting['runs'] == 1 and planting['refused'] is None, planting
    assert planting['total']['median'] > 0


def guard_move_wall_under_bound():
    assert fixture_result()['ops']['move_wall']['total']['median'] < 2500


def missing_browser_skips():
    # Test both absence paths without depending on this machine's installation.
    code = """
import sys
from unittest.mock import patch
sys.path.insert(0, 'tests')
import twin_edit_measure as m
if sys.argv[1] == 'package':
    sys.modules['playwright.sync_api'] = None
    raise SystemExit(m.main(['--runs', '1', '--tier', 'low']))
else:
    from playwright.sync_api import BrowserType, Error
    with patch.object(BrowserType, 'launch', side_effect=Error("Executable doesn't exist at test-chromium")):
        raise SystemExit(m.main(['--runs', '1', '--tier', 'low']))
"""
    for missing in ('package', 'chromium'):
        result = subprocess.run([sys.executable, '-c', code, missing], capture_output=True,
                                text=True, timeout=90, env={**os.environ, 'HA_BASE_URL': ''})
        assert result.returncode == 0 and 'skip' in result.stdout.lower(), result
        assert 'Traceback' not in result.stdout + result.stderr, result


if __name__ == '__main__':
    tests = [fixture_run_reports_every_field, house_is_unchanged_after, bad_file_exits_2,
             no_movable_wall_exits_2, refusal_is_reported, guard_move_wall_under_bound, missing_browser_skips]
    passed = 0
    for test in tests:
        try:
            test()
        except MeasurementSkipped as error:
            print('  skip ', error)
            sys.exit(0)
        except Exception:
            traceback.print_exc(limit=6)
            print('FAIL', test.__name__)
        else:
            passed += 1
            print('ok  ', test.__name__)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
