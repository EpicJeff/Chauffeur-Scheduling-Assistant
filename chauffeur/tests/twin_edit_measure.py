"""Measure real editor releases in Chromium; all house writes stay in scratch data.

Run from chauffeur/: python -I tests/twin_edit_measure.py --runs 5 --tier high
"""
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))

import argparse
import math
import os
from statistics import median
import tempfile

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_edit_measure_')
os.environ.pop('HA_BASE_URL', None)

SERVER = ('lock', 'apply', 'normalize', 'round', 'read', 'response')
DETAIL = ('generate', 'batch', 'yard', 'materials', 'dispose', 'bake_stop')


class MeasurementSkipped(RuntimeError):
    """The optional browser or its Chromium download is absent."""


def _request(page, path, method='GET', body=None):
    return page.evaluate("""async ([path, method, body]) => {
        const response = await fetch(window.chfBase + path, {method,
            ...(body === null ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})});
        const data = await response.json();
        if (!response.ok) throw Error(data.error || data.detail || `HTTP ${response.status}`);
        return data;
    }""", [path, method, body])


def _state(page):
    return _request(page, 'api/house/editor/state')


def _movable_wall(plan):
    for building in plan.get('buildings', []):
        for level in building.get('levels', []):
            if level.get('state') == 'ghost':
                continue
            for wall in building.get('walls', []):
                if (wall.get('level') == level['id'] and wall.get('state') != 'ghost'
                        and math.dist(wall['from'], wall['to']) > .001):
                    return building, level, wall
    raise ValueError('The house has no building with a movable wall.')


def _middle(values):
    return median(values) if values else 0


def _summary(records, refused=None):
    totals = [r['total'] for r in records]
    return {'runs': len(records), 'refused': refused,
            'total': {'median': _middle(totals), 'min': min(totals, default=0), 'max': max(totals, default=0)},
            **{name: {'median': _middle([r[name] for r in records])}
               for name in ('request', 'parse', 'rebuild', 'first_frame')},
            **{group: {name: _middle([r.get(group, {}).get(name, 0) for r in records]) for name in names}
               for group, names in (('server', SERVER), ('detail', DETAIL))},
            'bytes': _middle([r['bytes'] for r in records])}


def _operation(page, operation):
    # Waiting on the kept record includes the observed rendered frame, beyond op().
    page.evaluate('window.__twinEditTiming.length = 0')
    error = page.evaluate("""async operation => {
        try { await window.__twinEditor.op(operation); return null; }
        catch (error) { return {text: error.message, status: error.status || null}; }
    }""", operation)
    if error:
        if error['status'] is None:
            raise RuntimeError(error['text'])
        return None, error['text']
    page.wait_for_function('window.__twinEditTiming.length > 0', timeout=60000)
    return page.evaluate('window.__twinEditTiming.at(-1)'), None


def _measure_operation(page, operation, distance, runs):
    def moved(sign):
        return {**operation, 'by': [sign * v for v in distance] if isinstance(distance, list) else sign * distance}

    # Warm-up returns to the start before the measured alternating sequence.
    for sign in (1, -1):
        _, refused = _operation(page, moved(sign))
        if refused:
            return _summary([], refused)
    records = []
    for index in range(runs):
        record, refused = _operation(page, moved(1 if index % 2 == 0 else -1))
        if refused:
            return _summary(records, refused)
        records.append(record)
    if runs % 2:
        _, refused = _operation(page, moved(-1))
        if refused:
            return _summary(records, refused)
    return _summary(records)


def _drag_frames(page, building, level, wall):
    import house_editor_model_harness as H

    H.choose_floor(page, f"{building['id']}:{level['id']}")
    centre = [(a + b) / 2 for a, b in zip(wall['from'], wall['to'])]
    H.look_down(page, building['id'], *centre)
    page.evaluate('([wall, building]) => window.__editor.clickPiece(wall, building)', [wall['id'], building['id']])
    H.settle(page)
    handles = H.editor_state(page, 'handles')
    for handle in handles:
        if handle['kind'] != 'wall' or handle['id'] != wall['id']:
            continue
        x, y = H.screen_of_world(page, *handle['at'], building['id'])
        visible = page.evaluate("""([x,y]) => {
            const canvas=window.__twin.renderer3.domElement, r=canvas.getBoundingClientRect();
            const hit=document.elementFromPoint(x,y);
            return x>=r.left && x+80<r.right && y>=r.top && y<r.bottom
                && (hit===canvas || !!hit?.closest('.editor-handles'));
        }""", [x, y])
        if not visible:
            continue
        frames = []
        page.mouse.move(x, y)
        page.mouse.down()
        try:
            for step in range(1, 21):
                page.mouse.move(x + 4 * step, y)
                H.settle(page, 1)
                value = H.editor_state(page, 'lastDragFrameMs')
                if isinstance(value, (int, float)) and math.isfinite(value):
                    frames.append(value)
        finally:
            page.keyboard.press('Escape')
            page.mouse.up()
            H.settle(page)
        return {'median': _middle(frames), 'max': max(frames, default=0), 'frames': len(frames)}
    return {'median': 0, 'max': 0, 'frames': 0}


def _measure_page(page, runs, tier, wall=None, house='fixture'):
    state = _state(page)
    building, level, chosen = _movable_wall(state['plan'])
    wall_id = wall if wall is not None else chosen['id']
    planting = (state['plan'].get('site', {}).get('planting') or [None])[0]
    safe = _request(page, 'api/house/editor/houses', 'POST', {'name': 'Before timing measurement'})['save']['id']
    try:
        counts = page.evaluate("""async () => {
            const v=window.__twin, counts=await v.afterNextRender();
            return {...counts, buildings:v.plan.buildings.length,
                levels:v.plan.buildings.reduce((n,b)=>n+b.levels.length,0)};
        }""")
        idle = page.evaluate('() => new Promise(resolve => requestAnimationFrame(a => requestAnimationFrame(b => resolve(b-a))))')
        ops = {'move_wall': _measure_operation(page, {'op': 'move_wall', 'building': building['id'], 'wall': wall_id}, .25, runs)}
        ops['move_site_item'] = (_measure_operation(page, {'op': 'move_site_item', 'list': 'planting', 'id': planting['id']}, [1, 0], runs)
                                 if planting else _summary([], 'no planting'))
        # A notice raised by an operation covers the scene; report its words
        # and close it, so the timings above are never lost to the drag step.
        alert = page.evaluate("""() => {
            const modal = document.getElementById('cc-alert-modal');
            if (!modal || !modal.classList.contains('flex')) return null;
            const text = modal.innerText.replace(/\\s+/g, ' ').trim();
            modal.classList.remove('flex'); modal.classList.add('hidden');
            return text;
        }""")
        drag = {'median': 0, 'max': 0, 'frames': 0}
        if wall_id == chosen['id']:
            from playwright.sync_api import Error
            try:
                drag = _drag_frames(page, building, level, chosen)
            except Error as error:
                drag['error'] = ' '.join(str(error).split())[:200]
        return {'house': house, 'tier': tier, 'runs': runs, 'scene': counts, 'ops': ops, 'alert': alert,
                'drag_frame_ms': drag, 'idle_frame_ms': {'median': idle}}
    finally:
        # Inverse moves cannot undo topology splits or source/person metadata.
        # A saved snapshot also survives pruning when a caller asks for many runs.
        _request(page, f'api/house/editor/houses/{safe}/load', 'POST')
        _request(page, f'api/house/editor/houses/{safe}', 'DELETE')


def _prepare(house_path):
    from services import storage, twin_house_saves, twin_store
    import house_editor_model_harness as H

    if not H.STATE.get('token'):
        H.seed()
    else:
        twin_store.push_round(H.household_plan(), 'build')
    # Editor pages may ask for the map key; measurement never reads credentials.
    from services import maps
    maps.get_mapbox_api_key = lambda: ''
    if house_path is not None:
        data = Path(house_path).read_bytes()
        uploaded = twin_house_saves.upload(data, H.PARENT['id'])
        twin_house_saves.load(uploaded['save']['id'])
    _movable_wall(twin_store.current())


def measure(house_path=None, runs=5, tier='high', wall=None):
    """Return millisecond medians for real operations on a temporary house."""
    if type(runs) is not int or runs < 1:
        raise ValueError('Runs must be a positive integer.')
    if tier not in ('low', 'medium', 'high', 'max'):
        raise ValueError('Choose a low, medium, high or max tier.')
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise MeasurementSkipped('playwright not installed; measurement skipped') from error
    _prepare(house_path)
    import house_editor_model_harness as H
    from live_app import live_app

    served = live_app()
    if served is None:
        raise MeasurementSkipped('playwright not installed; measurement skipped')
    try:
        browser = served.browser(launch_args=H.GPU_ARGS)
        with browser as page:
            H.open_editor(page, served, query=f'tier={tier}&test=1&timing=1&perf=1')
            return _measure_page(page, runs, tier, wall, 'file' if house_path is not None else 'fixture')
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise MeasurementSkipped('Chromium not installed; measurement skipped') from error
        raise
    finally:
        served.stop()
        # live_app's __enter__ can fail before its __exit__ owns the driver.
        if 'browser' in locals() and browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _table(result):
    print(f"{result['house']} house | tier {result['tier']} | {result['runs']} measured runs")
    print('operation          runs   total ms  request   parse  rebuild  frame')
    for name, op in result['ops'].items():
        if op['refused']:
            print(f"{name:18} {op['runs']:4}   refused: {op['refused']}")
        else:
            values = ' '.join(f"{op[field]['median']:8.1f}" for field in ('total', 'request', 'parse', 'rebuild', 'first_frame'))
            print(f"{name:18} {op['runs']:4} {values}")
    drag = result['drag_frame_ms']
    print(f"drag frame: {drag['median']:.1f} ms median, {drag['max']:.1f} ms max ({drag['frames']} frames)"
          + (f" | not measured: {drag['error']}" if drag.get('error') else ''))
    if result.get('alert'):
        print(f"notice shown: {result['alert']}")
    print(f"idle frame: {result['idle_frame_ms']['median']:.1f} ms")


def main(argv=None):
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--house', type=Path)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--tier', default='high', choices=('low', 'medium', 'high', 'max'))
    parser.add_argument('--wall')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args(argv)
    try:
        result = measure(args.house, args.runs, args.tier, args.wall)
    except MeasurementSkipped as error:
        print('  skip ', error)
        return 0
    except (ValueError, OSError) as error:
        print(' '.join(str(error).split()))
        return 2
    _table(result)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
